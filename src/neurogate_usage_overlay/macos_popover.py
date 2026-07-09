"""macOS NSStatusItem + NSPopover + WKWebView menu bar UI.

All AppKit/WebKit calls happen on the main thread (required by macOS).
The PopoverServer runs in a daemon thread and serves the HTML/data.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

import objc
from AppKit import (
    NSBezierPath,
    NSColor,
    NSFont,
    NSForegroundColorAttributeName,
    NSImageLeft,
    NSApplication,
    NSImage,
    NSFontAttributeName,
    NSStatusBar,
    NSVariableStatusItemLength,
)
from Foundation import NSObject, NSString, NSURL, NSURLRequest
from WebKit import WKWebView, WKWebViewConfiguration, WKUserScript, WKUserScriptInjectionTimeAtDocumentEnd

# Lazy import — only needed at runtime on macOS
_AppKit = None
_VM_BLOB_IMAGE: Any = None


# ── JS bridge: intercepts window.__ng_action(name) calls ─────────────────────
_BRIDGE_SCRIPT = """
window.__ng_action = function(name, payload) {
    var token = encodeURIComponent(window.__NG_ACTION_TOKEN__ || '');
    fetch('/action/' + encodeURIComponent(name) + '?token=' + token, {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify(payload || {})
    }).catch(function(){});
};
// Report content height to NSPopover after render
function __ng_resize() {
    var h = document.documentElement.scrollHeight;
    var token = encodeURIComponent(window.__NG_ACTION_TOKEN__ || '');
    fetch('/resize/' + h + '?token=' + token, {method: 'POST'}).catch(function(){});
}
document.addEventListener('DOMContentLoaded', function() {
    __ng_resize();
    new MutationObserver(__ng_resize).observe(document.body, {childList: true, subtree: true, characterData: true});
});
"""

POPOVER_WIDTH  = 300
POPOVER_HEIGHT = 560


def _progress_color(percent: float | None) -> Any:
    if percent is None:
        return NSColor.colorWithCalibratedWhite_alpha_(1.0, 0.78)
    if percent > 75:
        return NSColor.colorWithCalibratedRed_green_blue_alpha_(1.0, 0.23, 0.19, 1.0)
    if percent > 50:
        return NSColor.colorWithCalibratedRed_green_blue_alpha_(1.0, 0.8, 0.0, 1.0)
    return NSColor.colorWithCalibratedRed_green_blue_alpha_(0.20, 0.78, 0.35, 1.0)


def _draw_vm_blob(origin_x: float = 0.0) -> None:
    from Foundation import NSMakeRect

    global _VM_BLOB_IMAGE
    if _VM_BLOB_IMAGE is None:
        asset_path = Path(__file__).with_name("assets") / "vm-reference-blob.png"
        _VM_BLOB_IMAGE = NSImage.alloc().initWithContentsOfFile_(str(asset_path))
    if _VM_BLOB_IMAGE is not None:
        _VM_BLOB_IMAGE.drawInRect_(NSMakeRect(origin_x, 0, 18, 18))


def _draw_vm_text(origin_x: float = 0.0) -> None:
    from Foundation import NSMakeRect

    attrs = {
        NSFontAttributeName: NSFont.boldSystemFontOfSize_(6.2),
        NSForegroundColorAttributeName: NSColor.blackColor(),
    }
    text = NSString.stringWithString_("VM")
    text_size = text.sizeWithAttributes_(attrs)
    text.drawInRect_withAttributes_(
        NSMakeRect(origin_x + (18 - text_size.width) / 2, (18 - text_size.height) / 2 - 1.0, text_size.width, text_size.height),
        attrs,
    )


def _make_vm_badge_image(title: str = "", progress_percent: float | None = None) -> Any:
    """Draw the menu bar status: VM badge, title, and title-width progress strip."""
    from Foundation import NSMakeRect, NSMakeSize

    title = title or ""
    title_attrs = {
        NSFontAttributeName: NSFont.boldSystemFontOfSize_(11.5),
        NSForegroundColorAttributeName: NSColor.whiteColor(),
    }
    title_text = NSString.stringWithString_(title)
    title_size = title_text.sizeWithAttributes_(title_attrs)
    title_width = max(12.0, float(title_size.width)) if title else 0.0
    text_x = 22.0
    width = int(text_x + title_width + 2) if title else 18
    image = NSImage.alloc().initWithSize_(NSMakeSize(width, 18))
    image.lockFocus()
    try:
        _draw_vm_blob()
        _draw_vm_text()

        if not title:
            return image

        title_text.drawInRect_withAttributes_(NSMakeRect(text_x, 6.4, title_width + 2.0, 12.0), title_attrs)

        track_y = 0.8
        track = NSBezierPath.bezierPathWithRoundedRect_xRadius_yRadius_(NSMakeRect(text_x, track_y, title_width, 2.2), 1.1, 1.1)
        NSColor.colorWithCalibratedWhite_alpha_(1.0, 0.28).setFill()
        track.fill()
        if progress_percent is not None:
            fill_width = max(1.0, min(title_width, title_width * max(0.0, min(100.0, progress_percent)) / 100.0))
            fill = NSBezierPath.bezierPathWithRoundedRect_xRadius_yRadius_(NSMakeRect(text_x, track_y, fill_width, 2.2), 1.1, 1.1)
            _progress_color(progress_percent).setFill()
            fill.fill()
    finally:
        image.unlockFocus()
    image.setSize_(NSMakeSize(width, 18))
    return image


def _make_popover(url: str) -> Any:
    """Build an NSPopover containing a WKWebView loaded with *url*."""
    from AppKit import NSPopover, NSPopoverBehaviorTransient, NSRectEdgeMinY

    cfg  = WKWebViewConfiguration.alloc().init()

    # Inject the JS bridge before page scripts run
    script = WKUserScript.alloc().initWithSource_injectionTime_forMainFrameOnly_(
        NSString.stringWithString_(_BRIDGE_SCRIPT),
        WKUserScriptInjectionTimeAtDocumentEnd,
        True,
    )
    cfg.userContentController().addUserScript_(script)

    from Foundation import NSMakeRect
    frame = NSMakeRect(0, 0, POPOVER_WIDTH, POPOVER_HEIGHT)
    wv = WKWebView.alloc().initWithFrame_configuration_(frame, cfg)
    try:
        wv.setDrawsBackground_(False)
    except AttributeError:
        # Newer WebKit: set transparent background via setValue_forKey_
        try:
            wv.setValue_forKey_(False, "_drawsBackground")
        except Exception:
            pass

    req = NSURLRequest.requestWithURL_(NSURL.URLWithString_(url))
    wv.loadRequest_(req)

    from AppKit import NSViewController
    vc = NSViewController.alloc().init()
    vc.setView_(wv)

    from Foundation import NSMakeSize
    popover = NSPopover.alloc().init()
    popover.setContentSize_(NSMakeSize(POPOVER_WIDTH, POPOVER_HEIGHT))
    popover.setContentViewController_(vc)
    popover.setBehavior_(NSPopoverBehaviorTransient)
    popover.setAnimates_(True)

    return popover, wv


class StatusItemDelegate(NSObject):  # type: ignore[misc]
    """Handles clicks on the NSStatusItem button."""

    _popover: Any = None
    _web_view: Any = None
    _server_url: str = ""

    @objc.python_method
    def setup(self, popover: Any, web_view: Any, server_url: str) -> None:
        self._popover = popover
        self._web_view = web_view
        self._server_url = server_url

    @objc.python_method
    def _button_ref(self) -> Any:
        return self._status_item.button() if hasattr(self, "_status_item") else None

    def buttonClicked_(self, sender: Any) -> None:
        from AppKit import NSApp

        event = NSApp.currentEvent()
        click_count = event.clickCount() if event and hasattr(event, "clickCount") else 1
        is_right_click = False
        if event and hasattr(event, "type"):
            try:
                from AppKit import NSEventTypeRightMouseUp

                is_right_click = event.type() == NSEventTypeRightMouseUp
            except Exception:
                is_right_click = False
        if self._popover.isShown() and click_count < 2 and not is_right_click:
            self._popover.close()
            return
        # Reload so data is always fresh when opening
        req = NSURLRequest.requestWithURL_(
            NSURL.URLWithString_(NSString.stringWithString_(self._server_url))
        )
        self._web_view.loadRequest_(req)
        from AppKit import NSRectEdgeMinY, NSZeroRect
        btn = sender
        self._popover.showRelativeToRect_ofView_preferredEdge_(
            btn.bounds(), btn, NSRectEdgeMinY
        )


class MenuBarPopover:
    """Manages the macOS status item, popover, and WebView lifecycle."""

    def __init__(self, server_url: str, initial_title: str = "...") -> None:
        self._server_url = server_url
        self._initial_title = initial_title
        self._status_item: Any = None
        self._popover: Any = None
        self._web_view: Any = None
        self._delegate: Any = None

    def _apply_badge(self, title: str, progress_percent: float | None = None) -> None:
        if not self._status_item:
            return
        image = _make_vm_badge_image(title, progress_percent)
        self._status_item.setLength_(max(24.0, float(image.size().width) + 2.0))
        btn = self._status_item.button()
        btn.setImage_(image)
        btn.setImagePosition_(NSImageLeft)
        btn.setTitle_("")

    # Call from main thread only
    def install(self) -> None:
        """Create the status item and popover. Must be called on the main thread."""
        self._popover, self._web_view = _make_popover(self._server_url)

        bar = NSStatusBar.systemStatusBar()
        self._status_item = bar.statusItemWithLength_(NSVariableStatusItemLength)
        try:
            self._status_item.setAutosaveName_("VibemodeMenuBarStatus")
            # Keep Vibemode from being the first item macOS drops when app menus are wide.
            self._status_item._setDropPriority_(-1_000_000.0)  # type: ignore[attr-defined]
            self._status_item._setOverflowSpecifierPriority_(1_000_000)  # type: ignore[attr-defined]
        except Exception:
            pass

        btn = self._status_item.button()
        self._apply_badge(self._initial_title)
        if hasattr(btn, "setImageHugsTitle_"):
            btn.setImageHugsTitle_(True)
        try:
            from AppKit import NSEventMaskLeftMouseUp, NSEventMaskRightMouseUp

            btn.sendActionOn_(NSEventMaskLeftMouseUp | NSEventMaskRightMouseUp)
        except Exception:
            pass
        self._delegate = StatusItemDelegate.alloc().init()
        self._delegate._status_item = self._status_item
        self._delegate.setup(self._popover, self._web_view, self._server_url)
        btn.setTarget_(self._delegate)
        btn.setAction_(objc.selector(
            self._delegate.buttonClicked_,
            selector=b"buttonClicked:",
            signature=b"v@:@",
        ))

    def set_title(self, title: str) -> None:
        """Update the status bar title. Safe to call from main thread."""
        self._apply_badge(title)

    def set_status(self, title: str, progress_percent: float | None = None) -> None:
        """Update title and tiny status progress strip. Safe to call from main thread."""
        self._apply_badge(title, progress_percent)

    def resize_to_content(self, height: int) -> None:
        """Resize the popover to fit content. Must be called on the main thread."""
        if not self._popover:
            return
        from Foundation import NSMakeSize
        clamped = max(POPOVER_HEIGHT, min(height + 8, 760))
        self._popover.setContentSize_(NSMakeSize(POPOVER_WIDTH, clamped))
        if self._web_view:
            from Foundation import NSMakeRect
            self._web_view.setFrame_(NSMakeRect(0, 0, POPOVER_WIDTH, clamped))

    def close_popover(self) -> None:
        if self._popover and self._popover.isShown():
            self._popover.close()

    def remove(self) -> None:
        if self._status_item:
            NSStatusBar.systemStatusBar().removeStatusItem_(self._status_item)
            self._status_item = None
