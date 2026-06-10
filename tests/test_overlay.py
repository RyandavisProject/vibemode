import unittest
import tempfile
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

from neurogate_usage_overlay.models import UsageSnapshot, UsageWindow
from neurogate_usage_overlay.overlay import UsageOverlay
from neurogate_usage_overlay.update_checker import UpdateInfo


class FakeRoot:
    def __init__(self) -> None:
        self.after_calls: list[int] = []
        self.cancelled: list[str] = []

    def after(self, delay_ms: int, _callback):
        self.after_calls.append(delay_ms)
        return f"after-{len(self.after_calls)}"

    def after_cancel(self, after_id: str) -> None:
        self.cancelled.append(after_id)


class OverlayScheduleTest(unittest.TestCase):
    def test_interval_choices_include_one_hour_without_two_minutes(self):
        self.assertEqual(UsageOverlay.INTERVAL_CHOICES_MINUTES, (1, 3, 5, 10, 15, 60))
        self.assertEqual(UsageOverlay._format_interval_menu(60), "1 час")
        self.assertEqual(UsageOverlay._format_interval_pill(60), "1ч")

    def test_login_state_polls_quickly(self):
        overlay = UsageOverlay.__new__(UsageOverlay)
        overlay.root = FakeRoot()
        overlay.after_id = None
        overlay.interval_minutes = 1
        overlay.last_snapshot = UsageSnapshot(updated_at=datetime.now(), status_note="нужен вход")

        overlay._schedule_next_refresh()

        self.assertEqual(overlay.root.after_calls, [UsageOverlay.LOGIN_POLL_SECONDS * 1000])

    def test_fresh_data_uses_selected_interval(self):
        overlay = UsageOverlay.__new__(UsageOverlay)
        overlay.root = FakeRoot()
        overlay.after_id = None
        overlay.interval_minutes = 3
        overlay.last_snapshot = UsageSnapshot(
            updated_at=datetime.now(),
            windows=[UsageWindow(title="5 часов", credits_remaining=10)],
        )

        overlay._schedule_next_refresh()

        self.assertEqual(overlay.root.after_calls, [3 * 60 * 1000])

    def test_interval_is_saved_in_overlay_state(self):
        with tempfile.TemporaryDirectory() as directory:
            overlay = UsageOverlay.__new__(UsageOverlay)
            overlay.state_file = Path(directory) / "overlay-state.json"
            overlay.interval_minutes = 60

            overlay._save_interval_minutes()

            restored = UsageOverlay.__new__(UsageOverlay)
            restored.state_file = overlay.state_file
            self.assertEqual(restored._load_interval_minutes(1), 60)

    def test_ui_scale_is_saved_in_overlay_state(self):
        with tempfile.TemporaryDirectory() as directory:
            overlay = UsageOverlay.__new__(UsageOverlay)
            overlay.state_file = Path(directory) / "overlay-state.json"
            overlay.ui_scale = UsageOverlay.SCALE_LARGE

            overlay._save_ui_scale()

            restored = UsageOverlay.__new__(UsageOverlay)
            restored.state_file = overlay.state_file
            self.assertEqual(restored._load_ui_scale(), UsageOverlay.SCALE_LARGE)

    def test_window_position_save_preserves_interval(self):
        with tempfile.TemporaryDirectory() as directory:
            state_file = Path(directory) / "overlay-state.json"
            state_file.write_text('{"interval_minutes": 60}', encoding="utf-8")

            overlay = UsageOverlay.__new__(UsageOverlay)
            overlay.state_file = state_file
            overlay.root = type(
                "Root",
                (),
                {
                    "winfo_x": lambda _self: 100,
                    "winfo_y": lambda _self: 120,
                    "winfo_screenwidth": lambda _self: 800,
                    "winfo_screenheight": lambda _self: 600,
                },
            )()

            overlay._save_window_position()

            restored = UsageOverlay.__new__(UsageOverlay)
            restored.state_file = state_file
            self.assertEqual(restored._load_interval_minutes(1), 60)
            self.assertEqual(restored._load_window_position(), (100, 120))

    def test_window_position_save_preserves_scale(self):
        with tempfile.TemporaryDirectory() as directory:
            state_file = Path(directory) / "overlay-state.json"
            state_file.write_text('{"ui_scale": 2}', encoding="utf-8")

            overlay = UsageOverlay.__new__(UsageOverlay)
            overlay.state_file = state_file
            overlay.ui_scale = UsageOverlay.SCALE_LARGE
            overlay.root = type(
                "Root",
                (),
                {
                    "winfo_x": lambda _self: 100,
                    "winfo_y": lambda _self: 120,
                    "winfo_screenwidth": lambda _self: 800,
                    "winfo_screenheight": lambda _self: 600,
                },
            )()

            overlay._save_window_position()

            restored = UsageOverlay.__new__(UsageOverlay)
            restored.state_file = state_file
            self.assertEqual(restored._load_ui_scale(), UsageOverlay.SCALE_LARGE)


class OverlayPositionTest(unittest.TestCase):
    def test_saved_position_is_clamped_inside_screen(self):
        overlay = UsageOverlay.__new__(UsageOverlay)

        self.assertEqual(
            overlay._clamp_position(9999, -50, screen_width=800, screen_height=600),
            (800 - UsageOverlay.WIDTH - 8, 8),
        )

    def test_large_scale_position_is_clamped_inside_screen(self):
        overlay = UsageOverlay.__new__(UsageOverlay)
        overlay.ui_scale = UsageOverlay.SCALE_LARGE

        self.assertEqual(
            overlay._clamp_position(9999, -50, screen_width=800, screen_height=600),
            (800 - UsageOverlay.WIDTH * 2 - 8, 8),
        )


