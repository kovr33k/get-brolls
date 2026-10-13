"""#53: explicit numeric graphics records, optional renderer, Storyboard cards."""

from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import _isolation  # noqa: F401
from _cli import run_cli
from _media import skip_unless_ffmpeg
from _paths import CLI, ROOT

from getbrolls.cli import FORMAT_GATE_SUBCOMMANDS
from getbrolls.graphics import (
    PRESERVE,
    _browser_record,
    _marker_matches_live,
    _probe_artifact,
    _verify_complete,
    default_profile,
    render_command,
    runtime_status,
    seconds_to_frame,
    validate_graphics,
)
from getbrolls.ledger import Ledger, validate_manifest
from getbrolls.ledger import digest as file_digest
from getbrolls.models import candidate, now, set_segment
from getbrolls.rendering import render
from getbrolls.review import import_review
from getbrolls.runtime import READ_ONLY_COMMANDS

WORKER = ROOT / "tests" / "fixtures" / "graphics_worker.py"
FAILING_WORKER = ROOT / "tests" / "fixtures" / "graphics_worker_fail.py"


def _assign_kwargs(**overrides):
    values = {
        "scene": "numeric-stat",
        "template": "numeric-stat",
        "occurrence": "stat-01",
        "chapter": "ch-1",
        "chapter_context": "The surrounding chapter keeps the original scenario paragraph.",
        "purpose": "Show the synthetic count",
        "narration": "The count stands at twelve units.",
        "timing": "estimated",
        "duration": 3.0,
        "start": None,
        "end": None,
        "anchor": None,
        "question": None,
        "propose_scene": None,
        "asset_ref": None,
        "evidence_ref": None,
        "confirm_fps": None,
        "value": "12",
        "unit": "units",
        "label": "Synthetic count",
        "claim_status": "synthetic",
        "style_note": None,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def _review_payload(page):
    match = re.search(r"window.GETBROLLS_REVIEW=(.*?);</script>", page)
    if match is None:
        raise AssertionError("GETBROLLS_REVIEW payload is missing")
    return json.loads(match.group(1))


def _project_with_rules(tmp):
    run_cli("init-rules", project=tmp)
    return tmp


class FrameRoundingTests(unittest.TestCase):
    def test_nonnegative_half_up_differs_from_bankers_rounding(self):
        self.assertEqual(1, seconds_to_frame(0.5, 1))
        self.assertEqual(3, seconds_to_frame(2.5, 1))
        self.assertEqual(2, seconds_to_frame(0.05, 30))
        self.assertEqual(90, seconds_to_frame(3, 30))

    def test_rejects_negative_or_non_finite_inputs(self):
        with self.assertRaises(ValueError):
            seconds_to_frame(-0.1, 30)
        with self.assertRaises(ValueError):
            seconds_to_frame(1, 0)


class OptionalRuntimeTests(unittest.TestCase):
    def test_help_and_providers_work_without_remotion_modules(self):
        search_help = subprocess.run(
            [sys.executable, str(CLI), "search", "--help"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            check=False,
        )
        self.assertEqual(0, search_help.returncode, search_help.stderr)
        self.assertIn("--query", search_help.stdout)
        assign_help = subprocess.run(
            [sys.executable, str(CLI), "graphics-assign", "--help"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            check=False,
        )
        self.assertEqual(0, assign_help.returncode, assign_help.stderr)
        self.assertIn("Authored scene identity", assign_help.stdout)
        self.assertIn("--template", assign_help.stdout)
        self.assertIn("numeric-stat", assign_help.stdout)
        payload = run_cli("providers")
        self.assertTrue(payload)

    def test_graphics_doctor_is_read_only_and_does_not_create_a_project(self):
        self.assertIn("graphics-doctor", READ_ONLY_COMMANDS)
        self.assertNotIn("graphics-assign", FORMAT_GATE_SUBCOMMANDS)
        self.assertNotIn("graphics-render", FORMAT_GATE_SUBCOMMANDS)
        self.assertNotIn("graphics-style", FORMAT_GATE_SUBCOMMANDS)
        with tempfile.TemporaryDirectory() as tmp:
            payload = run_cli("graphics-doctor", project=tmp)
            self.assertEqual("summary", next(iter(payload)))
            optional = {entry["item"] for entry in payload["summary"]["optional"]}
            ok = set(payload["summary"]["ok"])
            if payload["graphics"]["missing"]:
                self.assertIn("remotion", optional)
            else:
                self.assertIn("remotion", ok)
            self.assertFalse((Path(tmp) / "brolls").exists())
            self.assertIn("4.0.534", json.dumps(payload["setup"]))

    def test_doctor_lists_remotion_as_optional_or_installed(self):
        payload = run_cli("doctor")
        optional = {entry["item"] for entry in payload["summary"].get("optional") or []}
        if payload["graphics"]["missing"]:
            self.assertIn("remotion", optional)
            self.assertFalse(payload["graphics"]["installed"])
        else:
            self.assertTrue(payload["graphics"]["installed"])
            self.assertNotIn("remotion", optional)

    def test_missing_and_present_runtime_paths(self):
        from getbrolls import graphics as g

        original = g._package_versions
        try:
            g._package_versions = lambda: ({}, ["remotion"])
            missing = g.doctor_command(SimpleNamespace(prepare_browser=False))
            self.assertIn("remotion", {entry["item"] for entry in missing["summary"]["optional"]})
            g._package_versions = lambda: (dict(g.PINNED), [])
            present = g.doctor_command(SimpleNamespace(prepare_browser=False))
            self.assertIn("remotion", present["summary"]["ok"])
        finally:
            g._package_versions = original

    def test_render_without_runtime_names_the_install_command(self):
        from getbrolls import graphics as g

        with tempfile.TemporaryDirectory() as tmp:
            _project_with_rules(tmp)
            run_cli(
                "graphics-assign",
                "--scene",
                "numeric-stat",
                "--occurrence",
                "stat-01",
                "--chapter",
                "ch-1",
                "--chapter-context",
                "Surrounding chapter text from the scenario.",
                "--purpose",
                "Show the count",
                "--narration",
                "The count stands at twelve units.",
                "--timing",
                "estimated",
                "--duration",
                "3",
                project=tmp,
            )
            empty_worker = run_cli(
                "graphics-render",
                "--occurrence",
                "stat-01",
                project=tmp,
                expect=2,
                env={"GB_GRAPHICS_WORKER": ""},
            )
            self.assertIn("absolute existing path", json.dumps(empty_worker, ensure_ascii=False))
            relative_worker = run_cli(
                "graphics-render",
                "--occurrence",
                "stat-01",
                project=tmp,
                expect=2,
                env={"GB_GRAPHICS_WORKER": "tests/fixtures/graphics_worker.py"},
            )
            self.assertIn("absolute existing path", json.dumps(relative_worker, ensure_ascii=False))
            status = runtime_status()
            if status["missing"] or not status["node"]:
                refused = run_cli("graphics-render", "--occurrence", "stat-01", project=tmp, expect=2)
                self.assertIn(
                    "npm ci --ignore-scripts --prefix scripts/graphics", json.dumps(refused, ensure_ascii=False)
                )
                return
            original = g._package_versions
            previous = os.environ.pop("GB_GRAPHICS_WORKER", None)
            try:
                g._package_versions = lambda: ({}, ["remotion"])
                ledger = Ledger(tmp, recover=False)
                with self.assertRaises(ValueError) as ctx:
                    render_command(ledger, SimpleNamespace(occurrence="stat-01"))
                self.assertIn("npm ci --ignore-scripts --prefix scripts/graphics", str(ctx.exception))
            finally:
                g._package_versions = original
                if previous is not None:
                    os.environ["GB_GRAPHICS_WORKER"] = previous


class AssignAndStyleTests(unittest.TestCase):
    def test_estimated_duration_only_and_style_history(self):
        with tempfile.TemporaryDirectory() as tmp:
            _project_with_rules(tmp)
            first = run_cli("graphics-style", "--note", "first proposed draft", project=tmp)
            self.assertEqual(1, first["current_style_revision"])
            self.assertFalse(first["approved"])
            second = run_cli("graphics-style", "--note", "revised proposed draft", project=tmp)
            self.assertEqual(2, second["current_style_revision"])
            assigned = run_cli(
                "graphics-assign",
                "--scene",
                "numeric-stat",
                "--occurrence",
                "stat-01",
                "--chapter",
                "ch-1",
                "--chapter-context",
                "Surrounding chapter text from the scenario.",
                "--purpose",
                "Show the count",
                "--narration",
                "The count stands at twelve units.",
                "--timing",
                "estimated",
                "--duration",
                "3",
                "--question",
                "Is the unit still units?",
                "--propose-scene",
                "A later timeline",
                project=tmp,
            )
            occ = assigned["occurrence"]
            self.assertEqual("estimated", occ["timing"]["basis"])
            self.assertIsNone(occ["timing"]["start_s"])
            self.assertIsNone(occ["timing"]["end_s"])
            self.assertEqual(90, occ["timing"]["duration_in_frames"])
            self.assertEqual(2, occ["style_revision"])
            ledger = Ledger(tmp, recover=False)
            revisions = ledger.data["graphics"]["style_revisions"]
            self.assertEqual([1, 2], [item["revision"] for item in revisions])
            self.assertTrue(all(item["approved"] is False for item in revisions))
            self.assertEqual(0, len(ledger.data["items"]))

    def test_estimated_timing_rejects_start_and_existing_project_needs_confirm_fps(self):
        with tempfile.TemporaryDirectory() as tmp:
            _project_with_rules(tmp)
            refused = run_cli(
                "graphics-assign",
                "--scene",
                "numeric-stat",
                "--occurrence",
                "stat-01",
                "--chapter",
                "ch-1",
                "--chapter-context",
                "Surrounding chapter text from the scenario.",
                "--purpose",
                "Show the count",
                "--narration",
                "The count stands at twelve units.",
                "--timing",
                "estimated",
                "--duration",
                "3",
                "--start",
                "1",
                "--end",
                "4",
                project=tmp,
                expect=2,
            )
            self.assertIn("duration only", json.dumps(refused, ensure_ascii=False))
            ledger = Ledger(tmp)
            item = candidate("local", "clip", "Synthetic")
            set_segment(item, 0, 1)
            ledger.add(item)
            ledger.save("fixture", item)
            missing_fps = run_cli(
                "graphics-assign",
                "--scene",
                "numeric-stat",
                "--occurrence",
                "stat-01",
                "--chapter",
                "ch-1",
                "--chapter-context",
                "Surrounding chapter text from the scenario.",
                "--purpose",
                "Show the count",
                "--narration",
                "The count stands at twelve units.",
                "--timing",
                "estimated",
                "--duration",
                "3",
                project=tmp,
                expect=2,
            )
            self.assertIn("--confirm-fps", json.dumps(missing_fps, ensure_ascii=False))
            confirmed = run_cli(
                "graphics-assign",
                "--scene",
                "numeric-stat",
                "--occurrence",
                "stat-01",
                "--chapter",
                "ch-1",
                "--chapter-context",
                "Surrounding chapter text from the scenario.",
                "--purpose",
                "Show the count",
                "--narration",
                "The count stands at twelve units.",
                "--timing",
                "explicit",
                "--start",
                "1.5",
                "--end",
                "4.5",
                "--confirm-fps",
                "30",
                project=tmp,
            )
            timing = confirmed["occurrence"]["timing"]
            self.assertEqual("explicit", timing["basis"])
            self.assertEqual(45, timing["start_frame"])
            self.assertEqual(135, timing["end_frame"])
            self.assertEqual(90, timing["duration_in_frames"])

    def test_rejects_reserved_ids_and_path_traversal(self):
        with tempfile.TemporaryDirectory() as tmp:
            _project_with_rules(tmp)
            reserved = run_cli(
                "graphics-assign",
                "--scene",
                "numeric-stat",
                "--occurrence",
                "CON",
                "--chapter",
                "ch-1",
                "--chapter-context",
                "Surrounding chapter text from the scenario.",
                "--purpose",
                "Show the count",
                "--narration",
                "The count stands at twelve units.",
                "--timing",
                "estimated",
                "--duration",
                "3",
                project=tmp,
                expect=2,
            )
            self.assertIn("Windows", json.dumps(reserved, ensure_ascii=False))
            traversal = run_cli(
                "graphics-assign",
                "--scene",
                "numeric-stat",
                "--occurrence",
                "stat-01",
                "--chapter",
                "ch-1",
                "--chapter-context",
                "Surrounding chapter text from the scenario.",
                "--purpose",
                "Show the count",
                "--narration",
                "The count stands at twelve units.",
                "--timing",
                "estimated",
                "--duration",
                "3",
                "--asset-ref",
                "../secret.mp4",
                project=tmp,
                expect=2,
            )
            self.assertIn("relative posix", json.dumps(traversal, ensure_ascii=False))

    def test_legacy_manifest_without_graphics_still_validates(self):
        data = {"schema_version": 1, "items": []}
        self.assertEqual(data, validate_manifest(data))
        with self.assertRaises(ValueError):
            validate_graphics(
                {
                    "schema_version": 1,
                    "items": [],
                    "graphics": {"schema_version": 1, "profile": {}},
                }
            )


class StatusReadOnlyTests(unittest.TestCase):
    def test_status_reports_pending_graphics_without_writing_or_recovering(self):
        with tempfile.TemporaryDirectory() as tmp:
            _project_with_rules(tmp)
            run_cli(
                "graphics-assign",
                "--scene",
                "numeric-stat",
                "--occurrence",
                "stat-01",
                "--chapter",
                "ch-1",
                "--chapter-context",
                "Surrounding chapter text from the scenario.",
                "--purpose",
                "Show the count",
                "--narration",
                "The count stands at twelve units.",
                "--timing",
                "estimated",
                "--duration",
                "3",
                project=tmp,
            )
            root = Path(tmp) / "brolls"
            pending = root / ".pending-transaction.json"
            pending.write_text(
                json.dumps({"data": {"schema_version": 1, "items": []}, "events": []}),
                encoding="utf-8",
            )
            skip = {".command.lock", "diagnostics.jsonl", "getbrolls.log"}
            before = sorted(path.relative_to(root).as_posix() for path in root.rglob("*") if path.name not in skip)
            payload = run_cli("status", project=tmp)
            self.assertEqual("pending", payload["journal"]["recovered_write"])
            self.assertEqual(1, payload["graphics"]["pending"])
            self.assertFalse((root / "graphics").exists())
            after = sorted(path.relative_to(root).as_posix() for path in root.rglob("*") if path.name not in skip)
            self.assertEqual(before, after)
            self.assertTrue(pending.is_file())


@skip_unless_ffmpeg
class RenderStubTests(unittest.TestCase):
    def test_stub_render_publishes_immutable_preview_and_keeps_failed_version(self):
        with tempfile.TemporaryDirectory() as tmp:
            _project_with_rules(tmp)
            run_cli(
                "graphics-assign",
                "--scene",
                "numeric-stat",
                "--occurrence",
                "stat-01",
                "--chapter",
                "ch-1",
                "--chapter-context",
                'Chapter <b>one</b> & "quoted" context.',
                "--purpose",
                "Show the count",
                "--narration",
                "The count stands at twelve units.",
                "--timing",
                "estimated",
                "--duration",
                "3",
                "--question",
                "Need a source?",
                project=tmp,
            )
            env = {"GB_GRAPHICS_WORKER": str(WORKER)}
            first = run_cli("graphics-render", "--occurrence", "stat-01", project=tmp, env=env)
            self.assertEqual("v1", first["version"]["id"])
            self.assertIsNone(first["version"]["parent"])
            self.assertFalse(first["approved"])
            job = json.loads(
                (Path(tmp) / "brolls" / "graphics" / "numeric-stat" / "v1" / "job.json").read_text(encoding="utf-8")
            )
            self.assertEqual("bt709", job["colorSpace"])
            self.assertEqual("png", job["imageFormat"])
            self.assertEqual("yuv420p", job["pixelFormat"])
            preview = Path(tmp) / "brolls" / first["review"]
            self.assertTrue(preview.is_file())
            sha = first["version"]["artifact"]["sha256"]
            self.assertEqual(64, len(sha))
            fail = run_cli(
                "graphics-render",
                "--occurrence",
                "stat-01",
                project=tmp,
                expect=2,
                env={"GB_GRAPHICS_WORKER": str(FAILING_WORKER)},
            )
            self.assertIn("intentional graphics worker failure", json.dumps(fail, ensure_ascii=False))
            second = run_cli("graphics-render", "--occurrence", "stat-01", project=tmp, env=env)
            self.assertEqual("v3", second["version"]["id"])
            self.assertEqual("v1", second["version"]["parent"])
            self.assertEqual(sha, file_digest(Path(tmp) / "brolls" / first["review"]))
            self.assertTrue((Path(tmp) / "brolls" / first["review"]).is_file())
            ledger = Ledger(tmp, recover=False)
            self.assertEqual("failed", ledger.data["graphics"]["versions"]["v2"]["status"])
            self.assertIsNone(ledger.data["graphics"]["versions"]["v2"]["artifact"])
            self.assertEqual("complete", ledger.data["graphics"]["versions"]["v1"]["status"])
            self.assertIsNone(ledger.data["graphics"]["versions"]["v1"]["approval"])
            frozen = ledger.data["graphics"]["versions"]["v1"]
            self.assertEqual("test-worker", frozen["fingerprints"]["runtime"]["kind"])
            self.assertRegex(frozen["artifact"]["sha256"], r"^[0-9a-f]{64}$")
            self.assertEqual("numeric-stat", frozen["template"])
            self.assertEqual("NumericStat", frozen["composition"])
            self.assertIn("narration", frozen["assignment"])
            page = Path(render(ledger)).read_text(encoding="utf-8")
            self.assertIn("Chapter &lt;b&gt;one&lt;/b&gt; &amp; &quot;quoted&quot; context.", page)
            self.assertIn("previews/graphics-stat-01-v3.mp4", page)
            self.assertTrue(
                'class="timing-basis estimated">Draft · VO timing pending</span>' in page
                and "Estimated duration 3 s · 90 frames" in page,
                "estimated timing must retain its draft badge and exact duration/frame count",
            )
            self.assertIn("Need a source?", page)
            payload = _review_payload(page)
            self.assertEqual([], payload["items"])
            self.assertEqual("estimated", payload["graphics"][0]["timing_basis"])
            status = run_cli("status", project=tmp)
            self.assertEqual(2, status["graphics"]["complete_versions"])
            self.assertEqual(0, status["graphics"]["pending"])
            self.assertTrue(status["graphics"]["items"][0]["ready"])
            executed = json.loads(
                (
                    Path(tmp) / "brolls" / "graphics" / "numeric-stat" / "v3" / "staging" / "executed-worker.json"
                ).read_text(encoding="utf-8")
            )
            frozen_worker = Path(tmp) / "brolls" / "graphics" / "numeric-stat" / "v3" / "inputs" / WORKER.name
            self.assertEqual(os.path.normcase(str(frozen_worker.resolve())), os.path.normcase(executed["file"]))
            self.assertNotEqual(os.path.normcase(str(WORKER.resolve())), os.path.normcase(executed["file"]))

    def test_candidate_review_stays_intact_with_graphics(self):
        with tempfile.TemporaryDirectory() as tmp:
            _project_with_rules(tmp)
            ledger = Ledger(tmp)
            item = candidate("local", "clip", "Synthetic")
            set_segment(item, 0, 1)
            item["approval"] = {
                "status": "approved",
                "by": "Human",
                "at": now(),
                "revision": 1,
                "channel": "chat",
                "statement": "ok",
            }
            ledger.add(item)
            ledger.save("fixture", item)
            run_cli(
                "graphics-assign",
                "--scene",
                "numeric-stat",
                "--occurrence",
                "stat-01",
                "--chapter",
                "ch-1",
                "--chapter-context",
                "Surrounding chapter text from the scenario.",
                "--purpose",
                "Show the count",
                "--narration",
                "The count stands at twelve units.",
                "--timing",
                "estimated",
                "--duration",
                "3",
                "--confirm-fps",
                "30",
                project=tmp,
            )
            ledger = Ledger(tmp, recover=False)
            self.assertEqual("approved", ledger.get("local:clip")["approval"]["status"])
            page = Path(render(ledger)).read_text(encoding="utf-8")
            payload = _review_payload(page)
            self.assertEqual(["local:clip"], [row["id"] for row in payload["items"]])
            self.assertIn("stat-01", page)
            exported = _review_payload(page)
            for row in exported["items"]:
                row["state"] = "rejected"
            reviews = Path(tmp) / "brolls" / "reviews"
            reviews.mkdir(parents=True, exist_ok=True)
            path = reviews / "20261010-120000.json"
            path.write_text(json.dumps(exported), encoding="utf-8")
            result = import_review(Ledger(tmp), path, "Human")
            self.assertEqual(1, result["imported"])


class ServeAllowlistTests(unittest.TestCase):
    def test_graphics_authoring_tree_is_not_served(self):
        from getbrolls import serve

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            brolls = root / "brolls"
            (brolls / "previews").mkdir(parents=True)
            (brolls / "graphics" / "numeric-stat" / "v1").mkdir(parents=True)
            (brolls / "review.html").write_text("<html></html>", encoding="utf-8")
            (brolls / "graphics" / "numeric-stat" / "v1" / "job.json").write_text("{}", encoding="utf-8")
            preview = brolls / "previews" / "graphics-stat-01-v1.mp4"
            preview.write_bytes(b"mp4")
            server, port = serve.start(root, port=0)
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                with urllib.request.urlopen(
                    f"http://127.0.0.1:{port}/previews/graphics-stat-01-v1.mp4", timeout=5
                ) as response:
                    self.assertEqual(200, response.status)
                with self.assertRaises(urllib.error.HTTPError) as ctx:
                    urllib.request.urlopen(f"http://127.0.0.1:{port}/graphics/numeric-stat/v1/job.json", timeout=5)
                self.assertEqual(404, ctx.exception.code)
            finally:
                server.shutdown()
                thread.join(timeout=5)
                server.server_close()


class DirectAssignTests(unittest.TestCase):
    def test_assign_command_does_not_invent_candidates(self):
        from getbrolls.graphics import assign_command

        with tempfile.TemporaryDirectory() as tmp:
            ledger = Ledger(tmp)
            assign_command(ledger, _assign_kwargs())
            self.assertEqual([], ledger.data["items"])
            self.assertIn("stat-01", ledger.data["graphics"]["occurrences"])
            occ = ledger.data["graphics"]["occurrences"]["stat-01"]
            self.assertEqual("numeric-stat", occ["scene_id"])
            self.assertEqual("numeric-stat", occ["template"])
            self.assertEqual("NumericStat", occ["composition"])


class PublicCliRegressionTests(unittest.TestCase):
    def test_clip_source_uses_staticfile_and_editorial_copy(self):
        source = (ROOT / "scripts" / "graphics" / "src" / "NumericStat.jsx").read_text(encoding="utf-8")
        self.assertIn("staticFile(", source)
        self.assertIn("cancelRender", source)
        self.assertIn("delayRender", source)
        self.assertIn("#d5c9b5", source)
        self.assertNotIn("#5c564c", source)
        self.assertIn("extraNote", source)
        self.assertNotIn('url("/fonts/', source)
        self.assertNotIn("style_revision", source)
        root = (ROOT / "scripts" / "graphics" / "src" / "Root.jsx").read_text(encoding="utf-8")
        self.assertIn('id="NumericStat"', root)
        self.assertNotIn("style_revision", root)

    def test_scene_identity_is_independent_of_template(self):
        with tempfile.TemporaryDirectory() as tmp:
            _project_with_rules(tmp)
            first = run_cli(
                "graphics-assign",
                "--scene",
                "units-count",
                "--template",
                "numeric-stat",
                "--occurrence",
                "occ-a",
                "--chapter",
                "ch-1",
                "--chapter-context",
                "Surrounding chapter text from the scenario.",
                "--purpose",
                "Show units",
                "--narration",
                "Twelve units.",
                "--timing",
                "estimated",
                "--duration",
                "3",
                project=tmp,
            )
            second = run_cli(
                "graphics-assign",
                "--scene",
                "dollar-amount",
                "--template",
                "numeric-stat",
                "--occurrence",
                "occ-b",
                "--chapter",
                "ch-1",
                "--chapter-context",
                "Surrounding chapter text from the scenario.",
                "--purpose",
                "Show dollars",
                "--narration",
                "Twelve dollars.",
                "--timing",
                "estimated",
                "--duration",
                "3",
                project=tmp,
            )
            third = run_cli(
                "graphics-assign",
                "--scene",
                "units-count",
                "--occurrence",
                "occ-c",
                "--chapter",
                "ch-2",
                "--chapter-context",
                "A later chapter keeps the same numeric concept.",
                "--purpose",
                "Show units again",
                "--narration",
                "Twelve units, later.",
                "--timing",
                "estimated",
                "--duration",
                "2",
                project=tmp,
            )
            self.assertEqual("units-count", first["occurrence"]["scene_id"])
            self.assertEqual("dollar-amount", second["occurrence"]["scene_id"])
            self.assertEqual("units-count", third["occurrence"]["scene_id"])
            self.assertEqual("numeric-stat", first["occurrence"]["template"])
            self.assertEqual("NumericStat", second["occurrence"]["composition"])
            self.assertEqual("occ-a", first["occurrence"]["occurrence_id"])
            self.assertEqual("occ-c", third["occurrence"]["occurrence_id"])

    def test_preserves_original_multiline_narration_and_chapter_context(self):
        narration = "First line.\nSecond line."
        chapter = "Opening paragraph.\n\nLater paragraph."
        anchor = "Anchor first line.\nAnchor second line."
        with tempfile.TemporaryDirectory() as tmp:
            _project_with_rules(tmp)
            assigned = run_cli(
                "graphics-assign",
                "--scene",
                "numeric-stat",
                "--occurrence",
                "stat-01",
                "--chapter",
                "ch-1",
                "--chapter-context",
                chapter,
                "--purpose",
                "Show the count",
                "--narration",
                narration,
                "--timing",
                "estimated",
                "--duration",
                "3",
                "--anchor",
                anchor,
                project=tmp,
            )
            self.assertEqual(narration, assigned["occurrence"]["narration"])
            self.assertEqual(chapter, assigned["occurrence"]["chapter_context"])
            self.assertEqual(anchor, assigned["occurrence"]["anchors"][0]["text"])
            ledger = Ledger(tmp, recover=False)
            stored = ledger.data["graphics"]["occurrences"]["stat-01"]
            self.assertEqual(narration, stored["narration"])
            self.assertEqual(chapter, stored["chapter_context"])
            self.assertEqual(anchor, stored["anchors"][0]["text"])

    def test_parent_junction_and_ads_refs_are_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            _project_with_rules(tmp)
            root = Path(tmp)
            outside_dir = root / "outside"
            outside_dir.mkdir()
            sentinel = outside_dir / "sentinel.mp4"
            sentinel.write_bytes(b"OUTSIDE-SENTINEL")
            before = hashlib.sha256(sentinel.read_bytes()).hexdigest()
            escape = root / "brolls" / "previews" / "escape"
            linked = _make_dir_link(escape, outside_dir)
            colon = run_cli(
                "graphics-assign",
                "--scene",
                "numeric-stat",
                "--occurrence",
                "stat-01",
                "--chapter",
                "ch-1",
                "--chapter-context",
                "Surrounding chapter text from the scenario.",
                "--purpose",
                "Show the count",
                "--narration",
                "The count stands at twelve units.",
                "--timing",
                "estimated",
                "--duration",
                "3",
                "--asset-ref",
                "previews/clip.mp4:zone.identifier",
                project=tmp,
                expect=2,
            )
            self.assertIn("relative posix", json.dumps(colon, ensure_ascii=False))
            if not linked:
                self.skipTest("could not create a parent junction or directory symlink")
            refused = run_cli(
                "graphics-assign",
                "--scene",
                "numeric-stat",
                "--occurrence",
                "stat-01",
                "--chapter",
                "ch-1",
                "--chapter-context",
                "Surrounding chapter text from the scenario.",
                "--purpose",
                "Show the count",
                "--narration",
                "The count stands at twelve units.",
                "--timing",
                "estimated",
                "--duration",
                "3",
                "--asset-ref",
                "previews/escape/sentinel.mp4",
                project=tmp,
                expect=2,
            )
            message = json.dumps(refused, ensure_ascii=False)
            self.assertIn("outside", message.lower())
            self.assertEqual(before, hashlib.sha256(sentinel.read_bytes()).hexdigest())
            self.assertTrue(sentinel.is_file())
            ledger = Ledger(tmp, recover=False)
            self.assertEqual({}, ledger.data.get("graphics", {}).get("occurrences", {}))

    def test_status_rejects_malformed_complete_version_without_rewriting(self):
        with tempfile.TemporaryDirectory() as tmp:
            _project_with_rules(tmp)
            run_cli(
                "graphics-assign",
                "--scene",
                "numeric-stat",
                "--occurrence",
                "stat-01",
                "--chapter",
                "ch-1",
                "--chapter-context",
                "Surrounding chapter text from the scenario.",
                "--purpose",
                "Show the count",
                "--narration",
                "The count stands at twelve units.",
                "--timing",
                "estimated",
                "--duration",
                "3",
                project=tmp,
            )
            manifest = Path(tmp) / "brolls" / "manifest.json"
            data = json.loads(manifest.read_text(encoding="utf-8"))
            data["graphics"]["occurrences"]["stat-01"]["current_version"] = "v1"
            data["graphics"]["versions"]["v1"] = {
                "id": "v1",
                "occurrence_id": "stat-01",
                "status": "complete",
                "artifact": {
                    "path": "previews/graphics-stat-01-v1.mp4",
                    "sha256": "z" * 64,
                },
            }
            manifest.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            before = manifest.read_bytes()
            payload = run_cli("status", project=tmp, expect=2)
            dumped = json.dumps(payload, ensure_ascii=False)
            self.assertIn("Preserve", dumped)
            self.assertIn("Invalid graphics records", dumped)
            self.assertEqual(before, manifest.read_bytes())
            self.assertFalse((Path(tmp) / "brolls" / ".pending-transaction.json").exists())

    def test_status_rejects_bool_current_style_revision_without_rewriting(self):
        with tempfile.TemporaryDirectory() as tmp:
            _project_with_rules(tmp)
            run_cli(
                "graphics-assign",
                "--scene",
                "numeric-stat",
                "--occurrence",
                "stat-01",
                "--chapter",
                "ch-1",
                "--chapter-context",
                "Surrounding chapter text from the scenario.",
                "--purpose",
                "Show the count",
                "--narration",
                "The count stands at twelve units.",
                "--timing",
                "estimated",
                "--duration",
                "3",
                project=tmp,
            )
            manifest = Path(tmp) / "brolls" / "manifest.json"
            data = json.loads(manifest.read_text(encoding="utf-8"))
            data["graphics"]["current_style_revision"] = True
            manifest.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            before = manifest.read_bytes()
            payload = run_cli("status", project=tmp, expect=2)
            dumped = json.dumps(payload, ensure_ascii=False)
            self.assertIn("Preserve", dumped)
            self.assertIn(PRESERVE, dumped)
            self.assertEqual(before, manifest.read_bytes())


@skip_unless_ffmpeg
class FrozenVersionAndStagingTests(unittest.TestCase):
    def test_orphan_version_dir_is_skipped_not_reused(self):
        with tempfile.TemporaryDirectory() as tmp:
            _project_with_rules(tmp)
            run_cli(
                "graphics-assign",
                "--scene",
                "numeric-stat",
                "--occurrence",
                "stat-01",
                "--chapter",
                "ch-1",
                "--chapter-context",
                "Surrounding chapter text from the scenario.",
                "--purpose",
                "Show the count",
                "--narration",
                "The count stands at twelve units.",
                "--timing",
                "estimated",
                "--duration",
                "3",
                project=tmp,
            )
            orphan = Path(tmp) / "brolls" / "graphics" / "numeric-stat" / "v1"
            orphan.mkdir(parents=True)
            marker = orphan / "orphan.txt"
            marker.write_text("keep", encoding="utf-8")
            rendered = run_cli(
                "graphics-render",
                "--occurrence",
                "stat-01",
                project=tmp,
                env={"GB_GRAPHICS_WORKER": str(WORKER)},
            )
            self.assertEqual("v2", rendered["version"]["id"])
            self.assertTrue(marker.is_file())
            self.assertEqual("keep", marker.read_text(encoding="utf-8"))
            self.assertTrue((Path(tmp) / "brolls" / rendered["review"]).is_file())

    def test_saved_version_stays_paired_with_frozen_assignment(self):
        with tempfile.TemporaryDirectory() as tmp:
            _project_with_rules(tmp)
            run_cli(
                "graphics-assign",
                "--scene",
                "numeric-stat",
                "--occurrence",
                "stat-01",
                "--chapter",
                "ch-1",
                "--chapter-context",
                "Original chapter context.",
                "--purpose",
                "Show the count",
                "--narration",
                "The count stands at twelve units.",
                "--anchor",
                "<Original & anchor>\nsecond original line",
                "--timing",
                "estimated",
                "--duration",
                "3",
                project=tmp,
            )
            env = {"GB_GRAPHICS_WORKER": str(WORKER)}
            first = run_cli("graphics-render", "--occurrence", "stat-01", project=tmp, env=env)
            self.assertEqual("v1", first["version"]["id"])
            run_cli(
                "graphics-assign",
                "--scene",
                "numeric-stat",
                "--occurrence",
                "stat-01",
                "--chapter",
                "ch-1",
                "--chapter-context",
                "Changed chapter context.",
                "--purpose",
                "Show the count",
                "--narration",
                "The count now claims twenty units.",
                "--anchor",
                "<Changed & anchor>",
                "--timing",
                "estimated",
                "--duration",
                "4",
                project=tmp,
            )
            ledger = Ledger(tmp, recover=False)
            run_cli("review", project=tmp)
            page = (Path(tmp) / "brolls" / "review.html").read_text(encoding="utf-8")
            self.assertIn("The count stands at twelve units.", page)
            self.assertIn("Saved version remains paired with the frozen assignment from render time.", page)
            self.assertIn("graphics-pending-changes", page)
            self.assertIn("Current narration: The count now claims twenty units.", page)
            saved_card, pending = page.split('<div class="graphics-pending-changes">', 1)
            self.assertIn("Scenario anchors:", saved_card)
            self.assertIn("&lt;Original &amp; anchor&gt;\nsecond original line", saved_card)
            self.assertNotIn("&lt;Changed &amp; anchor&gt;", saved_card)
            self.assertIn("Current scenario anchors:", pending)
            self.assertIn("&lt;Changed &amp; anchor&gt;", pending)
            self.assertNotIn("<Original & anchor>", page)
            self.assertNotIn("<Changed & anchor>", page)
            self.assertIn("Estimated duration 3 s · 90 frames", saved_card)
            self.assertNotIn("Explicit ", saved_card)
            self.assertNotIn("graphics-anchor-time", saved_card.split("<body", 1)[-1])
            self.assertIn("Current timing: Estimated duration 4 s · 120 frames", pending)
            version = ledger.data["graphics"]["versions"]["v1"]
            self.assertEqual("The count stands at twelve units.", version["assignment"]["narration"])
            self.assertEqual(90, version["timing"]["duration_in_frames"])
            self.assertEqual(
                "The count now claims twenty units.", ledger.data["graphics"]["occurrences"]["stat-01"]["narration"]
            )
            status = run_cli("status", project=tmp)
            self.assertEqual(1, status["graphics"]["complete_versions"])
            self.assertEqual(1, status["graphics"]["pending"])
            self.assertFalse(status["graphics"]["items"][0]["ready"])

    def test_public_review_shows_zero_anchor_and_explicit_interval(self):
        with tempfile.TemporaryDirectory() as tmp:
            _project_with_rules(tmp)
            run_cli(
                "graphics-assign",
                "--scene",
                "zero-anchor",
                "--occurrence",
                "zero-01",
                "--chapter",
                "ch-1",
                "--chapter-context",
                "Original chapter context.",
                "--purpose",
                "Show the starting figure",
                "--narration",
                "Original narration.",
                "--anchor",
                "0:<Inicio & cifra>\nsegunda línea",
                "--timing",
                "explicit",
                "--start",
                "0",
                "--end",
                "1.5",
                project=tmp,
            )
            run_cli("review", project=tmp)
            page = (Path(tmp) / "brolls" / "review.html").read_text(encoding="utf-8")
            self.assertIn(
                '<span class="graphics-anchor-time">0 s</span> &lt;Inicio &amp; cifra&gt;\nsegunda línea', page
            )
            self.assertIn("Explicit 0–1.5 s (frames 0–45) · Duration 1.5 s · 45 frames", page)
            self.assertNotIn("<Inicio & cifra>", page)
            self.assertIn("Pending graphics assignment", page)

    def test_question_after_saved_version_is_pending_and_visible(self):
        with tempfile.TemporaryDirectory() as tmp:
            _project_with_rules(tmp)
            run_cli(
                "graphics-assign",
                "--scene",
                "numeric-stat",
                "--occurrence",
                "stat-01",
                "--chapter",
                "ch-1",
                "--chapter-context",
                "Original chapter context.",
                "--purpose",
                "Show the count",
                "--narration",
                "The count stands at twelve units.",
                "--timing",
                "estimated",
                "--duration",
                "3",
                project=tmp,
            )
            env = {"GB_GRAPHICS_WORKER": str(WORKER)}
            run_cli("graphics-render", "--occurrence", "stat-01", project=tmp, env=env)
            run_cli(
                "graphics-assign",
                "--scene",
                "numeric-stat",
                "--occurrence",
                "stat-01",
                "--chapter",
                "ch-1",
                "--chapter-context",
                "Original chapter context.",
                "--purpose",
                "Show the count",
                "--narration",
                "The count stands at twelve units.",
                "--timing",
                "estimated",
                "--duration",
                "3",
                "--question",
                "NEW QUESTION AFTER SAVED VERSION",
                project=tmp,
            )
            status = run_cli("status", project=tmp)
            self.assertEqual(1, status["graphics"]["complete_versions"])
            self.assertEqual(1, status["graphics"]["pending"])
            self.assertFalse(status["graphics"]["items"][0]["ready"])
            page = Path(render(Ledger(tmp, recover=False))).read_text(encoding="utf-8")
            self.assertIn("The count stands at twelve units.", page)
            self.assertIn("NEW QUESTION AFTER SAVED VERSION", page)
            self.assertIn("Current unresolved questions:", page)
            self.assertIn("graphics-pending-changes", page)

    def test_distinct_refs_keep_collision_free_frozen_paths(self):
        with tempfile.TemporaryDirectory() as tmp:
            _project_with_rules(tmp)
            root = Path(tmp) / "brolls"
            first = root / "previews" / "a__b" / "c.txt"
            second = root / "previews" / "a" / "b__c.txt"
            first.parent.mkdir(parents=True)
            second.parent.mkdir(parents=True)
            first.write_text("one", encoding="utf-8")
            second.write_text("two", encoding="utf-8")
            run_cli(
                "graphics-assign",
                "--scene",
                "numeric-stat",
                "--occurrence",
                "stat-01",
                "--chapter",
                "ch-1",
                "--chapter-context",
                "Surrounding chapter text from the scenario.",
                "--purpose",
                "Show the count",
                "--narration",
                "The count stands at twelve units.",
                "--timing",
                "estimated",
                "--duration",
                "3",
                "--asset-ref",
                "previews/a__b/c.txt",
                "--asset-ref",
                "previews/a/b__c.txt",
                project=tmp,
            )
            rendered = run_cli(
                "graphics-render",
                "--occurrence",
                "stat-01",
                project=tmp,
                env={"GB_GRAPHICS_WORKER": str(WORKER)},
            )
            self.assertEqual("complete", rendered["version"]["status"])
            version_dir = Path(tmp) / "brolls" / "graphics" / "numeric-stat" / "v1"
            frozen_first = version_dir / "inputs" / "refs" / "previews" / "a__b" / "c.txt"
            frozen_second = version_dir / "inputs" / "refs" / "previews" / "a" / "b__c.txt"
            self.assertEqual("one", frozen_first.read_text(encoding="utf-8"))
            self.assertEqual("two", frozen_second.read_text(encoding="utf-8"))
            self.assertFalse((version_dir / "inputs" / "refs" / "previews__a__b__c.txt").exists())
            inputs = rendered["version"]["fingerprints"]["inputs"]
            self.assertEqual("inputs/refs/previews/a__b/c.txt", inputs["previews/a__b/c.txt"]["frozen"])
            self.assertEqual("inputs/refs/previews/a/b__c.txt", inputs["previews/a/b__c.txt"]["frozen"])
            self.assertNotEqual(inputs["previews/a__b/c.txt"]["sha256"], inputs["previews/a/b__c.txt"]["sha256"])

    def test_complete_version_mutations_are_rejected_without_rewriting(self):
        with tempfile.TemporaryDirectory() as tmp:
            _project_with_rules(tmp)
            run_cli(
                "graphics-assign",
                "--scene",
                "numeric-stat",
                "--occurrence",
                "stat-01",
                "--chapter",
                "ch-1",
                "--chapter-context",
                "Surrounding chapter text from the scenario.",
                "--purpose",
                "Show the count",
                "--narration",
                "The count stands at twelve units.",
                "--timing",
                "estimated",
                "--duration",
                "3",
                project=tmp,
            )
            run_cli(
                "graphics-render",
                "--occurrence",
                "stat-01",
                project=tmp,
                env={"GB_GRAPHICS_WORKER": str(WORKER)},
            )
            manifest = Path(tmp) / "brolls" / "manifest.json"

            def reject_mutation(mutate):
                valid = manifest.read_bytes()
                data = json.loads(valid)
                mutate(data)
                manifest.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
                mutated = manifest.read_bytes()
                payload = run_cli("status", project=tmp, expect=2)
                dumped = json.dumps(payload, ensure_ascii=False)
                self.assertIn("Preserve", dumped)
                self.assertEqual(mutated, manifest.read_bytes())
                manifest.write_bytes(valid)

            def drop_source(data):
                del data["graphics"]["versions"]["v1"]["fingerprints"]["source"]

            def dict_question(data):
                data["graphics"]["versions"]["v1"]["assignment"]["questions"] = [{"text": "not a string"}]

            def self_parent(data):
                data["graphics"]["versions"]["v1"]["parent"] = "v1"

            reject_mutation(drop_source)
            reject_mutation(dict_question)
            reject_mutation(self_parent)
            restored = json.loads(manifest.read_text(encoding="utf-8"))
            self.assertIn("source", restored["graphics"]["versions"]["v1"]["fingerprints"])
            self.assertEqual([], restored["graphics"]["versions"]["v1"]["assignment"]["questions"])
            self.assertIsNone(restored["graphics"]["versions"]["v1"]["parent"])

    def test_freeze_oserror_marks_incomplete_and_does_not_reuse_identity(self):
        with tempfile.TemporaryDirectory() as tmp:
            _project_with_rules(tmp)
            run_cli(
                "graphics-assign",
                "--scene",
                "numeric-stat",
                "--occurrence",
                "stat-01",
                "--chapter",
                "ch-1",
                "--chapter-context",
                "Surrounding chapter text from the scenario.",
                "--purpose",
                "Show the count",
                "--narration",
                "The count stands at twelve units.",
                "--timing",
                "estimated",
                "--duration",
                "3",
                project=tmp,
            )
            worker = str(WORKER.resolve())
            self.assertTrue(Path(worker).is_file())
            ledger = Ledger(tmp, recover=False)
            previous = os.environ.get("GB_GRAPHICS_WORKER")
            os.environ["GB_GRAPHICS_WORKER"] = worker
            try:
                with (
                    patch(
                        "getbrolls.graphics._copy_checked",
                        side_effect=OSError("disk full while freezing graphics inputs"),
                    ),
                    self.assertRaises(ValueError) as ctx,
                ):
                    render_command(ledger, SimpleNamespace(occurrence="stat-01"))
            finally:
                if previous is None:
                    os.environ.pop("GB_GRAPHICS_WORKER", None)
                else:
                    os.environ["GB_GRAPHICS_WORKER"] = previous
            message = str(ctx.exception).lower()
            self.assertIn("freeze or publish", message)
            self.assertIn("disk full", message)
            saved = Ledger(tmp, recover=False)
            failed = saved.data["graphics"]["versions"]["v1"]
            self.assertEqual("failed", failed["status"])
            self.assertIsNone(failed["artifact"])
            self.assertIn("disk full", (failed.get("diagnostics") or {}).get("message", "").lower())
            self.assertFalse((Path(tmp) / "brolls" / "previews" / "graphics-stat-01-v1.mp4").exists())
            second = run_cli(
                "graphics-render",
                "--occurrence",
                "stat-01",
                project=tmp,
                env={"GB_GRAPHICS_WORKER": worker},
            )
            self.assertEqual("v2", second["version"]["id"])
            self.assertEqual("complete", second["version"]["status"])
            self.assertEqual("failed", Ledger(tmp, recover=False).data["graphics"]["versions"]["v1"]["status"])


class BrowserMarkerAndDecodeTests(unittest.TestCase):
    def test_stale_marker_text_is_not_readiness(self):
        with tempfile.TemporaryDirectory() as tmp:
            marker = Path(tmp) / "marker"
            marker.write_text("2026-10-10T00:00:00Z", encoding="utf-8")
            self.assertIsNone(_browser_record(marker))
            missing = Path(tmp) / "missing.exe"
            marker.write_text(
                json.dumps({"executable": str(missing), "type": "user-defined-path"}),
                encoding="utf-8",
            )
            record = _browser_record(marker)
            self.assertFalse(_marker_matches_live(record, {"type": "no-browser"}))
            self.assertFalse(_marker_matches_live(record, {"type": "local-puppeteer-browser", "path": str(missing)}))

    @skip_unless_ffmpeg
    def test_verify_rejects_unexpected_audio(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "with-audio.mp4"
            done = subprocess.run(
                [
                    "ffmpeg",
                    "-y",
                    "-v",
                    "error",
                    "-f",
                    "lavfi",
                    "-i",
                    "testsrc=size=1920x1080:rate=30",
                    "-f",
                    "lavfi",
                    "-i",
                    "sine=frequency=440:sample_rate=48000",
                    "-frames:v",
                    "30",
                    "-shortest",
                    "-c:v",
                    "libx264",
                    "-pix_fmt",
                    "yuv420p",
                    "-c:a",
                    "aac",
                    str(path),
                ],
                capture_output=True,
                text=True,
                encoding="utf-8",
                check=False,
            )
            if done.returncode != 0:
                self.skipTest(done.stderr or "ffmpeg could not write an audio fixture")
            with self.assertRaises(ValueError) as ctx:
                _verify_complete(path, default_profile(), 30)
            self.assertIn("audio", str(ctx.exception).lower())

    def test_probe_rejects_missing_decoded_frames_and_inconsistent_rates(self):
        from getbrolls import graphics as g

        video = {
            "codec_type": "video",
            "codec_name": "h264",
            "width": 1920,
            "height": 1080,
            "avg_frame_rate": "30/1",
            "r_frame_rate": "30/1",
            "nb_frames": "30",
            "pix_fmt": "yuv420p",
            "duration": "1.0",
        }
        original = g._probe_json
        try:
            g._probe_json = lambda _path, _extra: {
                "streams": [dict(video)],
                "format": {"duration": "1.0", "nb_streams": 1},
            }
            with self.assertRaises(ValueError) as missing_frames:
                _probe_artifact(Path("missing-frames.mp4"))
            self.assertIn("decoded frame", str(missing_frames.exception).lower())

            inconsistent = dict(video, nb_read_frames="30", avg_frame_rate="24/1")
            g._probe_json = lambda _path, _extra: {
                "streams": [inconsistent],
                "format": {"duration": "1.0", "nb_streams": 1},
            }
            with self.assertRaises(ValueError) as rates:
                _probe_artifact(Path("inconsistent-rate.mp4"))
            self.assertIn("inconsistent", str(rates.exception).lower())

            g._probe_json = lambda _path, _extra: {
                "streams": [
                    dict(video, nb_read_frames="30"),
                    {"codec_type": "audio", "codec_name": "aac"},
                ],
                "format": {"duration": "1.0", "nb_streams": 2},
            }
            with self.assertRaises(ValueError) as audio:
                _probe_artifact(Path("with-audio.mp4"))
            self.assertIn("audio", str(audio.exception).lower())
        finally:
            g._probe_json = original


def _make_dir_link(link, target):
    link = Path(link)
    target = Path(target)
    link.parent.mkdir(parents=True, exist_ok=True)
    try:
        link.symlink_to(target, target_is_directory=True)
        return link.exists()
    except OSError:
        done = subprocess.run(
            ["cmd", "/c", "mklink", "/J", str(link), str(target)],
            capture_output=True,
            text=True,
            encoding="utf-8",
            check=False,
        )
        return done.returncode == 0 and link.exists()


if __name__ == "__main__":
    unittest.main()
