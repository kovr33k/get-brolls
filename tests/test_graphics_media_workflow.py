"""#56 public background workflow: video/photo, freeze, rights, delivery, Storyboard."""

from __future__ import annotations

import json
import subprocess
import tempfile
import unittest
from pathlib import Path

import _isolation  # noqa: F401
from _cli import run_cli
from _media import skip_unless_ffmpeg, synth_image, synth_video
from _paths import ROOT
from test_graphics_review import _assign as _assign_base
from test_graphics_review import _project, _review_payload, _write_review

from getbrolls.graphics import (
    BACKGROUND_TEMPLATE,
    BACKGROUND_TEMPLATE_FILES,
    TEMPLATE_DIR,
    _source_template_names,
)
from getbrolls.ledger import Ledger
from getbrolls.ledger import digest as file_digest
from getbrolls.models import candidate, now, set_segment, signature
from getbrolls.runtime import READ_ONLY_COMMANDS

WORKER = ROOT / "tests" / "fixtures" / "graphics_media_worker.py"
ENV = {"GB_GRAPHICS_WORKER": str(WORKER)}
STATEMENT = "Synthetic fixture: I approve this exact version."


def _assign(tmp, occurrence="stat-01", scene="numeric-stat", **flags):
    flags.setdefault("confirm_fps", 30)
    flags.setdefault("duration", "2")
    return _assign_base(tmp, occurrence=occurrence, scene=scene, **flags)


def _write(path, text):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def _seed_media_candidate(  # noqa: PLR0913 - Fixture independently controls identity, bytes, media kind, rights and review state.
    tmp,
    *,
    ident,
    title,
    rel,
    kind="video",
    rights="permitted",
    approve=True,
    duration_s=6,
):
    path = Path(tmp) / "brolls" / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    if kind == "image":
        synth_image(path, color="blue", size="320x180")
    else:
        synth_video(path, size="320x180", duration=3, rate=10)
    digest_value = file_digest(path)
    ledger = Ledger(tmp)
    item = candidate("local", ident, title, source_url="https://example.org/" + ident)
    item["media"]["width"] = 320
    item["media"]["height"] = 180
    if kind == "video":
        item["media"]["duration_s"] = duration_s
        item["media"]["fps"] = 10
        set_segment(item, 2, 5)
    if approve:
        item["approval"] = {
            "status": "approved",
            "by": "Human",
            "at": now(),
            "revision": 1,
            "channel": "chat",
            "statement": "synthetic fixture approval",
        }
    item["rights"]["status"] = rights
    item["rights"]["evidence"] = ["Synthetic fixture license for tests only."]
    item["output"] = {"path": rel, "sha256": digest_value, "verified": True}
    item["state"] = "verified"
    item["acquisition"] = {"status": "available", "method": "local", "evidence": ["synthetic"]}
    if approve:
        item["approval"]["signature"] = signature(item)
    stored = ledger.add(item)
    ledger.save_many("fixture", [stored])
    return stored, digest_value


def _background_payload(candidate_id, ref, *, kind="video", raw="restricted"):
    payload = {
        "candidate_id": candidate_id,
        "ref": ref,
        "fit": "contain",
        "suitability": {
            "by": "Human",
            "statement": "Synthetic suitability for this fixture; preview access is not final use.",
            "at": "2026-10-11T00:00:00Z",
        },
        "material_use": {
            "rendered_use": "permitted",
            "raw_redistribution": raw,
            "evidence": ["Synthetic fixture rights evidence."],
            "conditions": "Finished-video use of the selected background.",
        },
    }
    if kind == "video":
        payload["source_start_s"] = 3
        payload["source_end_s"] = 5
    return payload


def _background_file(tmp, payload, name="background.json"):
    return _write(Path(tmp) / "brolls" / name, json.dumps(payload))


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


