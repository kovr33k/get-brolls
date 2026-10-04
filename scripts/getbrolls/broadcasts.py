"""Bounded broadcast discovery, source-clock windows and independent access decisions."""

import copy
import hashlib
import html
import json
import math
import re
from urllib.parse import parse_qs, quote, unquote, urljoin, urlsplit

from .http import ProviderError, get_json, public_url
from .models import candidate, invalidate_approval, now, signature

NAMES = ("gdelt_tv", "ec_audiovisual", "un_webtv")
LOCALES = ("en", "fr", "es", "ar", "zh", "ru")
EC_ENDPOINTS = (
    "https://gfdwwnbuul.execute-api.eu-west-1.amazonaws.com/avsportal/avsportal",
    "https://8hwk2cyeyb.execute-api.eu-west-1.amazonaws.com/parrotfish-prod/",
)
EC_PHOTOS = "https://ec.europa.eu/avservices/repository/photo/"
EC_TYPES = ("VIDEOSHOT", "VIDEO", "PHOTO", "REPORTAGE")
MAX_RESULTS = 5
SECONDS_PER_MINUTE = 60
MIN_UN_QUERY = 2
UN_DISCLAIMER = "Automatically generated transcripts are not official records or documents of the United Nations."


def number(value):
    if isinstance(value, bool):
        return None
    try:
        result = float(value)
        return result if math.isfinite(result) and result >= 0 else None
    except (ValueError, TypeError):
        return None


def seconds(value):
    if isinstance(value, str) and ":" in value:
        parts = value.split(":")
        if len(parts) not in (2, 3) or any(number(p) is None for p in parts):
            return None
        if any(float(p) >= SECONDS_PER_MINUTE for p in parts[1:]):
            return None
        return sum(float(p) * SECONDS_PER_MINUTE**i for i, p in enumerate(reversed(parts)))
    return number(value)


def _text(value):
    return html.unescape(re.sub(r"<[^>]*>", "", str(value or ""))).strip() or None


def _translated(value):
    if isinstance(value, dict):
        return next((_text(value[k]) for k in dict.fromkeys(("EN", "INT", "FR", *value)) if value.get(k)), None)
    return _text(value)


def _url(value, base):
    return public_url(urljoin(base, value.strip())) if isinstance(value, str) and value.strip() else None


def _ec_request(params):
    for endpoint in EC_ENDPOINTS:
        try:
            data = get_json(endpoint, {"wt": "json", "index": 1, "hasMedia": 1, **params}, cache_ttl=3600)
            response = data.get("response") if isinstance(data, dict) else None
            if not isinstance(response, dict) or not isinstance(response.get("docs"), list):
                raise ProviderError("EC portal response schema is unavailable.")
            header = data.get("responseHeader", {})
            if not isinstance(header, dict) or header.get("status", 0) != 0:
                raise ProviderError("EC portal rejected the query.")
            return response["docs"], endpoint
        except ProviderError:
            continue
    raise ProviderError("EC portal endpoints failed or changed schema; access is unverified, not an empty catalog.")


def _ec_representations(raw, page_kind, page):
    media = raw.get("media_json") or {}
    if isinstance(media, str):
        try:
            media = json.loads(media)
        except ValueError:
            raise ProviderError("EC media representation schema changed.") from None
    if not isinstance(media, dict):
        raise ProviderError("EC media representation schema changed.")
    reps = []
    poster = _url(raw.get("shot_thumbnail"), page)
    language = None
    if page_kind == "photo":
        for size in ("ORIGINAL", "HIGH", "MED", "LOW", "THUMB"):
            variant = media.get(size) or {}
            url = _url(variant.get("PATH"), EC_PHOTOS) if isinstance(variant, dict) else None
            if url:
                reps.append({"file": url, "url": url, "variant": size, "kind": "image"})
        poster = next((r["url"] for r in reps if r["variant"] in ("MED", "LOW", "THUMB")), poster)
    else:
        return _ec_video_representations(media, poster, page)
    return reps, poster, language


