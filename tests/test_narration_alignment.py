"""#59: ordered passage matching, bounded correction and alignment readiness."""

from __future__ import annotations

import copy
import hashlib
import json
import math
import unittest

import _isolation  # noqa: F401
from _paths import ROOT

from getbrolls.narration_alignment import (
    AUTO_TEXTUAL,
    FRAME_ROUNDING,
    MAX_ANCHOR_HITS,
    PRESERVE,
    SCHEMA_VERSION,
    alignment_readiness,
    correct_match,
    match_passages,
    seconds_to_frame,
    validate_match,
)

SCHEMA_PATH = ROOT / "schemas" / "narration-alignment.schema.json"
REC_SHA = hashlib.sha256(b"synthetic-recording").hexdigest()
ART_SHA = hashlib.sha256(b"synthetic-transcript-artifact").hexdigest()
ALT_ART = hashlib.sha256(b"replacement-transcript-artifact").hexdigest()
ALT_SHA = hashlib.sha256(b"other-recording-bytes").hexdigest()
ANALYSIS_ID = "an-pilot"
RECORDING_ID = "rec-pilot"
FPS = 30
DURATION_S = 120.0
FILLER = ("and", "then", "some", "bridging", "material", "continues", "here")
ALTERNATIVE_SPAN_GAP = 40


def _word(text, start_ms, end_ms, segment=0):
    return {"word": text, "start_ms": start_ms, "end_ms": end_ms, "segment": segment}


def _words(tokens, start_ms=0, step=400):
    items = []
    cursor = start_ms
    for token in tokens:
        items.append(_word(token, cursor, cursor + step - 50))
        cursor += step
    return items


def _transcript(words):
    return " ".join(item["word"] for item in words)


def _result(words, *, timing_resolved=True, extra=None):
    payload = {
        "transcript": _transcript(words),
        "words": words,
        "artifact_sha256": ART_SHA,
        "timing_resolved": timing_resolved,
    }
    if extra:
        payload.update(extra)
    return payload


def _passage(occurrence_id, narration, context="", anchors=None):
    return {
        "occurrence_id": occurrence_id,
        "narration": narration,
        "chapter_context": context,
        "anchors": [] if anchors is None else anchors,
    }


def _anchor(text):
    return {"text": text, "t_s": None}


def _match(result, passages, **overrides):
    kwargs = {
        "analysis_id": ANALYSIS_ID,
        "recording_id": RECORDING_ID,
        "recording_sha256": REC_SHA,
        "recording_duration_s": DURATION_S,
        "fps": FPS,
    }
    kwargs.update(overrides)
    return match_passages(result, passages, **kwargs)


def _recording():
    return {"id": RECORDING_ID, "sha256": REC_SHA, "duration_s": DURATION_S}


def _analysis(result):
    return {"id": ANALYSIS_ID, "result": result}


def _profile(**overrides):
    item = {"fps": FPS, "frame_rounding": FRAME_ROUNDING}
    item.update(overrides)
    return item


def _ready(record, result, passage, **overrides):
    kwargs = {
        "analysis": _analysis(result),
        "recording": _recording(),
        "passage": passage,
        "profile": _profile(),
    }
    kwargs.update(overrides)
    return alignment_readiness(record, **kwargs)


def _pad(tokens, repeats=8):
    padded = []
    for _ in range(repeats):
        padded.extend(FILLER)
    padded.extend(tokens)
    return padded


class SchemaContractTests(unittest.TestCase):
    def test_schema_version1_has_identity_state_and_no_confidence(self):
        schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
        required = set(schema["required"])
        self.assertEqual(1, SCHEMA_VERSION)
        self.assertEqual(SCHEMA_VERSION, schema["properties"]["schema_version"]["const"])
        self.assertTrue({"analysis_id", "transcript_sha256", "scenario_sha256", "input_fingerprint"} <= required)
        self.assertIn("state", required)
        self.assertEqual(["resolved", "uncertain", "missing", "stale"], schema["properties"]["state"]["enum"])
        self.assertEqual("half_up_nonnegative", schema["properties"]["frame_rounding"]["const"])
        self.assertNotIn("confidence", schema["properties"])
        self.assertNotIn("confidence", schema["$defs"]["candidate"]["properties"])
        self.assertEqual("boolean", schema["properties"]["search_truncated"]["type"])
        decision = schema["$defs"]["decision"]["required"]
        self.assertEqual(["by", "statement", "at", "input_fingerprint"], decision)
        identity = schema["properties"]["transcript_sha256"]["description"]
        self.assertIn("complete recognized result", identity)
        self.assertIn("artifact_sha256", identity)
        self.assertIn("start_ms", identity)
        self.assertIn("timing_resolved", identity)
        self.assertIn("boolean", identity)


