"""Explicitly confirmed OpenRouter media; one POST per job, GET-only video recovery.

Official dedicated Images and Videos APIs, checked 2026-10-19. Capabilities and
pricing are read before confirmation. No SDK, model substitution or POST retry.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import json
import math
import os
import re
import tempfile
import time
import uuid
from http import HTTPStatus
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request

from .ai_state import ALTERNATIVE_COUNT, fingerprint, text
from .http import _network_url, _opener

API = "https://openrouter.ai/api/v1"
MAX_IMAGE = 16 * 1024 * 1024
MAX_VIDEO = 256 * 1024 * 1024
MAX_JSON = 24 * 1024 * 1024
MODEL = re.compile(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+\Z")
HANDLE = re.compile(r"[A-Za-z0-9_-]{1,200}\Z")
POLL_S = 5
MAX_DURATION = 30


def setup(raw):
    if raw is None:
        return {}
    if not isinstance(raw, dict) or set(raw) - {"image", "video"}:
        raise ValueError("OpenRouter setup names image and/or video settings.")
    result = {}
    for kind, value in raw.items():
        if not isinstance(value, dict) or set(value) - {"model", "resolution", "duration"}:
            raise ValueError("OpenRouter settings need model, resolution and video duration only.")
        model = text(value.get("model"), "OpenRouter model", 200)
        resolution = text(value.get("resolution"), "OpenRouter resolution", 20)
        if not MODEL.fullmatch(model) or model.startswith("openrouter/"):
            raise ValueError("Use an explicit OpenRouter model slug, without automatic routing.")
        item: dict = {"model": model, "resolution": resolution}
        if kind == "video":
            duration = value.get("duration")
            if type(duration) is not int or not 1 <= duration <= MAX_DURATION:
                raise ValueError("OpenRouter video duration must be an explicit integer from 1 to 30 seconds.")
            item["duration"] = duration
        result[kind] = item
    return result


def _remaining(deadline):
    left = deadline - time.monotonic()
    if left <= 0:
        raise TimeoutError
    return left


def _read(response, limit, deadline):
    chunks, size = [], 0
    read = getattr(response, "read1", response.read)
    while True:
        _remaining(deadline)
        data = read(min(65536, limit + 1 - size))
        if not data:
            return b"".join(chunks)
        size += len(data)
        if size > limit:
            raise ValueError("OpenRouter media exceeded the bounded response size.")
        chunks.append(data)


def _json(path, deadline, *, body=None, token=None):
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = "Bearer " + token
    request = Request(  # noqa: S310 - fixed official HTTPS origin, constant or validated model/handle path
        API + path, headers=headers, data=json.dumps(body).encode() if body is not None else None
    )
    with _opener().open(request, timeout=min(60, _remaining(deadline))) as response:
        result = json.loads(_read(response, MAX_JSON, deadline))
    if not isinstance(result, dict):
        raise ValueError("OpenRouter returned an invalid response.")
    return result


def capabilities(choice, kind, aspect):
    """Public GETs only. Snapshot the exact provider's supported inputs before consent."""
    deadline = time.monotonic() + 30
    model = choice["model"]
    try:
        if kind == "image":
            result = _json("/images/models/" + model + "/endpoints", deadline)
            for endpoint in result.get("endpoints") or []:
                params = endpoint.get("supported_parameters") or {}
                tag = endpoint.get("provider_tag")
                if (
                    isinstance(tag, str)
                    and HANDLE.fullmatch(tag)
                    and choice["resolution"] in (params.get("resolution") or {}).get("values", [])
                    and aspect in (params.get("aspect_ratio") or {}).get("values", [])
                ):
                    return {
                        **choice,
                        "aspect_ratio": aspect,
                        "provider": tag,
                        "parameters": params,
                        "pricing": endpoint.get("pricing") or [],
                    }
        else:
            rows = _json("/videos/models", deadline).get("data") or []
            for row in rows:
                if row.get("id") != model:
                    continue
                if (
                    choice["resolution"] in (row.get("supported_resolutions") or [])
                    and choice["duration"] in (row.get("supported_durations") or [])
                    and aspect in (row.get("supported_aspect_ratios") or [])
                    and "first_frame" in (row.get("supported_frame_images") or [])
                ):
                    return {
                        **choice,
                        "aspect_ratio": aspect,
                        "audio": row.get("generate_audio"),
                        "pricing": row.get("pricing_skus") or {},
                    }
    except (OSError, URLError, ValueError):
        raise ValueError("OpenRouter capabilities could not be verified. No paid launch was prepared.") from None
    raise ValueError("OpenRouter model does not advertise the requested profile or required first-frame input.")


