"""Optional Remotion graphics: assignments, style history, local render, Storyboard cards.

Graphics are explicit project records, never discovered candidates. Ordinary collection
does not import this module on the search happy path beyond validate/status reads.
"""

from __future__ import annotations

import copy
import hashlib
import html
import json
import math
import os
import re
import shutil
import stat
import subprocess
import sys
import uuid
from contextlib import suppress
from pathlib import Path
from typing import TypeGuard

from .ledger import digest
from .media import run as media_run
from .models import now, require_fetch
from .models import signature as candidate_signature

SKILL_ROOT = Path(__file__).resolve().parents[2]
PACKAGE_ROOT = SKILL_ROOT / "scripts" / "graphics"
WORKER = PACKAGE_ROOT / "render.mjs"
TEMPLATE_DIR = PACKAGE_ROOT / "src"
TEMPLATE_FILES = ("index.jsx", "Root.jsx", "NumericStat.jsx")
AUDIO_TEMPLATE_FILES = (*TEMPLATE_FILES, "GraphicsAudio.jsx")
BACKGROUND_TEMPLATE = "GraphicsBackground.jsx"
BACKGROUND_TEMPLATE_FILES = (*AUDIO_TEMPLATE_FILES, BACKGROUND_TEMPLATE)
MAP_TEMPLATE_FILES = (
    "index.jsx",
    "Root.jsx",
    "MapScene.jsx",
    "GraphicsAudio.jsx",
    "GraphicsBackground.jsx",
    "LocalFonts.jsx",
)
CUSTOM_TEMPLATE_FILES = (
    "index.jsx",
    "Root.jsx",
    "CustomScene.jsx",
    "AuthorScene.jsx",
    "GraphicsAudio.jsx",
    "GraphicsBackground.jsx",
    "LocalFonts.jsx",
)

GRAPHICS_SCHEMA = 1
ID_RE = re.compile(r"[A-Za-z0-9_-]{1,80}$")
VERSION_RE = re.compile(r"^v([1-9][0-9]*)$")
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_WINDOWS_RESERVED = re.compile(r"^(?:con|prn|aux|nul|com[1-9]|lpt[1-9])$", re.IGNORECASE)
_CONTROL = re.compile(r"[\x00-\x1f\x7f]")
_PROSE_CONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
_ILLEGAL_PATH = re.compile(r'[<>"|?*]')
ARTIFACT_PREFIXES = ("previews/", "clips/")
INPUT_PREFIXES = ("previews/", "clips/", "graphics-data/")
JSON_FILE_LIMIT = 2_000_000
DEFAULT_WIDTH = 1920
DEFAULT_HEIGHT = 1080
DEFAULT_FPS = 30
FRAME_ROUNDING = "half_up_nonnegative"
PIXEL_FORMAT = "yuv420p"
COLOR_SPACE = "bt709"
IMAGE_FORMAT = "png"
PINNED = {
    "remotion": "4.0.534",
    "@remotion/renderer": "4.0.534",
    "@remotion/bundler": "4.0.534",
    "react": "19.3.0",
    "react-dom": "19.3.0",
    "@fontsource/ibm-plex-sans": "5.3.0",
}
FONT_FILES = (
    "ibm-plex-sans-latin-400-normal.woff",
    "ibm-plex-sans-latin-700-normal.woff",
)
TEMPLATES = {"numeric-stat": "NumericStat", "timeline": "Timeline", "map": "MapScene", "custom": "CustomScene"}
TIMELINE_TEMPLATE_FILES = (
    "index.jsx",
    "Root.jsx",
    "Timeline.jsx",
    "GraphicsAudio.jsx",
    "GraphicsBackground.jsx",
    "LocalFonts.jsx",
)
ASSIGN_CLAIM_STATUSES = ("synthetic", "unverified_scenario")
CLAIM_STATUSES = ("synthetic", "unverified_scenario", "sourced")
SOURCED_CLAIM_NOTE = "Sourced from recorded evidence for this occurrence. Original narration is unchanged."
KEEP_SCENARIO_NOTE = "Editor kept the original scenario; researched values are context, not proof the narration agrees."
EFFECTS_STREAM_COUNT = 2
MAX_TEXT = 8000
DIAGNOSTIC_LIMIT = 4000
RENDER_TIMEOUT_S = 180
WORKER_ENV = "GB_GRAPHICS_WORKER"
BROWSER_PREPARE_ENV = "GB_GRAPHICS_PREPARE_BROWSER"
FROZEN_REFS_PREFIX = "inputs/refs/"
ASSIGNMENT_FIELDS = (
    "template",
    "composition",
    "chapter_id",
    "chapter_context",
    "purpose",
    "narration",
    "style_revision",
    "timing",
    "anchors",
    "questions",
    "proposed_scenes",
    "asset_refs",
    "evidence_refs",
    "material_use",
    "props",
    "facts",
    "audio",
    "background",
    "alignment",
    "timeline",
    "scene_content",
)
ALIGNMENT_IDENTITY_BLOCKERS = (
    "stale_recording",
    "stale_analysis",
    "stale_transcript",
    "stale_scenario",
    "stale_profile",
    "stale_correction",
    "changed_result_artifact",
    "missing_result_artifact",
    "changed_recording_bytes",
    "missing_recording",
    "incomplete_transcript",
)
RENDERED_USE = ("permitted", "restricted", "unknown")
RAW_REDISTRIBUTION = ("permitted", "restricted", "unknown")
MATERIAL_USE_REQUIRED = ("ref", "rendered_use", "raw_redistribution", "evidence", "conditions", "sha256")

PRESERVE = "Invalid graphics records. Preserve the project files and restore a valid copy; history was not reset."

