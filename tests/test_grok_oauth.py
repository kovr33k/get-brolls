"""Audited X discovery with synthetic OAuth/streamed tool responses; no live credentials."""

import io
import json
import os
import tempfile
import unittest
from datetime import UTC, datetime, timedelta
from http.client import HTTPMessage
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.request import Request

import _isolation  # noqa: F401
from _media import skip_unless_ffmpeg, synth_image
from test_existing_catalog_fragments import call, confirm, progress_row, save_plan, storyboard, write_brief

from getbrolls import grok_oauth as grok
from getbrolls.ledger import Ledger
from getbrolls.runtime import OperationError

SECRET = "private_fixture_token_never_export"
URL = "https://x.com/fixture_author/status/12345"
FILTERS = ("allowed_x_handles=fixture_author", "from_date=2026-01-03", "to_date=2026-01-07")


def completed(posts=None, *, calls=1, cited=True, status="completed"):
    content = {"type": "output_text", "text": json.dumps({"posts": posts or []}), "annotations": []}
    if cited:
        content["annotations"] = [{"type": "url_citation", "url": "https://x.com/i/status/12345"}]
    response = {
        "status": status,
        "usage": {"server_side_tool_usage_details": {"x_search_calls": calls}},
        "output": [{"type": "message", "role": "assistant", "content": [content]}],
    }
    return ("data: " + json.dumps({"type": "response.completed", "response": response}) + "\n\ndata: [DONE]\n").encode()


def post(**changes):
    return {
        "url": URL,
        "date": "2026-01-04T12:00:00Z",
        "language": "es",
        "excerpt": "Material público sintético.",
        **changes,
    }


