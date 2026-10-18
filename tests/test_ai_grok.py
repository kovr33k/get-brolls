"""Native Grok media stays unverified. These checks must not spawn a provider."""

import os
import unittest
from pathlib import Path
from unittest.mock import patch

import _isolation  # noqa: F401
import _paths  # noqa: F401

from getbrolls.ai_grok import produce


class GrokQuarantineTests(unittest.TestCase):
    def job(self, kind="image", tool="image_gen"):
        return {
            "request": {
                "kind": kind,
                "tool": tool,
                "model": "grok-imagine-image-quality",
                "session_id": "00000000-0000-4000-8000-000000000001",
                "prompt": "A still",
            }
        }

    def test_invented_account_metadata_and_static_keys_do_not_spawn(self):
        calls = []
        with (
            patch("subprocess.Popen", side_effect=AssertionError("spawned")),
            patch.dict(
                os.environ,
                {
                    "GETBROLLS_GROK_ACCOUNT": '{"model":"grok-imagine-image-quality","media":{"image_gen":true}}',
                    "GETBROLLS_GROK_BIN": "grok",
                },
                clear=True,
            ),
        ):
            outcome = produce(Path(), self.job(), Path(), timeout=1, on_submitted=calls.append)
            self.assertEqual("unsupported", outcome["status"])
            self.assertEqual("unverified", outcome["code"])
            self.assertIn("unverified", outcome["error"].lower())
        self.assertEqual([], calls)
        with (
            patch("subprocess.Popen", side_effect=AssertionError("spawned")),
            patch.dict(os.environ, {"XAI_API_KEY": "synthetic-xai", "GROK_API_KEY": "synthetic-grok"}, clear=True),
        ):
            refused = produce(Path(), self.job(), Path(), timeout=1, on_submitted=calls.append)
        self.assertEqual("auth", refused["status"])
        self.assertNotIn("synthetic-xai", refused["error"])
        self.assertNotIn("synthetic-grok", refused["error"])
        with (
            patch("subprocess.Popen", side_effect=AssertionError("spawned")),
            patch.dict(os.environ, {}, clear=True),
        ):
            missing = produce(Path(), {"request": {}}, Path(), timeout=1, on_submitted=calls.append)
            video = produce(
                Path(), self.job("video", "reference_to_video"), Path(), timeout=1, on_submitted=calls.append
            )
        self.assertEqual("unsupported", missing["status"])
        self.assertEqual("unverified", video["code"])
        self.assertEqual([], calls)
