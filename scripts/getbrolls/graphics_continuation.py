"""Explicit continuation using the existing ledger and immutable render snapshots."""

from __future__ import annotations

import copy
import json
import uuid
from types import SimpleNamespace

from .ledger import digest
from .models import now

REPAIR_LIMIT = 2


def handoff_command(ledger, args):  # noqa: C901 - one snapshot boundary checks the actual version, reference base and existing scene inputs.
    """Persist reconstructable inputs; the host owns actual delegation and its evidence."""
    from . import graphics as g

    graphics, occurrence = g._require_occurrence(ledger, args.occurrence)
    context = args.host_context
    if context is not None and not g._bounded_text(context, 200):
        raise ValueError("--host-context must identify an actually observed host scene context.")
    request = None
    if args.request:
        request = next((item for item in graphics.get("requests", []) if item["id"] == args.request), None)
        if not isinstance(request, dict) or request.get("occurrence_id") != occurrence["occurrence_id"]:
            raise ValueError("Revision request must identify this exact occurrence.")
        if request.get("processing") is not None or request.get("state") != "saved":
            raise ValueError("Revision request was already processed; do not replay it.")
        if request.get("reference_change") and g._request_stale_reason(request, graphics):
            raise ValueError("Active reference context changed; preserve the fixed request target.")
        if request.get("kind") == "authoring":
            if g._request_stale_reason(request, graphics):
                raise ValueError("Initial reference assignment changed; preserve the original request.")
        elif request.get("reviewed_version") != occurrence.get("current_version"):
            raise ValueError("Select the actually reviewed version before restoring an older-version request.")
        if request.get("reviewed_version") is not None:
            reviewed = graphics["versions"][request["reviewed_version"]]
            if request["content_sha256"] != g.graphics_content_sha256(reviewed):
                raise ValueError("Reviewed version content changed; preserve the stale request.")
    refs = g._assignment_input_refs(occurrence)
    pairs = g._confine_refs(ledger.root, refs, g.INPUT_PREFIXES)
    versions = {
        key: copy.deepcopy(version)
        for key, version in graphics["versions"].items()
        if version["occurrence_id"] == occurrence["occurrence_id"]
    }
    packet = {
        "schema_version": 1,
        "project_id": g._ledger_project_id(ledger),
        "occurrence": copy.deepcopy(occurrence),
        "assignment_sha256": assignment_signature(occurrence),
        "style": copy.deepcopy(
            next(item for item in graphics["style_revisions"] if item["revision"] == occurrence["style_revision"])
        ),
        "profile": copy.deepcopy(graphics["profile"]),
        "input_hashes": {ref: digest(path) for ref, path in pairs},
        "versions": versions,
        "revision_request": copy.deepcopy(request),
        "work": work_status(ledger.root, occurrence),
        "host_context": context,
        "delegation_observed": False,
        "instruction": "One continuous occurrence only. Save work before the next assignment. Preserve original narration and meaning; return new scene ideas to the manager. Human questions pause this occurrence only. Use at most two scene-code repairs. A host-context label alone is not evidence of execution.",
    }
    if occurrence["occurrence_id"] in graphics.get("reference_states", {}):
        from .graphics_reference_context import active, scope_status
        from .graphics_references import checked_references

        sha, state = active(graphics, occurrence["occurrence_id"])
        checked_references(ledger.root, {"references": state["references"], "reference_change": {}})
        packet["active_references"] = {"sha256": sha, **state}
        packet["reference_scopes"] = [
            group
            for group in scope_status(graphics)
            if group["source_occurrence_id"] == occurrence["occurrence_id"]
            or any(t["occurrence_id"] == occurrence["occurrence_id"] for t in group["targets"])
        ]
    ref = "graphics-data/handoff-" + occurrence["occurrence_id"] + "-" + uuid.uuid4().hex + ".json"
    path = g._confine_planned(ledger.root, ledger.root / ref)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8") as stream:
        json.dump(packet, stream, ensure_ascii=False, indent=2, allow_nan=False)
        stream.write("\n")
    checkpoint = {
        "stage": "authoring",
        "at": now(),
        "outcome": "Scene context packet saved; host delegation remains external.",
        "assignment_sha256": assignment_signature(occurrence),
        "files": {ref: digest(path)},
    }
    occurrence.setdefault("work", {"checkpoints": [], "repairs": []})["checkpoints"].append(checkpoint)
    ledger.save("graphics-handoff")
    return {"occurrence": occurrence["occurrence_id"], "packet_ref": ref, "sha256": digest(path), "agents_launched": 0}


