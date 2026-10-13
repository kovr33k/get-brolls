"""Graphics sound cues, bounded VO excerpts and the three verified CC0 SFX routes.

Public functions are the frozen #57 audio seam. This module does not import graphics.py,
download unless import_sfx_command is called, or place private VO in render props.
"""

from __future__ import annotations

import contextlib
import hashlib
import json
import math
import os
import re
import shutil
import stat
import urllib.parse
from pathlib import Path
from typing import TYPE_CHECKING

from . import http
from .ledger import digest
from .media import run as media_run
from .models import now, require_fetch

if TYPE_CHECKING:
    from typing import TypeGuard

AUDIO_SCHEMA = 1
ID_RE = re.compile(r"[A-Za-z0-9_-]{1,80}$")
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
OWNED_AUDIO_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
_WINDOWS_RESERVED = re.compile(r"^(?:con|prn|aux|nul|com[1-9]|lpt[1-9])$", re.IGNORECASE)
_CONTROL = re.compile(r"[\x00-\x1f\x7f]")
_PROSE_CONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
_ILLEGAL_PATH = re.compile(r'[<>"|?*]')
EFFECT_PREFIXES = ("sounds/", "previews/", "clips/")
VO_PREFIXES = ("sounds/", "previews/", "clips/", "narration/private/audio/")
PREVIEW_PREFIXES = ("previews/",)
USE_STATES = ("permitted", "restricted", "unknown")
VO_KINDS = ("full_recording", "fragment")
AUDIO_SUFFIXES = {".wav", ".wave", ".mp3", ".m4a", ".aac", ".ogg", ".oga", ".flac"}
MAX_TEXT = 8000
MAX_URL = 2000
MAX_EFFECT_BYTES = 8 * 1024 * 1024
MAX_VO_BYTES = 64 * 1024 * 1024
MAX_SFX_BYTES = 8 * 1024 * 1024
MAX_EFFECT_DURATION_S = 30
MAX_VO_DURATION_S = 180
FULL_RECORDING_MAX_BYTES = 512 * 1024 * 1024
FULL_RECORDING_MAX_DURATION_S = 3600
MAX_GAIN = 4
FRAME_ROUNDING = "half_up_nonnegative"
SFX_CHOICES = ("whip", "whoosh", "uiSwitch")
_MIN_VERSION_PATH_PARTS = 2
_USE_RANK = {"permitted": 0, "unknown": 1, "restricted": 2}
_LINK_MSG = "Graphics audio path is a symlink or junction and will not be followed: "

# Individually verified 2026-10-10 CC0 pages. Package MIT does not license these files.
SFX_ROUTES = {
    "whip": {
        "url": "https://remotion.media/whip.wav",
        "terms_url": "https://www.remotion.dev/docs/sfx/whip",
        "license": "CC0",
        "author": "JW_Audio",
        "original_url": "https://freesound.org/s/838766/",
        "filename": "whip.wav",
        "conditions": (
            "CC0. Individual sound terms from remotion.dev/docs/sfx/whip; "
            "not inferred from the @remotion/sfx npm MIT license."
        ),
    },
    "whoosh": {
        "url": "https://remotion.media/whoosh.wav",
        "terms_url": "https://www.remotion.dev/docs/sfx/whoosh",
        "license": "CC0",
        "author": "1bob",
        "original_url": "https://freesound.org/s/831936/",
        "filename": "whoosh.wav",
        "conditions": (
            "CC0. Individual sound terms from remotion.dev/docs/sfx/whoosh; "
            "not inferred from the @remotion/sfx npm MIT license."
        ),
    },
    "uiSwitch": {
        "url": "https://remotion.media/switch.wav",
        "terms_url": "https://www.remotion.dev/docs/sfx/ui-switch",
        "license": "CC0",
        "author": "Kenney",
        "original_url": "https://kenney.nl/",
        "filename": "switch.wav",
        "conditions": (
            "CC0. Individual sound terms from remotion.dev/docs/sfx/ui-switch; "
            "not inferred from the @remotion/sfx npm MIT license."
        ),
    },
}


def seconds_to_frame(seconds, fps):
    """Non-negative half-up: frame = floor(t * fps + 0.5). Error is at most one frame."""
    if not isinstance(seconds, (int, float)) or isinstance(seconds, bool) or not math.isfinite(seconds) or seconds < 0:
        raise ValueError("Timing values must be finite seconds greater than or equal to 0.")
    if not isinstance(fps, (int, float)) or isinstance(fps, bool) or not math.isfinite(fps) or fps <= 0:
        raise ValueError("Profile fps must be a finite number greater than 0.")
    return math.floor(float(seconds) * float(fps) + 0.5)


def _is_int(value) -> TypeGuard[int]:
    return type(value) is int


def _is_number(value) -> TypeGuard[int | float]:
    return type(value) in (int, float) and not isinstance(value, bool) and math.isfinite(value)


def _as_dict(value):
    return value if isinstance(value, dict) else {}


def _bounded_prose(value, limit=MAX_TEXT):
    return isinstance(value, str) and bool(value.strip()) and len(value) <= limit and not _PROSE_CONTROL.search(value)


def _valid_id(value) -> TypeGuard[str]:
    return isinstance(value, str) and bool(ID_RE.fullmatch(value)) and not _WINDOWS_RESERVED.fullmatch(value)


def _sha256(value):
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
    if os.name != "nt":
        return False
    try:
        attrs = getattr(os.lstat(path), "st_file_attributes", 0)
    except OSError:
        return False
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


