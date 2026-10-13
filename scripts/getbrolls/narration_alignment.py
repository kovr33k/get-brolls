"""Pure narration matching, bounded correction and readiness for graphics occurrences.

Standard library only. Callers persist the returned records; this module never
writes files, contacts HTTP/STT, imports graphics.py/narration.py, or copies a
provider confidence field.

Conservative auto-resolution (documented rule, not a confidence):
A passage becomes state=resolved only when every condition holds:
1. Saved result.timing_resolved is True and every word timestamp is finite,
   non-boolean, ordered, and inside the recording.
2. Candidate search finished without truncation. A bounded search that stopped
   early cannot prove uniqueness.
3. Textual coverage of the original passage tokens is at least AUTO_TEXTUAL.
4. Uniqueness is proven: exactly one such span, or several repeats of the same
   normalized text where neighboring/anchor tokens uniquely identify one span.
   The first of several equal hits is never selected because it is first.
5. No still-plausible high-coverage rival from another passage overlaps that
   span. An ambiguous peer keeps every high-coverage alternative. A peer with
   unique, nontruncated, anchor-supported evidence may drop unselected repeats
   of that same text. First-hit or score ranking never discards a rival.
6. The span is order-consistent with tentatively unique neighbors. Unique but
   reordered speech stays uncertain rather than being squeezed into narrative
   chronology.

Matching score is a local weighted evidence ratio in [0, 1] for ranking review
candidates. It is not Inworld confidence and is not a probability of truth.

transcript_sha256 is the SHA-256 of the complete recognized result: original
transcript text, each word's original text/start_ms/end_ms/segment,
artifact_sha256, and the exact boolean timing_resolved. It is not a hash of
transcript text alone. Scenario copy lives in scenario_sha256, so a script
edit keeps this identity and does not require paid retranscription.
"""

from __future__ import annotations

import copy
import hashlib
import json
import math
import re
import unicodedata
from itertools import pairwise
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from typing import TypeGuard

SCHEMA_VERSION = 1
FRAME_ROUNDING = "half_up_nonnegative"
STATES = ("resolved", "uncertain", "missing", "stale")
MAX_TEXT = 8000
MAX_BY = 500
MAX_ANCHOR_TEXT = 500
MAX_CANDIDATES = 8
MAX_ANCHOR_HITS = 24
MAX_GAP = 4
ANCHOR_WINDOW = 24
MIN_DISAMBIGUATION_CANDIDATES = 2
MIN_TEXTUAL = 0.55
AUTO_TEXTUAL = 0.92
TEXTUAL_WEIGHT = 0.6
ANCHOR_WEIGHT = 0.25
ORDER_WEIGHT = 0.15
ID_RE = re.compile(r"[A-Za-z0-9_-]{1,80}$")
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_WINDOWS_RESERVED = re.compile(r"^(?:con|prn|aux|nul|com[1-9]|lpt[1-9])$", re.IGNORECASE)
_PROSE_CONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
RECORD_KEYS = (
    "schema_version",
    "occurrence_id",
    "original_text",
    "context",
    "analysis_id",
    "recording_id",
    "recording_sha256",
    "recording_duration_s",
    "transcript_sha256",
    "scenario_sha256",
    "order",
    "input_fingerprint",
    "fps",
    "frame_rounding",
    "search_truncated",
    "state",
    "candidates",
    "selected_candidate_id",
    "timing",
    "decision",
)
CANDIDATE_KEYS = (
    "id",
    "start_s",
    "end_s",
    "recognized_text",
    "word_start",
    "word_end",
    "textual_evidence",
    "anchor_evidence",
    "order_evidence",
    "score",
)
TEXTUAL_KEYS = ("matched_tokens", "passage_tokens", "span_tokens", "coverage")
ANCHOR_KEYS = ("before_hits", "after_hits", "anchor_tokens", "disambiguates")
ORDER_KEYS = ("narrative_order", "consistent", "inverted")
TIMING_KEYS = ("basis", "start_s", "end_s", "start_frame", "end_frame", "duration_in_frames", "duration_s")
DECISION_KEYS = ("by", "statement", "at", "input_fingerprint")
READINESS_REASONS = (
    "invalid_timing",
    "stale_recording",
    "stale_analysis",
    "stale_transcript",
    "stale_scenario",
    "stale_profile",
    "stale_correction",
    "incomplete_transcript",
    "search_truncated",
    "missing_match",
    "uncertain_match",
    "unresolved_match",
)
PRESERVE = (
    "Invalid narration alignment records. Preserve the project files and restore a valid copy; history was not reset."
)


def seconds_to_frame(seconds, fps):
    """Non-negative half-up: frame = floor(t * fps + 0.5). Error is at most one frame."""
    if not isinstance(seconds, (int, float)) or isinstance(seconds, bool) or not math.isfinite(seconds) or seconds < 0:
        raise ValueError("Timing values must be finite seconds greater than or equal to 0.")
    if not isinstance(fps, (int, float)) or isinstance(fps, bool) or not math.isfinite(fps) or fps <= 0:
        raise ValueError("Profile fps must be a finite number greater than 0.")
    return math.floor(float(seconds) * float(fps) + 0.5)


