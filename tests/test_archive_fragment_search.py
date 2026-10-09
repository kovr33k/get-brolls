"""Archive item/file contracts and observable fragment search through the audited CLI."""

import copy
import json
import os
import re
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import _isolation  # noqa: F401
from _media import skip_unless_ffmpeg, synth_image, synth_video
from _paths import ROOT  # noqa: F401

from getbrolls import archive, providers
from getbrolls.cli import parse_args
from getbrolls.commands import execute
from getbrolls.config import load_env
from getbrolls.fragment_search import validate_plans
from getbrolls.ledger import Ledger, digest
from getbrolls.models import candidate
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


def asset_row(item_id, asset, title=None, data=None):
    rows = archive.files(item_id, copy.deepcopy(data or META))
    row = copy.deepcopy(next(item for item in rows if item["archive"]["asset_file"] == asset))
    if title:
        row["title"] = title
    return row


def bound_id(row):
    return row["id"] + ":shot:opening"


def progress_row(project):
    return call(project, "status")["search_progress"][0]


def preview_clip(project, candidate, start, end, *extra):
    return call(
        project,
        "preview",
        "--candidate",
        candidate,
        "--start",
        str(start),
        "--end",
        str(end),
        *extra,
    )


def confirm(project, candidate_id, **options):
    viewed = options.get("viewed", "preview")
    arguments = [
        "search-confirm",
        "--shot",
        "opening",
        "--candidate",
        candidate_id,
        "--viewed",
        viewed,
        "--observation",
        options.get("observation", "Factory floor and moving machinery are visible in the viewed frames."),
        "--match",
        options.get("match", "The viewed interval shows the factory fragment in the scenario."),
        "--verdict",
        options.get("verdict", "suitable"),
    ]
    if viewed == "preview":
        arguments.extend(("--preview", options.get("preview", "gif")))
    elif options.get("preview"):
        arguments.extend(("--preview", options["preview"]))
    if options.get("distinctness"):
        arguments.extend(("--distinctness", options["distinctness"]))
    if options.get("duplicate_of"):
        arguments.extend(("--duplicate-of", options["duplicate_of"]))
    return call(project, *arguments)


def option_for(report, candidate):
    return next(
        option
        for option in report["suitable_options"]
        if any(item["candidate"] == candidate for item in option["identities"])
    )


def gallery_markup(page):
    return page.split('<div class="gallery">', 1)[1].split("<template", 1)[0]


def _restricted_metadata(identifier):
    data = copy.deepcopy(META)
    if identifier == "restricted-item":
        data["metadata"]["access-restricted-item"] = "true"
    return data