def _ec_video_representations(media, poster, page):
    reps = []
    language = None
    for aspect in media.values():
        if not isinstance(aspect, dict):
            continue
        for lang in dict.fromkeys(("EN", "INT", "FR", *aspect)):
            variants = aspect.get(lang)
            if not isinstance(variants, dict):
                continue
            usable = []
            for variant in ("h264_1080", "h264_720", "h264_480", "HIGH", "LOW", "HLS"):
                url = _url(variants.get(variant), page)
                if url:
                    usable.append({"file": url, "url": url, "variant": variant, "kind": "video", "language": lang})
            if usable:
                reps.extend(usable)
                language = language or lang
                poster = poster or _url(variants.get("THUMB"), page)
                break
    return reps, poster, language


def _ec_row(raw, selected=None):
    if not isinstance(raw, dict):
        raise ProviderError("Invalid EC catalog record.")
    ref = raw.get("ref")
    kind = raw.get("type")
    if not isinstance(ref, str) or not re.fullmatch(r"[A-Za-z0-9_+./|-]{1,100}", ref) or kind not in EC_TYPES:
        raise ProviderError("Invalid EC record identity/type.")
    parent = raw.get("document_ref") or raw.get("doc_ref") or ref.split("+")[0].split("-INT-")[0]
    page_kind = "photo" if kind in ("PHOTO", "REPORTAGE") else "video"
    page = "https://audiovisual.ec.europa.eu/en/" + page_kind + "/" + quote(str(parent), safe="-")
    c = candidate("ec_audiovisual", ref, _translated(raw.get("titlesshot_json") or raw.get("titles_json")) or ref, page)
    reps, poster, language = _ec_representations(raw, page_kind, page)
    chosen = next((r for r in reps if r["file"] == selected), None) if selected else next(iter(reps), None)
    if selected and chosen is None:
        raise ProviderError("Selected EC representation is absent; resolve and review a new file explicitly.")
    restricted = raw.get("download_enabled") == "N" or raw.get("isDownloadable") is False
    c["catalog"] = {
        "record_id": ref,
        "parent_id": str(parent),
        "record_type": kind,
        "selected_file": chosen["file"] if chosen else None,
        "representations": reps,
        "provider_source_start": number(raw.get("timecodeIn")) if kind == "VIDEOSHOT" else None,
        "provider_shot_duration": number(raw.get("shotduration")) if kind == "VIDEOSHOT" else None,
        "description": _translated(raw.get("summaryshot_json") or raw.get("summary_json") or raw.get("legend_json")),
        "language": language,
        "copyright_holder": raw.get("copyright_holder_details"),
        "location": raw.get("location_json"),
        "production_date": raw.get("productiondate"),
        "copyrights": raw.get("copyrights_json"),
        "scope": raw.get("scope_json"),
        "cc_by": raw.get("cc_by_json"),
        "download_enabled": raw.get("download_enabled"),
        "is_downloadable": raw.get("isDownloadable"),
        "access_restricted": restricted,
        "coverage": "One bounded portal page; an unversioned client endpoint, not complete catalog coverage.",
    }
    c["media"].update(
        kind="image" if page_kind == "photo" else "video",
        duration_s=seconds(raw.get("duration")) if page_kind == "video" else None,
    )
    c["asset_type"] = c["media"]["kind"]
    c["captured_at"] = raw.get("shootstartdate") or raw.get("productiondate")
    c["creator"]["name"] = _text(raw.get("copyright_holder_details"))
    c["preview"]["poster_url"] = poster
    c["media_url"] = chosen["url"] if chosen else None
    c["rights"].update(
        license_name="Verify EC item conditions and third-party exceptions",
        license_url="https://audiovisual.ec.europa.eu/en/copyright",
        evidence=[page],
    )
    c["acquisition"].update(
        status="available" if chosen else "unavailable",
        method="yt-dlp" if chosen and chosen["variant"] == "HLS" else "https" if chosen else "manual",
        access_required=restricted,
    )
    if restricted or not chosen:
        c["acquisition"]["restriction"] = (
            "Explicit access decision required for this restricted EC item."
            if restricted
            else "No public media representation; import an authorized original."
        )
    return c


