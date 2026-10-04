"""Public catalog contracts and audited, synthetic source-clock/access workflows."""

import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import _isolation  # noqa: F401
from _media import skip_unless_ffmpeg
from test_existing_catalog_fragments import call, confirm, progress_row, save_plan, storyboard, write_brief

from getbrolls import broadcasts, providers, social
from getbrolls.http import ProviderError
from getbrolls.ledger import Ledger
from getbrolls.media import cut, probe
from getbrolls.runtime import OperationError

VIDEO = "https://media.example.org/parent.mp4"
EC_PAGE = "https://audiovisual.ec.europa.eu/en/video/I-100"
UN_PAGE = "https://webtv.un.org/en/asset/k1a/k1abcdef12"
TRANSCRIPT = "https://transcripts.un.org/en/sc/10001"


def ec_record(restricted=False, hls=False):
    return {
        "ref": "I-100-INT-1+002",
        "document_ref": "I-100",
        "type": "VIDEOSHOT",
        "titlesshot_json": {"EN": "<p>Synthetic shot</p>", "FR": "Plan"},
        "summaryshot_json": {"EN": "Middle red source-clock interval"},
        "timecodeIn": 2,
        "shotduration": "2",
        "duration": "6",
        "download_enabled": "N" if restricted else "Y",
        "cc_by_json": [{"cc_by": "0"}],
        "copyrights_json": [{"holder": "Fixture copyright", "exception": "Third-party insert"}],
        "media_json": {"16:9": {"INT": {"HLS" if hls else "h264_1080": VIDEO}}},
    }


def un_record(locale="en"):
    return {
        "url": TRANSCRIPT,
        "video": {
            "id": "k1a/k1abcdef12",
            "kaltura_id": "1_abcdef12",
            "url": UN_PAGE,
            "title": "Fixture UN meeting",
            "date": "2026-10-01",
            "duration": "00:00:06",
        },
        "transcript": {
            "language": locale,
            "data": [
                {
                    "speaker": {"affiliation": "ZZZ"},
                    "paragraphs": [{"sentences": [{"text": "nuclear treaty agreement", "start": 2, "end": 4}]}],
                }
            ],
        },
    }


def gdelt_record():
    return {
        "preview_url": "https://archive.org/details/FIXTURE_20201001#start/2/end/4",
        "ia_show_id": "FIXTURE_20201001",
        "preview_thumb": "https://archive.org/download/FIXTURE_20201001/frame.jpg",
        "station": "CNN",
        "show": "Fixture news",
        "date": "20201001T120000Z",
        "snippet": "nuclear treaty agreement",
    }


def ec_transport(raw):
    return {"responseHeader": {"status": 0}, "response": {"numFound": 1, "docs": [raw]}}


