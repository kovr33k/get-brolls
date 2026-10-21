"""Private AI image and video references for one exact beat.

The caller holds the project lock. These functions use that ledger journal and
do not acquire the lock, because it is not re-entrant. They do not create
generation jobs, change approval, or call a provider.

Image measurement reuses the shipped graphics image probe. Path confinement
reuses the shipped graphics-audio helpers. Graphics chat activation is not used.
"""

from __future__ import annotations

import contextlib
import hashlib
import math
import os
import re
import subprocess
import tempfile
from copy import deepcopy
from pathlib import Path

from .ai_state import (
    MAX_PROMPT,
    beat_for,
    fingerprint,
    sanitize_public_text,
    state,
    text,
    version_signature,
)
from .graphics_audio import _confine_existing, _confine_planned, _is_link_or_junction, relative_audio_ref
from .graphics_references import MAX_IMAGE_BYTES, MAX_IMAGE_PIXELS
from .graphics_references import _probe as probe_image
from .ledger import digest
from .media import frame_times
from .media import run as media_run
from .models import now

PREFIX = "ai-data/references/"
MAX_VIDEO_BYTES = 64 * 1024 * 1024
FRAME_SAMPLES = 4
MAX_NAME = 300
MAX_NATIVE_ID = 200
SAME_COLOR = 70
DISTINCT_COLOR = 140
ROLES = ("guidance", "appearance", "content", "composition", "motion", "style")
SCOPES = ("beat", "shared")
IMAGE_DECLARED = {"image/png": "png", "image/jpeg": "jpg"}
VIDEO_DECLARED = {"video/mp4": "mp4"}
DECLARED = {**IMAGE_DECLARED, **VIDEO_DECLARED}
ATTACH_FIELDS = {
    "beat",
    "fingerprint",
    "identity",
    "name",
    "declared_type",
    "body",
    "length",
    "instructions",
    "role",
    "scope",
    "scope_instruction",
    "still",
    "interval",
}
STORE_KEYS = ("originals", "derivatives", "contexts", "active", "inputs", "invalidations")
LIMITS = {
    "image_bytes": MAX_IMAGE_BYTES,
    "image_pixels": MAX_IMAGE_PIXELS,
    "video_bytes": MAX_VIDEO_BYTES,
    "duration_rule": None,
    "contact_sheet_frames": FRAME_SAMPLES,
}
_LINK = "AI reference path is a symlink or junction and will not be followed."
_ESCAPE = "AI reference path escapes the private store or cannot be confined."
_ALTERED = "Saved reference bytes changed; the existing file was preserved."
_NOT_RECEIVED = "The server has not received this file. A browser selection was not transferred."
_INCOMPLETE = "Incomplete reference transfer; the request was not saved."
_IDENTITY = "This request identity already belongs to different reference inputs."
_OCCUPIED = "The occupied original does not match these bytes; the existing file was preserved."
_OPENING = "The opening was not used."
_UNTRUNCATED = "The interval was not truncated and the opening was not used."
_STILL_BOUND = (
    "Active guidance is bound to a retained still. Ordinary generation will not guess which result you meant. "
    "Use Apply for that retained result. The guidance and draft were preserved."
)
_UNSUPPORTED_ROUTE = (
    "Active reference guidance requires a supported subscription image route. "
    "OpenRouter was not called and no other model was substituted. Nothing was submitted."
)
_STALE_GUIDANCE = "This reference is stale for the current beat. Nothing was submitted. The guidance was preserved."
_MISSING_INTERVAL = "Video guidance is missing the requested interval. Nothing was submitted. The opening was not used."
_LOWEST_PRINTABLE = 32
_DELETE_CHAR = 127
_MP4_BOX_PREFIX = 12
_RGB_CHANNELS = 3
_SECONDS = r"(?:s\b|sec(?:onds?)?\b|сек\w*|segundos?\b)"
_TIMESTAMP = r"(?:\d{1,3}:\d{2}(?:[.,]\d+)?|\d+(?:[.,]\d+)?)"
_INSTRUCTION_RANGE = re.compile(
    rf"(?<![\d.:,\-])({_TIMESTAMP})\s*(?:{_SECONDS})?\s*(?:[–—-]|\bto\b|\bдо\b|\bпо\b|\ba\b)\s*"
    rf"({_TIMESTAMP})\s*({_SECONDS})?",
    re.IGNORECASE,
)


def unreceived_attachment(name):
    """A browser filename is not evidence that the server received bytes."""
    return {
        "state": "not_received",
        "received": False,
        "transferred": False,
        "stored": False,
        "name": _safe_name(name),
        "provider_input": "unsupported",
        "provider_access": False,
        "limits": dict(LIMITS),
    }


def attach_reference(ledger, payload):
    """Save one received reference and make it the active context for its exact target."""
    return _write_context(ledger, payload, replacing=False)


def replace_reference(ledger, payload):
    """Freeze the active context as history and activate a new received reference."""
    return _write_context(ledger, payload, replacing=True)


def remove_reference(ledger, payload):
    """Drop active guidance for this exact target. Bytes, history, and ancestor bindings stay."""
    fields = _target_fields(payload)
    _pending(ledger)
    beat = beat_for(ledger, fields["beat"], fields["fingerprint"])
    comment = beat.get("comment")
    version = _displayed_target(ledger, beat, fields["still"])
    store = _view(ledger)
    current = _exact_active(store, fields["key"])
    inherited = None
    if current is None and version is not None:
        inherited = _inherited_context(ledger, beat, store, fields["still_id"])
    blocked = None
    if current is not None:
        blocked = _retire_exact_context(ledger, fields["key"])
    elif inherited is not None:
        blocked = inherited["id"]
    if blocked is None:
        return show_reference(ledger, fields["beat"], fields["fingerprint"], fields["still_id"])
    if version is not None:
        # Empty affected keeps the ancestor context active on its original still.
        _write_retained_override(ledger, beat, version, blocked)
    if beat.get("comment") != comment:
        beat["comment"] = comment
    ledger.save("ai-reference-remove")
    return show_reference(ledger, fields["beat"], fields["fingerprint"], fields["still_id"])


def show_reference(ledger, beat_id, fingerprint_value, still_id=None):
    """Read active guidance for this target or the nearest retained ancestor. Drift is not rewritten."""
    beat = beat_for(ledger, beat_id, fingerprint_value)
    store = _view(ledger)
    displayed = _displayed_version(ledger, beat)
    if still_id:
        anchored = _image_version(ledger, beat, still_id)
        if anchored is not None:
            _producing_edge(ledger, beat, anchored)
    key = _target_key(beat_id, fingerprint_value, still_id)
    active = _exact_active(store, key)
    if active is None and still_id:
        active = _inherited_context(ledger, beat, store, still_id)
    preserved = _preserved(ledger, beat, store, displayed, active)
    if active is None:
        return {
            "state": "absent",
            "beat": beat["id"],
            "fingerprint": beat["fingerprint"],
            "still": {"id": still_id} if still_id else None,
            "displayed_still": displayed.get("id") if displayed else None,
            "active": None,
            "preserved": preserved,
            "received": False,
            "transferred": False,
            "provider_input": "unsupported",
            "provider_access": False,
            "limits": dict(LIMITS),
        }
    public = _public(ledger, beat, active, displayed, store)
    public["preserved"] = preserved
    return public


def show_saved(ledger, context_id):
    """Read one stored context or frozen input without making it current."""
    store = _view(ledger)
    frozen = _row(store, "inputs", context_id)
    if frozen is not None and isinstance(frozen.get("snapshot"), dict):
        beat = beat_for(ledger, frozen["snapshot"]["beat"], None)
        return _public_input(ledger, beat, frozen, store)
    record = _row(store, "contexts", context_id)
    if record is None:
        raise ValueError("Unknown saved reference.")
    beat = beat_for(ledger, record["beat"], None)
    displayed = _displayed_version(ledger, beat) if record.get("fingerprint") == beat.get("fingerprint") else None
    return _public(ledger, beat, record, displayed, store)


def freeze_inputs(ledger, payload):
    """Copy the active context into an immutable job-input record. No job is created."""
    fields = _target_fields(payload)
    if fields["identity"] is None:
        raise ValueError("Name the request identity for this frozen reference.")
    _pending(ledger)
    beat = beat_for(ledger, fields["beat"], fields["fingerprint"])
    _bind_still(ledger, beat, fields["still"])
    store = _view(ledger)
    active = _require_active(store, fields)
    _same_still(active, fields)
    _require_bytes(ledger, store, active)
    return _commit_frozen(ledger, beat, active, fields["identity"])


def _retained_fields(payload):
    if not isinstance(payload, dict):
        raise ValueError("Name the retained reference.")
    _unknown(payload, {"beat", "fingerprint", "still", "identity", "context"})
    beat_id = text(payload.get("beat"), "Beat", 80)
    fingerprint_value = text(payload.get("fingerprint"), "Beat fingerprint", 80)
    still = _still_fields(payload.get("still"))
    if still is None:
        raise ValueError("Name the retained still id and signature.")
    return {
        "beat": beat_id,
        "fingerprint": fingerprint_value,
        "still": still,
        "still_id": still["id"],
        "identity": text(payload.get("identity"), "Request identity", 160),
        "context": text(payload.get("context"), "Reference", 80),
        "key": _target_key(beat_id, fingerprint_value, still["id"]),
    }


