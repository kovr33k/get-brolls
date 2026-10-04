"""Audited browser attempt/import contracts; synthetic media, no website API calls."""

import json
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import _isolation  # noqa: F401
from _media import skip_unless_ffmpeg, synth_video
from _paths import ROOT  # noqa: F401
from test_archive_fragment_search import META, confirm
from test_search_chains import advance, brief_data, call, plan_chain, progress, stored, write_brief

from getbrolls import archive, providers
from getbrolls.ledger import Ledger
from getbrolls.runtime import OperationError

UN = "https://media.un.org/avlibrary/en/asset/d341/d3411148"
DESTOCKD = "https://destockd.com/#/shot/SYMPHONY%20IN%20F/shot_080"
SOCIAL = {
    "instagram": "https://www.instagram.com/reel/ABC123/",
    "tiktok": "https://www.tiktok.com/@fixture/video/1234567890123456789",
    "un_avlibrary": UN,
    "destockd": DESTOCKD,
}


class BrowserCatalogFragments(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.project = Path(self.temp.name)
        write_brief(self.project, brief_data(list(SOCIAL)))

    def reserve(self, query="factory", *extra):
        return call(self.project, "search-browser", "--shot", "opening", "--query", query, *extra)

    def complete(self, attempt, entries=None, outcome="results", *extra):
        args = [
            "search-import",
            "--shot",
            "opening",
            "--attempt",
            attempt["id"],
            "--outcome",
            outcome,
            "--assessment",
            "Observed results reviewed against the fragment.",
        ]
        if entries is not None:
            path = self.project / "observed.json"
            path.write_text(json.dumps(entries), encoding="utf-8")
            args.extend(("--results", str(path)))
        return call(self.project, *args, *extra)

    def test_reservation_is_durable_consumed_and_not_a_search(self):
        plan_chain(self.project, ["instagram"])
        with patch.object(providers, "search") as search, patch("getbrolls.http.get_json") as network:
            first = self.reserve()["attempt"]
            search.assert_not_called()
            network.assert_not_called()
        self.assertEqual("dispatched", stored(self.project)["attempts"][0]["status"])
        report = progress(self.project)
        self.assertEqual(1, report["queries_used"])
        self.assertEqual("complete_browser_attempt", report["next"])
        replay = self.reserve("  FACTORY  ", "--language", "pt")
        self.assertTrue(replay["replayed"])
        self.assertEqual(first["id"], replay["attempt"]["id"])
        self.assertEqual(1, progress(self.project)["queries_used"])
        with self.assertRaisesRegex(OperationError, "Assess prior results"):
            self.reserve("different meaningful query")

    def test_all_four_catalogs_import_observed_metadata_without_network(self):
        for catalog, url in SOCIAL.items():
            with self.subTest(catalog=catalog), tempfile.TemporaryDirectory() as folder:
                self.project = Path(folder)
                write_brief(self.project, brief_data([catalog]))
                plan_chain(self.project, [catalog])
                attempt = self.reserve()["attempt"]
                with patch.object(providers, "search") as search, patch("getbrolls.http.get_json") as network:
                    result = self.complete(
                        attempt,
                        [
                            {
                                "url": url,
                                "title": "Observed factory",
                                "account": "Public fixture account",
                                "date": "1957-01-01",
                                "language": "en",
                                "description": "Observed public caption.",
                            }
                        ],
                        "results",
                        "--coverage",
                        "assessed",
                    )
                    search.assert_not_called()
                    network.assert_not_called()
                row = result["items"][0]
                self.assertEqual("opening", row["shot"])
                self.assertEqual("Public fixture account", row["creator"]["name"])
                self.assertEqual("1957-01-01", row["source_metadata"]["date"])
                self.assertEqual("unknown", row["rights"]["status"])
                self.assertEqual("pending", row["approval"]["status"])
                self.assertEqual(0, progress(self.project)["suitable_count"])
                history = (self.project / "brolls/events.jsonl").read_bytes()
                replay = self.complete(
                    attempt,
                    [
                        {
                            "url": url,
                            "title": "Observed factory",
                            "account": "Public fixture account",
                            "date": "1957-01-01",
                            "language": "en",
                            "description": "Observed public caption.",
                        }
                    ],
                    "results",
                    "--coverage",
                    "assessed",
                )
                self.assertTrue(replay["replayed"])
                self.assertEqual(history, (self.project / "brolls/events.jsonl").read_bytes())
                with self.assertRaisesRegex(OperationError, "cannot rewrite"):
                    self.complete(attempt, [{"url": url, "title": "Changed history"}])

    def test_empty_access_failure_and_three_query_limit(self):
        plan_chain(self.project, ["un_avlibrary", "destockd"])
        for index in range(3):
            attempt = self.reserve(f"factory query {index}")["attempt"]
            if index == 1:
                with self.assertRaisesRegex(OperationError, "Access failure"):
                    self.complete(attempt, None, "access-failure", "--coverage", "assessed")
                self.complete(attempt, None, "access-failure")
            else:
                self.complete(attempt, None, "empty")
        self.assertEqual(3, progress(self.project)["queries_used"])
        with self.assertRaises(OperationError):
            self.reserve("fourth meaningful query")
        advance(self.project, "un_avlibrary", "allowance-exhausted", "Three real browser attempts assessed")
        self.assertEqual("destockd", progress(self.project)["catalog"])
        self.assertEqual(3, progress(self.project)["fragment_queries_used"])
        self.assertEqual(0, progress(self.project)["queries_used"])

    def test_dry_runs_do_not_change_manifest_or_events(self):
        plan_chain(self.project, ["un_avlibrary"])
        paths = [self.project / "brolls" / name for name in ("manifest.json", "events.jsonl")]
        before = [path.read_bytes() for path in paths]
        self.reserve("factory", "--dry-run")
        self.assertEqual(before, [path.read_bytes() for path in paths])
        attempt = self.reserve()["attempt"]
        before = [path.read_bytes() for path in paths]
        self.complete(attempt, [{"asset_id": "d3411148"}], "results", "--dry-run")
        self.assertEqual(before, [path.read_bytes() for path in paths])
        self.assertEqual([], Ledger(self.project, recover=False).data["items"])

    def test_invalid_imports_preserve_reserved_budget_without_partial_candidates(self):
        plan_chain(self.project, ["un_avlibrary"])
        attempt = self.reserve()["attempt"]
        bad = [
            {"url": SOCIAL["tiktok"]},
            {"url": UN, "asset_id": "d3419999"},
            {"url": UN, "preview_url": "https://cdn.example.org/clip.mp4?token=private"},
            {"url": UN, "preview_url": "https://cdn.example.org/clip.mp4?Expires=100"},
            {"url": UN, "preview_url": "blob:https://example.org/123"},
            {"url": UN, "cookie": "private"},
            {"url": UN, "source_interval": {"start_s": 3, "end_s": 1}},
            {"url": UN, "source_interval": {"start_s": True, "end_s": 4}},
        ]
        for entry in bad:
            with self.subTest(entry=entry), self.assertRaises(OperationError):
                self.complete(attempt, [{"url": UN}, entry])
            self.assertEqual([], Ledger(self.project, recover=False).data["items"])
            self.assertEqual(1, progress(self.project)["queries_used"])
            self.assertEqual("dispatched", stored(self.project)["attempts"][0]["status"])

    def test_browser_cannot_replay_a_keyword_catalog_attempt(self):
        write_brief(self.project, brief_data(["archive"]))
        plan_chain(self.project, ["archive"])
        with patch.object(providers, "search", return_value=[]):
            call(self.project, "search", "--planned", "--shot", "opening", "--query", "factory")
        with self.assertRaisesRegex(OperationError, "supported browser"):
            self.reserve()
        self.assertEqual(1, progress(self.project)["queries_used"])

    def test_interrupted_import_recovers_candidates_and_outcome_together_once(self):
        plan_chain(self.project, ["un_avlibrary"])
        attempt = self.reserve()["attempt"]
        with (
            patch.object(Ledger, "_finish_transaction", side_effect=OSError("Synthetic interruption")),
            self.assertRaises(OperationError),
        ):
            self.complete(attempt, [{"url": UN}])
        pending = self.project / "brolls/.pending-transaction.json"
        self.assertTrue(pending.exists())
        call(self.project, "status")
        self.assertTrue(pending.exists())
        replay = self.complete(attempt, [{"url": UN}])
        self.assertTrue(replay["replayed"])
        self.assertFalse(pending.exists())
        self.assertEqual(1, len(Ledger(self.project, recover=False).data["items"]))
        events = (self.project / "brolls/events.jsonl").read_text().splitlines()
        self.assertEqual(1, sum(json.loads(line)["operation"] == "browser-search-outcome" for line in events))

    def test_locator_direct_urls_asset_id_and_unknown_timing(self):
        with patch("getbrolls.http.get_json") as network:
            un = call(self.project, "resolve", "--un-asset-id", "d3411148")
            unifeed = call(self.project, "resolve", "--un-asset-id", "u120118c")
            shot = call(self.project, "resolve", "--url", DESTOCKD)
            network.assert_not_called()
        self.assertEqual(UN, un["source_url"])
        self.assertEqual("un_avlibrary", unifeed["provider"])
        self.assertTrue(un["locator"]["license_required"])
        self.assertEqual("shot_080", shot["locator"]["shot_id"])
        self.assertNotIn("source_interval", shot["locator"])
        self.assertNotIn("preview_url", shot["locator"])
        self.assertIsNone(shot["media"]["duration_s"])

    def test_tiktok_short_links_need_canonical_browser_result(self):
        plan_chain(self.project, ["tiktok"])
        attempt = self.reserve()["attempt"]
        with self.assertRaises(OperationError):
            self.complete(attempt, [{"url": "https://vm.tiktok.com/short/"}])
        self.assertEqual(1, progress(self.project)["queries_used"])

    def test_destockd_archive_original_keeps_separate_identity_and_interval(self):
        plan_chain(self.project, ["destockd"])
        attempt = self.reserve()["attempt"]
        locator = self.complete(
            attempt,
            [
                {
                    "url": DESTOCKD,
                    "archive_url": "https://archive.org/details/fixture",
                    "archive_file": "film-one.mp4",
                    "source_interval": {"start_s": 20, "end_s": 30},
                }
            ],
        )["items"][0]
        with patch.object(archive, "metadata", return_value=META):
            original = call(
                self.project,
                "resolve",
                "--url",
                "https://archive.org/details/fixture",
                "--archive-file",
                "film-one.mp4",
                "--original-for",
                locator["id"],
            )
            with self.assertRaisesRegex(OperationError, "does not match"):
                call(
                    self.project,
                    "resolve",
                    "--url",
                    "https://archive.org/details/wrong",
                    "--archive-file",
                    "film-one.mp4",
                    "--original-for",
                    locator["id"],
                )
        self.assertNotEqual(locator["id"], original["id"])
        self.assertEqual({"start_s": 20, "end_s": 30}, original["source_reference"]["source_interval"])
        self.assertIsNone(original["segment"]["start_s"])
        self.assertEqual("film-one.mp4", original["archive"]["selected_file"])
        self.assertEqual("pending", original["approval"]["status"])
        self.assertEqual("unknown", original["rights"]["status"])

    @skip_unless_ffmpeg
    def test_preview_is_deferred_and_supplied_original_uses_common_review_flow(self):
        plan_chain(self.project, ["un_avlibrary"])
        source = self.project / "synthetic.mp4"
        synth_video(source)
        attempt = self.reserve()["attempt"]
        locator = self.complete(
            attempt,
            [
                {
                    "url": UN,
                    "title": "Synthetic factory",
                    "preview_url": "https://cdn.example.org/public-preview.mp4",
                    "shotlist": "Fixture wide factory shot",
                    "source_interval": {"start_s": 10, "end_s": 16},
                }
            ],
        )["items"][0]
        ident = locator["id"]

        def download(url, target, **kwargs):
            shutil.copyfile(source, target)

        with patch("getbrolls.http.download", side_effect=download):
            call(self.project, "inspect", "--candidate", ident)
            call(self.project, "preview", "--candidate", ident, "--start", "1", "--end", "3")
        confirm(self.project, ident)
        self.assertEqual(0, progress(self.project)["suitable_count"])
        self.assertTrue(progress(self.project)["deferred_options"])
        with self.assertRaises(OperationError):
            call(self.project, "fetch", "--candidate", ident)
        call(
            self.project,
            "approve",
            "--candidate",
            ident,
            "--by",
            "Synthetic fixture reviewer",
            "--channel",
            "chat",
            "--statement",
            "Synthetic fixture preview approval",
        )
        call(self.project, "permit", "--candidate", ident, "--evidence", "Synthetic fixture media")
        with self.assertRaisesRegex(OperationError, "somente referência"):
            call(self.project, "fetch", "--candidate", ident)
        original = call(
            self.project,
            "resolve",
            "--file",
            str(source),
            "--original-for",
            ident,
            "--original-conditions",
            "Synthetic supplied-original context; rights still require evidence.",
        )
        original_id = original["id"]
        self.assertEqual("opening", original["shot"])
        self.assertEqual("pending", original["approval"]["status"])
        self.assertEqual("unknown", original["rights"]["status"])
        from getbrolls.delivery import render_origin

        origin = render_origin(original, "fixture.mp4")
        self.assertIn(UN, origin)
        self.assertIn("Synthetic supplied-original context", origin)
        self.assertNotIn(str(source), origin)
        call(self.project, "inspect", "--candidate", original_id)
        call(self.project, "preview", "--candidate", original_id, "--start", "1", "--end", "3")
        self.assertEqual(1, Ledger(self.project, recover=False).get(original_id)["segment"]["start_s"])
        confirm(self.project, original_id)
        self.assertEqual(1, progress(self.project)["suitable_count"])
        call(self.project, "review", "--ready-only")
        page = (self.project / "brolls/review.html").read_text(encoding="utf-8")
        self.assertIn("d3411148", page)
        self.assertIn("Synthetic supplied-original context", page)
        with self.assertRaises(OperationError):
            call(self.project, "fetch", "--candidate", original_id)
        source.write_bytes(b"changed synthetic original")
        with self.assertRaisesRegex(OperationError, "Local original changed"):
            call(self.project, "inspect", "--candidate", original_id)

    def test_long_public_description_and_secret_text_are_validated_fully(self):
        plan_chain(self.project, ["un_avlibrary"])
        attempt = self.reserve()["attempt"]
        with self.assertRaises(OperationError):
            self.complete(attempt, [{"url": UN, "description": "x" * 1300 + " Cookie: private"}])
        imported = self.complete(attempt, [{"url": UN, "description": "x" * 1500}])["items"][0]
        self.assertEqual(1500, len(imported["source_metadata"]["description"]))
