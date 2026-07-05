import unittest
from unittest.mock import patch

from neurogate_usage_overlay.macos_power import MacOSPowerObserver, install_macos_power_observer
from neurogate_usage_overlay.win32_power import install_win32_power_broadcast_handler


class PowerEventsTest(unittest.TestCase):
    def test_win32_power_handler_is_noop_off_windows(self):
        with patch("neurogate_usage_overlay.win32_power.sys.platform", "linux"):
            self.assertIsNone(
                install_win32_power_broadcast_handler(
                    object(),  # type: ignore[arg-type]
                    on_suspend=lambda: None,
                    on_resume=lambda: None,
                )
            )

    def test_macos_power_observer_is_noop_off_macos(self):
        with patch("neurogate_usage_overlay.macos_power.sys.platform", "win32"):
            self.assertIsNone(install_macos_power_observer(on_sleep=lambda: None, on_wake=lambda: None))

    def test_macos_power_observer_unregisters_center_observer(self):
        calls = []

        class FakeCenter:
            def removeObserver_(self, observer):
                calls.append(observer)

        observer = object()
        handle = MacOSPowerObserver(FakeCenter(), observer)

        handle.uninstall()

        self.assertEqual(calls, [observer])


if __name__ == "__main__":
    unittest.main()

