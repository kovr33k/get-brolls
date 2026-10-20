"""Reviewed AI media reaches the shared protected handoff through public actions."""

import base64
import hashlib
import json
import subprocess
import unittest
from pathlib import Path
from urllib.parse import quote
from urllib.request import Request, urlopen

import _isolation  # noqa: F401
import test_ai_openrouter_public as paid_helpers
from _media import skip_unless_ffmpeg


@skip_unless_ffmpeg
class AIDeliveryPublicTests(unittest.TestCase):
    def setUp(self):
        self.media = paid_helpers.OpenRouterPublicTests()
        self.addCleanup(self.media.doCleanups)
        self.media.setUp()
        self.media.ready_video()
        self.launch_count = 0
        self.clip_count = 0

    def video_bytes(self, *, color="blue", seconds=2, size="1920x1080", audio=False):
        self.clip_count += 1
        path = Path(self.media.temp.name) / f"{color}-{size}-{self.clip_count}.mp4"
        args = ["ffmpeg", "-v", "error", "-f", "lavfi", "-i", f"color=c={color}:s={size}:r=30:d={seconds}"]
        if audio:
            args += ["-f", "lavfi", "-i", f"sine=frequency=660:duration={seconds}"]
        subprocess.run(
            [*args, "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p", str(path)],
            check=True,
            capture_output=True,
        )
        return path.read_bytes()

    def launch(self, **clip):
        media = self.media
        media.responses = [paid_helpers.video_capabilities()]
        self.launch_count += 1
        _body, jobs = media.prepare(kind="video", version=media.still["id"], nonce=f"delivery-{self.launch_count}")
        media.responses = [
            {"id": "delivery-video"},
            {"status": "completed", "video": {"url": "https://media.example.com/clip.mp4"}},
            self.video_bytes(**clip),
        ]
        result = media.confirm(jobs)[0]
        self.assertEqual("complete", result["state"], result)
        return next(v for v in json.loads(media.http("/__ai/state")[1])["versions"] if v["id"] == result["result"])

    def approve(self, version):
        status, raw = self.media.http(
            "/__ai",
            {
                "action": "review",
                "version": version["id"],
                "signature": version["signature"],
                "decision": "approved",
                "by": "Test editor",
            },
        )
        self.assertEqual(200, status, raw)

    def permit(self, version, **extra):
        status, raw = self.media.http(
            "/__ai",
            {
                "action": "material-use",
                "version": version["id"],
                "signature": version["signature"],
                "state": "permitted",
                "conditions": "Synthetic test output and guided inputs may be used in this project",
                "evidence": "Synthetic fixture permission, not a real provider license",
                "by": "Test editor",
                **extra,
            },
        )
        self.assertEqual(200, status, raw)
        return json.loads(raw)

    def test_editorial_approval_does_not_invent_material_use_permission_or_deliver_unreviewed_media(self):
        version = self.launch()
        report = self.media.call("deliver")
        self.assertFalse(report["ai"])
        self.assertIn("approval_required", report["ai_skipped"][0]["reasons"])
        self.approve(version)
        report = self.media.call("deliver")
        self.assertFalse(report["ai"])
        self.assertIn("material_use_unresolved", report["ai_skipped"][0]["reasons"])
        self.assertFalse((self.media.project / "entrega/ai").exists())

    def test_full_hd_approved_output_and_separate_narration_reach_shared_handoff_with_exact_timing(self):
        media = self.media
        version = self.launch(audio=True)
        self.approve(version)
        self.permit(version)
        expected_video = (media.project / "brolls" / version["path"]).read_bytes()
        dry = media.call("deliver", "--dry-run")
        self.assertEqual("planned", dry["ai"][0]["method"])
        self.assertFalse((media.project / "entrega").exists())
        report = media.call("deliver")
        self.assertEqual(1, len(report["ai"]))
        entry = report["ai"][0]
        package = media.project / entry["package_dir"]
        self.assertEqual(expected_video, (media.project / entry["path"]).read_bytes())
        self.assertTrue((package / "narration.wav").read_bytes().startswith(b"RIFF"))
        timing = json.loads((package / "timing.json").read_text(encoding="utf-8"))
        self.assertEqual({"start_frame": 0, "end_frame": 60, "start_s": 0.0, "end_s": 2.0}, timing["placement"])
        self.assertEqual(30, timing["fps"])
        self.assertEqual("narration.wav", timing["narration"]["path"])
        provenance = json.loads((package / "provenance.json").read_text(encoding="utf-8"))
        self.assertEqual("ai-generated", provenance["kind"])
        self.assertEqual("scarcity", provenance["beat"])
        self.assertEqual(version["signature"], provenance["signature"])
        self.assertEqual("permitted", provenance["material_use"]["state"])
        self.assertEqual(version["sha256"], hashlib.sha256(expected_video).hexdigest())
        self.assertEqual(1920, provenance["output"]["width"])
        self.assertEqual(1080, provenance["output"]["height"])
        self.assertEqual(media.still["sha256"], provenance["sources"][0]["still"]["sha256"])
        self.assertIn("AI coverage", (media.project / "entrega/README.md").read_text(encoding="utf-8"))

    def test_native_profile_shortfall_and_missing_coverage_are_not_delivered_as_finished_video(self):
        for values, reason in [({"size": "160x90"}, "profile_shortfall"), ({"seconds": 1}, "coverage_shortfall")]:
            with self.subTest(reason=reason):
                version = self.launch(**values)
                self.approve(version)
                self.permit(version)
                report = self.media.call("deliver")
                self.assertFalse(report["ai"])
                self.assertIn(reason, report["ai_skipped"][0]["reasons"])
                self.assertFalse((self.media.project / "entrega/ai").exists())

    def test_repeat_delivery_keeps_foreign_files_and_rejects_modified_metadata_without_touching_originals(self):
        media = self.media
        version = self.launch()
        self.approve(version)
        self.permit(version)
        entry = media.call("deliver")["ai"][0]
        package = media.project / entry["package_dir"]
        foreign = media.project / "entrega/ai/foreign/ORIGEM.md"
        foreign.parent.mkdir(parents=True)
        foreign.write_text("User-owned notes", encoding="utf-8")
        before = len(media.requests)
        again = media.call("deliver")
        self.assertEqual(entry["path"], again["ai"][0]["path"])
        self.assertEqual("User-owned notes", foreign.read_text(encoding="utf-8"))
        metadata = package / "timing.json"
        metadata.write_text("User editing timeline", encoding="utf-8")
        self.assertIn("message", media.call("deliver", ok=False))
        self.assertEqual("User editing timeline", metadata.read_text(encoding="utf-8"))
        original = media.project / "brolls" / version["path"]
        self.assertEqual(version["sha256"], hashlib.sha256(original.read_bytes()).hexdigest())
        self.assertEqual(before, len(media.requests))

    def test_read_only_status_separates_ready_delivered_and_modified_package_without_recovery_or_lock(self):
        from getbrolls.runtime import project_lock

        media = self.media
        version = self.launch()
        self.approve(version)
        self.permit(version)
        manifest = media.project / "brolls/manifest.json"
        original = manifest.read_bytes()
        with project_lock(media.project):
            status = media.call("status")
        self.assertEqual(original, manifest.read_bytes())
        self.assertEqual(1, status["ai"]["delivery"]["undelivered"])
        self.assertIn("AI: 0 entregues, 1 pronto", status["summary"]["line"])
        self.assertEqual("deliver", status["summary"]["do"]["step"])
        entry = media.call("deliver")["ai"][0]
        status = media.call("status")
        self.assertEqual(1, status["ai"]["delivery"]["delivered"])
        self.assertNotEqual("search", status["summary"]["do"]["step"])
        metadata = media.project / entry["package_dir"] / "timing.json"
        metadata.write_text("User timeline", encoding="utf-8")
        original = manifest.read_bytes()
        with project_lock(media.project):
            status = media.call("status")
        self.assertEqual(original, manifest.read_bytes())
        self.assertEqual(0, status["ai"]["delivery"]["delivered"])
        self.assertEqual("modified_or_missing", status["ai"]["delivery"]["beats"][0]["delivery_state"])
        self.assertEqual("User timeline", metadata.read_text(encoding="utf-8"))

    def test_material_use_cli_binds_exact_version_and_revocation_preserves_prior_package(self):
        media = self.media
        version = self.launch()
        self.approve(version)
        args = (
            "ai-material-use",
            "--version",
            version["id"],
            "--state",
            "permitted",
            "--by",
            "Editor",
            "--conditions",
            "Synthetic project use",
            "--evidence",
            "Fixture only",
        )
        self.assertIn("message", media.call(*args, "--signature", "0" * 64, ok=False))
        result = media.call(*args, "--signature", version["signature"])
        self.assertEqual("permitted", result["material_use"]["state"])
        first = media.call("deliver")["ai"][0]
        self.permit(version, state="blocked", conditions="Fixture use revoked")
        report = media.call("deliver")
        self.assertFalse(report["ai"])
        self.assertIn("material_use_blocked", report["ai_skipped"][0]["reasons"])
        self.assertTrue((media.project / first["path"]).is_file())
        self.assertEqual(0, media.call("status")["ai"]["delivery"]["delivered"])

    def test_sequence_handoff_keeps_order_originals_tail_trim_and_portable_review(self):
        media = self.media
        media.call(
            "ai-timing-resolve",
            "--beat",
            "scarcity",
            "--analysis",
            "na-1",
            "--by",
            "Editor",
            "--statement",
            "Fixture span",
            "--start",
            "0.5",
            "--end",
            "8.5",
        )
        media.responses = [paid_helpers.video_capabilities()]
        status, raw = media.http(
            "/__ai",
            {
                "action": "prepare-sequence",
                "route": "openrouter",
                "beat": "scarcity",
                "version": media.still["id"],
                "requestId": "delivery-sequence",
            },
        )
        self.assertEqual(200, status, raw)
        sequence = json.loads(raw)["sequence"]
        originals = [self.video_bytes(color="red", seconds=6), self.video_bytes(color="blue", seconds=3, audio=True)]
        media.responses = [
            item
            for index, data in enumerate(originals)
            for item in (
                {"id": f"clip-{index}"},
                {"status": "completed", "video": {"url": f"https://media.example.com/{index}.mp4"}},
                data,
            )
        ]
        media.confirm([clip["job"] for clip in sequence["clips"]])
        result = json.loads(media.http("/__ai/state")[1])["beats"][0]["sequence"]
        self.assertEqual("complete", result["state"], result)
        version = result["version"]
        self.permit(version)
        self.assertIn("approval_required", media.call("deliver")["ai_skipped"][0]["reasons"])
        self.approve(version)
        entry = media.call("deliver")["ai"][0]
        package = media.project / entry["package_dir"]
        timing = json.loads((package / "timing.json").read_text(encoding="utf-8"))
        self.assertEqual(15, timing["placement"]["start_frame"])
        self.assertEqual(255, timing["placement"]["end_frame"])
        self.assertEqual([15, 195], [row["placement"]["start_frame"] for row in timing["clips"]])
        self.assertEqual([180, 60], [row["trim_end_frame"] for row in timing["clips"]])
        for index, data in enumerate(originals):
            self.assertEqual(data, (package / f"originals/{index + 1:03}.mp4").read_bytes())
        self.assertEqual(1, media.call("status")["ai"]["delivery"]["delivered"])
        media.call("review")
        page = (media.project / "brolls/review.html").read_text(encoding="utf-8")
        self.assertIn("AI handoff", page)
        self.assertIn("permitted", page)
        self.assertEqual(entry["path"], media.call("deliver")["ai"][0]["path"])

    def test_changed_or_missing_original_and_narration_block_current_handoff_preserving_history(self):
        media = self.media
        version = self.launch()
        self.approve(version)
        self.permit(version)
        first = media.call("deliver")["ai"][0]
        original = media.project / "brolls" / version["path"]
        saved = original.read_bytes()
        original.write_bytes(b"Changed result")
        self.assertIn("media_or_inputs_changed", media.call("deliver")["ai_skipped"][0]["reasons"])
        original.write_bytes(saved)
        media.plant(paid_helpers.SENTENCE, paid_helpers._words(paid_helpers.SENTENCE, 0, 2000), amplitude=1234)
        self.assertIn("media_or_inputs_changed", media.call("deliver")["ai_skipped"][0]["reasons"])
        self.assertTrue((media.project / first["path"]).is_file())
        self.assertEqual("approved", media.ai()["versions"][version["id"]]["approval"]["state"])

    def test_guided_revision_provenance_keeps_actual_reference_and_instruction_ancestry(self):
        from getbrolls import serve
        from getbrolls.ai_state import version_signature

        media = self.media
        metadata = {
            "beat": "scarcity",
            "fingerprint": media.ai()["beats"]["scarcity"]["fingerprint"],
            "identity": "delivery-ref",
            "name": "reference.png",
            "declared_type": "image/png",
            "instructions": "Keep the red palette",
            "role": "appearance",
            "scope": "beat",
        }
        request = Request(
            media.base + serve.AI_REFERENCE_PATH,
            data=media.image_bytes,
            headers={serve.TOKEN_HEADER: media.token, serve.AI_REFERENCE_HEADER: quote(json.dumps(metadata))},
        )
        with urlopen(request, timeout=15) as response:
            ref = json.loads(response.read())["reference"]
        media.launch_native_still("delivery-guided")
        parent = media.still
        media.responses = [{"data": [{"b64_json": base64.b64encode(media.image_bytes).decode()}]}]
        status, raw = media.http(
            "/__ai",
            {
                "action": "apply",
                "beat": "scarcity",
                "requestId": "delivery-edit",
                "still": {"id": parent["id"], "signature": version_signature(parent)},
                "instruction": "Darken the sky",
            },
        )
        self.assertEqual(200, status, raw)
        media.still = media.ai()["versions"][json.loads(raw)["job"]["result"]]
        self.approve({**media.still, "signature": version_signature(media.still)})
        media.call("ai-timing", "--beat", "scarcity", "--analysis", "na-1", "--still", media.still["id"])
        version = self.launch()
        self.approve(version)
        self.permit(version)
        entry = media.call("deliver")["ai"][0]
        package = media.project / entry["package_dir"]
        provenance = json.loads((package / "provenance.json").read_text(encoding="utf-8"))
        lineage = provenance["sources"][0]["still"]["lineage"]
        self.assertEqual([media.still["id"], parent["id"]], [item["version"] for item in lineage])
        self.assertIn("Darken the sky", lineage[0]["prompt"])
        self.assertEqual(hashlib.sha256(media.image_bytes).hexdigest(), lineage[1]["provider_inputs"][0]["sent_sha256"])
        self.assertIn("Keep the red palette", json.dumps(lineage))
        self.assertFalse(any(path.suffix == ".png" for path in package.rglob("*")))
        self.assertTrue(ref["context_id"])

    def test_mixed_source_and_graphics_delivery_continue_when_ai_input_becomes_stale(self):
        from test_delivery import fetched
        from test_delivery import project as seed_source
        from test_graphics_delivery import _approve, _assign_explicit
        from test_graphics_review import _render

        media = self.media
        _assign_explicit(media.project, confirm_fps=30)
        media.call("ai-timing", "--beat", "scarcity", "--analysis", "na-1", "--still", media.still["id"])
        version = self.launch()
        self.approve(version)
        self.permit(version)
        seed_source(media.project, [fetched("documentary", "Documentary source")])
        _render(media.project)
        _approve(media.project)
        report = media.call("deliver", timeout=30)
        self.assertEqual((1, 1, 1), tuple(len(report[key]) for key in ("items", "graphics", "ai")))
        media.plant(paid_helpers.SENTENCE, paid_helpers._words(paid_helpers.SENTENCE, 0, 2000), amplitude=1234)
        report = media.call("deliver", timeout=30)
        self.assertEqual((1, 1, 0), tuple(len(report[key]) for key in ("items", "graphics", "ai")))
        self.assertIn("media_or_inputs_changed", report["ai_skipped"][0]["reasons"])

    def test_ai_destination_link_never_writes_outside_project(self):
        from test_graphics_delivery import _make_dir_link, _remove_dir_link

        media = self.media
        version = self.launch()
        self.approve(version)
        self.permit(version)
        outside = Path(media.temp.name) / "outside"
        outside.mkdir()
        (media.project / "entrega").mkdir()
        link = media.project / "entrega/ai"
        if not _make_dir_link(link, outside):
            self.skipTest("Could not create a destination link or junction")
        self.addCleanup(_remove_dir_link, link)
        self.assertIn("message", media.call("deliver", ok=False))
        self.assertFalse(list(outside.iterdir()))

    def test_foreign_file_conflict_is_preflighted_before_any_ai_package_copy(self):
        media = self.media
        version = self.launch()
        self.approve(version)
        self.permit(version)
        entry = media.call("deliver", "--dry-run")["ai"][0]
        package = media.project / entry["package_dir"]
        package.mkdir(parents=True)
        foreign = package / "provenance.json"
        foreign.write_text("User file", encoding="utf-8")
        self.assertIn("message", media.call("deliver", ok=False))
        self.assertEqual([foreign], list(package.iterdir()))
        self.assertEqual("User file", foreign.read_text(encoding="utf-8"))

    def test_new_version_and_changed_project_profile_never_reuse_prior_readiness(self):
        from test_graphics_delivery import _assign_explicit

        media = self.media
        first = self.launch()
        self.approve(first)
        self.permit(first)
        entry = media.call("deliver")["ai"][0]
        second = self.launch(color="red")
        report = media.call("deliver")
        self.assertFalse(report["ai"])
        self.assertEqual(second["id"], report["ai_skipped"][0]["version"])
        self.assertIn("approval_required", report["ai_skipped"][0]["reasons"])
        self.assertTrue((media.project / entry["path"]).is_file())
        self.approve(second)
        self.permit(second)
        _assign_explicit(media.project, confirm_fps=24)
        report = media.call("deliver")
        self.assertFalse(report["ai"])
        self.assertIn("profile_context_changed", report["ai_skipped"][0]["reasons"])


if __name__ == "__main__":
    unittest.main()
