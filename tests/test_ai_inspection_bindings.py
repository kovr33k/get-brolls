"""Role-bound native inspection: manifest, mismatch refusal, and production handoff.

The native peer is the synthetic app-server fixture. These tests do not call a live model.
"""

import hashlib
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import _isolation  # noqa: F401
import _paths  # noqa: F401
from _media import skip_unless_ffmpeg, synth_image

from getbrolls.ai import (
    _accept_findings,
    _inspect_prompt,
    _observation_manifest,
    _observations_document,
    _reference_needs_inspection,
    _reused_observation,
    handle_apply,
    handle_generate,
)
from getbrolls.ai_provider import generate_still, inspect_images
from getbrolls.ai_references import attach_reference, remove_reference
from getbrolls.ai_state import import_plan, select, version_signature
from getbrolls.ledger import Ledger
from getbrolls.runtime import project_lock

FIXTURE = Path(__file__).resolve().parent / "fixtures" / "ai_app_server.py"
PNG = bytes.fromhex(
    "89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c489"
    "0000000a49444154789c63000100000500010d0a2db40000000049454e44ae426082"
)
PROMPT = "A still of an empty reservoir, no lettering."
OVERRIDE = "features.image_generation=false"


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


def _manifest_of(prompt):
    lines = prompt.splitlines()
    start = lines.index("INSPECTION_MANIFEST")
    end = lines.index("END_INSPECTION_MANIFEST")
    return [json.loads(line) for line in lines[start + 1 : end] if line.strip()]


