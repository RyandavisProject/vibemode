import tempfile
import unittest
from datetime import datetime
from pathlib import Path

from neurogate_usage_overlay.history import DailyUsageStore, spent_since_reset
from neurogate_usage_overlay.models import UsageSnapshot, UsageWindow


class SpentSinceResetTest(unittest.TestCase):
    def test_uses_explicit_limit_used(self):
        window = UsageWindow(title="5 часов", limit_used=700_000)

        self.assertEqual(spent_since_reset(window), 700_000)

    def test_uses_limit_total_and_remaining(self):
        window = UsageWindow(title="5 часов", limit_total=120_000_000, credits_remaining=119_300_000)

        self.assertEqual(spent_since_reset(window), 700_000)

    def test_estimates_from_remaining_and_progress(self):
        window = UsageWindow(title="5 часов", credits_remaining=119_300_000, progress_percent=0.58)

        self.assertEqual(spent_since_reset(window), 695_977)

    def test_zero_progress_means_zero_spent(self):
        window = UsageWindow(title="5 часов", credits_remaining=120_000_000, progress_percent=0)

        self.assertEqual(spent_since_reset(window), 0)


class DailyUsageStoreTest(unittest.TestCase):
    def test_records_only_current_day(self):
        with tempfile.TemporaryDirectory() as directory:
            store = DailyUsageStore(Path(directory) / "usage-daily.json")
            first = UsageSnapshot(
                updated_at=datetime.now(),
                windows=[UsageWindow(title="7 дней", credits_remaining=300_000_000)],
            )
            current = UsageSnapshot(
                updated_at=datetime.now(),
                windows=[UsageWindow(title="7 дней", credits_remaining=289_100_000)],
            )

            store.record_snapshot(first, datetime(2026, 6, 8, 1, 0))
            store.record_snapshot(current, datetime(2026, 6, 8, 12, 0))

            spent = store.today_spent_7d(current, datetime(2026, 6, 8, 12, 0))
            self.assertIsNotNone(spent)
            self.assertEqual(spent.amount, 10_900_000)
            self.assertEqual(spent.since_text, "01:00")

    def test_new_day_replaces_previous_day(self):
        with tempfile.TemporaryDirectory() as directory:
            store = DailyUsageStore(Path(directory) / "usage-daily.json")
            day_one = UsageSnapshot(
                updated_at=datetime.now(),
                windows=[UsageWindow(title="7 дней", credits_remaining=300_000_000)],
            )
            day_two = UsageSnapshot(
                updated_at=datetime.now(),
                windows=[UsageWindow(title="7 дней", credits_remaining=280_000_000)],
            )

            store.record_snapshot(day_one, datetime(2026, 6, 8, 12, 0))
            store.record_snapshot(day_two, datetime(2026, 6, 9, 1, 0))

            spent = store.today_spent_7d(day_two, datetime(2026, 6, 9, 1, 0))
            self.assertIsNotNone(spent)
            self.assertEqual(spent.amount, 0)
            self.assertEqual(spent.since_text, "01:00")

    def test_remaining_growth_resets_daily_baseline(self):
        with tempfile.TemporaryDirectory() as directory:
            store = DailyUsageStore(Path(directory) / "usage-daily.json")
            first = UsageSnapshot(
                updated_at=datetime.now(),
                windows=[UsageWindow(title="7 дней", credits_remaining=200_000_000)],
            )
            after_reset = UsageSnapshot(
                updated_at=datetime.now(),
                windows=[UsageWindow(title="7 дней", credits_remaining=600_000_000)],
            )

            store.record_snapshot(first, datetime(2026, 6, 8, 12, 0))
            store.record_snapshot(after_reset, datetime(2026, 6, 8, 13, 0))

            spent = store.today_spent_7d(after_reset, datetime(2026, 6, 8, 13, 0))
            self.assertIsNotNone(spent)
            self.assertEqual(spent.amount, 0)
            self.assertEqual(spent.since_text, "13:00")

    def test_existing_daily_file_without_first_seen_is_migrated(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "usage-daily.json"
            path.write_text(
                '{"date": "2026-06-08", "first_7d_remaining": 300000000, "last_7d_remaining": 290000000}',
                encoding="utf-8",
            )
            store = DailyUsageStore(path)
            current = UsageSnapshot(
                updated_at=datetime.now(),
                windows=[UsageWindow(title="7 дней", credits_remaining=289_100_000)],
            )

            store.record_snapshot(current, datetime(2026, 6, 8, 14, 32))
            spent = store.today_spent_7d(current, datetime(2026, 6, 8, 14, 32))

            self.assertIsNotNone(spent)
            self.assertEqual(spent.amount, 0)
            self.assertEqual(spent.since_text, "14:32")


if __name__ == "__main__":
    unittest.main()
