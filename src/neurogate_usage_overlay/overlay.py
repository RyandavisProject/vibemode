from __future__ import annotations

import math
import json
import re
import subprocess
import sys
import threading
import tkinter as tk
from datetime import datetime, timedelta
from pathlib import Path
from typing import Callable

from .history import DailyUsageStore, find_window, spent_since_reset, window_key
from .log_utils import append_bounded_log
from .models import UsageSnapshot, UsageWindow
from .update_checker import UpdateInfo, check_for_update


SnapshotReader = Callable[[], UsageSnapshot]
KeepBrowserGetter = Callable[[], bool]
KeepBrowserSetter = Callable[[bool], None]
AccountResetter = Callable[[], None]


def short_number(value: int | None) -> str:
    if value is None:
        return "-"
    if abs(value) >= 1_000_000_000:
        return f"{value / 1_000_000_000:.2f}B"
    if abs(value) >= 1_000_000:
        return f"{value / 1_000_000:.1f}M"
    if abs(value) >= 1_000:
        return f"{value / 1_000:.1f}K"
    return str(value)


def format_credits(value: int | None) -> str:
    if value is None:
        return "-"
    return short_number(value)


def short_number_clean(value: int | None) -> str:
    return short_number(value).replace(".0B", "B").replace(".0M", "M").replace(".0K", "K")


def compact_percent(value: float | None) -> str:
    if value is None:
        return "-"
    if value >= 100:
        return f"{round(value):.0f}%"
    if value >= 10:
        return f"{value:.0f}%"
    return f"{value:.1f}%"


def compact_reset_text(value: str | None) -> str:
    if not value:
        return "-"
    return (
        value.replace(" дней", "д")
        .replace(" день", "д")
        .replace(" д", "д")
        .replace(" часов", "ч")
        .replace(" часа", "ч")
        .replace(" час", "ч")
        .replace(" ч", "ч")
        .replace(" минут", "м")
        .replace(" минуты", "м")
        .replace(" мин", "м")
    )


def compact_plan_status(value: str | None) -> str:
    if not value:
        return ""
    cleaned = value.strip()
    prefixes = ("активен ещё", "активен еще")
    for prefix in prefixes:
        if cleaned.lower().startswith(prefix):
            cleaned = cleaned[len(prefix) :].strip()
            break
    return f"ост. {compact_reset_text(cleaned)}"


