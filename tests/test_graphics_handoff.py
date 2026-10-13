"""Scene recovery is durable; observed host delegation is a separate acceptance gate."""

import json
import tempfile
import unittest
from pathlib import Path

import _isolation  # noqa: F401
from _cli import run_cli
from _media import skip_unless_ffmpeg
from test_graphics_review import ENV, _assign, _project, _render, _review_payload, _write_review
from test_status import snapshot

from getbrolls.ledger import Ledger


@skip_unless_ffmpeg
class HandoffTests(unittest.TestCase):
    def test_packet_restores_inputs_without_launching_or_rendering(self):
        with tempfile.TemporaryDirectory() as tmp:
            _project(tmp)
            _assign(tmp)
            root = Path(tmp) / "brolls"
            first = run_cli("graphics-handoff", "--occurrence", "stat-01", project=tmp)
            packet = json.loads((root / first["packet_ref"]).read_text(encoding="utf-8"))
            self.assertEqual(0, first["agents_launched"])
            self.assertFalse(packet["delegation_observed"])
            self.assertIsNone(packet["host_context"])
            self.assertEqual("The count stands at twelve units.", packet["occurrence"]["narration"])
            self.assertEqual(2, packet["work"]["repair_limit"])
            self.assertEqual({}, packet["versions"])
            before = (root / first["packet_ref"]).read_bytes()
            second = run_cli(
                "graphics-handoff", "--occurrence", "stat-01", "--host-context", "Synthetic label only", project=tmp
            )
            self.assertNotEqual(first["packet_ref"], second["packet_ref"])
            self.assertEqual(before, (root / first["packet_ref"]).read_bytes())
            state = Ledger(tmp, recover=False).data["graphics"]
            self.assertEqual({}, state["versions"])
            self.assertEqual(2, len(state["occurrences"]["stat-01"]["work"]["checkpoints"]))
            prior = snapshot(root)
            run_cli("status", project=tmp)
            after = snapshot(root)
            prior.pop("getbrolls.log", None)
            after.pop("getbrolls.log", None)
            self.assertEqual(prior, after)

    def test_request_retains_exact_context_and_refuses_replay_or_retarget(self):
        with tempfile.TemporaryDirectory() as tmp:
            _project(tmp)
            _assign(tmp)
            _render(tmp)
            payload = _review_payload(tmp)
            payload["graphics"][0].update(state="changes", comment="Synthetic local title revision")
            review_file = _write_review(tmp, payload)
            run_cli("import-review", "--file", str(review_file), "--by", "Synthetic reviewer", project=tmp)
            request = Ledger(tmp, recover=False).data["graphics"]["requests"][0]
            result = run_cli("graphics-handoff", "--occurrence", "stat-01", "--request", request["id"], project=tmp)
            packet = json.loads((Path(tmp) / "brolls" / result["packet_ref"]).read_text(encoding="utf-8"))
            self.assertEqual(request, packet["revision_request"])
            self.assertIn("v1", packet["versions"])
            _assign(tmp, narration="A revised synthetic count.")
            run_cli("graphics-continue", project=tmp, env=ENV)
            refused = run_cli(
                "graphics-handoff", "--occurrence", "stat-01", "--request", request["id"], project=tmp, expect=2
            )
            self.assertIn("reviewed version", json.dumps(refused))
            run_cli(
                "graphics-request-complete",
                "--request",
                request["id"],
                "--version",
                "v2",
                "--outcome",
                "Synthetic revision done",
                project=tmp,
            )
            refused = run_cli(
                "graphics-handoff", "--occurrence", "stat-01", "--request", request["id"], project=tmp, expect=2
            )
            self.assertIn("replay", json.dumps(refused))
