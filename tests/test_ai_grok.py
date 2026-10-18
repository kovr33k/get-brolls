"""Caller-supplied account claims never grant OAuth media access."""

import json
import os
import tempfile
import unittest
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import patch

import _isolation  # noqa: F401
import _paths  # noqa: F401

from getbrolls.ai_grok import _credentials, produce


class GrokQuarantineTests(unittest.TestCase):
    def job(self, kind="image", tool="image_gen"):
        return {
            "request": {
                "kind": kind,
                "route": "grok-subscription",
                "tool": tool,
                "model": "grok-imagine-image-quality",
                "session_id": "00000000-0000-4000-8000-000000000001",
                "prompt": "A still",
            }
        }

    def test_invented_account_metadata_and_static_keys_do_not_spawn(self):
        calls = []
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        home = patch.object(Path, "home", return_value=Path(temp.name))
        home.start()
        self.addCleanup(home.stop)
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
            self.assertEqual("auth", outcome["status"])
            self.assertIn("OIDC", outcome["error"])
        self.assertEqual([], calls)

    def test_media_uses_only_oidc_even_when_other_reasoning_model_and_cached_keys_exist(self):
        with tempfile.TemporaryDirectory() as temp:
            home = Path(temp)
            private = home / ".grok"
            private.mkdir()
            account = {
                "oidc": {
                    "auth_mode": "oidc",
                    "oidc_issuer": "https://auth.x.ai",
                    "key": "synthetic-oauth",
                    "expires_at": (datetime.now(UTC) + timedelta(hours=1)).isoformat(),
                },
                "api": {"auth_mode": "api_key", "key": "synthetic-static"},
            }
            (private / "auth.json").write_text(json.dumps(account), encoding="utf-8")
            (private / "config.toml").write_text(
                'model = "another-reasoning-model"\n[models.custom]\napi_key = "synthetic-static"\n', encoding="utf-8"
            )
            with (
                patch.object(Path, "home", return_value=home),
                patch.dict(os.environ, {}, clear=True),
                patch("getbrolls.grok_oauth._client_version", return_value="1.0.52"),
                patch("getbrolls.grok_oauth._post", side_effect=AssertionError("unexpected network")),
            ):
                self.assertEqual(("synthetic-oauth", "1.0.52"), _credentials())

    def test_static_keys_and_unverified_video_pair_never_spawn(self):
        calls = []
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
        self.assertEqual("unsupported", video["code"])
        self.assertEqual([], calls)
