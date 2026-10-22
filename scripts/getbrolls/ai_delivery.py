"""AI coverage readiness and packages in the existing protected project handoff."""

import json

from .ai_recovery import check_inputs
from .ai_state import beat_for, checked_version, digest, fingerprint, sanitize_public_text, text, version_signature
from .ai_timing import _profile, preview_for_view
from .ledger import Ledger
from .models import now
from .runtime import project_lock

FPS_TOLERANCE = 0.001
PACKAGE_SCHEMA = 2


def record_use(ledger, data):
    version, _path = checked_version(ledger, data.get("version"))
    if version["kind"] not in {"video", "sequence"}:
        raise ValueError("Material-use delivery decisions require an AI video or sequence.")
    if data.get("signature") != version_signature(version) or data.get("state") not in (
        "permitted",
        "blocked",
        "unresolved",
    ):
        raise ValueError("Record material use for the exact displayed version: permitted, blocked or unresolved.")
    record = {
        "version": version["id"],
        "signature": data["signature"],
        "state": data["state"],
        "by": text(data.get("by"), "Responsible editor", 200),
        "conditions": text(data.get("conditions"), "Material-use conditions", 8000),
        "evidence": text(data.get("evidence"), "Material-use evidence", 8000),
        "profile": _profile(ledger),
    }
    records = ledger.data["ai"].setdefault("material_use", {})
    prior = records.get(version["id"])
    accept_profile = data.get("accept_profile")
    if accept_profile is not None and type(accept_profile) is not bool:
        raise ValueError("Accept actual quality explicitly for this exact version, or keep the required profile.")
    if accept_profile is True and data.get("profile_fingerprint") != fingerprint(record["profile"]):
        raise ValueError("The displayed project profile changed; review the current actual and required quality.")
    if accept_profile is not None:
        record["accept_profile"] = accept_profile
    elif prior and prior.get("profile") == record["profile"] and "accept_profile" in prior:
        record["accept_profile"] = prior["accept_profile"]
    if prior and all(prior.get(key) == value for key, value in record.items()):
        return {"material_use": prior}
    record["at"] = now()
    records[version["id"]] = record
    ledger.save("ai-material-use")
    return {"material_use": record}


def handle_use(project, data):
    with project_lock(project):
        return record_use(Ledger(project), data)


def use_command(ledger, args):
    return record_use(
        ledger,
        {
            key: getattr(args, key)
            for key in (
                "version",
                "signature",
                "state",
                "by",
                "conditions",
                "evidence",
                "accept_profile",
                "profile_fingerprint",
            )
        },
    )


def current_version(ledger, beat):
    ai = ledger.data.get("ai") or {}
    if beat.get("sequence"):
        record = (ai.get("sequences") or {}).get(beat["sequence"]) or {}
        # Preparing a plan does not launch it or replace retained single-clip coverage.
        if not record or record.get("launched") is not None or record.get("version"):
            return ai["versions"].get(record.get("version"))
    return next(
        (
            version
            for version in reversed(list(ai.get("versions", {}).values()))
            if version.get("kind") == "video"
            and version.get("beat") == beat["id"]
            and not (ai["jobs"].get(version.get("job"), {}).get("request") or {}).get("sequence")
        ),
        None,
    )


def _profile_shortfall(version, profile):
    return bool(
        not version.get("native_full_hd")
        or version.get("profile_shortfall")
        or version["width"] < profile["width"]
        or version["height"] < profile["height"]
        or abs(version["fps"] - profile["fps"]) > FPS_TOLERANCE
    )


