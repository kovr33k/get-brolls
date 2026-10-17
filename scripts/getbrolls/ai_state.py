"""Beat-local AI alternatives, immutable production requests and human decisions."""

from __future__ import annotations

import copy
import hashlib
import json
import math
import re
import uuid
from pathlib import Path

from .ledger import digest
from .models import now
from .runtime import redact, scrub_home

IDENTIFIER = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]{0,79}\Z")
SHA256 = re.compile(r"[0-9a-f]{64}\Z")
ALTERNATIVE_COUNT = 3
MAX_BEATS = 1000
MAX_PROMPT = 32000
MODES = ("economy", "images")
ROUTES = ("gpt-subscription", "grok-subscription", "openrouter")
JOB_STATES = (
    "awaiting_confirmation",
    "queued",
    "running",
    "remote_pending",
    "downloading",
    "complete",
    "failed",
    "unknown",
)
SUBMIT_OUTCOMES = ("not_sent", "accepted", "rejected", "unknown")
IN_FLIGHT = ("queued", "running", "remote_pending", "downloading")
_ABS_PATH = re.compile(
    r"(?i)(?:(?:[A-Za-z]:|\\\\)[\\/][^\s\"'<>]+|"
    r"/(?:home|Users|tmp|var|private|opt|root|usr)[^\s\"'<>]*|"
    r"~[\\/][^\s\"'<>]+)"
)
_SIGNED = re.compile(
    r"(?i)\b(?:x-amz-signature|x-amz-credential|x-amz-security-token|signature|sig|token|key-pair-id)\s*[=:]\s*[^\s&\"'<>]+"
)


def fingerprint(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False, allow_nan=False).encode()).hexdigest()


def text(value, label, limit=MAX_PROMPT):
    if not isinstance(value, str) or not value.strip() or len(value) > limit or "\0" in value:
        raise ValueError(f"{label} must be nonempty text up to {limit} characters.")
    return value.strip()


def identifier(value, label="Identifier"):
    if not isinstance(value, str) or not IDENTIFIER.fullmatch(value):
        raise ValueError(f"{label} must contain 1-80 letters, numbers, underscores or hyphens.")
    return value


def empty_ai():
    return {
        "schema_version": 1,
        "style": None,
        "plan": None,
        "beats": {},
        "references": {},
        "jobs": {},
        "versions": {},
    }


def state(data):
    return data.setdefault("ai", empty_ai())


def _sha(value):
    return isinstance(value, str) and bool(SHA256.fullmatch(value))


def _validate_beat(key, beat):
    if not isinstance(beat, dict) or beat.get("id") != identifier(key):
        raise ValueError("Invalid AI beat identity.")
    for name in ("text", "purpose", "chapter_context"):
        text(beat.get(name), "AI beat " + name)
    if beat.get("mode") not in MODES or not _sha(beat.get("fingerprint")):
        raise ValueError("Invalid AI beat mode or fingerprint.")
    alternatives = beat.get("alternatives")
    if not isinstance(alternatives, list) or len(alternatives) != ALTERNATIVE_COUNT:
        raise ValueError("An AI beat requires exactly three alternatives.")
    ids = set()
    for alternative in alternatives:
        if not isinstance(alternative, dict):
            raise ValueError("Invalid AI alternative.")
        ids.add(identifier(alternative.get("id"), "Alternative id"))
        text(alternative.get("description"), "Alternative description")
    if len(ids) != ALTERNATIVE_COUNT or (beat.get("selected") is not None and beat["selected"] not in ids):
        raise ValueError("Invalid AI alternative selection.")
    if not isinstance(beat.get("references"), list) or not isinstance(beat.get("images"), dict):
        raise ValueError("Invalid AI beat references or retained images.")


