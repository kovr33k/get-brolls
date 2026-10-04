"""Storyboard and credits generated from the canonical manifest."""

import html
from datetime import date
from pathlib import Path

from .models import signature
from .review import review_epoch


def safe_preview_url(value):
    from .http import public_url

    if not isinstance(value, str):
        return None
    if value.startswith("https://"):
        return public_url(value)
    if value.startswith(("previews/", "clips/")) and ".." not in Path(value).parts:
        return value
    return None


# Três botões: "outra fonte" virou opção dentro de "Request changes" — o valor exportado
# (`alternative`) continua o mesmo, só o caminho até ele ficou mais curto.
REVIEW_PANEL = (
    '<section class="review-panel"><h2>Does this clip work?</h2>'
    '<div class="review-actions">'
    '<button class="approve" data-decision="approved" aria-pressed="false"'
    ' title="Approve this clip for the final download to your folder.">Approve</button>'
    '<button data-decision="changes" aria-pressed="false"'
    ' title="Describe the changes you want (a different segment or video) and I will revise it.">Request changes</button>'
    '<button data-decision="rejected" aria-pressed="false"'
    ' title="Reject this clip and exclude it from the final download.">Reject</button>'
    "</div>"
    '<button class="comment-toggle" type="button" aria-expanded="false">Comment</button>'
    '<div class="review-fields" hidden>'
    '<label class="want-other" hidden><input type="checkbox" data-alternative>'
    " Find a different video</label>"
    '<label>What to change<textarea data-comment rows="3"'
    ' placeholder="Describe what you want in one line…"></textarea></label>'
    '<label class="other-url" hidden>Found another video? Paste the link (optional)'
    '<input data-suggestion type="url" placeholder="https://…"></label>'
    '<button class="confirm-review" type="button" hidden>Confirm change request</button>'
    "</div>"
    '<p data-review-status class="feedback" role="status"></p></section>'
)


def timecode(seconds):
    """Seconds → MM:SS.ff, the Storyboard's interval notation."""
    minutes, rest = divmod(float(seconds), 60)
    return f"{int(minutes):02d}:{rest:05.2f}"


def segment_label(c):
    if c["segment"]["start_s"] is not None:
        return f"{timecode(c['segment']['start_s'])}–{timecode(c['segment']['end_s'])}"
    if c.get("media", {}).get("kind") == "image":
        return "Still image"
    return "full video"


def source_domain(url):
    from urllib.parse import urlsplit

    host = urlsplit(url).hostname or ""
    return host.removeprefix("www.")