def relative_audio_ref(value, prefixes):
    if not isinstance(value, str) or not value or _CONTROL.search(value):
        raise ValueError("Graphics audio paths must be relative posix paths.")
    if "\\" in value or value.startswith(("/", "~")) or ":" in value:
        raise ValueError(
            "Graphics audio paths must be relative posix paths without drive letters, colons, ADS streams or backslashes."
        )
    if _ILLEGAL_PATH.search(value):
        raise ValueError("Graphics audio paths must be relative posix paths without Windows reserved characters.")
    path = Path(value)
    if ".." in path.parts or path.is_absolute():
        raise ValueError("Graphics audio paths must be relative posix paths and cannot leave the project tree.")
    if any(_WINDOWS_RESERVED.fullmatch(part.split(".")[0]) for part in path.parts):
        raise ValueError("Graphics audio paths must be relative posix paths without reserved Windows names.")
    if not value.startswith(prefixes):
        raise ValueError("Graphics audio references must stay under " + ", ".join(prefixes) + ".")
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
            raise ValueError("Graphics audio path could not be resolved.") from exc
        if _is_link_or_junction(path) or not _contained(resolved_root, resolved):
            raise ValueError("Graphics audio path resolves outside the project or through a link.")
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
        raise ValueError("Graphics audio path could not be resolved.") from exc
    if not _contained(resolved_root, resolved_parent):
        raise ValueError("Graphics audio path resolves outside the project.")
    try:
        rest = path.relative_to(existing)
    except ValueError as exc:
        raise ValueError("Graphics audio path resolves outside the project.") from exc
    if ".." in rest.parts:
        raise ValueError("Graphics audio path resolves outside the project.")
    planned = resolved_parent.joinpath(*rest.parts)
    if not _contained(resolved_root, planned):
        raise ValueError("Graphics audio path resolves outside the project.")
    return planned


def _confine_existing(root, rel, prefixes):
    relative_audio_ref(rel, prefixes)
    base = Path(root)
    path = base.joinpath(*rel.split("/"))
    _assert_ancestors(base, path)
    try:
        resolved_root = base.resolve()
        resolved = path.resolve()
    except OSError as exc:
        raise ValueError("Graphics audio reference could not be resolved: " + rel) from exc
    if not _contained(resolved_root, resolved):
        raise ValueError("Graphics audio reference resolves outside the project: " + rel)
    if _is_link_or_junction(path) or _is_link_or_junction(resolved):
        raise ValueError("Graphics audio reference is a symlink or junction: " + rel)
    if not resolved.is_file():
        raise ValueError("Graphics audio reference is missing: " + rel)
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
        raise ValueError("Graphics audio needs the project composition profile.")
    fps = profile.get("fps")
    if not _is_number(fps) or fps <= 0:
        raise ValueError("Profile fps must be a finite number greater than 0.")
    rounding = profile.get("frame_rounding")
    if rounding is not None and rounding != FRAME_ROUNDING:
        raise ValueError("Graphics audio requires half_up_nonnegative frame rounding.")
    return float(fps)


def _scene_frames(timing):
    if not isinstance(timing, dict):
        raise ValueError("Graphics audio needs the occurrence timing record.")
    frames = timing.get("duration_in_frames")
    if not _is_int(frames) or frames < 1:
        raise ValueError("Scene duration_in_frames must be a positive integer.")
    basis = timing.get("basis")
    if basis not in ("estimated", "explicit"):
        raise ValueError("Timing basis must be estimated or explicit.")
    return frames, basis


def _optional_url(value, flag):
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError(flag + " must be a public HTTPS URL or null.")
    text = value.strip()
    if not text:
        return None
    if len(text) > MAX_URL or _CONTROL.search(text):
        raise ValueError(flag + " must be a public HTTPS URL without credentials.")
    checked = http.public_url(text)
    if not checked:
        raise ValueError(flag + " must be a public HTTPS URL without credentials.")
    return checked


def _gain(value, flag):
    if not _is_number(value):
        raise ValueError(flag + " must be a finite number.")
    if value < 0 or value > MAX_GAIN:
        raise ValueError(flag + " must be a finite gain between 0 and 4.")
    return float(value) if type(value) is float else value


def _owned_name(effect_id, ref):
    suffix = Path(ref).suffix.lower()
    if suffix == ".wave":
        suffix = ".wav"
    if suffix not in AUDIO_SUFFIXES:
        raise ValueError("Graphics audio file type is not a supported audio container: " + ref)
    name = effect_id + suffix
    if not OWNED_AUDIO_RE.fullmatch(name) or _WINDOWS_RESERVED.fullmatch(Path(name).stem):
        raise ValueError("Frozen audio file name is not a safe owned identity: " + name)
    return name


def _probe_audio(path, *, max_bytes, max_duration_s):
    path = Path(path)
    try:
        size = path.stat().st_size
    except OSError as exc:
        raise ValueError("Graphics audio file could not be read: " + path.name) from exc
    if size <= 0:
        raise ValueError("Graphics audio file is empty: " + path.name)
    if size > max_bytes:
        raise ValueError("Graphics audio file exceeds the bounded size of " + str(max_bytes) + " bytes: " + path.name)
    try:
        payload = json.loads(
            media_run(
                ["ffprobe", "-v", "error", "-show_streams", "-show_format", "-of", "json", str(path)],
                op="graphics_audio_probe",
            )
        )
    except json.JSONDecodeError as exc:
        raise ValueError("ffprobe did not return JSON for " + path.name + ".") from exc
    if not isinstance(payload, dict):
        raise ValueError("ffprobe metadata was malformed for " + path.name + ".")
    streams = [item for item in (payload.get("streams") or []) if isinstance(item, dict)]
    audio = [item for item in streams if item.get("codec_type") == "audio"]
    if not audio:
        raise ValueError("File is not decodable audio: " + path.name)
    duration = _finite_float(audio[0].get("duration"))
    if duration is None:
        duration = _finite_float((_as_dict(payload.get("format"))).get("duration"))
    if duration is None or duration <= 0:
        raise ValueError("Audio duration is missing or not finite: " + path.name)
    if duration > max_duration_s:
        raise ValueError("Audio duration exceeds the bounded limit for " + path.name + ".")
    media_run(
        ["ffmpeg", "-v", "error", "-xerror", "-i", str(path), "-f", "null", "-"],
        op="graphics_audio_decode",
    )
    return {"duration_s": duration, "bytes": size, "codec": audio[0].get("codec_name")}


def _load_manifest(root):
    manifest = Path(root) / "manifest.json"
    if not manifest.is_file() or manifest.is_symlink():
        return {}
    try:
        data = json.loads(manifest.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError) as exc:
        raise ValueError("Project manifest could not be read to bind audio permissions.") from exc
    if not isinstance(data, dict):
        raise ValueError("Project manifest could not be read to bind audio permissions.")
    return data


def _load_items(root):
    items = _load_manifest(root).get("items")
    if items is None:
        return []
    if not isinstance(items, list):
        raise ValueError("Project manifest items could not be read to bind audio permissions.")
    return items


