"""Bounded ordered AI clips covering one resolved recorded narration interval."""

from __future__ import annotations

import copy
import json
import math
import tempfile
import uuid
from pathlib import Path

from .ai_state import (
    beat_for,
    checked_version,
    digest,
    fingerprint,
    identifier,
    new_job,
    public_job,
    public_version,
    sanitize_public_text,
    text,
    validate_operation_corrections,
    version_signature,
)
from .ai_timing import _motion, _profile, _video_prompt, checked_video_input, preview_for_view, video_request
from .ledger import Ledger
from .media import run
from .models import now
from .runtime import project_lock

MAX_CLIPS = 32


class CoverageShortfallError(ValueError):
    """Retained media cannot cover its planned placement without inventing video."""


def _scope(ledger, data, nonce, *, paid=None):
    request = video_request(ledger, data, nonce, paid=paid)
    fps = request["profile"]["fps"]
    interval = request["interval"]
    frames = interval["end_frame"] - interval["start_frame"]
    allowed = (6, 10) if request["tool"] == "image_to_video" else tuple(range(1, 16))
    duration = paid["duration"] if paid else data.get("clip_duration_s", max(allowed))
    if type(duration) is not int or (not paid and duration not in allowed):
        raise ValueError("Choose a clip length supported by the recorded video route.")
    per_clip = int(duration * fps)
    if frames <= 0 or per_clip <= 0 or math.ceil(frames / per_clip) > MAX_CLIPS:
        raise ValueError("A sequence must cover a nonempty interval with at most 32 explicitly planned clips.")
    clips = [
        {"start_frame": start, "end_frame": min(frames, start + per_clip), "still": request["still"]}
        for start in range(0, frames, per_clip)
    ]
    stills = data.get("stills")
    if stills is not None:
        if not isinstance(stills, list) or len(stills) != len(clips) or stills[0] != request["still"]["id"]:
            raise ValueError("Choose one approved first frame per planned clip, starting with the timing-bound still.")
        beat = beat_for(ledger, request["beat"])
        for clip, version_id in zip(clips, stills, strict=True):
            version, _path = checked_version(ledger, version_id, approved=True, kind="image")
            if version["beat"] != beat["id"]:
                raise ValueError("Every sequence still must belong to this beat.")
            clip["still"] = {"id": version["id"], "sha256": version["sha256"], "signature": version_signature(version)}
    for clip in clips:
        version = ledger.data["ai"]["versions"][clip["still"]["id"]]
        clip["motion"] = _motion(beat_for(ledger, request["beat"]), version)
    return {
        "request": request,
        "style": ledger.data["ai"]["style"]["prompt"],
        "profile": _profile(ledger),
        "clip_duration_s": duration,
        "frames": frames,
        "clips": clips,
    }


def _prepare(ledger, data, nonce, *, paid=None):
    ai = ledger.data["ai"]
    scope = _scope(ledger, data, nonce, paid=paid)
    signature = fingerprint(scope)
    sequences = ai.setdefault("sequences", {})
    previous = next((row for row in sequences.values() if row["nonce"] == nonce), None)
    if previous:
        if previous["fingerprint"] != signature:
            raise ValueError("This sequence request identity already belongs to different frozen inputs.")
        return previous
    ident = "sequence-" + uuid.uuid4().hex
    record = {
        "id": ident,
        "nonce": nonce,
        "scope": scope,
        "fingerprint": signature,
        "jobs": [],
        "version": None,
        "launched": None,
        "created_at": now(),
        "error": None,
    }
    sequences[ident] = record
    for index in range(len(scope["clips"])):
        request = _clip_request(record, index)
        job = new_job(ledger, request, "seq-" + fingerprint({"nonce": nonce, "index": index}))
        job["state"] = "awaiting_confirmation"
        record["jobs"].append(job["id"])
    beat_for(ledger, scope["request"]["beat"])["sequence"] = ident
    return record


