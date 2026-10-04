"""Geographic images, whitelisted user-session attachments, and honest X access diagnostics."""

import asyncio
import contextlib
import copy
import hashlib
import io
import json
import math
import os
import re
import sys
import tomllib
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlsplit

from .http import ProviderError, download, get_json
from .models import candidate, invalidate_approval, signature
from .runtime import record_warning

NAMES = ("mapillary", "telegram")
MAP_FIELDS = "id,geometry,captured_at,creator,sequence,width,height,thumb_original_url,thumb_2048_url"
MAX_HISTORY = 100
MAX_CHANNELS = 1000
SHORT_WAIT = 3
MAX_BYTES = 512 * 1024 * 1024
MAX_LATITUDE = 90
MAX_LONGITUDE = 180


def _date(value):
    try:
        if not re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", value):
            raise ValueError
        return datetime.fromisoformat(value).replace(tzinfo=UTC)
    except (ValueError, TypeError):
        raise ProviderError("Catalog dates require real YYYY-MM-DD values.") from None


def validate_filters(name, params):
    if name == "mapillary":
        if "bbox" not in params:
            raise ProviderError(
                "Mapillary requires a supplied geographic bbox=west,south,east,north; topic keywords cannot dispatch it."
            )
        try:
            west, south, east, north = [float(v) for v in params["bbox"].split(",")]
            if not all(math.isfinite(v) for v in (west, south, east, north)) or not (
                -MAX_LONGITUDE <= west < east <= MAX_LONGITUDE and -MAX_LATITUDE <= south < north <= MAX_LATITUDE
            ):
                raise ValueError
        except (ValueError, TypeError):
            raise ProviderError(
                "Mapillary bbox requires finite west,south,east,north coordinates; split dateline-crossing boxes."
            ) from None
        params["bbox"] = ",".join(str(v) for v in (west, south, east, north))
    if name == "telegram" and (not params.get("from_date") or not params.get("to_date")):
        raise ProviderError("Telegram history search requires explicit from_date and to_date filters.")
    for start, end in (("from_date", "to_date"), ("captured_after", "captured_before")):
        if params.get(start):
            _date(params[start])
        if params.get(end):
            _date(params[end])
        if params.get(start) and params.get(end) and _date(params[start]) > _date(params[end]):
            raise ProviderError("Catalog date range must run from earlier to later.")
    return params


def _asset(name, identity, url, title, kind, file_id, metadata, media):  # noqa: PLR0913, PLR0917 - explicit external asset fields
    item = candidate(name, identity, title or identity, url)
    item["media"].update(kind=kind, **media)
    item["asset_type"] = kind
    item["catalog"] = {"record_id": identity, "asset_id": file_id, "selected_file": file_id, **metadata}
    item["creator"]["name"] = metadata.get("creator")
    item["captured_at"] = metadata.get("source_date")
    item["acquisition"].update(
        status="available" if file_id else "unavailable",
        method=name if name == "mapillary" else "telethon",
        evidence=[url],
    )
    return item


def _map_request(identity=None, params=None):
    token = os.environ.get("MAPILLARY_TOKEN")
    if not token:
        raise ProviderError("Configure MAPILLARY_TOKEN to access geographic images.")
    data = get_json(
        "https://graph.mapillary.com/" + (identity or "images"),
        {"fields": MAP_FIELDS, **(params or {})},
        headers={"Authorization": "OAuth " + token},
        cache_ttl=0,
    )
    if not isinstance(data, dict) or data.get("error"):
        raise ProviderError("Mapillary access failed; verify the token and geographic request.")
    return data


