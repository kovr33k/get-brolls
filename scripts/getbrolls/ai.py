"""GPT subscription stills, recorded-narration timing, video launch, Storyboard and HTTP handlers."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import stat
import subprocess
import sys
import uuid
from html import escape
from pathlib import Path

from .ai_openrouter import retrievable as _openrouter_retrievable
from .ai_provider import APP_SERVER_ENV, COMPLETE, MAX_IMAGE_BYTES, TIMEOUT_S, generate_still, inspect_images
from .ai_provider import retrievable as _gpt_retrievable
from .ai_state import (
    ALTERNATIVE_COUNT,
    FULL_HD_HEIGHT,
    FULL_HD_WIDTH,
    IN_FLIGHT,
    MAX_PROMPT,
    _agreed_style,
    _image_route,
    _native_image_output,
    _session_id,
    attach_result,
    beat_for,
    checked_version,
    fingerprint,
    identifier,
    import_plan,
    launch_comparison,
    launch_still,
    new_job,
    public_job,
    public_version,
    review,
    sanitize_public_text,
    select,
    text,
    version_signature,
)
from .ledger import Ledger, digest
from .media import run
from .models import now
from .runtime import project_lock

INLINE_ENV = "GETBROLLS_AI_INLINE"
CRASH_ENV = "GETBROLLS_AI_TEST_CRASH"
FIXTURE_ENV = "GETBROLLS_AI_FIXTURE"
WORKER_ENV = (
    APP_SERVER_ENV,
    FIXTURE_ENV,
    INLINE_ENV,
    CRASH_ENV,
    "GETBROLLS_AI_TIMEOUT",
    "GETBROLLS_AI_FAIL_IF_PROMPT_CONTAINS",
    "GETBROLLS_AI_UNKNOWN_IF_PROMPT_CONTAINS",
    "GETBROLLS_GROK_BIN",
    "GETBROLLS_GROK_ACCOUNT",
    "GETBROLLS_GROK_FIXTURE",
    "GETBROLLS_GROK_SESSION_ROOT",
    "XAI_API_KEY",
    "GROK_API_KEY",
)


class _WorkerInterruptedError(Exception):
    """Deterministic interruption at a durable boundary in synthetic fault tests."""


def _interrupt_worker(point):
    if os.environ.get(CRASH_ENV) == point:
        raise _WorkerInterruptedError


STILL_CODECS = {"png": ".png", "mjpeg": ".jpg"}
MAX_ARTIFACT_PATH = 240
MAX_REMOTE_ID = 200


def _esc(value):
    return escape(str(value or ""), quote=True)


def _project_root(ledger):
    return ledger.root.parent


def _error_payload(message, code=None):
    payload = {"message": sanitize_public_text(message)}
    if code:
        payload["code"] = code
    return payload


def _should_dispatch(job):
    return job.get("state") == "queued" and job.get("submit_outcome") == "not_sent"


class _ReadOnlyLedger:
    """In-memory view for a status recheck. It has no save and creates no directories."""

    __slots__ = ("data", "root")

    def __init__(self, data, root):
        self.data = data
        self.root = root


def _status_reasons(checked, *, resolved):
    if not isinstance(checked, dict):
        return ["stale_binding"]
    raw = checked.get("reasons")
    reasons = [str(item) for item in raw if isinstance(item, str)] if isinstance(raw, list) else []
    if reasons:
        return reasons
    return [] if resolved else ["stale_binding"]


def _status_timing(data, root, beat):
    raw = beat.get("timing")
    if not isinstance(raw, dict):
        return None
    match = _mapping(raw.get("match"))
    interval = _mapping(match.get("timing"))
    still = _mapping(raw.get("still"))
    resolved = False
    reasons = ["unread"]
    if root is not None:
        try:
            from .ai_timing import current_readiness

            checked = current_readiness(_ReadOnlyLedger(data, Path(root)), beat, raw)
        except (ValueError, OSError, KeyError, TypeError):
            checked = None
        resolved = bool(isinstance(checked, dict) and checked.get("resolved"))
        reasons = _status_reasons(checked, resolved=resolved)
    return {
        "analysis_id": raw.get("analysis_id"),
        "recording_id": raw.get("recording_id"),
        "resolved": resolved,
        "reasons": reasons,
        "still": still.get("id"),
        "start_s": interval.get("start_s"),
        "end_s": interval.get("end_s"),
    }


def public_status(data, root=None):
    from .ai_delivery import progress
    from .ai_sequences import board_sequence

    ai = data.get("ai")
    if not isinstance(ai, dict):
        return {}
    beats = []
    for beat in (ai.get("beats") or {}).values():
        if not isinstance(beat, dict):
            continue
        beats.append(
            {
                "id": beat.get("id"),
                "active": beat.get("active"),
                "mode": beat.get("mode"),
                "selected": beat.get("selected"),
                "fingerprint": beat.get("fingerprint"),
                "timing": _status_timing(data, root, beat),
                "sequence": board_sequence(_ReadOnlyLedger(data, Path(root)), beat) if root is not None else None,
            }
        )
    view = _ReadOnlyLedger(data, Path(root)) if root is not None else None
    jobs = [public_job(job, view) for job in (ai.get("jobs") or {}).values() if isinstance(job, dict)]
    versions = [public_version(row) for row in (ai.get("versions") or {}).values() if isinstance(row, dict)]
    style_value = ai.get("style")
    style = style_value if isinstance(style_value, dict) else {}
    return {
        "plan": bool(ai.get("plan")),
        "style": style.get("fingerprint"),
        "beats": beats,
        "jobs": jobs,
        "versions": versions,
        "delivery": progress(view) if view else None,
    }


def _image_job(row, beat):
    request = row.get("request") or {}
    return (
        isinstance(row, dict)
        and request.get("beat") == beat.get("id")
        and request.get("inputs") == beat.get("fingerprint")
        and request.get("kind", "image") == "image"
    )


def _latest_job(jobs, beat):
    matching = [row for row in reversed(list(jobs.values())) if _image_job(row, beat)]
    inflight = next((row for row in matching if row.get("state") in IN_FLIGHT), None)
    if inflight is not None:
        return inflight
    return next((row for row in matching if (row.get("request") or {}).get("operation") != "inspect"), None)


def _matching_group(ai, beat):
    groups = ai.get("groups") if isinstance(ai.get("groups"), dict) else {}
    found = None
    for group in groups.values():
        scope = group.get("scope") if isinstance(group, dict) and isinstance(group.get("scope"), dict) else None
        if not scope:
            continue
        if (
            scope.get("beat") == beat.get("id")
            and scope.get("inputs") == beat.get("fingerprint")
            and scope.get("outputs") == ALTERNATIVE_COUNT
        ):
            found = group
    return found


def _group_slots(ai, beat):
    group = _matching_group(ai, beat)
    if not group:
        return None
    jobs = ai.get("jobs") or {}
    versions = ai.get("versions") or {}
    slots = []
    for original_id in group.get("jobs") or []:
        job_id = (group.get("corrections") or {}).get(original_id, original_id)
        job = jobs.get(job_id)
        if not isinstance(job, dict):
            continue
        version = versions.get(job.get("result") or "")
        if not isinstance(version, dict):
            version = None
        comment = (version.get("approval") or {}).get("comment") if version else None
        if not isinstance(comment, str):
            comment = (job.get("request") or {}).get("comment") or ""
        slots.append(
            {
                "alternative": (job.get("request") or {}).get("alternative"),
                "comment": comment,
                "job": public_job(job),
                "version": public_version(version) if version else None,
            }
        )
    return slots


def _mapping(value):
    return value if isinstance(value, dict) else {}


def _sequence(value):
    return value if isinstance(value, list) else []


def _public_timing(ledger, beat):
    raw = beat.get("timing")
    timing = raw if isinstance(raw, dict) else None
    if not timing:
        return None
    match = _mapping(timing.get("match"))
    readiness = _mapping(timing.get("readiness"))
    interval = _mapping(match.get("timing"))
    raw_still = timing.get("still")
    still = raw_still if isinstance(raw_still, dict) else None
    resolved = bool(readiness.get("resolved"))
    reasons = [str(item) for item in _sequence(readiness.get("reasons")) if isinstance(item, str)]
    from .ai_timing import _public_candidates, current_readiness, preview_for_view

    candidates = _public_candidates(match.get("candidates"))
    try:
        checked = current_readiness(ledger, beat, timing)
    except (ValueError, OSError, KeyError, TypeError):
        checked = {"resolved": False, "reasons": ["stale_binding"]}
    if not isinstance(checked, dict) or not checked.get("resolved"):
        resolved = False
        fresh = checked.get("reasons") if isinstance(checked, dict) else None
        reasons = [str(item) for item in _sequence(fresh) if isinstance(item, str)] or ["stale_binding"]
    preview, preview_error = None, None
    if resolved:
        try:
            preview, preview_error = preview_for_view(ledger, timing, resolved=True)
        except (ValueError, OSError, KeyError, TypeError):
            preview, preview_error = None, "The narration preview could not be verified. No excerpt was created."
    return {
        "state": match.get("state"),
        "resolved": resolved,
        "reasons": reasons,
        "start_s": interval.get("start_s"),
        "end_s": interval.get("end_s"),
        "ambiguous": match.get("state") == "uncertain",
        "candidates": candidates,
        "preview": preview,
        "preview_error": preview_error,
        "recording_id": timing.get("recording_id"),
        "analysis_id": timing.get("analysis_id"),
        "identity": fingerprint(checked.get("narration")) if resolved else None,
        "still": still.get("id") if still else None,
    }


def _approved_still_intact(ledger, version, expected_sha):
    if (
        not isinstance(version, dict)
        or version.get("kind") != "image"
        or not isinstance(expected_sha, str)
        or version.get("sha256") != expected_sha
    ):
        return False
    approval = version.get("approval")
    if not isinstance(approval, dict) or approval.get("state") != "approved":
        return False
    rel = version.get("path")
    if not isinstance(rel, str) or not rel.startswith("previews/") or ".." in rel.split("/"):
        return False
    file = ledger.root / rel
    try:
        if _is_reparse(file) or file.is_symlink() or not file.is_file():
            return False
        return digest(file) == expected_sha
    except (OSError, ValueError):
        return False


def _video_ready(ledger, beat, versions):
    raw = beat.get("timing")
    timing = raw if isinstance(raw, dict) else None
    if not timing:
        return False
    try:
        from .ai_timing import current_readiness

        ready = current_readiness(ledger, beat, timing)
    except (ValueError, OSError, KeyError, TypeError):
        return False
    if not isinstance(ready, dict) or not ready.get("resolved"):
        return False
    raw_still = timing.get("still")
    still = raw_still if isinstance(raw_still, dict) else None
    if still:
        return _approved_still_intact(ledger, versions.get(still.get("id") or ""), still.get("sha256"))
    for version in versions.values():
        if not isinstance(version, dict) or version.get("kind") != "image":
            continue
        if version.get("beat") != beat.get("id") or version.get("inputs") != beat.get("fingerprint"):
            continue
        if _approved_still_intact(ledger, version, version.get("sha256")):
            return True
    return False


def _latest_video(versions, beat):
    found = None
    for version in versions.values():
        if (
            isinstance(version, dict)
            and version.get("kind") == "video"
            and version.get("beat") == beat.get("id")
            and version.get("inputs") == beat.get("fingerprint")
        ):
            found = version
    return found


def _video_context_current(ledger, version):
    from .ai_timing import checked_video_input

    job = (ledger.data.get("ai") or {}).get("jobs", {}).get(version.get("job"))
    try:
        if not job:
            return False
        checked_video_input(ledger, job["request"])
        return True
    except (ValueError, OSError, KeyError, TypeError):
        return False


def _public_video(ledger, version):
    if not version:
        return None
    return {**public_version(version), "context_current": _video_context_current(ledger, version)}


def _latest_video_job(jobs, beat):
    return next(
        (
            row
            for row in reversed(list(jobs.values()))
            if isinstance(row, dict)
            and (row.get("request") or {}).get("beat") == beat.get("id")
            and (row.get("request") or {}).get("inputs") == beat.get("fingerprint")
            and (row.get("request") or {}).get("kind") == "video"
        ),
        None,
    )


def _public_inspection_sources(sources):
    if not isinstance(sources, list):
        return []
    public = []
    for source in sources:
        if not isinstance(source, dict):
            continue
        public.append(
            {
                "id": source.get("id"),
                "order": source.get("order"),
                "sha256": source.get("sha256"),
                "role": source.get("role"),
                "observation": source.get("observation"),
                "context_id": source.get("context_id"),
                "interval": source.get("interval"),
                "time_s": source.get("time_s"),
                "derivative_sha256": source.get("derivative_sha256"),
            }
        )
    return public


def _public_apply_job(job, ledger=None):
    public = public_job(job, ledger)
    if not isinstance(job, dict):
        return public
    raw_request = job.get("request")
    request = raw_request if isinstance(raw_request, dict) else {}
    if request.get("operation") in {"apply", "inspect"}:
        public["operation"] = request.get("operation")
    inspection = job.get("inspection")
    if isinstance(inspection, dict):
        public["inspection"] = {
            "origin": inspection.get("origin"),
            "provider_input": inspection.get("provider_input"),
            "media": False,
            "provider_access": False,
            "route": inspection.get("route"),
            "findings": inspection.get("findings") if isinstance(inspection.get("findings"), str) else None,
            "sources": _public_inspection_sources(inspection.get("sources")),
            "evidence": inspection.get("evidence") if isinstance(inspection.get("evidence"), dict) else None,
        }
    unexpected = job.get("unexpected_media")
    if isinstance(unexpected, dict):
        public["unexpected_media"] = {
            "media": True,
            "generated": True,
            "sha256": unexpected.get("sha256"),
            "approval": None,
        }
    return public


def _reference_card(ledger, beat, still_id):
    try:
        from .ai_references import show_reference

        shown = show_reference(ledger, beat.get("id"), beat.get("fingerprint"), still_id)
    except (ValueError, OSError, KeyError, TypeError) as exc:
        return {"error": sanitize_public_text(str(exc)), "received": False}
    if not isinstance(shown, dict) or not shown.get("received") or shown.get("state") in {None, "absent"}:
        return None
    return {
        "context_id": shown.get("context_id"),
        "name": shown.get("name"),
        "role": shown.get("role"),
        "kind": shown.get("kind"),
        "sha256": shown.get("sha256"),
        "instructions": shown.get("instructions"),
        "scope": shown.get("scope"),
        "target_still": {"id": still_id, "signature": version_signature(ledger.data["ai"]["versions"][still_id])}
        if still_id
        else None,
        "inspection": shown.get("inspection"),
        "findings": shown.get("findings"),
        "interval": shown.get("interval"),
        "provider_input": shown.get("provider_input"),
        "provider_access": False,
        "received": True,
    }


def public_board(ledger):
    from .ai_delivery import progress
    from .ai_sequences import board_sequence

    ai = ledger.data.get("ai") or {}
    jobs = ai.get("jobs") or {}
    versions = ai.get("versions") or {}
    delivery = progress(ledger)
    delivery_beats = {row["beat"]: row for row in delivery["beats"]}
    beats = []
    for beat in (ai.get("beats") or {}).values():
        if not isinstance(beat, dict):
            continue
        job = _latest_job(jobs, beat)
        version = versions.get((job or {}).get("result") or "") if job else None
        if not isinstance(version, dict):
            version = None
        job, version = _card_focus(ai, beat, job, version)
        video = _latest_video(versions, beat)
        video_job = _latest_video_job(jobs, beat)
        still_id = version.get("id") if isinstance(version, dict) and version.get("kind") == "image" else None
        beats.append(
            {
                "id": beat.get("id"),
                "active": beat.get("active", True),
                "fingerprint": beat.get("fingerprint"),
                "mode": beat.get("mode"),
                "selected": beat.get("selected"),
                "comment": beat.get("comment") or "",
                "job": _public_apply_job(job, ledger) if job else None,
                "version": public_version(version) if version else None,
                "slots": _group_slots(ai, beat),
                "timing": _public_timing(ledger, beat),
                "video": _public_video(ledger, video),
                "sequence": board_sequence(ledger, beat),
                "video_job": public_job(video_job, ledger) if video_job else None,
                "video_ready": _video_ready(ledger, beat, versions),
                "reference": _reference_card(ledger, beat, still_id) if still_id else None,
                "guidance": _reference_card(ledger, beat, None),
                "delivery": delivery_beats.get(beat["id"]),
            }
        )
    return {
        "beats": beats,
        "jobs": [_public_apply_job(job, ledger) for job in jobs.values() if isinstance(job, dict)],
        "versions": [public_version(row) for row in versions.values() if isinstance(row, dict)],
        "style": ((ai.get("style") or {}).get("prompt") if isinstance(ai.get("style"), dict) else None),
        "native_video": _native_video_status(ai),
        "still_provider": ai.get("still_provider") or {"route": "gpt-subscription", "model": None},
        "shared_references": _shared_reference_cards(ledger),
        "openrouter": ai.get("openrouter") or {},
        "delivery": delivery,
    }


def _shared_reference_cards(ledger):
    from .ai_references import shared_guidance

    try:
        return [
            {key: row.get(key) for key in ("context_id", "beat", "name", "instructions", "scope_instruction")}
            for row in shared_guidance(ledger)
        ]
    except (ValueError, OSError, KeyError, TypeError) as exc:
        return [{"error": sanitize_public_text(str(exc))}]


def _native_video_status(ai):
    from .ai_timing import public_native_video

    return public_native_video(ai)


def _read_json(path):
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("The AI plan must be a JSON object.")
    return payload


def plan_command(ledger, args):
    return import_plan(ledger, _read_json(args.file))


def select_command(ledger, args):
    payload = {"beat": args.beat, "alternative": args.alternative}
    if getattr(args, "comment", None) is not None:
        payload["comment"] = args.comment
    if getattr(args, "mode", None) is not None:
        payload["mode"] = args.mode
    if getattr(args, "expected", None) is not None:
        payload["expected"] = args.expected
    beat = select(ledger, payload)
    return {
        "beat": beat["id"],
        "selected": beat.get("selected"),
        "mode": beat.get("mode"),
        "comment": beat.get("comment") or "",
    }


def _still_payload(args):
    payload = {"beat": args.beat, "expected": getattr(args, "expected", None)}
    route = getattr(args, "route", None)
    model = getattr(args, "model", None)
    if route:
        payload["route"] = route
    if model:
        payload["model"] = model
    return payload


def _dispatch_payload(ledger, jobs):
    project = str(_project_root(ledger))
    start = [job["id"] for job in jobs if _should_dispatch(job)]
    if not start:
        return None
    if len(jobs) == 1:
        return {"project": project, "job": start[0]}
    return {"project": project, "jobs": [job["id"] for job in jobs], "start": start}


def generate_still_command(ledger, args):
    job = launch_still(ledger, _still_payload(args), args.request_id)
    ledger.save("ai-generate-still")
    payload = {"job": public_job(job), "beat": args.beat}
    dispatch = _dispatch_payload(ledger, [job])
    if dispatch:
        payload["ai_dispatch"] = dispatch
    return payload


def generate_comparison_command(ledger, args):
    launched = launch_comparison(
        ledger,
        {"beat": args.beat, "expected": getattr(args, "expected", None), "outputs": 3},
        args.request_id,
    )
    ledger.save("ai-generate-comparison")
    jobs = launched["jobs"]
    payload = {
        "group": launched["group"]["id"],
        "beat": args.beat,
        "jobs": [public_job(job) for job in jobs],
    }
    dispatch = _dispatch_payload(ledger, jobs)
    if dispatch:
        payload["ai_dispatch"] = dispatch
    return payload


def timing_command(ledger, args):
    from .ai_timing import prepare_timing

    return prepare_timing(
        ledger,
        args.beat,
        args.analysis,
        still=getattr(args, "still", None),
        expected=getattr(args, "expected", None),
    )


def timing_resolve_command(ledger, args):
    from .ai_timing import resolve_timing

    return resolve_timing(
        ledger,
        args.beat,
        args.analysis,
        {
            "by": args.by,
            "statement": args.statement,
            "candidate": getattr(args, "candidate", None),
            "start": getattr(args, "start", None),
            "end": getattr(args, "end", None),
            "expected": getattr(args, "expected", None),
        },
    )


def generate_video_command(ledger, args):
    from .ai_timing import launch_video

    payload = {
        "beat": args.beat,
        "expected": getattr(args, "expected", None),
        "version": args.version,
        "model": args.model,
        "tool": getattr(args, "tool", None) or "reference_to_video",
        "resolution": getattr(args, "resolution", None) or "480p",
        "speech": bool(getattr(args, "speech", False)),
        "music": bool(getattr(args, "music", False)),
        "atmosphere": bool(getattr(args, "atmosphere", False)),
        "effects": bool(getattr(args, "effects", False)),
    }
    job = launch_video(ledger, payload, args.request_id)
    ledger.save("ai-generate-video")
    result = {"job": public_job(job), "beat": args.beat}
    dispatch = _dispatch_payload(ledger, [job])
    if dispatch:
        result["ai_dispatch"] = dispatch
    return result


def approve_command(ledger, args):
    payload = {
        "version": args.version,
        "by": args.by,
        "decision": args.decision,
        "comment": args.comment,
        "signature": args.signature,
    }
    if payload["signature"] is None:
        version = (ledger.data.get("ai") or {}).get("versions", {}).get(args.version)
        if not version:
            raise ValueError("Select an existing AI result of the required type.")
        payload["signature"] = version_signature(version)
    return review(ledger, payload)


def resume_command(ledger, args):
    from .ai_recovery import check_inputs

    job = (ledger.data.get("ai") or {}).get("jobs", {}).get(identifier(args.job, "Job id"))
    if not job:
        raise ValueError("This AI job is not in the current project.")
    project = str(_project_root(ledger))
    if job.get("state") == "complete" and job.get("result"):
        checked_version(ledger, job["result"])
        return {"job": public_job(job), "resubmitted": False}
    check_inputs(ledger, job)
    if job.get("state") == "queued" and job.get("submit_outcome") == "not_sent":
        return {"job": public_job(job), "resubmitted": False, "ai_dispatch": {"project": project, "job": job["id"]}}
    if job.get("state") == "running" and job.get("submit_outcome") == "not_sent":
        job["state"] = "unknown"
        job["submit_outcome"] = "unknown"
        job["error"] = _error_payload(
            "The native still submit outcome is unknown. Resume will not send it again.", "unknown"
        )
        ledger.save("ai-resume-unknown")
        return {"job": public_job(job), "resubmitted": False}
    if (
        (_recorded_artifact(job) and (job.get("remote") or {}).get("artifact_sha256"))
        or _grok_retrievable(job)
        or _gpt_retrievable(job)
        or _openrouter_retrievable(job)
    ) and job.get("state") in {"remote_pending", "downloading", "unknown", "failed"}:
        return {
            "job": public_job(job),
            "resubmitted": False,
            "ai_dispatch": {"project": project, "job": job["id"], "retrieve": True},
        }
    return {"job": public_job(job), "resubmitted": False}


def _dispatch_ids(info):
    if isinstance(info.get("jobs"), list):
        return [job_id for job_id in info["jobs"] if job_id]
    if info.get("job"):
        return [info["job"]]
    return []


def dispatch_after_audit(result):
    info = result.pop("ai_dispatch", None) if isinstance(result, dict) else None
    if not isinstance(info, dict):
        return result
    job_ids = _dispatch_ids(info)
    raw_start = info.get("start")
    start_ids = raw_start if isinstance(raw_start, list) else job_ids
    retrieve = bool(info.get("retrieve"))
    for job_id in start_ids:
        if job_id:
            start_worker(info["project"], job_id, retrieve=retrieve)
    inline = os.environ.get(INLINE_ENV) == "1"
    result["worker"] = "inline" if inline else "started"
    if inline and job_ids:
        ledger = Ledger(info["project"], recover=False)
        stored = (ledger.data.get("ai") or {}).get("jobs", {})
        if isinstance(info.get("jobs"), list):
            result["jobs"] = [public_job(stored[job_id]) for job_id in job_ids if stored.get(job_id)]
        else:
            job = stored.get(job_ids[0])
            if job:
                result["job"] = public_job(job)
    return result


def handle_select(project, data):
    with project_lock(project):
        beat = select(Ledger(project), data)
    return {
        "beat": {
            "id": beat["id"],
            "selected": beat.get("selected"),
            "mode": beat.get("mode"),
            "comment": beat.get("comment") or "",
            "fingerprint": beat.get("fingerprint"),
        }
    }


def handle_review(project, data):
    payload = dict(data)
    payload.setdefault("by", payload.get("by") or "Storyboard")
    with project_lock(project):
        return review(Ledger(project), payload)


def handle_resume(project, data):
    with project_lock(project):
        result = resume_command(Ledger(project), argparse.Namespace(job=data.get("job")))
    return dispatch_after_audit(result)


def _refresh_jobs(project, job_ids):
    if os.environ.get(INLINE_ENV) != "1" or not job_ids:
        return None
    ledger = Ledger(project, recover=False)
    stored = (ledger.data.get("ai") or {}).get("jobs", {})
    return [public_job(stored[job_id]) for job_id in job_ids if stored.get(job_id)]


def _approval_snapshot(ledger):
    versions = (ledger.data.get("ai") or {}).get("versions") or {}
    rows = []
    for ident, version in versions.items():
        approval = version.get("approval") if isinstance(version, dict) else None
        encoded = json.dumps(approval, sort_keys=True) if isinstance(approval, dict) else None
        rows.append((ident, encoded))
    return tuple(sorted(rows))


def _apply_scope(data):
    scope = data.get("scope", "beat")
    if not isinstance(scope, str) or scope not in {"beat", "shared"}:
        raise ValueError("Apply scope must be beat or shared.")
    instruction = data.get("scope_instruction")
    if scope == "beat":
        if instruction not in (None, ""):
            raise ValueError("Beat-local guidance does not take a shared-style instruction.")
        return "beat", None
    if not isinstance(instruction, str) or not instruction.strip():
        raise ValueError("Shared AI style needs an explicit scope instruction. Beat-local guidance was not expanded.")
    return "shared", sanitize_public_text(text(instruction, "Scope instruction", 2000), limit=2000)


def _current_still(ledger, beat):
    versions = (ledger.data.get("ai") or {}).get("versions") or {}
    found = None
    for version in versions.values():
        if (
            isinstance(version, dict)
            and version.get("kind") == "image"
            and version.get("beat") == beat.get("id")
            and version.get("inputs") == beat.get("fingerprint")
        ):
            found = version
    return found


def _apply_target(ledger, beat, still):
    if still is None:
        if _current_still(ledger, beat) is not None:
            raise ValueError("Name the exact displayed still. The request was not retargeted.")
        return None
    if not isinstance(still, dict) or set(still) != {"id", "signature"}:
        raise ValueError("Name the exact displayed still id and signature.")
    version, path = checked_version(ledger, still["id"], kind="image")
    if version.get("beat") != beat["id"] or version.get("inputs") != beat["fingerprint"]:
        raise ValueError("The named still belongs to another beat. The request was not retargeted.")
    if still["signature"] != version_signature(version):
        raise ValueError("The displayed still changed. The request was not retargeted.")
    digest_value = digest(path)
    if digest_value != version.get("sha256"):
        raise ValueError("The displayed still bytes changed. The request was not retargeted.")
    return {"id": version["id"], "signature": still["signature"], "sha256": digest_value}


def _reject_apply_conflict(ledger, beat, target, nonce):
    jobs = (ledger.data.get("ai") or {}).get("jobs") or {}
    target_id = target["id"] if target else None
    for job in jobs.values():
        if not isinstance(job, dict) or job.get("state") not in IN_FLIGHT or job.get("nonce") == nonce:
            continue
        request = job.get("request") or {}
        if request.get("beat") != beat["id"] or request.get("kind", "image") != "image":
            continue
        job_target = request.get("target") if isinstance(request.get("target"), dict) else None
        job_target_id = job_target.get("id") if job_target else None
        same_target = target_id is not None and job_target_id == target_id
        same_open_beat = target_id is None and job_target_id is None
        if same_target or same_open_beat:
            raise ValueError("Another action is already in flight for this still. It was not retargeted.")


def _frozen_summary(frozen):
    derivative = frozen.get("derivative") if isinstance(frozen.get("derivative"), dict) else {}
    frames = [
        {"index": frame["index"], "sha256": frame["sha256"], "time_s": frame.get("time_s")}
        for frame in derivative.get("frames") or []
        if isinstance(frame, dict) and type(frame.get("index")) is int and isinstance(frame.get("sha256"), str)
    ]
    hashes = [derivative.get("sha256"), derivative.get("clip_sha256"), derivative.get("sheet_sha256")]
    hashes.extend(frame["sha256"] for frame in frames)
    summary = {
        "input_id": frozen.get("input_id"),
        "context_id": frozen.get("context_id"),
        "role": frozen.get("role"),
        "source_sha256": frozen.get("sha256"),
        "derivative_sha256": sorted({item for item in hashes if isinstance(item, str)}),
        "interval": frozen.get("interval"),
        "kind": frozen.get("kind"),
        "scope": frozen.get("scope"),
        "scope_instruction": frozen.get("scope_instruction"),
        "instructions": frozen.get("instructions"),
        "derivative_id": derivative.get("id"),
        "frames": frames,
        "inspection": frozen.get("inspection"),
        "inspection_origin": frozen.get("inspection_origin"),
        "provider_input": frozen.get("provider_input"),
    }
    findings = frozen.get("findings")
    if isinstance(findings, str) and findings.strip():
        summary["findings"] = findings
    return summary


def _active_reference(shown):
    return isinstance(shown, dict) and shown.get("received") and shown.get("state") not in {None, "absent"}


def _freeze_shown_reference(ledger, beat, nonce, _target, shown):
    """Freeze the resolved context. An ancestor keeps the still it was actually uploaded against."""
    from .ai_references import freeze_inputs, freeze_retained

    payload = {
        "beat": beat["id"],
        "fingerprint": beat["fingerprint"],
        "identity": "frz-" + fingerprint({"nonce": nonce, "context": shown["context_id"]})[:40],
    }
    still = shown.get("still") if isinstance(shown.get("still"), dict) else None
    if still is not None and isinstance(still.get("id"), str) and isinstance(still.get("signature"), str):
        payload["still"] = {"id": still["id"], "signature": still["signature"]}
        payload["context"] = shown["context_id"]
        return _frozen_summary(freeze_retained(ledger, payload))
    return _frozen_summary(freeze_inputs(ledger, payload))


def _freeze_apply_references(ledger, beat, nonce, target, route="gpt-subscription"):
    from .ai_references import freeze_shared_guidance, show_reference

    rows = []
    if target is not None:
        shown = show_reference(ledger, beat["id"], beat["fingerprint"], target["id"])
        if _active_reference(shown):
            rows.append(shown)
    shown = show_reference(ledger, beat["id"], beat["fingerprint"], None)
    if _active_reference(shown):
        rows.append(shown)
    rows.sort(key=lambda row: row.get("context_id") or "")
    return [
        *[_freeze_shown_reference(ledger, beat, nonce, target, shown) for shown in rows],
        *freeze_shared_guidance(ledger, beat, nonce, route, exclude={row["context_id"] for row in rows}),
    ]


def _reference_prompt_line(ref):
    from .ai_references import reference_prompt_lines

    lines = reference_prompt_lines([ref])
    return lines[0] if lines else ""


def _apply_prompt(beat, alternative, agreed, change, summaries):
    _style, style_prompt, quality = agreed
    instruction, scope, scope_instruction, target = change
    parts = [
        "Generate exactly one still image with the image generation tool. Do not produce video.",
        "Editor instruction: " + instruction,
        "Agreed visual style: " + style_prompt,
        "Agreed quality: " + quality,
        "Scene: " + alternative["description"],
        "Visual purpose: " + beat["purpose"],
        "Original scenario passage: " + beat["text"],
    ]
    comment = str(beat.get("comment") or "").strip()
    if comment:
        parts.append("Editor comment: " + comment)
    if target:
        parts.append("The attached target image is the exact retained still. Do not retarget to a later result.")
    if scope == "shared":
        parts.append("Shared style instruction: " + scope_instruction)
    else:
        parts.append("This change is beat-local. Do not expand it to other beats.")
    parts.extend(_reference_prompt_line(ref) for ref in summaries)
    parts.append("Generated illustration is not documentary evidence, rights clearance, or animation approval.")
    parts.append("A filename in this text is not image content.")
    return "\n".join(parts)


def _inspect_prompt(instruction, target, summaries, manifest=None):
    parts = [
        "Inspect the attached images only. Do not generate media.",
        "A filename in this text is not image content.",
        "Editor instruction: " + instruction,
    ]
    if target:
        parts.append("The attached target is the exact retained still.")
    parts.extend(_reference_prompt_line(ref) for ref in summaries)
    if not manifest:
        parts.append("Report findings for the stated role. Do not invent a caption from the filename.")
        return "\n".join(parts)
    parts.append(
        "The attached images are listed below in attachment order. "
        "Each sha256 was computed from the validated file bytes before this turn. "
        "Copy id, order, role, and sha256 exactly. Do not calculate a hash from pixels. "
        "Write one content observation for each input, describing what is visible for the stated role. "
        "Do not invent an observation from the filename, the role label, the hash, or other metadata. "
        "An empty observation is not acceptable."
    )
    parts.append("INSPECTION_MANIFEST")
    parts.extend(json.dumps(entry, ensure_ascii=False, separators=(",", ":"), sort_keys=True) for entry in manifest)
    parts.append("END_INSPECTION_MANIFEST")
    return "\n".join(parts)


def _observation_line(item):
    interval = item.get("interval") if isinstance(item.get("interval"), dict) else None
    extra = ""
    if interval is not None:
        extra += f" interval {interval.get('start_s')}–{interval.get('end_s')}s"
    if item.get("time_s") is not None:
        extra += f" frame_time {item.get('time_s')}"
    context = item.get("context_id") or "target"
    return (
        f"Observation id {item.get('id')} order {item.get('order')} role {item.get('role')} "
        f"context {context} sha256 {item.get('sha256')}{extra}: {item.get('observation')}"
    )


def _production_prompt(base, observations):
    """Append validated observations. The stored request prompt stays unchanged."""
    lines = [base or ""]
    if observations:
        lines.append(
            "Validated observations of the attached images. "
            "Each observation is bound to the listed source. Metadata is not a substitute."
        )
        lines.extend(_observation_line(item) for item in observations)
    return "\n".join(lines)


def _selected_alternative(beat):
    selected = beat.get("selected")
    alternatives = [row for row in beat.get("alternatives") or [] if isinstance(row, dict)]
    if selected not in {row.get("id") for row in alternatives}:
        raise ValueError("Select a scene alternative before Apply.")
    return selected, next(row for row in alternatives if row.get("id") == selected)


def _invalidate_target_videos(ledger, beat_id, target_id):
    versions = (ledger.data.get("ai") or {}).get("versions") or {}
    for version in versions.values():
        if not isinstance(version, dict) or version.get("kind") != "video" or version.get("beat") != beat_id:
            continue
        raw_still = version.get("still")
        still = raw_still if isinstance(raw_still, dict) else {}
        if still.get("id") != target_id:
            continue
        raw_approval = version.get("approval")
        approval = raw_approval if isinstance(raw_approval, dict) else {}
        comment = approval.get("comment") if isinstance(approval.get("comment"), str) else ""
        version["approval"] = {
            "state": "pending",
            "comment": comment,
            "invalidated_reason": "The retained still changed. This descendant needs a new decision.",
        }


def _launch_apply(ledger, data, nonce, operation):
    beat = beat_for(ledger, data.get("beat"), data.get("expected") or data.get("inputs"))
    instruction = text(data.get("instruction"), "Apply instruction", MAX_PROMPT)
    scope, scope_instruction = _apply_scope(data)
    target = _apply_target(ledger, beat, data.get("still"))
    _reject_apply_conflict(ledger, beat, target, nonce)
    route, model = _image_route(data, allow_openrouter=False, setup=(ledger.data.get("ai") or {}).get("still_provider"))
    if route == "grok-subscription" and operation == "inspect":
        raise ValueError("Grok has no verified analysis-only image route. No generation was submitted.")
    summaries = _freeze_apply_references(ledger, beat, nonce, target, route)
    if "reference" in data and (
        not isinstance(data["reference"], str) or data["reference"] not in {ref.get("context_id") for ref in summaries}
    ):
        raise ValueError("The uploaded reference changed. Nothing was submitted for a different context.")
    if operation == "inspect" and not summaries and target is None:
        raise ValueError("Inspection needs an actual image or the requested video frames.")
    style, style_prompt, quality = _agreed_style(ledger)
    selected, alternative = _selected_alternative(beat)
    prompt = (
        _inspect_prompt(instruction, target, summaries)
        if operation == "inspect"
        else _apply_prompt(
            beat,
            alternative,
            (style, style_prompt, quality),
            (instruction, scope, scope_instruction, target),
            summaries,
        )
    )
    request = {
        "beat": beat["id"],
        "inputs": beat["fingerprint"],
        "kind": "image",
        "route": route,
        "operation": operation,
        "alternative": selected,
        "description": alternative["description"],
        "comment": str(beat.get("comment") or ""),
        "instruction": instruction,
        "style": style_prompt,
        "style_fingerprint": style.get("fingerprint") or fingerprint(style_prompt),
        "quality": quality,
        "mode": beat.get("mode") or "economy",
        "scope": scope,
        "prompt": prompt,
        "references": summaries,
    }
    if scope_instruction:
        request["scope_instruction"] = scope_instruction
    if target:
        request["target"] = target
    if model:
        request.update(_native_image_output(ledger))
        request.update(
            model=model,
            tool="image_edit" if target or summaries else "image_gen",
            session_id=_session_id(nonce, request["style_fingerprint"]),
        )
    prior = set((ledger.data.get("ai") or {}).get("jobs") or {})
    job = new_job(ledger, request, nonce)
    created = job["id"] not in prior
    if created and operation == "apply" and target is not None:
        _invalidate_target_videos(ledger, beat["id"], target["id"])
    return job


def handle_apply(project, data):
    if not isinstance(data, dict):
        raise ValueError("Apply needs the instruction and the exact beat.")
    operation = data.get("operation", "apply")
    if not isinstance(operation, str) or operation not in {"apply", "inspect"}:
        raise ValueError("Apply inspects or generates. It does not take an edit or regenerate selector.")
    if data.get("route") not in (None, "gpt-subscription", "grok-subscription"):
        raise ValueError("Apply requires a supported subscription image route. No paid route was submitted.")
    nonce = text(data.get("requestId") or data.get("request_id") or data.get("nonce"), "Request identity", 160)
    with project_lock(project):
        ledger = Ledger(project)
        job = _launch_apply(ledger, data, nonce, operation)
        ledger.save("ai-apply")
        dispatch = _should_dispatch(job)
        public = _public_apply_job(job)
        job_id = job["id"]
    if dispatch:
        start_worker(project, job_id)
        if os.environ.get(INLINE_ENV) == "1":
            refreshed = Ledger(project, recover=False).data["ai"]["jobs"].get(job_id)
            if refreshed:
                public = _public_apply_job(refreshed)
    return {"job": public}


def _upload_payload(metadata, stream, length):
    payload = {
        "beat": metadata.get("beat"),
        "fingerprint": metadata.get("fingerprint") or metadata.get("expected"),
        "identity": metadata.get("identity"),
        "name": metadata.get("name"),
        "declared_type": metadata.get("declared_type"),
        "body": stream,
        "length": length,
        "instructions": metadata.get("instructions"),
        "role": metadata.get("role") or "guidance",
        "scope": metadata.get("scope") or "beat",
    }
    if metadata.get("scope") == "shared":
        payload["scope_instruction"] = metadata.get("scope_instruction")
    if metadata.get("still") is not None:
        payload["still"] = metadata.get("still")
    if metadata.get("interval") is not None:
        payload["interval"] = metadata.get("interval")
    return payload


def handle_reference_upload(project, stream, length, metadata):
    if not isinstance(metadata, dict):
        raise ValueError("Reference metadata must identify the beat and the received file.")
    from .ai_references import attach_reference, replace_reference, show_reference

    replacing = metadata.get("replace")
    if replacing is not None and type(replacing) is not bool:
        raise ValueError("Replace must be explicit. Nothing was attached.")
    with project_lock(project):
        ledger = Ledger(project)
        jobs_before = set((ledger.data.get("ai") or {}).get("jobs") or {})
        approvals_before = _approval_snapshot(ledger)
        payload = _upload_payload(metadata, stream, length)
        if replacing is True and "context" in metadata:
            still = payload.get("still")
            shown = show_reference(
                ledger,
                payload["beat"],
                payload["fingerprint"],
                still.get("id") if isinstance(still, dict) else None,
            )
            if not isinstance(metadata["context"], str) or shown.get("context_id") != metadata["context"]:
                raise ValueError("The visible reference changed. Refresh its context before replacing it.")
        public = replace_reference(ledger, payload) if replacing is True else attach_reference(ledger, payload)
        jobs_after = set((ledger.data.get("ai") or {}).get("jobs") or {})
        if jobs_before != jobs_after or approvals_before != _approval_snapshot(ledger):
            raise ValueError("Reference upload must not create a generation job or an approval.")
        return public


def handle_reference_remove(project, data):
    if not isinstance(data, dict):
        raise ValueError("Name the exact beat and fingerprint.")
    from .ai_references import remove_reference, show_reference

    with project_lock(project):
        ledger = Ledger(project)
        jobs_before = set((ledger.data.get("ai") or {}).get("jobs") or {})
        if "context" in data:
            still = data.get("still")
            shown = show_reference(
                ledger,
                data.get("beat"),
                data.get("expected") or data.get("fingerprint"),
                still.get("id") if isinstance(still, dict) else None,
            )
            if not isinstance(data["context"], str) or shown.get("context_id") != data["context"]:
                raise ValueError("The visible reference changed. Refresh its context before removing it.")
        public = remove_reference(
            ledger,
            {
                "beat": data.get("beat"),
                "fingerprint": data.get("expected") or data.get("fingerprint"),
                "still": data.get("still"),
            },
        )
        jobs_after = set((ledger.data.get("ai") or {}).get("jobs") or {})
        if jobs_before != jobs_after:
            raise ValueError("Removing a reference must not create a generation job.")
        return {"reference": public}


def reference_preview_bytes(project, context_id, part, index=None):
    from .ai_references import read_derivative

    ident = identifier(context_id, "Reference")
    if part not in {"pixels", "sheet", "frame"}:
        raise ValueError("That preview is not available.")
    if part == "frame":
        if isinstance(index, bool) or type(index) is not int or index < 0:
            raise ValueError("Name the reference frame.")
    elif index is not None:
        raise ValueError("That preview is not available.")
    with project_lock(project):
        ledger = Ledger(project, recover=False)
        store = (ledger.data.get("ai") or {}).get("references")
        contexts = store.get("contexts") if isinstance(store, dict) else None
        record = contexts.get(ident) if isinstance(contexts, dict) else None
        if not isinstance(record, dict):
            raise ValueError("Unknown reference.")
        data = read_derivative(ledger, record.get("derivative_id"), part, index if part == "frame" else None)
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return data, "image/png"
    if data.startswith(b"\xff\xd8\xff"):
        return data, "image/jpeg"
    raise ValueError("The preview is not a PNG or JPEG.")


def handle_generate(project, data):
    nonce = data.get("requestId") or data.get("request_id") or data.get("nonce")
    if data.get("route") not in (None, "gpt-subscription", "grok-subscription"):
        raise ValueError("This launch does not accept a paid API route.")
    outputs = data.get("outputs", None)
    with project_lock(project):
        ledger = Ledger(project)
        if outputs is None:
            job = launch_still(ledger, data, nonce)
            ledger.save("ai-generate-still")
            jobs = [job]
            group_id = None
        elif type(outputs) is int and outputs == ALTERNATIVE_COUNT:
            launched = launch_comparison(ledger, data, nonce)
            ledger.save("ai-generate-comparison")
            jobs = launched["jobs"]
            group_id = launched["group"]["id"]
        else:
            raise ValueError("A still launch is one economy image, or an explicit three-output comparison.")
        dispatch_ids = [job["id"] for job in jobs if _should_dispatch(job)]
        public_jobs = [public_job(job) for job in jobs]
    for job_id in dispatch_ids:
        start_worker(project, job_id)
    refreshed = _refresh_jobs(project, [job["id"] for job in jobs])
    if refreshed:
        public_jobs = refreshed
    if group_id:
        return {"group": group_id, "jobs": public_jobs}
    return {"job": public_jobs[0]}


def handle_timing(project, data):
    from .ai_timing import prepare_timing

    with project_lock(project):
        return prepare_timing(
            Ledger(project),
            data.get("beat"),
            data.get("analysis"),
            still=data.get("still") or data.get("version"),
            expected=data.get("expected"),
        )


def handle_timing_resolve(project, data):
    from .ai_timing import resolve_timing

    with project_lock(project):
        return resolve_timing(
            Ledger(project),
            data.get("beat"),
            data.get("analysis"),
            {
                "by": data.get("by") or "Storyboard",
                "statement": data.get("statement"),
                "candidate": data.get("candidate"),
                "start": data.get("start"),
                "end": data.get("end"),
                "expected": data.get("expected"),
            },
        )


def handle_video(project, data):
    from .ai_timing import launch_video

    nonce = data.get("requestId") or data.get("request_id") or data.get("nonce")
    with project_lock(project):
        ledger = Ledger(project)
        job = launch_video(ledger, data, nonce)
        ledger.save("ai-generate-video")
        dispatch = _should_dispatch(job)
        public = public_job(job)
        job_id = job["id"]
    if dispatch:
        start_worker(project, job_id)
        refreshed = _refresh_jobs(project, [job_id])
        if refreshed:
            public = refreshed[0]
    return {"job": public}


def handle_state(project):
    return public_board(Ledger(project, recover=False))


def review_records(ledger, ident):
    from .ai_sequences import board_sequence

    ai = ledger.data.get("ai")
    if not isinstance(ai, dict):
        return []
    records = []
    for version in (ai.get("versions") or {}).values():
        if not isinstance(version, dict) or version.get("kind") not in {"image", "sequence"}:
            continue
        beat = (ai.get("beats") or {}).get(version.get("beat")) or {}
        job = (ai.get("jobs") or {}).get(version.get("job")) or {}
        approval = version.get("approval") or {}
        records.append(
            {
                "id": "ai:" + str(version.get("beat")),
                "project": ident,
                "beat": version.get("beat"),
                "fingerprint": version.get("inputs"),
                "selected": (job.get("request") or {}).get("alternative") or beat.get("selected"),
                "comment": (
                    approval.get("comment") or ""
                    if approval.get("state") in {"approved", "changes", "rejected"}
                    else (job.get("request") or {}).get("comment") or ""
                ),
                "mode": beat.get("mode") or "economy",
                "job": version.get("job"),
                "version": version.get("id"),
                "signature": version_signature(version),
                "state": approval.get("state") or "pending",
                "path": version.get("path"),
                **(
                    {"kind": "sequence", "sequence": board_sequence(ledger, beat)}
                    if version.get("kind") == "sequence"
                    and (ai.get("sequences", {}).get(beat.get("sequence")) or {}).get("version") == version["id"]
                    else {}
                ),
            }
        )
    return records


def apply_review_import(ledger, rows, *, by):
    applied = []
    skipped = []
    unchanged = []
    if not rows:
        return applied, skipped, unchanged
    if not isinstance(ledger.data.get("ai"), dict):
        skipped.extend(
            {
                "id": (row or {}).get("id") or "ai",
                "reason": "missing_ai",
                "detail": "This project has no AI records.",
            }
            for row in rows
        )
        return applied, skipped, unchanged
    for row in rows:
        result = _import_row(ledger, row, by)
        if result == "applied":
            applied.append((row or {}).get("version"))
        elif result == "unchanged":
            unchanged.append((row or {}).get("version") or (row or {}).get("id") or "ai")
        else:
            skipped.append(result)
    return applied, skipped, unchanged


def _skip(ident, reason, detail):
    return {"id": ident, "reason": reason, "detail": detail}


def _import_row(ledger, row, by):
    from .ai_state import checked_version

    if not isinstance(row, dict):
        return _skip("ai", "invalid", "Invalid AI review row.")
    ident = row.get("id") or "ai"
    decision = row.get("decision") or row.get("state")
    version_id = row.get("version")
    if decision in (None, "pending"):
        result = "unchanged"
    elif not version_id:
        result = _skip(ident, "missing_version", "AI review needs a version.")
    else:
        try:
            version, _path = checked_version(ledger, version_id)
            current = version.get("approval") or {}
            if row.get("signature") != version_signature(version):
                result = _skip(
                    ident, "signature_mismatch", "The displayed AI version changed; review the exact current result."
                )
            elif decision not in ("approved", "changes", "rejected"):
                result = _skip(ident, "invalid_decision", "Choose an explicit human decision.")
            elif current.get("state") == decision and current.get("signature") == version_signature(version):
                result = "unchanged"
            else:
                version["approval"] = {
                    "state": decision,
                    "by": by,
                    "at": now(),
                    "signature": version_signature(version),
                    "comment": str(row.get("comment") or "")[:32000],
                }
                result = "applied"
        except ValueError as exc:
            result = _skip(ident, "invalid", str(exc))
    return result


def storyboard_section(ledger):
    from .ai_delivery import progress

    ai = ledger.data.get("ai")
    if not isinstance(ai, dict) or not ai.get("plan"):
        return ""
    style = (ai.get("style") or {}).get("prompt") or ""
    jobs = ai.get("jobs") or {}
    versions = ai.get("versions") or {}
    delivery = {row["beat"]: row for row in progress(ledger)["beats"]}
    parts = [
        '<section class="ai-board" aria-label="AI production">',
        "<h2>AI stills</h2>",
        f'<p class="ai-style" data-ai-style>{_esc(style)}</p>',
    ]
    routing = (ai.get("plan") or {}).get("routing") or []
    for record in routing:
        if not isinstance(record, dict):
            continue
        if record.get("route") != "ai":
            parts.append(
                f'<p class="ai-route" data-ai-route="{_esc(record.get("route"))}" data-ai-beat="{_esc(record.get("id"))}">'
                f"{_esc((record.get('route') or '').title())} · {_esc(record.get('title') or record.get('id'))}</p>"
            )
            continue
        beat = (ai.get("beats") or {}).get(record.get("id"))
        if not isinstance(beat, dict):
            continue
        job = _latest_job(jobs, beat)
        version = versions.get((job or {}).get("result") or "") if job else None
        if not isinstance(version, dict):
            version = None
        job, version = _card_focus(ai, beat, job, version)
        parts.append(
            _beat_card(
                beat,
                job,
                version,
                {
                    "slots": _group_slots(ai, beat),
                    "video": _latest_video(versions, beat),
                    "video_job": _latest_video_job(jobs, beat),
                    "video_ready": _video_ready(ledger, beat, versions),
                    "ledger": ledger,
                    "delivery": delivery.get(beat["id"]),
                },
            )
        )
    parts.append("</section>")
    return "".join(parts)


def _comparison_edit(ai, beat, group):
    # A later Apply keeps its own progress/result while the original three slots
    # stay available. Stop at this group's jobs so an older edit cannot hide a
    # newly requested comparison.
    for candidate in reversed(list((ai.get("jobs") or {}).values())):
        if not isinstance(candidate, dict):
            continue
        if candidate.get("id") in (group.get("jobs") or []):
            break
        request = candidate.get("request") or {}
        if (
            _image_job(candidate, beat)
            and request.get("operation") == "apply"
            and request.get("alternative") == beat.get("selected")
        ):
            return candidate
    return None


def _card_focus(ai, beat, job, version):
    """Pin the selected treatment, including its later Apply result; keep sibling progress."""
    if beat.get("mode") != "images":
        return job, version
    group = _matching_group(ai, beat)
    if not group:
        return job, version
    edited = _comparison_edit(ai, beat, group)
    if edited:
        result = (ai.get("versions") or {}).get(edited.get("result"))
        return edited, result if isinstance(result, dict) else None
    raw = []
    for job_id in group.get("jobs") or []:
        row = (ai.get("jobs") or {}).get(job_id)
        if isinstance(row, dict):
            raw.append(row)
    flight = next((row for row in raw if row.get("state") in IN_FLIGHT), None)
    selected = next(
        (row for row in raw if (row.get("request") or {}).get("alternative") == beat.get("selected")),
        None,
    )
    pinned = None
    if selected and selected.get("result"):
        candidate = (ai.get("versions") or {}).get(selected["result"])
        if isinstance(candidate, dict):
            pinned = candidate
    return flight or selected, pinned


def _card_state_attrs(job, version):
    parts = []
    if job:
        parts.append(f' data-ai-job="{_esc(job.get("id"))}"')
        parts.append(f' data-ai-state="{_esc(job.get("state") or "")}"')
    if version:
        approval = (version.get("approval") or {}).get("state") or "pending"
        parts.append(f' data-ai-version="{_esc(version.get("id"))}"')
        parts.append(f' data-ai-signature="{_esc(version_signature(version))}"')
        parts.append(f' data-ai-approval="{_esc(approval)}"')
    return "".join(parts)


def _slot_markup(slots, selected):
    if not slots:
        return ""
    figures = []
    for slot in slots:
        job = slot.get("job") or {}
        version = slot.get("version")
        alternative = slot.get("alternative") or ""
        image = ""
        if isinstance(version, dict) and version.get("path"):
            image = f'<img src="{_esc(version.get("path"))}" alt="Generated illustration">'
        caption = job.get("error") or job.get("state") or "waiting"
        chosen = "true" if alternative and alternative == selected else "false"
        version_attr = ""
        signature_attr = ""
        approval_attr = ""
        if isinstance(version, dict):
            version_attr = f' data-ai-version="{_esc(version.get("id"))}"'
            signature_attr = f' data-ai-signature="{_esc(version.get("signature"))}"'
            approval_attr = f' data-ai-approval="{_esc(version.get("approval") or "pending")}"'
        figures.append(
            f'<figure class="ai-slot" data-ai-slot="{_esc(alternative)}" data-ai-selected="{chosen}"'
            f' data-ai-slot-comment="{_esc(slot.get("comment") or "")}"'
            f' data-ai-job="{_esc(job.get("id"))}" data-ai-state="{_esc(job.get("state") or "")}"'
            f"{version_attr}{signature_attr}{approval_attr}>"
            f"{image}<figcaption>{_esc(caption)}</figcaption>"
            f'<button type="button" data-ai-choose="{_esc(alternative)}">Review this still</button>'
            "</figure>"
        )
    return f'<div class="ai-slots" data-ai-slots>{"".join(figures)}</div>'


def _video_decision_label(state):
    return {"approved": "Approved", "changes": "Changes requested", "rejected": "Rejected"}.get(
        state, "Awaiting decision"
    )


def _video_markup(video, *, context_current=True):
    if not isinstance(video, dict):
        return '<div class="ai-video-review" data-ai-video-review hidden></div>'
    approval = _mapping(video.get("approval"))
    comment = approval.get("comment") if isinstance(approval.get("comment"), str) else ""
    short = " Duration is shorter than the recorded interval." if video.get("coverage") == "short" else ""
    native = "Native 480p/720p is not native Full HD." if video.get("native_full_hd") is False else ""
    stale = (
        " This retained clip is not verified against the current narration and approved input."
        if not context_current
        else ""
    )
    meta = (
        f"{_esc(video.get('width'))}×{_esc(video.get('height'))} {_esc(video.get('resolution') or '')} · "
        f"{_esc(video.get('fps') if video.get('fps') is not None else 'unknown')} fps · "
        f"{_esc(video.get('duration_s'))}s · audio {_esc(video.get('audio'))}.{_esc(short)} {_esc(native)}{_esc(stale)}"
    )
    return (
        f'<div class="ai-video-review" data-ai-video-review data-ai-video-version="{_esc(video.get("id"))}"'
        f' data-ai-video-signature="{_esc(version_signature(video))}">'
        f"<p data-ai-video-meta>{meta}</p>"
        f'<video src="{_esc(video.get("path"))}" controls preload="metadata"></video>'
        f"<label>Video note <textarea data-ai-video-comment>{_esc(comment)}</textarea></label>"
        f'<p class="ai-decision" data-ai-video-decision-label>{_esc(_video_decision_label(approval.get("state")))}</p>'
        '<button type="button" data-ai-video-decision="approved">Approve this video</button>'
        '<button type="button" data-ai-video-decision="changes">Request video changes</button>'
        '<button type="button" data-ai-video-decision="rejected">Reject this video</button>'
        "</div>"
    )


def _apply_controls():
    return (
        "<label>Instruction <textarea data-ai-instruction></textarea></label>"
        '<label>Reference <input type="file" data-ai-file accept="image/png,image/jpeg,video/mp4"></label>'
        "<p data-ai-file-note></p>"
        "<p data-ai-reference-note></p>"
        "<details><summary>Reference options</summary>"
        "<label>Role <select data-ai-role>"
        '<option value="guidance" selected>Follow my instruction</option>'
        '<option value="appearance">Appearance</option>'
        '<option value="content">Content</option>'
        '<option value="composition">Composition</option>'
        '<option value="motion">Motion</option>'
        '<option value="style">Style</option>'
        "</select></label>"
        '<label>Interval start <input data-ai-interval-start inputmode="decimal"></label>'
        '<label>Interval end <input data-ai-interval-end inputmode="decimal"></label>'
        "<label>Scope <select data-ai-scope>"
        '<option value="beat" selected>This beat</option>'
        '<option value="shared">Shared style</option>'
        "</select></label>"
        "<label>Scope instruction <textarea data-ai-scope-instruction></textarea></label></details>"
        '<button type="button" data-ai-upload>Keep reference</button>'
        '<button type="button" data-ai-remove-reference>Remove reference</button>'
        '<button type="button" data-ai-apply>Apply</button>'
        "<p data-ai-apply-note></p>"
        '<img data-ai-reference-preview alt="" hidden>'
    )


def _beat_card(beat, job, version, board):
    slots = board.get("slots")
    video = board.get("video")
    video_ready = bool(board.get("video_ready"))
    ledger = board.get("ledger")
    beat_id = beat["id"]
    selected = beat.get("selected") or ""
    mode = beat.get("mode") or "economy"
    radios = []
    for alternative in beat.get("alternatives") or []:
        checked = " checked" if alternative.get("id") == selected else ""
        radios.append(
            '<label><input type="radio" name="ai-alt-'
            f'{_esc(beat_id)}" value="{_esc(alternative.get("id"))}" data-ai-alternative{checked}> '
            f"{_esc(alternative.get('description'))}</label>"
        )
    progress = ""
    if slots and mode == "images":
        progress = " · ".join(
            (
                f"{slot.get('alternative')}: "
                f"{(slot.get('job') or {}).get('error') or (slot.get('job') or {}).get('state') or 'waiting'}"
            )
            for slot in slots
        )
    elif job:
        progress = public_job(job).get("state") or ""
        if job.get("error"):
            progress = sanitize_public_text(
                (job.get("error") or {}).get("message") if isinstance(job.get("error"), dict) else job.get("error")
            )
    figure = ""
    review_hidden = " hidden"
    if isinstance(version, dict) and version.get("path"):
        figure = (
            f'<img src="{_esc(version.get("path"))}" alt="Generated illustration">'
            "<figcaption>Generated illustration</figcaption>"
        )
        review_hidden = ""
    native = _native_video_status(ledger.data.get("ai") if ledger is not None else None)
    provider = ((ledger.data.get("ai") or {}).get("still_provider") or {}) if ledger is not None else {}
    provider_label = "Grok subscription" if provider.get("route") == "grok-subscription" else "GPT subscription"
    if provider.get("route") == "gpt-subscription" and provider.get("session_model"):
        provider_label += " · session " + provider["session_model"]
    details = _details(beat, job, version, native)
    ready_attr = ' data-ai-video-ready="true"' if video_ready else ""
    video_job = board.get("video_job")
    video_state_attr = ""
    video_progress = ""
    if isinstance(video_job, dict):
        public_video_job = public_job(video_job)
        if public_video_job.get("state"):
            video_state_attr = f' data-ai-video-state="{_esc(public_video_job.get("state"))}"'
        video_progress = f"<p data-ai-video-progress>{_esc(public_video_job.get('error') or public_video_job.get('state') or '')}</p>"
    generate_label = "Generate three stills" if mode == "images" else "Generate still"
    images_selected = " selected" if mode == "images" else ""
    economy_selected = " selected" if mode != "images" else ""
    return (
        f'<article class="ai-card" data-ai-beat="{_esc(beat_id)}" data-ai-fingerprint="{_esc(beat.get("fingerprint"))}" '
        f'data-ai-mode="{_esc(mode)}"{ready_attr}{video_state_attr}{_card_state_attrs(job, version)}>'
        f"<h3>{_esc(beat.get('title') or beat_id)}</h3>"
        f'<p class="ai-purpose">{_esc(beat.get("purpose"))}</p>'
        f'<blockquote class="ai-text">{_esc(beat.get("text"))}</blockquote>'
        f'<fieldset class="ai-alternatives">{"".join(radios)}</fieldset>'
        f"<label>Comment <textarea data-ai-comment>{_esc(beat.get('comment') or '')}</textarea></label>"
        f"{_apply_controls()}"
        "<label>Comparison <select data-ai-mode>"
        f'<option value="economy"{economy_selected}>Descriptions, then one still</option>'
        f'<option value="images"{images_selected}>Generate three stills</option>'
        "</select></label>"
        f'<button type="button" data-ai-generate>{generate_label}</button>'
        f"<span data-ai-still-provider>Stills: {_esc(provider_label)}</span>"
        '<button type="button" data-ai-video' + ("" if video_ready else " disabled") + ">Generate video</button>"
        f"<p data-ai-video-setup>{_esc(native.get('message'))} "
        "480p and 720p are not native Full HD. A short clip does not cover the recorded interval. "
        "Motion follows the selected treatment. The approved still is the first frame. "
        "Speech and music stay off unless requested. Narration stays a separate recording.</p>"
        f"<p data-ai-progress>{_esc(progress)}</p>"
        f"{video_progress}"
        f"<p data-ai-timing>{_esc(_timing_line(ledger, beat))}</p>"
        f"{_slot_markup(slots, selected)}"
        f"<figure data-ai-result>{figure}</figure>"
        f'<div class="ai-review"{review_hidden}>'
        '<button type="button" data-ai-decision="approved">Approve this still</button>'
        '<button type="button" data-ai-decision="changes">Request changes</button>'
        '<button type="button" data-ai-decision="rejected">Reject</button>'
        "</div>"
        f"{_video_markup(video, context_current=_video_context_current(ledger, video) if ledger is not None and video else True)}"
        f"{_delivery_markup(board.get('delivery'))}"
        f'<details class="ai-details"><summary>Details</summary>{details}</details>'
        "</article>"
    )


def _delivery_markup(row):
    if not row:
        return ""
    use = row.get("material_use") or {}
    return (
        "<fieldset data-ai-delivery><legend>AI handoff</legend>"
        f"<p>Version: {_esc(row.get('version') or 'none')} · editorial: {_esc(row.get('approval') or 'pending')}"
        f" · use: {_esc(use.get('state') or 'unresolved')} · {_esc(row['delivery_state'])}</p>"
        f"<p>{_esc(', '.join(row['reasons']))}</p>"
        "<p>Material use is separate from editorial approval. Reference access does not grant reuse rights. "
        "Use the live Storyboard or ai-material-use CLI to record conditions, then run deliver. "
        "This portable snapshot does not publish a package or change conditions.</p></fieldset>"
    )


def _candidate_label(row):
    if not isinstance(row, dict) or not row.get("id"):
        return ""
    parts = [str(row.get("id"))]
    if row.get("start_s") is not None and row.get("end_s") is not None:
        parts.append(f"{row.get('start_s')}–{row.get('end_s')}s")
    if row.get("text"):
        parts.append(str(row.get("text")))
    return " · ".join(parts)


def _timing_line(ledger, beat):
    public = _public_timing(ledger, beat)
    if not public:
        return ""
    if public.get("resolved"):
        return f"Recorded interval {public.get('start_s')}–{public.get('end_s')}s. Timing does not generate media."
    reasons = ", ".join(public.get("reasons") or []) or public.get("state") or "unresolved"
    labels = "; ".join(label for row in public.get("candidates") or [] if (label := _candidate_label(row)))
    extra = (" Candidates: " + labels + ".") if labels else ""
    return "Timing unresolved: " + reasons + "." + extra + " Timing does not generate media."


def _details(beat, job, version, native=None):
    public = public_job(job) if job else {}
    lines = [
        f"<p>Beat {_esc(beat.get('id'))} · mode {_esc(beat.get('mode'))}</p>",
        (
            f"<p>Job {_esc(public.get('id') or 'none')} · route {_esc(public.get('route') or 'gpt-subscription')} · "
            f"state {_esc(public.get('state') or 'idle')}</p>"
        ),
    ]
    setup = native if isinstance(native, dict) else {}
    if public.get("session_model"):
        lines.append(f"<p>GPT session {_esc(public['session_model'])}</p>")
    lines.append(
        "<p>Native video route "
        f"{_esc(setup.get('route') or 'grok-subscription')} · model {_esc(setup.get('model') or 'not recorded')} · "
        f"tool {_esc(setup.get('tool') or 'not recorded')} · capability unverified.</p>"
    )
    if version:
        lines.append(
            f"<p>{_esc(version.get('width'))}×{_esc(version.get('height'))} {_esc(version.get('codec'))} · "
            f"sha256 {_esc(version.get('sha256'))} · original {_esc(version.get('original_sha256'))}</p>"
        )
        lines.append("<p>Generated illustration, not documentary evidence. Generation is not approval.</p>")
    if public.get("error"):
        lines.append(f"<p>{_esc(public.get('error'))}</p>")
    return "".join(lines)


def start_worker(project, job_id, *, retrieve=False):
    if os.environ.get(INLINE_ENV) == "1":
        run_worker(project, job_id, retrieve=retrieve)
        return None
    return spawn_worker(project, job_id, retrieve=retrieve)


def spawn_worker(project, job_id, *, retrieve=False):
    scripts = Path(__file__).resolve().parents[1]
    env = os.environ.copy()
    existing = env.get("PYTHONPATH")
    env["PYTHONPATH"] = str(scripts) + (os.pathsep + existing if existing else "")
    env["PYTHONUNBUFFERED"] = "1"
    for name in WORKER_ENV:
        value = os.environ.get(name)
        if value is not None:
            env[name] = value
    if any(os.environ.get(name) for name in (FIXTURE_ENV, INLINE_ENV, CRASH_ENV)) and not env.get(APP_SERVER_ENV):
        raise ValueError("Test fixture env is set but GETBROLLS_CODEX_APP_SERVER is missing.")
    command = [
        sys.executable,
        "-m",
        "getbrolls.ai",
        "--worker",
        "--project",
        str(Path(project).resolve()),
        "--job",
        str(job_id),
    ]
    if retrieve:
        command.append("--retrieve")
    kwargs = {
        "cwd": str(Path(project).resolve()),
        "env": env,
        "stdin": subprocess.DEVNULL,
        "stdout": subprocess.DEVNULL,
        "stderr": subprocess.DEVNULL,
        "close_fds": True,
    }
    if os.name == "nt":
        flags = 0
        if hasattr(subprocess, "CREATE_NO_WINDOW"):
            flags |= subprocess.CREATE_NO_WINDOW
        if hasattr(subprocess, "CREATE_NEW_PROCESS_GROUP"):
            flags |= subprocess.CREATE_NEW_PROCESS_GROUP
        if flags:
            kwargs["creationflags"] = flags
        startup = subprocess.STARTUPINFO()
        startup.dwFlags |= getattr(subprocess, "STARTF_USESHOWWINDOW", 0)
        kwargs["startupinfo"] = startup
    else:
        kwargs["start_new_session"] = True
    return subprocess.Popen(command, **kwargs)  # noqa: S603 - pinned interpreter and module path.


def run_worker(project, job_id, *, retrieve=False):
    from .ai_recovery import worker_lock

    with worker_lock(project, job_id):
        _run_worker(project, job_id, retrieve=retrieve)


def _run_worker(project, job_id, *, retrieve=False):
    try:
        _interrupt_worker("before_submit")
        if retrieve:
            _retrieve_worker(project, job_id)
            return
        _produce_worker(project, job_id)
    except _WorkerInterruptedError:
        return
    except (ValueError, OSError, KeyError) as exc:
        _store_terminal(project, job_id, {"state": "failed", "message": str(exc), "code": "worker"})
    finally:
        from .ai_sequences import assemble_for_job

        if os.environ.get(CRASH_ENV) != "assembly":
            assemble_for_job(project, job_id)


def _is_reparse(path):
    path = Path(path)
    try:
        info = os.lstat(path)
    except FileNotFoundError:
        return False
    except OSError:
        return True
    if stat.S_ISLNK(info.st_mode):
        return True
    try:
        if path.is_symlink():
            return True
    except OSError:
        return True
    attrs = getattr(info, "st_file_attributes", 0)
    return bool(attrs & stat.FILE_ATTRIBUTE_REPARSE_POINT)


def _chain_inside(root, path):
    """Reject a symlink or junction anywhere from `path` up through `root`."""
    root = Path(root)
    cursor = Path(path)
    root_key = os.path.normcase(os.path.normpath(str(root)))
    while True:
        if _is_reparse(cursor):
            raise ValueError("AI media escaped through a symlink or junction.")
        if os.path.normcase(os.path.normpath(str(cursor))) == root_key:
            return
        parent = cursor.parent
        if parent == cursor:
            break
        cursor = parent
    raise ValueError("AI media is outside the project.")


def _brolls_root(project):
    root = Path(project).resolve() / "brolls"
    if _is_reparse(root) or not root.is_dir():
        raise ValueError("AI storage escaped through a symlink or junction.")
    return root


def _job_dir(brolls, job_id):
    directory = Path(brolls) / "ai-work" / identifier(job_id, "Job id")
    _chain_inside(brolls, directory)
    return directory


def _artifact_suffixes(job):
    if isinstance(job, dict) and (job.get("request") or {}).get("kind") == "video":
        return {".mp4"}
    return {".png", ".jpg", ".jpeg"}


def _safe_artifact(value, suffixes=None):
    allowed = suffixes or {".png", ".jpg", ".jpeg"}
    if (
        not isinstance(value, str)
        or not value
        or len(value) > MAX_ARTIFACT_PATH
        or "\\" in value
        or ":" in value
        or "\0" in value
        or value.startswith("/")
    ):
        return False
    path = Path(value)
    if path.is_absolute() or ".." in path.parts or any(part in {"", ".", ".."} for part in path.parts):
        return False
    return path.suffix.lower() in allowed


def _recorded_artifact(job):
    remote = job.get("remote") if isinstance(job, dict) and isinstance(job.get("remote"), dict) else None
    if not remote:
        return None
    artifact = remote.get("artifact")
    return artifact if _safe_artifact(artifact, _artifact_suffixes(job)) else None


def _merge_remote(job, remote):
    if not isinstance(remote, dict):
        return
    info = dict(job.get("remote") or {})
    for key in ("threadId", "turnId", "imageItemId", "tool", "sessionId", "model", "requestId", "transport"):
        value = remote.get(key)
        if (
            isinstance(value, str)
            and value
            and len(value) <= MAX_REMOTE_ID
            and "\0" not in value
            and "://" not in value
            and "\\" not in value
        ):
            info[key] = value
    artifact = remote.get("artifact")
    if _safe_artifact(artifact, _artifact_suffixes(job)) and not info.get("artifact_sha256"):
        info["artifact"] = artifact
    job["remote"] = info


def _claim(project, job_id):
    with project_lock(project):
        ledger = Ledger(project)
        job = (ledger.data.get("ai") or {}).get("jobs", {}).get(job_id)
        if not job:
            raise ValueError("This AI job is not in the current project.")
        if job.get("state") == "unknown" or job.get("submit_outcome") == "unknown":
            return None, ledger
        if job.get("state") != "queued" or job.get("submit_outcome") != "not_sent":
            return None, ledger
        job["state"] = "running"
        job["submit_outcome"] = "not_sent"
        job["error"] = None
        ledger.save("ai-submit-intent")
        return job, ledger


def _visual_request(request):
    if not isinstance(request, dict):
        return False
    if request.get("operation") in {"apply", "inspect"}:
        return True
    return bool(request.get("references") or request.get("target"))


def _parse_observation_document(raw):
    """Return stored observation objects. A bare inspected flag is not an observation."""
    if not isinstance(raw, str) or not raw.strip():
        return []
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        return []
    if isinstance(payload, dict):
        items = payload.get("observations")
    elif isinstance(payload, list):
        items = payload
    else:
        return []
    if not isinstance(items, list):
        return []
    return [item for item in items if isinstance(item, dict)]


def _input_id(row):
    """Nonsecret id for one staged image. Paths stay out of the manifest."""
    context = row.get("context_id")
    frame = row.get("frame") if isinstance(row.get("frame"), dict) else None
    if isinstance(context, str) and context and frame is not None:
        return f"{context}:{frame.get('index')}"
    if isinstance(context, str) and context:
        return context
    return "target"


def _public_interval(interval):
    if not isinstance(interval, dict):
        return None
    start = interval.get("start_s")
    end = interval.get("end_s")
    if isinstance(start, bool) or isinstance(end, bool):
        return None
    if not isinstance(start, (int, float)) or not isinstance(end, (int, float)):
        return None
    return {"start_s": start, "end_s": end}


def _frame_time(row):
    frame = row.get("frame") if isinstance(row.get("frame"), dict) else None
    if frame is None:
        return None
    stamp = frame.get("time_s")
    if stamp is None or isinstance(stamp, bool) or not isinstance(stamp, (int, float)):
        return None
    return stamp


def _observation_manifest(rows):
    """Image order is the localImage order. Hashes are from the staged bytes."""
    manifest = []
    for order, row in enumerate(rows, start=1):
        manifest.append(
            {
                "id": _input_id(row),
                "order": order,
                "role": row.get("role"),
                "sha256": row.get("sha256"),
                "context_id": row.get("context_id"),
                "interval": _public_interval(row.get("interval")),
                "time_s": _frame_time(row),
            }
        )
    return manifest


def _observations_document(observations):
    public = [
        {
            "id": item["id"],
            "order": item["order"],
            "role": item["role"],
            "sha256": item["sha256"],
            "observation": item["observation"],
        }
        for item in observations
    ]
    return json.dumps({"observations": public}, ensure_ascii=False, separators=(",", ":"), sort_keys=True)


def _native_inspection_flag(ref):
    return (
        isinstance(ref, dict)
        and ref.get("inspection") == "inspected"
        and ref.get("inspection_origin") == "native-gpt"
        and ref.get("provider_input") == "localImage"
    )


def _reused_observation(row, references):
    """Reuse one stored observation only when id, role, and staged hash all match."""
    if not isinstance(row, dict):
        return None
    context = row.get("context_id")
    ref = next(
        (
            item
            for item in references
            if isinstance(item, dict) and item.get("context_id") == context and _native_inspection_flag(item)
        ),
        None,
    )
    if ref is None or ref.get("role") != row.get("role"):
        return None
    ident = _input_id(row)
    for item in _parse_observation_document(ref.get("findings")):
        observation = item.get("observation")
        if (
            item.get("id") == ident
            and item.get("role") == row.get("role")
            and item.get("sha256") == row.get("sha256")
            and isinstance(observation, str)
            and observation.strip()
        ):
            return {
                "id": item["id"],
                "order": item.get("order"),
                "role": item["role"],
                "sha256": item["sha256"],
                "observation": observation,
                "context_id": context,
                "interval": _public_interval(row.get("interval")),
                "time_s": _frame_time(row),
            }
    return None


def _reference_needs_inspection(ref):
    """An inspected flag without a bound observation still needs inspection."""
    if not _native_inspection_flag(ref):
        return True
    role = ref.get("role")
    for item in _parse_observation_document(ref.get("findings")):
        observation = item.get("observation")
        if (
            item.get("role") == role
            and isinstance(item.get("sha256"), str)
            and isinstance(observation, str)
            and observation.strip()
        ):
            return False
    return True


def _image_suffix(data):
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return ".png"
    if data.startswith(b"\xff\xd8\xff"):
        return ".jpg"
    raise ValueError("The attached image is not a PNG or JPEG. Nothing was submitted.")


def _stage_file(workdir, name, data, expected):
    if not isinstance(data, (bytes, bytearray)) or not data:
        raise ValueError("Frozen image bytes are missing. Nothing was submitted.")
    actual = hashlib.sha256(data).hexdigest()
    if expected and actual != expected:
        raise ValueError("Frozen image bytes changed before staging. Nothing was submitted.")
    dest = workdir / name
    _chain_inside(workdir, dest)
    if dest.exists() or dest.is_symlink():
        raise ValueError("A staged image path already exists. Nothing was submitted.")
    dest.write_bytes(data)
    if dest.is_symlink() or not dest.is_file():
        raise ValueError("The staged image is not a regular file. Nothing was submitted.")
    copied = dest.read_bytes()
    if hashlib.sha256(copied).hexdigest() != actual:
        dest.unlink(missing_ok=True)
        raise ValueError("Frozen image bytes changed while staging. Nothing was submitted.")
    return dest, actual


def _staged_row(dest, actual, source, frame=None):
    role, context, interval, derivative_hashes = source
    row = {
        "path": str(dest.resolve()),
        "detail": "original",
        "role": role,
        "sha256": actual,
        "context_id": context,
        "interval": interval,
        "derivative_sha256": list(derivative_hashes),
    }
    if isinstance(frame, dict):
        row["frame"] = {"index": frame.get("index"), "time_s": frame.get("time_s")}
    return row


def _stage_target(ledger, workdir, target):
    if not isinstance(target, dict):
        raise ValueError("The frozen still is missing. The request was not retargeted.")
    version, path = checked_version(ledger, target.get("id"), kind="image")
    if version_signature(version) != target.get("signature") or version.get("sha256") != target.get("sha256"):
        raise ValueError("The frozen still changed. The request was not retargeted.")
    data = Path(path).read_bytes()
    suffix = Path(path).suffix.lower()
    if suffix not in {".png", ".jpg", ".jpeg"}:
        suffix = _image_suffix(data)
    dest, actual = _stage_file(workdir, "target" + suffix, data, target.get("sha256"))
    return _staged_row(dest, actual, ("target", None, None, [actual]))


def _stage_reference(ledger, workdir, ref):
    from .ai_references import read_derivative

    if not isinstance(ref, dict):
        raise ValueError("A frozen reference is missing. Nothing was submitted.")
    context = identifier(ref.get("context_id"), "Reference")
    role = ref.get("role") or "appearance"
    allowed = [item for item in ref.get("derivative_sha256") or [] if isinstance(item, str)]
    interval = ref.get("interval") if isinstance(ref.get("interval"), dict) else None
    derivative_id = ref.get("derivative_id")
    if ref.get("kind") == "video":
        return _stage_video_reference(ledger, workdir, ref, (role, context, interval, allowed))
    data = read_derivative(ledger, derivative_id, "pixels")
    actual_hash = hashlib.sha256(data).hexdigest()
    if actual_hash not in allowed:
        raise ValueError("The reference derivative does not match the frozen bytes. Nothing was submitted.")
    dest, actual = _stage_file(workdir, "reference-" + context + _image_suffix(data), data, actual_hash)
    return [_staged_row(dest, actual, (role, context, None, allowed))]


def _stage_video_reference(ledger, workdir, ref, source):
    from .ai_references import read_derivative

    role, context, interval, allowed = source
    derivative_id = ref.get("derivative_id")
    frames = ref.get("frames") or []
    if not isinstance(frames, list) or not frames:
        raise ValueError("Video guidance is missing the requested interval frames. The opening was not used.")
    if interval is None or interval.get("start_s") is None or interval.get("end_s") is None:
        raise ValueError("Video guidance is missing the requested interval. The opening was not used.")
    rows = []
    for frame in frames:
        index = frame.get("index") if isinstance(frame, dict) else None
        expected = frame.get("sha256") if isinstance(frame, dict) else None
        if type(index) is not int or not isinstance(expected, str):
            raise ValueError("Video guidance is missing a requested frame. The opening was not used.")
        data = read_derivative(ledger, derivative_id, "frame", index)
        if hashlib.sha256(data).hexdigest() != expected:
            raise ValueError("A requested video frame changed. The opening was not substituted.")
        dest, actual = _stage_file(workdir, f"reference-{context}-{index}.png", data, expected)
        rows.append(
            _staged_row(
                dest,
                actual,
                (role, context, interval, allowed),
                {"index": index, "time_s": frame.get("time_s") if isinstance(frame, dict) else None},
            )
        )
    return rows


def _stage_apply_rows(project, job, workdir):
    request = job.get("request") if isinstance(job.get("request"), dict) else {}
    rows = []
    with project_lock(project):
        ledger = Ledger(project, recover=False)
        target = request.get("target") if isinstance(request.get("target"), dict) else None
        if target is not None:
            rows.append(_stage_target(ledger, workdir, target))
        for ref in request.get("references") or []:
            rows.extend(_stage_reference(ledger, workdir, ref))
    return rows


def _inspection_rows(request, rows, operation):
    if operation == "inspect":
        return list(rows)
    references = [ref for ref in (request.get("references") or []) if isinstance(ref, dict)]
    needed = set()
    for ref in references:
        context = ref.get("context_id")
        context_rows = [row for row in rows if row.get("context_id") == context]
        missing = not context_rows or any(_reused_observation(row, references) is None for row in context_rows)
        if context and missing:
            needed.add(context)
    if not needed:
        return []
    chosen = [row for row in rows if row.get("context_id") in needed]
    staged = {row.get("context_id") for row in chosen}
    if staged != needed:
        raise ValueError("An uninspected reference was not attached. Nothing was submitted.")
    return chosen


def _local_items(rows):
    return [{"path": row["path"], "detail": "original"} for row in rows]


def _recheck_rows(rows):
    for row in rows:
        path = Path(row["path"])
        if path.is_symlink() or not path.is_file():
            raise ValueError("Frozen image bytes changed before the next turn. Nothing further was submitted.")
        if hashlib.sha256(path.read_bytes()).hexdigest() != row["sha256"]:
            raise ValueError("Frozen image bytes changed before the next turn. Nothing further was submitted.")


def _accept_findings(outcome, rows):
    """Accept one returned observation per staged input. A mismatched binding is not inspected."""
    _recheck_rows(rows)
    unbound = "Inspection findings were not bound to the attached image bytes. Nothing was marked inspected."
    mismatch = "Inspection findings do not match the attached image bytes. Nothing was marked inspected."
    manifest = _observation_manifest(rows)
    raw = outcome.get("findings")
    try:
        payload = json.loads(raw) if isinstance(raw, str) else None
    except json.JSONDecodeError as exc:
        raise ValueError(unbound) from exc
    observations = payload.get("observations") if isinstance(payload, dict) else None
    if not isinstance(observations, list) or len(observations) != len(manifest) or not observations:
        raise ValueError(unbound if not observations else mismatch)
    seen_ids = set()
    seen_orders = set()
    bound = []
    for index, obs in enumerate(observations):
        expected = manifest[index]
        if not isinstance(obs, dict):
            raise ValueError(unbound)
        ident = obs.get("id")
        order = obs.get("order")
        role = obs.get("role")
        digest_value = obs.get("sha256")
        observation = obs.get("observation")
        if not isinstance(ident, str) or not ident or ident in seen_ids:
            raise ValueError(mismatch)
        if type(order) is not int or order in seen_orders:
            raise ValueError(mismatch)
        if not isinstance(role, str) or not isinstance(digest_value, str):
            raise ValueError(mismatch)
        if not isinstance(observation, str) or not observation.strip():
            raise ValueError(unbound)
        if (
            ident != expected.get("id")
            or order != expected.get("order")
            or role != expected.get("role")
            or digest_value != expected.get("sha256")
        ):
            raise ValueError(mismatch)
        seen_ids.add(ident)
        seen_orders.add(order)
        bound.append(
            {
                "id": ident,
                "order": order,
                "role": role,
                "sha256": digest_value,
                "observation": observation,
                "context_id": expected.get("context_id"),
                "interval": expected.get("interval"),
                "time_s": expected.get("time_s"),
            }
        )
    return bound


def _inspection_source(obs, rows):
    row = next(
        (item for item in rows if item.get("sha256") == obs.get("sha256") and _input_id(item) == obs.get("id")),
        None,
    )
    return {
        "id": obs.get("id"),
        "order": obs.get("order"),
        "sha256": obs.get("sha256"),
        "role": obs.get("role"),
        "observation": obs.get("observation"),
        "context_id": obs.get("context_id"),
        "interval": obs.get("interval"),
        "time_s": obs.get("time_s"),
        "derivative_sha256": list((row or {}).get("derivative_sha256") or []),
    }


def _bind_inspection(project, job_id, request, inspection):
    """Record this turn's observations. The frozen request and its snapshot stay unchanged."""
    from .ai_references import record_inspection

    observations, remote, rows = inspection
    evidence = {}
    if isinstance(remote, dict):
        thread = remote.get("threadId")
        turn = remote.get("turnId")
        if isinstance(thread, str) and isinstance(turn, str):
            evidence = {"threadId": thread, "turnId": turn}
    by_context = {}
    for obs in observations:
        context = obs.get("context_id")
        if isinstance(context, str) and context:
            by_context.setdefault(context, []).append(obs)
    with project_lock(project):
        ledger = Ledger(project)
        current = (ledger.data.get("ai") or {}).get("jobs", {}).get(job_id)
        if not current or current.get("state") == "complete":
            raise ValueError("The inspection finished after the job was already closed.")
        for ref in request.get("references") or []:
            if not isinstance(ref, dict) or ref.get("context_id") not in by_context:
                continue
            record_inspection(
                ledger,
                {
                    "context": ref.get("context_id"),
                    "role": ref.get("role"),
                    "source_sha256": ref.get("source_sha256"),
                    "derivative_sha256": ref.get("derivative_sha256"),
                    "findings": _observations_document(by_context[ref.get("context_id")]),
                    "origin": "native-gpt",
                    "route": "gpt-subscription",
                    "provider_input": "localImage",
                    "evidence": evidence,
                },
            )
        current = ledger.data["ai"]["jobs"][job_id]
        current["inspection"] = {
            "origin": "native-gpt",
            "provider_input": "localImage",
            "media": False,
            "provider_access": False,
            "route": "gpt-subscription",
            "findings": sanitize_public_text(_observations_document(observations), limit=MAX_PROMPT),
            "sources": [_inspection_source(obs, rows) for obs in observations],
            "evidence": evidence,
        }
        ledger.save("ai-inspection-recorded")


