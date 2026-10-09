"""Bounded Net-film and Suspilne discovery; card references are not media files."""

import re
import tempfile
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urlencode, urljoin, urlsplit

from .http import ProviderError, download, get_json, public_url
from .models import candidate

NAMES = ("netfilm", "suspilne")
NETFILM = "https://www.net-film.ru"
SUSPILNE = "https://mediateka.suspilne.media"
NETFILM_PAGE_SIZE = 20
HTML_BYTES = 8 * 1024 * 1024
TEXT_CHARS = 8192


def _text(parts):
    return " ".join("".join(parts).split())[:TEXT_CHARS]


def _locator(item, description, poster, metadata):
    item["asset_type"] = "video"
    item["media"]["kind"] = "video"
    item["preview"]["poster_url"] = public_url(poster)
    item["source_metadata"] = {"description": description}
    item["catalog"] = {"record_id": item["source_id"], "discovery_only": True, **metadata}
    item["acquisition"] = {"status": "unavailable", "method": "manual", "evidence": [item["source_url"]]}
    item["match"]["reason"] = "Catalog text match; inspect the source before visual confirmation."
    return item


class _NetfilmResults(HTMLParser):
    """Group nested result chapters under their canonical film card."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.rows = []
        self.total = None
        self.depth = 0
        self.card_depth = None
        self.card = None
        self.field = None
        self.title_span_depth = 0
        self.title_span_index = 0

    def handle_starttag(self, tag, attrs):
        values = dict(attrs)
        classes = (values.get("class") or "").split()
        total = values.get("data-resulttotal")
        if total is not None and total.isdigit():
            self.total = int(total)
        if tag == "div":
            self.depth += 1
            if "newsreel-unit" in classes:
                self.card_depth = self.depth
                self.card = {"title": [], "date": [], "tech": [], "description": [], "url": None, "poster": None}
        if self.card is None:
            return
        self._start_field(self.card, tag, values, classes)

    def _start_field(self, card, tag, values, classes):
        if tag == "a" and "newsreel-unit__name" in classes:
            card["url"] = urljoin(NETFILM, values.get("href") or "")
            self.field = "title"
            self.title_span_depth = 0
            self.title_span_index = 0
        elif tag == "span" and self.field in ("title", "date"):
            self.title_span_depth += 1
            if self.title_span_depth == 1:
                self.title_span_index += 1
                self.field = "title" if self.title_span_index == 1 else "date"
        elif tag == "p":
            if "newsreel-unit__tech" in classes:
                self.field = "tech"
            elif "data-nt" in values:
                self.field = "description"
        elif tag == "img" and not card["poster"]:
            card["poster"] = public_url(urljoin(NETFILM, values.get("src") or ""))

    def handle_data(self, data):
        if self.card is not None and self.field:
            self.card[self.field].append(data)

    def handle_endtag(self, tag):
        if self.card is not None and self.field:
            if tag == "span" and self.field in ("title", "date"):
                self.title_span_depth -= 1
            if tag in ("span", "br"):
                self.card[self.field].append(" ")
            if (tag == "a" and self.field in ("title", "date")) or tag == "p":
                self.card[self.field].append(" ")
                self.field = None
        if tag == "div":
            if self.card is not None and self.depth == self.card_depth:
                self.rows.append(self.card)
                self.card = None
                self.card_depth = None
                self.field = None
            self.depth -= 1


def _html(url):
    # Reuse the existing bounded, DNS-pinned HTTPS transport and keep the page
    # outside the user's project and the distributed source tree.
    with tempfile.TemporaryDirectory(prefix="getbrolls-catalog-") as folder:
        path = Path(folder) / "search.html"
        download(url, path, max_bytes=HTML_BYTES)
        try:
            return path.read_text(encoding="utf-8-sig")
        except UnicodeError:
            raise ProviderError("Net-film returned an invalid UTF-8 search page.") from None


def _netfilm_row(row, search_url, total):
    parsed = urlsplit(row["url"] or "")
    ident = re.fullmatch(r"/film-(\d+)/?", parsed.path)
    title = _text(row["title"])
    if parsed.hostname != "www.net-film.ru" or not ident or not title:
        raise ProviderError("Net-film returned an invalid film search card.")
    tech = _text(row["tech"])
    published = re.search(r"опубликовано:\s*([\d.]+\s+[\d:]+)", tech)
    return _locator(
        candidate("netfilm", ident[1], title, f"{NETFILM}/film-{ident[1]}/"),
        _text(row["description"]),
        row["poster"],
        {
            "date_text": _text(row["date"]) or None,
            "published_at": published[1] if published else None,
            "technical_text": tech,
            "search_url": search_url,
            "reported_total_count": total,
        },
    )


def _netfilm(query, limit):
    rows = []
    seen = set()
    for page in range(1, (limit + NETFILM_PAGE_SIZE - 1) // NETFILM_PAGE_SIZE + 1):
        search_url = f"{NETFILM}/found-page-{page}/?{urlencode({'q': query})}"
        parser = _NetfilmResults()
        parser.feed(_html(search_url))
        parser.close()
        if parser.total is None or bool(parser.total) != bool(parser.rows) or parser.card is not None:
            raise ProviderError("Net-film search layout changed or access was rejected; no empty result inferred.")
        for row in parser.rows:
            item = _netfilm_row(row, search_url, parser.total)
            if item["id"] not in seen:
                rows.append(item)
                seen.add(item["id"])
        if len(rows) >= limit or page * NETFILM_PAGE_SIZE >= parser.total:
            break
    return rows[:limit]


def _suspilne_row(row, locale):
    ident, title = row.get("id"), row.get("name")
    if type(ident) is not int or ident <= 0 or not isinstance(title, str) or not title.strip():
        raise ProviderError("Suspilne returned an invalid media search card.")
    description = row.get("description")
    poster = row.get("poster_image")
    item = _locator(
        candidate("suspilne", str(ident), title.strip()[:TEXT_CHARS], f"{SUSPILNE}/{locale}/media/{ident}"),
        description[:TEXT_CHARS] if isinstance(description, str) else None,
        urljoin(SUSPILNE, poster) if isinstance(poster, str) else None,
        {"year": row.get("year"), "published_at": row.get("published_at"), "locale": locale},
    )
    duration = row.get("duration")
    if type(duration) in (int, float) and 0 < duration < float("inf"):
        item["media"]["duration_s"] = duration
    return item


def _suspilne(query, limit, selected_filters):
    locale = selected_filters["locale"]
    data = get_json(
        f"{SUSPILNE}/api/content",
        {
            "l": locale,
            "branches": "media_items",
            "filter[media_items][name]": query,
            "page[media_items][limit]": limit,
            "page[media_items][offset]": 0,
        },
    )
    branch = data.get("media_items") if isinstance(data, dict) else None
    if not isinstance(branch, dict) or not isinstance(branch.get("items"), list):
        raise ProviderError("Suspilne search response changed; no empty result inferred.")
    total = branch.get("total_count")
    if type(total) is not int or total < 0 or bool(total) != bool(branch["items"]):
        raise ProviderError("Suspilne returned inconsistent search coverage.")
    rows = []
    seen = set()
    for row in branch["items"][:limit]:
        if not isinstance(row, dict):
            raise ProviderError("Suspilne returned an invalid search record.")
        if not isinstance(row.get("type"), str):
            raise ProviderError("Suspilne search record is missing its media type.")
        if row.get("type") != "film":
            continue
        item = _suspilne_row(row, locale)
        if item["id"] not in seen:
            item["catalog"]["reported_total_count"] = total
            rows.append(item)
            seen.add(item["id"])
    return rows


def search(name, query, limit, media, selected_filters):
    if media == "image":
        return []
    return _netfilm(query, limit) if name == "netfilm" else _suspilne(query, limit, selected_filters)
