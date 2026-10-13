"""Displayed-fact evidence and editorial conflict decisions for graphics scenes.

Standard library only. Callers persist the returned records; this module never
writes files, contacts HTTP, or imports graphics.py.
"""

from __future__ import annotations

import copy
import hashlib
import ipaddress
import json
import os
import re
import stat
import urllib.parse
from datetime import UTC, datetime
from pathlib import Path

SCHEMA_VERSION = 1
DATA_REF_PREFIXES = ("graphics-data/", "previews/", "clips/")
PERMISSIONS = ("permitted", "restricted", "unknown")
SOURCE_KINDS = ("data", "chart_image")
DECISIONS = ("accept_correction", "keep_scenario", "defer")
MAX_TEXT = 8000
MAX_CONDITIONS = 2000
MAX_BY = 500
CHUNK = 1024 * 1024
ID_RE = re.compile(r"[A-Za-z0-9_-]{1,80}$")
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_WINDOWS_RESERVED = re.compile(r"^(?:con|prn|aux|nul|com[1-9]|lpt[1-9])$", re.IGNORECASE)
_CONTROL = re.compile(r"[\x00-\x1f\x7f]")
_PROSE_CONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
_ILLEGAL_PATH = re.compile(r'[<>"|?*]')
SECRET_QUERY = {
    "key",
    "api_key",
    "apikey",
    "wskey",
    "client_secret",
    "token",
    "access_token",
    "authorization",
    "signature",
    "sig",
}
VALUE_KEYS = ("id", "value", "unit", "definition", "geography", "reference_date", "source_ids")
SOURCE_KEYS = (
    "id",
    "url",
    "title",
    "reference_date",
    "terms_url",
    "conditions",
    "rendered_use",
    "raw_redistribution",
    "kind",
    "data_ref",
    "sha256",
)
CONFLICT_KEYS = ("id", "original_narration", "explanation", "source_ids", "proposed_correction", "decision")
DECISION_KEYS = ("choice", "by", "statement", "at", "evidence_sha256")
RECORD_KEYS = ("schema_version", "required", "values", "sources", "conflicts")
PRESERVE = "Invalid facts records. Preserve the project files and restore a valid copy; history was not reset."


def normalize_facts(root, payload):
    """Return a defensive normalized facts record. Invalid input raises ValueError."""
    if not isinstance(payload, dict):
        raise ValueError("Facts payload must be a JSON object.")
    record = {
        "schema_version": _schema_version(payload.get("schema_version")),
        "required": _required_flag(payload.get("required")),
        "values": [_normalize_value(item) for item in _array(payload, "values")],
        "sources": [_normalize_source(root, item) for item in _array(payload, "sources")],
        "conflicts": [_normalize_conflict(item) for item in _array(payload, "conflicts")],
    }
    _validate_record(record)
    return record


def validate_facts(record):
    """Structural saved-record validation with no file reads. None stays compatible."""
    if record is None:
        return None
    try:
        _validate_record(record)
    except (ValueError, TypeError, KeyError):
        raise ValueError(PRESERVE) from None
    return record


def facts_readiness(root, record):
    """Read-only readiness. None does not invalidate old assignments without facts."""
    if record is None:
        return {"ready": True, "reasons": []}
    validate_facts(record)
    reasons = _readiness_reasons(root, record)
    return {"ready": not reasons, "reasons": reasons}


def resolve_conflict(record, conflict_id, decision, by, statement):
    """Record an explicit editorial decision without rewriting original evidence."""
    if record is None:
        raise ValueError("Facts conflict resolution needs a saved facts record.")
    validate_facts(record)
    if not _valid_id(conflict_id):
        raise ValueError("Facts conflict id is invalid.")
    if decision not in DECISIONS:
        raise ValueError("Facts decision must be accept_correction, keep_scenario or defer.")
    actor = _required_prose(by, "Facts decision actor", MAX_BY)
    text = _required_prose(statement, "Facts decision statement", MAX_TEXT)
    updated = copy.deepcopy(record)
    target = None
    for conflict in updated["conflicts"]:
        if conflict["id"] == conflict_id:
            target = conflict
            break
    if target is None:
        raise ValueError("Unknown facts conflict id: " + conflict_id)
    target["decision"] = {
        "choice": decision,
        "by": actor,
        "statement": text,
        "at": datetime.now(UTC).isoformat(),
        "evidence_sha256": _conflict_fingerprint(updated, target),
    }
    _validate_record(updated)
    return updated