def match_passages(  # noqa: PLR0913 - frozen caller seam: result plus recording/analysis identity
    result,
    passages,
    *,
    analysis_id,
    recording_id,
    recording_sha256,
    recording_duration_s,
    fps,
):
    """Match ordered scenario passages to a saved word-timed transcript. No I/O."""
    result_view = _result_view(result)
    duration_s = _positive_number(recording_duration_s, "recording_duration_s")
    fps_value = _positive_number(fps, "fps")
    analysis = _id(analysis_id, "analysis_id")
    recording = _id(recording_id, "recording_id")
    rec_sha = _sha256_hex(recording_sha256, "recording_sha256")
    parsed = _parse_passages(passages)
    words = result_view["words"]
    stream = _token_stream(words)
    timing_ok = result_view["timing_resolved"] is True and _words_coherent(words, duration_s)
    transcript_sha = _recognized_result_sha256(result_view)
    prepared = []
    for item in parsed:
        found, truncated = _locate_spans(stream, item["tokens"])
        candidates = _span_candidates(found, words, item, duration_s)
        prepared.append({**item, "raw_candidates": candidates, "search_truncated": truncated})
    _apply_neighbor_evidence(prepared, words)
    chosen = _choose_unique(prepared, timing_ok)
    records = {}
    for item in prepared:
        records[item["occurrence_id"]] = _build_record(
            item,
            chosen.get(item["occurrence_id"]),
            analysis_id=analysis,
            recording_id=recording,
            recording_sha256=rec_sha,
            recording_duration_s=duration_s,
            transcript_sha256=transcript_sha,
            fps=fps_value,
            stream=stream,
        )
    return records


def validate_match(record):
    """Structural saved-record validation with no file reads."""
    try:
        _validate_record(record)
    except (ValueError, TypeError, KeyError):
        raise ValueError(PRESERVE) from None


def correct_match(  # noqa: PLR0913 - frozen correction seam binds actor, seconds and fingerprints
    record, *, candidate_id=None, start_s=None, end_s=None, by, statement, at
):
    """Return a new record with an explicit candidate or bounded time override."""
    validate_match(record)
    if candidate_id is not None and (start_s is not None or end_s is not None):
        raise ValueError("Correction is a candidate confirmation or a time override, not both.")
    actor = _required_prose(by, "Correction actor", MAX_BY)
    text = _required_prose(statement, "Correction statement")
    when = _required_prose(at, "Correction time")
    updated = copy.deepcopy(record)
    if candidate_id is not None:
        selected = _candidate_by_id(updated["candidates"], candidate_id)
        timing = _explicit_timing(selected["start_s"], selected["end_s"], updated["fps"])
        updated["selected_candidate_id"] = selected["id"]
    elif start_s is not None and end_s is not None:
        _bounds_in_recording(start_s, end_s, updated["recording_duration_s"])
        timing = _explicit_timing(start_s, end_s, updated["fps"])
        updated["selected_candidate_id"] = None
    else:
        raise ValueError("Correction needs a candidate_id or bounded start_s and end_s.")
    updated["timing"] = timing
    updated["state"] = "resolved"
    updated["decision"] = {
        "by": actor,
        "statement": text,
        "at": when,
        "input_fingerprint": updated["input_fingerprint"],
    }
    validate_match(updated)
    return updated


def alignment_readiness(record, *, analysis, recording, passage, profile):
    """Compare current identities to a saved match. No writes. Timing is None unless resolved."""
    validate_match(record)
    reasons = _readiness_reasons(record, analysis, recording, passage, profile)
    resolved = not reasons
    timing = copy.deepcopy(record["timing"]) if resolved else None
    return {"reasons": reasons, "resolved": resolved, "timing": timing}


def _is_int(value) -> TypeGuard[int]:
    return type(value) is int


def _is_number(value) -> TypeGuard[int | float]:
    return type(value) in (int, float) and not isinstance(value, bool) and math.isfinite(value)


def _positive_number(value, flag):
    if not _is_number(value) or value <= 0:
        raise ValueError(flag + " must be a finite number greater than 0.")
    return float(value)


def _non_negative_number(value, flag):
    if not _is_number(value) or value < 0:
        raise ValueError(flag + " must be a finite number greater than or equal to 0.")
    return float(value)


def _valid_id(value):
    return isinstance(value, str) and bool(ID_RE.fullmatch(value)) and not _WINDOWS_RESERVED.fullmatch(value)


def _id(value, flag):
    if not _valid_id(value):
        raise ValueError(flag + " must be a stable id of 1-80 letters, digits, _ or -.")
    return value


def _sha256_hex(value, flag):
    if not (isinstance(value, str) and SHA256_RE.fullmatch(value)):
        raise ValueError(flag + " must be a 64-character lowercase hex digest.")
    return value


def _identity_ms(value):
    if type(value) is bool:
        return {"kind": "bool", "value": value}
    if _is_number(value):
        return {"kind": "ms", "value": float(value)}
    if isinstance(value, float) and math.isnan(value):
        return {"kind": "nan"}
    if isinstance(value, float) and math.isinf(value):
        return {"kind": "inf", "sign": int(math.copysign(1, value))}
    return {"kind": "other", "value": repr(value)}


def _recognized_result_payload(view):
    return {
        "artifact_sha256": view["artifact_sha256"],
        "timing_resolved": view["timing_resolved"] is True,
        "transcript": view["transcript"],
        "words": [
            {
                "end_ms": _identity_ms(word["end_ms"]),
                "segment": word["segment"],
                "start_ms": _identity_ms(word["start_ms"]),
                "word": word["word"],
            }
            for word in view["words"]
        ],
    }


def _recognized_result_sha256(view):
    """Identity of the complete recognized result, stored as transcript_sha256."""
    return _digest(_recognized_result_payload(view))


def _digest(payload):
    encoded = json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


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


def _normalize_copy(text):
    nfkc = unicodedata.normalize("NFKC", text).casefold().replace("ё", "е")
    chars = [char if char.isalnum() or char.isspace() else " " for char in nfkc]
    return " ".join("".join(chars).split())


def _tokens(text):
    normalized = _normalize_copy(text)
    return normalized.split() if normalized else []


