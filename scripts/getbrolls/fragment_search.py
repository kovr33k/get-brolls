"""Fragment catalog chains, per-catalog query accounting, and suitable-option confirmation."""

import copy
import hashlib
import json
import math
import re
import uuid

from . import providers
from .brief import QUERY_MAX_TOKENS, load_brief, search_query, validate_brief
from .http import BrowserVerificationError
from .models import empty_output, now
from .rules import allowed, format_report, load_rules
from .runtime import redact

QUERY_ALLOWANCE = 3
TARGET_OPTIONS = 3
MAX_CHAIN_CATALOGS = 5
MAX_PASSES = 2
MAX_FRAGMENT_QUERIES = MAX_CHAIN_CATALOGS * MAX_PASSES * QUERY_ALLOWANCE
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
ALLOWANCE_MESSAGE = "Search fragment has used all three meaningful queries for this catalog."
ROUTE_UNIMPLEMENTED = (
    "This catalog has no implemented keyword-search route. No query was dispatched and no browser search was run. "
    "Close it with search-plan --advance --because route-unimplemented, or import through its supported route "
    "when that lifecycle is available."
)
LIMIT_NOTE = (
    "Empty results, failed access, and incomplete coverage are search limits. "
    "They do not establish that matching footage is absent."
)
PLAN_RESET_MESSAGE = "This fragment already has a plan. Reusing its state cannot reset the query budget or context."
ASSESS_BEFORE_LEAVING = (
    "Assess prior results or the interrupted attempt with search-assess before leaving this catalog."
)
BECAUSE_KINDS = ("allowance-exhausted", "unavailable-access", "unsuitable-source", "route-unimplemented")
EARLY_KINDS = ("unavailable-access", "unsuitable-source", "route-unimplemented")
CATALOG_STATES = ("pending", "current", "exhausted", "skipped")
COVERAGE_VALUES = ("incomplete", "assessed")
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
    for key in (
        "source_url",
        "item_id",
        "asset_file",
        "selected_file",
        "local_sha256",
        "sha1",
        "md5",
        "locator_preview",
        "linked_original",
    ):
        if not _optional_text(representation.get(key)):
            return False
    return True


def _bounded_text(value):
    return isinstance(value, str) and bool(value.strip()) and len(value) <= MAX_TEXT


def _attempt_pass(plan, attempt):
    value = attempt.get("pass")
    if type(value) is int:
        return value
    catalog = attempt.get("catalog")
    if isinstance(catalog, str):
        for chain in _stored_chains(plan):
            catalogs = chain.get("catalogs") or []
            if any(isinstance(entry, dict) and entry.get("catalog") == catalog for entry in catalogs):
                return chain.get("pass") if type(chain.get("pass")) is int else 1
    return 1


def _attempt_catalog(plan, attempt):
    value = attempt.get("catalog")
    if isinstance(value, str) and value:
        return value
    return plan.get("catalog")


def _catalog_attempts(plan, catalog, search_pass):
    return [
        attempt
        for attempt in plan.get("attempts") or []
        if _attempt_catalog(plan, attempt) == catalog and _attempt_pass(plan, attempt) == search_pass
    ]


def _stored_chains(plan):
    """Persisted chains, or the one-catalog plan shape saved before chain support."""
    chains = plan.get("chains")
    if isinstance(chains, list) and chains:
        return chains
    return [
        {
            "pass": 1,
            "catalogs": [
                {
                    "catalog": plan.get("catalog"),
                    "reason": plan.get("reason"),
                    "expected_material": plan.get("expected_material"),
                    "state": "current",
                }
            ],
        }
    ]


def _ensure_chains(plan):
    if isinstance(plan.get("chains"), list) and plan["chains"]:
        return plan["chains"]
    plan["chains"] = _stored_chains(plan)
    return plan["chains"]


def _active_chain(plan):
    chains = _stored_chains(plan)
    for chain in chains:
        if chain.get("pass") == plan.get("pass"):
            return chain
    return chains[-1]


def _current_entry(plan):
    for entry in _active_chain(plan)["catalogs"]:
        if entry.get("catalog") == plan.get("catalog"):
            return entry
    raise ValueError("Invalid search plan; preserve the project state.")


def _entry_state(entry):
    return entry.get("state") or "current"


def _pending_entries(plan):
    return [entry for entry in _active_chain(plan)["catalogs"] if _entry_state(entry) == "pending"]


def _has_pass(plan, search_pass):
    return any(chain.get("pass") == search_pass for chain in _stored_chains(plan) if isinstance(chain, dict))


def _plan_catalogs(plan):
    return [
        entry["catalog"]
        for chain in _stored_chains(plan)
        for entry in chain.get("catalogs") or []
        if isinstance(entry, dict) and entry.get("catalog")
    ]


def _pass_exhausted(plan):
    try:
        entry = _current_entry(plan)
    except ValueError:
        return False
    open_allowance = _entry_state(entry) == "current" and (
        len(_catalog_attempts(plan, plan.get("catalog"), plan.get("pass"))) < QUERY_ALLOWANCE
    )
    return not open_allowance and not _pending_entries(plan)


def _needs_assessment(plan, catalog, search_pass):
    return any(
        attempt.get("status") in ("results", "dispatched") and not attempt.get("assessment")
        for attempt in _catalog_attempts(plan, catalog, search_pass)
    )


