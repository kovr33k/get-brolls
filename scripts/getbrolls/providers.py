"""Discovery adapters: yt-dlp for YouTube and official stock APIs."""

import html
import os
import re
from urllib.parse import parse_qs, quote, unquote, urlsplit

from .http import ProviderError, encoded_url, get_json, public_url
from .models import candidate

KEYS = {
    "pexels": "PEXELS_API_KEY",
    "pixabay": "PIXABAY_API_KEY",
    "dvids": "DVIDS_API_KEY",
    "europeana": "EUROPEANA_API_KEY",
    "nara": "NARA_API_KEY",
    "mapillary": "MAPILLARY_TOKEN",
}

# Guidance is inventory, never proof of an adapter or an authorized session.
PLANNED_CATALOGS: dict[str, tuple[str, tuple[str, ...]]] = {
    "x": ("Retained Grok OAuth X Search; OAuth/tool access unverified", ()),
}


def capabilities():
    from .broadcasts import NAMES as BROADCASTS
    from .catalogs import NAMES

    result = {}
    for name in (
        "youtube",
        "instagram",
        "tiktok",
        "pexels",
        "pixabay",
        "commons",
        "nasa",
        "archive",
        *NAMES,
        *BROADCASTS,
        "un_avlibrary",
        "destockd",
        "local",
    ):
        search_ok = name in ("youtube", "pexels", "pixabay", "commons", "nasa", "archive", *NAMES, *BROADCASTS)
        key = KEYS.get(name)
        result[name] = {
            "search": search_ok,
            "resolve_url": name
            in (
                "youtube",
                "instagram",
                "tiktok",
                "commons",
                "nasa",
                "archive",
                "un_avlibrary",
                "destockd",
                "ec_audiovisual",
                "un_webtv",
                *NAMES,
            ),
            "browser_search": name in ("instagram", "tiktok", "un_avlibrary", "destockd"),
            "account_library": False,
            "embed": False,
            "seek": "local" if name == "local" else "unsupported",
            "download": name not in ("un_avlibrary", "destockd", "gdelt_tv"),
            "transport": "browser-cdn-pairs / yt-dlp"
            if name == "instagram"
            else "yt-dlp"
            if name in ("youtube", "tiktok")
            else "website / observed link import / separately supplied original"
            if name in ("un_avlibrary", "destockd")
            else name,
            "configured": not key or bool(os.environ.get(key)),
            "env_key": key,
            "preview": True,
            "manual": name in ("instagram", "tiktok", "un_avlibrary", "destockd", "gdelt_tv"),
            "implementation": "supported",
            "live": "unverified",
            "live_observation": None,
            "access_verified": False,
            "media_types": ["image", "video"]
            if name in ("commons", "nasa", "archive", "local", "ec_audiovisual", *NAMES)
            else ["video"],
        }
        if name == "europeana":
            result[name]["configured"] = bool(os.environ.get("EUROPEANA_API_KEY")) and os.environ.get(
                "EUROPEANA_KEY_TYPE"
            ) in (
                "personal",
                "project",
            )
            result[name]["key_type"] = (
                os.environ.get("EUROPEANA_KEY_TYPE")
                if os.environ.get("EUROPEANA_KEY_TYPE") in ("personal", "project")
                else "unconfirmed"
            )
    result["gdelt_tv"].update(
        transport="caption search / Archive broadcast locator / linked original",
        visual_search=False,
        coverage="Actual station/date scope; station filter required by observed TV API.",
    )
    result["ec_audiovisual"].update(
        transport="bounded AV Portal client / fallback; HTTPS or HLS",
        access_decision="restricted items",
        seek="source clock",
    )
    result["un_webtv"].update(
        transport="UN Transcripts / direct older asset / yt-dlp Kaltura",
        coverage="Recent transcript search: last 365 days. Older assets: direct URL.",
        access_decision="required before media acquisition",
    )
    for name, (route, env_keys) in PLANNED_CATALOGS.items():
        result[name] = {
            "search": False,
            "resolve_url": False,
            "preview": False,
            "download": False,
            "manual": name in ("un_avlibrary", "destockd", "gdelt_tv"),
            "implementation": "planned",
            "configured": all(bool(os.environ.get(k)) for k in env_keys) if env_keys else None,
            "env_keys": list(env_keys),
            "transport": route,
            "live": "unverified",
            "live_observation": None,
            "access_verified": False,
        }
    for name, keys in (
        ("mapillary", ("MAPILLARY_TOKEN",)),
        ("telegram", ("TELEGRAM_API_ID", "TELEGRAM_API_HASH", "TELEGRAM_SESSION", "BROLL_TELEGRAM_CHANNELS")),
    ):
        result[name] = {
            "search": True,
            "resolve_url": True,
            "preview": True,
            "download": True,
            "implementation": "supported",
            "configured": all(bool(os.environ.get(k)) for k in keys),
            "env_keys": list(keys),
            "transport": "token / geographic image / private CDN refresh"
            if name == "mapillary"
            else "Telethon user session / bounded explicit public channels",
            "access_verified": False,
            "live": "unverified",
            "live_observation": None,
            "media_types": ["image"] if name == "mapillary" else ["image", "video"],
            "geographic_requirement": "bbox required; topic wording is not sent to the API"
            if name == "mapillary"
            else None,
            "session_authorization": "unverified" if name == "telegram" else None,
            "attachment_access": "unverified",
            "manual": False,
        }
    result["x"].update(
        resolve_url=True,
        manual=True,
        implementation="manual_original; oauth_unverified",
        media_types=["image", "video"],
        original_post="manual public reference",
        screenshot="separately supplied local image",
        attachment_download="unverified",
        billing_fallback=False,
    )
    result["mapillary"]["live"] = "sample_verified"
    result["mapillary"]["live_observation"] = {
        "date": "2026-10-04",
        "version": "2.13.0",
        "status": "passed_sample",
        "source_url": "https://www.mapillary.com/app/?pKey=2857466357804285",
        "selected_file": "thumb_original_url",
        "operations": ["search", "inspect", "preview", "review", "decode"],
        "width": 5660,
        "height": 2830,
        "bytes": 3149043,
        "duration_s": None,
        "visual_verdict": "unsuitable",
        "limitations": "One dated street panorama, not the requested Plaza Mayor square. No complete place coverage, current access, reuse rights or human acceptance established.",
    }
    result["archive"]["live"] = "sample_verified"
    result["archive"]["live_observation"] = {
        "date": "2026-10-03",
        "version": "2.6.0",
        "status": "passed_sample",
        "source_url": "https://archive.org/details/factory",
        "selected_file": "factory.mp4",
        "operations": ["search", "resolve_url", "inspect", "preview", "review", "decode_5s"],
        "width": 640,
        "height": 480,
        "duration_s": 783.071995,
        "limitations": "One public movie item; no rights permission, human acceptance, or editorial suitability established.",
    }
    samples = {
        "commons": ("https://commons.wikimedia.org/wiki/File:Folgers.ogv", 352, 264, 60, 4775695, "suitable"),
        "nasa": ("https://images.nasa.gov/details/PIA23645", 1280, 1266, None, 63836, "suitable"),
        "pexels": (
            "https://www.pexels.com/video/man-holding-a-cup-of-coffee-6343885/",
            720,
            1366,
            23.366667,
            1870196,
            "unsuitable",
        ),
        "pixabay": ("https://pixabay.com/videos/id-46989/", 1920, 1080, 34.538333, 12258063, "suitable"),
    }
    for name, (url, width, height, duration, size, verdict) in samples.items():
        result[name]["live"] = "sample_verified"
        result[name]["live_observation"] = {
            "date": "2026-10-04",
            "version": "2.7.0",
            "status": "passed_sample",
            "source_url": url,
            "operations": ["resolve_url"] if name in ("commons", "nasa") else ["search"],
            "preview": "passed",
            "decode": "passed",
            "bytes": size,
            "width": width,
            "height": height,
            "duration_s": duration,
            "interval_s": None if name == "nasa" else [0, 3],
            "visual_verdict": verdict,
            "limitations": (
                "One dated technical sample; not current access, catalog-wide quality, human approval, or reuse rights. "
                "The Pexels window did not show coffee preparation."
                if name == "pexels"
                else "One dated technical sample; not current access, catalog-wide quality, human approval, or reuse rights."
            ),
        }
    result["youtube"]["live_observation"] = {
        "date": "2026-10-04",
        "version": "2.7.0",
        "status": "partial_sample",
        "source_url": "https://www.youtube.com/watch?v=B_7EUmCxcvE",
        "operations": ["resolve_url", "inspect"],
        "preview": "failed_http_403",
        "decode": "unverified",
        "limitations": "One dated CDN denial; no acquired preview, visual confirmation, or permanent availability verdict.",
    }
    for name, url, width, height, duration, size in (
        ("nara", "https://catalog.archives.gov/id/115446171", 3152, 4728, None, 5070979),
        ("dvids", "https://www.dvidshub.net/video/1024892", 1920, 1080, 349.75, 132420398),
    ):
        result[name]["live"] = "sample_verified"
        result[name]["live_observation"] = {
            "date": "2026-10-04",
            "version": "2.10.0",
            "status": "passed_sample",
            "source_url": url,
            "operations": ["search", "resolve_url", "preview", "review", "decode"],
            "width": width,
            "height": height,
            "duration_s": duration,
            "bytes": size,
            "selected_object": "115446172" if name == "nara" else "DOD_112016651.mp4",
            "interval_s": None if name == "nara" else [0, 3],
            "limitations": "One dated technical sample. Viewed preview is unsuitable for a literal bridge shot; no human approval or reuse rights. Current access and complete catalog coverage remain unverified.",
        }
    result["loc"]["live_observation"] = {
        "date": "2026-10-04",
        "version": "2.9.0",
        "status": "failed_http_403",
        "operations": ["search"],
        "preview": "unverified",
        "limitations": "One bounded JSON search was denied. No original was acquired; no permanent platform availability verdict.",
    }
    for name, url, status, limit in (
        (
            "ec_audiovisual",
            "https://audiovisual.ec.europa.eu/en/video/I-294661",
            "passed_sample",
            "Shot I-294661-INT-1+002; decoded 6.36-9.36s MP4 window, 1920x1080/25fps/338.88s parent, 432162335 bytes. Viewed sign is unsuitable for literal speech. Live HLS/fallback unverified.",
        ),
        (
            "un_webtv",
            "https://webtv.un.org/en/asset/k14/k140iyou7p",
            "partial_sample",
            "English full-text transcript and actual yt-dlp/Kaltura metadata passed, 11247s. Acquisition, decoding and suitability unverified without an explicit access decision.",
        ),
        (
            "gdelt_tv",
            "https://archive.org/details/CNNW_20170926_160000_Inside_Politics#start/3561/end/3596",
            "partial_sample",
            "Caption locator and exact Archive original resolved; files restricted. CNN StationDetails range 2009-07-02 to 2024-10-10. Acquisition/decoding unverified; no visual-search capability.",
        ),
    ):
        result[name]["live"] = "sample_verified" if name == "ec_audiovisual" else "unverified"
        result[name]["live_observation"] = {
            "date": "2026-10-04",
            "version": "2.12.0",
            "status": status,
            "source_url": url,
            "limitations": limit + " One dated sample; no current access, human approval or reuse grant.",
        }
    return result