class FrameRoundingTests(unittest.TestCase):
    def test_half_up_nonnegative_matches_documented_graphics_convention(self):
        self.assertEqual(1, seconds_to_frame(0.5, 1))
        self.assertEqual(3, seconds_to_frame(2.5, 1))
        self.assertEqual(2, round(2.5))
        self.assertEqual(2, seconds_to_frame(0.05, 30))
        self.assertEqual(90, seconds_to_frame(3, 30))
        self.assertEqual(math.floor(0.05 * 30 + 0.5), seconds_to_frame(0.05, 30))

    def test_rejects_boolean_negative_and_non_finite_inputs(self):
        with self.assertRaises(ValueError):
            seconds_to_frame(True, 30)
        with self.assertRaises(ValueError):
            seconds_to_frame(0.2, True)
        with self.assertRaises(ValueError):
            seconds_to_frame(-0.1, 30)
        with self.assertRaises(ValueError):
            seconds_to_frame(1, 0)
        with self.assertRaises(ValueError):
            seconds_to_frame(float("nan"), 30)
        with self.assertRaises(ValueError):
            seconds_to_frame(1, float("inf"))


class UniqueMatchTests(unittest.TestCase):
    def test_preserves_original_text_while_matching_normalized_copy(self):
        words = _words(["The", "Number", "ROSE.", "afterward"])
        result = _result(words)
        original = "The number rose."
        passages = [_passage("occ-a", original, context="Opening chapter.")]
        records = _match(result, passages)
        record = records["occ-a"]
        validate_match(record)
        self.assertEqual("resolved", record["state"])
        self.assertEqual(original, record["original_text"])
        self.assertEqual("Opening chapter.", record["context"])
        self.assertEqual(set(records), {"occ-a"})
        self.assertIsNone(record["decision"])
        self.assertNotIn("confidence", record)
        self.assertEqual(FRAME_ROUNDING, record["frame_rounding"])
        picked = record["candidates"][0]
        self.assertEqual(original, passages[0]["narration"])
        self.assertIn("Number", picked["recognized_text"])
        self.assertGreaterEqual(picked["textual_evidence"]["coverage"], 0.92)
        timing = record["timing"]
        self.assertEqual("explicit", timing["basis"])
        self.assertEqual(seconds_to_frame(timing["start_s"], FPS), timing["start_frame"])
        self.assertEqual(max(1, timing["end_frame"] - timing["start_frame"]), timing["duration_in_frames"])

    def test_does_not_mutate_inputs_or_copy_provider_confidence(self):
        words = _words(["unique", "alpha", "sentence"])
        result = _result(words, extra={"confidence": 0.99})
        word0 = result["words"][0]
        passages = [_passage("occ-a", "Unique alpha sentence")]
        snapshot = copy.deepcopy(passages)
        records = _match(result, passages)
        self.assertIs(result["words"][0], word0)
        self.assertEqual("unique", result["words"][0]["word"])
        self.assertEqual(snapshot, passages)
        record = records["occ-a"]
        self.assertNotIn("confidence", record)
        self.assertNotIn("confidence", record["candidates"][0])
        self.assertEqual("resolved", record["state"])


class CyrillicTests(unittest.TestCase):
    def test_matches_normalized_cyrillic_punctuation_and_yo(self):
        words = _words(["Чёрный", "рынок", "вырос", "снова"])
        result = _result(words)
        original = "«Черный рынок вырос!»"
        records = _match(result, [_passage("occ-ru", original, context="Глава 1")])
        record = records["occ-ru"]
        self.assertEqual("resolved", record["state"])
        self.assertEqual(original, record["original_text"])
        self.assertEqual("Глава 1", record["context"])
        self.assertIn("Чёрный", record["candidates"][0]["recognized_text"])


