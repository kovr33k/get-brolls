"""Authenticated loopback transfers exercise actual private reference media."""

import hashlib
import http.client
import json
import os
import socket
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch
from urllib.parse import quote

import _isolation  # noqa: F401
import _paths  # noqa: F401
from _media import skip_unless_ffmpeg, synth_image
from test_ai_references import _BLUE_END, _BLUE_START, _mean, _two_tone, plan

from getbrolls import serve
from getbrolls.ai_references import MAX_VIDEO_BYTES
from getbrolls.ai_state import import_plan, select
from getbrolls.ledger import Ledger
from getbrolls.runtime import project_lock

NATIVE_ENV = {
    "GETBROLLS_CODEX_APP_SERVER": str(Path(__file__).parent / "fixtures/ai_app_server.py"),
    "GETBROLLS_AI_FIXTURE": "success",
    "GETBROLLS_AI_INLINE": "1",
    "GETBROLLS_AI_TIMEOUT": "8",
}


@skip_unless_ffmpeg
class ReferenceHTTPTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.project = Path(self.temp.name)
        with project_lock(self.project):
            ledger = Ledger(self.project)
            import_plan(ledger, plan())
            select(ledger, {"beat": "beat-1", "alternative": "option-1"})
        self.root = self.project / "brolls"
        (self.root / "review.html").write_text("<html>Synthetic review</html>", encoding="utf-8")
        self.server, self.port = serve.start(self.project, port=0)
        self.server.daemon_threads = False
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.addCleanup(self.thread.join, 2)
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.server.shutdown)
        token = self.server.save_token
        assert isinstance(token, str) and token
        self.token = token
        self.image = self.project / "source.png"
        synth_image(self.image, color="blue", size="32x16")
        self.body = self.image.read_bytes()

    def ai(self):
        return Ledger(self.project, recover=False).data["ai"]

    def metadata(self, **extra):
        return {
            "beat": "beat-1",
            "fingerprint": self.ai()["beats"]["beat-1"]["fingerprint"],
            "identity": "http-upload",
            "name": "Референс.png",
            "declared_type": "image/png",
            "instructions": "Keep the blue tone; this is appearance guidance.",
            "role": "appearance",
            **extra,
        }

    def request(self, path, *, method="GET", body=None, headers=None, auth=True):
        prepared = {serve.TOKEN_HEADER: self.token} if auth else {}
        prepared.update(headers or {})
        connection = http.client.HTTPConnection("127.0.0.1", self.port, timeout=30)
        try:
            connection.request(method, path, body=body, headers=prepared)
            response = connection.getresponse()
            return response.status, response.read(), dict(response.getheaders())
        finally:
            connection.close()

    def upload(self, body=None, metadata=None, **kwargs):
        headers = {serve.AI_REFERENCE_HEADER: quote(json.dumps(metadata or self.metadata()))}
        headers.update(kwargs.pop("headers", {}))
        return self.request(
            serve.AI_REFERENCE_PATH,
            method="POST",
            body=self.body if body is None else body,
            headers=headers,
            **kwargs,
        )

    def test_actual_image_retry_preview_head_and_reopen_keep_private_bytes(self):
        status, raw, _headers = self.upload()
        self.assertEqual(200, status, raw)
        ref = json.loads(raw)["reference"]
        self.assertEqual(hashlib.sha256(self.body).hexdigest(), ref["sha256"])
        self.assertEqual("Референс.png", ref["name"])
        saved = self.ai()["references"]
        original = self.root / saved["originals"][ref["sha256"]]["ref"]
        self.assertEqual(self.body, original.read_bytes())
        self.assertEqual(ref["context_id"], json.loads(self.upload()[1])["reference"]["context_id"])
        path = f"/__ai/reference/{ref['context_id']}?part=pixels"
        code, pixels, headers = self.request(path)
        self.assertEqual(200, code)
        self.assertEqual("image/png", headers["Content-Type"])
        self.assertTrue(pixels.startswith(b"\x89PNG"))
        self.assertEqual((200, b""), self.request(path, method="HEAD")[:2])
        self.assertEqual(403, self.request(path, auth=False)[0])
        self.assertEqual(404, self.request("/" + original.relative_to(self.root).as_posix())[0])
        state = json.loads(self.request("/__ai/state")[1])["beats"][0]
        self.assertEqual(ref["context_id"], state["guidance"]["context_id"])
        self.assertIsNone(state["guidance"]["target_still"])
        self.assertIsNone(state["reference"], "Guidance before the first still has no version-bound target")
        self.assertEqual({}, self.ai()["jobs"])

    def test_auth_origin_host_and_header_limits_leave_state_unchanged(self):
        before = (self.root / "manifest.json").read_bytes()
        attempts = [
            {"auth": False},
            {"headers": {serve.TOKEN_HEADER: "wrong-session"}},
            {"headers": {"Origin": "https://unrelated.example"}},
            {"headers": {"Host": "unrelated.example"}},
        ]
        for options in attempts:
            with self.subTest(options=options):
                self.assertEqual(403, self.upload(**options)[0])
        self.assertEqual(400, self.upload(headers={serve.AI_REFERENCE_HEADER: "%broken"})[0])
        self.assertEqual(before, (self.root / "manifest.json").read_bytes())
        self.assertFalse((self.root / "ai-data/references").exists())

    def test_oversized_chunked_corrupt_and_mismatched_media_never_become_ready(self):
        for headers in (
            {"Content-Length": str(MAX_VIDEO_BYTES + 1)},
            {"Transfer-Encoding": "chunked"},
            {"Content-Length": "invalid"},
        ):
            with self.subTest(headers=headers):
                self.assertIn(self.upload(body=b"", headers=headers)[0], (400, 413))
        self.assertEqual(400, self.upload(body=b"not a picture")[0])
        self.assertEqual(400, self.upload(metadata=self.metadata(declared_type="video/mp4"))[0])
        for replacing in (0, 1, "yes", []):
            self.assertEqual(400, self.upload(metadata=self.metadata(replace=replacing))[0])
        self.assertEqual({}, self.ai()["jobs"])
        self.assertFalse(self.ai().get("references", {}).get("contexts"))

    def test_interrupted_http_transfer_can_retry_without_partial_reference(self):
        connection = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        try:
            connection.putrequest("POST", serve.AI_REFERENCE_PATH)
            connection.putheader(serve.TOKEN_HEADER, self.token)
            connection.putheader(serve.AI_REFERENCE_HEADER, quote(json.dumps(self.metadata())))
            connection.putheader("Content-Length", str(len(self.body)))
            connection.endheaders(self.body[:12])
            assert connection.sock is not None
            connection.sock.shutdown(socket.SHUT_WR)
            response = connection.getresponse()
            self.assertEqual(400, response.status)
            self.assertIn(b"Incomplete reference transfer", response.read())
        finally:
            connection.close()
        self.assertFalse(self.ai().get("references", {}).get("contexts"))
        self.assertEqual(200, self.upload()[0])
        self.assertEqual(1, len(self.ai()["references"]["contexts"]))

    def test_replace_and_remove_reject_a_changed_visible_context(self):
        first = json.loads(self.upload()[1])["reference"]
        changed = self.metadata(
            identity="replacement", replace=True, context=first["context_id"], instructions="Cooler."
        )
        second = json.loads(self.upload(metadata=changed)[1])["reference"]
        self.assertNotEqual(first["context_id"], second["context_id"])
        self.assertEqual(400, self.upload(metadata=changed | {"identity": "late-replacement"})[0])
        action = {
            "action": "reference-remove",
            "beat": "beat-1",
            "expected": changed["fingerprint"],
            "context": first["context_id"],
        }
        self.assertEqual(400, self.request("/__ai", method="POST", body=json.dumps(action))[0])
        action["context"] = second["context_id"]
        self.assertEqual(200, self.request("/__ai", method="POST", body=json.dumps(action))[0])
        self.assertFalse(json.loads(self.request("/__ai/state")[1])["beats"][0]["guidance"])
        self.assertEqual(2, len(self.ai()["references"]["contexts"]))
        self.assertEqual({}, self.ai()["jobs"])

    def test_private_preview_rechecks_hash_and_rejects_paths_and_unknown_parts(self):
        ref = json.loads(self.upload()[1])["reference"]
        prefix = f"/__ai/reference/{ref['context_id']}"
        for tail in (
            "?part=original",
            "?part=frame&index=bad",
            "/../../manifest.json?part=pixels",
            "%2f..%2fmanifest.json",
            "?part=frame&index=" + "1" * 5000,
        ):
            with self.subTest(tail=tail):
                self.assertIn(self.request(prefix + tail)[0], (400, 404))
        derivative = self.ai()["references"]["derivatives"][ref["derivative"]["id"]]
        path = self.root / derivative["pixels_ref"]
        path.write_bytes(path.read_bytes() + b"changed")
        self.assertEqual(404, self.request(prefix + "?part=pixels")[0])
        self.assertEqual(403, self.request(prefix + "?part=pixels", auth=False)[0])

    def test_later_video_interval_retains_video_and_serves_only_derived_frames(self):
        video = self.project / "later.mp4"
        _two_tone(video)
        body = video.read_bytes()
        metadata = self.metadata(
            name="later.mp4",
            declared_type="video/mp4",
            role="motion",
            instructions=f"Повтори движение камеры с {_BLUE_START} до {_BLUE_END} секунд, после синего перехода.",
        )
        ambiguous = metadata | {"instructions": "Use 0–1 seconds and 2–3 seconds for motion."}
        self.assertEqual(400, self.upload(body, ambiguous)[0])
        self.assertFalse(self.ai().get("references", {}).get("contexts"))
        status, raw, _headers = self.upload(body, metadata)
        self.assertEqual(200, status, raw)
        ref = json.loads(raw)["reference"]
        self.assertEqual(hashlib.sha256(body).hexdigest(), ref["sha256"])
        self.assertEqual(_BLUE_START, ref["interval"]["start_s"])
        code, frame, _headers = self.request(f"/__ai/reference/{ref['context_id']}?part=frame&index=0")
        self.assertEqual(200, code)
        sample = self.project / "frame.png"
        sample.write_bytes(frame)
        red, _green, blue = _mean(sample)
        self.assertGreater(blue, red + 100)
        self.assertEqual(200, self.request(f"/__ai/reference/{ref['context_id']}?part=sheet")[0])
        self.assertEqual({}, self.ai()["jobs"])

    def production(self, action):
        with patch.dict(os.environ, NATIVE_ENV):
            status, raw, _headers = self.request("/__ai", method="POST", body=json.dumps(action))
        self.assertEqual(200, status, raw)
        job = json.loads(raw)["job"]
        self.assertEqual("complete", job["state"], job)
        return self.ai()["jobs"][job["id"]]

    def test_comparison_apply_result_is_visible_beside_retained_original_slots(self):
        choice = {"action": "select", "beat": "beat-1", "mode": "images", "alternative": "option-1"}
        self.assertEqual(200, self.request("/__ai", method="POST", body=json.dumps(choice))[0])
        launch = {"action": "generate", "beat": "beat-1", "outputs": 3, "requestId": "comparison-root"}
        with patch.dict(os.environ, NATIVE_ENV):
            status, raw, _headers = self.request("/__ai", method="POST", body=json.dumps(launch))
        self.assertEqual(200, status, raw)
        group = json.loads(raw)
        self.assertEqual(3, len(group["jobs"]))
        self.assertTrue(all(job["state"] == "complete" for job in group["jobs"]))
        before = json.loads(self.request("/__ai/state")[1])["beats"][0]
        version = before["version"]
        original = (self.root / version["path"]).read_bytes()
        edit = self.production(
            {
                "action": "apply",
                "beat": "beat-1",
                "requestId": "comparison-edit",
                "instruction": "Softer blue light.",
                "still": {"id": version["id"], "signature": version["signature"]},
            }
        )
        after = json.loads(self.request("/__ai/state")[1])["beats"][0]
        self.assertEqual(edit["id"], after["job"]["id"], "The comparison must not hide Apply progress or completion")
        self.assertEqual(edit["result"], after["version"]["id"])
        self.assertEqual(
            [slot["version"]["id"] for slot in before["slots"]], [slot["version"]["id"] for slot in after["slots"]]
        )
        self.assertEqual(original, (self.root / version["path"]).read_bytes())
        self.assertEqual("pending", after["version"]["approval"])

    def test_http_apply_keeps_exact_versions_and_remove_cancels_beat_guidance(self):
        ref = json.loads(self.upload()[1])["reference"]
        fp = self.metadata()["fingerprint"]
        first = self.production({"action": "generate", "beat": "beat-1", "expected": fp, "requestId": "first"})
        state = json.loads(self.request("/__ai/state")[1])["beats"][0]
        version = state["version"]
        original = (self.root / version["path"]).read_bytes()
        action = {
            "action": "apply",
            "beat": "beat-1",
            "expected": fp,
            "requestId": "edit-1",
            "instruction": "Keep this exact view and change the lighting.",
            "still": {"id": version["id"], "signature": version["signature"]},
            "reference": ref["context_id"],
        }
        revised = self.production(action)
        self.assertEqual(version["id"], revised["request"]["target"]["id"])
        self.assertEqual(ref["context_id"], revised["request"]["references"][0]["context_id"])
        self.assertNotEqual(first["result"], revised["result"])
        self.assertEqual(revised["id"], self.production(action)["id"])
        self.assertEqual(original, (self.root / version["path"]).read_bytes())
        self.assertEqual("pending", self.ai()["versions"][revised["result"]]["approval"]["state"])
        removed = {"action": "reference-remove", "beat": "beat-1", "expected": fp, "context": ref["context_id"]}
        self.assertEqual(200, self.request("/__ai", method="POST", body=json.dumps(removed))[0])
        state = json.loads(self.request("/__ai/state")[1])["beats"][0]
        self.assertIsNone(state["guidance"])
        self.assertEqual(2, len(self.ai()["versions"]))

    def test_explicit_shared_style_reaches_another_beat_without_rebinding_history(self):
        first = json.loads(self.upload()[1])["reference"]
        with project_lock(self.project):
            select(Ledger(self.project), {"beat": "beat-2", "alternative": "option-1"})
        plain = self.production({"action": "generate", "beat": "beat-2", "requestId": "local-only"})
        self.assertFalse(plain["request"].get("references"))
        metadata = self.metadata(
            identity="shared-style",
            replace=True,
            context=first["context_id"],
            scope="shared",
            scope_instruction="Use this blue palette for every AI scene in this project.",
        )
        shared = json.loads(self.upload(metadata=metadata)[1])["reference"]
        guided = self.production({"action": "generate", "beat": "beat-2", "requestId": "shared-guided"})
        self.assertIn(metadata["scope_instruction"], guided["request"]["prompt"])
        self.assertEqual([shared["context_id"]], [row["context_id"] for row in guided["request"]["references"]])
        frozen = json.dumps(guided["request"], sort_keys=True)
        snapshot = self.ai()["references"]["inputs"][guided["request"]["references"][0]["input_id"]]["snapshot"]
        self.assertEqual("beat-1", snapshot["beat"])
        self.assertEqual("shared", snapshot["scope"])
        action = {
            "action": "reference-remove",
            "beat": "beat-1",
            "expected": metadata["fingerprint"],
            "context": shared["context_id"],
        }
        self.assertEqual(200, self.request("/__ai", method="POST", body=json.dumps(action))[0])
        after = self.production({"action": "generate", "beat": "beat-2", "requestId": "shared-canceled"})
        self.assertFalse(after["request"].get("references"))
        self.assertEqual(frozen, json.dumps(self.ai()["jobs"][guided["id"]]["request"], sort_keys=True))
        self.assertEqual("beat", self.ai()["references"]["contexts"][first["context_id"]]["scope"])

    def test_malformed_action_is_a_controlled_refusal(self):
        for action in (None, [], {}, 42):
            with self.subTest(action=action):
                status, raw, _headers = self.request("/__ai", method="POST", body=json.dumps({"action": action}))
                self.assertEqual(400, status, raw)
        for extra in ({"operation": ["apply"]}, {"scope": ["shared"]}, {"reference": {}}):
            action = {
                "action": "apply",
                "beat": "beat-1",
                "instruction": "Keep this scene",
                "requestId": "malformed",
                **extra,
            }
            self.assertEqual(400, self.request("/__ai", method="POST", body=json.dumps(action))[0])