class UsageOverlay:
    WIDTH = 222
    HEIGHT = 70
    DAILY_LIMIT_HEIGHT = 92
    SCALE_NORMAL = 1
    SCALE_LARGE = 2
    MIN_REFRESH_SECONDS = 60
    LOGIN_POLL_SECONDS = 2
    TRANSIENT_FAILURE_CONFIRMATIONS = 3
    TRANSIENT_FAILURE_GRACE_SECONDS = 30
    UPDATE_CHECK_SECONDS = 24 * 60 * 60
    RESUME_HEARTBEAT_SECONDS = 30
    RESUME_GAP_SECONDS = 120
    DRAG_FRAME_MS = 16
    INTERVAL_CHOICES_MINUTES = (1, 3, 5, 10, 15, 60)
    if sys.platform == "darwin":
        UI_FONT = "SF Pro Text"
        TEXT_FONT = "SF Pro Text"
        NUMBER_FONT = "Helvetica Neue"
    elif sys.platform.startswith("win"):
        UI_FONT = "Segoe UI Variable Small"
        TEXT_FONT = "Segoe UI Variable Text"
        NUMBER_FONT = "Calibri Light"
    else:
        UI_FONT = "DejaVu Sans"
        TEXT_FONT = "DejaVu Sans"
        NUMBER_FONT = "DejaVu Sans"

    def __init__(
        self,
        reader: SnapshotReader,
        interval_seconds: int = 60,
        keep_browser_open_getter: KeepBrowserGetter | None = None,
        keep_browser_open_setter: KeepBrowserSetter | None = None,
        account_resetter: AccountResetter | None = None,
        async_refresh: bool = False,
    ) -> None:
        self.reader = reader
        self.keep_browser_open_getter = keep_browser_open_getter
        self.keep_browser_open_setter = keep_browser_open_setter
        self.account_resetter = account_resetter
        self.async_refresh = async_refresh
        self.debug_log = Path.home() / ".neurogate-usage-overlay" / "overlay-ui.log"
        self.state_file = Path.home() / ".neurogate-usage-overlay" / "overlay-state.json"
        self.daily_usage = DailyUsageStore(Path.home() / ".neurogate-usage-overlay" / "usage-daily.json")
        default_interval = self._normalize_interval_minutes(math.ceil(interval_seconds / 60))
        self.interval_minutes = self._load_interval_minutes(default_interval)
        self.ui_scale = self._load_ui_scale()
        self.daily_limit_set_at = self._load_daily_limit_set_at()
        self.daily_limit_credits = self._load_daily_limit_credits()
        self.refreshing = False
        self.after_id: str | None = None
        self.resume_after_id: str | None = None
        self.last_refresh_at: datetime | None = None
        self.last_resume_check_at: datetime | None = None
        self.last_snapshot: UsageSnapshot | None = None
        self.transient_failure_since: datetime | None = None
        self.transient_failure_count = 0
        self.transient_status_note: str | None = None
        self.update_info: UpdateInfo | None = None
        self.update_check_running = False
        self.status_text = "обновление"
        self.drag_x = 0
        self.drag_y = 0
        self.drag_start_pointer_x = 0
        self.drag_start_pointer_y = 0
        self.drag_start_window_x = 0
        self.drag_start_window_y = 0
        self.drag_pending_position: tuple[int, int] | None = None
        self.drag_after_id: str | None = None
        self.dragging = False
        self.menu_window: tk.Toplevel | None = None
        self.tooltip_window: tk.Toplevel | None = None
        self.tooltip_text_by_tag: dict[str, str] = {}
        self.position_after_id: str | None = None

        self.root = tk.Tk()
        self.root.title("NeuroGate API 1.7.2")
        self.root.geometry(self._initial_geometry())
        self.root.overrideredirect(True)
        self.root.attributes("-topmost", True)
        self.root.attributes("-alpha", 0.96)
        self.root.configure(bg="#0b0d12")
        self.root.protocol("WM_DELETE_WINDOW", self.close)

        self.canvas = tk.Canvas(
            self.root,
            width=self._scaled_width(),
            height=self._scaled_height(),
            highlightthickness=0,
            bd=0,
            bg="#0b0d12",
        )
        self.canvas.pack(fill="both", expand=True)

        self._bind_window()
        self._render()
        self.root.after(200, self.refresh)
        self.root.after(1200, self.check_for_updates)
        self._schedule_resume_watchdog()

    def _bind_window(self) -> None:
        self.root.bind("<ButtonPress-1>", self._start_drag)
        self.root.bind("<B1-Motion>", self._drag)
        self.root.bind("<ButtonRelease-1>", self._end_drag)
        self.root.bind("<Button-3>", self._show_menu)
        self.root.bind("<Configure>", self._remember_window_position_soon)
        self.root.bind("<Escape>", lambda _event: self.close())
        self.root.bind("<Control-r>", lambda _event: self.refresh(force=True))
        self.canvas.tag_bind("interval", "<Button-1>", lambda _event: self._cycle_interval())
        self.canvas.tag_bind("tooltip-target", "<Enter>", self._show_bound_tooltip)
        self.canvas.tag_bind("tooltip-target", "<Motion>", self._move_tooltip)
        self.canvas.tag_bind("tooltip-target", "<Leave>", lambda _event: self._hide_tooltip())
        self.canvas.tag_bind("daily-limit-row", "<Double-Button-1>", lambda _event: self._edit_daily_limit())

    def _start_drag(self, event: tk.Event) -> None:
        self._hide_menu()
        self._hide_tooltip()
        self.drag_x = event.x
        self.drag_y = event.y
        self.drag_start_pointer_x = int(getattr(event, "x_root", event.x))
        self.drag_start_pointer_y = int(getattr(event, "y_root", event.y))
        self.drag_start_window_x = self.root.winfo_x()
        self.drag_start_window_y = self.root.winfo_y()
        self.drag_pending_position = None
        self.dragging = True
        if self.position_after_id:
            try:
                self.root.after_cancel(self.position_after_id)
            except Exception:  # noqa: BLE001 - a stale timer must not break dragging.
                pass
            self.position_after_id = None

    def _drag(self, event: tk.Event) -> None:
        pointer_x = int(getattr(event, "x_root", event.x))
        pointer_y = int(getattr(event, "y_root", event.y))
        x = self.drag_start_window_x + pointer_x - self.drag_start_pointer_x
        y = self.drag_start_window_y + pointer_y - self.drag_start_pointer_y
        self.drag_pending_position = (x, y)
        if self.drag_after_id:
            return
        self.drag_after_id = self.root.after(self.DRAG_FRAME_MS, self._apply_pending_drag)

    def _apply_pending_drag(self) -> None:
        self.drag_after_id = None
        if not self.drag_pending_position:
            return
        x, y = self.drag_pending_position
        self.drag_pending_position = None
        self.root.geometry(f"+{x}+{y}")

    def _end_drag(self, _event: tk.Event) -> None:
        if self.drag_after_id:
            try:
                self.root.after_cancel(self.drag_after_id)
            except Exception:  # noqa: BLE001 - a stale timer must not break drag release.
                pass
            self.drag_after_id = None
        self._apply_pending_drag()
        self.dragging = False
        self._save_window_position()

    def _initial_geometry(self) -> str:
        x, y = self._load_window_position()
        x, y = self._clamp_position(x, y, self.root.winfo_screenwidth(), self.root.winfo_screenheight())
        return f"{self._scaled_width()}x{self._scaled_height()}+{x}+{y}"

    def _current_scale(self) -> int:
        return int(getattr(self, "ui_scale", self.SCALE_NORMAL))

    def _scaled_width(self) -> int:
        return self.WIDTH * self._current_scale()

    def _scaled_height(self) -> int:
        return self._content_height() * self._current_scale()

    def _content_height(self) -> int:
        return self.DAILY_LIMIT_HEIGHT if self._daily_limit_enabled() else self.HEIGHT

    def _s(self, value: float) -> int:
        return int(round(value * self._current_scale()))

    def _font_size(self, size: int) -> int:
        return max(1, int(round(size * self._current_scale())))

    def _load_state(self) -> dict[str, object]:
        try:
            payload = json.loads(self.state_file.read_text(encoding="utf-8"))
            return payload if isinstance(payload, dict) else {}
        except Exception:
            return {}

    def _save_state(self, updates: dict[str, object]) -> None:
        try:
            payload = self._load_state()
            payload.update(updates)
            self.state_file.parent.mkdir(parents=True, exist_ok=True)
            self.state_file.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        except Exception as exc:  # noqa: BLE001 - user preferences must not break the overlay.
            self._write_ui_log(f"save_state_error {exc!r}")

    def _load_window_position(self) -> tuple[int, int]:
        try:
            payload = self._load_state()
            return int(payload.get("x", 32)), int(payload.get("y", 72))
        except Exception:
            return 32, 72

    def _load_interval_minutes(self, default: int) -> int:
        try:
            payload = self._load_state()
            return self._normalize_interval_minutes(int(payload.get("interval_minutes", default)))
        except Exception:
            return self._normalize_interval_minutes(default)

    def _save_interval_minutes(self) -> None:
        self._save_state({"interval_minutes": self.interval_minutes})

    def _load_ui_scale(self) -> int:
        try:
            payload = self._load_state()
            scale = int(payload.get("ui_scale", self.SCALE_NORMAL))
            return self.SCALE_LARGE if scale == self.SCALE_LARGE else self.SCALE_NORMAL
        except Exception:
            return self.SCALE_NORMAL

    def _save_ui_scale(self) -> None:
        self._save_state({"ui_scale": self.ui_scale})

    def _load_daily_limit_credits(self) -> int | None:
        try:
            payload = self._load_state()
            value = int(payload.get("daily_limit_credits") or 0)
            if 0 < value < 1_000_000:
                value *= 1_000_000
            return value if value > 0 else None
        except Exception:
            return None

    def _load_daily_limit_set_at(self) -> datetime | None:
        try:
            payload = self._load_state()
            value = payload.get("daily_limit_set_at")
            if not isinstance(value, str):
                return None
            parsed = datetime.fromisoformat(value)
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=datetime.now().astimezone().tzinfo)
            return parsed
        except Exception:
            return None

    def _save_daily_limit_credits(self) -> None:
        self._save_state(
            {
                "daily_limit_credits": self.daily_limit_credits or None,
                "daily_limit_set_at": self.daily_limit_set_at.isoformat(timespec="seconds")
                if self.daily_limit_credits and self.daily_limit_set_at
                else None,
            }
        )

    def _daily_limit_enabled(self) -> bool:
        return bool(getattr(self, "daily_limit_credits", None)) and not self._daily_limit_expired()

    def _daily_limit_expired(self) -> bool:
        set_at = getattr(self, "daily_limit_set_at", None)
        if not getattr(self, "daily_limit_credits", None):
            return False
        if not set_at:
            return True
        now = datetime.now().astimezone()
        set_at_local = set_at.astimezone(now.tzinfo) if set_at.tzinfo else set_at.replace(tzinfo=now.tzinfo)
        return set_at_local.date() != now.date()

    def _expire_daily_limit_if_needed(self) -> bool:
        if not self._daily_limit_expired():
            return False
        self.daily_limit_credits = None
        self.daily_limit_set_at = None
        self._save_daily_limit_credits()
        return True

    def _save_window_position(self) -> None:
        try:
            self._save_state({"x": self.root.winfo_x(), "y": self.root.winfo_y()})
        except Exception as exc:  # noqa: BLE001 - position persistence must not break dragging.
            self._write_ui_log(f"save_window_position_error {exc!r}")

    def _remember_window_position_soon(self, event: tk.Event | None = None) -> None:
        if event is not None and event.widget is not self.root:
            return
        if getattr(self, "dragging", False):
            return
        try:
            if self.position_after_id:
                self.root.after_cancel(self.position_after_id)
            self.position_after_id = self.root.after(400, self._save_window_position_after_configure)
        except Exception as exc:  # noqa: BLE001 - position persistence must never affect UI.
            self._write_ui_log(f"schedule_window_position_save_error {exc!r}")

    def _save_window_position_after_configure(self) -> None:
        self.position_after_id = None
        self._save_window_position()

    def _clamp_position(self, x: int, y: int, screen_width: int, screen_height: int) -> tuple[int, int]:
        margin = 8
        max_x = max(margin, screen_width - self._scaled_width() - margin)
        max_y = max(margin, screen_height - self._scaled_height() - margin)
        return max(margin, min(x, max_x)), max(margin, min(y, max_y))

    def _show_menu(self, event: tk.Event) -> None:
        self._hide_menu()
        if self._expire_daily_limit_if_needed():
            self._resize_window_to_scale()
            self._render()

        item_height = 24
        padding = 6
        width = 160
        keep_browser_open = self._keep_browser_open()
        keep_browser_label = "Не закрывать ЛК"
        scale_label = "2x размер"
        daily_limit_label = "Скрыть лимит в день" if self._daily_limit_enabled() else "Задать лимит на день"
        checkbox_labels = {keep_browser_label, scale_label}
        rows: list[tuple[str, Callable[[], None] | None, bool]] = [
            ("Обновить лимиты", lambda: self.refresh(force=True), False),
            (
                daily_limit_label,
                self._hide_daily_limit if self._daily_limit_enabled() else self._show_daily_limit_dialog,
                False,
            ),
            ("", None, False),
            (
                keep_browser_label,
                self._toggle_keep_browser_open if self._has_keep_browser_toggle() else None,
                keep_browser_open,
            ),
            (
                scale_label,
                self._toggle_ui_scale,
                self.ui_scale == self.SCALE_LARGE,
            ),
            ("", None, False),
            *[
                (
                    self._format_interval_menu(minutes),
                    lambda value=minutes: self.set_interval(value),
                    minutes == self.interval_minutes,
                )
                for minutes in self.INTERVAL_CHOICES_MINUTES
            ],
        ]
        if self.update_info:
            rows.extend(
                [
                    ("", None, False),
                    (f"Доступна {self.update_info.latest_label}", None, False),
                    (f"Обновить до {self.update_info.latest_label}", self._start_update, False),
                ]
            )
        rows.extend(
            [
                ("", None, False),
                ("Сменить аккаунт", self._reset_account if self.account_resetter else None, False),
                ("Закрыть", self.close, False),
            ]
        )
        height = padding * 2 + sum(8 if not label else item_height for label, _command, _active in rows)

        menu = tk.Toplevel(self.root)
        self.menu_window = menu
        menu.overrideredirect(True)
        menu.attributes("-topmost", True)
        menu.attributes("-alpha", 0.97)
        menu.configure(bg="#0d1118", bd=0, highlightthickness=0)
        menu.geometry(f"{width}x{height}+{event.x_root}+{event.y_root}")

        canvas = tk.Canvas(menu, width=width, height=height, highlightthickness=0, bd=0, bg="#0d1118")
        canvas.pack(fill="both", expand=True)
        canvas.create_rectangle(0, 0, width, height, fill="#0f151f", outline="")

        y = padding
        for index, (label, command, active) in enumerate(rows):
            if not label:
                canvas.create_line(10, y + 3, width - 10, y + 3, fill="#202a36")
                y += 8
                continue

            tag = f"item-{index}"
            bg_tag = f"item-bg-{index}"
            fill = "#182333" if active else "#0f151f"
            canvas.create_rectangle(4, y, width - 4, y + item_height, fill=fill, outline="", tags=(tag, bg_tag))
            text_x = 14
            if label in checkbox_labels:
                text_x = 34
                box_x = 14
                box_y = y + 7
                canvas.create_rectangle(
                    box_x,
                    box_y,
                    box_x + 10,
                    box_y + 10,
                    fill="#101722",
                    outline="#3a4656",
                    width=1,
                    tags=tag,
                )
                if active:
                    canvas.create_line(
                        box_x + 2,
                        box_y + 5,
                        box_x + 5,
                        box_y + 8,
                        box_x + 9,
                        box_y + 2,
                        fill="#76a8ff",
                        width=2,
                        tags=tag,
                    )
            canvas.create_text(
                text_x,
                y + item_height // 2,
                text=label,
                fill="#f4f7fb" if not active else "#76a8ff",
                font=(self.UI_FONT, 8, "normal"),
                anchor="w",
                tags=tag,
            )
            if active:
                canvas.create_oval(width - 18, y + 9, width - 12, y + 15, fill="#76a8ff", outline="", tags=tag)

            def run_action(action: Callable[[], None] | None = command) -> None:
                self._hide_menu()
                if action:
                    action()

            canvas.tag_bind(tag, "<Enter>", lambda _event, bg_tag=bg_tag: canvas.itemconfigure(bg_tag, fill="#1b2635"))
            canvas.tag_bind(tag, "<Leave>", lambda _event, bg_tag=bg_tag, fill=fill: canvas.itemconfigure(bg_tag, fill=fill))
            canvas.tag_bind(tag, "<Button-1>", lambda _event, action=run_action: action())
            y += item_height

        menu.bind("<Escape>", lambda _event: self._hide_menu())
        menu.bind("<FocusOut>", lambda _event: self._hide_menu())
        menu.focus_force()

    def _hide_menu(self) -> None:
        if not self.menu_window:
            return
        try:
            self.menu_window.destroy()
        except tk.TclError:
            pass
        self.menu_window = None

    def _show_tooltip(self, event: tk.Event, text: str | None) -> None:
        if not text:
            return
        self._hide_tooltip()

        tooltip = tk.Toplevel(self.root)
        self.tooltip_window = tooltip
        tooltip.overrideredirect(True)
        tooltip.attributes("-topmost", True)
        tooltip.attributes("-alpha", 0.97)
        tooltip.configure(bg="#0d1118", bd=0, highlightthickness=0)

        label = tk.Label(
            tooltip,
            text=text,
            bg="#0f151f",
            fg="#f4f7fb",
            font=(self.UI_FONT, self._font_size(8), "normal"),
            padx=self._s(8),
            pady=self._s(5),
            bd=max(1, self._s(1)),
            relief="solid",
            highlightthickness=max(1, self._s(1)),
            highlightbackground="#303946",
        )
        label.pack()
        tooltip.update_idletasks()

        x = event.x_root + 8
        y = event.y_root + 12
        width = tooltip.winfo_reqwidth()
        height = tooltip.winfo_reqheight()
        screen_width = self.root.winfo_screenwidth()
        screen_height = self.root.winfo_screenheight()
        x = max(8, min(x, screen_width - width - 8))
        y = max(8, min(y, screen_height - height - 8))
        tooltip.geometry(f"+{x}+{y}")

    def _tooltip_text_for_event(self, event: tk.Event) -> str | None:
        try:
            current_items = event.widget.find_withtag("current")
            if not current_items:
                return None
            for tag in event.widget.gettags(current_items[0]):
                text = self.tooltip_text_by_tag.get(tag)
                if text:
                    return text
        except Exception:  # noqa: BLE001 - tooltip lookup must never affect the overlay.
            return None
        return None

    def _show_bound_tooltip(self, event: tk.Event) -> None:
        self._show_tooltip(event, self._tooltip_text_for_event(event))

    def _move_tooltip(self, event: tk.Event) -> None:
        if not self.tooltip_window:
            return
        x = event.x_root + 8
        y = event.y_root + 12
        width = self.tooltip_window.winfo_reqwidth()
        height = self.tooltip_window.winfo_reqheight()
        screen_width = self.root.winfo_screenwidth()
        screen_height = self.root.winfo_screenheight()
        x = max(8, min(x, screen_width - width - 8))
        y = max(8, min(y, screen_height - height - 8))
        self.tooltip_window.geometry(f"+{x}+{y}")

    def _hide_tooltip(self) -> None:
        if not self.tooltip_window:
            return
        try:
            self.tooltip_window.destroy()
        except tk.TclError:
            pass
        self.tooltip_window = None

    def _cycle_interval(self) -> None:
        if self.interval_minutes not in self.INTERVAL_CHOICES_MINUTES:
            self.interval_minutes = self.INTERVAL_CHOICES_MINUTES[0]
        index = self.INTERVAL_CHOICES_MINUTES.index(self.interval_minutes)
        self.set_interval(self.INTERVAL_CHOICES_MINUTES[(index + 1) % len(self.INTERVAL_CHOICES_MINUTES)])

    def _has_keep_browser_toggle(self) -> bool:
        return bool(self.keep_browser_open_getter and self.keep_browser_open_setter)

    def _keep_browser_open(self) -> bool:
        if not self.keep_browser_open_getter:
            return False
        try:
            return self.keep_browser_open_getter()
        except Exception as exc:  # noqa: BLE001 - keep the menu usable if browser state is unavailable.
            self._write_ui_log(f"keep_browser_open_getter_error {exc!r}")
            return False

    def _toggle_keep_browser_open(self) -> None:
        if not self.keep_browser_open_setter:
            return
        enabled = not self._keep_browser_open()
        try:
            self.keep_browser_open_setter(enabled)
        except Exception as exc:  # noqa: BLE001 - show operational errors without crashing.
            self._apply_error(exc)
            return
        self._render()

    def _toggle_ui_scale(self) -> None:
        self.ui_scale = self.SCALE_NORMAL if self.ui_scale == self.SCALE_LARGE else self.SCALE_LARGE
        self._save_ui_scale()
        self._hide_tooltip()
        self._resize_window_to_scale()
        self._render()

    def _daily_limit_dialog_default_credits(self) -> int | None:
        if self._daily_limit_enabled():
            return self.daily_limit_credits
        return self._default_daily_limit_credits()

    def _edit_daily_limit(self) -> None:
        self._hide_tooltip()
        if self._expire_daily_limit_if_needed():
            self._resize_window_to_scale()
            self._render()
            return
        self._show_daily_limit_dialog()

    def _show_daily_limit_dialog(self) -> None:
        self._hide_tooltip()
        dialog = tk.Toplevel(self.root)
        dialog.overrideredirect(True)
        dialog.attributes("-topmost", True)
        dialog.attributes("-alpha", 0.98)
        dialog.configure(bg="#0d1118", bd=0, highlightthickness=0)

        width = self._s(210)
        height = self._s(92)
        x = self.root.winfo_x() + self._s(8)
        y = self.root.winfo_y() + self._s(22)
        dialog.geometry(f"{width}x{height}+{x}+{y}")

        canvas = tk.Canvas(dialog, width=width, height=height, highlightthickness=0, bd=0, bg="#0d1118")
        canvas.pack(fill="both", expand=True)
        scale = self._current_scale()
        canvas.create_rectangle(0, 0, width, height, fill="#0f151f", outline="")
        canvas.create_text(
            self._s(12),
            self._s(11),
            text="Лимит на день",
            fill="#76a8ff",
            font=(self.UI_FONT, self._font_size(9), "normal"),
            anchor="nw",
        )
        canvas.create_text(
            self._s(12),
            self._s(30),
            text="Например: 82M",
            fill="#8793a4",
            font=(self.UI_FONT, self._font_size(8), "normal"),
            anchor="nw",
        )

        default_value = self._daily_limit_dialog_default_credits()
        value = tk.StringVar(value=short_number(default_value) if default_value else "")
        canvas.create_rectangle(
            self._s(12),
            self._s(49),
            self._s(104),
            self._s(73),
            fill="#1a222d",
            outline="#303946",
            width=max(1, self._s(1)),
        )
        entry = tk.Entry(
            dialog,
            textvariable=value,
            bg="#1a222d",
            fg="#f4f7fb",
            insertbackground="#76a8ff",
            relief="flat",
            bd=0,
            highlightthickness=0,
            font=(self.NUMBER_FONT, self._font_size(11), "bold"),
            justify="center",
        )
        entry.place(x=self._s(15), y=self._s(51), width=self._s(86), height=self._s(20))

        error_var = tk.StringVar(value="")
        error_label = tk.Label(
            dialog,
            textvariable=error_var,
            bg="#0f151f",
            fg="#ff4d5d",
            font=(self.UI_FONT, self._font_size(7), "normal"),
        )
        error_label.place(x=self._s(12), y=self._s(74), width=self._s(186), height=self._s(13))

        def close_dialog() -> None:
            try:
                dialog.destroy()
            except tk.TclError:
                pass

        def save_limit() -> None:
            parsed = self._parse_credit_input(value.get())
            if parsed is None:
                error_var.set("Введите число: 82M или 82000000")
                return
            self.daily_limit_credits = parsed
            self.daily_limit_set_at = datetime.now().astimezone()
            self._save_daily_limit_credits()
            close_dialog()
            self._resize_window_to_scale()
            self._render()

        ok = tk.Label(
            dialog,
            text="OK",
            bg="#1a222d",
            fg="#76a8ff",
            font=(self.UI_FONT, self._font_size(8), "normal"),
            padx=0,
            pady=0,
        )
        ok.place(x=self._s(116), y=self._s(49), width=self._s(36), height=self._s(24))
        ok.bind("<Button-1>", lambda _event: save_limit())
        cancel = tk.Label(
            dialog,
            text="Отмена",
            bg="#1a222d",
            fg="#9aa8ba",
            font=(self.UI_FONT, self._font_size(8), "normal"),
            padx=0,
            pady=0,
        )
        cancel.place(x=self._s(158), y=self._s(49), width=self._s(40), height=self._s(24))
        cancel.bind("<Button-1>", lambda _event: close_dialog())

        dialog.bind("<Return>", lambda _event: save_limit())
        dialog.bind("<Escape>", lambda _event: close_dialog())
        entry.focus_force()
        entry.selection_range(0, tk.END)

        # Keep pyright quiet when Tk scaling is 1; the variable is useful for future geometry tweaks.
        _ = scale

    def _hide_daily_limit(self) -> None:
        self.daily_limit_credits = None
        self.daily_limit_set_at = None
        self._save_daily_limit_credits()
        self._hide_tooltip()
        self._resize_window_to_scale()
        self._render()

    def _resize_window_to_scale(self) -> None:
        width = self._scaled_width()
        height = self._scaled_height()
        x, y = self._clamp_position(
            self.root.winfo_x(),
            self.root.winfo_y(),
            self.root.winfo_screenwidth(),
            self.root.winfo_screenheight(),
        )
        self.canvas.configure(width=width, height=height)
        self.root.geometry(f"{width}x{height}+{x}+{y}")

    def _reset_account(self) -> None:
        if not self.account_resetter:
            return
        try:
            self.account_resetter()
        except Exception as exc:  # noqa: BLE001 - show reset errors without crashing the overlay.
            self._apply_error(exc)
            return
        self._clear_transient_failure()
        self.last_snapshot = UsageSnapshot(updated_at=datetime.now().astimezone(), status_note="нужен вход")
        self.status_text = "нужен вход"
        self._schedule_next_refresh()
        self._render()

    def check_for_updates(self) -> None:
        if self.update_check_running:
            return
        self.update_check_running = True

        def run_check() -> None:
            info = check_for_update()

            def apply_result() -> None:
                self.update_check_running = False
                self.update_info = info
                self._render()
                self.root.after(self.UPDATE_CHECK_SECONDS * 1000, self.check_for_updates)

            try:
                self.root.after(0, apply_result)
            except tk.TclError:
                self.update_check_running = False

        threading.Thread(target=run_check, daemon=True).start()

    def _start_update(self) -> None:
        if not self.update_info:
            return

        scripts_dir = Path(__file__).resolve().parents[2] / "scripts"
        if sys.platform.startswith("win"):
            script = scripts_dir / "update-and-restart.ps1"
            cmd = [
                "powershell.exe",
                "-ExecutionPolicy",
                "Bypass",
                "-File",
                str(script),
                "-TargetVersion",
                self.update_info.latest_label,
            ]
            if self.update_info.release_zip_url:
                cmd += ["-ReleaseZipUrl", self.update_info.release_zip_url]
            if self.update_info.release_sha256:
                cmd += ["-ReleaseSha256", self.update_info.release_sha256]
            extra_kwargs: dict = {"creationflags": getattr(subprocess, "CREATE_NEW_CONSOLE", 0)}
        else:
            script = scripts_dir / "update-and-restart.sh"
            cmd = ["bash", str(script), "--target-version", self.update_info.latest_label]
            if self.update_info.release_zip_url:
                cmd += ["--release-zip-url", self.update_info.release_zip_url]
            if self.update_info.release_sha256:
                cmd += ["--release-sha256", self.update_info.release_sha256]
            extra_kwargs = {}

        if not script.exists():
            self._apply_error("скрипт обновления не найден")
            return
        try:
            subprocess.Popen(cmd, cwd=str(scripts_dir.parent), **extra_kwargs)
        except Exception as exc:  # noqa: BLE001 - show update launch errors in the overlay.
            self._apply_error(exc)
            return
        self.close()

    def set_interval(self, minutes: int) -> None:
        self.interval_minutes = self._normalize_interval_minutes(minutes)
        self._save_interval_minutes()
        self._schedule_next_refresh()
        self._render()

    @classmethod
    def _normalize_interval_minutes(cls, minutes: int) -> int:
        if minutes in cls.INTERVAL_CHOICES_MINUTES:
            return minutes
        return cls.INTERVAL_CHOICES_MINUTES[0]

    @staticmethod
    def _format_interval_menu(minutes: int) -> str:
        if minutes >= 60 and minutes % 60 == 0:
            hours = minutes // 60
            return f"{hours} час" if hours == 1 else f"{hours} ч"
        return f"{minutes} мин"

    @staticmethod
    def _format_interval_pill(minutes: int) -> str:
        if minutes >= 60 and minutes % 60 == 0:
            return f"{minutes // 60}ч"
        return f"{minutes}м"

    @staticmethod
    def _parse_credit_input(value: str) -> int | None:
        cleaned = value.strip().lower().replace(",", ".").replace(" ", "")
        if not cleaned:
            return None
        multiplier = 1
        suffixes = (
            ("млрд", 1_000_000_000),
            ("b", 1_000_000_000),
            ("млн", 1_000_000),
            ("m", 1_000_000),
            ("м", 1_000_000),
            ("тыс", 1_000),
            ("k", 1_000),
            ("к", 1_000),
        )
        for suffix, suffix_multiplier in suffixes:
            if cleaned.endswith(suffix):
                cleaned = cleaned[: -len(suffix)]
                multiplier = suffix_multiplier
                break
        try:
            amount = float(cleaned)
        except ValueError:
            return None
        if multiplier == 1 and amount < 1_000_000:
            multiplier = 1_000_000
        credits = round(amount * multiplier)
        return credits if credits > 0 else None

    @staticmethod
    def _remaining_plan_days(plan_status: str | None) -> float | None:
        if not plan_status:
            return None
        text = plan_status.lower().replace("ё", "е")
        days = 0.0
        patterns = (
            (r"(\d+(?:[.,]\d+)?)\s*(?:д|дн|дня|дней|день)", 1.0),
            (r"(\d+(?:[.,]\d+)?)\s*(?:ч|час|часа|часов)", 1.0 / 24.0),
            (r"(\d+(?:[.,]\d+)?)\s*(?:м|мин|минут|минуты)", 1.0 / (24.0 * 60.0)),
        )
        for pattern, multiplier in patterns:
            for match in re.finditer(pattern, text):
                days += float(match.group(1).replace(",", ".")) * multiplier
        if days <= 0:
            return None
        return days

    def _default_daily_limit_credits(self) -> int | None:
        if not self.last_snapshot:
            return None
        window = find_window(self.last_snapshot, "7d") or self._window_by_index(1)
        if not window or window.credits_remaining is None:
            return None
        days = self._remaining_plan_days(window.reset_text) or self._remaining_plan_days(self.last_snapshot.plan_status) or 1
        return max(1, round(window.credits_remaining / days))

    def _schedule_next_refresh(self) -> None:
        if self.after_id:
            self.root.after_cancel(self.after_id)
        delay_ms = self.interval_minutes * 60 * 1000
        if self._has_pending_transient_failure() or (self.last_snapshot and not self.last_snapshot.has_data):
            delay_ms = self.LOGIN_POLL_SECONDS * 1000
        self.after_id = self.root.after(delay_ms, self.refresh)

    def _schedule_resume_watchdog(self) -> None:
        if self.resume_after_id:
            self.root.after_cancel(self.resume_after_id)
        self.resume_after_id = self.root.after(self.RESUME_HEARTBEAT_SECONDS * 1000, self._check_resume_watchdog)

    def _check_resume_watchdog(self) -> None:
        now = datetime.now().astimezone()
        previous = self.last_resume_check_at
        self.last_resume_check_at = now
        try:
            if previous and now - previous >= timedelta(seconds=self.RESUME_GAP_SECONDS):
                self._write_ui_log(f"resume_gap_detected seconds={(now - previous).total_seconds():.0f}")
                self.last_refresh_at = None
                if not self.refreshing:
                    self.refresh(force=True)
        finally:
            self._schedule_resume_watchdog()

    def _has_displayable_data(self) -> bool:
        return bool(self.last_snapshot and self.last_snapshot.has_data)

    def _has_pending_transient_failure(self) -> bool:
        return self._has_displayable_data() and getattr(self, "transient_failure_count", 0) > 0

    def _stable_status_text(self) -> str:
        if self.last_snapshot and self.last_snapshot.has_data:
            return f"обн. {self.last_snapshot.updated_at.strftime('%H:%M')}"
        return self.status_text

    def _clear_transient_failure(self) -> None:
        self.transient_failure_since = None
        self.transient_failure_count = 0
        self.transient_status_note = None

    def _hold_transient_failure(self, status_note: str | None, now: datetime) -> bool:
        if not self._has_displayable_data():
            return False
        if getattr(self, "transient_failure_since", None) is None:
            self.transient_failure_since = now
            self.transient_failure_count = 0
        self.transient_failure_count += 1
        self.transient_status_note = status_note or "нет данных"
        elapsed = now - self.transient_failure_since
        should_confirm = (
            self.transient_failure_count >= self.TRANSIENT_FAILURE_CONFIRMATIONS
            and elapsed >= timedelta(seconds=self.TRANSIENT_FAILURE_GRACE_SECONDS)
        )
        if should_confirm:
            return False
        self.status_text = self._stable_status_text()
        self._write_ui_log(
            f"transient_failure_held count={self.transient_failure_count} "
            f"status={self.transient_status_note!r}"
        )
        return True

    def _rounded_rect(
        self,
        x1: int,
        y1: int,
        x2: int,
        y2: int,
        radius: int,
        fill: str,
        outline: str = "",
        width: int = 1,
        tags: str | tuple[str, ...] = (),
    ) -> None:
        points = [
            x1 + radius,
            y1,
            x2 - radius,
            y1,
            x2,
            y1,
            x2,
            y1 + radius,
            x2,
            y2 - radius,
            x2,
            y2,
            x2 - radius,
            y2,
            x1 + radius,
            y2,
            x1,
            y2,
            x1,
            y2 - radius,
            x1,
            y1 + radius,
            x1,
            y1,
        ]
        self.canvas.create_polygon(
            [self._s(point) for point in points],
            smooth=True,
            splinesteps=12 * self._current_scale(),
            fill=fill,
            outline=outline,
            width=max(1, self._s(width)),
            tags=tags,
        )

    def _text(
        self,
        x: int,
        y: int,
        text: str,
        fill: str = "#f4f7fb",
        size: int = 9,
        weight: str = "normal",
        anchor: str = "nw",
        tags: str | tuple[str, ...] = (),
        family: str | None = None,
    ) -> None:
        self.canvas.create_text(
            self._s(x),
            self._s(y),
            text=text,
            fill=fill,
            font=(family or self.TEXT_FONT, self._font_size(size), weight),
            anchor=anchor,
            tags=tags,
        )

    def _measure_text(self, text: str, size: int = 8, weight: str = "normal", family: str | None = None) -> int:
        item = self.canvas.create_text(
            -1000,
            -1000,
            text=text,
            font=(family or self.TEXT_FONT, self._font_size(size), weight),
            anchor="nw",
        )
        bbox = self.canvas.bbox(item)
        self.canvas.delete(item)
        if not bbox:
            return 0
        return math.ceil((bbox[2] - bbox[0]) / self._current_scale())

    def _progress(self, x: int, y: int, width: int, percent: float | None, tags: str | tuple[str, ...] = ()) -> None:
        self._rounded_rect(x, y, x + width, y + 3, 2, "#242932", tags=tags)
        if percent is None:
            return
        fill_width = min(width, max(0, int(width * max(0.0, min(1.0, percent / 100)))))
        if fill_width > 0:
            self._rounded_rect(x, y, x + fill_width, y + 3, 2, "#76a8ff", tags=tags)

    @staticmethod
    def _mix_color(start: str, end: str, amount: float) -> str:
        amount = max(0.0, min(1.0, amount))
        start_rgb = tuple(int(start[index : index + 2], 16) for index in (1, 3, 5))
        end_rgb = tuple(int(end[index : index + 2], 16) for index in (1, 3, 5))
        mixed = tuple(round(start_rgb[index] + (end_rgb[index] - start_rgb[index]) * amount) for index in range(3))
        return f"#{mixed[0]:02x}{mixed[1]:02x}{mixed[2]:02x}"

    def _daily_progress_color(self, percent: float) -> str:
        if percent <= 50:
            return "#76a8ff"
        if percent >= 100:
            return "#ff4d5d"
        if percent <= 75:
            return self._mix_color("#ffd166", "#ff9f1c", (percent - 50.0) / 25.0)
        return self._mix_color("#ff9f1c", "#ff4d5d", (percent - 75.0) / 25.0)

    def _daily_progress(self, x: int, y: int, width: int, percent: float | None, tags: str | tuple[str, ...] = ()) -> None:
        if percent is not None and percent >= 100:
            self._rounded_rect(x - 2, y - 1, x + width + 2, y + 4, 3, "#3a1e26", tags=tags)
        self._rounded_rect(x, y, x + width, y + 3, 2, "#242932", tags=tags)
        if percent is None:
            return
        fill_width = min(width, max(0, int(width * max(0.0, min(1.0, percent / 100)))))
        if fill_width <= 0:
            return
        color = self._daily_progress_color(percent)
        self._rounded_rect(x, y, x + fill_width, y + 3, 2, color, tags=tags)

    def _window_progress_percent(self, window: UsageWindow | None) -> float | None:
        if not window:
            return None
        if window.progress_percent is not None:
            return window.progress_percent
        return window.limit_percent

    def _window_by_index(self, index: int) -> UsageWindow | None:
        if not self.last_snapshot:
            return None
        if len(self.last_snapshot.windows) <= index:
            return None
        return self.last_snapshot.windows[index]

    def _compact_window_title(self, window: UsageWindow | None, fallback: str) -> str:
        if not window:
            return fallback
        title = window.title.lower()
        if "5" in title and "час" in title:
            return "5ч"
        if "24" in title and "час" in title:
            return "24ч"
        if "7" in title and "д" in title:
            return "7д"
        return fallback

    def _limit_tooltip_text(self, label: str, window: UsageWindow | None) -> str | None:
        if not window:
            return None
        if label == "5ч":
            spent = spent_since_reset(window)
            value = short_number(spent) if spent is not None else "нет данных"
            return f"Потрачено со сброса: {value}"
        if label == "7д" and self.last_snapshot:
            today_spent = self.daily_usage.today_spent_7d(self.last_snapshot)
            value = short_number(today_spent.amount) if today_spent is not None else "нет данных"
            since = today_spent.since_text if today_spent is not None else "--:--"
            if since == "00:00" or since == "--:--":
                return f"сегодня потрачено: {value}"
            return f"сегодня потрачено с {since}: {value}"
        return None

    def _draw_limit_row(self, y: int, fallback_label: str, window: UsageWindow | None) -> None:
        label = self._compact_window_title(window, fallback_label)
        value = format_credits(window.display_value if window else None)
        reset = compact_reset_text(window.reset_text if window else None)
        percent = self._window_progress_percent(window)
        tooltip = self._limit_tooltip_text(label, window)
        value_tag = f"limit-value-{window_key(window) or fallback_label}"
        value_tags: str | tuple[str, ...] = value_tag
        if tooltip:
            self.tooltip_text_by_tag[value_tag] = tooltip
            value_tags = (value_tag, "tooltip-target")

        self._text(9, y, label, "#9aa8ba", 9, "normal", family=self.UI_FONT)
        self._text(31, y, "остаток", "#667386", 8, "normal", family=self.UI_FONT)
        self.canvas.create_rectangle(
            self._s(92),
            self._s(y + 1),
            self._s(158),
            self._s(y + 16),
            fill="#101722",
            outline="",
            tags=value_tags,
        )
        self._text(124, y + 8, value, "#ffb86b", 10, "bold", "center", tags=value_tags, family=self.NUMBER_FONT)
        self._text(214, y + 2, reset, "#8793a4", 8, "normal", "ne", family=self.UI_FONT)
        self._progress(30, y + 17, 184, percent)

    def _daily_limit_values(self) -> tuple[int, int, int, float] | None:
        if not self._daily_limit_enabled() or not self.last_snapshot:
            return None
        limit = self.daily_limit_credits
        if not limit:
            return None
        today_spent = self.daily_usage.today_spent_7d(self.last_snapshot)
        spent = today_spent.amount if today_spent is not None else 0
        window = find_window(self.last_snapshot, "7d") or self._window_by_index(1)
        floor = max(0, (window.credits_remaining if window and window.credits_remaining is not None else 0) - limit)
        percent = min(999.0, (spent / limit) * 100)
        return spent, limit, floor, percent

    def _daily_limit_hint(self) -> str:
        values = self._daily_limit_values()
        if not values:
            return "нет данных"
        _spent, _limit, floor, _percent = values
        return f"не падаем ниже {short_number_clean(floor)}"

    def _draw_daily_limit_row(self, y: int) -> None:
        values = self._daily_limit_values()
        if not values:
            return
        spent, limit, floor, percent = values
        value = f"{short_number_clean(spent)} / {short_number_clean(limit)}"
        percent_text = compact_percent(percent)
        tooltip = self._daily_limit_hint()
        row_tag = "daily-limit-row"
        value_tag = "daily-limit-value"
        percent_tag = "daily-limit-percent"
        color = "#ff4d5d" if percent >= 100 else "#ffe082"
        percent_color = "#8793a4"
        value_x = self._daily_limit_value_x()
        self.tooltip_text_by_tag[value_tag] = tooltip

        self.canvas.create_rectangle(
            self._s(4),
            self._s(y - 2),
            self._s(self.WIDTH - 4),
            self._s(y + 21),
            fill="#101722",
            outline="",
            tags=row_tag,
        )
        self._text(9, y, "лимит/день", "#667386", 8, "normal", tags=row_tag, family=self.UI_FONT)
        self.canvas.create_rectangle(
            self._s(value_x - 4),
            self._s(y + 1),
            self._s(154),
            self._s(y + 16),
            fill="#101722",
            outline="",
            tags=(row_tag, value_tag, "tooltip-target"),
        )
        self._text(value_x, y + 8, value, color, 9, "bold", "w", tags=(row_tag, value_tag, "tooltip-target"), family=self.NUMBER_FONT)
        self._text(214, y + 2, percent_text, percent_color, 8, "normal", "ne", tags=(row_tag, percent_tag), family=self.UI_FONT)
        self._daily_progress(30, y + 17, 184, percent, tags=row_tag)

    def _daily_limit_value_x(self) -> int:
        window = self._window_by_index(1) or self._window_by_index(0)
        if not window:
            return 82
        value_width = self._measure_text(format_credits(window.display_value), 9, "bold", self.NUMBER_FONT)
        return max(80, round(124 - value_width / 2) - 10)

    def _render(self) -> None:
        if self._expire_daily_limit_if_needed():
            self._resize_window_to_scale()
        self.tooltip_text_by_tag = {}
        self.canvas.delete("all")
        content_height = self._content_height()
        self._rounded_rect(0, 0, self.WIDTH, content_height, 8, "#0d1118")
        self._rounded_rect(1, 1, self.WIDTH - 1, content_height - 1, 8, "#101722", "#182231")

        snapshot = self.last_snapshot
        if snapshot and not snapshot.has_data:
            message = snapshot.status_note or "нет данных"
            self._text(
                self.WIDTH // 2,
                content_height // 2,
                message,
                "#ffb86b",
                9,
                "bold",
                "center",
                family=self.UI_FONT,
            )
            return

        account = snapshot.account if snapshot and snapshot.account else "NeuroGate"
        plan_status = compact_plan_status(snapshot.plan_status if snapshot else None)
        plan_text = plan_status or self.status_text
        account_x = 12
        account_width = self._measure_text(account, 8, family=self.UI_FONT)
        plan_x = account_x + account_width + 8
        plan_width = self._measure_text(plan_text, 8, family=self.UI_FONT)
        left_pill_right = min(122, plan_x + plan_width + 4)
        pill_fill = "#1a222d"
        pill_outline = "#303946"
        self._rounded_rect(6, 5, left_pill_right, 21, 5, pill_fill, pill_outline)
        self._text(12, 6, account, "#76a8ff", 8, "normal", family=self.UI_FONT)
        if plan_status:
            self._text(plan_x, 6, plan_status, "#76a8ff", 8, "normal", family=self.UI_FONT)
        else:
            self._text(plan_x, 6, self.status_text, "#697386", 8, "normal", family=self.UI_FONT)

        status_width = self._measure_text(self.status_text, 8, family=self.UI_FONT)
        status_left = left_pill_right + 3
        status_right = min(196, status_left + status_width + 8)
        status_center = (status_left + status_right) // 2
        self._rounded_rect(status_left, 5, status_right, 21, 5, pill_fill, pill_outline)
        self._text(status_center, 13, self.status_text, "#697386", 8, "normal", "center", family=self.UI_FONT)
        interval_left = status_right + 4
        interval_right = min(self.WIDTH - 6, interval_left + 32)
        interval_center = (interval_left + interval_right) // 2
        self._rounded_rect(interval_left, 5, interval_right, 21, 5, pill_fill, pill_outline, tags="interval")
        self._text(
            interval_center,
            13,
            self._format_interval_pill(self.interval_minutes),
            "#9aa4b5",
            8,
            "normal",
            "center",
            tags="interval",
            family=self.UI_FONT,
        )

        self._draw_limit_row(25, "5ч", self._window_by_index(0))
        self._draw_limit_row(47, "7д", self._window_by_index(1))
        self._draw_daily_limit_row(69)

    def _apply_snapshot(self, snapshot: UsageSnapshot) -> None:
        now = datetime.now().astimezone()
        if not snapshot.has_data and self._hold_transient_failure(snapshot.status_note, now):
            self._render()
            return

        self.last_snapshot = snapshot
        self.last_refresh_at = now
        if snapshot.has_data:
            self._clear_transient_failure()
            self.daily_usage.record_snapshot(snapshot, self.last_refresh_at)
        if snapshot.status_note:
            self.status_text = snapshot.status_note
        else:
            self.status_text = f"обн. {snapshot.updated_at.strftime('%H:%M')}"
        self._write_ui_log(
            f"snapshot account={snapshot.account!r} total={snapshot.total_used} "
            f"remaining={snapshot.remaining} windows={len(snapshot.windows)} "
            f"titles={[item.title for item in snapshot.windows]!r} "
            f"cached={snapshot.is_cached} status={snapshot.status_note!r}"
        )
        self._render()

    def _apply_error(self, error: object) -> None:
        if self._hold_transient_failure("ошибка", datetime.now().astimezone()):
            self._render()
            self._write_ui_log(f"transient_error_held {error!r}")
            return
        self.status_text = "ошибка"
        self._write_ui_log(f"error {error!r}")
        self._render()
        print(f"NeuroGate API overlay error: {error}")

    def _write_ui_log(self, message: str) -> None:
        try:
            append_bounded_log(self.debug_log, f"{datetime.now().isoformat(timespec='seconds')} {message}\n")
        except Exception:
            pass

    def _finish_refresh(self, snapshot: UsageSnapshot | None = None, error: object | None = None) -> None:
        try:
            if error is not None:
                self._apply_error(error)
            elif snapshot is not None:
                self._apply_snapshot(snapshot)
        finally:
            self.refreshing = False
            self._schedule_next_refresh()

    def _refresh_in_background(self) -> None:
        try:
            snapshot = self.reader()
        except Exception as exc:  # noqa: BLE001 - show operational errors without crashing.
            try:
                self.root.after(0, lambda error=exc: self._finish_refresh(error=error))
            except tk.TclError:
                self.refreshing = False
            return
        try:
            self.root.after(0, lambda result=snapshot: self._finish_refresh(snapshot=result))
        except tk.TclError:
            self.refreshing = False

    def refresh(self, force: bool = False) -> None:
        now = datetime.now().astimezone()
        if self.refreshing:
            return
        has_fresh_data = self._has_displayable_data()
        if (
            not force
            and has_fresh_data
            and not self._has_pending_transient_failure()
            and self.last_refresh_at
            and now - self.last_refresh_at < timedelta(seconds=self.MIN_REFRESH_SECONDS)
        ):
            self.status_text = "ждем 1 мин"
            self._render()
            self._schedule_next_refresh()
            return

        self.refreshing = True
        if not has_fresh_data:
            self.status_text = "обновляю"
            self._render()
        if getattr(self, "async_refresh", False):
            threading.Thread(target=self._refresh_in_background, daemon=True).start()
            return
        self.root.update_idletasks()
        try:
            self._finish_refresh(snapshot=self.reader())
        except Exception as exc:  # noqa: BLE001 - show operational errors without crashing.
            self._finish_refresh(error=exc)

    def run(self) -> None:
        self.root.mainloop()

    def close(self) -> None:
        if self.after_id:
            self.root.after_cancel(self.after_id)
        if self.resume_after_id:
            self.root.after_cancel(self.resume_after_id)
            self.resume_after_id = None
        if self.position_after_id:
            self.root.after_cancel(self.position_after_id)
            self.position_after_id = None
        if self.drag_after_id:
            self.root.after_cancel(self.drag_after_id)
            self.drag_after_id = None
        self._hide_tooltip()
        self._save_window_position()
        self.root.destroy()


