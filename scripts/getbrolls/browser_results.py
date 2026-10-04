"""Agent-operated browser attempts and observed public locator data; no website API calls."""

import copy
import hashlib
import json
import math
import re
from pathlib import Path
from urllib.parse import parse_qsl, quote, unquote, urlsplit

from . import fragment_search as fragments
from . import providers
from .http import public_url
from .models import candidate, now
from .rules import allowed, format_report
from .runtime import redact

BROWSER_CATALOGS = ("instagram", "tiktok", "un_avlibrary", "destockd")
LOCATORS = ("un_avlibrary", "destockd")
REQUEST_URL = "https://media.un.org/avlibrary/en/contact/request_footage"
MAX_IMPORT_BYTES = 524288
FIELDS = {
    "url",
    "asset_id",
    "title",
    "creator",
    "account",
    "date",
    "description",
    "language",
    "preview_url",
    "poster_url",
    "request_url",
    "shotlist",
    "shotlist_url",
    "source_interval",
    "archive_url",
    "archive_file",
    "film_title",
}


def _text(value, field):
    if value is None:
        return None
    if not isinstance(value, str) or not value.strip() or len(value) > fragments.MAX_TEXT:
        raise ValueError(
            f"{field} must be nonempty public text of at most {fragments.MAX_TEXT} characters, without secrets."
        )
    public_text = value
    for match in re.finditer(r'https?://[^\s"<>]+', value):
        _url(match[0], field)
        public_text = public_text.replace(match[0], "[public URL]")
    if redact(public_text, limit=None) != public_text:
        raise ValueError(f"{field} must contain only public text without secrets.")
    return value.strip()


def _url(value, field) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str) or not value.strip() or len(value) > fragments.MAX_TEXT:
        raise ValueError(f"{field} requires a public HTTPS URL.")
    value = value.strip()
    try:
        parts = urlsplit(value)
        signed = {"expires", "policy", "key-pair-id", "oh", "oe", "__gda__"}
        if (
            not public_url(value)
            or parts.port not in (None, 443)
            or any(k.lower() in signed for k, _ in parse_qsl(parts.query))
        ):
            raise ValueError
    except ValueError:
        raise ValueError(
            f"{field} requires a public HTTPS URL without credentials or signed transport parameters."
        ) from None
    return value


def un_asset(asset_id):
    if not isinstance(asset_id, str) or not re.fullmatch(r"[a-z][a-z0-9]{4,12}", asset_id):
        raise ValueError("UN Asset ID must be the observed alphanumeric identifier, such as d3411148 or u120118c.")
    return locator("https://media.un.org/avlibrary/en/asset/" + asset_id[:4] + "/" + asset_id)


def recognizes(url):
    return urlsplit(url).hostname in ("media.un.org", "destockd.com", "www.destockd.com")


def locator(url):
    url = _url(url, "url")
    if url is None:
        raise ValueError("A complete public locator URL is required.")
    parts = urlsplit(url)
    if parts.hostname == "media.un.org":
        match = re.fullmatch(r"/avlibrary/[a-z]{2}/asset/([a-z][a-z0-9]{3})/([a-z][a-z0-9]{4,12})/?", parts.path)
        if not match:
            raise ValueError("Use the complete UN Audiovisual Library asset card URL.")
        source_id = match[2]
        if match[1] != source_id[:4]:
            raise ValueError("UN asset directory and Asset ID disagree.")
        row = candidate(
            "un_avlibrary",
            source_id,
            "UN archive asset · " + source_id,
            "https://media.un.org" + parts.path.rstrip("/"),
        )
        row["locator"] = {"asset_id": source_id, "license_required": True, "request_url": REQUEST_URL}
    elif parts.hostname in ("destockd.com", "www.destockd.com"):
        match = re.fullmatch(r"/shot/([^/]+)/([A-Za-z0-9_-]+)", parts.fragment)
        if parts.path not in ("", "/") or not match:
            raise ValueError("Use the complete Destockd #/shot/<film>/<shot> URL; timing cannot be inferred from it.")
        film_key = unquote(match[1])
        if not film_key or any(char in film_key for char in "\r\n\x00"):
            raise ValueError("Invalid Destockd film identity.")
        canonical = "https://destockd.com/#/shot/" + quote(film_key, safe="") + "/" + match[2]
        row = candidate(
            "destockd", hashlib.sha256(canonical.encode()).hexdigest()[:20], "Destockd shot · " + match[2], canonical
        )
        row["locator"] = {"film_key": film_key, "shot_id": match[2], "license_required": None}
    else:
        raise ValueError("This URL is not a supported archive locator card.")
    row["media"]["kind"] = "video"
    row["acquisition"].update(
        method="manual",
        restriction="Import a separately supplied or verified original; preview is a viewing reference.",
    )
    return row


