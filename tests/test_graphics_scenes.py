"""Selected map data and custom authoring share public review/version/delivery gates."""

from __future__ import annotations

import copy
import json
import tempfile
import unittest
from pathlib import Path

import _isolation  # noqa: F401
from _cli import run_cli
from _media import skip_unless_ffmpeg
from _paths import ROOT
from test_graphics_facts_workflow import _approve, _facts_payload
from test_graphics_review import ENV, _project, _version_hashes

from getbrolls.graphics_scenes import normalize_scene
from getbrolls.ledger import Ledger, digest


def write(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def scene_fixture(project, kind="map", occurrence="scene-01", start=10, *, raw="permitted", suffix="", estimated=False):  # noqa: PLR0913 - Fixture varies scene identity, clock, source bytes and permissions independently.
    if estimated:
        start = 0
    root = Path(project) / "brolls"
    if kind == "map":
        ref = "graphics-data/selected.geojson"
        geometry = {"type": "Polygon", "coordinates": [[[0, 0], [2, 0], [2, 2], [0, 2], [0, 0]]]}
        write(
            root / ref,
            {"type": "FeatureCollection", "features": [{"type": "Feature", "id": "region", "geometry": geometry}]},
        )
        extra = {
            "data_ref": ref,
            "data_sha256": digest(root / ref),
            "bounds": [-1, -1, 3, 3],
            "focus": [0, 0, 2.5, 2.5],
            "layers": [{"feature_id": "region", "label_point": [1, 1], "treatment": "claim", "geometry": geometry}],
        }
        beats = [{"id": "region", "label": "Synthetic disputed area", "fact_id": "region", "at_s": start + 0.2}]
    else:
        ref = "graphics-data/AuthorScene.jsx"
        (root / ref).parent.mkdir(parents=True, exist_ok=True)
        (root / ref).write_text(
            (ROOT / "references/graphics/RelationshipScene.jsx").read_text(encoding="utf-8") + suffix, encoding="utf-8"
        )
        extra = {
            "source_ref": ref,
            "source_sha256": digest(root / ref),
            "data": {"arrow_meaning": "Synthetic responsibility"},
        }
        beats = [
            {"id": str(i), "label": label, "fact_id": str(i), "at_s": start + 0.2 + i * 0.4}
            for i, label in enumerate(("Synthetic agency", "Synthetic CSM supplier", "Synthetic LM supplier"))
        ]
    permission = {
        "ref": ref,
        "rendered_use": "permitted",
        "raw_redistribution": raw,
        "evidence": ["Locally authored synthetic test data/code."],
        "conditions": "Synthetic fixture only.",
    }
    run_cli(
        "graphics-assign",
        "--scene",
        kind,
        "--template",
        kind,
        "--occurrence",
        occurrence,
        "--chapter",
        "ch-1",
        "--chapter-context",
        "Original chapter context",
        "--purpose",
        "Explain this passage",
        "--narration",
        "Original synthetic scenario passage",
        *(
            ["--timing", "estimated", "--duration", "2"]
            if estimated
            else ["--timing", "explicit", "--start", str(start), "--end", str(start + 2)]
        ),
        "--claim-status",
        "synthetic",
        "--asset-ref",
        ref,
        "--material-use",
        json.dumps(permission),
        project=project,
    )
    record = {
        "schema_version": 1,
        "kind": kind,
        "title": "Synthetic scene",
        "caption": "Conceptual fixture; not real geographic or organizational claims.",
        "beats": beats,
        **extra,
    }
    file = write(root / "graphics-data/content.json", record)
    return file, record


@skip_unless_ffmpeg
class SceneWorkflowTests(unittest.TestCase):
    def test_estimated_map_and_custom_render_in_draft_clock_but_cannot_deliver(self):
        for kind in ("map", "custom"):
            with self.subTest(kind=kind), tempfile.TemporaryDirectory() as tmp:
                _project(tmp)
                file, record = scene_fixture(tmp, kind, estimated=True)
                old_stamp = record["beats"][-1]["at_s"]
                record["beats"][-1]["at_s"] = 2
                write(file, record)
                refused = run_cli(
                    "graphics-content", "--occurrence", "scene-01", "--file", str(file), project=tmp, expect=2
                )
                self.assertIn("scene_beat_outside_draft", json.dumps(refused))
                record["beats"][-1]["at_s"] = old_stamp
                write(file, record)
                run_cli("graphics-content", "--occurrence", "scene-01", "--file", str(file), project=tmp)
                run_cli("graphics-render", "--occurrence", "scene-01", project=tmp, env=ENV)
                version = Ledger(tmp, recover=False).data["graphics"]["versions"]["v1"]
                self.assertEqual("estimated", version["props"]["timing_basis"])
                self.assertIsNone(version["timing"]["start_s"])
                self.assertIsNone(version["timing"]["start_frame"])
                self.assertEqual(6, version["props"]["scene"]["beats"][0]["at_frame"])
                run_cli("review", project=tmp)
                self.assertIn("draft clock 0.2s", (Path(tmp) / "brolls/review.html").read_text(encoding="utf-8"))
                _approve(tmp, "scene-01", "v1")
                report = run_cli("deliver", project=tmp)
                self.assertIn("estimated_timing", [item["reason"] for item in report.get("graphics_skipped") or []])
                self.assertEqual([], report["graphics"])

    def test_map_and_custom_keep_approved_history_and_editable_source(self):
        for kind in ("map", "custom"):
            with self.subTest(kind=kind), tempfile.TemporaryDirectory() as tmp:
                _project(tmp)
                file, record = scene_fixture(tmp, kind)
                run_cli("graphics-content", "--occurrence", "scene-01", "--file", str(file), project=tmp)
                result = run_cli("graphics-continue", project=tmp, env=ENV)
                self.assertEqual("rendered", result["items"][0]["action"])
                _approve(tmp, "scene-01", "v1")
                before = _version_hashes(tmp, kind, "v1")
                record["title"] = "Revised scene title"
                write(file, record)
                run_cli("graphics-content", "--occurrence", "scene-01", "--file", str(file), project=tmp)
                run_cli("graphics-continue", project=tmp, env=ENV)
                state = Ledger(tmp, recover=False).data["graphics"]
                self.assertIsNone(state["versions"]["v2"].get("approval"))
                self.assertEqual(before, _version_hashes(tmp, kind, "v1"))
                _approve(tmp, "scene-01", "v2")
                run_cli("deliver", project=tmp)
                delivered = Ledger(tmp, recover=False).data["graphics"]["versions"]["v2"]
                package = Path(tmp) / delivered["delivery"]["package_dir"]
                self.assertTrue((package / "props.json").is_file())
                entry = "AuthorScene.jsx" if kind == "custom" else "MapScene.jsx"
                self.assertTrue((package / "source" / entry).is_file())
                frozen = state["versions"]["v2"]
                self.assertEqual(6, frozen["props"]["scene"]["beats"][0]["at_frame"])
                self.assertEqual("Original synthetic scenario passage", frozen["assignment"]["narration"])
                run_cli("review", project=tmp)
                html = (Path(tmp) / "brolls/review.html").read_text(encoding="utf-8")
                self.assertIn("Revised scene title", html)
                self.assertIn(record["beats"][0]["label"], html)

    def test_permission_geometry_and_clock_errors_are_atomic(self):
        with tempfile.TemporaryDirectory() as tmp:
            _project(tmp)
            file, record = scene_fixture(tmp)
            before = Ledger(tmp, recover=False).data["graphics"]
            for mutate, expected in (
                (lambda r: r["layers"][0]["geometry"]["coordinates"][0][1].__setitem__(0, 1.5), "differs"),
                (lambda r: r["beats"][0].__setitem__("at_s", 12), "outside"),
                (lambda r: r.__setitem__("data_ref", "graphics-data/../foreign"), "path"),
            ):
                altered = copy.deepcopy(record)
                mutate(altered)
                write(file, altered)
                result = run_cli(
                    "graphics-content", "--occurrence", "scene-01", "--file", str(file), project=tmp, expect=2
                )
                self.assertIn(expected, json.dumps(result).lower())
                self.assertEqual(before, Ledger(tmp, recover=False).data["graphics"])
        with tempfile.TemporaryDirectory() as tmp:
            _project(tmp)
            file, _record = scene_fixture(tmp, "custom", raw="restricted")
            result = run_cli("graphics-content", "--occurrence", "scene-01", "--file", str(file), project=tmp, expect=2)
            self.assertIn("redistribution", json.dumps(result))

    def test_sourced_scene_conflict_waits_only_affected_occurrence(self):
        with tempfile.TemporaryDirectory() as tmp:
            _project(tmp)
            file, record = scene_fixture(tmp)
            run_cli("graphics-content", "--occurrence", "scene-01", "--file", str(file), project=tmp)
            root = Path(tmp) / "brolls"
            facts = _facts_payload(record["data_ref"], record["data_sha256"])
            facts["values"][0].update(id="region", value="area", definition="Synthetic disputed area")
            facts["conflicts"] = [
                {
                    "id": "area-dispute",
                    "original_narration": "Original synthetic scenario passage",
                    "explanation": "Synthetic geographic dispute",
                    "source_ids": ["src-1"],
                    "proposed_correction": "Display the claim separately",
                    "decision": None,
                }
            ]
            facts_file = write(root / "graphics-data/facts.json", facts)
            run_cli("graphics-facts", "--occurrence", "scene-01", "--file", str(facts_file), project=tmp)
            file, _record = scene_fixture(tmp, "custom", "scene-02", 30)
            run_cli("graphics-content", "--occurrence", "scene-02", "--file", str(file), project=tmp)
            result = run_cli("graphics-continue", project=tmp, env=ENV)
            self.assertEqual(["waiting", "rendered"], [item["action"] for item in result["items"]])
            self.assertEqual(
                "Original synthetic scenario passage",
                Ledger(tmp, recover=False).data["graphics"]["occurrences"]["scene-01"]["narration"],
            )

    def test_source_change_requires_explicit_rebind_and_new_version(self):
        with tempfile.TemporaryDirectory() as tmp:
            _project(tmp)
            file, record = scene_fixture(tmp, "custom")
            run_cli("graphics-content", "--occurrence", "scene-01", "--file", str(file), project=tmp)
            run_cli("graphics-continue", project=tmp, env=ENV)
            before = _version_hashes(tmp, "custom", "v1")
            source = Path(tmp) / "brolls" / record["source_ref"]
            source.write_text(source.read_text(encoding="utf-8") + "\n// revised authored source\n", encoding="utf-8")
            result = run_cli("graphics-continue", project=tmp, env=ENV)
            self.assertEqual("waiting", result["items"][0]["action"])
            self.assertEqual(before, _version_hashes(tmp, "custom", "v1"))
            self.assertEqual(1, len(Ledger(tmp, recover=False).data["graphics"]["versions"]))

    def test_custom_code_rebinding_retains_two_attempt_limit_and_meaning(self):
        failure = {"GB_GRAPHICS_WORKER": str(ROOT / "tests/fixtures/graphics_worker_fail.py")}
        with tempfile.TemporaryDirectory() as tmp:
            _project(tmp)
            file, _record = scene_fixture(tmp, "custom")
            run_cli("graphics-content", "--occurrence", "scene-01", "--file", str(file), project=tmp)
            run_cli("graphics-render", "--occurrence", "scene-01", project=tmp, env=failure, expect=2)
            before = _version_hashes(tmp, "custom", "v1")
            for attempt in range(1, 4):
                file, _record = scene_fixture(tmp, "custom", suffix="\n// code repair " + str(attempt) + "\n")
                run_cli("graphics-content", "--occurrence", "scene-01", "--file", str(file), project=tmp)
                run_cli("graphics-render", "--occurrence", "scene-01", "--repair", project=tmp, env=failure, expect=2)
                work = Ledger(tmp, recover=False).data["graphics"]["occurrences"]["scene-01"]["work"]
                self.assertEqual(min(attempt, 2), len(work["repairs"]))
            self.assertEqual(3, len(Ledger(tmp, recover=False).data["graphics"]["versions"]))
            self.assertEqual(before, _version_hashes(tmp, "custom", "v1"))


class GeographicInputTests(unittest.TestCase):
    def test_unclosed_nonfinite_antimeridian_and_unmarked_real_site_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            _project(tmp)
            _file, record = scene_fixture(tmp)
            timing = {"basis": "explicit", "start_s": 10, "end_s": 12}
            for mutate in (
                lambda r: r.__setitem__("bounds", [170, -5, -170, 5]),
                lambda r: r["layers"][0].__setitem__("label_point", [float("nan"), 0]),
                lambda r: r["layers"][0]["geometry"].__setitem__("coordinates", [[[0, 0], [1, 0], [1, 1], [0, 1]]]),
                lambda r: r["layers"][0].__setitem__("geometry", {"type": "Point", "coordinates": [1, 1]}),
            ):
                altered = copy.deepcopy(record)
                mutate(altered)
                with self.assertRaises(ValueError):
                    normalize_scene(Path(tmp) / "brolls", altered, timing)