class BroadcastContracts(unittest.TestCase):
    def test_capabilities_are_honest_and_filters_do_not_accept_credentials(self):
        caps = providers.capabilities()
        for name in broadcasts.NAMES:
            self.assertTrue(caps[name]["search"])
            self.assertEqual("supported", caps[name]["implementation"])
            with self.assertRaises(ValueError):
                providers.search(name, "query", catalog_filters=["token=fixture"])
        self.assertFalse(caps["gdelt_tv"]["download"])
        self.assertFalse(caps["gdelt_tv"]["visual_search"])
        self.assertNotIn("image", caps["un_webtv"]["media_types"])
        with patch.object(broadcasts, "get_json") as transport, self.assertRaisesRegex(ValueError, "locale"):
            providers.search("un_webtv", "query", language="pt")
        transport.assert_not_called()

    def test_ec_uses_keyword_parameter_shots_before_parents_and_preserves_unknowns(self):
        raw = ec_record()
        raw["shot_thumbnail"] = ""
        with patch.object(broadcasts, "get_json", return_value=ec_transport(raw)) as transport:
            result = providers.search("ec_audiovisual", "synthetic", limit=1, media="video")
        self.assertEqual("synthetic", transport.call_args.args[1]["kwgg"])
        self.assertNotIn("q", transport.call_args.args[1])
        self.assertEqual("VIDEOSHOT", transport.call_args.args[1]["type"])
        c = result[0]
        self.assertEqual(EC_PAGE, c["source_url"])
        self.assertEqual(raw["ref"], c["source_id"])
        self.assertEqual(2, c["catalog"]["provider_source_start"])
        self.assertIsNone(c["preview"]["poster_url"])
        self.assertIsNone(c["media"]["width"])
        self.assertEqual("unknown", c["rights"]["status"])
        raw.pop("timecodeIn")
        raw["media_json"] = {}
        with patch.object(broadcasts, "get_json", return_value=ec_transport(raw)):
            missing = providers.search("ec_audiovisual", "synthetic", limit=1)[0]
        self.assertIsNone(broadcasts.default_window(missing))
        self.assertEqual("unavailable", missing["acquisition"]["status"])

    def test_ec_fallback_and_no_parent_substitution_at_refresh(self):
        raw = ec_record()
        with patch.object(
            broadcasts, "get_json", side_effect=[ProviderError("schema"), ec_transport(raw)]
        ) as transport:
            c = providers.search("ec_audiovisual", "synthetic", 1)[0]
        self.assertEqual(broadcasts.EC_ENDPOINTS[1], transport.call_args.args[0])
        self.assertEqual(raw["ref"], c["catalog"]["record_id"])
        parent = {**raw, "ref": "I-100", "type": "VIDEO"}
        with (
            patch.object(broadcasts, "get_json", return_value=ec_transport(parent)),
            self.assertRaisesRegex(ValueError, "parent was not substituted"),
        ):
            providers.refresh(c)
        with (
            patch.object(broadcasts, "get_json", return_value={}),
            self.assertRaisesRegex(ValueError, "endpoints failed"),
        ):
            providers.search("ec_audiovisual", "synthetic")

    def test_ec_photo_uses_original_and_public_url_normalization(self):
        raw = {
            "ref": "P-100/00-01",
            "document_ref": "P-100",
            "type": "PHOTO",
            "media_json": {"ORIGINAL": {"PATH": "original.jpg"}, "MED": {"PATH": "//media.example.org/thumb.jpg"}},
        }
        with patch.object(broadcasts, "get_json", return_value=ec_transport(raw)):
            c = providers.search("ec_audiovisual", "synthetic", 1, media="image")[0]
        self.assertEqual(broadcasts.EC_PHOTOS + "original.jpg", c["media_url"])
        self.assertEqual("https://media.example.org/thumb.jpg", c["preview"]["poster_url"])
        self.assertEqual("image", c["media"]["kind"])

    def test_un_locale_full_text_deeplink_and_old_direct_asset(self):
        meeting = {
            "pageUrl": "/ru/sc/10001",
            "matches": {
                "statements": [
                    {
                        "text": "Fixture speech",
                        "start": 2,
                        "pageUrl": "/ru/sc/10001?t=0:02",
                        "speaker": {"affiliation": "ZZZ"},
                    }
                ]
            },
        }
        with patch.object(broadcasts, "get_json", side_effect=[{"meetings": [meeting]}, un_record("ru")]) as transport:
            c = providers.search("un_webtv", "договор", 1, language="ru")[0]
        self.assertIn("/ru/meetings.json", transport.call_args_list[0].args[0])
        self.assertEqual(1, transport.call_args_list[0].args[1]["ft"])
        self.assertEqual(2, c["catalog"]["matches"][0]["start"])
        self.assertEqual(UN_PAGE, c["source_url"])
        self.assertIn("365", c["catalog"]["coverage"])
        with patch.object(broadcasts, "get_json", side_effect=ProviderError("not found")):
            older = providers.resolve(UN_PAGE)
        self.assertEqual(UN_PAGE, older["source_url"])
        self.assertIn("No accessible transcript", older["catalog"]["transcript_limitation"])
        self.assertEqual("yt-dlp", older["acquisition"]["method"])

    def test_gdelt_preserves_locator_time_and_cannot_download(self):
        with patch.object(broadcasts, "get_json", return_value={"clips": [gdelt_record()]}) as transport:
            c = providers.search("gdelt_tv", "treaty", 1, catalog_filters=["station=CNN"])[0]
        self.assertEqual("treaty station:CNN", transport.call_args_list[0].args[1]["query"])
        self.assertEqual({"start_s": 2, "end_s": 4}, c["locator"]["source_interval"])
        self.assertEqual("unavailable", c["acquisition"]["status"])
        self.assertEqual("nuclear treaty agreement", c["catalog"]["matching_text"])
        with patch.object(broadcasts, "get_json") as transport, self.assertRaisesRegex(ValueError, "explicit station"):
            providers.search("gdelt_tv", "treaty")
        transport.assert_not_called()

    def test_ec_hls_transport_is_validated_against_selected_portal_file(self):
        raw = {**ec_record(hls=True), "ref": "I-100", "type": "VIDEO"}
        with patch.object(broadcasts, "get_json", return_value=ec_transport(raw)):
            social._validate_transport(VIDEO, EC_PAGE)
            with self.assertRaisesRegex(ValueError, "Selected EC representation"):
                social._validate_transport("https://media.example.org/other.m3u8", EC_PAGE)

    def test_gdelt_records_actual_station_coverage(self):
        details = {
            "station_details": [{"StationID": "CNN", "StartDate": "20090702T000000Z", "EndDate": "20241010T235959Z"}]
        }
        with patch.object(broadcasts, "get_json", side_effect=[{"clips": [gdelt_record()]}, details]):
            c = providers.search("gdelt_tv", "treaty station:CNN", 1)[0]
        self.assertEqual("20241010T235959Z", c["catalog"]["station_coverage"]["end"])
        self.assertEqual("https://archive.org/download/FIXTURE_20201001/frame.jpg", c["preview"]["poster_url"])

    def test_ec_refresh_changes_parent_and_conditions_without_forgetting_measured_dimensions(self):
        raw = ec_record()
        item = broadcasts._ec_row(raw)
        item["media"].update(width=160, height=90, fps=10)
        changed = {**raw, "document_ref": "I-200", "scope_json": ["Restricted insert"]}
        with patch.object(broadcasts, "get_json", return_value=ec_transport(changed)):
            refreshed = providers.refresh(item)
        self.assertEqual("https://audiovisual.ec.europa.eu/en/video/I-200", refreshed["source_url"])
        self.assertEqual(160, refreshed["media"]["width"])
        self.assertEqual("pending", refreshed["approval"]["status"])
        self.assertEqual("unknown", refreshed["rights"]["status"])