def freeze_retained(ledger, payload):
    """Freeze an active ancestor context without rebinding it to the displayed still."""
    fields = _retained_fields(payload)
    _pending(ledger)
    beat = beat_for(ledger, fields["beat"], fields["fingerprint"])
    store = _view(ledger)
    active = _row(store, "contexts", (store.get("active") or {}).get(fields["key"]))
    if active is None or active.get("status") != "active" or active.get("id") != fields["context"]:
        raise ValueError("There is no active reference for this retained still. Nothing was frozen.")
    if _invalidated(store, active["id"]):
        raise ValueError("This retained reference no longer applies. Nothing was frozen.")
    if active.get("beat") != beat["id"] or active.get("fingerprint") != beat["fingerprint"]:
        raise ValueError("The retained reference belongs to another beat. Nothing was frozen.")
    _same_still(active, fields)
    from .ai_state import checked_version

    version, _path = checked_version(ledger, fields["still_id"], kind="image")
    if version.get("beat") != beat["id"] or version_signature(version) != fields["still"]["signature"]:
        raise ValueError("The retained still changed. Its guidance was not applied to a different image.")
    _require_bytes(ledger, store, active)
    return _commit_frozen(ledger, beat, active, fields["identity"])


def _commit_frozen(ledger, beat, active, identity):
    store = _view(ledger)
    owner, existing = _identity_owner(store, identity)
    material = fingerprint({"context": active["id"], "material": active["material"]})
    if existing is not None:
        if owner == "inputs" and existing.get("material") == material:
            _require_bytes(ledger, store, existing["snapshot"])
            return _public_input(ledger, beat, existing, store)
        raise ValueError(_IDENTITY)
    snapshot = deepcopy(active)
    snapshot["status"] = "historical"
    record = {
        "id": "inp-" + fingerprint({"identity": identity, "material": material})[:24],
        "identity": identity,
        "material": material,
        "context_id": active["id"],
        "snapshot": snapshot,
        "created_at": now(),
    }
    store = _ensure_store(ledger)
    store["inputs"][record["id"]] = record
    ledger.save("ai-reference-freeze")
    return _public_input(ledger, beat, record, store)


def job_reference(frozen):
    """Slim public freeze for a job request. The context record is not rewritten."""
    derivative = frozen.get("derivative") if isinstance(frozen.get("derivative"), dict) else {}
    frames = [
        {"index": frame["index"], "sha256": frame["sha256"], "time_s": frame.get("time_s")}
        for frame in derivative.get("frames") or []
        if isinstance(frame, dict) and type(frame.get("index")) is int and isinstance(frame.get("sha256"), str)
    ]
    hashes = [derivative.get("sha256"), derivative.get("clip_sha256"), derivative.get("sheet_sha256")]
    hashes.extend(frame["sha256"] for frame in frames)
    findings = frozen.get("findings")
    return {
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
        "findings": findings if isinstance(findings, str) else None,
    }


def reference_prompt_lines(summaries):
    """Prompt lines for frozen guidance. A filename in these lines is not image content."""
    lines = []
    for ref in summaries or []:
        if not isinstance(ref, dict):
            continue
        role = ref.get("role") or "appearance"
        interval = ref.get("interval") if isinstance(ref.get("interval"), dict) else None
        if ref.get("kind") == "video" and interval is not None:
            lines.append(
                f"Video reference role {role}: requested interval {interval.get('start_s')}–{interval.get('end_s')}s. "
                f"Editor reference guidance: {ref.get('instructions') or ''}. "
                "The attached frames are that interval. The opening was not substituted. "
                "This is visual guidance, not first-frame production, documentary evidence, rights, or animation approval."
            )
        else:
            lines.append(f"Image reference role {role}: {ref.get('instructions') or ''}")
        if ref.get("scope") == "shared":
            lines[-1] += " Shared AI style instruction: " + str(ref.get("scope_instruction") or "")
    return lines


def freeze_ordinary_guidance(ledger, beat, nonce, route, *, allow_paid=False):
    """Freeze active beat-level guidance for an ordinary launch. No job is created.

    An empty list means this beat has no active guidance. Still-bound guidance is
    refused instead of guessing a retained result. Unsupported routes are refused
    before a provider call. The caller holds the project lock.
    """
    if not isinstance(beat, dict):
        raise ValueError("Name the beat before launching with guidance.")
    store = _view(ledger)
    if _unresolved_still_guidance(ledger, beat):
        raise ValueError(_STILL_BOUND)
    active = _exact_active(store, _target_key(beat.get("id"), beat.get("fingerprint"), None))
    if active is None:
        return freeze_shared_guidance(ledger, beat, nonce, route, allow_paid=allow_paid)
    still = active.get("still")
    if isinstance(still, dict) and still.get("id"):
        raise ValueError(_STILL_BOUND)
    if active.get("beat") != beat.get("id") or active.get("fingerprint") != beat.get("fingerprint"):
        raise ValueError(_STALE_GUIDANCE)
    if route not in (
        {"gpt-subscription", "grok-subscription", "openrouter"}
        if allow_paid
        else {"gpt-subscription", "grok-subscription"}
    ):
        raise ValueError(_UNSUPPORTED_ROUTE)
    _require_launch_video(store, active)
    identity = "frz-" + fingerprint({"nonce": nonce, "context": active["id"]})[:40]
    frozen = freeze_inputs(
        ledger,
        {"beat": beat["id"], "fingerprint": beat["fingerprint"], "identity": identity},
    )
    return [
        job_reference(frozen),
        *freeze_shared_guidance(ledger, beat, nonce, route, exclude={active["id"]}, allow_paid=allow_paid),
    ]


def shared_guidance(ledger, *, exclude=()):
    """Explicit shared references retain their original owner, target and history."""
    store = _view(ledger)
    rows = []
    for ident in dict.fromkeys((store.get("active") or {}).values()):
        record = _row(store, "contexts", ident)
        if not record or ident in exclude or record.get("scope") != "shared" or _invalidated(store, ident):
            continue
        owner = beat_for(ledger, record.get("beat"), record.get("fingerprint"))
        rows.append(_public(ledger, owner, record, _displayed_version(ledger, owner), store))
    return rows


def freeze_shared_guidance(ledger, beat, nonce, route, *, exclude=(), allow_paid=False):  # noqa: PLR0913 - explicit paid preparation policy and shared-source exclusions remain distinct.
    """Freeze shared style without attaching it to another beat or approving media."""
    beat_for(ledger, beat.get("id"), beat.get("fingerprint"))
    rows = shared_guidance(ledger, exclude=exclude)
    if rows and route not in (
        {"gpt-subscription", "grok-subscription", "openrouter"}
        if allow_paid
        else {"gpt-subscription", "grok-subscription"}
    ):
        raise ValueError(_UNSUPPORTED_ROUTE)
    result = []
    for row in rows:
        owner = beat_for(ledger, row["beat"], row["fingerprint"])
        identity = "frz-" + fingerprint({"nonce": nonce, "context": row["context_id"]})[:40]
        payload = {"beat": owner["id"], "fingerprint": owner["fingerprint"], "identity": identity}
        if row.get("still"):
            payload.update(still=row["still"], context=row["context_id"])
            frozen = freeze_retained(ledger, payload)
        else:
            frozen = freeze_inputs(ledger, payload)
        result.append(job_reference(frozen))
    return result


def _unresolved_still_guidance(ledger, beat):
    """True when the displayed still still has exact or inherited guidance.

    A retained ancestor on another branch stays active for Apply and does not
    make this ordinary launch unresolved. Retained-override removal returns no
    context. Broken lineage and byte checks raise; they are not treated as absent.
    """
    displayed = _displayed_version(ledger, beat)
    if not isinstance(displayed, dict) or displayed.get("kind") != "image":
        return False
    if displayed.get("beat") != beat.get("id") or displayed.get("inputs") != beat.get("fingerprint"):
        return False
    still_id = displayed.get("id")
    if not isinstance(still_id, str) or not still_id:
        return False
    resolved = _active_for_still(ledger, beat, _view(ledger), still_id)
    return isinstance(resolved, dict)


def _require_launch_video(store, active):
    if active.get("kind") != "video":
        return
    interval = active.get("interval") if isinstance(active.get("interval"), dict) else None
    frames = _public_frames(store, active)
    start = None if interval is None else interval.get("start_s")
    end = None if interval is None else interval.get("end_s")
    valid = (
        interval is not None
        and not isinstance(start, bool)
        and not isinstance(end, bool)
        and isinstance(start, (int, float))
        and isinstance(end, (int, float))
        and math.isfinite(start)
        and math.isfinite(end)
        and bool(frames)
    )
    if not valid:
        raise ValueError(_MISSING_INTERVAL)


def _inspection_evidence(value):
    if not isinstance(value, dict) or set(value) != {"threadId", "turnId"}:
        raise ValueError("Native inspection evidence names the turn only. Paths were not stored.")
    cleaned = {}
    for key in ("threadId", "turnId"):
        item = value.get(key)
        if (
            not isinstance(item, str)
            or not item.strip()
            or item != item.strip()
            or len(item) > MAX_NATIVE_ID
            or any(char in item for char in "\0\\/:")
        ):
            raise ValueError("Native inspection evidence names the turn only. Paths were not stored.")
        cleaned[key] = item
    return cleaned