def _unassessed_exit(plan):
    """Block a pass change or shortfall while the current catalog still needs search-assess."""
    if _needs_assessment(plan, plan.get("catalog"), plan.get("pass")):
        return ASSESS_BEFORE_LEAVING
    return None


def _keyword_search(catalog):
    # Browser and locator catalogs stay in the chain through their own route.
    # Missing keyword search is a limitation, not permission to invent a call.
    capability = providers.capabilities().get(catalog) or {}
    return bool(capability.get("search"))


def _browser_search(catalog):
    return bool((providers.capabilities().get(catalog) or {}).get("browser_search"))


def _chain_identity(entries):
    return [(entry["catalog"], entry["reason"], entry["expected_material"]) for entry in entries]


def _stored_identity(plan, search_pass):
    for chain in plan.get("chains") or []:
        if chain.get("pass") == search_pass:
            return [
                (entry.get("catalog"), entry.get("reason"), entry.get("expected_material"))
                for entry in chain.get("catalogs") or []
            ]
    if search_pass == 1 and "chains" not in plan and plan.get("catalog"):
        return [(plan.get("catalog"), plan.get("reason"), plan.get("expected_material"))]
    return None


def _validate_closed(entry):
    state = entry.get("state")
    closed = entry.get("closed")
    if state in ("pending", "current"):
        return closed is None
    if closed is None:
        return state == "exhausted"
    if (
        not isinstance(closed, dict)
        or closed.get("kind") not in BECAUSE_KINDS
        or not _bounded_text(closed.get("reason"))
    ):
        return False
    if not isinstance(closed.get("at"), str) or not closed["at"]:
        return False
    return not (state == "skipped" and closed["kind"] == "allowance-exhausted")


def _entry_acceptable(entry, seen, seen_pending):
    if (
        not isinstance(entry, dict)
        or entry.get("state") not in CATALOG_STATES
        or not _bounded_text(entry.get("catalog"))
        or not _bounded_text(entry.get("reason"))
        or not _bounded_text(entry.get("expected_material"))
        or entry["catalog"] in seen
        or not _validate_closed(entry)
    ):
        return False
    if entry["state"] in ("exhausted", "skipped") and seen_pending:
        return False
    return not (entry["state"] == "current" and seen_pending)


def _one_chain_shape(chain, seen, passes):
    catalogs = chain.get("catalogs") if isinstance(chain, dict) else None
    if (
        not isinstance(chain, dict)
        or type(chain.get("pass")) is not int
        or not isinstance(catalogs, list)
        or not 1 <= len(catalogs) <= MAX_CHAIN_CATALOGS
    ):
        return False
    passes.append(chain["pass"])
    seen_pending = False
    for entry in catalogs:
        if not _entry_acceptable(entry, seen, seen_pending):
            return False
        if entry["state"] == "pending":
            seen_pending = True
        seen.add(entry["catalog"])
    return True


def _currents_match(plan, chains):
    currents = [
        (chain["pass"], entry) for chain in chains for entry in chain["catalogs"] if entry["state"] == "current"
    ]
    if len(currents) > 1:
        return False
    if len(currents) == 1:
        return currents[0][0] == plan["pass"] and currents[0][1]["catalog"] == plan["catalog"]
    return plan.get("catalog") in {entry["catalog"] for entry in chains[-1]["catalogs"]}


def _validate_chain_shape(plan):
    chains = plan.get("chains")
    if not isinstance(chains, list) or not 1 <= len(chains) <= MAX_PASSES:
        return False
    seen = set()
    passes = []
    for chain in chains:
        if not _one_chain_shape(chain, seen, passes):
            return False
    if passes != list(range(1, len(passes) + 1)) or plan.get("pass") != passes[-1]:
        return False
    return _currents_match(plan, chains)


def _validate_attempts(plan):
    legacy = "chains" not in plan
    if legacy and (plan.get("pass") != 1 or len(plan["attempts"]) > QUERY_ALLOWANCE):
        raise ValueError("Invalid search plan; preserve the project state.")
    seen = set()
    counts = {}
    known = set(_plan_catalogs(plan)) if not legacy else {plan.get("catalog")}
    for attempt in plan["attempts"]:
        catalog = attempt.get("catalog")
        search_pass = attempt.get("pass", 1 if legacy else None)
        identity = (attempt.get("query_key"), catalog if isinstance(catalog, str) else None, search_pass)
        coverage = attempt.get("coverage", None)
        if (
            not isinstance(attempt, dict)
            or not isinstance(attempt.get("query_key"), str)
            or identity in seen
            or not isinstance(attempt.get("query"), str)
            or attempt.get("status") not in ("dispatched", "results", "empty", "access_or_provider_error")
            or not isinstance(attempt.get("candidates"), list)
            or any(not isinstance(candidate, str) for candidate in attempt["candidates"])
            or coverage not in (None, *COVERAGE_VALUES)
            or (isinstance(catalog, str) and catalog not in known)
            or ("pass" in attempt and type(attempt.get("pass")) is not int)
            or (attempt.get("route") not in (None, "browser"))
            or (
                attempt.get("route") == "browser"
                and (
                    catalog not in ("instagram", "tiktok", "un_avlibrary", "destockd", "loc")
                    or not isinstance(attempt.get("id"), str)
                    or not re.fullmatch(r"[0-9a-f]{20}", attempt["id"])
                )
            )
        ):
            raise ValueError("Invalid search attempt; preserve the project state.")
        seen.add(identity)
        key = (_attempt_catalog(plan, attempt), _attempt_pass(plan, attempt))
        counts[key] = counts.get(key, 0) + 1
    if len(plan["attempts"]) > MAX_FRAGMENT_QUERIES or any(count > QUERY_ALLOWANCE for count in counts.values()):
        raise ValueError("Invalid search plan; preserve the project state.")