def _map_row(raw, selected=None):
    identity = str(raw.get("id") or "")
    if not identity.isdigit():
        raise ProviderError("Mapillary result has no valid image identity.")
    representations = [name for name in ("thumb_original_url", "thumb_2048_url") if raw.get(name)]
    choice = selected or next(iter(representations), None)
    if selected and selected not in representations:
        raise ProviderError("Selected Mapillary image representation is no longer available.")
    creator = raw.get("creator") or {}
    sequence = raw.get("sequence")
    source_date = None
    if isinstance(raw.get("captured_at"), (int, float)):
        with contextlib.suppress(ValueError, OverflowError, OSError):
            source_date = datetime.fromtimestamp(raw["captured_at"] / 1000, UTC).isoformat()
    item = _asset(
        "mapillary",
        identity,
        "https://www.mapillary.com/app/?pKey=" + identity,
        "Mapillary image " + identity,
        "image",
        choice,
        {
            "sequence_id": sequence.get("id") if isinstance(sequence, dict) else sequence,
            "coordinates": (raw.get("geometry") or {}).get("coordinates"),
            "creator": creator.get("username") if isinstance(creator, dict) else None,
            "creator_id": creator.get("id") if isinstance(creator, dict) else None,
            "source_date": source_date,
            "representations": [{"file": r, "kind": "image", "mime_type": "image/jpeg"} for r in representations],
            "rights_url": "https://www.mapillary.com/terms",
            "access_verified": True,
            "coverage": "One bounded geographic page; no visual place verification or complete coverage.",
        },
        {
            "width": raw.get("width") if choice == "thumb_original_url" else None,
            "height": raw.get("height") if choice == "thumb_original_url" else None,
        },
    )
    item["rights"].update(
        license_name="Verify image terms and Mapillary attribution",
        license_url=item["catalog"]["rights_url"],
        evidence=[item["source_url"], item["catalog"]["rights_url"]],
        attribution=item["creator"]["name"],
    )
    # Signed CDN links stay in the transport response, never in candidate/review data.
    return item


def mapillary_search(query, limit, media, params):
    validate_filters("mapillary", params)
    if media == "video":
        raise ProviderError("Mapillary provides street images, not moving footage.")
    data = _map_request(params={**params, "limit": limit})
    if not isinstance(data.get("data"), list):
        raise ProviderError("Mapillary returned no geographic result listing.")
    rows = [_map_row(raw) for raw in data["data"][:limit]]
    for row in rows:
        row["catalog"].update(filters=params, geographic_query=True, topic_query_applied=False)
        row["query"] = query
    return rows


def _source_roots():
    root = Path(__file__).resolve().parents[2]
    roots = [root]
    git = root / ".git"
    if git.is_file():
        gitdir = (root / git.read_text(encoding="utf-8").strip().removeprefix("gitdir: ")).resolve()
        common = gitdir / "commondir"
        if common.is_file():
            roots.append((gitdir / common.read_text(encoding="utf-8").strip()).resolve().parent)
    return roots


def telegram_config():
    values = {
        k: os.environ.get(k, "").strip()
        for k in ("TELEGRAM_API_ID", "TELEGRAM_API_HASH", "TELEGRAM_SESSION", "BROLL_TELEGRAM_CHANNELS")
    }
    if not all(values.values()):
        raise ProviderError(
            "Configure TELEGRAM_API_ID, TELEGRAM_API_HASH, TELEGRAM_SESSION and BROLL_TELEGRAM_CHANNELS."
        )
    if (
        not values["TELEGRAM_API_ID"].isdigit()
        or int(values["TELEGRAM_API_ID"]) <= 0
        or not re.fullmatch(r"[A-Fa-f0-9]{32}", values["TELEGRAM_API_HASH"])
    ):
        raise ProviderError(
            "Telegram application ID must be positive and API hash must contain 32 hexadecimal characters."
        )
    try:
        inline = values["BROLL_TELEGRAM_CHANNELS"]
        channels = json.loads(inline) if inline.startswith("[") else [v.strip() for v in inline.split(",")]
        if not isinstance(channels, list) or not 1 <= len(channels) <= MAX_CHANNELS:
            raise ValueError
        if any(not isinstance(v, str) or not re.fullmatch(r"@?[A-Za-z][A-Za-z0-9_]{4,31}", v) for v in channels):
            raise ValueError
        channels = list(dict.fromkeys(v.removeprefix("@").lower() for v in channels))
    except (ValueError, TypeError):
        raise ProviderError(
            "BROLL_TELEGRAM_CHANNELS requires a JSON username array or comma-separated public usernames; private links/IDs and lists over 1000 entries are not allowed."
        ) from None
    reference = Path(values["TELEGRAM_SESSION"]).expanduser()
    if not reference.is_absolute():
        if ".." in reference.parts or any(not re.fullmatch(r"[A-Za-z0-9_.-]+", part) for part in reference.parts):
            raise ProviderError(
                "TELEGRAM_SESSION requires a private absolute path or a relative private session reference without parent traversal."
            )
        private_root = Path.home() / ".getbrolls"
        reference = private_root / (Path("sessions") / reference if len(reference.parts) == 1 else reference)
    if reference.suffix != ".session":
        reference = Path(str(reference) + ".session")
    reference = reference.resolve()
    if any(reference.is_relative_to(root) for root in _source_roots()):
        raise ProviderError("TELEGRAM_SESSION must remain outside the distributed repository source.")
    return int(values["TELEGRAM_API_ID"]), values["TELEGRAM_API_HASH"], reference, channels


