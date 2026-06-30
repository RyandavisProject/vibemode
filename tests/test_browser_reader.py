import unittest
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

from neurogate_usage_overlay.browser_reader import (
    AUTO_LOGIN_DELAY_ATTEMPTS,
    BODY_TEXT_TIMEOUT_MS,
    CACHE_SIZE_BYTES,
    LOGIN_PROMPT_CONFIRM_ATTEMPTS,
    USAGE_URL,
    BrowserSettings,
    NeurogateUsageReader,
    _format_plan_days_left,
    _snapshot_from_vibemode_api,
    _snapshot_from_vibemode_text,
)
from neurogate_usage_overlay.models import UsageSnapshot, UsageWindow


class BrowserReaderModeTest(unittest.TestCase):
    def test_default_usage_url_points_to_vibemode_dashboard(self):
        self.assertEqual(USAGE_URL, "https://portal.vibemod.pro/client")

    def test_format_plan_days_left_uses_ceiling_days(self):
        now = datetime(2026, 6, 25, 6, 0, tzinfo=timezone.utc)

        self.assertEqual(_format_plan_days_left("2026-06-26T07:00:00+00:00", now=now), "2 дн осталось")

    def test_snapshot_from_vibemode_api_converts_used_to_remaining(self):
        snapshot = _snapshot_from_vibemode_api(
            {
                "currentPlanCode": "ascend",
                "plan": {
                    "name": "Ascend",
                    "endsAt": "2026-07-12T13:15:55.09452+00:00",
                },
            },
            {
                "rows": [
                    {
                        "scope": "default",
                        "creditLimit5Hours": 120_000_000,
                        "creditLimit7Days": 600_000_000,
                        "credits5Hours": 4_695_705,
                        "credits7Days": 336_558_605,
                    },
                    {
                        "scope": "anthropic_compatible",
                        "creditLimit5Hours": 0,
                        "creditLimit7Days": 0,
                        "credits5Hours": 0,
                        "credits7Days": 0,
                    },
                ],
            },
            source_url="https://portal.vibemod.pro/client",
            raw_text="""
            КВОТА
            5-ЧАСОВОЕ ОКНО
            7% ИСПОЛЬЗОВАНО
            Сброс через 3ч 4м
            КВОТА
            7-ДНЕВНОЕ ОКНО
            68% ИСПОЛЬЗОВАНО
            Сброс через 20ч 7м
            """,
        )

        self.assertIsNotNone(snapshot)
        assert snapshot is not None
        self.assertEqual(snapshot.account, "Ascend")
        self.assertEqual(len(snapshot.windows), 2)
        self.assertEqual(snapshot.windows[0].title, "5 часов")
        self.assertEqual(snapshot.windows[0].limit_used, 4_695_705)
        self.assertEqual(snapshot.windows[0].limit_total, 120_000_000)
        self.assertEqual(snapshot.windows[0].credits_remaining, 115_304_295)
        self.assertEqual(snapshot.windows[0].reset_text, "3ч 4м")
        self.assertAlmostEqual(snapshot.windows[0].progress_percent or 0, 3.91, places=2)
        self.assertEqual(snapshot.windows[1].title, "7 дней")
        self.assertEqual(snapshot.windows[1].credits_remaining, 263_441_395)
        self.assertEqual(snapshot.windows[1].reset_text, "20ч 7м")
        self.assertAlmostEqual(snapshot.windows[1].progress_percent or 0, 56.09, places=2)

    def test_snapshot_from_vibemode_api_uses_profile_window_reset_timestamps(self):
        now = datetime(2026, 6, 30, 8, 0, tzinfo=timezone.utc)

        snapshot = _snapshot_from_vibemode_api(
            {
                "currentPlanCode": "ascend",
                "currentPlanEndsAt": "2026-07-12T13:15:55.09452+00:00",
                "usage": {
                    "rows": [
                        {
                            "scope": "default",
                            "window5HoursEndsAt": "2026-06-30T12:17:44.230927+00:00",
                            "window7DaysEndsAt": "2026-07-03T18:26:52.081267+00:00",
                        }
                    ]
                },
            },
            {
                "rows": [
                    {
                        "scope": "default",
                        "creditLimit5Hours": 120_000_000,
                        "creditLimit7Days": 600_000_000,
                        "credits5Hours": 12_387_470,
                        "credits7Days": 257_271_919,
                    }
                ],
            },
            source_url="https://portal.vibemod.pro/client",
            now=now,
        )

        self.assertIsNotNone(snapshot)
        assert snapshot is not None
        self.assertEqual(snapshot.account, "Ascend")
        self.assertEqual(snapshot.windows[0].credits_remaining, 107_612_530)
        self.assertEqual(snapshot.windows[0].reset_text, "4ч 18м")
        self.assertEqual(snapshot.windows[1].credits_remaining, 342_728_081)
        self.assertEqual(snapshot.windows[1].reset_text, "3д 10ч")

    def test_snapshot_from_vibemode_api_accepts_snake_case_reset_timestamps(self):
        now = datetime(2026, 6, 30, 8, 0, tzinfo=timezone.utc)

        snapshot = _snapshot_from_vibemode_api(
            {
                "usage": {
                    "rows": [
                        {
                            "scope": "default",
                            "window_5_hours_ends_at": "2026-06-30T09:05:00+00:00",
                            "window_7_days_ends_at": "2026-07-01T20:00:00+00:00",
                        }
                    ]
                },
            },
            {
                "rows": [
                    {
                        "scope": "default",
                        "creditLimit5Hours": 120_000_000,
                        "creditLimit7Days": 600_000_000,
                        "credits5Hours": 1,
                        "credits7Days": 2,
                    }
                ],
            },
            source_url="https://portal.vibemod.pro/client",
            now=now,
        )

        self.assertIsNotNone(snapshot)
        assert snapshot is not None
        self.assertEqual(snapshot.windows[0].reset_text, "1ч 5м")
        self.assertEqual(snapshot.windows[1].reset_text, "1д 12ч")

    def test_snapshot_from_vibemode_dashboard_text_converts_used_to_remaining(self):
        snapshot = _snapshot_from_vibemode_text(
            """
            ПЛАН
            Ascend
            18 ДН ОСТАЛОСЬ
            КВОТА
            5-ЧАСОВОЕ ОКНО
            11%
            13.52M
            из 120.00M
            11% ИСПОЛЬЗОВАНО
            Сброс через 3ч 4м
            КВОТА
            7-ДНЕВНОЕ ОКНО
            58%
            345.39M
            из 600.00M
            58% ИСПОЛЬЗОВАНО
            Сброс через 20ч 7м
            CLAUDE
            5-ЧАСОВОЕ ОКНО
            —
            —
            Нет в текущем тарифе
            """,
            source_url="https://portal.vibemod.pro/client",
        )

        self.assertIsNotNone(snapshot)
        assert snapshot is not None
        self.assertEqual(snapshot.account, "Ascend")
        self.assertEqual(snapshot.plan_status, "18 дн осталось")
        self.assertEqual(snapshot.windows[0].credits_remaining, 106_480_000)
        self.assertEqual(snapshot.windows[0].limit_used, 13_520_000)
        self.assertEqual(snapshot.windows[0].limit_total, 120_000_000)
        self.assertEqual(snapshot.windows[0].reset_text, "3ч 4м")
        self.assertAlmostEqual(snapshot.windows[0].progress_percent or 0, 11.27, places=2)
        self.assertEqual(snapshot.windows[1].credits_remaining, 254_610_000)
        self.assertEqual(snapshot.windows[1].limit_used, 345_390_000)
        self.assertEqual(snapshot.windows[1].limit_total, 600_000_000)
        self.assertEqual(snapshot.windows[1].reset_text, "20ч 7м")
        self.assertAlmostEqual(snapshot.windows[1].progress_percent or 0, 57.565, places=3)

    def test_keep_browser_open_updates_settings_before_start(self):
        reader = NeurogateUsageReader(BrowserSettings())

        reader.set_keep_browser_open(True)

        self.assertTrue(reader.keep_browser_open)
        self.assertFalse(reader.settings.hide_after_successful_login)
        self.assertTrue(reader.settings.show_browser_on_login)

        reader.set_keep_browser_open(False)

        self.assertFalse(reader.keep_browser_open)
        self.assertTrue(reader.settings.hide_after_successful_login)
        self.assertFalse(reader.settings.show_browser_on_login)

    def test_keep_browser_open_switches_running_context(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            reader = NeurogateUsageReader(BrowserSettings(headless=True, profile_dir=Path(tmpdir)))
            launches: list[bool] = []
            hides = 0
            reader._playwright = object()
            reader._current_headless = True

            def fake_launch_context(*, headless: bool) -> None:
                launches.append(headless)
                reader._current_headless = headless

            def fake_hide_current_browser_window() -> int:
                nonlocal hides
                hides += 1
                reader._current_headless = None
                return 1

            reader._launch_context = fake_launch_context  # type: ignore[method-assign]
            reader._hide_current_browser_window = fake_hide_current_browser_window  # type: ignore[method-assign]

            reader.set_keep_browser_open(True)
            reader.set_keep_browser_open(False)

            self.assertEqual(launches, [False])
            self.assertEqual(hides, 1)

    def test_visible_login_prompt_is_marked_as_opened(self):
        reader = NeurogateUsageReader(BrowserSettings(headless=True))
        launches: list[bool] = []

        def fake_launch_context(*, headless: bool) -> None:
            launches.append(headless)
            reader._current_headless = headless

        reader._launch_context = fake_launch_context  # type: ignore[method-assign]
        reader._write_debug = lambda *_args, **_kwargs: None  # type: ignore[method-assign]

        reader._open_visible_login_window()

        self.assertTrue(reader._login_prompt_opened)
        self.assertTrue(reader._login_visible)
        self.assertEqual(launches, [False])

    def test_hidden_mode_uses_offscreen_headed_browser_args(self):
        reader = NeurogateUsageReader(BrowserSettings(headless=True))

        args = reader._browser_args(hidden=True)

        self.assertIn("--window-position=-32000,-32000", args)
        self.assertIn("--window-size=1440,950", args)
        self.assertIn(f"--disk-cache-size={CACHE_SIZE_BYTES}", args)
        self.assertIn(f"--media-cache-size={CACHE_SIZE_BYTES}", args)

    def test_visible_mode_uses_reachable_window_args(self):
        reader = NeurogateUsageReader(BrowserSettings(headless=False))

        args = reader._browser_args(hidden=False)

        self.assertIn("--window-position=96,80", args)
        self.assertIn("--window-size=1180,860", args)

    def test_profile_cache_cleanup_keeps_session_storage(self):
        with tempfile.TemporaryDirectory() as directory:
            profile_dir = Path(directory) / "browser-profile"
            cache_file = profile_dir / "Default" / "Cache" / "Cache_Data" / "file"
            code_cache_file = profile_dir / "Default" / "Code Cache" / "js" / "file"
            local_storage_file = profile_dir / "Default" / "Local Storage" / "leveldb" / "session"
            session_storage_file = profile_dir / "Default" / "Session Storage" / "session"
            cookie_file = profile_dir / "Default" / "Cookies"
            for path in (cache_file, code_cache_file, local_storage_file, session_storage_file, cookie_file):
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text("data", encoding="utf-8")

            reader = NeurogateUsageReader(BrowserSettings(profile_dir=profile_dir))
            reader._write_debug = lambda *_args, **_kwargs: None  # type: ignore[method-assign]

            reader._prune_browser_caches()

            self.assertFalse((profile_dir / "Default" / "Cache").exists())
            self.assertFalse((profile_dir / "Default" / "Code Cache").exists())
            self.assertTrue(local_storage_file.exists())
            self.assertTrue(session_storage_file.exists())
            self.assertTrue(cookie_file.exists())

    def test_debug_log_does_not_store_raw_portal_text(self):
        with tempfile.TemporaryDirectory() as directory:
            debug_log = Path(directory) / "debug.log"
            reader = NeurogateUsageReader(BrowserSettings(debug_log=debug_log))
            snapshot = UsageSnapshot(
                updated_at=datetime.now(),
                account="ascend",
                raw_text="SECRET PORTAL TEXT WITH EMAIL user@example.com",
            )

            reader._write_debug(snapshot, note="test")

            content = debug_log.read_text(encoding="utf-8")
            self.assertIn("text_len=", content)
            self.assertNotIn("SECRET PORTAL TEXT", content)
            self.assertNotIn("user@example.com", content)

    def test_hidden_taskbar_hider_uses_profile_browser_pids(self):
        reader = NeurogateUsageReader(BrowserSettings())
        reader._profile_browser_process_ids_windows = lambda: {123, 456}  # type: ignore[method-assign]

        with (
            patch("neurogate_usage_overlay.browser_reader.sys.platform", "win32"),
            patch("neurogate_usage_overlay.browser_reader._hide_windows_for_pids", return_value=2) as hide,
        ):
            hidden_count = reader._hide_hidden_browser_taskbar_windows()

        hide.assert_called_once_with({123, 456})
        self.assertEqual(hidden_count, 2)

    def test_login_state_returns_fresh_status_without_cache(self):
        reader = NeurogateUsageReader(BrowserSettings(headless=True))
        reader._page = type("Page", (), {"url": reader.settings.usage_url})()
        reader._current_headless = True
        reader._wait_for_usage_text = lambda: "EMAIL\nПАРОЛЬ\nВойти"  # type: ignore[method-assign]
        reader._open_visible_login_window = lambda: None  # type: ignore[method-assign]
        reader._write_debug = lambda *_args, **_kwargs: None  # type: ignore[method-assign]

        snapshot = reader.read()

        self.assertFalse(snapshot.has_data)
        self.assertFalse(snapshot.is_cached)
        self.assertEqual(snapshot.status_note, "нужен вход")

    def test_hidden_login_state_reopens_visible_prompt_after_previous_login(self):
        reader = NeurogateUsageReader(BrowserSettings(headless=True))
        reader._page = type("Page", (), {"url": reader.settings.usage_url})()
        reader._current_headless = True
        reader._login_prompt_opened = True
        reader._login_visible = False
        opens = 0

        def open_visible_login_window() -> None:
            nonlocal opens
            opens += 1
            reader._current_headless = False
            reader._login_visible = True
            reader._login_prompt_opened = True

        reader._wait_for_usage_text = lambda: "EMAIL\nПАРОЛЬ\nВойти"  # type: ignore[method-assign]
        reader._open_visible_login_window = open_visible_login_window  # type: ignore[method-assign]
        reader._attach_window_progress = lambda _snapshot: None  # type: ignore[method-assign]
        reader._write_debug = lambda *_args, **_kwargs: None  # type: ignore[method-assign]

        snapshot = reader.read()

        self.assertEqual(opens, 1)
        self.assertTrue(reader._login_visible)
        self.assertEqual(snapshot.status_note, "нужен вход")

    def test_hidden_invalid_session_opens_visible_login_even_with_stale_cards(self):
        reader = NeurogateUsageReader(BrowserSettings(headless=True))
        reader._page = type("Page", (), {"url": reader.settings.usage_url})()
        reader._current_headless = True
        opens = 0
        stale_text = """
            КАБИНЕТ КЛИЕНТА
            Лимиты
            Подробная информация о Вашем тарифе
            Сессия больше недействительна.
            ascend
            активен ещё 28 д 8 ч
            5 часов
            117 888 444
            Кредитов осталось
            7 дней
            421 381 328
            Кредитов осталось
        """
        texts = [stale_text, stale_text]

        def open_visible_login_window() -> None:
            nonlocal opens
            opens += 1
            reader._current_headless = False
            reader._login_visible = True

        reader._wait_for_usage_text = lambda: texts.pop(0) if texts else stale_text  # type: ignore[method-assign]
        reader._open_visible_login_window = open_visible_login_window  # type: ignore[method-assign]
        reader._maybe_auto_submit_login = lambda: False  # type: ignore[method-assign]
        reader._attach_window_progress = lambda _snapshot: None  # type: ignore[method-assign]
        reader._expand_usage_card = lambda force=False: None  # type: ignore[method-assign]
        reader._write_debug = lambda *_args, **_kwargs: None  # type: ignore[method-assign]

        snapshot = reader.read()

        self.assertEqual(opens, 1)
        self.assertFalse(snapshot.has_data)
        self.assertEqual(snapshot.status_note, "нужен вход")

    def test_hidden_login_after_sleep_recovers_context_before_visible_prompt(self):
        reader = NeurogateUsageReader(BrowserSettings(headless=True))
        reader._playwright = object()
        reader._page = type("Page", (), {"url": reader.settings.usage_url})()
        reader._current_headless = True
        texts = iter(["EMAIL\nPASSWORD\nlogin", "dashboard"])
        launches: list[bool] = []
        opened_visible: list[bool] = []
        debug_notes: list[str] = []

        def launch_context(*, headless: bool) -> None:
            launches.append(headless)
            reader._current_headless = headless
            reader._page = type("Page", (), {"url": reader.settings.usage_url})()

        def api_snapshot(text: str) -> UsageSnapshot | None:
            if text != "dashboard":
                return None
            return UsageSnapshot(
                updated_at=datetime.now(),
                windows=[UsageWindow(title="5 часов", credits_remaining=102_000_000)],
            )

        reader._wait_for_usage_text = lambda: next(texts)  # type: ignore[method-assign]
        reader._launch_context = launch_context  # type: ignore[method-assign]
        reader._read_vibemode_api_snapshot = api_snapshot  # type: ignore[method-assign]
        reader._open_visible_login_window = lambda: opened_visible.append(True)  # type: ignore[method-assign]
        reader._hide_visible_browser_after_success = lambda: None  # type: ignore[method-assign]
        reader._write_debug = lambda _snapshot, note="": debug_notes.append(note)  # type: ignore[method-assign]

        snapshot = reader.read()

        self.assertTrue(snapshot.has_data)
        self.assertEqual(launches, [True])
        self.assertEqual(opened_visible, [])
        self.assertTrue(any("hidden_session_recovery_start" in note for note in debug_notes))
        self.assertTrue(any("outcome=recovered" in note for note in debug_notes))

    def test_hidden_missing_api_token_after_sleep_recovers_context_before_login_prompt(self):
        reader = NeurogateUsageReader(BrowserSettings(headless=True))
        reader._playwright = object()
        reader._page = type("Page", (), {"url": reader.settings.usage_url})()
        reader._current_headless = True
        texts = iter(["dashboard shell", "dashboard recovered"])
        launches: list[bool] = []
        opened_visible: list[bool] = []

        def launch_context(*, headless: bool) -> None:
            launches.append(headless)
            reader._current_headless = headless
            reader._page = type("Page", (), {"url": reader.settings.usage_url})()

        def api_snapshot(text: str) -> UsageSnapshot | None:
            if text == "dashboard shell":
                reader._last_vibemode_api_failure_reason = "missing_token"
                return None
            return UsageSnapshot(
                updated_at=datetime.now(),
                windows=[UsageWindow(title="5 С‡Р°СЃРѕРІ", credits_remaining=102_000_000)],
            )

        reader._wait_for_usage_text = lambda: next(texts)  # type: ignore[method-assign]
        reader._launch_context = launch_context  # type: ignore[method-assign]
        reader._read_vibemode_api_snapshot = api_snapshot  # type: ignore[method-assign]
        reader._open_visible_login_window = lambda: opened_visible.append(True)  # type: ignore[method-assign]
        reader._hide_visible_browser_after_success = lambda: None  # type: ignore[method-assign]
        reader._write_debug = lambda *_args, **_kwargs: None  # type: ignore[method-assign]

        snapshot = reader.read()

        self.assertTrue(snapshot.has_data)
        self.assertEqual(launches, [True])
        self.assertEqual(opened_visible, [])

    def test_hidden_stale_cabinet_after_sleep_recovers_without_login_status(self):
        reader = NeurogateUsageReader(BrowserSettings(headless=True))
        reader._playwright = object()
        reader._page = type("Page", (), {"url": reader.settings.usage_url})()
        reader._current_headless = True
        texts = iter(["could not load cabinet data.", "dashboard"])
        launches: list[bool] = []
        opened_visible: list[bool] = []

        def launch_context(*, headless: bool) -> None:
            launches.append(headless)
            reader._current_headless = headless
            reader._page = type("Page", (), {"url": reader.settings.usage_url})()

        reader._wait_for_usage_text = lambda: next(texts)  # type: ignore[method-assign]
        reader._launch_context = launch_context  # type: ignore[method-assign]
        reader._read_vibemode_api_snapshot = lambda text: UsageSnapshot(  # type: ignore[method-assign]
            updated_at=datetime.now(),
            windows=[UsageWindow(title="5h", credits_remaining=1)],
        ) if text == "dashboard" else None
        reader._open_visible_login_window = lambda: opened_visible.append(True)  # type: ignore[method-assign]
        reader._hide_visible_browser_after_success = lambda: None  # type: ignore[method-assign]
        reader._write_debug = lambda *_args, **_kwargs: None  # type: ignore[method-assign]

        snapshot = reader.read()

        self.assertTrue(snapshot.has_data)
        self.assertIsNone(snapshot.status_note)
        self.assertEqual(launches, [True])
        self.assertEqual(opened_visible, [])

    def test_hidden_invalid_session_after_sleep_recovers_without_login_status(self):
        reader = NeurogateUsageReader(BrowserSettings(headless=True))
        reader._playwright = object()
        reader._page = type("Page", (), {"url": reader.settings.usage_url})()
        reader._current_headless = True
        texts = iter(["session expired", "dashboard"])
        launches: list[bool] = []
        opened_visible: list[bool] = []

        def launch_context(*, headless: bool) -> None:
            launches.append(headless)
            reader._current_headless = headless
            reader._page = type("Page", (), {"url": reader.settings.usage_url})()

        reader._wait_for_usage_text = lambda: next(texts)  # type: ignore[method-assign]
        reader._launch_context = launch_context  # type: ignore[method-assign]
        reader._read_vibemode_api_snapshot = lambda text: UsageSnapshot(  # type: ignore[method-assign]
            updated_at=datetime.now(),
            windows=[UsageWindow(title="5h", credits_remaining=1)],
        ) if text == "dashboard" else None
        reader._open_visible_login_window = lambda: opened_visible.append(True)  # type: ignore[method-assign]
        reader._hide_visible_browser_after_success = lambda: None  # type: ignore[method-assign]
        reader._write_debug = lambda *_args, **_kwargs: None  # type: ignore[method-assign]

        snapshot = reader.read()

        self.assertTrue(snapshot.has_data)
        self.assertIsNone(snapshot.status_note)
        self.assertEqual(launches, [True])
        self.assertEqual(opened_visible, [])

    def test_failed_hidden_session_recovery_opens_visible_login_once(self):
        reader = NeurogateUsageReader(BrowserSettings(headless=True))
        reader._playwright = object()
        reader._page = type("Page", (), {"url": reader.settings.usage_url})()
        reader._current_headless = True
        texts = iter([
            "EMAIL\nPASSWORD\nlogin",
            "EMAIL\nPASSWORD\nlogin",
            "EMAIL\nPASSWORD\nlogin",
        ])
        launches: list[bool] = []
        opened_visible: list[bool] = []

        def launch_context(*, headless: bool) -> None:
            launches.append(headless)
            reader._current_headless = headless
            reader._page = type("Page", (), {"url": reader.settings.usage_url})()

        def open_visible_login_window() -> None:
            opened_visible.append(True)
            launch_context(headless=False)
            reader._login_visible = True

        reader._wait_for_usage_text = lambda: next(texts)  # type: ignore[method-assign]
        reader._launch_context = launch_context  # type: ignore[method-assign]
        reader._open_visible_login_window = open_visible_login_window  # type: ignore[method-assign]
        reader._maybe_auto_submit_login = lambda: False  # type: ignore[method-assign]
        reader._write_debug = lambda *_args, **_kwargs: None  # type: ignore[method-assign]

        snapshot = reader.read()

        self.assertFalse(snapshot.has_data)
        self.assertEqual(snapshot.status_note, reader._fallback_status(snapshot.raw_text))
        self.assertEqual(launches, [True, False])
        self.assertEqual(opened_visible, [True])

    def test_hidden_session_recovery_cooldown_prevents_reopen_loop(self):
        reader = NeurogateUsageReader(BrowserSettings(headless=True))
        reader._playwright = object()
        reader._page = type("Page", (), {"url": reader.settings.usage_url})()
        reader._current_headless = True
        reader._last_hidden_session_recovery_at = time.monotonic()
        launches: list[bool] = []
        opened_visible: list[bool] = []

        def open_visible_login_window() -> None:
            opened_visible.append(True)
            reader._current_headless = False
            reader._login_visible = True

        reader._wait_for_usage_text = lambda: "EMAIL\nPASSWORD\nlogin"  # type: ignore[method-assign]
        reader._launch_context = lambda *, headless: launches.append(headless)  # type: ignore[method-assign]
        reader._open_visible_login_window = open_visible_login_window  # type: ignore[method-assign]
        reader._maybe_auto_submit_login = lambda: False  # type: ignore[method-assign]
        reader._write_debug = lambda *_args, **_kwargs: None  # type: ignore[method-assign]

        snapshot = reader.read()

        self.assertFalse(snapshot.has_data)
        self.assertEqual(launches, [])
        self.assertEqual(opened_visible, [True])

    def test_force_hidden_session_recovery_bypasses_cooldown(self):
        reader = NeurogateUsageReader(BrowserSettings(headless=True))
        reader._playwright = object()
        reader._page = type("Page", (), {"url": reader.settings.usage_url})()
        reader._current_headless = True
        reader._last_hidden_session_recovery_at = time.monotonic()
        texts = iter(["EMAIL\nPASSWORD\nlogin", "dashboard"])
        launches: list[bool] = []
        opened_visible: list[bool] = []

        def launch_context(*, headless: bool) -> None:
            launches.append(headless)
            reader._current_headless = headless
            reader._page = type("Page", (), {"url": reader.settings.usage_url})()

        reader._wait_for_usage_text = lambda: next(texts)  # type: ignore[method-assign]
        reader._launch_context = launch_context  # type: ignore[method-assign]
        reader._read_vibemode_api_snapshot = lambda text: UsageSnapshot(  # type: ignore[method-assign]
            updated_at=datetime.now(),
            windows=[UsageWindow(title="5 часов", credits_remaining=1)],
        ) if text == "dashboard" else None
        reader._open_visible_login_window = lambda: opened_visible.append(True)  # type: ignore[method-assign]
        reader._hide_visible_browser_after_success = lambda: None  # type: ignore[method-assign]
        reader._write_debug = lambda *_args, **_kwargs: None  # type: ignore[method-assign]

        snapshot = reader.read(force_session_recovery=True)

        self.assertTrue(snapshot.has_data)
        self.assertEqual(launches, [True])
        self.assertEqual(opened_visible, [])

    def test_visible_login_stuck_state_can_recover_hidden_session(self):
        reader = NeurogateUsageReader(BrowserSettings(headless=True))
        reader._playwright = object()
        reader._page = type("Page", (), {"url": reader.settings.usage_url})()
        reader._current_headless = False
        reader._login_visible = True
        texts = iter(["EMAIL\nPASSWORD\nlogin", "dashboard"])
        launches: list[bool] = []

        def launch_context(*, headless: bool) -> None:
            launches.append(headless)
            reader._current_headless = headless
            reader._login_visible = False
            reader._page = type("Page", (), {"url": reader.settings.usage_url})()

        reader._wait_for_usage_text = lambda: next(texts)  # type: ignore[method-assign]
        reader._launch_context = launch_context  # type: ignore[method-assign]
        reader._read_vibemode_api_snapshot = lambda text: UsageSnapshot(  # type: ignore[method-assign]
            updated_at=datetime.now(),
            windows=[UsageWindow(title="5 часов", credits_remaining=1)],
        ) if text == "dashboard" else None
        reader._hide_visible_browser_after_success = lambda: None  # type: ignore[method-assign]
        reader._write_debug = lambda *_args, **_kwargs: None  # type: ignore[method-assign]

        snapshot = reader.read()

        self.assertTrue(snapshot.has_data)
        self.assertEqual(launches, [True])
        self.assertFalse(reader._login_visible)

    def test_hidden_session_recovery_does_not_delete_profile_state_or_history(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            profile_dir = root / "browser-profile"
            profile_file = profile_dir / "Default" / "Local Storage" / "leveldb" / "session"
            state_file = root / "overlay-state.json"
            history_file = root / "usage-daily.json"
            profile_file.parent.mkdir(parents=True)
            profile_file.write_text("local session", encoding="utf-8")
            state_file.write_text("{}", encoding="utf-8")
            history_file.write_text("{}", encoding="utf-8")

            reader = NeurogateUsageReader(BrowserSettings(headless=True, profile_dir=profile_dir))
            reader._playwright = object()
            reader._page = type("Page", (), {"url": reader.settings.usage_url})()
            reader._current_headless = True
            texts = iter(["EMAIL\nPASSWORD\nlogin", "dashboard"])

            reader._wait_for_usage_text = lambda: next(texts)  # type: ignore[method-assign]
            reader._launch_context = lambda *, headless: setattr(reader, "_current_headless", headless)  # type: ignore[method-assign]
            reader._read_vibemode_api_snapshot = lambda text: UsageSnapshot(  # type: ignore[method-assign]
                updated_at=datetime.now(),
                windows=[UsageWindow(title="5 часов", credits_remaining=1)],
            ) if text == "dashboard" else None
            reader._hide_visible_browser_after_success = lambda: None  # type: ignore[method-assign]
            reader._write_debug = lambda *_args, **_kwargs: None  # type: ignore[method-assign]

            snapshot = reader.read()

            self.assertTrue(snapshot.has_data)
            self.assertTrue(profile_file.exists())
            self.assertTrue(state_file.exists())
            self.assertTrue(history_file.exists())

    def test_successful_read_allows_future_login_prompt(self):
        reader = NeurogateUsageReader(BrowserSettings(headless=True))
        reader._page = type("Page", (), {"url": reader.settings.usage_url})()
        reader._current_headless = False
        reader._login_prompt_opened = True
        reader._login_visible = True
        reader._wait_for_usage_text = lambda: """
            КАБИНЕТ КЛИЕНТА
            Лимиты
            Подробная информация о Вашем тарифе
            ascend
            активен ещё 2 д 2 ч
            5 часов
            Сброс через 4 ч 58 мин
            119 300 000
            Кредитов осталось
            7 дней
            Сброс через 1 д 3 ч
            289 100 000
            Кредитов осталось
        """  # type: ignore[method-assign]
        reader._attach_window_progress = lambda _snapshot: None  # type: ignore[method-assign]
        reader._hide_visible_browser_after_success = lambda: None  # type: ignore[method-assign]
        reader._write_debug = lambda *_args, **_kwargs: None  # type: ignore[method-assign]

        snapshot = reader.read()

        self.assertTrue(snapshot.has_data)
        self.assertFalse(reader._login_prompt_opened)
        self.assertFalse(reader._login_visible)

    def test_successful_read_clears_account_switch_pending(self):
        reader = NeurogateUsageReader(BrowserSettings(headless=True))
        reader._page = type("Page", (), {"url": reader.settings.usage_url})()
        reader._current_headless = False
        reader._account_switch_pending = True
        reader._wait_for_usage_text = lambda: """
            КАБИНЕТ КЛИЕНТА
            Лимиты
            ascend
            5 часов
            119 300 000
            Кредитов осталось
            7 дней
            289 100 000
            Кредитов осталось
        """  # type: ignore[method-assign]
        reader._attach_window_progress = lambda _snapshot: None  # type: ignore[method-assign]
        reader._hide_visible_browser_after_success = lambda: None  # type: ignore[method-assign]
        reader._write_debug = lambda *_args, **_kwargs: None  # type: ignore[method-assign]

        snapshot = reader.read()

        self.assertTrue(snapshot.has_data)
        self.assertFalse(reader._account_switch_pending)

    def test_transient_login_page_does_not_open_visible_prompt(self):
        reader = NeurogateUsageReader(BrowserSettings(headless=True))
        reader._current_headless = True
        opens = 0
        texts = [
            "EMAIL\nПАРОЛЬ\nВойти",
            "EMAIL\nПАРОЛЬ\nВойти",
            """
                КАБИНЕТ КЛИЕНТА
                Лимиты
                ascend
                5 часов
                119 300 000
                Кредитов осталось
                7 дней
                289 100 000
                Кредитов осталось
            """,
        ]

        class Locator:
            def inner_text(self, timeout: int) -> str:
                return texts.pop(0)

        class Page:
            url = reader.settings.usage_url

            def wait_for_timeout(self, _timeout: int) -> None:
                return None

            def locator(self, _selector: str) -> Locator:
                return Locator()

        reader._page = Page()
        reader._open_visible_login_window = lambda: nonlocal_open()  # type: ignore[method-assign]
        reader._attach_window_progress = lambda _snapshot: None  # type: ignore[method-assign]
        reader._write_debug = lambda *_args, **_kwargs: None  # type: ignore[method-assign]

        def nonlocal_open() -> None:
            nonlocal opens
            opens += 1

        snapshot = reader.read()

        self.assertTrue(snapshot.has_data)
        self.assertEqual(opens, 0)

    def test_wait_for_usage_text_returns_login_prompt_quickly(self):
        reader = NeurogateUsageReader(BrowserSettings(headless=True))
        attempts = 0

        class Locator:
            def inner_text(self, timeout: int) -> str:
                nonlocal attempts
                attempts += 1
                return "EMAIL\nПАРОЛЬ\nВойти"

        class Page:
            def wait_for_timeout(self, _timeout: int) -> None:
                return None

            def locator(self, _selector: str) -> Locator:
                return Locator()

        reader._page = Page()

        text = reader._wait_for_usage_text()

        self.assertIn("EMAIL", text)
        self.assertEqual(attempts, LOGIN_PROMPT_CONFIRM_ATTEMPTS)

    def test_wait_for_usage_text_returns_vibemode_dashboard_quickly(self):
        reader = NeurogateUsageReader(BrowserSettings(headless=True))
        attempts = 0

        class Locator:
            def inner_text(self, timeout: int) -> str:
                nonlocal attempts
                attempts += 1
                return "Квота\n5-часовое окно\nКвота\n7-дневное окно"

        class Page:
            def wait_for_timeout(self, _timeout: int) -> None:
                return None

            def locator(self, _selector: str) -> Locator:
                return Locator()

        reader._page = Page()

        text = reader._wait_for_usage_text()

        self.assertIn("5-часовое окно", text)
        self.assertEqual(attempts, 1)

    def test_wait_for_usage_text_uses_short_body_timeout(self):
        reader = NeurogateUsageReader(BrowserSettings(headless=True, timeout_ms=45_000))
        seen_timeouts: list[int] = []

        class Locator:
            def inner_text(self, timeout: int) -> str:
                seen_timeouts.append(timeout)
                return "Квота\n5-часовое окно\nКвота\n7-дневное окно"

        class Page:
            def wait_for_timeout(self, _timeout: int) -> None:
                return None

            def locator(self, _selector: str) -> Locator:
                return Locator()

        reader._page = Page()

        reader._wait_for_usage_text()

        self.assertEqual(seen_timeouts, [BODY_TEXT_TIMEOUT_MS])

    def test_successful_visible_login_hides_current_window(self):
        reader = NeurogateUsageReader(BrowserSettings(headless=True))
        reader._current_headless = False
        hides = 0

        def fake_hide_current_browser_window() -> int:
            nonlocal hides
            hides += 1
            reader._current_headless = True
            return 1

        reader._hide_current_browser_window = fake_hide_current_browser_window  # type: ignore[method-assign]
        reader._write_debug = lambda *_args, **_kwargs: None  # type: ignore[method-assign]

        reader._hide_visible_browser_after_success()

        self.assertEqual(hides, 1)
        self.assertTrue(reader._current_headless)

    def test_refresh_uses_portal_refresh_when_usage_data_is_loaded(self):
        reader = NeurogateUsageReader(BrowserSettings(headless=True))
        reader._login_visible = False
        reader._current_headless = True
        reloads = 0
        portal_refreshes = 0

        class Locator:
            def inner_text(self, timeout: int) -> str:
                return """
                    КАБИНЕТ КЛИЕНТА
                    Лимиты
                    ascend
                    5 часов
                    119 300 000
                    Кредитов осталось
                    7 дней
                    289 100 000
                    Кредитов осталось
                """

        class Page:
            url = reader.settings.usage_url

            def locator(self, _selector: str) -> Locator:
                return Locator()

            def reload(self, wait_until: str) -> None:
                nonlocal reloads
                reloads += 1

        def fake_click_portal_refresh() -> None:
            nonlocal portal_refreshes
            portal_refreshes += 1

        reader._page = Page()
        reader._click_portal_refresh = fake_click_portal_refresh  # type: ignore[method-assign]
        reader.read = lambda: UsageSnapshot(updated_at=datetime.now())  # type: ignore[method-assign]

        reader.refresh()

        self.assertEqual(portal_refreshes, 1)
        self.assertEqual(reloads, 0)

    def test_current_page_with_cabinet_error_is_not_treated_as_loaded_usage(self):
        reader = NeurogateUsageReader(BrowserSettings(headless=True))

        class Locator:
            def inner_text(self, timeout: int) -> str:
                return """
                    КАБИНЕТ КЛИЕНТА
                    Лимиты
                    Подробная информация о Вашем тарифе
                    Could not load cabinet data.
                    ascend
                    активен ещё 28 д 8 ч
                    5 часов
                    117 888 444
                    Кредитов осталось
                    7 дней
                    421 381 328
                    Кредитов осталось
                """

        class Page:
            url = reader.settings.usage_url

            def locator(self, _selector: str) -> Locator:
                return Locator()

        reader._page = Page()

        self.assertFalse(reader._current_page_has_usage_data())

    def test_current_page_with_vibemode_dashboard_is_treated_as_loaded_usage(self):
        reader = NeurogateUsageReader(BrowserSettings(headless=True))

        class Locator:
            def inner_text(self, timeout: int) -> str:
                return "Мой дашборд\nКвота\n5-часовое окно\nКвота\n7-дневное окно"

        class Page:
            url = "https://portal.vibemod.pro/client"

            def locator(self, _selector: str) -> Locator:
                return Locator()

        reader._page = Page()

        self.assertTrue(reader._current_page_has_usage_data())

    def test_auto_login_submits_stable_prefilled_form(self):
        reader = NeurogateUsageReader(BrowserSettings(headless=True))
        reader._current_headless = False
        waits = 0
        clicks = 0

        class Page:
            def wait_for_timeout(self, _timeout: int) -> None:
                nonlocal waits
                waits += 1

        def click_login_submit() -> bool:
            nonlocal clicks
            clicks += 1
            return True

        reader._page = Page()
        reader._login_form_state = lambda: {"ready": True, "email": "user@example.com", "password": "__filled__"}  # type: ignore[method-assign]
        reader._click_login_submit = click_login_submit  # type: ignore[method-assign]
        reader._write_debug = lambda *_args, **_kwargs: None  # type: ignore[method-assign]

        submitted = reader._maybe_auto_submit_login()

        self.assertTrue(submitted)
        self.assertEqual(clicks, 1)
        self.assertEqual(waits, AUTO_LOGIN_DELAY_ATTEMPTS + 1)

    def test_hidden_prefilled_login_submits_without_visible_prompt(self):
        reader = NeurogateUsageReader(BrowserSettings(headless=True))
        reader._current_headless = True
        reader._page = type("Page", (), {"url": reader.settings.usage_url, "wait_for_timeout": lambda _self, _timeout: None})()
        texts = iter(["EMAIL\nПАРОЛЬ\nВойти", "ЛИМИТЫ ТАРИФА"])
        opened_visible: list[bool] = []
        clicks = 0

        def click_login_submit() -> bool:
            nonlocal clicks
            clicks += 1
            return True

        reader._wait_for_usage_text = lambda: next(texts)  # type: ignore[method-assign]
        reader._login_form_state = lambda: {  # type: ignore[method-assign]
            "ready": True,
            "email": "user@example.com",
            "password": "__filled__",
            "password_length": 8,
        }
        reader._click_login_submit = click_login_submit  # type: ignore[method-assign]
        reader._open_visible_login_window = lambda: opened_visible.append(True)  # type: ignore[method-assign]
        reader._read_vibemode_api_snapshot = lambda _text: UsageSnapshot(  # type: ignore[method-assign]
            updated_at=datetime.now(),
            windows=[UsageWindow(title="5 часов", credits_remaining=10)],
        )
        reader._hide_visible_browser_after_success = lambda: None  # type: ignore[method-assign]
        reader._write_debug = lambda *_args, **_kwargs: None  # type: ignore[method-assign]

        snapshot = reader.read()

        self.assertEqual(clicks, 1)
        self.assertEqual(opened_visible, [])
        self.assertTrue(snapshot.has_data)

    def test_auto_login_is_blocked_during_account_switch(self):
        reader = NeurogateUsageReader(BrowserSettings(headless=True))
        reader._current_headless = False
        reader._account_switch_pending = True
        clicks = 0

        class Page:
            def wait_for_timeout(self, _timeout: int) -> None:
                return None

        def click_login_submit() -> bool:
            nonlocal clicks
            clicks += 1
            return True

        reader._page = Page()
        reader._login_form_state = lambda: {"ready": True, "email": "old@example.com", "password": "__filled__"}  # type: ignore[method-assign]
        reader._click_login_submit = click_login_submit  # type: ignore[method-assign]

        submitted = reader._maybe_auto_submit_login()

        self.assertFalse(submitted)
        self.assertEqual(clicks, 0)

    def test_auto_login_cancels_when_login_form_changes(self):
        reader = NeurogateUsageReader(BrowserSettings(headless=True))
        reader._current_headless = False
        states = [
            {"ready": True, "email": "old@example.com", "password": "__filled__"},
            {"ready": True, "email": "new@example.com", "password": "__filled__"},
        ]
        clicks = 0

        class Page:
            def wait_for_timeout(self, _timeout: int) -> None:
                return None

        def login_form_state() -> dict[str, object]:
            return states.pop(0) if states else {"ready": True, "email": "new@example.com", "password": "__filled__"}

        def click_login_submit() -> bool:
            nonlocal clicks
            clicks += 1
            return True

        reader._page = Page()
        reader._login_form_state = login_form_state  # type: ignore[method-assign]
        reader._click_login_submit = click_login_submit  # type: ignore[method-assign]
        reader._write_debug = lambda *_args, **_kwargs: None  # type: ignore[method-assign]

        submitted = reader._maybe_auto_submit_login()

        self.assertFalse(submitted)
        self.assertEqual(clicks, 0)

    def test_visible_filled_login_form_is_not_submitted_automatically(self):
        reader = NeurogateUsageReader(BrowserSettings(headless=True))
        reader._page = type("Page", (), {"url": reader.settings.usage_url})()
        reader._current_headless = False
        reader._login_visible = True
        reader._wait_for_usage_text = lambda: "EMAIL\nПАРОЛЬ\nВойти"  # type: ignore[method-assign]
        reader._attach_window_progress = lambda _snapshot: None  # type: ignore[method-assign]
        reader._hide_visible_browser_after_success = lambda: None  # type: ignore[method-assign]
        reader._write_debug = lambda *_args, **_kwargs: None  # type: ignore[method-assign]

        snapshot = reader.read()

        self.assertFalse(snapshot.has_data)
        self.assertEqual(snapshot.status_note, "нужен вход")

    def test_reset_account_session_removes_profile_and_opens_login(self):
        with tempfile.TemporaryDirectory() as directory:
            profile_dir = Path(directory) / "browser-profile"
            profile_dir.mkdir()
            (profile_dir / "session.txt").write_text("local session", encoding="utf-8")
            reader = NeurogateUsageReader(BrowserSettings(profile_dir=profile_dir, headless=True))
            reader._playwright = object()
            reader._context = type("Context", (), {"close": lambda _self: None})()
            launches: list[bool] = []

            def fake_launch_context(*, headless: bool) -> None:
                launches.append(headless)
                reader._current_headless = headless

            reader._launch_context = fake_launch_context  # type: ignore[method-assign]
            reader._write_debug = lambda *_args, **_kwargs: None  # type: ignore[method-assign]

            reader.reset_account_session()

            self.assertFalse((profile_dir / "session.txt").exists())
            self.assertEqual(launches, [False])
            self.assertTrue(reader._login_prompt_opened)
            self.assertTrue(reader._login_visible)
            self.assertTrue(reader._account_switch_pending)

    def test_attach_window_progress_clamps_site_percent(self):
        reader = NeurogateUsageReader(BrowserSettings())
        reader._page = object()
        reader._extract_window_progress = lambda: [  # type: ignore[method-assign]
            {"title": "5 часов", "percent": 1.4},
            {"title": "7 дней", "percent": 150},
        ]
        snapshot = UsageSnapshot(
            updated_at=datetime.now(),
            windows=[UsageWindow(title="5 часов"), UsageWindow(title="7 дней")],
        )

        reader._attach_window_progress(snapshot)

        self.assertEqual(snapshot.windows[0].progress_percent, 1.4)
        self.assertEqual(snapshot.windows[1].progress_percent, 100.0)

    def test_attach_window_progress_does_not_shift_when_first_fill_is_missing(self):
        reader = NeurogateUsageReader(BrowserSettings())
        reader._page = object()
        reader._extract_window_progress = lambda: [{"title": "7 дней", "percent": 51.7}]  # type: ignore[method-assign]
        snapshot = UsageSnapshot(
            updated_at=datetime.now(),
            windows=[UsageWindow(title="5 часов"), UsageWindow(title="7 дней")],
        )

        reader._attach_window_progress(snapshot)

        self.assertIsNone(snapshot.windows[0].progress_percent)
        self.assertEqual(snapshot.windows[1].progress_percent, 51.7)

    def test_attach_window_progress_keeps_zero_percent_for_empty_first_bar(self):
        reader = NeurogateUsageReader(BrowserSettings())
        reader._page = object()
        reader._extract_window_progress = lambda: [  # type: ignore[method-assign]
            {"title": "5 часов", "percent": 0},
            {"title": "7 дней", "percent": 51.7},
        ]
        snapshot = UsageSnapshot(
            updated_at=datetime.now(),
            windows=[UsageWindow(title="5 часов"), UsageWindow(title="7 дней")],
        )

        reader._attach_window_progress(snapshot)

        self.assertEqual(snapshot.windows[0].progress_percent, 0.0)
        self.assertEqual(snapshot.windows[1].progress_percent, 51.7)


if __name__ == "__main__":
    unittest.main()
