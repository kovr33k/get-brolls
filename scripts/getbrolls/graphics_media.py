"""Graphics background selection, actual representation identity and freeze copies.

Public functions are the frozen #56 media seam. This module does not import
graphics.py, search providers, or copy private VO/originals into render props.
"""

from __future__ import annotations

import json
import math
import os
import re
import shutil
import stat
from pathlib import Path
from typing import TYPE_CHECKING

from .ledger import digest
from .media import run as media_run
from .models import require_fetch
from .models import signature as candidate_signature

if TYPE_CHECKING:
    from typing import TypeGuard

MEDIA_SCHEMA = 1
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
OWNED_MEDIA_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
_WINDOWS_RESERVED = re.compile(r"^(?:con|prn|aux|nul|com[1-9]|lpt[1-9])$", re.IGNORECASE)
_CONTROL = re.compile(r"[\x00-\x1f\x7f]")
_PROSE_CONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
_ILLEGAL_PATH = re.compile(r'[<>"|?*]')
MEDIA_PREFIXES = ("previews/", "clips/")
USE_STATES = ("permitted", "restricted", "unknown")
FITS = ("contain", "cover")
KINDS = ("video", "image")
CLOCK_STATES = ("resolved", "unresolved", "not_applicable")
FRAME_ROUNDING = "half_up_nonnegative"
VIDEO_SUFFIXES = {".mp4", ".mov", ".m4v", ".webm", ".mkv"}
IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp"}
VIDEO_FORMAT_TOKENS = {
    "mp4",
    "mov",
    "m4a",
    "m4v",
    "3gp",
    "3g2",
    "mj2",
    "matroska",
    "webm",
    "avi",
    "mpegts",
    "mpeg",
    "ogv",
    "flv",
    "asf",
    "nut",
    "quicktime",
    "ismv",
}
IMAGE_FORMAT_TOKENS = {
    "image2",
    "image2pipe",
    "png_pipe",
    "jpeg_pipe",
    "jpg_pipe",
    "bmp_pipe",
    "ppm_pipe",
    "tiff_pipe",
    "webp_pipe",
    "gif_pipe",
    "png",
    "jpeg",
    "jpg",
    "bmp",
    "ppm",
    "tiff",
    "mjpeg",
    "singlejpeg",
    "webp",
}
STILL_CODECS = {"png", "bmp", "tiff", "ppm", "pgm", "pam", "jpeg", "mjpeg"}
ANIMATION_CODECS = {"gif", "webp", "apng"}
ANIMATION_FORMAT_TOKENS = {"gif", "gif_pipe", "webp", "webp_pipe", "apng"}
ANIMATION_SUFFIXES = {".gif", ".webp"}
ANIMATION_FRAME_PROBE_LIMIT = 2
WEBP_FORMAT_TOKENS = {"webp", "webp_pipe"}
WEBP_ANIMATION_FLAG = 0x02
RIFF_HEADER_BYTES = 12
RIFF_CHUNK_HEADER_BYTES = 8
MAX_WEBP_CHUNKS = 4096
VIDEO_CODECS = {
    "h264",
    "avc1",
    "hevc",
    "h265",
    "hev1",
    "vp8",
    "vp9",
    "av1",
    "av01",
    "mpeg4",
    "mpeg2video",
    "prores",
    "dnxhd",
    "cfhd",
    "hap",
    "ffv1",
    "theora",
    "wmv2",
    "wmv3",
    "msmpeg4v3",
    "h263",
}
MAX_TEXT = 8000
MAX_BY = 500
MAX_CONDITIONS = 2000
MAX_URL = 2000
MAX_BACKGROUND_BYTES = 64 * 1024 * 1024
MAX_BACKGROUND_DURATION_S = 180
_LINK_MSG = "Graphics background path is a symlink or junction and will not be followed: "
_MISSING_NEXT = (
    "Reuse suitable saved project media first. Use the existing search, inspect and preview "
    "commands; missing background is not replaced with generic footage and does not start a "
    "new provider search."
)
RECORD_KEYS = (
    "schema_version",
    "candidate_id",
    "ref",
    "kind",
    "sha256",
    "bytes",
    "width",
    "height",
    "representation",
    "provider",
    "source_id",
    "source_url",
    "source_start_s",
    "source_end_s",
    "representation_source_start_s",
    "local_start_s",
    "local_end_s",
    "local_duration_s",
    "local_fps",
    "fit",
    "fps",
    "duration_in_frames",
    "frame_rounding",
    "clock_state",
    "candidate_signature",
    "candidate_rights",
    "candidate_acquisition",
    "candidate_approval",
    "suitability",
    "material_use",
)


def seconds_to_frame(seconds, fps):
    """Non-negative half-up: frame = floor(t * fps + 0.5). Error is at most one frame."""
    if not isinstance(seconds, (int, float)) or isinstance(seconds, bool) or not math.isfinite(seconds) or seconds < 0:
        raise ValueError("Timing values must be finite seconds greater than or equal to 0.")
    if not isinstance(fps, (int, float)) or isinstance(fps, bool) or not math.isfinite(fps) or fps <= 0:
        raise ValueError("Profile fps must be a finite number greater than 0.")
    return math.floor(float(seconds) * float(fps) + 0.5)


def _frame_tolerance_s(fps):
    return 1.0 / float(fps)


def _same_clock(left, right, fps):
    return abs(float(left) - float(right)) <= _frame_tolerance_s(fps)


def _is_int(value) -> TypeGuard[int]:
    return type(value) is int


def _is_number(value) -> TypeGuard[int | float]:
    return type(value) in (int, float) and not isinstance(value, bool) and math.isfinite(value)


def _as_dict(value):
    return value if isinstance(value, dict) else {}


def _bounded_prose(value, limit=MAX_TEXT) -> TypeGuard[str]:
    return isinstance(value, str) and bool(value.strip()) and len(value) <= limit and not _PROSE_CONTROL.search(value)


def _sha256(value) -> TypeGuard[str]:
    return isinstance(value, str) and bool(SHA256_RE.fullmatch(value))


def _contained(root, candidate):
    root_s = os.path.normcase(str(Path(root).resolve())).rstrip("\\/")
    cand_s = os.path.normcase(str(Path(candidate).resolve()))
    return cand_s == root_s or cand_s.startswith(root_s + os.sep)


def _is_link_or_junction(path):
    path = Path(path)
    try:
        if path.is_symlink():
            return True
    except OSError:
        return True
    try:
        info = os.lstat(path)
    except FileNotFoundError:
        return False
    except OSError:
        return True
    if stat.S_ISLNK(info.st_mode):
        return True
    attrs = getattr(info, "st_file_attributes", 0)
    return bool(attrs & stat.FILE_ATTRIBUTE_REPARSE_POINT)


def _refuse_if_link(path):
    path = Path(path)
    try:
        present = path.exists() or path.is_symlink()
    except OSError:
        present = True
    if not present:
        return
    if _is_link_or_junction(path):
        raise ValueError(_LINK_MSG + str(path))


def _assert_lexical_chain(path):
    cursor = Path(path)
    while True:
        _refuse_if_link(cursor)
        parent = cursor.parent
        if parent == cursor:
            break
        cursor = parent


def _assert_ancestors(root, path):
    """Refuse links on dest and every original lexical root ancestor before resolve()."""
    _assert_lexical_chain(root)
    _assert_lexical_chain(path)


