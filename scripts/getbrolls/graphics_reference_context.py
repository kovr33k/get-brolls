"""Versioned reference intentions and explicit, fixed multi-scene resolutions.

Transport never interprets prose. The managing agent supplies the effective
instructions and concrete shared targets after the user's chat activation.
"""

from __future__ import annotations

import copy
import json
import re
from pathlib import Path
from types import SimpleNamespace

from . import graphics_references as media

MAX_STATE_BYTES = 512_000
CONTEXT_SCHEMA = 3
CHANGE_FIELDS = ("reference_change", "reference_application", "shared_request_id")


def _g():
    from . import graphics

    return graphics


def fields(record):
    return {key: copy.deepcopy(record[key]) for key in CHANGE_FIELDS if key in record}


def _refs(record):
    refs = copy.deepcopy(media.references(record))
    for index, ref in enumerate(refs, 1):
        ref.setdefault("label", f"R{index}")
    return refs


def _event(prompt, scope, refs, application=None):
    event = {"prompt": prompt, "scope": scope, "bindings": [{"label": r["label"], "sha256": r["sha256"]} for r in refs]}
    if application is not None:
        event["application"] = application
    return event


def active(graphics, occurrence_id):
    """Derive legacy state without writes; stored states take precedence."""
    saved = graphics.get("reference_states", {}).get(occurrence_id)
    if saved:
        return saved["current"], copy.deepcopy(saved["revisions"][saved["current"]])
    occ = graphics["occurrences"][occurrence_id]
    context = occ.get("reference_context") or {}
    source = context
    for req in graphics.get("requests", []):
        if (
            req["occurrence_id"] == occurrence_id
            and req.get("reviewed_version") == occ.get("current_version")
            and media.reference_fields(req)
            and req.get("state") != "stale"
        ):
            source = req
    refs = _refs(source)
    history = copy.deepcopy(context.get("instruction_history", []))
    prompt = source.get("text", source.get("prompt"))
    if prompt and not history:
        history = [_event(prompt, source.get("scope", "scene"), refs)]
    state = {"revision": 0, "references": refs, "instructions": history}
    return _g()._payload_hash(state), state


def summary(graphics, occurrence_id):
    sha, state = active(graphics, occurrence_id)
    return {
        "sha256": sha,
        "revision": state["revision"],
        "references": state["references"],
        "instruction_count": len(state["instructions"]),
        "instructions": state["instructions"],
    }


def _advance(base, refs, prompt, scope, application=None):
    state = {
        "revision": base["revision"] + 1,
        "references": refs,
        "instructions": [*copy.deepcopy(base["instructions"]), _event(prompt, scope, refs, application)],
    }
    if len(json.dumps(state, ensure_ascii=False).encode()) > MAX_STATE_BYTES:
        raise ValueError("Reference instruction history exceeds 512 KB; preserve it and split the work explicitly.")
    return _g()._payload_hash(state), state


def prepare(graphics, project_id, row):
    """Build a canonical request from a known immutable base, without mutation."""
    g = _g()
    if row.get("project") != project_id or not g._sha256(row.get("referenceBase")):
        raise ValueError("Regenerate Storyboard: this reference edit has no valid project/context base.")
    if (
        row.get("state") != "changes"
        or not g._bounded_prose(row.get("comment"))
        or row.get("scope", "scene") not in ("scene", "shared")
    ):
        raise ValueError("Describe this change in a nonblank prompt and confirm its scope.")
    oid = row.get("occurrence_id")
    if not isinstance(oid, str) or oid not in graphics["occurrences"]:
        raise ValueError("The reference target no longer exists.")
    current_sha, current = active(graphics, oid)
    base_sha = row["referenceBase"]
    base = graphics.get("reference_states", {}).get(oid, {}).get("revisions", {}).get(base_sha)
    if base_sha == current_sha:
        base = current
    if base is None:
        raise ValueError("Unknown reference base. Reopen the actual scene; the draft was not retargeted.")
    refs = _refs(row) if media.reference_fields(row) else copy.deepcopy(base["references"])
    application = row.get("reference_application")
    if application is not None and not g._bounded_prose(application):
        raise ValueError("A shared target needs its actual application, including exceptions.")
    result_sha, result = _advance(base, refs, row["comment"].strip(), row.get("scope", "scene"), application)
    payload = {
        "project_id": project_id,
        "scene_id": row.get("scene_id"),
        "occurrence_id": oid,
        "reviewed_version": row.get("version"),
        "content_sha256": row.get("signature"),
        "text": row["comment"].strip(),
        "scope": row.get("scope", "scene"),
        "references": refs,
        "reference_change": {"base": base_sha, "result": result_sha},
    }
    if row.get("initial") is True:
        payload["kind"] = "authoring"
    for key in ("reference_application", "shared_request_id"):
        if key in row:
            payload[key] = copy.deepcopy(row[key])
    return payload, base, result, current_sha


