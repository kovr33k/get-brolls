"""Catalog records, original selection and common review gates. No network or real keys."""

import json
import os
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import _isolation  # noqa: F401
from _media import skip_unless_ffmpeg, synth_image, synth_video
from test_existing_catalog_fragments import call, confirm, planned, progress_row, save_plan, storyboard, write_brief

from getbrolls import catalogs, http, providers
from getbrolls.ledger import Ledger
from getbrolls.models import signature
from getbrolls.runtime import OperationError

FILE = "https://media.example.org/original.jpg"
VIDEO = "https://media.example.org/master.mp4"
ENV = {
    "DVIDS_API_KEY": "fixture-public",
    "DVIDS_CLIENT_SECRET": "fixture-server",
    "NARA_API_KEY": "fixture-nara",
    "EUROPEANA_API_KEY": "fixture-europeana",
    "EUROPEANA_KEY_TYPE": "project",
}


def loc_record():
    return {
        "item": {
            "id": "https://www.loc.gov/item/fixture/",
            "title": "Historical map",
            "date": "1910",
            "rights_advisory": "Consult item rights",
            "image_url": ["https://media.example.org/thumbnail.jpg"],
        },
        "resources": [
            {
                "url": "https://www.loc.gov/resource/fixture/",
                "files": [
                    [
                        {"url": FILE, "mimetype": "image/jpeg", "width": 1600, "height": 1200},
                        {
                            "url": "https://media.example.org/small.jpg",
                            "mimetype": "image/jpeg",
                            "width": 320,
                            "height": 240,
                        },
                    ]
                ],
            }
        ],
    }


def dvids_record(video=False):
    raw = {
        "id": "video:1" if video else "image:1",
        "title": "Bridge",
        "url": "https://www.dvidshub.net/video/1" if video else "https://www.dvidshub.net/image/1",
        "type": "video" if video else "image",
        "date": "2020-01-01",
        "date_published": "2024-02-02",
        "credit": [{"name": "Fixture creator"}],
        "unit_name": "Fixture unit",
        "location": {"country": "US"},
        "thumbnail": "https://media.example.org/thumb.jpg",
    }
    if video:
        raw.update(
            duration=4,
            files=[
                {"src": VIDEO, "type": "video/mp4", "width": 1920, "height": 1080, "size": 200},
                {
                    "src": "https://media.example.org/small.mp4",
                    "type": "video/mp4",
                    "width": 640,
                    "height": 360,
                    "size": 50,
                },
            ],
        )
    else:
        raw.update(image=FILE, dimensions={"width": 1600, "height": 1200})
    return raw


def europeana_record():
    return {
        "about": "/123/fixture",
        "title": ["Historical bridge"],
        "type": "IMAGE",
        "aggregations": [
            {
                "edmIsShownBy": FILE,
                "edmIsShownAt": "https://museum.example.org/record/1",
                "edmDataProvider": {"en": ["Fixture museum"]},
                "edmRights": {"def": ["https://rightsstatements.org/vocab/InC/1.0/"]},
                "webResources": [
                    {"about": FILE, "ebucoreHasMimeType": "image/jpeg", "ebucoreWidth": 1600, "ebucoreHeight": 1200}
                ],
            }
        ],
        "proxies": [{"europeanaProxy": False, "dcCreator": {"en": ["Fixture creator"]}, "dcDate": {"def": ["1910"]}}],
    }


def nara_record():
    return {
        "naId": 123,
        "title": "Historical bridge",
        "creators": [{"heading": "Fixture creator"}],
        "useRestriction": {"status": "Unrestricted"},
        "accessRestriction": {"status": "Unrestricted"},
        "digitalObjects": [
            {"objectId": "11", "objectFilename": "original.jpg", "objectUrl": FILE, "objectFileSize": 100}
        ],
    }


def nara_response(raw):
    return {"statusCode": 200, "body": {"hits": {"hits": [{"_source": {"record": raw}}]}}}


