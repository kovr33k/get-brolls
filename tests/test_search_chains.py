"""Offline catalog-chain scenarios through the audited CLI and persisted project state.

Capability patches in the thirty-query test use retained catalog ids. They do not
claim that those catalogs have a live keyword-search route.
"""

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import _isolation  # noqa: F401
from _paths import ROOT

from getbrolls import brief, providers
from getbrolls.cli import parse_args
from getbrolls.commands import execute
from getbrolls.fragment_search import LIMIT_NOTE
from getbrolls.ledger import Ledger, digest
from getbrolls.models import candidate
from getbrolls.runtime import OperationError, audited

CHAIN_SOURCES = ["archive", "nasa", "commons", "youtube", "instagram", "tiktok"]
LIMIT_IDS = (
    "archive",
    "nasa",
    "commons",
    "youtube",
    "instagram",
    "tiktok",
    "pexels",
    "pixabay",
    "loc",
    "dvids",
)


def brief_data(sources=None, beats=None, stock=False):
    return {
        "version": 1,
        "video": {"title": "Fixture", "objective": "Original scenario", "delivery": {"format": "native"}},
        "rights": {"posture": "per_item_evidence", "stock_allowed": stock},
        "defaults": {
            "allowed_sources": list(sources or CHAIN_SOURCES),
            "intent": "literal",
            "duration_hint_s": 2,
            "stock": stock,
        },
        "beats": beats
        or [
            {
                "id": "opening",
                "target": "archival factory",
                "narration": "Narração original da fábrica",
            }
        ],
    }


def write_brief(project, data=None):
    (project / "BRIEF.md").write_text("```json\n" + json.dumps(data or brief_data()) + "\n```", encoding="utf-8")


def write_image_rules(project):
    source = (ROOT / "docs" / "RULES.md").read_text(encoding="utf-8")
    replaced = source.replace(
        '"asset_types": ["video", "image", "news_screenshot", "web_screenshot"]',
        '"asset_types": ["image"]',
    )
    if replaced == source:
        raise AssertionError("RULES template no longer has the expected asset_types line")
    (project / "RULES.md").write_text(replaced, encoding="utf-8")


def call(project, *arguments):
    env_file = project / "empty.env"
    env_file.touch()
    args = parse_args(["--env-file", str(env_file), *arguments, "--project", str(project)])
    return audited(args, execute)


def plan_chain(project, catalogs, shot="opening", search_pass=None, dry_run=False):
    arguments = ["search-plan", "--shot", shot]
    if search_pass is not None:
        arguments.extend(("--pass", str(search_pass)))
    for index, name in enumerate(catalogs, start=1):
        arguments.extend(
            (
                "--provider",
                name,
                "--reason",
                f"{name} belongs because it holds fragment material {index}",
                "--expected-material",
                f"{name} film or still {index}",
            )
        )
    if dry_run:
        arguments.append("--dry-run")
    return call(project, *arguments)


def advance(project, catalog, because, reason, *, dry_run=False):
    arguments = [
        "search-plan",
        "--shot",
        "opening",
        "--advance",
        "--provider",
        catalog,
        "--because",
        because,
        "--reason",
        reason,
    ]
    if dry_run:
        arguments.append("--dry-run")
    return call(project, *arguments)


def planned(project, query, *extra, shot="opening", language=None):
    arguments = ["search", "--planned", "--shot", shot, "--query", query, *extra]
    if language:
        arguments.extend(("--language", language))
    return call(project, *arguments)


def assess(project, query, provider=None, coverage=None, shot="opening"):
    arguments = [
        "search-assess",
        "--shot",
        shot,
        "--query",
        query,
        "--assessment",
        "Results reviewed for this fragment.",
    ]
    if provider:
        arguments.extend(("--provider", provider))
    if coverage:
        arguments.extend(("--coverage", coverage))
    return call(project, *arguments)


def shortfall(project, reason, shot="opening"):
    return call(project, "search-plan", "--shot", shot, "--no-further-catalog", "--reason", reason)


def stored(project, shot="opening"):
    return Ledger(project, recover=False).data["search_plans"][shot]


def progress(project, shot="opening"):
    rows = call(project, "status")["search_progress"]
    return next(row for row in rows if row["fragment"] == shot)


def image_row(provider, source_id, title):
    row = candidate(provider, source_id, title, f"https://example.test/{provider}/{source_id}.jpg")
    row["asset_type"] = "image"
    row["media"]["kind"] = "image"
    row["media"]["width"] = 32
    row["media"]["height"] = 32
    row["acquisition"] = {"status": "available", "method": "https", "evidence": [row["source_url"]]}
    return row


def attach_material(project, item_id, name):
    folder = project / "synthetic"
    folder.mkdir(exist_ok=True)
    path = folder / name
    path.write_bytes(b"synthetic-still\n" + name.encode("ascii"))
    ledger = Ledger(project)
    item = ledger.get(item_id)
    item["local_path"] = str(path)
    item["local_sha256"] = digest(path)
    ledger.save("test-material")
    return item_id


def confirm(project, item_id, shot="opening"):
    return call(
        project,
        "search-confirm",
        "--shot",
        shot,
        "--candidate",
        item_id,
        "--viewed",
        "material",
        "--observation",
        "Synthetic still frames show the fragment subject.",
        "--match",
        "The still matches the fragment subject in this fixture.",
        "--verdict",
        "suitable",
    )


