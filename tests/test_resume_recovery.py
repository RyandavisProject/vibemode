import unittest
from datetime import datetime, timedelta

from neurogate_usage_overlay.resume_recovery import ResumeRefreshCoordinator


class ResumeRefreshCoordinatorTest(unittest.TestCase):
    def test_stale_refresh_can_be_abandoned_and_old_result_rejected(self):
        state = ResumeRefreshCoordinator(stale_refresh_seconds=10)
        started_at = datetime.now().astimezone() - timedelta(seconds=20)
        generation = state.begin_refresh(started_at)

        self.assertTrue(state.is_refresh_stale(datetime.now().astimezone()))
        self.assertEqual(state.abandon_active_refresh(), generation)
        self.assertFalse(state.finish_refresh(generation))

    def test_current_generation_result_is_accepted(self):
        state = ResumeRefreshCoordinator(stale_refresh_seconds=10)
        generation = state.begin_refresh(datetime.now().astimezone())

        self.assertTrue(state.finish_refresh(generation))
        self.assertIsNone(state.refresh_started_at)

    def test_resume_recovery_starts_when_idle(self):
        state = ResumeRefreshCoordinator(stale_refresh_seconds=10)

        decision = state.request_resume_recovery(datetime.now().astimezone(), is_refreshing=False)

        self.assertTrue(decision.start_refresh)
        self.assertFalse(decision.wait_for_active_refresh)
        self.assertIsNone(decision.abandoned_generation)
        self.assertTrue(state.resume_recovery_pending)

    def test_resume_recovery_waits_for_fresh_active_refresh(self):
        state = ResumeRefreshCoordinator(stale_refresh_seconds=10)
        state.begin_refresh(datetime.now().astimezone())

        decision = state.request_resume_recovery(datetime.now().astimezone(), is_refreshing=True)

        self.assertFalse(decision.start_refresh)
        self.assertTrue(decision.wait_for_active_refresh)
        self.assertIsNone(decision.abandoned_generation)

    def test_resume_recovery_waits_for_stale_active_refresh(self):
        state = ResumeRefreshCoordinator(stale_refresh_seconds=10)
        state.begin_refresh(datetime.now().astimezone() - timedelta(seconds=20))

        decision = state.request_resume_recovery(datetime.now().astimezone(), is_refreshing=True)

        self.assertFalse(decision.start_refresh)
        self.assertTrue(decision.wait_for_active_refresh)
        self.assertIsNone(decision.abandoned_generation)
        self.assertIsNotNone(state.refresh_started_at)

    def test_forced_refresh_waits_for_fresh_active_refresh_without_pending_recovery(self):
        state = ResumeRefreshCoordinator(stale_refresh_seconds=10)
        state.begin_refresh(datetime.now().astimezone())

        decision = state.request_forced_refresh(datetime.now().astimezone(), is_refreshing=True)

        self.assertFalse(decision.start_refresh)
        self.assertTrue(decision.wait_for_active_refresh)
        self.assertFalse(state.resume_recovery_pending)


if __name__ == "__main__":
    unittest.main()
