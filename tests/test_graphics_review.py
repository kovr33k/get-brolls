"""#54 slice A: version-specific graphics approval, select, and saved requests."""

from __future__ import annotations

import copy
import json
import re
import tempfile
import threading
import unittest
import urllib.request
from contextlib import contextmanager
from pathlib import Path
from unittest import mock

import _isolation  # noqa: F401
from _cli import run_cli
from _media import skip_unless_ffmpeg
from _paths import ROOT

from getbrolls import serve
from getbrolls.cli import FORMAT_GATE_SUBCOMMANDS
from getbrolls.graphics import MAX_TEXT, PRESERVE
from getbrolls.ledger import Ledger
from getbrolls.ledger import digest as file_digest
from getbrolls.models import candidate, set_segment
from getbrolls.rendering import render
from getbrolls.review import REVIEW_TEMPLATE_VERSION, import_review

WORKER = ROOT / "tests" / "fixtures" / "graphics_worker.py"
ENV = {"GB_GRAPHICS_WORKER": str(WORKER)}


def _project(tmp):
    run_cli("init-rules", project=tmp)
    return tmp


def _assign(tmp, occurrence="stat-01", scene="numeric-stat", **flags):
    args = [
        "graphics-assign",
        "--scene",
        scene,
        "--occurrence",
        occurrence,
        "--chapter",
        flags.get("chapter", "ch-1"),
        "--chapter-context",
        flags.get("chapter_context", "Surrounding chapter text from the scenario."),
        "--purpose",
        flags.get("purpose", "Show the count"),
        "--narration",
        flags.get("narration", "The count stands at twelve units."),
        "--timing",
        flags.get("timing", "estimated"),
    ]
    if flags.get("timing", "estimated") == "estimated":
        args += ["--duration", str(flags.get("duration", "3"))]
    else:
        args += ["--start", str(flags.get("start", "0")), "--end", str(flags.get("end", "1.5"))]
    if flags.get("question"):
        args += ["--question", flags["question"]]
    if flags.get("confirm_fps"):
        args += ["--confirm-fps", str(flags["confirm_fps"])]
    run_cli(*args, project=tmp)


def _render(tmp, occurrence="stat-01"):
    return run_cli("graphics-render", "--occurrence", occurrence, project=tmp, env=ENV)


def _review_payload(tmp):
    run_cli("review", project=tmp)
    page = (Path(tmp) / "brolls" / "review.html").read_text(encoding="utf-8")
    match = re.search(r"window.GETBROLLS_REVIEW=(.*?);</script>", page)
    if match is None:
        raise AssertionError("GETBROLLS_REVIEW payload is missing")
    return json.loads(match.group(1))


def _write_review(tmp, payload, name="20261010-120000.json"):
    folder = Path(tmp) / "brolls" / "reviews"
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / name
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def _version_hashes(tmp, scene, version):
    base = Path(tmp) / "brolls" / "graphics" / scene / version
    rels = [
        "source/index.jsx",
        "source/Root.jsx",
        "source/NumericStat.jsx",
        "assignment.json",
        "style.json",
        "props.json",
        "fingerprints.json",
        "job.json",
        "inputs/graphics_worker.py",
    ]
    hashed = {}
    for rel in rels:
        path = base.joinpath(*rel.split("/"))
        if path.is_file():
            hashed[rel] = file_digest(path)
    preview = Path(tmp) / "brolls" / "previews" / f"graphics-stat-01-{version}.mp4"
    if version.startswith("v") and preview.is_file():
        hashed["preview"] = file_digest(preview)
    return hashed