def _un_row(data, matches=None, locale="en"):
    if not isinstance(data, dict) or not isinstance(data.get("video"), dict):
        raise ProviderError("UN meeting/player metadata schema is unavailable.")
    video = data.get("video") or {}
    url = public_url(video.get("url"))
    if (
        not url
        or not re.fullmatch(r"/[a-z]{2}/asset/[a-z0-9]+/[a-z0-9]+/?", urlsplit(url).path)
        or urlsplit(url).hostname != "webtv.un.org"
    ):
        raise ProviderError("UN meeting did not supply a canonical Web TV asset page.")
    ident = urlsplit(url).path.split("/asset/")[1].rstrip("/")
    c = candidate("un_webtv", str(ident), video.get("clean_title") or video.get("title") or str(ident), url)
    c["media"].update(kind="video", duration_s=seconds(video.get("duration")))
    c["captured_at"] = video.get("date")
    c["catalog"] = {
        "record_id": str(ident),
        "kaltura_id": video.get("kaltura_id"),
        "language": locale,
        "transcript_url": public_url(data.get("url")),
        "matches": matches or [],
        "disclaimer": UN_DISCLAIMER,
        "original_request_url": "https://media.un.org/avlibrary/en/contact/request_footage",
        "description": (data.get("metadata") or {}).get("description"),
        "coverage": "Transcript meeting search covers the last 365 days; older catalog/direct assets are a separate route.",
    }
    c["acquisition"].update(
        status="available",
        method="yt-dlp",
        access_required=True,
        restriction="Explicit UN access decision required before working-media acquisition; reuse rights remain separate.",
    )
    c["rights"].update(
        license_name="Verify UN media conditions; preview is not reuse permission",
        license_url="https://media.un.org/en/about-us",
        evidence=[url],
    )
    return c


def _un_detail(url, locale):
    if not isinstance(url, str) or not public_url(url) or urlsplit(url).hostname != "transcripts.un.org":
        raise ProviderError("UN transcript reference must use its public transcript host.")
    return get_json(url.rstrip("/") + ".json", {"language": locale}, cache_ttl=3600)


def _gdelt_row(raw, filters):
    if not isinstance(raw, dict):
        raise ProviderError("GDELT clip metadata schema is unavailable.")
    url = _url(raw.get("preview_url") or raw.get("url"), "https://archive.org/")
    if not url or urlsplit(url).hostname not in ("archive.org", "www.archive.org"):
        raise ProviderError("GDELT result has no supported public broadcast viewing reference.")
    parts = urlsplit(url)
    match = re.fullmatch(r"/details/([^/]+)(?:/start/([0-9.]+)/end/([0-9.]+))?/?", parts.path)
    if not match:
        raise ProviderError("GDELT broadcast reference has an unsupported item/time shape.")
    query = parse_qs(parts.query)
    fragment = re.fullmatch(r"start/([0-9.]+)/end/([0-9.]+)", parts.fragment)
    start = number(match[2] or (fragment[1] if fragment else None) or (query.get("start") or [raw.get("start")])[0])
    end = number(match[3] or (fragment[2] if fragment else None) or (query.get("end") or [raw.get("end")])[0])
    if start is not None and (end is None or end <= start):
        end = None
    interval = {"start_s": start, "end_s": end} if start is not None else None
    ident = unquote(match[1])
    if raw.get("ia_show_id") and raw["ia_show_id"] != ident:
        raise ProviderError("GDELT archive identity does not match its viewing reference.")
    c = candidate(
        "gdelt_tv",
        ident + (":at:" + str(start) if start is not None else ""),
        _text(raw.get("show") or raw.get("title")) or ident,
        url,
    )
    c["catalog"] = {
        "record_id": ident,
        "station": raw.get("station"),
        "show": raw.get("show"),
        "broadcast_time": raw.get("show_date") or raw.get("date") or raw.get("datetime"),
        "match_time": raw.get("date"),
        "matching_text": _text(raw.get("snippet") or raw.get("text")),
        "filters": filters,
        "coverage": "Caption-based matches in the requested station/date scope; channel coverage varies. No visual-search route is implemented.",
    }
    c["locator"] = {
        "archive_url": "https://archive.org/details/" + quote(ident, safe=""),
        "source_interval": interval,
        "license_required": None,
    }
    c["media"]["kind"] = "video"
    c["preview"]["poster_url"] = _url(raw.get("preview_thumb") or raw.get("preview") or raw.get("thumbnail"), url)
    c["acquisition"].update(
        method="manual",
        restriction="Broadcast locator only. Resolve a real Archive file separately or import an authorized local original with --original-for.",
    )
    return c