def _clip_request(record, index):
    scope = record["scope"]
    base = scope["request"]
    clip = scope["clips"][index]
    fps = base["profile"]["fps"]
    request = copy.deepcopy(base)
    requested = scope["clip_duration_s"]
    if request["route"] != "openrouter" and request["tool"] == "reference_to_video":
        requested = math.ceil((clip["end_frame"] - clip["start_frame"]) / fps)
    request.update(
        sequence=record["id"],
        sequence_index=index,
        sequence_scope=record["fingerprint"],
        still=clip["still"],
        motion=clip["motion"],
        requested_duration_s=requested,
        session_id=str(uuid.UUID(fingerprint({"sequence": record["id"], "index": index})[:32])),
        interval={
            "start_frame": base["interval"]["start_frame"] + clip["start_frame"],
            "end_frame": base["interval"]["start_frame"] + clip["end_frame"],
            "start_s": base["interval"]["start_s"] + clip["start_frame"] / fps,
            "end_s": min(base["interval"]["end_s"], base["interval"]["start_s"] + clip["end_frame"] / fps),
        },
    )
    request["prompt"] = (
        _video_prompt(
            scope["style"],
            request["quality"],
            {
                "motion": request["motion"],
                "sound": request["sound"],
                "resolution": request["resolution"],
                "requested": requested,
            },
        )
        + f"\nOrdered sequence clip {index + 1} of {len(scope['clips'])}."
    )
    return request


def clip_jobs(record):
    replacements = record.get("corrections") or {}
    return [replacements.get(key, key) for key in record["jobs"]]


def public_sequence(ledger, record):
    ai = ledger.data["ai"]
    scope = record["scope"]
    clips = []
    for clip, job_id in zip(scope["clips"], clip_jobs(record), strict=True):
        clips.append({**clip, "job": public_job(ai["jobs"][job_id])})
    version = ai["versions"].get(record.get("version"))
    reasons = _context_reasons(ledger, record, version)
    states = [clip["job"]["state"] for clip in clips]
    state = "planned" if record["launched"] is None else "running"
    if any(s in {"failed", "unknown", "cancelled"} for s in states):
        state = "partial"
    if record.get("error"):
        state = "incomplete"
        reasons.append(record.get("error_code") or "assembly_failed")
    if version:
        state = "complete"
        if version["profile_shortfall"]:
            reasons.append("profile_shortfall")
    if "stale_inputs" in reasons:
        state = "stale"
    return {
        "id": record["id"],
        "signature": record["fingerprint"],
        "state": state,
        "frames": scope["frames"],
        "fps": scope["request"]["profile"]["fps"],
        "route": scope["request"]["route"],
        "clip_duration_s": scope["clip_duration_s"],
        "clips": clips,
        "frozen": {key: scope["request"].get(key) for key in ("model", "resolution", "sound", "interval", "profile")},
        "version": public_version(version) if version else None,
        "reasons": reasons,
        "error": sanitize_public_text(record.get("error")) if record.get("error") else None,
        "ready": bool(version and not reasons and version["approval"]["state"] == "approved"),
        "correction_count": len(record.get("corrections") or {}),
        "history": [
            public_version(row)
            for row in ai["versions"].values()
            if row.get("sequence") == record["id"] and row["id"] != record.get("version")
        ],
    }


def board_sequence(ledger, beat):
    record = (ledger.data.get("ai", {}).get("sequences") or {}).get(beat.get("sequence"))
    return public_sequence(ledger, record) if record else None


def validate_sequences(ai):
    records = ai.get("sequences", {})
    if not isinstance(records, dict):
        raise ValueError("Invalid AI sequence collection.")
    seen = set()
    for key, record in records.items():
        try:
            _validate_record(ai, key, record, seen)
        except (KeyError, TypeError, IndexError) as exc:
            raise ValueError("Invalid frozen AI sequence; preserve its records.") from exc
    if any(job["request"].get("sequence") and key not in seen for key, job in ai["jobs"].items()):
        raise ValueError("An AI sequence clip lost its frozen membership.")