def _client() -> Any:
    api_id, api_hash, session, _ = telegram_config()
    try:
        # Optional SDK: base quality environments intentionally omit Telegram dependencies.
        from telethon import TelegramClient  # pyright: ignore[reportMissingImports]
    except ImportError:
        raise ProviderError(
            "Telegram requires the optional Telethon dependency; install requirements-telegram.txt in the private runtime."
        ) from None
    session.parent.mkdir(parents=True, exist_ok=True)
    client = TelegramClient(
        str(session), api_id, api_hash, flood_sleep_threshold=0, request_retries=0, connection_retries=1, timeout=10
    )
    if session.exists():
        session.chmod(0o600)
    return client


async def _disconnect(client):
    try:
        await client.disconnect()
    except Exception:  # noqa: BLE001 - cleanup must not replace a sanitized failure with private RPC details
        record_warning(
            "TELEGRAM_DISCONNECT_FAILED", "Telegram connection cleanup failed; private RPC details were omitted."
        )


def _telegram_error(error):
    name = type(error).__name__
    if name in ("AuthKeyUnregisteredError", "SessionRevokedError", "AuthKeyDuplicatedError", "UserDeactivatedError"):
        return ProviderError(
            "Telegram session is expired or revoked; run telegram-login locally to authenticate again."
        )
    return ProviderError("Telegram operation could not complete (" + name + "); account/session data has been omitted.")


async def _authorized(client):
    await client.connect()
    if not await client.is_user_authorized():
        raise ProviderError(
            "Telegram session is unauthenticated or expired; run telegram-login locally, including 2FA if required."
        )
    account = await client.get_me()
    if getattr(account, "bot", False):
        raise ProviderError("Telegram discovery requires a user session, not a bot session.")


async def _channel(client, username):
    if username.lower() not in telegram_config()[3]:
        raise ProviderError("Telegram search is outside the explicit public-channel whitelist.")
    try:
        entity = await client.get_entity(username)
    except ValueError:
        raise ProviderError("Selected Telegram public channel is inaccessible.") from None
    if not getattr(entity, "broadcast", False) or (getattr(entity, "username", None) or "").lower() != username.lower():
        raise ProviderError(
            "Telegram target is not the selected public broadcast channel; private chats/groups are not searched."
        )
    return entity


