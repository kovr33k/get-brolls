"""One-catalog fragment plans and durable query accounting in the existing ledger."""

import copy
import hashlib
import json

from . import providers
from .brief import QUERY_MAX_TOKENS, load_brief, search_query, validate_brief
from .models import now
from .rules import allowed, format_report
from .runtime import redact

QUERY_ALLOWANCE = 3
MAX_RESULTS = 50
MAX_QUERY_CHARS = 500


def validate_plans(data):
    plans = data.get("search_plans", {})
    if not isinstance(plans, dict):
        raise ValueError("Invalid search plans; preserve the project state.")
    for shot, plan in plans.items():
        if (
            not isinstance(shot, str)
            or not isinstance(plan, dict)
            or type(plan.get("pass")) is not int
            or plan.get("pass") != 1
            or not all(
                isinstance(plan.get(k), str) and plan[k]
                for k in ("catalog", "reason", "expected_material", "context_hash")
            )
            or not isinstance(plan.get("context"), dict)
            or not isinstance(plan.get("attempts"), list)
            or len(plan["attempts"]) > QUERY_ALLOWANCE
        ):
            raise ValueError("Invalid search plan; preserve the project state.")
        seen = set()
        for attempt in plan["attempts"]:
            if (
                not isinstance(attempt, dict)
                or not isinstance(attempt.get("query_key"), str)
                or attempt["query_key"] in seen
                or not isinstance(attempt.get("query"), str)
                or attempt.get("status") not in ("dispatched", "results", "empty", "access_or_provider_error")
                or not isinstance(attempt.get("candidates"), list)
                or any(not isinstance(c, str) for c in attempt["candidates"])
            ):
                raise ValueError("Invalid search attempt; preserve the project state.")
            seen.add(attempt["query_key"])


def _fragment(project, shot, rules):
    brief, conflicts = validate_brief(load_brief(project), rules)
    if conflicts:
        raise ValueError("Resolve brief conflicts before planned search: " + "; ".join(conflicts))
    beat = next((b["resolved"] for b in brief["beats"] if b["id"] == shot), None)
    if beat is None:
        raise ValueError("--shot must identify an existing BRIEF search fragment.")
    if beat.get("blocked_reason"):
        raise ValueError("Search fragment is blocked: " + beat["blocked_reason"])
    context = {
        k: beat.get(k)
        for k in ("narration", "target", "intent", "allowed_sources", "stock", "notes", "asset_type", "duration_hint_s")
    }
    fingerprint = hashlib.sha256(json.dumps(context, sort_keys=True).encode()).hexdigest()
    return beat, context, fingerprint


def progress(data, recovery_pending=False):
    result = []
    for shot, plan in data.get("search_plans", {}).items():
        attempts = copy.deepcopy(plan["attempts"])
        for attempt in attempts:
            if attempt["status"] == "dispatched":
                attempt["status"] = "interrupted_or_uncertain"
        used = len(attempts)
        result.append(
            {
                "fragment": shot,
                "pass": plan["pass"],
                "catalog": plan["catalog"],
                "reason": plan["reason"],
                "expected_material": plan["expected_material"],
                "context": plan["context"],
                "queries_used": None if recovery_pending else used,
                "queries_remaining": None if recovery_pending else max(0, QUERY_ALLOWANCE - used),
                "recovery_pending": recovery_pending,
                "attempts": attempts,
                "target_reached": False,
                "suitable_options": [],
                "next": "recover_pending_write"
                if recovery_pending
                else "assess_results_or_finish_single_catalog"
                if used >= QUERY_ALLOWANCE
                else "assess_results_or_query",
                "note": "Pending journal may contain a consumed dispatch; recover it before determining the allowance."
                if recovery_pending
                else "Raw hits and generated previews do not establish suitable options. Visual confirmation is pending the next slice.",
            }
        )
    return result


