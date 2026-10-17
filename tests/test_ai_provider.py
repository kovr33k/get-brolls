"""Native JSONL app-server adapter: handshake, account shape, submit uncertainty, stills."""

import json
import os
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

_TESTS = Path(__file__).resolve().parent
if str(_TESTS) not in sys.path:
    sys.path.insert(0, str(_TESTS))

import _isolation  # noqa: F401
import _paths  # noqa: F401

from getbrolls.ai_provider import MAX_LINE, generate_still

FIXTURE = Path(__file__).resolve().parent / "fixtures" / "ai_app_server.py"
PROMPT = "A still of an empty reservoir, no lettering."
STILL_ACTIVE = 259


def pid_alive(pid):
    if pid <= 0:
        return False
    if os.name == "nt":
        import ctypes

        handle = ctypes.windll.kernel32.OpenProcess(0x1000, False, pid)
        if not handle:
            return False
        code = ctypes.c_ulong()
        ok = ctypes.windll.kernel32.GetExitCodeProcess(handle, ctypes.byref(code))
        ctypes.windll.kernel32.CloseHandle(handle)
        return bool(ok) and code.value == STILL_ACTIVE
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


def as_dict(value):
    assert isinstance(value, dict)
    return value


def wait_dead(pid, timeout=5):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if not pid_alive(pid):
            return True
        time.sleep(0.05)
    return not pid_alive(pid)


class NativeProviderTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.workdir = Path(self.temp.name)
        self.env = patch.dict(
            os.environ,
            {
                "GETBROLLS_CODEX_APP_SERVER": str(FIXTURE),
                "GETBROLLS_AI_FIXTURE": "success",
                "OPENAI_API_KEY": "sk-test-must-not-be-inherited",
                "OPENROUTER_API_KEY": "or-test-must-not-be-inherited",
            },
            clear=False,
        )
        self.env.start()
        self.addCleanup(self.env.stop)

    def generate(self, mode="success", timeout=8, on_submitted=None):
        os.environ["GETBROLLS_AI_FIXTURE"] = mode
        return generate_still(PROMPT, self.workdir, timeout=timeout, on_submitted=on_submitted)

    def received(self):
        path = self.workdir / "received.jsonl"
        if not path.is_file():
            return []
        return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]

    def methods(self):
        return [row.get("method") for row in self.received() if row.get("method")]

    def test_success_returns_synthetic_png_path(self):
        submitted = []
        result = self.generate(on_submitted=submitted.append)
        self.assertEqual("complete", result["status"])
        path = Path(result["path"])
        self.assertTrue(path.is_file())
        self.assertEqual(b"\x89PNG", path.read_bytes()[:4])
        remote = as_dict(result["remote"])
        self.assertEqual("thr_getbrolls_test", remote["threadId"])
        self.assertEqual("turn_getbrolls_test", remote["turnId"])
        self.assertTrue(submitted)
        self.assertEqual("thr_getbrolls_test", submitted[0]["threadId"])
        child = json.loads((self.workdir / "child-env.json").read_text(encoding="utf-8"))
        self.assertFalse(child["OPENAI_API_KEY"])
        self.assertFalse(child["OPENROUTER_API_KEY"])

    def test_text_before_image_is_success(self):
        result = self.generate("text_then_image")
        self.assertEqual("complete", result["status"])
        self.assertTrue(Path(result["path"]).is_file())

    def test_terminal_text_only_is_failure(self):
        result = self.generate("text_only")
        self.assertEqual("failed", result["status"])
        self.assertEqual("text_only", result["code"])
        self.assertNotIn("path", result)

    def test_auth_when_account_missing(self):
        result = self.generate("auth")
        self.assertEqual("auth", result["status"])
        self.assertEqual("account", result["code"])

    def test_api_key_account_is_auth(self):
        result = self.generate("apikey")
        self.assertEqual("auth", result["status"])
        self.assertIn("API key", result["error"])

    def test_unsupported_without_image_capability(self):
        result = self.generate("unsupported")
        self.assertEqual("unsupported", result["status"])
        self.assertEqual("capabilities", result["code"])

    def test_quota_usage_limit(self):
        result = self.generate("quota")
        self.assertEqual("quota", result["status"])
        self.assertEqual("quota", result["code"])

    def test_missing_saved_file(self):
        result = self.generate("missing_file")
        self.assertEqual("failed", result["status"])
        self.assertEqual("missing_file", result["code"])

    def test_lost_turn_start_ack_is_unknown_without_retry(self):
        submitted = []
        result = self.generate("lost_ack", timeout=3, on_submitted=submitted.append)
        self.assertEqual("unknown", result["status"])
        self.assertEqual("unknown", result["code"])
        self.assertTrue(submitted)
        self.assertEqual("1", (self.workdir / "turn-start-count.txt").read_text(encoding="utf-8"))
        self.assertEqual(1, self.methods().count("turn/start"))

    def test_hung_transport_deadline_cleans_up_process(self):
        result = self.generate("hung", timeout=1)
        self.assertEqual("failed", result["status"])
        self.assertEqual("transport", result["code"])
        pid = int((self.workdir / "app-server.pid").read_text(encoding="utf-8"))
        self.assertTrue(wait_dead(pid))

    def test_malformed_transport_deadline_cleans_up_process(self):
        result = self.generate("malformed", timeout=2)
        self.assertEqual("failed", result["status"])
        pid = int((self.workdir / "app-server.pid").read_text(encoding="utf-8"))
        self.assertTrue(wait_dead(pid))

    def test_oversized_line_deadline_cleans_up_process(self):
        result = self.generate("oversized", timeout=2)
        self.assertEqual("failed", result["status"])
        pid = int((self.workdir / "app-server.pid").read_text(encoding="utf-8"))
        self.assertTrue(wait_dead(pid))

    def test_irrelevant_thread_turn_events_are_ignored(self):
        result = self.generate("irrelevant")
        self.assertEqual("complete", result["status"])
        self.assertTrue(Path(result["path"]).is_file())
        remote = as_dict(result["remote"])
        self.assertEqual("thr_getbrolls_test", remote["threadId"])

    def test_thread_binds_openai_and_disables_fallback(self):
        result = self.generate("success")
        self.assertEqual("complete", result["status"])
        start = next(row for row in self.received() if row.get("method") == "thread/start")
        params = start["params"]
        self.assertEqual("openai", params["modelProvider"])
        self.assertIs(False, params["allowProviderModelFallback"])
        self.assertEqual("never", params["approvalPolicy"])
        self.assertEqual("workspace-write", params["sandbox"])
        for row in self.received():
            self.assertNotIn("jsonrpc", row)
        methods = self.methods()
        self.assertEqual("initialize", methods[0])
        self.assertEqual("initialized", methods[1])
        self.assertEqual("account/read", methods[2])

    def test_fixture_rejects_lsp_framing(self):
        proc = subprocess.Popen(
            [sys.executable, str(FIXTURE)],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            cwd=str(self.workdir),
            env={**os.environ, "GETBROLLS_AI_FIXTURE": "success"},
        )
        raw = b'{"id":1,"method":"initialize"}\n'
        lsp = f"Content-Length: {len(raw)}\r\n\r\n".encode("ascii") + raw
        stdout, stderr = proc.communicate(lsp, timeout=5)
        self.assertNotEqual(0, proc.returncode)
        self.assertIn(b"Content-Length", stderr)
        self.assertFalse(stdout.strip())

    def test_fixture_rejects_request_before_initialized(self):
        proc = subprocess.Popen(
            [sys.executable, str(FIXTURE)],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            cwd=str(self.workdir),
            env={**os.environ, "GETBROLLS_AI_FIXTURE": "success"},
        )
        stdin = proc.stdin
        stdout = proc.stdout
        assert stdin is not None
        assert stdout is not None
        stdin.write(b'{"id":1,"method":"initialize","params":{"clientInfo":{"name":"t","version":"0"}}}\n')
        stdin.write(b'{"id":2,"method":"account/read","params":{}}\n')
        stdin.flush()
        line = stdout.readline()
        init = json.loads(line)
        self.assertIn("result", init)
        line = stdout.readline()
        note = json.loads(line)
        self.assertEqual("remoteControl/status/changed", note.get("method"))
        line = stdout.readline()
        denied = json.loads(line)
        self.assertEqual(2, denied["id"])
        self.assertEqual("Not initialized", denied["error"]["message"])
        proc.communicate(timeout=5)

    def test_oversized_bound_matches_provider(self):
        self.assertEqual(1_048_576, MAX_LINE)

    def test_early_image_before_turn_ack_is_complete(self):
        result = self.generate("early_image")
        self.assertEqual("complete", result["status"])
        path = Path(result["path"])
        self.assertTrue(path.is_file())
        self.assertEqual(b"\x89PNG", path.read_bytes()[:4])

    def test_turn_completed_usage_limit_is_quota(self):
        result = self.generate("turn_quota")
        self.assertEqual("quota", result["status"])
        self.assertEqual("quota", result["code"])
        self.assertNotIn("path", result)

    def test_turn_completed_unauthorized_is_auth(self):
        result = self.generate("turn_auth")
        self.assertEqual("auth", result["status"])
        self.assertEqual("auth", result["code"])
        self.assertNotIn("path", result)

    def test_turn_completed_interrupted_is_failed(self):
        result = self.generate("interrupted")
        self.assertEqual("failed", result["status"])
        self.assertEqual("interrupted", result["code"])
        self.assertNotIn("path", result)

    def test_blocked_write_after_thread_start_is_unknown(self):
        os.environ["GETBROLLS_AI_FIXTURE"] = "blocked_write"
        prompt = "é" * 32000
        submitted = []
        started = time.monotonic()
        result = generate_still(prompt, self.workdir, timeout=0.5, on_submitted=submitted.append)
        elapsed = time.monotonic() - started
        self.assertLess(elapsed, 2.5)
        self.assertEqual("unknown", result["status"])
        self.assertEqual("unknown", result["code"])
        self.assertTrue(submitted)
        self.assertLessEqual(self.methods().count("turn/start"), 1)
        pid = int((self.workdir / "app-server.pid").read_text(encoding="utf-8"))
        self.assertTrue(wait_dead(pid))