def source_card(c, source, sheet, poster, esc):
    """Collected source as a card: thumbnail (sheet when it exists), identity and link."""
    # The card shows the poster; the full contact sheet follows inline below it.
    thumb = poster or sheet
    image = (
        f'<img class="source-thumbnail" src="{esc(thumb)}" alt="" loading="lazy">'
        if thumb
        # O painel de detalhe é onde a frase comprida cabe: a galeria só mostra a
        # tarja "image only", e aqui a pessoa fica sabendo o que fazer a respeito.
        else ('<span class="source-thumbnail placeholder">Motion preview unavailable — open the original link</span>')
    )
    usage = {
        "unknown": "not checked yet",
        "permitted": "permission recorded",
        "restricted": "restricted use",
    }.get(c["rights"]["status"], c["rights"]["status"])
    # O id é um hash: fica no title, fora do lugar nobre do card.
    details = [
        f"<strong>{esc(c['title'])}</strong>",
        f'<code title="Internal clip ID">{esc(c["id"])}</code>',
    ]
    if c["segment"]["start_s"] is not None:
        details.append(f"<p>{esc(cut_label(c))}</p>")
        duration = c.get("media", {}).get("duration_s")
        if duration:
            left = max(0.0, min(100.0, 100 * c["segment"]["start_s"] / duration))
            width = max(0.5, min(100.0 - left, 100 * (c["segment"]["end_s"] - c["segment"]["start_s"]) / duration))
            details.append(
                f'<span class="cut-position" role="img" aria-label="Clip position in the source video">'
                f'<span style="left:{left:.2f}%;width:{width:.2f}%"></span></span>'
            )
    if c.get("creator", {}).get("name"):
        details.append(f"<p>Creator: {esc(c['creator']['name'])}</p>")
    if c.get("captured_at"):
        details.append(f"<p>Captured on: {esc(c['captured_at'])}</p>")
    catalog = c.get("catalog") or {}
    locator = c.get("locator") or {}
    reference = c.get("source_reference") or {}
    observed = c.get("source_metadata") or {}
    for label, value in (
        ("Catalog record", catalog.get("record_id")),
        ("Institution", catalog.get("institution")),
        ("Institution record", catalog.get("institution_record")),
        ("Selected original file", catalog.get("selected_file")),
        ("Parent recording", catalog.get("parent_id")),
        ("Shot source start (seconds)", catalog.get("provider_source_start")),
        ("Shot duration (seconds)", catalog.get("provider_shot_duration")),
        ("Catalog coverage", catalog.get("coverage")),
        ("Station", catalog.get("station")),
        ("Station date coverage", catalog.get("station_coverage")),
        ("Program", catalog.get("show")),
        ("Broadcast time", catalog.get("broadcast_time")),
        ("Caption match", catalog.get("matching_text")),
        ("Transcript language", catalog.get("language")),
        ("Transcript matches", catalog.get("matches")),
        ("Transcript disclaimer", catalog.get("disclaimer")),
        ("Item conditions", catalog.get("copyrights")),
        ("Conditions scope", catalog.get("scope")),
        ("Source location", catalog.get("location")),
        ("Higher-quality original request", catalog.get("original_request_url")),
        ("Published on", catalog.get("published_at")),
        ("Unit", catalog.get("unit")),
        ("Item rights", c["rights"].get("license_name") if catalog else None),
        ("Access limitation", c["acquisition"].get("restriction") if catalog else None),
        ("Archive asset", locator.get("asset_id") or locator.get("shot_id")),
        ("Source film", locator.get("film_title")),
        ("Original reference", locator.get("archive_url") or reference.get("source_url")),
        ("Original interval", locator.get("source_interval") or reference.get("source_interval")),
        ("Request footage", locator.get("request_url")),
        ("Shotlist / script", locator.get("shotlist_url") or locator.get("shotlist")),
        ("Supplied conditions", reference.get("conditions")),
        ("Original access", c["acquisition"].get("restriction") if locator else None),
        ("License required", "Yes" if locator.get("license_required") else None),
        ("Source date", observed.get("date")),
        ("Source language", observed.get("language")),
        ("Source description", observed.get("description")),
    ):
        if value is not None and value not in ("", [], {}):
            details.append(f"<p>{label}: {esc(value)}</p>")
    details.append(f"<p>Why this was selected: {esc(c.get('match', {}).get('reason') or 'not recorded yet')}</p>")
    if c["rights"].get("attribution"):
        details.append(f"<p>{esc(c['rights']['attribution'])}</p>")
    details.append(f"<p>Usage rights? {esc(usage)} — check the source license before publishing.</p>")
    info = '<div class="source-link-info">'
    if source:
        info += f'<span class="source-domain">{esc(source_domain(source))}</span>'
    info += '<div class="source-details">' + "".join(details) + "</div>"
    info += (
        '<span class="source-link-label">Open original source ↗</span>'
        if source
        else '<span class="source-link-label">Own recording · no external source</span>'
    )
    info += "</div>"
    if source:
        return (
            f'<a class="source-link-card" href="{esc(source)}" target="_blank" rel="noopener noreferrer">'
            f"{image}{info}</a>"
        )
    return f'<div class="source-link-card">{image}{info}</div>'


def script_bubble(narration, esc):
    if not narration:
        return ""
    return (
        '<div class="caption-content review-script"><span class="script-label">Script narration</span>'
        f'<blockquote tabindex="0" role="region" aria-label="Script narration">“{esc(narration)}”</blockquote></div>'
    )


def format_seconds(value):
    """Seconds as a short English label: 7 → "7.0 s", 7.417 → "7.4 s"."""
    return f"{value:.1f} s"