def _mime(data):
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if data.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    raise ValueError("The image is not a bounded PNG/JPEG original.")


def _data_url(data):
    if len(data) > MAX_IMAGE:
        raise ValueError("An OpenRouter image input exceeds 16 MiB.")
    return "data:" + _mime(data) + ";base64," + base64.b64encode(data).decode()


def _reference_count(request):
    return sum(
        len(ref.get("frames") or []) if ref.get("kind") == "video" else 1 for ref in request.get("references") or []
    ) + bool(request.get("target"))


def validate_request(request):
    paid = request.get("paid") or {}
    if request.get("route") != "openrouter" or not MODEL.fullmatch(str(request.get("model") or "")):
        raise ValueError("The concrete OpenRouter model is missing.")
    if paid.get("model") != request["model"] or paid.get("resolution") != request.get("resolution"):
        raise ValueError("The paid profile changed after preparation.")
    refs = _reference_count(request)
    if request.get("kind") == "image":
        limit = (paid.get("parameters", {}).get("input_references") or {}).get("max", 0)
        if refs > limit:
            raise ValueError("This OpenRouter endpoint cannot accept all frozen reference images/interval frames.")
    elif request.get("kind") == "video":
        if request.get("requested_duration_s") != paid.get("duration"):
            raise ValueError("The paid video duration changed after preparation.")
        if any((request.get("sound") or {}).values()) and paid.get("audio") is not True:
            raise ValueError("The selected OpenRouter model does not advertise the requested audio capability.")
    else:
        raise ValueError("OpenRouter supports image and video jobs only.")


def estimate(request):
    """Quote only unambiguous image-unit prices; tiered/token/video tariffs stay unknown."""
    pricing = (request.get("paid") or {}).get("pricing")
    unknown = {"usd": None, "note": "Estimate unknown; this is paid generation."}
    if request.get("kind") != "image" or not isinstance(pricing, list) or not pricing:
        return unknown
    total, output = 0.0, False
    for line in pricing:
        if line.get("unit") != "image" or line.get("variant"):
            return unknown
        value = line.get("cost_usd")
        if type(value) not in (int, float) or not math.isfinite(value) or value < 0:
            return unknown
        if line.get("billable") == "output_image":
            total += value
            output = True
        elif line.get("billable") in {"input_image", "input_reference"}:
            total += value * _reference_count(request)
        else:
            return unknown
    return {"usd": round(total, 8), "note": "Provider estimate, not a spending cap."} if output else unknown


def _inputs(project, job, workdir):
    from .ai import _recheck_rows, _stage_apply_rows
    from .ai_timing import checked_video_input
    from .ledger import Ledger
    from .runtime import project_lock

    request = job["request"]
    if request["kind"] == "video":
        with project_lock(project):
            path = checked_video_input(Ledger(project), request)
            data = path.read_bytes()
            if hashlib.sha256(data).hexdigest() != request["still"]["sha256"]:
                raise ValueError("The approved starting-frame bytes changed.")
        return [{"type": "image_url", "frame_type": "first_frame", "image_url": {"url": _data_url(data)}}]
    rows = _stage_apply_rows(project, job, workdir) if request.get("references") or request.get("target") else []
    values = [{"type": "image_url", "image_url": {"url": _data_url(Path(row["path"]).read_bytes())}} for row in rows]
    _recheck_rows(rows)
    return values


def _payload(project, job, workdir):
    request = job["request"]
    validate_request(request)
    paid = request["paid"]
    body = {
        "model": request["model"],
        "prompt": request["prompt"],
        "resolution": request["resolution"],
        "aspect_ratio": paid["aspect_ratio"],
    }
    inputs = _inputs(project, job, workdir)
    if request["kind"] == "image":
        body.update(
            n=1,
            provider={"only": [paid["provider"]], "allow_fallbacks": False, "require_parameters": True},
        )
        formats = (paid.get("parameters") or {}).get("output_format") or {}
        if "png" in formats.get("values", []):
            body["output_format"] = "png"
        if inputs:
            body["input_references"] = inputs
    else:
        body.update(
            duration=request["requested_duration_s"], frame_images=inputs, generate_audio=any(request["sound"].values())
        )
    return body


