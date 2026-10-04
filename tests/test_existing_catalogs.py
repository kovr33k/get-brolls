"""Audited routes for the five existing catalogs. Synthetic media, no live providers."""

import json
import os
import shutil
import tempfile
import unittest
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import patch
from urllib.parse import quote

import _isolation  # noqa: F401
from _media import skip_unless_ffmpeg, synth_image, synth_video
from _paths import ROOT  # noqa: F401

from getbrolls import http, providers, social
from getbrolls.cli import parse_args
from getbrolls.commands import execute
from getbrolls.http import ProviderError, encoded_url
from getbrolls.ledger import Ledger
from getbrolls.media import probe
from getbrolls.models import candidate
from getbrolls.runtime import OperationError, audited

PHOTO_NOTE = "Photo search is not implemented for this catalog. Commons, NASA, and Archive.org accept --media image."
VIDEO_NOTE = "APIs atuais pesquisam vídeos. Para imagem/notícia use importação local ou browser-plan."
STOCK_REASON = "Stock catalog result. Visual match is unconfirmed and this is not reuse permission."
YOUTUBE_ID = "abcdefghijk"
COMMONS_FILE = "https://upload.wikimedia.org/wikipedia/commons/fixture.jpg"
COMMONS_THUMB = "https://upload.wikimedia.org/wikipedia/commons/thumb/fixture.jpg?time=12"
NARRATION = "A linha de montagem continua em português."
NASA_ID = "fixture still"
NASA_DESCRIPTION = "Courtesy of a partner. Not a reuse grant."
NASA_MEDIUM_SCRUBBED = f"https://images-assets.nasa.gov/image/{NASA_ID}/{NASA_ID}~medium.jpg"
NASA_MEDIUM = encoded_url(NASA_MEDIUM_SCRUBBED)
NASA_PREVIEW = encoded_url(f"https://images-assets.nasa.gov/image/{NASA_ID}/{NASA_ID}~thumb.jpg")
NASA_DETAILS = "https://images.nasa.gov/details/" + quote(NASA_ID, safe="")


def call(project, *arguments):
    env_file = project / "empty.env"
    env_file.touch()
    args = parse_args(["--env-file", str(env_file), *arguments, "--project", str(project)])
    return audited(args, execute)


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
    (Path(project) / "RULES.md").write_text("```json\n" + json.dumps(data) + "\n```", encoding="utf-8")


def commons_page(mime="image/jpeg", url=COMMONS_FILE, thumb=COMMONS_THUMB):
    return {
        "query": {
            "pages": {
                "42": {
                    "pageid": 42,
                    "title": "File:Fixture.jpg" if mime.startswith("image/") else "File:Fixture.webm",
                    "imageinfo": [
                        {
                            "mime": mime,
                            "url": url,
                            "thumburl": thumb,
                            "descriptionurl": "https://commons.wikimedia.org/wiki/File:Fixture.jpg",
                            "width": 800,
                            "height": 600,
                            "extmetadata": {
                                "Artist": {"value": "<a href='https://example.invalid/ada'>Ada</a>"},
                                "LicenseShortName": {"value": "CC BY 4.0"},
                                "LicenseUrl": {"value": "https://creativecommons.org/licenses/by/4.0/"},
                                "Attribution": {"value": "Ada, CC BY 4.0"},
                            },
                        }
                    ],
                }
            }
        }
    }


def assert_decoded_still(test, project, preview, ident, media_url):
    """The still preview is a decoded image, with no invented interval and rights still unknown."""
    poster = Path(preview["files"]["poster"])
    stored = Ledger(project).get(ident)
    material = Path(stored["local_path"])
    test.assertEqual(media_url, preview["media_url"])
    test.assertEqual(media_url, stored["media_url"])
    test.assertEqual((64, 64), (probe(poster)["width"], probe(poster)["height"]))
    test.assertEqual((64, 64), (probe(material)["width"], probe(material)["height"]))
    test.assertIsNone(preview["segment"]["start_s"])
    test.assertIsNone(preview["segment"]["end_s"])
    test.assertIsNone(stored["segment"]["start_s"])
    test.assertIsNone(stored["segment"]["end_s"])
    test.assertEqual("pending", preview["approval"]["status"])
    test.assertEqual("pending", stored["approval"]["status"])
    test.assertEqual("unknown", preview["rights"]["status"])
    test.assertEqual("unknown", stored["rights"]["status"])
    return stored


def nasa_search_page():
    """Search metadata shape. Preview links on this host are already HTTPS."""
    root = f"https://images-assets.nasa.gov/image/{NASA_ID}/{NASA_ID}"
    return {
        "collection": {
            "items": [
                {
                    "data": [
                        {
                            "center": "JPL",
                            "date_created": "2020-02-12T00:00:00Z",
                            "description": NASA_DESCRIPTION,
                            "media_type": "image",
                            "nasa_id": NASA_ID,
                            "secondary_creator": "Example/Archive",
                            "title": "Fixture still",
                        }
                    ],
                    "links": [
                        {"href": root + "~medium.jpg", "rel": "alternate", "render": "image"},
                        {"href": root + "~thumb.jpg", "rel": "preview", "render": "image"},
                        {"href": root + "~orig.jpg", "rel": "canonical", "render": "image"},
                    ],
                }
            ]
        }
    }


def nasa_asset_page(include_file=True):
    """Raw asset hrefs as the Images API publishes them, before get_json scrubs the body."""
    root = f"http://images-assets.nasa.gov/image/{NASA_ID}"
    items = [
        {"href": "http://evil.test/a.jpg"},
        {"href": "http://images-assets.nasa.gov.evil.test/a.jpg"},
        {"href": "http://x@images-assets.nasa.gov/secret.jpg"},
        {"href": "http://images-assets.nasa.gov/a.jpg?token=secret"},
        {"href": "http://images-api.nasa.gov/image/x/x~medium.jpg"},
        {"href": f"{root}/metadata.json"},
    ]
    if include_file:
        items = [
            {"href": f"{root}/{NASA_ID}~orig.jpg"},
            {"href": f"{root}/{NASA_ID}~large.jpg"},
            {"href": f"{root}/{NASA_ID}~medium.jpg"},
            {"href": f"{root}/{NASA_ID}~small.jpg"},
            {"href": f"{root}/{NASA_ID}~thumb.jpg"},
            *items,
        ]
    return {"collection": {"items": items}}


class _ApiBody:
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
    """Stand-in for the HTTP opener. get_json still scrubs and caches the body."""

    def __init__(self, image=None, files=True):
        self.image = image
        self.files = files
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
            return _ApiBody(json.dumps(nasa_search_page()))
        if "images-api.nasa.gov/asset/" in url:
            return _ApiBody(json.dumps(nasa_asset_page(self.files)))
        if self.image is not None and "~medium.jpg" in url:
            return _ApiBody(self.image)
        raise AssertionError(url)