def cut_label(candidate):
    """Where the cut sits in the source: 'clip 0:59.0–1:05.0 of 2:02.4'."""
    from .media import clock

    seg = candidate["segment"]
    if seg["start_s"] is None:
        return "clip interval to be defined"
    text = f"clip {clock(seg['start_s'])}–{clock(seg['end_s'])}"
    duration = candidate.get("media", {}).get("duration_s")
    if duration:
        text += f" of {clock(duration)}"
    return text


def contact_sheet_figure(candidate, sheet, esc):
    """Inline contact sheet with a per-cell time legend when ffmpeg drew no labels."""
    preview = candidate["preview"]
    times = preview.get("frame_times_s") or []
    grid = preview.get("sheet_grid") or []
    caption = f"Clip frames ({len(times)})" if times else "Clip frames"
    if len(grid) == 2:  # noqa: PLR2004 - `grid` is [columns, rows]
        caption += f" · grid {grid[0]}×{grid[1]}"
    caption += " · " + cut_label(candidate)
    legend = ""
    if times and not preview.get("sheet_labels"):
        cells = " · ".join(f"{i + 1} = {format_seconds(t)}" for i, t in enumerate(times))
        legend = f'<p class="sheet-legend">{esc(cells)}</p>'
    return (
        f'<figure class="contact-sheet"><a href="{esc(sheet)}" target="_blank" rel="noopener">'
        f'<img src="{esc(sheet)}" alt="Clip frames" loading="lazy"></a>'
        f"<figcaption>{esc(caption)} · open full size</figcaption>{legend}</figure>"
    )


_STALE_TEXT = {
    "candidate_missing": "Candidate is no longer in the project.",
    "rejected": "Rejected. This confirmation no longer counts.",
    "context_unverified": "Fragment context could not be verified.",
    "context_changed": "Fragment context changed. Confirm again for the current scenario.",
    "representation_changed": "Representation changed. Confirm the current material again.",
    "interval_changed": "Interval changed. Confirm the current interval again.",
    "superseded": "Superseded by a later confirmation.",
}


def _interval_text(interval):
    if not isinstance(interval, dict):
        return "Interval not recorded"
    if interval.get("kind") == "still":
        return "Still image " + str(interval.get("file") or "")
    return f"{interval.get('start_s')}–{interval.get('end_s')} s"


def _hash_text(hashes):
    parts = [f"{key} {value}" for key, value in (hashes or {}).items() if value]
    return ", ".join(parts) if parts else "No hash recorded"


def _esc(value):
    return html.escape(str(value if value is not None else ""), quote=True)


def _raw_hit_items(row):
    if not row["raw_hits"]:
        return ["<li>No raw hits recorded.</li>"]
    return [
        (
            f'<li class="raw-hit">{_esc(hit.get("title"))} '
            f"<code>{_esc(hit.get('candidate'))}</code> "
            f"approval {_esc(hit.get('approval'))}, rights {_esc(hit.get('rights'))}</li>"
        )
        for hit in row["raw_hits"]
    ]


def _identity_paragraph(identity):
    return (
        "<p>"
        f"Candidate <code>{_esc(identity['candidate'])}</code>; "
        f"source {_esc(identity.get('source_id'))}; "
        f"asset {_esc(identity.get('asset_file'))}; "
        f"representation {_esc(identity.get('selected_file'))}; "
        f"interval {_esc(_interval_text(identity.get('interval')))}; "
        f"hashes {_esc(_hash_text(identity.get('hashes')))}."
        "</p>"
    )


def _option_article(option):
    viewing = option.get("viewing") or {}
    identities = option.get("identities") or []
    noun = "identity" if len(identities) == 1 else "identities"
    viewed = viewing.get("viewed") or "unrecorded"
    part = viewing.get("viewed_preview")
    viewed_text = f"{viewed} {part}" if part else str(viewed)
    parts = [
        '<article class="suitable-option">',
        f"<p>Option {_esc(option['option_id'])}: {len(identities)} {noun}. Viewed {_esc(viewed_text)}.</p>",
        f"<p>{_esc(viewing.get('observation'))}</p>",
        f"<p>{_esc(viewing.get('match'))}</p>",
    ]
    if option.get("grouped_reason"):
        parts.append(f"<p>Grouped as {_esc(option['grouped_reason'])}.</p>")
    if option.get("distinctness_support"):
        parts.append(f"<p>Distinctness: {_esc(option.get('distinctness_support'))}.</p>")
    if option.get("distinctness"):
        parts.append(f"<p>{_esc(option['distinctness'])}</p>")
    parts.extend(
        f'<p class="unsupported-distinctness">Unsupported distinctness claim: {_esc(claim)}</p>'
        for claim in option.get("unsupported_distinctness") or []
    )
    parts.append("<details><summary>Identities, intervals, and hashes</summary>")
    parts.extend(_identity_paragraph(identity) for identity in identities)
    parts.append("</details></article>")
    return parts


