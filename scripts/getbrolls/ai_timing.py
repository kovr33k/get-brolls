"""Recorded-narration timing for one AI beat, and the first explicit video launch.

Timing reads a completed narration analysis. It does not transcribe, and it does
not create a generation job. Video launch freezes the exact approved still and
the resolved interval, then returns one queued native job.
"""

from __future__ import annotations

import math
import uuid
from pathlib import Path
from typing import TypeGuard

from .ai_state import (
    beat_for,
    checked_version,
    fingerprint,
    new_job,
    quality_text,
    sanitize_public_text,
    text,
    version_signature,
)
from .models import now

VIDEO_TOOLS = ("reference_to_video", "image_to_video")
RESOLUTIONS = ("480p", "720p")
_SOUND = ("speech", "music", "atmosphere", "effects")
_SHORT_INTERVAL_S = 8


def prepare_timing(ledger, beat_id, analysis_id, *, still=None, expected=None):
    beat = beat_for(ledger, beat_id, expected)
    timing = _bind(ledger, beat, analysis_id, still=still)
    beat["timing"] = timing
    ledger.save("ai-timing")
    return public_timing(timing)


def resolve_timing(ledger, beat_id, analysis_id, review):
    from .narration_alignment import alignment_readiness, correct_match

    if not isinstance(review, dict):
        raise ValueError("The interval correction must name the reviewer and the statement.")
    by = review.get("by")
    statement = review.get("statement")
    candidate = review.get("candidate")
    start = review.get("start")
    end = review.get("end")
    expected = review.get("expected")
    beat = beat_for(ledger, beat_id, expected)
    timing = beat.get("timing")
    if not isinstance(timing, dict) or not isinstance(timing.get("match"), dict):
        raise ValueError("Match the recording before resolving an interval.")
    if timing.get("analysis_id") != analysis_id:
        raise ValueError("Resolve the interval for the same completed analysis.")
    updated = correct_match(
        timing["match"],
        candidate_id=candidate,
        start_s=start,
        end_s=end,
        by=text(by, "Reviewer", 200),
        statement=text(statement, "Correction statement"),
        at=now(),
    )
    analysis, recording, _match_result, snapshot = _intact(ledger, analysis_id)
    passage = _passage(beat)
    profile = _profile(ledger)
    ready = alignment_readiness(
        updated,
        analysis={"id": analysis.get("id"), "result": analysis.get("result")},
        recording=_recording(recording),
        passage=passage,
        profile=profile,
    )
    timing["match"] = updated
    timing["identity"] = fingerprint(_narration_identity(analysis, recording))
    timing["readiness"] = {"resolved": ready["resolved"], "reasons": list(ready["reasons"])}
    timing["profile"] = {"fps": profile.get("fps"), "frame_rounding": profile.get("frame_rounding")}
    preview, error, record = _maybe_preview(
        ledger,
        beat,
        ready,
        {"snapshot": snapshot, "recording": recording, "profile": profile},
        timing,
    )
    timing["preview"] = preview
    timing["preview_error"] = sanitize_public_text(error) if error else None
    timing["preview_record"] = record
    beat["timing"] = timing
    ledger.save("ai-timing-resolve")
    return public_timing(timing)


def launch_video(ledger, payload, nonce, *, paid=None):
    return new_job(ledger, video_request(ledger, payload, nonce, paid=paid), nonce)


