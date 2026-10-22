"""A deliberate STT retry has its own exact consent and survives repeated commands."""

from __future__ import annotations

import copy
import tempfile
import unittest
from pathlib import Path

import _isolation  # noqa: F401
from _cli import run_cli
from test_narration import _env, _project, _serving, _stop, _write_wav
from test_narration_sync import _serving_sync, _SyncHandler

from getbrolls.ledger import Ledger


class NarrationRetryTests(unittest.TestCase):
    def _unknown(self, tmp, wav, env, *, sync=True):
        result = run_cli("narration-analyze", *(("--sync",) if sync else ()), "--recording", wav, project=tmp, env=env)
        self.assertEqual("unknown", result["state"])
        return result["analysis_id"]

    def _flags(self, wav, source, target="na-explicit-retry"):
        return ("--sync", "--recording", wav, "--retry-of", source, "--analysis", target)

    def _consent(self, proposal):
        return (
            "--confirm-retry",
            proposal["confirmation_fingerprint"],
            "--by",
            "Editor",
            "--statement",
            "Authorize one separate POST; the previous unknown request may also be charged.",
        )

    def test_prepare_confirm_reuse_preserves_unknown_and_limits_one_retry(self):
        with tempfile.TemporaryDirectory() as tmp:
            _project(tmp)
            wav = _write_wav(Path(tmp) / "vo.wav")
            server, thread = _serving(tmp, "disconnect")
            try:
                env = _env(server)
                source = self._unknown(tmp, wav, env, sync=False)
                old = copy.deepcopy(Ledger(tmp, recover=False).data["narration"]["analyses"][source])
                flags = self._flags(wav, source)
                proposal = run_cli("narration-analyze", *flags, project=tmp, env=env)
                self.assertEqual("awaiting_retry_confirmation", proposal["state"])
                self.assertEqual(0, proposal["provider_posts"])
                self.assertTrue(proposal["retry_scope"]["prior_attempt_may_have_been_charged"])
                self.assertEqual(1, server.state.posts)
                self.assertEqual({source}, set(Ledger(tmp, recover=False).data["narration"]["analyses"]))
                for consent in (
                    ("--confirm-retry", "0" * 64, "--by", "Editor", "--statement", "One POST"),
                    ("--confirm-retry", proposal["confirmation_fingerprint"]),
                ):
                    run_cli("narration-analyze", *flags, *consent, project=tmp, env=env, expect=2)
                run_cli(
                    "narration-analyze",
                    *flags,
                    *self._consent(proposal),
                    project=tmp,
                    env={**env, "INWORLD_API_KEY": ""},
                    expect=2,
                )
                self.assertEqual(1, server.state.posts)
                self.assertEqual({source}, set(Ledger(tmp, recover=False).data["narration"]["analyses"]))
                server.state.mode = "complete"
                server.RequestHandlerClass = _SyncHandler
                done = run_cli("narration-analyze", *flags, *self._consent(proposal), project=tmp, env=env)
                self.assertEqual("completed", done["state"])
                self.assertEqual(source, done["retry_of"])
                self.assertEqual("Hello world", done["transcript"])
                self.assertTrue(server.state.intent_before_post)
                self.assertIn(wav.read_bytes(), server.state.posted_body)
                no_key = {**env, "INWORLD_API_KEY": ""}
                repeated = run_cli("narration-analyze", *flags, *self._consent(proposal), project=tmp, env=no_key)
                self.assertTrue(repeated["reused"])
                status = run_cli("status", project=tmp, env=no_key)
                self.assertNotIn("Authorize one separate", str(status))
                analyses = Ledger(tmp, recover=False).data["narration"]["analyses"]
                self.assertEqual(old, analyses[source])
                self.assertEqual("Editor", analyses[done["analysis_id"]]["retry"]["by"])
                for original, target in ((source, "na-second-retry"), (done["analysis_id"], "na-chain")):
                    run_cli("narration-analyze", *self._flags(wav, original, target), project=tmp, env=env, expect=2)
                self.assertEqual((2, 0), (server.state.posts, server.state.gets))
            finally:
                _stop(server, thread)

    def test_interruption_consumes_retry_before_post_and_does_not_reset_on_resume(self):
        for crash, expected_posts, expected_state in (
            ("after-intent", 1, "unknown"),
            ("after-sync-result", 2, "completed"),
        ):
            with self.subTest(crash=crash), tempfile.TemporaryDirectory() as tmp:
                _project(tmp)
                wav = _write_wav(Path(tmp) / "vo.wav")
                server, thread = _serving_sync(tmp, "disconnect")
                try:
                    env = _env(server)
                    source = self._unknown(tmp, wav, env)
                    flags = self._flags(wav, source)
                    proposal = run_cli("narration-analyze", *flags, project=tmp, env=env)
                    server.state.mode = "complete"
                    run_cli(
                        "narration-analyze",
                        *flags,
                        *self._consent(proposal),
                        project=tmp,
                        env={**env, "GETBROLLS_INWORLD_STT_TEST_CRASH": crash},
                        expect=2,
                    )
                    resumed = run_cli("narration-analyze", *flags, project=tmp, env={**env, "INWORLD_API_KEY": ""})
                    self.assertEqual(expected_state, resumed["state"])
                    run_cli("narration-analyze", *self._flags(wav, source, "na-other"), project=tmp, env=env, expect=2)
                    self.assertEqual((expected_posts, 0), (server.state.posts, server.state.gets))
                    self.assertEqual(
                        "unknown", Ledger(tmp, recover=False).data["narration"]["analyses"][source]["state"]
                    )
                finally:
                    _stop(server, thread)

    def test_failed_retry_still_consumes_allowance_and_regular_analyze_cannot_bypass_it(self):
        for mode in ("disconnect", "reject", "invalid"):
            with self.subTest(mode=mode), tempfile.TemporaryDirectory() as tmp:
                _project(tmp)
                wav = _write_wav(Path(tmp) / "vo.wav")
                server, thread = _serving_sync(tmp, "disconnect")
                try:
                    env = _env(server)
                    source = self._unknown(tmp, wav, env)
                    flags = self._flags(wav, source)
                    proposal = run_cli("narration-analyze", *flags, project=tmp, env=env)
                    server.state.mode = mode
                    failed = run_cli("narration-analyze", *flags, *self._consent(proposal), project=tmp, env=env)
                    self.assertIn(failed["state"], ("failed", "unknown"))
                    run_cli("narration-analyze", *flags, *self._consent(proposal), project=tmp, env=env)
                    run_cli("narration-analyze", *self._flags(wav, source, "na-other"), project=tmp, env=env, expect=2)
                    run_cli(
                        "narration-analyze",
                        "--recording",
                        wav,
                        "--analysis",
                        "na-bypass",
                        project=tmp,
                        env=env,
                        expect=2,
                    )
                    self.assertEqual(2, server.state.posts)
                finally:
                    _stop(server, thread)

    def test_changed_bytes_language_transport_and_occupied_identity_refuse_before_post(self):
        with tempfile.TemporaryDirectory() as tmp:
            _project(tmp)
            wav = _write_wav(Path(tmp) / "vo.wav")
            other = _write_wav(Path(tmp) / "other.wav", byte=1)
            server, thread = _serving_sync(tmp, "disconnect")
            try:
                env = _env(server)
                source = self._unknown(tmp, wav, env)
                flags = self._flags(wav, source)
                proposal = run_cli("narration-analyze", *flags, project=tmp, env=env)
                for changed in (
                    self._flags(other, source),
                    (*flags, "--language", "es"),
                    tuple(x for x in flags if x != "--sync"),
                    self._flags(wav, source, source),
                ):
                    run_cli("narration-analyze", *changed, *self._consent(proposal), project=tmp, env=env, expect=2)
                run_cli(
                    "narration-analyze",
                    "--recording",
                    other,
                    "--confirm-retry",
                    proposal["confirmation_fingerprint"],
                    project=tmp,
                    env=env,
                    expect=2,
                )
                self.assertEqual(1, server.state.posts)
            finally:
                _stop(server, thread)

    def test_retained_receipt_and_changed_private_snapshot_block_new_paid_request(self):
        for damage in ("receipt", "snapshot"):
            with self.subTest(damage=damage), tempfile.TemporaryDirectory() as tmp:
                _project(tmp)
                wav = _write_wav(Path(tmp) / "vo.wav")
                server, thread = _serving_sync(tmp, "disconnect")
                try:
                    env = _env(server)
                    source = self._unknown(tmp, wav, env)
                    manifest = Ledger(tmp, recover=False).data["narration"]
                    if damage == "receipt":
                        path = Path(tmp) / "brolls/narration/private/receipts" / (source + ".json")
                        path.parent.mkdir(parents=True, exist_ok=True)
                        path.write_text("{}", encoding="utf-8")
                    else:
                        rec_id = manifest["analyses"][source]["recording_id"]
                        path = Path(tmp) / "brolls" / manifest["recordings"][rec_id]["snapshot"]
                        path.write_bytes(b"foreign")
                    before = path.read_bytes()
                    run_cli("narration-analyze", *self._flags(wav, source), project=tmp, env=env, expect=2)
                    self.assertEqual(before, path.read_bytes())
                    self.assertEqual(1, server.state.posts)
                finally:
                    _stop(server, thread)

    def test_known_handle_completed_and_rejected_attempts_do_not_use_unknown_retry(self):
        for mode in ("known-handle", "complete", "reject"):
            with self.subTest(mode=mode), tempfile.TemporaryDirectory() as tmp:
                _project(tmp)
                wav = _write_wav(Path(tmp) / "vo.wav")
                server, thread = _serving(tmp) if mode == "known-handle" else _serving_sync(tmp, mode)
                try:
                    env = _env(server)
                    result = run_cli(
                        "narration-analyze",
                        *(("--sync",) if mode != "known-handle" else ()),
                        "--recording",
                        wav,
                        project=tmp,
                        env=env,
                    )
                    run_cli(
                        "narration-analyze",
                        *self._flags(wav, result["analysis_id"]),
                        project=tmp,
                        env=env,
                        expect=2,
                    )
                    self.assertEqual((1, 0), (server.state.posts, server.state.gets))
                finally:
                    _stop(server, thread)
