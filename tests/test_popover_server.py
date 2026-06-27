from datetime import datetime, timezone
import threading
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
                    "interval_minutes": 1,
                    "interval_choices": [{"minutes": 1, "label": "1м"}, {"minutes": 3, "label": "3м"}],
                    "daily_limit_enabled": False,
                    "daily_limit_default": "56M",
                    "theme": "dark",
                    "version_label": "v.2.0 (доступна v.2.1)",
                    "version_update_available": True,
                    "has_account_reset": True,
                },
            )

            html = server.render_html()
            data = server.render_json()

            self.assertIn("Обновить", html)
            self.assertIn("Интервал обновления", html)
            self.assertIn("choice-list", html)
            self.assertIn("Тёмная тема", html)
            self.assertIn("Задать лимит на день", html)
            self.assertIn("dailyLimitInput", html)
            self.assertIn("Перезапустить", html)
            self.assertIn("Выход", html)
            self.assertIn("v.2.0 (доступна v.2.1)", html)
            self.assertNotIn("Обновить до", html)
            self.assertIn("106070000", html)
            self.assertIn("18 дн осталось", data)
            self.assertIn('"theme": "dark"', data)
            self.assertNotIn("Рћ", html)
            self.assertNotIn("вЂ", html)
            self.assertNotIn("не ниже", html)
        finally:
            server.stop()

    def test_popover_server_renders_loading_state_in_utf8(self) -> None:
        server = PopoverServer()
        try:
            server.update(
                None,
                {
                    "interval_label": "1 мин",
                    "interval_minutes": 1,
                    "interval_choices": [],
                    "daily_limit_enabled": False,
                    "daily_limit_default": "",
                    "theme": "light",
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

    def test_popover_server_passes_action_payload(self) -> None:
        server = PopoverServer()
        try:
            event = threading.Event()
            seen: dict[str, object] = {}

            def callback(payload: dict[str, object]) -> None:
                seen.update(payload)
                event.set()

            server.on_action("set_interval", callback)
            server.handle_action("set_interval", {"minutes": 5})

            self.assertTrue(event.wait(1))
            self.assertEqual(seen, {"minutes": 5})
        finally:
            server.stop()

    def test_daily_limit_block_renders_before_actions(self) -> None:
        server = PopoverServer()
        try:
            html = server.render_html()
            daily_insert = html.index("html += dailyLimitBlock();")
            actions_insert = html.index('html += `<div class="actions">`;')
            self.assertLess(daily_insert, actions_insert)
        finally:
            server.stop()


if __name__ == "__main__":
    unittest.main()