def _validate_checkpoint(checkpoint):
    from .graphics import _bounded_prose, _sha256, relative_artifact

    if not isinstance(checkpoint, dict) or set(checkpoint) != {"stage", "at", "files", "outcome", "assignment_sha256"}:
        raise ValueError
    if checkpoint["stage"] not in ("research", "authoring", "waiting", "error"):
        raise ValueError
    if not isinstance(checkpoint["files"], dict) or not _bounded_prose(checkpoint["outcome"]):
        raise ValueError
    if checkpoint["stage"] in ("research", "authoring") and not checkpoint["files"]:
        raise ValueError
    if not _sha256(checkpoint["assignment_sha256"]) or not _bounded_prose(checkpoint["at"], 100):
        raise ValueError
    for rel, value in checkpoint["files"].items():
        relative_artifact(rel, prefixes=("graphics-data/", "previews/", "clips/"))
        if not _sha256(value):
            raise ValueError


def validate_work(occurrence):
    from .graphics import VERSION_RE, _bounded_prose

    work = occurrence.get("work")
    if work is None:
        return
    if not isinstance(work, dict) or set(work) != {"checkpoints", "repairs"}:
        raise ValueError
    if (
        not isinstance(work["checkpoints"], list)
        or not isinstance(work["repairs"], list)
        or len(work["repairs"]) > REPAIR_LIMIT
    ):
        raise ValueError
    for repair in work["repairs"]:
        if (
            not isinstance(repair, dict)
            or set(repair) != {"version", "at"}
            or not isinstance(repair.get("version"), str)
            or not VERSION_RE.fullmatch(repair["version"])
            or not _bounded_prose(repair.get("at"), 100)
        ):
            raise ValueError
    for checkpoint in work["checkpoints"]:
        _validate_checkpoint(checkpoint)


def assignment_signature(occurrence):
    from .graphics import ASSIGNMENT_FIELDS, _payload_hash

    return _payload_hash(
        {key: occurrence.get(key) for key in ASSIGNMENT_FIELDS if key != "reference_context" or key in occurrence}
    )


def _repair_meaning_changed(previous, current):
    from .graphics import _assignment_changed

    old, new = copy.deepcopy(previous), copy.deepcopy(current)
    for assignment in (old, new):
        content = assignment.get("scene_content")
        if assignment.get("template") != "custom" or not isinstance(content, dict):
            continue
        content["source_sha256"] = "authored-code-repair"
        for entry in assignment.get("material_use") or []:
            if entry["ref"] == content["source_ref"]:
                entry["sha256"] = "authored-code-repair"
    return _assignment_changed(old, new)


def register_render_attempt(graphics, occurrence, record, *, repair):
    """Reserve a repair before execution. Continuation never resets this allowance."""
    latest = next(
        (v for v in reversed(list(graphics["versions"].values())) if v["occurrence_id"] == occurrence["occurrence_id"]),
        None,
    )
    work = occurrence.get("work") or {"checkpoints": [], "repairs": []}
    same_failed = (
        latest is not None
        and latest["status"] == "failed"
        and not _repair_meaning_changed(latest["assignment"], occurrence)
    )
    if repair and not same_failed:
        raise ValueError("--repair requires a failed scene with unchanged narrative meaning and assignment.")
    if same_failed:
        if len(work["repairs"]) >= REPAIR_LIMIT:
            raise ValueError("The two scene-code repair attempts are exhausted; partial work and diagnostics retained.")
        work["repairs"].append({"version": record["id"], "at": now()})
        occurrence["work"] = work


def checkpoint_command(ledger, args):
    from .graphics import INPUT_PREFIXES, _bounded_prose, _confine_refs, _require_occurrence

    _graphics, occurrence = _require_occurrence(ledger, args.occurrence)
    if not _bounded_prose(args.outcome):
        raise ValueError("A checkpoint needs a bounded --outcome describing the actual saved work.")
    pairs = _confine_refs(ledger.root, args.ref or [], prefixes=INPUT_PREFIXES)
    if args.stage in ("research", "authoring") and not pairs:
        raise ValueError("Research/authoring checkpoints need at least one actual saved --ref.")
    checkpoint = {
        "stage": args.stage,
        "at": now(),
        "outcome": args.outcome,
        "assignment_sha256": assignment_signature(occurrence),
        "files": {rel: digest(path) for rel, path in pairs},
    }
    work = occurrence.setdefault("work", {"checkpoints": [], "repairs": []})
    work["checkpoints"].append(checkpoint)
    occurrence["stage"] = args.stage
    ledger.save("graphics-checkpoint")
    return {"occurrence": occurrence["occurrence_id"], "checkpoint": checkpoint}