@skip_unless_ffmpeg
class BroadcastWorkflow(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.project = Path(self.temp.name)
        self.video = self.project / "synthetic.mp4"
        subprocess.run(
            [
                "ffmpeg",
                "-v",
                "error",
                "-f",
                "lavfi",
                "-i",
                "color=c=blue:s=160x90:d=2:r=10",
                "-f",
                "lavfi",
                "-i",
                "color=c=red:s=160x90:d=2:r=10",
                "-f",
                "lavfi",
                "-i",
                "color=c=green:s=160x90:d=2:r=10",
                "-filter_complex",
                "[0:v][1:v][2:v]concat=n=3:v=1:a=0[v]",
                "-map",
                "[v]",
                "-c:v",
                "libx264",
                "-pix_fmt",
                "yuv420p",
                str(self.video),
            ],
            check=True,
        )
        self.env = patch.dict(os.environ, {"GB_PREVIEW_MAX_SECONDS": "6", "GB_CONTACT_SHEET_FRAMES": "2"})
        self.env.start()
        self.addCleanup(self.env.stop)

    def assert_red(self, path):
        rgb = subprocess.run(
            [
                "ffmpeg",
                "-v",
                "error",
                "-i",
                str(path),
                "-frames:v",
                "1",
                "-f",
                "rawvideo",
                "-pix_fmt",
                "rgb24",
                "pipe:1",
            ],
            capture_output=True,
            check=True,
        ).stdout[:3]
        self.assertGreater(rgb[0], 200)
        self.assertLess(rgb[1], 50)
        self.assertLess(rgb[2], 50)

    def search_ec(self, raw):
        write_brief(self.project, ["ec_audiovisual"])
        save_plan(self.project, "ec_audiovisual")
        with patch.object(broadcasts, "get_json", return_value=ec_transport(raw)):
            found = call(
                self.project, "search", "--planned", "--shot", "opening", "--query", "synthetic", "--limit", "1"
            )
            self.assertTrue(
                call(self.project, "search", "--planned", "--shot", "opening", "--query", "synthetic", "--limit", "1")[
                    "replayed"
                ]
            )
        self.assertEqual(1, progress_row(self.project)["queries_used"])
        return found["items"][0]["id"]

    def test_ec_parent_offset_default_override_and_final_frames(self):
        raw = ec_record()
        ident = self.search_ec(raw)

        def download(url, target, **kwargs):
            self.assertEqual(VIDEO, url)
            shutil.copyfile(self.video, target)
            return target

        with (
            patch.object(broadcasts, "get_json", return_value=ec_transport(raw)),
            patch("getbrolls.http.download", side_effect=download),
        ):
            preview = call(self.project, "preview", "--candidate", ident, "--end", "4")
            self.assertEqual(2, preview["segment"]["start_s"])
            self.assertEqual(0, preview["local_start_s"])
            self.assert_red(self.project / "brolls" / preview["preview"]["poster_path"])
            confirm(self.project, ident, "gif", ("Synthetic red middle", "Matches fixture red target"))
            self.assertIn("Synthetic shot", storyboard(self.project))
            call(self.project, "permit", "--candidate", ident, "--evidence", "Synthetic fixture rights")
            call(self.project, "approve", "--candidate", ident, "--by", "Fixture", "--channel", "storyboard")
            final = call(self.project, "fetch", "--candidate", ident)
            self.assert_red(self.project / "brolls" / final["output"]["path"])
            self.assertAlmostEqual(2, probe(self.project / "brolls" / final["output"]["path"])["duration_s"], places=1)
            override = call(self.project, "preview", "--candidate", ident, "--source-start", "4", "--end", "5")
            self.assertEqual(4, override["segment"]["start_s"])
            self.assertEqual("pending", override["approval"]["status"])

    def test_ec_cached_section_has_nonzero_offset_without_double_addition(self):
        raw = ec_record(hls=True)
        ident = self.search_ec(raw)

        def section(url, target, start, end, *, source_url=None):
            self.assertEqual(VIDEO, url)
            self.assertEqual(EC_PAGE, source_url)
            self.assertEqual((2, 4), (start, end))
            cut(self.video, target, start, end)

        with (
            patch.object(broadcasts, "get_json", return_value=ec_transport(raw)),
            patch.object(social, "download_segment", side_effect=section) as transport,
        ):
            preview = call(self.project, "preview", "--candidate", ident)
            self.assertEqual(2, preview["local_start_s"])
            self.assert_red(self.project / "brolls" / preview["preview"]["poster_path"])
            again = call(self.project, "preview", "--candidate", ident, "--start", "2", "--end", "3")
            self.assertEqual(2, again["local_start_s"])
            self.assertEqual(1, transport.call_count)
            call(self.project, "permit", "--candidate", ident, "--evidence", "Synthetic fixture rights")
            call(self.project, "approve", "--candidate", ident, "--by", "Fixture", "--channel", "storyboard")
            final = call(self.project, "fetch", "--candidate", ident)
            self.assert_red(self.project / "brolls" / final["output"]["path"])
            self.assertAlmostEqual(1, probe(self.project / "brolls" / final["output"]["path"])["duration_s"], places=1)

    def test_un_locale_and_filter_changes_share_allowance_and_replay_after_reload(self):
        write_brief(self.project, ["un_webtv"])
        save_plan(self.project, "un_webtv")

        def transport(url, params=None, **kw):
            if "meetings.json" in url:
                return {"meetings": [{"pageUrl": "/en/sc/10001", "matches": {}}]}
            return un_record()

        with patch.object(broadcasts, "get_json", side_effect=transport) as network:
            for lang in ("en", "fr", "ru"):
                call(
                    self.project,
                    "search",
                    "--planned",
                    "--shot",
                    "opening",
                    "--query",
                    "treaty",
                    "--language",
                    lang,
                    "--limit",
                    "1",
                )
                call(
                    self.project,
                    "search-assess",
                    "--shot",
                    "opening",
                    "--query",
                    "treaty",
                    "--catalog-filter",
                    "locale=" + lang,
                    "--assessment",
                    "Fixture language results do not establish a viewed option",
                    "--coverage",
                    "incomplete",
                )
            used = network.call_count
            replay = call(
                self.project,
                "search",
                "--planned",
                "--shot",
                "opening",
                "--query",
                "treaty",
                "--language",
                "fr",
                "--limit",
                "1",
            )
            self.assertTrue(replay["replayed"])
            self.assertEqual(used, network.call_count)
            with self.assertRaisesRegex(OperationError, "three|3|exhausted"):
                call(
                    self.project,
                    "search",
                    "--planned",
                    "--shot",
                    "opening",
                    "--query",
                    "new treaty",
                    "--language",
                    "es",
                    "--limit",
                    "1",
                )
            self.assertEqual(used, network.call_count)
        self.assertEqual(3, progress_row(self.project)["queries_used"])
        attempts = Ledger(self.project).data["search_plans"]["opening"]["attempts"]
        self.assertEqual(["en", "fr", "ru"], [attempt["source_matches"][0]["language"] for attempt in attempts])

    def test_access_is_separate_and_changed_brief_blocks_even_cached_working_media(self):
        raw = ec_record(restricted=True)
        ident = self.search_ec(raw)
        with (
            patch.object(broadcasts, "get_json", return_value=ec_transport(raw)),
            patch(
                "getbrolls.http.download", side_effect=lambda url, target, **kw: shutil.copyfile(self.video, target)
            ) as transport,
        ):
            call(self.project, "permit", "--candidate", ident, "--evidence", "Synthetic rights do not grant access")
            with self.assertRaisesRegex(OperationError, "explicit access decision"):
                call(self.project, "preview", "--candidate", ident)
            transport.assert_not_called()
            access = call(
                self.project,
                "access",
                "--candidate",
                ident,
                "--by",
                "Fixture",
                "--evidence",
                "Fixture explicitly authorizes working acquisition",
            )
            self.assertEqual("pending", access["approval"]["status"])
            call(self.project, "preview", "--candidate", ident)
            call(self.project, "approve", "--candidate", ident, "--by", "Fixture", "--channel", "storyboard")
            raw["scope_json"] = ["Changed source conditions"]
            with self.assertRaisesRegex(OperationError, "explicit access decision"):
                call(self.project, "fetch", "--candidate", ident)
            refreshed = Ledger(self.project).get(ident)
            self.assertEqual("pending", refreshed["approval"]["status"])
            self.assertEqual("unknown", refreshed["rights"]["status"])
            path = self.project / "BRIEF.md"
            path.write_text(
                path.read_text().replace("Original scenario narration", "Changed narration"), encoding="utf-8"
            )
            with self.assertRaisesRegex(OperationError, "current brief"):
                call(self.project, "preview", "--candidate", ident)
            self.assertEqual(1, transport.call_count)

    def test_un_transcript_and_player_failure_remain_distinct_then_preview_uses_source_time(self):
        write_brief(self.project, ["un_webtv"])
        save_plan(self.project, "un_webtv")

        def transport(url, params=None, **kw):
            if "meetings.json" in url:
                return {
                    "meetings": [
                        {"pageUrl": "/en/sc/10001", "matches": {"statements": [{"start": 2, "text": "nuclear treaty"}]}}
                    ]
                }
            return un_record()

        with patch.object(broadcasts, "get_json", side_effect=transport):
            ident = call(
                self.project,
                "search",
                "--planned",
                "--shot",
                "opening",
                "--query",
                "nuclear treaty",
                "--language",
                "en",
            )["items"][0]["id"]
            with patch.object(social, "probe_remote", side_effect=ProviderError("player unavailable")):
                inspected = call(self.project, "inspect", "--candidate", ident, "--query", "nuclear treaty")
            self.assertIn("unverified", str(inspected))
            self.assertIn(broadcasts.UN_DISCLAIMER, str(inspected))
            self.assertEqual("pending", Ledger(self.project).get(ident)["approval"]["status"])
            with (
                patch.object(social, "download_segment") as download,
                self.assertRaisesRegex(OperationError, "explicit access decision"),
            ):
                call(self.project, "preview", "--candidate", ident, "--start", "2", "--end", "4")
            download.assert_not_called()
            call(
                self.project, "access", "--candidate", ident, "--by", "Fixture", "--evidence", "Fixture access decision"
            )
            with patch.object(
                social,
                "download_segment",
                side_effect=lambda url, target, start, end: cut(self.video, target, start, end),
            ):
                preview = call(self.project, "preview", "--candidate", ident, "--start", "2", "--end", "4")
            self.assert_red(self.project / "brolls" / preview["preview"]["poster_path"])
            self.assertEqual(2, preview["local_start_s"])
            confirm(self.project, ident, "gif", ("Synthetic red middle", "Matches fixture target"))
            self.assertIn(broadcasts.UN_DISCLAIMER, storyboard(self.project))
            with self.assertRaises(OperationError):
                call(self.project, "fetch", "--candidate", ident)

    def test_gdelt_linked_local_original_retains_source_interval_and_closed_gates(self):
        write_brief(self.project, ["gdelt_tv", "local"])
        save_plan(self.project, "gdelt_tv")
        with patch.object(broadcasts, "get_json", return_value={"clips": [gdelt_record()]}):
            ident = call(
                self.project,
                "search",
                "--planned",
                "--shot",
                "opening",
                "--query",
                "treaty",
                "--catalog-filter",
                "station=CNN",
            )["items"][0]["id"]
        with self.assertRaisesRegex(OperationError, "locator"):
            call(self.project, "inspect", "--candidate", ident)
        original = call(
            self.project,
            "resolve",
            "--file",
            str(self.video),
            "--original-for",
            ident,
            "--original-conditions",
            "Synthetic supplied original",
        )
        self.assertEqual({"start_s": 2, "end_s": 4}, original["source_reference"]["source_interval"])
        self.assertEqual("unknown", original["rights"]["status"])
        self.assertEqual("pending", original["approval"]["status"])
        preview = call(self.project, "preview", "--candidate", original["id"], "--start", "2", "--end", "4")
        self.assert_red(self.project / "brolls" / preview["preview"]["poster_path"])
        with self.assertRaises(OperationError):
            call(self.project, "fetch", "--candidate", original["id"])


if __name__ == "__main__":
    unittest.main()