def _key(provider):
    key = os.environ.get(KEYS[provider])
    if not key:
        raise ProviderError(f"Configure {KEYS[provider]} para pesquisar em {provider}")
    return key


def _base(provider, ident, title, url):
    return candidate(provider, str(ident), title, public_url(url))


def _poster(item, url):
    item["preview"]["poster_url"] = public_url(url)


def _media(item, url, width=None, height=None, duration=None):
    item["media"].update({"width": width, "height": height, "duration_s": duration})
    item["media_url"] = public_url(url)
    if item["media_url"]:
        item["acquisition"].update(
            {
                "status": "available",
                "method": "https",
                "evidence": [item["source_url"]] if item["source_url"] else [],
            }
        )
    return item


def _license(item, name, url, creator=None):
    item["rights"].update(
        {
            "license_name": name,
            "license_url": url,
            "status": "unknown",
            "evidence": [url] if url else [],
            "attribution": creator,
        }
    )


def _text(raw):
    return html.unescape(re.sub("<[^>]+>", "", str(raw or ""))).strip()


MEDIA_CHOICES = ("image", "video", "any")
# Fontes que publicam foto e vídeo no mesmo acervo; nas outras `--media` não muda nada.
MEDIA_AWARE = (
    "nasa",
    "commons",
    "archive",
    "loc",
    "dvids",
    "europeana",
    "nara",
    "ec_audiovisual",
    "mapillary",
    "telegram",
)