def _observed_row(entry, catalog):
    if not isinstance(entry, dict) or set(entry) - FIELDS:
        raise ValueError("Browser results must contain only the documented public metadata fields.")
    url = _url(entry.get("url"), "url")
    if not url and catalog == "un_avlibrary":
        row = un_asset(entry.get("asset_id"))
    elif not url:
        raise ValueError("Each browser result requires its canonical post or card URL.")
    else:
        row = locator(url) if catalog in LOCATORS else providers.resolve(url)
    if row["provider"] != catalog:
        raise ValueError("A browser result must belong to its reserved catalog.")
    asset_id = _text(entry.get("asset_id"), "asset_id")
    if asset_id is not None and (catalog != "un_avlibrary" or asset_id != row["source_id"]):
        raise ValueError("Observed Asset ID must match the UN asset card.")
    texts = {
        key: _text(entry.get(key), key)
        for key in (
            "title",
            "creator",
            "account",
            "date",
            "description",
            "language",
            "film_title",
            "shotlist",
            "archive_file",
        )
    }
    if texts["title"]:
        row["title"] = texts["title"]
    row["creator"]["name"] = texts["creator"] or texts["account"]
    row["source_metadata"] = {
        key: value for key, value in texts.items() if value is not None and key not in ("title", "creator")
    }
    if catalog not in LOCATORS:
        if any(
            entry.get(key) is not None
            for key in (
                "preview_url",
                "request_url",
                "shotlist",
                "shotlist_url",
                "source_interval",
                "archive_url",
                "archive_file",
                "film_title",
            )
        ):
            raise ValueError(
                "Social imports use their existing private stream capture route, not locator media fields."
            )
    else:
        _locator_metadata(row, entry, texts)
    poster = _url(entry.get("poster_url"), "poster_url")
    if poster:
        row["preview"]["poster_url"] = poster
    return row


def _locator_metadata(row, entry, texts):
    data = row["locator"]
    data.update({key: value for key, value in texts.items() if value is not None})
    for key in ("preview_url", "request_url", "archive_url", "shotlist_url"):
        value = _url(entry.get(key), key)
        if value is not None:
            data[key] = value
    original = data.get("archive_url")
    if original and (
        row["provider"] != "destockd"
        or urlsplit(original).hostname not in ("archive.org", "www.archive.org")
        or not re.fullmatch(r"/details/[^/]+/?", urlsplit(original).path)
    ):
        raise ValueError("Destockd originals require an observed Archive.org item link.")
    interval = entry.get("source_interval")
    if interval is not None:
        if (
            not isinstance(interval, dict)
            or set(interval) != {"start_s", "end_s"}
            or any(
                type(interval.get(k)) not in (int, float) or not math.isfinite(interval[k])
                for k in ("start_s", "end_s")
            )
            or not 0 <= interval["start_s"] < interval["end_s"]
        ):
            raise ValueError("source_interval requires observed finite original times: 0 <= start_s < end_s.")
        data["source_interval"] = copy.deepcopy(interval)
    preview = data.get("preview_url")
    if preview:
        if Path(urlsplit(preview).path).suffix.lower() not in (".mp4", ".webm", ".mov", ".m4v"):
            raise ValueError("preview_url must identify an observed public media file, not a player page or blob.")
        row["media_url"] = preview
        row["acquisition"]["method"] = "https"
        data["representation_role"] = "preview"


def reserve_command(ledger, args, rules):
    _, _, fingerprint = fragments._fragment(args.project, args.shot, rules)
    plan = fragments._require_saved(ledger, args.shot, fingerprint)
    if plan["catalog"] not in BROWSER_CATALOGS:
        raise ValueError("This catalog does not use the supported browser search/import route.")
    query = _text(args.query, "--query")
    if query is None or len(query) > fragments.MAX_QUERY_CHARS:
        raise ValueError("Browser query must be at most 500 characters.")
    _text(args.language, "--language")
    if args.media == "image" and (
        "image" not in rules["asset_types"]
        or "image" not in providers.capabilities().get(plan["catalog"], {}).get("media_types", ["video"])
    ):
        raise ValueError("This browser route or project does not support image search.")
    attempt, replayed = fragments.reserve_attempt(ledger, plan, args, query, browser=True)
    return {
        "attempt": copy.deepcopy(attempt),
        "replayed": replayed,
        "dry_run": args.dry_run,
        "search_progress": fragments.progress(ledger.data, project=args.project),
        "summary": {
            "line": "Browser query reservation only. The managing agent must now perform the external search and record its actual outcome with search-import."
        },
    }


