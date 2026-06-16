import unittest
import tempfile
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

from neurogate_usage_overlay.browser_reader import (
    AUTO_LOGIN_DELAY_ATTEMPTS,
    CACHE_SIZE_BYTES,
    LOGIN_PROMPT_CONFIRM_ATTEMPTS,
    BrowserSettings,
    NeurogateUsageReader,
)
from neurogate_usage_overlay.models import UsageSnapshot, UsageWindow


class BrowserReaderModeTest(unittest.TestCase):
    def test_keep_browser_open_updates_settings_before_start(self):
        reader = NeurogateUsageReader(BrowserSettings())

        reader.set_keep_browser_open(True)

        self.assertTrue(reader.keep_browser_open)
        self.assertFalse(reader.settings.hide_after_successful_login)

        reader.set_keep_browser_open(False)

        self.assertFalse(reader.keep_browser_open)
        self.assertTrue(reader.settings.hide_after_successful_login)

    def test_keep_browser_open_switches_running_context(self):
        reader = NeurogateUsageReader(BrowserSettings(headless=True))
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
            reader._current_headless = True
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

        with patch("neurogate_usage_overlay.browser_reader._hide_windows_for_pids", return_value=2) as hide:
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
            windows=[UsageWindow(title="5 С‡Р°СЃРѕРІ"), UsageWindow(title="7 РґРЅРµР№")],
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
