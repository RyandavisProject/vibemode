from __future__ import annotations

import sys
from dataclasses import dataclass
from typing import Any, Callable


PowerCallback = Callable[[], None]
_POWER_OBSERVER_CLASS: Any | None = None


@dataclass
class MacOSPowerObserver:
    center: Any
    observer: Any

    def uninstall(self) -> None:
        try:
            self.center.removeObserver_(self.observer)
        except Exception:
            return


def install_macos_power_observer(
    *,
    on_sleep: PowerCallback,
    on_wake: PowerCallback,
) -> MacOSPowerObserver | None:
    if sys.platform != "darwin":
        return None
    global _POWER_OBSERVER_CLASS
    try:
        import objc
        from AppKit import (
            NSWorkspace,
            NSWorkspaceDidWakeNotification,
            NSWorkspaceScreensDidWakeNotification,
            NSWorkspaceWillSleepNotification,
        )
        from Foundation import NSObject
    except Exception:
        return None

    if _POWER_OBSERVER_CLASS is None:
        class _PowerObserver(NSObject):  # type: ignore[misc, valid-type]
            def setup_(self, callbacks):  # noqa: ANN001 - PyObjC selector signature.
                self._on_sleep, self._on_wake = callbacks
                return self

            def willSleep_(self, _notification):  # noqa: ANN001 - PyObjC selector signature.
                self._on_sleep()

            def didWake_(self, _notification):  # noqa: ANN001 - PyObjC selector signature.
                self._on_wake()

        _POWER_OBSERVER_CLASS = _PowerObserver

    try:
        observer = _POWER_OBSERVER_CLASS.alloc().init().setup_((on_sleep, on_wake))
        center = NSWorkspace.sharedWorkspace().notificationCenter()
        center.addObserver_selector_name_object_(
            observer,
            objc.selector(observer.willSleep_, selector=b"willSleep:", signature=b"v@:@"),
            NSWorkspaceWillSleepNotification,
            None,
        )
        wake_selector = objc.selector(observer.didWake_, selector=b"didWake:", signature=b"v@:@")
        center.addObserver_selector_name_object_(observer, wake_selector, NSWorkspaceDidWakeNotification, None)
        center.addObserver_selector_name_object_(observer, wake_selector, NSWorkspaceScreensDidWakeNotification, None)
        return MacOSPowerObserver(center, observer)
    except Exception:
        return None
