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
FULL_HD_WIDTH = 1920
FULL_HD_HEIGHT = 1080
MAX_BEATS = 1000
MAX_PROMPT = 32000
MODES = ("economy", "images")
ROUTES = ("gpt-subscription", "grok-subscription", "openrouter")
SUBSCRIPTION_ROUTES = ("gpt-subscription", "grok-subscription")
SHARED_QUALITY = "agreed"
GROUP_NONCE_LIMIT = 70
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


def quality_text(style):
    """Economy and comparison share one agreed quality. A missing value stays the shared default."""
    if not isinstance(style, dict) or style.get("quality") in (None, ""):
        return SHARED_QUALITY
    return text(style.get("quality"), "Agreed AI quality", 2000)


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
        "groups": {},
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
    if beat.get("timing") is not None and not isinstance(beat.get("timing"), dict):
        raise ValueError("Invalid AI beat timing.")


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
    _validate_job_group(key, request, ai)


def _validate_job_group(key, request, ai):
    group_id = request.get("group")
    if group_id is None:
        return
    identifier(group_id, "Group id")
    raw_groups = ai.get("groups")
    groups = raw_groups if isinstance(raw_groups, dict) else {}
    group = groups.get(group_id)
    members = group.get("jobs") if isinstance(group, dict) else None
    if not isinstance(members, list) or key not in members:
        raise ValueError("AI job is not a member of its comparison group.")


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
    if version.get("kind") == "video":
        _validate_video_version(version, path)


def _validate_video_version(version, path):
    if not path.startswith("clips/ai-"):
        raise ValueError("Invalid AI video path.")
    if version.get("native_full_hd") is not True:
        return
    width = version.get("width") or 0
    height = version.get("height") or 0
    if version.get("resolution") in {"480p", "720p"} or width < FULL_HD_WIDTH or height < FULL_HD_HEIGHT:
        raise ValueError("Native 480p or 720p video is not native Full HD.")


def _validate_groups(ai):
    groups = ai.get("groups", None)
    if groups is None:
        return
    if not isinstance(groups, dict):
        raise ValueError("Invalid AI comparison groups.")
    seen = set()
    for key, group in groups.items():
        jobs, alt_ids = _validate_group_scope(key, group)
        _validate_group_members(ai, key, jobs, alt_ids, seen)


def _validate_group_scope(key, group):
    if not isinstance(group, dict) or group.get("id") != identifier(key, "Group id"):
        raise ValueError("Invalid AI comparison group identity.")
    jobs = group.get("jobs")
    if not isinstance(jobs, list) or len(jobs) != ALTERNATIVE_COUNT or len(set(jobs)) != ALTERNATIVE_COUNT:
        raise ValueError("A comparison group freezes exactly three still jobs.")
    scope = group.get("scope")
    if (
        not isinstance(scope, dict)
        or fingerprint(scope) != group.get("fingerprint")
        or scope.get("outputs") != ALTERNATIVE_COUNT
    ):
        raise ValueError("Comparison group inputs changed after being frozen.")
    text(group.get("nonce"), "Request identity", GROUP_NONCE_LIMIT)
    return jobs, _group_alternatives(scope)


def _group_alternatives(scope):
    alternatives = scope.get("alternatives")
    if not isinstance(alternatives, list) or len(alternatives) != ALTERNATIVE_COUNT:
        raise ValueError("Comparison group scope is missing its three treatments.")
    alt_ids = []
    for row in alternatives:
        if not isinstance(row, dict):
            raise ValueError("Comparison group scope is missing its three treatments.")
        alt_ids.append(identifier(row.get("id"), "Alternative id"))
    if len(set(alt_ids)) != ALTERNATIVE_COUNT:
        raise ValueError("Comparison group treatments must stay distinct.")
    return alt_ids


def _validate_group_members(ai, key, jobs, alt_ids, seen):
    for job_id, alt_id in zip(jobs, alt_ids, strict=True):
        job = ai["jobs"].get(job_id)
        request = job.get("request") if isinstance(job, dict) else None
        if not isinstance(request, dict) or request.get("group") != key or request.get("alternative") != alt_id:
            raise ValueError("Comparison group does not match its frozen jobs.")
        if job_id in seen:
            raise ValueError("A still job cannot belong to two comparison groups.")
        seen.add(job_id)


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
    _validate_native_video(ai)
    _validate_groups(ai)