def _suitable_items(row):
    if not row["suitable_options"]:
        return ["<p>No confirmed suitable options yet.</p>"]
    parts = []
    for option in row["suitable_options"]:
        parts.extend(_option_article(option))
    return parts


def _evidence_state(record):
    if record.get("deferred") and record.get("current"):
        return "Deferred: a separately requested original is not counted"
    return _STALE_TEXT.get(record.get("stale_reason"), "Current")


def _evidence_items(row):
    if not row["viewing_evidence"]:
        return ["<li>No viewing evidence recorded.</li>"]
    return [
        (
            f'<li class="viewing-evidence">{_esc(record.get("verdict"))}; {_esc(_evidence_state(record))}; '
            f"{_esc(record.get('observation'))}; interval {_esc(_interval_text(record.get('interval')))}; "
            f"candidate <code>{_esc(record.get('candidate'))}</code></li>"
        )
        for record in row["viewing_evidence"]
    ]


def _decision_items(row):
    if not row["pending_human_decisions"]:
        return ["<li>No pending human decision.</li>"]
    return [
        (
            f'<li class="pending-decision"><code>{_esc(decision["candidate"])}</code> '
            f"approval {_esc(decision.get('approval'))}, rights {_esc(decision.get('rights'))}</li>"
        )
        for decision in row["pending_human_decisions"]
    ]


def _fragment_article(row):
    narration = (row.get("context") or {}).get("narration")
    parts = [
        f'<article class="fragment-search" data-fragment="{_esc(row["fragment"])}">',
        f"<h3>Fragment {_esc(row['fragment'])}</h3>",
        (
            f"<p>Suitable options: {row['suitable_count']} of 3. "
            f"Target reached: {'yes' if row['target_reached'] else 'no'}.</p>"
        ),
        (
            f"<p>Pass {_esc(row.get('pass'))}, catalog {_esc(row.get('catalog'))}, next {_esc(row.get('next')).replace('_', ' ')}.</p>"
        ),
    ]
    shortfall = row.get("shortfall")
    if shortfall:
        parts.append(
            f'<p class="search-shortfall">Shortfall: {_esc(shortfall.get("suitable_count"))} of 3. '
            f"{_esc(shortfall.get('reason'))} {_esc(shortfall.get('note'))}</p>"
        )
    if narration:
        parts.append(
            f'<p class="scenario-narration"><span class="script-label">Scenario narration</span> {_esc(narration)}</p>'
        )
    parts.append("<h4>Raw hits</h4><ul>")
    parts.extend(_raw_hit_items(row))
    parts.append("</ul><h4>Confirmed suitable options</h4>")
    parts.extend(_suitable_items(row))
    parts.append("<h4>Viewing evidence</h4><ul>")
    parts.extend(_evidence_items(row))
    parts.append("</ul><h4>Pending human decisions</h4><ul>")
    parts.extend(_decision_items(row))
    parts.append("</ul></article>")
    return parts


def _search_preface(ledger):
    """English search summary. Scenario text and agent observations stay in their original language."""
    from .fragment_search import progress

    rows = progress(ledger.data, project=ledger.root.parent)
    if not rows:
        return ""
    parts = [
        '<section class="search-options" aria-label="Fragment search options">',
        "<h2>Search options</h2>",
        "<p>Visual confirmation is not human approval and does not grant usage rights.</p>",
    ]
    for row in rows:
        parts.extend(_fragment_article(row))
    parts.append("</section>")
    return "".join(parts)


