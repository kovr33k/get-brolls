#!/usr/bin/env python3
"""Release gates and reusable proof from the complete Windows CI; stdlib only."""

from __future__ import annotations

import argparse
import importlib
import io
import json
import os
import platform
import re
import shutil
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
WORKFLOW = ".github/workflows/test.yml"
EVIDENCE_NAME = "windows-verification-"
MAX_EVIDENCE_BYTES = 16384


def run(root: Path, *args: str, capture: bool = False) -> str:
    result = subprocess.run(
        args, cwd=root, check=True, text=True, encoding="utf-8", stdout=subprocess.PIPE if capture else None
    )
    return (result.stdout or "").strip()


def clean_tree(root: Path) -> str:
    if run(root, "git", "status", "--porcelain", capture=True):
        raise ValueError("CI reuse requires a clean tracked and untracked source tree")
    return run(root, "git", "rev-parse", "HEAD^{tree}", capture=True)


def record_ci(root: Path, destination: Path, output: Path) -> None:
    tree = clean_tree(root)
    evidence = {
        "schema": 1,
        "tree": tree,
        "commit": run(root, "git", "rev-parse", "HEAD", capture=True),
        "python": platform.python_version(),
        "platform": platform.system(),
        "run_id": int(os.environ["GITHUB_RUN_ID"]),
        "run_attempt": int(os.environ["GITHUB_RUN_ATTEMPT"]),
    }
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(evidence) + "\n", encoding="utf-8")
    with output.open("a", encoding="utf-8") as stream:
        stream.write(f"tree={tree}\n")


def gh_json(root: Path, endpoint: str) -> Any:
    return json.loads(run(root, "gh", "api", endpoint, capture=True))


def read_evidence(root: Path, repository: str, artifact: dict) -> dict:
    result = subprocess.run(
        ["gh", "api", f"repos/{repository}/actions/artifacts/{int(artifact['id'])}/zip"],
        cwd=root,
        check=True,
        capture_output=True,
    )
    with zipfile.ZipFile(io.BytesIO(result.stdout)) as archive:
        info = archive.getinfo("verification.json")
        if info.file_size > MAX_EVIDENCE_BYTES:
            raise ValueError("Oversized CI evidence")
        evidence = json.loads(archive.read(info))
    if not isinstance(evidence, dict):
        raise ValueError("Invalid CI evidence")
    return evidence


def reusable_ci(root: Path, repository: str, requested_run: int | None = None) -> int | None:
    """Unknown, expired, failed or mismatched evidence always requires full checks."""
    try:
        tree = clean_tree(root)
        if not re.fullmatch(r"[\w.-]+/[\w.-]+", repository):
            raise ValueError("Invalid repository")
        artifacts = gh_json(root, f"repos/{repository}/actions/artifacts?name={EVIDENCE_NAME}{tree}&per_page=100")[
            "artifacts"
        ]
        for artifact in artifacts:
            run_id = int(artifact["workflow_run"]["id"])
            if artifact["expired"] or artifact["name"] != EVIDENCE_NAME + tree:
                continue
            if requested_run is not None and requested_run != run_id:
                continue
            ci = gh_json(root, f"repos/{repository}/actions/runs/{run_id}")
            if (
                ci["status"] != "completed"
                or ci["conclusion"] != "success"
                or ci["path"] != WORKFLOW
                or ci["event"] != "pull_request"
                or ci["repository"]["full_name"].casefold() != repository.casefold()
                or ci["head_repository"]["full_name"].casefold() != repository.casefold()
            ):
                continue
            jobs = gh_json(root, f"repos/{repository}/actions/runs/{run_id}/jobs?per_page=100")["jobs"]
            if not any(
                job["name"] == "Windows checks" and job["status"] == "completed" and job["conclusion"] == "success"
                for job in jobs
            ):
                continue
            evidence = read_evidence(root, repository, artifact)
            if (
                evidence.get("schema") == 1
                and evidence.get("tree") == tree
                and evidence.get("platform") == platform.system() == "Windows"
                and evidence.get("python") == platform.python_version()
                and evidence.get("run_id") == run_id
                and evidence.get("run_attempt") == ci["run_attempt"]
            ):
                return run_id
    except (OSError, subprocess.CalledProcessError, ValueError, KeyError, TypeError, zipfile.BadZipFile):
        print("CI evidence unavailable or invalid; full checks are required.")
    return None


def validate_frontmatter_line(name: str, line: str) -> None:
    if not line or line.startswith((" ", "\t")) or ":" not in line:
        return
    key, value = line.split(":", 1)
    value = value.strip()
    if not value:
        return
    if value[0] in "'\"":
        if value[-1] != value[0]:
            raise ValueError(f"{name}: unclosed quote in {key}")
    elif value.startswith("[") and value.endswith("]"):
        return
    elif ": " in value or " #" in value or value[0] in "[]{}&*!|>%@`":
        raise ValueError(f"{name}: unquoted value in {key}")


def validate_frontmatter(root: Path) -> None:
    try:
        yaml = importlib.import_module("yaml")
    except ImportError:
        yaml = None
    tracked = run(root, "git", "ls-files", "-z", capture=True).split("\0")
    for name in tracked:
        path = root / name
        if path.suffix != ".md" or not path.is_file():
            continue
        match = re.match(r"\A---\n(.*?)\n---\n", path.read_text(encoding="utf-8"), re.DOTALL)
        if match is None:
            continue
        block = match.group(1)
        if yaml is not None:
            yaml.safe_load(block)
            continue
        for line in block.splitlines():
            validate_frontmatter_line(name, line)


