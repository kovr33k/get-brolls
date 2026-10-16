"""Bounded decoding and temporal evidence for saved graphics video references."""

from __future__ import annotations

import json
import math
import re
import subprocess
import tempfile
from fractions import Fraction
from pathlib import Path

from .config import tool_path
from .ledger import digest

MAX_VIDEO_BYTES = 64 * 1024 * 1024
MAX_PROCESS_SECONDS = 120
MAX_WIDTH = 3840
MAX_HEIGHT = 2160
MAX_FPS = 120
MIN_SAMPLES = 3
MAX_SAMPLES = 24
MAX_RECORD_BYTES = 32_768


def probe(path, *, decode=True):
    result = subprocess.run(  # noqa: S603 - pinned probe, fixed flags, confined staged input.
        [tool_path("ffprobe"), "-v", "error", "-show_streams", "-show_format", "-of", "json", str(path)],
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=15,
    )
    data = json.loads(result.stdout)
    videos = [s for s in data.get("streams", []) if s.get("codec_type") == "video"]
    fmt = data.get("format", {})
    if (
        len(videos) != 1
        or videos[0].get("codec_name") != "h264"
        or "mp4" not in fmt.get("format_name", "").split(",")
        or fmt.get("tags", {}).get("major_brand", "").strip() == "qt"
    ):
        raise ValueError("Supply an ordinary MP4 with one H.264 video stream.")
    video = videos[0]
    width, height = video.get("width", 0), video.get("height", 0)
    duration = float(video.get("duration") or fmt.get("duration", 0))
    fps = float(Fraction(video.get("avg_frame_rate", "0")))
    if (
        not width
        or not height
        or max(width, height) > MAX_WIDTH
        or min(width, height) > MAX_HEIGHT
        or not math.isfinite(duration)
        or duration <= 0
        or not 0 < fps <= MAX_FPS
    ):
        raise ValueError("Video must have measured duration, at most 3840×2160 pixels and 120 fps.")
    if decode:
        subprocess.run(  # noqa: S603 - full bounded decode; never silently trim the uploaded original.
            [
                tool_path("ffmpeg"),
                "-v",
                "error",
                "-xerror",
                "-i",
                str(path),
                "-map",
                "0:v:0",
                "-map",
                "0:a?",
                "-f",
                "null",
                "-",
            ],
            check=True,
            capture_output=True,
            timeout=MAX_PROCESS_SECONDS,
        )
    return {"width": width, "height": height, "duration_s": duration, "fps": fps, "codec": "h264"}


def validate_measurements(ref):
    if (
        ref.get("codec") != "h264"
        or not isinstance(ref.get("duration_s"), (float, int))
        or isinstance(ref.get("duration_s"), bool)
        or not math.isfinite(ref["duration_s"])
        or ref["duration_s"] <= 0
        or not isinstance(ref.get("fps"), (float, int))
        or isinstance(ref.get("fps"), bool)
        or not 0 < ref["fps"] <= MAX_FPS
        or max(ref["width"], ref["height"]) > MAX_WIDTH
        or min(ref["width"], ref["height"]) > MAX_HEIGHT
    ):
        raise ValueError("Invalid saved video measurements.")