class CatalogRecords(unittest.TestCase):
    def setUp(self):
        self.env = patch.dict(os.environ, ENV, clear=True)
        self.env.start()
        self.addCleanup(self.env.stop)

    def test_loc_selects_real_variant_and_refuses_ambiguous_resources(self):
        raw = loc_record()
        with patch.object(catalogs, "get_json", return_value=raw):
            c = providers.resolve("https://www.loc.gov/item/fixture/")
            self.assertEqual(FILE, c["media_url"])
            self.assertEqual(1600, c["media"]["width"])
            self.assertEqual("unknown", c["rights"]["status"])
            raw["resources"][0]["files"].append([{"url": VIDEO, "mimetype": "video/mp4"}])
            with self.assertRaisesRegex(ValueError, "--catalog-file"):
                providers.resolve(c["source_url"])
            other = providers.resolve(c["source_url"], catalog_file=VIDEO)
            self.assertEqual("video", other["media"]["kind"])
            self.assertNotEqual(c["id"], other["id"])
            with self.assertRaisesRegex(ValueError, "not found"):
                providers.resolve(c["source_url"], catalog_file="https://media.example.org/missing.mp4")

    def test_loc_reference_is_not_original_and_restrictions_stay_visible(self):
        raw = loc_record()
        raw["resources"] = []
        with patch.object(catalogs, "get_json", return_value=raw):
            c = providers.resolve("https://www.loc.gov/item/fixture/")
        self.assertIsNone(c["media_url"])
        self.assertEqual("manual", c["acquisition"]["method"])
        raw = loc_record()
        raw["resources"][0]["download_restricted"] = True
        with patch.object(catalogs, "get_json", return_value=raw):
            c = providers.resolve("https://www.loc.gov/item/fixture/")
        self.assertIsNone(c["media_url"])
        self.assertEqual("unavailable", c["acquisition"]["status"])

    def test_loc_movie_posters_are_not_selected_as_originals(self):
        raw = loc_record()
        raw["resources"][0]["files"][0].append({"url": VIDEO, "mimetype": "video/mp4"})
        raw["resources"][0]["fulltext_file"] = "https://media.example.org/transcript.txt"
        with patch.object(catalogs, "get_json", return_value=raw):
            c = providers.resolve("https://www.loc.gov/item/fixture/")
        self.assertEqual(VIDEO, c["media_url"])
        self.assertIsNone(c["media"]["width"])
        with tempfile.TemporaryDirectory() as directory:
            text = Path(directory) / "text.txt"
            text.write_text("Untimed source speech", encoding="utf-8")
            with patch.object(http, "download", side_effect=lambda url, target, **kw: shutil.copyfile(text, target)):
                transcripts = catalogs.inspect_transcripts(c)
        self.assertEqual("Untimed source speech", transcripts[0]["text"])
        self.assertFalse(transcripts[0]["timed"])

    def test_dvids_uses_selected_asset_dates_and_server_key_without_upload(self):
        raw = dvids_record(True)
        with patch.object(catalogs, "get_json", return_value={"results": raw}) as transport:
            c = providers.resolve(raw["url"])
        self.assertEqual(VIDEO, c["media_url"])
        self.assertEqual("2020-01-01", c["captured_at"])
        self.assertEqual("2024-02-02", c["catalog"]["published_at"])
        self.assertEqual("fixture-server", transport.call_args.args[1]["api_key"])
        self.assertNotIn("fixture-server", json.dumps(c))
        raw["files"] = raw["files"][1:]
        with (
            patch.object(catalogs, "get_json", return_value={"results": raw}),
            self.assertRaisesRegex(ValueError, "not replaced"),
        ):
            providers.refresh(c)

    def test_europeana_retains_institution_and_resource_rights(self):
        raw = europeana_record()
        with patch.object(catalogs, "get_json", return_value={"success": True, "object": raw}):
            c = providers.resolve("https://www.europeana.eu/item/123/fixture")
        self.assertEqual(FILE, c["media_url"])
        self.assertEqual("https://museum.example.org/record/1", c["catalog"]["institution_record"])
        self.assertEqual("Fixture creator", c["creator"]["name"])
        self.assertEqual("unknown", c["rights"]["status"])
        raw["aggregations"][0]["edmIsShownBy"] = "https://museum.example.org/view/1"
        with patch.object(catalogs, "get_json", return_value={"success": True, "object": raw}):
            c = providers.resolve(c["source_url"])
        self.assertIsNone(c["media_url"])
        self.assertEqual("manual", c["acquisition"]["method"])

    def test_europeana_key_type_must_be_confirmed_before_network(self):
        os.environ.pop("EUROPEANA_KEY_TYPE")
        with patch.object(catalogs, "get_json") as transport, self.assertRaisesRegex(ValueError, "EUROPEANA_KEY_TYPE"):
            providers.search("europeana", "bridge")
        transport.assert_not_called()
        self.assertFalse(providers.capabilities()["europeana"]["configured"])

    def test_europeana_views_keep_the_primary_and_distinct_file_choices(self):
        raw = europeana_record()
        raw["aggregations"][0]["hasView"] = [VIDEO]
        with patch.object(catalogs, "get_json", return_value={"success": True, "object": raw}):
            primary = providers.resolve("https://www.europeana.eu/item/123/fixture")
            selected = providers.resolve(primary["source_url"], catalog_file=VIDEO)
            self.assertEqual(FILE, primary["media_url"])
            self.assertNotEqual(primary["id"], selected["id"])
            raw["aggregations"][0]["edmIsShownBy"] = None
            raw["aggregations"][0]["hasView"] = [FILE, VIDEO]
            with self.assertRaisesRegex(ValueError, "--catalog-file"):
                providers.resolve(primary["source_url"])

    def test_nara_objects_have_distinct_identities_and_unknown_geometry(self):
        raw = nara_record()
        raw["digitalObjects"].append({"objectId": "12", "objectUrl": VIDEO})
        with patch.object(catalogs, "get_json", return_value=nara_response(raw)) as transport:
            found = providers.search("nara", "bridge", limit=2)
            self.assertEqual(2, len(found))
            self.assertNotEqual(found[0]["id"], found[1]["id"])
            self.assertIsNone(found[0]["media"]["width"])
            with self.assertRaisesRegex(ValueError, "--catalog-file"):
                providers.resolve(found[0]["source_url"])
            picked = providers.resolve(found[0]["source_url"], catalog_file="12")
            self.assertEqual("video", picked["media"]["kind"])
            self.assertEqual("fixture-nara", transport.call_args.kwargs["headers"]["x-api-key"])
        raw["digitalObjects"] = []
        with patch.object(catalogs, "get_json", return_value=nara_response(raw)):
            self.assertEqual(
                "manual", providers.resolve("https://catalog.archives.gov/id/123")["acquisition"]["method"]
            )

    def test_keyed_failures_and_missing_keys_are_diagnostics(self):
        for name in ("dvids", "europeana", "nara"):
            with (
                self.subTest(name=name),
                patch.object(catalogs, "get_json", return_value={"success": False, "statusCode": 403}),
            ):
                with self.assertRaises(ValueError) as error:
                    providers.search(name, "bridge")
                self.assertNotIn(ENV[catalogs.KEYS[name]], str(error.exception))
            with (
                self.subTest(missing=name),
                patch.dict(os.environ, {catalogs.KEYS[name]: ""}),
                patch.object(catalogs, "get_json") as transport,
            ):
                with self.assertRaisesRegex(ValueError, catalogs.KEYS[name]):
                    providers.search(name, "bridge")
                transport.assert_not_called()

    def test_filters_are_bounded_and_credentials_are_scrubbed(self):
        for name in catalogs.NAMES:
            with self.subTest(name=name), self.assertRaises(ValueError):
                providers.search(name, "bridge", catalog_filters=["api_key=fixture"])
        with patch.object(catalogs, "get_json", return_value={"results": [dvids_record(True)]}) as transport:
            providers.search("dvids", "bridge", media="video", catalog_filters=["category=B-Roll", "hd=1"])
        params = transport.call_args.args[1]
        self.assertEqual("B-Roll", params["category"])
        self.assertEqual(8, params["max_results"])
        self.assertIsNone(http.public_url(FILE + "?wskey=fixture"))
        self.assertEqual(
            {"id": "https://www.loc.gov/item/1/"}, http._scrub({"id": "http://www.loc.gov/item/1/", "wskey": "fixture"})
        )

    def test_refresh_preserves_selection_and_invalidates_changed_context(self):
        raw = europeana_record()
        with patch.object(catalogs, "get_json", return_value={"success": True, "object": raw}):
            c = providers.resolve("https://www.europeana.eu/item/123/fixture")
            c["rights"]["status"] = "permitted"
            c["approval"].update(status="approved", signature=signature(c))
            fresh = providers.refresh(c)
            self.assertEqual("approved", fresh["approval"]["status"])
            raw["aggregations"][0]["edmRights"] = {"def": ["Different rights"]}
            fresh = providers.refresh(c)
        self.assertEqual("pending", fresh["approval"]["status"])
        self.assertEqual("unknown", fresh["rights"]["status"])
        self.assertEqual(FILE, fresh["catalog"]["selected_file"])


