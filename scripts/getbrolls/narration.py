"""Complete-recording Inworld transcription.

Narration records are explicit project state, never discovered candidates.
Only narration-analyze and narration-resume contact the provider.
"""

from __future__ import annotations

import contextlib
import hashlib
import html
import ipaddress
import json
import math
import os
import re
import secrets
import socket
import stat
import struct
import urllib.error
import urllib.parse
import urllib.request
import wave
from pathlib import Path

from .http import ProviderError
from .ledger import digest
from .models import now
from .runtime import redact

NARRATION_SCHEMA = 1
PROVIDER = "inworld"
MODEL_ID = "inworld/inworld-stt-1"
AUDIO_ENCODING = "AUTO_DETECT"
PRODUCTION_API = "https://api.inworld.ai"
STT_PATH = "/stt/v1/transcribe:async"
SYNC_STT_PATH = "/stt/v1/transcribe"
LRO_PREFIX = "/lro/v1alpha/"
MAX_AUDIO_BYTES = 512 * 1024 * 1024
# Leave ample room for multipart config inside the synchronous request limit.
MAX_SYNC_AUDIO_BYTES = 8 * 1024 * 1024
MAX_JSON_BYTES = 8 * 1024 * 1024
POST_TIMEOUT_S = 60
GET_TIMEOUT_S = 30
HTTP_OK = 200
HTTP_CLIENT_MIN = 400
HTTP_SERVER_MIN = 500
LANGUAGE_MAX = 32
WAV_RIFF_HEADER = 12
WAV_CHUNK_HEADER = 8
WAV_FMT_MIN = 16
WAV_WORD_ALIGN = 2
WAV_FORM_TAG_BYTES = 4
TEMP_SUFFIX = ".tmp"
_EXCL_TEMP_FLAGS = os.O_CREAT | os.O_EXCL | os.O_WRONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0)
STAGE_HEAD = 0
STAGE_FILE_HEADER = 1
STAGE_FILE = 2
STAGE_TAIL = 3
COPY_CHUNK = 1024 * 1024
ID_RE = re.compile(r"[A-Za-z0-9_-]{1,80}$")
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
LANGUAGE_RE = re.compile(r"^[A-Za-z]{2,3}(?:-[A-Za-z0-9]{2,8})*$")
OPERATION_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._~/-]{0,509}$")
MODEL_META_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._/-]{0,79}$")
_WINDOWS_RESERVED = re.compile(r"^(?:con|prn|aux|nul|com[1-9]|lpt[1-9])$", re.IGNORECASE)
_CONTROL = re.compile(r"[\x00-\x1f\x7f]")
HEADERED = frozenset({"wav", "wave", "flac", "mp3", "m4a", "mp4", "ogg", "oga"})
RESULT_HOSTS = frozenset({"storage.googleapis.com", "storage.cloud.google.com"})
RESULT_HOST_SUFFIXES = (".storage.googleapis.com",)
PRIVATE_AUDIO_PREFIX = "narration/private/audio/"
RESULT_PREFIX = "narration/results/"
RECEIPT_PREFIX = "narration/private/receipts/"
PRESERVE = "Invalid narration records. Preserve the project files and restore a valid copy; history was not reset."
TEST_MODE_ENV = "GETBROLLS_INWORLD_STT_TEST_MODE"
TEST_BASE_ENV = "GETBROLLS_INWORLD_STT_TEST_BASE"
TEST_CRASH_ENV = "GETBROLLS_INWORLD_STT_TEST_CRASH"
TEST_TIMEOUT_ENV = "GETBROLLS_INWORLD_STT_TEST_TIMEOUT"
LOOPBACK = frozenset({"127.0.0.1", "localhost", "::1"})

STATES = frozenset({"intent", "pending", "completed", "failed", "unknown"})
SUBMIT_OUTCOMES = frozenset({"not_sent", "accepted", "rejected", "unknown"})
IN_FLIGHT = frozenset({"intent", "pending", "unknown"})
USAGE_KEYS = ("audioDurationMs", "modelId", "characters")
SECRET_MARKERS = (
    "http://",
    "https://",
    "authorization",
    "basic ",
    "inworld_api",
    "x-goog-",
    "signature=",
    "://",
)

CONTROLLED = {
    "RECORDING_INVALID": "The narration recording is missing, empty, unreadable or not a regular file.",
    "RECORDING_TOO_LARGE": "The narration recording exceeds the 512 MB transcription job limit.",
    "SYNC_RECORDING_TOO_LARGE": "Synchronous transcription accepts complete recordings up to 8 MiB. No audio was sent.",
    "RECORDING_UNSUPPORTED": "The narration recording is not a supported headered audio encoding.",
    "CREDENTIAL_MISSING": "INWORLD_API_KEY is not set. Use the already formatted Basic value; collection search does not need it.",
    "ANALYSIS_NOT_FOUND": "Unknown narration analysis identity. Use an id saved by narration-analyze.",
    "ALREADY_IN_FLIGHT": "This recording and provider settings already have a saved attempt. Use narration-resume; a repeated command does not resubmit.",
    "ALREADY_FAILED": "This analysis already failed for the same recording and settings. Pass a new --analysis for a separate attempt. There is no exactly-once billing promise.",
    "ALREADY_COMPLETED": "An intact completed analysis already exists for this recording and provider settings; it was reused without a provider call.",
    "FINGERPRINT_CHANGED": "Recording bytes or provider settings differ from the saved analysis. Start a separate analysis; completed history is not overwritten.",
    "SUBMIT_REJECTED": "Inworld rejected the transcription request. The attempt is recorded as failed and was not retried.",
    "SUBMIT_UNKNOWN": "The transcription submit outcome is unknown. Resume the saved analysis; a repeated command does not POST again.",
    "OPERATION_INVALID": "The provider returned an invalid operation handle. The submit outcome is unknown and was not retried.",
    "PROVIDER_JOB_ERROR": "The transcription job finished with a provider error. Recognized text is kept when it was already saved.",
    "RESULT_MISSING": "The completed operation has no transcript result. Resume does not submit a new job.",
    "RESULT_EXPIRED": "The transcript result is no longer available. Resume does not submit a new job because a signed link expired.",
    "RESULT_INVALID": "The transcript payload is invalid. Original recognized text is kept when present; timing stays unresolved.",
    "RESULT_DESTINATION_REFUSED": "The transcript result destination is not documented public storage, or it used a redirect or credentials.",
    "ARTIFACT_CORRUPT": "The saved transcript artifact is missing, corrupt or does not match its hash. Resume a known operation; this does not POST.",
    "TIMING_UNRESOLVED": "Recognized text is saved, but word timing is missing or invalid.",
    "STORAGE_REFUSED": (
        "Narration storage resolved outside the project or through a symlink or junction. "
        "Existing files were preserved and the provider was not called."
    ),
}


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: ARG002, PLR0913, PLR0917
        raise ProviderError(CONTROLLED["RESULT_DESTINATION_REFUSED"])


def _is_int(value):
    return type(value) is int


def _is_number(value):
    return type(value) in (int, float) and not isinstance(value, bool) and math.isfinite(value)


def _as_dict(value):
    return value if isinstance(value, dict) else {}


def _valid_id(value):
    return isinstance(value, str) and bool(ID_RE.fullmatch(value)) and not _WINDOWS_RESERVED.fullmatch(value)


def _sha256(value):
    return isinstance(value, str) and bool(SHA256_RE.fullmatch(value))


def _payload_hash(payload):
    encoded = json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _esc(value):
    return html.escape("" if value is None else str(value), quote=True)


def _relative(value, prefixes):
    if not isinstance(value, str) or not value or _CONTROL.search(value):
        raise ValueError
    if "\\" in value or value.startswith(("/", "~")) or ":" in value:
        raise ValueError
    path = Path(value)
    if ".." in path.parts or path.is_absolute() or not value.startswith(prefixes):
        raise ValueError
    return value


def _secret_text(value):
    if not isinstance(value, str) or not value:
        return False
    lowered = value.lower()
    return any(marker in lowered for marker in SECRET_MARKERS)


def _public_error(code, extra=None):
    message = CONTROLLED[code]
    if extra:
        message = redact(f"{message} {extra}", limit=400)
        if _secret_text(message):
            message = CONTROLLED[code]
    return {"code": code, "message": message}


def _test_mode():
    return os.environ.get(TEST_MODE_ENV) == "1"


def _test_timeout(default):
    if not _test_mode():
        return default
    raw = (os.environ.get(TEST_TIMEOUT_ENV) or "").strip()
    if not raw:
        return default
    try:
        value = float(raw)
    except ValueError:
        return default
    if not math.isfinite(value) or value <= 0:
        return default
    return value


