import base64
import shutil
import subprocess
import unittest
from pathlib import Path

import _isolation  # noqa: F401
from _paths import ROOT

from getbrolls.storyboard import render_page


class StoryboardTest(unittest.TestCase):
    def test_telegram_publication_is_separate_from_capture_including_legacy_records(self):
        import html

        from getbrolls.models import candidate
        from getbrolls.rendering import source_card

        row = candidate("telegram", "channel:30", "Fixture public message", "https://t.me/channel/30")
        row["captured_at"] = "2026-10-03"
        row["catalog"] = {"source_date": "2026-10-03"}
        card = source_card(row, row["source_url"], None, None, html.escape)
        self.assertIn("Published on: 2026-10-03", card)

        self.assertNotIn("Captured on:", card)
        row["captured_at"] = "2020-01-01"
        row["catalog"]["published_at"] = "2026-10-03"
        card = source_card(row, row["source_url"], None, None, html.escape)
        self.assertIn("Captured on: 2020-01-01", card)
        self.assertIn("Published on: 2026-10-03", card)

    def test_telegram_print_records_do_not_export_legacy_publication_as_capture(self):
        import copy
        import json
        import re
        import tempfile

        from getbrolls.ledger import Ledger
        from getbrolls.models import candidate
        from getbrolls.rendering import render

        with tempfile.TemporaryDirectory() as folder:
            ledger = Ledger(folder)
            ledger.data["project_id"] = "telegram-print-date-test"
            row = candidate("telegram", "channel:30", "Fixture public image", "https://t.me/channel/30")
            row["asset_type"] = row["media"]["kind"] = "image"
            row["captured_at"] = "2026-10-03"
            row["catalog"] = {"source_date": "2026-10-03"}
            ledger.data["items"].append(row)
            before = copy.deepcopy(ledger.data)
            page = Path(render(ledger)).read_text(encoding="utf-8")
            match = re.search(r"window.GETBROLLS_REVIEW=(.*?);</script>", page)
            assert match is not None
            exported = json.loads(match.group(1))["items"][0]
            self.assertIsNone(exported["captured_at"])
            self.assertEqual("2026-10-03", exported["published_at"])
            self.assertEqual(before, ledger.data)

    @unittest.skipUnless(shutil.which("node"), "Node.js required")
    def test_navigation_survives_review_toolbar_remounting(self):
        node = shutil.which("node")
        assert node is not None
        result = subprocess.run(
            [
                node,
                str(ROOT / "tests/fixtures/storyboard_navigation.cjs"),
                str(ROOT / "assets/storyboard.js"),
            ],
            capture_output=True,
            text=True,
            encoding="utf-8",
            check=False,
            timeout=10,
        )
        self.assertEqual(0, result.returncode, result.stderr)

    @unittest.skipUnless(shutil.which("node"), "Node.js required")
    def test_print_waits_for_delayed_images_and_preserves_decisions(self):
        node = shutil.which("node")
        assert node is not None
        result = subprocess.run(
            [node, str(ROOT / "tests/fixtures/storyboard_print.cjs"), str(ROOT / "assets/review.js")],
            capture_output=True,
            text=True,
            encoding="utf-8",
            check=False,
            timeout=10,
        )
        self.assertEqual(0, result.returncode, result.stderr)

    def test_cli_rejection_survives_ready_storyboard_and_context_invalidation(self):
        import copy
        import json
        import re
        import tempfile

        from getbrolls.cli import parse_args
        from getbrolls.commands import execute
        from getbrolls.ledger import Ledger
        from getbrolls.models import candidate, invalidate_approval
        from getbrolls.rendering import render
        from getbrolls.runtime import audited

        with tempfile.TemporaryDirectory() as folder:
            ledger = Ledger(folder)
            ledger.data["project_id"] = "rejected-ready-view-test"
            item = candidate("youtube", "rejected", "Prepared but rejected clip")
            item["narration"] = "Texto original"
            item["preview"]["gif_path"] = "previews/ready.gif"
            (ledger.root / "previews/ready.gif").write_bytes(b"GIF89a")
            ledger.data["items"].append(item)
            ledger.save("fixture")
            audited(
                parse_args(["reject", "--candidate", item["id"], "--reason", "No sirve", "--project", folder]),
                execute,
            )
            ledger = Ledger(folder)
            before = copy.deepcopy(ledger.data)

            def state():
                page = Path(render(ledger, ready_only=True)).read_text(encoding="utf-8")
                match = re.search(r"window.GETBROLLS_REVIEW=(.*?);</script>", page)
                assert match is not None
                return json.loads(match.group(1))["items"][0]["review"]

            self.assertEqual("rejected", state()["state"])
            self.assertEqual(before, ledger.data)
            invalidate_approval(ledger.data["items"][0])
            self.assertEqual("pending", state()["state"])

    def test_ready_only_keeps_search_results_and_approvals_in_ledger(self):
        import copy
        import tempfile

        from getbrolls.ledger import Ledger
        from getbrolls.models import candidate, signature
        from getbrolls.rendering import render

        with tempfile.TemporaryDirectory() as folder:
            ledger = Ledger(folder)
            ledger.data["project_id"] = "ready-view-test"
            raw = candidate("youtube", "raw", "Unprepared search result")
            ready = candidate("youtube", "ready", "Prepared clip")
            ready["narration"] = "Solo 210 minutos."
            ready["preview"]["gif_path"] = "previews/ready.gif"
            (ledger.root / "previews/ready.gif").write_bytes(b"GIF89a")
            raw["preview"]["gif_path"] = "previews/ready.gif"
            raw["output"]["path"] = "clips/original.mp4"
            ready["approval"].update(status="approved", signature=signature(ready))
            missing = candidate("youtube", "missing", "Missing preview file")
            missing["narration"] = "Texto original"
            missing["preview"]["gif_path"] = "previews/missing.gif"
            ledger.data["items"] = [raw, ready, missing]
            before = copy.deepcopy(ledger.data)
            page = Path(render(ledger, ready_only=True)).read_text(encoding="utf-8")
            self.assertIn(ready["title"], page)
            self.assertIn(ready["narration"], page)
            self.assertNotIn(raw["title"], page)
            self.assertNotIn(missing["title"], page)
            self.assertIn(raw["id"], (ledger.root / "credits.md").read_text(encoding="utf-8"))
            self.assertEqual(before, ledger.data)
            full = Path(render(ledger)).read_text(encoding="utf-8")
            self.assertIn(raw["title"], full)

    def test_english_interface_preserves_original_language_content_and_decisions(self):
        import json
        import tempfile

        from getbrolls.ledger import Ledger
        from getbrolls.models import candidate, signature
        from getbrolls.rendering import render

        with tempfile.TemporaryDirectory() as folder:
            ledger = Ledger(folder)
            item = candidate("youtube", "es", "La última entrevista de Maduro")
            item["narration"] = "¿Cómo ocurrió la operación?"
            item["creator"]["name"] = "Vídeos de Venezuela"
            item["match"]["reason"] = "Discurso original en español"
            item["review"] = {
                "state": "changes",
                "comment": "Conservar el audio original",
                "signature": signature(item),
            }
            ledger.data["items"].append(item)
            before = json.dumps(item, ensure_ascii=False, sort_keys=True)
            page = Path(render(ledger)).read_text(encoding="utf-8")
            self.assertIn('<html lang="en">', page)
            self.assertIn("Save decisions", page)
            self.assertIn("Request changes", page)
            for value in (
                item["title"],
                item["narration"],
                item["creator"]["name"],
                item["match"]["reason"],
                item["review"]["comment"],
            ):
                self.assertIn(value, page)
            self.assertEqual(before, json.dumps(item, ensure_ascii=False, sort_keys=True))

    def test_empty_and_escaped_portable_review(self):
        page = render_page([], title="Teste <script>")
        self.assertIn("Nothing here yet", page)
        self.assertIn("Teste &lt;script&gt;", page)
        self.assertNotIn("data:font/ttf;base64,", page)
        self.assertIn("system-ui", page)

    def test_gallery_and_detail_share_items(self):
        page = render_page(
            [
                {
                    "title": "Plano <1>",
                    "content": "<p>Fonte verificada</p>",
                    "narration": "Fala & contexto",
                    "time": "2–8 s",
                }
            ]
        )
        self.assertIn("Plano &lt;1&gt;", page)
        self.assertIn('data-index="0"', page)
        self.assertIn('id="shot-0"', page)
        self.assertIn("Fala &amp; contexto", page)

    def test_rendered_storyboard_uses_current_logo(self):
        logo = ROOT / "assets" / "brand-logo.png"
        self.assertTrue(logo.is_file())
        encoded = base64.b64encode(logo.read_bytes()).decode("ascii")
        page = render_page([])
        self.assertIn('class="brand-logo"', page)
        self.assertIn(f'src="data:image/png;base64,{encoded}"', page)
        self.assertNotIn('<div class="brand"><svg', page)