def _validate_native_video(ai):
    raw = ai.get("native_video", None)
    if raw is None:
        return
    if not isinstance(raw, dict):
        raise ValueError("Invalid native video setup.")
    text(raw.get("model"), "Native model", 200)
    if raw.get("tool") not in ("reference_to_video", "image_to_video"):
        raise ValueError("Invalid native video tool.")
    if raw.get("route") not in (None, "grok-subscription"):
        raise ValueError("Native video setup cannot switch billing route.")
    if raw.get("capability") not in (None, "unverified"):
        raise ValueError("Native video capability is not established.")


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
    if "native_video" in payload:
        from .ai_timing import explicit_native_video

        chosen = explicit_native_video(payload.get("native_video"))
        if chosen is None:
            working.pop("native_video", None)
        else:
            working["native_video"] = chosen
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
    _require_full_groups(ai, chosen)
    for job in chosen:
        job["confirmation"] = {"by": by, "at": now(), "fingerprint": job["fingerprint"]}
        job["state"] = "queued"
    ledger.save("ai-confirm-api")
    return {"jobs": [j["id"] for j in chosen]}


def _require_full_groups(ai, chosen):
    """A paid comparison confirms every frozen member or none. Ungrouped jobs stay single-job confirms."""
    groups = ai.get("groups") if isinstance(ai.get("groups"), dict) else {}
    chosen_ids = {job["id"] for job in chosen}
    required = set()
    for job in chosen:
        group_id = (job.get("request") or {}).get("group")
        if not group_id:
            continue
        group = groups.get(group_id)
        members = group.get("jobs") if isinstance(group, dict) else None
        if not isinstance(members, list) or job["id"] not in members:
            raise ValueError("Paid comparison confirmation must name the full frozen set.")
        required.update(members)
    if required - chosen_ids:
        raise ValueError("Paid comparison confirmation must name every still in the frozen set.")


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


def still_prompt(beat, alternative, style_prompt, quality=SHARED_QUALITY):
    comment = str(beat.get("comment") or "").strip()
    parts = [
        "Generate exactly one still image with the image generation tool. Do not produce video.",
        "Agreed visual style: " + style_prompt,
        "Agreed quality: " + quality,
        "Scene: " + alternative["description"],
        "Visual purpose: " + beat["purpose"],
        "Original scenario passage: " + beat["text"],
    ]
    motion = str(alternative.get("motion") or "").strip()
    if motion:
        parts.append("Motion note: " + motion)
    if comment:
        parts.append("Editor comment: " + comment)
    parts.append("The still is generated illustration, not documentary evidence.")
    return "\n".join(parts)


def _agreed_style(ledger):
    style = (ledger.data.get("ai") or {}).get("style") or {}
    if not isinstance(style, dict):
        style = {}
    style_prompt = text(style.get("prompt"), "Agreed AI visual style") if style.get("prompt") else ""
    if not style_prompt:
        raise ValueError("Agree an AI visual style before generating a still.")
    return style, style_prompt, quality_text(style)


def _launch_comment(beat, payload):
    comment = beat.get("comment") or ""
    if not isinstance(payload, dict) or payload.get("comment") is None:
        return comment
    comment = payload.get("comment")
    if not isinstance(comment, str) or len(comment) > MAX_PROMPT or "\0" in comment:
        raise ValueError("Scene comments must be text up to 32000 characters.")
    return comment


def _image_route(payload, *, allow_openrouter):
    route = payload.get("route") or "gpt-subscription"
    allowed = ROUTES if allow_openrouter else SUBSCRIPTION_ROUTES
    if route not in allowed:
        raise ValueError("Unsupported AI still route.")
    model = None
    if route == "grok-subscription":
        model = text(payload.get("model"), "Native model", 200)
    elif payload.get("model") not in (None, ""):
        raise ValueError("This still route does not take a separate native model.")
    return route, model