def changelog_section(root: Path, version: str) -> str:
    text = (root / "CHANGELOG.md").read_text(encoding="utf-8")
    lines = text.splitlines()
    start = next((i + 1 for i, line in enumerate(lines) if line.startswith(f"## {version} — ")), None)
    if start is None:
        raise ValueError(f"CHANGELOG section missing: {version}")
    end = next((i for i in range(start, len(lines)) if lines[i].startswith("## ")), len(lines))
    section = "\n".join(lines[start:end]).strip()
    if not section:
        raise ValueError(f"CHANGELOG section empty: {version}")
    return section + "\n"


def full_checks(root: Path) -> None:
    run(root, "pwsh", "-NoProfile", "-File", "scripts/install.ps1", "-Check")
    run(root, "pwsh", "-NoProfile", "-File", "scripts/playwright.ps1", "--version")
    run(root, sys.executable, "scripts/gb.py", "doctor")
    run(root, "pwsh", "-NoProfile", "-File", "scripts/check.ps1")
    for script in ("assets/storyboard.js", "assets/review.js"):
        run(root, "node", "--check", script)
    run(
        root,
        "pwsh",
        "-NoProfile",
        "-Command",
        "Get-ChildItem scripts -Filter *.ps1 | ForEach-Object { "
        "[scriptblock]::Create((Get-Content -Raw -LiteralPath $_.FullName)) | Out-Null }",
    )
    git_bash = Path(os.environ.get("PROGRAMFILES", "")) / "Git/bin/bash.exe"
    bash = str(git_bash) if git_bash.is_file() else shutil.which("bash")
    if bash is None:
        raise ValueError("Git Bash is required to validate the retained optional shell helpers")
    for script in sorted((root / "scripts").rglob("*.sh")):
        run(root, bash, "-n", script.relative_to(root).as_posix())


def preflight(root: Path, version: str | None, repository: str, ci_run: int | None, notes: Path | None) -> None:
    print("==> version coherence", flush=True)
    source = (root / "scripts/getbrolls/__init__.py").read_text(encoding="utf-8")
    match = re.search(r'__version__\s*=\s*"([^"]+)"', source)
    if match is None:
        raise ValueError("__version__ missing")
    actual = match.group(1)
    release_version: str = version or actual
    if actual != release_version:
        raise ValueError(f"--version {release_version} != __version__ {actual}")
    run(root, sys.executable, "-m", "unittest", "discover", "-s", "tests", "-p", "test_version_coherence.py")
    print("==> frontmatter", flush=True)
    validate_frontmatter(root)
    print("==> tracked release contents", flush=True)
    run(root, sys.executable, "-m", "unittest", "discover", "-s", "tests", "-p", "test_repository.py")
    print("==> skill mirror and anchors", flush=True)
    run(root, sys.executable, "scripts/gen_skill_mirror.py", "--check")
    run(root, sys.executable, "scripts/check_anchors.py")
    print("==> CHANGELOG section", flush=True)
    section = changelog_section(root, release_version)
    verified = reusable_ci(root, repository, ci_run) if repository else None
    if verified is None:
        print("==> complete Windows checks (no matching valid CI)", flush=True)
        full_checks(root)
    else:
        print(f"==> reused complete Windows CI: {repository}/actions/runs/{verified}", flush=True)
    if notes is not None:
        notes.write_text(section, encoding="utf-8")
    print(f"PREFLIGHT OK {release_version}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ref", help="Validate an exact commit in a temporary full local clone")
    parser.add_argument("--version")
    parser.add_argument("--ci-repository", default="", help="owner/repository; verify GitHub CI evidence before reuse")
    parser.add_argument("--ci-run", type=int, help="Restrict reuse to this successful run; never bypass verification")
    parser.add_argument("--notes-file", type=Path, help="Write release notes only after all gates pass")
    parser.add_argument("--record-ci", type=Path, help="Record actual checkout after all Windows CI checks pass")
    parser.add_argument("--github-output", type=Path)
    args = parser.parse_args(argv)
    if args.record_ci and args.github_output is None:
        parser.error("--record-ci requires --github-output")
    try:
        if args.record_ci:
            record_ci(ROOT, args.record_ci, args.github_output)
        elif args.ref:
            commit = run(ROOT, "git", "rev-parse", "--verify", f"{args.ref}^{{commit}}", capture=True)
            with tempfile.TemporaryDirectory(prefix="get-brolls-preflight-") as directory:
                root = Path(directory).resolve() / "repo"
                run(ROOT, "git", "clone", "--quiet", "--no-hardlinks", str(ROOT), str(root))
                run(root, "git", "checkout", "--quiet", "--detach", commit)
                preflight(root, args.version, args.ci_repository, args.ci_run, args.notes_file)
        else:
            preflight(ROOT, args.version, args.ci_repository, args.ci_run, args.notes_file)
    except (OSError, subprocess.CalledProcessError, ValueError, KeyError) as exc:
        print(f"PREFLIGHT FAILED: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
