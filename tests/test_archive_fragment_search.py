"""Archive item/file contracts and observable fragment search through the audited CLI."""

import copy
import json
import os
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import _isolation  # noqa: F401
from _media import skip_unless_ffmpeg, synth_video
from _paths import ROOT  # noqa: F401

from getbrolls import archive, providers
from getbrolls.cli import parse_args
from getbrolls.commands import execute
from getbrolls.config import load_env
from getbrolls.ledger import Ledger
from getbrolls.runtime import OperationError, audited, redact

META = {
    "metadata": {
        "title": "Synthetic collection",
        "creator": "Fixture creator",
        "date": "1950-01-01",
        "collection": ["fixture"],
    },
    "files": [
        {
            "name": "film-one.mp4",
            "source": "original",
            "format": "MPEG4",
            "length": "6",
            "width": "160",
            "height": "90",
        },
        {
            "name": "film-one-small.mp4",
            "original": "film-one.mp4",
            "source": "derivative",
            "format": "MPEG4",
            "height": "45",
        },
        {"name": "film-two.mp4", "source": "original", "format": "MPEG4", "length": "6"},
        {"name": "film-one.srt", "format": "SubRip"},
        {"name": "__ia_thumb.jpg", "format": "JPEG Thumb"},
    ],
}


def brief_data():
    return {
        "version": 1,
        "video": {"title": "Fixture", "objective": "Original scenario", "delivery": {"format": "native"}},
        "rights": {"posture": "per_item_evidence", "stock_allowed": False},
        "defaults": {"allowed_sources": ["archive"], "intent": "literal", "duration_hint_s": 2, "stock": False},
        "beats": [{"id": "opening", "target": "archival factory", "narration": "Original scenario narration"}],
    }


def write_brief(project, data=None):
    (project / "BRIEF.md").write_text("```json\n" + json.dumps(data or brief_data()) + "\n```", encoding="utf-8")


def call(project, *arguments):
    env_file = project / "empty.env"
    env_file.touch()
    args = parse_args(["--env-file", str(env_file), *arguments, "--project", str(project)])
    return audited(args, execute)


def plan(project):
    return call(
        project,
        "search-plan",
        "--shot",
        "opening",
        "--provider",
        "archive",
        "--reason",
        "Archive holds this event",
        "--expected-material",
        "Factory film",
    )


def search(project, query="factory", *extra):
    return call(project, "search", "--planned", "--shot", "opening", "--query", query, *extra)


def assess(project, query):
    return call(
        project,
        "search-assess",
        "--shot",
        "opening",
        "--query",
        query,
        "--assessment",
        "Results reviewed; inspect the factory scene next",
    )


