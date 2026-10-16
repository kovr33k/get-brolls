"""Mixed reference requests through real local HTTP, CLI, decoding and snapshots."""

from __future__ import annotations

import copy
import json
import struct
import subprocess
import tempfile
import unittest
import urllib.error
import urllib.request
from http import HTTPStatus
from pathlib import Path
from urllib.parse import quote

import _isolation  # noqa: F401
from _cli import run_cli
from _media import skip_unless_ffmpeg, synth_image, synth_video
from test_graphics_media_workflow import _background_payload
from test_graphics_references import post, serving
from test_graphics_review import _assign, _project, _render, _review_payload, _version_hashes

from getbrolls import serve
from getbrolls.graphics_references import NAME_HEADER, UPLOAD_PATH
from getbrolls.ledger import Ledger, digest


def upload_media(url, token, row, path, kind, label):  # noqa: PLR0913, PLR0917 - real transport identifies target, bytes, type and stable label.
    metadata = {
        key: row.get(key)
        for key in ("id", "project", "scene_id", "occurrence_id", "version", "signature", "reviewEpoch", "initial")
    }
    metadata.update(name="same-name.mp4", kind=kind)
    ref = post(
        url + UPLOAD_PATH,
        Path(path).read_bytes(),
        token,
        **{NAME_HEADER: quote(json.dumps(metadata)), "Content-Type": "application/octet-stream"},
    )["reference"]
    return {**ref, "label": label}


def mixed_request(project, *, rendered=False, duration=6, explicit=False, prompt=None, video_label="R2"):  # noqa: PLR0913 - fixture varies independent lifecycle, bounds and retained labels.
    _project(project)
    _assign(project, duration="2", **({"timing": "explicit", "start": "0", "end": "2"} if explicit else {}))
    if rendered:
        _render(project)
    image, video = Path(project) / "style.png", Path(project) / "motion.mp4"
    synth_image(image, color="blue")
    synth_video(video, duration=duration)
    payload = _review_payload(project)
    row = next(row for row in payload["graphics"] if row["current"])
    before = (Path(project) / "brolls/manifest.json").read_bytes()
    with serving(project) as (server, url):
        refs = [
            upload_media(url, server.save_token, row, image, "image", "R1"),
            upload_media(url, server.save_token, row, video, "video", video_label),
        ]
        row.update(
            references=refs,
            state="changes",
            comment=prompt
            or f"Use R1 colors and {video_label} from 3 to 5 seconds. Put {video_label} behind our graphics.",
            scope="scene",
        )
        saved = post(url + serve.SAVE_PATH, json.dumps(payload).encode(), server.save_token)
        media_url = url + UPLOAD_PATH + "/" + Path(refs[1]["ref"]).name
        with urllib.request.urlopen(urllib.request.Request(media_url, headers={"Range": "bytes=7-25"})) as response:
            assert response.status == HTTPStatus.PARTIAL_CONTENT
            assert response.read() == video.read_bytes()[7:26]
        with urllib.request.urlopen(
            urllib.request.Request(media_url, headers={"Range": "bytes=7-25", "If-Range": '"unmatched"'})
        ) as response:
            assert response.status == HTTPStatus.OK
            assert response.read() == video.read_bytes()
    assert before == (Path(project) / "brolls/manifest.json").read_bytes(), "Save/upload must not analyze or render."
    run_cli("import-review", "--file", saved["path"], "--by", "Synthetic editor", project=project)
    request = Ledger(project, recover=False).data["graphics"]["requests"][-1]
    return request, refs, saved["path"]


def inspect(project, request, *flags):
    label = next(ref["label"] for ref in request["references"] if ref["kind"] == "video")
    return run_cli(
        "graphics-reference-inspect",
        "--request",
        request["id"],
        "--label",
        label,
        "--wording",
        label + " from 3 to 5 seconds",
        *flags,
        project=project,
    )["inspection"]


