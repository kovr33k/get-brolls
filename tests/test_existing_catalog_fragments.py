"""Planned confirmation for the five existing catalogs. Synthetic media only.

The Commons Ogg fixture follows the MediaWiki imageinfo shape (MIME separate from
mediatype). Its file URL and bytes are synthetic. This module does not download
the public Folgers file and does not claim live catalog access.
"""

import json
import os
import shutil
import tempfile
import unittest
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import patch

import _isolation  # noqa: F401
from _media import skip_unless_ffmpeg, synth_image, synth_video
from test_inspect import VTT, WITH_EVERYTHING, stub_ytdlp

from getbrolls import http, providers, social
from getbrolls.cli import parse_args
from getbrolls.commands import execute
from getbrolls.http import encoded_url
from getbrolls.ledger import Ledger
from getbrolls.media import probe
from getbrolls.runtime import OperationError, audited

QUERY = "laboratory bench"
NARRATION = "Original scenario narration"
SHOT = "opening"
FRAGMENT_REASON = "Search hit; visual confirmation required."
STOCK_REASON = "Stock catalog result. Visual match is unconfirmed and this is not reuse permission."
PHOTO_NOTE = "Photo search is not implemented for this catalog. Commons, NASA, and Archive.org accept --media image."
VIDEO_NOTE = "This catalog searches video. Image-only projects need an image catalog or a browser/local import route."
FIXTURE_EVIDENCE = "Synthetic fixture created by this automated test"
COMMONS_API = "https://commons.wikimedia.org/w/api.php"
OGG_PAGE = "7962265"
OGG_TITLE = "File:Fixture.ogv"
OGG_FILE = "https://upload.wikimedia.org/wikipedia/commons/fixture.ogv"
OGG_MIME = "application/ogg"
AUDIO_TITLE = "File:Audio.ogg"
YOUTUBE_ID = "abcdefghijk"
WATCH = f"https://www.youtube.com/watch?v={YOUTUBE_ID}"
NASA_DESCRIPTION = "Courtesy of a partner. Not a reuse grant."
EN_DASH = "\u2013"


def write_brief(project, sources, *, stock=False):
    data = {
        "version": 1,
        "video": {"title": "Fixture", "objective": "Original scenario", "delivery": {"format": "native"}},
        "rights": {"posture": "per_item_evidence", "stock_allowed": stock},
        "defaults": {
            "allowed_sources": list(sources),
            "intent": "literal",
            "duration_hint_s": 2,
            "stock": stock,
        },
        "beats": [{"id": SHOT, "target": "laboratory bench", "narration": NARRATION}],
    }
    (project / "BRIEF.md").write_text("```json\n" + json.dumps(data) + "\n```", encoding="utf-8")


def image_rules(project):
    data = {
        "version": 1,
        "asset_types": ["image"],
        "video_format": "native",
        "preferred_providers": {
            "literal": ["youtube", "commons", "nasa"],
            "illustrative": ["pexels", "pixabay"],
        },
        "preferred_domains": [],
        "blocked_domains": [],
        "editorial_rules": [],
        "copyright": {"mode": "per_item_evidence", "responsible_person": None, "declaration": None},
        "browser": {
            "viewport": "mobile",
            "mobile_width": 390,
            "mobile_height": 844,
            "desktop_width": 1440,
            "desktop_height": 900,
            "full_page": False,
        },
    }
    (project / "RULES.md").write_text("```json\n" + json.dumps(data) + "\n```", encoding="utf-8")


def call(project, *arguments):
    env_file = project / "empty.env"
    env_file.touch()
    args = parse_args(["--env-file", str(env_file), *arguments, "--project", str(project)])
    return audited(args, execute)


def save_plan(project, provider):
    return call(
        project,
        "search-plan",
        "--shot",
        SHOT,
        "--provider",
        provider,
        "--reason",
        f"{provider} holds this laboratory bench",
        "--expected-material",
        "Synthetic laboratory bench material",
    )


def planned(project, query=QUERY, media="video"):
    return call(
        project,
        "search",
        "--planned",
        "--shot",
        SHOT,
        "--provider",
        "auto",
        "--query",
        query,
        "--language",
        "en",
        "--media",
        media,
        "--limit",
        "5",
    )


def confirm(project, ident, preview, texts, distinctness=None):
    observation, match = texts
    arguments = [
        "search-confirm",
        "--shot",
        SHOT,
        "--candidate",
        ident,
        "--viewed",
        "preview",
        "--preview",
        preview,
        "--observation",
        observation,
        "--match",
        match,
        "--verdict",
        "suitable",
    ]
    if distinctness:
        arguments.extend(("--distinctness", distinctness))
    return call(project, *arguments)


def progress_row(project):
    return call(project, "status")["search_progress"][0]


def latest_evidence(project, ident):
    records = [row for row in progress_row(project)["viewing_evidence"] if row["candidate"] == ident]
    return records[-1]


def storyboard(project):
    call(project, "review", "--ready-only")
    return (project / "brolls" / "review.html").read_text(encoding="utf-8")


def sections(page):
    raw = page.split("<h4>Raw hits</h4>", 1)[1].split("<h4>Confirmed suitable options</h4>", 1)[0]
    suitable = page.split("<h4>Confirmed suitable options</h4>", 1)[1].split("<h4>Viewing evidence</h4>", 1)[0]
    return raw, suitable


def assert_storyboard_frame(test, page):
    test.assertIn("Scenario narration", page)
    test.assertIn(NARRATION, page)
    test.assertIn("Visual confirmation is not human approval and does not grant usage rights.", page)
    test.assertIn("Target reached: yes.", page)
    test.assertIn('class="pending-decision"', page)