def readiness(ledger, beat):
    from .ai_sequences import _frames

    ai = ledger.data.get("ai") or {}
    version = current_version(ledger, beat)
    reasons = []
    if version is None:
        return {"beat": beat["id"], "version": None, "ready": False, "reasons": ["coverage_missing"]}
    profile = _profile(ledger)
    use = (ai.get("material_use") or {}).get(version["id"]) or {}
    accepted = bool(
        use.get("accept_profile") is True
        and use.get("signature") == version_signature(version)
        and use.get("profile") == profile
    )
    shortfall = False
    try:
        _version, path = checked_version(ledger, version["id"])
        originals = (
            [ai["versions"][clip["version"]] for clip in version["clips"]]
            if version["kind"] == "sequence"
            else [version]
        )
        for source in originals:
            check_inputs(ledger, ai["jobs"][source["job"]])
            _source(ledger, source)
        base = (
            ai["sequences"][version["sequence"]]["scope"]["request"]
            if version["kind"] == "sequence"
            else ai["jobs"][version["job"]]["request"]
        )
        frames = base["interval"]["end_frame"] - base["interval"]["start_frame"]
        count = (
            version.get("frames") if version["kind"] == "sequence" else _frames(path) * profile["fps"] / version["fps"]
        )
        if count + FPS_TOLERANCE < frames or version.get("coverage") != "covered":
            reasons.append("coverage_shortfall")
        shortfall = _profile_shortfall(version, profile)
        if shortfall and not accepted:
            reasons.append("profile_shortfall")
        narration, _error = preview_for_view(ledger, beat.get("timing"), resolved=True)
        if not narration:
            reasons.append("narration_missing")
    except (ValueError, OSError, KeyError):
        reasons.append("media_or_inputs_changed")
    approval = version.get("approval") or {}
    if approval.get("state") != "approved" or approval.get("signature") != version_signature(version):
        reasons.append("approval_required")
    if use.get("state") != "permitted" or use.get("signature") != version_signature(version):
        reasons.append("material_use_blocked" if use.get("state") == "blocked" else "material_use_unresolved")
    if use and use.get("profile") != profile:
        reasons.append("profile_context_changed")
    return {
        "beat": beat["id"],
        "version": version["id"],
        "signature": version_signature(version),
        "kind": version["kind"],
        "ready": not reasons,
        "reasons": reasons,
        "approval": approval.get("state"),
        "material_use": _safe_metadata(use),
        "required_profile": profile,
        "profile_fingerprint": fingerprint(profile),
        "profile_shortfall": shortfall,
        "profile_accepted": accepted,
        "warnings": ["profile_shortfall_accepted"] if shortfall and accepted else [],
        "actual": {key: version.get(key) for key in ("width", "height", "fps", "duration_s", "native_full_hd")},
    }


def plan(ledger):
    return [
        readiness(ledger, beat)
        for beat in (ledger.data.get("ai") or {}).get("beats", {}).values()
        if beat.get("active")
    ]


def progress(ledger):
    from .delivery import graphics_package_intact

    ai = ledger.data.get("ai") or {}
    rows = plan(ledger)
    for row in rows:
        version = ai.get("versions", {}).get(row["version"]) or {}
        record = version.get("delivery") or {}
        same = (
            (
                record.get("version_id") == row["version"]
                and record.get("signature") == row.get("signature")
                and record.get("video_sha256") == version.get("sha256")
                and record.get("package_dir")
                == "entrega/" + _package_rel(version, (ai.get("material_use") or {}).get(row["version"], {}))
                and record.get("path") == record.get("package_dir", "") + "/video.mp4"
                and set(record.get("files") or {})
                == {"video.mp4", "narration.wav", "timing.json", "provenance.json", "ORIGEM.md"}
                | {f"originals/{index + 1:03}.mp4" for index, _clip in enumerate(version.get("clips") or [])}
            )
            if record
            else False
        )
        row["delivery_state"] = (
            "delivered"
            if row["ready"] and same and graphics_package_intact(ledger.root, record)
            else "modified_or_missing"
            if row["ready"] and same
            else "not_delivered"
        )
    return {
        "present": bool(rows),
        "beats": rows,
        "delivered": sum(row["delivery_state"] == "delivered" for row in rows),
        "undelivered": sum(row["ready"] and row["delivery_state"] != "delivered" for row in rows),
        "pending_action": sum(not row["ready"] for row in rows),
        "reasons": sorted({reason for row in rows for reason in row["reasons"]}),
    }


def _package_rel(version, use):
    token = fingerprint({"schema": PACKAGE_SCHEMA, "approval": version.get("approval"), "use": use})[:12]
    return f"ai/{version['beat']}/{version['id']}-{token}"