def analysis_file(project, record, *, composition=None):
    payload = {
        "analyses": [
            {
                "label": "R1",
                "analysis": "Use its blue accent palette, keeping our facts.",
                "limitations": "One still image; no motion inferred.",
            },
            {
                "label": record["label"],
                "analysis": "Adopt the changing pattern over the requested two seconds.",
                "limitations": "Twelve temporal samples; motion between samples needs direct playback.",
                "inspection": record["record_ref"],
            },
        ]
    }
    if composition:
        payload["composition"] = composition
    path = Path(project) / "brolls/analyses.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


@skip_unless_ffmpeg
class GraphicsMixedReferencesTests(unittest.TestCase):
    def test_initial_and_revision_mixed_save_reopen_temporal_analysis_frozen_history(self):
        for rendered in (False, True):
            with self.subTest(revision=rendered), tempfile.TemporaryDirectory() as project:
                request, refs, saved = mixed_request(project, rendered=rendered, video_label="R2" if rendered else "R3")
                old = _version_hashes(project, "numeric-stat", "v1") if rendered else None
                reopened = _review_payload(project)
                self.assertEqual(refs, next(row for row in reopened["graphics"] if row["current"])["references"])
                self.assertEqual(refs[0]["name"], refs[1]["name"])
                self.assertNotEqual(refs[0]["sha256"], refs[1]["sha256"])
                run_cli("import-review", "--file", saved, "--by", "Synthetic editor", project=project)
                self.assertEqual(1, len(Ledger(project, recover=False).data["graphics"]["requests"]))
                record = inspect(project, request, "--start", "3", "--end", "5")
                self.assertGreaterEqual(min(record["frame_times_s"]), 3)
                self.assertLess(max(record["frame_times_s"]), 5)
                self.assertEqual(record, inspect(project, request, "--start", "3", "--end", "5"))
                self.assertTrue((Path(project) / "brolls" / record["sheet_ref"]).is_file())
                path = analysis_file(project, record)
                run_cli("graphics-reference-apply", "--request", request["id"], "--file", path, project=project)
                ledger = Ledger(project, recover=False)
                self.assertNotIn("background", ledger.data["graphics"]["occurrences"]["stat-01"])
                self.assertEqual([], ledger.data["items"], "Style attachments must not become composition candidates.")
                (Path(project) / "style.png").unlink()
                (Path(project) / "motion.mp4").unlink()
                _render(project)
                version_id = "v2" if rendered else "v1"
                run_cli(
                    "graphics-request-complete",
                    "--request",
                    request["id"],
                    "--version",
                    version_id,
                    "--outcome",
                    "Applied both inspected examples while preserving facts.",
                    project=project,
                )
                version = Ledger(project, recover=False).data["graphics"]["versions"][version_id]
                self.assertIsNone(version["approval"])
                self.assertEqual(refs, version["assignment"]["reference_context"]["references"])
                for ref in refs:
                    frozen = (
                        Path(project)
                        / "brolls/graphics/numeric-stat"
                        / version_id
                        / "references"
                        / Path(ref["ref"]).name
                    )
                    self.assertEqual(ref["sha256"], digest(frozen))
                self.assertEqual(
                    record["sheet_sha256"],
                    digest(
                        Path(project)
                        / "brolls/graphics/numeric-stat"
                        / version_id
                        / ("references/" + record["label"] + "-temporal.jpg")
                    ),
                )
                if old:
                    self.assertEqual(old, _version_hashes(project, "numeric-stat", "v1"))

    def test_explicit_composition_reuses_registered_original_interval_and_permission_gates(self):
        with tempfile.TemporaryDirectory() as project:
            request, refs, _saved = mixed_request(project, explicit=True)
            record = inspect(project, request, "--start", "3", "--end", "5")
            source = Path(project) / "brolls" / refs[1]["ref"]
            resolved = run_cli(
                "resolve",
                "--file",
                source,
                "--asset-type",
                "video",
                "--title",
                "Synthetic saved reference",
                project=project,
            )
            self.assertIsNotNone(resolved)
            candidate = Ledger(project, recover=False).data["items"][0]
            ident = candidate["id"]
            run_cli("preview", "--candidate", ident, "--start", "3", "--end", "5", project=project)
            denied = run_cli("fetch", "--candidate", ident, project=project, expect=2)
            self.assertIn("error", denied)
            run_cli(
                "approve",
                "--candidate",
                ident,
                "--by",
                "Synthetic editor",
                "--statement",
                "Synthetic test approval of this exact preview.",
                project=project,
            )
            run_cli(
                "permit",
                "--candidate",
                ident,
                "--evidence",
                "Synthetic media created by this test, cleared for this test only.",
                project=project,
            )
            run_cli("fetch", "--candidate", ident, project=project)
            candidate = Ledger(project, recover=False).data["items"][0]
            background = _background_payload(ident, candidate["output"]["path"])
            composition = {"label": "R2", "instruction": "Put R2 behind our graphics.", "background": background}
            path = analysis_file(project, record, composition=composition)
            before = (Path(project) / "brolls/manifest.json").read_bytes()
            bad = json.loads(path.read_text())
            bad["composition"]["background"]["source_start_s"] = 3.5
            path.write_text(json.dumps(bad), encoding="utf-8")
            run_cli("graphics-reference-apply", "--request", request["id"], "--file", path, project=project, expect=2)
            self.assertEqual(before, (Path(project) / "brolls/manifest.json").read_bytes())
            path = analysis_file(project, record, composition=composition)
            run_cli("graphics-reference-apply", "--request", request["id"], "--file", path, project=project)
            occ = Ledger(project, recover=False).data["graphics"]["occurrences"]["stat-01"]
            self.assertEqual(refs[1]["sha256"], candidate["local_sha256"])
            self.assertEqual((3, 5), (occ["background"]["source_start_s"], occ["background"]["source_end_s"]))
            _render(project)
            self.assertEqual(
                occ["background"],
                Ledger(project, recover=False).data["graphics"]["versions"]["v1"]["assignment"]["background"],
            )
            run_cli(
                "graphics-approve",
                "--occurrence",
                "stat-01",
                "--version",
                "v1",
                "--by",
                "Synthetic editor",
                "--statement",
                "Synthetic test approval of this exact technical version.",
                project=project,
            )
            run_cli("deliver", project=project)
            package = Path(project) / "entrega/graphics/numeric-stat/stat-01/v1"
            self.assertFalse((package / "references").exists())
            for ref in refs:
                self.assertFalse(any(p.is_file() and digest(p) == ref["sha256"] for p in package.rglob("*")))
            self.assertFalse(any((package / "public/media").glob("*")), "Restricted composition originals remain held.")

    def test_invalid_intervals_missing_temporal_evidence_and_changed_samples_refuse_without_mutation(self):
        with tempfile.TemporaryDirectory() as project:
            request, _refs, _saved = mixed_request(project)
            before = (Path(project) / "brolls/manifest.json").read_bytes()
            for flags in (
                [],
                ["--start", "5", "--end", "3"],
                ["--start", "0", "--end", "9"],
                ["--whole", "--start", "1"],
            ):
                run_cli(
                    "graphics-reference-inspect",
                    "--request",
                    request["id"],
                    "--label",
                    "R2",
                    "--wording",
                    "R2 from 3 to 5 seconds",
                    *flags,
                    project=project,
                    expect=2,
                )
            record = inspect(project, request, "--start", "3", "--end", "5")
            path = analysis_file(project, record)
            missing = json.loads(path.read_text())
            del missing["analyses"][1]["inspection"]
            path.write_text(json.dumps(missing), encoding="utf-8")
            run_cli("graphics-reference-apply", "--request", request["id"], "--file", path, project=project, expect=2)
            path = analysis_file(project, record)
            record_path = Path(project) / "brolls" / record["record_ref"]
            changed_record = {**record, "frame_times_s": [0] * record["frames"]}
            record_path.write_text(json.dumps(changed_record), encoding="utf-8")
            run_cli("graphics-reference-apply", "--request", request["id"], "--file", path, project=project, expect=2)
            record_path.write_text(json.dumps(record), encoding="utf-8")
            (Path(project) / "brolls" / record["sheet_ref"]).write_bytes(b"changed evidence")
            run_cli("graphics-reference-apply", "--request", request["id"], "--file", path, project=project, expect=2)
            self.assertEqual(before, (Path(project) / "brolls/manifest.json").read_bytes())

    def test_video_content_count_total_limits_and_whole_clip_longer_than_one_minute(self):
        with tempfile.TemporaryDirectory() as project:
            request, refs, _saved = mixed_request(
                project, duration=61, prompt="Use R1 colors. Analyze the whole R2 clip."
            )
            self.assertGreater(refs[1]["duration_s"], 60)
            result = run_cli(
                "graphics-reference-inspect",
                "--request",
                request["id"],
                "--label",
                "R2",
                "--wording",
                "Analyze the whole R2 clip.",
                "--whole",
                project=project,
            )
            self.assertEqual(refs[1]["duration_s"], result["inspection"]["end_s"])
            payload = _review_payload(project)
            row = payload["graphics"][0]
            with serving(project) as (server, url):
                with self.assertRaises(urllib.error.HTTPError) as error:
                    upload_media(url, server.save_token, row, Path(project) / "style.png", "video", "R3")
                error.exception.close()
                oversized = Path(project) / "large.mp4"
                data = (Path(project) / "motion.mp4").read_bytes()
                padding = 17 * 1024 * 1024 - len(data)
                oversized.write_bytes(data + struct.pack(">I4s", padding, b"free") + bytes(padding - 8))
                large = upload_media(url, server.save_token, row, oversized, "video", "R1")
                for collection in (
                    [{**refs[0], "label": "R1"}] * 9,
                    [{**large, "label": "R" + str(i)} for i in range(1, 9)],
                    [refs[0], {**refs[1], "duration_s": refs[1]["duration_s"] + 1}],
                    [refs[0], {**refs[1], "label": "R1"}],
                ):
                    row["references"] = collection
                    with self.assertRaises(urllib.error.HTTPError) as error:
                        post(url + serve.SAVE_PATH, json.dumps(payload).encode(), server.save_token)
                    error.exception.close()
                row["references"] = copy.deepcopy(refs)
                row["reference"] = refs[0]
                with self.assertRaises(urllib.error.HTTPError) as error:
                    post(url + serve.SAVE_PATH, json.dumps(payload).encode(), server.save_token)
                error.exception.close()

    def test_corrupt_truncated_and_non_h264_mp4_leave_no_published_reference(self):
        with tempfile.TemporaryDirectory() as project:
            _project(project)
            _assign(project)
            row = _review_payload(project)["graphics"][0]
            good, unsupported, truncated = (Path(project) / name for name in ("good.mp4", "mpeg4.mp4", "truncated.mp4"))
            synth_video(good, duration=1)
            subprocess.run(["ffmpeg", "-v", "error", "-i", str(good), "-c:v", "mpeg4", str(unsupported)], check=True)
            truncated.write_bytes(good.read_bytes()[:128])
            corrupt = Path(project) / "corrupt.mp4"
            corrupt.write_bytes(b"\x00\x00\x00\x20ftypisom" + b"broken data")
            before = (Path(project) / "brolls/manifest.json").read_bytes()
            with serving(project) as (server, url):
                for path in (unsupported, truncated, corrupt):
                    with self.assertRaises(urllib.error.HTTPError) as error:
                        upload_media(url, server.save_token, row, path, "video", "R1")
                    error.exception.close()
            folder = Path(project) / "brolls/graphics-data/references"
            self.assertEqual([], list(folder.glob("*")))
            self.assertEqual(before, (Path(project) / "brolls/manifest.json").read_bytes())
            with_audio = Path(project) / "longer-audio.mp4"
            subprocess.run(
                [
                    "ffmpeg",
                    "-v",
                    "error",
                    "-i",
                    str(good),
                    "-f",
                    "lavfi",
                    "-i",
                    "sine=frequency=440:duration=3",
                    "-c:v",
                    "copy",
                    "-c:a",
                    "aac",
                    str(with_audio),
                ],
                check=True,
            )
            with serving(project) as (server, url):
                ref = upload_media(url, server.save_token, row, with_audio, "video", "R1")
                self.assertAlmostEqual(
                    1, ref["duration_s"], places=2, msg="Visual bounds follow the video stream, not longer audio."
                )
            self.assertEqual(before, (Path(project) / "brolls/manifest.json").read_bytes())
