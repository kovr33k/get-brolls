"""Offline native discovery and audited CLI/fragment integration for both catalogs."""

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import _isolation  # noqa: F401
from _paths import ROOT

from getbrolls import catalogs, providers
from getbrolls.cli import parse_args
from getbrolls.commands import execute
from getbrolls.http import ProviderError
from getbrolls.ledger import Ledger
from getbrolls.runtime import audited


def netfilm_card(ident=17):
    return f"""<div class='im-view newsreel-unit catalogue__newsreel-unit'>
      <div class='newsreel-unit__caption'><a class='newsreel-unit__name' href='/film-{ident}/?q=test'>
        <h2><span>Космічний <b>політ</b></span><span>1960-1969</span></h2></a>
        <p class='newsreel-unit__tech'><span>4 сюжета, Хронометраж: 0:10:31</span>
          <span>опубликовано: 15.07.2024 12:38:56,</span></p></div>
      <div class='newsreel-unit__content'><div class='newsreel-unit__chapter'>
        <h3>Сюжет №3</h3><img src='//fs.netfilm.store/fs/fixture.jpg'/>
        <p data-nt='0'>Вид із <b>космічної</b> станції.</p>
      </div></div></div>"""


def netfilm_page(ids=(17,), total=None):
    ids = list(ids)
    return (
        f"<div data-resulttotal='{len(ids) if total is None else total}'>"
        + "".join(netfilm_card(ident) for ident in ids)
        + "</div>"
    )


def suspilne_record(ident=31, **extra):
    return {
        "id": ident,
        "name": "Київ і річка",
        "description": "Синтетичний опис архівного матеріалу.",
        "year": 1991,
        "published_at": "2026-10-08T07:00:00+00:00",
        "duration": 12.5,
        "type": "film",
        "poster_image": "/files/fixture.jpg",
        **extra,
    }


def suspilne_page(*rows, total=None):
    return {"media_items": {"total_count": len(rows) if total is None else total, "items": list(rows)}}


def call(project, *arguments):
    env_file = project / "empty.env"
    env_file.touch()
    args = parse_args(["--env-file", str(env_file), *arguments, "--project", str(project)])
    return audited(args, execute)


def write_brief(project):
    data = {
        "version": 1,
        "video": {"title": "Fixture", "objective": "Archive", "delivery": {"format": "native"}},
        "rights": {"posture": "per_item_evidence", "stock_allowed": False},
        "defaults": {
            "allowed_sources": ["netfilm", "suspilne"],
            "intent": "literal",
            "duration_hint_s": 2,
            "stock": False,
        },
        "beats": [{"id": "opening", "target": "archival city", "narration": "Original narration"}],
    }
    (project / "BRIEF.md").write_text("```json\n" + json.dumps(data) + "\n```", encoding="utf-8")


def plan(project, name):
    return call(
        project,
        "search-plan",
        "--shot",
        "opening",
        "--provider",
        name,
        "--reason",
        "This archive holds historical city footage",
        "--expected-material",
        "Original city film",
    )