@skip_unless_ffmpeg
class GraphicsApprovalImportTests(unittest.TestCase):
    def test_graphics_only_approval_import(self):
        with tempfile.TemporaryDirectory() as tmp:
            _project(tmp)
            _assign(tmp)
            rendered = _render(tmp)
            self.assertFalse(rendered["approved"])
            payload = _review_payload(tmp)
            self.assertEqual([], payload["items"])
            self.assertEqual(REVIEW_TEMPLATE_VERSION, payload["templateVersion"])
            self.assertTrue(payload["graphics"])
            payload["graphics"][0]["state"] = "approved"
            payload["graphics"][0]["comment"] = "Synthetic fixture approval for tests only."
            path = _write_review(tmp, payload)
            result = run_cli("import-review", "--file", str(path), "--by", "Human", project=tmp)
            self.assertGreaterEqual(result["imported"], 1)
            ledger = Ledger(tmp, recover=False)
            approval = ledger.data["graphics"]["versions"]["v1"]["approval"]
            self.assertEqual("approved", approval["status"])
            self.assertEqual("storyboard", approval["channel"])
            self.assertEqual("v1", approval["version_id"])
            status = run_cli("status", project=tmp)
            self.assertTrue(status["graphics"]["items"][0]["approved"])
            self.assertFalse(status["graphics"]["items"][0]["deliverable"])
            self.assertIn("estimated_timing", status["graphics"]["items"][0]["reasons"])

    def test_mixed_valid_candidate_and_stale_graphics_partial_import(self):
        with tempfile.TemporaryDirectory() as tmp:
            _project(tmp)
            ledger = Ledger(tmp)
            item = candidate("local", "clip", "Synthetic")
            set_segment(item, 0, 1)
            item["approval"] = {
                "status": "pending",
                "by": None,
                "at": None,
                "revision": 1,
            }
            ledger.add(item)
            ledger.save("fixture", item)
            _assign(tmp, confirm_fps=30)
            _render(tmp)
            payload = _review_payload(tmp)
            self.assertEqual(["local:clip"], [row["id"] for row in payload["items"]])
            payload["items"][0]["state"] = "approved"
            payload["graphics"][0]["state"] = "approved"
            payload["graphics"][0]["signature"] = "0" * 64
            path = _write_review(tmp, payload)
            result = run_cli("import-review", "--file", str(path), "--by", "Human", project=tmp)
            self.assertEqual(1, result["imported"])
            self.assertTrue(result["skipped"])
            self.assertEqual("signature_mismatch", result["skipped"][0]["reason"])
            fresh = Ledger(tmp, recover=False)
            self.assertEqual("approved", fresh.get("local:clip")["approval"]["status"])
            self.assertIsNone(fresh.data["graphics"]["versions"]["v1"]["approval"])

    def test_statement_approval_and_modified_files_keep_old_state(self):
        with tempfile.TemporaryDirectory() as tmp:
            _project(tmp)
            _assign(tmp)
            _render(tmp)
            missing = run_cli(
                "graphics-approve",
                "--occurrence",
                "stat-01",
                "--version",
                "v1",
                "--by",
                "Human",
                "--statement",
                "",
                project=tmp,
                expect=2,
            )
            self.assertIn("statement", json.dumps(missing, ensure_ascii=False).lower())
            approved = run_cli(
                "graphics-approve",
                "--occurrence",
                "stat-01",
                "--version",
                "v1",
                "--by",
                "Human",
                "--statement",
                "Synthetic fixture: I approve this exact version.",
                project=tmp,
            )
            self.assertTrue(approved["approved"])
            self.assertEqual("chat", approved["approval"]["channel"])
            self.assertFalse(approved["readiness"]["deliverable"])
            source = Path(tmp) / "brolls" / "graphics" / "numeric-stat" / "v1" / "source" / "NumericStat.jsx"
            before = source.read_bytes()
            preview = Path(tmp) / "brolls" / "previews" / "graphics-stat-01-v1.mp4"
            preview.write_bytes(preview.read_bytes() + b"x")
            refused = run_cli(
                "graphics-approve",
                "--occurrence",
                "stat-01",
                "--version",
                "v1",
                "--by",
                "Human",
                "--statement",
                "Synthetic fixture: I approve this exact version again.",
                project=tmp,
                expect=2,
            )
            dumped = json.dumps(refused, ensure_ascii=False)
            self.assertIn("preservado", dumped.lower())
            ledger = Ledger(tmp, recover=False)
            self.assertEqual("approved", ledger.data["graphics"]["versions"]["v1"]["approval"]["status"])
            self.assertEqual(
                "Synthetic fixture: I approve this exact version.",
                ledger.data["graphics"]["versions"]["v1"]["approval"]["statement"],
            )
            self.assertEqual(before, source.read_bytes())

    def test_changed_version_does_not_inherit_approval(self):
        with tempfile.TemporaryDirectory() as tmp:
            _project(tmp)
            _assign(tmp, occurrence="stat-01", scene="numeric-stat")
            _render(tmp, "stat-01")
            _assign(tmp, occurrence="stat-02", scene="units-count", narration="A second occurrence stays independent.")
            _render(tmp, "stat-02")
            run_cli(
                "graphics-approve",
                "--occurrence",
                "stat-01",
                "--version",
                "v1",
                "--by",
                "Human",
                "--statement",
                "Synthetic fixture approval of stat-01 v1 only.",
                project=tmp,
            )
            _assign(tmp, occurrence="stat-01", narration="The count now claims twenty units.")
            later = _render(tmp, "stat-01")
            self.assertEqual("v3", later["version"]["id"])
            self.assertFalse(later["approved"])
            ledger = Ledger(tmp, recover=False)
            self.assertIsNone(ledger.data["graphics"]["versions"]["v3"]["approval"])
            self.assertEqual("approved", ledger.data["graphics"]["versions"]["v1"]["approval"]["status"])
            self.assertIsNone(ledger.data["graphics"]["versions"]["v2"]["approval"])
            status = run_cli("status", project=tmp)
            by_occ = {row["occurrence_id"]: row for row in status["graphics"]["items"]}
            self.assertFalse(by_occ["stat-02"]["approved"])
            self.assertIsNone(ledger.data["graphics"]["versions"]["v2"]["approval"])


