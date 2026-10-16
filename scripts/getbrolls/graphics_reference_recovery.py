"""Read-only reference evidence and explicit continuation of fixed requests."""

from __future__ import annotations

from . import graphics_references as media
from .ledger import digest


def _g():
    from . import graphics

    return graphics


def _availability(root, request, context, cache):
    """Check known bytes and temporal records, without probing/decoding media."""
    from .graphics_reference_video import checked_inspection

    files, issues = [], []
    for ref in media.references(request):
        key = (ref["ref"], ref["sha256"], ref["bytes"])
        if key not in cache:
            try:
                path = _g()._confine_existing(root, ref["ref"], prefixes=("graphics-data/",))
                cache[key] = (
                    "available" if path.stat().st_size == ref["bytes"] and digest(path) == ref["sha256"] else "changed"
                )
            except (ValueError, OSError):
                cache[key] = "missing_or_unsafe"
        state = cache[key]
        label = ref.get("label", "R1")
        files.append({"label": label, "sha256": ref["sha256"], "state": state})
        if state != "available":
            issues.append("reference_" + state + ":" + label)
    for analysis in context.get("analyses", []):
        record = analysis.get("inspection")
        if record:
            try:
                if checked_inspection(root, record["record_ref"]) != record:
                    raise ValueError("Changed temporal record.")
            except (ValueError, OSError):
                issues.append("temporal_evidence_changed_or_missing:" + analysis["label"])
    return files, issues


def _result(graphics, request):
    g = _g()
    vid = (request.get("processing") or {}).get("resulting_version")
    candidates = [vid] if vid else reversed(list(graphics["versions"]))
    for candidate in candidates:
        try:
            return g._complete_result_version(graphics, request, candidate)
        except ValueError:
            continue
    return None


def request_work(root, graphics, request, *, cache=None):
    """Observe committed work only. This is also safe while a writer holds its lock."""
    g = _g()
    occ = graphics["occurrences"][request["occurrence_id"]]
    result = _result(graphics, request)
    assignment = result["assignment"] if result else occ
    context = assignment.get("reference_context") or {}
    applied = media.context_matches(request, assignment)
    issues, files = [], []
    if root is not None:
        files, issues = _availability(root, request, context if applied else {}, {} if cache is None else cache)
        if result:
            intact, reasons = g.verify_version_integrity(root, result)
            if not intact:
                issues.extend(reasons)
    reason = g._request_stale_reason(request, graphics) if not result else None
    unresolved = request["scope"] == "shared" and request["id"] not in graphics.get("reference_scopes", {})
    # Evidence failure takes precedence over recorded completion. No state is
    # mutated merely to report that the saved result now needs attention.
    state = next(
        name
        for condition, name in (
            (issues, "blocked"),
            (root is None, "unchecked"),
            (request["state"] == "processed", "processed"),
            (result is not None, "result_ready"),
            (reason, "stale"),
            (unresolved, "scope_unresolved"),
            (applied, "ready_to_continue"),
            (True, "analysis_required"),
        )
        if condition
    )
    return {
        "request_id": request["id"],
        "occurrence_id": request["occurrence_id"],
        "state": state,
        "files": files,
        "issues": issues,
        "reason": reason,
        "resulting_version": result["id"] if result else None,
        "processing": request.get("processing"),
        "render_started": False,
    }


def work_status(root, graphics):
    cache = {}
    return [
        request_work(root, graphics, request, cache=cache)
        for request in graphics.get("requests", [])
        if media.reference_fields(request)
    ]


def _continue_request(ledger, request):
    from .graphics_continuation import _continue_one

    graphics = ledger.data["graphics"]
    work = request_work(ledger.root, graphics, request)
    if work["state"] in ("processed", "result_ready"):
        return {
            **work,
            "action": "reused",
            "version": work["resulting_version"],
            "completion_required": work["state"] != "processed",
        }
    if work["state"] != "ready_to_continue":
        return {**work, "action": "waiting"}
    occ = graphics["occurrences"][request["occurrence_id"]]
    # Explicit production may re-probe; read-only status above never does.
    media.checked_context(ledger.root, occ["reference_context"], occ)
    return {**_continue_one(ledger, occ), "request_id": request["id"], "completion_required": True}


def continue_command(ledger, args):
    from .graphics_reference_context import scope_status

    graphics = ledger.data.get("graphics") or {}
    req = _g()._find_request(graphics, args.request)
    if not media.reference_fields(req):
        raise ValueError("Select a saved reference request for request-bound continuation.")
    if req["scope"] == "shared":
        group = graphics.get("reference_scopes", {}).get(req["id"])
        if group is None:
            return {
                "items": [{**request_work(ledger.root, graphics, req), "action": "waiting"}],
                "paid_submissions": 0,
                "automatic_repairs": 0,
            }
        requests = [_g()._find_request(graphics, item["request_id"]) for item in group["targets"]]
    else:
        requests = [req]
    outcomes = []
    for request in requests:
        try:
            outcomes.append(_continue_request(ledger, request))
        except (ValueError, OSError) as exc:
            outcomes.append(
                {
                    "request_id": request["id"],
                    "occurrence": request["occurrence_id"],
                    "action": "waiting",
                    "message": str(exc)[:4000],
                }
            )
    return {
        "items": outcomes,
        "reference_scopes": scope_status(graphics, work=work_status(ledger.root, graphics)),
        "paid_submissions": 0,
        "automatic_repairs": 0,
    }