def video_request(ledger, payload, nonce, *, paid=None):
    if not isinstance(payload, dict):
        raise ValueError("The video launch must name the approved still and frozen native tool.")
    beat = beat_for(ledger, payload.get("beat"), payload.get("expected") or payload.get("inputs"))
    version, _path = checked_version(ledger, payload.get("version"), approved=True, kind="image")
    if version.get("beat") != beat["id"]:
        raise ValueError("The approved still belongs to a different beat.")
    timing = beat.get("timing")
    if not isinstance(timing, dict):
        raise ValueError("Resolve the recorded narration interval before generating video.")
    ready = _recheck(ledger, beat, timing)
    if not ready["resolved"] or not isinstance(ready.get("timing"), dict):
        raise ValueError("The recorded interval is unresolved. Video was not submitted.")
    raw_still = timing.get("still")
    bound = raw_still if isinstance(raw_still, dict) else None
    if bound and (bound.get("id") != version["id"] or bound.get("sha256") != version["sha256"]):
        raise ValueError("The resolved interval is bound to a different still.")
    timing["still"] = {"id": version["id"], "sha256": version["sha256"]}
    model, tool = (paid["model"], "image_to_video") if paid else _freeze_native_choice(ledger, payload)
    resolution = paid["resolution"] if paid else payload.get("resolution") or "480p"
    if not paid and resolution not in RESOLUTIONS:
        raise ValueError("Native video resolution is 480p or 720p. That is not native Full HD.")
    sound = _sound(payload)
    interval = ready["timing"]
    length = float(interval["end_s"]) - float(interval["start_s"])
    if length <= 0:
        raise ValueError("The recorded interval is empty. Video was not submitted.")
    requested = (
        6 if length <= _SHORT_INTERVAL_S else 10 if tool == "image_to_video" else min(15, max(1, math.floor(length)))
    )
    requested = paid["duration"] if paid else requested
    style = (ledger.data.get("ai") or {}).get("style") or {}
    style_prompt = (
        text(style.get("prompt"), "Agreed AI visual style") if isinstance(style, dict) and style.get("prompt") else ""
    )
    if not style_prompt:
        raise ValueError("Agree an AI visual style before generating video.")
    quality = quality_text(style if isinstance(style, dict) else {})
    raw_profile = timing.get("profile")
    profile = raw_profile if isinstance(raw_profile, dict) else {}
    motion = _motion(beat, version)
    nonce = text(nonce, "Request identity", 160)
    request = {
        "beat": beat["id"],
        "inputs": beat["fingerprint"],
        "kind": "video",
        "route": "openrouter" if paid else "grok-subscription",
        "model": model,
        "tool": tool,
        "resolution": resolution,
        "still": {"id": version["id"], "sha256": version["sha256"], "signature": version_signature(version)},
        "interval": {
            "start_s": interval.get("start_s"),
            "end_s": interval.get("end_s"),
            "start_frame": interval.get("start_frame"),
            "end_frame": interval.get("end_frame"),
        },
        "profile": {"fps": profile.get("fps"), "frame_rounding": profile.get("frame_rounding")},
        "narration": ready["narration"],
        "sound": sound,
        "motion": motion,
        "requested_duration_s": requested,
        "quality": quality,
        "alternative": version.get("alternative") or beat.get("selected"),
        "prompt": _video_prompt(
            style_prompt,
            quality,
            {"motion": motion, "sound": sound, "resolution": resolution, "requested": requested},
        ),
        "session_id": str(uuid.UUID(fingerprint({"nonce": nonce, "still": version["sha256"]})[:32])),
    }
    if paid:
        request["paid"] = paid
    return request


def checked_video_input(ledger, request):
    """Recheck the frozen still and narration interval immediately before dispatch."""
    beat = beat_for(ledger, request.get("beat"), request.get("inputs"))
    still = request.get("still") or {}
    version, path = checked_version(ledger, still.get("id"), approved=True, kind="image")
    if (
        version.get("beat") != beat["id"]
        or version.get("sha256") != still.get("sha256")
        or version_signature(version) != still.get("signature")
    ):
        raise ValueError("The frozen approved first frame changed before video submission.")
    ready = current_readiness(ledger, beat, beat.get("timing"))
    timing = ready.get("timing") or {}
    interval = {key: timing.get(key) for key in ("start_s", "end_s", "start_frame", "end_frame")}
    expected_interval = request.get("interval")
    if request.get("sequence"):
        from .ai_sequences import checked_child

        expected_interval = checked_child(ledger, request)["scope"]["request"]["interval"]
    if not ready.get("resolved") or interval != expected_interval:
        raise ValueError("The frozen narration interval changed before video submission.")
    if ready.get("narration") != request.get("narration"):
        raise ValueError("The frozen recording or analysis identity changed before video submission.")
    profile = _profile(ledger)
    if {key: profile.get(key) for key in ("fps", "frame_rounding")} != request.get("profile"):
        raise ValueError("The video profile changed before submission.")
    return path