def _load_sounds(root):
    graphics = _load_manifest(root).get("graphics")
    if graphics is None:
        return {}
    if not isinstance(graphics, dict):
        raise ValueError("Project graphics records could not be read to bind audio permissions.")
    sounds = graphics.get("sounds")
    if sounds is None:
        return {}
    if not isinstance(sounds, dict):
        raise ValueError("Invalid graphics.sounds registry. Preserve the project files; history was not reset.")
    return sounds


def _candidate_media_paths(candidate):
    preview = candidate.get("preview") if isinstance(candidate.get("preview"), dict) else {}
    output = candidate.get("output") if isinstance(candidate.get("output"), dict) else {}
    return [
        path
        for path in (output.get("path"), preview.get("contact_sheet_path"), preview.get("poster_path"))
        if isinstance(path, str) and path
    ]


def _lookup_candidate(items, ref, candidate_id=None):
    matches = []
    by_id = None
    for candidate in items or []:
        if not isinstance(candidate, dict):
            continue
        if candidate_id is not None and candidate.get("id") == candidate_id:
            by_id = candidate
        if ref in _candidate_media_paths(candidate):
            matches.append(candidate)
    if candidate_id is not None:
        if by_id is None:
            raise ValueError("Audio candidate_id does not exist in this project: " + candidate_id)
        if ref not in _candidate_media_paths(by_id):
            raise ValueError("Audio ref is not that candidate's recorded output or preview path.")
        return by_id
    if len(matches) > 1:
        raise ValueError("Audio ref matches multiple candidates; pass candidate_id.")
    if len(matches) == 1:
        return matches[0]
    return None


def _candidate_permission_ok(entry, candidate, digest_value):
    if candidate is None:
        return entry.get("rendered_use") in USE_STATES
    output = _as_dict(candidate.get("output"))
    if output.get("path") == entry.get("ref"):
        recorded = output.get("sha256")
        if recorded is not None and recorded != digest_value:
            return False
    rights = _as_dict(candidate.get("rights"))
    if entry.get("rendered_use") != "permitted":
        return True
    if rights.get("status") != "permitted":
        return False
    try:
        require_fetch(candidate)
    except (ValueError, KeyError, TypeError):
        return False
    return True


def _stricter_use(left, right):
    rank_left = _USE_RANK.get(left)
    rank_right = _USE_RANK.get(right)
    if rank_left is None:
        return right if rank_right is not None else left
    if rank_right is None or rank_right < rank_left:
        return left
    return right


def _apply_candidate_permissions(entry, candidate, digest_value):
    if candidate is None:
        return
    if not _candidate_permission_ok(entry, candidate, digest_value):
        raise ValueError(
            "Rendered use cannot be permitted for "
            + entry["ref"]
            + " by pointing at a local file while the bound candidate is restricted, unapproved or changed."
        )
    rights = _as_dict(candidate.get("rights"))
    status = rights.get("status")
    if status in ("restricted", "unknown") and entry.get("rendered_use") == "permitted":
        raise ValueError(
            "Candidate permission for "
            + entry["ref"]
            + " remains "
            + str(status)
            + "; local reuse does not upgrade it."
        )
    if status == "restricted" and entry.get("raw_redistribution") == "permitted":
        raise ValueError("Raw redistribution cannot be permitted for restricted candidate media: " + entry["ref"])


def _apply_registered_permissions(entry, registered, digest_value):
    if registered is None:
        return
    for key in ("source_url", "terms_url", "license"):
        expected = registered.get(key)
        supplied = entry.get(key)
        if supplied is not None and expected is not None and supplied != expected:
            raise ValueError("Imported sound metadata does not match the registered " + key + " for " + entry["ref"])
    if registered.get("sha256") not in (None, digest_value):
        raise ValueError("Imported sound hash does not match the registered asset: " + entry["ref"])
    if entry.get("source_url") is None:
        entry["source_url"] = registered.get("source_url")
    if entry.get("terms_url") is None:
        entry["terms_url"] = registered.get("terms_url")
    if not entry.get("license"):
        entry["license"] = registered.get("license") or entry.get("license")
    if not entry.get("conditions"):
        entry["conditions"] = registered.get("conditions")
    entry["rendered_use"] = _stricter_use(entry.get("rendered_use"), registered.get("rendered_use"))
    entry["raw_redistribution"] = _stricter_use(entry.get("raw_redistribution"), registered.get("raw_redistribution"))


def _bind_effect_permissions(entry, candidate, digest_value, registered):
    """Keep candidate and registered-sound terms; local presence does not grant permission."""
    _apply_candidate_permissions(entry, candidate, digest_value)
    _apply_registered_permissions(entry, registered, digest_value)
    return entry


def _interval_frames(start_s, end_s, fps):
    if end_s <= start_s:
        raise ValueError("Audio interval end must be greater than start.")
    start_frame = seconds_to_frame(start_s, fps)
    end_frame = seconds_to_frame(end_s, fps)
    duration_in_frames = max(1, end_frame - start_frame)
    return start_frame, duration_in_frames


def _within_one_frame(duration_s, duration_in_frames, fps):
    converted = max(seconds_to_frame(duration_s, fps), 1)
    return abs(converted - duration_in_frames) <= 1


def _empty_record(fps, duration_in_frames):
    stored_fps = int(fps) if float(fps).is_integer() else float(fps)
    return {
        "schema_version": AUDIO_SCHEMA,
        "fps": stored_fps,
        "duration_in_frames": duration_in_frames,
        "effects": [],
        "vo": None,
    }


def _validate_effect_permissions(item):
    if item.get("rendered_use") not in USE_STATES or item.get("raw_redistribution") not in USE_STATES:
        raise ValueError(
            "Each sound effect needs rendered_use and raw_redistribution as permitted, restricted or unknown."
        )
    if not _bounded_prose(item.get("license"), 2000) or not _bounded_prose(item.get("conditions")):
        raise ValueError("Each sound effect must keep license and conditions as original text.")
    _optional_url(item.get("source_url"), "source_url")
    _optional_url(item.get("terms_url"), "terms_url")