def _validate_record(ai, key, record, seen):
    if not isinstance(record, dict) or record.get("id") != identifier(key, "Sequence id"):
        raise ValueError("Invalid AI sequence identity.")
    scope = record["scope"]
    if not isinstance(scope, dict) or fingerprint(scope) != record["fingerprint"]:
        raise ValueError("AI sequence inputs changed after being frozen.")
    text(record["nonce"], "Request identity", 160)
    jobs, clips = record["jobs"], scope["clips"]
    if not isinstance(jobs, list) or not isinstance(clips, list) or not 1 <= len(jobs) == len(clips) <= MAX_CLIPS:
        raise ValueError("A sequence must retain its bounded ordered clip set.")
    cursor = 0
    for index, (job_id, clip) in enumerate(zip(jobs, clips, strict=True)):
        if (
            type(clip["start_frame"]) is not int
            or type(clip["end_frame"]) is not int
            or clip["start_frame"] != cursor
            or clip["end_frame"] <= cursor
        ):
            raise ValueError("Sequence placements must be ordered with no gaps or overlaps.")
        cursor = clip["end_frame"]
        if job_id in seen or ai["jobs"][job_id]["request"] != _clip_request(record, index):
            raise ValueError("Sequence membership or frozen clip inputs changed.")
        seen.add(job_id)
    seen.update(validate_operation_corrections(ai, record, seen))
    if (
        cursor != scope["frames"]
        or cursor != scope["request"]["interval"]["end_frame"] - scope["request"]["interval"]["start_frame"]
    ):
        raise ValueError("Sequence coverage differs from its narration frame interval.")
    if record.get("version"):
        version = ai["versions"][record["version"]]
        if (
            version["kind"] != "sequence"
            or version.get("sequence") != key
            or version.get("sequence_scope") != record["fingerprint"]
        ):
            raise ValueError("Sequence version lost its frozen context.")


def handle_prepare(project, data):
    from .ai_openrouter import check_setup, prepared_setup, validate_request

    route = data.get("route", "grok-subscription")
    if route not in ("grok-subscription", "openrouter"):
        raise ValueError("Choose an explicitly configured sequence route.")
    nonce = text(data.get("requestId"), "Request identity", 160)
    paid = None
    if route == "openrouter":
        choice, aspect, paid = prepared_setup(Ledger(project, recover=False), "video", nonce)
    with project_lock(project):
        ledger = Ledger(project)
        if paid:
            check_setup(ledger, "video", choice, aspect)
        record = _prepare(ledger, data, nonce, paid=paid)
        if paid:
            for job_id in record["jobs"]:
                validate_request(ledger.data["ai"]["jobs"][job_id]["request"])
        ledger.save("ai-prepare-sequence")
        return {"sequence": public_sequence(ledger, record)}


def checked_child(ledger, request):
    ai = ledger.data["ai"]
    record = (ai.get("sequences") or {}).get(request.get("sequence"))
    index = request.get("sequence_index")
    if not record or type(index) is not int or not 0 <= index < len(record["jobs"]):
        raise ValueError("The frozen sequence membership changed.")
    job = ai["jobs"].get(clip_jobs(record)[index])
    if not job or job["request"] != request or record["fingerprint"] != request.get("sequence_scope"):
        raise ValueError("The frozen sequence clip changed.")
    beat = beat_for(ledger, request["beat"], request["inputs"])
    if beat.get("sequence") != record["id"] or _profile(ledger) != record["scope"]["profile"]:
        raise ValueError("The active sequence or output profile changed.")
    return record


