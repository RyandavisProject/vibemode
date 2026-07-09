from __future__ import annotations

import math
import re
import shlex
import subprocess
import sys
import threading
import tkinter as tk
from datetime import datetime, timedelta
from pathlib import Path
from typing import Callable

from . import __version__
from .history import DailyUsageStore, find_window, spent_since_reset, window_key
from .json_store import load_json_object, update_json_object_atomic
from .log_utils import append_bounded_log
from .macos_power import install_macos_power_observer
from .models import UsageSnapshot, UsageWindow
from .resume_recovery import ResumeRefreshCoordinator
from .update_checker import UpdateInfo, check_for_update
from .win32_power import install_win32_power_broadcast_handler
from .win32_window import apply_rounded_window_region, configure_rounded_window_background


SnapshotReader = Callable[[], UsageSnapshot]
KeepBrowserGetter = Callable[[], bool]
KeepBrowserSetter = Callable[[bool], None]
AccountResetter = Callable[[], None]


class _ResumeRecoveryOverlayMixin:
    STALE_REFRESH_SECONDS: int
    refreshing: bool
    last_refresh_at: datetime | None

    def _resume_recovery(self) -> ResumeRefreshCoordinator:
        legacy_state = getattr(self, "resume_recovery_state", None)
        coordinator = getattr(self, "resume_recovery", None)
        if isinstance(legacy_state, ResumeRefreshCoordinator) and legacy_state is not coordinator:
            coordinator = legacy_state
        if coordinator is None:
            coordinator = ResumeRefreshCoordinator(getattr(self, "STALE_REFRESH_SECONDS", 120))
        self.resume_recovery = coordinator
        self.resume_recovery_state = coordinator
        return coordinator

    def _sync_resume_recovery_aliases(self) -> None:
        coordinator = self._resume_recovery()
        self.refresh_started_at = coordinator.refresh_started_at
        self.refresh_generation = coordinator.refresh_generation
        self.resume_recovery_pending = coordinator.resume_recovery_pending

    def _begin_refresh_tracking(self, now: datetime) -> int:
        generation = self._resume_recovery().begin_refresh(now)
        self._sync_resume_recovery_aliases()
        return generation

    def _finish_refresh_tracking(self, generation: int | None) -> bool:
        accepted = self._resume_recovery().finish_refresh(generation)
        self._sync_resume_recovery_aliases()
        if not accepted:
            self._write_ui_log(f"stale_refresh_result_ignored generation={generation}")
        return accepted

    def _log_abandoned_refresh(self, reason: str, generation: int) -> None:
        self.refreshing = False
        self._write_ui_log(f"stale_refresh_abandoned reason={reason} generation={generation}")

    def _abandon_active_refresh(self, reason: str) -> None:
        stale_generation = self._resume_recovery().abandon_active_refresh()
        self._sync_resume_recovery_aliases()
        self._log_abandoned_refresh(reason, stale_generation)

    def request_resume_recovery(self, reason: str) -> None:
        now = datetime.now().astimezone()
        decision = self._resume_recovery().request_resume_recovery(now, self.refreshing)
        self._sync_resume_recovery_aliases()
        self.last_refresh_at = None
        self._write_ui_log(f"resume_recovery_requested reason={reason}")
        if decision.abandoned_generation is not None:
            self._log_abandoned_refresh(reason, decision.abandoned_generation)
        if decision.wait_for_active_refresh:
            self._write_ui_log(f"resume_recovery_waiting_for_active_refresh reason={reason}")
            return
        if decision.start_refresh:
            self.refresh(force=True)

    def _can_start_forced_refresh(self, now: datetime, reason: str) -> bool:
        decision = self._resume_recovery().request_forced_refresh(now, self.refreshing)
        self._sync_resume_recovery_aliases()
        if decision.abandoned_generation is not None:
            self._log_abandoned_refresh(reason, decision.abandoned_generation)
        return decision.start_refresh

    def _is_incomplete_snapshot_regression(self, snapshot: UsageSnapshot) -> bool:
        previous = getattr(self, "last_snapshot", None)
        if not previous or not previous.has_data or not snapshot.has_data:
            return False
        previous_keys = {window_key(window) for window in previous.windows}
        current_keys = {window_key(window) for window in snapshot.windows}
        for key in ("5h", "7d"):
            if key in previous_keys and key not in current_keys:
                return True
        return bool(previous.account and not snapshot.account and previous.windows)

    def _is_low_confidence_snapshot(self, snapshot: UsageSnapshot) -> bool:
        if not snapshot.has_data:
            return False
        keys = {window_key(window) for window in snapshot.windows}
        if snapshot.account and "7d" in keys:
            return False
        if "7d" in keys and "5h" in keys:
            return False
        has_limit_pair = any(window.limit_total is not None or window.limit_used is not None for window in snapshot.windows)
        if has_limit_pair and snapshot.account:
            return False
        return (
            not snapshot.account
            and len(snapshot.windows) == 1
            and "5h" in keys
            and not has_limit_pair
            and (snapshot.windows[0].credits_remaining or 0) <= 1
        )

    def _hold_low_confidence_snapshot(self, snapshot: UsageSnapshot, now: datetime) -> bool:
        if not self._is_low_confidence_snapshot(snapshot):
            return False
        if getattr(self, "transient_failure_since", None) is None:
            self.transient_failure_since = now
            self.transient_failure_count = 0
        self.transient_failure_count += 1
        self.transient_status_note = "low confidence snapshot"
        self.status_text = self._stable_status_text() if self._has_displayable_data() else "обновляю"
        self._write_ui_log(
            f"low_confidence_snapshot_held count={self.transient_failure_count} "
            f"{self._snapshot_debug_summary(snapshot)}"
        )
        return True

    def _hold_incomplete_snapshot_regression(self, snapshot: UsageSnapshot, now: datetime) -> bool:
        if not self._is_incomplete_snapshot_regression(snapshot):
            return False
        if getattr(self, "transient_failure_since", None) is None:
            self.transient_failure_since = now
            self.transient_failure_count = 0
        self.transient_failure_count += 1
        self.transient_status_note = "incomplete snapshot"
        self.status_text = self._stable_status_text()
        self._write_ui_log(
            f"incomplete_snapshot_held count={self.transient_failure_count} "
            f"{self._snapshot_debug_summary(snapshot)}"
        )
        return True

    def _snapshot_debug_summary(self, snapshot: UsageSnapshot) -> str:
        parts = [
            f"account={snapshot.account!r}",
            f"windows={len(snapshot.windows)}",
            f"status={snapshot.status_note!r}",
        ]
        for window in snapshot.windows:
            key = window_key(window) or window.title
            parts.append(
                f"{key}:remaining={window.credits_remaining} "
                f"used={window.limit_used} total={window.limit_total} "
                f"progress={window.progress_percent}"
            )
        daily = getattr(self, "daily_usage", None)
        last_snapshot = getattr(self, "last_snapshot", None)
        if daily is not None and last_snapshot is not None and hasattr(daily, "today_spent_7d"):
            try:
                today_spent = daily.today_spent_7d(last_snapshot)
            except Exception:
                today_spent = None
            if today_spent is not None:
                parts.append(f"daily_spent={today_spent.amount}")
        return " ".join(parts)


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