@skip_unless_ffmpeg
class CatalogWorkflow(unittest.TestCase):
    def test_each_catalog_reaches_preview_confirmation_storyboard_with_closed_fetch_gates(self):
        for name in catalogs.NAMES:
            with (
                self.subTest(name=name),
                tempfile.TemporaryDirectory() as directory,
                patch.dict(os.environ, ENV, clear=False),
            ):
                project = Path(directory)
                write_brief(project, [name])
                save_plan(project, name)
                image = project / "synthetic.jpg"
                synth_image(image)
                raw = {
                    "loc": loc_record(),
                    "dvids": dvids_record(),
                    "europeana": europeana_record(),
                    "nara": nara_record(),
                }[name]

                def transport(url, params=None, name=name, raw=raw, **kwargs):
                    if name == "loc":
                        return {"results": [raw["item"]]} if "search" in url else raw
                    if name == "dvids":
                        return {"results": [raw] if "search" in url else raw}
                    if name == "europeana":
                        summary = {
                            "id": "/123/fixture",
                            "type": "IMAGE",
                            "title": ["Historical bridge"],
                            "edmIsShownBy": [FILE],
                        }
                        return (
                            {"success": True, "items": [summary]}
                            if "search" in url
                            else {"success": True, "object": raw}
                        )
                    return nara_response(raw)

                def download(url, target, image=image, **kwargs):
                    self.assertEqual(FILE, url)
                    shutil.copyfile(image, target)
                    return target

                with (
                    patch.object(catalogs, "get_json", side_effect=transport),
                    patch.object(http, "download", side_effect=download),
                ):
                    found = planned(project, media="image")
                    ident = found["items"][0]["id"]
                    prepared = call(project, "preview", "--candidate", ident)
                    self.assertEqual("image", prepared["media"]["kind"])
                    self.assertGreater(prepared["media"]["width"], 0)
                    confirm(
                        project,
                        ident,
                        "poster",
                        ("Viewed the synthetic bridge image", "The fixture depicts the requested bridge"),
                    )
                    self.assertEqual(1, progress_row(project)["suitable_count"])
                    self.assertIn("Scenario narration", storyboard(project))
                    with self.assertRaisesRegex(OperationError, "Aprovação humana ausente"):
                        call(project, "fetch", "--candidate", ident)
                    stored = Ledger(project, recover=False).get(ident)
                    self.assertEqual("unknown", stored["rights"]["status"])
                    self.assertTrue(planned(project, media="image")["replayed"])
                    call(
                        project,
                        "approve",
                        "--candidate",
                        ident,
                        "--by",
                        "Synthetic fixture reviewer",
                        "--statement",
                        "Approve this generated test fixture",
                    )
                    with self.assertRaisesRegex(OperationError, "permit"):
                        call(project, "fetch", "--candidate", ident)
                    call(
                        project, "permit", "--candidate", ident, "--evidence", "Synthetic media generated by this test"
                    )
                    self.assertTrue(call(project, "fetch", "--candidate", ident)["output"]["verified"])

    def test_changed_filters_share_the_allowance_and_reordered_filters_replay(self):
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, ENV):
            project = Path(directory)
            write_brief(project, ["dvids"])
            save_plan(project, "dvids")

            def search(*values):
                return call(
                    project,
                    "search",
                    "--planned",
                    "--shot",
                    "opening",
                    "--query",
                    "bridge",
                    "--media",
                    "video",
                    *[part for v in values for part in ("--catalog-filter", v)],
                )

            with patch.object(catalogs, "get_json", return_value={"results": []}) as transport:
                first = search("hd=1", "category=B-Roll")
                self.assertFalse(first["replayed"])
                self.assertTrue(search("category=B-Roll", "hd=1")["replayed"])
                call(
                    project,
                    "search-assess",
                    "--shot",
                    "opening",
                    "--query",
                    "bridge",
                    "--assessment",
                    "Synthetic empty result",
                    "--coverage",
                    "assessed",
                )
                self.assertFalse(search("hd=0", "category=B-Roll")["replayed"])
                self.assertEqual(2, transport.call_count)
                self.assertEqual(2, progress_row(project)["queries_used"])
                call(
                    project,
                    "search-assess",
                    "--shot",
                    "opening",
                    "--query",
                    "bridge",
                    "--assessment",
                    "Second fixture filter tested",
                    "--catalog-filter",
                    "hd=0",
                    "--catalog-filter",
                    "category=B-Roll",
                )
                with self.assertRaises(OperationError):
                    search("api_key=override")
                self.assertEqual(2, progress_row(project)["queries_used"])

    def test_dvids_video_inspect_and_preview_use_the_pinned_file(self):
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, ENV):
            project = Path(directory)
            raw = dvids_record(True)
            movie = project / "synthetic.mp4"
            synth_video(movie, duration=4)
            with (
                patch.object(catalogs, "get_json", return_value={"results": raw}),
                patch.object(http, "download", side_effect=lambda url, target, **kw: shutil.copyfile(movie, target)),
            ):
                resolved = call(project, "resolve", "--url", raw["url"])
                ident = resolved["id"]
                report = call(project, "inspect", "--candidate", ident, "--query", "bridge")
                self.assertGreater(report["duration_s"], 0)
                prepared = call(project, "preview", "--candidate", ident, "--start", "0", "--end", "2")
                self.assertEqual(VIDEO, prepared["catalog"]["selected_file"])
                self.assertEqual(0, prepared["segment"]["start_s"])

    def test_inspect_pins_a_search_assets_file_before_cached_preview(self):
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, ENV):
            project = Path(directory)
            write_brief(project, ["dvids"])
            save_plan(project, "dvids")
            raw = dvids_record(True)
            summary = {k: v for k, v in raw.items() if k != "files"}
            movie = project / "synthetic.mp4"
            synth_video(movie, duration=4)

            def transport(url, **kwargs):
                return {"results": [summary] if "search" in url else raw}

            with (
                patch.object(catalogs, "get_json", side_effect=lambda url, params=None, **kw: transport(url)),
                patch.object(http, "download", side_effect=lambda url, target, **kw: shutil.copyfile(movie, target)),
            ):
                ident = planned(project)["items"][0]["id"]
                call(project, "inspect", "--candidate", ident, "--query", "bridge")
                self.assertEqual(VIDEO, Ledger(project, recover=False).get(ident)["catalog"]["selected_file"])
                raw["files"] = raw["files"][1:]
                with self.assertRaisesRegex(OperationError, "not replaced"):
                    call(project, "preview", "--candidate", ident, "--start", "0", "--end", "2")

    def test_still_inspection_pins_the_original_without_inventing_duration(self):
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, ENV):
            project = Path(directory)
            write_brief(project, ["dvids"])
            save_plan(project, "dvids")
            raw = dvids_record()
            summary = {k: v for k, v in raw.items() if k != "image"}
            image = project / "synthetic.jpg"
            synth_image(image)
            with (
                patch.object(
                    catalogs,
                    "get_json",
                    side_effect=lambda url, params=None, **kw: {"results": [summary] if "search" in url else raw},
                ),
                patch.object(http, "download", side_effect=lambda url, target, **kw: shutil.copyfile(image, target)),
            ):
                ident = planned(project, media="image")["items"][0]["id"]
                call(project, "inspect", "--candidate", ident, "--query", "bridge")
                c = Ledger(project, recover=False).get(ident)
                self.assertEqual(FILE, c["catalog"]["selected_file"])
                self.assertIsNone(c["media"]["duration_s"])
                raw["image"] = "https://media.example.org/replacement.jpg"
                with self.assertRaisesRegex(OperationError, "not replaced"):
                    call(project, "preview", "--candidate", ident)


if __name__ == "__main__":
    unittest.main()
