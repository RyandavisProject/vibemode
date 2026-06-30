from datetime import datetime
import unittest

from neurogate_usage_overlay.models import UsageSnapshot, UsageWindow
from neurogate_usage_overlay.projection import (
    find_window,
    parse_plan_remaining,
    projected_period_capacity,
    projected_spendable_credits,
    projected_window_capacity,
)


PLAN_2D_19H = "\u0430\u043a\u0442\u0438\u0432\u0435\u043d \u0435\u0449\u0451 2 \u0434 19 \u0447"
PLAN_10D = "\u0430\u043a\u0442\u0438\u0432\u0435\u043d \u0435\u0449\u0451 10 \u0434"
PERIOD_5H = "\u0430\u043a\u0442\u0438\u0432\u0435\u043d \u0435\u0449\u0451 5 \u0447"
PERIOD_7D = "\u0430\u043a\u0442\u0438\u0432\u0435\u043d \u0435\u0449\u0451 7 \u0434"
RESET_4H = "4 \u0447"


class ProjectionTest(unittest.TestCase):
    def test_find_window_matches_localized_window_titles(self):
        snapshot = UsageSnapshot(
            updated_at=datetime.now(),
            windows=[
                UsageWindow(title="5 \u0447\u0430\u0441\u043e\u0432", credits_remaining=1),
                UsageWindow(title="7 \u0434\u043d\u0435\u0439", credits_remaining=2),
            ],
        )

        self.assertEqual(find_window(snapshot, "5h").credits_remaining, 1)
        self.assertEqual(find_window(snapshot, "7d").credits_remaining, 2)

    def test_parse_plan_remaining(self):
        self.assertEqual(parse_plan_remaining(PLAN_2D_19H).total_seconds(), 67 * 60 * 60)

    def test_projected_capacity_counts_future_resets_before_plan_expires(self):
        self.assertEqual(
            projected_window_capacity(
                current_remaining=100,
                reset_text=RESET_4H,
                plan_remaining_text="\u0430\u043a\u0442\u0438\u0432\u0435\u043d \u0435\u0449\u0451 15 \u0447",
                window_limit=1_000,
                period=parse_plan_remaining(PERIOD_5H),
            ),
            3_100,
        )

    def test_projected_spendable_credits_is_limited_by_weekly_window(self):
        snapshot = UsageSnapshot(
            updated_at=datetime.now(),
            account="ascend",
            plan_status=PLAN_2D_19H,
            windows=[
                UsageWindow(
                    title="5 \u0447\u0430\u0441\u043e\u0432",
                    credits_remaining=115_000_000,
                    reset_text=RESET_4H,
                ),
                UsageWindow(
                    title="7 \u0434\u043d\u0435\u0439",
                    credits_remaining=328_000_000,
                    reset_text="1 \u0434 19 \u0447",
                ),
            ],
        )

        self.assertEqual(projected_spendable_credits(snapshot), 328_000_000)

    def test_projected_weekly_capacity_adds_only_full_weeks_before_plan_expires(self):
        self.assertEqual(
            projected_period_capacity(
                current_remaining=302_300_000,
                plan_remaining_text=PLAN_2D_19H,
                window_limit=600_000_000,
                period=parse_plan_remaining(PERIOD_7D),
            ),
            302_300_000,
        )
        self.assertEqual(
            projected_period_capacity(
                current_remaining=302_300_000,
                plan_remaining_text=PLAN_10D,
                window_limit=600_000_000,
                period=parse_plan_remaining(PERIOD_7D),
            ),
            902_300_000,
        )


if __name__ == "__main__":
    unittest.main()