@contextmanager
def nasa_api(project, image=None, files=True):
    cache = Path(project) / "cache"
    cache.mkdir(exist_ok=True)
    transport = _NasaApi(image=image, files=files)
    with (
        patch.dict(os.environ, {"GB_CACHE_DIR": str(cache)}),
        patch.object(http, "_opener", return_value=transport),
    ):
        yield transport, cache


def cached_bodies(cache):
    return "\n".join(path.read_text(encoding="utf-8") for path in sorted(Path(cache).glob("*.json")))


def asset_requests(transport):
    quoted = "/asset/" + quote(NASA_ID, safe="")
    return [url for url in transport.urls if quoted in url]


def pexels_row(link="https://videos.pexels.com/hd.mp4", width=1920, height=1080):
    return {
        "id": 7,
        "url": "https://www.pexels.com/video/laboratory-7/",
        "duration": 11,
        "image": "https://images.pexels.com/poster.jpg",
        "user": {"name": "Fixture Author", "url": "https://www.pexels.com/fixture/"},
        "video_pictures": [{"nr": 4, "picture": "https://images.pexels.com/frame-4.jpg"}],
        "video_files": [
            {"file_type": "video/mp4", "width": 3840, "height": 2160, "link": "https://videos.pexels.com/4k.mp4"},
            {"file_type": "video/mp4", "width": width, "height": height, "link": link},
        ],
    }


