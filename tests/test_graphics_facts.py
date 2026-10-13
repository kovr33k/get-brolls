"""#55: displayed-fact evidence, confined data identity and conflict decisions."""

from __future__ import annotations

import copy
import hashlib
import json
import re
import stat
import subprocess
import tempfile
import unittest
from pathlib import Path

import _isolation
from _paths import ROOT

from getbrolls.graphics_facts import (
    PRESERVE,
    facts_readiness,
    normalize_facts,
    resolve_conflict,
    validate_facts,
)

SCHEMA_PATH = ROOT / "schemas" / "graphics-facts.schema.json"
DATA_BYTES = b"indicator,value\nproven_reserves,303.8\n"
CHART_BYTES = b"\x89PNG\r\nchart-image-not-editable-data\n"
ORIGINAL_NARRATION = "The country holds the largest oil reserves in the world.\nThat claim stays in the scenario."
PROPOSED = "Proven reserves are 303.8 billion barrels (2020, World Bank)."
DEFINITION = "Proved oil reserves,\nmeasured in billion barrels."


def _sha(data):
    return hashlib.sha256(data).hexdigest()


def _brolls(tmp):
    root = Path(tmp) / "brolls"
    (root / "graphics-data").mkdir(parents=True)
    (root / "previews").mkdir()
    (root / "clips").mkdir()
    return root


def _write(root, rel, data):
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return _sha(data)


def _source(data_ref, digest, **overrides):
    item = {
        "id": "wb-reserves",
        "url": "https://api.worldbank.org/v2/country/VE/indicator/NY.GDP.PETR.RT.ZS",
        "title": "World Bank petroleum indicator",
        "reference_date": "2020",
        "terms_url": "https://data.worldbank.org/summary-terms-of-use",
        "conditions": "Attribution required; rendered use of the cited figure.",
        "rendered_use": "permitted",
        "raw_redistribution": "restricted",
        "kind": "data",
        "data_ref": data_ref,
        "sha256": digest,
    }
    item.update(overrides)
    return item


def _value(**overrides):
    item = {
        "id": "oil-reserves",
        "value": "303.8",
        "unit": "billion barrels",
        "definition": DEFINITION,
        "geography": "Venezuela",
        "reference_date": "2020",
        "source_ids": ["wb-reserves"],
    }
    item.update(overrides)
    return item


def _conflict(**overrides):
    item = {
        "id": "reserves-gap",
        "original_narration": ORIGINAL_NARRATION,
        "explanation": "Researched proved reserves disagree with the unqualified superlative.",
        "source_ids": ["wb-reserves"],
        "proposed_correction": PROPOSED,
        "decision": None,
    }
    item.update(overrides)
    return item


def _payload(data_ref, digest, *, required=True, with_conflict=True, **source_overrides):
    return {
        "schema_version": 1,
        "required": required,
        "values": [_value()],
        "sources": [_source(data_ref, digest, **source_overrides)],
        "conflicts": [_conflict()] if with_conflict else [],
    }


def _dir_link(link, target):
    link = Path(link)
    target = Path(target)
    link.parent.mkdir(parents=True, exist_ok=True)
    try:
        link.symlink_to(target, target_is_directory=True)
        return link.exists() or link.is_symlink()
    except OSError:
        done = subprocess.run(
            ["cmd", "/c", "mklink", "/J", str(link), str(target)],
            capture_output=True,
            text=True,
            encoding="utf-8",
            check=False,
        )
        return done.returncode == 0 and (link.exists() or link.is_symlink() or _is_reparse_path(link))


def _is_reparse_path(path):
    path = Path(path)
    try:
        if path.is_symlink():
            return True
    except OSError:
        return True
    try:
        info = path.lstat()
    except FileNotFoundError:
        return False
    except OSError:
        return True
    attributes = getattr(info, "st_file_attributes", 0)
    reparse = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
    return bool(attributes & reparse)


def _remove_owned_link(link):
    """Remove only the owned link node; never walk or rmtree through a junction."""
    link = Path(link)
    if not (link.exists() or link.is_symlink() or _is_reparse_path(link)):
        return
    if link.is_symlink():
        link.unlink()
        return
    try:
        link.rmdir()
    except OSError:
        link.unlink()


def _file_state(root):
    state = {}
    for path in sorted(root.rglob("*")):
        if path.is_file() and not path.is_symlink():
            state[path.relative_to(root).as_posix()] = path.read_bytes()
    return state


def _set_nested(record, path, value):
    cursor = record
    for key in path[:-1]:
        cursor = cursor[key]
    cursor[path[-1]] = value