def replay_and_stop(test, project, seen, media):
    before = len(seen)
    replayed = planned(project, QUERY, media)
    test.assertTrue(replayed["replayed"])
    test.assertEqual(before, len(seen))
    test.assertEqual(1, progress_row(project)["queries_used"])
    manifest = project / "brolls" / "manifest.json"
    snapshot = manifest.read_bytes()
    with test.assertRaisesRegex(OperationError, "Three suitable distinct"):
        planned(project, "another formulation", media)
    with test.assertRaisesRegex(OperationError, "Three suitable distinct"):
        call(
            project,
            "search",
            "--planned",
            "--shot",
            SHOT,
            "--query",
            "prospective query",
            "--media",
            media,
            "--dry-run",
        )
    test.assertEqual(before, len(seen))
    test.assertEqual(snapshot, manifest.read_bytes())
    test.assertEqual(1, progress_row(project)["queries_used"])


def assert_fetch_closed(test, project, ident):
    with test.assertRaisesRegex(OperationError, "Aprovação humana ausente"):
        call(project, "fetch", "--candidate", ident)
    stored = Ledger(project, recover=False).get(ident)
    test.assertEqual("pending", stored["approval"]["status"])
    test.assertEqual("unknown", stored["rights"]["status"])
    test.assertFalse(stored["output"]["verified"])


