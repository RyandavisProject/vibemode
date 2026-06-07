from __future__ import annotations

import math
import re
from datetime import timedelta

from .models import UsageSnapshot, UsageWindow


FIVE_HOUR_CREDIT_LIMIT = 120_000_000
SEVEN_DAY_CREDIT_LIMIT = 600_000_000


def parse_duration(text: str | None) -> timedelta | None:
    if not text:
        return None
    days = hours = minutes = 0
    for amount, unit in re.findall(r"(\d+)\s*([дdчhмm]|мин)", text.lower()):
        value = int(amount)
        if unit in {"д", "d"}:
            days += value
        elif unit in {"ч", "h"}:
            hours += value
        else:
            minutes += value
    if days == hours == minutes == 0:
        return None
    return timedelta(days=days, hours=hours, minutes=minutes)


def parse_plan_remaining(text: str | None) -> timedelta | None:
    if not text:
        return None
    cleaned = text.lower().replace("активен ещё", "").replace("активен еще", "").strip()
    return parse_duration(cleaned)


def find_window(snapshot: UsageSnapshot, marker: str) -> UsageWindow | None:
    marker = marker.lower()
    for window in snapshot.windows:
        if marker in window.title.lower():
            return window
    return None


def projected_window_capacity(
    current_remaining: int | None,
    reset_text: str | None,
    plan_remaining_text: str | None,
    window_limit: int,
    period: timedelta,
) -> int | None:
    if current_remaining is None:
        return None
    plan_remaining = parse_plan_remaining(plan_remaining_text)
    if not plan_remaining or plan_remaining <= timedelta(0):
        return current_remaining

    reset_remaining = parse_duration(reset_text)
    if not reset_remaining or reset_remaining > plan_remaining:
        return current_remaining

    remaining_after_first_reset = plan_remaining - reset_remaining
    future_resets = 1 + math.floor(remaining_after_first_reset / period)
    return current_remaining + future_resets * window_limit


def projected_spendable_credits(snapshot: UsageSnapshot) -> int | None:
    five_hour = find_window(snapshot, "5")
    seven_day = find_window(snapshot, "7")
    if not five_hour or not seven_day:
        return None

    five_hour_capacity = projected_window_capacity(
        five_hour.credits_remaining,
        five_hour.reset_text,
        snapshot.plan_status,
        FIVE_HOUR_CREDIT_LIMIT,
        timedelta(hours=5),
    )
    seven_day_capacity = projected_window_capacity(
        seven_day.credits_remaining,
        seven_day.reset_text,
        snapshot.plan_status,
        SEVEN_DAY_CREDIT_LIMIT,
        timedelta(days=7),
    )

    capacities = [item for item in (five_hour_capacity, seven_day_capacity) if item is not None]
    if not capacities:
        return None
    return min(capacities)