def explicit_native_video(raw):
    """Validate an agent-recorded model and tool. This does not discover or guess either."""
    if raw is None:
        return None
    if not isinstance(raw, dict):
        raise ValueError("Native video setup must name the model and tool. No model is guessed.")
    model = text(raw.get("model"), "Native model", 200)
    tool = raw.get("tool")
    if tool not in VIDEO_TOOLS:
        raise ValueError("Native video setup must name reference_to_video or image_to_video. No tool is guessed.")
    if raw.get("route") not in (None, "grok-subscription"):
        raise ValueError("Native video setup cannot switch to a paid API route.")
    if raw.get("capability") not in (None, "unverified"):
        raise ValueError("Native video capability is not established.")
    return {"route": "grok-subscription", "model": model, "tool": tool, "capability": "unverified"}


def recorded_native_video(ai):
    raw = ai.get("native_video") if isinstance(ai, dict) else None
    if raw is None:
        return None
    try:
        return explicit_native_video(raw)
    except ValueError:
        return None


def public_native_video(ai):
    setup = recorded_native_video(ai)
    if not setup:
        return {
            "route": "grok-subscription",
            "model": None,
            "tool": None,
            "capability": "unverified",
            "message": (
                "Native Grok video is unverified. Record the model and tool in the project plan. "
                "No model was guessed and no paid route was selected."
            ),
        }
    return {
        **setup,
        "message": (
            "Grok OAuth video uses the exact approved first frame and saved narration interval. "
            "Account access and quota are checked at launch. Unsupported models fail before submission; no API-key fallback."
        ),
    }


def _freeze_native_choice(ledger, payload):
    supplied_model = payload.get("model")
    supplied_tool = payload.get("tool")
    setup = recorded_native_video(ledger.data.get("ai"))
    model = supplied_model if isinstance(supplied_model, str) and supplied_model.strip() else (setup or {}).get("model")
    tool = supplied_tool or (setup or {}).get("tool")
    if not isinstance(model, str) or not model.strip():
        raise ValueError("Record the native model in project setup. The launch will not guess one.")
    model = text(model, "Native model", 200)
    if tool not in VIDEO_TOOLS:
        raise ValueError(
            "Record reference_to_video or image_to_video in project setup. The launch will not choose a tool."
        )
    ai = ledger.data.setdefault("ai", {})
    ai["native_video"] = {
        "route": "grok-subscription",
        "model": model,
        "tool": tool,
        "capability": "unverified",
    }
    return model, tool


def _mapping(value):
    return value if isinstance(value, dict) else {}


def _sequence(value):
    return value if isinstance(value, list) else []


def public_timing(timing):
    """Snapshot written with a fresh match. Later status reads recheck the binding."""
    if not isinstance(timing, dict):
        return None
    match = _mapping(timing.get("match"))
    readiness = _mapping(timing.get("readiness"))
    interval = _mapping(match.get("timing"))
    candidates = _public_candidates(match.get("candidates"))
    preview = timing.get("preview")
    if not _safe_preview_rel(preview):
        preview = None
    error = timing.get("preview_error")
    if not isinstance(error, str) or not error.strip():
        error = None
    if error:
        preview = None
    raw_still = timing.get("still")
    still = raw_still if isinstance(raw_still, dict) else None
    return {
        "state": match.get("state"),
        "resolved": bool(readiness.get("resolved")),
        "reasons": [item for item in _sequence(readiness.get("reasons")) if isinstance(item, str)],
        "start_s": interval.get("start_s"),
        "end_s": interval.get("end_s"),
        "ambiguous": match.get("state") == "uncertain",
        "candidates": candidates,
        "preview": preview,
        "preview_error": error,
        "recording_id": timing.get("recording_id"),
        "analysis_id": timing.get("analysis_id"),
        "identity": timing.get("identity"),
        "still": still.get("id") if still else None,
    }


