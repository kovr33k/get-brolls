"""Audited geographic/session routes, private transports and independent review gates."""

import json
import os
import tempfile
import unittest
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import _isolation  # noqa: F401
from _media import skip_unless_ffmpeg, synth_image, synth_video
from test_existing_catalog_fragments import call, confirm, image_rules, progress_row, save_plan, storyboard, write_brief

from getbrolls import account_catalogs as accounts
from getbrolls import providers
from getbrolls.ledger import Ledger
from getbrolls.models import approve
from getbrolls.runtime import OperationError, audited

BBOX = "-3.709,40.414,-3.706,40.416"
PERIOD = ["from_date=2026-10-01", "to_date=2026-10-04"]
PAGE = "https://t.me/fixture_channel/30"
SECRET = "fixture_private_session_secret_never_export"


def map_record(identity="100", **changes):
    return {
        "id": identity,
        "geometry": {"coordinates": [-3.707, 40.415]},
        "captured_at": 1600000000000,
        "creator": {"username": "Fixture photographer"},
        "sequence": "sequence-fixture",
        "width": 480,
        "height": 270,
        "thumb_original_url": "https://media.example.org/street.jpg?oh=" + SECRET,
        "thumb_2048_url": "https://media.example.org/street-small.jpg?oh=" + SECRET,
        **changes,
    }


def message(identity, *, photo=True, date=None, attachment=1000, caption="Synthetic laboratory bench"):
    asset = SimpleNamespace(id=attachment)
    return SimpleNamespace(
        id=identity,
        date=date or datetime(2026, 10, 3, tzinfo=UTC),
        raw_text=caption,
        photo=asset if photo else None,
        document=None if photo else asset,
        file=SimpleNamespace(
            mime_type="image/jpeg" if photo else "video/mp4",
            width=480,
            height=270,
            duration=None if photo else 6,
            size=1000,
        ),
        grouped_id=999,
        fwd_from=SimpleNamespace(from_id=SECRET),
        media=asset,
    )


class FakeClient:
    def __init__(self, messages=(), *, authorized=True, failure=None, source=None, public=True):
        self.messages = list(messages)
        self.authorized = authorized
        self.failure = failure
        self.source = source
        self.public = public
        self.entities = []
        self.queries = []

    async def connect(self):
        return None

    async def disconnect(self):
        return None

    async def is_user_authorized(self):
        return self.authorized

    async def get_me(self):
        return SimpleNamespace(bot=False)

    async def get_entity(self, username):
        self.entities.append(username)
        return SimpleNamespace(username=username, broadcast=self.public)

    async def get_messages(self, entity, ids):
        return next((m for m in self.messages if m.id == ids), None)

    async def iter_messages(self, entity, **kwargs):
        self.queries.append(kwargs)
        available = [m for m in self.messages if not kwargs["offset_id"] or m.id < kwargs["offset_id"]]
        if self.failure and not available:
            raise self.failure
        for index, row in enumerate(available[: kwargs["limit"]]):
            yield row
            if self.failure and index == 0:
                raise self.failure

    async def iter_download(self, media):
        if self.source is None:
            raise ValueError("Fixture source was not supplied")
        yield self.source.read_bytes()

    async def download_media(self, message, file, progress_callback):
        if self.source is None:
            raise ValueError("Fixture source was not supplied")
        data = self.source.read_bytes()
        progress_callback(len(data), len(data))
        Path(file).write_bytes(data)
        return file


class FloodWaitError(Exception):
    def __init__(self, seconds):
        self.seconds = seconds
        super().__init__(SECRET)


def planned(project, provider, query="laboratory bench", media="image", limit=3, resume=False, filters=None):  # noqa: PLR0913, PLR0917 - audited CLI scenario inputs
    args = [
        "search",
        "--planned",
        "--provider",
        provider,
        "--shot",
        "opening",
        "--query",
        query,
        "--media",
        media,
        "--limit",
        str(limit),
    ]
    for value in filters if filters is not None else (["bbox=" + BBOX] if provider == "mapillary" else PERIOD):
        args.extend(("--catalog-filter", value))
    if resume:
        args.append("--resume-history")
    return call(project, *args)


