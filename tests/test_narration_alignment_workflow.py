"""#59 public alignment workflow: full-track match, correction, render, VO/effects, regressions."""

from __future__ import annotations

import json
import re
import stat
import tempfile
import threading
import unittest
from pathlib import Path

import _isolation  # noqa: F401
from _cli import run_cli
from _media import skip_unless_ffmpeg
from _paths import ROOT
from test_graphics_audio_workflow import (
    AUDIO_ENV,
    FX_HZ,
    _assert_decoded_fx_without_vo,
    _assert_effects_job,
    _assert_no_media_autoplay,
    _assert_package_excludes_vo,
    _wav,
)
from test_graphics_review import _project, _review_payload, _write_review
from test_narration import (
    _analyze_complete,
    _assert_clean,
    _env,
    _file_hashes,
    _Handler,
    _Server,
    _State,
    _stop,
    _write_wav,
)

from getbrolls.cli import FORMAT_GATE_SUBCOMMANDS
from getbrolls.graphics import seconds_to_frame
from getbrolls.ledger import Ledger
from getbrolls.ledger import digest as file_digest
from getbrolls.runtime import READ_ONLY_COMMANDS

ANALYSIS_ID = "na-full"
FPS = 30
FILLER = ("and", "then", "some", "bridging", "material", "continues", "here")
STATEMENT = "Synthetic fixture: I approve this exact version."
CORRECTION = "Synthetic fixture: I confirm this bounded interval already received."
SHIFT_CORRECTION = "Synthetic fixture: I shift these clocks without changing duration."
SILENT_ENV = {"GB_GRAPHICS_WORKER": str(ROOT / "tests" / "fixtures" / "graphics_worker.py")}

PASSAGES = (
    {
        "occurrence": "stat-01",
        "narration": "The count stands at twelve units.",
        "chapter_context": "Opening numeric beat from the scenario.",
        "anchors": (),
        "expect": "resolved",
    },
    {
        "occurrence": "stat-rpt-2010",
        "narration": "The number rose.",
        "chapter_context": "First decade.",
        "anchors": ("In 2010",),
        "expect": "resolved",
    },
    {
        "occurrence": "stat-hello",
        "narration": "hello world now",
        "chapter_context": "Greeting spoken later than its narrative slot.",
        "anchors": (),
        "expect": "uncertain",
    },
    {
        "occurrence": "stat-bye",
        "narration": "goodbye moon today",
        "chapter_context": "Farewell spoken earlier than its narrative slot.",
        "anchors": (),
        "expect": "uncertain",
    },
    {
        "occurrence": "stat-long",
        "narration": "the market grew quickly",
        "chapter_context": "Long competing span.",
        "anchors": (),
        "expect": "uncertain",
    },
    {
        "occurrence": "stat-short",
        "narration": "the market grew",
        "chapter_context": "Short competing span.",
        "anchors": (),
        "expect": "uncertain",
    },
    {
        "occurrence": "stat-miss",
        "narration": "This clause was never recorded at all",
        "chapter_context": "Omitted passage kept in the scenario.",
        "anchors": (),
        "expect": "missing",
    },
    {
        "occurrence": "stat-rpt-2020",
        "narration": "The number rose.",
        "chapter_context": "Second decade after the intervening beats.",
        "anchors": ("In 2020",),
        "expect": "resolved",
    },
)
OCC_IDS = tuple(item["occurrence"] for item in PASSAGES)


class _ScriptState(_State):
    def __init__(self, project, script):
        super().__init__(project, "complete_after_poll")
        self.script = script


class _ScriptHandler(_Handler):
    def _result_payload(self, state):
        script = getattr(state, "script", None)
        if isinstance(script, dict):
            return script
        return super()._result_payload(state)


def _serving_script(project, script):
    state = _ScriptState(Path(project), script)
    server = _Server(("127.0.0.1", 0), _ScriptHandler, state)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, thread


def _write(path, text):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def _pad(tokens, repeats=8):
    padded = []
    for _ in range(repeats):
        padded.extend(FILLER)
    padded.extend(tokens)
    return padded


def _track_tokens():
    tokens = ["The", "count", "stands", "at", "twelve", "units"]
    tokens.extend(_pad(["In", "2010"], repeats=2))
    tokens.extend(["the", "number", "rose"])
    tokens.extend(["goodbye", "moon", "today"])
    tokens.extend(["the", "market", "grew", "quickly"])
    tokens.extend(_pad(["hello", "world", "now"], repeats=6))
    tokens.extend(_pad(["In", "2020"], repeats=12))
    tokens.extend(["the", "number", "rose"])
    return tokens


def _script_from_tokens(tokens, step_ms=300):
    stamps = []
    cursor = 0
    for token in tokens:
        stamps.append({"word": token, "startTimeMs": cursor, "endTimeMs": cursor + step_ms - 50})
        cursor += step_ms
    return {
        "transcript": " ".join(tokens),
        "language": "en",
        "usage": {"audioDurationMs": cursor, "modelId": "inworld/inworld-stt-1"},
        "segments": [{"wordTimestamps": stamps}],
    }, cursor / 1000.0


def _assign_passage(tmp, item, **flags):
    args = [
        "graphics-assign",
        "--scene",
        "numeric-stat",
        "--occurrence",
        item["occurrence"],
        "--chapter",
        "ch-1",
        "--chapter-context",
        flags.get("chapter_context", item["chapter_context"]),
        "--purpose",
        flags.get("purpose", "Show the beat"),
        "--narration",
        flags.get("narration", item["narration"]),
        "--timing",
        "estimated",
        "--duration",
        "3",
    ]
    anchors = flags.get("anchors", item["anchors"])
    for anchor in anchors:
        args += ["--anchor", anchor]
    if flags.get("confirm_fps") is not None:
        args += ["--confirm-fps", str(flags["confirm_fps"])]
    return run_cli(*args, project=tmp, expect=flags.get("expect", 0))


def _assign_all(tmp):
    for item in PASSAGES:
        _assign_passage(tmp, item)


def _match_cli(tmp, analysis_id, occurrences, env=None):
    args = ["narration-match", "--analysis", analysis_id]
    for occ_id in occurrences:
        args += ["--occurrence", occ_id]
    return run_cli(*args, project=tmp, env=env)


def _resolve_candidate(tmp, occurrence, candidate_id, env=None, statement=CORRECTION):
    return run_cli(
        "graphics-timing-resolve",
        "--occurrence",
        occurrence,
        "--candidate",
        candidate_id,
        "--by",
        "Human",
        "--statement",
        statement,
        project=tmp,
        env=env,
    )