def catalog_states(row):
    return {entry["catalog"]: entry["state"] for entry in row["catalogs"]}


def refuse_without_write(test, project, actions):
    manifest = project / "brolls" / "manifest.json"
    before = manifest.read_bytes()
    with patch.object(providers, "search") as provider:
        for action in actions:
            with test.assertRaisesRegex(OperationError, "Assess prior"):
                action()
        provider.assert_not_called()
    test.assertEqual(before, manifest.read_bytes())
    return before


def read_only_progress(test, project, before):
    with patch("getbrolls.runtime._acquire_lock", side_effect=AssertionError("Status took a lock")):
        row = progress(project)
    test.assertEqual(before, (project / "brolls" / "manifest.json").read_bytes())
    return row


class SearchChains(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.project = Path(self.tmp.name)
        write_brief(self.project)

    def test_one_catalog_plan_is_valid_and_fragments_keep_independent_chains(self):
        data = brief_data(
            beats=[
                {"id": "opening", "target": "archival factory", "narration": "Narração original da fábrica"},
                {"id": "closing", "target": "transport", "narration": "Narração original do encerramento"},
            ]
        )
        write_brief(self.project, data)
        opening = plan_chain(self.project, ["archive"])
        self.assertEqual(["archive"], [entry["catalog"] for entry in opening["search_progress"][0]["catalogs"]])
        self.assertEqual("current", stored(self.project)["chains"][0]["catalogs"][0]["state"])
        plan_chain(self.project, ["commons", "youtube"], shot="closing")
        with patch.object(providers, "search", return_value=[]):
            planned(self.project, "factory")
        rows = {row["fragment"]: row for row in call(self.project, "status")["search_progress"]}
        self.assertEqual(1, rows["opening"]["queries_used"])
        self.assertEqual(0, rows["closing"]["queries_used"])
        self.assertEqual(["archive"], [entry["catalog"] for entry in rows["opening"]["catalogs"]])
        self.assertEqual(["commons", "youtube"], [entry["catalog"] for entry in rows["closing"]["catalogs"]])
        self.assertEqual("Narração original do encerramento", rows["closing"]["context"]["narration"])

    def test_plan_errors_reject_bad_chains_without_saving(self):
        with self.assertRaisesRegex(OperationError, "one to five"):
            call(self.project, "search-plan", "--shot", "opening")
        with self.assertRaisesRegex(OperationError, "one to five"):
            plan_chain(self.project, CHAIN_SOURCES)
        with self.assertRaisesRegex(OperationError, "distinct"):
            plan_chain(self.project, ["archive", "archive"])
        with self.assertRaisesRegex(OperationError, "one --reason"):
            call(
                self.project,
                "search-plan",
                "--shot",
                "opening",
                "--provider",
                "archive",
                "--provider",
                "nasa",
                "--reason",
                "Only one reason",
                "--expected-material",
                "Film",
                "--expected-material",
                "Stills",
            )
        with self.assertRaisesRegex(OperationError, "--reason must explain"):
            call(
                self.project,
                "search-plan",
                "--shot",
                "opening",
                "--provider",
                "archive",
                "--reason",
                "",
                "--expected-material",
                "Film",
            )
        with self.assertRaisesRegex(OperationError, "import route"):
            plan_chain(self.project, ["local"])
        write_brief(self.project, brief_data(sources=["archive"]))
        with self.assertRaisesRegex(OperationError, "supported discovery"):
            plan_chain(self.project, ["youtube"])
        write_image_rules(self.project)
        write_brief(self.project, brief_data(sources=["archive", "youtube"]))
        with self.assertRaisesRegex(OperationError, "incompatible with project media"):
            plan_chain(self.project, ["youtube"])
        saved = plan_chain(self.project, ["archive"])
        self.assertEqual("archive", saved["search_progress"][0]["catalog"])
        self.assertEqual([], stored(self.project)["attempts"])
        with self.assertRaisesRegex(OperationError, "either catalog advance"):
            call(
                self.project,
                "search-plan",
                "--shot",
                "opening",
                "--advance",
                "--no-further-catalog",
                "--provider",
                "archive",
                "--because",
                "unsuitable-source",
                "--reason",
                "Stop",
            )
        with self.assertRaisesRegex(OperationError, "--because belongs"):
            call(self.project, "search-plan", "--shot", "opening", "--because", "unsuitable-source")
        self.assertEqual([], stored(self.project)["attempts"])

    def test_early_skip_and_unimplemented_route_do_not_spend_a_query(self):
        plan_chain(self.project, ["instagram", "archive", "nasa"])
        self.assertEqual("reserve_browser_query", progress(self.project)["next"])
        with patch.object(providers, "search") as provider:
            dry = planned(self.project, "factory", "--dry-run")
            provider.assert_not_called()
        self.assertIsNone(dry["would_dispatch"])
        self.assertEqual("route_unimplemented", dry["limitation"])
        self.assertIn("browser search", dry["summary"]["line"])
        self.assertIn("did not invent", dry["summary"]["line"])
        self.assertEqual([], stored(self.project)["attempts"])
        with patch.object(providers, "search") as provider:
            with self.assertRaisesRegex(OperationError, "No query was dispatched"):
                planned(self.project, "factory")
            provider.assert_not_called()
        self.assertEqual([], stored(self.project)["attempts"])
        with self.assertRaisesRegex(OperationError, "implemented search route"):
            advance(self.project, "instagram", "route-unimplemented", "Browser import is available")
        advance(self.project, "instagram", "unavailable-access", "No authorized browser session for this fragment")
        with self.assertRaisesRegex(OperationError, "implemented search route"):
            advance(self.project, "archive", "route-unimplemented", "Archive search exists")
        with patch.object(providers, "search") as provider:
            advance(self.project, "archive", "unavailable-access", "Archive access is unavailable for this fragment")
            provider.assert_not_called()
        row = progress(self.project)
        self.assertEqual("nasa", row["catalog"])
        self.assertEqual(0, row["fragment_queries_used"])
        self.assertEqual(
            {"instagram": "skipped", "archive": "skipped", "nasa": "current"},
            catalog_states(row),
        )
        manifest = self.project / "brolls" / "manifest.json"
        before = manifest.read_bytes()
        advance(self.project, "archive", "unavailable-access", "Archive access is unavailable for this fragment")
        self.assertEqual(before, manifest.read_bytes())
        with self.assertRaisesRegex(OperationError, "already closed"):
            advance(self.project, "archive", "unsuitable-source", "A different closure")
        with self.assertRaisesRegex(OperationError, "still has query allowance"):
            advance(self.project, "nasa", "allowance-exhausted", "Allowance is not used yet")

    def test_allowance_language_fallback_and_replay_are_per_catalog(self):
        plan_chain(self.project, ["archive", "nasa"])
        with patch.object(providers, "search", return_value=[]) as provider:
            planned(self.project, "factory")
            advance(self.project, "archive", "unsuitable-source", "Archive does not hold the needed event")
            first = planned(self.project, "factory machinery", language="en")
            replay = planned(self.project, "factory machinery", language="fr")
            self.assertTrue(replay["replayed"])
            self.assertEqual(1, replay["search_progress"][0]["queries_used"])
            self.assertEqual("en", replay["attempt"]["language"])
            long_query = "the factory production line machinery in the old industrial district"
            spent = planned(self.project, long_query)
            self.assertEqual(3, spent["search_progress"][0]["queries_used"])
            with self.assertRaisesRegex(OperationError, "three meaningful"):
                planned(self.project, "fourth formulation")
            self.assertEqual(4, provider.call_count)
        nasa = next(entry for entry in progress(self.project)["catalogs"] if entry["catalog"] == "nasa")
        archive = next(entry for entry in progress(self.project)["catalogs"] if entry["catalog"] == "archive")
        self.assertEqual(3, nasa["queries_used"])
        self.assertEqual(1, archive["queries_used"])
        self.assertEqual(4, progress(self.project)["fragment_queries_used"])
        self.assertEqual("en", first["attempt"]["language"])

    def test_same_wording_on_the_next_catalog_is_a_new_query(self):
        plan_chain(self.project, ["archive", "nasa"])
        with patch.object(providers, "search", return_value=[]) as provider:
            planned(self.project, "factory")
            advance(self.project, "archive", "unsuitable-source", "Nothing suitable in Archive")
            second = planned(self.project, "factory")
            self.assertFalse(second["replayed"])
            self.assertEqual(2, provider.call_count)
        self.assertEqual(1, progress(self.project)["queries_used"])
        self.assertEqual(2, progress(self.project)["fragment_queries_used"])
        with self.assertRaisesRegex(OperationError, "--provider"):
            assess(self.project, "factory")
        assess(self.project, "factory", provider="nasa")
        self.assertEqual("nasa", stored(self.project)["attempts"][1]["catalog"])

    def test_confirmed_options_carry_across_catalogs_and_stop_the_search(self):
        plan_chain(self.project, ["archive", "nasa", "commons", "youtube"])

        def fake_search(name, query, limit, media="any"):
            return [image_row(name, f"{name}-a", f"{name} first"), image_row(name, f"{name}-b", f"{name} second")]

        confirmed = []
        with patch.object(providers, "search", side_effect=fake_search) as provider:
            for name in ("archive", "nasa", "commons"):
                found = planned(self.project, f"{name} still")
                self.assertEqual(2, len(found["items"]))
                item_id = found["items"][0]["id"]
                assess(self.project, f"{name} still")
                attach_material(self.project, item_id, f"{name}.bin")
                report = confirm(self.project, item_id)
                confirmed.append(item_id)
                self.assertEqual("pending", report["approval"]["status"])
                self.assertEqual("unknown", report["rights"]["status"])
                if name != "commons":
                    advance(self.project, name, "unsuitable-source", f"No further useful material in {name}")
            self.assertEqual(3, provider.call_count)
            replay = planned(self.project, "commons still")
            provider.assert_called()
            self.assertEqual(3, provider.call_count)
        self.assertTrue(replay["replayed"])
        row = progress(self.project)
        self.assertEqual(3, row["suitable_count"])
        self.assertTrue(row["target_reached"])
        self.assertEqual(6, len(row["raw_hits"]))
        self.assertIsNone(row["shortfall"])
        self.assertEqual("target_reached", row["next"])
        seen = {identity["provider"] for option in row["suitable_options"] for identity in option["identities"]}
        self.assertEqual({"archive", "nasa", "commons"}, seen)
        found = {identity["candidate"] for option in row["suitable_options"] for identity in option["identities"]}
        self.assertEqual(set(confirmed), found)
        with patch.object(providers, "search") as provider:
            for action in (
                lambda: planned(self.project, "another query"),
                lambda: advance(self.project, "commons", "unsuitable-source", "Target is already met"),
                lambda: plan_chain(self.project, ["youtube"], search_pass=2),
            ):
                with self.assertRaisesRegex(OperationError, "Three suitable distinct"):
                    action()
            provider.assert_not_called()
        with self.assertRaisesRegex(OperationError, "Aprovação humana"):
            call(self.project, "fetch", "--candidate", confirmed[0])
        self.assertEqual(3, len(stored(self.project)["confirmations"]))

    def test_second_pass_is_disjoint_and_a_third_pass_is_rejected(self):
        plan_chain(self.project, ["archive", "nasa"])
        advance(self.project, "archive", "unavailable-access", "Archive cannot be reached")
        advance(self.project, "nasa", "unsuitable-source", "NASA does not hold this event")
        with self.assertRaisesRegex(OperationError, "other catalogs"):
            plan_chain(self.project, ["archive", "commons"], search_pass=2)
        plan_chain(self.project, ["commons", "youtube"], search_pass=2)
        self.assertEqual([1, 2], [chain["pass"] for chain in stored(self.project)["chains"]])
        self.assertEqual("commons", stored(self.project)["catalog"])
        with patch.object(providers, "search", return_value=[]):
            planned(self.project, "commons query")
        attempts = list(stored(self.project)["attempts"])
        plan_chain(self.project, ["commons", "youtube"], search_pass=2)
        self.assertEqual(attempts, stored(self.project)["attempts"])
        with self.assertRaisesRegex(OperationError, "reset"):
            plan_chain(self.project, ["instagram", "tiktok"], search_pass=2)
        with self.assertRaises(SystemExit):
            call(
                self.project,
                "search-plan",
                "--shot",
                "opening",
                "--pass",
                "3",
                "--provider",
                "instagram",
                "--reason",
                "A third pass",
                "--expected-material",
                "More film",
            )
        self.assertEqual(attempts, stored(self.project)["attempts"])
        self.assertEqual(2, stored(self.project)["pass"])

    def test_shortfalls_report_zero_one_and_two_options_without_claiming_absence(self):
        plan_chain(self.project, ["archive"])
        advance(self.project, "archive", "unsuitable-source", "Archive does not hold this event")
        recorded = shortfall(self.project, "No other suitable catalog remains")
        row = recorded["search_progress"][0]
        self.assertEqual(0, row["suitable_count"])
        self.assertEqual("no-further-catalog", row["shortfall"]["kind"])
        self.assertIn(LIMIT_NOTE, row["note"])
        self.assertIn(LIMIT_NOTE, row["shortfall"]["note"])
        self.assertNotIn("footage does not exist", row["note"])
        page = Path(call(self.project, "review")["review"]).read_text(encoding="utf-8")
        self.assertIn("Narração original da fábrica", page)
        self.assertIn("Pass 1, catalog archive, next shortfall.", page)
        self.assertIn('class="search-shortfall"', page)
        self.assertIn(LIMIT_NOTE, page)
        self.assertNotIn("footage does not exist", page)
        with patch.object(providers, "search") as provider:
            with self.assertRaisesRegex(OperationError, "recorded shortfall"):
                planned(self.project, "later")
            provider.assert_not_called()
        with self.assertRaisesRegex(OperationError, "recorded shortfall"):
            plan_chain(self.project, ["nasa"], search_pass=2)

    def test_one_and_two_confirmed_options_remain_visible_in_a_shortfall(self):
        self._confirm_then_close(["archive"])
        self.assertEqual(1, progress(self.project)["shortfall"]["suitable_count"])
        self.assertEqual(1, progress(self.project)["suitable_count"])
        other = self.project / "other-project"
        other.mkdir()
        write_brief(other)
        self._confirm_then_close(["archive", "nasa"], project=other)
        row = progress(other)
        self.assertEqual(2, row["suitable_count"])
        self.assertEqual(2, row["shortfall"]["suitable_count"])
        self.assertEqual("no-further-catalog", row["shortfall"]["kind"])
        self.assertIn(LIMIT_NOTE, row["note"])

    def test_exhausted_second_pass_shows_a_computed_shortfall_without_a_write(self):
        plan_chain(self.project, ["archive"])
        with patch.object(providers, "search", return_value=[]):
            for query in ("one", "two", "three"):
                planned(self.project, query)
            advance(self.project, "archive", "allowance-exhausted", "Archive used its three queries")
        plan_chain(self.project, ["nasa"], search_pass=2)
        with patch.object(providers, "search", return_value=[]):
            for query in ("four", "five", "six"):
                planned(self.project, query)
        manifest = self.project / "brolls" / "manifest.json"
        before = manifest.read_bytes()
        with patch("getbrolls.runtime._acquire_lock", side_effect=AssertionError("Status took a lock")):
            row = progress(self.project)
        self.assertEqual(before, manifest.read_bytes())
        self.assertNotIn("shortfall", stored(self.project))
        self.assertEqual("passes-exhausted", row["shortfall"]["kind"])
        self.assertEqual("Both search passes are exhausted.", row["shortfall"]["reason"])
        self.assertEqual(0, row["shortfall"]["suitable_count"])
        self.assertEqual("record_shortfall", row["next"])
        self.assertIn(LIMIT_NOTE, row["note"])

    def test_repeated_plan_and_advance_do_not_refresh_allowance_or_history(self):
        plan_chain(self.project, ["archive", "nasa"])
        with patch.object(providers, "search", return_value=[]):
            planned(self.project, "factory")
        attempts = stored(self.project)["attempts"]
        plan_chain(self.project, ["archive", "nasa"])
        self.assertEqual(attempts, stored(self.project)["attempts"])
        with self.assertRaisesRegex(OperationError, "reset"):
            plan_chain(self.project, ["nasa", "commons"])
        self.assertEqual(attempts, stored(self.project)["attempts"])
        self.assertEqual("archive", stored(self.project)["catalog"])

    def test_legacy_single_catalog_plan_stays_loadable_with_its_confirmations(self):
        plan_chain(self.project, ["archive"])
        with patch.object(providers, "search", return_value=[image_row("archive", "still-1", "Factory still")]):
            found = planned(self.project, "factory")
        item_id = found["items"][0]["id"]
        assess(self.project, "factory")
        attach_material(self.project, item_id, "still-1.bin")
        confirm(self.project, item_id)
        ledger = Ledger(self.project)
        plan = ledger.data["search_plans"]["opening"]
        plan.pop("chains")
        ledger.save("test-legacy-plan")
        self.assertNotIn("chains", stored(self.project))
        self.assertEqual(1, progress(self.project)["suitable_count"])
        self.assertEqual(1, progress(self.project)["queries_used"])
        plan_chain(self.project, ["archive"])
        reloaded = stored(self.project)
        self.assertNotIn("chains", reloaded)
        self.assertEqual(1, len(reloaded["attempts"]))
        self.assertEqual(1, len(reloaded["confirmations"]))
        self.assertEqual(item_id, reloaded["confirmations"][0]["candidate"])
        self.assertEqual("pending", Ledger(self.project, recover=False).get(item_id)["approval"]["status"])

    def test_interrupted_dispatch_blocks_advance_and_survives_restart(self):
        plan_chain(self.project, ["archive", "nasa"])
        with (
            patch.object(providers, "search", side_effect=KeyboardInterrupt),
            self.assertRaisesRegex(OperationError, "interrompida"),
        ):
            planned(self.project, "factory")
        with patch.object(providers, "search") as provider:
            with self.assertRaisesRegex(OperationError, "Assess prior"):
                advance(self.project, "archive", "allowance-exhausted", "Cannot leave an uncertain attempt")
            provider.assert_not_called()
        reloaded = Ledger(self.project, recover=False).data["search_plans"]["opening"]["attempts"][0]
        self.assertEqual("dispatched", reloaded["status"])
        assess(self.project, "factory")
        advance(self.project, "archive", "unavailable-access", "Leave the interrupted catalog")
        row = progress(self.project)
        self.assertEqual("nasa", row["catalog"])
        self.assertEqual(1, row["fragment_queries_used"])
        self.assertEqual("archive", row["attempts"][0]["catalog"])

    def test_unassessed_third_dispatch_blocks_a_new_pass_until_assessed(self):
        plan_chain(self.project, ["archive"])
        with patch.object(providers, "search", return_value=[]):
            planned(self.project, "first wording")
            planned(self.project, "second wording")
        with (
            patch.object(providers, "search", side_effect=KeyboardInterrupt),
            self.assertRaisesRegex(OperationError, "interrompida"),
        ):
            planned(self.project, "third wording")
        reloaded = Ledger(self.project, recover=False).data["search_plans"]["opening"]
        third = reloaded["attempts"][2]
        self.assertEqual("dispatched", third["status"])
        self.assertNotIn("assessment", third)
        self.assertEqual([("archive", 1)] * 3, [(item["catalog"], item["pass"]) for item in reloaded["attempts"]])
        before = refuse_without_write(
            self,
            self.project,
            (
                lambda: advance(
                    self.project, "archive", "allowance-exhausted", "Cannot leave the uncertain third query"
                ),
                lambda: plan_chain(self.project, ["nasa"], search_pass=2, dry_run=True),
                lambda: plan_chain(self.project, ["nasa"], search_pass=2),
            ),
        )
        blocked = stored(self.project)
        self.assertEqual(1, blocked["pass"])
        self.assertEqual("archive", blocked["catalog"])
        self.assertEqual(3, len(blocked["attempts"]))
        self.assertNotIn("shortfall", blocked)
        self.assertEqual([], blocked.get("confirmations") or [])
        row = read_only_progress(self, self.project, before)
        self.assertEqual("assess_results_or_plan_additional_pass", row["next"])
        self.assertIsNone(row["shortfall"])
        self.assertEqual(3, row["queries_used"])
        self.assertEqual(3, row["fragment_queries_used"])
        self.assertEqual(0, row["suitable_count"])
        assess(self.project, "third wording")
        self.assertEqual("dispatched", stored(self.project)["attempts"][2]["status"])
        with patch.object(providers, "search") as provider:
            opened = plan_chain(self.project, ["nasa"], search_pass=2)
            provider.assert_not_called()
        self.assertEqual("nasa", opened["search_progress"][0]["catalog"])
        saved = stored(self.project)
        self.assertEqual(2, saved["pass"])
        self.assertEqual(3, len(saved["attempts"]))
        self.assertEqual([("archive", 1)] * 3, [(item["catalog"], item["pass"]) for item in saved["attempts"]])
        self.assertEqual("exhausted", saved["chains"][0]["catalogs"][0]["state"])
        self.assertTrue(saved["attempts"][2].get("assessment"))
        self.assertEqual(3, progress(self.project)["fragment_queries_used"])
        self.assertEqual(0, progress(self.project)["queries_used"])
        plan_chain(self.project, ["nasa"], search_pass=2)
        self.assertEqual(3, len(stored(self.project)["attempts"]))

    def test_unassessed_third_results_block_a_new_pass_and_keep_confirmations(self):
        plan_chain(self.project, ["archive"])
        with patch.object(providers, "search", return_value=[image_row("archive", "still-1", "Factory still")]):
            found = planned(self.project, "first wording")
        item_id = found["items"][0]["id"]
        assess(self.project, "first wording")
        attach_material(self.project, item_id, "still-1.bin")
        confirm(self.project, item_id)
        with patch.object(providers, "search", return_value=[]):
            planned(self.project, "second wording")
        with patch.object(providers, "search", return_value=[image_row("archive", "still-3", "Unreviewed still")]):
            later = planned(self.project, "third wording")
        later_id = later["items"][0]["id"]
        reloaded = Ledger(self.project, recover=False).data["search_plans"]["opening"]
        self.assertEqual("results", reloaded["attempts"][2]["status"])
        self.assertNotIn("assessment", reloaded["attempts"][2])
        self.assertEqual(item_id, reloaded["confirmations"][0]["candidate"])
        manifest = self.project / "brolls" / "manifest.json"
        before = manifest.read_bytes()
        with patch.object(providers, "search") as provider:
            with self.assertRaisesRegex(OperationError, "Assess prior"):
                plan_chain(self.project, ["nasa"], search_pass=2)
            provider.assert_not_called()
        self.assertEqual(before, manifest.read_bytes())
        blocked = stored(self.project)
        self.assertEqual(1, blocked["pass"])
        self.assertEqual("archive", blocked["catalog"])
        self.assertEqual([("archive", 1)] * 3, [(item["catalog"], item["pass"]) for item in blocked["attempts"]])
        self.assertEqual(item_id, blocked["confirmations"][0]["candidate"])
        held = Ledger(self.project, recover=False)
        self.assertEqual(later_id, held.get(later_id)["id"])
        self.assertEqual("pending", held.get(item_id)["approval"]["status"])
        self.assertEqual("unknown", held.get(item_id)["rights"]["status"])
        self.assertEqual(1, progress(self.project)["suitable_count"])
        assess(self.project, "third wording")
        with patch.object(providers, "search") as provider:
            plan_chain(self.project, ["nasa"], search_pass=2)
            provider.assert_not_called()
        saved = stored(self.project)
        self.assertEqual(2, saved["pass"])
        self.assertEqual("nasa", saved["catalog"])
        self.assertEqual(3, len(saved["attempts"]))
        self.assertEqual(item_id, saved["confirmations"][0]["candidate"])
        row = progress(self.project)
        self.assertEqual(1, row["suitable_count"])
        self.assertEqual(3, row["fragment_queries_used"])
        self.assertEqual("pending", Ledger(self.project, recover=False).get(item_id)["approval"]["status"])

    def test_unassessed_third_results_block_a_shortfall_until_assessed(self):
        plan_chain(self.project, ["archive"])
        with patch.object(providers, "search", return_value=[]):
            planned(self.project, "first wording")
            planned(self.project, "second wording")
        with patch.object(providers, "search", return_value=[image_row("archive", "still-3", "Unreviewed still")]):
            planned(self.project, "third wording")
        third = Ledger(self.project, recover=False).data["search_plans"]["opening"]["attempts"][2]
        self.assertEqual("results", third["status"])
        self.assertNotIn("assessment", third)
        manifest = self.project / "brolls" / "manifest.json"
        before = manifest.read_bytes()
        with patch.object(providers, "search") as provider:
            with self.assertRaisesRegex(OperationError, "Assess prior"):
                shortfall(self.project, "No other suitable catalog remains")
            provider.assert_not_called()
        self.assertEqual(before, manifest.read_bytes())
        blocked = stored(self.project)
        self.assertEqual(1, blocked["pass"])
        self.assertEqual("archive", blocked["catalog"])
        self.assertNotIn("shortfall", blocked)
        self.assertEqual([("archive", 1)] * 3, [(item["catalog"], item["pass"]) for item in blocked["attempts"]])
        with patch("getbrolls.runtime._acquire_lock", side_effect=AssertionError("Status took a lock")):
            row = progress(self.project)
        self.assertEqual(before, manifest.read_bytes())
        self.assertIsNone(row["shortfall"])
        self.assertEqual("assess_results_or_plan_additional_pass", row["next"])
        self.assertEqual(0, row["suitable_count"])
        assess(self.project, "third wording")
        with patch.object(providers, "search") as provider:
            recorded = shortfall(self.project, "No other suitable catalog remains")
            provider.assert_not_called()
        saved = stored(self.project)
        self.assertEqual(3, len(saved["attempts"]))
        self.assertEqual("archive", saved["catalog"])
        self.assertEqual(1, saved["pass"])
        self.assertEqual("no-further-catalog", recorded["search_progress"][0]["shortfall"]["kind"])
        self.assertEqual(0, recorded["search_progress"][0]["suitable_count"])
        shortfall(self.project, "No other suitable catalog remains")
        self.assertEqual("No other suitable catalog remains", stored(self.project)["shortfall"]["reason"])
        self.assertEqual(3, len(stored(self.project)["attempts"]))

    def test_unassessed_final_attempt_blocks_shortfall_until_assessed(self):
        plan_chain(self.project, ["archive"])
        with patch.object(providers, "search", return_value=[]):
            for query in ("one", "two", "three"):
                planned(self.project, query)
            advance(self.project, "archive", "allowance-exhausted", "Archive used its three queries")
        plan_chain(self.project, ["nasa"], search_pass=2)
        with patch.object(providers, "search", return_value=[]):
            planned(self.project, "four")
            planned(self.project, "five")
        with (
            patch.object(providers, "search", side_effect=KeyboardInterrupt),
            self.assertRaisesRegex(OperationError, "interrompida"),
        ):
            planned(self.project, "six")
        reloaded = Ledger(self.project, recover=False).data["search_plans"]["opening"]
        self.assertEqual("dispatched", reloaded["attempts"][-1]["status"])
        self.assertNotIn("assessment", reloaded["attempts"][-1])
        self.assertEqual(2, reloaded["pass"])
        self.assertEqual("nasa", reloaded["catalog"])
        before = refuse_without_write(
            self,
            self.project,
            (
                lambda: shortfall(self.project, "Both passes are done"),
                lambda: call(
                    self.project,
                    "search-plan",
                    "--shot",
                    "opening",
                    "--no-further-catalog",
                    "--reason",
                    "Dry-run must not close an uncertain attempt",
                    "--dry-run",
                ),
            ),
        )
        blocked = stored(self.project)
        self.assertNotIn("shortfall", blocked)
        self.assertEqual(6, len(blocked["attempts"]))
        self.assertEqual(
            ["archive", "archive", "archive", "nasa", "nasa", "nasa"],
            [item["catalog"] for item in blocked["attempts"]],
        )
        self.assertEqual([1, 1, 1, 2, 2, 2], [item["pass"] for item in blocked["attempts"]])
        row = read_only_progress(self, self.project, before)
        self.assertIsNone(row["shortfall"])
        self.assertEqual("assess_results_or_record_shortfall", row["next"])
        self.assertEqual(0, row["suitable_count"])
        assess(self.project, "six", provider="nasa")
        viewed = read_only_progress(self, self.project, (self.project / "brolls" / "manifest.json").read_bytes())
        self.assertNotIn("shortfall", stored(self.project))
        self.assertEqual("passes-exhausted", viewed["shortfall"]["kind"])
        self.assertEqual("record_shortfall", viewed["next"])
        with patch.object(providers, "search") as provider:
            recorded = shortfall(self.project, "Both passes are done")
            provider.assert_not_called()
        saved = stored(self.project)
        self.assertEqual("passes-exhausted", recorded["search_progress"][0]["shortfall"]["kind"])
        self.assertEqual(6, len(saved["attempts"]))
        self.assertEqual("nasa", saved["catalog"])
        self.assertEqual(2, saved["pass"])
        shortfall(self.project, "Both passes are done")
        repeated = stored(self.project)
        self.assertEqual(6, len(repeated["attempts"]))
        self.assertEqual("Both passes are done", repeated["shortfall"]["reason"])

    def test_status_is_read_only_and_ordinary_search_is_not_a_chain(self):
        plan_chain(self.project, ["archive", "nasa"])
        manifest = self.project / "brolls" / "manifest.json"
        before = manifest.read_bytes()
        with patch("getbrolls.runtime._acquire_lock", side_effect=AssertionError("Status took a lock")):
            row = progress(self.project)
        self.assertEqual(before, manifest.read_bytes())
        self.assertEqual(1, row["pass"])
        self.assertEqual(["archive", "nasa"], [entry["catalog"] for entry in row["catalogs"]])
        self.assertEqual("assess_results_or_query", row["next"])
        self.assertEqual(30, row["fragment_query_limit"])
        with patch.object(providers, "search", return_value=[]) as provider:
            planned(self.project, "factory")
            call(self.project, "search", "--provider", "archive", "--query", "ordinary", "--shot", "opening")
            self.assertEqual(2, provider.call_count)
        self.assertEqual(1, len(stored(self.project)["attempts"]))
        self.assertEqual(1, progress(self.project)["queries_used"])
        self.assertEqual("factory", stored(self.project)["attempts"][0]["query"])

    def test_dry_run_plan_search_and_advance_do_not_write(self):
        preview = plan_chain(self.project, ["archive", "nasa"], dry_run=True)
        self.assertTrue(preview["dry_run"])
        self.assertFalse((self.project / "brolls" / "manifest.json").exists())
        self.assertEqual("archive", preview["search_progress"][0]["catalog"])
        plan_chain(self.project, ["archive", "nasa"])
        manifest = self.project / "brolls" / "manifest.json"
        before = manifest.read_bytes()
        with patch.object(providers, "search") as provider:
            dry = planned(self.project, "factory", "--dry-run")
            provider.assert_not_called()
        self.assertEqual("factory", dry["would_dispatch"]["query"])
        self.assertEqual(before, manifest.read_bytes())
        shown = advance(self.project, "archive", "unavailable-access", "Dry-run closure", dry_run=True)
        self.assertEqual("nasa", shown["search_progress"][0]["catalog"])
        self.assertEqual(before, manifest.read_bytes())
        self.assertEqual("archive", stored(self.project)["catalog"])

    def test_outcomes_distinguish_empty_access_and_incomplete_coverage(self):
        plan_chain(self.project, ["archive"])
        with patch.object(providers, "search", return_value=[]):
            planned(self.project, "empty wording")
        assess(self.project, "empty wording", coverage="incomplete")
        with patch.object(providers, "search", side_effect=ValueError("access failed")):
            failed = planned(self.project, "blocked wording")
        self.assertEqual("access_failure", failed["attempt"]["outcome"])
        with self.assertRaisesRegex(OperationError, "Access failures"):
            assess(self.project, "blocked wording", coverage="incomplete")
        with patch.object(providers, "search", return_value=[image_row("archive", "still-9", "Factory still")]):
            planned(self.project, "found wording")
        assess(self.project, "found wording", coverage="incomplete")
        row = progress(self.project)
        self.assertEqual(1, row["outcomes"]["empty_results"])
        self.assertEqual(1, row["outcomes"]["access_failures"])
        self.assertEqual(2, row["outcomes"]["incomplete_coverage"])
        self.assertIn(LIMIT_NOTE, row["note"])

    def test_two_maximum_chains_stop_at_thirty_meaningful_queries(self):
        original = providers.capabilities

        def synthetic_capabilities():
            caps = original()
            for name in LIMIT_IDS:
                caps[name]["search"] = True
                caps[name]["media_types"] = ["image", "video"]
            return caps

        calls = []

        def fake_search(name, query, limit, media="any"):
            calls.append((name, query))
            return []

        extended = (*brief.SOURCES, "loc", "dvids")
        with (
            patch.object(brief, "SOURCES", extended),
            patch.object(providers, "capabilities", synthetic_capabilities),
            patch.object(providers, "search", side_effect=fake_search),
        ):
            write_brief(self.project, brief_data(sources=LIMIT_IDS, stock=True))
            plan_chain(self.project, LIMIT_IDS[:5])
            self._spend(LIMIT_IDS[:5])
            plan_chain(self.project, LIMIT_IDS[5:], search_pass=2)
            self._spend(LIMIT_IDS[5:])
            replay = planned(self.project, f"{LIMIT_IDS[-1]} query 3")
            with self.assertRaisesRegex(OperationError, "three meaningful"):
                planned(self.project, "thirty first meaningful query")
            plan_chain(self.project, LIMIT_IDS[5:], search_pass=2)
            with self.assertRaisesRegex(OperationError, "reset"):
                plan_chain(self.project, ["archive", "nasa"], search_pass=2)
        self.assertTrue(replay["replayed"])
        self.assertEqual(30, len(calls))
        plan = stored(self.project)
        self.assertEqual(30, len(plan["attempts"]))
        self.assertEqual([1, 2], [chain["pass"] for chain in plan["chains"]])
        first = {entry["catalog"] for entry in plan["chains"][0]["catalogs"]}
        second = {entry["catalog"] for entry in plan["chains"][1]["catalogs"]}
        self.assertFalse(first & second)
        counts = {}
        for attempt in plan["attempts"]:
            key = (attempt["pass"], attempt["catalog"])
            counts[key] = counts.get(key, 0) + 1
        self.assertEqual(10, len(counts))
        self.assertEqual({3}, set(counts.values()))
        self.assertEqual(30, progress(self.project)["fragment_queries_used"])
        self.assertEqual(30, progress(self.project)["fragment_query_limit"])

    def _spend(self, names):
        for index, name in enumerate(names):
            for number in (1, 2, 3):
                planned(self.project, f"{name} query {number}")
            if index != len(names) - 1:
                advance(self.project, name, "allowance-exhausted", f"{name} used its three queries")

    def _confirm_then_close(self, catalogs, project=None):
        project = project or self.project
        plan_chain(project, catalogs)

        def fake_search(name, query, limit, media="any"):
            return [image_row(name, f"{name}-kept", f"{name} kept")]

        with patch.object(providers, "search", side_effect=fake_search):
            for name in catalogs:
                found = planned(project, f"{name} still")
                item_id = found["items"][0]["id"]
                assess(project, f"{name} still")
                attach_material(project, item_id, f"{name}-kept.bin")
                confirm(project, item_id)
                reason = f"No further useful material in {name}"
                advance(project, name, "unsuitable-source", reason)
        shortfall(project, "No other suitable catalog remains")