def _assert_schema_compatible(testcase, record):
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    defs = schema["$defs"]
    testcase.assertEqual(set(schema["required"]), set(record))
    testcase.assertEqual(schema["properties"]["schema_version"]["const"], record["schema_version"])
    testcase.assertIsInstance(record["schema_version"], int)
    testcase.assertIsInstance(record["required"], bool)
    testcase.assertEqual("string", defs["prose"]["type"])
    testcase.assertEqual("string", defs["conditions"]["type"])
    testcase.assertEqual("array", defs["sourceIds"]["type"])
    testcase.assertEqual({"type": "null"}, defs["conflict"]["properties"]["decision"]["anyOf"][0])
    data_ref_re = re.compile(defs["dataRef"]["pattern"])
    sha_re = re.compile(defs["sha256OrEmpty"]["pattern"])
    for value in record["values"]:
        testcase.assertEqual(set(defs["value"]["required"]), set(value))
        for key in ("id", "value", "unit", "definition", "geography", "reference_date"):
            testcase.assertIsInstance(value[key], str)
        testcase.assertIsInstance(value["source_ids"], list)
        testcase.assertNotIn(None, value["source_ids"])
        testcase.assertLessEqual(len(value["value"]), defs["prose"]["maxLength"])
    for source in record["sources"]:
        testcase.assertEqual(set(defs["source"]["required"]), set(source))
        for key in ("id", "url", "title", "reference_date", "terms_url"):
            testcase.assertIsInstance(source[key], str)
        testcase.assertIsInstance(source["conditions"], str)
        testcase.assertLessEqual(len(source["conditions"]), defs["conditions"]["maxLength"])
        testcase.assertIn(source["rendered_use"], defs["permission"]["enum"])
        testcase.assertIn(source["raw_redistribution"], defs["permission"]["enum"])
        testcase.assertIn(source["kind"], defs["source"]["properties"]["kind"]["enum"])
        testcase.assertIsInstance(source["data_ref"], str)
        testcase.assertIsInstance(source["sha256"], str)
        testcase.assertRegex(source["data_ref"], data_ref_re)
        testcase.assertRegex(source["sha256"], sha_re)
    for conflict in record["conflicts"]:
        testcase.assertEqual(set(defs["conflict"]["required"]), set(conflict))
        for key in ("id", "original_narration", "explanation", "proposed_correction"):
            testcase.assertIsInstance(conflict[key], str)
            testcase.assertGreaterEqual(len(conflict[key]), 1)
        testcase.assertIsInstance(conflict["source_ids"], list)
        testcase.assertNotIn(None, conflict["source_ids"])
        decision = conflict["decision"]
        if decision is None:
            continue
        testcase.assertIsInstance(decision, dict)
        testcase.assertEqual(set(defs["decision"]["required"]), set(decision))
        testcase.assertIn(decision["choice"], defs["decision"]["properties"]["choice"]["enum"])
        for key in ("by", "statement", "at", "evidence_sha256"):
            testcase.assertIsInstance(decision[key], str)


class SchemaContractTests(unittest.TestCase):
    def test_schema_models_draft_empty_arrays_and_optional_strings(self):
        schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
        self.assertEqual(1, schema["properties"]["schema_version"]["const"])
        self.assertEqual("boolean", schema["properties"]["required"]["type"])
        self.assertEqual("integer", schema["properties"]["schema_version"]["type"])
        for key in ("values", "sources", "conflicts"):
            self.assertEqual("array", schema["properties"][key]["type"])
            self.assertNotIn("minItems", schema["properties"][key])
        defs = schema["$defs"]
        self.assertEqual(["data", "chart_image"], defs["source"]["properties"]["kind"]["enum"])
        self.assertEqual("^(?:|(?:graphics-data|previews|clips)/.+)$", defs["dataRef"]["pattern"])
        self.assertEqual("^(?:|[0-9a-f]{64})$", defs["sha256OrEmpty"]["pattern"])
        self.assertEqual({"type": "null"}, defs["conflict"]["properties"]["decision"]["anyOf"][0])
        self.assertIn("prose", defs)
        self.assertEqual(8000, defs["prose"]["maxLength"])
        self.assertEqual("string", defs["prose"]["type"])
        self.assertEqual("string", defs["conditions"]["type"])
        self.assertEqual("array", defs["sourceIds"]["type"])
        for key in ("value", "unit", "definition", "geography", "reference_date"):
            self.assertEqual("#/$defs/prose", defs["value"]["properties"][key]["$ref"])
        for key in ("url", "title", "reference_date", "terms_url"):
            self.assertEqual("#/$defs/prose", defs["source"]["properties"][key]["$ref"])
        self.assertEqual("#/$defs/conditions", defs["source"]["properties"]["conditions"]["$ref"])
        self.assertEqual("#/$defs/sourceIds", defs["value"]["properties"]["source_ids"]["$ref"])