def work_status(root, occurrence):
    from .graphics import INPUT_PREFIXES, _confine_existing

    work = occurrence.get("work") or {}
    checkpoints = []
    for checkpoint in work.get("checkpoints") or []:
        reasons = []
        if checkpoint["assignment_sha256"] != assignment_signature(occurrence):
            reasons.append("changed_assignment")
        if root is not None:
            for rel, expected in checkpoint["files"].items():
                try:
                    if digest(_confine_existing(root, rel, prefixes=INPUT_PREFIXES)) != expected:
                        reasons.append("changed_checkpoint_file:" + rel)
                except (ValueError, OSError):
                    reasons.append("missing_checkpoint_file:" + rel)
        else:
            reasons.append("unchecked_files")
        checkpoints.append({**copy.deepcopy(checkpoint), "intact": not reasons, "reasons": reasons})
    return {
        "stage": occurrence.get("stage", "assigned"),
        "checkpoints": checkpoints,
        "repair_attempts": len(work.get("repairs") or []),
        "repair_limit": REPAIR_LIMIT,
    }


def _live_input_reasons(root, fingerprints):
    from . import graphics as g

    reasons = []
    for rel, spec in fingerprints["inputs"].items():
        try:
            if digest(g._confine_existing(root, rel, prefixes=g.INPUT_PREFIXES)) != spec["sha256"]:
                reasons.append("changed_input:" + rel)
        except (OSError, ValueError):
            reasons.append("missing_input:" + rel)
    return reasons


def _runtime_reasons(runtime, kind):
    from . import graphics as g

    if kind != "remotion":
        return []
    status = g.runtime_status()
    reasons = ["missing_runtime"] if status["missing"] else []
    for key, path in (
        ("package_json_sha256", g.PACKAGE_ROOT / "package.json"),
        ("package_lock_sha256", g.PACKAGE_ROOT / "package-lock.json"),
        ("node_sha256", status.get("node")),
        ("browser_sha256", runtime.get("browser_executable")),
    ):
        if runtime.get(key) != g._file_sha256(path):
            reasons.append("changed_runtime:" + key)
    return reasons


def dependency_reasons(root, version, occurrence, graphics):
    from . import graphics as g

    reasons = []
    if g._assignment_changed(version["assignment"], occurrence):
        reasons.append("changed_assignment")
    fingerprints = version["fingerprints"]
    style = next(item for item in graphics["style_revisions"] if item["revision"] == occurrence["style_revision"])
    if fingerprints["style_sha256"] != g._payload_hash(style):
        reasons.append("changed_style")
    if fingerprints["profile"] != graphics["profile"]:
        reasons.append("changed_profile")
    reasons.extend(_live_input_reasons(root, fingerprints))
    source_paths = g._template_source_paths(occurrence["template"], root, occurrence)
    for name, path in source_paths.items():
        if fingerprints["source"].get(name) != g._file_sha256(path):
            reasons.append("changed_template:" + name)
    worker, kind = g._worker_path()
    runtime = fingerprints["runtime"]
    if kind != runtime["kind"] or digest(worker) != runtime["worker_sha256"]:
        reasons.append("changed_worker")
    if kind == "remotion":
        reasons.extend(_runtime_reasons(runtime, kind))
        fonts, _terms = g._font_sources()
        if fingerprints["fonts"] != {name: digest(path) for name, path in fonts.items()}:
            reasons.append("changed_fonts")
    return reasons


