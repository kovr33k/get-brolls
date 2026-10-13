"""#58: complete-VO Inworld asynchronous transcription through the public CLI."""

from __future__ import annotations

import hashlib
import http.server
import json
import os
import re
import stat
import subprocess
import sys
import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.request
import wave
from pathlib import Path
from unittest.mock import patch

import _isolation  # noqa: F401
from _cli import run_cli
from _paths import CLI

from getbrolls.cli import FORMAT_GATE_SUBCOMMANDS
from getbrolls.ledger import Ledger
from getbrolls.narration import PRODUCTION_API, TEST_BASE_ENV, TEST_MODE_ENV, api_base
from getbrolls.runtime import READ_ONLY_COMMANDS, project_lock

FIXTURE_KEY = "fixture-inworld-basic-token-SECRET99"
SIGNED = "https://storage.googleapis.com/bucket/x?X-Goog-Signature=stealme&X-Goog-Credential=stealcred"
MALICIOUS_ERROR = (
    f"fail {SIGNED} Authorization: Basic {FIXTURE_KEY} INWORLD_API_KEY={FIXTURE_KEY} </script><img onerror=alert(1)>"
)
OPERATION = "workspaces/ws/sttTranscriptionJobs/job/operations/op-1"
TRANSCRIPT = 'Hello </script> & "quoted" world'
SECRETS = (FIXTURE_KEY, "stealme", "stealcred", SIGNED, "Authorization: Basic")
VALID_SAMPLE_RATE = 8000
VALID_DURATION_S = 3
VALID_FRAME_COUNT = VALID_SAMPLE_RATE * VALID_DURATION_S
PCM_WAV_HEADER_BYTES = 44
TRUNCATED_KEEP_FRAMES = 80
OUTSIDE_WORD_END_MS = 4000
NONMONOTONIC_FIRST_END_MS = 800
NONMONOTONIC_SECOND_START_MS = 100
NONMONOTONIC_SECOND_END_MS = 200
BACKWARDS_START_FIRST_START_MS = 500
BACKWARDS_START_FIRST_END_MS = 800
BACKWARDS_START_SECOND_START_MS = 100
BACKWARDS_START_SECOND_END_MS = 900
MAX_FIXTURE_BODY = 1024 * 1024
CHUNK_CRLF = b"\r\n"
OUTSIDE_SENTINEL_NAME = "keep-me.bin"
OUTSIDE_SENTINEL = b"OUTSIDE-SENTINEL"
FOREIGN_AUDIO = b"FOREIGN-NARRATION-AUDIO"
FOREIGN_RESULT = b"FOREIGN-NARRATION-RESULT"
FOREIGN_RECEIPT = b"FOREIGN-NARRATION-RECEIPT"
FOREIGN_TEMP = b"FOREIGN-NARRATION-TEMP"
TAMPERED_RESULT = b'{"tampered": true}'
_SKIP_STATUS_NAMES = frozenset({".command.lock", "diagnostics.jsonl", "getbrolls.log"})
_DONE_RESULT_MODES = frozenset(
    {
        "complete_after_poll",
        "invalid_times",
        "redirect_result",
        "private_result",
        "metadata_leak",
        "outside_timing",
        "nonmonotonic",
        "backwards_start",
    }
)
_STORAGE_RELS = (
    "narration/private/audio",
    "narration/results",
    "narration/private/receipts",
)
_FOREIGN_FILE_KINDS = ("audio", "result", "receipt")
_FOREIGN_TMP_KINDS = ("audio-tmp", "result-tmp", "receipt-tmp")


def _write_wav(path: Path, frames: int = VALID_FRAME_COUNT, rate: int = VALID_SAMPLE_RATE, byte: int = 0) -> Path:
    path = Path(path)
    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(rate)
        handle.writeframes(bytes((byte, 0)) * frames)
    return path


def _header_only_wav(path: Path) -> Path:
    full = _write_wav(path)
    full.write_bytes(full.read_bytes()[:PCM_WAV_HEADER_BYTES])
    return full


def _truncated_payload_wav(path: Path) -> Path:
    full = _write_wav(path)
    keep = PCM_WAV_HEADER_BYTES + (TRUNCATED_KEEP_FRAMES * 2)
    full.write_bytes(full.read_bytes()[:keep])
    return full


def _project(tmp: str | Path) -> Path:
    run_cli("init-rules", project=tmp)
    return Path(tmp)


def _review_payload(page: str) -> dict[str, object]:
    match = re.search(r"window.GETBROLLS_REVIEW=(.*?);</script>", page)
    if match is None:
        raise AssertionError("GETBROLLS_REVIEW payload is missing")
    payload = json.loads(match.group(1))
    if not isinstance(payload, dict):
        raise AssertionError("GETBROLLS_REVIEW payload is not an object")
    return payload


def _review_transcript(page: str) -> str:
    records = _review_payload(page).get("narration")
    if not isinstance(records, list) or not records or not isinstance(records[0], dict):
        raise AssertionError("review narration records are missing")
    transcript = records[0].get("transcript")
    if not isinstance(transcript, str):
        raise AssertionError("review narration transcript is missing")
    return transcript


def _recording_id(path: Path) -> str:
    return "rec-" + hashlib.sha256(path.read_bytes()).hexdigest()[:16]


def _is_link(path: Path) -> bool:
    if path.is_symlink():
        return True
    try:
        info = path.lstat()
    except OSError:
        return False
    attributes = getattr(info, "st_file_attributes", 0)
    reparse = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
    return bool(attributes & reparse)


def _confined(path: Path, root: Path) -> bool:
    resolved = path.resolve()
    base = root.resolve()
    return resolved == base or base in resolved.parents


def _make_dir_link(link: Path, target: Path) -> bool:
    link = Path(link)
    target = Path(target)
    target.mkdir(parents=True, exist_ok=True)
    link.parent.mkdir(parents=True, exist_ok=True)
    if link.exists() or link.is_symlink():
        return False
    try:
        link.symlink_to(target, target_is_directory=True)
        return True
    except OSError:
        if os.name != "nt":
            return False
        done = subprocess.run(
            ["cmd", "/c", "mklink", "/J", str(link), str(target)],
            capture_output=True,
            text=True,
            encoding="utf-8",
            check=False,
        )
        return done.returncode == 0 and (link.exists() or _is_link(link))


def _remove_owned_link(link: Path) -> None:
    """Remove only the link node; never walk or rmtree through a junction."""
    if not (link.exists() or link.is_symlink() or _is_link(link)):
        return
    if link.is_symlink():
        link.unlink()
        return
    link.rmdir()


