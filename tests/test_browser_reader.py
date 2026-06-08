import unittest
from datetime import datetime
from unittest.mock import patch

from neurogate_usage_overlay.browser_reader import BrowserSettings, NeurogateUsageReader
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

    def test_visible_mode_uses_reachable_window_args(self):
        reader = NeurogateUsageReader(BrowserSettings(headless=False))

        args = reader._browser_args(hidden=False)

        self.assertIn("--window-position=96,80", args)
        self.assertIn("--window-size=1180,860", args)

    def test_hidden_taskbar_hider_uses_profile_browser_pids(self):
        reader = NeurogateUsageReader(BrowserSettings())
        reader._profile_browser_process_ids = lambda: {123, 456}  # type: ignore[method-assign]

        with patch("neurogate_usage_overlay.browser_reader._hide_windows_for_pids", return_value=2) as hide:
            hidden_count = reader._hide_hidden_browser_taskbar_windows()

        hide.assert_called_once_with({123, 456})
        self.assertEqual(hidden_count, 2)

    def test_login_state_returns_fresh_status_without_cache(self):
        reader = NeurogateUsageReader(BrowserSettings(headless=True))
        reader._page = type("Page", (), {"url": reader.settings.usage_url})()
        reader._current_headless = True
        reader._wait_for_usage_text = lambda: "EMAIL\nПАРОЛЬ\nВойти"  # type: ignore[method-assign]
        reader._click_login_action_if_available = lambda: None  # type: ignore[method-assign]
        reader._open_visible_login_window = lambda: None  # type: ignore[method-assign]
        reader._write_debug = lambda *_args, **_kwargs: None  # type: ignore[method-assign]

        snapshot = reader.read()

        self.assertFalse(snapshot.has_data)
        self.assertFalse(snapshot.is_cached)
        self.assertEqual(snapshot.status_note, "нужен вход")

    def test_visible_filled_login_form_is_submitted_automatically(self):
        reader = NeurogateUsageReader(BrowserSettings(headless=True))
        reader._page = type("Page", (), {"url": reader.settings.usage_url})()
        reader._current_headless = False
        reader._login_visible = True
        calls = {"click": 0}
        texts = iter(
            [
                "EMAIL\nПАРОЛЬ\nВойти",
                """
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
                """,
            ]
        )

        def click_login() -> bool:
            calls["click"] += 1
            return True

        reader._wait_for_usage_text = lambda: next(texts)  # type: ignore[method-assign]
        reader._click_login_action_if_available = click_login  # type: ignore[method-assign]
        reader._attach_window_progress = lambda _snapshot: None  # type: ignore[method-assign]
        reader._hide_visible_browser_after_success = lambda: None  # type: ignore[method-assign]
        reader._write_debug = lambda *_args, **_kwargs: None  # type: ignore[method-assign]

        snapshot = reader.read()

        self.assertEqual(calls["click"], 1)
        self.assertTrue(snapshot.has_data)

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