class ExistingCatalogRoutes(unittest.TestCase):
    def test_dated_samples_stay_separate_from_configured_and_current_access(self):
        with patch.dict(os.environ, {"PEXELS_API_KEY": "", "PIXABAY_API_KEY": ""}):
            report = providers.capabilities()
        for name in ("commons", "nasa", "pexels", "pixabay"):
            self.assertEqual("sample_verified", report[name]["live"])
            self.assertEqual("2026-10-04", report[name]["live_observation"]["date"])
            self.assertEqual("2.7.0", report[name]["live_observation"]["version"])
            self.assertEqual("passed", report[name]["live_observation"]["preview"])
            self.assertFalse(report[name]["access_verified"])
        self.assertFalse(report["pexels"]["configured"])
        self.assertFalse(report["pixabay"]["configured"])
        self.assertEqual("unsuitable", report["pexels"]["live_observation"]["visual_verdict"])
        self.assertIsNone(report["nasa"]["live_observation"]["duration_s"])
        self.assertIsNone(report["nasa"]["live_observation"]["interval_s"])
        self.assertEqual("sample_verified", report["youtube"]["live"])
        self.assertEqual("passed_sample", report["youtube"]["live_observation"]["status"])
        self.assertEqual("passed", report["youtube"]["live_observation"]["preview"])
        self.assertEqual("passed", report["youtube"]["live_observation"]["decode"])
        self.assertFalse(report["youtube"]["access_verified"])
        with patch.dict(os.environ, {"PEXELS_API_KEY": "synthetic-fixture-secret"}):
            configured = providers.capabilities()
        self.assertTrue(configured["pexels"]["configured"])
        self.assertFalse(configured["pexels"]["access_verified"])
        self.assertNotIn("synthetic-fixture-secret", json.dumps(configured))

    def test_youtube_search_keeps_identity_and_does_not_call_another_catalog(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(providers, "get_json") as transport:
            project = Path(tmp)
            with patch.object(
                social,
                "search",
                return_value=[
                    {
                        "id": YOUTUBE_ID,
                        "title": "Discurso original",
                        "channel": "Canal Oficial",
                        "duration": 95,
                        "availability": "unlisted",
                        "thumbnails": [{"url": "https://i.ytimg.com/vi/abcdefghijk/hqdefault.jpg"}],
                    }
                ],
            ):
                result = call(
                    project,
                    "search",
                    "--provider",
                    "youtube",
                    "--query",
                    "discurso",
                    "--shot",
                    "speech",
                    "--limit",
                    "2",
                )
            transport.assert_not_called()
            item = result["items"][0]
            self.assertEqual(f"youtube:{YOUTUBE_ID}:shot:speech", item["id"])
            self.assertEqual("discurso", item["query"])
            self.assertEqual("speech", item["shot"])
            self.assertEqual("Canal Oficial", item["creator"]["name"])
            self.assertEqual(f"https://www.youtube.com/watch?v={YOUTUBE_ID}", item["source_url"])
            self.assertEqual("yt-dlp", item["acquisition"]["method"])
            self.assertEqual(["availability: unlisted"], item["limitations"])
            self.assertEqual("literal", item["match"]["kind"])
            self.assertEqual("pending", item["approval"]["status"])
            self.assertEqual("unknown", item["rights"]["status"])
            self.assertIsNone(item["segment"]["start_s"])
            self.assertNotIn("stock", item)
            saved = Ledger(project).get(item["id"])
            self.assertEqual(item["limitations"], saved["limitations"])
            self.assertEqual("discurso", saved["query"])

    def test_boolean_age_and_public_availability_are_not_invented_limits(self):
        self.assertEqual([], social.source_limitations({"availability": "public", "age_limit": True}))
        self.assertEqual([], social.source_limitations({"live_status": "not_live"}))
        self.assertEqual(
            ["age_limit: 18", "live_status: is_upcoming"],
            social.source_limitations({"age_limit": 18, "live_status": "is_upcoming"}),
        )

    def test_youtube_resolve_records_probe_limits_without_an_api_key(self):
        payload = {
            "id": YOUTUBE_ID,
            "title": "Keynote",
            "channel": "NVIDIA",
            "channel_id": "UC123",
            "uploader_id": "@nvidia",
            "channel_url": "https://www.youtube.com/channel/UC123",
            "duration": 120,
            "availability": "public",
            "age_limit": 18,
            "live_status": "not_live",
        }
        with (
            tempfile.TemporaryDirectory() as tmp,
            patch.object(social, "run", return_value=(json.dumps(payload), [])) as spy,
        ):
            result = call(Path(tmp), "resolve", "--url", f"https://youtu.be/{YOUTUBE_ID}")
        argv = spy.call_args.args[0]
        self.assertIn("--skip-download", argv)
        self.assertNotIn("--api-key", argv)
        self.assertEqual(["age_limit: 18"], result["limitations"])
        self.assertEqual("NVIDIA", result["creator"]["name"])
        self.assertEqual("@nvidia", result["creator"]["handle"])
        self.assertEqual(120.0, result["media"]["duration_s"])
        self.assertEqual("pending", result["approval"]["status"])

    def test_commons_image_search_keeps_the_file_and_ignores_the_timed_thumbnail(self):
        with (
            tempfile.TemporaryDirectory() as tmp,
            patch.object(providers, "get_json", return_value=commons_page()) as transport,
        ):
            result = call(
                Path(tmp),
                "search",
                "--provider",
                "commons",
                "--media",
                "image",
                "--query",
                "arquivo histórico",
                "--shot",
                "still",
            )
        self.assertEqual(1, transport.call_count)
        self.assertNotIn("videoinfo", transport.call_args.args[1]["prop"])
        self.assertIn("filetype:bitmap", transport.call_args.args[1]["gsrsearch"])
        item = result["items"][0]
        self.assertEqual("commons:42:shot:still", item["id"])
        self.assertEqual("arquivo histórico", item["query"])
        self.assertEqual("image", item["media"]["kind"])
        self.assertEqual("image", item["asset_type"])
        self.assertEqual(COMMONS_FILE, item["media_url"])
        self.assertEqual(COMMONS_THUMB, item["preview"]["poster_url"])
        self.assertNotIn("time=", item["media_url"])
        self.assertIsNone(item["segment"]["start_s"])
        self.assertIsNone(item["segment"]["end_s"])
        self.assertEqual("Ada", item["creator"]["name"])
        self.assertEqual("CC BY 4.0", item["rights"]["license_name"])
        self.assertEqual("https://creativecommons.org/licenses/by/4.0/", item["rights"]["license_url"])
        self.assertEqual("unknown", item["rights"]["status"])
        self.assertEqual("absent", item["commons"]["videoinfo"])
        self.assertEqual(COMMONS_FILE, item["commons"]["representations"][0]["url"])
        self.assertTrue(all("time=" not in (row["url"] or "") for row in item["commons"]["representations"]))
        self.assertEqual(800, item["media"]["width"])
        self.assertEqual(600, item["media"]["height"])

    def test_commons_video_resolve_reads_srclang_tracks_without_downloading_captions(self):
        file_url = "https://upload.wikimedia.org/wikipedia/commons/fixture.webm"
        tracked_original = file_url + "?utm_source=commons.wikimedia.org&utm_campaign=api&utm_content=original"
        transcode = "https://upload.wikimedia.org/wikipedia/commons/transcoded/fixture.webm/fixture.480p.webm"
        alternate = "https://upload.wikimedia.org/wikipedia/commons/other-fixture.webm"
        english = (
            "https://commons.wikimedia.org/w/api.php?action=timedtext&title=File%3AFixture.webm&lang=en&trackformat=vtt"
        )
        german = (
            "https://commons.wikimedia.org/w/api.php?action=timedtext&title=File%3AFixture.webm&lang=de&trackformat=vtt"
        )
        alias = "https://commons.wikimedia.org/w/api.php?action=timedtext&title=File%3AFixture.webm&trackformat=vtt"
        codec = 'video/webm; codecs="vp9, opus"'
        transcode_key = "480p.webm"
        pages = [
            commons_page(mime="video/webm", url=file_url),
            {
                "query": {
                    "pages": {
                        "42": {
                            "videoinfo": [
                                {
                                    "derivatives": [
                                        {
                                            "type": "image/jpeg",
                                            "src": "https://upload.wikimedia.org/poster.jpg?time=3",
                                            "width": 320,
                                            "height": 180,
                                        },
                                        {
                                            "type": 'video/webm; codecs="vp8, vorbis"',
                                            "src": tracked_original,
                                            "width": 800,
                                            "height": 600,
                                        },
                                        {
                                            "type": codec,
                                            "src": transcode,
                                            "transcodekey": transcode_key,
                                            "width": 480,
                                            "height": 270,
                                        },
                                        {
                                            "type": "video/webm",
                                            "src": alternate,
                                            "width": 640,
                                            "height": 360,
                                        },
                                    ],
                                    "timedtext": [
                                        {
                                            "src": english,
                                            "kind": "subtitles",
                                            "type": "text/vtt",
                                            "srclang": "en",
                                            "dir": "ltr",
                                            "label": "English (en)",
                                        },
                                        {
                                            "src": german,
                                            "kind": "subtitles",
                                            "type": "text/vtt",
                                            "srclang": "de",
                                            "dir": "ltr",
                                            "label": "Deutsch (de)",
                                        },
                                        {
                                            "url": alias,
                                            "kind": "subtitles",
                                            "type": "text/vtt",
                                            "language": "pt",
                                        },
                                        {"src": "https://commons.wikimedia.org/no-lang.vtt", "kind": "subtitles"},
                                        {"srclang": "sv", "kind": "subtitles", "type": "text/vtt"},
                                        {"srclang": "fr", "src": "http://commons.wikimedia.org/insecure.vtt"},
                                        "not-a-track",
                                    ],
                                }
                            ]
                        }
                    }
                }
            },
        ]
        with tempfile.TemporaryDirectory() as tmp, patch.object(providers, "get_json", side_effect=pages) as transport:
            project = Path(tmp)
            item = call(project, "resolve", "--url", "https://commons.wikimedia.org/wiki/File:Fixture.webm")
            saved = Ledger(project).get(item["id"])
        props = [request.args[1]["prop"] for request in transport.call_args_list]
        requested = [request.args[0] for request in transport.call_args_list]
        self.assertEqual(["imageinfo", "videoinfo"], props)
        self.assertEqual("derivatives|timedtext", transport.call_args_list[1].args[1]["viprop"])
        self.assertEqual(2, transport.call_count)
        self.assertTrue(all("action=timedtext" not in url for url in requested))
        self.assertEqual(file_url, item["media_url"])
        self.assertEqual(file_url, saved["media_url"])
        self.assertNotIn("time=", saved["media_url"])
        self.assertIsNone(saved["segment"]["start_s"])
        self.assertEqual("present", saved["commons"]["videoinfo"])
        self.assertEqual(
            [
                {"role": "original", "url": file_url, "mime": "video/webm", "width": 800, "height": 600},
                {
                    "role": "derivative",
                    "url": transcode,
                    "mime": codec,
                    "width": 480,
                    "height": 270,
                    "transcodekey": transcode_key,
                },
                {"url": alternate, "mime": "video/webm", "width": 640, "height": 360},
            ],
            saved["commons"]["representations"],
        )
        roles = [row.get("role") for row in saved["commons"]["representations"]]
        self.assertEqual(["original", "derivative", None], roles)
        self.assertNotIn(tracked_original, [row["url"] for row in saved["commons"]["representations"]])
        tracks = [
            {
                "lang": "en",
                "url": english,
                "kind": "subtitles",
                "type": "text/vtt",
                "label": "English (en)",
                "dir": "ltr",
            },
            {
                "lang": "de",
                "url": german,
                "kind": "subtitles",
                "type": "text/vtt",
                "label": "Deutsch (de)",
                "dir": "ltr",
            },
            {"lang": "pt", "url": alias, "kind": "subtitles", "type": "text/vtt"},
        ]
        self.assertEqual(tracks, item["commons"]["timed_text"])
        self.assertEqual(tracks, saved["commons"]["timed_text"])
        self.assertEqual("CC BY 4.0", saved["rights"]["license_name"])
        self.assertEqual("unknown", saved["rights"]["status"])

    def test_commons_videoinfo_failure_still_resolves_the_file(self):
        file_url = "https://upload.wikimedia.org/wikipedia/commons/fixture.webm"

        def transport(url, params=None, headers=None, cache_ttl=0):
            if params and params.get("prop") == "videoinfo":
                raise ProviderError("videoinfo ausente")
            return commons_page(mime="video/webm", url=file_url)

        with tempfile.TemporaryDirectory() as tmp, patch.object(providers, "get_json", side_effect=transport):
            project = Path(tmp)
            item = call(project, "resolve", "--url", "https://commons.wikimedia.org/wiki/File:Fixture.webm")
            saved = Ledger(project).get(item["id"])
        self.assertEqual(file_url, saved["media_url"])
        self.assertEqual("absent", saved["commons"]["videoinfo"])
        self.assertNotIn("timed_text", saved["commons"])
        self.assertEqual(file_url, saved["commons"]["representations"][0]["url"])

    def test_commons_malformed_videoinfo_keeps_the_original_file(self):
        file_url = "https://upload.wikimedia.org/wikipedia/commons/fixture.webm"
        pages = [
            {"query": {"pages": {"42": {"videoinfo": [{"timedtext": {"srclang": "en"}, "derivatives": "nope"}]}}}},
            {"query": {"pages": {"42": {"videoinfo": []}}}},
            {
                "query": {
                    "pages": {
                        "42": {
                            "videoinfo": [
                                {
                                    "timedtext": [
                                        {"src": "https://commons.wikimedia.org/no-lang.vtt"},
                                        "bad",
                                    ],
                                    "derivatives": [
                                        {
                                            "type": "image/jpeg",
                                            "src": "https://upload.wikimedia.org/poster.jpg?time=1",
                                        }
                                    ],
                                }
                            ]
                        }
                    }
                }
            },
        ]
        for second in pages:
            with (
                tempfile.TemporaryDirectory() as tmp,
                patch.object(
                    providers,
                    "get_json",
                    side_effect=[commons_page(mime="video/webm", url=file_url), second],
                ),
            ):
                project = Path(tmp)
                item = call(project, "resolve", "--url", "https://commons.wikimedia.org/wiki/File:Fixture.webm")
                saved = Ledger(project).get(item["id"])
            self.assertEqual(file_url, saved["media_url"])
            self.assertNotIn("timed_text", saved["commons"])
            self.assertEqual([file_url], [row["url"] for row in saved["commons"]["representations"]])
            self.assertNotIn("time=", saved["media_url"])
            self.assertEqual("unknown", saved["rights"]["status"])

    def test_nasa_keeps_center_date_and_third_party_without_a_developer_key(self):
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp)
            with nasa_api(project) as (transport, cache):
                result = call(
                    project,
                    "search",
                    "--provider",
                    "nasa",
                    "--media",
                    "image",
                    "--query",
                    "apollo still",
                    "--shot",
                    "moon",
                )
                item = result["items"][0]
                saved = Ledger(project).get(item["id"])
                stored = cached_bodies(cache)
            self.assertEqual(
                ["https://images-api.nasa.gov/asset/" + quote(NASA_ID, safe="")], asset_requests(transport)
            )
            self.assertEqual([], [url for url in transport.urls if " " in url])
            self.assertFalse(any(name.lower() == "authorization" for names in transport.header_names for name in names))
            self.assertIn(NASA_MEDIUM_SCRUBBED, stored)
            self.assertNotIn("http://", stored)
            self.assertNotIn("token=secret", stored)
            self.assertNotIn("Fixture still", stored)
        self.assertEqual("JPL", saved["nasa"]["center"])
        self.assertEqual(f"nasa:{NASA_ID}:shot:moon", item["id"])
        self.assertEqual("apollo still", item["query"])
        self.assertEqual(NASA_MEDIUM, item["media_url"])
        self.assertEqual(NASA_MEDIUM, saved["media_url"])
        self.assertNotEqual(NASA_PREVIEW, item["media_url"])
        self.assertEqual(NASA_PREVIEW, item["preview"]["poster_url"])
        self.assertEqual(NASA_DETAILS, item["source_url"])
        self.assertEqual("image", item["media"]["kind"])
        self.assertEqual("Example/Archive", item["creator"]["name"])
        self.assertEqual(
            {
                "nasa_id": NASA_ID,
                "center": "JPL",
                "date": "2020-02-12T00:00:00Z",
                "secondary_creator": "Example/Archive",
                "description": NASA_DESCRIPTION,
            },
            item["nasa"],
        )
        self.assertEqual("unknown", item["rights"]["status"])
        self.assertNotIn(NASA_DESCRIPTION, " ".join(item["rights"]["evidence"]))
        self.assertEqual("pending", item["approval"]["status"])
        self.assertNotIn("http://", item["media_url"])
        self.assertNotIn("token=secret", json.dumps(saved))
        self.assertNotIn("nasa_api_key", json.dumps(result).lower())

    def test_nasa_resolve_keeps_the_scrubbed_https_file_and_rejects_other_links(self):
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp)
            with nasa_api(project) as (transport, cache):
                item = call(project, "resolve", "--url", NASA_DETAILS)
                saved = Ledger(project).get(item["id"])
                stored = cached_bodies(cache)
            self.assertEqual(
                ["https://images-api.nasa.gov/asset/" + quote(NASA_ID, safe="")], asset_requests(transport)
            )
            self.assertEqual([], [url for url in transport.urls if " " in url])
            self.assertIn(NASA_MEDIUM_SCRUBBED, stored)
            self.assertNotIn("http://", stored)
            self.assertNotIn("token=secret", stored)
        self.assertEqual(NASA_MEDIUM, saved["media_url"])
        self.assertEqual(NASA_PREVIEW, saved["preview"]["poster_url"])
        self.assertEqual(NASA_DETAILS, saved["source_url"])
        self.assertEqual(NASA_ID, saved["nasa"]["nasa_id"])
        self.assertEqual("2020-02-12T00:00:00Z", saved["nasa"]["date"])
        self.assertEqual("Example/Archive", saved["creator"]["name"])
        self.assertEqual("unknown", saved["rights"]["status"])
        self.assertEqual("available", saved["acquisition"]["status"])
        self.assertNotIn("token=secret", json.dumps(saved))
        self.assertNotIn("evil.test", json.dumps(saved))

        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp)
            with nasa_api(project, files=False) as (transport, cache):
                item = call(project, "resolve", "--url", NASA_DETAILS)
                saved = Ledger(project).get(item["id"])
                stored = cached_bodies(cache)
            self.assertEqual(
                ["https://images-api.nasa.gov/asset/" + quote(NASA_ID, safe="")], asset_requests(transport)
            )
            self.assertNotIn("http://", stored)
            self.assertNotIn("token=secret", stored)
        self.assertIsNone(saved["media_url"])
        self.assertEqual(NASA_PREVIEW, saved["preview"]["poster_url"])
        self.assertEqual("unavailable", saved["acquisition"]["status"])
        self.assertEqual(NASA_ID, saved["nasa"]["nasa_id"])
        self.assertEqual("unknown", saved["rights"]["status"])
        self.assertNotIn("token=secret", json.dumps(saved))

    def test_pexels_keeps_stock_policy_dimensions_and_ignores_picture_index(self):
        with (
            tempfile.TemporaryDirectory() as tmp,
            patch.dict(os.environ, {"PEXELS_API_KEY": "fixture-key"}),
            patch.object(providers, "get_json", return_value={"videos": [pexels_row()]}) as transport,
        ):
            result = call(
                Path(tmp),
                "search",
                "--provider",
                "pexels",
                "--query",
                "laboratory glass",
                "--intent",
                "literal",
                "--shot",
                "stock",
            )
            saved = Ledger(Path(tmp)).get(result["items"][0]["id"])
        self.assertNotIn("cache_ttl", transport.call_args.kwargs)
        self.assertEqual("fixture-key", transport.call_args.args[2]["Authorization"])
        self.assertEqual("https://api.pexels.com/v1/videos/search", transport.call_args.args[0])
        item = result["items"][0]
        self.assertEqual("https://videos.pexels.com/hd.mp4", item["media_url"])
        self.assertEqual(1920, item["media"]["width"])
        self.assertEqual(1080, item["media"]["height"])
        self.assertEqual(11, item["media"]["duration_s"])
        self.assertIsNone(item["segment"]["start_s"])
        self.assertNotEqual(4, item["segment"]["start_s"])
        self.assertTrue(item["stock"])
        self.assertEqual("illustrative", item["match"]["kind"])
        self.assertEqual(STOCK_REASON, item["match"]["reason"])
        self.assertEqual("unknown", item["rights"]["status"])
        self.assertEqual("laboratory glass", item["query"])
        self.assertNotIn("fixture-key", json.dumps(result))
        self.assertEqual("illustrative", saved["match"]["kind"])
        self.assertTrue(saved["stock"])

    def test_pixabay_keeps_the_cached_video_and_refreshes_its_dimensions(self):
        def row(width, height, url):
            return {
                "id": 9,
                "pageURL": "https://pixabay.com/videos/id-9/",
                "tags": "laboratory, glass",
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

        answers = [
            {"hits": [row(1920, 1080, "https://cdn.pixabay.com/large.mp4")]},
            {"hits": [row(1280, 720, "https://cdn.pixabay.com/refreshed.mp4")]},
        ]
        with (
            tempfile.TemporaryDirectory() as tmp,
            patch.dict(os.environ, {"PIXABAY_API_KEY": "fixture-key"}),
            patch.object(providers, "get_json", side_effect=answers) as transport,
        ):
            result = call(Path(tmp), "search", "--provider", "pixabay", "--query", "glass", "--shot", "bank")
            saved = Ledger(Path(tmp)).get(result["items"][0]["id"])
            refreshed = providers.refresh(saved)
        self.assertEqual(86400, transport.call_args_list[0].kwargs["cache_ttl"])
        self.assertEqual(86400, transport.call_args_list[1].kwargs["cache_ttl"])
        item = result["items"][0]
        self.assertEqual("https://cdn.pixabay.com/large.mp4", item["media_url"])
        self.assertEqual("https://cdn.pixabay.com/thumb.jpg", item["preview"]["poster_url"])
        self.assertEqual(8, item["media"]["duration_s"])
        self.assertIsNone(item["segment"]["start_s"])
        self.assertTrue(item["stock"])
        self.assertEqual("illustrative", item["match"]["kind"])
        self.assertEqual(STOCK_REASON, item["match"]["reason"])
        self.assertNotIn("fixture-key", json.dumps(result))
        self.assertEqual("https://cdn.pixabay.com/refreshed.mp4", refreshed["media_url"])
        self.assertEqual(1280, refreshed["media"]["width"])
        self.assertEqual(720, refreshed["media"]["height"])
        self.assertEqual(8, refreshed["media"]["duration_s"])
        self.assertEqual(saved["approval"], refreshed["approval"])
        self.assertEqual(saved["segment"], refreshed["segment"])

    def test_photo_search_is_refused_and_image_needs_still_reach_commons(self):
        def urls(project, *arguments):
            seen = []

            def transport(url, params=None, headers=None, cache_ttl=0):
                seen.append(url)
                if "commons.wikimedia.org" in url:
                    return {"query": {"pages": {}}}
                if "images-api.nasa.gov" in url:
                    return {"collection": {"items": []}}
                raise AssertionError(url)

            with patch.object(providers, "get_json", side_effect=transport), patch.object(social, "search") as youtube:
                result = call(project, *arguments)
                youtube.assert_not_called()
            return result, seen

        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp)
            refused, seen = urls(project, "search", "--provider", "pexels", "--media", "image", "--query", "moon")
            self.assertEqual(PHOTO_NOTE, refused["note"])
            self.assertEqual([], refused["items"])
            self.assertEqual([], seen)
            alias, seen = urls(project, "search", "--provider", "pixel", "--media", "image", "--query", "moon")
            self.assertEqual(PHOTO_NOTE, alias["note"])
            self.assertEqual([], seen)
            youtube, seen = urls(project, "search", "--provider", "youtube", "--media", "image", "--query", "moon")
            self.assertEqual(PHOTO_NOTE, youtube["note"])
            self.assertEqual([], seen)

        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp)
            image_rules(project)
            refused, seen = urls(project, "search", "--provider", "youtube", "--query", "moon")
            self.assertEqual(VIDEO_NOTE, refused["note"])
            self.assertEqual([], seen)
            found, seen = urls(project, "search", "--provider", "auto", "--query", "moon")
            self.assertEqual([], found["items"])
            self.assertTrue(any("commons.wikimedia.org" in url for url in seen))
            self.assertTrue(any("images-api.nasa.gov" in url for url in seen))
            self.assertFalse(any("pexels" in url or "pixabay" in url or "youtube" in url for url in seen))

    def test_dry_run_does_not_save_and_status_does_not_recover_an_old_project(self):
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp)
            with patch.object(
                social,
                "search",
                return_value=[{"id": YOUTUBE_ID, "title": "Dry", "channel": "Canal", "duration": 10}],
            ):
                result = call(project, "search", "--provider", "youtube", "--query", "dry", "--dry-run")
            self.assertTrue(result["dry_run"])
            self.assertEqual(1, len(result["items"]))
            self.assertFalse((project / "brolls" / "manifest.json").exists())
            self.assertEqual([], list((project / "brolls" / "candidates").glob("*.json")))

        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp)
            root = project / "brolls"
            root.mkdir()
            old = candidate("youtube", YOUTUBE_ID, "Old title", f"https://www.youtube.com/watch?v={YOUTUBE_ID}")
            (root / "manifest.json").write_text(
                json.dumps({"schema_version": 1, "items": [old]}),
                encoding="utf-8",
            )
            pending = root / ".pending-transaction.json"
            pending.write_text('{"kept": true}\n', encoding="utf-8")
            before_manifest = (root / "manifest.json").read_bytes()
            before_pending = pending.read_bytes()
            with patch("getbrolls.runtime._acquire_lock", side_effect=AssertionError("status locked")):
                status = call(project, "status")
            self.assertEqual(before_manifest, (root / "manifest.json").read_bytes())
            self.assertEqual(before_pending, pending.read_bytes())
            self.assertEqual("pending", status["journal"]["recovered_write"])
            self.assertFalse((root / "candidates").exists())
            self.assertFalse((root / "previews").exists())
            self.assertFalse((root / "clips").exists())
            opened = Ledger(project, recover=False).get(old["id"])
            self.assertNotIn("nasa", opened)
            self.assertNotIn("commons", opened)
            self.assertNotIn("limitations", opened)

    def test_missing_key_and_unknown_items_stay_bounded(self):
        with (
            tempfile.TemporaryDirectory() as tmp,
            patch.dict(os.environ, {"PEXELS_API_KEY": ""}),
            self.assertRaises(OperationError) as caught,
        ):
            call(Path(tmp), "search", "--provider", "pexels", "--query", "glass")
        self.assertIn("PEXELS_API_KEY", str(caught.exception))
        self.assertNotIn("fixture-key", str(caught.exception))

        with (
            tempfile.TemporaryDirectory() as tmp,
            patch.object(
                providers,
                "get_json",
                return_value={"query": {"pages": {"-1": {"missing": ""}}}},
            ),
            self.assertRaises(OperationError) as caught,
        ):
            call(Path(tmp), "resolve", "--url", "https://commons.wikimedia.org/wiki/File:Missing.jpg")
        self.assertIn("Missing.jpg", str(caught.exception))

        with (
            tempfile.TemporaryDirectory() as tmp,
            patch.object(providers, "get_json", return_value={"collection": {"items": []}}),
            self.assertRaises(OperationError) as caught,
        ):
            call(Path(tmp), "resolve", "--url", "https://images.nasa.gov/details/nao-existe")
        self.assertIn("nao-existe", str(caught.exception))