def _search_ec(query, limit, media, filters):
    types = ("PHOTO", "REPORTAGE") if media == "image" else ("VIDEOSHOT", "VIDEO") if media == "video" else EC_TYPES
    selected_type = filters.get("type")
    if selected_type:
        if selected_type not in types:
            raise ProviderError("EC record type is incompatible with the requested media.")
        types = (selected_type,)
    rows = []
    for kind in types:
        raw, endpoint = _ec_request({**filters, "kwgg": query, "type": kind, "pagesize": limit - len(rows)})
        for record in raw[: limit - len(rows)]:
            c = _ec_row(record)
            c["catalog"].update(endpoint=endpoint, filters=filters)
            rows.append(c)
        if len(rows) >= limit:
            break
    return rows


def _search_un(query, limit, media, filters):  # noqa: ARG001 - common discovery signature; wrapper validates video-only requests
    locale = filters.get("locale", "en")
    if locale not in LOCALES or len(query) < MIN_UN_QUERY:
        raise ProviderError(
            "UN transcript search requires a supported locale (en/fr/es/ar/zh/ru) and at least two query characters."
        )
    params = {k: v for k, v in filters.items() if k != "locale"}
    data = get_json(
        "https://transcripts.un.org/" + locale + "/meetings.json", {**params, "q": query, "ft": 1, "page": 1}
    )
    if not isinstance(data, dict) or not isinstance(data.get("meetings"), list):
        raise ProviderError("UN transcript search returned no accessible meeting listing.")
    rows = []
    for meeting in data["meetings"][:limit]:
        page = _url(meeting.get("pageUrl"), "https://transcripts.un.org/")
        detail = _un_detail(page, locale)
        rows.append(_un_row(detail, (meeting.get("matches") or {}).get("statements"), locale))
    return rows


def _search_gdelt(query, limit, media, filters):  # noqa: ARG001 - common discovery signature; wrapper validates video-only requests
    params = dict(filters)
    station = params.pop("station", None)
    if station:
        if not re.fullmatch(r"[A-Za-z0-9_-]{1,30}", station):
            raise ProviderError("GDELT station must be an actual station code.")
        query += " station:" + station
    if not re.search(r"\bstation:", query, re.IGNORECASE):
        raise ProviderError(
            "GDELT currently requires an explicit station: operator or --catalog-filter station=CODE; no unbounded all-station search was dispatched."
        )
    data = get_json(
        "https://api.gdeltproject.org/api/v2/tv/tv",
        {**params, "query": query, "mode": "clipgallery", "format": "json", "maxrecords": limit},
    )
    if data == {}:
        return []
    clips = data.get("clips") if isinstance(data, dict) else None
    if not isinstance(clips, list):
        raise ProviderError("GDELT returned no supported clip listing; discovery/access is unverified.")
    rows = [_gdelt_row(raw, filters) for raw in clips[:limit]]
    if rows:
        try:
            details = get_json(
                "https://api.gdeltproject.org/api/v2/tv/tv",
                {"mode": "stationdetails", "format": "json"},
                cache_ttl=3600,
            )
            stations = {s["StationID"]: s for s in details["station_details"]}
            for row in rows:
                station = stations.get(row["catalog"]["station"], {})
                row["catalog"]["station_coverage"] = {"start": station.get("StartDate"), "end": station.get("EndDate")}
        except (ProviderError, KeyError, TypeError):
            for row in rows:
                row["catalog"]["station_coverage"] = {"start": None, "end": None}
    return rows


def search(name, query, limit, media, filters):
    if name != "ec_audiovisual" and media == "image":
        raise ProviderError("This broadcast route searches video references, not still images.")
    return {"ec_audiovisual": _search_ec, "un_webtv": _search_un, "gdelt_tv": _search_gdelt}[name](
        query, min(limit, MAX_RESULTS), media, filters
    )


