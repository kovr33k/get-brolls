"""#54 protected graphics delivery: public CLI regressions with synthetic media."""

from __future__ import annotations

import json
import os
import stat
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import _isolation  # noqa: F401
from _cli import run_cli
from _media import skip_unless_ffmpeg
from test_delivery import fetched, with_brief
from test_delivery import project as seed_candidates
from test_graphics_review import _assign, _project, _render, _review_payload, _write_review

from getbrolls import delivery
from getbrolls.ledger import Ledger
from getbrolls.ledger import digest as file_digest
from getbrolls.models import candidate, now, set_segment, signature

STATEMENT = "Synthetic fixture: I approve this exact version."


def _assign_explicit(tmp, occurrence="stat-01", scene="numeric-stat", **flags):
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
        "explicit",
        "--start",
        str(flags.get("start", "0")),
        "--end",
        str(flags.get("end", "1.5")),
    ]
    if flags.get("question"):
        args += ["--question", flags["question"]]
    if flags.get("confirm_fps"):
        args += ["--confirm-fps", str(flags["confirm_fps"])]
    for ref in flags.get("asset_refs") or []:
        args += ["--asset-ref", ref]
    for ref in flags.get("evidence_refs") or []:
        args += ["--evidence-ref", ref]
    for item in flags.get("material_use") or []:
        args += ["--material-use", item if isinstance(item, str) else json.dumps(item)]
    run_cli(*args, project=tmp)


def _approve(tmp, occurrence="stat-01", version="v1"):
    return run_cli(
        "graphics-approve",
        "--occurrence",
        occurrence,
        "--version",
        version,
        "--by",
        "Human",
        "--statement",
        STATEMENT,
        project=tmp,
    )


def _package(tmp, scene="numeric-stat", occurrence="stat-01", version="v1"):
    return Path(tmp) / "entrega" / "graphics" / scene / occurrence / version


def _seed_bound_candidate(tmp, *, rel="clips/bound.mp4", stale=False, reference_only=False):
    path = Path(tmp) / "brolls" / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"synthetic-candidate-bytes")
    digest_value = file_digest(path)
    ledger = Ledger(tmp)
    item = candidate("local", "bound", "Synthetic bound clip", source_url="https://example.org/bound")
    set_segment(item, 0, 1)
    item["approval"] = {
        "status": "approved",
        "by": "Human",
        "at": now(),
        "revision": 1,
        "channel": "chat",
        "statement": "synthetic fixture approval",
    }
    item["rights"]["status"] = "permitted"
    item["rights"]["evidence"] = ["Synthetic fixture license for tests only."]
    item["output"] = {"path": rel, "sha256": digest_value, "verified": True}
    item["state"] = "verified"
    item["acquisition"] = {
        "status": "reference_only" if reference_only else "available",
        "method": "local",
        "evidence": ["synthetic"],
    }
    item["approval"]["signature"] = "0" * 64 if stale else signature(item)
    stored = ledger.add(item)
    ledger.save_many("fixture", [stored])
    return stored, digest_value


def _material_payload(ref, digest_value, *, rendered="permitted", raw="permitted", candidate_id="local:bound"):
    return {
        "ref": ref,
        "rendered_use": rendered,
        "raw_redistribution": raw,
        "evidence": ["Synthetic fixture rights evidence."],
        "conditions": "Finished-video use only; tests do not grant redistribution.",
        "sha256": digest_value,
        "candidate_id": candidate_id,
    }


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


def _remove_dir_link(link):
    link = Path(link)
    if link.is_symlink():
        link.unlink()
        return
    link.rmdir()


def _within_temp(path, root):
    path = Path(path).resolve()
    root = Path(root).resolve()
    return path == root or root in path.parents


def _rerender_check(pkg, extra=None):
    cmd = [sys.executable, str(Path(pkg) / "rerender.py"), "--check"]
    if extra:
        cmd.extend(extra)
    return subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
        cwd=str(pkg),
    )