def relative_media_ref(value, prefixes=MEDIA_PREFIXES):
    if not isinstance(value, str) or not value or _CONTROL.search(value):
        raise ValueError("Graphics background paths must be relative posix paths.")
    if "\\" in value or value.startswith(("/", "~")) or ":" in value or "//" in value:
        raise ValueError(
            "Graphics background paths must be relative posix paths without drive letters, colons, "
            "ADS streams, UNC, URLs or backslashes."
        )
    if _ILLEGAL_PATH.search(value):
        raise ValueError("Graphics background paths must be relative posix paths without Windows reserved characters.")
    path = Path(value)
    if ".." in path.parts or path.is_absolute():
        raise ValueError("Graphics background paths must be relative posix paths and cannot leave the project tree.")
    if any(_WINDOWS_RESERVED.fullmatch(part.split(".")[0]) for part in path.parts):
        raise ValueError("Graphics background paths must be relative posix paths without reserved Windows names.")
    if not value.startswith(prefixes):
        raise ValueError("Graphics background references must stay under previews/ or clips/. " + _MISSING_NEXT)
    return value


def _confine_planned(root, path):
    base = Path(root)
    path = Path(path)
    _assert_ancestors(base, path)
    if path.exists() or path.is_symlink():
        try:
            resolved_root = base.resolve()
            resolved = path.resolve()
        except OSError as exc:
            raise ValueError("Graphics background path could not be resolved.") from exc
        if _is_link_or_junction(path) or not _contained(resolved_root, resolved):
            raise ValueError("Graphics background path resolves outside the project or through a link.")
        return resolved
    parent = path.parent
    while not parent.exists() and parent != parent.parent:
        parent = parent.parent
    existing = parent if parent.exists() else base
    _assert_ancestors(base, existing)
    try:
        resolved_root = base.resolve()
        resolved_parent = existing.resolve()
    except OSError as exc:
        raise ValueError("Graphics background path could not be resolved.") from exc
    if not _contained(resolved_root, resolved_parent):
        raise ValueError("Graphics background path resolves outside the project.")
    try:
        rest = path.relative_to(existing)
    except ValueError as exc:
        raise ValueError("Graphics background path resolves outside the project.") from exc
    if ".." in rest.parts:
        raise ValueError("Graphics background path resolves outside the project.")
    planned = resolved_parent.joinpath(*rest.parts)
    if not _contained(resolved_root, planned):
        raise ValueError("Graphics background path resolves outside the project.")
    return planned


def _confine_existing(root, rel, prefixes=MEDIA_PREFIXES):
    relative_media_ref(rel, prefixes)
    base = Path(root)
    path = base.joinpath(*rel.split("/"))
    _assert_ancestors(base, path)
    try:
        resolved_root = base.resolve()
        resolved = path.resolve()
    except OSError as exc:
        raise ValueError("Graphics background reference could not be resolved: " + rel) from exc
    if not _contained(resolved_root, resolved):
        raise ValueError("Graphics background reference resolves outside the project: " + rel)
    if _is_link_or_junction(path) or _is_link_or_junction(resolved):
        raise ValueError("Graphics background reference is a symlink or junction: " + rel)
    if not resolved.is_file():
        raise ValueError("Graphics background reference is missing: " + rel + ". " + _MISSING_NEXT)
    return resolved


def _finite_float(value):
    if value in (None, "N/A", ""):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(number):
        return None
    return number


def _profile_fps(profile):
    if not isinstance(profile, dict):
        raise ValueError("Graphics background needs the project composition profile.")
    fps = profile.get("fps")
    if not _is_number(fps) or fps <= 0:
        raise ValueError("Profile fps must be a finite number greater than 0.")
    rounding = profile.get("frame_rounding")
    if rounding is not None and rounding != FRAME_ROUNDING:
        raise ValueError("Graphics background requires half_up_nonnegative frame rounding.")
    return float(fps)


def _scene_frames(timing):
    if not isinstance(timing, dict):
        raise ValueError("Graphics background needs the occurrence timing record.")
    frames = timing.get("duration_in_frames")
    if not _is_int(frames) or frames < 1:
        raise ValueError("Scene duration_in_frames must be a positive integer.")
    basis = timing.get("basis")
    if basis not in ("estimated", "explicit"):
        raise ValueError("Timing basis must be estimated or explicit.")
    return frames, basis


def _stored_fps(fps):
    return int(fps) if float(fps).is_integer() else float(fps)


def _optional_url(value):
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError("Background source_url must be a string or null.")
    text = value.strip()
    if not text:
        return None
    if _CONTROL.search(text) or len(text) > MAX_URL:
        raise ValueError("Background source_url must be original recorded text without control characters.")
    return text


def _candidate_media_paths(candidate):
    preview = candidate.get("preview") if isinstance(candidate.get("preview"), dict) else {}
    output = candidate.get("output") if isinstance(candidate.get("output"), dict) else {}
    return [
        path
        for path in (output.get("path"), preview.get("contact_sheet_path"), preview.get("poster_path"))
        if isinstance(path, str) and path
    ]


def _lookup_candidate(items, ref, candidate_id):
    if not isinstance(items, list):
        raise ValueError("Background items must be the existing project candidate list. " + _MISSING_NEXT)
    matches = []
    by_id = None
    for candidate in items:
        if not isinstance(candidate, dict):
            continue
        if candidate.get("id") == candidate_id:
            by_id = candidate
        if ref in _candidate_media_paths(candidate):
            matches.append(candidate)
    if by_id is None:
        raise ValueError(
            "Background candidate_id does not exist in this project: " + str(candidate_id) + ". " + _MISSING_NEXT
        )
    if ref not in _candidate_media_paths(by_id):
        raise ValueError("Background ref is not that candidate's recorded output or preview path. " + _MISSING_NEXT)
    if len(matches) > 1 and any(item is not by_id and item.get("id") != by_id.get("id") for item in matches):
        raise ValueError("Background ref matches multiple candidates; pass the explicit saved candidate_id.")
    return by_id


def _format_tokens(format_name):
    text = str(format_name or "").lower().replace(",", " ")
    return {part.strip() for part in text.split() if part.strip()}


def _frame_count(stream):
    frames = stream.get("nb_frames")
    if isinstance(frames, str) and frames.isdigit():
        return int(frames)
    if _is_int(frames) and frames >= 0:
        return frames
    return None


def _animation_container(format_name, codec_name, path):
    tokens = _format_tokens(format_name)
    codec = str(codec_name or "").lower()
    suffix = Path(path).suffix.lower()
    return codec in ANIMATION_CODECS or bool(tokens & ANIMATION_FORMAT_TOKENS) or suffix in ANIMATION_SUFFIXES


def _decoded_frames_from_payload(payload):
    if not isinstance(payload, dict):
        return None
    frames = payload.get("frames")
    if isinstance(frames, list) and frames:
        return len(frames)
    streams = [item for item in (payload.get("streams") or []) if isinstance(item, dict)]
    if not streams:
        return None
    read = streams[0].get("nb_read_frames")
    if isinstance(read, str) and read.isdigit():
        return int(read)
    if _is_int(read) and read >= 0:
        return read
    return None