def _result_view(result):
    if not isinstance(result, dict):
        raise ValueError("Narration result must be a JSON object.")
    transcript = result.get("transcript")
    if not isinstance(transcript, str):
        raise ValueError("Narration result must keep the original transcript text.")
    if _PROSE_CONTROL.search(transcript):
        raise ValueError("Transcript text must not contain control characters.")
    timing_resolved = result.get("timing_resolved")
    if type(timing_resolved) is not bool:
        raise ValueError("timing_resolved must be a boolean.")
    artifact = _sha256_hex(result.get("artifact_sha256"), "artifact_sha256")
    words = result.get("words")
    if not isinstance(words, list):
        raise ValueError("Narration result words must be an array.")
    parsed_words = [_parse_word(item, index) for index, item in enumerate(words)]
    return {
        "transcript": transcript,
        "words": parsed_words,
        "artifact_sha256": artifact,
        "timing_resolved": timing_resolved,
    }


def _try_result_view(result):
    try:
        return _result_view(result)
    except (ValueError, TypeError, KeyError):
        return None


def _parse_word(item, index):
    if not isinstance(item, dict):
        raise ValueError("Each transcript word must be an object.")
    original = item.get("word")
    if not isinstance(original, str):
        raise ValueError("Each transcript word must keep the original recognized text.")
    if _PROSE_CONTROL.search(original):
        raise ValueError("Recognized words must not contain control characters.")
    segment = item.get("segment")
    if not _is_int(segment) or segment < 0:
        raise ValueError("Word segment must be a non-negative integer.")
    start_ms = item.get("start_ms")
    end_ms = item.get("end_ms")
    times_ok = _is_number(start_ms) and _is_number(end_ms) and start_ms >= 0 and end_ms >= start_ms
    return {
        "index": index,
        "word": original,
        "tokens": _tokens(original),
        "start_ms": start_ms,
        "end_ms": end_ms,
        "segment": segment,
        "times_ok": times_ok,
    }


def _words_coherent(words, duration_s):
    if not words:
        return False
    limit_ms = duration_s * 1000.0
    if not math.isfinite(limit_ms) or limit_ms <= 0:
        return False
    previous_start = None
    previous_end = None
    for word in words:
        if not word["times_ok"]:
            return False
        start = word["start_ms"]
        end = word["end_ms"]
        went_backwards = (previous_start is not None and start < previous_start) or (
            previous_end is not None and end < previous_end
        )
        if start > limit_ms or end > limit_ms or went_backwards:
            return False
        previous_start = start
        previous_end = end
    return True


def _parse_passages(passages):
    if not isinstance(passages, list):
        raise ValueError("Passages must be an array in explicit narrative order.")
    parsed = []
    seen = set()
    for order, raw in enumerate(passages):
        item = _parse_passage(raw, order)
        occ = item["occurrence_id"]
        if occ in seen:
            raise ValueError("Passage occurrence_id cannot repeat: " + occ)
        seen.add(occ)
        parsed.append(item)
    return parsed


def _parse_passage(raw, order):
    if not isinstance(raw, dict):
        raise ValueError("Each passage must be an object.")
    occ = _id(raw.get("occurrence_id"), "occurrence_id")
    narration = _required_prose(raw.get("narration"), "passage narration")
    context = _optional_prose(raw.get("chapter_context"), "chapter_context")
    anchors = _parse_anchors(raw.get("anchors"))
    tokens = _tokens(narration)
    if not tokens:
        raise ValueError("Passage narration must contain letters or digits after normalization.")
    return {
        "occurrence_id": occ,
        "narration": narration,
        "chapter_context": context,
        "anchors": anchors,
        "tokens": tokens,
        "normalized": _normalize_copy(narration),
        "order": order,
    }


def _parse_anchors(value):
    if value is None:
        return []
    if not isinstance(value, list):
        raise ValueError("Passage anchors must be an array.")
    anchors = []
    for item in value:
        if not isinstance(item, dict):
            raise ValueError("Each anchor must be an object with original text.")
        text = _required_prose(item.get("text"), "anchor text", MAX_ANCHOR_TEXT)
        stamp = item.get("t_s")
        if stamp is not None and not _is_number(stamp):
            raise ValueError("Anchor t_s must be finite seconds or null.")
        anchors.append({"text": text, "t_s": None if stamp is None else float(stamp)})
    return anchors


def _token_stream(words):
    stream = []
    for word in words:
        stream.extend((token, word["index"]) for token in word["tokens"])
    return stream


def _token_counts(stream):
    counts = {}
    for token, _index in stream:
        counts[token] = counts.get(token, 0) + 1
    return counts


def _rarest_index(tokens, counts):
    best_i = 0
    best = (counts.get(tokens[0], 0), -len(tokens[0]), 0)
    for index, token in enumerate(tokens):
        key = (counts.get(token, 0), -len(token), index)
        if key < best:
            best = key
            best_i = index
    return best_i


def _find_forward(stream, token, start, limit):
    end = min(len(stream), limit)
    for index in range(start, end):
        if stream[index][0] == token:
            return index
    return None


def _find_backward(stream, token, start, stop):
    for index in range(stop - 1, start - 1, -1):
        if stream[index][0] == token:
            return index
    return None


def _align_around(stream, tokens, rare_i, pos):
    matched = [pos] * len(tokens)
    cursor = pos + 1
    for index in range(rare_i + 1, len(tokens)):
        hit = _find_forward(stream, tokens[index], cursor, cursor + MAX_GAP + 1)
        if hit is None:
            return None
        matched[index] = hit
        cursor = hit + 1
    cursor = pos - 1
    for index in range(rare_i - 1, -1, -1):
        start = max(0, cursor - MAX_GAP)
        hit = _find_backward(stream, tokens[index], start, cursor + 1)
        if hit is None:
            return None
        matched[index] = hit
        cursor = hit - 1
    return matched