def _schema_version(value):
    if type(value) is not int or value != SCHEMA_VERSION:
        raise ValueError("Facts schema_version must be the integer 1.")
    return value


def _required_flag(value):
    if type(value) is not bool:
        raise ValueError("Facts required must be a boolean.")
    return value


def _array(payload, key):
    if key not in payload or payload[key] is None:
        return []
    items = payload[key]
    if not isinstance(items, list):
        raise ValueError("Facts " + key + " must be an array.")
    return items


def _valid_id(value):
    return isinstance(value, str) and bool(ID_RE.fullmatch(value)) and not _WINDOWS_RESERVED.fullmatch(value)


def _sha256_hex(value):
    return isinstance(value, str) and bool(SHA256_RE.fullmatch(value))


def _optional_prose(value, flag, limit=MAX_TEXT):
    if value is None:
        return ""
    if not isinstance(value, str) or len(value) > limit or _PROSE_CONTROL.search(value):
        raise ValueError(flag + " must be text without control characters.")
    return value


def _required_prose(value, flag, limit=MAX_TEXT):
    text = _optional_prose(value, flag, limit)
    if not text.strip():
        raise ValueError(flag + " must keep the original text, including harmless line breaks.")
    return text


def _id(value, flag):
    if not _valid_id(value):
        raise ValueError(flag + " must be a stable id of 1-80 letters, digits, _ or -.")
    return value


def _source_ids(value, flag):
    if value is None:
        return []
    if not isinstance(value, list):
        raise ValueError(flag + " must be an array of source ids.")
    seen = set()
    ids = []
    for item in value:
        ident = _id(item, flag)
        if ident in seen:
            raise ValueError(flag + " cannot repeat " + ident + ".")
        seen.add(ident)
        ids.append(ident)
    return ids


def _stored_optional_prose(item, key, flag, limit=MAX_TEXT):
    actual = item.get(key)
    normalized = _optional_prose(actual, flag, limit)
    if actual != normalized:
        raise ValueError(flag + " must be a normalized string.")
    return normalized


def _stored_public_url(item, key, flag):
    actual = item.get(key)
    normalized = _public_url(actual, flag)
    if actual != normalized:
        raise ValueError(flag + " must be a normalized string.")
    return normalized


def _stored_source_ids(item, flag):
    actual = item.get("source_ids")
    ids = _source_ids(actual, flag)
    if actual != ids:
        raise ValueError(flag + " must be a normalized array of source ids.")
    return ids


def _normalize_value(item):
    if not isinstance(item, dict):
        raise ValueError("Facts values must be objects.")
    return {
        "id": _id(item.get("id"), "Facts value id"),
        "value": _optional_prose(item.get("value"), "Facts value"),
        "unit": _optional_prose(item.get("unit"), "Facts unit"),
        "definition": _optional_prose(item.get("definition"), "Facts definition"),
        "geography": _optional_prose(item.get("geography"), "Facts geography"),
        "reference_date": _optional_prose(item.get("reference_date"), "Facts value reference_date"),
        "source_ids": _source_ids(item.get("source_ids"), "Facts value source_ids"),
    }


