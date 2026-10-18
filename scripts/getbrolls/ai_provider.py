"""Native ChatGPT subscription stills via Codex app-server JSON-RPC.

`codex exec` JSON omits imageGeneration. This adapter speaks `codex app-server --stdio`
as JSONL (one object per line, envelope omits jsonrpc) and treats only an
`imageGeneration` item with a real `savedPath` as completion.
"""

from __future__ import annotations

import contextlib
import hashlib
import json
import os
import queue
import shutil
import subprocess
import sys
import threading
import time
from collections import deque
from pathlib import Path

from . import __version__
from .runtime import redact

APP_SERVER_ENV = "GETBROLLS_CODEX_APP_SERVER"
TIMEOUT_S = 120
CLIENT_NAME = "get-brolls"
OPENAI_PROVIDER = "openai"
MAX_LINE = 1_048_576
MAX_EVENTS = 32
MAX_INBOX = 64
READ_CHUNK = 4096
TEST_ENV = ("GETBROLLS_AI_FIXTURE", "GETBROLLS_AI_INLINE", "GETBROLLS_AI_TEST_CRASH")
BILLING_KEYS = ("OPENAI_API_KEY", "OPENROUTER_API_KEY", "ANTHROPIC_API_KEY")
QUOTA_INFO = frozenset({"usageLimitExceeded", "rateLimitExceeded", "sessionBudgetExceeded"})

UNSUPPORTED = "unsupported"
AUTH = "auth"
QUOTA = "quota"
UNKNOWN = "unknown"
FAILED = "failed"
COMPLETE = "complete"
IMAGE_DETAILS = frozenset({"auto", "low", "high", "original"})
INSPECTION_OVERRIDE = "features.image_generation=false"
INSPECTION_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["observations"],
    "properties": {
        "observations": {
            "type": "array",
            "minItems": 1,
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["id", "order", "role", "sha256", "observation"],
                "properties": {
                    "id": {"type": "string"},
                    "order": {"type": "integer", "minimum": 1},
                    "role": {"type": "string"},
                    "sha256": {"type": "string"},
                    "observation": {"type": "string"},
                },
            },
        },
    },
}

_TURN_EVENTS = frozenset({"item/started", "item/completed", "turn/started", "turn/completed"})
_OVERSIZED = "Native app-server line exceeds the bounded JSONL size."


class _TransportEndedError(Exception):
    def __init__(self):
        super().__init__("The native app-server ended before a saved still was available.")


class _DeadlineExceededError(Exception):
    def __init__(self):
        super().__init__("The native app-server deadline elapsed before a saved still was available.")


def _encode(payload):
    return json.dumps(payload, ensure_ascii=False, allow_nan=False).encode("utf-8") + b"\n"


def _child_env():
    env = os.environ.copy()
    env["PYTHONUNBUFFERED"] = "1"
    for name in BILLING_KEYS:
        env.pop(name, None)
    return env


def _close_stream(stream):
    if stream is None:
        return
    with contextlib.suppress(OSError):
        stream.close()


def _decode_line(line):
    if len(line) > MAX_LINE:
        raise ValueError(_OVERSIZED)
    data = json.loads(line.decode("utf-8"))
    if not isinstance(data, dict):
        raise ValueError("Native app-server sent a non-object JSONL message.")
    return data


def _split_jsonl(buf):
    messages = []
    while True:
        newline = buf.find(b"\n")
        if newline < 0:
            break
        line = buf[:newline].rstrip(b"\r")
        buf = buf[newline + 1 :]
        if line.strip():
            messages.append(_decode_line(line))
    if len(buf) > MAX_LINE:
        raise ValueError(_OVERSIZED)
    return messages, buf


def _is_rpc_response(message):
    return "id" in message and "method" not in message and ("result" in message or "error" in message)