def _inspection_record(payload, role, source, expected, findings):
    origin = payload.get("origin", "supplied")
    route = payload.get("route", None)
    provider_input = payload.get("provider_input", None)
    evidence = payload.get("evidence", None)
    if origin == "supplied":
        if route is not None or provider_input is not None or evidence is not None:
            raise ValueError("Supplied inspection does not record a provider route. The reference stays uninspected.")
        return {
            "state": "inspected",
            "role": role,
            "source_sha256": source,
            "derivative_sha256": expected,
            "findings": findings,
            "provider_access": False,
            "origin": "supplied",
        }
    if origin != "native-gpt":
        raise ValueError("Inspection origin is not supported. The reference stays uninspected.")
    if route != "gpt-subscription" or provider_input != "localImage":
        raise ValueError("Native inspection needs the GPT subscription localImage route. Nothing was marked inspected.")
    return {
        "state": "inspected",
        "role": role,
        "source_sha256": source,
        "derivative_sha256": expected,
        "findings": findings,
        "provider_access": False,
        "origin": "native-gpt",
        "route": "gpt-subscription",
        "provider_input": "localImage",
        "evidence": _inspection_evidence(evidence),
    }


def _provider_claim(inspection):
    """Only a verified native localImage inspection is reported. Access stays closed."""
    evidence = inspection.get("evidence") if isinstance(inspection, dict) else None
    if (
        isinstance(inspection, dict)
        and inspection.get("state") == "inspected"
        and inspection.get("origin") == "native-gpt"
        and inspection.get("route") == "gpt-subscription"
        and inspection.get("provider_input") == "localImage"
        and isinstance(evidence, dict)
        and set(evidence) == {"threadId", "turnId"}
    ):
        return "localImage"
    return "unsupported"


def record_inspection(ledger, payload):
    """Bind findings to the exact source, derivative hashes, and role.

    Upload does not call this. Absent findings stay uninspected. Supplied
    findings are evidence from the caller, not provider access. A native-gpt
    record stores route evidence only; it does not grant provider access.
    """
    _pending(ledger)
    if not isinstance(payload, dict):
        raise ValueError("Reference inspection must name its source, derivatives, role, and findings.")
    _unknown(
        payload,
        {
            "context",
            "role",
            "source_sha256",
            "derivative_sha256",
            "findings",
            "identity",
            "origin",
            "route",
            "provider_input",
            "evidence",
        },
    )
    store = _view(ledger)
    record = _row(store, "contexts", payload.get("context"))
    if record is None:
        raise ValueError("Reference inspection needs a stored context. Nothing was marked inspected.")
    role = _choice(payload.get("role"), ROLES, "Reference role")
    if role != record["role"]:
        raise ValueError("Inspection role does not match the declared reference role. The reference stays uninspected.")
    source = payload.get("source_sha256")
    if source != record["original_sha256"]:
        raise ValueError("Inspection source does not match the stored reference. The reference stays uninspected.")
    hashes = payload.get("derivative_sha256")
    expected = _derivative_hashes(store, record)
    if not isinstance(hashes, list) or sorted(set(hashes)) != expected or not expected:
        raise ValueError("Inspection derivatives do not match the stored frames. The reference stays uninspected.")
    _require_bytes(ledger, store, record)
    findings = sanitize_public_text(text(payload.get("findings"), "Inspection findings", MAX_PROMPT), limit=MAX_PROMPT)
    inspection = _inspection_record(payload, role, source, expected, findings)
    if record.get("inspection") == inspection:
        beat = beat_for(ledger, record["beat"], None)
        return _public(ledger, beat, record, _displayed_version(ledger, beat), store)
    record["inspection"] = inspection
    ledger.save("ai-reference-inspect")
    beat = beat_for(ledger, record["beat"], None)
    return _public(ledger, beat, record, _displayed_version(ledger, beat), store)


def record_invalidation(ledger, payload):
    """Mark only the named contexts or frozen inputs. Earlier media stays on disk."""
    _pending(ledger)
    if not isinstance(payload, dict):
        raise ValueError("Name the beat, the affected reference ids, and why they no longer apply.")
    _unknown(payload, {"beat", "fingerprint", "affected", "reason", "identity"})
    beat = beat_for(ledger, payload.get("beat"), payload.get("fingerprint"))
    affected = payload.get("affected")
    if not isinstance(affected, list) or not affected or not all(isinstance(item, str) for item in affected):
        raise ValueError("Name each affected reference. Unrelated references were not changed.")
    store = _view(ledger)
    for ident in affected:
        row = _affected_scope(store, ident)
        if row is None or row.get("beat") != beat["id"] or row.get("fingerprint") != beat["fingerprint"]:
            raise ValueError("An affected reference is not part of this beat and fingerprint. Nothing was invalidated.")
    reason = sanitize_public_text(text(payload.get("reason"), "Invalidation reason", 2000), limit=2000)
    identity = text(payload.get("identity"), "Request identity", 160)
    material = fingerprint({"beat": beat["id"], "affected": affected, "reason": reason})
    owner, existing = _identity_owner(store, identity)
    if existing is not None:
        if owner == "invalidations" and existing.get("material") == material:
            return _public_invalidation(existing)
        raise ValueError(_IDENTITY)
    record = {
        "id": "inv-" + fingerprint({"identity": identity, "material": material})[:24],
        "identity": identity,
        "material": material,
        "beat": beat["id"],
        "fingerprint": beat["fingerprint"],
        "affected": list(affected),
        "reason": reason,
        "created_at": now(),
    }
    store = _ensure_store(ledger)
    for ident in affected:
        context = _row(store, "contexts", ident)
        key = _active_key_for(store, ident)
        if key is not None and (store.get("active") or {}).get(key) == ident:
            if context is not None and context.get("status") == "active":
                context["status"] = "historical"
            store["active"].pop(key, None)
    store["invalidations"][record["id"]] = record
    ledger.save("ai-reference-invalidate")
    return _public_invalidation(record)


def handoff(ledger, ident):
    """Bytes and frames for a later inspector or provider. Support stays unsupported."""
    store = _view(ledger)
    frozen = _row(store, "inputs", ident)
    if frozen is not None and isinstance(frozen.get("snapshot"), dict):
        record = frozen["snapshot"]
        requested = frozen["id"]
    else:
        record = _row(store, "contexts", ident)
        if record is None:
            raise ValueError("Unknown saved reference.")
        requested = record["id"]
    beat = (ledger.data.get("ai") or {}).get("beats", {}).get(record["beat"]) or {}
    displayed = None
    if isinstance(beat, dict) and record.get("fingerprint") == beat.get("fingerprint"):
        displayed = _displayed_version(ledger, beat)
    _require_bytes(ledger, store, record)
    inspection = record.get("inspection")
    if not isinstance(inspection, dict):
        inspection = {}
    inspected = inspection.get("state") == "inspected"
    invalidation = _invalidated(store, requested)
    return {
        "id": requested,
        "context_id": record["id"],
        "inspection": "inspected" if inspected else "uninspected",
        "inspection_origin": inspection.get("origin") if inspected else None,
        "findings": inspection.get("findings") if inspected else None,
        "provider_input": _provider_claim(inspection) if inspected else "unsupported",
        "provider_access": False,
        "role": record["role"],
        "source_sha256": record["original_sha256"],
        "derivative_sha256": _derivative_hashes(store, record),
        "frames": _public_frames(store, record),
        "interval": record.get("interval"),
        "instructions": record.get("instructions"),
        "invalidated": invalidation is not None,
        "invalidation_reason": invalidation.get("reason") if invalidation else None,
        "applies_to_displayed_still": _applies(ledger, record, displayed, store),
        "received": True,
        "limits": dict(LIMITS),
    }


def read_original(ledger, sha256):
    """Return the private original bytes after confinement and a hash check."""
    store = _view(ledger)
    row = _row(store, "originals", sha256)
    if row is None:
        raise ValueError("Unknown reference original.")
    return _read_checked(ledger.root, row["ref"], sha256, row["bytes"])


def read_derivative(ledger, derivative_id, kind, index=None):
    """Return one private derivative. `kind` is clip, sheet, pixels, or frame."""
    store = _view(ledger)
    row = _row(store, "derivatives", derivative_id)
    if row is None:
        raise ValueError("Unknown reference derivative.")
    if kind == "frame":
        frames = [frame for frame in row.get("frames") or [] if frame.get("index") == index]
        if len(frames) != 1:
            raise ValueError("Unknown reference frame.")
        frame = frames[0]
        return _read_checked(ledger.root, frame["ref"], frame["sha256"], None)
    part = {"clip": "clip_ref", "sheet": "sheet_ref", "pixels": "pixels_ref"}.get(kind)
    sha_name = {"clip": "clip_sha256", "sheet": "sheet_sha256", "pixels": "sha256"}.get(kind)
    if part is None or not row.get(part):
        raise ValueError("That derivative is not part of this reference.")
    return _read_checked(ledger.root, row[part], row[sha_name], None)


def _write_context(ledger, payload, *, replacing):
    fields = _attach_fields(payload)
    _pending(ledger)
    beat = beat_for(ledger, fields["beat"], fields["fingerprint"])
    comment = beat.get("comment")
    style = deepcopy((ledger.data.get("ai") or {}).get("style"))
    _bind_still(ledger, beat, fields["still"])
    data = _read_body(fields)
    detected = _detect(data, fields["declared_type"])
    _reject_interval_shape(detected, fields["interval"])
    source_sha = hashlib.sha256(data).hexdigest()
    view = _view(ledger)
    with tempfile.TemporaryDirectory(dir=ledger.root, prefix=".ai-ref-") as temp_name:
        temp = Path(temp_name)
        staged = temp / "upload"
        staged.write_bytes(data)
        _fsync(staged)
        probed = _probe_staged(staged, detected)
        bounds = (
            _interval(
                fields["interval"] if fields["interval"] is not None else _instruction_interval(fields["instructions"]),
                probed,
            )
            if detected["kind"] == "video"
            else None
        )
        material = _material(fields, detected, source_sha, bounds)
        reused = _reused_context(ledger, view, fields, material)
        if reused is not None:
            return reused
        _require_active_slot(ledger, beat, view, fields, replacing=replacing)
        derivative = _derive(staged, temp, detected, probed, bounds)
        published = _publish_all(ledger.root, detected, data, probed, derivative)
        record = _context_record(
            fields,
            {
                "detected": detected,
                "probed": probed,
                "derivative": derivative,
                "material": material,
                "published": published,
            },
        )
        _store_context(ledger, beat, fields, {"record": record, "published": published, "replacing": replacing})
    if beat.get("comment") != comment:
        beat["comment"] = comment
    if (ledger.data.get("ai") or {}).get("style") != style:
        ledger.data["ai"]["style"] = style
    ledger.save("ai-reference-replace" if replacing else "ai-reference-attach")
    return show_reference(ledger, fields["beat"], fields["fingerprint"], fields["still_id"])


