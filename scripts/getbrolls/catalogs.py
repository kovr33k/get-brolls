"""Bounded public catalog discovery and explicit original-file selection."""

import copy
import hashlib
import os
import re
import tempfile
from pathlib import Path, PurePosixPath
from urllib.parse import quote, unquote, urlsplit

from .http import ProviderError, get_json, public_url
from .models import candidate, invalidate_approval, signature
from .runtime import record_warning

NAMES = ("loc", "dvids", "europeana", "nara")
KEYS = {"dvids": "DVIDS_API_KEY", "europeana": "EUROPEANA_API_KEY", "nara": "NARA_API_KEY"}
FILTERS = {
    "x": {"allowed_x_handles", "excluded_x_handles", "from_date", "to_date"},
    "mapillary": {"bbox", "captured_after", "captured_before"},
    "telegram": {"channel", "from_date", "to_date"},
    "gdelt_tv": {"station", "STARTDATETIME", "ENDDATETIME", "timespan"},
    "ec_audiovisual": {"type"},
    "un_webtv": {"locale", "category", "date", "from", "to", "sort"},
    "loc": {"fa", "dates"},
    "dvids": {
        "category",
        "branch",
        "country",
        "city",
        "state",
        "unit",
        "unit_name",
        "unit_id",
        "from_date",
        "to_date",
        "from_publishdate",
        "to_publishdate",
        "from_duration",
        "to_duration",
        "hd",
    },
    "europeana": {"qf", "theme", "reusability", "media", "landingpage"},
    "nara": {
        "typeOfMaterials",
        "objectType",
        "startDate",
        "endDate",
        "creators",
        "geographicReference",
        "ancestorNaId",
        "collectionIdentifier",
        "recordGroupNumber",
        "availableOnline",
        "levelOfDescription",
    },
}
VIDEO = {".mp4", ".webm", ".mov", ".mkv", ".avi", ".mpg", ".mpeg", ".m4v", ".ogv"}
IMAGE = {".jpg", ".jpeg", ".png", ".tif", ".tiff", ".gif", ".webp", ".jp2"}
TRANSCRIPT_CHARS = 32768


def filters(name, values=None, language=None):
    result = {}
    for entry in values or []:
        key, sep, value = entry.partition("=")
        if not sep or key not in FILTERS.get(name, set()) or not value.strip() or len(value) > 500:  # noqa: PLR2004 - same bounded length as source queries
            raise ProviderError(
                f"Unsupported {name} catalog filter. Use an allowed KEY=VALUE; credentials/paging are not filters."
            )
        if key in result:
            raise ProviderError(f"Duplicate catalog filter: {key}.")
        result[key] = value.strip()
    if name in ("mapillary", "telegram"):
        from .account_catalogs import validate_filters

        validate_filters(name, result)
    if name == "x":
        from .grok_oauth import validate_filters

        validate_filters(result)
    if name == "un_webtv":
        from .broadcasts import LOCALES

        locale = language or result.get("locale", "en")
        if locale not in LOCALES or (language and result.get("locale", locale) != locale):
            raise ProviderError("UN query language must match a supported locale: en/fr/es/ar/zh/ru.")
        result["locale"] = locale
    return result


def _key(name):
    value = os.environ.get(KEYS[name])
    if not value:
        raise ProviderError(f"Configure {KEYS[name]} to access {name}.")
    if name == "europeana" and os.environ.get("EUROPEANA_KEY_TYPE") not in ("personal", "project"):
        raise ProviderError(
            "Confirm EUROPEANA_KEY_TYPE=personal (development experiments) or project (operational use) before enabling Europeana."
        )
    # DVIDS documents the secret as api_key for server requests without a Referer.
    return (os.environ.get("DVIDS_CLIENT_SECRET") or value) if name == "dvids" else value


def _text(value):
    if isinstance(value, dict):
        if value.get("logicalDate"):
            return str(value["logicalDate"])
        return _text(list(value.values()))
    if isinstance(value, list):
        return "; ".join(filter(None, (_text(v) for v in value))) or None
    return str(value) if value is not None else None