def _handoff_observations(request, rows, fresh):
    references = [ref for ref in (request.get("references") or []) if isinstance(ref, dict)]
    fresh_by_key = {(item.get("id"), item.get("sha256")): item for item in fresh}
    handoff = []
    for row in rows:
        chosen = fresh_by_key.get((_input_id(row), row.get("sha256")))
        if chosen is None:
            chosen = _reused_observation(row, references)
        if chosen is not None:
            handoff.append(chosen)
    return handoff


def _failed_visual(message, code, remote=None):
    outcome = {"status": "failed", "error": message, "code": code, "media": False}
    if remote:
        outcome["remote"] = remote
    return outcome


def _produce_visual(project, job, workdir, timeout, on_submitted):  # noqa: PLR0911 - Inspection refusal, unknown submission and media completion are distinct terminal outcomes.
    """Stage frozen bytes, inspect through the pre-submit gate, then generate only after a clean inspection."""
    request = job.get("request") if isinstance(job.get("request"), dict) else {}
    session_options = {"session_model": request["session_model"]} if request.get("session_model") else {}
    operation = request.get("operation") or "apply"
    try:
        rows = _stage_apply_rows(project, job, workdir)
        inspect_rows = _inspection_rows(request, rows, operation)
    except (ValueError, OSError) as exc:
        return _failed_visual(str(exc), "stage")
    if operation == "inspect" and not inspect_rows:
        return _failed_visual(
            "Inspection needs an actual image or the requested video frames. Nothing was submitted.",
            "missing_images",
        )
    remote = None
    fresh = []
    if inspect_rows:
        manifest = _observation_manifest(inspect_rows)
        outcome = inspect_images(
            _inspect_prompt(
                request.get("instruction") or "",
                request.get("target"),
                request.get("references") or [],
                manifest,
            ),
            workdir,
            _local_items(inspect_rows),
            timeout=timeout,
            on_submitted=on_submitted,
            **session_options,
        )
        if not isinstance(outcome, dict):
            return _failed_visual("Inspection did not return a result. Nothing further was submitted.", "inspection")
        remote = outcome.get("remote")
        if outcome.get("media") is True or outcome.get("status") != COMPLETE:
            return outcome
        try:
            fresh = _accept_findings(outcome, inspect_rows)
            _bind_inspection(project, job["id"], request, (fresh, remote, inspect_rows))
        except (ValueError, OSError) as exc:
            return _failed_visual(str(exc), "inspection_mismatch", remote)
        if operation == "inspect":
            return {
                "status": "inspected",
                "remote": remote,
                "media": False,
                "findings": _observations_document(fresh),
            }
        try:
            _recheck_rows(rows)
        except (ValueError, OSError) as exc:
            return _failed_visual(str(exc), "stage", remote)
    observations = _handoff_observations(request, rows, fresh)
    inspected_ids = {_input_id(row) for row in inspect_rows}
    if not inspected_ids <= {item.get("id") for item in observations}:
        return _failed_visual(
            "Inspection findings do not match the attached image bytes. Nothing was marked inspected.",
            "inspection_mismatch",
            remote,
        )
    return generate_still(
        _production_prompt(request.get("prompt") or "", observations),
        workdir,
        images=_local_items(rows) or None,
        timeout=timeout,
        on_submitted=on_submitted,
        **session_options,
    )


