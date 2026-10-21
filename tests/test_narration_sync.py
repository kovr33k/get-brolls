"""Short complete recordings use synchronous STT without bypassing saved attempts."""

from __future__ import annotations

import json
import tempfile
import threading
import unittest
from pathlib import Path

import _isolation  # noqa: F401
from _cli import run_cli
from test_graphics_review import _assign
from test_narration import (
    FIXTURE_KEY,
    _assert_multipart_config_first,
    _env,
    _Handler,
    _project,
    _Server,
    _serving,
    _State,
    _stop,
    _write_wav,
)

from getbrolls.ledger import Ledger


class _SyncHandler(_Handler):
    def do_POST(self):  # noqa: N802
        state = self.server.state
        self._observe_post(state, self._read_request_body())
        if self.path != "/stt/v1/transcribe":
            self._send(402, {"error": "async upload requires a payment method"})
            return
        if state.mode == "disconnect":
            self.close_connection = True
            self.connection.close()
            return
        if state.mode == "reject":
            self._send(403, {"error": "rejected"})
            return
        if state.mode == "invalid":
            self._send(200, {"transcription": []})
            return
        stamps = [
            {"word": "Hello", "endTimeMs": 400, "confidence": 0},
            {"word": "world", "startTimeMs": 400, "endTimeMs": 800, "confidence": 0},
        ]
        if state.mode == "no-timing":
            stamps = []
        text = "Hello world"
        if state.mode == "matching":
            text = "The count stands at twelve units."
            stamps = [
                {"word": word, "startTimeMs": index * 300, "endTimeMs": index * 300 + 250}
                for index, word in enumerate(text.split())
            ]
        self._send(200, {"transcription": {"transcript": text, "isFinal": True, "wordTimestamps": stamps}})


def _serving_sync(project, mode="complete"):
    server = _Server(("127.0.0.1", 0), _SyncHandler, _State(Path(project), mode))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, thread


