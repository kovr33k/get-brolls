"""Explicit recovery and bounded correction through the authenticated Storyboard seam."""

import base64
import json
import os
import unittest
from concurrent.futures import ThreadPoolExecutor
from http.client import HTTPMessage
from threading import Event
from unittest.mock import patch
from urllib.error import HTTPError, URLError

import _isolation  # noqa: F401
import test_ai_openrouter_public as paid_helpers
import test_ai_sequences_public as sequence_helpers
from _media import skip_unless_ffmpeg

from getbrolls.ai_state import version_signature


@skip_unless_ffmpeg
class RecoveryPublicTests(unittest.TestCase):
    def setUp(self):
        self.flow = sequence_helpers.SequencePublicTests()
        self.addCleanup(self.flow.doCleanups)
        self.flow.setUp()
        self.media = self.flow.media

    def test_restart_recovers_local_sequence_after_all_originals_committed_without_generation(self):
        media = self.media
        plan = self.flow.prepare()
        media.responses = [
            {"request_id": "recover-1"},
            {"status": "done", "video": {"url": "https://media.example.com/1.mp4"}},
            self.flow.clip("red", 6),
            {"request_id": "recover-2"},
            {"status": "done", "video": {"url": "https://media.example.com/2.mp4"}},
            self.flow.clip("blue", 2),
        ]
        with patch.dict(os.environ, {"GETBROLLS_AI_TEST_CRASH": "assembly"}):
            status, raw = media.http(
                "/__ai", {"action": "launch-sequence", "sequence": plan["id"], "signature": plan["signature"]}
            )
        self.assertEqual(200, status, raw)
        before = json.loads(media.http("/__ai/state")[1])["beats"][0]["sequence"]
        self.assertIsNone(before["version"])
        self.assertEqual(["complete", "complete"], [clip["job"]["state"] for clip in before["clips"]])
        originals = [clip["job"]["result"] for clip in before["clips"]]
        requests = len(media.requests)
        media.server_restart()
        body = {"action": "resume-sequence", "sequence": plan["id"], "signature": plan["signature"]}
        status, raw = media.http("/__ai", body)
        self.assertEqual(200, status, raw)
        recovered = json.loads(raw)["sequence"]
        self.assertEqual("complete", recovered["state"], raw)
        self.assertEqual("pending", recovered["version"]["approval"])
        self.assertEqual(originals, [clip["job"]["result"] for clip in recovered["clips"]])
        self.assertEqual(200, media.http("/__ai", body)[0])
        self.assertEqual(requests, len(media.requests))
        self.assertEqual(
            recovered["version"]["id"],
            json.loads(media.http("/__ai/state")[1])["beats"][0]["sequence"]["version"]["id"],
        )

    def test_observed_still_defect_allows_one_frozen_correction_across_restart_and_preserves_approval(self):
        media = self.media
        original = media.still
        original_job = original["job"]
        body = {
            "action": "correct",
            "job": original_job,
            "requestId": "fix-observed-defect",
            "defect": "The wall has a visible duplicated edge",
            "instruction": "Remove only the duplicated edge",
            "by": "Test editor",
        }
        body["signature"] = version_signature(original)
        media.responses = [{"data": [{"b64_json": base64.b64encode(media.image_bytes).decode()}]}]
        status, raw = media.http("/__ai", body)
        self.assertEqual(200, status, raw)
        corrected = json.loads(raw)["job"]
        self.assertEqual("complete", corrected["state"], raw)
        self.assertEqual(original_job, corrected["correction_of"])
        self.assertEqual("The wall has a visible duplicated edge", corrected["correction"]["defect"])
        state = json.loads(media.http("/__ai/state")[1])
        versions = {v["id"]: v for v in state["versions"]}
        self.assertEqual("approved", versions[original["id"]]["approval"])
        self.assertEqual("pending", versions[corrected["result"]]["approval"])
        submitted = len(media.requests)
        media.server_restart()
        self.assertEqual(200, media.http("/__ai", body)[0])
        self.assertEqual(submitted, len(media.requests))
        self.assertEqual(400, media.http("/__ai", {**body, "requestId": "another-fix"})[0])
        child_version = versions[corrected["result"]]
        self.assertEqual(
            400,
            media.http(
                "/__ai", {**body, "job": corrected["id"], "signature": child_version["signature"], "requestId": "chain"}
            )[0],
        )
        self.assertEqual(400, media.http("/__ai", {**body, "instruction": "A different request"})[0])
        self.assertEqual(submitted, len(media.requests))

    def test_sequence_correction_replaces_only_defective_clip_and_cannot_reset_allowance_via_other_clip(self):
        media = self.media
        plan = self.flow.prepare()
        media.responses = [
            {"request_id": "short"},
            *media.done(),
            {"request_id": "intact"},
            {"status": "done", "video": {"url": "https://media.example.com/2.mp4"}},
            self.flow.clip("blue", 2),
        ]
        status, raw = media.http(
            "/__ai", {"action": "launch-sequence", "sequence": plan["id"], "signature": plan["signature"]}
        )
        self.assertEqual(200, status, raw)
        partial = json.loads(raw)["sequence"]
        bad, intact = [clip["job"] for clip in partial["clips"]]
        original = media.ai()["versions"][bad["result"]]
        body = {
            "action": "correct",
            "job": bad["id"],
            "signature": version_signature(original),
            "requestId": "correct-sequence",
            "defect": "Clip ends after one second, leaving five seconds uncovered",
            "instruction": "Generate the requested complete six seconds",
            "by": "Test editor",
        }
        before = len([r for r in media.requests if r.method == "POST"])
        media.responses = [
            {"request_id": "corrected"},
            {"status": "done", "video": {"url": "https://media.example.com/corrected.mp4"}},
            self.flow.clip("red", 6),
        ]
        status, raw = media.http("/__ai", body)
        self.assertEqual(200, status, raw)
        child = json.loads(raw)["job"]
        self.assertEqual("complete", child["state"], raw)
        state = json.loads(media.http("/__ai/state")[1])
        sequence = state["beats"][0]["sequence"]
        self.assertEqual("complete", sequence["state"], sequence)
        self.assertEqual([child["id"], intact["id"]], [clip["job"]["id"] for clip in sequence["clips"]])
        self.assertEqual(intact["result"], sequence["clips"][1]["job"]["result"])
        self.assertEqual("pending", sequence["version"]["approval"])
        self.assertEqual(before + 1, len([r for r in media.requests if r.method == "POST"]))
        original_request = media.ai()["jobs"][bad["id"]]["request"]
        self.assertEqual(original_request["still"], media.ai()["jobs"][child["id"]]["request"]["still"])
        media.server_restart()
        self.assertEqual(200, media.http("/__ai", body)[0])
        other = media.ai()["versions"][intact["result"]]
        self.assertEqual(
            400,
            media.http(
                "/__ai",
                {**body, "job": intact["id"], "signature": version_signature(other), "requestId": "reset-via-other"},
            )[0],
        )

    def test_native_known_handle_retrieval_and_local_handoff_survive_publication_interruptions(self):
        media = self.media
        for point in ("accepted", "artifact", "committed"):
            with self.subTest(point=point):
                media.responses = [{"request_id": "resume-" + point}, *media.done()]
                with patch.dict(os.environ, {"GETBROLLS_AI_TEST_CRASH": point}):
                    status, raw = media.http("/__ai", media.video("interrupted-" + point))
                self.assertEqual(200, status, raw)
                job = json.loads(raw)["job"]
                self.assertEqual(
                    "remote_pending" if point == "accepted" else "downloading" if point == "artifact" else "complete",
                    job["state"],
                    job,
                )
                self.assertEqual("retrieve" if point != "committed" else None, job["recovery"]["action"])
                posts = len([r for r in media.requests if r.method == "POST"])
                media.server_restart()
                status, raw = media.http("/__ai", {"action": "resume", "job": job["id"]})
                self.assertEqual(200, status, raw)
                recovered = json.loads(raw)["job"]
                self.assertEqual("complete", recovered["state"], raw)
                self.assertEqual(0, recovered["correction_count"])
                self.assertEqual(posts, len([r for r in media.requests if r.method == "POST"]))
                version = media.ai()["versions"][recovered["result"]]
                self.assertEqual(media.clip_bytes, (media.project / "brolls" / version["path"]).read_bytes())

    def test_native_image_local_handoff_and_unknown_submit_never_use_correction_allowance(self):
        media = self.media
        media.responses = [{"data": [{"b64_json": base64.b64encode(media.image_bytes).decode()}]}]
        with patch.dict(os.environ, {"GETBROLLS_AI_TEST_CRASH": "artifact"}):
            status, raw = media.http("/__ai", {"action": "generate", "beat": "scarcity", "requestId": "local-handoff"})
        self.assertEqual(200, status, raw)
        job = json.loads(raw)["job"]
        self.assertEqual("downloading", job["state"])
        calls = len(media.requests)
        media.server_restart()
        status, raw = media.http("/__ai", {"action": "resume", "job": job["id"]})
        self.assertEqual(200, status, raw)
        self.assertEqual("complete", json.loads(raw)["job"]["state"])
        self.assertEqual(calls, len(media.requests))

    def test_refresh_reports_corrupt_committed_media_and_server_refuses_uncommitted_files(self):
        media = self.media
        path = media.project / "brolls" / media.still["path"]
        original = path.read_bytes()
        before = (media.project / "brolls/manifest.json").read_bytes()
        self.assertEqual(200, media.http("/" + media.still["path"])[0])
        rogue = path.parent / "ai-uncommitted.png"
        rogue.write_bytes(original)
        self.assertEqual(404, media.http("/previews/ai-uncommitted.png")[0])
        path.write_bytes(b"corrupted")
        self.assertEqual(404, media.http("/" + media.still["path"])[0])
        status, raw = media.http("/__ai/state")
        self.assertEqual(200, status, raw)
        job = next(job for job in json.loads(raw)["jobs"] if job["id"] == media.still["job"])
        self.assertEqual("output_invalid", job["recovery"]["reason"])
        self.assertEqual(400, media.http("/__ai", {"action": "resume", "job": job["id"]})[0])
        self.assertEqual(before, (media.project / "brolls/manifest.json").read_bytes())
        path.write_bytes(original)
        self.assertEqual(200, media.http("/" + media.still["path"])[0])

    def test_unknown_submit_is_not_a_download_failure_or_a_content_correction(self):
        media = self.media
        media.responses = [URLError("lost response")]
        status, raw = media.http("/__ai", {"action": "generate", "beat": "scarcity", "requestId": "unknown-image"})
        self.assertEqual(200, status, raw)
        unknown = json.loads(raw)["job"]
        self.assertEqual("unknown", unknown["state"])
        self.assertIsNone(unknown["recovery"]["action"])
        self.assertEqual("unknown_submit", unknown["recovery"]["reason"])
        calls = len(media.requests)
        self.assertEqual(200, media.http("/__ai", {"action": "resume", "job": unknown["id"]})[0])
        self.assertEqual(
            400,
            media.http(
                "/__ai",
                {
                    "action": "correct",
                    "job": unknown["id"],
                    "requestId": "not-a-fix",
                    "defect": "Download failed",
                    "instruction": "Try again",
                    "by": "Editor",
                },
            )[0],
        )
        self.assertEqual(calls, len(media.requests))

    def test_before_submit_and_failed_review_regeneration_preserve_one_authorized_job(self):
        media = self.media
        with patch.dict(os.environ, {"GETBROLLS_AI_TEST_CRASH": "before_submit"}):
            status, raw = media.http("/__ai", media.video("queued-before-submit"))
        self.assertEqual(200, status, raw)
        job = json.loads(raw)["job"]
        self.assertEqual("queued", job["state"])
        self.assertEqual("continue", job["recovery"]["action"])
        page = media.project / "brolls/review.html"
        saved_page = page.read_bytes()
        page.unlink()
        page.mkdir()
        try:
            media.call("review", ok=False)
        finally:
            page.rmdir()
            page.write_bytes(saved_page)
        media.server_restart()
        media.responses = [{"request_id": "initial-authorized-send"}, *media.done()]
        count = len([r for r in media.requests if r.method == "POST"])
        status, raw = media.http("/__ai", {"action": "resume", "job": job["id"]})
        self.assertEqual(200, status, raw)
        complete = json.loads(raw)["job"]
        self.assertEqual("complete", complete["state"])
        media.call("review")
        self.assertEqual(count + 1, len([r for r in media.requests if r.method == "POST"]))
        self.assertEqual(0, complete["correction_count"])

    def test_concurrent_recovery_reports_contention_and_refresh_does_not_take_worker_lock(self):
        from getbrolls import ai_grok

        media = self.media
        media.responses = [{"request_id": "only-one-retriever"}, *media.done()]
        with patch.dict(os.environ, {"GETBROLLS_AI_TEST_CRASH": "accepted"}):
            status, raw = media.http("/__ai", media.video("concurrent-recovery"))
        self.assertEqual(200, status, raw)
        job = json.loads(raw)["job"]
        entered, release = Event(), Event()

        def held_reply(request, **kwargs):
            if request.method == "GET" and "/videos/" in request.full_url:
                entered.set()
                if not release.wait(10):
                    raise TimeoutError("Synthetic retrieval was not released")
            return media.reply(request, **kwargs)

        ai_grok._opener.return_value.open.side_effect = held_reply
        body = {"action": "resume", "job": job["id"]}
        count = len([r for r in media.requests if r.method == "POST"])
        with ThreadPoolExecutor(max_workers=1) as pool:
            first = pool.submit(media.http, "/__ai", body)
            try:
                self.assertTrue(entered.wait(5))
                status, raw = media.http("/__ai", body)
                self.assertEqual(400, status, raw)
                self.assertIn(b"already running or being recovered", raw)
                self.assertEqual(200, media.http("/__ai/state")[0])
            finally:
                release.set()
            self.assertEqual(200, first.result()[0])
        self.assertEqual(count, len([r for r in media.requests if r.method == "POST"]))
        self.assertEqual("complete", media.ai()["jobs"][job["id"]]["state"])

    def test_known_rejection_is_distinct_from_unknown_submit_and_does_not_offer_generation_retry(self):
        media = self.media
        count = len(media.requests)
        media.responses = [
            HTTPError("https://api.x.ai/v1/images/generations", 429, "private quota", HTTPMessage(), None)
        ]
        status, raw = media.http("/__ai", {"action": "generate", "beat": "scarcity", "requestId": "rejected-image"})
        self.assertEqual(200, status, raw)
        job = json.loads(raw)["job"]
        self.assertEqual("rejected", job["submit_outcome"])
        self.assertEqual("rejected", job["recovery"]["reason"])
        self.assertIsNone(job["recovery"]["action"])
        self.assertEqual(200, media.http("/__ai", {"action": "resume", "job": job["id"]})[0])
        self.assertEqual(count + 1, len(media.requests))

    def test_processing_response_remains_known_pending_work_until_explicit_recovery(self):
        media = self.media
        media.responses = [{"request_id": "processing"}, {"status": "processing"}]
        status, raw = media.http("/__ai", media.video("still-processing"))
        self.assertEqual(200, status, raw)
        job = json.loads(raw)["job"]
        self.assertEqual("remote_pending", job["state"], raw)
        self.assertEqual("provider_processing", job["recovery"]["reason"])
        count = len(media.requests)
        media.responses = media.done()
        self.assertEqual(200, media.http("/__ai", {"action": "resume", "job": job["id"]})[0])
        self.assertEqual(["GET", "GET"], [r.get_method() for r in media.requests[count:]])

    def test_changed_local_download_recovers_exact_remote_result_without_overwriting_or_regenerating(self):
        media = self.media
        media.responses = [{"request_id": "same-result"}, *media.done()]
        with patch.dict(os.environ, {"GETBROLLS_AI_TEST_CRASH": "artifact"}):
            status, raw = media.http("/__ai", media.video("local-copy-damaged"))
        self.assertEqual(200, status, raw)
        job = json.loads(raw)["job"]
        saved = media.ai()["jobs"][job["id"]]["remote"]
        retained = media.project / "brolls/ai-work" / job["id"] / saved["artifact"]
        retained.write_bytes(b"damaged original retained for diagnosis")
        count = len(media.requests)
        media.responses = media.done()
        status, raw = media.http("/__ai", {"action": "resume", "job": job["id"]})
        self.assertEqual(200, status, raw)
        recovered = json.loads(raw)["job"]
        self.assertEqual("complete", recovered["state"], raw)
        self.assertEqual(b"damaged original retained for diagnosis", retained.read_bytes())
        self.assertEqual(["GET", "GET"], [request.method for request in media.requests[count:]])
        self.assertEqual(0, recovered["correction_count"])

    def test_partial_sequence_with_unknown_second_submit_keeps_intact_clip_without_automatic_regeneration(self):
        media = self.media
        plan = self.flow.prepare()
        media.responses = [
            {"request_id": "intact-first"},
            {"status": "done", "video": {"url": "https://media.example.com/first.mp4"}},
            self.flow.clip("red", 6),
            URLError("Lost second submit response"),
        ]
        status, raw = media.http(
            "/__ai", {"action": "launch-sequence", "sequence": plan["id"], "signature": plan["signature"]}
        )
        self.assertEqual(200, status, raw)
        original = json.loads(raw)["sequence"]
        self.assertEqual(["complete", "unknown"], [clip["job"]["state"] for clip in original["clips"]])
        count = len(media.requests)
        media.server_restart()
        media.call(
            "ai-select",
            "--beat",
            "scarcity",
            "--alternative",
            "option-2",
            "--comment",
            "Later unsent creative direction",
        )
        status, raw = media.http(
            "/__ai", {"action": "resume-sequence", "sequence": plan["id"], "signature": plan["signature"]}
        )
        self.assertEqual(200, status, raw)
        recovered = json.loads(raw)["sequence"]
        self.assertEqual("partial", recovered["state"])
        self.assertEqual(original["clips"][0]["job"]["result"], recovered["clips"][0]["job"]["result"])
        self.assertEqual("unknown_submit", recovered["clips"][1]["job"]["recovery"]["reason"])
        self.assertEqual(0, recovered["correction_count"])
        self.assertEqual(count, len(media.requests))

    def test_changed_approved_input_blocks_retrieval_and_read_only_refresh_reports_it_without_locking(self):
        from getbrolls.runtime import project_lock

        media = self.media
        media.responses = [{"request_id": "known-before-input-change"}, *media.done()]
        with patch.dict(os.environ, {"GETBROLLS_AI_TEST_CRASH": "accepted"}):
            status, raw = media.http("/__ai", media.video("changed-input"))
        self.assertEqual(200, status, raw)
        job = json.loads(raw)["job"]
        (media.project / "brolls" / media.still["path"]).write_bytes(b"changed first frame")
        manifest = media.project / "brolls/manifest.json"
        saved = manifest.read_bytes()
        count = len(media.requests)
        with project_lock(media.project):
            status, raw = media.http("/__ai/state")
        self.assertEqual(200, status, raw)
        reported = next(row for row in json.loads(raw)["jobs"] if row["id"] == job["id"])
        self.assertEqual("inputs_changed", reported["recovery"]["reason"])
        self.assertIsNone(reported["recovery"]["action"])
        self.assertEqual(400, media.http("/__ai", {"action": "resume", "job": job["id"]})[0])
        self.assertEqual(count, len(media.requests))
        self.assertEqual(saved, manifest.read_bytes())

    def test_corrected_sequence_keeps_previous_assembly_bytes_and_human_decision_in_history(self):
        media = self.media
        plan = self.flow.prepare()
        media.responses = [
            {"request_id": "first"},
            {"status": "done", "video": {"url": "https://media.example.com/first.mp4"}},
            self.flow.clip("red", 6),
            {"request_id": "second"},
            {"status": "done", "video": {"url": "https://media.example.com/second.mp4"}},
            self.flow.clip("blue", 2),
        ]
        status, raw = media.http(
            "/__ai", {"action": "launch-sequence", "sequence": plan["id"], "signature": plan["signature"]}
        )
        self.assertEqual(200, status, raw)
        original = json.loads(raw)["sequence"]
        version = original["version"]
        saved_path = media.project / "brolls" / version["path"]
        saved = saved_path.read_bytes()
        review = {
            "action": "review",
            "version": version["id"],
            "signature": version["signature"],
            "decision": "approved",
            "by": "Editor",
        }
        self.assertEqual(200, media.http("/__ai", review)[0])
        job = original["clips"][1]["job"]
        source = media.ai()["versions"][job["result"]]
        media.responses = [
            {"request_id": "fixed"},
            {"status": "done", "video": {"url": "https://media.example.com/fixed.mp4"}},
            self.flow.clip("green", 2),
        ]
        status, raw = media.http(
            "/__ai",
            {
                "action": "correct",
                "job": job["id"],
                "signature": version_signature(source),
                "defect": "A visible flicker in the second clip",
                "instruction": "Remove the flicker while preserving the scene",
                "by": "Editor",
                "requestId": "fix-reviewed-sequence",
            },
        )
        self.assertEqual(200, status, raw)
        current = json.loads(media.http("/__ai/state")[1])["beats"][0]["sequence"]
        self.assertNotEqual(version["id"], current["version"]["id"])
        self.assertEqual("pending", current["version"]["approval"])
        self.assertEqual([version["id"]], [row["id"] for row in current["history"]])
        self.assertEqual("approved", current["history"][0]["approval"])
        self.assertEqual(saved, saved_path.read_bytes())
        self.assertEqual(400, media.http("/__ai", review)[0], "An old decision cannot approve the corrected sequence")