def _produce_worker(project, job_id):  # noqa: C901 - Dispatch retains separate no-transport, staging, submission and recovery failure outcomes.
    job, _ledger = _claim(project, job_id)
    if job is None:
        return
    if os.environ.get(CRASH_ENV) == "submit":
        if os.environ.get(INLINE_ENV) == "1":
            return
        os._exit(1)
    request = job.get("request") or {}
    route = request.get("route")
    kind = request.get("kind")
    if route not in {"gpt-subscription", "grok-subscription", "openrouter"} or kind not in {"image", "video"}:
        _store_terminal(
            project,
            job_id,
            {
                "state": "failed",
                "message": "This AI route has no media transport for the frozen operation.",
                "code": "unsupported",
            },
        )
        return
    if route == "gpt-subscription" and kind != "image":
        _store_terminal(
            project,
            job_id,
            {"state": "failed", "message": "The GPT subscription route launches stills only.", "code": "unsupported"},
        )
        return
    if route in {"grok-subscription", "openrouter"}:
        try:
            beat_for(_ledger, request.get("beat"), request.get("inputs"))
        except ValueError as exc:
            _store_terminal(project, job_id, {"state": "failed", "message": str(exc), "code": "stale"})
            return
    workdir = _job_dir(_brolls_root(project), job_id)
    workdir.mkdir(parents=True, exist_ok=True)

    def on_submitted(remote):
        with project_lock(project):
            ledger = Ledger(project)
            current = (ledger.data.get("ai") or {}).get("jobs", {}).get(job_id)
            if not current:
                return
            current["submit_outcome"] = "accepted"
            current["state"] = "downloading" if remote.get("phase") == "downloading" else "remote_pending"
            current["remote"] = dict(remote or {})
            ledger.save("ai-submitted")
        _interrupt_worker("accepted")

    timeout = float(os.environ.get("GETBROLLS_AI_TIMEOUT") or TIMEOUT_S)
    if route == "gpt-subscription" and _visual_request(request):
        outcome = _produce_visual(project, job, workdir, timeout, on_submitted)
    elif route == "gpt-subscription":
        session_options = {"session_model": request["session_model"]} if request.get("session_model") else {}
        outcome = generate_still(
            request.get("prompt") or "", workdir, timeout=timeout, on_submitted=on_submitted, **session_options
        )
    elif route == "openrouter":
        from .ai_openrouter import produce

        outcome = produce(project, job, workdir, timeout=timeout, on_submitted=on_submitted)
    else:
        from .ai_grok import produce

        outcome = produce(project, job, workdir, timeout=timeout, on_submitted=on_submitted)
    _finish_outcome(project, job, outcome)


