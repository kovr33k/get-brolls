"""#56: graphics background domain, actual representation clocks and freeze copies."""

from __future__ import annotations

import copy
import json
import re
import stat
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import _isolation  # noqa: F401
from _media import skip_unless_ffmpeg, synth_image, synth_video
from _paths import ROOT

from getbrolls.graphics_media import (
    WEBP_ANIMATION_FLAG,
    _classify_background_kind,
    _resolve_webp_frame_count,
    _webp_riff_frame_count,
    background_readiness,
    freeze_background,
    normalize_background,
    seconds_to_frame,
    validate_background,
)
from getbrolls.ledger import digest as file_digest
from getbrolls.models import approve, candidate
from getbrolls.models import signature as candidate_signature

SCHEMA_PATH = ROOT / "schemas" / "graphics-media.schema.json"
PROFILE = {
    "width": 1920,
    "height": 1080,
    "fps": 30,
    "fps_source": "default",
    "frame_rounding": "half_up_nonnegative",
}
SCENE_S = 3.0
SCENE_FRAMES = 90


def _estimated():
    return {
        "basis": "estimated",
        "duration_in_frames": SCENE_FRAMES,
        "duration_s": SCENE_S,
        "start_s": None,
        "end_s": None,
        "start_frame": None,
        "end_frame": None,
    }


def _brolls(tmp):
    root = Path(tmp) / "brolls"
    (root / "previews").mkdir(parents=True)
    (root / "clips").mkdir()
    return root


def _suitability():
    return {
        "by": "Editor Name",
        "statement": "This saved clip matches the oil-field passage.",
        "at": "2026-10-11T12:00:00+00:00",
    }


def _material(ref, digest_value, **overrides):
    item = {
        "ref": ref,
        "rendered_use": "permitted",
        "raw_redistribution": "restricted",
        "evidence": ["Synthetic project permit for rendered clip use."],
        "conditions": "Rendered composition use; original stays separately held.",
        "sha256": digest_value,
    }
    item.update(overrides)
    return item


def _permit(item):
    item["rights"] = {
        "status": "permitted",
        "license_name": "CC0",
        "license_url": None,
        "evidence": ["Synthetic test permit."],
        "attribution": None,
    }
    item["acquisition"] = {"status": "available", "method": "local", "evidence": ["local file"]}
    return item


def _video_item(root, rel, *, source_id="bg-video", **clip):
    path = root.joinpath(*rel.split("/"))
    path.parent.mkdir(parents=True, exist_ok=True)
    size = clip.get("size", "160x90")
    rate = clip.get("rate", 10)
    start_s = clip.get("start_s", 2.0)
    end_s = clip.get("end_s", 8.0)
    synth_video(path, size=size, duration=clip.get("duration_s", 6), rate=rate)
    item = candidate("local", source_id, "Background video", source_url="https://example.invalid/video")
    item["media"] = {"kind": "video", "duration_s": 20, "width": 160, "height": 90, "fps": rate}
    item["segment"] = {"start_s": start_s, "end_s": end_s, "revision": 1}
    item["output"] = {"path": rel, "sha256": file_digest(path), "verified": True}
    item["asset_type"] = "video"
    _permit(item)
    approve(item, "Editor Name", channel="chat", statement="Use this saved clip.")
    return item, path


def _photo_from_existing(rel, path, *, source_id="bg-photo"):
    item = candidate("local", source_id, "Background photograph", source_url="https://example.invalid/photo")
    item["media"] = {"kind": "image", "duration_s": None, "width": 64, "height": 64, "fps": None}
    item["output"] = {"path": rel, "sha256": file_digest(path), "verified": True}
    item["asset_type"] = "image"
    _permit(item)
    approve(item, "Editor Name", channel="chat", statement="Use this saved photograph.")
    return item


def _image_item(root, rel, *, size="64x64", source_id="bg-photo"):
    path = root.joinpath(*rel.split("/"))
    path.parent.mkdir(parents=True, exist_ok=True)
    synth_image(path, color="red", size=size)
    return _photo_from_existing(rel, path, source_id=source_id), path


def _write_color_sequence(path, *, duration, rate, size="64x64", extra=None):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    command = [
        "ffmpeg",
        "-v",
        "error",
        "-y",
        "-f",
        "lavfi",
        "-i",
        f"testsrc2=s={size}:d={duration}:r={rate}",
    ]
    if extra:
        command.extend(extra)
    command.append(str(path))
    done = subprocess.run(command, capture_output=True, text=True, encoding="utf-8", check=False)
    return done.returncode == 0 and path.is_file() and path.stat().st_size > 0


def _payload(item, rel, digest_value, **overrides):
    body = {
        "candidate_id": item["id"],
        "ref": rel,
        "fit": "contain",
        "suitability": _suitability(),
        "material_use": _material(rel, digest_value),
    }
    body.update(overrides)
    return body


def _dir_link(link, target):
    link = Path(link)
    target = Path(target)
    link.parent.mkdir(parents=True, exist_ok=True)
    try:
        link.symlink_to(target, target_is_directory=True)
        return link.exists() or link.is_symlink()
    except OSError:
        done = subprocess.run(
            ["cmd", "/c", "mklink", "/J", str(link), str(target)],
            capture_output=True,
            text=True,
            encoding="utf-8",
            check=False,
        )
        return done.returncode == 0 and (link.exists() or link.is_symlink() or _is_reparse_path(link))


def _is_reparse_path(path):
    path = Path(path)
    try:
        if path.is_symlink():
            return True
    except OSError:
        return True
    try:
        info = path.lstat()
    except FileNotFoundError:
        return False
    except OSError:
        return True
    attributes = getattr(info, "st_file_attributes", 0)
    reparse = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
    return bool(attributes & reparse)