def _save_image(result, workdir):
    rows = result.get("data")
    if not isinstance(rows, list) or len(rows) != 1 or not isinstance(rows[0], dict):
        raise ValueError("OpenRouter did not return exactly one original per image job.")
    encoded = rows[0].get("b64_json")
    if not isinstance(encoded, str) or len(encoded) > MAX_IMAGE * 4 // 3 + 4:
        raise ValueError("OpenRouter returned no bounded image original.")
    data = base64.b64decode(encoded, validate=True)
    if len(data) > MAX_IMAGE:
        raise ValueError("OpenRouter image original exceeds 16 MiB.")
    suffix = ".png" if _mime(data) == "image/png" else ".jpg"
    path = workdir / ("openrouter-image-" + uuid.uuid4().hex + suffix)
    with path.open("xb") as output:
        output.write(data)
        output.flush()
        os.fsync(output.fileno())
    return path


def _download(url, workdir, deadline, *, token=None):
    if not isinstance(url, str):
        raise ValueError("The completed OpenRouter video has no media URL.")
    _network_url(url)
    if token and not re.fullmatch(re.escape(API) + r"/videos/[A-Za-z0-9_-]{1,200}/content\?index=0", url):
        raise ValueError("Refusing to forward OpenRouter credentials outside the exact video content endpoint.")
    path = workdir / ("openrouter-video-" + uuid.uuid4().hex + ".mp4")
    pending = path.with_suffix(".part")
    headers = {"Authorization": "Bearer " + token} if token else {}
    # A bearer is used only with a locally constructed official content endpoint.
    request = Request(url, method="GET", headers=headers)  # noqa: S310 - public HTTPS DNS pinned, redirects forbidden
    with _opener().open(request, timeout=min(60, _remaining(deadline))) as response:
        data = _read(response, MAX_VIDEO, deadline)
    with pending.open("xb") as output:
        output.write(data)
        output.flush()
        os.fsync(output.fileno())
    pending.rename(path)
    return path


def _poll(remote, workdir, token, deadline, on_submitted=None):
    handle = remote.get("requestId")
    if not isinstance(handle, str) or not HANDLE.fullmatch(handle):
        raise ValueError("The retained OpenRouter video handle is invalid.")
    while True:
        result = _json("/videos/" + handle, deadline, token=token)
        status = result.get("status")
        if status == "completed":
            urls = result.get("urls")
            if urls is not None and (not isinstance(urls, list) or len(urls) != 1):
                raise ValueError("OpenRouter did not return exactly one signed video download.")
            if on_submitted:
                on_submitted({**remote, "phase": "downloading"})
            # unsigned_urls require authentication in the current API. Never forward
            # a bearer to a returned URL: construct the exact job's content path.
            path = (
                _download(urls[0], workdir, deadline)
                if urls
                else _download(API + "/videos/" + handle + "/content?index=0", workdir, deadline, token=token)
            )
            return {"status": "complete", "path": str(path), "remote": remote}
        if status in {"failed", "cancelled", "expired"}:
            return {
                "status": "failed",
                "code": "provider",
                "error": "The existing OpenRouter video " + status + ". No new generation was sent.",
                "remote": remote,
            }
        if status not in {"pending", "in_progress"}:
            raise ValueError("Unknown OpenRouter status; retain the handle instead of resubmitting.")
        if _remaining(deadline) <= POLL_S:
            return {"status": "pending", "remote": remote}
        time.sleep(POLL_S)


def retrievable(job):
    remote = job.get("remote") or {}
    return (
        (job.get("request") or {}).get("route") == "openrouter"
        and remote.get("transport") == "openrouter-media"
        and bool(HANDLE.fullmatch(str(remote.get("requestId") or "")))
    )


def _failure(exc, *, sent=False, remote=None):
    status, code = "unknown" if sent and not remote else "failed", "transport"
    rejected = False
    message = "OpenRouter media could not complete. Recover a retained result; no generation was retried."
    if isinstance(exc, HTTPError):
        number = exc.code
        exc.close()
        status = (
            "unknown"
            if sent and (number >= HTTPStatus.INTERNAL_SERVER_ERROR or number == HTTPStatus.REQUEST_TIMEOUT)
            else "failed"
        )
        code = "auth" if number in {401, 403} else "quota" if number in {402, 429} else "http"
        outcome = "submission is uncertain" if status == "unknown" else "request was rejected"
        message = f"OpenRouter {outcome} (HTTP {number}). No retry or billing fallback."
        rejected = (
            sent
            and not remote
            and HTTPStatus.BAD_REQUEST <= number < HTTPStatus.INTERNAL_SERVER_ERROR
            and number != HTTPStatus.REQUEST_TIMEOUT
        )
    return {
        "status": status,
        "code": code,
        "error": message,
        "remote": remote,
        "submit_outcome": "rejected" if rejected else None,
    }


def _token():
    token = os.environ.get("OPENROUTER_API_KEY", "").strip()
    if not token or any(char.isspace() for char in token):
        raise ValueError("Set the private OPENROUTER_API_KEY before confirming paid work.")
    return token