def _safe_metadata(value):
    if isinstance(value, str):
        return sanitize_public_text(value, limit=32000)
    if isinstance(value, dict):
        return {key: _safe_metadata(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_safe_metadata(item) for item in value]
    return value


def _source(ledger, version):
    job = ledger.data["ai"]["jobs"][version["job"]]
    request = job["request"]
    still, _path = checked_version(ledger, request["still"]["id"], approved=True, kind="image")
    still_job = ledger.data["ai"]["jobs"][still["job"]]
    check_inputs(ledger, still_job)
    lineage, seen = [], set()
    ancestor = still
    while ancestor:
        if ancestor["id"] in seen:
            raise ValueError("Cyclic AI image ancestry; preserve the production records.")
        seen.add(ancestor["id"])
        parent_job = ledger.data["ai"]["jobs"][ancestor["job"]]
        check_inputs(ledger, parent_job)
        parent = parent_job["request"]
        lineage.append(
            {
                "version": ancestor["id"],
                "sha256": ancestor["sha256"],
                "job": parent_job["id"],
                "route": parent.get("route"),
                "model": parent.get("model"),
                **({"session_model": parent["session_model"]} if parent.get("session_model") is not None else {}),
                "prompt": parent.get("prompt"),
                "target": parent.get("target"),
                "instruction": parent.get("instruction"),
                "references": parent.get("references") or [],
                "provider_inputs": (parent_job.get("remote") or {}).get("imageInputs") or [],
            }
        )
        ancestor = checked_version(ledger, parent["target"]["id"], kind="image")[0] if parent.get("target") else None
    return {
        "version": version["id"],
        "sha256": version["sha256"],
        "job": job["id"],
        "route": request["route"],
        "model": request.get("model"),
        "prompt": request.get("prompt"),
        "sound": request.get("sound"),
        "motion": request.get("motion"),
        "correction": request.get("correction"),
        "actual": {
            key: version.get(key) for key in ("width", "height", "fps", "duration_s", "audio", "native_full_hd")
        },
        "provider_inputs": (job.get("remote") or {}).get("imageInputs") or [],
        "still": {
            **request["still"],
            "job": still_job["id"],
            "prompt": still_job["request"].get("prompt"),
            "references": still_job["request"].get("references") or [],
            "lineage": lineage,
        },
    }


def _package(ledger, version):
    from .ai import _probe_clip
    from .narration import _confine_existing_file

    ai = ledger.data["ai"]
    beat = beat_for(ledger, version["beat"])
    _version, video = checked_version(ledger, version["id"])
    copies = [("video.mp4", video)]
    clips = (
        version.get("clips") if version["kind"] == "sequence" else [{"version": version["id"], "trim_start_frame": 0}]
    )
    sources, placements = [], []
    for index, clip in enumerate(clips):
        original, path = checked_version(ledger, clip["version"], kind="video")
        source = _source(ledger, original)
        sources.append(source)
        request = ai["jobs"][original["job"]]["request"]
        name = f"originals/{index + 1:03}.mp4" if version["kind"] == "sequence" else "video.mp4"
        if version["kind"] == "sequence":
            copies.append((name, path))
        placements.append(
            {
                "path": name,
                "version": original["id"],
                "sha256": original["sha256"],
                "placement": request["interval"],
                "trim_start_frame": clip["trim_start_frame"],
                "trim_end_frame": request["interval"]["end_frame"] - request["interval"]["start_frame"],
                "trim_frame_rate": request["profile"]["fps"],
                "source_trim": {
                    "start_s": 0,
                    "end_s": (request["interval"]["end_frame"] - request["interval"]["start_frame"])
                    / request["profile"]["fps"],
                },
                "source_fps": original["fps"],
            }
        )
    base = ai["sequences"][version["sequence"]]["scope"]["request"] if version["kind"] == "sequence" else request
    narration, error = preview_for_view(ledger, beat["timing"], resolved=True)
    if not narration:
        raise ValueError(error or "The separate narration excerpt is missing.")
    vo = _confine_existing_file(ledger.root, narration, ("previews/",))
    copies.append(("narration.wav", vo))
    use = ai["material_use"][version["id"]]
    timing = {
        "schema": PACKAGE_SCHEMA,
        "fps": base["profile"]["fps"],
        "placement": base["interval"],
        "clips": placements,
        "narration": {**base["narration"], "path": "narration.wav", "sha256": digest(vo)},
        "video": "video.mp4",
        "narration_baked_in": False,
    }
    provenance = {
        "schema": PACKAGE_SCHEMA,
        "kind": "ai-generated",
        "beat": beat["id"],
        "passage": beat["text"],
        "version": version["id"],
        "signature": version_signature(version),
        "output": {**_probe_clip(video), "sha256": version["sha256"], "native_full_hd": version["native_full_hd"]},
        "sources": sources,
        "approval": version["approval"],
        "material_use": use,
        "required_profile": _profile(ledger),
        "warnings": ["profile_shortfall_accepted"]
        if use.get("accept_profile") is True and _profile_shortfall(version, _profile(ledger))
        else [],
    }
    generated = {
        "timing.json": json.dumps(_safe_metadata(timing), indent=2, ensure_ascii=False, sort_keys=True) + "\n",
        "provenance.json": json.dumps(_safe_metadata(provenance), indent=2, ensure_ascii=False, sort_keys=True) + "\n",
        "ORIGEM.md": f"# AI coverage: {beat['id']}\n\nGenerated illustration; not documentary evidence.\n\nImport video.mp4 and narration.wav separately. Follow timing.json for recorded placement and source trims. Keep the current project handoff index as the readiness reference. Reference guidance does not grant unrestricted reuse rights. Raw guidance images/videos are not redistributed.\n\nVersion: {version['id']}\nSHA-256: {version['sha256']}\n",
    }
    if provenance["warnings"]:
        actual, profile = provenance["output"], provenance["required_profile"]
        generated["ORIGEM.md"] += (
            f"\nAccepted quality shortfall for this exact version: {actual['width']}x{actual['height']} at "
            f"{actual['fps']} fps; project {profile['width']}x{profile['height']} at {profile['fps']} fps. "
            "Original media is unchanged. This exception does not establish native Full HD.\n"
        )
    return _package_rel(version, use), copies, generated


def deliver(ledger, root, dry_run, expected):
    from .delivery import (
        _ancestor_rels,
        _planned_graphics_hashes,
        _preflight_graphics_package,
        _retained_graphics_rels,
        _write_graphics_copies,
        _write_graphics_generated,
    )

    ai = ledger.data.get("ai") or {}
    expected.update(_retained_graphics_rels(ai, folder="ai"))
    listed, skipped, conflicts, changed = [], [], [], False
    for row in plan(ledger):
        if not row["ready"]:
            skipped.append(row)
            continue
        version = ai["versions"][row["version"]]
        try:
            package_rel, copies, generated = _package(ledger, version)
            package = root / package_rel
            _preflight_graphics_package(ledger.root, root, package, copies, generated)
            if dry_run:
                files = _planned_graphics_hashes(copies, generated)
            else:
                files = {
                    **_write_graphics_copies(package, copies, "video.mp4"),
                    **_write_graphics_generated(package, generated),
                }
            record = {
                "version_id": version["id"],
                "signature": version_signature(version),
                "video_sha256": version["sha256"],
                "package_dir": "entrega/" + package_rel,
                "path": "entrega/" + package_rel + "/video.mp4",
                "files": files,
                "method": "copy",
            }
            expected.update(package_rel + "/" + name for name in files)
            expected.update(_ancestor_rels(package_rel + "/video.mp4"))
            listed.append(
                {
                    "beat": row["beat"],
                    "version": version["id"],
                    **record,
                    "method": "planned" if dry_run else "copy",
                    "warnings": row["warnings"],
                    "actual": row["actual"],
                    "required_profile": row["required_profile"],
                }
            )
            if not dry_run and version.get("delivery") != record:
                version["delivery"] = record
                changed = True
        except (ValueError, OSError, KeyError) as exc:
            skipped.append(
                {**row, "ready": False, "reasons": ["delivery_conflict"], "error": sanitize_public_text(str(exc))}
            )
            conflicts.append(str(exc))
    return listed, skipped, conflicts, changed


def readme_lines(listed, skipped):
    if not listed and not skipped:
        return []
    lines = [
        "",
        "## AI coverage",
        "",
        "Generated illustration is separate from documentary sources and authored graphics. Import scene video and narration separately; use each package's timing.json. Earlier packages remain retained; only entries below are current.",
        "",
    ]
    lines += [
        f"- {row['beat']} / {row['version']}: `{row['package_dir']}`"
        + (" — accepted lower source quality; see provenance.json" if row.get("warnings") else "")
        for row in listed
    ]
    lines += [
        f"- Not delivered: {row['beat']} / {row.get('version') or 'none'}: {', '.join(row['reasons'])}"
        for row in skipped
    ]
    return lines
