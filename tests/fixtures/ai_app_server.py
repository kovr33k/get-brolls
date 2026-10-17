#!/usr/bin/env python3
"""Synthetic `codex app-server --stdio` fixture.

Speaks the installed JSONL contract (one JSON object per line, no jsonrpc key).
Rejects LSP Content-Length framing and requests sent before `initialized`.
"""

from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

MAX_LINE = 1_048_576
THREAD_ID = "thr_getbrolls_test"
TURN_ID = "turn_getbrolls_test"
PNG = bytes.fromhex(
    "89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c489"
    "0000000a49444154789c63000100000500010d0a2db40000000049454e44ae426082"
)


def _cwd():
    return Path.cwd()


def _write(payload):
    sys.stdout.buffer.write(json.dumps(payload, ensure_ascii=False, allow_nan=False).encode("utf-8") + b"\n")
    sys.stdout.buffer.flush()


def _error(ident, message, code=1):
    _write({"id": ident, "error": {"code": code, "message": message}})


def _result(ident, result):
    _write({"id": ident, "result": result})


def _notify(method, params):
    _write({"method": method, "params": params})


def _record(message):
    path = _cwd() / "received.jsonl"
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(message, ensure_ascii=False) + "\n")


def _count_turn_start():
    path = _cwd() / "turn-start-count.txt"
    n = int(path.read_text(encoding="utf-8") or "0") if path.is_file() else 0
    path.write_text(str(n + 1), encoding="utf-8")
    return n + 1


def _read_message():
    buf = bytearray()
    stdin = sys.stdin.buffer
    while True:
        chunk = stdin.read(1)
        if not chunk:
            return None
        if chunk == b"\n":
            break
        buf += chunk
        if buf.lower().startswith(b"content-length:"):
            sys.stderr.write("LSP Content-Length framing is not the app-server stdio contract.\n")
            sys.stderr.flush()
            raise SystemExit(2)
        if len(buf) > MAX_LINE:
            sys.stderr.write("Incoming JSONL line exceeds the bounded size.\n")
            sys.stderr.flush()
            raise SystemExit(2)
    line = bytes(buf).rstrip(b"\r")
    if not line.strip():
        return _read_message()
    data = json.loads(line.decode("utf-8"))
    if not isinstance(data, dict):
        raise ValueError("Client sent a non-object JSONL message.")
    _record(data)
    return data


def _still_path():
    path = _cwd() / "still.png"
    path.write_bytes(PNG)
    return str(path.resolve())


def _account(mode):
    if mode == "auth":
        return {"account": None, "requiresOpenaiAuth": True}
    if mode == "apikey":
        return {"account": {"type": "apiKey"}, "requiresOpenaiAuth": True}
    return {
        "account": {"type": "chatgpt", "email": "pilot@example.com", "planType": "plus"},
        "requiresOpenaiAuth": True,
    }


def _capabilities(mode):
    return {
        "imageGeneration": mode != "unsupported",
        "namespaceTools": False,
        "webSearch": False,
    }


def _thread_result(cwd):
    return {
        "approvalPolicy": "never",
        "approvalsReviewer": "user",
        "cwd": cwd,
        "model": "gpt-5",
        "modelProvider": "openai",
        "sandbox": {"type": "workspaceWrite", "writableRoots": [cwd], "networkAccess": False},
        "thread": {
            "id": THREAD_ID,
            "cliVersion": "get-brolls-fixture",
            "createdAt": 1,
            "updatedAt": 1,
            "cwd": cwd,
            "ephemeral": False,
            "modelProvider": "openai",
            "preview": "",
            "projectId": None,
            "sessionId": THREAD_ID,
            "source": "cli",
            "status": {"type": "idle"},
            "turns": [],
        },
    }


def _turn_result():
    return {"turn": {"id": TURN_ID, "items": [], "status": "inProgress"}}


def _item_completed(item, thread_id=THREAD_ID, turn_id=TURN_ID):
    _notify(
        "item/completed",
        {"completedAtMs": 1, "item": item, "threadId": thread_id, "turnId": turn_id},
    )


def _agent_text(text="Working on the still."):
    return {"id": "item_text", "type": "agentMessage", "text": text}


def _image_item(path=None, failure=None):
    item = {
        "id": "item_image",
        "type": "imageGeneration",
        "result": "image",
        "status": "failed" if failure else "completed",
        "revisedPrompt": "A still of an empty reservoir, no lettering.",
    }
    if path is not None:
        item["savedPath"] = path
    if failure is not None:
        item["failure"] = failure
    return item


def _turn_completed(thread_id=THREAD_ID, turn_id=TURN_ID, items=None, status="completed", error=None):
    turn = {"id": turn_id, "items": items or [], "status": status}
    if error is not None:
        turn["error"] = error
    _notify("turn/completed", {"threadId": thread_id, "turn": turn})