def _reused_context(ledger, view, fields, material):
    existing_owner, existing = _identity_owner(view, fields["identity"])
    if existing is None:
        return None
    same_bytes = existing_owner == "contexts" and existing.get("material") == material
    if not same_bytes:
        raise ValueError(_IDENTITY)
    active_id = (view.get("active") or {}).get(fields["key"])
    if active_id == existing.get("id"):
        return show_reference(ledger, fields["beat"], fields["fingerprint"], fields["still_id"])
    return show_saved(ledger, existing["id"])


def _require_active_slot(ledger, beat, view, fields, *, replacing):
    active = _exact_active(view, fields["key"])
    inherited = None
    if active is None and fields["still_id"]:
        inherited = _inherited_context(ledger, beat, view, fields["still_id"])
    if (active is not None or inherited is not None) and not replacing:
        raise ValueError("This beat already has an active reference. Replace or remove it explicitly.")
    if replacing and active is None and inherited is None:
        raise ValueError("Replace needs an active reference. Nothing was attached.")


def _store_context(ledger, beat, fields, saved):
    record = saved["record"]
    published = saved["published"]
    store = _ensure_store(ledger)
    if saved["replacing"]:
        current = _row(store, "contexts", (store.get("active") or {}).get(fields["key"]))
        if current is not None and current.get("status") == "active":
            current["status"] = "historical"
    store["originals"][record["original_sha256"]] = published["original"]
    store["derivatives"][record["derivative_id"]] = published["derivative"]
    store["contexts"][record["id"]] = record
    store["active"][fields["key"]] = record["id"]
    refs = beat.setdefault("references", [])
    if record["id"] not in refs:
        refs.append(record["id"])


def _attach_fields(payload):
    if not isinstance(payload, dict):
        raise ValueError("Reference upload must include the received file and its beat.")
    _unknown(payload, ATTACH_FIELDS)
    beat_id = text(payload.get("beat"), "Beat", 80)
    fingerprint_value = text(payload.get("fingerprint"), "Beat fingerprint", 80)
    still = _still_fields(payload.get("still"))
    scope, scope_instruction = _scope_fields(payload)
    interval = payload.get("interval")
    if interval is not None and not isinstance(interval, dict):
        raise ValueError("Video reference interval must be finite start_s and end_s. " + _OPENING)
    return {
        "beat": beat_id,
        "fingerprint": fingerprint_value,
        "identity": text(payload.get("identity"), "Request identity", 160),
        "name": _required_name(payload.get("name")),
        "declared_type": _declared(payload.get("declared_type")),
        "body": payload.get("body", None),
        "length": payload.get("length", None),
        "instructions": sanitize_public_text(
            text(payload.get("instructions"), "Reference instructions"), limit=MAX_PROMPT
        ),
        "role": _choice(payload.get("role"), ROLES, "Reference role"),
        "scope": scope,
        "scope_instruction": scope_instruction,
        "still": still,
        "still_id": still["id"] if still else None,
        "interval": interval,
        "key": _target_key(beat_id, fingerprint_value, still["id"] if still else None),
    }


def _target_fields(payload):
    if not isinstance(payload, dict):
        raise ValueError("Name the exact beat and fingerprint.")
    allowed = {"beat", "fingerprint", "still", "identity"}
    _unknown(payload, allowed)
    beat_id = text(payload.get("beat"), "Beat", 80)
    fingerprint_value = text(payload.get("fingerprint"), "Beat fingerprint", 80)
    still = _still_fields(payload.get("still"))
    identity = payload.get("identity")
    return {
        "beat": beat_id,
        "fingerprint": fingerprint_value,
        "still": still,
        "still_id": still["id"] if still else None,
        "identity": text(identity, "Request identity", 160) if identity is not None else None,
        "key": _target_key(beat_id, fingerprint_value, still["id"] if still else None),
    }


def _still_fields(still):
    if still is None:
        return None
    if not isinstance(still, dict) or set(still) != {"id", "signature"}:
        raise ValueError("Name the exact displayed still id and signature.")
    return {
        "id": text(still.get("id"), "Still id", 80),
        "signature": text(still.get("signature"), "Still signature", 80),
    }


def _scope_fields(payload):
    scope = payload.get("scope", "beat")
    scope = _choice(scope, SCOPES, "Reference scope")
    instruction = payload.get("scope_instruction")
    if scope == "beat":
        if instruction not in (None, ""):
            raise ValueError("Beat-local guidance does not take a shared-style instruction.")
        return scope, None
    if instruction is None:
        raise ValueError("Shared AI style needs an explicit scope instruction. Beat-local guidance was not expanded.")
    return scope, sanitize_public_text(text(instruction, "Scope instruction", 2000), limit=2000)


def _declared(value):
    if value is None:
        return None
    if value not in DECLARED:
        raise ValueError("Unsupported reference type. Supply a PNG, JPEG, or MP4.")
    return value


def _choice(value, choices, label):
    if value not in choices:
        raise ValueError(label + " must be one of: " + ", ".join(choices) + ".")
    return value


def _unknown(payload, allowed):
    extra = sorted(set(payload) - set(allowed))
    if extra:
        raise ValueError("Unsupported reference field: " + ", ".join(extra) + ".")


def _required_name(value):
    if not isinstance(value, str) or not value.strip() or len(value.strip()) > MAX_NAME:
        raise ValueError("The reference needs a valid display name (at most 300 characters).")
    cleaned = value.strip()
    if any(ord(char) < _LOWEST_PRINTABLE or ord(char) == _DELETE_CHAR for char in cleaned):
        raise ValueError("The reference needs a valid display name (at most 300 characters).")
    return sanitize_public_text(cleaned, limit=MAX_NAME)


def _safe_name(value):
    raw = value if isinstance(value, str) else ""
    base = raw.replace("\\", "/").rsplit("/", 1)[-1].strip()
    try:
        return _required_name(base)
    except ValueError:
        return "attachment"


def _read_body(fields):
    body = fields["body"]
    length = fields["length"]
    declared = fields["declared_type"]
    limit = MAX_IMAGE_BYTES if declared in IMAGE_DECLARED else MAX_VIDEO_BYTES
    _reject_declared_length(length, declared, limit)
    data = _body_bytes(body, length)
    if len(data) > limit:
        _oversized(declared, len(data))
    return data


def _reject_declared_length(length, declared, limit):
    if isinstance(length, bool) or (length is not None and type(length) is not int):
        raise ValueError(_INCOMPLETE)
    if type(length) is int and (length <= 0 or length > limit):
        _oversized(declared, length)


def _body_bytes(body, length):
    if isinstance(body, (str, Path)) or body is None:
        raise ValueError(_NOT_RECEIVED)
    if isinstance(body, (bytes, bytearray, memoryview)):
        return _exact_bytes(bytes(body), length)
    if hasattr(body, "read"):
        return _read_stream(body, length)
    raise ValueError(_NOT_RECEIVED)


def _exact_bytes(data, length):
    if length is None:
        length = len(data)
    if length != len(data) or length <= 0:
        raise ValueError(_INCOMPLETE)
    return data


def _read_stream(body, length):
    if type(length) is not int:
        raise ValueError(_INCOMPLETE)
    chunk = body.read(length + 1)
    if not isinstance(chunk, (bytes, bytearray)) or len(chunk) != length:
        raise ValueError(_INCOMPLETE)
    return bytes(chunk)


def _oversized(declared, length):
    if length <= 0:
        raise ValueError(_INCOMPLETE)
    if declared in IMAGE_DECLARED and length > MAX_IMAGE_BYTES:
        raise ValueError(
            f"Image reference exceeds the technical limit of {MAX_IMAGE_BYTES} bytes. The file was not saved."
        )
    if length > MAX_VIDEO_BYTES:
        raise ValueError(
            f"Video reference exceeds the technical upload limit of {MAX_VIDEO_BYTES} bytes. "
            "This is a resource limit, not a duration rule. The file was not saved."
        )
    raise ValueError(_INCOMPLETE)


def _detect(data, declared):
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        detected = {"kind": "image", "media": "png", "extension": "png", "declared": "image/png"}
    elif data.startswith(b"\xff\xd8\xff"):
        detected = {"kind": "image", "media": "jpeg", "extension": "jpg", "declared": "image/jpeg"}
    elif len(data) >= _MP4_BOX_PREFIX and data[4:8] == b"ftyp":
        detected = {"kind": "video", "media": "mp4", "extension": "mp4", "declared": "video/mp4"}
    else:
        raise ValueError("Supply an actual PNG, JPEG, or MP4. The file was not saved.")
    if declared is not None and declared != detected["declared"]:
        raise ValueError("Reference type does not match the file. The file was not saved.")
    limit = MAX_IMAGE_BYTES if detected["kind"] == "image" else MAX_VIDEO_BYTES
    if len(data) > limit:
        label = "Image" if detected["kind"] == "image" else "Video"
        extra = "" if detected["kind"] == "image" else " This is a resource limit, not a duration rule."
        raise ValueError(
            f"{label} reference exceeds the technical limit of {limit} bytes.{extra} The file was not saved."
        )
    return detected