def select_file(current, fresh):
    """Apply an explicit representation choice to the same catalog original/fragment."""
    for field in ("id", "provider", "source_id", "source_url"):
        if current.get(field) != fresh.get(field):
            raise ProviderError("The selected catalog file must retain the same original identity and source page.")
    if (current.get("catalog") or {}).get("asset_id") != fresh["catalog"].get("asset_id"):
        raise ProviderError("A different catalog original requires its own candidate.")
    updated = copy.deepcopy(current)
    for key in (
        "catalog",
        "media",
        "media_url",
        "title",
        "creator",
        "captured_at",
        "asset_type",
        "acquisition",
        "format",
    ):
        if key in fresh:
            updated[key] = copy.deepcopy(fresh[key])
    if signature(updated) != signature(current):
        updated["rights"] = copy.deepcopy(fresh["rights"])
        updated["preview"] = copy.deepcopy(fresh["preview"])
        for key in ("local_path", "local_sha256", "local_start_s", "local_duration_s"):
            updated.pop(key, None)
        invalidate_approval(updated, bump_revision=True)
    return updated


def _number(value):
    try:
        number = float(value)
        return number if 0 < number < float("inf") else None
    except (ValueError, TypeError):
        return None


def _loc_url(url):
    if isinstance(url, str) and url.startswith("//"):
        url = "https:" + url
    if isinstance(url, str) and url.startswith("http://"):
        parsed = urlsplit(url)
        if parsed.hostname == "loc.gov" or (parsed.hostname or "").endswith(".loc.gov"):
            url = "https:" + url[len("http:") :]
    return public_url(url)


def _kind(url, mime=None):
    mime = (_text(mime) or "").lower()
    suffix = PurePosixPath(urlsplit(url or "").path).suffix.lower()
    if "mpegurl" in mime or suffix == ".m3u8":
        return None
    if mime.startswith("video/"):
        return "video"
    if mime.startswith("image/"):
        return "image"
    if mime and mime not in ("application/octet-stream", "binary/octet-stream"):
        return None
    return "video" if suffix in VIDEO else "image" if suffix in IMAGE else None


def _file(  # noqa: PLR0913, PLR0917 - explicit file metadata from different catalog schemas
    url, identity=None, mime=None, width=None, height=None, duration=None, size=None, restricted=False, rights=None
):
    safe = public_url(url)
    return {
        "file": str(identity or safe or ""),
        "url": safe,
        "kind": _kind(safe, mime),
        "mime_type": _text(mime),
        "width": _number(width),
        "height": _number(height),
        "duration_s": _number(duration),
        "size": _number(size),
        "restricted": bool(restricted),
        "rights": _text(rights),
    }


def _candidate(name, record_id, source_url, title, asset, representations, metadata, selected=None, kind=None):  # noqa: PLR0913, PLR0917 - explicit source fields, no extra configuration object
    usable = [r for r in representations if r["kind"] and r["url"]]
    if selected is not None:
        chosen = next((r for r in usable if selected in (r["file"], r["url"])), None)
        if not chosen:
            raise ProviderError(
                f"Selected {name} file is absent or unsupported; the original selection was not replaced."
            )
    else:
        chosen = max(
            usable,
            key=lambda r: (not r["restricted"], (r["width"] or 0) * (r["height"] or 0), r["size"] or 0),
            default=None,
        )
    identity = (
        str(record_id) if asset is None else str(record_id) + ":" + hashlib.sha256(str(asset).encode()).hexdigest()[:16]
    )
    c = candidate(name, identity, _text(title) or str(record_id), public_url(source_url))
    c["catalog"] = {
        "record_id": str(record_id),
        "asset_id": asset,
        "selected_file": chosen["file"] if chosen else None,
        "selected_rights": chosen.get("rights") if chosen else None,
        "representations": representations,
        **metadata,
    }
    c["creator"]["name"] = _text(metadata.get("creator"))
    c["captured_at"] = _text(metadata.get("source_date"))
    c["rights"].update(
        license_name=_text(metadata.get("rights")),
        license_url=public_url(_text(metadata.get("rights_url"))),
        evidence=[c["source_url"]],
        attribution=c["creator"]["name"],
    )
    c["preview"]["poster_url"] = public_url(metadata.get("poster"))
    c["media"].update(kind=chosen["kind"] if chosen else kind)
    if c["media"]["kind"]:
        c["asset_type"] = c["media"]["kind"]
    restricted = metadata.get("access_restricted") or (chosen or {}).get("restricted")
    c["media_url"] = chosen["url"] if chosen and not restricted else None
    if chosen:
        c["media"].update({k: chosen[k] for k in ("width", "height", "duration_s")})
        if chosen.get("rights"):
            c["rights"]["license_name"] = chosen["rights"]
    c["acquisition"].update(
        status="available" if c["media_url"] else "unavailable",
        method="https" if c["media_url"] else "manual",
        evidence=[c["source_url"]],
    )
    if not c["media_url"]:
        c["acquisition"]["restriction"] = (
            "Record requires separate access."
            if restricted
            else "No supported public original file; resolve the record or import an authorized institution original. Thumbnails are references."
        )
    return c