def _assert_timing_metadata(test, tmp, pkg):
    video = pkg / "numeric-stat-stat-01-v1.mp4"
    test.assertTrue(video.is_file())
    test.assertFalse(video.is_symlink())
    frozen_preview = Path(tmp) / "brolls" / "graphics" / "numeric-stat" / "v1" / "preview.mp4"
    test.assertFalse(os.path.samestat(video.stat(), frozen_preview.stat()))
    timing = json.loads((pkg / "timing.json").read_text(encoding="utf-8"))
    ledger = Ledger(tmp, recover=False)
    version = ledger.data["graphics"]["versions"]["v1"]
    test.assertEqual(ledger.data.get("project_id"), timing["project_id"])
    test.assertEqual("numeric-stat", timing["scene_id"])
    test.assertEqual("stat-01", timing["occurrence_id"])
    test.assertEqual("v1", timing["version"])
    test.assertIsNone(timing["parent"])
    test.assertEqual(version["artifact"]["sha256"], timing["video_sha256"])
    test.assertEqual(0, timing["narration"]["start_s"])
    test.assertEqual(1.5, timing["narration"]["end_s"])
    test.assertEqual("explicit", timing["timing_basis"])
    test.assertFalse(timing["embedded_voice_over"])
    return version


def _assert_rerender_layout(test, pkg):
    rerender = json.loads((pkg / "rerender.json").read_text(encoding="utf-8"))
    test.assertIsInstance(rerender["props"], dict)
    test.assertEqual("rerender-out.mp4", rerender["output"])
    test.assertEqual("public", rerender["publicDir"])
    test.assertEqual("source/index.jsx", rerender["entry"])
    test.assertIn("python rerender.py", rerender["invocation"]["command"])
    test.assertIn("--check", rerender["invocation"]["check"])
    test.assertTrue((pkg / "rerender.py").is_file())
    adapter = (pkg / "rerender.py").read_text(encoding="utf-8")
    test.assertIn("props.json must be a JSON object", adapter)
    test.assertIn("separately-held.json", adapter)
    test.assertIn("--browser-executable", adapter)
    test.assertIn("npm ci --ignore-scripts", adapter)
    test.assertIn("held-ref", adapter)
    return adapter


def _assert_independent_source_edit(test, tmp, pkg):
    frozen_source = Path(tmp) / "brolls" / "graphics" / "numeric-stat" / "v1" / "source" / "index.jsx"
    original = frozen_source.read_bytes()
    delivered_source = pkg / "source" / "index.jsx"
    delivered_source.write_bytes(original + b"\n// independent edit\n")
    test.assertEqual(original, frozen_source.read_bytes())
    test.assertIn(b"independent edit", delivered_source.read_bytes())


@skip_unless_ffmpeg
class GraphicsOnlyDeliveryTests(unittest.TestCase):
    def test_eligible_graphics_only_package_and_timing_metadata(self):
        with tempfile.TemporaryDirectory() as tmp:
            _project(tmp)
            _assign_explicit(tmp)
            rendered = _render(tmp)
            self.assertFalse(rendered["approved"])
            approved = _approve(tmp)
            self.assertTrue(approved["readiness"]["deliverable"])
            manifest = Path(tmp) / "brolls" / "manifest.json"
            before = manifest.read_bytes()
            dry = run_cli("deliver", "--dry-run", project=tmp)
            self.assertEqual(before, manifest.read_bytes())
            self.assertFalse((Path(tmp) / "entrega").exists())
            self.assertEqual("planned", dry["graphics"][0]["method"])
            report = run_cli("deliver", project=tmp)
            self.assertEqual(1, len(report["graphics"]))
            self.assertEqual("copy", report["graphics"][0]["method"])
            pkg = _package(tmp)
            version = _assert_timing_metadata(self, tmp, pkg)
            _assert_rerender_layout(self, pkg)
            origin = (pkg / "ORIGEM.md").read_text(encoding="utf-8")
            approval_day = version["approval"]["at"][:10]
            self.assertIn(f"created: {approval_day}", origin)
            self.assertIn(f"updated: {approval_day}", origin)
            status = run_cli("status", project=tmp)
            self.assertEqual(1, status["graphics"]["delivery"]["delivered"])
            self.assertEqual(0, status["graphics"]["delivery"]["undelivered"])
            again = run_cli("deliver", project=tmp)
            self.assertEqual("copy", again["graphics"][0]["method"])
            self.assertEqual(origin, (pkg / "ORIGEM.md").read_text(encoding="utf-8"))
            _assert_independent_source_edit(self, tmp, pkg)

    def test_dry_run_does_not_mutate_manifest_or_media(self):
        with tempfile.TemporaryDirectory() as tmp:
            _project(tmp)
            _assign_explicit(tmp)
            _render(tmp)
            _approve(tmp)
            manifest = Path(tmp) / "brolls" / "manifest.json"
            before = manifest.read_bytes()
            run_cli("deliver", "--dry-run", project=tmp)
            self.assertEqual(before, manifest.read_bytes())
            self.assertFalse((Path(tmp) / "entrega").exists())
            ledger = Ledger(tmp, recover=False)
            self.assertNotIn("delivery", ledger.data["graphics"]["versions"]["v1"])