@skip_unless_ffmpeg
class GraphicsRequestSelectTests(unittest.TestCase):
    def test_change_request_import_records_context_without_launch(self):
        with tempfile.TemporaryDirectory() as tmp:
            _project(tmp)
            _assign(tmp)
            _render(tmp)
            before = sorted(
                path.relative_to(Path(tmp) / "brolls").as_posix()
                for path in (Path(tmp) / "brolls" / "graphics").rglob("*")
                if path.is_file() and "node_modules" not in path.parts
            )
            payload = _review_payload(tmp)
            payload["items"] = []
            payload["graphics"][0]["state"] = "changes"
            payload["graphics"][0]["comment"] = "Make the numeral larger."
            payload["graphics"][0]["scope"] = "scene"
            path = _write_review(tmp, payload)
            result = run_cli("import-review", "--file", str(path), "--by", "Human", project=tmp)
            self.assertGreaterEqual(result["imported"], 1)
            after = sorted(
                path.relative_to(Path(tmp) / "brolls").as_posix()
                for path in (Path(tmp) / "brolls" / "graphics").rglob("*")
                if path.is_file() and "node_modules" not in path.parts
            )
            self.assertEqual(before, after)
            status = run_cli("status", project=tmp)
            self.assertEqual(1, len(status["graphics"]["requests"]))
            req = status["graphics"]["requests"][0]
            self.assertEqual("saved", req["state"])
            self.assertEqual("scene", req["scope"])
            self.assertEqual("v1", req["reviewed_version"])
            self.assertEqual("Make the numeral larger.", req["text"])
            self.assertIsNone(req["processing"])
            ledger = Ledger(tmp, recover=False)
            self.assertIsNone(ledger.data["graphics"]["versions"]["v1"]["approval"])

    def test_duplicate_processed_import_is_noop_and_payload_conflict_is_reported(self):
        with tempfile.TemporaryDirectory() as tmp:
            _project(tmp)
            _assign(tmp)
            _render(tmp)
            payload = _review_payload(tmp)
            payload["graphics"][0]["state"] = "changes"
            payload["graphics"][0]["comment"] = "Shift the label."
            path = _write_review(tmp, payload, "20261010-120000.json")
            first = run_cli("import-review", "--file", str(path), "--by", "Human", project=tmp)
            self.assertGreaterEqual(first["imported"], 1)
            request_id = run_cli("status", project=tmp)["graphics"]["requests"][0]["id"]
            _assign(tmp, narration="The count now claims twenty units.")
            second_render = _render(tmp)
            self.assertEqual("v2", second_render["version"]["id"])
            complete = run_cli(
                "graphics-request-complete",
                "--request",
                request_id,
                "--version",
                "v2",
                "--outcome",
                "Synthetic specialist produced v2 after chat instruction.",
                project=tmp,
            )
            self.assertFalse(complete["idempotent"])
            again = run_cli("import-review", "--file", str(path), "--by", "Human", project=tmp)
            self.assertEqual(0, again["imported"])
            self.assertTrue(again["unchanged"])
            self.assertEqual("already_processed", again["unchanged"][0]["reason"])
            self.assertEqual("processed", run_cli("status", project=tmp)["graphics"]["requests"][0]["state"])
            conflict = json.loads(path.read_text(encoding="utf-8"))
            conflict["graphics"][0]["comment"] = "A different request text under the same id."
            conflict["graphics"][0]["requestId"] = request_id
            other = _write_review(tmp, conflict, "20261010-120001.json")
            failed = run_cli("import-review", "--file", str(other), "--by", "Human", project=tmp, expect=2)
            self.assertIn("outro texto, alvo ou escopo", json.dumps(failed, ensure_ascii=False))
            self.assertEqual(
                "Synthetic specialist produced v2 after chat instruction.",
                Ledger(tmp, recover=False).data["graphics"]["requests"][0]["processing"]["outcome"],
            )

    def test_stale_target_and_unrelated_completion(self):
        with tempfile.TemporaryDirectory() as tmp:
            _project(tmp)
            _assign(tmp, occurrence="stat-01")
            _render(tmp, "stat-01")
            payload = _review_payload(tmp)
            payload["graphics"][0]["state"] = "changes"
            payload["graphics"][0]["comment"] = "Revise the first occurrence."
            _write_review(tmp, payload)
            run_cli(
                "import-review",
                "--file",
                str(Path(tmp) / "brolls" / "reviews" / "20261010-120000.json"),
                "--by",
                "Human",
                project=tmp,
            )
            request_id = run_cli("status", project=tmp)["graphics"]["requests"][0]["id"]
            stale = json.loads((Path(tmp) / "brolls" / "reviews" / "20261010-120000.json").read_text(encoding="utf-8"))
            stale["graphics"][0]["version"] = "v9"
            stale["graphics"][0]["id"] = "graphics:stat-01:v9"
            stale_path = _write_review(tmp, stale, "20261010-130000.json")
            skipped = run_cli("import-review", "--file", str(stale_path), "--by", "Human", project=tmp, expect=2)
            self.assertIn("ausente ou incompleta", json.dumps(skipped, ensure_ascii=False))
            _assign(tmp, occurrence="stat-02", scene="units-count", narration="Independent second scene.")
            other = _render(tmp, "stat-02")
            refused = run_cli(
                "graphics-request-complete",
                "--request",
                request_id,
                "--version",
                other["version"]["id"],
                "--outcome",
                "Wrong occurrence.",
                project=tmp,
                expect=2,
            )
            self.assertIn("occurrence", json.dumps(refused, ensure_ascii=False).lower())
            _assign(tmp, occurrence="stat-01", narration="The count now claims twenty units.")
            descendant = _render(tmp, "stat-01")
            accepted = run_cli(
                "graphics-request-complete",
                "--request",
                request_id,
                "--version",
                descendant["version"]["id"],
                "--outcome",
                "Synthetic descendant of the reviewed version.",
                project=tmp,
            )
            self.assertEqual(descendant["version"]["id"], accepted["version"])
            self.assertEqual("processed", accepted["request"]["state"])
            idempotent = run_cli(
                "graphics-request-complete",
                "--request",
                request_id,
                "--version",
                descendant["version"]["id"],
                "--outcome",
                "Synthetic descendant of the reviewed version.",
                project=tmp,
            )
            self.assertTrue(idempotent["idempotent"])

    def test_select_older_version_preserves_frozen_files_and_reports_drift(self):
        with tempfile.TemporaryDirectory() as tmp:
            _project(tmp)
            _assign(tmp)
            first = _render(tmp)
            self.assertEqual("v1", first["version"]["id"])
            v1_before = _version_hashes(tmp, "numeric-stat", "v1")
            _assign(tmp, narration="The count now claims twenty units.")
            second = _render(tmp)
            self.assertEqual("v2", second["version"]["id"])
            v2_before = _version_hashes(tmp, "numeric-stat", "v2")
            selected = run_cli(
                "graphics-select",
                "--occurrence",
                "stat-01",
                "--version",
                "v1",
                project=tmp,
            )
            self.assertEqual("v1", selected["current_version"])
            self.assertTrue(selected["assignment_drift"])
            self.assertEqual(v1_before, _version_hashes(tmp, "numeric-stat", "v1"))
            self.assertEqual(v2_before, _version_hashes(tmp, "numeric-stat", "v2"))
            ledger = Ledger(tmp, recover=False)
            self.assertEqual("v1", ledger.data["graphics"]["occurrences"]["stat-01"]["current_version"])
            self.assertEqual("v1", ledger.data["graphics"]["versions"]["v2"]["parent"])
            self.assertEqual(
                "The count now claims twenty units.",
                ledger.data["graphics"]["occurrences"]["stat-01"]["narration"],
            )
            self.assertEqual(
                "The count stands at twelve units.",
                ledger.data["graphics"]["versions"]["v1"]["assignment"]["narration"],
            )
            self.assertIsNone(ledger.data["graphics"]["versions"]["v1"]["approval"])
            status = run_cli("status", project=tmp)
            self.assertIn("assignment_drift", status["graphics"]["items"][0]["reasons"])
            self.assertFalse(status["graphics"]["items"][0]["deliverable"])