def _validate_effect_timing(item, fps, duration_in_frames):
    if not _is_int(item.get("start_frame")) or item["start_frame"] < 0:
        raise ValueError("Effect start_frame must be a nonnegative integer.")
    if not _is_number(item.get("source_start_s")) or item["source_start_s"] < 0:
        raise ValueError("Effect source_start_s must be finite seconds greater than or equal to 0.")
    if not _is_number(item.get("duration_s")) or item["duration_s"] <= 0:
        raise ValueError("Effect duration_s must be a finite duration greater than 0.")
    _gain(item.get("gain"), "effect gain")
    start_trim, cue_frames = _interval_frames(item["source_start_s"], item["source_start_s"] + item["duration_s"], fps)
    if item["start_frame"] >= duration_in_frames:
        raise ValueError("Effect start_frame must lie inside the scene.")
    if item["start_frame"] + cue_frames > duration_in_frames:
        raise ValueError("Effect cue extends past the scene duration.")
    if cue_frames < 1:
        raise ValueError("Effect duration_in_frames must be positive.")
    return start_trim, cue_frames


def _validate_effect_struct(item, fps, duration_in_frames, *, require_hash=True):
    if not isinstance(item, dict):
        raise ValueError("Each sound effect must be an object.")
    if not _valid_id(item.get("id")):
        raise ValueError("Each sound effect needs a safe id.")
    relative_audio_ref(item.get("ref"), EFFECT_PREFIXES)
    if require_hash and not _sha256(item.get("sha256")):
        raise ValueError("Each sound effect needs a sha256 hex digest.")
    if item.get("sha256") is not None and not _sha256(item.get("sha256")):
        raise ValueError("Each sound effect sha256 must be a 64-character hex digest.")
    _validate_effect_permissions(item)
    if item.get("candidate_id") is not None and (
        not isinstance(item.get("candidate_id"), str) or not item["candidate_id"].strip()
    ):
        raise ValueError("candidate_id must be a non-empty string when present.")
    return _validate_effect_timing(item, fps, duration_in_frames)


def _validate_vo_struct(vo, fps, duration_in_frames, *, require_hash=True):
    if vo is None:
        return None
    if not isinstance(vo, dict):
        raise ValueError("vo must be null or an object.")
    relative_audio_ref(vo.get("ref"), VO_PREFIXES)
    if require_hash and not _sha256(vo.get("sha256")):
        raise ValueError("VO needs a sha256 hex digest.")
    if vo.get("sha256") is not None and not _sha256(vo.get("sha256")):
        raise ValueError("VO sha256 must be a 64-character hex digest.")
    if vo.get("kind") not in VO_KINDS:
        raise ValueError("VO kind must be full_recording or fragment.")
    if not _is_number(vo.get("source_start_s")) or vo["source_start_s"] < 0:
        raise ValueError("VO source_start_s must be finite seconds greater than or equal to 0.")
    if not _is_number(vo.get("source_end_s")) or vo["source_end_s"] <= vo["source_start_s"]:
        raise ValueError("VO source_end_s must be greater than source_start_s.")
    _gain(vo.get("gain"), "VO gain")
    duration_s = vo["source_end_s"] - vo["source_start_s"]
    if duration_s > MAX_VO_DURATION_S:
        raise ValueError("VO interval exceeds the bounded duration.")
    if not _within_one_frame(duration_s, duration_in_frames, fps):
        raise ValueError("VO interval duration must match the scene length within one frame.")
    return vo


def validate_audio(record):
    """Structural read-free validation. None is a legacy silent version."""
    if record is None:
        return None
    if not isinstance(record, dict):
        raise ValueError("Graphics audio record must be an object or null.")
    if record.get("schema_version") != AUDIO_SCHEMA:
        raise ValueError("Graphics audio schema_version must be 1.")
    fps = record.get("fps")
    if not _is_number(fps) or fps <= 0:
        raise ValueError("Graphics audio fps must be a finite number greater than 0.")
    duration_in_frames = record.get("duration_in_frames")
    if not _is_int(duration_in_frames) or duration_in_frames < 1:
        raise ValueError("Graphics audio duration_in_frames must be a positive integer.")
    effects = record.get("effects")
    if not isinstance(effects, list):
        raise ValueError("Graphics audio effects must be a list.")
    seen_ids = set()
    seen_ref_spellings = {}
    for item in effects:
        _validate_effect_struct(item, float(fps), duration_in_frames)
        key = item["id"].casefold()
        if key in seen_ids:
            raise ValueError("Sound effect ids cannot repeat: " + item["id"])
        seen_ids.add(key)
        ref_key = item["ref"].casefold()
        previous = seen_ref_spellings.get(ref_key)
        if previous is not None and previous != item["ref"]:
            raise ValueError("Sound effect references collide case-insensitively: " + previous + " and " + item["ref"])
        seen_ref_spellings[ref_key] = item["ref"]
    _validate_vo_struct(record.get("vo"), float(fps), duration_in_frames)
    return record


def _registered_for_ref(sounds, ref):
    for item in sounds.values():
        if isinstance(item, dict) and item.get("ref") == ref:
            return item
    return None


def _normalize_effect(root, item, scene, *, items, sounds):
    fps, duration_in_frames = scene
    start_trim, cue_frames = _validate_effect_struct(item, fps, duration_in_frames, require_hash=False)
    path = _confine_existing(root, item["ref"], EFFECT_PREFIXES)
    info = _probe_audio(path, max_bytes=MAX_EFFECT_BYTES, max_duration_s=MAX_EFFECT_DURATION_S)
    actual = digest(path)
    if item.get("sha256") not in (None, actual):
        raise ValueError("Sound effect sha256 does not match the confined file: " + item["ref"])
    source_end = item["source_start_s"] + item["duration_s"]
    if source_end - info["duration_s"] > (1.0 / fps):
        raise ValueError("Effect trim extends past the decoded audio duration: " + item["ref"])
    if item["source_start_s"] >= info["duration_s"]:
        raise ValueError("Effect source_start_s is past the decoded audio duration: " + item["ref"])
    candidate_id = item.get("candidate_id")
    if isinstance(candidate_id, str):
        candidate_id = candidate_id.strip() or None
    candidate = _lookup_candidate(items, item["ref"], candidate_id)
    source_url = _optional_url(item.get("source_url"), "source_url")
    terms_url = _optional_url(item.get("terms_url"), "terms_url")
    entry = {
        "id": item["id"],
        "ref": item["ref"],
        "sha256": actual,
        "source_url": source_url,
        "terms_url": terms_url,
        "license": item["license"],
        "conditions": item["conditions"],
        "rendered_use": item["rendered_use"],
        "raw_redistribution": item["raw_redistribution"],
        "start_frame": item["start_frame"],
        "source_start_s": float(item["source_start_s"])
        if type(item["source_start_s"]) is float
        else item["source_start_s"],
        "duration_s": float(item["duration_s"]) if type(item["duration_s"]) is float else item["duration_s"],
        "gain": _gain(item["gain"], "effect gain"),
    }
    if candidate_id:
        entry["candidate_id"] = candidate_id
    registered = _registered_for_ref(sounds, item["ref"])
    _bind_effect_permissions(entry, candidate, actual, registered)
    entry["_trim_before_frame"] = start_trim
    entry["_duration_in_frames"] = cue_frames
    return entry


