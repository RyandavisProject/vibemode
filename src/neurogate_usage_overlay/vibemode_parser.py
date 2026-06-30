from __future__ import annotations

import re
from datetime import datetime
from typing import Any

from .models import UsageSnapshot, UsageWindow


def _as_int(value: object) -> int | None:
    if value is None:
        return None
    try:
        return round(float(value))
    except (TypeError, ValueError):
        return None


def _format_plan_days_left(value: object, now: datetime | None = None) -> str | None:
    if not value:
        return None
    try:
        ends_at = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    current = now or datetime.now().astimezone()
    if ends_at.tzinfo is None:
        ends_at = ends_at.replace(tzinfo=current.tzinfo)
    delta_seconds = (ends_at - current).total_seconds()
    if delta_seconds <= 0:
        return "истёк"
    days = max(1, int((delta_seconds + 86_399) // 86_400))
    return f"{days} дн осталось"


def _parse_iso_datetime(value: object) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    current = datetime.now().astimezone()
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=current.tzinfo)
    return parsed


def _format_window_reset_text(value: object, now: datetime | None = None) -> str | None:
    ends_at = _parse_iso_datetime(value)
    if not ends_at:
        return None
    current = now or datetime.now().astimezone()
    if ends_at.tzinfo is None:
        ends_at = ends_at.replace(tzinfo=current.tzinfo)
    total_minutes = int((ends_at - current).total_seconds() + 59) // 60
    if total_minutes <= 0:
        return None
    days, remainder = divmod(total_minutes, 24 * 60)
    hours, minutes = divmod(remainder, 60)
    if days:
        return f"{days}д {hours}ч" if hours else f"{days}д"
    if hours:
        return f"{hours}ч {minutes}м" if minutes else f"{hours}ч"
    return f"{minutes}м"


def _vibemode_window(
    title: str,
    used_value: object,
    total_value: object,
    *,
    reset_text: str | None = None,
) -> UsageWindow | None:
    used = _as_int(used_value)
    total = _as_int(total_value)
    if total is None or total <= 0:
        return None
    used = max(0, used or 0)
    remaining = max(0, total - used)
    return UsageWindow(
        title=title,
        limit_used=used,
        limit_total=total,
        credits_remaining=remaining,
        reset_text=reset_text,
        progress_percent=min(100.0, (used / total) * 100),
    )


def _parse_vibemode_amount(value: str | None) -> int | None:
    if not value:
        return None
    cleaned = value.strip().replace("\u00a0", " ").replace(",", ".")
    match = re.search(r"(\d+(?:\.\d+)?)\s*([kкmмbб])?", cleaned, flags=re.IGNORECASE)
    if not match:
        return None
    amount = float(match.group(1))
    suffix = (match.group(2) or "").lower()
    multiplier = 1
    if suffix in {"k", "к"}:
        multiplier = 1_000
    elif suffix in {"m", "м"}:
        multiplier = 1_000_000
    elif suffix in {"b", "б"}:
        multiplier = 1_000_000_000
    return round(amount * multiplier)


def _vibemode_text_window(title: str, text: str) -> UsageWindow | None:
    label = "5-часовое окно" if "5" in title else "7-дневное окно"
    match = re.search(
        rf"{re.escape(label)}(?P<segment>.*?)(?:\n\s*(?:КВОТА|CLAUDE|АКТИВНОСТЬ)\b|\Z)",
        text,
        flags=re.IGNORECASE | re.DOTALL,
    )
    if not match:
        return None
    segment = match.group("segment")
    reset_text = _vibemode_reset_text_from_segment(segment)
    used_total = re.search(
        r"(?P<used>\d+(?:[.,]\d+)?\s*[kкmмbб]?)\s*\n\s*из\s+(?P<total>\d+(?:[.,]\d+)?\s*[kкmмbб]?)",
        segment,
        flags=re.IGNORECASE,
    )
    if not used_total:
        return None
    return _vibemode_window(
        title,
        _parse_vibemode_amount(used_total.group("used")),
        _parse_vibemode_amount(used_total.group("total")),
        reset_text=reset_text,
    )


def _vibemode_reset_text_from_segment(segment: str) -> str | None:
    match = re.search(r"Сброс\s+через\s+([^\n\r]+)", segment, flags=re.IGNORECASE)
    return match.group(1).strip() if match else None


def _vibemode_window_key(title: str) -> str:
    if "5" in title:
        return "5h"
    if "7" in title:
        return "7d"
    return title.strip().lower()


def _row_scope(row: dict[str, Any]) -> str:
    scope = str(row.get("scope") or "").strip()
    return scope or "default"


def _profile_usage_rows(profile: dict[str, Any] | None) -> list[dict[str, Any]]:
    usage = profile.get("usage") if isinstance(profile, dict) else None
    rows = usage.get("rows") if isinstance(usage, dict) else None
    return [row for row in rows if isinstance(row, dict)] if isinstance(rows, list) else []


def _limit_rows(limits: dict[str, Any] | None) -> list[dict[str, Any]]:
    rows = limits.get("rows") if isinstance(limits, dict) else None
    return [row for row in rows if isinstance(row, dict)] if isinstance(rows, list) else []


def _merged_usage_rows(profile: dict[str, Any] | None, limits: dict[str, Any] | None) -> list[dict[str, Any]]:
    merged_by_scope: dict[str, dict[str, Any]] = {}
    order: list[str] = []
    for row in _profile_usage_rows(profile):
        scope = _row_scope(row)
        if scope not in merged_by_scope:
            order.append(scope)
        merged_by_scope[scope] = dict(row)
    for row in _limit_rows(limits):
        scope = _row_scope(row)
        if scope not in merged_by_scope:
            order.append(scope)
            merged_by_scope[scope] = dict(row)
            continue
        merged_by_scope[scope] = {**merged_by_scope[scope], **row}
    return [merged_by_scope[scope] for scope in order]


def _window_reset_text(row: dict[str, Any], key: str, now: datetime | None = None) -> str | None:
    if key == "5h":
        return _format_window_reset_text(
            row.get("window5HoursEndsAt")
            or row.get("window_5_hours_ends_at")
            or row.get("window5hEndsAt")
            or row.get("window_5h_ends_at"),
            now,
        )
    if key == "7d":
        return _format_window_reset_text(
            row.get("window7DaysEndsAt")
            or row.get("window_7_days_ends_at")
            or row.get("window7dEndsAt")
            or row.get("window_7d_ends_at"),
            now,
        )
    return None


def _vibemode_reset_texts(text: str) -> dict[str, str]:
    resets: dict[str, str] = {}
    for title in ("5 часов", "7 дней"):
        label = "5-часовое окно" if "5" in title else "7-дневное окно"
        match = re.search(
            rf"{re.escape(label)}(?P<segment>.*?)(?:\n\s*(?:КВОТА|CLAUDE|АКТИВНОСТЬ)\b|\Z)",
            text,
            flags=re.IGNORECASE | re.DOTALL,
        )
        if not match:
            continue
        reset_text = _vibemode_reset_text_from_segment(match.group("segment"))
        if reset_text:
            resets[_vibemode_window_key(title)] = reset_text
    return resets


def _attach_vibemode_reset_texts(snapshot: UsageSnapshot, text: str) -> None:
    if not text or not snapshot.windows:
        return
    resets = _vibemode_reset_texts(text)
    if not resets:
        return
    for window in snapshot.windows:
        if not window.reset_text:
            window.reset_text = resets.get(_vibemode_window_key(window.title))


def _snapshot_from_vibemode_text(text: str, *, source_url: str | None) -> UsageSnapshot | None:
    if "5-часовое окно" not in text.lower() or "7-дневное окно" not in text.lower():
        return None

    snapshot = UsageSnapshot(
        updated_at=datetime.now().astimezone(),
        source_url=source_url,
        raw_text=text,
    )

    lines = [line.strip() for line in text.splitlines() if line.strip()]
    for index, line in enumerate(lines):
        if line.lower() == "план" and index + 1 < len(lines):
            snapshot.account = lines[index + 1]
            if index + 2 < len(lines) and "остал" in lines[index + 2].lower():
                snapshot.plan_status = lines[index + 2].lower()
            break

    windows = [
        _vibemode_text_window("5 часов", text),
        _vibemode_text_window("7 дней", text),
    ]
    snapshot.windows = [window for window in windows if window is not None]
    return snapshot if snapshot.has_data or snapshot.account else None


def _snapshot_from_vibemode_api(
    profile: dict[str, Any] | None,
    limits: dict[str, Any] | None,
    *,
    source_url: str | None,
    raw_text: str = "",
    now: datetime | None = None,
) -> UsageSnapshot | None:
    if not profile and not limits:
        return None

    snapshot = UsageSnapshot(
        updated_at=datetime.now().astimezone(),
        source_url=source_url,
        raw_text=raw_text,
    )

    plan = profile.get("plan") if isinstance(profile, dict) else None
    if isinstance(plan, dict):
        snapshot.account = str(plan.get("name") or plan.get("code") or "").strip() or None
        snapshot.plan_status = _format_plan_days_left(plan.get("endsAt"), now=now)
    elif isinstance(profile, dict):
        plan_code = str(profile.get("currentPlanCode") or "").strip()
        snapshot.account = plan_code.capitalize() if plan_code else None
        snapshot.plan_status = _format_plan_days_left(profile.get("currentPlanEndsAt"), now=now)

    rows = _merged_usage_rows(profile, limits)
    if not rows:
        return snapshot if snapshot.account else None

    default_row = next(
        (
            row
            for row in rows
            if isinstance(row, dict)
            and row.get("scope") == "default"
            and (_as_int(row.get("creditLimit5Hours")) or _as_int(row.get("creditLimit7Days")))
        ),
        None,
    )
    if default_row is None:
        default_row = next(
            (
                row
                for row in rows
                if isinstance(row, dict)
                and (_as_int(row.get("creditLimit5Hours")) or _as_int(row.get("creditLimit7Days")))
            ),
            None,
        )
    if not isinstance(default_row, dict):
        return snapshot if snapshot.account else None

    five_hour = _vibemode_window(
        "5 часов",
        default_row.get("credits5Hours"),
        default_row.get("creditLimit5Hours"),
        reset_text=_window_reset_text(default_row, "5h", now),
    )
    seven_day = _vibemode_window(
        "7 дней",
        default_row.get("credits7Days"),
        default_row.get("creditLimit7Days"),
        reset_text=_window_reset_text(default_row, "7d", now),
    )
    snapshot.windows = [window for window in (five_hour, seven_day) if window is not None]
    _attach_vibemode_reset_texts(snapshot, raw_text)
    return snapshot if snapshot.has_data or snapshot.account else None