@skip_unless_ffmpeg
class MixedCandidateGraphicsTests(unittest.TestCase):
    def test_mixed_candidate_and_graphics_success(self):
        with tempfile.TemporaryDirectory() as tmp:
            _project(tmp)
            seed_candidates(tmp, [fetched("a", "Palco", shot="abertura", clip="clips/a.mp4", sheet="previews/a.jpg")])
            with_brief(tmp)
            _assign_explicit(tmp, confirm_fps=30)
            _render(tmp)
            _approve(tmp)
            report = run_cli("deliver", project=tmp)
            self.assertEqual(1, len(report["items"]))
            self.assertEqual(1, len(report["graphics"]))
            self.assertTrue((Path(tmp) / report["items"][0]["path"]).exists())
            self.assertTrue(_package(tmp).is_dir())
            ledger = Ledger(tmp, recover=False)
            self.assertTrue((ledger.data["items"][0].get("delivery") or {}).get("path"))
            self.assertEqual("v1", ledger.data["graphics"]["versions"]["v1"]["delivery"]["version_id"])

    def test_mixed_success_then_conflict_keeps_unrelated_commit(self):
        with tempfile.TemporaryDirectory() as tmp:
            _project(tmp)
            seed_candidates(
                tmp,
                [
                    fetched("a", "Palco", shot="abertura", clip="clips/a.mp4", sheet="previews/a.jpg"),
                    fetched("b", "Plateia", shot="fechamento", clip="clips/b.mp4", sheet="previews/b.jpg"),
                ],
            )
            with_brief(tmp)
            _assign_explicit(tmp, confirm_fps=30)
            _render(tmp)
            _approve(tmp)
            plan = run_cli("deliver", "--dry-run", project=tmp)
            first = Path(tmp) / plan["items"][0]["path"]
            first.parent.mkdir(parents=True, exist_ok=True)
            first.write_bytes(b"foreign candidate edit")
            refused = run_cli("deliver", project=tmp, expect=2)
            dumped = json.dumps(refused, ensure_ascii=False)
            self.assertIn("parece edição sua", dumped)
            ledger = Ledger(tmp, recover=False)
            self.assertEqual("v1", ledger.data["graphics"]["versions"]["v1"]["delivery"]["version_id"])
            self.assertTrue(_package(tmp).is_dir())
            delivered = [c["id"] for c in ledger.data["items"] if (c.get("delivery") or {}).get("path")]
            self.assertEqual(1, len(delivered))


