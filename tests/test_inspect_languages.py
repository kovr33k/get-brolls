"""Source-language inspection: real scoring and bounded yt-dlp selection, offline."""

import json
import re
import tempfile
import unicodedata
import unittest
from pathlib import Path
from unittest.mock import patch

import _isolation  # noqa: F401
from _paths import ROOT  # noqa: F401
from test_inspect import run_cli, stub_ytdlp

from getbrolls import broadcasts, inspecting, social
from getbrolls.cli import build_parser

URL = "https://www.youtube.com/watch?v=abcdefghijk"
VTT = "WEBVTT\nLanguage: {language}\n\n00:00:20.000 --> 00:00:24.000\n{text}\n"


def cue(text):
    return {"start_s": 20.0, "end_s": 24.0, "text": text}


class UnicodeInspectionTests(unittest.TestCase):
    def test_cyrillic_letters_survive_composed_and_decomposed_input(self):
        text = "Київ їде йому, русский край, ґанок Європи 2026"
        expected = ["київ", "їде", "йому", "русский", "край", "ґанок", "європи", "2026"]
        self.assertEqual(expected, inspecting.tokens(text))
        self.assertEqual(expected, inspecting.tokens(unicodedata.normalize("NFD", text)))
        self.assertNotEqual(inspecting.tokens("й ї ё"), inspecting.tokens("и і е"))

    def test_latin_accent_and_case_folding_remain_compatible(self):
        self.assertEqual(
            ["ceu", "naranja", "nino", "acao", "gtc", "2024"], inspecting.tokens("CÉU naranja niño ação GTC 2024")
        )

    def test_the_matching_second_track_wins_before_duplicate_intervals_are_removed(self):
        for language, query in (("es", "cielo naranja"), ("ru", "оранжевое небо"), ("uk", "північний Київ")):
            with self.subTest(language=language):
                probe = {
                    "duration_s": 90,
                    "subtitles": {
                        "en": {"cues": [cue("orange sky")]},
                        language: {"cues": [cue(query)], "kind": "manual", "is_original": True},
                    },
                }
                windows = inspecting.candidate_windows(probe, query, 3, language=language)
                self.assertEqual(1, len(windows))
                self.assertEqual(1.0, windows[0]["score"])
                self.assertEqual(query, windows[0]["text"])
                self.assertEqual(language, windows[0]["language"])
                self.assertEqual("manual", windows[0]["subtitle_kind"])
                self.assertTrue(windows[0]["is_original"])

    def test_explicit_language_breaks_a_name_only_tie_without_guessing(self):
        probe = {"subtitles": {"en": {"cues": [cue("Jensen Huang")]}, "es-ES": {"cues": [cue("Jensen Huang")]}}}
        self.assertIsNone(inspecting.guess_language("Jensen Huang"))
        self.assertEqual("es-ES", inspecting.candidate_windows(probe, "Jensen Huang", language="es")[0]["language"])

    def test_catalog_captions_with_unknown_language_keep_their_score(self):
        probe = {"subtitles": {"und": {"cues": [cue("північний Київ")]}}}
        self.assertEqual(1.0, inspecting.candidate_windows(probe, "північний Київ", language="uk")[0]["score"])

    def test_language_hints_require_words_and_do_not_classify_names(self):
        for language, text in (
            ("es", "el momento cuando dice"),
            ("ru", "где он говорит что это"),
            ("uk", "коли він каже що це"),
        ):
            self.assertEqual(language, inspecting.guess_language(text))
        for name in ("Jensen Huang", "Микола Київ", "Juan Carlos"):
            self.assertIsNone(inspecting.guess_language(name))


