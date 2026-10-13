#!/usr/bin/env python3
"""Deterministic H.264 stub for graphics background tests. Not the Remotion renderer.

Offline proof only: refuses remote/private background src and requires the frozen
public/media file when a background is declared. Actual pinned Remotion remains a
coordinator gate.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path


def _refuse(message):
    sys.stderr.write(message + "\n")
    raise SystemExit(2)


def _media_path(public_dir, src):
    if not isinstance(src, str) or not src.startswith("media/"):
        _refuse("offline worker needs background src under media/")
    rest = src[6:]
    if not rest or rest in (".", "..") or "/" in rest or "\\" in rest:
        _refuse("offline worker refused an unsafe background src")
    root = public_dir.resolve()
    path = (public_dir / src).resolve()
    try:
        path.relative_to(root)
    except ValueError:
        _refuse("offline worker background path escaped publicDir")
    if not path.is_file():
        _refuse("offline worker missing frozen background: " + src)
    return path


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--job", required=True)
    args = parser.parse_args(argv)
    job = json.loads(Path(args.job).read_text(encoding="utf-8"))
    dumped = json.dumps(job)
    if "http://" in dumped or "https://" in dumped or "narration/private" in dumped:
        _refuse("offline worker refused remote or private background props")
    props = job.get("props") if isinstance(job.get("props"), dict) else {}
    background = props.get("background")
    if isinstance(background, dict):
        public = Path(job.get("publicDir") or "")
        if not public.is_dir():
            _refuse("offline worker needs job.publicDir with frozen background media")
        _media_path(public, background.get("src"))
        if background.get("kind") not in ("video", "image"):
            _refuse("offline worker background kind must be video or image")
        if background.get("muted") is not True:
            _refuse("offline worker background must be muted")
    output = Path(job["output"])
    output.parent.mkdir(parents=True, exist_ok=True)
    identity = output.parent / "executed-worker.json"
    identity.write_text(json.dumps({"file": str(Path(__file__).resolve())}), encoding="utf-8")
    frames = int(job["durationInFrames"])
    done = subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-v",
            "error",
            "-f",
            "lavfi",
            "-i",
            f"testsrc=size={int(job['width'])}x{int(job['height'])}:rate={job['fps']}",
            "-frames:v",
            str(frames),
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            "-crf",
            "18",
            "-an",
            str(output),
        ],
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    if done.returncode != 0:
        sys.stderr.write((done.stderr or done.stdout or "ffmpeg failed").strip())
        raise SystemExit(done.returncode)
    sys.stdout.write(json.dumps({"ok": True, "output": str(output)}) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