def _validate_shortfall(plan):
    shortfall = plan.get("shortfall")
    if shortfall is None:
        return
    if (
        not isinstance(shortfall, dict)
        or shortfall.get("kind") not in ("no-further-catalog", "passes-exhausted")
        or not _bounded_text(shortfall.get("reason"))
        or not isinstance(shortfall.get("at"), str)
        or not shortfall["at"]
    ):
        raise ValueError("Invalid search plan; preserve the project state.")


def validate_plans(data):
    plans = data.get("search_plans", {})
    if not isinstance(plans, dict):
        raise ValueError("Invalid search plans; preserve the project state.")
    for shot, plan in plans.items():
        legacy = isinstance(plan, dict) and "chains" not in plan
        if (
            not isinstance(shot, str)
            or not isinstance(plan, dict)
            or type(plan.get("pass")) is not int
            or plan.get("pass") not in (1, 2)
            or (legacy and plan.get("pass") != 1)
            or not all(
                isinstance(plan.get(key), str) and plan[key]
                for key in ("catalog", "reason", "expected_material", "context_hash")
            )
            or not isinstance(plan.get("context"), dict)
            or not isinstance(plan.get("attempts"), list)
            or ("chains" in plan and not _validate_chain_shape(plan))
        ):
            raise ValueError("Invalid search plan; preserve the project state.")
        _validate_attempts(plan)
        _validate_shortfall(plan)
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
    if candidate.get("provider") in ("un_avlibrary", "destockd"):
        return True
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
        "locator_preview": (candidate.get("locator") or {}).get("preview_url"),
        "linked_original": json.dumps(candidate.get("source_reference"), sort_keys=True)
        if candidate.get("source_reference")
        else None,
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
        "locator_preview",
        "linked_original",
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


def _outcome_counts(plan):
    empty = access = incomplete = 0
    for attempt in plan.get("attempts") or []:
        status = attempt.get("status")
        if status == "empty":
            empty += 1
        elif status == "access_or_provider_error":
            access += 1
        if attempt.get("coverage") == "incomplete":
            incomplete += 1
    return {"empty_results": empty, "access_failures": access, "incomplete_coverage": incomplete}


def _catalog_rows(plan, recovery_pending):
    rows = []
    for chain in _stored_chains(plan):
        for entry in chain["catalogs"]:
            used = len(_catalog_attempts(plan, entry.get("catalog"), chain.get("pass")))
            state = _entry_state(entry)
            if recovery_pending:
                remaining = None
            elif state == "current":
                remaining = max(0, QUERY_ALLOWANCE - used)
            else:
                remaining = 0
            rows.append(
                {
                    "pass": chain.get("pass"),
                    "catalog": entry.get("catalog"),
                    "reason": entry.get("reason"),
                    "expected_material": entry.get("expected_material"),
                    "state": state,
                    "queries_used": None if recovery_pending else used,
                    "queries_remaining": remaining,
                    "closed": copy.deepcopy(entry.get("closed")),
                }
            )
    return rows


def _closed_catalog_next(plan, needs, pending):
    if needs and pending:
        return "assess_results_or_advance"
    if needs and plan.get("pass") == 1 and not _has_pass(plan, 2):
        return "assess_results_or_plan_additional_pass"
    if needs:
        return "assess_results_or_record_shortfall"
    if pending:
        return "advance_catalog"
    if plan.get("pass") == 1 and not _has_pass(plan, 2):
        return "plan_additional_pass"
    return "record_shortfall"


def _catalog_next(plan):
    used = len(_catalog_attempts(plan, plan.get("catalog"), plan.get("pass")))
    needs = _needs_assessment(plan, plan.get("catalog"), plan.get("pass"))
    pending = bool(_pending_entries(plan))
    if any(
        item.get("route") == "browser" and item["status"] == "dispatched"
        for item in _catalog_attempts(plan, plan.get("catalog"), plan.get("pass"))
    ):
        return "complete_browser_attempt"
    if (
        _entry_state(_current_entry(plan)) == "current"
        and any(
            item.get("error_code") == "BROWSER_VERIFICATION_REQUIRED" and item.get("route") != "browser"
            for item in _catalog_attempts(plan, plan.get("catalog"), plan.get("pass"))
        )
        and _browser_search(plan.get("catalog"))
    ):
        return "reserve_browser_query"
    if _entry_state(_current_entry(plan)) == "current" and QUERY_ALLOWANCE - used > 0:
        if not _keyword_search(plan.get("catalog")) and not needs:
            if _browser_search(plan.get("catalog")):
                return "reserve_browser_query"
            return "advance_unimplemented_route"
        return "assess_results_or_query"
    return _closed_catalog_next(plan, needs, pending)


def _next_action(plan, reached, recovery_pending):
    if recovery_pending:
        return "recover_pending_write"
    if reached:
        return "target_reached"
    if plan.get("shortfall"):
        return "shortfall"
    return _catalog_next(plan)


