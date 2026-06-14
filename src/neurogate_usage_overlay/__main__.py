from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from .browser_reader import BrowserSettings, NeurogateUsageReader, USAGE_URL
from .overlay import UsageOverlay
from .reader_worker import ThreadedUsageReader
from .single_instance import SingleInstanceLock


def _write_pid_file(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(str(os.getpid()), encoding="utf-8")


def _remove_pid_file(path: Path) -> None:
    try:
        if path.read_text(encoding="utf-8").strip() == str(os.getpid()):
            path.unlink()
    except FileNotFoundError:
        return
    except Exception:
        return


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="NeuroGate API usage overlay.")
    parser.add_argument("--url", default=USAGE_URL, help="Usage page URL.")
    parser.add_argument("--interval", type=int, default=60, help="Refresh interval in seconds.")
    parser.add_argument(
        "--profile-dir",
        type=Path,
        default=Path.home() / ".neurogate-usage-overlay" / "browser-profile",
        help="Local browser profile directory. Contains cookies/session, not passwords from this app.",
    )
    parser.add_argument(
        "--show-browser",
        action="store_true",
        help="Keep the browser visible instead of using the default hidden mode after login.",
    )
    parser.add_argument(
        "--headless",
        action="store_true",
        help="Compatibility flag. Hidden mode is already the default.",
    )
    parser.add_argument("--browser-channel", default="chrome", help="Playwright browser channel, usually chrome.")
    parser.add_argument("--once", action="store_true", help="Print one snapshot and exit.")
    return parser


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    args = build_parser().parse_args()
    state_dir = args.profile_dir.parent
    lock = SingleInstanceLock(state_dir / "overlay.lock")
    if not lock.acquire():
        print("NeuroGate API overlay is already running.")
        return 0
    pid_file = state_dir / "overlay.pid"
    _write_pid_file(pid_file)

    settings = BrowserSettings(
        usage_url=args.url,
        profile_dir=args.profile_dir,
        headless=args.headless or not args.show_browser,
        browser_channel=args.browser_channel,
    )
    try:
        if args.once:
            reader = NeurogateUsageReader(settings)
            reader.start()
            snapshot = reader.read()
            print(snapshot)
            reader.stop()
            return 0
        reader = ThreadedUsageReader(settings)
        overlay = UsageOverlay(
            reader.refresh,
            interval_seconds=args.interval,
            keep_browser_open_getter=lambda: reader.keep_browser_open,
            keep_browser_open_setter=reader.set_keep_browser_open,
            account_resetter=reader.reset_account_session,
            async_refresh=True,
        )
        overlay.run()
        return 0
    finally:
        try:
            if "reader" in locals():
                reader.stop()
        finally:
            _remove_pid_file(pid_file)
            lock.release()


if __name__ == "__main__":
    raise SystemExit(main())