def _session_id(nonce, material):
    return str(uuid.UUID(fingerprint({"nonce": nonce, "material": material})[:32]))


def _ordinary_references(ledger, beat, nonce, route):
    """Beat-level guidance frozen into this launch. Empty when the beat has none."""
    from .ai_references import freeze_ordinary_guidance

    return freeze_ordinary_guidance(ledger, beat, nonce, route)


def _guided_prompt(prompt, references):
    if not references:
        return prompt
    from .ai_references import reference_prompt_lines

    lines = reference_prompt_lines(references)
    if not lines:
        return prompt
    return prompt + "\n" + "\n".join(lines)


def _apply_comment(beat, payload, comment, selected=None):
    if isinstance(payload, dict) and payload.get("comment") is not None:
        beat["comment"] = comment
    if selected is not None:
        beat["selected"] = selected


def launch_still(ledger, payload, nonce):
    beat = beat_for(ledger, payload.get("beat"), payload.get("expected") or payload.get("inputs"))
    if beat.get("mode") != "economy":
        raise ValueError(
            "Images mode generates three stills through an explicit three-output launch. "
            "Economy mode generates one still."
        )
    selected = payload.get("alternative") or beat.get("selected")
    ids = {row["id"] for row in beat["alternatives"]}
    if selected not in ids:
        raise ValueError("Select a scene alternative before generating a still.")
    alternative = next(row for row in beat["alternatives"] if row["id"] == selected)
    style, style_prompt, quality = _agreed_style(ledger)
    route, model = _image_route(payload, allow_openrouter=False)
    comment = _launch_comment(beat, payload)
    nonce = text(nonce, "Request identity", 160)
    references = _ordinary_references(ledger, beat, nonce, route)
    _apply_comment(beat, payload, comment, selected)
    request = {
        "beat": beat["id"],
        "inputs": beat["fingerprint"],
        "kind": "image",
        "route": route,
        "alternative": selected,
        "description": alternative["description"],
        "comment": comment,
        "style": style_prompt,
        "style_fingerprint": style.get("fingerprint") or fingerprint(style_prompt),
        "quality": quality,
        "mode": "economy",
        "prompt": _guided_prompt(
            still_prompt({**beat, "comment": comment}, alternative, style_prompt, quality), references
        ),
    }
    if references:
        request["references"] = references
    if model:
        request["model"] = model
        request["tool"] = "image_gen"
        request["session_id"] = _session_id(nonce, request["style_fingerprint"])
    return new_job(ledger, request, nonce)


def _comparison_scope(beat, agreed, comment, provider, references=None):
    route, model = provider
    _style, style_prompt, quality = agreed
    scope = {
        "beat": beat["id"],
        "inputs": beat["fingerprint"],
        "mode": "images",
        "outputs": ALTERNATIVE_COUNT,
        "route": route,
        "quality": quality,
        "style": style_prompt,
        "style_fingerprint": _style.get("fingerprint") or fingerprint(style_prompt),
        "comment": comment,
        "alternatives": [{"id": row["id"], "description": row["description"]} for row in beat["alternatives"]],
    }
    if references:
        scope["references"] = references
    if model:
        scope["model"] = model
        scope["tool"] = "image_gen"
    return scope


def _comparison_request(beat, row, scope, binding):
    comment = scope["comment"]
    quality = scope["quality"]
    model = scope.get("model")
    references = scope.get("references") if isinstance(scope.get("references"), list) else []
    request = {
        "beat": beat["id"],
        "inputs": beat["fingerprint"],
        "kind": "image",
        "route": scope["route"],
        "alternative": row["id"],
        "description": row["description"],
        "comment": comment,
        "style": scope["style"],
        "style_fingerprint": scope["style_fingerprint"],
        "quality": quality,
        "mode": "images",
        "outputs": ALTERNATIVE_COUNT,
        "group": binding["group_id"],
        "slot": binding["slot"],
        "prompt": _guided_prompt(still_prompt({**beat, "comment": comment}, row, scope["style"], quality), references),
    }
    if references:
        request["references"] = references
    if model:
        request["model"] = model
        request["tool"] = "image_gen"
        request["session_id"] = _session_id(f"{binding['nonce']}:{row['id']}", binding["group_id"])
    return request


