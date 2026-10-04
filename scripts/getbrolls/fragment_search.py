"""One-catalog fragment plans, query accounting, and suitable-option confirmation."""

import copy
import hashlib
import json
import math
import re
import uuid

from . import providers
from .brief import QUERY_MAX_TOKENS, load_brief, search_query, validate_brief
from .models import empty_output, now
from .rules import allowed, format_report, load_rules
from .runtime import redact

QUERY_ALLOWANCE = 3
TARGET_OPTIONS = 3
MAX_RESULTS = 50
MAX_QUERY_CHARS = 500
MAX_TEXT = 2000
BOUNDARY_SHIFT_S = 1.0
NEAR_TRIM_IOU = 0.8
DIFFERENT_MOMENT_IOU = 0.35
SEPARATION_S = 1.0
INTERVAL_TOLERANCE_S = 0.001
TARGET_REACHED_MESSAGE = (
    "Three suitable distinct options are already confirmed for this fragment. No additional search query is dispatched."
)
DEFERRED_COUNT_REASON = (
    "Whether a visually confirmed option that needs a separately requested original "
    "counts toward the target is deferred."
)
CONTEXT_FIELDS = (
    "narration",
    "target",
    "intent",
    "allowed_sources",
    "stock",
    "notes",
    "asset_type",
    "duration_hint_s",
)


def _text(value):
    return isinstance(value, str) and bool(value)


def _optional_text(value):
    return value is None or isinstance(value, str)


def _optional_token(value):
    return value is None or _text(value)


PREVIEW_PARTS = {
    "gif": "gif_path",
    "contact-sheet": "contact_sheet_path",
    "poster": "poster_path",
}
_OPTION_NAME = re.compile(r"[a-z0-9][a-z0-9-]{0,40}\Z")


def _finite_number(value):
    return type(value) in (int, float) and math.isfinite(value)


def _valid_interval(interval):
    if not isinstance(interval, dict):
        return False
    kind = interval.get("kind")
    if kind == "still":
        return _text(interval.get("file")) and "start_s" not in interval and "end_s" not in interval
    if kind not in (None, "video"):
        return False
    start, end = interval.get("start_s"), interval.get("end_s")
    if not (type(start) is int or type(start) is float):
        return False
    if not (type(end) is int or type(end) is float):
        return False
    return math.isfinite(start) and math.isfinite(end) and 0 <= start < end


def _valid_confirmation(record):
    representation = record.get("representation") if isinstance(record, dict) else None
    interval = record.get("interval") if isinstance(record, dict) else None
    if (
        not isinstance(record, dict)
        or not _text(record.get("candidate"))
        or record.get("verdict") not in ("suitable", "unsuitable")
        or record.get("viewed") not in ("preview", "material")
        or not _optional_text(record.get("viewed_path"))
        or (record.get("viewed_path") is not None and not record["viewed_path"].startswith("previews/"))
        or not _text(record.get("viewed_sha256"))
        or not _text(record.get("observation"))
        or not _text(record.get("match"))
        or not _optional_text(record.get("distinctness"))
        or not _optional_text(record.get("duplicate_of"))
        or not _text(record.get("context_hash"))
        or not _text(record.get("at"))
        or type(record.get("requested_original")) is not bool
        or record.get("viewed_preview", None) not in (None, *PREVIEW_PARTS)
        or not _optional_token(record.get("invalidation"))
        or not isinstance(representation, dict)
        or not _text(representation.get("provider"))
        or not _text(representation.get("source_id"))
        or not _valid_interval(interval)
    ):
        return False
    for key in ("source_url", "item_id", "asset_file", "selected_file", "local_sha256", "sha1", "md5"):
        if not _optional_text(representation.get(key)):
            return False
    return True


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
        confirmations = plan.get("confirmations", [])
        if not isinstance(confirmations, list) or any(not _valid_confirmation(record) for record in confirmations):
            raise ValueError("Invalid suitable-option confirmation; preserve the project state.")


def _fragment(project, shot, rules):
    brief, conflicts = validate_brief(load_brief(project), rules)
    if conflicts:
        raise ValueError("Resolve brief conflicts before planned search: " + "; ".join(conflicts))
    beat = next((b["resolved"] for b in brief["beats"] if b["id"] == shot), None)
    if beat is None:
        raise ValueError("--shot must identify an existing BRIEF search fragment.")
    if beat.get("blocked_reason"):
        raise ValueError("Search fragment is blocked: " + beat["blocked_reason"])
    context = {key: beat.get(key) for key in CONTEXT_FIELDS}
    fingerprint = hashlib.sha256(json.dumps(context, sort_keys=True).encode()).hexdigest()
    return beat, context, fingerprint


