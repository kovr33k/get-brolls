"""Authenticated Storyboard paid launches → mocked HTTP → actual synthetic media."""

import base64
import hashlib
import io
import json
import os
import tempfile
import unittest
from http.client import HTTPMessage
from pathlib import Path
from unittest.mock import patch
from urllib.error import HTTPError, URLError

import _isolation  # noqa: F401
import test_ai_grok_public as grok_helpers
from _media import skip_unless_ffmpeg, synth_image, synth_video
from test_ai_timing_public import FIXTURE_TIMEOUT_S, SENTENCE, _words

from getbrolls.ai import handle_reference_upload, run_worker
from getbrolls.ai_state import version_signature
from getbrolls.ledger import Ledger


def image_capabilities():
    return {
        "id": "test/image",
        "endpoints": [
            {
                "provider_tag": "test-provider",
                "supported_parameters": {
                    "resolution": {"values": ["2K"]},
                    "aspect_ratio": {"values": ["16:9"]},
                    "input_references": {"max": 16},
                },
                "pricing": [{"billable": "output_image", "unit": "image", "cost_usd": 0.04}],
            }
        ],
    }


def video_capabilities():
    return {
        "data": [
            {
                "id": "test/video",
                "supported_resolutions": ["1080p"],
                "supported_durations": [6],
                "supported_aspect_ratios": ["16:9"],
                "supported_frame_images": ["first_frame"],
                "generate_audio": True,
                "pricing_skus": {"complex_tariff": "0.1"},
            }
        ]
    }