@skip_unless_ffmpeg
class PaidRecoveryPublicTests(unittest.TestCase):
    clip = sequence_helpers.SequencePublicTests.clip

    def setUp(self):
        self.media = paid_helpers.OpenRouterPublicTests()
        self.addCleanup(self.media.doCleanups)
        self.media.setUp()

    def test_paid_processing_state_keeps_confirmation_and_recovers_with_get_only(self):
        media = self.media
        media.ready_video()
        media.responses = [paid_helpers.video_capabilities()]
        _body, jobs = media.prepare(kind="video", version=media.still["id"])
        media.responses = [{"id": "processing"}, {"status": "in_progress"}]
        job = media.confirm(jobs)[0]
        self.assertEqual("remote_pending", job["state"], job)
        self.assertEqual("provider_processing", job["recovery"]["reason"])
        count = len(media.requests)
        media.server_restart()
        media.responses = [
            {"status": "completed", "video": {"url": "https://media.example.com/processing.mp4"}},
            media.clip_bytes,
        ]
        status, raw = media.http("/__ai", {"action": "resume", "job": job["id"]})
        self.assertEqual(200, status, raw)
        self.assertEqual("complete", json.loads(raw)["job"]["state"])
        self.assertEqual(["GET", "GET"], [r.get_method() for r in media.requests[count:]])

    def test_paid_image_correction_waits_for_its_own_exact_confirmation_after_restart(self):
        media = self.media
        media.responses = [paid_helpers.image_capabilities()]
        _body, jobs = media.prepare()
        media.responses = [media.image_result()]
        parent = media.confirm(jobs)[0]
        original = media.ai()["versions"][parent["result"]]
        body = {
            "action": "correct",
            "job": parent["id"],
            "signature": version_signature(original),
            "requestId": "paid-image-correction",
            "defect": "Duplicated wall edge",
            "instruction": "Remove the duplicate",
            "by": "Editor",
        }
        count = len(media.requests)
        status, raw = media.http("/__ai", body)
        self.assertEqual(200, status, raw)
        child = json.loads(raw)["job"]
        self.assertEqual("awaiting_confirmation", child["state"])
        self.assertEqual(0.04, child["paid"]["estimate"]["usd"])
        self.assertEqual(count, len(media.requests))
        self.assertNotEqual(parent["paid"]["fingerprint"], child["paid"]["fingerprint"])
        self.assertEqual(
            400,
            media.http(
                "/__ai", {**media.confirmation([child]), "signatures": {child["id"]: parent["paid"]["fingerprint"]}}
            )[0],
        )
        media.server_restart()
        self.assertEqual(200, media.http("/__ai", {"action": "resume", "job": child["id"]})[0])
        media.confirm(jobs)
        self.assertEqual(count, len(media.requests), "Original consent and retrieval cannot launch a correction")
        media.responses = [media.image_result()]
        corrected = media.confirm([child])[0]
        self.assertEqual("complete", corrected["state"], corrected)
        self.assertEqual(count + 1, len(media.requests))
        media.confirm([child])
        self.assertEqual(count + 1, len(media.requests))
        self.assertEqual(400, media.http("/__ai", {**body, "requestId": "second-paid"})[0])

    def test_paid_comparison_shares_one_correction_and_api_image_handoff_needs_no_second_post(self):
        media = self.media
        self.assertEqual(200, media.http("/__ai", {"action": "select", "beat": "scarcity", "mode": "images"})[0])
        media.responses = [paid_helpers.image_capabilities()]
        _body, jobs = media.prepare(outputs=3)
        media.responses = [media.image_result(), media.image_result(), media.image_result()]
        parents = media.confirm(jobs)
        versions = media.ai()["versions"]
        parent = parents[0]
        body = {
            "action": "correct",
            "job": parent["id"],
            "signature": version_signature(versions[parent["result"]]),
            "requestId": "comparison-correction",
            "defect": "A duplicated edge",
            "instruction": "Remove the duplicate",
            "by": "Editor",
        }
        status, raw = media.http("/__ai", body)
        self.assertEqual(200, status, raw)
        child = json.loads(raw)["job"]
        media.responses = [media.image_result()]
        with patch.dict(os.environ, {"GETBROLLS_AI_TEST_CRASH": "artifact"}):
            result = media.confirm([child])[0]
        self.assertEqual("downloading", result["state"])
        count = len(media.requests)
        media.server_restart()
        status, raw = media.http("/__ai", {"action": "resume", "job": child["id"]})
        self.assertEqual(200, status, raw)
        self.assertEqual("complete", json.loads(raw)["job"]["state"])
        self.assertEqual(count, len(media.requests))
        other = parents[1]
        self.assertEqual(
            400,
            media.http(
                "/__ai",
                {
                    **body,
                    "job": other["id"],
                    "signature": version_signature(versions[other["result"]]),
                    "requestId": "comparison-reset",
                },
            )[0],
        )

    def test_paid_sequence_correction_confirms_only_new_clip_and_reuses_intact_original(self):
        media = self.media
        media.ready_video()
        media.call(
            "ai-timing-resolve",
            "--beat",
            "scarcity",
            "--analysis",
            "na-1",
            "--by",
            "Editor",
            "--statement",
            "Fixture interval",
            "--start",
            "0",
            "--end",
            "8",
        )
        media.responses = [paid_helpers.video_capabilities()]
        status, raw = media.http(
            "/__ai",
            {
                "action": "prepare-sequence",
                "route": "openrouter",
                "beat": "scarcity",
                "version": media.still["id"],
                "requestId": "paid-plan",
            },
        )
        self.assertEqual(200, status, raw)
        plan = json.loads(raw)["sequence"]
        jobs = [clip["job"] for clip in plan["clips"]]
        media.responses = [
            {"id": "original"},
            {"status": "completed", "video": {"url": "https://media.example.com/original.mp4"}},
            media.clip_bytes,
            {"id": "intact"},
            {"status": "completed", "video": {"url": "https://media.example.com/intact.mp4"}},
            self.clip("blue", 6),
        ]
        parent, intact = media.confirm(jobs)
        original = media.ai()["versions"][parent["result"]]
        count = len(media.requests)
        status, raw = media.http(
            "/__ai",
            {
                "action": "correct",
                "job": parent["id"],
                "signature": version_signature(original),
                "requestId": "paid-sequence-correction",
                "defect": "The returned video ends too early",
                "instruction": "Keep the frozen first frame and provide the full requested duration",
                "by": "Editor",
            },
        )
        self.assertEqual(200, status, raw)
        child = json.loads(raw)["job"]
        self.assertIsNone(child["paid"]["estimate"]["usd"])
        self.assertEqual(count, len(media.requests))
        media.server_restart()
        media.responses = [
            {"id": "corrected"},
            {"status": "completed", "video": {"url": "https://media.example.com/corrected.mp4"}},
            self.clip("red", 6),
        ]
        media.responses[-1] = URLError("Interrupted corrective download")
        failed = media.confirm([child])[0]
        self.assertIn(failed["state"], ("failed", "unknown"), failed)
        self.assertEqual("retrieve", failed["recovery"]["action"])
        posts = len([r for r in media.requests if r.get_method() == "POST"])
        media.server_restart()
        media.responses = [
            {"status": "completed", "video": {"url": "https://media.example.com/corrected.mp4"}},
            self.clip("green", 6),
        ]
        status, raw = media.http(
            "/__ai", {"action": "resume-sequence", "sequence": plan["id"], "signature": plan["signature"]}
        )
        self.assertEqual(200, status, raw)
        corrected = next(job for job in json.loads(media.http("/__ai/state")[1])["jobs"] if job["id"] == child["id"])
        self.assertEqual("complete", corrected["state"], corrected)
        self.assertEqual(original["still"], media.ai()["versions"][corrected["result"]]["still"])
        sequence = json.loads(media.http("/__ai/state")[1])["beats"][0]["sequence"]
        self.assertEqual("complete", sequence["state"], sequence)
        self.assertEqual(intact["result"], sequence["clips"][1]["job"]["result"])
        self.assertEqual("pending", sequence["version"]["approval"])
        self.assertEqual(count + 5, len(media.requests), "One POST and two retrieval attempts")
        self.assertEqual(posts, len([r for r in media.requests if r.get_method() == "POST"]))


if __name__ == "__main__":
    unittest.main()