def render_one(**overrides):
    """Um candidato de YouTube renderizado pelo pipeline real, do ledger ao HTML."""
    import tempfile

    from getbrolls.ledger import Ledger
    from getbrolls.models import candidate, set_segment
    from getbrolls.rendering import render

    with tempfile.TemporaryDirectory() as d:
        ledger = Ledger(d)
        c = candidate("youtube", "abc", "Foguete decolando")
        c["source_url"] = "https://www.youtube.com/watch?v=abc"
        set_segment(c, 7, 12)
        c["preview"].update(overrides)
        ledger.data["items"].append(c)
        return Path(render(ledger)).read_text(encoding="utf-8")


class ContactSheetRenderingTest(unittest.TestCase):
    def render_item(self, **overrides):
        return render_one(**overrides)

    def test_contact_sheet_is_inline_with_legend_when_unlabelled(self):
        page = self.render_item(
            poster_path="previews/a-poster.jpg",
            contact_sheet_path="previews/a-sheet.jpg",
            frame_times_s=[7.0, 8.3, 9.5, 10.8],
            sheet_grid=[4, 1],
            sheet_labels=False,
        )
        self.assertIn('<figure class="contact-sheet">', page)
        self.assertIn('<img src="previews/a-sheet.jpg"', page)
        self.assertIn("1 = 7.0 s · 2 = 8.3 s · 3 = 9.5 s · 4 = 10.8 s", page)
        self.assertIn("Clip frames (4) · grid 4×1 · clip 0:07.0–0:12.0", page)
        self.assertIn("Video clip", page)
        self.assertNotIn("Contact sheet", page)
        self.assertNotIn("Sem prévia", page)
        self.assertNotIn("Ver contact sheet", page)

    def test_labelled_sheet_has_no_legend(self):
        page = self.render_item(
            poster_path="previews/a-poster.jpg",
            contact_sheet_path="previews/a-sheet.jpg",
            frame_times_s=[7.0, 9.5],
            sheet_grid=[2, 1],
            sheet_labels=True,
        )
        self.assertIn('<figure class="contact-sheet">', page)
        self.assertNotIn('<p class="sheet-legend">', page)

    def test_source_thumbnail_is_never_called_a_preview(self):
        page = self.render_item(poster_url="https://i.ytimg.com/vi/abc/hq.jpg")
        self.assertIn("Source image · no motion preview", page)
        self.assertIn('<span class="preview-badge">image only</span>', page)
        self.assertNotIn("Video clip", page)
        self.assertNotIn('alt="Prévia', page)
        self.assertIn('alt="Source thumbnail — Foguete decolando"', page)


