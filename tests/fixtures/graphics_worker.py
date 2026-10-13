#!/usr/bin/env python3
"""Deterministic H.264 stub used by graphics tests. Not the Remotion renderer."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--job", required=True)
    args = parser.parse_args(argv)
    job = json.loads(Path(args.job).read_text(encoding="utf-8"))
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