def _count_decoded_frames(path, *, limit=ANIMATION_FRAME_PROBE_LIMIT):
    """Count decoded frames inside a bounded window. None means the count is unproven."""
    if not _is_int(limit) or limit < 1:
        return None
    try:
        payload = json.loads(
            media_run(
                [
                    "ffprobe",
                    "-v",
                    "error",
                    "-select_streams",
                    "v:0",
                    "-read_intervals",
                    "%+#" + str(limit),
                    "-count_frames",
                    "-show_frames",
                    "-show_streams",
                    "-of",
                    "json",
                    str(path),
                ],
                op="graphics_media_count_frames",
            )
        )
    except (json.JSONDecodeError, ValueError):
        return None
    return _decoded_frames_from_payload(payload)


def _is_webp_representation(format_name, codec_name, path):
    tokens = _format_tokens(format_name)
    codec = str(codec_name or "").lower()
    return codec == "webp" or bool(tokens & WEBP_FORMAT_TOKENS) or Path(path).suffix.lower() == ".webp"


def _webp_riff_frame_count(path):
    """Count still vs ANMF frames from original RIFF metadata. None is incomplete/unknown."""
    try:
        with Path(path).open("rb") as handle:
            header = handle.read(RIFF_HEADER_BYTES)
            if len(header) != RIFF_HEADER_BYTES or header[:4] != b"RIFF" or header[8:12] != b"WEBP":
                return None
            remaining = int.from_bytes(header[4:8], "little") - 4
            if remaining < 0 or remaining + RIFF_HEADER_BYTES != os.fstat(handle.fileno()).st_size:
                return None
            return _webp_frames_from_riff_chunks(handle, remaining)
    except OSError:
        return None


def _webp_conclude_frames(seen_still, animated, anmf, *, complete):
    if anmf > 1:
        return anmf
    if not complete:
        return None
    if animated:
        return 1 if anmf == 1 else None
    return 1 if seen_still else None


def _webp_frames_from_riff_chunks(handle, remaining):
    seen_still = False
    animated = False
    anmf = 0
    for _ in range(MAX_WEBP_CHUNKS):
        if remaining < RIFF_CHUNK_HEADER_BYTES:
            return _webp_conclude_frames(seen_still, animated, anmf, complete=remaining == 0)
        header = handle.read(RIFF_CHUNK_HEADER_BYTES)
        if len(header) != RIFF_CHUNK_HEADER_BYTES:
            return None
        remaining -= RIFF_CHUNK_HEADER_BYTES
        fourcc = header[:4]
        size = int.from_bytes(header[4:8], "little")
        padded = size + (size & 1)
        if padded > remaining:
            return None
        counted = _webp_apply_chunk(handle, fourcc, size, padded)
        if counted is None:
            return None
        still_chunk, anim_chunk, anmf_chunk = counted
        seen_still = seen_still or still_chunk
        animated = animated or anim_chunk
        anmf += anmf_chunk
        remaining -= padded
        if anmf > 1:
            return anmf
    return _webp_conclude_frames(seen_still, animated, anmf, complete=False)


def _webp_apply_vp8x(handle, size, padded):
    if size < 1:
        return None
    flags = handle.read(1)
    if len(flags) != 1:
        return None
    skip = padded - 1
    if skip and _webp_skip(handle, skip) is None:
        return None
    return False, bool(flags[0] & WEBP_ANIMATION_FLAG), 0


def _webp_apply_chunk(handle, fourcc, size, padded):
    if fourcc == b"VP8X":
        return _webp_apply_vp8x(handle, size, padded)
    if fourcc in (b"ANIM", b"ANMF"):
        if _webp_skip(handle, padded) is None:
            return None
        return False, True, 1 if fourcc == b"ANMF" else 0
    if _webp_skip(handle, padded) is None:
        return None
    return fourcc in (b"VP8 ", b"VP8L"), False, 0


def _webp_skip(handle, count):
    try:
        handle.seek(count, os.SEEK_CUR)
    except OSError:
        return None
    return True


def _resolve_webp_frame_count(path, reported):
    container = _webp_riff_frame_count(path)
    if not _is_int(container):
        return None
    if container > 1:
        return container
    if _is_int(reported) and reported > 1:
        return reported
    decoded = _count_decoded_frames(path)
    if not _is_int(decoded) or decoded < 1:
        return None
    if decoded > 1:
        return decoded
    return container


def _resolve_probe_frame_count(path, stream, format_name, codec_name):
    reported = _frame_count(stream)
    if not _animation_container(format_name, codec_name, path):
        return reported
    if _is_webp_representation(format_name, codec_name, path):
        return _resolve_webp_frame_count(path, reported)
    if _is_int(reported) and reported > 1:
        return reported
    return _count_decoded_frames(path)


def _classify_background_kind(format_name, codec_name, duration, frame_count, path):
    """Classify from probed container/codec. Duration never turns a video into a photograph.

    GIF/WebP/APNG-like containers are stills only after a proven single frame.
    WebP requires original RIFF animation/frame metadata; one decoded frame is not
    complete container proof. Short or missing duration does not freeze an animation
    as an image.
    """
    path = Path(path)
    tokens = _format_tokens(format_name)
    codec = str(codec_name or "").lower()
    suffix = path.suffix.lower()
    video_container = bool(tokens & VIDEO_FORMAT_TOKENS) or suffix in VIDEO_SUFFIXES
    if video_container:
        if duration is None or duration <= 0:
            raise ValueError("Video duration is missing or not finite: " + path.name)
        return "video"
    if _animation_container(format_name, codec_name, path):
        if not _is_int(frame_count) or frame_count < 1:
            raise ValueError(
                "Uncertain animated image cannot be used as a still photograph without a proven "
                "single frame: " + path.name
            )
        if frame_count > 1:
            raise ValueError(
                "Unsupported animated image cannot be used as a still photograph or retimed video: " + path.name
            )
        return "image"
    still = bool(tokens & IMAGE_FORMAT_TOKENS) or codec in STILL_CODECS or suffix in IMAGE_SUFFIXES
    if still:
        return "image"
    if codec in VIDEO_CODECS:
        if duration is None or duration <= 0:
            raise ValueError("Video duration is missing or not finite: " + path.name)
        return "video"
    raise ValueError("Unknown or unsupported background representation: " + path.name)


def _background_file_size(path):
    try:
        size = path.stat().st_size
    except OSError as exc:
        raise ValueError("Graphics background file could not be read: " + path.name) from exc
    if size <= 0:
        raise ValueError("Graphics background file is empty: " + path.name)
    if size > MAX_BACKGROUND_BYTES:
        raise ValueError(
            "Graphics background file exceeds the bounded size of " + str(MAX_BACKGROUND_BYTES) + " bytes."
        )
    return size


def _ffprobe_video_stream(path):
    try:
        payload = json.loads(
            media_run(
                ["ffprobe", "-v", "error", "-show_streams", "-show_format", "-of", "json", str(path)],
                op="graphics_media_probe",
            )
        )
    except json.JSONDecodeError as exc:
        raise ValueError("ffprobe did not return JSON for " + path.name + ".") from exc
    if not isinstance(payload, dict):
        raise ValueError("ffprobe metadata was malformed for " + path.name + ".")
    streams = [item for item in (payload.get("streams") or []) if isinstance(item, dict)]
    video = [item for item in streams if item.get("codec_type") == "video"]
    if not video:
        raise ValueError("File is not a decodable video or image representation: " + path.name)
    return payload, video[0]


def _stream_geometry(stream, path):
    width = stream.get("width")
    height = stream.get("height")
    if not _is_int(width) or not _is_int(height) or width < 1 or height < 1:
        raise ValueError("Background width and height must be actual positive integers: " + path.name)
    return width, height


