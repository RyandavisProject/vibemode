from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime


@dataclass(slots=True)
class UsageWindow:
    title: str
    tokens: int | None = None
    cache: int | None = None
    limit_used: int | None = None
    limit_total: int | None = None
    credits_remaining: int | None = None
    reset_text: str | None = None

    @property
    def limit_percent(self) -> float | None:
        if not self.limit_used or not self.limit_total:
            return None
        if self.limit_total <= 0:
            return None
        return min(999.0, (self.limit_used / self.limit_total) * 100)

    @property
    def display_value(self) -> int | None:
        if self.credits_remaining is not None:
            return self.credits_remaining
        if self.limit_used is not None:
            return self.limit_used
        return None


@dataclass(slots=True)
class UsageSnapshot:
    updated_at: datetime
    account: str | None = None
    model_group: str | None = None
    total_used: int | None = None
    remaining: int | None = None
    plan_status: str | None = None
    windows: list[UsageWindow] = field(default_factory=list)
    source_url: str | None = None
    raw_text: str = ""
    is_cached: bool = False
    status_note: str | None = None

    @property
    def has_data(self) -> bool:
        return bool(self.total_used or self.remaining or self.windows)
