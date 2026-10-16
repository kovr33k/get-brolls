"""Controlled faults at real local HTTP/CLI boundaries, using synthetic media."""

from __future__ import annotations

import copy
import http.client
import json
import os
import socket
import subprocess
import sys
import tempfile
import unittest
import urllib.error
import urllib.request
from pathlib import Path
from unittest import mock
from urllib.parse import quote, urlsplit

import _isolation  # noqa: F401
from _cli import run_cli
from _media import skip_unless_ffmpeg, synth_image, synth_video
from _paths import ROOT
from test_graphics_continuation import interrupted
from test_graphics_media_workflow import _background_payload
from test_graphics_mixed_references import analysis_file, inspect, upload_media
from test_graphics_reference_context import complete, current_row, edit
from test_graphics_references import post, serving
from test_graphics_review import ENV, _assign, _project, _render
from test_narration import _env, _serving, _stop, _write_wav

from getbrolls import serve
from getbrolls.ledger import Ledger, digest
from getbrolls.runtime import project_lock

FAULT = ROOT / "tests/fixtures/reference_interruption.py"
INTERRUPTED = 91


def fault_cli(project, fault, *args, expect=INTERRUPTED):
    empty = Path(project) / "empty.env"
    empty.write_text("", encoding="utf-8")
    result = subprocess.run(
        [sys.executable, str(FAULT), fault, "--env-file", str(empty), *map(str, args), "--project", str(project)],
        env={**os.environ, **ENV},
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )
    assert result.returncode == expect, result.stderr or result.stdout
    return json.loads(result.stdout if expect == 0 else result.stderr) if expect != INTERRUPTED else None


def prepare(project, *, rendered=False, shared=False, explicit=False, upload_video=True):
    _project(project)
    _assign(project, duration="2", **({"timing": "explicit", "start": "0", "end": "2"} if explicit else {}))
    if rendered:
        _render(project)
    payload, row = current_row(project)
    image, video = Path(project) / "style.png", Path(project) / "motion.mp4"
    synth_image(image, color="blue")
    synth_video(video, duration=6)
    with serving(project) as (server, url):
        refs = [upload_media(url, server.save_token, row, image, "image", "R1")]
        if upload_video:
            refs.append(upload_media(url, server.save_token, row, video, "video", "R3"))
    prompt = "Use R1 colors and R3 from 3 to 5 seconds."
    if explicit:
        prompt += " Put R3 behind our graphics."
    edit(
        row,
        prompt,
        refs,
        "shared" if shared else "scene",
    )
    return payload, refs


def save_only(project, payload):
    with serving(project) as (server, url):
        return post(url + serve.SAVE_PATH, json.dumps(payload).encode(), server.save_token)["path"]


def import_saved(project, path):
    run_cli("import-review", "--file", path, "--by", "Synthetic editor", project=project)
    return Ledger(project, recover=False).data["graphics"]["requests"][-1]


def critical(project):
    root = Path(project) / "brolls"
    return {
        path.relative_to(root).as_posix(): digest(path)
        for path in root.rglob("*")
        if path.is_file()
        and path.name not in {"diagnostics.jsonl", "getbrolls.log", "getbrolls.log.1", ".command.lock"}
    }


def truncated(url, token, route, body, metadata=None):
    target = urlsplit(url)
    conn = http.client.HTTPConnection(target.hostname, target.port, timeout=15)
    conn.putrequest("POST", route)
    conn.putheader(serve.TOKEN_HEADER, token)
    conn.putheader("Content-Length", str(len(body) + 17))
    if metadata:
        conn.putheader("X-GetBrolls-Reference", quote(json.dumps(metadata)))
    conn.endheaders()
    conn.send(body)
    assert conn.sock is not None
    conn.sock.shutdown(socket.SHUT_WR)
    response = conn.getresponse()
    result = response.status, json.loads(response.read())
    conn.close()
    return result


