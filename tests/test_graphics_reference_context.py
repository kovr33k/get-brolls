"""Active reference journeys and fixed shared outcomes through HTTP and CLI."""

from __future__ import annotations

import copy
import json
import tempfile
import unittest
import urllib.error
from pathlib import Path

import _isolation  # noqa: F401
from _cli import run_cli
from _media import skip_unless_ffmpeg, synth_image
from test_graphics_media_workflow import _background_payload
from test_graphics_mixed_references import analysis_file, inspect, mixed_request, upload_media
from test_graphics_references import post, serving
from test_graphics_review import _assign, _project, _render, _review_payload, _version_hashes, _write_review

from getbrolls import serve
from getbrolls.ledger import Ledger


def current_row(project, occurrence="stat-01"):
    payload = _review_payload(project)
    return payload, next(row for row in payload["graphics"] if row["current"] and row["occurrence_id"] == occurrence)


def edit(row, prompt, refs=None, scope="scene"):
    row.update(state="changes", comment=prompt, scope=scope, referenceBase=row["activeReferences"]["sha256"])
    row.pop("reference", None)
    row.pop("reference_application", None)
    row.pop("shared_request_id", None)
    row["references"] = copy.deepcopy(row["activeReferences"]["references"] if refs is None else refs)
    return row


def save_import(project, payload):
    for row in payload["graphics"]:
        if row["state"] == "approved":
            row["state"] = "pending"  # unchanged approvals are not resubmitted by the browser
    before = (Path(project) / "brolls/manifest.json").read_bytes()
    with serving(project) as (server, url):
        answer = post(url + serve.SAVE_PATH, json.dumps(payload).encode(), server.save_token)
    assert before == (Path(project) / "brolls/manifest.json").read_bytes(), "Save must stay idle."
    run_cli("import-review", "--file", answer["path"], "--by", "Synthetic editor", project=project)
    return Ledger(project, recover=False).data["graphics"]["requests"][-1], answer["path"]


def complete(project, request, version):
    return run_cli(
        "graphics-request-complete",
        "--request",
        request["id"],
        "--version",
        version,
        "--outcome",
        "Applied the actual instructions in this synthetic fixture.",
        project=project,
    )


def apply_image(project, request):
    path = Path(project) / "brolls/active-analysis.json"
    path.write_text(
        json.dumps(
            {
                "effective_instructions": "Use blue accents, retain data and the original narration.",
                "analyses": [
                    {"label": ref["label"], "analysis": "Blue accent palette.", "limitations": "Still image only."}
                    for ref in request["references"]
                ],
            }
        ),
        encoding="utf-8",
    )
    return run_cli("graphics-reference-apply", "--request", request["id"], "--file", path, project=project)


