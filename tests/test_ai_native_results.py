"""Bounded native image frames, exact saved-history reconciliation and confined retention."""

import copy
import hashlib
import json
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import _isolation  # noqa: F401
import _paths  # noqa: F401
from _paths import ROOT

from getbrolls import ai, ai_provider


class NativeResultTests(unittest.TestCase):
    @unittest.skipUnless(shutil.which("node"), "Node.js required")
    def test_storyboard_identity_and_async_recovery(self):
        result = subprocess.run(
            ["node", str(ROOT / "tests/fixtures/storyboard_ai.cjs"), str(ROOT / "assets/review.js")],
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=20,
            check=False,
        )
        self.assertEqual(0, result.returncode, result.stderr + result.stdout)

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.workdir = self.root / "work"
        self.workdir.mkdir()
        self.native_home = self.root / "native-home"
        self.enterContext(patch.dict("os.environ", {"CODEX_HOME": str(self.native_home)}))
        self.original = self.native_home / "generated_images/thread-1/image-1.png"
        self.original.parent.mkdir(parents=True)
        self.original.write_bytes(b"\x89PNG\r\n\x1a\nsynthetic boundary bytes; full decoding covered by workflow tests")
        self.job = {
            "state": "unknown",
            "submit_outcome": "unknown",
            "request": {"route": "gpt-subscription", "kind": "image", "prompt": "Frozen prompt"},
            "remote": {
                "threadId": "thread-1",
                "phase": "generation",
                "prompt_sha256": hashlib.sha256(b"Frozen prompt").hexdigest(),
            },
        }
        self.thread = {
            "id": "thread-1",
            "turns": [
                {
                    "id": "turn-1",
                    "status": "interrupted",
                    "items": [
                        {"type": "userMessage", "content": [{"type": "text", "text": "Frozen prompt"}]},
                        {
                            "id": "image-1",
                            "type": "imageGeneration",
                            "status": "completed",
                            "savedPath": str(self.original),
                        },
                    ],
                }
            ],
        }

    def test_large_duplicate_image_payload_is_compacted_but_control_remains_bounded(self):
        item = {"type": "imageGeneration", "result": "A" * (ai_provider.MAX_LINE + 100), "savedPath": "saved.png"}
        raw = json.dumps({"method": "item/completed", "params": {"item": item}}).encode()
        parsed = ai_provider._decode_line(raw)
        self.assertEqual("", parsed["params"]["item"]["result"])
        self.assertEqual("saved.png", parsed["params"]["item"]["savedPath"])
        raw = json.dumps({"error": "A" * (ai_provider.MAX_LINE + 100)}).encode()
        with self.assertRaises(ValueError):
            ai_provider._decode_line(raw)
        item["unrelated"] = "A" * (ai_provider.MAX_LINE + 100)
        with self.assertRaises(ValueError):
            ai_provider._decode_line(json.dumps({"params": {"item": item}}).encode())

    def test_history_requires_exact_thread_turn_prompt_and_one_image(self):
        result = ai_provider._history_image(self.thread, self.job)
        self.assertEqual("complete", result["status"])
        remote = result["remote"]
        assert isinstance(remote, dict)
        self.assertEqual("image-1", remote["imageItemId"])
        malformed = []
        for field, value in (("id", "other-thread"), ("turns", True), ("turns", self.thread["turns"] * 2)):
            malformed.append({**copy.deepcopy(self.thread), field: value})
        for mutate in (
            lambda turn: turn.update(items=True),
            lambda turn: turn["items"][0].update(content=True),
            lambda turn: turn["items"][0]["content"][0].update(text="Different request"),
            lambda turn: turn["items"].append(copy.deepcopy(turn["items"][1])),
        ):
            thread = copy.deepcopy(self.thread)
            mutate(thread["turns"][0])
            malformed.append(thread)
        for thread in malformed:
            with self.subTest(thread=thread):
                self.assertEqual("unknown", ai_provider._history_image(thread, self.job)["status"])
        self.job["remote"]["turnId"] = "other-turn"
        self.assertEqual("unknown", ai_provider._history_image(self.thread, self.job)["status"])

    def test_inspection_or_unbound_reference_job_cannot_retrieve_a_production_image(self):
        self.assertTrue(ai_provider.retrievable(self.job))
        self.job["remote"]["phase"] = "inspection"
        self.assertFalse(ai_provider.retrievable(self.job))
        self.job["remote"] = {"threadId": "thread-1"}
        self.job["request"]["operation"] = "apply"
        self.assertFalse(ai_provider.retrievable(self.job))

    def test_recorded_local_original_never_falls_back_to_native_history(self):
        self.job["remote"].update(artifact="native.png", artifact_sha256="f" * 64)
        self.assertFalse(ai_provider.retrievable(self.job))

    def test_native_retention_preserves_original_and_refuses_wrong_location_or_foreign_copy(self):
        result = ai_provider._history_image(self.thread, self.job)
        original = self.original.read_bytes()
        retained = ai._native_still_original(self.job, self.workdir, result)
        self.assertEqual(original, retained.read_bytes())
        self.assertEqual(original, self.original.read_bytes())
        self.assertEqual(retained, ai._native_still_original(self.job, self.workdir, result))
        retained.write_bytes(b"foreign copy")
        with self.assertRaises(ValueError):
            ai._native_still_original(self.job, self.workdir, result)
        self.assertEqual(b"foreign copy", retained.read_bytes())
        with self.assertRaises(ValueError):
            ai._native_still_original(self.job, self.workdir, {**result, "path": str(self.root / "other.png")})