def check_row(ledger, row, *, replay=False):
    graphics = ledger.data.get("graphics") or {}
    payload, base, result, current = prepare(graphics, ledger.data["project_id"], row)
    existing = _g()._lookup_request(graphics, _g().derive_request_id(payload))
    if replay and existing and _g()._request_identity(existing) == payload:
        media.checked_references(ledger.root, payload)
        return payload, base, result, True
    if current != payload["reference_change"]["base"]:
        raise ValueError(
            "Active references changed since this draft. Reopen the scene and reconcile the prompt; nothing was overwritten."
        )
    media.target(ledger, row)
    media.checked_references(ledger.root, payload)
    return payload, base, result, False


def import_row(ctx, row):
    g = _g()
    target = None if row.get("initial") else g._resolve_graphics_row(ctx, row)
    ident = g._graphics_row_id(ctx, row) if row.get("initial") else target["ident"] if target else None
    if ident is None:
        return
    try:
        ledger = SimpleNamespace(data={"graphics": ctx["working"], "project_id": ctx["project_id"]}, root=ctx["root"])
        payload, base, result, replay = check_row(ledger, row, replay=True)
        if replay:
            ctx["unchanged"].append({"id": ident, "reason": "existing_request"})
            return
        if row.get("initial"):
            ctx["working"].setdefault("requests", []).append(
                {**payload, "id": g.derive_request_id(payload), "state": "saved", "processing": None}
            )
            ctx["applied"].append(ident)
        else:
            if target is None or not g._graphics_row_fresh(ctx, target):
                return
            target["row"] = {**row, "reference": None, "references": payload["references"], **fields(payload)}
            g._apply_graphics_changes(ctx, target)
        change = payload["reference_change"]
        stored = (
            ctx["working"].setdefault("reference_states", {}).setdefault(payload["occurrence_id"], {"revisions": {}})
        )
        stored["revisions"].update({change["base"]: copy.deepcopy(base), change["result"]: result})
        stored["current"] = change["result"]
    except (ValueError, OSError, KeyError) as exc:
        g._skip_row(ctx["skipped"], ident, "invalid_reference", str(exc))


def stale(req, graphics):
    change = req.get("reference_change")
    if change and active(graphics, req["occurrence_id"])[0] != change["result"]:
        return "reference_context_mismatch"
    if not change and req.get("id") and req.get("occurrence_id") in graphics.get("reference_states", {}):
        return "reference_context_unbound"
    return None


def decorate(graphics, rows):
    groups = scope_status(graphics)
    for row in rows:
        row["activeReferences"] = summary(graphics, row["occurrence_id"])
        version = graphics.get("versions", {}).get(row.get("version"), {})
        frozen = version.get("assignment", {}).get("reference_context") or {}
        row["frozenReferences"] = _refs(frozen)
        row["frozenReferenceInstructions"] = copy.deepcopy(frozen.get("instruction_history", [])) or (
            [_event(frozen["prompt"], "scene", _refs(frozen))] if frozen.get("prompt") else []
        )
        row["referenceScopes"] = [
            group
            for group in groups
            if group["source_occurrence_id"] == row["occurrence_id"]
            or any(t["occurrence_id"] == row["occurrence_id"] for t in group["targets"])
        ]