def _shortfall_view(plan, suitable_count, reached):
    if reached:
        return None
    outcomes = _outcome_counts(plan)
    stored = plan.get("shortfall") if isinstance(plan.get("shortfall"), dict) else None
    passes_done = plan.get("pass") == MAX_PASSES and _pass_exhausted(plan) and _unassessed_exit(plan) is None
    if stored is None and not passes_done:
        return None
    return {
        "kind": stored["kind"] if stored else "passes-exhausted",
        "reason": stored["reason"] if stored else "Both search passes are exhausted.",
        "suitable_count": suitable_count,
        "target": TARGET_OPTIONS,
        "empty_results": outcomes["empty_results"],
        "access_failures": outcomes["access_failures"],
        "incomplete_coverage": outcomes["incomplete_coverage"],
        "note": LIMIT_NOTE,
    }


def progress(data, recovery_pending=False, project=None):
    items = data.get("items") or []
    fingerprints = _fragment_hashes(project)
    result = []
    for shot, plan in data.get("search_plans", {}).items():
        attempts = copy.deepcopy(plan["attempts"])
        for attempt in attempts:
            if attempt["status"] == "dispatched":
                attempt["status"] = "interrupted_or_uncertain"
        current_used = len(_catalog_attempts(plan, plan.get("catalog"), plan.get("pass")))
        try:
            current_state = _entry_state(_current_entry(plan))
        except ValueError:
            current_state = "current"
        fragment_hash = None if fingerprints is None else fingerprints.get(shot)
        evidence, countable, deferred_records = _annotate(plan, items, fragment_hash)
        suitable = _group_options(countable)
        deferred = [_deferred_option(record) for record in deferred_records]
        reached = len(suitable) >= TARGET_OPTIONS
        outcomes = _outcome_counts(plan)
        shortfall = None if recovery_pending else _shortfall_view(plan, len(suitable), reached)
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
        if not recovery_pending and (shortfall or any(outcomes.values())):
            note = note + " " + LIMIT_NOTE
        if recovery_pending or current_state != "current":
            remaining = None if recovery_pending else 0
        else:
            remaining = max(0, QUERY_ALLOWANCE - current_used)
        result.append(
            {
                "fragment": shot,
                "pass": plan["pass"],
                "catalog": plan["catalog"],
                "reason": plan["reason"],
                "expected_material": plan["expected_material"],
                "context": plan["context"],
                "context_stale": fragment_hash != plan.get("context_hash"),
                "queries_used": None if recovery_pending else current_used,
                "queries_remaining": remaining,
                "fragment_queries_used": None if recovery_pending else len(plan["attempts"]),
                "fragment_query_limit": MAX_FRAGMENT_QUERIES,
                "keyword_search": _keyword_search(plan.get("catalog")),
                "browser_search": _browser_search(plan.get("catalog")),
                "catalog_state": current_state,
                "catalogs": _catalog_rows(plan, recovery_pending),
                "outcomes": outcomes,
                "shortfall": shortfall,
                "recovery_pending": recovery_pending,
                "attempts": attempts,
                "raw_hits": _raw_hits(plan, items, shot),
                "suitable_options": suitable,
                "suitable_count": len(suitable),
                "viewing_evidence": evidence,
                "pending_human_decisions": _pending_decisions(suitable, items),
                "deferred_options": deferred,
                "target_reached": reached,
                "next": _next_action(plan, reached, recovery_pending),
                "note": note,
            }
        )
    return result


def _target_reached(ledger, project, shot):
    return any(row["fragment"] == shot and row["target_reached"] for row in progress(ledger.data, project=project))


def _as_list(value):
    if value is None:
        return []
    if isinstance(value, str):
        return [value]
    if isinstance(value, list):
        return value
    raise ValueError("Invalid search plan arguments.")


def _plan_result(args, plan, items):
    data = {"search_plans": {args.shot: plan}, "items": items}
    return {
        "search_progress": progress(data, project=args.project),
        "dry_run": bool(getattr(args, "dry_run", False)),
        "summary": {
            "line": "Validated the fragment plan."
            if getattr(args, "dry_run", False)
            else "Saved the fragment plan with its existing query allowance."
        },
    }


def _plan_mode(args):
    advance = bool(getattr(args, "advance", False))
    done = bool(getattr(args, "no_further_catalog", False))
    because = getattr(args, "because", None)
    if advance and done:
        raise ValueError("Choose either catalog advance or a shortfall.")
    if because and not advance:
        raise ValueError("--because belongs to catalog advance.")
    if advance:
        return "advance"
    if done:
        return "shortfall"
    return "chain"


def _check_catalog(name, beat, rules):
    if name == "local":
        raise ValueError("Local files are an import route, not a search catalog.")
    capability = providers.capabilities().get(name)
    if not capability or name not in beat["allowed_sources"]:
        raise ValueError("Selected catalog must have supported discovery and be allowed for this fragment.")
    media = capability.get("media_types")
    if media is not None and not (set(media) & set(rules["asset_types"])):
        raise ValueError("Selected catalog is incompatible with project media policy.")