def _stream_duration(stream, fmt):
    duration = _finite_float(stream.get("duration"))
    if duration is None:
        duration = _finite_float(fmt.get("duration"))
    return duration


def _stream_fps(stream):
    rate = stream.get("avg_frame_rate") or stream.get("r_frame_rate") or "0/1"
    if not isinstance(rate, str) or "/" not in rate:
        return None
    left, right = rate.split("/", 1)
    num = _finite_float(left)
    den = _finite_float(right)
    if num is None or den is None or den == 0:
        return None
    fps = num / den
    if fps <= 0 or not math.isfinite(fps):
        return None
    return fps


def _assert_video_probe_duration(kind, duration, path):
    if kind == "video" and (duration is None or duration <= 0):
        raise ValueError("Video duration is missing or not finite: " + path.name)
    if kind == "video" and duration is not None and duration > MAX_BACKGROUND_DURATION_S:
        raise ValueError("Background duration exceeds the bounded limit for " + path.name + ".")


def _probe_background(path):
    path = Path(path)
    size = _background_file_size(path)
    payload, stream = _ffprobe_video_stream(path)
    fmt = _as_dict(payload.get("format"))
    duration = _stream_duration(stream, fmt)
    fps = _stream_fps(stream)
    format_name = fmt.get("format_name")
    codec_name = stream.get("codec_name")
    kind = _classify_background_kind(
        format_name,
        codec_name,
        duration,
        _resolve_probe_frame_count(path, stream, format_name, codec_name),
        path,
    )
    width, height = _stream_geometry(stream, path)
    media_run(["ffmpeg", "-v", "error", "-xerror", "-i", str(path), "-f", "null", "-"], op="graphics_media_decode")
    _assert_video_probe_duration(kind, duration, path)
    return {
        "kind": kind,
        "width": width,
        "height": height,
        "duration_s": None if kind == "image" else duration,
        "fps": None if kind == "image" else fps,
        "bytes": size,
    }


def _owned_name(ref):
    suffix = Path(ref).suffix.lower()
    if suffix == ".jpeg":
        suffix = ".jpg"
    if suffix not in VIDEO_SUFFIXES and suffix not in IMAGE_SUFFIXES:
        raise ValueError("Graphics background file type is not a supported video or image container: " + ref)
    name = "background" + suffix
    if not OWNED_MEDIA_RE.fullmatch(name) or _WINDOWS_RESERVED.fullmatch(Path(name).stem):
        raise ValueError("Frozen background file name is not a safe owned identity: " + name)
    return name


def _material_evidence(value):
    if isinstance(value, str):
        value = [value]
    if not isinstance(value, list) or not value:
        raise ValueError("Background material_use evidence must be a non-empty list of original statements.")
    evidence = []
    for item in value:
        if not _bounded_prose(item, 2000):
            raise ValueError("Background material_use evidence must keep original text.")
        evidence.append(item)
    return evidence


def _normalize_candidate_rights(value):
    if value is None:
        return None
    if not isinstance(value, dict):
        raise ValueError("Background candidate_rights must be an object or null.")
    status = value.get("status")
    if status not in (None, "unknown", "permitted", "restricted"):
        raise ValueError("Background candidate_rights.status must be unknown, permitted, restricted or null.")
    evidence = value.get("evidence")
    if evidence is None:
        evidence = []
    if not isinstance(evidence, list) or any(not isinstance(item, str) for item in evidence):
        raise ValueError("Background candidate_rights.evidence must be a list of strings.")
    record = {"status": status, "evidence": list(evidence)}
    for key in ("license_name", "license_url"):
        item = value.get(key)
        if item is None:
            record[key] = None
            continue
        if not _bounded_prose(item, 2000):
            raise ValueError("Background candidate_rights " + key + " must keep original text.")
        record[key] = item
    return record


def _live_candidate_rights(candidate):
    rights = _as_dict(candidate.get("rights"))
    return {
        "status": rights.get("status") if rights.get("status") in ("unknown", "permitted", "restricted") else None,
        "evidence": list(rights.get("evidence") or []) if isinstance(rights.get("evidence"), list) else [],
        "license_name": rights.get("license_name"),
        "license_url": rights.get("license_url"),
    }


def _rights_identity(value):
    """Complete normalized rights terms: status, evidence and license fields. Not approval/signature."""
    rights = value if isinstance(value, dict) else {}
    status = rights.get("status")
    if status not in (None, "unknown", "permitted", "restricted"):
        status = None
    evidence = rights.get("evidence")
    if not isinstance(evidence, list):
        evidence = []
    evidence = tuple(item for item in evidence if isinstance(item, str))
    name = rights.get("license_name")
    url = rights.get("license_url")
    return (
        status,
        evidence,
        name if isinstance(name, str) else None,
        url if isinstance(url, str) else None,
    )


def _live_approval(candidate):
    approval = _as_dict(candidate.get("approval"))
    status = approval.get("status")
    if status not in ("pending", "approved", "rejected"):
        status = "pending"
    signature = approval.get("signature")
    if _sha256(signature):
        return {"status": status, "signature": signature}
    return {"status": status}


def _normalize_suitability(value):
    if value is None:
        return None
    if not isinstance(value, dict):
        raise ValueError("Background suitability must be an explicit {by,statement,at} decision or null.")
    by = value.get("by")
    statement = value.get("statement")
    at = value.get("at")
    if not _bounded_prose(by, MAX_BY) or not _bounded_prose(statement) or not _bounded_prose(at, MAX_URL):
        raise ValueError(
            "Background suitability must be an explicit received decision with by, statement and at; "
            "visual preview access does not invent suitability."
        )
    extra = set(value) - {"by", "statement", "at"}
    if extra:
        raise ValueError("Background suitability only records by, statement and at.")
    return {"by": by.strip(), "statement": statement, "at": at}


def _normalize_material_use(item, ref, digest_value):
    if item is None:
        return None
    if not isinstance(item, dict):
        raise ValueError("Background material_use must be an object or null.")
    declared_ref = item.get("ref", ref)
    if declared_ref != ref:
        raise ValueError("Background material_use.ref must match the selected background ref.")
    relative_media_ref(declared_ref)
    if item.get("rendered_use") not in USE_STATES:
        raise ValueError("Background material_use.rendered_use must be permitted, restricted or unknown.")
    if item.get("raw_redistribution") not in USE_STATES:
        raise ValueError("Background material_use.raw_redistribution must be permitted, restricted or unknown.")
    if not _bounded_prose(item.get("conditions"), MAX_CONDITIONS):
        raise ValueError("Background material_use must keep original conditions text.")
    supplied = item.get("sha256")
    if supplied is not None and supplied != digest_value:
        raise ValueError(
            "Background material_use sha256 does not match the confined file bytes; changed identity cannot be adopted."
        )
    return {
        "ref": declared_ref,
        "rendered_use": item["rendered_use"],
        "raw_redistribution": item["raw_redistribution"],
        "evidence": _material_evidence(item.get("evidence")),
        "conditions": item["conditions"],
        "sha256": digest_value,
    }


def _output_source_interval(candidate, ref):
    output = _as_dict(candidate.get("output"))
    if output.get("path") != ref:
        return None
    segment = _as_dict(candidate.get("segment"))
    start_s = segment.get("start_s")
    end_s = segment.get("end_s")
    if not _is_number(start_s) or not _is_number(end_s) or start_s < 0 or end_s <= start_s:
        return None
    return float(start_s), float(end_s)