class ArchiveContracts(unittest.TestCase):
    def test_multiple_originals_and_derivatives_keep_separate_identity(self):
        rows = archive.files("fixture", copy.deepcopy(META))
        self.assertEqual(2, len(rows))
        self.assertEqual("film-one.mp4", rows[0]["archive"]["asset_file"])
        self.assertEqual(2, len(rows[0]["archive"]["representations"]))
        self.assertEqual("film-one.mp4", rows[0]["archive"]["selected_file"])
        self.assertEqual("film-one.srt", rows[0]["archive"]["captions"][0]["file"])
        self.assertEqual("unknown", rows[0]["rights"]["status"])
        self.assertNotEqual(rows[0]["id"], rows[1]["id"])

    @patch.object(archive, "metadata", return_value=META)
    def test_item_resolution_requires_actual_file_and_refresh_keeps_selection(self, metadata):
        with self.assertRaisesRegex(ValueError, "--archive-file"):
            providers.resolve("https://archive.org/details/fixture")
        selected = providers.resolve("https://archive.org/details/fixture", archive_file="film-one-small.mp4")
        self.assertEqual("film-one.mp4", selected["archive"]["asset_file"])
        self.assertEqual("film-one-small.mp4", providers.refresh(selected)["archive"]["selected_file"])
        self.assertEqual("https://archive.org/details/fixture", selected["source_url"])

    def test_restricted_file_is_not_publicly_acquirable(self):
        data = copy.deepcopy(META)
        data["metadata"]["access-restricted-item"] = "true"
        rows = archive.files("fixture", data)
        self.assertTrue(all(r["media_url"] is None for r in rows))
        self.assertTrue(all(r["acquisition"]["status"] == "unavailable" for r in rows))
        self.assertEqual("unknown", rows[0]["rights"]["status"])

    def test_storage_url_remains_on_archive_and_rejects_traversal_hosts(self):
        data = copy.deepcopy(META)
        data.update(d1="ia800000.us.archive.org", dir="/1/items/fixture")
        row = archive.files("fixture", data)[0]
        self.assertEqual("https://ia800000.us.archive.org/1/items/fixture/film-one.mp4", row["media_url"])
        data["d1"] = "attacker.example/archive.org"
        self.assertTrue(archive.files("fixture", data)[0]["media_url"].startswith("https://archive.org/download/"))

    @patch.object(archive, "get_json")
    def test_bounded_search_looks_up_selected_items_and_retains_actual_files(self, get):
        get.side_effect = [{"response": {"docs": [{"identifier": "fixture"}, {"identifier": "unused"}]}}, META]
        rows = providers.search("archive", "collection:fixture", 2, "video")
        self.assertEqual(2, len(rows))
        self.assertEqual(2, get.call_count)
        self.assertEqual("collection:fixture", rows[0]["query"])
        self.assertIn("mediatype:movies", get.call_args_list[0].args[1]["q"])

    def test_image_selection_does_not_use_search_thumbnail(self):
        data = copy.deepcopy(META)
        data["files"].append({"name": "original.tif", "source": "original"})
        rows = archive.files("fixture", data, "image")
        self.assertEqual(["original.tif"], [r["archive"]["selected_file"] for r in rows])
        self.assertEqual("image", rows[0]["asset_type"])

    def test_missing_metadata_fields_and_malformed_file_names_stay_safe(self):
        data = {
            "is_dark": "false",
            "files": [
                {"name": "valid.mp4"},
                {"name": "../bad.mp4"},
                {"name": "nested\\bad.mp4"},
                {"name": "bad.mp4", "original": []},
            ],
        }
        rows = archive.files("fixture", data)
        self.assertEqual(2, len(rows))
        self.assertIsNone(rows[0]["media"]["width"])
        self.assertIsNone(rows[0]["archive"]["source_date"])
        self.assertEqual("available", rows[0]["acquisition"]["status"])

    def test_bad_metadata_and_search_responses_report_provider_errors(self):
        for data in ([], {"files": [], "metadata": None}, {"error": "restricted"}):
            with (
                self.subTest(data=data),
                patch.object(archive, "get_json", return_value=data),
                self.assertRaises(ValueError),
            ):
                archive.metadata("fixture")
        with patch.object(archive, "get_json", return_value={"response": {}}), self.assertRaises(ValueError):
            archive.search("factory", 1)


