"""Synthetic still ingestion: durable identity, recovery and project confinement."""

import copy
import os
import subprocess
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

import _isolation  # noqa: F401
import _paths  # noqa: F401
from _media import skip_unless_ffmpeg, synth_image

from getbrolls import ai, ai_provider, runtime
from getbrolls.ai_state import import_plan, new_job, review, version_signature
from getbrolls.ledger import Ledger, digest

ERROR_PRIVILEGE_NOT_HELD = 1314


@skip_unless_ffmpeg
class AICoreTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.project = Path(self.temp.name) / "project"
        ledger = Ledger(self.project)
        import_plan(
            ledger,
            {
                "scenario": "A resource runs out.",
                "style": "Restrained illustrative realism.",
                "beats": [
                    {
                        "id": "scarcity",
                        "route": "ai",
                        "text": "A resource runs out.",
                        "purpose": "Illustrate scarcity.",
                        "alternatives": ["An empty reservoir", "A final drop", "An empty warehouse"],
                    }
                ],
            },
        )
        self.job = new_job(
            ledger,
            {
                "beat": "scarcity",
                "inputs": ledger.data["ai"]["beats"]["scarcity"]["fingerprint"],
                "kind": "image",
                "route": "gpt-subscription",
                "alternative": "option-1",
                "prompt": "An empty reservoir",
            },
            "launch-once",
        )
        ledger.save("test-job")
        self.workdir = ledger.root / "ai-work" / self.job["id"]
        self.workdir.mkdir(parents=True)
        self.image = self.workdir / "native.png"
        synth_image(self.image, size="64x32")

    def stored(self):
        return Ledger(self.project).data["ai"]

    def finish(self, remote=None):
        ai._finish_outcome(self.project, self.job, {"status": "complete", "path": str(self.image), "remote": remote})

    def test_worker_waits_for_competing_project_write_before_first_submission(self):
        self.contended_worker("claim")

    def test_worker_retains_generated_result_after_competing_project_write(self):
        self.contended_worker("result")

    def contended_worker(self, stage):
        attempted = threading.Event()
        produced = threading.Event()
        proceed = threading.Event()
        errors = []
        acquire = runtime._acquire_lock

        def noticed(stream, *args, **kwargs):
            try:
                return acquire(stream, *args, **kwargs)
            except BlockingIOError:
                attempted.set()
                raise

        def run():
            try:
                ai.run_worker(self.project, self.job["id"])
            except (ValueError, OSError, KeyError) as exc:
                errors.append(exc)

        def result(*args, **kwargs):
            produced.set()
            if not proceed.wait(3):
                raise TimeoutError("The synthetic provider was not released")
            return {"status": "complete", "path": str(self.image)}

        with (
            patch("getbrolls.runtime._acquire_lock", side_effect=noticed),
            patch.object(ai, "generate_still", side_effect=result) as produce,
        ):
            worker = threading.Thread(target=run)
            if stage == "result":
                worker.start()
                self.assertTrue(produced.wait(2))
            with runtime.project_lock(self.project):
                proceed.set()
                if stage == "claim":
                    worker.start()
                collided = attempted.wait(2)
            worker.join(5)
            self.assertTrue(collided, "The worker must contend with an actual project writer")
            self.assertFalse(worker.is_alive())
            self.assertFalse(errors, errors)
            self.assertEqual("complete", self.stored()["jobs"][self.job["id"]]["state"])
            self.assertEqual(1, produce.call_count)

    def test_project_lock_remains_fail_fast_by_default_and_bounds_opt_in_wait(self):
        with runtime.project_lock(self.project):
            with self.assertRaisesRegex(ValueError, "Outro comando"), runtime.project_lock(self.project):
                self.fail("A competing writer must never enter")
            with self.assertRaisesRegex(ValueError, "Outro comando"), runtime.project_lock(self.project, timeout=0.05):
                self.fail("A lock timeout must never enter the critical section")
        with runtime.project_lock(self.project, timeout=0.05):
            self.assertEqual("queued", self.stored()["jobs"][self.job["id"]]["state"])

    def directory_link(self, link, target):
        try:
            link.symlink_to(target, target_is_directory=True)
        except OSError as exc:
            if os.name != "nt" or getattr(exc, "winerror", None) != ERROR_PRIVILEGE_NOT_HELD:
                raise
            result = subprocess.run(
                ["cmd", "/c", "mklink", "/J", str(link), str(target)],
                capture_output=True,
                check=False,
            )
            self.assertEqual(0, result.returncode, result.stderr)
        self.addCleanup(lambda: link.unlink() if link.is_symlink() else link.rmdir())

    def test_duplicate_completion_and_late_failure_preserve_exact_approved_result(self):
        self.finish()
        ledger = Ledger(self.project)
        ident = ledger.data["ai"]["jobs"][self.job["id"]]["result"]
        version = ledger.data["ai"]["versions"][ident]
        review(
            ledger,
            {"version": ident, "signature": version_signature(version), "decision": "approved", "by": "Test editor"},
        )
        approved = copy.deepcopy(self.stored()["versions"][ident])
        self.finish({"threadId": "late-thread"})
        ai._store_terminal(self.project, self.job["id"], {"state": "unknown", "message": "Late lost acknowledgement"})
        stored = self.stored()
        self.assertEqual([ident], list(stored["versions"]))
        self.assertEqual(approved, stored["versions"][ident])
        self.assertEqual("complete", stored["jobs"][self.job["id"]]["state"])
        self.assertEqual(ident, stored["jobs"][self.job["id"]]["result"])
        self.assertEqual(1, len(list((self.project / "brolls/previews").glob("ai-*.png"))))

    def test_concurrent_result_copies_attach_once_and_remove_unreferenced_copy(self):
        first = ai._ingest_still(self.project / "brolls", self.job, self.image)
        second = ai._ingest_still(self.project / "brolls", self.job, self.image)
        ai._commit_result(self.project, self.job["id"], first)
        ai._commit_result(self.project, self.job["id"], second)
        self.assertEqual([first["id"]], list(self.stored()["versions"]))
        self.assertTrue((self.project / "brolls" / first["path"]).is_file())
        self.assertFalse((self.project / "brolls" / second["path"]).exists())

    def test_resume_requires_recorded_result_identity_and_does_not_scan_reference_images(self):
        ledger = Ledger(self.project)
        job = ledger.data["ai"]["jobs"][self.job["id"]]
        job.update(state="unknown", submit_outcome="unknown", remote={"threadId": "thread"})
        ledger.save("test-unknown")
        with (
            patch.object(ai, "generate_still", side_effect=AssertionError("Recovery must not generate")),
            patch.object(ai_provider, "retrieve_still", return_value={"status": "unknown"}) as retrieve,
        ):
            ai.run_worker(self.project, job["id"], retrieve=True)
        retrieve.assert_called_once()
        self.assertFalse(self.stored()["versions"])
        self.assertEqual("unknown", self.stored()["jobs"][job["id"]]["state"])

    def record_received(self):
        ledger = Ledger(self.project)
        job = ledger.data["ai"]["jobs"][self.job["id"]]
        job.update(
            state="downloading",
            submit_outcome="accepted",
            remote={
                "threadId": "thread",
                "artifact": self.image.name,
                "artifact_sha256": digest(self.image),
            },
        )
        ledger.save("test-received")

    def test_resume_uses_only_recorded_native_result_and_checks_its_hash(self):
        self.record_received()
        (self.workdir / "000-reference.png").write_bytes(b"unrelated uploaded reference")
        with patch.object(ai, "generate_still", side_effect=AssertionError("Recovery must not generate")):
            ai.run_worker(self.project, self.job["id"], retrieve=True)
        version = next(iter(self.stored()["versions"].values()))
        self.assertEqual(digest(self.image), version["sha256"])
        self.assertEqual((64, 32), (version["width"], version["height"]))

    def test_changed_recorded_artifact_is_rejected_without_attaching_result(self):
        self.record_received()
        self.image.write_bytes(b"replaced result")
        with patch.object(ai_provider, "retrieve_still", side_effect=AssertionError("Keep the recorded original")):
            ai.run_worker(self.project, self.job["id"], retrieve=True)
        stored = self.stored()
        self.assertFalse(stored["versions"])
        self.assertEqual("failed", stored["jobs"][self.job["id"]]["state"])
        self.assertIn("changed", stored["jobs"][self.job["id"]]["error"]["message"])

    def test_result_receipt_survives_local_ingestion_error_and_can_resume(self):
        with patch.object(ai, "_ingest_still", side_effect=OSError("Transient local copy error")):
            self.finish({"threadId": "thread", "turnId": "turn"})
        ledger = Ledger(self.project)
        job = ledger.data["ai"]["jobs"][self.job["id"]]
        self.assertEqual(digest(self.image), job["remote"]["artifact_sha256"])
        response = ai.resume_command(ledger, type("Args", (), {"job": job["id"]})())
        self.assertTrue(response["ai_dispatch"]["retrieve"])
        with patch.object(ai, "generate_still", side_effect=AssertionError("Recovery must not generate")):
            ai.run_worker(self.project, job["id"], retrieve=True)
        self.assertEqual("complete", self.stored()["jobs"][job["id"]]["state"])

    def test_linked_artifact_parent_is_rejected(self):
        outside = Path(self.temp.name) / "outside"
        outside.mkdir()
        outside_image = outside / "native.png"
        outside_image.write_bytes(self.image.read_bytes())
        linked = self.workdir / "linked"
        self.directory_link(linked, outside)
        with self.assertRaisesRegex(ValueError, "symlink or junction"):
            ai._ingest_still(self.project / "brolls", self.job, linked / outside_image.name)
        self.assertFalse(self.stored()["versions"])

    def test_changed_beat_does_not_present_previous_context_result_as_current(self):
        self.finish()
        ledger = Ledger(self.project)
        state = ledger.data["ai"]
        original = next(iter(state["versions"].values()))
        import_plan(
            ledger,
            {
                "scenario": state["plan"]["scenario"],
                "style": state["style"]["prompt"],
                "beats": [{**state["beats"]["scarcity"], "purpose": "A materially different visual purpose"}],
            },
        )
        board = ai.public_board(ledger)
        self.assertIsNone(board["beats"][0]["job"])
        self.assertIsNone(board["beats"][0]["version"])
        self.assertNotIn("data-ai-version=", ai.storyboard_section(ledger))
        self.assertEqual(original["inputs"], ai.review_records(ledger, "synthetic")[0]["fingerprint"])
        self.assertEqual([original["id"]], list(ledger.data["ai"]["versions"]))

    def test_linked_preview_directory_is_rejected(self):
        previews = self.project / "brolls/previews"
        previews.rmdir()
        outside = Path(self.temp.name) / "outside-previews"
        outside.mkdir()
        self.directory_link(previews, outside)
        with self.assertRaisesRegex(ValueError, "symlink or junction"):
            ai._ingest_still(self.project / "brolls", self.job, self.image)
        self.assertFalse(list(outside.iterdir()))

    def test_review_export_keeps_comment_bound_to_exact_decision(self):
        self.finish()
        ledger = Ledger(self.project)
        version = next(iter(ledger.data["ai"]["versions"].values()))
        review(
            ledger,
            {
                "version": version["id"],
                "signature": version_signature(version),
                "decision": "changes",
                "by": "Test editor",
                "comment": "Change the lighting of this still",
            },
        )
        ledger.data["ai"]["beats"]["scarcity"]["comment"] = "A new scene prompt"
        ledger.save("test-new-scene-draft")
        self.assertEqual("Change the lighting of this still", ai.review_records(ledger, "synthetic")[0]["comment"])

    def test_inactive_beat_is_explicit_in_read_only_board_state(self):
        ledger = Ledger(self.project)
        ledger.data["ai"]["beats"]["scarcity"]["active"] = False
        ledger.save("test-reroute")
        self.assertFalse(ai.public_board(ledger)["beats"][0]["active"])

    def test_native_jpeg_preserves_real_dimensions_codec_and_hash(self):
        jpeg = self.workdir / "native.jpg"
        synth_image(jpeg, color="blue", size="64x32")
        ai._finish_outcome(self.project, self.job, {"status": "complete", "path": str(jpeg)})
        version = next(iter(self.stored()["versions"].values()))
        self.assertEqual((64, 32, "mjpeg"), (version["width"], version["height"], version["codec"]))
        self.assertEqual(digest(jpeg), version["sha256"])
        self.assertEqual(digest(jpeg), version["original_sha256"])
        self.assertTrue(version["path"].endswith(".jpg"))

    def test_named_png_with_invalid_bytes_is_not_media_completion(self):
        self.image.write_bytes(b"A text answer saved with a PNG name")
        self.finish()
        stored = self.stored()
        self.assertFalse(stored["versions"])
        self.assertEqual("failed", stored["jobs"][self.job["id"]]["state"])
