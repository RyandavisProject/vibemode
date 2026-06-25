from datetime import datetime, timezone
import unittest

from neurogate_usage_overlay.models import UsageSnapshot, UsageWindow
from neurogate_usage_overlay.popover_server import PopoverServer


class PopoverServerTest(unittest.TestCase):
    def test_popover_server_renders_utf8_labels(self) -> None:
        server = PopoverServer()
        try:
            snapshot = UsageSnapshot(
                updated_at=datetime.now(timezone.utc),
                account="Ascend",
                plan_status="18 дн осталось",
                windows=[
                    UsageWindow(
                        title="5 часов",
                        credits_remaining=106_070_000,
                        limit_used=13_930_000,
                        limit_total=120_000_000,
                        progress_percent=11.6,
                    )
                ],
            )
            server.update(
                snapshot,
                {
                    "interval_label": "1 мин",
                    "daily_limit_enabled": False,
                    "version_label": "v.2.0 (доступна v.2.1)",
                    "version_update_available": True,
                    "has_account_reset": True,
                },
            )

            html = server.render_html()
            data = server.render_json()

            self.assertIn("Обновить", html)
            self.assertIn("Интервал", html)
            self.assertIn("Задать лимит на день", html)
            self.assertIn("v.2.0 (доступна v.2.1)", html)
            self.assertNotIn("Обновить до", html)
            self.assertIn("106070000", html)
            self.assertIn("18 дн осталось", data)
            self.assertNotIn("Рћ", html)
            self.assertNotIn("вЂ", html)
        finally:
            server.stop()

    def test_popover_server_renders_loading_state_in_utf8(self) -> None:
        server = PopoverServer()
        try:
            server.update(
                None,
                {
                    "interval_label": "1 мин",
                    "daily_limit_enabled": False,
                    "version_label": "v.2.0 (последняя)",
                    "version_update_available": False,
                    "has_account_reset": True,
                },
            )

            html = server.render_html()

            self.assertIn("Загрузка...", html)
            self.assertIn("v.2.0 (последняя)", html)
            self.assertNotIn("Р—", html)
        finally:
            server.stop()


if __name__ == "__main__":
    unittest.main()
