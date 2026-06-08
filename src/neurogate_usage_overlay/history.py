from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from .models import UsageSnapshot, UsageWindow


@dataclass(frozen=True, slots=True)
class TodaySpend:
    amount: int
    since_text: str


def window_key(window: UsageWindow | None) -> str:
    if not window:
        return ""
    title = window.title.lower()
    if "5" in title and "час" in title:
        return "5h"
    if "24" in title and "час" in title:
        return "24h"
    if "7" in title and "д" in title:
        return "7d"
    return title.strip()


def find_window(snapshot: UsageSnapshot, key: str) -> UsageWindow | None:
    for window in snapshot.windows:
        if window_key(window) == key:
            return window
    return None


def spent_since_reset(window: UsageWindow | None) -> int | None:
    if not window:
        return None
    if window.limit_used is not None:
        return max(0, window.limit_used)
    if window.limit_total is not None and window.credits_remaining is not None:
        return max(0, window.limit_total - window.credits_remaining)
    if window.credits_remaining is None or window.progress_percent is None:
        return None

    progress = max(0.0, min(100.0, float(window.progress_percent)))
    if progress <= 0:
        return 0
    if progress >= 100:
        return None
    return max(0, round(window.credits_remaining * progress / (100.0 - progress)))


class DailyUsageStore:
    def __init__(self, path: Path) -> None:
        self.path = path

    def record_snapshot(self, snapshot: UsageSnapshot, now: datetime | None = None) -> None:
        window = find_window(snapshot, "7d")
        if not window or window.credits_remaining is None:
            return
        now = now or datetime.now().astimezone()
        today = now.date().isoformat()
        current = window.credits_remaining
        payload = self._load()

        if payload.get("date") != today:
            payload = self._new_payload(today, current, now)
        else:
            first = self._to_int(payload.get("first_7d_remaining"))
            if first is None or current > first:
                payload = self._new_payload(today, current, now)
            elif not payload.get("first_seen_at"):
                payload = self._new_payload(today, current, now)
            else:
                payload["last_7d_remaining"] = current

        self._save(payload)

    def today_spent_7d(self, snapshot: UsageSnapshot, now: datetime | None = None) -> TodaySpend | None:
        window = find_window(snapshot, "7d")
        if not window or window.credits_remaining is None:
            return None
        today = (now or datetime.now().astimezone()).date().isoformat()
        payload = self._load()
        if payload.get("date") != today:
            return TodaySpend(0, "--:--")
        first = self._to_int(payload.get("first_7d_remaining"))
        if first is None:
            return None
        return TodaySpend(
            amount=max(0, first - window.credits_remaining),
            since_text=self._format_since_time(payload.get("first_seen_at")),
        )

    def _load(self) -> dict[str, object]:
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
            return payload if isinstance(payload, dict) else {}
        except Exception:
            return {}

    def _save(self, payload: dict[str, object]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")

    @staticmethod
    def _new_payload(today: str, remaining: int, first_seen_at: datetime) -> dict[str, object]:
        return {
            "date": today,
            "first_seen_at": first_seen_at.isoformat(timespec="seconds"),
            "first_7d_remaining": remaining,
            "last_7d_remaining": remaining,
        }

    @staticmethod
    def _to_int(value: object) -> int | None:
        try:
            return int(value)
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _format_since_time(value: object) -> str:
        if not isinstance(value, str):
            return "--:--"
        try:
            return datetime.fromisoformat(value).strftime("%H:%M")
        except ValueError:
            return "--:--"
