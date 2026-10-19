"""Storyboard sequence actions retain bounded ordered media and exact review."""

import json
import math
import re
import struct
import subprocess
import unittest
from pathlib import Path

import _isolation  # noqa: F401
import test_ai_grok_public as grok_helpers
import test_ai_openrouter_public as paid_helpers
from _media import skip_unless_ffmpeg
from test_ai_timing_public import SENTENCE, _words


@skip_unless_ffmpeg
class SequencePublicTests(unittest.TestCase):
    def setUp(self):
        self.media = grok_helpers.GrokPublicTests()
        self.addCleanup(self.media.doCleanups)
        self.media.setUp()
        self.media.approve_and_time()

    def prepare(self, **extra):
        status, raw = self.media.http(
            "/__ai",
            {
                "action": "prepare-sequence",
                "beat": "scarcity",
                "version": self.media.still["id"],
                "route": "grok-subscription",
                "requestId": "sequence-1",
                "clip_duration_s": 6,
                **extra,
            },
        )
        self.assertEqual(200, status, raw)
        return json.loads(raw)["sequence"]

    def clip(self, color, seconds, *, audio=False):
        path = Path(self.media.temp.name) / (color + ".mp4")
        args = ["ffmpeg", "-v", "error", "-f", "lavfi", "-i", f"color=c={color}:s=160x90:r=30:d={seconds}"]
        if audio:
            args += ["-f", "lavfi", "-i", f"sine=frequency=660:duration={seconds}"]
        subprocess.run([*args, "-c:v", "libx264", "-pix_fmt", "yuv420p", str(path)], check=True, capture_output=True)
        return path.read_bytes()

    def rms(self, path, start):
        data = subprocess.run(
            [
                "ffmpeg",
                "-v",
                "error",
                "-i",
                str(path),
                "-ss",
                str(start),
                "-t",
                "0.5",
                "-map",
                "0:a:0",
                "-ac",
                "1",
                "-f",
                "f32le",
                "pipe:1",
            ],
            check=True,
            capture_output=True,
        ).stdout
        values = struct.unpack("<" + "f" * (len(data) // 4), data)
        return math.sqrt(sum(v * v for v in values) / len(values))

    def test_short_outputs_remain_incomplete_and_originals_survive_without_hidden_fill(self):
        sequence = self.prepare()
        media = self.media
        short = self.clip("magenta", 1)
        media.responses = [
            {"request_id": "short-1"},
            {"status": "done", "video": {"url": "https://media.example.com/1.mp4"}},
            short,
            {"request_id": "short-2"},
            {"status": "done", "video": {"url": "https://media.example.com/2.mp4"}},
            short,
        ]
        self.assertEqual(
            200,
            media.http(
                "/__ai", {"action": "launch-sequence", "sequence": sequence["id"], "signature": sequence["signature"]}
            )[0],
        )
        before = len(media.requests)
        result = json.loads(media.http("/__ai/state")[1])["beats"][0]["sequence"]
        self.assertEqual("incomplete", result["state"], result)
        self.assertIn("coverage_shortfall", result["reasons"])
        self.assertIsNone(result["version"])
        self.assertFalse(result["ready"])
        self.assertEqual(["complete", "complete"], [clip["job"]["state"] for clip in result["clips"]])
        for clip in result["clips"]:
            version = media.ai()["versions"][clip["job"]["result"]]
            self.assertEqual(short, (media.project / "brolls" / version["path"]).read_bytes())
        self.assertEqual(before, len(media.requests))

    def test_two_actual_clips_cover_the_interval_with_separate_narration_and_exact_sequence_review(self):
        media = self.media
        media.plant(SENTENCE, _words(SENTENCE, 0, 2000), amplitude=5000, frequency=220)
        media.call("ai-timing", "--beat", "scarcity", "--analysis", "na-1", "--still", media.still["id"])
        media.call(
            "ai-timing-resolve",
            "--beat",
            "scarcity",
            "--analysis",
            "na-1",
            "--by",
            "Editor",
            "--statement",
            "Use this fixture span",
            "--start",
            "0",
            "--end",
            "8",
        )
        sequence = self.prepare()
        media.responses = [
            {"request_id": "red-clip"},
            {"status": "done", "video": {"url": "https://media.example.com/red.mp4"}},
            self.clip("red", 6),
            {"request_id": "blue-clip"},
            {"status": "done", "video": {"url": "https://media.example.com/blue.mp4"}},
            self.clip("blue", 3, audio=True),
        ]
        launch = {"action": "launch-sequence", "sequence": sequence["id"], "signature": sequence["signature"]}
        status, raw = media.http("/__ai", launch)
        self.assertEqual(200, status, raw)
        board = json.loads(media.http("/__ai/state")[1])
        result = board["beats"][0]["sequence"]
        self.assertEqual("complete", result["state"], result)
        version = result["version"]
        self.assertEqual("pending", version["approval"])
        self.assertEqual(240, version["frames"])
        self.assertEqual("covered", version["coverage"])
        self.assertFalse(version["native_full_hd"])
        self.assertIn("profile_shortfall", result["reasons"])
        movie = media.project / "brolls" / version["path"]
        preview = media.project / "brolls" / version["preview"]["path"]
        self.assertLess(self.rms(movie, 0.5), 0.001, "Production must not contain the separate narration")
        self.assertGreater(self.rms(movie, 6.5), 0.01, "Retain scene sound of the second original")
        self.assertGreater(self.rms(preview, 0.5), 0.01, "Preview must include corresponding narration")
        for at, channel in ((1, 0), (6.5, 2)):
            rgb = subprocess.run(
                [
                    "ffmpeg",
                    "-v",
                    "error",
                    "-ss",
                    str(at),
                    "-i",
                    str(movie),
                    "-frames:v",
                    "1",
                    "-vf",
                    "scale=1:1",
                    "-f",
                    "rawvideo",
                    "-pix_fmt",
                    "rgb24",
                    "pipe:1",
                ],
                check=True,
                capture_output=True,
            ).stdout
            self.assertGreater(rgb[channel], 180, "Retain the planned red then blue ordering")
        count = len(media.requests)
        self.assertEqual(200, media.http("/__ai", launch)[0])
        self.assertEqual(count, len(media.requests), "Repeated launch must not repeat provider generation")
        review = {
            "action": "review",
            "version": version["id"],
            "signature": version["signature"],
            "by": "Editor",
            "decision": "approved",
        }
        self.assertEqual(200, media.http("/__ai", review)[0])
        self.assertEqual(
            "approved", json.loads(media.http("/__ai/state")[1])["beats"][0]["sequence"]["version"]["approval"]
        )

    def test_preparation_plans_two_ordered_clips_without_generating_or_approving(self):
        media = self.media
        before = len(media.requests)
        payload = {
            "action": "prepare-sequence",
            "beat": "scarcity",
            "version": media.still["id"],
            "route": "grok-subscription",
            "requestId": "sequence-1",
            "clip_duration_s": 6,
        }
        status, raw = media.http("/__ai", payload)
        self.assertEqual(200, status, raw)
        sequence = json.loads(raw)["sequence"]
        self.assertEqual("planned", sequence["state"])
        self.assertEqual(240, sequence["frames"])
        self.assertEqual([(0, 180), (180, 240)], [(c["start_frame"], c["end_frame"]) for c in sequence["clips"]])
        self.assertEqual([media.still["id"], media.still["id"]], [c["still"]["id"] for c in sequence["clips"]])
        self.assertEqual(before, len(media.requests), "Preparing and viewing a native plan must not generate")
        again = json.loads(media.http("/__ai", payload)[1])["sequence"]
        self.assertEqual(sequence["id"], again["id"])
        board = json.loads(media.http("/__ai/state")[1])
        self.assertEqual(sequence["id"], board["beats"][0]["sequence"]["id"])
        self.assertIsNone(board["beats"][0]["sequence"]["version"])

    def test_long_interval_and_malformed_scope_are_refused_before_any_generation(self):
        media = self.media
        media.plant(SENTENCE, _words(SENTENCE, 0, 2000), seconds=40)
        media.call("ai-timing", "--beat", "scarcity", "--analysis", "na-1", "--still", media.still["id"])
        media.call(
            "ai-timing-resolve",
            "--beat",
            "scarcity",
            "--analysis",
            "na-1",
            "--by",
            "Editor",
            "--statement",
            "Long fixture",
            "--start",
            "0",
            "--end",
            "40",
        )
        before = len(media.requests)
        payload = {
            "action": "prepare-sequence",
            "beat": "scarcity",
            "version": media.still["id"],
            "requestId": "bounded",
            "clip_duration_s": 1,
        }
        self.assertEqual(400, media.http("/__ai", payload)[0])
        for changes in (
            {"clip_duration_s": True},
            {"clip_duration_s": 16},
            {"route": []},
            {"version": []},
            {"beat": []},
        ):
            self.assertEqual(400, media.http("/__ai", {**payload, **changes})[0], changes)
        self.assertEqual(before, len(media.requests))
        self.assertFalse(media.ai().get("sequences"))

    def test_fractional_profile_offline_sequence_review_and_changed_recording(self):
        from getbrolls.graphics import default_profile, empty_graphics
        from getbrolls.ledger import Ledger

        media = self.media
        ledger = Ledger(media.project)
        ledger.data["graphics"] = empty_graphics(default_profile(29.97, "confirmed"))
        ledger.save("test-fractional-profile")
        media.call("ai-timing", "--beat", "scarcity", "--analysis", "na-1", "--still", media.still["id"])
        media.call(
            "ai-timing-resolve",
            "--beat",
            "scarcity",
            "--analysis",
            "na-1",
            "--by",
            "Editor",
            "--statement",
            "Fractional fixture",
            "--start",
            "0.5",
            "--end",
            "8.5",
        )
        sequence = self.prepare()
        media.responses = [
            {"request_id": "fractional-1"},
            {"status": "done", "video": {"url": "https://media.example.com/1.mp4"}},
            self.clip("cyan", 6),
            {"request_id": "fractional-2"},
            {"status": "done", "video": {"url": "https://media.example.com/2.mp4"}},
            self.clip("orange", 3),
        ]
        self.assertEqual(
            200,
            media.http(
                "/__ai", {"action": "launch-sequence", "sequence": sequence["id"], "signature": sequence["signature"]}
            )[0],
        )
        result = json.loads(media.http("/__ai/state")[1])["beats"][0]["sequence"]
        self.assertEqual("complete", result["state"], result)
        self.assertEqual(240, result["version"]["frames"])
        media.call("review")
        page = (media.project / "brolls/review.html").read_text(encoding="utf-8")
        match = re.search(r"window.GETBROLLS_REVIEW=(.*?);</script>", page)
        assert match is not None
        exported = json.loads(match.group(1))
        row = next(row for row in exported["ai"] if row["version"] == result["version"]["id"])
        self.assertEqual(result["id"], row["sequence"]["id"])
        row.update(state="approved", decision="approved", comment="Offline sequence acceptance")
        path = Path(media.temp.name) / "offline.json"
        path.write_text(json.dumps(exported), encoding="utf-8")
        self.assertEqual(1, media.call("import-review", "--file", path, "--by", "Editor")["ai_imported"])
        self.assertEqual("approved", media.ai()["versions"][row["version"]]["approval"]["state"])
        before = len(media.requests)
        media.plant(SENTENCE, _words(SENTENCE, 0, 2000), amplitude=1500)
        stale = json.loads(media.http("/__ai/state")[1])["beats"][0]["sequence"]
        self.assertEqual("stale", stale["state"])
        self.assertFalse(stale["ready"])
        self.assertEqual("approved", stale["version"]["approval"], "Preserve the historical explicit decision")
        self.assertEqual(
            400,
            media.http(
                "/__ai",
                {
                    "action": "review",
                    "version": row["version"],
                    "signature": row["signature"],
                    "decision": "approved",
                    "by": "Editor",
                },
            )[0],
        )
        self.assertEqual(before, len(media.requests))

    def test_paid_sequence_confirms_all_clips_once_and_recovers_retained_handle(self):
        media = paid_helpers.OpenRouterPublicTests()
        self.addCleanup(media.doCleanups)
        media.setUp()
        media.ready_video()
        media.call(
            "ai-timing-resolve",
            "--beat",
            "scarcity",
            "--analysis",
            "na-1",
            "--by",
            "Editor",
            "--statement",
            "Fixture span",
            "--start",
            "0",
            "--end",
            "8",
        )
        media.responses = [paid_helpers.video_capabilities()]
        payload = {
            "action": "prepare-sequence",
            "route": "openrouter",
            "beat": "scarcity",
            "version": media.still["id"],
            "requestId": "paid-sequence",
        }
        status, raw = media.http("/__ai", payload)
        self.assertEqual(200, status, raw)
        sequence = json.loads(raw)["sequence"]
        jobs = [clip["job"] for clip in sequence["clips"]]
        self.assertEqual(2, len(jobs))
        self.assertTrue(all(job["state"] == "awaiting_confirmation" for job in jobs))
        self.assertEqual(400, media.http("/__ai", media.confirmation(jobs[:1]))[0])
        self.assertEqual(
            400,
            media.http(
                "/__ai", {"action": "launch-sequence", "sequence": sequence["id"], "signature": sequence["signature"]}
            )[0],
        )
        before = len(media.requests)
        self.assertEqual(200, media.http("/__ai", payload)[0])
        self.assertEqual(before, len(media.requests))
        from urllib.error import URLError

        media.responses = [
            {"id": "paid-red", "status": "pending"},
            {"id": "paid-red", "status": "completed", "urls": ["https://media.example.com/red.mp4"]},
            self.clip("green", 6),
            {"id": "paid-blue", "status": "pending"},
            {"id": "paid-blue", "status": "completed", "urls": ["https://media.example.com/blue.mp4"]},
            URLError("interrupted download"),
        ]
        media.confirm(jobs)
        result = json.loads(media.http("/__ai/state")[1])["beats"][0]["sequence"]
        self.assertEqual("partial", result["state"], result)
        self.assertIsNone(result["version"])
        post_count = sum(req.get_method() == "POST" for req in media.requests)
        media.server_restart()
        media.confirm(jobs)
        self.assertEqual(post_count, sum(req.get_method() == "POST" for req in media.requests))
        media.responses = [
            {"id": "paid-blue", "status": "completed", "urls": ["https://media.example.com/blue.mp4"]},
            self.clip("yellow", 3),
        ]
        self.assertEqual(200, media.http("/__ai", {"action": "resume", "job": jobs[1]["id"]})[0])
        result = json.loads(media.http("/__ai/state")[1])["beats"][0]["sequence"]
        self.assertEqual("complete", result["state"], result)
        self.assertEqual(240, result["version"]["frames"])
        self.assertEqual(post_count, sum(req.get_method() == "POST" for req in media.requests))

    def test_different_approved_first_frames_are_frozen_in_order_and_revocation_blocks_launch(self):
        from getbrolls.ai_state import version_signature

        media = self.media
        first = media.still
        _, job = media.launch_still("second-still")
        second = media.ai()["versions"][job["result"]]
        media.still = first
        payload = {
            "action": "prepare-sequence",
            "beat": "scarcity",
            "version": media.still["id"],
            "requestId": "ordered-frames",
            "clip_duration_s": 6,
            "stills": [media.still["id"], second["id"]],
        }
        self.assertEqual(400, media.http("/__ai", payload)[0], "An unseen second still must not be animated")
        self.assertEqual(
            200,
            media.http(
                "/__ai",
                {
                    "action": "review",
                    "version": second["id"],
                    "signature": version_signature(second),
                    "by": "Editor",
                    "decision": "approved",
                },
            )[0],
        )
        status, raw = media.http("/__ai", payload)
        self.assertEqual(200, status, raw)
        sequence = json.loads(raw)["sequence"]
        self.assertEqual([media.still["id"], second["id"]], [clip["still"]["id"] for clip in sequence["clips"]])
        self.assertEqual(
            400,
            media.http("/__ai", {**payload, "stills": [second["id"], media.still["id"]]})[0],
            "Old request identity cannot reorder its frozen shots",
        )
        self.assertEqual(
            200,
            media.http(
                "/__ai",
                {
                    "action": "review",
                    "version": second["id"],
                    "signature": version_signature(second),
                    "by": "Editor",
                    "decision": "changes",
                },
            )[0],
        )
        before = len(media.requests)
        self.assertEqual(
            400,
            media.http(
                "/__ai", {"action": "launch-sequence", "sequence": sequence["id"], "signature": sequence["signature"]}
            )[0],
        )
        self.assertEqual(before, len(media.requests))
        self.assertEqual("stale", json.loads(media.http("/__ai/state")[1])["beats"][0]["sequence"]["state"])

    def test_shared_storyboard_sequence_and_graphics_reference_versions_remain_independent(self):
        from test_graphics_mixed_references import upload_media
        from test_graphics_reference_context import apply_image, complete, edit
        from test_graphics_review import _assign, _render, _review_payload, _version_hashes

        from getbrolls.ledger import Ledger

        media = self.media
        _assign(media.project, duration="2")
        _render(media.project)
        v1 = _version_hashes(media.project, "numeric-stat", "v1")
        payload = _review_payload(media.project)
        row = next(row for row in payload["graphics"] if row["current"])
        reference = upload_media(
            media.base, media.token, row, media.project / "brolls" / media.still["path"], "image", "R1"
        )
        graphics = Ledger(media.project, recover=False).data["graphics"]
        sequence = self.prepare()
        media.responses = [
            {"request_id": "mixed-1"},
            {"status": "done", "video": {"url": "https://media.example.com/1.mp4"}},
            self.clip("lime", 6),
            {"request_id": "mixed-2"},
            {"status": "done", "video": {"url": "https://media.example.com/2.mp4"}},
            self.clip("pink", 3),
        ]
        launch = {"action": "launch-sequence", "sequence": sequence["id"], "signature": sequence["signature"]}
        self.assertEqual(200, media.http("/__ai", launch)[0])
        self.assertEqual(graphics, Ledger(media.project, recover=False).data["graphics"])
        payload = _review_payload(media.project)
        seq_row = next(row for row in payload["ai"] if row.get("kind") == "sequence")
        seq_row.update(state="approved", decision="approved", comment="Synthetic mixed sequence check")
        row = next(row for row in payload["graphics"] if row["current"])
        edit(row, "Use R1 colors while preserving values.", [reference])
        path = Path(media.temp.name) / "mixed-review.json"
        path.write_text(json.dumps(payload), encoding="utf-8")
        self.assertEqual(1, media.call("import-review", "--file", path, "--by", "Test editor")["ai_imported"])
        ledger = Ledger(media.project, recover=False)
        request = ledger.data["graphics"]["requests"][-1]
        ai_before = ledger.data["ai"]
        apply_image(media.project, request)
        _render(media.project)
        complete(media.project, request, "v2")
        self.assertEqual(ai_before, Ledger(media.project, recover=False).data["ai"])
        self.assertEqual(v1, _version_hashes(media.project, "numeric-stat", "v1"))
        before = len(media.requests)
        media.server_restart()
        self.assertEqual(200, media.http("/__ai", launch)[0])
        self.assertEqual(before, len(media.requests))
        current = json.loads(media.http("/__ai/state")[1])["beats"][0]["sequence"]
        self.assertEqual("complete", current["state"], current)
        self.assertEqual("approved", current["version"]["approval"])
