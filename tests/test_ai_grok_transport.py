"""Synthetic responses exercise the fixed OAuth media wire, without provider access."""

import base64
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
import _paths  # noqa: F401

from getbrolls import ai_grok


class GrokTransportTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.calls = []
        self.submitted = []
        self.credentials = ai_grok._credentials
        self.addCleanup(patch.stopall)
        patch.dict(os.environ, {}, clear=True).start()
        patch("getbrolls.ai_grok._credentials", return_value=("synthetic-oauth", "1.0.52")).start()
        self.open = patch("getbrolls.ai_grok._opener").start().return_value.open
        self.open.side_effect = self.reply
        self.responses = []

    def reply(self, request, **kwargs):
        self.calls.append(request)
        result = self.responses.pop(0)
        if isinstance(result, Exception):
            raise result
        return io.BytesIO(json.dumps(result).encode() if isinstance(result, dict) else result)

    def job(self, kind="image", **fields):
        return {
            "request": {
                "kind": kind,
                "route": "grok-subscription",
                "prompt": "A still, no lettering",
                "model": "grok-imagine-image-quality" if kind == "image" else "grok-imagine-video-1.5",
                "tool": "image_gen" if kind == "image" else "reference_to_video",
                "session_id": "00000000-0000-4000-8000-000000000001",
                **fields,
            }
        }

    def produce(self, job=None):
        return ai_grok.produce(self.root, job or self.job(), self.root, timeout=1, on_submitted=self.submitted.append)

    def test_one_image_post_retains_original_and_actual_route(self):
        original = b"\x89PNG\r\n\x1a\nsynthetic-image"
        self.responses = [{"data": [{"b64_json": base64.b64encode(original).decode()}]}]
        result = self.produce()
        self.assertEqual("complete", result["status"])
        self.assertEqual(original, Path(result["path"]).read_bytes())
        self.assertEqual(1, len(self.calls))
        request = self.calls[0]
        self.assertEqual("https://api.x.ai/v1/images/generations", request.full_url)
        self.assertEqual("Bearer synthetic-oauth", request.get_header("Authorization"))
        body = json.loads(request.data)
        self.assertEqual(1, body["n"])
        self.assertEqual("grok-imagine-image-quality", body["model"])
        self.assertEqual("b64_json", body["response_format"])
        self.assertEqual("oauth-imagine", result["remote"]["transport"])

    def test_lost_image_response_is_unknown_and_never_retried(self):
        self.responses = [URLError("private-url?token=secret")]
        result = self.produce()
        self.assertEqual("unknown", result["status"])
        self.assertEqual(1, len(self.calls))
        self.assertNotIn("private-url", str(result))
        self.assertNotIn("secret", str(result))

    def test_auth_quota_and_server_errors_do_not_retry_or_expose_body(self):
        for code, status in [(401, "auth"), (403, "auth"), (429, "quota"), (503, "unknown")]:
            with self.subTest(code=code):
                self.calls.clear()
                self.responses = [
                    HTTPError("https://api.x.ai", code, "private-secret", HTTPMessage(), io.BytesIO(b"secret"))
                ]
                result = self.produce()
                self.assertEqual(status, result["status"])
                self.assertEqual(1, len(self.calls))
                self.assertNotIn("secret", str(result))

    def test_missing_or_multiple_images_do_not_succeed(self):
        for body in [
            {},
            {"data": []},
            {"data": [{"url": "https://example.com/image"}]},
            {"data": [{"b64_json": "YQ=="}, {"b64_json": "Yg=="}]},
        ]:
            with self.subTest(body=body):
                self.responses = [body]
                self.assertNotEqual("complete", self.produce()["status"])
        self.assertEqual([], list(self.root.glob("*.png")))

    def test_static_key_and_unimplemented_model_are_refused_before_auth_or_network(self):
        with (
            patch.dict(os.environ, {"XAI_API_KEY": "private-static"}),
            patch("getbrolls.ai_grok._credentials", wraps=self.credentials),
        ):
            self.assertEqual("auth", self.produce()["status"])
        result = self.produce(self.job(model="invented-model"))
        self.assertEqual("unsupported", result["status"])
        self.assertEqual([], self.calls)

    def test_video_freezes_exact_bytes_and_download_never_carries_oauth(self):
        still = b"\x89PNG\r\n\x1a\nexact-approved-image"
        with patch("getbrolls.ai_grok._video_input", return_value=(still, "image/png")):
            self.responses = [
                {"request_id": "video-123"},
                {"status": "done", "video": {"url": "https://media.example.com/clip.mp4?sig=private"}},
                b"synthetic-mp4",
            ]
            result = self.produce(self.job("video", requested_duration_s=6, resolution="480p"))
        self.assertEqual("complete", result["status"])
        body = json.loads(self.calls[0].data)
        self.assertEqual(still, base64.b64decode(body["image"]["url"].split(",")[1]))
        self.assertNotIn("reference_images", body)
        self.assertEqual(6, body["duration"])
        self.assertEqual("video-123", self.submitted[0]["requestId"])
        self.assertIsNone(self.calls[-1].get_header("Authorization"))
        self.assertNotIn("private", str(result))
        self.assertEqual(b"synthetic-mp4", Path(result["path"]).read_bytes())

    def test_resume_polls_recorded_video_without_new_post(self):
        self.responses = [{"status": "done", "video": {"url": "https://media.example.com/clip.mp4"}}, b"mp4"]
        job = self.job("video")
        job["remote"] = {"requestId": "video-123", "transport": "oauth-imagine"}
        result = ai_grok.retrieve(job, self.root, timeout=1)
        self.assertEqual("complete", result["status"])
        self.assertTrue(all(request.get_method() == "GET" for request in self.calls))

    def test_private_or_non_https_download_targets_are_refused(self):
        for url in ["http://example.com/video", "https://user:pass@example.com/video", "https://127.0.0.1/video"]:
            with self.subTest(url=url):
                self.calls.clear()
                self.responses = [{"status": "done", "video": {"url": url}}]
                job = self.job("video")
                job["remote"] = {"requestId": "video-123", "transport": "oauth-imagine"}
                result = ai_grok.retrieve(job, self.root, timeout=1)
                self.assertNotEqual("complete", result["status"])
                self.assertEqual(1, len(self.calls))