def _bind(ledger, beat, analysis_id, *, still):
    from .narration_alignment import alignment_readiness, match_passages

    analysis, recording, match_result, snapshot = _intact(ledger, analysis_id)
    if analysis.get("id") != analysis_id:
        raise ValueError("Match the named completed analysis. Timing does not transcribe.")
    passage = _passage(beat)
    profile = _profile(ledger)
    records = match_passages(
        match_result,
        [passage],
        analysis_id=analysis.get("id"),
        recording_id=recording.get("id"),
        recording_sha256=recording.get("sha256"),
        recording_duration_s=recording.get("duration_s"),
        fps=profile.get("fps"),
    )
    record = records.get(beat["id"])
    if not isinstance(record, dict):
        raise ValueError("The narration match did not return this beat.")
    ready = alignment_readiness(
        record,
        analysis={"id": analysis.get("id"), "result": analysis.get("result")},
        recording=_recording(recording),
        passage=passage,
        profile=profile,
    )
    bound = _still_binding(ledger, beat, still)
    previous = beat.get("timing") if isinstance(beat.get("timing"), dict) else None
    preview, error, preview_record = _maybe_preview(
        ledger,
        beat,
        ready,
        {"snapshot": snapshot, "recording": recording, "profile": profile},
        previous,
    )
    return {
        "analysis_id": analysis.get("id"),
        "identity": fingerprint(_narration_identity(analysis, recording)),
        "recording_id": recording.get("id"),
        "recording_sha256": recording.get("sha256"),
        "recording_duration_s": recording.get("duration_s"),
        "transcript_sha256": record.get("transcript_sha256"),
        "match": record,
        "profile": {"fps": profile.get("fps"), "frame_rounding": profile.get("frame_rounding")},
        "passage": passage,
        "still": bound,
        "readiness": {"resolved": ready["resolved"], "reasons": list(ready["reasons"])},
        "preview": preview,
        "preview_error": sanitize_public_text(error) if error else None,
        "preview_record": preview_record,
    }


def current_readiness(ledger, beat, timing):
    """Re-read recording, analysis, transcript and profile. This does not save."""
    if not isinstance(timing, dict) or not isinstance(timing.get("match"), dict):
        return {"resolved": False, "reasons": ["unresolved_match"], "timing": None}
    return _recheck(ledger, beat, timing)


def _recheck(ledger, beat, timing):
    from .narration_alignment import alignment_readiness

    analysis, recording, _match_result, _snapshot = _intact(ledger, timing.get("analysis_id"))
    profile = _profile(ledger)
    ready = alignment_readiness(
        timing.get("match"),
        analysis={"id": analysis.get("id"), "result": analysis.get("result")},
        recording=_recording(recording),
        passage=_passage(beat),
        profile=profile,
    )
    ready["narration"] = _narration_identity(analysis, recording)
    return ready


def _narration_identity(analysis, recording):
    return {
        "analysis_id": analysis.get("id"),
        "analysis_sha256": (analysis.get("result") or {}).get("artifact_sha256"),
        "recording_id": recording.get("id"),
        "recording_sha256": recording.get("sha256"),
        "input_fingerprint": analysis.get("input_fingerprint"),
    }


def _intact(ledger, analysis_id):
    from .graphics import _require_intact_analysis

    if not isinstance(analysis_id, str) or not analysis_id:
        raise ValueError("Name the completed narration analysis. Timing does not transcribe.")
    return _require_intact_analysis(ledger, analysis_id)


def _recording(recording):
    return {
        "id": recording.get("id"),
        "sha256": recording.get("sha256"),
        "duration_s": recording.get("duration_s"),
    }


def _passage(beat):
    return {
        "occurrence_id": beat["id"],
        "narration": beat["text"],
        "chapter_context": beat.get("chapter_context") or beat["text"],
        "anchors": [],
        "order": 0,
    }


def _profile(ledger):
    from .graphics import default_profile

    graphics = ledger.data.get("graphics")
    if isinstance(graphics, dict) and isinstance(graphics.get("profile"), dict):
        profile = graphics["profile"]
        if profile.get("fps") and profile.get("frame_rounding"):
            return profile
    return default_profile()


def _still_binding(ledger, beat, still):
    if not still:
        return None
    version, _path = checked_version(ledger, still, kind="image")
    if version.get("beat") != beat["id"]:
        raise ValueError("The still belongs to a different beat.")
    return {"id": version["id"], "sha256": version["sha256"]}


_OCCUPIED_PREVIEW = (
    "The cached narration preview does not match this interval. The existing file was kept and was not replaced."
)
_LINK_PREVIEW = "The narration preview path is a link or junction and was not followed."
_MISSING_PREVIEW = "The narration preview is missing and was not created during viewing."
_UNVERIFIED_PREVIEW = "The narration preview could not be verified. No excerpt was created."


def _canonical_number(value):
    if type(value) is bool or type(value) not in (int, float) or not math.isfinite(float(value)):
        return None
    number = float(value)
    if number.is_integer():
        return int(number)
    return number


def _interval_duration(start_s, end_s):
    start = _canonical_number(start_s)
    end = _canonical_number(end_s)
    if start is None or end is None or end <= start:
        return None
    return float(end) - float(start)