def search(  # noqa: C901, PLR0913 - documented provider dispatch and recoverable session context
    provider,
    query,
    limit=8,
    media="any",
    catalog_filters=None,
    *,
    language=None,
    ledger=None,
    resume_history=False,
    search_context=None,
):
    from . import account_catalogs, broadcasts, catalogs
    from .archive import search as archive_search

    if not isinstance(limit, int) or not 1 <= limit <= 50:  # noqa: PLR2004 - matches the "entre 1 e 50" message below
        raise ProviderError("Limite deve estar entre 1 e 50")
    if not isinstance(query, str) or not query.strip() or len(query) > 500:  # noqa: PLR2004 - matches the "entre 1 e 500 caracteres" message below
        raise ProviderError("Consulta deve ter entre 1 e 500 caracteres")
    if media not in MEDIA_CHOICES:
        raise ProviderError("--media aceita image, video ou any")
    selected_filters = catalogs.filters(provider, catalog_filters, language)
    if provider == "mapillary":
        return account_catalogs.mapillary_search(query.strip(), limit, media, selected_filters)
    if provider == "telegram":
        return account_catalogs.telegram_search(
            query.strip(), limit, media, selected_filters, ledger, resume_history, search_context
        )
    if provider in broadcasts.NAMES:
        items = broadcasts.search(provider, query.strip(), limit, media, selected_filters)
        for item in items:
            item["query"] = query.strip()
        return items
    if provider in catalogs.NAMES:
        items = catalogs.search(provider, query.strip(), limit, media, selected_filters)
        for item in items:
            item["query"] = query.strip()
        return items
    fn = {
        "pexels": _pexels,
        "pixabay": _pixabay,
        "youtube": _youtube,
        "commons": _commons,
        "nasa": _nasa,
        "archive": archive_search,
    }.get(provider)
    if not fn:
        raise ProviderError("Busca indisponível nesta fonte; forneça URL ou arquivo local")
    # YouTube e os bancos só devolvem vídeo: pedir imagem ali não é erro do usuário,
    # é fonte errada — e quem escolhe a fonte é o beat, não esta função.
    items = fn(query.strip(), limit, media) if provider in MEDIA_AWARE else fn(query.strip(), limit)
    for item in items:
        item["query"] = query.strip()
        item["match"]["kind"] = "illustrative" if provider in ("pexels", "pixabay") else "literal"
    return items[:limit]