def _reject_interval_shape(detected, interval):
    if detected["kind"] == "image" and interval is not None:
        raise ValueError("Image references do not take a video interval. No excerpt was saved.")


def _probe_staged(staged, detected):
    if detected["kind"] == "image":
        try:
            width, height = probe_image(staged, detected["extension"])
        except ValueError as exc:
            if str(exc) == "Image reference must contain at most 20 megapixels.":
                raise ValueError(
                    f"Image reference could not be decoded within the {MAX_IMAGE_PIXELS}-pixel processing limit. "
                    "Preserve the upload and retry with a PNG or JPEG."
                ) from exc
            raise
        except (OSError, subprocess.SubprocessError) as exc:
            raise ValueError(
                "Image reference could not be decoded. Preserve the upload and retry with a PNG or JPEG."
            ) from exc
        return {"width": width, "height": height, "duration_s": None, "fps": None, "audio": False}
    return _probe_video(staged)


def _probe_video(path):
    payload = _json_media(
        ["ffprobe", "-v", "error", "-show_streams", "-show_format", "-of", "json", str(path)],
        "ai_reference_probe",
    )
    streams = [row for row in payload.get("streams") or [] if isinstance(row, dict)]
    videos = [
        row
        for row in streams
        if row.get("codec_type") == "video" and not (row.get("disposition") or {}).get("attached_pic")
    ]
    if len(videos) != 1 or any(row.get("codec_type") not in {"video", "audio"} for row in streams):
        raise ValueError("Video reference must contain one decodable video stream. The file was not saved.")
    stream = videos[0]
    stream_index = stream.get("index")
    width = stream.get("width")
    height = stream.get("height")
    if (
        type(stream_index) is not int
        or stream_index < 0
        or type(width) is not int
        or type(height) is not int
        or width <= 0
        or height <= 0
    ):
        raise ValueError("Video reference measurements are missing. The file was not saved.")
    if width * height > MAX_IMAGE_PIXELS:
        raise ValueError(
            f"Video reference frame exceeds the technical limit of {MAX_IMAGE_PIXELS} pixels. The file was not saved."
        )
    rate = str(stream.get("avg_frame_rate") or "0/1")
    parts = rate.split("/", 1)
    try:
        fps = float(parts[0]) / float(parts[1] if len(parts) > 1 else 1)
    except (ValueError, ZeroDivisionError):
        fps = 0
    duration = _finite(stream.get("duration"))
    if duration is None:
        duration = _finite((payload.get("format") or {}).get("duration"))
    if duration is None or duration <= 0 or not math.isfinite(fps) or fps <= 0:
        raise ValueError("Video reference duration or frame rate is missing. The file was not saved.")
    _media(
        [
            "ffmpeg",
            "-v",
            "error",
            "-xerror",
            "-i",
            str(path),
            "-map",
            f"0:{stream_index}",
            "-map",
            "0:a?",
            "-f",
            "null",
            "-",
        ],
        "ai_reference_decode",
    )
    return {
        "video_stream_index": stream_index,
        "width": width,
        "height": height,
        "duration_s": duration,
        "fps": fps,
        "audio": any(row.get("codec_type") == "audio" for row in streams),
    }


def _derive(staged, temp, detected, probed, bounds):
    if detected["kind"] == "image":
        return _derive_image(staged, temp, detected)
    return _derive_video(staged, temp, detected, probed, bounds)


def _derive_image(staged, temp, detected):
    pixels = temp / "pixels.png"
    _media(
        ["ffmpeg", "-v", "error", "-y", "-i", str(staged), "-frames:v", "1", str(pixels)],
        "ai_reference_pixels",
    )
    if not pixels.is_file():
        raise ValueError("Image reference could not be decoded. The file was not saved.")
    sha = _file_sha(pixels)
    derivative_id = "drv-" + fingerprint({"kind": "image", "pixels": sha, "extension": detected["extension"]})[:24]
    return {
        "id": derivative_id,
        "kind": "image",
        "sha256": sha,
        "frames": [{"index": 0, "time_s": None, "sha256": sha, "path": pixels}],
        "sheet_sha256": None,
        "clip_sha256": None,
        "bounds": None,
        "opening_was_used": None,
        "opening_distinct": None,
        "audio_kept": False,
        "files": {"pixels": pixels},
    }


def _interval(interval, probed):
    duration = probed["duration_s"]
    if not isinstance(interval, dict) or "start_s" not in interval or "end_s" not in interval:
        raise ValueError(
            "Video reference interval needs finite start_s and end_s. "
            f"{_OPENING} Decoded duration is {duration:.3f} seconds."
        )
    extra = set(interval) - {"start_s", "end_s", "content"}
    if extra:
        raise ValueError("Unsupported interval field: " + ", ".join(sorted(extra)) + ". " + _OPENING)
    start = _real_seconds(interval.get("start_s"))
    end = _real_seconds(interval.get("end_s"))
    if start is None or end is None or start < 0 or end <= start:
        raise ValueError(
            "Video reference interval is not a positive finite range. "
            f"{_OPENING} Decoded duration is {duration:.3f} seconds."
        )
    tolerance = 1.0 / probed["fps"]
    if start > duration or end > duration + tolerance:
        raise ValueError(
            f"Requested video interval {start:g}–{end:g} exceeds the decoded duration of {duration:.3f} seconds. "
            + _UNTRUNCATED
        )
    content = interval.get("content")
    if content is not None:
        content = sanitize_public_text(text(content, "Requested interval content", 8000), limit=8000)
    return {"start_s": start, "end_s": end, "content": content, "duration_s": end - start}


def _instruction_interval(instructions):
    """Accept one explicit textual time range. Ambiguous prose never selects the opening."""
    matches = list(_INSTRUCTION_RANGE.finditer(instructions))
    ranges = [match for match in matches if match[3] or ":" in match[1] or ":" in match[2]]
    if len(ranges) != 1:
        raise ValueError("Name one video interval, for example 3–5 seconds or 00:03–00:05. " + _OPENING)

    def seconds(value):
        minutes, separator, seconds_part = value.replace(",", ".").partition(":")
        return float(minutes) * 60 + float(seconds_part) if separator else float(minutes)

    match = ranges[0]
    return {"start_s": seconds(match[1]), "end_s": seconds(match[2]), "content": instructions}


def _derive_video(staged, temp, detected, probed, bounds):
    times = frame_times(bounds["start_s"], bounds["end_s"], FRAME_SAMPLES)
    if not times or times[0] < bounds["start_s"] or times[-1] >= bounds["end_s"]:
        raise ValueError("The requested interval did not produce samples inside its bounds. " + _UNTRUNCATED)
    frames = []
    for index, stamp in enumerate(times):
        path = temp / f"frame-{index}.png"
        _extract_frame(staged, path, stamp, stream_index=probed["video_stream_index"])
        frames.append({"index": index, "time_s": stamp, "sha256": _file_sha(path), "path": path})
    sheet = temp / "sheet.png"
    _media(
        [
            "ffmpeg",
            "-v",
            "error",
            "-y",
            "-framerate",
            "1",
            "-start_number",
            "0",
            "-i",
            str(temp / "frame-%d.png"),
            "-vf",
            "tile=2x2",
            "-frames:v",
            "1",
            str(sheet),
        ],
        "ai_reference_sheet",
    )
    clip = temp / "clip.mp4"
    _media(
        [
            "ffmpeg",
            "-v",
            "error",
            "-y",
            "-i",
            str(staged),
            "-ss",
            f"{bounds['start_s']:.6f}",
            "-t",
            f"{bounds['duration_s']:.6f}",
            "-map",
            f"0:{probed['video_stream_index']}",
            "-c:v",
            "libx264",
            "-preset",
            "veryfast",
            "-pix_fmt",
            "yuv420p",
            *(["-map", "0:a?", "-c:a", "aac"] if probed["audio"] else ["-an"]),
            str(clip),
        ],
        "ai_reference_clip",
    )
    info = _probe_video(clip)
    slack = max(2.0 / probed["fps"], 0.05)
    if abs(info["duration_s"] - bounds["duration_s"]) > slack:
        raise ValueError("The derived clip duration does not match the requested interval. " + _UNTRUNCATED)
    if (info["width"], info["height"]) != (probed["width"], probed["height"]):
        raise ValueError("The derived clip changed the frame size. The opening was not kept as a substitute.")
    distinct = _verify_interval_content(temp, bounds, probed, (staged, frames[0]["path"], clip))
    clip_sha = _file_sha(clip)
    sheet_sha = _file_sha(sheet)
    derivative_id = (
        "drv-"
        + fingerprint(
            {
                "kind": "video",
                "source_extension": detected["extension"],
                "start": bounds["start_s"],
                "end": bounds["end_s"],
                "frames": [frame["sha256"] for frame in frames],
                "clip": clip_sha,
            }
        )[:24]
    )
    return {
        "id": derivative_id,
        "kind": "video",
        "sha256": clip_sha,
        "frames": frames,
        "sheet_sha256": sheet_sha,
        "clip_sha256": clip_sha,
        "bounds": {
            "start_s": bounds["start_s"],
            "end_s": bounds["end_s"],
            "duration_s": bounds["duration_s"],
            "clip_duration_s": info["duration_s"],
        },
        "opening_was_used": False,
        "opening_distinct": distinct,
        "audio_kept": bool(info["audio"]),
        "content": bounds.get("content"),
        "files": {"clip": clip, "sheet": sheet, **{f"frame-{frame['index']}": frame["path"] for frame in frames}},
    }