class StoryboardV2Test(unittest.TestCase):
    """The generator ships the approved V2 template (source card, speech bubble, decisions)."""

    def render_two(self):
        import tempfile

        from getbrolls.ledger import Ledger
        from getbrolls.models import candidate, set_segment
        from getbrolls.rendering import render

        with tempfile.TemporaryDirectory() as d:
            ledger = Ledger(d)
            bare = candidate("youtube", "one", "Sem prévia ainda")
            bare["source_url"] = "https://www.youtube.com/watch?v=one"
            bare["preview"]["poster_url"] = "https://i.ytimg.com/vi/one/hq.jpg"
            shown = candidate("youtube", "two", "Foguete <decolando>")
            shown["source_url"] = "https://www.youtube.com/watch?v=two"
            shown["creator"]["name"] = "KHOU 11"
            shown["media"]["duration_s"] = 122.0
            set_segment(shown, 59, 65)
            shown["narration"] = "e o foguete saiu do chão"
            shown["preview"].update(
                poster_path="previews/b-poster.jpg",
                gif_path="previews/b.gif",
                contact_sheet_path="previews/b-sheet.jpg",
                frame_times_s=[59.0, 62.0],
                sheet_grid=[2, 1],
                sheet_labels=True,
            )
            ledger.data["items"] += [bare, shown]
            return Path(render(ledger)).read_text(encoding="utf-8")

    def test_header_gallery_and_panels_follow_v2(self):
        page = self.render_two()
        self.assertIn('<header class="artifact-header">', page)
        self.assertIn('<span class="wordmark">engenheiro<span>de vídeo<b>.</b></span></span>', page)
        self.assertIn("<span>2 shots</span>", page)
        self.assertIn('<div class="gallery-head"><h2>Storyboard</h2>', page)
        self.assertIn('data-storyboard-mode="hover"', page)
        self.assertIn('id="pending-only"', page)
        # Source card, speech bubble and the three decisions.
        self.assertIn('<a class="source-link-card" href="https://www.youtube.com/watch?v=two"', page)
        self.assertIn('<span class="source-domain">youtube.com</span>', page)
        self.assertIn("<strong>Foguete &lt;decolando&gt;</strong>", page)
        self.assertIn("<p>clip 0:59.0–1:05.0 of 2:02.0</p>", page)
        self.assertIn("Why this was selected:", page)
        self.assertIn("Usage rights? not checked yet", page)
        self.assertIn('<span class="cut-position"', page)
        self.assertIn("Open original source ↗", page)
        self.assertIn('<span class="script-label">Script narration</span>', page)
        self.assertIn("“e o foguete saiu do chão”", page)
        # Três botões: "outra fonte" virou caixinha dentro de "Request changes"; o valor
        # exportado `alternative` segue existindo no JS/no schema.
        for decision in ("approved", "changes", "rejected"):
            self.assertIn(f'data-decision="{decision}"', page)
        self.assertNotIn('data-decision="alternative"', page)
        self.assertIn("<h2>Does this clip work?</h2>", page)
        self.assertIn("data-alternative", page)
        self.assertIn('title="Reject this clip and exclude it from the final download."', page)
        self.assertIn('class="comment-toggle"', page)
        # Presenter interval in MM:SS.ff and the first frame with a preview flagged.
        self.assertIn("00:59.00–01:05.00", page)
        self.assertIn('id="shot-0" data-preview="0"', page)
        self.assertIn('id="shot-1" data-preview="1"', page)
        self.assertIn('data-animated-thumb="previews/b.gif"', page)
        # The old toolbar and the "Revisar trecho" panel are gone.
        self.assertNotIn('<section class="review-toolbar">', page)
        self.assertNotIn("Revisar trecho", page)

    def test_brand_logo_is_not_cropped(self):
        page = self.render_two()
        css = page.split("</style>")[0]
        self.assertIn(".brand-logo{display:block;width:48px;height:48px;max-width:none;object-fit:contain", css)
        self.assertNotIn("brand-logo-frame", page)