class GraphicsReviewPayloadTests(unittest.TestCase):
    def test_new_commands_are_not_format_gates(self):
        self.assertNotIn("graphics-approve", FORMAT_GATE_SUBCOMMANDS)
        self.assertNotIn("graphics-select", FORMAT_GATE_SUBCOMMANDS)
        self.assertNotIn("graphics-request-complete", FORMAT_GATE_SUBCOMMANDS)

    def test_candidate_only_legacy_file_without_graphics_key_still_imports(self):
        with tempfile.TemporaryDirectory() as tmp:
            _project(tmp)
            ledger = Ledger(tmp)
            item = candidate("local", "clip", "Synthetic")
            set_segment(item, 0, 1)
            ledger.add(item)
            ledger.save("fixture", item)
            page = Path(render(ledger)).read_text(encoding="utf-8")
            match = re.search(r"window.GETBROLLS_REVIEW=(.*?);</script>", page)
            if match is None:
                raise AssertionError("GETBROLLS_REVIEW payload is missing")
            payload = json.loads(match.group(1))
            payload.pop("graphics", None)
            payload["items"][0]["state"] = "approved"
            path = _write_review(tmp, payload)
            result = import_review(Ledger(tmp), path, "Human")
            self.assertEqual(1, result["imported"])
            self.assertEqual("approved", Ledger(tmp, recover=False).get("local:clip")["approval"]["status"])


def _explicit(tmp, occurrence="stat-01", scene="numeric-stat", **flags):
    flags.setdefault("timing", "explicit")
    flags.setdefault("start", "0")
    flags.setdefault("end", "0.5")
    _assign(tmp, occurrence=occurrence, scene=scene, **flags)


def _approve(tmp, occurrence="stat-01", version="v1", statement="Synthetic fixture approval only."):
    return run_cli(
        "graphics-approve",
        "--occurrence",
        occurrence,
        "--version",
        version,
        "--by",
        "Synthetic reviewer",
        "--statement",
        statement,
        project=tmp,
    )