def _fragment_hashes(project):
    """Current scenario fingerprints, or None when the fragment context cannot be read."""
    if not project:
        return None
    try:
        rules = load_rules(project)
        brief, conflicts = validate_brief(load_brief(project), rules)
    except (OSError, ValueError):
        return None
    if conflicts:
        return None
    fingerprints = {}
    for beat in brief["beats"]:
        resolved = beat["resolved"]
        context = {key: resolved.get(key) for key in CONTEXT_FIELDS}
        fingerprints[beat["id"]] = hashlib.sha256(json.dumps(context, sort_keys=True).encode()).hexdigest()
    return fingerprints


def _belongs(candidate, shot):
    return candidate.get("shot") == shot or str(candidate.get("id", "")).endswith(":shot:" + shot)


def _requested_original(candidate):
    acquisition = candidate.get("acquisition") or {}
    if acquisition.get("status") != "unavailable":
        return False
    restriction = str(acquisition.get("restriction") or "").lower()
    return acquisition.get("method") == "manual" or "separate access" in restriction or "request" in restriction


def _representation(candidate):
    archive = candidate.get("archive") or {}
    selected = archive.get("selected_file")
    representations = archive.get("representations") or []
    chosen = next((row for row in representations if isinstance(row, dict) and row.get("file") == selected), {})
    return {
        "provider": candidate.get("provider"),
        "source_id": candidate.get("source_id"),
        "source_url": candidate.get("source_url"),
        "item_id": archive.get("item_id"),
        "asset_file": archive.get("asset_file"),
        "selected_file": selected,
        "local_sha256": candidate.get("local_sha256"),
        "sha1": chosen.get("sha1") if isinstance(chosen, dict) else None,
        "md5": chosen.get("md5") if isinstance(chosen, dict) else None,
    }


def _interval_of(candidate):
    if (candidate.get("media") or {}).get("kind") == "image":
        archive = candidate.get("archive") or {}
        return {"kind": "still", "file": archive.get("selected_file") or candidate.get("source_id")}
    segment = candidate.get("segment") or {}
    if segment.get("start_s") is None or segment.get("end_s") is None:
        raise ValueError(
            "Video confirmation requires the viewed interval. Choose it with preview --start and --end; "
            "a scan or metadata row is not an interval."
        )
    return {"start_s": segment["start_s"], "end_s": segment["end_s"]}


def _close(left, right):
    return abs(float(left) - float(right)) <= INTERVAL_TOLERANCE_S


def _representation_matches(record, candidate):
    current = _representation(candidate)
    stored = record["representation"]
    keys = (
        "provider",
        "source_id",
        "source_url",
        "item_id",
        "asset_file",
        "selected_file",
        "local_sha256",
        "sha1",
        "md5",
    )
    return all(stored.get(key) == current.get(key) for key in keys)


def _interval_matches(record, candidate):
    try:
        current = _interval_of(candidate)
    except ValueError:
        return False
    stored = record["interval"]
    if stored.get("kind") == "still" or current.get("kind") == "still":
        return (
            stored.get("kind") == "still"
            and current.get("kind") == "still"
            and stored.get("file") == current.get("file")
        )
    return _close(stored.get("start_s"), current["start_s"]) and _close(stored.get("end_s"), current["end_s"])


def _invalidation_id(candidate):
    marker = candidate.get("visual_invalidation") if isinstance(candidate, dict) else None
    if not isinstance(marker, dict):
        return None
    ident = marker.get("id")
    return ident if _text(ident) else None


def _currency(record, candidate, fragment_hash):
    if candidate is None:
        reason = "candidate_missing"
    elif (candidate.get("approval") or {}).get("status") == "rejected" or record.get(
        "invalidation"
    ) != _invalidation_id(candidate):
        reason = "rejected"
    elif not fragment_hash:
        reason = "context_unverified"
    elif record.get("context_hash") != fragment_hash:
        reason = "context_changed"
    elif not _representation_matches(record, candidate):
        reason = "representation_changed"
    elif not _interval_matches(record, candidate):
        reason = "interval_changed"
    else:
        reason = None
    return reason