def _message_row(username, message):
    file = getattr(message, "file", None)
    photo = getattr(message, "photo", None)
    document = getattr(message, "document", None)
    mime = getattr(file, "mime_type", None) or ("image/jpeg" if photo else "")
    kind = "image" if photo or mime.startswith("image/") else "video" if mime.startswith("video/") else None
    attachment = photo or document
    if not kind or not attachment or not getattr(attachment, "id", None):
        return None
    message_id = str(message.id)
    file_id = ("photo:" if photo else "document:") + str(attachment.id)
    date = message.date.isoformat() if message.date else None
    caption = (getattr(message, "raw_text", None) or "")[:32768]
    row = _asset(
        "telegram",
        username + ":" + message_id,
        "https://t.me/" + username + "/" + message_id,
        caption or "Telegram attachment " + message_id,
        kind,
        file_id,
        {
            "channel": username,
            "message_id": message_id,
            "grouped_id": str(message.grouped_id) if getattr(message, "grouped_id", None) else None,
            "creator": username,
            "source_date": date,
            "description": caption,
            "forwarded": bool(getattr(message, "fwd_from", None)),
            "original_source_url": None,
            "original_source_verified": False,
            "representations": [{"file": file_id, "kind": kind, "mime_type": mime}],
            "session_authorized": True,
            "attachment_access": "metadata_only",
            "coverage": "Bounded matching public messages in the selected period; no original-source or visual verification.",
        },
        {
            "width": getattr(file, "width", None),
            "height": getattr(file, "height", None),
            "duration_s": getattr(file, "duration", None),
            "size": getattr(file, "size", None),
        },
    )
    row["rights"].update(evidence=[row["source_url"]], attribution=username)
    return row


def _save(ledger):
    if ledger is not None:
        ledger.save("telegram-history-progress")


def _history_key(query, params, channels, context):
    normalized = " ".join(query.split()).casefold()
    return hashlib.sha256(
        json.dumps([normalized, params, sorted(channels), context], sort_keys=True).encode()
    ).hexdigest()


async def _history(client, query, limit, media, params, state, ledger):  # noqa: C901, PLR0913, PLR0917, PLR0912, PLR0915 - bounded cursor/period/rate state at the transport boundary
    scanned = 0
    waited = False
    lower, upper = _date(params["from_date"]), _date(params["to_date"]) + timedelta(days=1)
    for username, cursor in state["channels"].items():
        if cursor["done"] or len(state["rows"]) >= limit or scanned >= MAX_HISTORY:
            continue
        while True:
            try:
                entity = await _channel(client, username)
                cursor["access"] = "accessible_public_channel"
                count = 0
                allowance = MAX_HISTORY - scanned
                async for message in client.iter_messages(
                    entity, search=query, offset_id=cursor["offset_id"], offset_date=upper, limit=allowance, wait_time=0
                ):
                    count += 1
                    scanned += 1
                    if not message.date or message.date >= upper:
                        cursor["offset_id"] = message.id
                        _save(ledger)
                        continue
                    if message.date < lower:
                        cursor["done"] = True
                        _save(ledger)
                        break
                    row = _message_row(username, message)
                    if (
                        row
                        and media in ("any", row["media"]["kind"])
                        and not any(r["source_id"] == row["source_id"] for r in state["rows"])
                    ):
                        state["rows"].append(row)
                    # Save the public result and cursor together; interrupted iteration resumes after this message.
                    cursor["offset_id"] = message.id
                    state["scanned"] += 1
                    _save(ledger)
                    if len(state["rows"]) >= limit or scanned >= MAX_HISTORY:
                        break
                else:
                    cursor["done"] = count < allowance
                break
            except ProviderError:
                cursor["access"] = "inaccessible_channel"
                _save(ledger)
                record_warning(
                    "TELEGRAM_CHANNEL_INACCESSIBLE",
                    "A selected public channel is inaccessible; coverage is incomplete.",
                )
                break
            except Exception as error:  # noqa: BLE001 - RPC exception bodies can expose account/session data
                if type(error).__name__ in (
                    "UsernameInvalidError",
                    "UsernameNotOccupiedError",
                    "ChannelPrivateError",
                    "ChannelInvalidError",
                    "ChatAdminRequiredError",
                ):
                    cursor["access"] = "inaccessible_channel"
                    _save(ledger)
                    record_warning(
                        "TELEGRAM_CHANNEL_INACCESSIBLE",
                        "A selected public channel is inaccessible; coverage is incomplete.",
                    )
                    break
                seconds = getattr(error, "seconds", None)
                if type(error).__name__ != "FloodWaitError" or not isinstance(seconds, int):
                    raise _telegram_error(error) from None
                if 0 <= seconds <= SHORT_WAIT and not waited:
                    waited = True
                    await asyncio.sleep(seconds)
                    continue
                eligible = (datetime.now(UTC) + timedelta(seconds=max(1, seconds))).isoformat()
                state["next_eligible_at"] = eligible
                if ledger is not None:
                    ledger.data["telegram_access"] = {"next_eligible_at": eligible}
                _save(ledger)
                record_warning(
                    "TELEGRAM_RATE_WAIT",
                    "Telegram rate wait was recorded; resume after next_eligible_at or continue with another catalog.",
                )
                return
        _save(ledger)