@skip_unless_ffmpeg
class GraphicsReviewRegressionTests(unittest.TestCase):
    def test_fresh_changes_after_approval_block_delivery_and_keep_other_occurrence(self):
        with tempfile.TemporaryDirectory() as tmp:
            _project(tmp)
            _explicit(tmp, occurrence="stat-01")
            _render(tmp, "stat-01")
            _explicit(
                tmp,
                occurrence="stat-02",
                scene="units-count",
                narration="Independent second scene stays approved.",
            )
            _render(tmp, "stat-02")
            first = _approve(tmp, "stat-01", "v1", "Synthetic fixture approval of stat-01.")
            second = _approve(tmp, "stat-02", "v2", "Synthetic fixture approval of stat-02.")
            self.assertTrue(first["readiness"]["deliverable"])
            self.assertTrue(second["readiness"]["deliverable"])
            payload = _review_payload(tmp)
            row = next(item for item in payload["graphics"] if item["occurrence_id"] == "stat-01")
            payload["graphics"] = [row]
            row["state"] = "changes"
            row["comment"] = "Synthetic fixture: correct this version before delivery."
            imported = run_cli(
                "import-review",
                "--file",
                str(_write_review(tmp, payload, "changes-after-approval.json")),
                "--by",
                "Synthetic reviewer",
                project=tmp,
            )
            self.assertGreaterEqual(imported["imported"], 1)
            status = run_cli("status", project=tmp)
            by_occ = {item["occurrence_id"]: item for item in status["graphics"]["items"]}
            self.assertFalse(by_occ["stat-01"]["deliverable"])
            self.assertFalse(by_occ["stat-01"]["approved"])
            self.assertIn("changes_requested", by_occ["stat-01"]["reasons"])
            self.assertTrue(by_occ["stat-02"]["approved"])
            self.assertTrue(by_occ["stat-02"]["deliverable"])
            req = status["graphics"]["requests"][0]
            self.assertEqual("saved", req["state"])
            ledger = Ledger(tmp, recover=False)
            version = ledger.data["graphics"]["versions"]["v1"]
            self.assertIsNone(version["approval"])
            self.assertEqual("changes", version["review"]["state"])
            self.assertTrue(
                any(
                    entry.get("statement") == "Synthetic fixture approval of stat-01."
                    for entry in version["review_history"]
                )
            )
            self.assertEqual("approved", ledger.data["graphics"]["versions"]["v2"]["approval"]["status"])
            reapproved = _approve(tmp, "stat-01", "v1", "Synthetic fixture reapproval after changes.")
            self.assertTrue(reapproved["readiness"]["deliverable"])
            after = run_cli("status", project=tmp)
            self.assertEqual("saved", after["graphics"]["requests"][0]["state"])
            self.assertIsNone(after["graphics"]["requests"][0]["processing"])

    def test_job_and_frozen_preview_mutations_refuse_approval(self):
        with tempfile.TemporaryDirectory() as tmp:
            _project(tmp)
            _explicit(tmp)
            _render(tmp)
            original = _approve(tmp, statement="Synthetic job mutation probe.")
            self.assertTrue(original["approved"])
            frozen = Path(tmp) / "brolls" / "graphics" / "numeric-stat" / "v1"
            job_path = frozen / "job.json"
            job_before = job_path.read_bytes()
            job = json.loads(job_before)
            job["props"]["value"] = "CHANGED-AFTER-RENDER"
            job_path.write_text(json.dumps(job), encoding="utf-8")
            refused_job = run_cli(
                "graphics-approve",
                "--occurrence",
                "stat-01",
                "--version",
                "v1",
                "--by",
                "Synthetic reviewer",
                "--statement",
                "Synthetic later approval of a mutated job.",
                project=tmp,
                expect=2,
            )
            self.assertIn("preservado", json.dumps(refused_job, ensure_ascii=False).lower())
            ledger = Ledger(tmp, recover=False)
            self.assertEqual(
                "Synthetic job mutation probe.", ledger.data["graphics"]["versions"]["v1"]["approval"]["statement"]
            )
            job_path.write_bytes(job_before)
            preview = frozen / "preview.mp4"
            preview_before = preview.read_bytes()
            preview.write_bytes(b"modified frozen preview probe")
            refused_preview = run_cli(
                "graphics-approve",
                "--occurrence",
                "stat-01",
                "--version",
                "v1",
                "--by",
                "Synthetic reviewer",
                "--statement",
                "Synthetic later approval of a mutated preview.",
                project=tmp,
                expect=2,
            )
            self.assertIn("preservado", json.dumps(refused_preview, ensure_ascii=False).lower())
            self.assertEqual(
                "Synthetic job mutation probe.",
                Ledger(tmp, recover=False).data["graphics"]["versions"]["v1"]["approval"]["statement"],
            )
            preview.write_bytes(preview_before)
            preview.unlink()
            refused_missing = run_cli(
                "graphics-approve",
                "--occurrence",
                "stat-01",
                "--version",
                "v1",
                "--by",
                "Synthetic reviewer",
                "--statement",
                "Synthetic later approval of a missing preview.",
                project=tmp,
                expect=2,
            )
            self.assertIn("preservado", json.dumps(refused_missing, ensure_ascii=False).lower())
            preview.write_bytes(preview_before)
            self.assertEqual(
                "Synthetic job mutation probe.",
                Ledger(tmp, recover=False).data["graphics"]["versions"]["v1"]["approval"]["statement"],
            )

    def test_retained_v1_request_is_stale_after_v2_and_processed_reimport_is_noop(self):
        with tempfile.TemporaryDirectory() as tmp:
            _project(tmp)
            _explicit(tmp)
            _render(tmp)
            payload = _review_payload(tmp)
            payload["graphics"][0]["state"] = "changes"
            payload["graphics"][0]["comment"] = "Revise the first version."
            first_path = _write_review(tmp, payload, "20261010-120000.json")
            first = run_cli("import-review", "--file", str(first_path), "--by", "Human", project=tmp)
            self.assertGreaterEqual(first["imported"], 1)
            request_id = run_cli("status", project=tmp)["graphics"]["requests"][0]["id"]
            older = copy.deepcopy(payload)
            older["graphics"][0]["comment"] = "Synthetic request against retained v1."
            older["graphics"][0]["requestId"] = "older-target-regression"
            stale_epoch = run_cli(
                "import-review",
                "--file",
                str(_write_review(tmp, older, "stale-epoch.json")),
                "--by",
                "Synthetic reviewer",
                project=tmp,
                expect=2,
            )
            self.assertIn("estado anterior", json.dumps(stale_epoch, ensure_ascii=False).lower())
            self.assertEqual(1, len(run_cli("status", project=tmp)["graphics"]["requests"]))
            older = _review_payload(tmp)
            older["graphics"][0]["state"] = "changes"
            older["graphics"][0]["comment"] = "Synthetic request against retained v1."
            older["graphics"][0]["requestId"] = "older-target-regression"
            _explicit(tmp, narration="A new synthetic narration context.")
            later = _render(tmp)
            self.assertEqual("v2", later["version"]["id"])
            old_result = run_cli(
                "import-review",
                "--file",
                str(_write_review(tmp, older, "independent-older.json")),
                "--by",
                "Synthetic reviewer",
                project=tmp,
            )
            status = run_cli("status", project=tmp)
            self.assertEqual("v2", status["graphics"]["items"][0]["current_version"])
            req = next(row for row in status["graphics"]["requests"] if row["id"] == "older-target-regression")
            self.assertEqual("stale", req["state"])
            self.assertEqual("v1", req["reviewed_version"])
            self.assertEqual("Synthetic request against retained v1.", req["text"])
            self.assertEqual("current_version_mismatch", req["reason"])
            self.assertTrue(any(entry["reason"] == "stale_target" for entry in old_result["skipped"]))
            complete = run_cli(
                "graphics-request-complete",
                "--request",
                request_id,
                "--version",
                "v2",
                "--outcome",
                "Synthetic specialist produced v2 after chat instruction.",
                project=tmp,
            )
            self.assertEqual("processed", complete["request"]["state"])
            again = run_cli("import-review", "--file", str(first_path), "--by", "Human", project=tmp)
            self.assertEqual(0, again["imported"])
            self.assertEqual("already_processed", again["unchanged"][0]["reason"])
            refused = run_cli(
                "graphics-request-complete",
                "--request",
                "older-target-regression",
                "--version",
                "v1",
                "--outcome",
                "Same version is not a descendant.",
                project=tmp,
                expect=2,
            )
            self.assertIn("descendente", json.dumps(refused, ensure_ascii=False).lower())
            self.assertEqual("stale", run_cli("status", project=tmp)["graphics"]["requests"][1]["state"])

    def test_storyboard_approval_history_retains_unique_statement(self):
        with tempfile.TemporaryDirectory() as tmp:
            _project(tmp)
            _explicit(tmp)
            _render(tmp)
            payload = _review_payload(tmp)
            payload["graphics"][0]["state"] = "approved"
            payload["graphics"][0]["comment"] = "Unique synthetic Storyboard approval phrase."
            run_cli(
                "import-review",
                "--file",
                str(_write_review(tmp, payload, "independent-storyboard-approval.json")),
                "--by",
                "Synthetic board reviewer",
                project=tmp,
            )
            _approve(tmp, statement="Synthetic later explicit decision.")
            ledger = Ledger(tmp, recover=False)
            version = ledger.data["graphics"]["versions"]["v1"]
            history = version["review_history"]
            board = next(entry for entry in history if entry.get("channel") == "storyboard")
            self.assertEqual("Unique synthetic Storyboard approval phrase.", board["statement"])
            self.assertEqual(ledger.data["project_id"], board["project_id"])
            self.assertEqual("numeric-stat", board["scene_id"])
            self.assertEqual("stat-01", board["occurrence_id"])
            self.assertEqual("v1", board["version_id"])
            self.assertEqual("storyboard", board["channel"])
            self.assertTrue(any(entry.get("statement") == "Synthetic later explicit decision." for entry in history))
            self.assertEqual("Synthetic later explicit decision.", version["approval"]["statement"])

    def test_project_mismatch_and_malformed_processed_preserve_state(self):
        with tempfile.TemporaryDirectory() as tmp:
            _project(tmp)
            _explicit(tmp)
            _render(tmp)
            _approve(tmp, statement="Synthetic fixture approval bound to this project.")
            manifest = Path(tmp) / "brolls" / "manifest.json"
            data = json.loads(manifest.read_text(encoding="utf-8"))
            data["project_id"] = "changed-project-identity-regression"
            manifest.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            before = manifest.read_bytes()
            refused = run_cli("status", project=tmp, expect=2)
            dumped = json.dumps(refused, ensure_ascii=False)
            self.assertIn("Preserve", dumped)
            self.assertIn(PRESERVE, dumped)
            self.assertEqual(before, manifest.read_bytes())
        with tempfile.TemporaryDirectory() as tmp:
            _project(tmp)
            _explicit(tmp)
            _render(tmp)
            payload = _review_payload(tmp)
            payload["graphics"][0]["state"] = "changes"
            payload["graphics"][0]["comment"] = "Synthetic saved request before malformed processing."
            run_cli(
                "import-review",
                "--file",
                str(_write_review(tmp, payload, "saved-request.json")),
                "--by",
                "Human",
                project=tmp,
            )
            manifest = Path(tmp) / "brolls" / "manifest.json"
            data = json.loads(manifest.read_text(encoding="utf-8"))
            data["graphics"]["requests"][0]["state"] = "processed"
            data["graphics"]["requests"][0]["processing"] = None
            manifest.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            before = manifest.read_bytes()
            refused = run_cli("status", project=tmp, expect=2)
            dumped = json.dumps(refused, ensure_ascii=False)
            self.assertIn("Preserve", dumped)
            self.assertEqual(before, manifest.read_bytes())

    def test_oversized_graphics_row_skips_valid_candidate(self):
        with tempfile.TemporaryDirectory() as tmp:
            _project(tmp)
            ledger = Ledger(tmp)
            item = candidate("local", "clip", "Synthetic")
            set_segment(item, 0, 1)
            item["approval"] = {"status": "pending", "by": None, "at": None, "revision": 1}
            ledger.add(item)
            ledger.save("fixture", item)
            _explicit(tmp, confirm_fps=30)
            _render(tmp)
            payload = _review_payload(tmp)
            payload["items"][0]["state"] = "approved"
            payload["graphics"][0]["state"] = "changes"
            payload["graphics"][0]["comment"] = "x" * (MAX_TEXT + 1)
            result = run_cli(
                "import-review",
                "--file",
                str(_write_review(tmp, payload, "oversized-graphics.json")),
                "--by",
                "Human",
                project=tmp,
            )
            self.assertEqual(1, result["imported"])
            self.assertEqual(0, result["graphics_imported"])
            self.assertEqual("invalid_item", result["skipped"][0]["reason"])
            fresh = Ledger(tmp, recover=False)
            self.assertEqual("approved", fresh.get("local:clip")["approval"]["status"])
            self.assertIsNone(fresh.data["graphics"]["versions"]["v1"]["approval"])
            self.assertEqual([], fresh.data["graphics"]["requests"])

    def test_precommit_rejection_does_not_leak_proposed_import_state(self):
        with tempfile.TemporaryDirectory() as tmp:
            _project(tmp)
            ledger = Ledger(tmp)
            item = candidate("local", "clip", "Synthetic")
            set_segment(item, 0, 1)
            item["approval"] = {"status": "pending", "by": None, "at": None, "revision": 1}
            ledger.add(item)
            ledger.save("fixture", item)
            _explicit(tmp, confirm_fps=30)
            _render(tmp)
            payload = _review_payload(tmp)
            payload["items"][0]["state"] = "approved"
            payload["graphics"][0]["state"] = "approved"
            payload["graphics"][0]["comment"] = "Synthetic fixture approval for tests only."
            path = _write_review(tmp, payload, "precommit.json")
            live = Ledger(tmp)
            with (
                mock.patch.object(Ledger, "save_many", side_effect=ValueError("precommit fixture")),
                self.assertRaises(ValueError),
            ):
                import_review(live, path, "Human")
            self.assertFalse(live.pending.exists())
            self.assertEqual("pending", live.get("local:clip")["approval"]["status"])
            self.assertIsNone(live.data["graphics"]["versions"]["v1"]["approval"])
            journal = _write_review(tmp, payload, "journal.json")
            with (
                mock.patch.object(Ledger, "_finish_transaction", side_effect=ValueError("journal fixture")),
                self.assertRaises(ValueError),
            ):
                import_review(live, journal, "Human")
            self.assertTrue(live.pending.exists())
            self.assertEqual("approved", live.data["graphics"]["versions"]["v1"]["approval"]["status"])
            recovered = Ledger(tmp, recover=True)
            self.assertEqual("approved", recovered.get("local:clip")["approval"]["status"])
            self.assertEqual("approved", recovered.data["graphics"]["versions"]["v1"]["approval"]["status"])
            self.assertFalse(recovered.pending.exists())