@skip_unless_ffmpeg
class GraphicsReferenceContextTests(unittest.TestCase):
    def test_mixed_text_followup_reuses_inspection_origin_and_preserves_frozen_history(self):
        with tempfile.TemporaryDirectory() as project:
            first, refs, _ = mixed_request(project)
            record = inspect(project, first, "--start", "3", "--end", "5")
            path = analysis_file(project, record)
            run_cli("graphics-reference-apply", "--request", first["id"], "--file", path, project=project)
            _render(project)
            complete(project, first, "v1")
            old = _version_hashes(project, "numeric-stat", "v1")
            payload, row = current_row(project)
            edit(row, "Make the title larger; keep the earlier palette and inspected motion.")
            follow, saved = save_import(project, payload)
            self.assertEqual(refs, follow["references"])
            result = run_cli(
                "graphics-reference-apply",
                "--request",
                follow["id"],
                "--analysis",
                "Larger title; preserve the blue palette, earlier motion, facts and narration.",
                project=project,
            )
            context = result["reference_context"]
            self.assertEqual(first["id"], context["analyses"][1]["basis"]["request_id"])
            self.assertEqual(record, context["analyses"][1]["inspection"])
            self.assertEqual(2, len(context["instruction_history"]))
            _render(project)
            complete(project, follow, "v2")
            run_cli("import-review", "--file", saved, "--by", "Synthetic editor", project=project)
            self.assertEqual(2, len(Ledger(project, recover=False).data["graphics"]["requests"]))
            self.assertEqual(old, _version_hashes(project, "numeric-stat", "v1"))
            payload, current = current_row(project)
            historical = next(row for row in payload["graphics"] if row["version"] == "v1")
            self.assertEqual(refs, historical["frozenReferences"])
            self.assertEqual(current["activeReferences"], historical["activeReferences"])
            self.assertIsNone(Ledger(project, recover=False).data["graphics"]["versions"]["v2"]["approval"])

    def test_remove_replace_empty_and_stale_base_cannot_overwrite_newer_set(self):
        with tempfile.TemporaryDirectory() as project:
            _project(project)
            _assign(project)
            payload, row = current_row(project)
            image = Path(project) / "same.png"
            synth_image(image, color="blue")
            with serving(project) as (server, url):
                original = upload_media(url, server.save_token, row, image, "image", "R1")
            edit(row, "Use R1 blue accents, keep our data.", [original])
            first, saved = save_import(project, payload)
            stale = copy.deepcopy(payload)
            stale["graphics"][0]["comment"] = "Conflicting old-tab edit."
            before = Ledger(project, recover=False).path.read_bytes()
            with serving(project) as (server, url), self.assertRaises(urllib.error.HTTPError):
                post(url + serve.SAVE_PATH, json.dumps(stale).encode(), server.save_token)
            run_cli(
                "import-review",
                "--file",
                _write_review(project, stale),
                "--by",
                "Synthetic editor",
                project=project,
                expect=2,
            )
            self.assertEqual(before, Ledger(project, recover=False).path.read_bytes())
            run_cli("import-review", "--file", saved, "--by", "Synthetic editor", project=project)
            apply_image(project, first)
            _render(project)
            complete(project, first, "v1")
            frozen = _version_hashes(project, "numeric-stat", "v1")
            payload, row = current_row(project)
            image.unlink()
            synth_image(image, color="green")
            with serving(project) as (server, url):
                replacement = upload_media(url, server.save_token, row, image, "image", "R1")
            self.assertEqual(original["name"], replacement["name"])
            self.assertNotEqual(original["sha256"], replacement["sha256"])
            edit(row, "Replace R1; use its green palette and retain the larger labels.", [replacement])
            changed, _ = save_import(project, payload)
            run_cli(
                "graphics-reference-apply",
                "--request",
                changed["id"],
                "--analysis",
                "Green palette.",
                project=project,
                expect=2,
            )
            apply_image(project, changed)
            _render(project)
            complete(project, changed, "v2")
            payload, row = current_row(project)
            edit(row, "Remove R1 from future style references; retain our data and use neutral labels.", [])
            removed, _ = save_import(project, payload)
            self.assertEqual([], removed["references"])
            run_cli(
                "graphics-reference-apply",
                "--request",
                removed["id"],
                "--analysis",
                "Neutral labels; original facts and narration retained.",
                project=project,
            )
            _render(project)
            complete(project, removed, "v3")
            self.assertEqual(frozen, _version_hashes(project, "numeric-stat", "v1"))
            active = current_row(project)[1]["activeReferences"]
            self.assertEqual([], active["references"])
            self.assertEqual(3, active["instruction_count"])

    def test_fixed_shared_subset_exceptions_retry_and_local_approvals(self):
        with tempfile.TemporaryDirectory() as project:
            _project(project)
            for oid in ("stat-01", "stat-02", "stat-03"):
                _assign(project, occurrence=oid, scene="scene-" + oid)
            local_payload, local_row = current_row(project, "stat-02")
            edit(local_row, "Use red labels and a larger title; preserve the original narration.", [])
            local, _ = save_import(project, local_payload)
            run_cli(
                "graphics-reference-apply",
                "--request",
                local["id"],
                "--analysis",
                "Red labels and larger title; original narration.",
                project=project,
            )
            _render(project, "stat-02")
            local_version = Ledger(project, recover=False).data["graphics"]["occurrences"]["stat-02"]["current_version"]
            complete(project, local, local_version)
            _render(project, "stat-03")
            untouched_version = Ledger(project, recover=False).data["graphics"]["occurrences"]["stat-03"][
                "current_version"
            ]
            run_cli(
                "graphics-approve",
                "--occurrence",
                "stat-03",
                "--version",
                untouched_version,
                "--by",
                "Synthetic editor",
                "--statement",
                "Synthetic fixture approval only.",
                project=project,
            )
            untouched = copy.deepcopy(Ledger(project, recover=False).data["graphics"]["versions"][untouched_version])
            payload, row = current_row(project)
            edit(
                row,
                "Use neutral labels in scenes 1 and 2; keep scene 2's larger title. Leave scene 3 alone.",
                [],
                "shared",
            )
            source, _ = save_import(project, payload)
            run_cli(
                "graphics-reference-apply",
                "--request",
                source["id"],
                "--analysis",
                "Neutral labels.",
                project=project,
                expect=2,
            )
            path = Path(project) / "brolls/scope.json"
            path.write_text(json.dumps({"resolution": "Ambiguous all scenes."}), encoding="utf-8")
            run_cli("graphics-reference-scope", "--request", source["id"], "--file", path, project=project, expect=2)
            spec = {
                "resolution": "Only scenes 1 and 2, retaining scene 2's larger title.",
                "targets": [
                    {"occurrence_id": "stat-01", "references": [], "instruction": "Neutral labels."},
                    {
                        "occurrence_id": "stat-02",
                        "references": [],
                        "instruction": "Neutral labels; preserve the larger title.",
                    },
                ],
            }
            path.write_text(json.dumps(spec), encoding="utf-8")
            result = run_cli("graphics-reference-scope", "--request", source["id"], "--file", path, project=project)
            self.assertEqual("incomplete", result["scope"]["state"])
            _assign(project, occurrence="stat-04", scene="scene-4")
            handoff = run_cli(
                "graphics-handoff", "--occurrence", source["occurrence_id"], "--request", source["id"], project=project
            )
            packet = json.loads((Path(project) / "brolls" / handoff["packet_ref"]).read_text(encoding="utf-8"))
            self.assertEqual(2, len(packet["reference_scopes"][0]["targets"]))
            self.assertEqual(source["reference_change"]["result"], packet["active_references"]["sha256"])
            self.assertTrue(
                run_cli("graphics-reference-scope", "--request", source["id"], "--file", path, project=project)[
                    "idempotent"
                ]
            )
            requests = Ledger(project, recover=False).data["graphics"]["requests"][1:]
            self.assertEqual(2, len(requests))
            for index, request in enumerate(requests, 1):
                run_cli(
                    "graphics-reference-apply",
                    "--request",
                    request["id"],
                    "--analysis",
                    "Neutral labels; preserve existing facts and scene-specific title size.",
                    project=project,
                )
                _render(project, request["occurrence_id"])
                version = Ledger(project, recover=False).data["graphics"]["occurrences"][request["occurrence_id"]][
                    "current_version"
                ]
                complete(project, request, version)
                status = run_cli("status", project=project)["graphics"]
                self.assertEqual(
                    "complete" if index == len(requests) else "incomplete", status["reference_scopes"][0]["state"]
                )
            graphics = Ledger(project, recover=False).data["graphics"]
            self.assertNotIn("stat-03", graphics["reference_states"])
            self.assertNotIn("stat-04", graphics["reference_states"])
            self.assertEqual(untouched, graphics["versions"][untouched_version])
            state = graphics["reference_states"]["stat-02"]
            self.assertEqual(local["text"], state["revisions"][state["current"]]["instructions"][0]["prompt"])
            self.assertEqual("Neutral labels; preserve the larger title.", requests[1]["reference_application"])
            self.assertTrue(
                run_cli("graphics-reference-scope", "--request", source["id"], "--file", path, project=project)[
                    "idempotent"
                ]
            )
            spec["targets"].append({"occurrence_id": "stat-04", "references": [], "instruction": "New target."})
            path.write_text(json.dumps(spec), encoding="utf-8")
            run_cli("graphics-reference-scope", "--request", source["id"], "--file", path, project=project, expect=2)

    def test_shared_conflict_keeps_fixed_group_incomplete_and_other_scene_untouched(self):
        with tempfile.TemporaryDirectory() as project:
            _project(project)
            _assign(project)
            _assign(project, occurrence="stat-02", scene="other-scene")
            payload, row = current_row(project)
            edit(row, "Neutral labels for these two scenes.", [], "shared")
            source, _ = save_import(project, payload)
            path = Path(project) / "brolls/scope.json"
            spec = {
                "resolution": "Exactly two registered occurrences.",
                "targets": [
                    {"occurrence_id": oid, "references": [], "instruction": "Neutral labels."}
                    for oid in ("stat-01", "stat-02")
                ],
            }
            path.write_text(json.dumps(spec), encoding="utf-8")
            run_cli("graphics-reference-scope", "--request", source["id"], "--file", path, project=project)
            payload, row = current_row(project, "stat-02")
            edit(row, "Keep a local exception: larger white labels.", [])
            row.pop("reference_application", None)
            row.pop("shared_request_id", None)
            local, _ = save_import(project, payload)
            status = run_cli("status", project=project)["graphics"]["reference_scopes"][0]
            self.assertEqual("conflict", status["state"])
            self.assertEqual("reference_context_mismatch", status["targets"][1]["reason"])
            child = Ledger(project, recover=False).data["graphics"]["requests"][1]
            run_cli("graphics-handoff", "--occurrence", "stat-02", "--request", child["id"], project=project, expect=2)
            self.assertNotEqual(source["id"], local["id"])
            self.assertTrue(
                run_cli("graphics-reference-scope", "--request", source["id"], "--file", path, project=project)[
                    "idempotent"
                ]
            )

    def test_changed_or_missing_active_bytes_refuse_apply_and_text_followup_save(self):
        with tempfile.TemporaryDirectory() as project:
            _project(project)
            _assign(project)
            payload, row = current_row(project)
            image = Path(project) / "style.png"
            synth_image(image, color="blue")
            with serving(project) as (server, url):
                ref = upload_media(url, server.save_token, row, image, "image", "R1")
            edit(row, "Use R1 colors.", [ref])
            request, _ = save_import(project, payload)
            original = Path(project) / "brolls" / ref["ref"]
            before = Ledger(project, recover=False).path.read_bytes()
            original.write_bytes(b"changed")
            run_cli(
                "graphics-reference-apply", "--request", request["id"], "--analysis", "Blue.", project=project, expect=2
            )
            original.unlink()
            payload, row = current_row(project)
            edit(row, "A larger title with the same references.")
            with serving(project) as (server, url), self.assertRaises(urllib.error.HTTPError):
                post(url + serve.SAVE_PATH, json.dumps(payload).encode(), server.save_token)
            self.assertEqual(before, Ledger(project, recover=False).path.read_bytes())

    def test_followup_keeps_explicit_composition_clock_permission_and_original_instruction(self):
        with tempfile.TemporaryDirectory() as project:
            first, refs, _ = mixed_request(project, explicit=True)
            record = inspect(project, first, "--start", "3", "--end", "5")
            run_cli(
                "resolve",
                "--file",
                Path(project) / "brolls" / refs[1]["ref"],
                "--asset-type",
                "video",
                "--title",
                "Synthetic included reference",
                project=project,
            )
            candidate = Ledger(project, recover=False).data["items"][0]
            ident = candidate["id"]
            run_cli("preview", "--candidate", ident, "--start", "3", "--end", "5", project=project)
            run_cli(
                "approve",
                "--candidate",
                ident,
                "--by",
                "Synthetic editor",
                "--statement",
                "Synthetic fixture selection only.",
                project=project,
            )
            run_cli("permit", "--candidate", ident, "--evidence", "Synthetic fixture rights only.", project=project)
            run_cli("fetch", "--candidate", ident, project=project)
            candidate = Ledger(project, recover=False).data["items"][0]
            composition = {
                "label": "R2",
                "instruction": "Put R2 behind our graphics.",
                "background": _background_payload(ident, candidate["output"]["path"]),
            }
            path = analysis_file(project, record, composition=composition)
            run_cli("graphics-reference-apply", "--request", first["id"], "--file", path, project=project)
            _render(project)
            complete(project, first, "v1")
            original = copy.deepcopy(Ledger(project, recover=False).data["graphics"]["versions"]["v1"])
            payload, row = current_row(project)
            edit(row, "Use a larger title; preserve our included background and original narration.")
            follow, _ = save_import(project, payload)
            answer = run_cli(
                "graphics-reference-apply",
                "--request",
                follow["id"],
                "--analysis",
                "Larger title; unchanged background, palette, original narration and facts.",
                project=project,
            )
            self.assertEqual(
                original["assignment"]["reference_context"]["composition"], answer["reference_context"]["composition"]
            )
            _render(project)
            complete(project, follow, "v2")
            graphics = Ledger(project, recover=False).data["graphics"]
            self.assertEqual(
                original["assignment"]["background"], graphics["versions"]["v2"]["assignment"]["background"]
            )
            self.assertEqual(original["assignment"]["narration"], graphics["versions"]["v2"]["assignment"]["narration"])
            self.assertEqual(original["assignment"], graphics["versions"]["v1"]["assignment"])
            self.assertEqual(original["fingerprints"], graphics["versions"]["v1"]["fingerprints"])