def _validate_event(event):
    g = _g()
    if (
        not isinstance(event, dict)
        or set(event) - {"prompt", "scope", "bindings", "application"}
        or not g._bounded_prose(event.get("prompt"))
        or event.get("scope") not in ("scene", "shared")
        or not isinstance(event.get("bindings"), list)
    ):
        raise ValueError("Invalid original reference instruction.")
    if "application" in event and not g._bounded_prose(event["application"]):
        raise ValueError("Invalid shared application.")
    if len(event["bindings"]) > media.MAX_FILES or len(
        {binding.get("label") for binding in event["bindings"] if isinstance(binding, dict)}
    ) != len(event["bindings"]):
        raise ValueError("Historical instruction bindings must have unique bounded labels.")
    for binding in event["bindings"]:
        if (
            not isinstance(binding, dict)
            or set(binding) != {"label", "sha256"}
            or not isinstance(binding.get("label"), str)
            or not re.fullmatch(r"R[1-8]", binding["label"])
            or not g._sha256(binding.get("sha256"))
        ):
            raise ValueError("Invalid historical instruction binding.")


def _validate_state(sha, state):
    if (
        not isinstance(state, dict)
        or _g()._payload_hash(state) != sha
        or set(state) != {"revision", "references", "instructions"}
        or type(state["revision"]) is not int
        or state["revision"] < 0
    ):
        raise ValueError("Reference-state fingerprint changed.")
    media.references({"references": state["references"], "reference_change": {}})
    if (
        not isinstance(state["instructions"], list)
        or len(json.dumps(state, ensure_ascii=False).encode()) > MAX_STATE_BYTES
    ):
        raise ValueError("Invalid reference instruction history.")
    for event in state["instructions"]:
        _validate_event(event)


def _validate_change(req, states):
    g = _g()
    change = req["reference_change"]
    if "references" not in req or "reference" in req:
        raise ValueError(
            "An active change requires its canonical effective references, including an explicit empty set."
        )
    if (
        not isinstance(change, dict)
        or set(change) != {"base", "result"}
        or not all(g._sha256(value) for value in change.values())
    ):
        raise ValueError("Invalid reference change.")
    if req["id"] != g.derive_request_id(g._request_identity(req)):
        raise ValueError("Reference request identity changed.")
    revisions = states.get(req["occurrence_id"], {}).get("revisions", {})
    if change["base"] not in revisions or change["result"] not in revisions:
        raise ValueError("Missing request reference state.")
    sha, expected = _advance(
        revisions[change["base"]], _refs(req), req["text"], req["scope"], req.get("reference_application")
    )
    if sha != change["result"] or expected != revisions[sha]:
        raise ValueError("Request effective references changed.")


def validate(graphics):
    states = graphics.get("reference_states", {})
    if not isinstance(states, dict):
        raise ValueError("Invalid active reference states.")
    for oid, stored in states.items():
        if (
            oid not in graphics["occurrences"]
            or not isinstance(stored, dict)
            or set(stored) != {"current", "revisions"}
        ):
            raise ValueError("Invalid reference-state owner.")
        revisions = stored["revisions"]
        if not isinstance(revisions, dict) or stored["current"] not in revisions:
            raise ValueError("Missing active reference revision.")
        for sha, state in revisions.items():
            _validate_state(sha, state)
    for req in graphics.get("requests", []):
        if req.get("reference_change") is not None:
            _validate_change(req, states)
        if "shared_request_id" in req or "reference_application" in req:
            group = graphics.get("reference_scopes", {}).get(req.get("shared_request_id"), {})
            if not _g()._bounded_prose(req.get("reference_application")) or not any(
                target.get("request_id") == req["id"] for target in group.get("targets", [])
            ):
                raise ValueError("A shared child must belong to its fixed resolved scope.")
    _validate_scopes(graphics)