class RepeatedPassageTests(unittest.TestCase):
    def test_complete_anchor_outweighs_common_context_words(self):
        early = ["the", *_pad(["In", "2010"], repeats=2), "the", "number", "rose", "the", "market", "grew"]
        late = [*_pad(["In", "2020"], repeats=12), "the", "number", "rose"]
        result = _result(_words([*early, *late]))
        passages = [
            _passage("occ-2010", "The number rose.", context="First decade.", anchors=[_anchor("In 2010")]),
            _passage(
                "occ-2020", "The number rose.", context="After the intervening beats.", anchors=[_anchor("In 2020")]
            ),
        ]
        records = _match(result, passages)
        first, second = records["occ-2010"], records["occ-2020"]
        self.assertEqual("resolved", first["state"])
        self.assertEqual("resolved", second["state"])
        self.assertLess(first["timing"]["end_s"], second["timing"]["start_s"])

    def test_same_text_without_anchors_stays_uncertain_and_does_not_take_first_hit(self):
        first = _pad(["the", "number", "rose"], repeats=2)
        second = _pad(["the", "number", "rose"], repeats=10)
        words = _words([*first, *second])
        result = _result(words)
        passages = [
            _passage("occ-a", "The number rose."),
            _passage("occ-b", "The number rose."),
        ]
        records = _match(result, passages)
        for occ in ("occ-a", "occ-b"):
            record = records[occ]
            self.assertEqual("uncertain", record["state"])
            self.assertIsNone(record["selected_candidate_id"])
            self.assertIsNone(record["timing"])
            self.assertGreaterEqual(len(record["candidates"]), 2)
            starts = [item["start_s"] for item in record["candidates"]]
            self.assertEqual(starts, sorted(starts))
            self.assertNotEqual(record["candidates"][0]["start_s"], record["candidates"][1]["start_s"])
        ready = _ready(records["occ-a"], result, passages[0])
        self.assertFalse(ready["resolved"])
        self.assertIsNone(ready["timing"])
        self.assertIn("uncertain_match", ready["reasons"])

    def test_neighbor_anchors_uniquely_resolve_repeated_text(self):
        early = [*_pad(["In", "2010"], repeats=2), "the", "number", "rose"]
        late = [*_pad(["In", "2020"], repeats=12), "the", "number", "rose"]
        words = _words([*early, *late])
        result = _result(words)
        passages = [
            _passage("occ-2010", "The number rose.", context="First decade.", anchors=[_anchor("In 2010")]),
            _passage("occ-2020", "The number rose.", context="Second decade.", anchors=[_anchor("In 2020")]),
        ]
        records = _match(result, passages)
        first = records["occ-2010"]
        second = records["occ-2020"]
        self.assertEqual("resolved", first["state"])
        self.assertEqual("resolved", second["state"])
        self.assertLess(first["timing"]["end_s"], second["timing"]["start_s"])
        self.assertTrue(any(item["anchor_evidence"]["disambiguates"] for item in first["candidates"]))
        self.assertNotEqual(first["selected_candidate_id"], second["selected_candidate_id"])
        self.assertEqual(first["transcript_sha256"], second["transcript_sha256"])
        self.assertNotEqual(first["scenario_sha256"], second["scenario_sha256"])

    def test_unique_anchor_peer_does_not_treat_ruled_out_repeat_as_overlap(self):
        early = [*_pad(["In", "2010"], repeats=2), "the", "number", "rose"]
        late = [*_pad(["In", "2020"], repeats=12), "the", "number", "rose"]
        words = _words([*early, *late])
        result = _result(words)
        passages = [
            _passage("occ-2010", "The number rose.", context="First decade.", anchors=[_anchor("In 2010")]),
            _passage("occ-2020", "The number rose.", context="Second decade.", anchors=[_anchor("In 2020")]),
        ]
        records = _match(result, passages)
        first = records["occ-2010"]
        second = records["occ-2020"]
        self.assertEqual("resolved", first["state"])
        self.assertEqual("resolved", second["state"])
        strong_first = [item for item in first["candidates"] if item["textual_evidence"]["coverage"] >= AUTO_TEXTUAL]
        strong_second = [item for item in second["candidates"] if item["textual_evidence"]["coverage"] >= AUTO_TEXTUAL]
        self.assertEqual(2, len(strong_first))
        self.assertEqual(2, len(strong_second))
        picked_first = next(item for item in first["candidates"] if item["id"] == first["selected_candidate_id"])
        picked_second = next(item for item in second["candidates"] if item["id"] == second["selected_candidate_id"])
        self.assertTrue(picked_first["anchor_evidence"]["disambiguates"])
        self.assertTrue(picked_second["anchor_evidence"]["disambiguates"])
        self.assertTrue(
            any(
                item["id"] != picked_second["id"]
                and item["start_s"] < picked_first["end_s"]
                and picked_first["start_s"] < item["end_s"]
                for item in strong_second
            )
        )
        self.assertTrue(
            any(
                item["id"] != picked_first["id"]
                and item["start_s"] < picked_second["end_s"]
                and picked_second["start_s"] < item["end_s"]
                for item in strong_first
            )
        )
        self.assertLess(first["timing"]["end_s"], second["timing"]["start_s"])