def _loopback_origin(raw):
    parsed = urllib.parse.urlsplit((raw or "").strip())
    host = (parsed.hostname or "").lower()
    if parsed.scheme != "http" or host not in LOOPBACK:
        raise ValueError("Inworld test transport is explicit loopback HTTP only.")
    if parsed.path not in ("", "/") or parsed.query or parsed.fragment or parsed.username or parsed.password:
        raise ValueError("Inworld test transport must be a loopback origin without path, query or credentials.")
    if parsed.port is None:
        raise ValueError("Inworld test transport must include an explicit loopback port.")
    hostname = parsed.hostname
    if hostname == "::1":
        return f"http://[{hostname}]:{parsed.port}"
    return f"http://{hostname}:{parsed.port}"


def api_base():
    if not _test_mode():
        return PRODUCTION_API
    raw = os.environ.get(TEST_BASE_ENV)
    if not raw:
        raise ValueError("Inworld test transport is enabled without a loopback base.")
    return _loopback_origin(raw)


def _test_crash(point):
    return _test_mode() and os.environ.get(TEST_CRASH_ENV) == point


def _api_key():
    value = os.environ.get("INWORLD_API_KEY")
    if not isinstance(value, str) or not value.strip():
        return None
    if _CONTROL.search(value) or "\n" in value or "\r" in value:
        raise ValueError(CONTROLLED["CREDENTIAL_MISSING"])
    return value.strip()


def _require_key():
    key = _api_key()
    if key is None:
        raise ValueError(CONTROLLED["CREDENTIAL_MISSING"])
    return key


def analysis_config(language=None):
    if language is None or language == "":
        hint = None
    else:
        if not isinstance(language, str) or not LANGUAGE_RE.fullmatch(language) or len(language) > LANGUAGE_MAX:
            raise ValueError("Optional --language must be a short language tag such as en or pt-BR.")
        hint = language
    return {
        "provider": PROVIDER,
        "model_id": MODEL_ID,
        "audio_encoding": AUDIO_ENCODING,
        "include_word_timestamps": True,
        "language": hint,
    }


def _transcribe_config(config):
    payload = {
        "modelId": config["model_id"],
        "audioEncoding": config["audio_encoding"],
        "includeWordTimestamps": True,
    }
    if config.get("language"):
        payload["language"] = config["language"]
    return payload


def input_fingerprint(audio_sha256, config):
    return _payload_hash({"audio": audio_sha256, "config": config})


def empty_narration():
    return {"schema_version": NARRATION_SCHEMA, "recordings": {}, "analyses": {}, "current_analysis": None}


def ensure_narration(data):
    if "narration" not in data:
        data["narration"] = empty_narration()
    return data["narration"]


def validate_narration(data):
    if "narration" not in data:
        return data
    try:
        _validate_payload(data.get("narration"))
    except (ValueError, TypeError, KeyError):
        raise ValueError(PRESERVE) from None
    return data


def _validate_payload(narration):
    if not isinstance(narration, dict) or not _is_int(narration.get("schema_version")):
        raise ValueError
    if narration["schema_version"] != NARRATION_SCHEMA:
        raise ValueError
    recordings = narration.get("recordings")
    analyses = narration.get("analyses")
    if not isinstance(recordings, dict) or not isinstance(analyses, dict):
        raise ValueError
    for rec_id, rec in recordings.items():
        _validate_recording_record(rec_id, rec)
    for analysis_id, analysis in analyses.items():
        _validate_analysis_record(analysis_id, analysis, recordings)
    _validate_retries(analyses)
    current = narration.get("current_analysis")
    if current is not None and (not isinstance(current, str) or current not in analyses):
        raise ValueError


def _validate_recording_record(rec_id, rec):
    if not _valid_id(rec_id) or not isinstance(rec, dict):
        raise ValueError
    if rec.get("id") != rec_id:
        raise ValueError
    if not _sha256(rec.get("sha256")):
        raise ValueError
    if not _is_int(rec.get("bytes")) or rec["bytes"] <= 0 or rec["bytes"] > MAX_AUDIO_BYTES:
        raise ValueError
    if not _is_number(rec.get("duration_s")) or rec["duration_s"] <= 0:
        raise ValueError
    if rec.get("format") not in HEADERED:
        raise ValueError
    if not isinstance(rec.get("codec"), str) or not rec["codec"] or _CONTROL.search(rec["codec"]):
        raise ValueError
    if not _is_int(rec.get("channels")) or rec["channels"] < 1:
        raise ValueError
    if not _is_int(rec.get("sample_rate")) or rec["sample_rate"] < 1:
        raise ValueError
    _relative(rec.get("snapshot"), PRIVATE_AUDIO_PREFIX)


def _validate_analysis_config(analysis):
    config = analysis.get("config")
    if not isinstance(config, dict):
        raise ValueError
    expected = analysis_config(config.get("language"))
    if config != expected or _payload_hash(config) != analysis["config_fingerprint"]:
        raise ValueError
    transport = analysis.get("transport", "async")
    if transport not in ("async", "sync") or (transport == "sync" and analysis.get("operation_name") is not None):
        raise ValueError


def _validate_analysis_error(error):
    if error is None:
        return
    if not isinstance(error, dict) or not isinstance(error.get("code"), str):
        raise ValueError
    if not isinstance(error.get("message"), str):
        raise ValueError
    lowered = error["message"].lower()
    if "http://" in lowered or "https://" in lowered:
        raise ValueError


def _validate_analysis_record(analysis_id, analysis, recordings):
    if not _valid_id(analysis_id) or not isinstance(analysis, dict):
        raise ValueError
    if analysis.get("id") != analysis_id:
        raise ValueError
    recording_id = analysis.get("recording_id")
    if recording_id not in recordings:
        raise ValueError
    if analysis.get("state") not in STATES:
        raise ValueError
    if analysis.get("submit_outcome") not in SUBMIT_OUTCOMES:
        raise ValueError
    if not _sha256(analysis.get("audio_fingerprint")) or not _sha256(analysis.get("input_fingerprint")):
        raise ValueError
    if not _sha256(analysis.get("config_fingerprint")):
        raise ValueError
    _validate_analysis_config(analysis)
    name = analysis.get("operation_name")
    if name is not None:
        _operation_name(name)
    _validate_analysis_error(analysis.get("error"))
    result = analysis.get("result")
    if result is not None:
        _validate_result(result, recordings[recording_id].get("duration_s"))


def _retry_scope(source, analysis_id, transport):
    return {
        "retry_of": source["id"],
        "analysis_id": analysis_id,
        "recording_id": source["recording_id"],
        "audio_sha256": source["audio_fingerprint"],
        "input_fingerprint": source["input_fingerprint"],
        "config": source["config"],
        "transport": transport,
        "posts": 1,
        "prior_attempt_may_have_been_charged": True,
    }


def _retry_text(value, limit):
    if not isinstance(value, str) or not value.strip() or len(value) > limit or _CONTROL.search(value):
        raise ValueError("The retry needs a bounded reviewer and explicit authorization statement.")
    return value.strip()


def _validate_retries(analyses):
    consumed = set()
    for analysis in analyses.values():
        retry = analysis.get("retry")
        if retry is None:
            continue
        if not isinstance(retry, dict):
            raise ValueError
        source = analyses.get(retry.get("source"))
        if not isinstance(source, dict) or source.get("retry") is not None or source["id"] == analysis["id"]:
            raise ValueError
        for key in ("recording_id", "audio_fingerprint", "input_fingerprint", "config_fingerprint", "config"):
            if source[key] != analysis[key]:
                raise ValueError
        scope = _retry_scope(source, analysis["id"], analysis.get("transport", "async"))
        if retry.get("fingerprint") != _payload_hash(scope) or analysis["input_fingerprint"] in consumed:
            raise ValueError
        _retry_text(retry.get("by"), 200)
        _retry_text(retry.get("statement"), 4000)
        _retry_text(retry.get("at"), 100)
        consumed.add(analysis["input_fingerprint"])


def _validate_result(result, duration_s=None):
    if not isinstance(result, dict):
        raise ValueError
    if "transcript" not in result or not isinstance(result.get("transcript"), str):
        raise ValueError
    if result.get("timing_resolved") not in (True, False):
        raise ValueError
    if "confidence" in result:
        raise ValueError
    _relative(result.get("artifact"), RESULT_PREFIX)
    if not _sha256(result.get("artifact_sha256")):
        raise ValueError
    words = result.get("words")
    if not isinstance(words, list):
        raise ValueError
    for word in words:
        _validate_stored_word(word)
    if result["timing_resolved"] and not _words_timing_ok(words, duration_s):
        raise ValueError
    _validate_usage(result.get("usage"))
    _validate_result_language(result.get("language"))
    if result.get("result_uri") is not None or result.get("authorization") is not None:
        raise ValueError


def _validate_stored_word(word):
    if not isinstance(word, dict):
        raise ValueError
    if not isinstance(word.get("word"), str):
        raise ValueError
    if "confidence" in word:
        raise ValueError
    for key in ("start_ms", "end_ms"):
        if not _is_number(word.get(key)) or word[key] < 0:
            raise ValueError
    if word["start_ms"] > word["end_ms"]:
        raise ValueError
    if not _is_int(word.get("segment")) or word["segment"] < 0:
        raise ValueError