def _emit_turn(mode):
    _notify("turn/started", {"threadId": THREAD_ID, "turn": {"id": TURN_ID, "items": [], "status": "inProgress"}})
    if mode == "irrelevant":
        _item_completed(_agent_text("Other thread text"), thread_id="thr_other", turn_id="turn_other")
        _turn_completed(thread_id="thr_other", turn_id="turn_other")
        _notify("remoteControl/status/changed", {"status": "disabled"})
        _item_completed(_agent_text("Ignore this other turn"), thread_id=THREAD_ID, turn_id="turn_other")
        _item_completed(_image_item(_still_path()))
        return
    if mode == "text_only":
        _item_completed(_agent_text())
        _turn_completed(items=[_agent_text()])
        return
    if mode == "quota":
        _item_completed(_agent_text())
        _item_completed(_image_item(failure={"type": "usageLimitExceeded", "limitId": "images"}))
        _turn_completed()
        return
    if mode == "missing_file":
        _item_completed(_image_item(path=str((_cwd() / "missing.png").resolve())))
        return
    if mode in {"success", "text_then_image"}:
        if mode == "text_then_image":
            _item_completed(_agent_text())
        _item_completed(_image_item(_still_path()))
        _turn_completed()
        return
    _item_completed(_image_item(_still_path()))
    _turn_completed()


def _handle_turn_start(ident, mode):
    _count_turn_start()
    if mode == "lost_ack":
        sys.stdout.buffer.close()
        time.sleep(30)
        return
    if mode == "early_image":
        _item_completed(_image_item(_still_path()))
        _result(ident, _turn_result())
        _turn_completed()
        return
    if mode == "turn_quota":
        _result(ident, _turn_result())
        _turn_completed(status="failed", error={"message": "usage limit", "codexErrorInfo": "usageLimitExceeded"})
        return
    if mode == "turn_auth":
        _result(ident, _turn_result())
        _turn_completed(status="failed", error={"message": "unauthorized", "codexErrorInfo": "unauthorized"})
        return
    if mode == "interrupted":
        _result(ident, _turn_result())
        _turn_completed(status="interrupted")
        return
    _result(ident, _turn_result())
    _emit_turn(mode)


def _handle_request(message, mode):
    ident = message.get("id")
    method = message.get("method")
    params = message.get("params") if isinstance(message.get("params"), dict) else {}
    if method == "account/read":
        _result(ident, _account(mode))
        return
    if method == "modelProvider/capabilities/read":
        _result(ident, _capabilities(mode))
        return
    if method == "thread/start":
        cwd = params.get("cwd") or str(_cwd().resolve())
        _result(ident, _thread_result(cwd))
        _notify("thread/started", {"thread": {"id": THREAD_ID}})
        if mode in {"blocked_write", "hang_ack"}:
            time.sleep(60)
        return
    if method == "turn/start":
        _handle_turn_start(ident, mode)
        return
    _error(ident, f"Unexpected method {method}.")


def _not_initialized(ident, detail):
    if ident is not None:
        _error(ident, "Not initialized")
    else:
        sys.stderr.write(detail + "\n")
        sys.stderr.flush()
    return 2


def _corrupt_after_initialize(mode):
    if mode == "malformed":
        sys.stdout.buffer.write(b"this is not json\n")
        sys.stdout.buffer.flush()
        time.sleep(30)
        return 2
    if mode == "oversized":
        sys.stdout.buffer.write(b"x" * (MAX_LINE + 64) + b"\n")
        sys.stdout.buffer.flush()
        time.sleep(30)
        return 2
    return None


def _accept_initialize(message, mode):
    ident = message.get("id")
    if message.get("method") != "initialize" or ident is None:
        return _not_initialized(ident, "First client message must be initialize.")
    _result(
        ident,
        {
            "userAgent": "get-brolls-fixture",
            "platformFamily": "windows" if os.name == "nt" else "unix",
            "platformOs": "windows" if os.name == "nt" else "linux",
            "codexHome": str(_cwd().resolve()),
        },
    )
    _notify("remoteControl/status/changed", {"status": "disabled"})
    return _corrupt_after_initialize(mode)


def _next_message():
    try:
        return _read_message()
    except json.JSONDecodeError:
        sys.stderr.write("Client sent malformed JSONL.\n")
        sys.stderr.flush()
        raise SystemExit(2) from None


def main():
    mode = os.environ.get("GETBROLLS_AI_FIXTURE", "success")
    (_cwd() / "app-server.pid").write_text(str(os.getpid()), encoding="utf-8")
    (_cwd() / "child-env.json").write_text(
        json.dumps({name: name in os.environ for name in ("OPENAI_API_KEY", "OPENROUTER_API_KEY")}),
        encoding="utf-8",
    )
    if mode == "hung":
        time.sleep(3600)
        return 0

    saw_initialize = False
    initialized = False
    while True:
        message = _next_message()
        if message is None:
            return 0
        if not saw_initialize:
            saw_initialize = True
            code = _accept_initialize(message, mode)
            if code is not None:
                return code
            continue
        if not initialized:
            if message.get("method") == "initialized" and message.get("id") is None:
                initialized = True
                continue
            return _not_initialized(message.get("id"), "initialized notification is required before other requests.")
        if message.get("method") == "initialized" or message.get("id") is None:
            continue
        _handle_request(message, mode)
        if mode == "lost_ack" and message.get("method") == "turn/start":
            return 0


if __name__ == "__main__":
    raise SystemExit(main())