def _locate_spans(stream, tokens):
    if not tokens:
        return [], False
    if not stream:
        return [], False
    counts = _token_counts(stream)
    rare_i = _rarest_index(tokens, counts)
    rare = tokens[rare_i]
    hits = [index for index, (token, _word) in enumerate(stream) if token == rare]
    truncated = len(hits) > MAX_ANCHOR_HITS
    if truncated:
        hits = hits[:MAX_ANCHOR_HITS]
    spans = []
    seen = set()
    for pos in hits:
        aligned = _align_around(stream, tokens, rare_i, pos)
        if aligned is None:
            continue
        word_start = stream[aligned[0]][1]
        word_end = stream[aligned[-1]][1]
        key = (word_start, word_end)
        if key in seen:
            continue
        seen.add(key)
        span_tokens = aligned[-1] - aligned[0] + 1
        spans.append(
            {
                "word_start": word_start,
                "word_end": word_end,
                "matched_tokens": len(tokens),
                "span_tokens": span_tokens,
            }
        )
        if len(spans) >= MAX_CANDIDATES:
            remaining = pos != hits[-1]
            truncated = truncated or remaining
            break
    return spans, truncated


def _span_times(words, word_start, word_end, duration_s):
    first = words[word_start]
    last = words[word_end]
    if not first["times_ok"] or not last["times_ok"]:
        return None
    start_s = first["start_ms"] / 1000.0
    end_s = last["end_ms"] / 1000.0
    if not _is_number(start_s) or not _is_number(end_s):
        return None
    if start_s < 0 or end_s > duration_s or end_s <= start_s:
        return None
    return start_s, end_s


def _coverage(matched, passage_tokens, span_tokens):
    if passage_tokens <= 0:
        return 0.0
    raw = matched / passage_tokens
    if span_tokens > passage_tokens:
        raw *= passage_tokens / span_tokens
    return min(1.0, raw)


def _span_candidates(spans, words, passage, duration_s):
    candidates = []
    passage_n = len(passage["tokens"])
    for span in spans:
        times = _span_times(words, span["word_start"], span["word_end"], duration_s)
        if times is None:
            continue
        start_s, end_s = times
        coverage = _coverage(span["matched_tokens"], passage_n, span["span_tokens"])
        if coverage < MIN_TEXTUAL:
            continue
        recognized = " ".join(word["word"] for word in words[span["word_start"] : span["word_end"] + 1])
        if not recognized.strip():
            continue
        candidates.append(
            {
                "start_s": start_s,
                "end_s": end_s,
                "recognized_text": recognized,
                "word_start": span["word_start"],
                "word_end": span["word_end"],
                "textual_evidence": {
                    "matched_tokens": span["matched_tokens"],
                    "passage_tokens": passage_n,
                    "span_tokens": span["span_tokens"],
                    "coverage": coverage,
                },
                "anchor_evidence": {
                    "before_hits": 0,
                    "after_hits": 0,
                    "anchor_tokens": 0,
                    "disambiguates": False,
                },
                "order_evidence": {
                    "narrative_order": passage["order"],
                    "consistent": True,
                    "inverted": False,
                },
                "score": TEXTUAL_WEIGHT * coverage,
            }
        )
    candidates.sort(key=lambda item: (item["start_s"], item["word_start"], item["word_end"]))
    return candidates


def _neighbor_tokens(prepared, index):
    item = prepared[index]
    tokens = []
    tokens.extend(_tokens(item["chapter_context"]))
    for anchor in item["anchors"]:
        tokens.extend(_tokens(anchor["text"]))
    own = set(item["tokens"])
    if index > 0:
        prev = prepared[index - 1]
        tokens.extend(token for token in prev["tokens"] if token not in own)
    if index + 1 < len(prepared):
        nxt = prepared[index + 1]
        tokens.extend(token for token in nxt["tokens"] if token not in own)
    unique = []
    seen = set()
    for token in tokens:
        if token in seen:
            continue
        seen.add(token)
        unique.append(token)
    return unique


def _window_tokens(words, start, end):
    tokens = []
    lo = max(0, start)
    hi = min(len(words), end)
    for word in words[lo:hi]:
        tokens.extend(word["tokens"])
    return tokens


def _count_hits(needles, haystack):
    if not needles:
        return 0
    bag = set(haystack)
    return sum(1 for token in needles if token in bag)


def _apply_neighbor_evidence(prepared, words):
    for index, item in enumerate(prepared):
        anchors = _neighbor_tokens(prepared, index)
        explicit = [_tokens(anchor["text"]) for anchor in item["anchors"]]
        candidates = item["raw_candidates"]
        hit_counts = []
        for cand in candidates:
            before = _window_tokens(words, cand["word_start"] - ANCHOR_WINDOW, cand["word_start"])
            after = _window_tokens(words, cand["word_end"] + 1, cand["word_end"] + 1 + ANCHOR_WINDOW)
            before_hits = _complete_anchor_hits(explicit, before) if explicit else _count_hits(anchors, before)
            after_hits = _complete_anchor_hits(explicit, after) if explicit else _count_hits(anchors, after)
            cand["anchor_evidence"] = {
                "before_hits": before_hits,
                "after_hits": after_hits,
                "anchor_tokens": sum(len(phrase) for phrase in explicit) if explicit else len(anchors),
                "disambiguates": False,
            }
            hit_counts.append(before_hits + after_hits)
        _mark_disambiguation(candidates, hit_counts)
        _score_candidates(candidates)


def _complete_anchor_hits(phrases, window):
    """An explicit anchor needs its complete phrase; shared context words cannot vote."""
    return sum(
        len(phrase)
        for phrase in phrases
        if phrase
        and any(window[index : index + len(phrase)] == phrase for index in range(len(window) - len(phrase) + 1))
    )


def _mark_disambiguation(candidates, hit_counts):
    if len(candidates) < MIN_DISAMBIGUATION_CANDIDATES or not hit_counts:
        return
    best = max(hit_counts)
    if best <= 0:
        return
    winners = [index for index, hits in enumerate(hit_counts) if hits == best]
    if len(winners) != 1:
        return
    others = [hits for index, hits in enumerate(hit_counts) if index != winners[0]]
    if others and best <= max(others):
        return
    candidates[winners[0]]["anchor_evidence"]["disambiguates"] = True