def _pick_largest(variants, cap=1920):
    """Maior variante cujo lado maior não passe de `cap`; sem isso, a maior de todas."""
    fitting = [v for v in variants if max(v.get("width") or 0, v.get("height") or 0) <= cap]
    return max(
        fitting or variants,
        key=lambda v: (v.get("width") or 0) * (v.get("height") or 0),
        default={},
    )


def _pexels(query, limit):
    data = get_json(
        "https://api.pexels.com/v1/videos/search",
        {"query": query, "per_page": limit},
        {"Authorization": _key("pexels")},
    )
    return _pexels_rows(data)


def _pexels_rows(data):
    out = []
    for row in data.get("videos", []):
        item = _base("pexels", row["id"], f"Pexels · {row['id']}", row.get("url"))
        user = row.get("user") or {}
        item["creator"] = {"name": user.get("name"), "url": public_url(user.get("url"))}
        _license(item, "Pexels License", "https://www.pexels.com/license/", user.get("name"))
        _poster(item, row.get("image"))
        files = [
            v for v in row.get("video_files", []) if v.get("file_type") == "video/mp4" and public_url(v.get("link"))
        ]
        file = _pick_largest(files)
        out.append(
            _media(
                item,
                file.get("link"),
                file.get("width"),
                file.get("height"),
                row.get("duration"),
            )
        )
    return out


def _pixabay(query, limit):
    data = get_json(
        "https://pixabay.com/api/videos/",
        {"key": _key("pixabay"), "q": query, "per_page": max(3, limit)},
        cache_ttl=86400,
    )
    return _pixabay_rows(data)


def _pixabay_rows(data):
    out = []
    for row in data.get("hits", []):
        item = _base(
            "pixabay",
            row["id"],
            row.get("tags") or f"Pixabay · {row['id']}",
            row.get("pageURL"),
        )
        item["creator"]["name"] = row.get("user")
        _license(
            item,
            "Pixabay Content License",
            "https://pixabay.com/service/license-summary/",
            row.get("user"),
        )
        variants = [v for v in row.get("videos", {}).values() if public_url(v.get("url"))]
        v = _pick_largest(variants)
        _poster(item, v.get("thumbnail"))
        out.append(_media(item, v.get("url"), v.get("width"), v.get("height"), row.get("duration")))
    return out


def _youtube(query, limit):
    from . import social

    out = []
    for row in social.search(query, limit):
        ident = row.get("id")
        if not isinstance(ident, str) or not re.fullmatch(r"[A-Za-z0-9_-]{11}", ident):
            continue
        item = resolve("https://www.youtube.com/watch?v=" + ident)
        item["title"] = row.get("title") or item["title"]
        item["creator"]["name"] = row.get("channel") or row.get("uploader")
        item["media"]["duration_s"] = row.get("duration")
        limits = social.source_limitations(row)
        if limits:
            item["limitations"] = limits
        thumbs = row.get("thumbnails") or []
        _poster(item, thumbs[-1].get("url") if thumbs else None)
        out.append(item)
    return out


# imageinfo props. `mediatype` is separate from MIME: application/ogg is VIDEO or AUDIO.
_COMMONS_IIPROP = "url|size|mime|mediatype|extmetadata"
_COMMONS_REFRESH_IIPROP = "url|size|mime|mediatype"
# DRAWING is an SVG or diagram still. AUDIO, office, text, archive, and executable stay out.
_COMMONS_KIND_BY_TYPE = {"VIDEO": "video", "BITMAP": "image", "DRAWING": "image"}


def _commons_mediatype(info):
    value = info.get("mediatype") if isinstance(info, dict) else None
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None


def _commons_kind(info):
    """Prefer MediaWiki mediatype. MIME applies only when that field is absent.

    `application/ogg` names a container, so VIDEO and AUDIO stay different files.
    A filename or a generic application type is not a kind. Office, text, audio,
    archive, and executable mediatypes stay out even when the MIME looks familiar.
    """
    if not isinstance(info, dict):
        return None
    declared = _commons_mediatype(info)
    if declared:
        return _COMMONS_KIND_BY_TYPE.get(declared.upper())
    mime = str(info.get("mime") or "")
    if mime.startswith("video/"):
        return "video"
    if mime.startswith("image/"):
        return "image"
    return None


