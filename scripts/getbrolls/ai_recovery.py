"""Bounded corrective attempts retain the original operation and its frozen scope."""

from __future__ import annotations

import copy
import uuid
from contextlib import contextmanager

from .ai_state import (
    beat_for,
    checked_version,
    digest,
    fingerprint,
    identifier,
    new_job,
    public_job,
    text,
    version_signature,
)
from .ledger import Ledger
from .runtime import _acquire_lock, _release_lock, project_lock


@contextmanager
def worker_lock(project, job_id):
    """One producer/retriever per job, released by the OS even after process death."""
    from .ai import _brolls_root, _chain_inside, _job_dir

    root = _brolls_root(project)
    directory = _job_dir(root, job_id)
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / ".worker.lock"
    _chain_inside(root, path)
    with path.open("a+", encoding="utf-8") as stream:
        try:
            _acquire_lock(stream)
        except BlockingIOError:
            raise ValueError("This AI job is already running or being recovered. Wait for it to finish.") from None
        try:
            yield
        finally:
            _release_lock(stream)


def check_inputs(ledger, job):
    from .ai_references import handoff
    from .ai_timing import checked_video_input

    request = job["request"]
    beat_for(ledger, request["beat"], request["inputs"])
    if request["kind"] == "video":
        checked_video_input(ledger, request)
    target = request.get("target")
    if target:
        version, _path = checked_version(ledger, target.get("id"), kind="image")
        if version_signature(version) != target.get("signature") or version["sha256"] != target.get("sha256"):
            raise ValueError("The frozen original image changed.")
    for ref in request.get("references") or []:
        saved = handoff(ledger, ref["input_id"])
        if (
            saved["invalidated"]
            or saved["source_sha256"] != ref["source_sha256"]
            or saved["derivative_sha256"] != ref["derivative_sha256"]
        ):
            raise ValueError("A frozen reference changed or was invalidated.")


def checked_artifact(ledger, job):
    from .ai import _confined_original, _job_dir, _recorded_artifact

    workdir = _job_dir(ledger.root, job["id"])
    artifact = _recorded_artifact(job)
    if not artifact:
        raise ValueError("No recorded local AI result is available.")
    path = _confined_original(workdir, workdir / artifact)
    if digest(path) != (job.get("remote") or {}).get("artifact_sha256"):
        raise ValueError("The recorded local AI result is missing or changed.")
    return path


def recovery_state(job, ledger=None):  # noqa: PLR0911 - distinguish durable outcome, current input/output integrity and retrieval availability.
    from .ai import _grok_retrievable, _openrouter_retrievable, _recorded_artifact

    state = job.get("state")
    artifact = bool(_recorded_artifact(job) and (job.get("remote") or {}).get("artifact_sha256"))
    remote = _grok_retrievable(job) or _openrouter_retrievable(job)
    code = (job.get("error") or {}).get("code")
    if ledger is not None:
        if job.get("result"):
            try:
                checked_version(ledger, job["result"])
            except (ValueError, OSError, KeyError):
                return {"action": None, "reason": "output_invalid"}
        try:
            check_inputs(ledger, job)
        except (ValueError, OSError, KeyError):
            return {"action": None, "reason": "inputs_changed"}
        if artifact and state != "complete":
            try:
                checked_artifact(ledger, job)
            except (ValueError, OSError, KeyError):
                return {"action": "retrieve" if remote else None, "reason": "artifact_invalid"}
    if state == "complete":
        return {"action": None, "reason": "complete"}
    if state in {"failed", "unknown", "remote_pending", "downloading"} and (artifact or remote):
        return {
            "action": "retrieve",
            "reason": "artifact_invalid"
            if code == "artifact"
            else "local_handoff"
            if artifact
            else "retrieval_failed"
            if job.get("error")
            else "provider_processing",
        }
    if state == "queued" and job.get("submit_outcome") == "not_sent":
        return {"action": "continue", "reason": "before_submit"}
    return {
        "action": None,
        "reason": "unknown_submit"
        if job.get("submit_outcome") == "unknown" or state == "running"
        else "rejected"
        if job.get("submit_outcome") == "rejected"
        else state,
    }


def correction_request(original, intent, nonce):
    request = copy.deepcopy(original["request"])
    # A corrective output is independent of the original comparison's all-three consent.
    for key in ("group", "slot", "mode"):
        request.pop(key, None)
    request["correction"] = intent
    request["session_id"] = str(uuid.UUID(fingerprint({"correction": original["id"], "nonce": nonce})[:32]))
    request["prompt"] += "\nObserved defect: " + intent["defect"] + "\nCorrective intent: " + intent["instruction"]
    return request


def handle_correct(project, data):
    from .ai import _dispatch_payload, dispatch_after_audit
    from .ai_timing import checked_video_input

    nonce = text(data.get("requestId"), "Request identity", 160)
    with project_lock(project):
        ledger = Ledger(project)
        ai = ledger.data.get("ai") or {}
        original = ai.get("jobs", {}).get(identifier(data.get("job"), "Job id"))
        if not original or original["state"] != "complete" or not original.get("result"):
            raise ValueError("Observe a defect in a completed result before requesting a correction.")
        version, _path = checked_version(ledger, original["result"])
        if data.get("signature") != version_signature(version):
            raise ValueError("Identify the exact original result with the observed defect.")
        intent = {
            "original": original["id"],
            "version": version["id"],
            "signature": data["signature"],
            "defect": text(data.get("defect"), "Observed defect", 8000),
            "instruction": text(data.get("instruction"), "Corrective intent", 8000),
            "by": text(data.get("by"), "Requester", 200),
        }
        request = correction_request(original, intent, nonce)
        prior = next((j for j in ai["jobs"].values() if j["nonce"] == nonce), None)
        record = (ai.get("sequences") or {}).get(request.get("sequence")) or (ai.get("groups") or {}).get(
            original["request"].get("group")
        )
        if (
            record
            and record.get("corrections")
            and (record["corrections"].get(original["id"]) != (prior or {}).get("id"))
        ):
            raise ValueError("This operation has already used its one corrective generation.")
        if request["kind"] == "video" and not prior:
            checked_video_input(ledger, original["request"])
        if request["kind"] == "image":
            check_inputs(ledger, original)
        job = new_job(ledger, request, nonce, correction_of=original["id"])
        if record and not prior:
            record["corrections"] = {original["id"]: job["id"]}
            if request.get("sequence"):
                record.update(version=None, error=None)
        if request["kind"] == "video":
            checked_video_input(ledger, job["request"])
        ledger.save("ai-corrective-intent")
        result = {"job": public_job(job)}
        dispatch = _dispatch_payload(ledger, [job])
        if dispatch:
            result["ai_dispatch"] = dispatch
    return dispatch_after_audit(result)


def admitted_media(project, relative):
    """Read-only serving guard: publish only intact committed AI versions/preview bytes."""
    from .ai_timing import checked_video_input

    try:
        ledger = Ledger(project, recover=False)
        ai = ledger.data.get("ai") or {}
        for version in ai.get("versions", {}).values():
            if relative not in {version.get("path"), (version.get("preview") or {}).get("path")}:
                continue
            checked_version(ledger, version["id"])
            if version["kind"] == "video":
                checked_video_input(ledger, ai["jobs"][version["job"]]["request"])
            return True
    except (ValueError, OSError, KeyError):
        return False
    return False
