"""#57 public audio workflow: cues, AAC vs VO exclusion, sync fixture, no download on view."""

from __future__ import annotations

import array
import json
import math
import subprocess
import sys
import tempfile
import unittest
import wave
from html.parser import HTMLParser
from pathlib import Path

import _isolation  # noqa: F401
from _cli import run_cli
from _media import skip_unless_ffmpeg
from _paths import CLI, ROOT
from test_graphics_review import _assign, _project

from getbrolls.graphics import (
    AUDIO_TEMPLATE_FILES,
    TEMPLATE_DIR,
    TEMPLATE_FILES,
    _source_template_names,
    graphics_content_sha256,
)
from getbrolls.ledger import Ledger
from getbrolls.ledger import digest as file_digest


class _MediaTags(HTMLParser):
    def __init__(self):
        super().__init__()
        self.media = []

    def handle_starttag(self, tag, attrs):
        if tag in {"audio", "video"}:
            self.media.append((tag, dict(attrs)))


def _assert_no_media_autoplay(case, page):
    parsed = _MediaTags()
    parsed.feed(page)
    case.assertTrue(parsed.media, "The page must contain the media players being checked")
    for tag, attrs in parsed.media:
        case.assertNotIn("autoplay", attrs, f"The {tag} element must wait for explicit playback")


class MediaPlaybackMarkupTests(unittest.TestCase):
    def test_no_autoplay_check_reads_media_attributes_instead_of_script_text(self):
        _assert_no_media_autoplay(self, "<audio controls></audio><script>audio.autoplay = false;</script>")
        for attribute in ("autoplay", 'autoplay="false"'):
            with self.subTest(attribute=attribute), self.assertRaises(AssertionError):
                _assert_no_media_autoplay(self, f"<video {attribute}></video>")


SILENT_WORKER = ROOT / "tests" / "fixtures" / "graphics_worker.py"
AUDIO_WORKER = ROOT / "tests" / "fixtures" / "graphics_audio_worker.py"
AUDIO_ENV = {"GB_GRAPHICS_WORKER": str(AUDIO_WORKER)}
SILENT_ENV = {"GB_GRAPHICS_WORKER": str(SILENT_WORKER)}
STATEMENT = "Synthetic fixture: I approve this exact version."
FX_HZ = 880
VO_HZ = 220
FX_OVER_VO_RATIO = 8
FX_CUE_OVER_TAIL_RATIO = 4
RMS_CUE_OVER_TAIL_RATIO = 3
GOERTZEL_MIN_SAMPLES = 8


def _write(path, text):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def _wav(path, frequency, duration):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-v",
            "error",
            "-f",
            "lavfi",
            "-i",
            f"sine=frequency={frequency}:duration={duration}",
            "-c:a",
            "pcm_s16le",
            str(path),
        ],
        check=True,
        capture_output=True,
    )
    return path


def _probe(path):
    raw = subprocess.run(
        [
            "ffprobe",
            "-v",
            "error",
            "-show_entries",
            "stream=codec_name,codec_type,duration,color_space:format=duration,nb_streams",
            "-of",
            "json",
            str(path),
        ],
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    return json.loads(raw.stdout)


def _pcm_mono16(src, dest, rate=48000):
    subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-v",
            "error",
            "-i",
            str(src),
            "-vn",
            "-ac",
            "1",
            "-ar",
            str(rate),
            "-c:a",
            "pcm_s16le",
            str(dest),
        ],
        check=True,
        capture_output=True,
    )
    with wave.open(str(dest), "rb") as handle:
        samples = array.array("h")
        samples.frombytes(handle.readframes(handle.getnframes()))
        return samples, handle.getframerate()


def _goertzel_power(samples, freq, rate):
    n = len(samples)
    if n < GOERTZEL_MIN_SAMPLES:
        return 0.0
    k = int(0.5 + (n * float(freq)) / float(rate))
    omega = 2.0 * math.pi * k / n
    coeff = 2.0 * math.cos(omega)
    s0 = s1 = s2 = 0.0
    for sample in samples:
        s0 = float(sample) + coeff * s1 - s2
        s2 = s1
        s1 = s0
    return (s1 * s1 + s2 * s2 - coeff * s1 * s2) / (n * n)


def _slice_seconds(samples, rate, start_s, end_s):
    start = max(0, int(start_s * rate))
    end = min(len(samples), int(end_s * rate))
    return samples[start:end]