class SubtitleAcquisitionTests(unittest.TestCase):
    def probe(self, data, language=None, missing=(), fail_after_write=False):
        calls = []

        def run(arguments, timeout=180, **kwargs):
            calls.append(arguments)
            if "--load-info-json" not in arguments:
                return json.dumps(data), []
            loaded = json.loads(Path(arguments[arguments.index("--load-info-json") + 1]).read_text(encoding="utf-8"))
            self.assertEqual(data, loaded)
            self.assertIn("--skip-download", arguments)
            self.assertIn("--no-simulate", arguments)
            template = arguments[arguments.index("-o") + 1]
            patterns = arguments[arguments.index("--sub-langs") + 1].split(",")
            available = {}
            if "--write-subs" in arguments:
                available.update(data.get("subtitles") or {})
            if "--write-auto-subs" in arguments:
                for code, tracks in (data.get("automatic_captions") or {}).items():
                    available.setdefault(code, tracks)
            for code, tracks in available.items():
                if code not in missing and any(re.fullmatch(pattern, code) for pattern in patterns):
                    text = tracks[0].get("text", "cielo naranja")
                    if text is None:
                        continue
                    Path(template.replace("%(ext)s", code + ".vtt")).write_text(
                        VTT.format(language=code, text=text), encoding="utf-8"
                    )
            if fail_after_write:
                raise social.ProviderError("Synthetic subtitle batch failure")
            return "", []

        with tempfile.TemporaryDirectory() as tmp, patch.object(social, "run", side_effect=run):
            kwargs = {"langs": (language,)} if language else {}
            result = social.probe_remote(URL, cache=Path(tmp), **kwargs)
        return result, calls

    def test_requested_es_ru_uk_regional_author_track_precedes_auto(self):
        for code in ("es-ES", "ru-RU", "uk-UA", "pt-BR", "en-US"):
            with self.subTest(code=code):
                base = code.split("-")[0]
                data = {
                    "duration": 90,
                    "language": code,
                    "subtitles": {code: [{"ext": "vtt", "text": "author text"}]},
                    "automatic_captions": {base + "-orig": [{"ext": "vtt", "text": "auto text"}]},
                }
                result, calls = self.probe(data, base)
                self.assertEqual([code], list(result["subtitles"]))
                self.assertEqual("manual", result["subtitles"][code]["kind"])
                self.assertTrue(result["subtitles"][code]["is_original"])
                self.assertIn("--write-subs", calls[-1])

    def test_original_auto_is_downloaded_even_without_an_explicit_language(self):
        for code in ("es", "ru", "uk"):
            with self.subTest(code=code):
                data = {
                    "automatic_captions": {
                        **{f"x{n}": [{"ext": "vtt"}] for n in range(300)},
                        code + "-orig": [{"ext": "vtt"}],
                    }
                }
                result, calls = self.probe(data)
                self.assertEqual([code + "-orig"], list(result["subtitles"]))
                self.assertEqual("automatic", result["subtitles"][code + "-orig"]["kind"])
                self.assertEqual(2, len(calls))
                self.assertNotIn("all", calls[-1])

    def test_original_name_marker_and_regional_request_are_supported(self):
        data = {
            "automatic_captions": {"es-419": [{"ext": "vtt", "name": "Spanish (Original)"}], "en": [{"ext": "vtt"}]}
        }
        result, _ = self.probe(data, "es-MX")
        self.assertEqual(["es-419"], list(result["subtitles"]))
        self.assertTrue(result["subtitles"]["es-419"]["is_original"])

    def test_multiple_original_tracks_follow_declared_audio_not_dict_order(self):
        tracks = {"en-orig": [{"ext": "vtt"}], "ru-orig": [{"ext": "vtt"}], "ru": [{"ext": "vtt"}]}
        for automatic in (tracks, dict(reversed(list(tracks.items())))):
            result, _ = self.probe({"language": "ru", "automatic_captions": automatic}, "ru")
            self.assertEqual("ru-orig", result["original_lang"])
            self.assertEqual(["ru-orig"], list(result["subtitles"]))
        ambiguous, _ = self.probe({"automatic_captions": tracks}, "ru")
        self.assertIsNone(ambiguous["original_lang"])
        self.assertEqual(["ru-orig"], list(ambiguous["subtitles"]))
        self.assertTrue(ambiguous["subtitle_warnings"])

    def test_declared_language_without_captions_is_not_advertised_as_a_track(self):
        result, _ = self.probe({"language": "es", "subtitles": {}, "automatic_captions": {}})
        self.assertEqual("es", result["original_lang"])
        self.assertEqual([], result["subtitle_langs"])

    def test_known_original_without_a_matching_track_does_not_fetch_another_language(self):
        result, calls = self.probe({"language": "en", "subtitles": {"fr": [{"text": "autre langue"}]}})
        self.assertEqual("en", result["original_lang"])
        self.assertEqual({}, result["subtitles"])
        self.assertEqual([], result["subtitle_tracks"])
        self.assertEqual(1, len(calls))
        self.assertTrue(any("original language en" in warning for warning in result["subtitle_warnings"]))

    def test_same_code_author_subtitles_win_over_automatic(self):
        result, _ = self.probe(
            {
                "language": "ru",
                "subtitles": {"ru": [{"text": "автор"}]},
                "automatic_captions": {"ru": [{"text": "автомат"}]},
            },
            "ru",
        )
        self.assertEqual("автор", result["subtitles"]["ru"]["cues"][0]["text"])

    def test_failed_original_author_track_has_one_auto_fallback(self):
        for original in ("ru", "ru-orig"):
            with self.subTest(original=original):
                result, calls = self.probe(
                    {
                        "language": "ru",
                        "subtitles": {"ru": [{"text": None}]},
                        "automatic_captions": {original: [{"text": "Київ йому"}]},
                    },
                    "ru",
                )
                self.assertEqual("automatic", result["subtitles"][original]["kind"])
                self.assertEqual("Київ йому", result["subtitles"][original]["cues"][0]["text"])
                self.assertEqual(["unavailable", "obtained"], [track["status"] for track in result["subtitle_tracks"]])
                self.assertEqual(3, len(calls))
                self.assertIn("--no-write-subs", calls[-1])

    def test_a_failed_track_keeps_another_obtained_language(self):
        result, _ = self.probe(
            {"language": "en", "subtitles": {"es": [{"text": "cielo naranja"}], "en": [{"text": None}]}}, "es"
        )
        self.assertEqual(["es"], list(result["subtitles"]))
        self.assertEqual("obtained", result["subtitle_tracks"][0]["status"])

    def test_a_failed_batch_preserves_metadata_and_already_written_subtitles(self):
        result, _ = self.probe(
            {"title": "Source", "duration": 90, "language": "es", "subtitles": {"es": [{"text": "cielo naranja"}]}},
            "es",
            fail_after_write=True,
        )
        self.assertEqual("Source", result["title"])
        self.assertEqual(90, result["duration_s"])
        self.assertTrue(result["subtitles"]["es"]["cues"])
        self.assertTrue(result["subtitle_warnings"])

    def test_metadata_only_scan_does_not_download_subtitles(self):
        with patch.object(
            social, "run", return_value=(json.dumps({"language": "ru", "automatic_captions": {"ru-orig": [{}]}}), [])
        ) as run:
            result = social.probe_remote(URL, langs=())
        self.assertEqual(1, run.call_count)
        self.assertEqual({}, result["subtitles"])

    def test_absent_requested_language_has_only_a_bounded_honest_fallback(self):
        result, calls = self.probe({"subtitles": {"fr": [{"ext": "vtt"}], "de": [{"ext": "vtt"}]}}, "uk")
        self.assertEqual(1, len(result["subtitles"]))
        self.assertIsNone(result["original_lang"])
        self.assertTrue(result["subtitle_warnings"])
        self.assertEqual(2, len(calls))

    def test_no_subtitles_remain_distinct_from_advertised_but_failed_download(self):
        absent, calls = self.probe({"duration": 90, "subtitles": {}, "automatic_captions": {}}, "es")
        self.assertEqual({}, absent["subtitles"])
        self.assertEqual(1, len(calls))
        failed, calls = self.probe(
            {"duration": 90, "language": "es", "subtitles": {"es": [{"ext": "vtt"}]}}, "es", missing=("es",)
        )
        self.assertEqual({}, failed["subtitles"])
        self.assertEqual(["es"], failed["subtitle_langs"])
        self.assertEqual("unavailable", failed["subtitle_tracks"][0]["status"])
        self.assertTrue(failed["subtitle_warnings"])
        self.assertEqual(2, len(calls))

    def test_bad_language_does_not_turn_into_a_regex_or_all_tracks(self):
        for language in ("all", "en.*", "ru,uk", "../es", ""):
            with self.subTest(language=language), patch.object(social, "run") as run:
                with self.assertRaises(ValueError):
                    social.probe_remote(URL, langs=(language,))
                run.assert_not_called()


