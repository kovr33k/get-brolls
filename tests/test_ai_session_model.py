"""Explicit native session choice is frozen; it never rewrites global Codex settings."""

import copy
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import _isolation  # noqa: F401
import _paths  # noqa: F401

from getbrolls import ai
from getbrolls.ai_state import import_plan, launch_comparison, launch_still, public_job, select
from getbrolls.ledger import Ledger


class NativeSessionModelTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.project = Path(self.temp.name)
        self.ledger = Ledger(self.project)
        self.plan = {
            "scenario": "The reserve runs out.",
            "style": "Restrained illustration",
            "still_provider": {"route": "gpt-subscription", "session_model": "fixture-session-model"},
            "beats": [
                {
                    "id": "reserve",
                    "route": "ai",
                    "text": "The reserve runs out.",
                    "purpose": "Show a limited reserve",
                    "alternatives": ["An empty reservoir", "An empty warehouse", "The final drop"],
                }
            ],
        }
        import_plan(self.ledger, self.plan)
        select(self.ledger, {"beat": "reserve", "alternative": "option-1"})

    def test_economy_freezes_explicit_session_model(self):
        still = launch_still(self.ledger, {"beat": "reserve"}, "economy-once")
        self.assertEqual("fixture-session-model", still["request"].get("session_model"))
        self.assertNotIn("model", still["request"])
        self.assertEqual("fixture-session-model", public_job(still)["session_model"])
        self.assertIn("Stills: GPT subscription · session fixture-session-model", ai.storyboard_section(self.ledger))

    def test_apply_freezes_explicit_session_model(self):
        applied = ai._launch_apply(
            self.ledger, {"beat": "reserve", "instruction": "Use a higher camera angle."}, "apply-once", "apply"
        )
        self.assertEqual("fixture-session-model", applied["request"].get("session_model"))
        self.assertEqual("gpt-subscription", applied["request"]["route"])
        self.assertNotIn("model", applied["request"])

    def test_comparison_scope_and_children_keep_choice_and_refuse_changed_replay(self):
        select(self.ledger, {"beat": "reserve", "mode": "images"})
        group = launch_comparison(self.ledger, {"beat": "reserve", "outputs": 3}, "compare-once")
        self.assertEqual("fixture-session-model", group["group"]["scope"].get("session_model"))
        self.assertEqual(["fixture-session-model"] * 3, [job["request"].get("session_model") for job in group["jobs"]])
        original = copy.deepcopy(group)
        self.plan["still_provider"]["session_model"] = "fixture-other-model"
        import_plan(self.ledger, self.plan)
        with self.assertRaisesRegex(ValueError, "frozen inputs"):
            launch_comparison(self.ledger, {"beat": "reserve", "outputs": 3}, "compare-once")
        self.assertEqual(original, group)

    def test_worker_uses_frozen_choice_after_project_setup_changes(self):
        job = launch_still(self.ledger, {"beat": "reserve"}, "worker-once")
        self.ledger.save("test-freeze")
        self.plan["still_provider"]["session_model"] = "fixture-other-model"
        import_plan(self.ledger, self.plan)
        with patch(
            "getbrolls.ai.generate_still", return_value={"status": "unsupported", "error": "fixture stop"}
        ) as run:
            ai._produce_worker(self.project, job["id"])
        self.assertEqual("fixture-session-model", run.call_args.kwargs.get("session_model"))
        self.assertEqual(1, run.call_count)

    def test_invalid_or_other_route_session_choices_are_refused_before_save(self):
        for value in ("", "a b", "https://example.invalid/model", 3, "a" * 201):
            with self.subTest(value=value):
                self.plan["still_provider"] = {"route": "gpt-subscription", "session_model": value}
                with self.assertRaises(ValueError):
                    import_plan(self.ledger, self.plan)
        self.plan["still_provider"] = {
            "route": "grok-subscription",
            "model": "grok-imagine-image-quality",
            "session_model": "fixture-session-model",
        }
        with self.assertRaises(ValueError):
            import_plan(self.ledger, self.plan)
