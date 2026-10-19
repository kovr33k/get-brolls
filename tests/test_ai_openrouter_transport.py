"""Wire failures and credential boundaries; no provider access or generated test media."""

import io
import json
import os
import tempfile
import time
import unittest
from http.client import HTTPMessage
from pathlib import Path
from unittest.mock import patch
from urllib.error import HTTPError, URLError

import _isolation  # noqa: F401
import _paths  # noqa: F401

from getbrolls import ai_openrouter as provider
from getbrolls.ai_state import fingerprint
from getbrolls.runtime import redact


class OpenRouterTransportTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.calls, self.responses, self.saved = [], [], []
        self.addCleanup(patch.stopall)
        patch.dict(os.environ, {"OPENROUTER_API_KEY": "synthetic-private-key"}, clear=True).start()
        patch("getbrolls.ai_openrouter._opener").start().return_value.open.side_effect = self.reply

    def reply(self, request, **kwargs):
        self.calls.append(request)
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return io.BytesIO(json.dumps(response).encode() if isinstance(response, dict) else response)

    def job(self, kind="image"):
        request = {
            "route": "openrouter",
            "kind": kind,
            "model": "test/model",
            "resolution": "2K" if kind == "image" else "1080p",
            "prompt": "Frozen prompt",
            "paid": {
                "model": "test/model",
                "resolution": "2K" if kind == "image" else "1080p",
                "provider": "test-provider",
                "aspect_ratio": "16:9",
                "duration": 6,
                "audio": True,
            },
            "requested_duration_s": 6,
            "sound": {"speech": False, "music": False, "atmosphere": False, "effects": False},
        }
        return {"request": request, "confirmation": {"fingerprint": fingerprint(request)}}

    def produce(self, job=None):
        return provider.produce(self.root, job or self.job(), self.root, timeout=1, on_submitted=self.saved.append)

    def test_missing_or_changed_confirmation_and_key_make_no_request(self):
        job = self.job()
        job["confirmation"]["fingerprint"] = "0" * 64
        self.assertEqual("failed", self.produce(job)["status"])
        with patch.dict(os.environ, {}, clear=True):
            result = self.produce()
            self.assertEqual("auth", result["status"])
            self.assertIn("OPENROUTER_API_KEY", result["error"])
        self.assertFalse(self.calls)

    def test_http_rejection_uncertainty_and_redirects_never_retry_or_leak(self):
        for code, expected in [(401, "failed"), (402, "failed"), (429, "failed"), (503, "unknown"), (302, "failed")]:
            with self.subTest(code=code):
                headers = HTTPMessage()
                headers["Location"] = "https://hostile.example.com/steal?secret=private"
                self.responses = [
                    HTTPError(provider.API + "/images", code, "private message", headers, io.BytesIO(b"secret body"))
                ]
                before = len(self.calls)
                result = self.produce()
                self.assertEqual(expected, result["status"])
                if expected == "unknown":
                    self.assertIn("uncertain", result["error"])
                self.assertEqual(before + 1, len(self.calls))
                self.assertNotIn("private", str(result))
                self.assertNotIn("hostile", str(result))

    def test_timeout_and_malformed_success_without_handle_stay_unknown(self):
        for response in [URLError("private url"), {"status": "pending", "id": "../escape"}]:
            with self.subTest(response=type(response).__name__):
                self.responses = [response]
                with patch.object(provider, "_inputs", return_value=[]):
                    result = self.produce(self.job("video"))
                self.assertEqual("unknown", result["status"])
        self.assertFalse(self.saved)

    def test_authenticated_content_url_is_derived_from_recorded_handle(self):
        job = self.job("video")
        job["remote"] = {"transport": "openrouter-media", "requestId": "video-1"}
        self.responses = [
            {"status": "completed", "unsigned_urls": ["https://hostile.example.com/steal"]},
            b"synthetic clip",
        ]
        result = provider.retrieve(job, self.root, timeout=1)
        self.assertEqual("complete", result["status"])
        self.assertEqual(provider.API + "/videos/video-1/content?index=0", self.calls[-1].full_url)
        self.assertEqual("Bearer synthetic-private-key", self.calls[-1].get_header("Authorization"))
        self.assertEqual(b"synthetic clip", Path(result["path"]).read_bytes())
        self.assertTrue(all(call.get_method() == "GET" for call in self.calls))

    def test_content_redirect_is_not_followed_and_handle_is_retained(self):
        job = self.job("video")
        job["remote"] = {"transport": "openrouter-media", "requestId": "video-1"}
        headers = HTTPMessage()
        headers["Location"] = "https://hostile.example.com/"
        self.responses = [
            {"status": "completed"},
            HTTPError(provider.API + "/videos/video-1/content", 302, "private", headers, None),
        ]
        result = provider.retrieve(job, self.root, timeout=1)
        self.assertEqual("failed", result["status"])
        self.assertEqual("video-1", result["remote"]["requestId"])
        self.assertEqual(2, len(self.calls))
        self.assertNotIn("hostile", str(result))

    def test_download_refuses_http_and_bearer_forwarding_to_other_origins(self):
        for url, token in [
            ("http://media.example.com/video.mp4", None),
            ("https://hostile.example.com/video.mp4", "synthetic-private-key"),
        ]:
            with self.subTest(url=url), self.assertRaises(ValueError):
                provider._download(url, self.root, time.monotonic() + 1, token=token)
        self.assertFalse(self.calls)

    def test_model_auto_routing_and_credentials_are_not_setup_fields(self):
        for raw in [
            {"image": {"model": "openrouter/auto", "resolution": "2K", "key": "private"}},
            {"image": {"model": "auto", "resolution": "2K"}},
        ]:
            with self.subTest(raw=raw), self.assertRaises(ValueError):
                provider.setup(raw)
        self.assertNotIn("synthetic-private-key", redact("Error synthetic-private-key"))