def _normalize_source(root, item):
    if not isinstance(item, dict):
        raise ValueError("Facts sources must be objects.")
    kind = item.get("kind")
    if kind not in SOURCE_KINDS:
        raise ValueError("Facts source kind must be data or chart_image.")
    rendered_use, raw_redistribution = _source_permissions(item)
    data_ref, sha256 = _source_bytes(root, item.get("data_ref"), item.get("sha256"))
    return {
        "id": _id(item.get("id"), "Facts source id"),
        "url": _public_url(item.get("url"), "Facts source url"),
        "title": _optional_prose(item.get("title"), "Facts source title"),
        "reference_date": _optional_prose(item.get("reference_date"), "Facts source reference_date"),
        "terms_url": _public_url(item.get("terms_url"), "Facts source terms_url"),
        "conditions": _optional_prose(item.get("conditions"), "Facts source conditions", MAX_CONDITIONS),
        "rendered_use": rendered_use,
        "raw_redistribution": raw_redistribution,
        "kind": kind,
        "data_ref": data_ref,
        "sha256": sha256,
    }


def _normalize_conflict(item):
    if not isinstance(item, dict):
        raise ValueError("Facts conflicts must be objects.")
    decision = item.get("decision")
    if decision is not None:
        decision = _normalize_decision(decision)
    return {
        "id": _id(item.get("id"), "Facts conflict id"),
        "original_narration": _required_prose(item.get("original_narration"), "Facts original_narration"),
        "explanation": _required_prose(item.get("explanation"), "Facts conflict explanation"),
        "source_ids": _source_ids(item.get("source_ids"), "Facts conflict source_ids"),
        "proposed_correction": _required_prose(item.get("proposed_correction"), "Facts proposed_correction"),
        "decision": decision,
    }


def _normalize_decision(item):
    if not isinstance(item, dict):
        raise ValueError("Facts conflict decision must be null or an object.")
    choice = item.get("choice")
    if choice not in DECISIONS:
        raise ValueError("Facts decision must be accept_correction, keep_scenario or defer.")
    digest_value = item.get("evidence_sha256")
    if not _sha256_hex(digest_value):
        raise ValueError("Facts decision evidence_sha256 must be a 64-character lowercase hex digest.")
    return {
        "choice": choice,
        "by": _required_prose(item.get("by"), "Facts decision actor", MAX_BY),
        "statement": _required_prose(item.get("statement"), "Facts decision statement"),
        "at": _required_prose(item.get("at"), "Facts decision time"),
        "evidence_sha256": digest_value,
    }


def _source_permissions(item):
    rendered_use = item.get("rendered_use")
    raw_redistribution = item.get("raw_redistribution")
    if rendered_use not in PERMISSIONS:
        raise ValueError("Facts source rendered_use must be permitted, restricted or unknown.")
    if raw_redistribution not in PERMISSIONS:
        raise ValueError("Facts source raw_redistribution must be permitted, restricted or unknown.")
    return rendered_use, raw_redistribution


def _source_bytes(root, data_ref, sha256):
    data_ref = _optional_data_ref(data_ref)
    sha256 = _optional_sha256(sha256)
    if data_ref:
        actual = _digest(_confine_data_file(root, data_ref))
        if sha256 and sha256 != actual:
            raise ValueError("Facts source sha256 does not match the confined file bytes: " + data_ref)
        return data_ref, actual
    if sha256:
        raise ValueError("Facts source sha256 requires a confined data_ref.")
    return data_ref, sha256


def _optional_data_ref(value):
    if value is None:
        return ""
    if not isinstance(value, str):
        raise ValueError(
            "Facts data_ref must be a project-relative posix path under graphics-data/, previews/ or clips/."
        )
    if value == "":
        return ""
    return _relative_data_ref(value)


def _optional_sha256(value):
    if value is None or value == "":
        return ""
    if not _sha256_hex(value):
        raise ValueError("Facts source sha256 must be a 64-character lowercase hex digest.")
    return value


def _validate_record(record):
    if not isinstance(record, dict) or set(record) != set(RECORD_KEYS):
        raise ValueError("Facts record keys must be schema_version, required, values, sources and conflicts.")
    _schema_version(record.get("schema_version"))
    _required_flag(record.get("required"))
    values = record.get("values")
    sources = record.get("sources")
    conflicts = record.get("conflicts")
    if not isinstance(values, list) or not isinstance(sources, list) or not isinstance(conflicts, list):
        raise ValueError("Facts values, sources and conflicts must be arrays.")
    _unique_ids(values, "value")
    known = _unique_ids(sources, "source")
    _unique_ids(conflicts, "conflict")
    for item in values:
        _validate_value(item, known)
    for item in sources:
        _validate_source(item)
    for item in conflicts:
        _validate_conflict(item, known)