class XWorkflow(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.project = self.root / "project"
        self.project.mkdir()
        self.private = self.root / ".grok"
        self.private.mkdir()
        self.auth = self.private / "auth.json"
        self.record = {
            "auth_mode": "oidc",
            "oidc_issuer": grok.ISSUER,
            "oidc_client_id": "fixture-client",
            "key": SECRET,
            "refresh_token": SECRET,
            "expires_at": (datetime.now(UTC) + timedelta(hours=1)).isoformat(),
            "email": SECRET,
        }
        self.write_auth()
        (self.private / "config.toml").write_text('[models]\ndefault = "grok-4.7"\n', encoding="utf-8")
        write_brief(self.project, ["x"])
        self.home = patch.object(Path, "home", return_value=self.root)
        self.home.start()
        self.addCleanup(self.home.stop)
        self.binary = patch.object(grok.shutil, "which", return_value="synthetic-retained-grok")
        self.binary.start()
        self.addCleanup(self.binary.stop)
        self.version = patch.object(grok, "_client_version", return_value="1.0.46")
        self.version_mock = self.version.start()
        self.addCleanup(self.version.stop)
        self.requests = []
        self.reply = completed([post()])
        self.transport = patch.object(grok, "build_opener", return_value=SimpleNamespace(open=self.open_request))
        self.transport.start()
        self.addCleanup(self.transport.stop)

    def write_auth(self):
        self.auth.write_text(json.dumps({"issuer::fixture": self.record}), encoding="utf-8")

    def open_request(self, request, timeout):
        self.assertEqual(45, timeout)
        self.requests.append(request)
        if request.full_url.endswith("/oauth2/token"):
            return io.BytesIO(
                json.dumps(
                    {
                        "access_token": "rotated_fixture_token",
                        "refresh_token": "rotated_fixture_refresh",
                        "expires_in": 3600,
                    }
                ).encode()
            )
        return io.BytesIO(self.reply)

    def search(self, query="laboratory bench", *, planned=True, extra=(), filters=FILTERS):
        arguments = [
            "search",
            "--provider",
            "auto" if planned else "x",
            "--shot",
            "opening",
            "--query",
            query,
            "--media",
            "any",
            "--limit",
            "2",
        ]
        if planned:
            arguments.append("--planned")
        for value in filters:
            arguments.extend(("--catalog-filter", value))
        return call(self.project, *arguments, *extra)

    def test_native_discovery_keeps_original_reference_and_separate_unverified_metadata(self):
        save_plan(self.project, "x")
        with patch.dict(os.environ, {"XAI_API_KEY": SECRET}):
            result = self.search()
        self.assertEqual(1, len(self.requests))
        sent = self.requests[0]
        self.assertEqual(grok.PROXY, sent.full_url)
        self.assertEqual("Bearer " + SECRET, sent.get_header("Authorization"))
        self.assertEqual("1.0.46", sent.get_header("X-grok-client-version"))
        payload = json.loads(sent.data)
        self.assertEqual("grok-4.7", payload["model"])
        self.assertEqual(1, payload["max_tool_calls"])
        self.assertEqual(
            [
                {
                    "type": "x_search",
                    "allowed_x_handles": ["fixture_author"],
                    "from_date": "2026-01-03",
                    "to_date": "2026-01-07",
                }
            ],
            payload["tools"],
        )
        self.assertNotIn(SECRET, json.dumps(payload))
        row = result["items"][0]
        self.assertEqual(URL, row["source_url"])
        self.assertEqual("12345", row["source_id"])
        self.assertEqual("fixture_author", row["creator"]["name"])
        self.assertEqual("es", row["catalog"]["original_language"])
        self.assertFalse(row["catalog"]["quote_verified"])
        self.assertFalse(row["catalog"]["original_post_viewed"])
        self.assertFalse(row["catalog"]["search_metadata_verified"])
        self.assertIsNone(row.get("captured_at"))
        self.assertEqual([], row["catalog"]["attached_media"])
        self.assertEqual(0, progress_row(self.project)["suitable_count"])
        with self.assertRaises(OperationError):
            call(self.project, "inspect", "--candidate", row["id"])
        self.assertNotIn(SECRET, json.dumps(Ledger(self.project, recover=False).data))
        self.assertTrue(self.search()["replayed"])
        self.assertEqual(1, len(self.requests))

    def test_dry_run_does_not_read_refresh_or_invoke_client_or_transport(self):
        save_plan(self.project, "x")
        self.record["expires_at"] = (datetime.now(UTC) - timedelta(hours=1)).isoformat()
        self.write_auth()
        before = self.auth.read_bytes()
        self.search(extra=("--dry-run",))
        self.search(planned=False, extra=("--dry-run",))
        self.assertEqual(before, self.auth.read_bytes())
        self.version_mock.assert_not_called()
        self.assertEqual([], self.requests)
        self.assertEqual(0, progress_row(self.project)["queries_used"])

    def test_expired_oauth_refreshes_same_account_then_searches_without_key_fallback(self):
        self.record["expires_at"] = (datetime.now(UTC) - timedelta(hours=1)).isoformat()
        self.write_auth()
        save_plan(self.project, "x")
        self.search()
        self.assertEqual([grok.ISSUER + "/oauth2/token", grok.PROXY], [r.full_url for r in self.requests])
        self.assertEqual("Bearer rotated_fixture_token", self.requests[1].get_header("Authorization"))
        updated = json.loads(self.auth.read_text())["issuer::fixture"]
        self.assertEqual("rotated_fixture_refresh", updated["refresh_token"])
        self.assertEqual(SECRET, updated["email"])
        self.assertEqual([], list(self.private.glob(".getbrolls-*")))
        self.assertNotIn(SECRET, json.dumps(Ledger(self.project, recover=False).data))

    def test_expired_without_refresh_and_ambiguous_or_unsupported_auth_stay_unavailable(self):
        cases = [
            {**self.record, "expires_at": (datetime.now(UTC) - timedelta(hours=1)).isoformat(), "refresh_token": None},
            {**self.record, "auth_mode": "api_key"},
            {**self.record, "expires_at": "2026-01-01"},
            {**self.record, "expires_at": None},
        ]
        for record in cases:
            with self.subTest(record={k: v for k, v in record.items() if k in ("auth_mode", "expires_at")}):
                self.record = record
                self.write_auth()
                with self.assertRaises(OperationError):
                    self.search(planned=False)
        self.assertEqual([], self.requests)
        self.auth.write_text(json.dumps({"one": self.record, "two": self.record}))
        with self.assertRaises(OperationError):
            self.search(planned=False)
        self.assertEqual([], self.requests)

    def test_unverified_selected_model_never_substitutes(self):
        (self.private / "config.toml").write_text('model = "unverified-selected-model"\n')
        save_plan(self.project, "x")
        result = self.search()
        self.assertEqual([], result["items"])
        self.assertIn("model/tool pair is unverified", result["search_progress"][0]["attempts"][0]["error"])
        self.assertEqual([], self.requests)

    def test_bad_filters_refuse_before_spending_an_attempt(self):
        save_plan(self.project, "x")
        for filters in (
            (),
            (*FILTERS, "excluded_x_handles=other"),
            ("allowed_x_handles=bad/handle", *FILTERS[1:]),
            ("from_date=2026-01-07", "to_date=2026-01-03"),
            (*FILTERS, "max_tool_calls=2"),
        ):
            with self.subTest(filters=filters), self.assertRaises(OperationError):
                self.search(filters=filters)
        self.assertEqual([], self.requests)
        self.assertEqual(0, progress_row(self.project)["queries_used"])

    def test_missing_citation_malformed_output_and_tool_failures_are_saved_without_suitable_options(self):
        replies = (
            completed([post()], cited=False),
            completed([post()], calls=0),
            completed([post()], status="incomplete"),
            b"data: invalid\n",
        )
        for index, reply in enumerate(replies):
            self.project = self.root / ("error-" + str(index))
            self.project.mkdir()
            write_brief(self.project, ["x"])
            save_plan(self.project, "x")
            self.reply = reply
            result = self.search()
            self.assertEqual([], result["items"])
            self.assertEqual("access_or_provider_error", result["search_progress"][0]["attempts"][0]["status"])
            self.assertEqual(0, progress_row(self.project)["suitable_count"])
            # Same failed attempt never becomes a fresh network request on restart.
            self.assertTrue(self.search()["replayed"])
            self.assertEqual(index + 1, len(self.requests))

    def test_three_queries_share_the_allowance_and_no_fourth_call_is_sent(self):
        save_plan(self.project, "x")
        self.reply = completed([])
        for query in ("first original query", "second wording", "tercera consulta"):
            self.search(query)
        with self.assertRaises(OperationError):
            self.search("fourth wording")
        self.assertEqual(3, len(self.requests))
        self.assertEqual(3, progress_row(self.project)["queries_used"])

    def test_concurrent_account_change_during_refresh_is_preserved(self):
        self.record["expires_at"] = (datetime.now(UTC) - timedelta(hours=1)).isoformat()
        self.write_auth()
        save_plan(self.project, "x")
        concurrent = json.dumps({"other": {"auth_mode": "oidc", "key": "new-private-state"}})

        def changed(*args, **kwargs):
            self.auth.write_text(concurrent)
            return b'{"access_token":"new-token","expires_in":3600}'

        with patch.object(grok, "_post", side_effect=changed):
            result = self.search()
        self.assertEqual(concurrent, self.auth.read_text())
        self.assertEqual([], result["items"])
        self.assertEqual([], list(self.private.glob(".getbrolls-*")))

    def test_parsing_requires_matching_account_date_and_identity(self):
        for changed in (
            {"url": "https://x.com/other/status/12345"},
            {"date": "2025-01-04"},
            {"url": "https://x.com/fixture_author/status/99999"},
            {"excerpt": "Authorization: Bearer private"},
            {"url": "https://x.com/i/status/12345"},
        ):
            with self.subTest(changed=changed):
                self.reply = completed([post(**changed)])
                with self.assertRaises(OperationError):
                    self.search(planned=False, query=json.dumps(changed))

    def test_empty_native_result_is_incomplete_coverage_and_replays_without_inference(self):
        save_plan(self.project, "x")
        self.reply = completed([])
        self.search()
        self.assertTrue(self.search()["replayed"])
        self.assertEqual(1, len(self.requests))
        history = next(iter(Ledger(self.project).data["x_search_history"].values()))
        self.assertEqual(1, history["tool_calls"])
        self.assertEqual([], history["rows"])
        self.assertIn("incomplete", history["coverage"])

    def test_interruption_after_native_result_recovers_without_another_request_or_query(self):
        save_plan(self.project, "x")
        save = Ledger.save_many

        def interrupted(ledger, operation, candidates=None):
            if operation == "search-outcome":
                raise OSError("Synthetic interruption after durable native result")
            return save(ledger, operation, candidates)

        with patch.object(Ledger, "save_many", new=interrupted), self.assertRaises(OperationError):
            self.search()
        self.assertEqual(1, len(self.requests))
        result = self.search()
        self.assertTrue(result["replayed"])
        self.assertEqual(1, len(result["items"]))
        self.assertEqual(URL, result["items"][0]["source_url"])
        self.assertEqual(1, progress_row(self.project)["queries_used"])
        self.assertEqual(1, len(self.requests))

    def test_transport_rejection_omits_secret_response_and_redirect_is_disabled(self):
        save_plan(self.project, "x")
        error = HTTPError(grok.PROXY, 401, SECRET, HTTPMessage(), io.BytesIO(SECRET.encode()))
        with patch.object(
            grok,
            "build_opener",
            return_value=SimpleNamespace(open=lambda *args, **kwargs: (_ for _ in ()).throw(error)),
        ):
            result = self.search()
        self.assertIn("HTTP 401", result["search_progress"][0]["attempts"][0]["error"])
        self.assertNotIn(SECRET, json.dumps(result))
        self.assertIsNone(
            grok._NoRedirect().redirect_request(
                Request(grok.PROXY), io.BytesIO(), 302, "", HTTPMessage(), "https://untrusted.example/"
            )
        )

    def test_refresh_failure_preserves_private_account_and_requires_local_login(self):
        self.record["expires_at"] = (datetime.now(UTC) - timedelta(hours=1)).isoformat()
        self.write_auth()
        before = self.auth.read_bytes()
        save_plan(self.project, "x")
        with patch.object(grok, "_post", return_value=b'{"error":"invalid_grant"}'):
            result = self.search()
        self.assertEqual(before, self.auth.read_bytes())
        self.assertEqual([], self.requests)
        self.assertIn("Re-login locally", result["search_progress"][0]["attempts"][0]["error"])
        self.assertEqual([], list(self.private.glob(".getbrolls-*")))

    @skip_unless_ffmpeg
    def test_discovered_post_and_supplied_capture_reach_existing_storyboard_and_human_rights_gates(self):
        save_plan(self.project, "x")
        row = self.search()["items"][0]
        image = self.project / "viewed.jpg"
        synth_image(image)
        original = call(
            self.project,
            "resolve",
            "--file",
            str(image),
            "--asset-type",
            "web_screenshot",
            "--source-url",
            URL,
            "--original-for",
            row["id"],
            "--original-conditions",
            "Synthetic original public post capture; separate from its search excerpt",
        )
        call(self.project, "preview", "--candidate", original["id"])
        confirm(
            self.project,
            original["id"],
            "poster",
            ("Synthetic post actually viewed", "Visible fixture fits the fragment"),
        )
        self.assertEqual(1, progress_row(self.project)["suitable_count"])
        self.assertIn(URL, storyboard(self.project))
        with self.assertRaises(OperationError):
            call(self.project, "fetch", "--candidate", original["id"])
        self.assertEqual("pending", Ledger(self.project).get(original["id"])["approval"]["status"])
        self.assertEqual("unknown", Ledger(self.project).get(original["id"])["rights"]["status"])
