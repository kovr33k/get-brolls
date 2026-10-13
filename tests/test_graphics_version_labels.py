"""Storyboard version numbers belong to an occurrence, not the project render counter."""

import copy
import tempfile
import unittest
from html.parser import HTMLParser
from pathlib import Path

import _isolation  # noqa: F401
from _cli import run_cli
from _media import skip_unless_ffmpeg
from test_graphics_review import _approve, _assign, _project, _render, _review_payload, _write_review

from getbrolls.graphics import _occurrence_storyboard_versions, _storyboard_version_tools
from getbrolls.ledger import Ledger


class VersionOptions(HTMLParser):
    def __init__(self):
        super().__init__()
        self.cards = {}
        self.card = None
        self.select = None
        self.option = None

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "article" and "data-occurrence" in attrs:
            self.card = attrs["data-occurrence"]
            self.cards[self.card] = {}
        if tag == "select" and self.card:
            for kind in ("display", "compare"):
                if "data-graphics-" + kind in attrs:
                    self.select = kind
                    self.cards[self.card][kind] = []
        if tag == "option" and self.select:
            self.option = {"id": attrs.get("value"), "label": ""}
            self.cards[self.card][self.select].append(self.option)

    def handle_data(self, data):
        if self.option is not None:
            self.option["label"] += data

    def handle_endtag(self, tag):
        if tag == "option":
            self.option = None
        if tag == "select":
            self.select = None
        if tag == "article":
            self.card = None


class VersionLabelOrderTests(unittest.TestCase):
    def test_saved_versions_keep_creation_order_after_nine_and_skip_failed_attempts(self):
        versions = {
            "v10": {"id": "v10", "occurrence_id": "piece", "status": "complete", "artifact": {}},
            "v8": {"id": "v8", "occurrence_id": "piece", "status": "failed"},
            "v9": {"id": "v9", "occurrence_id": "piece", "status": "complete", "artifact": {}},
        }
        before = copy.deepcopy(versions)
        complete, failed = _occurrence_storyboard_versions(versions, "piece")
        self.assertEqual(["v9", "v10"], [version["id"] for version in complete])
        self.assertEqual(["v8"], [version["id"] for version in failed])
        parser = VersionOptions()
        parser.feed(
            '<article data-occurrence="piece">' + "".join(_storyboard_version_tools(complete, "v10")) + "</article>"
        )
        self.assertEqual(
            [{"id": "v9", "label": "v1"}, {"id": "v10", "label": "v2"}],
            parser.cards["piece"]["display"],
        )
        self.assertEqual(before, versions)


@skip_unless_ffmpeg
class PieceVersionReviewTests(unittest.TestCase):
    def test_interleaved_occurrences_number_their_own_versions_and_keep_review_targets(self):
        with tempfile.TemporaryDirectory() as tmp:
            _project(tmp)
            for occurrence in ("first", "second"):
                _assign(tmp, occurrence=occurrence, scene="recurring-scene", duration=1.5)
                _render(tmp, occurrence=occurrence)
            _approve(tmp, occurrence="second", version="v2")
            for occurrence in ("first", "second"):
                _assign(
                    tmp, occurrence=occurrence, scene="recurring-scene", duration=1.5, narration="Revised " + occurrence
                )
                _render(tmp, occurrence=occurrence)
            before = copy.deepcopy(Ledger(tmp, recover=False).data["graphics"])
            payload = _review_payload(tmp)
            self.assertEqual(before, Ledger(tmp, recover=False).data["graphics"])
            parser = VersionOptions()
            page = (Path(tmp) / "brolls/review.html").read_text(encoding="utf-8")
            parser.feed(page)
            for occurrence, ids in (("first", ["v1", "v3"]), ("second", ["v2", "v4"])):
                self.assertEqual(
                    [{"id": ident, "label": label} for ident, label in zip(ids, ("v1", "v2"), strict=True)],
                    parser.cards[occurrence]["display"],
                )
                self.assertEqual(
                    [{"id": "", "label": "None"}, *parser.cards[occurrence]["display"]],
                    parser.cards[occurrence]["compare"],
                )
            self.assertEqual(2, page.count('<p class="graphics-version-label">v1</p>'))
            self.assertEqual(2, page.count('<p class="graphics-version-label">v2</p>'))
            self.assertIn('data-version="v4"', page)
            self.assertIn("Saved ID v4", page)
            payload["graphics"] = [row for row in payload["graphics"] if row["version"] == "v4"]
            payload["graphics"][0].update(state="changes", comment="Synthetic fixture: revise this exact second piece.")
            run_cli("import-review", "--file", _write_review(tmp, payload), "--by", "Synthetic reviewer", project=tmp)
            graphics = Ledger(tmp, recover=False).data["graphics"]
            self.assertEqual("v4", graphics["requests"][-1]["reviewed_version"])
            self.assertEqual("second", graphics["requests"][-1]["occurrence_id"])
            self.assertEqual(before["versions"]["v2"]["approval"], graphics["versions"]["v2"]["approval"])
            self.assertEqual(before["versions"]["v3"], graphics["versions"]["v3"])


if __name__ == "__main__":
    unittest.main()