def _score_candidates(candidates):
    for cand in candidates:
        coverage = cand["textual_evidence"]["coverage"]
        evidence = cand["anchor_evidence"]
        denom = evidence["anchor_tokens"]
        anchor_ratio = 0.0
        if denom:
            anchor_ratio = min(1.0, (evidence["before_hits"] + evidence["after_hits"]) / denom)
        order_ratio = 0.0 if cand["order_evidence"]["inverted"] else 1.0
        cand["score"] = min(
            1.0,
            TEXTUAL_WEIGHT * coverage + ANCHOR_WEIGHT * anchor_ratio + ORDER_WEIGHT * order_ratio,
        )


def _strong_candidates(candidates):
    return [cand for cand in candidates if cand["textual_evidence"]["coverage"] >= AUTO_TEXTUAL]


def _overlaps(left, right):
    return left["start_s"] < right["end_s"] and right["start_s"] < left["end_s"]


def _still_plausible_rivals(other, timing_ok):
    """High-coverage spans that still compete for the recording interval.

    Ambiguous peers keep every strong alternative. A peer with unique,
    nontruncated, anchor-supported evidence may drop unselected repeats.
    First-hit, score, or a mere tentative pick never discards a rival.
    """
    strong = _strong_candidates(other["raw_candidates"])
    if not strong:
        return []
    if other["search_truncated"] or not timing_ok:
        return strong
    unique = [cand for cand in strong if cand["anchor_evidence"]["disambiguates"] is True]
    if len(unique) != 1:
        return strong
    return unique


def _has_competing_overlap(choice, occ, prepared, timing_ok):
    """True when a still-plausible high-coverage rival overlaps choice.

    Actual selected-span overlap still competes. Unselected repeats of a peer
    with unique anchor evidence do not. Ambiguous alternatives stay rivals.
    """
    for other in prepared:
        if other["occurrence_id"] == occ:
            continue
        for rival in _still_plausible_rivals(other, timing_ok):
            if _overlaps(choice, rival):
                return True
    return False


def _repeat_group(prepared, item):
    return [other["occurrence_id"] for other in prepared if other["normalized"] == item["normalized"]]


def _tentative_choice(item, timing_ok):
    if not timing_ok or item["search_truncated"]:
        return None
    strong = _strong_candidates(item["raw_candidates"])
    if not strong:
        return None
    if len(strong) == 1:
        return strong[0]
    unique = [cand for cand in strong if cand["anchor_evidence"]["disambiguates"]]
    if len(unique) == 1:
        return unique[0]
    return None


def _choose_unique(prepared, timing_ok):
    tentative = {}
    for item in prepared:
        choice = _tentative_choice(item, timing_ok)
        if choice is not None:
            tentative[item["occurrence_id"]] = choice
    blocked = set()
    items = {item["occurrence_id"]: item for item in prepared}
    for occ, choice in list(tentative.items()):
        group = _repeat_group(prepared, items[occ])
        if len(group) > 1 and not choice["anchor_evidence"]["disambiguates"]:
            blocked.add(occ)
            continue
        if _has_competing_overlap(choice, occ, prepared, timing_ok):
            blocked.add(occ)
    ordered = [item for item in prepared if item["occurrence_id"] in tentative]
    for prev, curr in pairwise(ordered):
        left = tentative[prev["occurrence_id"]]
        right = tentative[curr["occurrence_id"]]
        inverted = right["start_s"] < left["end_s"]
        if inverted:
            blocked.add(prev["occurrence_id"])
            blocked.add(curr["occurrence_id"])
            _set_order_flags(prev["raw_candidates"], consistent=False, inverted=True)
            _set_order_flags(curr["raw_candidates"], consistent=False, inverted=True)
            _score_candidates(prev["raw_candidates"])
            _score_candidates(curr["raw_candidates"])
    return {occ: choice for occ, choice in tentative.items() if occ not in blocked}


def _set_order_flags(candidates, *, consistent, inverted):
    for cand in candidates:
        cand["order_evidence"]["consistent"] = consistent
        cand["order_evidence"]["inverted"] = inverted


def _tokens_as_subsequence(haystack, needle):
    if not needle:
        return False
    index = 0
    for token in haystack:
        if token == needle[index]:
            index += 1
            if index == len(needle):
                return True
    return False


def _text_present(item, stream):
    haystack = [token for token, _index in stream]
    return _tokens_as_subsequence(haystack, item["tokens"])


def _explicit_timing(start_s, end_s, fps):
    start = _non_negative_number(start_s, "start_s")
    end = _positive_number(end_s, "end_s")
    if end <= start:
        raise ValueError("Explicit timing requires end_s after start_s.")
    start_frame = seconds_to_frame(start, fps)
    end_frame = seconds_to_frame(end, fps)
    return {
        "basis": "explicit",
        "start_s": start,
        "end_s": end,
        "start_frame": start_frame,
        "end_frame": end_frame,
        "duration_in_frames": max(1, end_frame - start_frame),
        "duration_s": end - start,
    }


def _bounds_in_recording(start_s, end_s, duration_s):
    start = _non_negative_number(start_s, "start_s")
    end = _positive_number(end_s, "end_s")
    if end <= start:
        raise ValueError("Explicit timing requires end_s after start_s.")
    if end > duration_s:
        raise ValueError("Explicit seconds must stay inside the recording duration.")
    if start > duration_s:
        raise ValueError("Explicit seconds must stay inside the recording duration.")


def _candidate_by_id(candidates, candidate_id):
    ident = _id(candidate_id, "candidate_id")
    for item in candidates:
        if item["id"] == ident:
            return item
    raise ValueError("Unknown alignment candidate_id: " + ident)