def _normalize_vo(root, vo, scene, timing):
    if vo is None:
        return None
    fps, duration_in_frames = scene
    basis = timing.get("basis")
    _validate_vo_struct(vo, fps, duration_in_frames, require_hash=False)
    path = _confine_existing(root, vo["ref"], VO_PREFIXES)
    info = _probe_audio(
        path,
        max_bytes=MAX_VO_BYTES if vo["kind"] == "fragment" else FULL_RECORDING_MAX_BYTES,
        max_duration_s=FULL_RECORDING_MAX_DURATION_S,
    )
    actual = digest(path)
    if vo.get("sha256") not in (None, actual):
        raise ValueError("VO sha256 does not match the confined file: " + vo["ref"])
    if vo["source_end_s"] - info["duration_s"] > (1.0 / fps):
        raise ValueError("VO interval extends past the decoded audio duration.")
    if vo["kind"] == "full_recording":
        if basis != "explicit":
            raise ValueError(
                "Full-recording VO requires explicit narration times; estimated drafts stay labeled and not deliverable."
            )
        start_s = timing.get("start_s")
        end_s = timing.get("end_s")
        if not _is_number(start_s) or not _is_number(end_s):
            raise ValueError("Full-recording VO source times must equal explicit narration start_s and end_s.")
        if vo["source_start_s"] != start_s or vo["source_end_s"] != end_s:
            raise ValueError("Full-recording VO source times must equal the original narration clock.")
    elif vo["source_start_s"] < 0:
        raise ValueError("Fragment VO times are fragment-local and cannot be negative.")
    return {
        "ref": vo["ref"],
        "sha256": actual,
        "kind": vo["kind"],
        "source_start_s": float(vo["source_start_s"]) if type(vo["source_start_s"]) is float else vo["source_start_s"],
        "source_end_s": float(vo["source_end_s"]) if type(vo["source_end_s"]) is float else vo["source_end_s"],
        "gain": _gain(vo["gain"], "VO gain"),
    }


def _remember_effect_identity(entry, root, seen_ids, seen_files):
    key = entry["id"].casefold()
    if key in seen_ids:
        raise ValueError("Sound effect ids cannot repeat: " + entry["id"])
    seen_ids.add(key)
    path = _confine_existing(root, entry["ref"], EFFECT_PREFIXES)
    file_key = os.path.normcase(str(path))
    previous = seen_files.get(file_key)
    if previous is not None and previous != entry["ref"]:
        raise ValueError("Sound effect references collide case-insensitively: " + previous + " and " + entry["ref"])
    seen_files[file_key] = entry["ref"]


def _normalize_effects_list(root, effects_in, scene, *, items, sounds):
    seen_ids = set()
    seen_files = {}
    effects = []
    for item in effects_in:
        entry = _normalize_effect(root, item, scene, items=items, sounds=sounds)
        _remember_effect_identity(entry, root, seen_ids, seen_files)
        effects.append(entry)
    return effects


def normalize_audio(root, payload, profile, timing):
    """Validate and normalize sound assets and VO clocks. No download or writes."""
    fps = _profile_fps(profile)
    duration_in_frames = _scene_frames(timing)[0]
    if payload is None:
        return _empty_record(fps, duration_in_frames)
    if not isinstance(payload, dict):
        raise ValueError("Graphics audio payload must be a JSON object.")
    if payload.get("schema_version") not in (None, AUDIO_SCHEMA):
        raise ValueError("Graphics audio schema_version must be 1.")
    if payload.get("fps") is not None and float(payload["fps"]) != fps:
        raise ValueError("Audio fps must match the project composition profile.")
    if payload.get("duration_in_frames") is not None and payload["duration_in_frames"] != duration_in_frames:
        raise ValueError("Audio duration_in_frames must match the scene timing.")
    effects_in = payload.get("effects")
    if effects_in is None:
        effects_in = []
    if not isinstance(effects_in, list):
        raise ValueError("effects must be a list.")
    root = Path(root)
    _assert_ancestors(root, root)
    items = _load_items(root)
    sounds = _load_sounds(root)
    scene = (fps, duration_in_frames)
    effects = _normalize_effects_list(root, effects_in, scene, items=items, sounds=sounds)
    vo = _normalize_vo(root, payload.get("vo"), scene, timing)
    record = _empty_record(fps, duration_in_frames)
    record["effects"] = [{k: v for k, v in item.items() if not k.startswith("_")} for item in effects]
    record["vo"] = vo
    validate_audio(record)
    return record


def _effect_cue_math(effect, fps, duration_in_frames):
    start_trim, cue_frames = _interval_frames(
        effect["source_start_s"], effect["source_start_s"] + effect["duration_s"], fps
    )
    if effect["start_frame"] + cue_frames > duration_in_frames:
        raise ValueError("Effect cue extends past the scene duration.")
    return start_trim, cue_frames


def _registry_readiness_flags(effect, registered, actual):
    hash_block = False
    perm_block = False
    if registered is None:
        return hash_block, perm_block
    if registered.get("sha256") not in (None, actual):
        hash_block = True
    for key in ("source_url", "terms_url", "license", "conditions"):
        expected = registered.get(key)
        saved = effect.get(key)
        if expected not in (None, "") and saved not in (None, "") and expected != saved:
            perm_block = True
            break
    current = registered.get("rendered_use")
    saved_use = effect.get("rendered_use")
    if current in ("restricted", "unknown") or (
        current in USE_STATES and saved_use in USE_STATES and current != saved_use
    ):
        perm_block = True
    return hash_block, perm_block


def _confine_reason(exc, missing_code):
    message = str(exc)
    if "symlink or junction" in message.lower():
        return message
    return missing_code


