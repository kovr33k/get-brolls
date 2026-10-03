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

    atomic_write(ledger.root / "review.html", enhance(render_page(story_items), ledger, records))
    atomic_write(ledger.root / "credits.md", "\n".join(credits_lines))
    return str(ledger.root / "review.html")