def _saved_comparison(ai, nonce, scope_fingerprint):
    groups = ai.get("groups") or {}
    prior = next((group for group in groups.values() if isinstance(group, dict) and group.get("nonce") == nonce), None)
    if not prior:
        return None
    if prior.get("fingerprint") != scope_fingerprint:
        raise ValueError("This request identity already belongs to different frozen inputs.")
    jobs = []
    for job_id in prior.get("jobs") or []:
        job = ai["jobs"].get(job_id)
        if not job:
            raise ValueError("The saved comparison group is missing a still job.")
        jobs.append(job)
    return {"group": prior, "jobs": jobs}


def _freeze_comparison(ledger, beat, scope, nonce):
    ai = state(ledger.data)
    groups = ai.setdefault("groups", {})
    scope_fingerprint = fingerprint(scope)
    group_id = "group-" + fingerprint({"nonce": nonce, "scope": scope_fingerprint})[:24]
    before = set(ai["jobs"])
    fresh = []
    try:
        jobs = []
        for slot, row in enumerate(beat["alternatives"], 1):
            request = _comparison_request(beat, row, scope, {"group_id": group_id, "slot": slot, "nonce": nonce})
            job = new_job(ledger, request, f"{nonce}:{row['id']}")
            if job["request"].get("group") != group_id:
                raise ValueError("The comparison child does not match the frozen group.")
            if job["id"] not in before:
                fresh.append(job["id"])
            jobs.append(job)
        group = {
            "id": group_id,
            "nonce": nonce,
            "fingerprint": scope_fingerprint,
            "scope": scope,
            "jobs": [job["id"] for job in jobs],
        }
        groups[group_id] = group
    except Exception:
        for job_id in fresh:
            ai["jobs"].pop(job_id, None)
        groups.pop(group_id, None)
        raise
    return {"group": group, "jobs": jobs}


def launch_comparison(ledger, payload, nonce):
    """Freeze exactly three still jobs. The caller must pass outputs=3; mode selection alone does not launch."""
    if (
        not isinstance(payload, dict)
        or type(payload.get("outputs")) is not int
        or payload.get("outputs") != ALTERNATIVE_COUNT
    ):
        raise ValueError("Three-image comparison launches exactly three stills.")
    beat = beat_for(ledger, payload.get("beat"), payload.get("expected") or payload.get("inputs"))
    if beat.get("mode") != "images":
        raise ValueError(
            "Switch to images mode before the explicit three-still launch. Economy mode generates one still."
        )
    nonce = text(nonce, "Request identity", GROUP_NONCE_LIMIT)
    route, model = _image_route(payload, allow_openrouter=True)
    agreed = _agreed_style(ledger)
    comment = _launch_comment(beat, payload)
    references = _ordinary_references(ledger, beat, nonce, route)
    scope = _comparison_scope(beat, agreed, comment, (route, model), references)
    saved = _saved_comparison(state(ledger.data), nonce, fingerprint(scope))
    if saved:
        return saved
    _apply_comment(beat, payload, comment)
    return _freeze_comparison(ledger, beat, scope, nonce)


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
    public = {
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
    for name in ("group", "slot", "mode"):
        if name in request and request.get(name) is not None:
            public[name] = request.get(name)
    return public


def public_version(version):
    row = {
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
        "inputs": version.get("inputs"),
    }
    if version.get("kind") != "video":
        return row
    approval = version.get("approval") if isinstance(version.get("approval"), dict) else {}
    comment = approval.get("comment") if isinstance(approval.get("comment"), str) else ""
    still = version.get("still") if isinstance(version.get("still"), dict) else {}
    row.update(
        comment=comment,
        fps=version.get("fps"),
        duration_s=version.get("duration_s"),
        audio=version.get("audio"),
        native_full_hd=version.get("native_full_hd"),
        coverage=version.get("coverage"),
        resolution=version.get("resolution"),
        still={"id": still.get("id"), "sha256": still.get("sha256")},
    )
    return row