@skip_unless_ffmpeg
class MaterialBindingTests(unittest.TestCase):
    def test_permitted_raw_is_copied_restricted_is_separately_held(self):
        with tempfile.TemporaryDirectory() as tmp:
            _project(tmp)
            _seed_bound_candidate(tmp, rel="clips/bound.mp4")
            permitted = Path(tmp) / "brolls" / "previews" / "open.txt"
            permitted.parent.mkdir(parents=True, exist_ok=True)
            permitted.write_bytes(b"open-ref")
            ledger = Ledger(tmp, recover=False)
            open_id = "local:open"
            extra = candidate("local", "open", "Open ref", source_url="https://example.org/open")
            set_segment(extra, 0, 1)
            extra["id"] = open_id
            extra["approval"] = {
                "status": "approved",
                "by": "Human",
                "at": now(),
                "revision": 1,
                "channel": "chat",
                "statement": "synthetic",
            }
            extra["rights"]["status"] = "permitted"
            extra["rights"]["evidence"] = ["Synthetic open license."]
            extra["output"] = {
                "path": "previews/open.txt",
                "sha256": file_digest(permitted),
                "verified": True,
            }
            extra["state"] = "verified"
            extra["acquisition"] = {"status": "available", "method": "local", "evidence": ["synthetic"]}
            extra["approval"]["signature"] = signature(extra)
            stored = ledger.add(extra)
            ledger.save_many("fixture", [stored])
            bound = file_digest(Path(tmp) / "brolls" / "clips" / "bound.mp4")
            open_hash = file_digest(permitted)
            _assign_explicit(
                tmp,
                confirm_fps=30,
                asset_refs=["clips/bound.mp4", "previews/open.txt"],
                material_use=[
                    _material_payload("clips/bound.mp4", bound, raw="restricted"),
                    _material_payload("previews/open.txt", open_hash, candidate_id=open_id, raw="permitted"),
                ],
            )
            _render(tmp)
            _approve(tmp)
            run_cli("deliver", project=tmp)
            pkg = _package(tmp)
            self.assertTrue((pkg / "refs" / "previews" / "open.txt").is_file())
            self.assertFalse((pkg / "refs" / "clips" / "bound.mp4").exists())
            held = json.loads((pkg / "separately-held.json").read_text(encoding="utf-8"))
            self.assertTrue(any(item.get("ref") == "clips/bound.mp4" for item in held))
            self.assertTrue(any(item.get("candidate_rights") for item in held if item.get("ref") == "clips/bound.mp4"))
            assignment = json.loads((pkg / "assignment.json").read_text(encoding="utf-8"))
            rights = next(
                item["candidate_rights"] for item in assignment["material_use"] if item["ref"] == "clips/bound.mp4"
            )
            self.assertEqual("permitted", rights["status"])

    def test_stale_candidate_signature_and_reference_only_are_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            _project(tmp)
            _seed_bound_candidate(tmp, stale=True, reference_only=True)
            digest_value = file_digest(Path(tmp) / "brolls" / "clips" / "bound.mp4")
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
                "explicit",
                "--start",
                "0",
                "--end",
                "1.5",
                "--confirm-fps",
                "30",
                "--asset-ref",
                "clips/bound.mp4",
                "--material-use",
                json.dumps(_material_payload("clips/bound.mp4", digest_value)),
                project=tmp,
                expect=2,
            )
            dumped = json.dumps(refused, ensure_ascii=False).lower()
            self.assertIn("rendered use cannot be permitted", dumped)

    def test_wrong_supplied_hash_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            _project(tmp)
            _seed_bound_candidate(tmp)
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
                "explicit",
                "--start",
                "0",
                "--end",
                "1.5",
                "--confirm-fps",
                "30",
                "--asset-ref",
                "clips/bound.mp4",
                "--material-use",
                json.dumps(_material_payload("clips/bound.mp4", "0" * 64)),
                project=tmp,
                expect=2,
            )
            dumped = json.dumps(refused, ensure_ascii=False).lower()
            self.assertIn("sha256", dumped)
            self.assertIn("does not match", dumped)

    def test_frozen_then_stale_candidate_blocks_delivery(self):
        with tempfile.TemporaryDirectory() as tmp:
            _project(tmp)
            stored, digest_value = _seed_bound_candidate(tmp)
            _assign_explicit(
                tmp,
                confirm_fps=30,
                asset_refs=["clips/bound.mp4"],
                material_use=[_material_payload("clips/bound.mp4", digest_value, raw="restricted")],
            )
            _render(tmp)
            _approve(tmp)
            ledger = Ledger(tmp)
            live = ledger.get(stored["id"])
            live["approval"]["signature"] = "0" * 64
            ledger.save_many("tamper", [live])
            report = run_cli("deliver", project=tmp)
            skipped = report.get("graphics_skipped") or []
            self.assertTrue(skipped)
            self.assertIn("unresolved_material_use", skipped[0]["reason"])
            self.assertFalse(_package(tmp).exists())
            fresh = Ledger(tmp, recover=False)
            self.assertEqual("approved", fresh.data["graphics"]["versions"]["v1"]["approval"]["status"])
            self.assertNotIn("delivery", fresh.data["graphics"]["versions"]["v1"])