def _finalize_candidates(raw_candidates):
    finalized = []
    for index, raw in enumerate(raw_candidates):
        item = {
            "id": "c" + str(index),
            "start_s": float(raw["start_s"]),
            "end_s": float(raw["end_s"]),
            "recognized_text": raw["recognized_text"],
            "word_start": raw["word_start"],
            "word_end": raw["word_end"],
            "textual_evidence": dict(raw["textual_evidence"]),
            "anchor_evidence": dict(raw["anchor_evidence"]),
            "order_evidence": dict(raw["order_evidence"]),
            "score": float(raw["score"]),
        }
        finalized.append(item)
    return finalized


def _selected_id(final_candidates, chosen):
    if chosen is None:
        return None
    for item in final_candidates:
        same_words = item["word_start"] == chosen["word_start"] and item["word_end"] == chosen["word_end"]
        same_times = item["start_s"] == chosen["start_s"] and item["end_s"] == chosen["end_s"]
        if same_words and same_times:
            return item["id"]
    return None


def _scenario_payload(item):
    return {
        "occurrence_id": item["occurrence_id"],
        "narration": item["narration"],
        "chapter_context": item["chapter_context"],
        "anchors": item["anchors"],
    }


def _input_payload(  # noqa: PLR0913 - fingerprint fields are the documented identity tuple
    *,
    analysis_id,
    recording_id,
    recording_sha256,
    recording_duration_s,
    transcript_sha256,
    scenario_sha256,
    order,
    fps,
):
    return {
        "analysis_id": analysis_id,
        "recording_id": recording_id,
        "recording_sha256": recording_sha256,
        "recording_duration_s": recording_duration_s,
        "transcript_sha256": transcript_sha256,
        "scenario_sha256": scenario_sha256,
        "order": order,
        "fps": fps,
        "frame_rounding": FRAME_ROUNDING,
    }


def _passage_state(item, selected, stream):
    if selected is not None:
        return "resolved"
    if item["search_truncated"] or item["raw_candidates"] or _text_present(item, stream):
        return "uncertain"
    return "missing"


def _build_record(  # noqa: PLR0913 - record binds source, scenario, fps and candidates together
    item,
    chosen,
    *,
    analysis_id,
    recording_id,
    recording_sha256,
    recording_duration_s,
    transcript_sha256,
    fps,
    stream,
):
    candidates = _finalize_candidates(item["raw_candidates"])
    selected = _selected_id(candidates, chosen)
    state = _passage_state(item, selected, stream)
    timing = None
    if selected is not None:
        picked = _candidate_by_id(candidates, selected)
        timing = _explicit_timing(picked["start_s"], picked["end_s"], fps)
    scenario_sha = _digest(_scenario_payload(item))
    fingerprint = _digest(
        _input_payload(
            analysis_id=analysis_id,
            recording_id=recording_id,
            recording_sha256=recording_sha256,
            recording_duration_s=recording_duration_s,
            transcript_sha256=transcript_sha256,
            scenario_sha256=scenario_sha,
            order=item["order"],
            fps=fps,
        )
    )
    record = {
        "schema_version": SCHEMA_VERSION,
        "occurrence_id": item["occurrence_id"],
        "original_text": item["narration"],
        "context": item["chapter_context"],
        "analysis_id": analysis_id,
        "recording_id": recording_id,
        "recording_sha256": recording_sha256,
        "recording_duration_s": recording_duration_s,
        "transcript_sha256": transcript_sha256,
        "scenario_sha256": scenario_sha,
        "order": item["order"],
        "input_fingerprint": fingerprint,
        "fps": fps,
        "frame_rounding": FRAME_ROUNDING,
        "search_truncated": item["search_truncated"] is True,
        "state": state,
        "candidates": candidates,
        "selected_candidate_id": selected,
        "timing": timing,
        "decision": None,
    }
    _validate_record(record)
    return record


def _validate_record(record):  # noqa: C901, PLR0912 - schema_version 1 field-by-field structural gate
    if not isinstance(record, dict) or set(record) != set(RECORD_KEYS):
        raise ValueError("Alignment record keys do not match schema_version 1.")
    if "confidence" in record:
        raise ValueError("Alignment records must not store provider confidence.")
    if type(record.get("schema_version")) is not int or record["schema_version"] != SCHEMA_VERSION:
        raise ValueError("Alignment schema_version must be the integer 1.")
    _id(record.get("occurrence_id"), "occurrence_id")
    _required_prose(record.get("original_text"), "original_text")
    _optional_prose(record.get("context"), "context")
    _id(record.get("analysis_id"), "analysis_id")
    _id(record.get("recording_id"), "recording_id")
    _sha256_hex(record.get("recording_sha256"), "recording_sha256")
    duration_s = _positive_number(record.get("recording_duration_s"), "recording_duration_s")
    _sha256_hex(record.get("transcript_sha256"), "transcript_sha256")
    _sha256_hex(record.get("scenario_sha256"), "scenario_sha256")
    if not _is_int(record.get("order")) or record["order"] < 0:
        raise ValueError("order must be a non-negative integer.")
    _sha256_hex(record.get("input_fingerprint"), "input_fingerprint")
    fps = _positive_number(record.get("fps"), "fps")
    if record.get("frame_rounding") != FRAME_ROUNDING:
        raise ValueError("frame_rounding must be half_up_nonnegative.")
    if type(record.get("search_truncated")) is not bool:
        raise ValueError("search_truncated must be a boolean.")
    if record.get("state") not in STATES:
        raise ValueError("state must be resolved, uncertain, missing or stale.")
    candidates = record.get("candidates")
    if not isinstance(candidates, list):
        raise ValueError("candidates must be an array.")
    seen = set()
    for item in candidates:
        _validate_candidate(item, duration_s)
        if item["id"] in seen:
            raise ValueError("candidate id cannot repeat: " + item["id"])
        seen.add(item["id"])
    selected = record.get("selected_candidate_id")
    if selected is not None:
        _candidate_by_id(candidates, selected)
    timing = record.get("timing")
    if timing is not None:
        _validate_timing(timing, fps, duration_s)
    decision = record.get("decision")
    if decision is not None:
        _validate_decision(decision)
    expected_fp = _digest(
        _input_payload(
            analysis_id=record["analysis_id"],
            recording_id=record["recording_id"],
            recording_sha256=record["recording_sha256"],
            recording_duration_s=duration_s,
            transcript_sha256=record["transcript_sha256"],
            scenario_sha256=record["scenario_sha256"],
            order=record["order"],
            fps=fps,
        )
    )
    if record["input_fingerprint"] != expected_fp:
        raise ValueError("input_fingerprint must bind analysis, recording, result, scenario, order and fps.")
    _validate_state_invariants(record)