def telegram_search(query, limit, media, params, ledger=None, resume=False, context=None):  # noqa: PLR0913, PLR0917 - existing CLI/query context plus resumable ledger
    validate_filters("telegram", params)
    channels = telegram_config()[3]
    if params.get("channel"):
        selected = params["channel"].removeprefix("@").lower()
        if selected not in channels:
            raise ProviderError("Telegram search is outside the explicit public-channel whitelist.")
        channels = [selected]
    access = (ledger.data.get("telegram_access") or {}) if ledger else {}
    if access.get("next_eligible_at") and datetime.fromisoformat(access["next_eligible_at"]) > datetime.now(UTC):
        raise ProviderError("Telegram rate wait is still active; next eligible access: " + access["next_eligible_at"])
    key = _history_key(query, {**params, "media": media}, channels, context)
    states = ledger.data.setdefault("telegram_history", {}) if ledger is not None else {}
    state = states.setdefault(
        key,
        {
            "query": query,
            "filters": params,
            "context": context,
            "channels": {c: {"offset_id": 0, "done": False} for c in channels},
            "rows": [],
            "scanned": 0,
        },
    )
    if (
        not isinstance(state, dict)
        or set(state.get("channels", {})) != set(channels)
        or not isinstance(state.get("rows"), list)
        or any(
            type(c.get("offset_id")) is not int or c["offset_id"] < 0 or type(c.get("done")) is not bool
            for c in state["channels"].values()
        )
    ):
        raise ProviderError("Telegram saved history cursor is invalid; preserve and restore the project state.")
    if not state.get("started") or resume:

        async def run():
            client = _client()
            try:
                await _authorized(client)
                state["session_authorized"] = True
                state["started"] = True
                state.pop("next_eligible_at", None)
                _save(ledger)
                await _history(client, query, limit, media, params, state, ledger)
            except ProviderError:
                raise
            except Exception as error:  # noqa: BLE001 - RPC exception bodies can expose account/session data
                raise _telegram_error(error) from None
            finally:
                await _disconnect(client)

        asyncio.run(asyncio.wait_for(run(), timeout=45))
    result = copy.deepcopy(state["rows"][:limit])
    for row in result:
        row["catalog"]["history_progress"] = {
            "scanned": state["scanned"],
            "complete": all(v["done"] for v in state["channels"].values()),
            "next_eligible_at": state.get("next_eligible_at"),
        }
    return result


def telegram_login():
    if not sys.stdin.isatty():
        raise ProviderError(
            "telegram-login requires a local interactive terminal; phone, code and 2FA must not be passed as command arguments."
        )

    async def run():
        import getpass

        client = _client()
        try:
            # Prompt secrets locally; never return them in JSON, diagnostics or project state.
            with contextlib.redirect_stdout(io.StringIO()):
                await client.start(
                    phone=lambda: getpass.getpass("Telegram phone: "),
                    code_callback=lambda: getpass.getpass("Telegram login code: "),
                    password=lambda: getpass.getpass("Telegram 2FA password: "),
                )
            await _authorized(client)
            return {
                "session_authorized": True,
                "scope": "Explicit public-channel whitelist only; no subscription enumeration or account-wide search.",
            }
        except ProviderError:
            raise
        except Exception as error:  # noqa: BLE001 - interactive secrets/RPC failures must stay local
            raise _telegram_error(error) from None
        finally:
            await _disconnect(client)

    return asyncio.run(run())