if sys.platform == "darwin":
    import queue as _queue_module
    import objc as _objc
    from Foundation import NSObject as _NSObject, NSTimer as _NSTimer, NSRunLoop as _NSRunLoop, NSDefaultRunLoopMode as _NSDefaultRunLoopMode

    class _TimerTarget(_NSObject):  # type: ignore[misc]
        """One-shot or repeating NSTimer callback target. Created once per timer call."""
        _cb = None

        @_objc.python_method
        def setup_(self, cb):
            self._cb = cb

        def fire_(self, _timer):
            try:
                if self._cb:
                    self._cb()
            except Exception:
                pass

    class MenuBarOverlay:
        """macOS menu bar status item showing NeuroGate API usage.

        Displays a compact title (e.g. "NG 82.3M") in the menu bar; clicking it
        reveals a dropdown with per-window limits, settings, and actions.
        """

        INTERVAL_CHOICES_MINUTES = UsageOverlay.INTERVAL_CHOICES_MINUTES
        MIN_REFRESH_SECONDS = UsageOverlay.MIN_REFRESH_SECONDS
        UPDATE_CHECK_SECONDS = UsageOverlay.UPDATE_CHECK_SECONDS
        RESUME_HEARTBEAT_SECONDS = UsageOverlay.RESUME_HEARTBEAT_SECONDS
        RESUME_GAP_SECONDS = UsageOverlay.RESUME_GAP_SECONDS
        TRANSIENT_FAILURE_CONFIRMATIONS = UsageOverlay.TRANSIENT_FAILURE_CONFIRMATIONS
        TRANSIENT_FAILURE_GRACE_SECONDS = UsageOverlay.TRANSIENT_FAILURE_GRACE_SECONDS

        def __init__(
            self,
            reader: SnapshotReader,
            interval_seconds: int = 60,
            keep_browser_open_getter: KeepBrowserGetter | None = None,
            keep_browser_open_setter: KeepBrowserSetter | None = None,
            account_resetter: AccountResetter | None = None,
            async_refresh: bool = False,
        ) -> None:
            self.reader = reader
            self.keep_browser_open_getter = keep_browser_open_getter
            self.keep_browser_open_setter = keep_browser_open_setter
            self.account_resetter = account_resetter
            self.async_refresh = async_refresh
            self.debug_log = Path.home() / ".neurogate-usage-overlay" / "overlay-ui.log"
            self.state_file = Path.home() / ".neurogate-usage-overlay" / "overlay-state.json"
            self.daily_usage = DailyUsageStore(Path.home() / ".neurogate-usage-overlay" / "usage-daily.json")
            default_interval = UsageOverlay._normalize_interval_minutes(math.ceil(interval_seconds / 60))
            self.interval_minutes = self._load_interval_minutes(default_interval)
            self.daily_limit_credits: int | None = self._load_daily_limit_credits()
            self.daily_limit_set_at: datetime | None = self._load_daily_limit_set_at()
            self.last_snapshot: UsageSnapshot | None = None
            self.last_refresh_at: datetime | None = None
            self.last_resume_check_at: datetime | None = None
            self.refreshing = False
            self.transient_failure_since: datetime | None = None
            self.transient_failure_count = 0
            self.transient_status_note: str | None = None
            self.update_info: UpdateInfo | None = None
            self.update_check_running = False
            # Background thread posts (snapshot, error) tuples here;
            # the main-thread NSTimer drains it on the main thread.
            self._pending: _queue_module.Queue = _queue_module.Queue()
            self._ns_timer: object | None = None
            self._resume_ns_timer: object | None = None

            from .popover_server import PopoverServer
            from .macos_popover import MenuBarPopover
            self._server = PopoverServer()
            self._popover_ui: MenuBarPopover | None = None
            self._PopoverServer = PopoverServer
            self._MenuBarPopover = MenuBarPopover
            self._register_server_actions()

        # ------------------------------------------------------------------ state helpers

        def _load_state(self) -> dict[str, object]:
            try:
                payload = json.loads(self.state_file.read_text(encoding="utf-8"))
                return payload if isinstance(payload, dict) else {}
            except Exception:
                return {}

        def _save_state(self, updates: dict[str, object]) -> None:
            try:
                payload = self._load_state()
                payload.update(updates)
                self.state_file.parent.mkdir(parents=True, exist_ok=True)
                self.state_file.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
            except Exception as exc:
                self._write_ui_log(f"save_state_error {exc!r}")

        def _load_interval_minutes(self, default: int) -> int:
            try:
                payload = self._load_state()
                return UsageOverlay._normalize_interval_minutes(int(payload.get("interval_minutes", default)))
            except Exception:
                return UsageOverlay._normalize_interval_minutes(default)

        def _save_interval_minutes(self) -> None:
            self._save_state({"interval_minutes": self.interval_minutes})

        def _load_daily_limit_credits(self) -> int | None:
            try:
                payload = self._load_state()
                value = int(payload.get("daily_limit_credits") or 0)
                if 0 < value < 1_000_000:
                    value *= 1_000_000
                return value if value > 0 else None
            except Exception:
                return None

        def _load_daily_limit_set_at(self) -> datetime | None:
            try:
                payload = self._load_state()
                value = payload.get("daily_limit_set_at")
                if not isinstance(value, str):
                    return None
                parsed = datetime.fromisoformat(value)
                if parsed.tzinfo is None:
                    parsed = parsed.replace(tzinfo=datetime.now().astimezone().tzinfo)
                return parsed
            except Exception:
                return None

        def _save_daily_limit(self) -> None:
            self._save_state(
                {
                    "daily_limit_credits": self.daily_limit_credits or None,
                    "daily_limit_set_at": self.daily_limit_set_at.isoformat(timespec="seconds")
                    if self.daily_limit_credits and self.daily_limit_set_at
                    else None,
                }
            )

        def _daily_limit_expired(self) -> bool:
            set_at = self.daily_limit_set_at
            if not self.daily_limit_credits:
                return False
            if not set_at:
                return True
            now = datetime.now().astimezone()
            set_at_local = set_at.astimezone(now.tzinfo) if set_at.tzinfo else set_at.replace(tzinfo=now.tzinfo)
            return set_at_local.date() != now.date()

        def _daily_limit_enabled(self) -> bool:
            return bool(self.daily_limit_credits) and not self._daily_limit_expired()

        def _expire_daily_limit_if_needed(self) -> bool:
            if not self._daily_limit_expired():
                return False
            self.daily_limit_credits = None
            self.daily_limit_set_at = None
            self._save_daily_limit()
            return True

        def _keep_browser_open(self) -> bool:
            if not self.keep_browser_open_getter:
                return False
            try:
                return self.keep_browser_open_getter()
            except Exception as exc:
                self._write_ui_log(f"keep_browser_open_getter_error {exc!r}")
                return False

        def _has_keep_browser_toggle(self) -> bool:
            return bool(self.keep_browser_open_getter and self.keep_browser_open_setter)

        def _has_displayable_data(self) -> bool:
            return bool(self.last_snapshot and self.last_snapshot.has_data)

        def _has_pending_transient_failure(self) -> bool:
            return self._has_displayable_data() and self.transient_failure_count > 0

        def _clear_transient_failure(self) -> None:
            self.transient_failure_since = None
            self.transient_failure_count = 0
            self.transient_status_note = None

        def _hold_transient_failure(self, status_note: str | None, now: datetime) -> bool:
            if not self._has_displayable_data():
                return False
            if self.transient_failure_since is None:
                self.transient_failure_since = now
                self.transient_failure_count = 0
            self.transient_failure_count += 1
            self.transient_status_note = status_note or "нет данных"
            elapsed = now - self.transient_failure_since
            should_confirm = (
                self.transient_failure_count >= self.TRANSIENT_FAILURE_CONFIRMATIONS
                and elapsed >= timedelta(seconds=self.TRANSIENT_FAILURE_GRACE_SECONDS)
            )
            return not should_confirm

        def _write_ui_log(self, message: str) -> None:
            try:
                append_bounded_log(self.debug_log, f"{datetime.now().isoformat(timespec='seconds')} {message}\n")
            except Exception:
                pass

        # ------------------------------------------------------------------ title helpers

        def _menu_bar_title(self) -> str:
            snap = self.last_snapshot
            if not snap or not snap.has_data:
                return "NG …"
            # Show remaining credits from the shortest window (5h), fall back to 7d.
            window = snap.windows[0] if snap.windows else None
            if window and window.credits_remaining is not None:
                return f"NG {short_number(window.credits_remaining)}"
            if snap.remaining is not None:
                return f"NG {short_number(snap.remaining)}"
            return "NG ?"

        # ------------------------------------------------------------------ server actions

        def _register_server_actions(self) -> None:
            self._server.on_action("refresh", lambda: self.refresh(force=True))
            self._server.on_action("hide_daily", self._on_hide_daily_limit)
            self._server.on_action("set_daily", self._on_show_daily_limit_dialog)
            self._server.on_action("toggle_keep", self._on_toggle_keep_browser)
            self._server.on_action("open_interval", self._on_cycle_interval)
            self._server.on_action("reset_account", self._on_reset_account)
            self._server.on_action("update", self._on_start_update)
            self._server.on_action("quit", self.close)
            self._server.on_resize(lambda h: self._pending.put(("resize", h)))

        def _push_server_data(self) -> None:
            self._expire_daily_limit_if_needed()
            snap = self.last_snapshot
            interval_label = UsageOverlay._format_interval_menu(self.interval_minutes)
            extra = {
                "daily_limit_enabled": self._daily_limit_enabled(),
                "keep_browser_open": self._keep_browser_open(),
                "has_keep_toggle": self._has_keep_browser_toggle(),
                "interval_label": interval_label,
                "has_account_reset": bool(self.account_resetter),
                "update_available": bool(self.update_info),
                "update_label": self.update_info.latest_label if self.update_info else "",
            }
            self._server.update(snap, extra)
            if self._popover_ui:
                title = self._menu_bar_title()
                self._popover_ui.set_title(title)

        # ------------------------------------------------------------------ callbacks

        def _on_toggle_keep_browser(self, _sender: object) -> None:
            if not self.keep_browser_open_setter:
                return
            try:
                self.keep_browser_open_setter(not self._keep_browser_open())
            except Exception as exc:
                self._write_ui_log(f"toggle_keep_browser_error {exc!r}")
            self._push_server_data()

        def _on_set_interval(self, minutes: int) -> None:
            self.interval_minutes = UsageOverlay._normalize_interval_minutes(minutes)
            self._save_interval_minutes()
            self._reschedule_timer()
            self._push_server_data()

        def _on_hide_daily_limit(self, _sender: object) -> None:
            self.daily_limit_credits = None
            self.daily_limit_set_at = None
            self._save_daily_limit()
            self._push_server_data()

        def _on_show_daily_limit_dialog(self, _sender: object = None) -> None:
            from AppKit import NSAlert, NSTextField
            default = self._default_daily_limit_credits()
            default_str = short_number(default) if default else ""

            alert = NSAlert.alloc().init()
            alert.setMessageText_("Лимит на день")
            alert.setInformativeText_("Введите лимит токенов (например: 56M)")
            alert.addButtonWithTitle_("OK")
            alert.addButtonWithTitle_("Отмена")

            from Foundation import NSMakeRect
            field = NSTextField.alloc().initWithFrame_(NSMakeRect(0, 0, 200, 24))
            field.setStringValue_(default_str)
            alert.setAccessoryView_(field)
            alert.window().setInitialFirstResponder_(field)

            result = alert.runModal()
            if result != 1000:  # NSAlertFirstButtonReturn
                return
            parsed = UsageOverlay._parse_credit_input(field.stringValue())
            if parsed is None:
                from AppKit import NSAlert as _A
                err = _A.alloc().init()
                err.setMessageText_("Введите число: 56M или 56000000")
                err.runModal()
                return
            self.daily_limit_credits = parsed
            self.daily_limit_set_at = datetime.now().astimezone()
            self._save_daily_limit()
            self._push_server_data()

        def _default_daily_limit_credits(self) -> int | None:
            if not self.last_snapshot:
                return None
            window = find_window(self.last_snapshot, "7d")
            if window and window.credits_remaining is not None:
                days = UsageOverlay._remaining_plan_days(window.reset_text) or 1
                return max(1, round(window.credits_remaining / days))
            return None

        def _on_reset_account(self) -> None:
            if not self.account_resetter:
                return
            try:
                self.account_resetter()
            except Exception as exc:
                self._write_ui_log(f"reset_account_error {exc!r}")
                return
            self._clear_transient_failure()
            self.last_snapshot = UsageSnapshot(updated_at=datetime.now().astimezone(), status_note="нужен вход")
            self._push_server_data()
            self._reschedule_timer()

        def _on_cycle_interval(self) -> None:
            choices = self.INTERVAL_CHOICES_MINUTES
            try:
                idx = choices.index(self.interval_minutes)
                next_idx = (idx + 1) % len(choices)
            except ValueError:
                next_idx = 0
            self.interval_minutes = choices[next_idx]
            self._save_interval_minutes()
            self._reschedule_timer()
            self._push_server_data()

        def _on_start_update(self) -> None:
            if not self.update_info:
                return
            scripts_dir = Path(__file__).resolve().parents[2] / "scripts"
            script = scripts_dir / "update-and-restart.sh"
            cmd = ["bash", str(script), "--target-version", self.update_info.latest_label]
            if self.update_info.release_zip_url:
                cmd += ["--release-zip-url", self.update_info.release_zip_url]
            if self.update_info.release_sha256:
                cmd += ["--release-sha256", self.update_info.release_sha256]
            if not script.exists():
                self._write_ui_log("update_script_not_found")
                return
            try:
                subprocess.Popen(cmd, cwd=str(scripts_dir.parent))
            except Exception as exc:
                self._write_ui_log(f"start_update_error {exc!r}")
                return
            self.close()
            self.close()

        # ------------------------------------------------------------------ refresh logic

        def refresh(self, force: bool = False) -> None:
            now = datetime.now().astimezone()
            if self.refreshing:
                return
            if (
                not force
                and self._has_displayable_data()
                and not self._has_pending_transient_failure()
                and self.last_refresh_at
                and now - self.last_refresh_at < timedelta(seconds=self.MIN_REFRESH_SECONDS)
            ):
                self._reschedule_timer()
                return
            self.refreshing = True
            if self.async_refresh:
                threading.Thread(target=self._refresh_in_background, daemon=True).start()
            else:
                try:
                    self._finish_refresh(snapshot=self.reader())
                except Exception as exc:
                    self._finish_refresh(error=exc)

        def _refresh_in_background(self) -> None:
            self._write_ui_log("refresh_background_start")
            try:
                snapshot = self.reader()
            except Exception as exc:
                self._write_ui_log(f"refresh_background_error {exc!r}")
                self._pending.put(("error", exc))
                return
            self._write_ui_log(f"refresh_background_done has_data={snapshot.has_data}")
            self._pending.put(("snapshot", snapshot))

        def _finish_refresh(self, snapshot: UsageSnapshot | None = None, error: object | None = None) -> None:
            try:
                if error is not None:
                    self._apply_error(error)
                elif snapshot is not None:
                    self._apply_snapshot(snapshot)
            finally:
                self.refreshing = False
                self._reschedule_timer()

        def _apply_snapshot(self, snapshot: UsageSnapshot) -> None:
            now = datetime.now().astimezone()
            if not snapshot.has_data and self._hold_transient_failure(snapshot.status_note, now):
                return
            self.last_snapshot = snapshot
            self.last_refresh_at = now
            if snapshot.has_data:
                self._clear_transient_failure()
                self.daily_usage.record_snapshot(snapshot, self.last_refresh_at)
            self._write_ui_log(
                f"snapshot account={snapshot.account!r} total={snapshot.total_used} "
                f"remaining={snapshot.remaining} windows={len(snapshot.windows)} "
                f"cached={snapshot.is_cached} status={snapshot.status_note!r}"
            )
            for i, w in enumerate(snapshot.windows):
                self._write_ui_log(
                    f"  window[{i}] title={w.title!r} remaining={w.credits_remaining} display={w.display_value}"
                )
            self._push_server_data()

        def _apply_error(self, error: object) -> None:
            if self._hold_transient_failure("ошибка", datetime.now().astimezone()):
                self._write_ui_log(f"transient_error_held {error!r}")
                return
            self._write_ui_log(f"error {error!r}")
            if self._popover_ui:
                self._popover_ui.set_title("NG !")

        def check_for_updates(self) -> None:
            if self.update_check_running:
                return
            self.update_check_running = True

            def run_check() -> None:
                info = check_for_update()
                self._pending.put(("update_check", info))

            threading.Thread(target=run_check, daemon=True).start()

        # ------------------------------------------------------------------ run / close

        # ------------------------------------------------------------------ NSTimer helpers

        @staticmethod
        def _make_ns_timer(interval: float, callback: "Callable[[], None]") -> object:
            """Schedule a repeating NSTimer on the main run loop."""
            target = _TimerTarget.alloc().init()
            target.setup_(callback)
            timer = _NSTimer.scheduledTimerWithTimeInterval_target_selector_userInfo_repeats_(
                interval, target, _objc.selector(target.fire_, selector=b"fire:", signature=b"v@:@"), None, True
            )
            _NSRunLoop.mainRunLoop().addTimer_forMode_(timer, _NSDefaultRunLoopMode)
            return timer

        @staticmethod
        def _cancel_ns_timer(timer: object) -> None:
            if timer is not None:
                try:
                    timer.invalidate()  # type: ignore[attr-defined]
                except Exception:
                    pass

        # ------------------------------------------------------------------ pending queue drain

        def _drain_pending(self) -> None:
            """Drains background refresh results on main thread."""
            try:
                while True:
                    item = self._pending.get_nowait()
                    kind, value = item[0], item[1]
                    if kind == "snapshot":
                        self._finish_refresh(snapshot=value)
                    elif kind == "error":
                        self._finish_refresh(error=value)
                    elif kind == "resize":
                        if self._popover_ui:
                            self._popover_ui.resize_to_content(value)
                    elif kind == "update_check":
                        self.update_check_running = False
                        self.update_info = value
                        self._push_server_data()
                        self._make_ns_timer(self.UPDATE_CHECK_SECONDS, self.check_for_updates)
            except Exception:
                pass

        # ------------------------------------------------------------------ refresh timer

        def _reschedule_timer(self) -> None:
            self._cancel_ns_timer(self._ns_timer)
            delay = self.interval_minutes * 60
            if self._has_pending_transient_failure() or (self.last_snapshot and not self.last_snapshot.has_data):
                delay = 2

            def _tick() -> None:
                self._cancel_ns_timer(self._ns_timer)
                self._ns_timer = None
                self.refresh()

            self._ns_timer = self._make_ns_timer(delay, _tick)

        # ------------------------------------------------------------------ run / close

        def run(self) -> None:
            from AppKit import NSApplication, NSApp
            from Foundation import NSTimer, NSRunLoop, NSDefaultRunLoopMode

            app = NSApplication.sharedApplication()
            app.setActivationPolicy_(1)  # NSApplicationActivationPolicyAccessory — no Dock icon

            # Install the popover status item on main thread
            self._popover_ui = self._MenuBarPopover(
                server_url=self._server.get_url(),
                initial_title="NG …",
            )
            self._popover_ui.install()

            # Poll timer: drains background refresh results every 0.5s on main thread
            self._ns_poll_timer = self._make_ns_timer(0.5, self._drain_pending)

            # Resume watchdog
            self._resume_ns_timer = self._make_ns_timer(
                self.RESUME_HEARTBEAT_SECONDS, self._on_resume_watchdog_ns
            )

            # Kick off first refresh and update check after a short delay
            self._make_ns_timer(0.5, self._initial_refresh)
            self._make_ns_timer(1.2, self._initial_update_check)

            app.run()

        def _initial_refresh(self) -> None:
            self.refresh()

        def _initial_update_check(self) -> None:
            self.check_for_updates()

        def _on_resume_watchdog_ns(self) -> None:
            now = datetime.now().astimezone()
            previous = self.last_resume_check_at
            self.last_resume_check_at = now
            if previous and now - previous >= timedelta(seconds=self.RESUME_GAP_SECONDS):
                self._write_ui_log(f"resume_gap_detected seconds={(now - previous).total_seconds():.0f}")
                self.last_refresh_at = None
                if not self.refreshing:
                    self.refresh(force=True)

        def close(self) -> None:
            self._cancel_ns_timer(self._ns_timer)
            self._cancel_ns_timer(getattr(self, "_ns_poll_timer", None))
            self._cancel_ns_timer(self._resume_ns_timer)
            if self._popover_ui:
                self._popover_ui.remove()
            self._server.stop()
            from AppKit import NSApp
            NSApp.terminate_(None)