def _extract_frame(source, dest, stamp, *, stream_index=0):
    _media(
        [
            "ffmpeg",
            "-v",
            "error",
            "-y",
            "-i",
            str(source),
            "-map",
            f"0:{stream_index}",
            "-ss",
            f"{float(stamp):.6f}",
            "-frames:v",
            "1",
            str(dest),
        ],
        "ai_reference_frame",
    )
    if not dest.is_file() or dest.stat().st_size <= 0:
        raise ValueError("The requested interval did not yield a decodable frame. " + _OPENING)


def _verify_interval_content(temp, bounds, probed, samples):
    source, requested_frame, clip = samples
    opening = temp / "opening.png"
    _extract_frame(source, opening, 0, stream_index=probed["video_stream_index"])
    clip_frame = temp / "clip-first.png"
    _extract_frame(clip, clip_frame, 0)
    requested = _mean_rgb(requested_frame, temp / "requested.rgb")
    opened = _mean_rgb(opening, temp / "opening.rgb")
    derived = _mean_rgb(clip_frame, temp / "clip.rgb")
    if not _close(derived, requested, SAME_COLOR):
        raise ValueError(
            "Derived clip does not match the requested interval. The opening was not kept as a substitute."
        )
    distinct = bounds["start_s"] > (1.0 / probed["fps"]) and not _close(requested, opened, DISTINCT_COLOR)
    if distinct and _close(derived, opened, SAME_COLOR):
        raise ValueError("Derived clip matches the opening instead of the requested interval.")
    return distinct


def _mean_rgb(path, dest):
    _media(
        [
            "ffmpeg",
            "-v",
            "error",
            "-y",
            "-i",
            str(path),
            "-vf",
            "scale=1:1:flags=area",
            "-frames:v",
            "1",
            "-f",
            "rawvideo",
            "-pix_fmt",
            "rgb24",
            str(dest),
        ],
        "ai_reference_mean",
    )
    data = dest.read_bytes()
    if len(data) < _RGB_CHANNELS:
        raise ValueError("The reference frame could not be read. " + _OPENING)
    return data[0], data[1], data[2]


def _close(left, right, limit):
    return all(abs(a - b) <= limit for a, b in zip(left, right, strict=True))


def _material(fields, detected, source_sha, bounds):
    interval = None
    if bounds is not None:
        interval = {"start_s": bounds["start_s"], "end_s": bounds["end_s"], "content": bounds.get("content")}
    return fingerprint(
        {
            "beat": fields["beat"],
            "fingerprint": fields["fingerprint"],
            "still": fields["still"],
            "role": fields["role"],
            "instructions": fields["instructions"],
            "scope": fields["scope"],
            "scope_instruction": fields["scope_instruction"],
            "name": fields["name"],
            "media": detected["media"],
            "original_sha256": source_sha,
            "interval": interval,
        }
    )


def _context_record(fields, parts):
    detected = parts["detected"]
    probed = parts["probed"]
    derivative = parts["derivative"]
    material = parts["material"]
    published = parts["published"]
    original = published["original"]
    return {
        "id": "ctx-" + fingerprint({"identity": fields["identity"], "material": material})[:24],
        "identity": fields["identity"],
        "status": "active",
        "beat": fields["beat"],
        "fingerprint": fields["fingerprint"],
        "still": fields["still"],
        "role": fields["role"],
        "scope": fields["scope"],
        "scope_instruction": fields["scope_instruction"],
        "instructions": fields["instructions"],
        "name": fields["name"],
        "kind": detected["kind"],
        "media": detected["media"],
        "original_sha256": original["sha256"],
        "bytes": original["bytes"],
        "width": probed["width"],
        "height": probed["height"],
        "duration_s": probed["duration_s"],
        "audio": probed["audio"],
        "interval": _stored_interval(derivative),
        "derivative_id": derivative["id"],
        "inspection": {"state": "uninspected"},
        "material": material,
        "created_at": now(),
    }


def _stored_interval(derivative):
    if derivative["kind"] != "video":
        return None
    bounds = derivative["bounds"]
    return {
        "start_s": bounds["start_s"],
        "end_s": bounds["end_s"],
        "content": derivative.get("content"),
    }


def _publish_all(root, detected, data, probed, derivative):
    sha = hashlib.sha256(data).hexdigest()
    original_rel = f"{PREFIX}originals/{sha}.{detected['extension']}"
    created = []
    try:
        original_path, was_new = _publish_file(root, original_rel, data)
        if was_new:
            created.append(original_path)
        if digest(original_path) != sha:
            raise ValueError(_ALTERED)
        derivative_record = _publish_derivative(root, derivative, sha, created)
    except Exception:
        for path in created:
            with contextlib.suppress(OSError):
                path.unlink(missing_ok=True)
        raise
    return {
        "original": {
            "sha256": sha,
            "ref": original_rel,
            "bytes": len(data),
            "kind": detected["kind"],
            "media": detected["media"],
            "width": probed["width"],
            "height": probed["height"],
            "duration_s": probed["duration_s"],
        },
        "derivative": derivative_record,
    }


def _publish_derivative(root, derivative, source_sha, created):
    base = f"{PREFIX}derivatives/{derivative['id']}"
    record = {
        "id": derivative["id"],
        "source_sha256": source_sha,
        "kind": derivative["kind"],
        "sha256": derivative["sha256"],
        "clip_sha256": derivative["clip_sha256"],
        "sheet_sha256": derivative["sheet_sha256"],
        "bounds": derivative["bounds"],
        "opening_was_used": derivative["opening_was_used"],
        "opening_distinct": derivative["opening_distinct"],
        "audio_kept": derivative["audio_kept"],
        "frames": [],
    }
    if derivative["kind"] == "image":
        rel = base + "/pixels.png"
        path, was_new = _publish_file(root, rel, derivative["files"]["pixels"].read_bytes())
        if was_new:
            created.append(path)
        record["pixels_ref"] = rel
        record["frames"] = [{"index": 0, "time_s": None, "sha256": derivative["sha256"], "ref": rel}]
        return record
    for name, suffix, key in (("clip", "/clip.mp4", "clip_ref"), ("sheet", "/sheet.png", "sheet_ref")):
        rel = base + suffix
        path, was_new = _publish_file(root, rel, derivative["files"][name].read_bytes())
        if was_new:
            created.append(path)
        record[key] = rel
    for frame in derivative["frames"]:
        rel = f"{base}/frame-{frame['index']}.png"
        path, was_new = _publish_file(root, rel, frame["path"].read_bytes())
        if was_new:
            created.append(path)
        record["frames"].append(
            {"index": frame["index"], "time_s": frame["time_s"], "sha256": frame["sha256"], "ref": rel}
        )
    return record


def _publish_file(root, rel, data):
    dest = _planned(root, rel)
    if dest.exists() or dest.is_symlink() or _is_link_or_junction(dest):
        if _is_link_or_junction(dest) or dest.is_symlink() or not dest.is_file():
            raise ValueError(_LINK)
        if digest(dest) == hashlib.sha256(data).hexdigest() and dest.stat().st_size == len(data):
            return dest, False
        raise ValueError(_OCCUPIED)
    parent = _planned(root, str(Path(rel).parent).replace("\\", "/"))
    parent.mkdir(parents=True, exist_ok=True)
    if _is_link_or_junction(parent) or not parent.is_dir():
        raise ValueError(_LINK)
    dest = _planned(root, rel)
    staged = dest.with_name(".upload-" + dest.name)
    if staged.exists() or staged.is_symlink() or _is_link_or_junction(staged):
        raise ValueError(_LINK)
    staged.write_bytes(data)
    _fsync(staged)
    try:
        os.link(staged, dest)
    except FileExistsError:
        staged.unlink(missing_ok=True)
        if digest(dest) == hashlib.sha256(data).hexdigest():
            return dest, False
        raise ValueError(_OCCUPIED) from None
    finally:
        staged.unlink(missing_ok=True)
    if _is_link_or_junction(dest) or digest(dest) != hashlib.sha256(data).hexdigest():
        dest.unlink(missing_ok=True)
        raise ValueError(_ALTERED)
    return dest, True


def _planned(root, rel):
    try:
        relative_audio_ref(rel, (PREFIX,))
        path = _confine_planned(Path(root), Path(root) / rel)
    except ValueError as exc:
        lowered = str(exc).lower()
        if "symlink" in lowered or "junction" in lowered or "link" in lowered:
            raise ValueError(_LINK) from exc
        raise ValueError(_ESCAPE) from exc
    if path.exists() and _is_link_or_junction(path):
        raise ValueError(_LINK)
    return path


def _existing(root, rel):
    try:
        path = _confine_existing(Path(root), rel, (PREFIX,))
    except ValueError as exc:
        lowered = str(exc).lower()
        if "symlink" in lowered or "junction" in lowered:
            raise ValueError(_LINK) from exc
        raise ValueError(_ESCAPE) from exc
    if _is_link_or_junction(path):
        raise ValueError(_LINK)
    return path


def _read_checked(root, rel, sha256, size):
    path = _existing(root, rel)
    if digest(path) != sha256 or (size is not None and path.stat().st_size != size):
        raise ValueError(_ALTERED)
    return path.read_bytes()