def _make_file_link(link: Path, target: Path) -> bool:
    link = Path(link)
    target = Path(target)
    link.parent.mkdir(parents=True, exist_ok=True)
    if link.exists() or link.is_symlink():
        return False
    try:
        link.symlink_to(target)
        return True
    except OSError:
        if os.name != "nt":
            return False
        done = subprocess.run(
            ["cmd", "/c", "mklink", str(link), str(target)],
            capture_output=True,
            text=True,
            encoding="utf-8",
            check=False,
        )
        return done.returncode == 0 and (link.exists() or link.is_symlink() or _is_link(link))


def _file_hashes(root: Path) -> dict[str, str]:
    hashes: dict[str, str] = {}
    for path in root.rglob("*"):
        if not path.is_file() or path.name in _SKIP_STATUS_NAMES or _is_link(path):
            continue
        hashes[path.relative_to(root).as_posix()] = hashlib.sha256(path.read_bytes()).hexdigest()
    return hashes


def _analyze_complete(
    tmp: str | Path, wav: Path, env: dict[str, str], analysis_id: str
) -> tuple[dict[str, object], dict[str, object]]:
    submitted = run_cli(
        "narration-analyze",
        "--recording",
        str(wav),
        "--analysis",
        analysis_id,
        project=tmp,
        env=env,
    )
    last = submitted
    if last.get("state") != "completed":
        last = run_cli("narration-resume", "--analysis", analysis_id, project=tmp, env=env)
    if last.get("state") != "completed":
        last = run_cli("narration-resume", "--analysis", analysis_id, project=tmp, env=env)
    if not isinstance(submitted, dict) or not isinstance(last, dict):
        raise AssertionError("CLI did not return a JSON object")
    return submitted, last


class _State:
    def __init__(self, project: Path, mode: str = "complete_after_poll") -> None:
        self.project = Path(project)
        self.mode = mode
        self.posts = 0
        self.gets = 0
        self.downloads = 0
        self.redirects = 0
        self.auth_on_download = False
        self.config_before_file = False
        self.intent_before_post = False
        self.posted_json = False
        self.posted_body = b""
        self.posted_body_bytes = 0
        self.auth: list[str | None] = []
        self.paths: list[tuple[str, str, str | None]] = []


class _Server(http.server.ThreadingHTTPServer):
    state: _State

    def __init__(
        self,
        server_address: tuple[str, int],
        request_handler: type[http.server.BaseHTTPRequestHandler],
        state: _State,
    ) -> None:
        self.state = state
        super().__init__(server_address, request_handler)

    @property
    def port(self) -> int:
        address = self.server_address
        if not isinstance(address, tuple):
            raise TypeError("fixture HTTP server must bind an inet address")
        try:
            _host, bound_port, *_extra = address
        except ValueError as exc:
            raise TypeError("fixture HTTP server must bind an inet address") from exc
        if not isinstance(bound_port, int):
            raise TypeError("fixture HTTP server must bind an inet address")
        return bound_port