def _methods(workdir):
    path = workdir / "received.jsonl"
    if not path.is_file():
        return []
    return [json.loads(line).get("method") for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def _turn_count(workdir):
    path = workdir / "turn-start-count.txt"
    if not path.is_file():
        return 0
    return int(path.read_text(encoding="utf-8") or "0")


def _argv(workdir):
    return json.loads((workdir / "argv.json").read_text(encoding="utf-8"))


class InspectionProviderTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.workdir = Path(self.temp.name)
        self.env = patch.dict(
            os.environ,
            {
                "GETBROLLS_CODEX_APP_SERVER": str(FIXTURE),
                "GETBROLLS_AI_FIXTURE": "success",
                "GETBROLLS_AI_TIMEOUT": "8",
            },
            clear=False,
        )
        self.env.start()
        self.addCleanup(self.env.stop)

    def test_pre_submit_gate_refuses_before_a_thread(self):
        image = self.workdir / "sample.png"
        image.write_bytes(PNG)
        for mode in ("gate_absent", "gate_unverified", "gate_refused"):
            with self.subTest(mode=mode):
                os.environ["GETBROLLS_AI_FIXTURE"] = mode
                result = inspect_images(
                    "Inspect the attached images only.",
                    self.workdir,
                    [{"path": str(image)}],
                    timeout=8,
                )
                self.assertEqual("unsupported", result["status"])
                self.assertEqual("inspection_gate", result["code"])
                self.assertNotIn("thread/start", _methods(self.workdir))
                self.assertNotIn("turn/start", _methods(self.workdir))
                self.assertFalse((self.workdir / "still.png").is_file())

    def test_ordinary_generation_has_no_inspection_override(self):
        os.environ["GETBROLLS_AI_FIXTURE"] = "success"
        result = generate_still(PROMPT, self.workdir, timeout=8)
        self.assertEqual("complete", result["status"])
        self.assertTrue(Path(result["path"]).is_file())
        self.assertNotIn(OVERRIDE, _argv(self.workdir))
        self.assertNotIn("config/read", _methods(self.workdir))
        turn = _turns(self.workdir)[0]
        self.assertIsNone(turn["params"].get("outputSchema"))

    def test_fixture_echoes_the_supplied_manifest_without_hashing_pixels(self):
        image = self.workdir / "sample.png"
        image.write_bytes(PNG)
        actual = hashlib.sha256(PNG).hexdigest()
        fake = "ab" * 32
        self.assertNotEqual(actual, fake)
        row = {
            "path": str(image),
            "role": "appearance",
            "sha256": fake,
            "context_id": "ctx-1",
            "interval": None,
        }
        prompt = _inspect_prompt("Keep the night light.", None, [], _observation_manifest([row]))
        self.assertIn("Do not calculate a hash from pixels", prompt)
        self.assertNotIn(str(image), prompt)
        os.environ["GETBROLLS_AI_FIXTURE"] = "success"
        result = inspect_images(prompt, self.workdir, [{"path": str(image), "detail": "original"}], timeout=8)
        self.assertEqual("complete", result["status"])
        self.assertFalse(result["media"])
        self.assertFalse((self.workdir / "still.png").is_file())
        self.assertIn(OVERRIDE, _argv(self.workdir))
        observations = json.loads(result["findings"])["observations"]
        self.assertEqual("ctx-1", observations[0]["id"])
        self.assertEqual("appearance", observations[0]["role"])
        self.assertEqual(fake, observations[0]["sha256"])
        self.assertIn("Synthetic observation of ctx-1 for role appearance", observations[0]["observation"])
        stored = json.loads((self.workdir / "local-images.json").read_text(encoding="utf-8"))
        self.assertEqual(actual, stored[0][0]["sha256"])
        self.assertNotEqual(fake, stored[0][0]["sha256"])
        self.assertEqual(actual, hashlib.sha256(Path(stored[0][0]["path"]).read_bytes()).hexdigest())

    def test_manifest_carries_interval_and_frame_time_without_a_path(self):
        digest = "cd" * 32
        manifest = _observation_manifest(
            [
                {
                    "path": r"C:\secret\frame.png",
                    "role": "motion",
                    "sha256": digest,
                    "context_id": "ctx-video",
                    "interval": {"start_s": 1, "end_s": 2.5, "note": "hidden"},
                    "frame": {"index": 3, "time_s": 1.25},
                }
            ]
        )
        self.assertEqual(
            {
                "id": "ctx-video:3",
                "order": 1,
                "role": "motion",
                "sha256": digest,
                "context_id": "ctx-video",
                "interval": {"start_s": 1, "end_s": 2.5},
                "time_s": 1.25,
            },
            manifest[0],
        )
        prompt = _inspect_prompt("Look.", None, [], manifest)
        self.assertNotIn("secret", prompt)
        self.assertNotIn("hidden", prompt)
        self.assertIn(digest, prompt)

    def test_validator_rejects_malformed_observations(self):
        image = self.workdir / "sample.png"
        image.write_bytes(PNG)
        digest = hashlib.sha256(PNG).hexdigest()
        row = {
            "path": str(image),
            "role": "appearance",
            "sha256": digest,
            "context_id": "ctx-1",
            "interval": None,
            "derivative_sha256": [digest],
        }
        valid = {
            "id": "ctx-1",
            "order": 1,
            "role": "appearance",
            "sha256": digest,
            "observation": "A red field.",
        }

        def accept(observations):
            return _accept_findings({"findings": json.dumps({"observations": observations})}, [row])

        bound = accept([valid])
        self.assertEqual("A red field.", bound[0]["observation"])
        self.assertEqual("appearance", bound[0]["role"])
        cases = {
            "wrong-role": [{**valid, "role": "unrelated-role"}],
            "wrong-hash": [{**valid, "sha256": "0" * 64}],
            "missing": [],
            "duplicate": [valid, dict(valid)],
            "empty": [{**valid, "observation": "   "}],
            "extra": [valid, {**valid, "id": "other", "order": 2}],
        }
        for name, observations in cases.items():
            with self.subTest(name=name), self.assertRaises(ValueError):
                accept(observations)

    def test_inspected_flag_without_a_bound_observation_is_not_reused(self):
        digest = "ab" * 32
        row = {"context_id": "ctx-1", "role": "appearance", "sha256": digest, "interval": None}
        flagged = {
            "context_id": "ctx-1",
            "role": "appearance",
            "inspection": "inspected",
            "inspection_origin": "native-gpt",
            "provider_input": "localImage",
            "findings": "inspected",
        }
        self.assertTrue(_reference_needs_inspection(flagged))
        self.assertIsNone(_reused_observation(row, [flagged]))
        flagged["findings"] = _observations_document(
            [
                {
                    "id": "ctx-1",
                    "order": 1,
                    "role": "appearance",
                    "sha256": digest,
                    "observation": "A red field.",
                }
            ]
        )
        reused = _reused_observation(row, [flagged])
        self.assertIsNotNone(reused)
        assert reused is not None
        self.assertEqual("A red field.", reused["observation"])
        self.assertIsNone(_reused_observation({**row, "sha256": "cd" * 32}, [flagged]))
        self.assertIsNone(_reused_observation({**row, "role": "motion"}, [flagged]))


@skip_unless_ffmpeg
class InspectionWorkerTests(unittest.TestCase):
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
        media = self.project / "media"
        media.mkdir()
        image = media / "reservoir.png"
        synth_image(image, color="red", size="16x16")
        body = image.read_bytes()
        beat = ledger.data["ai"]["beats"]["beat-1"]
        with project_lock(self.project):
            self.reference = attach_reference(
                ledger,
                {
                    "beat": "beat-1",
                    "fingerprint": beat["fingerprint"],
                    "identity": "ref-reservoir",
                    "name": "reservoir.png",
                    "declared_type": "image/png",
                    "body": body,
                    "length": len(body),
                    "instructions": "Keep the empty reservoir and the cool night light.",
                    "role": "appearance",
                },
            )

    def _apply(
        self, request_id, mode="success", operation="apply", instruction="Keep the cool night light.", *, still=None
    ):
        os.environ["GETBROLLS_AI_FIXTURE"] = mode
        payload = {
            "beat": "beat-1",
            "instruction": instruction,
            "requestId": request_id,
            "operation": operation,
        }
        if still is not None:
            payload["still"] = still
        return handle_apply(
            self.project,
            payload,
        )

    def _still(self, job_id):
        ai = Ledger(self.project, recover=False).data["ai"]
        version = ai["versions"][ai["jobs"][job_id]["result"]]
        return {"id": version["id"], "signature": version_signature(version)}

    def _job(self, job_id):
        return Ledger(self.project, recover=False).data["ai"]["jobs"][job_id]

    def _workdir(self, job_id):
        return self.project / "brolls" / "ai-work" / job_id

    def _stored_request(self, job_id):
        return self._job(job_id)["request"]

    def test_ordinary_launch_without_guidance_stays_a_single_generation_turn(self):
        with project_lock(self.project):
            ledger = Ledger(self.project)
            beat = ledger.data["ai"]["beats"]["beat-1"]
            remove_reference(ledger, {"beat": beat["id"], "fingerprint": beat["fingerprint"]})
        os.environ["GETBROLLS_AI_FIXTURE"] = "success"
        result = handle_generate(self.project, {"beat": "beat-1", "requestId": "still-1"})
        job_id = result["job"]["id"]
        workdir = self._workdir(job_id)
        self.assertEqual("complete", self._job(job_id)["state"])
        self.assertEqual(1, _turn_count(workdir))
        self.assertNotIn(OVERRIDE, _argv(workdir))
        self.assertIsNone(_turns(workdir)[0]["params"].get("outputSchema"))
        self.assertEqual(1, len(Ledger(self.project, recover=False).data["ai"]["versions"]))

    def test_apply_hands_the_returned_observation_to_production(self):
        result = self._apply("apply-1")
        job_id = result["job"]["id"]
        job = self._job(job_id)
        workdir = self._workdir(job_id)
        self.assertEqual("complete", job["state"])
        self.assertEqual(2, _turn_count(workdir))
        inspection, production = _turns(workdir)
        self.assertIsNotNone(inspection["params"].get("outputSchema"))
        self.assertIsNone(production["params"].get("outputSchema"))
        prompt = _prompt_of(inspection)
        manifest = _manifest_of(prompt)
        self.assertEqual(1, len(manifest))
        self.assertEqual(self.reference["context_id"], manifest[0]["id"])
        self.assertEqual("appearance", manifest[0]["role"])
        self.assertEqual(1, manifest[0]["order"])
        attached = _images_of(inspection)
        self.assertEqual(attached, _images_of(production))
        file_hash = hashlib.sha256(Path(attached[0]["path"]).read_bytes()).hexdigest()
        self.assertEqual(file_hash, manifest[0]["sha256"])
        stored = json.loads((workdir / "local-images.json").read_text(encoding="utf-8"))
        self.assertEqual(file_hash, stored[0][0]["sha256"])
        self.assertEqual(file_hash, stored[1][0]["sha256"])
        sentence = f"Synthetic observation of {self.reference['context_id']} for role appearance. Not image content."
        self.assertIn(sentence, _prompt_of(production))
        self.assertNotIn(sentence, self._stored_request(job_id)["prompt"])
        self.assertNotIn("findings", self._stored_request(job_id)["references"][0])
        self.assertNotIn(str(Path(attached[0]["path"])), prompt)
        source = job["inspection"]["sources"][0]
        self.assertEqual("appearance", source["role"])
        self.assertEqual(sentence, source["observation"])
        self.assertEqual(file_hash, source["sha256"])
        self.assertEqual(
            {"threadId": "thr_getbrolls_test", "turnId": "turn_getbrolls_test"},
            job["inspection"]["evidence"],
        )
        contexts = Ledger(self.project, recover=False).data["ai"]["references"]["contexts"]
        context = contexts[self.reference["context_id"]]
        self.assertEqual("inspected", context["inspection"]["state"])
        self.assertIn(sentence, context["inspection"]["findings"])

    def test_explicit_session_model_reaches_both_inspection_and_production(self):
        ledger = Ledger(self.project)
        plan = _plan()
        plan["still_provider"] = {"route": "gpt-subscription", "session_model": "fixture-session-model"}
        import_plan(ledger, plan)
        result = self._apply("explicit-session-apply")
        job_id = result["job"]["id"]
        self.assertEqual("complete", self._job(job_id)["state"])
        self.assertEqual("fixture-session-model", self._stored_request(job_id)["session_model"])
        rows = [
            json.loads(line)
            for line in (self._workdir(job_id) / "received.jsonl").read_text(encoding="utf-8").splitlines()
        ]
        starts = [row["params"] for row in rows if row.get("method") == "thread/start"]
        self.assertEqual(["fixture-session-model"] * 2, [row["model"] for row in starts])
        self.assertTrue(all(row["allowProviderModelFallback"] is False for row in starts))

    def test_mismatch_refuses_before_production_and_does_not_mark_inspected(self):
        modes = (
            "inspection_wrong_role",
            "inspection_wrong_hash",
            "inspection_missing",
            "inspection_duplicate",
        )
        for index, mode in enumerate(modes, start=1):
            with self.subTest(mode=mode):
                result = self._apply(f"mismatch-{index}", mode=mode, instruction=f"Instruction {index}.")
                job_id = result["job"]["id"]
                job = self._job(job_id)
                workdir = self._workdir(job_id)
                self.assertEqual("failed", job["state"])
                self.assertEqual("inspection_mismatch", job["error"]["code"])
                self.assertEqual(1, _turn_count(workdir))
                self.assertIsNotNone(_turns(workdir)[0]["params"].get("outputSchema"))
                self.assertFalse((workdir / "still.png").is_file())
                self.assertNotIn("inspection", job)
                context = Ledger(self.project, recover=False).data["ai"]["references"]["contexts"][
                    self.reference["context_id"]
                ]
                self.assertNotEqual("inspected", (context.get("inspection") or {}).get("state"))

    def test_inspection_only_submits_no_media(self):
        result = self._apply("inspect-1", operation="inspect")
        job_id = result["job"]["id"]
        job = self._job(job_id)
        workdir = self._workdir(job_id)
        self.assertEqual("complete", job["state"])
        self.assertIsNone(job["result"])
        self.assertEqual(1, _turn_count(workdir))
        self.assertIsNotNone(_turns(workdir)[0]["params"].get("outputSchema"))
        self.assertFalse((workdir / "still.png").is_file())
        self.assertFalse(job["inspection"]["media"])
        self.assertEqual({}, Ledger(self.project, recover=False).data["ai"]["versions"])
        sentence = f"Synthetic observation of {self.reference['context_id']} for role appearance. Not image content."
        self.assertIn(sentence, job["inspection"]["findings"])

    def test_hostile_inspection_media_is_retained_failed_and_not_retried(self):
        result = self._apply("hostile-1", mode="inspection_hostile")
        job_id = result["job"]["id"]
        job = self._job(job_id)
        workdir = self._workdir(job_id)
        still = workdir / "still.png"
        self.assertEqual("failed", job["state"])
        self.assertEqual("inspection_media", job["error"]["code"])
        self.assertEqual(1, _turn_count(workdir))
        self.assertEqual(1, len(_turns(workdir)))
        self.assertTrue(still.is_file())
        unexpected = job["unexpected_media"]
        self.assertTrue(unexpected["media"])
        self.assertTrue(unexpected["generated"])
        self.assertIsNone(unexpected["approval"])
        self.assertEqual(hashlib.sha256(still.read_bytes()).hexdigest(), unexpected["sha256"])
        self.assertEqual({}, Ledger(self.project, recover=False).data["ai"]["versions"])
        self.assertNotIn("inspection", job)

    def test_later_request_reuses_bound_observations_and_keeps_history(self):
        first = self._apply("apply-history")
        first_id = first["job"]["id"]
        frozen = json.loads(json.dumps(self._stored_request(first_id)))
        sentence = f"Synthetic observation of {self.reference['context_id']} for role appearance. Not image content."
        second = self._apply("apply-later", instruction="Shift the light slightly.", still=self._still(first_id))
        second_id = second["job"]["id"]
        workdir = self._workdir(second_id)
        self.assertEqual("complete", self._job(second_id)["state"])
        self.assertEqual(1, _turn_count(workdir))
        turn = _turns(workdir)[0]
        self.assertIsNone(turn["params"].get("outputSchema"))
        self.assertIn(sentence, _prompt_of(turn))
        self.assertNotIn(sentence, self._stored_request(second_id)["prompt"])
        self.assertIn(sentence, self._stored_request(second_id)["references"][0]["findings"])
        self.assertTrue(_images_of(turn))
        self.assertEqual(frozen, self._stored_request(first_id))

    def test_flag_without_findings_is_inspected_again_and_cannot_generate(self):
        first = self._apply("apply-flag")
        with project_lock(self.project):
            ledger = Ledger(self.project)
            record = ledger.data["ai"]["references"]["contexts"][self.reference["context_id"]]
            record["inspection"]["findings"] = "inspected"
            ledger.save("ai-reference-inspect")
        result = self._apply(
            "apply-flag-again",
            mode="inspection_wrong_role",
            instruction="Try the flag alone.",
            still=self._still(first["job"]["id"]),
        )
        job_id = result["job"]["id"]
        job = self._job(job_id)
        workdir = self._workdir(job_id)
        self.assertEqual("failed", job["state"])
        self.assertEqual("inspection_mismatch", job["error"]["code"])
        self.assertEqual(1, _turn_count(workdir))
        self.assertIsNotNone(_turns(workdir)[0]["params"].get("outputSchema"))
        self.assertFalse((workdir / "still.png").is_file())