def _image_clocks():
    return {
        "source_start_s": None,
        "source_end_s": None,
        "representation_source_start_s": None,
        "local_start_s": None,
        "local_end_s": None,
        "local_duration_s": None,
        "local_fps": None,
        "clock_state": "not_applicable",
    }


def _unresolved_local_clocks(duration_s, local_fps, source_start_s, source_end_s):
    return {
        "source_start_s": source_start_s,
        "source_end_s": source_end_s,
        "representation_source_start_s": None,
        "local_start_s": 0.0,
        "local_end_s": duration_s,
        "local_duration_s": duration_s,
        "local_fps": local_fps,
        "clock_state": "unresolved",
    }


def _requested_source_interval(payload):
    requested_start = payload.get("source_start_s")
    requested_end = payload.get("source_end_s")
    if requested_start is None and requested_end is None:
        return None
    if (
        not _is_number(requested_start)
        or not _is_number(requested_end)
        or requested_start < 0
        or requested_end <= requested_start
    ):
        raise ValueError("Background source_start_s/source_end_s must be a finite original-source interval.")
    return float(requested_start), float(requested_end)


def _derive_clocks(payload, candidate, ref, info, fps):  # noqa: C901 - source vs local clocks
    if info.get("kind") == "image":
        if payload.get("source_start_s") is not None or payload.get("source_end_s") is not None:
            raise ValueError("Still-image backgrounds have no fabricated time interval.")
        return _image_clocks()
    local_duration = info.get("duration_s")
    local_fps = info.get("fps")
    if not _is_number(local_duration) or local_duration <= 0:
        raise ValueError("Video duration is missing or not finite.")
    duration_s = float(local_duration)
    recorded = _output_source_interval(candidate, ref)
    requested = _requested_source_interval(payload)
    if recorded is None:
        start_s, end_s = (None, None) if requested is None else requested
        return _unresolved_local_clocks(duration_s, local_fps, start_s, end_s)
    source_start, source_end = recorded
    recorded_span = source_end - source_start
    if abs(duration_s - recorded_span) > max(0.25, 2.0 / fps):
        start_s, end_s = recorded if requested is None else requested
        return _unresolved_local_clocks(duration_s, local_fps, start_s, end_s)
    if requested is not None:
        requested_start, requested_end = requested
        if requested_start < source_start - (1.0 / fps) or requested_end > source_end + (1.0 / fps):
            raise ValueError(
                "Requested background source interval is outside the recorded cut of this output. "
                "Do not confuse source, local-media, narration and scene clocks."
            )
        local_start = requested_start - source_start
        local_end = requested_end - source_start
        if local_start < 0:
            local_start = 0.0
        if local_end > duration_s:
            if local_end - duration_s > (1.0 / fps):
                raise ValueError("Requested background interval extends past the selected representation.")
            local_end = duration_s
        if local_end <= local_start:
            raise ValueError("Mapped local background interval must be ordered and non-empty.")
        return {
            "source_start_s": requested_start,
            "source_end_s": requested_end,
            "representation_source_start_s": source_start,
            "local_start_s": local_start,
            "local_end_s": local_end,
            "local_duration_s": duration_s,
            "local_fps": local_fps,
            "clock_state": "resolved",
        }
    return {
        "source_start_s": source_start,
        "source_end_s": source_end,
        "representation_source_start_s": source_start,
        "local_start_s": 0.0,
        "local_end_s": duration_s,
        "local_duration_s": duration_s,
        "local_fps": local_fps,
        "clock_state": "resolved",
    }


def _assert_duration_sufficient(kind, clocks, fps, duration_in_frames):
    if kind != "video":
        return
    local_start = clocks["local_start_s"]
    local_end = clocks["local_end_s"]
    available = max(1, seconds_to_frame(local_end, fps) - seconds_to_frame(local_start, fps))
    if available < duration_in_frames:
        raise ValueError(
            "Selected background video is shorter than the scene at the composition fps; "
            "the renderer will not loop or freeze missing frames."
        )


def _assert_claimed_geometry(payload, info):
    for key in ("width", "height"):
        claimed = payload.get(key)
        if claimed is None:
            continue
        if claimed != info[key]:
            raise ValueError(
                "Background "
                + key
                + " must be the actual representation size "
                + str(info[key])
                + ", not a FullHD composition claim."
            )
    claimed_hash = payload.get("sha256")
    if claimed_hash is not None and not _sha256(claimed_hash):
        raise ValueError("Background sha256 must be a 64-character hex digest.")


def _bind_live_rights(entry, candidate):
    live_rights = _live_candidate_rights(candidate)
    supplied_rights = entry.get("candidate_rights")
    if not isinstance(supplied_rights, dict):
        entry["candidate_rights"] = live_rights
        return live_rights
    if supplied_rights.get("status") not in (None, live_rights.get("status")):
        raise ValueError("Background candidate_rights cannot override the live candidate rights status.")
    supplied_evidence = supplied_rights.get("evidence")
    if supplied_evidence is not None and list(supplied_evidence) != list(live_rights.get("evidence") or []):
        raise ValueError("Background candidate_rights.evidence cannot override the live candidate record.")
    for key in ("license_name", "license_url"):
        supplied = supplied_rights.get(key)
        if supplied is not None and supplied != live_rights.get(key):
            raise ValueError("Background candidate_rights cannot override the live candidate record.")
    entry["candidate_rights"] = live_rights
    return live_rights


def _assert_permitted_rendered_use(entry, candidate, live_rights):
    material = entry.get("material_use")
    if isinstance(material, dict) and material.get("rendered_use") == "permitted":
        try:
            require_fetch(candidate)
        except (ValueError, KeyError, TypeError) as exc:
            raise ValueError(
                "Rendered use cannot be permitted for "
                + entry["ref"]
                + " unless the bound candidate is approved with a current signature, "
                "rights are permitted with evidence, and acquisition is available. "
                "Preview access is not final use."
            ) from exc
        if live_rights.get("status") != "permitted":
            raise ValueError(
                "Candidate permission for "
                + entry["ref"]
                + " remains "
                + str(live_rights.get("status"))
                + "; local reuse does not upgrade it."
            )


def _bind_permissions(entry, candidate, digest_value):
    live_sig = candidate_signature(candidate)
    stored_sig = entry.get("candidate_signature")
    if stored_sig is not None and stored_sig != live_sig:
        raise ValueError("Background candidate_signature does not match the current saved candidate.")
    entry["candidate_signature"] = live_sig
    live_rights = _bind_live_rights(entry, candidate)
    acquisition = _as_dict(candidate.get("acquisition")).get("status")
    supplied_acq = entry.get("candidate_acquisition")
    if supplied_acq is not None and supplied_acq != acquisition:
        raise ValueError("Background candidate_acquisition cannot override the live candidate record.")
    entry["candidate_acquisition"] = acquisition
    entry["candidate_approval"] = _live_approval(candidate)
    _assert_output_hash(candidate, entry.get("ref"), digest_value)
    _assert_permitted_rendered_use(entry, candidate, live_rights)


def _assert_output_hash(candidate, ref, digest_value):
    output = _as_dict(candidate.get("output"))
    if output.get("path") == ref:
        recorded = output.get("sha256")
        if recorded is not None and recorded != digest_value:
            raise ValueError("Background bytes do not match the candidate's recorded output hash.")