def inspect_un(item, cache):
    from .social import probe_remote

    try:
        result = probe_remote(item["source_url"], cache=cache)
    except (ValueError, OSError):
        result = {
            "url": item["source_url"],
            "title": item["title"],
            "duration_s": item["media"].get("duration_s"),
            "chapters": [],
            "description": "",
            "tags": [],
            "subtitle_langs": [],
            "subtitle_langs_total": 0,
            "subtitles": {},
            "limitations": ["UN player metadata is unavailable; transcript timing is not acquired or decoded media."],
            "representation_status": "unverified",
        }
    try:
        transcript = transcript_probe(item)
    except (ValueError, OSError):
        transcript = {}
        result.setdefault("limitations", []).append(
            "UN transcript unavailable; older/direct assets remain a separate route."
        )
    if transcript:
        result["subtitles"] = transcript
        result["subtitle_langs"] = list(transcript)
        result["subtitle_langs_total"] = len(transcript)
    result.setdefault("limitations", []).append(UN_DISCLAIMER)
    return result


def inspect_remote(item, url, cache):
    from .social import probe_remote

    if item["provider"] == "un_webtv":
        return inspect_un(item, cache)
    if item["provider"] == "ec_audiovisual":
        return probe_remote(item["media_url"], cache=cache, source_url=url)
    return probe_remote(url, cache=cache)


def recognizes(url):
    host = urlsplit(url).hostname
    return (
        "ec_audiovisual"
        if host == "audiovisual.ec.europa.eu"
        else "un_webtv"
        if host in ("webtv.un.org", "transcripts.un.org")
        else None
    )


def resolve(url, selected=None):
    parts = urlsplit(url)
    name = recognizes(url)
    if name == "ec_audiovisual":
        match = re.fullmatch(r"/[a-z]{2}/(?:video|photo|reportage)/([^/]+)/?", parts.path)
        if not match:
            raise ProviderError("Use a complete EC video/photo record URL.")
        ref = unquote(match[1])
        rows, _ = _ec_request({"ref": ref, "pagesize": 1, "type": ",".join(EC_TYPES)})
        record = next((r for r in rows if r.get("ref") == ref), None)
        if record is None:
            raise ProviderError("EC record is unavailable; this is not proof that the material is absent.")
        return _ec_row(record, selected)
    locale = parts.path.strip("/").split("/")[0]
    if locale not in LOCALES:
        raise ProviderError("Use a supported UN transcript/Web TV locale.")
    page = "https://transcripts.un.org" + parts.path.rstrip("/").removesuffix(".json")
    try:
        return _un_row(_un_detail(page, locale), locale=locale)
    except ProviderError:
        # Older Web TV recordings need no recent transcript to retain their exact asset route.
        if parts.hostname != "webtv.un.org" or not re.fullmatch(r"/[a-z]{2}/asset/[a-z0-9]+/[a-z0-9]+/?", parts.path):
            raise
        row = _un_row(
            {
                "video": {
                    "url": url.split("?")[0],
                    "title": "UN Web TV asset",
                    "id": parts.path.split("/asset/")[1].rstrip("/"),
                }
            },
            locale=locale,
        )
        row["catalog"]["transcript_limitation"] = (
            "No accessible transcript for this direct asset; recent search coverage cannot establish absence."
        )
        return row


def refresh(item):
    if item["provider"] != "ec_audiovisual":
        return copy.deepcopy(item)
    old = item.get("catalog") or {}
    rows, endpoint = _ec_request({"ref": old.get("record_id"), "type": old.get("record_type"), "pagesize": 1})
    record = next((r for r in rows if r.get("ref") == old.get("record_id")), None)
    if record is None:
        raise ProviderError("Selected EC shot/record is unavailable; its parent was not substituted.")
    fresh = _ec_row(record, old.get("selected_file"))
    current = copy.deepcopy(item)
    if fresh["catalog"].get("selected_file") == old.get("selected_file"):
        for key in ("width", "height", "fps"):
            if item["media"].get(key) is not None:
                fresh["media"][key] = item["media"][key]
    for key in ("catalog", "media", "media_url", "source_url", "acquisition", "title", "creator", "captured_at"):
        current[key] = fresh[key]
    current["catalog"].update(endpoint=endpoint, filters=old.get("filters", {}))
    if signature(current) != signature(item):
        invalidate_approval(current)
        current["rights"]["status"] = "unknown"
    return current


