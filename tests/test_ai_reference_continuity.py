"""Active guidance stays on later exact-result revisions until replace or remove.

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
from unittest.mock import patch

import _isolation  # noqa: F401
import _paths  # noqa: F401
from _media import skip_unless_ffmpeg, synth_image
from test_ai_references import _two_tone

from getbrolls.ai import (
    handle_apply,
    handle_generate,
    handle_reference_remove,
    handle_reference_upload,
    handle_select,
    public_board,
    reference_preview_bytes,
)
from getbrolls.ai_references import read_original, show_reference
from getbrolls.ai_state import import_plan, select, version_signature
from getbrolls.ledger import Ledger

FIXTURE = Path(__file__).resolve().parent / "fixtures" / "ai_app_server.py"
_BLUE_START = 2.6
_BLUE_END = 3.4


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
            },
            {
                "id": "beat-2",
                "route": "ai",
                "text": "A second passage needs a picture.",
                "purpose": "Show the remaining supply without inventing an event.",
                "alternatives": ["A closed valve", "A marked gauge", "A single spare canister"],
            },
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


def _turn_count(workdir):
    path = workdir / "turn-start-count.txt"
    if not path.is_file():
        return 0
    return int(path.read_text(encoding="utf-8") or "0")


def _observation(context_id, role):
    return f"Synthetic observation of {context_id} for role {role}. Not image content."


@skip_unless_ffmpeg
class ReferenceContinuityTests(unittest.TestCase):
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

    def _beat(self, beat_id="beat-1"):
        return self._ai()["beats"][beat_id]

    def _job(self, job_id):
        return self._ai()["jobs"][job_id]

    def _request(self, job_id):
        return self._job(job_id)["request"]

    def _version(self, job_id):
        ai = self._ai()
        return ai["versions"][ai["jobs"][job_id]["result"]]

    def _still(self, job_id):
        version = self._version(job_id)
        return {"id": version["id"], "signature": version_signature(version)}

    def _workdir(self, job_id):
        return self.project / "brolls" / "ai-work" / job_id

    def _job_ids(self):
        return set(self._ai()["jobs"])

    def _input_ids(self):
        return set((self._ai().get("references") or {}).get("inputs") or {})

    def _approvals(self):
        rows = []
        for ident, version in self._ai()["versions"].items():
            approval = version.get("approval") if isinstance(version, dict) else None
            rows.append((ident, json.dumps(approval, sort_keys=True)))
        return tuple(sorted(rows))

    def _context(self, context_id):
        return self._ai()["references"]["contexts"][context_id]

    def _input(self, input_id):
        return self._ai()["references"]["inputs"][input_id]

    def _board(self, beat_id="beat-1"):
        board = public_board(Ledger(self.project, recover=False))
        return next(row for row in board["beats"] if row["id"] == beat_id)

    def _png(self, name, color):
        path = self.project / "media" / name
        synth_image(path, color=color, size="32x16")
        return path.read_bytes()

    def _apply(self, request_id, still, instruction, beat="beat-1"):
        os.environ["GETBROLLS_AI_FIXTURE"] = "success"
        payload = {
            "beat": beat,
            "expected": self._beat(beat)["fingerprint"],
            "instruction": instruction,
            "requestId": request_id,
            "operation": "apply",
            "still": still,
        }
        return handle_apply(self.project, payload)

    def _generate(self, beat, request_id):
        os.environ["GETBROLLS_AI_FIXTURE"] = "success"
        return handle_generate(self.project, {"beat": beat, "requestId": request_id})

    def _upload(  # noqa: PLR0913 - Public upload fields stay named in the multi-step reference journeys.
        self,
        body,
        *,
        identity,
        name,
        declared,
        instructions,
        still,
        role="appearance",
        replace=False,
        interval=None,
        beat="beat-1",
    ):
        metadata = {
            "beat": beat,
            "fingerprint": self._beat(beat)["fingerprint"],
            "identity": identity,
            "name": name,
            "declared_type": declared,
            "instructions": instructions,
            "role": role,
            "scope": "beat",
        }
        if still is not None:
            metadata["still"] = still
        if replace:
            metadata["replace"] = True
        if interval is not None:
            metadata["interval"] = interval
        return handle_reference_upload(self.project, io.BytesIO(body), len(body), metadata)

    def _remove(self, still, beat="beat-1"):
        return handle_reference_remove(
            self.project,
            {"beat": beat, "expected": self._beat(beat)["fingerprint"], "still": still},
        )

    def _image_hashes(self, turn):
        found = set()
        for item in _images_of(turn):
            found.add(hashlib.sha256(Path(item["path"]).read_bytes()).hexdigest())
        return found

    def _assert_pending(self, job_id):
        self.assertEqual({"state": "pending"}, self._version(job_id)["approval"])

    def _assert_bound(self, context_id, still, body):
        record = self._context(context_id)
        self.assertEqual("active", record["status"])
        self.assertEqual(still["id"], record["still"]["id"])
        self.assertEqual(still["signature"], record["still"]["signature"])
        self.assertEqual(body, read_original(Ledger(self.project, recover=False), record["original_sha256"]))

    def _guided_image(self):
        generated = self._generate("beat-1", "still-root")
        root_id = generated["job"]["id"]
        root = self._still(root_id)
        jobs = self._job_ids()
        approvals = self._approvals()
        body = self._png("guidance.png", "blue")
        uploaded = self._upload(
            body,
            identity="ref-blue",
            name="guidance.png",
            declared="image/png",
            instructions="Keep the blue appearance.",
            role="appearance",
            still=root,
        )
        self.assertEqual(jobs, self._job_ids())
        self.assertEqual(approvals, self._approvals())
        return root_id, root, uploaded, body

    def test_text_only_revisions_keep_image_guidance_and_bound_observations(self):  # noqa: PLR0915 - This regression follows one retained lineage across several public revisions.
        root_id, root, uploaded, body = self._guided_image()
        context_id = uploaded["context_id"]
        jobs = self._job_ids()
        approvals = self._approvals()
        style = copy.deepcopy(self._ai()["style"])
        passage = self._beat()["text"]
        self.assertEqual(root["id"], uploaded["still"]["id"])
        self.assertEqual(jobs, self._job_ids())
        self.assertEqual(approvals, self._approvals())
        self.assertEqual(style, self._ai()["style"])
        self.assertEqual(passage, self._beat()["text"])
        selected = handle_select(
            self.project,
            {"beat": "beat-1", "comment": "No people", "expected": self._beat()["fingerprint"]},
        )
        self.assertEqual("No people", selected["beat"]["comment"])
        self.assertEqual(jobs, self._job_ids())
        self.assertEqual(context_id, self._board()["reference"]["context_id"])
        retry = self._upload(
            body,
            identity="ref-blue",
            name="guidance.png",
            declared="image/png",
            instructions="Keep the blue appearance.",
            still=root,
        )
        self.assertEqual(context_id, retry["context_id"])
        self.assertEqual(jobs, self._job_ids())

        second = self._apply("revision-1", root, "Keep the blue field.")
        second_id = second["job"]["id"]
        sentence = _observation(context_id, "appearance")
        self.assertEqual("complete", self._job(second_id)["state"])
        self.assertEqual(root["id"], self._request(second_id)["target"]["id"])
        self.assertEqual([context_id], [ref["context_id"] for ref in self._request(second_id)["references"]])
        self.assertNotIn("findings", self._request(second_id)["references"][0])
        self.assertEqual(2, _turn_count(self._workdir(second_id)))
        self.assertIn(sentence, _prompt_of(_turns(self._workdir(second_id))[1]))
        self.assertNotIn(sentence, self._request(second_id)["prompt"])
        self._assert_pending(second_id)
        frozen_request = copy.deepcopy(self._request(second_id))
        frozen_input_id = frozen_request["references"][0]["input_id"]
        frozen_input = copy.deepcopy(self._input(frozen_input_id))
        self.assertEqual(root["id"], frozen_input["snapshot"]["still"]["id"])
        self.assertEqual("historical", frozen_input["snapshot"]["status"])
        self.assertEqual("active", self._context(context_id)["status"])
        child = self._still(second_id)

        third = self._apply("revision-2", child, "Shift the light slightly.")
        third_id = third["job"]["id"]
        third_refs = self._request(third_id)["references"]
        self.assertEqual("complete", self._job(third_id)["state"])
        self.assertEqual(child["id"], self._request(third_id)["target"]["id"])
        self.assertEqual([context_id], [ref["context_id"] for ref in third_refs])
        self.assertIn(sentence, third_refs[0]["findings"])
        self.assertNotIn(sentence, self._request(third_id)["prompt"])
        self.assertEqual(1, _turn_count(self._workdir(third_id)))
        later = _turns(self._workdir(third_id))[0]
        self.assertIsNone(later["params"].get("outputSchema"))
        self.assertIn(sentence, _prompt_of(later))
        self.assertTrue(set(third_refs[0]["derivative_sha256"]) & self._image_hashes(later))
        retained = self._input(third_refs[0]["input_id"])["snapshot"]
        self.assertEqual(root["id"], retained["still"]["id"])
        self.assertEqual(root["signature"], retained["still"]["signature"])
        self.assertEqual(context_id, retained["id"])
        self.assertNotEqual(child["id"], retained["still"]["id"])
        self._assert_pending(third_id)
        self._assert_bound(context_id, root, body)
        grandchild = self._still(third_id)

        fourth = self._apply("revision-3", grandchild, "Hold the same field.")
        fourth_id = fourth["job"]["id"]
        self.assertEqual([context_id], [ref["context_id"] for ref in self._request(fourth_id)["references"]])
        self.assertEqual(grandchild["id"], self._request(fourth_id)["target"]["id"])
        self.assertEqual(1, _turn_count(self._workdir(fourth_id)))
        self.assertIn(sentence, _prompt_of(_turns(self._workdir(fourth_id))[0]))
        self._assert_pending(fourth_id)
        self.assertEqual({"state": "pending"}, self._version(root_id)["approval"])
        self.assertEqual(frozen_request, self._request(second_id))
        self.assertEqual(frozen_input, self._input(frozen_input_id))
        self.assertEqual("No people", self._beat()["comment"])
        self._assert_bound(context_id, root, body)

        newest = self._still(fourth_id)
        shown = show_reference(Ledger(self.project, recover=False), "beat-1", self._beat()["fingerprint"], newest["id"])
        self.assertEqual(context_id, shown["context_id"])
        self.assertEqual("active", shown["state"])
        self.assertEqual(root["id"], shown["still"]["id"])
        self.assertEqual(root["signature"], shown["still"]["signature"])
        self.assertTrue(shown["applies_to_displayed_still"])
        self.assertTrue(all(not row.get("applies_to_displayed_still") for row in shown["preserved"]))
        reopened = public_board(Ledger(self.project, recover=False))
        card = next(row for row in reopened["beats"] if row["id"] == "beat-1")["reference"]
        self.assertEqual(context_id, card["context_id"])
        self.assertEqual(uploaded["sha256"], card["sha256"])
        self.assertEqual("Keep the blue appearance.", card["instructions"])
        self.assertTrue(card["received"])
        preview, content_type = reference_preview_bytes(self.project, context_id, "pixels")
        self.assertEqual("image/png", content_type)
        self.assertTrue(preview.startswith(b"\x89PNG\r\n\x1a\n"))
        self.assertIn(hashlib.sha256(preview).hexdigest(), third_refs[0]["derivative_sha256"])
        versions = set(self._ai()["versions"])
        again = self._apply("revision-3", grandchild, "Hold the same field.")
        self.assertEqual(fourth_id, again["job"]["id"])
        self.assertEqual(versions, set(self._ai()["versions"]))

    def test_later_interval_video_guidance_persists(self):  # noqa: PLR0915 - Keep upload, interval pixels, reopening and next production in one public journey.
        generated = self._generate("beat-1", "video-root")
        root = self._still(generated["job"]["id"])
        path = self.project / "media" / "moving.mp4"
        _two_tone(path)
        body = path.read_bytes()
        uploaded = self._upload(
            body,
            identity="ref-motion",
            name="moving.mp4",
            declared="video/mp4",
            instructions="Follow the blue field after the cut.",
            role="motion",
            still=root,
            interval={"start_s": _BLUE_START, "end_s": _BLUE_END, "content": "the blue field after the cut"},
        )
        context_id = uploaded["context_id"]
        frames = uploaded["derivative"]["frames"]
        self.assertFalse(uploaded["opening_was_used"])
        self.assertEqual(_BLUE_START, uploaded["interval"]["start_s"])
        self.assertEqual(_BLUE_END, uploaded["interval"]["end_s"])
        self.assertGreaterEqual(len(frames), 1)
        self.assertTrue(all(_BLUE_START <= frame["time_s"] < _BLUE_END for frame in frames))
        self.assertTrue(all(frame["time_s"] > 1 for frame in frames))
        self.assertEqual({generated["job"]["id"]}, self._job_ids())

        second = self._apply("video-revision-1", root, "Keep the later interval.")
        second_id = second["job"]["id"]
        self.assertEqual(2, _turn_count(self._workdir(second_id)))
        frozen_request = copy.deepcopy(self._request(second_id))
        frozen_input = copy.deepcopy(self._input(frozen_request["references"][0]["input_id"]))
        self.assertEqual(root["id"], frozen_input["snapshot"]["still"]["id"])
        child = self._still(second_id)
        sentence = _observation(f"{context_id}:0", "motion")

        third = self._apply("video-revision-2", child, "Hold the same interval.")
        third_id = third["job"]["id"]
        ref = self._request(third_id)["references"][0]
        self.assertEqual(context_id, ref["context_id"])
        self.assertEqual("video", ref["kind"])
        self.assertEqual(_BLUE_START, ref["interval"]["start_s"])
        self.assertEqual(_BLUE_END, ref["interval"]["end_s"])
        self.assertEqual(frames, ref["frames"])
        self.assertEqual(child["id"], self._request(third_id)["target"]["id"])
        self.assertEqual(root["id"], self._input(ref["input_id"])["snapshot"]["still"]["id"])
        self.assertEqual(1, _turn_count(self._workdir(third_id)))
        production = _turns(self._workdir(third_id))[0]
        self.assertIsNone(production["params"].get("outputSchema"))
        self.assertIn(sentence, _prompt_of(production))
        self.assertNotIn(sentence, self._request(third_id)["prompt"])
        self.assertTrue({frame["sha256"] for frame in frames} <= self._image_hashes(production))
        self._assert_pending(third_id)
        grandchild = self._still(third_id)

        fourth = self._apply("video-revision-3", grandchild, "Revise the text only.")
        fourth_id = fourth["job"]["id"]
        kept = self._request(fourth_id)["references"][0]
        self.assertEqual(context_id, kept["context_id"])
        self.assertEqual(frames, kept["frames"])
        self.assertEqual(root["id"], self._input(kept["input_id"])["snapshot"]["still"]["id"])
        self.assertEqual(root["signature"], self._input(kept["input_id"])["snapshot"]["still"]["signature"])
        self.assertEqual(1, _turn_count(self._workdir(fourth_id)))
        self.assertIn(sentence, _prompt_of(_turns(self._workdir(fourth_id))[0]))
        self.assertEqual(frozen_request, self._request(second_id))
        self.assertEqual(frozen_input, self._input(frozen_request["references"][0]["input_id"]))
        self._assert_bound(context_id, root, body)
        self.assertEqual(context_id, self._board()["reference"]["context_id"])
        self.assertEqual("video", self._board()["reference"]["kind"])
        preview, content_type = reference_preview_bytes(self.project, context_id, "sheet")
        self.assertEqual("image/png", content_type)
        self.assertTrue(preview.startswith(b"\x89PNG\r\n\x1a\n"))

    def test_replace_and_remove_persist_without_generation_or_resurface(self):  # noqa: PLR0915 - One lineage must preserve its ancestors through replacement, removal and later Apply.
        _root_id, root, uploaded, body = self._guided_image()
        context_id = uploaded["context_id"]
        base = self._apply("replace-base", root, "First revision.")
        base_id = base["job"]["id"]
        child = self._still(base_id)
        frozen_request = copy.deepcopy(self._request(base_id))
        frozen_input = copy.deepcopy(self._input(frozen_request["references"][0]["input_id"]))
        jobs = self._job_ids()
        approvals = self._approvals()
        nearer = self._png("nearer.png", "navy")
        with self.assertRaisesRegex(ValueError, "Replace or remove it explicitly"):
            self._upload(
                nearer,
                identity="ref-plain",
                name="nearer.png",
                declared="image/png",
                instructions="This attach is not an explicit replace.",
                still=child,
            )
        self.assertEqual(jobs, self._job_ids())
        self.assertEqual(approvals, self._approvals())
        identities = {row.get("identity") for row in self._ai()["references"]["contexts"].values()}
        self.assertNotIn("ref-plain", identities)

        replaced = self._upload(
            nearer,
            identity="ref-nearer",
            name="nearer.png",
            declared="image/png",
            instructions="Use the nearer field.",
            still=child,
            replace=True,
        )
        replacement_id = replaced["context_id"]
        self.assertEqual(jobs, self._job_ids())
        self.assertEqual(approvals, self._approvals())
        self.assertEqual(child["id"], replaced["still"]["id"])
        self.assertNotEqual(context_id, replacement_id)
        self._assert_bound(context_id, root, body)
        self.assertEqual(replacement_id, self._board()["reference"]["context_id"])
        preview, _content_type = reference_preview_bytes(self.project, replacement_id, "pixels")
        self.assertTrue(preview.startswith(b"\x89PNG\r\n\x1a\n"))

        replaced_job = self._apply("replace-child", child, "Use the replacement.")
        replaced_id = replaced_job["job"]["id"]
        replaced_refs = self._request(replaced_id)["references"]
        self.assertEqual([replacement_id], [ref["context_id"] for ref in replaced_refs])
        self.assertEqual(child["id"], self._input(replaced_refs[0]["input_id"])["snapshot"]["still"]["id"])
        sentence = _observation(replacement_id, "appearance")
        self.assertEqual(2, _turn_count(self._workdir(replaced_id)))
        self.assertIn(sentence, _prompt_of(_turns(self._workdir(replaced_id))[1]))
        grandchild = self._still(replaced_id)

        carried = self._apply("replace-grandchild", grandchild, "Keep the replacement.")
        carried_id = carried["job"]["id"]
        carried_ref = self._request(carried_id)["references"][0]
        self.assertEqual(replacement_id, carried_ref["context_id"])
        self.assertNotEqual(context_id, carried_ref["context_id"])
        self.assertEqual(child["id"], self._input(carried_ref["input_id"])["snapshot"]["still"]["id"])
        self.assertNotEqual(grandchild["id"], self._input(carried_ref["input_id"])["snapshot"]["still"]["id"])
        self.assertEqual(1, _turn_count(self._workdir(carried_id)))
        self.assertIn(sentence, _prompt_of(_turns(self._workdir(carried_id))[0]))
        self._assert_bound(context_id, root, body)
        self._assert_bound(replacement_id, child, nearer)
        displayed = self._still(carried_id)
        current = show_reference(
            Ledger(self.project, recover=False), "beat-1", self._beat()["fingerprint"], displayed["id"]
        )
        self.assertEqual(replacement_id, current["context_id"])
        self.assertTrue(current["applies_to_displayed_still"])
        self.assertEqual(child["id"], current["still"]["id"])
        ancestor = next(row for row in current["preserved"] if row["context_id"] == context_id)
        self.assertEqual("active", ancestor["state"])
        self.assertEqual(root["id"], ancestor["still"]["id"])
        self.assertFalse(ancestor["applies_to_displayed_still"])

        beat_body = self._png("beat-guide.png", "green")
        beat_ref = self._upload(
            beat_body,
            identity="ref-beat",
            name="beat-guide.png",
            declared="image/png",
            instructions="Beat guidance stays separate.",
            still=None,
        )
        self.assertEqual(jobs | {replaced_id, carried_id}, self._job_ids())
        removed = self._remove(displayed)
        self.assertEqual("absent", removed["reference"]["state"])
        self.assertIsNone(removed["reference"]["active"])
        self.assertEqual(jobs | {replaced_id, carried_id}, self._job_ids())
        self.assertIsNone(self._board()["reference"])
        self.assertEqual(beat_ref["context_id"], self._board()["guidance"]["context_id"])
        reopened = Ledger(self.project, recover=False)
        fingerprint = self._beat()["fingerprint"]
        self.assertEqual("absent", show_reference(reopened, "beat-1", fingerprint, displayed["id"])["state"])
        root_shown = show_reference(reopened, "beat-1", fingerprint, root["id"])
        self.assertEqual(context_id, root_shown["context_id"])
        self.assertFalse(root_shown["applies_to_displayed_still"])
        self.assertEqual(replacement_id, show_reference(reopened, "beat-1", fingerprint, child["id"])["context_id"])

        later = self._apply("after-remove", displayed, "Text only after removal.")
        later_id = later["job"]["id"]
        later_ids = [ref["context_id"] for ref in self._request(later_id)["references"]]
        self.assertEqual([beat_ref["context_id"]], later_ids)
        self.assertNotIn(context_id, later_ids)
        self.assertNotIn(replacement_id, later_ids)
        self.assertIsNone(self._board()["reference"])
        self.assertEqual(beat_ref["context_id"], self._board()["guidance"]["context_id"])
        descendant = self._still(later_id)
        reopened = Ledger(self.project, recover=False)
        self.assertEqual("absent", show_reference(reopened, "beat-1", fingerprint, displayed["id"])["state"])
        self.assertEqual("absent", show_reference(reopened, "beat-1", fingerprint, descendant["id"])["state"])
        self.assertEqual(frozen_request, self._request(base_id))
        self.assertEqual(frozen_input, self._input(frozen_request["references"][0]["input_id"]))
        self._assert_bound(context_id, root, body)
        self._assert_bound(replacement_id, child, nearer)
        self.assertEqual(self._beat()["text"], "One resource is running out.")
        self.assertEqual("beat", self._context(replacement_id)["scope"])
        self.assertIsNone(self._context(replacement_id)["scope_instruction"])

    def test_sibling_beat_and_branch_keep_their_own_guidance(self):
        _root_id, root, uploaded, body = self._guided_image()
        context_id = uploaded["context_id"]
        left = self._apply("branch-left", root, "Left revision.")
        left_id = left["job"]["id"]
        left_still = self._still(left_id)
        left_request = copy.deepcopy(self._request(left_id))
        right = self._apply("branch-right", root, "Right revision.")
        right_id = right["job"]["id"]
        right_still = self._still(right_id)
        self.assertEqual([context_id], [ref["context_id"] for ref in self._request(left_id)["references"]])
        self.assertEqual([context_id], [ref["context_id"] for ref in self._request(right_id)["references"]])
        jobs = self._job_ids()
        nearer = self._png("right.png", "navy")
        replaced = self._upload(
            nearer,
            identity="ref-right",
            name="right.png",
            declared="image/png",
            instructions="Only the right branch.",
            still=right_still,
            replace=True,
        )
        self.assertEqual(jobs, self._job_ids())
        right_child = self._apply("right-child", right_still, "Use the right picture.")
        right_child_id = right_child["job"]["id"]
        self.assertEqual(
            [replaced["context_id"]],
            [ref["context_id"] for ref in self._request(right_child_id)["references"]],
        )
        self.assertEqual(
            right_still["id"],
            self._input(self._request(right_child_id)["references"][0]["input_id"])["snapshot"]["still"]["id"],
        )
        left_child = self._apply("left-child", left_still, "Stay with the first picture.")
        left_child_id = left_child["job"]["id"]
        left_ref = self._request(left_child_id)["references"][0]
        self.assertEqual(context_id, left_ref["context_id"])
        self.assertNotEqual(replaced["context_id"], left_ref["context_id"])
        self.assertEqual(root["id"], self._input(left_ref["input_id"])["snapshot"]["still"]["id"])
        self.assertEqual(root["signature"], self._input(left_ref["input_id"])["snapshot"]["still"]["signature"])
        self.assertEqual(left_request, self._request(left_id))
        self._assert_bound(context_id, root, body)
        self._assert_bound(replaced["context_id"], right_still, nearer)
        root_again = self._apply("root-after-branch", root, "Revise the original after a later result.")
        root_again_id = root_again["job"]["id"]
        root_again_ref = self._request(root_again_id)["references"][0]
        self.assertEqual(context_id, root_again_ref["context_id"])
        self.assertNotEqual(replaced["context_id"], root_again_ref["context_id"])
        self.assertEqual(root["id"], self._input(root_again_ref["input_id"])["snapshot"]["still"]["id"])
        self.assertEqual(root["signature"], self._input(root_again_ref["input_id"])["snapshot"]["still"]["signature"])
        self.assertEqual(left_request, self._request(left_id))

        handle_select(
            self.project,
            {"beat": "beat-2", "alternative": "option-1", "expected": self._beat("beat-2")["fingerprint"]},
        )
        other = self._generate("beat-2", "beat-2-root")
        other_still = self._still(other["job"]["id"])
        other_apply = self._apply("beat-2-apply", other_still, "A different passage.", beat="beat-2")
        other_id = other_apply["job"]["id"]
        self.assertEqual([], self._request(other_id)["references"])
        self.assertIsNone(self._board("beat-2")["reference"])
        self.assertIsNone(self._board("beat-2")["guidance"])
        shown = show_reference(
            Ledger(self.project, recover=False),
            "beat-1",
            self._beat()["fingerprint"],
            left_still["id"],
        )
        self.assertEqual(context_id, shown["context_id"])
        self._assert_bound(context_id, root, body)

    def test_stale_and_tampered_lineage_is_refused(self):
        _root_id, root, uploaded, body = self._guided_image()
        context_id = uploaded["context_id"]
        applied = self._apply("tamper-base", root, "Keep the blue field.")
        applied_id = applied["job"]["id"]
        child = self._still(applied_id)
        frozen_request = copy.deepcopy(self._request(applied_id))

        stale = {"id": child["id"], "signature": "0" * 64}
        self._refuse(
            "displayed still changed",
            lambda: self._apply("tamper-stale", stale, "Stale signature."),
            frozen_request,
            applied_id,
        )
        self._refuse(
            "scenario or style changed",
            lambda: handle_apply(
                self.project,
                {
                    "beat": "beat-1",
                    "expected": "0" * 64,
                    "instruction": "Wrong fingerprint.",
                    "requestId": "tamper-fingerprint",
                    "still": child,
                },
            ),
            frozen_request,
            applied_id,
        )

        handle_select(
            self.project,
            {"beat": "beat-2", "alternative": "option-1", "expected": self._beat("beat-2")["fingerprint"]},
        )
        other = self._generate("beat-2", "tamper-other-root")
        other_still = self._still(other["job"]["id"])
        self._refuse(
            "another beat",
            lambda: self._apply("tamper-cross", other_still, "Wrong beat."),
            frozen_request,
            applied_id,
        )

        self._mutate_version(root["id"], "width", self._version_by_id(root["id"])["width"] + 1)
        self._refuse(
            "retained still changed",
            lambda: self._apply("tamper-signature", child, "Ancestor signature drifted."),
            frozen_request,
            applied_id,
        )
        self._mutate_version(root["id"], "width", self._version_by_id(root["id"])["width"] - 1)

        removed = self._pop_version(root["id"])
        self._refuse(
            "ancestor still is missing",
            lambda: self._apply("tamper-missing", child, "Ancestor removed."),
            frozen_request,
            applied_id,
        )
        self._restore_version(root["id"], removed)

        self._mutate_version(root["id"], "beat", "beat-2")
        self._refuse(
            "another beat",
            lambda: self._apply("tamper-beat", child, "Ancestor moved beats."),
            frozen_request,
            applied_id,
        )
        self._mutate_version(root["id"], "beat", "beat-1")

        self._flip_version_file(root["id"])
        self._refuse(
            "retained still bytes changed",
            lambda: self._apply("tamper-file", child, "Ancestor file drifted."),
            frozen_request,
            applied_id,
        )
        self._flip_version_file(root["id"])

        self._flip_reference_file(context_id, "original")
        self._refuse(
            "existing file was preserved",
            lambda: self._apply("tamper-original", child, "Original bytes drifted."),
            frozen_request,
            applied_id,
        )
        self._flip_reference_file(context_id, "original")

        self._flip_reference_file(context_id, "derivative")
        self._refuse(
            "existing file was preserved",
            lambda: self._apply("tamper-derivative", child, "Derivative bytes drifted."),
            frozen_request,
            applied_id,
        )
        self._flip_reference_file(context_id, "derivative")

        record = self._context(context_id)
        self._mutate_context_signature(context_id, "0" * 64)
        self._refuse(
            "retained still changed",
            lambda: self._apply("tamper-binding", child, "Binding signature drifted."),
            frozen_request,
            applied_id,
        )
        self._mutate_context_signature(context_id, record["still"]["signature"])

        self._mutate_job(applied_id, "result", root["id"])
        self._refuse(
            "producing job does not match",
            lambda: self._apply("tamper-job-link", child, "Broken producing link."),
            frozen_request,
            applied_id,
        )
        self._mutate_job(applied_id, "result", child["id"])

        shown = show_reference(Ledger(self.project, recover=False), "beat-1", self._beat()["fingerprint"], child["id"])
        self.assertEqual(context_id, shown["context_id"])
        self.assertEqual(root["id"], shown["still"]["id"])
        self._assert_bound(context_id, root, body)

    def _refuse(self, message, call, frozen_request, applied_id):
        jobs = self._job_ids()
        inputs = self._input_ids()
        approvals = self._approvals()
        with self.assertRaisesRegex(ValueError, message):
            call()
        self.assertEqual(jobs, self._job_ids())
        self.assertEqual(inputs, self._input_ids())
        self.assertEqual(approvals, self._approvals())
        self.assertEqual(frozen_request, self._request(applied_id))

    def _version_by_id(self, version_id):
        return self._ai()["versions"][version_id]

    def _save(self, mutate):
        ledger = Ledger(self.project)
        mutate(ledger)
        ledger.save("test-tamper")

    def _mutate_job(self, job_id, key, value):
        def mutate(ledger):
            ledger.data["ai"]["jobs"][job_id][key] = value

        self._save(mutate)

    def _mutate_version(self, version_id, key, value):
        def mutate(ledger):
            ledger.data["ai"]["versions"][version_id][key] = value

        self._save(mutate)

    def _pop_version(self, version_id):
        holder = {}

        def mutate(ledger):
            holder["version"] = ledger.data["ai"]["versions"].pop(version_id)

        self._save(mutate)
        return holder["version"]

    def _restore_version(self, version_id, version):
        def mutate(ledger):
            ledger.data["ai"]["versions"][version_id] = version

        self._save(mutate)

    def _mutate_context_signature(self, context_id, signature):
        def mutate(ledger):
            ledger.data["ai"]["references"]["contexts"][context_id]["still"]["signature"] = signature

        self._save(mutate)

    def _flip_version_file(self, version_id):
        path = Ledger(self.project, recover=False).root / self._version_by_id(version_id)["path"]
        self._flip(path)

    def _flip_reference_file(self, context_id, kind):
        ledger = Ledger(self.project, recover=False)
        store = ledger.data["ai"]["references"]
        record = store["contexts"][context_id]
        if kind == "original":
            rel = store["originals"][record["original_sha256"]]["ref"]
        else:
            rel = store["derivatives"][record["derivative_id"]]["pixels_ref"]
        self._flip(ledger.root / rel)

    def _flip(self, path):
        data = path.read_bytes()
        path.write_bytes(data[:-1] + bytes([data[-1] ^ 1]))