def _grok_retrievable(job):
    remote = job.get("remote") or {}
    request = job.get("request") or {}
    return (
        request.get("route") == "grok-subscription"
        and request.get("kind") == "video"
        and remote.get("transport") == "oauth-imagine"
        and bool(remote.get("requestId"))
    )


def _retrieve_job(project, job_id):
    from .ai_recovery import check_inputs

    with project_lock(project):
        ledger = Ledger(project)
        job = (ledger.data.get("ai") or {}).get("jobs", {}).get(job_id)
        if not job or job.get("state") == "complete":
            return None
        check_inputs(ledger, job)
        if (
            not _grok_retrievable(job)
            and not _gpt_retrievable(job)
            and not _openrouter_retrievable(job)
            and (not _recorded_artifact(job) or not (job.get("remote") or {}).get("artifact_sha256"))
        ):
            return None
        return job


def _retrieve_worker(project, job_id):
    from .ai_recovery import checked_artifact

    job = _retrieve_job(project, job_id)
    if job is None:
        return
    try:
        found = checked_artifact(Ledger(project, recover=False), job)
    except (ValueError, OSError):
        found = None
    if (_gpt_retrievable(job) or _grok_retrievable(job) or _openrouter_retrievable(job)) and found is None:
        if _openrouter_retrievable(job):
            from .ai_openrouter import retrieve
        elif _gpt_retrievable(job):
            from .ai_provider import retrieve_still as retrieve
        else:
            from .ai_grok import retrieve

        workdir = _job_dir(_brolls_root(project), job_id)
        workdir.mkdir(parents=True, exist_ok=True)
        outcome = retrieve(job, workdir, timeout=float(os.environ.get("GETBROLLS_AI_TIMEOUT") or TIMEOUT_S))
        _finish_outcome(project, job, outcome)
        return
    try:
        brolls = _brolls_root(project)
        if found is None:
            raise ValueError("The recorded local AI result is missing or changed.")
        if (job.get("request") or {}).get("kind") == "video":
            version = _ingest_video(brolls, job, found)
        else:
            version = _ingest_still(brolls, job, found)
    except (ValueError, OSError) as exc:
        _store_terminal(project, job_id, {"state": "failed", "message": str(exc), "code": "artifact"})
        return
    _commit_result(project, job_id, version)


