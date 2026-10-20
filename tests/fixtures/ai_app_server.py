#!/usr/bin/env python3
"""Synthetic `codex app-server --stdio` fixture.

Speaks the installed JSONL contract (one JSON object per line, no jsonrpc key).
Rejects LSP Content-Length framing and requests sent before `initialized`.
"""

from __future__ import annotations

import hashlib
import json
import os
import struct
import sys
import time
import zlib
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


def _override_present():
    """True only when this process was launched with the process-only disable flag."""
    args = sys.argv
    return any(
        arg == "-c" and index + 1 < len(args) and args[index + 1] == "features.image_generation=false"
        for index, arg in enumerate(args)
    )


def _configured_image_generation(mode):
    """outputSchema does not change this. A missing override leaves generation available."""
    if mode == "gate_absent":
        return True
    if mode == "gate_unverified":
        return None
    if mode == "gate_refused":
        return "refused"
    return not _override_present()


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


def _chunk(tag, data):
    return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)


def _png_for(prompt):
    """2x2 RGB PNG whose pixels follow the prompt digest. An empty prompt keeps the fixed sample."""
    if not prompt:
        return PNG
    digest = hashlib.sha256(prompt.encode("utf-8")).digest()
    rows = []
    for y in range(2):
        row = b"\x00"
        for x in range(2):
            start = (y * 2 + x) * 3
            row += digest[start : start + 3]
        rows.append(row)
    ihdr = struct.pack(">IIBBBBB", 2, 2, 8, 2, 0, 0, 0)
    return (
        b"\x89PNG\r\n\x1a\n"
        + _chunk(b"IHDR", ihdr)
        + _chunk(b"IDAT", zlib.compress(b"".join(rows)))
        + _chunk(b"IEND", b"")
    )


def _prompt_text(params):
    raw = params.get("input") if isinstance(params, dict) else None
    if isinstance(raw, list) and raw and isinstance(raw[0], dict):
        return str(raw[0].get("text") or "")
    return ""


def _local_images(params):
    raw = params.get("input") if isinstance(params, dict) else None
    found = []
    if not isinstance(raw, list):
        return found
    for item in raw:
        if not isinstance(item, dict) or item.get("type") != "localImage":
            continue
        path = item.get("path")
        if not isinstance(path, str) or not path:
            found.append({"path": "", "sha256": "", "bytes": 0, "detail": item.get("detail"), "read": False})
            continue
        file = Path(path)
        data = file.read_bytes() if file.is_file() and not file.is_symlink() else b""
        found.append(
            {
                "path": path,
                "sha256": hashlib.sha256(data).hexdigest() if data else "",
                "bytes": len(data),
                "detail": item.get("detail"),
                "read": bool(data),
            }
        )
    return found


def _store_local_images(images):
    path = _cwd() / "local-images.json"
    previous = []
    if path.is_file():
        previous = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(previous, list):
            previous = []
    previous.append(images)
    path.write_text(json.dumps(previous), encoding="utf-8")


def _still_material(prompt, images):
    extra = "|".join(row["sha256"] for row in images if row.get("read"))
    return prompt if not extra else prompt + "\n" + extra


def _still_path(prompt="", images=None):
    path = _cwd() / "still.png"
    path.write_bytes(_png_for(_still_material(prompt, images or [])))
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