def _bind_still(ledger, beat, still):
    if still is None:
        return
    displayed = _displayed_version(ledger, beat)
    if displayed is None or displayed.get("kind") != "image" or displayed.get("id") != still["id"]:
        raise ValueError("That still is not the displayed result. The reference was not bound to a different image.")
    if displayed.get("beat") != beat["id"] or displayed.get("inputs") != beat["fingerprint"]:
        raise ValueError("The displayed still belongs to a different beat. Nothing was bound.")
    if version_signature(displayed) != still["signature"]:
        raise ValueError("The displayed still signature changed. Nothing was bound.")
    if not _still_intact(ledger, displayed):
        raise ValueError("The displayed still bytes changed. Nothing was bound.")


def _displayed_version(ledger, beat):
    from .ai import _card_focus, _latest_job

    ai = ledger.data.get("ai") or {}
    jobs = ai.get("jobs")
    if not isinstance(jobs, dict):
        jobs = {}
    versions = ai.get("versions")
    if not isinstance(versions, dict):
        versions = {}
    job = _latest_job(jobs, beat)
    version = None
    if isinstance(job, dict):
        candidate = versions.get(job.get("result") or "")
        if isinstance(candidate, dict):
            version = candidate
    _job, focused = _card_focus(ai, beat, job, version)
    return focused if isinstance(focused, dict) else None


def _still_intact(ledger, version):
    from .narration import _confine_existing_file

    rel = version.get("path")
    if not isinstance(rel, str):
        return False
    try:
        path = _confine_existing_file(ledger.root, rel, ("previews/", "clips/"))
    except ValueError:
        return False
    try:
        return digest(path) == version.get("sha256")
    except OSError:
        return False


def _pending(ledger):
    if ledger.pending.exists():
        raise ValueError("A project write is pending. Finish it with the CLI before saving references.")


def _view(ledger):
    raw = (ledger.data.get("ai") or {}).get("references")
    if raw is None:
        return {key: {} for key in STORE_KEYS}
    if not isinstance(raw, dict):
        raise ValueError("Invalid AI reference collection.")
    return raw


def _ensure_store(ledger):
    ai = state(ledger.data)
    raw = ai.get("references")
    if not isinstance(raw, dict):
        raise ValueError("Invalid AI reference collection.")
    for key in STORE_KEYS:
        if key not in raw:
            raw[key] = {}
        if not isinstance(raw[key], dict):
            raise ValueError("Invalid AI reference collection.")
    return raw


def _row(store, key, ident):
    if not isinstance(ident, str):
        return None
    row = (store.get(key) or {}).get(ident)
    return row if isinstance(row, dict) else None


def _identity_owner(store, identity):
    for key in ("contexts", "inputs", "invalidations"):
        for row in (store.get(key) or {}).values():
            if isinstance(row, dict) and row.get("identity") == identity:
                return key, row
    return None, None


def _same_still(active, fields):
    stored = active.get("still")
    supplied = fields["still"]
    if stored is None and supplied is None:
        return
    if (
        not isinstance(stored, dict)
        or not isinstance(supplied, dict)
        or stored.get("id") != supplied.get("id")
        or stored.get("signature") != supplied.get("signature")
    ):
        raise ValueError("The displayed still signature changed. Nothing was bound.")


def _affected_scope(store, ident):
    context = _row(store, "contexts", ident)
    if context is not None:
        return context
    frozen = _row(store, "inputs", ident)
    if frozen is not None and isinstance(frozen.get("snapshot"), dict):
        return frozen["snapshot"]
    return None


def _require_active(store, fields):
    active = _row(store, "contexts", (store.get("active") or {}).get(fields["key"]))
    if active is None or active.get("status") != "active":
        raise ValueError("There is no active reference for this exact target.")
    return active


def _active_key_for(store, ident):
    for key, value in (store.get("active") or {}).items():
        if value == ident:
            return key
    return None


def _invalidated(store, ident):
    for row in (store.get("invalidations") or {}).values():
        if isinstance(row, dict) and ident in (row.get("affected") or []):
            return row
    return None


def _preserved(ledger, beat, store, displayed, active):
    rows = []
    active_id = active.get("id") if isinstance(active, dict) else None
    for ident in beat.get("references") or []:
        if ident == active_id or not isinstance(ident, str):
            continue
        record = _row(store, "contexts", ident)
        if record is not None:
            rows.append(_public(ledger, beat, record, displayed, store))
    return rows


def _public(ledger, beat, record, displayed, store):
    _require_bytes(ledger, store, record)
    derivative = _row(store, "derivatives", record.get("derivative_id"))
    inspection = record.get("inspection") if isinstance(record.get("inspection"), dict) else {}
    inspected = inspection.get("state") == "inspected"
    invalidation = _invalidated(store, record["id"])
    video = record.get("kind") == "video"
    return {
        "state": record.get("status"),
        "context_id": record.get("id"),
        "identity": record.get("identity"),
        "beat": record.get("beat"),
        "fingerprint": record.get("fingerprint"),
        "still": deepcopy(record.get("still")),
        "displayed_still": displayed.get("id") if displayed else None,
        "applies_to_displayed_still": _applies(ledger, record, displayed, store),
        "applies_to_current_fingerprint": record.get("fingerprint") == beat.get("fingerprint"),
        "invalidated": invalidation is not None,
        "invalidation_reason": invalidation.get("reason") if invalidation else None,
        "role": record.get("role"),
        "scope": record.get("scope"),
        "scope_instruction": record.get("scope_instruction"),
        "shared_style_applied": False,
        "instructions": record.get("instructions"),
        "name": record.get("name"),
        "kind": record.get("kind"),
        "media": record.get("media"),
        "sha256": record.get("original_sha256"),
        "bytes": record.get("bytes"),
        "width": record.get("width"),
        "height": record.get("height"),
        "duration_s": record.get("duration_s"),
        "audio": record.get("audio"),
        "interval": deepcopy(record.get("interval")),
        "interval_truncated": False if video else None,
        "opening_was_used": derivative.get("opening_was_used") if video and derivative else False if video else None,
        "derivative": _public_derivative(derivative),
        "inspection": "inspected" if inspected else "uninspected",
        "inspection_origin": inspection.get("origin") if inspected else None,
        "findings": inspection.get("findings") if inspected else None,
        "provider_input": _provider_claim(inspection) if inspected else "unsupported",
        "provider_access": False,
        "received": True,
        "transferred": True,
        "created_at": record.get("created_at"),
        "limits": dict(LIMITS),
    }


def _public_input(ledger, beat, record, store):
    snapshot = record["snapshot"]
    displayed = None
    if snapshot.get("fingerprint") == beat.get("fingerprint"):
        displayed = _displayed_version(ledger, beat)
    public = _public(ledger, beat, snapshot, displayed, store)
    public["input_id"] = record["id"]
    public["state"] = "historical"
    public["frozen"] = True
    invalidation = _invalidated(store, record["id"])
    public["invalidated"] = invalidation is not None
    public["invalidation_reason"] = invalidation.get("reason") if invalidation else None
    return public


def _public_invalidation(record):
    return {
        "id": record["id"],
        "identity": record["identity"],
        "beat": record["beat"],
        "fingerprint": record["fingerprint"],
        "affected": list(record["affected"]),
        "reason": record["reason"],
        "deleted_media": False,
        "provider_input": "unsupported",
    }


def _public_derivative(derivative):
    if not isinstance(derivative, dict):
        return None
    return {
        "id": derivative.get("id"),
        "sha256": derivative.get("sha256"),
        "clip_sha256": derivative.get("clip_sha256"),
        "sheet_sha256": derivative.get("sheet_sha256"),
        "frames": _public_frames_from(derivative),
        "bounds": deepcopy(derivative.get("bounds")),
        "opening_was_used": derivative.get("opening_was_used"),
        "opening_distinct": derivative.get("opening_distinct"),
        "audio_kept": derivative.get("audio_kept"),
    }


def _public_frames(store, record):
    return _public_frames_from(_row(store, "derivatives", record.get("derivative_id")))


def _public_frames_from(derivative):
    if not isinstance(derivative, dict):
        return []
    return [
        {"index": frame.get("index"), "time_s": frame.get("time_s"), "sha256": frame.get("sha256")}
        for frame in derivative.get("frames") or []
        if isinstance(frame, dict)
    ]


def _derivative_hashes(store, record):
    derivative = _row(store, "derivatives", record.get("derivative_id"))
    if derivative is None:
        return []
    hashes = [derivative.get("sha256"), derivative.get("clip_sha256"), derivative.get("sheet_sha256")]
    hashes.extend(frame.get("sha256") for frame in derivative.get("frames") or [] if isinstance(frame, dict))
    return sorted({item for item in hashes if isinstance(item, str)})


def _require_bytes(ledger, store, record):
    original = _row(store, "originals", record.get("original_sha256"))
    if original is None:
        raise ValueError("Saved reference original is missing. The request was not retargeted.")
    _read_checked(ledger.root, original["ref"], original["sha256"], original["bytes"])
    derivative = _row(store, "derivatives", record.get("derivative_id"))
    if derivative is None:
        raise ValueError("Saved reference derivative is missing. The request was not retargeted.")
    if derivative.get("kind") == "image":
        _read_checked(ledger.root, derivative["pixels_ref"], derivative["sha256"], None)
        return
    _read_checked(ledger.root, derivative["clip_ref"], derivative["clip_sha256"], None)
    _read_checked(ledger.root, derivative["sheet_ref"], derivative["sheet_sha256"], None)
    for frame in derivative.get("frames") or []:
        _read_checked(ledger.root, frame["ref"], frame["sha256"], None)