def _validate_optional_number(value, flag, *, allow_null, positive=False):
    if value is None:
        if allow_null:
            return
        raise ValueError(flag + " must be a finite number.")
    if not _is_number(value) or value < 0 or (positive and value <= 0):
        raise ValueError(
            flag + " must be a finite number" + (" greater than 0." if positive else " greater than or equal to 0.")
        )


def _validate_representation(item, kind):
    representation = item.get("representation")
    if not isinstance(representation, dict):
        raise ValueError("Background representation must record the actual selected file.")
    if representation.get("width") != item.get("width") or representation.get("height") != item.get("height"):
        raise ValueError("Background representation width/height must match the probed actual dimensions.")
    if not _is_int(representation.get("bytes")) or representation["bytes"] < 1:
        raise ValueError("Background representation bytes must be a positive integer.")
    if representation.get("bytes") != item.get("bytes"):
        raise ValueError("Background representation bytes must match the selected file size.")
    if kind == "image":
        if representation.get("duration_s") is not None or representation.get("fps") is not None:
            raise ValueError("Still-image representation cannot fabricate duration or fps.")
        return
    _validate_optional_number(
        representation.get("duration_s"), "representation.duration_s", allow_null=False, positive=True
    )
    fps = representation.get("fps")
    if fps is not None and (not _is_number(fps) or fps <= 0):
        raise ValueError("representation.fps must be a finite number greater than 0 when present.")


def _assert_video_clock_bounds(item):
    fps = item.get("fps")
    if not _is_number(fps) or fps <= 0:
        raise ValueError("Background fps must be the composition fps.")
    local_start = item["local_start_s"]
    local_end = item["local_end_s"]
    local_duration = item["local_duration_s"]
    if local_end - local_duration > _frame_tolerance_s(fps):
        raise ValueError("Background local_end_s must stay inside the selected representation duration.")
    if local_start - local_duration > _frame_tolerance_s(fps):
        raise ValueError("Background local_start_s must stay inside the selected representation duration.")
    representation = item.get("representation") if isinstance(item.get("representation"), dict) else {}
    probed = representation.get("duration_s")
    if not _is_number(probed) or probed <= 0 or not _same_clock(probed, local_duration, fps):
        raise ValueError("Background local_duration_s must match the probed representation duration.")


def _assert_resolved_clock_mapping(item):
    fps = item["fps"]
    offset = item["representation_source_start_s"]
    source_start = item["source_start_s"]
    source_end = item["source_end_s"]
    local_start = item["local_start_s"]
    local_end = item["local_end_s"]
    if not _same_clock(local_start, source_start - offset, fps):
        raise ValueError(
            "Resolved background local_start_s must map from source_start_s by representation_source_start_s."
        )
    if not _same_clock(local_end, source_end - offset, fps):
        raise ValueError("Resolved background local_end_s must map from source_end_s by representation_source_start_s.")
    if not _same_clock(local_end - local_start, source_end - source_start, fps):
        raise ValueError("Resolved background local interval must match the selected source interval.")
    derived_start = offset + local_start
    derived_end = offset + local_end
    if not _same_clock(derived_start, source_start, fps) or not _same_clock(derived_end, source_end, fps):
        raise ValueError("Resolved background source interval must equal the derived original-to-local mapping.")


def _validate_image_clocks(item, state):
    if state != "not_applicable":
        raise ValueError("Still-image backgrounds use clock_state not_applicable.")
    for key in (
        "source_start_s",
        "source_end_s",
        "representation_source_start_s",
        "local_start_s",
        "local_end_s",
        "local_duration_s",
        "local_fps",
    ):
        if item.get(key) is not None:
            raise ValueError("Still-image backgrounds have no fabricated time interval.")


def _validate_source_pair(item, *, allow_null):
    _validate_optional_number(item.get("source_start_s"), "source_start_s", allow_null=allow_null)
    _validate_optional_number(item.get("source_end_s"), "source_end_s", allow_null=allow_null, positive=True)
    start_s = item.get("source_start_s")
    end_s = item.get("source_end_s")
    if start_s is not None and end_s is not None and end_s <= start_s:
        raise ValueError("Background source_end_s must be greater than source_start_s.")


def _validate_clocks(item):
    kind = item.get("kind")
    state = item.get("clock_state")
    if state not in CLOCK_STATES:
        raise ValueError("Background clock_state must be resolved, unresolved or not_applicable.")
    if kind == "image":
        _validate_image_clocks(item, state)
        return
    if state == "not_applicable":
        raise ValueError("Video backgrounds cannot use clock_state not_applicable.")
    _validate_optional_number(item.get("local_start_s"), "local_start_s", allow_null=False)
    _validate_optional_number(item.get("local_end_s"), "local_end_s", allow_null=False, positive=True)
    if item["local_end_s"] <= item["local_start_s"]:
        raise ValueError("Background local_end_s must be greater than local_start_s.")
    _validate_optional_number(item.get("local_duration_s"), "local_duration_s", allow_null=False, positive=True)
    fps = item.get("local_fps")
    if fps is not None and (not _is_number(fps) or fps <= 0):
        raise ValueError("local_fps must be a finite number greater than 0 when present.")
    _assert_video_clock_bounds(item)
    if state == "resolved":
        _validate_source_pair(item, allow_null=False)
        _validate_optional_number(
            item.get("representation_source_start_s"), "representation_source_start_s", allow_null=False
        )
        _assert_resolved_clock_mapping(item)
        return
    _validate_source_pair(item, allow_null=True)
    if item.get("representation_source_start_s") is not None:
        raise ValueError("Unresolved original-to-local mapping cannot claim representation_source_start_s.")


