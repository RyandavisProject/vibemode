import queue
import threading
import time
import unittest
from concurrent.futures import Future
from datetime import datetime
from unittest.mock import patch

from neurogate_usage_overlay.browser_reader import BrowserSettings
from neurogate_usage_overlay.models import UsageSnapshot, UsageWindow
from neurogate_usage_overlay.reader_worker import ThreadedUsageReader


class ThreadedUsageReaderTest(unittest.TestCase):
    def test_preloads_first_refresh_before_ui_requests_it(self):
        started = threading.Event()

        class FakeReader:
            def __init__(self, _settings):
                pass

            def refresh(self):
                started.set()
                return UsageSnapshot(
                    updated_at=datetime.now(),
                    windows=[UsageWindow(title="5 часов", credits_remaining=1)],
                )

            def set_keep_browser_open(self, _enabled):
                return None

            def reset_account_session(self):
                return None

            def stop(self):
                return None

        with patch("neurogate_usage_overlay.reader_worker.NeurogateUsageReader", FakeReader):
            reader = ThreadedUsageReader(BrowserSettings())
            try:
                self.assertTrue(started.wait(1))
                snapshot = reader.refresh()
                self.assertEqual(snapshot.windows[0].credits_remaining, 1)
            finally:
                reader.stop()

    def test_force_refresh_reaches_browser_reader(self):
        calls: list[bool] = []
        second_call = threading.Event()

        class FakeReader:
            def __init__(self, _settings):
                pass

            def refresh(self, force_session_recovery: bool = False):
                calls.append(force_session_recovery)
                if len(calls) >= 2:
                    second_call.set()
                return UsageSnapshot(
                    updated_at=datetime.now(),
                    windows=[UsageWindow(title="5 часов", credits_remaining=1)],
                )

            def set_keep_browser_open(self, _enabled):
                return None

            def reset_account_session(self):
                return None

            def stop(self):
                return None

        with patch("neurogate_usage_overlay.reader_worker.NeurogateUsageReader", FakeReader):
            reader = ThreadedUsageReader(BrowserSettings())
            try:
                snapshot = reader.refresh(force_session_recovery=True)
                self.assertEqual(snapshot.windows[0].credits_remaining, 1)
                self.assertTrue(second_call.wait(1))
                self.assertIn(True, calls)
            finally:
                reader.stop()

    def test_worker_call_times_out_instead_of_blocking_forever(self):
        reader = ThreadedUsageReader.__new__(ThreadedUsageReader)
        future: Future = Future()
        reader._worker_lock = threading.Lock()
        reader._future_queues = {}
        reader._enqueue = lambda *_args: future  # type: ignore[method-assign]

        with patch("neurogate_usage_overlay.reader_worker.WORKER_CALL_TIMEOUT_SECONDS", 0.01):
            with self.assertRaisesRegex(RuntimeError, "timed out"):
                reader._call("refresh")

        self.assertTrue(future.cancelled())

    def test_worker_queue_full_fails_fast(self):
        reader = ThreadedUsageReader.__new__(ThreadedUsageReader)
        reader._worker_lock = threading.Lock()
        reader._future_queues = {}
        reader._commands = queue.Queue(maxsize=1)
        reader._commands.put(("refresh", (), Future()))

        with self.assertRaisesRegex(RuntimeError, "queue is full"):
            reader._enqueue("refresh")

    def test_worker_recovers_after_hung_preload_refresh(self):
        release_first_refresh = threading.Event()
        first_stopped = threading.Event()
        created: list[object] = []

        class FakeReader:
            def __init__(self, settings):
                self.settings = settings
                self.index = len(created)
                created.append(self)

            def refresh(self):
                if self.index == 0:
                    release_first_refresh.wait(1)
                    return UsageSnapshot(
                        updated_at=datetime.now(),
                        windows=[UsageWindow(title="stale", credits_remaining=0)],
                    )
                return UsageSnapshot(
                    updated_at=datetime.now(),
                    windows=[UsageWindow(title="recovered", credits_remaining=2)],
                )

            def set_keep_browser_open(self, _enabled):
                return None

            def reset_account_session(self):
                return None

            def stop(self):
                if self.index == 0:
                    first_stopped.set()
                return None

        with patch("neurogate_usage_overlay.reader_worker.NeurogateUsageReader", FakeReader):
            with patch("neurogate_usage_overlay.reader_worker.WORKER_CALL_TIMEOUT_SECONDS", 0.01):
                reader = ThreadedUsageReader(BrowserSettings())
                try:
                    with self.assertRaisesRegex(RuntimeError, "timed out: refresh"):
                        reader.refresh()

                    deadline = time.monotonic() + 1
                    while len(created) < 2 and time.monotonic() < deadline:
                        time.sleep(0.01)

                    snapshot = reader.refresh()
                    self.assertEqual(snapshot.windows[0].title, "recovered")
                    self.assertEqual(snapshot.windows[0].credits_remaining, 2)
                finally:
                    reader.stop()
                    release_first_refresh.set()
                    self.assertTrue(first_stopped.wait(1))

    def test_worker_restart_after_timeout_preserves_force_session_recovery(self):
        release_first_refresh = threading.Event()
        first_stopped = threading.Event()
        force_calls: list[bool] = []
        created: list[object] = []

        class FakeReader:
            def __init__(self, settings):
                self.settings = settings
                self.index = len(created)
                created.append(self)

            def refresh(self, force_session_recovery: bool = False):
                if self.index == 0:
                    release_first_refresh.wait(1)
                    return UsageSnapshot(updated_at=datetime.now())
                force_calls.append(force_session_recovery)
                return UsageSnapshot(
                    updated_at=datetime.now(),
                    windows=[UsageWindow(title="recovered", credits_remaining=3)],
                )

            def set_keep_browser_open(self, _enabled):
                return None

            def reset_account_session(self):
                return None

            def stop(self):
                if self.index == 0:
                    first_stopped.set()
                return None

        with patch("neurogate_usage_overlay.reader_worker.NeurogateUsageReader", FakeReader):
            with patch("neurogate_usage_overlay.reader_worker.WORKER_CALL_TIMEOUT_SECONDS", 0.01):
                reader = ThreadedUsageReader(BrowserSettings())
                try:
                    with self.assertRaisesRegex(RuntimeError, "timed out: refresh"):
                        reader.refresh()

                    deadline = time.monotonic() + 1
                    while len(created) < 2 and time.monotonic() < deadline:
                        time.sleep(0.01)

                    snapshot = reader.refresh(force_session_recovery=True)
                    self.assertEqual(snapshot.windows[0].title, "recovered")
                    self.assertEqual(snapshot.windows[0].credits_remaining, 3)
                    self.assertEqual(force_calls, [True])
                finally:
                    reader.stop()
                    release_first_refresh.set()
                    self.assertTrue(first_stopped.wait(1))

    def test_worker_restart_preserves_keep_browser_open_setting(self):
        release_first_refresh = threading.Event()
        created: list[object] = []

        class FakeReader:
            def __init__(self, settings):
                self.settings = settings
                self.index = len(created)
                created.append(self)

            def refresh(self):
                release_first_refresh.wait(1)
                return UsageSnapshot(updated_at=datetime.now())

            def set_keep_browser_open(self, _enabled):
                return None

            def reset_account_session(self):
                return None

            def stop(self):
                return None

        with patch("neurogate_usage_overlay.reader_worker.NeurogateUsageReader", FakeReader):
            with patch("neurogate_usage_overlay.reader_worker.WORKER_CALL_TIMEOUT_SECONDS", 0.01):
                reader = ThreadedUsageReader(BrowserSettings(headless=True))
                try:
                    with self.assertRaisesRegex(RuntimeError, "timed out: set_keep_browser_open"):
                        reader.set_keep_browser_open(True)

                    deadline = time.monotonic() + 1
                    while len(created) < 2 and time.monotonic() < deadline:
                        time.sleep(0.01)

                    self.assertGreaterEqual(len(created), 2)
                    self.assertFalse(created[-1].settings.headless)
                    self.assertTrue(created[-1].settings.show_browser_on_login)
                    self.assertFalse(created[-1].settings.hide_after_successful_login)
                finally:
                    reader.stop()
                    release_first_refresh.set()


if __name__ == "__main__":
    unittest.main()
