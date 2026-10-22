"""Storyboard → real OAuth adapter wire → synthetic decoded media, review and resume."""

import base64
import hashlib
import io
import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from urllib.error import URLError

import _isolation  # noqa: F401
import test_ai_timing_public as timing_helpers
from _media import skip_unless_ffmpeg, synth_image, synth_video
from test_ai_timing_public import SENTENCE, _words

from getbrolls.ai import _probe_clip, handle_reference_upload, run_worker
from getbrolls.ai_grok import MAX_REFERENCE, _reference_bytes
from getbrolls.ai_state import version_signature
from getbrolls.ledger import Ledger


@skip_unless_ffmpeg
class GrokPublicTests(unittest.TestCase):
    base: str
    token: str

    call = timing_helpers.PublicTimingTests.call
    ai = timing_helpers.PublicTimingTests.ai
    plant = timing_helpers.PublicTimingTests.plant
    start_server = timing_helpers.PublicTimingTests.start_server
    http = timing_helpers.PublicTimingTests.http

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.project = Path(self.temp.name) / "project"
        self.env = {**os.environ, "GETBROLLS_AI_INLINE": "1", "GETBROLLS_AI_TIMEOUT": timing_helpers.FIXTURE_TIMEOUT_S}
        self.call("init-rules")
        plan = {
            "scenario": SENTENCE,
            "style": "Restrained illustration",
            "still_provider": {"route": "grok-subscription", "model": "grok-imagine-image-quality"},
            "native_video": {"model": "grok-imagine-video-1.5", "tool": "reference_to_video"},
            "beats": [
                {
                    "id": "scarcity",
                    "route": "ai",
                    "text": SENTENCE,
                    "purpose": "Explain scarcity",
                    "alternatives": ["Empty reservoir", "Final drop", "Dry spillway"],
                }
            ],
        }
        path = Path(self.temp.name) / "plan.json"
        path.write_text(json.dumps(plan), encoding="utf-8")
        self.call("ai-plan", "--file", path)
        self.call("ai-select", "--beat", "scarcity", "--alternative", "option-1")
        original = Path(self.temp.name) / "original.png"
        synth_image(original)
        self.image_bytes = original.read_bytes()
        clip = Path(self.temp.name) / "clip.mp4"
        synth_video(clip, duration=1)
        self.clip_bytes = clip.read_bytes()
        self.requests = []
        self.responses = []
        self.addCleanup(patch.stopall)
        patch.dict(
            os.environ, {"GETBROLLS_AI_INLINE": "1", "GETBROLLS_AI_TIMEOUT": timing_helpers.FIXTURE_TIMEOUT_S}
        ).start()
        patch("getbrolls.ai_grok._credentials", return_value=("synthetic-oauth", "1.0.52")).start()
        patch("getbrolls.ai_grok._opener").start().return_value.open.side_effect = self.reply
        self.start_server()

    def reply(self, request, **kwargs):
        self.requests.append(request)
        result = self.responses.pop(0)
        if isinstance(result, Exception):
            raise result
        return io.BytesIO(json.dumps(result).encode() if isinstance(result, dict) else result)

    def launch_still(self, nonce="native-still"):
        self.responses = [{"data": [{"b64_json": base64.b64encode(self.image_bytes).decode()}]}]
        body = {"action": "generate", "beat": "scarcity", "requestId": nonce}
        status, raw = self.http("/__ai", body)
        self.assertEqual(200, status, raw)
        job = json.loads(raw)["job"]
        self.assertEqual("complete", job["state"], raw)
        self.still = self.ai()["versions"][job["result"]]
        return body, job

    def approve_and_time(self):
        self.launch_still()
        status, raw = self.http(
            "/__ai",
            {
                "action": "review",
                "version": self.still["id"],
                "signature": version_signature(self.still),
                "by": "Test editor",
                "decision": "approved",
            },
        )
        self.assertEqual(200, status, raw)
        self.plant(SENTENCE, _words(SENTENCE, 0, 2000))
        self.call("ai-timing", "--beat", "scarcity", "--analysis", "na-1", "--still", self.still["id"])
        self.call(
            "ai-timing-resolve",
            "--beat",
            "scarcity",
            "--analysis",
            "na-1",
            "--by",
            "Test editor",
            "--statement",
            "Use this fixture span",
            "--start",
            "0",
            "--end",
            "8",
        )

    def video(self, nonce="native-video"):
        return {
            "action": "video",
            "beat": "scarcity",
            "version": self.still["id"],
            "requestId": nonce,
            "resolution": "480p",
            "speech": False,
            "music": False,
            "atmosphere": False,
            "effects": False,
        }

    def done(self):
        return [{"status": "done", "video": {"url": "https://media.example.com/clip.mp4?sig=private"}}, self.clip_bytes]

    def test_still_exact_video_duplicate_and_separate_review(self):
        self.approve_and_time()
        self.responses = [{"request_id": "vid-1"}, *self.done()]
        body = self.video()
        status, raw = self.http("/__ai", body)
        self.assertEqual(200, status, raw)
        job = json.loads(raw)["job"]
        self.assertEqual("complete", job["state"], raw)
        version = self.ai()["versions"][job["result"]]
        self.assertEqual("pending", version["approval"]["state"])
        self.assertEqual("approved", self.ai()["versions"][self.still["id"]]["approval"]["state"])
        self.assertFalse(version["native_full_hd"])
        self.assertEqual("short", version["coverage"])
        self.assertFalse(version["audio"])
        payload = json.loads(next(row.data for row in self.requests if row.full_url.endswith("/videos/generations")))
        self.assertEqual(self.image_bytes, base64.b64decode(payload["image"]["url"].split(",")[1]))
        count = len(self.requests)
        self.assertEqual(200, self.http("/__ai", body)[0])
        self.assertEqual(count, len(self.requests))
        self.assertEqual(
            200,
            self.http(
                "/__ai",
                {
                    "action": "review",
                    "version": version["id"],
                    "signature": version_signature(version),
                    "by": "Test editor",
                    "decision": "approved",
                },
            )[0],
        )
        self.assertEqual("approved", self.ai()["versions"][version["id"]]["approval"]["state"])
        self.assertTrue(json.loads(self.http("/__ai/state")[1])["beats"][0]["video"]["context_current"])
        self.plant(SENTENCE, _words(SENTENCE, 0, 2000), amplitude=1100)
        self.assertFalse(json.loads(self.http("/__ai/state")[1])["beats"][0]["video"]["context_current"])
        self.assertEqual(count, len(self.requests), "Read-only state must not retrieve or regenerate media")

    def test_known_handle_survives_restart_and_resume_only_gets_existing_video(self):
        self.approve_and_time()
        self.responses = [{"request_id": "vid-resume"}, URLError("lost polling response")]
        status, raw = self.http("/__ai", self.video())
        self.assertEqual(200, status, raw)
        job = json.loads(raw)["job"]
        self.assertEqual("unknown", job["state"])
        self.assertEqual("vid-resume", self.ai()["jobs"][job["id"]]["remote"]["requestId"])
        self.responses = self.done()
        # A freshly opened ledger and server are the same public resume path after restart.
        self.server_restart()
        status, raw = self.http("/__ai", {"action": "resume", "job": job["id"]})
        self.assertEqual(200, status, raw)
        self.assertEqual("complete", self.ai()["jobs"][job["id"]]["state"], self.ai()["jobs"][job["id"]])
        self.assertEqual(
            1, sum(row.get_method() == "POST" and row.full_url.endswith("/videos/generations") for row in self.requests)
        )

    def server_restart(self):
        self.start_server()

    def test_lost_still_response_and_missing_file_do_not_generate_again(self):
        self.responses = [URLError("lost submit response")]
        body = {"action": "generate", "beat": "scarcity", "requestId": "lost-image"}
        status, raw = self.http("/__ai", body)
        self.assertEqual(200, status, raw)
        job = json.loads(raw)["job"]
        self.assertEqual("unknown", job["state"])
        self.assertEqual(200, self.http("/__ai", body)[0])
        self.assertEqual(200, self.http("/__ai", {"action": "resume", "job": job["id"]})[0])
        self.assertEqual(1, len(self.requests))
        self.assertEqual({}, self.ai()["versions"])
        self.approve_and_time()
        (self.project / "brolls" / self.still["path"]).unlink()
        count = len(self.requests)
        self.assertEqual(400, self.http("/__ai", self.video())[0])
        self.assertEqual(count, len(self.requests))

    def test_corrupt_provider_bytes_are_not_reviewable_results(self):
        self.responses = [{"data": [{"b64_json": base64.b64encode(b"\x89PNG\r\n\x1a\nnot decodable").decode()}]}]
        status, raw = self.http("/__ai", {"action": "generate", "beat": "scarcity", "requestId": "bad-image"})
        self.assertEqual(200, status, raw)
        self.assertEqual("failed", json.loads(raw)["job"]["state"])
        self.assertEqual({}, self.ai()["versions"])

    def test_attached_cover_is_not_a_second_motion_video_stream(self):
        clip = Path(self.temp.name) / "clip.mp4"
        image = Path(self.temp.name) / "original.png"
        covered = Path(self.temp.name) / "with-cover.mp4"
        subprocess.run(
            [
                "ffmpeg",
                "-v",
                "error",
                "-i",
                str(clip),
                "-i",
                str(image),
                "-map",
                "0:v",
                "-map",
                "1:v",
                "-c",
                "copy",
                "-disposition:v:1",
                "attached_pic",
                str(covered),
            ],
            check=True,
            capture_output=True,
        )
        info = _probe_clip(covered)
        self.assertEqual((160, 90), (info["width"], info["height"]))

    def test_guided_still_and_exact_apply_transfer_pixels_without_gpt_or_fake_inspection(self):
        beat = self.ai()["beats"]["scarcity"]
        handle_reference_upload(
            self.project,
            io.BytesIO(self.image_bytes),
            len(self.image_bytes),
            {
                "beat": "scarcity",
                "fingerprint": beat["fingerprint"],
                "identity": "ref-1",
                "name": "reference.png",
                "declared_type": "image/png",
                "instructions": "Keep the red background",
                "role": "appearance",
                "scope": "beat",
            },
        )
        _body, job = self.launch_still()
        self.assertEqual("https://api.x.ai/v1/images/edits", self.requests[0].full_url)
        payload = json.loads(self.requests[0].data)
        self.assertTrue(payload["image"]["url"].startswith("data:image/png;base64,"))
        source = self.ai()["jobs"][job["id"]]["remote"]["imageInputs"][0]
        self.assertEqual(source["source_sha256"], source["sent_sha256"])
        self.assertNotIn("inspection", self.ai()["jobs"][job["id"]])
        self.responses = [{"data": [{"b64_json": base64.b64encode(self.image_bytes).decode()}]}]
        status, raw = self.http(
            "/__ai",
            {
                "action": "apply",
                "beat": "scarcity",
                "still": {"id": self.still["id"], "signature": version_signature(self.still)},
                "instruction": "Darken the sky",
                "requestId": "exact-revision",
            },
        )
        self.assertEqual(200, status, raw)
        applied = json.loads(raw)["job"]
        self.assertEqual("complete", applied["state"], raw)
        frozen = self.ai()["jobs"][applied["id"]]["request"]
        self.assertEqual(self.still["id"], frozen["target"]["id"])
        self.assertEqual("image_edit", frozen["tool"])
        self.assertEqual(2, len(self.ai()["versions"]))
        self.assertEqual(2, len(self.requests))

    def test_queued_video_rechecks_approval_before_the_only_post(self):
        self.approve_and_time()
        with patch("getbrolls.ai.start_worker"):
            status, raw = self.http("/__ai", self.video())
        self.assertEqual(200, status, raw)
        job = json.loads(raw)["job"]
        ledger = Ledger(self.project)
        ledger.data["ai"]["versions"][self.still["id"]]["approval"] = {"state": "pending"}
        ledger.save("test-revoked-approval")
        before = len(self.requests)
        run_worker(self.project, job["id"])
        self.assertEqual(before, len(self.requests))
        self.assertEqual("not_sent", self.ai()["jobs"][job["id"]]["submit_outcome"])
        self.assertEqual("failed", self.ai()["jobs"][job["id"]]["state"])

    def test_video_reference_transfers_only_the_requested_interval_images(self):
        start_s, end_s = 0.2, 0.8
        beat = self.ai()["beats"]["scarcity"]
        handle_reference_upload(
            self.project,
            io.BytesIO(self.clip_bytes),
            len(self.clip_bytes),
            {
                "beat": "scarcity",
                "fingerprint": beat["fingerprint"],
                "identity": "video-ref-1",
                "name": "reference.mp4",
                "declared_type": "video/mp4",
                "instructions": "Use only this motion interval",
                "role": "motion",
                "scope": "beat",
                "interval": {"start_s": start_s, "end_s": end_s},
            },
        )
        _body, job = self.launch_still()
        inputs = self.ai()["jobs"][job["id"]]["remote"]["imageInputs"]
        frames = [row["frame"] for row in inputs if row.get("frame")]
        self.assertTrue(frames)
        self.assertTrue(all(start_s <= row["time_s"] <= end_s for row in frames))
        payload = json.loads(self.requests[-1].data)
        self.assertEqual(len(inputs), len(payload["images"]))
        self.assertTrue(all(row["url"].startswith("data:image/") for row in payload["images"]))

    def test_same_interval_on_replaced_recording_does_not_authorize_queued_video(self):
        self.approve_and_time()
        with patch("getbrolls.ai.start_worker"):
            status, raw = self.http("/__ai", self.video())
        self.assertEqual(200, status, raw)
        job = json.loads(raw)["job"]
        self.plant(SENTENCE, _words(SENTENCE, 0, 2000), amplitude=1100)
        self.call("ai-timing", "--beat", "scarcity", "--analysis", "na-1", "--still", self.still["id"])
        self.call(
            "ai-timing-resolve",
            "--beat",
            "scarcity",
            "--analysis",
            "na-1",
            "--by",
            "Test editor",
            "--statement",
            "Same interval on a changed recording",
            "--start",
            "0",
            "--end",
            "8",
        )
        before = len(self.requests)
        self.responses = [{"request_id": "must-not-submit"}, *self.done()]
        run_worker(self.project, job["id"])
        self.assertEqual(before, len(self.requests))
        self.assertEqual("failed", self.ai()["jobs"][job["id"]]["state"])

    def test_large_reference_has_a_bounded_traceable_format_derivative(self):
        source = Path(self.temp.name) / "noise.png"
        subprocess.run(
            [
                "ffmpeg",
                "-v",
                "error",
                "-f",
                "lavfi",
                "-i",
                "nullsrc=s=1280x720,geq=random(1)*255:128:128",
                "-frames:v",
                "1",
                str(source),
            ],
            check=True,
            capture_output=True,
        )
        original = source.read_bytes()
        self.assertGreater(len(original), MAX_REFERENCE)
        data = _reference_bytes(
            {"path": str(source), "sha256": hashlib.sha256(original).hexdigest()}, Path(self.temp.name), 1
        )
        self.assertLessEqual(len(data), MAX_REFERENCE)
        self.assertTrue(data.startswith(b"\xff\xd8\xff"))
        self.assertEqual(original, source.read_bytes())
