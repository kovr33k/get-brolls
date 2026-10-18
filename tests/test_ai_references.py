"""Private AI reference storage, exact targets, and derivative integrity."""

import copy
import hashlib
import json
import os
import subprocess
import tempfile
import threading
import unittest
from pathlib import Path

import _isolation  # noqa: F401
import _paths  # noqa: F401
from _isolation import symlink_or_skip
from _media import skip_unless_ffmpeg, synth_image

from getbrolls.ai_references import (
    FRAME_SAMPLES,
    MAX_VIDEO_BYTES,
    attach_reference,
    freeze_inputs,
    handoff,
    read_derivative,
    read_original,
    record_inspection,
    record_invalidation,
    remove_reference,
    replace_reference,
    show_reference,
    show_saved,
    unreceived_attachment,
)
from getbrolls.ai_state import (
    attach_result,
    import_plan,
    new_job,
    select,
    version_signature,
)
from getbrolls.graphics_references import MAX_IMAGE_BYTES
from getbrolls.ledger import Ledger, digest
from getbrolls.runtime import project_lock
from getbrolls.serve import ALLOWED_GET_FOLDERS

_CHANNEL_HIGH = 150
_CHANNEL_LOW = 80
_RGB_BYTES = 3
_MIN_TONE_DURATION = 3.5
_OPENING_STAMP = 0.2
_LATER_STAMP = 3.0
_RED_START = 0.2
_RED_END = 1.0
_BLUE_START = 2.6
_BLUE_END = 3.4
_AFTER_OPENING = 1


def plan():
    return {
        "scenario": "One resource is running out. A second passage needs a picture.",
        "style": "Restrained editorial realism, cool night lighting.",
        "beats": [
            {
                "id": "beat-1",
                "route": "ai",
                "text": "One resource is running out.",
                "purpose": "Illustrate scarcity without pretending to document an event.",
                "alternatives": ["An empty reservoir", "A final drop in a pipe", "One container in an empty warehouse"],
            },
            {
                "id": "beat-2",
                "route": "ai",
                "text": "A second passage needs a picture.",
                "purpose": "Show the remaining supply without inventing an event.",
                "alternatives": ["A closed valve", "A marked gauge", "A single spare canister"],
            },
        ],
    }


def _open_project(case):
    temp = tempfile.TemporaryDirectory()
    case.addCleanup(temp.cleanup)
    project = Path(temp.name)
    ledger = Ledger(project)
    import_plan(ledger, plan())
    return temp, project, ledger


def _payload(ledger, body, **extra):
    beat_id = extra.pop("beat", "beat-1")
    beat = ledger.data["ai"]["beats"][beat_id]
    length = extra.pop("length", len(body) if isinstance(body, (bytes, bytearray)) else None)
    payload = {
        "beat": beat_id,
        "fingerprint": extra.pop("fingerprint", beat["fingerprint"]),
        "identity": "ref-reservoir",
        "name": "reservoir.png",
        "declared_type": "image/png",
        "body": body,
        "length": length,
        "instructions": "Keep the empty reservoir and the cool night light.",
        "role": "appearance",
    }
    payload.update(extra)
    return payload


def _locked(project, call):
    with project_lock(project):
        return call()


def _mean(path, stamp=None):
    dest = Path(str(path) + ".mean.rgb")
    command = ["ffmpeg", "-v", "error", "-y", "-i", str(path)]
    if stamp is not None:
        command.extend(["-ss", f"{float(stamp):.6f}"])
    command.extend(["-frames:v", "1", "-vf", "scale=1:1:flags=area", "-f", "rawvideo", "-pix_fmt", "rgb24", str(dest)])
    subprocess.run(command, check=True)
    data = dest.read_bytes()
    dest.unlink(missing_ok=True)
    if len(data) < _RGB_BYTES:
        raise AssertionError("frame mean was not readable")
    return data[0], data[1], data[2]


def _encode_png(path, compression):
    subprocess.run(
        [
            "ffmpeg",
            "-v",
            "error",
            "-y",
            "-f",
            "lavfi",
            "-i",
            "color=c=red:s=16x16",
            "-frames:v",
            "1",
            "-compression_level",
            str(compression),
            str(path),
        ],
        check=True,
    )


def _two_tone(path):
    subprocess.run(
        [
            "ffmpeg",
            "-v",
            "error",
            "-y",
            "-f",
            "lavfi",
            "-i",
            "color=c=red:s=64x64:r=10:d=2",
            "-f",
            "lavfi",
            "-i",
            "color=c=blue:s=64x64:r=10:d=2",
            "-filter_complex",
            "[0:v][1:v]concat=n=2:v=1:a=0",
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            str(path),
        ],
        check=True,
    )


def _duration(path):
    raw = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "json", str(path)],
        check=True,
        capture_output=True,
        text=True,
    )
    return float(json.loads(raw.stdout)["format"]["duration"])


def _flip(path):
    data = path.read_bytes()
    changed = data[:-1] + bytes([data[-1] ^ 1])
    path.write_bytes(changed)
    return data


def _keys(value):
    if isinstance(value, dict):
        for key, item in value.items():
            yield key
            yield from _keys(item)
    elif isinstance(value, list):
        for item in value:
            yield from _keys(item)


def _derivative_hashes(public):
    derivative = public["derivative"]
    values = [derivative.get("sha256"), derivative.get("clip_sha256"), derivative.get("sheet_sha256")]
    values.extend(frame.get("sha256") for frame in derivative.get("frames") or [])
    return sorted({item for item in values if isinstance(item, str)})


def _junction(link, target):
    link.parent.mkdir(parents=True, exist_ok=True)
    done = subprocess.run(
        ["cmd", "/c", "mklink", "/J", str(link), str(target)],
        capture_output=True,
        text=True,
        check=False,
    )
    return done.returncode == 0 and (link.exists() or link.is_symlink())