def _same_recording(left, right):
    """One original: archive item and asset, a shared file hash, or provider plus source id."""
    if left.get("item_id") and left.get("asset_file") and right.get("item_id") and right.get("asset_file"):
        same_asset = (left.get("provider"), left.get("item_id"), left.get("asset_file")) == (
            right.get("provider"),
            right.get("item_id"),
            right.get("asset_file"),
        )
        if same_asset:
            return True
    if any(left.get(key) and left.get(key) == right.get(key) for key in ("local_sha256", "sha1", "md5")):
        return True
    return bool(
        left.get("provider")
        and left.get("source_id")
        and (left.get("provider"), left.get("source_id")) == (right.get("provider"), right.get("source_id"))
    )


def _different_catalog_identity(left, right):
    rep_left, rep_right = left["representation"], right["representation"]
    if rep_left.get("item_id") and rep_right.get("item_id"):
        return (rep_left.get("item_id"), rep_left.get("asset_file")) != (
            rep_right.get("item_id"),
            rep_right.get("asset_file"),
        )
    return rep_left.get("source_id") != rep_right.get("source_id")


def _timed_relation(first, second):
    start_a, end_a = float(first["start_s"]), float(first["end_s"])
    start_b, end_b = float(second["start_s"]), float(second["end_s"])
    overlap = max(0.0, min(end_a, end_b) - max(start_a, start_b))
    union = max(end_a, end_b) - min(start_a, start_b)
    ratio = overlap / union if union > 0 else 1.0
    gap = max(start_a, start_b) - min(end_a, end_b)
    if abs(start_a - start_b) <= BOUNDARY_SHIFT_S and abs(end_a - end_b) <= BOUNDARY_SHIFT_S:
        relation = "small_boundary_shift"
    elif ratio >= NEAR_TRIM_IOU:
        relation = "near_identical_trim"
    elif ratio < DIFFERENT_MOMENT_IOU or gap >= SEPARATION_S:
        relation = "different_moment"
    else:
        relation = "ambiguous"
    return relation


def _interval_relation(left, right):
    first, second = left["interval"], right["interval"]
    if first.get("kind") == "still" or second.get("kind") == "still":
        same_still = first.get("kind") == second.get("kind") == "still" and _same_recording(
            left["representation"], right["representation"]
        )
        return "same_still" if same_still else "different"
    if not all(_finite_number(item.get(key)) for item in (first, second) for key in ("start_s", "end_s")):
        return "different"
    return _timed_relation(first, second)


def _pair_reason(left, right):
    explicit = left.get("duplicate_of") == right["candidate"] or right.get("duplicate_of") == left["candidate"]
    same = _same_recording(left["representation"], right["representation"])
    relation = _interval_relation(left, right) if same else "different"
    if same and relation == "same_still":
        if _different_catalog_identity(left, right):
            return "repost"
        return "same_still"
    if same and relation in ("small_boundary_shift", "near_identical_trim"):
        if _different_catalog_identity(left, right):
            return "repost"
        return relation
    if explicit:
        return "explicit_duplicate"
    return None


def _viewing(record):
    return {
        "viewed": record["viewed"],
        "viewed_preview": record.get("viewed_preview"),
        "viewed_path": record.get("viewed_path"),
        "viewed_sha256": record["viewed_sha256"],
        "observation": record["observation"],
        "match": record["match"],
        "at": record["at"],
    }


def _identity(record):
    representation = record["representation"]
    return {
        "candidate": record["candidate"],
        "provider": representation.get("provider"),
        "source_id": representation.get("source_id"),
        "source_url": representation.get("source_url"),
        "item_id": representation.get("item_id"),
        "asset_file": representation.get("asset_file"),
        "selected_file": representation.get("selected_file"),
        "interval": copy.deepcopy(record["interval"]),
        "hashes": {
            "local_sha256": representation.get("local_sha256"),
            "sha1": representation.get("sha1"),
            "md5": representation.get("md5"),
        },
        "viewing": _viewing(record),
        "distinctness": record.get("distinctness"),
    }


def _option_id(members):
    payload = [[member["candidate"], member["interval"]] for member in members]
    return hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()[:16]


def _clusters(records):
    parent = list(range(len(records)))

    def find(index):
        while parent[index] != index:
            parent[index] = parent[parent[index]]
            index = parent[index]
        return index

    for left_index, left in enumerate(records):
        for right_index in range(left_index + 1, len(records)):
            if _pair_reason(left, records[right_index]):
                parent[find(right_index)] = find(left_index)
    groups = {}
    for index, record in enumerate(records):
        groups.setdefault(find(index), []).append(record)
    return list(groups.values())