def _remove_owned_link(link):
    link = Path(link)
    if not (link.exists() or link.is_symlink() or _is_reparse_path(link)):
        return
    if link.is_symlink():
        link.unlink()
        return
    try:
        link.rmdir()
    except OSError:
        link.unlink()


def _file_state(root):
    state = {}
    for path in sorted(root.rglob("*")):
        if path.is_file() and not path.is_symlink():
            state[path.relative_to(root).as_posix()] = path.read_bytes()
    return state


def _normalized(root, payload, items):
    record = normalize_background(root, payload, PROFILE, _estimated(), items=items)
    if not isinstance(record, dict):
        raise AssertionError("expected a normalized background record")
    return record


def _riff_chunk(fourcc, payload):
    size = len(payload)
    pad = b"\x00" if size % 2 else b""
    return fourcc + size.to_bytes(4, "little") + payload + pad


def _write_riff_webp(path, chunks):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    body = b"".join(chunks)
    path.write_bytes(b"RIFF" + (len(body) + 4).to_bytes(4, "little") + b"WEBP" + body)
    return path


def _assert_schema_compatible(testcase, record):
    if not isinstance(record, dict):
        raise AssertionError("expected a background record")
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    testcase.assertEqual(set(schema["required"]), set(record))
    testcase.assertEqual(schema["properties"]["schema_version"]["const"], record["schema_version"])
    testcase.assertEqual(1, record["schema_version"])
    testcase.assertIn(record["kind"], schema["properties"]["kind"]["enum"])
    testcase.assertIn(record["fit"], schema["properties"]["fit"]["enum"])
    testcase.assertIn(record["clock_state"], schema["properties"]["clock_state"]["enum"])
    testcase.assertRegex(record["sha256"], re.compile(schema["$defs"]["sha256"]["pattern"]))
    testcase.assertRegex(record["ref"], re.compile(schema["$defs"]["mediaRef"]["pattern"]))
    testcase.assertEqual(set(schema["$defs"]["representation"]["required"]), set(record["representation"]))


class ClassifyRepresentationTests(unittest.TestCase):
    def test_one_frame_mp4_is_video_not_image(self):
        kind = _classify_background_kind("mov,mp4,m4a,3gp,3g2,mj2", "h264", 1.0, 1, "clips/one.mp4")
        self.assertEqual("video", kind)
        kind_short = _classify_background_kind("mov,mp4,m4a,3gp,3g2,mj2", "h264", 0.04, 1, "clips/frame.mp4")
        self.assertEqual("video", kind_short)

    def test_missing_duration_video_is_not_a_photograph(self):
        with self.assertRaises(ValueError) as ctx:
            _classify_background_kind("mov,mp4,m4a,3gp,3g2,mj2", "h264", None, None, "clips/bad.mp4")
        self.assertIn("duration", str(ctx.exception).lower())

    def test_zero_duration_video_is_not_a_photograph(self):
        with self.assertRaises(ValueError) as ctx:
            _classify_background_kind("matroska,webm", "vp9", 0.0, 1, "clips/empty.webm")
        self.assertIn("duration", str(ctx.exception).lower())

    def test_png_and_jpeg_stills_remain_images(self):
        self.assertEqual(
            "image",
            _classify_background_kind("png_pipe", "png", 0.04, 1, "previews/still.png"),
        )
        self.assertEqual(
            "image",
            _classify_background_kind("png_pipe", "png", 0.04, None, "previews/still.png"),
        )
        self.assertEqual(
            "image",
            _classify_background_kind("image2", "mjpeg", None, 1, "previews/still.jpg"),
        )
        self.assertEqual(
            "image",
            _classify_background_kind("jpeg_pipe", "mjpeg", 0.04, 1, "clips/photo.jpeg"),
        )

    def test_animated_gif_is_refused(self):
        with self.assertRaises(ValueError) as ctx:
            _classify_background_kind("gif", "gif", 1.0, 10, "previews/loop.gif")
        message = str(ctx.exception).lower()
        self.assertIn("animated", message)
        self.assertEqual("image", _classify_background_kind("gif", "gif", None, 1, "previews/still.gif"))

    def test_short_or_unknown_animation_is_not_a_photograph(self):
        cases = (
            ("apng", "apng", 0.08, None, "previews/short.png"),
            ("gif", "gif", 0.08, None, "previews/short.gif"),
            ("gif", "gif", None, None, "previews/unknown.gif"),
            ("webp", "webp", 0.08, None, "previews/short.webp"),
            ("webp_pipe", "webp", None, None, "previews/unknown.webp"),
            ("gif", "gif", 0.08, 0, "previews/empty.gif"),
        )
        for format_name, codec_name, duration, frame_count, path in cases:
            with self.subTest(path=path, duration=duration, frame_count=frame_count):
                with self.assertRaises(ValueError) as ctx:
                    _classify_background_kind(format_name, codec_name, duration, frame_count, path)
                message = str(ctx.exception).lower()
                self.assertIn("animated", message)
                self.assertTrue("uncertain" in message or "unsupported" in message)
                self.assertIn("photograph", message)

    def test_known_multiframe_apng_is_refused(self):
        with self.assertRaises(ValueError) as ctx:
            _classify_background_kind("apng", "apng", 1.0, 10, "previews/loop.png")
        message = str(ctx.exception).lower()
        self.assertIn("animated", message)
        self.assertIn("unsupported", message)

    def test_verified_single_frame_gif_webp_apng_remain_images(self):
        self.assertEqual("image", _classify_background_kind("gif", "gif", 0.2, 1, "previews/still.gif"))
        self.assertEqual("image", _classify_background_kind("webp", "webp", 0.04, 1, "previews/still.webp"))
        self.assertEqual("image", _classify_background_kind("apng", "apng", 0.04, 1, "previews/still.png"))


