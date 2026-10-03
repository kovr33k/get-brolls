"""Public Archive.org item/file discovery; no collection-wide rights assumptions."""

import hashlib
import re
import tempfile
from pathlib import Path, PurePosixPath
from urllib.parse import quote, unquote, urlsplit

from .http import ProviderError, get_json, public_url
from .models import candidate
from .runtime import record_warning

VIDEO = {".mp4", ".webm", ".mov", ".mkv", ".avi", ".mpg", ".mpeg", ".m4v", ".ogv"}
IMAGE = {".jpg", ".jpeg", ".png", ".tif", ".tiff"}
CAPTIONS = {".vtt", ".srt"}


def metadata(identifier):
    if not isinstance(identifier, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,99}", identifier):
        raise ProviderError("Invalid Archive.org item identifier.")
    data = get_json("https://archive.org/metadata/" + quote(identifier, safe=""), cache_ttl=3600)
    if (
        not isinstance(data, dict)
        or not isinstance(data.get("files"), list)
        or not isinstance(data.get("metadata", {}), dict)
    ):
        raise ProviderError("Archive.org item has no accessible file listing.")
    return data


def _number(value):
    try:
        result = float(value)
        return result if 0 <= result < float("inf") else None
    except (ValueError, TypeError):
        return None


def _text(value):
    return "; ".join(str(v) for v in value) if isinstance(value, list) else str(value) if value is not None else None


def _file_url(identifier, name, data):
    canonical = "https://archive.org/download/" + quote(identifier, safe="") + "/" + quote(name, safe="/")
    # The metadata-supplied storage host avoids download-page redirects. The
    # shared transport still validates DNS/TLS and refuses redirects/private IPs.
    host, directory = data.get("d1"), data.get("dir")
    if (
        isinstance(host, str)
        and re.fullmatch(r"[A-Za-z0-9.-]+\.archive\.org", host)
        and isinstance(directory, str)
        and directory.startswith("/")
        and directory.endswith("/items/" + identifier)
        and ".." not in directory.split("/")
    ):
        return public_url("https://" + host + quote(directory, safe="/") + "/" + quote(name, safe="/"))
    return canonical


def _safe_name(name):
    return (
        isinstance(name, str)
        and bool(name)
        and "\\" not in name
        and ".." not in name.split("/")
        and not name.startswith("/")
    )


def _kind(row):
    name = row.get("name", "")
    if not _safe_name(name):
        return None
    if "thumb" in str(row.get("format", "")).lower() or name.startswith("__ia_"):
        return None
    suffix = PurePosixPath(name).suffix.lower()
    return "video" if suffix in VIDEO else "image" if suffix in IMAGE else None


def files(identifier, data, media="any"):
    """One candidate per original asset; derivatives remain explicit representations."""
    groups = {}
    for row in data["files"]:
        if not isinstance(row, dict):
            continue
        kind = _kind(row)
        if kind is None or media not in ("any", kind):
            continue
        original = row.get("original") or row["name"]
        if not _safe_name(original):
            continue
        groups.setdefault((original, kind), []).append(row)
    return [_candidate(identifier, original, rows, data) for (original, _), rows in groups.items()]


def _restricted(data, row):
    return any(
        str(v).lower() in ("true", "1")
        for v in (data.get("is_dark"), (data.get("metadata") or {}).get("access-restricted-item"), row.get("private"))
    )