def _chain_entries_from_args(args, beat, rules):
    catalogs = _as_list(getattr(args, "provider", None))
    reasons = _as_list(getattr(args, "reason", None))
    materials = _as_list(getattr(args, "expected_material", None))
    if not catalogs or not reasons or not materials:
        raise ValueError("A search chain needs one to five catalogs, each with a reason and expected material.")
    if not (len(catalogs) == len(reasons) == len(materials)):
        raise ValueError("Each catalog needs one --reason and one --expected-material, in the same order.")
    if not 1 <= len(catalogs) <= MAX_CHAIN_CATALOGS:
        raise ValueError(
            "A search chain contains one to five catalogs. Two or three is usual; padding is not required."
        )
    entries = []
    for catalog, reason, material in zip(catalogs, reasons, materials, strict=True):
        if not isinstance(catalog, str) or not catalog.strip():
            raise ValueError("Each catalog in the chain needs a name.")
        if not _bounded_text(reason):
            raise ValueError("--reason must explain the catalog plan.")
        if not _bounded_text(material):
            raise ValueError("--expected-material must explain the catalog plan.")
        name = catalog.strip()
        _check_catalog(name, beat, rules)
        entries.append({"catalog": name, "reason": reason.strip(), "expected_material": material.strip()})
    if len({entry["catalog"] for entry in entries}) != len(entries):
        raise ValueError("Catalogs in one chain must be distinct.")
    return entries


def _require_saved(ledger, shot, fingerprint):
    plan = ledger.data.get("search_plans", {}).get(shot)
    if plan is None:
        raise ValueError("Save a search-plan for this fragment first.")
    if plan["context_hash"] != fingerprint:
        raise ValueError("Fragment context changed. Existing budget is preserved; review the plan before continuing.")
    return plan


def _stamp_attempts(plan):
    for attempt in plan.get("attempts") or []:
        attempt.setdefault("catalog", plan.get("catalog"))
        attempt.setdefault("pass", plan.get("pass"))


def _find_catalog(plan, name):
    for chain in plan.get("chains") or []:
        for entry in chain.get("catalogs") or []:
            if entry.get("catalog") == name:
                return chain, entry
    return None, None


def _close_current(entry, because, reason, used):
    early = because in EARLY_KINDS and used < QUERY_ALLOWANCE
    entry["state"] = "skipped" if early else "exhausted"
    entry["closed"] = {"kind": because, "reason": reason, "at": now()}


def _move_to_pending(plan, chain):
    pending = [item for item in chain["catalogs"] if item.get("state") == "pending"]
    if not pending:
        return
    pending[0]["state"] = "current"
    plan["catalog"] = pending[0]["catalog"]
    plan["reason"] = pending[0]["reason"]
    plan["expected_material"] = pending[0]["expected_material"]


def _existing_second_pass(current, entries, fingerprint):
    """Return keep, an error, or None when this pass has not been saved."""
    if current is None:
        return "Save the initial chain before an additional pass."
    if current.get("context_hash") != fingerprint:
        return PLAN_RESET_MESSAGE
    stored = _stored_identity(current, MAX_PASSES)
    if stored is None:
        return None
    if stored == _chain_identity(entries):
        return "keep"
    return PLAN_RESET_MESSAGE


def _new_second_pass_error(ledger, args, current, entries):
    if _target_reached(ledger, args.project, args.shot):
        return TARGET_REACHED_MESSAGE
    if current.get("shortfall"):
        return "A recorded shortfall closes the search. Another pass cannot refresh the budget."
    if current.get("pass") != 1 or not _pass_exhausted(current):
        return "Finish or skip the initial chain before planning another pass."
    unresolved = _unassessed_exit(current)
    if unresolved:
        return unresolved
    used = set(_plan_catalogs(current))
    if any(entry["catalog"] in used for entry in entries):
        return "The additional pass must use other catalogs. Repeating a catalog does not replenish its allowance."
    return None


def _save_second_pass(ledger, args, current, entries, fingerprint):
    existing = _existing_second_pass(current, entries, fingerprint)
    if existing == "keep":
        return _plan_result(args, current, ledger.data.get("items", []))
    if existing:
        raise ValueError(existing)
    blocked = _new_second_pass_error(ledger, args, current, entries)
    if blocked:
        raise ValueError(blocked)
    working = copy.deepcopy(current) if args.dry_run else current
    _stamp_attempts(working)
    _ensure_chains(working)
    for entry in _active_chain(working)["catalogs"]:
        if entry.get("state") == "current":
            entry["state"] = "exhausted"
    for index, entry in enumerate(entries):
        entry["state"] = "current" if index == 0 else "pending"
    working["chains"].append({"pass": MAX_PASSES, "catalogs": entries})
    working["pass"] = MAX_PASSES
    working["catalog"] = entries[0]["catalog"]
    working["reason"] = entries[0]["reason"]
    working["expected_material"] = entries[0]["expected_material"]
    if not args.dry_run:
        ledger.save("search-plan-pass-2")
    return _plan_result(args, working, ledger.data.get("items", []))


def _save_chain(ledger, args, rules, prepared):
    beat, context, fingerprint = prepared
    search_pass = getattr(args, "search_pass", None) or 1
    if search_pass not in (1, MAX_PASSES):
        raise ValueError("A fragment has at most two search passes.")
    entries = _chain_entries_from_args(args, beat, rules)
    current = ledger.data.get("search_plans", {}).get(args.shot)
    if search_pass == MAX_PASSES:
        return _save_second_pass(ledger, args, current, entries, fingerprint)
    if current:
        same = _stored_identity(current, 1) == _chain_identity(entries) and current.get("context_hash") == fingerprint
        if same:
            return _plan_result(args, current, ledger.data.get("items", []))
        raise ValueError(PLAN_RESET_MESSAGE)
    for index, entry in enumerate(entries):
        entry["state"] = "current" if index == 0 else "pending"
    proposed = {
        "pass": 1,
        "catalog": entries[0]["catalog"],
        "reason": entries[0]["reason"],
        "expected_material": entries[0]["expected_material"],
        "context": context,
        "context_hash": fingerprint,
        "attempts": [],
        "chains": [{"pass": 1, "catalogs": entries}],
    }
    if not args.dry_run:
        ledger.data.setdefault("search_plans", {})[args.shot] = proposed
        ledger.save("search-plan")
    return _plan_result(args, proposed, ledger.data.get("items", []))