def _group_signals(members):
    reasons, claims, relations = [], [], []
    for left_index, left in enumerate(members):
        if left.get("distinctness"):
            claims.append(left["distinctness"])
        for right in members[left_index + 1 :]:
            reason = _pair_reason(left, right)
            if reason:
                reasons.append(reason)
            relations.append(_interval_relation(left, right))
    grouped_reason = next(
        (
            reason
            for reason in (
                "repost",
                "same_still",
                "small_boundary_shift",
                "near_identical_trim",
                "explicit_duplicate",
            )
            if reason in reasons
        ),
        None,
    )
    return grouped_reason, claims, relations


def _group_support(members, records, grouped_reason, claims, relations):
    if len(members) == 1:
        others = [record for record in records if record is not members[0]]
        return _singleton_support(members[0], others)
    unsupported = (grouped_reason == "explicit_duplicate" and "different_moment" in relations) or bool(claims)
    return "unsupported" if unsupported else "supported"


def _group_options(records):
    options = []
    for members in _clusters(records):
        grouped_reason, claims, relations = _group_signals(members)
        support = _group_support(members, records, grouped_reason, claims, relations)
        options.append(
            {
                "option_id": _option_id(members),
                "counts_toward_target": True,
                "grouped_reason": grouped_reason,
                "distinctness": members[0].get("distinctness") if len(members) == 1 else None,
                "distinctness_support": support,
                "unsupported_distinctness": claims if support == "unsupported" else [],
                "identities": [_identity(member) for member in members],
                "viewing": _viewing(members[0]),
            }
        )
    return options


def _singleton_support(record, others):
    same = [other for other in others if _same_recording(record["representation"], other["representation"])]
    if same:
        relations = [_interval_relation(record, other) for other in same]
        if "ambiguous" in relations or not (record.get("distinctness") or "").strip():
            return "unsupported"
        return "supported"
    if any(
        not _same_recording(record["representation"], other["representation"])
        and not any(
            record["representation"].get(key) and other["representation"].get(key)
            for key in ("local_sha256", "sha1", "md5")
        )
        and not (
            record["representation"].get("asset_file")
            and other["representation"].get("asset_file")
            and record["representation"].get("asset_file") != other["representation"].get("asset_file")
        )
        for other in others
    ):
        return "unsupported"
    return "supported"


def _derived_selection(candidate):
    """A preview option is a scene of a source, not another catalog result."""
    selection = candidate.get("selection")
    return isinstance(selection, dict) and _text(selection.get("source_candidate"))


def _raw_hits(plan, items, shot):
    identities = []
    for attempt in plan.get("attempts") or []:
        for ident in attempt.get("candidates") or []:
            if ident not in identities:
                identities.append(ident)
    for candidate in items:
        if (
            isinstance(candidate, dict)
            and _belongs(candidate, shot)
            and candidate.get("id") not in identities
            and not _derived_selection(candidate)
        ):
            identities.append(candidate["id"])
    by_id = {candidate["id"]: candidate for candidate in items if isinstance(candidate, dict) and candidate.get("id")}
    hits = []
    for ident in identities:
        candidate = by_id.get(ident) or {}
        hits.append(
            {
                "candidate": ident,
                "title": candidate.get("title"),
                "provider": candidate.get("provider"),
                "source_id": candidate.get("source_id"),
                "source_url": candidate.get("source_url"),
                "approval": (candidate.get("approval") or {}).get("status"),
                "rights": (candidate.get("rights") or {}).get("status"),
            }
        )
    return hits


def _annotate(plan, items, fragment_hash):
    by_id = {candidate["id"]: candidate for candidate in items if isinstance(candidate, dict) and candidate.get("id")}
    stored = copy.deepcopy(plan.get("confirmations") or [])
    latest_index = {}
    for index, record in enumerate(stored):
        latest_index[record["candidate"]] = index
    evidence = []
    countable = []
    deferred = []
    for index, record in enumerate(stored):
        candidate = by_id.get(record["candidate"])
        superseded = latest_index.get(record["candidate"]) != index
        stale = "superseded" if superseded else _currency(record, candidate, fragment_hash)
        current = stale is None
        record_view = {
            **record,
            "current": current,
            "stale_reason": stale,
            "superseded": superseded,
            "deferred": bool(record.get("requested_original")),
        }
        evidence.append(record_view)
        if not current or record["verdict"] != "suitable":
            continue
        if record.get("requested_original"):
            deferred.append(record)
        else:
            countable.append(record)
    return evidence, countable, deferred