def handle_launch(project, data):
    from .ai import _should_dispatch, start_worker

    with project_lock(project):
        ledger = Ledger(project)
        record = (ledger.data["ai"].get("sequences") or {}).get(identifier(data.get("sequence"), "Sequence id"))
        if not record or data.get("signature") != record["fingerprint"]:
            raise ValueError("Launch the exact displayed sequence plan.")
        if record["scope"]["request"]["route"] != "grok-subscription":
            raise ValueError("Confirm the full paid sequence through its frozen paid launch.")
        jobs = [ledger.data["ai"]["jobs"][key] for key in clip_jobs(record)]
        _checked_inputs(ledger, record)
        if not record["launched"]:
            record["launched"] = now()
            for job in jobs:
                job["state"] = "queued"
            ledger.save("ai-launch-sequence")
        dispatch = [job["id"] for job in jobs if _should_dispatch(job)]
    for key in dispatch:
        start_worker(project, key)
    current = Ledger(project, recover=False)
    return {"sequence": public_sequence(current, current.data["ai"]["sequences"][record["id"]])}


def checked_sequence_version(ledger, version):
    from .narration import _confine_existing_file

    record = (ledger.data["ai"].get("sequences") or {}).get(version.get("sequence"))
    if not record or record["version"] != version["id"] or record["fingerprint"] != version.get("sequence_scope"):
        raise ValueError("The exact sequence version is no longer current.")
    _checked_inputs(ledger, record)
    for job_id, clip in zip(clip_jobs(record), version["clips"], strict=True):
        job = ledger.data["ai"]["jobs"][job_id]
        source, _path = checked_version(ledger, job["result"], kind="video")
        if source["id"] != clip["version"] or source["sha256"] != clip["sha256"]:
            raise ValueError("A retained sequence original changed.")
    preview = version["preview"]
    path = _confine_existing_file(ledger.root, preview["path"], ("previews/",))
    if digest(path) != preview["sha256"]:
        raise ValueError("The sequence preview changed; review the exact bytes.")


def handle_resume(project, data):
    from argparse import Namespace

    from .ai import dispatch_after_audit, resume_command

    with project_lock(project):
        ledger = Ledger(project)
        record = (ledger.data.get("ai", {}).get("sequences") or {}).get(identifier(data.get("sequence"), "Sequence id"))
        if not record or record["fingerprint"] != data.get("signature") or not record.get("launched"):
            raise ValueError("Recover the exact previously launched sequence.")
        _checked_inputs(ledger, record)
        results = []
        for job_id in clip_jobs(record):
            job = ledger.data["ai"]["jobs"][job_id]
            if job.get("result"):
                checked_version(ledger, job["result"], kind="video")
            results.append(resume_command(ledger, Namespace(job=job_id)))
    for result in results:
        dispatch_after_audit(result)
    # Also covers a crash after the last child commit, before local composition.
    assemble_for_job(project, record["jobs"][0])
    current = Ledger(project, recover=False)
    return {"sequence": public_sequence(current, current.data["ai"]["sequences"][record["id"]])}


def assemble_for_job(project, job_id):
    """Serialize local composition; successful originals never turn into failed jobs."""
    with project_lock(project):
        ledger = Ledger(project)
        job = (ledger.data.get("ai") or {}).get("jobs", {}).get(job_id)
        record = (ledger.data.get("ai", {}).get("sequences") or {}).get((job or {}).get("request", {}).get("sequence"))
        if not record or record.get("version") or not record.get("launched"):
            return
        jobs = [ledger.data["ai"]["jobs"][key] for key in clip_jobs(record)]
        if any(child["state"] != "complete" for child in jobs):
            return
        try:
            version = _assemble(ledger, record, jobs)
            ledger.data["ai"]["versions"][version["id"]] = version
            record.update(version=version["id"], error=None)
        except (ValueError, OSError, KeyError) as exc:
            record["error"] = sanitize_public_text(str(exc))
            record["error_code"] = (
                "coverage_shortfall" if isinstance(exc, CoverageShortfallError) else "assembly_failed"
            )
        ledger.save("ai-assemble-sequence")