def reject_and_renew(test, project, ident, preview, distinctness=None):
    before = progress_row(project)["suitable_count"]
    call(project, "reject", "--candidate", ident, "--reason", "Synthetic rejection of the viewed material")
    test.assertEqual(before - 1, progress_row(project)["suitable_count"])
    test.assertEqual("rejected", latest_evidence(project, ident)["stale_reason"])
    call(
        project,
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
    test.assertEqual("approved", Ledger(project, recover=False).get(ident)["approval"]["status"])
    test.assertEqual(before - 1, progress_row(project)["suitable_count"])
    test.assertEqual("rejected", latest_evidence(project, ident)["stale_reason"])
    confirm(
        project,
        ident,
        preview,
        (
            "The same material was viewed again after the rejection.",
            "The renewed viewing matches the laboratory bench fragment.",
        ),
        distinctness,
    )
    test.assertEqual(before, progress_row(project)["suitable_count"])
    test.assertTrue(latest_evidence(project, ident)["current"])


def confirm_stills(test, project, ids):
    for ident in ids:
        preview = call(project, "preview", "--candidate", ident)
        stored = Ledger(project, recover=False).get(ident)
        poster = probe(preview["files"]["poster"])
        test.assertEqual(64, stored["media"]["width"])
        test.assertEqual(64, stored["media"]["height"])
        test.assertEqual(64, poster["width"])
        test.assertEqual(64, poster["height"])
        test.assertIsNone(stored["media"]["duration_s"])
        test.assertIsNone(stored["media"]["fps"])
        test.assertIsNone(stored["segment"]["start_s"])
        test.assertIsNone(stored["segment"]["end_s"])
        test.assertIsNone(preview["files"]["gif"])
        test.assertIsNone(preview["files"]["contact_sheet"])
        test.assertEqual("pending", stored["approval"]["status"])
        test.assertEqual("unknown", stored["rights"]["status"])
        confirm(
            project,
            ident,
            "poster",
            (
                "The still shows the laboratory bench.",
                "The viewed still matches the laboratory bench fragment.",
            ),
        )
    report = progress_row(project)
    test.assertEqual(ids, [hit["candidate"] for hit in report["raw_hits"]])
    identities = [item["candidate"] for option in report["suitable_options"] for item in option["identities"]]
    test.assertEqual(ids, identities)
    test.assertEqual(3, report["suitable_count"])
    test.assertTrue(report["target_reached"])
    test.assertEqual(1, report["queries_used"])
    return report


def confirm_scenes(test, project, root_id):
    scenes = []
    for name, start in (("exterior", 0), ("office", 2), ("machinery", 4)):
        created = call(
            project,
            "preview",
            "--candidate",
            root_id,
            "--start",
            str(start),
            "--end",
            str(start + 1),
            "--option",
            name,
        )
        test.assertEqual(root_id, created["selection"]["source_candidate"])
        test.assertTrue(Path(created["files"]["contact_sheet"]).is_file())
        test.assertEqual("pending", created["approval"]["status"])
        test.assertEqual("unknown", created["rights"]["status"])
        confirm(
            project,
            created["id"],
            "contact-sheet",
            (
                f"The {name} frames show a separate laboratory action.",
                f"The {name} interval matches a different part of the fragment.",
            ),
            f"Synthetic disjoint {name} moment.",
        )
        scenes.append(created["id"])
    report = progress_row(project)
    test.assertEqual([root_id], [hit["candidate"] for hit in report["raw_hits"]])
    identities = [item["candidate"] for option in report["suitable_options"] for item in option["identities"]]
    test.assertEqual(scenes, identities)
    test.assertEqual(3, report["suitable_count"])
    test.assertTrue(report["target_reached"])
    test.assertEqual(1, report["queries_used"])
    for option in report["suitable_options"]:
        test.assertEqual("supported", option["distinctness_support"])
        test.assertIsNone(option["grouped_reason"])
    return scenes


def assert_attempt(test, found, media):
    test.assertEqual(QUERY, found["attempt"]["query"])
    test.assertEqual("en", found["attempt"]["language"])
    test.assertEqual(media, found["attempt"]["media"])
    test.assertEqual(1, len(found["search_progress"][0]["attempts"]))
    item = found["items"][0]
    test.assertEqual(QUERY, item["query"])
    test.assertEqual(SHOT, item["shot"])
    test.assertEqual(NARRATION, item["narration"])
    test.assertTrue(item["id"].endswith(":shot:" + SHOT))
    test.assertEqual("pending", item["approval"]["status"])
    test.assertEqual("unknown", item["rights"]["status"])
    return item


def new_project():
    tmp = tempfile.TemporaryDirectory()
    return tmp, Path(tmp.name)


def commons_image_page(pageid, name, url, mediatype=None):
    info = {
        "mime": "image/jpeg",
        "url": url,
        "descriptionurl": f"https://commons.wikimedia.org/wiki/File:{name}.jpg",
        "width": 800,
        "height": 600,
        "extmetadata": {
            "Artist": {"value": "Fixture Author"},
            "LicenseShortName": {"value": "CC BY 4.0"},
            "LicenseUrl": {"value": "https://creativecommons.org/licenses/by/4.0/"},
        },
    }
    if mediatype:
        info["mediatype"] = mediatype
    return {"pageid": pageid, "title": f"File:{name}.jpg", "imageinfo": [info]}


def commons_excluded_page(pageid, title, mime, mediatype, url):
    return {
        "pageid": pageid,
        "title": title,
        "imageinfo": [{"mime": mime, "url": url, "width": 10, "height": 10, "mediatype": mediatype}],
    }


def ogg_info(mediatype=None, url=OGG_FILE, mime=OGG_MIME):
    info = {
        "size": 4775695,
        "width": 352,
        "height": 264,
        "duration": 60,
        "url": url,
        "descriptionurl": "https://commons.wikimedia.org/wiki/File:Fixture.ogv",
        "mime": mime,
        "thumburl": "https://upload.wikimedia.org/wikipedia/commons/thumb/fixture.ogv.jpg?time=12",
        "extmetadata": {
            "Artist": {"value": "Fixture Author"},
            "LicenseShortName": {"value": "Public domain"},
            "LicenseUrl": {"value": "https://creativecommons.org/publicdomain/mark/1.0/"},
        },
    }
    if mediatype:
        info["mediatype"] = mediatype
    return info


def videoinfo_payload():
    return {
        "query": {
            "pages": {
                OGG_PAGE: {
                    "videoinfo": [
                        {
                            "derivatives": [
                                {
                                    "type": "video/webm",
                                    "src": "https://upload.wikimedia.org/wikipedia/commons/transcode/fixture.webm",
                                    "transcodekey": "480p.webm",
                                    "width": 480,
                                    "height": 360,
                                }
                            ],
                            "timedtext": [
                                {
                                    "srclang": "en",
                                    "src": "https://commons.wikimedia.org/w/timedtext/fixture.vtt",
                                    "kind": "subtitles",
                                    "type": "text/vtt",
                                    "label": "English",
                                    "dir": "ltr",
                                }
                            ],
                        }
                    ]
                }
            }
        }
    }


class _Body:
    def __init__(self, body):
        self._body = body if isinstance(body, bytes) else body.encode("utf-8")
        self._pos = 0
        self.status = 200
        self.headers = {"Content-Length": str(len(self._body))}

    def read(self, n=-1):
        if n is None or n < 0:
            chunk = self._body[self._pos :]
            self._pos = len(self._body)
            return chunk
        chunk = self._body[self._pos : self._pos + n]
        self._pos += len(chunk)
        return chunk

    def __enter__(self):
        return self

    def __exit__(self, *_exc):
        return False


class _NasaApi:
    """HTTP opener stand-in. get_json still scrubs and caches the body."""

    def __init__(self, items, assets, media):
        self.items = items
        self.assets = assets
        self.media = media
        self.urls = []
        self.header_names = []

    def open(self, request, timeout=None):
        url = request.full_url
        names = [key for key, _value in request.header_items()]
        self.urls.append(url)
        self.header_names.append(names)
        if any(key.lower() == "authorization" for key in names):
            raise AssertionError(url)
        if "images-api.nasa.gov/search" in url:
            return _Body(json.dumps({"collection": {"items": self.items}}))
        if "/asset/" in url:
            ident = url.split("/asset/", 1)[1].split("?", 1)[0]
            return _Body(json.dumps(self.assets[ident]))
        for ident, body in self.media.items():
            if ident in url and "~medium." in url:
                return _Body(body)
        raise AssertionError(url)


@contextmanager
def nasa_api(project, items, assets, media):
    cache = project / "nasa-cache"
    cache.mkdir()
    transport = _NasaApi(items, assets, media)
    with (
        patch.dict(os.environ, {"GB_CACHE_DIR": str(cache)}),
        patch.object(http, "_opener", return_value=transport),
    ):
        yield transport, cache


def nasa_item(ident, kind, title):
    folder = "image" if kind == "image" else "video"
    ext = "jpg" if kind == "image" else "mp4"
    root = f"https://images-assets.nasa.gov/{folder}/{ident}/{ident}"
    return {
        "data": [
            {
                "center": "JPL",
                "date_created": "2020-02-12T00:00:00Z",
                "description": NASA_DESCRIPTION,
                "media_type": kind,
                "nasa_id": ident,
                "secondary_creator": "Example/Archive",
                "title": title,
            }
        ],
        "links": [
            {"href": f"{root}~medium.{ext}", "rel": "alternate"},
            {"href": f"{root}~thumb.jpg", "rel": "preview"},
            {"href": f"{root}~orig.{ext}", "rel": "canonical"},
        ],
    }


def nasa_asset(ident, kind):
    folder = "image" if kind == "image" else "video"
    ext = "jpg" if kind == "image" else "mp4"
    root = f"http://images-assets.nasa.gov/{folder}/{ident}"
    items = [
        {"href": f"{root}/{ident}~orig.{ext}"},
        {"href": f"{root}/{ident}~medium.{ext}"},
        {"href": f"{root}/{ident}~thumb.{ext}"},
        {"href": "http://evil.test/a.jpg"},
        {"href": "http://images-assets.nasa.gov.evil.test/a.jpg"},
        {"href": "http://x@images-assets.nasa.gov/secret.jpg"},
        {"href": "http://images-assets.nasa.gov/a.jpg?token=secret"},
        {"href": "http://images-api.nasa.gov/image/x/x~medium.jpg"},
        {"href": f"{root}/metadata.json"},
    ]
    return {"collection": {"items": items}}


def cached_text(cache):
    return "\n".join(path.read_text(encoding="utf-8") for path in sorted(Path(cache).glob("*.json")))


def assert_nasa_scrub(test, transport, cache, stored):
    text = cached_text(cache)
    test.assertIn("https://images-assets.nasa.gov", text)
    test.assertNotIn("http://images-assets.nasa.gov", text)
    test.assertFalse(any(url.startswith("http://") for url in transport.urls))
    for names in transport.header_names:
        test.assertFalse(any(name.lower() == "authorization" for name in names))
    blob = json.dumps(stored)
    test.assertNotIn("token=secret", blob)
    test.assertNotIn("evil.test", blob)
    test.assertNotIn(NASA_DESCRIPTION, " ".join(stored["rights"]["evidence"]))
    test.assertEqual("Example/Archive", stored["creator"]["name"])
    test.assertEqual("JPL", stored["nasa"]["center"])
    test.assertEqual("2020-02-12T00:00:00Z", stored["nasa"]["date"])
    test.assertIn("~thumb.jpg", stored["preview"]["poster_url"])
    test.assertNotEqual(stored["preview"]["poster_url"], stored["media_url"])


def pexels_row():
    return {
        "id": 7,
        "url": "https://www.pexels.com/video/laboratory-7/",
        "duration": 11,
        "image": "https://images.pexels.com/poster.jpg",
        "user": {"name": "Fixture Author", "url": "https://www.pexels.com/fixture/"},
        "video_pictures": [{"nr": 4, "picture": "https://images.pexels.com/frame-4.jpg"}],
        "video_files": [
            {"file_type": "video/mp4", "width": 3840, "height": 2160, "link": "https://videos.pexels.com/4k.mp4"},
            {"file_type": "video/mp4", "width": 1920, "height": 1080, "link": "https://videos.pexels.com/hd.mp4"},
        ],
    }


def pixabay_row(url="https://cdn.pixabay.com/large.mp4", width=1920, height=1080):
    return {
        "id": 9,
        "pageURL": "https://pixabay.com/videos/id-9/",
        "tags": "laboratory, bench",
        "user": "Fixture",
        "duration": 8,
        "videos": {
            "large": {
                "url": url,
                "width": width,
                "height": height,
                "thumbnail": "https://cdn.pixabay.com/thumb.jpg",
            }
        },
    }


class PlannedCatalogGuards(unittest.TestCase):
    def test_planned_photo_search_does_not_spend_a_query(self):
        for provider, stock in (("youtube", False), ("pexels", True), ("pixabay", True)):
            with self.subTest(provider=provider):
                tmp, project = new_project()
                self.addCleanup(tmp.cleanup)
                write_brief(project, [provider], stock=stock)
                with (
                    patch.object(providers, "get_json") as transport,
                    patch.object(social, "search") as youtube,
                ):
                    save_plan(project, provider)
                    explicit = call(
                        project,
                        "search",
                        "--planned",
                        "--shot",
                        SHOT,
                        "--provider",
                        provider,
                        "--query",
                        QUERY,
                        "--media",
                        "image",
                    )
                    automatic = planned(project, media="image")
                self.assertEqual(PHOTO_NOTE, explicit["note"])
                self.assertEqual(PHOTO_NOTE, automatic["note"])
                self.assertEqual([], explicit["items"])
                self.assertEqual([], automatic["items"])
                transport.assert_not_called()
                youtube.assert_not_called()
                plan = Ledger(project, recover=False).data["search_plans"][SHOT]
                self.assertEqual([], plan["attempts"])

    def test_image_only_rules_refuse_a_saved_video_catalog_before_a_query(self):
        tmp, project = new_project()
        self.addCleanup(tmp.cleanup)
        write_brief(project, ["youtube"])
        image_rules(project)
        with self.assertRaisesRegex(OperationError, "incompatible with project media policy"):
            save_plan(project, "youtube")

        tmp, project = new_project()
        self.addCleanup(tmp.cleanup)
        write_brief(project, ["youtube"])
        save_plan(project, "youtube")
        image_rules(project)
        with patch.object(providers, "get_json") as transport, patch.object(social, "search") as youtube:
            refused = planned(project, media="video")
        self.assertEqual(VIDEO_NOTE, refused["note"])
        self.assertEqual([], refused["items"])
        transport.assert_not_called()
        youtube.assert_not_called()
        self.assertEqual([], Ledger(project, recover=False).data["search_plans"][SHOT]["attempts"])


def commons_still_pages(project):
    pages = {}
    images = {}
    for pageid, color, mediatype in ((1, "red", "BITMAP"), (2, "blue", None), (3, "green", None)):
        path = project / f"{color}.jpg"
        synth_image(path, color=color, size="64x64")
        url = f"https://upload.wikimedia.org/wikipedia/commons/{color}.jpg"
        pages[str(pageid)] = commons_image_page(pageid, color, url, mediatype)
        images[url] = path
    pages["4"] = commons_excluded_page(4, AUDIO_TITLE, OGG_MIME, "AUDIO", "https://upload.wikimedia.org/audio.ogg")
    pages["5"] = {
        "pageid": 5,
        "title": "File:Bare.ogv",
        "imageinfo": [{"mime": OGG_MIME, "url": "https://upload.wikimedia.org/bare.ogv"}],
    }
    pages["6"] = commons_excluded_page(
        6, "File:Spoken.jpg", "image/jpeg", "AUDIO", "https://upload.wikimedia.org/spoken.jpg"
    )
    return pages, images


def ogg_catalog_pages():
    return {
        OGG_PAGE: {"pageid": int(OGG_PAGE), "title": OGG_TITLE, "imageinfo": [ogg_info("VIDEO")]},
        "2": {
            "pageid": 2,
            "title": AUDIO_TITLE,
            "imageinfo": [ogg_info("AUDIO", "https://upload.wikimedia.org/audio.ogg")],
        },
        "3": {
            "pageid": 3,
            "title": "File:Bare.ogv",
            "imageinfo": [ogg_info(None, "https://upload.wikimedia.org/bare.ogv")],
        },
        "4": commons_excluded_page(
            4, "File:Notes.pdf", "application/pdf", "OFFICE", "https://upload.wikimedia.org/notes.pdf"
        ),
    }


def assert_ogg_hit(test, found, calls):
    item = assert_attempt(test, found, "video")
    root_id = item["id"]
    test.assertEqual(f"commons:{OGG_PAGE}:shot:opening", root_id)
    test.assertEqual([root_id], [row["id"] for row in found["items"]])
    test.assertEqual(OGG_MIME, item["commons"]["mime"])
    test.assertEqual("VIDEO", item["commons"]["mediatype"])
    test.assertEqual(OGG_FILE, item["media_url"])
    test.assertEqual("absent", item["commons"]["videoinfo"])
    test.assertEqual(352, item["media"]["width"])
    test.assertEqual(264, item["media"]["height"])
    test.assertIsNone(item["media"]["duration_s"])
    test.assertIn("time=12", item["preview"]["poster_url"])
    test.assertEqual("Public domain", item["rights"]["license_name"])
    test.assertEqual("Fixture Author", item["creator"]["name"])
    test.assertEqual(FRAGMENT_REASON, item["match"]["reason"])
    search = next(query for query in calls if query.get("generator") == "search")
    test.assertIn("mediatype", search["iiprop"])
    test.assertIn("filetype:video", search["gsrsearch"])
    test.assertEqual("imageinfo", search["prop"])
    return root_id


def assert_ogg_scene(test, project, root_id, scenes):
    scene = Ledger(project, recover=False).get(scenes[0])
    root = Ledger(project, recover=False).get(root_id)
    test.assertEqual(160, scene["media"]["width"])
    test.assertEqual(90, scene["media"]["height"])
    test.assertIsNone(scene["media"]["duration_s"])
    test.assertEqual(OGG_FILE, scene["media_url"])
    test.assertEqual(OGG_MIME, scene["commons"]["mime"])
    test.assertEqual("VIDEO", scene["commons"]["mediatype"])
    test.assertEqual("absent", scene["commons"]["videoinfo"])
    test.assertNotIn("timed_text", scene["commons"])
    test.assertEqual(352, root["media"]["width"])
    test.assertIsNone(root["media"]["duration_s"])
    test.assertEqual((0.0, 1.0), (scene["segment"]["start_s"], scene["segment"]["end_s"]))


def assert_video_storyboard(test, project, root_id, scenes):
    page = storyboard(project)
    raw, _suitable = sections(page)
    assert_storyboard_frame(test, page)
    test.assertEqual(1, raw.count('class="raw-hit"'))
    test.assertIn(root_id, raw)
    for scene_id in scenes:
        test.assertNotIn(scene_id, raw)
    for interval in ("0.0" + EN_DASH + "1.0 s", "2.0" + EN_DASH + "3.0 s", "4.0" + EN_DASH + "5.0 s"):
        test.assertIn(interval, page)


def assert_ogg_refresh(test, project, root_id, calls):
    root = Ledger(project, recover=False).get(root_id)
    refreshed = providers.refresh(root)
    reread = Ledger(project, recover=False).get(root_id)
    test.assertEqual("absent", reread["commons"]["videoinfo"])
    test.assertEqual("present", refreshed["commons"]["videoinfo"])
    test.assertEqual(OGG_FILE, refreshed["media_url"])
    test.assertEqual(OGG_MIME, refreshed["commons"]["representations"][0]["mime"])
    test.assertEqual("480p.webm", refreshed["commons"]["representations"][1]["transcodekey"])
    test.assertEqual("en", refreshed["commons"]["timed_text"][0]["lang"])
    test.assertNotEqual(OGG_FILE, refreshed["commons"]["representations"][1]["url"])
    refresh_calls = [query for query in calls if query.get("pageids") == OGG_PAGE]
    test.assertIn("mediatype", refresh_calls[0]["iiprop"])
    test.assertNotIn("extmetadata", refresh_calls[0]["iiprop"])
    with test.assertRaisesRegex(OperationError, "não é vídeo nem imagem"):
        call(project, "resolve", "--url", "https://commons.wikimedia.org/wiki/File:Audio.ogg")
    test.assertFalse(any(query.get("prop") == "videoinfo" and query.get("titles") == AUDIO_TITLE for query in calls))


def assert_youtube_hit(test, found, seen, transport):
    item = assert_attempt(test, found, "video")
    root_id = item["id"]
    test.assertEqual(f"youtube:{YOUTUBE_ID}:shot:opening", root_id)
    test.assertEqual("Fixture Channel", item["creator"]["name"])
    test.assertEqual(WATCH, item["source_url"])
    test.assertEqual("yt-dlp", item["acquisition"]["method"])
    test.assertEqual(
        ["availability: unlisted", "age_limit: 18", "live_status: is_upcoming"],
        item["limitations"],
    )
    test.assertEqual(FRAGMENT_REASON, item["match"]["reason"])
    test.assertEqual("literal", item["match"]["kind"])
    test.assertNotIn("stock", item)
    test.assertEqual([(QUERY, 5)], seen)
    transport.assert_not_called()
    return root_id


def assert_youtube_inspect(test, project, root_id):
    stub = project / "ytdlp-stub"
    stub.mkdir()
    with patch.dict(os.environ, stub_ytdlp(stub, WITH_EVERYTHING, VTT)):
        inspected = call(project, "inspect", "--candidate", root_id, "--query", "tempestade")
    stored = Ledger(project, recover=False).get(root_id)
    test.assertEqual(120.0, stored["media"]["duration_s"])
    test.assertIn("live_status: is_upcoming", stored["limitations"])
    test.assertIn("Abertura", [chapter["title"] for chapter in inspected["chapters"]])
    test.assertIn("pt", inspected["subtitle_langs"])
    test.assertTrue(
        any("tempestade" in (window.get("text") or "").casefold() for window in inspected["candidate_windows"])
    )


def assert_youtube_shift(test, project, scenes, segment_calls):
    shifted = call(project, "preview", "--candidate", scenes[0], "--start", "0.2", "--end", "1.2")
    test.assertEqual(scenes[0], shifted["id"])
    held = progress_row(project)
    test.assertEqual(2, held["suitable_count"])
    test.assertEqual("interval_changed", latest_evidence(project, scenes[0])["stale_reason"])
    spans = [item["interval"] for option in held["suitable_options"] for item in option["identities"]]
    test.assertEqual({(2.0, 3.0), (4.0, 5.0)}, {(row["start_s"], row["end_s"]) for row in spans})
    confirm(
        project,
        scenes[0],
        "contact-sheet",
        (
            "The shifted exterior frames still show a separate laboratory action.",
            "The 0.2 to 1.2 second interval matches a different part of the fragment.",
        ),
        "Synthetic disjoint exterior moment.",
    )
    restored = progress_row(project)
    test.assertEqual(3, restored["suitable_count"])
    restored_spans = [
        (item["interval"]["start_s"], item["interval"]["end_s"])
        for option in restored["suitable_options"]
        for item in option["identities"]
    ]
    test.assertEqual({(0.2, 1.2), (2.0, 3.0), (4.0, 5.0)}, set(restored_spans))
    for option in restored["suitable_options"]:
        test.assertIsNone(option["grouped_reason"])
    reject_and_renew(test, project, scenes[0], "contact-sheet", "Synthetic disjoint exterior moment.")
    with test.assertRaisesRegex(OperationError, "permit"):
        call(project, "fetch", "--candidate", scenes[0])
    before_fetch = len(segment_calls)
    call(project, "permit", "--candidate", scenes[0], "--evidence", FIXTURE_EVIDENCE)
    fetched = call(project, "fetch", "--candidate", scenes[0])
    test.assertEqual(before_fetch, len(segment_calls))
    test.assertEqual("verified", fetched["state"])
    test.assertEqual("permitted", fetched["rights"]["status"])
    test.assertIn(FIXTURE_EVIDENCE, " ".join(fetched["rights"]["evidence"]))
    test.assertTrue((project / "brolls" / fetched["output"]["path"]).is_file())


@skip_unless_ffmpeg
class ExistingCatalogFragments(unittest.TestCase):
    def test_commons_images_reach_the_measured_still_target(self):
        tmp, project = new_project()
        self.addCleanup(tmp.cleanup)
        write_brief(project, ["commons"])
        save_plan(project, "commons")
        pages, images = commons_still_pages(project)
        calls = []

        def transport(url, params=None, headers=None, cache_ttl=0):
            query = dict(params or {})
            calls.append(query)
            if url != COMMONS_API or query.get("prop") == "videoinfo":
                raise AssertionError((url, query))
            if query.get("generator") == "search":
                return {"query": {"pages": pages}}
            pageid = str(query.get("pageids") or "")
            return {"query": {"pages": {pageid: pages[pageid]}}}

        def save(url, target, max_bytes=None):
            shutil.copyfile(images[url], target)
            return target

        with (
            patch.object(providers, "get_json", side_effect=transport),
            patch("getbrolls.http.download", side_effect=save),
        ):
            found = planned(project, media="image")
            item = assert_attempt(self, found, "image")
            self.assertEqual("commons:1:shot:opening", item["id"])
            self.assertEqual("BITMAP", item["commons"]["mediatype"])
            self.assertEqual("image/jpeg", item["commons"]["mime"])
            self.assertNotIn("mediatype", found["items"][1]["commons"])
            self.assertEqual(800, item["media"]["width"])
            self.assertIsNone(item["media"]["duration_s"])
            self.assertEqual("image", item["media"]["kind"])
            self.assertEqual("CC BY 4.0", item["rights"]["license_name"])
            self.assertEqual(FRAGMENT_REASON, item["match"]["reason"])
            self.assertEqual("literal", item["match"]["kind"])
            self.assertNotIn("stock", item)
            ids = [row["id"] for row in found["items"]]
            self.assertEqual(
                ["commons:1:shot:opening", "commons:2:shot:opening", "commons:3:shot:opening"],
                ids,
            )
            search = next(query for query in calls if query.get("generator") == "search")
            self.assertIn("mediatype", search["iiprop"])
            self.assertIn("filetype:bitmap", search["gsrsearch"])
            self.assertEqual("imageinfo", search["prop"])
            confirm_stills(self, project, ids)
            replay_and_stop(self, project, calls, "image")
            page = storyboard(project)
            raw, suitable = sections(page)
            assert_storyboard_frame(self, page)
            self.assertEqual(3, raw.count('class="raw-hit"'))
            self.assertEqual(3, suitable.count('class="suitable-option"'))
            for ident in ids:
                self.assertIn(ident, raw)
                self.assertIn("Still image " + ident.split(":")[1], page)
            assert_fetch_closed(self, project, ids[0])
            reject_and_renew(self, project, ids[0], "poster")

    def test_commons_ogg_video_scenes_keep_the_declared_file(self):
        tmp, project = new_project()
        self.addCleanup(tmp.cleanup)
        write_brief(project, ["commons"])
        save_plan(project, "commons")
        video = project / "clip.mp4"
        synth_video(video, size="160x90", duration=6)
        pages = ogg_catalog_pages()
        calls = []

        def transport(url, params=None, headers=None, cache_ttl=0):
            query = dict(params or {})
            calls.append(query)
            if url != COMMONS_API:
                raise AssertionError(url)
            if query.get("prop") == "videoinfo":
                if query.get("titles") != OGG_TITLE:
                    raise AssertionError(query)
                return videoinfo_payload()
            if query.get("generator") == "search":
                return {"query": {"pages": pages}}
            if query.get("titles") == AUDIO_TITLE:
                return {"query": {"pages": {"2": pages["2"]}}}
            pageid = str(query.get("pageids") or "")
            return {"query": {"pages": {pageid: pages[pageid]}}}

        def save(url, target, max_bytes=None):
            self.assertEqual(OGG_FILE, url)
            shutil.copyfile(video, target)
            return target

        with (
            patch.object(providers, "get_json", side_effect=transport),
            patch("getbrolls.http.download", side_effect=save),
        ):
            found = planned(project, media="video")
            root_id = assert_ogg_hit(self, found, calls)
            scenes = confirm_scenes(self, project, root_id)
            assert_ogg_scene(self, project, root_id, scenes)
            replay_and_stop(self, project, calls, "video")
            assert_video_storyboard(self, project, root_id, scenes)
            assert_fetch_closed(self, project, scenes[0])
            assert_ogg_refresh(self, project, root_id, calls)
            reject_and_renew(self, project, scenes[0], "contact-sheet", "Synthetic disjoint exterior moment.")

    def test_nasa_images_use_scrubbed_medium_files(self):
        tmp, project = new_project()
        self.addCleanup(tmp.cleanup)
        write_brief(project, ["nasa"])
        save_plan(project, "nasa")
        colors = ("nasa-red", "nasa-blue", "nasa-green")
        items = [nasa_item(ident, "image", ident) for ident in colors]
        assets = {ident: nasa_asset(ident, "image") for ident in colors}
        media = {}
        for ident, color in zip(colors, ("red", "blue", "green"), strict=True):
            path = project / f"{color}.jpg"
            synth_image(path, color=color, size="64x64")
            media[ident] = path.read_bytes()
        with nasa_api(project, items, assets, media) as (transport, cache):
            found = planned(project, media="image")
            item = assert_attempt(self, found, "image")
            ids = [row["id"] for row in found["items"]]
            self.assertEqual([f"nasa:{ident}:shot:opening" for ident in colors], ids)
            self.assertEqual(
                encoded_url(f"https://images-assets.nasa.gov/image/{colors[0]}/{colors[0]}~medium.jpg"),
                item["media_url"],
            )
            self.assertEqual(FRAGMENT_REASON, item["match"]["reason"])
            self.assertEqual("literal", item["match"]["kind"])
            self.assertIsNone(item["media"]["width"])
            self.assertIsNone(item["media"]["duration_s"])
            self.assertTrue(any("media_type=image" in url for url in transport.urls))
            confirm_stills(self, project, ids)
            stored = Ledger(project, recover=False).get(ids[0])
            assert_nasa_scrub(self, transport, cache, stored)
            self.assertIn("~medium.jpg", stored["media_url"])
            self.assertEqual(colors[0], stored["nasa"]["nasa_id"])
            replay_and_stop(self, project, transport.urls, "image")
            page = storyboard(project)
            raw, _suitable = sections(page)
            assert_storyboard_frame(self, page)
            self.assertEqual(3, raw.count('class="raw-hit"'))
            self.assertIn("Still image " + colors[0], page)
            assert_fetch_closed(self, project, ids[0])
            reject_and_renew(self, project, ids[0], "poster")

    def test_nasa_video_interval_uses_the_scrubbed_mp4(self):
        tmp, project = new_project()
        self.addCleanup(tmp.cleanup)
        write_brief(project, ["nasa"])
        save_plan(project, "nasa")
        ident = "nasa-film"
        video = project / "clip.mp4"
        synth_video(video, size="160x90", duration=6)
        with nasa_api(
            project,
            [nasa_item(ident, "video", "Laboratory film")],
            {ident: nasa_asset(ident, "video")},
            {ident: video.read_bytes()},
        ) as (transport, cache):
            found = planned(project, media="video")
            item = assert_attempt(self, found, "video")
            root_id = item["id"]
            expected = encoded_url(f"https://images-assets.nasa.gov/video/{ident}/{ident}~medium.mp4")
            self.assertEqual(expected, item["media_url"])
            self.assertEqual("video", item["media"]["kind"])
            self.assertIsNone(item["media"]["duration_s"])
            self.assertTrue(any("media_type=video" in url for url in transport.urls))
            preview = call(project, "preview", "--candidate", root_id, "--start", "0", "--end", "1")
            stored = Ledger(project, recover=False).get(root_id)
            self.assertEqual(160, stored["media"]["width"])
            self.assertEqual(90, stored["media"]["height"])
            self.assertIsNone(stored["media"]["duration_s"])
            self.assertEqual((0.0, 1.0), (stored["segment"]["start_s"], stored["segment"]["end_s"]))
            self.assertTrue(Path(preview["files"]["contact_sheet"]).is_file())
            self.assertEqual(expected, stored["media_url"])
            confirm(
                project,
                root_id,
                "contact-sheet",
                (
                    "The film shows the laboratory bench.",
                    "The viewed interval matches the laboratory bench fragment.",
                ),
            )
            report = progress_row(project)
            self.assertEqual(1, report["suitable_count"])
            self.assertEqual(1, len(report["raw_hits"]))
            self.assertFalse(report["target_reached"])
            self.assertEqual("pending", stored["approval"]["status"])
            assert_nasa_scrub(self, transport, cache, stored)
            self.assertIn("~medium.mp4", stored["media_url"])
            assert_fetch_closed(self, project, root_id)
            reject_and_renew(self, project, root_id, "contact-sheet")

    def test_youtube_scenes_keep_source_limits_and_inspect(self):
        tmp, project = new_project()
        self.addCleanup(tmp.cleanup)
        write_brief(project, ["youtube"])
        save_plan(project, "youtube")
        video = project / "clip.mp4"
        synth_video(video, size="160x90", duration=6)
        seen = []
        segment_calls = []
        row = {
            "id": YOUTUBE_ID,
            "title": "Laboratory bench",
            "channel": "Fixture Channel",
            "duration": 95,
            "availability": "unlisted",
            "age_limit": 18,
            "live_status": "is_upcoming",
            "thumbnails": [{"url": "https://i.ytimg.com/vi/abcdefghijk/hqdefault.jpg"}],
        }

        def search_stub(query, limit):
            seen.append((query, limit))
            return [row]

        def save_segment(url, target, start, end):
            segment_calls.append((url, start, end))
            self.assertEqual(WATCH, url)
            shutil.copyfile(video, target)

        with (
            patch.object(social, "search", side_effect=search_stub),
            patch.object(providers, "get_json") as transport,
            patch.object(social, "download_segment", side_effect=save_segment),
        ):
            found = planned(project, media="video")
            root_id = assert_youtube_hit(self, found, seen, transport)
            assert_youtube_inspect(self, project, root_id)
            scenes = confirm_scenes(self, project, root_id)
            replay_and_stop(self, project, seen, "video")
            assert_video_storyboard(self, project, root_id, scenes)
            assert_fetch_closed(self, project, scenes[0])
            assert_youtube_shift(self, project, scenes, segment_calls)

    def test_pexels_scenes_stay_illustrative_and_keyed(self):
        self._assert_stock_scenes(
            "pexels",
            "PEXELS_API_KEY",
            "https://videos.pexels.com/hd.mp4",
            pexels_row,
            self._pexels_transport,
        )

    def test_pixabay_scenes_stay_illustrative_and_cached(self):
        self._assert_stock_scenes(
            "pixabay",
            "PIXABAY_API_KEY",
            "https://cdn.pixabay.com/large.mp4",
            pixabay_row,
            self._pixabay_transport,
        )

    def _assert_stock_scenes(self, provider, env_key, media_url, row_factory, transport_factory):
        tmp, project = new_project()
        self.addCleanup(tmp.cleanup)
        write_brief(project, [provider], stock=True)
        save_plan(project, provider)
        video = project / "clip.mp4"
        synth_video(video, size="160x90", duration=6)
        calls = []
        transport = transport_factory(calls, row_factory())

        def save(url, target, max_bytes=None):
            self.assertEqual(media_url, url)
            shutil.copyfile(video, target)
            return target

        with (
            patch.dict(os.environ, {env_key: "fixture-key", "GB_CACHE_DIR": str(project / "cache")}),
            patch.object(providers, "get_json", side_effect=transport),
            patch("getbrolls.http.download", side_effect=save),
        ):
            (project / "cache").mkdir()
            found = planned(project, media="video")
            item = assert_attempt(self, found, "video")
            self.assertTrue(item["stock"])
            self.assertEqual("illustrative", item["match"]["kind"])
            self.assertEqual(STOCK_REASON, item["match"]["reason"])
            self.assertEqual("literal", Ledger(project, recover=False).data["search_plans"][SHOT]["context"]["intent"])
            self.assertEqual(media_url, item["media_url"])
            self.assertIsNone(item["segment"]["start_s"])
            self.assertNotIn("fixture-key", json.dumps(item))
            scenes = confirm_scenes(self, project, item["id"])
            stored = Ledger(project, recover=False).get(scenes[0])
            self.assertEqual(160, stored["media"]["width"])
            self.assertEqual(90, stored["media"]["height"])
            self.assertEqual(media_url, stored["media_url"])
            self.assertNotEqual(4, stored["segment"]["start_s"])
            self.assertNotIn("fixture-key", json.dumps(stored))
            self.assertTrue(stored["stock"])
            self.assertEqual("illustrative", stored["match"]["kind"])
            replay_and_stop(self, project, calls, "video")
            page = storyboard(project)
            raw, _suitable = sections(page)
            assert_storyboard_frame(self, page)
            self.assertEqual(1, raw.count('class="raw-hit"'))
            assert_fetch_closed(self, project, scenes[0])
            reject_and_renew(self, project, scenes[0], "contact-sheet", "Synthetic disjoint exterior moment.")
        return calls

    def _pexels_transport(self, calls, row):
        def transport(url, params=None, headers=None, cache_ttl=None):
            calls.append(url)
            self.assertIsNone(cache_ttl)
            self.assertEqual("fixture-key", (headers or {})["Authorization"])
            if url.endswith("/search"):
                self.assertEqual("https://api.pexels.com/v1/videos/search", url)
                return {"videos": [row]}
            self.assertEqual("https://api.pexels.com/v1/videos/videos/7", url)
            return row

        return transport

    def _pixabay_transport(self, calls, row):
        def transport(url, params=None, headers=None, cache_ttl=None):
            calls.append(url)
            self.assertEqual(86400, cache_ttl)
            self.assertEqual("https://pixabay.com/api/videos/", url)
            self.assertEqual("fixture-key", (params or {})["key"])
            self.assertNotIn("fixture-key", headers or {})
            if params and params.get("id"):
                self.assertEqual("9", str(params["id"]))
            return {"hits": [row]}

        return transport