def _resolve_interval(tmp, occurrence, start_s, end_s, env=None, statement=CORRECTION, expect=0):  # noqa: PLR0913, PLR0917 - CLI fixture preserves interval, actor statement, provider isolation and expected refusal.
    return run_cli(
        "graphics-timing-resolve",
        "--occurrence",
        occurrence,
        "--start",
        str(start_s),
        "--end",
        str(end_s),
        "--by",
        "Human",
        "--statement",
        statement,
        project=tmp,
        env=env,
        expect=expect,
    )


def _events(tmp):
    path = Path(tmp) / "brolls" / "events.jsonl"
    if not path.is_file():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def _event_ops(tmp):
    return [row.get("operation") for row in _events(tmp)]


def _item(status, occurrence):
    return next(row for row in status["graphics"]["items"] if row["occurrence_id"] == occurrence)


def _preview_paths(tmp, occurrence=None):
    folder = Path(tmp) / "brolls" / "previews"
    if not folder.is_dir():
        return []
    pattern = "alignment-" + (occurrence + "-" if occurrence else "") + "*.wav"
    return sorted(path for path in folder.glob(pattern) if path.is_file())


def _alignment_form_flags(html):
    return re.findall(
        r'<div class="graphics-alignment-correct"[^>]*data-alignment-editable="([01])"',
        html,
    )


def _playable_preview_refs(public):
    refs = []
    alignment = public or {}
    for item in alignment.get("candidates") or []:
        preview = item.get("preview") if isinstance(item, dict) else None
        if isinstance(preview, dict) and preview.get("ref"):
            refs.append(preview["ref"])
    override = alignment.get("override_preview")
    if not isinstance(override, dict):
        override = {}
    if override.get("ref") and not override.get("error"):
        refs.append(override["ref"])
    return refs


def _assert_no_missing_playable_preview(test, tmp, public):
    for ref in _playable_preview_refs(public):
        test.assertTrue(str(ref).startswith("previews/"))
        test.assertTrue((Path(tmp) / "brolls" / ref).is_file(), ref)


def _public_alignment(tmp, occurrence):
    return _item(run_cli("status", project=tmp), occurrence)["alignment"]


def _public_preview_candidate(public):
    for item in public.get("candidates") or []:
        if not isinstance(item, dict):
            continue
        start_s = item.get("start_s")
        end_s = item.get("end_s")
        preview = item.get("preview")
        if not isinstance(preview, dict):
            preview = {}
        ref = preview.get("ref")
        if start_s is None or end_s is None:
            continue
        duration_s = float(end_s) - float(start_s)
        if duration_s <= 0:
            continue
        if isinstance(ref, str) and ref.startswith("previews/"):
            return item, duration_s, ref
    raise AssertionError("public matching output has no bounded candidate preview")


def _preview_dest(tmp, ref):
    return Path(tmp) / "brolls" / ref


def _plant_valid_same_duration_wav(dest, duration_s):
    dest = Path(dest)
    frames = max(1, round(float(duration_s) * 8000))
    _write_wav(dest, frames=frames, rate=8000, byte=3)
    return dest.read_bytes(), file_digest(dest)


def _candidate_by_id(public, candidate_id):
    for item in public.get("candidates") or []:
        if isinstance(item, dict) and item.get("id") == candidate_id:
            return item
    raise AssertionError("public matching output is missing candidate " + str(candidate_id))


def _assert_occupied_preview_refused(test, tmp, occurrence, dest, ref, candidate_id):  # noqa: PLR0913, PLR0917 - Assert both original occupied bytes and exact public candidate/ref refusal.
    body = dest.read_bytes()
    digest_value = file_digest(dest)
    public = _public_alignment(tmp, occurrence)
    test.assertEqual(body, dest.read_bytes())
    test.assertEqual(digest_value, file_digest(dest))
    live = _candidate_by_id(public, candidate_id)
    test.assertEqual("occupied_preview", live.get("preview_error"))
    test.assertFalse(live.get("preview"))
    test.assertNotIn(ref, _playable_preview_refs(public))
    _assert_no_missing_playable_preview(test, tmp, public)
    payload = _review_payload(tmp)
    test.assertEqual(body, dest.read_bytes())
    test.assertEqual(digest_value, file_digest(dest))
    page = (Path(tmp) / "brolls" / "review.html").read_text(encoding="utf-8")
    test.assertIn("occupied_preview", page)
    test.assertIn("preview unavailable", page.lower())
    test.assertNotIn('src="' + ref + '"', page)
    row = next(item for item in payload["alignment"] if item["occurrence_id"] == occurrence)
    review_live = _candidate_by_id(row, candidate_id)
    test.assertEqual("occupied_preview", review_live.get("preview_error"))
    test.assertFalse((review_live.get("preview") or {}).get("ref"))


def _snapshot_rel(tmp):
    ledger = Ledger(tmp, recover=False)
    recording_id = ledger.data["narration"]["analyses"][ANALYSIS_ID]["recording_id"]
    return ledger.data["narration"]["recordings"][recording_id]["snapshot"]


def _result_path(tmp):
    ledger = Ledger(tmp, recover=False)
    rel = ledger.data["narration"]["analyses"][ANALYSIS_ID]["result"]["artifact"]
    return Path(tmp) / "brolls" / rel, ledger


def _plant_result_bytes(tmp, payload):
    path, ledger = _result_path(tmp)
    if isinstance(payload, (bytes, bytearray)):
        path.write_bytes(payload)
    else:
        path.write_text(json.dumps(payload), encoding="utf-8")
    analysis = ledger.data["narration"]["analyses"][ANALYSIS_ID]
    analysis["result"]["artifact_sha256"] = file_digest(path)
    ledger.save("fixture")
    return path


def _full_audio_payload(effect_ref, effect_sha, vo_ref, vo_sha, start_s, end_s):  # noqa: PLR0913, PLR0917 - Synthetic effect and private full-recording VO have separate identity and source clocks.
    return {
        "schema_version": 1,
        "effects": [
            {
                "id": "whip-1",
                "ref": effect_ref,
                "sha256": effect_sha,
                "source_url": "https://remotion.media/whip.wav",
                "terms_url": "https://www.remotion.dev/docs/sfx/whip",
                "license": "CC0-1.0",
                "conditions": "Permitted CC0 effect; viewing is not a download.",
                "rendered_use": "permitted",
                "raw_redistribution": "permitted",
                "start_frame": 0,
                "source_start_s": 0,
                "duration_s": 0.3,
                "gain": 1,
            }
        ],
        "vo": {
            "ref": vo_ref,
            "sha256": vo_sha,
            "kind": "full_recording",
            "source_start_s": start_s,
            "source_end_s": end_s,
            "gain": 1,
        },
    }