def _safe_usage_value(key, value):
    if key == "audioDurationMs":
        return _is_number(value) and value >= 0
    if key == "characters":
        return _is_int(value) and value >= 0
    if key == "modelId":
        return (
            isinstance(value, str)
            and bool(MODEL_META_RE.fullmatch(value))
            and not _CONTROL.search(value)
            and not _secret_text(value)
        )
    return False


def _validate_usage(usage):
    if usage is None:
        return
    if not isinstance(usage, dict):
        raise ValueError
    for key, value in usage.items():
        if key not in USAGE_KEYS or not _safe_usage_value(key, value):
            raise ValueError


def _validate_result_language(language):
    if language is None:
        return
    if not isinstance(language, str) or not language or _CONTROL.search(language):
        raise ValueError
    if len(language) > LANGUAGE_MAX or _secret_text(language):
        raise ValueError


def _timing_limit_ms(duration_s):
    if not _is_number(duration_s) or duration_s <= 0:
        return None
    limit = duration_s * 1000
    if not math.isfinite(limit) or limit <= 0:
        return None
    return limit


def _words_timing_ok(words, duration_s):
    if not words:
        return False
    limit = _timing_limit_ms(duration_s)
    if limit is None:
        return False
    previous_start = None
    previous_end = None
    for word in words:
        start = word["start_ms"]
        end = word["end_ms"]
        if start > end or start > limit or end > limit:
            return False
        if previous_start is not None and start < previous_start:
            return False
        if previous_end is not None and end < previous_end:
            return False
        previous_start = start
        previous_end = end
    return True


def _operation_name(value):
    if not isinstance(value, str) or not OPERATION_RE.fullmatch(value):
        raise ValueError(CONTROLLED["OPERATION_INVALID"])
    if ".." in value or value.startswith("/") or "://" in value or "?" in value or "#" in value or "\\" in value:
        raise ValueError(CONTROLLED["OPERATION_INVALID"])
    if "/operations/" not in value:
        raise ValueError(CONTROLLED["OPERATION_INVALID"])
    return value


def _u32(buffer, offset=0):
    return struct.unpack_from("<I", buffer, offset)[0]


def _next_wav_chunk(handle, offset, limit, size):
    handle.seek(offset)
    chunk = handle.read(WAV_CHUNK_HEADER)
    if len(chunk) != WAV_CHUNK_HEADER:
        raise ValueError
    payload = _u32(chunk, 4)
    data_end = offset + WAV_CHUNK_HEADER + payload
    if data_end > limit or data_end > size:
        raise ValueError
    if payload % WAV_WORD_ALIGN and data_end < limit:
        if data_end + 1 > limit or data_end + 1 > size:
            raise ValueError
        return chunk[:4], payload, data_end + 1
    return chunk[:4], payload, data_end


def _wav_data_bytes(path, size):
    if size < WAV_RIFF_HEADER + WAV_CHUNK_HEADER:
        raise ValueError
    with path.open("rb") as handle:
        header = handle.read(WAV_RIFF_HEADER)
        if len(header) != WAV_RIFF_HEADER or header[:4] != b"RIFF" or header[8:12] != b"WAVE":
            raise ValueError
        declared = _u32(header, 4)
        limit = 8 + declared
        if declared < WAV_FORM_TAG_BYTES or limit > size:
            raise ValueError
        offset = WAV_RIFF_HEADER
        saw_fmt = False
        data_bytes = 0
        while offset + WAV_CHUNK_HEADER <= limit:
            name, payload, offset = _next_wav_chunk(handle, offset, limit, size)
            if name == b"fmt ":
                if payload < WAV_FMT_MIN:
                    raise ValueError
                saw_fmt = True
            elif name == b"data":
                data_bytes = payload
        if not saw_fmt or data_bytes < 1:
            raise ValueError
        return data_bytes


def _wav_identity(path, size):
    try:
        data_bytes = _wav_data_bytes(path, size)
        with wave.open(str(path), "rb") as handle:
            channels = handle.getnchannels()
            rate = handle.getframerate()
            width = handle.getsampwidth()
    except (OSError, wave.Error, ValueError, struct.error):
        raise ValueError(CONTROLLED["RECORDING_UNSUPPORTED"]) from None
    frame_bytes = channels * width
    if channels < 1 or rate < 1 or width < 1 or frame_bytes < 1:
        raise ValueError(CONTROLLED["RECORDING_UNSUPPORTED"])
    if data_bytes % frame_bytes:
        raise ValueError(CONTROLLED["RECORDING_UNSUPPORTED"])
    frames = data_bytes // frame_bytes
    if frames < 1:
        raise ValueError(CONTROLLED["RECORDING_UNSUPPORTED"])
    duration = frames / float(rate)
    if not math.isfinite(duration) or duration <= 0:
        raise ValueError(CONTROLLED["RECORDING_UNSUPPORTED"])
    return {
        "format": "wav",
        "codec": f"pcm_s{width * 8}le",
        "channels": channels,
        "sample_rate": rate,
        "duration_s": duration,
    }


def validate_recording(path):
    path = Path(path)
    if not path.is_file():
        raise ValueError(CONTROLLED["RECORDING_INVALID"])
    try:
        size = path.stat().st_size
    except OSError as exc:
        raise ValueError(CONTROLLED["RECORDING_INVALID"]) from exc
    if size <= 0:
        raise ValueError(CONTROLLED["RECORDING_INVALID"])
    if size > MAX_AUDIO_BYTES:
        raise ValueError(CONTROLLED["RECORDING_TOO_LARGE"])
    identity = _wav_identity(path, size)
    sha = digest(path)
    return {
        "path": path,
        "bytes": size,
        "sha256": sha,
        "id": "rec-" + sha[:16],
        **identity,
    }


def _snapshot_rel(recording):
    return PRIVATE_AUDIO_PREFIX + recording["id"] + ".wav"


def _is_reparse(path):
    path = Path(path)
    try:
        info = os.lstat(path)
    except FileNotFoundError:
        return False
    except OSError:
        return True
    try:
        if path.is_symlink():
            return True
    except OSError:
        return True
    if stat.S_ISLNK(info.st_mode):
        return True
    attrs = getattr(info, "st_file_attributes", 0)
    return bool(attrs & stat.FILE_ATTRIBUTE_REPARSE_POINT)


def _contained(root, candidate):
    try:
        root_s = os.path.normcase(str(Path(root).resolve())).rstrip("\\/")
        cand_s = os.path.normcase(str(Path(candidate).resolve()))
    except OSError as exc:
        raise ValueError(CONTROLLED["STORAGE_REFUSED"]) from exc
    return cand_s == root_s or cand_s.startswith(root_s + os.sep)


def _same_lexical(left, right):
    return os.path.normcase(os.path.normpath(str(left))) == os.path.normcase(os.path.normpath(str(right)))


def _refuse_reparse_ancestors(root, dest):
    cursor = Path(dest)
    root = Path(root)
    while True:
        if _is_reparse(cursor):
            raise ValueError(CONTROLLED["STORAGE_REFUSED"])
        if _same_lexical(cursor, root) or cursor.parent == cursor:
            break
        cursor = cursor.parent


def _resolved_inside(root, path):
    if _is_reparse(path):
        raise ValueError(CONTROLLED["STORAGE_REFUSED"])
    try:
        resolved = Path(path).resolve()
    except OSError as exc:
        raise ValueError(CONTROLLED["STORAGE_REFUSED"]) from exc
    if not _contained(root, resolved):
        raise ValueError(CONTROLLED["STORAGE_REFUSED"])
    return resolved


def _planned_inside(root, dest):
    parent = Path(dest).parent
    while not parent.exists() and parent != parent.parent:
        parent = parent.parent
    if not (parent.exists() or parent.is_symlink()):
        raise ValueError(CONTROLLED["STORAGE_REFUSED"])
    resolved_parent = _resolved_inside(root, parent)
    try:
        rest = dest.relative_to(parent)
    except ValueError as exc:
        raise ValueError(CONTROLLED["STORAGE_REFUSED"]) from exc
    if ".." in rest.parts:
        raise ValueError(CONTROLLED["STORAGE_REFUSED"])
    planned = resolved_parent.joinpath(*rest.parts)
    if not _contained(root, planned):
        raise ValueError(CONTROLLED["STORAGE_REFUSED"])
    return planned


def _confine_project_path(root, rel, prefixes):
    rel = _relative(rel, prefixes)
    base = Path(root)
    dest = base / rel
    _refuse_reparse_ancestors(base, dest)
    if dest.exists() or dest.is_symlink():
        return _resolved_inside(base, dest)
    return _planned_inside(base, dest)


