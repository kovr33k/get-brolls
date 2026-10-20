"""Public CLI and authenticated Storyboard workflow with a synthetic native peer."""

import json
import os
import re
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import _isolation  # noqa: F401
from _media import skip_unless_ffmpeg
from _paths import CLI

from getbrolls import serve
from getbrolls.ledger import Ledger
from getbrolls.runtime import project_lock

PEER = Path(__file__).parent / "fixtures/ai_app_server.py"


@skip_unless_ffmpeg
class AIWorkflowTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.project = Path(self.temp.name) / "project"
        self.env = {
            **os.environ,
            "GETBROLLS_CODEX_APP_SERVER": str(PEER),
            "GETBROLLS_AI_FIXTURE": "success",
            "GETBROLLS_AI_INLINE": "1",
            # Successful workflows include subprocess startup and durable ledger writes on Windows.
            "GETBROLLS_AI_TIMEOUT": "8",
            "CODEX_HOME": str(Path(self.temp.name) / "native-home"),
        }
        self.call("init-rules")
        plan = {
            "scenario": "A resource runs out. People wait.",
            "style": "Restrained editorial illustration.",
            "beats": [
                {
                    "id": "scarcity",
                    "route": "ai",
                    "text": "A resource runs out.",
                    "purpose": "Explain scarcity.",
                    "alternatives": ["An empty reservoir", "A final drop", "An empty warehouse"],
                },
                {"id": "people", "route": "broll", "text": "People wait."},
            ],
        }
        self.plan = Path(self.temp.name) / "plan.json"
        self.plan.write_text(json.dumps(plan), encoding="utf-8")
        self.call("ai-plan", "--file", self.plan)

    def call(self, command, *args, ok=True, project=None, timeout=15):
        result = subprocess.run(
            [sys.executable, str(CLI), command, "--project", str(project or self.project), *map(str, args)],
            capture_output=True,
            text=True,
            encoding="utf-8",
            env=self.env,
            check=False,
            timeout=timeout,
        )
        self.assertEqual(0 if ok else 2, result.returncode, result.stderr)
        return json.loads(result.stdout if ok else result.stderr)

    def ai(self):
        return Ledger(self.project, recover=False).data["ai"]

    def select(self):
        return self.call("ai-select", "--beat", "scarcity", "--alternative", "option-2", "--comment", "No lettering")

    def launch(self, nonce="launch-1"):
        return self.call("ai-generate-still", "--beat", "scarcity", "--request-id", nonce)

    def turn_count(self):
        counts = (self.project / "brolls/ai-work").glob("*/turn-start-count.txt")
        return sum(int(path.read_text()) for path in counts)

    def test_plan_selection_reopen_and_read_only_status_never_start_provider(self):
        self.select()
        review_result = self.call("review")
        self.assertNotIn("EMPTY_STORYBOARD", json.dumps(review_result.get("warnings", [])))
        stored = self.ai()
        self.assertEqual("economy", stored["beats"]["scarcity"]["mode"])
        self.assertEqual(3, len(stored["beats"]["scarcity"]["alternatives"]))
        self.assertEqual("option-2", stored["beats"]["scarcity"]["selected"])
        self.assertEqual("No lettering", stored["beats"]["scarcity"]["comment"])
        self.assertFalse(stored["jobs"])
        self.assertEqual(0, self.turn_count())
        manifest = self.project / "brolls/manifest.json"
        before = manifest.read_bytes()
        with project_lock(self.project):
            status_result = self.call("status")
        self.assertFalse(status_result.get("warnings"))
        self.assertEqual(before, manifest.read_bytes())
        absent = Path(self.temp.name) / "absent"
        self.call("status", project=absent, ok=False)
        self.assertFalse(absent.exists())

    def test_explicit_launch_duplicate_and_exact_review_use_actual_saved_image(self):
        self.select()
        first = self.launch()
        self.assertEqual("complete", first["job"]["state"], first)
        again = self.launch()
        self.assertEqual(first["job"]["id"], again["job"]["id"])
        self.assertEqual(1, self.turn_count())
        stored = self.ai()
        self.assertEqual(1, len(stored["versions"]))
        version = next(iter(stored["versions"].values()))
        self.assertEqual("pending", version["approval"]["state"])
        self.assertGreater(version["width"], 0)
        self.assertTrue((self.project / "brolls" / version["path"]).is_file())
        self.call("ai-approve", "--version", version["id"], "--decision", "approved", "--by", "Test editor")
        self.assertEqual("approved", self.ai()["versions"][version["id"]]["approval"]["state"])
        self.launch()
        self.assertEqual(1, self.turn_count())
        self.assertEqual("approved", self.ai()["versions"][version["id"]]["approval"]["state"])

    def test_background_comparison_finishes_all_three_jobs_with_one_turn_each(self):
        self.call("ai-select", "--beat", "scarcity", "--mode", "images")
        self.env.pop("GETBROLLS_AI_INLINE")
        launched = self.call("ai-generate-comparison", "--beat", "scarcity", "--request-id", "background-three")
        ids = [job["id"] for job in launched["jobs"]]
        deadline = time.monotonic() + 20
        while True:
            jobs = [self.ai()["jobs"][key] for key in ids]
            if all(job["state"] == "complete" for job in jobs) or time.monotonic() >= deadline:
                break
            time.sleep(0.1)
        self.assertEqual(["complete"] * 3, [job["state"] for job in jobs], jobs)
        self.assertEqual(3, len(self.ai()["versions"]))
        self.assertEqual(3, self.turn_count())

    def test_unknown_submit_survives_restart_without_second_native_turn(self):
        self.select()
        self.env["GETBROLLS_AI_FIXTURE"] = "lost_ack"
        self.env["GETBROLLS_AI_TIMEOUT"] = "1"
        launched = self.launch()
        self.assertEqual("unknown", launched["job"]["state"], launched)
        self.env["GETBROLLS_AI_FIXTURE"] = "success"
        resumed = self.call("ai-resume", "--job", launched["job"]["id"])
        self.assertEqual("unknown", resumed["job"]["state"])
        self.launch()
        self.assertEqual(1, self.turn_count())
        self.assertFalse(self.ai()["versions"])

    def test_native_large_result_is_retained_from_codex_home(self):
        self.select()
        self.env["GETBROLLS_AI_FIXTURE"] = "large_external_image"
        launched = self.launch()
        self.assertEqual("complete", launched["job"]["state"], launched)
        version = self.ai()["versions"][launched["job"]["result"]]
        original = Path(self.env["CODEX_HOME"]) / "generated_images/thr_getbrolls_test/item_image.png"
        self.assertGreater(original.stat().st_size, 1_048_576)
        self.assertEqual(original.read_bytes(), (self.project / "brolls" / version["path"]).read_bytes())
        self.assertEqual(1, self.turn_count())

    def test_native_saved_history_recovers_unknown_without_a_new_turn(self):
        self.select()
        self.env["GETBROLLS_AI_FIXTURE"] = "lost_image_result"
        self.env["GETBROLLS_AI_TIMEOUT"] = "1"
        launched = self.launch()
        self.assertEqual("unknown", launched["job"]["state"])
        self.env["GETBROLLS_AI_FIXTURE"] = "success"
        self.env["GETBROLLS_AI_TIMEOUT"] = "8"
        resumed = self.call("ai-resume", "--job", launched["job"]["id"])
        self.assertEqual("complete", resumed["job"]["state"], resumed)
        self.assertFalse(resumed["resubmitted"])
        self.assertEqual(1, self.turn_count())
        self.assertEqual(1, len(self.ai()["jobs"]))
        self.assertEqual(0, resumed["job"]["correction_count"])

    def test_gpt_local_handoff_recovers_after_interruption_without_another_native_turn(self):
        self.select()
        self.env["GETBROLLS_AI_TEST_CRASH"] = "artifact"
        launched = self.launch()
        self.assertEqual("downloading", launched["job"]["state"], launched)
        self.env.pop("GETBROLLS_AI_TEST_CRASH")
        self.call("review")
        resumed = self.call("ai-resume", "--job", launched["job"]["id"])
        self.assertEqual("complete", resumed["job"]["state"], resumed)
        self.assertEqual(1, self.turn_count())
        self.assertEqual(0, resumed["job"]["correction_count"])

    def test_portable_exact_still_review_import_checks_signature_and_media_bytes(self):
        self.env["GETBROLLS_AI_FIXTURE"] = "slow_ack"
        self.select()
        launched = self.launch()
        self.assertEqual("complete", launched["job"]["state"], launched)
        self.call("review")
        page = (self.project / "brolls/review.html").read_text(encoding="utf-8")
        match = re.search(r"window.GETBROLLS_REVIEW=(.*?);</script>", page)
        self.assertIsNotNone(match)
        assert match is not None
        payload = json.loads(match.group(1))
        row = payload["ai"][0]
        row.update(state="changes", decision="changes", comment="Synthetic offline review")
        exported = Path(self.temp.name) / "review.json"
        exported.write_text(json.dumps(payload), encoding="utf-8")
        result = self.call("import-review", "--file", exported, "--by", "Test editor")
        self.assertEqual(1, result["ai_imported"])
        self.assertEqual("changes", self.ai()["versions"][row["version"]]["approval"]["state"])
        replay = self.call("import-review", "--file", exported, "--by", "Test editor")
        self.assertEqual([row["version"]], replay["unchanged"])
        row.update(state="approved", decision="approved", signature="0" * 64)
        exported.write_text(json.dumps(payload), encoding="utf-8")
        self.call("import-review", "--file", exported, "--by", "Test editor", ok=False)
        self.assertEqual("changes", self.ai()["versions"][row["version"]]["approval"]["state"])
        version = self.ai()["versions"][row["version"]]
        (self.project / "brolls" / version["path"]).write_bytes(b"changed synthetic media")
        row["signature"] = version["approval"]["signature"]
        exported.write_text(json.dumps(payload), encoding="utf-8")
        self.call("import-review", "--file", exported, "--by", "Test editor", ok=False)
        self.assertEqual("changes", self.ai()["versions"][row["version"]]["approval"]["state"])
        self.assertEqual(1, self.turn_count())

    def start_server(self):
        self.call("review")
        server, port = serve.start(self.project, port=0)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(thread.join, 2)
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        self.base = f"http://127.0.0.1:{port}"
        token = server.save_token
        assert isinstance(token, str) and token
        self.token = token

    def http(self, path, data=None, *, token=True):
        headers = {"Content-Type": "application/json"}
        if token:
            headers[serve.TOKEN_HEADER] = self.token
        raw = json.dumps(data).encode() if data is not None else None
        request = Request(self.base + path, data=raw, headers=headers)
        try:
            with urlopen(request, timeout=10) as response:
                return response.status, response.read()
        except HTTPError as exc:
            with exc:
                return exc.code, exc.read()

    def test_local_server_rejects_unauthenticated_mutation_and_state(self):
        self.start_server()
        before = (self.project / "brolls/manifest.json").read_bytes()
        for path, data in (
            ("/__ai/state", None),
            ("/__ai", {"action": "generate", "beat": "scarcity", "nonce": "bad"}),
        ):
            status, _body = self.http(path, data, token=False)
            self.assertEqual(403, status)
        self.assertEqual(before, (self.project / "brolls/manifest.json").read_bytes())
        self.assertEqual(0, self.turn_count())
        status, raw = self.http(
            "/__ai", {"action": "select", "beat": "scarcity", "alternative": "option-3", "comment": "Wide view"}
        )
        self.assertEqual(200, status, raw)
        status, raw = self.http("/__ai/state")
        self.assertEqual(200, status, raw)
        state = json.loads(raw)
        self.assertEqual("option-3", state["beats"][0]["selected"])
        self.assertFalse(state["jobs"])
        self.assertEqual(0, self.turn_count())

    def test_http_generation_and_exact_review_reject_stale_context(self):
        self.env["GETBROLLS_AI_FIXTURE"] = "slow_ack"
        self.start_server()
        expected = self.ai()["beats"]["scarcity"]["fingerprint"]
        payload = {
            "action": "generate",
            "beat": "scarcity",
            "expected": expected,
            "alternative": "option-2",
            "comment": "No lettering",
            "nonce": "http-launch",
        }
        with patch.dict(os.environ, self.env):
            status, raw = self.http("/__ai", payload)
            self.assertEqual(200, status, raw)
            self.assertEqual("complete", json.loads(raw)["job"]["state"], raw)
            self.assertEqual(200, self.http("/__ai", payload)[0])
        self.assertEqual(1, self.turn_count())
        state = json.loads(self.http("/__ai/state")[1])
        version = state["beats"][0]["version"]
        decision = {
            "action": "review",
            "version": version["id"],
            "signature": "0" * 64,
            "decision": "approved",
            "by": "Test editor",
        }
        self.assertEqual(400, self.http("/__ai", decision)[0])
        decision["signature"] = version["signature"]
        self.assertEqual(200, self.http("/__ai", decision)[0])
        payload.update(expected="0" * 64, nonce="stale-launch")
        self.assertEqual(400, self.http("/__ai", payload)[0])
        self.assertEqual(1, self.turn_count())

    def _image_bytes(self):
        stored = self.ai()
        found = {}
        for job in stored["jobs"].values():
            if (job.get("request") or {}).get("kind") != "image" or not job.get("result"):
                continue
            version = stored["versions"][job["result"]]
            found[job["request"]["alternative"]] = (self.project / "brolls" / version["path"]).read_bytes()
        return found

    def test_explicit_comparison_launches_three_distinct_stills_without_hidden_replay(self):
        self.call("ai-generate-comparison", "--beat", "scarcity", "--request-id", "cmp-1", ok=False, timeout=30)
        self.assertFalse(self.ai()["jobs"])
        self.assertEqual(0, self.turn_count())
        self.call(
            "ai-select",
            "--beat",
            "scarcity",
            "--mode",
            "images",
            "--alternative",
            "option-2",
            "--comment",
            "No lettering",
        )
        self.assertFalse(self.ai()["jobs"])
        self.assertEqual(0, self.turn_count())
        first = self.call("ai-generate-comparison", "--beat", "scarcity", "--request-id", "cmp-1", timeout=45)
        self.assertEqual(3, len(first["jobs"]))
        self.assertTrue(all(job["state"] == "complete" for job in first["jobs"]))
        self.assertEqual(["option-1", "option-2", "option-3"], [job["alternative"] for job in first["jobs"]])
        blobs = self._image_bytes()
        self.assertEqual({"option-1", "option-2", "option-3"}, set(blobs))
        self.assertTrue(all(blob.startswith(b"\x89PNG") for blob in blobs.values()))
        self.assertEqual(3, len(set(blobs.values())))
        self.assertEqual(3, self.turn_count())
        again = self.call("ai-generate-comparison", "--beat", "scarcity", "--request-id", "cmp-1", timeout=30)
        self.assertEqual([job["id"] for job in first["jobs"]], [job["id"] for job in again["jobs"]])
        self.assertEqual(first["group"], again["group"])
        self.assertEqual(3, self.turn_count())
        self.call("ai-select", "--beat", "scarcity", "--comment", "A different note")
        self.call("ai-generate-comparison", "--beat", "scarcity", "--request-id", "cmp-1", ok=False, timeout=30)
        self.assertEqual(3, len(self.ai()["jobs"]))
        self.assertEqual(3, len(self.ai()["versions"]))
        self.assertEqual(3, self.turn_count())
        self.call("review")
        page = (self.project / "brolls/review.html").read_text(encoding="utf-8")
        self.assertEqual(3, page.count('class="ai-slot"'))
        self.assertIn("Generate three stills", page)
        self.assertIn('data-ai-route="broll"', page)
        self.assertTrue(all(version["approval"]["state"] == "pending" for version in self.ai()["versions"].values()))
        self.assertFalse(any((job.get("request") or {}).get("kind") == "video" for job in self.ai()["jobs"].values()))

    def test_comparison_failure_and_unknown_leave_siblings_untouched(self):
        self.call("ai-select", "--beat", "scarcity", "--mode", "images", "--alternative", "option-1")
        self.env["GETBROLLS_AI_FAIL_IF_PROMPT_CONTAINS"] = "empty warehouse"
        failed = self.call("ai-generate-comparison", "--beat", "scarcity", "--request-id", "cmp-fail", timeout=45)
        by_alt = {job["alternative"]: job["state"] for job in failed["jobs"]}
        self.assertEqual({"option-1": "complete", "option-2": "complete", "option-3": "failed"}, by_alt)
        self.assertEqual({"option-1", "option-2"}, set(self._image_bytes()))
        self.assertEqual(2, len(set(self._image_bytes().values())))
        self.call("ai-select", "--beat", "scarcity", "--mode", "economy")
        self.assertEqual(2, len(self.ai()["versions"]))
        self.assertEqual(3, len(self.ai()["jobs"]))
        self.call("ai-select", "--beat", "scarcity", "--mode", "images")
        again = self.call("ai-generate-comparison", "--beat", "scarcity", "--request-id", "cmp-fail", timeout=30)
        self.assertEqual([job["id"] for job in failed["jobs"]], [job["id"] for job in again["jobs"]])
        self.assertEqual(3, self.turn_count())
        self.env.pop("GETBROLLS_AI_FAIL_IF_PROMPT_CONTAINS")
        self.env["GETBROLLS_AI_UNKNOWN_IF_PROMPT_CONTAINS"] = "A final drop"
        unknown = self.call("ai-generate-comparison", "--beat", "scarcity", "--request-id", "cmp-unknown", timeout=45)
        unknown_job = next(job for job in unknown["jobs"] if job["alternative"] == "option-2")
        self.assertEqual("unknown", unknown_job["state"])
        self.assertEqual(
            {"complete", "unknown"},
            {job["state"] for job in unknown["jobs"]},
        )
        self.env.pop("GETBROLLS_AI_UNKNOWN_IF_PROMPT_CONTAINS")
        self.env["GETBROLLS_AI_FIXTURE"] = "success"
        resumed = self.call("ai-resume", "--job", unknown_job["id"])
        self.assertEqual("unknown", resumed["job"]["state"])
        self.assertFalse(resumed["resubmitted"])
        self.assertEqual(6, self.turn_count())
        self.assertEqual(6, len(self.ai()["jobs"]))

    def test_http_comparison_exposes_slots_and_selection_does_not_approve(self):
        self.start_server()
        self.call(
            "ai-select",
            "--beat",
            "scarcity",
            "--mode",
            "images",
            "--alternative",
            "option-1",
            "--comment",
            "No lettering",
        )
        expected = self.ai()["beats"]["scarcity"]["fingerprint"]
        refused, _body = self.http(
            "/__ai",
            {
                "action": "generate",
                "beat": "scarcity",
                "expected": expected,
                "outputs": 3,
                "nonce": "paid-http",
                "route": "openrouter",
            },
        )
        self.assertEqual(400, refused)
        self.assertFalse(self.ai()["jobs"])
        payload = {
            "action": "generate",
            "beat": "scarcity",
            "expected": expected,
            "outputs": 3,
            "nonce": "http-cmp",
            "comment": "No lettering",
        }
        with patch.dict(os.environ, self.env):
            status, raw = self.http("/__ai", payload)
        self.assertEqual(200, status, raw)
        body = json.loads(raw)
        self.assertEqual(3, len(body["jobs"]))
        self.assertTrue(all(job["state"] == "complete" for job in body["jobs"]))
        with patch.dict(os.environ, self.env):
            self.assertEqual(200, self.http("/__ai", payload)[0])
        self.assertEqual(3, self.turn_count())
        state = json.loads(self.http("/__ai/state")[1])
        beat = next(row for row in state["beats"] if row["id"] == "scarcity")
        self.assertEqual(3, len(beat["slots"]))
        self.assertTrue(all(slot["comment"] == "No lettering" for slot in beat["slots"]))
        hashes = [slot["version"]["sha256"] for slot in beat["slots"]]
        paths = [slot["version"]["path"] for slot in beat["slots"]]
        self.assertEqual(3, len(set(hashes)))
        self.assertEqual(3, len(set(paths)))
        self.assertTrue(all(path.startswith("previews/") for path in paths))
        chosen = beat["slots"][1]
        status, raw = self.http(
            "/__ai",
            {"action": "select", "beat": "scarcity", "alternative": chosen["alternative"], "expected": expected},
        )
        self.assertEqual(200, status, raw)
        self.assertEqual(3, len(self.ai()["versions"]))
        self.assertTrue(all(version["approval"]["state"] == "pending" for version in self.ai()["versions"].values()))
        decision = {
            "action": "review",
            "version": chosen["version"]["id"],
            "signature": chosen["version"]["signature"],
            "decision": "approved",
            "by": "Test editor",
            "comment": "Chosen slot review note",
        }
        self.assertEqual(200, self.http("/__ai", decision)[0])
        approved = [version for version in self.ai()["versions"].values() if version["approval"]["state"] == "approved"]
        self.assertEqual([chosen["version"]["id"]], [version["id"] for version in approved])
        refreshed = json.loads(self.http("/__ai/state")[1])
        slots = next(row for row in refreshed["beats"] if row["id"] == "scarcity")["slots"]
        for slot in slots:
            expected_comment = (
                "Chosen slot review note" if slot["alternative"] == chosen["alternative"] else "No lettering"
            )
            self.assertEqual(expected_comment, slot["comment"])
        self.assertEqual(3, len(self.ai()["versions"]))
        self.assertFalse(any((job.get("request") or {}).get("kind") == "video" for job in self.ai()["jobs"].values()))
