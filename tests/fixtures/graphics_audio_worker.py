#!/usr/bin/env python3
"""Deterministic H.264+AAC stub for graphics audio tests. Not the Remotion renderer.

Offline proof only: muxes the frozen cue assets at their start/trim/gain instead of
a fixed oscillator. Does not embed voice-over even if a private path is on disk.
Actual pinned Remotion remains a coordinator gate.
"""

from __future__ import annotations

import argparse
import json
import math
import subprocess
import sys
from pathlib import Path


def _refuse(message):
    sys.stderr.write(message + "\n")
    raise SystemExit(2)


def _cue_path(public_dir, src):
    if not isinstance(src, str) or not src.startswith("audio/"):
        _refuse("offline worker needs cue src under audio/")
    rest = src[6:]
    if not rest or rest in (".", "..") or "/" in rest or "\\" in rest:
        _refuse("offline worker refused an unsafe cue src")
    root = public_dir.resolve()
    path = (public_dir / src).resolve()
    try:
        path.relative_to(root)
    except ValueError:
        _refuse("offline worker cue path escaped publicDir")
    if not path.is_file():
        _refuse("offline worker missing cue audio: " + src)
    return path


def _cue_files(job, cues):
    public = Path(job.get("publicDir") or "")
    if not public.is_dir():
        _refuse("offline worker needs job.publicDir with frozen cue audio")
    files = []
    for cue in cues:
        if not isinstance(cue, dict):
            _refuse("offline worker sound_cues entries must be objects")
        files.append((cue, _cue_path(public, cue.get("src"))))
    return files


def _finite_number(value, label):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        _refuse("offline worker cue " + label + " must be a finite number")
    number = float(value)
    if not math.isfinite(number):
        _refuse("offline worker cue " + label + " must be a finite number")
    return number


def _nonneg_int(value, label):
    number = _finite_number(value, label)
    if number != int(number) or number < 0:
        _refuse("offline worker cue " + label + " must be a nonnegative integer")
    return int(number)


def _audio_filter(cues, fps, duration_s):
    filters = []
    labels = []
    for index, cue in enumerate(cues):
        trim_frames = _nonneg_int(cue.get("trim_before_frame"), "trim_before_frame")
        cue_frames = _nonneg_int(cue.get("duration_in_frames"), "duration_in_frames")
        start_frames = _nonneg_int(cue.get("start_frame"), "start_frame")
        if cue_frames < 1:
            _refuse("offline worker cue duration_in_frames must be positive")
        gain = _finite_number(cue.get("gain"), "gain")
        trim_s = trim_frames / fps
        dur_s = cue_frames / fps
        delay_ms = round((start_frames / fps) * 1000)
        src_index = index + 1
        label = "a" + str(index)
        filters.append(
            f"[{src_index}:a]atrim=start={trim_s}:duration={dur_s},asetpts=PTS-STARTPTS,"
            f"volume={gain},adelay={delay_ms}|{delay_ms},apad=whole_dur={duration_s}[{label}]"
        )
        labels.append("[" + label + "]")
    fmt = "aformat=sample_fmts=fltp:sample_rates=48000:channel_layouts=stereo[aout]"
    if len(labels) == 1:
        filters.append(labels[0] + fmt)
    else:
        filters.append(
            "".join(labels)
            + "amix=inputs="
            + str(len(labels))
            + ":duration=longest:dropout_transition=0:normalize=0,"
            + fmt
        )
    return ";".join(filters)


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--job", required=True)
    args = parser.parse_args(argv)
    job = json.loads(Path(args.job).read_text(encoding="utf-8"))
    output = Path(job["output"])
    output.parent.mkdir(parents=True, exist_ok=True)
    identity = output.parent / "executed-worker.json"
    props = job.get("props") if isinstance(job.get("props"), dict) else {}
    for forbidden in ("vo", "source_ref", "vo_preview"):
        if forbidden in props:
            _refuse("voice-over must not appear in job props")
    frames = int(job["durationInFrames"])
    fps = float(job["fps"])
    duration = frames / fps
    width = int(job["width"])
    height = int(job["height"])
    audio = job.get("audio") if isinstance(job.get("audio"), dict) else None
    cues = props.get("sound_cues") if isinstance(props.get("sound_cues"), list) else []
    command = [
        "ffmpeg",
        "-y",
        "-v",
        "error",
        "-f",
        "lavfi",
        "-i",
        f"testsrc=size={width}x{height}:rate={fps}",
    ]
    consumed = []
    maps = ["-map", "0:v"]
    audio_opts = ["-an"]
    if audio and audio.get("mode") == "effects" and audio.get("codec") == "aac":
        if not cues:
            _refuse("offline worker effects job is missing sound_cues")
        pairs = _cue_files(job, cues)
        consumed = [str(path) for _cue, path in pairs]
        for _cue, path in pairs:
            command.extend(["-i", str(path)])
        command.extend(["-filter_complex", _audio_filter(cues, fps, duration)])
        maps.extend(["-map", "[aout]"])
        audio_opts = ["-c:a", "aac", "-shortest"]
    command.extend(maps)
    command.extend(
        [
            "-frames:v",
            str(frames),
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            "-colorspace",
            "bt709",
            "-color_primaries",
            "bt709",
            "-color_trc",
            "bt709",
            "-crf",
            "18",
        ]
    )
    command.extend(audio_opts)
    identity.write_text(
        json.dumps({"file": str(Path(__file__).resolve()), "offline": True, "cues": consumed}),
        encoding="utf-8",
    )
    command.append(str(output))
    done = subprocess.run(command, check=False, capture_output=True, text=True, encoding="utf-8")
    if done.returncode != 0:
        sys.stderr.write((done.stderr or done.stdout or "ffmpeg failed").strip())
        raise SystemExit(done.returncode)
    sys.stdout.write(json.dumps({"ok": True, "output": str(output), "offline": True}) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