def _validate_job(key, job, ai):
    if not isinstance(job, dict) or job.get("id") != identifier(key, "Job id"):
        raise ValueError("Invalid AI job identity.")
    request = job.get("request")
    if not isinstance(request, dict) or job.get("state") not in JOB_STATES:
        raise ValueError("Invalid AI job request or state.")
    if request.get("beat") not in ai["beats"] or request.get("route") not in ROUTES:
        raise ValueError("Invalid AI job beat or route.")
    if request.get("kind") not in ("image", "video") or fingerprint(request) != job.get("fingerprint"):
        raise ValueError("AI job inputs changed after being frozen.")
    if type(job.get("correction_count")) is not int or job["correction_count"] not in (0, 1):
        raise ValueError("Invalid AI correction allowance.")
    confirmation = job.get("confirmation")
    if confirmation is not None and (
        not isinstance(confirmation, dict) or confirmation.get("fingerprint") != job["fingerprint"]
    ):
        raise ValueError("AI confirmation does not match its paid launch.")
    if request["route"] == "openrouter" and job["state"] != "awaiting_confirmation" and confirmation is None:
        raise ValueError("Paid AI job is missing explicit launch confirmation.")
    outcome = job.get("submit_outcome")
    if outcome is not None and outcome not in SUBMIT_OUTCOMES:
        raise ValueError("Invalid AI job submit outcome.")
    if outcome == "unknown" and job["state"] not in ("unknown", "failed", "complete"):
        raise ValueError("An unknown AI submit must stay unknown until it is reconciled.")


def _validate_version(key, version, ai):  # noqa: C901 - identity, media path and approval checks stay together.
    if not isinstance(version, dict) or version.get("id") != identifier(key, "Version id"):
        raise ValueError("Invalid AI version identity.")
    if version.get("beat") not in ai["beats"] or version.get("kind") not in ("image", "video", "sequence"):
        raise ValueError("Invalid AI version beat or kind.")
    if not _sha(version.get("sha256")) or not _sha(version.get("inputs")):
        raise ValueError("Invalid AI version fingerprint.")
    if version.get("original_sha256") is not None and not _sha(version.get("original_sha256")):
        raise ValueError("Invalid AI original media fingerprint.")
    for name in ("width", "height"):
        if version.get(name) is not None and (type(version.get(name)) is not int or version[name] <= 0):
            raise ValueError("Invalid AI still measurements.")
    path = version.get("path")
    if not isinstance(path, str) or not path.startswith(("previews/ai-", "clips/ai-")):
        raise ValueError("Invalid AI version media path.")
    if "\\" in path or any(p in ("", ".", "..") for p in path.split("/")):
        raise ValueError("Unsafe AI version media path.")
    approval = version.get("approval")
    if not isinstance(approval, dict) or approval.get("state") not in ("pending", "approved", "changes", "rejected"):
        raise ValueError("Invalid AI version approval.")
    if approval["state"] == "approved" and approval.get("signature") != version_signature(version):
        raise ValueError("AI approved version changed.")


def validate_ai(data):
    ai = data.get("ai")
    if ai is None:
        return
    if not isinstance(ai, dict) or type(ai.get("schema_version")) is not int or ai["schema_version"] != 1:
        raise ValueError("Invalid or unsupported AI production records; preserve the manifest.")
    for name in ("beats", "references", "jobs", "versions"):
        if not isinstance(ai.get(name), dict):
            raise ValueError("Invalid AI record collection: " + name)
    for key, beat in ai["beats"].items():
        _validate_beat(key, beat)
    for key, job in ai["jobs"].items():
        _validate_job(key, job, ai)
    for key, version in ai["versions"].items():
        _validate_version(key, version, ai)


def beat_for(ledger, beat_id, expected=None):
    beat = (ledger.data.get("ai") or {}).get("beats", {}).get(beat_id)
    if not isinstance(beat, dict) or not beat.get("active"):
        raise ValueError("This AI beat is not active in the current scenario plan.")
    if expected is not None and expected != beat["fingerprint"]:
        raise ValueError("This beat's scenario or style changed. Review its current alternatives first.")
    return beat


def _plan_entry(entry, scenario):
    if not isinstance(entry, dict) or entry.get("route") not in ("broll", "graphics", "ai"):
        raise ValueError("Each narrative beat needs a broll, graphics or ai route.")
    result = {"id": identifier(entry.get("id"), "Beat id"), "route": entry["route"]}
    result["text"] = text(entry.get("text"), "Original beat text")
    if result["text"] not in scenario:
        raise ValueError("Beat text must occur in the original scenario; do not rewrite narration.")
    result["title"] = text(entry.get("title") or result["id"], "Beat title", 200)
    result["chapter"] = text(entry.get("chapter") or "main", "Chapter", 200)
    return result