def validate_context(context):
    g = _g()
    keys = {
        "schema_version",
        "request_id",
        "prompt",
        "references",
        "analyses",
        "active_state_sha256",
        "active_revision",
        "instruction_history",
        "effective_instructions",
    }
    if "composition" in context:
        keys.add("composition")
    if "shared_scope" in context:
        keys.add("shared_scope")
    if (
        set(context) != keys
        or not g._sha256(context.get("active_state_sha256"))
        or not g._bounded_prose(context.get("effective_instructions"))
    ):
        raise ValueError("Record the actual resolution of earlier instructions and this prompt.")
    history = context.get("instruction_history")
    if not isinstance(history, list) or not history or history[-1].get("prompt") != context.get("prompt"):
        raise ValueError("Preserve the original instruction history.")
    _validate_state(
        context["active_state_sha256"],
        {"revision": context["active_revision"], "references": context["references"], "instructions": history},
    )
    if not isinstance(context.get("analyses"), list):
        raise ValueError("Supply an ordered analysis list.")
    # Validate each actual analysis against its original request, never rebind a
    # temporal record to a new text-only request or a reused display label.
    for ref, analysis in zip(media.references(context), context.get("analyses", []), strict=True):
        if not isinstance(analysis, dict):
            raise ValueError("Invalid effective reference analysis.")
        item = copy.deepcopy(analysis)
        basis = item.pop("basis", None)
        if not isinstance(basis, dict) or set(basis) != {"request_id", "prompt"}:
            raise ValueError("An inherited analysis needs its original request and prompt.")
        check = {"schema_version": 2, **basis, "references": [ref], "analyses": [item]}
        media._validate_plural_context(check)
    if not g._valid_id(context.get("request_id")) or not g._bounded_prose(context.get("prompt")):
        raise ValueError("Invalid reference request context.")
    _validate_context_bindings(context, history)


def _validate_context_bindings(context, history):
    g = _g()
    if "composition" in context:
        composition = context["composition"]
        if (
            not isinstance(composition, dict)
            or set(composition) != {"label", "instruction", "background"}
            or not isinstance(composition["background"], dict)
            or not g._bounded_prose(composition.get("instruction"))
            or not any(composition.get("instruction") in event["prompt"] for event in history)
        ):
            raise ValueError("Composition must retain its explicit original instruction and registered background.")
    if "shared_scope" in context:
        scope = context["shared_scope"]
        if (
            not isinstance(scope, dict)
            or set(scope) != {"request_id", "resolution_sha256", "application"}
            or not g._valid_id(scope.get("request_id"))
            or not g._sha256(scope.get("resolution_sha256"))
            or not g._bounded_prose(scope.get("application"))
        ):
            raise ValueError("Invalid frozen shared instruction application.")


def _analysis_payload(req, args):
    payload = {
        "effective_instructions": args.analysis,
        "analyses": [{"label": r["label"], "reuse": True} for r in req["references"]],
    }
    if getattr(args, "file", None):
        path = Path(args.file)
        if path.stat().st_size > media.MAX_REVIEW_BYTES:
            raise ValueError("Analysis file exceeds 2 MB.")
        payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict) or set(payload) - {"analyses", "effective_instructions", "composition"}:
        raise ValueError("Supply effective_instructions, analyses and optional explicit composition.")
    analyses = payload.get("analyses")
    if not isinstance(analyses, list) or len(analyses) != len(req["references"]):
        raise ValueError("Account for every effective reference, including unchanged ones.")
    return payload