class NativeDiscovery(unittest.TestCase):
    def test_netfilm_preserves_canonical_card_and_matching_text_without_selecting_a_part(self):
        with patch("getbrolls.historical_catalogs._html", return_value=netfilm_page()) as request:
            row = providers.search("netfilm", "  космос  ", 1)[0]
        self.assertEqual(
            "https://www.net-film.ru/found-page-1/?q=%D0%BA%D0%BE%D1%81%D0%BC%D0%BE%D1%81", request.call_args.args[0]
        )
        self.assertEqual("netfilm:17", row["id"])
        self.assertEqual("https://www.net-film.ru/film-17/", row["source_url"])
        self.assertEqual("Космічний політ", row["title"])
        self.assertEqual("Вид із космічної станції.", row["source_metadata"]["description"])
        self.assertEqual("1960-1969", row["catalog"]["date_text"])
        self.assertEqual("15.07.2024 12:38:56", row["catalog"]["published_at"])
        self.assertEqual("https://fs.netfilm.store/fs/fixture.jpg", row["preview"]["poster_url"])
        self.assertIsNone(row["media"]["duration_s"])
        self.assertIsNone(row["segment"]["start_s"])
        self.assertNotIn("media_url", row)
        self.assertEqual("unknown", row["rights"]["status"])
        self.assertEqual("pending", row["approval"]["status"])

    def test_netfilm_bounded_paging_deduplicates_cards_and_respects_limit(self):
        pages = [netfilm_page(range(20), 90), netfilm_page(range(19, 30), 90)]
        with patch("getbrolls.historical_catalogs._html", side_effect=pages) as request:
            rows = providers.search("netfilm", "archive", 23)
        self.assertEqual(23, len(rows))
        self.assertEqual(23, len({row["id"] for row in rows}))
        self.assertEqual(2, request.call_count)
        self.assertIn("/found-page-2/", request.call_args.args[0])

    def test_netfilm_does_not_infer_a_date_from_a_title_ending_in_a_year(self):
        page = netfilm_page().replace("Космічний <b>політ</b>", "Події 1991").replace("<span>1960-1969</span>", "")
        with patch("getbrolls.historical_catalogs._html", return_value=page):
            row = providers.search("netfilm", "archive", 1)[0]
        self.assertEqual("Події 1991", row["title"])
        self.assertIsNone(row["catalog"]["date_text"])

    def test_netfilm_empty_search_is_distinct_from_rejected_or_changed_html(self):
        with patch("getbrolls.historical_catalogs._html", return_value=netfilm_page([])):
            self.assertEqual([], providers.search("netfilm", "absent", 3))
        for page in ("<html>verification required</html>", netfilm_page([], 1), netfilm_page().replace("</div>", "")):
            with (
                self.subTest(page=page[:80]),
                patch("getbrolls.historical_catalogs._html", return_value=page),
                self.assertRaises(ProviderError),
            ):
                providers.search("netfilm", "archive", 3)

    def test_netfilm_rejects_external_card_links(self):
        page = netfilm_page().replace("/film-17/?q=test", "https://example.test/film-17/")
        with (
            patch("getbrolls.historical_catalogs._html", return_value=page),
            self.assertRaisesRegex(ProviderError, "invalid film"),
        ):
            providers.search("netfilm", "archive", 1)

    def test_html_transport_is_bounded_and_temporary(self):
        def download_page(url, path, max_bytes):
            self.assertEqual(8 * 1024 * 1024, max_bytes)
            path.write_text(netfilm_page(), encoding="utf-8")

        with patch("getbrolls.historical_catalogs.download", side_effect=download_page) as request:
            self.assertEqual(1, len(providers.search("netfilm", "archive", 1)))
        self.assertFalse(request.call_args.args[1].exists())

    def test_suspilne_preserves_duration_year_and_separate_publication_date(self):
        with patch("getbrolls.historical_catalogs.get_json", return_value=suspilne_page(suspilne_record())) as request:
            row = providers.search("suspilne", "Київ", 3, language="uk")[0]
        self.assertEqual("https://mediateka.suspilne.media/api/content", request.call_args.args[0])
        params = request.call_args.args[1]
        self.assertEqual("Київ", params["filter[media_items][name]"])
        self.assertEqual(3, params["page[media_items][limit]"])
        self.assertEqual(0, params["page[media_items][offset]"])
        self.assertEqual("suspilne:31", row["id"])
        self.assertEqual("https://mediateka.suspilne.media/uk/media/31", row["source_url"])
        self.assertEqual("https://mediateka.suspilne.media/files/fixture.jpg", row["preview"]["poster_url"])
        self.assertEqual(12.5, row["media"]["duration_s"])
        self.assertEqual(1991, row["catalog"]["year"])
        self.assertEqual("2026-10-08T07:00:00+00:00", row["catalog"]["published_at"])
        self.assertNotIn("captured_at", row)
        self.assertNotIn("media_url", row)
        self.assertEqual("manual", row["acquisition"]["method"])

    def test_locale_selects_ui_without_rewriting_query_or_changing_identity(self):
        with patch("getbrolls.historical_catalogs.get_json", return_value=suspilne_page(suspilne_record())) as request:
            english = providers.search("suspilne", "Ленин", 1, language="en-GB")[0]
            ukrainian = providers.search("suspilne", "Ленин", 1, language="ru")[0]
        self.assertEqual(english["id"], ukrainian["id"])
        self.assertEqual("en", english["catalog"]["locale"])
        self.assertEqual("uk", ukrainian["catalog"]["locale"])
        self.assertEqual("Ленин", request.call_args.args[1]["filter[media_items][name]"])
        self.assertEqual({"locale": "uk"}, catalogs.filters("suspilne", ["locale=uk"], "en"))

    def test_suspilne_filters_nonfilms_and_duplicates_and_drops_signed_poster(self):
        rows = suspilne_page(
            suspilne_record(type="photo"),
            suspilne_record(32, poster_image="https://cdn.example.test/poster.jpg?token=private"),
            suspilne_record(32),
        )
        with patch("getbrolls.historical_catalogs.get_json", return_value=rows):
            found = providers.search("suspilne", "archive", 3)
        self.assertEqual(["suspilne:32"], [row["id"] for row in found])
        self.assertIsNone(found[0]["preview"]["poster_url"])

    def test_suspilne_empty_and_invalid_response_are_distinct(self):
        with patch("getbrolls.historical_catalogs.get_json", return_value=suspilne_page()):
            self.assertEqual([], providers.search("suspilne", "absent", 3))
        for response in (
            {},
            {"media_items": []},
            suspilne_page(total=1),
            suspilne_page(suspilne_record(), total=0),
            suspilne_page("bad"),
            suspilne_page(suspilne_record(type=None)),
            suspilne_page(suspilne_record(id="bad")),
        ):
            with (
                self.subTest(response=response),
                patch("getbrolls.historical_catalogs.get_json", return_value=response),
                self.assertRaises(ProviderError),
            ):
                providers.search("suspilne", "archive", 3)

    def test_unknown_or_private_filters_are_refused_before_network(self):
        with patch("getbrolls.historical_catalogs.get_json") as request:
            for filters in (["locale=ru"], ["locale=uk", "locale=en"], ["token=secret"], ["offset=12"]):
                with self.subTest(filters=filters), self.assertRaises(ProviderError):
                    providers.search("suspilne", "archive", catalog_filters=filters)
            request.assert_not_called()

    def test_image_requests_do_not_contact_video_catalogs(self):
        with (
            patch("getbrolls.historical_catalogs.get_json") as api,
            patch("getbrolls.historical_catalogs._html") as page,
        ):
            for name in ("netfilm", "suspilne"):
                self.assertEqual([], providers.search(name, "archive", media="image"))
            api.assert_not_called()
            page.assert_not_called()

    def test_capabilities_and_schemas_allow_search_without_claiming_native_media_acquisition(self):
        schema = json.loads((ROOT / "schemas" / "candidate.schema.json").read_text(encoding="utf-8"))
        for name in ("netfilm", "suspilne"):
            entry = providers.capabilities()[name]
            self.assertTrue(entry["search"])
            self.assertTrue(entry["configured"])
            self.assertFalse(entry["download"])
            self.assertFalse(entry["preview"])
            self.assertIn(name, schema["properties"]["provider"]["enum"])


