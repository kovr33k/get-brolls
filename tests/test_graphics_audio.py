"""#57: graphics audio domain, bounded VO excerpt, pinned CC0 import and renderer cues."""

from __future__ import annotations

import copy
import json
import shutil
import stat
import subprocess
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

import _isolation  # noqa: F401
from _cli import run_cli
from _media import skip_unless_ffmpeg
from _paths import ROOT

from getbrolls.graphics_audio import (
    SFX_ROUTES,
    audio_readiness,
    freeze_audio,
    import_sfx_command,
    normalize_audio,
    seconds_to_frame,
    validate_audio,
)
from getbrolls.ledger import Ledger
from getbrolls.ledger import digest as file_digest
from getbrolls.models import candidate

PROFILE = {
    "width": 1920,
    "height": 1080,
    "fps": 30,
    "fps_source": "default",
    "frame_rounding": "half_up_nonnegative",
}
SCENE_S = 3.0
SCENE_FRAMES = 90
TONE_A = 440
TONE_B = 880
TONE_C = 220


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


def _explicit(start_s=1.0, end_s=4.0):
    return {
        "basis": "explicit",
        "duration_in_frames": max(1, seconds_to_frame(end_s, 30) - seconds_to_frame(start_s, 30)),
        "duration_s": end_s - start_s,
        "start_s": start_s,
        "end_s": end_s,
        "start_frame": seconds_to_frame(start_s, 30),
        "end_frame": seconds_to_frame(end_s, 30),
    }


def _wav(path, frequency, duration):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        [
            "ffmpeg",
            "-v",
            "error",
            "-y",
            "-f",
            "lavfi",
            "-i",
            f"sine=frequency={frequency}:duration={duration}",
            "-c:a",
            "pcm_s16le",
            str(path),
        ],
        check=True,
    )
    return path


def _effect(effect_id, ref, **overrides):
    item = {
        "id": effect_id,
        "ref": ref,
        "source_url": SFX_ROUTES["whip"]["url"],
        "terms_url": SFX_ROUTES["whip"]["terms_url"],
        "license": "CC0",
        "conditions": SFX_ROUTES["whip"]["conditions"],
        "rendered_use": "permitted",
        "raw_redistribution": "permitted",
        "start_frame": 0,
        "source_start_s": 0,
        "duration_s": 0.5,
        "gain": 1,
    }
    item.update(overrides)
    return item


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
    """Remove only the owned link node; never walk or rmtree through a junction."""
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


def _assign_graphics(tmp):
    run_cli("init-rules", project=tmp)
    run_cli(
        "graphics-assign",
        "--scene",
        "numeric-stat",
        "--occurrence",
        "stat-01",
        "--chapter",
        "ch-1",
        "--chapter-context",
        "Surrounding chapter text from the scenario.",
        "--purpose",
        "Show the synthetic count",
        "--narration",
        "The count stands at twelve units.",
        "--timing",
        "estimated",
        "--duration",
        "3",
        project=tmp,
    )


class FrameRoundingTests(unittest.TestCase):
    def test_nonnegative_half_up_matches_graphics_convention(self):
        self.assertEqual(1, seconds_to_frame(0.5, 1))
        self.assertEqual(3, seconds_to_frame(2.5, 1))
        self.assertEqual(2, seconds_to_frame(0.05, 30))
        self.assertEqual(90, seconds_to_frame(3, 30))


class ValidateAudioTests(unittest.TestCase):
    def test_none_is_legacy_silence(self):
        self.assertIsNone(validate_audio(None))
        ready = audio_readiness(Path(), None)
        self.assertTrue(ready["ready"])
        self.assertEqual([], ready["reasons"])

    def test_empty_payload_normalizes_without_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            record = normalize_audio(root, {}, PROFILE, _estimated())
            self.assertEqual(1, record["schema_version"])
            self.assertEqual(30, record["fps"])
            self.assertEqual(SCENE_FRAMES, record["duration_in_frames"])
            self.assertEqual([], record["effects"])
            self.assertIsNone(record["vo"])
            version_dir = root / "graphics" / "numeric-stat" / "v1"
            version_dir.mkdir(parents=True)
            frozen = freeze_audio(root, version_dir, record)
            self.assertEqual([], frozen["sound_cues"])
            self.assertIsNone(frozen["vo_preview"])
            self.assertEqual([], frozen["assets"])
            self.assertFalse((version_dir / "public" / "audio").exists())