def _read_results(args):
    entries = []
    if args.outcome == "results":
        if not args.results:
            raise ValueError("A results outcome requires --results with the observed public JSON rows.")
        path = Path(args.results)
        if path.stat().st_size > MAX_IMPORT_BYTES:
            raise ValueError("Browser result import exceeds 512 KiB.")
        entries = json.loads(path.read_text(encoding="utf-8-sig"))
        if not isinstance(entries, list) or not 1 <= len(entries) <= fragments.MAX_RESULTS:
            raise ValueError(
                "Browser results must be an array of one to fifty observed rows; use empty for no results."
            )
    elif args.results:
        raise ValueError("Empty and access-failure outcomes cannot contain result rows.")
    if args.outcome == "access-failure" and args.coverage:
        raise ValueError("Access failure is not an assessed or incomplete result set.")
    return entries


def import_command(ledger, args, rules):
    _, _, fingerprint = fragments._fragment(args.project, args.shot, rules)
    plan = fragments._require_saved(ledger, args.shot, fingerprint)
    attempt = next(
        (item for item in plan["attempts"] if item.get("id") == args.attempt and item.get("route") == "browser"), None
    )
    if attempt is None:
        raise ValueError("Complete an existing reserved browser attempt for this fragment.")
    assessment = _text(args.assessment, "--assessment")
    entries = _read_results(args)
    prepared = [_observed_row(entry, attempt["catalog"]) for entry in entries]
    completion = hashlib.sha256(
        json.dumps([entries, args.outcome, assessment, args.coverage], sort_keys=True).encode()
    ).hexdigest()
    if attempt["status"] != "dispatched":
        if attempt.get("completion_hash") != completion:
            raise ValueError("This browser outcome was already saved; replay cannot rewrite its history.")
        return {
            "items": [ledger.get(ident) for ident in attempt["candidates"]],
            "replayed": True,
            "dry_run": args.dry_run,
            "search_progress": fragments.progress(ledger.data, project=args.project),
        }
    added = []
    for row in prepared:
        if not allowed(row, rules):
            continue
        row.update(shot=args.shot, query=attempt["query"], narration=plan["context"]["narration"])
        row["id"] += ":shot:" + args.shot
        row["format"] = format_report(row, rules)
        fragments._annotate_dispatch(row, plan)
        added.append(row)
    if args.dry_run:
        return {
            "items": added,
            "dry_run": True,
            "search_progress": fragments.progress(ledger.data, project=args.project),
        }
    added = [ledger.add(row) for row in added]
    status = "access_or_provider_error" if args.outcome == "access-failure" else "results" if added else "empty"
    attempt.update(
        status=status,
        candidates=list(dict.fromkeys(row["id"] for row in added)),
        assessment=assessment,
        assessed_at=now(),
        coverage=args.coverage,
        completion_hash=completion,
        returned_count=len(entries),
        excluded_count=len(entries) - len(added),
    )
    ledger.save_many("browser-search-outcome", added)
    return {
        "items": added,
        "attempt": copy.deepcopy(attempt),
        "replayed": False,
        "search_progress": fragments.progress(ledger.data, project=args.project),
        "summary": {
            "line": "Recorded observed browser results. Imported hits still require viewing, suitability confirmation, human review, and usage rights."
        },
    }


def link_original(ledger, args, row, rules):
    source = ledger.get(args.original_for)
    if source["provider"] not in LOCATORS or row["provider"] not in ("local", "archive"):
        raise ValueError("--original-for links a local supplied original or Archive.org file to a UN/Destockd locator.")
    if source["provider"] == "un_avlibrary" and row["provider"] != "local":
        raise ValueError("UN requested originals must be supplied explicitly as a local --file.")
    if args.shot and source.get("shot") and args.shot != source["shot"]:
        raise ValueError("The linked original must retain its locator's fragment.")
    data = source.get("locator") or {}
    if row["provider"] == "archive":
        if data.get("archive_url") and data["archive_url"].rstrip("/") != row["source_url"].rstrip("/"):
            raise ValueError("The Archive.org original does not match the observed source-film link.")
        if data.get("archive_file") and data["archive_file"] != row["archive"].get("selected_file"):
            raise ValueError("The selected Archive file does not match the observed source-film file.")
    if source.get("shot"):
        args.shot = source["shot"]
        fragments.attach_fragment_context(ledger, args, rules, source)
    row["narration"] = source.get("narration")
    row["source_reference"] = {
        "candidate": source["id"],
        "provider": source["provider"],
        "source_id": source["source_id"],
        "source_url": source["source_url"],
        "source_interval": copy.deepcopy(data.get("source_interval")),
        "conditions": _text(args.original_conditions, "--original-conditions"),
    }