class _Handler(http.server.BaseHTTPRequestHandler):
    server: _Server
    protocol_version = "HTTP/1.1"

    def log_message(self, format: str, *args: object) -> None:  # noqa: A002
        return

    def _send(self, status: int, payload: object, headers: dict[str, str] | None = None) -> None:
        body = payload if isinstance(payload, bytes) else json.dumps(payload).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        for key, value in (headers or {}).items():
            self.send_header(key, value)
        self.end_headers()
        self.wfile.write(body)

    def _result_uri(self) -> str:
        return f"http://127.0.0.1:{self.server.port}/results/op-1.json"

    def _read_chunked_body(self) -> bytes:
        parts: list[bytes] = []
        total = 0
        while True:
            line = self.rfile.readline(64)
            if not line:
                raise ValueError("truncated chunked POST body")
            count = int(line.split(b";", 1)[0].strip(), 16)
            if count < 0 or total + count > MAX_FIXTURE_BODY:
                raise ValueError("chunked POST body exceeds the fixture bound")
            if count == 0:
                while True:
                    trailer = self.rfile.readline(1024)
                    if not trailer or trailer in {CHUNK_CRLF, b"\n"}:
                        break
                break
            chunk = self.rfile.read(count)
            if len(chunk) != count:
                raise ValueError("truncated chunk")
            if self.rfile.read(len(CHUNK_CRLF)) != CHUNK_CRLF:
                raise ValueError("invalid chunk delimiter")
            parts.append(chunk)
            total += count
        return b"".join(parts)

    def _read_request_body(self) -> bytes:
        encoding = (self.headers.get("Transfer-Encoding") or "").lower()
        if "chunked" in encoding:
            return self._read_chunked_body()
        raw_length = self.headers.get("Content-Length")
        if raw_length is None or raw_length == "":
            return b""
        try:
            length = int(raw_length)
        except ValueError:
            return b""
        if length <= 0 or length > MAX_FIXTURE_BODY:
            return b""
        return self.rfile.read(length)

    def _observe_post(self, state: _State, body: bytes) -> None:
        state.posts += 1
        state.posted_body = body
        state.posted_body_bytes = len(body)
        state.auth.append(self.headers.get("Authorization"))
        state.paths.append(("POST", self.path, self.headers.get("Authorization")))
        state.posted_json = body.lstrip().startswith(b"{") or b"audioData" in body
        config_at = body.find(b'name="transcribeConfig"')
        file_at = body.find(b'name="file"')
        state.config_before_file = config_at != -1 and file_at != -1 and config_at < file_at
        manifest_path = state.project / "brolls" / "manifest.json"
        if not manifest_path.is_file():
            return
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return
        analyses = (manifest.get("narration") or {}).get("analyses") or {}
        values = analyses.values() if isinstance(analyses, dict) else ()
        state.intent_before_post = any(
            isinstance(item, dict) and item.get("state") in {"intent", "pending", "unknown"} for item in values
        )

    def _result_payload(self, state: _State) -> dict[str, object]:
        if state.mode == "invalid_times":
            return {
                "transcript": "kept text",
                "segments": [
                    {
                        "wordTimestamps": [
                            {"word": "bad", "startTimeMs": True, "endTimeMs": 10},
                            {"word": "neg", "startTimeMs": -1, "endTimeMs": 2},
                            {"word": "rev", "startTimeMs": 9, "endTimeMs": 1},
                        ]
                    }
                ],
            }
        if state.mode == "metadata_leak":
            return {
                "transcript": TRANSCRIPT,
                "language": {"signedURI": SIGNED, "authorization": "Basic " + FIXTURE_KEY},
                "usage": {
                    "modelId": {"resultUri": SIGNED, "authorization": "Basic " + FIXTURE_KEY},
                    "audioDurationMs": SIGNED,
                },
                "confidence": 0,
                "segments": [
                    {
                        "wordTimestamps": [
                            {"word": "Hello", "endTimeMs": 400},
                            {"word": "</script>", "startTimeMs": 400, "endTimeMs": 700},
                        ]
                    },
                    {"wordTimestamps": [{"word": "world", "startTimeMs": 800, "endTimeMs": 1100}]},
                ],
            }
        if state.mode == "outside_timing":
            return {
                "transcript": TRANSCRIPT,
                "segments": [{"wordTimestamps": [{"word": "Hello", "endTimeMs": OUTSIDE_WORD_END_MS}]}],
            }
        if state.mode == "nonmonotonic":
            return {
                "transcript": TRANSCRIPT,
                "segments": [
                    {"wordTimestamps": [{"word": "Hello", "endTimeMs": NONMONOTONIC_FIRST_END_MS}]},
                    {
                        "wordTimestamps": [
                            {
                                "word": "world",
                                "startTimeMs": NONMONOTONIC_SECOND_START_MS,
                                "endTimeMs": NONMONOTONIC_SECOND_END_MS,
                            }
                        ]
                    },
                ],
            }
        if state.mode == "backwards_start":
            return {
                "transcript": TRANSCRIPT,
                "segments": [
                    {
                        "wordTimestamps": [
                            {
                                "word": "Hello",
                                "startTimeMs": BACKWARDS_START_FIRST_START_MS,
                                "endTimeMs": BACKWARDS_START_FIRST_END_MS,
                            }
                        ]
                    },
                    {
                        "wordTimestamps": [
                            {
                                "word": "world",
                                "startTimeMs": BACKWARDS_START_SECOND_START_MS,
                                "endTimeMs": BACKWARDS_START_SECOND_END_MS,
                            }
                        ]
                    },
                ],
            }
        return {
            "transcript": TRANSCRIPT,
            "language": "en",
            "usage": {"audioDurationMs": VALID_DURATION_S * 1000, "modelId": "inworld/inworld-stt-1"},
            "confidence": 0,
            "segments": [
                {
                    "wordTimestamps": [
                        {"word": "Hello", "endTimeMs": 400},
                        {"word": "</script>", "startTimeMs": 400, "endTimeMs": 700},
                    ]
                },
                {"wordTimestamps": [{"word": "world", "startTimeMs": 800, "endTimeMs": 1100}]},
            ],
        }

    def _operation_payload(self, state: _State) -> dict[str, object]:
        if state.mode == "job_error":
            return {"name": OPERATION, "done": True, "error": {"message": MALICIOUS_ERROR}}
        if state.mode == "missing":
            return {"name": OPERATION, "done": True, "response": {}}
        if state.mode == "pending":
            return {"name": OPERATION, "done": False}
        if state.mode == "complete_after_poll" and state.gets == 1:
            return {"name": OPERATION, "done": False}
        result_uri = "http://127.0.0.1:1/secret" if state.mode == "private_result" else self._result_uri()
        expire = "2020-01-01T00:00:00Z" if state.mode == "expired" else "2099-01-01T00:00:00Z"
        if state.mode in _DONE_RESULT_MODES or state.mode == "expired":
            return {"name": OPERATION, "done": True, "response": {"resultUri": result_uri, "expireTime": expire}}
        return {"name": OPERATION, "done": False}

    def _handle_result(self, state: _State) -> None:
        state.downloads += 1
        if self.headers.get("Authorization"):
            state.auth_on_download = True
        if state.mode == "expired":
            self._send(404, {"error": MALICIOUS_ERROR})
            return
        if state.mode == "redirect_result":
            state.redirects += 1
            self.send_response(302)
            self.send_header("Location", "https://example.com/steal")
            self.end_headers()
            return
        self._send(200, self._result_payload(state))

    def _handle_operation(self, state: _State) -> None:
        state.gets += 1
        self._send(200, self._operation_payload(state))

    def do_GET(self) -> None:
        state = self.server.state
        state.paths.append(("GET", self.path, self.headers.get("Authorization")))
        if self.path.startswith("/results/"):
            self._handle_result(state)
            return
        if self.path.startswith("/lro/v1alpha/"):
            self._handle_operation(state)
            return
        self._send(404, {"error": "missing"})

    def do_POST(self) -> None:
        state = self.server.state
        body = self._read_request_body()
        self._observe_post(state, body)
        if state.mode == "disconnect":
            self.close_connection = True
            self.connection.close()
            return
        if state.mode == "timeout":
            time.sleep(2)
            return
        if state.mode == "reject":
            self._send(400, {"error": MALICIOUS_ERROR})
            return
        if state.mode == "invalid_handle":
            self._send(200, {"name": "workspaces/../etc/operations/x"})
            return
        self._send(200, {"name": OPERATION})


def _serving(project: str | Path, mode: str = "complete_after_poll") -> tuple[_Server, threading.Thread]:
    state = _State(Path(project), mode)
    server = _Server(("127.0.0.1", 0), _Handler, state)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, thread


def _stop(server: _Server, thread: threading.Thread) -> None:
    server.shutdown()
    thread.join(timeout=5)
    server.server_close()


def _env(server: _Server, extra: dict[str, str] | None = None) -> dict[str, str]:
    values = {
        "INWORLD_API_KEY": FIXTURE_KEY,
        "GETBROLLS_INWORLD_STT_TEST_MODE": "1",
        "GETBROLLS_INWORLD_STT_TEST_BASE": f"http://127.0.0.1:{server.port}",
        "GETBROLLS_INWORLD_STT_TEST_TIMEOUT": "0.4",
    }
    if extra:
        values.update(extra)
    return values


def _dump(tmp: str | Path) -> str:
    text = []
    root = Path(tmp) / "brolls"
    if root.is_dir():
        for path in root.rglob("*"):
            if path.is_file() and not _is_link(path):
                try:
                    text.append(path.read_text(encoding="utf-8", errors="replace"))
                except OSError:
                    text.append(path.read_bytes().decode("latin1", errors="replace"))
    return "\n".join(text)


def _assert_clean(test: unittest.TestCase, *blobs: object) -> None:
    combined = "\n".join(str(item) for item in blobs)
    for secret in SECRETS:
        test.assertNotIn(secret, combined)


def _assert_multipart_config_first(test: unittest.TestCase, server: _Server) -> None:
    test.assertGreater(server.state.posted_body_bytes, 0)
    body = server.state.posted_body
    test.assertIn(b'name="transcribeConfig"', body)
    test.assertIn(b'name="file"', body)
    test.assertLess(body.find(b'name="transcribeConfig"'), body.find(b'name="file"'))
    test.assertTrue(server.state.config_before_file)
    test.assertFalse(server.state.posted_json)


def _audio_regular_files(tmp: str | Path) -> list[Path]:
    root = Path(tmp) / "brolls" / "narration" / "private" / "audio"
    if not root.is_dir() or _is_link(root):
        return []
    return [path for path in root.iterdir() if path.is_file() and not _is_link(path)]