def _commit_result(project, job_id, version, remote=None):
    with project_lock(project):
        ledger = Ledger(project)
        current = (ledger.data.get("ai") or {}).get("jobs", {}).get(job_id)
        if not current or current.get("state") == "complete":
            rel = version["path"]
            retained = (ledger.data.get("ai") or {}).get("versions", {}).values()
            if not any(row.get("path") == rel for row in retained):
                target = ledger.root / rel
                _chain_inside(ledger.root, target)
                target.unlink(missing_ok=True)
            return
        _merge_remote(current, remote)
        attach_result(ledger, current, version)
        ledger.save("ai-complete")
    _interrupt_worker("committed")


def _finish_outcome(project, job, outcome):  # noqa: C901, PLR0911 - Terminal inspection/media/unknown outcomes keep separate durable transitions.
    job_id = job["id"]
    with project_lock(project):
        ledger = Ledger(project)
        current = (ledger.data.get("ai") or {}).get("jobs", {}).get(job_id)
        if not current or current.get("state") == "complete":
            return
    status = (outcome or {}).get("status")
    remote = (outcome or {}).get("remote")
    if (outcome or {}).get("media") is True:
        _retain_unexpected_media(project, job_id, outcome)
        return
    if status == "inspected":
        _store_inspected(project, job_id, outcome)
        return
    if status == "complete":
        try:
            brolls = _brolls_root(project)
            workdir = _job_dir(brolls, job_id)
            original = _native_still_original(job, workdir, outcome)
            original_hash = digest(original)
            with project_lock(project):
                ledger = Ledger(project)
                current = ledger.data["ai"]["jobs"][job_id]
                if current.get("state") == "complete":
                    return
                recorded = current.get("remote") or {}
                if recorded.get("artifact_sha256") and recorded["artifact_sha256"] != original_hash:
                    raise ValueError("The retrieved provider result differs from the recorded original.")
                _merge_remote(current, remote)
                current["remote"] = dict(current.get("remote") or {})
                current["remote"]["artifact"] = original.relative_to(workdir).as_posix()
                current["remote"]["artifact_sha256"] = original_hash
                current["state"] = "downloading"
                current["submit_outcome"] = "accepted"
                ledger.save("ai-result-received")
            _interrupt_worker("artifact")
            if (job.get("request") or {}).get("kind") == "video":
                version = _ingest_video(brolls, job, original)
            else:
                version = _ingest_still(brolls, job, original)
        except (ValueError, OSError, KeyError) as exc:
            _store_terminal(
                project, job_id, {"state": "failed", "message": str(exc), "code": "artifact", "remote": remote}
            )
            return
        _commit_result(project, job_id, version, remote)
        return
    if status == "pending":
        _store_terminal(project, job_id, {"state": "remote_pending", "remote": remote})
        return
    if status == "unknown":
        _store_terminal(
            project,
            job_id,
            {
                "state": "unknown",
                "message": (outcome or {}).get("error") or "unknown",
                "code": "unknown",
                "remote": remote,
            },
        )
        return
    code = (outcome or {}).get("code") or status or "failed"
    if status in {"auth", "quota", "unsupported"} and code != "inspection_gate":
        code = status
    _store_terminal(
        project,
        job_id,
        {
            "state": "failed",
            "message": (outcome or {}).get("error") or status,
            "code": code,
            "remote": remote,
            "submit_outcome": (outcome or {}).get("submit_outcome"),
        },
    )


