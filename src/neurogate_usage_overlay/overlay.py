from __future__ import annotations

import math
import json
import tkinter as tk
from datetime import datetime, timedelta
from pathlib import Path
from typing import Callable

from .history import DailyUsageStore, spent_since_reset, window_key
from .models import UsageSnapshot, UsageWindow


SnapshotReader = Callable[[], UsageSnapshot]
KeepBrowserGetter = Callable[[], bool]
KeepBrowserSetter = Callable[[bool], None]


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
    MIN_REFRESH_SECONDS = 60
    LOGIN_POLL_SECONDS = 2
    INTERVAL_CHOICES_MINUTES = (1, 3, 5, 10, 15, 60)
    UI_FONT = "Segoe UI Variable Small"
    TEXT_FONT = "Segoe UI Variable Text"
    NUMBER_FONT = "Calibri Light"

    def __init__(
        self,
        reader: SnapshotReader,
        interval_seconds: int = 60,
        keep_browser_open_getter: KeepBrowserGetter | None = None,
        keep_browser_open_setter: KeepBrowserSetter | None = None,
    ) -> None:
        self.reader = reader
        self.keep_browser_open_getter = keep_browser_open_getter
        self.keep_browser_open_setter = keep_browser_open_setter
        self.debug_log = Path.home() / ".neurogate-usage-overlay" / "overlay-ui.log"
        self.state_file = Path.home() / ".neurogate-usage-overlay" / "overlay-state.json"
        self.daily_usage = DailyUsageStore(Path.home() / ".neurogate-usage-overlay" / "usage-daily.json")
        default_interval = self._normalize_interval_minutes(math.ceil(interval_seconds / 60))
        self.interval_minutes = self._load_interval_minutes(default_interval)
        self.refreshing = False
        self.after_id: str | None = None
        self.last_refresh_at: datetime | None = None
        self.last_snapshot: UsageSnapshot | None = None
        self.status_text = "обновление"
        self.drag_x = 0
        self.drag_y = 0
        self.menu_window: tk.Toplevel | None = None
        self.tooltip_window: tk.Toplevel | None = None

        self.root = tk.Tk()
        self.root.title("NeuroGate API 1.3.0")
        self.root.geometry(self._initial_geometry())
        self.root.overrideredirect(True)
        self.root.attributes("-topmost", True)
        self.root.attributes("-alpha", 0.96)
        self.root.configure(bg="#0b0d12")
        self.root.protocol("WM_DELETE_WINDOW", self.close)

        self.canvas = tk.Canvas(
            self.root,
            width=self.WIDTH,
            height=self.HEIGHT,
            highlightthickness=0,
            bd=0,
            bg="#0b0d12",
        )
        self.canvas.pack(fill="both", expand=True)

        self._bind_window()
        self._render()
        self.root.after(200, self.refresh)

    def _bind_window(self) -> None:
        self.root.bind("<ButtonPress-1>", self._start_drag)
        self.root.bind("<B1-Motion>", self._drag)
        self.root.bind("<ButtonRelease-1>", self._end_drag)
        self.root.bind("<Button-3>", self._show_menu)
        self.root.bind("<Escape>", lambda _event: self.close())
        self.root.bind("<Control-r>", lambda _event: self.refresh(force=True))
        self.canvas.tag_bind("interval", "<Button-1>", lambda _event: self._cycle_interval())

    def _start_drag(self, event: tk.Event) -> None:
        self._hide_menu()
        self.drag_x = event.x
        self.drag_y = event.y

    def _drag(self, event: tk.Event) -> None:
        x = self.root.winfo_x() + event.x - self.drag_x
        y = self.root.winfo_y() + event.y - self.drag_y
        self.root.geometry(f"+{x}+{y}")

    def _end_drag(self, _event: tk.Event) -> None:
        self._save_window_position()

    def _initial_geometry(self) -> str:
        x, y = self._load_window_position()
        x, y = self._clamp_position(x, y, self.root.winfo_screenwidth(), self.root.winfo_screenheight())
        return f"{self.WIDTH}x{self.HEIGHT}+{x}+{y}"

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

    def _save_window_position(self) -> None:
        try:
            x, y = self._clamp_position(
                self.root.winfo_x(),
                self.root.winfo_y(),
                self.root.winfo_screenwidth(),
                self.root.winfo_screenheight(),
            )
            self._save_state({"x": x, "y": y})
        except Exception as exc:  # noqa: BLE001 - position persistence must not break dragging.
            self._write_ui_log(f"save_window_position_error {exc!r}")

    def _clamp_position(self, x: int, y: int, screen_width: int, screen_height: int) -> tuple[int, int]:
        margin = 8
        max_x = max(margin, screen_width - self.WIDTH - margin)
        max_y = max(margin, screen_height - self.HEIGHT - margin)
        return max(margin, min(x, max_x)), max(margin, min(y, max_y))

    def _show_menu(self, event: tk.Event) -> None:
        self._hide_menu()

        item_height = 24
        padding = 6
        width = 160
        keep_browser_open = self._keep_browser_open()
        keep_browser_label = "Не закрывать ЛК"
        rows: list[tuple[str, Callable[[], None] | None, bool]] = [
            ("Обновить", lambda: self.refresh(force=True), False),
            ("", None, False),
            (
                keep_browser_label,
                self._toggle_keep_browser_open if self._has_keep_browser_toggle() else None,
                keep_browser_open,
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
            ("", None, False),
            ("Закрыть", self.close, False),
        ]
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
            if label == keep_browser_label:
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
            font=(self.UI_FONT, 8, "normal"),
            padx=8,
            pady=5,
            bd=1,
            relief="solid",
            highlightthickness=1,
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

    def _schedule_next_refresh(self) -> None:
        if self.after_id:
            self.root.after_cancel(self.after_id)
        delay_ms = self.interval_minutes * 60 * 1000
        if self.last_snapshot and not self.last_snapshot.has_data:
            delay_ms = self.LOGIN_POLL_SECONDS * 1000
        self.after_id = self.root.after(delay_ms, self.refresh)

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
            points,
            smooth=True,
            splinesteps=12,
            fill=fill,
            outline=outline,
            width=width,
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
            x,
            y,
            text=text,
            fill=fill,
            font=(family or self.TEXT_FONT, size, weight),
            anchor=anchor,
            tags=tags,
        )

    def _measure_text(self, text: str, size: int = 8, weight: str = "normal", family: str | None = None) -> int:
        item = self.canvas.create_text(
            -1000,
            -1000,
            text=text,
            font=(family or self.TEXT_FONT, size, weight),
            anchor="nw",
        )
        bbox = self.canvas.bbox(item)
        self.canvas.delete(item)
        if not bbox:
            return 0
        return bbox[2] - bbox[0]

    def _progress(self, x: int, y: int, width: int, percent: float | None) -> None:
        self._rounded_rect(x, y, x + width, y + 3, 2, "#242932")
        if percent is None:
            return
        fill_width = min(width, max(0, int(width * max(0.0, min(1.0, percent / 100)))))
        if fill_width > 0:
            self._rounded_rect(x, y, x + fill_width, y + 3, 2, "#76a8ff")

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

        self._text(9, y, label, "#9aa8ba", 9, "normal", family=self.UI_FONT)
        self._text(31, y, "остаток", "#667386", 8, "normal", family=self.UI_FONT)
        self.canvas.create_rectangle(92, y + 1, 158, y + 16, fill="#101722", outline="", tags=value_tag)
        self._text(124, y + 8, value, "#ffb86b", 10, "bold", "center", tags=value_tag, family=self.NUMBER_FONT)
        if tooltip:
            self.canvas.tag_bind(value_tag, "<Enter>", lambda event, text=tooltip: self._show_tooltip(event, text))
            self.canvas.tag_bind(value_tag, "<Motion>", lambda event: self._move_tooltip(event))
            self.canvas.tag_bind(value_tag, "<Leave>", lambda _event: self._hide_tooltip())
        self._text(214, y + 2, reset, "#8793a4", 8, "normal", "ne", family=self.UI_FONT)
        self._progress(30, y + 17, 184, percent)

    def _render(self) -> None:
        self.canvas.delete("all")
        self._rounded_rect(0, 0, self.WIDTH, self.HEIGHT, 8, "#0d1118")
        self._rounded_rect(1, 1, self.WIDTH - 1, self.HEIGHT - 1, 8, "#101722", "#182231")

        snapshot = self.last_snapshot
        if snapshot and not snapshot.has_data:
            message = snapshot.status_note or "нет данных"
            self._text(
                self.WIDTH // 2,
                self.HEIGHT // 2,
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

    def _apply_snapshot(self, snapshot: UsageSnapshot) -> None:
        self.last_snapshot = snapshot
        self.last_refresh_at = datetime.now().astimezone()
        if snapshot.has_data:
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
        self.status_text = "ошибка"
        self._write_ui_log(f"error {error!r}")
        self._render()
        print(f"NeuroGate API overlay error: {error}")

    def _write_ui_log(self, message: str) -> None:
        try:
            self.debug_log.parent.mkdir(parents=True, exist_ok=True)
            with self.debug_log.open("a", encoding="utf-8") as handle:
                handle.write(f"{datetime.now().isoformat(timespec='seconds')} {message}\n")
        except Exception:
            pass

    def refresh(self, force: bool = False) -> None:
        now = datetime.now().astimezone()
        if self.refreshing:
            return
        has_fresh_data = bool(self.last_snapshot and self.last_snapshot.has_data)
        if (
            not force
            and has_fresh_data
            and self.last_refresh_at
            and now - self.last_refresh_at < timedelta(seconds=self.MIN_REFRESH_SECONDS)
        ):
            self.status_text = "ждем 1 мин"
            self._render()
            self._schedule_next_refresh()
            return

        self.refreshing = True
        self.status_text = "обновляю"
        self._render()
        self.root.update_idletasks()
        try:
            self._apply_snapshot(self.reader())
        except Exception as exc:  # noqa: BLE001 - show operational errors without crashing.
            self._apply_error(exc)
        finally:
            self.refreshing = False
            self._schedule_next_refresh()

    def run(self) -> None:
        self.root.mainloop()

    def close(self) -> None:
        if self.after_id:
            self.root.after_cancel(self.after_id)
        self._hide_tooltip()
        self._save_window_position()
        self.root.destroy()
