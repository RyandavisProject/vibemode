from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta


@dataclass(frozen=True)
class ResumeRecoveryDecision:
    start_refresh: bool = False
    wait_for_active_refresh: bool = False
    abandoned_generation: int | None = None


@dataclass
class ResumeRefreshCoordinator:
    stale_refresh_seconds: int
    refresh_started_at: datetime | None = None
    refresh_generation: int = 0
    resume_recovery_pending: bool = False

    def begin_refresh(self, now: datetime) -> int:
        self.refresh_generation += 1
        self.refresh_started_at = now
        return self.refresh_generation

    def finish_refresh(self, generation: int | None) -> bool:
        if generation is None:
            return True
        if generation != self.refresh_generation:
            return False
        self.refresh_started_at = None
        self.resume_recovery_pending = False
        return True

    def is_refresh_stale(self, now: datetime) -> bool:
        if self.refresh_started_at is None:
            return False
        return now - self.refresh_started_at >= timedelta(seconds=self.stale_refresh_seconds)

    def abandon_active_refresh(self) -> int:
        stale_generation = self.refresh_generation
        self.refresh_generation += 1
        self.refresh_started_at = None
        return stale_generation

    def request_resume_recovery(self, now: datetime, is_refreshing: bool) -> ResumeRecoveryDecision:
        self.resume_recovery_pending = True
        if not is_refreshing:
            return ResumeRecoveryDecision(start_refresh=True)
        return ResumeRecoveryDecision(wait_for_active_refresh=True)

    def request_forced_refresh(self, now: datetime, is_refreshing: bool) -> ResumeRecoveryDecision:
        if not is_refreshing:
            return ResumeRecoveryDecision(start_refresh=True)
        if self.is_refresh_stale(now):
            return ResumeRecoveryDecision(
                start_refresh=True,
                abandoned_generation=self.abandon_active_refresh(),
            )
        return ResumeRecoveryDecision(wait_for_active_refresh=True)


ResumeRecoveryState = ResumeRefreshCoordinator