def _store_terminal(project, job_id, fields):
    with project_lock(project):
        ledger = Ledger(project)
        job = (ledger.data.get("ai") or {}).get("jobs", {}).get(job_id)
        if not job or job.get("state") == "complete":
            return
        state_name = fields["state"]
        job["state"] = state_name
        job["submit_outcome"] = (
            "unknown"
            if state_name == "unknown" and not _grok_retrievable(job) and not _openrouter_retrievable(job)
            else job.get("submit_outcome") or "accepted"
        )
        if fields.get("submit_outcome") == "rejected":
            job["submit_outcome"] = "rejected"
        job["error"] = (
            None if state_name == "remote_pending" else _error_payload(fields.get("message"), fields.get("code"))
        )
        _merge_remote(job, fields.get("remote"))
        unexpected = fields.get("unexpected_media")
        if isinstance(unexpected, dict):
            job["unexpected_media"] = _private_unexpected_media(unexpected)
        ledger.save("ai-" + state_name)


def _private_unexpected_media(unexpected):
    """Keep the unreviewed artifact accounted for. The public view does not receive its path."""
    stored = {"media": True, "generated": True, "sha256": unexpected.get("sha256"), "approval": None}
    artifact = unexpected.get("artifact")
    if isinstance(artifact, str) and _safe_artifact(artifact, {".png", ".jpg", ".jpeg"}):
        stored["artifact"] = artifact
    return stored


