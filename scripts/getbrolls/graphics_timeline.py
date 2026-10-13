"""A bounded chronology for one narration occurrence, never a montage editor."""

from __future__ import annotations

import copy
import math

from .graphics_facts import facts_readiness

MAX_MILESTONES = 6
FIRST_PRINTABLE = 32
TITLE_LIMIT = 90
DATE_LIMITS = {1: 60, 2: 60, 3: 30, 4: 20, 5: 20, 6: 20}
LABEL_LIMITS = {1: 120, 2: 120, 3: 80, 4: 80, 5: 50, 6: 50}


def validate_timeline(record):
    if not isinstance(record, dict) or type(record.get("schema_version")) is not int or record["schema_version"] != 1:
        raise ValueError("Timeline schema_version must be the integer 1.")
    if set(record) != {"schema_version", "title", "milestones"}:
        raise ValueError("Timeline accepts only schema_version, title and milestones.")
    _text(record["title"], TITLE_LIMIT)
    milestones = record["milestones"]
    if not isinstance(milestones, list) or not 1 <= len(milestones) <= MAX_MILESTONES:
        raise ValueError("A timeline needs one to six legible milestones per occurrence.")
    seen = set()
    previous = -1.0
    for item in milestones:
        if not isinstance(item, dict) or set(item) != {"id", "date", "label", "fact_id", "at_s"}:
            raise ValueError("Each milestone needs id, date, label, fact_id and explicit at_s (or null).")
        for key, limit in (
            ("id", 80),
            ("date", DATE_LIMITS[len(milestones)]),
            ("label", LABEL_LIMITS[len(milestones)]),
            ("fact_id", 80),
        ):
            _text(item[key], limit)
        if item["id"] in seen:
            raise ValueError("Timeline milestone ids must be unique.")
        seen.add(item["id"])
        stamp = item["at_s"]
        if stamp is not None:
            if type(stamp) not in (int, float) or not math.isfinite(stamp) or stamp < 0 or stamp <= previous:
                raise ValueError("Timeline emphasis times must be finite, distinct and in narration order.")
            previous = stamp
    return record


def _text(value, limit):
    if (
        not isinstance(value, str)
        or not value.strip()
        or len(value) > limit
        or any(ord(c) < FIRST_PRINTABLE for c in value)
    ):
        raise ValueError("Timeline text must be bounded nonempty single-line text.")


def normalize_timeline(payload, timing):
    record = copy.deepcopy(payload)
    validate_timeline(record)
    errors = timing_reasons(record, timing)
    if errors:
        raise ValueError("; ".join(errors))
    return record


def timing_reasons(record, timing):
    reasons = []
    explicit = timing.get("basis") == "explicit"
    timed = False
    for item in record["milestones"]:
        stamp = item["at_s"]
        if stamp is None:
            continue
        timed = True
        if not explicit or not timing["start_s"] <= stamp < timing["end_s"]:
            reasons.append("Timeline " + item["id"] + " emphasis is outside this occurrence's narration interval.")
    if explicit and not timed:
        reasons.append("An explicitly timed timeline needs at least one narration-clock emphasis.")
    return reasons


def timeline_readiness(root, occurrence):
    record = occurrence.get("timeline")
    if record is None:
        return ["timeline_missing"] if occurrence.get("template") == "timeline" else []
    reasons = timing_reasons(record, occurrence["timing"])
    if occurrence["props"]["claim_status"] == "synthetic":
        return reasons
    facts = occurrence.get("facts")
    if not isinstance(facts, dict) or not facts_readiness(root, facts)["ready"]:
        return [*reasons, "timeline_facts_not_ready"]
    values = {item["id"]: item for item in facts["values"]}
    for milestone in record["milestones"]:
        fact = values.get(milestone["fact_id"])
        if not fact or fact["value"] != milestone["date"] or fact["definition"] != milestone["label"]:
            reasons.append("timeline_fact_mismatch:" + milestone["id"])
    return reasons


def clip_milestones(record, timing, fps, to_frame):
    """Dates have no invented duration. Only explicitly narrated instants get emphasis."""
    return [
        {
            **copy.deepcopy(item),
            "at_frame": (
                None
                if item["at_s"] is None
                else min(timing["duration_in_frames"] - 1, to_frame(item["at_s"], fps) - timing["start_frame"])
            ),
        }
        for item in record["milestones"]
    ]