def _one_text(value, flag):
    values = _as_list(value)
    if len(values) != 1 or not _bounded_text(values[0]):
        raise ValueError(f"{flag} must explain this action.")
    return values[0].strip()


def _reject_closed_search(ledger, args, plan):
    if _target_reached(ledger, args.project, args.shot):
        raise ValueError(TARGET_REACHED_MESSAGE)
    if plan.get("shortfall"):
        raise ValueError("Search is already closed by a shortfall. Advancing cannot refresh the budget.")


def _advance_request(args):
    because = getattr(args, "because", None)
    if because not in BECAUSE_KINDS:
        raise ValueError(
            "--because must be allowance-exhausted, unavailable-access, unsuitable-source, or route-unimplemented."
        )
    if getattr(args, "expected_material", None):
        raise ValueError("Catalog advance does not take expected material.")
    catalogs = _as_list(getattr(args, "provider", None))
    if len(catalogs) != 1 or not isinstance(catalogs[0], str) or not catalogs[0].strip():
        raise ValueError("Name the one catalog being closed with --provider.")
    return catalogs[0].strip(), because, _one_text(getattr(args, "reason", None), "--reason")


def _advance_entry(working, name, because, reason):
    """Return the open catalog entry, or None when this exact advance was already saved."""
    chain, entry = _find_catalog(working, name)
    if chain is None or entry is None:
        raise ValueError("That catalog is not in this fragment's saved chains.")
    if entry.get("state") in ("exhausted", "skipped"):
        closed = entry.get("closed") or {}
        if closed.get("kind") == because and closed.get("reason") == reason:
            return None
        raise ValueError("That catalog is already closed. A repeated advance cannot rewrite its history.")
    current = chain.get("pass") == working.get("pass") and entry.get("catalog") == working.get("catalog")
    if not current or entry.get("state") != "current":
        raise ValueError("Advance the current catalog. A later catalog cannot be skipped ahead of it.")
    unresolved = _unassessed_exit(working)
    if unresolved:
        raise ValueError(unresolved)
    return entry


def _reject_advance_reason(name, because, used):
    if because == "allowance-exhausted" and used < QUERY_ALLOWANCE:
        raise ValueError(
            "This catalog still has query allowance. Early advance needs unavailable access, an unsuitable source, "
            "or an unimplemented route."
        )
    if because == "route-unimplemented" and (_keyword_search(name) or _browser_search(name)):
        raise ValueError("This catalog has an implemented search route. Use a query or a different advance reason.")


def _advance(ledger, args, fingerprint):
    plan = _require_saved(ledger, args.shot, fingerprint)
    _reject_closed_search(ledger, args, plan)
    name, because, reason = _advance_request(args)
    working = copy.deepcopy(plan) if args.dry_run else plan
    _stamp_attempts(working)
    _ensure_chains(working)
    entry = _advance_entry(working, name, because, reason)
    if entry is None:
        return _plan_result(args, plan, ledger.data.get("items", []))
    used = len(_catalog_attempts(working, name, working["pass"]))
    _reject_advance_reason(name, because, used)
    _close_current(entry, because, reason, used)
    _move_to_pending(working, _active_chain(working))
    if not args.dry_run:
        ledger.save("search-advance")
    return _plan_result(args, working, ledger.data.get("items", []))


def _record_shortfall(ledger, args, fingerprint):
    plan = _require_saved(ledger, args.shot, fingerprint)
    if _target_reached(ledger, args.project, args.shot):
        raise ValueError(TARGET_REACHED_MESSAGE)
    if (
        getattr(args, "provider", None)
        or getattr(args, "expected_material", None)
        or getattr(args, "search_pass", None)
    ):
        raise ValueError("A shortfall records why the search stops. It does not start another chain.")
    reason = _one_text(getattr(args, "reason", None), "--reason")
    if not _pass_exhausted(plan):
        raise ValueError("Finish or skip the planned catalogs before recording a shortfall.")
    kind = "passes-exhausted" if plan.get("pass") == MAX_PASSES else "no-further-catalog"
    stored = plan.get("shortfall")
    if isinstance(stored, dict):
        if stored.get("kind") == kind and stored.get("reason") == reason:
            return _plan_result(args, plan, ledger.data.get("items", []))
        raise ValueError("A shortfall is already recorded. Repeating it cannot reset the budget or erase attempts.")
    unresolved = _unassessed_exit(plan)
    if unresolved:
        raise ValueError(unresolved)
    working = copy.deepcopy(plan) if args.dry_run else plan
    working["shortfall"] = {"kind": kind, "reason": reason, "at": now()}
    if not args.dry_run:
        ledger.save("search-shortfall")
    return _plan_result(args, working, ledger.data.get("items", []))