def _retain_unexpected_media(project, job_id, outcome):
    """A generated inspection file is a failed, unreviewed result. It is not deleted, retried, or approved."""
    private = {"media": True, "generated": True, "sha256": None, "approval": None}
    raw_sha = (outcome or {}).get("sha256")
    if (
        isinstance(raw_sha, str)
        and len(raw_sha) == hashlib.sha256().digest_size * 2
        and all(char in "0123456789abcdef" for char in raw_sha)
    ):
        private["sha256"] = raw_sha
    saved = (outcome or {}).get("path")
    if isinstance(saved, str) and saved:
        try:
            workdir = _job_dir(_brolls_root(project), job_id)
            resolved = _confined_original(workdir, Path(saved))
            private["sha256"] = digest(resolved)
            private["artifact"] = resolved.relative_to(workdir).as_posix()
        except (ValueError, OSError):
            pass
    _store_terminal(
        project,
        job_id,
        {
            "state": "failed",
            "message": (outcome or {}).get("error")
            or "Inspection observed generated media. The file is unreviewed and was not approved.",
            "code": "inspection_media",
            "remote": (outcome or {}).get("remote"),
            "unexpected_media": private,
        },
    )


def _store_inspected(project, job_id, outcome):
    with project_lock(project):
        ledger = Ledger(project)
        job = (ledger.data.get("ai") or {}).get("jobs", {}).get(job_id)
        if not job or job.get("state") == "complete":
            return
        job["state"] = "complete"
        job["result"] = None
        job["error"] = None
        job["submit_outcome"] = "accepted"
        _merge_remote(job, (outcome or {}).get("remote"))
        ledger.save("ai-inspected")