def _validate_candidate(item, duration_s):
    if not isinstance(item, dict) or set(item) != set(CANDIDATE_KEYS):
        raise ValueError("Alignment candidate keys do not match schema_version 1.")
    if "confidence" in item:
        raise ValueError("Candidates must not store provider confidence.")
    _id(item.get("id"), "candidate id")
    start_s = _non_negative_number(item.get("start_s"), "candidate start_s")
    end_s = _positive_number(item.get("end_s"), "candidate end_s")
    if end_s <= start_s or end_s > duration_s:
        raise ValueError("Candidate seconds must be ordered and inside the recording.")
    _required_prose(item.get("recognized_text"), "recognized_text")
    if not _is_int(item.get("word_start")) or item["word_start"] < 0:
        raise ValueError("word_start must be a non-negative integer.")
    if not _is_int(item.get("word_end")) or item["word_end"] < item["word_start"]:
        raise ValueError("word_end must be an integer at or after word_start.")
    _validate_textual(item.get("textual_evidence"))
    _validate_anchor(item.get("anchor_evidence"))
    _validate_order(item.get("order_evidence"))
    score = item.get("score")
    if not _is_number(score) or score < 0 or score > 1:
        raise ValueError("Matching score must be a finite number in [0, 1].")


def _validate_textual(value):
    if not isinstance(value, dict) or set(value) != set(TEXTUAL_KEYS):
        raise ValueError("textual_evidence keys are invalid.")
    for key in ("matched_tokens", "passage_tokens", "span_tokens"):
        if not _is_int(value[key]) or value[key] < 0:
            raise ValueError(key + " must be a non-negative integer.")
    coverage = value["coverage"]
    if not _is_number(coverage) or coverage < 0 or coverage > 1:
        raise ValueError("textual coverage must be a finite number in [0, 1].")


def _validate_anchor(value):
    if not isinstance(value, dict) or set(value) != set(ANCHOR_KEYS):
        raise ValueError("anchor_evidence keys are invalid.")
    for key in ("before_hits", "after_hits", "anchor_tokens"):
        if not _is_int(value[key]) or value[key] < 0:
            raise ValueError(key + " must be a non-negative integer.")
    if type(value["disambiguates"]) is not bool:
        raise ValueError("anchor disambiguates must be a boolean.")


def _validate_order(value):
    if not isinstance(value, dict) or set(value) != set(ORDER_KEYS):
        raise ValueError("order_evidence keys are invalid.")
    if not _is_int(value["narrative_order"]) or value["narrative_order"] < 0:
        raise ValueError("narrative_order must be a non-negative integer.")
    if type(value["consistent"]) is not bool or type(value["inverted"]) is not bool:
        raise ValueError("order evidence flags must be booleans.")


def _validate_timing_frames(timing, fps, start_s, end_s):
    if not _is_int(timing.get("start_frame")) or timing["start_frame"] < 0:
        raise ValueError("start_frame must be a non-negative integer.")
    if not _is_int(timing.get("end_frame")) or timing["end_frame"] < 0:
        raise ValueError("end_frame must be a non-negative integer.")
    if timing["start_frame"] != seconds_to_frame(start_s, fps):
        raise ValueError("start_frame must use floor(t*fps+0.5).")
    if timing["end_frame"] != seconds_to_frame(end_s, fps):
        raise ValueError("end_frame must use floor(t*fps+0.5).")
    if not _is_int(timing.get("duration_in_frames")) or timing["duration_in_frames"] < 1:
        raise ValueError("duration_in_frames must be an integer of at least 1.")
    if timing["duration_in_frames"] != max(1, timing["end_frame"] - timing["start_frame"]):
        raise ValueError("duration_in_frames must be max(1, end_frame-start_frame).")


def _validate_timing(timing, fps, duration_s):
    if not isinstance(timing, dict) or set(timing) != set(TIMING_KEYS):
        raise ValueError("Alignment timing must be the explicit half_up_nonnegative dict or null.")
    if timing.get("basis") != "explicit":
        raise ValueError("Alignment timing basis must be explicit.")
    start_s = _non_negative_number(timing.get("start_s"), "timing start_s")
    end_s = _positive_number(timing.get("end_s"), "timing end_s")
    if end_s <= start_s or end_s > duration_s:
        raise ValueError("Timing seconds must be ordered and inside the recording.")
    _validate_timing_frames(timing, fps, start_s, end_s)
    duration = _positive_number(timing.get("duration_s"), "timing duration_s")
    if duration != end_s - start_s:
        raise ValueError("timing duration_s must equal end_s minus start_s.")


def _validate_decision(decision):
    if not isinstance(decision, dict) or set(decision) != set(DECISION_KEYS):
        raise ValueError("Correction decision keys are invalid.")
    _required_prose(decision.get("by"), "decision by", MAX_BY)
    _required_prose(decision.get("statement"), "decision statement")
    _required_prose(decision.get("at"), "decision at")
    _sha256_hex(decision.get("input_fingerprint"), "decision input_fingerprint")