def plan_command(ledger, args, rules):
    beat, context, fingerprint = _fragment(args.project, args.shot, rules)
    mode = _plan_mode(args)
    if mode == "advance":
        return _advance(ledger, args, fingerprint)
    if mode == "shortfall":
        return _record_shortfall(ledger, args, fingerprint)
    return _save_chain(ledger, args, rules, (beat, context, fingerprint))


def assess_command(ledger, args, rules):
    _, _, fingerprint = _fragment(args.project, args.shot, rules)
    plan = ledger.data.get("search_plans", {}).get(args.shot)
    if plan is None or plan["context_hash"] != fingerprint:
        raise ValueError("Assessment requires an existing plan with unchanged fragment context.")
    selected = getattr(args, "provider", None)
    matching = [
        attempt
        for attempt in plan["attempts"]
        if " ".join(attempt["query"].split()).casefold() == " ".join(args.query.split()).casefold()
        and (args.media is None or attempt.get("media", "any") == args.media)
        and (selected in (None, "") or _attempt_catalog(plan, attempt) == selected)
    ]
    if getattr(args, "catalog_filter", None) is not None:
        from .catalogs import filters

        selected_filters = filters(selected or plan["catalog"], args.catalog_filter)
        matching = [attempt for attempt in matching if attempt.get("catalog_filters", {}) == selected_filters]
    if len(matching) != 1 or not str(getattr(args, "assessment", "") or "").strip():
        raise ValueError(
            "Assessment requires one recorded query and a nonempty explanation; "
            "use --media, --provider or --catalog-filter to distinguish repeated wording."
        )
    attempt = matching[0]
    coverage = getattr(args, "coverage", None)
    if coverage is not None:
        if coverage not in COVERAGE_VALUES:
            raise ValueError("--coverage must be incomplete or assessed.")
        if coverage == "incomplete" and attempt.get("status") not in ("empty", "results"):
            raise ValueError(
                "Incomplete coverage applies to returned or empty results. Access failures stay access failures."
            )
        attempt["coverage"] = coverage
    attempt.update(assessment=args.assessment.strip(), assessed_at=now())
    ledger.save("search-assessment")
    return {
        "search_progress": progress(ledger.data, project=args.project),
        "summary": {"line": "Recorded the query assessment; visual suitability and human approval remain separate."},
    }


def attach_fragment_context(ledger, args, rules, row):
    """An explicit file selection from a catalog in this fragment retains its saved narration."""
    plan = ledger.data.get("search_plans", {}).get(args.shot)
    if plan and row["provider"] in set(_plan_catalogs(plan)):
        _, _, fingerprint = _fragment(args.project, args.shot, rules)
        if plan["context_hash"] != fingerprint:
            raise ValueError("Fragment context changed; review the saved plan before selecting another file.")
        row["narration"] = plan["context"]["narration"]


def _annotate_dispatch(row, plan):
    """Keep a stock hit illustrative. Other catalogs keep the fragment intent."""
    from .commands import _search_annotation

    annotation = _search_annotation(row.get("provider"), plan["context"]["intent"])
    if annotation.get("stock"):
        row.update(annotation)
        return
    row["match"] = {"kind": plan["context"]["intent"], "reason": "Search hit; visual confirmation required."}


def _query_key(query, media, catalog_filters=None, catalog=None):
    if catalog == "mapillary":
        query = "geographic image search"
    key = " ".join(query.split()).casefold() + " [" + media + "]"
    return key + (" " + json.dumps(catalog_filters, sort_keys=True) if catalog_filters else "")


def _allowance_error(plan):
    message = ALLOWANCE_MESSAGE
    if _pending_entries(plan):
        return message + " Advance the saved chain to use the next catalog."
    if plan.get("pass") == 1 and not _has_pass(plan, 2):
        return message + " Plan one additional chain or record the shortfall."
    return message + " No further pass is available."


def _refuse_new_dispatch(ledger, plan, args, browser=False):
    if _target_reached(ledger, args.project, args.shot):
        raise ValueError(TARGET_REACHED_MESSAGE)
    if plan.get("shortfall"):
        raise ValueError(
            "Search is closed after the recorded shortfall. No additional query is dispatched. " + LIMIT_NOTE
        )
    entry = _current_entry(plan)
    if _entry_state(entry) != "current":
        raise ValueError("This catalog is closed. Plan the additional pass or record the shortfall.")
    if browser and not _browser_search(plan["catalog"]):
        raise ValueError("This catalog does not use the supported browser search/import route.")
    if not browser and not _keyword_search(plan["catalog"]):
        raise ValueError(ROUTE_UNIMPLEMENTED)
    if len(_catalog_attempts(plan, plan["catalog"], plan["pass"])) >= QUERY_ALLOWANCE:
        raise ValueError(_allowance_error(plan))
    if _needs_assessment(plan, plan["catalog"], plan["pass"]):
        raise ValueError("Assess prior results or the interrupted attempt with search-assess before another query.")


