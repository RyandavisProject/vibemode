from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .browser_reader import BrowserSettings, NeurogateUsageReader, USAGE_URL
from .overlay import UsageOverlay


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
    settings = BrowserSettings(
        usage_url=args.url,
        profile_dir=args.profile_dir,
        headless=args.headless or not args.show_browser,
        browser_channel=args.browser_channel,
    )
    reader = NeurogateUsageReader(settings)

    try:
        reader.start()
        if args.once:
            snapshot = reader.read()
            print(snapshot)
            return 0
        overlay = UsageOverlay(
            reader.refresh,
            interval_seconds=args.interval,
            keep_browser_open_getter=lambda: reader.keep_browser_open,
            keep_browser_open_setter=reader.set_keep_browser_open,
            account_resetter=reader.reset_account_session,
        )
        overlay.run()
        return 0
    finally:
        reader.stop()


if __name__ == "__main__":
    raise SystemExit(main())
