import unittest
import tempfile
import threading
import time
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import patch

from neurogate_usage_overlay.models import UsageSnapshot, UsageWindow
from neurogate_usage_overlay.overlay import UsageOverlay, compact_percent
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

    def update_idletasks(self) -> None:
        pass


class FakePositionRoot(FakeRoot):
    def __init__(self, x: int = 100, y: int = 120) -> None:
        super().__init__()
        self.x = x
        self.y = y
        self.callbacks = {}

    def after(self, delay_ms: int, callback):
        after_id = super().after(delay_ms, callback)
        self.callbacks[after_id] = callback
        return after_id

    def winfo_x(self) -> int:
        return self.x

    def winfo_y(self) -> int:
        return self.y


class FakeDragRoot(FakePositionRoot):
    def __init__(self, x: int = 100, y: int = 120) -> None:
        super().__init__(x, y)
        self.geometry_calls: list[str] = []

    def geometry(self, value: str) -> None:
        self.geometry_calls.append(value)
        if value.startswith("+"):
            x_text, y_text = value[1:].split("+", 1)
            self.x = int(x_text)
            self.y = int(y_text)


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
        overlay.transient_failure_count = 0
        overlay.last_snapshot = UsageSnapshot(
            updated_at=datetime.now(),
            windows=[UsageWindow(title="5 часов", credits_remaining=10)],
        )

        overlay._schedule_next_refresh()

        self.assertEqual(overlay.root.after_calls, [3 * 60 * 1000])

    def test_pending_transient_failure_polls_quickly_while_showing_old_data(self):
        overlay = UsageOverlay.__new__(UsageOverlay)
        overlay.root = FakeRoot()
        overlay.after_id = None
        overlay.interval_minutes = 10
        overlay.transient_failure_count = 1
        overlay.last_snapshot = UsageSnapshot(
            updated_at=datetime.now(),
            windows=[UsageWindow(title="5 часов", credits_remaining=10)],
        )

        overlay._schedule_next_refresh()

        self.assertEqual(overlay.root.after_calls, [UsageOverlay.LOGIN_POLL_SECONDS * 1000])

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

    def test_daily_limit_is_saved_in_overlay_state(self):
        with tempfile.TemporaryDirectory() as directory:
            overlay = UsageOverlay.__new__(UsageOverlay)
            overlay.state_file = Path(directory) / "overlay-state.json"
            overlay.daily_limit_credits = 82_000_000
            overlay.daily_limit_set_at = datetime(2026, 6, 14, 10, 0).astimezone()

            overlay._save_daily_limit_credits()

            restored = UsageOverlay.__new__(UsageOverlay)
            restored.state_file = overlay.state_file
            restored.daily_limit_set_at = restored._load_daily_limit_set_at()
            self.assertEqual(restored._load_daily_limit_credits(), 82_000_000)
            self.assertEqual(restored.daily_limit_set_at.hour, 10)

    def test_legacy_daily_limit_without_suffix_is_migrated_to_millions(self):
        with tempfile.TemporaryDirectory() as directory:
            state_file = Path(directory) / "overlay-state.json"
            state_file.write_text('{"daily_limit_credits": 80}', encoding="utf-8")

            overlay = UsageOverlay.__new__(UsageOverlay)
            overlay.state_file = state_file

            self.assertEqual(overlay._load_daily_limit_credits(), 80_000_000)

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

    def test_window_position_is_saved_after_configure_event(self):
        with tempfile.TemporaryDirectory() as directory:
            overlay = UsageOverlay.__new__(UsageOverlay)
            overlay.state_file = Path(directory) / "overlay-state.json"
            overlay.root = FakePositionRoot(144, 188)
            overlay.position_after_id = None
            overlay._write_ui_log = lambda _message: None

            event = type("Event", (), {"widget": overlay.root})()
            overlay._remember_window_position_soon(event)
            overlay.root.callbacks[overlay.position_after_id]()

            restored = UsageOverlay.__new__(UsageOverlay)
            restored.state_file = overlay.state_file
            self.assertEqual(restored._load_window_position(), (144, 188))

    def test_resume_watchdog_forces_refresh_after_long_gap(self):
        overlay = UsageOverlay.__new__(UsageOverlay)
        root = FakeRoot()
        overlay.root = root
        overlay.resume_after_id = None
        overlay.last_resume_check_at = datetime.now().astimezone() - timedelta(
            seconds=UsageOverlay.RESUME_GAP_SECONDS + 5
        )
        overlay.last_refresh_at = datetime.now().astimezone()
        overlay.refreshing = False
        calls = []
        overlay.refresh = lambda force=False: calls.append(force)
        overlay._write_ui_log = lambda _message: None

        overlay._check_resume_watchdog()

        self.assertEqual(calls, [True])
        self.assertIsNone(overlay.last_refresh_at)
        self.assertEqual(root.after_calls, [UsageOverlay.RESUME_HEARTBEAT_SECONDS * 1000])