def format_limit_value(window: UsageWindow | None) -> str:
    if not window:
        return "-"
    value = format_credits(window.display_value)
    if window.limit_total:
        return f"{value}/{short_number_clean(window.limit_total)}"
    return value


def short_number_clean(value: int | None) -> str:
    return short_number(value).replace(".0B", "B").replace(".0M", "M").replace(".0K", "K")


def menu_bar_number(value: int | None) -> str:
    if value is None:
        return "-"
    if abs(value) >= 1_000_000:
        return f"{value / 1_000_000:.0f}"
    if abs(value) >= 1_000:
        return f"{value / 1_000:.0f}K"
    return str(value)


def compact_percent(value: float | None) -> str:
    if value is None:
        return "-"
    if value >= 100:
        return f"{round(value):.0f}%"
    if value >= 10:
        return f"{value:.0f}%"
    return f"{value:.1f}%"


def display_version(value: str) -> str:
    cleaned = value.strip()
    if cleaned.lower().startswith("v"):
        cleaned = cleaned[1:]
    parts = cleaned.split(".")
    if len(parts) >= 3 and parts[-1] == "0":
        cleaned = ".".join(parts[:-1])
    return f"v.{cleaned}"


def version_menu_label(current_version: str, update_info: UpdateInfo | None) -> str:
    current = display_version(current_version)
    if update_info:
        return f"{current} (доступна {display_version(update_info.latest_version)})"
    return f"{current} (последняя)"


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
    cleaned = re.sub(r"\s+остал(?:ось|ся|ась|ись)?\s*$", "", cleaned, flags=re.IGNORECASE)
    return f"ост. {compact_reset_text(cleaned)}"


