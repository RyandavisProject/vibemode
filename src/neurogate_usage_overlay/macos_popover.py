"""macOS NSStatusItem + NSPopover + WKWebView menu bar UI.

All AppKit/WebKit calls happen on the main thread (required by macOS).
The PopoverServer runs in a daemon thread and serves the HTML/data.
"""
from __future__ import annotations

from typing import Any, Callable

import objc
from AppKit import (
    NSApplication,
    NSImage,
    NSStatusBar,
    NSVariableStatusItemLength,
)
from Foundation import NSObject, NSString, NSURL, NSURLRequest
from WebKit import WKWebView, WKWebViewConfiguration, WKUserScript, WKUserScriptInjectionTimeAtDocumentEnd

# Lazy import — only needed at runtime on macOS
_AppKit = None


# ── JS bridge: intercepts window.__ng_action(name) calls ─────────────────────
_BRIDGE_SCRIPT = """
window.__ng_action = function(name) {
    fetch('/action/' + name, {method: 'POST'}).catch(function(){});
};
// Report content height to NSPopover after render
function __ng_resize() {
    var h = document.documentElement.scrollHeight;
    fetch('/resize/' + h, {method: 'POST'}).catch(function(){});
}
document.addEventListener('DOMContentLoaded', function() {
    __ng_resize();
    new MutationObserver(__ng_resize).observe(document.body, {childList: true, subtree: true, characterData: true});
});
"""

POPOVER_WIDTH  = 300
POPOVER_HEIGHT = 380


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
        if self._popover.isShown():
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

    def __init__(self, server_url: str, initial_title: str = "NG …") -> None:
        self._server_url = server_url
        self._initial_title = initial_title
        self._status_item: Any = None
        self._popover: Any = None
        self._web_view: Any = None
        self._delegate: Any = None

    # Call from main thread only
    def install(self) -> None:
        """Create the status item and popover. Must be called on the main thread."""
        self._popover, self._web_view = _make_popover(self._server_url)

        bar = NSStatusBar.systemStatusBar()
        self._status_item = bar.statusItemWithLength_(NSVariableStatusItemLength)

        btn = self._status_item.button()
        btn.setTitle_(self._initial_title)

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
        if self._status_item:
            self._status_item.button().setTitle_(title)

    def resize_to_content(self, height: int) -> None:
        """Resize the popover to fit content. Must be called on the main thread."""
        if not self._popover:
            return
        from Foundation import NSMakeSize
        clamped = max(200, min(height + 8, 600))
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
