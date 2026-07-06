from datetime import datetime, timezone
import json
import threading
import unittest
from urllib.error import HTTPError
from urllib.parse import urlparse
from urllib.request import Request, urlopen

from neurogate_usage_overlay.models import UsageSnapshot, UsageWindow
from neurogate_usage_overlay.popover_server import PopoverServer, _Handler


class PopoverServerTest(unittest.TestCase):
    def test_popover_handler_ignores_disconnected_client(self) -> None:
        handler = object.__new__(_Handler)
        calls = []

        class ClosedWriter:
            def write(self, _body: bytes) -> None:
                raise BrokenPipeError("client closed")

        handler.send_response = lambda code: calls.append(("response", code))  # type: ignore[method-assign]
        handler.send_header = lambda name, value: calls.append((name, value))  # type: ignore[method-assign]
        handler.end_headers = lambda: calls.append(("end", None))  # type: ignore[method-assign]
        handler.wfile = ClosedWriter()

        handler._respond(200, "text/plain", b"ok")

        self.assertIn(("response", 200), calls)

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
            self.assertIn('shortNum(w.credits_remaining) + "/" + shortNum(w.limit_total)', html)
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

    def test_popover_server_protects_local_actions_with_token(self) -> None:
        server = PopoverServer()
        try:
            server.update(
                UsageSnapshot(updated_at=datetime.now(timezone.utc)),
                {
                    "interval_label": "1 мин",
                    "daily_limit_enabled": False,
                    "version_label": "v.2.0 (последняя)",
                    "version_update_available": False,
                    "has_account_reset": True,
                },
            )
            parsed = urlparse(server.get_url())
            base = f"http://127.0.0.1:{server.port}"
            token_query = parsed.query

            with self.assertRaises(HTTPError) as denied_html:
                urlopen(f"{base}/", timeout=2)
            self.assertEqual(denied_html.exception.code, 403)
            html = urlopen(f"{base}/?{token_query}", timeout=2).read().decode("utf-8")
            self.assertIn("window.__NG_ACTION_TOKEN__", html)

            with self.assertRaises(HTTPError) as denied:
                urlopen(f"{base}/data", timeout=2)
            self.assertEqual(denied.exception.code, 403)

            payload = json.loads(urlopen(f"{base}/data?{token_query}", timeout=2).read().decode("utf-8"))
            self.assertIn("action_token", payload)

            with self.assertRaises(HTTPError) as get_action:
                urlopen(f"{base}/action/refresh?{token_query}", timeout=2)
            self.assertEqual(get_action.exception.code, 405)

            with self.assertRaises(HTTPError) as denied_action:
                urlopen(f"{base}/action/refresh", timeout=2)
            self.assertEqual(denied_action.exception.code, 403)

            with self.assertRaises(HTTPError) as denied_resize:
                urlopen(f"{base}/resize/320", timeout=2)
            self.assertEqual(denied_resize.exception.code, 403)

            with self.assertRaises(HTTPError) as get_resize:
                urlopen(f"{base}/resize/320?{token_query}", timeout=2)
            self.assertEqual(get_resize.exception.code, 405)

            called = threading.Event()
            server.on_action("refresh", lambda _payload: called.set())
            request = Request(f"{base}/action/refresh?{token_query}", data=b"", method="POST")
            self.assertEqual(urlopen(request, timeout=2).read(), b"ok")
            self.assertTrue(called.wait(1))
        finally:
            server.stop()

    def test_popover_server_passes_http_action_payload_with_token(self) -> None:
        server = PopoverServer()
        try:
            parsed = urlparse(server.get_url())
            base = f"http://127.0.0.1:{server.port}"
            token_query = parsed.query
            event = threading.Event()
            seen: dict[str, object] = {}

            def callback(payload: dict[str, object]) -> None:
                seen.update(payload)
                event.set()

            server.on_action("set_interval", callback)
            request = Request(
                f"{base}/action/set_interval?{token_query}",
                data=json.dumps({"minutes": 5}).encode("utf-8"),
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            self.assertEqual(urlopen(request, timeout=2).read(), b"ok")
            self.assertTrue(event.wait(1))
            self.assertEqual(seen, {"minutes": 5})
        finally:
            server.stop()

    def test_popover_server_rejects_oversized_post_body_before_action(self) -> None:
        server = PopoverServer()
        try:
            parsed = urlparse(server.get_url())
            base = f"http://127.0.0.1:{server.port}"
            token_query = parsed.query
            called = threading.Event()
            server.on_action("set_daily", lambda _payload: called.set())
            request = Request(
                f"{base}/action/set_daily?{token_query}",
                data=b"{" + (b'"value":' + b'"' + b"x" * (20 * 1024) + b'"') + b"}",
                headers={"Content-Type": "application/json"},
                method="POST",
            )

            with self.assertRaises(HTTPError) as too_large:
                urlopen(request, timeout=2)

            self.assertEqual(too_large.exception.code, 413)
            self.assertFalse(called.wait(0.1))
        finally:
            server.stop()

    def test_popover_server_rejects_post_to_data_with_token_as_wrong_method(self) -> None:
        server = PopoverServer()
        try:
            parsed = urlparse(server.get_url())
            base = f"http://127.0.0.1:{server.port}"
            token_query = parsed.query
            request = Request(f"{base}/data?{token_query}", data=b"{}", method="POST")

            with self.assertRaises(HTTPError) as wrong_method:
                urlopen(request, timeout=2)

            self.assertEqual(wrong_method.exception.code, 405)
        finally:
            server.stop()


if __name__ == "__main__":
    unittest.main()