def _alternatives(entries):
    if not isinstance(entries, list) or len(entries) != ALTERNATIVE_COUNT:
        raise ValueError("Provide three distinct scene alternatives for each AI beat.")
    result = []
    for index, value in enumerate(entries, 1):
        entry = {"description": value} if isinstance(value, str) else value
        if not isinstance(entry, dict):
            raise ValueError("Each alternative needs a scene description.")
        result.append(
            {
                "id": identifier(entry.get("id") or f"option-{index}", "Alternative id"),
                "description": text(entry.get("description"), "Scene description"),
                "motion": str(entry.get("motion") or ""),
            }
        )
    if (
        len({r["id"] for r in result}) != ALTERNATIVE_COUNT
        or len({r["description"].casefold() for r in result}) != ALTERNATIVE_COUNT
    ):
        raise ValueError("Three duplicate alternatives do not provide a scene choice.")
    return result


def import_plan(ledger, payload):
    """Record the managing agent's routing, never run a second scenario planner."""
    if not isinstance(payload, dict):
        raise ValueError("The AI plan must be a JSON object.")
    scenario = text(payload.get("scenario"), "Original scenario", 500000)
    style = text(payload.get("style"), "Agreed AI visual style")
    entries = payload.get("beats")
    if not isinstance(entries, list) or not entries or len(entries) > MAX_BEATS:
        raise ValueError("Provide 1-1000 narrative beats.")
    working = copy.deepcopy(ledger.data.get("ai") or empty_ai())
    routing = []
    seen = set()
    for entry in entries:
        record = _plan_entry(entry, scenario)
        if record["id"] in seen:
            raise ValueError("Narrative beat ids must be unique.")
        seen.add(record["id"])
        routing.append(record)
        if record["route"] == "ai":
            _register_beat(working, entry, record, style)
    active = {r["id"] for r in routing if r["route"] == "ai"}
    for key, beat in working["beats"].items():
        beat["active"] = key in active
    working["style"] = {"prompt": style, "fingerprint": fingerprint(style)}
    working["plan"] = {"scenario": scenario, "sha256": fingerprint(scenario), "routing": routing}
    ledger.data["ai"] = working
    ledger.save("ai-plan")
    return {"beats": len(routing), "ai_beats": len(active), "default_mode": "economy"}


def _register_beat(working, entry, record, style):
    alternatives = _alternatives(entry.get("alternatives"))
    purpose = text(entry.get("purpose"), "Visual purpose")
    context = text(entry.get("chapter_context") or record["text"], "Chapter context")
    inputs = fingerprint([record["text"], record["chapter"], context, purpose, style, alternatives])
    old = working["beats"].get(record["id"], {})
    unchanged = old.get("fingerprint") == inputs
    working["beats"][record["id"]] = {
        **record,
        "purpose": purpose,
        "chapter_context": context,
        "alternatives": alternatives,
        "fingerprint": inputs,
        "mode": old.get("mode", "economy"),
        "selected": old.get("selected") if unchanged else None,
        "comment": old.get("comment", "") if unchanged else "",
        "references": old.get("references", []),
        "images": old.get("images", {}),
        "sequence": old.get("sequence") if unchanged else None,
        "timing": old.get("timing") if unchanged else None,
        "active": True,
    }


def _omitted(payload, key, current):
    """A missing key or JSON null keeps the saved value. An explicit value replaces it."""
    if not isinstance(payload, dict) or key not in payload or payload.get(key) is None:
        return current
    return payload[key]


def select(ledger, payload):
    beat = beat_for(ledger, payload.get("beat"), payload.get("expected"))
    mode = _omitted(payload, "mode", beat.get("mode") or "economy")
    selected = _omitted(payload, "alternative", beat.get("selected"))
    if mode not in MODES or (selected is not None and selected not in {r["id"] for r in beat["alternatives"]}):
        raise ValueError("Select an existing scene alternative and a supported comparison mode.")
    comment = _omitted(payload, "comment", beat.get("comment") if isinstance(beat.get("comment"), str) else "")
    if not isinstance(comment, str) or len(comment) > MAX_PROMPT or "\0" in comment:
        raise ValueError("Scene comments must be text up to 32000 characters.")
    beat.update(mode=mode, selected=selected, comment=comment)
    ledger.save("ai-select")
    return copy.deepcopy(beat)