def _commons(query, limit, media="any"):
    kinds = {"image": "bitmap", "video": "video"}.get(media)
    data = get_json(
        "https://commons.wikimedia.org/w/api.php",
        {
            "action": "query",
            "format": "json",
            "generator": "search",
            "gsrsearch": query + (f" filetype:{kinds}" if kinds else " filetype:video|bitmap"),
            "gsrnamespace": 6,
            "gsrlimit": limit,
            "prop": "imageinfo",
            "iiprop": _COMMONS_IIPROP,
        },
    )
    out = []
    for row in data.get("query", {}).get("pages", {}).values():
        info = (row.get("imageinfo") or [{}])[0]
        kind = _commons_kind(info)
        if kind is None or (media in ("image", "video") and kind != media):
            continue
        out.append(_commons_item(row, info))
    return out


def _remember_commons(item, info):
    """The selected representation is the file URL. Videoinfo starts absent."""
    mime = str(info.get("mime") or "")
    record = {
        "file_title": item.get("title"),
        "mime": mime or None,
        "representations": [
            {
                "role": "original",
                "url": public_url(info.get("url")),
                "mime": mime or None,
                "width": info.get("width"),
                "height": info.get("height"),
            }
        ],
        "videoinfo": "absent",
    }
    mediatype = _commons_mediatype(info)
    if mediatype:
        record["mediatype"] = mediatype
    item["commons"] = record
    return item


def _videoinfo_block(data):
    for page in ((data.get("query") or {}).get("pages") or {}).values():
        info = page.get("videoinfo") if isinstance(page, dict) else None
        if isinstance(info, list) and info and isinstance(info[0], dict):
            return info[0]
    return None


def _same_remote_file(left, right):
    """Same file when only the query differs. Tracking parameters are not a new file."""
    if not left or not right:
        return False
    a = urlsplit(left)
    b = urlsplit(right)
    return (
        a.scheme == b.scheme
        and (a.hostname or "").lower() == (b.hostname or "").lower()
        and unquote(a.path) == unquote(b.path)
    )


def _video_row(derivative, original_url):
    """Keep a transcode or a distinct video file. The original is already recorded."""
    if not isinstance(derivative, dict):
        return None
    kind = str(derivative.get("type") or derivative.get("mime") or "")
    url = public_url(derivative.get("src") or derivative.get("url"))
    # Image derivatives are poster frames. They are not a representation or a timestamp.
    if not url or not kind.startswith("video/") or _same_remote_file(url, original_url):
        return None
    row = {
        "url": url,
        "mime": kind,
        "width": derivative.get("width"),
        "height": derivative.get("height"),
    }
    key = derivative.get("transcodekey")
    if isinstance(key, str) and key.strip():
        row["role"] = "derivative"
        row["transcodekey"] = key.strip()
    return row


def _video_derivatives(block, original_url):
    found = []
    for derivative in block.get("derivatives") or []:
        row = _video_row(derivative, original_url)
        if row:
            found.append(row)
    return found


def _track_language(track):
    """TimedMediaHandler publishes `srclang`. `lang` and `language` are older aliases."""
    for key in ("srclang", "lang", "language"):
        value = track.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def _timed_text_row(track):
    """Keep the discovered track. Do not invent cue timings or read the caption file."""
    if not isinstance(track, dict):
        return None
    url = public_url(track.get("src") or track.get("url"))
    lang = _track_language(track)
    if not url or not lang:
        return None
    row = {"lang": lang, "url": url}
    for key in ("kind", "type", "label", "dir"):
        value = track.get(key)
        if isinstance(value, str) and value.strip():
            row[key] = value.strip()
    return row


def _timed_text(block):
    tracks = block.get("timedtext") if isinstance(block, dict) else None
    if not isinstance(tracks, list):
        return []
    found = []
    for track in tracks:
        row = _timed_text_row(track)
        if row:
            found.append(row)
    return found


def _commons_videoinfo(item):
    """Best-effort derivatives and timed text. A missing module does not drop the file."""
    title = (item.get("commons") or {}).get("file_title") or item.get("title")
    if not title:
        return item
    try:
        data = get_json(
            "https://commons.wikimedia.org/w/api.php",
            {
                "action": "query",
                "format": "json",
                "titles": title,
                "prop": "videoinfo",
                "viprop": "derivatives|timedtext",
            },
        )
    except ProviderError:
        return item
    block = _videoinfo_block(data)
    if not block:
        return item
    record = item.setdefault("commons", {})
    original = next(
        (
            row.get("url")
            for row in record.get("representations") or []
            if isinstance(row, dict) and row.get("role") == "original"
        ),
        None,
    )
    record["representations"] = list(record.get("representations") or []) + _video_derivatives(block, original)
    record["videoinfo"] = "present"
    timed = _timed_text(block)
    if timed:
        record["timed_text"] = timed
    return item


