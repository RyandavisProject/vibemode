from __future__ import annotations

import ctypes
import sys
import tkinter as tk
from ctypes import wintypes
from dataclasses import dataclass
from typing import Callable

from .win32_window import _win32_long_ptr_type


WM_POWERBROADCAST = 0x0218
PBT_APMSUSPEND = 0x0004
PBT_APMRESUMEAUTOMATIC = 0x0012
PBT_APMRESUMESUSPEND = 0x0007
GWLP_WNDPROC = -4

PowerCallback = Callable[[], None]


@dataclass
class Win32PowerBroadcastHandle:
    window: tk.Tk | tk.Toplevel
    hwnd: int
    old_wndproc: int
    new_wndproc: object

    def uninstall(self) -> None:
        if not sys.platform.startswith("win"):
            return
        try:
            user32 = ctypes.windll.user32
            long_ptr = _win32_long_ptr_type()
            user32.SetWindowLongPtrW(self.hwnd, GWLP_WNDPROC, long_ptr(self.old_wndproc))
        except Exception:
            return


def install_win32_power_broadcast_handler(
    window: tk.Tk | tk.Toplevel,
    *,
    on_suspend: PowerCallback,
    on_resume: PowerCallback,
) -> Win32PowerBroadcastHandle | None:
    if not sys.platform.startswith("win"):
        return None
    try:
        window.update_idletasks()
        hwnd = window.winfo_id()
        user32 = ctypes.windll.user32
        long_ptr = _win32_long_ptr_type()
        wndproc_type = ctypes.WINFUNCTYPE(
            wintypes.LRESULT,
            wintypes.HWND,
            wintypes.UINT,
            wintypes.WPARAM,
            wintypes.LPARAM,
        )
        user32.GetWindowLongPtrW.argtypes = [wintypes.HWND, ctypes.c_int]
        user32.GetWindowLongPtrW.restype = long_ptr
        user32.SetWindowLongPtrW.argtypes = [wintypes.HWND, ctypes.c_int, long_ptr]
        user32.SetWindowLongPtrW.restype = long_ptr
        user32.CallWindowProcW.argtypes = [
            long_ptr,
            wintypes.HWND,
            wintypes.UINT,
            wintypes.WPARAM,
            wintypes.LPARAM,
        ]
        user32.CallWindowProcW.restype = wintypes.LRESULT
        old_wndproc = user32.GetWindowLongPtrW(hwnd, GWLP_WNDPROC)

        def schedule(callback: PowerCallback) -> None:
            try:
                window.after(0, callback)
            except Exception:
                callback()

        def wndproc(hwnd_arg, msg, wparam, lparam):  # noqa: ANN001 - ctypes callback signature.
            if msg == WM_POWERBROADCAST:
                if int(wparam) == PBT_APMSUSPEND:
                    schedule(on_suspend)
                elif int(wparam) in {PBT_APMRESUMEAUTOMATIC, PBT_APMRESUMESUSPEND}:
                    schedule(on_resume)
            return user32.CallWindowProcW(old_wndproc, hwnd_arg, msg, wparam, lparam)

        new_wndproc = wndproc_type(wndproc)
        user32.SetWindowLongPtrW(hwnd, GWLP_WNDPROC, long_ptr(ctypes.cast(new_wndproc, ctypes.c_void_p).value))
        return Win32PowerBroadcastHandle(window, hwnd, int(old_wndproc), new_wndproc)
    except Exception:
        return None