def new_job(ledger, request, nonce, *, correction_of=None):
    ai = state(ledger.data)
    nonce = text(nonce, "Request identity", 160)
    prior = next((j for j in ai["jobs"].values() if j["nonce"] == nonce), None)
    frozen = fingerprint(request)
    if prior:
        if prior["fingerprint"] != frozen:
            raise ValueError("This request identity already belongs to different frozen inputs.")
        return prior
    if request.get("route") not in ROUTES or request.get("kind") not in ("image", "video"):
        raise ValueError("Unsupported AI production route or operation.")
    beat_for(ledger, request.get("beat"), request.get("inputs"))
    parent = ai["jobs"].get(correction_of) if correction_of else None
    if correction_of and (not parent or parent["correction_count"] or parent.get("correction_of")):
        raise ValueError("This operation has already used its one corrective generation.")
    job_id = "job-" + uuid.uuid4().hex
    job = {
        "id": job_id,
        "nonce": nonce,
        "request": copy.deepcopy(request),
        "fingerprint": frozen,
        "state": "awaiting_confirmation" if request["route"] == "openrouter" else "queued",
        "created_at": now(),
        "confirmation": None,
        "correction_count": 0,
        "correction_of": correction_of,
        "remote": None,
        "result": None,
        "error": None,
        "submit_outcome": "not_sent",
    }
    if parent:
        parent["correction_count"] = 1
    ai["jobs"][job_id] = job
    return job


def confirm(ledger, job_ids, signatures, by):
    ai = state(ledger.data)
    by = text(by, "Reviewer", 200)
    if not isinstance(job_ids, list) or not job_ids or not isinstance(signatures, dict):
        raise ValueError("Confirm the identified paid launch and its frozen inputs.")
    chosen = []
    for key in job_ids:
        job = ai["jobs"].get(key)
        if not job or job["request"]["route"] != "openrouter" or signatures.get(key) != job["fingerprint"]:
            raise ValueError("Paid launch confirmation is missing or refers to changed inputs.")
        if job["state"] != "awaiting_confirmation":
            raise ValueError("This paid launch was already confirmed or started.")
        beat_for(ledger, job["request"]["beat"], job["request"]["inputs"])
        chosen.append(job)
    for job in chosen:
        job["confirmation"] = {"by": by, "at": now(), "fingerprint": job["fingerprint"]}
        job["state"] = "queued"
    ledger.save("ai-confirm-api")
    return {"jobs": [j["id"] for j in chosen]}


def version_signature(version):
    return fingerprint({key: value for key, value in version.items() if key not in ("approval", "delivery")})


def checked_version(ledger, version_id, *, approved=False, kind=None):
    from .narration import _confine_existing_file

    version = (ledger.data.get("ai") or {}).get("versions", {}).get(version_id)
    if not version or (kind is not None and version["kind"] != kind):
        raise ValueError("Select an existing AI result of the required type.")
    beat_for(ledger, version["beat"], version["inputs"])
    path = _confine_existing_file(ledger.root, version["path"], ("previews/", "clips/"))
    if digest(path) != version["sha256"]:
        raise ValueError("The saved AI media changed; its previous approval cannot be reused.")
    approval = version["approval"]
    if approved and (approval["state"] != "approved" or approval.get("signature") != version_signature(version)):
        raise ValueError("Approve this exact AI image before video production.")
    return version, path


def review(ledger, payload):
    version, _path = checked_version(ledger, payload.get("version"))
    if payload.get("signature") != version_signature(version):
        raise ValueError("The displayed AI version changed; review the exact current result.")
    decision = payload.get("decision")
    if decision not in ("approved", "changes", "rejected"):
        raise ValueError("Choose an explicit human approval, changes request or rejection.")
    by = text(payload.get("by"), "Reviewer", 200)
    version["approval"] = {
        "state": decision,
        "by": by,
        "at": now(),
        "signature": version_signature(version),
        "comment": str(payload.get("comment") or "")[:32000],
    }
    ledger.save("ai-review")
    return {"version": version["id"], "decision": decision}


def finite(value, label):
    if type(value) not in (int, float) or not math.isfinite(value) or value < 0:
        raise ValueError(label + " must be a finite nonnegative number.")
    return float(value)


def still_prompt(beat, alternative, style_prompt):
    comment = str(beat.get("comment") or "").strip()
    parts = [
        "Generate exactly one still image with the image generation tool. Do not produce video.",
        "Agreed visual style: " + style_prompt,
        "Scene: " + alternative["description"],
        "Visual purpose: " + beat["purpose"],
        "Original scenario passage: " + beat["text"],
    ]
    if comment:
        parts.append("Editor comment: " + comment)
    parts.append("The still is generated illustration, not documentary evidence.")
    return "\n".join(parts)