def _thread_result(cwd, model=None):
    return {
        "approvalPolicy": "never",
        "approvalsReviewer": "user",
        "cwd": cwd,
        "model": model or "gpt-5",
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


def _emit_turn(mode, prompt="", images=None):
    _notify("turn/started", {"threadId": THREAD_ID, "turn": {"id": TURN_ID, "items": [], "status": "inProgress"}})
    if mode == "irrelevant":
        _item_completed(_agent_text("Other thread text"), thread_id="thr_other", turn_id="turn_other")
        _turn_completed(thread_id="thr_other", turn_id="turn_other")
        _notify("remoteControl/status/changed", {"status": "disabled"})
        _item_completed(_agent_text("Ignore this other turn"), thread_id=THREAD_ID, turn_id="turn_other")
        _item_completed(_image_item(_still_path(prompt, images)))
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
        _item_completed(_image_item(_still_path(prompt, images)))
        _turn_completed()
        return
    _item_completed(_image_item(_still_path(prompt, images)))
    _turn_completed()


_MANIFEST_START = "INSPECTION_MANIFEST"
_MANIFEST_END = "END_INSPECTION_MANIFEST"


def _manifest_from_prompt(prompt):
    """Read the manifest the client supplied. Pixel bytes are not hashed here."""
    lines = str(prompt or "").splitlines()
    try:
        start = lines.index(_MANIFEST_START)
        end = lines.index(_MANIFEST_END)
    except ValueError:
        return []
    entries = []
    for line in lines[start + 1 : end]:
        text = line.strip()
        if not text:
            continue
        try:
            item = json.loads(text)
        except json.JSONDecodeError:
            continue
        if isinstance(item, dict):
            entries.append(item)
    return entries


def _synthetic_observation(entry):
    return {
        "id": entry.get("id"),
        "order": entry.get("order"),
        "role": entry.get("role"),
        "sha256": entry.get("sha256"),
        "observation": (f"Synthetic observation of {entry.get('id')} for role {entry.get('role')}. Not image content."),
    }


def _emit_inspection(prompt, mode="success"):
    """Bind clearly synthetic observations to the supplied manifest. Do not hash pixels."""
    observations = []
    for entry in _manifest_from_prompt(prompt):
        if not isinstance(entry.get("id"), str) or not isinstance(entry.get("role"), str):
            continue
        if not isinstance(entry.get("sha256"), str) or type(entry.get("order")) is not int:
            continue
        observations.append(_synthetic_observation(entry))
    if mode == "inspection_wrong_role" and observations:
        observations[0] = {**observations[0], "role": "unrelated-role"}
    elif mode == "inspection_wrong_hash" and observations:
        observations[0] = {**observations[0], "sha256": "0" * 64}
    elif mode == "inspection_missing" and observations:
        observations = observations[:-1]
    elif mode == "inspection_duplicate" and observations:
        observations.append(dict(observations[0]))
    text = json.dumps({"observations": observations}, separators=(",", ":"), sort_keys=True)
    _notify("turn/started", {"threadId": THREAD_ID, "turn": {"id": TURN_ID, "items": [], "status": "inProgress"}})
    _item_completed(_agent_text(text))
    _turn_completed(items=[_agent_text(text)])


def _handle_turn_start(ident, mode, prompt="", images=None):
    _count_turn_start()
    unknown = os.environ.get("GETBROLLS_AI_UNKNOWN_IF_PROMPT_CONTAINS") or ""
    failed = os.environ.get("GETBROLLS_AI_FAIL_IF_PROMPT_CONTAINS") or ""
    if mode == "lost_ack" or (unknown and unknown in prompt):
        sys.stdout.buffer.close()
        time.sleep(30)
        return
    if failed and failed in prompt:
        _result(ident, _turn_result())
        _emit_turn("text_only", prompt)
        return
    if mode == "early_image":
        _item_completed(_image_item(_still_path(prompt, images)))
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
    if mode == "slow_ack":
        time.sleep(1.2)
    _result(ident, _turn_result())
    _emit_turn(mode, prompt, images)


def _handle_config_read(ident, mode):
    state = _configured_image_generation(mode)
    if state == "refused":
        _error(ident, "config read refused")
        return
    features = {}
    if state is True or state is False:
        features["image_generation"] = state
    (_cwd() / "inspection-gate.json").write_text(
        json.dumps(
            {
                "image_generation": features.get("image_generation"),
                "turn_started": False,
                "override_present": _override_present(),
            }
        ),
        encoding="utf-8",
    )
    _result(ident, {"config": {"features": features}, "origins": []})


def _handle_inspection(ident, mode, prompt, images):
    _count_turn_start()
    unknown = os.environ.get("GETBROLLS_AI_UNKNOWN_IF_PROMPT_CONTAINS") or ""
    if mode == "lost_ack" or (unknown and unknown in prompt):
        sys.stdout.buffer.close()
        time.sleep(30)
        return
    if mode == "inspection_hostile":
        _result(ident, _turn_result())
        _emit_turn("success", prompt, images)
        return
    _result(ident, _turn_result())
    _emit_inspection(prompt, mode)


def _handle_turn(ident, mode, params):
    prompt = _prompt_text(params)
    images = _local_images(params)
    if images:
        _store_local_images(images)
    if isinstance(params, dict) and params.get("outputSchema") is not None:
        _handle_inspection(ident, mode, prompt, images)
        return
    _handle_turn_start(ident, mode, prompt, images)


def _handle_request(message, mode):
    ident = message.get("id")
    method = message.get("method")
    params = message.get("params") if isinstance(message.get("params"), dict) else {}
    if method == "config/read":
        _handle_config_read(ident, mode)
        return
    if method == "account/read":
        _result(ident, _account(mode))
        return
    if method == "modelProvider/capabilities/read":
        _result(ident, _capabilities(mode))
        return
    if method == "thread/start":
        cwd = params.get("cwd") or str(_cwd().resolve())
        model = None if mode == "model_mismatch" else params.get("model")
        result = ["malformed thread response"] if mode == "model_malformed" else _thread_result(cwd, model)
        _result(ident, result)
        _notify("thread/started", {"thread": {"id": THREAD_ID}})
        if mode in {"blocked_write", "hang_ack"}:
            time.sleep(60)
        return
    if method == "turn/start":
        _handle_turn(ident, mode, params)
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
    (_cwd() / "argv.json").write_text(json.dumps(sys.argv), encoding="utf-8")
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