def _preview_identity(recording_sha, start_s, end_s, fps):
    return fingerprint(
        {
            "recording": recording_sha,
            "start": _canonical_number(start_s),
            "end": _canonical_number(end_s),
            "fps": _canonical_number(fps),
        }
    )


_MAX_PREVIEW_PATH_CHARS = 240


def _safe_preview_rel(rel) -> TypeGuard[str]:
    if not isinstance(rel, str) or not rel.startswith("previews/ai-vo-") or len(rel) > _MAX_PREVIEW_PATH_CHARS:
        return False
    if "\\" in rel or ":" in rel or "\0" in rel:
        return False
    return all(part and part not in {".", ".."} for part in rel.split("/"))


def _link_or_junction(path):
    from .graphics_audio import _is_link_or_junction

    path = Path(path)
    try:
        if path.is_symlink() or _is_link_or_junction(path):
            return True
    except OSError:
        return True
    return False


def _path_occupied(path):
    path = Path(path)
    try:
        return path.exists() or path.is_symlink() or _link_or_junction(path)
    except OSError:
        return True


def _preview_failure(path):
    path = Path(path)
    if _link_or_junction(path):
        return _LINK_PREVIEW
    try:
        if path.exists():
            return _OCCUPIED_PREVIEW
    except OSError:
        return _OCCUPIED_PREVIEW
    return _MISSING_PREVIEW


def _preview_record(rel, identity, *, sha=None, duration=None, error=None):
    payload = {"ref": rel, "identity_sha256": identity}
    if error:
        payload["error"] = error
        return payload
    payload["sha256"] = sha
    payload["duration_s"] = duration
    return payload


def _matches_excerpt(root, rel, record, expected_duration, fps):
    """Reuse only a confined file whose frozen hash and decoded duration match this interval."""
    from .graphics_audio import MAX_VO_BYTES, MAX_VO_DURATION_S, _confine_existing, _probe_audio, _sha256
    from .ledger import digest

    if (
        not isinstance(record, dict)
        or record.get("error")
        or record.get("ref") != rel
        or not _sha256(record.get("sha256"))
        or expected_duration is None
        or not fps
    ):
        return False
    try:
        dest = _confine_existing(root, rel, ("previews/",))
        if digest(dest) != record["sha256"]:
            return False
        info = _probe_audio(dest, max_bytes=MAX_VO_BYTES, max_duration_s=MAX_VO_DURATION_S)
        return abs(float(info["duration_s"]) - float(expected_duration)) <= (1.0 / float(fps))
    except (OSError, TypeError, ValueError):
        return False


def _extract_preview(root, rel, snapshot, interval, fps):
    from .ai import _chain_inside
    from .graphics_audio import _confine_planned, _extract_vo_excerpt

    dest = Path(root) / rel
    dest.parent.mkdir(parents=True, exist_ok=True)
    _chain_inside(root, dest.parent)
    planned = _confine_planned(root, dest)
    return _extract_vo_excerpt(snapshot, planned, interval.get("start_s"), interval.get("end_s"), fps)


def _maybe_preview(ledger, beat, ready, source, previous=None):
    if not ready.get("resolved") or not isinstance(ready.get("timing"), dict):
        return None, None, None
    interval = ready["timing"]
    recording = _mapping(source.get("recording"))
    profile = _mapping(source.get("profile"))
    start_s = interval.get("start_s")
    end_s = interval.get("end_s")
    duration = _interval_duration(start_s, end_s)
    fps = profile.get("fps")
    if duration is None or not fps:
        return None, "VO excerpt clocks must be a finite interval.", None
    identity = _preview_identity(recording.get("sha256"), start_s, end_s, fps)
    rel = f"previews/ai-vo-{beat['id']}-{identity[:12]}.wav"
    root = Path(ledger.root)
    dest = root / rel
    prior = previous.get("preview_record") if isinstance(previous, dict) else None
    if _path_occupied(dest):
        valid = _mapping(prior).get("identity_sha256") == identity and _matches_excerpt(root, rel, prior, duration, fps)
        return (
            (rel, None, prior)
            if valid
            else (None, _preview_failure(dest), _preview_record(rel, identity, error="occupied_preview"))
        )
    if source.get("snapshot") is None:
        return None, _MISSING_PREVIEW, _preview_record(rel, identity, error="missing_preview")
    try:
        excerpt_hash, excerpt_duration = _extract_preview(root, rel, source.get("snapshot"), interval, fps)
    except (OSError, ValueError) as exc:
        occupied = _path_occupied(dest)
        message = (
            _preview_failure(dest)
            if occupied
            else (sanitize_public_text(exc) or "The narration preview could not be extracted.")
        )
        code = "occupied_preview" if occupied else "extraction_failed"
        return None, message, _preview_record(rel, identity, error=code)
    return rel, None, _preview_record(rel, identity, sha=excerpt_hash, duration=excerpt_duration)