def produce(project, job, workdir, *, timeout, on_submitted):
    remote, sent = None, False
    try:
        request = job["request"]
        if not job.get("confirmation") or job["confirmation"].get("fingerprint") != fingerprint(request):
            raise ValueError("This paid launch has no matching confirmation.")
        try:
            token = _token()
        except ValueError as exc:
            return {"status": "auth", "code": "auth", "error": str(exc)}
        body = _payload(project, job, workdir)
        deadline = time.monotonic() + min(300, max(0.1, timeout))
        sent = True
        result = _json("/images" if request["kind"] == "image" else "/videos", deadline, token=token, body=body)
        remote = {"transport": "openrouter-media", "model": request["model"]}
        if request["kind"] == "image":
            on_submitted(remote)
            path = _save_image(result, workdir)
            remote.update(artifact=path.name, artifact_sha256=hashlib.sha256(path.read_bytes()).hexdigest())
            on_submitted(remote)
            return {"status": "complete", "path": str(path), "remote": remote}
        handle = result.get("id")
        if not isinstance(handle, str) or not HANDLE.fullmatch(handle):
            remote = None
            raise ValueError("The submission returned no usable video handle.")
        remote["requestId"] = handle
        on_submitted(remote)
        return _poll(remote, workdir, token, deadline, on_submitted)
    except (OSError, URLError, ValueError, binascii.Error) as exc:
        return _failure(exc, sent=sent, remote=remote)


def retrieve(job, workdir, *, timeout):
    remote = job.get("remote") or {}
    try:
        if not retrievable(job):
            raise ValueError("No retained OpenRouter video handle.")
        return _poll(remote, workdir, _token(), time.monotonic() + min(300, max(0.1, timeout)))
    except (OSError, URLError, ValueError) as exc:
        return _failure(exc, remote=remote)


def public_launch(job):
    from .ai_state import sanitize_public_text

    request = job["request"]
    return {
        "fingerprint": job["fingerprint"],
        "model": request.get("model"),
        "provider": (request.get("paid") or {}).get("provider"),
        "prompt": sanitize_public_text(request.get("prompt"), limit=32000),
        "references": [
            {
                key: ref.get(key)
                for key in (
                    "context_id",
                    "kind",
                    "source_sha256",
                    "derivative_sha256",
                    "role",
                    "instructions",
                    "interval",
                    "frames",
                )
            }
            for ref in request.get("references") or []
        ],
        "still": request.get("still"),
        "interval": request.get("interval"),
        "narration": request.get("narration"),
        "motion": request.get("motion"),
        "sound": request.get("sound"),
        "resolution": request.get("resolution"),
        "aspect_ratio": (request.get("paid") or {}).get("aspect_ratio"),
        "profile": request.get("profile"),
        "duration": request.get("requested_duration_s"),
        "estimate": estimate(request),
    }


def _prior_paid(ai, nonce):
    jobs = ai.get("jobs") or {}
    for job in jobs.values():
        if job.get("nonce") == nonce:
            return (job.get("request") or {}).get("paid")
    for group in (ai.get("groups") or {}).values():
        if group.get("nonce") == nonce:
            return ((jobs.get(group["jobs"][0]) or {}).get("request") or {}).get("paid")
    for sequence in (ai.get("sequences") or {}).values():
        if sequence.get("nonce") == nonce:
            return sequence["scope"]["request"].get("paid")
    return None


def prepared_setup(snapshot, kind, nonce):
    from .ai_state import _native_image_output

    ai = snapshot.data.get("ai") or {}
    choice = setup(ai.get("openrouter")).get(kind)
    if not choice:
        raise ValueError("Configure the explicit OpenRouter model/profile in the AI plan first.")
    aspect = _native_image_output(snapshot)["aspect_ratio"]
    paid = _prior_paid(ai, nonce)
    if paid is not None:
        if any(paid.get(key) != value for key, value in choice.items()) or paid.get("aspect_ratio") != aspect:
            raise ValueError("This request identity already belongs to different frozen inputs.")
    else:
        paid = capabilities(choice, kind, aspect)
    return choice, aspect, paid


def check_setup(ledger, kind, choice, aspect):
    from .ai_state import _native_image_output

    if (
        setup((ledger.data.get("ai") or {}).get("openrouter")).get(kind) != choice
        or _native_image_output(ledger)["aspect_ratio"] != aspect
    ):
        raise ValueError("OpenRouter setup changed while preparing; prepare the new scope.")