def _unique_ids(items, label):
    found = set()
    for item in items:
        if not isinstance(item, dict):
            raise ValueError("Facts " + label + " entries must be objects.")
        ident = item.get("id")
        if not _valid_id(ident):
            raise ValueError("Facts " + label + " id is invalid.")
        if ident in found:
            raise ValueError("Facts " + label + " ids cannot be duplicated: " + ident)
        found.add(ident)
    return found


def _validate_value(item, known_sources):
    if set(item) != set(VALUE_KEYS):
        raise ValueError("Facts value keys are incomplete or unexpected.")
    _id(item.get("id"), "Facts value id")
    for field in ("value", "unit", "definition", "geography", "reference_date"):
        _stored_optional_prose(item, field, "Facts " + field)
    ids = _stored_source_ids(item, "Facts value source_ids")
    _known_source_ids(ids, known_sources, "Facts value " + item["id"])


def _validate_source(item):
    if set(item) != set(SOURCE_KEYS):
        raise ValueError("Facts source keys are incomplete or unexpected.")
    _id(item.get("id"), "Facts source id")
    _stored_public_url(item, "url", "Facts source url")
    _stored_optional_prose(item, "title", "Facts source title")
    _stored_optional_prose(item, "reference_date", "Facts source reference_date")
    _stored_public_url(item, "terms_url", "Facts source terms_url")
    _stored_optional_prose(item, "conditions", "Facts source conditions", MAX_CONDITIONS)
    if item.get("rendered_use") not in PERMISSIONS:
        raise ValueError("Facts source rendered_use must be permitted, restricted or unknown.")
    if item.get("raw_redistribution") not in PERMISSIONS:
        raise ValueError("Facts source raw_redistribution must be permitted, restricted or unknown.")
    if item.get("kind") not in SOURCE_KINDS:
        raise ValueError("Facts source kind must be data or chart_image.")
    data_ref = _optional_data_ref(item.get("data_ref"))
    sha256 = _optional_sha256(item.get("sha256"))
    if data_ref and not sha256:
        raise ValueError("Facts source data_ref requires a sha256 digest.")
    if sha256 and not data_ref:
        raise ValueError("Facts source sha256 requires a confined data_ref.")
    if item.get("data_ref") != data_ref or item.get("sha256") != sha256:
        raise ValueError("Facts source data_ref and sha256 must be normalized strings.")


def _validate_conflict(item, known_sources):
    if set(item) != set(CONFLICT_KEYS):
        raise ValueError("Facts conflict keys are incomplete or unexpected.")
    _id(item.get("id"), "Facts conflict id")
    _required_prose(item.get("original_narration"), "Facts original_narration")
    _required_prose(item.get("explanation"), "Facts conflict explanation")
    _required_prose(item.get("proposed_correction"), "Facts proposed_correction")
    ids = _stored_source_ids(item, "Facts conflict source_ids")
    _known_source_ids(ids, known_sources, "Facts conflict " + item["id"])
    decision = item.get("decision")
    if decision is not None:
        if not isinstance(decision, dict):
            raise ValueError("Facts conflict decision must be null or an object.")
        if set(decision) != set(DECISION_KEYS):
            raise ValueError("Facts decision keys are incomplete or unexpected.")
        normalized = _normalize_decision(decision)
        if any(decision.get(key) != normalized[key] for key in DECISION_KEYS):
            raise ValueError("Facts decision fields must be normalized.")


def _known_source_ids(ids, known, flag):
    for ident in ids:
        if ident not in known:
            raise ValueError(flag + " source_ids reference unknown source " + ident + ".")