OGG_PAGE = "7962265"
OGG_FILE = "https://upload.wikimedia.org/wikipedia/commons/fixture.ogv"
OGG_TITLE = "File:Fixture.ogv"
OGG_MIME = "application/ogg"


def ogg_info(mediatype, url=OGG_FILE, mime=OGG_MIME):
    """imageinfo shape from the 2026-10-04 File:Folgers.ogv response, with synthetic bytes."""
    info = {
        "size": 4775695,
        "width": 352,
        "height": 264,
        "duration": 60,
        "url": url,
        "descriptionurl": "https://commons.wikimedia.org/wiki/File:Fixture.ogv",
        "mime": mime,
        "extmetadata": {
            "Artist": {"value": "Fixture Author"},
            "LicenseShortName": {"value": "Public domain"},
            "LicenseUrl": {"value": "https://creativecommons.org/publicdomain/mark/1.0/"},
        },
    }
    if mediatype:
        info["mediatype"] = mediatype
    return info


def ogg_page(mediatype, url=OGG_FILE, mime=OGG_MIME, pageid=OGG_PAGE, title=OGG_TITLE):
    return {
        "query": {
            "pages": {
                str(pageid): {
                    "pageid": int(pageid) if str(pageid).isdigit() else pageid,
                    "title": title,
                    "imageinfo": [ogg_info(mediatype, url, mime)],
                }
            }
        }
    }