def _frames(path):
    data = json.loads(
        run(
            [
                "ffprobe",
                "-v",
                "error",
                "-select_streams",
                "v:0",
                "-count_frames",
                "-show_entries",
                "stream=nb_read_frames",
                "-of",
                "json",
                str(path),
            ]
        )
    )
    return int(data["streams"][0]["nb_read_frames"])


def _assemble(ledger, record, jobs):
    from .ai import _chain_inside, _probe_clip
    from .narration import _confine_existing_file

    scope = record["scope"]
    fps = scope["request"]["profile"]["fps"]
    originals = []
    _checked_inputs(ledger, record)
    for job in jobs:
        version, path = checked_version(ledger, job["result"], kind="video")
        originals.append((version, path, _probe_clip(path)))
    profile = scope["profile"]
    # Preserve the agreed aspect ratio without enlarging any original.
    ratio = min(
        1.0, *(min(info["width"] / profile["width"], info["height"] / profile["height"]) for _, _, info in originals)
    )
    width, height = (max(2, int(profile[key] * ratio) // 2 * 2) for key in ("width", "height"))
    ident = "sequence-" + uuid.uuid4().hex
    target = ledger.root / "clips" / ("ai-" + ident + ".mp4")
    preview = ledger.root / "previews" / ("ai-" + ident + ".mp4")
    for path in (target, preview):
        path.parent.mkdir(parents=True, exist_ok=True)
        _chain_inside(ledger.root, path)
    lineage = []
    staging = ledger.root / "ai-work"
    _chain_inside(ledger.root, staging)
    with tempfile.TemporaryDirectory(prefix="sequence-", dir=staging) as scratch:
        parts = []
        for index, (clip, (source, path, info)) in enumerate(zip(scope["clips"], originals, strict=True)):
            frames = clip["end_frame"] - clip["start_frame"]
            seconds = frames / fps
            part = Path(scratch) / f"{index}.mp4"
            args = ["ffmpeg", "-v", "error", "-i", str(path)]
            if not info["audio"]:
                args += ["-f", "lavfi", "-i", "anullsrc=r=48000:cl=stereo"]
            video = f"fps={fps},trim=end_frame={frames},setpts=PTS-STARTPTS,scale={width}:{height}:force_original_aspect_ratio=decrease:force_divisible_by=2,pad={width}:{height}:(ow-iw)/2:(oh-ih)/2,setsar=1"
            audio = f"[{0 if info['audio'] else 1}:a:0]aresample=48000,apad,atrim=duration={seconds},asetpts=PTS-STARTPTS[a]"
            run(
                [
                    *args,
                    "-filter_complex",
                    f"[0:v:0]{video}[v];{audio}",
                    "-map",
                    "[v]",
                    "-map",
                    "[a]",
                    "-c:v",
                    "libx264",
                    "-preset",
                    "fast",
                    "-pix_fmt",
                    "yuv420p",
                    "-c:a",
                    "aac",
                    "-ac",
                    "2",
                    "-t",
                    str(seconds),
                    str(part),
                ]
            )
            if _frames(part) != frames:
                raise CoverageShortfallError(
                    f"Clip {index + 1} is shorter than its planned coverage; no frames were invented."
                )
            parts.append(part)
            lineage.append(
                {
                    **clip,
                    "job": jobs[index]["id"],
                    "version": source["id"],
                    "sha256": source["sha256"],
                    "actual_duration_s": info["duration_s"],
                    "trim_start_frame": 0,
                    "trim_end_frame": frames,
                }
            )
        movie = Path(scratch) / "movie.mp4"
        _join(parts, scope["clips"], fps, movie)
        timing = beat_for(ledger, scope["request"]["beat"])["timing"]
        narration, error = preview_for_view(ledger, timing, resolved=True)
        if not narration:
            raise ValueError(error or "The bounded narration preview is missing.")
        vo = _confine_existing_file(ledger.root, narration, ("previews/",))
        audition = Path(scratch) / "preview.mp4"
        run(
            [
                "ffmpeg",
                "-v",
                "error",
                "-i",
                str(movie),
                "-i",
                str(vo),
                "-filter_complex",
                "[0:a][1:a]amix=inputs=2:weights='0.35 1':normalize=0:duration=first[a]",
                "-map",
                "0:v",
                "-map",
                "[a]",
                "-c:v",
                "copy",
                "-c:a",
                "aac",
                "-movflags",
                "+faststart",
                str(audition),
            ]
        )
        info = _probe_clip(movie)
        _probe_clip(audition)
        if _frames(movie) != scope["frames"] or _frames(audition) != scope["frames"]:
            raise ValueError("The composed sequence does not cover the exact planned frame count.")
        movie.replace(target)
        audition.replace(preview)
    return {
        "id": ident,
        "kind": "sequence",
        "beat": scope["request"]["beat"],
        "inputs": scope["request"]["inputs"],
        "sequence": record["id"],
        "sequence_scope": record["fingerprint"],
        "path": target.relative_to(ledger.root).as_posix(),
        "sha256": digest(target),
        "preview": {"path": preview.relative_to(ledger.root).as_posix(), "sha256": digest(preview)},
        **info,
        "fps": fps,
        "frames": scope["frames"],
        "profile": profile,
        "clips": lineage,
        "coverage": "covered",
        "native_full_hd": all(item[0]["native_full_hd"] for item in originals),
        "profile_shortfall": any(
            not source["native_full_hd"]
            or info["width"] < profile["width"]
            or info["height"] < profile["height"]
            or info["fps"] + 0.001 < fps
            for source, _, info in originals
        ),
        "approval": {"state": "pending"},
    }


def _join(parts, clips, fps, movie):
    inputs = []
    chains = []
    for index, (part, clip) in enumerate(zip(parts, clips, strict=True)):
        inputs += ["-i", str(part)]
        seconds = (clip["end_frame"] - clip["start_frame"]) / fps
        chains += [
            f"[{index}:v]setpts=PTS-STARTPTS[v{index}]",
            f"[{index}:a]atrim=duration={seconds},asetpts=PTS-STARTPTS[a{index}]",
        ]
    chains.append("".join(f"[v{i}][a{i}]" for i in range(len(parts))) + f"concat=n={len(parts)}:v=1:a=1[v][a]")
    run(
        [
            "ffmpeg",
            "-v",
            "error",
            *inputs,
            "-filter_complex",
            ";".join(chains),
            "-map",
            "[v]",
            "-map",
            "[a]",
            "-c:v",
            "libx264",
            "-preset",
            "fast",
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "aac",
            "-movflags",
            "+faststart",
            str(movie),
        ]
    )


def _context_reasons(ledger, record, version):
    try:
        if version:
            checked_version(ledger, version["id"], kind="sequence")
        else:
            _checked_inputs(ledger, record)
    except (ValueError, OSError, KeyError):
        return ["stale_inputs"]
    return []


def _checked_inputs(ledger, record):
    scope = record["scope"]
    checked_video_input(ledger, scope["request"])
    beat = beat_for(ledger, scope["request"]["beat"])
    if beat.get("sequence") != record["id"] or scope["profile"] != _profile(ledger):
        raise ValueError("The active sequence or output profile changed.")
    # Verify shared narration once, and every distinct approved first frame once.
    stills = {fingerprint(clip["still"]): clip["still"] for clip in scope["clips"]}
    for binding in stills.values():
        version, _path = checked_version(ledger, binding["id"], approved=True, kind="image")
        if version["sha256"] != binding["sha256"] or version_signature(version) != binding["signature"]:
            raise ValueError("A frozen sequence first frame changed.")