def _effective_analyses(root, req, previous, analyses):
    from .graphics_reference_video import checked_inspection

    old_refs = _refs(previous)
    old_analyses = previous.get("analyses", [])
    if previous.get("reference"):
        old_analyses = [
            {"label": "R1", "analysis": previous["analysis"], "limitations": "Legacy still-image inspection."}
        ]
    results = []
    for ref, item in zip(req["references"], analyses, strict=True):
        if not isinstance(item, dict) or item.get("label") != ref["label"]:
            raise ValueError("Preserve effective reference order and labels.")
        if item.get("reuse") is True:
            if set(item) != {"label", "reuse"}:
                raise ValueError("Reuse accepts only label and reuse:true.")
            old = next(
                (
                    a
                    for r, a in zip(old_refs, old_analyses, strict=True)
                    if r["sha256"] == ref["sha256"] and r["label"] == ref["label"]
                ),
                None,
            )
            if old is None:
                raise ValueError(
                    "Inspect and analyse new/replaced references before applying; no intact earlier analysis exists."
                )
            result = copy.deepcopy(old)
            result.setdefault("basis", {"request_id": previous["request_id"], "prompt": previous["prompt"]})
        else:
            result = copy.deepcopy(item)
            result["basis"] = {"request_id": req["id"], "prompt": req["text"]}
            if "inspection" in result:
                result["inspection"] = checked_inspection(root, result["inspection"])
        results.append(result)
    return results


def apply_command(ledger, args):
    g = _g()
    graphics = ledger.data["graphics"]
    req = g._find_request(graphics, args.request)
    if req.get("state") == "processed" or g._request_stale_reason(req, graphics):
        raise ValueError("Select the actual unprocessed reference request; no retargeting occurred.")
    if req["scope"] == "shared" and req["id"] not in graphics.get("reference_scopes", {}):
        raise ValueError("Resolve the concrete shared targets with graphics-reference-scope before processing.")
    media.checked_references(ledger.root, req)
    occ = graphics["occurrences"][req["occurrence_id"]]
    previous = occ.get("reference_context") or {}
    if previous:
        media.checked_context(ledger.root, previous, occ)
    payload = _analysis_payload(req, args)
    results = _effective_analyses(ledger.root, req, previous, payload["analyses"])
    state = graphics["reference_states"][req["occurrence_id"]]["revisions"][req["reference_change"]["result"]]
    context = {
        "schema_version": CONTEXT_SCHEMA,
        "request_id": req["id"],
        "prompt": req["text"],
        "references": copy.deepcopy(req["references"]),
        "analyses": results,
        "active_state_sha256": req["reference_change"]["result"],
        "active_revision": state["revision"],
        "instruction_history": copy.deepcopy(state["instructions"]),
        "effective_instructions": payload.get("effective_instructions"),
    }
    shared_id = req.get("shared_request_id") or (req["id"] if req["scope"] == "shared" else None)
    if shared_id:
        group = graphics["reference_scopes"][shared_id]
        target = next(t for t in group["targets"] if t["request_id"] == req["id"])
        context["shared_scope"] = {
            "request_id": shared_id,
            "resolution_sha256": group["resolution_sha256"],
            "application": target["instruction"],
        }
    if "composition" in payload and payload["composition"] is not None:
        context["composition"] = media._composition(ledger, req, occ, payload["composition"], results)
    elif "composition" not in payload and previous.get("composition"):
        context["composition"] = copy.deepcopy(previous["composition"])
    validate_context(context)
    if occ.get("reference_context") == context:
        return {"reference_context": context, "idempotent": True, "render_started": False}
    occ["reference_context"] = context
    if context.get("composition"):
        occ["background"] = copy.deepcopy(context["composition"]["background"])
    ledger.save("graphics-reference-apply")
    return {"reference_context": context, "idempotent": False, "render_started": False}