class OverlayProgressTest(unittest.TestCase):
    def test_window_progress_prefers_site_percent(self):
        overlay = UsageOverlay.__new__(UsageOverlay)
        window = UsageWindow(
            title="5 часов",
            credits_remaining=118_000_000,
            limit_used=1_000_000,
            limit_total=120_000_000,
            progress_percent=1.25,
        )

        self.assertEqual(overlay._window_progress_percent(window), 1.25)

    def test_window_progress_falls_back_to_used_total_pair(self):
        overlay = UsageOverlay.__new__(UsageOverlay)

        self.assertEqual(
            overlay._window_progress_percent(UsageWindow(title="7 дней", limit_used=300_000_000, limit_total=600_000_000)),
            50.0,
        )

    def test_zero_progress_does_not_draw_blue_fill(self):
        overlay = UsageOverlay.__new__(UsageOverlay)
        calls = []
        overlay._rounded_rect = lambda *args, **_kwargs: calls.append(args)

        overlay._progress(30, 42, 184, 0)

        self.assertEqual(len(calls), 1)

    def test_five_hour_tooltip_reports_spent_since_reset(self):
        overlay = UsageOverlay.__new__(UsageOverlay)
        window = UsageWindow(title="5 часов", limit_total=120_000_000, credits_remaining=119_300_000)

        self.assertEqual(overlay._limit_tooltip_text("5ч", window), "Потрачено со сброса: 700.0K")

    def test_seven_day_tooltip_reports_today_spent(self):
        overlay = UsageOverlay.__new__(UsageOverlay)
        snapshot = UsageSnapshot(updated_at=datetime.now(), windows=[UsageWindow(title="7 дней", credits_remaining=289_100_000)])
        overlay.last_snapshot = snapshot
        today_spent = type("TodaySpend", (), {"amount": 10_900_000, "since_text": "07:18"})()
        overlay.daily_usage = type("DailyUsage", (), {"today_spent_7d": lambda _self, _snapshot: today_spent})()

        self.assertEqual(overlay._limit_tooltip_text("7д", snapshot.windows[0]), "сегодня потрачено с 07:18: 10.9M")

    def test_seven_day_tooltip_hides_unknown_since_time(self):
        overlay = UsageOverlay.__new__(UsageOverlay)
        snapshot = UsageSnapshot(updated_at=datetime.now(), windows=[UsageWindow(title="7 дней", credits_remaining=289_100_000)])
        overlay.last_snapshot = snapshot
        today_spent = type("TodaySpend", (), {"amount": 1_500_000, "since_text": "--:--"})()
        overlay.daily_usage = type("DailyUsage", (), {"today_spent_7d": lambda _self, _snapshot: today_spent})()

        self.assertEqual(overlay._limit_tooltip_text("7д", snapshot.windows[0]), "сегодня потрачено: 1.5M")

    def test_seven_day_tooltip_uses_full_day_wording_for_midnight_baseline(self):
        overlay = UsageOverlay.__new__(UsageOverlay)
        snapshot = UsageSnapshot(updated_at=datetime.now(), windows=[UsageWindow(title="7 дней", credits_remaining=289_100_000)])
        overlay.last_snapshot = snapshot
        today_spent = type("TodaySpend", (), {"amount": 10_400_000, "since_text": "00:00"})()
        overlay.daily_usage = type("DailyUsage", (), {"today_spent_7d": lambda _self, _snapshot: today_spent})()

        self.assertEqual(overlay._limit_tooltip_text("7д", snapshot.windows[0]), "сегодня потрачено: 10.4M")


class OverlayRenderTest(unittest.TestCase):
    def test_login_state_renders_single_centered_message(self):
        overlay = UsageOverlay(lambda: UsageSnapshot(updated_at=datetime.now()))
        try:
            overlay.last_snapshot = UsageSnapshot(updated_at=datetime.now(), status_note="нужен вход")
            overlay.status_text = "нужен вход"

            overlay._render()
            overlay.root.update_idletasks()

            text_items = [
                item
                for item in overlay.canvas.find_all()
                if overlay.canvas.type(item) == "text"
            ]
            self.assertEqual(len(text_items), 1)
            self.assertEqual(overlay.canvas.itemcget(text_items[0], "text"), "нужен вход")
            self.assertEqual(
                tuple(round(value) for value in overlay.canvas.coords(text_items[0])),
                (overlay._s(UsageOverlay.WIDTH // 2), overlay._s(UsageOverlay.HEIGHT // 2)),
            )
        finally:
            overlay.close()


class OverlayUpdateTest(unittest.TestCase):
    def test_start_update_launches_update_script_with_target_version(self):
        overlay = UsageOverlay.__new__(UsageOverlay)
        overlay.update_info = UpdateInfo(
            current_version="1.5.0",
            latest_version="1.5.1",
            release_url="https://github.com/RyandavisProject/neurogate-overlay/releases/tag/v1.5.1",
        )
        closed = []
        overlay.close = lambda: closed.append(True)
        overlay._apply_error = lambda error: self.fail(f"unexpected update error: {error}")

        with patch("neurogate_usage_overlay.overlay.subprocess.Popen") as popen:
            overlay._start_update()

        self.assertTrue(closed)
        args = popen.call_args.args[0]
        self.assertTrue(any(str(item).endswith("update-and-restart.ps1") for item in args))
        self.assertIn("-TargetVersion", args)
        self.assertIn("v1.5.1", args)


if __name__ == "__main__":
    unittest.main()