def _loc_rows(data, media="any", selected=None):  # noqa: C901 - nested item/resource/page/representation schema
    item = data.get("item") or data
    url = _loc_url(item.get("id") or item.get("url"))
    if not url:
        raise ProviderError("Library of Congress record has no canonical item URL.")
    ident = urlsplit(url).path.strip("/")
    resources = data.get("resources") or item.get("resources") or []
    if not resources and data.get("resource"):
        resources = [data["resource"]]
    meta = {
        "creator": item.get("contributor_names") or item.get("contributor"),
        "source_date": item.get("date") or item.get("created_published"),
        "collection": item.get("partof"),
        "location": item.get("location"),
        "language": item.get("language"),
        "rights": item.get("rights_advisory") or item.get("rights"),
        "access_advisory": item.get("access_advisory"),
        "access_restricted": bool(item.get("access_restricted")),
        "poster": next((_loc_url(u) for u in item.get("image_url", []) if _loc_url(u)), None),
    }
    rows = []
    for index, resource in enumerate(resources):
        asset = _loc_url(resource.get("url")) or resource.get("id") or str(index)
        files = resource.get("files") or []
        for page, page_files in enumerate(files):
            variants = page_files if isinstance(page_files, list) else [page_files]
            reps = []
            for f in variants:
                if not isinstance(f, dict):
                    continue
                u = _loc_url(f.get("url") or f.get("download"))
                reps.append(
                    _file(
                        u,
                        u,
                        f.get("mimetype"),
                        f.get("width"),
                        f.get("height"),
                        f.get("duration") or resource.get("duration"),
                        f.get("size"),
                        resource.get("download_restricted")
                        or f.get("rights_restricted")
                        or f.get("canDownload") is False,
                    )
                )
            reps = [r for r in reps if r["kind"] and media in ("any", r["kind"])]
            if media == "any" and any(r["kind"] == "video" for r in reps):
                # Frame images alongside movie encodings are posters, not a second original.
                reps = [r for r in reps if r["kind"] == "video"]
            if reps:
                captions = [
                    {"url": _loc_url(resource.get(k))}
                    for k in ("fulltext_file", "fulltext_derivative", "djvu_text_file")
                    if _loc_url(resource.get(k))
                ]
                rows.append(
                    _candidate(
                        "loc",
                        ident,
                        url,
                        item.get("title"),
                        str(asset) + ":" + str(page),
                        reps,
                        {**meta, "captions": captions},
                        selected if selected and any(selected in (r["file"], r["url"]) for r in reps) else None,
                    )
                )
    if selected:
        rows = [r for r in rows if r["catalog"]["selected_file"] == selected]
        if not rows:
            raise ProviderError("Selected Library of Congress file was not found.")
    return rows or [
        _candidate("loc", ident, url, item.get("title"), None, [], meta, kind=media if media != "any" else None)
    ]


def _dvids_row(raw, selected=None):
    ident = str(raw.get("id") or "")
    if not re.fullmatch(r"(?:video|image):[0-9]+", ident):
        raise ProviderError("Invalid DVIDS asset identity.")
    kind = ident.split(":", maxsplit=1)[0]
    reps = [
        _file(
            f.get("src"),
            f.get("src"),
            f.get("type"),
            f.get("width"),
            f.get("height"),
            raw.get("duration"),
            f.get("size"),
        )
        for f in raw.get("files", [])
    ]
    if kind == "image" and raw.get("image"):
        dimensions = raw.get("dimensions") or {}
        reps.append(_file(raw["image"], raw["image"], "image/jpeg", dimensions.get("width"), dimensions.get("height")))
    thumb = raw.get("thumbnail")
    meta = {
        "creator": [c.get("name") for c in raw.get("credit", [])]
        if isinstance(raw.get("credit"), list)
        else raw.get("credit"),
        "source_date": raw.get("date"),
        "published_at": raw.get("date_published") or raw.get("publishdate"),
        "unit": raw.get("unit_name"),
        "unit_id": raw.get("unit_id"),
        "branch": raw.get("branch"),
        "virin": raw.get("virin"),
        "location": raw.get("location") or {k: raw.get(k) for k in ("city", "state", "country")},
        "rights": raw.get("copyright"),
        "rights_url": "https://www.dvidshub.net/about/copyright",
        "poster": thumb.get("url") if isinstance(thumb, dict) else thumb,
        "description": raw.get("description") or raw.get("short_description"),
        "captions": [{"url": public_url(u)} for u in (raw.get("closed_caption_urls") or {}).values() if public_url(u)],
    }
    return _candidate(
        "dvids",
        ident,
        raw.get("url") or f"https://www.dvidshub.net/{kind}/{ident.split(':')[1]}",
        raw.get("title"),
        None,
        reps,
        meta,
        selected,
        kind,
    )