@skip_unless_ffmpeg
class GraphicsBackgroundWorkflowTests(unittest.TestCase):
    def test_video_and_photo_background_status_and_storyboard(self):
        with tempfile.TemporaryDirectory() as tmp:
            _project(tmp)
            video_item, _video_sha = _seed_media_candidate(
                tmp, ident="bg-video", title="Synthetic background video", rel="previews/bg-video.mp4"
            )
            photo_item, _photo_sha = _seed_media_candidate(
                tmp,
                ident="bg-photo",
                title="Synthetic background photo",
                rel="previews/bg-photo.png",
                kind="image",
            )
            _assign(tmp, occurrence="stat-01", scene="numeric-stat")
            _assign(
                tmp,
                occurrence="stat-02",
                scene="units-count",
                narration="A still photograph sits behind the count.",
            )
            video_file = _background_file(
                tmp,
                _background_payload(video_item["id"], "previews/bg-video.mp4", kind="video"),
                "bg-video.json",
            )
            photo_file = _background_file(
                tmp,
                _background_payload(photo_item["id"], "previews/bg-photo.png", kind="image", raw="permitted"),
                "bg-photo.json",
            )
            attached = run_cli(
                "graphics-background",
                "--occurrence",
                "stat-01",
                "--file",
                str(video_file),
                project=tmp,
            )
            self.assertEqual("stat-01", attached["occurrence"]["occurrence_id"])
            self.assertIn("background", attached["occurrence"])
            video_bg = attached["occurrence"]["background"]
            self.assertEqual(2, video_bg.get("representation_source_start_s"))
            self.assertEqual(1, video_bg.get("local_start_s"))
            self.assertEqual(3, video_bg.get("local_end_s"))
            self.assertEqual("resolved", video_bg.get("clock_state"))
            run_cli(
                "graphics-background",
                "--occurrence",
                "stat-02",
                "--file",
                str(photo_file),
                project=tmp,
            )
            before = sorted(path.relative_to(tmp).as_posix() for path in Path(tmp).rglob("*") if path.is_file())
            status = run_cli("status", project=tmp)
            after = sorted(path.relative_to(tmp).as_posix() for path in Path(tmp).rglob("*") if path.is_file())
            self.assertEqual(before, after)
            by_occ = {row["occurrence_id"]: row for row in status["graphics"]["items"]}
            self.assertEqual("video", by_occ["stat-01"]["background"]["kind"])
            self.assertEqual("image", by_occ["stat-02"]["background"]["kind"])
            self.assertNotIn("1080", json.dumps(by_occ["stat-01"]["background"]))
            review = run_cli("review", project=tmp)
            page = Path(tmp) / "brolls" / "review.html"
            html = page.read_text(encoding="utf-8")
            self.assertIn("Background", html)
            self.assertIn("previews/bg-video.mp4", html)
            self.assertIn("Still image background has no fabricated time interval.", html)
            self.assertNotIn("narration/private", html)
            dumped = json.dumps(review, ensure_ascii=False)
            self.assertNotIn("INWORLD", dumped.upper())
            self.assertIn("status", READ_ONLY_COMMANDS)

    def test_changed_media_is_scene_blocker(self):
        with tempfile.TemporaryDirectory() as tmp:
            _project(tmp)
            item, digest_value = _seed_media_candidate(
                tmp, ident="bg-video", title="Synthetic background video", rel="previews/bg-video.mp4"
            )
            _assign(tmp)
            payload = _background_payload(item["id"], "previews/bg-video.mp4")
            payload["sha256"] = digest_value
            path = _background_file(tmp, payload)
            run_cli("graphics-background", "--occurrence", "stat-01", "--file", str(path), project=tmp)
            (Path(tmp) / "brolls" / "previews" / "bg-video.mp4").write_bytes(b"changed-bytes")
            refused = run_cli(
                "graphics-background",
                "--occurrence",
                "stat-01",
                "--file",
                str(path),
                project=tmp,
                expect=2,
            )
            dumped = json.dumps(refused, ensure_ascii=False).lower()
            self.assertTrue("hash" in dumped or "sha256" in dumped or "changed" in dumped or "bytes" in dumped)

    def test_unsafe_ref_is_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            _project(tmp)
            _assign(tmp)
            path = _background_file(
                tmp,
                {
                    "ref": "../outside.mp4",
                    "candidate_id": "local:missing",
                    "fit": "contain",
                },
            )
            refused = run_cli(
                "graphics-background",
                "--occurrence",
                "stat-01",
                "--file",
                str(path),
                project=tmp,
                expect=2,
            )
            self.assertIn("error", refused)

    def test_video_render_freeze_and_held_delivery(self):
        with tempfile.TemporaryDirectory() as tmp:
            _project(tmp)
            item, digest_value = _seed_media_candidate(
                tmp, ident="bg-video", title="Synthetic background video", rel="previews/bg-video.mp4"
            )
            _assign(tmp, timing="explicit", start="0", end="1.5")
            path = _background_file(tmp, _background_payload(item["id"], "previews/bg-video.mp4", raw="restricted"))
            run_cli("graphics-background", "--occurrence", "stat-01", "--file", str(path), project=tmp)
            rendered = run_cli("graphics-render", "--occurrence", "stat-01", project=tmp, env=ENV)
            self.assertFalse(rendered["approved"])
            version_dir = Path(tmp) / "brolls" / "graphics" / "numeric-stat" / "v1"
            self.assertTrue((version_dir / "source" / "GraphicsBackground.jsx").is_file())
            job = json.loads((version_dir / "job.json").read_text(encoding="utf-8"))
            self.assertTrue(str(job["props"]["background"]["src"]).startswith("media/"))
            self.assertIs(True, job["props"]["background"].get("muted"))
            media_files = list((version_dir / "public" / "media").glob("*"))
            self.assertTrue(media_files)
            fingerprints = json.loads((version_dir / "fingerprints.json").read_text(encoding="utf-8"))
            self.assertIn("background", fingerprints)
            self.assertEqual(digest_value, fingerprints["background"]["assets"][0]["sha256"])
            self.assertEqual(set(BACKGROUND_TEMPLATE_FILES), set(fingerprints["source"]))
            _approve(tmp)
            delivered = run_cli("deliver", project=tmp)
            self.assertEqual(1, len(delivered["graphics"]))
            self.assertEqual("stat-01", delivered["graphics"][0]["occurrence"])
            self.assertEqual("v1", delivered["graphics"][0]["version"])
            status = run_cli("status", project=tmp)
            self.assertEqual(1, status["graphics"]["delivery"]["delivered"])
            self.assertTrue(status["graphics"]["items"][0]["deliverable"])
            pkg = Path(tmp) / "entrega" / "graphics" / "numeric-stat" / "stat-01" / "v1"
            held = json.loads((pkg / "separately-held.json").read_text(encoding="utf-8"))
            self.assertTrue(any(item.get("ref") == "previews/bg-video.mp4" for item in held))
            public_media = pkg / "public" / "media"
            if public_media.is_dir():
                self.assertFalse(any(public_media.iterdir()))
            listed = "\n".join(str(path) for path in pkg.rglob("*"))
            self.assertNotIn("narration/private", listed)

    def test_permitted_photo_package_keeps_editable_media(self):
        with tempfile.TemporaryDirectory() as tmp:
            _project(tmp)
            item, digest_value = _seed_media_candidate(
                tmp,
                ident="bg-photo",
                title="Synthetic background photo",
                rel="previews/bg-photo.png",
                kind="image",
            )
            _assign(tmp, timing="explicit", start="0", end="1.5")
            path = _background_file(
                tmp,
                _background_payload(item["id"], "previews/bg-photo.png", kind="image", raw="permitted"),
            )
            run_cli("graphics-background", "--occurrence", "stat-01", "--file", str(path), project=tmp)
            run_cli("graphics-render", "--occurrence", "stat-01", project=tmp, env=ENV)
            _approve(tmp)
            run_cli("deliver", project=tmp)
            pkg = Path(tmp) / "entrega" / "graphics" / "numeric-stat" / "stat-01" / "v1"
            self.assertTrue((pkg / "source" / "GraphicsBackground.jsx").is_file())
            hits = [
                path.relative_to(pkg).as_posix()
                for path in pkg.rglob("*")
                if path.is_file() and file_digest(path) == digest_value
            ]
            self.assertTrue(hits)

    def test_review_import_does_not_retarget_alignment_without_context(self):
        with tempfile.TemporaryDirectory() as tmp:
            _project(tmp)
            _assign(tmp)
            payload = _review_payload(tmp)
            payload["items"] = []
            payload["alignment"] = [
                {
                    "id": "alignment:stat-01",
                    "occurrence_id": "stat-01",
                    "signature": "00" * 32,
                    "reviewEpoch": "00" * 32,
                    "candidate_id": "c1",
                    "statement": "Stale correction must not apply.",
                }
            ]
            path = _write_review(tmp, payload)
            refused = run_cli("import-review", "--file", str(path), "--by", "Human", project=tmp, expect=2)
            dumped = json.dumps(refused, ensure_ascii=False).lower()
            self.assertTrue("stale" in dumped or "nenhuma" in dumped or "alignment" in dumped)

    def test_missing_suitability_and_unresolved_rights_are_separate_blockers(self):
        with tempfile.TemporaryDirectory() as tmp:
            _project(tmp)
            permitted, _ = _seed_media_candidate(
                tmp, ident="bg-suit", title="Suitability draft video", rel="previews/bg-suit.mp4"
            )
            denied, _ = _seed_media_candidate(
                tmp,
                ident="bg-rights",
                title="Unknown-rights video",
                rel="previews/bg-rights.mp4",
                rights="unknown",
            )
            _assign(tmp, occurrence="stat-01", scene="numeric-stat")
            _assign(tmp, occurrence="stat-02", scene="units-count", narration="A second numeric beat.")
            draft = _background_payload(permitted["id"], "previews/bg-suit.mp4")
            draft.pop("suitability")
            run_cli(
                "graphics-background",
                "--occurrence",
                "stat-01",
                "--file",
                str(_background_file(tmp, draft, "bg-suit.json")),
                project=tmp,
            )
            unresolved = _background_payload(denied["id"], "previews/bg-rights.mp4")
            refused = run_cli(
                "graphics-background",
                "--occurrence",
                "stat-02",
                "--file",
                str(_background_file(tmp, unresolved, "bg-rights.json")),
                project=tmp,
                expect=2,
            )
            self.assertIn("cannot be permitted", refused["error"])
            unresolved["material_use"]["rendered_use"] = "unknown"
            run_cli(
                "graphics-background",
                "--occurrence",
                "stat-02",
                "--file",
                str(_background_file(tmp, unresolved, "bg-rights.json")),
                project=tmp,
            )
            before = sorted(path.relative_to(tmp).as_posix() for path in Path(tmp).rglob("*") if path.is_file())
            status = run_cli("status", project=tmp)
            after = sorted(path.relative_to(tmp).as_posix() for path in Path(tmp).rglob("*") if path.is_file())
            self.assertEqual(before, after)
            by_occ = {row["occurrence_id"]: row for row in status["graphics"]["items"]}
            self.assertFalse(by_occ["stat-01"]["deliverable"])
            self.assertFalse(by_occ["stat-02"]["deliverable"])
            suit_reasons = json.dumps(by_occ["stat-01"]["reasons"]).lower()
            rights_reasons = json.dumps(by_occ["stat-02"]["reasons"]).lower()
            self.assertIn("suitability", suit_reasons)
            self.assertNotIn("missing_approval", by_occ["stat-01"]["reasons"])
            self.assertTrue(
                "permission" in rights_reasons or "rights" in rights_reasons or "unresolved" in rights_reasons
            )
            self.assertNotEqual(by_occ["stat-01"]["reasons"], by_occ["stat-02"]["reasons"])

    def test_missing_and_changed_media_block_without_status_writes(self):
        with tempfile.TemporaryDirectory() as tmp:
            _project(tmp)
            item, digest_value = _seed_media_candidate(
                tmp, ident="bg-video", title="Synthetic background video", rel="previews/bg-video.mp4"
            )
            _assign(tmp)
            path = _background_file(tmp, _background_payload(item["id"], "previews/bg-video.mp4"))
            run_cli("graphics-background", "--occurrence", "stat-01", "--file", str(path), project=tmp)
            media = Path(tmp) / "brolls" / "previews" / "bg-video.mp4"
            media.unlink()
            before = sorted(path.relative_to(tmp).as_posix() for path in Path(tmp).rglob("*") if path.is_file())
            status = run_cli("status", project=tmp)
            after = sorted(path.relative_to(tmp).as_posix() for path in Path(tmp).rglob("*") if path.is_file())
            self.assertEqual(before, after)
            reasons = json.dumps(status["graphics"]["items"][0]["reasons"]).lower()
            self.assertTrue("missing" in reasons or "file" in reasons or "background" in reasons)
            self.assertFalse(status["graphics"]["items"][0]["deliverable"])
            self.assertNotIn("INWORLD", json.dumps(status, ensure_ascii=False).upper())
            media.write_bytes(b"changed-bytes-not-the-original")
            status_changed = run_cli("status", project=tmp)
            changed_reasons = json.dumps(status_changed["graphics"]["items"][0]["reasons"]).lower()
            self.assertTrue("hash" in changed_reasons or "sha256" in changed_reasons or "changed" in changed_reasons)
            self.assertNotEqual(digest_value, file_digest(media))

    def test_old_version_sources_survive_a_new_render(self):
        with tempfile.TemporaryDirectory() as tmp:
            _project(tmp)
            item, digest_value = _seed_media_candidate(
                tmp, ident="bg-video", title="Synthetic background video", rel="previews/bg-video.mp4"
            )
            _assign(tmp, timing="explicit", start="0", end="1.5")
            path = _background_file(tmp, _background_payload(item["id"], "previews/bg-video.mp4"))
            run_cli("graphics-background", "--occurrence", "stat-01", "--file", str(path), project=tmp)
            first = run_cli("graphics-render", "--occurrence", "stat-01", project=tmp, env=ENV)
            v1 = Path(tmp) / "brolls" / "graphics" / "numeric-stat" / "v1"
            old = {rel.as_posix(): file_digest(rel) for rel in v1.rglob("*") if rel.is_file()}
            _assign(tmp, timing="explicit", start="0", end="1.5", narration="The count stands at twelve units.")
            second = run_cli("graphics-render", "--occurrence", "stat-01", project=tmp, env=ENV)
            self.assertEqual("v2", second["version"]["id"])
            self.assertEqual("v1", first["version"]["id"])
            for rel, digest_value_old in old.items():
                self.assertEqual(digest_value_old, file_digest(v1 / rel))
            self.assertEqual(
                digest_value,
                json.loads((v1 / "fingerprints.json").read_text(encoding="utf-8"))["background"]["assets"][0]["sha256"],
            )
            self.assertFalse(first["approved"])
            self.assertFalse(second["approved"])