class UsageOverlay(_ResumeRecoveryOverlayMixin):
    WIDTH = 222
    HEIGHT = 78
    DAILY_LIMIT_HEIGHT = 106
    WINDOW_CORNER_RADIUS = 7
    WINDOW_TRANSPARENT_COLOR = "#010203"
    SCALE_NORMAL = 1
    SCALE_LARGE = 2
    MIN_REFRESH_SECONDS = 60
    LOGIN_POLL_SECONDS = 2
    TRANSIENT_FAILURE_CONFIRMATIONS = 3
    TRANSIENT_FAILURE_GRACE_SECONDS = 30
    UPDATE_CHECK_SECONDS = 3 * 60 * 60
    RESUME_HEARTBEAT_SECONDS = 30
    RESUME_GAP_SECONDS = 120
    STALE_REFRESH_SECONDS = 120
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
        self.resume_recovery = ResumeRefreshCoordinator(self.STALE_REFRESH_SECONDS)
        self.resume_recovery_state = self.resume_recovery
        self.refresh_started_at: datetime | None = None
        self.refresh_generation = 0
        self.resume_recovery_pending = False
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
        self.root.title(f"Vibemode {__version__}")
        self.root.geometry(self._initial_geometry())
        self.root.overrideredirect(True)
        self.root.attributes("-topmost", True)
        if not sys.platform.startswith("win"):
            self.root.attributes("-alpha", 0.96)
        configure_rounded_window_background(self.root, self.WINDOW_TRANSPARENT_COLOR)
        self.root.protocol("WM_DELETE_WINDOW", self.close)

        self.canvas = tk.Canvas(
            self.root,
            width=self._scaled_width(),
            height=self._scaled_height(),
            highlightthickness=0,
            bd=0,
            bg=self.WINDOW_TRANSPARENT_COLOR,
        )
        self.canvas.pack(fill="both", expand=True)
        apply_rounded_window_region(
            self.root,
            self._scaled_width(),
            self._scaled_height(),
            self._s(self.WINDOW_CORNER_RADIUS),
            self.WINDOW_TRANSPARENT_COLOR,
        )
        self.power_event_handle = install_win32_power_broadcast_handler(
            self.root,
            on_suspend=self._on_power_suspend,
            on_resume=self._on_power_resume,
        )

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
        return load_json_object(self.state_file)

    def _save_state(self, updates: dict[str, object]) -> None:
        try:
            update_json_object_atomic(self.state_file, updates)
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

    @staticmethod
    def _clamp_popup_position(
        x: int,
        y: int,
        width: int,
        height: int,
        screen_width: int,
        screen_height: int,
        margin: int = 8,
    ) -> tuple[int, int]:
        max_x = max(margin, screen_width - width - margin)
        max_y = max(margin, screen_height - height - margin)
        return max(margin, min(x, max_x)), max(margin, min(y, max_y))

    def _show_menu(self, event: tk.Event) -> None:
        self._hide_menu()
        if self._expire_daily_limit_if_needed():
            self._resize_window_to_scale()
            self._render()

        item_height = 24
        padding = 6
        width = 166
        scale_label = "2x размер"
        daily_limit_label = "Скрыть лимит в день" if self._daily_limit_enabled() else "Задать лимит на день"
        version_label = self._version_menu_label()
        version_command = self._version_menu_command()
        checkbox_labels = {scale_label}
        rows: list[tuple[str, Callable[[], None] | None, bool]] = [
            ("Обновить лимиты", lambda: self.refresh(force=True), False),
            (
                daily_limit_label,
                self._hide_daily_limit if self._daily_limit_enabled() else self._show_daily_limit_dialog,
                False,
            ),
            ("", None, False),
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
        rows.extend(
            [
                ("", None, False),
                (version_label, version_command, False),
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
        menu.configure(bg="#18181b", bd=0, highlightthickness=0)
        x, y = self._clamp_popup_position(
            int(event.x_root),
            int(event.y_root),
            width,
            height,
            self.root.winfo_screenwidth(),
            self.root.winfo_screenheight(),
        )
        menu.geometry(f"{width}x{height}+{x}+{y}")

        canvas = tk.Canvas(menu, width=width, height=height, highlightthickness=0, bd=0, bg="#18181b")
        canvas.pack(fill="both", expand=True)
        canvas.create_rectangle(0, 0, width, height, fill="#202124", outline="#3a3a40")

        y = padding
        for index, (label, command, active) in enumerate(rows):
            if not label:
                canvas.create_line(10, y + 3, width - 10, y + 3, fill="#3a3a40")
                y += 8
                continue

            tag = f"item-{index}"
            bg_tag = f"item-bg-{index}"
            fill = "#303035" if active else "#202124"
            disabled = command is None
            canvas.create_rectangle(5, y, width - 5, y + item_height, fill=fill, outline="", tags=(tag, bg_tag))
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
                    fill="#18181b",
                    outline="#4a4a50",
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
                        fill="#64d2ff",
                        width=2,
                        tags=tag,
                    )
            text_fill = "#f5f5f7" if not active else "#64d2ff"
            if disabled:
                text_fill = "#8793a4"
            canvas.create_text(
                text_x,
                y + item_height // 2,
                text=label,
                fill=text_fill,
                font=(self.UI_FONT, 8, "normal"),
                anchor="w",
                tags=tag,
            )
            if active:
                canvas.create_oval(width - 18, y + 9, width - 12, y + 15, fill="#64d2ff", outline="", tags=tag)

            def run_action(action: Callable[[], None] | None = command) -> None:
                self._hide_menu()
                if action:
                    action()

            if command:
                canvas.tag_bind(tag, "<Enter>", lambda _event, bg_tag=bg_tag: canvas.itemconfigure(bg_tag, fill="#2c2c30"))
                canvas.tag_bind(tag, "<Leave>", lambda _event, bg_tag=bg_tag, fill=fill: canvas.itemconfigure(bg_tag, fill=fill))
                canvas.tag_bind(tag, "<Button-1>", lambda _event, action=run_action: action())
            y += item_height

        menu.bind("<Escape>", lambda _event: self._hide_menu())
        menu.bind("<FocusOut>", lambda _event: self._hide_menu())
        menu.focus_force()

    def _version_menu_label(self) -> str:
        return version_menu_label(__version__, self.update_info)

    def _version_menu_command(self) -> Callable[[], None] | None:
        return self._start_update if self.update_info else None

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
        tooltip.configure(bg="#18181b", bd=0, highlightthickness=0)

        label = tk.Label(
            tooltip,
            text=text,
            bg="#2c2c30",
            fg="#f5f5f7",
            font=(self.UI_FONT, self._font_size(8), "normal"),
            padx=self._s(8),
            pady=self._s(5),
            bd=max(1, self._s(1)),
            relief="solid",
            highlightthickness=max(1, self._s(1)),
            highlightbackground="#4a4a50",
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
        dialog.configure(bg="#18181b", bd=0, highlightthickness=0)

        width = self._s(210)
        height = self._s(92)
        x = self.root.winfo_x() + self._s(8)
        y = self.root.winfo_y() + self._s(22)
        dialog.geometry(f"{width}x{height}+{x}+{y}")

        canvas = tk.Canvas(dialog, width=width, height=height, highlightthickness=0, bd=0, bg="#18181b")
        canvas.pack(fill="both", expand=True)
        scale = self._current_scale()
        canvas.create_rectangle(0, 0, width, height, fill="#202124", outline="#3a3a40")

        def rounded_rect(
            x1: int,
            y1: int,
            x2: int,
            y2: int,
            radius: int,
            fill: str,
            outline: str = "",
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
            canvas.create_polygon(
                [self._s(point) for point in points],
                smooth=True,
                splinesteps=12 * self._current_scale(),
                fill=fill,
                outline=outline,
                width=max(1, self._s(1)),
                tags=tags,
            )

        canvas.create_text(
            self._s(12),
            self._s(11),
            text="Лимит на день",
            fill="#f5f5f7",
            font=(self.UI_FONT, self._font_size(9), "bold"),
            anchor="nw",
        )
        canvas.create_text(
            self._s(12),
            self._s(30),
            text="Например: 82M",
            fill="#c9c9cf",
            font=(self.UI_FONT, self._font_size(8), "normal"),
            anchor="nw",
        )

        default_value = self._daily_limit_dialog_default_credits()
        value = tk.StringVar(value=short_number(default_value) if default_value else "")
        rounded_rect(12, 49, 104, 73, 6, "#2c2c30", "#4a4a50")
        entry = tk.Entry(
            dialog,
            textvariable=value,
            bg="#2c2c30",
            fg="#f5f5f7",
            insertbackground="#64d2ff",
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
            bg="#202124",
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

        rounded_rect(116, 49, 152, 73, 6, "#2c2c30", "#3a3a40", tags="daily-ok")
        canvas.create_text(
            self._s(134),
            self._s(61),
            text="OK",
            fill="#f5f5f7",
            font=(self.UI_FONT, self._font_size(8), "bold"),
            anchor="center",
            tags="daily-ok",
        )
        rounded_rect(158, 49, 198, 73, 6, "#2c2c30", "#3a3a40", tags="daily-cancel")
        canvas.create_text(
            self._s(178),
            self._s(61),
            text="Отмена",
            fill="#b7b7bd",
            font=(self.UI_FONT, self._font_size(8), "normal"),
            anchor="center",
            tags="daily-cancel",
        )
        canvas.tag_bind("daily-ok", "<Button-1>", lambda _event: save_limit())
        canvas.tag_bind("daily-cancel", "<Button-1>", lambda _event: close_dialog())

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
        apply_rounded_window_region(self.root, width, height, self._s(self.WINDOW_CORNER_RADIUS), self.WINDOW_TRANSPARENT_COLOR)

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

    @staticmethod
    def _daily_limit_divisor_days(reset_text: str | None, plan_status: str | None = None) -> float:
        days = UsageOverlay._remaining_plan_days(reset_text) or UsageOverlay._remaining_plan_days(plan_status) or 1.0
        return max(1.0, days)

    @staticmethod
    def _seven_day_daily_limit_divisor_days(reset_text: str | None, plan_status: str | None = None) -> float | None:
        reset_days = UsageOverlay._remaining_plan_days(reset_text)
        if reset_days is not None:
            return min(7.0, max(1.0, reset_days))
        return None

    def _default_daily_limit_credits(self) -> int | None:
        if not self.last_snapshot:
            return None
        window = find_window(self.last_snapshot, "7d") or self._window_by_index(1)
        if not window or window.credits_remaining is None:
            return None
        days = self._seven_day_daily_limit_divisor_days(window.reset_text, self.last_snapshot.plan_status)
        if days is None:
            return None
        return max(1, round(window.credits_remaining / days))

    def _schedule_next_refresh(self) -> None:
        if self.after_id:
            self.root.after_cancel(self.after_id)
        delay_ms = self.interval_minutes * 60 * 1000
        force_session_recovery = self._should_force_session_recovery_on_next_refresh()
        if force_session_recovery:
            delay_ms = self.LOGIN_POLL_SECONDS * 1000
        self.after_id = self.root.after(
            delay_ms,
            lambda force=force_session_recovery: self.refresh(force=force),
        )

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
                self.request_resume_recovery("timer_gap")
        finally:
            self._schedule_resume_watchdog()

    def _on_power_suspend(self) -> None:
        self._write_ui_log("power_suspend")

    def _on_power_resume(self) -> None:
        self.request_resume_recovery("windows_power_resume")

    def _has_displayable_data(self) -> bool:
        return bool(self.last_snapshot and self.last_snapshot.has_data)

    def _has_pending_transient_failure(self) -> bool:
        return self._has_displayable_data() and getattr(self, "transient_failure_count", 0) > 0

    def _should_force_session_recovery_on_next_refresh(self) -> bool:
        return self._has_pending_transient_failure() or bool(self.last_snapshot and not self.last_snapshot.has_data)

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
        radius = max(0, min(radius, (x2 - x1) // 2, (y2 - y1) // 2))
        if radius <= 0:
            self.canvas.create_rectangle(
                self._s(x1),
                self._s(y1),
                self._s(x2),
                self._s(y2),
                fill=fill,
                outline=outline,
                width=max(1, self._s(width)),
                tags=tags,
            )
            return

        scaled_width = max(1, self._s(width))
        rects = (
            (x1 + radius, y1, x2 - radius, y2),
            (x1, y1 + radius, x2, y2 - radius),
        )
        arcs = (
            (x1, y1, x1 + radius * 2, y1 + radius * 2, 90),
            (x2 - radius * 2, y1, x2, y1 + radius * 2, 0),
            (x2 - radius * 2, y2 - radius * 2, x2, y2, 270),
            (x1, y2 - radius * 2, x1 + radius * 2, y2, 180),
        )
        for left, top, right, bottom in rects:
            self.canvas.create_rectangle(
                self._s(left),
                self._s(top),
                self._s(right),
                self._s(bottom),
                fill=fill,
                outline="",
                tags=tags,
            )
        for left, top, right, bottom, start in arcs:
            self.canvas.create_arc(
                self._s(left),
                self._s(top),
                self._s(right),
                self._s(bottom),
                start=start,
                extent=90,
                style=tk.PIESLICE,
                fill=fill,
                outline="",
                tags=tags,
            )
        if not outline:
            return

        self.canvas.create_line(
            self._s(x1 + radius),
            self._s(y1),
            self._s(x2 - radius),
            self._s(y1),
            fill=outline,
            width=scaled_width,
            tags=tags,
        )
        self.canvas.create_line(
            self._s(x2),
            self._s(y1 + radius),
            self._s(x2),
            self._s(y2 - radius),
            fill=outline,
            width=scaled_width,
            tags=tags,
        )
        self.canvas.create_line(
            self._s(x2 - radius),
            self._s(y2),
            self._s(x1 + radius),
            self._s(y2),
            fill=outline,
            width=scaled_width,
            tags=tags,
        )
        self.canvas.create_line(
            self._s(x1),
            self._s(y2 - radius),
            self._s(x1),
            self._s(y1 + radius),
            fill=outline,
            width=scaled_width,
            tags=tags,
        )
        for left, top, right, bottom, start in arcs:
            self.canvas.create_arc(
                self._s(left),
                self._s(top),
                self._s(right),
                self._s(bottom),
                start=start,
                extent=90,
                style=tk.ARC,
                outline=outline,
                width=scaled_width,
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

    def _fit_text_to_width(
        self,
        text: str,
        max_width: int,
        size: int = 8,
        weight: str = "normal",
        family: str | None = None,
    ) -> str:
        if max_width <= 0:
            return ""
        if self._measure_text(text, size, weight, family) <= max_width:
            return text
        ellipsis = "..."
        if self._measure_text(ellipsis, size, weight, family) > max_width:
            return ""
        fitted = text
        while fitted and self._measure_text(f"{fitted}{ellipsis}", size, weight, family) > max_width:
            fitted = fitted[:-1].rstrip()
        return f"{fitted}{ellipsis}" if fitted else ellipsis

    def _bar_line(self, x: int, y: int, width: int, color: str, thickness: int = 4, tags: str | tuple[str, ...] = ()) -> None:
        center_y = y + thickness / 2
        self.canvas.create_line(
            self._s(x),
            self._s(center_y),
            self._s(x + width),
            self._s(center_y),
            fill=color,
            width=max(1, self._s(thickness)),
            capstyle=tk.ROUND,
            tags=tags,
        )

    def _progress(self, x: int, y: int, width: int, percent: float | None, tags: str | tuple[str, ...] = ()) -> None:
        self._bar_line(x, y, width, "#3a3a40", tags=tags)
        if percent is None:
            return
        fill_width = min(width, max(0, int(width * max(0.0, min(1.0, percent / 100)))))
        if fill_width > 0:
            self._bar_line(x, y, fill_width, self._daily_progress_color(percent), tags=tags)

    @staticmethod
    def _mix_color(start: str, end: str, amount: float) -> str:
        amount = max(0.0, min(1.0, amount))
        start_rgb = tuple(int(start[index : index + 2], 16) for index in (1, 3, 5))
        end_rgb = tuple(int(end[index : index + 2], 16) for index in (1, 3, 5))
        mixed = tuple(round(start_rgb[index] + (end_rgb[index] - start_rgb[index]) * amount) for index in range(3))
        return f"#{mixed[0]:02x}{mixed[1]:02x}{mixed[2]:02x}"

    def _daily_progress_color(self, percent: float) -> str:
        if percent <= 50:
            return "#34c759"
        if percent <= 75:
            return "#ffcc00"
        return "#ff3b30"

    def _daily_progress(self, x: int, y: int, width: int, percent: float | None, tags: str | tuple[str, ...] = ()) -> None:
        if percent is not None and percent >= 100:
            self._bar_line(x - 2, y - 1, width + 4, "#4a2025", 6, tags=tags)
        self._bar_line(x, y, width, "#3a3a40", tags=tags)
        if percent is None:
            return
        fill_width = min(width, max(0, int(width * max(0.0, min(1.0, percent / 100)))))
        if fill_width <= 0:
            return
        color = self._daily_progress_color(percent)
        self._bar_line(x, y, fill_width, color, tags=tags)

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
        value = format_limit_value(window)
        reset = compact_reset_text(window.reset_text if window else None)
        percent = self._window_progress_percent(window)
        tooltip = self._limit_tooltip_text(label, window)
        value_tag = f"limit-value-{window_key(window) or fallback_label}"
        value_tags: str | tuple[str, ...] = value_tag
        if tooltip:
            self.tooltip_text_by_tag[value_tag] = tooltip
            value_tags = (value_tag, "tooltip-target")

        self._rounded_rect(5, y - 3, self.WIDTH - 5, y + 21, 6, "#2c2c30", "#3a3a40", tags=value_tags)
        self._text(10, y, label, "#f5f5f7", 9, "normal", family=self.UI_FONT)
        self._text(32, y, "остаток", "#8d8d95", 8, "normal", family=self.UI_FONT)
        self._text(128, y + 8, value, "#ffd166", 9, "bold", "center", tags=value_tags, family=self.NUMBER_FONT)
        self._text(212, y + 2, reset, "#b7b7bd", 8, "normal", "ne", family=self.UI_FONT)
        self._progress(31, y + 17, 178, percent)

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
        spent, limit, _floor, percent = values
        value = f"{short_number_clean(spent)}/{short_number_clean(limit)}"
        percent_text = compact_percent(percent)
        row_tag = "daily-limit-row"
        value_tag = "daily-limit-value"
        percent_tag = "daily-limit-percent"
        color = "#ff6961" if percent >= 100 else "#ffe082"
        percent_color = "#b7b7bd"

        self._rounded_rect(5, y - 3, self.WIDTH - 5, y + 21, 6, "#2c2c30", "#3a3a40", tags=row_tag)
        self._text(10, y, "лимит/день", "#8d8d95", 8, "normal", tags=row_tag, family=self.UI_FONT)
        self._text(128, y + 8, value, color, 9, "bold", "center", tags=(row_tag, value_tag), family=self.NUMBER_FONT)
        self._text(212, y + 2, percent_text, percent_color, 8, "normal", "ne", tags=(row_tag, percent_tag), family=self.UI_FONT)
        self._daily_progress(31, y + 17, 178, percent, tags=row_tag)

    def _render(self) -> None:
        if self._expire_daily_limit_if_needed():
            self._resize_window_to_scale()
        self.tooltip_text_by_tag = {}
        self.canvas.delete("all")
        content_height = self._content_height()
        self._rounded_rect(0, 0, self.WIDTH, content_height, self.WINDOW_CORNER_RADIUS, "#18181b")
        self._rounded_rect(1, 1, self.WIDTH - 1, content_height - 1, self.WINDOW_CORNER_RADIUS, "#202124", "#3a3a40")

        snapshot = self.last_snapshot
        if snapshot and not snapshot.has_data:
            message = snapshot.status_note or "нет данных"
            self._text(
                self.WIDTH // 2,
                content_height // 2,
                message,
                "#ffd166",
                9,
                "bold",
                "center",
                family=self.UI_FONT,
            )
            return

        account = snapshot.account if snapshot and snapshot.account else "Vibemode"
        plan_status = compact_plan_status(snapshot.plan_status if snapshot else None)
        plan_text = plan_status or self.status_text
        account_x = 12
        interval_right = self.WIDTH - 6
        interval_left = interval_right - 32
        header_right = interval_left - 4
        account_width = self._measure_text(account, 8, "bold", family=self.UI_FONT)
        account_max_width = max(42, min(account_width, header_right - account_x - 36))
        account = self._fit_text_to_width(account, account_max_width, 8, "bold", self.UI_FONT)
        account_width = self._measure_text(account, 8, "bold", family=self.UI_FONT)
        plan_x = account_x + account_width + 8
        plan_text = self._fit_text_to_width(plan_text, max(0, header_right - plan_x), 8, "normal", self.UI_FONT)
        pill_fill = "#2c2c30"
        pill_outline = "#3a3a40"
        self._text(12, 6, account, "#f5f5f7", 8, "bold", family=self.UI_FONT)
        if plan_status:
            self._text(plan_x, 6, plan_text, "#b7b7bd", 8, "normal", family=self.UI_FONT)
        else:
            self._text(plan_x, 6, plan_text, "#8d8d95", 8, "normal", family=self.UI_FONT)

        interval_center = (interval_left + interval_right) // 2
        self._rounded_rect(interval_left, 3, interval_right, 19, 5, pill_fill, pill_outline, tags="interval")
        self._text(
            interval_center,
            11,
            self._format_interval_pill(self.interval_minutes),
            "#b7b7bd",
            8,
            "normal",
            "center",
            tags="interval",
            family=self.UI_FONT,
        )

        self._draw_limit_row(25, "5ч", self._window_by_index(0))
        self._draw_limit_row(53, "7д", self._window_by_index(1))
        self._draw_daily_limit_row(81)

    def _apply_snapshot(self, snapshot: UsageSnapshot) -> None:
        now = datetime.now().astimezone()
        if not snapshot.has_data and self._hold_transient_failure(snapshot.status_note, now):
            self._render()
            return
        if self._hold_low_confidence_snapshot(snapshot, now):
            self._render()
            return
        if self._hold_incomplete_snapshot_regression(snapshot, now):
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
            f"cached={snapshot.is_cached} status={snapshot.status_note!r} "
            f"{self._snapshot_debug_summary(snapshot)}"
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
        print(f"Vibemode overlay error: {error}")

    def _write_ui_log(self, message: str) -> None:
        try:
            append_bounded_log(self.debug_log, f"{datetime.now().isoformat(timespec='seconds')} {message}\n")
        except Exception:
            pass

    def _read_snapshot(self, *, force_session_recovery: bool = False) -> UsageSnapshot:
        try:
            return self.reader(force_session_recovery=force_session_recovery)  # type: ignore[call-arg]
        except TypeError as exc:
            if "force_session_recovery" not in str(exc):
                raise
            return self.reader()

    def _finish_refresh(
        self,
        snapshot: UsageSnapshot | None = None,
        error: object | None = None,
        generation: int | None = None,
    ) -> None:
        if not self._finish_refresh_tracking(generation):
            return
        try:
            if error is not None:
                self._apply_error(error)
            elif snapshot is not None:
                self._apply_snapshot(snapshot)
        finally:
            self.refreshing = False
            self._schedule_next_refresh()

    def _refresh_in_background(self, force_session_recovery: bool = False, generation: int | None = None) -> None:
        try:
            snapshot = self._read_snapshot(force_session_recovery=force_session_recovery)
        except Exception as exc:  # noqa: BLE001 - show operational errors without crashing.
            try:
                self.root.after(0, lambda error=exc, gen=generation: self._finish_refresh(error=error, generation=gen))
            except tk.TclError:
                self.refreshing = False
            return
        try:
            self.root.after(
                0,
                lambda result=snapshot, gen=generation: self._finish_refresh(snapshot=result, generation=gen),
            )
        except tk.TclError:
            self.refreshing = False

    def refresh(self, force: bool = False) -> None:
        now = datetime.now().astimezone()
        self._write_ui_log(f"refresh_requested force={force} refreshing={self.refreshing}")
        if self.refreshing:
            if not force or not self._can_start_forced_refresh(now, "forced_refresh"):
                self._write_ui_log(f"refresh_skipped force={force} refreshing=True")
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
        generation = self._begin_refresh_tracking(now)
        self._write_ui_log(f"refresh_started force={force} generation={generation}")
        if not has_fresh_data:
            self.status_text = "обновляю"
            self._render()
        if getattr(self, "async_refresh", False):
            threading.Thread(target=self._refresh_in_background, args=(force, generation), daemon=True).start()
            return
        self.root.update_idletasks()
        try:
            self._finish_refresh(
                snapshot=self._read_snapshot(force_session_recovery=force),
                generation=generation,
            )
        except Exception as exc:  # noqa: BLE001 - show operational errors without crashing.
            self._finish_refresh(error=exc, generation=generation)

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
        handle = getattr(self, "power_event_handle", None)
        if handle is not None:
            try:
                handle.uninstall()
            except Exception:
                pass
            self.power_event_handle = None
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

    class MenuBarOverlay(_ResumeRecoveryOverlayMixin):
        """macOS menu bar status item showing Vibemode usage.

        Displays a compact title (e.g. "NG 82.3M") in the menu bar; clicking it
        reveals a dropdown with per-window limits, settings, and actions.
        """

        INTERVAL_CHOICES_MINUTES = UsageOverlay.INTERVAL_CHOICES_MINUTES
        MIN_REFRESH_SECONDS = UsageOverlay.MIN_REFRESH_SECONDS
        UPDATE_CHECK_SECONDS = UsageOverlay.UPDATE_CHECK_SECONDS
        RESUME_HEARTBEAT_SECONDS = UsageOverlay.RESUME_HEARTBEAT_SECONDS
        RESUME_GAP_SECONDS = UsageOverlay.RESUME_GAP_SECONDS
        STALE_REFRESH_SECONDS = UsageOverlay.STALE_REFRESH_SECONDS
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
            self.theme = self._load_theme()
            self.last_snapshot: UsageSnapshot | None = None
            self.last_refresh_at: datetime | None = None
            self.last_resume_check_at: datetime | None = None
            self._keep_browser_open_override: bool | None = None
            self.refreshing = False
            self.resume_recovery = ResumeRefreshCoordinator(self.STALE_REFRESH_SECONDS)
            self.resume_recovery_state = self.resume_recovery
            self.refresh_started_at: datetime | None = None
            self.refresh_generation = 0
            self.resume_recovery_pending = False
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
            self._power_observer: object | None = None

            from .popover_server import PopoverServer
            from .macos_popover import MenuBarPopover
            self._server = PopoverServer()
            self._popover_ui: MenuBarPopover | None = None
            self._PopoverServer = PopoverServer
            self._MenuBarPopover = MenuBarPopover
            self._register_server_actions()

        # ------------------------------------------------------------------ state helpers

        def _load_state(self) -> dict[str, object]:
            return load_json_object(self.state_file)

        def _save_state(self, updates: dict[str, object]) -> None:
            try:
                update_json_object_atomic(self.state_file, updates)
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

        def _load_theme(self) -> str:
            try:
                value = self._load_state().get("popover_theme")
                return "dark" if value == "dark" else "light"
            except Exception:
                return "light"

        def _save_theme(self) -> None:
            self._save_state({"popover_theme": self.theme})

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
            if self._keep_browser_open_override is not None:
                return self._keep_browser_open_override
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

        def _should_force_session_recovery_on_next_refresh(self) -> bool:
            return self._has_pending_transient_failure() or bool(self.last_snapshot and not self.last_snapshot.has_data)

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

        def _read_snapshot(self, *, force_session_recovery: bool = False) -> UsageSnapshot:
            try:
                return self.reader(force_session_recovery=force_session_recovery)  # type: ignore[call-arg]
            except TypeError as exc:
                if "force_session_recovery" not in str(exc):
                    raise
                return self.reader()

        # ------------------------------------------------------------------ title helpers

        def _menu_bar_title(self) -> str:
            snap = self.last_snapshot
            if not snap or not snap.has_data:
                return "..."
            daily = self._daily_limit_values()
            if daily:
                spent, limit, _floor, _percent = daily
                return f"{menu_bar_number(spent)}/{menu_bar_number(limit)}"
            window = find_window(snap, "5h") or (snap.windows[0] if snap.windows else None)
            if window and window.credits_remaining is not None:
                return menu_bar_number(window.credits_remaining)
            if snap.remaining is not None:
                return menu_bar_number(snap.remaining)
            return "..."

        def _menu_bar_progress_percent(self) -> float | None:
            snap = self.last_snapshot
            if not snap or not snap.has_data:
                return None
            daily = self._daily_limit_values()
            if daily:
                _spent, _limit, _floor, percent = daily
                return max(0.0, min(100.0, percent))
            window = find_window(snap, "5h") or (snap.windows[0] if snap.windows else None)
            if not window:
                return None
            percent = window.progress_percent if window.progress_percent is not None else window.limit_percent
            if percent is None:
                return None
            return max(0.0, min(100.0, float(percent)))

        # ------------------------------------------------------------------ server actions

        def _register_server_actions(self) -> None:
            self._server.on_action("refresh", lambda _payload: self.refresh(force=True))
            self._server.on_action("hide_daily", self._on_hide_daily_limit)
            self._server.on_action("set_daily", self._on_set_daily_limit)
            self._server.on_action("set_interval", self._on_set_interval_from_payload)
            self._server.on_action("toggle_theme", self._on_toggle_theme)
            self._server.on_action("reset_account", self._on_reset_account)
            self._server.on_action("update", self._on_start_update)
            self._server.on_action("restart", self._on_restart)
            self._server.on_action("quit", lambda _payload: self.close())
            self._server.on_resize(lambda h: self._pending.put(("resize", h)))

        def _push_server_data(self) -> None:
            self._expire_daily_limit_if_needed()
            snap = self.last_snapshot
            interval_label = UsageOverlay._format_interval_menu(self.interval_minutes)
            interval_choices = [
                {
                    "minutes": value,
                    "label": UsageOverlay._format_interval_pill(value),
                    "menu_label": UsageOverlay._format_interval_menu(value),
                }
                for value in self.INTERVAL_CHOICES_MINUTES
            ]
            extra = {
                "daily_limit_enabled": self._daily_limit_enabled(),
                "daily_limit": self._daily_limit_payload(),
                "daily_limit_default": self._daily_limit_default_label(),
                "interval_label": interval_label,
                "interval_minutes": self.interval_minutes,
                "interval_choices": interval_choices,
                "theme": self.theme,
                "has_account_reset": bool(self.account_resetter),
                "version_label": version_menu_label(__version__, self.update_info),
                "version_update_available": bool(self.update_info),
            }
            self._server.update(snap, extra)
            if self._popover_ui:
                title = self._menu_bar_title()
                self._popover_ui.set_status(title, self._menu_bar_progress_percent())

        # ------------------------------------------------------------------ callbacks

        def _on_set_interval(self, minutes: int) -> None:
            self.interval_minutes = UsageOverlay._normalize_interval_minutes(minutes)
            self._save_interval_minutes()
            self._reschedule_timer()
            self._push_server_data()

        def _on_set_interval_from_payload(self, payload: dict[str, object]) -> None:
            try:
                minutes = int(payload.get("minutes") or self.interval_minutes)
            except (TypeError, ValueError):
                minutes = self.interval_minutes
            self._on_set_interval(minutes)

        def _on_toggle_theme(self, _payload: dict[str, object]) -> None:
            self.theme = "light" if self.theme == "dark" else "dark"
            self._save_theme()
            self._push_server_data()

        def _on_hide_daily_limit(self, _payload: dict[str, object]) -> None:
            self.daily_limit_credits = None
            self.daily_limit_set_at = None
            self._save_daily_limit()
            self._push_server_data()

        def _on_set_daily_limit(self, payload: dict[str, object]) -> None:
            value = payload.get("value")
            parsed = UsageOverlay._parse_credit_input(str(value or ""))
            if parsed is None:
                self._write_ui_log(f"daily_limit_parse_error value={value!r}")
                return
            self.daily_limit_credits = parsed
            self.daily_limit_set_at = datetime.now().astimezone()
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
                days = UsageOverlay._seven_day_daily_limit_divisor_days(window.reset_text, self.last_snapshot.plan_status)
                if days is None:
                    return None
                return max(1, round(window.credits_remaining / days))
            return None

        def _daily_limit_default_label(self) -> str:
            if self._daily_limit_enabled() and self.daily_limit_credits:
                return short_number_clean(self.daily_limit_credits)
            default = self._default_daily_limit_credits()
            return short_number_clean(default) if default else ""

        def _daily_limit_values(self) -> tuple[int, int, int, float] | None:
            if not self._daily_limit_enabled() or not self.last_snapshot:
                return None
            limit = self.daily_limit_credits
            if not limit:
                return None
            today_spent = self.daily_usage.today_spent_7d(self.last_snapshot)
            spent = today_spent.amount if today_spent is not None else 0
            window = find_window(self.last_snapshot, "7d")
            floor = max(0, (window.credits_remaining if window and window.credits_remaining is not None else 0) - limit)
            percent = min(999.0, (spent / limit) * 100)
            return spent, limit, floor, percent

        def _daily_limit_payload(self) -> dict[str, object] | None:
            values = self._daily_limit_values()
            if not values:
                return None
            spent, limit, floor, percent = values
            return {
                "spent": spent,
                "limit": limit,
                "floor": floor,
                "percent": percent,
                "spent_label": short_number_clean(spent),
                "limit_label": short_number_clean(limit),
            }

        def _on_reset_account(self, _payload: dict[str, object]) -> None:
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

        def _on_cycle_interval(self, _payload: dict[str, object] | None = None) -> None:
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

        def _on_start_update(self, _payload: dict[str, object]) -> None:
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

        def _on_restart(self, _payload: dict[str, object]) -> None:
            root = Path(__file__).resolve().parents[2]
            state_dir = Path.home() / ".neurogate-usage-overlay"
            log_path = Path.home() / ".neurogate-usage-overlay" / "restart.log"
            runner_command = f"cd {shlex.quote(str(root))} && exec bash scripts/run-overlay.sh >> {shlex.quote(str(log_path))} 2>&1"
            script_path = state_dir / "restart-vibemode.sh"
            script = "\n".join(
                [
                    "#!/usr/bin/env bash",
                    "set -u",
                    "sleep 5",
                    "/usr/bin/screen -S vibemode -X quit 2>/dev/null || true",
                    "/usr/bin/screen -wipe >/dev/null 2>&1 || true",
                    f"/usr/bin/screen -dmS vibemode bash -lc {shlex.quote(runner_command)}",
                    "",
                ]
            )
            try:
                state_dir.mkdir(parents=True, exist_ok=True)
                script_path.write_text(script, encoding="utf-8")
                script_path.chmod(0o700)
                subprocess.Popen(
                    ["/bin/bash", str(script_path)],
                    stdin=subprocess.DEVNULL,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    start_new_session=True,
                    close_fds=True,
                )
            except Exception as exc:
                self._write_ui_log(f"restart_error {exc!r}")
                return
            self.close()

        # ------------------------------------------------------------------ refresh logic

        def _on_power_sleep(self) -> None:
            self._write_ui_log("power_suspend")

        def _on_power_wake(self) -> None:
            self.request_resume_recovery("macos_workspace_wake")

        def refresh(self, force: bool = False) -> None:
            now = datetime.now().astimezone()
            self._write_ui_log(f"refresh_requested force={force} refreshing={self.refreshing}")
            if self.refreshing:
                if not force or not self._can_start_forced_refresh(now, "forced_refresh"):
                    self._write_ui_log(f"refresh_skipped force={force} refreshing=True")
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
            generation = self._begin_refresh_tracking(now)
            self._write_ui_log(f"refresh_started force={force} generation={generation}")
            if self.async_refresh:
                threading.Thread(target=self._refresh_in_background, args=(force, generation), daemon=True).start()
            else:
                try:
                    self._finish_refresh(
                        snapshot=self._read_snapshot(force_session_recovery=force),
                        generation=generation,
                    )
                except Exception as exc:
                    self._finish_refresh(error=exc, generation=generation)

        def _refresh_in_background(self, force_session_recovery: bool = False, generation: int | None = None) -> None:
            self._write_ui_log("refresh_background_start")
            try:
                snapshot = self._read_snapshot(force_session_recovery=force_session_recovery)
            except Exception as exc:
                self._write_ui_log(f"refresh_background_error {exc!r}")
                self._pending.put(("error", exc, generation))
                return
            self._write_ui_log(f"refresh_background_done has_data={snapshot.has_data}")
            self._pending.put(("snapshot", snapshot, generation))

        def _finish_refresh(
            self,
            snapshot: UsageSnapshot | None = None,
            error: object | None = None,
            generation: int | None = None,
        ) -> None:
            if not self._finish_refresh_tracking(generation):
                return
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
            if self._hold_low_confidence_snapshot(snapshot, now):
                self._push_server_data()
                return
            if self._hold_incomplete_snapshot_regression(snapshot, now):
                self._push_server_data()
                return
            self.last_snapshot = snapshot
            self.last_refresh_at = now
            if snapshot.has_data:
                self._clear_transient_failure()
                self.daily_usage.record_snapshot(snapshot, self.last_refresh_at)
            self._write_ui_log(
                f"snapshot account={snapshot.account!r} total={snapshot.total_used} "
                f"remaining={snapshot.remaining} windows={len(snapshot.windows)} "
                f"cached={snapshot.is_cached} status={snapshot.status_note!r} "
                f"{self._snapshot_debug_summary(snapshot)}"
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
                self._popover_ui.set_status("!", None)

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
        def _make_ns_timer(interval: float, callback: "Callable[[], None]", *, repeats: bool = True) -> object:
            """Schedule an NSTimer on the main run loop."""
            target = _TimerTarget.alloc().init()
            target.setup_(callback)
            timer = _NSTimer.scheduledTimerWithTimeInterval_target_selector_userInfo_repeats_(
                interval,
                target,
                _objc.selector(target.fire_, selector=b"fire:", signature=b"v@:@"),
                None,
                repeats,
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
                    generation = item[2] if len(item) > 2 else None
                    if kind == "snapshot":
                        self._finish_refresh(snapshot=value, generation=generation)
                    elif kind == "error":
                        self._finish_refresh(error=value, generation=generation)
                    elif kind == "resize":
                        if self._popover_ui:
                            self._popover_ui.resize_to_content(value)
                    elif kind == "update_check":
                        self.update_check_running = False
                        self.update_info = value
                        self._push_server_data()
                        self._make_ns_timer(self.UPDATE_CHECK_SECONDS, self.check_for_updates, repeats=False)
            except Exception:
                pass

        # ------------------------------------------------------------------ refresh timer

        def _reschedule_timer(self) -> None:
            self._cancel_ns_timer(self._ns_timer)
            delay = self.interval_minutes * 60
            force_session_recovery = self._should_force_session_recovery_on_next_refresh()
            if force_session_recovery:
                delay = 2

            def _tick() -> None:
                self._cancel_ns_timer(self._ns_timer)
                self._ns_timer = None
                self.refresh(force=force_session_recovery)

            self._ns_timer = self._make_ns_timer(delay, _tick, repeats=False)

        # ------------------------------------------------------------------ run / close

        def run(self) -> None:
            from AppKit import NSApplication, NSApp
            from Foundation import NSTimer, NSRunLoop, NSDefaultRunLoopMode

            app = NSApplication.sharedApplication()
            app.setActivationPolicy_(1)  # NSApplicationActivationPolicyAccessory: no Dock icon

            # Install the popover status item on main thread
            self._popover_ui = self._MenuBarPopover(
                server_url=self._server.get_url(),
                initial_title="...",
            )
            self._popover_ui.install()

            # Poll timer: drains background refresh results every 0.5s on main thread
            self._ns_poll_timer = self._make_ns_timer(0.5, self._drain_pending)

            self._power_observer = install_macos_power_observer(
                on_sleep=self._on_power_sleep,
                on_wake=self._on_power_wake,
            )

            # Resume watchdog
            self._resume_ns_timer = self._make_ns_timer(
                self.RESUME_HEARTBEAT_SECONDS, self._on_resume_watchdog_ns
            )

            # Kick off first refresh and update check after a short delay
            self._make_ns_timer(0.5, self._initial_refresh, repeats=False)
            self._make_ns_timer(1.2, self._initial_update_check, repeats=False)

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
                self.request_resume_recovery("timer_gap")

        def close(self) -> None:
            self._cancel_ns_timer(self._ns_timer)
            self._cancel_ns_timer(getattr(self, "_ns_poll_timer", None))
            self._cancel_ns_timer(self._resume_ns_timer)
            if self._power_observer is not None:
                try:
                    self._power_observer.uninstall()  # type: ignore[attr-defined]
                except Exception:
                    pass
                self._power_observer = None
            if self._popover_ui:
                self._popover_ui.remove()
            self._server.stop()
            from AppKit import NSApp
            NSApp.terminate_(None)