def _validate_identity(item):  # noqa: C901, PLR0912, PLR0915 - one check per persisted identity field
    if not isinstance(item.get("candidate_id"), str) or not item["candidate_id"].strip():
        raise ValueError("Background candidate_id must be a non-empty string.")
    relative_media_ref(item.get("ref"))
    if item.get("kind") not in KINDS:
        raise ValueError("Background kind must be video or image.")
    if not _sha256(item.get("sha256")):
        raise ValueError("Background needs a sha256 hex digest.")
    if not _is_int(item.get("bytes")) or item["bytes"] < 1:
        raise ValueError("Background bytes must be a positive integer.")
    if not _is_int(item.get("width")) or not _is_int(item.get("height")) or item["width"] < 1 or item["height"] < 1:
        raise ValueError("Background width and height must be actual positive integers.")
    if item.get("fit") not in FITS:
        raise ValueError("Background fit must be contain or cover.")
    if not _is_number(item.get("fps")) or item["fps"] <= 0:
        raise ValueError("Background fps must be the composition fps.")
    if not _is_int(item.get("duration_in_frames")) or item["duration_in_frames"] < 1:
        raise ValueError("Background duration_in_frames must be a positive integer.")
    if item.get("frame_rounding") != FRAME_ROUNDING:
        raise ValueError("Background frame_rounding must be half_up_nonnegative.")
    if not isinstance(item.get("provider"), str) or not item["provider"].strip():
        raise ValueError("Background provider must be the original candidate provider.")
    if not isinstance(item.get("source_id"), str) or not str(item["source_id"]).strip():
        raise ValueError("Background source_id must be the original candidate source_id.")
    if item.get("source_url") is not None and not isinstance(item.get("source_url"), str):
        raise ValueError("Background source_url must be a string or null.")
    if not _sha256(item.get("candidate_signature")):
        raise ValueError("Background candidate_signature must be a 64-character hex digest.")
    if not isinstance(item.get("candidate_rights"), dict):
        raise ValueError("Background candidate_rights must be an object.")
    _normalize_candidate_rights(item.get("candidate_rights"))
    approval = item.get("candidate_approval")
    if not isinstance(approval, dict) or approval.get("status") not in ("pending", "approved", "rejected"):
        raise ValueError("Background candidate_approval.status must remain a recorded approval state.")
    if approval.get("signature") is not None and not _sha256(approval.get("signature")):
        raise ValueError("Background candidate_approval.signature must be a hex digest when present.")
    if item.get("candidate_acquisition") is not None and (
        not isinstance(item.get("candidate_acquisition"), str) or not item["candidate_acquisition"].strip()
    ):
        raise ValueError("Background candidate_acquisition must be recorded text or null.")
    if item.get("suitability") is not None:
        _normalize_suitability(item.get("suitability"))
    material = item.get("material_use")
    if material is not None:
        if not isinstance(material, dict):
            raise ValueError("Background material_use must be an object or null.")
        if material.get("rendered_use") not in USE_STATES or material.get("raw_redistribution") not in USE_STATES:
            raise ValueError("Background material_use needs rendered_use and raw_redistribution.")
        _material_evidence(material.get("evidence"))
        if not _bounded_prose(material.get("conditions"), MAX_CONDITIONS):
            raise ValueError("Background material_use must keep original conditions text.")
        if material.get("ref") != item.get("ref"):
            raise ValueError("Background material_use.ref must match the selected background ref.")
        if not _sha256(material.get("sha256")):
            raise ValueError("Background material_use needs a sha256 hex digest.")
        if material.get("sha256") != item.get("sha256"):
            raise ValueError("Background material_use sha256 must match the selected background identity.")


def _validate_record(record):
    if not isinstance(record, dict):
        raise ValueError("Graphics background record must be an object or null.")
    extra = set(record) - set(RECORD_KEYS)
    if extra:
        raise ValueError("Graphics background record has unsupported keys: " + ", ".join(sorted(extra)) + ".")
    missing = [key for key in RECORD_KEYS if key not in record]
    if missing:
        raise ValueError("Graphics background record is missing " + ", ".join(missing) + ".")
    if record.get("schema_version") != MEDIA_SCHEMA:
        raise ValueError("Graphics background schema_version must be 1.")
    _validate_identity(record)
    _validate_representation(record, record["kind"])
    _validate_clocks(record)


def validate_background(record):
    """Structural saved-record validation with no file reads. None is legacy absent-background."""
    if record is not None:
        _validate_record(record)


def _empty_freeze():
    return {"background": None, "assets": []}


def normalize_background(root, payload, profile, timing, *, items):
    """Validate a bounded explicit candidate/ref against saved media and the actual file."""
    fps = _profile_fps(profile)
    duration_in_frames = _scene_frames(timing)[0]
    if payload is None:
        return None
    if not isinstance(payload, dict):
        raise ValueError("Graphics background payload must be a JSON object.")
    if payload.get("schema_version") not in (None, MEDIA_SCHEMA):
        raise ValueError("Graphics background schema_version must be 1.")
    candidate_id = payload.get("candidate_id")
    ref = payload.get("ref")
    if not isinstance(candidate_id, str) or not candidate_id.strip() or not isinstance(ref, str) or not ref.strip():
        raise ValueError("Background payload needs candidate_id and ref. " + _MISSING_NEXT)
    relative_media_ref(ref)
    root = Path(root)
    _assert_ancestors(root, root)
    candidate = _lookup_candidate(items, ref, candidate_id.strip())
    path = _confine_existing(root, ref)
    actual = digest(path)
    claimed = payload.get("sha256")
    if claimed not in (None, actual):
        raise ValueError("Background sha256 does not match the confined file: " + ref)
    _assert_output_hash(candidate, ref, actual)
    info = _probe_background(path)
    _assert_claimed_geometry(payload, info)
    kind = info["kind"]
    clocks = _derive_clocks(payload, candidate, ref, info, fps)
    _assert_duration_sufficient(kind, clocks, fps, duration_in_frames)
    fit = payload.get("fit", "contain")
    if fit not in FITS:
        raise ValueError("Background fit must be contain or cover.")
    record = {
        "schema_version": MEDIA_SCHEMA,
        "candidate_id": candidate_id.strip(),
        "ref": ref,
        "kind": kind,
        "sha256": actual,
        "bytes": info["bytes"],
        "width": info["width"],
        "height": info["height"],
        "representation": {
            "width": info["width"],
            "height": info["height"],
            "duration_s": info["duration_s"],
            "fps": info["fps"],
            "bytes": info["bytes"],
        },
        "provider": candidate.get("provider"),
        "source_id": str(candidate.get("source_id")),
        "source_url": _optional_url(candidate.get("source_url")),
        "source_start_s": clocks["source_start_s"],
        "source_end_s": clocks["source_end_s"],
        "representation_source_start_s": clocks["representation_source_start_s"],
        "local_start_s": clocks["local_start_s"],
        "local_end_s": clocks["local_end_s"],
        "local_duration_s": clocks["local_duration_s"],
        "local_fps": clocks["local_fps"],
        "fit": fit,
        "fps": _stored_fps(fps),
        "duration_in_frames": duration_in_frames,
        "frame_rounding": FRAME_ROUNDING,
        "clock_state": clocks["clock_state"],
        "candidate_signature": payload.get("candidate_signature"),
        "candidate_rights": _normalize_candidate_rights(payload.get("candidate_rights")),
        "candidate_acquisition": payload.get("candidate_acquisition"),
        "candidate_approval": None,
        "suitability": _normalize_suitability(payload.get("suitability")),
        "material_use": _normalize_material_use(payload.get("material_use"), ref, actual),
    }
    _bind_permissions(record, candidate, actual)
    validate_background(record)
    return record


def _confine_reason(exc, missing_code):
    message = str(exc)
    if "symlink or junction" in message.lower():
        return message
    if "search, inspect and preview" in message:
        return missing_code + ": " + message
    return missing_code


def _permission_reasons(record, candidate, actual):
    reasons = []
    if record.get("suitability") is None:
        reasons.append("missing_suitability")
    material = record.get("material_use") if isinstance(record.get("material_use"), dict) else None
    rendered = material.get("rendered_use") if material else None
    if rendered != "permitted":
        reasons.append("unresolved_background_permission")
    if candidate is None:
        reasons.append("missing_background_candidate")
        return reasons
    live_sig = candidate_signature(candidate)
    if record.get("candidate_signature") != live_sig:
        reasons.append("stale_candidate_signature")
    live_rights = _live_candidate_rights(candidate)
    stored_rights = record.get("candidate_rights") if isinstance(record.get("candidate_rights"), dict) else {}
    if _rights_identity(stored_rights) != _rights_identity(live_rights):
        reasons.append("unresolved_background_permission")
    approval = _as_dict(candidate.get("approval"))
    stored_approval = _as_dict(record.get("candidate_approval"))
    if stored_approval.get("status") != approval.get("status"):
        reasons.append("stale_candidate_signature")
    if rendered == "permitted":
        try:
            require_fetch(candidate)
        except (ValueError, KeyError, TypeError):
            reasons.append("unresolved_background_permission")
        output = _as_dict(candidate.get("output"))
        if output.get("path") == record.get("ref") and output.get("sha256") not in (None, actual):
            reasons.append("changed_background_hash")
    return reasons