class FragmentSearch(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.project = Path(self.tmp.name)
        write_brief(self.project)

    def test_three_queries_language_budget_idempotence_and_assessment(self):
        plan(self.project)
        rows = archive.files("fixture", copy.deepcopy(META))
        with patch.object(providers, "search", return_value=rows) as provider:
            first = search(self.project, "factory", "--language", "en")
            again = search(self.project, "factory", "--language", "fr")
            self.assertTrue(again["replayed"])
            self.assertEqual(1, provider.call_count)
            self.assertEqual(1, again["search_progress"][0]["queries_used"])
            self.assertEqual(2, len(Ledger(self.project, recover=False).data["items"]))
            with self.assertRaisesRegex(OperationError, "Assess prior"):
                search(self.project, "industrial machinery")
            assess(self.project, "factory")
            search(self.project, "industrial machinery", "--language", "fr")
            assess(self.project, "industrial machinery")
            search(self.project, "production line", "--language", "de")
            with self.assertRaisesRegex(OperationError, "three meaningful"):
                search(self.project, "manufacturing")
            self.assertEqual(3, provider.call_count)
            self.assertEqual(2, len(Ledger(self.project, recover=False).data["items"]))
        self.assertFalse(first["search_progress"][0]["target_reached"])
        self.assertEqual("pending", first["items"][0]["approval"]["status"])
        self.assertEqual("Original scenario narration", first["items"][0]["narration"])
        self.assertEqual(3, plan(self.project)["search_progress"][0]["queries_used"])

    def test_fallback_spends_the_same_allowance_and_fourth_dispatch_is_refused(self):
        plan(self.project)
        with patch.object(providers, "search", return_value=[]) as provider:
            result = search(self.project, "the factory production line machinery in the old industrial district")
            self.assertEqual(2, result["search_progress"][0]["queries_used"])
            search(self.project, "another formulation")
            with self.assertRaises(OperationError):
                search(self.project, "fourth formulation")
            self.assertEqual(3, provider.call_count)

    def test_interrupted_dispatch_survives_restart_without_automatic_retry(self):
        plan(self.project)
        with (
            patch.object(providers, "search", side_effect=KeyboardInterrupt),
            self.assertRaisesRegex(OperationError, "interrompida"),
        ):
            search(self.project)
        with patch.object(providers, "search") as provider:
            result = search(self.project)
            provider.assert_not_called()
        self.assertTrue(result["interrupted_or_uncertain"])
        self.assertEqual(1, result["search_progress"][0]["queries_used"])

    def test_dispatch_journal_recovery_and_status_are_read_only(self):
        from getbrolls import ledger as storage

        plan(self.project)
        original = storage.atomic_write

        def fail_manifest(path, text):
            if path.name == "manifest.json":
                raise OSError("Synthetic interrupted manifest write")
            return original(path, text)

        with (
            patch.object(storage, "atomic_write", side_effect=fail_manifest),
            patch.object(providers, "search") as provider,
        ):
            with self.assertRaises(OperationError):
                search(self.project)
            provider.assert_not_called()
        pending = self.project / "brolls/.pending-transaction.json"
        before = pending.read_bytes()
        with patch("getbrolls.runtime._acquire_lock", side_effect=AssertionError("Status took a lock")):
            result = call(self.project, "status")
        self.assertEqual(before, pending.read_bytes())
        self.assertTrue(result["journal"]["recovered_write"])
        self.assertIsNone(result["search_progress"][0]["queries_remaining"])
        self.assertEqual("recover_pending_write", result["search_progress"][0]["next"])
        with patch.object(providers, "search") as provider:
            result = search(self.project)
            provider.assert_not_called()
        self.assertFalse(pending.exists())
        self.assertEqual(1, result["search_progress"][0]["queries_used"])

    def test_context_changes_do_not_reset_existing_budget(self):
        plan(self.project)
        with patch.object(providers, "search", return_value=[]):
            search(self.project)
        data = brief_data()
        data["beats"][0]["narration"] = "Changed scenario"
        write_brief(self.project, data)
        with self.assertRaisesRegex(OperationError, "context changed"):
            search(self.project)
        with self.assertRaisesRegex(OperationError, "reset"):
            plan(self.project)
        self.assertEqual(1, call(self.project, "status")["search_progress"][0]["queries_used"])

    def test_two_fragments_keep_independent_plans_and_budgets(self):
        data = brief_data()
        data["beats"].append(
            {"id": "closing", "target": "Archive transport", "narration": "Original closing narration"}
        )
        write_brief(self.project, data)
        plan(self.project)
        call(
            self.project,
            "search-plan",
            "--shot",
            "closing",
            "--provider",
            "archive",
            "--reason",
            "Transport history",
            "--expected-material",
            "Train footage",
        )
        with patch.object(providers, "search", return_value=[]):
            search(self.project)
        progress = {r["fragment"]: r for r in call(self.project, "status")["search_progress"]}
        self.assertEqual(1, progress["opening"]["queries_used"])
        self.assertEqual(0, progress["closing"]["queries_used"])
        self.assertEqual("Original closing narration", progress["closing"]["context"]["narration"])

    def test_restricted_archive_file_never_falls_back_to_other_acquisition(self):
        data = copy.deepcopy(META)
        data["metadata"]["access-restricted-item"] = "true"
        with patch.object(archive, "metadata", return_value=data):
            item = call(
                self.project,
                "resolve",
                "--url",
                "https://archive.org/details/fixture",
                "--archive-file",
                "film-one.mp4",
            )
            with (
                patch("getbrolls.social.probe_remote") as fallback,
                self.assertRaisesRegex(OperationError, "requires separate access"),
            ):
                call(self.project, "inspect", "--candidate", item["id"])
            fallback.assert_not_called()
            with (
                patch("getbrolls.http.download") as download,
                self.assertRaisesRegex(OperationError, "requires separate access"),
            ):
                call(self.project, "preview", "--candidate", item["id"], "--start", "0", "--end", "2")
            download.assert_not_called()

    def test_dry_run_leaves_plan_and_candidates_byte_identical(self):
        plan(self.project)
        path = self.project / "brolls/manifest.json"
        before = path.read_bytes()
        with patch.object(providers, "search") as provider:
            result = search(self.project, "factory", "--dry-run")
            provider.assert_not_called()
            self.assertEqual("factory", result["would_dispatch"]["query"])
        self.assertEqual(before, path.read_bytes())

    def test_provider_errors_are_persisted_redacted_and_consume_the_allowance(self):
        plan(self.project)
        with (
            patch.dict(os.environ, {"DVIDS_API_KEY": "fixture-secret"}),
            patch.object(providers, "search", side_effect=ValueError("access failed fixture-secret")) as provider,
        ):
            for query in ("factory", "industry", "production"):
                result = search(self.project, query)
                self.assertEqual("access_or_provider_error", result["attempt"]["status"])
                self.assertNotIn("fixture-secret", json.dumps(result))
            with self.assertRaises(OperationError):
                search(self.project, "fourth")
            self.assertEqual(3, provider.call_count)
        self.assertEqual(3, call(self.project, "status")["search_progress"][0]["queries_used"])

    def test_media_filter_changes_are_new_dispatches_in_the_same_allowance(self):
        plan(self.project)
        with patch.object(providers, "search", return_value=[]) as provider:
            search(self.project, "factory", "--media", "video")
            result = search(self.project, "factory", "--media", "image")
            self.assertEqual(2, provider.call_count)
            self.assertEqual(2, result["search_progress"][0]["queries_used"])
            with self.assertRaisesRegex(OperationError, "--media"):
                assess(self.project, "factory")
            call(
                self.project,
                "search-assess",
                "--shot",
                "opening",
                "--query",
                "factory",
                "--media",
                "image",
                "--assessment",
                "No still image found",
            )

    def test_unknown_fragment_disallowed_catalog_and_empty_reason_are_rejected(self):
        for extra in (("--shot", "unknown"), ("--provider", "youtube"), ("--reason", "")):
            with self.subTest(extra=extra), self.assertRaises(OperationError):
                call(
                    self.project,
                    "search-plan",
                    "--shot",
                    "opening",
                    "--provider",
                    "archive",
                    "--reason",
                    "Fits",
                    "--expected-material",
                    "Film",
                    *extra,
                )

    @skip_unless_ffmpeg
    @patch.object(archive, "metadata", return_value=META)
    def test_synthetic_archive_inspect_preview_review_and_independent_final_gates(self, metadata):
        source = self.project / "synthetic.mp4"
        synth_video(source, size="320x180")
        plan(self.project)

        def download(url, target, **kwargs):
            if url.endswith(".srt"):
                Path(target).write_text(
                    "1\n00:00:01,000 --> 00:00:03,000\nFactory production line\n\n", encoding="utf-8"
                )
            else:
                shutil.copyfile(source, target)

        with (
            patch.object(providers, "search", return_value=archive.files("fixture", META)),
            patch("getbrolls.http.download", side_effect=download),
        ):
            result = search(self.project)
            self.assertTrue(result["items"])
            selected = call(
                self.project,
                "resolve",
                "--url",
                "https://archive.org/details/fixture",
                "--archive-file",
                "film-one-small.mp4",
                "--shot",
                "opening",
            )
            ident = selected["id"]
            self.assertEqual("Original scenario narration", selected["narration"])
            self.assertEqual("film-one-small.mp4", selected["archive"]["selected_file"])
            inspection = call(self.project, "inspect", "--candidate", ident, "--query", "Factory")
            self.assertEqual("subtitle", inspection["candidate_windows"][0]["source"])
            self.assertEqual(320, Ledger(self.project, recover=False).get(ident)["media"]["width"])
            call(self.project, "preview", "--candidate", ident, "--start", "1", "--end", "3")
            page = call(self.project, "review", "--ready-only")
            self.assertIn(
                "Original scenario narration", (self.project / "brolls/review.html").read_text(encoding="utf-8")
            )
            self.assertTrue(page)
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
                "Synthetic test approval",
            )
            with self.assertRaises(OperationError):
                call(self.project, "fetch", "--candidate", ident)
            call(
                self.project,
                "permit",
                "--candidate",
                ident,
                "--evidence",
                "Synthetic fixture created by this automated test",
            )
            call(self.project, "fetch", "--candidate", ident)
            call(self.project, "verify")
            self.assertEqual("verified", Ledger(self.project, recover=False).get(ident)["state"])
            delivery = call(self.project, "deliver")
            self.assertEqual(ident, delivery["items"][0]["id"])
            self.assertTrue((self.project / "entrega/README.md").is_file())


