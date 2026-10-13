"""#55 public facts workflow: save, render, conflict, synthetic decision, delivery."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

import _isolation  # noqa: F401
from _cli import run_cli
from _media import skip_unless_ffmpeg
from _paths import ROOT
from test_graphics_review import _assign, _project, _render

from getbrolls.cli import FORMAT_GATE_SUBCOMMANDS, SUMMARIES
from getbrolls.graphics import graphics_content_sha256
from getbrolls.ledger import Ledger
from getbrolls.ledger import digest as file_digest
from getbrolls.runtime import READ_ONLY_COMMANDS

WORKER = ROOT / "tests" / "fixtures" / "graphics_worker.py"
ENV = {"GB_GRAPHICS_WORKER": str(WORKER)}
STATEMENT = "Synthetic fixture: I approve this exact version."
FACT_DECISION = "Synthetic editorial decision for this fixture only; not live acceptance."


def _write(path, text):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def _facts_payload(data_ref, digest_value, *, required=True, conflicts=None, value="18"):
    return {
        "schema_version": 1,
        "required": required,
        "values": [
            {
                "id": "primary",
                "value": value,
                "unit": "percent",
                "definition": "Share of sampled crossings that used the bridge.",
                "geography": "Menai Strait",
                "reference_date": "2024-06-01",
                "source_ids": ["src-1"],
            }
        ],
        "sources": [
            {
                "id": "src-1",
                "url": "https://example.invalid/bridge-count",
                "title": "Synthetic bridge count table",
                "reference_date": "2024-06-01",
                "terms_url": "https://example.invalid/terms",
                "conditions": "Finished-video use of the derived number.",
                "rendered_use": "permitted",
                "raw_redistribution": "permitted",
                "kind": "data",
                "data_ref": data_ref,
                "sha256": digest_value,
            }
        ],
        "conflicts": conflicts or [],
    }


def _conflict():
    return {
        "id": "c-bridge",
        "original_narration": "The count stands at twelve units.",
        "explanation": "Researched table shows 18 percent, not twelve units.",
        "source_ids": ["src-1"],
        "proposed_correction": "18 percent",
        "decision": None,
    }


def _facts_file(tmp, payload, name="facts-stat-01.json"):
    path = Path(tmp) / "brolls" / name
    _write(path, json.dumps(payload, ensure_ascii=False, indent=2))
    return path


def _data_file(tmp, body="crossings,18\n"):
    path = Path(tmp) / "brolls" / "graphics-data" / "bridge.csv"
    _write(path, body)
    return path, file_digest(path)


def _approve(tmp, occurrence="stat-01", version="v1"):
    return run_cli(
        "graphics-approve",
        "--occurrence",
        occurrence,
        "--version",
        version,
        "--by",
        "Human",
        "--statement",
        STATEMENT,
        project=tmp,
    )


def _graphics_item(status, occurrence):
    return next(row for row in status["graphics"]["items"] if row["occurrence_id"] == occurrence)


class GraphicsFactsCommandSurfaceTests(unittest.TestCase):
    def test_four_commands_are_documented_and_not_format_gate(self):
        for name in ("graphics-facts", "graphics-fact-resolve", "graphics-audio", "graphics-sound-import"):
            self.assertIn(name, SUMMARIES)
            self.assertNotIn(name, FORMAT_GATE_SUBCOMMANDS)
            self.assertNotIn(name, READ_ONLY_COMMANDS)
        self.assertIn("status", READ_ONLY_COMMANDS)


@skip_unless_ffmpeg
class GraphicsFactsWorkflowTests(unittest.TestCase):
    def test_numeric_source_caption_is_frozen_without_rewriting_narration(self):
        with tempfile.TemporaryDirectory() as tmp:
            _project(tmp)
            _assign(tmp, narration="Original spoken line.", timing="explicit", start="0", end="1.5")
            _, data_sha = _data_file(tmp)
            payload = _facts_payload("graphics-data/bridge.csv", data_sha)
            payload["sources"][0]["title"] = "Source: survey publication, June 2024"
            facts_path = _facts_file(tmp, payload)
            saved = run_cli("graphics-facts", "--occurrence", "stat-01", "--file", str(facts_path), project=tmp)
            self.assertEqual(payload["sources"][0]["title"], saved["occurrence"]["props"]["claim_note"])
            first = _render(tmp)["version"]
            self.assertEqual("Original spoken line.", first["assignment"]["narration"])
            self.assertEqual(payload["sources"][0]["title"], first["props"]["claim_note"])
            payload["sources"][0]["title"] = "Source: revised survey publication, July 2024"
            facts_path = _facts_file(tmp, payload)
            run_cli("graphics-facts", "--occurrence", "stat-01", "--file", str(facts_path), project=tmp)
            second = _render(tmp)["version"]
            self.assertNotEqual(first["props"]["claim_note"], second["props"]["claim_note"])
            ledger = Ledger(tmp, recover=False)
            self.assertEqual(first["props"], ledger.data["graphics"]["versions"][first["id"]]["props"])

    def test_facts_save_render_decision_delivery_and_isolated_second_scene(self):
        with tempfile.TemporaryDirectory() as tmp:
            _project(tmp)
            _assign(
                tmp,
                occurrence="stat-01",
                narration="The count stands at twelve units.",
                timing="explicit",
                start="0",
                end="1.5",
            )
            _assign(
                tmp,
                occurrence="stat-02",
                scene="second-stat",
                narration="A second scene keeps its own original line.",
                timing="explicit",
                start="0",
                end="1.5",
            )
            _, digest_value = _data_file(tmp)
            payload = _facts_payload(
                "graphics-data/bridge.csv",
                digest_value,
                conflicts=[_conflict()],
            )
            facts_path = _facts_file(tmp, payload)
            saved = run_cli(
                "graphics-facts",
                "--occurrence",
                "stat-01",
                "--file",
                str(facts_path),
                project=tmp,
            )
            self.assertEqual("The count stands at twelve units.", saved["occurrence"]["narration"])
            self.assertNotEqual("sourced", saved["occurrence"]["props"]["claim_status"])
            status = run_cli("status", project=tmp)
            item = next(row for row in status["graphics"]["items"] if row["occurrence_id"] == "stat-01")
            other = next(row for row in status["graphics"]["items"] if row["occurrence_id"] == "stat-02")
            self.assertIn("facts_not_ready", item["reasons"])
            self.assertNotIn("facts_not_ready", other["reasons"])
            self.assertIn("Menai Strait", json.dumps(item["facts"]))
            resolved = run_cli(
                "graphics-fact-resolve",
                "--occurrence",
                "stat-01",
                "--conflict",
                "c-bridge",
                "--decision",
                "accept_correction",
                "--by",
                "Editor",
                "--statement",
                FACT_DECISION,
                project=tmp,
            )
            self.assertEqual("accept_correction", resolved["decision"])
            occ = Ledger(tmp, recover=False).data["graphics"]["occurrences"]["stat-01"]
            self.assertEqual("The count stands at twelve units.", occ["narration"])
            self.assertEqual("18", occ["props"]["value"])
            self.assertEqual("percent", occ["props"]["unit"])
            self.assertEqual("sourced", occ["props"]["claim_status"])
            rendered = _render(tmp, "stat-01")
            self.assertEqual("v1", rendered["version"]["id"])
            assignment = rendered["version"]["assignment"]
            self.assertEqual("The count stands at twelve units.", assignment["narration"])
            self.assertIn("graphics-data/bridge.csv", rendered["version"]["fingerprints"]["inputs"])
            run_cli("review", project=tmp)
            page = (Path(tmp) / "brolls" / "review.html").read_text(encoding="utf-8")
            self.assertIn("Displayed-fact evidence", page)
            self.assertIn("Menai Strait", page)
            self.assertIn(FACT_DECISION, page)
            self.assertIn("The count stands at twelve units.", page)
            _approve(tmp, version="v1")
            delivered = run_cli("deliver", project=tmp)
            self.assertTrue(delivered.get("graphics") or delivered)
            pkg = Path(tmp) / "entrega" / "graphics" / "numeric-stat" / "stat-01" / "v1"
            self.assertTrue((pkg / "assignment.json").is_file())
            self.assertTrue((pkg / "refs" / "graphics-data" / "bridge.csv").is_file())
            self.assertNotIn("narration/private", json.dumps((pkg / "rerender.json").read_text(encoding="utf-8")))
            second = _render(tmp, "stat-02")
            self.assertEqual("v2", second["version"]["id"])
            self.assertEqual("A second scene keeps its own original line.", second["occurrence"]["narration"])
            self.assertNotIn("facts", second["version"]["assignment"])

    def test_keep_scenario_preserves_original_value_and_blocks_defer(self):
        with tempfile.TemporaryDirectory() as tmp:
            _project(tmp)
            _assign(tmp, timing="explicit", start="0", end="1.5")
            _data_file(tmp)
            digest_value = file_digest(Path(tmp) / "brolls" / "graphics-data" / "bridge.csv")
            facts_path = _facts_file(
                tmp, _facts_payload("graphics-data/bridge.csv", digest_value, conflicts=[_conflict()])
            )
            run_cli("graphics-facts", "--occurrence", "stat-01", "--file", str(facts_path), project=tmp)
            kept = run_cli(
                "graphics-fact-resolve",
                "--occurrence",
                "stat-01",
                "--conflict",
                "c-bridge",
                "--decision",
                "keep_scenario",
                "--by",
                "Editor",
                "--statement",
                FACT_DECISION,
                project=tmp,
            )
            occ = Ledger(tmp, recover=False).data["graphics"]["occurrences"]["stat-01"]
            self.assertEqual("—", occ["props"]["value"])
            self.assertEqual("units", occ["props"]["unit"])
            self.assertNotEqual("sourced", occ["props"]["claim_status"])
            self.assertEqual("The count stands at twelve units.", occ["narration"])
            run_cli("review", project=tmp)
            page = (Path(tmp) / "brolls" / "review.html").read_text(encoding="utf-8")
            self.assertIn("Editor kept the original scenario", page)
            self.assertEqual("keep_scenario", kept["decision"])
            deferred = _facts_file(
                tmp,
                _facts_payload("graphics-data/bridge.csv", digest_value, conflicts=[_conflict()]),
                name="facts-defer.json",
            )
            run_cli("graphics-facts", "--occurrence", "stat-01", "--file", str(deferred), project=tmp)
            run_cli(
                "graphics-fact-resolve",
                "--occurrence",
                "stat-01",
                "--conflict",
                "c-bridge",
                "--decision",
                "defer",
                "--by",
                "Editor",
                "--statement",
                FACT_DECISION,
                project=tmp,
            )
            status = run_cli("status", project=tmp)
            item = next(row for row in status["graphics"]["items"] if row["occurrence_id"] == "stat-01")
            self.assertFalse(item["deliverable"])
            self.assertIn("facts_not_ready", item["reasons"])

    def test_changed_facts_need_fresh_review_and_retain_old_signature(self):
        with tempfile.TemporaryDirectory() as tmp:
            _project(tmp)
            _assign(tmp, timing="explicit", start="0", end="1.5")
            first = _render(tmp)
            old_hash = first["version"]["fingerprints"]["assignment_sha256"]
            old_content = graphics_content_sha256(first["version"])
            _, digest_value = _data_file(tmp)
            facts_path = _facts_file(tmp, _facts_payload("graphics-data/bridge.csv", digest_value, conflicts=[]))
            run_cli("graphics-facts", "--occurrence", "stat-01", "--file", str(facts_path), project=tmp)
            ledger = Ledger(tmp, recover=False)
            v1 = ledger.data["graphics"]["versions"]["v1"]
            self.assertEqual(old_hash, v1["fingerprints"]["assignment_sha256"])
            self.assertEqual(old_content, graphics_content_sha256(v1))
            status = run_cli("status", project=tmp)
            item = next(row for row in status["graphics"]["items"] if row["occurrence_id"] == "stat-01")
            self.assertIn("assignment_drift", item["reasons"])
            second = _render(tmp)
            self.assertEqual("v2", second["version"]["id"])
            self.assertEqual("v1", second["version"]["parent"])
            self.assertNotEqual(old_content, graphics_content_sha256(second["version"]))
            self.assertIsNone(second["version"]["approval"])
            still = Ledger(tmp, recover=False).data["graphics"]["versions"]["v1"]
            self.assertEqual(old_content, graphics_content_sha256(still))

    def test_complete_then_unready_restores_original_props_and_keeps_hashes(self):
        with tempfile.TemporaryDirectory() as tmp:
            _project(tmp)
            _assign(tmp, timing="explicit", start="0", end="1.5")
            original = Ledger(tmp, recover=False).data["graphics"]["occurrences"]["stat-01"]["props"]
            original_value = original["value"]
            original_unit = original["unit"]
            original_claim = original["claim_status"]
            _, digest_value = _data_file(tmp)
            ready_path = _facts_file(tmp, _facts_payload("graphics-data/bridge.csv", digest_value, conflicts=[]))
            run_cli("graphics-facts", "--occurrence", "stat-01", "--file", str(ready_path), project=tmp)
            sourced = Ledger(tmp, recover=False).data["graphics"]["occurrences"]["stat-01"]
            self.assertEqual("sourced", sourced["props"]["claim_status"])
            self.assertEqual("18", sourced["props"]["value"])
            first = _render(tmp)
            old_content = graphics_content_sha256(first["version"])
            unready_path = _facts_file(
                tmp,
                _facts_payload("graphics-data/bridge.csv", digest_value, conflicts=[_conflict()]),
                name="facts-unready.json",
            )
            run_cli("graphics-facts", "--occurrence", "stat-01", "--file", str(unready_path), project=tmp)
            occ = Ledger(tmp, recover=False).data["graphics"]["occurrences"]["stat-01"]
            self.assertEqual(original_value, occ["props"]["value"])
            self.assertEqual(original_unit, occ["props"]["unit"])
            self.assertEqual(original_claim, occ["props"]["claim_status"])
            self.assertNotEqual("sourced", occ["props"]["claim_status"])
            self.assertEqual("The count stands at twelve units.", occ["narration"])
            status = run_cli("status", project=tmp)
            item = next(row for row in status["graphics"]["items"] if row["occurrence_id"] == "stat-01")
            self.assertIn("facts_not_ready", item["reasons"])
            v1 = Ledger(tmp, recover=False).data["graphics"]["versions"]["v1"]
            self.assertEqual(old_content, graphics_content_sha256(v1))
            self.assertEqual("sourced", v1["assignment"]["props"]["claim_status"])

    def test_optional_unresolved_and_deferred_conflicts_block_delivery(self):
        with tempfile.TemporaryDirectory() as tmp:
            _project(tmp)
            _assign(
                tmp,
                occurrence="stat-01",
                narration="The count stands at twelve units.",
                timing="explicit",
                start="0",
                end="1.5",
            )
            _assign(
                tmp,
                occurrence="stat-02",
                scene="second-stat",
                narration="A second scene keeps its own original line.",
                timing="explicit",
                start="0",
                end="1.5",
            )
            _, digest_value = _data_file(tmp)
            payload = _facts_payload(
                "graphics-data/bridge.csv",
                digest_value,
                required=False,
                conflicts=[_conflict()],
            )
            run_cli(
                "graphics-facts",
                "--occurrence",
                "stat-01",
                "--file",
                str(_facts_file(tmp, payload)),
                project=tmp,
            )
            occ = Ledger(tmp, recover=False).data["graphics"]["occurrences"]["stat-01"]
            self.assertFalse(occ["facts"]["required"])
            self.assertEqual("The count stands at twelve units.", occ["narration"])
            first = _render(tmp, "stat-01")
            second = _render(tmp, "stat-02")
            _approve(tmp, occurrence="stat-01", version=first["version"]["id"])
            _approve(tmp, occurrence="stat-02", version=second["version"]["id"])
            status = run_cli("status", project=tmp)
            blocked = _graphics_item(status, "stat-01")
            other = _graphics_item(status, "stat-02")
            self.assertTrue(blocked["approved"])
            self.assertFalse(blocked["deliverable"])
            self.assertIn("facts_not_ready", blocked["reasons"])
            self.assertTrue(any("unresolved" in reason for reason in blocked["reasons"]))
            self.assertTrue(other["deliverable"])
            delivered = run_cli("deliver", project=tmp)
            skipped = json.dumps(delivered.get("graphics_skipped") or [])
            self.assertIn("stat-01", skipped)
            self.assertIn("facts_not_ready", skipped)
            self.assertFalse(
                (Path(tmp) / "entrega" / "graphics" / "numeric-stat" / "stat-01" / first["version"]["id"]).is_dir()
            )
            self.assertTrue(
                (Path(tmp) / "entrega" / "graphics" / "second-stat" / "stat-02" / second["version"]["id"]).is_dir()
            )
            deferred = _facts_file(
                tmp,
                _facts_payload(
                    "graphics-data/bridge.csv",
                    digest_value,
                    required=False,
                    conflicts=[_conflict()],
                ),
                name="facts-optional-defer.json",
            )
            run_cli("graphics-facts", "--occurrence", "stat-01", "--file", str(deferred), project=tmp)
            run_cli(
                "graphics-fact-resolve",
                "--occurrence",
                "stat-01",
                "--conflict",
                "c-bridge",
                "--decision",
                "defer",
                "--by",
                "Editor",
                "--statement",
                FACT_DECISION,
                project=tmp,
            )
            self.assertFalse(Ledger(tmp, recover=False).data["graphics"]["occurrences"]["stat-01"]["facts"]["required"])
            refreshed = _render(tmp, "stat-01")
            _approve(tmp, occurrence="stat-01", version=refreshed["version"]["id"])
            after = _graphics_item(run_cli("status", project=tmp), "stat-01")
            self.assertFalse(after["deliverable"])
            self.assertIn("facts_not_ready", after["reasons"])
            self.assertTrue(any("deferred" in reason for reason in after["reasons"]))

    def test_optional_stale_conflict_blocks_and_accepted_decision_delivers(self):
        with tempfile.TemporaryDirectory() as tmp:
            _project(tmp)
            _assign(tmp, timing="explicit", start="0", end="1.5")
            _, digest_value = _data_file(tmp)
            payload = _facts_payload(
                "graphics-data/bridge.csv",
                digest_value,
                required=False,
                conflicts=[_conflict()],
            )
            run_cli(
                "graphics-facts",
                "--occurrence",
                "stat-01",
                "--file",
                str(_facts_file(tmp, payload)),
                project=tmp,
            )
            resolved = run_cli(
                "graphics-fact-resolve",
                "--occurrence",
                "stat-01",
                "--conflict",
                "c-bridge",
                "--decision",
                "accept_correction",
                "--by",
                "Editor",
                "--statement",
                FACT_DECISION,
                project=tmp,
            )
            decision = resolved["facts"]["conflicts"][0]["decision"]
            stale_payload = _facts_payload(
                "graphics-data/bridge.csv",
                digest_value,
                required=False,
                conflicts=[_conflict()],
                value="19",
            )
            stale_payload["conflicts"][0]["decision"] = decision
            run_cli(
                "graphics-facts",
                "--occurrence",
                "stat-01",
                "--file",
                str(_facts_file(tmp, stale_payload, name="facts-stale.json")),
                project=tmp,
            )
            stale_occ = Ledger(tmp, recover=False).data["graphics"]["occurrences"]["stat-01"]
            self.assertFalse(stale_occ["facts"]["required"])
            self.assertEqual("The count stands at twelve units.", stale_occ["narration"])
            stale_version = _render(tmp)
            _approve(tmp, version=stale_version["version"]["id"])
            stale_item = _graphics_item(run_cli("status", project=tmp), "stat-01")
            self.assertTrue(stale_item["approved"])
            self.assertFalse(stale_item["deliverable"])
            self.assertTrue(any("stale evidence" in reason for reason in stale_item["reasons"]))
            accepted = _facts_payload(
                "graphics-data/bridge.csv",
                digest_value,
                required=False,
                conflicts=[_conflict()],
            )
            run_cli(
                "graphics-facts",
                "--occurrence",
                "stat-01",
                "--file",
                str(_facts_file(tmp, accepted, name="facts-accepted.json")),
                project=tmp,
            )
            run_cli(
                "graphics-fact-resolve",
                "--occurrence",
                "stat-01",
                "--conflict",
                "c-bridge",
                "--decision",
                "accept_correction",
                "--by",
                "Editor",
                "--statement",
                FACT_DECISION,
                project=tmp,
            )
            ready_occ = Ledger(tmp, recover=False).data["graphics"]["occurrences"]["stat-01"]
            self.assertEqual("18", ready_occ["props"]["value"])
            self.assertEqual("sourced", ready_occ["props"]["claim_status"])
            ready = _render(tmp)
            _approve(tmp, version=ready["version"]["id"])
            ready_item = _graphics_item(run_cli("status", project=tmp), "stat-01")
            self.assertTrue(ready_item["deliverable"])
            run_cli("deliver", project=tmp)
            pkg = Path(tmp) / "entrega" / "graphics" / "numeric-stat" / "stat-01" / ready["version"]["id"]
            self.assertTrue((pkg / "assignment.json").is_file())

    def test_optional_incomplete_without_conflict_stays_deliverable(self):
        with tempfile.TemporaryDirectory() as tmp:
            _project(tmp)
            _assign(tmp, timing="explicit", start="0", end="1.5")
            _, digest_value = _data_file(tmp)
            payload = _facts_payload(
                "graphics-data/bridge.csv",
                digest_value,
                required=False,
                conflicts=[],
            )
            payload["values"][0]["definition"] = ""
            run_cli(
                "graphics-facts",
                "--occurrence",
                "stat-01",
                "--file",
                str(_facts_file(tmp, payload, name="facts-optional-draft.json")),
                project=tmp,
            )
            occ = Ledger(tmp, recover=False).data["graphics"]["occurrences"]["stat-01"]
            self.assertFalse(occ["facts"]["required"])
            self.assertNotEqual("sourced", occ["props"]["claim_status"])
            rendered = _render(tmp)
            _approve(tmp, version=rendered["version"]["id"])
            item = _graphics_item(run_cli("status", project=tmp), "stat-01")
            self.assertIn("facts_not_ready", item["reasons"])
            self.assertFalse(any("conflict" in reason.lower() for reason in item["reasons"]))
            self.assertTrue(item["deliverable"])
            run_cli("deliver", project=tmp)
            pkg = Path(tmp) / "entrega" / "graphics" / "numeric-stat" / "stat-01" / rendered["version"]["id"]
            self.assertTrue((pkg / "assignment.json").is_file())

    def test_malicious_file_and_foreign_paths_are_rejected(self):
        with tempfile.TemporaryDirectory() as outer:
            outer_path = Path(outer)
            project = outer_path / "project"
            project.mkdir()
            _project(project)
            _assign(project)
            sentinel = outer_path / "external-sentinel.txt"
            sentinel.write_text("keep", encoding="utf-8")
            outside = outer_path / "foreign-facts.json"
            outside.write_text("{}", encoding="utf-8")
            denied = run_cli(
                "graphics-facts",
                "--occurrence",
                "stat-01",
                "--file",
                str(outside),
                project=project,
                expect=2,
            )
            self.assertIn("project", json.dumps(denied).lower())
            folder = project / "brolls" / "facts-dir"
            folder.mkdir()
            as_dir = run_cli(
                "graphics-facts",
                "--occurrence",
                "stat-01",
                "--file",
                str(folder),
                project=project,
                expect=2,
            )
            self.assertIn("regular file", json.dumps(as_dir).lower())
            huge = project / "brolls" / "huge.json"
            huge.write_bytes(b"{" + b"a" * 2_000_001 + b"}")
            oversized = run_cli(
                "graphics-facts",
                "--occurrence",
                "stat-01",
                "--file",
                str(huge),
                project=project,
                expect=2,
            )
            self.assertIn("2 MB", json.dumps(oversized))
            status = run_cli("status", project=project)
            self.assertIn("graphics", status)
            self.assertEqual("keep", sentinel.read_text(encoding="utf-8"))
            self.assertTrue(outside.is_file())


if __name__ == "__main__":
    unittest.main()