def _remember_nasa(item, meta):
    """Keep center, date and third-party authorship. Rights stay unknown."""
    third = _text(meta.get("secondary_creator")) or None
    center = _text(meta.get("center")) or None
    item["creator"]["name"] = third or center
    recorded = {
        "nasa_id": str(meta.get("nasa_id") or item["source_id"]),
        "center": center,
        "date": _text(meta.get("date_created")) or None,
        "secondary_creator": third,
    }
    description = _text(meta.get("description")) or None
    if description:
        recorded["description"] = description
    item["nasa"] = recorded
    return item


def _commons_item(row, info):
    """Um arquivo do Commons vira candidato: mesma leitura na busca e na página dele."""
    item = _base("commons", row["pageid"], row["title"], info.get("descriptionurl"))
    metadata = info.get("extmetadata", {})

    def field(key, metadata=metadata):
        return _text(metadata.get(key, {}).get("value")) or None

    item["creator"]["name"] = field("Artist")
    _license(
        item,
        field("LicenseShortName"),
        public_url(field("LicenseUrl")),
        field("Attribution") or field("Artist"),
    )
    kind = _commons_kind(info)
    if kind == "image":
        item["media"]["kind"] = "image"
        item["asset_type"] = "image"
    elif kind == "video":
        item["media"]["kind"] = "video"
    # `thumburl` can carry `time=`. It is a poster, never the file and never a cut.
    _poster(item, info.get("thumburl"))
    _media(item, info.get("url"), info.get("width"), info.get("height"))
    return _remember_commons(item, info)


def _commons_file(title):
    """`commons.wikimedia.org/wiki/File:…` vira candidato pela mesma API pública da busca.

    Recusar a página enquanto `search --provider commons` existe deixava quem já tem o
    link do arquivo sem rota nenhuma — e o Commons é onde mora a foto histórica literal.
    """
    data = get_json(
        "https://commons.wikimedia.org/w/api.php",
        {
            "action": "query",
            "format": "json",
            "titles": title,
            "prop": "imageinfo",
            "iiprop": _COMMONS_IIPROP,
        },
        cache_ttl=86400,
    )
    pages = list((data.get("query") or {}).get("pages", {}).values())
    row = pages[0] if pages else {}
    info = (row.get("imageinfo") or [{}])[0]
    if row.get("missing") is not None or not info.get("url") or not row.get("pageid"):
        raise ProviderError(f"O Commons não tem o arquivo {title!r}; confira o endereço da página.")
    if _commons_kind(info) is None:
        raise ProviderError(f"O arquivo {title!r} não é vídeo nem imagem; o Commons também guarda som e documento.")
    item = _commons_item(row, info)
    # Search stays one imageinfo response. Derivatives and timed text are per file.
    if item["media"].get("kind") == "video":
        _commons_videoinfo(item)
    return item


def _nasa(query, limit, media="any"):
    media_type = {"image": "image", "video": "video"}.get(media, "image,video")
    data = get_json(
        "https://images-api.nasa.gov/search",
        {"q": query, "media_type": media_type, "page_size": limit},
    )
    accepted = {"image": ("image",), "video": ("video",)}.get(media, ("image", "video"))
    out = []
    for row in data.get("collection", {}).get("items", []):
        if len(out) >= limit:
            # Avoid an unbounded N+1 of /asset lookups: once we have `limit` valid items,
            # further rows (even if present in the page) don't need a network round-trip.
            break
        meta = (row.get("data") or [{}])[0]
        ident = meta.get("nasa_id")
        kind = meta.get("media_type")
        if not ident or kind not in accepted:
            continue
        item = _base(
            "nasa",
            ident,
            meta.get("title") or ident,
            "https://images.nasa.gov/details/" + quote(ident, safe=""),
        )
        _remember_nasa(item, meta)
        # Sem isto o relatório da busca mostrava `media.kind: None` para todo item da NASA.
        item["media"]["kind"] = kind
        if kind == "image":
            item["asset_type"] = "image"
        _license(
            item,
            "Verificar condições NASA e autoria do item",
            "https://www.nasa.gov/nasa-brand-center/images-and-media/",
            item["creator"]["name"],
        )
        _poster(
            item,
            encoded_url(
                next(
                    (v.get("href") for v in row.get("links", []) if v.get("rel") == "preview"),
                    None,
                )
            ),
        )
        suffixes = (".mp4",) if kind == "video" else NASA_IMAGE_SUFFIXES
        urls = _nasa_asset_urls(ident, suffixes)
        out.append(_media(item, urls[0] if urls else None))
    return out


# Arquivos de imagem que o acervo da NASA publica para um mesmo item.
NASA_IMAGE_SUFFIXES = (".jpg", ".jpeg", ".png", ".tif", ".tiff")