@skip_unless_ffmpeg
class SkipAndPreservationTests(unittest.TestCase):
    def test_estimated_questions_and_unapproved_are_skipped(self):
        with tempfile.TemporaryDirectory() as tmp:
            _project(tmp)
            _assign(tmp, timing="estimated")
            _render(tmp)
            _approve(tmp)
            report = run_cli("deliver", project=tmp)
            reasons = [item["reason"] for item in report.get("graphics_skipped") or []]
            self.assertIn("estimated_timing", reasons)
            self.assertFalse(_package(tmp).exists())

        with tempfile.TemporaryDirectory() as tmp:
            _project(tmp)
            _assign_explicit(tmp, question="What is the sourced figure?")
            _render(tmp)
            _approve(tmp)
            report = run_cli("deliver", project=tmp)
            reasons = [item["reason"] for item in report.get("graphics_skipped") or []]
            self.assertIn("unresolved_questions", reasons)

        with tempfile.TemporaryDirectory() as tmp:
            _project(tmp)
            _assign_explicit(tmp)
            _render(tmp)
            report = run_cli("deliver", project=tmp)
            reasons = [item["reason"] for item in report.get("graphics_skipped") or []]
            self.assertTrue(reasons)
            self.assertIn(reasons[0], ("missing_approval", "not_deliverable"))

    def test_old_version_files_and_history_are_kept(self):
        with tempfile.TemporaryDirectory() as tmp:
            _project(tmp)
            _assign_explicit(tmp)
            _render(tmp)
            _approve(tmp)
            run_cli("deliver", project=tmp)
            v1 = _package(tmp, version="v1")
            v1_video = v1 / "numeric-stat-stat-01-v1.mp4"
            self.assertTrue(v1_video.is_file())
            payload = _review_payload(tmp)
            payload["graphics"][0]["state"] = "changes"
            payload["graphics"][0]["comment"] = "Synthetic fixture request to keep history."
            path = _write_review(tmp, payload)
            run_cli("import-review", "--file", str(path), "--by", "Human", project=tmp)
            _assign_explicit(tmp, narration="The count stands at thirteen units after the revision.")
            _render(tmp)
            _approve(tmp, version="v2")
            run_cli("deliver", project=tmp)
            self.assertTrue(v1_video.is_file())
            self.assertTrue((_package(tmp, version="v2") / "numeric-stat-stat-01-v2.mp4").is_file())
            frozen_v1 = Path(tmp) / "brolls" / "graphics" / "numeric-stat" / "v1" / "source" / "index.jsx"
            self.assertTrue(frozen_v1.is_file())
            ledger = Ledger(tmp, recover=False)
            self.assertTrue(ledger.data["graphics"]["versions"]["v1"].get("review_history"))
            self.assertTrue(ledger.data["graphics"].get("requests"))
            self.assertEqual("approved", ledger.data["graphics"]["versions"]["v2"]["approval"]["status"])

    def test_missing_package_is_not_counted_delivered(self):
        with tempfile.TemporaryDirectory() as tmp:
            _project(tmp)
            _assign_explicit(tmp)
            _render(tmp)
            _approve(tmp)
            run_cli("deliver", project=tmp)
            pkg = _package(tmp)
            for child in pkg.rglob("*"):
                if child.is_file():
                    child.chmod(child.stat().st_mode | stat.S_IWRITE)
            for child in sorted(pkg.rglob("*"), reverse=True):
                if child.is_file():
                    child.unlink()
                elif child.is_dir():
                    child.rmdir()
            pkg.rmdir()
            status = run_cli("status", project=tmp)
            self.assertEqual(0, status["graphics"]["delivery"]["delivered"])
            self.assertEqual(1, status["graphics"]["delivery"]["undelivered"])
            run_cli("deliver", project=tmp)
            self.assertTrue((_package(tmp) / "numeric-stat-stat-01-v1.mp4").is_file())