FAILING_WORKER = ROOT / "tests" / "fixtures" / "graphics_worker_fail.py"


@skip_unless_ffmpeg
class GraphicsStoryboardUiTests(unittest.TestCase):
    def test_graphics_only_and_mixed_boards_list_every_complete_version(self):  # noqa: PLR0915 - Exercise frozen versions and pending changes on one evolving project.
        with tempfile.TemporaryDirectory() as tmp:
            _project(tmp)
            _assign(
                tmp,
                chapter_context="Original chapter\ncontext",
                narration="The count stands at twelve units.",
            )
            first = _render(tmp)
            self.assertEqual("v1", first["version"]["id"])
            payload = _review_payload(tmp)
            self.assertEqual([], payload["items"])
            self.assertEqual(REVIEW_TEMPLATE_VERSION, payload["templateVersion"])
            self.assertEqual(["v1"], [row["version"] for row in payload["graphics"]])
            self.assertEqual("The count stands at twelve units.", payload["graphics"][0]["context"]["narration"])
            self.assertEqual("Original chapter\ncontext", payload["graphics"][0]["context"]["chapter_context"])
            self.assertEqual("estimated", payload["graphics"][0]["context"]["timing"]["basis"])
            page = (Path(tmp) / "brolls" / "review.html").read_text(encoding="utf-8")
            self.assertTrue("<select data-graphics-display" in page, "single-version card keeps the uniform selector")
            self.assertIn("<select data-graphics-compare disabled", page)
            self.assertIn('class="graphics-vo-status">Без озвучки', page)
            self.assertNotIn("Does this graphics version work?", page)
            self.assertIn("Needs changes</button>", page)
            self.assertEqual(1, page.count('<details class="graphics-details">'))
            self.assertNotIn("0 shots", page)
            self.assertIn("Save decisions, then ask in chat to process revision requests.", page)
            self.assertNotIn("Not approved.", page)
            self.assertFalse(
                "Nothing here yet" in page,
                "graphics-only board should not show the candidate empty-state",
            )
            _assign(
                tmp,
                chapter_context="Changed chapter context.",
                narration="The count now claims twenty units.",
            )
            second = _render(tmp)
            self.assertEqual("v2", second["version"]["id"])
            mixed_ledger = Ledger(tmp)
            item = candidate("local", "clip", "Synthetic")
            set_segment(item, 0, 1)
            mixed_ledger.add(item)
            mixed_ledger.save("fixture", item)
            _assign(
                tmp,
                chapter_context="Later unrendered chapter context.",
                narration="The count later claims thirty units.",
            )
            payload = _review_payload(tmp)
            self.assertEqual(["local:clip"], [row["id"] for row in payload["items"]])
            self.assertEqual(["v1", "v2"], [row["version"] for row in payload["graphics"]])
            by_version = {row["version"]: row for row in payload["graphics"]}
            self.assertEqual(
                ("The count stands at twelve units.", "Original chapter\ncontext"),
                (by_version["v1"]["context"]["narration"], by_version["v1"]["context"]["chapter_context"]),
            )
            self.assertEqual(
                ("The count now claims twenty units.", "Changed chapter context."),
                (by_version["v2"]["context"]["narration"], by_version["v2"]["context"]["chapter_context"]),
            )
            self.assertFalse(by_version["v1"]["current"])
            self.assertTrue(by_version["v2"]["current"])
            self.assertEqual("v1", by_version["v2"]["parent"])
            page = (Path(tmp) / "brolls" / "review.html").read_text(encoding="utf-8")
            self.assertTrue("<select data-graphics-display" in page, "retained versions need a version selector")
            self.assertIn('class="graphics-navigation"', page)
            self.assertIn("data-graphics-piece", page)
            posters = re.findall(r'<video[^>]+poster="([^"]+)"', page)
            self.assertEqual(2, len(posters))
            self.assertTrue(all((Path(tmp) / "brolls" / poster).is_file() for poster in posters))
            self.assertEqual(1, page.count('<details class="graphics-details">'))
            self.assertEqual(2, page.count('class="graphics-version-details'))
            self.assertTrue(
                "previews/graphics-stat-01-v1.mp4" in page,
                "frozen v1 preview missing from mixed board",
            )
            self.assertTrue(
                "previews/graphics-stat-01-v2.mp4" in page,
                "frozen v2 preview missing from mixed board",
            )
            self.assertTrue(
                "Current delivery readiness:" in page,
                "readiness copy missing",
            )
            self.assertTrue(
                'class="graphics-pending-changes"' in page,
                "later unrendered assignment should show pending-changes",
            )
            self.assertTrue(
                "The count stands at twelve units." in page,
                "frozen v1 narration missing",
            )
            self.assertTrue(
                "The count now claims twenty units." in page,
                "frozen v2 narration missing",
            )
            self.assertTrue(
                "The count later claims thirty units." in page,
                "current unrendered narration missing",
            )
            self.assertIn("Apply this change to all graphics (shared)", page)
            self.assertIn('data-decision="rejected"', page)
            self.assertNotIn('data-graphics-decision="rejected"', page)
            css = (ROOT / "assets" / "storyboard.css").read_text(encoding="utf-8")
            self.assertIn(".graphics-preview,.graphics-version-tools,.graphics-review-actions", css)
            self.assertIn(".graphics-card.is-wired .graphics-version{display:block!important}", css)

    def test_failed_version_cannot_be_approved_and_complete_versions_stay_listed(self):
        with tempfile.TemporaryDirectory() as tmp:
            _project(tmp)
            _assign(tmp)
            _render(tmp)
            run_cli(
                "graphics-render",
                "--occurrence",
                "stat-01",
                project=tmp,
                expect=2,
                env={"GB_GRAPHICS_WORKER": str(FAILING_WORKER)},
            )
            _assign(tmp, narration="The count now claims twenty units.")
            later = _render(tmp)
            self.assertEqual("v3", later["version"]["id"])
            payload = _review_payload(tmp)
            self.assertEqual(["v1", "v3"], [row["version"] for row in payload["graphics"]])
            page = (Path(tmp) / "brolls" / "review.html").read_text(encoding="utf-8")
            self.assertIn("Render attempt ID v2 failed and cannot be approved.", page)
            self.assertIn('<p class="graphics-version-label">v2</p>', page)
            self.assertNotIn('<p class="graphics-version-label">v3</p>', page)
            self.assertIn("previews/graphics-stat-01-v1.mp4", page)
            self.assertIn("previews/graphics-stat-01-v3.mp4", page)
            self.assertIn("No human approval is recorded for this version.", page)
            self.assertNotIn("Not approved.", page)

    def test_print_css_hides_graphics_controls_and_keeps_decision_copy(self):
        css = (ROOT / "assets" / "storyboard.css").read_text(encoding="utf-8")
        self.assertIn("@media print", css)
        self.assertIn(".graphics-decision-record,.graphics-readiness,.graphics-request-status,.graphics-workflow", css)
        self.assertIn(".graphics-compare-context,.empty-board{display:none!important}", css)