def default_window(item):
    metadata = item.get("catalog") or {}
    start = metadata.get("provider_source_start")
    duration = metadata.get("provider_shot_duration")
    if item.get("provider") == "ec_audiovisual" and start is not None and duration is not None and duration > 0:
        return start, start + duration
    return None


def preview_window(item, start, end):
    window = default_window(item)
    if window:
        start = window[0] if start is None else start
        end = start + (window[1] - window[0]) if end is None else end
    return start, end


def access_context(ledger, item):
    from .brief import brief_path
    from .ledger import digest

    path = brief_path(ledger.root.parent)
    metadata = item.get("catalog") or {}
    context = [
        item["provider"],
        item["source_id"],
        item["source_url"],
        metadata.get("selected_file"),
        metadata.get("parent_id"),
        metadata.get("access_restricted"),
        metadata.get("copyrights"),
        metadata.get("scope"),
        metadata.get("copyright_holder"),
        metadata.get("cc_by"),
        metadata.get("provider_source_start"),
        item.get("shot"),
        item.get("narration"),
        digest(path) if path.is_file() else None,
    ]
    return hashlib.sha256(json.dumps(context, sort_keys=True).encode()).hexdigest()


def require_access(ledger, item):
    if not item.get("acquisition", {}).get("access_required"):
        return
    decision = item.get("access_decision") or {}
    if decision.get("signature") != access_context(ledger, item) or not decision.get("evidence"):
        raise ValueError(
            "Record an explicit access decision with access --candidate ID --by NAME --evidence TEXT for this asset and current brief before acquiring working or final media. Access is independent of reuse rights and human approval."
        )


def refresh_working_item(ledger, item):
    if item.get("provider") != "ec_audiovisual":
        return
    previous = signature(item)
    item.update(refresh(item))
    if signature(item) != previous and item["id"] in {row["id"] for row in ledger.data.get("items", [])}:
        ledger.save("source-refresh", item)


def prepare_inspection(ledger, item):
    if item.get("provider") == "gdelt_tv":
        raise ValueError(
            "GDELT is a broadcast/time locator. Inspect its separately resolved viewing original or authorized local import; no editing media is currently acquired."
        )
    if item.get("provider") == "ec_audiovisual":
        refresh_working_item(ledger, item)
        require_access(ledger, item)


def record_access(ledger, item, by, evidence):
    from .browser_results import _text as public_text

    if item["provider"] not in ("ec_audiovisual", "un_webtv") or not item.get("acquisition", {}).get("access_required"):
        raise ValueError("This item does not require a separate EC/UN access decision.")
    if not isinstance(by, str) or not by.strip() or not isinstance(evidence, str) or not evidence.strip():
        raise ValueError("Name the person who supplied the explicit access decision and its evidence.")
    item["access_decision"] = {
        "by": public_text(by, "--by"),
        "evidence": public_text(evidence, "--evidence"),
        "at": now(),
        "signature": access_context(ledger, item),
    }
    return item


def transcript_probe(item):
    metadata = item.get("catalog") or {}
    page = metadata.get("transcript_url")
    if not page:
        return {}
    data = _un_detail(page, metadata.get("language", "en"))
    transcript = data.get("transcript") or {}
    cues = []
    for statement in transcript.get("data") or []:
        for paragraph in statement.get("paragraphs") or []:
            for sentence in paragraph.get("sentences") or []:
                start, end = number(sentence.get("start")), number(sentence.get("end"))
                text = _text(sentence.get("text"))
                if start is not None and end is not None and end > start and text:
                    cues.append({"start_s": start, "end_s": end, "text": text})
    locale = transcript.get("language") or metadata.get("language", "en")
    return {locale: {"cues": cues, "automatic": True, "disclaimer": UN_DISCLAIMER}} if cues else {}