class NormalizeAndValidateTests(unittest.TestCase):
    def test_complete_evidence_captures_hash_and_preserves_multiline_prose(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = _brolls(tmp)
            digest = _write(root, "graphics-data/reserves.csv", DATA_BYTES)
            payload = _payload("graphics-data/reserves.csv", None)
            snapshot = copy.deepcopy(payload)
            record = normalize_facts(root, payload)
            self.assertEqual(snapshot, payload)
            self.assertIsNot(record["values"], payload["values"])
            self.assertEqual(digest, record["sources"][0]["sha256"])
            self.assertEqual(DEFINITION, record["values"][0]["definition"])
            self.assertEqual(ORIGINAL_NARRATION, record["conflicts"][0]["original_narration"])
            self.assertEqual("data", record["sources"][0]["kind"])
            self.assertEqual("restricted", record["sources"][0]["raw_redistribution"])
            self.assertIs(record, validate_facts(record))
            _assert_schema_compatible(self, record)

    def test_omitted_arrays_normalize_to_empty_draft(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = _brolls(tmp)
            record = normalize_facts(root, {"schema_version": 1, "required": True})
            self.assertEqual([], record["values"])
            self.assertEqual([], record["sources"])
            self.assertEqual([], record["conflicts"])
            self.assertTrue(record["required"])
            ready = facts_readiness(root, record)
            self.assertFalse(ready["ready"])
            self.assertTrue(ready["reasons"])

    def test_none_is_compatible_and_does_not_invalidate_legacy_assignments(self):
        self.assertIsNone(validate_facts(None))
        ready = facts_readiness(Path("unused"), None)
        self.assertTrue(ready["ready"])
        self.assertEqual([], ready["reasons"])

    def test_malformed_saved_record_is_not_reset(self):
        with self.assertRaises(ValueError) as ctx:
            validate_facts({"schema_version": 1, "required": False})
        self.assertEqual(PRESERVE, str(ctx.exception))

    def test_bool_int_and_non_string_value_distinctions(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = _brolls(tmp)
            digest = _write(root, "graphics-data/reserves.csv", DATA_BYTES)
            payload = _payload("graphics-data/reserves.csv", digest)
            payload["required"] = 1
            with self.assertRaises(ValueError) as required:
                normalize_facts(root, payload)
            self.assertIn("boolean", str(required.exception))
            payload["required"] = True
            payload["schema_version"] = True
            with self.assertRaises(ValueError) as version:
                normalize_facts(root, payload)
            self.assertIn("integer 1", str(version.exception))
            payload["schema_version"] = 1
            payload["values"][0]["value"] = 303.8
            with self.assertRaises(ValueError) as numeric:
                normalize_facts(root, payload)
            self.assertIn("text", str(numeric.exception).lower())

    def test_duplicate_and_unknown_ids_are_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = _brolls(tmp)
            digest = _write(root, "graphics-data/reserves.csv", DATA_BYTES)
            payload = _payload("graphics-data/reserves.csv", digest)
            payload["values"].append(_value())
            with self.assertRaises(ValueError) as duplicated:
                normalize_facts(root, payload)
            self.assertIn("duplicated", str(duplicated.exception))
            payload = _payload("graphics-data/reserves.csv", digest)
            payload["values"][0]["source_ids"] = ["missing-source"]
            with self.assertRaises(ValueError) as missing:
                normalize_facts(root, payload)
            self.assertIn("unknown source", str(missing.exception))

    def test_credential_and_non_https_urls_are_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = _brolls(tmp)
            digest = _write(root, "graphics-data/reserves.csv", DATA_BYTES)
            cases = (
                "http://data.worldbank.org/indicator",
                "https://user:pass@data.worldbank.org/indicator",
                "https://data.worldbank.org/indicator?api_key=secret",
                "https://127.0.0.1/indicator",
            )
            for url in cases:
                payload = _payload("graphics-data/reserves.csv", digest, url=url)
                with self.assertRaises(ValueError) as ctx:
                    normalize_facts(root, payload)
                self.assertIn("public HTTPS", str(ctx.exception))

    def test_validate_facts_does_not_read_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = _brolls(tmp)
            digest = _write(root, "graphics-data/reserves.csv", DATA_BYTES)
            record = normalize_facts(root, _payload("graphics-data/reserves.csv", digest, with_conflict=False))
            (root / "graphics-data" / "reserves.csv").unlink()
            self.assertIs(record, validate_facts(record))
            ready = facts_readiness(root, record)
            self.assertFalse(ready["ready"])
            self.assertTrue(any("missing" in reason or "regular file" in reason for reason in ready["reasons"]))

    def test_input_nulls_normalize_to_canonical_empty_draft(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = _brolls(tmp)
            payload = {
                "schema_version": 1,
                "required": False,
                "values": [
                    _value(
                        value=None,
                        unit=None,
                        definition=None,
                        geography=None,
                        reference_date=None,
                        source_ids=None,
                    )
                ],
                "sources": [
                    _source(
                        "",
                        "",
                        url=None,
                        title=None,
                        reference_date=None,
                        terms_url=None,
                        conditions=None,
                    )
                ],
                "conflicts": [],
            }
            snapshot = copy.deepcopy(payload)
            record = normalize_facts(root, payload)
            self.assertEqual(snapshot, payload)
            self.assertEqual("", record["values"][0]["value"])
            self.assertEqual("", record["values"][0]["unit"])
            self.assertEqual([], record["values"][0]["source_ids"])
            self.assertEqual("", record["sources"][0]["url"])
            self.assertEqual("", record["sources"][0]["title"])
            self.assertEqual("", record["sources"][0]["terms_url"])
            self.assertEqual("", record["sources"][0]["conditions"])
            self.assertIs(record, validate_facts(record))
            _assert_schema_compatible(self, record)
            ready = facts_readiness(root, record)
            self.assertFalse(ready["ready"])
            self.assertTrue(ready["reasons"])

    def test_stored_null_and_wrong_types_raise_preserve_without_mutation(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = _brolls(tmp)
            digest = _write(root, "graphics-data/reserves.csv", DATA_BYTES)
            record = normalize_facts(root, _payload("graphics-data/reserves.csv", digest))
            decided = resolve_conflict(
                record,
                "reserves-gap",
                "keep_scenario",
                "Editor Name",
                "Keep the original scenario wording visible.",
            )
            cases = (
                ("value-null", ["values", 0, "value"], None),
                ("unit-null", ["values", 0, "unit"], None),
                ("definition-null", ["values", 0, "definition"], None),
                ("geography-null", ["values", 0, "geography"], None),
                ("value-reference_date-null", ["values", 0, "reference_date"], None),
                ("value-source_ids-null", ["values", 0, "source_ids"], None),
                ("value-wrong-type", ["values", 0, "value"], 303.8),
                ("source_ids-wrong-type", ["values", 0, "source_ids"], "wb-reserves"),
                ("source-url-null", ["sources", 0, "url"], None),
                ("source-title-null", ["sources", 0, "title"], None),
                ("source-reference_date-null", ["sources", 0, "reference_date"], None),
                ("source-terms_url-null", ["sources", 0, "terms_url"], None),
                ("source-conditions-null", ["sources", 0, "conditions"], None),
                ("conflict-source_ids-null", ["conflicts", 0, "source_ids"], None),
                ("decision-wrong-type", ["conflicts", 0, "decision"], "keep_scenario"),
                ("decision-by-null", ["conflicts", 0, "decision", "by"], None),
            )
            before = _file_state(root)
            for name, path, value in cases:
                with self.subTest(name=name):
                    malformed = copy.deepcopy(decided)
                    _set_nested(malformed, path, value)
                    original = copy.deepcopy(malformed)
                    with self.assertRaises(ValueError) as validated:
                        validate_facts(malformed)
                    self.assertEqual(PRESERVE, str(validated.exception))
                    with self.assertRaises(ValueError) as ready:
                        facts_readiness(root, malformed)
                    self.assertEqual(PRESERVE, str(ready.exception))
                    self.assertEqual(original, malformed)
                    self.assertEqual(before, _file_state(root))

    def test_normalized_records_match_owned_schema(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = _brolls(tmp)
            digest = _write(root, "graphics-data/reserves.csv", DATA_BYTES)
            chart_digest = _write(root, "previews/reserves-chart.png", CHART_BYTES)
            complete = normalize_facts(root, _payload("graphics-data/reserves.csv", digest, with_conflict=False))
            optional = normalize_facts(
                root, _payload("graphics-data/reserves.csv", digest, required=False, with_conflict=False)
            )
            draft = normalize_facts(root, {"schema_version": 1, "required": True})
            chart = normalize_facts(
                root,
                {
                    "schema_version": 1,
                    "required": True,
                    "values": [_value(source_ids=["wb-reserves", "chart-shot"])],
                    "sources": [
                        _source("graphics-data/reserves.csv", digest),
                        _source(
                            "previews/reserves-chart.png",
                            chart_digest,
                            kind="chart_image",
                            id="chart-shot",
                            title="Published chart image, not the editable series",
                        ),
                    ],
                    "conflicts": [],
                },
            )
            decided = resolve_conflict(
                normalize_facts(root, _payload("graphics-data/reserves.csv", digest)),
                "reserves-gap",
                "accept_correction",
                "Editor Name",
                "Accept the researched proved-reserves figure for this scene.",
            )
            for record in (complete, optional, draft, chart, decided):
                self.assertIs(record, validate_facts(record))
                _assert_schema_compatible(self, record)


class ReadinessAndIdentityTests(unittest.TestCase):
    def test_incomplete_research_is_a_draft_with_actionable_blockers(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = _brolls(tmp)
            payload = {
                "schema_version": 1,
                "required": True,
                "values": [
                    _value(
                        value="",
                        unit="",
                        definition="",
                        geography="",
                        reference_date="",
                        source_ids=[],
                    )
                ],
                "sources": [
                    _source(
                        "",
                        "",
                        url="",
                        title="",
                        reference_date="",
                        terms_url="",
                        conditions="",
                        rendered_use="unknown",
                        raw_redistribution="unknown",
                    )
                ],
                "conflicts": [],
            }
            snapshot = copy.deepcopy(payload)
            record = normalize_facts(root, payload)
            self.assertEqual(snapshot, payload)
            self.assertIs(record, validate_facts(record))
            ready = facts_readiness(root, record)
            self.assertFalse(ready["ready"])
            joined = " ".join(ready["reasons"])
            self.assertIn("empty", joined)
            self.assertIn("no source evidence", joined)
            self.assertIn("unknown", joined)
            self.assertIn("data_ref is missing", joined)
            self.assertIn("unit is missing", joined)
            self.assertIn("definition is missing", joined)
            self.assertIn("geography is missing", joined)
            self.assertIn("reference_date is missing", joined)
            self.assertIn("title is missing", joined)
            self.assertIn("terms_url is missing", joined)
            self.assertIn("conditions is missing", joined)

    def test_modified_bytes_block_readiness_without_writes(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = _brolls(tmp)
            rel = "graphics-data/reserves.csv"
            digest = _write(root, rel, DATA_BYTES)
            record = normalize_facts(root, _payload(rel, digest, with_conflict=False))
            before = sorted(path.relative_to(root).as_posix() for path in root.rglob("*") if path.is_file())
            (root / rel).write_bytes(DATA_BYTES + b"tampered\n")
            ready = facts_readiness(root, record)
            after = sorted(path.relative_to(root).as_posix() for path in root.rglob("*") if path.is_file())
            self.assertFalse(ready["ready"])
            self.assertTrue(any("bytes changed" in reason for reason in ready["reasons"]))
            self.assertEqual(before, after)

    def test_wrong_declared_hash_is_rejected_on_normalize(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = _brolls(tmp)
            _write(root, "graphics-data/reserves.csv", DATA_BYTES)
            fake = "0" * 64
            with self.assertRaises(ValueError) as ctx:
                normalize_facts(root, _payload("graphics-data/reserves.csv", fake, with_conflict=False))
            self.assertIn("does not match", str(ctx.exception))

    def test_chart_image_is_distinct_from_editable_source_data(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = _brolls(tmp)
            data_digest = _write(root, "graphics-data/reserves.csv", DATA_BYTES)
            chart_digest = _write(root, "previews/reserves-chart.png", CHART_BYTES)
            payload = {
                "schema_version": 1,
                "required": True,
                "values": [_value(source_ids=["wb-reserves", "chart-shot"])],
                "sources": [
                    _source("graphics-data/reserves.csv", data_digest),
                    _source(
                        "previews/reserves-chart.png",
                        chart_digest,
                        kind="chart_image",
                        id="chart-shot",
                        title="Published chart image, not the editable series",
                    ),
                ],
                "conflicts": [],
            }
            record = normalize_facts(root, payload)
            kinds = {item["id"]: item["kind"] for item in record["sources"]}
            self.assertEqual("data", kinds["wb-reserves"])
            self.assertEqual("chart_image", kinds["chart-shot"])
            self.assertNotEqual(record["sources"][0]["data_ref"], record["sources"][1]["data_ref"])
            ready = facts_readiness(root, record)
            self.assertTrue(ready["ready"])
            self.assertEqual([], ready["reasons"])

    def test_restricted_rendered_use_and_unknown_permissions_block_sourced_ready_state(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = _brolls(tmp)
            digest = _write(root, "clips/reserves.csv", DATA_BYTES)
            restricted = normalize_facts(
                root,
                _payload("clips/reserves.csv", digest, with_conflict=False, rendered_use="restricted"),
            )
            blocked = facts_readiness(root, restricted)
            self.assertFalse(blocked["ready"])
            self.assertTrue(any("rendered_use is restricted" in reason for reason in blocked["reasons"]))

    def test_erasing_required_context_or_terms_blocks_sourced_ready_state(self):
        cases = (
            ("values", 0, "unit"),
            ("values", 0, "definition"),
            ("values", 0, "geography"),
            ("values", 0, "reference_date"),
            ("sources", 0, "title"),
            ("sources", 0, "reference_date"),
            ("sources", 0, "terms_url"),
            ("sources", 0, "conditions"),
        )
        with tempfile.TemporaryDirectory() as tmp:
            root = _brolls(tmp)
            digest = _write(root, "graphics-data/reserves.csv", DATA_BYTES)
            payload = _payload("graphics-data/reserves.csv", digest, with_conflict=False)
            snapshot = copy.deepcopy(payload)
            record = normalize_facts(root, payload)
            self.assertEqual(snapshot, payload)
            complete = facts_readiness(root, record)
            self.assertTrue(complete["ready"])
            self.assertEqual([], complete["reasons"])
            before = _file_state(root)
            for group, index, field in cases:
                with self.subTest(group=group, field=field):
                    erased = copy.deepcopy(record)
                    erased[group][index][field] = ""
                    original = copy.deepcopy(erased)
                    self.assertIs(erased, validate_facts(erased))
                    ready = facts_readiness(root, erased)
                    ident = erased[group][index]["id"]
                    self.assertFalse(ready["ready"])
                    self.assertTrue(
                        any(field in reason and ident in reason for reason in ready["reasons"]),
                        ready["reasons"],
                    )
                    self.assertEqual(original, erased)
                    self.assertEqual(snapshot, payload)
                    self.assertEqual(before, _file_state(root))

    def test_optional_incomplete_draft_is_not_sourced_ready(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = _brolls(tmp)
            digest = _write(root, "graphics-data/reserves.csv", DATA_BYTES)
            complete = normalize_facts(
                root, _payload("graphics-data/reserves.csv", digest, required=False, with_conflict=False)
            )
            self.assertTrue(facts_readiness(root, complete)["ready"])
            payload = _payload("graphics-data/reserves.csv", digest, required=False, with_conflict=False)
            payload["values"][0]["unit"] = ""
            snapshot = copy.deepcopy(payload)
            draft = normalize_facts(root, payload)
            self.assertEqual(snapshot, payload)
            self.assertFalse(draft["required"])
            self.assertIs(draft, validate_facts(draft))
            ready = facts_readiness(root, draft)
            self.assertFalse(ready["ready"])
            self.assertTrue(any("unit" in reason and "oil-reserves" in reason for reason in ready["reasons"]))

    def test_explicit_not_applicable_context_stays_sourced_ready(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = _brolls(tmp)
            digest = _write(root, "graphics-data/reserves.csv", DATA_BYTES)
            payload = _payload("graphics-data/reserves.csv", digest, with_conflict=False)
            payload["values"][0]["unit"] = "count (dimensionless)"
            payload["values"][0]["geography"] = "global (not applicable to a single country)"
            payload["values"][0]["reference_date"] = "not applicable; stock figure without a period"
            payload["sources"][0]["reference_date"] = "not applicable; undated methodology note"
            record = normalize_facts(root, payload)
            self.assertEqual("count (dimensionless)", record["values"][0]["unit"])
            self.assertEqual("restricted", record["sources"][0]["raw_redistribution"])
            self.assertEqual("permitted", record["sources"][0]["rendered_use"])
            ready = facts_readiness(root, record)
            self.assertTrue(ready["ready"])
            self.assertEqual([], ready["reasons"])


class UnsafeRefTests(unittest.TestCase):
    def test_lexical_traversal_and_foreign_prefixes_are_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = _brolls(tmp)
            unsafe = (
                "../graphics-data/reserves.csv",
                "graphics-data/../clips/reserves.csv",
                "/tmp/reserves.csv",
                r"graphics-data\reserves.csv",
                "C:/Windows/reserves.csv",
                "sounds/whip.wav",
                "narration/private/audio/vo.wav",
                "graphics-data/foo:bar.csv",
            )
            for rel in unsafe:
                with self.assertRaises(ValueError) as ctx:
                    normalize_facts(root, _payload(rel, _sha(DATA_BYTES), with_conflict=False))
                message = str(ctx.exception).lower()
                self.assertTrue(
                    "posix" in message or "project" in message or "colon" in message or "graphics-data" in message
                )

    def test_file_symlink_to_external_bytes_is_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            root = _brolls(tmp)
            outside = tmp_path / "outside.csv"
            outside.write_bytes(DATA_BYTES)
            link = root / "graphics-data" / "linked.csv"
            _isolation.symlink_or_skip(link, outside)
            with self.assertRaises(ValueError) as ctx:
                normalize_facts(root, _payload("graphics-data/linked.csv", _sha(DATA_BYTES), with_conflict=False))
            self.assertIn("symlink or junction", str(ctx.exception))

    def test_directory_junction_or_symlink_input_is_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            root = tmp_path / "brolls"
            root.mkdir()
            (root / "previews").mkdir()
            (root / "clips").mkdir()
            outside = tmp_path / "outside"
            outside.mkdir()
            (outside / "leaked.csv").write_bytes(DATA_BYTES)
            link = root / "graphics-data"
            if not _dir_link(link, outside):
                self.skipTest("could not create a confined directory symlink or junction")
            try:
                with self.assertRaises(ValueError) as ctx:
                    normalize_facts(root, _payload("graphics-data/leaked.csv", _sha(DATA_BYTES), with_conflict=False))
                message = str(ctx.exception)
                self.assertTrue("symlink or junction" in message or "outside the project" in message)
                self.assertEqual(DATA_BYTES, (outside / "leaked.csv").read_bytes())
            finally:
                _remove_owned_link(link)
            self.assertEqual(DATA_BYTES, (outside / "leaked.csv").read_bytes())

    def test_lexical_root_junction_does_not_redefine_confinement(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            root = _brolls(tmp)
            digest = _write(root, "graphics-data/reserves.csv", DATA_BYTES)
            payload = _payload("graphics-data/reserves.csv", digest, with_conflict=False)
            snapshot = copy.deepcopy(payload)
            record = normalize_facts(root, payload)
            self.assertEqual(snapshot, payload)
            intact = facts_readiness(root, record)
            self.assertTrue(intact["ready"])
            self.assertEqual([], intact["reasons"])

            sentinel = b"EXTERNAL-SENTINEL-BYTES-DO-NOT-FOLLOW"
            external = tmp_path / "external-target"
            external.mkdir()
            (external / "graphics-data").mkdir()
            (external / "previews").mkdir()
            (external / "clips").mkdir()
            (external / "graphics-data" / "reserves.csv").write_bytes(DATA_BYTES)
            (external / "sentinel.bin").write_bytes(sentinel)
            linked_root = tmp_path / "linked-brolls"
            if not _dir_link(linked_root, external):
                self.skipTest("could not create a root junction or directory symlink")
            try:
                with self.assertRaises(ValueError) as ctx:
                    normalize_facts(linked_root, copy.deepcopy(payload))
                self.assertIn("symlink or junction", str(ctx.exception))
                ready = facts_readiness(linked_root, record)
                self.assertFalse(ready["ready"])
                self.assertTrue(any("symlink or junction" in reason for reason in ready["reasons"]))
                self.assertEqual(snapshot, payload)
                self.assertEqual(sentinel, (external / "sentinel.bin").read_bytes())
                self.assertEqual(DATA_BYTES, (external / "graphics-data" / "reserves.csv").read_bytes())
            finally:
                _remove_owned_link(linked_root)
            self.assertFalse(linked_root.exists())
            self.assertFalse(linked_root.is_symlink())
            self.assertFalse(_is_reparse_path(linked_root))
            self.assertEqual(sentinel, (external / "sentinel.bin").read_bytes())
            self.assertEqual(DATA_BYTES, (external / "graphics-data" / "reserves.csv").read_bytes())

    def test_lexical_parent_junction_does_not_redefine_confinement(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            root = _brolls(tmp)
            digest = _write(root, "graphics-data/reserves.csv", DATA_BYTES)
            payload = _payload("graphics-data/reserves.csv", digest, with_conflict=False)
            snapshot = copy.deepcopy(payload)
            record = normalize_facts(root, payload)
            self.assertEqual(snapshot, payload)
            intact = facts_readiness(root, record)
            self.assertTrue(intact["ready"])
            self.assertEqual([], intact["reasons"])

            sentinel = b"EXTERNAL-PARENT-JUNCTION-SENTINEL-DO-NOT-FOLLOW"
            external = tmp_path / "external-parent-target"
            external.mkdir()
            (external / "brolls").mkdir()
            (external / "brolls" / "graphics-data").mkdir()
            (external / "brolls" / "previews").mkdir()
            (external / "brolls" / "clips").mkdir()
            (external / "brolls" / "graphics-data" / "reserves.csv").write_bytes(DATA_BYTES)
            (external / "sentinel.bin").write_bytes(sentinel)
            linked_parent = tmp_path / "linked-parent"
            if not _dir_link(linked_parent, external):
                self.skipTest("could not create a parent junction or directory symlink")
            linked_root = linked_parent / "brolls"
            try:
                with self.assertRaises(ValueError) as ctx:
                    normalize_facts(linked_root, copy.deepcopy(payload))
                self.assertIn("symlink or junction", str(ctx.exception))
                ready = facts_readiness(linked_root, record)
                self.assertFalse(ready["ready"])
                self.assertTrue(any("symlink or junction" in reason for reason in ready["reasons"]))
                self.assertEqual(snapshot, payload)
                self.assertEqual(DATA_BYTES, (root / "graphics-data" / "reserves.csv").read_bytes())
                self.assertEqual(sentinel, (external / "sentinel.bin").read_bytes())
                self.assertEqual(DATA_BYTES, (external / "brolls" / "graphics-data" / "reserves.csv").read_bytes())
            finally:
                _remove_owned_link(linked_parent)
            self.assertFalse(linked_parent.exists())
            self.assertFalse(linked_parent.is_symlink())
            self.assertFalse(_is_reparse_path(linked_parent))
            self.assertTrue((root / "graphics-data" / "reserves.csv").is_file())
            self.assertEqual(DATA_BYTES, (root / "graphics-data" / "reserves.csv").read_bytes())
            self.assertEqual(sentinel, (external / "sentinel.bin").read_bytes())
            self.assertEqual(DATA_BYTES, (external / "brolls" / "graphics-data" / "reserves.csv").read_bytes())


class ConflictDecisionTests(unittest.TestCase):
    def test_accept_correction_binds_fingerprint_and_leaves_originals_untouched(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = _brolls(tmp)
            digest = _write(root, "graphics-data/reserves.csv", DATA_BYTES)
            payload = _payload("graphics-data/reserves.csv", digest)
            snapshot = copy.deepcopy(payload)
            record = normalize_facts(root, payload)
            updated = resolve_conflict(
                record,
                "reserves-gap",
                "accept_correction",
                "Editor Name",
                "Accept the researched proved-reserves figure for this scene.",
            )
            self.assertEqual(snapshot, payload)
            self.assertIsNone(record["conflicts"][0]["decision"])
            self.assertEqual(ORIGINAL_NARRATION, updated["conflicts"][0]["original_narration"])
            self.assertEqual(PROPOSED, updated["conflicts"][0]["proposed_correction"])
            self.assertEqual("accept_correction", updated["conflicts"][0]["decision"]["choice"])
            self.assertEqual("Editor Name", updated["conflicts"][0]["decision"]["by"])
            self.assertRegex(updated["conflicts"][0]["decision"]["evidence_sha256"], r"^[0-9a-f]{64}$")
            ready = facts_readiness(root, updated)
            self.assertTrue(ready["ready"])

    def test_keep_scenario_does_not_rewrite_narration_and_defer_stays_unresolved(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = _brolls(tmp)
            digest = _write(root, "graphics-data/reserves.csv", DATA_BYTES)
            record = normalize_facts(root, _payload("graphics-data/reserves.csv", digest))
            kept = resolve_conflict(
                record,
                "reserves-gap",
                "keep_scenario",
                "Editor Name",
                "Keep the original scenario wording visible.",
            )
            self.assertEqual(ORIGINAL_NARRATION, kept["conflicts"][0]["original_narration"])
            self.assertTrue(facts_readiness(root, kept)["ready"])
            deferred = resolve_conflict(
                record,
                "reserves-gap",
                "defer",
                "Editor Name",
                "Need another source before choosing.",
            )
            ready = facts_readiness(root, deferred)
            self.assertFalse(ready["ready"])
            self.assertTrue(any("deferred" in reason for reason in ready["reasons"]))
            self.assertIsNone(record["conflicts"][0]["decision"])

    def test_changed_values_or_sources_invalidate_a_bound_decision(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = _brolls(tmp)
            digest = _write(root, "graphics-data/reserves.csv", DATA_BYTES)
            record = normalize_facts(root, _payload("graphics-data/reserves.csv", digest))
            decided = resolve_conflict(
                record,
                "reserves-gap",
                "accept_correction",
                "Editor Name",
                "Accept the researched figure.",
            )
            self.assertTrue(facts_readiness(root, decided)["ready"])
            changed_value = copy.deepcopy(decided)
            changed_value["values"][0]["value"] = "999"
            stale_value = facts_readiness(root, changed_value)
            self.assertFalse(stale_value["ready"])
            self.assertTrue(any("stale evidence" in reason for reason in stale_value["reasons"]))
            changed_source = copy.deepcopy(decided)
            changed_source["sources"][0]["title"] = "Different attribution"
            stale_source = facts_readiness(root, changed_source)
            self.assertFalse(stale_source["ready"])
            self.assertTrue(any("stale evidence" in reason for reason in stale_source["reasons"]))
            changed_conflict = copy.deepcopy(decided)
            changed_conflict["conflicts"][0]["explanation"] = "Updated discrepancy note."
            stale_conflict = facts_readiness(root, changed_conflict)
            self.assertFalse(stale_conflict["ready"])
            self.assertTrue(any("stale evidence" in reason for reason in stale_conflict["reasons"]))

    def test_unresolved_conflict_blocks_only_this_record(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = _brolls(tmp)
            digest = _write(root, "graphics-data/reserves.csv", DATA_BYTES)
            blocked = normalize_facts(root, _payload("graphics-data/reserves.csv", digest))
            other = normalize_facts(root, _payload("graphics-data/reserves.csv", digest, with_conflict=False))
            self.assertFalse(facts_readiness(root, blocked)["ready"])
            self.assertTrue(any("unresolved" in reason for reason in facts_readiness(root, blocked)["reasons"]))
            self.assertTrue(facts_readiness(root, other)["ready"])

    def test_second_conflict_remains_blocking_after_one_decision(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = _brolls(tmp)
            digest = _write(root, "graphics-data/reserves.csv", DATA_BYTES)
            payload = _payload("graphics-data/reserves.csv", digest)
            payload["conflicts"].append(
                _conflict(
                    id="second-gap",
                    explanation="A second discrepancy still needs a decision.",
                    proposed_correction="State the 2020 proved-reserves figure with its source.",
                )
            )
            record = normalize_facts(root, payload)
            updated = resolve_conflict(
                record,
                "reserves-gap",
                "accept_correction",
                "Editor Name",
                "Resolve only the first gap.",
            )
            ready = facts_readiness(root, updated)
            self.assertFalse(ready["ready"])
            self.assertTrue(any("second-gap" in reason and "unresolved" in reason for reason in ready["reasons"]))
            self.assertEqual(ORIGINAL_NARRATION, updated["conflicts"][0]["original_narration"])
            self.assertEqual(ORIGINAL_NARRATION, updated["conflicts"][1]["original_narration"])


if __name__ == "__main__":
    unittest.main()