class OverlayPositionTest(unittest.TestCase):
    def test_drag_uses_screen_coordinates_and_batches_geometry_updates(self):
        overlay = UsageOverlay.__new__(UsageOverlay)
        overlay.root = FakeDragRoot(100, 120)
        overlay.position_after_id = None
        overlay.drag_after_id = None
        overlay._hide_menu = lambda: None
        overlay._hide_tooltip = lambda: None

        overlay._start_drag(type("Event", (), {"x": 10, "y": 10, "x_root": 210, "y_root": 310})())
        overlay._drag(type("Event", (), {"x": 14, "y": 14, "x_root": 260, "y_root": 360})())
        first_after_id = overlay.drag_after_id
        overlay._drag(type("Event", (), {"x": 20, "y": 20, "x_root": 280, "y_root": 390})())

        self.assertEqual(overlay.root.after_calls, [UsageOverlay.DRAG_FRAME_MS])
        self.assertEqual(overlay.root.geometry_calls, [])

        overlay.root.callbacks[first_after_id]()

        self.assertEqual(overlay.root.geometry_calls, ["+170+200"])

    def test_configure_position_save_is_skipped_while_dragging(self):
        overlay = UsageOverlay.__new__(UsageOverlay)
        overlay.root = FakeDragRoot(100, 120)
        overlay.position_after_id = None
        overlay.dragging = True
        overlay._write_ui_log = lambda _message: None

        overlay._remember_window_position_soon(type("Event", (), {"widget": overlay.root})())

        self.assertEqual(overlay.root.after_calls, [])
        self.assertIsNone(overlay.position_after_id)

    def test_drag_release_applies_latest_position_and_saves_once(self):
        overlay = UsageOverlay.__new__(UsageOverlay)
        overlay.root = FakeDragRoot(100, 120)
        overlay.position_after_id = None
        overlay.drag_after_id = None
        overlay._hide_menu = lambda: None
        overlay._hide_tooltip = lambda: None
        saves = []
        overlay._save_window_position = lambda: saves.append((overlay.root.winfo_x(), overlay.root.winfo_y()))

        overlay._start_drag(type("Event", (), {"x": 10, "y": 10, "x_root": 210, "y_root": 310})())
        overlay._drag(type("Event", (), {"x": 20, "y": 20, "x_root": 290, "y_root": 410})())
        overlay._end_drag(type("Event", (), {})())

        self.assertEqual(overlay.root.cancelled, ["after-1"])
        self.assertEqual(overlay.root.geometry_calls, ["+180+220"])
        self.assertEqual(saves, [(180, 220)])
        self.assertFalse(overlay.dragging)

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

    def test_daily_limit_expands_height_only_when_enabled(self):
        overlay = UsageOverlay.__new__(UsageOverlay)
        overlay.daily_limit_credits = None
        overlay.daily_limit_set_at = None

        self.assertEqual(overlay._content_height(), UsageOverlay.HEIGHT)

        overlay.daily_limit_credits = 82_000_000
        overlay.daily_limit_set_at = datetime.now().astimezone()
        self.assertEqual(overlay._content_height(), UsageOverlay.DAILY_LIMIT_HEIGHT)

    def test_expired_daily_limit_uses_normal_height(self):
        overlay = UsageOverlay.__new__(UsageOverlay)
        overlay.daily_limit_credits = 82_000_000
        overlay.daily_limit_set_at = datetime.now().astimezone() - timedelta(hours=25)

        self.assertEqual(overlay._content_height(), UsageOverlay.HEIGHT)

    def test_daily_limit_expires_on_next_calendar_day_even_before_24_hours(self):
        fixed_now = datetime(2026, 6, 15, 9, 0).astimezone()

        class FixedDatetime(datetime):
            @classmethod
            def now(cls, tz=None):
                return fixed_now if tz is None else fixed_now.astimezone(tz)

        overlay = UsageOverlay.__new__(UsageOverlay)
        overlay.daily_limit_credits = 82_000_000
        overlay.daily_limit_set_at = datetime(2026, 6, 14, 22, 0).astimezone()

        with patch("neurogate_usage_overlay.overlay.datetime", FixedDatetime):
            self.assertEqual(overlay._content_height(), UsageOverlay.HEIGHT)

    def test_daily_limit_without_set_time_is_treated_as_expired(self):
        overlay = UsageOverlay.__new__(UsageOverlay)
        overlay.daily_limit_credits = 82_000_000
        overlay.daily_limit_set_at = None

        self.assertEqual(overlay._content_height(), UsageOverlay.HEIGHT)