def plan_command(ledger, args, rules):
    beat, context, fingerprint = _fragment(args.project, args.shot, rules)
    capability = providers.capabilities().get(args.provider, {})
    if args.provider not in beat["allowed_sources"] or not capability.get("search"):
        raise ValueError("Selected catalog must have supported discovery and be allowed for this fragment.")
    if not set(capability["media_types"]) & set(rules["asset_types"]):
        raise ValueError("Selected catalog is incompatible with project media policy.")
    for name in ("reason", "expected_material"):
        if not isinstance(getattr(args, name), str) or not getattr(args, name).strip():
            raise ValueError(f"--{name.replace('_', '-')} must explain the catalog plan.")
    current = ledger.data.get("search_plans", {}).get(args.shot)
    proposed = {
        "pass": 1,
        "catalog": args.provider,
        "reason": args.reason.strip(),
        "expected_material": args.expected_material.strip(),
        "context": context,
        "context_hash": fingerprint,
        "attempts": [],
    }
    if current and any(current[k] != proposed[k] for k in proposed if k != "attempts"):
        raise ValueError(
            "This fragment already has a plan. Reusing its state cannot reset the query budget or context."
        )
    if not current and not args.dry_run:
        ledger.data.setdefault("search_plans", {})[args.shot] = proposed
        ledger.save("search-plan")
    data = {"search_plans": {args.shot: current or proposed}}
    return {
        "search_progress": progress(data),
        "dry_run": args.dry_run,
        "summary": {
            "line": "Validated the fragment plan."
            if args.dry_run
            else "Saved the fragment plan with its existing query allowance."
        },
    }


def assess_command(ledger, args, rules):
    _, _, fingerprint = _fragment(args.project, args.shot, rules)
    plan = ledger.data.get("search_plans", {}).get(args.shot)
    if plan is None or plan["context_hash"] != fingerprint:
        raise ValueError("Assessment requires an existing plan with unchanged fragment context.")
    matching = [
        a
        for a in plan["attempts"]
        if " ".join(a["query"].split()).casefold() == " ".join(args.query.split()).casefold()
        and (args.media is None or a.get("media", "any") == args.media)
    ]
    if len(matching) != 1 or not args.assessment.strip():
        raise ValueError(
            "Assessment requires one recorded query and a nonempty explanation; use --media to distinguish repeated wording."
        )
    attempt = matching[0]
    attempt.update(assessment=args.assessment.strip(), assessed_at=now())
    ledger.save("search-assessment")
    return {
        "search_progress": progress(ledger.data),
        "summary": {"line": "Recorded the query assessment; visual suitability and human approval remain separate."},
    }


def attach_fragment_context(ledger, args, rules, row):
    """An explicit file selection from this catalog retains its saved narration."""
    plan = ledger.data.get("search_plans", {}).get(args.shot)
    if plan and row["provider"] == plan["catalog"]:
        _, _, fingerprint = _fragment(args.project, args.shot, rules)
        if plan["context_hash"] != fingerprint:
            raise ValueError("Fragment context changed; review the saved plan before selecting another file.")
        row["narration"] = plan["context"]["narration"]