def _confine_existing_file(root, rel, prefixes):
    path = _confine_project_path(root, rel, prefixes)
    if _is_reparse(path) or not path.is_file():
        raise ValueError(CONTROLLED["STORAGE_REFUSED"])
    if not _contained(root, path):
        raise ValueError(CONTROLLED["STORAGE_REFUSED"])
    return path


def _occupied(path):
    try:
        os.lstat(path)
    except FileNotFoundError:
        return False
    except OSError:
        return True
    return True


def _analysis_storage(snapshot_rel, analysis_id):
    dests = (
        (snapshot_rel, PRIVATE_AUDIO_PREFIX),
        (RESULT_PREFIX + analysis_id + ".json", RESULT_PREFIX),
        (RECEIPT_PREFIX + analysis_id + ".json", RECEIPT_PREFIX),
    )
    temps = tuple((rel + TEMP_SUFFIX, prefix) for rel, prefix in dests)
    return dests, temps


def _confine_storage_plan(root, snapshot_rel, analysis_id):
    dests, temps = _analysis_storage(snapshot_rel, analysis_id)
    confined = {}
    for rel, prefix in dests + temps:
        confined[rel] = _confine_project_path(root, rel, prefix)
    return confined


def _matching_snapshot_file(path, recording):
    if _is_reparse(path) or not path.is_file():
        return False
    try:
        return digest(path) == recording["sha256"] and path.stat().st_size == recording["bytes"]
    except OSError:
        return False


def _refuse_occupied(path):
    if _occupied(path):
        raise ValueError(CONTROLLED["STORAGE_REFUSED"])


def _preflight_write_temps(confined, rels):
    for rel in rels:
        _refuse_occupied(confined[rel])


def _preflight_new_attempt_storage(root, snapshot_rel, analysis_id, recording):
    dests, temps = _analysis_storage(snapshot_rel, analysis_id)
    confined = _confine_storage_plan(root, snapshot_rel, analysis_id)
    _preflight_write_temps(confined, tuple(rel for rel, _prefix in temps))
    for rel, _prefix in dests:
        path = confined[rel]
        if not _occupied(path):
            continue
        if rel == snapshot_rel and _matching_snapshot_file(path, recording):
            continue
        raise ValueError(CONTROLLED["STORAGE_REFUSED"])


def _preflight_resume_storage(root, snapshot_rel, analysis_id):
    confined = _confine_storage_plan(root, snapshot_rel, analysis_id)
    temps = _analysis_storage(snapshot_rel, analysis_id)[1]
    write_temps = tuple(rel for rel, prefix in temps if prefix != PRIVATE_AUDIO_PREFIX)
    _preflight_write_temps(confined, write_temps)


def _release_owned_temp(tmp):
    tmp = Path(tmp)
    try:
        if _is_reparse(tmp) or tmp.is_dir():
            return
        tmp.unlink()
    except FileNotFoundError:
        return
    except OSError:
        return


def _create_owned_temp(root, dest):
    tmp = dest.with_name(dest.name + TEMP_SUFFIX)
    if _occupied(tmp):
        # Foreign or stale dest.tmp is preserved; this process never unlinks it.
        raise ValueError(CONTROLLED["STORAGE_REFUSED"])
    try:
        fd = os.open(os.fspath(tmp), _EXCL_TEMP_FLAGS, 0o600)
    except FileExistsError as exc:
        raise ValueError(CONTROLLED["STORAGE_REFUSED"]) from exc
    except OSError as exc:
        raise ValueError(CONTROLLED["STORAGE_REFUSED"]) from exc
    with contextlib.suppress(OSError):
        os.close(fd)
    if _is_reparse(tmp) or not tmp.is_file() or not _contained(root, tmp):
        if not _is_reparse(tmp):
            _release_owned_temp(tmp)
        raise ValueError(CONTROLLED["STORAGE_REFUSED"])
    return tmp


def _prepare_write_dest(root, dest):
    dest = Path(dest)
    parent = dest.parent
    _refuse_reparse_ancestors(root, dest)
    if _occupied(parent) and (_is_reparse(parent) or not _contained(root, parent)):
        raise ValueError(CONTROLLED["STORAGE_REFUSED"])
    parent.mkdir(parents=True, exist_ok=True)
    _refuse_reparse_ancestors(root, dest)
    if not _contained(root, dest.parent):
        raise ValueError(CONTROLLED["STORAGE_REFUSED"])
    if _occupied(dest):
        raise ValueError(CONTROLLED["STORAGE_REFUSED"])
    return _create_owned_temp(root, dest)


def ensure_snapshot(root, recording):
    rel = _snapshot_rel(recording)
    dest = _confine_project_path(root, rel, PRIVATE_AUDIO_PREFIX)
    if _matching_snapshot_file(dest, recording):
        return rel
    if _occupied(dest):
        raise ValueError(CONTROLLED["STORAGE_REFUSED"])
    tmp = _prepare_write_dest(root, dest)
    hasher = hashlib.sha256()
    copied = 0
    try:
        with recording["path"].open("rb") as src, tmp.open("wb") as out:
            while True:
                chunk = src.read(COPY_CHUNK)
                if not chunk:
                    break
                copied += len(chunk)
                if copied > MAX_AUDIO_BYTES:
                    raise ValueError(CONTROLLED["RECORDING_TOO_LARGE"])
                hasher.update(chunk)
                out.write(chunk)
            out.flush()
            os.fsync(out.fileno())
        if hasher.hexdigest() != recording["sha256"] or copied != recording["bytes"]:
            raise ValueError(CONTROLLED["RECORDING_INVALID"])
        if _occupied(dest):
            raise ValueError(CONTROLLED["STORAGE_REFUSED"])
        tmp.replace(dest)
        dest.chmod(0o600)
    finally:
        _release_owned_temp(tmp)
    if digest(dest) != recording["sha256"]:
        raise ValueError(CONTROLLED["RECORDING_INVALID"])
    return rel


def _recording_record(recording, snapshot):
    return {
        "id": recording["id"],
        "sha256": recording["sha256"],
        "bytes": recording["bytes"],
        "duration_s": recording["duration_s"],
        "format": recording["format"],
        "codec": recording["codec"],
        "channels": recording["channels"],
        "sample_rate": recording["sample_rate"],
        "snapshot": snapshot,
    }


def _next_analysis_id(analyses):
    index = 1
    while f"na-{index}" in analyses:
        index += 1
    return f"na-{index}"