class SuitableOptions(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.project = Path(self.tmp.name)
        write_brief(self.project)

    def test_unviewed_hits_and_query_assessments_do_not_count(self):
        plan(self.project)
        rows = [
            asset_row("fixture", "film-one.mp4", "Factory original"),
            asset_row("fixture", "film-two.mp4", "Second camera"),
            asset_row("other-item", "film-one.mp4", "Repost metadata"),
        ]
        with patch.object(providers, "search", return_value=rows):
            result = search(self.project)
        self.assertIn("0 current suitable options", result["summary"]["line"])
        report = result["search_progress"][0]
        self.assertEqual(1, report["queries_used"])
        self.assertEqual(0, report["suitable_count"])
        self.assertEqual(3, len(report["raw_hits"]))
        self.assertEqual([], report["viewing_evidence"])
        self.assertFalse(report["target_reached"])
        self.assertIn("Query assessments are not viewing evidence", report["note"])
        assess(self.project, "factory")
        assessed = progress_row(self.project)
        self.assertEqual([], assessed["viewing_evidence"])
        self.assertEqual(0, assessed["suitable_count"])
        self.assertTrue(assessed["attempts"][0]["assessment"])
        with self.assertRaisesRegex(OperationError, "viewed interval"):
            confirm(self.project, bound_id(rows[0]))
        stored = Ledger(self.project, recover=False).data["search_plans"]["opening"]
        self.assertEqual([], stored.get("confirmations", []))
        self.assertEqual(1, progress_row(self.project)["queries_used"])
        with self.assertRaisesRegex(OperationError, "--option"):
            call(self.project, "preview", "--candidate", bound_id(rows[0]), "--scan", "--option", "opening")
        with self.assertRaisesRegex(OperationError, "--option"):
            call(
                self.project,
                "preview",
                "--candidate",
                bound_id(rows[0]),
                "--start",
                "0",
                "--end",
                "1",
                "--option",
                "Bad Name",
            )

    @skip_unless_ffmpeg
    @patch.object(archive, "metadata", return_value=META)
    def test_one_catalog_source_keeps_three_scenes_out_of_raw_hits(self, _metadata):
        source = self.project / "synthetic.mp4"
        synth_video(source, size="320x180")
        plan(self.project)
        primary = asset_row("fixture", "film-one.mp4", "Factory reel")

        def download(url, target, **kwargs):
            shutil.copyfile(source, target)

        with (
            patch.object(providers, "search", return_value=[primary]),
            patch("getbrolls.http.download", side_effect=download),
        ):
            found = search(self.project)
            root_id = found["items"][0]["id"]
            self.assertEqual([root_id], [hit["candidate"] for hit in found["search_progress"][0]["raw_hits"]])
            scenes = []
            for name, start in (("exterior", 0), ("office", 2), ("machinery", 4)):
                created = preview_clip(self.project, root_id, start, start + 1, "--option", name)
                self.assertEqual(root_id, created["selection"]["source_candidate"])
                confirm(
                    self.project,
                    created["id"],
                    preview="contact-sheet",
                    distinctness=f"Synthetic disjoint {name} moment.",
                    observation=f"The {name} frames show a separate factory action.",
                    match=f"The {name} interval matches a different part of the fragment.",
                )
                scenes.append(created["id"])
            manifest = self.project / "brolls/manifest.json"
            before = manifest.read_bytes()
            with patch("getbrolls.runtime._acquire_lock", side_effect=AssertionError("Status took a lock")):
                report = progress_row(self.project)
            self.assertEqual(before, manifest.read_bytes())
            self._assert_one_raw_source_and_three_scenes(report, root_id, scenes)
            stored = Ledger(self.project, recover=False)
            self.assertEqual([root_id], stored.data["search_plans"]["opening"]["attempts"][0]["candidates"])
            self.assertEqual({root_id, *scenes}, {item["id"] for item in stored.data["items"]})
            self.assertEqual(3, len(stored.data["search_plans"]["opening"]["confirmations"]))
            self._assert_storyboard_separates_raw_source(root_id, scenes)
            resolved = call(
                self.project,
                "resolve",
                "--url",
                "https://archive.org/details/fixture",
                "--archive-file",
                "film-two.mp4",
                "--shot",
                "opening",
            )
            kept = progress_row(self.project)
            self.assertEqual([root_id, resolved["id"]], [hit["candidate"] for hit in kept["raw_hits"]])
            self.assertEqual(3, kept["suitable_count"])
            self.assertEqual(1, kept["queries_used"])
            history = Ledger(self.project, recover=False).data["search_plans"]["opening"]["attempts"][0]["candidates"]
            self.assertEqual([root_id], history)
            self._assert_storyboard_separates_raw_source(root_id, scenes, extra_raw=(resolved["id"],))

    def _assert_one_raw_source_and_three_scenes(self, report, root_id, scenes):
        self.assertEqual([root_id], [hit["candidate"] for hit in report["raw_hits"]])
        self.assertEqual(3, report["suitable_count"])
        self.assertTrue(report["target_reached"])
        identities = [item["candidate"] for option in report["suitable_options"] for item in option["identities"]]
        self.assertEqual(scenes, identities)
        self.assertEqual(scenes, [decision["candidate"] for decision in report["pending_human_decisions"]])
        self.assertEqual(scenes, [record["candidate"] for record in report["viewing_evidence"]])
        self.assertTrue(
            all(record["current"] and record["verdict"] == "suitable" for record in report["viewing_evidence"])
        )

    def _assert_storyboard_separates_raw_source(self, root_id, scenes, extra_raw=()):
        call(self.project, "review", "--ready-only")
        page = (self.project / "brolls/review.html").read_text(encoding="utf-8")
        raw_section = page.split("<h4>Raw hits</h4>", 1)[1].split("<h4>Confirmed suitable options</h4>", 1)[0]
        self.assertIn(root_id, raw_section)
        self.assertEqual(1 + len(extra_raw), raw_section.count('class="raw-hit"'))
        for ident in extra_raw:
            self.assertIn(ident, raw_section)
        for scene in scenes:
            self.assertNotIn(scene, raw_section)
            self.assertIn(scene, page)
        self.assertIn("Original scenario narration", page)
        for interval in ("0.0–1.0 s", "2.0–3.0 s", "4.0–5.0 s"):
            self.assertIn(interval, page)

    @skip_unless_ffmpeg
    @patch.object(archive, "metadata", return_value=META)
    def test_duplicates_distinct_scenes_stop_and_restart(self, _metadata):
        source = self.project / "synthetic.mp4"
        synth_video(source, size="320x180")
        plan(self.project)
        raw = asset_row("raw-item", "film-two.mp4", "unopened metadata")
        primary = asset_row("fixture", "film-one.mp4", "Factory reel")
        repost = asset_row("repost-item", "film-two.mp4", "Repost of the shot")
        aside = asset_row("aside-item", "film-two.mp4", "Aside miss")
        rows = [raw, primary, repost, aside]

        def download(url, target, **kwargs):
            shutil.copyfile(source, target)

        with (
            patch.object(providers, "search", return_value=rows) as provider,
            patch("getbrolls.http.download", side_effect=download),
        ):
            search(self.project)
            self.assertEqual(1, provider.call_count)
            with self.assertRaisesRegex(OperationError, "viewed interval"):
                confirm(self.project, bound_id(raw))
            primary_id, opening_id = self._confirm_one_source_scenes(primary, repost)
            self._assert_search_stops(provider)
            self._confirm_late_and_unsuitable(primary_id, aside)
            self._assert_option_is_not_duplicated(primary_id, opening_id)
            self._assert_restart_and_storyboard(raw, opening_id)

    def _confirm_one_source_scenes(self, primary, repost):
        primary_id = bound_id(primary)
        copied = bound_id(repost)
        preview_clip(self.project, primary_id, 1, 3)
        confirm(self.project, primary_id)
        self.assertEqual(1, progress_row(self.project)["suitable_count"])
        self._approve_source(primary_id)
        edge = preview_clip(self.project, primary_id, 1.2, 3.2, "--option", "edge")
        self._assert_new_option_is_independent(primary_id, edge["id"])
        confirm(
            self.project,
            edge["id"],
            distinctness="different angle",
            observation="The same machinery is visible a fraction later.",
            match="This is the same factory shot with a small boundary change.",
        )
        grouped = option_for(progress_row(self.project), primary_id)
        self.assertEqual(1, progress_row(self.project)["suitable_count"])
        self.assertEqual("small_boundary_shift", grouped["grouped_reason"])
        self.assertEqual(["different angle"], grouped["unsupported_distinctness"])
        self.assertEqual({primary_id, edge["id"]}, {item["candidate"] for item in grouped["identities"]})
        preview_clip(self.project, copied, 1.05, 3.05)
        confirm(
            self.project,
            copied,
            observation="The same frames appear under another Archive item and file name.",
            match="This repost shows the same factory shot already counted.",
        )
        grouped = option_for(progress_row(self.project), primary_id)
        self.assertEqual(1, progress_row(self.project)["suitable_count"])
        self.assertEqual("repost", grouped["grouped_reason"])
        identities = {item["candidate"]: item for item in grouped["identities"]}
        self.assertEqual({primary_id, edge["id"], copied}, set(identities))
        self.assertEqual(identities[primary_id]["source_id"], identities[edge["id"]]["source_id"])
        self.assertNotEqual(identities[primary_id]["item_id"], identities[copied]["item_id"])
        hashes = {item["hashes"]["local_sha256"] for item in identities.values()}
        self.assertEqual(1, len(hashes))
        self.assertIsNotNone(next(iter(hashes)))
        opening = preview_clip(self.project, primary_id, 0, 1.2, "--option", "opening")
        confirm(
            self.project,
            opening["id"],
            distinctness="Opening moment before the counted shot",
            observation="The opening shows a different factory action.",
            match="This is a separate relevant moment of the same recording.",
        )
        middle = preview_clip(self.project, opening["id"], 2.6, 3.8, "--option", "middle")
        self.assertEqual(bound_id(primary), middle["selection"]["source_candidate"])
        confirm(
            self.project,
            middle["id"],
            distinctness="Middle action after the counted shot",
            observation="Workers move through a later part of the reel.",
            match="This moment is separate from the opening and the first shot.",
        )
        report = progress_row(self.project)
        self.assertEqual(3, report["suitable_count"])
        self.assertTrue(report["target_reached"])
        self.assertEqual(1, report["queries_used"])
        self.assertEqual("supported", option_for(report, opening["id"])["distinctness_support"])
        self.assertEqual("supported", option_for(report, middle["id"])["distinctness_support"])
        self.assertIsNone(option_for(report, opening["id"])["grouped_reason"])
        parent = Ledger(self.project, recover=False).get(primary_id)
        self.assertEqual(1, parent["segment"]["start_s"])
        self.assertEqual(3, parent["segment"]["end_s"])
        return primary_id, opening["id"]

    def _approve_source(self, ident):
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
        call(
            self.project,
            "permit",
            "--candidate",
            ident,
            "--evidence",
            "Synthetic fixture created by this automated test",
        )

    def _assert_new_option_is_independent(self, parent_id, child_id):
        ledger = Ledger(self.project, recover=False)
        parent, child = ledger.get(parent_id), ledger.get(child_id)
        self.assertNotEqual(parent_id, child_id)
        self.assertEqual(parent["source_id"], child["source_id"])
        self.assertEqual(parent["archive"]["asset_file"], child["archive"]["asset_file"])
        self.assertEqual(parent["local_sha256"], child["local_sha256"])
        self.assertEqual("approved", parent["approval"]["status"])
        self.assertEqual("permitted", parent["rights"]["status"])
        self.assertEqual(1, parent["segment"]["start_s"])
        self.assertEqual("pending", child["approval"]["status"])
        self.assertNotIn("signature", child["approval"])
        self.assertEqual("unknown", child["rights"]["status"])
        self.assertNotIn("basis", child["rights"])
        self.assertNotIn("Synthetic fixture created", " ".join(child["rights"]["evidence"]))
        self.assertFalse(child["output"]["verified"])
        self.assertIsNone(child["output"]["path"])
        self.assertNotIn("rejection", child)
        self.assertNotIn("visual_invalidation", child)
        self.assertEqual(1, sum(item["id"] == child_id for item in ledger.data["items"]))

    def _assert_search_stops(self, provider):
        with patch.object(providers, "search") as blocked:
            with self.assertRaisesRegex(OperationError, "Three suitable distinct"):
                search(self.project, "another formulation")
            blocked.assert_not_called()
        self.assertEqual(1, provider.call_count)
        self.assertEqual(1, len(Ledger(self.project, recover=False).data["search_plans"]["opening"]["attempts"]))
        with patch.object(providers, "search") as blocked:
            replay = search(self.project, "factory")
            blocked.assert_not_called()
        self.assertTrue(replay["replayed"])
        manifest = self.project / "brolls/manifest.json"
        before = manifest.read_bytes()
        with patch.object(providers, "search") as blocked:
            with self.assertRaisesRegex(OperationError, "Three suitable distinct"):
                search(self.project, "prospective query", "--dry-run")
            blocked.assert_not_called()
        self.assertEqual(before, manifest.read_bytes())
        with patch.object(providers, "search") as blocked:
            dry = search(self.project, "factory", "--dry-run")
            blocked.assert_not_called()
        self.assertTrue(dry["replayed"])
        self.assertEqual(before, manifest.read_bytes())

    def _confirm_late_and_unsuitable(self, primary_id, aside):
        aside_id = bound_id(aside)
        closing = preview_clip(self.project, primary_id, 4.4, 5.5, "--option", "closing")
        confirmed = confirm(
            self.project,
            closing["id"],
            distinctness="Closing moment of the same reel",
            observation="The closing frames show another factory action.",
            match="This is a third relevant moment and still the same recording.",
        )
        self.assertEqual(4, confirmed["search_progress"][0]["suitable_count"])
        self.assertEqual(1, confirmed["search_progress"][0]["queries_used"])
        self.assertEqual("pending", confirmed["approval"]["status"])
        self.assertEqual("unknown", confirmed["rights"]["status"])
        self.assertIn("not human approval", confirmed["summary"]["line"])
        preview_clip(self.project, aside_id, 4.4, 5.5)
        confirm(
            self.project,
            aside_id,
            verdict="unsuitable",
            observation="The aside frames do not show the narrated factory action.",
            match="The visible action misses the fragment.",
        )
        report = progress_row(self.project)
        self.assertEqual(4, report["suitable_count"])
        self.assertEqual(1, report["queries_used"])
        self.assertTrue(any(record["verdict"] == "unsuitable" for record in report["viewing_evidence"]))
        self.assertNotIn(
            aside_id, [item["candidate"] for option in report["suitable_options"] for item in option["identities"]]
        )

    def _assert_option_is_not_duplicated(self, primary_id, opening_id):
        before = [item["id"] for item in Ledger(self.project, recover=False).data["items"]]
        again = preview_clip(self.project, opening_id, 0, 1.2, "--option", "opening")
        repeated = preview_clip(self.project, primary_id, 0, 1.2, "--option", "opening")
        after = [item["id"] for item in Ledger(self.project, recover=False).data["items"]]
        self.assertEqual(opening_id, again["id"])
        self.assertEqual(opening_id, repeated["id"])
        self.assertEqual(before, after)
        self.assertEqual(1, sum(ident.endswith(":option:opening") for ident in after))
        self.assertEqual(4, progress_row(self.project)["suitable_count"])

    def _assert_restart_and_storyboard(self, raw, opening_id):
        manifest = self.project / "brolls/manifest.json"
        before = manifest.read_bytes()
        with patch("getbrolls.runtime._acquire_lock", side_effect=AssertionError("Status took a lock")):
            report = progress_row(self.project)
        self.assertEqual(before, manifest.read_bytes())
        self.assertEqual(4, report["suitable_count"])
        self.assertTrue(report["target_reached"])
        self.assertEqual(4, len(report["raw_hits"]))
        self.assertTrue(all(":option:" not in hit["candidate"] for hit in report["raw_hits"]))
        self.assertIn("unopened metadata", [hit["title"] for hit in report["raw_hits"]])
        self.assertNotIn(bound_id(raw), [decision["candidate"] for decision in report["pending_human_decisions"]])
        self.assertIn(opening_id, [decision["candidate"] for decision in report["pending_human_decisions"]])
        call(self.project, "review", "--ready-only")
        page = (self.project / "brolls/review.html").read_text(encoding="utf-8")
        gallery = gallery_markup(page)
        self.assertLess(page.index("search-options"), page.index('<div class="gallery">'))
        for heading in (
            "Search options",
            "Raw hits",
            "Confirmed suitable options",
            "Viewing evidence",
            "Pending human decisions",
            "Visual confirmation is not human approval and does not grant usage rights.",
            "Identities, intervals, and hashes",
        ):
            self.assertIn(heading, page)
        self.assertIn("Original scenario narration", page)
        self.assertIn("different angle", page)
        self.assertIn("unsupported-distinctness", page)
        self.assertIn("pending-decision", page)
        self.assertIn("unopened metadata", page)
        self.assertNotIn("unopened metadata", gallery)
        self.assertIn("Factory reel", gallery)
        self.assertIn("0.0–1.2 s", page)
        self.assertIn("2.6–3.8 s", page)
        self.assertIn(opening_id, page)

    @skip_unless_ffmpeg
    @patch.object(archive, "metadata", return_value=META)
    def test_stale_context_interval_representation_and_rejection(self, _metadata):
        source = self.project / "synthetic.mp4"
        replacement = self.project / "replacement.mp4"
        synth_video(source, size="320x180")
        synth_video(replacement, size="320x180", pattern="testsrc2")
        plan(self.project)
        row = asset_row("fixture", "film-one.mp4", "Only shot")
        current = {"file": source}

        def download(url, target, **kwargs):
            shutil.copyfile(current["file"], target)

        with (
            patch.object(providers, "search", return_value=[row]) as provider,
            patch("getbrolls.http.download", side_effect=download),
        ):
            ident = bound_id(row)
            search(self.project)
            preview_clip(self.project, ident, 0, 2)
            confirm(self.project, ident)
            self.assertEqual(1, progress_row(self.project)["suitable_count"])
            self._assert_context_round_trip(provider)
            self._assert_interval_allows_another_query(ident)
            self._assert_representation_and_rejection(ident, current, replacement)

    def _assert_context_round_trip(self, provider):
        data = brief_data()
        data["beats"][0]["narration"] = "Changed scenario"
        write_brief(self.project, data)
        changed = progress_row(self.project)
        self.assertEqual(0, changed["suitable_count"])
        self.assertEqual("context_changed", changed["viewing_evidence"][0]["stale_reason"])
        self.assertTrue(changed["context_stale"])
        with self.assertRaisesRegex(OperationError, "context changed"):
            search(self.project, "blocked formulation")
        self.assertEqual(1, provider.call_count)
        self.assertEqual(1, progress_row(self.project)["queries_used"])
        write_brief(self.project, brief_data())
        restored = progress_row(self.project)
        self.assertEqual(1, restored["suitable_count"])
        self.assertTrue(restored["viewing_evidence"][0]["current"])
        self.assertFalse(restored["context_stale"])

    def _assert_interval_allows_another_query(self, ident):
        preview_clip(self.project, ident, 3, 5)
        shifted = progress_row(self.project)
        self.assertEqual(0, shifted["suitable_count"])
        self.assertEqual("interval_changed", shifted["viewing_evidence"][0]["stale_reason"])
        assess(self.project, "factory")
        search(self.project, "second formulation")
        self.assertEqual(2, progress_row(self.project)["queries_used"])
        confirm(
            self.project,
            ident,
            observation="The later window shows a different stretch of the factory reel.",
            match="The fragment now matches the 3–5 second interval that was viewed.",
        )
        renewed = progress_row(self.project)
        self.assertEqual(1, renewed["suitable_count"])
        self.assertEqual(2, renewed["queries_used"])
        self.assertEqual("superseded", renewed["viewing_evidence"][0]["stale_reason"])

    def _assert_representation_and_rejection(self, ident, current, replacement):
        stored = Ledger(self.project, recover=False).get(ident)
        Path(stored["local_path"]).unlink()
        current["file"] = replacement
        preview_clip(self.project, ident, 3, 5)
        changed = progress_row(self.project)
        self.assertEqual(0, changed["suitable_count"])
        latest = changed["viewing_evidence"][-1]
        self.assertEqual("representation_changed", latest["stale_reason"])
        confirm(
            self.project,
            ident,
            viewed="material",
            observation="The replacement file shows a different test pattern across the same interval.",
            match="The fragment still matches this interval of the file now on disk.",
        )
        self.assertEqual(1, progress_row(self.project)["suitable_count"])
        self.assertEqual(2, progress_row(self.project)["queries_used"])
        call(self.project, "reject", "--candidate", ident, "--reason", "Synthetic rejection of the viewed interval")
        rejected = progress_row(self.project)
        self.assertEqual(0, rejected["suitable_count"])
        self.assertEqual("rejected", rejected["viewing_evidence"][-1]["stale_reason"])
        self.assertTrue(rejected["viewing_evidence"])
        self.assertEqual("rejected", Ledger(self.project, recover=False).get(ident)["approval"]["status"])
        self.assertEqual("unknown", Ledger(self.project, recover=False).get(ident)["rights"]["status"])
        self._assert_rejection_survives_approval(ident)

    @skip_unless_ffmpeg
    @patch.object(archive, "metadata", side_effect=_restricted_metadata)
    def test_confirmation_does_not_open_fetch_and_defers_requested_originals(self, _metadata):
        video = self.project / "synthetic.mp4"
        poster = self.project / "poster.png"
        synth_video(video, size="320x180")
        synth_image(poster)
        plan(self.project)
        normal = asset_row("fixture", "film-one.mp4", "Public original")
        restricted = asset_row(
            "restricted-item",
            "film-one.mp4",
            "Requested original",
            _restricted_metadata("restricted-item"),
        )
        restricted["preview"]["poster_url"] = "https://archive.org/services/img/fixture"

        def download(url, target, **kwargs):
            shutil.copyfile(poster if "img" in str(url) else video, target)

        with (
            patch.object(providers, "search", return_value=[normal, restricted]),
            patch("getbrolls.http.download", side_effect=download),
        ):
            search(self.project)
            ident = bound_id(normal)
            held = bound_id(restricted)
            preview_clip(self.project, ident, 0, 2)
            confirmed = confirm(self.project, ident)
            self.assertFalse(confirmed["requested_original"])
            self.assertEqual("pending", confirmed["approval"]["status"])
            self._assert_fetch_stays_closed(ident)
            self._assert_format_invalidation_keeps_suitability(ident)
            self._assert_requested_original_is_deferred(held)

    def _assert_fetch_stays_closed(self, ident):
        with patch("getbrolls.http.download") as blocked, self.assertRaisesRegex(OperationError, "Aprovação"):
            call(self.project, "fetch", "--candidate", ident)
        blocked.assert_not_called()
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
        with patch("getbrolls.http.download") as blocked, self.assertRaisesRegex(OperationError, "permit"):
            call(self.project, "fetch", "--candidate", ident)
        blocked.assert_not_called()

    def _assert_format_invalidation_keeps_suitability(self, ident):
        before = Ledger(self.project, recover=False).get(ident)
        data = brief_data()
        data["video"]["delivery"]["format"] = "horizontal"
        call(self.project, "init-rules", "--format", "horizontal", "--force")
        write_brief(self.project, data)
        call(self.project, "review", "--confirm-format-change")
        stored = Ledger(self.project, recover=False).get(ident)
        report = progress_row(self.project)
        self.assertEqual("pending", stored["approval"]["status"])
        self.assertNotIn("signature", stored["approval"])
        self.assertEqual(before["segment"]["start_s"], stored["segment"]["start_s"])
        self.assertEqual(before["segment"]["end_s"], stored["segment"]["end_s"])
        self.assertGreater(stored["segment"]["revision"], before["segment"]["revision"])
        self.assertEqual(1, report["suitable_count"])
        self.assertNotIn("visual_invalidation", stored)
        self.assertEqual("unknown", stored["rights"]["status"])
        with patch("getbrolls.http.download") as blocked, self.assertRaises(OperationError):
            call(self.project, "fetch", "--candidate", ident)
        blocked.assert_not_called()

    def _assert_requested_original_is_deferred(self, held):
        preview_clip(self.project, held, 0, 2, "--reference-only")
        confirmed = confirm(
            self.project,
            held,
            preview="poster",
            observation="The reference poster shows the factory item that cannot be downloaded.",
            match="The poster matches the fragment, and the original still requires separate access.",
        )
        self.assertTrue(confirmed["requested_original"])
        report = confirmed["search_progress"][0]
        self.assertEqual(1, report["suitable_count"])
        self.assertEqual(held, report["deferred_options"][0]["candidate"])
        self.assertFalse(report["deferred_options"][0]["counts_toward_target"])
        self.assertIn("separately requested original", report["note"])
        self.assertNotIn(
            held, [item["candidate"] for option in report["suitable_options"] for item in option["identities"]]
        )
        evidence = next(record for record in report["viewing_evidence"] if record["candidate"] == held)
        self.assertTrue(evidence["current"])
        self.assertTrue(evidence["deferred"])
        call(
            self.project,
            "approve",
            "--candidate",
            held,
            "--by",
            "Synthetic fixture reviewer",
            "--channel",
            "chat",
            "--statement",
            "Synthetic test approval",
        )
        call(
            self.project,
            "permit",
            "--candidate",
            held,
            "--evidence",
            "Synthetic fixture created by this automated test",
        )
        with patch("getbrolls.http.download") as blocked, self.assertRaisesRegex(OperationError, "somente referência"):
            call(self.project, "fetch", "--candidate", held)
        blocked.assert_not_called()
        page = (self.project / "brolls/review.html").read_text(encoding="utf-8")
        self.assertIn("Deferred: a separately requested original is not counted", page)

    def _assert_rejection_survives_approval(self, ident):
        other = preview_clip(self.project, ident, 0, 1.2, "--option", "other")
        ledger = Ledger(self.project, recover=False)
        child, parent = ledger.get(other["id"]), ledger.get(ident)
        self.assertEqual("pending", child["approval"]["status"])
        self.assertNotIn("rejection", child)
        self.assertNotIn("visual_invalidation", child)
        self.assertEqual("rejected", parent["approval"]["status"])
        self.assertEqual(3, parent["segment"]["start_s"])
        self.assertNotEqual(parent["segment"]["start_s"], child["segment"]["start_s"])
        marker = parent["visual_invalidation"]["id"]
        self._approve_source_only(ident)
        held = progress_row(self.project)
        self.assertEqual(0, held["suitable_count"])
        latest = held["viewing_evidence"][-1]
        self.assertEqual("rejected", latest["stale_reason"])
        self.assertNotEqual(marker, latest.get("invalidation"))
        confirm(
            self.project,
            ident,
            observation="The same 3–5 second window was viewed again after the rejection.",
            match="The renewed viewing matches the fragment on the current interval.",
        )
        restored = progress_row(self.project)
        self.assertEqual(1, restored["suitable_count"])
        renewed = restored["viewing_evidence"][-1]
        self.assertTrue(renewed["current"])
        self.assertEqual(marker, renewed["invalidation"])
        self.assertEqual(marker, Ledger(self.project, recover=False).get(ident)["visual_invalidation"]["id"])

    def _approve_source_only(self, ident):
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

    @skip_unless_ffmpeg
    @patch.object(archive, "metadata", return_value=META)
    def test_storyboard_rejection_requires_a_new_confirmation(self, _metadata):
        source = self.project / "synthetic.mp4"
        synth_video(source, size="320x180")
        plan(self.project)
        row = asset_row("fixture", "film-one.mp4", "Board shot")

        def download(url, target, **kwargs):
            shutil.copyfile(source, target)

        with (
            patch.object(providers, "search", return_value=[row]),
            patch("getbrolls.http.download", side_effect=download),
        ):
            ident = bound_id(row)
            search(self.project)
            preview_clip(self.project, ident, 0, 2)
            confirm(self.project, ident)
            self.assertEqual(1, progress_row(self.project)["suitable_count"])
            decision = self.project / "brolls/reviews/rejection.json"
            decision.parent.mkdir(parents=True, exist_ok=True)
            decision.write_text(json.dumps(self._rejected_review(ident)), encoding="utf-8")
            call(self.project, "import-review", "--file", str(decision), "--by", "Synthetic fixture reviewer")
            rejected = progress_row(self.project)
            self.assertEqual(0, rejected["suitable_count"])
            self.assertEqual("rejected", rejected["viewing_evidence"][-1]["stale_reason"])
            marker = Ledger(self.project, recover=False).get(ident)["visual_invalidation"]["id"]
            self._approve_source_only(ident)
            self.assertEqual(0, progress_row(self.project)["suitable_count"])
            self.assertEqual("approved", Ledger(self.project, recover=False).get(ident)["approval"]["status"])
            confirm(
                self.project,
                ident,
                observation="The contact sheet was viewed again after the board rejection.",
                match="The same interval still shows the factory fragment.",
            )
            restored = progress_row(self.project)
            self.assertEqual(1, restored["suitable_count"])
            self.assertEqual(marker, restored["viewing_evidence"][-1]["invalidation"])
            self.assertIn("signature", Ledger(self.project, recover=False).get(ident)["approval"])

    def _rejected_review(self, ident):
        page = (self.project / "brolls/review.html").read_text(encoding="utf-8")
        payload_match = re.search(r"window.GETBROLLS_REVIEW=(.*?);</script>", page)
        if payload_match is None:
            self.fail("Storyboard review payload is missing")
        payload = json.loads(payload_match.group(1))
        found = False
        for item in payload["items"]:
            item["state"] = "rejected" if item["id"] == ident else "pending"
            found = found or item["id"] == ident
        self.assertTrue(found)
        return payload

    @skip_unless_ffmpeg
    @patch.object(archive, "metadata", return_value=META)
    def test_confirmation_records_the_preview_that_was_viewed(self, _metadata):
        source = self.project / "synthetic.mp4"
        synth_video(source, size="320x180")
        plan(self.project)
        row = asset_row("fixture", "film-one.mp4", "Viewed shot")

        def download(url, target, **kwargs):
            shutil.copyfile(source, target)

        with (
            patch.object(providers, "search", return_value=[row]),
            patch("getbrolls.http.download", side_effect=download),
        ):
            ident = bound_id(row)
            search(self.project)
            preview_clip(self.project, ident, 0, 2)
            with self.assertRaisesRegex(OperationError, "--preview must name"):
                call(
                    self.project,
                    "search-confirm",
                    "--shot",
                    "opening",
                    "--candidate",
                    ident,
                    "--viewed",
                    "preview",
                    "--observation",
                    "Frames are visible.",
                    "--match",
                    "They match the fragment.",
                )
            self.assertEqual(
                [], Ledger(self.project, recover=False).data["search_plans"]["opening"].get("confirmations", [])
            )
            confirm(self.project, ident, preview="contact-sheet")
            stored = Ledger(self.project, recover=False)
            candidate_row = stored.get(ident)
            record = stored.data["search_plans"]["opening"]["confirmations"][-1]
            relative = candidate_row["preview"]["contact_sheet_path"]
            self.assertEqual("contact-sheet", record["viewed_preview"])
            self.assertEqual(relative, record["viewed_path"])
            self.assertNotEqual(candidate_row["preview"]["gif_path"], record["viewed_path"])
            self.assertEqual(digest(stored.root / relative), record["viewed_sha256"])
            (stored.root / relative).unlink()
            with self.assertRaisesRegex(OperationError, "not on disk"):
                confirm(self.project, ident, preview="contact-sheet")
            self.assertEqual(
                1, len(Ledger(self.project, recover=False).data["search_plans"]["opening"]["confirmations"])
            )
            candidate_row["preview"]["gif_path"] = "clips/not-a-preview.gif"
            stored.save("test-preview-path")
            with self.assertRaisesRegex(OperationError, "not a generated preview"):
                confirm(self.project, ident, preview="gif")
            material = confirm(
                self.project,
                ident,
                viewed="material",
                observation="The acquired file shows the factory interval.",
                match="Material viewing matches the fragment.",
            )
            material_record = Ledger(self.project, recover=False).data["search_plans"]["opening"]["confirmations"][-1]
            self.assertIsNone(material_record["viewed_path"])
            self.assertIsNone(material_record["viewed_preview"])
            self.assertEqual(candidate_row["local_sha256"], material_record["viewed_sha256"])
            self.assertEqual(1, material["search_progress"][0]["suitable_count"])
            with self.assertRaisesRegex(OperationError, "Omit it when --viewed material"):
                confirm(self.project, ident, viewed="material", preview="gif")
            env_file = self.project / "empty.env"
            with self.assertRaises(SystemExit):
                parse_args(
                    [
                        "--env-file",
                        str(env_file),
                        "search-confirm",
                        "--shot",
                        "opening",
                        "--candidate",
                        ident,
                        "--viewed",
                        "preview",
                        "--preview",
                        "frame",
                        "--observation",
                        "Frames are visible.",
                        "--match",
                        "They match the fragment.",
                        "--project",
                        str(self.project),
                    ]
                )
            with self.assertRaises(SystemExit):
                parse_args(
                    [
                        "--env-file",
                        str(env_file),
                        "search-confirm",
                        "--shot",
                        "opening",
                        "--candidate",
                        ident,
                        "--viewed",
                        "preview",
                        "--preview",
                        "C:/secret.gif",
                        "--observation",
                        "Frames are visible.",
                        "--match",
                        "They match the fragment.",
                        "--project",
                        str(self.project),
                    ]
                )

    @skip_unless_ffmpeg
    def test_identical_still_reposts_count_once(self):
        red = self.project / "red.png"
        blue = self.project / "blue.png"
        synth_image(red)
        synth_image(blue, color="blue")
        plan(self.project)
        metadata = {}
        rows = []
        for index in range(3):
            item_id = f"repost{index}"
            filename = f"repost{index}.png"
            data = {
                "metadata": {"title": f"Repost {index}"},
                "files": [{"name": filename, "source": "original", "format": "PNG", "width": "64", "height": "64"}],
            }
            metadata[item_id] = data
            row = archive.files(item_id, data, "image")[0]
            row["title"] = f"Repost {index}"
            rows.append(row)
        distinct = {
            "metadata": {"title": "Different still"},
            "files": [{"name": "distinct.png", "source": "original", "format": "PNG", "width": "64", "height": "64"}],
        }
        metadata["distinct-item"] = distinct
        different = archive.files("distinct-item", distinct, "image")[0]
        different["title"] = "Different still"
        rows.append(different)

        def download(url, target, **kwargs):
            shutil.copyfile(blue if "distinct.png" in str(url) else red, target)

        with (
            patch.object(providers, "search", return_value=rows),
            patch.object(archive, "metadata", side_effect=lambda ident: metadata[ident]),
            patch("getbrolls.http.download", side_effect=download),
        ):
            found = search(self.project, "red square", "--media", "image")
            self.assertEqual(4, len(found["items"]))
            for index, item in enumerate(found["items"]):
                call(self.project, "preview", "--candidate", item["id"])
                confirm(
                    self.project,
                    item["id"],
                    preview="poster",
                    distinctness="different file name" if index == 1 else None,
                    observation="A square fills the prepared still.",
                    match="The still shows the fragment subject.",
                )
            report = progress_row(self.project)
            self.assertEqual(2, report["suitable_count"])
            self.assertEqual([item["id"] for item in found["items"]], [hit["candidate"] for hit in report["raw_hits"]])
            self.assertFalse(report["target_reached"])
            grouped = option_for(report, found["items"][0]["id"])
            self.assertEqual("repost", grouped["grouped_reason"])
            self.assertEqual(["different file name"], grouped["unsupported_distinctness"])
            identities = grouped["identities"]
            self.assertEqual(3, len(identities))
            self.assertEqual(3, len({item["item_id"] for item in identities}))
            self.assertEqual(3, len({item["interval"]["file"] for item in identities}))
            self.assertEqual(1, len({item["hashes"]["local_sha256"] for item in identities}))
            separate = option_for(report, found["items"][3]["id"])
            self.assertNotEqual(grouped["option_id"], separate["option_id"])
            self.assertNotEqual(
                identities[0]["hashes"]["local_sha256"], separate["identities"][0]["hashes"]["local_sha256"]
            )
            posters = [
                Ledger(self.project, recover=False).get(item["id"])["preview"]["poster_path"]
                for item in found["items"][:3]
            ]
            self.assertEqual(3, len(set(posters)))
            record = next(
                item
                for item in Ledger(self.project, recover=False).data["search_plans"]["opening"]["confirmations"]
                if item["candidate"] == found["items"][0]["id"]
            )
            self.assertEqual("poster", record["viewed_preview"])
            self.assertTrue(record["viewed_path"].endswith("-poster.jpg"))

    def test_original_still_identity_without_a_local_hash(self):
        plan(self.project)
        previews = self.project / "brolls/previews"
        previews.mkdir(parents=True, exist_ok=True)
        for name in ("master.png", "master-small.png", "left.png", "right.png", "one.png", "two.png"):
            (previews / name).write_bytes(b"synthetic-still")

        def still(source_id, ident, title, fields):
            item = fields.get("item")
            row = candidate("archive", source_id, title, "https://archive.org/details/" + (item or "work"))
            row["id"] = "archive:" + ident
            row["asset_type"] = "image"
            row["media"]["kind"] = "image"
            row["archive"] = {"selected_file": fields["selected"], "description": fields.get("description")}
            if item:
                row["archive"]["item_id"] = item
                row["archive"]["asset_file"] = fields["asset"]
            row["preview"]["poster_path"] = "previews/" + fields["poster"]
            return row

        rows = [
            still(
                "plate:master",
                "plate-master",
                "Master",
                {
                    "poster": "master.png",
                    "selected": "master.png",
                    "item": "plate",
                    "asset": "master.png",
                    "description": "full",
                },
            ),
            still(
                "plate:small",
                "plate-small",
                "Small master",
                {
                    "poster": "master-small.png",
                    "selected": "master-small.png",
                    "item": "plate",
                    "asset": "master.png",
                    "description": "derivative",
                },
            ),
            still(
                "work:still-1",
                "generic",
                "Generic original",
                {"poster": "left.png", "selected": "left.png", "description": "alpha"},
            ),
            still(
                "work:still-1",
                "generic-repost",
                "Generic repost",
                {"poster": "right.png", "selected": "right.png", "description": "beta"},
            ),
            still(
                "album:one",
                "album-one",
                "Album one",
                {"poster": "one.png", "selected": "one.png", "item": "album", "asset": "one.png"},
            ),
            still(
                "album:two",
                "album-two",
                "Album two",
                {"poster": "two.png", "selected": "two.png", "item": "album", "asset": "two.png"},
            ),
        ]
        with patch.object(providers, "search", return_value=rows):
            found = search(self.project, "stills", "--media", "image")
        identifiers = [item["id"] for item in found["items"]]
        self.assertEqual(6, len(identifiers))
        for ident in identifiers:
            confirm(
                self.project,
                ident,
                preview="poster",
                distinctness="different representation" if ident.endswith(":generic-repost:shot:opening") else None,
                observation="The still subject is visible.",
                match="The still matches the fragment.",
            )
        report = progress_row(self.project)
        self.assertEqual(4, report["suitable_count"])
        representations = option_for(report, identifiers[0])
        generic = option_for(report, identifiers[2])
        self.assertEqual(representations["option_id"], option_for(report, identifiers[1])["option_id"])
        self.assertEqual("same_still", representations["grouped_reason"])
        self.assertEqual(
            {"master.png", "master-small.png"}, {item["interval"]["file"] for item in representations["identities"]}
        )
        self.assertEqual(generic["option_id"], option_for(report, identifiers[3])["option_id"])
        self.assertEqual("same_still", generic["grouped_reason"])
        self.assertEqual(["different representation"], generic["unsupported_distinctness"])
        self.assertIsNone(next(item["hashes"]["local_sha256"] for item in generic["identities"]))
        self.assertNotEqual(
            option_for(report, identifiers[4])["option_id"], option_for(report, identifiers[5])["option_id"]
        )
        stored = Ledger(self.project, recover=False)
        self.assertTrue(all(stored.get(ident).get("local_sha256") is None for ident in identifiers))

    def test_confirmation_rejects_nonfinite_and_invalid_intervals(self):
        plan(self.project)
        ledger = Ledger(self.project)
        base = {
            "candidate": "archive:fixture:shot:opening",
            "verdict": "suitable",
            "viewed": "preview",
            "viewed_path": "previews/example.gif",
            "viewed_sha256": "abc",
            "viewed_preview": "gif",
            "observation": "Visible machinery.",
            "match": "It matches the factory fragment.",
            "distinctness": None,
            "duplicate_of": None,
            "context_hash": "a" * 64,
            "representation": {
                "provider": "archive",
                "source_id": "fixture:file",
                "source_url": None,
                "item_id": "fixture",
                "asset_file": "film.mp4",
                "selected_file": "film.mp4",
                "local_sha256": None,
                "sha1": None,
                "md5": None,
            },
            "interval": {"start_s": 0, "end_s": 1},
            "requested_original": False,
            "invalidation": None,
            "at": "2026-10-04T00:00:00+00:00",
        }
        ledger.data["search_plans"]["opening"]["confirmations"] = [base]
        ledger.save("search-confirm")
        reloaded = Ledger(self.project, recover=False).data["search_plans"]["opening"]["confirmations"]
        self.assertEqual([{"start_s": 0, "end_s": 1}], [item["interval"] for item in reloaded])
        for interval in (
            {"start_s": float("inf"), "end_s": 1},
            {"start_s": float("nan"), "end_s": 1},
            {"start_s": True, "end_s": 2},
            {"kind": "nope", "start_s": 0, "end_s": 1},
            {"kind": "still", "file": "still.png", "start_s": 0, "end_s": 1},
            {"kind": "still"},
        ):
            broken = copy.deepcopy(base)
            broken["interval"] = interval
            ledger.data["search_plans"]["opening"]["confirmations"] = [broken]
            with self.assertRaisesRegex(ValueError, "suitable-option confirmation"):
                validate_plans(ledger.data)


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
            x_capabilities = providers.capabilities()["x"]
            self.assertTrue(x_capabilities["search"])
            self.assertFalse(x_capabilities["configured"])
            self.assertFalse(x_capabilities["billing_fallback"])
            path.write_text("UNKNOWN_SETTING=value", encoding="utf-8")
            with self.assertRaises(ValueError):
                load_env(path)

    def test_inventory_is_twenty_two_catalogs_plus_local_not_a_live_access_guarantee(self):
        capabilities = providers.capabilities()
        self.assertEqual(23, len(capabilities))
        self.assertTrue(capabilities["archive"]["search"])
        self.assertEqual("supported", capabilities["telegram"]["implementation"])
        self.assertEqual("sample_verified", capabilities["telegram"]["live"])
        self.assertEqual("passed_sample", capabilities["telegram"]["live_observation"]["status"])
        self.assertFalse(capabilities["telegram"]["access_verified"])
        self.assertFalse(capabilities["instagram"]["search"])