def render(ledger, *, ready_only=False):
    records = []
    story_items = []
    credits_lines = [
        "---",
        "type: credits",
        "status: current",
        "created: " + date.today().isoformat(),  # noqa: DTZ011 - local date in the rendered page; timezone-aware would shift the day near midnight
        "updated: " + date.today().isoformat(),  # noqa: DTZ011 - local date in the rendered page; timezone-aware would shift the day near midnight
        "tags: [get-brolls, credits]",
        "---",
        "",
        "# Collection credits",
        "",
    ]

    def esc(s):
        return html.escape(str(s or ""))

    for c in ledger.data["items"]:
        out = safe_preview_url(c["output"]["path"])
        if out:
            credits_lines += [
                f"## {c['id']}",
                f"- File: {out}",
                f"- Source: {c['source_url'] or 'local original'}",
                f"- Creator: {c['creator'].get('name') or 'not provided'}",
                f"- License: {c['rights'].get('license_name') or 'see evidence'}",
                f"- License URL: {c['rights'].get('license_url') or 'not provided'}",
                f"- Evidence: {'; '.join(c['rights']['evidence'])}",
                "",
            ]
        if ready_only:
            preview_path = safe_preview_url(
                c["preview"].get("poster_path" if c.get("asset_type") == "image" else "gif_path")
            )
            if not (c.get("narration") or "").strip() or not preview_path or not (ledger.root / preview_path).is_file():
                continue
        p = safe_preview_url(c["preview"].get("poster_path") or c["preview"].get("poster_url"))
        gif = safe_preview_url(c["preview"].get("gif_path"))
        sheet = safe_preview_url(c["preview"].get("contact_sheet_path"))
        source = safe_preview_url(c["source_url"])
        has_preview = bool(c["preview"].get("poster_path"))
        context = safe_preview_url(c["preview"].get("context_path"))
        content = source_card(c, source, sheet, p, esc)
        if context:
            content += f'<figure class="context-still"><img src="{esc(context)}" alt="Presenter image for context" loading="lazy"><figcaption>Presenter in frame (context)</figcaption></figure>'
        if sheet:
            content += contact_sheet_figure(c, sheet, esc)
        if c["preview"].get("warning"):
            content += f'<p role="status">{esc(c["preview"]["warning"])}</p>'
        if not c.get("local_path"):
            content += '<p class="source-note">Only a source image is available here. A motion preview requires the original file on your computer.</p>'
        content = f'<section class="review-source"><h2>Collected source</h2>{content}</section>'
        content += script_bubble(c.get("narration"), esc)

        records.append(
            {
                "id": c["id"],
                "signature": signature(c),
                "state": "pending",
                "title": c["title"],
                "segment": c["segment"],
                "asset_type": c.get("asset_type", "video"),
                "captured_at": c.get("captured_at"),
                "source": source,
                "narration": c.get("narration"),
                "collection_reason": c.get("match", {}).get("reason"),
                "creator": c.get("creator", {}).get("name"),
                "poster": p,
                "context_poster": context,
                "review": (
                    {**c.get("review", {}), "state": "approved"}
                    if c["approval"]["status"] == "approved" and c["approval"].get("signature") == signature(c)
                    else {
                        **c.get("review", {}),
                        "state": c.get("review", {}).get("state", "pending")
                        if c.get("review", {}).get("signature") == signature(c)
                        else "pending",
                    }
                ),
                "reviewEpoch": review_epoch(c),
            }
        )
        content += REVIEW_PANEL
        story_items.append(
            {
                "title": c["title"],
                "content": content,
                "presenter": p,
                "presenterLabel": "Video clip" if has_preview else "Source image · no motion preview",
                "no_preview": not has_preview,
                "gif": gif,
                "poster": None,
                "time": segment_label(c),
                "status": c["state"],
                # A fala já está no painel de material como balão; nada a repetir.
                "narration": None,
            }
        )
    from .ledger import atomic_write
    from .review import enhance
    from .storyboard import render_page

    atomic_write(
        ledger.root / "review.html",
        enhance(render_page(story_items, extra_html=_search_preface(ledger)), ledger, records),
    )
    atomic_write(ledger.root / "credits.md", "\n".join(credits_lines))
    return str(ledger.root / "review.html")