def launch_still(ledger, payload, nonce):
    beat = beat_for(ledger, payload.get("beat"), payload.get("expected") or payload.get("inputs"))
    if beat.get("mode") != "economy":
        raise ValueError("Three-image comparison is not available yet. Economy mode generates one still.")
    selected = payload.get("alternative") or beat.get("selected")
    ids = {row["id"] for row in beat["alternatives"]}
    if selected not in ids:
        raise ValueError("Select a scene alternative before generating a still.")
    alternative = next(row for row in beat["alternatives"] if row["id"] == selected)
    style = (ledger.data.get("ai") or {}).get("style") or {}
    style_prompt = text(style.get("prompt"), "Agreed AI visual style") if style.get("prompt") else ""
    if not style_prompt:
        raise ValueError("Agree an AI visual style before generating a still.")
    comment = beat.get("comment") or ""
    if payload.get("comment") is not None:
        comment = payload.get("comment")
        if not isinstance(comment, str) or len(comment) > MAX_PROMPT or "\0" in comment:
            raise ValueError("Scene comments must be text up to 32000 characters.")
        beat["comment"] = comment
        beat["selected"] = selected
    request = {
        "beat": beat["id"],
        "inputs": beat["fingerprint"],
        "kind": "image",
        "route": "gpt-subscription",
        "alternative": selected,
        "description": alternative["description"],
        "comment": comment,
        "style": style_prompt,
        "style_fingerprint": style.get("fingerprint") or fingerprint(style_prompt),
        "mode": "economy",
        "prompt": still_prompt(beat, alternative, style_prompt),
    }
    return new_job(ledger, request, nonce)


def mark_job(ledger, job_id, **fields):
    job = (ledger.data.get("ai") or {}).get("jobs", {}).get(job_id)
    if not job:
        raise ValueError("This AI job is not in the current project.")
    for key, value in fields.items():
        job[key] = value
    return job


def attach_result(ledger, job, version):
    """Attach one still to one job. A second completion keeps the first result."""
    ai = state(ledger.data)
    ident = identifier(version["id"], "Version id")
    current_id = job.get("result")
    if current_id:
        kept = ai["versions"].get(current_id)
        if isinstance(kept, dict):
            job["state"] = "complete"
            job["error"] = None
            return kept
    existing = ai["versions"].get(ident)
    if isinstance(existing, dict):
        same = existing.get("sha256") == version.get("sha256") and existing.get("original_sha256") == version.get(
            "original_sha256"
        )
        if not same:
            raise ValueError("This job already has a different saved still.")
        job["state"] = "complete"
        job["result"] = ident
        job["error"] = None
        return existing
    ai["versions"][ident] = version
    job["state"] = "complete"
    job["result"] = ident
    job["error"] = None
    beat = ai["beats"].get(job["request"]["beat"])
    if isinstance(beat, dict):
        images = beat.setdefault("images", {})
        images[ident] = {"path": version["path"], "sha256": version["sha256"]}
    return version


def sanitize_public_text(value, limit=500):
    """Strip secrets, signed URLs and absolute home/work paths from public AI text."""
    text = redact(str(value or ""), limit=None)
    text = scrub_home(text)
    text = _SIGNED.sub("[REDACTED]", text)
    try:
        work = str(Path.cwd())
        if work and work not in {"", "/", "\\"}:
            text = text.replace(work, "[path]")
            text = text.replace(json.dumps(work)[1:-1], "[path]")
    except (OSError, RuntimeError):
        pass
    text = _ABS_PATH.sub("[path]", text)
    return text[:limit]


def public_job(job):
    request = job.get("request") or {}
    error = job.get("error")
    message = str(error.get("message") or error.get("code") or "") if isinstance(error, dict) else str(error or "")
    remote = job.get("remote") if isinstance(job.get("remote"), dict) else None
    return {
        "id": job.get("id"),
        "state": job.get("state"),
        "submit_outcome": job.get("submit_outcome"),
        "beat": request.get("beat"),
        "alternative": request.get("alternative"),
        "kind": request.get("kind"),
        "route": request.get("route"),
        "result": job.get("result"),
        "error": sanitize_public_text(message) or None,
        "remote": {"threadId": remote.get("threadId")} if remote and remote.get("threadId") else None,
    }


def public_version(version):
    return {
        "id": version.get("id"),
        "beat": version.get("beat"),
        "kind": version.get("kind"),
        "path": version.get("path"),
        "sha256": version.get("sha256"),
        "original_sha256": version.get("original_sha256"),
        "width": version.get("width"),
        "height": version.get("height"),
        "codec": version.get("codec"),
        "job": version.get("job"),
        "signature": version_signature(version),
        "approval": (version.get("approval") or {}).get("state"),
    }