def _foreign_storage_rel(kind: str, wav: Path, analysis_id: str) -> str:
    recording_id = _recording_id(wav)
    if kind == "audio":
        return f"narration/private/audio/{recording_id}.wav"
    if kind == "result":
        return f"narration/results/{analysis_id}.json"
    if kind == "receipt":
        return f"narration/private/receipts/{analysis_id}.json"
    if kind == "audio-tmp":
        return f"narration/private/audio/{recording_id}.wav.tmp"
    if kind == "result-tmp":
        return f"narration/results/{analysis_id}.json.tmp"
    if kind == "receipt-tmp":
        return f"narration/private/receipts/{analysis_id}.json.tmp"
    raise AssertionError(f"unsupported foreign storage kind: {kind}")


def _foreign_storage_bytes(kind: str) -> bytes:
    if kind.endswith("-tmp"):
        return FOREIGN_TEMP
    if kind == "audio":
        return FOREIGN_AUDIO
    if kind == "result":
        return FOREIGN_RESULT
    if kind == "receipt":
        return FOREIGN_RECEIPT
    raise AssertionError(f"unsupported foreign storage kind: {kind}")


def _save_valid_pending(root: Path) -> tuple[Path, dict[str, object], bytes]:
    manifest_path = root / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if not isinstance(manifest, dict):
        raise AssertionError("manifest is not an object")
    pending = root / ".pending-transaction.json"
    pending.write_text(json.dumps({"data": manifest, "events": []}, ensure_ascii=False, indent=2), encoding="utf-8")
    return pending, manifest, pending.read_bytes()