class HistoricalCLI(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.project = Path(self.folder.name)
        write_brief(self.project)

    def stored_plan(self):
        return Ledger(self.project, recover=False).data["search_plans"]["opening"]

    def test_plain_cli_search_passes_suspilne_language_and_saves_candidate(self):
        with patch("getbrolls.historical_catalogs.get_json", return_value=suspilne_page(suspilne_record())) as request:
            result = call(
                self.project, "search", "--provider", "suspilne", "--query", "Kyiv", "--language", "en", "--limit", "1"
            )
        self.assertEqual("en", request.call_args.args[1]["l"])
        self.assertEqual("suspilne:31", result["items"][0]["id"])
        self.assertEqual("Kyiv", Ledger(self.project, recover=False).get("suspilne:31")["query"])

    def test_planned_netfilm_results_replay_without_another_request_or_allowance(self):
        plan(self.project, "netfilm")
        with patch("getbrolls.historical_catalogs._html", return_value=netfilm_page()) as request:
            first = call(self.project, "search", "--planned", "--shot", "opening", "--query", "космос", "--limit", "1")
            replay = call(self.project, "search", "--planned", "--shot", "opening", "--query", "космос", "--limit", "1")
        self.assertEqual(1, request.call_count)
        self.assertTrue(replay["replayed"])
        self.assertEqual(1, len(self.stored_plan()["attempts"]))
        self.assertEqual("netfilm:17:shot:opening", first["items"][0]["id"])
        self.assertEqual("Original narration", first["items"][0]["narration"])

    def test_planned_suspilne_locale_is_request_and_replay_identity(self):
        plan(self.project, "suspilne")
        with patch("getbrolls.historical_catalogs.get_json", return_value=suspilne_page(suspilne_record())) as request:
            call(self.project, "search", "--planned", "--shot", "opening", "--query", "Kyiv", "--language", "en")
            replay = call(
                self.project,
                "search",
                "--planned",
                "--shot",
                "opening",
                "--query",
                "Kyiv",
                "--catalog-filter",
                "locale=en",
            )
        self.assertEqual("en", request.call_args.args[1]["l"])
        self.assertEqual(1, request.call_count)
        self.assertTrue(replay["replayed"])
        self.assertEqual({"locale": "en"}, self.stored_plan()["attempts"][0]["catalog_filters"])

    def test_access_failure_is_saved_and_image_or_dry_run_does_not_spend_query(self):
        plan(self.project, "netfilm")
        with patch("getbrolls.historical_catalogs._html", side_effect=ProviderError("HTTP 403")) as request:
            call(self.project, "search", "--planned", "--shot", "opening", "--query", "city", "--dry-run")
            image = call(
                self.project, "search", "--planned", "--shot", "opening", "--query", "city", "--media", "image"
            )
            self.assertEqual([], image["items"])
            self.assertIn("Photo search is not implemented", image["note"])
            self.assertEqual([], self.stored_plan()["attempts"])
            call(self.project, "search", "--planned", "--shot", "opening", "--query", "city")
        self.assertEqual(1, request.call_count)
        self.assertEqual("access_or_provider_error", self.stored_plan()["attempts"][0]["status"])


if __name__ == "__main__":
    unittest.main()