class NarrationSyncTests(unittest.TestCase):
    def test_sync_complete_multipart_and_local_reuse_in_both_modes(self):
        with tempfile.TemporaryDirectory() as tmp:
            _project(tmp)
            wav = _write_wav(Path(tmp) / "vo.wav")
            server, thread = _serving_sync(tmp)
            try:
                env = _env(server)
                done = run_cli("narration-analyze", "--sync", "--recording", wav, project=tmp, env=env)
                self.assertEqual("completed", done["state"])
                self.assertEqual("accepted", done["submit_outcome"])
                self.assertIsNone(done["operation_name"])
                self.assertEqual("Hello world", done["transcript"])
                self.assertTrue(done["timing_resolved"])
                self.assertEqual(0, done["timing"]["start_ms"])
                self.assertTrue(server.state.intent_before_post)
                self.assertEqual("Basic " + FIXTURE_KEY, server.state.auth[0])
                _assert_multipart_config_first(self, server)
                self.assertIn(wav.read_bytes(), server.state.posted_body)
                self.assertIn(b'"modelId":"inworld/inworld-stt-1"', server.state.posted_body)
                self.assertIn(b'"includeWordTimestamps":true', server.state.posted_body)
                self.assertEqual(str(len(server.state.posted_body)), server.state.posted_content_length)
                no_key = {**env, "INWORLD_API_KEY": ""}
                for flags in ((), ("--sync",)):
                    reused = run_cli("narration-analyze", *flags, "--recording", wav, project=tmp, env=no_key)
                    self.assertTrue(reused["reused"])
                    self.assertEqual(done["analysis_id"], reused["analysis_id"])
                resumed = run_cli("narration-resume", "--analysis", done["analysis_id"], project=tmp, env=no_key)
                self.assertTrue(resumed["reused"])
                result = Ledger(tmp, recover=False).data["narration"]["analyses"][done["analysis_id"]]["result"]
                self.assertNotIn("confidence", json.dumps(result))
                self.assertEqual((1, 0, 0), (server.state.posts, server.state.gets, server.state.downloads))
            finally:
                _stop(server, thread)

    def test_unknown_blocks_changed_transport_and_new_identity(self):
        for original_sync in (False, True):
            with self.subTest(sync=original_sync), tempfile.TemporaryDirectory() as tmp:
                _project(tmp)
                wav = _write_wav(Path(tmp) / "vo.wav")
                server, thread = (_serving_sync if original_sync else _serving)(tmp, "disconnect")
                try:
                    env = _env(server)
                    done = run_cli(
                        "narration-analyze",
                        *(("--sync",) if original_sync else ()),
                        "--recording",
                        wav,
                        project=tmp,
                        env=env,
                    )
                    self.assertEqual("unknown", done["state"])
                    blocked = run_cli(
                        "narration-analyze",
                        *(() if original_sync else ("--sync",)),
                        "--recording",
                        wav,
                        "--analysis",
                        "another",
                        project=tmp,
                        env=env,
                        expect=2,
                    )
                    self.assertIn("resubmit", blocked["error"])
                    self.assertEqual(1, server.state.posts)
                finally:
                    _stop(server, thread)

    def test_sync_failure_outcomes_do_not_retry(self):
        for mode, expected in (("disconnect", "unknown"), ("invalid", "unknown"), ("reject", "failed")):
            with self.subTest(mode=mode), tempfile.TemporaryDirectory() as tmp:
                _project(tmp)
                wav = _write_wav(Path(tmp) / "vo.wav")
                server, thread = _serving_sync(tmp, mode)
                try:
                    env = _env(server)
                    done = run_cli("narration-analyze", "--sync", "--recording", wav, project=tmp, env=env)
                    self.assertEqual(expected, done["state"])
                    resumed = run_cli("narration-resume", "--analysis", done["analysis_id"], project=tmp, env=env)
                    self.assertEqual(expected, resumed["state"])
                    self.assertEqual(1, server.state.posts)
                    self.assertEqual(0, server.state.gets)
                finally:
                    _stop(server, thread)

    def test_sync_retains_text_without_inventing_timing(self):
        with tempfile.TemporaryDirectory() as tmp:
            _project(tmp)
            wav = _write_wav(Path(tmp) / "vo.wav")
            server, thread = _serving_sync(tmp, "no-timing")
            try:
                done = run_cli("narration-analyze", "--sync", "--recording", wav, project=tmp, env=_env(server))
                self.assertEqual("completed", done["state"])
                self.assertEqual("Hello world", done["transcript"])
                self.assertFalse(done["timing_resolved"])
                self.assertEqual("TIMING_UNRESOLVED", done["error"]["code"])
            finally:
                _stop(server, thread)

    def test_sync_size_cap_before_intent_or_post(self):
        with tempfile.TemporaryDirectory() as tmp:
            _project(tmp)
            wav = _write_wav(Path(tmp) / "vo.wav", frames=8 * 1024 * 1024 // 2)
            server, thread = _serving_sync(tmp)
            try:
                failed = run_cli(
                    "narration-analyze", "--sync", "--recording", wav, project=tmp, env=_env(server), expect=2
                )
                self.assertIn("8 MiB", failed["error"])
                self.assertEqual(0, server.state.posts)
                self.assertFalse(Ledger(tmp, recover=False).data.get("narration", {}).get("analyses"))
            finally:
                _stop(server, thread)

    def test_durable_sync_receipt_recovers_without_key_or_network(self):
        with tempfile.TemporaryDirectory() as tmp:
            _project(tmp)
            wav = _write_wav(Path(tmp) / "vo.wav")
            server, thread = _serving_sync(tmp)
            try:
                env = _env(server, {"GETBROLLS_INWORLD_STT_TEST_CRASH": "after-sync-result"})
                run_cli(
                    "narration-analyze",
                    "--sync",
                    "--analysis",
                    "na-sync",
                    "--recording",
                    wav,
                    project=tmp,
                    env=env,
                    expect=2,
                )
                self.assertEqual("intent", Ledger(tmp, recover=False).data["narration"]["analyses"]["na-sync"]["state"])
                resumed = run_cli(
                    "narration-resume",
                    "--analysis",
                    "na-sync",
                    project=tmp,
                    env={**_env(server), "INWORLD_API_KEY": ""},
                )
                self.assertEqual("completed", resumed["state"])
                self.assertEqual("Hello world", resumed["transcript"])
                self.assertEqual((1, 0), (server.state.posts, server.state.gets))
            finally:
                _stop(server, thread)

    def test_sync_receipt_identity_and_artifact_corruption_preserve_history(self):
        for damage in ("identity", "artifact", "malformed"):
            with self.subTest(damage=damage), tempfile.TemporaryDirectory() as tmp:
                _project(tmp)
                wav = _write_wav(Path(tmp) / "vo.wav")
                server, thread = _serving_sync(tmp)
                try:
                    env = _env(server, {"GETBROLLS_INWORLD_STT_TEST_CRASH": "after-sync-result"})
                    run_cli(
                        "narration-analyze",
                        "--sync",
                        "--analysis",
                        "na-sync",
                        "--recording",
                        wav,
                        project=tmp,
                        env=env,
                        expect=2,
                    )
                    receipt = Path(tmp) / "brolls/narration/private/receipts/na-sync.json"
                    result = Path(tmp) / "brolls/narration/results/na-sync.json"
                    if damage == "identity":
                        data = json.loads(receipt.read_text(encoding="utf-8"))
                        data["input_fingerprint"] = "0" * 64
                        receipt.write_text(json.dumps(data), encoding="utf-8")
                    elif damage == "artifact":
                        result.write_text('{"transcript":"foreign"}', encoding="utf-8")
                    else:
                        receipt.write_text("[]", encoding="utf-8")
                    before = (receipt.read_bytes(), result.read_bytes())
                    failed = run_cli(
                        "narration-resume",
                        "--analysis",
                        "na-sync",
                        project=tmp,
                        env={**_env(server), "INWORLD_API_KEY": ""},
                        expect=2,
                    )
                    self.assertIn("artifact", failed["error"])
                    self.assertEqual(before, (receipt.read_bytes(), result.read_bytes()))
                    self.assertEqual(
                        "intent", Ledger(tmp, recover=False).data["narration"]["analyses"]["na-sync"]["state"]
                    )
                    self.assertEqual((1, 0), (server.state.posts, server.state.gets))
                finally:
                    _stop(server, thread)

    def test_sync_result_matches_scenario_without_retranscription(self):
        with tempfile.TemporaryDirectory() as tmp:
            _project(tmp)
            _assign(tmp, confirm_fps=30)
            wav = _write_wav(Path(tmp) / "vo.wav")
            server, thread = _serving_sync(tmp, "matching")
            try:
                done = run_cli(
                    "narration-analyze", "--sync", "--recording", wav, "--language", "en", project=tmp, env=_env(server)
                )
                self.assertIn(b'"language":"en"', server.state.posted_body)
                matched = run_cli(
                    "narration-match",
                    "--analysis",
                    done["analysis_id"],
                    "--occurrence",
                    "stat-01",
                    project=tmp,
                    env={**_env(server), "INWORLD_API_KEY": ""},
                )
                self.assertFalse(matched["retranscribed"])
                self.assertEqual("resolved", matched["matches"]["stat-01"]["state"])
                self.assertEqual((1, 0), (server.state.posts, server.state.gets))
            finally:
                _stop(server, thread)