def _refuse_link(path):
    if path.is_symlink() or not path.is_file():
        raise ValueError("The native still is missing, a symlink, or not a regular file.")
    return path


def _native_still_original(job, workdir, outcome):
    """Retain a native Codex original from its exact thread/item location, without moving it."""
    saved = Path(outcome["path"]).absolute()
    if job["request"]["route"] != "gpt-subscription" or saved.is_relative_to(workdir):
        return _confined_original(workdir, saved)
    remote = outcome.get("remote") or {}
    thread = identifier(remote.get("threadId"), "Native thread")
    item = identifier(remote.get("imageItemId"), "Native image item")
    native_home = Path(os.environ.get("CODEX_HOME") or Path.home() / ".codex").absolute()
    expected = native_home / "generated_images" / thread / (item + ".png")
    # Reject uncollapsed links in either spelling before expanding Windows short names.
    _chain_inside(native_home, expected)
    _chain_inside(saved.parent.parent.parent, saved)
    if os.path.normcase(str(saved.resolve())) != os.path.normcase(str(expected.resolve())):
        raise ValueError("The native image is outside its recorded thread/item location.")
    with expected.open("rb") as stream:
        data = stream.read(MAX_IMAGE_BYTES + 1)
    if not data or len(data) > MAX_IMAGE_BYTES or not data.startswith(b"\x89PNG\r\n\x1a\n"):
        raise ValueError("The native original must be a bounded PNG image.")
    actual = hashlib.sha256(data).hexdigest()
    dest = workdir / ("native-" + item + ".png")
    _chain_inside(workdir, dest)
    if dest.exists():
        retained = _confined_original(workdir, dest)
        if digest(retained) != actual:
            raise ValueError("The retained native image differs from the original; no file was overwritten.")
        return retained
    with dest.open("xb") as stream:
        stream.write(data)
    retained = _confined_original(workdir, dest)
    if digest(retained) != actual:
        raise ValueError("The native image changed while being retained.")
    return retained


def _confined_original(workdir, saved):
    _chain_inside(workdir, saved)
    workdir = Path(workdir).resolve()
    path = _refuse_link(Path(saved))
    try:
        resolved = path.resolve()
    except OSError as exc:
        raise ValueError("The native still path could not be resolved.") from exc
    try:
        resolved.relative_to(workdir)
    except ValueError as exc:
        raise ValueError("The native still path escaped the job work directory.") from exc
    if resolved.is_symlink() or not resolved.is_file():
        raise ValueError("The native still is missing, a symlink, or not a regular file.")
    return resolved


def _probe_still(path):
    raw = run(
        [
            "ffprobe",
            "-v",
            "error",
            "-select_streams",
            "v:0",
            "-show_entries",
            "stream=width,height,codec_name,codec_type",
            "-of",
            "json",
            str(path),
        ],
        op="ai_probe",
    )
    data = json.loads(raw)
    videos = [row for row in (data.get("streams") or []) if row.get("codec_type") == "video"]
    if len(videos) != 1:
        raise ValueError("AI still must contain exactly one image stream.")
    stream = videos[0]
    codec = str(stream.get("codec_name") or "").lower()
    if codec not in STILL_CODECS:
        raise ValueError("AI still codec must be png or jpeg.")
    width = int(stream.get("width") or 0)
    height = int(stream.get("height") or 0)
    if width <= 0 or height <= 0:
        raise ValueError("AI still measurements are missing.")
    run(
        ["ffmpeg", "-v", "error", "-xerror", "-i", str(path), "-f", "null", "-"],
        op="ai_decode",
    )
    return {"width": width, "height": height, "codec": codec}


def _ingest_still(brolls, job, saved_path):
    brolls = _brolls_root(brolls.parent)
    request = job["request"]
    workdir = _job_dir(brolls, job["id"])
    original = _confined_original(workdir, saved_path)
    info = _probe_still(original)
    original_hash = digest(original)
    version_id = "still-" + uuid.uuid4().hex[:12]
    rel = "previews/ai-" + version_id + STILL_CODECS[info["codec"]]
    dest = brolls / rel
    _chain_inside(brolls, dest.parent)
    if dest.exists() or dest.is_symlink():
        raise ValueError("AI preview path already exists and will not be overwritten.")
    dest.parent.mkdir(parents=True, exist_ok=True)
    _chain_inside(brolls, dest.parent)
    shutil.copyfile(original, dest)
    if dest.is_symlink() or not dest.is_file():
        dest.unlink(missing_ok=True)
        raise ValueError("AI preview copy is not a regular confined file.")
    copy_info = _probe_still(dest)
    copy_hash = digest(dest)
    if copy_hash != original_hash or (copy_info["width"], copy_info["height"], copy_info["codec"]) != (
        info["width"],
        info["height"],
        info["codec"],
    ):
        dest.unlink(missing_ok=True)
        raise ValueError("AI preview copy does not match the original still.")
    return {
        "id": version_id,
        "beat": request["beat"],
        "kind": "image",
        "alternative": request.get("alternative"),
        "path": rel,
        "sha256": copy_hash,
        "original_sha256": original_hash,
        "inputs": request["inputs"],
        "width": copy_info["width"],
        "height": copy_info["height"],
        "codec": copy_info["codec"],
        "job": job["id"],
        "approval": {"state": "pending"},
    }


def _probe_clip(path):
    raw = run(
        ["ffprobe", "-v", "error", "-show_streams", "-show_format", "-of", "json", str(path)],
        op="ai_probe_video",
    )
    data = json.loads(raw)
    streams = data.get("streams") or []
    videos = [
        row
        for row in streams
        if row.get("codec_type") == "video" and not (row.get("disposition") or {}).get("attached_pic")
    ]
    if len(videos) != 1:
        raise ValueError("AI video must contain exactly one video stream.")
    stream = videos[0]
    rate = str(stream.get("avg_frame_rate") or "0/1")
    parts = rate.split("/", 1)
    numerator = float(parts[0] or 0)
    denominator = float(parts[1] if len(parts) > 1 else 1)
    fps = numerator / denominator if denominator else 0
    duration = float((data.get("format") or {}).get("duration") or 0)
    width = int(stream.get("width") or 0)
    height = int(stream.get("height") or 0)
    if width <= 0 or height <= 0 or fps <= 0 or duration <= 0:
        raise ValueError("AI video measurements are missing.")
    run(["ffmpeg", "-v", "error", "-xerror", "-i", str(path), "-f", "null", "-"], op="ai_decode_video")
    return {
        "width": width,
        "height": height,
        "codec": str(stream.get("codec_name") or ""),
        "fps": fps,
        "duration_s": duration,
        "audio": any(row.get("codec_type") == "audio" for row in streams),
    }


def _measured_seconds(value):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value)


def _video_coverage(request, info):
    raw_interval = request.get("interval")
    interval = raw_interval if isinstance(raw_interval, dict) else {}
    start = _measured_seconds(interval.get("start_s"))
    end = _measured_seconds(interval.get("end_s"))
    if start is None or end is None:
        return "short"
    length = end - start
    short = info["duration_s"] + (1.0 / info["fps"]) < length
    return "short" if short else "covered"


def _native_full_hd(request, info):
    if request.get("resolution") in {"480p", "720p"}:
        return False
    return info["width"] >= FULL_HD_WIDTH and info["height"] >= FULL_HD_HEIGHT


def _ingest_video(brolls, job, saved_path):
    brolls = _brolls_root(brolls.parent)
    request = job["request"]
    workdir = _job_dir(brolls, job["id"])
    original = _confined_original(workdir, saved_path)
    info = _probe_clip(original)
    original_hash = digest(original)
    version_id = "clip-" + uuid.uuid4().hex[:12]
    rel = "clips/ai-" + version_id + ".mp4"
    dest = brolls / rel
    _chain_inside(brolls, dest.parent)
    if dest.exists() or dest.is_symlink():
        raise ValueError("AI video path already exists and will not be overwritten.")
    dest.parent.mkdir(parents=True, exist_ok=True)
    _chain_inside(brolls, dest.parent)
    shutil.copyfile(original, dest)
    if dest.is_symlink() or not dest.is_file():
        dest.unlink(missing_ok=True)
        raise ValueError("AI video copy is not a regular confined file.")
    copy_info = _probe_clip(dest)
    copy_hash = digest(dest)
    if copy_hash != original_hash or (copy_info["width"], copy_info["height"]) != (info["width"], info["height"]):
        dest.unlink(missing_ok=True)
        raise ValueError("AI video copy does not match the original file.")
    still = request.get("still") if isinstance(request.get("still"), dict) else {}
    return {
        "id": version_id,
        "beat": request["beat"],
        "kind": "video",
        "path": rel,
        "sha256": copy_hash,
        "original_sha256": original_hash,
        "inputs": request["inputs"],
        "width": copy_info["width"],
        "height": copy_info["height"],
        "codec": copy_info["codec"],
        "fps": copy_info["fps"],
        "duration_s": copy_info["duration_s"],
        "audio": copy_info["audio"],
        "resolution": request.get("resolution"),
        "native_full_hd": _native_full_hd(request, copy_info),
        "coverage": _video_coverage(request, copy_info),
        "still": {"id": still.get("id"), "sha256": still.get("sha256")},
        "job": job["id"],
        "approval": {"state": "pending"},
    }


def worker_main(argv=None):
    parser = argparse.ArgumentParser(prog="getbrolls.ai")
    parser.add_argument("--worker", action="store_true", required=True)
    parser.add_argument("--project", required=True)
    parser.add_argument("--job", required=True)
    parser.add_argument("--retrieve", action="store_true")
    args = parser.parse_args(argv)
    run_worker(args.project, args.job, retrieve=args.retrieve)
    return 0


if __name__ == "__main__":
    raise SystemExit(worker_main())