def _deferred_option(record):
    return {
        "candidate": record["candidate"],
        "counts_toward_target": False,
        "count_policy": "deferred",
        "reason": DEFERRED_COUNT_REASON,
        "interval": copy.deepcopy(record["interval"]),
        "representation": copy.deepcopy(record["representation"]),
        "viewing": _viewing(record),
        "distinctness": record.get("distinctness"),
    }


def _pending_decisions(options, items):
    by_id = {candidate["id"]: candidate for candidate in items if isinstance(candidate, dict) and candidate.get("id")}
    pending = []
    for option in options:
        for identity in option["identities"]:
            candidate = by_id.get(identity["candidate"]) or {}
            approval = (candidate.get("approval") or {}).get("status")
            if approval == "approved":
                continue
            pending.append(
                {
                    "candidate": identity["candidate"],
                    "option_id": option["option_id"],
                    "approval": approval or "pending",
                    "rights": (candidate.get("rights") or {}).get("status"),
                }
            )
    return pending


def progress(data, recovery_pending=False, project=None):
    items = data.get("items") or []
    fingerprints = _fragment_hashes(project)
    result = []
    for shot, plan in data.get("search_plans", {}).items():
        attempts = copy.deepcopy(plan["attempts"])
        for attempt in attempts:
            if attempt["status"] == "dispatched":
                attempt["status"] = "interrupted_or_uncertain"
        used = len(attempts)
        fragment_hash = None if fingerprints is None else fingerprints.get(shot)
        evidence, countable, deferred_records = _annotate(plan, items, fragment_hash)
        suitable = _group_options(countable)
        deferred = [_deferred_option(record) for record in deferred_records]
        reached = len(suitable) >= TARGET_OPTIONS
        note = (
            "Pending journal may contain a consumed dispatch or confirmation; recover it before "
            "determining the allowance or the suitable-option count."
            if recovery_pending
            else "Three suitable distinct options are confirmed. Further search queries are not dispatched. "
            "Visual confirmation is not human approval or usage rights."
            if reached
            else "Query assessments are not viewing evidence. A hit counts only after search-confirm records "
            "the material or preview that was actually viewed. Visual confirmation is not human approval or usage rights."
        )
        if deferred and not recovery_pending:
            note = note + " " + DEFERRED_COUNT_REASON
        result.append(
            {
                "fragment": shot,
                "pass": plan["pass"],
                "catalog": plan["catalog"],
                "reason": plan["reason"],
                "expected_material": plan["expected_material"],
                "context": plan["context"],
                "context_stale": fragment_hash != plan.get("context_hash"),
                "queries_used": None if recovery_pending else used,
                "queries_remaining": None if recovery_pending else max(0, QUERY_ALLOWANCE - used),
                "recovery_pending": recovery_pending,
                "attempts": attempts,
                "raw_hits": _raw_hits(plan, items, shot),
                "suitable_options": suitable,
                "suitable_count": len(suitable),
                "viewing_evidence": evidence,
                "pending_human_decisions": _pending_decisions(suitable, items),
                "deferred_options": deferred,
                "target_reached": reached,
                "next": "recover_pending_write"
                if recovery_pending
                else "target_reached"
                if reached
                else "assess_results_or_finish_single_catalog"
                if used >= QUERY_ALLOWANCE
                else "assess_results_or_query",
                "note": note,
            }
        )
    return result


