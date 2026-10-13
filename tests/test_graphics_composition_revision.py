"""Composition revisions retain occurrence identity and immutable review history."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

import _isolation  # noqa: F401
from _cli import run_cli
from _media import skip_unless_ffmpeg
from _paths import ROOT
from test_graphics_facts_workflow import _approve
from test_graphics_review import _assign, _project, _render, _review_payload, _version_hashes, _write_review
from test_graphics_scenes import scene_fixture, write
from test_graphics_timeline import assign_timeline, timeline_file

from getbrolls.graphics import _assignment_diffs
from getbrolls.ledger import Ledger, digest


def reassign(project, occurrence, template, *, opt_in=True, expect=0, source=None):  # noqa: PLR0913 - Exercise explicit consent, source permission and refusal independently.
    old = Ledger(project, recover=False).data["graphics"]["occurrences"][occurrence]
    args = ["graphics-assign", "--occurrence", occurrence, "--scene", old["scene_id"], "--template", template]
    for field in ("chapter", "chapter-context", "purpose", "narration"):
        key = "chapter_id" if field == "chapter" else field.replace("-", "_")
        args += ["--" + field, old[key]]
    args += ["--timing", "explicit", "--start", str(old["timing"]["start_s"]), "--end", str(old["timing"]["end_s"])]
    args += ["--claim-status", "synthetic"]
    if opt_in:
        args += ["--replace-template"]
    if source:
        args += [
            "--asset-ref",
            source,
            "--material-use",
            json.dumps(
                {
                    "ref": source,
                    "rendered_use": "permitted",
                    "raw_redistribution": "permitted",
                    "evidence": ["Locally authored synthetic JSX."],
                    "conditions": "Synthetic fixture only.",
                }
            ),
        ]
    return run_cli(*args, project=project, expect=expect)


class AssignmentCompositionIdentityTests(unittest.TestCase):
    def test_composition_alone_invalidates_assignment_identity(self):
        self.assertEqual(
            ["template", "composition"],
            _assignment_diffs(
                {"template": "numeric-stat", "composition": "NumericStat"},
                {"template": "custom", "composition": "CustomScene"},
            ),
        )


@skip_unless_ffmpeg
class CompositionRevisionWorkflowTests(unittest.TestCase):
    def test_numeric_to_custom_fulfills_request_without_overwriting_reviewed_version(self):
        with tempfile.TemporaryDirectory() as tmp:
            _project(tmp)
            _assign(tmp, timing="explicit", start=0, end=2)
            _render(tmp)
            _approve(tmp, "stat-01", "v1")
            payload = _review_payload(tmp)
            payload["graphics"][0].update(state="changes", comment="Replace the count with a comparison chart.")
            review = _write_review(tmp, payload)
            run_cli("import-review", "--file", str(review), "--by", "Synthetic reviewer", project=tmp)
            before = Ledger(tmp, recover=False).data["graphics"]
            hashes = _version_hashes(tmp, "numeric-stat", "v1")
            denied = reassign(tmp, "stat-01", "custom", opt_in=False, expect=2)
            self.assertIn("--replace-template", json.dumps(denied))
            self.assertEqual(before, Ledger(tmp, recover=False).data["graphics"])
            root = Path(tmp) / "brolls"
            source = root / "graphics-data/chart.jsx"
            source.parent.mkdir(parents=True, exist_ok=True)
            source.write_text("export const AuthorScene = () => <div>Synthetic chart</div>;\n", encoding="utf-8")
            reassign(tmp, "stat-01", "custom", source="graphics-data/chart.jsx")
            pending = run_cli("status", project=tmp)["graphics"]
            self.assertEqual(1, pending["pending"])
            self.assertFalse(pending["items"][0]["deliverable"])
            content = write(
                root / "graphics-data/content.json",
                {
                    "schema_version": 1,
                    "kind": "custom",
                    "title": "Synthetic chart",
                    "caption": "Synthetic fixture",
                    "beats": [{"id": "chart", "label": "Synthetic comparison", "fact_id": "chart", "at_s": 0}],
                    "source_ref": "graphics-data/chart.jsx",
                    "source_sha256": digest(source),
                    "data": {"values": [12, 8]},
                },
            )
            run_cli("graphics-content", "--occurrence", "stat-01", "--file", str(content), project=tmp)
            new = _render(tmp)["version"]
            self.assertEqual(
                ("v2", "v1", "custom", "CustomScene"),
                (new["id"], new["parent"], new["template"], new["composition"]),
            )
            self.assertIsNone(new["approval"])
            self.assertEqual(before["versions"]["v1"], Ledger(tmp, recover=False).data["graphics"]["versions"]["v1"])
            self.assertEqual(hashes, _version_hashes(tmp, "numeric-stat", "v1"))
            self.assertEqual("The count stands at twelve units.", new["assignment"]["narration"])
            request = before["requests"][0]["id"]
            run_cli(
                "graphics-request-complete",
                "--request",
                request,
                "--version",
                "v2",
                "--outcome",
                "Synthetic comparison created.",
                project=tmp,
            )
            replay = run_cli("import-review", "--file", str(review), "--by", "Synthetic reviewer", project=tmp)
            self.assertEqual("already_processed", replay["unchanged"][0]["reason"])
            rows = _review_payload(tmp)["graphics"]
            self.assertEqual({"v1", "v2"}, {r["version"] for r in rows})
            run_cli("graphics-select", "--occurrence", "stat-01", "--version", "v1", project=tmp)
            self.assertEqual(
                "v1", Ledger(tmp, recover=False).data["graphics"]["occurrences"]["stat-01"]["current_version"]
            )
            self.assertEqual(hashes, _version_hashes(tmp, "numeric-stat", "v1"))

    def test_incompatible_authored_content_is_removed_and_compatible_content_is_retained(self):
        for kind in ("map", "custom", "timeline"):
            with self.subTest(kind=kind), tempfile.TemporaryDirectory() as tmp:
                _project(tmp)
                if kind == "timeline":
                    assign_timeline(tmp, claim="synthetic")
                    occurrence, key = "history-01", "timeline"
                    file = timeline_file(tmp)
                    run_cli("graphics-timeline", "--occurrence", occurrence, "--file", str(file), project=tmp)
                else:
                    file, _record = scene_fixture(tmp, kind)
                    occurrence, key = "scene-01", "scene_content"
                    run_cli("graphics-content", "--occurrence", occurrence, "--file", str(file), project=tmp)
                original = Ledger(tmp, recover=False).data["graphics"]["occurrences"][occurrence][key]
                source = "graphics-data/AuthorScene.jsx" if kind == "custom" else None
                reassign(tmp, occurrence, kind, source=source)
                self.assertEqual(original, Ledger(tmp, recover=False).data["graphics"]["occurrences"][occurrence][key])
                reassign(tmp, occurrence, "numeric-stat")
                self.assertNotIn(key, Ledger(tmp, recover=False).data["graphics"]["occurrences"][occurrence])

    def test_template_replacement_does_not_reset_consumed_repairs(self):
        with tempfile.TemporaryDirectory() as tmp:
            _project(tmp)
            _assign(tmp, timing="explicit", start=0, end=2)
            failed = {"GB_GRAPHICS_WORKER": str(ROOT / "tests/fixtures/graphics_worker_fail.py")}
            run_cli("graphics-render", "--occurrence", "stat-01", project=tmp, env=failed, expect=2)
            run_cli("graphics-render", "--occurrence", "stat-01", "--repair", project=tmp, env=failed, expect=2)
            work = Ledger(tmp, recover=False).data["graphics"]["occurrences"]["stat-01"]["work"]
            self.assertEqual(1, len(work["repairs"]))
            reassign(tmp, "stat-01", "custom")
            self.assertEqual(work, Ledger(tmp, recover=False).data["graphics"]["occurrences"]["stat-01"]["work"])


if __name__ == "__main__":
    unittest.main()