def _remove_link(link):
    if not link.exists() and not link.is_symlink():
        return
    if link.is_symlink():
        link.unlink()
        return
    try:
        link.rmdir()
    except OSError:
        link.unlink(missing_ok=True)


class _Unread:
    def read(self, _n=-1):
        raise AssertionError("the upload was read")


class ReferenceGuardTests(unittest.TestCase):
    def setUp(self):
        self.temp, self.project, self.ledger = _open_project(self)

    def _manifest(self):
        return self.ledger.path.read_bytes()

    def test_browser_path_is_not_a_received_file(self):
        before = self._manifest()
        notice = unreceived_attachment(r"C:\fakepath\shot.png")
        self.assertEqual("not_received", notice["state"])
        self.assertFalse(notice["received"])
        self.assertFalse(notice["transferred"])
        self.assertFalse(notice["stored"])
        self.assertEqual("shot.png", notice["name"])
        self.assertEqual("unsupported", notice["provider_input"])
        with self.assertRaisesRegex(ValueError, "has not received"):
            _locked(self.project, lambda: attach_reference(self.ledger, _payload(self.ledger, r"C:\fakepath\shot.png")))
        self.assertEqual(before, self._manifest())
        self.assertEqual({}, self.ledger.data["ai"]["jobs"])

    def test_incomplete_mismatched_and_oversized_uploads_are_not_saved(self):
        before = copy.deepcopy(self.ledger.data)
        manifest = self._manifest()
        cases = [
            (_payload(self.ledger, b""), "Incomplete"),
            (_payload(self.ledger, b"\xff\xd8\xff\xe0" + b"\x00" * 16, declared_type="image/png"), "does not match"),
            (
                _payload(self.ledger, _Unread(), length=MAX_IMAGE_BYTES + 1, declared_type="image/png"),
                "technical limit",
            ),
            (
                _payload(
                    self.ledger, _Unread(), length=MAX_VIDEO_BYTES + 1, declared_type="video/mp4", name="clip.mp4"
                ),
                "resource limit",
            ),
        ]
        for payload, message in cases:
            with self.subTest(message=message):
                with self.assertRaisesRegex(ValueError, message):
                    _locked(self.project, lambda payload=payload: attach_reference(self.ledger, payload))
                self.assertEqual(before, self.ledger.data)
                self.assertEqual(manifest, self._manifest())
        with self.assertRaisesRegex(ValueError, "not a duration rule") as raised:
            attach_reference(
                self.ledger,
                _payload(
                    self.ledger, _Unread(), length=MAX_VIDEO_BYTES + 1, declared_type="video/mp4", name="clip.mp4"
                ),
            )
        self.assertIn("resource limit", str(raised.exception))

    def test_pending_journal_blocks_the_upload_and_stays_in_place(self):
        self.ledger.pending.write_text("{kept}", encoding="utf-8")
        manifest = self._manifest()
        with self.assertRaisesRegex(ValueError, "pending"):
            attach_reference(self.ledger, _payload(self.ledger, b"\x89PNG\r\n\x1a\nunused"))
        self.assertEqual("{kept}", self.ledger.pending.read_text(encoding="utf-8"))
        self.assertEqual(manifest, self._manifest())

    def test_shared_scope_without_instruction_does_not_expand_or_save(self):
        before = copy.deepcopy(self.ledger.data)
        with self.assertRaisesRegex(ValueError, "explicit scope instruction"):
            attach_reference(self.ledger, _payload(self.ledger, b"\x89PNG\r\n\x1a\nunused", scope="shared"))
        self.assertEqual(before, self.ledger.data)

    def test_image_interval_is_refused_before_a_save(self):
        before = copy.deepcopy(self.ledger.data)
        with self.assertRaisesRegex(ValueError, "do not take a video interval"):
            attach_reference(
                self.ledger,
                _payload(self.ledger, b"\x89PNG\r\n\x1a\nunused", interval={"start_s": 0, "end_s": 1}),
            )
        self.assertEqual(before, self.ledger.data)