def reserve_attempt(ledger, plan, args, query, browser=False):
    from .catalogs import filters

    selected_filters = filters(plan["catalog"], getattr(args, "catalog_filter", None), getattr(args, "language", None))
    key = _query_key(query, args.media, selected_filters, plan["catalog"])
    existing = next(
        (attempt for attempt in _catalog_attempts(plan, plan["catalog"], plan["pass"]) if attempt["query_key"] == key),
        None,
    )
    if existing:
        return existing, True
    _refuse_new_dispatch(ledger, plan, args, browser=browser)
    attempt = {
        "query": query,
        "query_key": key,
        "language": args.language,
        "media": args.media,
        "catalog": plan["catalog"],
        "pass": plan["pass"],
        "at": now(),
        "status": "dispatched",
        "candidates": [],
        "catalog_filters": selected_filters,
    }
    if browser:
        attempt["route"] = "browser"
        attempt["id"] = hashlib.sha256(
            json.dumps([args.shot, plan["catalog"], plan["pass"], key]).encode()
        ).hexdigest()[:20]
    if getattr(args, "dry_run", False):
        return attempt, False
    plan["attempts"].append(attempt)
    ledger.save("search-dispatch")
    return attempt, False


def _dispatch(ledger, plan, args, rules, query):  # noqa: C901 - persisted dispatch, Telegram continuation and completed X recovery
    attempt, replayed = reserve_attempt(ledger, plan, args, query)
    resume_x = False
    if replayed and plan["catalog"] == "x" and attempt["status"] == "dispatched":
        from .grok_oauth import saved_result

        resume_x = (
            saved_result(
                ledger,
                query,
                args.media,
                attempt["catalog_filters"],
                language=args.language,
                context={"shot": args.shot, "pass": plan["pass"], "query_key": attempt["query_key"]},
            )
            is not None
        )
    if replayed and not resume_x and not (plan["catalog"] == "telegram" and getattr(args, "resume_history", False)):
        return attempt, True
    if replayed:
        entry = _current_entry(plan)
        if (
            _target_reached(ledger, args.project, args.shot)
            or plan.get("shortfall")
            or _entry_state(entry) != "current"
        ):
            raise ValueError(
                "The fragment/catalog is closed; Telegram history cannot continue after closure or target completion."
            )
    selected_filters = attempt["catalog_filters"]
    try:
        rows = providers.search(
            plan["catalog"],
            query,
            args.limit,
            media=args.media,
            **({"catalog_filters": args.catalog_filter} if selected_filters else {}),
            **({"language": args.language} if plan["catalog"] in ("un_webtv", "x", "suspilne") else {}),
            **(
                {
                    "ledger": ledger,
                    "resume_history": getattr(args, "resume_history", False),
                    "search_context": {"shot": args.shot, "pass": plan["pass"], "query_key": attempt["query_key"]},
                }
                if plan["catalog"] in ("telegram", "x")
                else {}
            ),
        )
    except (ValueError, OSError) as error:
        attempt.update(status="access_or_provider_error", outcome="access_failure", error=redact(error))
        if isinstance(error, BrowserVerificationError):
            attempt["error_code"] = error.error_code
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
        _annotate_dispatch(row, plan)
        added.append(ledger.add(row))
    attempt.update(
        status="results" if added else "empty",
        outcome="results" if added else "empty_results",
        candidates=[row["id"] for row in added],
        returned_count=len(rows),
        excluded_count=len(rows) - len(added),
        assessed_at=None,
    )
    if plan["catalog"] == "un_webtv":
        # The same video can match different localized speech; retain each query's
        # evidence without replacing its existing media/review candidate.
        attempt["source_matches"] = [
            {
                "source_id": row["source_id"],
                "source_url": row["source_url"],
                "language": row["catalog"]["language"],
                "matches": row["catalog"]["matches"],
                "transcript_url": row["catalog"]["transcript_url"],
            }
            for row in rows
            if allowed(row, rules)
        ]
    ledger.save_many("search-outcome", added)
    if plan["catalog"] == "telegram":
        attempt["coverage"] = "incomplete"
        attempt["history_progress"] = [row["catalog"]["history_progress"] for row in rows]
        ledger.save("search-outcome")
    return attempt, replayed


def _planned_dry_run(ledger, plan, args):
    """Validate a prospective dispatch without contacting the catalog or spending a query."""
    from .catalogs import filters

    query_key = _query_key(
        args.query,
        args.media,
        filters(plan["catalog"], getattr(args, "catalog_filter", None), getattr(args, "language", None)),
        plan["catalog"],
    )
    replayed = any(
        attempt["query_key"] == query_key for attempt in _catalog_attempts(plan, plan["catalog"], plan["pass"])
    )
    unimplemented = (
        not replayed
        and not _keyword_search(plan["catalog"])
        and not plan.get("shortfall")
        and _entry_state(_current_entry(plan)) == "current"
        and not _target_reached(ledger, args.project, args.shot)
    )
    if unimplemented:
        return {
            "items": [],
            "dry_run": True,
            "replayed": False,
            "would_dispatch": None,
            "limitation": "route_unimplemented",
            "summary": {
                "line": (
                    "No keyword-search route is implemented for this catalog. "
                    "Dry-run did not invent a query or a browser search."
                )
            },
            "search_progress": progress(ledger.data, project=args.project),
        }
    if not replayed:
        _refuse_new_dispatch(ledger, plan, args)
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
    if getattr(args, "resume_history", False) and (plan["catalog"] != "telegram" or args.dry_run):
        raise ValueError("--resume-history requires the saved Telegram catalog and cannot be combined with --dry-run.")
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
        room = len(_catalog_attempts(plan, plan["catalog"], plan["pass"])) < QUERY_ALLOWANCE
        if shorter != args.query.strip() and room and not _target_reached(ledger, args.project, args.shot):
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