def _europeana_row(raw, selected=None):
    ident = raw.get("about") or raw.get("id")
    if not isinstance(ident, str) or not re.fullmatch(r"/[A-Za-z0-9_-]+/[^/?#]+", ident):
        raise ProviderError("Invalid Europeana record identity.")
    aggregations = raw.get("aggregations") or []
    proxies = [p for p in raw.get("proxies", []) if not p.get("europeanaProxy")]
    proxy = proxies[0] if proxies else raw
    aggregation = aggregations[0] if aggregations else raw
    shown = aggregation.get("edmIsShownBy")
    links = ([shown] if isinstance(shown, str) else shown or []) + (
        aggregation.get("hasView") or aggregation.get("edmHasView") or []
    )
    resources = {r.get("about"): r for a in aggregations for r in a.get("webResources", [])}
    reps = []
    for u in dict.fromkeys(links):
        r = resources.get(u) or {}
        reps.append(
            _file(
                u,
                u,
                r.get("ebucoreHasMimeType"),
                r.get("ebucoreWidth"),
                r.get("ebucoreHeight"),
                r.get("duration"),
                r.get("ebucoreFileByteSize"),
                rights=r.get("webResourceEdmRights") or r.get("webResourceDcRights"),
            )
        )
    usable = [r for r in reps if r["kind"] and r["url"]]
    primary = next((r["file"] for r in usable if r["url"] == shown), None)
    choice = selected or primary or (usable[0]["file"] if len(usable) == 1 else None)
    meta = {
        "creator": proxy.get("dcCreator"),
        "source_date": proxy.get("dcDate") or raw.get("year"),
        "collection": raw.get("europeanaCollectionName"),
        "location": proxy.get("dctermsSpatial") or raw.get("country"),
        "language": raw.get("language"),
        "institution": _text(aggregation.get("edmDataProvider") or raw.get("dataProvider")),
        "institution_record": _text(aggregation.get("edmIsShownAt")),
        "rights": aggregation.get("edmRights") or raw.get("rights"),
        "poster": (raw.get("edmPreview") or [None])[0]
        if isinstance(raw.get("edmPreview"), list)
        else raw.get("edmPreview"),
    }
    item = _candidate(
        "europeana",
        ident,
        "https://www.europeana.eu/item" + quote(ident, safe="/"),
        raw.get("title") or proxy.get("dcTitle"),
        choice,
        reps if choice else [],
        meta,
        choice,
        str(raw.get("type", "")).lower() if raw.get("type") in ("IMAGE", "VIDEO") else None,
    )
    if not choice and usable:
        item["catalog"].update(representations=reps, requires_file_selection=True)
        item["acquisition"]["restriction"] = "Multiple institution originals; select --catalog-file explicitly."
    return item


def _nara_rows(raw, media="any", selected=None):
    ident = str(raw.get("naId") or "")
    if not ident.isdigit():
        raise ProviderError("NARA record has no valid NAID.")
    meta = {
        "creator": [c.get("heading") for c in raw.get("creators", [])],
        "source_date": raw.get("productionDates") or raw.get("inclusiveStartDate"),
        "collection": raw.get("ancestors"),
        "location": raw.get("subjects"),
        "rights": raw.get("useRestriction"),
        "access_advisory": raw.get("accessRestriction"),
        "access_restricted": (raw.get("accessRestriction") or {}).get("status") not in (None, "Unrestricted"),
    }
    rows = []
    for obj in raw.get("digitalObjects", []):
        u = obj.get("objectUrl")
        file_id = str(obj.get("objectId") or obj.get("objectFilename") or u or "")
        rep = _file(
            u,
            file_id,
            width=obj.get("width"),
            height=obj.get("height"),
            duration=obj.get("duration"),
            size=obj.get("objectFileSize"),
        )
        if (
            rep["kind"]
            and media in ("any", rep["kind"])
            and (selected is None or selected in (file_id, u, obj.get("objectFilename")))
        ):
            rows.append(
                _candidate(
                    "nara",
                    ident,
                    "https://catalog.archives.gov/id/" + ident,
                    raw.get("title"),
                    file_id,
                    [rep],
                    {
                        **meta,
                        "object_filename": obj.get("objectFilename"),
                        "object_description": obj.get("objectDescription"),
                    },
                )
            )
    if selected and not rows:
        raise ProviderError("Selected NARA digital object was not found or is unsupported.")
    return rows or [
        _candidate("nara", ident, "https://catalog.archives.gov/id/" + ident, raw.get("title"), None, [], meta)
    ]