class GraphicsOnlySaveTests(unittest.TestCase):
    @contextmanager
    def _serving(self, root):
        server, port = serve.start(root, port=0)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            yield server, port
        finally:
            server.shutdown()
            thread.join(timeout=5)
            server.server_close()

    def test_post_saves_graphics_only_envelope_without_ledger_or_agent_changes(self):
        with tempfile.TemporaryDirectory() as tmp:
            _project(tmp)
            root = Path(tmp)
            brolls = root / "brolls"
            ledger = Ledger(tmp)
            ledger.save("fixture")
            manifest = brolls / "manifest.json"
            before = manifest.read_bytes()
            (brolls / "review.html").write_text("<html><body>storyboard</body></html>", encoding="utf-8")
            payload = {
                "type": "getbrolls-review",
                "templateVersion": REVIEW_TEMPLATE_VERSION,
                "project": "synthetic-graphics-only",
                "items": [],
                "graphics": [
                    {
                        "id": "graphics:stat-01:v1",
                        "state": "changes",
                        "comment": "Make the numeral larger.",
                        "scope": "scene",
                    }
                ],
            }
            with self._serving(root) as (server, port):
                token = server.save_token
                if not isinstance(token, str) or not token:
                    raise AssertionError("The local server fixture must provide a nonempty save token.")
                request = urllib.request.Request(
                    f"http://127.0.0.1:{port}/__save",
                    data=json.dumps(payload).encode(),
                    headers={"Content-Type": "application/json", serve.TOKEN_HEADER: token},
                    method="POST",
                )
                with urllib.request.urlopen(request, timeout=5) as response:
                    self.assertEqual(200, response.status)
                    answer = json.loads(response.read().decode("utf-8"))
            saved = Path(answer["path"])
            self.assertTrue(saved.is_file())
            self.assertEqual(payload, json.loads(saved.read_text(encoding="utf-8")))
            self.assertEqual(before, manifest.read_bytes())
            self.assertFalse((brolls / "graphics").exists())
            ledger = Ledger(tmp, recover=False)
            self.assertEqual([], ledger.data["items"])
            self.assertNotIn("graphics", ledger.data)