def inspect(root, request, reference, args):
    from . import graphics as g
    from . import graphics_references as refs
    from .media import scan_sheet

    source = refs.checked_image(root, reference)
    wording = args.wording
    if not g._bounded_prose(wording) or wording not in request["text"]:
        raise ValueError("Record the exact original interval/whole-clip wording from the prompt.")
    if args.whole:
        if args.start is not None or args.end is not None:
            raise ValueError("Choose explicit whole clip or a resolved start/end interval.")
        start, end = 0.0, reference["duration_s"]
    else:
        start, end = args.start, args.end
        if (
            not isinstance(start, (int, float))
            or not isinstance(end, (int, float))
            or not math.isfinite(start)
            or not math.isfinite(end)
            or not 0 <= start < end <= reference["duration_s"]
        ):
            raise ValueError(
                "Resolve an explicit interval within the measured source duration; no interval was guessed."
            )
    if not MIN_SAMPLES <= args.frames <= MAX_SAMPLES:
        raise ValueError("Temporal inspection needs 3–24 samples; the original remains available for closer viewing.")
    if (end - start) * reference["fps"] < MIN_SAMPLES:
        raise ValueError(
            "The resolved interval has fewer than three nominal source frames; it cannot establish temporal behavior. Inspect the original and clarify the intended use."
        )
    identity = {
        "request_id": request["id"],
        "label": reference["label"],
        "source_sha256": reference["sha256"],
        "wording": wording,
        "whole": args.whole,
        "start_s": start,
        "end_s": end,
        "frames": args.frames,
    }
    ident = g._payload_hash(identity)
    rel = "graphics-data/reference-inspections/" + ident
    folder = g._confine_planned(root, Path(root) / rel)
    if folder.exists():
        return checked_inspection(root, rel + "/inspection.json", identity)
    folder.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=folder.parent, prefix=".inspect-") as temporary:
        stage = Path(temporary)
        result = scan_sheet(source, stage, "temporal", start, end - start, frames=args.frames)
        sheet = stage / "temporal-scan.jpg"
        record = {
            **identity,
            "record_ref": rel + "/inspection.json",
            "sheet_ref": rel + "/temporal-scan.jpg",
            "sheet_sha256": digest(sheet),
            "frame_times_s": result["frame_times_s"],
            "limitations": "Timestamped low-resolution samples at the listed cadence; inspect the original video for motion between samples. Audio is not analyzed.",
        }
        (stage / "inspection.json").write_text(
            json.dumps(record, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        stage.rename(folder)
    return checked_inspection(root, rel + "/inspection.json", identity)


def checked_inspection(root, rel, identity=None):
    from . import graphics as g

    if not isinstance(rel, str) or not re.fullmatch(
        r"graphics-data/reference-inspections/[0-9a-f]{64}/inspection\.json", rel
    ):
        raise ValueError("Select a generated temporal inspection record.")
    path = g._confine_existing(root, rel, prefixes=("graphics-data/",))
    if path.stat().st_size > MAX_RECORD_BYTES:
        raise ValueError("Invalid temporal inspection record.")
    record = json.loads(path.read_text(encoding="utf-8"))
    actual = validate_inspection(record)
    if record["record_ref"] != rel or (identity is not None and actual != identity):
        raise ValueError("Temporal evidence does not match its resolved request and interval.")
    sheet = g._confine_existing(root, record["sheet_ref"], prefixes=("graphics-data/",))
    if digest(sheet) != record.get("sheet_sha256"):
        raise ValueError("Temporal evidence changed; preserve the original inspection.")
    return record


def validate_inspection(record):
    from . import graphics as g
    from .media import frame_times

    keys = ("request_id", "label", "source_sha256", "wording", "whole", "start_s", "end_s", "frames")
    extra = {"record_ref", "sheet_ref", "sheet_sha256", "frame_times_s", "limitations"}
    if not isinstance(record, dict) or set(record) != set(keys) | extra:
        raise ValueError("Invalid temporal inspection record.")
    actual = {key: record[key] for key in keys}
    if (
        not g._valid_id(record["request_id"])
        or not re.fullmatch(r"R[1-8]", str(record["label"]))
        or not g._sha256(record["source_sha256"])
        or not g._sha256(record["sheet_sha256"])
        or type(record["whole"]) is not bool
        or type(record["frames"]) is not int
        or not MIN_SAMPLES <= record["frames"] <= MAX_SAMPLES
        or not all(type(record[k]) in (int, float) and math.isfinite(record[k]) for k in ("start_s", "end_s"))
        or not 0 <= record["start_s"] < record["end_s"]
        or not g._bounded_prose(record["wording"])
        or not g._bounded_prose(record["limitations"])
    ):
        raise ValueError("Invalid temporal inspection measurements.")
    rel = "graphics-data/reference-inspections/" + g._payload_hash(actual) + "/"
    if (
        record["record_ref"] != rel + "inspection.json"
        or record["sheet_ref"] != rel + "temporal-scan.jpg"
        or record["frame_times_s"] != frame_times(record["start_s"], record["end_s"], record["frames"])
    ):
        raise ValueError("Temporal evidence does not match its declared sample times and interval.")
    return actual
