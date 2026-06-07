from __future__ import annotations

import math
import tkinter as tk
from datetime import datetime, timedelta
from pathlib import Path
from typing import Callable

from .models import UsageSnapshot, UsageWindow
from .projection import projected_spendable_credits


SnapshotReader = Callable[[], UsageSnapshot]


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
    WIDTH = 340
    HEIGHT = 70
    MIN_REFRESH_SECONDS = 60
    INTERVAL_CHOICES_MINUTES = (1, 2, 3, 5, 10, 15)
    UI_FONT = "Segoe UI Variable Small"
    TEXT_FONT = "Segoe UI Variable Text"

    def __init__(self, reader: SnapshotReader, interval_seconds: int = 60) -> None:
        self.reader = reader
        self.interval_minutes = max(1, math.ceil(interval_seconds / 60))
        if self.interval_minutes not in self.INTERVAL_CHOICES_MINUTES:
            self.interval_minutes = 1
        self.refreshing = False
        self.after_id: str | None = None
        self.last_refresh_at: datetime | None = None
        self.last_snapshot: UsageSnapshot | None = None
        self.status_text = "обновление"
        self.debug_log = Path.home() / ".neurogate-usage-overlay" / "overlay-ui.log"
        self.drag_x = 0
        self.drag_y = 0
        self.menu_window: tk.Toplevel | None = None

        self.root = tk.Tk()
        self.root.title("Neurogate Usage Overlay")
        self.root.geometry(f"{self.WIDTH}x{self.HEIGHT}+32+72")
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

    def _show_menu(self, event: tk.Event) -> None:
        self._hide_menu()

        item_height = 24
        padding = 6
        width = 176
        rows: list[tuple[str, Callable[[], None] | None, bool]] = [
            ("Обновить", lambda: self.refresh(force=True), False),
            ("", None, False),
            *[
                (
                    f"{minutes} мин",
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
            canvas.create_text(
                14,
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

    def _cycle_interval(self) -> None:
        index = self.INTERVAL_CHOICES_MINUTES.index(self.interval_minutes)
        self.set_interval(self.INTERVAL_CHOICES_MINUTES[(index + 1) % len(self.INTERVAL_CHOICES_MINUTES)])

    def set_interval(self, minutes: int) -> None:
        self.interval_minutes = max(1, minutes)
        self._schedule_next_refresh()
        self._render()

    def _schedule_next_refresh(self) -> None:
        if self.after_id:
            self.root.after_cancel(self.after_id)
        delay_ms = self.interval_minutes * 60 * 1000
        if self.last_snapshot and not self.last_snapshot.has_data:
            delay_ms = 15 * 1000
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

    def _progress(self, x: int, y: int, width: int, percent: float | None) -> None:
        self._rounded_rect(x, y, x + width, y + 3, 2, "#242932")
        if percent is None:
            return
        fill_width = max(4, min(width, int(width * max(0.0, min(1.0, percent / 100)))))
        self._rounded_rect(x, y, x + fill_width, y + 3, 2, "#76a8ff")

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

    def _draw_limit_row(self, y: int, fallback_label: str, window: UsageWindow | None, total: int | None) -> None:
        label = self._compact_window_title(window, fallback_label)
        value = format_credits(window.display_value if window else None)
        if total is not None and window and window.display_value is not None:
            value = f"{value} / {format_credits(total)}"
        reset = compact_reset_text(window.reset_text if window else None)

        self._text(10, y + 1, label, "#9aa8ba", 9, "normal", family=self.UI_FONT)
        self._text(40, y, "остаток", "#667386", 8, "normal", family=self.UI_FONT)
        self._text(110, y - 1, value, "#ffb86b", 11, "normal", family=self.TEXT_FONT)
        self._text(330, y + 2, reset, "#8793a4", 8, "normal", "ne", family=self.UI_FONT)
        self._progress(40, y + 17, 288, None)

    def _render(self) -> None:
        self.canvas.delete("all")
        self._rounded_rect(0, 0, self.WIDTH, self.HEIGHT, 8, "#0d1118")
        self._rounded_rect(1, 1, self.WIDTH - 1, self.HEIGHT - 1, 8, "#101722", "#182231")

        snapshot = self.last_snapshot
        account = snapshot.account if snapshot and snapshot.account else "Neurogate"
        plan_status = compact_plan_status(snapshot.plan_status if snapshot else None)
        projected_total = projected_spendable_credits(snapshot) if snapshot else None
        self._text(10, 7, account, "#76a8ff", 8, "normal", family=self.UI_FONT)
        if plan_status:
            self._text(68, 7, plan_status, "#76a8ff", 8, "normal", family=self.UI_FONT)
        else:
            self._text(68, 7, self.status_text, "#697386", 8, "normal", family=self.UI_FONT)

        self._text(258, 7, self.status_text, "#697386", 8, "normal", "ne", family=self.UI_FONT)
        self._rounded_rect(302, 5, 334, 21, 5, "#161d28", "#25303b", tags="interval")
        self._text(318, 13, f"{self.interval_minutes}м", "#9aa4b5", 8, "normal", "center", tags="interval", family=self.UI_FONT)

        self._draw_limit_row(25, "5ч", self._window_by_index(0), projected_total)
        self._draw_limit_row(47, "7д", self._window_by_index(1), projected_total)

        if snapshot and not snapshot.windows:
            message = "нужен вход в Neurogate" if not snapshot.total_used else "лимиты не раскрылись"
            self._text(40, 38, message, "#ffb86b", 8, "normal", family=self.UI_FONT)

    def _apply_snapshot(self, snapshot: UsageSnapshot) -> None:
        self.last_snapshot = snapshot
        self.last_refresh_at = datetime.now().astimezone()
        if snapshot.is_cached:
            self.status_text = snapshot.status_note or f"кэш {snapshot.updated_at.strftime('%H:%M')}"
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
        print(f"Neurogate usage overlay error: {error}")

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
        if not force and self.last_refresh_at and now - self.last_refresh_at < timedelta(seconds=self.MIN_REFRESH_SECONDS):
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
        self.root.destroy()