class OmittedReorderedCompetingTests(unittest.TestCase):
    def test_omitted_passage_is_missing(self):
        words = _words(["alpha", "unique", "sentence", "spoken"])
        result = _result(words)
        passages = [
            _passage("occ-a", "Alpha unique sentence spoken"),
            _passage("occ-miss", "This clause was never recorded at all"),
        ]
        records = _match(result, passages)
        self.assertEqual("resolved", records["occ-a"]["state"])
        missing = records["occ-miss"]
        self.assertEqual("missing", missing["state"])
        self.assertEqual([], missing["candidates"])
        self.assertIsNone(missing["timing"])
        ready = _ready(missing, result, passages[1])
        self.assertFalse(ready["resolved"])
        self.assertIn("missing_match", ready["reasons"])

    def test_reordered_unique_spans_stay_uncertain(self):
        words = _words(["goodbye", "moon", "today", *_pad(["hello", "world", "now"], repeats=6)])
        result = _result(words)
        passages = [
            _passage("occ-hello", "hello world now"),
            _passage("occ-bye", "goodbye moon today"),
        ]
        records = _match(result, passages)
        hello = records["occ-hello"]
        bye = records["occ-bye"]
        self.assertEqual("uncertain", hello["state"])
        self.assertEqual("uncertain", bye["state"])
        self.assertTrue(any(item["order_evidence"]["inverted"] for item in hello["candidates"]))
        self.assertIsNone(hello["selected_candidate_id"])
        self.assertEqual(1, len(hello["candidates"]))
        self.assertEqual(1, len(bye["candidates"]))
        self.assertGreater(hello["candidates"][0]["start_s"], bye["candidates"][0]["end_s"])

    def test_competing_overlapping_spans_are_not_auto_assigned(self):
        words = _words(["the", "market", "grew", "quickly"])
        result = _result(words)
        passages = [
            _passage("occ-long", "the market grew quickly"),
            _passage("occ-short", "the market grew"),
        ]
        records = _match(result, passages)
        self.assertEqual("uncertain", records["occ-long"]["state"])
        self.assertEqual("uncertain", records["occ-short"]["state"])
        self.assertIsNone(records["occ-long"]["timing"])
        self.assertIsNone(records["occ-short"]["selected_candidate_id"])

    def test_high_coverage_alternative_blocks_overlap_without_tentative_peer(self):
        fillers = []
        while len(fillers) < ALTERNATIVE_SPAN_GAP:
            fillers.extend(FILLER)
        fillers = fillers[:ALTERNATIVE_SPAN_GAP]
        tokens = [
            "alpha",
            "beta",
            "gamma",
            *fillers,
            "alpha",
            "beta",
            "extra",
            "extra",
            "extra",
            "extra",
            "gamma",
        ]
        result = _result(_words(tokens))
        passages = [
            _passage("occ-long", "alpha beta gamma"),
            _passage("occ-short", "alpha beta"),
        ]
        records = _match(result, passages)
        long = records["occ-long"]
        short = records["occ-short"]
        strong_long = [item for item in long["candidates"] if item["textual_evidence"]["coverage"] >= AUTO_TEXTUAL]
        strong_short = [item for item in short["candidates"] if item["textual_evidence"]["coverage"] >= AUTO_TEXTUAL]
        self.assertEqual(1, len(strong_long))
        self.assertGreaterEqual(len(strong_short), 2)
        self.assertTrue(
            any(
                item["start_s"] < strong_long[0]["end_s"] and strong_long[0]["start_s"] < item["end_s"]
                for item in strong_short
            )
        )
        self.assertEqual("uncertain", short["state"])
        self.assertEqual("uncertain", long["state"])
        self.assertIsNone(long["selected_candidate_id"])
        self.assertIsNone(long["timing"])
        self.assertIsNone(short["selected_candidate_id"])
        self.assertGreaterEqual(len(short["candidates"]), 2)


class TruncationTests(unittest.TestCase):
    def test_bounded_search_does_not_treat_truncation_as_uniqueness(self):
        count = MAX_ANCHOR_HITS + 6
        tokens = []
        for _ in range(count):
            tokens.extend([*FILLER, "zebroid"])
        words = _words(tokens)
        result = _result(words)
        records = _match(result, [_passage("occ-z", "zebroid")])
        record = records["occ-z"]
        self.assertTrue(record["search_truncated"])
        self.assertEqual("uncertain", record["state"])
        self.assertIsNone(record["selected_candidate_id"])
        self.assertLessEqual(len(record["candidates"]), 8)
        ready = _ready(record, result, _passage("occ-z", "zebroid"))
        self.assertFalse(ready["resolved"])
        self.assertIn("search_truncated", ready["reasons"])


class InvalidTimestampTests(unittest.TestCase):
    def test_boolean_nan_and_out_of_range_times_cannot_resolve(self):
        cases = [
            [_word("hello", True, 400), _word("world", 400, 800)],
            [_word("hello", 0, float("nan")), _word("world", 400, 800)],
            [_word("hello", 800, 400), _word("world", 900, 1200)],
            [_word("hello", 0, 400), _word("world", 400, DURATION_S * 1000 + 5000)],
        ]
        passage = [_passage("occ-a", "hello world")]
        for words in cases:
            with self.subTest(words=words):
                result = _result(words)
                record = _match(result, passage)["occ-a"]
                self.assertNotEqual("resolved", record["state"])
                self.assertIsNone(record["timing"])

    def test_unresolved_provider_timing_does_not_claim_source_timestamps(self):
        words = _words(["hello", "world"])
        result = _result(words, timing_resolved=False)
        record = _match(result, [_passage("occ-a", "hello world")])["occ-a"]
        self.assertEqual("uncertain", record["state"])
        self.assertIsNone(record["timing"])
        self.assertGreaterEqual(len(record["candidates"]), 1)

    def test_nonmonotonic_words_block_auto_resolution(self):
        words = [_word("hello", 800, 1200), _word("world", 100, 400)]
        result = _result(words)
        record = _match(result, [_passage("occ-a", "hello world")])["occ-a"]
        self.assertNotEqual("resolved", record["state"])