@skip_unless_ffmpeg
class ReferenceMediaTests(unittest.TestCase):
    def setUp(self):
        self.temp, self.project, self.ledger = _open_project(self)
        self.work = Path(self.temp.name) / "media"
        self.work.mkdir()

    def _png(self, name="reservoir.png", color="red"):
        path = self.work / name
        synth_image(path, color=color, size="16x16")
        return path.read_bytes()

    def _attach(self, body, **extra):
        return _locked(self.project, lambda: attach_reference(self.ledger, _payload(self.ledger, body, **extra)))

    def _assert_public(self, public):
        blob = json.dumps(public)
        self.assertNotIn("ai-data", blob)
        self.assertNotIn("original_ref", blob)
        self.assertNotRegex(blob, r"[A-Za-z]:\\")
        self.assertFalse(
            set(_keys(public)) & {"ref", "path", "root", "original_ref", "clip_ref", "sheet_ref", "pixels_ref"}
        )

    def _assert_private_store(self, public):
        store = self.ledger.data["ai"]["references"]
        original = store["originals"][public["sha256"]]["ref"]
        derivative = store["derivatives"][public["derivative"]["id"]]
        rels = [original]
        rels.extend([derivative[key] for key in ("pixels_ref", "clip_ref", "sheet_ref") if derivative.get(key)])
        rels.extend([frame["ref"] for frame in derivative.get("frames") or []])
        for rel in rels:
            self.assertTrue(rel.startswith("ai-data/references/"))
            self.assertNotIn(rel.split("/", 1)[0], ALLOWED_GET_FOLDERS)
            self.assertTrue((self.ledger.root / rel).is_file())

    def _assert_no_generation(self):
        ai = self.ledger.data["ai"]
        self.assertEqual({}, ai["jobs"])
        self.assertEqual({}, ai["versions"])
        self.assertNotIn("approval", ai)

    def test_png_and_jpeg_stay_private_and_exact_retry_reuses_the_original(self):
        png = self._png()
        jpeg_path = self.work / "reservoir.jpg"
        synth_image(jpeg_path, color="navy", size="16x16")
        jpeg = jpeg_path.read_bytes()
        style = copy.deepcopy(self.ledger.data["ai"]["style"])
        saved = self._attach(png)
        self._assert_public(saved)
        self._assert_private_store(saved)
        self.assertEqual(png, read_original(self.ledger, saved["sha256"]))
        self.assertEqual("uninspected", saved["inspection"])
        self.assertIsNone(saved["findings"])
        self.assertFalse(saved["shared_style_applied"])
        self.assertEqual("unsupported", saved["provider_input"])
        self.assertFalse(saved["provider_access"])
        self.assertIsNone(saved["limits"]["duration_rule"])
        again = self._attach(png)
        self.assertEqual(saved["context_id"], again["context_id"])
        self.assertEqual("active", again["state"])
        self.assertEqual(1, len(self.ledger.data["ai"]["references"]["originals"]))
        self.assertEqual(1, len(list((self.ledger.root / "ai-data" / "references" / "originals").iterdir())))
        jpeg_saved = _locked(
            self.project,
            lambda: replace_reference(
                self.ledger,
                _payload(
                    self.ledger,
                    jpeg,
                    identity="ref-jpeg",
                    name="reservoir.jpg",
                    declared_type="image/jpeg",
                    instructions="Keep the navy field.",
                ),
            ),
        )
        self.assertEqual(jpeg, read_original(self.ledger, jpeg_saved["sha256"]))
        self.assertTrue(read_derivative(self.ledger, jpeg_saved["derivative"]["id"], "pixels").startswith(b"\x89PNG"))
        historical = show_saved(self.ledger, saved["context_id"])
        self.assertEqual("historical", historical["state"])
        self.assertEqual("Keep the empty reservoir and the cool night light.", historical["instructions"])
        self.assertEqual(png, read_original(self.ledger, historical["sha256"]))
        reloaded = show_reference(
            Ledger(self.project), "beat-1", self.ledger.data["ai"]["beats"]["beat-1"]["fingerprint"]
        )
        self.assertEqual(jpeg_saved["context_id"], reloaded["context_id"])
        self.assertEqual(style, self.ledger.data["ai"]["style"])
        self._assert_no_generation()
        manifest = self.ledger.path.read_bytes()
        show_reference(self.ledger, "beat-1", self.ledger.data["ai"]["beats"]["beat-1"]["fingerprint"])
        show_saved(self.ledger, saved["context_id"])
        handoff(self.ledger, saved["context_id"])
        self.assertEqual(manifest, self.ledger.path.read_bytes())

    def test_identical_pixels_do_not_reuse_a_different_original(self):
        loose = self.work / "loose.png"
        tight = self.work / "tight.png"
        _encode_png(loose, 0)
        _encode_png(tight, 9)
        loose_bytes = loose.read_bytes()
        tight_bytes = tight.read_bytes()
        self.assertNotEqual(loose_bytes, tight_bytes)
        self.assertEqual(_mean(loose), _mean(tight))
        first = self._attach(loose_bytes, instructions="First original bytes.")
        with self.assertRaisesRegex(ValueError, "different reference inputs"):
            self._attach(tight_bytes, instructions="First original bytes.")
        self.assertEqual([first["context_id"]], list(self.ledger.data["ai"]["references"]["contexts"]))
        self.assertEqual(loose_bytes, read_original(self.ledger, first["sha256"]))
        second = _locked(
            self.project,
            lambda: replace_reference(
                self.ledger,
                _payload(self.ledger, tight_bytes, identity="ref-tight", instructions="Second original bytes."),
            ),
        )
        self.assertNotEqual(first["sha256"], second["sha256"])
        self.assertEqual(loose_bytes, read_original(self.ledger, first["sha256"]))
        self.assertEqual(tight_bytes, read_original(self.ledger, second["sha256"]))
        self.assertEqual("First original bytes.", show_saved(self.ledger, first["context_id"])["instructions"])
        self.assertEqual("historical", show_saved(self.ledger, first["context_id"])["state"])

    def test_replace_and_remove_keep_historical_bytes_and_instructions(self):
        first_bytes = self._png("first.png", color="red")
        second_bytes = self._png("second.png", color="navy")
        self.assertNotEqual(first_bytes, second_bytes)
        self.assertTrue(first_bytes.startswith(b"\x89PNG\r\n\x1a\n"))
        self.assertTrue(second_bytes.startswith(b"\x89PNG\r\n\x1a\n"))
        first = self._attach(first_bytes, instructions="Hold the wide reservoir.")
        _locked(
            self.project,
            lambda: select(
                self.ledger,
                {
                    "beat": "beat-1",
                    "comment": "No people",
                    "expected": self.ledger.data["ai"]["beats"]["beat-1"]["fingerprint"],
                },
            ),
        )
        second = _locked(
            self.project,
            lambda: replace_reference(
                self.ledger,
                _payload(self.ledger, second_bytes, identity="ref-next", instructions="Move closer to the pipe."),
            ),
        )
        self.assertEqual("No people", self.ledger.data["ai"]["beats"]["beat-1"]["comment"])
        self.assertEqual("Hold the wide reservoir.", show_saved(self.ledger, first["context_id"])["instructions"])
        self.assertEqual(first_bytes, read_original(self.ledger, first["sha256"]))
        removed = _locked(
            self.project,
            lambda: remove_reference(
                self.ledger,
                {
                    "beat": "beat-1",
                    "fingerprint": self.ledger.data["ai"]["beats"]["beat-1"]["fingerprint"],
                },
            ),
        )
        self.assertEqual("absent", removed["state"])
        self.assertEqual("No people", self.ledger.data["ai"]["beats"]["beat-1"]["comment"])
        self.assertEqual("removed", show_saved(self.ledger, second["context_id"])["state"])
        self.assertEqual("historical", show_saved(self.ledger, first["context_id"])["state"])
        self.assertEqual(first_bytes, read_original(self.ledger, first["sha256"]))
        self.assertEqual(second_bytes, read_original(self.ledger, second["sha256"]))
        retry = self._attach(second_bytes, identity="ref-next", instructions="Move closer to the pipe.")
        self.assertEqual("removed", retry["state"])
        self.assertEqual(
            "absent",
            show_reference(self.ledger, "beat-1", self.ledger.data["ai"]["beats"]["beat-1"]["fingerprint"])["state"],
        )
        self._assert_no_generation()

    def test_text_revision_and_explicit_shared_scope_do_not_launch_or_retarget(self):
        body = self._png()
        style = copy.deepcopy(self.ledger.data["ai"]["style"])
        saved = self._attach(body, role="style")
        fingerprint = self.ledger.data["ai"]["beats"]["beat-1"]["fingerprint"]
        _locked(
            self.project,
            lambda: select(self.ledger, {"beat": "beat-1", "comment": "Hold the wide shot", "expected": fingerprint}),
        )
        shown = show_reference(self.ledger, "beat-1", fingerprint)
        self.assertEqual(saved["context_id"], shown["context_id"])
        self.assertEqual(saved["instructions"], shown["instructions"])
        self.assertEqual("Hold the wide shot", self.ledger.data["ai"]["beats"]["beat-1"]["comment"])
        self.assertEqual(style, self.ledger.data["ai"]["style"])
        shared = _locked(
            self.project,
            lambda: replace_reference(
                self.ledger,
                _payload(
                    self.ledger,
                    body,
                    identity="ref-shared",
                    scope="shared",
                    scope_instruction="Apply this grade only when the editor asks for the shared style.",
                    instructions="Cooler highlights.",
                ),
            ),
        )
        self.assertEqual("shared", shared["scope"])
        self.assertFalse(shared["shared_style_applied"])
        self.assertEqual(style, self.ledger.data["ai"]["style"])
        self.assertEqual("Cooler highlights.", show_reference(self.ledger, "beat-1", fingerprint)["instructions"])
        self.assertEqual(saved["instructions"], show_saved(self.ledger, saved["context_id"])["instructions"])
        self.assertEqual("historical", show_saved(self.ledger, saved["context_id"])["state"])
        self._assert_no_generation()

    def test_freeze_rejects_a_wrong_signature_and_does_not_follow_a_later_still(self):
        fingerprint = self.ledger.data["ai"]["beats"]["beat-1"]["fingerprint"]
        first = self._still("still-one", "first-still")
        second = self._still("still-two", "second-still")
        body = self._png()
        before = self.ledger.path.read_bytes()
        with self.assertRaisesRegex(ValueError, "not the displayed result"):
            self._attach(body, identity="ref-stale", still={"id": first["id"], "signature": version_signature(first)})
        self.assertNotIn("contexts", self.ledger.data["ai"].get("references") or {})
        self.assertEqual(before, self.ledger.path.read_bytes())
        bound = self._attach(body, still={"id": second["id"], "signature": version_signature(second)})
        self.assertTrue(bound["applies_to_displayed_still"])
        self.assertEqual(second["id"], bound["still"]["id"])
        jobs = set(self.ledger.data["ai"]["jobs"])
        with self.assertRaisesRegex(ValueError, "signature changed"):
            _locked(
                self.project,
                lambda: freeze_inputs(
                    self.ledger,
                    {
                        "beat": "beat-1",
                        "fingerprint": fingerprint,
                        "identity": "freeze-wrong",
                        "still": {"id": second["id"], "signature": "0" * 64},
                    },
                ),
            )
        self.assertEqual({}, self.ledger.data["ai"]["references"]["inputs"])
        frozen = _locked(
            self.project,
            lambda: freeze_inputs(
                self.ledger,
                {
                    "beat": "beat-1",
                    "fingerprint": fingerprint,
                    "identity": "freeze-right",
                    "still": {"id": second["id"], "signature": version_signature(second)},
                },
            ),
        )
        self.assertTrue(frozen["frozen"])
        self.assertEqual(bound["sha256"], frozen["sha256"])
        self.assertEqual(jobs, set(self.ledger.data["ai"]["jobs"]))
        third = self._still("still-three", "third-still")
        current = show_reference(self.ledger, "beat-1", fingerprint, second["id"])
        self.assertFalse(current["applies_to_displayed_still"])
        self.assertEqual(
            "absent",
            show_reference(self.ledger, "beat-1", fingerprint, third["id"])["state"],
        )
        self.assertEqual(bound["context_id"], current["context_id"])

    def test_freeze_rejects_altered_reference_bytes_without_a_snapshot(self):
        fingerprint = self.ledger.data["ai"]["beats"]["beat-1"]["fingerprint"]
        saved = self._attach(self._png())
        path = self.ledger.root / self.ledger.data["ai"]["references"]["originals"][saved["sha256"]]["ref"]
        original = _flip(path)
        with self.assertRaisesRegex(ValueError, "existing file was preserved"):
            _locked(
                self.project,
                lambda: freeze_inputs(
                    self.ledger,
                    {"beat": "beat-1", "fingerprint": fingerprint, "identity": "freeze-altered"},
                ),
            )
        self.assertEqual({}, self.ledger.data["ai"]["references"]["inputs"])
        self.assertEqual(path.read_bytes(), original[:-1] + bytes([original[-1] ^ 1]))
        reloaded = Ledger(self.project, recover=False)
        self.assertEqual({}, reloaded.data["ai"]["references"]["inputs"])

    def test_history_survives_inspection_replacement_and_frozen_invalidation(self):
        fingerprint = self.ledger.data["ai"]["beats"]["beat-1"]["fingerprint"]
        saved = self._attach(self._png(), instructions="Freeze this reservoir.")
        frozen = _locked(
            self.project,
            lambda: freeze_inputs(
                self.ledger,
                {"beat": "beat-1", "fingerprint": fingerprint, "identity": "freeze-live"},
            ),
        )
        snapshot = copy.deepcopy(self.ledger.data["ai"]["references"]["inputs"][frozen["input_id"]]["snapshot"])
        self.assertEqual("uninspected", handoff(self.ledger, saved["context_id"])["inspection"])
        self.assertEqual("unsupported", handoff(self.ledger, saved["context_id"])["provider_input"])
        inspected = _locked(
            self.project,
            lambda: record_inspection(
                self.ledger,
                {
                    "context": saved["context_id"],
                    "role": "appearance",
                    "source_sha256": saved["sha256"],
                    "derivative_sha256": _derivative_hashes(saved),
                    "findings": "The reservoir is empty and the light is cool.",
                },
            ),
        )
        self.assertEqual("inspected", inspected["inspection"])
        self.assertEqual("supplied", inspected["inspection_origin"])
        self.assertFalse(inspected["provider_access"])
        self.assertEqual("unsupported", handoff(self.ledger, frozen["input_id"])["provider_input"])
        self.assertEqual("uninspected", handoff(self.ledger, frozen["input_id"])["inspection"])
        self.assertEqual(snapshot, self.ledger.data["ai"]["references"]["inputs"][frozen["input_id"]]["snapshot"])
        _locked(
            self.project,
            lambda: record_invalidation(
                self.ledger,
                {
                    "beat": "beat-1",
                    "fingerprint": fingerprint,
                    "affected": [frozen["input_id"]],
                    "reason": "The frozen input no longer matches the editor's request.",
                    "identity": "inv-frozen",
                },
            ),
        )
        frozen_view = handoff(self.ledger, frozen["input_id"])
        live_view = handoff(self.ledger, saved["context_id"])
        self.assertTrue(frozen_view["invalidated"])
        self.assertIn("no longer matches", frozen_view["invalidation_reason"])
        self.assertFalse(live_view["invalidated"])
        self.assertEqual("active", show_reference(self.ledger, "beat-1", fingerprint)["state"])
        self.assertEqual(snapshot, self.ledger.data["ai"]["references"]["inputs"][frozen["input_id"]]["snapshot"])
        other = self._png("replacement.png", color="navy")
        self.assertNotEqual(other, read_original(self.ledger, saved["sha256"]))
        replaced = _locked(
            self.project,
            lambda: replace_reference(
                self.ledger,
                _payload(self.ledger, other, identity="ref-after-freeze", instructions="A later note."),
            ),
        )
        self.assertEqual("Freeze this reservoir.", show_saved(self.ledger, frozen["input_id"])["instructions"])
        self.assertEqual(saved["sha256"], show_saved(self.ledger, frozen["input_id"])["sha256"])
        self.assertEqual("A later note.", replaced["instructions"])
        self.assertEqual(snapshot, self.ledger.data["ai"]["references"]["inputs"][frozen["input_id"]]["snapshot"])
        self.assertEqual({}, self.ledger.data["ai"]["jobs"])

    def test_invalidation_stays_inside_the_declared_beat_and_fingerprint(self):
        fingerprint = self.ledger.data["ai"]["beats"]["beat-1"]["fingerprint"]
        other_fingerprint = self.ledger.data["ai"]["beats"]["beat-2"]["fingerprint"]
        first_body = self._png("beat-one.png", color="red")
        second_body = self._png("beat-two.png", color="navy")
        first = self._attach(first_body, identity="ref-beat-1")
        second = self._attach(
            second_body,
            beat="beat-2",
            identity="ref-beat-2",
            instructions="Keep the spare canister.",
        )
        before = copy.deepcopy(self.ledger.data["ai"]["references"])
        manifest = self.ledger.path.read_bytes()
        with self.assertRaisesRegex(ValueError, "not part of this beat"):
            _locked(
                self.project,
                lambda: record_invalidation(
                    self.ledger,
                    {
                        "beat": "beat-1",
                        "fingerprint": fingerprint,
                        "affected": [second["context_id"]],
                        "reason": "Wrong beat.",
                        "identity": "inv-cross",
                    },
                ),
            )
        self.assertEqual(before, self.ledger.data["ai"]["references"])
        self.assertEqual(manifest, self.ledger.path.read_bytes())
        self.assertEqual("active", show_reference(self.ledger, "beat-2", other_fingerprint)["state"])
        marked = _locked(
            self.project,
            lambda: record_invalidation(
                self.ledger,
                {
                    "beat": "beat-1",
                    "fingerprint": fingerprint,
                    "affected": [first["context_id"]],
                    "reason": "Only this beat changed.",
                    "identity": "inv-local",
                },
            ),
        )
        self.assertEqual([first["context_id"]], marked["affected"])
        self.assertFalse(marked["deleted_media"])
        self.assertEqual(first_body, read_original(self.ledger, first["sha256"]))
        self.assertEqual(second_body, read_original(self.ledger, second["sha256"]))
        other_shown = show_reference(self.ledger, "beat-2", other_fingerprint)
        self.assertEqual("active", other_shown["state"])
        self.assertEqual(second["context_id"], other_shown["context_id"])
        shown = show_reference(self.ledger, "beat-1", fingerprint)
        self.assertEqual("absent", shown["state"])
        self.assertEqual("historical", shown["preserved"][0]["state"])
        self.assertTrue(shown["preserved"][0]["invalidated"])
        old = fingerprint
        changed = plan()
        changed["beats"][0]["purpose"] = "A different intended explanation."
        _locked(self.project, lambda: import_plan(self.ledger, changed))
        current = self.ledger.data["ai"]["beats"]["beat-1"]["fingerprint"]
        self.assertNotEqual(old, current)
        with self.assertRaisesRegex(ValueError, "changed"):
            record_invalidation(
                self.ledger,
                {
                    "beat": "beat-1",
                    "fingerprint": old,
                    "affected": [first["context_id"]],
                    "reason": "Old fingerprint.",
                    "identity": "inv-old",
                },
            )
        with self.assertRaisesRegex(ValueError, "not part of this beat"):
            record_invalidation(
                self.ledger,
                {
                    "beat": "beat-1",
                    "fingerprint": current,
                    "affected": [first["context_id"]],
                    "reason": "Current fingerprint cannot adopt the old reference.",
                    "identity": "inv-current",
                },
            )
        self.assertEqual(first_body, read_original(self.ledger, first["sha256"]))
        self.assertEqual(second_body, read_original(self.ledger, second["sha256"]))
        self.assertNotIn("inv-old", self.ledger.data["ai"]["references"].get("invalidations", {}))
        drifted = show_reference(self.ledger, "beat-1", current)
        self.assertEqual("absent", drifted["state"])
        self.assertFalse(drifted["preserved"][0]["applies_to_current_fingerprint"])
        with self.assertRaisesRegex(ValueError, "changed"):
            show_reference(self.ledger, "beat-1", old)

    def test_inspection_does_not_persist_when_original_or_derivative_bytes_change(self):
        saved = self._attach(self._png())
        store = self.ledger.data["ai"]["references"]
        original = self.ledger.root / store["originals"][saved["sha256"]]["ref"]
        pixels = self.ledger.root / store["derivatives"][saved["derivative"]["id"]]["pixels_ref"]
        payload = {
            "context": saved["context_id"],
            "role": "appearance",
            "source_sha256": saved["sha256"],
            "derivative_sha256": _derivative_hashes(saved),
            "findings": "Supplied only after the bytes match.",
        }
        events = (self.ledger.root / "events.jsonl").read_bytes()
        for path in (original, pixels):
            with self.subTest(path=path.name):
                kept = path.read_bytes()
                try:
                    _flip(path)
                    with self.assertRaisesRegex(ValueError, "existing file was preserved"):
                        _locked(self.project, lambda: record_inspection(self.ledger, payload))
                    self.assertEqual({"state": "uninspected"}, store["contexts"][saved["context_id"]]["inspection"])
                    reloaded = Ledger(self.project, recover=False)
                    self.assertEqual(
                        {"state": "uninspected"},
                        reloaded.data["ai"]["references"]["contexts"][saved["context_id"]]["inspection"],
                    )
                    self.assertEqual(events, (self.ledger.root / "events.jsonl").read_bytes())
                finally:
                    path.write_bytes(kept)
        wrong = dict(payload, derivative_sha256=["0" * 64])
        with self.assertRaisesRegex(ValueError, "stays uninspected"):
            record_inspection(self.ledger, wrong)
        self.assertEqual({"state": "uninspected"}, store["contexts"][saved["context_id"]]["inspection"])

    def test_altered_occupied_original_is_preserved(self):
        body = self._png()
        saved = self._attach(body)
        path = self.ledger.root / self.ledger.data["ai"]["references"]["originals"][saved["sha256"]]["ref"]
        _flip(path)
        flipped = path.read_bytes()
        before = copy.deepcopy(self.ledger.data)
        manifest = self.ledger.path.read_bytes()
        with self.assertRaisesRegex(ValueError, "existing file was preserved"):
            self._attach(body, beat="beat-2", identity="ref-other", name="spare.png")
        self.assertEqual(flipped, path.read_bytes())
        self.assertEqual(before, self.ledger.data)
        self.assertEqual(manifest, self.ledger.path.read_bytes())
        self.assertEqual([saved["context_id"]], list(self.ledger.data["ai"]["references"]["contexts"]))
        self.assertEqual([], self.ledger.data["ai"]["beats"]["beat-2"].get("references") or [])
        with self.assertRaisesRegex(ValueError, "existing file was preserved"):
            show_reference(
                self.ledger,
                "beat-1",
                self.ledger.data["ai"]["beats"]["beat-1"]["fingerprint"],
            )

    def test_probeable_corrupt_image_is_rejected_without_a_context(self):
        corrupt = self._png() + b"\x00"
        before = copy.deepcopy(self.ledger.data)
        manifest = self.ledger.path.read_bytes()
        with self.assertRaises(ValueError) as raised:
            self._attach(corrupt)
        message = str(raised.exception)
        self.assertIn("could not be decoded", message)
        self.assertNotIn("ffmpeg", message)
        self.assertNotIn(str(self.ledger.root), message)
        self.assertEqual(before, self.ledger.data)
        self.assertEqual(manifest, self.ledger.path.read_bytes())
        self.assertFalse(any(self.ledger.root.glob(".ai-ref-*")))
        self.assertFalse((self.ledger.root / "ai-data").exists())

    def test_decode_escape_link_and_junction_do_not_publish(self):
        before = copy.deepcopy(self.ledger.data)
        with self.assertRaisesRegex(ValueError, "could not be decoded|PNG or JPEG"):
            self._attach(b"\x89PNG\r\n\x1a\nnot-a-png")
        self.assertEqual(before, self.ledger.data)
        self.assertFalse(any(self.ledger.root.glob(".ai-ref-*")))
        saved = self._attach(self._png())
        row = self.ledger.data["ai"]["references"]["originals"][saved["sha256"]]
        original_ref = row["ref"]
        row["ref"] = "../manifest.json"
        with self.assertRaisesRegex(ValueError, "escapes the private store"):
            read_original(self.ledger, saved["sha256"])
        row["ref"] = "ai-data/references/originals/../../manifest.json"
        with self.assertRaisesRegex(ValueError, "escapes the private store"):
            read_original(self.ledger, saved["sha256"])
        row["ref"] = original_ref
        self.assertTrue(read_original(self.ledger, saved["sha256"]).startswith(b"\x89PNG"))

    def test_symlink_and_junction_are_not_followed(self):
        body = self._png("linked.png")
        sha = hashlib.sha256(body).hexdigest()
        outside = self.work / "outside-target.png"
        outside.write_bytes(b"sentinel-outside")
        dest = self.ledger.root / "ai-data" / "references" / "originals" / f"{sha}.png"
        dest.parent.mkdir(parents=True)
        self.addCleanup(lambda: dest.unlink(missing_ok=True) if dest.is_symlink() else None)
        symlink_or_skip(dest, outside)
        with self.assertRaisesRegex(ValueError, "symlink or junction"):
            self._attach(body, identity="ref-link")
        self.assertEqual(b"sentinel-outside", outside.read_bytes())
        self.assertFalse(self.ledger.data["ai"].get("references", {}).get("contexts"))

    def test_junction_is_refused_without_symlink_privilege(self):
        if os.name != "nt":
            self.skipTest("Windows junction coverage")
        body = self._png("junction.png")
        canary_dir = self.work / "junction-target"
        canary_dir.mkdir()
        (canary_dir / "canary.txt").write_text("keep", encoding="utf-8")
        junction = self.ledger.root / "ai-data" / "references" / "originals"
        self.addCleanup(lambda: _remove_link(junction))
        if not _junction(junction, canary_dir):
            self.skipTest("could not create a junction")
        with self.assertRaisesRegex(ValueError, "symlink or junction"):
            self._attach(body, identity="ref-junction")
        self.assertEqual(["canary.txt"], sorted(path.name for path in canary_dir.iterdir()))
        self.assertFalse((self.ledger.data["ai"].get("references") or {}).get("contexts"))

    def test_project_lock_serializes_reference_writes(self):
        body = self._png()
        started = threading.Event()
        release = threading.Event()
        holder = []
        other = []

        def hold():
            try:
                with project_lock(self.project):
                    started.set()
                    attach_reference(self.ledger, _payload(self.ledger, body, identity="ref-locked"))
                    if not release.wait(10):
                        holder.append("timeout")
            except Exception as exc:  # noqa: BLE001 - the test records the holder failure
                holder.append(repr(exc))
            finally:
                started.set()

        def rival():
            if not started.wait(10):
                other.append("not started")
                return
            try:
                with project_lock(self.project):
                    other.append("acquired")
            except ValueError as exc:
                other.append(str(exc))
            finally:
                release.set()

        first = threading.Thread(target=hold)
        second = threading.Thread(target=rival)
        first.start()
        second.start()
        first.join(15)
        second.join(15)
        self.assertFalse(first.is_alive())
        self.assertFalse(second.is_alive())
        self.assertEqual([], holder)
        self.assertEqual(1, len(other))
        self.assertIn("Outro comando está usando este projeto", other[0])
        saved = Ledger(self.project)
        self.assertEqual(1, len(saved.data["ai"]["references"]["contexts"]))

    def _moving_source(self):
        path = self.work / "moving.mp4"
        _two_tone(path)
        self.assertGreater(_duration(path), _MIN_TONE_DURATION)
        self._assert_red(_mean(path, _OPENING_STAMP))
        self._assert_blue(_mean(path, _LATER_STAMP))
        return path

    def _attach_video(self, body, **extra):
        fields = {"name": "moving.mp4", "declared_type": "video/mp4", "role": "motion"}
        fields.update(extra)
        return self._attach(body, **fields)

    def test_rejected_video_intervals_do_not_save(self):
        path = self._moving_source()
        body = path.read_bytes()
        before = copy.deepcopy(self.ledger.data)
        failures = [
            ({}, "finite start_s"),
            ({"content": "the push near the end"}, "finite start_s"),
            ({"start_s": float("nan"), "end_s": _BLUE_END}, "not a positive finite"),
            ({"start_s": _RED_END + _OPENING_STAMP, "end_s": 10}, "not truncated"),
        ]
        for interval, message in failures:
            with self.subTest(interval=sorted(interval)):
                with self.assertRaisesRegex(ValueError, message) as raised:
                    self._attach_video(body, identity="ref-bad-interval", interval=interval)
                self.assertIn("opening was not used", str(raised.exception))
                self.assertEqual(before, self.ledger.data)
                self.assertFalse((self.ledger.root / "ai-data" / "references" / "derivatives").exists())

    def test_requested_video_interval_is_not_the_opening(self):
        path = self._moving_source()
        body = path.read_bytes()
        fingerprint = self.ledger.data["ai"]["beats"]["beat-1"]["fingerprint"]
        saved = self._attach_video(
            body,
            identity="ref-blue",
            interval={"start_s": _BLUE_START, "end_s": _BLUE_END, "content": "the blue field after the cut"},
        )
        self._assert_public(saved)
        self._assert_private_store(saved)
        self.assertFalse(saved["opening_was_used"])
        self.assertFalse(saved["interval_truncated"])
        self.assertTrue(saved["derivative"]["opening_distinct"])
        self.assertEqual(body, read_original(self.ledger, saved["sha256"]))
        self.assertNotEqual(saved["sha256"], saved["derivative"]["clip_sha256"])
        self.assertFalse(saved["audio"])
        self.assertFalse(saved["derivative"]["audio_kept"])
        self.assertEqual(fingerprint, saved["fingerprint"])
        self.assertEqual(_BLUE_START, saved["interval"]["start_s"])
        self.assertEqual(_BLUE_END, saved["interval"]["end_s"])
        times = [frame["time_s"] for frame in saved["derivative"]["frames"]]
        self.assertEqual(FRAME_SAMPLES, len(times))
        self.assertTrue(all(_BLUE_START <= stamp < _BLUE_END for stamp in times))
        self.assertTrue(all(stamp > _AFTER_OPENING for stamp in times))
        for frame in saved["derivative"]["frames"]:
            raw = read_derivative(self.ledger, saved["derivative"]["id"], "frame", frame["index"])
            sample = self.work / f"frame-{frame['index']}.png"
            sample.write_bytes(raw)
            self._assert_blue(_mean(sample))
        clip = self.work / "clip.mp4"
        clip.write_bytes(read_derivative(self.ledger, saved["derivative"]["id"], "clip"))
        sheet = self.work / "sheet.png"
        sheet.write_bytes(read_derivative(self.ledger, saved["derivative"]["id"], "sheet"))
        self._assert_blue(_mean(clip, 0))
        self._assert_blue(_mean(sheet))
        self._assert_red(_mean(path, 0))
        self._assert_no_generation()

    def test_opening_interval_frames_differ_from_the_later_interval(self):
        path = self._moving_source()
        body = path.read_bytes()
        saved = self._attach_video(
            body,
            identity="ref-blue",
            interval={"start_s": _BLUE_START, "end_s": _BLUE_END, "content": "the blue field after the cut"},
        )
        red = _locked(
            self.project,
            lambda: replace_reference(
                self.ledger,
                _payload(
                    self.ledger,
                    body,
                    name="moving.mp4",
                    declared_type="video/mp4",
                    identity="ref-red",
                    role="motion",
                    interval={"start_s": _RED_START, "end_s": _RED_END, "content": "the opening red field"},
                ),
            ),
        )
        self.assertFalse(red["opening_was_used"])
        red_frame = read_derivative(self.ledger, red["derivative"]["id"], "frame", 0)
        red_path = self.work / "red-frame.png"
        red_path.write_bytes(red_frame)
        self._assert_red(_mean(red_path))
        blue_frame = read_derivative(self.ledger, saved["derivative"]["id"], "frame", 0)
        blue_path = self.work / "blue-frame.png"
        blue_path.write_bytes(blue_frame)
        self._assert_blue(_mean(blue_path))
        self.assertNotEqual(red_frame, blue_frame)
        self.assertEqual("historical", show_saved(self.ledger, saved["context_id"])["state"])
        self.assertEqual(body, read_original(self.ledger, saved["sha256"]))
        self._assert_no_generation()

    def test_altered_video_derivatives_stay_uninspected(self):
        path = self._moving_source()
        saved = self._attach_video(
            path.read_bytes(),
            identity="ref-blue",
            interval={"start_s": _BLUE_START, "end_s": _BLUE_END, "content": "the blue field after the cut"},
        )
        store = self.ledger.data["ai"]["references"]["derivatives"][saved["derivative"]["id"]]
        events = (self.ledger.root / "events.jsonl").read_bytes()
        parts = (
            ("clip", store["clip_ref"]),
            ("sheet", store["sheet_ref"]),
            ("frame", store["frames"][0]["ref"]),
        )
        for label, rel in parts:
            with self.subTest(derivative=label):
                target = self.ledger.root / rel
                kept = target.read_bytes()
                try:
                    _flip(target)
                    with self.assertRaisesRegex(ValueError, "existing file was preserved"):
                        record_inspection(
                            self.ledger,
                            {
                                "context": saved["context_id"],
                                "role": "motion",
                                "source_sha256": saved["sha256"],
                                "derivative_sha256": _derivative_hashes(saved),
                                "findings": "This describes the blue field.",
                            },
                        )
                    inspected = self.ledger.data["ai"]["references"]["contexts"][saved["context_id"]]["inspection"]
                    self.assertEqual({"state": "uninspected"}, inspected)
                    self.assertEqual(events, (self.ledger.root / "events.jsonl").read_bytes())
                finally:
                    target.write_bytes(kept)

    def _assert_red(self, rgb):
        self.assertGreater(rgb[0], _CHANNEL_HIGH)
        self.assertLess(rgb[2], _CHANNEL_LOW)

    def _assert_blue(self, rgb):
        self.assertGreater(rgb[2], _CHANNEL_HIGH)
        self.assertLess(rgb[0], _CHANNEL_LOW)

    def _still(self, ident, nonce):
        path = self.ledger.root / "previews" / f"ai-{ident}.png"
        synth_image(path, color="red", size="8x8")
        sha = digest(path)
        beat = self.ledger.data["ai"]["beats"]["beat-1"]
        request = {
            "beat": "beat-1",
            "inputs": beat["fingerprint"],
            "kind": "image",
            "route": "gpt-subscription",
            "alternative": "option-1",
            "prompt": "A still for " + ident,
        }

        def save():
            job = new_job(self.ledger, request, nonce)
            version = {
                "id": ident,
                "beat": "beat-1",
                "kind": "image",
                "path": f"previews/ai-{ident}.png",
                "sha256": sha,
                "original_sha256": sha,
                "inputs": beat["fingerprint"],
                "width": 8,
                "height": 8,
                "codec": "png",
                "job": job["id"],
                "approval": {"state": "pending"},
            }
            attach_result(self.ledger, job, version)
            self.ledger.save("test-still")
            return version

        return _locked(self.project, save)
