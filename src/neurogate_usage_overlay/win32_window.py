from __future__ import annotations

import ctypes
from ctypes import wintypes
import sys
import tkinter as tk


DWMWA_WINDOW_CORNER_PREFERENCE = 33
DWMWCP_ROUND = 2
GWL_EXSTYLE = -20
WS_EX_LAYERED = 0x00080000
LWA_COLORKEY = 0x00000001


def configure_rounded_window_background(window: tk.Tk | tk.Toplevel, transparent_color: str) -> None:
    window.configure(bg=transparent_color)
    if not sys.platform.startswith("win"):
        return
    try:
        window.attributes("-transparentcolor", transparent_color)
    except tk.TclError:
        pass


def transparent_colorref(transparent_color: str) -> int:
    red = int(transparent_color[1:3], 16)
    green = int(transparent_color[3:5], 16)
    blue = int(transparent_color[5:7], 16)
    return red | (green << 8) | (blue << 16)


def _win32_long_ptr_type():
    return ctypes.c_longlong if ctypes.sizeof(ctypes.c_void_p) == 8 else ctypes.c_long


def _configure_win32_window_api(user32, gdi32) -> None:
    long_ptr = _win32_long_ptr_type()
    user32.GetWindowLongPtrW.argtypes = [wintypes.HWND, ctypes.c_int]
    user32.GetWindowLongPtrW.restype = long_ptr
    user32.SetWindowLongPtrW.argtypes = [wintypes.HWND, ctypes.c_int, long_ptr]
    user32.SetWindowLongPtrW.restype = long_ptr
    user32.SetLayeredWindowAttributes.argtypes = [
        wintypes.HWND,
        wintypes.COLORREF,
        wintypes.BYTE,
        wintypes.DWORD,
    ]
    user32.SetLayeredWindowAttributes.restype = wintypes.BOOL
    user32.SetWindowRgn.argtypes = [wintypes.HWND, wintypes.HRGN, wintypes.BOOL]
    user32.SetWindowRgn.restype = ctypes.c_int
    gdi32.CreateRoundRectRgn.argtypes = [
        ctypes.c_int,
        ctypes.c_int,
        ctypes.c_int,
        ctypes.c_int,
        ctypes.c_int,
        ctypes.c_int,
    ]
    gdi32.CreateRoundRectRgn.restype = wintypes.HRGN
    gdi32.DeleteObject.argtypes = [wintypes.HGDIOBJ]
    gdi32.DeleteObject.restype = wintypes.BOOL


def _apply_dwm_corner_preference(hwnd: int) -> None:
    try:
        dwmapi = ctypes.windll.dwmapi
        dwmapi.DwmSetWindowAttribute.argtypes = [
            wintypes.HWND,
            wintypes.DWORD,
            wintypes.LPVOID,
            wintypes.DWORD,
        ]
        dwmapi.DwmSetWindowAttribute.restype = ctypes.c_long
        preference = ctypes.c_int(DWMWCP_ROUND)
        dwmapi.DwmSetWindowAttribute(
            hwnd,
            DWMWA_WINDOW_CORNER_PREFERENCE,
            ctypes.byref(preference),
            ctypes.sizeof(preference),
        )
    except Exception:
        return


def apply_rounded_window_region(
    window: tk.Tk | tk.Toplevel,
    width: int,
    height: int,
    radius: int,
    transparent_color: str,
) -> None:
    if not sys.platform.startswith("win"):
        return
    try:
        window.update_idletasks()
        hwnd = window.winfo_id()
        user32 = ctypes.windll.user32
        gdi32 = ctypes.windll.gdi32
        _configure_win32_window_api(user32, gdi32)
        long_ptr = _win32_long_ptr_type()
        ex_style = user32.GetWindowLongPtrW(hwnd, GWL_EXSTYLE)
        user32.SetWindowLongPtrW(hwnd, GWL_EXSTYLE, long_ptr(ex_style | WS_EX_LAYERED))
        user32.SetLayeredWindowAttributes(
            hwnd,
            transparent_colorref(transparent_color),
            255,
            LWA_COLORKEY,
        )
        region = gdi32.CreateRoundRectRgn(
            0,
            0,
            width + 1,
            height + 1,
            radius * 2,
            radius * 2,
        )
        if region:
            if not user32.SetWindowRgn(hwnd, region, True):
                gdi32.DeleteObject(region)
        _apply_dwm_corner_preference(hwnd)
    except Exception:
        return