class CommandSurfaceTests(unittest.TestCase):
    def test_commands_are_outside_format_gates_and_status_is_read_only(self):
        self.assertNotIn("narration-analyze", FORMAT_GATE_SUBCOMMANDS)
        self.assertNotIn("narration-resume", FORMAT_GATE_SUBCOMMANDS)
        self.assertNotIn("narration-analyze", READ_ONLY_COMMANDS)
        self.assertIn("status", READ_ONLY_COMMANDS)
        analyze = subprocess.run(
            [sys.executable, str(CLI), "narration-analyze", "--help"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            check=False,
        )
        self.assertEqual(0, analyze.returncode, analyze.stderr)
        self.assertIn("--recording", analyze.stdout)
        self.assertNotIn("--confirm-format-change", analyze.stdout)


class NarrationCliTests(unittest.TestCase):
    def test_validation_and_missing_key_never_post(self):
        with tempfile.TemporaryDirectory() as tmp:
            _project(tmp)
            server, thread = _serving(tmp)
            try:
                env = _env(server)
                env.pop("INWORLD_API_KEY")
                wav = _write_wav(Path(tmp) / "vo.wav")
                missing = run_cli(
                    "narration-analyze",
                    "--recording",
                    str(wav),
                    project=tmp,
                    env=env,
                    expect=2,
                )
                self.assertIn("INWORLD_API_KEY", missing["error"])
                empty = Path(tmp) / "empty.wav"
                empty.write_bytes(b"")
                env = _env(server)
                bad = run_cli(
                    "narration-analyze",
                    "--recording",
                    str(empty),
                    project=tmp,
                    env=env,
                    expect=2,
                )
                self.assertIn("recording", bad["error"].lower())
                bogus = Path(tmp) / "vo.txt"
                bogus.write_text("not a headered recording", encoding="utf-8")
                unsupported = run_cli(
                    "narration-analyze",
                    "--recording",
                    str(bogus),
                    project=tmp,
                    env=env,
                    expect=2,
                )
                self.assertIn("encoding", unsupported["error"].lower())
                self.assertEqual(0, server.state.posts)
            finally:
                _stop(server, thread)

    def test_submit_pending_resume_download_reuse_and_multipart_intent(self):
        with tempfile.TemporaryDirectory() as tmp:
            _project(tmp)
            wav = _write_wav(Path(tmp) / "vo.wav")
            server, thread = _serving(tmp, "complete_after_poll")
            try:
                env = _env(server)
                first = run_cli("narration-analyze", "--recording", str(wav), project=tmp, env=env)
                self.assertEqual("pending", first["state"])
                self.assertEqual("accepted", first["submit_outcome"])
                self.assertTrue(server.state.intent_before_post)
                _assert_multipart_config_first(self, server)
                self.assertEqual(1, server.state.posts)
                posted_auth = server.state.auth[0]
                self.assertIsNotNone(posted_auth)
                self.assertTrue((posted_auth or "").startswith("Basic "))
                pending = run_cli("narration-resume", "--analysis", first["analysis_id"], project=tmp, env=env)
                self.assertEqual("pending", pending["state"])
                done = run_cli("narration-resume", "--analysis", first["analysis_id"], project=tmp, env=env)
                self.assertEqual("completed", done["state"])
                self.assertEqual(TRANSCRIPT, done["transcript"])
                self.assertEqual(3, done["word_count"])
                self.assertEqual(0, done["timing"]["start_ms"])
                self.assertEqual(2, done["timing"]["segments"])
                self.assertTrue(done["timing_resolved"])
                self.assertNotIn("confidence", done)
                reused = run_cli("narration-analyze", "--recording", str(wav), project=tmp, env=env)
                self.assertTrue(reused["reused"])
                self.assertEqual(first["analysis_id"], reused["analysis_id"])
                self.assertEqual(1, server.state.posts)
                self.assertEqual(2, server.state.gets)
                self.assertEqual(1, server.state.downloads)
                self.assertFalse(server.state.auth_on_download)
                no_key = dict(env)
                no_key.pop("INWORLD_API_KEY")
                local = run_cli("narration-resume", "--analysis", first["analysis_id"], project=tmp, env=no_key)
                self.assertTrue(local["reused"])
                self.assertEqual(1, server.state.posts)
                other = _write_wav(Path(tmp) / "vo2.wav", byte=1)
                second = run_cli("narration-analyze", "--recording", str(other), project=tmp, env=env)
                self.assertNotEqual(first["analysis_id"], second["analysis_id"])
                lang = run_cli(
                    "narration-analyze",
                    "--recording",
                    str(wav),
                    "--language",
                    "pt-BR",
                    project=tmp,
                    env=env,
                )
                self.assertNotEqual(first["analysis_id"], lang["analysis_id"])
                ledger = Ledger(tmp, recover=False)
                self.assertEqual("completed", ledger.data["narration"]["analyses"][first["analysis_id"]]["state"])
                self.assertEqual(
                    TRANSCRIPT, ledger.data["narration"]["analyses"][first["analysis_id"]]["result"]["transcript"]
                )
                self.assertEqual(3, server.state.posts)
                _assert_clean(self, json.dumps(done), json.dumps(reused), _dump(tmp))
            finally:
                _stop(server, thread)

    def test_unknown_outcomes_never_repost(self):
        for mode, expect_state in (
            ("timeout", "unknown"),
            ("disconnect", "unknown"),
            ("invalid_handle", "unknown"),
        ):
            with self.subTest(mode=mode), tempfile.TemporaryDirectory() as tmp:
                _project(tmp)
                wav = _write_wav(Path(tmp) / "vo.wav")
                server, thread = _serving(tmp, mode)
                try:
                    env = _env(server)
                    result = run_cli(
                        "narration-analyze",
                        "--recording",
                        str(wav),
                        "--analysis",
                        f"na-{mode}",
                        project=tmp,
                        env=env,
                    )
                    self.assertEqual(expect_state, result["state"])
                    posts = server.state.posts
                    again = run_cli(
                        "narration-analyze",
                        "--recording",
                        str(wav),
                        "--analysis",
                        f"na-{mode}",
                        project=tmp,
                        env=env,
                        expect=2,
                    )
                    self.assertIn("resubmit", again["error"].lower())
                    resumed = run_cli("narration-resume", "--analysis", f"na-{mode}", project=tmp, env=env)
                    self.assertEqual("unknown", resumed["state"])
                    self.assertEqual(posts, server.state.posts)
                finally:
                    _stop(server, thread)

    def test_crash_windows_and_known_operation_resume(self):
        with tempfile.TemporaryDirectory() as tmp:
            _project(tmp)
            wav = _write_wav(Path(tmp) / "vo.wav")
            server, thread = _serving(tmp, "pending")
            try:
                env = _env(server, {"GETBROLLS_INWORLD_STT_TEST_CRASH": "after-intent"})
                crashed = run_cli(
                    "narration-analyze",
                    "--recording",
                    str(wav),
                    "--analysis",
                    "na-crash",
                    project=tmp,
                    env=env,
                    expect=2,
                )
                self.assertIn("interrupt", crashed["error"].lower())
                self.assertEqual(0, server.state.posts)
                ledger = Ledger(tmp, recover=False)
                self.assertEqual("intent", ledger.data["narration"]["analyses"]["na-crash"]["state"])
                env.pop("GETBROLLS_INWORLD_STT_TEST_CRASH")
                unknown = run_cli("narration-resume", "--analysis", "na-crash", project=tmp, env=env)
                self.assertEqual("unknown", unknown["state"])
                self.assertEqual(0, server.state.posts)
            finally:
                _stop(server, thread)
        with tempfile.TemporaryDirectory() as tmp:
            _project(tmp)
            wav = _write_wav(Path(tmp) / "vo.wav")
            server, thread = _serving(tmp, "pending")
            try:
                env = _env(server, {"GETBROLLS_INWORLD_STT_TEST_CRASH": "before-operation"})
                crashed = run_cli(
                    "narration-analyze",
                    "--recording",
                    str(wav),
                    "--analysis",
                    "na-post",
                    project=tmp,
                    env=env,
                    expect=2,
                )
                self.assertIn("interrupt", crashed["error"].lower())
                self.assertEqual(1, server.state.posts)
                env.pop("GETBROLLS_INWORLD_STT_TEST_CRASH")
                resumed = run_cli("narration-resume", "--analysis", "na-post", project=tmp, env=env)
                self.assertEqual("unknown", resumed["state"])
                self.assertEqual(1, server.state.posts)
            finally:
                _stop(server, thread)
        with tempfile.TemporaryDirectory() as tmp:
            _project(tmp)
            wav = _write_wav(Path(tmp) / "vo.wav")
            server, thread = _serving(tmp, "pending")
            try:
                env = _env(server)
                submitted = run_cli(
                    "narration-analyze", "--recording", str(wav), "--analysis", "na-op", project=tmp, env=env
                )
                self.assertEqual("pending", submitted["state"])
                self.assertEqual(OPERATION, submitted["operation_name"])
                resumed = run_cli("narration-resume", "--analysis", "na-op", project=tmp, env=env)
                self.assertEqual("pending", resumed["state"])
                self.assertEqual(1, server.state.posts)
                self.assertEqual(1, server.state.gets)
            finally:
                _stop(server, thread)

    def test_rejection_job_error_missing_expired_and_redaction(self):
        with tempfile.TemporaryDirectory() as tmp:
            _project(tmp)
            wav = _write_wav(Path(tmp) / "vo.wav")
            server, thread = _serving(tmp, "reject")
            try:
                env = _env(server)
                rejected = run_cli(
                    "narration-analyze", "--recording", str(wav), "--analysis", "na-rej", project=tmp, env=env
                )
                self.assertEqual("failed", rejected["state"])
                self.assertEqual("rejected", rejected["submit_outcome"])
                _assert_clean(self, json.dumps(rejected), _dump(tmp))
                repeat = run_cli(
                    "narration-analyze",
                    "--recording",
                    str(wav),
                    "--analysis",
                    "na-rej",
                    project=tmp,
                    env=env,
                    expect=2,
                )
                self.assertEqual(1, server.state.posts)
                self.assertIn("failed", repeat["error"].lower())
            finally:
                _stop(server, thread)
        for mode, code in (
            ("job_error", "PROVIDER_JOB_ERROR"),
            ("missing", "RESULT_MISSING"),
            ("expired", "RESULT_EXPIRED"),
        ):
            with tempfile.TemporaryDirectory() as tmp:
                _project(tmp)
                wav = _write_wav(Path(tmp) / "vo.wav")
                server, thread = _serving(tmp, mode)
                try:
                    env = _env(server)
                    run_cli("narration-analyze", "--recording", str(wav), "--analysis", "na-x", project=tmp, env=env)
                    result = run_cli("narration-resume", "--analysis", "na-x", project=tmp, env=env)
                    self.assertEqual(code, (result.get("error") or {}).get("code"))
                    _assert_clean(self, json.dumps(result), _dump(tmp), result.get("error"))
                    self.assertEqual(1, server.state.posts)
                finally:
                    _stop(server, thread)

    def test_corrupt_result_is_preserved_without_provider_calls(self):
        with tempfile.TemporaryDirectory() as tmp:
            _project(tmp)
            wav = _write_wav(Path(tmp) / "vo.wav")
            server, thread = _serving(tmp, "complete_after_poll")
            try:
                env = _env(server)
                run_cli("narration-analyze", "--recording", str(wav), "--analysis", "na-c", project=tmp, env=env)
                run_cli("narration-resume", "--analysis", "na-c", project=tmp, env=env)
                run_cli("narration-resume", "--analysis", "na-c", project=tmp, env=env)
                artifact = Path(tmp) / "brolls" / "narration" / "results" / "na-c.json"
                artifact.write_bytes(TAMPERED_RESULT)
                posts = server.state.posts
                gets = server.state.gets
                downloads = server.state.downloads
                corrupt = run_cli(
                    "narration-analyze",
                    "--recording",
                    str(wav),
                    "--analysis",
                    "na-c",
                    project=tmp,
                    env=env,
                    expect=2,
                )
                self.assertIn("corrupt", corrupt["error"].lower())
                recovered = run_cli("narration-resume", "--analysis", "na-c", project=tmp, env=env)
                self.assertEqual("completed", recovered["state"])
                self.assertEqual("ARTIFACT_CORRUPT", (recovered.get("error") or {}).get("code"))
                self.assertEqual(TAMPERED_RESULT, artifact.read_bytes())
                self.assertEqual(posts, server.state.posts)
                self.assertEqual(gets, server.state.gets)
                self.assertEqual(downloads, server.state.downloads)
            finally:
                _stop(server, thread)

    def test_missing_result_is_restored_without_resubmitting(self):
        with tempfile.TemporaryDirectory() as tmp:
            _project(tmp)
            wav = _write_wav(Path(tmp) / "vo.wav")
            server, thread = _serving(tmp, "complete_after_poll")
            try:
                env = _env(server)
                _submitted, done = _analyze_complete(tmp, wav, env, "na-restore")
                self.assertEqual("completed", done["state"])
                self.assertEqual(TRANSCRIPT, done["transcript"])
                self.assertTrue(done["timing_resolved"])
                artifact = Path(tmp) / "brolls" / "narration" / "results" / "na-restore.json"
                self.assertTrue(artifact.is_file())
                posts = server.state.posts
                downloads = server.state.downloads
                artifact.unlink()
                restored = run_cli("narration-resume", "--analysis", "na-restore", project=tmp, env=env)
                self.assertEqual("completed", restored["state"])
                self.assertEqual(TRANSCRIPT, restored["transcript"])
                self.assertEqual(done.get("timing"), restored.get("timing"))
                self.assertTrue(restored["timing_resolved"])
                self.assertEqual(posts, server.state.posts)
                self.assertGreater(server.state.downloads, downloads)
                self.assertTrue(artifact.is_file())
                self.assertNotEqual("ARTIFACT_CORRUPT", (restored.get("error") or {}).get("code"))
                stored = json.loads(artifact.read_text(encoding="utf-8"))
                self.assertEqual(TRANSCRIPT, stored.get("transcript"))
                self.assertTrue(stored.get("timing_resolved"))
            finally:
                _stop(server, thread)

    def test_malicious_destinations_redirects_and_invalid_times(self):
        with tempfile.TemporaryDirectory() as tmp:
            _project(tmp)
            wav = _write_wav(Path(tmp) / "vo.wav")
            server, thread = _serving(tmp, "private_result")
            try:
                env = _env(server)
                run_cli("narration-analyze", "--recording", str(wav), "--analysis", "na-p", project=tmp, env=env)
                result = run_cli("narration-resume", "--analysis", "na-p", project=tmp, env=env)
                self.assertEqual("RESULT_DESTINATION_REFUSED", (result.get("error") or {}).get("code"))
                _assert_clean(self, json.dumps(result), _dump(tmp))
            finally:
                _stop(server, thread)
        with tempfile.TemporaryDirectory() as tmp:
            _project(tmp)
            wav = _write_wav(Path(tmp) / "vo.wav")
            server, thread = _serving(tmp, "redirect_result")
            try:
                env = _env(server)
                run_cli("narration-analyze", "--recording", str(wav), "--analysis", "na-r", project=tmp, env=env)
                result = run_cli("narration-resume", "--analysis", "na-r", project=tmp, env=env)
                self.assertEqual("RESULT_DESTINATION_REFUSED", (result.get("error") or {}).get("code"))
                self.assertGreaterEqual(server.state.redirects, 1)
            finally:
                _stop(server, thread)
        with tempfile.TemporaryDirectory() as tmp:
            _project(tmp)
            wav = _write_wav(Path(tmp) / "vo.wav")
            server, thread = _serving(tmp, "invalid_times")
            try:
                env = _env(server)
                run_cli("narration-analyze", "--recording", str(wav), "--analysis", "na-t", project=tmp, env=env)
                result = run_cli("narration-resume", "--analysis", "na-t", project=tmp, env=env)
                self.assertEqual("completed", result["state"])
                self.assertEqual("kept text", result["transcript"])
                self.assertFalse(result["timing_resolved"])
                self.assertNotIn("confidence", json.dumps(result))
            finally:
                _stop(server, thread)

    def test_status_under_writer_lock_keeps_valid_pending_journal(self):
        with tempfile.TemporaryDirectory() as tmp:
            _project(tmp)
            wav = _write_wav(Path(tmp) / "vo.wav")
            server, thread = _serving(tmp, "complete_after_poll")
            try:
                env = _env(server)
                _analyze_complete(tmp, wav, env, "na-1")
                root = Path(tmp) / "brolls"
                pending, _manifest, pending_bytes = _save_valid_pending(root)
                before = _file_hashes(root)
                posts = server.state.posts
                with project_lock(tmp):
                    status = run_cli("status", project=tmp)
                self.assertEqual("pending", status["journal"]["recovered_write"])
                self.assertEqual("completed", status["narration"]["current"]["state"])
                self.assertEqual(TRANSCRIPT, status["narration"]["current"]["transcript"])
                self.assertEqual(posts, server.state.posts)
                self.assertEqual(before, _file_hashes(root))
                self.assertTrue(pending.is_file())
                self.assertEqual(pending_bytes, pending.read_bytes())
                _assert_clean(self, json.dumps(status), _dump(tmp))
            finally:
                _stop(server, thread)

    def test_review_recovers_saved_valid_narration_transaction(self):
        with tempfile.TemporaryDirectory() as tmp:
            _project(tmp)
            wav = _write_wav(Path(tmp) / "vo.wav")
            server, thread = _serving(tmp, "complete_after_poll")
            try:
                env = _env(server)
                _analyze_complete(tmp, wav, env, "na-1")
                root = Path(tmp) / "brolls"
                pending, manifest, _pending_bytes = _save_valid_pending(root)
                posts = server.state.posts
                reviewed = run_cli("review", project=tmp)
                self.assertFalse(pending.is_file())
                recovered = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
                self.assertEqual(manifest.get("narration"), recovered.get("narration"))
                page = Path(reviewed["review"]).read_text(encoding="utf-8")
                self.assertIn("narration-board", page)
                self.assertIn("Hello &lt;/script&gt; &amp; &quot;quoted&quot; world", page)
                self.assertNotIn("</script><img", page.split("narration-board", 1)[1].split("</section>", 1)[0])
                payload = _review_payload(page)
                self.assertEqual(TRANSCRIPT, _review_transcript(page))
                self.assertNotIn("resultUri", json.dumps(payload))
                self.assertNotIn("narration/private", json.dumps(payload))
                self.assertEqual(posts, server.state.posts)
                _assert_clean(self, page, json.dumps(payload), _dump(tmp))
            finally:
                _stop(server, thread)

    def test_serve_denies_private_audio_and_receipts(self):
        with tempfile.TemporaryDirectory() as tmp:
            _project(tmp)
            wav = _write_wav(Path(tmp) / "vo.wav")
            server, thread = _serving(tmp, "complete_after_poll")
            try:
                env = _env(server)
                _analyze_complete(tmp, wav, env, "na-1")
                reviewed = run_cli("review", project=tmp)
                self.assertTrue(Path(reviewed["review"]).is_file())
                root = Path(tmp) / "brolls"
                from getbrolls import serve

                httpd, port = serve.start(tmp, port=0)
                serve_thread = threading.Thread(target=httpd.serve_forever, daemon=True)
                serve_thread.start()
                try:
                    audio = next((root / "narration" / "private" / "audio").glob("*.wav"))
                    receipt = root / "narration" / "private" / "receipts" / "na-1.json"
                    receipt.parent.mkdir(parents=True, exist_ok=True)
                    receipt.write_text(json.dumps({"resultUri": SIGNED}), encoding="utf-8")
                    for rel in (audio.relative_to(root).as_posix(), receipt.relative_to(root).as_posix()):
                        with self.assertRaises(urllib.error.HTTPError) as raised:
                            urllib.request.urlopen(f"http://127.0.0.1:{port}/{rel}", timeout=5)
                        try:
                            self.assertEqual(404, raised.exception.code)
                        finally:
                            raised.exception.close()
                finally:
                    httpd.shutdown()
                    serve_thread.join(timeout=5)
                    httpd.server_close()
            finally:
                _stop(server, thread)

    def test_invalid_narration_history_is_preserved(self):
        with tempfile.TemporaryDirectory() as tmp:
            _project(tmp)
            wav = _write_wav(Path(tmp) / "vo.wav")
            server, thread = _serving(tmp, "complete_after_poll")
            try:
                env = _env(server)
                _analyze_complete(tmp, wav, env, "na-1")
                root = Path(tmp) / "brolls"
                manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
                manifest["narration"]["analyses"]["na-1"]["state"] = "nope"
                (root / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
                broken = run_cli("status", project=tmp, expect=2)
                self.assertIn("Preserve", broken["error"])
                stored = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
                self.assertEqual("nope", stored["narration"]["analyses"]["na-1"]["state"])
            finally:
                _stop(server, thread)

    def test_legacy_project_without_narration_still_status(self):
        with tempfile.TemporaryDirectory() as tmp:
            _project(tmp)
            Ledger(tmp)
            payload = run_cli("status", project=tmp)
            self.assertEqual(0, payload["narration"]["analyses"])
            self.assertIsNone(payload["narration"]["current"])

    def test_truncated_recordings_are_refused_without_provider_post(self):
        with tempfile.TemporaryDirectory() as tmp:
            _project(tmp)
            server, thread = _serving(tmp)
            try:
                env = _env(server)
                header_only = _header_only_wav(Path(tmp) / "header-only.wav")
                truncated = _truncated_payload_wav(Path(tmp) / "truncated-payload.wav")
                header_result = run_cli(
                    "narration-analyze",
                    "--recording",
                    str(header_only),
                    "--analysis",
                    "na-header",
                    project=tmp,
                    env=env,
                    expect=2,
                )
                truncated_result = run_cli(
                    "narration-analyze",
                    "--recording",
                    str(truncated),
                    "--analysis",
                    "na-trunc",
                    project=tmp,
                    env=env,
                    expect=2,
                )
                self.assertEqual(0, server.state.posts)
                self.assertEqual([], _audio_regular_files(tmp))
                self.assertIn("recording", header_result["error"].lower())
                self.assertIn("recording", truncated_result["error"].lower())
                wav = _write_wav(Path(tmp) / "vo.wav")
                submitted, done = _analyze_complete(tmp, wav, env, "na-valid")
                self.assertIn(submitted["state"], {"pending", "completed"})
                self.assertEqual("completed", done["state"])
                self.assertEqual(TRANSCRIPT, done["transcript"])
                self.assertTrue(done["timing_resolved"])
                reused = run_cli("narration-analyze", "--recording", str(wav), project=tmp, env=env)
                self.assertTrue(reused["reused"])
                self.assertEqual(1, server.state.posts)
                self.assertFalse(server.state.auth_on_download)
            finally:
                _stop(server, thread)

    def test_malicious_provider_metadata_is_kept_out_of_public_state(self):
        with tempfile.TemporaryDirectory() as tmp:
            _project(tmp)
            wav = _write_wav(Path(tmp) / "vo.wav")
            server, thread = _serving(tmp, "metadata_leak")
            try:
                env = _env(server)
                _submitted, done = _analyze_complete(tmp, wav, env, "na-meta")
                status = run_cli("status", project=tmp)
                reviewed = run_cli("review", project=tmp)
                page = Path(reviewed["review"]).read_text(encoding="utf-8")
                payload = _review_payload(page)
                self.assertEqual(TRANSCRIPT, done["transcript"])
                self.assertEqual(TRANSCRIPT, status["narration"]["current"]["transcript"])
                dumped = _dump(tmp)
                public = json.dumps({"done": done, "status": status, "payload": payload})
                _assert_clean(self, public, dumped, page)
                self.assertNotIn("resultUri", public)
                result_path = Path(tmp) / "brolls" / "narration" / "results" / "na-meta.json"
                self.assertTrue(result_path.is_file())
                stored = json.loads(result_path.read_text(encoding="utf-8"))
                self.assertEqual(TRANSCRIPT, stored.get("transcript"))
                self.assertIsNone(stored.get("language"))
                usage = stored.get("usage")
                if isinstance(usage, dict) and "modelId" in usage:
                    self.assertIsInstance(usage["modelId"], str)
                if isinstance(usage, dict):
                    self.assertNotEqual(SIGNED, usage.get("audioDurationMs"))
                _assert_clean(self, json.dumps(stored))
                self.assertNotIn("confidence", done)
                self.assertEqual(1, server.state.posts)
                self.assertFalse(server.state.auth_on_download)
            finally:
                _stop(server, thread)

    def test_out_of_bounds_and_nonmonotonic_timing_stay_unresolved(self):
        cases = ("outside_timing", "nonmonotonic", "backwards_start")
        for mode in cases:
            with self.subTest(mode=mode), tempfile.TemporaryDirectory() as tmp:
                _project(tmp)
                wav = _write_wav(Path(tmp) / "vo.wav")
                server, thread = _serving(tmp, mode)
                try:
                    env = _env(server)
                    _submitted, done = _analyze_complete(tmp, wav, env, f"na-{mode}")
                    status = run_cli("status", project=tmp)
                    self.assertEqual("completed", done["state"])
                    self.assertEqual(TRANSCRIPT, done["transcript"])
                    self.assertFalse(done["timing_resolved"])
                    self.assertNotIn("confidence", json.dumps(done))
                    current = status["narration"]["current"]
                    self.assertEqual(TRANSCRIPT, current["transcript"])
                    self.assertFalse(current["timing_resolved"])
                    recording = done.get("recording") or current.get("recording") or {}
                    if not isinstance(recording, dict):
                        raise AssertionError("public CLI omitted recording identity")
                    duration = recording.get("duration_s")
                    if not isinstance(duration, int | float) or isinstance(duration, bool):
                        raise AssertionError("public CLI omitted recording duration")
                    self.assertEqual(float(VALID_DURATION_S), float(duration))
                    if mode == "outside_timing":
                        timing = done.get("timing")
                        end_ms = timing.get("end_ms") if isinstance(timing, dict) else None
                        if isinstance(end_ms, int | float) and not isinstance(end_ms, bool):
                            self.assertGreater(end_ms, float(duration) * 1000)
                    self.assertEqual(1, server.state.posts)
                    self.assertFalse(server.state.auth_on_download)
                finally:
                    _stop(server, thread)

    def test_unsafe_storage_links_and_foreign_artifacts_are_refused(self):
        for rel in _STORAGE_RELS:
            with self.subTest(storage=rel):
                self._assert_storage_dir_link_refused(rel)
        for kind in _FOREIGN_FILE_KINDS:
            with self.subTest(storage=f"foreign-{kind}"):
                self._assert_foreign_path_preserved(kind)
        for kind in _FOREIGN_TMP_KINDS:
            with self.subTest(storage=kind):
                self._assert_foreign_path_preserved(kind)
        with self.subTest(storage="snapshot-file-link"):
            self._assert_snapshot_file_link_refused()

    def _assert_storage_dir_link_refused(self, rel: str) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = _project(tmp)
            outside = root / "outside-storage"
            sentinel = outside / OUTSIDE_SENTINEL_NAME
            link = root / "brolls" / rel
            if not _make_dir_link(link, outside):
                self.skipTest("could not create a confined directory link or junction")
            self.assertTrue(_confined(outside, root))
            sentinel.write_bytes(OUTSIDE_SENTINEL)
            server, thread = _serving(tmp)
            try:
                wav = _write_wav(root / "vo.wav")
                refused = run_cli(
                    "narration-analyze",
                    "--recording",
                    str(wav),
                    "--analysis",
                    "na-link",
                    project=tmp,
                    env=_env(server),
                    expect=2,
                )
                self.assertEqual(0, server.state.posts)
                self.assertEqual(OUTSIDE_SENTINEL, sentinel.read_bytes())
                names = sorted(path.name for path in outside.iterdir() if path.is_file())
                self.assertEqual([OUTSIDE_SENTINEL_NAME], names)
                self.assertTrue(refused.get("error"))
                ledger = Ledger(tmp, recover=False)
                analyses = (ledger.data.get("narration") or {}).get("analyses") or {}
                self.assertEqual({}, analyses)
            finally:
                _remove_owned_link(link)
                _stop(server, thread)
                self.assertEqual(OUTSIDE_SENTINEL, sentinel.read_bytes())
                self.assertTrue(sentinel.is_file())

    def _assert_foreign_path_preserved(self, kind: str) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = _project(tmp)
            wav = _write_wav(root / "vo.wav")
            analysis_id = "na-foreign"
            payload = _foreign_storage_bytes(kind)
            planted = root / "brolls" / _foreign_storage_rel(kind, wav, analysis_id)
            planted.parent.mkdir(parents=True, exist_ok=True)
            planted.write_bytes(payload)
            server, thread = _serving(tmp)
            try:
                refused = run_cli(
                    "narration-analyze",
                    "--recording",
                    str(wav),
                    "--analysis",
                    analysis_id,
                    project=tmp,
                    env=_env(server),
                    expect=2,
                )
                self.assertEqual(0, server.state.posts)
                self.assertTrue(refused.get("error"))
                self.assertEqual(payload, planted.read_bytes())
                ledger = Ledger(tmp, recover=False)
                analyses = (ledger.data.get("narration") or {}).get("analyses") or {}
                self.assertEqual({}, analyses)
            finally:
                _stop(server, thread)

    def _assert_snapshot_file_link_refused(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = _project(tmp)
            outside = root / "outside-file"
            outside.mkdir()
            target = outside / "foreign.wav"
            target.write_bytes(FOREIGN_AUDIO)
            wav = _write_wav(root / "vo.wav")
            dest = root / "brolls" / "narration" / "private" / "audio" / f"{_recording_id(wav)}.wav"
            if not _make_file_link(dest, target):
                self.skipTest("could not create a confined file link")
            self.assertTrue(_confined(target, root))
            server, thread = _serving(tmp)
            try:
                refused = run_cli(
                    "narration-analyze",
                    "--recording",
                    str(wav),
                    "--analysis",
                    "na-filelink",
                    project=tmp,
                    env=_env(server),
                    expect=2,
                )
                self.assertEqual(0, server.state.posts)
                self.assertEqual(FOREIGN_AUDIO, target.read_bytes())
                self.assertTrue(refused.get("error"))
            finally:
                if dest.is_symlink() or _is_link(dest):
                    dest.unlink()
                _stop(server, thread)
                self.assertEqual(FOREIGN_AUDIO, target.read_bytes())


class TransportGuardTests(unittest.TestCase):
    def test_loopback_substitution_cannot_silently_route_production(self):
        with patch.dict(os.environ, {TEST_MODE_ENV: "0", TEST_BASE_ENV: "http://127.0.0.1:9"}):
            self.assertEqual(PRODUCTION_API, api_base())
        with patch.dict(os.environ, {TEST_MODE_ENV: "1"}):
            os.environ.pop(TEST_BASE_ENV, None)
            with self.assertRaises(ValueError):
                api_base()
        with (
            patch.dict(os.environ, {TEST_MODE_ENV: "1", TEST_BASE_ENV: "https://127.0.0.1:9"}),
            self.assertRaises(ValueError),
        ):
            api_base()
        with (
            patch.dict(os.environ, {TEST_MODE_ENV: "1", TEST_BASE_ENV: "http://example.com:9"}),
            self.assertRaises(ValueError),
        ):
            api_base()
        with (
            patch.dict(os.environ, {TEST_MODE_ENV: "1", TEST_BASE_ENV: "http://127.0.0.1:9/stt"}),
            self.assertRaises(ValueError),
        ):
            api_base()
        with patch.dict(os.environ, {TEST_MODE_ENV: "1", TEST_BASE_ENV: "http://127.0.0.1:9"}):
            self.assertEqual("http://127.0.0.1:9", api_base())


if __name__ == "__main__":
    unittest.main()