class AppServer:
    """Bounded JSONL transport over a stdio app-server process."""

    def __init__(self, proc, timeout: float = TIMEOUT_S):
        self.proc = proc
        self.timeout = timeout
        self.deadline = time.monotonic() + timeout
        self._next_id = 1
        self.pending = {}
        self.results = {}
        self._events = deque()
        self._inbox = queue.Queue(maxsize=MAX_INBOX)
        self._outbox = queue.Queue(maxsize=1)
        self._closed = False
        self._reader = threading.Thread(target=self._read_stdout, name="app-server-stdout", daemon=True)
        self._writer = threading.Thread(target=self._write_loop, name="app-server-stdin", daemon=True)
        self._reader.start()
        self._writer.start()

    def remaining(self):
        return self.deadline - time.monotonic()

    def close(self):
        if self._closed:
            return
        self._closed = True
        proc = self.proc
        if proc.poll() is None:
            with contextlib.suppress(OSError):
                proc.terminate()
            try:
                proc.wait(timeout=0.5)
            except subprocess.TimeoutExpired:
                with contextlib.suppress(OSError):
                    proc.kill()
                with contextlib.suppress(subprocess.TimeoutExpired):
                    proc.wait(timeout=0.5)
        with contextlib.suppress(queue.Full):
            self._outbox.put_nowait(None)
        self._writer.join(timeout=0.5)
        self._reader.join(timeout=0.5)
        _close_stream(proc.stdin)
        _close_stream(proc.stdout)
        _close_stream(proc.stderr)

    def _inbox_put(self, item):
        while not self._closed:
            try:
                self._inbox.put(item, timeout=0.1)
                return
            except queue.Full:
                if self._closed:
                    return
        with contextlib.suppress(queue.Full):
            self._inbox.put_nowait(item)

    def notify(self, method, params=None):
        message = {"method": method}
        if params is not None:
            message["params"] = params
        self._write(message)

    def request(self, method, params=None):
        ident = self._next_id
        self._next_id += 1
        message = {"id": ident, "method": method}
        if params is not None:
            message["params"] = params
        self.pending[ident] = method
        self._write(message)
        return ident

    def wait(self, ident):
        while ident in self.pending:
            message = self._recv()
            if ident not in self.pending:
                break
            if message.get("method") in _TURN_EVENTS:
                self._buffer(message)
        return self.results.pop(ident)

    def read(self):
        if self._events:
            return self._events.popleft()
        return self._recv()

    def _buffer(self, message):
        if len(self._events) >= MAX_EVENTS:
            raise ValueError("Native app-server event buffer exceeded the bound.")
        self._events.append(message)

    def _write(self, message):
        timeout = self.remaining()
        if self._closed or timeout <= 0:
            raise _DeadlineExceededError
        raw = _encode(message)
        if len(raw) > MAX_LINE:
            raise ValueError(_OVERSIZED)
        done = threading.Event()
        result = {"exc": None}
        try:
            self._outbox.put((raw, done, result), timeout=timeout)
        except queue.Full as exc:
            raise _DeadlineExceededError from exc
        if not done.wait(timeout=max(0.0, self.remaining())):
            raise _DeadlineExceededError
        if result["exc"] is not None:
            raise result["exc"]

    def _write_loop(self):
        while not self._closed:
            try:
                item = self._outbox.get(timeout=0.1)
            except queue.Empty:
                continue
            if item is None:
                return
            raw, done, result = item
            try:
                self._write_all(raw)
            except (OSError, ValueError, _TransportEndedError, _DeadlineExceededError) as exc:
                result["exc"] = exc
            finally:
                done.set()

    def _write_all(self, raw):
        if self._closed:
            raise _TransportEndedError
        stdin = self.proc.stdin
        if stdin is None:
            raise _TransportEndedError
        view = memoryview(raw)
        offset = 0
        while offset < len(raw):
            if self._closed:
                raise _TransportEndedError
            written = stdin.write(view[offset:])
            if not written:
                raise _TransportEndedError
            offset += written
        stdin.flush()

    def _recv(self):
        timeout = self.remaining()
        if timeout <= 0:
            raise _DeadlineExceededError
        if self.proc.poll() is not None and self._inbox.empty() and not self._events:
            raise _TransportEndedError
        try:
            item = self._inbox.get(timeout=timeout)
        except queue.Empty:
            raise _DeadlineExceededError from None
        if item is None:
            raise _TransportEndedError
        if isinstance(item, BaseException):
            raise item
        if _is_rpc_response(item):
            ident = item.get("id")
            self.pending.pop(ident, None)
            self.results[ident] = item
        return item

    def _read_stdout(self):
        stream = self.proc.stdout
        buf = b""
        try:
            while True:
                chunk = stream.read(READ_CHUNK)
                if not chunk:
                    if buf.strip():
                        self._inbox_put(ValueError("Native app-server ended mid-line."))
                    self._inbox_put(None)
                    return
                buf += chunk
                messages, buf = _split_jsonl(buf)
                for data in messages:
                    self._inbox_put(data)
        except (OSError, ValueError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            closed = self._closed or (isinstance(exc, ValueError) and "closed" in str(exc).lower())
            self._inbox_put(None if closed else exc)


def _command(*, inspection=False):
    override = os.environ.get(APP_SERVER_ENV)
    if any(os.environ.get(name) for name in TEST_ENV) and not override:
        raise ValueError("Test fixture env is set but GETBROLLS_CODEX_APP_SERVER is missing.")
    if override:
        path = Path(override)
        if not path.is_file():
            raise ValueError("GETBROLLS_CODEX_APP_SERVER does not point to an executable fixture.")
        command = [sys.executable, str(path)] if path.suffix.lower() == ".py" else [str(path)]
    else:
        binary = shutil.which("codex")
        if not binary:
            raise ValueError("Codex CLI is not installed; GPT subscription stills cannot run.")
        command = [binary, "app-server", "--stdio"]
    if inspection:
        return _inspection_command(command)
    return command


def _inspection_command(command):
    """Process-only image-generation disable. This does not write user configuration."""
    flag = ["-c", INSPECTION_OVERRIDE]
    executable = Path(command[0]).name.lower()
    if executable.startswith("python"):
        return [*command, "--", *flag]
    if "app-server" in command:
        index = command.index("app-server")
        return [*command[:index], *flag, *command[index:]]
    return [command[0], *flag, *command[1:]]


def _spawn(command, workdir):
    kwargs = {
        "stdin": subprocess.PIPE,
        "stdout": subprocess.PIPE,
        "stderr": subprocess.DEVNULL,
        "cwd": str(workdir),
        "env": _child_env(),
        "bufsize": 0,
    }
    if os.name == "nt" and hasattr(subprocess, "CREATE_NO_WINDOW"):
        kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW
    return subprocess.Popen(command, **kwargs)  # noqa: S603 - pinned Codex binary or test fixture.


def _rpc_error(message):
    error = message.get("error") if isinstance(message, dict) else None
    if not isinstance(error, dict):
        return ""
    text = str(error.get("message") or error.get("data") or "")
    return redact(text)


def _classify_rpc_error(text):
    lowered = text.lower()
    if any(token in lowered for token in ("unauthor", "login", "not logged", "auth")):
        return AUTH, "ChatGPT subscription login is required for native stills."
    if "usage" in lowered or "quota" in lowered or "limit" in lowered:
        return QUOTA, "The ChatGPT subscription image quota is exhausted."
    return FAILED, text or "The native image session failed."


def _account_status(result):
    if not isinstance(result, dict):
        return AUTH, "ChatGPT subscription login is required for native stills."
    account = result.get("account")
    if not isinstance(account, dict):
        return AUTH, "ChatGPT subscription login is required for native stills."
    kind = account.get("type")
    if kind == "chatgpt":
        return None, None
    if kind == "apiKey":
        return AUTH, "An API key is not ChatGPT subscription image access."
    return AUTH, "ChatGPT subscription login is required for native stills."


def _item(message):
    params = message.get("params") if isinstance(message, dict) else None
    if not isinstance(params, dict):
        return None
    item = params.get("item")
    return item if isinstance(item, dict) else None


def _nested_id(result, key):
    if not isinstance(result, dict):
        return None
    payload = result.get("result") if "result" in result else result
    if not isinstance(payload, dict):
        return None
    nested = payload.get(key)
    if isinstance(nested, dict) and isinstance(nested.get("id"), str):
        return nested["id"]
    if isinstance(payload.get("id"), str):
        return payload["id"]
    return None


def _params(message):
    params = message.get("params") if isinstance(message, dict) else None
    return params if isinstance(params, dict) else {}


def _event_id(params, key, nested):
    value = params.get(key)
    if isinstance(value, str):
        return value
    obj = params.get(nested)
    if isinstance(obj, dict) and isinstance(obj.get("id"), str):
        return obj["id"]
    return None


def _relevant(message, thread, turn):
    if message.get("method") not in _TURN_EVENTS:
        return False
    params = _params(message)
    event_thread = _event_id(params, "threadId", "thread")
    if event_thread is not None and event_thread != thread:
        return False
    event_turn = _event_id(params, "turnId", "turn")
    if turn and event_turn is not None and event_turn != turn:
        return False
    return event_thread is not None or event_turn is not None


def _codex_error_info(error):
    if not isinstance(error, dict):
        return None
    info = error.get("codexErrorInfo")
    if isinstance(info, str) and info:
        return info
    if isinstance(info, dict) and len(info) == 1:
        key = next(iter(info))
        return key if isinstance(key, str) else None
    return None


def _image_outcome(item, remote):
    failure = item.get("failure")
    if isinstance(failure, dict) and failure.get("type") == "usageLimitExceeded":
        return {
            "status": QUOTA,
            "error": "The ChatGPT subscription image quota is exhausted.",
            "code": "quota",
            "remote": remote,
        }
    saved = item.get("savedPath")
    if not isinstance(saved, str) or not saved:
        return {
            "status": FAILED,
            "error": "Native image generation finished without a saved still.",
            "code": "missing_path",
            "remote": remote,
        }
    path = Path(saved)
    if not path.is_file():
        return {
            "status": FAILED,
            "error": "Native image generation named a still that is not a local file.",
            "code": "missing_file",
            "remote": remote,
        }
    return {
        "status": COMPLETE,
        "path": str(path),
        "remote": remote,
        "revised_prompt": item.get("revisedPrompt"),
    }


def _failed_turn(info, message, remote):
    if info in QUOTA_INFO:
        return {
            "status": QUOTA,
            "error": "The ChatGPT subscription image quota is exhausted.",
            "code": "quota",
            "remote": remote,
        }
    if info == "unauthorized":
        return {
            "status": AUTH,
            "error": "ChatGPT subscription login is required for native stills.",
            "code": "auth",
            "remote": remote,
        }
    classified, text = _classify_rpc_error(message or str(info or ""))
    if classified in {AUTH, QUOTA}:
        return {"status": classified, "error": text, "code": classified, "remote": remote}
    return {
        "status": FAILED,
        "error": redact(message) or "The native image turn failed.",
        "code": info if isinstance(info, str) else "turn",
        "remote": remote,
    }


def _terminal_turn(turn, remote):
    status = turn.get("status")
    error = turn.get("error") if isinstance(turn.get("error"), dict) else None
    info = _codex_error_info(error)
    message = str(error.get("message") or "") if error else ""
    if status == "completed":
        return {
            "status": FAILED,
            "error": "The native session returned text without a saved still. That is not image completion.",
            "code": "text_only",
            "remote": remote,
        }
    if status == "interrupted":
        return {
            "status": FAILED,
            "error": "The native image turn was interrupted before a saved still was available.",
            "code": "interrupted",
            "remote": remote,
        }
    if status == "failed":
        return _failed_turn(info, message, remote)
    return {
        "status": FAILED,
        "error": redact(message) or "The native image turn ended without a saved still.",
        "code": info if isinstance(info, str) else "turn",
        "remote": remote,
    }


def _event_outcome(message, thread, turn, remote):
    if not _relevant(message, thread, turn):
        return None
    method = message.get("method")
    if method == "item/completed":
        item = _item(message) or {}
        if item.get("type") == "imageGeneration":
            return _image_outcome(item, remote)
        return None
    if method == "turn/completed":
        turn_obj = _params(message).get("turn")
        if isinstance(turn_obj, dict):
            return _terminal_turn(turn_obj, remote)
    return None


def _call_on_submitted(on_submitted, remote):
    if on_submitted is None:
        return
    on_submitted(dict(remote))


def _uncertain(remote=None):
    payload = {
        "status": UNKNOWN,
        "error": "The native still submit outcome is unknown. Resume will not send it again.",
        "code": "unknown",
    }
    if remote:
        return {**payload, "remote": dict(remote)}
    return payload


def _failed_transport(exc):
    return {"status": FAILED, "error": redact(str(exc)), "code": "transport"}


def _rpc(session, method, params, code):
    message = session.wait(session.request(method, params))
    if message.get("error"):
        status, text = _classify_rpc_error(_rpc_error(message))
        return {"status": status, "error": text, "code": code}, message
    return None, message


def _initialize(session):
    error, _message = _rpc(
        session, "initialize", {"clientInfo": {"name": CLIENT_NAME, "version": __version__}}, "initialize"
    )
    if error:
        return error
    session.notify("initialized", {})
    return None


def _read_account(session):
    error, message = _rpc(session, "account/read", {}, "account")
    if error:
        return error
    status, text = _account_status(message.get("result"))
    if status:
        return {"status": status, "error": text, "code": "account"}
    return None


def _read_capabilities(session):
    error, message = _rpc(session, "modelProvider/capabilities/read", {}, "capabilities")
    if error:
        return error
    capabilities = message.get("result") if isinstance(message.get("result"), dict) else {}
    if capabilities.get("imageGeneration") is True:
        return None
    return {
        "status": UNSUPPORTED,
        "error": "This ChatGPT subscription session does not expose native image generation.",
        "code": "capabilities",
    }


def _read_inspection_gate(session):
    """Confirm the process override before any inspection thread. outputSchema is not this gate."""
    error, message = _rpc(session, "config/read", {"includeLayers": False}, "config")
    if error:
        return {
            "status": UNSUPPORTED,
            "error": "Inspection could not verify that image generation is disabled. Nothing was submitted.",
            "code": "inspection_gate",
            "media": False,
        }
    raw_result = message.get("result")
    result = raw_result if isinstance(raw_result, dict) else {}
    raw_config = result.get("config")
    config = raw_config if isinstance(raw_config, dict) else {}
    raw_features = config.get("features")
    features = raw_features if isinstance(raw_features, dict) else {}
    if features.get("image_generation") is not False:
        return {
            "status": UNSUPPORTED,
            "error": "Image generation is still available. Inspection was not submitted.",
            "code": "inspection_gate",
            "media": False,
        }
    return None


def _start_thread(session, workdir):
    error, message = _rpc(
        session,
        "thread/start",
        {
            "cwd": str(workdir.resolve()),
            "approvalPolicy": "never",
            "sandbox": "workspace-write",
            "modelProvider": OPENAI_PROVIDER,
            "allowProviderModelFallback": False,
        },
        "thread",
    )
    if error:
        return None, error
    thread = _nested_id(message, "thread")
    if thread:
        return thread, None
    return None, {"status": FAILED, "error": "The native session did not return a thread id.", "code": "thread"}


def _watch_turn(session, thread, turn):
    remote = {"threadId": thread, "turnId": turn}
    while True:
        message = session.read()
        outcome = _event_outcome(message, thread, turn, remote)
        if outcome is not None:
            return outcome


def _prepare_images(images):
    """Turn caller image records into localImage items. A name in text is not an item."""
    if images is None:
        return []
    if not isinstance(images, list):
        raise ValueError("Local image inputs must be a list of files.")
    prepared = []
    for image in images:
        if not isinstance(image, dict):
            raise ValueError("Each local image input must name a path.")
        raw = image.get("path")
        if not isinstance(raw, str) or not raw.strip() or "\0" in raw:
            raise ValueError("A local image input needs an actual file path.")
        path = Path(raw)
        if path.is_symlink() or not path.is_file():
            raise ValueError("A local image input is missing or is not a regular file.")
        item = {"type": "localImage", "path": str(path.resolve())}
        detail = image.get("detail")
        if detail is not None:
            if detail not in IMAGE_DETAILS:
                raise ValueError("Image detail must be auto, low, high, or original.")
            item["detail"] = detail
        prepared.append(item)
    return prepared


def _turn_input(prompt, images):
    if not isinstance(prompt, str) or not prompt.strip():
        raise ValueError("The native turn needs the instruction text.")
    return [{"type": "text", "text": prompt}, *images]


def _surprise_media(item, remote):
    """Account for generated media. Detecting it is not a no-generation gate and does not approve it."""
    saved = item.get("savedPath")
    path = None
    digest = None
    if isinstance(saved, str) and saved and "\0" not in saved:
        candidate = Path(saved)
        try:
            if candidate.is_file() and not candidate.is_symlink():
                data = candidate.read_bytes()
                path = str(candidate.resolve())
                digest = hashlib.sha256(data).hexdigest()
        except OSError:
            path = None
            digest = None
    return {
        "status": FAILED,
        "error": "Inspection observed generated media. The file is unreviewed and was not approved.",
        "code": "inspection_media",
        "remote": remote,
        "media": True,
        "generated": True,
        "path": path,
        "sha256": digest,
    }


def _watch_findings(session, thread, turn):
    """Read one inspection turn. A generated image stays a failed, unreviewed artifact."""
    remote = {"threadId": thread, "turnId": turn}
    texts = []
    while True:
        message = session.read()
        if not _relevant(message, thread, turn):
            continue
        method = message.get("method")
        if method == "item/completed":
            item = _item(message) or {}
            if item.get("type") == "imageGeneration":
                return _surprise_media(item, remote)
            if item.get("type") == "agentMessage" and isinstance(item.get("text"), str):
                texts.append(item["text"])
            continue
        if method != "turn/completed":
            continue
        turn_obj = _params(message).get("turn")
        if not isinstance(turn_obj, dict):
            return {
                "status": FAILED,
                "error": "The inspection turn ended without findings.",
                "code": "inspection_empty",
                "remote": remote,
                "media": False,
            }
        if turn_obj.get("status") != "completed":
            failed = _terminal_turn(turn_obj, remote)
            failed["media"] = False
            return failed
        if not texts:
            return {
                "status": FAILED,
                "error": "The inspection turn completed without findings for the attached images.",
                "code": "inspection_empty",
                "remote": remote,
                "media": False,
            }
        return {"status": COMPLETE, "findings": texts[-1], "remote": remote, "media": False}


def _run_turn(session, thread, turn):
    prompt = turn["prompt"]
    images = turn["images"]
    output_schema = turn["output_schema"]
    expect = turn["expect"]
    on_submitted = turn["on_submitted"]
    state = turn["state"]
    remote = {"threadId": thread}
    state["submitted"] = True
    state["remote"] = remote
    params = {"threadId": thread, "input": _turn_input(prompt, images), "approvalPolicy": "never"}
    if output_schema is not None:
        params["outputSchema"] = output_schema
    try:
        turn_req = session.request("turn/start", params)
    except (_TransportEndedError, _DeadlineExceededError, OSError, ValueError):
        _call_on_submitted(on_submitted, remote)
        return _uncertain(remote)
    _call_on_submitted(on_submitted, remote)
    turn_msg = session.wait(turn_req)
    if turn_msg.get("error"):
        status, text = _classify_rpc_error(_rpc_error(turn_msg))
        return {"status": status, "error": text, "code": "turn", "remote": remote}
    turn = _nested_id(turn_msg, "turn")
    if turn:
        remote = {"threadId": thread, "turnId": turn}
        state["remote"] = remote
        _call_on_submitted(on_submitted, remote)
    if expect == "findings":
        return _watch_findings(session, thread, turn)
    return _watch_turn(session, thread, turn)


def _run_session(session, workdir, turn):
    error = _initialize(session) or _read_account(session)
    if error:
        return error
    if turn["expect"] == "still":
        error = _read_capabilities(session)
        if error:
            return error
    else:
        error = _read_inspection_gate(session)
        if error:
            return error
    thread, error = _start_thread(session, workdir)
    if error:
        return error
    return _run_turn(session, thread, turn)


def _execute(prompt, workdir, options):
    images = options.get("images")
    output_schema = options.get("output_schema")
    expect = options.get("expect")
    timeout = options.get("timeout")
    on_submitted = options.get("on_submitted")
    workdir = Path(workdir)
    workdir.mkdir(parents=True, exist_ok=True)
    prepared = _prepare_images(images)
    if expect == "findings" and not prepared:
        return {
            "status": FAILED,
            "error": "Inspection needs the actual image files. Nothing was submitted.",
            "code": "missing_images",
            "media": False,
        }
    try:
        proc = _spawn(_command(inspection=expect == "findings"), workdir)
    except OSError as exc:
        return {"status": FAILED, "error": redact(str(exc)), "code": "spawn"}
    session = AppServer(proc, timeout=timeout)
    state = {"submitted": False, "remote": {}}
    try:
        return _run_session(
            session,
            workdir,
            {
                "prompt": prompt,
                "images": prepared,
                "output_schema": output_schema,
                "expect": expect,
                "on_submitted": on_submitted,
                "state": state,
            },
        )
    except (
        _TransportEndedError,
        _DeadlineExceededError,
        ValueError,
        OSError,
        json.JSONDecodeError,
        UnicodeDecodeError,
    ) as exc:
        if state["submitted"]:
            return _uncertain(state["remote"])
        return _failed_transport(exc)
    finally:
        session.close()


def generate_still(prompt, workdir, *, images=None, timeout: float = TIMEOUT_S, on_submitted=None):
    """Run one bounded native still. Image files travel as localImage items, never as a fallback provider."""
    return _execute(
        prompt,
        workdir,
        {
            "images": images,
            "output_schema": None,
            "expect": "still",
            "timeout": timeout,
            "on_submitted": on_submitted,
        },
    )


def inspect_images(prompt, workdir, images, *, timeout: float = TIMEOUT_S, on_submitted=None):
    """One bounded inspection turn. It must not be treated as media generation."""
    return _execute(
        prompt,
        workdir,
        {
            "images": images,
            "output_schema": INSPECTION_SCHEMA,
            "expect": "findings",
            "timeout": timeout,
            "on_submitted": on_submitted,
        },
    )