def _dispatch(ledger, plan, args, rules, query):
    key = " ".join(query.split()).casefold() + " [" + args.media + "]"
    existing = next((a for a in plan["attempts"] if a["query_key"] == key), None)
    if existing:
        return existing, True
    if len(plan["attempts"]) >= QUERY_ALLOWANCE:
        raise ValueError("Search fragment has used all three meaningful queries for this catalog.")
    if any(a["status"] in ("results", "dispatched") and not a.get("assessment") for a in plan["attempts"]):
        raise ValueError("Assess prior results or the interrupted attempt with search-assess before another query.")
    attempt = {
        "query": query,
        "query_key": key,
        "language": args.language,
        "media": args.media,
        "at": now(),
        "status": "dispatched",
        "candidates": [],
    }
    plan["attempts"].append(attempt)
    ledger.save("search-dispatch")
    try:
        rows = providers.search(plan["catalog"], query, args.limit, media=args.media)
    except (ValueError, OSError) as error:
        attempt.update(status="access_or_provider_error", error=redact(error))
        ledger.save("search-outcome")
        return attempt, False
    added = []
    for source_row in rows:
        row = copy.deepcopy(source_row)
        if not allowed(row, rules):
            continue
        row["id"] += ":shot:" + args.shot
        row["shot"] = args.shot
        row["narration"] = plan["context"]["narration"]
        row["format"] = format_report(row, rules)
        row["match"] = {"kind": plan["context"]["intent"], "reason": "Search hit; visual confirmation required."}
        added.append(ledger.add(row))
    attempt.update(
        status="results" if added else "empty",
        candidates=[r["id"] for r in added],
        returned_count=len(rows),
        excluded_count=len(rows) - len(added),
        assessed_at=None,
    )
    ledger.save_many("search-outcome", added)
    return attempt, False


def search_command(ledger, args, rules):  # noqa: C901 - validation plus idempotent dispatch and optional bounded fallback
    if not args.shot or not 1 <= args.limit <= MAX_RESULTS:
        raise ValueError("Planned search requires --shot and a limit between 1 and 50.")
    beat, _, fingerprint = _fragment(args.project, args.shot, rules)
    plan = ledger.data.get("search_plans", {}).get(args.shot)
    if plan is None:
        raise ValueError("Save a search-plan for this fragment first.")
    if plan["context_hash"] != fingerprint:
        raise ValueError("Fragment context changed. Existing budget is preserved; review the plan before continuing.")
    if args.provider not in ("auto", plan["catalog"]):
        raise ValueError("--provider must match the saved fragment catalog.")
    if args.intent != beat["intent"]:
        raise ValueError("--intent must match the search fragment.")
    if not args.query.strip() or len(args.query) > MAX_QUERY_CHARS:
        raise ValueError("Search query must contain between 1 and 500 characters.")
    if args.media == "image" and "image" not in rules["asset_types"]:
        raise ValueError("Image search is incompatible with project media policy.")
    if args.dry_run:
        # Planned dry-run validates a prospective dispatch without contacting
        # the catalog: network searches must first consume a durable attempt.
        if len(plan["attempts"]) >= QUERY_ALLOWANCE:
            raise ValueError("Search fragment has used all three meaningful queries for this catalog.")
        return {
            "items": [],
            "dry_run": True,
            "would_dispatch": {"catalog": plan["catalog"], "query": args.query.strip(), "language": args.language},
            "summary": {"line": "Validated the planned query; dry-run did not contact the catalog."},
            "search_progress": progress(ledger.data),
        }
    attempt, replayed = _dispatch(ledger, plan, args, rules, args.query.strip())
    if attempt["status"] == "empty" and not replayed and len(args.query.split()) > QUERY_MAX_TOKENS:
        shorter = search_query({"target": args.query, "queries": []})
        if shorter != args.query.strip() and len(plan["attempts"]) < QUERY_ALLOWANCE:
            attempt, replayed = _dispatch(ledger, plan, args, rules, shorter)
    if attempt["status"] == "dispatched":
        return {
            "items": [],
            "interrupted_or_uncertain": True,
            "replayed": True,
            "search_progress": progress(ledger.data),
            "note": "No automatic re-dispatch: inspect the interrupted attempt.",
            "summary": {"line": "The saved dispatch is uncertain and remains consumed; no query was repeated."},
        }
    return {
        "items": [ledger.get(ident) for ident in attempt["candidates"]],
        "attempt": copy.deepcopy(attempt),
        "replayed": replayed,
        "dry_run": False,
        "search_progress": progress(ledger.data),
        "summary": {
            "line": f"{'Reused' if replayed else 'Recorded'} query outcome: {attempt['status']}; {len(attempt['candidates'])} candidates, suitability unconfirmed."
        },
    }
