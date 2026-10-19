"""Bounded Imagine side calls using only the installed Grok client's xAI OAuth account.

The wire contract follows xai-org/grok-build 2bdd1d6a (image_gen/video_gen).
This is a direct OAuth media transport, not a reasoning CLI turn. One POST per
claimed job; a lost response never triggers a retry or API-key fallback.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import ipaddress
import json
import os
import re
import time
import uuid
from datetime import UTC, datetime, timedelta
from http import HTTPStatus
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request

from .ai_state import MAX_PROMPT
from .http import ProviderError, _network_url, _opener

IMAGE_TOOL = "image_gen"
IMAGE_TOOLS = (IMAGE_TOOL, "image_edit")
IMAGE_MODEL = "grok-imagine-image-quality"
VIDEO_MODEL = "grok-imagine-video-1.5"
VIDEO_TOOLS = ("reference_to_video", "image_to_video")
API = "https://api.x.ai/v1"
MAX_IMAGE = 16 * 1024 * 1024
MAX_VIDEO = 256 * 1024 * 1024
MAX_JSON = 24 * 1024 * 1024
POLL_S = 5
MAX_SECONDS = 300
MAX_REFERENCE = 400 * 1024
MAX_INPUTS = 32
_REQUEST_ID = re.compile(r"[A-Za-z0-9_-]{1,200}\Z")


def _credentials():
    from .grok_oauth import _account, _client_version, _refresh

    if os.environ.get("XAI_API_KEY") or os.environ.get("GROK_API_KEY"):
        raise ProviderError("Static XAI_API_KEY or GROK_API_KEY is set. No API-key fallback is allowed.")
    path, before, data, name, record, expiry, _model = _account(verify_model=False)
    version = _client_version()
    if expiry <= datetime.now(UTC) + timedelta(seconds=60):
        record = _refresh(path, before, data, name, record)
    return record["key"], version


def _frozen(request):
    if not isinstance(request, dict) or request.get("route") != "grok-subscription":
        raise ValueError("The frozen native OAuth request is missing.")
    kind = request.get("kind")
    tool = request.get("tool")
    model = request.get("model")
    if not (kind == "image" and model == IMAGE_MODEL and tool in IMAGE_TOOLS) and not (
        kind == "video" and model == VIDEO_MODEL and tool in VIDEO_TOOLS
    ):
        raise ValueError("This frozen native model/tool pair is unverified. No model was substituted.")
    prompt = request.get("prompt")
    if not isinstance(prompt, str) or not prompt.strip() or len(prompt) > MAX_PROMPT or "\0" in prompt:
        raise ValueError("The frozen media prompt is missing or invalid.")
    session = request.get("session_id")
    if not isinstance(session, str) or not re.fullmatch(r"[a-f0-9-]{36}", session):
        raise ValueError("The frozen native session identity is invalid.")
    return kind


def _remaining(deadline):
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise TimeoutError
    return remaining


def _read(response, limit, deadline, output=None):
    """Bound byte count and elapsed time; never retain remote error bodies."""
    size = 0
    chunks = []
    read = getattr(response, "read1", response.read)
    while True:
        _remaining(deadline)
        chunk = read(min(64 * 1024, limit + 1 - size))
        if not chunk:
            break
        size += len(chunk)
        if size > limit:
            raise ValueError("The Grok media response exceeded its bounded size limit.")
        if output is None:
            chunks.append(chunk)
        else:
            output.write(chunk)
    return b"".join(chunks)


def _json(path, credentials, deadline, *, body=None, session=None):
    token, version = credentials
    headers = {
        "Authorization": "Bearer " + token,
        "Content-Type": "application/json",
        "User-Agent": "xai-grok-build/" + version,
        "x-grok-client-version": version,
    }
    if session:
        headers["x-grok-session-id"] = session
    request = Request(  # noqa: S310 - fixed official HTTPS origin; path is constant or a validated opaque request id
        API + path,
        headers=headers,
        data=json.dumps(body).encode() if body is not None else None,
        method="POST" if body is not None else "GET",
    )
    with _opener().open(request, timeout=min(60, _remaining(deadline))) as response:
        raw = _read(response, MAX_JSON, deadline)
    result = json.loads(raw)
    if not isinstance(result, dict):
        raise ValueError("Grok returned an invalid media response.")
    return result


def _video_input(project, request):
    from .ai_timing import checked_video_input
    from .ledger import Ledger
    from .runtime import project_lock

    with project_lock(project):
        path = checked_video_input(Ledger(project), request)
        if path.stat().st_size > MAX_IMAGE:
            raise ValueError("The approved first frame exceeds the native input size limit.")
        data = path.read_bytes()
        if hashlib.sha256(data).hexdigest() != request["still"]["sha256"]:
            raise ValueError("The approved first-frame bytes changed before submission.")
    return data, _image_type(data)


def _image_type(data):
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if data.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    raise ValueError("Grok returned no PNG/JPEG image original.")


def _edit_payload(project, job, workdir, payload):
    from .ai import _recheck_rows, _stage_apply_rows

    rows = _stage_apply_rows(project, job, workdir)
    if not rows or len(rows) > MAX_INPUTS:
        raise ValueError("Native image editing requires 1–32 bounded image inputs. No request was sent.")
    images, manifest = [], []
    for order, row in enumerate(rows, 1):
        data = _reference_bytes(row, workdir, order)
        images.append({"url": "data:" + _image_type(data) + ";base64," + base64.b64encode(data).decode()})
        manifest.append(
            {
                "order": order,
                "role": row.get("role"),
                "source_sha256": row["sha256"],
                "sent_sha256": hashlib.sha256(data).hexdigest(),
                "context_id": row.get("context_id"),
                "frame": row.get("frame"),
                "interval": row.get("interval"),
            }
        )
    _recheck_rows(rows)
    payload["prompt"] += (
        "\nActual attached image order (one-based); use these roles and frame times with the corresponding pixels: "
        + json.dumps(manifest, separators=(",", ":"))
    )
    if len(images) == 1:
        return {**payload, "image": images[0]}, manifest
    return {**payload, "images": images}, manifest


def _reference_bytes(row, workdir, order):
    from .media import run

    path = Path(row["path"])
    data = path.read_bytes()
    if hashlib.sha256(data).hexdigest() != row["sha256"]:
        raise ValueError("The frozen native reference bytes changed. Nothing was submitted.")
    if len(data) <= MAX_REFERENCE:
        _image_type(data)
        return data
    # Traceable spatial/format derivative, never a generated replacement. Keep the original.
    for quality in (4, 8, 12):
        converted = workdir / f"native-reference-{order}-{quality}.jpg"
        run(
            [
                "ffmpeg",
                "-v",
                "error",
                "-i",
                str(path),
                "-vf",
                "scale=w='min(768,iw)':h='min(768,ih)':force_original_aspect_ratio=decrease:force_divisible_by=2",
                "-frames:v",
                "1",
                "-q:v",
                str(quality),
                str(converted),
            ],
            op="ai_native_reference",
        )
        data = converted.read_bytes()
        if len(data) <= MAX_REFERENCE:
            return data
    raise ValueError("The native reference cannot fit its 400 KiB input limit. No generation was sent.")


def _payload(project, request, kind, job, workdir):
    payload = {"model": request["model"], "prompt": request["prompt"]}
    if kind == "image":
        if request.get("operation") == "inspect":
            raise ValueError("Grok analysis-only image inspection is unverified. No generation was sent.")
        aspect = request.get("aspect_ratio", "16:9")
        if request.get("resolution", "1k") != "1k":
            raise ValueError("The frozen native image resolution is unsupported. No quality substitution was sent.")
        if aspect not in {"16:9", "9:16", "1:1", "4:3", "3:4", "3:2", "2:3", "2:1", "1:2", "20:9", "9:20"}:
            raise ValueError("This image aspect ratio is unsupported by the native route.")
        payload.update(n=1, aspect_ratio=aspect, resolution="1k", response_format="b64_json")
        if request["tool"] == "image_edit":
            return _edit_payload(project, job, workdir, payload)
        if request.get("references") or request.get("target"):
            raise ValueError("Frozen references require image_edit. No text-only substitute was sent.")
        return payload, []
    duration, resolution = request.get("requested_duration_s"), request.get("resolution")
    allowed = (6, 10) if request["tool"] == "image_to_video" else range(1, 16)
    if type(duration) is not int or duration not in allowed or resolution not in {"480p", "720p"}:
        raise ValueError("Unsupported frozen native duration or resolution. No request was sent.")
    data, mime = _video_input(project, request)
    # The literal first-frame field preserves the approved bytes. Reference images alone do not.
    return {
        **payload,
        "duration": duration,
        "resolution": resolution,
        "image": {"url": "data:" + mime + ";base64," + base64.b64encode(data).decode()},
    }, []


def _remote(request):
    return {
        "transport": "oauth-imagine",
        "model": request["model"],
        "tool": request["tool"],
        "sessionId": request["session_id"],
    }


def _image_result(result, workdir, remote):
    rows = result.get("data")
    if not isinstance(rows, list) or len(rows) != 1 or not isinstance(rows[0], dict):
        raise ValueError("Grok did not return exactly one image original. The request will not be repeated.")
    encoded = rows[0].get("b64_json")
    if not isinstance(encoded, str) or len(encoded) > MAX_IMAGE * 4 // 3 + 4:
        raise ValueError("Grok returned a missing or oversized image original.")
    data = base64.b64decode(encoded, validate=True)
    mime = _image_type(data)
    path = workdir / ("native-image.png" if mime == "image/png" else "native-image.jpg")
    with path.open("xb") as handle:
        handle.write(data)
        handle.flush()
        os.fsync(handle.fileno())
    return {"status": "complete", "path": str(path), "remote": remote}


def _download(url, workdir, deadline):
    """Signed URLs stay in memory. Never send the account bearer to a media host."""
    if not isinstance(url, str):
        raise ValueError("The completed video has no download URL.")
    parsed = _network_url(url)
    try:
        address = ipaddress.ip_address(parsed.hostname)
    except ValueError:
        address = None
    if (
        (address is not None and not address.is_global)
        or parsed.hostname == "localhost"
        or parsed.hostname.endswith(".local")
    ):
        raise ValueError("The media download target is not public HTTPS.")
    # _opener resolves/pins public addresses and forbids redirects, including DNS rebinding.
    path = workdir / ("native-video-" + uuid.uuid4().hex + ".mp4")
    pending = path.with_suffix(".part")
    request = Request(url, method="GET")  # noqa: S310 - HTTPS validated above, public DNS pinned by _opener
    with pending.open("xb") as handle:
        with _opener().open(request, timeout=min(60, _remaining(deadline))) as response:
            _read(response, MAX_VIDEO, deadline, handle)
        handle.flush()
        os.fsync(handle.fileno())
    if path.exists() or path.is_symlink():
        raise ValueError("The native video original already exists and will not be overwritten.")
    pending.rename(path)
    return path


def _poll(workdir, remote, credentials, deadline):
    request_id = remote.get("requestId")
    if not isinstance(request_id, str) or not _REQUEST_ID.fullmatch(request_id):
        raise ValueError("The recorded video request identity is missing or invalid.")
    while True:
        result = _json("/videos/" + request_id, credentials, deadline)
        status = result.get("status")
        if status == "done":
            video = result.get("video")
            path = _download(video.get("url") if isinstance(video, dict) else None, workdir, deadline)
            return {"status": "complete", "path": str(path), "remote": remote}
        if status in {"failed", "expired"}:
            return _status(
                "failed", "The recorded Grok video request " + status + ". No new generation was sent.", remote
            )
        if status not in {"pending", "processing", "in_progress"}:
            raise ValueError("Grok returned an unknown video status. Keep the recorded request; do not resubmit.")
        remaining = _remaining(deadline)
        if remaining <= POLL_S:
            return {"status": "pending", "remote": remote}
        time.sleep(POLL_S)


def _status(status, message, remote=None):
    result = {"status": status, "error": message, "code": status}
    if remote:
        result["remote"] = remote
    return result


def _failure(exc, *, sent=False, remote=None):
    if isinstance(exc, HTTPError):
        code = exc.code
        exc.close()
        status = (
            "auth"
            if code in {HTTPStatus.UNAUTHORIZED, HTTPStatus.FORBIDDEN}
            else "quota"
            if code == HTTPStatus.TOO_MANY_REQUESTS
            else "unknown"
            if code >= HTTPStatus.INTERNAL_SERVER_ERROR or code == HTTPStatus.REQUEST_TIMEOUT
            else "failed"
        )
        outcome = _status(status, f"Grok OAuth media rejected (HTTP {code}). No retry or billing fallback.", remote)
        if (
            sent
            and not remote
            and HTTPStatus.BAD_REQUEST <= code < HTTPStatus.INTERNAL_SERVER_ERROR
            and code != HTTPStatus.REQUEST_TIMEOUT
        ):
            outcome["submit_outcome"] = "rejected"
        return outcome
    if isinstance(exc, (OSError, URLError, TimeoutError)):
        return _status(
            "unknown" if sent or remote else "auth",
            "Grok media transport was interrupted. Resume only a recorded request; never resubmit.",
            remote,
        )
    return _status(
        "unknown" if sent and not remote else "failed",
        "Grok media output is missing or invalid. No retry was sent.",
        remote,
    )


def produce(project, job, workdir, *, timeout, on_submitted):
    request = job.get("request") if isinstance(job, dict) else None
    if not isinstance(request, dict):
        return _status("unsupported", "The frozen native OAuth request is missing.")
    try:
        kind = _frozen(request)
    except ValueError as exc:
        return _status("unsupported", str(exc))
    try:
        credentials = _credentials()
    except ProviderError as exc:
        return _status("auth", str(exc))
    try:
        payload, inputs = _payload(project, request, kind, job, workdir)
    except (ValueError, OSError) as exc:
        return _status("unsupported", str(exc))
    deadline = time.monotonic() + min(MAX_SECONDS, max(0.1, timeout))
    remote = None
    try:
        result = _json(
            "/images/edits"
            if request["tool"] == "image_edit"
            else "/images/generations"
            if kind == "image"
            else "/videos/generations",
            credentials,
            deadline,
            body=payload,
            session=request["session_id"],
        )
        remote = _remote(request)
        if inputs:
            remote["imageInputs"] = inputs
        if kind == "video":
            request_id = result.get("request_id")
            if not isinstance(request_id, str) or not _REQUEST_ID.fullmatch(request_id):
                raise ValueError("No valid video request identity was returned.")
            remote["requestId"] = request_id
        on_submitted(remote)
        return (
            _image_result(result, workdir, remote) if kind == "image" else _poll(workdir, remote, credentials, deadline)
        )
    except (OSError, URLError, ValueError, binascii.Error) as exc:
        return _failure(exc, sent=True, remote=remote)


def retrieve(job, workdir, *, timeout):
    """Read the existing video request. There is deliberately no POST on this path."""
    remote = job.get("remote") or {}
    if remote.get("transport") != "oauth-imagine" or not remote.get("requestId"):
        return _status("unsupported", "No retained OAuth video request can be retrieved.")
    try:
        credentials = _credentials()
    except ProviderError as exc:
        return _status("auth", str(exc), remote)
    try:
        return _poll(workdir, remote, credentials, time.monotonic() + min(MAX_SECONDS, max(0.1, timeout)))
    except (OSError, URLError, ValueError) as exc:
        return _failure(exc, remote=remote)