def _effect_file_reasons(effect, path, actual, fps):
    reasons = []
    if actual != effect.get("sha256"):
        reasons.append("changed_audio_hash")
    try:
        info = _probe_audio(path, max_bytes=MAX_EFFECT_BYTES, max_duration_s=MAX_EFFECT_DURATION_S)
        source_end = effect["source_start_s"] + effect["duration_s"]
        if source_end - info["duration_s"] > (1.0 / fps):
            reasons.append("audio_trim_out_of_range")
    except ValueError:
        reasons.append("undecodable_audio")
    return reasons


def _effect_permission_reasons(effect, actual, items, sounds):
    reasons = []
    candidate = None
    try:
        candidate = _lookup_candidate(items, effect.get("ref"), effect.get("candidate_id"))
    except ValueError:
        reasons.append("unresolved_audio_permission")
    if effect.get("rendered_use") != "permitted" or (
        candidate is not None and not _candidate_permission_ok(effect, candidate, actual)
    ):
        reasons.append("unresolved_audio_permission")
    registered = _registered_for_ref(sounds, effect.get("ref"))
    hash_block, perm_block = _registry_readiness_flags(effect, registered, actual)
    if hash_block:
        reasons.append("changed_audio_hash")
    if perm_block:
        reasons.append("unresolved_audio_permission")
    return reasons


def _effect_readiness_reasons(root, effect, scene, *, items, sounds):
    fps, duration_in_frames = scene
    try:
        path = _confine_existing(root, effect.get("ref"), EFFECT_PREFIXES)
    except ValueError as exc:
        return [_confine_reason(exc, "missing_audio_file")]
    try:
        actual = digest(path)
    except OSError:
        return ["missing_audio_file"]
    reasons = _effect_file_reasons(effect, path, actual, fps)
    reasons.extend(_effect_permission_reasons(effect, actual, items, sounds))
    try:
        _effect_cue_math(effect, fps, duration_in_frames)
    except ValueError:
        reasons.append("audio_cue_out_of_range")
    return reasons


def _vo_readiness_reasons(root, vo):
    try:
        path = _confine_existing(root, vo.get("ref"), VO_PREFIXES)
        actual = digest(path)
    except ValueError as exc:
        return [_confine_reason(exc, "missing_vo_file")]
    except OSError:
        return ["missing_vo_file"]
    reasons = []
    if actual != vo.get("sha256"):
        reasons.append("changed_vo_hash")
    try:
        _probe_audio(
            path,
            max_bytes=MAX_VO_BYTES if vo.get("kind") == "fragment" else FULL_RECORDING_MAX_BYTES,
            max_duration_s=FULL_RECORDING_MAX_DURATION_S,
        )
    except ValueError:
        reasons.append("undecodable_vo")
    return reasons


def audio_readiness(root, record):
    """Read-only hash and permission recheck. None does not invalidate a silent legacy version."""
    if record is None:
        return {"ready": True, "reasons": []}
    try:
        validate_audio(record)
    except ValueError:
        return {"ready": False, "reasons": ["invalid_audio_record"]}
    fps = float(record["fps"])
    duration_in_frames = record["duration_in_frames"]
    try:
        root = Path(root)
        _assert_ancestors(root, root)
        items = _load_items(root)
        sounds = _load_sounds(root)
    except ValueError as exc:
        return {"ready": False, "reasons": [_confine_reason(exc, "unresolved_audio_permission")]}
    reasons = []
    for effect in record.get("effects") or []:
        reasons.extend(_effect_readiness_reasons(root, effect, (fps, duration_in_frames), items=items, sounds=sounds))
    vo = record.get("vo")
    if vo is not None:
        reasons.extend(_vo_readiness_reasons(root, vo))
    ordered = list(dict.fromkeys(reasons))
    return {"ready": not ordered, "reasons": ordered}


def _version_names(root, version_dir):
    base = Path(root)
    planned = _confine_planned(base, version_dir)
    if not planned.is_dir() or _is_link_or_junction(Path(version_dir)):
        raise ValueError("freeze_audio requires a reserved existing version directory.")
    try:
        rel = planned.relative_to(base.resolve())
    except ValueError as exc:
        raise ValueError("Version directory is outside the project.") from exc
    parts = rel.parts
    scene = parts[-_MIN_VERSION_PATH_PARTS] if len(parts) >= _MIN_VERSION_PATH_PARTS else "scene"
    version = parts[-1] if parts else "v1"
    if not _valid_id(scene) or not isinstance(version, str) or not re.fullmatch(r"v[1-9][0-9]*", version):
        scene = "scene"
        version = "v1"
        ident = hashlib.sha256(str(planned).encode("utf-8")).hexdigest()[:12]
        return scene, version, ident
    return scene, version, None


def _copy_checked(src, dest, expected):
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(src, dest)
    actual = digest(dest)
    if actual != expected:
        raise ValueError("Frozen audio bytes changed while copying: " + dest.name)
    return actual


def _extract_vo_excerpt(src, dest, start_s, end_s, fps):
    if not _is_number(start_s) or not _is_number(end_s) or end_s <= start_s:
        raise ValueError("VO excerpt clocks must be a finite interval.")
    duration = end_s - start_s
    dest = Path(dest)
    tmp = dest.with_name(dest.name + ".part")
    if tmp.exists() or tmp.is_symlink() or _is_link_or_junction(tmp):
        raise ValueError("VO excerpt staging path already exists and will not be overwritten.")
    if dest.exists() or dest.is_symlink() or _is_link_or_junction(dest):
        raise ValueError("VO preview path already exists and will not be overwritten.")
    dest.parent.mkdir(parents=True, exist_ok=True)
    published = False
    try:
        media_run(
            [
                "ffmpeg",
                "-v",
                "error",
                "-y",
                "-i",
                str(src),
                "-ss",
                str(start_s),
                "-t",
                str(duration),
                "-vn",
                "-c:a",
                "pcm_s16le",
                "-f",
                "wav",
                str(tmp),
            ],
            op="graphics_vo_excerpt",
        )
        info = _probe_audio(tmp, max_bytes=MAX_VO_BYTES, max_duration_s=MAX_VO_DURATION_S)
        if abs(info["duration_s"] - duration) > (1.0 / fps):
            raise ValueError("VO excerpt duration does not match the requested interval.")
        actual = digest(tmp)
        if dest.exists() or dest.is_symlink():
            raise ValueError("VO preview path already exists and will not be overwritten.")
        tmp.replace(dest)
        published = True
        return actual, info["duration_s"]
    finally:
        if not published:
            with contextlib.suppress(OSError):
                tmp.unlink(missing_ok=True)