class OverlayProgressTest(unittest.TestCase):
    def test_compact_percent_formats_daily_limit_progress(self):
        self.assertEqual(compact_percent(13.29), "13%")
        self.assertEqual(compact_percent(8.71), "8.7%")
        self.assertEqual(compact_percent(100.4), "100%")

    def test_credit_input_accepts_millions_suffix(self):
        self.assertEqual(UsageOverlay._parse_credit_input("82M"), 82_000_000)
        self.assertEqual(UsageOverlay._parse_credit_input("82,5 млн"), 82_500_000)
        self.assertEqual(UsageOverlay._parse_credit_input("80"), 80_000_000)
        self.assertEqual(UsageOverlay._parse_credit_input("82000000"), 82_000_000)
        self.assertIsNone(UsageOverlay._parse_credit_input("нет"))

    def test_daily_limit_dialog_prefills_saved_limit_when_editing(self):
        overlay = UsageOverlay.__new__(UsageOverlay)
        overlay.daily_limit_credits = 80_000_000
        overlay.daily_limit_set_at = datetime.now().astimezone()

        self.assertEqual(overlay._daily_limit_dialog_default_credits(), 80_000_000)

    def test_plan_days_include_hours_as_decimal_part(self):
        self.assertAlmostEqual(UsageOverlay._remaining_plan_days("активен еще 2 дня 18 часов"), 2.75)
        self.assertAlmostEqual(UsageOverlay._remaining_plan_days("ост. 4д 10ч"), 4 + 10 / 24)

    def test_daily_limit_dialog_suggests_seven_day_remaining_divided_by_reset_days(self):
        overlay = UsageOverlay.__new__(UsageOverlay)
        overlay.daily_limit_credits = None
        overlay.daily_limit_set_at = None
        overlay.last_snapshot = UsageSnapshot(
            updated_at=datetime.now(),
            plan_status="активен еще 28 дней",
            windows=[UsageWindow(title="7 дней", credits_remaining=345_000_000, reset_text="4д 10ч")],
        )

        self.assertEqual(overlay._daily_limit_dialog_default_credits(), 78_113_208)

    def test_daily_limit_hint_reports_weekly_floor_after_daily_limit(self):
        overlay = UsageOverlay.__new__(UsageOverlay)
        overlay.last_snapshot = UsageSnapshot(
            updated_at=datetime.now(),
            windows=[UsageWindow(title="7 дней", credits_remaining=413_100_000, reset_text="5д 8ч")],
        )
        overlay.daily_limit_credits = 80_000_000
        overlay.daily_limit_set_at = datetime.now().astimezone()
        today_spent = type("TodaySpend", (), {"amount": 8_700_000, "since_text": "00:00"})()
        overlay.daily_usage = type("DailyUsage", (), {"today_spent_7d": lambda _self, _snapshot: today_spent})()

        self.assertEqual(overlay._daily_limit_hint(), "не падаем ниже 333.1M")

    def test_daily_limit_values_use_today_spent_and_saved_limit(self):
        overlay = UsageOverlay.__new__(UsageOverlay)
        snapshot = UsageSnapshot(updated_at=datetime.now(), windows=[UsageWindow(title="7 дней", credits_remaining=421_300_000)])
        overlay.last_snapshot = snapshot
        overlay.daily_limit_credits = 82_000_000
        overlay.daily_limit_set_at = datetime.now().astimezone()
        today_spent = type("TodaySpend", (), {"amount": 10_900_000, "since_text": "00:00"})()
        overlay.daily_usage = type("DailyUsage", (), {"today_spent_7d": lambda _self, _snapshot: today_spent})()

        spent, limit, floor, percent = overlay._daily_limit_values()
        self.assertEqual((spent, limit, floor), (10_900_000, 82_000_000, 339_300_000))
        self.assertAlmostEqual(percent, 13.29, places=2)

    def test_daily_progress_color_warns_after_half_and_red_after_limit(self):
        overlay = UsageOverlay.__new__(UsageOverlay)

        self.assertEqual(overlay._daily_progress_color(49), "#76a8ff")
        self.assertEqual(overlay._daily_progress_color(50), "#76a8ff")
        self.assertEqual(overlay._daily_progress_color(53), "#ffcb5d")
        self.assertEqual(overlay._daily_progress_color(75), "#ff9f1c")
        self.assertEqual(overlay._daily_progress_color(90), "#ff6e43")
        self.assertEqual(overlay._daily_progress_color(100), "#ff4d5d")

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
    def test_render_does_not_rebind_canvas_tags(self):
        snapshot = UsageSnapshot(
            updated_at=datetime.now(),
            windows=[
                UsageWindow(title="5 часов", credits_remaining=119_000_000, reset_text="2 часа"),
                UsageWindow(title="7 дней", credits_remaining=421_300_000, reset_text="5 дней"),
            ],
        )
        overlay = UsageOverlay(lambda: snapshot)
        try:
            overlay.last_snapshot = snapshot
            overlay.daily_limit_credits = 82_000_000
            overlay.daily_limit_set_at = datetime.now().astimezone()
            today_spent = type("TodaySpend", (), {"amount": 10_900_000, "since_text": "00:00"})()
            overlay.daily_usage = type("DailyUsage", (), {"today_spent_7d": lambda _self, _snapshot: today_spent})()
            calls = []
            original_tag_bind = overlay.canvas.tag_bind
            overlay.canvas.tag_bind = lambda *args, **kwargs: calls.append((args, kwargs)) or original_tag_bind(*args, **kwargs)

            overlay._render()
            overlay._render()

            self.assertEqual(calls, [])
        finally:
            overlay.close()

    def test_tooltip_text_is_resolved_from_current_canvas_tag(self):
        overlay = UsageOverlay.__new__(UsageOverlay)
        overlay.tooltip_text_by_tag = {"limit-value-7d": "сегодня потрачено: 10.4M"}

        class Canvas:
            def find_withtag(self, tag):
                return (5,) if tag == "current" else ()

            def gettags(self, _item):
                return ("tooltip-target", "limit-value-7d")

        event = type("Event", (), {"widget": Canvas()})()

        self.assertEqual(overlay._tooltip_text_for_event(event), "сегодня потрачено: 10.4M")

    def test_daily_limit_row_has_double_click_editor_binding(self):
        snapshot = UsageSnapshot(
            updated_at=datetime.now(),
            windows=[UsageWindow(title="7 дней", credits_remaining=421_300_000)],
        )
        overlay = UsageOverlay(lambda: snapshot)
        try:
            overlay.last_snapshot = snapshot
            overlay.daily_limit_credits = 82_000_000
            overlay.daily_limit_set_at = datetime.now().astimezone()
            today_spent = type("TodaySpend", (), {"amount": 10_900_000, "since_text": "00:00"})()
            overlay.daily_usage = type("DailyUsage", (), {"today_spent_7d": lambda _self, _snapshot: today_spent})()

            overlay._render()

            self.assertTrue(overlay.canvas.tag_bind("daily-limit-row", "<Double-Button-1>"))
            percent_items = overlay.canvas.find_withtag("daily-limit-percent")
            self.assertEqual(len(percent_items), 1)
            self.assertEqual(overlay.canvas.itemcget(percent_items[0], "text"), "13%")
        finally:
            overlay.close()

    def test_login_state_renders_single_centered_message(self):
        overlay = UsageOverlay(lambda: UsageSnapshot(updated_at=datetime.now()))
        try:
            overlay.last_snapshot = UsageSnapshot(updated_at=datetime.now(), status_note="нужен вход")
            overlay.status_text = "нужен вход"
            overlay.daily_limit_credits = None

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