class GraphicsBackgroundSourceSetTests(unittest.TestCase):
    def test_new_numeric_stat_source_set_includes_background_template(self):
        names = dict.fromkeys(BACKGROUND_TEMPLATE_FILES, "ab" * 32)
        self.assertEqual(BACKGROUND_TEMPLATE_FILES, _source_template_names(names))
        self.assertIn("GraphicsBackground.jsx", BACKGROUND_TEMPLATE_FILES)
        self.assertEqual(5, len(BACKGROUND_TEMPLATE_FILES))
        self.assertTrue((TEMPLATE_DIR / BACKGROUND_TEMPLATE).is_file())


class GraphicsMediaBrowserFixtureTests(unittest.TestCase):
    def test_storyboard_alignment_fixture_exports_bound_correction(self):
        script = ROOT / "tests" / "fixtures" / "storyboard_alignment.cjs"
        review_js = ROOT / "assets" / "review.js"
        self.assertTrue(script.is_file())
        self.assertTrue(review_js.is_file())
        done = subprocess.run(
            ["node", str(script), str(review_js)],
            capture_output=True,
            text=True,
            encoding="utf-8",
            check=False,
        )
        self.assertEqual(0, done.returncode, done.stderr or done.stdout)
        self.assertEqual("", (done.stderr or "").strip())