def _plan_frozen_effects(base, version_path, public_audio, record):
    planned = []
    seen_owned = {}
    for effect in record.get("effects") or []:
        owned = _owned_name(effect["id"], effect["ref"])
        key = os.path.normcase(owned)
        previous = seen_owned.get(key)
        if previous is not None:
            raise ValueError("Frozen audio filenames collide: " + previous + " and " + owned)
        seen_owned[key] = owned
        src = _confine_existing(base, effect["ref"], EFFECT_PREFIXES)
        dest = _confine_planned(version_path, public_audio / owned)
        planned.append((effect, src, dest, "public/audio/" + owned, "audio/" + owned, owned))
    return planned


def _preflight_freeze(base, version_path, planned, vo):
    for effect, src, dest, _frozen_ref, _src_rel, owned in planned:
        if dest.exists() or dest.is_symlink():
            raise ValueError("Frozen audio destination already exists and will not be overwritten: " + owned)
        _assert_ancestors(version_path, dest.parent)
        if digest(src) != effect["sha256"]:
            raise ValueError("Sound effect hash changed before freeze: " + effect["ref"])
    if vo is None:
        return None, None, None
    vo_src = _confine_existing(base, vo["ref"], VO_PREFIXES)
    scene, version, ident = _version_names(base, version_path)
    stem = f"graphics-{scene}-{version}-vo.wav" if ident is None else f"graphics-vo-{ident}.wav"
    vo_rel = "previews/" + stem
    relative_audio_ref(vo_rel, PREVIEW_PREFIXES)
    vo_dest = _confine_planned(base, base / vo_rel)
    if vo_dest.exists() or vo_dest.is_symlink():
        raise ValueError("VO preview path already exists and will not be overwritten: " + vo_rel)
    if digest(vo_src) != vo["sha256"]:
        raise ValueError("VO hash changed before freeze: " + vo["ref"])
    return vo_src, vo_dest, vo_rel


def _publish_effect_cues(planned, fps, duration_in_frames):
    assets = []
    sound_cues = []
    for effect, src, dest, frozen_ref, src_rel, _owned in planned:
        copied = _copy_checked(src, dest, effect["sha256"])
        trim_before, cue_frames = _effect_cue_math(effect, fps, duration_in_frames)
        sound_cues.append(
            {
                "id": effect["id"],
                "src": src_rel,
                "start_frame": effect["start_frame"],
                "trim_before_frame": trim_before,
                "duration_in_frames": cue_frames,
                "gain": effect["gain"],
            }
        )
        assets.append(
            {
                "id": effect["id"],
                "kind": "effect",
                "ref": effect["ref"],
                "frozen_ref": frozen_ref,
                "sha256": copied,
                "source_url": effect.get("source_url"),
                "terms_url": effect.get("terms_url"),
                "license": effect.get("license"),
                "conditions": effect.get("conditions"),
                "rendered_use": effect.get("rendered_use"),
                "raw_redistribution": effect.get("raw_redistribution"),
            }
        )
    return sound_cues, assets


def freeze_audio(root, version_dir, record):
    """Copy effects into version public/audio and a bounded VO excerpt under previews/.

    Preflights destinations. Frozen partial copies and history stay if a later stage fails.
    """
    if record is None:
        return {"sound_cues": [], "vo_preview": None, "assets": []}
    validate_audio(record)
    fps = float(record["fps"])
    duration_in_frames = record["duration_in_frames"]
    base = Path(root)
    _assert_ancestors(base, base)
    version_path = _confine_planned(base, version_dir)
    if not version_path.is_dir():
        raise ValueError("freeze_audio requires a reserved existing version directory.")
    public_audio = _confine_planned(version_path, version_path / "public" / "audio")
    vo = record.get("vo")
    planned = _plan_frozen_effects(base, version_path, public_audio, record)
    vo_src, vo_dest, vo_rel = _preflight_freeze(base, version_path, planned, vo)
    sound_cues, assets = _publish_effect_cues(planned, fps, duration_in_frames)
    vo_preview = None
    if vo is not None:
        if vo_src is None or vo_dest is None or vo_rel is None:
            raise ValueError("VO preview path could not be planned.")
        excerpt_hash, excerpt_duration = _extract_vo_excerpt(
            vo_src, vo_dest, vo["source_start_s"], vo["source_end_s"], fps
        )
        vo_preview = {
            "ref": vo_rel,
            "sha256": excerpt_hash,
            "source_ref": vo["ref"],
            "source_sha256": vo["sha256"],
            "source_start_s": vo["source_start_s"],
            "source_end_s": vo["source_end_s"],
            "duration_s": excerpt_duration,
            "gain": vo["gain"],
            "kind": vo["kind"],
        }
    return {"sound_cues": sound_cues, "vo_preview": vo_preview, "assets": assets}


def _graphics_section(ledger):
    graphics = ledger.data.get("graphics")
    if not isinstance(graphics, dict):
        raise ValueError(
            "Graphics records are not initialized. Run graphics-assign before graphics-sound-import; "
            "the sounds registry was not created."
        )
    return graphics


def _sound_registry(graphics):
    sounds = graphics.get("sounds")
    if sounds is None:
        return {}
    if not isinstance(sounds, dict):
        raise ValueError("Invalid graphics.sounds registry. Preserve the project files; history was not reset.")
    return sounds


def _asset_intact(root, record):
    if not isinstance(record, dict):
        return False
    ref = record.get("ref")
    expected = record.get("sha256")
    if not isinstance(ref, str) or not _sha256(expected):
        return False
    try:
        path = _confine_existing(root, ref, EFFECT_PREFIXES)
    except ValueError:
        return False
    try:
        return digest(path) == expected
    except OSError:
        return False


