"""Ordinary GPT economy and three-image launches keep active beat guidance.

The native peer is the synthetic app-server fixture. These tests do not call a live model.
"""

import copy
import hashlib
import io
import json
import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import _isolation  # noqa: F401
import _paths  # noqa: F401
from _media import skip_unless_ffmpeg, synth_image
from test_ai_references import _AFTER_OPENING, _BLUE_END, _BLUE_START, _two_tone

from getbrolls.ai import (
    dispatch_after_audit,
    generate_comparison_command,
    generate_still_command,
    handle_generate,
    handle_reference_upload,
    resume_command,
)
from getbrolls.ai_references import read_derivative, read_original, show_reference
from getbrolls.ai_state import fingerprint, import_plan, launch_comparison, select, version_signature
from getbrolls.ledger import Ledger
from getbrolls.runtime import project_lock

FIXTURE = Path(__file__).resolve().parent / "fixtures" / "ai_app_server.py"
_DIFFERENT = "This request identity already belongs to different frozen inputs."


def _plan():
    return {
        "scenario": "One resource is running out. A second passage needs a picture.",
        "style": "Restrained editorial realism, cool night lighting.",
        "beats": [
            {
                "id": "beat-1",
                "route": "ai",
                "text": "One resource is running out.",
                "purpose": "Illustrate scarcity without pretending to document an event.",
                "alternatives": [
                    "An empty reservoir",
                    "A final drop in a pipe",
                    "One container in an empty warehouse",
                ],
            }
        ],
    }


def _turns(workdir):
    path = workdir / "received.jsonl"
    if not path.is_file():
        return []
    found = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        if row.get("method") == "turn/start":
            found.append(row)
    return found


def _prompt_of(turn):
    return turn["params"]["input"][0]["text"]


def _images_of(turn):
    return [item for item in turn["params"]["input"] if isinstance(item, dict) and item.get("type") == "localImage"]


def _observation(context_id, role):
    return f"Synthetic observation of {context_id} for role {role}. Not image content."