class NormalizeAudioTests(unittest.TestCase):
    @skip_unless_ffmpeg
    def test_hashes_probe_and_distinct_tones(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            whip = _wav(root / "sounds" / "whip.wav", TONE_A, 1)
            whoosh = _wav(root / "sounds" / "whoosh.wav", TONE_B, 1)
            self.assertNotEqual(file_digest(whip), file_digest(whoosh))
            record = normalize_audio(
                root,
                {
                    "effects": [
                        _effect("hit", "sounds/whip.wav", duration_s=0.4),
                        _effect(
                            "pass",
                            "sounds/whoosh.wav",
                            source_url=SFX_ROUTES["whoosh"]["url"],
                            terms_url=SFX_ROUTES["whoosh"]["terms_url"],
                            conditions=SFX_ROUTES["whoosh"]["conditions"],
                            start_frame=12,
                            duration_s=0.4,
                        ),
                    ]
                },
                PROFILE,
                _estimated(),
            )
            self.assertEqual(file_digest(whip), record["effects"][0]["sha256"])
            self.assertEqual(file_digest(whoosh), record["effects"][1]["sha256"])
            self.assertEqual(12, record["effects"][1]["start_frame"])
            self.assertTrue(audio_readiness(root, record)["ready"])

    @skip_unless_ffmpeg
    def test_rejects_hash_change_and_path_escape(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            whip = _wav(root / "sounds" / "whip.wav", TONE_A, 1)
            digest_value = file_digest(whip)
            with self.assertRaises(ValueError):
                normalize_audio(
                    root,
                    {"effects": [_effect("hit", "sounds/whip.wav", sha256="0" * 64)]},
                    PROFILE,
                    _estimated(),
                )
            with self.assertRaises(ValueError):
                normalize_audio(
                    root,
                    {"effects": [_effect("hit", "sounds/../whip.wav", sha256=digest_value)]},
                    PROFILE,
                    _estimated(),
                )
            with self.assertRaises(ValueError):
                normalize_audio(
                    root,
                    {"effects": [_effect("hit", "sounds/whip.wav:zone.identifier", sha256=digest_value)]},
                    PROFILE,
                    _estimated(),
                )
            with self.assertRaises(ValueError):
                normalize_audio(
                    root,
                    {"effects": [_effect("hit", "sounds/whip.wav", duration_s=0.4, gain=float("inf"))]},
                    PROFILE,
                    _estimated(),
                )
            (root / "sounds" / "truncated.wav").write_bytes(b"RIFF    WAVEfmt ")
            with self.assertRaises(ValueError):
                normalize_audio(
                    root,
                    {
                        "effects": [
                            _effect("bad", "sounds/truncated.wav", duration_s=0.4, source_url=None, terms_url=None)
                        ]
                    },
                    PROFILE,
                    _estimated(),
                )

    @skip_unless_ffmpeg
    def test_full_recording_clocks_match_explicit_narration(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            vo = _wav(root / "narration" / "private" / "audio" / "take.wav", TONE_C, 5)
            timing = _explicit(1.0, 4.0)
            record = normalize_audio(
                root,
                {
                    "vo": {
                        "ref": "narration/private/audio/take.wav",
                        "kind": "full_recording",
                        "source_start_s": 1.0,
                        "source_end_s": 4.0,
                        "gain": 1,
                    }
                },
                PROFILE,
                timing,
            )
            self.assertEqual("full_recording", record["vo"]["kind"])
            self.assertEqual(file_digest(vo), record["vo"]["sha256"])
            with self.assertRaises(ValueError):
                normalize_audio(
                    root,
                    {
                        "vo": {
                            "ref": "narration/private/audio/take.wav",
                            "kind": "full_recording",
                            "source_start_s": 0.0,
                            "source_end_s": 3.0,
                            "gain": 1,
                        }
                    },
                    PROFILE,
                    timing,
                )
            with self.assertRaises(ValueError):
                normalize_audio(
                    root,
                    {
                        "vo": {
                            "ref": "narration/private/audio/take.wav",
                            "kind": "full_recording",
                            "source_start_s": 1.0,
                            "source_end_s": 4.0,
                            "gain": 1,
                        }
                    },
                    PROFILE,
                    _estimated(),
                )

    @skip_unless_ffmpeg
    def test_fragment_clocks_are_local(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            fragment = _wav(root / "previews" / "vo-fragment.wav", TONE_C, 3)
            record = normalize_audio(
                root,
                {
                    "vo": {
                        "ref": "previews/vo-fragment.wav",
                        "kind": "fragment",
                        "source_start_s": 0.0,
                        "source_end_s": 3.0,
                        "gain": 0.8,
                    }
                },
                PROFILE,
                _estimated(),
            )
            self.assertEqual("fragment", record["vo"]["kind"])
            self.assertEqual(0.0, record["vo"]["source_start_s"])
            self.assertEqual(file_digest(fragment), record["vo"]["sha256"])

    @skip_unless_ffmpeg
    def test_restricted_candidate_is_not_upgraded_by_local_path(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            clip = _wav(root / "clips" / "user.wav", TONE_A, 1)
            item = candidate("local", "user-1", "User recording")
            item["output"]["path"] = "clips/user.wav"
            item["output"]["sha256"] = file_digest(clip)
            item["output"]["verified"] = True
            item["rights"]["status"] = "restricted"
            item["rights"]["evidence"] = ["Owner withheld raw use"]
            (root / "manifest.json").write_text(
                json.dumps({"schema_version": 1, "items": [item]}, ensure_ascii=False),
                encoding="utf-8",
            )
            with self.assertRaises(ValueError) as raised:
                normalize_audio(
                    root,
                    {
                        "effects": [
                            _effect(
                                "hit",
                                "clips/user.wav",
                                candidate_id=item["id"],
                                rendered_use="permitted",
                                raw_redistribution="permitted",
                                source_url=None,
                                terms_url=None,
                                license="unknown",
                                conditions="User media; permission is not implied by a local file.",
                            )
                        ]
                    },
                    PROFILE,
                    _estimated(),
                )
            self.assertIn("restricted", str(raised.exception).lower())

    @skip_unless_ffmpeg
    def test_corrupt_manifest_items_block_permission_binding(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _wav(root / "sounds" / "whip.wav", TONE_A, 1)
            record = normalize_audio(
                root,
                {"effects": [_effect("hit", "sounds/whip.wav", duration_s=0.4)]},
                PROFILE,
                _estimated(),
            )
            (root / "manifest.json").write_text(
                json.dumps({"schema_version": 1, "items": "nope"}, ensure_ascii=False),
                encoding="utf-8",
            )
            with self.assertRaises(ValueError):
                normalize_audio(
                    root,
                    {"effects": [_effect("hit", "sounds/whip.wav", duration_s=0.4)]},
                    PROFILE,
                    _estimated(),
                )
            ready = audio_readiness(root, record)
            self.assertFalse(ready["ready"])
            self.assertIn("unresolved_audio_permission", ready["reasons"])

    @skip_unless_ffmpeg
    def test_repeated_asset_at_distinct_cue_ids_is_accepted(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            whip = _wav(root / "sounds" / "whip.wav", TONE_A, 1)
            digest_value = file_digest(whip)
            record = normalize_audio(
                root,
                {
                    "effects": [
                        _effect("hit", "sounds/whip.wav", duration_s=0.4, start_frame=0),
                        _effect("hit-late", "sounds/whip.wav", duration_s=0.4, start_frame=30),
                    ]
                },
                PROFILE,
                _estimated(),
            )
            self.assertEqual(2, len(record["effects"]))
            self.assertEqual("hit", record["effects"][0]["id"])
            self.assertEqual("hit-late", record["effects"][1]["id"])
            self.assertEqual("sounds/whip.wav", record["effects"][0]["ref"])
            self.assertEqual("sounds/whip.wav", record["effects"][1]["ref"])
            self.assertEqual(digest_value, record["effects"][0]["sha256"])
            self.assertEqual(digest_value, record["effects"][1]["sha256"])
            self.assertEqual(0, record["effects"][0]["start_frame"])
            self.assertEqual(30, record["effects"][1]["start_frame"])
            self.assertEqual(record, validate_audio(record))
            self.assertTrue(audio_readiness(root, record)["ready"])

    @skip_unless_ffmpeg
    def test_duplicate_ids_and_case_alias_refs_are_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _wav(root / "sounds" / "whip.wav", TONE_A, 1)
            with self.assertRaises(ValueError) as duplicate_id:
                normalize_audio(
                    root,
                    {
                        "effects": [
                            _effect("hit", "sounds/whip.wav", duration_s=0.4, start_frame=0),
                            _effect("Hit", "sounds/whip.wav", duration_s=0.4, start_frame=30),
                        ]
                    },
                    PROFILE,
                    _estimated(),
                )
            self.assertIn("cannot repeat", str(duplicate_id.exception).lower())
            with self.assertRaises(ValueError) as alias:
                normalize_audio(
                    root,
                    {
                        "effects": [
                            _effect("hit", "sounds/whip.wav", duration_s=0.4, start_frame=0),
                            _effect("hit-late", "sounds/Whip.wav", duration_s=0.4, start_frame=30),
                        ]
                    },
                    PROFILE,
                    _estimated(),
                )
            message = str(alias.exception).lower()
            self.assertTrue("case-insensitively" in message or "missing" in message or "symlink" in message)
            saved = {
                "schema_version": 1,
                "fps": 30,
                "duration_in_frames": SCENE_FRAMES,
                "effects": [
                    _effect("hit", "sounds/whip.wav", sha256="a" * 64, duration_s=0.4, start_frame=0),
                    _effect("Hit", "sounds/whip.wav", sha256="a" * 64, duration_s=0.4, start_frame=30),
                ],
                "vo": None,
            }
            with self.assertRaises(ValueError) as saved_ids:
                validate_audio(saved)
            self.assertIn("cannot repeat", str(saved_ids.exception).lower())

    @skip_unless_ffmpeg
    def test_registered_cc0_does_not_upgrade_supplied_restrictions(self):
        with tempfile.TemporaryDirectory() as tmp:
            _assign_graphics(tmp)
            source = Path(tmp) / "fixture-whip.wav"
            _wav(source, TONE_A, 1)

            def downloader(url, target, max_bytes=None):
                shutil.copyfile(source, target)
                return target

            import_sfx_command(
                Ledger(tmp),
                SimpleNamespace(sfx="whip", asset="whip-1"),
                downloader=downloader,
            )
            root = Path(tmp) / "brolls"
            restricted = "Project permits rendered use; raw redistribution restricted."
            record = normalize_audio(
                root,
                {
                    "effects": [
                        _effect(
                            "hit",
                            "sounds/whip-1.wav",
                            duration_s=0.4,
                            rendered_use="restricted",
                            raw_redistribution="restricted",
                            conditions=restricted,
                        )
                    ]
                },
                PROFILE,
                _estimated(),
            )
            self.assertEqual("restricted", record["effects"][0]["rendered_use"])
            self.assertEqual("restricted", record["effects"][0]["raw_redistribution"])
            self.assertEqual(restricted, record["effects"][0]["conditions"])
            snapshot = copy.deepcopy(record)
            ready = audio_readiness(root, record)
            self.assertFalse(ready["ready"])
            self.assertIn("unresolved_audio_permission", ready["reasons"])
            self.assertEqual(snapshot, record)

    @skip_unless_ffmpeg
    def test_readiness_detects_changed_registry_terms_without_mutation(self):
        with tempfile.TemporaryDirectory() as tmp:
            _assign_graphics(tmp)
            source = Path(tmp) / "fixture-whip.wav"
            _wav(source, TONE_A, 1)

            def downloader(url, target, max_bytes=None):
                shutil.copyfile(source, target)
                return target

            import_sfx_command(
                Ledger(tmp),
                SimpleNamespace(sfx="whip", asset="whip-1"),
                downloader=downloader,
            )
            root = Path(tmp) / "brolls"
            record = normalize_audio(
                root,
                {"effects": [_effect("hit", "sounds/whip-1.wav", duration_s=0.4)]},
                PROFILE,
                _estimated(),
            )
            self.assertTrue(audio_readiness(root, record)["ready"])
            snapshot = copy.deepcopy(record)
            ledger = Ledger(tmp, recover=False)
            sound = ledger.data["graphics"]["sounds"]["whip-1"]
            sound["terms_url"] = SFX_ROUTES["whoosh"]["terms_url"]
            sound["conditions"] = "Changed registry terms after import."
            sound["rendered_use"] = "restricted"
            ledger.save("graphics-sound-import")
            ready = audio_readiness(root, record)
            self.assertFalse(ready["ready"])
            self.assertIn("unresolved_audio_permission", ready["reasons"])
            self.assertEqual(snapshot, record)
            self.assertEqual("permitted", record["effects"][0]["rendered_use"])
            self.assertEqual(SFX_ROUTES["whip"]["terms_url"], record["effects"][0]["terms_url"])

    @skip_unless_ffmpeg
    def test_stable_restricted_raw_allows_permitted_render(self):
        with tempfile.TemporaryDirectory() as tmp:
            _assign_graphics(tmp)
            source = Path(tmp) / "fixture-whip.wav"
            _wav(source, TONE_A, 1)

            def downloader(url, target, max_bytes=None):
                shutil.copyfile(source, target)
                return target

            import_sfx_command(
                Ledger(tmp),
                SimpleNamespace(sfx="whip", asset="whip-1"),
                downloader=downloader,
            )
            ledger = Ledger(tmp, recover=False)
            sound = ledger.data["graphics"]["sounds"]["whip-1"]
            sound["raw_redistribution"] = "restricted"
            ledger.save("graphics-sound-import")
            root = Path(tmp) / "brolls"
            record = normalize_audio(
                root,
                {
                    "effects": [
                        _effect(
                            "hit",
                            "sounds/whip-1.wav",
                            duration_s=0.4,
                            rendered_use="permitted",
                            raw_redistribution="restricted",
                        )
                    ]
                },
                PROFILE,
                _estimated(),
            )
            self.assertEqual("permitted", record["effects"][0]["rendered_use"])
            self.assertEqual("restricted", record["effects"][0]["raw_redistribution"])
            snapshot = copy.deepcopy(record)
            ready = audio_readiness(root, record)
            self.assertTrue(ready["ready"])
            self.assertEqual([], ready["reasons"])
            self.assertEqual(snapshot, record)

    @skip_unless_ffmpeg
    def test_stricter_caller_raw_does_not_block_permitted_render(self):
        with tempfile.TemporaryDirectory() as tmp:
            _assign_graphics(tmp)
            source = Path(tmp) / "fixture-whip.wav"
            _wav(source, TONE_A, 1)

            def downloader(url, target, max_bytes=None):
                shutil.copyfile(source, target)
                return target

            import_sfx_command(
                Ledger(tmp),
                SimpleNamespace(sfx="whip", asset="whip-1"),
                downloader=downloader,
            )
            root = Path(tmp) / "brolls"
            record = normalize_audio(
                root,
                {
                    "effects": [
                        _effect(
                            "hit",
                            "sounds/whip-1.wav",
                            duration_s=0.4,
                            rendered_use="permitted",
                            raw_redistribution="restricted",
                        )
                    ]
                },
                PROFILE,
                _estimated(),
            )
            self.assertEqual("permitted", record["effects"][0]["rendered_use"])
            self.assertEqual("restricted", record["effects"][0]["raw_redistribution"])
            snapshot = copy.deepcopy(record)
            ready = audio_readiness(root, record)
            self.assertTrue(ready["ready"])
            self.assertEqual([], ready["reasons"])
            self.assertEqual(snapshot, record)

    @skip_unless_ffmpeg
    def test_registry_rendered_denial_blocks_without_mutation(self):
        with tempfile.TemporaryDirectory() as tmp:
            _assign_graphics(tmp)
            source = Path(tmp) / "fixture-whip.wav"
            _wav(source, TONE_A, 1)

            def downloader(url, target, max_bytes=None):
                shutil.copyfile(source, target)
                return target

            import_sfx_command(
                Ledger(tmp),
                SimpleNamespace(sfx="whip", asset="whip-1"),
                downloader=downloader,
            )
            root = Path(tmp) / "brolls"
            record = normalize_audio(
                root,
                {"effects": [_effect("hit", "sounds/whip-1.wav", duration_s=0.4)]},
                PROFILE,
                _estimated(),
            )
            self.assertTrue(audio_readiness(root, record)["ready"])
            snapshot = copy.deepcopy(record)
            ledger = Ledger(tmp, recover=False)
            sound = ledger.data["graphics"]["sounds"]["whip-1"]
            sound["rendered_use"] = "restricted"
            ledger.save("graphics-sound-import")
            ready = audio_readiness(root, record)
            self.assertFalse(ready["ready"])
            self.assertIn("unresolved_audio_permission", ready["reasons"])
            self.assertEqual(snapshot, record)
            self.assertEqual("permitted", record["effects"][0]["rendered_use"])
            self.assertEqual("permitted", record["effects"][0]["raw_redistribution"])


class FreezeAudioTests(unittest.TestCase):
    def test_none_is_empty_freeze_without_creating_paths(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            missing = root / "graphics" / "numeric-stat" / "v1"
            frozen = freeze_audio(root, missing, None)
            self.assertEqual([], frozen["sound_cues"])
            self.assertIsNone(frozen["vo_preview"])
            self.assertEqual([], frozen["assets"])
            self.assertFalse(missing.exists())

    @skip_unless_ffmpeg
    def test_copies_effects_and_bounded_vo_excerpt(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _wav(root / "sounds" / "whip.wav", TONE_A, 1)
            vo_src = _wav(root / "narration" / "private" / "audio" / "take.wav", TONE_C, 5)
            record = normalize_audio(
                root,
                {
                    "effects": [_effect("hit", "sounds/whip.wav", duration_s=0.4)],
                    "vo": {
                        "ref": "narration/private/audio/take.wav",
                        "kind": "full_recording",
                        "source_start_s": 1.0,
                        "source_end_s": 4.0,
                        "gain": 1,
                    },
                },
                PROFILE,
                _explicit(1.0, 4.0),
            )
            version_dir = root / "graphics" / "numeric-stat" / "v1"
            version_dir.mkdir(parents=True)
            frozen = freeze_audio(root, version_dir, record)
            cue = frozen["sound_cues"][0]
            self.assertEqual("hit", cue["id"])
            self.assertEqual("audio/hit.wav", cue["src"])
            self.assertGreaterEqual(cue["duration_in_frames"], 1)
            self.assertEqual(0, cue["trim_before_frame"])
            asset = frozen["assets"][0]
            self.assertEqual("effect", asset["kind"])
            self.assertEqual("sounds/whip.wav", asset["ref"])
            self.assertEqual("public/audio/hit.wav", asset["frozen_ref"])
            frozen_file = version_dir / "public" / "audio" / "hit.wav"
            self.assertTrue(frozen_file.is_file())
            self.assertEqual(file_digest(frozen_file), asset["sha256"])
            preview = frozen["vo_preview"]
            self.assertEqual("full_recording", preview["kind"])
            self.assertEqual("narration/private/audio/take.wav", preview["source_ref"])
            self.assertTrue(preview["ref"].startswith("previews/"))
            excerpt = root.joinpath(*preview["ref"].split("/"))
            self.assertTrue(excerpt.is_file())
            self.assertLess(excerpt.stat().st_size, vo_src.stat().st_size)
            self.assertAlmostEqual(preview["duration_s"], 3.0, delta=1.0 / 30)
            dumped = json.dumps(frozen["sound_cues"])
            self.assertNotIn("narration/private", dumped)
            self.assertNotIn(str(vo_src), dumped)
            self.assertNotIn("source_ref", dumped)

    @skip_unless_ffmpeg
    def test_refuses_foreign_collision_and_preserves_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _wav(root / "sounds" / "whip.wav", TONE_A, 1)
            record = normalize_audio(
                root,
                {"effects": [_effect("hit", "sounds/whip.wav", duration_s=0.4)]},
                PROFILE,
                _estimated(),
            )
            version_dir = root / "graphics" / "numeric-stat" / "v1"
            dest = version_dir / "public" / "audio" / "hit.wav"
            dest.parent.mkdir(parents=True)
            dest.write_bytes(b"FOREIGN-AUDIO")
            before = dest.read_bytes()
            with self.assertRaises(ValueError):
                freeze_audio(root, version_dir, record)
            self.assertEqual(before, dest.read_bytes())

    def test_missing_version_dir_does_not_create_tree(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            version_dir = root / "graphics" / "numeric-stat" / "v1"
            with self.assertRaises(ValueError):
                freeze_audio(
                    root,
                    version_dir,
                    {
                        "schema_version": 1,
                        "fps": 30,
                        "duration_in_frames": 90,
                        "effects": [],
                        "vo": None,
                    },
                )
            self.assertFalse(version_dir.exists())

    @skip_unless_ffmpeg
    def test_fragment_excerpt_is_preview_only(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = _wav(root / "previews" / "vo-fragment.wav", TONE_C, 3)
            record = normalize_audio(
                root,
                {
                    "vo": {
                        "ref": "previews/vo-fragment.wav",
                        "kind": "fragment",
                        "source_start_s": 0.0,
                        "source_end_s": 3.0,
                        "gain": 0.8,
                    }
                },
                PROFILE,
                _estimated(),
            )
            version_dir = root / "graphics" / "numeric-stat" / "v1"
            version_dir.mkdir(parents=True)
            frozen = freeze_audio(root, version_dir, record)
            self.assertEqual([], frozen["sound_cues"])
            self.assertEqual([], frozen["assets"])
            preview = frozen["vo_preview"]
            self.assertEqual("fragment", preview["kind"])
            self.assertEqual("previews/vo-fragment.wav", preview["source_ref"])
            self.assertTrue(preview["ref"].startswith("previews/graphics-"))
            self.assertNotEqual(preview["ref"], preview["source_ref"])
            excerpt = root.joinpath(*preview["ref"].split("/"))
            self.assertTrue(excerpt.is_file())
            self.assertAlmostEqual(preview["duration_s"], 3.0, delta=1.0 / 30)
            self.assertLessEqual(excerpt.stat().st_size, source.stat().st_size)
            self.assertNotIn("source_ref", json.dumps(frozen["sound_cues"]))
            self.assertFalse((version_dir / "public" / "audio").exists())

    @skip_unless_ffmpeg
    def test_hash_change_preflight_does_not_create_dest(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            whip = _wav(root / "sounds" / "whip.wav", TONE_A, 1)
            record = normalize_audio(
                root,
                {"effects": [_effect("hit", "sounds/whip.wav", duration_s=0.4)]},
                PROFILE,
                _estimated(),
            )
            version_dir = root / "graphics" / "numeric-stat" / "v1"
            version_dir.mkdir(parents=True)
            dest = version_dir / "public" / "audio" / "hit.wav"
            whip.write_bytes(whip.read_bytes() + b"tamper")
            with self.assertRaises(ValueError):
                freeze_audio(root, version_dir, record)
            self.assertFalse(dest.exists())
            self.assertFalse((version_dir / "public").exists())

    @skip_unless_ffmpeg
    def test_repeated_asset_freeze_keeps_both_placements(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _wav(root / "sounds" / "whip.wav", TONE_A, 1)
            record = normalize_audio(
                root,
                {
                    "effects": [
                        _effect("hit", "sounds/whip.wav", duration_s=0.4, start_frame=0),
                        _effect("hit-late", "sounds/whip.wav", duration_s=0.4, start_frame=30),
                    ]
                },
                PROFILE,
                _estimated(),
            )
            version_dir = root / "graphics" / "numeric-stat" / "v1"
            version_dir.mkdir(parents=True)
            frozen = freeze_audio(root, version_dir, record)
            self.assertEqual(2, len(frozen["sound_cues"]))
            self.assertEqual("hit", frozen["sound_cues"][0]["id"])
            self.assertEqual("hit-late", frozen["sound_cues"][1]["id"])
            self.assertEqual("audio/hit.wav", frozen["sound_cues"][0]["src"])
            self.assertEqual("audio/hit-late.wav", frozen["sound_cues"][1]["src"])
            self.assertEqual(0, frozen["sound_cues"][0]["start_frame"])
            self.assertEqual(30, frozen["sound_cues"][1]["start_frame"])
            self.assertEqual(2, len(frozen["assets"]))
            self.assertEqual("sounds/whip.wav", frozen["assets"][0]["ref"])
            self.assertEqual("sounds/whip.wav", frozen["assets"][1]["ref"])
            self.assertTrue((version_dir / "public" / "audio" / "hit.wav").is_file())
            self.assertTrue((version_dir / "public" / "audio" / "hit-late.wav").is_file())

    @skip_unless_ffmpeg
    def test_foreign_vo_part_is_refused_and_frozen_effects_are_preserved(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _wav(root / "sounds" / "whip.wav", TONE_A, 1)
            vo_src = _wav(root / "narration" / "private" / "audio" / "take.wav", TONE_C, 5)
            record = normalize_audio(
                root,
                {
                    "effects": [_effect("hit", "sounds/whip.wav", duration_s=0.4)],
                    "vo": {
                        "ref": "narration/private/audio/take.wav",
                        "kind": "full_recording",
                        "source_start_s": 1.0,
                        "source_end_s": 4.0,
                        "gain": 1,
                    },
                },
                PROFILE,
                _explicit(1.0, 4.0),
            )
            version_dir = root / "graphics" / "numeric-stat" / "v1"
            version_dir.mkdir(parents=True)
            part = root / "previews" / "graphics-numeric-stat-v1-vo.wav.part"
            part.parent.mkdir(parents=True)
            part.write_bytes(b"FOREIGN-PART")
            before = part.read_bytes()
            frozen_effect = version_dir / "public" / "audio" / "hit.wav"
            with self.assertRaises(ValueError) as raised:
                freeze_audio(root, version_dir, record)
            self.assertIn("already exists", str(raised.exception).lower())
            self.assertEqual(before, part.read_bytes())
            self.assertTrue(frozen_effect.is_file())
            self.assertEqual(file_digest(root / "sounds" / "whip.wav"), file_digest(frozen_effect))
            self.assertTrue(vo_src.is_file())
            self.assertFalse((root / "previews" / "graphics-numeric-stat-v1-vo.wav").exists())


class ImportSfxTests(unittest.TestCase):
    @skip_unless_ffmpeg
    def test_controlled_download_reuse_and_hash_change(self):
        with tempfile.TemporaryDirectory() as tmp:
            _assign_graphics(tmp)
            source = Path(tmp) / "fixture-whip.wav"
            _wav(source, TONE_A, 1)
            calls = []

            def downloader(url, target, max_bytes=None):
                calls.append({"url": url, "target": str(target), "max_bytes": max_bytes})
                shutil.copyfile(source, target)
                return target

            ledger = Ledger(tmp)
            first = import_sfx_command(
                ledger,
                SimpleNamespace(sfx="whip", asset="whip-1"),
                downloader=downloader,
            )
            self.assertFalse(first["reused"])
            self.assertTrue(first["downloaded"])
            self.assertEqual(1, len(calls))
            self.assertEqual(SFX_ROUTES["whip"]["url"], calls[0]["url"])
            self.assertEqual("CC0", first["sound"]["license"])
            self.assertIn("not inferred from the @remotion/sfx npm MIT", first["sound"]["conditions"])
            saved = Ledger(tmp, recover=False).data["graphics"]["sounds"]["whip-1"]
            self.assertEqual(first["sound"]["sha256"], saved["sha256"])
            second = import_sfx_command(
                ledger,
                SimpleNamespace(sfx="whip", asset="whip-1"),
                downloader=downloader,
            )
            self.assertTrue(second["reused"])
            self.assertFalse(second["downloaded"])
            self.assertEqual(1, len(calls))
            dest = Path(tmp) / "brolls" / "sounds" / "whip-1.wav"
            dest.write_bytes(dest.read_bytes() + b"tamper")
            with self.assertRaises(ValueError) as raised:
                import_sfx_command(
                    Ledger(tmp),
                    SimpleNamespace(sfx="whip", asset="whip-1"),
                    downloader=downloader,
                )
            self.assertIn("hash changed", str(raised.exception).lower())
            self.assertEqual(1, len(calls))

    @skip_unless_ffmpeg
    def test_foreign_destination_and_missing_graphics_are_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            run_cli("init-rules", project=tmp)
            source = Path(tmp) / "fixture-whip.wav"
            _wav(source, TONE_A, 1)

            def downloader(url, target, max_bytes=None):
                raise AssertionError("download must not run")

            ledger = Ledger(tmp)
            with self.assertRaises(ValueError) as missing:
                import_sfx_command(ledger, SimpleNamespace(sfx="whip", asset="whip-1"), downloader=downloader)
            self.assertIn("graphics-assign", str(missing.exception))
            run_cli(
                "graphics-assign",
                "--scene",
                "numeric-stat",
                "--occurrence",
                "stat-01",
                "--chapter",
                "ch-1",
                "--chapter-context",
                "Surrounding chapter text from the scenario.",
                "--purpose",
                "Show the synthetic count",
                "--narration",
                "The count stands at twelve units.",
                "--timing",
                "estimated",
                "--duration",
                "3",
                project=tmp,
            )
            dest = Path(tmp) / "brolls" / "sounds" / "whip-1.wav"
            dest.parent.mkdir(parents=True)
            dest.write_bytes(b"FOREIGN")
            with self.assertRaises(ValueError) as collision:
                import_sfx_command(
                    Ledger(tmp),
                    SimpleNamespace(sfx="whip", asset="whip-1"),
                    downloader=downloader,
                )
            self.assertIn("already exists", str(collision.exception))
            self.assertEqual(b"FOREIGN", dest.read_bytes())

    @skip_unless_ffmpeg
    def test_reuses_intact_bytes_for_a_new_asset_id_without_download(self):
        with tempfile.TemporaryDirectory() as tmp:
            _assign_graphics(tmp)
            source = Path(tmp) / "fixture-whoosh.wav"
            _wav(source, TONE_B, 1)
            calls = []

            def downloader(url, target, max_bytes=None):
                calls.append(url)
                shutil.copyfile(source, target)
                return target

            ledger = Ledger(tmp)
            first = import_sfx_command(
                ledger,
                SimpleNamespace(sfx="whoosh", asset="whoosh-a"),
                downloader=downloader,
            )
            second = import_sfx_command(
                Ledger(tmp),
                SimpleNamespace(sfx="whoosh", asset="whoosh-b"),
                downloader=downloader,
            )
            self.assertEqual(1, len(calls))
            self.assertTrue(second["reused"])
            self.assertFalse(second["downloaded"])
            self.assertEqual(first["sound"]["sha256"], second["sound"]["sha256"])
            self.assertEqual("sounds/whoosh-b.wav", second["sound"]["ref"])

    @skip_unless_ffmpeg
    def test_reuse_preserves_stricter_registered_permissions(self):
        with tempfile.TemporaryDirectory() as tmp:
            _assign_graphics(tmp)
            source = Path(tmp) / "fixture-whoosh.wav"
            _wav(source, TONE_B, 1)
            calls = []

            def downloader(url, target, max_bytes=None):
                calls.append(url)
                shutil.copyfile(source, target)
                return target

            import_sfx_command(
                Ledger(tmp),
                SimpleNamespace(sfx="whoosh", asset="whoosh-a"),
                downloader=downloader,
            )
            ledger = Ledger(tmp, recover=False)
            saved = ledger.data["graphics"]["sounds"]["whoosh-a"]
            saved["raw_redistribution"] = "restricted"
            saved["rendered_use"] = "restricted"
            saved["conditions"] = "Project permits rendered use; raw redistribution restricted."
            ledger.save("graphics-sound-import")
            second = import_sfx_command(
                Ledger(tmp),
                SimpleNamespace(sfx="whoosh", asset="whoosh-b"),
                downloader=downloader,
            )
            self.assertEqual(1, len(calls))
            self.assertTrue(second["reused"])
            self.assertFalse(second["downloaded"])
            self.assertEqual("restricted", second["sound"]["raw_redistribution"])
            self.assertEqual("restricted", second["sound"]["rendered_use"])
            self.assertEqual(
                "Project permits rendered use; raw redistribution restricted.",
                second["sound"]["conditions"],
            )
            stored = Ledger(tmp, recover=False).data["graphics"]["sounds"]["whoosh-b"]
            self.assertEqual("restricted", stored["raw_redistribution"])
            self.assertEqual(saved["sha256"], stored["sha256"])


class UnsafeRootTests(unittest.TestCase):
    @skip_unless_ffmpeg
    def test_lexical_root_junction_does_not_redefine_confinement(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            root = tmp_path / "brolls"
            root.mkdir()
            whip = _wav(root / "sounds" / "whip.wav", TONE_A, 1)
            payload = {"effects": [_effect("hit", "sounds/whip.wav", duration_s=0.4)]}
            record = normalize_audio(root, payload, PROFILE, _estimated())
            self.assertTrue(audio_readiness(root, record)["ready"])

            sentinel = b"EXTERNAL-AUDIO-SENTINEL-DO-NOT-FOLLOW"
            external = tmp_path / "external-target"
            external.mkdir()
            (external / "sounds").mkdir()
            shutil.copyfile(whip, external / "sounds" / "whip.wav")
            (external / "sentinel.bin").write_bytes(sentinel)
            linked_root = tmp_path / "linked-brolls"
            if not _dir_link(linked_root, external):
                self.skipTest("could not create a root junction or directory symlink")
            try:
                with self.assertRaises(ValueError) as ctx:
                    normalize_audio(linked_root, copy.deepcopy(payload), PROFILE, _estimated())
                self.assertIn("symlink or junction", str(ctx.exception))
                ready = audio_readiness(linked_root, record)
                self.assertFalse(ready["ready"])
                self.assertTrue(any("symlink or junction" in reason.lower() for reason in ready["reasons"]))
                version_dir = linked_root / "graphics" / "numeric-stat" / "v1"
                version_dir.mkdir(parents=True)
                with self.assertRaises(ValueError) as freeze_ctx:
                    freeze_audio(linked_root, version_dir, record)
                self.assertIn("symlink or junction", str(freeze_ctx.exception))
                self.assertEqual(sentinel, (external / "sentinel.bin").read_bytes())
                self.assertTrue((external / "sounds" / "whip.wav").is_file())
            finally:
                _remove_owned_link(linked_root)
            self.assertFalse(linked_root.exists())
            self.assertFalse(linked_root.is_symlink())
            self.assertFalse(_is_reparse_path(linked_root))
            self.assertEqual(sentinel, (external / "sentinel.bin").read_bytes())

    @skip_unless_ffmpeg
    def test_parent_ancestor_junction_is_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            external = tmp_path / "external-target"
            real_root = external / "brolls"
            real_root.mkdir(parents=True)
            _wav(real_root / "sounds" / "whip.wav", TONE_A, 1)
            (external / "sentinel.bin").write_bytes(b"PARENT-JUNCTION-SENTINEL")
            linked_parent = tmp_path / "linked-parent"
            if not _dir_link(linked_parent, external):
                self.skipTest("could not create a parent junction or directory symlink")
            lexical_root = linked_parent / "brolls"
            payload = {"effects": [_effect("hit", "sounds/whip.wav", duration_s=0.4)]}
            try:
                with self.assertRaises(ValueError) as ctx:
                    normalize_audio(lexical_root, payload, PROFILE, _estimated())
                self.assertIn("symlink or junction", str(ctx.exception))
                self.assertEqual(b"PARENT-JUNCTION-SENTINEL", (external / "sentinel.bin").read_bytes())
            finally:
                _remove_owned_link(linked_parent)
            self.assertEqual(b"PARENT-JUNCTION-SENTINEL", (external / "sentinel.bin").read_bytes())

    @skip_unless_ffmpeg
    def test_grandparent_ancestor_junction_is_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            external = tmp_path / "external-target"
            real_root = external / "parent" / "brolls"
            real_root.mkdir(parents=True)
            whip = _wav(real_root / "sounds" / "whip.wav", TONE_A, 1)
            sentinel = b"GRANDPARENT-JUNCTION-SENTINEL"
            (external / "sentinel.bin").write_bytes(sentinel)
            payload = {"effects": [_effect("hit", "sounds/whip.wav", duration_s=0.4)]}
            record = normalize_audio(real_root, payload, PROFILE, _estimated())
            self.assertTrue(audio_readiness(real_root, record)["ready"])
            _assign_graphics(tmp_path / "import-project")
            linked_grandparent = tmp_path / "linked-grandparent"
            if not _dir_link(linked_grandparent, external):
                self.skipTest("could not create a grandparent junction or directory symlink")
            lexical_root = linked_grandparent / "parent" / "brolls"
            calls = []

            def downloader(url, target, max_bytes=None):
                calls.append(url)
                raise AssertionError("download must not run")

            try:
                with self.assertRaises(ValueError) as ctx:
                    normalize_audio(lexical_root, copy.deepcopy(payload), PROFILE, _estimated())
                self.assertIn("symlink or junction", str(ctx.exception))
                ready = audio_readiness(lexical_root, record)
                self.assertFalse(ready["ready"])
                self.assertTrue(any("symlink or junction" in reason.lower() for reason in ready["reasons"]))
                version_dir = lexical_root / "graphics" / "numeric-stat" / "v1"
                version_dir.mkdir(parents=True)
                with self.assertRaises(ValueError) as freeze_ctx:
                    freeze_audio(lexical_root, version_dir, record)
                self.assertIn("symlink or junction", str(freeze_ctx.exception))
                ledger = Ledger(tmp_path / "import-project")
                ledger.root = lexical_root
                with self.assertRaises(ValueError) as import_ctx:
                    import_sfx_command(
                        ledger,
                        SimpleNamespace(sfx="whip", asset="whip-1"),
                        downloader=downloader,
                    )
                self.assertIn("symlink or junction", str(import_ctx.exception))
                self.assertEqual([], calls)
                self.assertEqual(sentinel, (external / "sentinel.bin").read_bytes())
                self.assertTrue((external / "parent" / "brolls" / "sounds" / "whip.wav").is_file())
            finally:
                _remove_owned_link(linked_grandparent)
            self.assertFalse(linked_grandparent.exists())
            self.assertFalse(linked_grandparent.is_symlink())
            self.assertFalse(_is_reparse_path(linked_grandparent))
            self.assertEqual(sentinel, (external / "sentinel.bin").read_bytes())
            self.assertTrue(whip.is_file())

    @skip_unless_ffmpeg
    def test_import_refuses_lexical_root_junction_without_download(self):
        with tempfile.TemporaryDirectory() as tmp:
            _assign_graphics(tmp)
            source = Path(tmp) / "fixture-whip.wav"
            _wav(source, TONE_A, 1)
            calls = []

            def downloader(url, target, max_bytes=None):
                calls.append(url)
                raise AssertionError("download must not run")

            ledger = Ledger(tmp)
            external = Path(tmp) / "external-root"
            external.mkdir()
            (external / "sentinel.bin").write_bytes(b"IMPORT-JUNCTION-SENTINEL")
            linked_root = Path(tmp) / "linked-brolls"
            if not _dir_link(linked_root, external):
                self.skipTest("could not create a root junction or directory symlink")
            try:
                ledger.root = linked_root
                with self.assertRaises(ValueError) as ctx:
                    import_sfx_command(
                        ledger,
                        SimpleNamespace(sfx="whip", asset="whip-1"),
                        downloader=downloader,
                    )
                self.assertIn("symlink or junction", str(ctx.exception))
                self.assertEqual([], calls)
                self.assertEqual(b"IMPORT-JUNCTION-SENTINEL", (external / "sentinel.bin").read_bytes())
            finally:
                _remove_owned_link(linked_root)


class RendererSourceTests(unittest.TestCase):
    def test_graphics_audio_uses_installed_remotion_audio(self):
        source = (ROOT / "scripts" / "graphics" / "src" / "GraphicsAudio.jsx").read_text(encoding="utf-8")
        self.assertIn('from "remotion"', source)
        self.assertIn("Audio", source)
        self.assertIn("Sequence", source)
        self.assertIn("staticFile", source)
        self.assertIn("trimBefore", source)
        self.assertNotIn("@remotion/media", source)
        self.assertIn("voice-over", source)

    def test_numeric_stat_keeps_honest_labels_and_estimated_timing(self):
        source = (ROOT / "scripts" / "graphics" / "src" / "NumericStat.jsx").read_text(encoding="utf-8")
        self.assertIn("Synthetic draft value", source)
        self.assertIn("Unverified scenario claim", source)
        self.assertIn("Sourced from recorded evidence", source)
        self.assertIn("Estimated draft timing", source)
        self.assertIn("GraphicsAudio", source)
        self.assertIn("sound_cues", source)
        self.assertIn("fontFamily: '\"IBM Plex Sans\", sans-serif'", source)

    def test_worker_legacy_silence_and_effects_aac(self):
        source = (ROOT / "scripts" / "graphics" / "render.mjs").read_text(encoding="utf-8")
        self.assertIn('mode !== "effects"', source)
        self.assertIn('codec !== "aac"', source)
        self.assertIn("muted: audio.muted", source)
        self.assertIn("audioCodec", source)
        self.assertIn("enforceAudioTrack", source)
        self.assertIn("voice-over", source)
        self.assertIn("Legacy silent graphics jobs cannot carry sound_cues", source)
        self.assertIn("unsupported keys", source)


if __name__ == "__main__":
    unittest.main()