class CorrectionTests(unittest.TestCase):
    def test_candidate_confirmation_binds_fingerprints_and_exact_seconds(self):
        first = _pad(["the", "number", "rose"], repeats=2)
        second = _pad(["the", "number", "rose"], repeats=10)
        words = _words([*first, *second])
        result = _result(words)
        passage = _passage("occ-a", "The number rose.")
        record = _match(result, [passage])["occ-a"]
        self.assertEqual("uncertain", record["state"])
        chosen = record["candidates"][1]
        original_fp = record["input_fingerprint"]
        transcript_sha = record["transcript_sha256"]
        updated = correct_match(
            record,
            candidate_id=chosen["id"],
            by="editor",
            statement="Use the later spoken occurrence.",
            at="2026-10-11T12:00:00+00:00",
        )
        self.assertIsNot(updated, record)
        self.assertEqual("uncertain", record["state"])
        self.assertEqual("resolved", updated["state"])
        self.assertEqual(chosen["id"], updated["selected_candidate_id"])
        self.assertEqual(chosen["start_s"], updated["timing"]["start_s"])
        self.assertEqual(chosen["end_s"], updated["timing"]["end_s"])
        self.assertEqual(original_fp, updated["input_fingerprint"])
        self.assertEqual(original_fp, updated["decision"]["input_fingerprint"])
        self.assertEqual(transcript_sha, updated["transcript_sha256"])
        self.assertEqual(REC_SHA, updated["recording_sha256"])
        self.assertEqual(ANALYSIS_ID, updated["analysis_id"])
        ready = _ready(updated, result, passage)
        self.assertTrue(ready["resolved"])
        self.assertEqual(updated["timing"], ready["timing"])

    def test_explicit_time_override_works_without_provider_timestamps(self):
        words = _words(["hello", "world"])
        result = _result(words, timing_resolved=False)
        passage = _passage("occ-a", "hello world")
        record = _match(result, [passage])["occ-a"]
        updated = correct_match(
            record,
            start_s=1.25,
            end_s=4.5,
            by="editor",
            statement="Hand-marked fragment on the recording.",
            at="2026-10-11T12:01:00+00:00",
        )
        self.assertEqual("resolved", updated["state"])
        self.assertIsNone(updated["selected_candidate_id"])
        self.assertEqual(1.25, updated["timing"]["start_s"])
        self.assertEqual(4.5, updated["timing"]["end_s"])
        self.assertEqual(seconds_to_frame(1.25, FPS), updated["timing"]["start_frame"])
        self.assertEqual(record["recording_sha256"], updated["recording_sha256"])
        self.assertEqual(record["transcript_sha256"], updated["transcript_sha256"])
        stub = {"id": ANALYSIS_ID}
        ready = alignment_readiness(
            updated,
            analysis=stub,
            recording=_recording(),
            passage=passage,
            profile=_profile(),
        )
        self.assertTrue(ready["resolved"])
        self.assertEqual(updated["timing"]["start_s"], ready["timing"]["start_s"])
        with self.assertRaises(ValueError):
            correct_match(record, start_s=True, end_s=4.5, by="e", statement="x", at="t")
        with self.assertRaises(ValueError):
            correct_match(record, start_s=1.0, end_s=DURATION_S + 1, by="e", statement="x", at="t")
        with self.assertRaises(ValueError):
            correct_match(
                record,
                candidate_id=record["candidates"][0]["id"] if record["candidates"] else "c0",
                start_s=1.0,
                end_s=2.0,
                by="e",
                statement="x",
                at="t",
            )