def _file_reasons(root, record, fps):
    try:
        path = _confine_existing(root, record.get("ref"))
        actual = digest(path)
    except ValueError as exc:
        return [_confine_reason(exc, "missing_background_file")], None
    except OSError:
        return ["missing_background_file"], None
    reasons = []
    if actual != record.get("sha256"):
        reasons.append("changed_background_hash")
    try:
        info = _probe_background(path)
        if info["width"] != record.get("width") or info["height"] != record.get("height"):
            reasons.append("changed_background_hash")
        if info.get("kind") != record.get("kind"):
            reasons.append("changed_background_hash")
        if record.get("kind") == "video" and record.get("clock_state") == "resolved":
            local_end = record.get("local_end_s")
            if _is_number(local_end) and local_end - (info.get("duration_s") or 0) > (1.0 / fps):
                reasons.append("insufficient_background_duration")
    except ValueError:
        reasons.append("undecodable_background")
    return reasons, actual


def _live_clock_reasons(record, candidate, fps):  # noqa: PLR0911 - each mapping mismatch is one unresolved reason
    if record.get("kind") != "video" or record.get("clock_state") != "resolved":
        return []
    if candidate is None:
        return []
    recorded = _output_source_interval(candidate, record.get("ref"))
    if recorded is None:
        return ["unresolved_clock_mapping"]
    live_start, live_end = recorded
    offset = record.get("representation_source_start_s")
    source_start = record.get("source_start_s")
    source_end = record.get("source_end_s")
    local_start = record.get("local_start_s")
    local_end = record.get("local_end_s")
    if not all(_is_number(value) for value in (offset, source_start, source_end, local_start, local_end)):
        return ["unresolved_clock_mapping"]
    if not _same_clock(offset, live_start, fps):
        return ["unresolved_clock_mapping"]
    if source_start < live_start - _frame_tolerance_s(fps) or source_end > live_end + _frame_tolerance_s(fps):
        return ["unresolved_clock_mapping"]
    expected_local_start = float(source_start) - live_start
    expected_local_end = float(source_end) - live_start
    if not _same_clock(local_start, expected_local_start, fps) or not _same_clock(local_end, expected_local_end, fps):
        return ["unresolved_clock_mapping"]
    derived_start = float(offset) + float(local_start)
    derived_end = float(offset) + float(local_end)
    if not _same_clock(derived_start, source_start, fps) or not _same_clock(derived_end, source_end, fps):
        return ["unresolved_clock_mapping"]
    return []


def background_readiness(root, record, profile, timing, *, items):
    """Read-only hash, clock and permission recheck. None does not invalidate a legacy scene."""
    if record is None:
        return {"ready": True, "reasons": []}
    try:
        validate_background(record)
        fps = _profile_fps(profile)
        duration_in_frames = _scene_frames(timing)[0]
    except ValueError:
        return {"ready": False, "reasons": ["invalid_background_record"]}
    if float(record["fps"]) != fps or record["duration_in_frames"] != duration_in_frames:
        return {"ready": False, "reasons": ["background_profile_mismatch"]}
    try:
        root = Path(root)
        _assert_ancestors(root, root)
    except ValueError as exc:
        return {"ready": False, "reasons": [_confine_reason(exc, "unsafe_background_ref")]}
    reasons = []
    if record.get("clock_state") == "unresolved":
        reasons.append("unresolved_clock_mapping")
    if record.get("kind") == "video" and record.get("clock_state") == "resolved":
        try:
            _assert_duration_sufficient(record["kind"], record, fps, duration_in_frames)
        except ValueError:
            reasons.append("insufficient_background_duration")
    file_reasons, actual = _file_reasons(root, record, fps)
    reasons.extend(file_reasons)
    candidate = None
    try:
        candidate = _lookup_candidate(items, record.get("ref"), record.get("candidate_id"))
    except ValueError as exc:
        reasons.append(_confine_reason(exc, "missing_background_candidate"))
    reasons.extend(_live_clock_reasons(record, candidate, fps))
    if actual is not None:
        reasons.extend(_permission_reasons(record, candidate, actual))
    ordered = list(dict.fromkeys(reasons))
    return {"ready": not ordered, "reasons": ordered}


def _renderer_timing(record):
    fps = float(record["fps"])
    duration_in_frames = record["duration_in_frames"]
    if record["kind"] == "image":
        return 0, duration_in_frames
    trim_before = seconds_to_frame(record["local_start_s"], fps)
    return trim_before, duration_in_frames


def _copy_checked(src, dest, expected):
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(src, dest)
    actual = digest(dest)
    if actual != expected:
        raise ValueError("Frozen background bytes changed while copying: " + dest.name)
    return actual


def _asset_row(record, frozen_ref, copied):
    material = record.get("material_use") if isinstance(record.get("material_use"), dict) else {}
    rights = record.get("candidate_rights") if isinstance(record.get("candidate_rights"), dict) else {}
    return {
        "ref": record["ref"],
        "frozen_ref": frozen_ref,
        "sha256": copied,
        "kind": "background",
        "candidate_id": record["candidate_id"],
        "provider": record.get("provider"),
        "source_id": record.get("source_id"),
        "source_url": record.get("source_url"),
        "rendered_use": material.get("rendered_use"),
        "raw_redistribution": material.get("raw_redistribution"),
        "evidence": list(material.get("evidence") or []),
        "conditions": material.get("conditions"),
        "candidate_signature": record.get("candidate_signature"),
        "candidate_acquisition": record.get("candidate_acquisition"),
        "candidate_rights": {
            "status": rights.get("status"),
            "evidence": list(rights.get("evidence") or []),
            "license_name": rights.get("license_name"),
            "license_url": rights.get("license_url"),
        },
        "suitability": record.get("suitability"),
    }


def freeze_background(root, version_dir, record):
    """Copy the selected bytes into a reserved version's public/media/. Occupied paths stay.

    Preflights destinations. Frozen partial copies remain if a later stage fails.
    """
    if record is None:
        return _empty_freeze()
    validate_background(record)
    base = Path(root)
    _assert_ancestors(base, base)
    version_path = _confine_planned(base, version_dir)
    if not version_path.is_dir() or _is_link_or_junction(Path(version_dir)):
        raise ValueError("freeze_background requires a reserved existing version directory.")
    owned = _owned_name(record["ref"])
    dest = _confine_planned(version_path, version_path / "public" / "media" / owned)
    if dest.exists() or dest.is_symlink() or _is_link_or_junction(dest):
        raise ValueError("Frozen background destination already exists and will not be overwritten: " + owned)
    src = _confine_existing(base, record["ref"])
    if digest(src) != record["sha256"]:
        raise ValueError("Background hash changed before freeze: " + record["ref"])
    copied = _copy_checked(src, dest, record["sha256"])
    trim_before, duration_in_frames = _renderer_timing(record)
    background = {
        "kind": record["kind"],
        "src": "media/" + owned,
        "fit": record["fit"],
        "width": record["width"],
        "height": record["height"],
        "trim_before": trim_before,
        "duration_in_frames": duration_in_frames,
        "muted": True,
    }
    return {
        "background": background,
        "assets": [_asset_row(record, "public/media/" + owned, copied)],
    }