@skip_unless_ffmpeg
class GuidedLaunchTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.project = Path(self.temp.name)
        self.env = patch.dict(
            os.environ,
            {
                "GETBROLLS_CODEX_APP_SERVER": str(FIXTURE),
                "GETBROLLS_AI_FIXTURE": "success",
                "GETBROLLS_AI_INLINE": "1",
                "GETBROLLS_AI_TIMEOUT": "8",
            },
            clear=False,
        )
        self.env.start()
        self.addCleanup(self.env.stop)
        ledger = Ledger(self.project)
        import_plan(ledger, _plan())
        select(ledger, {"beat": "beat-1", "alternative": "option-1", "comment": "No lettering"})
        (self.project / "media").mkdir()

    def _ai(self):
        return Ledger(self.project, recover=False).data["ai"]

    def _beat(self):
        return self._ai()["beats"]["beat-1"]

    def _job(self, job_id):
        return self._ai()["jobs"][job_id]

    def _request(self, job_id):
        return self._job(job_id)["request"]

    def _version(self, job_id):
        ai = self._ai()
        return ai["versions"][ai["jobs"][job_id]["result"]]

    def _version_bytes(self, job_id):
        version = self._version(job_id)
        return (self.project / "brolls" / version["path"]).read_bytes()

    def _workdir(self, job_id):
        return self.project / "brolls" / "ai-work" / job_id

    def _turn_count(self):
        total = 0
        root = self.project / "brolls" / "ai-work"
        if not root.is_dir():
            return 0
        for path in root.glob("*/turn-start-count.txt"):
            total += int(path.read_text(encoding="utf-8") or "0")
        return total

    def _ledger(self):
        return Ledger(self.project, recover=False)

    def _png(self, name, color):
        path = self.project / "media" / name
        synth_image(path, color=color, size="32x16")
        return path.read_bytes()

    def _upload(self, body, **metadata):
        beat = self._beat()
        payload = {
            "beat": "beat-1",
            "fingerprint": beat["fingerprint"],
            "identity": "ref-reservoir",
            "name": "reservoir.png",
            "declared_type": "image/png",
            "instructions": "Keep the empty reservoir and the cool night light.",
            "role": "appearance",
            "scope": "beat",
        }
        payload.update(metadata)
        return handle_reference_upload(self.project, io.BytesIO(body), len(body), payload)

    def _mode(self, mode):
        with project_lock(self.project):
            select(Ledger(self.project), {"beat": "beat-1", "mode": mode})

    def _cli_still(self, request_id):
        with project_lock(self.project):
            result = generate_still_command(
                Ledger(self.project),
                SimpleNamespace(beat="beat-1", request_id=request_id),
            )
        return dispatch_after_audit(result)

    def _cli_comparison(self, request_id):
        with project_lock(self.project):
            result = generate_comparison_command(
                Ledger(self.project),
                SimpleNamespace(beat="beat-1", request_id=request_id),
            )
        return dispatch_after_audit(result)

    def _assert_style(self, request):
        style = self._ai()["style"]
        self.assertEqual(style["prompt"], request["style"])
        self.assertEqual(style["fingerprint"], request["style_fingerprint"])
        self.assertEqual("agreed", request["quality"])
        self.assertIn("Agreed visual style: " + style["prompt"], request["prompt"])
        self.assertIn("Agreed quality: agreed", request["prompt"])
        self.assertIn("Editor comment: No lettering", request["prompt"])
        self.assertNotIn("target", request)
        self.assertNotIn("operation", request)

    def _assert_image_bytes(self, turn, blobs):
        images = _images_of(turn)
        self.assertEqual(len(blobs), len(images))
        for item, blob in zip(images, blobs, strict=True):
            data = Path(item["path"]).read_bytes()
            self.assertEqual(blob, data)
            self.assertTrue(data.startswith(b"\x89PNG\r\n\x1a\n"))
            self.assertIn(hashlib.sha256(data).hexdigest(), _prompt_of(turn))

    def _frame_blobs(self, uploaded):
        ledger = self._ledger()
        blobs = []
        for frame in uploaded["derivative"]["frames"]:
            self.assertGreater(frame["time_s"], _AFTER_OPENING)
            self.assertGreaterEqual(frame["time_s"], _BLUE_START)
            self.assertLess(frame["time_s"], _BLUE_END)
            blobs.append(read_derivative(ledger, uploaded["derivative"]["id"], "frame", frame["index"]))
        return blobs

    def test_cli_economy_image_freezes_guidance_and_reuses_findings(self):  # noqa: PLR0915 - One public launch/reopen/reuse journey checks retained bytes and observed handoff.
        body = self._png("reservoir.png", "red")
        uploaded = self._upload(body)
        context_id = uploaded["context_id"]
        derivative_id = uploaded["derivative"]["id"]
        pixels = read_derivative(self._ledger(), derivative_id, "pixels")
        self.assertEqual({}, self._ai()["jobs"])
        self.assertEqual(0, self._turn_count())

        launched = self._cli_still("econ-1")
        job_id = launched["job"]["id"]
        request = self._request(job_id)
        workdir = self._workdir(job_id)
        sentence = _observation(context_id, "appearance")
        inspection, production = _turns(workdir)
        self.assertEqual("complete", self._job(job_id)["state"])
        self.assertEqual(2, len(_turns(workdir)))
        self.assertIsNotNone(inspection["params"].get("outputSchema"))
        self.assertIsNone(production["params"].get("outputSchema"))
        self._assert_image_bytes(inspection, [pixels])
        self._assert_image_bytes(production, [pixels])
        self.assertIn(sentence, _prompt_of(production))
        self.assertNotIn(sentence, request["prompt"])
        self.assertIn(
            "Image reference role appearance: Keep the empty reservoir and the cool night light.",
            request["prompt"],
        )
        self.assertIn("An empty reservoir", request["prompt"])
        reference = request["references"][0]
        self.assertEqual(context_id, reference["context_id"])
        self.assertEqual("appearance", reference["role"])
        self.assertEqual(hashlib.sha256(body).hexdigest(), reference["source_sha256"])
        self.assertIn(hashlib.sha256(pixels).hexdigest(), reference["derivative_sha256"])
        self.assertEqual("Keep the empty reservoir and the cool night light.", reference["instructions"])
        self.assertIsNone(reference["findings"])
        self.assertIsNone(reference["interval"])
        self._assert_style(request)
        self.assertEqual(self._job(job_id)["fingerprint"], fingerprint(request))
        self.assertEqual("pending", self._version(job_id)["approval"]["state"])
        self.assertTrue(self._version_bytes(job_id).startswith(b"\x89PNG\r\n\x1a\n"))
        self.assertIn(sentence, self._job(job_id)["inspection"]["findings"])
        self.assertEqual("appearance", self._job(job_id)["inspection"]["sources"][0]["role"])
        frozen = copy.deepcopy(request)
        original_bytes = copy.deepcopy(self._version_bytes(job_id))

        again = self._cli_still("econ-2")
        second_id = again["job"]["id"]
        second = self._request(second_id)
        second_turns = _turns(self._workdir(second_id))
        self.assertNotEqual(job_id, second_id)
        self.assertEqual(1, len(second_turns))
        self.assertIsNone(second_turns[0]["params"].get("outputSchema"))
        self._assert_image_bytes(second_turns[0], [pixels])
        self.assertIn(sentence, _prompt_of(second_turns[0]))
        self.assertNotIn(sentence, second["prompt"])
        self.assertIn(sentence, second["references"][0]["findings"])
        self.assertEqual("appearance", second["references"][0]["role"])
        self.assertIn(hashlib.sha256(pixels).hexdigest(), second["references"][0]["derivative_sha256"])
        self.assertEqual(frozen, self._request(job_id))
        self.assertEqual(original_bytes, self._version_bytes(job_id))
        self.assertEqual("pending", self._version(job_id)["approval"]["state"])
        self.assertEqual("pending", self._version(second_id)["approval"]["state"])
        self.assertEqual(3, self._turn_count())
        snapshot = self._ai()["references"]["inputs"][frozen["references"][0]["input_id"]]["snapshot"]
        self.assertNotEqual("inspected", (snapshot.get("inspection") or {}).get("state"))
        self.assertEqual(body, read_original(self._ledger(), reference["source_sha256"]))

    def test_handler_video_interval_sends_later_frames(self):
        path = self.project / "media" / "moving.mp4"
        _two_tone(path)
        body = path.read_bytes()
        uploaded = self._upload(
            body,
            identity="ref-motion",
            name="moving.mp4",
            declared_type="video/mp4",
            instructions="Follow the blue field after the cut.",
            role="motion",
            interval={"start_s": _BLUE_START, "end_s": _BLUE_END, "content": "the blue field after the cut"},
        )
        self.assertFalse(uploaded["opening_was_used"])
        blobs = self._frame_blobs(uploaded)
        self.assertGreaterEqual(len(blobs), 2)
        self.assertEqual({}, self._ai()["jobs"])

        result = handle_generate(self.project, {"beat": "beat-1", "requestId": "video-econ"})
        job_id = result["job"]["id"]
        request = self._request(job_id)
        inspection, production = _turns(self._workdir(job_id))
        reference = request["references"][0]
        self.assertEqual("complete", self._job(job_id)["state"])
        self.assertEqual(2, len(_turns(self._workdir(job_id))))
        self.assertIsNotNone(inspection["params"].get("outputSchema"))
        self.assertIsNone(production["params"].get("outputSchema"))
        self._assert_image_bytes(inspection, blobs)
        self._assert_image_bytes(production, blobs)
        self.assertEqual("motion", reference["role"])
        self.assertEqual(_BLUE_START, reference["interval"]["start_s"])
        self.assertEqual(_BLUE_END, reference["interval"]["end_s"])
        self.assertEqual("Follow the blue field after the cut.", reference["instructions"])
        self.assertEqual(hashlib.sha256(body).hexdigest(), reference["source_sha256"])
        self.assertEqual(
            [frame["sha256"] for frame in uploaded["derivative"]["frames"]],
            [frame["sha256"] for frame in reference["frames"]],
        )
        self.assertTrue(all(frame["time_s"] > _AFTER_OPENING for frame in reference["frames"]))
        line = f"Video reference role motion: requested interval {_BLUE_START}–{_BLUE_END}s."
        self.assertIn(line, request["prompt"])
        self.assertIn("The opening was not substituted.", request["prompt"])
        self.assertIn(line, _prompt_of(production))
        for frame in reference["frames"]:
            self.assertIn(_observation(f"{uploaded['context_id']}:{frame['index']}", "motion"), _prompt_of(production))
            self.assertNotIn(_observation(f"{uploaded['context_id']}:{frame['index']}", "motion"), request["prompt"])
        self._assert_style(request)
        self.assertNotIn("target", request)
        self.assertEqual("pending", self._version(job_id)["approval"]["state"])
        self.assertEqual(body, read_original(self._ledger(), reference["source_sha256"]))

    def test_cli_comparison_slots_keep_guidance_siblings_and_identity(self):
        body = self._png("grid.png", "navy")
        self._mode("images")
        uploaded = self._upload(
            body,
            identity="ref-grid",
            name="grid.png",
            instructions="Hold the cool grid and the night edge.",
            role="composition",
        )
        context_id = uploaded["context_id"]
        pixels = read_derivative(self._ledger(), uploaded["derivative"]["id"], "pixels")
        line = "Image reference role composition: Hold the cool grid and the night edge."
        sentence = _observation(context_id, "composition")
        self.assertEqual({}, self._ai()["jobs"])

        first = self._cli_comparison("cmp-1")
        self.assertEqual(3, len(first["jobs"]))
        prompts = []
        blobs = set()
        for public in first["jobs"]:
            request = self._request(public["id"])
            inspection, production = _turns(self._workdir(public["id"]))
            self.assertEqual("complete", public["state"])
            self.assertEqual(2, len(_turns(self._workdir(public["id"]))))
            self._assert_image_bytes(inspection, [pixels])
            self._assert_image_bytes(production, [pixels])
            self.assertIn(sentence, _prompt_of(production))
            self.assertNotIn(sentence, request["prompt"])
            self.assertIn(line, request["prompt"])
            self.assertEqual(context_id, request["references"][0]["context_id"])
            self.assertEqual("composition", request["references"][0]["role"])
            self.assertEqual("Hold the cool grid and the night edge.", request["references"][0]["instructions"])
            self.assertIn(hashlib.sha256(pixels).hexdigest(), request["references"][0]["derivative_sha256"])
            self.assertIsNone(request["references"][0]["findings"])
            self.assertIn(sentence, self._job(public["id"])["inspection"]["findings"])
            self.assertEqual("composition", self._job(public["id"])["inspection"]["sources"][0]["role"])
            self._assert_style(request)
            self.assertEqual("pending", self._version(public["id"])["approval"]["state"])
            prompts.append(request["prompt"])
            blobs.add(self._version_bytes(public["id"]))
        self.assertEqual(3, len(set(prompts)))
        self.assertEqual(3, len(blobs))
        self.assertTrue(all(blob.startswith(b"\x89PNG\r\n\x1a\n") for blob in blobs))
        group = self._ai()["groups"][first["group"]]
        self.assertEqual(group["fingerprint"], fingerprint(group["scope"]))
        self.assertEqual(context_id, group["scope"]["references"][0]["context_id"])
        for job_id in group["jobs"]:
            self.assertEqual(group["scope"]["references"], self._request(job_id)["references"])
        frozen = {job_id: copy.deepcopy(self._request(job_id)) for job_id in group["jobs"]}
        self.assertEqual(6, self._turn_count())

        again = self._cli_comparison("cmp-1")
        self.assertEqual([job["id"] for job in first["jobs"]], [job["id"] for job in again["jobs"]])
        self.assertEqual(first["group"], again["group"])
        self.assertEqual(frozen, {job_id: self._request(job_id) for job_id in group["jobs"]})
        self.assertEqual(6, self._turn_count())

    def test_comparison_partial_and_unknown_do_not_replay_or_drop_guidance(self):
        body = self._png("grid.png", "navy")
        self._mode("images")
        uploaded = self._upload(
            body,
            identity="ref-grid",
            name="grid.png",
            instructions="Hold the cool grid and the night edge.",
            role="composition",
        )
        pixels = read_derivative(self._ledger(), uploaded["derivative"]["id"], "pixels")
        line = "Image reference role composition: Hold the cool grid and the night edge."

        with patch.dict(os.environ, {"GETBROLLS_AI_FAIL_IF_PROMPT_CONTAINS": "empty warehouse"}):
            failed = self._cli_comparison("cmp-fail")
        failed_states = {job["alternative"]: job["state"] for job in failed["jobs"]}
        self.assertEqual({"option-1": "complete", "option-2": "complete", "option-3": "failed"}, failed_states)
        self.assertIsNone(next(job["result"] for job in failed["jobs"] if job["alternative"] == "option-3"))
        kept = next(job for job in failed["jobs"] if job["alternative"] == "option-1")
        kept_request = copy.deepcopy(self._request(kept["id"]))
        kept_turns = _turns(self._workdir(kept["id"]))
        self.assertEqual(2, len(kept_turns))
        production = kept_turns[1]
        self.assertIn(line, kept_request["prompt"])
        self.assertEqual(pixels, Path(_images_of(production)[0]["path"]).read_bytes())
        self.assertEqual(uploaded["context_id"], kept_request["references"][0]["context_id"])
        failed_frozen = {job["id"]: copy.deepcopy(self._request(job["id"])) for job in failed["jobs"]}
        self.assertEqual(6, self._turn_count())
        replay = self._cli_comparison("cmp-fail")
        self.assertEqual([job["id"] for job in failed["jobs"]], [job["id"] for job in replay["jobs"]])
        self.assertEqual(failed_frozen, {job["id"]: self._request(job["id"]) for job in failed["jobs"]})
        self.assertEqual(6, self._turn_count())

        with patch.dict(
            os.environ,
            {"GETBROLLS_AI_UNKNOWN_IF_PROMPT_CONTAINS": "A final drop", "GETBROLLS_AI_TIMEOUT": "8"},
        ):
            unknown = self._cli_comparison("cmp-unknown")
        unknown_states = {job["alternative"]: job["state"] for job in unknown["jobs"]}
        self.assertEqual(
            {"option-1": "complete", "option-2": "unknown", "option-3": "complete"},
            unknown_states,
        )
        unknown_job = next(job for job in unknown["jobs"] if job["alternative"] == "option-2")
        self.assertIsNone(unknown_job["result"])
        self.assertIn(line, self._request(unknown_job["id"])["prompt"])
        self.assertEqual(uploaded["context_id"], self._request(unknown_job["id"])["references"][0]["context_id"])
        unknown_turns = _turns(self._workdir(unknown_job["id"]))
        self.assertEqual(1, len(unknown_turns), "Saved bound observations need no second inspection")
        self.assertIsNone(unknown_turns[0]["params"].get("outputSchema"))
        self.assertEqual(pixels, Path(_images_of(unknown_turns[0])[0]["path"]).read_bytes())
        self.assertEqual(9, self._turn_count())
        with project_lock(self.project):
            resumed = resume_command(Ledger(self.project), SimpleNamespace(job=unknown_job["id"]))
        self.assertFalse(resumed["resubmitted"])
        self.assertEqual("unknown", resumed["job"]["state"])
        self.assertTrue(resumed["ai_dispatch"]["retrieve"])
        recovered = dispatch_after_audit(resumed)
        self.assertEqual("unknown", recovered["job"]["state"], "Missing native history stays uncertain")
        self.assertEqual(9, self._turn_count(), "History retrieval must not repeat inspection or generation")
        repeated = self._cli_comparison("cmp-unknown")
        repeated_unknown = next(job["id"] for job in repeated["jobs"] if job["alternative"] == "option-2")
        self.assertEqual(unknown_job["id"], repeated_unknown)
        self.assertEqual(9, self._turn_count())
        self.assertEqual(failed_frozen, {job["id"]: self._request(job["id"]) for job in failed["jobs"]})

    def test_no_reference_handler_and_cli_stay_one_production_turn(self):
        handler = handle_generate(self.project, {"beat": "beat-1", "requestId": "plain-handler"})
        command = self._cli_still("plain-cli")
        self.assertEqual(2, self._turn_count())
        prompts = []
        for job_id in (handler["job"]["id"], command["job"]["id"]):
            request = self._request(job_id)
            turns = _turns(self._workdir(job_id))
            self.assertEqual("complete", self._job(job_id)["state"])
            self.assertEqual(1, len(turns))
            self.assertIsNone(turns[0]["params"].get("outputSchema"))
            self.assertEqual([], _images_of(turns[0]))
            self.assertNotIn("references", request)
            self.assertNotIn("Image reference role", request["prompt"])
            self.assertNotIn("Video reference role", request["prompt"])
            self._assert_style(request)
            self.assertEqual("pending", self._version(job_id)["approval"]["state"])
            self.assertTrue(self._version_bytes(job_id).startswith(b"\x89PNG\r\n\x1a\n"))
            prompts.append(request["prompt"])
        self.assertEqual(prompts[0], prompts[1])
        self.assertEqual("absent", show_reference(self._ledger(), "beat-1", self._beat()["fingerprint"])["state"])

    def test_tamper_stale_and_unsupported_routes_refuse_before_turns(self):  # noqa: PLR0915 - Verify every refusal preserves the same original reference and produces zero turns.
        body = self._png("reservoir.png", "red")
        uploaded = self._upload(body)
        context_id = uploaded["context_id"]
        comment = self._beat()["comment"]
        derivative = self._ai()["references"]["derivatives"][uploaded["derivative"]["id"]]
        pixels_path = self._ledger().root / derivative["pixels_ref"]
        original = pixels_path.read_bytes()
        pixels_path.write_bytes(original + b"tamper")
        try:
            with self.assertRaisesRegex(ValueError, "Saved reference bytes changed"):
                handle_generate(self.project, {"beat": "beat-1", "requestId": "tamper-1"})
        finally:
            pixels_path.write_bytes(original)
        self.assertEqual({}, self._ai()["jobs"])
        self.assertEqual(0, self._turn_count())
        self.assertEqual(comment, self._beat()["comment"])

        with project_lock(self.project):
            ledger = Ledger(self.project)
            context = ledger.data["ai"]["references"]["contexts"][context_id]
            kept = context["fingerprint"]
            context["fingerprint"] = "0" * 64
            ledger.save("ai-reference-inspect")
        with self.assertRaisesRegex(ValueError, "stale for the current beat"):
            handle_generate(self.project, {"beat": "beat-1", "requestId": "stale-1"})
        with project_lock(self.project):
            ledger = Ledger(self.project)
            ledger.data["ai"]["references"]["contexts"][context_id]["fingerprint"] = kept
            ledger.save("ai-reference-inspect")
        self.assertEqual({}, self._ai()["jobs"])
        self.assertEqual(0, self._turn_count())

        with self.assertRaisesRegex(ValueError, "native Grok image model is unverified"):
            handle_generate(
                self.project,
                {"beat": "beat-1", "requestId": "grok-still", "route": "grok-subscription", "model": "fixture-model"},
            )
        self._mode("images")
        with self.assertRaisesRegex(ValueError, "native Grok image model is unverified"):
            handle_generate(
                self.project,
                {
                    "beat": "beat-1",
                    "requestId": "grok-cmp",
                    "route": "grok-subscription",
                    "model": "fixture-model",
                    "outputs": 3,
                },
            )
        with self.assertRaisesRegex(ValueError, "does not accept a paid API route"):
            handle_generate(
                self.project,
                {"beat": "beat-1", "requestId": "paid-http", "route": "openrouter", "outputs": 3},
            )
        with project_lock(self.project), self.assertRaisesRegex(ValueError, "OpenRouter was not called"):
            launch_comparison(
                Ledger(self.project),
                {"beat": "beat-1", "outputs": 3, "route": "openrouter"},
                "paid-guided",
            )
        self.assertEqual({}, self._ai()["jobs"])
        self.assertEqual(0, self._turn_count())
        self.assertEqual(comment, self._beat()["comment"])
        shown = show_reference(self._ledger(), "beat-1", self._beat()["fingerprint"])
        self.assertEqual(context_id, shown["context_id"])
        self.assertTrue(shown["received"])
        self.assertEqual(body, read_original(self._ledger(), uploaded["sha256"]))

        self._mode("economy")
        result = handle_generate(self.project, {"beat": "beat-1", "requestId": "after-refusal"})
        self.assertEqual("complete", result["job"]["state"])
        self.assertEqual(context_id, self._request(result["job"]["id"])["references"][0]["context_id"])
        self.assertEqual(2, self._turn_count())
        self.assertEqual(1, len(self._ai()["jobs"]))

    def test_still_bound_guidance_is_not_guessed(self):
        root = handle_generate(self.project, {"beat": "beat-1", "requestId": "root-still"})
        root_id = root["job"]["id"]
        version = self._version(root_id)
        still = {"id": version["id"], "signature": version_signature(version)}
        body = self._png("bound.png", "blue")
        bound = self._upload(
            body,
            identity="ref-bound",
            name="bound.png",
            instructions="Keep the blue appearance.",
            still=still,
        )
        with project_lock(self.project):
            select(Ledger(self.project), {"beat": "beat-1", "comment": "Keep the draft"})
        with self.assertRaisesRegex(ValueError, "Use Apply for that retained result"):
            handle_generate(self.project, {"beat": "beat-1", "requestId": "guess-still"})
        self.assertEqual({root_id}, set(self._ai()["jobs"]))
        self.assertEqual(1, self._turn_count())
        self.assertNotIn("references", self._request(root_id))
        self.assertNotIn("target", self._request(root_id))
        self.assertEqual("Keep the draft", self._beat()["comment"])
        shown = show_reference(self._ledger(), "beat-1", self._beat()["fingerprint"], still["id"])
        self.assertEqual(bound["context_id"], shown["context_id"])
        self.assertEqual(still["id"], shown["still"]["id"])

        beat_level = self._upload(
            self._png("beat-level.png", "green"),
            identity="ref-beat",
            name="beat-level.png",
            instructions="Keep the beat-level field.",
            role="content",
        )
        with self.assertRaisesRegex(ValueError, "Use Apply for that retained result"):
            self._cli_still("guess-both")
        self.assertEqual({root_id}, set(self._ai()["jobs"]))
        self.assertEqual(1, self._turn_count())
        self.assertEqual("Keep the draft", self._beat()["comment"])
        shown_still = show_reference(self._ledger(), "beat-1", self._beat()["fingerprint"], still["id"])
        self.assertEqual(bound["context_id"], shown_still["context_id"])
        self.assertEqual(
            beat_level["context_id"],
            show_reference(self._ledger(), "beat-1", self._beat()["fingerprint"])["context_id"],
        )

    def test_changed_reference_does_not_reuse_or_overwrite_history(self):
        original = self._png("reservoir.png", "red")
        uploaded = self._upload(original)
        launched = self._cli_still("econ-same")
        job_id = launched["job"]["id"]
        frozen = copy.deepcopy(self._request(job_id))
        version_bytes = self._version_bytes(job_id)
        old_pixels = read_derivative(self._ledger(), uploaded["derivative"]["id"], "pixels")
        self.assertEqual(old_pixels, Path(_images_of(_turns(self._workdir(job_id))[1])[0]["path"]).read_bytes())

        duplicate = self._cli_still("econ-same")
        self.assertEqual(job_id, duplicate["job"]["id"])
        self.assertEqual(2, self._turn_count())

        replacement = self._png("replacement.png", "green")
        replaced = self._upload(
            replacement,
            identity="ref-next",
            name="replacement.png",
            instructions="Use the green field only.",
            role="style",
            replace=True,
        )
        with project_lock(self.project), self.assertRaisesRegex(ValueError, _DIFFERENT):
            generate_still_command(
                Ledger(self.project),
                SimpleNamespace(beat="beat-1", request_id="econ-same"),
            )
        self.assertEqual({job_id}, set(self._ai()["jobs"]))
        self.assertEqual(frozen, self._request(job_id))
        self.assertEqual(version_bytes, self._version_bytes(job_id))
        self.assertEqual(original, read_original(self._ledger(), frozen["references"][0]["source_sha256"]))
        self.assertEqual("pending", self._version(job_id)["approval"]["state"])
        self.assertEqual(2, self._turn_count())
        self.assertEqual("No lettering", self._beat()["comment"])

        launched_next = self._cli_still("econ-next")
        next_id = launched_next["job"]["id"]
        nxt = self._request(next_id)
        production = _turns(self._workdir(next_id))[-1]
        new_pixels = read_derivative(self._ledger(), replaced["derivative"]["id"], "pixels")
        self.assertNotEqual(job_id, next_id)
        self.assertEqual(replaced["context_id"], nxt["references"][0]["context_id"])
        self.assertNotEqual(frozen["references"][0]["context_id"], nxt["references"][0]["context_id"])
        self.assertEqual("style", nxt["references"][0]["role"])
        self.assertEqual("Use the green field only.", nxt["references"][0]["instructions"])
        self.assertEqual(hashlib.sha256(replacement).hexdigest(), nxt["references"][0]["source_sha256"])
        self.assertIn("Image reference role style: Use the green field only.", nxt["prompt"])
        self.assertEqual(new_pixels, Path(_images_of(production)[0]["path"]).read_bytes())
        self.assertNotEqual(old_pixels, new_pixels)
        self.assertEqual(frozen, self._request(job_id))
        self.assertEqual(version_bytes, self._version_bytes(job_id))
        self.assertEqual(original, read_original(self._ledger(), frozen["references"][0]["source_sha256"]))
        self.assertEqual("pending", self._version(job_id)["approval"]["state"])
        self.assertEqual("pending", self._version(next_id)["approval"]["state"])

    def test_unknown_submit_does_not_replay(self):
        body = self._png("reservoir.png", "red")
        uploaded = self._upload(body)
        pixels = read_derivative(self._ledger(), uploaded["derivative"]["id"], "pixels")
        with patch.dict(os.environ, {"GETBROLLS_AI_FIXTURE": "lost_ack", "GETBROLLS_AI_TIMEOUT": "1"}):
            result = handle_generate(self.project, {"beat": "beat-1", "requestId": "unknown-guided"})
        job_id = result["job"]["id"]
        turns = _turns(self._workdir(job_id))
        frozen = copy.deepcopy(self._request(job_id))
        self.assertEqual("unknown", self._job(job_id)["state"])
        self.assertEqual("unknown", self._job(job_id)["submit_outcome"])
        self.assertEqual(1, len(turns))
        self.assertIsNotNone(turns[0]["params"].get("outputSchema"))
        self.assertEqual(pixels, Path(_images_of(turns[0])[0]["path"]).read_bytes())
        self.assertIsNone(self._job(job_id)["result"])
        self.assertEqual({}, self._ai()["versions"])
        self.assertEqual(uploaded["context_id"], frozen["references"][0]["context_id"])
        with project_lock(self.project):
            resumed = resume_command(Ledger(self.project), SimpleNamespace(job=job_id))
        self.assertFalse(resumed["resubmitted"])
        self.assertNotIn("ai_dispatch", resumed)
        with patch.dict(os.environ, {"GETBROLLS_AI_FIXTURE": "success"}):
            again = handle_generate(self.project, {"beat": "beat-1", "requestId": "unknown-guided"})
        self.assertEqual(job_id, again["job"]["id"])
        self.assertEqual("unknown", again["job"]["state"])
        self.assertEqual(1, self._turn_count())
        self.assertEqual(frozen, self._request(job_id))
        self.assertEqual(body, read_original(self._ledger(), frozen["references"][0]["source_sha256"]))
        self.assertEqual("No lettering", self._beat()["comment"])