def _target_row(ledger, graphics, oid):
    occ = graphics["occurrences"].get(oid)
    if not isinstance(occ, dict):
        raise ValueError("A shared target is not a registered occurrence.")
    row = {
        "project": ledger.data["project_id"],
        "scene_id": occ["scene_id"],
        "occurrence_id": oid,
        "state": "changes",
        "scope": "scene",
        "referenceBase": active(graphics, oid)[0],
    }
    vid = occ.get("current_version")
    if vid:
        version = graphics["versions"][vid]
        row.update(
            id=f"graphics:{oid}:{vid}",
            version=vid,
            signature=_g().graphics_content_sha256(version),
            reviewEpoch=_g().graphics_review_epoch(version),
        )
    else:
        sha = media.assignment_signature(occ)
        row.update(id=f"graphics:{oid}:initial", initial=True, version=None, signature=sha, reviewEpoch=sha)
    return row


def scope_command(ledger, args):  # noqa: C901, PLR0912 - one atomic fixed-scope write with explicit refusal and replay boundaries.
    """Record concrete targets once. Never expand a natural-language 'all'."""
    g = _g()
    path = Path(args.file)
    if path.stat().st_size > media.MAX_REVIEW_BYTES:
        raise ValueError("Shared resolution file exceeds 2 MB.")
    spec = json.loads(path.read_text(encoding="utf-8"))
    if (
        not isinstance(spec, dict)
        or set(spec) != {"resolution", "targets"}
        or not g._bounded_prose(spec.get("resolution"))
        or not isinstance(spec.get("targets"), list)
        or not spec["targets"]
    ):
        raise ValueError(
            "Resolve ambiguous scope in chat; supply resolution and concrete targets with references and instruction."
        )
    graphics = ledger.data["graphics"]
    req = g._find_request(graphics, args.request)
    if req.get("scope") != "shared" or not req.get("reference_change"):
        raise ValueError("Select a saved context-aware shared request.")
    existing = graphics.get("reference_scopes", {}).get(req["id"])
    if existing:
        if existing["resolution_sha256"] != g._payload_hash(spec):
            raise ValueError("This shared scope is already fixed. Create a new request for a different scope.")
        return {
            "scope": next(s for s in scope_status(graphics) if s["request_id"] == req["id"]),
            "idempotent": True,
            "render_started": False,
        }
    if req.get("state") == "processed" or g._request_stale_reason(req, graphics):
        raise ValueError("Resolve the actual unprocessed shared request.")
    working = copy.deepcopy(graphics)
    ctx = g._import_ctx(working, ledger.data["project_id"], ledger.root, "Shared prompt resolution")
    targets, seen = [], set()
    for item in spec["targets"]:
        if (
            not isinstance(item, dict)
            or set(item) != {"occurrence_id", "references", "instruction"}
            or not isinstance(item["occurrence_id"], str)
            or item["occurrence_id"] in seen
            or not g._bounded_prose(item["instruction"])
        ):
            raise ValueError(
                "Shared targets must be unique concrete occurrences with their effective references and actual instruction/exceptions."
            )
        oid = item["occurrence_id"]
        seen.add(oid)
        row = _target_row(ledger, working, oid)
        row.update(
            references=item["references"],
            comment=req["text"],
            reference_application=item["instruction"],
            shared_request_id=req["id"],
        )
        media.checked_references(ledger.root, row)
        media.target(SimpleNamespace(data={"graphics": working, "project_id": ledger.data["project_id"]}), row)
        if oid == req["occurrence_id"]:
            if item["references"] != req["references"]:
                raise ValueError(
                    "Source target references must match its saved request. Resolve a different source set with a new request."
                )
            child_id = req["id"]
        else:
            payload, _, _, _ = prepare(working, ledger.data["project_id"], row)
            child_id = g.derive_request_id(payload)
            import_row(ctx, row)
            if ctx["skipped"] or not g._lookup_request(working, child_id):
                raise ValueError(
                    "A shared target conflicts with its saved assignment/context; no targets were committed."
                )
        targets.append(
            {
                "occurrence_id": oid,
                "request_id": child_id,
                "instruction": item["instruction"],
                "reviewed_version": row["version"],
                "content_sha256": row["signature"],
                "base": row["referenceBase"],
            }
        )
    if req["occurrence_id"] not in seen:
        raise ValueError("Include the source occurrence explicitly in the concrete shared target list.")
    working.setdefault("reference_scopes", {})[req["id"]] = {
        "resolution": spec["resolution"],
        "resolution_sha256": g._payload_hash(spec),
        "targets": targets,
    }
    validate(working)
    ledger.data["graphics"] = working
    ledger.save("graphics-reference-scope")
    return {
        "scope": next(s for s in scope_status(working) if s["request_id"] == req["id"]),
        "idempotent": False,
        "render_started": False,
    }