def _rms(samples):
    if not samples:
        return 0.0
    total = sum(float(sample) * float(sample) for sample in samples)
    return math.sqrt(total / len(samples))


def _assert_decoded_fx_without_vo(test, artifact, tmp):
    samples, rate = _pcm_mono16(artifact, Path(tmp) / "decoded-fx.wav")
    cue = _slice_seconds(samples, rate, 0.02, 0.32)
    later = _slice_seconds(samples, rate, 0.7, 1.2)
    fx_cue = _goertzel_power(cue, FX_HZ, rate)
    vo_cue = _goertzel_power(cue, VO_HZ, rate)
    fx_later = _goertzel_power(later, FX_HZ, rate)
    test.assertGreater(fx_cue, vo_cue * FX_OVER_VO_RATIO)
    test.assertGreater(fx_cue, fx_later * FX_CUE_OVER_TAIL_RATIO)
    test.assertGreater(_rms(cue), _rms(later) * RMS_CUE_OVER_TAIL_RATIO)


def _assert_effects_job(test, job):
    test.assertEqual({"mode": "effects", "codec": "aac"}, job.get("audio"))
    test.assertIn("sound_cues", job["props"])
    test.assertNotIn("vo", job["props"])
    test.assertNotIn("source_ref", json.dumps(job["props"]))
    test.assertNotIn("narration/private", json.dumps(job))
    cues = job["props"]["sound_cues"]
    test.assertEqual(1, len(cues))
    test.assertEqual(0, cues[0]["start_frame"])
    test.assertGreater(cues[0]["duration_in_frames"], 0)
    test.assertEqual(1, cues[0]["gain"])
    test.assertTrue(str(cues[0]["src"]).startswith("audio/"))


def _assert_package_excludes_vo(test, pkg):
    rerender = json.loads((pkg / "rerender.json").read_text(encoding="utf-8"))
    test.assertEqual({"mode": "effects", "codec": "aac"}, rerender.get("audio"))
    test.assertIn("sound_cues", rerender["props"])
    adapter = (pkg / "rerender.py").read_text(encoding="utf-8")
    test.assertIn('job["audio"] = config["audio"]', adapter)
    test.assertTrue(any(pkg.joinpath("public", "audio").glob("*")))
    test.assertFalse((pkg / "narration").exists())
    listed = "\n".join(str(path) for path in pkg.rglob("*"))
    test.assertNotIn("private", listed)


def _shared_original_effects(effect_ref, effect_sha, *, first_raw="restricted", second_raw="restricted"):
    def effect(cue_id, start_frame, gain, raw):
        return {
            "id": cue_id,
            "ref": effect_ref,
            "sha256": effect_sha,
            "source_url": "https://remotion.media/whip.wav",
            "terms_url": "https://www.remotion.dev/docs/sfx/whip",
            "license": "CC0-1.0",
            "conditions": "SYNTHETIC TECHNICAL FIXTURE: shared original; raw " + raw + ".",
            "rendered_use": "permitted",
            "raw_redistribution": raw,
            "start_frame": start_frame,
            "source_start_s": 0,
            "duration_s": 0.3,
            "gain": gain,
        }

    return {
        "schema_version": 1,
        "effects": [
            effect("cue-1", 0, 1, first_raw),
            effect("cue-2", 30, 0.6, second_raw),
        ],
    }


def _assert_decoded_shared_cues(test, artifact, tmp):
    samples, rate = _pcm_mono16(artifact, Path(tmp) / "decoded-shared-cues.wav")
    first = _slice_seconds(samples, rate, 0.05, 0.25)
    middle = _slice_seconds(samples, rate, 0.5, 0.8)
    second = _slice_seconds(samples, rate, 1.05, 1.25)
    first_fx = _goertzel_power(first, FX_HZ, rate)
    second_fx = _goertzel_power(second, FX_HZ, rate)
    middle_fx = _goertzel_power(middle, FX_HZ, rate)
    vo_first = _goertzel_power(first, VO_HZ, rate)
    test.assertGreater(first_fx, middle_fx * FX_CUE_OVER_TAIL_RATIO)
    test.assertGreater(second_fx, middle_fx * FX_CUE_OVER_TAIL_RATIO)
    test.assertGreater(first_fx, vo_first * FX_OVER_VO_RATIO)
    test.assertGreater(_rms(first), _rms(middle) * RMS_CUE_OVER_TAIL_RATIO)
    test.assertGreater(_rms(second), _rms(middle) * RMS_CUE_OVER_TAIL_RATIO)