def _nasa_asset_urls(ident, suffixes):
    """Arquivos públicos deste item, do mais completo para o mais leve."""
    data = get_json("https://images-api.nasa.gov/asset/" + quote(ident, safe=""), cache_ttl=86400)
    urls = [
        encoded_url(v["href"])
        for v in data.get("collection", {}).get("items", [])
        if public_url(v.get("href")) and urlsplit(v["href"]).path.lower().endswith(suffixes)
    ]
    urls.sort(key=lambda u: ("~orig" in u, "~medium" not in u, len(u)))
    return urls


def _nasa_details(ident):
    """`images.nasa.gov/details/<id>` vira candidato pela mesma API pública da busca.

    Recusar esta página enquanto `search --provider nasa` existe deixava o beat de
    foto estática sem rota nenhuma: a pessoa tem o link do item e não consegue usá-lo.
    """
    data = get_json("https://images-api.nasa.gov/search", {"nasa_id": ident}, cache_ttl=86400)
    rows = data.get("collection", {}).get("items", [])
    meta = (rows[0].get("data") or [{}])[0] if rows else {}
    if not meta.get("nasa_id"):
        raise ProviderError(f"O acervo da NASA não tem item com o id {ident!r}; confira o endereço da página.")
    nasa_id = str(meta["nasa_id"])
    video = meta.get("media_type") == "video"
    item = _base(
        "nasa",
        nasa_id,
        meta.get("title") or nasa_id,
        "https://images.nasa.gov/details/" + quote(nasa_id, safe=""),
    )
    _remember_nasa(item, meta)
    _license(
        item,
        "Verificar condições NASA e autoria do item",
        "https://www.nasa.gov/nasa-brand-center/images-and-media/",
        item["creator"]["name"],
    )
    _poster(
        item,
        encoded_url(next((v.get("href") for v in (rows[0].get("links") or []) if v.get("rel") == "preview"), None)),
    )
    item["media"]["kind"] = "video" if video else "image"
    if not video:
        item["asset_type"] = "image"
    urls = _nasa_asset_urls(nasa_id, (".mp4",) if video else NASA_IMAGE_SUFFIXES)
    _media(item, urls[0] if urls else None)
    item["state"] = "candidate"
    return item


def resolve(url, archive_file=None, catalog_file=None):  # noqa: C901, PLR0912, PLR0911 - existing size; one branch per recognized source host/URL shape
    if not public_url(url):
        raise ProviderError("Forneça URL pública HTTPS sem credenciais")
    p = urlsplit(url)
    host = p.hostname.lower()
    path = p.path.strip("/")
    from . import account_catalogs, broadcasts, browser_results, catalogs

    if catalog_file is not None and not (
        catalogs.recognizes(url)
        or broadcasts.recognizes(url) == "ec_audiovisual"
        or account_catalogs.recognizes(url) in account_catalogs.NAMES
    ):
        raise ProviderError("--catalog-file requires a catalog item URL with an actual file/attachment identity.")
    if archive_file is not None and host not in ("archive.org", "www.archive.org"):
        raise ProviderError("--archive-file requires an Archive.org item URL.")
    if account_catalogs.recognizes(url):
        return account_catalogs.resolve(url, catalog_file)
    if browser_results.recognizes(url):
        return browser_results.locator(url)
    if catalogs.recognizes(url):
        return catalogs.resolve(url, catalog_file)
    if broadcasts.recognizes(url):
        return broadcasts.resolve(url, catalog_file)
    if host in ("archive.org", "www.archive.org"):
        from .archive import resolve as archive_resolve

        return archive_resolve(url, archive_file)
    if host in ("youtube.com", "www.youtube.com", "m.youtube.com", "youtu.be"):
        ident = (
            path
            if host == "youtu.be"
            else (parse_qs(p.query).get("v") or [None])[0]
            if path == "watch"
            else path.split("/")[1]
            if path.startswith(("shorts/", "embed/")) and len(path.split("/")) == 2  # noqa: PLR2004 - caminho "shorts/<id>" ou "embed/<id>": exatamente 2 partes
            else None
        )
        if not ident or not re.fullmatch(r"[A-Za-z0-9_-]{11}", ident):
            raise ProviderError("URL de vídeo YouTube inválida")
        item = _base(
            "youtube",
            ident,
            "YouTube · " + ident,
            "https://www.youtube.com/watch?v=" + ident,
        )
        item["preview"].update(
            {
                "embed_url": "https://www.youtube-nocookie.com/embed/" + ident,
                "seek_mode": "native",
            }
        )
    elif host in ("instagram.com", "www.instagram.com"):
        match = re.fullmatch(r"(?:[A-Za-z0-9_.]+/)?(?:p|reel|reels|tv)/([A-Za-z0-9_-]+)", path)
        if not match:
            raise ProviderError("Forneça URL completa do post/reel Instagram")
        item = _base(
            "instagram",
            match[1],
            "Instagram · " + match[1],
            "https://www.instagram.com/" + path + "/",
        )
    elif host in ("images.nasa.gov", "www.images.nasa.gov"):
        match = re.fullmatch(r"details/(.+)", path)
        if not match:
            raise ProviderError("Forneça a URL completa do item: https://images.nasa.gov/details/<id>")
        return _nasa_details(unquote(match[1]))
    elif host in ("commons.wikimedia.org", "commons.m.wikimedia.org"):
        match = re.fullmatch(r"wiki/(File:.+)", unquote(path))
        if not match:
            raise ProviderError("Forneça a URL completa do arquivo: https://commons.wikimedia.org/wiki/File:<nome>")
        return _commons_file(match[1].replace("_", " "))
    elif host in ("tiktok.com", "www.tiktok.com", "m.tiktok.com"):
        match = re.fullmatch(r"@([A-Za-z0-9_.-]+)/video/(\d+)", path)
        if not match:
            raise ProviderError("Forneça URL completa TikTok @usuario/video/ID; links curtos não são expandidos")
        item = _base("tiktok", match[2], "TikTok · " + match[2], "https://www.tiktok.com/" + path)
    else:
        raise ProviderError(
            "Fonte de URL não suportada; use busca do banco (`search --provider ...`) ou original local"
        )
    item["state"] = "candidate"
    item["acquisition"].update({"status": "available", "method": "yt-dlp"})
    return item