class DriftReadinessTests(unittest.TestCase):
    def test_scenario_edit_changes_scenario_hash_not_transcript_identity(self):
        words = _words(["hello", "world", "today"])
        result = _result(words)
        first_passages = [_passage("occ-a", "hello world today", context="v1")]
        second_passages = [_passage("occ-a", "hello world today, revised", context="v2")]
        first = _match(result, first_passages)["occ-a"]
        second = _match(result, second_passages)["occ-a"]
        self.assertEqual(first["transcript_sha256"], second["transcript_sha256"])
        self.assertEqual(first["analysis_id"], second["analysis_id"])
        self.assertEqual(first["recording_sha256"], second["recording_sha256"])
        self.assertNotEqual(first["scenario_sha256"], second["scenario_sha256"])
        self.assertNotEqual(first["input_fingerprint"], second["input_fingerprint"])
        drifted = _ready(first, result, second_passages[0])
        self.assertFalse(drifted["resolved"])
        self.assertIsNone(drifted["timing"])
        self.assertIn("stale_scenario", drifted["reasons"])

    def test_recording_drift_and_stale_correction_block_even_with_explicit_flag(self):
        words = _words(["hello", "world"])
        result = _result(words)
        passage = _passage("occ-a", "hello world")
        record = _match(result, [passage])["occ-a"]
        corrected = correct_match(
            record,
            start_s=0.5,
            end_s=2.0,
            by="editor",
            statement="Override.",
            at="2026-10-11T12:02:00+00:00",
        )
        other_recording = {"id": RECORDING_ID, "sha256": ALT_SHA, "duration_s": DURATION_S}
        ready = alignment_readiness(
            corrected,
            analysis=_analysis(result),
            recording=other_recording,
            passage=passage,
            profile=_profile(explicit_timing=True, timing_basis="explicit"),
        )
        self.assertFalse(ready["resolved"])
        self.assertIsNone(ready["timing"])
        self.assertIn("stale_recording", ready["reasons"])
        self.assertIn("stale_correction", ready["reasons"])
        self.assertIn("unresolved_match", ready["reasons"])

    def test_auto_match_without_complete_result_is_not_resolved(self):
        words = _words(["hello", "world"])
        result = _result(words)
        passage = _passage("occ-a", "hello world")
        record = _match(result, [passage])["occ-a"]
        self.assertEqual("resolved", record["state"])
        ready = alignment_readiness(
            record,
            analysis={"id": ANALYSIS_ID},
            recording=_recording(),
            passage=passage,
            profile=_profile(),
        )
        self.assertFalse(ready["resolved"])
        self.assertIn("incomplete_transcript", ready["reasons"])

    def test_changed_transcript_invalidates_auto_match_only(self):
        words = _words(["hello", "world"])
        result = _result(words)
        passage = _passage("occ-a", "hello world")
        record = _match(result, [passage])["occ-a"]
        other = _result(_words(["hello", "world", "again"]))
        ready = _ready(record, other, passage)
        self.assertFalse(ready["resolved"])
        self.assertIn("stale_transcript", ready["reasons"])

    def test_word_timestamp_change_with_same_text_invalidates_resolved_timing(self):
        words = _words(["hello", "world", "today"])
        result = _result(words)
        passage = _passage("occ-a", "hello world today")
        record = _match(result, [passage])["occ-a"]
        self.assertEqual("resolved", record["state"])
        original_ready = _ready(record, result, passage)
        self.assertTrue(original_ready["resolved"])
        self.assertEqual(record["timing"], original_ready["timing"])
        shifted = copy.deepcopy(words)
        for item in shifted:
            item["start_ms"] += 1500
            item["end_ms"] += 1500
        other = _result(shifted)
        self.assertEqual(result["transcript"], other["transcript"])
        self.assertEqual(result["artifact_sha256"], other["artifact_sha256"])
        rematch = _match(other, [passage])["occ-a"]
        self.assertNotEqual(record["transcript_sha256"], rematch["transcript_sha256"])
        ready = _ready(record, other, passage)
        self.assertFalse(ready["resolved"])
        self.assertIsNone(ready["timing"])
        self.assertIn("stale_transcript", ready["reasons"])

    def test_artifact_change_with_same_text_and_words_invalidates_identity(self):
        words = _words(["hello", "world", "today"])
        result = _result(words)
        passage = _passage("occ-a", "hello world today")
        record = _match(result, [passage])["occ-a"]
        other = _result(words, extra={"artifact_sha256": ALT_ART})
        self.assertEqual(result["transcript"], other["transcript"])
        self.assertEqual(result["words"], other["words"])
        rematch = _match(other, [passage])["occ-a"]
        self.assertNotEqual(record["transcript_sha256"], rematch["transcript_sha256"])
        ready = _ready(record, other, passage)
        self.assertFalse(ready["resolved"])
        self.assertIsNone(ready["timing"])
        self.assertIn("stale_transcript", ready["reasons"])

    def test_saved_text_or_context_mutation_is_stale_against_current_passage(self):
        words = _words(["hello", "world", "today"])
        result = _result(words)
        passage = _passage("occ-a", "hello world today", context="Chapter one")
        record = _match(result, [passage])["occ-a"]
        self.assertEqual("resolved", record["state"])
        original_ready = _ready(record, result, passage)
        self.assertTrue(original_ready["resolved"])
        self.assertEqual([], original_ready["reasons"])
        self.assertEqual(record["original_text"], passage["narration"])
        self.assertEqual(record["context"], passage["chapter_context"])
        text_only = copy.deepcopy(record)
        text_only["original_text"] = "hello world today, displayed differently"
        self.assertEqual(record["scenario_sha256"], text_only["scenario_sha256"])
        self.assertEqual(record["input_fingerprint"], text_only["input_fingerprint"])
        validate_match(text_only)
        text_ready = _ready(text_only, result, passage)
        self.assertFalse(text_ready["resolved"])
        self.assertIsNone(text_ready["timing"])
        self.assertIn("stale_scenario", text_ready["reasons"])
        self.assertNotIn("stale_correction", text_ready["reasons"])
        context_only = copy.deepcopy(record)
        context_only["context"] = "Different chapter"
        self.assertEqual(record["scenario_sha256"], context_only["scenario_sha256"])
        self.assertEqual(record["input_fingerprint"], context_only["input_fingerprint"])
        validate_match(context_only)
        context_ready = _ready(context_only, result, passage)
        self.assertFalse(context_ready["resolved"])
        self.assertIsNone(context_ready["timing"])
        self.assertIn("stale_scenario", context_ready["reasons"])
        corrected = correct_match(
            record,
            candidate_id=record["selected_candidate_id"],
            by="editor",
            statement="Confirm the spoken span.",
            at="2026-10-11T12:07:00+00:00",
        )
        self.assertTrue(_ready(corrected, result, passage)["resolved"])
        mutated_override = copy.deepcopy(corrected)
        mutated_override["original_text"] = "hello world today, displayed differently"
        self.assertEqual(corrected["scenario_sha256"], mutated_override["scenario_sha256"])
        override_ready = _ready(mutated_override, result, passage)
        self.assertFalse(override_ready["resolved"])
        self.assertIn("stale_scenario", override_ready["reasons"])
        self.assertIn("stale_correction", override_ready["reasons"])
        rematch = _match(result, [passage])["occ-a"]
        self.assertEqual(record["transcript_sha256"], rematch["transcript_sha256"])
        self.assertEqual(record["scenario_sha256"], rematch["scenario_sha256"])

    def test_timing_resolved_boolean_is_part_of_recognized_result_identity(self):
        words = _words(["hello", "world", "today"])
        result = _result(words, timing_resolved=True)
        passage = _passage("occ-a", "hello world today")
        record = _match(result, [passage])["occ-a"]
        self.assertEqual("resolved", record["state"])
        flipped = _result(words, timing_resolved=False)
        self.assertEqual(result["transcript"], flipped["transcript"])
        self.assertEqual(result["words"], flipped["words"])
        self.assertEqual(result["artifact_sha256"], flipped["artifact_sha256"])
        rematch = _match(flipped, [passage])["occ-a"]
        self.assertNotEqual(record["transcript_sha256"], rematch["transcript_sha256"])
        self.assertEqual("uncertain", rematch["state"])
        ready = _ready(record, flipped, passage)
        self.assertFalse(ready["resolved"])
        self.assertIsNone(ready["timing"])
        self.assertIn("stale_transcript", ready["reasons"])
        confirmed = correct_match(
            record,
            candidate_id=record["selected_candidate_id"],
            by="editor",
            statement="Confirm the spoken span.",
            at="2026-10-11T12:06:00+00:00",
        )
        stale_confirmed = _ready(confirmed, flipped, passage)
        self.assertFalse(stale_confirmed["resolved"])
        self.assertIn("stale_transcript", stale_confirmed["reasons"])
        self.assertIn("stale_correction", stale_confirmed["reasons"])
        override = correct_match(
            rematch,
            start_s=0.5,
            end_s=2.0,
            by="editor",
            statement="Hand interval from unresolved timing.",
            at="2026-10-11T12:05:00+00:00",
        )
        still = _ready(override, flipped, passage)
        self.assertTrue(still["resolved"])
        self.assertEqual(override["timing"], still["timing"])
        revised = _passage("occ-a", "hello world today, revised")
        rematch_scenario = _match(flipped, [revised])["occ-a"]
        self.assertEqual(rematch["transcript_sha256"], rematch_scenario["transcript_sha256"])
        self.assertNotEqual(rematch["scenario_sha256"], rematch_scenario["scenario_sha256"])

    def test_timing_resolved_must_be_actual_boolean(self):
        words = _words(["hello", "world"])
        passages = [_passage("occ-a", "hello world")]
        for flag in (1, 0, "true", None):
            with self.subTest(flag=flag):
                result = _result(words, extra={"timing_resolved": flag})
                with self.assertRaises(ValueError):
                    _match(result, passages)

    def test_corrupt_intermediate_words_do_not_keep_stale_auto_or_correction(self):
        words = _words(["hello", "middle", "world"])
        result = _result(words)
        passage = _passage("occ-a", "hello middle world")
        record = _match(result, [passage])["occ-a"]
        self.assertEqual("resolved", record["state"])
        corrected = correct_match(
            record,
            candidate_id=record["selected_candidate_id"],
            by="editor",
            statement="Confirm the spoken span.",
            at="2026-10-11T12:03:00+00:00",
        )
        corrupt = copy.deepcopy(words)
        corrupt[1]["start_ms"] = 10
        corrupt[1]["end_ms"] = 20
        other = _result(corrupt)
        self.assertEqual(result["transcript"], other["transcript"])
        rematch = _match(other, [passage])["occ-a"]
        self.assertNotEqual(record["transcript_sha256"], rematch["transcript_sha256"])
        self.assertNotEqual("resolved", rematch["state"])
        for saved in (record, corrected):
            ready = _ready(saved, other, passage)
            self.assertFalse(ready["resolved"])
            self.assertIsNone(ready["timing"])
            self.assertIn("stale_transcript", ready["reasons"])
        self.assertIn("stale_correction", _ready(corrected, other, passage)["reasons"])