class InspectLanguageRoutingTests(unittest.TestCase):
    def test_cli_source_language_reaches_download_scoring_and_output(self):
        for language, query in (("es", "cielo naranja"), ("ru", "оранжевое небо"), ("uk", "північний Київ")):
            with self.subTest(language=language), tempfile.TemporaryDirectory() as tmp:
                data = {
                    "id": "abcdefghijk",
                    "duration": 90,
                    "language": "en",
                    "subtitles": {"en": [{"ext": "vtt"}], language: [{"ext": "vtt"}]},
                }
                text = VTT.format(language=language, text=query)
                env = stub_ytdlp(tmp, data, {language: text, "en": VTT.format(language="en", text="orange sky")})
                done = run_cli(
                    ["inspect", "--project", tmp, "--url", URL, "--query", query, "--language", language], env
                )
                self.assertEqual(0, done.returncode, done.stdout + done.stderr)
                result = json.loads(done.stdout)
                self.assertEqual(language, result["query_language"])
                self.assertEqual([language, "en"], result["obtained_subtitle_langs"])
                self.assertEqual("en", result["original_lang"])
                self.assertEqual(1.0, result["candidate_windows"][0]["score"])
                self.assertEqual(language, result["candidate_windows"][0]["language"])
                self.assertFalse((Path(tmp) / "brolls" / "manifest.json").exists())

    def test_inspect_accepts_language_without_changing_the_legacy_default(self):
        parser = build_parser()
        args = parser.parse_args(["inspect", "--project", "p", "--url", URL, "--language", "uk"])
        self.assertEqual("uk", args.language)
        legacy = parser.parse_args(["inspect", "--project", "p", "--url", URL])
        self.assertIsNone(legacy.language)

    def test_remote_route_passes_the_language_and_keeps_ec_transport(self):
        with patch.object(social, "probe_remote", return_value={}) as probe:
            broadcasts.inspect_remote({"provider": "youtube"}, URL, Path("cache"), language="ru")
            self.assertEqual(("ru",), probe.call_args.kwargs["langs"])
            broadcasts.inspect_remote(
                {"provider": "ec_audiovisual", "media_url": "https://example.org/video"},
                URL,
                Path("cache"),
                language="es",
            )
            self.assertEqual(URL, probe.call_args.kwargs["source_url"])
            self.assertEqual(("es",), probe.call_args.kwargs["langs"])

    def test_un_transcript_route_is_retained(self):
        transcript = {"uk": {"cues": [cue("Київ")]}}
        item = {"provider": "un_webtv", "source_url": URL}
        with (
            patch.object(social, "probe_remote", return_value={}),
            patch.object(broadcasts, "transcript_probe", return_value=transcript),
        ):
            self.assertEqual(
                transcript, broadcasts.inspect_remote(item, URL, Path("cache"), language="uk")["subtitles"]
            )


if __name__ == "__main__":
    unittest.main()