class NarrationAlignmentCommandContractTests(unittest.TestCase):
    def test_public_commands_are_outside_format_gates_and_status_is_read_only(self):
        self.assertNotIn("narration-match", FORMAT_GATE_SUBCOMMANDS)
        self.assertNotIn("graphics-timing-resolve", FORMAT_GATE_SUBCOMMANDS)
        self.assertNotIn("narration-match", READ_ONLY_COMMANDS)
        self.assertIn("status", READ_ONLY_COMMANDS)


@skip_unless_ffmpeg
class NarrationAlignmentWorkflowTests(unittest.TestCase):
    def test_full_track_match_correct_render_vo_effects_and_no_retranscription(self):  # noqa: PLR0915 - One full-recording lifecycle asserts matching, corrections, rendering, delivery and exactly one provider submission.
        with tempfile.TemporaryDirectory() as tmp:
            _project(tmp)
            _assign_all(tmp)
            script, duration_s = _script_from_tokens(_track_tokens())
            wav = _write_wav(Path(tmp) / "vo.wav", frames=int((duration_s + 1) * 8000))
            server, thread = _serving_script(tmp, script)
            try:
                env = _env(server)
                submitted, done = _analyze_complete(tmp, wav, env, ANALYSIS_ID)
                if done.get("state") != "completed":
                    done = run_cli("narration-resume", "--analysis", ANALYSIS_ID, project=tmp, env=env)
                self.assertEqual("completed", done["state"])
                self.assertIs(True, done.get("timing_resolved"))
                self.assertEqual(1, server.state.posts)
                self.assertFalse(submitted.get("reused"))
                matched = _match_cli(tmp, ANALYSIS_ID, OCC_IDS, env)
                self.assertIs(False, matched["retranscribed"])
                self.assertEqual(1, server.state.posts)
                self.assertEqual(list(OCC_IDS), matched["occurrences"])
                for item in PASSAGES:
                    record = matched["matches"][item["occurrence"]]
                    self.assertEqual(item["expect"], record["state"], item["occurrence"])
                    self.assertEqual(item["narration"], record["original_text"])
                    self.assertNotIn("confidence", json.dumps(record))
                unique = matched["matches"]["stat-01"]
                self.assertEqual("resolved", unique["state"])
                self.assertIsNotNone(unique["timing"])
                self.assertEqual("explicit", unique["timing"]["basis"])
                self.assertEqual("half_up_nonnegative", unique.get("frame_rounding"))
                start_s = unique["timing"]["start_s"]
                end_s = unique["timing"]["end_s"]
                start_frame = seconds_to_frame(start_s, FPS)
                end_frame = seconds_to_frame(end_s, FPS)
                self.assertEqual(start_frame, unique["timing"]["start_frame"])
                self.assertEqual(end_frame, unique["timing"]["end_frame"])
                self.assertEqual(max(1, end_frame - start_frame), unique["timing"]["duration_in_frames"])
                self.assertEqual("missing", matched["matches"]["stat-miss"]["state"])
                self.assertEqual([], matched["matches"]["stat-miss"]["candidates"])
                hello = matched["matches"]["stat-hello"]
                self.assertGreaterEqual(len(hello["candidates"]), 1)
                self.assertTrue(any(item["order_evidence"]["inverted"] for item in hello["candidates"]))
                self.assertGreater(
                    hello["candidates"][0]["start_s"],
                    matched["matches"]["stat-bye"]["candidates"][0]["end_s"],
                )
                competing = json.dumps(matched["matches"]["stat-long"]["candidates"])
                self.assertIn("the market", competing.lower())
                hashes_before = _file_hashes(Path(tmp) / "brolls")
                posts = server.state.posts
                status = run_cli("status", project=tmp)
                self.assertEqual(posts, server.state.posts)
                self.assertEqual(hashes_before, _file_hashes(Path(tmp) / "brolls"))
                self.assertEqual(1, status["narration"]["analyses"])
                self.assertIs(True, status["narration"]["current"]["timing_resolved"])
                self.assertEqual("resolved", _item(status, "stat-01")["alignment"]["state"])
                self.assertFalse(_item(status, "stat-miss")["deliverable"])
                self.assertIn("unresolved_alignment", _item(status, "stat-miss")["reasons"])
                preview_before = {path.as_posix() for path in _preview_paths(tmp)}
                review = run_cli("review", project=tmp)
                self.assertEqual(posts, server.state.posts)
                html = Path(tmp) / "brolls" / "review.html"
                page = html.read_text(encoding="utf-8")
                self.assertIn("Narration alignment state", page)
                self.assertIn("stat-miss", page)
                self.assertNotIn("narration/private", page)
                _assert_no_media_autoplay(self, page)
                self.assertEqual(preview_before, {path.as_posix() for path in _preview_paths(tmp)})
                _assert_clean(self, json.dumps(status), json.dumps(review), page)
                candidate_id = hello["candidates"][0]["id"]
                events_before = Path(tmp).joinpath("brolls", "events.jsonl").read_bytes()
                corrected = _resolve_candidate(tmp, "stat-hello", candidate_id, env)
                self.assertIs(False, corrected["retranscribed"])
                self.assertEqual("resolved", corrected["alignment"]["state"])
                self.assertEqual(candidate_id, corrected["alignment"]["selected_candidate_id"])
                self.assertEqual(1, server.state.posts)
                replay = _resolve_candidate(tmp, "stat-hello", candidate_id, env)
                self.assertTrue(replay.get("idempotent"))
                self.assertEqual(1, server.state.posts)
                self.assertEqual(
                    events_before.count(b"graphics-timing-resolve") + 1,
                    Path(tmp).joinpath("brolls", "events.jsonl").read_bytes().count(b"graphics-timing-resolve"),
                )
                _assign_passage(
                    tmp,
                    PASSAGES[0],
                    narration="The count stands at twelve units, revised.",
                )
                rematched = _match_cli(tmp, ANALYSIS_ID, OCC_IDS, env)
                self.assertIs(False, rematched["retranscribed"])
                self.assertEqual(1, server.state.posts)
                self.assertNotEqual(
                    unique["scenario_sha256"],
                    rematched["matches"]["stat-01"]["scenario_sha256"],
                )
                self.assertEqual(
                    unique["transcript_sha256"],
                    rematched["matches"]["stat-01"]["transcript_sha256"],
                )
                _assign_passage(tmp, PASSAGES[0])
                restored = _match_cli(tmp, ANALYSIS_ID, ["stat-01"], env)
                self.assertEqual("resolved", restored["matches"]["stat-01"]["state"])
                timing = restored["matches"]["stat-01"]["timing"]
                vo_rel = _snapshot_rel(tmp)
                vo_path = Path(tmp) / "brolls" / vo_rel
                fx = _wav(Path(tmp) / "brolls" / "sounds" / "whip.wav", FX_HZ, 1)
                audio_file = _write(
                    Path(tmp) / "brolls" / "audio-stat-01.json",
                    json.dumps(
                        _full_audio_payload(
                            "sounds/whip.wav",
                            file_digest(fx),
                            vo_rel,
                            file_digest(vo_path),
                            timing["start_s"],
                            timing["end_s"],
                        )
                    ),
                )
                run_cli("graphics-audio", "--occurrence", "stat-01", "--file", str(audio_file), project=tmp)
                rendered = run_cli("graphics-render", "--occurrence", "stat-01", project=tmp, env=AUDIO_ENV)
                self.assertFalse(rendered["approved"])
                version_dir = Path(tmp) / "brolls" / "graphics" / "numeric-stat" / rendered["version"]["id"]
                job = json.loads((version_dir / "job.json").read_text(encoding="utf-8"))
                _assert_effects_job(self, job)
                fingerprints = json.loads((version_dir / "fingerprints.json").read_text(encoding="utf-8"))
                self.assertIn("alignment", fingerprints)
                artifact = Path(tmp) / "brolls" / rendered["review"]
                _assert_decoded_fx_without_vo(self, artifact, tmp)
                run_cli(
                    "graphics-approve",
                    "--occurrence",
                    "stat-01",
                    "--version",
                    rendered["version"]["id"],
                    "--by",
                    "Human",
                    "--statement",
                    STATEMENT,
                    project=tmp,
                )
                delivered = run_cli("deliver", project=tmp)
                self.assertEqual(1, server.state.posts)
                self.assertTrue(delivered["graphics"])
                pkg = Path(tmp) / "entrega" / "graphics" / "numeric-stat" / "stat-01" / rendered["version"]["id"]
                _assert_package_excludes_vo(self, pkg)
                listed = "\n".join(str(path) for path in pkg.rglob("*"))
                self.assertNotIn("narration/private", listed)
            finally:
                _stop(server, thread)

    def test_status_review_keep_hashes_events_and_provider_counts(self):
        with tempfile.TemporaryDirectory() as tmp:
            _project(tmp)
            _assign_all(tmp)
            script, duration_s = _script_from_tokens(_track_tokens())
            wav = _write_wav(Path(tmp) / "vo.wav", frames=int((duration_s + 1) * 8000))
            server, thread = _serving_script(tmp, script)
            try:
                env = _env(server)
                _analyze_complete(tmp, wav, env, ANALYSIS_ID)
                _match_cli(tmp, ANALYSIS_ID, OCC_IDS, env)
                posts = server.state.posts
                self.assertEqual(1, posts)
                root = Path(tmp) / "brolls"
                before = _file_hashes(root)
                events_before = (root / "events.jsonl").read_bytes() if (root / "events.jsonl").is_file() else b""
                status = run_cli("status", project=tmp)
                self.assertEqual(posts, server.state.posts)
                self.assertEqual(before, _file_hashes(root))
                self.assertEqual(events_before, (root / "events.jsonl").read_bytes())
                preview_before = {path.as_posix() for path in _preview_paths(tmp)}
                run_cli("review", project=tmp)
                self.assertEqual(posts, server.state.posts)
                self.assertEqual(preview_before, {path.as_posix() for path in _preview_paths(tmp)})
                _assert_clean(self, json.dumps(status))
            finally:
                _stop(server, thread)

    def test_explicit_occurrence_order_and_group_reorder_invalidates_obsolete_context(self):
        with tempfile.TemporaryDirectory() as tmp:
            _project(tmp)
            _assign_all(tmp)
            script, duration_s = _script_from_tokens(_track_tokens())
            wav = _write_wav(Path(tmp) / "vo.wav", frames=int((duration_s + 1) * 8000))
            server, thread = _serving_script(tmp, script)
            try:
                env = _env(server)
                _analyze_complete(tmp, wav, env, ANALYSIS_ID)
                group = ["stat-rpt-2010", "stat-rpt-2020", "stat-01"]
                matched = _match_cli(tmp, ANALYSIS_ID, group, env)
                self.assertEqual(group, matched["occurrences"])
                self.assertEqual(0, matched["matches"]["stat-rpt-2010"]["order"])
                self.assertEqual(1, matched["matches"]["stat-rpt-2020"]["order"])
                self.assertEqual(2, matched["matches"]["stat-01"]["order"])
                first = matched["matches"]["stat-rpt-2010"]
                if first["state"] == "resolved":
                    candidate_id = first["selected_candidate_id"]
                else:
                    candidate_id = first["candidates"][0]["id"]
                _resolve_candidate(tmp, "stat-rpt-2010", candidate_id, env)
                rematched = _match_cli(tmp, ANALYSIS_ID, ["stat-01", "stat-rpt-2020"], env)
                self.assertEqual(["stat-01", "stat-rpt-2020"], rematched["occurrences"])
                self.assertEqual(0, rematched["matches"]["stat-01"]["order"])
                self.assertEqual(1, rematched["matches"]["stat-rpt-2020"]["order"])
                self.assertEqual(1, server.state.posts)
                status = run_cli("status", project=tmp)
                leftover = _item(status, "stat-rpt-2010")
                reasons = json.dumps(leftover.get("reasons") or []).lower()
                self.assertFalse(leftover["deliverable"])
                self.assertTrue(
                    "stale" in reasons or "unresolved" in reasons or "alignment" in reasons,
                    reasons,
                )
                refused = run_cli(
                    "graphics-timing-resolve",
                    "--occurrence",
                    "stat-rpt-2010",
                    "--candidate",
                    candidate_id,
                    "--by",
                    "Human",
                    "--statement",
                    CORRECTION,
                    project=tmp,
                    env=env,
                    expect=2,
                )
                dumped = json.dumps(refused, ensure_ascii=False).lower()
                self.assertTrue("stale" in dumped or "rematch" in dumped or "drift" in dumped)
                self.assertEqual(1, server.state.posts)
            finally:
                _stop(server, thread)

    def test_stale_result_recording_anchors_and_profile_block_correction(self):
        with tempfile.TemporaryDirectory() as tmp:
            _project(tmp)
            _assign_all(tmp)
            script, duration_s = _script_from_tokens(_track_tokens())
            wav = _write_wav(Path(tmp) / "vo.wav", frames=int((duration_s + 1) * 8000))
            server, thread = _serving_script(tmp, script)
            try:
                env = _env(server)
                _analyze_complete(tmp, wav, env, ANALYSIS_ID)
                matched = _match_cli(tmp, ANALYSIS_ID, ["stat-hello"], env)
                candidate_id = matched["matches"]["stat-hello"]["candidates"][0]["id"]
                path, ledger = _result_path(tmp)
                original = path.read_bytes()
                path.write_bytes(original + b" ")
                status = run_cli("status", project=tmp)
                reasons = json.dumps(_item(status, "stat-hello").get("reasons") or []).lower()
                self.assertTrue("result" in reasons or "stale" in reasons or "transcript" in reasons)
                self.assertFalse(_item(status, "stat-hello")["deliverable"])
                refused = run_cli(
                    "graphics-timing-resolve",
                    "--occurrence",
                    "stat-hello",
                    "--candidate",
                    candidate_id,
                    "--by",
                    "Human",
                    "--statement",
                    CORRECTION,
                    project=tmp,
                    env=env,
                    expect=2,
                )
                self.assertIn("error", refused)
                path.write_bytes(original)
                snap = Path(tmp) / "brolls" / _snapshot_rel(tmp)
                snap.write_bytes(snap.read_bytes() + b"x")
                status = run_cli("status", project=tmp)
                rec_reasons = json.dumps(_item(status, "stat-hello").get("reasons") or []).lower()
                self.assertTrue("recording" in rec_reasons or "stale" in rec_reasons)
                snap.write_bytes(snap.read_bytes()[:-1])
                _assign_passage(tmp, PASSAGES[2], anchors=("A different unused anchor",))
                status = run_cli("status", project=tmp)
                anchor_reasons = json.dumps(_item(status, "stat-hello").get("reasons") or []).lower()
                self.assertTrue("stale" in anchor_reasons or "scenario" in anchor_reasons)
                _assign_passage(tmp, PASSAGES[2])
                refused_profile = _assign_passage(tmp, PASSAGES[2], confirm_fps=24, expect=2)
                self.assertIn("30 fps", refused_profile["error"])
                status = run_cli("status", project=tmp)
                self.assertEqual(FPS, status["graphics"]["profile"]["fps"])
                self.assertEqual(1, server.state.posts)
                self.assertIs(ledger.data["narration"]["analyses"][ANALYSIS_ID]["result"]["timing_resolved"], True)
            finally:
                _stop(server, thread)

    def test_malformed_unreadable_and_confidence_artifacts_are_actionable(self):  # noqa: PLR0915 - Sequential artifact corruption cases retain one original saved transcript and provider-count control.
        with tempfile.TemporaryDirectory() as tmp:
            _project(tmp)
            _assign_all(tmp)
            script, duration_s = _script_from_tokens(_track_tokens())
            wav = _write_wav(Path(tmp) / "vo.wav", frames=int((duration_s + 1) * 8000))
            server, thread = _serving_script(tmp, script)
            try:
                env = _env(server)
                _analyze_complete(tmp, wav, env, ANALYSIS_ID)
                _match_cli(tmp, ANALYSIS_ID, ["stat-01"], env)
                path, _ledger = _result_path(tmp)
                intact = json.loads(path.read_text(encoding="utf-8"))
                _plant_result_bytes(tmp, [])
                status = run_cli("status", project=tmp)
                self.assertIn("graphics", status)
                self.assertFalse(_item(status, "stat-01")["deliverable"])
                refused = run_cli(
                    "narration-match",
                    "--analysis",
                    ANALYSIS_ID,
                    "--occurrence",
                    "stat-01",
                    project=tmp,
                    env=env,
                    expect=2,
                )
                self.assertIn("error", refused)
                _plant_result_bytes(tmp, None)
                status = run_cli("status", project=tmp)
                self.assertFalse(_item(status, "stat-01")["deliverable"])
                planted = dict(intact)
                planted["confidence"] = 0.9
                _plant_result_bytes(tmp, planted)
                status = run_cli("status", project=tmp)
                reasons = json.dumps(_item(status, "stat-01").get("reasons") or []).lower()
                self.assertTrue(
                    "incomplete" in reasons or "confidence" in reasons or "stale" in reasons or "transcript" in reasons
                )
                match_refused = run_cli(
                    "narration-match",
                    "--analysis",
                    ANALYSIS_ID,
                    "--occurrence",
                    "stat-01",
                    project=tmp,
                    env=env,
                    expect=2,
                )
                dumped = json.dumps(match_refused, ensure_ascii=False).lower()
                self.assertTrue("confidence" in dumped or "result" in dumped or "transcript" in dumped)
                planted_bool = dict(intact)
                planted_bool["timing_resolved"] = 1
                _plant_result_bytes(tmp, planted_bool)
                status = run_cli("status", project=tmp)
                bool_reasons = json.dumps(_item(status, "stat-01").get("reasons") or []).lower()
                self.assertFalse(_item(status, "stat-01")["deliverable"])
                self.assertTrue("stale" in bool_reasons or "transcript" in bool_reasons or "unresolved" in bool_reasons)
                missing = Path(tmp) / "brolls" / "narration" / "results" / (ANALYSIS_ID + ".json")
                payload = json.loads(missing.read_text(encoding="utf-8")) if missing.is_file() else intact
                _plant_result_bytes(tmp, payload)
                result_file, _ignored = _result_path(tmp)
                result_file.unlink()
                status = run_cli("status", project=tmp)
                missing_reasons = json.dumps(_item(status, "stat-01").get("reasons") or []).lower()
                self.assertTrue("missing" in missing_reasons or "result" in missing_reasons)
                _plant_result_bytes(tmp, intact)
                result_file, _ignored = _result_path(tmp)
                result_file.chmod(0)
                try:
                    status = run_cli("status", project=tmp)
                    self.assertIn("graphics", status)
                finally:
                    result_file.chmod(stat.S_IRUSR | stat.S_IWUSR | stat.S_IREAD | stat.S_IWRITE)
                self.assertEqual(1, server.state.posts)
            finally:
                _stop(server, thread)

    def test_same_duration_shifted_full_vo_requires_repair_and_keeps_old_version(self):
        with tempfile.TemporaryDirectory() as tmp:
            _project(tmp)
            _assign_all(tmp)
            script, duration_s = _script_from_tokens(_track_tokens())
            wav = _write_wav(Path(tmp) / "vo.wav", frames=int((duration_s + 1) * 8000))
            server, thread = _serving_script(tmp, script)
            try:
                env = _env(server)
                _analyze_complete(tmp, wav, env, ANALYSIS_ID)
                matched = _match_cli(tmp, ANALYSIS_ID, ["stat-01"], env)
                timing = matched["matches"]["stat-01"]["timing"]
                vo_rel = _snapshot_rel(tmp)
                fx = _wav(Path(tmp) / "brolls" / "sounds" / "whip.wav", FX_HZ, 1)
                audio_file = _write(
                    Path(tmp) / "brolls" / "audio-stat-01.json",
                    json.dumps(
                        _full_audio_payload(
                            "sounds/whip.wav",
                            file_digest(fx),
                            vo_rel,
                            file_digest(Path(tmp) / "brolls" / vo_rel),
                            timing["start_s"],
                            timing["end_s"],
                        )
                    ),
                )
                run_cli("graphics-audio", "--occurrence", "stat-01", "--file", str(audio_file), project=tmp)
                first = run_cli("graphics-render", "--occurrence", "stat-01", project=tmp, env=AUDIO_ENV)
                v1 = Path(tmp) / "brolls" / "graphics" / "numeric-stat" / first["version"]["id"]
                old = {rel.as_posix(): file_digest(rel) for rel in v1.rglob("*") if rel.is_file()}
                journal = Path(tmp) / "brolls" / "events.jsonl"
                journal_before = journal.read_bytes()
                shifted_start = float(timing["start_s"]) + 0.5
                shifted_end = float(timing["end_s"]) + 0.5
                self.assertEqual(
                    round(float(timing["end_s"]) - float(timing["start_s"]), 6),
                    round(shifted_end - shifted_start, 6),
                )
                resolved = _resolve_interval(
                    tmp, "stat-01", shifted_start, shifted_end, env, statement=SHIFT_CORRECTION
                )
                self.assertIs(False, resolved["retranscribed"])
                repair = json.dumps(resolved, ensure_ascii=False).lower()
                self.assertTrue(resolved.get("audio_duration_repair_required") or "repair" in repair)
                status = run_cli("status", project=tmp)
                reasons = json.dumps(_item(status, "stat-01")["reasons"])
                self.assertIn("audio_duration_repair_required", reasons)
                self.assertFalse(_item(status, "stat-01")["deliverable"])
                for rel, digest_value in old.items():
                    self.assertEqual(digest_value, file_digest(v1 / rel))
                journal_after = journal.read_bytes()
                self.assertEqual(journal_before, journal_after[: len(journal_before)])
                added_events = [json.loads(line) for line in journal_after[len(journal_before) :].splitlines()]
                self.assertIn("graphics-timing-resolve", [event["operation"] for event in added_events])
                self.assertEqual(1, server.state.posts)
            finally:
                _stop(server, thread)

    def test_preview_occupied_missing_and_extraction_failure_stay_actionable(self):  # noqa: PLR0915 - Retain state/hash controls across occupied, missing and failed excerpt recovery in one project.
        with tempfile.TemporaryDirectory() as tmp:
            _project(tmp)
            _assign_all(tmp)
            script, duration_s = _script_from_tokens(_track_tokens())
            wav = _write_wav(Path(tmp) / "vo.wav", frames=int((duration_s + 1) * 8000))
            server, thread = _serving_script(tmp, script)
            try:
                env = _env(server)
                _analyze_complete(tmp, wav, env, ANALYSIS_ID)
                matched = _match_cli(tmp, ANALYSIS_ID, ["stat-hello", "stat-bye"], env)
                self.assertIs(False, matched["retranscribed"])
                previews = _preview_paths(tmp, "stat-hello")
                self.assertTrue(previews)
                original = {path: path.read_bytes() for path in previews}
                for path in previews:
                    path.unlink()
                hashes_before = _file_hashes(Path(tmp) / "brolls")
                status = run_cli("status", project=tmp)
                self.assertEqual(hashes_before, _file_hashes(Path(tmp) / "brolls"))
                public = _item(status, "stat-hello")["alignment"]
                for cand in public.get("candidates") or []:
                    if cand.get("preview"):
                        ref = cand["preview"].get("ref")
                        self.assertTrue(ref and (Path(tmp) / "brolls" / ref).is_file())
                    else:
                        self.assertTrue(cand.get("preview_error"))
                _assert_no_missing_playable_preview(self, tmp, public)
                run_cli("review", project=tmp)
                page = (Path(tmp) / "brolls" / "review.html").read_text(encoding="utf-8")
                for path in previews:
                    self.assertNotIn(path.name, page)
                occupied = previews[0]
                occupied.parent.mkdir(parents=True, exist_ok=True)
                occupied.write_bytes(b"occupied-foreign-bytes")
                rematched = _match_cli(tmp, ANALYSIS_ID, ["stat-hello", "stat-bye"], env)
                self.assertEqual(1, server.state.posts)
                self.assertEqual(b"occupied-foreign-bytes", occupied.read_bytes())
                occupied_public = rematched["matches"]["stat-hello"]
                errors = [
                    item.get("preview_error")
                    for item in occupied_public.get("candidates") or []
                    if item.get("preview_error")
                ]
                status = run_cli("status", project=tmp)
                live = _item(status, "stat-hello")["alignment"]
                live_errors = [item.get("preview_error") for item in live.get("candidates") or []]
                self.assertTrue(errors or any(live_errors) or live.get("override_preview", {}).get("error"))
                _assert_no_missing_playable_preview(self, tmp, live)
                occupied.unlink()
                occupied.mkdir()
                rematched = _match_cli(tmp, ANALYSIS_ID, ["stat-hello"], env)
                self.assertTrue(occupied.is_dir())
                fail_public = rematched["matches"]["stat-hello"]
                fail_errors = [item.get("preview_error") for item in fail_public.get("candidates") or []]
                self.assertTrue(any(fail_errors) or not _playable_preview_refs(fail_public))
                for path, body in original.items():
                    if path.is_file():
                        self.assertNotEqual(body, b"")
            finally:
                _stop(server, thread)

    def test_occupied_valid_same_duration_wav_is_refused_and_same_context_reuses_excerpt(self):  # noqa: PLR0915 - Compare identical-duration foreign WAV rejection with genuine bound-preview reuse and immutable bytes.
        with tempfile.TemporaryDirectory() as tmp:
            _project(tmp)
            _assign_all(tmp)
            script, duration_s = _script_from_tokens(_track_tokens())
            wav = _write_wav(Path(tmp) / "vo.wav", frames=int((duration_s + 1) * 8000))
            server, thread = _serving_script(tmp, script)
            try:
                env = _env(server)
                _analyze_complete(tmp, wav, env, ANALYSIS_ID)
                solo = ["stat-hello"]
                pair = ["stat-bye", "stat-hello"]
                solo_match = _match_cli(tmp, ANALYSIS_ID, solo, env)
                self.assertIs(False, solo_match["retranscribed"])
                solo_public = _public_alignment(tmp, "stat-hello")
                solo_cand, solo_duration, solo_ref = _public_preview_candidate(solo_public)
                solo_dest = _preview_dest(tmp, solo_ref)
                self.assertTrue(solo_dest.is_file())
                self.assertEqual(
                    solo_duration,
                    float(solo_cand["end_s"]) - float(solo_cand["start_s"]),
                )
                pair_match = _match_cli(tmp, ANALYSIS_ID, pair, env)
                self.assertIs(False, pair_match["retranscribed"])
                pair_public = _public_alignment(tmp, "stat-hello")
                pair_cand, pair_duration, pair_ref = _public_preview_candidate(pair_public)
                pair_dest = _preview_dest(tmp, pair_ref)
                self.assertTrue(pair_dest.is_file())
                self.assertEqual(
                    pair_duration,
                    float(pair_cand["end_s"]) - float(pair_cand["start_s"]),
                )
                self.assertNotEqual(solo_public.get("input_fingerprint"), pair_public.get("input_fingerprint"))
                self.assertNotEqual(solo_ref, pair_ref)
                genuine_bytes = pair_dest.read_bytes()
                genuine_hash = file_digest(pair_dest)
                self.assertTrue(genuine_bytes)
                reused = _match_cli(tmp, ANALYSIS_ID, pair, env)
                self.assertIs(False, reused["retranscribed"])
                self.assertEqual(1, server.state.posts)
                self.assertEqual(genuine_bytes, pair_dest.read_bytes())
                self.assertEqual(genuine_hash, file_digest(pair_dest))
                reused_public = _public_alignment(tmp, "stat-hello")
                reused_cand = _candidate_by_id(reused_public, pair_cand["id"])
                reused_preview = reused_cand.get("preview")
                self.assertIsInstance(reused_preview, dict)
                if not isinstance(reused_preview, dict):
                    self.fail("Genuine same-context reuse must expose its saved preview")
                self.assertEqual(pair_ref, reused_preview.get("ref"))
                self.assertEqual(genuine_hash, reused_preview.get("sha256"))
                self.assertFalse(reused_cand.get("preview_error"))
                self.assertIn(pair_ref, _playable_preview_refs(reused_public))
                _assert_no_missing_playable_preview(self, tmp, reused_public)
                planted_pair, planted_pair_hash = _plant_valid_same_duration_wav(pair_dest, pair_duration)
                self.assertNotEqual(planted_pair, genuine_bytes)
                self.assertNotEqual(planted_pair_hash, genuine_hash)
                mismatched = _match_cli(tmp, ANALYSIS_ID, pair, env)
                self.assertIs(False, mismatched["retranscribed"])
                self.assertEqual(1, server.state.posts)
                self.assertEqual(planted_pair, pair_dest.read_bytes())
                self.assertEqual(planted_pair_hash, file_digest(pair_dest))
                _assert_occupied_preview_refused(self, tmp, "stat-hello", pair_dest, pair_ref, pair_cand["id"])
                self.assertTrue(solo_dest.is_file())
                planted_solo, planted_solo_hash = _plant_valid_same_duration_wav(solo_dest, solo_duration)
                absent = _match_cli(tmp, ANALYSIS_ID, solo, env)
                self.assertIs(False, absent["retranscribed"])
                self.assertEqual(1, server.state.posts)
                self.assertEqual(planted_solo, solo_dest.read_bytes())
                self.assertEqual(planted_solo_hash, file_digest(solo_dest))
                _assert_occupied_preview_refused(self, tmp, "stat-hello", solo_dest, solo_ref, solo_cand["id"])
                self.assertEqual(planted_pair, pair_dest.read_bytes())
                self.assertEqual(planted_pair_hash, file_digest(pair_dest))
            finally:
                _stop(server, thread)

    def test_storyboard_keeps_frozen_form_and_one_current_editable_form(self):
        with tempfile.TemporaryDirectory() as tmp:
            _project(tmp)
            _assign_all(tmp)
            script, duration_s = _script_from_tokens(_track_tokens())
            wav = _write_wav(Path(tmp) / "vo.wav", frames=int((duration_s + 1) * 8000))
            server, thread = _serving_script(tmp, script)
            try:
                env = _env(server)
                _analyze_complete(tmp, wav, env, ANALYSIS_ID)
                matched = _match_cli(tmp, ANALYSIS_ID, ["stat-01"], env)
                rendered = run_cli("graphics-render", "--occurrence", "stat-01", project=tmp, env=SILENT_ENV)
                self.assertEqual("v1", rendered["version"]["id"])
                run_cli("review", project=tmp)
                page = (Path(tmp) / "brolls" / "review.html").read_text(encoding="utf-8")
                flags = _alignment_form_flags(page)
                self.assertIn("0", flags)
                self.assertEqual(1, flags.count("1"))
                self.assertIn("This saved version keeps its original alignment context", page)
                payload = _review_payload(tmp)
                row = next(item for item in payload["alignment"] if item["occurrence_id"] == "stat-01")
                self.assertEqual(matched["matches"]["stat-01"]["input_fingerprint"], row["input_fingerprint"])
                self.assertTrue(row["signature"])
                self.assertEqual(row["signature"], row["reviewEpoch"])
            finally:
                _stop(server, thread)

    def test_manual_override_preview_mixed_import_and_exact_replay(self):  # noqa: PLR0915 - One correction lifecycle verifies invalid mixed import atomicity, bound preview and exact replay.
        with tempfile.TemporaryDirectory() as tmp:
            _project(tmp)
            _assign_all(tmp)
            script, duration_s = _script_from_tokens(_track_tokens())
            wav = _write_wav(Path(tmp) / "vo.wav", frames=int((duration_s + 1) * 8000))
            server, thread = _serving_script(tmp, script)
            try:
                env = _env(server)
                _analyze_complete(tmp, wav, env, ANALYSIS_ID)
                matched = _match_cli(tmp, ANALYSIS_ID, ["stat-hello", "stat-bye"], env)
                hello = matched["matches"]["stat-hello"]
                start_s = float(hello["candidates"][0]["start_s"])
                end_s = float(hello["candidates"][0]["end_s"])
                resolved = _resolve_interval(tmp, "stat-hello", start_s, end_s, env)
                self.assertIsNone(resolved["alignment"]["selected_candidate_id"])
                self.assertEqual("resolved", resolved["alignment"]["state"])
                status = run_cli("status", project=tmp)
                public = _item(status, "stat-hello")["alignment"]
                override = public.get("override_preview") or {}
                self.assertTrue(override.get("ref") or override.get("error"))
                if override.get("ref"):
                    self.assertTrue(str(override["ref"]).startswith("previews/"))
                    self.assertTrue((Path(tmp) / "brolls" / override["ref"]).is_file())
                run_cli("review", project=tmp)
                page = (Path(tmp) / "brolls" / "review.html").read_text(encoding="utf-8")
                if override.get("ref"):
                    self.assertIn(override["ref"], page)
                    self.assertIn("graphics-alignment-preview", page)
                elif override.get("error"):
                    self.assertIn(str(override["error"]), page)
                payload = _review_payload(tmp)
                hello_row = next(row for row in payload["alignment"] if row["occurrence_id"] == "stat-hello")
                bye_row = next(row for row in payload["alignment"] if row["occurrence_id"] == "stat-bye")
                replay_payload = json.loads(json.dumps(payload))
                hello_row["start_s"] = start_s
                hello_row["end_s"] = end_s
                hello_row["statement"] = CORRECTION
                hello_row["by"] = "Human"
                bye_row["signature"] = "00" * 32
                bye_row["reviewEpoch"] = "00" * 32
                bye_row["candidate_id"] = (bye_row.get("candidates") or [{"id": "c1"}])[0]["id"]
                bye_row["statement"] = CORRECTION
                path = _write_review(tmp, payload)
                imported = run_cli("import-review", "--file", str(path), "--by", "Human", project=tmp)
                self.assertTrue(imported["skipped"])
                self.assertGreaterEqual(imported.get("imported", 0) + len(imported.get("unchanged") or []), 1)
                stale = [row for row in imported["skipped"] if row.get("id") == bye_row["id"]]
                self.assertTrue(stale)
                alignment_before = Ledger(tmp, recover=False).data["graphics"]["occurrences"]["stat-hello"]["alignment"]
                replay_hello = next(row for row in replay_payload["alignment"] if row["occurrence_id"] == "stat-hello")
                replay_hello["start_s"] = start_s
                replay_hello["end_s"] = end_s
                replay_hello["statement"] = CORRECTION
                replay_hello["by"] = "Human"
                replay_hello["signature"] = hello_row["signature"]
                replay_hello["reviewEpoch"] = hello_row["reviewEpoch"]
                replay_path = _write_review(tmp, replay_payload, name="20261011-replay.json")
                replayed = run_cli("import-review", "--file", str(replay_path), "--by", "Human", project=tmp)
                self.assertEqual(0, replayed.get("alignment_imported") or 0)
                self.assertTrue(replayed.get("unchanged"))
                alignment_after = Ledger(tmp, recover=False).data["graphics"]["occurrences"]["stat-hello"]["alignment"]
                self.assertEqual(alignment_before, alignment_after)
                self.assertEqual(1, server.state.posts)
                self.assertGreaterEqual(_event_ops(tmp).count("import-review"), 1)
            finally:
                _stop(server, thread)

    def test_old_version_sources_and_journal_survive_new_alignment_render(self):
        with tempfile.TemporaryDirectory() as tmp:
            _project(tmp)
            _assign_all(tmp)
            script, duration_s = _script_from_tokens(_track_tokens())
            wav = _write_wav(Path(tmp) / "vo.wav", frames=int((duration_s + 1) * 8000))
            server, thread = _serving_script(tmp, script)
            try:
                env = _env(server)
                _analyze_complete(tmp, wav, env, ANALYSIS_ID)
                first_match = _match_cli(tmp, ANALYSIS_ID, ["stat-01"], env)
                first = run_cli("graphics-render", "--occurrence", "stat-01", project=tmp, env=SILENT_ENV)
                v1 = Path(tmp) / "brolls" / "graphics" / "numeric-stat" / first["version"]["id"]
                old = {rel.as_posix(): file_digest(rel) for rel in v1.rglob("*") if rel.is_file()}
                journal_before = Path(tmp).joinpath("brolls", "events.jsonl").read_bytes()
                hello_match = _match_cli(tmp, ANALYSIS_ID, ["stat-hello"], env)
                candidate_id = hello_match["matches"]["stat-hello"]["candidates"][0]["id"]
                _resolve_candidate(tmp, "stat-hello", candidate_id, env)
                _assign_passage(tmp, PASSAGES[0], narration="The count stands at twelve units again.")
                second_match = _match_cli(tmp, ANALYSIS_ID, ["stat-01"], env)
                second = run_cli("graphics-render", "--occurrence", "stat-01", project=tmp, env=SILENT_ENV)
                self.assertNotEqual(first["version"]["id"], second["version"]["id"])
                for rel, digest_value in old.items():
                    self.assertEqual(digest_value, file_digest(v1 / rel))
                frozen = json.loads((v1 / "assignment.json").read_text(encoding="utf-8"))
                self.assertEqual(
                    first_match["matches"]["stat-01"]["input_fingerprint"],
                    frozen["alignment"]["input_fingerprint"],
                )
                self.assertNotEqual(
                    first_match["matches"]["stat-01"]["scenario_sha256"],
                    second_match["matches"]["stat-01"]["scenario_sha256"],
                )
                self.assertTrue(journal_before)
                self.assertEqual(1, server.state.posts)
                run_cli("review", project=tmp)
                page = (Path(tmp) / "brolls" / "review.html").read_text(encoding="utf-8")
                self.assertIn('data-alignment-editable="0"', page)
                self.assertIn('data-alignment-editable="1"', page)
                self.assertNotIn("narration/private", page)
            finally:
                _stop(server, thread)


if __name__ == "__main__":
    unittest.main()