def recognizes(url):
    parts = urlsplit(url)
    host = (parts.hostname or "").lower().removeprefix("www.")
    return (
        "mapillary"
        if host == "mapillary.com"
        else "telegram"
        if host == "t.me"
        else "x"
        if host in ("x.com", "twitter.com")
        else None
    )


def _telegram_post(url):
    match = re.fullmatch(r"/(?:s/)?([A-Za-z][A-Za-z0-9_]{4,31})/([0-9]+)/?", urlsplit(url).path)
    if not match:
        raise ProviderError("Telegram requires a public channel/message permalink, never a private chat or invite URL.")
    return match[1].lower(), int(match[2])


async def _get_message(client, url):
    username, identity = _telegram_post(url)
    entity = await _channel(client, username)
    message = await client.get_messages(entity, ids=identity)
    if message is None:
        raise ProviderError("Selected Telegram message is inaccessible or deleted.")
    row = _message_row(username, message)
    if row is None:
        raise ProviderError("Selected Telegram message has no supported image/video attachment.")
    return row, message


def resolve(url, selected=None):
    name = recognizes(url)
    if name == "mapillary":
        identity = (parse_qs(urlsplit(url).query).get("pKey") or [None])[0]
        if not identity or not identity.isdigit():
            raise ProviderError("Mapillary requires its canonical image page with pKey=IMAGE_ID.")
        return _map_row(_map_request(identity), selected)
    if name == "telegram":

        async def run():
            client = _client()
            try:
                await _authorized(client)
                row, _ = await _get_message(client, url)
                if selected and selected != row["catalog"]["selected_file"]:
                    raise ProviderError("Selected Telegram attachment identity changed; it was not replaced.")
                return row
            except ProviderError:
                raise
            except Exception as error:  # noqa: BLE001 - RPC exception bodies can expose account/session data
                raise _telegram_error(error) from None
            finally:
                await _disconnect(client)

        return asyncio.run(asyncio.wait_for(run(), timeout=30))
    match = re.fullmatch(r"/([A-Za-z0-9_]{1,15})/status/([0-9]+)/?", urlsplit(url).path)
    if name != "x" or not match:
        raise ProviderError("X requires the canonical original account/status/post URL.")
    row = candidate("x", match[2], "X post " + match[2], "https://x.com/" + match[1] + "/status/" + match[2])
    row["creator"]["name"] = match[1]
    row["catalog"] = {
        "record_id": match[2],
        "author": match[1],
        "quote_verified": False,
        "original_post_viewed": False,
        "oauth_search": "unverified",
    }
    row["acquisition"].update(
        method="manual",
        restriction="Original-post viewing, screenshot and attached media are separate. Supply an actually viewed local original with --original-for; OAuth X Search is unverified.",
        evidence=[row["source_url"]],
    )
    return row


def refresh(item):
    fresh = resolve(item["source_url"], item.get("catalog", {}).get("selected_file"))
    if fresh["catalog"].get("asset_id") != item.get("catalog", {}).get("asset_id"):
        raise ProviderError("Selected attachment identity changed; resolve and review separately.")
    current = copy.deepcopy(item)
    for key in ("catalog", "media", "title", "creator", "captured_at", "acquisition", "rights"):
        if key == "rights":
            current[key].update(
                {k: fresh[key].get(k) for k in ("license_name", "license_url", "evidence", "attribution")}
            )
        else:
            current[key] = fresh[key]
    for key in ("width", "height", "duration_s", "fps"):
        if current["media"].get(key) is None and item["media"].get(key) is not None:
            current["media"][key] = item["media"][key]
    for key in ("filters", "history_progress", "geographic_query", "topic_query_applied"):
        if key in item.get("catalog", {}):
            current["catalog"][key] = item["catalog"][key]
    if signature(current) != signature(item):
        invalidate_approval(current)
    return current


