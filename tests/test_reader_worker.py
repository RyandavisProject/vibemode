import threading
import unittest
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


if __name__ == "__main__":
    unittest.main()
