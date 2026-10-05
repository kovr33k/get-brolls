"""Release verification must fail closed when reusable CI cannot be established."""

import copy
import io
import json
import os
import subprocess
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

import _isolation  # noqa: F401
from _paths import ROOT

import preflight

REPOSITORY = "owner/repository"
TREE = "a" * 40
RUN_ID = 42


class ReusableCITests(unittest.TestCase):
    def setUp(self):
        self.artifact = {
            "id": 1,
            "name": preflight.EVIDENCE_NAME + TREE,
            "expired": False,
            "workflow_run": {"id": RUN_ID},
        }
        self.ci = {
            "status": "completed",
            "conclusion": "success",
            "path": preflight.WORKFLOW,
            "event": "pull_request",
            "repository": {"full_name": REPOSITORY},
            "head_repository": {"full_name": REPOSITORY},
            "run_attempt": 1,
        }
        self.jobs = [{"name": "Windows checks", "status": "completed", "conclusion": "success"}]
        self.evidence = {
            "schema": 1,
            "tree": TREE,
            "platform": "Windows",
            "python": "3.14.4",
            "run_id": RUN_ID,
            "run_attempt": 1,
        }

    def lookup(self):
        with (
            patch.object(preflight, "clean_tree", return_value=TREE),
            patch.object(
                preflight, "gh_json", side_effect=[{"artifacts": [self.artifact]}, self.ci, {"jobs": self.jobs}]
            ),
            patch.object(preflight, "read_evidence", return_value=self.evidence),
            patch.object(preflight.platform, "system", return_value="Windows"),
            patch.object(preflight.platform, "python_version", return_value="3.14.4"),
        ):
            return preflight.reusable_ci(ROOT, REPOSITORY)

    def test_reuses_completed_full_ci_for_actual_tested_tree(self):
        self.assertEqual(RUN_ID, self.lookup())

    def test_never_reuses_expired_missing_or_other_named_artifact(self):
        for key, value in (("expired", True), ("name", "unrelated")):
            with self.subTest(key=key):
                original = copy.deepcopy(self.artifact)
                self.artifact[key] = value
                self.assertIsNone(self.lookup())
                self.artifact = original
        with (
            patch.object(preflight, "clean_tree", return_value=TREE),
            patch.object(preflight, "gh_json", return_value={"artifacts": []}),
        ):
            self.assertIsNone(preflight.reusable_ci(ROOT, REPOSITORY))

    def test_pending_failed_other_workflow_event_or_repository_is_not_full_ci(self):
        changes = (
            ("status", "in_progress"),
            ("conclusion", "failure"),
            ("path", ".github/workflows/other.yml"),
            ("event", "push"),
            ("repository", {"full_name": "other/repo"}),
            ("head_repository", {"full_name": "fork/repo"}),
        )
        for key, value in changes:
            with self.subTest(key=key):
                original = copy.deepcopy(self.ci)
                self.ci[key] = value
                self.assertIsNone(self.lookup())
                self.ci = original

    def test_missing_skipped_failed_or_incomplete_windows_job_is_rejected(self):
        for jobs in (
            [],
            [{"name": "Other", "status": "completed", "conclusion": "success"}],
            [{"name": "Windows checks", "status": "completed", "conclusion": "skipped"}],
            [{"name": "Windows checks", "status": "in_progress", "conclusion": None}],
        ):
            with self.subTest(jobs=jobs):
                self.jobs = jobs
                self.assertIsNone(self.lookup())

    def test_mismatched_source_python_os_schema_run_or_attempt_is_rejected(self):
        for key, value in (
            ("tree", "b" * 40),
            ("python", "3.13.0"),
            ("platform", "Linux"),
            ("schema", 2),
            ("run_id", 7),
            ("run_attempt", 2),
        ):
            with self.subTest(key=key):
                original = copy.deepcopy(self.evidence)
                self.evidence[key] = value
                self.assertIsNone(self.lookup())
                self.evidence = original

    def test_network_failure_or_dirty_tree_requires_full_checks(self):
        for error in (ValueError("dirty checkout"), subprocess.CalledProcessError(1, ["gh", "api"])):
            with patch.object(preflight, "clean_tree", side_effect=error):
                self.assertIsNone(preflight.reusable_ci(ROOT, REPOSITORY))

    def test_requested_run_does_not_bypass_matching(self):
        with (
            patch.object(preflight, "clean_tree", return_value=TREE),
            patch.object(preflight, "gh_json", return_value={"artifacts": [self.artifact]}),
        ):
            self.assertIsNone(preflight.reusable_ci(ROOT, REPOSITORY, requested_run=99))

    def test_downloaded_zip_is_read_without_extracting_paths(self):
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w") as archive:
            archive.writestr("verification.json", json.dumps(self.evidence))
            archive.writestr("../outside.json", "must never be extracted")
        with patch.object(
            preflight.subprocess, "run", return_value=subprocess.CompletedProcess([], 0, buffer.getvalue())
        ):
            self.assertEqual(self.evidence, preflight.read_evidence(ROOT, REPOSITORY, self.artifact))