DOCUMENTARY_PROPOSAL = {
    "family": "documentary",
    "approved": False,
    "user_note": "Пока без референса. Хочу посмотреть на предложенный документальный стиль",
    "proposal": {
        "palette": "dark ink and paper, restrained amber accent",
        "type": "large tabular numerals with editorial labels",
        "motion": "calm sequential reveals",
        "separation": "unlike measures, units and dates stay on distinct rows",
        "status": "proposed draft, not approved visual direction",
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


def _unique(items):
    return list(dict.fromkeys(items))


def _bounded_text(value, limit=MAX_TEXT):
    return isinstance(value, str) and bool(value.strip()) and len(value) <= limit and not _CONTROL.search(value)


def _bounded_prose(value, limit=MAX_TEXT):
    return isinstance(value, str) and bool(value.strip()) and len(value) <= limit and not _PROSE_CONTROL.search(value)


def _original_prose(value, flag, limit=MAX_TEXT):
    if not _bounded_prose(value, limit):
        raise ValueError(f"{flag} must keep the original text, including harmless line breaks.")
    return value


def _valid_id(value):
    return isinstance(value, str) and bool(ID_RE.fullmatch(value)) and not _WINDOWS_RESERVED.fullmatch(value)


def _sha256(value):
    return isinstance(value, str) and bool(SHA256_RE.fullmatch(value))


def _payload_hash(payload):
    encoded = json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _esc(value):
    return html.escape("" if value is None else str(value))


def _contained(root, candidate):
    root_s = os.path.normcase(str(Path(root).resolve())).rstrip("\\/")
    cand_s = os.path.normcase(str(Path(candidate).resolve()))
    return cand_s == root_s or cand_s.startswith(root_s + os.sep)


def relative_artifact(value, prefixes=ARTIFACT_PREFIXES):
    if not isinstance(value, str) or not value or _CONTROL.search(value):
        raise ValueError("Graphics paths must be relative posix paths.")
    if "\\" in value or value.startswith(("/", "~")) or ":" in value:
        raise ValueError(
            "Graphics paths must be relative posix paths without drive letters, colons, ADS streams or backslashes."
        )
    if _ILLEGAL_PATH.search(value):
        raise ValueError("Graphics paths must be relative posix paths without Windows reserved characters.")
    path = Path(value)
    if ".." in path.parts or path.is_absolute():
        raise ValueError("Graphics paths must be relative posix paths and cannot leave the project tree.")
    if any(_WINDOWS_RESERVED.fullmatch(part.split(".")[0]) for part in path.parts):
        raise ValueError("Graphics paths must be relative posix paths without reserved Windows names.")
    if not value.startswith(prefixes):
        if prefixes == ARTIFACT_PREFIXES:
            raise ValueError("Graphics preview artifacts must use previews/ or clips/ as a relative posix path.")
        raise ValueError("Graphics paths must use " + " or ".join(prefixes) + " as a relative posix path.")
    return value


def _confine_planned(root, path):
    base = Path(root).resolve()
    path = Path(path)
    if path.exists():
        try:
            resolved = path.resolve()
        except OSError as exc:
            raise ValueError("Graphics path could not be resolved.") from exc
        if not _contained(base, resolved):
            raise ValueError("Graphics path resolves outside the project.")
        return resolved
    parent = path.parent
    while not parent.exists() and parent != parent.parent:
        parent = parent.parent
    try:
        resolved_parent = parent.resolve()
    except OSError as exc:
        raise ValueError("Graphics path could not be resolved.") from exc
    if not _contained(base, resolved_parent):
        raise ValueError("Graphics path resolves outside the project.")
    try:
        rest = path.relative_to(parent)
    except ValueError as exc:
        raise ValueError("Graphics path resolves outside the project.") from exc
    if ".." in rest.parts:
        raise ValueError("Graphics path resolves outside the project.")
    planned = resolved_parent.joinpath(*rest.parts)
    if not _contained(base, planned):
        raise ValueError("Graphics path resolves outside the project.")
    return planned


def _confine_existing(root, rel, prefixes=ARTIFACT_PREFIXES):
    relative_artifact(rel, prefixes)
    base = Path(root).resolve()
    try:
        resolved = (base / rel).resolve()
    except OSError as exc:
        raise ValueError("Graphics reference could not be resolved.") from exc
    if not _contained(base, resolved):
        raise ValueError("Graphics reference resolves outside the project.")
    if not resolved.is_file() or resolved.is_symlink():
        raise ValueError("Graphics reference is missing: " + rel)
    return resolved


def _confine_refs(root, refs, prefixes=ARTIFACT_PREFIXES):
    seen_rel = set()
    seen_file = {}
    resolved = []
    for rel in refs:
        if rel in seen_rel:
            raise ValueError("Graphics references cannot repeat the same path: " + rel)
        seen_rel.add(rel)
        path = _confine_existing(root, rel, prefixes=prefixes)
        key = os.path.normcase(str(path))
        previous = seen_file.get(key)
        if previous is not None and previous != rel:
            raise ValueError("Graphics references collide case-insensitively: " + previous + " and " + rel)
        seen_file[key] = rel
        resolved.append((rel, path))
    return resolved


def load_bounded_json_file(root, raw_path):
    """Read a bounded JSON object that stays inside the project tree."""
    if raw_path is None or not str(raw_path).strip():
        raise ValueError("--file must point to an existing project JSON object.")
    path = Path(raw_path)
    if path.is_symlink() or path.is_dir() or not path.is_file():
        raise ValueError("--file must be an existing regular file, not a directory or symlink.")
    try:
        resolved = path.resolve()
    except OSError as exc:
        raise ValueError("Graphics JSON file could not be resolved.") from exc
    brolls = Path(root).resolve()
    project = brolls.parent
    if not (_contained(project, resolved) or _contained(brolls, resolved)):
        raise ValueError("--file must stay inside the project tree.")
    try:
        size = resolved.stat().st_size
    except OSError as exc:
        raise ValueError("Graphics JSON file could not be read.") from exc
    if size > JSON_FILE_LIMIT:
        raise ValueError("--file exceeds the 2 MB bound for graphics JSON.")
    try:
        data = json.loads(resolved.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("--file must contain a JSON object: " + str(exc)) from exc
    if not isinstance(data, dict):
        raise ValueError("--file must contain a JSON object.")
    return data


def empty_graphics(profile):
    return {
        "schema_version": GRAPHICS_SCHEMA,
        "profile": profile,
        "style_revisions": [],
        "current_style_revision": None,
        "occurrences": {},
        "versions": {},
        "requests": [],
    }


def default_profile(fps: int | float = DEFAULT_FPS, fps_source="default"):
    stored = fps if type(fps) is int else float(fps)
    if isinstance(stored, float) and stored.is_integer():
        stored = int(stored)
    return {
        "width": DEFAULT_WIDTH,
        "height": DEFAULT_HEIGHT,
        "fps": stored,
        "fps_source": fps_source,
        "frame_rounding": FRAME_ROUNDING,
        "frame_rounding_note": (
            "Non-negative times use frame = floor(t * fps + 0.5), matching JS Math.round "
            "for t >= 0. Conversion error is at most one frame at each boundary. "
            "Remotion receives these integers and does not re-derive them from floats."
        ),
    }


def _profile_fps(profile):
    fps = profile.get("fps")
    if not _is_number(fps) or fps <= 0:
        raise ValueError
    return float(fps)


def validate_graphics(data):
    if "graphics" not in data:
        return data
    graphics = data.get("graphics")
    try:
        _validate_graphics_payload(graphics, data.get("project_id"))
    except (ValueError, TypeError, KeyError):
        raise ValueError(PRESERVE) from None
    return data


def _validate_graphics_payload(graphics, project_id=None):
    if not isinstance(graphics, dict) or not _is_int(graphics.get("schema_version")):
        raise ValueError
    if graphics["schema_version"] != GRAPHICS_SCHEMA:
        raise ValueError
    profile = graphics.get("profile")
    _validate_profile(profile)
    seen_rev = _validate_style_revisions(graphics.get("style_revisions"))
    current = graphics.get("current_style_revision")
    if current is not None and (not _is_int(current) or current not in seen_rev):
        raise ValueError
    occurrences = graphics.get("occurrences")
    versions = graphics.get("versions")
    if not isinstance(occurrences, dict) or not isinstance(versions, dict):
        raise ValueError
    for occ_id, occ in occurrences.items():
        _validate_occurrence(occ_id, occ, seen_rev, profile, versions)
    for ver_id, version in versions.items():
        _validate_version(ver_id, version, graphics, seen_rev, project_id)
    _validate_requests(graphics, project_id)


def _validate_profile(profile):
    if not isinstance(profile, dict):
        raise ValueError
    if not _is_int(profile.get("width")) or not _is_int(profile.get("height")):
        raise ValueError
    if profile["width"] != DEFAULT_WIDTH or profile["height"] != DEFAULT_HEIGHT:
        raise ValueError
    _profile_fps(profile)
    if profile.get("fps_source") not in ("default", "confirmed"):
        raise ValueError
    if profile.get("frame_rounding") != FRAME_ROUNDING:
        raise ValueError


def _validate_style_record(revision):
    if not isinstance(revision, dict) or not _is_int(revision.get("revision")):
        raise ValueError
    if revision["revision"] < 1:
        raise ValueError
    if revision.get("family") != "documentary":
        raise ValueError
    if revision.get("approved") is not False:
        raise ValueError
    if not isinstance(revision.get("proposal"), dict):
        raise ValueError
    if not _bounded_prose(revision.get("user_note", "x")):
        raise ValueError


def _validate_style_revisions(revisions):
    if not isinstance(revisions, list):
        raise ValueError
    seen_rev = set()
    for revision in revisions:
        _validate_style_record(revision)
        if revision["revision"] in seen_rev:
            raise ValueError
        seen_rev.add(revision["revision"])
    return seen_rev


def _validate_occurrence_props(props):
    if not isinstance(props, dict) or props.get("claim_status") not in CLAIM_STATUSES:
        raise ValueError
    for key in ("value", "unit", "label", "claim_note"):
        if not _bounded_text(props.get(key), 500):
            raise ValueError


def _validate_clip_props(props):
    _validate_occurrence_props(props)
    if not _bounded_prose(props.get("narration")):
        raise ValueError
    if props.get("timing_basis") not in ("estimated", "explicit"):
        raise ValueError
    background = props.get("background")
    if background is None:
        return
    if not isinstance(background, dict):
        raise ValueError
    src = background.get("src")
    if not isinstance(src, str) or not src.startswith("media/"):
        raise ValueError
    name = src[len("media/") :]
    if not name or name in (".", "..") or "/" in name or "\\" in name:
        raise ValueError
    if background.get("kind") not in ("video", "image"):
        raise ValueError


def _validate_anchors(anchors):
    if not isinstance(anchors, list):
        raise ValueError
    for item in anchors:
        if not isinstance(item, dict) or not _bounded_prose(item.get("text"), 500):
            raise ValueError
        if item.get("t_s") is not None and not _is_number(item["t_s"]):
            raise ValueError


def _validate_text_items(items):
    if not isinstance(items, list):
        raise ValueError
    for item in items:
        if not _bounded_prose(item, 2000):
            raise ValueError


def _validate_assignment_fields(payload, seen_rev, profile):
    for key in ("scene_id", "chapter_id"):
        if not _valid_id(payload.get(key)):
            raise ValueError
    template = payload.get("template")
    if template not in TEMPLATES or payload.get("composition") != TEMPLATES[template]:
        raise ValueError
    for key in ("chapter_context", "purpose", "narration"):
        if not _bounded_prose(payload.get(key)):
            raise ValueError
    if not _is_int(payload.get("style_revision")) or payload["style_revision"] not in seen_rev:
        raise ValueError
    _validate_timing(payload.get("timing"), profile["fps"])
    _validate_anchors(payload.get("anchors"))
    _validate_text_items(payload.get("questions"))
    _validate_text_items(payload.get("proposed_scenes"))
    if not isinstance(payload.get("asset_refs"), list) or not isinstance(payload.get("evidence_refs"), list):
        raise ValueError
    _validate_ref_list([*payload["asset_refs"], *payload["evidence_refs"]])
    _validate_material_use_field(payload)
    _validate_occurrence_props(payload.get("props"))
    _validate_optional_facts_audio(payload)
    _validate_optional_scene(payload, template)
    from .graphics_continuation import validate_work

    validate_work(payload)


def _validate_optional_scene(payload, template):
    if "timeline" in payload:
        from .graphics_timeline import validate_timeline

        if template != "timeline":
            raise ValueError
        validate_timeline(payload["timeline"])
    if "scene_content" in payload:
        from .graphics_scenes import validate_scene

        validate_scene(payload["scene_content"])
        if template != payload["scene_content"]["kind"]:
            raise ValueError


def _validate_optional_facts_audio(payload):
    if "facts" in payload:
        try:
            from .graphics_facts import validate_facts
        except ImportError as exc:
            raise ValueError from exc
        validate_facts(payload.get("facts"))
    if "audio" in payload:
        try:
            from .graphics_audio import validate_audio
        except ImportError as exc:
            raise ValueError from exc
        validate_audio(payload.get("audio"))
    if "background" in payload:
        try:
            from .graphics_media import validate_background
        except ImportError as exc:
            raise ValueError from exc
        validate_background(payload.get("background"))
    if "alignment" in payload:
        try:
            from .narration_alignment import validate_match
        except ImportError as exc:
            raise ValueError from exc
        validate_match(payload.get("alignment"))
    _validate_alignment_previews(payload.get("alignment_previews"))
    if "alignment_group" in payload:
        _validate_alignment_group(payload.get("alignment_group"))


def _validate_alignment_previews(previews):
    if previews is None:
        return
    if not isinstance(previews, dict):
        raise ValueError
    for key, item in previews.items():
        if not isinstance(key, str) or not key or not isinstance(item, dict):
            raise ValueError
        if item.get("error"):
            if not isinstance(item.get("error"), str) or not item.get("error"):
                raise ValueError
            continue
        ref = item.get("ref")
        if not isinstance(ref, str) or not ref.startswith("previews/"):
            raise ValueError
        relative_artifact(ref)
        if not _sha256(item.get("sha256")):
            raise ValueError


def _validate_alignment_group(group):
    if not isinstance(group, dict):
        raise ValueError
    ids = group.get("occurrence_ids")
    if not isinstance(ids, list) or not ids:
        raise ValueError
    seen = set()
    for occ_id in ids:
        if not _valid_id(occ_id) or occ_id in seen:
            raise ValueError
        seen.add(occ_id)


def _validate_occurrence(occ_id, occ, seen_rev, profile, versions):
    if not _valid_id(occ_id) or not isinstance(occ, dict):
        raise ValueError
    if occ.get("occurrence_id") != occ_id:
        raise ValueError
    _validate_assignment_fields(occ, seen_rev, profile)
    current_version = occ.get("current_version")
    if current_version is not None:
        if not isinstance(current_version, str) or not VERSION_RE.fullmatch(current_version):
            raise ValueError
        version = versions.get(current_version)
        if not isinstance(version, dict) or version.get("occurrence_id") != occ_id:
            raise ValueError


def _validate_ref_list(refs):
    seen = set()
    for ref in refs:
        relative_artifact(ref, prefixes=INPUT_PREFIXES)
        key = os.path.normcase(ref)
        if key in seen:
            raise ValueError
        seen.add(key)


def _material_evidence(value):
    if isinstance(value, str):
        value = [value]
    if not isinstance(value, list) or not value:
        raise ValueError
    evidence = []
    for item in value:
        if not _bounded_prose(item, 2000):
            raise ValueError
        evidence.append(item)
    return evidence


def _optional_candidate_id(value):
    if value is None:
        return None
    if not isinstance(value, str) or not value.strip():
        raise ValueError
    return value.strip()


def _optional_sha256(value, *, required):
    if required:
        if not _sha256(value):
            raise ValueError
        return value
    if value is None:
        return None
    if not _sha256(value):
        raise ValueError
    return value


def _normalize_candidate_rights(value):
    if value is None:
        return None
    if not isinstance(value, dict):
        raise ValueError
    status = value.get("status")
    if status not in (None, "unknown", "permitted", "restricted"):
        raise ValueError
    evidence = value.get("evidence")
    if evidence is None:
        evidence = []
    if not isinstance(evidence, list):
        raise ValueError
    record = {"status": status, "evidence": _material_evidence(evidence) if evidence else []}
    for key in ("license_name", "license_url"):
        item = value.get(key)
        if item is None:
            record[key] = None
            continue
        if not _bounded_prose(item, 2000):
            raise ValueError
        record[key] = item
    return record


def _attach_material_identity(item, entry, *, require_hash):
    candidate_id = _optional_candidate_id(item.get("candidate_id"))
    if candidate_id is not None:
        entry["candidate_id"] = candidate_id
    digest_value = _optional_sha256(item.get("sha256"), required=require_hash)
    if digest_value is not None:
        entry["sha256"] = digest_value
    rights = _normalize_candidate_rights(item.get("candidate_rights"))
    if rights is not None:
        entry["candidate_rights"] = rights
    signature = item.get("candidate_signature")
    if signature is not None:
        entry["candidate_signature"] = _optional_sha256(signature, required=True)
    acquisition = item.get("candidate_acquisition")
    if acquisition is None:
        return
    if not isinstance(acquisition, str) or not acquisition.strip():
        raise ValueError
    entry["candidate_acquisition"] = acquisition.strip()


def _normalize_material_use_entry(item, *, require_hash):
    if not isinstance(item, dict):
        raise ValueError
    ref = item.get("ref")
    relative_artifact(ref, prefixes=INPUT_PREFIXES)
    if item.get("rendered_use") not in RENDERED_USE:
        raise ValueError
    if item.get("raw_redistribution") not in RAW_REDISTRIBUTION:
        raise ValueError
    if not _bounded_prose(item.get("conditions"), 2000):
        raise ValueError
    entry = {
        "ref": ref,
        "rendered_use": item["rendered_use"],
        "raw_redistribution": item["raw_redistribution"],
        "evidence": _material_evidence(item.get("evidence")),
        "conditions": item["conditions"],
    }
    _attach_material_identity(item, entry, require_hash=require_hash)
    return entry


def _validate_material_use_field(payload):
    if "material_use" not in payload:
        return
    entries = payload.get("material_use")
    if not isinstance(entries, list):
        raise ValueError
    refs = set(payload.get("asset_refs") or []) | set(payload.get("evidence_refs") or [])
    seen = set()
    for item in entries:
        entry = _normalize_material_use_entry(item, require_hash=True)
        if entry["ref"] not in refs:
            raise ValueError
        key = os.path.normcase(entry["ref"])
        if key in seen:
            raise ValueError
        seen.add(key)


def _parse_material_use_args(values):
    parsed = []
    seen = set()
    for raw in values or []:
        if not isinstance(raw, str) or not raw.strip():
            raise ValueError(
                "--material-use must be JSON with ref, rendered_use, raw_redistribution, evidence and conditions."
            )
        try:
            item = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise ValueError("--material-use must be a JSON object: " + str(exc)) from exc
        entry = _normalize_material_use_entry(item, require_hash=False)
        key = os.path.normcase(entry["ref"])
        if key in seen:
            raise ValueError("material-use declarations cannot repeat the same ref: " + entry["ref"])
        seen.add(key)
        parsed.append(entry)
    return parsed


def _candidate_media_paths(candidate):
    preview = candidate.get("preview") if isinstance(candidate.get("preview"), dict) else {}
    output = candidate.get("output") if isinstance(candidate.get("output"), dict) else {}
    return [
        path for path in (output.get("path"), preview.get("contact_sheet_path"), preview.get("poster_path")) if path
    ]


def lookup_project_media(items, ref, candidate_id=None):
    """Bind a graphics ref to existing candidate media; do not invent rights."""
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
            raise ValueError("material-use candidate does not exist in this project: " + candidate_id)
        if ref not in _candidate_media_paths(by_id):
            raise ValueError("material-use ref is not that candidate's recorded output or preview path.")
        return by_id
    if len(matches) > 1:
        raise ValueError("material-use ref matches multiple candidates; pass candidate_id.")
    if len(matches) == 1:
        return matches[0]
    return None


def _live_candidate_rights(candidate):
    rights = _as_dict(candidate.get("rights"))
    return {
        "status": rights.get("status"),
        "evidence": list(rights.get("evidence") or []),
        "license_name": rights.get("license_name"),
        "license_url": rights.get("license_url"),
    }


def _candidate_hash_contract(entry, candidate, digest_value):
    output = _as_dict(candidate.get("output"))
    preview = _as_dict(candidate.get("preview"))
    ref = entry.get("ref")
    if output.get("path") == ref:
        return output.get("verified") is True and output.get("sha256") == digest_value
    if preview.get("contact_sheet_path") == ref:
        recorded = candidate.get("full_preview_sha256")
        return recorded is None or recorded == digest_value
    if preview.get("poster_path") == ref:
        recorded = candidate.get("context_image_sha256")
        return recorded is None or recorded == digest_value
    return True


def _caller_binding_matches_live(entry, live):
    supplied_sig = entry.get("candidate_signature")
    if supplied_sig is not None and supplied_sig != live["candidate_signature"]:
        return False
    supplied_acq = entry.get("candidate_acquisition")
    if supplied_acq is not None and supplied_acq != live["candidate_acquisition"]:
        return False
    supplied_rights = entry.get("candidate_rights")
    if not isinstance(supplied_rights, dict):
        return True
    live_rights = live["candidate_rights"]
    if supplied_rights.get("status") not in (None, live_rights.get("status")):
        return False
    supplied_evidence = supplied_rights.get("evidence")
    return supplied_evidence is None or list(supplied_evidence) == list(live_rights.get("evidence") or [])


def _live_candidate_binding(candidate):
    acquisition = _as_dict(candidate.get("acquisition"))
    return {
        "candidate_id": candidate.get("id"),
        "candidate_signature": candidate_signature(candidate),
        "candidate_acquisition": acquisition.get("status"),
        "candidate_rights": _live_candidate_rights(candidate),
    }


def _frozen_binding_matches_live(entry, live):
    frozen_sig = entry.get("candidate_signature")
    if frozen_sig is not None and frozen_sig != live["candidate_signature"]:
        return False
    frozen_acq = entry.get("candidate_acquisition")
    if frozen_acq is not None and frozen_acq != live["candidate_acquisition"]:
        return False
    frozen_rights = entry.get("candidate_rights") if isinstance(entry.get("candidate_rights"), dict) else None
    if frozen_rights is None:
        return True
    live_rights = live["candidate_rights"]
    if frozen_rights.get("status") != live_rights.get("status"):
        return False
    return list(frozen_rights.get("evidence") or []) == list(live_rights.get("evidence") or [])


def _candidate_permission_ok(entry, candidate, digest_value):
    """Revalidate identity, content and current permission; status strings are not enough."""
    if candidate is None:
        return True
    live = _live_candidate_binding(candidate)
    if not _frozen_binding_matches_live(entry, live) or not _candidate_hash_contract(entry, candidate, digest_value):
        return False
    if entry.get("rendered_use") != "permitted":
        return True
    try:
        require_fetch(candidate)
    except (ValueError, KeyError, TypeError):
        return False
    return live["candidate_signature"] == candidate_signature(candidate)


def _candidate_rendered_use_ok(entry, candidate, digest_value):
    return _candidate_permission_ok(entry, candidate, digest_value)


def bind_material_use(root, entries, assigned_refs, items):
    """Attach content-bound hashes and reuse candidate approval/rights, never path presence."""
    confined = dict(_confine_refs(root, assigned_refs, prefixes=INPUT_PREFIXES))
    bound = []
    for entry in entries:
        rel = entry["ref"]
        if rel not in confined:
            raise ValueError("material-use ref must be one of this assignment's --asset-ref or --evidence-ref paths.")
        digest_value = digest(confined[rel])
        supplied = entry.get("sha256")
        if supplied is not None and supplied != digest_value:
            raise ValueError(
                "material-use sha256 does not match the confined file bytes for "
                + rel
                + "; supplied content identity cannot be overwritten."
            )
        stored = dict(entry)
        stored["sha256"] = digest_value
        try:
            candidate = lookup_project_media(items, rel, stored.get("candidate_id"))
        except ValueError as exc:
            raise ValueError(str(exc)) from exc
        if candidate is not None:
            live = _live_candidate_binding(candidate)
            if not _caller_binding_matches_live(stored, live):
                raise ValueError(
                    "Explicit material-use candidate metadata cannot override this project's current "
                    "approval, signature, acquisition or rights for " + rel + "."
                )
            stored.update(live)
        if stored.get("rendered_use") == "permitted" and not _candidate_rendered_use_ok(
            stored, candidate, digest_value
        ):
            raise ValueError(
                "Rendered use cannot be permitted for "
                + rel
                + " unless the bound candidate is approved with a current signature, "
                "rights are permitted with evidence, acquisition is available, and the hash still matches."
            )
        bound.append(stored)
    return bound


def _frozen_input_hashes(root, version, rel):
    spec = _as_dict(_as_dict(version.get("fingerprints")).get("inputs")).get(rel)
    recorded = spec.get("sha256") if isinstance(spec, dict) else None
    frozen_rel = spec.get("frozen") if isinstance(spec, dict) else None
    actual = None
    if isinstance(frozen_rel, str) and _valid_id(version.get("scene_id")) and isinstance(version.get("id"), str):
        try:
            version_dir = _confine_planned(root, _version_dir(root, version.get("scene_id"), version.get("id")))
            actual = _file_digest(_confine_declared_file(version_dir, frozen_rel))
        except ValueError:
            actual = None
    return recorded, actual


def _separately_held_record(entry, *, note):
    record = {
        "ref": entry.get("ref"),
        "sha256": entry.get("sha256"),
        "rendered_use": entry.get("rendered_use"),
        "raw_redistribution": entry.get("raw_redistribution"),
        "evidence": list(entry.get("evidence") or []),
        "conditions": entry.get("conditions"),
        "note": note,
    }
    if entry.get("candidate_id"):
        record["candidate_id"] = entry.get("candidate_id")
    if isinstance(entry.get("candidate_rights"), dict):
        record["candidate_rights"] = entry.get("candidate_rights")
    frozen_ref = entry.get("frozen_ref")
    if isinstance(frozen_ref, str):
        posix = frozen_ref.replace("\\", "/")
        if posix.startswith(("public/audio/", "public/media/")):
            record["frozen_ref"] = posix
    return record


def _material_entries_by_ref(frozen):
    if "material_use" not in frozen:
        return None
    entries = frozen.get("material_use")
    if not isinstance(entries, list):
        raise ValueError
    by_ref = {}
    for item in entries:
        entry = _normalize_material_use_entry(item, require_hash=True)
        if entry["ref"] in by_ref:
            raise ValueError
        by_ref[entry["ref"]] = entry
    return by_ref


def _classify_asset_ref(ctx, rel):
    entry = ctx["by_ref"].get(rel)
    if entry is None:
        ctx["reasons"].append("unresolved_material_use")
        return
    reason, record = _material_entry_state(ctx["root"], ctx["version"], entry, ctx["items"], require_rendered=True)
    if reason:
        ctx["reasons"].append(reason)
        return
    if entry.get("raw_redistribution") == "permitted":
        ctx["permitted_raw"].append(record)
        return
    ctx["separately_held"].append(
        _separately_held_record(
            record,
            note="Raw redistribution is restricted or unknown; the original is separately held.",
        )
    )
    if entry.get("raw_redistribution") == "unknown":
        ctx["reasons"].append("unresolved_material_use")


def _classify_evidence_ref(ctx, rel):
    entry = ctx["by_ref"].get(rel)
    if entry is None:
        recorded, actual = _frozen_input_hashes(ctx["root"], ctx["version"], rel)
        ctx["separately_held"].append(
            _separately_held_record(
                {
                    "ref": rel,
                    "sha256": actual or recorded,
                    "rendered_use": "unknown",
                    "raw_redistribution": "unknown",
                    "evidence": [],
                    "conditions": "No explicit raw-redistribution declaration.",
                },
                note="Separately held; unknown raw evidence is not copied into the source package.",
            )
        )
        return
    reason, record = _material_entry_state(ctx["root"], ctx["version"], entry, ctx["items"], require_rendered=False)
    if reason:
        ctx["reasons"].append(reason)
        ctx["separately_held"].append(
            _separately_held_record(entry, note="Stale or unknown evidence remains separately held.")
        )
        return
    if entry.get("raw_redistribution") == "permitted":
        ctx["permitted_raw"].append(record)
        return
    ctx["separately_held"].append(_separately_held_record(record, note="Evidence raw bytes remain separately held."))


def classify_material_use(root, version, items=None):
    """Permission for finished-video use is distinct from raw redistribution.

    Missing optional material_use on a legacy assignment is left absent. Nonempty
    asset_refs without a matching content-bound declaration stay unresolved.
    """
    frozen = version.get("assignment") if isinstance(version.get("assignment"), dict) else {}
    asset_refs = [rel for rel in (frozen.get("asset_refs") or []) if isinstance(rel, str)]
    evidence_refs = [rel for rel in (frozen.get("evidence_refs") or []) if isinstance(rel, str)]
    if asset_refs and "material_use" not in frozen:
        return {"reasons": ["unresolved_material_use"], "permitted_raw": [], "separately_held": []}
    try:
        by_ref = _material_entries_by_ref(frozen)
    except ValueError:
        return {"reasons": ["unresolved_material_use"], "permitted_raw": [], "separately_held": []}
    ctx = {
        "root": root,
        "version": version,
        "items": items,
        "by_ref": by_ref or {},
        "reasons": [],
        "permitted_raw": [],
        "separately_held": [],
    }
    for rel in asset_refs:
        _classify_asset_ref(ctx, rel)
    for rel in evidence_refs:
        _classify_evidence_ref(ctx, rel)
    _classify_facts_sources(ctx, frozen)
    _classify_audio_effects(ctx, frozen)
    _classify_background(ctx, frozen)
    return {
        "reasons": _unique(ctx["reasons"]),
        "permitted_raw": ctx["permitted_raw"],
        "separately_held": ctx["separately_held"],
    }


def _classify_facts_sources(ctx, assignment):
    facts = assignment.get("facts") if isinstance(assignment, dict) else None
    if not isinstance(facts, dict):
        return
    require_rendered = facts.get("required") is True
    for source in facts.get("sources") or []:
        if not isinstance(source, dict) or not isinstance(source.get("data_ref"), str):
            continue
        rel = source["data_ref"]
        entry = {
            "ref": rel,
            "sha256": source.get("sha256"),
            "rendered_use": source.get("rendered_use"),
            "raw_redistribution": source.get("raw_redistribution"),
            "evidence": [item for item in (source.get("title"), source.get("url"), rel) if item],
            "conditions": source.get("conditions") or "Fact source data.",
        }
        kind = source.get("kind")
        reason, record = _material_entry_state(
            ctx["root"], ctx["version"], entry, ctx["items"], require_rendered=require_rendered and kind == "data"
        )
        if reason:
            ctx["reasons"].append(reason)
            ctx["separately_held"].append(
                _separately_held_record(entry, note="Fact source data remains separately held.")
            )
            continue
        if kind == "chart_image":
            ctx["separately_held"].append(
                _separately_held_record(
                    record,
                    note="Chart images are not editable source data and remain separately held.",
                )
            )
            continue
        if entry.get("raw_redistribution") == "permitted" and kind == "data":
            ctx["permitted_raw"].append(record)
            continue
        ctx["separately_held"].append(
            _separately_held_record(record, note="Restricted or unknown fact source data remains separately held.")
        )
        if entry.get("raw_redistribution") == "unknown":
            ctx["reasons"].append("unresolved_material_use")


def _audio_frozen_ref(version, ref):
    audio_fp = _as_dict(_as_dict(version.get("fingerprints")).get("audio"))
    for item in audio_fp.get("assets") or []:
        if not isinstance(item, dict) or item.get("ref") != ref:
            continue
        frozen_ref = item.get("frozen_ref")
        if isinstance(frozen_ref, str) and frozen_ref.replace("\\", "/").startswith("public/audio/"):
            return frozen_ref.replace("\\", "/")
    return None


def _classify_audio_effects(ctx, assignment):
    audio = assignment.get("audio") if isinstance(assignment, dict) else None
    if not isinstance(audio, dict):
        return
    for effect in audio.get("effects") or []:
        if not isinstance(effect, dict) or not isinstance(effect.get("ref"), str):
            continue
        entry = {
            "ref": effect.get("ref"),
            "sha256": effect.get("sha256"),
            "rendered_use": effect.get("rendered_use"),
            "raw_redistribution": effect.get("raw_redistribution"),
            "evidence": [item for item in (effect.get("source_url"), effect.get("license"), effect.get("id")) if item],
            "conditions": effect.get("conditions") or "Sound effect.",
        }
        frozen_ref = _audio_frozen_ref(ctx.get("version") or {}, entry["ref"])
        if frozen_ref:
            entry["frozen_ref"] = frozen_ref
        if entry.get("rendered_use") != "permitted":
            ctx["reasons"].append("unresolved_material_use")
        if entry.get("raw_redistribution") == "permitted":
            ctx["permitted_raw"].append(entry)
            continue
        ctx["separately_held"].append(
            _separately_held_record(
                entry,
                note=(
                    "Restricted or unknown effect originals remain separately held. "
                    "Frozen public/audio cue bytes are omitted from the package; "
                    "reconstruct them with --held-ref at the frozen cue src."
                ),
            )
        )
        if entry.get("raw_redistribution") == "unknown":
            ctx["reasons"].append("unresolved_material_use")


def _background_frozen_ref(version, ref):
    background_fp = _as_dict(_as_dict(version.get("fingerprints")).get("background"))
    for item in background_fp.get("assets") or []:
        if not isinstance(item, dict) or item.get("ref") != ref:
            continue
        frozen_ref = item.get("frozen_ref")
        if isinstance(frozen_ref, str) and frozen_ref.replace("\\", "/").startswith("public/media/"):
            return frozen_ref.replace("\\", "/")
    return None


def _classify_background(ctx, assignment):
    background = assignment.get("background") if isinstance(assignment, dict) else None
    if not isinstance(background, dict):
        return
    ref = background.get("ref")
    if not isinstance(ref, str) or not ref:
        ctx["reasons"].append("unresolved_material_use")
        return
    material = _as_dict(background.get("material_use"))
    entry = {
        "ref": ref,
        "sha256": background.get("sha256") or material.get("sha256"),
        "rendered_use": material.get("rendered_use") or background.get("rendered_use"),
        "raw_redistribution": material.get("raw_redistribution") or background.get("raw_redistribution"),
        "evidence": list(material.get("evidence") or background.get("evidence") or []),
        "conditions": material.get("conditions") or background.get("conditions") or "Background media.",
        "candidate_id": background.get("candidate_id") or material.get("candidate_id"),
    }
    frozen_ref = _background_frozen_ref(ctx.get("version") or {}, ref)
    if frozen_ref:
        entry["frozen_ref"] = frozen_ref
    if entry.get("rendered_use") != "permitted":
        ctx["reasons"].append("unresolved_material_use")
    if entry.get("raw_redistribution") == "permitted":
        ctx["permitted_raw"].append(entry)
        return
    ctx["separately_held"].append(
        _separately_held_record(
            entry,
            note=(
                "Restricted or unknown background originals remain separately held. "
                "Frozen public/media bytes are omitted from the package; "
                "reconstruct them with --held-ref at the frozen media src."
            ),
        )
    )
    if entry.get("raw_redistribution") == "unknown":
        ctx["reasons"].append("unresolved_material_use")


def _material_entry_state(root, version, entry, items, *, require_rendered):
    recorded, actual = _frozen_input_hashes(root, version, entry["ref"])
    digest_value = entry.get("sha256")
    unresolved = "unresolved_material_use", entry
    if not _sha256(digest_value) or recorded != digest_value or actual != digest_value:
        return unresolved
    try:
        candidate = lookup_project_media(items, entry["ref"], entry.get("candidate_id"))
    except ValueError:
        return unresolved
    missing = bool(entry.get("candidate_id") and candidate is None)
    denied = candidate is not None and not _candidate_rendered_use_ok(entry, candidate, digest_value)
    unfinished = require_rendered and (
        entry.get("rendered_use") != "permitted" or entry.get("raw_redistribution") not in ("permitted", "restricted")
    )
    if missing or denied or unfinished:
        return unresolved
    record = dict(entry)
    if candidate is not None:
        record["candidate_id"] = candidate.get("id")
    return None, record


def _validate_parent_chain(ver_id, versions):
    seen = set()
    current = ver_id
    while current is not None:
        if current in seen:
            raise ValueError
        version = versions.get(current)
        if not isinstance(version, dict):
            raise ValueError
        seen.add(current)
        parent = version.get("parent")
        if parent is None:
            return
        if parent == current or not isinstance(parent, str) or not VERSION_RE.fullmatch(parent):
            raise ValueError
        parent_version = versions.get(parent)
        if not isinstance(parent_version, dict) or parent_version.get("occurrence_id") != version.get("occurrence_id"):
            raise ValueError
        current = parent


def _validate_hash_map(value, required_keys=None):
    if not isinstance(value, dict):
        raise ValueError
    for key, digest_value in value.items():
        if not isinstance(key, str) or not key or not _sha256(digest_value):
            raise ValueError
    if required_keys is not None and set(value) != set(required_keys):
        raise ValueError


def _frozen_ref_rel(rel):
    relative_artifact(rel, prefixes=INPUT_PREFIXES)
    return FROZEN_REFS_PREFIX + rel


def _assignment_input_refs(assignment):
    refs = []
    if isinstance(assignment.get("scene_content"), dict):
        from .graphics_scenes import input_refs

        refs.extend(input_refs(assignment["scene_content"]))
    for key in ("asset_refs", "evidence_refs"):
        refs.extend(rel for rel in assignment.get(key) or [] if isinstance(rel, str))
    facts = assignment.get("facts")
    if isinstance(facts, dict):
        refs.extend(
            source["data_ref"]
            for source in facts.get("sources") or []
            if isinstance(source, dict) and isinstance(source.get("data_ref"), str) and source["data_ref"]
        )
    return _unique(refs)


def _source_template_names(source):
    if not isinstance(source, dict):
        raise ValueError
    keys = set(source)
    if keys == set(TEMPLATE_FILES):
        return TEMPLATE_FILES
    if keys == set(AUDIO_TEMPLATE_FILES):
        return AUDIO_TEMPLATE_FILES
    if keys == set(BACKGROUND_TEMPLATE_FILES):
        return BACKGROUND_TEMPLATE_FILES
    if keys == set(TIMELINE_TEMPLATE_FILES):
        return TIMELINE_TEMPLATE_FILES
    if keys == set(MAP_TEMPLATE_FILES):
        return MAP_TEMPLATE_FILES
    if keys == set(CUSTOM_TEMPLATE_FILES):
        return CUSTOM_TEMPLATE_FILES
    raise ValueError


def _validate_inputs_map(inputs, expected_refs):
    if not isinstance(inputs, dict):
        raise ValueError
    if set(inputs) != set(expected_refs):
        raise ValueError
    seen_frozen = set()
    for rel, spec in inputs.items():
        relative_artifact(rel, prefixes=INPUT_PREFIXES)
        if not isinstance(spec, dict) or not _sha256(spec.get("sha256")):
            raise ValueError
        frozen = spec.get("frozen")
        if not isinstance(frozen, str) or frozen != _frozen_ref_rel(rel):
            raise ValueError
        relative_artifact(frozen, prefixes=(FROZEN_REFS_PREFIX,))
        key = os.path.normcase(frozen)
        if key in seen_frozen:
            raise ValueError
        seen_frozen.add(key)


def _validate_runtime(runtime):
    if not isinstance(runtime, dict) or runtime.get("kind") not in ("remotion", "test-worker"):
        raise ValueError
    if not _sha256(runtime.get("worker_sha256")):
        raise ValueError
    if runtime["kind"] != "remotion":
        return
    if not _sha256(runtime.get("package_lock_sha256")) or not _sha256(runtime.get("package_json_sha256")):
        raise ValueError
    if not _sha256(runtime.get("node_sha256")) or not _sha256(runtime.get("browser_sha256")):
        raise ValueError
    if not isinstance(runtime.get("browser_executable"), str) or not runtime["browser_executable"]:
        raise ValueError
    if not isinstance(runtime.get("node_version"), str) or not runtime["node_version"]:
        raise ValueError


def _validate_fingerprints(version, assignment, style, props):
    fingerprints = version.get("fingerprints")
    if not isinstance(fingerprints, dict):
        raise ValueError
    if fingerprints.get("assignment_sha256") != _payload_hash(assignment):
        raise ValueError
    if fingerprints.get("style_sha256") != _payload_hash(style):
        raise ValueError
    if fingerprints.get("props_sha256") != _payload_hash(props):
        raise ValueError
    if fingerprints.get("style_revision") != style.get("revision"):
        raise ValueError
    if fingerprints.get("profile") != version.get("profile") or fingerprints.get("timing") != version.get("timing"):
        raise ValueError
    _validate_hash_map(fingerprints.get("source"), _source_template_names(fingerprints.get("source")))
    runtime = fingerprints.get("runtime")
    _validate_runtime(runtime)
    if not isinstance(runtime, dict):
        raise ValueError
    font_keys = FONT_FILES if runtime["kind"] == "remotion" else ()
    _validate_hash_map(fingerprints.get("fonts"), font_keys)
    _validate_inputs_map(fingerprints.get("inputs"), _assignment_input_refs(assignment))
    _validate_optional_fingerprints(fingerprints, version, assignment)


def _validate_optional_fingerprints(fingerprints, version, assignment):
    audio_fp = fingerprints.get("audio")
    if audio_fp is not None:
        _validate_audio_fingerprints(audio_fp, version)
    background_fp = fingerprints.get("background")
    if background_fp is not None:
        _validate_background_fingerprints(background_fp, version)
    elif version.get("status") == "complete" and isinstance(assignment.get("background"), dict):
        raise ValueError
    alignment_fp = fingerprints.get("alignment")
    if isinstance(assignment.get("alignment"), dict):
        if not isinstance(alignment_fp, dict) or alignment_fp.get("sha256") != _payload_hash(
            assignment.get("alignment")
        ):
            raise ValueError
    elif alignment_fp is not None:
        raise ValueError


def _validate_version_identity(ver_id, version, occurrences):
    if not isinstance(ver_id, str) or not VERSION_RE.fullmatch(ver_id) or not isinstance(version, dict):
        raise ValueError
    if version.get("id") != ver_id:
        raise ValueError
    occ_id = version.get("occurrence_id")
    if occ_id not in occurrences:
        raise ValueError
    occ = occurrences[occ_id]
    if version.get("scene_id") != occ.get("scene_id"):
        raise ValueError
    template = version.get("template")
    if template not in TEMPLATES or version.get("composition") != TEMPLATES[template]:
        raise ValueError
    if version.get("status") not in ("staging", "failed", "complete"):
        raise ValueError
    return occ_id


def _validate_version_payloads(version, occ_id, versions, profile, seen_rev):
    _validate_profile(version.get("profile"))
    if version["profile"] != profile:
        raise ValueError
    _validate_timing(version.get("timing"), version["profile"]["fps"])
    assignment = version.get("assignment")
    if not isinstance(assignment, dict) or assignment.get("occurrence_id") != occ_id:
        raise ValueError
    _validate_occurrence(occ_id, assignment, seen_rev, version["profile"], versions)
    if assignment.get("scene_id") != version.get("scene_id") or assignment.get("timing") != version.get("timing"):
        raise ValueError
    style = version.get("style")
    _validate_style_record(style)
    if style["revision"] not in seen_rev or style["revision"] != assignment.get("style_revision"):
        raise ValueError
    props = version.get("props")
    _validate_clip_props(props)
    _validate_scene_version_props(version, assignment, props)
    _validate_fingerprints(version, assignment, style, props)


def _validate_scene_version_props(version, assignment, props):
    if assignment["template"] in ("map", "custom"):
        from .graphics_scenes import clip_scene

        if not isinstance(assignment.get("scene_content"), dict) or props.get("scene") != clip_scene(
            assignment["scene_content"], assignment["timing"], version["profile"]["fps"], seconds_to_frame
        ):
            raise ValueError
    if assignment["template"] == "timeline":
        from .graphics_timeline import clip_milestones

        timeline = assignment.get("timeline")
        if not isinstance(timeline, dict) or props.get("title") != timeline["title"]:
            raise ValueError
        if props.get("milestones") != clip_milestones(
            timeline, assignment["timing"], version["profile"]["fps"], seconds_to_frame
        ):
            raise ValueError
    if assignment["template"] == "custom":
        ref = assignment["scene_content"]["source_ref"]
        if version["fingerprints"]["source"].get("AuthorScene.jsx") != version["fingerprints"]["inputs"][ref]["sha256"]:
            raise ValueError


def _validate_processing_record(processing):
    if processing is None:
        return
    if not isinstance(processing, dict):
        raise ValueError
    if not isinstance(processing.get("at"), str) or not processing["at"]:
        raise ValueError
    if not _bounded_prose(processing.get("outcome")):
        raise ValueError
    resulting = processing.get("resulting_version")
    if not isinstance(resulting, str) or not VERSION_RE.fullmatch(resulting):
        raise ValueError


def _bound_project_id(value):
    return isinstance(value, str) and bool(value.strip())


def _validate_approval_actor(approval):
    if approval.get("status") != "approved":
        raise ValueError
    if not _bounded_text(approval.get("by"), 500):
        raise ValueError
    if not isinstance(approval.get("at"), str) or not approval["at"]:
        raise ValueError
    if approval.get("channel") not in ("chat", "storyboard"):
        raise ValueError
    statement = approval.get("statement")
    if statement is not None and (not isinstance(statement, str) or len(statement) > MAX_TEXT):
        raise ValueError
    if approval["channel"] == "chat" and not (statement or "").strip():
        raise ValueError


def _validate_approval_target(approval, version, project_id=None):
    if approval.get("version_id") != version.get("id"):
        raise ValueError
    if approval.get("occurrence_id") != version.get("occurrence_id"):
        raise ValueError
    if approval.get("scene_id") != version.get("scene_id"):
        raise ValueError
    bound = approval.get("project_id")
    if not _bound_project_id(bound):
        raise ValueError
    if _bound_project_id(project_id) and bound != project_id:
        raise ValueError


def _validate_approval_record(approval, version, project_id=None):
    if not isinstance(approval, dict):
        raise ValueError
    _validate_approval_actor(approval)
    _validate_approval_target(approval, version, project_id)
    content = graphics_content_sha256(version)
    if approval.get("content_sha256") != content or approval.get("signature") != content:
        raise ValueError


def _validate_review_state(review):
    if review is None:
        return
    if not isinstance(review, dict):
        raise ValueError
    if review.get("state") not in ("pending", "approved", "changes"):
        raise ValueError
    comment = review.get("comment", "")
    if not isinstance(comment, str) or len(comment) > MAX_TEXT:
        raise ValueError


def _validate_approval_history_entry(entry):
    if not _bounded_text(entry.get("by"), 500):
        raise ValueError
    if entry.get("channel") not in ("chat", "storyboard"):
        raise ValueError
    if not _valid_id(entry.get("scene_id")) or not _valid_id(entry.get("occurrence_id")):
        raise ValueError
    if not isinstance(entry.get("version_id"), str) or not VERSION_RE.fullmatch(entry["version_id"]):
        raise ValueError
    if not _bound_project_id(entry.get("project_id")):
        raise ValueError
    if not _sha256(entry.get("content_sha256")) or entry.get("signature") != entry.get("content_sha256"):
        raise ValueError
    statement = entry.get("statement")
    if statement is not None and (not isinstance(statement, str) or len(statement) > MAX_TEXT):
        raise ValueError
    if entry["channel"] == "chat" and not (statement or "").strip():
        raise ValueError


def _validate_request_history_entry(entry):
    if not _bounded_text(entry.get("by"), 500):
        raise ValueError
    if not _valid_id(entry.get("request_id")):
        raise ValueError
    if not isinstance(entry.get("reviewed_version"), str) or not VERSION_RE.fullmatch(entry["reviewed_version"]):
        raise ValueError
    if entry.get("scope") not in ("scene", "shared"):
        raise ValueError


def _validate_complete_history_entry(entry):
    if not _valid_id(entry.get("request_id")):
        raise ValueError
    if not _bounded_prose(entry.get("outcome")):
        raise ValueError
    resulting = entry.get("resulting_version")
    if not isinstance(resulting, str) or not VERSION_RE.fullmatch(resulting):
        raise ValueError


def _validate_review_history(history):
    if history is None:
        return
    if not isinstance(history, list):
        raise ValueError
    for entry in history:
        if not isinstance(entry, dict):
            raise ValueError
        kind = entry.get("kind")
        if kind not in ("approval", "request", "request_complete"):
            raise ValueError
        if not isinstance(entry.get("at"), str) or not entry["at"]:
            raise ValueError
        if kind == "approval":
            _validate_approval_history_entry(entry)
        elif kind == "request":
            _validate_request_history_entry(entry)
        else:
            _validate_complete_history_entry(entry)


def _validate_request_target(req, graphics, project_id):
    if not _bound_project_id(req.get("project_id")):
        raise ValueError
    if _bound_project_id(project_id) and req["project_id"] != project_id:
        raise ValueError
    if not _valid_id(req.get("scene_id")) or not _valid_id(req.get("occurrence_id")):
        raise ValueError
    occurrences = graphics.get("occurrences") if isinstance(graphics.get("occurrences"), dict) else {}
    if req["occurrence_id"] not in occurrences:
        raise ValueError
    occ = occurrences[req["occurrence_id"]]
    if not isinstance(occ, dict) or occ.get("scene_id") != req["scene_id"]:
        raise ValueError
    if not isinstance(req.get("reviewed_version"), str) or not VERSION_RE.fullmatch(req["reviewed_version"]):
        raise ValueError
    versions = graphics.get("versions") if isinstance(graphics.get("versions"), dict) else {}
    version = versions.get(req["reviewed_version"])
    if isinstance(version, dict) and version.get("occurrence_id") != req["occurrence_id"]:
        raise ValueError
    return occ, version


def _validate_processed_result(req, processing, graphics):
    _validate_processing_record(processing)
    versions = graphics.get("versions") if isinstance(graphics.get("versions"), dict) else {}
    resulting = processing.get("resulting_version")
    result = versions.get(resulting)
    if not isinstance(result, dict) or result.get("status") != "complete":
        raise ValueError
    if result.get("occurrence_id") != req.get("occurrence_id"):
        raise ValueError
    if not _is_descendant(versions, resulting, req.get("reviewed_version")):
        raise ValueError


def _validate_request_processing(req, graphics):
    processing = req.get("processing")
    history = req.get("processing_history")
    if history is not None:
        if not isinstance(history, list):
            raise ValueError
        for item in history:
            _validate_processing_record(item)
    if req.get("state") == "processed":
        if processing is None:
            raise ValueError
        _validate_processed_result(req, processing, graphics)
        return
    if processing is not None:
        raise ValueError


def _validate_request(req, graphics, seen_ids, project_id=None):
    if not isinstance(req, dict):
        raise ValueError
    ident = req.get("id")
    if not _valid_id(ident) or ident in seen_ids:
        raise ValueError
    seen_ids.add(ident)
    _validate_request_target(req, graphics, project_id)
    if not _sha256(req.get("content_sha256")):
        raise ValueError
    if not _bounded_prose(req.get("text")):
        raise ValueError
    if req.get("scope") not in ("scene", "shared"):
        raise ValueError
    if req.get("state") not in ("saved", "processed", "stale"):
        raise ValueError
    _validate_request_processing(req, graphics)


def _validate_requests(graphics, project_id=None):
    requests = graphics.get("requests")
    if requests is None:
        return
    if not isinstance(requests, list):
        raise ValueError
    seen_ids = set()
    for req in requests:
        _validate_request(req, graphics, seen_ids, project_id)


def _validate_render_progress(version):
    progress = version.get("render_progress")
    if progress is not None:
        if not isinstance(progress, dict) or progress.get("phase") not in ("frozen", "rendered", "published"):
            raise ValueError
        if progress["phase"] in ("rendered", "published") and not _sha256(progress.get("sha256")):
            raise ValueError
        if version["status"] == "complete" and (
            progress["phase"] != "published" or progress["sha256"] != (version.get("artifact") or {}).get("sha256")
        ):
            raise ValueError
        if version["status"] != "complete" and progress["phase"] == "published":
            raise ValueError


def _validate_version_outcome(version, project_id=None):
    _validate_render_progress(version)
    artifact = version.get("artifact")
    if version["status"] == "complete":
        _validate_complete_artifact(artifact, version)
        approval = version.get("approval")
        if approval is not None:
            _validate_approval_record(approval, version, project_id)
        _validate_review_state(version.get("review"))
        _validate_review_history(version.get("review_history"))
        if "delivery" in version:
            _validate_delivery_record(version.get("delivery"), version)
        return
    if artifact is not None:
        raise ValueError
    if version.get("approval") is not None:
        raise ValueError
    if version["status"] != "failed":
        return
    diagnostics = version.get("diagnostics")
    message = diagnostics.get("message") if isinstance(diagnostics, dict) else None
    if not isinstance(message, str) or not message or len(message) > DIAGNOSTIC_LIMIT:
        raise ValueError


def _validate_version(ver_id, version, graphics, seen_rev, project_id=None):
    occurrences = graphics.get("occurrences")
    versions = graphics.get("versions")
    if not isinstance(occurrences, dict) or not isinstance(versions, dict):
        raise ValueError
    occ_id = _validate_version_identity(ver_id, version, occurrences)
    _validate_parent_chain(ver_id, versions)
    _validate_version_payloads(version, occ_id, versions, graphics.get("profile"), seen_rev)
    _validate_version_outcome(version, project_id)


def _validate_artifact_duration(artifact, version):
    if not _is_int(artifact.get("nb_frames")) or artifact["nb_frames"] < 1:
        raise ValueError
    expected = version["timing"]["duration_in_frames"]
    if abs(artifact["nb_frames"] - expected) > 1:
        raise ValueError
    if not _is_number(artifact.get("duration_s")):
        raise ValueError
    fps = float(version["profile"]["fps"])
    if abs(artifact["duration_s"] - (expected / fps)) > (1.0 / fps):
        raise ValueError


def _version_has_effects(version):
    audio = _as_dict(_as_dict(version.get("fingerprints")).get("audio"))
    if audio.get("mode") == "effects" and audio.get("codec") == "aac":
        return True
    cues = _as_dict(version.get("props")).get("sound_cues")
    return isinstance(cues, list) and bool(cues)


def _validate_audio_assets(assets):
    if assets is None:
        return
    if not isinstance(assets, list):
        raise ValueError
    for item in assets:
        if not isinstance(item, dict) or not _sha256(item.get("sha256")):
            raise ValueError
        frozen_ref = item.get("frozen_ref")
        if not isinstance(frozen_ref, str) or not frozen_ref.startswith("public/audio/"):
            raise ValueError
        _safe_version_rel(frozen_ref)


def _validate_audio_fingerprints(audio_fp, version):
    if not isinstance(audio_fp, dict):
        raise ValueError
    if audio_fp.get("mode") != "effects" or audio_fp.get("codec") != "aac":
        raise ValueError
    if not _sha256(audio_fp.get("cues_sha256")):
        raise ValueError
    cues = _as_dict(version.get("props")).get("sound_cues")
    if not isinstance(cues, list) or not cues:
        raise ValueError
    if audio_fp.get("cues_sha256") != _payload_hash(cues):
        raise ValueError
    _validate_audio_assets(audio_fp.get("assets"))


def _validate_background_assets(assets):
    if not isinstance(assets, list) or not assets:
        raise ValueError
    for item in assets:
        if not isinstance(item, dict) or not _sha256(item.get("sha256")):
            raise ValueError
        frozen_ref = item.get("frozen_ref")
        if not isinstance(frozen_ref, str) or not frozen_ref.replace("\\", "/").startswith("public/media/"):
            raise ValueError
        _safe_version_rel(frozen_ref.replace("\\", "/"))
        if item.get("kind") not in ("background", "video", "image"):
            raise ValueError


def _validate_background_fingerprints(background_fp, version):
    if not isinstance(background_fp, dict):
        raise ValueError
    props_bg = _as_dict(version.get("props")).get("background")
    if not isinstance(props_bg, dict):
        raise ValueError
    src = props_bg.get("src")
    if not isinstance(src, str) or not src.startswith("media/"):
        raise ValueError
    if not _sha256(background_fp.get("sha256")):
        raise ValueError
    if background_fp.get("sha256") != _payload_hash(props_bg):
        raise ValueError
    _validate_background_assets(background_fp.get("assets"))


def _validate_complete_artifact(artifact, version):
    if not isinstance(artifact, dict):
        raise ValueError
    relative_artifact(artifact.get("path"))
    if not _sha256(artifact.get("sha256")) or artifact.get("verified") is not True:
        raise ValueError
    if artifact.get("width") != DEFAULT_WIDTH or artifact.get("height") != DEFAULT_HEIGHT:
        raise ValueError
    if not _is_number(artifact.get("fps")) or float(artifact["fps"]) != float(version["profile"]["fps"]):
        raise ValueError
    if artifact.get("codec") not in ("h264", "avc1") or artifact.get("pix_fmt") != "yuv420p":
        raise ValueError
    _validate_artifact_duration(artifact, version)
    _validate_artifact_audio_fields(artifact, _version_has_effects(version))


def _validate_artifact_audio_fields(artifact, has_effects):
    audio_codec = artifact.get("audio_codec")
    audio_streams = artifact.get("audio_streams")
    if has_effects:
        if audio_codec != "aac" or audio_streams != 1:
            raise ValueError
        if artifact.get("color_space") != COLOR_SPACE:
            raise ValueError
        return
    if (audio_codec is not None or audio_streams is not None) and (audio_codec != "aac" or audio_streams != 1):
        raise ValueError


def _validate_estimated_timing(timing, fps):
    if timing.get("start_s") is not None or timing.get("end_s") is not None:
        raise ValueError
    if timing.get("start_frame") is not None or timing.get("end_frame") is not None:
        raise ValueError
    if not _is_number(timing.get("duration_s")) or timing["duration_s"] <= 0:
        raise ValueError
    if seconds_to_frame(timing["duration_s"], fps) != timing["duration_in_frames"]:
        raise ValueError


def _validate_explicit_timing(timing, fps):
    if not _is_number(timing.get("start_s")) or not _is_number(timing.get("end_s")):
        raise ValueError
    if timing["end_s"] <= timing["start_s"]:
        raise ValueError
    if not _is_int(timing.get("start_frame")) or not _is_int(timing.get("end_frame")):
        raise ValueError
    if timing["start_frame"] != seconds_to_frame(timing["start_s"], fps):
        raise ValueError
    if timing["end_frame"] != seconds_to_frame(timing["end_s"], fps):
        raise ValueError
    if timing["duration_in_frames"] != max(1, timing["end_frame"] - timing["start_frame"]):
        raise ValueError


def _validate_timing(timing, fps):
    if not isinstance(timing, dict) or timing.get("basis") not in ("estimated", "explicit"):
        raise ValueError
    if not _is_int(timing.get("duration_in_frames")) or timing["duration_in_frames"] < 1:
        raise ValueError
    if timing["basis"] == "estimated":
        _validate_estimated_timing(timing, fps)
        return
    _validate_explicit_timing(timing, fps)


def graphics_status(data, root=None):
    graphics = data.get("graphics")
    if not isinstance(graphics, dict):
        return {
            "occurrences": 0,
            "pending": 0,
            "complete_versions": 0,
            "profile": None,
            "items": [],
            "requests": [],
            "delivery": {
                "present": False,
                "undelivered": 0,
                "pending_action": 0,
                "delivered": 0,
                "reasons": [],
            },
        }
    versions = graphics.get("versions") or {}
    complete = sum(
        1 for version in versions.values() if isinstance(version, dict) and version.get("status") == "complete"
    )
    items = []
    pending = 0
    for occ in (graphics.get("occurrences") or {}).values():
        if not isinstance(occ, dict):
            continue
        version = versions.get(occ.get("current_version") or "")
        frozen = version.get("assignment") if isinstance(version, dict) else None
        complete_current = bool(isinstance(version, dict) and version.get("status") == "complete")
        changed = complete_current and _assignment_changed(frozen, occ)
        ready = complete_current and not changed
        if not ready:
            pending += 1
        if isinstance(version, dict) and root is not None:
            readiness = version_readiness(root, version, occ, data.get("project_id"), data.get("items"), data=data)
        elif isinstance(version, dict):
            readiness = {
                "complete": complete_current,
                "reviewable": False,
                "approved": False,
                "deliverable": False,
                "assignment_drift": changed,
                "reasons": ["status_without_project_root"] if complete_current else ["incomplete_version"],
            }
        else:
            extra, _required, _align, _bg = (
                _facts_audio_reasons(root, occ, data=data) if root is not None else ([], False, False, False)
            )
            readiness = {
                "complete": False,
                "reviewable": False,
                "approved": False,
                "deliverable": False,
                "assignment_drift": changed,
                "reasons": _unique(["incomplete_version", *extra]),
            }
        item = {
            "occurrence_id": occ.get("occurrence_id"),
            "scene_id": occ.get("scene_id"),
            "template": occ.get("template"),
            "chapter_id": occ.get("chapter_id"),
            "timing_basis": (occ.get("timing") or {}).get("basis"),
            "current_version": occ.get("current_version"),
            "ready": ready,
            "complete": readiness["complete"],
            "reviewable": readiness["reviewable"],
            "approved": readiness["approved"],
            "deliverable": readiness["deliverable"],
            "reasons": readiness["reasons"],
        }
        _add_status_optional_records(item, occ, version, root)
        from .graphics_continuation import work_status

        item["work"] = work_status(root, occ)
        if "timeline" in occ:
            item["timeline"] = copy.deepcopy(occ["timeline"])
        items.append(item)
    return {
        "occurrences": len(graphics.get("occurrences") or {}),
        "pending": pending,
        "complete_versions": complete,
        "profile": graphics.get("profile"),
        "current_style_revision": graphics.get("current_style_revision"),
        "items": items,
        "requests": _public_requests(graphics),
        "delivery": graphics_delivery_progress(data, root),
    }


def _public_facts(facts):
    if not isinstance(facts, dict):
        return {}
    values = []
    for item in facts.get("values") or []:
        if not isinstance(item, dict):
            continue
        values.append(
            {
                "id": item.get("id"),
                "value": item.get("value"),
                "unit": item.get("unit"),
                "definition": item.get("definition"),
                "geography": item.get("geography"),
                "reference_date": item.get("reference_date"),
                "source_ids": list(item.get("source_ids") or []),
            }
        )
    sources = []
    for item in facts.get("sources") or []:
        if not isinstance(item, dict):
            continue
        sources.append(
            {
                "id": item.get("id"),
                "url": item.get("url"),
                "title": item.get("title"),
                "reference_date": item.get("reference_date"),
                "terms_url": item.get("terms_url"),
                "conditions": item.get("conditions"),
                "rendered_use": item.get("rendered_use"),
                "raw_redistribution": item.get("raw_redistribution"),
                "kind": item.get("kind"),
                "data_ref": item.get("data_ref"),
                "sha256": item.get("sha256"),
            }
        )
    conflicts = []
    for item in facts.get("conflicts") or []:
        if not isinstance(item, dict):
            continue
        decision = item.get("decision")
        public_decision = None
        if isinstance(decision, dict):
            public_decision = {
                "choice": decision.get("choice"),
                "by": decision.get("by"),
                "statement": decision.get("statement"),
                "at": decision.get("at"),
            }
        conflicts.append(
            {
                "id": item.get("id"),
                "original_narration": item.get("original_narration"),
                "explanation": item.get("explanation"),
                "source_ids": list(item.get("source_ids") or []),
                "proposed_correction": item.get("proposed_correction"),
                "decision": public_decision,
            }
        )
    return {
        "schema_version": facts.get("schema_version"),
        "required": facts.get("required"),
        "values": values,
        "sources": sources,
        "conflicts": conflicts,
    }


def _public_vo_preview(preview):
    if not isinstance(preview, dict):
        return {}
    public = {
        "kind": preview.get("kind"),
        "source_start_s": preview.get("source_start_s"),
        "source_end_s": preview.get("source_end_s"),
        "duration_s": preview.get("duration_s"),
        "gain": preview.get("gain"),
    }
    ref = preview.get("ref")
    if isinstance(ref, str) and ref.startswith("previews/"):
        public["ref"] = ref
        public["sha256"] = preview.get("sha256")
    return public


def _public_audio(audio, version=None):
    if not isinstance(audio, dict):
        return {}
    effects = []
    for item in audio.get("effects") or []:
        if not isinstance(item, dict):
            continue
        effects.append(
            {
                "id": item.get("id"),
                "ref": item.get("ref"),
                "sha256": item.get("sha256"),
                "source_url": item.get("source_url"),
                "terms_url": item.get("terms_url"),
                "license": item.get("license"),
                "conditions": item.get("conditions"),
                "rendered_use": item.get("rendered_use"),
                "raw_redistribution": item.get("raw_redistribution"),
                "start_frame": item.get("start_frame"),
                "source_start_s": item.get("source_start_s"),
                "duration_s": item.get("duration_s"),
                "gain": item.get("gain"),
            }
        )
    public = {"schema_version": audio.get("schema_version"), "effects": effects}
    vo = audio.get("vo") if isinstance(audio.get("vo"), dict) else None
    preview = None
    if isinstance(version, dict) and isinstance(version.get("vo_preview"), dict):
        preview = _public_vo_preview(version.get("vo_preview"))
    if vo is not None:
        public["vo"] = {
            "kind": vo.get("kind"),
            "source_start_s": vo.get("source_start_s"),
            "source_end_s": vo.get("source_end_s"),
            "gain": vo.get("gain"),
            "present": True,
        }
        if preview:
            public["vo_preview"] = preview
    elif preview:
        public["vo_preview"] = preview
    return public


def _public_background(background, version=None):
    if not isinstance(background, dict):
        return {}
    public = {
        "schema_version": background.get("schema_version"),
        "candidate_id": background.get("candidate_id"),
        "ref": background.get("ref"),
        "kind": background.get("kind"),
        "sha256": background.get("sha256"),
        "bytes": background.get("bytes"),
        "width": background.get("width"),
        "height": background.get("height"),
        "fit": background.get("fit"),
        "source_start_s": background.get("source_start_s"),
        "source_end_s": background.get("source_end_s"),
        "representation_source_start_s": background.get("representation_source_start_s"),
        "local_start_s": background.get("local_start_s"),
        "local_end_s": background.get("local_end_s"),
        "duration_s": background.get("duration_s") or background.get("local_duration_s"),
        "fps": background.get("fps") or background.get("local_fps"),
        "provider": background.get("provider"),
        "source_id": background.get("source_id"),
        "source_url": background.get("source_url"),
        "suitability": background.get("suitability"),
        "material_use": background.get("material_use"),
    }
    frozen = None
    if isinstance(version, dict):
        assets = _as_dict(_as_dict(version.get("fingerprints")).get("background")).get("assets") or []
        if assets and isinstance(assets[0], dict):
            frozen = assets[0]
    if isinstance(frozen, dict):
        public["frozen_ref"] = frozen.get("frozen_ref")
        public["frozen_sha256"] = frozen.get("sha256")
    return {key: value for key, value in public.items() if value is not None}


def _add_status_optional_records(item, occ, version, root):
    if isinstance(occ.get("facts"), dict):
        item["facts"] = _public_facts(occ.get("facts"))
    if isinstance(occ.get("audio"), dict):
        item["audio"] = _public_audio(occ.get("audio"), version)
    if isinstance(occ.get("background"), dict):
        item["background"] = _public_background(occ.get("background"), version)
    if isinstance(occ.get("alignment"), dict):
        item["alignment"] = _public_alignment(occ.get("alignment"), occ, root=root)
    if isinstance(occ.get("alignment_group"), dict):
        item["alignment_group"] = copy.deepcopy(occ.get("alignment_group"))


def _public_preview_payload(preview, record, item, *, root=None):
    if (
        not isinstance(preview, dict)
        or not isinstance(record, dict)
        or not isinstance(item, dict)
        or preview.get("identity_sha256") != _alignment_preview_identity(record, item)
    ):
        return None
    identity_sha = _alignment_preview_identity(record, item)
    if preview.get("error"):
        error = preview.get("error")
        return {"error": error} if isinstance(error, str) and error else None
    ref = preview.get("ref")
    if not isinstance(ref, str) or not ref.startswith("previews/"):
        return {"error": "missing_preview"}
    fps = record.get("fps")
    expected_duration = None
    start_s, end_s = item.get("start_s"), item.get("end_s")
    if _is_number(start_s) and _is_number(end_s):
        expected_duration = end_s - start_s
    if root is not None:
        try:
            dest = _confine_existing(root, ref)
        except (OSError, ValueError):
            return {"error": "missing_preview"}
        if not _preview_same_context(preview, identity_sha, dest, expected_duration, fps):
            return {"error": "missing_preview"}
    exposed = {"ref": ref, "sha256": preview.get("sha256")}
    if preview.get("duration_s") is not None:
        exposed["duration_s"] = preview.get("duration_s")
    return exposed


def _public_alignment_candidate(item, previews=None, record=None, *, root=None):
    if not isinstance(item, dict):
        return {}
    cand_id = item.get("id")
    word_start = item.get("word_start")
    if word_start is None:
        word_start = item.get("word_start_index")
    word_end = item.get("word_end")
    if word_end is None:
        word_end = item.get("word_end_index")
    textual = item.get("textual_evidence")
    anchor = item.get("anchor_evidence")
    order_evidence = item.get("order_evidence")
    public = {
        "id": cand_id,
        "start_s": item.get("start_s"),
        "end_s": item.get("end_s"),
        "recognized_text": item.get("recognized_text") or item.get("text"),
        "word_start": word_start,
        "word_end": word_end,
        "score": item.get("score"),
        "textual_evidence": textual,
        "anchor_evidence": anchor,
        "order_evidence": order_evidence,
    }
    if textual is not None or anchor is not None or order_evidence is not None:
        public["evidence"] = {
            "textual": textual,
            "anchor": anchor,
            "order": order_evidence,
        }
    elif item.get("evidence") is not None:
        public["evidence"] = item.get("evidence")
    preview = None
    if isinstance(previews, dict) and cand_id in previews:
        preview = _public_preview_payload(previews.get(cand_id), record, item, root=root)
    if isinstance(preview, dict):
        if preview.get("error"):
            public["preview_error"] = preview.get("error")
        else:
            public["preview"] = preview
    return {key: value for key, value in public.items() if value is not None}


def _public_alignment(alignment, occurrence=None, *, root=None):
    if not isinstance(alignment, dict):
        return {}
    previews = occurrence.get("alignment_previews") if isinstance(occurrence, dict) else None
    decision = alignment.get("decision")
    public_decision = None
    if isinstance(decision, dict):
        public_decision = {
            "by": decision.get("by"),
            "statement": decision.get("statement"),
            "at": decision.get("at"),
            "candidate_id": decision.get("candidate_id") or alignment.get("selected_candidate_id"),
            "input_fingerprint": decision.get("input_fingerprint"),
        }
    candidates = [
        _public_alignment_candidate(item, previews, alignment, root=root)
        for item in (alignment.get("candidates") or [])
        if isinstance(item, dict)
    ]
    override = None
    if alignment.get("selected_candidate_id") is None and isinstance(alignment.get("timing"), dict):
        timing = _as_dict(alignment.get("timing"))
        override_item = {"id": "override", "start_s": timing.get("start_s"), "end_s": timing.get("end_s")}
        stored = previews.get("override") if isinstance(previews, dict) else None
        override = _public_preview_payload(stored, alignment, override_item, root=root)
    return {
        "schema_version": alignment.get("schema_version"),
        "state": alignment.get("state"),
        "original_text": alignment.get("original_text"),
        "analysis_id": alignment.get("analysis_id"),
        "recording_id": alignment.get("recording_id"),
        "recording_sha256": alignment.get("recording_sha256"),
        "recording_duration_s": alignment.get("recording_duration_s"),
        "transcript_sha256": alignment.get("transcript_sha256"),
        "scenario_sha256": alignment.get("scenario_sha256"),
        "order": alignment.get("order"),
        "input_fingerprint": alignment.get("input_fingerprint"),
        "selected_candidate_id": alignment.get("selected_candidate_id"),
        "timing": alignment.get("timing"),
        "decision": public_decision,
        "candidates": candidates,
        "override_preview": override,
        "fps": alignment.get("fps"),
    }


RUNTIME_HASH_KEYS = (
    "kind",
    "worker_sha256",
    "package_lock_sha256",
    "package_json_sha256",
    "node_sha256",
    "browser_sha256",
)
SNAPSHOT_FILES = ("assignment.json", "style.json", "props.json", "fingerprints.json")


def graphics_content_payload(version):
    fingerprints = _as_dict(version.get("fingerprints"))
    runtime = _as_dict(fingerprints.get("runtime"))
    artifact = _as_dict(version.get("artifact"))
    payload = {
        "id": version.get("id"),
        "occurrence_id": version.get("occurrence_id"),
        "scene_id": version.get("scene_id"),
        "assignment": version.get("assignment"),
        "style": version.get("style"),
        "props": version.get("props"),
        "profile": version.get("profile"),
        "timing": version.get("timing"),
        "artifact_sha256": artifact.get("sha256"),
        "source": fingerprints.get("source"),
        "inputs": fingerprints.get("inputs"),
        "fonts": fingerprints.get("fonts"),
        "runtime": {key: runtime.get(key) for key in RUNTIME_HASH_KEYS},
        "assignment_sha256": fingerprints.get("assignment_sha256"),
        "style_sha256": fingerprints.get("style_sha256"),
        "props_sha256": fingerprints.get("props_sha256"),
    }
    for key in ("audio", "facts", "background", "alignment"):
        value = fingerprints.get(key)
        if value is not None:
            payload[key] = value
    preview = version.get("vo_preview")
    if isinstance(preview, dict):
        public_preview = _public_vo_preview(preview)
        if public_preview:
            payload["vo_preview"] = public_preview
    return payload


def graphics_content_sha256(version):
    return _payload_hash(graphics_content_payload(version))


def graphics_review_epoch(version):
    approval = _as_dict(version.get("approval"))
    return hashlib.sha256(
        json.dumps(
            [
                {key: approval.get(key) for key in ("status", "by", "at", "content_sha256")},
                version.get("review"),
                version.get("id"),
                graphics_content_sha256(version),
            ],
            sort_keys=True,
            ensure_ascii=False,
        ).encode()
    ).hexdigest()


def _version_dir(root, scene_id, version_id):
    return Path(root) / "graphics" / scene_id / version_id


def _declared_source_files(fingerprints):
    source = fingerprints.get("source")
    if not isinstance(source, dict):
        return []
    declared = []
    names = list(TEMPLATE_FILES)
    for name in source:
        if name not in names:
            names.append(name)
    for name in names:
        digest_value = source.get(name)
        if _sha256(digest_value):
            declared.append(("source/" + name, digest_value))
    return declared


def _declared_audio_files(fingerprints):
    audio = fingerprints.get("audio")
    if not isinstance(audio, dict):
        return []
    declared = []
    for item in audio.get("assets") or []:
        if not isinstance(item, dict):
            continue
        frozen_ref = item.get("frozen_ref")
        digest_value = item.get("sha256")
        if isinstance(frozen_ref, str) and _sha256(digest_value):
            declared.append((frozen_ref, digest_value))
    return declared


def _declared_font_files(fingerprints):
    fonts = fingerprints.get("fonts")
    if not isinstance(fonts, dict):
        return []
    remotion = _as_dict(fingerprints.get("runtime")).get("kind") == "remotion"
    declared = []
    for name, digest_value in fonts.items():
        if not isinstance(name, str) or not _sha256(digest_value):
            continue
        declared.append(("inputs/fonts/" + name, digest_value))
        if remotion:
            declared.append(("public/fonts/" + name, digest_value))
    return declared


def _declared_input_files(fingerprints):
    inputs = fingerprints.get("inputs")
    if not isinstance(inputs, dict):
        return []
    declared = []
    for spec in inputs.values():
        if not isinstance(spec, dict):
            continue
        frozen = spec.get("frozen")
        digest_value = spec.get("sha256")
        if isinstance(frozen, str) and _sha256(digest_value):
            declared.append((frozen, digest_value))
    return declared


def _declared_runtime_files(fingerprints):
    runtime = _as_dict(fingerprints.get("runtime"))
    declared = []
    worker_name = Path(str(runtime.get("worker") or "")).name
    worker_hash = runtime.get("worker_sha256")
    if worker_name and _sha256(worker_hash):
        declared.append(("inputs/" + worker_name, worker_hash))
    if runtime.get("kind") != "remotion":
        return declared
    package_json = runtime.get("package_json_sha256")
    package_lock = runtime.get("package_lock_sha256")
    if _sha256(package_json):
        declared.append(("inputs/package.json", package_json))
    if _sha256(package_lock):
        declared.append(("inputs/package-lock.json", package_lock))
    return declared


def _declared_background_files(fingerprints):
    background = fingerprints.get("background")
    if not isinstance(background, dict):
        return []
    declared = []
    for item in background.get("assets") or []:
        if not isinstance(item, dict):
            continue
        frozen_ref = item.get("frozen_ref")
        digest_value = item.get("sha256")
        posix = frozen_ref.replace("\\", "/") if isinstance(frozen_ref, str) else ""
        if posix.startswith("public/media/") and _sha256(digest_value):
            declared.append((posix, digest_value))
    return declared


def _declared_fingerprint_files(version):
    fingerprints = _as_dict(version.get("fingerprints"))
    declared = []
    declared.extend(_declared_source_files(fingerprints))
    declared.extend(_declared_font_files(fingerprints))
    declared.extend(_declared_input_files(fingerprints))
    declared.extend(_declared_runtime_files(fingerprints))
    declared.extend(_declared_audio_files(fingerprints))
    declared.extend(_declared_background_files(fingerprints))
    return declared


def _safe_version_rel(rel):
    if not isinstance(rel, str) or not rel or _CONTROL.search(rel):
        raise ValueError("missing_declared_file")
    if "\\" in rel or rel.startswith(("/", "~")) or ":" in rel:
        raise ValueError("missing_declared_file")
    if _ILLEGAL_PATH.search(rel):
        raise ValueError("missing_declared_file")
    path = Path(rel)
    if path.is_absolute() or ".." in path.parts or "node_modules" in path.parts:
        raise ValueError("missing_declared_file")
    if any(_WINDOWS_RESERVED.fullmatch(part.split(".")[0]) for part in path.parts):
        raise ValueError("missing_declared_file")
    return rel


def _confine_declared_file(version_dir, rel):
    rel = _safe_version_rel(rel)
    path = version_dir.joinpath(*rel.split("/"))
    planned = _confine_planned(version_dir, path)
    if planned.is_symlink() or not planned.is_file():
        raise ValueError("missing_declared_file")
    return planned


def _read_snapshot(path):
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError) as exc:
        raise ValueError("changed_declared_file") from exc
    return payload


def _file_digest(path):
    try:
        return digest(path)
    except OSError as exc:
        raise ValueError("missing_declared_file") from exc


def _verify_payload_hashes(version):
    fingerprints = _as_dict(version.get("fingerprints"))
    reasons = []
    if fingerprints.get("assignment_sha256") != _payload_hash(version.get("assignment")):
        reasons.append("changed_declared_file")
    if fingerprints.get("style_sha256") != _payload_hash(version.get("style")):
        reasons.append("changed_declared_file")
    if fingerprints.get("props_sha256") != _payload_hash(version.get("props")):
        reasons.append("changed_declared_file")
    return reasons


def _verify_declared_paths(version_dir, version):
    reasons = []
    for rel, expected in _declared_fingerprint_files(version):
        try:
            path = _confine_declared_file(version_dir, rel)
            actual = _file_digest(path)
        except ValueError:
            reasons.append("missing_declared_file")
            continue
        if actual != expected:
            reasons.append("changed_declared_file")
    return reasons


def _verify_snapshots(version_dir, version):
    recorded = {
        "assignment.json": version.get("assignment"),
        "style.json": version.get("style"),
        "props.json": version.get("props"),
        "fingerprints.json": _as_dict(version.get("fingerprints")),
    }
    reasons = []
    for name in SNAPSHOT_FILES:
        try:
            path = _confine_declared_file(version_dir, name)
            payload = _read_snapshot(path)
        except ValueError as exc:
            reasons.append(
                str(exc) if str(exc) in ("missing_declared_file", "changed_declared_file") else "missing_declared_file"
            )
            continue
        if payload != recorded[name]:
            reasons.append("changed_declared_file")
    return reasons


def _job_rel_suffix(value, *parts):
    if not isinstance(value, str) or not value or _CONTROL.search(value):
        return False
    normalized = value.replace("\\", "/").rstrip("/")
    expected = "/".join(parts)
    return normalized.endswith("/" + expected)


def _job_matches_version(job, version):
    profile = _as_dict(version.get("profile"))
    timing = _as_dict(version.get("timing"))
    expected_audio = {"mode": "effects", "codec": "aac"} if _version_has_effects(version) else None
    return (
        job.get("composition") == version.get("composition")
        and job.get("width") == profile.get("width")
        and job.get("height") == profile.get("height")
        and job.get("fps") == profile.get("fps")
        and job.get("durationInFrames") == timing.get("duration_in_frames")
        and job.get("props") == version.get("props")
        and job.get("audio") == expected_audio
        and _job_rel_suffix(job.get("entry"), "source", "index.jsx")
        and _job_rel_suffix(job.get("publicDir"), "public")
    )


def _verify_frozen_job(version_dir, version):
    try:
        job = _read_snapshot(_confine_declared_file(version_dir, "job.json"))
        _validate_job_encoding(job)
    except ValueError as exc:
        reason = str(exc)
        return [reason if reason in ("missing_declared_file", "changed_declared_file") else "changed_declared_file"]
    if _job_matches_version(job, version):
        return []
    return ["changed_declared_file"]


def _verify_previews(root, version_dir, version):
    artifact = _as_dict(version.get("artifact"))
    expected = artifact.get("sha256")
    reasons = []
    served = None
    try:
        preview = _confine_existing(root, artifact.get("path"))
        served = _file_digest(preview)
    except ValueError:
        reasons.append("missing_artifact")
    if served is not None and served != expected:
        reasons.append("changed_declared_file")
    try:
        frozen = _file_digest(_confine_declared_file(version_dir, "preview.mp4"))
    except ValueError:
        reasons.append("missing_artifact")
        return reasons
    if frozen != expected or (served is not None and frozen != served):
        reasons.append("changed_declared_file")
    return reasons


def _verify_vo_preview(root, version):
    preview = version.get("vo_preview")
    if not isinstance(preview, dict):
        return []
    rel = preview.get("ref")
    expected = preview.get("sha256")
    if not isinstance(rel, str) or not rel.startswith("previews/") or not _sha256(expected):
        return ["missing_artifact"]
    try:
        path = _confine_existing(root, rel)
        actual = _file_digest(path)
    except ValueError:
        return ["missing_artifact"]
    if actual != expected:
        return ["changed_declared_file"]
    return []


def verify_version_integrity(root, version):
    """Hash declared frozen files and both previews; never walk inputs/node_modules."""
    if not isinstance(version, dict) or version.get("status") != "complete":
        return False, ["incomplete_version"]
    scene_id = version.get("scene_id")
    version_id = version.get("id")
    if not _valid_id(scene_id) or not isinstance(version_id, str) or not VERSION_RE.fullmatch(version_id):
        return False, ["incomplete_version"]
    try:
        resolved_dir = _confine_planned(root, _version_dir(root, scene_id, version_id))
    except ValueError:
        return False, ["missing_declared_file"]
    if not resolved_dir.is_dir():
        return False, ["missing_declared_file"]
    reasons = []
    reasons.extend(_verify_payload_hashes(version))
    reasons.extend(_verify_declared_paths(resolved_dir, version))
    reasons.extend(_verify_snapshots(resolved_dir, version))
    reasons.extend(_verify_frozen_job(resolved_dir, version))
    reasons.extend(_verify_previews(root, resolved_dir, version))
    reasons.extend(_verify_vo_preview(root, version))
    unique = _unique(reasons)
    return not unique, unique


def _approval_blockers(version, project_id):
    reasons = []
    review = _as_dict(version.get("review"))
    if review.get("state") == "changes":
        reasons.append("changes_requested")
    approval = version.get("approval") if isinstance(version.get("approval"), dict) else None
    if approval is None or approval.get("status") != "approved":
        reasons.append("missing_approval")
        return reasons
    if not _bound_project_id(approval.get("project_id")):
        reasons.append("missing_approval")
        return reasons
    if _bound_project_id(project_id) and approval.get("project_id") != project_id:
        reasons.append("wrong_project")
    if approval.get("content_sha256") != graphics_content_sha256(version):
        reasons.append("stale_approval")
    return reasons


def _record_from_occurrence_or_frozen(occurrence, frozen, key):
    if isinstance(occurrence, dict) and occurrence.get(key) is not None:
        return occurrence.get(key)
    if isinstance(frozen, dict) and frozen.get(key) is not None:
        return frozen.get(key)
    return None


def _facts_conflict_blocks_delivery(record, readiness_reasons):
    if not isinstance(record, dict):
        return False
    for conflict in record.get("conflicts") or []:
        if not isinstance(conflict, dict):
            continue
        decision = conflict.get("decision")
        if not isinstance(decision, dict):
            return True
        if decision.get("choice") not in ("accept_correction", "keep_scenario"):
            return True
    for reason in readiness_reasons:
        if isinstance(reason, str) and reason.startswith("Facts conflict ") and "stale evidence" in reason:
            return True
    return False


def _graphics_profile(version=None, data=None):
    if isinstance(version, dict) and isinstance(version.get("profile"), dict):
        return version.get("profile")
    if isinstance(data, dict):
        graphics = data.get("graphics")
        if isinstance(graphics, dict) and isinstance(graphics.get("profile"), dict):
            return graphics.get("profile")
    return None


def _current_alignment_group_order(occurrence, data=None):
    group = occurrence.get("alignment_group") if isinstance(occurrence, dict) else None
    ids = group.get("occurrence_ids") if isinstance(group, dict) else None
    if not isinstance(ids, list) or not ids:
        return None
    occ_id = occurrence.get("occurrence_id")
    try:
        index = list(ids).index(occ_id)
    except ValueError:
        return None
    graphics = data.get("graphics") if isinstance(data, dict) else None
    occurrences = graphics.get("occurrences") if isinstance(graphics, dict) else None
    if not isinstance(occurrences, dict):
        return index
    expected = list(ids)
    for member_id in expected:
        member = occurrences.get(member_id)
        if not isinstance(member, dict):
            return None
        other = member.get("alignment_group") if isinstance(member.get("alignment_group"), dict) else None
        other_ids = other.get("occurrence_ids") if isinstance(other, dict) else None
        if list(other_ids or []) != expected:
            return None
    return index


def _bind_alignment_match_group(graphics, occurrence_ids):
    group_ids = list(occurrence_ids)
    group = {"occurrence_ids": group_ids}
    members = set(group_ids)
    occurrences = graphics.get("occurrences") if isinstance(graphics, dict) else {}
    if not isinstance(occurrences, dict):
        return
    for occ_id, occ in occurrences.items():
        if not isinstance(occ, dict):
            continue
        if occ_id in members:
            occ["alignment_group"] = copy.deepcopy(group)
            continue
        old = occ.get("alignment_group") if isinstance(occ.get("alignment_group"), dict) else None
        old_ids = old.get("occurrence_ids") if old else None
        if isinstance(old_ids, list) and members.intersection(old_ids):
            occ.pop("alignment_group", None)


def _passage_from_occurrence(occurrence, data=None):
    if not isinstance(occurrence, dict):
        return None
    return {
        "occurrence_id": occurrence.get("occurrence_id"),
        "narration": occurrence.get("narration"),
        "chapter_context": occurrence.get("chapter_context"),
        "anchors": occurrence.get("anchors") or [],
        "purpose": occurrence.get("purpose"),
        "order": _current_alignment_group_order(occurrence, data),
    }


def _result_artifact_reasons(payload, result):
    reasons = []
    if not isinstance(payload, dict) or not isinstance(result, dict):
        return ["changed_result_artifact"]
    if "confidence" in payload or "confidence" in result:
        reasons.append("incomplete_transcript")
    saved_timing = result.get("timing_resolved")
    payload_timing = payload.get("timing_resolved")
    if type(saved_timing) is not bool or type(payload_timing) is not bool:
        reasons.append("incomplete_transcript")
    elif payload_timing is not saved_timing:
        reasons.append("changed_result_artifact")
    extra_sha = payload.get("artifact_sha256")
    if extra_sha is not None and extra_sha != result.get("artifact_sha256"):
        reasons.append("changed_result_artifact")
    if payload.get("transcript") != result.get("transcript") or payload.get("words") != result.get("words"):
        reasons.append("changed_result_artifact")
    return _unique(reasons)


def _read_only_result_artifact_reasons(root, result):
    from .narration import RESULT_PREFIX

    reasons = []
    try:
        artifact = _confine_existing(root, result.get("artifact"), (RESULT_PREFIX,))
    except (OSError, ValueError):
        reasons.append("missing_result_artifact")
        artifact = None
    if artifact is not None:
        try:
            actual = digest(artifact)
        except OSError:
            reasons.append("missing_result_artifact")
            artifact = None
        else:
            if actual != result.get("artifact_sha256"):
                reasons.append("changed_result_artifact")
                artifact = None
    if artifact is not None:
        try:
            payload = json.loads(artifact.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError):
            reasons.append("changed_result_artifact")
        else:
            reasons.extend(_result_artifact_reasons(payload, result))
    return reasons


def _read_only_alignment_artifacts(root, analysis, recording):
    reasons = []
    if root is None:
        return reasons
    from .narration import PRIVATE_AUDIO_PREFIX

    result = analysis.get("result") if isinstance(analysis, dict) else None
    if not isinstance(result, dict):
        reasons.append("incomplete_transcript")
        return reasons
    if type(result.get("timing_resolved")) is not bool:
        reasons.append("incomplete_transcript")
    reasons.extend(_read_only_result_artifact_reasons(root, result))
    if not isinstance(recording, dict):
        reasons.append("missing_recording")
        return _unique(reasons)
    try:
        snapshot = _confine_existing(root, recording.get("snapshot"), (PRIVATE_AUDIO_PREFIX,))
    except (OSError, ValueError):
        reasons.append("missing_recording")
        return _unique(reasons)
    try:
        if digest(snapshot) != recording.get("sha256"):
            reasons.append("changed_recording_bytes")
    except OSError:
        reasons.append("missing_recording")
    return _unique(reasons)


def _background_reasons(root, occurrence, frozen, version, items, profile):  # noqa: PLR0913, PLR0917 - Keep original/current version, candidate rights and composition profile distinct.
    record = _record_from_occurrence_or_frozen(occurrence, frozen, "background")
    if record is None:
        return [], False
    try:
        from .graphics_media import background_readiness
    except ImportError:
        return ["background_module_missing"], True
    if not isinstance(profile, dict):
        return ["background_not_ready"], True
    timing = None
    if isinstance(version, dict) and isinstance(version.get("timing"), dict):
        timing = version.get("timing")
    elif isinstance(occurrence, dict):
        timing = occurrence.get("timing")
    try:
        status = background_readiness(root, record, profile, timing, items=items)
    except (ValueError, TypeError):
        return ["background_not_ready"], True
    unreadiness = status.get("reasons") or []
    if status.get("ready"):
        return unreadiness, False
    return [*unreadiness, "background_not_ready"], True


def _alignment_readiness_inputs(root, occurrence, record, data=None):
    passage = _passage_from_occurrence(occurrence, data)
    analysis = None
    recording = None
    file_reasons = []
    narration = data.get("narration") if isinstance(data, dict) else None
    analysis_id = record.get("analysis_id") if isinstance(record, dict) else None
    recording_id = record.get("recording_id") if isinstance(record, dict) else None
    if not isinstance(narration, dict):
        return None, None, passage, ["incomplete_transcript"]
    analyses = _as_dict(narration.get("analyses"))
    recordings = _as_dict(narration.get("recordings"))
    stored = analyses.get(analysis_id) if analysis_id else None
    recording = recordings.get(recording_id) if recording_id else None
    if isinstance(stored, dict):
        result = stored.get("result") if isinstance(stored.get("result"), dict) else None
        analysis = {"id": stored.get("id") or analysis_id, "result": result}
        file_reasons = _read_only_alignment_artifacts(root, analysis, recording)
    else:
        file_reasons = ["incomplete_transcript"]
    if isinstance(recording, dict) and recording.get("id") is None and recording_id:
        recording = {**recording, "id": recording_id}
    return analysis, recording, passage, file_reasons


def _alignment_reasons(root, occurrence, frozen, profile, data=None):
    record = _record_from_occurrence_or_frozen(occurrence, frozen, "alignment")
    if record is None:
        return [], False
    try:
        from .narration_alignment import alignment_readiness
    except ImportError:
        return ["alignment_module_missing"], True
    analysis, recording, passage, file_reasons = _alignment_readiness_inputs(root, occurrence, record, data)
    unreadiness = list(file_reasons)
    if (
        not isinstance(profile, dict)
        or not isinstance(analysis, dict)
        or not isinstance(recording, dict)
        or not isinstance(passage, dict)
    ):
        unreadiness.extend(["incomplete_transcript"] if "incomplete_transcript" not in unreadiness else [])
        return _unique([*unreadiness, "unresolved_alignment"]), True
    try:
        status = alignment_readiness(record, analysis=analysis, recording=recording, passage=passage, profile=profile)
    except (ValueError, TypeError):
        return _unique([*unreadiness, "unresolved_alignment"]), True
    unreadiness.extend(status.get("reasons") or [])
    unreadiness = _unique(unreadiness)
    resolved = status.get("resolved") is True and not file_reasons
    if resolved and not unreadiness:
        return [], False
    return [*unreadiness, "unresolved_alignment"], True


def _full_recording_vo_clock_mismatch(audio, timing):
    vo = audio.get("vo") if isinstance(audio, dict) else None
    if not isinstance(vo, dict) or vo.get("kind") != "full_recording":
        return False
    if not isinstance(timing, dict):
        return True
    start_s = timing.get("start_s")
    end_s = timing.get("end_s")
    return vo.get("source_start_s") != start_s or vo.get("source_end_s") != end_s


def _audio_duration_repair_reasons(occurrence, frozen=None):
    audio = _record_from_occurrence_or_frozen(occurrence, frozen, "audio")
    timing = occurrence.get("timing") if isinstance(occurrence, dict) else None
    if not isinstance(audio, dict) or not isinstance(timing, dict):
        return []
    duration = timing.get("duration_in_frames")
    if not _is_int(duration) or duration < 1:
        return []
    if _full_recording_vo_clock_mismatch(audio, timing):
        return ["audio_duration_repair_required", "audio_not_ready"]
    try:
        from .graphics_audio import validate_audio
    except ImportError:
        return (
            ["audio_duration_repair_required", "audio_not_ready"] if audio.get("duration_in_frames") != duration else []
        )
    probe = copy.deepcopy(audio)
    probe["duration_in_frames"] = duration
    try:
        validate_audio(probe)
    except ValueError:
        return ["audio_duration_repair_required", "audio_not_ready"]
    return []


def _timing_repair_reasons(occurrence, frozen=None, *, root=None, version=None, items=None, profile=None):  # noqa: PLR0913 - Timing repair needs separate frozen/current media and profile context.
    reasons = list(_audio_duration_repair_reasons(occurrence, frozen))
    extra_bg, unready = _background_reasons(root, occurrence, frozen, version, items, profile)
    if unready:
        reasons.extend(extra_bg)
    return _unique(reasons)


def _facts_audio_reasons(root, occurrence, frozen=None, version=None, items=None, data=None):  # noqa: PLR0913, PLR0917 - Current ledger, frozen version and candidate rights are independent readiness inputs.
    reasons = []
    facts_required_block = False
    alignment_unresolved = False
    background_unready = False
    facts_record = _record_from_occurrence_or_frozen(occurrence, frozen, "facts")
    if facts_record is not None:
        from .graphics_facts import facts_readiness

        status = facts_readiness(root, facts_record)
        unreadiness = status.get("reasons") or []
        if not status.get("ready"):
            reasons.extend(unreadiness)
            reasons.append("facts_not_ready")
            required = isinstance(facts_record, dict) and facts_record.get("required") is True
            facts_required_block = required or _facts_conflict_blocks_delivery(facts_record, unreadiness)
    audio_record = _record_from_occurrence_or_frozen(occurrence, frozen, "audio")
    if audio_record is not None:
        from .graphics_audio import audio_readiness

        status = audio_readiness(root, audio_record)
        if not status.get("ready"):
            reasons.extend(status.get("reasons") or [])
            reasons.append("audio_not_ready")
    reasons.extend(_audio_duration_repair_reasons(occurrence, frozen))
    profile = _graphics_profile(version, data)
    extra_bg, background_unready = _background_reasons(root, occurrence, frozen, version, items, profile)
    reasons.extend(extra_bg)
    extra_align, alignment_unresolved = _alignment_reasons(root, occurrence, frozen, profile, data=data)
    reasons.extend(extra_align)
    from .graphics_timeline import timeline_readiness

    timeline_reasons = timeline_readiness(root, occurrence)
    from .graphics_scenes import scene_readiness

    scene_reasons = scene_readiness(root, occurrence)
    if scene_reasons:
        reasons.extend(scene_reasons)
        reasons.append("scene_content_not_ready")
        facts_required_block = True
    if timeline_reasons:
        reasons.extend(timeline_reasons)
        reasons.append("timeline_not_ready")
        facts_required_block = True
    return reasons, facts_required_block, alignment_unresolved, background_unready


def _readiness_blockers(root, version, occurrence, project_id, items=None, data=None):  # noqa: PLR0913, PLR0917 - Preserve explicit project identity, immutable version and live ledger inputs.
    reasons = []
    intact, file_reasons = verify_version_integrity(root, version)
    reasons.extend(file_reasons)
    frozen = version.get("assignment") if isinstance(version.get("assignment"), dict) else None
    assignment_drift = _assignment_changed(frozen, occurrence)
    if assignment_drift:
        reasons.append("assignment_drift")
    timing = _as_dict(version.get("timing"))
    if timing.get("basis") != "explicit":
        reasons.append("estimated_timing")
    questions = frozen.get("questions") if isinstance(frozen, dict) else None
    if questions:
        reasons.append("unresolved_questions")
    reasons.extend(classify_material_use(root, version, items).get("reasons") or [])
    reasons.extend(_approval_blockers(version, project_id))
    extra, facts_required_block, alignment_unresolved, background_unready = _facts_audio_reasons(
        root, occurrence, frozen, version=version, items=items, data=data
    )
    reasons.extend(extra)
    return intact, assignment_drift, reasons, facts_required_block, alignment_unresolved, background_unready


def version_readiness(root, version, occurrence, project_id=None, items=None, data=None):  # noqa: PLR0913, PLR0917 - Public compatibility API keeps each independent readiness context explicit.
    complete = bool(isinstance(version, dict) and version.get("status") == "complete")
    assignment_drift = False
    facts_required_block = False
    alignment_unresolved = False
    background_unready = False
    if not complete:
        extra, facts_required_block, alignment_unresolved, background_unready = _facts_audio_reasons(
            root, occurrence, version=version, items=items, data=data
        )
        unique = _unique(["incomplete_version", *extra])
        intact = False
    else:
        intact, assignment_drift, reasons, facts_required_block, alignment_unresolved, background_unready = (
            _readiness_blockers(root, version, occurrence, project_id, items, data=data)
        )
        unique = _unique(reasons)
    approved = (
        complete
        and intact
        and not any(
            reason in unique for reason in ("missing_approval", "stale_approval", "changes_requested", "wrong_project")
        )
    )
    reviewable = complete and intact
    delivery_blockers = [
        "estimated_timing",
        "unresolved_questions",
        "assignment_drift",
        "unresolved_material_use",
        "missing_artifact",
        "missing_declared_file",
        "changed_declared_file",
        "changes_requested",
        "wrong_project",
        "audio_not_ready",
        "audio_duration_repair_required",
        "unresolved_alignment",
        "background_not_ready",
        "background_module_missing",
        "alignment_module_missing",
        "timeline_not_ready",
        "scene_content_not_ready",
    ]
    if facts_required_block:
        delivery_blockers.append("facts_not_ready")
    if alignment_unresolved:
        delivery_blockers.append("unresolved_alignment")
    if background_unready:
        delivery_blockers.append("background_not_ready")
    deliverable = approved and not any(reason in unique for reason in delivery_blockers)
    return {
        "complete": complete,
        "reviewable": reviewable,
        "approved": approved,
        "deliverable": deliverable,
        "assignment_drift": assignment_drift,
        "reasons": unique,
    }


def _delivery_layout(version):
    scene = version.get("scene_id")
    occ = version.get("occurrence_id")
    ver = version.get("id")
    if not _valid_id(scene) or not _valid_id(occ) or not (isinstance(ver, str) and VERSION_RE.fullmatch(ver)):
        raise ValueError
    package_dir = f"entrega/graphics/{scene}/{occ}/{ver}"
    video_name = f"{scene}-{occ}-{ver}.mp4"
    return package_dir, f"{package_dir}/{video_name}", video_name


def _validate_delivery_identities(delivery, version):
    package_dir, path, video_name = _delivery_layout(version)
    if delivery.get("path") != path or delivery.get("package_dir") != package_dir:
        raise ValueError
    if delivery.get("method") != "copy":
        raise ValueError
    if delivery.get("version_id") != version.get("id"):
        raise ValueError
    if delivery.get("occurrence_id") != version.get("occurrence_id"):
        raise ValueError
    if delivery.get("scene_id") != version.get("scene_id"):
        raise ValueError
    if delivery.get("parent") != version.get("parent"):
        raise ValueError
    if delivery.get("content_sha256") != graphics_content_sha256(version):
        raise ValueError
    if delivery.get("video_sha256") != _as_dict(version.get("artifact")).get("sha256"):
        raise ValueError
    if not _sha256(delivery.get("content_sha256")) or not _sha256(delivery.get("video_sha256")):
        raise ValueError
    return video_name


def _validate_delivery_files(delivery, video_name):
    files = delivery.get("files")
    if not isinstance(files, dict) or not files:
        raise ValueError
    if files.get(video_name) != delivery.get("video_sha256"):
        raise ValueError
    for rel, digest_value in files.items():
        _safe_version_rel(rel)
        if not _sha256(digest_value):
            raise ValueError


def _validate_delivery_record(delivery, version):
    if delivery is None:
        return
    if not isinstance(delivery, dict):
        raise ValueError
    video_name = _validate_delivery_identities(delivery, version)
    _validate_delivery_files(delivery, video_name)


def _bookkeeping_delivery(version):
    delivery = version.get("delivery") if isinstance(version.get("delivery"), dict) else None
    if delivery is None:
        return None
    try:
        _validate_delivery_record(delivery, version)
    except ValueError:
        return None
    return delivery


def _delivered_package_intact(root, delivery):
    if root is None:
        return False
    from .delivery import graphics_package_intact

    return graphics_package_intact(root, delivery)


def _progress_for_occurrence(root, version, occ, project_id, items, data=None):  # noqa: PLR0913, PLR0917 - Delivery progress uses the same explicit read-only readiness context.
    if not isinstance(version, dict) or version.get("status") != "complete":
        extra, _required, _align, _bg = (
            _facts_audio_reasons(root, occ, data=data) if root is not None else ([], False, False, False)
        )
        priority = ("facts_not_ready", "audio_duration_repair_required", "unresolved_alignment", "background_not_ready")
        return "pending", next((reason for reason in priority if reason in extra), "incomplete_version")
    readiness = (
        version_readiness(root, version, occ, project_id, items, data=data)
        if root is not None
        else {"deliverable": False, "reasons": ["status_without_project_root"]}
    )
    delivery = _bookkeeping_delivery(version)
    intact = bool(delivery) and (root is None or _delivered_package_intact(root, delivery))
    if readiness.get("deliverable"):
        return ("delivered", None) if intact else ("undelivered", None)
    reason = (readiness.get("reasons") or ["not_deliverable"])[0]
    return "pending", reason


def graphics_delivery_progress(data, root=None):
    """Current-occurrence delivery remaining work; absent graphics stay out of the candidate ladder."""
    graphics = data.get("graphics") if isinstance(data, dict) else None
    empty = {
        "present": False,
        "undelivered": 0,
        "pending_action": 0,
        "delivered": 0,
        "reasons": [],
    }
    if not isinstance(graphics, dict):
        return empty
    occurrences = graphics.get("occurrences") if isinstance(graphics.get("occurrences"), dict) else {}
    if not occurrences:
        return empty
    raw_versions = graphics.get("versions")
    versions = raw_versions if isinstance(raw_versions, dict) else {}
    items = data.get("items")
    project_id = data.get("project_id")
    undelivered = 0
    pending_action = 0
    delivered = 0
    reasons = []
    for occ in occurrences.values():
        if not isinstance(occ, dict):
            continue
        version = versions.get(occ.get("current_version") or "")
        bucket, reason = _progress_for_occurrence(root, version, occ, project_id, items, data=data)
        if bucket == "delivered":
            delivered += 1
        elif bucket == "undelivered":
            undelivered += 1
        else:
            pending_action += 1
            if reason:
                reasons.append(reason)
    return {
        "present": True,
        "undelivered": undelivered,
        "pending_action": pending_action,
        "delivered": delivered,
        "reasons": _unique(reasons),
    }


def _request_stale_reason(req, graphics):
    occurrences = graphics.get("occurrences") if isinstance(graphics.get("occurrences"), dict) else {}
    versions = graphics.get("versions") if isinstance(graphics.get("versions"), dict) else {}
    occ = occurrences.get(req.get("occurrence_id"))
    version = versions.get(req.get("reviewed_version"))
    if not isinstance(occ, dict) or not isinstance(version, dict) or version.get("status") != "complete":
        return "stale_target"
    if occ.get("current_version") != req.get("reviewed_version"):
        return "current_version_mismatch"
    if _assignment_changed(version.get("assignment"), occ):
        return "assignment_mismatch"
    return None


def _request_effective_state(req, graphics):
    state = req.get("state")
    if state == "processed":
        return "processed", None
    reason = _request_stale_reason(req, graphics)
    if reason:
        return "stale", reason
    return state, None


def _public_requests(graphics):
    rows = []
    for req in graphics.get("requests") or []:
        if not isinstance(req, dict):
            continue
        state, reason = _request_effective_state(req, graphics)
        rows.append(
            {
                "id": req.get("id"),
                "occurrence_id": req.get("occurrence_id"),
                "scene_id": req.get("scene_id"),
                "reviewed_version": req.get("reviewed_version"),
                "state": state,
                "scope": req.get("scope"),
                "text": req.get("text"),
                "processing": req.get("processing"),
                "reason": reason,
            }
        )
    return rows


def _request_identity(req):
    return {
        "project_id": req.get("project_id"),
        "scene_id": req.get("scene_id"),
        "occurrence_id": req.get("occurrence_id"),
        "reviewed_version": req.get("reviewed_version"),
        "content_sha256": req.get("content_sha256"),
        "text": req.get("text"),
        "scope": req.get("scope"),
    }


def derive_request_id(identity):
    return "grq-" + _payload_hash(identity)[:40]


def _append_history(version, entry):
    history = version.get("review_history")
    if not isinstance(history, list):
        history = []
    version["review_history"] = [*history, entry]


def _is_descendant(versions, child_id, ancestor_id):
    if child_id == ancestor_id:
        return False
    current = child_id
    seen = set()
    while current is not None:
        if current in seen:
            return False
        seen.add(current)
        if current == ancestor_id:
            return True
        version = versions.get(current)
        if not isinstance(version, dict):
            return False
        current = version.get("parent")
    return False


def _occurrence_versions(graphics, occurrence_id):
    rows = []
    versions = graphics.get("versions") if isinstance(graphics.get("versions"), dict) else {}
    for version in versions.values():
        if not isinstance(version, dict) or version.get("occurrence_id") != occurrence_id:
            continue
        artifact = _as_dict(version.get("artifact"))
        approval = _as_dict(version.get("approval"))
        timing = _as_dict(version.get("timing"))
        rows.append(
            {
                "id": version.get("id"),
                "parent": version.get("parent"),
                "status": version.get("status"),
                "artifact": {"path": artifact.get("path"), "sha256": artifact.get("sha256")},
                "approval": approval.get("status"),
                "timing_basis": timing.get("basis"),
            }
        )
    rows.sort(key=lambda row: row.get("id") or "")
    return rows


def _review_record_state(version, project):
    review = _as_dict(version.get("review"))
    approval = _as_dict(version.get("approval"))
    if review.get("state") == "changes":
        return "changes"
    content = graphics_content_sha256(version)
    bound = approval.get("project_id")
    if (
        approval.get("status") == "approved"
        and approval.get("content_sha256") == content
        and _bound_project_id(bound)
        and (not _bound_project_id(project) or bound == project)
    ):
        return "approved"
    return review.get("state") or "pending"


def graphics_review_records(ledger, project):
    graphics = ledger.data.get("graphics")
    if not isinstance(graphics, dict):
        return []
    records = []
    versions = graphics.get("versions")
    occurrences = graphics.get("occurrences")
    if not isinstance(versions, dict):
        versions = {}
    if not isinstance(occurrences, dict):
        occurrences = {}
    for occ in occurrences.values():
        if not isinstance(occ, dict):
            continue
        occ_id = occ.get("occurrence_id")
        occ_versions = _occurrence_versions(graphics, occ_id)
        occ_requests = [req for req in _public_requests(graphics) if req.get("occurrence_id") == occ_id]
        for version in versions.values():
            if not isinstance(version, dict) or version.get("occurrence_id") != occ_id:
                continue
            if version.get("status") != "complete":
                continue
            review = _as_dict(version.get("review"))
            approval = _as_dict(version.get("approval"))
            content = graphics_content_sha256(version)
            identity = {
                "project_id": project,
                "scene_id": version.get("scene_id"),
                "occurrence_id": occ_id,
                "reviewed_version": version.get("id"),
                "content_sha256": content,
                "text": review.get("comment") or "",
                "scope": "scene",
            }
            comment = review.get("comment") or ""
            matched = _matching_saved_request(occ_requests, version.get("id"), comment)
            scope = matched.get("scope") if matched and matched.get("scope") in ("scene", "shared") else "scene"
            if matched and isinstance(matched.get("id"), str) and matched.get("id"):
                request_id = matched.get("id")
            else:
                request_id = derive_request_id(identity) if comment.strip() else None
            records.append(
                {
                    "id": "graphics:" + str(occ_id) + ":" + str(version.get("id")),
                    "project": project,
                    "scene_id": version.get("scene_id"),
                    "occurrence_id": occ_id,
                    "version": version.get("id"),
                    "parent": version.get("parent"),
                    "current": occ.get("current_version") == version.get("id"),
                    "signature": content,
                    "reviewEpoch": graphics_review_epoch(version),
                    "state": _review_record_state(version, project),
                    "comment": comment,
                    "scope": scope,
                    "requestId": request_id,
                    "timing_basis": _as_dict(version.get("timing")).get("basis"),
                    "artifact": _as_dict(version.get("artifact")).get("path"),
                    "approval": approval.get("status"),
                    "readiness": version_readiness(
                        ledger.root, version, occ, project, ledger.data.get("items"), data=ledger.data
                    ),
                    "versions": occ_versions,
                    "requests": occ_requests,
                    "context": _review_frozen_context(version, root=ledger.root),
                }
            )
    return records


def _alignment_review_fingerprint(occ, alignment):
    group = occ.get("alignment_group") if isinstance(occ, dict) else None
    group_ids = group.get("occurrence_ids") if isinstance(group, dict) else None
    return _payload_hash(
        {
            "occurrence_id": occ.get("occurrence_id") if isinstance(occ, dict) else None,
            "scene_id": occ.get("scene_id") if isinstance(occ, dict) else None,
            "narration": occ.get("narration") if isinstance(occ, dict) else None,
            "chapter_context": occ.get("chapter_context") if isinstance(occ, dict) else None,
            "anchors": occ.get("anchors") if isinstance(occ, dict) else None,
            "analysis_id": alignment.get("analysis_id") if isinstance(alignment, dict) else None,
            "recording_id": alignment.get("recording_id") if isinstance(alignment, dict) else None,
            "recording_sha256": alignment.get("recording_sha256") if isinstance(alignment, dict) else None,
            "recording_duration_s": alignment.get("recording_duration_s") if isinstance(alignment, dict) else None,
            "transcript_sha256": alignment.get("transcript_sha256") if isinstance(alignment, dict) else None,
            "scenario_sha256": alignment.get("scenario_sha256") if isinstance(alignment, dict) else None,
            "order": alignment.get("order") if isinstance(alignment, dict) else None,
            "alignment_group": list(group_ids) if isinstance(group_ids, list) else None,
            "input_fingerprint": alignment.get("input_fingerprint") if isinstance(alignment, dict) else None,
            "fps": alignment.get("fps") if isinstance(alignment, dict) else None,
            "state": alignment.get("state") if isinstance(alignment, dict) else None,
            "selected_candidate_id": alignment.get("selected_candidate_id") if isinstance(alignment, dict) else None,
            "timing": alignment.get("timing") if isinstance(alignment, dict) else None,
        }
    )


def alignment_review_records(ledger, project):
    graphics = ledger.data.get("graphics")
    if not isinstance(graphics, dict):
        return []
    records = []
    occurrences = graphics.get("occurrences")
    if not isinstance(occurrences, dict):
        return []
    for occ in occurrences.values():
        if not isinstance(occ, dict) or not isinstance(occ.get("alignment"), dict):
            continue
        alignment = _as_dict(occ.get("alignment"))
        fingerprint = _alignment_review_fingerprint(occ, alignment)
        public = _public_alignment(alignment, occ, root=ledger.root)
        records.append(
            {
                "id": "alignment:" + str(occ.get("occurrence_id")),
                "project": project,
                "scene_id": occ.get("scene_id"),
                "occurrence_id": occ.get("occurrence_id"),
                "signature": fingerprint,
                "reviewEpoch": fingerprint,
                "analysis_id": alignment.get("analysis_id"),
                "recording_id": alignment.get("recording_id"),
                "recording_sha256": alignment.get("recording_sha256"),
                "recording_duration_s": alignment.get("recording_duration_s"),
                "transcript_sha256": alignment.get("transcript_sha256"),
                "scenario_sha256": alignment.get("scenario_sha256"),
                "order": alignment.get("order"),
                "alignment_group": copy.deepcopy(occ.get("alignment_group"))
                if isinstance(occ.get("alignment_group"), dict)
                else None,
                "input_fingerprint": alignment.get("input_fingerprint"),
                "fps": alignment.get("fps"),
                "state": alignment.get("state"),
                "selected_candidate_id": alignment.get("selected_candidate_id"),
                "timing": alignment.get("timing"),
                "candidates": public.get("candidates"),
                "override_preview": public.get("override_preview"),
                "decision": public.get("decision"),
                "by": (public.get("decision") or {}).get("by") if isinstance(public.get("decision"), dict) else None,
                "statement": (public.get("decision") or {}).get("statement")
                if isinstance(public.get("decision"), dict)
                else None,
            }
        )
    return records


def _skip_row(skipped, ident, reason, detail):
    skipped.append({"id": ident, "reason": reason, "detail": detail})


def _import_ctx(working, project_id, root, by):
    return {
        "working": working,
        "seen": set(),
        "skipped": [],
        "applied": [],
        "unchanged": [],
        "project_id": project_id,
        "root": root,
        "by": by,
    }


def _graphics_row_id(ctx, row):
    skipped = ctx["skipped"]
    if not isinstance(row, dict) or not isinstance(row.get("id"), str):
        _skip_row(
            skipped,
            None,
            "invalid_item",
            "Há uma decisão de graphics sem identificação. Nada desta linha foi aplicado.",
        )
        return None
    ident = row["id"]
    if ident in ctx["seen"]:
        _skip_row(
            skipped,
            ident,
            "invalid_item",
            "A decisão de graphics " + ident + " aparece duas vezes no arquivo. Nada desta linha foi aplicado.",
        )
        return None
    ctx["seen"].add(ident)
    return ident


def _graphics_row_version(ctx, row, ident):
    working = ctx["working"]
    versions = working.get("versions") if isinstance(working.get("versions"), dict) else {}
    version_id = row.get("version")
    version = versions.get(version_id) if isinstance(version_id, str) else None
    if not isinstance(version, dict) or version.get("status") != "complete":
        _skip_row(
            ctx["skipped"],
            ident,
            "stale_target",
            "A versão de graphics "
            + str(version_id)
            + " está ausente ou incompleta. O pedido permanece no contexto original e não foi retargetado.",
        )
        return None
    if version.get("occurrence_id") != row.get("occurrence_id") or version.get("scene_id") != row.get("scene_id"):
        _skip_row(
            ctx["skipped"],
            ident,
            "wrong_target",
            "A decisão de graphics "
            + ident
            + " não coincide com a occurrence/cena salva. Nada foi aplicado a outro alvo.",
        )
        return None
    return version


def _graphics_row_comment(ctx, row, ident):
    state = row.get("state")
    comment = row.get("comment", "")
    version_id = row.get("version")
    skipped = ctx["skipped"]
    if state not in ("pending", "approved", "changes"):
        _skip_row(
            skipped,
            ident,
            "invalid_item",
            "Decisão desconhecida na versão "
            + str(version_id)
            + ". Use approved ou changes; rejected/alternative não se aplicam a graphics.",
        )
        return None
    if not isinstance(comment, str) or len(comment) > MAX_TEXT:
        _skip_row(skipped, ident, "invalid_item", "O comentário da versão " + str(version_id) + " está grande demais.")
        return None
    if state == "changes" and not comment.strip():
        _skip_row(
            skipped,
            ident,
            "invalid_item",
            "Faltou dizer o que mudar na versão " + str(version_id) + ".",
        )
        return None
    return state, comment


def _graphics_row_fresh(ctx, target):
    row = target["row"]
    version = target["version"]
    ident = target["ident"]
    version_id = row.get("version")
    skipped = ctx["skipped"]
    if row.get("signature") != target["content"]:
        _skip_row(
            skipped,
            ident,
            "signature_mismatch",
            "O conteúdo da versão "
            + str(version_id)
            + " mudou depois da decisão. Nada se perdeu; revise de novo esta versão.",
        )
        return False
    if row.get("reviewEpoch") != graphics_review_epoch(version):
        _skip_row(
            skipped,
            ident,
            "stale_epoch",
            "A decisão da versão "
            + str(version_id)
            + " é de um estado anterior. Nada se perdeu; revise de novo esta versão.",
        )
        return False
    intact, file_reasons = verify_version_integrity(ctx["root"], version)
    if intact:
        return True
    _skip_row(
        skipped,
        ident,
        file_reasons[0] if file_reasons else "missing_declared_file",
        "Arquivos congelados ou o preview de "
        + str(version_id)
        + " estão ausentes ou alterados ("
        + ", ".join(file_reasons)
        + "). O estado anterior foi preservado.",
    )
    return False


def _changes_scope(ctx, row, ident):
    scope = row.get("scope")
    if scope is None:
        scope = "scene"
    if scope not in ("scene", "shared"):
        _skip_row(
            ctx["skipped"], ident, "invalid_item", "Escopo de revisão inválido em " + ident + ". Use scene ou shared."
        )
        return None
    if scope == "shared" and row.get("scope") != "shared":
        _skip_row(ctx["skipped"], ident, "invalid_item", "Escopo shared exige um valor explícito no arquivo exportado.")
        return None
    return scope


def _request_payload(project_id, version, comment, scope, content):
    return {
        "project_id": project_id,
        "scene_id": version["scene_id"],
        "occurrence_id": version["occurrence_id"],
        "reviewed_version": version["id"],
        "content_sha256": content,
        "text": comment.strip(),
        "scope": scope,
    }


def _existing_request_action(existing, payload, ident, ctx):
    if existing is None:
        return "create"
    if _request_identity(existing) != payload:
        _skip_row(
            ctx["skipped"],
            ident,
            "request_conflict",
            "O pedido "
            + str(existing.get("id"))
            + " já existe com outro texto, alvo ou escopo. Nada foi reaberto nem sobrescrito.",
        )
        return "done"
    reason = "already_processed" if existing.get("state") == "processed" else "already_saved"
    ctx["unchanged"].append({"id": ident, "reason": reason, "request": existing.get("id")})
    return "done"


def _approval_record(version, decision):
    return {
        "status": "approved",
        "by": decision["by"],
        "at": decision.get("at") or now(),
        "channel": decision["channel"],
        "statement": decision.get("statement"),
        "project_id": decision["project_id"],
        "version_id": version["id"],
        "occurrence_id": version["occurrence_id"],
        "scene_id": version["scene_id"],
        "content_sha256": decision["content"],
        "signature": decision["content"],
    }


def _history_approval(record):
    return {
        "kind": "approval",
        "status": record.get("status"),
        "project_id": record.get("project_id"),
        "scene_id": record.get("scene_id"),
        "occurrence_id": record.get("occurrence_id"),
        "version_id": record.get("version_id"),
        "statement": record.get("statement"),
        "content_sha256": record.get("content_sha256"),
        "signature": record.get("signature") or record.get("content_sha256"),
        "by": record.get("by"),
        "channel": record.get("channel"),
        "at": record.get("at"),
    }


def _apply_graphics_approval(ctx, target):
    version = target["version"]
    content = target["content"]
    existing = version.get("approval") if isinstance(version.get("approval"), dict) else None
    if (
        existing
        and existing.get("status") == "approved"
        and existing.get("content_sha256") == content
        and existing.get("by") == ctx["by"]
        and existing.get("channel") == "storyboard"
        and _as_dict(version.get("review")).get("state") != "changes"
    ):
        ctx["unchanged"].append({"id": target["ident"], "reason": "already_approved"})
        return
    record = _approval_record(
        version,
        {
            "by": ctx["by"],
            "channel": "storyboard",
            "statement": target["comment"].strip() or None,
            "content": content,
            "project_id": ctx["project_id"],
        },
    )
    _append_history(version, _history_approval(record))
    version["approval"] = record
    version["review"] = {
        "state": "approved",
        "comment": target["comment"],
        "by": ctx["by"],
        "at": record["at"],
        "signature": content,
    }
    ctx["applied"].append(target["ident"])


def _archive_current_approval(version):
    if isinstance(version.get("approval"), dict):
        version["approval"] = None


def _lookup_request(working, request_id):
    requests = working.setdefault("requests", [])
    return next((item for item in requests if item.get("id") == request_id), None)


def _apply_graphics_changes(ctx, target):
    row = target["row"]
    version = target["version"]
    ident = target["ident"]
    scope = _changes_scope(ctx, row, ident)
    if scope is None:
        return
    payload = _request_payload(ctx["project_id"], version, target["comment"], scope, target["content"])
    supplied = row.get("requestId")
    request_id = supplied if isinstance(supplied, str) and _valid_id(supplied) else derive_request_id(payload)
    existing_payload = dict(payload)
    if _sha256(row.get("signature")):
        existing_payload["content_sha256"] = row.get("signature")
    existing = _lookup_request(ctx["working"], request_id)
    if _existing_request_action(existing, existing_payload, ident, ctx) != "create":
        return
    stale = _request_stale_reason(
        {"occurrence_id": version["occurrence_id"], "reviewed_version": version["id"]},
        ctx["working"],
    )
    ctx["working"].setdefault("requests", []).append(
        {
            "id": request_id,
            "project_id": ctx["project_id"],
            "scene_id": version["scene_id"],
            "occurrence_id": version["occurrence_id"],
            "reviewed_version": version["id"],
            "content_sha256": target["content"],
            "text": target["comment"].strip(),
            "scope": scope,
            "state": "stale" if stale else "saved",
            "processing": None,
        }
    )
    _archive_current_approval(version)
    stamped = now()
    version["review"] = {
        "state": "changes",
        "comment": target["comment"],
        "by": ctx["by"],
        "at": stamped,
        "signature": target["content"],
    }
    _append_history(
        version,
        {
            "kind": "request",
            "at": stamped,
            "by": ctx["by"],
            "request_id": request_id,
            "scope": scope,
            "reviewed_version": version["id"],
            "project_id": ctx["project_id"],
            "scene_id": version["scene_id"],
            "occurrence_id": version["occurrence_id"],
        },
    )
    ctx["applied"].append(ident)
    if stale:
        _skip_row(
            ctx["skipped"],
            ident,
            "stale_target",
            "O pedido da versão "
            + str(version.get("id"))
            + " permanece no alvo original, mas está stale ("
            + stale
            + ") em relação à current_version ou ao assignment atual. Nada foi retargetado.",
        )


def _reuse_existing_changes(ctx, target):
    row = target["row"]
    ident = target["ident"]
    scope = _changes_scope(ctx, row, ident)
    if scope is None:
        return True
    payload = _request_payload(
        ctx["project_id"],
        target["version"],
        target["comment"],
        scope,
        row.get("signature") if _sha256(row.get("signature")) else target["content"],
    )
    supplied = row.get("requestId")
    request_id = supplied if isinstance(supplied, str) and _valid_id(supplied) else derive_request_id(payload)
    existing = _lookup_request(ctx["working"], request_id)
    if existing is None:
        return False
    _existing_request_action(existing, payload, ident, ctx)
    return True


def _resolve_graphics_row(ctx, row):
    ident = _graphics_row_id(ctx, row)
    if ident is None:
        return None
    version = _graphics_row_version(ctx, row, ident)
    if version is None:
        return None
    if row.get("project") not in (None, ctx["project_id"]) and row.get("project") != ctx["project_id"]:
        _skip_row(ctx["skipped"], ident, "wrong_project", "A decisão de graphics " + ident + " é de outro projeto.")
        return None
    try:
        content = graphics_content_sha256(version)
    except (TypeError, ValueError):
        _skip_row(
            ctx["skipped"], ident, "stale_target", "Não consegui calcular a assinatura de conteúdo de " + ident + "."
        )
        return None
    parsed = _graphics_row_comment(ctx, row, ident)
    if parsed is None:
        return None
    state, comment = parsed
    return {"ident": ident, "version": version, "content": content, "state": state, "comment": comment, "row": row}


def _apply_one_graphics_row(ctx, row):
    target = _resolve_graphics_row(ctx, row)
    if target is None:
        return
    if target["state"] == "pending":
        ctx["unchanged"].append({"id": target["ident"], "reason": "pending"})
        return
    if target["state"] == "changes" and _reuse_existing_changes(ctx, target):
        return
    if not _graphics_row_fresh(ctx, target):
        return
    if target["state"] == "approved":
        _apply_graphics_approval(ctx, target)
        return
    _apply_graphics_changes(ctx, target)


def apply_graphics_review_import(graphics, rows, *, project_id, root, by):
    if not rows:
        return graphics, [], [], []
    if graphics is None:
        skipped = []
        for row in rows:
            ident = row.get("id") if isinstance(row, dict) else None
            _skip_row(
                skipped,
                ident,
                "missing_graphics",
                "Este arquivo traz decisões de graphics, mas o projeto não tem registros de graphics.",
            )
        return graphics, [], skipped, []
    working = copy.deepcopy(graphics)
    working.setdefault("requests", [])
    ctx = _import_ctx(working, project_id, root, by)
    for row in rows:
        _apply_one_graphics_row(ctx, row)
    return working, ctx["applied"], ctx["skipped"], ctx["unchanged"]


def _alignment_import_choice(row):
    candidate_id = row.get("candidate_id")
    start_s = row.get("start_s")
    end_s = row.get("end_s")
    has_candidate = isinstance(candidate_id, str) and bool(candidate_id.strip())
    has_interval = start_s is not None or end_s is not None
    if has_candidate and has_interval:
        return None, "invalid_alignment", "Use candidate_id or start_s/end_s, not both."
    if has_candidate:
        return {"candidate_id": candidate_id.strip(), "start_s": None, "end_s": None}, None, None
    if start_s is None or end_s is None:
        return None, "invalid_alignment", "Alignment correction needs candidate_id or both start_s and end_s."
    return {"candidate_id": None, "start_s": start_s, "end_s": end_s}, None, None


def _alignment_identity_blockers(root, occ, data, profile):
    reasons, _unresolved = _alignment_reasons(root, occ, None, profile, data=data)
    return [reason for reason in reasons if reason in ALIGNMENT_IDENTITY_BLOCKERS]


def _alignment_replay(previous, updated, *, by, statement, choice):
    if not isinstance(previous, dict) or not isinstance(updated, dict):
        return False
    prev_d = previous.get("decision") if isinstance(previous.get("decision"), dict) else {}
    new_d = updated.get("decision") if isinstance(updated.get("decision"), dict) else {}
    if not prev_d or not new_d:
        return False
    same_choice = previous.get("selected_candidate_id") == updated.get("selected_candidate_id") and previous.get(
        "timing"
    ) == updated.get("timing")
    if choice.get("candidate_id"):
        same_choice = same_choice and updated.get("selected_candidate_id") == choice.get("candidate_id")
    else:
        timing = _as_dict(updated.get("timing"))
        same_choice = (
            same_choice
            and timing.get("start_s") == choice.get("start_s")
            and timing.get("end_s") == choice.get("end_s")
        )
    return (
        prev_d.get("by") == by
        and new_d.get("by") == by
        and prev_d.get("statement") == statement
        and new_d.get("statement") == statement
        and prev_d.get("input_fingerprint") == new_d.get("input_fingerprint")
        and previous.get("analysis_id") == updated.get("analysis_id")
        and previous.get("recording_id") == updated.get("recording_id")
        and previous.get("recording_sha256") == updated.get("recording_sha256")
        and previous.get("transcript_sha256") == updated.get("transcript_sha256")
        and previous.get("input_fingerprint") == updated.get("input_fingerprint")
        and same_choice
    )


def _alignment_import_target(occ, row, root, context):
    alignment = occ.get("alignment")
    if not isinstance(alignment, dict):
        return None, ("stale_target", "Occurrence has no saved alignment record.")
    fingerprint = _alignment_review_fingerprint(occ, alignment)
    if row.get("signature") != fingerprint or row.get("reviewEpoch") != fingerprint:
        return None, (
            "stale_target",
            "Alignment correction is bound to a different occurrence/scenario/recording/result.",
        )
    fields = (
        ("input_fingerprint", "Alignment input fingerprint does not match the saved record."),
        ("analysis_id", "Alignment analysis identity does not match the saved record."),
        ("recording_id", "Alignment recording identity does not match the saved record."),
    )
    for key, detail in fields:
        if row.get(key) not in (None, alignment.get(key)):
            return None, ("stale_target", detail)
    profile = _as_dict(_as_dict(context.get("graphics")).get("profile"))
    blockers = _alignment_identity_blockers(root, occ, context, profile)
    if blockers:
        return None, (
            "stale_target",
            "Alignment correction is bound to obsolete source, result, scenario or profile: "
            + ", ".join(blockers)
            + ".",
        )
    statement = row.get("statement")
    if not isinstance(statement, str) or not statement.strip() or len(statement) > MAX_TEXT:
        return None, ("invalid_alignment", "Alignment correction needs a bounded human statement.")
    return alignment, None


def _stage_alignment_import(occ, updated, root, context):
    staged = copy.deepcopy(occ)
    staged["alignment"] = updated
    staged["stage"] = "assigned"
    profile = _as_dict(_as_dict(context.get("graphics")).get("profile"))
    fps = profile.get("fps") if isinstance(profile.get("fps"), (int, float)) else DEFAULT_FPS
    _apply_pending_timing(
        staged,
        updated.get("timing") if isinstance(updated, dict) else None,
        fps,
        root=root,
        profile=profile,
        items=context.get("items"),
    )
    snapshot = _alignment_snapshot(root, context, updated)
    _publish_alignment_previews(root, staged, updated if isinstance(updated, dict) else {}, snapshot, fps)
    return staged


def _skip_alignment_rows(rows, reason, detail):
    skipped = []
    for row in rows:
        ident = row.get("id") if isinstance(row, dict) else None
        _skip_row(skipped, ident, reason, detail)
    return skipped


def _alignment_import_correction(row, alignment, by, correct_match):
    statement = row["statement"]
    choice, reason, detail = _alignment_import_choice(row)
    if choice is None:
        return {"error": (reason, detail)}
    actor = (by or "").strip() or (row.get("by") if isinstance(row.get("by"), str) else "")
    if not actor:
        return {"error": ("invalid_alignment", "Alignment correction needs the reviewing person.")}
    try:
        updated = correct_match(
            alignment,
            candidate_id=choice["candidate_id"],
            start_s=choice["start_s"],
            end_s=choice["end_s"],
            by=actor,
            statement=statement.strip(),
            at=now(),
        )
    except ValueError as exc:
        return {"error": ("invalid_alignment", str(exc))}
    if _alignment_replay(alignment, updated, by=actor, statement=statement.strip(), choice=choice):
        return {"unchanged": {"id": row.get("id"), "reason": "replay", "by": actor, "statement": statement.strip()}}
    return {"updated": updated}


def apply_alignment_review_import(graphics, rows, *, project_id, root, by, data=None):  # noqa: C901, PLR0913, ARG001 - Atomic import keeps ordered refusal/replay/staging explicit; the outer loader validates project identity.
    applied = []
    skipped = []
    unchanged = []
    if not rows:
        return graphics, applied, skipped, unchanged
    if graphics is None:
        skipped.extend(
            _skip_alignment_rows(
                rows,
                "missing_graphics",
                "Este arquivo traz correções de alinhamento, mas o projeto não tem registros de graphics.",
            )
        )
        return graphics, applied, skipped, unchanged
    try:
        from .narration_alignment import correct_match
    except ImportError:
        skipped.extend(
            _skip_alignment_rows(
                rows,
                "alignment_module_missing",
                "Narration alignment module is missing; alignment corrections were not applied.",
            )
        )
        return graphics, applied, skipped, unchanged
    working = copy.deepcopy(graphics)
    occurrences = working.get("occurrences") if isinstance(working.get("occurrences"), dict) else {}
    context = data if isinstance(data, dict) else {"graphics": working}
    if context.get("graphics") is not working:
        context = {**context, "graphics": working}
    seen = set()
    for row in rows:
        if not isinstance(row, dict):
            _skip_row(skipped, None, "invalid_alignment", "Alignment row is not an object.")
            continue
        ident = row.get("id")
        occ_id = row.get("occurrence_id")
        if not isinstance(ident, str) or ident in seen:
            _skip_row(skipped, ident, "invalid_alignment", "Alignment row is missing a unique id.")
            continue
        seen.add(ident)
        occ = occurrences.get(occ_id)
        if not isinstance(occ, dict):
            _skip_row(skipped, ident, "stale_target", "Occurrence " + str(occ_id) + " is not in this project.")
            continue
        alignment, error = _alignment_import_target(occ, row, root, context)
        if error is not None:
            _skip_row(skipped, ident, *error)
            continue
        correction = _alignment_import_correction(row, alignment, by, correct_match)
        if "error" in correction:
            _skip_row(skipped, ident, *correction["error"])
            continue
        if "unchanged" in correction:
            unchanged.append(correction["unchanged"])
            continue
        updated = correction["updated"]
        try:
            staged = _stage_alignment_import(occ, updated, root, context)
        except ValueError as exc:
            _skip_row(skipped, ident, "audio_duration_repair_required", str(exc))
            continue
        occurrences[occ_id] = staged
        applied.append({"id": ident, "occurrence_id": occ_id})
    return working, applied, skipped, unchanged


def _require_complete_version(graphics, occurrence_id, version_id, action):
    if not isinstance(graphics, dict):
        raise ValueError("Este projeto não tem registros de graphics.")
    occ = (graphics.get("occurrences") or {}).get(occurrence_id)
    version = (graphics.get("versions") or {}).get(version_id)
    if not isinstance(occ, dict):
        raise ValueError("Unknown graphics occurrence. Register it with graphics-assign first.")
    if not isinstance(version, dict) or version.get("occurrence_id") != occurrence_id:
        raise ValueError("Essa versão não pertence à occurrence informada. Nada foi aplicado a outro alvo.")
    if version.get("status") != "complete":
        raise ValueError("Só uma versão completa pode receber " + action + ".")
    return occ, version


def _ledger_project_id(ledger):
    ident = ledger.data.get("project_id")
    if _bound_project_id(ident):
        return ident
    ident = str(uuid.uuid4())
    ledger.data["project_id"] = ident
    return ident


def approve_command(ledger, args):
    by = (getattr(args, "by", None) or "").strip()
    statement = getattr(args, "statement", None)
    if not by:
        raise ValueError("Informe quem aprovou.")
    if not isinstance(statement, str) or not statement.strip():
        raise ValueError("Aprovação de graphics exige --statement com a frase exata dita pela pessoa.")
    graphics = ledger.data.get("graphics")
    occ, version = _require_complete_version(graphics, args.occurrence, args.version, "aprovação humana")
    intact, reasons = verify_version_integrity(ledger.root, version)
    if not intact:
        raise ValueError("Recuso a aprovação: " + "; ".join(reasons) + ". O estado anterior foi preservado.")
    content = graphics_content_sha256(version)
    project = _ledger_project_id(ledger)
    record = _approval_record(
        version,
        {
            "by": by,
            "channel": "chat",
            "statement": statement.strip(),
            "content": content,
            "project_id": project,
        },
    )
    _append_history(version, _history_approval(record))
    version["approval"] = record
    version["review"] = {
        "state": "approved",
        "comment": record["statement"],
        "by": by,
        "at": record["at"],
        "signature": content,
    }
    ledger.save("graphics-approve")
    return {
        "occurrence": args.occurrence,
        "version": version["id"],
        "approval": record,
        "approved": True,
        "readiness": version_readiness(ledger.root, version, occ, project, ledger.data.get("items"), data=ledger.data),
    }


def select_command(ledger, args):
    graphics = ledger.data.get("graphics")
    occ, version = _require_complete_version(graphics, args.occurrence, args.version, "seleção")
    intact, reasons = verify_version_integrity(ledger.root, version)
    if not intact:
        raise ValueError("Recuso a seleção: " + "; ".join(reasons) + ". current_version não foi alterado.")
    previous = occ.get("current_version")
    occ["current_version"] = version["id"]
    ledger.save("graphics-select")
    readiness = version_readiness(
        ledger.root, version, occ, ledger.data.get("project_id"), ledger.data.get("items"), data=ledger.data
    )
    return {
        "occurrence": args.occurrence,
        "version": version["id"],
        "previous_version": previous,
        "current_version": occ["current_version"],
        "readiness": readiness,
        "assignment_drift": readiness["assignment_drift"],
    }


def _find_request(graphics, request_id):
    requests = graphics.setdefault("requests", [])
    found = next((item for item in requests if item.get("id") == request_id), None)
    if found is None:
        raise ValueError("Pedido de revisão não encontrado: " + str(request_id))
    return found


def _complete_result_version(graphics, found, version_id):
    versions = graphics.get("versions") if isinstance(graphics.get("versions"), dict) else {}
    result = versions.get(version_id)
    if not isinstance(result, dict) or result.get("status") != "complete":
        raise ValueError("A versão resultante precisa existir e estar completa.")
    if result.get("occurrence_id") != found.get("occurrence_id"):
        raise ValueError("A versão resultante não pertence à occurrence do pedido. Nada foi retargetado.")
    if not _is_descendant(versions, version_id, found.get("reviewed_version")):
        raise ValueError("A versão resultante precisa ser uma descendente completa distinta da versão revisada.")
    return result


def _mark_request_processed(found, processing):
    previous = found.get("processing") if isinstance(found.get("processing"), dict) else None
    if found.get("state") == "processed" and previous:
        if (
            previous.get("resulting_version") == processing["resulting_version"]
            and previous.get("outcome") == processing["outcome"]
        ):
            return True
        raise ValueError(
            "Esse pedido já foi processado com outro resultado. O histórico foi preservado; não sobrescrevi o outcome."
        )
    history = list(found.get("processing_history") or [])
    if previous:
        history.append(previous)
        found["processing_history"] = history
    found["processing"] = processing
    found["state"] = "processed"
    return False


def request_complete_command(ledger, args):
    outcome = getattr(args, "outcome", None)
    if not isinstance(outcome, str) or not outcome.strip():
        raise ValueError("Informe --outcome com o resultado real do processamento.")
    graphics = ledger.data.get("graphics")
    if not isinstance(graphics, dict):
        raise ValueError("Este projeto não tem registros de graphics.")
    found = _find_request(graphics, args.request)
    result = _complete_result_version(graphics, found, args.version)
    intact, reasons = verify_version_integrity(ledger.root, result)
    if not intact:
        raise ValueError("Recuso a conclusão: " + "; ".join(reasons) + ". O pedido permanece como estava.")
    processing = {"at": now(), "outcome": outcome.strip(), "resulting_version": args.version}
    if _mark_request_processed(found, processing):
        return {"request": found, "version": args.version, "idempotent": True}
    ledger.save("graphics-request-complete")
    return {"request": found, "version": args.version, "idempotent": False}


def _graphics(ledger):
    data = ledger.data
    if "graphics" not in data:
        data["graphics"] = empty_graphics(default_profile())
    return data["graphics"]


def _normalize_fps(value):
    if type(value) is int:
        return value
    number = float(value)
    return int(number) if number.is_integer() else number


def _profile_for_write(graphics, confirm_fps, *, existing_project):
    if graphics.get("profile") and graphics.get("style_revisions"):
        profile = graphics["profile"]
        if confirm_fps is not None and float(confirm_fps) != float(profile["fps"]):
            raise ValueError(
                "This project already has a graphics profile at "
                + str(profile["fps"])
                + " fps. Pass matching --confirm-fps; fps is not inferred from footage."
            )
        return profile
    if confirm_fps is not None:
        return default_profile(fps=_normalize_fps(confirm_fps), fps_source="confirmed")
    if existing_project:
        raise ValueError(
            "This project already has collection records. Pass --confirm-fps with the editing "
            "frame rate. Graphics fps is never inferred from acquired footage."
        )
    return default_profile()


def _append_style(graphics, *, note=None, family="documentary"):
    if family != "documentary":
        raise ValueError("Only the proposed documentary family is available in this slice.")
    next_rev = max((item["revision"] for item in graphics["style_revisions"]), default=0) + 1
    record = {
        "revision": next_rev,
        "family": "documentary",
        "approved": False,
        "at": now(),
        "user_note": (note or DOCUMENTARY_PROPOSAL["user_note"]),
        "proposal": dict(DOCUMENTARY_PROPOSAL["proposal"]),
    }
    if not _bounded_prose(record["user_note"]):
        raise ValueError("--note must keep the original style note text.")
    graphics["style_revisions"].append(record)
    graphics["current_style_revision"] = next_rev
    return record


def _ensure_style(graphics, note=None):
    current = graphics["current_style_revision"]
    if current is not None:
        return next(item for item in graphics["style_revisions"] if item["revision"] == current)
    return _append_style(graphics, note=note)


def _timing_from_args(args, fps):
    basis = args.timing
    if basis == "estimated":
        duration = args.duration
        if duration is None:
            raise ValueError("Estimated timing requires --duration seconds and must not invent VO start/end.")
        if args.start is not None or args.end is not None:
            raise ValueError("Estimated timing records a duration only; omit --start and --end.")
        frames = seconds_to_frame(duration, fps)
        if frames < 1:
            raise ValueError("Estimated duration is shorter than one frame at this fps.")
        return {
            "basis": "estimated",
            "duration_s": float(duration),
            "duration_in_frames": frames,
            "start_s": None,
            "end_s": None,
            "start_frame": None,
            "end_frame": None,
        }
    if args.start is None or args.end is None:
        raise ValueError("Explicit timing requires --start and --end in narration seconds.")
    if args.duration is not None:
        raise ValueError("Explicit timing uses --start/--end; omit --duration.")
    start_frame = seconds_to_frame(args.start, fps)
    end_frame = seconds_to_frame(args.end, fps)
    if end_frame <= start_frame:
        raise ValueError("Explicit timing requires end after start.")
    return {
        "basis": "explicit",
        "start_s": float(args.start),
        "end_s": float(args.end),
        "start_frame": start_frame,
        "end_frame": end_frame,
        "duration_in_frames": max(1, end_frame - start_frame),
        "duration_s": float(args.end) - float(args.start),
    }


def _parse_anchors(values, basis):
    anchors = []
    for raw in values or []:
        if not _bounded_prose(raw, 500):
            raise ValueError("Each --anchor must be original scenario text, optionally prefixed with seconds.")
        text = raw
        t_s = None
        if re.match(r"^\d+(?:\.\d+)?:", text.strip()):
            stamp, remainder = text.strip().split(":", 1)
            t_s = float(stamp)
            text = remainder if remainder.startswith(("\n", "\t")) else remainder.lstrip(" ")
            if basis == "estimated":
                raise ValueError(
                    "Estimated timing cannot attach narration-clock times to anchors; keep the original text only."
                )
        anchors.append({"text": text, "t_s": t_s})
    return anchors


def _text_list(values, flag):
    return [_original_prose(raw, flag, 2000) for raw in values or []]


def style_command(ledger, args):
    existing = bool(ledger.data.get("items"))
    graphics = _graphics(ledger)
    graphics["profile"] = _profile_for_write(graphics, getattr(args, "confirm_fps", None), existing_project=existing)
    record = _append_style(
        graphics, note=getattr(args, "note", None), family=getattr(args, "family", None) or "documentary"
    )
    for occurrence in graphics["occurrences"].values():
        occurrence["style_revision"] = record["revision"]
    ledger.save("graphics-style")
    return {
        "style": record,
        "current_style_revision": graphics["current_style_revision"],
        "profile": graphics["profile"],
        "approved": False,
    }


def _validate_assign_ids(args):
    for ident, label in (
        (getattr(args, "scene", None), "--scene"),
        (getattr(args, "occurrence", None), "--occurrence"),
        (getattr(args, "chapter", None), "--chapter"),
    ):
        if not _valid_id(ident):
            raise ValueError(
                f"{label} must be 1–80 letters, numbers, hyphen or underscore, without reserved Windows names."
            )


def _occurrence_display_props(args):
    claim = getattr(args, "claim_status", None) or "synthetic"
    if claim not in ASSIGN_CLAIM_STATUSES:
        raise ValueError("--claim-status must be synthetic or unverified_scenario.")
    value = getattr(args, "value", None) or "—"
    unit = getattr(args, "unit", None) or "units"
    label = getattr(args, "label", None) or "Synthetic numeric draft"
    if not _bounded_text(value, 500) or not _bounded_text(unit, 500) or not _bounded_text(label, 500):
        raise ValueError("--value, --unit and --label must be non-empty editorial text without control characters.")
    note = (
        "Synthetic draft value."
        if claim == "synthetic"
        else "Unverified scenario claim; not researched or published as fact in this slice."
    )
    return {
        "value": value,
        "unit": unit,
        "label": label,
        "claim_status": claim,
        "claim_note": note,
    }


def _inherit_occurrence_records(root, occurrence, previous):
    if not previous:
        return
    if isinstance(previous.get("facts"), dict):
        occurrence["facts"] = previous["facts"]
        if isinstance(previous.get("props_before_facts"), dict):
            occurrence["props_before_facts"] = previous["props_before_facts"]
        _apply_facts_display(root, occurrence)
    for key in (
        "audio",
        "background",
        "alignment",
        "alignment_previews",
        "alignment_group",
        "work",
        "timeline",
        "scene_content",
    ):
        if isinstance(previous.get(key), dict):
            if key == "timeline" and occurrence["template"] != "timeline":
                continue
            if key == "scene_content" and previous[key].get("kind") != occurrence["template"]:
                continue
            occurrence[key] = copy.deepcopy(previous[key])


def assign_command(ledger, args):
    _validate_assign_ids(args)
    chapter_context = _original_prose(args.chapter_context, "--chapter-context")
    purpose = _original_prose(args.purpose, "--purpose")
    narration = _original_prose(args.narration, "--narration")
    scene_id = args.scene
    template = getattr(args, "template", None) or "numeric-stat"
    if template not in TEMPLATES:
        raise ValueError("Unknown graphics template. Use numeric-stat, timeline, map or custom.")
    asset_refs = list(getattr(args, "asset_ref", None) or [])
    evidence_refs = list(getattr(args, "evidence_ref", None) or [])
    _confine_refs(ledger.root, [*asset_refs, *evidence_refs], prefixes=INPUT_PREFIXES)
    material_use_args = _parse_material_use_args(getattr(args, "material_use", None) or [])
    material_use = None
    if material_use_args:
        material_use = bind_material_use(
            ledger.root, material_use_args, [*asset_refs, *evidence_refs], ledger.data.get("items")
        )
    existing = bool(ledger.data.get("items"))
    graphics = _graphics(ledger)
    graphics["profile"] = _profile_for_write(graphics, getattr(args, "confirm_fps", None), existing_project=existing)
    style = _ensure_style(graphics, note=getattr(args, "style_note", None))
    occ_id = args.occurrence
    previous = graphics["occurrences"].get(occ_id)
    if previous and previous.get("scene_id") != scene_id:
        raise ValueError("Occurrence " + occ_id + " already belongs to scene " + previous["scene_id"] + ".")
    if previous and previous.get("template") not in (None, template) and not getattr(args, "replace_template", False):
        raise ValueError(
            "Occurrence "
            + occ_id
            + " already uses template "
            + previous["template"]
            + ". Use --replace-template to revise its composition while retaining earlier versions."
        )
    timing = _timing_from_args(args, graphics["profile"]["fps"])
    occurrence = {
        "occurrence_id": occ_id,
        "scene_id": scene_id,
        "template": template,
        "composition": TEMPLATES[template],
        "chapter_id": args.chapter,
        "chapter_context": chapter_context,
        "purpose": purpose,
        "narration": narration,
        "style_revision": style["revision"],
        "timing": timing,
        "anchors": _parse_anchors(getattr(args, "anchor", None), timing["basis"]),
        "questions": _text_list(getattr(args, "question", None), "--question"),
        "proposed_scenes": _text_list(getattr(args, "propose_scene", None), "--propose-scene"),
        "asset_refs": asset_refs,
        "evidence_refs": evidence_refs,
        **({"material_use": material_use} if material_use is not None else {}),
        "props": _occurrence_display_props(args),
        "current_version": previous.get("current_version") if previous else None,
        "stage": "assigned",
    }
    _inherit_occurrence_records(ledger.root, occurrence, previous)
    graphics["occurrences"][occ_id] = occurrence
    ledger.save("graphics-assign")
    return {"occurrence": occurrence, "profile": graphics["profile"], "style_revision": style["revision"]}


def _next_version_id(versions, scene_dir):
    taken = set()
    for key in versions:
        match = VERSION_RE.fullmatch(key)
        if match:
            taken.add(int(match.group(1)))
    if scene_dir.is_dir():
        for child in scene_dir.iterdir():
            match = VERSION_RE.fullmatch(child.name)
            if match:
                taken.add(int(match.group(1)))
    index = 1
    while index in taken:
        index += 1
    return f"v{index}"


def _package_versions():
    missing = []
    found = {}
    for name, pinned in PINNED.items():
        manifest = PACKAGE_ROOT / "node_modules" / name / "package.json"
        if not manifest.is_file():
            missing.append(name)
            continue
        try:
            version = json.loads(manifest.read_text(encoding="utf-8")).get("version")
        except (OSError, ValueError, json.JSONDecodeError):
            missing.append(name)
            continue
        found[name] = version
        if version != pinned:
            missing.append(f"{name}=={version} (pinned {pinned})")
    return found, missing


def _worker_path():
    raw = os.environ.get(WORKER_ENV)
    if raw is None:
        worker = WORKER
        if not worker.is_file():
            raise ValueError(
                "Graphics worker is missing. Install the optional package under scripts/graphics "
                "or set GB_GRAPHICS_WORKER to an absolute existing path. Collection commands do not need it."
            )
        return worker, "remotion"
    if not isinstance(raw, str) or not raw.strip():
        raise ValueError("GB_GRAPHICS_WORKER must be an absolute existing path when set.")
    worker = Path(raw)
    if not worker.is_absolute() or not worker.is_file():
        raise ValueError("GB_GRAPHICS_WORKER must be an absolute existing path when set.")
    kind = "test-worker" if worker.suffix.lower() == ".py" else "remotion"
    return worker, kind


def runtime_status():
    found, missing = _package_versions()
    raw = os.environ.get(WORKER_ENV)
    worker = None
    kind = None
    if raw is None:
        if WORKER.is_file():
            worker = str(WORKER)
            kind = "remotion"
    elif raw.strip():
        path = Path(raw)
        if path.is_absolute() and path.is_file():
            worker = str(path)
            kind = "test-worker" if path.suffix.lower() == ".py" else "remotion"
    node = shutil.which("node")
    return {
        "package_root": str(PACKAGE_ROOT),
        "worker": worker,
        "worker_kind": kind,
        "node": node,
        "versions": found,
        "pinned": PINNED,
        "missing": missing,
        "browser_prepared": _browser_is_prepared(node) if node and not missing else False,
    }


def _browser_marker():
    return PACKAGE_ROOT / ".browser-prepared"


def _browser_record(marker=None):
    path = Path(marker) if marker is not None else _browser_marker()
    if not path.is_file():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, json.JSONDecodeError):
        return None
    if not isinstance(payload, dict):
        return None
    executable = payload.get("executable")
    if not isinstance(executable, str) or not executable:
        return None
    return payload


def _marker_matches_live(record, live):
    if not isinstance(record, dict) or not isinstance(live, dict):
        return False
    if live.get("type") in ("no-browser", "version-mismatch") or not live.get("path"):
        return False
    recorded = record.get("executable")
    if not isinstance(recorded, str) or not Path(recorded).is_file():
        return False
    try:
        live_path = Path(live["path"]).resolve()
        recorded_path = Path(recorded).resolve()
    except OSError:
        return False
    return os.path.normcase(str(live_path)) == os.path.normcase(str(recorded_path))


def _last_json_line(text):
    for raw_line in reversed((text or "").splitlines()):
        candidate = raw_line.strip()
        if not candidate:
            continue
        try:
            return json.loads(candidate)
        except json.JSONDecodeError:
            continue
    raise ValueError("Graphics worker did not return JSON status.")


def _probe_browser_status(node):
    command = [node, str(WORKER), "--status-browser"]
    env = os.environ.copy()
    env.pop(BROWSER_PREPARE_ENV, None)
    try:
        done = subprocess.run(
            command,
            capture_output=True,
            text=True,
            encoding="utf-8",
            env=env,
            check=False,
            timeout=120,
            cwd=str(PACKAGE_ROOT),
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise ValueError("Could not inspect the Remotion browser: " + str(exc)) from exc
    try:
        payload = _last_json_line(done.stdout)
    except ValueError:
        payload = {"type": "no-browser", "error": (done.stderr or done.stdout or "no-browser").strip()[:1200]}
    if not isinstance(payload, dict):
        raise ValueError("Remotion browser status was not an object.")
    return payload


def _browser_is_prepared(node):
    record = _browser_record()
    if record is None:
        return False
    try:
        live = _probe_browser_status(node)
    except ValueError:
        return False
    return _marker_matches_live(record, live)


def doctor_command(args):
    status = runtime_status()
    if getattr(args, "prepare_browser", False):
        return _prepare_browser(status)
    missing = []
    optional = []
    ok = []
    if status["node"]:
        ok.append("node")
    else:
        missing.append(
            {
                "item": "node",
                "note": "Node.js is required only for graphics rendering, not for collection.",
                "fix": "Install Node 22+ and reopen the terminal so node is on PATH.",
            }
        )
    if status["missing"]:
        optional.append(
            {
                "item": "remotion",
                "note": "Optional graphics runtime is not installed: " + ", ".join(status["missing"]),
                "fix": (
                    "From the skill root run: npm ci --ignore-scripts --prefix scripts/graphics "
                    "then python scripts/gb.py graphics-doctor --prepare-browser"
                ),
            }
        )
    else:
        ok.append("remotion")
    if status["missing"] or not status["browser_prepared"]:
        optional.append(
            {
                "item": "remotion-browser",
                "note": "The local Remotion browser is not a verified prepared runtime; render will refuse to download it.",
                "fix": "python scripts/gb.py graphics-doctor --prepare-browser",
            }
        )
    elif "remotion" in ok:
        ok.append("remotion-browser")
    return {
        "summary": {"ok": ok, "missing": missing, "optional": optional},
        "graphics": status,
        "setup": {
            "install": "npm ci --ignore-scripts --prefix scripts/graphics",
            "browser": "python scripts/gb.py graphics-doctor --prepare-browser",
            "diagnose": "python scripts/gb.py graphics-doctor",
            "tested": {"remotion": PINNED["remotion"], "react": PINNED["react"], "react-dom": PINNED["react-dom"]},
        },
    }


def attach_doctor(result):
    status = runtime_status()
    result["graphics"] = {
        "installed": not status["missing"] and bool(status["node"]),
        "pinned": PINNED,
        "missing": status["missing"],
    }
    if status["missing"]:
        result.setdefault("summary", {}).setdefault("optional", []).append(
            {
                "item": "remotion",
                "note": "Optional local graphics renderer; collection commands work without it. See graphics-doctor.",
            }
        )
    return result


def _prepare_browser(status):
    if not status["node"]:
        raise ValueError("Node.js is missing. Install Node 22+ before preparing the Remotion browser.")
    if status["missing"]:
        raise ValueError(
            "Install the optional graphics package first: npm ci --ignore-scripts --prefix scripts/graphics. "
            "Missing: " + ", ".join(status["missing"])
        )
    env = os.environ.copy()
    env[BROWSER_PREPARE_ENV] = "1"
    try:
        done = subprocess.run(
            [status["node"], str(WORKER), "--ensure-browser"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            env=env,
            check=False,
            timeout=300,
            cwd=str(PACKAGE_ROOT),
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise ValueError("Could not prepare the Remotion browser: " + str(exc)) from exc
    if done.returncode != 0:
        detail = (done.stderr or done.stdout or "").strip() or "unknown renderer error"
        raise ValueError("Remotion browser preparation failed: " + detail[:1200])
    payload = _last_json_line(done.stdout)
    executable = payload.get("path") if isinstance(payload, dict) else None
    if not isinstance(executable, str) or not Path(executable).is_file():
        raise ValueError("Remotion browser preparation did not return an existing executable path.")
    record = {"at": now(), "executable": executable, "type": payload.get("type")}
    _browser_marker().write_text(json.dumps(record, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    live = _probe_browser_status(status["node"])
    if not _marker_matches_live(record, live):
        raise ValueError("Prepared Remotion browser could not be verified without downloading.")
    return {"prepared": True, "marker": str(_browser_marker()), "detail": record}


def _template_source_paths(template, root=None, occurrence=None) -> dict[str, Path]:
    if template in ("map", "custom"):
        names = MAP_TEMPLATE_FILES if template == "map" else CUSTOM_TEMPLATE_FILES
        paths = {name: TEMPLATE_DIR / name for name in names}
        paths["Root.jsx"] = TEMPLATE_DIR / ("MapRoot.jsx" if template == "map" else "CustomRoot.jsx")
        if template == "custom":
            if (
                root is None
                or not isinstance(occurrence, dict)
                or not isinstance(occurrence.get("scene_content"), dict)
            ):
                raise ValueError("Custom scene source context is missing.")
            from .graphics_scenes import _live_source

            paths["AuthorScene.jsx"] = _live_source(root, occurrence["scene_content"])
        return paths
    names = TIMELINE_TEMPLATE_FILES if template == "timeline" else BACKGROUND_TEMPLATE_FILES
    return {
        name: TEMPLATE_DIR / ("TimelineRoot.jsx" if template == "timeline" and name == "Root.jsx" else name)
        for name in names
    }


def _require_templates(names=TEMPLATE_FILES, *, template="numeric-stat", root=None, occurrence=None):
    hashes = {}
    for name in names:
        source_paths = _template_source_paths(template, root, occurrence)
        src = source_paths[name] if name in source_paths else TEMPLATE_DIR / name
        if not src.is_file():
            raise ValueError("Graphics template missing in the skill: " + name)
        hashes[name] = digest(src)
    return hashes


def _font_sources():
    font_root = PACKAGE_ROOT / "node_modules" / "@fontsource" / "ibm-plex-sans" / "files"
    sources = {}
    for name in FONT_FILES:
        src = font_root / name
        if not src.is_file():
            raise ValueError(
                "Local IBM Plex Sans files are missing. Install the optional graphics package "
                "(npm ci --ignore-scripts --prefix scripts/graphics). Render will not use a network font."
            )
        sources[name] = src
    license_src = PACKAGE_ROOT / "node_modules" / "@fontsource" / "ibm-plex-sans" / "LICENSE"
    return sources, license_src if license_src.is_file() else None


def _copy_checked(src, dest, expected=None):
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(src, dest)
    actual = digest(dest)
    if expected is not None and actual != expected:
        raise ValueError("Frozen graphics input changed while copying: " + dest.name)
    return actual


def _write_json(path, payload):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _validate_job_encoding(job):
    if not isinstance(job, dict):
        raise ValueError("Frozen graphics job is missing encoding choices.")
    if job.get("codec") != "h264" or job.get("pixelFormat") != PIXEL_FORMAT:
        raise ValueError("Frozen graphics job must encode H.264 " + PIXEL_FORMAT + ".")
    if job.get("colorSpace") != COLOR_SPACE:
        raise ValueError("Frozen graphics job must set colorSpace to " + COLOR_SPACE + ".")
    if job.get("imageFormat") != IMAGE_FORMAT:
        raise ValueError("Frozen graphics job must set imageFormat to " + IMAGE_FORMAT + ".")
    audio = job.get("audio")
    cues = _as_dict(job.get("props")).get("sound_cues") if isinstance(job.get("props"), dict) else None
    if audio is None:
        if cues:
            raise ValueError("Silent graphics job cannot include sound cues.")
        return
    if not isinstance(audio, dict) or audio.get("mode") != "effects" or audio.get("codec") != "aac":
        raise ValueError("Frozen graphics job audio must be effects AAC.")
    if not isinstance(cues, list) or not cues:
        raise ValueError("Effects graphics job must include sound_cues.")
    vo = _as_dict(job.get("props")).get("vo") if isinstance(job.get("props"), dict) else None
    if vo is not None:
        raise ValueError("Frozen graphics job props cannot include voice-over.")


def _preview_rel(occurrence_id, version_id):
    return f"previews/graphics-{occurrence_id}-{version_id}.mp4"


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


def _finite_int(value):
    number = _finite_float(value)
    if number is None or number != int(number):
        return None
    return int(number)


def _parse_rate(rate):
    if not isinstance(rate, str) or not rate or rate in ("N/A", "0/0"):
        return None
    if "/" in rate:
        num, den = rate.split("/", 1)
        numerator = _finite_float(num)
        denominator = _finite_float(den)
        if numerator is None or denominator is None or denominator == 0:
            return None
        value = numerator / denominator
        return value if math.isfinite(value) else None
    return _finite_float(rate)


def _probe_json(path, extra_args):
    raw = media_run(["ffprobe", "-v", "error", *extra_args, "-of", "json", str(path)], op="graphics_probe")
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError("Rendered graphics metadata was not valid JSON.") from exc
    if not isinstance(data, dict):
        raise ValueError("Rendered graphics metadata was malformed.")
    return data


def _probe_stream_groups(data):
    streams = [item for item in (data.get("streams") or []) if isinstance(item, dict)]
    video = [item for item in streams if item.get("codec_type") == "video"]
    audio = [item for item in streams if item.get("codec_type") == "audio"]
    other = [item for item in streams if item.get("codec_type") not in ("video", "audio")]
    nb_streams = _finite_int((data.get("format") or {}).get("nb_streams"))
    return streams, video, audio, other, nb_streams


def _assert_probe_layout(groups, *, expect_audio):
    streams, video, audio, other, nb_streams = groups
    if other:
        raise ValueError("Rendered graphics include unexpected extra streams.")
    if expect_audio:
        if len(video) != 1 or len(audio) != 1 or (nb_streams is not None and nb_streams != EFFECTS_STREAM_COUNT):
            raise ValueError("Rendered file must contain exactly one H.264 video stream and one AAC audio stream.")
        if audio[0].get("codec_name") != "aac":
            raise ValueError(
                "Rendered graphics audio codec must be aac, found " + str(audio[0].get("codec_name")) + "."
            )
        if video[0].get("color_space") != COLOR_SPACE:
            raise ValueError("Rendered graphics color_space must be " + COLOR_SPACE + ".")
        return
    if audio:
        raise ValueError("Rendered graphics include unexpected audio; the initial composition is silent.")
    if len(video) != 1 or len(streams) != 1 or (nb_streams is not None and nb_streams != 1):
        raise ValueError("Rendered file must contain exactly one video stream.")


def _probe_artifact(path, *, expect_audio=False):
    data = _probe_json(
        path,
        [
            "-count_frames",
            "-show_entries",
            "stream=codec_name,codec_type,width,height,avg_frame_rate,r_frame_rate,nb_frames,nb_read_frames,pix_fmt,color_space,duration:format=duration,nb_streams",
        ],
    )
    groups = _probe_stream_groups(data)
    _assert_probe_layout(groups, expect_audio=expect_audio)
    video = groups[1]
    audio = groups[2]
    stream = video[0]
    frames = _finite_int(stream.get("nb_read_frames"))
    if frames is None:
        raise ValueError("Rendered graphics are missing a decoded frame count.")
    r_rate = _parse_rate(stream.get("r_frame_rate"))
    avg_rate = _parse_rate(stream.get("avg_frame_rate"))
    if r_rate is None or avg_rate is None:
        raise ValueError("Rendered graphics are missing a usable frame rate.")
    if r_rate != avg_rate:
        raise ValueError("Rendered graphics have inconsistent r_frame_rate and avg_frame_rate.")
    duration = _finite_float(stream.get("duration"))
    if duration is None:
        duration = _finite_float((data.get("format") or {}).get("duration"))
    info = {
        "codec_name": stream.get("codec_name"),
        "pix_fmt": stream.get("pix_fmt"),
        "width": _finite_int(stream.get("width")),
        "height": _finite_int(stream.get("height")),
        "fps": r_rate,
        "duration_s": duration,
        "nb_frames": frames,
    }
    if expect_audio:
        info["audio_codec"] = audio[0].get("codec_name")
        info["audio_streams"] = 1
        info["color_space"] = stream.get("color_space")
    return info


def _artifact_verify_problems(info, profile, duration_in_frames, *, expect_audio):
    problems = []
    if info["codec_name"] not in ("h264", "avc1"):
        problems.append("codec " + str(info["codec_name"]))
    if info["pix_fmt"] != "yuv420p":
        problems.append("pix_fmt " + str(info["pix_fmt"]))
    if info["width"] != profile["width"] or info["height"] != profile["height"]:
        problems.append(f"size {info['width']}x{info['height']}")
    expected_fps = float(profile["fps"])
    if info["fps"] is None or info["fps"] != expected_fps:
        problems.append("fps " + str(info["fps"]))
    expected_duration = duration_in_frames / expected_fps
    if info["duration_s"] is None or abs(info["duration_s"] - expected_duration) > (1.0 / expected_fps):
        problems.append("duration " + str(info["duration_s"]))
    if info["nb_frames"] is None:
        problems.append("missing decoded frame count")
    elif abs(info["nb_frames"] - duration_in_frames) > 1:
        problems.append("nb_frames " + str(info["nb_frames"]))
    problems.extend(_artifact_audio_problems(info, expect_audio=expect_audio))
    return problems


def _artifact_audio_problems(info, *, expect_audio):
    if not expect_audio:
        return []
    problems = []
    if info.get("audio_codec") != "aac" or info.get("audio_streams") != 1:
        problems.append("audio " + str(info.get("audio_codec")))
    if info.get("color_space") != COLOR_SPACE:
        problems.append("color_space " + str(info.get("color_space")))
    return problems


def _verify_complete(path, profile, duration_in_frames, *, expect_audio=False):
    media_run(
        ["ffmpeg", "-v", "error", "-xerror", "-i", str(path), "-f", "null", "-"],
        op="graphics_decode",
    )
    info = _probe_artifact(path, expect_audio=expect_audio)
    problems = _artifact_verify_problems(info, profile, duration_in_frames, expect_audio=expect_audio)
    if problems:
        raise ValueError("Rendered graphics failed verification: " + ", ".join(problems) + ".")
    return info


def _run_worker(worker, job_path, output, timeout=RENDER_TIMEOUT_S):
    env = os.environ.copy()
    env.pop(BROWSER_PREPARE_ENV, None)
    if worker.suffix.lower() == ".py":
        command = [sys.executable, str(worker), "--job", str(job_path)]
        cwd = str(worker.parent)
    else:
        node = shutil.which("node")
        if not node:
            raise ValueError("Node.js is required to render graphics. Collection commands still work without it.")
        command = [node, str(worker), "--job", str(job_path)]
        cwd = str(PACKAGE_ROOT)
        env["NODE_PATH"] = str(PACKAGE_ROOT / "node_modules")
    try:
        done = subprocess.run(
            command,
            capture_output=True,
            text=True,
            encoding="utf-8",
            check=False,
            timeout=timeout,
            cwd=cwd,
            env=env,
        )
    except subprocess.TimeoutExpired as exc:
        raise ValueError("Graphics render timed out after " + str(timeout) + "s. No retry was attempted.") from exc
    if done.returncode != 0:
        detail = (done.stderr or done.stdout or "").strip() or "worker exited " + str(done.returncode)
        raise ValueError("Graphics render failed: " + detail[:1200])
    if not Path(output).is_file():
        raise ValueError("Graphics worker exited 0 without writing the staging file.")
    return done


def _clip_props(occ, fps=None):
    props = {
        "value": occ["props"]["value"],
        "unit": occ["props"]["unit"],
        "label": occ["props"]["label"],
        "claim_status": occ["props"]["claim_status"],
        "claim_note": occ["props"]["claim_note"],
        "narration": occ["narration"],
        "timing_basis": occ["timing"]["basis"],
    }
    if occ["template"] == "timeline":
        from .graphics_timeline import clip_milestones

        props["title"] = occ["timeline"]["title"]
        props["milestones"] = clip_milestones(occ["timeline"], occ["timing"], fps, seconds_to_frame)
    if occ["template"] in ("map", "custom"):
        from .graphics_scenes import clip_scene

        props["scene"] = clip_scene(occ["scene_content"], occ["timing"], fps, seconds_to_frame)
    return props


def _node_version(node):
    try:
        done = subprocess.run(
            [node, "--version"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            check=False,
            timeout=30,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    return (done.stdout or "").strip() or None


def _require_browser(status):
    if not status["node"]:
        raise ValueError("Node.js is required to render graphics. Collection commands still work without it.")
    record = _browser_record()
    if record is None:
        raise ValueError(
            "The local Remotion browser is not prepared. Run "
            "`python scripts/gb.py graphics-doctor --prepare-browser` before rendering. "
            "A stale marker is not readiness. Render will not download a browser or a network font by itself."
        )
    live = _probe_browser_status(status["node"])
    if not _marker_matches_live(record, live):
        raise ValueError(
            "The recorded Remotion browser is missing, mismatched or stale. Run "
            "`python scripts/gb.py graphics-doctor --prepare-browser`. Render will not download a browser."
        )
    return live


def _file_sha256(path):
    if not path:
        return None
    candidate = Path(path)
    if not candidate.is_file():
        return None
    return digest(candidate)


def _build_runtime(kind, worker, status, browser):
    node = status.get("node")
    pkg_src = PACKAGE_ROOT / "package.json"
    lock_src = PACKAGE_ROOT / "package-lock.json"
    browser_path = None if browser is None else browser.get("path")
    remotion = kind == "remotion"
    return {
        "kind": kind,
        "pinned": dict(PINNED),
        "worker": str(worker),
        "worker_sha256": digest(worker),
        "node": node,
        "node_version": _node_version(node) if node else None,
        "node_sha256": _file_sha256(node) if remotion else None,
        "package_versions": dict(status["versions"]),
        "package_json_sha256": digest(pkg_src) if remotion else None,
        "package_lock_sha256": digest(lock_src) if remotion else None,
        "browser_executable": browser_path,
        "browser_type": None if browser is None else browser.get("type"),
        "browser_sha256": _file_sha256(browser_path) if remotion else None,
        "browser_version": None if browser is None else browser.get("actualVersion"),
    }


def _input_mapping(ref_pairs, input_hashes):
    mapping = {}
    seen_dest = {}
    for rel, _src in ref_pairs:
        frozen = _frozen_ref_rel(rel)
        key = os.path.normcase(frozen)
        previous = seen_dest.get(key)
        if previous is not None:
            raise ValueError("Frozen graphics inputs collide: " + previous + " and " + rel)
        seen_dest[key] = rel
        mapping[rel] = {"sha256": input_hashes[rel], "frozen": frozen}
    return mapping


def _freeze_refs(version_dir, ref_pairs, mapping):
    for rel, src in ref_pairs:
        spec = mapping[rel]
        dest = version_dir.joinpath(*spec["frozen"].split("/"))
        planned = _confine_planned(version_dir, dest)
        if planned.exists():
            raise ValueError("Frozen graphics input would overwrite another file: " + spec["frozen"])
        actual = _copy_checked(src, planned, spec["sha256"])
        if actual != spec["sha256"]:
            raise ValueError("Frozen graphics input does not match the recorded hash: " + rel)
    for rel, spec in mapping.items():
        dest = version_dir.joinpath(*spec["frozen"].split("/"))
        if not dest.is_file() or digest(dest) != spec["sha256"]:
            raise ValueError("Frozen graphics input is missing or changed: " + rel)
    return mapping


def _link_optional_modules(inputs_dir):
    dest = Path(inputs_dir) / "node_modules"
    src = PACKAGE_ROOT / "node_modules"
    if not src.is_dir():
        raise ValueError("Optional graphics packages are missing under scripts/graphics/node_modules.")
    if dest.exists() or dest.is_symlink():
        try:
            same = os.path.normcase(str(dest.resolve())) == os.path.normcase(str(src.resolve()))
        except OSError as exc:
            raise ValueError("Frozen worker module path could not be resolved.") from exc
        if same:
            return dest
        raise ValueError("Frozen worker module path already exists and will not be overwritten.")
    try:
        dest.symlink_to(src, target_is_directory=True)
        return dest
    except OSError as exc:
        comspec = os.environ.get("COMSPEC")
        if not comspec or not Path(comspec).is_file():
            raise ValueError("Could not link scripts/graphics/node_modules next to the frozen worker.") from exc
        done = subprocess.run(
            [comspec, "/c", "mklink", "/J", str(dest), str(src)],
            capture_output=True,
            text=True,
            encoding="utf-8",
            check=False,
        )
        if done.returncode != 0 or not dest.exists():
            detail = (done.stderr or done.stdout or "").strip()[:1200]
            raise ValueError(
                "Could not link scripts/graphics/node_modules next to the frozen worker. " + detail
            ) from exc
        return dest


def _fail_version(record, occ, ledger, exc, staging):
    if ledger.pending.exists():
        # A durable transaction owns the next recovery; never replace it with a failure.
        return
    if (record.get("render_progress") or {}).get("phase") == "published":
        record["render_progress"]["phase"] = "rendered"
    record["status"] = "failed"
    record["diagnostics"] = {
        "message": str(exc)[:DIAGNOSTIC_LIMIT],
        "staging": "staging/out.mp4" if staging is not None and Path(staging).is_file() else None,
    }
    record["artifact"] = None
    occ["stage"] = "render_failed"
    ledger.save("graphics-render-failed")


def render_command(ledger, args):  # noqa: C901, PLR0912, PLR0915 - staging first, then freeze, verify, publish
    graphics = ledger.data.get("graphics")
    if not isinstance(graphics, dict) or args.occurrence not in graphics.get("occurrences", {}):
        raise ValueError("Unknown graphics occurrence. Register it with graphics-assign first.")
    occ = graphics["occurrences"][args.occurrence]
    status = runtime_status()
    worker, kind = _worker_path()
    audio_record = occ.get("audio") if isinstance(occ.get("audio"), dict) else None
    background_record = occ.get("background") if isinstance(occ.get("background"), dict) else None
    source_paths = _template_source_paths(occ["template"], ledger.root, occ)
    source_names = tuple(source_paths)
    source_hashes = _require_templates(source_names, template=occ["template"], root=ledger.root, occurrence=occ)
    from .graphics_scenes import scene_readiness

    scene_reasons = scene_readiness(ledger.root, occ)
    if scene_reasons:
        raise ValueError("Scene content is not ready: " + "; ".join(scene_reasons))
    from .graphics_timeline import timeline_readiness

    timeline_reasons = timeline_readiness(ledger.root, occ)
    if timeline_reasons:
        raise ValueError("Timeline is not ready: " + "; ".join(timeline_reasons))
    ref_pairs = _confine_refs(ledger.root, _assignment_input_refs(occ), prefixes=INPUT_PREFIXES)
    font_hashes = {}
    font_sources = {}
    license_src = None
    browser = None
    lock_src = PACKAGE_ROOT / "package-lock.json"
    pkg_src = PACKAGE_ROOT / "package.json"
    if kind == "remotion":
        if status["missing"]:
            raise ValueError(
                "Optional Remotion runtime is not installed. Collection still works. "
                "Install with npm ci --ignore-scripts --prefix scripts/graphics. Missing: "
                + ", ".join(status["missing"])
            )
        if not lock_src.is_file() or not pkg_src.is_file():
            raise ValueError(
                "scripts/graphics/package.json or package-lock.json is missing; freeze cannot record the actual runtime."
            )
        font_sources, license_src = _font_sources()
        font_hashes = {name: digest(path) for name, path in font_sources.items()}
        browser = _require_browser(status)
    scene_id = occ["scene_id"]
    scene_dir = ledger.root / "graphics" / scene_id
    version_id = _next_version_id(graphics["versions"], scene_dir)
    version_dir = _confine_planned(ledger.root, scene_dir / version_id)
    if version_dir.exists():
        raise ValueError("Version directory already exists and will not be overwritten: " + str(version_dir))
    preview_rel = _preview_rel(occ["occurrence_id"], version_id)
    relative_artifact(preview_rel)
    preview_path = _confine_planned(ledger.root, ledger.root / preview_rel)
    if preview_path.exists():
        raise ValueError("Preview path already exists and will not be overwritten: " + preview_rel)
    staging = version_dir / "staging" / "out.mp4"
    assignment = copy.deepcopy(occ)
    style = copy.deepcopy(
        next(item for item in graphics["style_revisions"] if item["revision"] == occ["style_revision"])
    )
    props = _clip_props(occ, graphics["profile"]["fps"])
    input_hashes = {rel: digest(path) for rel, path in ref_pairs}
    mapping = _input_mapping(ref_pairs, input_hashes)
    if "material_use" in occ:
        for entry in occ.get("material_use") or []:
            rel = entry.get("ref") if isinstance(entry, dict) else None
            if rel not in input_hashes or entry.get("sha256") != input_hashes[rel]:
                raise ValueError(
                    "material-use hash does not match the referenced file. Record a new assignment and version; "
                    "permission is not retrofitted onto an already frozen result."
                )
    runtime = _build_runtime(kind, worker, status, browser)
    fingerprints = {
        "style_revision": occ["style_revision"],
        "assignment_sha256": _payload_hash(assignment),
        "style_sha256": _payload_hash(style),
        "props_sha256": _payload_hash(props),
        "source": source_hashes,
        "fonts": font_hashes,
        "inputs": mapping,
        "timing": copy.deepcopy(occ["timing"]),
        "profile": copy.deepcopy(graphics["profile"]),
        "runtime": runtime,
    }
    if isinstance(assignment.get("facts"), dict):
        fingerprints["facts"] = {"sha256": _payload_hash(assignment["facts"])}
    if isinstance(assignment.get("alignment"), dict):
        fingerprints["alignment"] = {"sha256": _payload_hash(assignment["alignment"])}
    record = {
        "id": version_id,
        "occurrence_id": occ["occurrence_id"],
        "scene_id": scene_id,
        "template": occ["template"],
        "composition": occ["composition"],
        "parent": occ.get("current_version"),
        "status": "staging",
        "at": now(),
        "assignment": assignment,
        "style": style,
        "props": props,
        "profile": copy.deepcopy(graphics["profile"]),
        "timing": copy.deepcopy(occ["timing"]),
        "fingerprints": fingerprints,
        "font_terms": "OFL-1.1" if kind == "remotion" else "test-stub",
        "artifact": None,
        "diagnostics": None,
        "approval": None,
    }
    if audio_record is not None and _audio_duration_repair_reasons(occ):
        raise ValueError(
            "Scene duration changed after audio was attached. Run graphics-audio for "
            + occ["occurrence_id"]
            + " so cues and VO keep their declared placement. This render did not drop or clamp audio."
        )
    from .graphics_continuation import register_render_attempt

    register_render_attempt(graphics, occ, record, repair=getattr(args, "repair", False))
    graphics["versions"][version_id] = record
    ledger.save("graphics-render-staging")
    try:
        _confine_planned(ledger.root, version_dir)
        source_dir = version_dir / "source"
        font_dir = version_dir / "inputs" / "fonts"
        public_fonts = version_dir / "public" / "fonts"
        for name in source_names:
            _copy_checked(source_paths[name], source_dir / name, source_hashes[name])
        if kind == "remotion":
            for name, src in font_sources.items():
                copied = _copy_checked(src, font_dir / name, font_hashes[name])
                _copy_checked(src, public_fonts / name, copied)
            if license_src is not None:
                terms_path = font_dir / "OFL-1.1.txt"
                shutil.copyfile(license_src, terms_path)
                record["font_terms"] = terms_path.read_text(encoding="utf-8", errors="replace")[:2000]
            _copy_checked(lock_src, version_dir / "inputs" / "package-lock.json", runtime["package_lock_sha256"])
            _copy_checked(pkg_src, version_dir / "inputs" / "package.json", runtime["package_json_sha256"])
            _link_optional_modules(version_dir / "inputs")
        else:
            public_fonts.mkdir(parents=True, exist_ok=True)
        frozen_worker = version_dir / "inputs" / worker.name
        _copy_checked(worker, frozen_worker, runtime["worker_sha256"])
        _freeze_refs(version_dir, ref_pairs, mapping)
        if audio_record is not None:
            from .graphics_audio import freeze_audio

            frozen_audio = freeze_audio(ledger.root, version_dir, audio_record) or {}
            cues = frozen_audio.get("sound_cues") or []
            if cues:
                props["sound_cues"] = cues
                fingerprints["props_sha256"] = _payload_hash(props)
                fingerprints["audio"] = _audio_fingerprints(frozen_audio)
                record["props"] = props
                record["fingerprints"] = fingerprints
            vo_preview = frozen_audio.get("vo_preview")
            if isinstance(vo_preview, dict):
                record["vo_preview"] = vo_preview
        if background_record is not None:
            from .graphics_media import freeze_background

            frozen_bg = freeze_background(ledger.root, version_dir, background_record) or {}
            bg_props = frozen_bg.get("background")
            if isinstance(bg_props, dict):
                props["background"] = bg_props
                fingerprints["props_sha256"] = _payload_hash(props)
                fingerprints["background"] = _background_fingerprints(frozen_bg)
                record["props"] = props
                record["fingerprints"] = fingerprints
        job = {
            "composition": occ["composition"],
            "entry": str(source_dir / "index.jsx"),
            "packageRoot": str(PACKAGE_ROOT),
            "publicDir": str(version_dir / "public"),
            "output": str(staging),
            "width": graphics["profile"]["width"],
            "height": graphics["profile"]["height"],
            "fps": graphics["profile"]["fps"],
            "durationInFrames": occ["timing"]["duration_in_frames"],
            "props": props,
            "codec": "h264",
            "pixelFormat": PIXEL_FORMAT,
            "colorSpace": COLOR_SPACE,
            "imageFormat": IMAGE_FORMAT,
            "crf": 18,
            "concurrency": 1,
            "browserExecutable": None if browser is None else browser.get("path"),
        }
        if props.get("sound_cues"):
            job["audio"] = {"mode": "effects", "codec": "aac"}
        _validate_job_encoding(job)
        _write_json(version_dir / "job.json", job)
        _write_json(version_dir / "props.json", props)
        _write_json(version_dir / "assignment.json", assignment)
        _write_json(version_dir / "style.json", style)
        _write_json(version_dir / "fingerprints.json", fingerprints)
        record["render_progress"] = {"phase": "frozen"}
        ledger.save("graphics-render-frozen")
        staging.parent.mkdir(parents=True, exist_ok=True)
        if digest(frozen_worker) != runtime["worker_sha256"]:
            raise ValueError("Frozen graphics worker does not match the recorded hash.")
        _run_worker(frozen_worker, version_dir / "job.json", staging)
        expect_audio = bool(job.get("audio"))
        info = _verify_complete(
            staging, graphics["profile"], occ["timing"]["duration_in_frames"], expect_audio=expect_audio
        )
        record["render_progress"] = {"phase": "rendered", "sha256": digest(staging)}
        ledger.save("graphics-render-verified")
        return _publish_render_result(ledger, record, occ, info)
    except (OSError, shutil.Error) as exc:
        message = "Graphics freeze or publish failed: " + str(exc)
        _fail_version(record, occ, ledger, ValueError(message), staging)
        raise ValueError(message) from exc
    except ValueError as exc:
        _fail_version(record, occ, ledger, exc, staging)
        raise


def _publish_render_result(ledger, record, occurrence, info):
    """Publish only verified bytes. Existing matching bytes can finish an interrupted write."""
    expected = record["render_progress"]["sha256"]
    version_dir = _confine_planned(ledger.root, _version_dir(ledger.root, record["scene_id"], record["id"]))
    staging = _confine_declared_file(version_dir, "staging/out.mp4")
    preview_path = ledger.root / _preview_rel(occurrence["occurrence_id"], record["id"])
    if digest(staging) != expected:
        raise ValueError("Verified graphics staging bytes changed; publication refused.")
    published = version_dir / "preview.mp4"
    for planned in (preview_path, published):
        dest = _confine_planned(ledger.root, planned)
        if dest.exists():
            if not dest.is_file() or digest(dest) != expected:
                raise ValueError("Graphics publication collision; existing file preserved: " + dest.name)
        else:
            dest.parent.mkdir(parents=True, exist_ok=True)
            _copy_checked(staging, dest, expected)
    artifact = {
        "path": _preview_rel(occurrence["occurrence_id"], record["id"]),
        "sha256": expected,
        "width": info["width"],
        "height": info["height"],
        "fps": info["fps"],
        "duration_s": info["duration_s"],
        "nb_frames": info["nb_frames"],
        "codec": info["codec_name"],
        "pix_fmt": info["pix_fmt"],
        "verified": True,
    }
    if _version_has_effects(record):
        artifact.update(
            audio_codec=info.get("audio_codec"),
            audio_streams=info.get("audio_streams"),
            color_space=info.get("color_space"),
        )
    record["status"] = "complete"
    record["artifact"] = artifact
    record["render_progress"] = {"phase": "published", "sha256": expected}
    occurrence["current_version"] = record["id"]
    occurrence["stage"] = "ready_for_review"
    ledger.save("graphics-render")
    return {"version": record, "occurrence": occurrence, "review": artifact["path"], "approved": False}


def _assignment_diffs(frozen, current):
    if not isinstance(frozen, dict) or not isinstance(current, dict):
        return list(ASSIGNMENT_FIELDS)
    return [key for key in ASSIGNMENT_FIELDS if frozen.get(key) != current.get(key)]


def _assignment_changed(frozen, current):
    return bool(_assignment_diffs(frozen, current))


def _audio_fingerprints(frozen):
    cues = frozen.get("sound_cues") or []
    assets = []
    for item in frozen.get("assets") or []:
        if not isinstance(item, dict):
            continue
        assets.append(
            {
                "id": item.get("id"),
                "kind": item.get("kind") or "effect",
                "ref": item.get("ref"),
                "frozen_ref": item.get("frozen_ref"),
                "sha256": item.get("sha256"),
                "source_url": item.get("source_url"),
                "terms_url": item.get("terms_url"),
                "license": item.get("license"),
                "conditions": item.get("conditions"),
                "rendered_use": item.get("rendered_use"),
                "raw_redistribution": item.get("raw_redistribution"),
            }
        )
    return {
        "mode": "effects",
        "codec": "aac",
        "cues_sha256": _payload_hash(cues),
        "assets": assets,
    }


def _background_fingerprints(frozen):
    props = frozen.get("background") if isinstance(frozen, dict) else None
    assets = []
    for item in frozen.get("assets") or []:
        if not isinstance(item, dict):
            continue
        assets.append(
            {
                "id": item.get("id") or item.get("candidate_id"),
                "kind": item.get("kind") or "background",
                "ref": item.get("ref"),
                "frozen_ref": item.get("frozen_ref"),
                "sha256": item.get("sha256"),
                "candidate_id": item.get("candidate_id"),
                "source_url": item.get("source_url"),
                "rendered_use": item.get("rendered_use"),
                "raw_redistribution": item.get("raw_redistribution"),
                "conditions": item.get("conditions"),
            }
        )
    return {
        "sha256": _payload_hash(props) if isinstance(props, dict) else _payload_hash({}),
        "assets": assets,
    }


def _facts_decision_choices(facts):
    choices = []
    for conflict in facts.get("conflicts") or []:
        if not isinstance(conflict, dict):
            continue
        decision = conflict.get("decision")
        if isinstance(decision, dict) and decision.get("choice"):
            choices.append(decision.get("choice"))
        else:
            choices.append(None)
    return choices


def _apply_facts_display(root, occ):
    facts = occ.get("facts")
    if not isinstance(facts, dict):
        return
    props = occ.get("props")
    if not isinstance(props, dict):
        return
    if "props_before_facts" not in occ:
        occ["props_before_facts"] = {
            "value": props.get("value"),
            "unit": props.get("unit"),
            "claim_status": props.get("claim_status"),
            "claim_note": props.get("claim_note"),
        }
    original = occ["props_before_facts"]
    if occ.get("template") in ("timeline", "map", "custom"):
        from .graphics_scenes import scene_readiness
        from .graphics_timeline import timeline_readiness

        props["claim_status"] = original["claim_status"]
        present = "timeline" in occ or "scene_content" in occ
        if (
            present
            and not timeline_readiness(root, occ)
            and not scene_readiness(root, occ)
            and original["claim_status"] != "synthetic"
        ):
            props["claim_status"] = "sourced"
            titles = [source["title"] for source in facts.get("sources") or []]
            props["claim_note"] = " · ".join(titles)[:500] or SOURCED_CLAIM_NOTE
        return
    from .graphics_facts import facts_readiness

    status = facts_readiness(root, facts)
    choices = _facts_decision_choices(facts)
    keep = "keep_scenario" in choices
    open_or_deferred = None in choices or "defer" in choices
    if keep or open_or_deferred or not status.get("ready"):
        props["value"] = original.get("value")
        props["unit"] = original.get("unit")
        props["claim_status"] = original.get("claim_status")
        props["claim_note"] = original.get("claim_note")
        return
    values = facts.get("values") or []
    primary = values[0] if values and isinstance(values[0], dict) else None
    if primary is None:
        return
    if not _bounded_text(primary.get("value"), 500) or not _bounded_text(primary.get("unit"), 500):
        return
    props["value"] = primary["value"]
    props["unit"] = primary["unit"]
    props["claim_status"] = "sourced"
    sources = {source["id"]: source for source in facts.get("sources") or []}
    titles = [sources[source_id]["title"] for source_id in primary.get("source_ids") or []]
    props["claim_note"] = " · ".join(titles)[:500] or SOURCED_CLAIM_NOTE


def _require_occurrence(ledger, occurrence_id):
    graphics = ledger.data.get("graphics")
    if not isinstance(graphics, dict) or occurrence_id not in graphics.get("occurrences", {}):
        raise ValueError("Unknown graphics occurrence. Register it with graphics-assign first.")
    return graphics, graphics["occurrences"][occurrence_id]


def timeline_command(ledger, args):
    from .graphics_timeline import normalize_timeline

    graphics, occurrence = _require_occurrence(ledger, args.occurrence)
    if occurrence["template"] != "timeline":
        raise ValueError("graphics-timeline requires an occurrence assigned with --template timeline.")
    payload = load_bounded_json_file(ledger.root, args.file)
    occurrence["timeline"] = normalize_timeline(payload, occurrence["timing"])
    _apply_facts_display(ledger.root, occurrence)
    occurrence["stage"] = "authoring"
    ledger.save("graphics-timeline")
    return {"occurrence": occurrence, "profile": graphics["profile"]}


def facts_command(ledger, args):
    occ = _require_occurrence(ledger, args.occurrence)[1]
    payload = load_bounded_json_file(ledger.root, args.file)
    try:
        from .graphics_facts import normalize_facts
    except ImportError as exc:
        raise ValueError("Displayed-fact module is missing; graphics-facts cannot run in this snapshot.") from exc

    record = normalize_facts(ledger.root, payload)
    occ["facts"] = record
    _apply_facts_display(ledger.root, occ)
    occ["stage"] = "assigned"
    ledger.save("graphics-facts")
    return {"occurrence": occ, "facts": record}


def fact_resolve_command(ledger, args):
    occ = _require_occurrence(ledger, args.occurrence)[1]
    if not isinstance(occ.get("facts"), dict):
        raise ValueError("Occurrence has no saved fact evidence. Attach it with graphics-facts first.")
    try:
        from .graphics_facts import resolve_conflict
    except ImportError as exc:
        raise ValueError(
            "Displayed-fact module is missing; graphics-fact-resolve cannot run in this snapshot."
        ) from exc

    updated = resolve_conflict(occ["facts"], args.conflict, args.decision, args.by, args.statement)
    occ["facts"] = updated
    _apply_facts_display(ledger.root, occ)
    occ["stage"] = "assigned"
    ledger.save("graphics-fact-resolve")
    return {
        "occurrence": occ.get("occurrence_id"),
        "conflict": args.conflict,
        "decision": args.decision,
        "facts": updated,
    }


def audio_command(ledger, args):
    graphics, occ = _require_occurrence(ledger, args.occurrence)
    payload = load_bounded_json_file(ledger.root, args.file)
    try:
        from .graphics_audio import normalize_audio
    except ImportError as exc:
        raise ValueError("Graphics audio module is missing; graphics-audio cannot run in this snapshot.") from exc

    record = normalize_audio(ledger.root, payload, graphics.get("profile"), occ.get("timing"))
    occ["audio"] = record
    occ["stage"] = "assigned"
    ledger.save("graphics-audio")
    return {"occurrence": occ, "audio": record}


def background_command(ledger, args):
    graphics, occ = _require_occurrence(ledger, args.occurrence)
    payload = load_bounded_json_file(ledger.root, args.file)
    try:
        from .graphics_media import normalize_background
    except ImportError as exc:
        raise ValueError("Graphics media module is missing; graphics-background cannot run in this snapshot.") from exc

    record = normalize_background(
        ledger.root, payload, graphics.get("profile"), occ.get("timing"), items=ledger.data.get("items")
    )
    occ["background"] = record
    occ["stage"] = "assigned"
    ledger.save("graphics-background")
    return {"occurrence": occ, "background": record}


def _require_intact_result_artifact(root, result):
    from .narration import RESULT_PREFIX

    try:
        artifact = _confine_existing(root, result.get("artifact"), (RESULT_PREFIX,))
        actual = digest(artifact)
    except (OSError, ValueError) as exc:
        raise ValueError(
            "Narration result artifact is missing or unreadable. Matching will not use stale bytes."
        ) from exc
    if actual != result.get("artifact_sha256"):
        raise ValueError("Narration result artifact changed. Matching will not use stale bytes.")
    try:
        payload = json.loads(artifact.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("Narration result artifact could not be read.") from exc
    if not isinstance(payload, dict):
        raise ValueError("Narration result artifact must be a JSON object.")
    identity_reasons = _result_artifact_reasons(payload, result)
    if "incomplete_transcript" in identity_reasons:
        raise ValueError(
            "Narration result must not include a provider confidence field or a non-boolean timing_resolved."
        )
    if identity_reasons:
        raise ValueError("Narration result artifact does not match the saved transcript.")


def _intact_analysis(root, data, analysis_id):
    from .narration import PRIVATE_AUDIO_PREFIX

    narration = data.get("narration") if isinstance(data, dict) else None
    if not isinstance(narration, dict):
        raise ValueError("Unknown narration analysis. Complete narration-analyze first; matching does not transcribe.")
    analyses = _as_dict(narration.get("analyses"))
    recordings = _as_dict(narration.get("recordings"))
    analysis = analyses.get(analysis_id)
    if not isinstance(analysis, dict) or analysis.get("state") != "completed":
        raise ValueError(
            "Narration analysis " + str(analysis_id) + " is not a completed local result. Matching does not transcribe."
        )
    result = analysis.get("result")
    if not isinstance(result, dict):
        raise ValueError("Narration analysis " + str(analysis_id) + " has no saved transcript result.")
    if type(result.get("timing_resolved")) is not bool:
        raise ValueError("Narration result timing_resolved must be an exact boolean.")
    recording = recordings.get(analysis.get("recording_id"))
    if not isinstance(recording, dict):
        raise ValueError("Narration recording for analysis " + str(analysis_id) + " is missing.")
    _require_intact_result_artifact(root, result)
    try:
        snapshot = _confine_existing(root, recording.get("snapshot"), (PRIVATE_AUDIO_PREFIX,))
        snap_hash = digest(snapshot)
    except (OSError, ValueError) as exc:
        raise ValueError(
            "Narration recording snapshot is missing or unreadable. Matching will not use stale bytes."
        ) from exc
    if snap_hash != recording.get("sha256"):
        raise ValueError("Narration recording snapshot changed. Matching will not use stale bytes.")
    match_result = {
        "transcript": result.get("transcript"),
        "words": result.get("words"),
        "artifact_sha256": result.get("artifact_sha256"),
        "timing_resolved": result.get("timing_resolved"),
    }
    if recording.get("id") is None and analysis.get("recording_id"):
        recording = {**recording, "id": analysis.get("recording_id")}
    return analysis, recording, match_result, snapshot


def _require_intact_analysis(ledger, analysis_id):
    return _intact_analysis(ledger.root, ledger.data, analysis_id)


def _match_passages_from_occurrences(graphics, occurrence_ids):
    occurrences = graphics.get("occurrences") if isinstance(graphics.get("occurrences"), dict) else {}
    order = list(occurrence_ids) if occurrence_ids else list(occurrences)
    if not order:
        raise ValueError("Unknown graphics occurrence. Register it with graphics-assign first.")
    passages = []
    seen = set()
    for occ_id in order:
        if occ_id in seen:
            raise ValueError("Occurrence " + occ_id + " is listed more than once in the match order.")
        seen.add(occ_id)
        occ = occurrences.get(occ_id)
        if not isinstance(occ, dict):
            raise ValueError("Unknown graphics occurrence. Register it with graphics-assign first.")
        passages.append(
            {
                "occurrence_id": occ_id,
                "narration": occ.get("narration"),
                "chapter_context": occ.get("chapter_context"),
                "anchors": occ.get("anchors") or [],
                "purpose": occ.get("purpose"),
                "order": len(passages),
            }
        )
    return passages


def _explicit_timing_from_match(timing, fps):
    if not isinstance(timing, dict):
        return None
    if timing.get("basis") == "explicit":
        _validate_timing(timing, fps)
        return copy.deepcopy(timing)
    start_s = timing.get("start_s")
    end_s = timing.get("end_s")
    if start_s is None or end_s is None:
        return None
    start_frame = seconds_to_frame(start_s, fps)
    end_frame = seconds_to_frame(end_s, fps)
    if end_frame <= start_frame:
        raise ValueError("Explicit timing requires end after start.")
    resolved = {
        "basis": "explicit",
        "start_s": float(start_s),
        "end_s": float(end_s),
        "start_frame": start_frame,
        "end_frame": end_frame,
        "duration_in_frames": max(1, end_frame - start_frame),
        "duration_s": float(end_s) - float(start_s),
    }
    _validate_timing(resolved, fps)
    return resolved


def _apply_pending_timing(occ, timing, fps, *, root=None, profile=None, items=None, version=None):  # noqa: PLR0913 - Clock repair must receive current profile and candidate rights separately.
    resolved = _explicit_timing_from_match(timing, fps)
    if resolved is None:
        return None
    staged = copy.deepcopy(occ)
    staged["timing"] = copy.deepcopy(resolved)
    repair = _timing_repair_reasons(
        staged,
        root=root,
        version=version if version is not None else {"timing": resolved, "profile": profile},
        items=items,
        profile=profile,
    )
    occ["timing"] = resolved
    audio_repair = [reason for reason in repair if reason in ("audio_duration_repair_required", "audio_not_ready")]
    if not audio_repair:
        audio = occ.get("audio")
        if isinstance(audio, dict) and audio.get("duration_in_frames") != resolved["duration_in_frames"]:
            audio["duration_in_frames"] = resolved["duration_in_frames"]
    if repair:
        raise ValueError(
            "Accepted timing cannot keep the declared scene-local cues, full-recording VO clocks or background "
            "coverage. Run graphics-audio and graphics-background for "
            + str(occ.get("occurrence_id"))
            + " so the new duration is attached without dropping or clamping audio, effects or background. "
            "Earlier versions were not rewritten. Repair: " + ", ".join(repair) + "."
        )
    return resolved


def _alignment_preview_identity(record, item):
    return _payload_hash(
        {
            "analysis_id": record.get("analysis_id"),
            "recording_id": record.get("recording_id"),
            "recording_sha256": record.get("recording_sha256"),
            "transcript_sha256": record.get("transcript_sha256"),
            "input_fingerprint": record.get("input_fingerprint"),
            "candidate_id": item.get("id"),
            "start_s": item.get("start_s"),
            "end_s": item.get("end_s"),
            "word_start": item.get("word_start"),
            "word_end": item.get("word_end"),
        }
    )


def _alignment_preview_rel(occurrence_id, identity_sha):
    return "previews/alignment-" + str(occurrence_id) + "-" + str(identity_sha)[:16] + ".wav"


def _preview_context_record(record, item, identity_sha, rel, digest_value=None, duration_s=None, error=None):  # noqa: PLR0913, PLR0917 - Preview metadata keeps identity, safe ref, hash, duration and error independently bound.
    payload = {
        "ref": rel,
        "analysis_id": record.get("analysis_id"),
        "recording_id": record.get("recording_id"),
        "recording_sha256": record.get("recording_sha256"),
        "transcript_sha256": record.get("transcript_sha256"),
        "input_fingerprint": record.get("input_fingerprint"),
        "candidate_id": item.get("id"),
        "start_s": item.get("start_s"),
        "end_s": item.get("end_s"),
        "identity_sha256": identity_sha,
    }
    if digest_value is not None:
        payload["sha256"] = digest_value
    if duration_s is not None:
        payload["duration_s"] = duration_s
    if error:
        payload["error"] = error
        payload.pop("sha256", None)
    return payload


def _preview_reparse(path):
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
    return bool(attrs & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400))


def _preview_same_context(existing, identity_sha, dest, expected_duration, fps):
    if (
        not isinstance(existing, dict)
        or existing.get("error")
        or existing.get("identity_sha256") != identity_sha
        or not _sha256(existing.get("sha256"))
        or expected_duration is None
        or existing.get("duration_s") is None
        or not fps
    ):
        return False
    try:
        if dest.is_symlink() or not dest.is_file() or _preview_reparse(dest):
            return False
        actual = digest(dest)
    except OSError:
        return False
    if existing.get("sha256") != actual:
        return False
    stored_duration = existing["duration_s"]
    try:
        return abs(float(stored_duration) - float(expected_duration)) <= (1.0 / float(fps))
    except (TypeError, ValueError):
        return False


def _iter_alignment_preview_items(record):
    items = [item for item in record.get("candidates") or [] if isinstance(item, dict)]
    if record.get("selected_candidate_id") is None and isinstance(record.get("timing"), dict):
        timing = record.get("timing")
        if timing.get("start_s") is not None and timing.get("end_s") is not None:
            items.append(
                {
                    "id": "override",
                    "start_s": timing.get("start_s"),
                    "end_s": timing.get("end_s"),
                }
            )
    return items


def _prior_preview_for_identity(previous, identity_sha):
    if not isinstance(previous, dict):
        return None
    for stored in previous.values():
        if isinstance(stored, dict) and stored.get("identity_sha256") == identity_sha and not stored.get("error"):
            return stored
    return None


def _preview_path_occupied(dest):
    try:
        return dest.exists() or dest.is_symlink() or _preview_reparse(dest)
    except OSError:
        return True


def _publish_alignment_previews(root, occ, record, snapshot, fps):
    previous = occ.get("alignment_previews") if isinstance(occ.get("alignment_previews"), dict) else {}
    published = {}
    extract = None
    extract_error = None
    try:
        from .graphics_audio import _extract_vo_excerpt

        extract = _extract_vo_excerpt
    except ImportError:
        extract_error = "extraction_unavailable"
    for item in _iter_alignment_preview_items(record):
        cand_id = item.get("id")
        start_s = item.get("start_s")
        end_s = item.get("end_s")
        if not isinstance(cand_id, str) or not cand_id or start_s is None or end_s is None:
            continue
        identity_sha = _alignment_preview_identity(record, item)
        rel = _alignment_preview_rel(occ.get("occurrence_id"), identity_sha)
        expected_duration = float(end_s) - float(start_s)
        existing = _prior_preview_for_identity(previous, identity_sha)
        try:
            dest = _confine_planned(root, Path(root) / rel)
        except ValueError:
            published[cand_id] = _preview_context_record(record, item, identity_sha, rel, error="occupied_preview")
            continue
        if _preview_path_occupied(dest):
            if _preview_same_context(existing, identity_sha, dest, expected_duration, fps):
                published[cand_id] = existing
            else:
                published[cand_id] = _preview_context_record(record, item, identity_sha, rel, error="occupied_preview")
            continue
        if extract is None:
            published[cand_id] = _preview_context_record(
                record, item, identity_sha, rel, error=extract_error or "extraction_failed"
            )
            continue
        if snapshot is None:
            published[cand_id] = _preview_context_record(record, item, identity_sha, rel, error="missing_preview")
            continue
        try:
            excerpt_hash, duration_s = extract(snapshot, dest, start_s, end_s, fps)
        except (OSError, ValueError):
            published[cand_id] = _preview_context_record(record, item, identity_sha, rel, error="extraction_failed")
            continue
        published[cand_id] = _preview_context_record(
            record, item, identity_sha, rel, digest_value=excerpt_hash, duration_s=duration_s
        )
    occ["alignment_previews"] = published
    return published


def match_command(ledger, args):
    graphics = ledger.data.get("graphics")
    if not isinstance(graphics, dict) or not graphics.get("occurrences"):
        raise ValueError("Unknown graphics occurrence. Register it with graphics-assign first.")
    try:
        from .narration_alignment import match_passages
    except ImportError as exc:
        raise ValueError("Narration alignment module is missing; narration-match cannot run in this snapshot.") from exc

    analysis, recording, match_result, snapshot = _require_intact_analysis(ledger, args.analysis)
    passages = _match_passages_from_occurrences(graphics, getattr(args, "occurrence", None))
    fps = graphics.get("profile", {}).get("fps") if isinstance(graphics.get("profile"), dict) else DEFAULT_FPS
    matched = match_passages(
        match_result,
        passages,
        analysis_id=analysis.get("id"),
        recording_id=recording.get("id"),
        recording_sha256=recording.get("sha256"),
        recording_duration_s=recording.get("duration_s"),
        fps=fps,
    )
    if not isinstance(matched, dict):
        raise ValueError("Alignment match_passages must return a dict keyed by occurrence_id.")
    _bind_alignment_match_group(graphics, [item["occurrence_id"] for item in passages])
    attached = []
    profile = _as_dict(graphics.get("profile"))
    for occ_id, record in matched.items():
        occ = graphics["occurrences"].get(occ_id)
        if not isinstance(occ, dict):
            raise ValueError("Unknown graphics occurrence. Register it with graphics-assign first.")
        occ["alignment"] = record
        occ["stage"] = "assigned"
        if isinstance(record, dict) and record.get("state") == "resolved":
            with suppress(ValueError):
                _apply_pending_timing(
                    occ,
                    record.get("timing"),
                    fps,
                    root=ledger.root,
                    profile=profile,
                    items=ledger.data.get("items"),
                )
        _publish_alignment_previews(ledger.root, occ, record if isinstance(record, dict) else {}, snapshot, fps)
        attached.append(occ_id)
    ledger.save("narration-match")
    return {
        "analysis_id": analysis.get("id"),
        "recording_id": recording.get("id"),
        "occurrences": attached,
        "matches": {occ_id: graphics["occurrences"][occ_id].get("alignment") for occ_id in attached},
        "retranscribed": False,
    }


def _timing_resolve_choice(args):
    candidate_id = getattr(args, "candidate", None)
    start_s = getattr(args, "start", None)
    end_s = getattr(args, "end", None)
    has_candidate = isinstance(candidate_id, str) and bool(candidate_id.strip())
    has_interval = start_s is not None or end_s is not None
    if has_candidate and has_interval:
        raise ValueError("Use --candidate or --start/--end, not both.")
    if isinstance(candidate_id, str) and has_candidate:
        return candidate_id.strip(), None, None
    if start_s is None or end_s is None:
        raise ValueError("graphics-timing-resolve requires --candidate or both --start and --end.")
    return None, start_s, end_s


def _alignment_snapshot(root, data, updated):
    analysis_id = updated.get("analysis_id") if isinstance(updated, dict) else None
    if not analysis_id:
        return None
    try:
        _analysis, _recording, _result, snapshot = _intact_analysis(root, data, analysis_id)
    except ValueError:
        return None
    return snapshot


def timing_resolve_command(ledger, args):
    graphics, occ = _require_occurrence(ledger, args.occurrence)
    record = occ.get("alignment")
    if not isinstance(record, dict):
        raise ValueError("Occurrence has no saved alignment record. Run narration-match first.")
    try:
        from .narration_alignment import correct_match
    except ImportError as exc:
        raise ValueError(
            "Narration alignment module is missing; graphics-timing-resolve cannot run in this snapshot."
        ) from exc

    candidate_id, start_s, end_s = _timing_resolve_choice(args)
    statement = getattr(args, "statement", None)
    by = getattr(args, "by", None)
    if not isinstance(by, str) or not by.strip():
        raise ValueError("Informe quem corrigiu o intervalo.")
    if not isinstance(statement, str) or not statement.strip():
        raise ValueError("A correção exige --statement com a frase exata já recebida.")
    profile = _as_dict(graphics.get("profile"))
    blockers = _alignment_identity_blockers(ledger.root, occ, ledger.data, profile)
    if blockers:
        raise ValueError(
            "Cannot apply this saved match: current recording, result, scenario or profile drifted. "
            "Rematch without retranscribing unchanged audio. Blockers: " + ", ".join(blockers) + "."
        )
    updated = correct_match(
        record,
        candidate_id=candidate_id,
        start_s=start_s,
        end_s=end_s,
        by=by.strip(),
        statement=statement.strip(),
        at=now(),
    )
    choice = {"candidate_id": candidate_id, "start_s": start_s, "end_s": end_s}
    if _alignment_replay(record, updated, by=by.strip(), statement=statement.strip(), choice=choice):
        return {
            "occurrence": occ.get("occurrence_id"),
            "alignment": record,
            "idempotent": True,
            "retranscribed": False,
            "by": by.strip(),
            "statement": statement.strip(),
        }
    fps = profile.get("fps") if isinstance(profile.get("fps"), (int, float)) else DEFAULT_FPS
    staged = copy.deepcopy(occ)
    staged["alignment"] = updated
    staged["stage"] = "assigned"
    repair = None
    try:
        _apply_pending_timing(
            staged,
            updated.get("timing") if isinstance(updated, dict) else None,
            fps,
            root=ledger.root,
            profile=profile,
            items=ledger.data.get("items"),
        )
    except ValueError as exc:
        repair = str(exc)
    snapshot = _alignment_snapshot(ledger.root, ledger.data, updated)
    _publish_alignment_previews(ledger.root, staged, updated if isinstance(updated, dict) else {}, snapshot, fps)
    graphics["occurrences"][args.occurrence] = staged
    ledger.save("graphics-timing-resolve")
    result = {
        "occurrence": staged.get("occurrence_id"),
        "alignment": updated,
        "timing": staged.get("timing"),
        "idempotent": False,
        "retranscribed": False,
        "by": by.strip(),
        "statement": statement.strip(),
    }
    if repair:
        result["repair"] = repair
        result["audio_duration_repair_required"] = "audio_duration_repair_required" in repair
    return result


def sound_import_command(ledger, args):
    try:
        from .graphics_audio import import_sfx_command
    except ImportError as exc:
        raise ValueError(
            "Graphics audio module is missing; graphics-sound-import cannot run in this snapshot."
        ) from exc

    return import_sfx_command(ledger, args)


def _storyboard_list(heading, items):
    if not items:
        return []
    parts = [f"<p>{_esc(heading)}</p><ul>"]
    parts.extend(f"<li>{_esc(item)}</li>" for item in items)
    parts.append("</ul>")
    return parts


def _storyboard_number(value):
    if type(value) is int:
        return _esc(value)
    if type(value) is float:
        return _esc(int(value) if value.is_integer() else value)
    return _esc(value)


def _storyboard_timing(timing, *, current=False):
    if not isinstance(timing, dict):
        return []
    basis = timing.get("basis")
    frames = _storyboard_number(timing.get("duration_in_frames"))
    label = "Current timing: " if current else ""
    if basis == "explicit":
        duration = _storyboard_number(timing.get("duration_s"))
        start_s = _storyboard_number(timing.get("start_s"))
        end_s = _storyboard_number(timing.get("end_s"))
        start_frame = _storyboard_number(timing.get("start_frame"))
        end_frame = _storyboard_number(timing.get("end_frame"))
        text = (
            f"{label}Explicit {start_s}–{end_s} s (frames {start_frame}–{end_frame}) "
            f"· Duration {duration} s · {frames} frames"
        )
    elif basis == "estimated":
        duration = _storyboard_number(timing.get("duration_s"))
        text = f"{label}Estimated duration {duration} s · {frames} frames"
    else:
        return []
    return [f'<p class="graphics-timing">{text}</p>']


def _storyboard_anchor_item(item):
    if not isinstance(item, dict):
        return ""
    text = _esc(item.get("text"))
    stamp = item.get("t_s")
    if stamp is None:
        return f'<li class="graphics-original">{text}</li>'
    return (
        f'<li class="graphics-original"><span class="graphics-anchor-time">'
        f"{_storyboard_number(stamp)} s</span> {text}</li>"
    )


def _storyboard_anchors(anchors, heading="Scenario anchors:"):
    if not isinstance(anchors, list) or not anchors:
        return []
    items = [item for item in (_storyboard_anchor_item(row) for row in anchors) if item]
    if not items:
        return []
    return [f'<p>{_esc(heading)}</p><ul class="graphics-anchors">', *items, "</ul>"]


def _storyboard_facts(shown):
    facts = shown.get("facts") if isinstance(shown, dict) else None
    if not isinstance(facts, dict):
        return []
    public = _public_facts(facts)
    parts = ['<div class="graphics-facts">', "<p>Displayed-fact evidence (original narration is unchanged):</p>"]
    parts.extend(
        "<p>Value "
        + _esc(item.get("value"))
        + " "
        + _esc(item.get("unit"))
        + " · definition "
        + _esc(item.get("definition"))
        + " · geography "
        + _esc(item.get("geography"))
        + " · date "
        + _esc(item.get("reference_date"))
        + ".</p>"
        for item in public.get("values") or []
    )
    for source in public.get("sources") or []:
        kind = "chart image" if source.get("kind") == "chart_image" else "source data"
        parts.append(
            "<p>Source "
            + _esc(source.get("title"))
            + " ("
            + _esc(kind)
            + "): "
            + _esc(source.get("url"))
            + " · date "
            + _esc(source.get("reference_date"))
            + " · rendered use "
            + _esc(source.get("rendered_use"))
            + " · raw redistribution "
            + _esc(source.get("raw_redistribution"))
            + " · "
            + _esc(source.get("conditions"))
            + ".</p>"
        )
    for conflict in public.get("conflicts") or []:
        decision = conflict.get("decision") if isinstance(conflict.get("decision"), dict) else None
        if decision and decision.get("choice") == "keep_scenario":
            decision_text = KEEP_SCENARIO_NOTE + " Statement: " + str(decision.get("statement") or "")
        elif decision:
            decision_text = (
                "Decision "
                + str(decision.get("choice"))
                + " by "
                + str(decision.get("by") or "")
                + ": "
                + str(decision.get("statement") or "")
            )
        else:
            decision_text = "Unresolved conflict; delivery stays blocked for this occurrence."
        parts.append(
            "<p>Conflict "
            + _esc(conflict.get("id"))
            + ": "
            + _esc(conflict.get("explanation"))
            + " Proposed correction: "
            + _esc(conflict.get("proposed_correction"))
            + " "
            + _esc(decision_text)
            + "</p>"
        )
    parts.append("</div>")
    return parts


def _storyboard_audio(shown):
    audio = shown.get("audio") if isinstance(shown, dict) else None
    if not isinstance(audio, dict):
        return []
    parts = ['<div class="graphics-audio">', "<p>Sound cues (voice-over is not embedded in the clip):</p><ul>"]
    for effect in audio.get("effects") or []:
        if not isinstance(effect, dict):
            continue
        parts.append(
            "<li>"
            + _esc(effect.get("id"))
            + " start frame "
            + _esc(effect.get("start_frame"))
            + " · duration "
            + _esc(effect.get("duration_s"))
            + " s · rendered use "
            + _esc(effect.get("rendered_use"))
            + " · raw redistribution "
            + _esc(effect.get("raw_redistribution"))
            + "</li>"
        )
    parts.append("</ul></div>")
    return parts


def _storyboard_background(shown):
    background = shown.get("background") if isinstance(shown, dict) else None
    if not isinstance(background, dict):
        return []
    public = _public_background(background)
    suitability = _as_dict(public.get("suitability"))
    material = _as_dict(public.get("material_use"))
    parts = [
        '<div class="graphics-background">',
        "<p>Background "
        + _esc(public.get("kind"))
        + " "
        + _esc(public.get("width"))
        + "×"
        + _esc(public.get("height"))
        + " · fit "
        + _esc(public.get("fit"))
        + " · source "
        + _esc(public.get("ref"))
        + " · candidate "
        + _esc(public.get("candidate_id"))
        + ".</p>",
    ]
    if public.get("source_start_s") is not None or public.get("local_start_s") is not None:
        parts.append(
            "<p>Background clocks: source "
            + _esc(public.get("source_start_s"))
            + "–"
            + _esc(public.get("source_end_s"))
            + " s · local "
            + _esc(public.get("local_start_s"))
            + "–"
            + _esc(public.get("local_end_s"))
            + " s · representation offset "
            + _esc(public.get("representation_source_start_s"))
            + " s. FullHD composition is not native 1080p source proof.</p>"
        )
    else:
        parts.append("<p>Still image background has no fabricated time interval.</p>")
    parts.append(
        "<p>Suitability (preview access is not final use): "
        + _esc(suitability.get("by"))
        + " · "
        + _esc(suitability.get("statement"))
        + ". Rendered use "
        + _esc(material.get("rendered_use") or public.get("rendered_use"))
        + " · raw redistribution "
        + _esc(material.get("raw_redistribution") or public.get("raw_redistribution"))
        + " · "
        + _esc(material.get("conditions") or public.get("conditions"))
        + ".</p>"
    )
    parts.append("</div>")
    return parts


def _storyboard_alignment_audio(ref, candidate_id, error=None, label="Candidate"):
    if isinstance(ref, str) and ref.startswith("previews/"):
        return (
            f'<audio class="graphics-alignment-preview" controls preload="metadata" '
            f'src="{_esc(ref)}" data-candidate="{_esc(candidate_id)}"></audio>'
        )
    if error:
        return "<p>" + _esc(label) + " preview unavailable: " + _esc(error) + ".</p>"
    return ""


def _storyboard_alignment_candidate(item):
    if not isinstance(item, dict):
        return ""
    preview = _as_dict(item.get("preview"))
    ref = preview.get("ref")
    audio = _storyboard_alignment_audio(ref, item.get("id"), item.get("preview_error"), "Candidate")
    evidence = item.get("evidence")
    if evidence is None:
        evidence = {
            "textual": item.get("textual_evidence"),
            "anchor": item.get("anchor_evidence"),
            "order": item.get("order_evidence"),
        }
    evidence_text = json.dumps(evidence, ensure_ascii=False) if evidence is not None else ""
    word_start = item.get("word_start")
    word_end = item.get("word_end")
    return (
        '<li data-candidate-id="'
        + _esc(item.get("id"))
        + '">Candidate '
        + _esc(item.get("id"))
        + " · "
        + _esc(item.get("start_s"))
        + "–"
        + _esc(item.get("end_s"))
        + " s · words "
        + _esc(word_start)
        + "–"
        + _esc(word_end)
        + " · score "
        + _esc(item.get("score"))
        + " · "
        + _esc(item.get("recognized_text"))
        + " · evidence "
        + _esc(evidence_text)
        + audio
        + "</li>"
    )


def _storyboard_alignment(shown, occ=None, *, editable=False, root=None, form_only=False):
    alignment = shown.get("alignment") if isinstance(shown, dict) else None
    if not isinstance(alignment, dict):
        return []
    host = occ if isinstance(occ, dict) else shown
    public = _public_alignment(alignment, host, root=root)
    state = public.get("state")
    occ_id = host.get("occurrence_id") if isinstance(host, dict) else ""
    fingerprint = _alignment_review_fingerprint(host, alignment)
    row_id = "alignment:" + str(occ_id)
    scope = "current" if editable else "frozen"
    parts = [
        '<div class="graphics-alignment" data-alignment-occurrence="'
        + _esc(occ_id)
        + '" data-alignment-editable="'
        + ("1" if editable else "0")
        + '" data-alignment-scope="'
        + scope
        + '">',
    ]
    if not form_only:
        parts.append(
            "<p>Narration alignment state: " + _esc(state) + ". Unresolved matching is not scene timing or delivery. "
            "Estimated drafts stay distinct from explicit intervals.</p>"
        )
        if public.get("selected_candidate_id"):
            parts.append("<p>Selected candidate " + _esc(public.get("selected_candidate_id")) + ".</p>")
        parts.extend(_storyboard_timing(public.get("timing") or {}))
        override = public.get("override_preview") if isinstance(public.get("override_preview"), dict) else None
        if override:
            parts.append("<p>Manual override excerpt (bounded preview; the original recording is not served):</p>")
            parts.append(
                _storyboard_alignment_audio(
                    override.get("ref"),
                    "override",
                    override.get("error"),
                    "Override",
                )
            )
        candidates = public.get("candidates") or []
        if candidates:
            parts.append("<p>Alignment candidates (bounded previews; the original recording is not served):</p>")
            parts.append('<ul class="graphics-alignment-candidates">')
            parts.extend(_storyboard_alignment_candidate(item) for item in candidates)
            parts.append("</ul>")
        decision = public.get("decision") if isinstance(public.get("decision"), dict) else None
        if decision:
            parts.append(
                "<p>Recorded correction by "
                + _esc(decision.get("by"))
                + ": "
                + _esc(decision.get("statement"))
                + ".</p>"
            )
    disabled = "" if editable else " disabled"
    stale_note = (
        "<p>Enter an explicit candidate confirmation or bounded start/end already received. "
        "Saving does not transcribe, retarget a frozen version, or grant timing approval.</p>"
        if editable
        else "<p>This saved version keeps its original alignment context. "
        "Record a correction on the current assignment; this form will not retarget.</p>"
    )
    parts.append(
        '<div class="graphics-alignment-correct" data-alignment-id="'
        + _esc(row_id)
        + '" data-alignment-signature="'
        + _esc(fingerprint)
        + '" data-alignment-epoch="'
        + _esc(fingerprint)
        + '" data-alignment-editable="'
        + ("1" if editable else "0")
        + '" data-alignment-scope="'
        + scope
        + '">'
        + stale_note
        + '<label>Candidate id <input data-alignment-candidate maxlength="80"'
        + disabled
        + "></label>"
        '<label>Start s <input data-alignment-start inputmode="decimal"' + disabled + "></label>"
        '<label>End s <input data-alignment-end inputmode="decimal"' + disabled + "></label>"
        '<label>Correction statement <textarea data-alignment-statement rows="2" maxlength="8000" '
        'placeholder="Exact human correction already received…"' + disabled + "></textarea></label>"
        '<button type="button" data-alignment-record' + disabled + ">Record correction</button>"
        '<p class="graphics-alignment-status" data-alignment-status role="status"></p>'
        "</div>"
    )
    parts.append("</div>")
    return parts


def _storyboard_timeline(shown):
    timeline = shown.get("timeline")
    if not isinstance(timeline, dict):
        return ""
    rows = "".join(
        "<li>"
        + _esc(item["date"])
        + " — "
        + _esc(item["label"])
        + " · fact "
        + _esc(item["fact_id"])
        + " · narration "
        + _esc(str(item["at_s"]))
        + "s</li>"
        for item in timeline["milestones"]
    )
    return "<section><h4>" + _esc(timeline["title"]) + "</h4><ol>" + rows + "</ol></section>"


def _storyboard_assignment_body(shown, *, editable=False, root=None):
    props = shown.get("props") or {}
    parts = [
        f'<p class="graphics-original">Chapter context: {_esc(shown.get("chapter_context"))}</p>',
        f"<p>Purpose: {_esc(shown.get('purpose'))}</p>",
        (
            f"<p>Displayed value: {_esc(props.get('value'))} {_esc(props.get('unit'))} "
            f"({_esc(props.get('claim_status'))}: {_esc(props.get('claim_note'))})</p>"
        ),
    ]
    parts.extend(_storyboard_timing(shown.get("timing") or {}))
    parts.extend(_storyboard_anchors(shown.get("anchors") or []))
    parts.extend(_storyboard_list("Unresolved questions:", shown.get("questions") or []))
    parts.extend(_storyboard_list("Additional-scene proposals:", shown.get("proposed_scenes") or []))
    parts.extend(_storyboard_facts(shown))
    parts.extend(_storyboard_audio(shown))
    parts.extend(_storyboard_background(shown))
    parts.extend(_storyboard_alignment(shown, shown, editable=editable, root=root))
    parts.append(_storyboard_timeline(shown))
    parts.append(_storyboard_scene_content(shown))
    return parts


def _storyboard_scene_content(shown):
    scene = shown.get("scene_content")
    if not isinstance(scene, dict):
        return ""
    clock = "draft clock" if shown["timing"]["basis"] == "estimated" else "narration"
    rows = "".join(
        "<li>"
        + _esc(beat["label"])
        + " · fact "
        + _esc(beat["fact_id"])
        + " · "
        + clock
        + " "
        + _esc(str(beat["at_s"]))
        + "s</li>"
        for beat in scene["beats"]
    )
    treatments = ", ".join(layer["treatment"] for layer in scene.get("layers", []))
    source = scene.get("data_ref", scene.get("source_ref"))
    return (
        "<section><h4>"
        + _esc(scene["title"])
        + "</h4><p>"
        + _esc(scene["caption"])
        + "</p><p>"
        + _esc(source)
        + " · "
        + _esc(treatments)
        + "</p><ol>"
        + rows
        + "</ol></section>"
    )


def _pending_text_blocks(diffs, current):
    parts = []
    if "chapter_context" in diffs:
        parts.append(
            f'<p class="graphics-original">Current chapter context: {_esc(current.get("chapter_context"))}</p>'
        )
    if "narration" in diffs:
        parts.append(f'<p class="graphics-original">Current narration: {_esc(current.get("narration"))}</p>')
    if "purpose" in diffs:
        parts.append(f"<p>Current purpose: {_esc(current.get('purpose'))}</p>")
    if "questions" in diffs:
        parts.extend(_storyboard_list("Current unresolved questions:", current.get("questions") or []))
    if "proposed_scenes" in diffs:
        parts.extend(_storyboard_list("Current additional-scene proposals:", current.get("proposed_scenes") or []))
    return parts


def _pending_structured_blocks(diffs, current, root=None):
    parts = []
    if "anchors" in diffs:
        parts.extend(_storyboard_anchors(current.get("anchors") or [], heading="Current scenario anchors:"))
    if "timing" in diffs:
        parts.extend(_storyboard_timing(current.get("timing") or {}, current=True))
    if "facts" in diffs:
        parts.extend(_storyboard_facts(current))
    if "audio" in diffs:
        parts.append("<p>Current sound cues or VO clocks changed after the saved version.</p>")
        parts.extend(_storyboard_audio(current))
    if "background" in diffs:
        parts.append("<p>Current background selection changed after the saved version.</p>")
        parts.extend(_storyboard_background(current))
    if "alignment" in diffs:
        parts.append("<p>Current narration alignment changed after the saved version.</p>")
        parts.extend(_storyboard_alignment(current, current, editable=True, root=root))
    if "props" in diffs:
        props = current.get("props") or {}
        parts.append(
            "<p>Current displayed value: "
            + _esc(props.get("value"))
            + " "
            + _esc(props.get("unit"))
            + " ("
            + _esc(props.get("claim_status"))
            + ").</p>"
        )
    return parts


def _storyboard_pending_changes(frozen, current, root=None):
    diffs = _assignment_diffs(frozen, current)
    if not diffs:
        return []
    parts = [
        (
            "<p>Saved version remains paired with the frozen assignment from render time. "
            "Current unrendered changes: " + _esc(", ".join(diffs)) + ".</p>"
        ),
        '<div class="graphics-pending-changes">',
        (
            "<p>Pending graphics assignment — unrendered changes after the saved version, "
            "without a new completed version, provider or human approval.</p>"
        ),
    ]
    parts.extend(_pending_text_blocks(diffs, current))
    parts.extend(_pending_structured_blocks(diffs, current, root=root))
    parts.append("</div>")
    return parts


def _matching_saved_request(occ_requests, version_id, comment):
    for req in occ_requests:
        if not isinstance(req, dict):
            continue
        if req.get("reviewed_version") == version_id and (req.get("text") or "") == (comment or ""):
            return req
    return None


def _review_frozen_context(version, root=None):
    frozen = _as_dict(version.get("assignment"))
    timing = version.get("timing") if isinstance(version.get("timing"), dict) else frozen.get("timing")
    props = frozen.get("props") if isinstance(frozen.get("props"), dict) else version.get("props")
    if not isinstance(props, dict):
        props = {}
    style = _as_dict(version.get("style"))
    context = {
        "chapter_context": frozen.get("chapter_context"),
        "narration": frozen.get("narration"),
        "purpose": frozen.get("purpose"),
        "timing": timing if isinstance(timing, dict) else {},
        "anchors": frozen.get("anchors") if isinstance(frozen.get("anchors"), list) else [],
        "questions": frozen.get("questions") if isinstance(frozen.get("questions"), list) else [],
        "proposed_scenes": frozen.get("proposed_scenes") if isinstance(frozen.get("proposed_scenes"), list) else [],
        "props": {
            "value": props.get("value"),
            "unit": props.get("unit"),
            "label": props.get("label"),
            "claim_status": props.get("claim_status"),
            "claim_note": props.get("claim_note"),
        },
        "style_revision": style.get("revision", frozen.get("style_revision")),
    }
    if isinstance(frozen.get("facts"), dict):
        context["facts"] = _public_facts(frozen.get("facts"))
    if isinstance(frozen.get("audio"), dict):
        context["audio"] = _public_audio(frozen.get("audio"), version)
    if isinstance(frozen.get("background"), dict):
        context["background"] = _public_background(frozen.get("background"), version)
    if isinstance(frozen.get("alignment"), dict):
        context["alignment"] = _public_alignment(frozen.get("alignment"), frozen, root=root)
    return context


GRAPHICS_REVIEW_PANEL = (
    '<section class="graphics-review-panel">'
    '<div class="graphics-review-actions review-actions">'
    '<button class="approve" type="button" data-graphics-decision="approved" aria-pressed="false"'
    ' title="Record human approval of this exact saved version. This does not start delivery or a job.">'
    "Approve</button>"
    '<button type="button" data-graphics-decision="changes" aria-pressed="false"'
    ' title="Describe the revision you want. Saving does not start an agent or render.">'
    "Needs changes</button>"
    "</div>"
    '<div class="review-fields" hidden>'
    '<label>What to change<textarea data-graphics-comment rows="3" maxlength="8000"'
    ' placeholder="Describe the revision or approval statement…"></textarea></label>'
    '<label class="graphics-shared-scope"><input type="checkbox" data-graphics-shared>'
    " Apply this change to all graphics (shared)</label>"
    '<button class="confirm-review" type="button" hidden>Confirm change request</button>'
    "</div>"
    '<p data-graphics-status class="feedback" role="status"></p>'
    '<details class="graphics-details"><summary>Details</summary>'
    "<!-- graphics-details -->"
    '<button class="comment-toggle" type="button" aria-expanded="false">Comment</button>'
    '<p data-graphics-readiness class="graphics-readiness"></p>'
    '<div class="graphics-request-status" data-graphics-requests></div>'
    '<p class="graphics-workflow">Save decisions, then ask in chat to process revision requests. '
    "Saving does not start production.</p>"
    "</details>"
    "</section>"
)


def _storyboard_failed_version(version):
    return (
        f'<p class="graphics-pending">Version {_esc(version.get("id"))} failed and cannot be approved. '
        "A later complete version is a new unapproved result.</p>"
    )


def _storyboard_approval_line(version):
    approval = _as_dict(version.get("approval"))
    if approval.get("status") == "approved":
        return (
            "<p>Historical human approval is recorded for this exact version. It is not current delivery readiness.</p>"
        )
    return "<p>No human approval is recorded for this version. A completed render is not approval.</p>"


def _storyboard_readiness_line(readiness):
    if not isinstance(readiness, dict):
        return "<p>Current delivery readiness: unknown.</p>"
    if readiness.get("deliverable"):
        status = "ready for delivery checks"
    elif readiness.get("approved"):
        status = "approved for this version, not currently deliverable"
    elif readiness.get("reviewable"):
        status = "reviewable, not currently approved or deliverable"
    else:
        status = "not reviewable"
    reasons = [str(item) for item in (readiness.get("reasons") or []) if item]
    extra = " (" + _esc(", ".join(reasons)) + ")" if reasons else ""
    return f"<p>Current delivery readiness: {_esc(status)}{extra}.</p>"


def _storyboard_passage(narration):
    text = str(narration or "")
    preview_limit = 240
    full = f'<blockquote class="graphics-original">{_esc(text)}</blockquote>'
    if len(text) <= preview_limit:
        return full
    preview = text[:preview_limit].rstrip() + "…"
    return (
        '<details class="graphics-passage"><summary>'
        f'<span class="graphics-passage-preview graphics-original">{_esc(preview)}</span>'
        '<span class="graphics-passage-expand">Читать целиком</span>'
        '<span class="graphics-passage-collapse">Свернуть</span>'
        "</summary>" + full + "</details>"
    )


def _storyboard_complete_version(version, shown):
    rel = version["artifact"].get("path")
    fps = _as_dict(version.get("profile")).get("fps") or DEFAULT_FPS
    vo = version.get("vo_preview") if isinstance(version.get("vo_preview"), dict) else {}
    vo_ref = vo.get("ref")
    vo_rel = vo_ref if isinstance(vo_ref, str) and vo_ref.startswith("previews/") else None
    audio_html = (
        f'<audio class="graphics-vo-preview" controls preload="metadata" src="{_esc(vo_rel)}" data-fps="{_esc(fps)}"></audio>'
        if vo_rel
        else ""
    )
    return (
        f'<video class="graphics-preview" controls preload="metadata" src="{_esc(rel)}" data-fps="{_esc(fps)}"></video>'
        + audio_html
        + f'<p class="graphics-version-label">{_esc(version.get("id"))}</p>'
        + _storyboard_passage(shown.get("narration"))
    )


def _storyboard_version_details(version, occ, readiness):
    parent = f", parent {_esc(version.get('parent'))}" if version.get("parent") else ", no parent"
    current_label = "current saved version" if occ.get("current_version") == version.get("id") else "retained version"
    return (
        f"<p>Version {_esc(version.get('id'))} ({_esc(current_label)}){parent}"
        f", sha256 {_esc((version['artifact'].get('sha256') or '')[:12])}…, "
        f"{_esc(version['artifact'].get('width'))}×{_esc(version['artifact'].get('height'))} "
        f"@ {_esc(version['artifact'].get('fps'))} fps, "
        f"{_esc(version['artifact'].get('nb_frames'))} frames, "
        f"style revision {_esc((version.get('style') or {}).get('revision'))}.</p>"
        + _storyboard_approval_line(version)
        + _storyboard_readiness_line(readiness)
    )


def _storyboard_version_tools(complete_versions, current_id):
    ids = [version.get("id") for version in complete_versions]
    selected_id = current_id if current_id in ids else next(iter(ids), None)
    options = [] if ids else ['<option value="">Pending</option>']
    display_disabled = "" if ids else " disabled"
    compare_disabled = " disabled" if len(ids) <= 1 else ""
    compare = ['<option value="">None</option>']
    for version in complete_versions:
        ident = version.get("id")
        selected = " selected" if ident == selected_id else ""
        options.append(f'<option value="{_esc(ident)}"{selected}>{_esc(ident)}</option>')
        compare.append(f'<option value="{_esc(ident)}">{_esc(ident)}</option>')
    return [
        '<div class="graphics-version-tools">',
        f"<label>Version <select data-graphics-display{display_disabled}>{''.join(options)}</select></label>",
        f"<label>Compare with <select data-graphics-compare{compare_disabled}>{''.join(compare)}</select></label>",
        "</div>",
    ]


def _occurrence_storyboard_versions(versions, occ_id):
    rows = [
        version for version in versions.values() if isinstance(version, dict) and version.get("occurrence_id") == occ_id
    ]
    rows.sort(key=lambda row: row.get("id") or "")
    complete = [
        version for version in rows if version.get("status") == "complete" and isinstance(version.get("artifact"), dict)
    ]
    failed = [version for version in rows if version.get("status") == "failed"]
    return complete, failed


def storyboard_section(ledger):  # noqa: PLR0915 - One ordered section preserves current/frozen version forms and pending actions together.
    graphics = ledger.data.get("graphics")
    if not isinstance(graphics, dict) or not graphics.get("occurrences"):
        return ""
    project = ledger.data.get("project_id")
    parts = [
        '<section class="graphics-board" aria-label="Graphics assignments">',
        "<h2>Graphics</h2>",
    ]
    versions = graphics.get("versions") or {}
    if not isinstance(versions, dict):
        versions = {}
    for occ in graphics["occurrences"].values():
        if not isinstance(occ, dict):
            continue
        occ_id = occ.get("occurrence_id")
        complete_versions, failed_versions = _occurrence_storyboard_versions(versions, occ_id)
        current_id = occ.get("current_version")
        current_version = versions.get(current_id) if isinstance(current_id, str) else None
        frozen = None
        if (
            isinstance(current_version, dict)
            and current_version.get("status") == "complete"
            and isinstance(current_version.get("artifact"), dict)
            and isinstance(current_version.get("assignment"), dict)
        ):
            frozen = current_version.get("assignment")
        shown = frozen if isinstance(frozen, dict) else occ
        timing = shown.get("timing") or {}
        basis = timing.get("basis")
        badge = "Draft · VO timing pending" if basis == "estimated" else ""
        parts.append(f'<article class="graphics-card" data-occurrence="{_esc(occ_id)}">')
        title = (
            _as_dict(shown.get("scene_content")).get("title")
            or _as_dict(shown.get("timeline")).get("title")
            or _as_dict(shown.get("props")).get("label")
            or occ.get("scene_id")
        )
        vo_ref = _as_dict(_as_dict(current_version).get("vo_preview")).get("ref")
        has_vo = isinstance(vo_ref, str) and vo_ref.startswith("previews/")
        parts.append(
            f'<h3 class="graphics-card-title">{_esc(title)}'
            f'<span class="graphics-vo-status"{" hidden" if has_vo else ""}>Без озвучки</span></h3>'
        )
        parts.extend(_storyboard_version_tools(complete_versions, current_id))
        details = [f'<span class="timing-basis {_esc(basis)}"{" hidden" if not badge else ""}>{_esc(badge)}</span>']
        if not complete_versions:
            parts.append(_storyboard_passage(shown.get("narration")))
            parts.append('<p class="graphics-pending">Preview pending.</p>')
            details.extend(_storyboard_assignment_body(shown, editable=True, root=ledger.root))
            extra, _required, _align, _bg = _facts_audio_reasons(ledger.root, occ, data=ledger.data)
            details.append(
                _storyboard_readiness_line(
                    {
                        "complete": False,
                        "reviewable": False,
                        "approved": False,
                        "deliverable": False,
                        "reasons": _unique(["incomplete_version", *extra]),
                    }
                )
            )
            details.append(
                '<p class="graphics-pending">Pending graphics assignment — no completed version, '
                "provider, media preview or human approval. Pending or failed assignments cannot be approved.</p>"
            )
            details.extend(_storyboard_failed_version(version) for version in failed_versions)
            parts.append(
                '<details class="graphics-details"><summary>Details</summary>' + "".join(details) + "</details>"
            )
        else:
            parts.append('<div class="graphics-versions">')
            for version in complete_versions:
                readiness = version_readiness(
                    ledger.root, version, occ, project, ledger.data.get("items"), data=ledger.data
                )
                row_id = "graphics:" + str(occ_id) + ":" + str(version.get("id"))
                current_attr = "true" if version.get("id") == current_id else "false"
                shown_class = " is-shown" if version.get("id") == current_id else ""
                frozen_shown = version.get("assignment") if isinstance(version.get("assignment"), dict) else occ
                parts.append(
                    f'<div class="graphics-version{shown_class}" data-version="{_esc(version.get("id"))}" '
                    f'data-row-id="{_esc(row_id)}" data-current="{current_attr}">'
                )
                parts.append(_storyboard_complete_version(version, frozen_shown))
                parts.append('<p class="graphics-decision-record" data-graphics-decision-record></p>')
                parts.append("</div>")
                details.append(
                    f'<div class="graphics-version-details{shown_class}" data-version="{_esc(version.get("id"))}">'
                )
                details.append(_storyboard_version_details(version, occ, readiness))
                details.extend(_storyboard_assignment_body(frozen_shown, root=ledger.root))
                details.append("</div>")
            parts.append("</div>")
            details.extend(_storyboard_failed_version(version) for version in failed_versions)
            diffs = _assignment_diffs(frozen, occ) if isinstance(frozen, dict) else []
            if isinstance(frozen, dict):
                parts.append('<p class="graphics-pending">Changes await a new preview.</p>' if diffs else "")
                details.extend(_storyboard_pending_changes(frozen, occ, root=ledger.root))
            if isinstance(occ.get("alignment"), dict) and "alignment" not in diffs:
                details.append(
                    "<h4>Adjust narration timing</h4>"
                    "<p>Current assignment alignment can be corrected here. "
                    "This form is bound to the current occurrence, recording and result; "
                    "frozen version forms stay disabled.</p>"
                )
                details.extend(_storyboard_alignment(occ, occ, editable=True, root=ledger.root, form_only=True))
            parts.append(GRAPHICS_REVIEW_PANEL.replace("<!-- graphics-details -->", "".join(details)))
        parts.append("</article>")
    parts.append("</section>")
    return "".join(parts)