@skip_unless_ffmpeg
class GraphicsReferenceRecoveryTests(unittest.TestCase):
    def test_partial_transfer_and_prepublication_failure_preserve_existing_state_then_retry(self):
        for rendered in (False, True):
            with self.subTest(revision=rendered), tempfile.TemporaryDirectory() as project:
                payload, refs = prepare(project, rendered=rendered, upload_video=False)
                before = critical(project)
                row = payload["graphics"][0]
                metadata = {
                    key: row.get(key)
                    for key in (
                        "id",
                        "project",
                        "scene_id",
                        "occurrence_id",
                        "version",
                        "signature",
                        "reviewEpoch",
                        "initial",
                        "referenceBase",
                    )
                }
                metadata.update(name="interrupted.mp4", kind="video")
                with serving(project) as (server, url):
                    for route in (serve.SAVE_PATH, "/__graphics-reference"):
                        for headers in (
                            [("Content-Length", "2"), ("Content-Length", "2")],
                            [("Content-Length", "2"), ("Transfer-Encoding", "chunked")],
                        ):
                            connection = http.client.HTTPConnection(urlsplit(url).netloc, timeout=10)
                            connection.putrequest("POST", route)
                            connection.putheader(serve.TOKEN_HEADER, server.save_token or "")
                            for name, value in headers:
                                connection.putheader(name, value)
                            connection.endheaders(b"{}")
                            response = connection.getresponse()
                            self.assertIn(response.status, (400, 413))
                            response.read()
                            connection.close()
                    code, response = truncated(
                        url, server.save_token, "/__graphics-reference", b"partial video", metadata
                    )
                    self.assertEqual(400, code)
                    self.assertIn("error", response)
                    self.assertFalse(list((Path(project) / "brolls/reviews").glob("*.json")))
                    ref = upload_media(url, server.save_token, row, Path(project) / "motion.mp4", "video", "R3")
                    refs.append(ref)
                    row["references"].append(copy.deepcopy(ref))
                    code, _ = truncated(url, server.save_token, serve.SAVE_PATH, json.dumps(payload).encode())
                    self.assertEqual(400, code, "a valid JSON prefix is still an incomplete declared body")
                    with (
                        mock.patch.object(serve, "_publish_review", side_effect=OSError("Synthetic full-disk refusal")),
                        self.assertRaises(urllib.error.HTTPError),
                    ):
                        post(url + serve.SAVE_PATH, json.dumps(payload).encode(), server.save_token)
                    with self.assertRaises(urllib.error.HTTPError) as error:
                        urllib.request.urlopen(url + "/__graphics-reference/" + Path(refs[0]["ref"]).name)
                    self.assertEqual(404, error.exception.code)
                    error.exception.close()
                    answer = post(url + serve.SAVE_PATH, json.dumps(payload).encode(), server.save_token)
                self.assertFalse(list((Path(project) / "brolls/graphics-data/references").glob(".upload-*")))
                self.assertFalse(list((Path(project) / "brolls/reviews").glob(".save-*")))
                after = critical(project)
                self.assertEqual(
                    before,
                    {
                        key: value
                        for key, value in after.items()
                        if not key.startswith("reviews/") and key != refs[1]["ref"]
                    },
                )
                self.assertEqual(1, len(list((Path(project) / "brolls/reviews").glob("references-*.json"))))
                request = import_saved(project, answer["path"])
                self.assertEqual(refs, request["references"])

    def test_lost_success_response_is_persistent_idempotent_and_conflicting_replay_is_refused(self):
        with tempfile.TemporaryDirectory() as project:
            payload, refs = prepare(project)
            original = serve._NoCacheHandler.end_headers
            dropped = False

            def drop_response(handler):
                nonlocal dropped
                if handler.command == "POST" and handler.path == serve.SAVE_PATH and not dropped:
                    dropped = True
                    handler.connection.shutdown(socket.SHUT_RDWR)
                    handler.close_connection = True
                    raise ConnectionResetError("Synthetic response lost after durable publication")
                return original(handler)

            with serving(project) as (server, url):
                server.handle_error = lambda request, client_address: None
                with (
                    mock.patch.object(serve._NoCacheHandler, "end_headers", drop_response),
                    self.assertRaises((http.client.RemoteDisconnected, ConnectionError)),
                ):
                    post(url + serve.SAVE_PATH, json.dumps(payload).encode(), server.save_token)
                stored = list((Path(project) / "brolls/reviews").glob("references-*.json"))
                self.assertEqual(1, len(stored))
                self.assertEqual(payload, json.loads(stored[0].read_text(encoding="utf-8")))
                old_token = server.save_token
            with serving(project) as (server, url):
                with self.assertRaises(urllib.error.HTTPError) as error:
                    post(url + serve.SAVE_PATH, json.dumps(payload).encode(), old_token)
                self.assertEqual(403, error.exception.code)
                for index in range(35):
                    post(
                        url + serve.SAVE_PATH, json.dumps({"items": [], "ordinary": index}).encode(), server.save_token
                    )
                retry = {**payload, "exportedAt": "retry after response loss"}
                answer = post(url + serve.SAVE_PATH, json.dumps(retry).encode(), server.save_token)
                self.assertEqual(str(stored[0]), answer["path"])
                with urllib.request.urlopen(url + "/__graphics-reference/" + Path(refs[0]["ref"]).name) as response:
                    self.assertEqual((Path(project) / "brolls" / refs[0]["ref"]).read_bytes(), response.read())
            request = import_saved(project, answer["path"])
            import_saved(project, answer["path"])
            self.assertEqual(1, len(Ledger(project, recover=False).data["graphics"]["requests"]))
            conflict = copy.deepcopy(payload)
            conflict["graphics"][0]["comment"] = "Conflicting replay from the older context."
            with serving(project) as (server, url), self.assertRaises(urllib.error.HTTPError):
                post(url + serve.SAVE_PATH, json.dumps(conflict).encode(), server.save_token)
            self.assertEqual(request, Ledger(project, recover=False).data["graphics"]["requests"][0])

    def test_initial_and_revision_import_journal_and_regeneration_faults_recover_once(self):
        for rendered, fault in ((False, "before-journal"), (True, "after-journal"), (False, "review-regeneration")):
            with self.subTest(revision=rendered, fault=fault), tempfile.TemporaryDirectory() as project:
                payload, refs = prepare(project, rendered=rendered)
                saved = save_only(project, payload)
                root = Path(project) / "brolls"
                result = fault_cli(
                    project,
                    fault,
                    "import-review",
                    "--file",
                    saved,
                    "--by",
                    "Synthetic editor",
                    expect=2 if fault == "review-regeneration" else 91,
                )
                if fault == "before-journal":
                    self.assertFalse((root / ".pending-transaction.json").exists())
                    self.assertEqual([], Ledger(project, recover=False).data["graphics"]["requests"])
                elif fault == "after-journal":
                    self.assertTrue((root / ".pending-transaction.json").is_file())
                else:
                    assert isinstance(result, dict)
                    self.assertTrue(result["state_committed"])
                    self.assertFalse(result["recovery_pending"])
                before = critical(project)
                with project_lock(project):
                    run_cli("status", project=project)
                self.assertEqual(
                    before, critical(project), "status cannot recover or publish while the writer lock is held"
                )
                import_saved(project, saved)
                run_cli("review", project=project)
                graph = Ledger(project, recover=False).data["graphics"]
                self.assertEqual(1, len(graph["requests"]))
                self.assertEqual(refs, graph["requests"][0]["references"])
                self.assertFalse((root / ".pending-transaction.json").exists())
                events = [json.loads(line)["transaction"] for line in (root / "events.jsonl").read_text().splitlines()]
                self.assertEqual(len(events), len(set(events)))

    def test_lock_contention_is_retryable_without_publishing_or_recovering(self):
        with tempfile.TemporaryDirectory() as project:
            payload, _refs = prepare(project)
            before = critical(project)
            with serving(project) as (server, url), project_lock(project):
                with self.assertRaises(urllib.error.HTTPError):
                    post(url + serve.SAVE_PATH, json.dumps(payload).encode(), server.save_token)
                run_cli("status", project=project)
            self.assertEqual(before, critical(project))
            self.assertTrue(Path(save_only(project, payload)).is_file())

    def test_shared_composition_render_recovery_reuses_fixed_results_and_reports_changed_evidence(self):  # noqa: PLR0915 - One public journey establishes actual inclusion, fixed scope, and process recovery with observable outcomes.
        with tempfile.TemporaryDirectory() as project:
            payload, refs = prepare(project, shared=True, explicit=True)
            _assign(project, occurrence="stat-02", scene="second-scene")
            source = import_saved(project, save_only(project, payload))
            spec = {
                "resolution": "Only these two occurrences; keep the second scene's local neutral labels.",
                "targets": [
                    {
                        "occurrence_id": "stat-01",
                        "references": refs,
                        "instruction": "Use the inspected palette and explicitly included video interval.",
                    },
                    {
                        "occurrence_id": "stat-02",
                        "references": [],
                        "instruction": "Keep the local neutral labels and original narration.",
                    },
                ],
            }
            path = Path(project) / "brolls/scope.json"
            scope_path = path
            path.write_text(json.dumps(spec), encoding="utf-8")
            fault_cli(project, "after-manifest", "graphics-reference-scope", "--request", source["id"], "--file", path)
            before = critical(project)
            run_cli("status", project=project)
            self.assertEqual(before, critical(project))
            result = run_cli("graphics-reference-scope", "--request", source["id"], "--file", path, project=project)
            self.assertTrue(result["idempotent"])
            self.assertEqual(2, len(Ledger(project, recover=False).data["graphics"]["requests"]))
            _assign(project, occurrence="stat-03", scene="later-scene")
            waiting = run_cli("graphics-continue", "--request", source["id"], project=project, env=ENV)
            self.assertEqual(["waiting", "waiting"], [item["action"] for item in waiting["items"]])
            record = inspect(project, source, "--start", "3", "--end", "5")
            run_cli(
                "resolve",
                "--file",
                Path(project) / "brolls" / refs[1]["ref"],
                "--asset-type",
                "video",
                "--title",
                "Synthetic inclusion",
                project=project,
            )
            ident = Ledger(project, recover=False).data["items"][0]["id"]
            run_cli("preview", "--candidate", ident, "--start", "3", "--end", "5", project=project)
            run_cli(
                "approve",
                "--candidate",
                ident,
                "--by",
                "Synthetic editor",
                "--statement",
                "Synthetic fixture only.",
                project=project,
            )
            run_cli("permit", "--candidate", ident, "--evidence", "Synthetic fixture rights only.", project=project)
            run_cli("fetch", "--candidate", ident, project=project)
            candidate = Ledger(project, recover=False).data["items"][0]
            analysis = analysis_file(
                project,
                record,
                composition={
                    "label": "R3",
                    "instruction": "Put R3 behind our graphics.",
                    "background": _background_payload(ident, candidate["output"]["path"]),
                },
            )
            data = json.loads(analysis.read_text())
            data["effective_instructions"] = (
                "Use blue accents and the explicitly inspected 3-5-second video background; keep original facts and narration."
            )
            analysis.write_text(json.dumps(data), encoding="utf-8")
            fault_cli(
                project, "after-journal", "graphics-reference-apply", "--request", source["id"], "--file", analysis
            )
            before = critical(project)
            self.assertTrue(run_cli("status", project=project)["graphics"]["reference_recovery_pending"])
            self.assertEqual(before, critical(project))
            applied = run_cli(
                "graphics-reference-apply", "--request", source["id"], "--file", analysis, project=project
            )
            self.assertTrue(applied["idempotent"])
            interrupted(project, "after-verified")
            continued = run_cli("graphics-continue", "--request", source["id"], project=project, env=ENV)
            self.assertEqual(["recovered", "waiting"], [item["action"] for item in continued["items"]], continued)
            self.assertEqual("v1", continued["items"][0]["version"])
            repeated = run_cli("graphics-continue", "--request", source["id"], project=project, env=ENV)
            self.assertEqual("reused", repeated["items"][0]["action"])
            self.assertTrue(repeated["items"][0]["completion_required"])
            complete(project, source, "v1")
            child = Ledger(project, recover=False).data["graphics"]["requests"][1]
            run_cli(
                "graphics-reference-apply",
                "--request",
                child["id"],
                "--analysis",
                "Keep the existing neutral labels and original narration.",
                project=project,
            )
            result = run_cli("graphics-continue", "--request", source["id"], project=project, env=ENV)
            self.assertEqual(["reused", "rendered"], [item["action"] for item in result["items"]])
            complete(project, child, result["items"][1]["version"])
            run_cli("graphics-continue", "--request", source["id"], project=project, env=ENV)
            graph = Ledger(project, recover=False).data["graphics"]
            self.assertEqual(2, len(graph["versions"]))
            self.assertIsNone(graph["occurrences"]["stat-03"].get("current_version"))
            original = Path(project) / "brolls" / refs[1]["ref"]
            original_bytes = original.read_bytes()
            original.write_bytes(b"changed committed source")
            before = critical(project)
            status = run_cli("status", project=project)["graphics"]["reference_work"]
            self.assertEqual("blocked", next(work for work in status if work["request_id"] == source["id"])["state"])
            self.assertEqual(before, critical(project))
            replayed_scope = run_cli(
                "graphics-reference-scope", "--request", source["id"], "--file", scope_path, project=project
            )
            self.assertEqual("conflict", replayed_scope["scope"]["state"])
            resumed = run_cli("graphics-continue", "--request", source["id"], project=project, env=ENV)
            self.assertEqual("waiting", resumed["items"][0]["action"])
            self.assertEqual(2, len(Ledger(project, recover=False).data["graphics"]["versions"]))
            original.write_bytes(original_bytes)
            artifact = Path(project) / "brolls" / graph["versions"]["v1"]["artifact"]["path"]
            artifact.write_bytes(b"changed completed output")
            blocked = run_cli("graphics-continue", "--request", source["id"], project=project, env=ENV)
            self.assertEqual("waiting", blocked["items"][0]["action"])
            self.assertEqual("conflict", blocked["reference_scopes"][0]["state"])
            self.assertEqual(2, len(Ledger(project, recover=False).data["graphics"]["versions"]))

    def test_request_continuation_keeps_unchanged_unknown_narration_without_network_resubmission(self):
        with tempfile.TemporaryDirectory() as project:
            payload, _refs = prepare(project)
            request = import_saved(project, save_only(project, payload))
            record = inspect(project, request, "--start", "3", "--end", "5")
            path = analysis_file(project, record)
            data = json.loads(path.read_text())
            data["effective_instructions"] = (
                "Use the inspected palette and motion; preserve the original narration and facts."
            )
            path.write_text(json.dumps(data), encoding="utf-8")
            run_cli("graphics-reference-apply", "--request", request["id"], "--file", path, project=project)
            server, thread = _serving(project, "disconnect")
            try:
                provider = _env(server)
                wav = _write_wav(Path(project) / "vo.wav")
                result = run_cli(
                    "narration-analyze", "--recording", wav, "--analysis", "na-unknown", project=project, env=provider
                )
                self.assertEqual("unknown", result["state"])
                original = Ledger(project, recover=False).data["narration"]
                calls = server.state.posts, server.state.gets
                first = run_cli(
                    "graphics-continue", "--request", request["id"], project=project, env={**provider, **ENV}
                )
                second = run_cli(
                    "graphics-continue", "--request", request["id"], project=project, env={**provider, **ENV}
                )
                self.assertEqual("rendered", first["items"][0]["action"])
                self.assertEqual("reused", second["items"][0]["action"])
                self.assertEqual(calls, (server.state.posts, server.state.gets))
                self.assertEqual(original, Ledger(project, recover=False).data["narration"])
                self.assertEqual(1, len(Ledger(project, recover=False).data["graphics"]["versions"]))
            finally:
                _stop(server, thread)

    def test_saved_retry_keeps_original_target_while_changed_assignment_waits(self):
        for rendered in (False, True):
            with self.subTest(revision=rendered), tempfile.TemporaryDirectory() as project:
                payload, _refs = prepare(project, rendered=rendered)
                saved = save_only(project, payload)
                request = import_saved(project, saved)
                _assign(project, narration="A changed scenario requires its own actual context.")
                self.assertEqual(saved, save_only(project, payload))
                import_saved(project, saved)
                graph = Ledger(project, recover=False).data["graphics"]
                before = len(graph["versions"])
                result = run_cli("graphics-continue", "--request", request["id"], project=project, env=ENV)
                self.assertEqual("waiting", result["items"][0]["action"])
                self.assertEqual("stale", result["items"][0]["state"])
                self.assertEqual(before, len(Ledger(project, recover=False).data["graphics"]["versions"]))
                self.assertEqual(
                    request["reviewed_version"],
                    Ledger(project, recover=False).data["graphics"]["requests"][0]["reviewed_version"],
                )