class PanelStringsSnapshotTest(unittest.TestCase):
    """As frases do painel de decisão: mudá-las é decisão de produto, não refactor.

    Elas estavam sem teste nenhum — `REVIEW_PANEL` e as mensagens do `review.js`
    passaram três rodadas de UX copy sem rede. Este teste é a rede: quem trocar um
    texto vê o teste vermelho e decide de propósito.
    """

    ASSETS = ROOT / "assets"

    def page(self):
        return render_one(
            poster_path="previews/a-poster.jpg",
            contact_sheet_path="previews/a-sheet.jpg",
        )

    def test_panel_placeholders_and_labels_are_exactly_these(self):
        page = self.page()
        self.assertIn('placeholder="Describe what you want in one line…"', page)
        self.assertIn('<input data-suggestion type="url" placeholder="https://…">', page)
        self.assertIn("<h2>Does this clip work?</h2>", page)
        self.assertIn("<label>What to change<textarea data-comment", page)
        self.assertIn("Found another video? Paste the link (optional)", page)
        self.assertIn(" Find a different video</label>", page)
        self.assertIn(
            '<button class="confirm-review" type="button" hidden>Confirm change request</button>',
            page,
        )
        self.assertIn('<button class="comment-toggle" type="button" aria-expanded="false">Comment</button>', page)

    def test_the_three_decision_buttons_say_what_each_one_causes(self):
        page = self.page()
        self.assertIn('title="Approve this clip for the final download to your folder.">Approve</button>', page)
        self.assertIn(
            'title="Describe the changes you want (a different segment or video) and I will revise it.">Request changes</button>',
            page,
        )
        self.assertIn('title="Reject this clip and exclude it from the final download.">Reject</button>', page)

    def test_review_js_error_and_confirm_strings_are_exactly_these(self):
        js = (self.ASSETS / "review.js").read_text(encoding="utf-8")
        self.assertIn('status.textContent = "Describe what you want in one line.";', js)
        self.assertIn('wanted() === "changes" ? "Confirm change request" : "Confirm: find a different video"', js)
        self.assertIn('note("Could not save to the project; downloaded the file instead.");', js)
        self.assertIn('"Decisions saved in getbrolls-review.json (in your Downloads folder). "', js)
        self.assertIn('"Return to the chat and say where you saved the file."', js)
        self.assertIn('copy.textContent = "Copy path";', js)
        for state, label in (
            ("pending", "Awaiting decision"),
            ("approved", "Approved"),
            ("changes", "Changes requested"),
            ("rejected", "Rejected"),
            ("alternative", "Different video requested"),
        ):
            self.assertIn(f'{state}: "{label}"', js)

    def test_the_live_region_is_mounted_empty_at_load_without_a_timer(self):
        """Determinismo: a região viva existe desde o load e o export só troca o texto."""
        js = (self.ASSETS / "review.js").read_text(encoding="utf-8")
        self.assertIn('<p class="export-done" role="status" aria-live="polite"></p>', js)
        self.assertIn('const done = document.querySelector(".export-done");', js)
        # O `setTimeout(…, 100)` que atrasava o anúncio saiu de cena.
        self.assertNotIn("bar.after(done)", js)
        self.assertNotIn("}, 100);", js)
        # O único `setTimeout` que sobra é o `revokeObjectURL`, que não é anúncio.
        self.assertEqual(1, js.count("setTimeout("))
        self.assertIn("setTimeout(() => URL.revokeObjectURL(url), 1000);", js)
        # Vazia ela não pinta faixa nenhuma na página.
        self.assertIn(".export-done:empty{display:none}", (self.ASSETS / "review.css").read_text(encoding="utf-8"))

    def test_the_panel_column_has_no_fixed_width_that_would_overflow_375px(self):
        """375 px sem overflow: nada no painel pode ter largura fixa maior que isso."""
        import re

        css = (self.ASSETS / "review.css").read_text(encoding="utf-8")
        for value in re.findall(r"(?:^|[;{])\s*(?:min-)?width:\s*(\d+)px", css):
            self.assertLessEqual(int(value), 375, f"largura fixa de {value}px estoura a tela de 375 px")


class GalleryThumbnailFallbackTest(unittest.TestCase):
    """Sem imagem, a miniatura diz só a tarja; a frase longa fica no detalhe."""

    def test_the_gallery_fallback_is_the_badge_text_and_the_panel_keeps_the_long_one(self):
        page = render_page([{"title": "Sem imagem", "content": "<p>x</p>", "no_preview": True}])
        self.assertIn('<div class="thumbs"><span class="placeholder">image only</span>', page)
        self.assertIn('<span class="preview-badge">image only</span>', page)
        # O cartão da galeria não repete a explicação comprida.
        gallery = page.split('<div class="gallery">')[1].split("<template")[0]
        self.assertNotIn("Não consegui gerar o movimento", gallery)

    def test_the_detail_panel_still_carries_the_full_explanation(self):
        page = render_one()
        panel = page[page.index("<template") :]
        self.assertIn("Motion preview unavailable — open the original link", panel)
        self.assertNotIn("sem imagem da fonte", page)


if __name__ == "__main__":
    unittest.main()