class AccountContracts(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.project = Path(self.temp.name)
        self.env = patch.dict(
            os.environ,
            {
                "MAPILLARY_TOKEN": "fixture_mapillary_token",
                "TELEGRAM_API_ID": "12345",
                "TELEGRAM_API_HASH": "1" * 32,
                "TELEGRAM_SESSION": str(self.project / "private.session"),
                "BROLL_TELEGRAM_CHANNELS": '["@fixture_channel"]',
                "GB_LIBRARY": "off",
            },
        )
        self.env.start()
        self.addCleanup(self.env.stop)
        self.addCleanup(self.temp.cleanup)

    def test_geographic_request_keeps_representation_and_unknowns_without_signed_links(self):
        with patch.object(
            accounts,
            "get_json",
            return_value={
                "data": [map_record(), map_record("200", creator=None, geometry=None, captured_at=None, sequence=None)]
            },
        ) as transport:
            rows = providers.search("mapillary", "street topic", 2, "image", ["bbox=" + BBOX])
            self.assertNotIn("q", transport.call_args.args[1])
            self.assertEqual(BBOX, transport.call_args.args[1]["bbox"])
            self.assertEqual("thumb_original_url", rows[0]["catalog"]["selected_file"])
            self.assertFalse(rows[0]["catalog"]["topic_query_applied"])
            self.assertIsNone(rows[0].get("media_url"))
            self.assertIsNone(rows[1]["creator"]["name"])
            self.assertIsNone(rows[1]["captured_at"])
            self.assertNotIn(SECRET, json.dumps(rows))
            with self.assertRaisesRegex(ValueError, "moving footage"):
                providers.search("mapillary", "street", media="video", catalog_filters=["bbox=" + BBOX])
        with patch.dict(os.environ, {"MAPILLARY_TOKEN": ""}), self.assertRaisesRegex(ValueError, "MAPILLARY_TOKEN"):
            providers.search("mapillary", "street", catalog_filters=["bbox=" + BBOX])

    def test_missing_geography_and_invalid_filters_do_not_spend_an_attempt(self):
        write_brief(self.project, ["mapillary"])
        save_plan(self.project, "mapillary")
        with patch.object(accounts, "get_json") as transport:
            for filters in ([], ["bbox=nan,0,1,1"], ["bbox=0,0,1,1", "token=secret"]):
                with self.assertRaises(OperationError):
                    planned(self.project, "mapillary", filters=filters)
            self.assertFalse(transport.called)
        self.assertEqual(0, progress_row(self.project)["queries_used"])
        with self.assertRaisesRegex(ValueError, "representation"):
            accounts._map_row(map_record(thumb_original_url=None), "thumb_original_url")

    def test_configuration_rejects_nonpublic_channels_and_source_session_storage(self):
        for value in ('["me"]', '["https://t.me/fixture_channel"]', "[12345]", "[]", "me,https://t.me/private"):
            with patch.dict(os.environ, {"BROLL_TELEGRAM_CHANNELS": value}), self.assertRaises(ValueError):
                accounts.telegram_config()
        with patch.dict(os.environ, {"TELEGRAM_API_HASH": "invalid"}), self.assertRaisesRegex(ValueError, "32"):
            accounts.telegram_config()
        for root in accounts._source_roots():
            with (
                patch.dict(os.environ, {"TELEGRAM_SESSION": str(root / "private.session")}),
                self.assertRaisesRegex(ValueError, "outside"),
            ):
                accounts.telegram_config()
        with patch.dict(os.environ, {"TELEGRAM_SESSION": "fixture-name"}):
            self.assertTrue(accounts.telegram_config()[2].is_absolute())
            self.assertTrue(accounts.telegram_config()[2].is_relative_to(Path.home()))
        with patch.dict(
            os.environ,
            {"TELEGRAM_SESSION": "sessions/fixture", "BROLL_TELEGRAM_CHANNELS": "@fixture_channel, other_channel"},
        ):
            config = accounts.telegram_config()
            self.assertEqual(Path.home() / ".getbrolls" / "sessions" / "fixture.session", config[2])
            self.assertEqual(["fixture_channel", "other_channel"], config[3])

    def test_login_required_is_distinct_and_secrets_are_not_exported(self):
        fake = FakeClient(authorized=False)
        with patch.object(accounts, "_client", return_value=fake), self.assertRaisesRegex(ValueError, "telegram-login"):
            providers.search("telegram", "query", catalog_filters=PERIOD, ledger=Ledger(self.project))
        self.assertFalse(fake.entities)
        with (
            patch.object(accounts.sys.stdin, "isatty", return_value=False),
            self.assertRaisesRegex(ValueError, "interactive"),
        ):
            accounts.telegram_login()
        with (
            patch.dict(accounts.sys.modules, {"telethon": None}),
            patch.object(accounts.sys.stdin, "isatty", return_value=True),
            self.assertRaisesRegex(ValueError, "requirements-telegram.txt"),
        ):
            accounts.telegram_login()
        self.assertNotIn(
            SECRET,
            (self.project / "brolls" / "manifest.json").read_text()
            if (self.project / "brolls" / "manifest.json").exists()
            else "",
        )

    def test_interactive_login_supplies_2fa_callbacks_without_returning_secrets(self):
        assert_valid = self.assertTrue

        class LoginClient(FakeClient):
            async def start(self, **kwargs):
                for key in ("phone", "code_callback", "password"):
                    assert_valid(kwargs[key]() == SECRET)

        fake = LoginClient()
        with (
            patch.object(accounts, "_client", return_value=fake),
            patch.object(accounts.sys.stdin, "isatty", return_value=True),
            patch("getpass.getpass", return_value=SECRET) as prompt,
        ):
            result = accounts.telegram_login()
        self.assertEqual(3, prompt.call_count)
        self.assertTrue(result["session_authorized"])
        self.assertNotIn(SECRET, json.dumps(result))

    def test_login_errors_are_actionable_private_and_leave_the_session_intact(self):
        session = self.project / "private.session"
        session.write_bytes(b"synthetic existing session")
        for name, phrase in (
            ("PhoneNumberInvalidError", "international number"),
            ("PhoneCodeInvalidError", "latest code"),
            ("PhoneCodeEmptyError", "requires a login code"),
            ("PhoneCodeExpiredError", "expired"),
            ("PasswordHashInvalidError", "two-step verification password"),
        ):
            with self.subTest(error=name):
                error = type(name, (Exception,), {})(SECRET)
                fake = SimpleNamespace(start=AsyncMock(side_effect=error), disconnect=AsyncMock())
                with (
                    patch.object(accounts, "_client", return_value=fake),
                    patch.object(accounts.sys.stdin, "isatty", return_value=True),
                    self.assertRaises(OperationError) as ctx,
                ):
                    audited(
                        SimpleNamespace(command="telegram-login", project=str(self.project)),
                        lambda args: accounts.telegram_login(),
                    )
                payload = ctx.exception.payload
                self.assertIn(phrase, payload["message"])
                self.assertFalse(payload["state_committed"])
                self.assertNotIn("traceback", payload)
                self.assertNotIn("repr", payload)
                self.assertNotIn("RULES.md", payload["message"])
                self.assertNotIn("review", payload["hint"])
                fake.disconnect.assert_awaited_once()
                self.assertEqual(b"synthetic existing session", session.read_bytes())
        diagnostic = json.loads((self.project / "brolls" / "diagnostics.jsonl").read_text().splitlines()[-1])
        self.assertIn("traceback", diagnostic)
        self.assertNotIn(SECRET, json.dumps(diagnostic))

    def test_exhausted_login_code_attempts_explain_the_retry_without_rpc_secrets(self):
        for error, expected in (
            (RuntimeError("3 consecutive sign-in attempts failed. Aborting"), "latest code for the new request"),
            (RuntimeError(SECRET), "RuntimeError"),
        ):
            fake = SimpleNamespace(start=AsyncMock(side_effect=error), disconnect=AsyncMock())
            with (
                patch.object(accounts, "_client", return_value=fake),
                patch.object(accounts.sys.stdin, "isatty", return_value=True),
                self.assertRaisesRegex(ValueError, expected) as ctx,
            ):
                accounts.telegram_login()
            self.assertNotIn(SECRET, str(ctx.exception))
            fake.disconnect.assert_awaited_once()

    def test_login_prompts_trim_phone_and_code_but_preserve_2fa_password(self):
        observed = {}

        class LoginClient(FakeClient):
            async def start(self, **kwargs):
                observed.update({key: kwargs[key]() for key in ("phone", "code_callback", "password")})

        with (
            patch.object(accounts, "_client", return_value=LoginClient()),
            patch.object(accounts.sys.stdin, "isatty", return_value=True),
            patch(
                "getpass.getpass", side_effect=["  +12345678901  ", "  fixture code  ", " password with spaces "]
            ) as prompt,
        ):
            accounts.telegram_login()
        self.assertEqual("+12345678901", observed["phone"])
        self.assertEqual("fixture code", observed["code_callback"])
        self.assertEqual(" password with spaces ", observed["password"])
        self.assertIn("+country code", prompt.call_args_list[0].args[0])

    def test_interrupted_login_disconnects_without_project_recovery_advice(self):
        fake = SimpleNamespace(start=AsyncMock(side_effect=KeyboardInterrupt), disconnect=AsyncMock())
        with (
            patch.object(accounts, "_client", return_value=fake),
            patch.object(accounts.sys.stdin, "isatty", return_value=True),
            self.assertRaises(OperationError) as ctx,
        ):
            audited(SimpleNamespace(command="telegram-login"), lambda args: accounts.telegram_login())
        self.assertEqual("INTERRUPTED", ctx.exception.payload["error_code"])
        self.assertIn("telegram-login again locally", ctx.exception.payload["message"])
        self.assertNotIn("gravação", ctx.exception.payload["message"])
        fake.disconnect.assert_awaited_once()

    def test_whitelist_message_identity_and_public_channel_boundary(self):
        fake = FakeClient([message(30)])
        with patch.object(accounts, "_client", return_value=fake):
            rows = providers.search("telegram", "bench", catalog_filters=PERIOD)
            self.assertEqual(PAGE, rows[0]["source_url"])
            self.assertEqual("photo:1000", rows[0]["catalog"]["selected_file"])
            self.assertEqual("999", rows[0]["catalog"]["grouped_id"])
            self.assertIsNone(rows[0].get("captured_at"))
            self.assertEqual("2026-10-03T00:00:00+00:00", rows[0]["catalog"]["published_at"])
            self.assertTrue(rows[0]["catalog"]["forwarded"])
            self.assertIsNone(rows[0]["catalog"]["original_source_url"])
            self.assertNotIn(SECRET, json.dumps(rows))
            with self.assertRaisesRegex(ValueError, "whitelist"):
                providers.resolve("https://t.me/another_channel/30")
            with self.assertRaisesRegex(ValueError, "identity"):
                providers.resolve(PAGE, catalog_file="photo:9999")
        self.assertEqual({"fixture_channel"}, set(fake.entities))
        with patch.object(accounts, "_client", return_value=FakeClient([message(30)], public=False)):
            self.assertEqual([], providers.search("telegram", "bench", catalog_filters=PERIOD))

    def test_changed_telegram_publication_date_invalidates_review(self):
        original = accounts._message_row("fixture_channel", message(30))
        assert original is not None
        approve(original, "Synthetic fixture reviewer", statement="Approve this synthetic fixture only")
        original["rights"]["status"] = "permitted"
        later = message(30, date=datetime(2026, 10, 4, tzinfo=UTC))
        with patch.object(accounts, "_client", return_value=FakeClient([later])):
            refreshed = accounts.refresh(original)
        self.assertIsNone(refreshed["captured_at"])
        self.assertEqual("2026-10-04T00:00:00+00:00", refreshed["catalog"]["published_at"])
        self.assertEqual("pending", refreshed["approval"]["status"])

    def test_audited_cursor_continues_after_restart_without_renewing_allowance(self):
        write_brief(self.project, ["telegram"])
        save_plan(self.project, "telegram")
        fake = FakeClient([message(30), message(20, attachment=2000), message(10, attachment=3000)])
        with patch.object(accounts, "_client", return_value=fake):
            first = planned(self.project, "telegram", limit=1)
            replay = planned(self.project, "telegram", limit=1)
            self.assertTrue(replay["replayed"])
            self.assertEqual(1, len(fake.queries))
            resumed = planned(self.project, "telegram", query=" LABORATORY   BENCH ", limit=2, resume=True)
            self.assertEqual(2, len(resumed["items"]))
            self.assertEqual(30, fake.queries[1]["offset_id"])
            self.assertEqual(first["items"][0]["id"], resumed["items"][0]["id"])
        self.assertEqual(1, progress_row(self.project)["queries_used"])
        state = next(iter(Ledger(self.project, recover=False).data["telegram_history"].values()))
        self.assertEqual(20, state["channels"]["fixture_channel"]["offset_id"])

    def test_interrupted_history_keeps_result_and_cursor_for_explicit_resume(self):
        write_brief(self.project, ["telegram"])
        save_plan(self.project, "telegram")
        failed = FakeClient([message(30)], failure=OSError(SECRET))
        with patch.object(accounts, "_client", return_value=failed):
            result = planned(self.project, "telegram")
        self.assertEqual("access_or_provider_error", result["attempt"]["status"])
        state = next(iter(Ledger(self.project, recover=False).data["telegram_history"].values()))
        self.assertEqual(30, state["channels"]["fixture_channel"]["offset_id"])
        self.assertEqual(1, len(state["rows"]))
        with patch.object(
            accounts, "_client", return_value=FakeClient([message(30), message(20, attachment=2000)])
        ) as transport:
            resumed = planned(self.project, "telegram", resume=True)
            self.assertEqual(2, len(resumed["items"]))
            self.assertEqual(1, transport.call_count)
        self.assertEqual(1, progress_row(self.project)["queries_used"])
        self.assertNotIn(SECRET, (self.project / "brolls" / "manifest.json").read_text())

    def test_short_wait_retries_once_and_long_wait_survives_restart(self):
        fake = FakeClient([message(30)], failure=FloodWaitError(1))
        with (
            patch.object(accounts, "_client", return_value=fake),
            patch.object(accounts.asyncio, "sleep", new=AsyncMock()) as sleep,
        ):
            providers.search("telegram", "bench", catalog_filters=PERIOD, ledger=Ledger(self.project))
            sleep.assert_awaited_once_with(1)
        self.assertEqual(30, fake.queries[1]["offset_id"])
        self.assertIn("telegram_access", Ledger(self.project, recover=False).data)
        fake = FakeClient([], failure=FloodWaitError(120))
        project = self.project / "long-wait"
        with patch.object(accounts, "_client", return_value=fake):
            providers.search("telegram", "bench", catalog_filters=PERIOD, ledger=Ledger(project))
        ledger = Ledger(project, recover=False)
        self.assertGreater(
            datetime.fromisoformat(ledger.data["telegram_access"]["next_eligible_at"]), datetime.now(UTC)
        )
        with patch.object(accounts, "_client") as transport, self.assertRaisesRegex(ValueError, "still active"):
            providers.search("telegram", "another wording", catalog_filters=PERIOD, ledger=ledger)
        self.assertFalse(transport.called)

    def test_period_bounds_skip_old_messages_without_presenting_them_as_matches(self):
        fake = FakeClient([message(30), message(20, date=datetime(2020, 1, 1, tzinfo=UTC)), message(10)])
        with patch.object(accounts, "_client", return_value=fake):
            rows = providers.search("telegram", "bench", catalog_filters=PERIOD, ledger=Ledger(self.project))
        self.assertEqual(["fixture_channel:30"], [r["source_id"] for r in rows])
        self.assertLessEqual(fake.queries[0]["limit"], accounts.MAX_HISTORY)
        with self.assertRaisesRegex(ValueError, "from_date"):
            providers.search("telegram", "bench")

    def test_x_diagnostics_never_use_keys_or_claim_tool_access(self):
        path = self.project / "auth.json"
        record = {
            "auth_mode": "oidc",
            "oidc_issuer": "https://auth.x.ai",
            "key": SECRET,
            "refresh_token": SECRET,
            "expires_at": (datetime.now(UTC) - timedelta(hours=1)).isoformat(),
            "email": SECRET,
        }
        path.write_text(json.dumps({"issuer::client": record}))
        with patch.dict(os.environ, {"XAI_API_KEY": SECRET}), patch.object(accounts, "get_json") as transport:
            result = accounts.x_access(path, "retained-fixture-model")
            self.assertEqual("expired", result["oauth"])
            self.assertTrue(result["refresh_available"])
            self.assertFalse(result["api_key_used"])
            self.assertFalse(result["billing_fallback"])
            self.assertEqual("unverified", result["search"])
            self.assertNotIn(SECRET, json.dumps(result))
            record["expires_at"] = (datetime.now(UTC) + timedelta(hours=1)).isoformat()
            path.write_text(json.dumps({"issuer::client": record}))
            self.assertEqual("present_unverified", accounts.x_access(path)["oauth"])
            self.assertEqual("missing", accounts.x_access(self.project / "missing")["oauth"])
            self.assertFalse(transport.called)

    def test_x_diagnostics_read_the_retained_clients_selected_default_model(self):
        root = self.project / ".grok"
        root.mkdir()
        config = root / "config.toml"
        config.write_text('[models]\ndefault = "retained-fixture-model"\n', encoding="utf-8")
        with patch.object(Path, "home", return_value=self.project), patch.object(accounts, "get_json") as transport:
            result = accounts.x_access()
            self.assertEqual("retained-fixture-model", result["model"])
            self.assertEqual("explicit-fixture-model", accounts.x_access(model="explicit-fixture-model")["model"])
            self.assertEqual("unverified", result["search"])
            self.assertFalse(result["model_tool_verified"])
            config.write_text('model = "legacy-fixture-model"\n[models]\ndefault = "other"\n', encoding="utf-8")
            self.assertEqual("legacy-fixture-model", accounts.x_access()["model"])
            self.assertFalse(transport.called)

    def test_catalog_inventory_remains_available_without_a_home_directory(self):
        with (
            patch.object(Path, "home", side_effect=RuntimeError("Could not determine home directory.")),
            patch.object(accounts, "get_json") as transport,
        ):
            inventory = providers.capabilities()
            self.assertFalse(inventory["x"]["configured"])
            self.assertEqual("invalid_private_auth_metadata", accounts.x_access()["oauth"])
            self.assertIn("europeana", inventory)
            self.assertFalse(transport.called)

    @skip_unless_ffmpeg
    def test_mapillary_actual_image_enters_review_and_duplicate_count_is_one(self):
        write_brief(self.project, ["mapillary"])
        image_rules(self.project)
        save_plan(self.project, "mapillary")
        image = self.project / "image.jpg"
        synth_image(image)
        records = [map_record("100"), map_record("200")]

        def transport(url, *args, **kwargs):
            return (
                {"data": records}
                if url.endswith("/images")
                else next(r for r in records if url.endswith("/" + r["id"]))
            )

        def download(url, target, **kwargs):
            target.write_bytes(image.read_bytes())

        with (
            patch.object(accounts, "get_json", side_effect=transport),
            patch.object(accounts, "download", side_effect=download),
        ):
            found = planned(self.project, "mapillary")
            relabeled = planned(self.project, "mapillary", query="new words for the same geographic box")
            self.assertTrue(relabeled["replayed"])
            for row in found["items"]:
                inspection = call(self.project, "inspect", "--candidate", row["id"])
                self.assertEqual(row["id"], inspection["candidate"])
                self.assertIsNone(inspection["duration_s"])
                self.assertEqual([], inspection["candidate_windows"])
                self.assertGreater(Ledger(self.project).get(row["id"])["media"]["width"], 0)
                call(self.project, "preview", "--candidate", row["id"])
                self.assertEqual(".jpg", Path(Ledger(self.project).get(row["id"])["local_path"]).suffix)
                confirm(
                    self.project,
                    row["id"],
                    "poster",
                    ("Synthetic street image", "Synthetic place-view fixture; not live evidence"),
                )
                with self.assertRaises(OperationError):
                    call(self.project, "fetch", "--candidate", row["id"])
            first = found["items"][0]["id"]
            call(
                self.project,
                "approve",
                "--candidate",
                first,
                "--by",
                "Fixture reviewer",
                "--statement",
                "Synthetic approval of this fixture image only",
            )
            with self.assertRaisesRegex(OperationError, "permit"):
                call(self.project, "fetch", "--candidate", first)
            call(self.project, "permit", "--candidate", first, "--evidence", "Synthetic fixture permission only")
            fetched = call(self.project, "fetch", "--candidate", first)
            self.assertEqual("verified", fetched["state"])
            self.assertEqual(".jpg", Path(fetched["output"]["path"]).suffix)
            self.assertEqual(image.read_bytes(), (self.project / "brolls" / fetched["output"]["path"]).read_bytes())
        self.assertEqual(1, progress_row(self.project)["suitable_count"])
        self.assertEqual(1, progress_row(self.project)["queries_used"])
        self.assertIn("Original scenario narration", storyboard(self.project))
        self.assertNotIn(SECRET, storyboard(self.project))

    @skip_unless_ffmpeg
    def test_telegram_video_preview_decode_and_cached_attachment_guard(self):
        write_brief(self.project, ["telegram"])
        save_plan(self.project, "telegram")
        source = self.project / "source.mp4"
        synth_video(source, duration=6)
        fake = FakeClient([message(30, photo=False)], source=source)
        with patch.object(accounts, "_client", return_value=fake):
            row = planned(self.project, "telegram", media="video")["items"][0]
            inspection = call(self.project, "inspect", "--candidate", row["id"])
            self.assertAlmostEqual(6, inspection["duration_s"], places=1)
            preview = call(self.project, "preview", "--candidate", row["id"], "--start", "0", "--end", "2")
            self.assertTrue(Path(preview["files"]["gif"]).is_file())
            confirm(
                self.project,
                row["id"],
                "gif",
                ("Synthetic laboratory video", "Synthetic fixture; not live editorial evidence"),
            )
            self.assertEqual(1, progress_row(self.project)["suitable_count"])
            self.assertIn("Original scenario narration", storyboard(self.project))
            with self.assertRaisesRegex(OperationError, "Aprovação humana ausente"):
                call(self.project, "fetch", "--candidate", row["id"])
            call(
                self.project,
                "approve",
                "--candidate",
                row["id"],
                "--by",
                "Fixture reviewer",
                "--statement",
                "Approve this synthetic Telegram fixture only",
            )
            with self.assertRaisesRegex(OperationError, "permit"):
                call(self.project, "fetch", "--candidate", row["id"])
            call(self.project, "permit", "--candidate", row["id"], "--evidence", "Synthetic fixture permission")
            fetched = call(self.project, "fetch", "--candidate", row["id"])
            self.assertTrue(fetched["output"]["verified"])
            fake.authorized = False
            with self.assertRaisesRegex(OperationError, "telegram-login"):
                call(self.project, "preview", "--candidate", row["id"], "--start", "0", "--end", "2")
            fake.authorized = True
            fake.messages = [message(30, photo=False, attachment=2000)]
            with self.assertRaisesRegex(OperationError, "identity"):
                call(self.project, "preview", "--candidate", row["id"], "--start", "0", "--end", "2")

    @skip_unless_ffmpeg
    def test_x_original_capture_enters_common_review_without_automated_discovery(self):
        write_brief(self.project, ["x"])
        save_plan(self.project, "x")
        url = "https://x.com/fixture_author/status/12345"
        locator = call(self.project, "resolve", "--url", url, "--shot", "opening")
        self.assertFalse(locator["catalog"]["quote_verified"])
        with self.assertRaises(OperationError):
            planned(self.project, "x", media="video", filters=[])
        self.assertEqual(0, progress_row(self.project)["queries_used"])
        with self.assertRaisesRegex(OperationError, "unverified"):
            call(self.project, "inspect", "--candidate", locator["id"])
        image = self.project / "post.jpg"
        synth_image(image)
        capture = call(
            self.project,
            "resolve",
            "--file",
            str(image),
            "--asset-type",
            "web_screenshot",
            "--source-url",
            url,
            "--original-for",
            locator["id"],
            "--original-conditions",
            "Synthetic original-post capture, not a live post or styled quotation",
        )
        call(self.project, "preview", "--candidate", capture["id"])
        confirm(
            self.project,
            capture["id"],
            "poster",
            ("Synthetic original-post capture", "Synthetic visible material; no invented quote"),
        )
        self.assertEqual(1, progress_row(self.project)["suitable_count"])
        self.assertEqual("pending", Ledger(self.project).get(capture["id"])["approval"]["status"])


if __name__ == "__main__":
    unittest.main()