def mixed_commons_pages():
    """Official container types plus the MIME fallback and the excluded mediatypes."""
    pages = {
        "1": {
            "pageid": 1,
            "title": "File:Fixture.ogv",
            "imageinfo": [ogg_info("VIDEO", OGG_FILE, OGG_MIME)],
        },
        "2": {
            "pageid": 2,
            "title": "File:Audio.ogg",
            "imageinfo": [ogg_info("AUDIO", "https://upload.wikimedia.org/wikipedia/commons/audio.ogg")],
        },
        "3": {
            "pageid": 3,
            "title": "File:Bare.ogg",
            "imageinfo": [ogg_info(None, "https://upload.wikimedia.org/wikipedia/commons/bare.ogg")],
        },
        "4": {
            "pageid": 4,
            "title": "File:Still.jpg",
            "imageinfo": [
                {
                    "mime": "image/jpeg",
                    "url": "https://upload.wikimedia.org/wikipedia/commons/still.jpg",
                    "descriptionurl": "https://commons.wikimedia.org/wiki/File:Still.jpg",
                    "width": 800,
                    "height": 600,
                }
            ],
        },
        "5": {
            "pageid": 5,
            "title": "File:Labeled-audio.jpg",
            "imageinfo": [
                {
                    "mime": "image/jpeg",
                    "mediatype": "AUDIO",
                    "url": "https://upload.wikimedia.org/wikipedia/commons/labeled-audio.jpg",
                    "descriptionurl": "https://commons.wikimedia.org/wiki/File:Labeled-audio.jpg",
                }
            ],
        },
        "6": {
            "pageid": 6,
            "title": "File:Notes.pdf",
            "imageinfo": [
                {
                    "mime": "application/pdf",
                    "mediatype": "OFFICE",
                    "url": "https://upload.wikimedia.org/wikipedia/commons/notes.pdf",
                }
            ],
        },
        "7": {
            "pageid": 7,
            "title": "File:Program.exe",
            "imageinfo": [
                {
                    "mime": "application/octet-stream",
                    "mediatype": "EXECUTABLE",
                    "url": "https://upload.wikimedia.org/wikipedia/commons/program.exe",
                }
            ],
        },
        "8": {
            "pageid": 8,
            "title": "File:Notes.txt",
            "imageinfo": [
                {
                    "mime": "text/plain",
                    "mediatype": "TEXT",
                    "url": "https://upload.wikimedia.org/wikipedia/commons/notes.txt",
                }
            ],
        },
        "9": {
            "pageid": 9,
            "title": "File:Diagram.svg",
            "imageinfo": [
                {
                    "mime": "image/svg+xml",
                    "mediatype": "DRAWING",
                    "url": "https://upload.wikimedia.org/wikipedia/commons/diagram.svg",
                    "descriptionurl": "https://commons.wikimedia.org/wiki/File:Diagram.svg",
                    "width": 640,
                    "height": 480,
                }
            ],
        },
    }
    return {"query": {"pages": pages}}