class WebpRiffContainerTests(unittest.TestCase):
    def test_claimed_riff_size_cannot_hide_truncated_or_trailing_data(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = _write_riff_webp(Path(tmp) / "still.webp", [_riff_chunk(b"VP8 ", b"\x00" * 10)])
            original = path.read_bytes()
            path.write_bytes(original[:-1])
            self.assertIsNone(_webp_riff_frame_count(path))
            path.write_bytes(original + _riff_chunk(b"ANMF", b"\x00" * 16))
            self.assertIsNone(_webp_riff_frame_count(path))

    def test_incomplete_final_chunk_is_not_complete_container_proof(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = _write_riff_webp(Path(tmp) / "still.webp", [_riff_chunk(b"VP8 ", b"\x00" * 10)])
            data = bytearray(path.read_bytes() + b"A")
            data[4:8] = (len(data) - 8).to_bytes(4, "little")
            path.write_bytes(data)
            self.assertIsNone(_webp_riff_frame_count(path))

    def test_container_metadata_does_not_replace_successful_frame_decoding(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = _write_riff_webp(Path(tmp) / "still.webp", [_riff_chunk(b"VP8 ", b"\x00" * 10)])
            with mock.patch("getbrolls.graphics_media._count_decoded_frames", return_value=None):
                self.assertIsNone(_resolve_webp_frame_count(path, 1))

    def test_anmf_frames_are_counted_without_decoder(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = _write_riff_webp(
                Path(tmp) / "anim.webp",
                [
                    _riff_chunk(b"VP8X", bytes([WEBP_ANIMATION_FLAG]) + b"\x00" * 9),
                    _riff_chunk(b"ANIM", b"\x00" * 6),
                    _riff_chunk(b"ANMF", b"\x00" * 16),
                    _riff_chunk(b"ANMF", b"\x00" * 16),
                ],
            )
            self.assertEqual(2, _webp_riff_frame_count(path))

    def test_vp8x_animation_without_anmf_is_incomplete(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = _write_riff_webp(
                Path(tmp) / "incomplete.webp",
                [
                    _riff_chunk(b"VP8X", bytes([WEBP_ANIMATION_FLAG]) + b"\x00" * 9),
                    _riff_chunk(b"ANIM", b"\x00" * 6),
                ],
            )
            self.assertIsNone(_webp_riff_frame_count(path))

    def test_simple_vp8_still_is_one_frame(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = _write_riff_webp(Path(tmp) / "still.webp", [_riff_chunk(b"VP8 ", b"\x00" * 10)])
            self.assertEqual(1, _webp_riff_frame_count(path))


class SecondsToFrameTests(unittest.TestCase):
    def test_nonnegative_half_up_matches_graphics_convention(self):
        self.assertEqual(1, seconds_to_frame(0.5, 1))
        self.assertEqual(3, seconds_to_frame(2.5, 1))
        self.assertEqual(2, seconds_to_frame(0.05, 30))
        self.assertEqual(90, seconds_to_frame(3, 30))


class ValidateBackgroundTests(unittest.TestCase):
    def test_none_is_legacy_absent_background(self):
        self.assertIsNone(validate_background(None))
        ready = background_readiness(Path("unused"), None, PROFILE, _estimated(), items=[])
        self.assertTrue(ready["ready"])
        self.assertEqual([], ready["reasons"])

    def test_none_payload_normalizes_without_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = _brolls(tmp)
            self.assertIsNone(normalize_background(root, None, PROFILE, _estimated(), items=[]))
            missing = root / "graphics" / "numeric-stat" / "v1"
            frozen = freeze_background(root, missing, None)
            self.assertIsNone(frozen["background"])
            self.assertEqual([], frozen["assets"])
            self.assertFalse(missing.exists())


class NormalizeVideoTests(unittest.TestCase):
    @skip_unless_ffmpeg
    def test_output_cut_maps_original_interval_to_local_clock(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = _brolls(tmp)
            rel = "clips/field.mp4"
            item, path = _video_item(root, rel, start_s=2.0, end_s=8.0, duration_s=6)
            digest_value = file_digest(path)
            payload = _payload(item, rel, digest_value, source_start_s=3.0, source_end_s=6.0)
            snapshot = copy.deepcopy(payload)
            items = [item]
            record = _normalized(root, payload, items)
            self.assertEqual(snapshot, payload)
            self.assertIsNone(validate_background(record))
            _assert_schema_compatible(self, record)
            self.assertEqual("video", record["kind"])
            self.assertEqual(digest_value, record["sha256"])
            self.assertEqual(path.stat().st_size, record["bytes"])
            self.assertEqual(160, record["width"])
            self.assertEqual(90, record["height"])
            self.assertEqual(160, record["representation"]["width"])
            self.assertNotEqual(1920, record["width"])
            self.assertEqual("resolved", record["clock_state"])
            self.assertEqual(2.0, record["representation_source_start_s"])
            self.assertAlmostEqual(1.0, record["local_start_s"])
            self.assertAlmostEqual(4.0, record["local_end_s"])
            self.assertEqual(3.0, record["source_start_s"])
            self.assertEqual(6.0, record["source_end_s"])
            self.assertEqual(candidate_signature(item), record["candidate_signature"])
            self.assertEqual("approved", record["candidate_approval"]["status"])
            self.assertEqual("permitted", record["candidate_rights"]["status"])
            self.assertIsNotNone(record["suitability"])
            self.assertEqual("restricted", record["material_use"]["raw_redistribution"])
            ready = background_readiness(root, record, PROFILE, _estimated(), items=items)
            self.assertTrue(ready["ready"])
            self.assertEqual([], ready["reasons"])
            version_dir = root / "graphics" / "numeric-stat" / "v1"
            version_dir.mkdir(parents=True)
            frozen = freeze_background(root, version_dir, record)
            self.assertEqual(seconds_to_frame(1.0, 30), frozen["background"]["trim_before"])
            self.assertNotEqual(seconds_to_frame(2.0, 30), frozen["background"]["trim_before"])

    @skip_unless_ffmpeg
    def test_mutated_clocks_and_use_hash_fail_without_rewriting(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = _brolls(tmp)
            rel = "clips/field.mp4"
            item, path = _video_item(root, rel, start_s=2.0, end_s=8.0, duration_s=6)
            record = _normalized(
                root,
                _payload(item, rel, file_digest(path), source_start_s=3.0, source_end_s=6.0),
                [item],
            )
            snapshot = copy.deepcopy(record)
            before = _file_state(root)
            shifted = copy.deepcopy(record)
            shifted["local_start_s"] = 2.0
            shifted["local_end_s"] = 5.0
            with self.assertRaises(ValueError) as clock_ctx:
                validate_background(shifted)
            self.assertIn("map", str(clock_ctx.exception).lower())
            ready_clocks = background_readiness(root, shifted, PROFILE, _estimated(), items=[item])
            self.assertFalse(ready_clocks["ready"])
            self.assertIn("invalid_background_record", ready_clocks["reasons"])
            duration = copy.deepcopy(record)
            duration["representation"] = dict(record["representation"])
            duration["representation"]["duration_s"] = 3.0
            with self.assertRaises(ValueError):
                validate_background(duration)
            ready_duration = background_readiness(root, duration, PROFILE, _estimated(), items=[item])
            self.assertFalse(ready_duration["ready"])
            self.assertIn("invalid_background_record", ready_duration["reasons"])
            hashed = copy.deepcopy(record)
            hashed["material_use"] = dict(record["material_use"])
            hashed["material_use"]["sha256"] = "ab" * 32
            self.assertNotEqual(hashed["material_use"]["sha256"], hashed["sha256"])
            with self.assertRaises(ValueError) as hash_ctx:
                validate_background(hashed)
            self.assertIn("identity", str(hash_ctx.exception).lower())
            ready_hash = background_readiness(root, hashed, PROFILE, _estimated(), items=[item])
            self.assertFalse(ready_hash["ready"])
            self.assertIn("invalid_background_record", ready_hash["reasons"])
            remapped = copy.deepcopy(record)
            remapped["representation_source_start_s"] = 1.0
            remapped["local_start_s"] = 2.0
            remapped["local_end_s"] = 5.0
            self.assertIsNone(validate_background(remapped))
            ready_live = background_readiness(root, remapped, PROFILE, _estimated(), items=[item])
            self.assertFalse(ready_live["ready"])
            self.assertIn("unresolved_clock_mapping", ready_live["reasons"])
            self.assertEqual(snapshot, record)
            self.assertEqual(before, _file_state(root))
            still_ready = background_readiness(root, record, PROFILE, _estimated(), items=[item])
            self.assertTrue(still_ready["ready"])
            self.assertEqual([], still_ready["reasons"])

    @skip_unless_ffmpeg
    def test_actual_low_resolution_is_not_native_1080p(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = _brolls(tmp)
            rel = "clips/small.mp4"
            item, path = _video_item(root, rel, size="160x90")
            payload = _payload(item, rel, file_digest(path), width=1920, height=1080)
            with self.assertRaises(ValueError) as ctx:
                normalize_background(root, payload, PROFILE, _estimated(), items=[item])
            self.assertIn("actual representation", str(ctx.exception))

    @skip_unless_ffmpeg
    def test_short_video_is_rejected_without_looping(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = _brolls(tmp)
            rel = "clips/short.mp4"
            item, path = _video_item(root, rel, start_s=0.0, end_s=1.0, duration_s=1, rate=10)
            payload = _payload(item, rel, file_digest(path), source_start_s=0.0, source_end_s=1.0)
            with self.assertRaises(ValueError) as ctx:
                normalize_background(root, payload, PROFILE, _estimated(), items=[item])
            self.assertIn("shorter than the scene", str(ctx.exception))
            self.assertIn("loop", str(ctx.exception))

    @skip_unless_ffmpeg
    def test_one_frame_mp4_is_not_a_photograph_or_frozen_substitute(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = _brolls(tmp)
            rel = "clips/one-frame.mp4"
            item, path = _video_item(root, rel, start_s=0.0, end_s=1.0, duration_s=1, rate=1)
            payload = _payload(item, rel, file_digest(path), source_start_s=0.0, source_end_s=1.0)
            with self.assertRaises(ValueError) as ctx:
                normalize_background(root, payload, PROFILE, _estimated(), items=[item])
            message = str(ctx.exception).lower()
            self.assertTrue("shorter than the scene" in message or "duration is missing" in message)
            self.assertNotIn("photograph", message)
            if "shorter than the scene" in message:
                self.assertIn("loop", message)

    @skip_unless_ffmpeg
    def test_wrong_hash_is_rejected_and_bytes_are_not_adopted(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = _brolls(tmp)
            rel = "clips/field.mp4"
            item, path = _video_item(root, rel)
            actual = file_digest(path)
            payload = _payload(item, rel, "0" * 64, sha256="0" * 64)
            snapshot = path.read_bytes()
            with self.assertRaises(ValueError) as ctx:
                normalize_background(root, payload, PROFILE, _estimated(), items=[item])
            self.assertIn("does not match", str(ctx.exception))
            self.assertEqual(snapshot, path.read_bytes())
            self.assertEqual(actual, file_digest(path))


class NormalizeImageTests(unittest.TestCase):
    @skip_unless_ffmpeg
    def test_photograph_has_no_fabricated_interval(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = _brolls(tmp)
            rel = "previews/field-poster.jpg"
            item, path = _image_item(root, rel, size="64x64")
            payload = _payload(item, rel, file_digest(path), fit="cover")
            record = _normalized(root, payload, [item])
            self.assertIsNone(validate_background(record))
            _assert_schema_compatible(self, record)
            self.assertEqual("image", record["kind"])
            self.assertEqual("not_applicable", record["clock_state"])
            self.assertIsNone(record["source_start_s"])
            self.assertIsNone(record["source_end_s"])
            self.assertIsNone(record["representation_source_start_s"])
            self.assertIsNone(record["local_start_s"])
            self.assertIsNone(record["local_end_s"])
            self.assertEqual(64, record["width"])
            self.assertEqual(64, record["height"])
            self.assertEqual("cover", record["fit"])
            ready = background_readiness(root, record, PROFILE, _estimated(), items=[item])
            self.assertTrue(ready["ready"])

    @skip_unless_ffmpeg
    def test_image_rejects_fabricated_source_times(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = _brolls(tmp)
            rel = "clips/still.png"
            item, path = _image_item(root, rel)
            payload = _payload(item, rel, file_digest(path), source_start_s=0, source_end_s=3)
            with self.assertRaises(ValueError) as ctx:
                normalize_background(root, payload, PROFILE, _estimated(), items=[item])
            self.assertIn("no fabricated time interval", str(ctx.exception))

    @skip_unless_ffmpeg
    def test_verified_still_gif_is_an_image(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = _brolls(tmp)
            rel = "previews/still.gif"
            item, path = _image_item(root, rel)
            digest_value = file_digest(path)
            record = _normalized(root, _payload(item, rel, digest_value), [item])
            self.assertIsNone(validate_background(record))
            self.assertEqual("image", record["kind"])
            self.assertEqual("not_applicable", record["clock_state"])
            self.assertIsNone(record["source_start_s"])
            self.assertIsNone(record["local_duration_s"])
            self.assertEqual(digest_value, record["sha256"])

    @skip_unless_ffmpeg
    def test_verified_still_webp_is_an_image(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = _brolls(tmp)
            rel = "previews/still.webp"
            try:
                item, path = _image_item(root, rel)
            except subprocess.CalledProcessError:
                self.skipTest("could not encode a single-frame still WebP")
            digest_value = file_digest(path)
            record = _normalized(root, _payload(item, rel, digest_value), [item])
            self.assertEqual("image", record["kind"])
            self.assertEqual("not_applicable", record["clock_state"])

    @skip_unless_ffmpeg
    def test_short_multiframe_gif_is_not_a_photograph(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = _brolls(tmp)
            rel = "previews/short.gif"
            path = root.joinpath(*rel.split("/"))
            if not _write_color_sequence(path, duration=0.08, rate=25):
                self.skipTest("could not encode a short multi-frame GIF")
            item = _photo_from_existing(rel, path)
            digest_value = file_digest(path)
            snapshot = path.read_bytes()
            with self.assertRaises(ValueError) as ctx:
                normalize_background(root, _payload(item, rel, digest_value), PROFILE, _estimated(), items=[item])
            message = str(ctx.exception).lower()
            self.assertIn("animated", message)
            self.assertTrue("unsupported" in message or "uncertain" in message)
            self.assertEqual(snapshot, path.read_bytes())

    @skip_unless_ffmpeg
    def test_multiframe_apng_is_not_a_photograph(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = _brolls(tmp)
            rel = "previews/short.png"
            path = root.joinpath(*rel.split("/"))
            if not _write_color_sequence(path, duration=1.0, rate=10, extra=["-plays", "0", "-f", "apng"]):
                self.skipTest("could not encode a multi-frame APNG")
            item = _photo_from_existing(rel, path)
            digest_value = file_digest(path)
            snapshot = path.read_bytes()
            with self.assertRaises(ValueError) as ctx:
                normalize_background(root, _payload(item, rel, digest_value), PROFILE, _estimated(), items=[item])
            message = str(ctx.exception).lower()
            self.assertIn("animated", message)
            self.assertTrue("unsupported" in message or "uncertain" in message)
            self.assertEqual(snapshot, path.read_bytes())

    @skip_unless_ffmpeg
    def test_short_or_unknown_webp_is_not_a_photograph(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = _brolls(tmp)
            rel = "previews/short.webp"
            path = root.joinpath(*rel.split("/"))
            if not _write_color_sequence(path, duration=0.08, rate=25, extra=["-loop", "0"]):
                self.skipTest("could not encode a short WebP sequence")
            self.assertEqual(2, _webp_riff_frame_count(path), "fixture must contain two changing frames")
            item = _photo_from_existing(rel, path)
            digest_value = file_digest(path)
            snapshot = path.read_bytes()
            with self.assertRaises(ValueError) as ctx:
                normalize_background(root, _payload(item, rel, digest_value), PROFILE, _estimated(), items=[item])
            message = str(ctx.exception).lower()
            self.assertIn("animated", message)
            self.assertTrue("unsupported" in message or "uncertain" in message)
            self.assertEqual(snapshot, path.read_bytes())


class DraftAndPermissionTests(unittest.TestCase):
    @skip_unless_ffmpeg
    def test_missing_suitability_is_draft_not_ready(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = _brolls(tmp)
            rel = "clips/field.mp4"
            item, path = _video_item(root, rel)
            payload = _payload(item, rel, file_digest(path))
            payload["suitability"] = None
            payload["material_use"] = None
            record = _normalized(root, payload, [item])
            self.assertIsNone(record["suitability"])
            self.assertIsNone(record["material_use"])
            self.assertEqual("approved", record["candidate_approval"]["status"])
            ready = background_readiness(root, record, PROFILE, _estimated(), items=[item])
            self.assertFalse(ready["ready"])
            self.assertIn("missing_suitability", ready["reasons"])
            self.assertIn("unresolved_background_permission", ready["reasons"])
            version_dir = root / "graphics" / "numeric-stat" / "v1"
            version_dir.mkdir(parents=True)
            frozen = freeze_background(root, version_dir, record)
            self.assertTrue(frozen["background"]["muted"])
            self.assertEqual("media/background.mp4", frozen["background"]["src"])

    @skip_unless_ffmpeg
    def test_signature_and_rights_staleness_block_readiness_without_writes(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = _brolls(tmp)
            rel = "clips/field.mp4"
            item, path = _video_item(root, rel)
            record = _normalized(root, _payload(item, rel, file_digest(path)), [item])
            snapshot = copy.deepcopy(record)
            before = _file_state(root)
            self.assertTrue(background_readiness(root, record, PROFILE, _estimated(), items=[item])["ready"])
            stale = copy.deepcopy(item)
            stale["title"] = "Changed title after selection"
            ready_sig = background_readiness(root, record, PROFILE, _estimated(), items=[stale])
            self.assertFalse(ready_sig["ready"])
            self.assertIn("stale_candidate_signature", ready_sig["reasons"])
            denied = copy.deepcopy(item)
            denied["rights"]["status"] = "restricted"
            ready_rights = background_readiness(root, record, PROFILE, _estimated(), items=[denied])
            self.assertFalse(ready_rights["ready"])
            self.assertIn("unresolved_background_permission", ready_rights["reasons"])
            self.assertEqual(snapshot, record)
            self.assertEqual(before, _file_state(root))
            self.assertEqual("permitted", record["candidate_rights"]["status"])
            self.assertIsNotNone(record["suitability"])

    @skip_unless_ffmpeg
    def test_rights_evidence_and_license_identity_block_readiness(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = _brolls(tmp)
            rel = "clips/field.mp4"
            item, path = _video_item(root, rel)
            record = _normalized(root, _payload(item, rel, file_digest(path)), [item])
            snapshot = copy.deepcopy(record)
            before = _file_state(root)
            self.assertEqual(candidate_signature(item), item["approval"]["signature"])
            evidence = copy.deepcopy(item)
            evidence["rights"]["evidence"] = ["Different recorded use terms."]
            self.assertEqual(candidate_signature(item), candidate_signature(evidence))
            self.assertEqual(item["approval"]["signature"], evidence["approval"]["signature"])
            self.assertEqual("permitted", evidence["rights"]["status"])
            ready_evidence = background_readiness(root, record, PROFILE, _estimated(), items=[evidence])
            self.assertFalse(ready_evidence["ready"])
            self.assertIn("unresolved_background_permission", ready_evidence["reasons"])
            self.assertNotIn("stale_candidate_signature", ready_evidence["reasons"])
            named = copy.deepcopy(item)
            named["rights"]["license_name"] = "CC-BY-4.0"
            self.assertEqual(candidate_signature(item), candidate_signature(named))
            ready_name = background_readiness(root, record, PROFILE, _estimated(), items=[named])
            self.assertFalse(ready_name["ready"])
            self.assertIn("unresolved_background_permission", ready_name["reasons"])
            self.assertNotIn("stale_candidate_signature", ready_name["reasons"])
            linked = copy.deepcopy(item)
            linked["rights"]["license_url"] = "https://example.invalid/license"
            self.assertEqual(candidate_signature(item), candidate_signature(linked))
            ready_url = background_readiness(root, record, PROFILE, _estimated(), items=[linked])
            self.assertFalse(ready_url["ready"])
            self.assertIn("unresolved_background_permission", ready_url["reasons"])
            self.assertNotIn("stale_candidate_signature", ready_url["reasons"])
            self.assertEqual(snapshot, record)
            self.assertEqual(before, _file_state(root))
            self.assertEqual("permitted", record["candidate_rights"]["status"])
            self.assertEqual(["Synthetic test permit."], record["candidate_rights"]["evidence"])
            self.assertEqual("CC0", record["candidate_rights"]["license_name"])
            self.assertIsNone(record["candidate_rights"]["license_url"])
            self.assertEqual("approved", record["candidate_approval"]["status"])
            self.assertIsNotNone(record["suitability"])
            self.assertEqual("available", record["candidate_acquisition"])

    @skip_unless_ffmpeg
    def test_missing_candidate_names_search_inspect_preview(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = _brolls(tmp)
            rel = "clips/field.mp4"
            item, path = _video_item(root, rel)
            payload = _payload(item, rel, file_digest(path), candidate_id="local:missing")
            with self.assertRaises(ValueError) as ctx:
                normalize_background(root, payload, PROFILE, _estimated(), items=[item])
            message = str(ctx.exception)
            self.assertIn("search", message)
            self.assertIn("inspect", message)
            self.assertIn("preview", message)
            self.assertIn("generic footage", message)

    @skip_unless_ffmpeg
    def test_validate_does_not_read_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = _brolls(tmp)
            rel = "clips/field.mp4"
            item, path = _video_item(root, rel)
            record = _normalized(root, _payload(item, rel, file_digest(path)), [item])
            path.unlink()
            self.assertIsNone(validate_background(record))
            ready = background_readiness(root, record, PROFILE, _estimated(), items=[item])
            self.assertFalse(ready["ready"])
            self.assertTrue(any("missing_background_file" in reason for reason in ready["reasons"]))


class UnsafeInputTests(unittest.TestCase):
    @skip_unless_ffmpeg
    def test_missing_file_is_actionable(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = _brolls(tmp)
            rel = "clips/field.mp4"
            item, path = _video_item(root, rel)
            payload = _payload(item, rel, file_digest(path))
            path.unlink()
            with self.assertRaises(ValueError) as ctx:
                normalize_background(root, payload, PROFILE, _estimated(), items=[item])
            message = str(ctx.exception)
            self.assertIn("missing", message.lower())
            self.assertTrue("inspect" in message or "preview" in message or "search" in message)

    def test_unsafe_refs_are_rejected_before_io(self):
        root = Path("unused")
        item = candidate("local", "x", "X")
        cases = (
            "C:/Windows/clips/a.mp4",
            "/etc/passwd",
            "//server/share/clips/a.mp4",
            "clips/foo:stream",
            "https://example.invalid/a.mp4",
            "clips/../secrets.mp4",
            "sounds/whip.wav",
            "narration/private/audio/take.wav",
            "clips/con.mp4",
        )
        for ref in cases:
            with self.subTest(ref=ref):
                with self.assertRaises(ValueError) as ctx:
                    normalize_background(
                        root,
                        {"candidate_id": "local:x", "ref": ref},
                        PROFILE,
                        _estimated(),
                        items=[item],
                    )
                message = str(ctx.exception).lower()
                self.assertTrue(
                    "posix" in message or "previews/" in message or "clips/" in message or "reserved" in message
                )

    @skip_unless_ffmpeg
    def test_changed_bytes_block_readiness_without_writes(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = _brolls(tmp)
            rel = "clips/field.mp4"
            item, path = _video_item(root, rel)
            record = _normalized(root, _payload(item, rel, file_digest(path)), [item])
            before = _file_state(root)
            path.write_bytes(path.read_bytes() + b"tamper")
            ready = background_readiness(root, record, PROFILE, _estimated(), items=[item])
            self.assertFalse(ready["ready"])
            self.assertIn("changed_background_hash", ready["reasons"])
            after = {key: value for key, value in _file_state(root).items() if key != rel}
            self.assertEqual({key: value for key, value in before.items() if key != rel}, after)

    @skip_unless_ffmpeg
    def test_lexical_root_junction_is_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            root = tmp_path / "brolls"
            root.mkdir()
            (root / "clips").mkdir()
            rel = "clips/field.mp4"
            item, path = _video_item(root, rel)
            payload = _payload(item, rel, file_digest(path))
            record = _normalized(root, payload, [item])
            sentinel = b"EXTERNAL-MEDIA-SENTINEL-DO-NOT-FOLLOW"
            external = tmp_path / "external-target"
            external.mkdir()
            (external / "clips").mkdir()
            (external / "clips" / "field.mp4").write_bytes(path.read_bytes())
            (external / "sentinel.bin").write_bytes(sentinel)
            linked_root = tmp_path / "linked-brolls"
            if not _dir_link(linked_root, external):
                self.skipTest("could not create a root junction or directory symlink")
            try:
                with self.assertRaises(ValueError) as ctx:
                    normalize_background(linked_root, copy.deepcopy(payload), PROFILE, _estimated(), items=[item])
                self.assertIn("symlink or junction", str(ctx.exception))
                ready = background_readiness(linked_root, record, PROFILE, _estimated(), items=[item])
                self.assertFalse(ready["ready"])
                self.assertTrue(any("symlink or junction" in reason.lower() for reason in ready["reasons"]))
                version_dir = linked_root / "graphics" / "numeric-stat" / "v1"
                version_dir.mkdir(parents=True)
                with self.assertRaises(ValueError) as freeze_ctx:
                    freeze_background(linked_root, version_dir, record)
                self.assertIn("symlink or junction", str(freeze_ctx.exception))
                self.assertEqual(sentinel, (external / "sentinel.bin").read_bytes())
            finally:
                _remove_owned_link(linked_root)
            self.assertEqual(sentinel, (external / "sentinel.bin").read_bytes())

    @skip_unless_ffmpeg
    def test_parent_ancestor_junction_is_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            external = tmp_path / "external-target"
            real_root = external / "brolls"
            real_root.mkdir(parents=True)
            (real_root / "clips").mkdir()
            rel = "clips/field.mp4"
            item, _path = _video_item(real_root, rel)
            payload = _payload(item, rel, file_digest(real_root / rel))
            (external / "sentinel.bin").write_bytes(b"PARENT-JUNCTION-SENTINEL")
            linked_parent = tmp_path / "linked-parent"
            if not _dir_link(linked_parent, external):
                self.skipTest("could not create a parent junction or directory symlink")
            lexical_root = linked_parent / "brolls"
            try:
                with self.assertRaises(ValueError) as ctx:
                    normalize_background(lexical_root, payload, PROFILE, _estimated(), items=[item])
                self.assertIn("symlink or junction", str(ctx.exception))
                self.assertEqual(b"PARENT-JUNCTION-SENTINEL", (external / "sentinel.bin").read_bytes())
            finally:
                _remove_owned_link(linked_parent)


class FreezeBackgroundTests(unittest.TestCase):
    def test_missing_version_dir_does_not_create_tree(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            version_dir = root / "graphics" / "numeric-stat" / "v1"
            with self.assertRaises(ValueError):
                freeze_background(
                    root,
                    version_dir,
                    {
                        "schema_version": 1,
                        "candidate_id": "local:x",
                        "ref": "clips/x.mp4",
                        "kind": "image",
                        "sha256": "0" * 64,
                        "bytes": 1,
                        "width": 64,
                        "height": 64,
                        "representation": {
                            "width": 64,
                            "height": 64,
                            "duration_s": None,
                            "fps": None,
                            "bytes": 1,
                        },
                        "provider": "local",
                        "source_id": "x",
                        "source_url": None,
                        "source_start_s": None,
                        "source_end_s": None,
                        "representation_source_start_s": None,
                        "local_start_s": None,
                        "local_end_s": None,
                        "local_duration_s": None,
                        "local_fps": None,
                        "fit": "contain",
                        "fps": 30,
                        "duration_in_frames": 90,
                        "frame_rounding": "half_up_nonnegative",
                        "clock_state": "not_applicable",
                        "candidate_signature": "a" * 64,
                        "candidate_rights": {
                            "status": "unknown",
                            "evidence": [],
                            "license_name": None,
                            "license_url": None,
                        },
                        "candidate_acquisition": "unavailable",
                        "candidate_approval": {"status": "pending"},
                        "suitability": None,
                        "material_use": None,
                    },
                )
            self.assertFalse(version_dir.exists())

    @skip_unless_ffmpeg
    def test_copies_unique_local_bytes_and_muted_props(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = _brolls(tmp)
            rel = "clips/field.mp4"
            item, path = _video_item(root, rel, start_s=2.0, end_s=8.0, duration_s=6)
            record = _normalized(
                root,
                _payload(item, rel, file_digest(path), source_start_s=3.0, source_end_s=6.0),
                [item],
            )
            version_dir = root / "graphics" / "numeric-stat" / "v1"
            version_dir.mkdir(parents=True)
            frozen = freeze_background(root, version_dir, record)
            background = frozen["background"]
            self.assertEqual("video", background["kind"])
            self.assertEqual("media/background.mp4", background["src"])
            self.assertEqual("contain", background["fit"])
            self.assertEqual(160, background["width"])
            self.assertEqual(90, background["height"])
            self.assertTrue(background["muted"])
            self.assertEqual(seconds_to_frame(1.0, 30), background["trim_before"])
            self.assertEqual(SCENE_FRAMES, background["duration_in_frames"])
            asset = frozen["assets"][0]
            self.assertEqual("background", asset["kind"])
            self.assertEqual(rel, asset["ref"])
            self.assertEqual("public/media/background.mp4", asset["frozen_ref"])
            self.assertEqual(item["id"], asset["candidate_id"])
            dest = version_dir / "public" / "media" / "background.mp4"
            self.assertTrue(dest.is_file())
            self.assertEqual(file_digest(dest), asset["sha256"])
            self.assertEqual(file_digest(path), asset["sha256"])
            dumped = json.dumps(frozen)
            self.assertNotIn("narration/private", dumped)
            self.assertNotIn(str(path.resolve().parent.parent), background["src"])

    @skip_unless_ffmpeg
    def test_image_freeze_keeps_zero_trim(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = _brolls(tmp)
            rel = "previews/field.jpg"
            item, path = _image_item(root, rel)
            record = _normalized(root, _payload(item, rel, file_digest(path), fit="cover"), [item])
            version_dir = root / "graphics" / "numeric-stat" / "v1"
            version_dir.mkdir(parents=True)
            frozen = freeze_background(root, version_dir, record)
            self.assertEqual("image", frozen["background"]["kind"])
            self.assertEqual("media/background.jpg", frozen["background"]["src"])
            self.assertEqual(0, frozen["background"]["trim_before"])
            self.assertTrue(frozen["background"]["muted"])
            self.assertEqual("cover", frozen["background"]["fit"])

    @skip_unless_ffmpeg
    def test_occupied_destination_is_preserved(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = _brolls(tmp)
            rel = "clips/field.mp4"
            item, path = _video_item(root, rel)
            record = _normalized(root, _payload(item, rel, file_digest(path)), [item])
            version_dir = root / "graphics" / "numeric-stat" / "v1"
            dest = version_dir / "public" / "media" / "background.mp4"
            dest.parent.mkdir(parents=True)
            dest.write_bytes(b"FOREIGN-BACKGROUND")
            before = dest.read_bytes()
            with self.assertRaises(ValueError) as ctx:
                freeze_background(root, version_dir, record)
            self.assertIn("already exists", str(ctx.exception))
            self.assertEqual(before, dest.read_bytes())

    @skip_unless_ffmpeg
    def test_hash_change_preflight_does_not_create_dest(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = _brolls(tmp)
            rel = "clips/field.mp4"
            item, path = _video_item(root, rel)
            record = _normalized(root, _payload(item, rel, file_digest(path)), [item])
            version_dir = root / "graphics" / "numeric-stat" / "v1"
            version_dir.mkdir(parents=True)
            dest = version_dir / "public" / "media" / "background.mp4"
            path.write_bytes(path.read_bytes() + b"tamper")
            with self.assertRaises(ValueError):
                freeze_background(root, version_dir, record)
            self.assertFalse(dest.exists())
            self.assertFalse((version_dir / "public" / "media").exists())


class RendererSourceTests(unittest.TestCase):
    def test_graphics_background_uses_installed_offthread_video_and_img(self):
        source = (ROOT / "scripts" / "graphics" / "src" / "GraphicsBackground.jsx").read_text(encoding="utf-8")
        self.assertIn('from "remotion"', source)
        self.assertIn("OffthreadVideo", source)
        self.assertIn("Img", source)
        self.assertIn("staticFile", source)
        self.assertIn("trimBefore", source)
        self.assertIn("durationInFrames", source)
        self.assertIn("muted", source)
        self.assertIn("contain", source)
        self.assertIn("cover", source)
        self.assertNotIn("@remotion/media", source)
        self.assertNotIn("loop={", source)
        self.assertNotIn("loop=", source)

    def test_numeric_stat_keeps_absent_look_audio_and_readable_overlay(self):
        source = (ROOT / "scripts" / "graphics" / "src" / "NumericStat.jsx").read_text(encoding="utf-8")
        self.assertIn("GraphicsBackground", source)
        self.assertIn("GraphicsAudio", source)
        self.assertIn("sound_cues", source)
        self.assertIn("background", source)
        self.assertIn("transparent", source)
        self.assertIn(" : ink", source)
        self.assertIn("Synthetic draft value", source)
        self.assertIn("Estimated draft timing", source)
        self.assertIn("rgba(", source)

    def test_worker_refuses_unsafe_background_props(self):
        source = (ROOT / "scripts" / "graphics" / "render.mjs").read_text(encoding="utf-8")
        self.assertIn("assertSafeBackground", source)
        self.assertIn("media/", source)
        self.assertIn("muted", source)
        self.assertIn("trim_before", source)
        self.assertIn("duration_in_frames", source)
        self.assertIn("remote", source.lower())
        self.assertIn("voice-over", source)
        self.assertIn('mode !== "effects"', source)


if __name__ == "__main__":
    unittest.main()