def _validate_selected_timing(record, selected, timing):
    if selected is None:
        return
    if timing is None:
        raise ValueError("A selected candidate requires saved timing.")
    picked = _candidate_by_id(record["candidates"], selected)
    if picked["start_s"] != timing["start_s"] or picked["end_s"] != timing["end_s"]:
        raise ValueError("Selected candidate seconds must agree with saved timing.")


def _validate_resolved_state(record, selected, timing, decision):
    if timing is None:
        raise ValueError("Resolved alignment needs explicit timing.")
    if selected is None and decision is None:
        raise ValueError("Resolved alignment needs a selected candidate or an explicit correction.")
    if decision is not None and decision["input_fingerprint"] != record["input_fingerprint"]:
        raise ValueError("Correction input_fingerprint must bind the matching record.")


def _validate_state_invariants(record):
    state = record["state"]
    selected = record["selected_candidate_id"]
    timing = record["timing"]
    decision = record["decision"]
    _validate_selected_timing(record, selected, timing)
    if state == "resolved":
        _validate_resolved_state(record, selected, timing, decision)
        return
    if state == "missing":
        if selected is not None or timing is not None:
            raise ValueError("Missing alignment cannot carry selected timing.")
        return
    if state == "uncertain" and (selected is not None or timing is not None):
        raise ValueError("Uncertain alignment cannot silently select an interval.")


def _analysis_result(analysis):
    if not isinstance(analysis, dict):
        raise ValueError("Readiness analysis must be an object.")
    result = analysis.get("result")
    if result is None:
        return None
    if not isinstance(result, dict):
        raise ValueError("Readiness analysis result must be an object.")
    return result


def _readiness_reasons(record, analysis, recording, passage, profile):
    if not isinstance(analysis, dict):
        raise ValueError("Readiness analysis must be an object.")
    if not isinstance(recording, dict):
        raise ValueError("Readiness recording must be an object.")
    if not isinstance(passage, dict):
        raise ValueError("Readiness passage must be an object.")
    if not isinstance(profile, dict):
        raise ValueError("Readiness profile must be an object.")
    flags = dict.fromkeys(READINESS_REASONS, False)
    _recording_drift(flags, record, recording)
    _analysis_drift(flags, record, analysis)
    _scenario_drift(flags, record, passage)
    _profile_drift(flags, record, profile)
    _state_reasons(flags, record, analysis)
    uses_explicit = profile.get("explicit_timing") or profile.get("timing_basis") == "explicit"
    stale_for_explicit = (
        flags["stale_recording"] or flags["stale_analysis"] or flags["stale_scenario"] or flags["stale_correction"]
    )
    if uses_explicit and stale_for_explicit:
        flags["unresolved_match"] = True
    return [key for key in READINESS_REASONS if flags[key]]


def _recording_drift(flags, record, recording):
    rec_id = recording.get("id")
    rec_sha = recording.get("sha256")
    duration = recording.get("duration_s")
    if rec_id != record["recording_id"] or rec_sha != record["recording_sha256"]:
        flags["stale_recording"] = True
    if not _is_number(duration) or float(duration) != float(record["recording_duration_s"]):
        flags["stale_recording"] = True


def _analysis_drift(flags, record, analysis):
    if analysis.get("id") != record["analysis_id"]:
        flags["stale_analysis"] = True
    result = _analysis_result(analysis)
    if result is None:
        return
    view = _try_result_view(result)
    if view is None or _recognized_result_sha256(view) != record["transcript_sha256"]:
        flags["stale_transcript"] = True


def _scenario_drift(flags, record, passage):
    try:
        parsed = _parse_passage(passage, record["order"] if "order" not in passage else passage["order"])
    except ValueError:
        flags["stale_scenario"] = True
        return
    if parsed["occurrence_id"] != record["occurrence_id"]:
        flags["stale_scenario"] = True
    if parsed["order"] != record["order"]:
        flags["stale_scenario"] = True
    if _digest(_scenario_payload(parsed)) != record["scenario_sha256"]:
        flags["stale_scenario"] = True
    if parsed["narration"] != record["original_text"] or parsed["chapter_context"] != record["context"]:
        flags["stale_scenario"] = True


def _profile_drift(flags, record, profile):
    fps = profile.get("fps")
    if not _is_number(fps) or float(fps) != float(record["fps"]):
        flags["stale_profile"] = True
    rounding = profile.get("frame_rounding")
    if rounding is not None and rounding != FRAME_ROUNDING:
        flags["stale_profile"] = True


def _state_reasons(flags, record, analysis):
    drifted = any(
        flags[key]
        for key in (
            "stale_recording",
            "stale_analysis",
            "stale_transcript",
            "stale_scenario",
            "stale_profile",
        )
    )
    decision = record["decision"]
    selected = record["selected_candidate_id"]
    if decision is not None and (drifted or decision["input_fingerprint"] != record["input_fingerprint"]):
        flags["stale_correction"] = True
    if drifted:
        flags["unresolved_match"] = True
        return
    _active_match_reasons(flags, record, analysis, decision, selected)


def _active_match_reasons(flags, record, analysis, decision, selected):
    if record["search_truncated"] and record["state"] != "resolved":
        flags["search_truncated"] = True
    state = record["state"]
    if state == "missing":
        flags["missing_match"] = True
        return
    if state == "uncertain":
        flags["uncertain_match"] = True
        return
    if state == "stale":
        flags["unresolved_match"] = True
        return
    if record["timing"] is None:
        flags["invalid_timing"] = True
        flags["unresolved_match"] = True
        return
    try:
        _validate_timing(record["timing"], record["fps"], record["recording_duration_s"])
    except ValueError:
        flags["invalid_timing"] = True
        flags["unresolved_match"] = True
        return
    if decision is not None and selected is None:
        return
    result = _analysis_result(analysis)
    view = None if result is None else _try_result_view(result)
    if (
        view is None
        or view["timing_resolved"] is not True
        or not _words_coherent(view["words"], record["recording_duration_s"])
    ):
        flags["incomplete_transcript"] = True