def _audio_payload(effect_ref, effect_sha, vo_ref, vo_sha, *, duration_s=0.4):
    return {
        "schema_version": 1,
        "effects": [
            {
                "id": "whip-1",
                "ref": effect_ref,
                "sha256": effect_sha,
                "source_url": "https://remotion.media/whip.wav",
                "terms_url": "https://www.remotion.dev/docs/sfx/whip",
                "license": "CC0-1.0",
                "conditions": "Permitted CC0 effect; viewing is not a download.",
                "rendered_use": "permitted",
                "raw_redistribution": "permitted",
                "start_frame": 0,
                "source_start_s": 0,
                "duration_s": duration_s,
                "gain": 1,
            }
        ],
        "vo": {
            "ref": vo_ref,
            "sha256": vo_sha,
            "kind": "fragment",
            "source_start_s": 0,
            "source_end_s": 1.5,
            "gain": 1,
        },
    }


def _approve(tmp, version="v1"):
    return run_cli(
        "graphics-approve",
        "--occurrence",
        "stat-01",
        "--version",
        version,
        "--by",
        "Human",
        "--statement",
        STATEMENT,
        project=tmp,
    )


def _package_digest_hits(pkg, digest_value):
    hits = []
    for path in pkg.rglob("*"):
        if not path.is_file() or path.is_symlink():
            continue
        try:
            if file_digest(path) == digest_value:
                hits.append(path.relative_to(pkg).as_posix())
        except OSError:
            continue
    return hits


def _rerender_pkg(pkg, extra=None, *, check=False):
    cmd = [sys.executable, str(pkg / "rerender.py")]
    if check:
        cmd.append("--check")
    cmd.extend(extra or [])
    return subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
        cwd=str(pkg),
    )