class PreflightGatesTests(unittest.TestCase):
    def test_full_checks_run_when_reuse_cannot_be_proven_and_skip_only_when_proven(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "scripts/getbrolls").mkdir(parents=True)
            (root / "scripts/getbrolls/__init__.py").write_text('__version__ = "1.2.3"\n', encoding="utf-8")
            (root / "CHANGELOG.md").write_text("## 1.2.3 — date\n\n- Real notes.\n", encoding="utf-8")
            for reused in (None, RUN_ID):
                with (
                    self.subTest(reused=reused),
                    patch.object(preflight, "run") as checks,
                    patch.object(preflight, "validate_frontmatter") as frontmatter,
                    patch.object(preflight, "reusable_ci", return_value=reused),
                    patch.object(preflight, "full_checks") as full,
                ):
                    notes = root / "notes.txt"
                    preflight.preflight(root, "1.2.3", REPOSITORY, None, notes)
                    frontmatter.assert_called_once_with(root)
                    self.assertEqual(4, checks.call_count)
                    self.assertEqual(1 if reused is None else 0, full.call_count)
                    self.assertEqual("- Real notes.\n", notes.read_text(encoding="utf-8"))

    def test_wrong_version_and_missing_changelog_stop_publication(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "scripts/getbrolls").mkdir(parents=True)
            (root / "scripts/getbrolls/__init__.py").write_text('__version__ = "1.2.3"\n', encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "__version__"), patch.object(preflight, "full_checks") as full:
                preflight.preflight(root, "9.9.9", "", None, root / "notes.txt")
            full.assert_not_called()
            (root / "CHANGELOG.md").write_text("## 1.2.30 — date\n\n- Wrong version.\n", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "section missing"):
                preflight.changelog_section(root, "1.2.3")
            self.assertFalse((root / "notes.txt").exists())

    def test_changelog_uses_literal_version_and_stops_at_next_heading(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "CHANGELOG.md").write_text(
                "## 1x2x3 — date\n\nWrong.\n\n## 1.2.3 — date\n\nRight.\n\n## 1.2.2 — date\nOlder.\n",
                encoding="utf-8",
            )
            self.assertEqual("Right.\n", preflight.changelog_section(root, "1.2.3"))

    def test_frontmatter_fallback_accepts_tags_but_rejects_unclosed_quotes_and_colons(self):
        preflight.validate_frontmatter_line("doc.md", "tags: [one, two]")
        for line in ('description: "unfinished', "description: text: ambiguous"):
            with self.subTest(line=line), self.assertRaises(ValueError):
                preflight.validate_frontmatter_line("doc.md", line)

    def test_dirty_tree_cannot_be_recorded_as_ci_proof(self):
        with patch.object(preflight, "run", return_value=" M tracked.py"), self.assertRaises(ValueError):
            preflight.clean_tree(ROOT)

    def test_recorded_tree_is_actual_checkout_not_pr_api_head(self):
        with tempfile.TemporaryDirectory() as directory:
            proof = Path(directory) / "verification.json"
            output = Path(directory) / "output"
            with (
                patch.object(preflight, "clean_tree", return_value=TREE),
                patch.object(preflight, "run", return_value="actual-merge-commit"),
                patch.dict(os.environ, {"GITHUB_RUN_ID": str(RUN_ID), "GITHUB_RUN_ATTEMPT": "1"}),
            ):
                preflight.record_ci(ROOT, proof, output)
            self.assertEqual(TREE, json.loads(proof.read_text(encoding="utf-8"))["tree"])
            self.assertEqual(f"tree={TREE}\n", output.read_text(encoding="utf-8"))

    def test_explicit_ref_is_checked_in_full_clone_and_invalid_ref_stops(self):
        with (
            patch.object(preflight, "run", side_effect=["commit-sha", "", ""]) as commands,
            patch.object(preflight, "preflight") as gate,
        ):
            self.assertEqual(0, preflight.main(["--ref", "chosen", "--version", "2.13.1"]))
            self.assertIn("--no-hardlinks", commands.call_args_list[1].args)
            self.assertNotEqual(ROOT, gate.call_args.args[0])
        with (
            patch.object(preflight, "run", side_effect=subprocess.CalledProcessError(1, ["git"])),
            patch.object(preflight, "preflight") as gate,
        ):
            self.assertEqual(1, preflight.main(["--ref", "missing"]))
            gate.assert_not_called()