class CatalogConfiguration(unittest.TestCase):
    def test_new_settings_load_without_relaxing_unknown_keys_and_never_select_billing(self):
        from getbrolls.config import KEYS

        names = (
            "DVIDS_API_KEY",
            "DVIDS_CLIENT_SECRET",
            "EUROPEANA_API_KEY",
            "NARA_API_KEY",
            "MAPILLARY_TOKEN",
            "TELEGRAM_API_ID",
            "TELEGRAM_API_HASH",
            "TELEGRAM_SESSION",
            "BROLL_TELEGRAM_CHANNELS",
            "GEMINI_API_KEY",
            "XAI_API_KEY",
        )
        self.assertTrue(set(names) <= KEYS)
        with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ, {}, clear=True):
            path = Path(tmp) / "fixture.env"
            path.write_text("\n".join(n + "=fixture-value" for n in names), encoding="utf-8")
            os.environ["DVIDS_API_KEY"] = "process-precedence"
            load_env(path)
            self.assertEqual("process-precedence", os.environ["DVIDS_API_KEY"])
            self.assertNotIn("fixture-value", json.dumps(providers.capabilities()))
            self.assertNotIn("fixture-value", redact("fixture-value"))
            self.assertFalse(providers.capabilities()["x"]["search"])
            path.write_text("UNKNOWN_SETTING=value", encoding="utf-8")
            with self.assertRaises(ValueError):
                load_env(path)

    def test_inventory_is_twenty_catalogs_plus_local_not_twenty_working_adapters(self):
        capabilities = providers.capabilities()
        self.assertEqual(21, len(capabilities))
        self.assertTrue(capabilities["archive"]["search"])
        self.assertEqual("planned", capabilities["telegram"]["implementation"])
        self.assertEqual("unverified", capabilities["telegram"]["live"])
        self.assertFalse(capabilities["instagram"]["search"])