@skip_unless_ffmpeg
class GraphicsAudioWorkflowTests(unittest.TestCase):
    def test_cues_store_aac_and_exclude_vo_by_decoded_signal(self):
        with tempfile.TemporaryDirectory() as tmp:
            _project(tmp)
            _assign(tmp, timing="explicit", start="0", end="1.5")
            fx = _wav(Path(tmp) / "brolls" / "sounds" / "whip.wav", FX_HZ, 1)
            vo = _wav(Path(tmp) / "brolls" / "narration" / "private" / "audio" / "vo.wav", VO_HZ, 4)
            payload = _audio_payload(
                "sounds/whip.wav",
                file_digest(fx),
                "narration/private/audio/vo.wav",
                file_digest(vo),
            )
            audio_file = _write(Path(tmp) / "brolls" / "audio-stat-01.json", json.dumps(payload))
            saved = run_cli(
                "graphics-audio",
                "--occurrence",
                "stat-01",
                "--file",
                str(audio_file),
                project=tmp,
            )
            self.assertTrue(saved["audio"]["effects"])
            rendered = run_cli("graphics-render", "--occurrence", "stat-01", project=tmp, env=AUDIO_ENV)
            job = json.loads(
                (Path(tmp) / "brolls" / "graphics" / "numeric-stat" / "v1" / "job.json").read_text(encoding="utf-8")
            )
            _assert_effects_job(self, job)
            artifact = Path(tmp) / "brolls" / rendered["review"]
            probed = _probe(artifact)
            streams = probed.get("streams") or []
            kinds = {item.get("codec_type"): item.get("codec_name") for item in streams}
            self.assertEqual("h264", kinds.get("video"))
            self.assertEqual("aac", kinds.get("audio"))
            self.assertEqual(2, probed.get("format", {}).get("nb_streams") or len(streams))
            video = next(item for item in streams if item.get("codec_type") == "video")
            self.assertEqual("bt709", video.get("color_space"))
            _assert_decoded_fx_without_vo(self, artifact, tmp)
            version = rendered["version"]
            self.assertEqual("aac", version["artifact"].get("audio_codec"))
            self.assertEqual(1, version["artifact"].get("audio_streams"))
            preview = version.get("vo_preview") or {}
            if preview.get("ref"):
                self.assertTrue(str(preview["ref"]).startswith("previews/"))
                self.assertNotIn("narration/private", str(preview["ref"]))
            run_cli("review", project=tmp)
            page = (Path(tmp) / "brolls" / "review.html").read_text(encoding="utf-8")
            self.assertIn("graphics-vo-preview", page)
            self.assertNotIn("narration/private/audio/vo.wav", page)
            _assert_no_media_autoplay(self, page)
            _approve(tmp)
            run_cli("deliver", project=tmp)
            pkg = Path(tmp) / "entrega" / "graphics" / "numeric-stat" / "stat-01" / "v1"
            _assert_package_excludes_vo(self, pkg)
            self.assertTrue(_package_digest_hits(pkg, file_digest(fx)))
            status = run_cli("status", project=tmp)
            public = json.dumps(status["graphics"])
            self.assertNotIn("narration/private/audio/vo.wav", public)

    def test_changed_cues_need_fresh_review_and_old_silent_signature_stays(self):
        with tempfile.TemporaryDirectory() as tmp:
            _project(tmp)
            _assign(tmp, timing="explicit", start="0", end="1.5")
            silent = run_cli("graphics-render", "--occurrence", "stat-01", project=tmp, env=SILENT_ENV)
            old_content = graphics_content_sha256(silent["version"])
            self.assertNotIn("audio", silent["version"]["fingerprints"])
            self.assertIn("GraphicsAudio.jsx", silent["version"]["fingerprints"]["source"])
            expected_sources = {
                "index.jsx",
                "Root.jsx",
                "NumericStat.jsx",
                "GraphicsAudio.jsx",
                "GraphicsBackground.jsx",
            }
            self.assertEqual(expected_sources, set(silent["version"]["fingerprints"]["source"]))
            self.assertNotIn("audio_codec", silent["version"]["artifact"])
            job = json.loads(
                (Path(tmp) / "brolls" / "graphics" / "numeric-stat" / "v1" / "job.json").read_text(encoding="utf-8")
            )
            self.assertNotIn("audio", job)
            fx = _wav(Path(tmp) / "brolls" / "sounds" / "whoosh.wav", FX_HZ, 1)
            payload = {
                "schema_version": 1,
                "effects": [
                    {
                        "id": "whoosh-1",
                        "ref": "sounds/whoosh.wav",
                        "sha256": file_digest(fx),
                        "source_url": "https://remotion.media/whoosh.wav",
                        "terms_url": "https://www.remotion.dev/docs/sfx/whoosh",
                        "license": "CC0-1.0",
                        "conditions": "Permitted CC0 effect.",
                        "rendered_use": "permitted",
                        "raw_redistribution": "restricted",
                        "start_frame": 0,
                        "source_start_s": 0,
                        "duration_s": 0.3,
                        "gain": 1,
                    }
                ],
            }
            audio_file = _write(Path(tmp) / "brolls" / "audio-whoosh.json", json.dumps(payload))
            run_cli("graphics-audio", "--occurrence", "stat-01", "--file", str(audio_file), project=tmp)
            ledger = Ledger(tmp, recover=False)
            v1 = ledger.data["graphics"]["versions"]["v1"]
            self.assertEqual(old_content, graphics_content_sha256(v1))
            status = run_cli("status", project=tmp)
            item = next(row for row in status["graphics"]["items"] if row["occurrence_id"] == "stat-01")
            self.assertIn("assignment_drift", item["reasons"])
            second = run_cli("graphics-render", "--occurrence", "stat-01", project=tmp, env=AUDIO_ENV)
            self.assertEqual("v2", second["version"]["id"])
            self.assertNotEqual(old_content, graphics_content_sha256(second["version"]))
            self.assertEqual("v1", second["version"]["parent"])
            sources = set(second["version"]["fingerprints"]["source"])
            self.assertIn("GraphicsAudio.jsx", sources)
            self.assertEqual(expected_sources, sources)
            self.assertEqual(expected_sources, set(v1["fingerprints"]["source"]))
            _approve(tmp, version="v2")
            run_cli("deliver", project=tmp)
            pkg = Path(tmp) / "entrega" / "graphics" / "numeric-stat" / "stat-01" / "v2"
            held_path = pkg / "separately-held.json"
            held = json.loads(held_path.read_text(encoding="utf-8"))
            self.assertTrue(any(item.get("ref") == "sounds/whoosh.wav" for item in held))
            self.assertEqual([], _package_digest_hits(pkg, file_digest(fx)))
            frozen_audio = Path(tmp) / "brolls" / "graphics" / "numeric-stat" / "v2" / "public" / "audio"
            self.assertTrue(any(file_digest(path) == file_digest(fx) for path in frozen_audio.glob("*")))
            self.assertTrue((Path(tmp) / "brolls" / "graphics" / "numeric-stat" / "v1").is_dir())

    def test_restricted_raw_effect_stays_held_and_reconstructs_from_held_ref(self):
        with tempfile.TemporaryDirectory() as tmp:
            _project(tmp)
            _assign(tmp, timing="explicit", start="0", end="1.5")
            silent = run_cli("graphics-render", "--occurrence", "stat-01", project=tmp, env=SILENT_ENV)
            self.assertEqual("v1", silent["version"]["id"])
            fx = _wav(Path(tmp) / "brolls" / "sounds" / "held.wav", FX_HZ, 1)
            vo = _wav(Path(tmp) / "brolls" / "narration" / "private" / "audio" / "vo.wav", VO_HZ, 4)
            fx_digest = file_digest(fx)
            payload = _audio_payload(
                "sounds/held.wav",
                fx_digest,
                "narration/private/audio/vo.wav",
                file_digest(vo),
            )
            payload["effects"][0]["raw_redistribution"] = "restricted"
            payload["effects"][0]["conditions"] = (
                "SYNTHETIC TECHNICAL FIXTURE: rendered use allowed; raw transfer restricted."
            )
            audio_file = _write(Path(tmp) / "brolls" / "audio-held.json", json.dumps(payload))
            run_cli("graphics-audio", "--occurrence", "stat-01", "--file", str(audio_file), project=tmp)
            rendered = run_cli("graphics-render", "--occurrence", "stat-01", project=tmp, env=AUDIO_ENV)
            self.assertEqual("v2", rendered["version"]["id"])
            job = json.loads(
                (Path(tmp) / "brolls" / "graphics" / "numeric-stat" / "v2" / "job.json").read_text(encoding="utf-8")
            )
            _assert_effects_job(self, job)
            _approve(tmp, version="v2")
            run_cli("deliver", project=tmp)
            pkg = Path(tmp) / "entrega" / "graphics" / "numeric-stat" / "stat-01" / "v2"
            self._assert_held_package_and_rerender(pkg, fx, tmp)

    def _assert_held_package_and_rerender(self, pkg, fx, tmp):
        fx_digest = file_digest(fx)
        held = json.loads((pkg / "separately-held.json").read_text(encoding="utf-8"))
        held_item = next(item for item in held if item.get("ref") == "sounds/held.wav")
        self.assertEqual("restricted", held_item.get("raw_redistribution"))
        self.assertEqual("permitted", held_item.get("rendered_use"))
        self.assertTrue(str(held_item.get("frozen_ref") or "").startswith("public/audio/"))
        self.assertEqual([], _package_digest_hits(pkg, fx_digest))
        self.assertFalse((pkg / "narration").exists())
        listed = "\n".join(path.as_posix() for path in pkg.rglob("*"))
        self.assertNotIn("private", listed)
        frozen_audio = Path(tmp) / "brolls" / "graphics" / "numeric-stat" / "v2" / "public" / "audio"
        self.assertTrue(any(file_digest(path) == fx_digest for path in frozen_audio.glob("*")))
        self.assertTrue((Path(tmp) / "brolls" / "graphics" / "numeric-stat" / "v1" / "preview.mp4").is_file())
        self.assertTrue((pkg / "numeric-stat-stat-01-v2.mp4").is_file())
        cues = json.loads((pkg / "props.json").read_text(encoding="utf-8")).get("sound_cues") or []
        self.assertEqual(1, len(cues))
        self.assertEqual(0, cues[0]["start_frame"])
        self.assertEqual(1, cues[0]["gain"])
        self.assertTrue(str(cues[0]["src"]).startswith("audio/"))
        missing = _rerender_pkg(pkg, check=True)
        self.assertEqual(2, missing.returncode)
        missing_payload = json.loads(missing.stdout)
        self.assertFalse(missing_payload["ok"])
        self.assertIn("held-ref", json.dumps(missing_payload))
        ack = _rerender_pkg(pkg, ["--acknowledge-separately-held"], check=True)
        self.assertEqual(2, ack.returncode)
        self.assertIn("held-ref", ack.stdout)
        wrong = _wav(Path(tmp) / "wrong-held.wav", 440, 1)
        bad = _rerender_pkg(pkg, ["--held-ref", f"sounds/held.wav={wrong}"], check=True)
        self.assertEqual(2, bad.returncode)
        self.assertIn("sha256", bad.stdout)
        mapped = _rerender_pkg(pkg, ["--held-ref", f"sounds/held.wav={fx}"], check=True)
        mapped_payload = json.loads(mapped.stdout)
        self.assertEqual(0, mapped.returncode)
        self.assertTrue(mapped_payload["ok"])
        self.assertTrue(mapped_payload["held"][0]["supplied"])
        done = _rerender_pkg(
            pkg,
            ["--held-ref", f"sounds/held.wav={fx}", "--output", "held-out.mp4"],
        )
        self.assertEqual(0, done.returncode, done.stderr or done.stdout)
        output = pkg / "held-out.mp4"
        self.assertTrue(output.is_file())
        _assert_decoded_fx_without_vo(self, output, tmp)
        self.assertEqual([], _package_digest_hits(pkg, fx_digest))
        self.assertFalse((pkg / "public" / "audio" / Path(held_item["frozen_ref"]).name).is_file())

    def _deliver_shared_original_package(self, tmp, *, first_raw, second_raw):
        _project(tmp)
        _assign(tmp, timing="explicit", start="0", end="1.5")
        silent = run_cli("graphics-render", "--occurrence", "stat-01", project=tmp, env=SILENT_ENV)
        self.assertEqual("v1", silent["version"]["id"])
        fx = _wav(Path(tmp) / "brolls" / "sounds" / "held.wav", FX_HZ, 1)
        payload = _shared_original_effects(
            "sounds/held.wav",
            file_digest(fx),
            first_raw=first_raw,
            second_raw=second_raw,
        )
        audio_file = _write(Path(tmp) / "brolls" / "audio-shared.json", json.dumps(payload))
        run_cli("graphics-audio", "--occurrence", "stat-01", "--file", str(audio_file), project=tmp)
        rendered = run_cli("graphics-render", "--occurrence", "stat-01", project=tmp, env=AUDIO_ENV)
        self.assertEqual("v2", rendered["version"]["id"])
        _approve(tmp, version="v2")
        run_cli("deliver", project=tmp)
        pkg = Path(tmp) / "entrega" / "graphics" / "numeric-stat" / "stat-01" / "v2"
        return pkg, fx

    def _assert_shared_held_reconstructed(self, pkg, fx, tmp):
        fx_digest = file_digest(fx)
        held = json.loads((pkg / "separately-held.json").read_text(encoding="utf-8"))
        frozen = {item.get("frozen_ref") for item in held if isinstance(item, dict)}
        self.assertIn("public/audio/cue-1.wav", frozen)
        self.assertIn("public/audio/cue-2.wav", frozen)
        self.assertTrue(all(item.get("ref") == "sounds/held.wav" for item in held))
        self.assertTrue(all(item.get("raw_redistribution") == "restricted" for item in held))
        self.assertEqual([], _package_digest_hits(pkg, fx_digest))
        self.assertFalse((pkg / "public" / "audio" / "cue-1.wav").is_file())
        self.assertFalse((pkg / "public" / "audio" / "cue-2.wav").is_file())
        self.assertFalse((pkg / "refs" / "sounds" / "held.wav").is_file())
        cues = json.loads((pkg / "props.json").read_text(encoding="utf-8")).get("sound_cues") or []
        self.assertEqual(["cue-1", "cue-2"], [item.get("id") for item in cues])
        self.assertEqual("audio/cue-1.wav", cues[0]["src"])
        self.assertEqual("audio/cue-2.wav", cues[1]["src"])
        missing = _rerender_pkg(pkg, check=True)
        self.assertEqual(2, missing.returncode)
        self.assertIn("held-ref", missing.stdout)
        self.assertIn("missing cue dependency", missing.stdout)
        self.assertIn("cue-2", missing.stdout)
        ack = _rerender_pkg(pkg, ["--acknowledge-separately-held"], check=True)
        self.assertEqual(2, ack.returncode)
        self.assertIn("held-ref", ack.stdout)
        mapped = _rerender_pkg(pkg, ["--held-ref", f"sounds/held.wav={fx}"], check=True)
        mapped_payload = json.loads(mapped.stdout)
        self.assertEqual(0, mapped.returncode, mapped.stdout)
        self.assertTrue(mapped_payload["ok"])
        listed = []
        for item in mapped_payload.get("held") or []:
            listed.extend(item.get("frozen_cues") or [])
        self.assertIn("audio/cue-1.wav", listed)
        self.assertIn("audio/cue-2.wav", listed)
        self.assertEqual([], _package_digest_hits(pkg, fx_digest))
        done = _rerender_pkg(
            pkg,
            ["--held-ref", f"sounds/held.wav={fx}", "--output", "held-out.mp4"],
        )
        self.assertEqual(0, done.returncode, done.stderr or done.stdout)
        executed = json.loads((pkg / "executed-worker.json").read_text(encoding="utf-8"))
        consumed = "\n".join(executed.get("cues") or [])
        self.assertIn("cue-1.wav", consumed)
        self.assertIn("cue-2.wav", consumed)
        _assert_decoded_shared_cues(self, pkg / "held-out.mp4", tmp)
        self.assertEqual([], _package_digest_hits(pkg, fx_digest))
        self.assertFalse((pkg / "public" / "audio" / "cue-1.wav").is_file())
        self.assertFalse((pkg / "public" / "audio" / "cue-2.wav").is_file())

    def test_two_restricted_cues_sharing_held_original_reconstruct_both_destinations(self):
        with tempfile.TemporaryDirectory() as tmp:
            pkg, fx = self._deliver_shared_original_package(tmp, first_raw="restricted", second_raw="restricted")
            self._assert_shared_held_reconstructed(pkg, fx, tmp)

    def test_later_restricted_declaration_keeps_shared_original_held(self):
        with tempfile.TemporaryDirectory() as tmp:
            pkg, fx = self._deliver_shared_original_package(tmp, first_raw="permitted", second_raw="restricted")
            self._assert_shared_held_reconstructed(pkg, fx, tmp)

    def test_malicious_audio_file_and_viewing_does_not_download(self):
        with tempfile.TemporaryDirectory() as outer:
            outer_path = Path(outer)
            project = outer_path / "project"
            project.mkdir()
            _project(project)
            _assign(project)
            sentinel = outer_path / "external-sentinel.txt"
            sentinel.write_text("keep", encoding="utf-8")
            outside = outer_path / "foreign-audio.json"
            outside.write_text("{}", encoding="utf-8")
            denied = run_cli(
                "graphics-audio",
                "--occurrence",
                "stat-01",
                "--file",
                str(outside),
                project=project,
                expect=2,
            )
            self.assertIn("project", json.dumps(denied).lower())
            run_cli("status", project=project)
            run_cli("review", project=project)
            self.assertFalse((project / "brolls" / "sounds").exists())
            help_text = subprocess.run(
                [sys.executable, str(CLI), "graphics-sound-import", "--help"],
                capture_output=True,
                text=True,
                encoding="utf-8",
                check=False,
            )
            self.assertIn("viewing does not download", help_text.stdout.lower())
            self.assertEqual("keep", sentinel.read_text(encoding="utf-8"))
            self.assertTrue(outside.is_file())

    def test_storyboard_media_events_seek_and_version_switch(self):
        node = subprocess.run(["node", "--version"], capture_output=True, check=False)
        if node.returncode != 0:
            self.skipTest("node is required for the Storyboard audio fixture")
        done = subprocess.run(
            [
                "node",
                str(ROOT / "tests" / "fixtures" / "storyboard_audio.cjs"),
                str(ROOT / "assets" / "review.js"),
            ],
            capture_output=True,
            text=True,
            encoding="utf-8",
            check=False,
        )
        self.assertEqual(0, done.returncode, done.stderr or done.stdout)
        self.assertIn("ok", done.stdout)


class GraphicsLegacySourceSignatureTests(unittest.TestCase):
    def test_old_three_file_source_signature_stays_valid(self):
        source = {name: file_digest(TEMPLATE_DIR / name) for name in TEMPLATE_FILES}
        self.assertEqual(TEMPLATE_FILES, _source_template_names(source))
        self.assertEqual(3, len(source))
        self.assertNotIn("GraphicsAudio.jsx", source)
        four = dict(source)
        four["GraphicsAudio.jsx"] = "ab" * 32
        self.assertEqual(AUDIO_TEMPLATE_FILES, _source_template_names(four))


if __name__ == "__main__":
    unittest.main()
