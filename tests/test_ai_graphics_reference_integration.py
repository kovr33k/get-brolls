"""AI and Remotion references share one actual Storyboard and recover separately."""

import http.client
import json
import os
import re
import socket
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from urllib.parse import quote
from urllib.request import urlopen

import _isolation  # noqa: F401
from _cli import run_cli
from _media import skip_unless_ffmpeg, synth_image
from test_ai_reference_http import NATIVE_ENV
from test_ai_references import plan
from test_graphics_mixed_references import upload_media
from test_graphics_reference_context import apply_image, complete, current_row, edit
from test_graphics_reference_recovery import truncated
from test_graphics_references import post, serving
from test_graphics_review import ENV, _assign, _project, _render, _review_payload, _version_hashes

from getbrolls import serve
from getbrolls.ai_state import import_plan, select
from getbrolls.ledger import Ledger
from getbrolls.runtime import project_lock


@skip_unless_ffmpeg
class CombinedReferenceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.project = Path(self.temp.name)
        _project(self.project)
        _assign(self.project, duration="2")
        with project_lock(self.project):
            ledger = Ledger(self.project)
            import_plan(ledger, plan())
            select(ledger, {"beat": "beat-1", "alternative": "option-1"})
        _review_payload(self.project)
        self.image = self.project / "same-reference.png"
        synth_image(self.image, color="blue", size="32x16")

    def ai_reference(self, url, token):
        metadata = {
            "beat": "beat-1",
            "fingerprint": Ledger(self.project, recover=False).data["ai"]["beats"]["beat-1"]["fingerprint"],
            "identity": "combined-reference",
            "name": self.image.name,
            "declared_type": "image/png",
            "instructions": "Keep the blue palette in this AI still.",
            "role": "guidance",
        }
        return post(
            url + serve.AI_REFERENCE_PATH,
            self.image.read_bytes(),
            token,
            **{serve.AI_REFERENCE_HEADER: quote(json.dumps(metadata))},
        )["reference"]

    def retry_lost_response(self, server, url, route, payload):
        original = serve._NoCacheHandler.end_headers
        dropped = False

        def drop(handler):
            nonlocal dropped
            if handler.command == "POST" and handler.path == route and not dropped:
                dropped = True
                handler.connection.shutdown(socket.SHUT_RDWR)
                handler.close_connection = True
                raise ConnectionResetError("Synthetic lost response after publication")
            return original(handler)

        server.handle_error = lambda request, address: None
        with (
            patch.object(serve._NoCacheHandler, "end_headers", drop),
            self.assertRaises((http.client.RemoteDisconnected, ConnectionError)),
        ):
            post(url + route, json.dumps(payload).encode(), server.save_token)
        self.assertTrue(dropped)
        before = Ledger(self.project, recover=False).data
        turns = self.turn_count()
        result = post(url + route, json.dumps(payload).encode(), server.save_token)
        self.assertEqual(before, Ledger(self.project, recover=False).data)
        self.assertEqual(turns, self.turn_count(), "Lost-response retry must not start another native turn")
        return result

    def turn_count(self):
        return sum(int(p.read_text()) for p in (self.project / "brolls/ai-work").glob("*/turn-start-count.txt"))

    def test_mixed_versions_references_and_lost_responses_recover_independently(self):  # noqa: PLR0915 - One public mixed-project journey verifies isolation across durable saves, versioning and both recovery paths.
        _render(self.project)
        graphics_v1 = _version_hashes(self.project, "numeric-stat", "v1")
        with serving(self.project) as (server, url), patch.dict(os.environ, NATIVE_ENV):
            with urlopen(url + "/review.html", timeout=10) as response:
                page = response.read().decode()
            match = re.search(r"window.GETBROLLS_SAVE=(.*?);</script>", page)
            self.assertIsNotNone(match)
            assert match is not None
            config = json.loads(match.group(1))
            self.assertEqual(serve.AI_PATH, config["aiUrl"])
            self.assertEqual(serve.AI_REFERENCE_PATH, config["aiReferenceUrl"])
            self.assertEqual(8, config["referenceMaxFiles"])
            self.assertEqual(64 * 1024 * 1024, config["referenceVideoMaxBytes"])
            _, row = current_row(self.project)
            graphics_ref = upload_media(url, server.save_token, row, self.image, "image", "R1")
            graphics_before = Ledger(self.project, recover=False).data["graphics"]
            ai_ref = self.ai_reference(url, server.save_token)
            launch = {"action": "generate", "beat": "beat-1", "requestId": "combined-first"}
            first = post(url + serve.AI_PATH, json.dumps(launch).encode(), server.save_token)["job"]
            self.assertEqual("complete", first["state"])
            self.assertEqual(graphics_before, Ledger(self.project, recover=False).data["graphics"])
            payload, row = current_row(self.project)
            self.assertTrue(payload["ai"])
            edit(row, "Use R1 blue accents, preserving our values and narration.", [graphics_ref])
            payload["ai"][0].update(state="changes", decision="changes", comment="Synthetic mixed-board review")
            saved = self.retry_lost_response(server, url, serve.SAVE_PATH, payload)
            imported = run_cli(
                "import-review", "--file", saved["path"], "--by", "Synthetic editor", project=self.project
            )
            self.assertEqual(1, imported["ai_imported"])
            ledger = Ledger(self.project, recover=False)
            request = ledger.data["graphics"]["requests"][-1]
            ai_before = ledger.data["ai"]
            self.assertEqual([graphics_ref], request["references"])
            apply_image(self.project, request)
            _render(self.project)
            complete(self.project, request, "v2")
            self.assertEqual(ai_before, Ledger(self.project, recover=False).data["ai"])
            self.assertEqual(graphics_v1, _version_hashes(self.project, "numeric-stat", "v1"))
            version = ai_before["versions"][first["result"]]
            old_image = (self.project / "brolls" / version["path"]).read_bytes()
            graphics_before = Ledger(self.project, recover=False).data["graphics"]
            apply = {
                "action": "apply",
                "beat": "beat-1",
                "requestId": "combined-edit",
                "instruction": "Keep this view and make the blue lighting softer.",
                "still": {"id": version["id"], "signature": payload["ai"][0]["signature"]},
                "reference": ai_ref["context_id"],
            }
            revised = self.retry_lost_response(server, url, serve.AI_PATH, apply)["job"]
            self.assertEqual("complete", revised["state"])
            self.assertNotEqual(first["result"], revised["result"])
            self.assertEqual(graphics_before, Ledger(self.project, recover=False).data["graphics"])
            self.assertEqual(old_image, (self.project / "brolls" / version["path"]).read_bytes())
        with serving(self.project) as (server, url), patch.dict(os.environ, NATIVE_ENV):
            before = Ledger(self.project, recover=False).data
            turns = self.turn_count()
            self.assertEqual(
                revised["id"], post(url + serve.AI_PATH, json.dumps(apply).encode(), server.save_token)["job"]["id"]
            )
            retried = post(url + serve.SAVE_PATH, json.dumps(payload).encode(), server.save_token)
            self.assertEqual(saved["name"], retried["name"])
            self.assertTrue(Path(saved["path"]).samefile(retried["path"]))
            self.assertEqual(before, Ledger(self.project, recover=False).data)
            self.assertEqual(turns, self.turn_count())
        run_cli("graphics-continue", "--request", request["id"], project=self.project, env=ENV)
        after = Ledger(self.project, recover=False).data
        self.assertEqual(2, len(after["ai"]["versions"]))
        self.assertEqual(2, len(after["graphics"]["versions"]))
        self.assertEqual(before["ai"], after["ai"])
        self.assertEqual(graphics_v1, _version_hashes(self.project, "numeric-stat", "v1"))
        reopened = _review_payload(self.project)
        self.assertEqual(2, len(reopened["ai"]))
        self.assertEqual({"v1", "v2"}, {r["version"] for r in reopened["graphics"]})

    def test_incomplete_ai_json_cannot_remove_a_saved_reference(self):
        with serving(self.project) as (server, url):
            reference = self.ai_reference(url, server.save_token)
            body = json.dumps(
                {
                    "action": "reference-remove",
                    "beat": "beat-1",
                    "context": reference["context_id"],
                    "expected": Ledger(self.project, recover=False).data["ai"]["beats"]["beat-1"]["fingerprint"],
                }
            ).encode()
            before = (self.project / "brolls/manifest.json").read_bytes()
            status, _response = truncated(url, server.save_token, serve.AI_PATH, body)
            self.assertEqual(400, status, "A complete JSON prefix is still an incomplete declared request")
            self.assertEqual(before, (self.project / "brolls/manifest.json").read_bytes())
            result = post(url + serve.AI_PATH, body, server.save_token)
            self.assertEqual("absent", result["reference"]["state"])

    def test_ambiguous_ai_json_framing_cannot_change_the_selection(self):
        body = json.dumps({"action": "select", "beat": "beat-1", "alternative": "option-2"}).encode()
        with serving(self.project) as (server, url):
            before = (self.project / "brolls/manifest.json").read_bytes()
            for extra_headers in (
                [("Content-Length", str(len(body))), ("Content-Length", str(len(body)))],
                [("Content-Length", str(len(body))), ("Transfer-Encoding", "chunked")],
            ):
                with self.subTest(headers=extra_headers):
                    connection = http.client.HTTPConnection(url.removeprefix("http://"), timeout=10)
                    try:
                        connection.putrequest("POST", serve.AI_PATH)
                        connection.putheader(serve.TOKEN_HEADER, server.save_token or "")
                        for name, value in extra_headers:
                            connection.putheader(name, value)
                        connection.endheaders(body)
                        response = connection.getresponse()
                        self.assertEqual(400, response.status)
                        response.read()
                    finally:
                        connection.close()
                    self.assertEqual(before, (self.project / "brolls/manifest.json").read_bytes())
            post(url + serve.AI_PATH, body, server.save_token)
            self.assertEqual("option-2", Ledger(self.project, recover=False).data["ai"]["beats"]["beat-1"]["selected"])