def _find_reusable(sounds, root, sfx, asset_id):
    exact = sounds.get(asset_id)
    if (
        isinstance(exact, dict)
        and exact.get("sfx") == sfx
        and _asset_intact(root, exact)
        and exact.get("source_url") == SFX_ROUTES[sfx]["url"]
    ):
        return exact, True
    if isinstance(exact, dict) and exact.get("sfx") == sfx and _asset_intact(root, exact):
        raise ValueError("Registered sound asset " + asset_id + " does not match the pinned " + sfx + " source URL.")
    if isinstance(exact, dict) and exact.get("sfx") != sfx:
        raise ValueError("Sound asset id already registered for a different effect: " + asset_id)
    if isinstance(exact, dict) and not _asset_intact(root, exact):
        raise ValueError(
            "Registered sound asset "
            + asset_id
            + " is missing or its hash changed; the existing file was not overwritten."
        )
    for record in sounds.values():
        if (
            isinstance(record, dict)
            and record.get("sfx") == sfx
            and _asset_intact(root, record)
            and record.get("source_url") == SFX_ROUTES[sfx]["url"]
        ):
            return record, False
    return None, False


def _registered_sound_record(asset_id, sfx, dest_rel, info, meta):
    return {
        "id": asset_id,
        "sfx": sfx,
        "ref": dest_rel,
        "sha256": info["sha256"],
        "source_url": meta.get("source_url"),
        "terms_url": meta.get("terms_url"),
        "license": meta.get("license"),
        "author": meta.get("author"),
        "original_url": meta.get("original_url"),
        "conditions": meta.get("conditions"),
        "rendered_use": meta.get("rendered_use"),
        "raw_redistribution": meta.get("raw_redistribution"),
        "bytes": info["bytes"],
        "duration_s": info["duration_s"],
        "imported_at": now(),
    }


def _reuse_metadata(existing, route):
    return {
        "source_url": existing.get("source_url") or route["url"],
        "terms_url": existing.get("terms_url") or route["terms_url"],
        "license": existing.get("license") or route["license"],
        "author": existing.get("author") or route["author"],
        "original_url": existing.get("original_url") or route["original_url"],
        "conditions": existing.get("conditions") or route["conditions"],
        "rendered_use": _stricter_use(existing.get("rendered_use"), "permitted"),
        "raw_redistribution": _stricter_use(existing.get("raw_redistribution"), "permitted"),
    }


def _route_metadata(route):
    return {
        "source_url": route["url"],
        "terms_url": route["terms_url"],
        "license": route["license"],
        "author": route["author"],
        "original_url": route["original_url"],
        "conditions": route["conditions"],
        "rendered_use": "permitted",
        "raw_redistribution": "permitted",
    }


def _commit_sound(graphics, sounds, asset_id, record, ledger):
    updated = dict(sounds)
    updated[asset_id] = record
    graphics["sounds"] = updated
    ledger.save("graphics-sound-import")
    return record


def _copy_reused_sound(root, existing, dest, asset_id):
    sfx = existing["sfx"]
    dest_rel = "sounds/" + asset_id + ".wav"
    src = _confine_existing(root, existing["ref"], EFFECT_PREFIXES)
    dest.parent.mkdir(parents=True, exist_ok=True)
    actual = _copy_checked(src, dest, existing["sha256"])
    info = _probe_audio(dest, max_bytes=MAX_SFX_BYTES, max_duration_s=MAX_EFFECT_DURATION_S)
    info["sha256"] = actual
    return _registered_sound_record(asset_id, sfx, dest_rel, info, _reuse_metadata(existing, SFX_ROUTES[sfx]))


def _download_pinned_sound(fetch, dest, root, asset_id, sfx):
    route = SFX_ROUTES[sfx]
    dest_rel = "sounds/" + asset_id + ".wav"
    url = route["url"]
    parsed = urllib.parse.urlsplit(url)
    if parsed.scheme != "https" or parsed.hostname != "remotion.media":
        raise ValueError("SFX download URL is not the pinned remotion.media host.")
    if not http.public_url(url):
        raise ValueError("SFX download URL must be public HTTPS without credentials.")
    dest.parent.mkdir(parents=True, exist_ok=True)
    fetch(url, dest, max_bytes=MAX_SFX_BYTES)
    if _is_link_or_junction(dest) or not dest.is_file():
        raise ValueError("Downloaded sound is not a regular confined file.")
    if not _contained(root, dest.resolve()):
        raise ValueError("Downloaded sound resolved outside the project.")
    info = _probe_audio(dest, max_bytes=MAX_SFX_BYTES, max_duration_s=MAX_EFFECT_DURATION_S)
    info["sha256"] = digest(dest)
    return _registered_sound_record(asset_id, sfx, dest_rel, info, _route_metadata(route))


def import_sfx_command(ledger, args, *, downloader=None):
    """Explicit network command: reuse an intact registered CC0 asset or download the pinned URL."""
    sfx = getattr(args, "sfx", None)
    asset_id = getattr(args, "asset", None)
    if sfx not in SFX_ROUTES:
        raise ValueError("graphics-sound-import --sfx must be one of whip, whoosh, uiSwitch.")
    if not _valid_id(asset_id):
        raise ValueError("graphics-sound-import --asset must be a safe identity [A-Za-z0-9_-]{1,80}.")
    root = Path(ledger.root)
    _assert_ancestors(root, root)
    graphics = _graphics_section(ledger)
    sounds = _sound_registry(graphics)
    dest_rel = "sounds/" + asset_id + ".wav"
    relative_audio_ref(dest_rel, EFFECT_PREFIXES)
    dest = _confine_planned(root, root / dest_rel)
    existing, exact_id = _find_reusable(sounds, root, sfx, asset_id)
    if existing is not None and exact_id:
        return {"reused": True, "sound": dict(existing), "downloaded": False}
    if dest.exists() or dest.is_symlink():
        raise ValueError(
            "Sound destination already exists and will not be overwritten: "
            + dest_rel
            + ". Reuse the registered asset or choose another --asset id."
        )
    _assert_ancestors(root, dest.parent)
    fetch = downloader or http.download
    created = []
    try:
        if existing is not None and not exact_id:
            created.append(dest)
            record = _copy_reused_sound(root, existing, dest, asset_id)
            _commit_sound(graphics, sounds, asset_id, record, ledger)
            return {"reused": True, "sound": record, "downloaded": False}
        created.append(dest)
        record = _download_pinned_sound(fetch, dest, root, asset_id, sfx)
        _commit_sound(graphics, sounds, asset_id, record, ledger)
        return {"reused": False, "sound": record, "downloaded": True}
    except (OSError, shutil.Error, http.ProviderError, ValueError, TypeError, KeyError):
        for path in reversed(created):
            with contextlib.suppress(OSError):
                Path(path).unlink(missing_ok=True)
        raise