def _validate_scopes(graphics):
    scopes = graphics.get("reference_scopes", {})
    if not isinstance(scopes, dict):
        raise ValueError("Invalid shared reference scopes.")
    for rid, group in scopes.items():
        req = _g()._lookup_request(graphics, rid)
        if (
            not req
            or req["scope"] != "shared"
            or not isinstance(group, dict)
            or set(group) != {"resolution", "resolution_sha256", "targets"}
            or not _g()._bounded_prose(group["resolution"])
            or not _g()._sha256(group["resolution_sha256"])
            or not isinstance(group["targets"], list)
            or not group["targets"]
        ):
            raise ValueError("Invalid fixed shared scope.")
        seen = set()
        spec = {"resolution": group["resolution"], "targets": []}
        for item in group["targets"]:
            if not isinstance(item, dict) or set(item) != {
                "occurrence_id",
                "request_id",
                "instruction",
                "reviewed_version",
                "content_sha256",
                "base",
            }:
                raise ValueError("Invalid shared target snapshot.")
            child = _g()._lookup_request(graphics, item.get("request_id"))
            if (
                not child
                or child["occurrence_id"] != item.get("occurrence_id")
                or item["occurrence_id"] in seen
                or child["reviewed_version"] != item.get("reviewed_version")
                or child["content_sha256"] != item.get("content_sha256")
                or not _g()._bounded_prose(item.get("instruction"))
                or not _g()._sha256(item.get("base"))
            ):
                raise ValueError("Shared target identity changed.")
            expected_base = child["reference_change"]["result" if child["id"] == rid else "base"]
            if item["base"] != expected_base or (
                child["id"] != rid
                and (child.get("shared_request_id") != rid or child.get("reference_application") != item["instruction"])
            ):
                raise ValueError("Shared target context/application changed.")
            spec["targets"].append(
                {
                    "occurrence_id": item["occurrence_id"],
                    "references": child["references"],
                    "instruction": item["instruction"],
                }
            )
            seen.add(item["occurrence_id"])
        if req["occurrence_id"] not in seen:
            raise ValueError("Shared source target is missing.")
        if _g()._payload_hash(spec) != group["resolution_sha256"]:
            raise ValueError("Fixed shared resolution fingerprint changed.")


def scope_status(graphics):
    rows = []
    for req in graphics.get("requests", []):
        if req.get("scope") != "shared" or not req.get("reference_change"):
            continue
        group = graphics.get("reference_scopes", {}).get(req["id"])
        targets = []
        for target in (group or {}).get("targets", []):
            child = _g()._lookup_request(graphics, target["request_id"]) or {}
            state, reason = _g()._request_effective_state(child, graphics)
            occ = graphics.get("occurrences", {}).get(target["occurrence_id"], {})
            targets.append(
                {
                    **target,
                    "title": (occ.get("props") or {}).get("label") or target["occurrence_id"],
                    "state": state,
                    "reason": reason,
                    "processing": child.get("processing"),
                }
            )
        state = (
            "unresolved"
            if group is None
            else "complete"
            if all(t["state"] == "processed" for t in targets)
            else "conflict"
            if any(t["state"] == "stale" for t in targets)
            else "incomplete"
        )
        rows.append(
            {
                "request_id": req["id"],
                "source_occurrence_id": req["occurrence_id"],
                "state": state,
                "resolution": (group or {}).get("resolution"),
                "targets": targets,
            }
        )
    return rows