class CommonsContainerKind(unittest.TestCase):
    """application/ogg follows mediatype. The MIME string stays what the API returned."""

    def test_search_keeps_declared_video_and_drops_audio_office_and_bare_application(self):
        def transport(url, params=None, headers=None, cache_ttl=0):
            self.assertIn("mediatype", (params or {})["iiprop"])
            self.assertNotIn("videoinfo", (params or {})["prop"])
            return mixed_commons_pages()

        with tempfile.TemporaryDirectory() as tmp, patch.object(providers, "get_json", side_effect=transport):
            project = Path(tmp)
            both = call(project, "search", "--provider", "commons", "--query", "fixture", "--media", "any")
            video = call(project, "search", "--provider", "commons", "--query", "fixture", "--media", "video")
            image = call(project, "search", "--provider", "commons", "--query", "fixture", "--media", "image")
        self.assertEqual(["commons:1", "commons:4", "commons:9"], [item["id"] for item in both["items"]])
        ogg = both["items"][0]
        self.assertEqual("video", ogg["media"]["kind"])
        self.assertEqual(OGG_MIME, ogg["commons"]["mime"])
        self.assertEqual("VIDEO", ogg["commons"]["mediatype"])
        self.assertEqual(OGG_FILE, ogg["media_url"])
        self.assertEqual(OGG_MIME, ogg["commons"]["representations"][0]["mime"])
        self.assertIsNone(ogg["media"]["duration_s"])
        self.assertEqual("unknown", ogg["rights"]["status"])
        self.assertEqual("pending", ogg["approval"]["status"])
        self.assertEqual(["commons:1"], [item["id"] for item in video["items"]])
        self.assertEqual(["commons:4", "commons:9"], [item["id"] for item in image["items"]])
        self.assertEqual("image", image["items"][1]["asset_type"])

    def test_resolve_accepts_ogg_video_and_refuses_audio_office_and_executable(self):
        calls = []

        def transport(url, params=None, headers=None, cache_ttl=0):
            calls.append(params or {})
            title = (params or {}).get("titles")
            if title == "File:Fixture.ogv":
                if (params or {}).get("prop") == "videoinfo":
                    return {"query": {"pages": {OGG_PAGE: {"videoinfo": [{"derivatives": [], "timedtext": []}]}}}}
                return ogg_page("VIDEO")
            if title == "File:Audio.ogg":
                return ogg_page(
                    "AUDIO", "https://upload.wikimedia.org/wikipedia/commons/audio.ogg", pageid="2", title=title
                )
            if title == "File:Notes.pdf":
                return ogg_page(
                    "OFFICE", "https://upload.wikimedia.org/wikipedia/commons/notes.pdf", "application/pdf", "6", title
                )
            if title == "File:Program.exe":
                return ogg_page(
                    "EXECUTABLE",
                    "https://upload.wikimedia.org/wikipedia/commons/program.exe",
                    "application/octet-stream",
                    "7",
                    title,
                )
            raise AssertionError(params)

        with tempfile.TemporaryDirectory() as tmp, patch.object(providers, "get_json", side_effect=transport):
            project = Path(tmp)
            item = call(project, "resolve", "--url", "https://commons.wikimedia.org/wiki/File:Fixture.ogv")
            saved = Ledger(project).get(item["id"])
            for title in ("File:Audio.ogg", "File:Notes.pdf", "File:Program.exe"):
                with self.assertRaises(OperationError) as caught:
                    call(project, "resolve", "--url", "https://commons.wikimedia.org/wiki/" + title.replace(" ", "_"))
                self.assertIn("não é vídeo nem imagem", str(caught.exception))
        props = [row.get("prop") for row in calls]
        self.assertEqual(["imageinfo", "videoinfo"], props[:2])
        self.assertIn("mediatype", calls[0]["iiprop"])
        self.assertEqual(OGG_MIME, saved["commons"]["mime"])
        self.assertEqual("VIDEO", saved["commons"]["mediatype"])
        self.assertEqual(OGG_FILE, saved["media_url"])
        self.assertEqual("video", saved["media"]["kind"])
        self.assertIsNone(saved["media"]["duration_s"])
        self.assertEqual("Public domain", saved["rights"]["license_name"])
        self.assertEqual("unknown", saved["rights"]["status"])
        self.assertEqual("pending", saved["approval"]["status"])
        self.assertNotIn("videoinfo", [row.get("prop") for row in calls if row.get("titles") == "File:Audio.ogg"])

    def test_refresh_keeps_ogg_video_and_refuses_ogg_audio(self):
        refreshed_url = "https://upload.wikimedia.org/wikipedia/commons/fixture-refreshed.ogv"
        calls = []

        def transport(url, params=None, headers=None, cache_ttl=0):
            calls.append(params or {})
            if (params or {}).get("prop") == "videoinfo":
                return {
                    "query": {
                        "pages": {
                            OGG_PAGE: {
                                "videoinfo": [
                                    {
                                        "derivatives": [
                                            {
                                                "type": "video/webm",
                                                "src": "https://upload.wikimedia.org/wikipedia/commons/transcoded/fixture.480p.webm",
                                                "transcodekey": "480p.webm",
                                            }
                                        ],
                                        "timedtext": [
                                            {
                                                "src": "https://commons.wikimedia.org/w/api.php?title=File:Fixture.ogv&lang=en",
                                                "srclang": "en",
                                                "kind": "subtitles",
                                                "type": "text/vtt",
                                            }
                                        ],
                                    }
                                ]
                            }
                        }
                    }
                }
            if (params or {}).get("titles"):
                return ogg_page("VIDEO")
            return ogg_page("VIDEO", refreshed_url)

        with tempfile.TemporaryDirectory() as tmp, patch.object(providers, "get_json", side_effect=transport):
            project = Path(tmp)
            item = call(project, "resolve", "--url", "https://commons.wikimedia.org/wiki/File:Fixture.ogv")
            saved = Ledger(project).get(item["id"])
            refreshed = providers.refresh(saved)
            with (
                patch.object(providers, "get_json", return_value=ogg_page("AUDIO", pageid=OGG_PAGE)),
                self.assertRaises(ProviderError),
            ):
                providers.refresh(saved)
        self.assertEqual(refreshed_url, refreshed["media_url"])
        self.assertEqual(OGG_MIME, refreshed["commons"]["mime"])
        self.assertEqual("VIDEO", refreshed["commons"]["mediatype"])
        self.assertEqual("video", refreshed["media"]["kind"])
        self.assertEqual(
            {"role": "original", "url": refreshed_url, "mime": OGG_MIME, "width": 352, "height": 264},
            refreshed["commons"]["representations"][0],
        )
        self.assertEqual("480p.webm", refreshed["commons"]["representations"][1]["transcodekey"])
        self.assertEqual("en", refreshed["commons"]["timed_text"][0]["lang"])
        self.assertIn("mediatype", calls[2]["iiprop"])
        self.assertNotEqual(refreshed["media_url"], refreshed["commons"]["representations"][1]["url"])