@skip_unless_ffmpeg
class OpenRouterPublicTests(unittest.TestCase):
    base: str
    token: str
    call = grok_helpers.GrokPublicTests.call
    ai = grok_helpers.GrokPublicTests.ai
    plant = grok_helpers.GrokPublicTests.plant
    start_server = grok_helpers.GrokPublicTests.start_server
    http = grok_helpers.GrokPublicTests.http
    reply = grok_helpers.GrokPublicTests.reply
    launch_native_still = grok_helpers.GrokPublicTests.launch_still
    server_restart = grok_helpers.GrokPublicTests.server_restart

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.project = Path(self.temp.name) / "project"
        self.env = {**os.environ, "GETBROLLS_AI_INLINE": "1", "GETBROLLS_AI_TIMEOUT": FIXTURE_TIMEOUT_S}
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
        patch.dict(os.environ, {"GETBROLLS_AI_INLINE": "1", "GETBROLLS_AI_TIMEOUT": FIXTURE_TIMEOUT_S}).start()
        patch("getbrolls.ai_grok._credentials", return_value=("synthetic-oauth", "1.0.52")).start()
        patch("getbrolls.ai_grok._opener").start().return_value.open.side_effect = self.reply
        self.start_server()
        patch.dict(os.environ, {"OPENROUTER_API_KEY": "synthetic-private-key"}).start()
        patch("getbrolls.ai_openrouter._opener").start().return_value.open.side_effect = self.reply
        ledger = Ledger(self.project)
        ledger.data["ai"]["openrouter"] = {
            "image": {"model": "test/image", "resolution": "2K"},
            "video": {"model": "test/video", "resolution": "1080p", "duration": 6},
        }
        ledger.save("test-paid-setup")

    def prepare(self, *, kind="image", nonce="paid-1", **values):
        body = {"action": "prepare-paid", "kind": kind, "beat": "scarcity", "requestId": nonce, **values}
        status, raw = self.http("/__ai", body)
        self.assertEqual(200, status, raw)
        return body, json.loads(raw)["jobs"]

    def confirmation(self, jobs):
        return {
            "action": "confirm-paid",
            "jobs": [j["id"] for j in jobs],
            "signatures": {j["id"]: j["paid"]["fingerprint"] for j in jobs},
            "by": "Test editor",
        }

    def confirm(self, jobs):
        status, raw = self.http("/__ai", self.confirmation(jobs))
        self.assertEqual(200, status, raw)
        return json.loads(raw)["jobs"]

    def image_result(self, data=None):
        return {"data": [{"b64_json": base64.b64encode(self.image_bytes if data is None else data).decode()}]}

    def ready_video(self):
        _body, job = self.launch_native_still()
        self.still = self.ai()["versions"][job["result"]]
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
        self.assertEqual(
            200,
            self.http(
                "/__ai", {"action": "timing", "beat": "scarcity", "analysis": "na-1", "version": self.still["id"]}
            )[0],
        )

    def test_one_image_requires_exact_confirmation_and_duplicate_is_same_job(self):
        self.responses = [image_capabilities()]
        body, jobs = self.prepare()
        self.assertEqual("awaiting_confirmation", jobs[0]["state"])
        self.assertEqual(0.04, jobs[0]["paid"]["estimate"]["usd"])
        self.assertEqual(1, len(self.requests))
        run_worker(self.project, jobs[0]["id"])
        self.assertEqual(1, len(self.requests))
        self.assertEqual(200, self.http("/__ai", body)[0])
        self.assertEqual(1, len(self.requests), "Duplicate preparation must not fetch capabilities or regenerate")
        self.responses = [self.image_result()]
        result = self.confirm(jobs)[0]
        self.assertEqual("complete", result["state"], result)
        version = self.ai()["versions"][result["result"]]
        self.assertEqual("pending", version["approval"]["state"])
        post = self.requests[-1]
        self.assertEqual("https://openrouter.ai/api/v1/images", post.full_url)
        payload = json.loads(post.data)
        self.assertEqual(1, payload["n"])
        self.assertEqual(["test-provider"], payload["provider"]["only"])
        self.assertFalse(payload["provider"]["allow_fallbacks"])
        count = len(self.requests)
        self.confirm(jobs)
        self.assertEqual(count, len(self.requests))

    def test_three_images_confirm_as_one_exact_scope_with_partial_failure(self):
        self.assertEqual(200, self.http("/__ai", {"action": "select", "beat": "scarcity", "mode": "images"})[0])
        self.responses = [image_capabilities()]
        _body, jobs = self.prepare(outputs=3)
        self.assertEqual(3, len(jobs))
        self.assertEqual(400, self.http("/__ai", self.confirmation(jobs[:1]))[0])
        self.assertTrue(all(j["state"] == "awaiting_confirmation" for j in self.ai()["jobs"].values()))
        self.responses = [self.image_result(), URLError("lost secret response"), self.image_result()]
        results = self.confirm(jobs)
        self.assertEqual(["complete", "unknown", "complete"], [j["state"] for j in results])
        self.assertEqual(3, sum(r.get_method() == "POST" for r in self.requests))
        count = len(self.requests)
        self.confirm(jobs)
        self.assertEqual(count, len(self.requests))
        self.assertEqual(2, len(self.ai()["versions"]))

    def test_changed_scope_and_fingerprint_cannot_reuse_consent(self):
        self.responses = [image_capabilities()]
        body, jobs = self.prepare(comment="first")
        self.assertEqual(400, self.http("/__ai", {**body, "comment": "changed"})[0])
        bad = self.confirmation(jobs)
        bad["signatures"][jobs[0]["id"]] = "0" * 64
        self.assertEqual(400, self.http("/__ai", bad)[0])
        self.assertEqual(1, len(self.requests))
        self.responses = [image_capabilities()]
        _body, later = self.prepare(nonce="later", comment="changed")
        self.assertNotEqual(jobs[0]["id"], later[0]["id"])
        self.assertEqual("awaiting_confirmation", later[0]["state"])

    def test_video_exact_first_frame_and_same_handle_recovery_without_bearer_download(self):
        self.ready_video()
        self.requests.clear()
        self.responses = [video_capabilities()]
        _body, jobs = self.prepare(kind="video", version=self.still["id"])
        self.assertIsNone(jobs[0]["paid"]["estimate"]["usd"])
        self.assertEqual("1080p", jobs[0]["paid"]["resolution"])
        self.responses = [
            {"id": "video-1", "status": "pending"},
            {"id": "video-1", "status": "completed", "urls": ["https://media.example.com/clip.mp4?sig=private"]},
            URLError("download interrupted"),
        ]
        result = self.confirm(jobs)[0]
        self.assertEqual("failed", result["state"], result)
        self.assertEqual("video-1", self.ai()["jobs"][jobs[0]["id"]]["remote"]["requestId"])
        post = next(r for r in self.requests if r.get_method() == "POST")
        body = json.loads(post.data)
        self.assertEqual("first_frame", body["frame_images"][0]["frame_type"])
        self.assertEqual(self.image_bytes, base64.b64decode(body["frame_images"][0]["image_url"]["url"].split(",")[1]))
        self.assertFalse(body["generate_audio"])
        self.assertIsNone(self.requests[-1].get_header("Authorization"))
        self.server_restart()
        self.responses = [
            {"id": "video-1", "status": "completed", "urls": ["https://media.example.com/clip.mp4?sig=private"]},
            self.clip_bytes,
        ]
        self.assertEqual(200, self.http("/__ai", {"action": "resume", "job": jobs[0]["id"]})[0])
        final = self.ai()["jobs"][jobs[0]["id"]]
        self.assertEqual("complete", final["state"], final)
        version = self.ai()["versions"][final["result"]]
        self.assertEqual("pending", version["approval"]["state"])
        self.assertFalse(version["native_full_hd"], "Requested 1080p cannot disguise smaller actual media")
        self.assertEqual(1, sum(r.get_method() == "POST" for r in self.requests))
        self.assertNotIn("sig=private", self.http("/__ai/state")[1].decode())

    def test_unknown_submit_and_invalid_media_never_resubmit(self):
        for suffix, response, state in [
            ("lost", URLError("secret"), "unknown"),
            ("bad", self.image_result(b"not an image"), "failed"),
        ]:
            with self.subTest(suffix=suffix):
                self.responses = [image_capabilities()]
                _body, jobs = self.prepare(nonce=suffix)
                self.responses = [response]
                self.assertEqual(state, self.confirm(jobs)[0]["state"])
                if suffix == "bad":
                    self.assertEqual("accepted", self.ai()["jobs"][jobs[0]["id"]]["submit_outcome"])
                count = len(self.requests)
                self.assertEqual(200, self.http("/__ai", {"action": "resume", "job": jobs[0]["id"]})[0])
                self.confirm(jobs)
                self.assertEqual(count, len(self.requests))

    def test_unsupported_capability_and_changed_recording_stop_before_post(self):
        cap = image_capabilities()
        cap["endpoints"][0]["supported_parameters"]["resolution"]["values"] = ["1K"]
        self.responses = [cap]
        self.assertEqual(
            400,
            self.http(
                "/__ai", {"action": "prepare-paid", "kind": "image", "beat": "scarcity", "requestId": "bad-profile"}
            )[0],
        )
        self.assertFalse(self.ai()["jobs"])
        self.ready_video()
        self.responses = [video_capabilities()]
        _body, jobs = self.prepare(kind="video", version=self.still["id"])
        self.plant(SENTENCE, _words(SENTENCE, 0, 2000), amplitude=1100)
        count = len(self.requests)
        self.assertEqual(400, self.http("/__ai", self.confirmation(jobs))[0])
        self.assertEqual(count, len(self.requests))
        self.assertEqual("awaiting_confirmation", self.ai()["jobs"][jobs[0]["id"]]["state"])

    def test_payment_failure_and_missing_price_are_explicit_without_fallback(self):
        cap = image_capabilities()
        cap["endpoints"][0]["pricing"] = []
        self.responses = [cap]
        _body, jobs = self.prepare()
        self.assertIsNone(jobs[0]["paid"]["estimate"]["usd"])
        self.responses = [HTTPError("https://openrouter.ai/api/v1/images", 402, "private body", HTTPMessage(), None)]
        result = self.confirm(jobs)[0]
        self.assertEqual("failed", result["state"])
        self.assertEqual("quota", self.ai()["jobs"][result["id"]]["error"]["code"])
        self.assertEqual("rejected", result["submit_outcome"])
        self.assertEqual("rejected", result["recovery"]["reason"])
        self.assertFalse(self.ai()["versions"])
        self.assertTrue(all(r.full_url.startswith("https://openrouter.ai/") for r in self.requests))

    def test_duplicate_ids_and_unauthenticated_confirmation_are_rejected(self):
        self.responses = [image_capabilities()]
        _body, jobs = self.prepare()
        body = self.confirmation(jobs)
        body["jobs"] *= 3
        self.assertEqual(400, self.http("/__ai", body)[0])
        status, _ = self.http("/__ai", self.confirmation(jobs), token=False)
        self.assertNotEqual(200, status)
        self.assertEqual(1, len(self.requests))

    def test_image_reference_sends_actual_frozen_pixels(self):
        self._check_reference(self.image_bytes, "ref.png", "image/png", None)

    def test_video_reference_sends_only_requested_interval_frames(self):
        self._check_reference(self.clip_bytes, "ref.mp4", "video/mp4", {"start_s": 0.2, "end_s": 0.8})

    def _check_reference(self, data, name, mime, interval):
        beat = self.ai()["beats"]["scarcity"]
        handle_reference_upload(
            self.project,
            io.BytesIO(data),
            len(data),
            {
                "beat": "scarcity",
                "fingerprint": beat["fingerprint"],
                "identity": "reference",
                "name": name,
                "declared_type": mime,
                "instructions": "Keep these pixels and interval",
                "role": "appearance",
                "scope": "beat",
                "interval": interval,
            },
        )
        self.responses = [image_capabilities()]
        _body, jobs = self.prepare(nonce="reference")
        self.responses = [self.image_result()]
        result = self.confirm(jobs)[0]
        self.assertEqual("complete", result["state"], result)
        body = json.loads(self.requests[-1].data)
        inputs = body["input_references"]
        refs = self.ai()["jobs"][jobs[0]["id"]]["request"]["references"]
        self.assertEqual(hashlib.sha256(data).hexdigest(), refs[0]["source_sha256"])
        if interval is None:
            sent = base64.b64decode(inputs[0]["image_url"]["url"].split(",")[1])
            self.assertIn(hashlib.sha256(sent).hexdigest(), refs[0]["derivative_sha256"])
        else:
            frames = [frame for ref in refs for frame in ref["frames"]]
            self.assertTrue(frames)
            self.assertEqual(len(frames), len(inputs))
            self.assertTrue(all(interval["start_s"] <= frame["time_s"] <= interval["end_s"] for frame in frames))
            for item, frame in zip(inputs, frames, strict=True):
                sent = base64.b64decode(item["image_url"]["url"].split(",")[1])
                self.assertEqual(frame["sha256"], hashlib.sha256(sent).hexdigest())

    def test_queued_paid_video_rechecks_revoked_still_approval_without_post(self):
        self.ready_video()
        self.responses = [video_capabilities()]
        _body, jobs = self.prepare(kind="video", version=self.still["id"])
        with patch("getbrolls.ai.start_worker"):
            self.confirm(jobs)
        ledger = Ledger(self.project)
        ledger.data["ai"]["versions"][self.still["id"]]["approval"] = {"state": "pending"}
        ledger.save("test-revoked-approval")
        count = len(self.requests)
        run_worker(self.project, jobs[0]["id"])
        self.assertEqual(count, len(self.requests))
        self.assertEqual("failed", self.ai()["jobs"][jobs[0]["id"]]["state"])