class ValidationTests(unittest.TestCase):
    def test_validate_match_rejects_nonbool_truncated_and_foreign_keys(self):
        words = _words(["hello", "world"])
        record = _match(_result(words), [_passage("occ-a", "hello world")])["occ-a"]
        validate_match(record)
        broken = copy.deepcopy(record)
        broken["search_truncated"] = 1
        with self.assertRaises(ValueError) as raised:
            validate_match(broken)
        self.assertEqual(PRESERVE, str(raised.exception))
        extra = copy.deepcopy(record)
        extra["confidence"] = 0.4
        with self.assertRaises(ValueError):
            validate_match(extra)

    def test_match_passages_rejects_boolean_fps_and_duration(self):
        words = _words(["hello", "world"])
        result = _result(words)
        passages = [_passage("occ-a", "hello world")]
        with self.assertRaises(ValueError):
            _match(result, passages, fps=True)
        with self.assertRaises(ValueError):
            _match(result, passages, recording_duration_s=True)
        with self.assertRaises(ValueError):
            _match(result, passages, recording_duration_s=float("nan"))

    def test_same_frame_bounds_keep_at_least_one_frame(self):
        words = [_word("hello", 10, 20), _word("world", 20, 30)]
        result = _result(words)
        record = _match(result, [_passage("occ-a", "hello world")], fps=1, recording_duration_s=5)["occ-a"]
        self.assertEqual("resolved", record["state"])
        self.assertGreaterEqual(record["timing"]["duration_in_frames"], 1)
        self.assertEqual(
            max(1, record["timing"]["end_frame"] - record["timing"]["start_frame"]),
            record["timing"]["duration_in_frames"],
        )

    def test_selected_candidate_must_agree_with_saved_timing(self):
        record = _match(_result(_words(["hello", "world"])), [_passage("occ-a", "hello world")])["occ-a"]
        self.assertEqual("resolved", record["state"])
        self.assertIsNotNone(record["selected_candidate_id"])
        picked = record["candidates"][0]
        self.assertLessEqual(picked["end_s"], 1.0)
        broken = copy.deepcopy(record)
        broken["timing"] = {
            "basis": "explicit",
            "start_s": 5.0,
            "end_s": 6.0,
            "start_frame": seconds_to_frame(5.0, FPS),
            "end_frame": seconds_to_frame(6.0, FPS),
            "duration_in_frames": max(1, seconds_to_frame(6.0, FPS) - seconds_to_frame(5.0, FPS)),
            "duration_s": 1.0,
        }
        with self.assertRaises(ValueError) as raised:
            validate_match(broken)
        self.assertEqual(PRESERVE, str(raised.exception))

    def test_input_fingerprint_must_bind_saved_source_scenario_and_fps(self):
        record = _match(
            _result(_words(["hello", "world"])),
            [_passage("occ-a", "hello world", context="Chapter one")],
        )["occ-a"]
        original_fp = record["input_fingerprint"]
        other_scenario = hashlib.sha256(b"other-scenario-identity").hexdigest()
        other_result = hashlib.sha256(b"other-recognized-result").hexdigest()
        cases = [
            ("recording_sha256", ALT_SHA, None),
            ("analysis_id", "an-other", None),
            ("scenario_sha256", other_scenario, None),
            ("transcript_sha256", other_result, None),
            ("recording_duration_s", DURATION_S + 5.0, None),
            ("fps", 24.0, 24.0),
        ]
        for field, value, new_fps in cases:
            with self.subTest(field=field):
                broken = copy.deepcopy(record)
                broken[field] = value
                if new_fps is not None:
                    timing = broken["timing"]
                    timing["start_frame"] = seconds_to_frame(timing["start_s"], new_fps)
                    timing["end_frame"] = seconds_to_frame(timing["end_s"], new_fps)
                    timing["duration_in_frames"] = max(1, timing["end_frame"] - timing["start_frame"])
                self.assertEqual(original_fp, broken["input_fingerprint"])
                with self.assertRaises(ValueError) as raised:
                    validate_match(broken)
                self.assertEqual(PRESERVE, str(raised.exception))

    def test_explicit_override_and_unresolved_records_remain_structurally_valid(self):
        words = _words(["hello", "world"])
        result = _result(words)
        passage = _passage("occ-a", "hello world")
        record = _match(result, [passage])["occ-a"]
        override = correct_match(
            record,
            start_s=5.0,
            end_s=6.0,
            by="editor",
            statement="Hand interval.",
            at="2026-10-11T12:04:00+00:00",
        )
        self.assertIsNone(override["selected_candidate_id"])
        validate_match(override)
        stale = copy.deepcopy(record)
        stale["state"] = "stale"
        validate_match(stale)
        first = _pad(["the", "number", "rose"], repeats=2)
        second = _pad(["the", "number", "rose"], repeats=10)
        uncertain = _match(_result(_words([*first, *second])), [_passage("occ-r", "The number rose.")])["occ-r"]
        self.assertEqual("uncertain", uncertain["state"])
        validate_match(uncertain)
        missing = _match(
            result,
            [_passage("occ-a", "hello world"), _passage("occ-miss", "never spoken phrase here")],
        )["occ-miss"]
        self.assertEqual("missing", missing["state"])
        validate_match(missing)


if __name__ == "__main__":
    unittest.main()
