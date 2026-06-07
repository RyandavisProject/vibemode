import unittest

from neurogate_usage_overlay.parser import parse_usage_text
from neurogate_usage_overlay.projection import (
    parse_plan_remaining,
    projected_spendable_credits,
    projected_window_capacity,
)


class ProjectionTest(unittest.TestCase):
    def test_parse_plan_remaining(self):
        self.assertEqual(parse_plan_remaining("активен ещё 2 д 19 ч").total_seconds(), 67 * 60 * 60)

    def test_projected_capacity_counts_future_resets_before_plan_expires(self):
        self.assertEqual(
            projected_window_capacity(
                current_remaining=100,
                reset_text="4 ч",
                plan_remaining_text="активен ещё 15 ч",
                window_limit=1_000,
                period=parse_plan_remaining("активен ещё 5 ч"),
            ),
            3_100,
        )

    def test_projected_spendable_credits_is_limited_by_weekly_window(self):
        snapshot = parse_usage_text(
            """
            ascend
            активен ещё 2 д 19 ч
            ПЛАТНЫЙ СБРОС
            Сбрасывает: 7 дней, 5 часов.
            5 часов
            Сброс через 4 ч
            115 000 000
            Кредитов осталось
            7 дней
            Сброс через 1 д 19 ч
            328 000 000
            Кредитов осталось
            """
        )

        self.assertEqual(projected_spendable_credits(snapshot), 928_000_000)


if __name__ == "__main__":
    unittest.main()