@skip_unless_ffmpeg
class DestinationGuardTests(unittest.TestCase):
    def test_foreign_file_preflight_does_not_write_partial_package(self):
        with tempfile.TemporaryDirectory() as tmp:
            _project(tmp)
            _assign_explicit(tmp)
            _render(tmp)
            _approve(tmp)
            pkg = _package(tmp)
            pkg.mkdir(parents=True, exist_ok=True)
            foreign = pkg / "PACKAGE.md"
            foreign.write_text("pessoa editou", encoding="utf-8")
            refused = run_cli("deliver", project=tmp, expect=2)
            self.assertIn("parece edição sua", json.dumps(refused, ensure_ascii=False))
            self.assertEqual("pessoa editou", foreign.read_text(encoding="utf-8"))
            self.assertFalse((pkg / "numeric-stat-stat-01-v1.mp4").exists())
            self.assertFalse((pkg / "timing.json").exists())
            ledger = Ledger(tmp, recover=False)
            self.assertNotIn("delivery", ledger.data["graphics"]["versions"]["v1"])

    def test_edited_source_is_preserved_on_repeat(self):
        with tempfile.TemporaryDirectory() as tmp:
            _project(tmp)
            _assign_explicit(tmp)
            _render(tmp)
            _approve(tmp)
            run_cli("deliver", project=tmp)
            pkg = _package(tmp)
            delivered = pkg / "source" / "index.jsx"
            frozen = Path(tmp) / "brolls" / "graphics" / "numeric-stat" / "v1" / "source" / "index.jsx"
            original = frozen.read_bytes()
            delivered.write_bytes(original + b"\n// hand edit\n")
            note = pkg / "minhas-notas.txt"
            note.write_text("keep me", encoding="utf-8")
            refused = run_cli("deliver", project=tmp, expect=2)
            self.assertIn("parece edição sua", json.dumps(refused, ensure_ascii=False))
            self.assertTrue(note.is_file())
            self.assertEqual(original, frozen.read_bytes())
            self.assertIn(b"hand edit", delivered.read_bytes())

    def _refuse_file_symlink_dest(self):
        with tempfile.TemporaryDirectory() as tmp:
            _project(tmp)
            _assign_explicit(tmp)
            _render(tmp)
            _approve(tmp)
            pkg = _package(tmp)
            pkg.mkdir(parents=True, exist_ok=True)
            outside = Path(tmp) / "outside-video.mp4"
            outside.write_bytes(b"outside")
            self.assertTrue(_within_temp(outside, tmp))
            link = pkg / "numeric-stat-stat-01-v1.mp4"
            try:
                link.symlink_to(outside)
                linked = link.exists() or link.is_symlink()
            except OSError:
                return False
            if not linked:
                return False
            refused = run_cli("deliver", project=tmp, expect=2)
            dumped = json.dumps(refused, ensure_ascii=False).lower()
            self.assertTrue("symlink" in dumped or "junction" in dumped)
            self.assertEqual(b"outside", outside.read_bytes())
            self.assertFalse((pkg / "timing.json").exists())
            return True

    def _refuse_dir_junction_dest(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _project(tmp)
            _assign_explicit(tmp)
            _render(tmp)
            _approve(tmp)
            escape = root / "escape-target"
            escape.mkdir()
            sentinel = escape / "sentinel.txt"
            sentinel.write_text("keep", encoding="utf-8")
            self.assertTrue(_within_temp(escape, root))
            junction_dest = root / "entrega" / "graphics" / "numeric-stat"
            if junction_dest.exists() or junction_dest.is_symlink():
                return False
            junction_dest.parent.mkdir(parents=True, exist_ok=True)
            if not _make_dir_link(junction_dest, escape):
                return False
            self.assertTrue(_within_temp(junction_dest.resolve(), root))
            refused = run_cli("deliver", project=tmp, expect=2)
            dumped = json.dumps(refused, ensure_ascii=False).lower()
            self.assertTrue("symlink" in dumped or "junction" in dumped)
            self.assertEqual("keep", sentinel.read_text(encoding="utf-8"))
            _remove_dir_link(junction_dest)
            self.assertFalse(junction_dest.exists())
            self.assertEqual("keep", sentinel.read_text(encoding="utf-8"))
            return True

    def test_symlink_and_junction_destinations_are_refused(self):
        linked = self._refuse_file_symlink_dest()
        junctioned = self._refuse_dir_junction_dest()
        if not linked and not junctioned:
            self.skipTest("could not create a destination symlink or junction")


def _write_adapter_package(pkg, *, kind, held=None, worker_name="render.mjs"):
    pkg = Path(pkg)
    pkg.mkdir(parents=True, exist_ok=True)
    (pkg / "source").mkdir()
    (pkg / "public" / "fonts").mkdir(parents=True)
    (pkg / "inputs").mkdir()
    (pkg / "source" / "index.jsx").write_text("export const Comp = () => null;\n", encoding="utf-8")
    (pkg / "inputs" / worker_name).write_text("// copied worker placeholder\n", encoding="utf-8")
    (pkg / "props.json").write_text("{}", encoding="utf-8")
    (pkg / "separately-held.json").write_text(json.dumps(held or []), encoding="utf-8")
    (pkg / "rerender.py").write_text(delivery.RERENDER_ADAPTER, encoding="utf-8")
    config = {
        "entry": "source/index.jsx",
        "publicDir": "public",
        "output": "rerender-out.mp4",
        "composition": "NumericStat",
        "runtime": {"kind": kind, "worker": "inputs/" + worker_name},
    }
    (pkg / "rerender.json").write_text(json.dumps(config), encoding="utf-8")
    return pkg


_PINNED_RUNTIME = {
    "remotion": "4.0.534",
    "@remotion/renderer": "4.0.534",
    "@remotion/bundler": "4.0.534",
    "react": "19.3.0",
    "react-dom": "19.3.0",
    "@fontsource/ibm-plex-sans": "5.3.0",
}


def _write_pinned_root_and_modules(pkg, *, installed):
    pkg = Path(pkg)
    (pkg / "package.json").write_text(
        json.dumps({"name": "delivered-graphics", "private": True, "dependencies": dict(_PINNED_RUNTIME)}),
        encoding="utf-8",
    )
    (pkg / "package-lock.json").write_text(
        json.dumps({"lockfileVersion": 3, "name": "delivered-graphics", "packages": {}}),
        encoding="utf-8",
    )
    for name, version in installed.items():
        dest = pkg / "node_modules" / Path(*name.split("/"))
        dest.mkdir(parents=True, exist_ok=True)
        (dest / "package.json").write_text(json.dumps({"name": name, "version": version}), encoding="utf-8")
    browser = pkg / "fictional-browser.bin"
    browser.write_bytes(b"not-a-prepared-browser")
    marker = "import fs from 'node:fs'; fs.writeFileSync('WORKER_RAN', 'yes');\n"
    (pkg / "inputs" / "render.mjs").write_text(marker, encoding="utf-8")
    return browser


@skip_unless_ffmpeg
class IntactPackageRepeatTests(unittest.TestCase):
    def test_repeat_keeps_intact_package_when_generator_changes(self):
        with tempfile.TemporaryDirectory() as tmp:
            _project(tmp)
            _assign_explicit(tmp)
            _render(tmp)
            _approve(tmp)
            run_cli("deliver", project=tmp)
            pkg = _package(tmp)
            adapter = pkg / "rerender.py"
            before = adapter.read_bytes()
            mtime = adapter.stat().st_mtime_ns
            digest_before = file_digest(adapter)
            origin = (pkg / "ORIGEM.md").read_bytes()
            with patch.object(delivery, "RERENDER_ADAPTER", before.decode("utf-8") + "\n# generator-update\n"):
                again = run_cli("deliver", project=tmp)
            self.assertEqual("copy", again["graphics"][0]["method"])
            self.assertEqual(before, adapter.read_bytes())
            self.assertEqual(digest_before, file_digest(adapter))
            self.assertEqual(mtime, adapter.stat().st_mtime_ns)
            self.assertEqual(origin, (pkg / "ORIGEM.md").read_bytes())
            self.assertNotIn(b"generator-update", adapter.read_bytes())
            status = run_cli("status", project=tmp)
            self.assertEqual(1, status["graphics"]["delivery"]["delivered"])
            self.assertEqual(0, status["graphics"]["delivery"]["undelivered"])

    def test_rerender_check_accepts_test_worker_without_browser(self):
        with tempfile.TemporaryDirectory() as tmp:
            _project(tmp)
            _assign_explicit(tmp)
            _render(tmp)
            _approve(tmp)
            run_cli("deliver", project=tmp)
            pkg = _package(tmp)
            done = _rerender_check(pkg)
            payload = json.loads(done.stdout)
            self.assertEqual(0, done.returncode)
            self.assertTrue(payload["ok"])
            self.assertFalse(payload["self_contained"])
            self.assertEqual("test-worker", payload["kind"])
            self.assertIsNone(payload["browserExecutable"])


class RerenderAdapterCheckTests(unittest.TestCase):
    def test_check_reports_missing_remotion_runtime_and_browser(self):
        with tempfile.TemporaryDirectory() as tmp:
            pkg = _write_adapter_package(Path(tmp) / "pkg", kind="remotion")
            done = _rerender_check(pkg)
            payload = json.loads(done.stdout)
            dumped = json.dumps(payload)
            self.assertEqual(2, done.returncode)
            self.assertFalse(payload["ok"])
            self.assertFalse(payload["self_contained"])
            self.assertIn("npm ci --ignore-scripts", dumped)
            self.assertIn("browser-executable", dumped)
            self.assertIsNone(payload["browserExecutable"])

    def test_check_requires_held_ref_bytes_not_acknowledgement(self):
        with tempfile.TemporaryDirectory() as tmp:
            original = Path(tmp) / "held.mp4"
            original.write_bytes(b"restricted-bytes")
            digest_value = file_digest(original)
            held = [
                {
                    "ref": "clips/bound.mp4",
                    "sha256": digest_value,
                    "raw_redistribution": "restricted",
                }
            ]
            pkg = _write_adapter_package(Path(tmp) / "pkg", kind="test-worker", worker_name="worker.py")
            (pkg / "separately-held.json").write_text(json.dumps(held), encoding="utf-8")
            acknowledged = subprocess.run(
                [sys.executable, str(pkg / "rerender.py"), "--check", "--acknowledge-separately-held"],
                capture_output=True,
                text=True,
                encoding="utf-8",
                check=False,
                cwd=str(pkg),
            )
            ack = json.loads(acknowledged.stdout)
            self.assertEqual(2, acknowledged.returncode)
            self.assertFalse(ack["ok"])
            self.assertIn("held-ref", json.dumps(ack))
            mapped = _rerender_check(pkg, extra=["--held-ref", f"clips/bound.mp4={original}"])
            payload = json.loads(mapped.stdout)
            self.assertEqual(0, mapped.returncode)
            self.assertTrue(payload["ok"])
            self.assertTrue(payload["held"][0]["supplied"])

    def test_check_rejects_wrong_held_hash_and_missing_browser_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            original = Path(tmp) / "held.mp4"
            original.write_bytes(b"restricted-bytes")
            held = [{"ref": "clips/bound.mp4", "sha256": "0" * 64, "raw_redistribution": "restricted"}]
            pkg = _write_adapter_package(Path(tmp) / "pkg", kind="test-worker", worker_name="worker.py")
            (pkg / "separately-held.json").write_text(json.dumps(held), encoding="utf-8")
            wrong = _rerender_check(pkg, extra=["--held-ref", f"clips/bound.mp4={original}"])
            payload = json.loads(wrong.stdout)
            self.assertEqual(2, wrong.returncode)
            self.assertFalse(payload["ok"])
            self.assertIn("sha256", json.dumps(payload))
            missing_browser = subprocess.run(
                [
                    sys.executable,
                    str(pkg / "rerender.py"),
                    "--check",
                    "--browser-executable",
                    str(Path(tmp) / "no-chrome"),
                ],
                capture_output=True,
                text=True,
                encoding="utf-8",
                check=False,
                cwd=str(pkg),
            )
            self.assertNotEqual(0, missing_browser.returncode)
            self.assertIn("browser executable", (missing_browser.stderr or missing_browser.stdout).lower())

    def test_check_rejects_mismatched_installed_package_metadata(self):
        with tempfile.TemporaryDirectory() as tmp:
            pkg = _write_adapter_package(Path(tmp) / "pkg", kind="remotion")
            browser = _write_pinned_root_and_modules(pkg, installed={"@remotion/bundler": "0.0.0"})
            done = _rerender_check(pkg, extra=["--browser-executable", str(browser)])
            payload = json.loads(done.stdout)
            dumped = json.dumps(payload)
            self.assertEqual(2, done.returncode)
            self.assertFalse(payload["ok"])
            self.assertFalse(payload["self_contained"])
            self.assertIn("@remotion/bundler expected 4.0.534, actual 0.0.0", dumped)
            self.assertIn("@remotion/renderer expected 4.0.534, actual missing", dumped)
            self.assertIn("remotion expected 4.0.534, actual missing", dumped)
            self.assertIn("react expected 19.3.0, actual missing", dumped)
            self.assertIn("react-dom expected 19.3.0, actual missing", dumped)
            self.assertIn("@fontsource/ibm-plex-sans expected 5.3.0, actual missing", dumped)
            self.assertIn("Directory presence is not enough", dumped)
            self.assertEqual("0.0.0", payload["runtime"]["installed"]["@remotion/bundler"])
            self.assertEqual("missing", payload["runtime"]["installed"]["react"])
            self.assertFalse((pkg / "WORKER_RAN").exists())

    def test_check_accepts_matching_pin_metadata_without_render(self):
        with tempfile.TemporaryDirectory() as tmp:
            pkg = _write_adapter_package(Path(tmp) / "pkg", kind="remotion")
            browser = _write_pinned_root_and_modules(pkg, installed=dict(_PINNED_RUNTIME))
            done = _rerender_check(pkg, extra=["--browser-executable", str(browser)])
            payload = json.loads(done.stdout)
            self.assertEqual(0, done.returncode)
            self.assertTrue(payload["ok"])
            self.assertFalse(payload["self_contained"])
            self.assertEqual([], payload["errors"])
            self.assertEqual(str(browser.resolve()), payload["browserExecutable"])
            self.assertEqual(_PINNED_RUNTIME, payload["runtime"]["pins"])
            self.assertEqual(_PINNED_RUNTIME, payload["runtime"]["installed"])
            self.assertFalse((pkg / "WORKER_RAN").exists())


if __name__ == "__main__":
    unittest.main()
