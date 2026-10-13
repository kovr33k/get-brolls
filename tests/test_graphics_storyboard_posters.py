"""Saved animation previews show a real frame before playback, preserving approvals."""

from __future__ import annotations

import copy
import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import _isolation  # noqa: F401
import _paths  # noqa: F401
from _media import skip_unless_ffmpeg

from getbrolls import graphics
from getbrolls.config import tool_path
from getbrolls.ledger import digest
from getbrolls.media import run


@skip_unless_ffmpeg
class GraphicsStoryboardPosterTest(unittest.TestCase):
    def test_poster_shows_animation_and_keeps_saved_video_and_approval(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            previews = root / "previews"
            previews.mkdir()
            video = previews / "saved.mp4"
            run(
                [
                    "ffmpeg",
                    "-v",
                    "error",
                    "-y",
                    "-f",
                    "lavfi",
                    "-i",
                    "color=c=red:s=64x64:r=30:d=2",
                    "-vf",
                    "fade=t=in:st=0:d=0.8",
                    "-c:v",
                    "libx264",
                    "-pix_fmt",
                    "yuv420p",
                    str(video),
                ]
            )
            version = {
                "artifact": {"path": "previews/saved.mp4", "sha256": digest(video), "duration_s": 2},
                "approval": {"status": "approved", "signature": "saved-signature"},
            }
            before = copy.deepcopy(version)
            with (
                mock.patch.dict(os.environ, {"GB_FFMPEG_PATH": str(root / "missing-ffmpeg.exe")}),
                self.assertRaisesRegex(ValueError, "GB_FFMPEG_PATH"),
            ):
                graphics._storyboard_poster(root, version)
            with mock.patch.object(graphics, "media_run", side_effect=ValueError("Unavailable decoder")):
                self.assertIsNone(graphics._storyboard_poster(root, version))
            poster = graphics._storyboard_poster(root, version)
            if poster is None:
                self.fail("A saved animation needs a visible poster before playback")
            self.assertEqual(version, before)
            self.assertEqual(digest(video), before["artifact"]["sha256"])
            self.assertTrue((root / poster).is_file())
            # A black first frame must not be the image shown before playback.
            pixels = subprocess.run(
                [
                    tool_path("ffmpeg"),
                    "-v",
                    "error",
                    "-i",
                    str(root / poster),
                    "-vf",
                    "scale=1:1",
                    "-f",
                    "rawvideo",
                    "-pix_fmt",
                    "rgb24",
                    "-frames:v",
                    "1",
                    "-",
                ],
                check=True,
                capture_output=True,
            ).stdout
            self.assertGreater(pixels[0], 150)
            self.assertLess(pixels[1], 30)
            markup = graphics._storyboard_complete_version(version, {"narration": "Original passage"}, "v1", poster)
            self.assertIn(f'poster="{poster}"', markup)
            self.assertIn('src="previews/saved.mp4"', markup)
            with mock.patch.object(graphics, "media_run", side_effect=AssertionError("Must reuse poster")):
                self.assertEqual(graphics._storyboard_poster(root, version), poster)
            video.write_bytes(b"changed")
            self.assertIsNone(graphics._storyboard_poster(root, version))

    def test_missing_or_unconfined_video_does_not_break_review(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            for path in ("previews/missing.mp4", "../outside.mp4"):
                with self.subTest(path=path):
                    version = {"artifact": {"path": path, "sha256": "a" * 64, "duration_s": 2}}
                    with mock.patch.object(graphics, "media_run", side_effect=AssertionError("Unsafe extraction")):
                        self.assertIsNone(graphics._storyboard_poster(root, version))


if __name__ == "__main__":
    unittest.main()
