"""Public timing and exact-still video workflow. Native media stays refused."""

import json
import math
import os
import subprocess
import sys
import tempfile
import threading
import unittest
import wave
from pathlib import Path
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import _isolation  # noqa: F401
from _media import skip_unless_ffmpeg
from _paths import CLI

from getbrolls import serve
from getbrolls.ai_grok import produce as native_produce
from getbrolls.graphics import default_profile, empty_graphics
from getbrolls.ledger import Ledger
from getbrolls.ledger import digest as file_digest
from getbrolls.narration import _payload_hash, analysis_config, input_fingerprint

PEER = Path(__file__).parent / "fixtures/ai_app_server.py"
SENTENCE = "A resource runs out."
# Success fixtures include process startup, durable ledger writes and media probing on Windows CI.
FIXTURE_TIMEOUT_S = "10"


def _write_wav(path, seconds, rate=16000, amplitude=0, frequency=0):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    frames = int(seconds * rate)
    sample = int(amplitude).to_bytes(2, "little", signed=True)
    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(rate)
        handle.writeframes(
            b"".join(
                int(amplitude * math.sin(2 * math.pi * frequency * i / rate)).to_bytes(2, "little", signed=True)
                for i in range(frames)
            )
            if frequency
            else sample * frames
        )
    return path


def _write_mp4(path, width, height, seconds, *, audio):
    command = [
        "ffmpeg",
        "-y",
        "-v",
        "error",
        "-f",
        "lavfi",
        "-i",
        f"color=c=black:s={width}x{height}:r=30:d={seconds}",
    ]
    if audio:
        command.extend(["-f", "lavfi", "-i", f"sine=frequency=440:duration={seconds}", "-shortest"])
    command.extend(["-c:v", "libx264", "-pix_fmt", "yuv420p"])
    if audio:
        command.extend(["-c:a", "aac"])
    command.append(str(path))
    subprocess.run(command, check=True, capture_output=True)


def _words(text, start_ms, end_ms):
    tokens = text.split()
    step = (end_ms - start_ms) // len(tokens)
    words = []
    for index, token in enumerate(tokens):
        start = start_ms + index * step
        end = end_ms if index == len(tokens) - 1 else start + step
        words.append({"word": token, "start_ms": start, "end_ms": end, "segment": 0})
    return words