def _public_url(value, flag):
    if value is None:
        return ""
    if not isinstance(value, str) or _CONTROL.search(value) or " " in value:
        raise ValueError(flag + " must be a public HTTPS URL without credentials.")
    if value == "":
        return ""
    parsed = urllib.parse.urlsplit(value)
    if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password:
        raise ValueError(flag + " must be a public HTTPS URL without credentials.")
    host = parsed.hostname.lower()
    if host == "localhost" or host.endswith(".local"):
        raise ValueError(flag + " must be a public HTTPS URL without credentials.")
    try:
        ip = ipaddress.ip_address(parsed.hostname)
    except ValueError:
        ip = None
    if ip is not None and not ip.is_global:
        raise ValueError(flag + " must be a public HTTPS URL without credentials.")
    for key, _value in urllib.parse.parse_qsl(parsed.query, keep_blank_values=True):
        lowered = key.lower()
        if lowered in SECRET_QUERY or lowered.startswith(("x-amz-", "x-goog-")):
            raise ValueError(flag + " must be a public HTTPS URL without credentials.")
    return value


def _relative_data_ref(value):
    if not isinstance(value, str) or not value or _CONTROL.search(value):
        raise ValueError(
            "Facts data_ref must be a project-relative posix path under graphics-data/, previews/ or clips/."
        )
    if "\\" in value or value.startswith(("/", "~")) or ":" in value:
        raise ValueError(
            "Facts data_ref must be a project-relative posix path without drive letters, colons, ADS streams or backslashes."
        )
    if _ILLEGAL_PATH.search(value):
        raise ValueError("Facts data_ref must be a project-relative posix path without Windows reserved characters.")
    path = Path(value)
    if ".." in path.parts or path.is_absolute():
        raise ValueError("Facts data_ref cannot leave the project tree.")
    if any(_WINDOWS_RESERVED.fullmatch(part.split(".")[0]) for part in path.parts):
        raise ValueError("Facts data_ref must not use reserved Windows names.")
    if not value.startswith(DATA_REF_PREFIXES):
        raise ValueError(
            "Facts data_ref must be a project-relative posix path under graphics-data/, previews/ or clips/."
        )
    return value


def _is_reparse(path):
    path = Path(path)
    try:
        info = os.lstat(path)
    except FileNotFoundError:
        return False
    except OSError:
        return True
    try:
        if path.is_symlink():
            return True
    except OSError:
        return True
    if stat.S_ISLNK(info.st_mode):
        return True
    attrs = getattr(info, "st_file_attributes", 0)
    return bool(attrs & stat.FILE_ATTRIBUTE_REPARSE_POINT)


def _contained(root, candidate):
    try:
        root_s = os.path.normcase(str(Path(root).resolve())).rstrip("\\/")
        cand_s = os.path.normcase(str(Path(candidate).resolve()))
    except OSError as exc:
        raise ValueError("Facts data_ref could not be resolved.") from exc
    return cand_s == root_s or cand_s.startswith(root_s + os.sep)


def _refuse_reparse_chain(path):
    cursor = Path(path)
    while True:
        if _is_reparse(cursor):
            raise ValueError("Facts data_ref is a symlink or junction.")
        parent = cursor.parent
        if parent == cursor:
            break
        cursor = parent


def _refuse_reparse_ancestors(root, dest):
    # Walk dest through the lexical root and the root's parent chain before
    # resolve(). An ordinary brolls directory under a junction parent is still
    # an unsafe confinement base.
    _refuse_reparse_chain(dest)
    _refuse_reparse_chain(root)


def _confine_data_file(root, rel):
    rel = _relative_data_ref(rel)
    try:
        base = Path(root)
        str(base)
    except (TypeError, OSError, ValueError) as exc:
        raise ValueError("Facts root must be the project brolls directory.") from exc
    dest = base / rel
    try:
        _refuse_reparse_ancestors(base, dest)
    except ValueError as exc:
        raise ValueError("Facts data_ref is a symlink or junction: " + rel) from exc
    if _is_reparse(dest):
        raise ValueError("Facts data_ref is a symlink or junction: " + rel)
    try:
        resolved_root = base.resolve()
        resolved = dest.resolve()
    except OSError as exc:
        raise ValueError("Facts data_ref could not be resolved: " + rel) from exc
    if not _contained(resolved_root, resolved):
        raise ValueError("Facts data_ref resolves outside the project: " + rel)
    if not resolved.is_file() or resolved.is_symlink() or _is_reparse(resolved):
        raise ValueError("Facts data_ref is missing or not a regular file: " + rel)
    return resolved


