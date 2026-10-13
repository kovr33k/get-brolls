"""P57-W9: single-byte Range on already-admitted previews/clips for browser seeking."""

import builtins
import http.client
import json
import tempfile
import threading
import unittest
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import patch

import _isolation  # noqa: F401  (efeito de import: define GB_HOME)
from _paths import ROOT  # noqa: F401  (efeito de import: insere scripts/ em sys.path)

from getbrolls import serve

PAYLOAD = bytes(range(256)) * 4  # 1024 distinct repeating bytes
PRIVATE_MARKER = b"PRIVATE-ORIGINAL-16S"
SEEK_OFFSET = 262144
SEEK_TOTAL = 300000


def _project_with_media(root, payload=PAYLOAD):
    brolls = root / "brolls"
    brolls.mkdir(parents=True)
    (brolls / "review.html").write_text("<html><body>storyboard</body></html>", encoding="utf-8")
    previews = brolls / "previews"
    clips = brolls / "clips"
    previews.mkdir()
    clips.mkdir()
    (previews / "clip.mp4").write_bytes(payload)
    (previews / "vo.wav").write_bytes(payload)
    (clips / "final.mp4").write_bytes(payload)
    (previews / "empty.mp4").write_bytes(b"")
    private = brolls / "narration" / "private" / "audio"
    private.mkdir(parents=True)
    (private / "original.wav").write_bytes(PRIVATE_MARKER * 32)
    (brolls / "manifest.json").write_text('{"secret":"ledger"}', encoding="utf-8")
    (brolls / "reviews").mkdir()
    (brolls / "reviews" / "decision.json").write_text("{}", encoding="utf-8")
    (root / "secret.txt").write_text("outside-secret", encoding="utf-8")
    return root