class OverlayTransientStatusTest(unittest.TestCase):
    def test_async_refresh_returns_before_slow_reader_finishes(self):
        finished = threading.Event()
        snapshot = UsageSnapshot(
            updated_at=datetime(2026, 6, 12, 15, 25),
            windows=[UsageWindow(title="5 часов", credits_remaining=118_900_000)],
        )

        class AsyncRoot(FakeRoot):
            def after(self, delay_ms: int, callback):
                result = super().after(delay_ms, callback)
                if delay_ms == 0:
                    callback()
                    finished.set()
                return result

        def slow_reader() -> UsageSnapshot:
            time.sleep(0.15)
            return snapshot

        overlay = UsageOverlay.__new__(UsageOverlay)
        overlay.reader = slow_reader
        overlay.root = AsyncRoot()
        overlay.after_id = None
        overlay.interval_minutes = 1
        overlay.refreshing = False
        overlay.async_refresh = True
        overlay.last_snapshot = None
        overlay.last_refresh_at = None
        overlay.status_text = "обновляю"
        overlay.transient_failure_since = None
        overlay.transient_failure_count = 0
        overlay.transient_status_note = None
        overlay.daily_usage = type("DailyUsage", (), {"record_snapshot": lambda *_args: None})()
        overlay._render = lambda: None
        overlay._write_ui_log = lambda _message: None

        started = time.perf_counter()
        overlay.refresh()
        elapsed = time.perf_counter() - started

        self.assertLess(elapsed, 0.08)
        self.assertTrue(overlay.refreshing)
        self.assertTrue(finished.wait(1))
        self.assertFalse(overlay.refreshing)
        self.assertEqual(overlay.last_snapshot, snapshot)

    def test_no_data_keeps_last_successful_snapshot_during_grace(self):
        overlay = UsageOverlay.__new__(UsageOverlay)
        good_snapshot = UsageSnapshot(
            updated_at=datetime(2026, 6, 12, 15, 20),
            windows=[UsageWindow(title="5 часов", credits_remaining=119_000_000)],
        )
        no_data_snapshot = UsageSnapshot(updated_at=datetime.now(), status_note="нужен вход")
        renders = []
        overlay.last_snapshot = good_snapshot
        overlay.last_refresh_at = good_snapshot.updated_at
        overlay.status_text = "обн. 15:20"
        overlay.transient_failure_since = None
        overlay.transient_failure_count = 0
        overlay.transient_status_note = None
        overlay._render = lambda: renders.append(overlay.status_text)
        overlay._write_ui_log = lambda _message: None

        overlay._apply_snapshot(no_data_snapshot)

        self.assertIs(overlay.last_snapshot, good_snapshot)
        self.assertEqual(overlay.status_text, "обн. 15:20")
        self.assertEqual(overlay.transient_failure_count, 1)
        self.assertEqual(overlay.transient_status_note, "нужен вход")
        self.assertEqual(renders, ["обн. 15:20"])

    def test_no_data_after_grace_confirms_login_state(self):
        overlay = UsageOverlay.__new__(UsageOverlay)
        good_snapshot = UsageSnapshot(
            updated_at=datetime(2026, 6, 12, 15, 20),
            windows=[UsageWindow(title="5 часов", credits_remaining=119_000_000)],
        )
        no_data_snapshot = UsageSnapshot(updated_at=datetime.now(), status_note="нужен вход")
        renders = []
        overlay.last_snapshot = good_snapshot
        overlay.last_refresh_at = good_snapshot.updated_at
        overlay.status_text = "обн. 15:20"
        overlay.transient_failure_since = datetime.now().astimezone() - timedelta(
            seconds=UsageOverlay.TRANSIENT_FAILURE_GRACE_SECONDS + 1
        )
        overlay.transient_failure_count = UsageOverlay.TRANSIENT_FAILURE_CONFIRMATIONS - 1
        overlay.transient_status_note = "нужен вход"
        overlay._render = lambda: renders.append(overlay.status_text)
        overlay._write_ui_log = lambda _message: None

        overlay._apply_snapshot(no_data_snapshot)

        self.assertIs(overlay.last_snapshot, no_data_snapshot)
        self.assertEqual(overlay.status_text, "нужен вход")
        self.assertEqual(renders, ["нужен вход"])

    def test_refresh_with_existing_data_does_not_render_updating_status(self):
        overlay = UsageOverlay.__new__(UsageOverlay)
        old_snapshot = UsageSnapshot(
            updated_at=datetime(2026, 6, 12, 15, 20),
            windows=[UsageWindow(title="5 часов", credits_remaining=119_000_000)],
        )
        new_snapshot = UsageSnapshot(
            updated_at=datetime(2026, 6, 12, 15, 25),
            windows=[UsageWindow(title="5 часов", credits_remaining=118_900_000)],
        )
        renders = []
        overlay.reader = lambda: new_snapshot
        overlay.root = FakeRoot()
        overlay.after_id = None
        overlay.interval_minutes = 1
        overlay.refreshing = False
        overlay.last_snapshot = old_snapshot
        overlay.last_refresh_at = datetime.now().astimezone() - timedelta(minutes=2)
        overlay.status_text = "обн. 15:20"
        overlay.transient_failure_since = None
        overlay.transient_failure_count = 0
        overlay.transient_status_note = None
        overlay.daily_usage = type("DailyUsage", (), {"record_snapshot": lambda *_args: None})()
        overlay._render = lambda: renders.append(overlay.status_text)
        overlay._write_ui_log = lambda _message: None

        overlay.refresh()

        self.assertNotIn("обновляю", renders)
        self.assertEqual(overlay.last_snapshot, new_snapshot)
        self.assertEqual(renders, ["обн. 15:25"])