def _target_reached(ledger, project, shot):
    return any(row["fragment"] == shot and row["target_reached"] for row in progress(ledger.data, project=project))


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
    data = {"search_plans": {args.shot: current or proposed}, "items": ledger.data.get("items", [])}
    return {
        "search_progress": progress(data, project=args.project),
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
        "search_progress": progress(ledger.data, project=args.project),
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
    if _target_reached(ledger, args.project, args.shot):
        raise ValueError(TARGET_REACHED_MESSAGE)
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


def _planned_dry_run(ledger, plan, args):
    """Validate a prospective dispatch without contacting the catalog or spending a query."""
    query_key = " ".join(args.query.split()).casefold() + " [" + args.media + "]"
    replayed = any(attempt["query_key"] == query_key for attempt in plan["attempts"])
    if not replayed and _target_reached(ledger, args.project, args.shot):
        raise ValueError(TARGET_REACHED_MESSAGE)
    if not replayed and len(plan["attempts"]) >= QUERY_ALLOWANCE:
        raise ValueError("Search fragment has used all three meaningful queries for this catalog.")
    return {
        "items": [],
        "dry_run": True,
        "replayed": replayed,
        "would_dispatch": {"catalog": plan["catalog"], "query": args.query.strip(), "language": args.language},
        "summary": {"line": "Validated the planned query; dry-run did not contact the catalog."},
        "search_progress": progress(ledger.data, project=args.project),
    }


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
        return _planned_dry_run(ledger, plan, args)
    attempt, replayed = _dispatch(ledger, plan, args, rules, args.query.strip())
    if attempt["status"] == "empty" and not replayed and len(args.query.split()) > QUERY_MAX_TOKENS:
        shorter = search_query({"target": args.query, "queries": []})
        if (
            shorter != args.query.strip()
            and len(plan["attempts"]) < QUERY_ALLOWANCE
            and not _target_reached(ledger, args.project, args.shot)
        ):
            attempt, replayed = _dispatch(ledger, plan, args, rules, shorter)
    report = progress(ledger.data, project=args.project)
    suitable_count = next(row["suitable_count"] for row in report if row["fragment"] == args.shot)
    if attempt["status"] == "dispatched":
        return {
            "items": [],
            "interrupted_or_uncertain": True,
            "replayed": True,
            "search_progress": report,
            "note": "No automatic re-dispatch: inspect the interrupted attempt.",
            "summary": {"line": "The saved dispatch is uncertain and remains consumed; no query was repeated."},
        }
    return {
        "items": [ledger.get(ident) for ident in attempt["candidates"]],
        "attempt": copy.deepcopy(attempt),
        "replayed": replayed,
        "dry_run": False,
        "search_progress": report,
        "summary": {
            "line": (
                f"{'Reused' if replayed else 'Recorded'} query outcome: {attempt['status']}; "
                f"{len(attempt['candidates'])} raw hits, {suitable_count} current suitable options."
            )
        },
    }


def _bounded(value, flag):
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{flag} must describe what was actually viewed.")
    text = value.strip()
    if len(text) > MAX_TEXT:
        raise ValueError(f"{flag} must be at most {MAX_TEXT} characters.")
    return text


def _safe_preview_path(value):
    from pathlib import Path

    return (
        isinstance(value, str) and value.startswith("previews/") and ".." not in Path(value).parts and "\\" not in value
    )


def _viewed_evidence(ledger, candidate, viewed, preview_part):
    from pathlib import Path

    from .ledger import digest

    if viewed == "material":
        if preview_part:
            raise ValueError("--preview names a generated preview. Omit it when --viewed material.")
        path = candidate.get("local_path")
        if not path or not Path(path).is_file():
            raise ValueError(
                "Material viewing requires the acquired file on disk. A preview path or metadata is not material."
            )
        digest_value = digest(path)
        if candidate.get("local_sha256") and digest_value != candidate["local_sha256"]:
            raise ValueError(
                "Acquired material changed since it was stored. Preview the current representation before confirming."
            )
        return {"viewed": "material", "viewed_preview": None, "viewed_path": None, "viewed_sha256": digest_value}
    if viewed != "preview":
        raise ValueError("--viewed must be preview or material.")
    if preview_part not in PREVIEW_PARTS:
        raise ValueError("--preview must name the file you opened: gif, contact-sheet, or poster.")
    relative = (candidate.get("preview") or {}).get(PREVIEW_PARTS[preview_part])
    if not _safe_preview_path(relative):
        raise ValueError(
            "The selected preview is missing or is not a generated preview file. "
            "Choose gif, contact-sheet, or poster from this candidate."
        )
    preview_file = ledger.root / relative
    if not preview_file.is_file():
        raise ValueError(
            "The preview file is not on disk, so it has not been viewed. Generate it and look at it before search-confirm."
        )
    return {
        "viewed": "preview",
        "viewed_preview": preview_part,
        "viewed_path": relative,
        "viewed_sha256": digest(preview_file),
    }


def invalidate_visual_confirmation(candidate):
    """Rejection drops current suitability until a later search-confirm. Approval does not clear it."""
    candidate["visual_invalidation"] = {"id": uuid.uuid4().hex, "at": now()}
    return candidate


def select_preview_option(ledger, parent, option):
    """Reuse or create one interval selection of this source. The default preview still edits the parent."""
    key = (option or "").strip().casefold()
    if _OPTION_NAME.fullmatch(key) is None:
        raise ValueError(
            "--option must be a short name such as opening or scene-2. It selects another interval of this source."
        )
    selection = parent.get("selection")
    root_id = parent["id"]
    if isinstance(selection, dict) and _text(selection.get("source_candidate")):
        root_id = selection["source_candidate"]
    new_id = root_id + ":option:" + key
    existing = next((item for item in ledger.data["items"] if item.get("id") == new_id), None)
    if existing is not None:
        return existing
    child = copy.deepcopy(parent)
    child["id"] = new_id
    child["selection"] = {"option": key, "source_candidate": root_id}
    child["approval"] = {"status": "pending", "by": None, "at": None, "revision": None}
    child.pop("review", None)
    child.pop("rejection", None)
    child.pop("visual_invalidation", None)
    child["output"] = empty_output()
    child["state"] = "candidate"
    child["segment"] = {"start_s": None, "end_s": None, "revision": 0}
    preview = child.get("preview") or {}
    child["preview"] = {name: preview[name] for name in ("poster_url", "embed_url", "seek_mode") if name in preview}
    rights = child.get("rights") or {}
    source_url = child.get("source_url")
    child["rights"] = {
        "status": "unknown",
        "license_name": rights.get("license_name"),
        "license_url": rights.get("license_url"),
        "evidence": [source_url] if isinstance(source_url, str) and source_url else [],
        "attribution": rights.get("attribution"),
    }
    ledger.data["items"].append(child)
    return child


def confirm_command(ledger, args, rules):
    """Record the managing agent's viewing evidence without granting approval or spending a query."""
    _, _, fingerprint = _fragment(args.project, args.shot, rules)
    plan = ledger.data.get("search_plans", {}).get(args.shot)
    if plan is None:
        raise ValueError("Save a search-plan for this fragment first.")
    candidate = ledger.get(args.candidate)
    if not _belongs(candidate, args.shot):
        raise ValueError("Candidate is not part of this search fragment.")
    verdict = getattr(args, "verdict", None) or "suitable"
    if verdict not in ("suitable", "unsuitable"):
        raise ValueError("--verdict must be suitable or unsuitable.")
    distinctness = (getattr(args, "distinctness", None) or "").strip() or None
    if distinctness and len(distinctness) > MAX_TEXT:
        raise ValueError(f"--distinctness must be at most {MAX_TEXT} characters.")
    duplicate_of = (getattr(args, "duplicate_of", None) or "").strip() or None
    if duplicate_of:
        other = ledger.get(duplicate_of)
        if other["id"] == candidate["id"] or not _belongs(other, args.shot):
            raise ValueError("--duplicate-of must name another candidate in this search fragment.")
    record = {
        "candidate": candidate["id"],
        "verdict": verdict,
        "observation": _bounded(args.observation, "--observation"),
        "match": _bounded(args.match, "--match"),
        "distinctness": distinctness,
        "duplicate_of": duplicate_of,
        "context_hash": fingerprint,
        "representation": _representation(candidate),
        "interval": _interval_of(candidate),
        "requested_original": _requested_original(candidate),
        "invalidation": _invalidation_id(candidate),
        "at": now(),
        **_viewed_evidence(ledger, candidate, args.viewed, getattr(args, "preview", None)),
    }
    if not _valid_confirmation(record):
        raise ValueError("Viewing evidence is incomplete. Preserve the project and record the viewed material again.")
    plan.setdefault("confirmations", []).append(record)
    ledger.save("search-confirm")
    from .rendering import render

    render(ledger)
    report = progress(ledger.data, project=args.project)
    row = next(item for item in report if item["fragment"] == args.shot)
    return {
        "candidate": candidate["id"],
        "verdict": verdict,
        "requested_original": record["requested_original"],
        "approval": candidate.get("approval"),
        "rights": {"status": (candidate.get("rights") or {}).get("status")},
        "search_progress": report,
        "summary": {
            "line": (
                f"Recorded visual confirmation for {candidate['id']}. "
                f"Suitable distinct options: {row['suitable_count']} of {TARGET_OPTIONS}. "
                "This is not human approval or usage rights."
            )
        },
    }