def _recover_render(ledger, version, occurrence):
    from . import graphics as g

    progress = version.get("render_progress") or {}
    if progress.get("phase") != "rendered":
        version["status"] = "failed"
        version["diagnostics"] = {
            "message": "Interrupted before a durable verified render result; partial files retained."
        }
        occurrence["stage"] = "render_failed"
        ledger.save("graphics-continue-interrupted")
        return None
    directory = g._confine_planned(ledger.root, g._version_dir(ledger.root, version["scene_id"], version["id"]))
    reasons = (
        g._verify_declared_paths(directory, version)
        + g._verify_snapshots(directory, version)
        + g._verify_frozen_job(directory, version)
        + g._verify_vo_preview(ledger.root, version)
    )
    staging = g._confine_declared_file(directory, "staging/out.mp4")
    if reasons or digest(staging) != progress["sha256"]:
        raise ValueError(
            "Interrupted render snapshots/result changed; preserve the partial files and repair this scene."
        )
    info = g._verify_complete(
        staging,
        version["profile"],
        version["timing"]["duration_in_frames"],
        expect_audio=g._version_has_effects(version),
    )
    return g._publish_render_result(ledger, version, occurrence, info)


def _resume_staging(ledger, occurrence):
    graphics = ledger.data["graphics"]
    for version in reversed(list(graphics["versions"].values())):
        recoverable = version["status"] == "staging" or (
            version["status"] == "failed" and (version.get("render_progress") or {}).get("phase") == "rendered"
        )
        if version["occurrence_id"] != occurrence["occurrence_id"] or not recoverable:
            continue
        drift = dependency_reasons(ledger.root, version, occurrence, graphics)
        if drift:
            return {
                "occurrence": occurrence["occurrence_id"],
                "action": "waiting",
                "reasons": ["interrupted_inputs_changed", *drift],
            }
        if _recover_render(ledger, version, occurrence):
            return {"occurrence": occurrence["occurrence_id"], "action": "recovered", "version": version["id"]}
    return None


def _continue_one(ledger, occurrence):
    from . import graphics as g

    graphics = ledger.data["graphics"]
    identifier = occurrence["occurrence_id"]
    waiting = []
    if occurrence.get("stage") in ("research", "authoring"):
        checkpoints = work_status(ledger.root, occurrence)["checkpoints"]
        if checkpoints and not checkpoints[-1]["intact"]:
            waiting = checkpoints[-1]["reasons"]
    if occurrence.get("stage") in ("waiting", "error"):
        work = occurrence.get("work") or {}
        latest = (work.get("checkpoints") or [{}])[-1]
        waiting = [latest.get("outcome", "Saved work needs attention.")]
    if waiting:
        return {"occurrence": identifier, "action": "waiting", "reasons": waiting}
    extra, _facts, _alignment, _background = g._facts_audio_reasons(ledger.root, occurrence, data=ledger.data)
    if occurrence.get("questions") or extra:
        return {"occurrence": identifier, "action": "waiting", "reasons": [*occurrence["questions"], *extra]}
    recovery = _resume_staging(ledger, occurrence)
    if recovery:
        return recovery
    current = graphics["versions"].get(occurrence.get("current_version"))
    reasons = []
    if current is not None and current["status"] == "complete":
        intact, reasons = g.verify_version_integrity(ledger.root, current)
        reasons.extend(dependency_reasons(ledger.root, current, occurrence, graphics))
        if intact and not reasons:
            return {"occurrence": identifier, "action": "reused", "version": current["id"]}
    latest = next((v for v in reversed(list(graphics["versions"].values())) if v["occurrence_id"] == identifier), None)
    if (
        latest is not None
        and latest["status"] == "failed"
        and not _repair_meaning_changed(latest["assignment"], occurrence)
    ):
        return {
            "occurrence": identifier,
            "action": "repair_required",
            "version": latest["id"],
            **work_status(ledger.root, occurrence),
        }
    result = g.render_command(ledger, SimpleNamespace(occurrence=identifier, repair=False))
    return {"occurrence": identifier, "action": "rendered", "version": result["version"]["id"], "invalidated": reasons}


def continue_command(ledger, args):
    graphics = ledger.data.get("graphics")
    if not isinstance(graphics, dict):
        raise ValueError("This project has no graphics assignments to continue.")
    identifiers = [args.occurrence] if args.occurrence else list(graphics["occurrences"])
    if any(identifier not in graphics["occurrences"] for identifier in identifiers):
        raise ValueError("Unknown graphics occurrence.")
    outcomes = []
    for identifier in identifiers:
        try:
            outcomes.append(_continue_one(ledger, graphics["occurrences"][identifier]))
        except (ValueError, OSError) as exc:
            outcomes.append({"occurrence": identifier, "action": "error", "message": str(exc)[:4000]})
    return {"items": outcomes, "paid_submissions": 0, "automatic_repairs": 0}