def handle_prepare(project, data):
    from .ai_state import public_job
    from .ledger import Ledger
    from .runtime import project_lock

    nonce = text(data.get("requestId"), "Request identity", 160)
    kind = data.get("kind")
    if kind not in {"image", "video"}:
        raise ValueError("Prepare one image, three image alternatives, or one video.")
    choice, aspect, paid = prepared_setup(Ledger(project, recover=False), kind, nonce)
    with project_lock(project):
        ledger = Ledger(project)
        check_setup(ledger, kind, choice, aspect)
        jobs = _prepare_jobs(ledger, data, nonce, kind, paid)
        for job in jobs:
            validate_request(job["request"])
        ledger.save("ai-prepare-paid")
        return {"jobs": [public_job(job) for job in jobs], "outputs": len(jobs)}


def _prepare_jobs(ledger, data, nonce, kind, paid):
    from .ai_state import launch_comparison, launch_still
    from .ai_timing import launch_video

    if kind == "video":
        if data.get("outputs") not in (None, 1):
            raise ValueError("This video launch prepares exactly one output.")
        jobs = [launch_video(ledger, data, nonce, paid=paid)]
    elif type(data.get("outputs")) is int and data["outputs"] == ALTERNATIVE_COUNT:
        jobs = launch_comparison(ledger, data, nonce, paid=paid)["jobs"]
    elif data.get("outputs") is None:
        jobs = [launch_still(ledger, data, nonce, paid=paid)]
    else:
        raise ValueError("A still launch prepares one image or exactly three alternatives.")
    return jobs


def handle_confirm(project, data):
    from .ai import _job_dir, _refresh_jobs, _should_dispatch, start_worker
    from .ai_sequences import MAX_CLIPS
    from .ai_state import confirm, public_job
    from .ledger import Ledger
    from .runtime import project_lock

    ids = data.get("jobs")
    signatures = data.get("signatures")
    if (
        not isinstance(ids, list)
        or not 1 <= len(ids) <= MAX_CLIPS
        or any(not isinstance(key, str) for key in ids)
        or len(set(ids)) != len(ids)
    ):
        raise ValueError("Confirm the exact bounded launch once.")
    snapshot = Ledger(project, recover=False)
    stored = (snapshot.data.get("ai") or {}).get("jobs") or {}
    jobs = [stored.get(key) for key in ids]
    if not isinstance(signatures, dict) or any(
        not job
        or (job.get("request") or {}).get("route") != "openrouter"
        or signatures.get(job["id"]) != job["fingerprint"]
        for job in jobs
    ):
        raise ValueError("Paid confirmation does not match the displayed frozen launch.")
    jobs = [job for job in jobs if isinstance(job, dict)]
    _check_launch_membership(snapshot.data["ai"], jobs, ids)
    # Only validation and local staging before consent; no remote call or credential lookup.
    for job in jobs:
        if job["state"] == "awaiting_confirmation":
            directory = _job_dir(snapshot.root, job["id"])
            directory.mkdir(parents=True, exist_ok=True)
            # Validation must not occupy the worker's write-once staging names.
            with tempfile.TemporaryDirectory(prefix="preflight-", dir=directory) as scratch:
                _payload(project, job, Path(scratch))
    with project_lock(project):
        ledger = Ledger(project)
        current_jobs = (ledger.data.get("ai") or {})["jobs"]
        current = [current_jobs[key] for key in ids]
        if all(job["state"] == "awaiting_confirmation" for job in current):
            confirm(ledger, ids, signatures, data.get("by") or "Storyboard")
        elif not all(
            (job.get("confirmation") or {}).get("fingerprint") == signatures.get(job["id"]) for job in current
        ):
            raise ValueError("This confirmation contains an incomplete or changed launch.")
        dispatch = [job["id"] for job in current if _should_dispatch(job)]
        public = [public_job(job) for job in current]
    for job_id in dispatch:
        start_worker(project, job_id)
    return {"jobs": _refresh_jobs(project, ids) or public}


def _check_launch_membership(ai, jobs, ids):
    if len(jobs) == 1 and jobs[0].get("correction_of"):
        return  # Its own fingerprint confirms exactly one retained corrective intent.
    sequence_ids = {job["request"].get("sequence") for job in jobs}
    if sequence_ids != {None}:
        sequences = ai.get("sequences") or {}
        if (
            len(sequence_ids) != 1
            or None in sequence_ids
            or set(sequences.get(next(iter(sequence_ids)), {}).get("jobs", [])) != set(ids)
        ):
            raise ValueError("Confirm every clip of one exact frozen sequence.")
    elif len(ids) not in {1, 3}:
        raise ValueError("Confirm one output or three image alternatives.")
