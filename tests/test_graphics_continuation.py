"""#60 public continuation, interrupted publication and retained repair allowance."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import _isolation  # noqa: F401
from _cli import run_cli
from _media import skip_unless_ffmpeg
from _paths import ROOT
from test_graphics_review import ENV, _assign, _project, _render, _review_payload, _version_hashes, _write_review
from test_narration import _env, _serving, _stop, _write_wav
from test_status import snapshot

from getbrolls.ledger import Ledger
from getbrolls.runtime import project_lock

FAULT = ROOT / "tests/fixtures/graphics_interruption.py"
FAIL = ROOT / "tests/fixtures/graphics_worker_fail.py"
INTERRUPTED = 91


def interrupted(project, fault):
    empty = Path(project) / "empty.env"
    empty.write_text("", encoding="utf-8")
    result = subprocess.run(
        [
            sys.executable,
            str(FAULT),
            fault,
            "--env-file",
            str(empty),
            "graphics-render",
            "--occurrence",
            "stat-01",
            "--project",
            str(project),
        ],
        env={**os.environ, **ENV},
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )
    if result.returncode != INTERRUPTED:
        raise AssertionError(result.stderr or result.stdout)


def continuation(project):
    return run_cli("graphics-continue", project=project, env=ENV)


@skip_unless_ffmpeg
class GraphicsContinuationTests(unittest.TestCase):
    def test_unknown_paid_operation_is_retained_without_submit_or_poll(self):
        with tempfile.TemporaryDirectory() as tmp:
            _project(tmp)
            _assign(tmp)
            server, thread = _serving(tmp, "disconnect")
            try:
                wav = _write_wav(Path(tmp) / "vo.wav")
                provider = _env(server)
                result = run_cli(
                    "narration-analyze", "--recording", str(wav), "--analysis", "na-unknown", project=tmp, env=provider
                )
                self.assertEqual("unknown", result["state"])
                original = Ledger(tmp, recover=False).data["narration"]
                posts, gets = server.state.posts, server.state.gets
                continued = run_cli("graphics-continue", project=tmp, env={**provider, **ENV})
                self.assertEqual("rendered", continued["items"][0]["action"])
                self.assertEqual(original, Ledger(tmp, recover=False).data["narration"])
                self.assertEqual((posts, gets), (server.state.posts, server.state.gets))
            finally:
                _stop(server, thread)

    def test_processed_request_identity_is_not_reprocessed_on_continuation(self):
        with tempfile.TemporaryDirectory() as tmp:
            _project(tmp)
            _assign(tmp)
            _render(tmp)
            payload = _review_payload(tmp)
            payload["graphics"][0].update(state="changes", comment="Synthetic revision request.")
            review_file = _write_review(tmp, payload)
            run_cli("import-review", "--file", str(review_file), "--by", "Synthetic reviewer", project=tmp)
            request_id = Ledger(tmp, recover=False).data["graphics"]["requests"][0]["id"]
            _assign(tmp, narration="A revised synthetic count.")
            continuation(tmp)
            run_cli(
                "graphics-request-complete",
                "--request",
                request_id,
                "--version",
                "v2",
                "--outcome",
                "Synthetic revision completed.",
                project=tmp,
            )
            saved = Ledger(tmp, recover=False).data["graphics"]["requests"]
            for _ in range(2):
                self.assertEqual("reused", continuation(tmp)["items"][0]["action"])
            self.assertEqual(saved, Ledger(tmp, recover=False).data["graphics"]["requests"])
            replay = run_cli("import-review", "--file", str(review_file), "--by", "Synthetic reviewer", project=tmp)
            self.assertEqual(0, replay["imported"])
            self.assertEqual("already_processed", replay["unchanged"][0]["reason"])

    def test_unchanged_result_is_reused_without_production_write(self):
        with tempfile.TemporaryDirectory() as tmp:
            _project(tmp)
            _assign(tmp)
            _render(tmp)
            root = Path(tmp) / "brolls"
            before = snapshot(root)
            before.pop("getbrolls.log", None)
            result = continuation(tmp)
            self.assertEqual("reused", result["items"][0]["action"])
            after = snapshot(root)
            after.pop("getbrolls.log", None)
            self.assertEqual(
                {},
                {
                    key: (before.get(key), after.get(key))
                    for key in before.keys() | after.keys()
                    if before.get(key) != after.get(key)
                },
            )
            self.assertEqual(0, result["paid_submissions"])

    def test_local_assignment_change_renders_only_its_dependent_and_preserves_history(self):
        with tempfile.TemporaryDirectory() as tmp:
            _project(tmp)
            _assign(tmp)
            _assign(tmp, occurrence="stat-02", scene="other")
            continuation(tmp)
            old = _version_hashes(tmp, "numeric-stat", "v1")
            _assign(tmp, narration="The count now stands at eighteen units.")
            result = continuation(tmp)
            self.assertEqual(["rendered", "reused"], [item["action"] for item in result["items"]])
            self.assertEqual(old, _version_hashes(tmp, "numeric-stat", "v1"))
            self.assertEqual(3, len(Ledger(tmp, recover=False).data["graphics"]["versions"]))

    def test_shared_style_invalidates_both_recorded_dependents(self):
        with tempfile.TemporaryDirectory() as tmp:
            _project(tmp)
            _assign(tmp)
            _assign(tmp, occurrence="stat-02", scene="other")
            continuation(tmp)
            run_cli("graphics-style", "--note", "Synthetic new shared requirement", project=tmp)
            result = continuation(tmp)
            self.assertEqual(["rendered", "rendered"], [item["action"] for item in result["items"]])
            versions = Ledger(tmp, recover=False).data["graphics"]["versions"]
            self.assertEqual([1, 1, 2, 2], [v["style"]["revision"] for v in versions.values()])
            self.assertTrue(all(v.get("approval") is None for v in versions.values()))

    def test_missing_artifact_is_not_a_cache_hit(self):
        with tempfile.TemporaryDirectory() as tmp:
            _project(tmp)
            _assign(tmp)
            first = _render(tmp)["version"]
            (Path(tmp) / "brolls" / first["artifact"]["path"]).unlink()
            result = continuation(tmp)["items"][0]
            self.assertEqual("rendered", result["action"])
            self.assertIn("missing_artifact", result["invalidated"])
            self.assertEqual("v2", result["version"])

    def test_waiting_question_and_actual_authoring_files_survive_continuation(self):
        with tempfile.TemporaryDirectory() as tmp:
            _project(tmp)
            _assign(tmp, question="Which dated source does the editor choose?")
            _assign(tmp, occurrence="stat-02", scene="other")
            root = Path(tmp) / "brolls"
            note = root / "graphics-data/draft.jsx"
            note.parent.mkdir()
            note.write_text("synthetic partial composition", encoding="utf-8")
            run_cli(
                "graphics-checkpoint",
                "--occurrence",
                "stat-01",
                "--stage",
                "authoring",
                "--outcome",
                "Draft retained; waiting on dated source",
                "--ref",
                "graphics-data/draft.jsx",
                project=tmp,
            )
            result = continuation(tmp)
            self.assertEqual(["waiting", "rendered"], [item["action"] for item in result["items"]])
            status = run_cli("status", project=tmp)["graphics"]["items"][0]
            self.assertTrue(status["work"]["checkpoints"][0]["intact"])
            note.write_text("changed partial source", encoding="utf-8")
            status = run_cli("status", project=tmp)["graphics"]["items"][0]
            self.assertFalse(status["work"]["checkpoints"][0]["intact"])
            self.assertEqual(
                "Which dated source does the editor choose?",
                Ledger(tmp, recover=False).data["graphics"]["occurrences"]["stat-01"]["questions"][0],
            )

    def test_changed_authoring_checkpoint_waits_until_actual_work_is_saved_again(self):
        with tempfile.TemporaryDirectory() as tmp:
            _project(tmp)
            _assign(tmp)
            note = Path(tmp) / "brolls/graphics-data/draft.txt"
            note.parent.mkdir()
            note.write_text("Saved authoring outcome.", encoding="utf-8")
            args = (
                "graphics-checkpoint",
                "--occurrence",
                "stat-01",
                "--stage",
                "authoring",
                "--outcome",
                "Saved composition notes.",
                "--ref",
                "graphics-data/draft.txt",
            )
            run_cli(*args, project=tmp)
            note.write_text("Interrupted changed authoring notes.", encoding="utf-8")
            result = continuation(tmp)["items"][0]
            self.assertEqual("waiting", result["action"])
            self.assertIn("changed_checkpoint_file:graphics-data/draft.txt", result["reasons"])
            self.assertEqual({}, Ledger(tmp, recover=False).data["graphics"]["versions"])
            run_cli(*args, project=tmp)
            self.assertEqual("rendered", continuation(tmp)["items"][0]["action"])

    def test_before_and_after_intent_do_not_promote_partial_work(self):
        for fault in ("before-staging", "after-staging", "after-frozen"):
            with self.subTest(fault=fault), tempfile.TemporaryDirectory() as tmp:
                _project(tmp)
                _assign(tmp)
                interrupted(tmp, fault)
                before = Ledger(tmp, recover=False).data["graphics"]
                self.assertFalse(any(v["status"] == "complete" for v in before["versions"].values()))
                result = continuation(tmp)["items"][0]
                if fault == "before-staging":
                    self.assertEqual("rendered", result["action"])
                else:
                    self.assertEqual("repair_required", result["action"])
                    self.assertTrue(
                        all(
                            v["status"] == "failed"
                            for v in Ledger(tmp, recover=False).data["graphics"]["versions"].values()
                        )
                    )

    def test_verified_and_partially_published_results_recover_same_version_without_worker(self):
        for fault in ("after-verified", "after-preview"):
            with self.subTest(fault=fault), tempfile.TemporaryDirectory() as tmp:
                _project(tmp)
                _assign(tmp)
                interrupted(tmp, fault)
                root = Path(tmp) / "brolls"
                executed = root / "graphics/numeric-stat/v1/staging/executed-worker.json"
                before = executed.stat().st_mtime_ns
                result = continuation(tmp)["items"][0]
                self.assertEqual("recovered", result["action"])
                self.assertEqual("v1", result["version"])
                self.assertEqual(before, executed.stat().st_mtime_ns)
                self.assertEqual("reused", continuation(tmp)["items"][0]["action"])
                self.assertEqual(1, len(Ledger(tmp, recover=False).data["graphics"]["versions"]))

    def test_corrupted_verified_staging_and_foreign_preview_are_preserved(self):
        for target in ("staging/out.mp4", "foreign-preview"):
            with self.subTest(target=target), tempfile.TemporaryDirectory() as tmp:
                _project(tmp)
                _assign(tmp)
                interrupted(tmp, "after-verified")
                root = Path(tmp) / "brolls"
                path = root / (
                    "previews/graphics-stat-01-v1.mp4"
                    if target == "foreign-preview"
                    else "graphics/numeric-stat/v1/" + target
                )
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(b"foreign bytes retained")
                result = continuation(tmp)["items"][0]
                self.assertEqual("error", result["action"])
                self.assertEqual(b"foreign bytes retained", path.read_bytes())
                self.assertEqual("staging", Ledger(tmp, recover=False).data["graphics"]["versions"]["v1"]["status"])

    def test_two_repairs_remain_consumed_after_continuation_and_reassignment(self):
        with tempfile.TemporaryDirectory() as tmp:
            _project(tmp)
            _assign(tmp)
            failed_env = {"GB_GRAPHICS_WORKER": str(FAIL)}
            run_cli("graphics-render", "--occurrence", "stat-01", project=tmp, env=failed_env, expect=2)
            for expected in (1, 2):
                run_cli("graphics-render", "--occurrence", "stat-01", "--repair", project=tmp, env=failed_env, expect=2)
                result = continuation(tmp)["items"][0]
                self.assertEqual("repair_required", result["action"])
                self.assertEqual(expected, result["repair_attempts"])
                _assign(tmp)
            result = run_cli("graphics-render", "--occurrence", "stat-01", "--repair", project=tmp, env=ENV, expect=2)
            self.assertIn("exhausted", json.dumps(result))
            self.assertEqual(3, len(Ledger(tmp, recover=False).data["graphics"]["versions"]))
            result = run_cli("graphics-render", "--occurrence", "stat-01", project=tmp, env=ENV, expect=2)
            self.assertIn("exhausted", json.dumps(result))

    def test_status_keeps_pending_transaction_and_invalid_history_intact(self):
        with tempfile.TemporaryDirectory() as tmp:
            _project(tmp)
            _assign(tmp)
            interrupted(tmp, "after-verified")
            root = Path(tmp) / "brolls"
            pending = root / ".pending-transaction.json"
            pending.write_text("{invalid retained journal", encoding="utf-8")
            before = snapshot(root)
            run_cli("status", project=tmp)
            # status diagnostics are explicitly outside production/history state.
            after = snapshot(root)
            self.assertEqual(before, after)
            run_cli("graphics-continue", project=tmp, env=ENV, expect=2)
            self.assertEqual("{invalid retained journal", pending.read_text(encoding="utf-8"))

    def test_durable_journal_recovery_preserves_prefix_and_deduplicates_events(self):
        for fault in ("after-journal", "after-manifest"):
            with self.subTest(fault=fault), tempfile.TemporaryDirectory() as tmp:
                _project(tmp)
                _assign(tmp)
                root = Path(tmp) / "brolls"
                events = root / "events.jsonl"
                prefix = events.read_bytes()
                interrupted(tmp, fault)
                pending = root / ".pending-transaction.json"
                self.assertTrue(pending.is_file())
                pending_bytes = pending.read_bytes()
                run_cli("status", project=tmp)
                self.assertEqual(pending_bytes, pending.read_bytes())
                self.assertEqual("repair_required", continuation(tmp)["items"][0]["action"])
                self.assertFalse(pending.exists())
                self.assertTrue(events.read_bytes().startswith(prefix))
                transactions = [json.loads(line)["transaction"] for line in events.read_text().splitlines()]
                self.assertEqual(len(transactions), len(set(transactions)))
                before = events.read_bytes()
                continuation(tmp)
                self.assertEqual(before, events.read_bytes())

    def test_conflicting_writer_refuses_before_render_and_status_still_reads(self):
        with tempfile.TemporaryDirectory() as tmp:
            _project(tmp)
            _assign(tmp)
            with project_lock(tmp):
                refused = run_cli("graphics-continue", project=tmp, env=ENV, expect=2)
                self.assertIn("Outro comando", json.dumps(refused))
                status = run_cli("status", project=tmp)
                self.assertEqual(0, status["graphics"]["complete_versions"])
            self.assertEqual({}, Ledger(tmp, recover=False).data["graphics"]["versions"])

    def test_invalid_retained_events_refuses_recovery_before_manifest_replacement(self):
        with tempfile.TemporaryDirectory() as tmp:
            _project(tmp)
            _assign(tmp)
            root = Path(tmp) / "brolls"
            original = (root / "manifest.json").read_bytes()
            events = root / "events.jsonl"
            events.write_text("not valid JSON retained", encoding="utf-8")
            interrupted(tmp, "after-journal")
            pending = root / ".pending-transaction.json"
            before_pending = pending.read_bytes()
            run_cli("graphics-continue", project=tmp, env=ENV, expect=2)
            self.assertEqual(original, (root / "manifest.json").read_bytes())
            self.assertEqual(before_pending, pending.read_bytes())
            self.assertEqual("not valid JSON retained", events.read_text(encoding="utf-8"))
