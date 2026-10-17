"""GPT subscription still commands, durable worker, Storyboard and HTTP handlers."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import stat
import subprocess
import sys
import uuid
from html import escape
from pathlib import Path

from .ai_provider import APP_SERVER_ENV, TIMEOUT_S, generate_still
from .ai_state import (
    attach_result,
    identifier,
    import_plan,
    launch_still,
    public_job,
    public_version,
    review,
    sanitize_public_text,
    select,
    version_signature,
)
from .ledger import Ledger, digest
from .media import run
from .models import now
from .runtime import project_lock

INLINE_ENV = "GETBROLLS_AI_INLINE"
CRASH_ENV = "GETBROLLS_AI_TEST_CRASH"
FIXTURE_ENV = "GETBROLLS_AI_FIXTURE"
WORKER_ENV = (
    APP_SERVER_ENV,
    FIXTURE_ENV,
    INLINE_ENV,
    CRASH_ENV,
    "GETBROLLS_AI_TIMEOUT",
)
STILL_CODECS = {"png": ".png", "mjpeg": ".jpg"}
MAX_ARTIFACT_PATH = 240
MAX_REMOTE_ID = 200


def _esc(value):
    return escape(str(value or ""), quote=True)


def _project_root(ledger):
    return ledger.root.parent


def _error_payload(message, code=None):
    payload = {"message": sanitize_public_text(message)}
    if code:
        payload["code"] = code
    return payload


def _should_dispatch(job):
    return job.get("state") == "queued" and job.get("submit_outcome") == "not_sent"


def public_status(data, root=None):  # noqa: ARG001 - status_report always passes ledger.root.
    ai = data.get("ai")
    if not isinstance(ai, dict):
        return {}
    beats = []
    for beat in (ai.get("beats") or {}).values():
        if not isinstance(beat, dict):
            continue
        beats.append(
            {
                "id": beat.get("id"),
                "active": beat.get("active"),
                "mode": beat.get("mode"),
                "selected": beat.get("selected"),
                "fingerprint": beat.get("fingerprint"),
            }
        )
    jobs = [public_job(job) for job in (ai.get("jobs") or {}).values() if isinstance(job, dict)]
    versions = [public_version(row) for row in (ai.get("versions") or {}).values() if isinstance(row, dict)]
    style_value = ai.get("style")
    style = style_value if isinstance(style_value, dict) else {}
    return {
        "plan": bool(ai.get("plan")),
        "style": style.get("fingerprint"),
        "beats": beats,
        "jobs": jobs,
        "versions": versions,
    }


def public_board(ledger):
    ai = ledger.data.get("ai") or {}
    jobs = ai.get("jobs") or {}
    versions = ai.get("versions") or {}
    beats = []
    for beat in (ai.get("beats") or {}).values():
        if not isinstance(beat, dict):
            continue
        job = next(
            (
                row
                for row in reversed(list(jobs.values()))
                if isinstance(row, dict)
                and (row.get("request") or {}).get("beat") == beat.get("id")
                and (row.get("request") or {}).get("inputs") == beat.get("fingerprint")
            ),
            None,
        )
        version = versions.get((job or {}).get("result") or "") if job else None
        if not isinstance(version, dict):
            version = None
        beats.append(
            {
                "id": beat.get("id"),
                "active": beat.get("active", True),
                "fingerprint": beat.get("fingerprint"),
                "mode": beat.get("mode"),
                "selected": beat.get("selected"),
                "comment": beat.get("comment") or "",
                "job": public_job(job) if job else None,
                "version": public_version(version) if version else None,
            }
        )
    return {
        "beats": beats,
        "jobs": [public_job(job) for job in jobs.values() if isinstance(job, dict)],
        "versions": [public_version(row) for row in versions.values() if isinstance(row, dict)],
        "style": ((ai.get("style") or {}).get("prompt") if isinstance(ai.get("style"), dict) else None),
    }


def _read_json(path):
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("The AI plan must be a JSON object.")
    return payload


def plan_command(ledger, args):
    return import_plan(ledger, _read_json(args.file))


def select_command(ledger, args):
    payload = {"beat": args.beat, "alternative": args.alternative}
    if getattr(args, "comment", None) is not None:
        payload["comment"] = args.comment
    if getattr(args, "mode", None) is not None:
        payload["mode"] = args.mode
    if getattr(args, "expected", None) is not None:
        payload["expected"] = args.expected
    beat = select(ledger, payload)
    return {
        "beat": beat["id"],
        "selected": beat.get("selected"),
        "mode": beat.get("mode"),
        "comment": beat.get("comment") or "",
    }


def generate_still_command(ledger, args):
    job = launch_still(ledger, {"beat": args.beat, "expected": args.expected}, args.request_id)
    ledger.save("ai-generate-still")
    payload = {"job": public_job(job), "beat": args.beat}
    if _should_dispatch(job):
        payload["ai_dispatch"] = {"project": str(_project_root(ledger)), "job": job["id"]}
    return payload


def approve_command(ledger, args):
    payload = {
        "version": args.version,
        "by": args.by,
        "decision": args.decision,
        "comment": args.comment,
        "signature": args.signature,
    }
    if payload["signature"] is None:
        version = (ledger.data.get("ai") or {}).get("versions", {}).get(args.version)
        if not version:
            raise ValueError("Select an existing AI result of the required type.")
        payload["signature"] = version_signature(version)
    return review(ledger, payload)


def resume_command(ledger, args):
    job = (ledger.data.get("ai") or {}).get("jobs", {}).get(args.job)
    if not job:
        raise ValueError("This AI job is not in the current project.")
    project = str(_project_root(ledger))
    if job.get("state") == "complete" and job.get("result"):
        return {"job": public_job(job), "resubmitted": False}
    if job.get("state") == "queued" and job.get("submit_outcome") == "not_sent":
        return {"job": public_job(job), "resubmitted": False, "ai_dispatch": {"project": project, "job": job["id"]}}
    if job.get("state") == "running" and job.get("submit_outcome") == "not_sent":
        job["state"] = "unknown"
        job["submit_outcome"] = "unknown"
        job["error"] = _error_payload(
            "The native still submit outcome is unknown. Resume will not send it again.", "unknown"
        )
        ledger.save("ai-resume-unknown")
        return {"job": public_job(job), "resubmitted": False}
    if (
        _recorded_artifact(job)
        and (job.get("remote") or {}).get("artifact_sha256")
        and job.get("state") in {"remote_pending", "downloading", "unknown", "failed"}
    ):
        return {
            "job": public_job(job),
            "resubmitted": False,
            "ai_dispatch": {"project": project, "job": job["id"], "retrieve": True},
        }
    return {"job": public_job(job), "resubmitted": False}


def dispatch_after_audit(result):
    info = result.pop("ai_dispatch", None) if isinstance(result, dict) else None
    if not isinstance(info, dict):
        return result
    start_worker(info["project"], info["job"], retrieve=bool(info.get("retrieve")))
    inline = os.environ.get(INLINE_ENV) == "1"
    result["worker"] = "inline" if inline else "started"
    if inline:
        ledger = Ledger(info["project"], recover=False)
        job = (ledger.data.get("ai") or {}).get("jobs", {}).get(info["job"])
        if job:
            result["job"] = public_job(job)
    return result


def handle_select(project, data):
    with project_lock(project):
        beat = select(Ledger(project), data)
    return {
        "beat": {
            "id": beat["id"],
            "selected": beat.get("selected"),
            "mode": beat.get("mode"),
            "comment": beat.get("comment") or "",
            "fingerprint": beat.get("fingerprint"),
        }
    }


def handle_review(project, data):
    payload = dict(data)
    payload.setdefault("by", payload.get("by") or "Storyboard")
    with project_lock(project):
        return review(Ledger(project), payload)


def handle_generate(project, data):
    nonce = data.get("requestId") or data.get("request_id") or data.get("nonce")
    with project_lock(project):
        ledger = Ledger(project)
        job = launch_still(ledger, data, nonce)
        ledger.save("ai-generate-still")
        dispatch = _should_dispatch(job)
        public = public_job(job)
        job_id = job["id"]
    if dispatch:
        start_worker(project, job_id)
        if os.environ.get(INLINE_ENV) == "1":
            ledger = Ledger(project, recover=False)
            job = (ledger.data.get("ai") or {}).get("jobs", {}).get(job_id)
            if job:
                public = public_job(job)
    return {"job": public}


def handle_state(project):
    return public_board(Ledger(project, recover=False))


def review_records(ledger, ident):
    ai = ledger.data.get("ai")
    if not isinstance(ai, dict):
        return []
    records = []
    for version in (ai.get("versions") or {}).values():
        if not isinstance(version, dict) or version.get("kind") != "image":
            continue
        beat = (ai.get("beats") or {}).get(version.get("beat")) or {}
        job = (ai.get("jobs") or {}).get(version.get("job")) or {}
        approval = version.get("approval") or {}
        records.append(
            {
                "id": "ai:" + str(version.get("beat")),
                "project": ident,
                "beat": version.get("beat"),
                "fingerprint": version.get("inputs"),
                "selected": (job.get("request") or {}).get("alternative") or beat.get("selected"),
                "comment": (
                    approval.get("comment") or ""
                    if approval.get("state") in {"approved", "changes", "rejected"}
                    else (job.get("request") or {}).get("comment") or ""
                ),
                "mode": beat.get("mode") or "economy",
                "job": version.get("job"),
                "version": version.get("id"),
                "signature": version_signature(version),
                "state": approval.get("state") or "pending",
                "path": version.get("path"),
            }
        )
    return records


def apply_review_import(ledger, rows, *, by):
    applied = []
    skipped = []
    unchanged = []
    if not rows:
        return applied, skipped, unchanged
    if not isinstance(ledger.data.get("ai"), dict):
        skipped.extend(
            {
                "id": (row or {}).get("id") or "ai",
                "reason": "missing_ai",
                "detail": "This project has no AI records.",
            }
            for row in rows
        )
        return applied, skipped, unchanged
    for row in rows:
        result = _import_row(ledger, row, by)
        if result == "applied":
            applied.append((row or {}).get("version"))
        elif result == "unchanged":
            unchanged.append((row or {}).get("version") or (row or {}).get("id") or "ai")
        else:
            skipped.append(result)
    return applied, skipped, unchanged


def _skip(ident, reason, detail):
    return {"id": ident, "reason": reason, "detail": detail}


def _import_row(ledger, row, by):
    from .ai_state import checked_version

    if not isinstance(row, dict):
        return _skip("ai", "invalid", "Invalid AI review row.")
    ident = row.get("id") or "ai"
    decision = row.get("decision") or row.get("state")
    version_id = row.get("version")
    if decision in (None, "pending"):
        result = "unchanged"
    elif not version_id:
        result = _skip(ident, "missing_version", "AI review needs a version.")
    else:
        try:
            version, _path = checked_version(ledger, version_id)
            current = version.get("approval") or {}
            if row.get("signature") != version_signature(version):
                result = _skip(
                    ident, "signature_mismatch", "The displayed AI version changed; review the exact current result."
                )
            elif decision not in ("approved", "changes", "rejected"):
                result = _skip(ident, "invalid_decision", "Choose an explicit human decision.")
            elif current.get("state") == decision and current.get("signature") == version_signature(version):
                result = "unchanged"
            else:
                version["approval"] = {
                    "state": decision,
                    "by": by,
                    "at": now(),
                    "signature": version_signature(version),
                    "comment": str(row.get("comment") or "")[:32000],
                }
                result = "applied"
        except ValueError as exc:
            result = _skip(ident, "invalid", str(exc))
    return result


def storyboard_section(ledger):
    ai = ledger.data.get("ai")
    if not isinstance(ai, dict) or not ai.get("plan"):
        return ""
    style = (ai.get("style") or {}).get("prompt") or ""
    jobs = ai.get("jobs") or {}
    versions = ai.get("versions") or {}
    parts = [
        '<section class="ai-board" aria-label="AI production">',
        "<h2>AI stills</h2>",
        f'<p class="ai-style" data-ai-style>{_esc(style)}</p>',
    ]
    routing = (ai.get("plan") or {}).get("routing") or []
    for record in routing:
        if not isinstance(record, dict):
            continue
        if record.get("route") != "ai":
            parts.append(
                f'<p class="ai-route" data-ai-route="{_esc(record.get("route"))}" data-ai-beat="{_esc(record.get("id"))}">'
                f"{_esc((record.get('route') or '').title())} · {_esc(record.get('title') or record.get('id'))}</p>"
            )
            continue
        beat = (ai.get("beats") or {}).get(record.get("id"))
        if not isinstance(beat, dict):
            continue
        job = next(
            (
                row
                for row in reversed(list(jobs.values()))
                if isinstance(row, dict)
                and (row.get("request") or {}).get("beat") == beat["id"]
                and (row.get("request") or {}).get("inputs") == beat.get("fingerprint")
            ),
            None,
        )
        version = versions.get((job or {}).get("result") or "") if job else None
        parts.append(_beat_card(beat, job, version if isinstance(version, dict) else None))
    parts.append("</section>")
    return "".join(parts)


def _card_state_attrs(job, version):
    parts = []
    if job:
        parts.append(f' data-ai-job="{_esc(job.get("id"))}"')
        parts.append(f' data-ai-state="{_esc(job.get("state") or "")}"')
    if version:
        approval = (version.get("approval") or {}).get("state") or "pending"
        parts.append(f' data-ai-version="{_esc(version.get("id"))}"')
        parts.append(f' data-ai-signature="{_esc(version_signature(version))}"')
        parts.append(f' data-ai-approval="{_esc(approval)}"')
    return "".join(parts)


def _beat_card(beat, job, version):
    beat_id = beat["id"]
    selected = beat.get("selected") or ""
    mode = beat.get("mode") or "economy"
    radios = []
    for alternative in beat.get("alternatives") or []:
        checked = " checked" if alternative.get("id") == selected else ""
        radios.append(
            '<label><input type="radio" name="ai-alt-'
            f'{_esc(beat_id)}" value="{_esc(alternative.get("id"))}" data-ai-alternative{checked}> '
            f"{_esc(alternative.get('description'))}</label>"
        )
    progress = ""
    if job:
        progress = public_job(job).get("state") or ""
        if job.get("error"):
            progress = sanitize_public_text(
                (job.get("error") or {}).get("message") if isinstance(job.get("error"), dict) else job.get("error")
            )
    figure = ""
    review_hidden = " hidden"
    if version:
        figure = (
            f'<img src="{_esc(version.get("path"))}" alt="Generated illustration">'
            "<figcaption>Generated illustration</figcaption>"
        )
        review_hidden = ""
    details = _details(beat, job, version)
    return (
        f'<article class="ai-card" data-ai-beat="{_esc(beat_id)}" data-ai-fingerprint="{_esc(beat.get("fingerprint"))}" '
        f'data-ai-mode="{_esc(mode)}"{_card_state_attrs(job, version)}>'
        f"<h3>{_esc(beat.get('title') or beat_id)}</h3>"
        f'<p class="ai-purpose">{_esc(beat.get("purpose"))}</p>'
        f'<blockquote class="ai-text">{_esc(beat.get("text"))}</blockquote>'
        f'<fieldset class="ai-alternatives">{"".join(radios)}</fieldset>'
        f"<label>Comment <textarea data-ai-comment>{_esc(beat.get('comment') or '')}</textarea></label>"
        "<label>Comparison <select data-ai-mode>"
        f'<option value="economy"{" selected" if mode == "economy" else ""}>Descriptions, then one still</option>'
        '<option value="images" disabled'
        + (" selected" if mode == "images" else "")
        + ">Three-image comparison is not available yet</option>"
        "</select></label>"
        '<button type="button" data-ai-generate'
        + (" disabled" if mode != "economy" else "")
        + ">Generate still</button>"
        '<button type="button" data-ai-video disabled>Video is not available on the GPT subscription route</button>'
        f"<p data-ai-progress>{_esc(progress)}</p>"
        f"<figure data-ai-result>{figure}</figure>"
        f'<div class="ai-review"{review_hidden}>'
        '<button type="button" data-ai-decision="approved">Approve this still</button>'
        '<button type="button" data-ai-decision="changes">Request changes</button>'
        '<button type="button" data-ai-decision="rejected">Reject</button>'
        "</div>"
        f'<details class="ai-details"><summary>Details</summary>{details}</details>'
        "</article>"
    )


def _details(beat, job, version):
    public = public_job(job) if job else {}
    lines = [
        f"<p>Beat {_esc(beat.get('id'))} · mode {_esc(beat.get('mode'))}</p>",
        (
            f"<p>Job {_esc(public.get('id') or 'none')} · route {_esc(public.get('route') or 'gpt-subscription')} · "
            f"state {_esc(public.get('state') or 'idle')}</p>"
        ),
    ]
    if version:
        lines.append(
            f"<p>{_esc(version.get('width'))}×{_esc(version.get('height'))} {_esc(version.get('codec'))} · "
            f"sha256 {_esc(version.get('sha256'))} · original {_esc(version.get('original_sha256'))}</p>"
        )
        lines.append("<p>Generated illustration, not documentary evidence. Generation is not approval.</p>")
    if public.get("error"):
        lines.append(f"<p>{_esc(public.get('error'))}</p>")
    return "".join(lines)


def start_worker(project, job_id, *, retrieve=False):
    if os.environ.get(INLINE_ENV) == "1":
        run_worker(project, job_id, retrieve=retrieve)
        return None
    return spawn_worker(project, job_id, retrieve=retrieve)


def spawn_worker(project, job_id, *, retrieve=False):
    scripts = Path(__file__).resolve().parents[1]
    env = os.environ.copy()
    existing = env.get("PYTHONPATH")
    env["PYTHONPATH"] = str(scripts) + (os.pathsep + existing if existing else "")
    env["PYTHONUNBUFFERED"] = "1"
    for name in WORKER_ENV:
        value = os.environ.get(name)
        if value is not None:
            env[name] = value
    if any(os.environ.get(name) for name in (FIXTURE_ENV, INLINE_ENV, CRASH_ENV)) and not env.get(APP_SERVER_ENV):
        raise ValueError("Test fixture env is set but GETBROLLS_CODEX_APP_SERVER is missing.")
    command = [
        sys.executable,
        "-m",
        "getbrolls.ai",
        "--worker",
        "--project",
        str(Path(project).resolve()),
        "--job",
        str(job_id),
    ]
    if retrieve:
        command.append("--retrieve")
    kwargs = {
        "cwd": str(Path(project).resolve()),
        "env": env,
        "stdin": subprocess.DEVNULL,
        "stdout": subprocess.DEVNULL,
        "stderr": subprocess.DEVNULL,
        "close_fds": True,
    }
    if os.name == "nt":
        flags = 0
        if hasattr(subprocess, "CREATE_NO_WINDOW"):
            flags |= subprocess.CREATE_NO_WINDOW
        if hasattr(subprocess, "CREATE_NEW_PROCESS_GROUP"):
            flags |= subprocess.CREATE_NEW_PROCESS_GROUP
        if flags:
            kwargs["creationflags"] = flags
        startup = subprocess.STARTUPINFO()
        startup.dwFlags |= getattr(subprocess, "STARTF_USESHOWWINDOW", 0)
        kwargs["startupinfo"] = startup
    else:
        kwargs["start_new_session"] = True
    return subprocess.Popen(command, **kwargs)  # noqa: S603 - pinned interpreter and module path.


def run_worker(project, job_id, *, retrieve=False):
    try:
        if retrieve:
            _retrieve_worker(project, job_id)
            return
        _produce_worker(project, job_id)
    except (ValueError, OSError, KeyError) as exc:
        _store_terminal(project, job_id, {"state": "failed", "message": str(exc), "code": "worker"})


def _is_reparse(path):
    path = Path(path)
    try:
        info = os.lstat(path)
    except FileNotFoundError:
        return False
    except OSError:
        return True
    if stat.S_ISLNK(info.st_mode):
        return True
    try:
        if path.is_symlink():
            return True
    except OSError:
        return True
    attrs = getattr(info, "st_file_attributes", 0)
    return bool(attrs & stat.FILE_ATTRIBUTE_REPARSE_POINT)


def _chain_inside(root, path):
    """Reject a symlink or junction anywhere from `path` up through `root`."""
    root = Path(root)
    cursor = Path(path)
    root_key = os.path.normcase(os.path.normpath(str(root)))
    while True:
        if _is_reparse(cursor):
            raise ValueError("AI media escaped through a symlink or junction.")
        if os.path.normcase(os.path.normpath(str(cursor))) == root_key:
            return
        parent = cursor.parent
        if parent == cursor:
            break
        cursor = parent
    raise ValueError("AI media is outside the project.")


def _brolls_root(project):
    root = Path(project).resolve() / "brolls"
    if _is_reparse(root) or not root.is_dir():
        raise ValueError("AI storage escaped through a symlink or junction.")
    return root


def _job_dir(brolls, job_id):
    directory = Path(brolls) / "ai-work" / identifier(job_id, "Job id")
    _chain_inside(brolls, directory)
    return directory


def _safe_artifact(value):
    if (
        not isinstance(value, str)
        or not value
        or len(value) > MAX_ARTIFACT_PATH
        or "\\" in value
        or ":" in value
        or "\0" in value
        or value.startswith("/")
    ):
        return False
    path = Path(value)
    if path.is_absolute() or ".." in path.parts or any(part in {"", ".", ".."} for part in path.parts):
        return False
    return path.suffix.lower() in {".png", ".jpg", ".jpeg"}


def _recorded_artifact(job):
    remote = job.get("remote") if isinstance(job, dict) and isinstance(job.get("remote"), dict) else None
    if not remote:
        return None
    artifact = remote.get("artifact")
    return artifact if _safe_artifact(artifact) else None


def _merge_remote(job, remote):
    if not isinstance(remote, dict):
        return
    info = dict(job.get("remote") or {})
    for key in ("threadId", "turnId"):
        value = remote.get(key)
        if (
            isinstance(value, str)
            and value
            and len(value) <= MAX_REMOTE_ID
            and "\0" not in value
            and "://" not in value
        ):
            info[key] = value
    artifact = remote.get("artifact")
    if _safe_artifact(artifact) and not info.get("artifact_sha256"):
        info["artifact"] = artifact
    job["remote"] = info


def _claim(project, job_id):
    with project_lock(project):
        ledger = Ledger(project)
        job = (ledger.data.get("ai") or {}).get("jobs", {}).get(job_id)
        if not job:
            raise ValueError("This AI job is not in the current project.")
        if job.get("state") == "unknown" or job.get("submit_outcome") == "unknown":
            return None, ledger
        if job.get("state") != "queued" or job.get("submit_outcome") != "not_sent":
            return None, ledger
        job["state"] = "running"
        job["submit_outcome"] = "not_sent"
        job["error"] = None
        ledger.save("ai-submit-intent")
        return job, ledger


def _produce_worker(project, job_id):
    job, _ledger = _claim(project, job_id)
    if job is None:
        return
    if os.environ.get(CRASH_ENV) == "submit":
        if os.environ.get(INLINE_ENV) == "1":
            return
        os._exit(1)
    workdir = _job_dir(_brolls_root(project), job_id)
    workdir.mkdir(parents=True, exist_ok=True)

    def on_submitted(remote):
        with project_lock(project):
            ledger = Ledger(project)
            current = (ledger.data.get("ai") or {}).get("jobs", {}).get(job_id)
            if not current:
                return
            current["submit_outcome"] = "accepted"
            current["state"] = "remote_pending"
            current["remote"] = dict(remote or {})
            ledger.save("ai-submitted")

    timeout = float(os.environ.get("GETBROLLS_AI_TIMEOUT") or TIMEOUT_S)
    outcome = generate_still(job["request"]["prompt"], workdir, timeout=timeout, on_submitted=on_submitted)
    _finish_outcome(project, job, outcome)


def _retrieve_job(project, job_id):
    with project_lock(project):
        ledger = Ledger(project)
        job = (ledger.data.get("ai") or {}).get("jobs", {}).get(job_id)
        if not job or job.get("state") == "complete":
            return None
        if not _recorded_artifact(job) or not (job.get("remote") or {}).get("artifact_sha256"):
            return None
        return job


def _retrieve_worker(project, job_id):
    job = _retrieve_job(project, job_id)
    if job is None:
        return
    try:
        brolls = _brolls_root(project)
        workdir = _job_dir(brolls, job_id)
        artifact = _recorded_artifact(job)
        if not artifact:
            return
        found = _confined_original(workdir, workdir / artifact)
        if digest(found) != job["remote"]["artifact_sha256"]:
            raise ValueError("The recorded native still changed before retrieval.")
        version = _ingest_still(brolls, job, found)
    except (ValueError, OSError) as exc:
        _store_terminal(project, job_id, {"state": "failed", "message": str(exc), "code": "artifact"})
        return
    _commit_result(project, job_id, version)


def _commit_result(project, job_id, version, remote=None):
    with project_lock(project):
        ledger = Ledger(project)
        current = (ledger.data.get("ai") or {}).get("jobs", {}).get(job_id)
        if not current or current.get("state") == "complete":
            rel = version["path"]
            retained = (ledger.data.get("ai") or {}).get("versions", {}).values()
            if not any(row.get("path") == rel for row in retained):
                target = ledger.root / rel
                _chain_inside(ledger.root, target)
                target.unlink(missing_ok=True)
            return
        _merge_remote(current, remote)
        attach_result(ledger, current, version)
        ledger.save("ai-complete")


def _finish_outcome(project, job, outcome):
    job_id = job["id"]
    with project_lock(project):
        ledger = Ledger(project)
        current = (ledger.data.get("ai") or {}).get("jobs", {}).get(job_id)
        if not current or current.get("state") == "complete":
            return
    status = (outcome or {}).get("status")
    remote = (outcome or {}).get("remote")
    if status == "complete":
        try:
            brolls = _brolls_root(project)
            workdir = _job_dir(brolls, job_id)
            original = _confined_original(workdir, Path(outcome["path"]))
            original_hash = digest(original)
            with project_lock(project):
                ledger = Ledger(project)
                current = ledger.data["ai"]["jobs"][job_id]
                if current.get("state") == "complete":
                    return
                recorded = current.get("remote") or {}
                if recorded.get("artifact_sha256") and (
                    recorded["artifact_sha256"] != original_hash
                    or recorded.get("artifact") != original.relative_to(workdir).as_posix()
                ):
                    return
                _merge_remote(current, remote)
                current["remote"] = dict(current.get("remote") or {})
                current["remote"]["artifact"] = original.relative_to(workdir).as_posix()
                current["remote"]["artifact_sha256"] = original_hash
                current["state"] = "downloading"
                ledger.save("ai-result-received")
            version = _ingest_still(brolls, job, original)
        except (ValueError, OSError, KeyError) as exc:
            _store_terminal(
                project, job_id, {"state": "failed", "message": str(exc), "code": "artifact", "remote": remote}
            )
            return
        _commit_result(project, job_id, version, remote)
        return
    if status == "unknown":
        _store_terminal(
            project,
            job_id,
            {
                "state": "unknown",
                "message": (outcome or {}).get("error") or "unknown",
                "code": "unknown",
                "remote": remote,
            },
        )
        return
    code = (outcome or {}).get("code") or status or "failed"
    if status in {"auth", "quota", "unsupported"}:
        code = status
    _store_terminal(
        project,
        job_id,
        {"state": "failed", "message": (outcome or {}).get("error") or status, "code": code, "remote": remote},
    )


def _store_terminal(project, job_id, fields):
    with project_lock(project):
        ledger = Ledger(project)
        job = (ledger.data.get("ai") or {}).get("jobs", {}).get(job_id)
        if not job or job.get("state") == "complete":
            return
        state_name = fields["state"]
        job["state"] = state_name
        job["submit_outcome"] = "unknown" if state_name == "unknown" else job.get("submit_outcome") or "accepted"
        job["error"] = _error_payload(fields.get("message"), fields.get("code"))
        _merge_remote(job, fields.get("remote"))
        ledger.save("ai-" + state_name)


def _refuse_link(path):
    if path.is_symlink() or not path.is_file():
        raise ValueError("The native still is missing, a symlink, or not a regular file.")
    return path


def _confined_original(workdir, saved):
    _chain_inside(workdir, saved)
    workdir = Path(workdir).resolve()
    path = _refuse_link(Path(saved))
    try:
        resolved = path.resolve()
    except OSError as exc:
        raise ValueError("The native still path could not be resolved.") from exc
    try:
        resolved.relative_to(workdir)
    except ValueError as exc:
        raise ValueError("The native still path escaped the job work directory.") from exc
    if resolved.is_symlink() or not resolved.is_file():
        raise ValueError("The native still is missing, a symlink, or not a regular file.")
    return resolved


def _probe_still(path):
    raw = run(
        [
            "ffprobe",
            "-v",
            "error",
            "-select_streams",
            "v:0",
            "-show_entries",
            "stream=width,height,codec_name,codec_type",
            "-of",
            "json",
            str(path),
        ],
        op="ai_probe",
    )
    data = json.loads(raw)
    videos = [row for row in (data.get("streams") or []) if row.get("codec_type") == "video"]
    if len(videos) != 1:
        raise ValueError("AI still must contain exactly one image stream.")
    stream = videos[0]
    codec = str(stream.get("codec_name") or "").lower()
    if codec not in STILL_CODECS:
        raise ValueError("AI still codec must be png or jpeg.")
    width = int(stream.get("width") or 0)
    height = int(stream.get("height") or 0)
    if width <= 0 or height <= 0:
        raise ValueError("AI still measurements are missing.")
    run(
        ["ffmpeg", "-v", "error", "-xerror", "-i", str(path), "-f", "null", "-"],
        op="ai_decode",
    )
    return {"width": width, "height": height, "codec": codec}


def _ingest_still(brolls, job, saved_path):
    brolls = _brolls_root(brolls.parent)
    request = job["request"]
    workdir = _job_dir(brolls, job["id"])
    original = _confined_original(workdir, saved_path)
    info = _probe_still(original)
    original_hash = digest(original)
    version_id = "still-" + uuid.uuid4().hex[:12]
    rel = "previews/ai-" + version_id + STILL_CODECS[info["codec"]]
    dest = brolls / rel
    _chain_inside(brolls, dest.parent)
    if dest.exists() or dest.is_symlink():
        raise ValueError("AI preview path already exists and will not be overwritten.")
    dest.parent.mkdir(parents=True, exist_ok=True)
    _chain_inside(brolls, dest.parent)
    shutil.copyfile(original, dest)
    if dest.is_symlink() or not dest.is_file():
        dest.unlink(missing_ok=True)
        raise ValueError("AI preview copy is not a regular confined file.")
    copy_info = _probe_still(dest)
    copy_hash = digest(dest)
    if copy_hash != original_hash or (copy_info["width"], copy_info["height"], copy_info["codec"]) != (
        info["width"],
        info["height"],
        info["codec"],
    ):
        dest.unlink(missing_ok=True)
        raise ValueError("AI preview copy does not match the original still.")
    return {
        "id": version_id,
        "beat": request["beat"],
        "kind": "image",
        "alternative": request.get("alternative"),
        "path": rel,
        "sha256": copy_hash,
        "original_sha256": original_hash,
        "inputs": request["inputs"],
        "width": copy_info["width"],
        "height": copy_info["height"],
        "codec": copy_info["codec"],
        "job": job["id"],
        "approval": {"state": "pending"},
    }


def worker_main(argv=None):
    parser = argparse.ArgumentParser(prog="getbrolls.ai")
    parser.add_argument("--worker", action="store_true", required=True)
    parser.add_argument("--project", required=True)
    parser.add_argument("--job", required=True)
    parser.add_argument("--retrieve", action="store_true")
    args = parser.parse_args(argv)
    run_worker(args.project, args.job, retrieve=args.retrieve)
    return 0


if __name__ == "__main__":
    raise SystemExit(worker_main())
