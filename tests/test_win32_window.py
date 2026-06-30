import unittest
from ctypes import wintypes
from unittest.mock import patch

from neurogate_usage_overlay.win32_window import apply_rounded_window_region, transparent_colorref


class Win32WindowTest(unittest.TestCase):
    def test_transparent_colorref_uses_win32_bgr_order(self):
        self.assertEqual(transparent_colorref("#010203"), 0x030201)

    def test_region_is_applied_even_when_dwm_preference_fails(self):
        class FakeFunc:
            def __init__(self, result=1, error: Exception | None = None) -> None:
                self.result = result
                self.error = error
                self.calls = []
                self.argtypes = None
                self.restype = None

            def __call__(self, *args):
                self.calls.append(args)
                if self.error:
                    raise self.error
                return self.result

        class FakeWindow:
            def update_idletasks(self) -> None:
                pass

            def winfo_id(self) -> int:
                return 12345

        user32 = type(
            "FakeUser32",
            (),
            {
                "GetWindowLongPtrW": FakeFunc(result=0),
                "SetWindowLongPtrW": FakeFunc(result=1),
                "SetLayeredWindowAttributes": FakeFunc(result=1),
                "SetWindowRgn": FakeFunc(result=1),
            },
        )()
        gdi32 = type(
            "FakeGdi32",
            (),
            {
                "CreateRoundRectRgn": FakeFunc(result=67890),
                "DeleteObject": FakeFunc(result=1),
            },
        )()
        dwmapi = type("FakeDwmApi", (), {"DwmSetWindowAttribute": FakeFunc(error=OSError("no dwm"))})()
        windll = type("FakeWinDll", (), {"user32": user32, "gdi32": gdi32, "dwmapi": dwmapi})()

        with (
            patch("neurogate_usage_overlay.win32_window.sys.platform", "win32"),
            patch("neurogate_usage_overlay.win32_window.ctypes.windll", windll, create=True),
        ):
            apply_rounded_window_region(FakeWindow(), 222, 106, 7, "#010203")

        self.assertEqual(user32.GetWindowLongPtrW.argtypes[0], wintypes.HWND)
        self.assertEqual(user32.SetLayeredWindowAttributes.argtypes[1], wintypes.COLORREF)
        self.assertEqual(len(user32.SetWindowRgn.calls), 1)
        self.assertEqual(len(gdi32.DeleteObject.calls), 0)


if __name__ == "__main__":
    unittest.main()
