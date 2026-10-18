"""AI planning, per-launch consent, immutable requests and approval boundaries."""

import copy
import json
import tempfile
import unittest
from pathlib import Path

import _isolation  # noqa: F401
import _paths  # noqa: F401

from getbrolls.ai_state import (
    checked_version,
    confirm,
    fingerprint,
    import_plan,
    new_job,
    public_job,
    review,
    select,
    validate_ai,
    version_signature,
)
from getbrolls.ledger import Ledger, digest


def plan():
    return {
        "scenario": "One resource is running out. A second passage needs real footage.",
        "style": "Restrained editorial realism, cool night lighting.",
        "beats": [
            {
                "id": "beat-1",
                "route": "ai",
                "text": "One resource is running out.",
                "purpose": "Illustrate scarcity without pretending to document an event.",
                "alternatives": ["An empty reservoir", "A final drop in a pipe", "One container in an empty warehouse"],
            },
            {"id": "beat-2", "route": "broll", "text": "A second passage needs real footage."},
        ],
    }


def request(ledger, route="gpt-subscription"):
    beat = ledger.data["ai"]["beats"]["beat-1"]
    return {
        "beat": beat["id"],
        "inputs": beat["fingerprint"],
        "kind": "image",
        "route": route,
        "alternative": "option-2",
        "prompt": "A final drop in a pipe, no lettering.",
    }


class AIStateTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.project = Path(self.temp.name)
        self.ledger = Ledger(self.project)
        import_plan(self.ledger, plan())

    def test_legacy_manifest_without_ai_remains_read_only(self):
        target = self.project / "absent"
        ledger = Ledger(target, recover=False)
        before = copy.deepcopy(ledger.data)
        validate_ai(ledger.data)
        self.assertEqual(before, ledger.data)
        self.assertFalse(target.exists())

    def test_routing_and_three_text_alternatives_do_not_generate_media(self):
        ai = self.ledger.data["ai"]
        self.assertEqual(["ai", "broll"], [r["route"] for r in ai["plan"]["routing"]])
        self.assertEqual(["beat-1"], list(ai["beats"]))
        self.assertEqual("economy", ai["beats"]["beat-1"]["mode"])
        self.assertEqual(3, len(ai["beats"]["beat-1"]["alternatives"]))
        self.assertFalse(ai["jobs"])
        self.assertFalse(ai["versions"])

    def test_bad_later_beat_does_not_partially_replace_plan(self):
        before = self.ledger.path.read_bytes()
        payload = plan()
        payload["beats"][1]["text"] = "Invented narration."
        with self.assertRaisesRegex(ValueError, "original scenario"):
            import_plan(self.ledger, payload)
        self.assertEqual(before, self.ledger.path.read_bytes())
        self.assertEqual(self.ledger.data, Ledger(self.project).data)

    def test_three_identical_descriptions_are_not_scene_choice(self):
        payload = plan()
        payload["beats"][0]["alternatives"] = ["Same image"] * 3
        with self.assertRaisesRegex(ValueError, "duplicate alternatives"):
            import_plan(self.ledger, payload)

    def test_comment_and_mode_are_saved_without_launch(self):
        select(self.ledger, {"beat": "beat-1", "alternative": "option-2", "comment": "No people", "mode": "images"})
        ai = Ledger(self.project).data["ai"]
        self.assertEqual("No people", ai["beats"]["beat-1"]["comment"])
        self.assertEqual("images", ai["beats"]["beat-1"]["mode"])
        self.assertFalse(ai["jobs"])

    def test_omitted_mode_and_comment_keep_the_saved_choice(self):
        from argparse import Namespace

        from getbrolls.ai import select_command

        select(self.ledger, {"beat": "beat-1", "alternative": "option-1", "comment": "Hold the wide shot"})
        result = select_command(
            self.ledger,
            Namespace(beat="beat-1", alternative="option-2", comment=None, mode=None, expected=None),
        )
        saved = Ledger(self.project).data["ai"]["beats"]["beat-1"]
        self.assertEqual("option-2", result["selected"])
        self.assertEqual("economy", result["mode"])
        self.assertEqual("Hold the wide shot", saved["comment"])
        self.assertEqual("economy", saved["mode"])
        self.assertFalse(saved.get("jobs"))
        self.assertFalse(self.ledger.data["ai"]["jobs"])

    def test_second_completion_of_one_job_does_not_replace_its_result(self):
        from getbrolls.ai_state import attach_result

        job = new_job(self.ledger, request(self.ledger), "same-result")
        self.ledger.save("test-job")
        first = {
            "id": "still-first",
            "beat": "beat-1",
            "kind": "image",
            "path": "previews/ai-still-first.png",
            "sha256": fingerprint("bytes"),
            "original_sha256": fingerprint("bytes"),
            "inputs": job["request"]["inputs"],
            "width": 1,
            "height": 1,
            "codec": "png",
            "job": job["id"],
            "approval": {"state": "pending"},
        }
        attach_result(self.ledger, job, first)
        self.ledger.save("ai-complete")
        second = {**first, "id": "still-second", "path": "previews/ai-still-second.png"}
        kept = attach_result(self.ledger, job, second)
        self.ledger.save("ai-complete-again")
        stored = Ledger(self.project).data["ai"]
        self.assertEqual("still-first", kept["id"])
        self.assertEqual("still-first", stored["jobs"][job["id"]]["result"])
        self.assertEqual(["still-first"], list(stored["versions"]))

    def test_old_board_does_not_retarget_changed_beat(self):
        old = self.ledger.data["ai"]["beats"]["beat-1"]["fingerprint"]
        payload = plan()
        payload["beats"][0]["purpose"] = "A different intended explanation."
        import_plan(self.ledger, payload)
        with self.assertRaisesRegex(ValueError, "changed"):
            select(self.ledger, {"beat": "beat-1", "alternative": "option-2", "expected": old})

    def test_repeated_submission_returns_existing_frozen_job_after_reload(self):
        original = request(self.ledger)
        job = new_job(self.ledger, original, "browser-request")
        original["prompt"] = "Changed after submission"
        self.ledger.save("test-job")
        ledger = Ledger(self.project)
        again = new_job(ledger, request(ledger), "browser-request")
        self.assertEqual(job["id"], again["id"])
        self.assertEqual(1, len(ledger.data["ai"]["jobs"]))
        with self.assertRaisesRegex(ValueError, "different frozen inputs"):
            new_job(ledger, original, "browser-request")

    def test_api_job_waits_for_matching_confirmation(self):
        job = new_job(self.ledger, request(self.ledger, "openrouter"), "paid-request")
        self.ledger.save("test-job")
        self.assertEqual("awaiting_confirmation", job["state"])
        with self.assertRaisesRegex(ValueError, "changed inputs"):
            confirm(self.ledger, [job["id"]], {job["id"]: "0" * 64}, "Editor")
        self.assertEqual("awaiting_confirmation", job["state"])
        confirm(self.ledger, [job["id"]], {job["id"]: job["fingerprint"]}, "Editor")
        self.assertEqual("queued", Ledger(self.project).data["ai"]["jobs"][job["id"]]["state"])
        with self.assertRaisesRegex(ValueError, "already confirmed"):
            confirm(self.ledger, [job["id"]], {job["id"]: job["fingerprint"]}, "Editor")

    def test_group_confirmation_is_atomic(self):
        first = new_job(self.ledger, request(self.ledger, "openrouter"), "paid-a")
        second = new_job(self.ledger, request(self.ledger, "openrouter"), "paid-b")
        self.ledger.save("test-jobs")
        with self.assertRaises(ValueError):
            confirm(self.ledger, [first["id"], second["id"]], {first["id"]: first["fingerprint"]}, "Editor")
        self.assertEqual("awaiting_confirmation", first["state"])
        self.assertIsNone(first["confirmation"])

    def test_manifest_cannot_make_unconfirmed_paid_work_runnable(self):
        job = new_job(self.ledger, request(self.ledger, "openrouter"), "paid")
        job["state"] = "queued"
        with self.assertRaisesRegex(ValueError, "missing explicit"):
            self.ledger.save("test-tamper")

    def test_one_correction_survives_restart_and_paid_correction_waits(self):
        parent = new_job(self.ledger, request(self.ledger), "initial")
        corrective = new_job(self.ledger, request(self.ledger, "openrouter"), "correction", correction_of=parent["id"])
        self.ledger.save("test-correction")
        ledger = Ledger(self.project)
        self.assertEqual("awaiting_confirmation", corrective["state"])
        with self.assertRaisesRegex(ValueError, "one corrective"):
            new_job(ledger, request(ledger), "again", correction_of=parent["id"])
        with self.assertRaisesRegex(ValueError, "one corrective"):
            new_job(ledger, request(ledger), "chain", correction_of=corrective["id"])

    def test_job_inputs_cannot_be_changed_in_saved_manifest(self):
        job = new_job(self.ledger, request(self.ledger), "one")
        job["request"]["prompt"] = "A different request"
        with self.assertRaisesRegex(ValueError, "frozen"):
            self.ledger.save("test-change")

    def saved_image(self):
        path = self.ledger.root / "previews/ai-image.png"
        path.write_bytes(b"synthetic media identity fixture")
        beat = self.ledger.data["ai"]["beats"]["beat-1"]
        version = {
            "id": "image-1",
            "beat": "beat-1",
            "kind": "image",
            "alternative": "option-2",
            "path": "previews/ai-image.png",
            "sha256": digest(path),
            "inputs": beat["fingerprint"],
            "approval": {"state": "pending"},
        }
        self.ledger.data["ai"]["versions"][version["id"]] = version
        self.ledger.save("test-image")
        return version, path

    def test_selecting_description_is_not_still_approval(self):
        select(self.ledger, {"beat": "beat-1", "alternative": "option-2"})
        version, _path = self.saved_image()
        with self.assertRaisesRegex(ValueError, "Approve this exact"):
            checked_version(self.ledger, version["id"], approved=True, kind="image")

    def test_approval_is_bound_to_actual_bytes_and_displayed_version(self):
        version, path = self.saved_image()
        review(
            self.ledger,
            {"version": version["id"], "signature": version_signature(version), "decision": "approved", "by": "Editor"},
        )
        checked_version(self.ledger, version["id"], approved=True)
        path.write_bytes(b"changed media")
        with self.assertRaisesRegex(ValueError, "media changed"):
            checked_version(Ledger(self.project), version["id"], approved=True)

    def test_version_metadata_tampering_invalidates_approval(self):
        version, _path = self.saved_image()
        review(
            self.ledger,
            {"version": version["id"], "signature": version_signature(version), "decision": "approved", "by": "Editor"},
        )
        version["sha256"] = fingerprint("other bytes")
        with self.assertRaisesRegex(ValueError, "approved version changed"):
            self.ledger.save("test-tamper")

    def test_public_job_sanitizes_secrets_signed_urls_and_absolute_paths(self):
        home = str(__import__("pathlib").Path.home())
        job = {
            "id": "job-1",
            "state": "failed",
            "submit_outcome": "accepted",
            "request": {"beat": "beat-1", "alternative": "option-2", "kind": "image", "route": "gpt-subscription"},
            "result": None,
            "remote": {"threadId": "thr", "turnId": "turn"},
            "error": {
                "message": (
                    f"failed at {home}\\ai-work\\job-1\\still.png "
                    "https://example.com/still.png?X-Amz-Signature=abcdef123 "
                    "OPENAI_API_KEY=sk-secret token=abcd"
                )
            },
        }
        public = public_job(job)
        blob = json.dumps(public)
        self.assertNotIn(home, blob)
        self.assertNotIn("sk-secret", blob)
        self.assertNotIn("abcdef123", blob.lower())
        self.assertNotIn("still.png", blob)
        self.assertIsNone(public["remote"].get("turnId") if public["remote"] else None)
        self.assertEqual("thr", public["remote"]["threadId"])

    def test_comparison_group_reuses_identity_and_confirms_only_as_a_full_set(self):
        from getbrolls.ai_state import confirm, launch_comparison

        with self.assertRaisesRegex(ValueError, "images mode"):
            launch_comparison(self.ledger, {"beat": "beat-1", "outputs": 3}, "cmp-1")
        self.assertFalse(self.ledger.data["ai"]["jobs"])
        select(self.ledger, {"beat": "beat-1", "alternative": "option-1", "mode": "images", "comment": "No people"})
        launched = launch_comparison(self.ledger, {"beat": "beat-1", "outputs": 3}, "cmp-1")
        jobs = launched["jobs"]
        self.assertEqual(["option-1", "option-2", "option-3"], [job["request"]["alternative"] for job in jobs])
        self.assertEqual({1, 2, 3}, {job["request"]["slot"] for job in jobs})
        self.assertTrue(all(job["request"]["group"] == launched["group"]["id"] for job in jobs))
        self.assertTrue(all(job["request"]["quality"] == "agreed" for job in jobs))
        self.assertTrue(all(job["state"] == "queued" and job["submit_outcome"] == "not_sent" for job in jobs))
        self.ledger.save("ai-generate-comparison")
        again = launch_comparison(Ledger(self.project), {"beat": "beat-1", "outputs": 3}, "cmp-1")
        self.assertEqual([job["id"] for job in jobs], [job["id"] for job in again["jobs"]])
        select(self.ledger, {"beat": "beat-1", "comment": "Changed direction", "mode": "images"})
        with self.assertRaisesRegex(ValueError, "different frozen"):
            launch_comparison(self.ledger, {"beat": "beat-1", "outputs": 3}, "cmp-1")
        self.assertEqual(3, len(self.ledger.data["ai"]["jobs"]))
        paid = launch_comparison(self.ledger, {"beat": "beat-1", "outputs": 3, "route": "openrouter"}, "paid-cmp")
        self.assertTrue(all(job["state"] == "awaiting_confirmation" for job in paid["jobs"]))
        with self.assertRaisesRegex(ValueError, "every still"):
            confirm(
                self.ledger,
                [paid["jobs"][0]["id"]],
                {paid["jobs"][0]["id"]: paid["jobs"][0]["fingerprint"]},
                "Editor",
            )
        self.assertTrue(all(job["state"] == "awaiting_confirmation" for job in paid["jobs"]))
        signatures = {job["id"]: job["fingerprint"] for job in paid["jobs"]}
        confirm(self.ledger, list(signatures), signatures, "Editor")
        self.assertTrue(all(job["state"] == "queued" and job["submit_outcome"] == "not_sent" for job in paid["jobs"]))

    def test_stale_timing_flag_does_not_advertise_video(self):
        from getbrolls.ai import public_board

        beat = self.ledger.data["ai"]["beats"]["beat-1"]
        beat["timing"] = {
            "readiness": {"resolved": True},
            "analysis_id": "missing-analysis",
            "match": {"state": "resolved"},
        }
        row = next(item for item in public_board(self.ledger)["beats"] if item["id"] == "beat-1")
        self.assertFalse(row["video_ready"])
        self.assertFalse(row["timing"]["resolved"])
        self.assertNotEqual(["resolved"], row["timing"]["reasons"])

    def test_board_focus_matches_the_selected_comparison_still(self):
        from getbrolls.ai import public_board, storyboard_section
        from getbrolls.ai_state import launch_comparison

        select(
            self.ledger,
            {"beat": "beat-1", "mode": "images", "alternative": "option-2", "comment": "No people"},
        )
        launched = launch_comparison(self.ledger, {"beat": "beat-1", "outputs": 3}, "cmp-focus")
        ai = self.ledger.data["ai"]
        for job in launched["jobs"]:
            alternative = job["request"]["alternative"]
            version_id = "still-" + alternative
            version = {
                "id": version_id,
                "beat": "beat-1",
                "kind": "image",
                "path": "previews/ai-" + version_id + ".png",
                "sha256": "ab" * 32,
                "inputs": job["request"]["inputs"],
                "job": job["id"],
                "alternative": alternative,
                "approval": {"state": "approved" if alternative == "option-2" else "pending"},
            }
            ai["versions"][version_id] = version
            job["state"] = "complete"
            job["result"] = version_id
        row = next(item for item in public_board(self.ledger)["beats"] if item["id"] == "beat-1")
        self.assertEqual("still-option-2", row["version"]["id"])
        self.assertEqual("approved", row["version"]["approval"])
        page = storyboard_section(self.ledger)
        self.assertIn('data-ai-version="still-option-2"', page)
        self.assertIn('data-ai-approval="approved"', page)
        self.assertIn('data-ai-slot="option-1"', page)
        self.assertIn('data-ai-approval="pending"', page)

    def test_deleted_or_changed_still_is_not_video_ready(self):
        from unittest.mock import patch

        from getbrolls.ai import _video_ready, public_board

        preview = self.ledger.root / "previews" / "ai-still-test.png"
        preview.parent.mkdir(parents=True, exist_ok=True)
        preview.write_bytes(b"png-bytes")
        sha = digest(preview)
        version = {
            "id": "still-test",
            "kind": "image",
            "beat": "beat-1",
            "inputs": self.ledger.data["ai"]["beats"]["beat-1"]["fingerprint"],
            "path": "previews/ai-still-test.png",
            "sha256": sha,
            "approval": {"state": "approved"},
        }
        beat = self.ledger.data["ai"]["beats"]["beat-1"]
        beat["timing"] = {
            "readiness": {"resolved": True, "reasons": []},
            "match": {"state": "resolved"},
            "analysis_id": "missing-analysis",
            "still": {"id": "still-test", "sha256": sha},
        }
        versions = {"still-test": version}
        ready = {"resolved": True, "reasons": [], "timing": {"start_s": 0, "end_s": 1}}
        with patch("getbrolls.ai_timing.current_readiness", return_value=ready):
            self.assertTrue(_video_ready(self.ledger, beat, versions))
            preview.write_bytes(b"changed")
            self.assertFalse(_video_ready(self.ledger, beat, versions))
            preview.unlink()
            self.assertFalse(_video_ready(self.ledger, beat, versions))
        row = next(item for item in public_board(self.ledger)["beats"] if item["id"] == "beat-1")
        self.assertFalse(row["video_ready"])
        self.assertFalse(row["timing"]["resolved"])