def refresh(item):  # noqa: C901, PLR0911, PLR0912 - source-specific refresh contracts with explicit identity preservation
    """Refresh public stock file URLs without changing selection or approval."""
    import copy

    name = item["provider"]
    ident = str(item["source_id"])
    current = copy.deepcopy(item)
    from . import account_catalogs, broadcasts, catalogs

    if name in account_catalogs.NAMES:
        return account_catalogs.refresh(item)

    if name in broadcasts.NAMES:
        return broadcasts.refresh(item)

    if name in catalogs.NAMES:
        return catalogs.refresh(item)
    if name == "archive":
        from .archive import refresh as archive_refresh

        fresh = archive_refresh(item)
        current["media_url"] = fresh["media_url"]
        current["acquisition"] = fresh["acquisition"]
        return current
    if name == "pexels":
        if not ident.isdigit():
            raise ProviderError("ID Pexels inválido")
        row = get_json(
            "https://api.pexels.com/v1/videos/videos/" + ident,
            headers={"Authorization": _key(name)},
        )
        rows = _pexels_rows({"videos": [row]})
    elif name == "pixabay":
        if not ident.isdigit():
            raise ProviderError("ID Pixabay inválido")
        data = get_json(
            "https://pixabay.com/api/videos/",
            {"key": _key(name), "id": ident},
            cache_ttl=86400,
        )
        rows = _pixabay_rows(data)
    elif name == "nasa":
        image = (item.get("media") or {}).get("kind") == "image"
        urls = _nasa_asset_urls(ident, NASA_IMAGE_SUFFIXES if image else (".mp4",))
        if not urls:
            raise ProviderError("Arquivo do provedor não está mais disponível")
        current["media_url"] = urls[0]
        return current
    elif name == "commons":
        return _refresh_commons(current, ident)
    else:
        return current
    match = next((v for v in rows if v["source_id"] == ident), None)
    if not match or not match.get("media_url"):
        raise ProviderError("Arquivo do provedor não está mais disponível")
    return _copy_refreshed_media(current, match)


def _copy_refreshed_media(current, match):
    """Replace the file URL and its reported size. Approval and the interval stay."""
    current["media_url"] = match["media_url"]
    fresh = match.get("media") or {}
    media = current.setdefault("media", {})
    for key in ("width", "height", "duration_s"):
        if fresh.get(key) is not None:
            media[key] = fresh[key]
    return current


def _refresh_commons(current, ident):
    data = get_json(
        "https://commons.wikimedia.org/w/api.php",
        {
            "action": "query",
            "format": "json",
            "pageids": ident,
            "prop": "imageinfo",
            "iiprop": _COMMONS_REFRESH_IIPROP,
        },
    )
    page = (data.get("query") or {}).get("pages", {}).get(ident, {})
    info = (page.get("imageinfo") or [{}])[0]
    kind = _commons_kind(info)
    media_url = public_url(info.get("url")) if kind else None
    if not media_url:
        raise ProviderError("Arquivo do provedor não está mais disponível")
    if page.get("title") and not current.get("title"):
        current["title"] = page["title"]
    _remember_commons(current, info)
    if kind == "video":
        _commons_videoinfo(current)
    current["media_url"] = media_url
    media = current.setdefault("media", {})
    if kind == "image":
        media["kind"] = "image"
        current["asset_type"] = "image"
    elif kind == "video":
        media["kind"] = "video"
    if info.get("width") is not None:
        media["width"] = info["width"]
    if info.get("height") is not None:
        media["height"] = info["height"]
    return current