@skip_unless_ffmpeg
class ExistingCatalogPreview(unittest.TestCase):
    def test_commons_image_preview_reaches_storyboard_and_stops_before_fetch(self):
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp)
            image = project / "still.jpg"
            synth_image(image, size="64x64")

            def save_image(url, target, max_bytes=None):
                self.assertEqual(COMMONS_FILE, url)
                shutil.copyfile(image, target)
                return target

            with (
                patch.object(providers, "get_json", return_value=commons_page()),
                patch("getbrolls.http.download", side_effect=save_image),
            ):
                found = call(
                    project,
                    "search",
                    "--provider",
                    "commons",
                    "--media",
                    "image",
                    "--query",
                    "arquivo",
                    "--shot",
                    "still",
                )
                ident = found["items"][0]["id"]
                with self.assertRaises(OperationError) as interval:
                    call(project, "preview", "--candidate", ident, "--start", "1", "--end", "2")
                preview = call(project, "preview", "--candidate", ident, "--narration", NARRATION)
            self.assertIn("Imagem estática", str(interval.exception))
            stored = assert_decoded_still(self, project, preview, ident, COMMONS_FILE)
            self.assertEqual("File:Fixture.jpg", stored["title"])
            self.assertEqual(COMMONS_FILE, stored["commons"]["representations"][0]["url"])
            html = Path(call(project, "review", "--ready-only")["review"]).read_text(encoding="utf-8")
            self.assertIn(NARRATION, html)
            self.assertIn("Script narration", html)
            with self.assertRaises(OperationError) as fetch:
                call(project, "fetch", "--candidate", ident)
            self.assertIn("Aprovação humana ausente", str(fetch.exception))
            self.assertEqual([], list((project / "brolls" / "clips").glob("*")))

    def test_pexels_video_preview_reaches_storyboard_and_stops_before_fetch(self):
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp)
            video = project / "clip.mp4"
            synth_video(video, size="160x90", duration=6)
            answers = [{"videos": [pexels_row()]}, pexels_row()]

            def save_video(url, target, max_bytes=None):
                self.assertEqual("https://videos.pexels.com/hd.mp4", url)
                shutil.copyfile(video, target)
                return target

            with (
                patch.dict(os.environ, {"PEXELS_API_KEY": "fixture-key"}),
                patch.object(providers, "get_json", side_effect=answers),
                patch("getbrolls.http.download", side_effect=save_video),
            ):
                found = call(project, "search", "--provider", "pexels", "--query", "glass", "--shot", "bank")
                ident = found["items"][0]["id"]
                self.assertIsNone(found["items"][0]["segment"]["start_s"])
                preview = call(
                    project,
                    "preview",
                    "--candidate",
                    ident,
                    "--start",
                    "0",
                    "--end",
                    "2",
                    "--narration",
                    NARRATION,
                )
            self.assertEqual(11, found["items"][0]["media"]["duration_s"])
            self.assertEqual((0.0, 2.0), (preview["segment"]["start_s"], preview["segment"]["end_s"]))
            self.assertEqual((160, 90), (preview["media"]["width"], preview["media"]["height"]))
            self.assertTrue(Path(preview["files"]["contact_sheet"]).is_file())
            self.assertEqual(("pending", "unknown"), (preview["approval"]["status"], preview["rights"]["status"]))
            self.assertNotIn("fixture-key", json.dumps({"id": ident, "url": preview["media_url"]}))
            html = Path(call(project, "review", "--ready-only")["review"]).read_text(encoding="utf-8")
            self.assertIn(NARRATION, html)
            with self.assertRaises(OperationError) as fetch:
                call(project, "fetch", "--candidate", ident)
            self.assertIn("Aprovação humana ausente", str(fetch.exception))
            stored = Ledger(project).get(ident)
            self.assertEqual("pending", stored["approval"]["status"])
            self.assertNotEqual("permitted", stored["rights"]["status"])

    def test_nasa_image_preview_decodes_the_still_without_an_interval(self):
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp)
            image = project / "still.jpg"
            synth_image(image, size="64x64")
            with nasa_api(project, image=image.read_bytes()) as (transport, cache):
                found = call(
                    project,
                    "search",
                    "--provider",
                    "nasa",
                    "--media",
                    "image",
                    "--query",
                    "apollo still",
                    "--shot",
                    "moon",
                )
                ident = found["items"][0]["id"]
                self.assertEqual(NASA_MEDIUM, found["items"][0]["media_url"])
                self.assertEqual(
                    ["https://images-api.nasa.gov/asset/" + quote(NASA_ID, safe="")],
                    asset_requests(transport),
                )
                with self.assertRaises(OperationError) as interval:
                    call(project, "preview", "--candidate", ident, "--start", "1", "--end", "2")
                self.assertEqual(
                    ["https://images-api.nasa.gov/asset/" + quote(NASA_ID, safe="")],
                    asset_requests(transport),
                )
                preview = call(project, "preview", "--candidate", ident, "--narration", NARRATION)
                self.assertEqual(
                    ["https://images-api.nasa.gov/asset/" + quote(NASA_ID, safe="")],
                    asset_requests(transport),
                )
                self.assertIn(NASA_MEDIUM, transport.urls)
                self.assertEqual([], [url for url in transport.urls if " " in url])
                self.assertIn(NASA_MEDIUM_SCRUBBED, cached_bodies(cache))
            self.assertIn("Imagem estática", str(interval.exception))
            stored = assert_decoded_still(self, project, preview, ident, NASA_MEDIUM)
            self.assertEqual(f"nasa:{NASA_ID}:shot:moon", ident)
            self.assertEqual(NASA_DETAILS, stored["source_url"])
            self.assertEqual("Example/Archive", stored["creator"]["name"])
            self.assertEqual(NASA_ID, stored["nasa"]["nasa_id"])
            self.assertEqual("JPL", stored["nasa"]["center"])
            self.assertEqual(NASA_PREVIEW, stored["preview"]["poster_url"])
            self.assertNotEqual(NASA_PREVIEW, stored["media_url"])
            self.assertNotIn(NASA_DESCRIPTION, " ".join(stored["rights"]["evidence"]))
            self.assertNotIn("token=secret", json.dumps(stored))
            html = Path(call(project, "review", "--ready-only")["review"]).read_text(encoding="utf-8")
            self.assertIn(NARRATION, html)
            self.assertIn("Script narration", html)
            with self.assertRaises(OperationError) as fetch:
                call(project, "fetch", "--candidate", ident)
            self.assertIn("Aprovação humana ausente", str(fetch.exception))
            self.assertEqual([], list((project / "brolls" / "clips").glob("*")))

    def test_ogg_video_preview_decodes_the_synthetic_file_and_keeps_the_original_mime(self):
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp)
            video = project / "clip.mp4"
            synth_video(video, size="160x90", duration=6)

            def transport(url, params=None, headers=None, cache_ttl=0):
                if (params or {}).get("prop") == "videoinfo":
                    return {"query": {"pages": {OGG_PAGE: {"videoinfo": [{"derivatives": [], "timedtext": []}]}}}}
                return ogg_page("VIDEO")

            def save_video(url, target, max_bytes=None):
                self.assertEqual(OGG_FILE, url)
                shutil.copyfile(video, target)
                return target

            with (
                patch.object(providers, "get_json", side_effect=transport),
                patch("getbrolls.http.download", side_effect=save_video),
            ):
                item = call(project, "resolve", "--url", "https://commons.wikimedia.org/wiki/File:Fixture.ogv")
                self.assertEqual(352, item["media"]["width"])
                self.assertIsNone(item["media"]["duration_s"])
                preview = call(project, "preview", "--candidate", item["id"], "--start", "0", "--end", "1")
            stored = Ledger(project).get(item["id"])
            self.assertEqual((160, 90), (stored["media"]["width"], stored["media"]["height"]))
            self.assertEqual((0.0, 1.0), (stored["segment"]["start_s"], stored["segment"]["end_s"]))
            self.assertTrue(Path(preview["files"]["contact_sheet"]).is_file())
            self.assertEqual(OGG_MIME, stored["commons"]["mime"])
            self.assertEqual("VIDEO", stored["commons"]["mediatype"])
            self.assertEqual(OGG_FILE, stored["media_url"])
            self.assertEqual("unknown", stored["rights"]["status"])
            self.assertEqual("pending", stored["approval"]["status"])
            self.assertNotEqual("permitted", stored["rights"]["status"])