def _digest(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(CHUNK), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _canonical_hash(payload):
    encoded = json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _conflict_fingerprint(record, conflict):
    return _canonical_hash(
        {
            "values": record.get("values"),
            "sources": record.get("sources"),
            "conflict": {
                "id": conflict.get("id"),
                "original_narration": conflict.get("original_narration"),
                "explanation": conflict.get("explanation"),
                "source_ids": conflict.get("source_ids"),
                "proposed_correction": conflict.get("proposed_correction"),
            },
        }
    )


def _readiness_reasons(root, record):
    reasons = []
    if not record["values"]:
        reasons.append("Facts have no displayed values.")
    for item in record["values"]:
        reasons.extend(_value_reasons(item))
    for item in record["sources"]:
        reasons.extend(_source_reasons(root, item))
    for item in record["conflicts"]:
        reasons.extend(_conflict_reasons(record, item))
    return reasons


def _value_reasons(item):
    reasons = []
    ident = item["id"]
    if not item["value"].strip():
        reasons.append("Facts value " + ident + " is empty.")
    reasons.extend(
        [
            "Facts value " + ident + " " + field + " is missing."
            for field in ("unit", "definition", "geography", "reference_date")
            if not item[field].strip()
        ]
    )
    if not item["source_ids"]:
        reasons.append("Facts value " + ident + " has no source evidence.")
    return reasons


def _source_metadata_reasons(item):
    ident = item["id"]
    reasons = []
    if not item["url"]:
        reasons.append("Facts source " + ident + " is missing a public source URL.")
    reasons.extend(
        [
            "Facts source " + ident + " " + field + " is missing."
            for field, blank in (
                ("title", not item["title"].strip()),
                ("reference_date", not item["reference_date"].strip()),
                ("terms_url", not item["terms_url"]),
                ("conditions", not item["conditions"].strip()),
            )
            if blank
        ]
    )
    return reasons


def _source_permission_reasons(item):
    ident = item["id"]
    reasons = []
    if item["rendered_use"] == "unknown":
        reasons.append("Facts source " + ident + " rendered_use is unknown.")
    elif item["rendered_use"] == "restricted":
        reasons.append("Facts source " + ident + " rendered_use is restricted.")
    if item["raw_redistribution"] == "unknown":
        reasons.append("Facts source " + ident + " raw_redistribution is unknown.")
    return reasons


def _source_data_reasons(root, item):
    ident = item["id"]
    if not item["data_ref"]:
        return ["Facts source " + ident + " data_ref is missing."]
    try:
        actual = _digest(_confine_data_file(root, item["data_ref"]))
    except ValueError as exc:
        return [str(exc)]
    except OSError:
        return ["Facts data_ref is missing or not a regular file: " + item["data_ref"]]
    if actual != item["sha256"]:
        return ["Facts source " + ident + " bytes changed; sha256 does not match " + item["data_ref"] + "."]
    return []


def _source_reasons(root, item):
    reasons = _source_metadata_reasons(item)
    reasons.extend(_source_permission_reasons(item))
    reasons.extend(_source_data_reasons(root, item))
    return reasons


def _conflict_reasons(record, item):
    ident = item["id"]
    reasons = []
    if not item["source_ids"]:
        reasons.append("Facts conflict " + ident + " has no source evidence.")
    decision = item.get("decision")
    if decision is None:
        reasons.append("Facts conflict " + ident + " is unresolved.")
        return reasons
    if decision["choice"] == "defer":
        reasons.append("Facts conflict " + ident + " is deferred and remains unresolved.")
    if decision["evidence_sha256"] != _conflict_fingerprint(record, item):
        reasons.append("Facts conflict " + ident + " decision is bound to stale evidence.")
    return reasons