def preview_for_view(ledger, timing, *, resolved):
    """Report a cached excerpt without extracting, repairing, or replacing it."""
    if not isinstance(timing, dict) or not resolved:
        return None, None
    record = timing.get("preview_record")
    if not isinstance(record, dict):
        rel = timing.get("preview")
        error = (
            _preview_failure(Path(ledger.root) / rel)
            if (_safe_preview_rel(rel) and _path_occupied(Path(ledger.root) / rel))
            else None
        )
        return None, error
    if record.get("error"):
        rel = record.get("ref")
        error = (
            _LINK_PREVIEW
            if _safe_preview_rel(rel) and _link_or_junction(Path(ledger.root) / rel)
            else (_OCCUPIED_PREVIEW if record.get("error") == "occupied_preview" else _UNVERIFIED_PREVIEW)
        )
        return None, error
    interval = _mapping(_mapping(timing.get("match")).get("timing"))
    profile = _mapping(timing.get("profile"))
    start_s = interval.get("start_s")
    end_s = interval.get("end_s")
    duration = _interval_duration(start_s, end_s)
    fps = profile.get("fps")
    identity = _preview_identity(timing.get("recording_sha256"), start_s, end_s, fps)
    rel = record.get("ref")
    if not _safe_preview_rel(rel) or record.get("identity_sha256") != identity:
        return None, _UNVERIFIED_PREVIEW
    root = Path(ledger.root)
    if _matches_excerpt(root, rel, record, duration, fps):
        return rel, None
    dest = root / rel
    return None, _preview_failure(dest) if _path_occupied(dest) else _MISSING_PREVIEW


def _public_candidates(candidates):
    rows = []
    for row in _sequence(candidates):
        if not isinstance(row, dict) or not row.get("id"):
            continue
        recognized = row.get("recognized_text")
        rows.append(
            {
                "id": row.get("id"),
                "text": sanitize_public_text(recognized, limit=240) if isinstance(recognized, str) else "",
                "start_s": row.get("start_s"),
                "end_s": row.get("end_s"),
            }
        )
    return rows


def _sound(payload):
    sound = {}
    for name in _SOUND:
        if name not in payload or payload.get(name) is None:
            sound[name] = False
            continue
        value = payload.get(name)
        if type(value) is not bool:
            raise ValueError(name + " must be an explicit boolean.")
        sound[name] = value
    return sound


def _motion(beat, version):
    alternative = version.get("alternative") or beat.get("selected")
    for row in beat.get("alternatives") or []:
        if row.get("id") == alternative and str(row.get("motion") or "").strip():
            return str(row.get("motion")).strip()
    return "Hold the approved still as the first frame."


def _video_prompt(style_prompt, quality, policy):
    motion = policy["motion"]
    sound = policy["sound"]
    resolution = policy["resolution"]
    requested = policy["requested"]
    lines = [
        "Generate one video whose first frame is exactly the supplied still. Do not create a new starting image.",
        f"Requested duration: {requested}s. Requested resolution: {resolution}. Measure actual output; do not claim upscale as native Full HD.",
        "Agreed visual style: " + style_prompt,
        "Agreed quality: " + quality,
        "Motion: " + motion,
        "Narration stays a separate recording and must not be spoken inside the clip.",
    ]
    if not sound["speech"]:
        lines.append("Do not add speech, spoken words, or voices.")
    else:
        lines.append("Speech was explicitly requested.")
    if not sound["music"]:
        lines.append("Do not add music.")
    else:
        lines.append("Music was explicitly requested.")
    if sound["atmosphere"]:
        lines.append("Atmosphere may be included.")
    if sound["effects"]:
        lines.append("Effects may be included.")
    lines.append("The clip is generated illustration, not documentary evidence.")
    return "\n".join(lines)