def _applies(ledger, record, displayed, store):  # noqa: PLR0911 - Each early refusal checks a separate retained-guidance invariant.
    """True when this active context is the displayed still's validated guidance."""
    if not isinstance(record, dict) or not isinstance(displayed, dict):
        return False
    if record.get("status") != "active" or _invalidated(store, record.get("id")):
        return False
    if record.get("beat") != displayed.get("beat") or record.get("fingerprint") != displayed.get("inputs"):
        return False
    beat = {"id": displayed.get("beat"), "fingerprint": displayed.get("inputs")}
    try:
        resolved = _active_for_still(ledger, beat, store, displayed.get("id"))
    except (ValueError, OSError):
        return False
    if not isinstance(resolved, dict) or resolved.get("id") != record.get("id"):
        return False
    still = record.get("still")
    if isinstance(still, dict) and still.get("id") == displayed.get("id"):
        if version_signature(displayed) != still.get("signature"):
            return False
        return _still_intact(ledger, displayed)
    return True


def _target_key(beat_id, fingerprint_value, still_id):
    if still_id:
        return f"{beat_id}:{fingerprint_value}:{still_id}"
    return f"{beat_id}:{fingerprint_value}"


def _exact_active(store, key):
    row = _row(store, "contexts", (store.get("active") or {}).get(key))
    if row is None or row.get("status") != "active" or _invalidated(store, row.get("id")):
        return None
    return row


def _versions(ledger):
    versions = (ledger.data.get("ai") or {}).get("versions")
    return versions if isinstance(versions, dict) else {}


def _jobs(ledger):
    jobs = (ledger.data.get("ai") or {}).get("jobs")
    return jobs if isinstance(jobs, dict) else {}


def _image_version(ledger, beat, still_id):
    """Return one stored still on this beat and fingerprint, or None when the id is unknown."""
    version = _versions(ledger).get(still_id) if isinstance(still_id, str) else None
    if not isinstance(version, dict):
        return None
    if version.get("kind") != "image":
        raise ValueError("The retained result is not a still. Guidance was not applied.")
    if version.get("beat") != beat["id"]:
        raise ValueError("The retained still belongs to another beat. Guidance was not applied.")
    if version.get("inputs") != beat["fingerprint"]:
        raise ValueError("The retained still belongs to a different beat revision. Guidance was not applied.")
    if not _still_intact(ledger, version):
        raise ValueError("The retained still bytes changed. Guidance was not applied.")
    return version


def _producing_edge(ledger, beat, version):
    """Completed job that produced this still. A broken result link is not a parent edge."""
    job_id = version.get("job")
    if not isinstance(job_id, str) or not job_id:
        raise ValueError("The retained still lineage is missing. Guidance was not applied.")
    job = _jobs(ledger).get(job_id)
    if not isinstance(job, dict) or job.get("id") != job_id:
        raise ValueError("The retained still lineage is missing. Guidance was not applied.")
    if job.get("state") != "complete" or job.get("result") != version.get("id"):
        raise ValueError("The retained still's producing job does not match this result. Guidance was not applied.")
    request = job.get("request")
    if not isinstance(request, dict):
        raise ValueError("The retained still lineage is missing. Guidance was not applied.")
    if request.get("beat") != beat["id"] or request.get("inputs") != beat["fingerprint"]:
        raise ValueError("The retained still belongs to another beat. Guidance was not applied.")
    if request.get("kind", "image") != "image":
        raise ValueError("The retained still lineage is not an image revision. Guidance was not applied.")
    stored = job.get("fingerprint")
    if not isinstance(stored, str) or stored != fingerprint(request):
        raise ValueError("The retained still lineage is invalid. Guidance was not applied.")
    return request


def _lineage_parent(ledger, beat, version):
    """Follow the stored job target one step. A root still has no parent. Invalid lineage raises."""
    request = _producing_edge(ledger, beat, version)
    target = request.get("target")
    if target is None:
        return None
    if not isinstance(target, dict):
        raise ValueError("The retained still lineage is invalid. Guidance was not applied.")
    parent_id = target.get("id")
    signature = target.get("signature")
    digest_value = target.get("sha256")
    if not isinstance(parent_id, str) or not isinstance(signature, str) or not isinstance(digest_value, str):
        raise ValueError("The retained still lineage is invalid. Guidance was not applied.")
    parent = _image_version(ledger, beat, parent_id)
    if parent is None:
        raise ValueError("The retained ancestor still is missing. Guidance was not applied.")
    if version_signature(parent) != signature or parent.get("sha256") != digest_value:
        raise ValueError("The retained still changed. Its guidance was not applied to a different image.")
    return parent


def _retained_override(store, beat, version):
    """A removal at this still. It does not invalidate the ancestor context."""
    signature = version_signature(version)
    found = None
    for row in (store.get("invalidations") or {}).values():
        if not isinstance(row, dict) or row.get("kind") != "retained-override":
            continue
        if row.get("beat") != beat["id"] or row.get("fingerprint") != beat["fingerprint"]:
            continue
        still = row.get("still")
        if not isinstance(still, dict) or still.get("id") != version.get("id"):
            continue
        if still.get("signature") != signature:
            raise ValueError("The retained still changed. Removed guidance was not applied to a different image.")
        found = row
    return found


def _accepted_retained(ledger, beat, store, context, version):
    if context.get("beat") != beat["id"] or context.get("fingerprint") != beat["fingerprint"]:
        raise ValueError("The retained reference belongs to another beat. Guidance was not applied.")
    still = context.get("still")
    if (
        not isinstance(still, dict)
        or still.get("id") != version.get("id")
        or still.get("signature") != version_signature(version)
    ):
        raise ValueError("The retained still changed. Its guidance was not applied to a different image.")
    if not _still_intact(ledger, version):
        raise ValueError("The retained still bytes changed. Guidance was not applied.")
    _require_bytes(ledger, store, context)
    return context


def _inherited_context(ledger, beat, store, still_id):
    """Nearest active ancestor context. Never the newest unrelated still, and never a rewritten binding."""
    version = _image_version(ledger, beat, still_id)
    if version is None:
        return None
    if _retained_override(store, beat, version) is not None:
        return None
    seen = {version["id"]}
    current = version
    while True:
        parent = _lineage_parent(ledger, beat, current)
        if parent is None:
            return None
        if parent["id"] in seen:
            raise ValueError("The retained still lineage repeats. Guidance was not applied.")
        seen.add(parent["id"])
        context = _exact_active(store, _target_key(beat["id"], beat["fingerprint"], parent["id"]))
        if context is not None:
            return _accepted_retained(ledger, beat, store, context, parent)
        if _retained_override(store, beat, parent) is not None:
            return None
        current = parent


def _active_for_still(ledger, beat, store, still_id):
    """Exact guidance for this still, otherwise the nearest validated ancestor."""
    exact = _exact_active(store, _target_key(beat["id"], beat["fingerprint"], still_id))
    if exact is not None:
        return exact
    return _inherited_context(ledger, beat, store, still_id)


def _displayed_target(ledger, beat, still):
    if still is None:
        return None
    _bind_still(ledger, beat, still)
    version = _image_version(ledger, beat, still["id"])
    if version is None:
        raise ValueError("The retained still lineage is missing. Guidance was not applied.")
    return version


def _retire_exact_context(ledger, key):
    store = _ensure_store(ledger)
    current = _exact_active(store, key)
    if current is None:
        return None
    current["status"] = "removed"
    store["active"].pop(key, None)
    return current["id"]


def _write_retained_override(ledger, beat, version, blocked):
    """Record that this still refuses ancestor guidance. The ancestor context stays where it was."""
    store = _ensure_store(ledger)
    existing = _retained_override(store, beat, version)
    if existing is not None:
        return existing
    signature = version_signature(version)
    material = fingerprint(
        {
            "kind": "retained-override",
            "beat": beat["id"],
            "fingerprint": beat["fingerprint"],
            "still": version["id"],
            "signature": signature,
            "blocked": blocked,
        }
    )
    identity = "ovr-" + material[:48]
    owner, prior = _identity_owner(store, identity)
    if prior is not None:
        if owner == "invalidations" and prior.get("material") == material:
            return prior
        raise ValueError(_IDENTITY)
    record = {
        "id": "ovr-" + fingerprint({"identity": identity, "material": material})[:24],
        "identity": identity,
        "material": material,
        "kind": "retained-override",
        "beat": beat["id"],
        "fingerprint": beat["fingerprint"],
        "still": {"id": version["id"], "signature": signature},
        "blocked": blocked,
        "affected": [],
        "reason": "Removed at this result. Older guidance stays on its original still.",
        "created_at": now(),
    }
    store["invalidations"][record["id"]] = record
    return record


def _real_seconds(value):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        return None
    return float(value)


def _finite(value):
    if isinstance(value, bool) or value in (None, "N/A", ""):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(number):
        return None
    return number


def _json_media(args, label):
    import json

    try:
        payload = json.loads(_media(args, label))
    except json.JSONDecodeError as exc:
        raise ValueError("The reference could not be decoded. The file was not saved.") from exc
    if not isinstance(payload, dict):
        raise ValueError("The reference could not be decoded. The file was not saved.")
    return payload


def _media(args, label):
    try:
        return media_run(args, op=label)
    except ValueError as exc:
        message = str(exc)
        if "180s" in message or "excedeu" in message:
            raise ValueError(
                "The requested reference could not be processed within the technical time limit. " + _UNTRUNCATED
            ) from exc
        raise ValueError(
            "The reference could not be decoded. Preserve the upload and retry with a supported PNG, JPEG, or MP4."
        ) from exc


def _file_sha(path):
    return digest(path)


def _fsync(path):
    """Flush through a writable handle. A read-only handle fails on Windows (EBADF)."""
    with Path(path).open("r+b") as handle:
        handle.flush()
        os.fsync(handle.fileno())