def _nara_data(params):
    data = get_json(
        "https://catalog.archives.gov/api/v2/records/search",
        params,
        headers={"x-api-key": _key("nara")},
        cache_ttl=3600,
    )
    if data.get("statusCode", 200) != 200:  # noqa: PLR2004 - documented successful API status
        raise ProviderError(
            f"NARA catalog request rejected (status {data.get('statusCode')}); verify NARA_API_KEY and quota."
        )
    hits = data.get("body", {}).get("hits", {}).get("hits")
    if not isinstance(hits, list):
        raise ProviderError("NARA returned no accessible catalog result listing.")
    return [h.get("_source", {}).get("record", {}) for h in hits]


def search(name, query, limit, media="any", catalog_filters=None):  # noqa: C901 - four documented catalog response shapes
    params = dict(catalog_filters or {})
    if name == "loc":
        if media != "any":
            facet = "online-format:image" if media == "image" else "online-format:video"
            params["fa"] = "|".join(filter(None, (params.get("fa"), facet)))
        data = get_json("https://www.loc.gov/search/", {**params, "q": query, "c": limit, "fo": "json"})
        if not isinstance(data.get("results"), list):
            raise ProviderError("Library of Congress returned no result listing.")
        rows = [c for r in data["results"] for c in _loc_rows(r, media)]
    elif name == "dvids":
        data = get_json(
            "https://api.dvidshub.net/search",
            {
                **params,
                "q": query,
                "max_results": limit,
                "type": "video,image" if media == "any" else media,
                "api_key": _key(name),
            },
        )
        if not isinstance(data.get("results"), list):
            raise ProviderError("DVIDS search failed; verify DVIDS_API_KEY/server secret and access.")
        rows = [_dvids_row(r) for r in data["results"] if r.get("type") in ("image", "video")]
    elif name == "europeana":
        if media != "any":
            params["qf"] = " AND ".join(filter(None, (params.get("qf"), "TYPE:" + media.upper())))
        data = get_json(
            "https://api.europeana.eu/record/v2/search.json",
            {**params, "query": query, "rows": limit, "profile": "rich", "wskey": _key(name)},
        )
        if data.get("success") is not True or not isinstance(data.get("items"), list):
            raise ProviderError("Europeana search failed; verify EUROPEANA_API_KEY, key terms and quota.")
        rows = [_europeana_row(r) for r in data["items"] if r.get("type") in ("IMAGE", "VIDEO")]
    else:
        params.setdefault("availableOnline", "true")
        if media == "video":
            params.setdefault("typeOfMaterials", "Moving Images")
        rows = [c for r in _nara_data({**params, "q": query, "limit": limit}) for c in _nara_rows(r, media)]
    for c in rows:
        c["catalog"]["coverage"] = "One bounded page; not complete catalog coverage."
        c["catalog"]["filters"] = params
    return rows[:limit]


def recognizes(url):
    host = (urlsplit(url).hostname or "").lower()
    return {
        "www.loc.gov": "loc",
        "loc.gov": "loc",
        "www.dvidshub.net": "dvids",
        "dvidshub.net": "dvids",
        "www.europeana.eu": "europeana",
        "europeana.eu": "europeana",
        "catalog.archives.gov": "nara",
    }.get(host)