def _candidate(identifier, original, rows, data, selected=None):
    # Prefer real source resolution, then the original when dimensions are unknown.
    ranked = sorted(
        rows,
        key=lambda r: (
            _number(r.get("height")) or 0,
            r.get("source") == "original",
            _number(r.get("size")) or 0,
        ),
        reverse=True,
    )
    row = selected or next((r for r in ranked if not _restricted(data, r)), ranked[0])
    meta = data.get("metadata") or {}
    ident = identifier + ":" + hashlib.sha256((original + "\0" + row["name"]).encode()).hexdigest()[:16]
    item = candidate(
        "archive",
        ident,
        (_text(meta.get("title")) or identifier) + " · " + original,
        "https://archive.org/details/" + quote(identifier, safe=""),
    )
    item["archive"] = {
        "item_id": identifier,
        "asset_file": original,
        "selected_file": row["name"],
        "source_date": _text(meta.get("date")),
        "collection": meta.get("collection"),
        "description": _text(meta.get("description")),
        "representations": [
            {
                "file": r["name"],
                "source": r.get("source"),
                "original": r.get("original"),
                "format": r.get("format"),
                "width": _number(r.get("width")),
                "height": _number(r.get("height")),
                "duration_s": _number(r.get("length")),
                "size": _number(r.get("size")),
                "sha1": r.get("sha1"),
                "md5": r.get("md5"),
                "restricted": _restricted(data, r),
                "url": _file_url(identifier, r["name"], data),
            }
            for r in rows
        ],
        "captions": [
            {"file": r["name"], "url": _file_url(identifier, r["name"], data)}
            for r in data["files"]
            if isinstance(r, dict)
            and _safe_name(r.get("name"))
            and PurePosixPath(r["name"]).suffix.lower() in CAPTIONS
            and (r.get("original") == original or PurePosixPath(r["name"]).stem == PurePosixPath(original).stem)
            and not _restricted(data, r)
        ],
    }
    kind = _kind(row)
    item["asset_type"] = kind
    item["media"].update(
        kind=kind,
        width=_number(row.get("width")),
        height=_number(row.get("height")),
        duration_s=_number(row.get("length")),
    )
    item["creator"]["name"] = _text(meta.get("creator"))
    item["rights"].update(
        license_name=_text(meta.get("rights")),
        license_url=public_url(_text(meta.get("licenseurl"))),
        evidence=[item["source_url"]],
        attribution=item["creator"]["name"],
    )
    restricted = _restricted(data, row)
    item["media_url"] = None if restricted else _file_url(identifier, row["name"], data)
    item["acquisition"].update(
        status="unavailable" if restricted else "available",
        method="manual" if restricted else "https",
        evidence=[item["source_url"]],
    )
    if restricted:
        item["acquisition"]["restriction"] = "Archive.org item/file requires separate access."
    return item


def search(query, limit, media="any"):
    kind = {"video": "movies", "image": "image"}.get(media, "(movies OR image)")
    data = get_json(
        "https://archive.org/advancedsearch.php",
        {
            "q": f"({query}) AND mediatype:{kind}",
            "fl[0]": "identifier",
            "rows": limit,
            "page": 1,
            "output": "json",
        },
    )
    response = data.get("response") if isinstance(data, dict) else None
    if (
        not isinstance(data, dict)
        or data.get("error")
        or not isinstance(response, dict)
        or not isinstance(response.get("docs"), list)
    ):
        raise ProviderError("Archive.org search returned an invalid response.")
    out = []
    for row in response["docs"][:limit]:
        if len(out) >= limit:
            break
        identifier = row.get("identifier") if isinstance(row, dict) else None
        if identifier:
            out.extend(files(identifier, metadata(identifier), media))
    return out[:limit]


def resolve(url, filename=None):
    parts = urlsplit(url)
    match = re.fullmatch(r"/(details|download)/([A-Za-z0-9_.-]+)(?:/(.+))?/?", parts.path)
    if parts.hostname not in ("archive.org", "www.archive.org") or not match:
        raise ProviderError("Use an Archive.org item page or a complete item/file URL.")
    identifier = match[2]
    filename = filename or (unquote(match[3]) if match[3] else None)
    data = metadata(identifier)
    candidates = files(identifier, data)
    if filename:
        for item in candidates:
            rows = [
                r
                for r in data["files"]
                if isinstance(r, dict) and r.get("name") in {rep["file"] for rep in item["archive"]["representations"]}
            ]
            selected = next((r for r in rows if r["name"] == filename), None)
            if selected:
                return _candidate(identifier, item["archive"]["asset_file"], rows, data, selected)
        raise ProviderError("Selected Archive.org file is not an available image/video asset.")
    if len(candidates) != 1:
        raise ProviderError(
            "Select an actual Archive.org file with --archive-file; item contains: "
            + ", ".join(i["archive"]["asset_file"] for i in candidates)
        )
    return candidates[0]


def refresh(item):
    selected = resolve(item["source_url"], item["archive"]["selected_file"])
    if selected["archive"]["asset_file"] != item["archive"]["asset_file"]:
        raise ProviderError("Archive.org original asset identity changed; resolve and review again.")
    return selected


def inspect_captions(item):
    """Read at most three asset-associated caption files, bounded to 2 MiB each."""
    from .http import download
    from .inspecting import parse_vtt

    result = {}
    for caption in item.get("archive", {}).get("captions", [])[:3]:
        try:
            with tempfile.TemporaryDirectory() as directory:
                target = Path(directory) / "captions.txt"
                download(caption["url"], target, max_bytes=2 * 1024 * 1024)
                text = target.read_text(encoding="utf-8-sig")
                cues = parse_vtt(text)
                if cues:
                    result[caption["file"]] = {"cues": cues, "text": text}
        except (ValueError, OSError, UnicodeError):
            record_warning(
                "ARCHIVE_CAPTIONS_UNAVAILABLE", "An Archive caption file could not be read; coverage is incomplete."
            )
    return result