def acquire(item, target):  # noqa: C901 - geographic/SDK transports enforce identity, private target and byte bounds
    if item["provider"] == "mapillary":
        raw = _map_request(item["source_id"])
        fresh = _map_row(raw, item["catalog"]["selected_file"])
        if fresh["catalog"].get("asset_id") != item["catalog"].get("asset_id"):
            raise ProviderError("Mapillary representation changed; review separately.")
        download(raw[item["catalog"]["selected_file"]], target, max_bytes=MAX_BYTES)
        return

    async def run():
        client = _client()
        try:
            await _authorized(client)
            fresh, message = await _get_message(client, item["source_url"])
            if fresh["catalog"]["asset_id"] != item["catalog"]["asset_id"]:
                raise ProviderError("Telegram attachment changed; cached media cannot replace the original selection.")
            size = (fresh["media"] or {}).get("size")
            if size and size > MAX_BYTES:
                raise ProviderError("Telegram attachment exceeds the bounded 512 MiB acquisition limit.")

            def progress(received, total):
                if received > MAX_BYTES or (total and total > MAX_BYTES):
                    raise ProviderError("Telegram attachment exceeded the bounded acquisition limit.")

            downloaded = await client.download_media(message, file=str(target), progress_callback=progress)
            if not downloaded or Path(downloaded).resolve() != Path(target).resolve():
                raise ProviderError("Telegram did not produce the selected attachment at the expected private target.")
        except ProviderError:
            raise
        except Exception as error:  # noqa: BLE001 - RPC exception bodies can expose account/session data
            raise _telegram_error(error) from None
        finally:
            await _disconnect(client)

    asyncio.run(asyncio.wait_for(run(), timeout=180))


def x_access(auth_path=None, model=None):
    """Inspect local prerequisite metadata only. Never invoke Grok, refresh, or API billing."""
    root = Path.home() / ".grok"
    path = Path(auth_path) if auth_path else root / "auth.json"
    result = {
        "route": "retained Grok OAuth x_search",
        "oauth": "missing",
        "token_expiry": None,
        "refresh_available": False,
        "model": model,
        "model_tool_verified": False,
        "search": "unverified",
        "original_post": "manual public reference",
        "screenshots": "separately supplied local image",
        "attachment_download": "unverified",
        "api_key_used": False,
        "billing_fallback": False,
        "live_probe": "not_run",
    }
    try:
        if not model and (root / "config.toml").is_file():
            config = tomllib.loads((root / "config.toml").read_text(encoding="utf-8"))
            result["model"] = config.get("model")
        if path.is_file() and path.stat().st_size <= 256 * 1024:
            data = json.loads(path.read_text(encoding="utf-8"))
            records = [
                v
                for v in data.values()
                if isinstance(v, dict)
                and v.get("auth_mode") == "oidc"
                and v.get("oidc_issuer") == "https://auth.x.ai"
                and v.get("key")
            ]
            if len(records) == 1:
                record = records[0]
                expiry = record.get("expires_at")
                result["token_expiry"] = datetime.fromisoformat(expiry).isoformat() if isinstance(expiry, str) else None
                result["oauth"] = (
                    "expired"
                    if result["token_expiry"] and datetime.fromisoformat(result["token_expiry"]) <= datetime.now(UTC)
                    else "present_unverified"
                )
                result["refresh_available"] = bool(record.get("refresh_token"))
            elif records:
                result["oauth"] = "ambiguous_selection"
            else:
                result["oauth"] = "unsupported_auth_mode"
    except (ValueError, OSError, TypeError, AttributeError):
        result["oauth"] = "invalid_private_auth_metadata"
        result["token_expiry"] = None
    result["next_action"] = (
        "Use the retained client's local OAuth login/refresh, verify the selected model and x_search with an explicitly authorized bounded probe. No search or billing fallback is enabled here."
    )
    return result
