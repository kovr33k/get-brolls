"""Image reference journeys at the local HTTP and public CLI boundary."""

from __future__ import annotations

import copy
import http.client
import json
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from contextlib import contextmanager
from pathlib import Path
from urllib.parse import quote

import _isolation  # noqa: F401
from _cli import run_cli
from _media import skip_unless_ffmpeg, synth_image
from test_graphics_review import _assign, _project, _render, _review_payload, _version_hashes

from getbrolls import serve
from getbrolls.graphics import graphics_content_sha256
from getbrolls.graphics_references import MAX_IMAGE_BYTES, NAME_HEADER, UPLOAD_PATH
from getbrolls.ledger import Ledger, digest
from getbrolls.runtime import project_lock


@contextmanager
def serving(project):
    server, port = serve.start(project, port=0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield server, "http://127.0.0.1:" + str(port)
    finally:
        server.shutdown()
        thread.join(timeout=5)
        server.server_close()


def post(url, data, token, **headers):
    request = urllib.request.Request(url, data=data, method="POST", headers={serve.TOKEN_HEADER: token, **headers})
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            return json.loads(response.read())
    except urllib.error.HTTPError as exc:
        exc.close()
        raise


def upload(url, token, row, image, name="reference.png"):
    metadata = {
        key: row[key] for key in ("id", "project", "scene_id", "occurrence_id", "version", "signature", "reviewEpoch")
    }
    metadata["initial"] = row.get("initial", False)
    metadata["name"] = name
    return post(
        url + UPLOAD_PATH,
        image,
        token,
        **{NAME_HEADER: quote(json.dumps(metadata)), "Content-Type": "application/octet-stream"},
    )["reference"]


@skip_unless_ffmpeg
class GraphicsReferenceWorkflowTests(unittest.TestCase):
    def setup_project(self, project, *, rendered=False):
        _project(project)
        _assign(project)
        if rendered:
            _render(project)
        payload = _review_payload(project)
        path = Path(project) / "example.png"
        synth_image(path, color="blue")
        return payload, path

    def save_request(self, project, payload, image):
        row = payload["graphics"][0]
        before = (Path(project) / "brolls/manifest.json").read_bytes()
        with serving(project) as (server, url):
            ref = upload(url, server.save_token, row, image)
            with self.assertRaises(urllib.error.HTTPError) as error:
                urllib.request.urlopen(url + UPLOAD_PATH + "/" + Path(ref["ref"]).name)
            self.assertEqual(404, error.exception.code)
            error.exception.close()
            row.update(
                reference=ref, state="changes", comment="Adopt the blue palette; preserve our values.", scope="scene"
            )
            answer = post(url + serve.SAVE_PATH, json.dumps(payload).encode(), server.save_token)
            repeated = post(
                url + serve.SAVE_PATH, json.dumps({**payload, "exportedAt": "later"}).encode(), server.save_token
            )
            self.assertEqual(answer["path"], repeated["path"])
            with urllib.request.urlopen(url + UPLOAD_PATH + "/" + Path(ref["ref"]).name) as response:
                self.assertEqual(image, response.read())
        self.assertEqual(before, (Path(project) / "brolls/manifest.json").read_bytes())
        saved = json.loads(Path(answer["path"]).read_text(encoding="utf-8"))
        self.assertEqual(ref, saved["graphics"][0]["reference"])
        run_cli("import-review", "--file", answer["path"], "--by", "Synthetic editor", project=project)
        ledger = Ledger(project, recover=False)
        request = ledger.data["graphics"]["requests"][-1]
        return request, ref, answer["path"]

    def test_initial_image_save_reopen_authoring_freeze_and_idempotent_import(self):
        with tempfile.TemporaryDirectory() as project:
            payload, original = self.setup_project(project)
            self.assertTrue(payload["graphics"][0]["initial"])
            request, ref, saved = self.save_request(project, payload, original.read_bytes())
            original.unlink()
            self.assertEqual("authoring", request["kind"])
            self.assertIsNone(request["reviewed_version"])
            reopened = _review_payload(project)
            self.assertEqual(ref, reopened["graphics"][0]["reference"])
            run_cli("import-review", "--file", saved, "--by", "Synthetic editor", project=project)
            self.assertEqual(1, len(Ledger(project, recover=False).data["graphics"]["requests"]))
            result = run_cli(
                "graphics-reference-apply",
                "--request",
                request["id"],
                "--analysis",
                "Blue palette, large label, unchanged scene facts.",
                project=project,
            )
            self.assertFalse(result["render_started"])
            _render(project)
            ledger = Ledger(project, recover=False)
            version = ledger.data["graphics"]["versions"]["v1"]
            self.assertIsNone(version["parent"])
            self.assertEqual(ref, version["assignment"]["reference_context"]["reference"])
            self.assertNotIn("background", version["props"])
            self.assertIsNone(version["approval"])
            frozen = ledger.root / "graphics/numeric-stat/v1/references" / Path(ref["ref"]).name
            self.assertEqual(ref["sha256"], digest(frozen))
            run_cli(
                "graphics-request-complete",
                "--request",
                request["id"],
                "--version",
                "v1",
                "--outcome",
                "Applied the inspected palette.",
                project=project,
            )
            run_cli("import-review", "--file", saved, "--by", "Synthetic editor", project=project)
            self.assertEqual("processed", Ledger(project, recover=False).data["graphics"]["requests"][0]["state"])

    def test_revision_retains_original_signatures_history_and_requires_own_context(self):
        with tempfile.TemporaryDirectory() as project:
            payload, image = self.setup_project(project, rendered=True)
            hashes = _version_hashes(project, "numeric-stat", "v1")
            old = Ledger(project, recover=False).data["graphics"]["versions"]["v1"]
            old_signature = graphics_content_sha256(old)
            request, ref, saved = self.save_request(project, payload, image.read_bytes())
            run_cli(
                "graphics-reference-apply",
                "--request",
                request["id"],
                "--analysis",
                "Use blue accents; keep values and narration.",
                project=project,
            )
            _render(project)
            run_cli(
                "graphics-request-complete",
                "--request",
                request["id"],
                "--version",
                "v2",
                "--outcome",
                "Applied visual direction.",
                project=project,
            )
            ledger = Ledger(project, recover=False)
            self.assertEqual(old_signature, graphics_content_sha256(ledger.data["graphics"]["versions"]["v1"]))
            self.assertEqual(hashes, _version_hashes(project, "numeric-stat", "v1"))
            self.assertEqual("v1", ledger.data["graphics"]["versions"]["v2"]["parent"])
            self.assertEqual(
                ref, ledger.data["graphics"]["versions"]["v2"]["assignment"]["reference_context"]["reference"]
            )
            run_cli("import-review", "--file", saved, "--by", "Synthetic editor", project=project)
            self.assertEqual(1, len(Ledger(project, recover=False).data["graphics"]["requests"]))

    def test_upload_and_save_refuse_missing_prompt_wrong_token_origin_stale_and_corrupt(self):
        with tempfile.TemporaryDirectory() as project:
            payload, original = self.setup_project(project)
            row = payload["graphics"][0]
            image = original.read_bytes()
            with serving(project) as (server, url):
                for token, changed_row, content in [
                    ("wrong", row, image),
                    (server.save_token, {**row, "project": "foreign"}, image),
                    (server.save_token, {**row, "occurrence_id": {}}, image),
                    (server.save_token, row, b"not png"),
                ]:
                    with self.assertRaises(urllib.error.HTTPError):
                        upload(url, token, changed_row, content)
                ref = upload(url, server.save_token, row, image)
                bad = copy.deepcopy(payload)
                bad["graphics"][0].update(reference=ref, state="changes", comment="")
                with self.assertRaises(urllib.error.HTTPError):
                    post(url + serve.SAVE_PATH, json.dumps(bad).encode(), server.save_token)
                bad["graphics"][0]["comment"] = "Use this image's colors."
                bad["project"] = "foreign"
                with self.assertRaises(urllib.error.HTTPError):
                    post(url + serve.SAVE_PATH, json.dumps(bad).encode(), server.save_token)
                with self.assertRaises(urllib.error.HTTPError) as error:
                    post(url + UPLOAD_PATH, image, server.save_token, Origin="https://example.org")
                self.assertEqual(403, error.exception.code)
                with project_lock(project), self.assertRaises(urllib.error.HTTPError):
                    upload(url, server.save_token, row, image)
                _assign(project, narration="Changed scene context.")
                with self.assertRaises(urllib.error.HTTPError):
                    upload(url, server.save_token, row, image)
            self.assertFalse(any((Path(project) / "brolls/reviews").glob("*.json")))
            self.assertFalse(any((Path(project) / "brolls/graphics-data/references").glob(".upload-*")))

    def test_jpeg_probe_and_oversized_body_refusal(self):
        with tempfile.TemporaryDirectory() as project:
            payload, _original = self.setup_project(project)
            jpg = Path(project) / "actual.jpg"
            synth_image(jpg, color="green", size="80x40")
            with serving(project) as (server, url):
                ref = upload(url, server.save_token, payload["graphics"][0], jpg.read_bytes(), "actual.jpg")
                self.assertEqual((80, 40), (ref["width"], ref["height"]))
                self.assertTrue(ref["ref"].endswith(".jpg"))
                connection = http.client.HTTPConnection("127.0.0.1", server.server_address[1], timeout=5)
                try:
                    connection.request(
                        "POST",
                        UPLOAD_PATH,
                        body=b"x",
                        headers={
                            serve.TOKEN_HEADER: str(server.save_token),
                            "Content-Length": str(MAX_IMAGE_BYTES + 1),
                        },
                    )
                    response = connection.getresponse()
                    self.assertEqual(413, response.status)
                    response.read()
                finally:
                    connection.close()

    def test_same_prompt_with_changed_reference_has_distinct_identity_and_cannot_complete_wrong_request(self):
        with tempfile.TemporaryDirectory() as project:
            payload, image = self.setup_project(project)
            first, _ref, _saved = self.save_request(project, payload, image.read_bytes())
            another = Path(project) / "another.png"
            synth_image(another, color="red")
            second_payload = _review_payload(project)
            second, _ref2, _saved2 = self.save_request(project, second_payload, another.read_bytes())
            self.assertNotEqual(first["id"], second["id"])
            run_cli(
                "graphics-reference-apply",
                "--request",
                first["id"],
                "--analysis",
                "Use the actually inspected blue direction.",
                project=project,
            )
            ledger = Ledger(project, recover=False)
            ledger.data["graphics"]["occurrences"]["stat-01"]["reference_context"]["prompt"] = "A different prompt."
            ledger.save("synthetic-conflicting-prompt")
            _render(project)
            run_cli(
                "graphics-request-complete",
                "--request",
                first["id"],
                "--version",
                "v1",
                "--outcome",
                "Wrong frozen prompt.",
                project=project,
                expect=2,
            )
            run_cli(
                "graphics-request-complete",
                "--request",
                second["id"],
                "--version",
                "v1",
                "--outcome",
                "Wrong reference request.",
                project=project,
                expect=2,
            )
            run_cli(
                "graphics-reference-apply",
                "--request",
                second["id"],
                "--analysis",
                "Wrong old target.",
                project=project,
                expect=2,
            )
            self.assertEqual(
                "v1", Ledger(project, recover=False).data["graphics"]["occurrences"]["stat-01"]["current_version"]
            )

    def test_changed_saved_bytes_and_foreign_path_refused_without_manifest_mutation(self):
        with tempfile.TemporaryDirectory() as project:
            payload, original = self.setup_project(project)
            request, ref, saved = self.save_request(project, payload, original.read_bytes())
            ledger = Ledger(project, recover=False)
            before = ledger.path.read_bytes()
            forged = json.loads(Path(saved).read_text(encoding="utf-8"))
            forged["graphics"][0]["project"] = "foreign"
            foreign = Path(project) / "foreign.json"
            foreign.write_text(json.dumps(forged), encoding="utf-8")
            run_cli("import-review", "--file", str(foreign), "--by", "Synthetic editor", project=project, expect=2)
            self.assertEqual(before, ledger.path.read_bytes())
            (ledger.root / ref["ref"]).write_bytes(b"changed")
            run_cli(
                "graphics-reference-apply",
                "--request",
                request["id"],
                "--analysis",
                "Inspected image.",
                project=project,
                expect=2,
            )
            self.assertEqual(before, ledger.path.read_bytes())
            forged = json.loads(Path(saved).read_text(encoding="utf-8"))
            forged["graphics"][0]["reference"]["ref"] = "graphics-data/../../outside.png"
            Path(saved).write_text(json.dumps(forged), encoding="utf-8")
            run_cli("import-review", "--file", saved, "--by", "Synthetic editor", project=project, expect=2)
            self.assertEqual(before, ledger.path.read_bytes())

    def test_reopening_same_prompt_revision_selects_the_latest_saved_image(self):
        with tempfile.TemporaryDirectory() as project:
            payload, image = self.setup_project(project, rendered=True)
            first, _ref, _saved = self.save_request(project, payload, image.read_bytes())
            image.unlink()
            synth_image(image, color="red")
            second, reference, _saved2 = self.save_request(project, _review_payload(project), image.read_bytes())
            self.assertNotEqual(first["id"], second["id"])
            self.assertEqual(first["text"], second["text"])
            reopened = _review_payload(project)["graphics"][0]
            self.assertEqual(second["id"], reopened["requestId"])
            self.assertEqual(reference, reopened["reference"])


if __name__ == "__main__":
    unittest.main()