def _intact_result(root, analysis):
    result = analysis.get("result")
    if not isinstance(result, dict) or analysis.get("state") != "completed":
        return False
    try:
        artifact = _confine_existing_file(root, result["artifact"], RESULT_PREFIX)
        if artifact.stat().st_size > MAX_JSON_BYTES:
            return False
        if digest(artifact) != result["artifact_sha256"]:
            return False
        payload = json.loads(artifact.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return False
    return (
        isinstance(payload, dict)
        and payload.get("transcript") == result.get("transcript")
        and payload.get("words") == result.get("words")
        and "confidence" not in payload
    )


def _matching(analyses, fingerprint):
    return [item for item in analyses.values() if item.get("input_fingerprint") == fingerprint]


def _prefix_for(rel):
    if isinstance(rel, str) and rel.startswith(RESULT_PREFIX):
        return RESULT_PREFIX
    if isinstance(rel, str) and rel.startswith(RECEIPT_PREFIX):
        return RECEIPT_PREFIX
    raise ValueError(CONTROLLED["STORAGE_REFUSED"])


def _confine_write(root, rel, payload):
    path = _confine_project_path(root, rel, _prefix_for(rel))
    text = json.dumps(payload, ensure_ascii=False, indent=2)
    if path.exists() or path.is_symlink() or _is_reparse(path):
        if _is_reparse(path) or not path.is_file():
            raise ValueError(CONTROLLED["STORAGE_REFUSED"])
        try:
            current = path.read_text(encoding="utf-8")
        except OSError as exc:
            raise ValueError(CONTROLLED["STORAGE_REFUSED"]) from exc
        if current == text:
            return digest(path)
        raise ValueError(CONTROLLED["ARTIFACT_CORRUPT"])
    tmp = _prepare_write_dest(root, path)
    try:
        with tmp.open("w", encoding="utf-8") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        if _occupied(path):
            raise ValueError(CONTROLLED["STORAGE_REFUSED"])
        tmp.replace(path)
        path.chmod(0o600)
    finally:
        _release_owned_temp(tmp)
    return digest(path)


class _MultipartBody:
    def __init__(self, config_bytes, file_path, filename, boundary):
        self._head = (
            (
                f"--{boundary}\r\n"
                'Content-Disposition: form-data; name="transcribeConfig"\r\n'
                "Content-Type: application/json\r\n"
                "\r\n"
            ).encode()
            + config_bytes
            + b"\r\n"
        )
        self._file_header = (
            f"--{boundary}\r\n"
            f'Content-Disposition: form-data; name="file"; filename="{filename}"\r\n'
            "Content-Type: application/octet-stream\r\n"
            "\r\n"
        ).encode()
        self._tail = f"\r\n--{boundary}--\r\n".encode()
        self._path = Path(file_path)
        self._size = self._path.stat().st_size
        self._file = None
        self._stage = STAGE_HEAD
        self._offset = 0
        self.length = len(self._head) + len(self._file_header) + self._size + len(self._tail)

    def __len__(self):
        return self.length

    def _current(self):
        if self._stage == STAGE_HEAD:
            return self._head
        if self._stage == STAGE_FILE_HEADER:
            return self._file_header
        if self._stage == STAGE_FILE:
            return None
        return self._tail

    def read(self, size=-1):
        if size == 0:
            return b""
        remaining = size if size is not None and size >= 0 else None
        chunks = []
        while remaining is None or remaining > 0:
            if self._stage == STAGE_FILE:
                if self._file is None:
                    self._file = self._path.open("rb")
                want = COPY_CHUNK if remaining is None else remaining
                piece = self._file.read(want)
                if piece:
                    chunks.append(piece)
                    if remaining is not None:
                        remaining -= len(piece)
                    continue
                self.close()
                self._stage = STAGE_TAIL
                self._offset = 0
                continue
            block = self._current()
            if block is None or self._offset >= len(block):
                if self._stage >= STAGE_TAIL:
                    break
                self._stage += 1
                self._offset = 0
                continue
            take = len(block) - self._offset if remaining is None else min(remaining, len(block) - self._offset)
            chunks.append(block[self._offset : self._offset + take])
            self._offset += take
            if remaining is not None:
                remaining -= take
        return b"".join(chunks)

    def close(self):
        if self._file is not None:
            self._file.close()
            self._file = None


def _opener(url):
    parsed = urllib.parse.urlsplit(url)
    if _test_mode():
        origin = urllib.parse.urlsplit(api_base())
        if parsed.hostname not in LOOPBACK or parsed.hostname != origin.hostname:
            raise ProviderError(CONTROLLED["RESULT_DESTINATION_REFUSED"])
        if parsed.scheme != "http" or parsed.port != origin.port:
            raise ProviderError(CONTROLLED["RESULT_DESTINATION_REFUSED"])
        return urllib.request.build_opener(urllib.request.ProxyHandler({}), _NoRedirect())
    from .http import _PinnedHTTPSHandler

    return urllib.request.build_opener(urllib.request.ProxyHandler({}), _PinnedHTTPSHandler(), _NoRedirect())


def _request(url, *, data=None, headers=None, method="GET", authorization=False):
    request_headers = {
        "User-Agent": "Get-Brolls/narration-stt",
        "Accept": "application/json",
    }
    request_headers.update(headers or {})
    if authorization:
        request_headers["Authorization"] = "Basic " + _require_key()
    elif "Authorization" in request_headers:
        request_headers.pop("Authorization")
    request = urllib.request.Request(url, data=data, headers=request_headers, method=method)  # noqa: S310
    timeout = _test_timeout(POST_TIMEOUT_S if method == "POST" else GET_TIMEOUT_S)
    try:
        with _opener(url).open(request, timeout=timeout) as response:
            raw = response.read(MAX_JSON_BYTES + 1)
            status = getattr(response, "status", None)
    except urllib.error.HTTPError as error:
        with contextlib.suppress(OSError, ValueError):
            error.read(300)
        error.close()
        code = error.code
        if HTTP_CLIENT_MIN <= code < HTTP_SERVER_MIN:
            raise _KnownRejectionError(code) from None
        raise _UnknownTransportError from None
    except (urllib.error.URLError, TimeoutError, OSError):
        raise _UnknownTransportError from None
    if len(raw) > MAX_JSON_BYTES:
        raise _UnknownTransportError
    return status, raw


class _KnownRejectionError(ProviderError):
    def __init__(self, status):
        super().__init__(CONTROLLED["SUBMIT_REJECTED"])
        self.status = status
        self.error_code = "INVALID_DATA"


class _UnknownTransportError(ProviderError):
    def __init__(self):
        super().__init__(CONTROLLED["SUBMIT_UNKNOWN"])
        self.error_code = "INVALID_DATA"


def _validate_result_destination(url):
    if not isinstance(url, str):
        raise ValueError(CONTROLLED["RESULT_DESTINATION_REFUSED"])
    parsed = urllib.parse.urlsplit(url)
    if parsed.username or parsed.password:
        raise ValueError(CONTROLLED["RESULT_DESTINATION_REFUSED"])
    host = (parsed.hostname or "").lower().rstrip(".")
    if _test_mode():
        origin = urllib.parse.urlsplit(api_base())
        if parsed.scheme != "http" or host not in LOOPBACK or host != (origin.hostname or "").lower():
            raise ValueError(CONTROLLED["RESULT_DESTINATION_REFUSED"])
        if parsed.port != origin.port:
            raise ValueError(CONTROLLED["RESULT_DESTINATION_REFUSED"])
        return url
    if parsed.scheme != "https" or not host or parsed.port not in (None, 443):
        raise ValueError(CONTROLLED["RESULT_DESTINATION_REFUSED"])
    allowed = host in RESULT_HOSTS or any(host.endswith(suffix) for suffix in RESULT_HOST_SUFFIXES)
    if not allowed:
        raise ValueError(CONTROLLED["RESULT_DESTINATION_REFUSED"])
    try:
        addresses = socket.getaddrinfo(host, 443, type=socket.SOCK_STREAM)
    except OSError as exc:
        raise ValueError(CONTROLLED["RESULT_DESTINATION_REFUSED"]) from exc
    if not addresses or any(not ipaddress.ip_address(row[4][0]).is_global for row in addresses):
        raise ValueError(CONTROLLED["RESULT_DESTINATION_REFUSED"])
    return url


def _submit_recording(snapshot_path, config, endpoint):
    boundary = "----GetBrollsSTT" + secrets.token_hex(8)
    config_bytes = json.dumps(_transcribe_config(config), ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    filename = Path(snapshot_path).name.replace('"', "")
    body = _MultipartBody(config_bytes, snapshot_path, filename, boundary)
    url = api_base() + endpoint
    headers = {"Content-Type": f"multipart/form-data; boundary={boundary}", "Content-Length": str(body.length)}
    try:
        status, raw = _request(
            url,
            data=body,
            headers=headers,
            method="POST",
            authorization=True,
        )
    finally:
        body.close()
    if status != HTTP_OK:
        raise _UnknownTransportError
    try:
        payload = json.loads(raw.decode("utf-8"))
    except (ValueError, UnicodeError) as exc:
        raise _UnknownTransportError from exc
    if not isinstance(payload, dict):
        raise _UnknownTransportError
    return payload


def submit_async(snapshot_path, config):
    payload = _submit_recording(snapshot_path, config, STT_PATH)
    try:
        return _operation_name(payload.get("name"))
    except ValueError as exc:
        raise _UnknownTransportError from exc


def submit_sync(snapshot_path, config):
    if Path(snapshot_path).stat().st_size > MAX_SYNC_AUDIO_BYTES:
        raise ValueError(CONTROLLED["SYNC_RECORDING_TOO_LARGE"])
    payload = _submit_recording(snapshot_path, config, SYNC_STT_PATH)
    transcription = payload.get("transcription")
    if not isinstance(transcription, dict) or transcription.get("isFinal") is not True:
        raise _UnknownTransportError
    if not isinstance(transcription.get("transcript"), str):
        raise _UnknownTransportError
    return {
        "transcript": transcription["transcript"],
        "segments": [{"wordTimestamps": transcription.get("wordTimestamps")}],
    }


def poll_operation(operation_name):
    handle = _operation_name(operation_name)
    url = api_base() + LRO_PREFIX + urllib.parse.quote(handle, safe="/")
    status, raw = _request(url, method="GET", authorization=True)
    if status != HTTP_OK:
        raise _UnknownTransportError
    try:
        payload = json.loads(raw.decode("utf-8"))
    except (ValueError, UnicodeError) as exc:
        raise ProviderError(CONTROLLED["PROVIDER_JOB_ERROR"]) from exc
    if not isinstance(payload, dict):
        raise ProviderError(CONTROLLED["PROVIDER_JOB_ERROR"])
    return payload


def download_transcript(result_uri):
    url = _validate_result_destination(result_uri)
    try:
        status, raw = _request(url, method="GET", authorization=False)
    except _KnownRejectionError as error:
        if error.status in (404, 410):
            raise ValueError(CONTROLLED["RESULT_EXPIRED"]) from None
        raise ValueError(CONTROLLED["RESULT_MISSING"]) from None
    except _UnknownTransportError:
        raise ValueError(CONTROLLED["RESULT_MISSING"]) from None
    except ProviderError:
        raise ValueError(CONTROLLED["RESULT_DESTINATION_REFUSED"]) from None
    if status != HTTP_OK:
        raise ValueError(CONTROLLED["RESULT_MISSING"])
    try:
        payload = json.loads(raw.decode("utf-8"))
    except (ValueError, UnicodeError) as exc:
        raise ValueError(CONTROLLED["RESULT_INVALID"]) from exc
    if not isinstance(payload, dict):
        raise ValueError(CONTROLLED["RESULT_INVALID"])
    return payload


def _ms(value):
    if value is None:
        return 0
    if isinstance(value, bool) or not _is_number(value) or value < 0:
        raise ValueError
    return value


def _stamp_word(item, index):
    if not isinstance(item, dict) or not isinstance(item.get("word"), str):
        raise ValueError
    start = _ms(item.get("startTimeMs"))
    end = _ms(item.get("endTimeMs"))
    if start > end:
        raise ValueError
    return {"word": item["word"], "start_ms": start, "end_ms": end, "segment": index}


def _parse_words(payload):
    segments = payload.get("segments")
    words = []
    timing_ok = True
    if segments is None:
        timing_ok = False
        segments = []
    if not isinstance(segments, list):
        raise ValueError(CONTROLLED["RESULT_INVALID"])
    if not segments:
        timing_ok = False
    for index, segment in enumerate(segments):
        stamps = segment.get("wordTimestamps") if isinstance(segment, dict) else None
        if not isinstance(stamps, list) or not stamps:
            timing_ok = False
            continue
        for item in stamps:
            try:
                words.append(_stamp_word(item, index))
            except ValueError:
                timing_ok = False
    if segments and not words:
        timing_ok = False
    return words, timing_ok, len(segments)


def _public_usage(usage):
    if not isinstance(usage, dict):
        return None
    public = {key: usage[key] for key in USAGE_KEYS if key in usage and _safe_usage_value(key, usage[key])}
    return public or None


def _public_language(payload):
    language = payload.get("language")
    if language is None:
        language = payload.get("languageCode")
    if not isinstance(language, str) or not language or _CONTROL.search(language):
        return None
    if len(language) > LANGUAGE_MAX or _secret_text(language):
        return None
    return language


def parse_transcript(payload, duration_s=None):
    transcript = payload.get("transcript")
    if transcript is None:
        transcript = ""
    if not isinstance(transcript, str):
        raise ValueError(CONTROLLED["RESULT_INVALID"])
    words, timing_ok, segments = _parse_words(payload)
    if not _words_timing_ok(words, duration_s):
        timing_ok = False
    return {
        "transcript": transcript,
        "words": words,
        "segments": segments,
        "timing_resolved": bool(timing_ok and words),
        "language": _public_language(payload),
        "usage": _public_usage(payload.get("usage")),
    }


def _store_result(root, analysis_id, parsed):
    rel = RESULT_PREFIX + analysis_id + ".json"
    stored = {
        "transcript": parsed["transcript"],
        "words": parsed["words"],
        "segments": parsed["segments"],
        "timing_resolved": parsed["timing_resolved"],
        "language": parsed["language"],
        "usage": parsed["usage"],
    }
    sha = _confine_write(root, rel, stored)
    return {
        **stored,
        "artifact": rel,
        "artifact_sha256": sha,
    }


def _public_analysis(analysis, *, reused=False, recording=None):
    result = _as_dict(analysis.get("result"))
    stored_words = result.get("words")
    words = stored_words if isinstance(stored_words, list) else []
    timing = None
    if words:
        timing = {
            "words": len(words),
            "segments": result.get("segments"),
            "start_ms": words[0]["start_ms"],
            "end_ms": words[-1]["end_ms"],
        }
    error = analysis.get("error")
    payload = {
        "analysis_id": analysis.get("id"),
        "recording_id": analysis.get("recording_id"),
        "state": analysis.get("state"),
        "submit_outcome": analysis.get("submit_outcome"),
        "reused": reused,
        "operation_name": analysis.get("operation_name"),
        "transport": analysis.get("transport", "async"),
        "config": analysis.get("config"),
        "audio_fingerprint": analysis.get("audio_fingerprint"),
        "input_fingerprint": analysis.get("input_fingerprint"),
        "transcript": result.get("transcript"),
        "word_count": len(words),
        "timing_resolved": result.get("timing_resolved"),
        "timing": timing,
        "error": error,
    }
    if recording:
        payload["recording"] = {
            "id": recording.get("id"),
            "sha256": recording.get("sha256"),
            "bytes": recording.get("bytes"),
            "duration_s": recording.get("duration_s"),
            "format": recording.get("format"),
            "codec": recording.get("codec"),
        }
    if analysis.get("retry"):
        payload["retry_of"] = analysis["retry"]["source"]
    return payload


def _refuse_resubmit(analysis):
    state = analysis.get("state")
    if state in IN_FLIGHT or analysis.get("submit_outcome") == "unknown":
        raise ValueError(CONTROLLED["ALREADY_IN_FLIGHT"] + f" Saved analysis: {analysis.get('id')}.")
    if state == "failed":
        raise ValueError(CONTROLLED["ALREADY_FAILED"] + f" Saved analysis: {analysis.get('id')}.")


def _select_existing(analyses, fingerprint, requested):
    matches = _matching(analyses, fingerprint)
    if requested and requested in analyses:
        target = analyses[requested]
        if target.get("input_fingerprint") != fingerprint:
            raise ValueError(CONTROLLED["FINGERPRINT_CHANGED"])
        return target
    completed = [item for item in matches if item.get("state") == "completed"]
    if completed:
        return completed[-1]
    in_flight = [item for item in matches if item.get("state") in IN_FLIGHT or item.get("submit_outcome") == "unknown"]
    if in_flight:
        _refuse_resubmit(in_flight[-1])
    if requested:
        return None
    if matches:
        _refuse_resubmit(matches[-1])
    return None


def _check_retry_available(ledger, source, recording):
    analyses = ensure_narration(ledger.data)["analyses"]
    if source.get("state") != "unknown" or source.get("operation_name"):
        raise ValueError("Only an unknown submit without a handle can prepare a deliberate retry; resume known work.")
    for analysis in _matching(analyses, source["input_fingerprint"]):
        if analysis.get("retry") is not None:
            raise ValueError("The one deliberate retry is already consumed. Resume its saved analysis.")
        if analysis["id"] != source["id"] and (analysis.get("state") == "completed" or analysis.get("operation_name")):
            raise ValueError("A completed result or known operation already exists. Reuse or resume it first.")
    snapshot = _confine_existing_file(
        ledger.root,
        ensure_narration(ledger.data)["recordings"][source["recording_id"]]["snapshot"],
        PRIVATE_AUDIO_PREFIX,
    )
    if digest(snapshot) != recording["sha256"]:
        raise ValueError(CONTROLLED["RECORDING_INVALID"])
    receipt = _confine_project_path(ledger.root, RECEIPT_PREFIX + source["id"] + ".json", RECEIPT_PREFIX)
    if receipt.exists() or receipt.is_symlink():
        raise ValueError(
            "The earlier analysis has a retained receipt. Resume it before considering a new paid request."
        )


def _prepare_retry(ledger, args, recording, config):
    analyses = ensure_narration(ledger.data)["analyses"]
    source = analyses.get(args.retry_of)
    if not isinstance(source, dict):
        raise ValueError(CONTROLLED["ANALYSIS_NOT_FOUND"])
    requested = args.analysis
    if not _valid_id(requested) or requested == source["id"]:
        raise ValueError("A retry needs a distinct explicit --analysis identity.")
    if source.get("retry") is not None:
        raise ValueError("A retry cannot start another retry. The one-retry allowance does not reset.")
    if recording["sha256"] != source["audio_fingerprint"] or config != source["config"]:
        raise ValueError(CONTROLLED["FINGERPRINT_CHANGED"])
    transport = "sync" if args.sync else "async"
    if transport == "sync" and recording["bytes"] > MAX_SYNC_AUDIO_BYTES:
        raise ValueError(CONTROLLED["SYNC_RECORDING_TOO_LARGE"])
    scope = _retry_scope(source, requested, transport)
    fingerprint = _payload_hash(scope)
    confirmation = getattr(args, "confirm_retry", None)
    if confirmation is not None and confirmation != fingerprint:
        raise ValueError("The retry confirmation does not match the exact prepared scope.")
    existing = analyses.get(requested)
    if existing is not None:
        retry = existing.get("retry") or {}
        if retry.get("source") != source["id"] or retry.get("fingerprint") != fingerprint:
            raise ValueError("The retry identity is already occupied by a different request.")
        return {"existing": existing}
    _check_retry_available(ledger, source, recording)
    if not confirmation:
        return {
            "proposal": {
                "state": "awaiting_retry_confirmation",
                "retry_scope": scope,
                "confirmation_fingerprint": fingerprint,
                "recording_duration_s": recording["duration_s"],
                "recording_bytes": recording["bytes"],
                "provider_posts": 0,
                "warning": "This is a new potentially billable POST. The earlier attempt stays unknown and may be charged.",
            }
        }
    return {
        "retry": {
            "source": source["id"],
            "fingerprint": fingerprint,
            "by": _retry_text(getattr(args, "by", None), 200),
            "statement": _retry_text(getattr(args, "statement", None), 4000),
            "at": now(),
        }
    }


def analyze_command(ledger, args):  # noqa: C901, PLR0911, PLR0912, PLR0915
    recording = validate_recording(args.recording)
    config = analysis_config(getattr(args, "language", None))
    fingerprint = input_fingerprint(recording["sha256"], config)
    narration = ensure_narration(ledger.data)
    rec_id = recording["id"]
    requested = getattr(args, "analysis", None)
    if requested is not None and not _valid_id(requested):
        raise ValueError("Analysis identity must be 1–80 letters, numbers, hyphen or underscore.")
    retry = None
    if getattr(args, "retry_of", None):
        prepared = _prepare_retry(ledger, args, recording, config)
        if "proposal" in prepared:
            return prepared["proposal"]
        if "existing" in prepared:
            return resume_command(ledger, args)
        retry = prepared["retry"]
        existing = None
    else:
        if any(getattr(args, key, None) for key in ("confirm_retry", "by", "statement")):
            raise ValueError("Retry confirmation/reviewer flags require --retry-of.")
        existing = _select_existing(narration["analyses"], fingerprint, requested)
    recording_row = narration["recordings"].get(rec_id)
    if existing is not None and existing.get("state") == "completed":
        if _intact_result(ledger.root, existing):
            narration["current_analysis"] = existing["id"]
            ledger.save("narration-analyze")
            return _public_analysis(existing, reused=True, recording=recording_row)
        existing["error"] = _public_error("ARTIFACT_CORRUPT")
        ledger.save("narration-analyze")
        raise ValueError(CONTROLLED["ARTIFACT_CORRUPT"] + f" Saved analysis: {existing['id']}.")
    if existing is not None:
        if existing.get("state") == "intent" and not existing.get("operation_name"):
            existing["state"] = "unknown"
            existing["submit_outcome"] = "unknown"
            existing["error"] = _public_error("SUBMIT_UNKNOWN")
            narration["current_analysis"] = existing["id"]
            ledger.save("narration-analyze")
            return _public_analysis(existing, recording=recording_row)
        _refuse_resubmit(existing)
    synchronous = bool(getattr(args, "sync", False))
    if synchronous and recording["bytes"] > MAX_SYNC_AUDIO_BYTES:
        raise ValueError(CONTROLLED["SYNC_RECORDING_TOO_LARGE"])
    analysis_id = requested or _next_analysis_id(narration["analyses"])
    if analysis_id in narration["analyses"]:
        raise ValueError(CONTROLLED["ALREADY_IN_FLIGHT"] + f" Saved analysis: {analysis_id}.")
    snapshot_rel = _snapshot_rel(recording)
    _preflight_new_attempt_storage(ledger.root, snapshot_rel, analysis_id, recording)
    if recording_row is not None and recording_row.get("sha256") != recording["sha256"]:
        raise ValueError(CONTROLLED["FINGERPRINT_CHANGED"])
    snapshot = ensure_snapshot(ledger.root, recording)
    if rec_id not in narration["recordings"]:
        narration["recordings"][rec_id] = _recording_record(recording, snapshot)
    _require_key()
    analysis = {
        "id": analysis_id,
        "recording_id": rec_id,
        "state": "intent",
        "submit_outcome": "not_sent",
        "transport": "sync" if synchronous else "async",
        "created_at": now(),
        "config": config,
        "config_fingerprint": _payload_hash(config),
        "audio_fingerprint": recording["sha256"],
        "input_fingerprint": fingerprint,
        "operation_name": None,
        "error": None,
        "result": None,
    }
    if retry is not None:
        analysis["retry"] = retry
    narration["analyses"][analysis_id] = analysis
    narration["current_analysis"] = analysis_id
    ledger.save("narration-analyze")
    if _test_crash("after-intent"):
        raise ValueError("Test interrupt after narration submit intent.")
    snapshot_path = _confine_existing_file(ledger.root, snapshot, PRIVATE_AUDIO_PREFIX)
    if digest(snapshot_path) != recording["sha256"]:
        raise ValueError(CONTROLLED["RECORDING_INVALID"])
    try:
        response = submit_sync(snapshot_path, config) if synchronous else submit_async(snapshot_path, config)
    except _KnownRejectionError:
        analysis["state"] = "failed"
        analysis["submit_outcome"] = "rejected"
        analysis["error"] = _public_error("SUBMIT_REJECTED")
        ledger.save("narration-analyze")
        return _public_analysis(analysis, recording=narration["recordings"][rec_id])
    except (_UnknownTransportError, ProviderError, ValueError, OSError, TimeoutError):
        analysis["state"] = "unknown"
        analysis["submit_outcome"] = "unknown"
        analysis["error"] = _public_error("SUBMIT_UNKNOWN")
        ledger.save("narration-analyze")
        return _public_analysis(analysis, recording=narration["recordings"][rec_id])
    if synchronous:
        _complete_transcript(ledger.root, analysis, response, recording["duration_s"])
        analysis["submit_outcome"] = "accepted"
        analysis["submitted_at"] = now()
        _confine_write(
            ledger.root,
            RECEIPT_PREFIX + analysis_id + ".json",
            {
                "analysis_id": analysis_id,
                "input_fingerprint": fingerprint,
                "result": analysis["result"],
                "error": analysis["error"],
                "submitted_at": analysis["submitted_at"],
            },
        )
        if _test_crash("after-sync-result"):
            raise ValueError("Test interrupt after durable synchronous result before ledger persistence.")
        ledger.save("narration-analyze")
        return _public_analysis(analysis, recording=narration["recordings"][rec_id])
    if _test_crash("before-operation"):
        raise ValueError("Test interrupt after provider POST before operation persistence.")
    analysis["operation_name"] = response
    analysis["state"] = "pending"
    analysis["submit_outcome"] = "accepted"
    analysis["submitted_at"] = now()
    ledger.save("narration-analyze")
    return _public_analysis(analysis, recording=narration["recordings"][rec_id])


def _apply_operation_payload(root, analysis, payload, duration_s=None):  # noqa: PLR0911
    if payload.get("done") is False:
        analysis["state"] = "pending"
        analysis["error"] = None
        return analysis
    if payload.get("error"):
        analysis["state"] = "failed"
        analysis["error"] = _public_error("PROVIDER_JOB_ERROR")
        return analysis
    if payload.get("done") is not True:
        analysis["state"] = "unknown"
        analysis["error"] = _public_error("SUBMIT_UNKNOWN")
        return analysis
    response = payload.get("response")
    if not isinstance(response, dict):
        analysis["state"] = "failed"
        analysis["error"] = _public_error("RESULT_MISSING")
        return analysis
    expire = response.get("expireTime")
    result_uri = response.get("resultUri")
    if not result_uri:
        analysis["state"] = "failed"
        analysis["error"] = _public_error("RESULT_EXPIRED" if expire else "RESULT_MISSING")
        return analysis
    try:
        raw = download_transcript(result_uri)
    except ValueError as exc:
        message = str(exc)
        code = "RESULT_INVALID"
        for key, text in CONTROLLED.items():
            if text == message:
                code = key
                break
        if not analysis.get("result"):
            analysis["state"] = "failed"
        analysis["error"] = _public_error(code if code in CONTROLLED else "RESULT_INVALID")
        return analysis
    return _complete_transcript(root, analysis, raw, duration_s)


def _complete_transcript(root, analysis, raw, duration_s=None):
    try:
        parsed = parse_transcript(raw, duration_s)
    except ValueError:
        transcript = raw.get("transcript") if isinstance(raw.get("transcript"), str) else ""
        parsed = {
            "transcript": transcript,
            "words": [],
            "segments": 0,
            "timing_resolved": False,
            "language": None,
            "usage": None,
        }
        stored = _store_result(root, analysis["id"], parsed)
        analysis["result"] = stored
        analysis["state"] = "completed"
        analysis["error"] = _public_error("RESULT_INVALID" if transcript else "TIMING_UNRESOLVED")
        return analysis
    stored = _store_result(root, analysis["id"], parsed)
    analysis["result"] = stored
    analysis["state"] = "completed"
    if parsed["timing_resolved"]:
        analysis["error"] = None
    else:
        analysis["error"] = _public_error("TIMING_UNRESOLVED")
    return analysis


def _artifact_missing_inside(root, analysis):
    result = _as_dict(analysis.get("result"))
    rel = result.get("artifact")
    if not isinstance(rel, str):
        rel = RESULT_PREFIX + analysis["id"] + ".json"
    dest = _confine_project_path(root, rel, RESULT_PREFIX)
    return not dest.exists() and not dest.is_symlink() and not _is_reparse(dest)


def _resume_without_provider(ledger, narration, analysis, recording):
    analysis_id = analysis["id"]
    if analysis.get("transport") == "sync" and analysis.get("state") in IN_FLIGHT:
        _restore_sync_receipt(ledger.root, analysis, recording)
    if analysis.get("state") == "completed" and _intact_result(ledger.root, analysis):
        narration["current_analysis"] = analysis_id
        ledger.save("narration-resume")
        return _public_analysis(analysis, reused=True, recording=recording)
    if analysis.get("state") == "completed":
        try:
            replaceable = _artifact_missing_inside(ledger.root, analysis)
        except ValueError:
            analysis["error"] = _public_error("STORAGE_REFUSED")
            narration["current_analysis"] = analysis_id
            ledger.save("narration-resume")
            raise ValueError(CONTROLLED["STORAGE_REFUSED"]) from None
        analysis["error"] = _public_error("ARTIFACT_CORRUPT")
        if not replaceable or not analysis.get("operation_name"):
            narration["current_analysis"] = analysis_id
            ledger.save("narration-resume")
            if not analysis.get("operation_name"):
                raise ValueError(CONTROLLED["ARTIFACT_CORRUPT"])
            return _public_analysis(analysis, recording=recording)
    elif analysis.get("state") == "failed" and not analysis.get("operation_name"):
        narration["current_analysis"] = analysis_id
        ledger.save("narration-resume")
        return _public_analysis(analysis, recording=recording)
    elif not analysis.get("operation_name"):
        analysis["state"] = "unknown"
        analysis["submit_outcome"] = "unknown"
        analysis["error"] = _public_error("SUBMIT_UNKNOWN")
        narration["current_analysis"] = analysis_id
        ledger.save("narration-resume")
        return _public_analysis(analysis, recording=recording)
    return None


def _restore_sync_receipt(root, analysis, recording):
    rel = RECEIPT_PREFIX + analysis["id"] + ".json"
    path = _confine_project_path(root, rel, RECEIPT_PREFIX)
    if not _occupied(path):
        return
    path = _confine_existing_file(root, rel, RECEIPT_PREFIX)
    try:
        if path.stat().st_size > MAX_JSON_BYTES:
            raise ValueError
        receipt = json.loads(path.read_text(encoding="utf-8"))
        if receipt["analysis_id"] != analysis["id"] or receipt["input_fingerprint"] != analysis["input_fingerprint"]:
            raise ValueError
        result = receipt["result"]
        _validate_result(result, recording.get("duration_s"))
        _validate_analysis_error(receipt.get("error"))
        submitted = receipt["submitted_at"]
        if not isinstance(submitted, str) or result["artifact"] != RESULT_PREFIX + analysis["id"] + ".json":
            raise ValueError
        if not _intact_result(root, {"state": "completed", "result": result}):
            raise ValueError
    except (ValueError, TypeError, KeyError, OSError) as exc:
        raise ValueError(CONTROLLED["ARTIFACT_CORRUPT"]) from exc
    analysis.update(
        state="completed", submit_outcome="accepted", result=result, error=receipt.get("error"), submitted_at=submitted
    )


def resume_command(ledger, args):
    narration = ledger.data.get("narration")
    if not isinstance(narration, dict):
        raise ValueError(CONTROLLED["ANALYSIS_NOT_FOUND"])
    analysis_id = args.analysis
    analysis = (narration.get("analyses") or {}).get(analysis_id)
    if not isinstance(analysis, dict):
        raise ValueError(CONTROLLED["ANALYSIS_NOT_FOUND"])
    recording = (narration.get("recordings") or {}).get(analysis.get("recording_id"))
    local = _resume_without_provider(ledger, narration, analysis, recording)
    if local is not None:
        return local
    snapshot = recording.get("snapshot") if isinstance(recording, dict) else None
    if isinstance(snapshot, str):
        _preflight_resume_storage(ledger.root, snapshot, analysis_id)
    else:
        result_rel = RESULT_PREFIX + analysis_id + ".json"
        receipt_rel = RECEIPT_PREFIX + analysis_id + ".json"
        for rel, prefix in (
            (result_rel, RESULT_PREFIX),
            (receipt_rel, RECEIPT_PREFIX),
            (result_rel + TEMP_SUFFIX, RESULT_PREFIX),
            (receipt_rel + TEMP_SUFFIX, RECEIPT_PREFIX),
        ):
            path = _confine_project_path(ledger.root, rel, prefix)
            if rel.endswith(TEMP_SUFFIX):
                _refuse_occupied(path)
    _require_key()
    try:
        payload = poll_operation(analysis["operation_name"])
    except _KnownRejectionError:
        analysis["state"] = "failed"
        analysis["error"] = _public_error("PROVIDER_JOB_ERROR")
        ledger.save("narration-resume")
        return _public_analysis(analysis, recording=recording)
    except (_UnknownTransportError, ProviderError, ValueError):
        analysis["error"] = _public_error("SUBMIT_UNKNOWN")
        ledger.save("narration-resume")
        return _public_analysis(analysis, recording=recording)
    duration_s = recording.get("duration_s") if isinstance(recording, dict) else None
    _apply_operation_payload(ledger.root, analysis, payload, duration_s)
    narration["current_analysis"] = analysis_id
    ledger.save("narration-resume")
    return _public_analysis(analysis, recording=recording)


def narration_status(data, root=None):
    narration = data.get("narration")
    if not isinstance(narration, dict):
        return {"schema_version": NARRATION_SCHEMA, "recordings": 0, "analyses": 0, "current": None, "items": []}
    analyses = narration.get("analyses") or {}
    recordings = narration.get("recordings") or {}
    items = []
    for analysis in analyses.values():
        if not isinstance(analysis, dict):
            continue
        recording = recordings.get(analysis.get("recording_id"))
        public = _public_analysis(analysis, recording=recording if isinstance(recording, dict) else None)
        if root is not None and analysis.get("state") == "completed" and not _intact_result(root, analysis):
            public["error"] = _public_error("ARTIFACT_CORRUPT")
            public["timing_resolved"] = False
        items.append(public)
    current_id = narration.get("current_analysis")
    current = next((item for item in items if item.get("analysis_id") == current_id), items[-1] if items else None)
    return {
        "schema_version": NARRATION_SCHEMA,
        "recordings": len(recordings),
        "analyses": len(analyses),
        "current": current,
        "items": items,
    }


def narration_review_records(ledger):
    status = narration_status(ledger.data, ledger.root)
    return [
        {
            "id": item.get("analysis_id"),
            "recording_id": item.get("recording_id"),
            "state": item.get("state"),
            "transcript": item.get("transcript"),
            "word_count": item.get("word_count"),
            "timing": item.get("timing"),
            "timing_resolved": item.get("timing_resolved"),
            "error": item.get("error"),
            "config": item.get("config"),
            "recording": item.get("recording"),
        }
        for item in status.get("items") or []
    ]


def storyboard_section(ledger):
    status = narration_status(ledger.data, ledger.root)
    if not status.get("items"):
        return ""
    parts = [
        '<section class="narration-board" aria-label="Narration analysis">',
        '<details class="narration-details"><summary>Narration transcripts and analysis details</summary>',
        "<h2>Narration analysis</h2>",
        (
            "<p>Inworld transcription of a complete local recording. "
            "Recognized text and word times are inputs to later scene matching. "
            "Viewing this board does not submit, poll or download.</p>"
        ),
    ]
    for item in status["items"]:
        recording = item.get("recording") or {}
        error = item.get("error") or {}
        timing = item.get("timing") or {}
        transcript = item.get("transcript") or ""
        parts.append(f'<article class="narration-card" data-analysis="{_esc(item.get("analysis_id"))}">')
        parts.append(f"<h3>Analysis {_esc(item.get('analysis_id'))} · {_esc(item.get('state'))}</h3>")
        parts.append(
            "<p>Recording "
            f"{_esc(recording.get('id'))} · sha256 {_esc((recording.get('sha256') or '')[:16])} "
            f"· {_esc(recording.get('format'))} {_esc(recording.get('duration_s'))}s</p>"
        )
        if transcript:
            parts.append(f"<blockquote>{_esc(transcript)}</blockquote>")
        if timing:
            parts.append(
                "<p>Word timing "
                f"{_esc(timing.get('words'))} words, {_esc(timing.get('segments'))} segments, "
                f"{_esc(timing.get('start_ms'))}–{_esc(timing.get('end_ms'))} ms"
                f"{'' if item.get('timing_resolved') else ' (unresolved)'}</p>"
            )
        elif item.get("state") == "completed":
            parts.append("<p>Word timing unresolved.</p>")
        if error.get("message"):
            parts.append(f'<p class="narration-error">{_esc(error.get("message"))}</p>')
        parts.append("</article>")
    parts.append("</details></section>")
    return "".join(parts)