@contextmanager
def _serving(root):
    server, port = serve.start(root, port=0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield server, port
    finally:
        server.shutdown()
        thread.join(timeout=5)
        server.server_close()


def _request(port, method, path, headers=None):
    extra = dict(headers or {})
    connection = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
    try:
        connection.request(method, path, headers=extra)
        response = connection.getresponse()
        body = response.read()
        return response.status, response.headers, body
    finally:
        connection.close()


def _snapshot(root):
    mapping = {}
    for path in sorted(root.rglob("*")):
        if path.is_file():
            mapping[path.relative_to(root).as_posix()] = path.read_bytes()
    return mapping


def _security(headers):
    return {
        "cache": headers.get("Cache-Control"),
        "frame": headers.get("X-Frame-Options"),
        "csp": headers.get("Content-Security-Policy"),
        "sniff": headers.get("X-Content-Type-Options"),
        "referrer": headers.get("Referrer-Policy"),
    }


class ByteRangeServingTests(unittest.TestCase):
    def _assert_security(self, headers):
        seen = _security(headers)
        self.assertEqual("no-store", seen["cache"])
        self.assertEqual("DENY", seen["frame"])
        self.assertIn("frame-ancestors 'none'", seen["csp"] or "")
        self.assertEqual("nosniff", seen["sniff"])
        self.assertEqual("no-referrer", seen["referrer"])

    def test_first_middle_open_ended_suffix_and_clamped_ranges_are_exact_206(self):
        cases = {
            "first": ("bytes=0-9", 0, 9),
            "middle": ("bytes=100-149", 100, 149),
            "from_start": ("bytes=0-", 0, 1023),
            "open": ("bytes=1000-", 1000, 1023),
            "suffix": ("bytes=-32", 992, 1023),
            "clamped": ("bytes=1000-9999", 1000, 1023),
        }
        with tempfile.TemporaryDirectory() as tmp:
            root = _project_with_media(Path(tmp))
            with _serving(root) as (_server, port):
                for name, (spec, start, end) in cases.items():
                    with self.subTest(name=name, spec=spec):
                        status, headers, body = _request(port, "GET", "/previews/clip.mp4", {"Range": spec})
                        self.assertEqual(206, status)
                        self.assertEqual(PAYLOAD[start : end + 1], body)
                        self.assertEqual(str(end - start + 1), headers.get("Content-Length"))
                        self.assertEqual(f"bytes {start}-{end}/{len(PAYLOAD)}", headers.get("Content-Range"))
                        self.assertEqual("bytes", headers.get("Accept-Ranges"))
                        self.assertRegex(headers.get("Content-Type", ""), r"video/mp4")
                        self._assert_security(headers)

                status, headers, body = _request(port, "GET", "/previews/vo.wav", {"Range": "bytes=0-3"})
                self.assertEqual(206, status)
                self.assertEqual(PAYLOAD[0:4], body)
                self.assertRegex(headers.get("Content-Type", ""), r"audio/(x-)?wav")

                status, headers, body = _request(port, "GET", "/clips/final.mp4", {"Range": "bytes=8-11"})
                self.assertEqual(206, status)
                self.assertEqual(PAYLOAD[8:12], body)
                self.assertEqual(f"bytes 8-11/{len(PAYLOAD)}", headers.get("Content-Range"))

                status, headers, body = _request(port, "GET", "/previews/clip.mp4?v=1", {"Range": "bytes=0-1"})
                self.assertEqual(206, status)
                self.assertEqual(PAYLOAD[0:2], body)

    def test_unranged_get_is_200_full_file_and_announces_bytes(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = _project_with_media(Path(tmp))
            with _serving(root) as (_server, port):
                status, headers, body = _request(port, "GET", "/previews/clip.mp4")
                self.assertEqual(200, status)
                self.assertEqual(PAYLOAD, body)
                self.assertEqual(str(len(PAYLOAD)), headers.get("Content-Length"))
                self.assertEqual("bytes", headers.get("Accept-Ranges"))
                self.assertIsNone(headers.get("Content-Range"))
                self.assertRegex(headers.get("Content-Type", ""), r"video/mp4")
                self._assert_security(headers)

                status, headers, body = _request(port, "GET", "/previews/empty.mp4")
                self.assertEqual(200, status)
                self.assertEqual(b"", body)
                self.assertEqual("0", headers.get("Content-Length"))
                self.assertEqual("bytes", headers.get("Accept-Ranges"))

    def test_head_ignores_range_and_sends_no_body(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = _project_with_media(Path(tmp))
            with _serving(root) as (_server, port):
                status, headers, body = _request(port, "HEAD", "/previews/clip.mp4", {"Range": "bytes=0-9"})
                self.assertEqual(200, status)
                self.assertEqual(b"", body)
                self.assertEqual(str(len(PAYLOAD)), headers.get("Content-Length"))
                self.assertEqual("bytes", headers.get("Accept-Ranges"))
                self.assertIsNone(headers.get("Content-Range"))
                self.assertRegex(headers.get("Content-Type", ""), r"video/mp4")
                self._assert_security(headers)

    def test_chromium_style_open_ended_seek_on_larger_media(self):
        payload = bytes(i % 256 for i in range(SEEK_TOTAL))
        with tempfile.TemporaryDirectory() as tmp:
            root = _project_with_media(Path(tmp), payload=payload)
            with _serving(root) as (_server, port):
                status, headers, body = _request(port, "GET", "/previews/vo.wav", {"Range": "bytes=0-"})
                self.assertEqual(206, status)
                self.assertEqual(payload, body)
                self.assertEqual(f"bytes 0-{SEEK_TOTAL - 1}/{SEEK_TOTAL}", headers.get("Content-Range"))
                self.assertEqual("bytes", headers.get("Accept-Ranges"))

                status, headers, body = _request(port, "GET", "/previews/clip.mp4", {"Range": f"bytes={SEEK_OFFSET}-"})
                self.assertEqual(206, status)
                self.assertEqual(payload[SEEK_OFFSET:], body)
                self.assertEqual(
                    f"bytes {SEEK_OFFSET}-{SEEK_TOTAL - 1}/{SEEK_TOTAL}",
                    headers.get("Content-Range"),
                )
                self.assertEqual(str(SEEK_TOTAL - SEEK_OFFSET), headers.get("Content-Length"))


class RangeUnsatisfiableTests(unittest.TestCase):
    def test_unsatisfiable_and_zero_byte_file_are_416_without_file_bytes(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = _project_with_media(Path(tmp))
            with _serving(root) as (_server, port):
                status, headers, body = _request(
                    port, "GET", "/previews/clip.mp4", {"Range": f"bytes={len(PAYLOAD)}-2000"}
                )
                self.assertEqual(416, status)
                self.assertEqual(b"", body)
                self.assertEqual(f"bytes */{len(PAYLOAD)}", headers.get("Content-Range"))
                self.assertEqual("0", headers.get("Content-Length"))
                self.assertEqual("bytes", headers.get("Accept-Ranges"))
                self.assertEqual("no-store", headers.get("Cache-Control"))
                self.assertEqual("nosniff", headers.get("X-Content-Type-Options"))
                self.assertNotIn(PAYLOAD[:16], body)

                for spec in ("bytes=0-0", "bytes=0-", "bytes=-1", "bytes=1-1"):
                    with self.subTest(empty=spec):
                        status, headers, body = _request(port, "GET", "/previews/empty.mp4", {"Range": spec})
                        self.assertEqual(416, status)
                        self.assertEqual(b"", body)
                        self.assertEqual("bytes */0", headers.get("Content-Range"))
                        self.assertEqual("0", headers.get("Content-Length"))

                status, headers, body = _request(port, "HEAD", "/previews/empty.mp4", {"Range": "bytes=0-0"})
                self.assertEqual(200, status)
                self.assertEqual(b"", body)
                self.assertEqual("0", headers.get("Content-Length"))
                self.assertIsNone(headers.get("Content-Range"))


class RangeRobustnessTests(unittest.TestCase):
    def test_invalid_unknown_multipart_and_oversized_range_fall_back_to_200(self):
        ignored = (
            "bytes=",
            "bytes=abc",
            "bytes=10-5",
            "bytes=1-2-3",
            "bytes=0-1,2-3",
            "items=0-1",
            "seconds=1-2",
            "bytes=" + "9" * 20 + "-",
            "bytes=0-" + "9" * 20,
            "bytes=-" + "9" * 20,
        )
        with tempfile.TemporaryDirectory() as tmp:
            root = _project_with_media(Path(tmp))
            with _serving(root) as (_server, port):
                for spec in ignored:
                    with self.subTest(spec=spec):
                        status, headers, body = _request(port, "GET", "/previews/clip.mp4", {"Range": spec})
                        self.assertEqual(200, status)
                        self.assertEqual(PAYLOAD, body)
                        self.assertEqual("bytes", headers.get("Accept-Ranges"))
                        self.assertIsNone(headers.get("Content-Range"))

    def test_if_range_without_an_established_validator_returns_full_200(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = _project_with_media(Path(tmp))
            with _serving(root) as (_server, port):
                status, headers, body = _request(port, "GET", "/previews/clip.mp4")
                self.assertEqual(200, status)
                last_modified = headers.get("Last-Modified")
                self.assertTrue(last_modified)

                status, headers, body = _request(
                    port,
                    "GET",
                    "/previews/clip.mp4",
                    {"Range": "bytes=0-9", "If-Range": '"unestablished-etag"'},
                )
                self.assertEqual(200, status)
                self.assertEqual(PAYLOAD, body)
                self.assertIsNone(headers.get("Content-Range"))

                status, headers, body = _request(
                    port,
                    "GET",
                    "/previews/clip.mp4",
                    {"Range": "bytes=0-9", "If-Range": 'W/"weak"'},
                )
                self.assertEqual(200, status)
                self.assertEqual(PAYLOAD, body)

                status, headers, body = _request(
                    port,
                    "GET",
                    "/previews/clip.mp4",
                    {"Range": "bytes=0-9", "If-Range": "Wed, 21 Oct 2015 07:28:00 GMT"},
                )
                self.assertEqual(200, status)
                self.assertEqual(PAYLOAD, body)

                status, headers, body = _request(
                    port,
                    "GET",
                    "/previews/clip.mp4",
                    {"Range": "bytes=0-9", "If-Range": last_modified},
                )
                self.assertEqual(206, status)
                self.assertEqual(PAYLOAD[0:10], body)
                self.assertEqual(f"bytes 0-9/{len(PAYLOAD)}", headers.get("Content-Range"))


class RangeAdmissionTests(unittest.TestCase):
    def test_private_manifest_outside_control_traversal_and_listing_stay_404_with_range(self):
        refused = (
            "/narration/private/audio/original.wav",
            "/previews/../narration/private/audio/original.wav",
            "/previews/%2e%2e/narration/private/audio/original.wav",
            "/previews/%2e%2e/manifest.json",
            "/manifest.json",
            "/reviews/decision.json",
            "/../secret.txt",
            "/previews/%00x.mp4",
            "/previews/",
            "/previews",
            "/clips/",
            "/previews/.hidden.mp4",
        )
        with tempfile.TemporaryDirectory() as tmp:
            root = _project_with_media(Path(tmp))
            (root / "brolls" / "previews" / ".hidden.mp4").write_bytes(b"hidden")
            with _serving(root) as (_server, port):
                for path in refused:
                    with self.subTest(path=path):
                        status, headers, body = _request(port, "GET", path, {"Range": "bytes=0-10"})
                        self.assertEqual(404, status)
                        self.assertEqual("nosniff", headers.get("X-Content-Type-Options"))
                        self.assertEqual("no-store", headers.get("Cache-Control"))
                        self.assertNotIn(PRIVATE_MARKER, body)
                        self.assertNotIn(b"outside-secret", body)
                        self.assertNotIn(b"ledger", body)
                        payload = json.loads(body.decode("utf-8"))
                        self.assertEqual({"error": "Não encontrado."}, payload)

    def test_security_admission_precedes_opening_the_private_original(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = _project_with_media(Path(tmp))
            private = (root / "brolls" / "narration" / "private" / "audio" / "original.wav").resolve()
            real_open = builtins.open

            def guarded(path, *args, **kwargs):
                try:
                    candidate = Path(path).resolve()
                except (OSError, TypeError, ValueError):
                    return real_open(path, *args, **kwargs)
                if candidate == private:
                    raise AssertionError("private original was opened")
                return real_open(path, *args, **kwargs)

            with _serving(root) as (_server, port), patch.object(builtins, "open", side_effect=guarded):
                for path in (
                    "/narration/private/audio/original.wav",
                    "/previews/%2e%2e/narration/private/audio/original.wav",
                    "/previews/../narration/private/audio/original.wav",
                ):
                    status, _headers, body = _request(port, "GET", path, {"Range": "bytes=0-10"})
                    self.assertEqual(404, status)
                    self.assertNotIn(PRIVATE_MARKER, body)

                status, _headers, body = _request(port, "GET", "/previews/clip.mp4", {"Range": "bytes=0-3"})
                self.assertEqual(206, status)
                self.assertEqual(PAYLOAD[0:4], body)

    def test_foreign_host_is_still_403_when_range_is_present(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = _project_with_media(Path(tmp))
            with _serving(root) as (_server, port):
                status, headers, body = _request(
                    port,
                    "GET",
                    "/previews/clip.mp4",
                    {"Range": "bytes=0-9", "Host": "evil.test:80"},
                )
                self.assertEqual(403, status)
                self.assertNotIn(PAYLOAD[:8], body)
                payload = json.loads(body.decode("utf-8"))
                self.assertIn("error", payload)
                self.assertEqual("no-store", headers.get("Cache-Control"))

    def test_range_does_not_apply_to_review_html_or_take_the_writer_lock(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = _project_with_media(Path(tmp))
            before = _snapshot(root)
            with _serving(root) as (_server, port):
                status, headers, body = _request(port, "GET", "/review.html", {"Range": "bytes=0-3"})
                self.assertEqual(200, status)
                self.assertIn(b"storyboard", body)
                self.assertIsNone(headers.get("Content-Range"))
                self.assertNotEqual("3", headers.get("Content-Length"))

                status, headers, body = _request(port, "GET", "/previews/clip.mp4", {"Range": "bytes=2-5"})
                self.assertEqual(206, status)
                self.assertEqual(PAYLOAD[2:6], body)

            after = _snapshot(root)
            self.assertEqual(before, after)
            self.assertFalse((root / "brolls" / ".command.lock").exists())
            self.assertFalse((root / ".command.lock").exists())