@skip_unless_ffmpeg
class PublicTimingTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.project = Path(self.temp.name) / "project"
        self.env = {
            **os.environ,
            "GETBROLLS_CODEX_APP_SERVER": str(PEER),
            "GETBROLLS_AI_FIXTURE": "success",
            "GETBROLLS_AI_INLINE": "1",
            "GETBROLLS_AI_TIMEOUT": FIXTURE_TIMEOUT_S,
        }
        self.call("init-rules")
        plan = {
            "scenario": "A resource runs out. People wait. A reserve remains.",
            "style": "Restrained editorial illustration.",
            "beats": [
                {
                    "id": "scarcity",
                    "route": "ai",
                    "text": SENTENCE,
                    "purpose": "Explain scarcity.",
                    "alternatives": ["An empty reservoir", "A final drop", "An empty warehouse"],
                },
                {
                    "id": "reserve",
                    "route": "ai",
                    "text": "A reserve remains.",
                    "purpose": "Show what is left.",
                    "alternatives": ["A closed valve", "A marked crate", "A quiet gauge"],
                },
                {"id": "people", "route": "broll", "text": "People wait."},
            ],
        }
        path = Path(self.temp.name) / "plan.json"
        path.write_text(json.dumps(plan), encoding="utf-8")
        self.call("ai-plan", "--file", path)
        self.call("ai-select", "--beat", "scarcity", "--alternative", "option-2", "--comment", "No lettering")
        self.call("ai-generate-still", "--beat", "scarcity", "--request-id", "still-1", timeout=45)
        self.still = next(row for row in self.ai()["versions"].values() if row.get("kind") == "image")
        self.call("ai-approve", "--version", self.still["id"], "--decision", "approved", "--by", "Test editor")
        self.still_path = self.project / "brolls" / self.still["path"]
        self.still_bytes = self.still_path.read_bytes()
        self.assertTrue(self.still_bytes.startswith(b"\x89PNG"))

    def call(self, command, *args, ok=True, timeout=15):
        result = subprocess.run(
            [sys.executable, str(CLI), command, "--project", str(self.project), *map(str, args)],
            capture_output=True,
            text=True,
            encoding="utf-8",
            env=self.env,
            check=False,
            timeout=timeout,
        )
        self.assertEqual(0 if ok else 2, result.returncode, result.stderr or result.stdout)
        return json.loads(result.stdout if ok else result.stderr)

    def ai(self):
        return Ledger(self.project, recover=False).data["ai"]

    def previews(self):
        root = self.project / "brolls" / "previews"
        if not root.is_dir():
            return []
        return sorted(
            path.relative_to(self.project / "brolls").as_posix() for path in root.rglob("*") if path.is_file()
        )

    def plant(self, transcript, words, *, amplitude=0, frequency=0, seconds=9):
        root = self.project / "brolls"
        audio_rel = "narration/private/audio/rec-1.wav"
        result_rel = "narration/results/na-1.json"
        audio = _write_wav(root / audio_rel, seconds, amplitude=amplitude, frequency=frequency)
        payload = {"transcript": transcript, "words": words, "timing_resolved": True}
        artifact = root / result_rel
        artifact.parent.mkdir(parents=True, exist_ok=True)
        artifact.write_text(json.dumps(payload), encoding="utf-8")
        audio_sha = file_digest(audio)
        config = analysis_config(None)
        ledger = Ledger(self.project)
        ledger.data["narration"] = {
            "schema_version": 1,
            "current_analysis": "na-1",
            "recordings": {
                "rec-1": {
                    "id": "rec-1",
                    "sha256": audio_sha,
                    "bytes": audio.stat().st_size,
                    "duration_s": seconds,
                    "format": "wav",
                    "codec": "pcm_s16le",
                    "channels": 1,
                    "sample_rate": 16000,
                    "snapshot": audio_rel,
                }
            },
            "analyses": {
                "na-1": {
                    "id": "na-1",
                    "recording_id": "rec-1",
                    "state": "completed",
                    "submit_outcome": "accepted",
                    "audio_fingerprint": audio_sha,
                    "config": config,
                    "config_fingerprint": _payload_hash(config),
                    "input_fingerprint": input_fingerprint(audio_sha, config),
                    "error": None,
                    "result": {
                        **payload,
                        "artifact": result_rel,
                        "artifact_sha256": file_digest(artifact),
                        "usage": None,
                        "language": None,
                    },
                }
            },
        }
        ledger.save("test-narration")

    def start_server(self):
        self.call("review")
        server, _port = serve.start(self.project, port=0)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(thread.join, 2)
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        self.base = f"http://127.0.0.1:{server.server_address[1]}"
        token = server.save_token
        assert isinstance(token, str) and token
        self.token = token

    def http(self, path, data=None, *, token=True, timeout=30):
        headers = {"Content-Type": "application/json"}
        if token:
            headers[serve.TOKEN_HEADER] = self.token
        raw = json.dumps(data).encode() if data is not None else None
        request = Request(self.base + path, data=raw, headers=headers)
        try:
            with urlopen(request, timeout=timeout) as response:
                return response.status, response.read()
        except HTTPError as exc:
            with exc:
                return exc.code, exc.read()

    def test_timing_before_recording_preserves_the_approved_still(self):
        jobs = set(self.ai()["jobs"])
        failed = self.call("ai-timing", "--beat", "scarcity", "--analysis", "na-1", ok=False)
        self.assertIn("message", failed)
        self.assertEqual(jobs, set(self.ai()["jobs"]))
        self.assertIsNone(self.ai()["beats"]["scarcity"]["timing"])
        self.assertEqual(self.still_bytes, self.still_path.read_bytes())
        self.assertEqual("approved", self.ai()["versions"][self.still["id"]]["approval"]["state"])
        self.assertIsNone(self.ai()["beats"]["reserve"]["timing"])

    def test_unique_match_exposes_bounded_preview_and_status_does_not_extract(self):
        self.plant(SENTENCE, _words(SENTENCE, 0, 2000))
        before = self.previews()
        self.start_server()
        status, raw = self.http("/__ai/state")
        self.assertEqual(200, status, raw)
        self.assertNotIn(b"narration/private", raw)
        self.assertEqual(before, self.previews())
        select = self.http("/__ai", {"action": "select", "beat": "scarcity", "comment": "No lettering"})
        self.assertEqual(200, select[0], select[1])
        self.assertEqual(before, self.previews())
        matched = self.call("ai-timing", "--beat", "scarcity", "--analysis", "na-1", "--still", self.still["id"])
        self.assertTrue(matched["resolved"])
        self.assertEqual(self.still["id"], matched["still"])
        self.assertTrue(str(matched["preview"]).startswith("previews/ai-vo-scarcity-"))
        preview = self.project / "brolls" / matched["preview"]
        self.assertTrue(preview.read_bytes().startswith(b"RIFF"))
        served_status, served = self.http("/" + matched["preview"], token=False)
        self.assertEqual(200, served_status)
        self.assertEqual(preview.read_bytes(), served)
        uncommitted = preview.with_name("ai-vo-uncommitted.wav")
        uncommitted.write_bytes(served)
        self.assertEqual(404, self.http("/previews/ai-vo-uncommitted.wav", token=False)[0])
        self.assertNotIn("narration/private", preview.as_posix())
        held = self.previews()
        report = self.call("status")
        self.assertNotIn("narration/private", json.dumps(report))
        timing = next(row["timing"] for row in report["ai"]["beats"] if row["id"] == "scarcity")
        self.assertTrue(timing["resolved"])
        self.assertNotIn("preview", timing)
        self.assertEqual(held, self.previews())
        preview.unlink()
        self.call("status")
        self.assertFalse(preview.exists())
        state_status, state_raw = self.http("/__ai/state")
        self.assertEqual(200, state_status, state_raw)
        self.assertFalse(preview.exists())
        self.assertNotIn(b"narration/private", state_raw)
        denied, _body = self.http("/narration/private/audio/rec-1.wav", token=False)
        self.assertEqual(404, denied)
        self.assertEqual("approved", self.ai()["versions"][self.still["id"]]["approval"]["state"])
        self.assertEqual(self.still_bytes, self.still_path.read_bytes())

    def test_repeated_narration_stays_unresolved_until_an_explicit_candidate(self):
        words = _words(SENTENCE, 0, 2000) + _words(SENTENCE, 4000, 6000)
        self.plant(SENTENCE + " " + SENTENCE, words)
        prepared = self.call("ai-timing", "--beat", "scarcity", "--analysis", "na-1")
        self.assertFalse(prepared["resolved"])
        self.assertGreaterEqual(len(prepared["candidates"]), 2)
        self.assertIn("uncertain_match", prepared["reasons"])
        shown = prepared["candidates"]
        self.assertTrue(
            all(isinstance(row, dict) and isinstance(row.get("text"), str) and row["text"] for row in shown)
        )
        self.assertIn(SENTENCE, {row["text"] for row in shown})
        self.assertNotEqual(shown[0]["start_s"], shown[1]["start_s"])
        self.assertNotEqual(shown[0]["end_s"], shown[1]["end_s"])
        self.assertNotEqual(shown[0]["id"], shown[1]["id"])
        self.assertNotIn("narration/private", json.dumps(shown))
        rows = self.ai()["beats"]["scarcity"]["timing"]["match"]["candidates"]
        later = max(rows, key=lambda row: row["start_s"])
        earlier = min(rows, key=lambda row: row["start_s"])
        self.assertNotEqual(later["id"], earlier["id"])
        self.assertEqual(1, len(self.ai()["jobs"]))
        both = self.call(
            "ai-timing-resolve",
            "--beat",
            "scarcity",
            "--analysis",
            "na-1",
            "--by",
            "Test editor",
            "--statement",
            "Both clocks were supplied.",
            "--candidate",
            later["id"],
            "--start",
            "0",
            "--end",
            "1",
            ok=False,
        )
        self.assertIn("message", both)
        resolved = self.call(
            "ai-timing-resolve",
            "--beat",
            "scarcity",
            "--analysis",
            "na-1",
            "--by",
            "Test editor",
            "--statement",
            "Use the later spoken span.",
            "--candidate",
            later["id"],
        )
        self.assertTrue(resolved["resolved"])
        self.assertEqual(later["start_s"], resolved["start_s"])
        self.assertNotEqual(earlier["start_s"], resolved["start_s"])
        self.assertEqual(self.still_bytes, self.still_path.read_bytes())

    def test_changed_recording_and_profile_invalidate_only_video_readiness(self):
        self.plant(SENTENCE, _words(SENTENCE, 0, 2000))
        matched = self.call("ai-timing", "--beat", "scarcity", "--analysis", "na-1")
        self.assertTrue(matched["resolved"])
        ledger = Ledger(self.project)
        ledger.data["graphics"] = empty_graphics(default_profile(24, "confirmed"))
        ledger.save("test-profile")
        profile = self.call("status")
        timing = next(row["timing"] for row in profile["ai"]["beats"] if row["id"] == "scarcity")
        self.assertFalse(timing["resolved"])
        self.assertIn("stale_profile", timing["reasons"])
        self.assertEqual(self.still_bytes, self.still_path.read_bytes())
        self.assertIsNone(self.ai()["beats"]["reserve"]["timing"])
        ledger = Ledger(self.project)
        ledger.data.pop("graphics", None)
        ledger.save("test-profile-restored")
        restored = next(row["timing"] for row in self.call("status")["ai"]["beats"] if row["id"] == "scarcity")
        self.assertTrue(restored["resolved"])
        audio = _write_wav(self.project / "brolls/narration/private/audio/rec-1.wav", 9, amplitude=1200)
        ledger = Ledger(self.project)
        recording = ledger.data["narration"]["recordings"]["rec-1"]
        recording["sha256"] = file_digest(audio)
        recording["bytes"] = audio.stat().st_size
        ledger.save("test-recording")
        drifted = next(row["timing"] for row in self.call("status")["ai"]["beats"] if row["id"] == "scarcity")
        self.assertFalse(drifted["resolved"])
        self.assertIn("stale_recording", drifted["reasons"])
        self.assertEqual("approved", self.ai()["versions"][self.still["id"]]["approval"]["state"])
        self.assertEqual(self.still_bytes, self.still_path.read_bytes())
        self.assertEqual(1, len(self.ai()["jobs"]))

    def _video(self, nonce, **extra):
        args = [
            "ai-generate-video",
            "--beat",
            "scarcity",
            "--version",
            self.still["id"],
            "--request-id",
            nonce,
            "--model",
            extra.pop("model", "grok-video"),
        ]
        args.extend("--" + name for name in ("speech", "music", "atmosphere", "effects") if extra.pop(name, False))
        if "resolution" in extra:
            args.extend(["--resolution", extra.pop("resolution")])
        if "tool" in extra:
            args.extend(["--tool", extra.pop("tool")])
        return self.call(*args, ok=extra.pop("ok", True), timeout=extra.pop("timeout", 20))

    def test_native_refusal_keeps_duplicate_scope_and_still_guards(self):
        self.plant(SENTENCE, _words(SENTENCE, 0, 2000))
        self.call("ai-timing", "--beat", "scarcity", "--analysis", "na-1", "--still", self.still["id"])
        self.call(
            "ai-timing-resolve",
            "--beat",
            "scarcity",
            "--analysis",
            "na-1",
            "--by",
            "Test editor",
            "--statement",
            "Use the whole recorded span.",
            "--start",
            "0",
            "--end",
            "8",
        )
        launched = self._video("vid-1")
        job = self.ai()["jobs"][launched["job"]["id"]]
        self.assertEqual("failed", job["state"])
        self.assertEqual("unsupported", job["error"]["code"])
        self.assertIn("unverified", job["error"]["message"].lower())
        self.assertEqual("not_sent", job["submit_outcome"])
        self.assertEqual("grok-subscription", job["request"]["route"])
        self.assertEqual(6, job["request"]["requested_duration_s"])
        self.assertIn("Do not create a new starting image.", job["request"]["prompt"])
        self.assertIn("Do not add speech", job["request"]["prompt"])
        self.assertIn("Do not add music", job["request"]["prompt"])
        self.assertNotIn("Atmosphere may be included.", job["request"]["prompt"])
        self.assertFalse(any(row.get("kind") == "video" for row in self.ai()["versions"].values()))
        resumed = self.call("ai-resume", "--job", job["id"])
        self.assertFalse(resumed["resubmitted"])
        self.assertNotIn("worker", resumed)
        self.assertEqual("failed", self.ai()["jobs"][job["id"]]["state"])
        again = self._video("vid-1")
        self.assertEqual(job["id"], again["job"]["id"])
        self._video("vid-1", model="other-model", ok=False)
        spoken = self._video("vid-speech", speech=True, music=True, atmosphere=True, effects=True)
        prompt = self.ai()["jobs"][spoken["job"]["id"]]["request"]["prompt"]
        self.assertIn("Speech was explicitly requested.", prompt)
        self.assertIn("Music was explicitly requested.", prompt)
        self.assertIn("Atmosphere may be included.", prompt)
        self.assertIn("Effects may be included.", prompt)
        self.call(
            "ai-timing-resolve",
            "--beat",
            "scarcity",
            "--analysis",
            "na-1",
            "--by",
            "Test editor",
            "--statement",
            "Shorten the recorded span.",
            "--start",
            "1",
            "--end",
            "8",
        )
        before = set(self.ai()["jobs"])
        self._video("vid-1", ok=False)
        self.assertEqual(before, set(self.ai()["jobs"]))
        self.still_path.write_bytes(self.still_bytes + b"\x00")
        self._video("vid-changed", ok=False)
        self.assertEqual(before, set(self.ai()["jobs"]))
        self.assertEqual("approved", self.ai()["versions"][self.still["id"]]["approval"]["state"])

    def start_inline(self, produce):
        self.start_server()
        self.inline = patch.dict(os.environ, {"GETBROLLS_AI_INLINE": "1"})
        self.producer = patch("getbrolls.ai_grok.produce", produce)
        self.inline.start()
        self.producer.start()
        self.addCleanup(self.producer.stop)
        self.addCleanup(self.inline.stop)

    def video_body(self, nonce, **extra):
        body = {
            "action": "video",
            "beat": "scarcity",
            "version": self.still["id"],
            "requestId": nonce,
            "model": "grok-video",
            "tool": "reference_to_video",
            "resolution": "480p",
            "speech": False,
            "music": False,
            "atmosphere": False,
            "effects": False,
        }
        body.update(extra)
        return body

    def test_invalid_video_artifacts_do_not_publish_a_clip(self):
        self.plant(SENTENCE, _words(SENTENCE, 0, 2000))
        self.call("ai-timing", "--beat", "scarcity", "--analysis", "na-1")
        self.call(
            "ai-timing-resolve",
            "--beat",
            "scarcity",
            "--analysis",
            "na-1",
            "--by",
            "Test editor",
            "--statement",
            "Use the whole recorded span.",
            "--start",
            "0",
            "--end",
            "8",
        )

        def produce(project, job, workdir, *, timeout, on_submitted):
            del project, timeout
            work = Path(workdir)
            mode = job["request"]["model"]
            remote = {"tool": job["request"]["tool"], "model": mode, "sessionId": "synthetic-session"}
            on_submitted(remote)
            if mode == "missing":
                return {"status": "complete", "path": str(work / "missing.mp4"), "remote": remote}
            if mode == "escape":
                return {"status": "complete", "path": str(self.still_path), "remote": remote}
            dest = work / "bad.mp4"
            dest.write_text("not a video", encoding="utf-8")
            return {"status": "complete", "path": str(dest), "remote": remote}

        self.start_inline(produce)
        for nonce, model in (("bad-missing", "missing"), ("bad-escape", "escape"), ("bad-bytes", "garbage")):
            status, raw = self.http("/__ai", self.video_body(nonce, model=model))
            self.assertEqual(200, status, raw)
            self.assertEqual("failed", json.loads(raw)["job"]["state"])
        self.assertFalse(any(row.get("kind") == "video" for row in self.ai()["versions"].values()))
        clips = self.project / "brolls" / "clips"
        found = list(clips.glob("ai-*.mp4")) if clips.is_dir() else []
        self.assertEqual([], found)
        self.assertEqual(self.still_bytes, self.still_path.read_bytes())

    def _resolve_full_span(self):
        self.plant(SENTENCE, _words(SENTENCE, 0, 2000))
        self.call("ai-timing", "--beat", "scarcity", "--analysis", "na-1", "--still", self.still["id"])
        self.call(
            "ai-timing-resolve",
            "--beat",
            "scarcity",
            "--analysis",
            "na-1",
            "--by",
            "Test editor",
            "--statement",
            "Use the whole recorded span.",
            "--start",
            "0",
            "--end",
            "8",
        )

    def _clip_producer(self, calls):
        def produce(project, job, workdir, *, timeout, on_submitted):
            del project, timeout
            calls.append(job["id"])
            resolution = job["request"]["resolution"]
            if job["request"]["model"] == "unknown-model":
                on_submitted(
                    {"tool": job["request"]["tool"], "model": "unknown-model", "sessionId": "synthetic-session"}
                )
                return {"status": "unknown", "error": "transport closed", "code": "unknown"}
            width, height, audio = (1280, 720, False) if resolution == "720p" else (854, 480, True)
            dest = Path(workdir) / "clip.mp4"
            _write_mp4(dest, width, height, 2, audio=audio)
            remote = {
                "tool": job["request"]["tool"],
                "model": job["request"]["model"],
                "sessionId": "synthetic-session",
            }
            on_submitted(remote)
            return {"status": "complete", "path": str(dest), "remote": remote}

        return produce

    def _assert_480_measurements(self, stored):
        self.assertEqual(854, stored["width"])
        self.assertEqual(480, stored["height"])
        self.assertFalse(stored["native_full_hd"])
        self.assertEqual("short", stored["coverage"])
        self.assertTrue(stored["audio"])
        self.assertGreater(stored["fps"], 0)
        self.assertLess(stored["duration_s"], 8)
        self.assertEqual("480p", stored["resolution"])
        self.assertEqual(self.still["id"], stored["still"]["id"])
        self.assertEqual("pending", stored["approval"]["state"])
        self.assertEqual("approved", self.ai()["versions"][self.still["id"]]["approval"]["state"])

    def _reject_clip_only(self, stored):
        from getbrolls.ai_state import version_signature

        signature = version_signature(self.ai()["versions"][stored["id"]])
        self.call(
            "ai-approve",
            "--version",
            stored["id"],
            "--decision",
            "rejected",
            "--by",
            "Test editor",
            "--signature",
            signature,
        )
        self.assertEqual("rejected", self.ai()["versions"][stored["id"]]["approval"]["state"])
        self.assertEqual("approved", self.ai()["versions"][self.still["id"]]["approval"]["state"])

    def _assert_other_video_jobs(self, calls, first):
        duplicate_status, duplicate_raw = self.http("/__ai", self.video_body("clip-480"))
        self.assertEqual(200, duplicate_status, duplicate_raw)
        self.assertEqual(first["id"], json.loads(duplicate_raw)["job"]["id"])
        self.assertEqual(1, len(calls))
        second_status, second_raw = self.http("/__ai", self.video_body("clip-720", resolution="720p"))
        self.assertEqual(200, second_status, second_raw)
        second = self.ai()["versions"][json.loads(second_raw)["job"]["result"]]
        self.assertEqual(1280, second["width"])
        self.assertEqual(720, second["height"])
        self.assertFalse(second["audio"])
        self.assertFalse(second["native_full_hd"])
        self.assertEqual("short", second["coverage"])
        unknown_status, unknown_raw = self.http("/__ai", self.video_body("clip-unknown", model="unknown-model"))
        self.assertEqual(200, unknown_status, unknown_raw)
        unknown = json.loads(unknown_raw)["job"]
        self.assertEqual("unknown", unknown["state"])
        calls_after = len(calls)
        self.producer.stop()
        resumed = self.call("ai-resume", "--job", unknown["id"])
        self.assertEqual("unknown", resumed["job"]["state"])
        self.assertFalse(resumed["resubmitted"])
        self.assertEqual(calls_after, len(calls))

    def _assert_moved_interval_and_page(self, stored, kept):
        self.call(
            "ai-timing-resolve",
            "--beat",
            "scarcity",
            "--analysis",
            "na-1",
            "--by",
            "Test editor",
            "--statement",
            "Move the recorded span.",
            "--start",
            "1",
            "--end",
            "8",
        )
        refused, refused_raw = self.http("/__ai", self.video_body("clip-480"))
        self.assertEqual(400, refused, refused_raw)
        self.assertTrue(kept.is_file())
        self.call("ai-approve", "--version", self.still["id"], "--decision", "changes", "--by", "Test editor")
        self.assertEqual("changes", self.ai()["versions"][self.still["id"]]["approval"]["state"])
        self.assertEqual("rejected", self.ai()["versions"][stored["id"]]["approval"]["state"])
        self.call("review")
        page = (self.project / "brolls/review.html").read_text(encoding="utf-8")
        self.assertIn("Timing does not generate media.", page)
        self.assertIn("Generate video", page)
        self.assertIn("Approve this still", page)
        self.assertIn("Approve this video", page)
        self.assertIn("data-ai-video-comment", page)
        self.assertIn("data-ai-video-decision-label", page)
        self.assertIn("data-ai-video-setup", page)
        self.assertIn("capability unverified", page)
        self.assertIn("not native Full HD", page)
        self.assertNotIn("narration/private", page)
        self.assertTrue(kept.is_file())

    def test_synthetic_clip_keeps_native_measurements_and_separate_review(self):
        self._resolve_full_span()
        calls = []
        self.start_inline(self._clip_producer(calls))
        first_status, first_raw = self.http("/__ai", self.video_body("clip-480"))
        self.assertEqual(200, first_status, first_raw)
        first = json.loads(first_raw)["job"]
        self.assertEqual("complete", first["state"])
        stored = self.ai()["versions"][first["result"]]
        self._assert_480_measurements(stored)
        self._reject_clip_only(stored)
        kept = self.project / "brolls" / stored["path"]
        self.assertTrue(kept.is_file())
        self._assert_other_video_jobs(calls, first)
        self._assert_moved_interval_and_page(stored, kept)

    def _matched_preview(self):
        self.plant(SENTENCE, _words(SENTENCE, 0, 2000))
        matched = self.call("ai-timing", "--beat", "scarcity", "--analysis", "na-1", "--still", self.still["id"])
        self.assertTrue(matched["resolved"])
        self.assertTrue(str(matched["preview"]).startswith("previews/ai-vo-scarcity-"))
        self.assertIsNone(matched["preview_error"])
        return matched

    def _preview_file(self, matched):
        path = self.project / "brolls" / matched["preview"]
        original = path.read_bytes()
        self.assertTrue(original.startswith(b"RIFF"))
        self.assertNotIn("narration/private", path.as_posix())
        return path, original

    def _assert_preview_reuse(self, matched, path, original):
        reused = self.call("ai-timing", "--beat", "scarcity", "--analysis", "na-1", "--still", self.still["id"])
        self.assertEqual(matched["preview"], reused["preview"])
        self.assertIsNone(reused["preview_error"])
        self.assertEqual(original, path.read_bytes())

    def _assert_view_keeps_bytes(self, path, payload):
        status, raw = self.http("/__ai/state")
        self.assertEqual(200, status, raw)
        self.assertNotIn(b"narration/private", raw)
        body = json.loads(raw)
        timing = next(row["timing"] for row in body["beats"] if row["id"] == "scarcity")
        self.assertIsNone(timing["preview"])
        self.assertTrue(timing["preview_error"])
        self.assertEqual(payload, path.read_bytes())
        report = self.call("status")
        status_timing = next(row["timing"] for row in report["ai"]["beats"] if row["id"] == "scarcity")
        self.assertNotIn("preview", status_timing)
        self.assertEqual(payload, path.read_bytes())

    def _assert_prepare_keeps_bytes(self, path, payload):
        refused = self.call("ai-timing", "--beat", "scarcity", "--analysis", "na-1", "--still", self.still["id"])
        self.assertIsNone(refused["preview"])
        self.assertIn("existing file was kept", refused["preview_error"])
        self.assertNotIn("narration/private", json.dumps(refused))
        self.assertEqual(payload, path.read_bytes())

    def _remove_link_node(self, path):
        path = Path(path)
        if path.is_symlink():
            path.unlink()
            return
        try:
            if path.is_dir():
                path.rmdir()
        except OSError:
            return

    def _plant_link(self, path, target, *, directory, preserved):
        path = Path(path)
        if path.is_symlink() or (path.exists() and not path.is_dir()):
            path.unlink()
        elif path.is_dir():
            return False
        linked = False
        try:
            path.symlink_to(target, target_is_directory=directory)
            linked = path.is_symlink() or path.exists()
        except OSError:
            linked = False
        if not linked and os.name == "nt":
            command = ["cmd", "/c", "mklink"]
            if directory:
                command.append("/J")
            command.extend([str(path), str(target)])
            done = subprocess.run(command, capture_output=True, text=True, encoding="utf-8", check=False)
            linked = done.returncode == 0 and (path.exists() or path.is_symlink())
        if not linked:
            if not path.exists():
                path.write_bytes(preserved)
            return False
        self.addCleanup(self._remove_link_node, path)
        return True

    def _assert_preview_link(self, path, preserved, *, directory):
        if directory:
            target = self.project / "brolls" / "previews" / "junction-target"
            target.mkdir(parents=True, exist_ok=True)
            before = sorted(item.name for item in target.iterdir())
        else:
            target = self.project / "brolls/narration/private/audio/rec-1.wav"
            before = target.read_bytes()
        if not self._plant_link(path, target, directory=directory, preserved=preserved):
            self.assertEqual(preserved, path.read_bytes())
            return
        refused = self.call("ai-timing", "--beat", "scarcity", "--analysis", "na-1", "--still", self.still["id"])
        self.assertIsNone(refused["preview"])
        self.assertIn("link", refused["preview_error"].lower())
        self.assertNotIn("narration/private", json.dumps(refused))
        after = sorted(item.name for item in target.iterdir()) if directory else target.read_bytes()
        self.assertEqual(before, after)
        self._remove_link_node(path)
        path.write_bytes(preserved)

    def _assert_stale_interval_keeps_bytes(self, path, preserved, previous):
        moved = self.call(
            "ai-timing-resolve",
            "--beat",
            "scarcity",
            "--analysis",
            "na-1",
            "--by",
            "Test editor",
            "--statement",
            "Move the recorded span.",
            "--start",
            "1",
            "--end",
            "8",
        )
        self.assertNotEqual(previous, moved.get("preview"))
        self.assertTrue(str(moved.get("preview") or "").startswith("previews/ai-vo-scarcity-"))
        self.assertNotIn("narration/private", json.dumps(moved))
        self.assertEqual(preserved, path.read_bytes())
        fresh = self.project / "brolls" / moved["preview"]
        self.assertTrue(fresh.read_bytes().startswith(b"RIFF"))
        self.assertEqual(self.still_bytes, self.still_path.read_bytes())

    def test_cached_preview_keeps_occupied_bytes_and_reuses_a_matching_excerpt(self):
        matched = self._matched_preview()
        path, original = self._preview_file(matched)
        self._assert_preview_reuse(matched, path, original)
        junk = b"not-audio-preview"
        path.write_bytes(junk)
        self.start_server()
        self._assert_view_keeps_bytes(path, junk)
        self._assert_prepare_keeps_bytes(path, junk)
        altered = _write_wav(Path(self.temp.name) / "altered.wav", 1, amplitude=1400).read_bytes()
        path.write_bytes(altered)
        self._assert_prepare_keeps_bytes(path, altered)
        self._assert_preview_link(path, altered, directory=False)
        self._assert_preview_link(path, altered, directory=True)
        self._assert_stale_interval_keeps_bytes(path, altered, matched["preview"])

    def test_recorded_setup_launches_without_a_typed_model_and_stays_unverified(self):
        self._resolve_full_span()
        self.start_inline(native_produce)
        before = set(self.ai()["jobs"])
        missing = self.video_body("setup-missing")
        missing.pop("model")
        missing.pop("tool")
        status, raw = self.http("/__ai", missing)
        self.assertEqual(400, status, raw)
        self.assertIn("guess", raw.decode("utf-8").lower())
        self.assertEqual(before, set(self.ai()["jobs"]))
        ledger = Ledger(self.project)
        ledger.data["ai"]["native_video"] = {
            "route": "grok-subscription",
            "model": "grok-video",
            "tool": "reference_to_video",
            "capability": "unverified",
        }
        ledger.save("test-native-setup")
        launched = self.video_body("setup-video")
        launched.pop("model")
        launched.pop("tool")
        status, raw = self.http("/__ai", launched)
        self.assertEqual(200, status, raw)
        job = self.ai()["jobs"][json.loads(raw)["job"]["id"]]
        self.assertEqual("failed", job["state"])
        self.assertEqual("unsupported", job["error"]["code"])
        self.assertIn("unverified", job["error"]["message"].lower())
        self.assertEqual("not_sent", job["submit_outcome"])
        self.assertEqual("grok-video", job["request"]["model"])
        self.assertEqual("reference_to_video", job["request"]["tool"])
        self.assertEqual("grok-subscription", job["request"]["route"])
        self.assertEqual("unverified", self.ai()["native_video"]["capability"])
        self.assertFalse(any(row.get("kind") == "video" for row in self.ai()["versions"].values()))
