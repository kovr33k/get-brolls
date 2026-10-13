"""#62 repeated chronology occurrences use the existing factual/version/review seam."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

import _isolation  # noqa: F401
from _cli import run_cli
from _media import skip_unless_ffmpeg
from test_graphics_facts_workflow import _approve, _facts_payload
from test_graphics_review import ENV, _project, _version_hashes

from getbrolls.graphics_timeline import normalize_timeline
from getbrolls.ledger import Ledger, digest


def assign_timeline(project, occurrence="history-01", start=10, end=12, claim="unverified_scenario"):
    return run_cli(
        "graphics-assign",
        "--scene",
        "history",
        "--template",
        "timeline",
        "--occurrence",
        occurrence,
        "--chapter",
        "ch-1",
        "--chapter-context",
        "Original scenario dates are separate narrative passages.",
        "--purpose",
        "Explain dated context",
        "--narration",
        "The first synthetic event occurred in 1900.",
        "--timing",
        "explicit",
        "--start",
        str(start),
        "--end",
        str(end),
        "--claim-status",
        claim,
        project=project,
    )


def timeline_file(project, occurrence="history-01", stamp=10.4, first_date="1900"):
    record = {
        "schema_version": 1,
        "title": "Synthetic milestones",
        "milestones": [
            {"id": "early", "date": first_date, "label": "First synthetic event", "fact_id": "early", "at_s": stamp},
            {"id": "later", "date": "1950", "label": "Later synthetic event", "fact_id": "later", "at_s": None},
        ],
    }
    file = Path(project) / "brolls/graphics-data" / (occurrence + ".json")
    file.parent.mkdir(parents=True, exist_ok=True)
    file.write_text(json.dumps(record), encoding="utf-8")
    return file


def attach_facts(project, occurrence, *, conflict=False, first_date="1900"):
    root = Path(project) / "brolls"
    data = root / "graphics-data/dates.csv"
    data.write_text(
        "date,label\n" + first_date + ",First synthetic event\n1950,Later synthetic event\n", encoding="utf-8"
    )
    record = _facts_payload("graphics-data/dates.csv", digest(data))
    record["values"] = [
        {
            "id": identifier,
            "value": date,
            "unit": "date",
            "definition": label,
            "geography": "Synthetic pilot region",
            "reference_date": "2026-10-11",
            "source_ids": ["src-1"],
        }
        for identifier, date, label in (
            ("early", first_date, "First synthetic event"),
            ("later", "1950", "Later synthetic event"),
        )
    ]
    if conflict:
        record["conflicts"] = [
            {
                "id": "date-conflict",
                "original_narration": "The first synthetic event occurred in 1900.",
                "explanation": "The synthetic source instead dates it 1901.",
                "source_ids": ["src-1"],
                "proposed_correction": "1901",
                "decision": None,
            }
        ]
    file = root / "graphics-data" / (occurrence + "-facts.json")
    file.write_text(json.dumps(record), encoding="utf-8")
    return run_cli("graphics-facts", "--occurrence", occurrence, "--file", str(file), project=project)


@skip_unless_ffmpeg
class TimelineWorkflowTests(unittest.TestCase):
    def test_recurring_timeline_has_separate_versions_clocks_sources_and_delivery(self):
        with tempfile.TemporaryDirectory() as tmp:
            _project(tmp)
            for occurrence, start in (("history-01", 10), ("history-02", 30)):
                assign_timeline(tmp, occurrence, start, start + 2)
                file = timeline_file(tmp, occurrence, start + 0.4)
                run_cli("graphics-timeline", "--occurrence", occurrence, "--file", str(file), project=tmp)
                attach_facts(tmp, occurrence)
            result = run_cli("graphics-continue", project=tmp, env=ENV)
            self.assertEqual(["rendered", "rendered"], [r["action"] for r in result["items"]])
            versions = Ledger(tmp, recover=False).data["graphics"]["versions"]
            self.assertEqual([10, 30], [v["timing"]["start_s"] for v in versions.values()])
            self.assertEqual([60, 60], [v["timing"]["duration_in_frames"] for v in versions.values()])
            for version in versions.values():
                self.assertEqual("Timeline", version["composition"])
                self.assertEqual(12, version["props"]["milestones"][0]["at_frame"])
                self.assertIsNone(version["props"]["milestones"][1]["at_frame"])
                self.assertEqual("sourced", version["props"]["claim_status"])
                self.assertEqual("Synthetic bridge count table", version["props"]["claim_note"])
                self.assertIn("Timeline.jsx", version["fingerprints"]["source"])
                _approve(tmp, version["occurrence_id"], version["id"])
            run_cli("review", project=tmp)
            page = (Path(tmp) / "brolls/review.html").read_text(encoding="utf-8")
            self.assertIn("First synthetic event", page)
            self.assertIn("Synthetic milestones", page)
            delivery = run_cli("deliver", project=tmp)
            self.assertEqual(2, len(delivery["graphics"]))
            for version in Ledger(tmp, recover=False).data["graphics"]["versions"].values():
                directory = Path(tmp) / version["delivery"]["package_dir"]
                self.assertTrue((directory / "source/Timeline.jsx").is_file())
                timing = json.loads((directory / "timing.json").read_text(encoding="utf-8"))
                self.assertEqual(version["timing"]["start_s"], timing["narration"]["start_s"])
            old = _version_hashes(tmp, "history", "v1")
            file = timeline_file(tmp, stamp=11)
            run_cli("graphics-timeline", "--occurrence", "history-01", "--file", str(file), project=tmp)
            result = run_cli("graphics-continue", project=tmp, env=ENV)
            self.assertEqual(["rendered", "reused"], [r["action"] for r in result["items"]])
            updated = Ledger(tmp, recover=False).data["graphics"]["versions"]["v3"]
            self.assertEqual("v1", updated["parent"])
            self.assertIsNone(updated["approval"])
            self.assertEqual(old, _version_hashes(tmp, "history", "v1"))

    def test_conflicting_evidence_waits_only_its_scene_and_never_rewrites_narration(self):
        with tempfile.TemporaryDirectory() as tmp:
            _project(tmp)
            assign_timeline(tmp)
            file = timeline_file(tmp)
            run_cli("graphics-timeline", "--occurrence", "history-01", "--file", str(file), project=tmp)
            attach_facts(tmp, "history-01", conflict=True, first_date="1901")
            assign_timeline(tmp, "history-02", 30, 32, claim="synthetic")
            file = timeline_file(tmp, "history-02", 30.4)
            run_cli("graphics-timeline", "--occurrence", "history-02", "--file", str(file), project=tmp)
            result = run_cli("graphics-continue", project=tmp, env=ENV)
            self.assertEqual(["waiting", "rendered"], [r["action"] for r in result["items"]])
            run_cli("graphics-render", "--occurrence", "history-01", project=tmp, env=ENV, expect=2)
            run_cli(
                "graphics-fact-resolve",
                "--occurrence",
                "history-01",
                "--conflict",
                "date-conflict",
                "--decision",
                "accept_correction",
                "--by",
                "Synthetic fixture",
                "--statement",
                "Synthetic test decision only: display the documented date 1901.",
                project=tmp,
            )
            file = timeline_file(tmp, first_date="1901")
            run_cli("graphics-timeline", "--occurrence", "history-01", "--file", str(file), project=tmp)
            result = run_cli("graphics-continue", project=tmp, env=ENV)
            self.assertEqual(["rendered", "reused"], [r["action"] for r in result["items"]])
            occ = Ledger(tmp, recover=False).data["graphics"]["occurrences"]["history-01"]
            self.assertEqual("The first synthetic event occurred in 1900.", occ["narration"])
            self.assertEqual("1901", occ["timeline"]["milestones"][0]["date"])

    def test_outside_clock_is_refused_atomically_and_retiming_requires_new_emphasis(self):
        with tempfile.TemporaryDirectory() as tmp:
            _project(tmp)
            assign_timeline(tmp, claim="synthetic")
            file = timeline_file(tmp, stamp=30)
            refused = run_cli(
                "graphics-timeline", "--occurrence", "history-01", "--file", str(file), project=tmp, expect=2
            )
            self.assertIn("outside", json.dumps(refused))
            self.assertNotIn("timeline", Ledger(tmp, recover=False).data["graphics"]["occurrences"]["history-01"])
            file = timeline_file(tmp)
            run_cli("graphics-timeline", "--occurrence", "history-01", "--file", str(file), project=tmp)
            run_cli("graphics-continue", project=tmp, env=ENV)
            assign_timeline(tmp, start=20, end=22, claim="synthetic")
            self.assertEqual("waiting", run_cli("graphics-continue", project=tmp, env=ENV)["items"][0]["action"])
            self.assertEqual(1, len(Ledger(tmp, recover=False).data["graphics"]["versions"]))


class TimelineInputTests(unittest.TestCase):
    def test_density_limits_refuse_overlapping_labels_before_render(self):
        timing = {"basis": "explicit", "start_s": 10, "end_s": 13}
        for count, date_limit, label_limit in ((2, 60, 120), (3, 30, 80), (4, 20, 80), (6, 20, 50)):
            with self.subTest(count=count):
                record = {
                    "schema_version": 1,
                    "title": "W" * 90,
                    "milestones": [
                        {
                            "id": str(i),
                            "date": "W" * date_limit,
                            "label": "W" * label_limit,
                            "fact_id": str(i),
                            "at_s": 10.4 if i == 0 else None,
                        }
                        for i in range(count)
                    ],
                }
                normalize_timeline(record, timing)
                for field, limit in (("date", date_limit), ("label", label_limit)):
                    before = record["milestones"][0][field]
                    record["milestones"][0][field] = "W" * (limit + 1)
                    with self.assertRaises(ValueError):
                        normalize_timeline(record, timing)
                    record["milestones"][0][field] = before

    def test_simultaneous_or_backward_emphasis_is_not_invented(self):
        record = {
            "schema_version": 1,
            "title": "Dates",
            "milestones": [
                {"id": "a", "date": "1900", "label": "A", "fact_id": "a", "at_s": 10.2},
                {"id": "b", "date": "1950", "label": "B", "fact_id": "b", "at_s": 10.2},
            ],
        }
        with self.assertRaises(ValueError):
            normalize_timeline(record, {"basis": "explicit", "start_s": 10, "end_s": 12})