def resolve(url, selected=None):
    name = recognizes(url)
    path = unquote(urlsplit(url).path).strip("/")
    if name == "loc" and re.fullmatch(r"(?:item|resource)/[^/?#]+", path):
        data = get_json("https://www.loc.gov/" + quote(path, safe="/") + "/", {"fo": "json"}, cache_ttl=3600)
        rows = _loc_rows(data, selected=selected)
    elif name == "dvids" and re.match(r"^(?:video|image)/[0-9]+(?:/|$)", path):
        bits = path.split("/")
        data = get_json(
            "https://api.dvidshub.net/asset", {"id": bits[0] + ":" + bits[1], "api_key": _key(name)}, cache_ttl=3600
        )
        if not isinstance(data.get("results"), dict):
            raise ProviderError("DVIDS asset is inaccessible or unpublished.")
        rows = [_dvids_row(data["results"], selected)]
    elif name == "europeana" and re.fullmatch(r"(?:[a-z]{2}/)?item/[A-Za-z0-9_-]+/[^/?#]+", path):
        ident = path.split("item/", 1)[1]
        data = get_json(
            "https://api.europeana.eu/record/v2/" + quote(ident, safe="/") + ".json",
            {"wskey": _key(name)},
            cache_ttl=3600,
        )
        if data.get("success") is not True or not isinstance(data.get("object"), dict):
            raise ProviderError("Europeana record is inaccessible; verify the key and record identity.")
        rows = [_europeana_row(data["object"], selected)]
    elif name == "nara" and re.fullmatch(r"id/[0-9]+", path):
        ident = path.split("/")[1]
        records = _nara_data({"naId": ident, "limit": 1})
        rows = [c for r in records if str(r.get("naId")) == ident for c in _nara_rows(r, selected=selected)]
    else:
        raise ProviderError("Invalid public catalog item URL.")
    if len(rows) != 1:
        choices = [r["catalog"].get("selected_file") for r in rows]
        raise ProviderError(
            f"Select an actual resource/digital object with --catalog-file. Available files: {choices[:20]}"
        )
    if rows[0]["catalog"].get("requires_file_selection"):
        choices = [r["file"] for r in rows[0]["catalog"]["representations"] if r["kind"]]
        raise ProviderError(f"Select an institution original with --catalog-file. Available files: {choices[:20]}")
    return rows[0]


def refresh(item):
    old = item.get("catalog") or {}
    fresh = resolve(item["source_url"], old.get("selected_file"))
    if old.get("asset_id") is not None and fresh["catalog"]["asset_id"] != old["asset_id"]:
        raise ProviderError("Catalog original identity changed; resolve and review it separately.")
    current = copy.deepcopy(item)
    for key in ("catalog", "media", "media_url", "acquisition", "creator", "captured_at", "title"):
        current[key] = fresh[key]
    for key in ("coverage", "filters"):
        if key in old:
            current["catalog"][key] = old[key]
    current["rights"].update({k: fresh["rights"].get(k) for k in ("license_name", "license_url", "attribution")})
    if item.get("catalog") and signature(current) != signature(item):
        invalidate_approval(current)
        if any(current["catalog"].get(k) != old.get(k) for k in ("rights", "selected_rights")):
            current["rights"]["status"] = "unknown"
    return current


def inspect_captions(item):
    """Reuse the existing bounded timed-caption reader; plain transcripts are references."""
    from .archive import inspect_captions as read_captions

    if item.get("provider") == "archive":
        return read_captions(item)
    captions = item.get("catalog", {}).get("captions") or []
    timed = [
        {"url": r["url"], "file": r["url"]}
        for r in captions
        if PurePosixPath(urlsplit(r["url"]).path).suffix.lower() in (".srt", ".vtt")
    ]
    return read_captions({"archive": {"captions": timed}})


def inspect_transcripts(item):
    """Read supplied plain transcripts without inventing timed cues or speech."""
    from .http import download

    result = []
    for row in (item.get("catalog", {}).get("captions") or [])[:3]:
        url = row["url"]
        if PurePosixPath(urlsplit(url).path).suffix.lower() not in (".txt", ".text"):
            continue
        try:
            with tempfile.TemporaryDirectory() as directory:
                target = Path(directory) / "transcript.txt"
                download(url, target, max_bytes=2 * 1024 * 1024)
                text = target.read_text(encoding="utf-8-sig")
            result.append(
                {"url": url, "text": text[:TRANSCRIPT_CHARS], "timed": False, "truncated": len(text) > TRANSCRIPT_CHARS}
            )
        except (ValueError, OSError, UnicodeError):
            record_warning(
                "CATALOG_TRANSCRIPT_UNAVAILABLE", "A supplied transcript could not be read; coverage is incomplete."
            )
    return result