class OverlayAccountTest(unittest.TestCase):
    def test_reset_account_runs_resetter_and_marks_login_needed(self):
        overlay = UsageOverlay.__new__(UsageOverlay)
        calls = []
        renders = []
        overlay.account_resetter = lambda: calls.append(True)
        overlay.root = FakeRoot()
        overlay.after_id = None
        overlay.interval_minutes = 1
        overlay._render = lambda: renders.append(True)
        overlay._apply_error = lambda error: self.fail(f"unexpected reset error: {error}")

        overlay._reset_account()

        self.assertEqual(calls, [True])
        self.assertEqual(renders, [True])
        self.assertEqual(overlay.status_text, "нужен вход")
        self.assertEqual(overlay.last_snapshot.status_note, "нужен вход")
        self.assertEqual(overlay.root.after_calls, [UsageOverlay.LOGIN_POLL_SECONDS * 1000])


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

    def test_start_update_passes_release_zip_and_checksum(self):
        overlay = UsageOverlay.__new__(UsageOverlay)
        overlay.update_info = UpdateInfo(
            current_version="1.6.0",
            latest_version="1.7.0",
            release_url="https://github.com/RyandavisProject/neurogate-overlay/releases/tag/v1.7.0",
            release_zip_url="https://example.test/neurogate-overlay-v1.7.0.zip",
            release_sha256="b" * 64,
        )
        overlay.close = lambda: None
        overlay._apply_error = lambda error: self.fail(f"unexpected update error: {error}")

        with patch("neurogate_usage_overlay.overlay.subprocess.Popen") as popen:
            overlay._start_update()

        args = popen.call_args.args[0]
        self.assertIn("-ReleaseZipUrl", args)
        self.assertIn("https://example.test/neurogate-overlay-v1.7.0.zip", args)
        self.assertIn("-ReleaseSha256", args)
        self.assertIn("b" * 64, args)


if __name__ == "__main__":
    unittest.main()
