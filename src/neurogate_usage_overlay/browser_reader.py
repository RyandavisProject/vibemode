from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from .models import UsageSnapshot, UsageWindow
from .parser import parse_usage_text


USAGE_URL = "https://portal.neurogate.space/client/usage"


@dataclass(slots=True)
class BrowserSettings:
    usage_url: str = USAGE_URL
    profile_dir: Path = Path.home() / ".neurogate-usage-overlay" / "browser-profile"
    headless: bool = True
    show_browser_on_login: bool = True
    hide_after_successful_login: bool = True
    browser_channel: str = "chrome"
    timeout_ms: int = 45_000
    debug_log: Path = Path.home() / ".neurogate-usage-overlay" / "overlay-debug.log"
    cache_file: Path = Path.home() / ".neurogate-usage-overlay" / "last-good-snapshot.json"


class NeurogateUsageReader:
    def __init__(self, settings: BrowserSettings) -> None:
        self.settings = settings
        self._playwright = None
        self._context = None
        self._page = None
        self._current_headless: bool | None = None
        self._login_visible = False

    def start(self) -> None:
        try:
            from playwright.sync_api import sync_playwright
        except ImportError as exc:
            raise RuntimeError(
                "Playwright is not installed. Run scripts\\install.ps1 first."
            ) from exc

        self.settings.profile_dir.mkdir(parents=True, exist_ok=True)
        if not self._playwright:
            self._playwright = sync_playwright().start()
        self._launch_context(headless=self.settings.headless)

    def _launch_context(self, headless: bool) -> None:
        assert self._playwright is not None
        self._close_context()
        self._context = self._playwright.chromium.launch_persistent_context(
            user_data_dir=str(self.settings.profile_dir),
            channel=self.settings.browser_channel,
            headless=headless,
            viewport={"width": 1440, "height": 950},
            args=["--disable-blink-features=AutomationControlled"],
        )
        self._current_headless = headless
        self._login_visible = False
        if self._context.pages:
            self._page = self._context.pages[0]
        else:
            self._page = self._context.new_page()
        self._page.set_default_timeout(self.settings.timeout_ms)
        self._page.goto(self.settings.usage_url, wait_until="domcontentloaded")

    def _close_context(self) -> None:
        if self._context:
            self._context.close()
            self._context = None
        self._page = None
        self._current_headless = None

    def stop(self) -> None:
        self._close_context()
        if self._playwright:
            self._playwright.stop()
            self._playwright = None

    def read(self) -> UsageSnapshot:
        if not self._page:
            self.start()
        assert self._page is not None
        if self.settings.usage_url not in self._page.url:
            self._page.goto(self.settings.usage_url, wait_until="domcontentloaded")
        text = self._wait_for_usage_text()
        if self._is_login_text(text) and self._current_headless and self.settings.show_browser_on_login:
            self._open_visible_login_window()
            text = self._wait_for_usage_text()
        snapshot = parse_usage_text(text, source_url=self._page.url)
        if not snapshot.windows and not self._is_login_text(text):
            self._expand_usage_card(force=True)
            text = self._wait_for_usage_text()
            snapshot = parse_usage_text(text, source_url=self._page.url)
        if snapshot.has_data:
            self._write_cache(snapshot)
            self._login_visible = False
            self._hide_visible_browser_after_success()
        else:
            self._login_visible = self._is_login_text(snapshot.raw_text) and self._current_headless is False
            cached = self._read_cache(status_note=self._fallback_status(snapshot.raw_text))
            if cached:
                self._write_debug(snapshot, note="using_cached_snapshot")
                return cached
        self._write_debug(snapshot)
        return snapshot

    def refresh(self) -> UsageSnapshot:
        if not self._page:
            self.start()
        assert self._page is not None
        if not self._login_visible:
            self._page.reload(wait_until="domcontentloaded")
        return self.read()

    def _is_login_text(self, text: str) -> bool:
        return "EMAIL" in text or "Connect Codex" in text or "ПАРОЛЬ" in text or "Войти" in text

    def _open_visible_login_window(self) -> None:
        self._write_debug(parse_usage_text("", source_url=self.settings.usage_url), note="opening_visible_login")
        self._launch_context(headless=False)
        self._login_visible = True

    def _hide_visible_browser_after_success(self) -> None:
        if (
            self.settings.headless
            and self.settings.hide_after_successful_login
            and self._current_headless is False
        ):
            self._write_debug(parse_usage_text("", source_url=self.settings.usage_url), note="hiding_browser_after_login")
            self._launch_context(headless=True)

    def _wait_for_usage_text(self) -> str:
        assert self._page is not None
        last_text = ""
        for _attempt in range(30):
            self._page.wait_for_timeout(500)
            last_text = self._page.locator("body").inner_text(timeout=self.settings.timeout_ms)
            if "EMAIL" in last_text or "Connect Codex" in last_text:
                return last_text
            if last_text.count("Кредитов осталось") >= 2:
                return last_text
            if "ЛИМИТЫ ТАРИФА" in last_text:
                return last_text
        return last_text

    def _expand_usage_card(self, force: bool = False) -> None:
        assert self._page is not None
        if force:
            self._click_usage_window()
            return
        self._click_usage_window()

    def _click_usage_window(self) -> None:
        assert self._page is not None
        try:
            candidate = self._page.locator('[role="button"].usage-window').first
            if candidate.count() > 0 and candidate.is_visible(timeout=1000):
                candidate.click(timeout=3000)
                self._page.wait_for_timeout(900)
                return
        except Exception:
            pass

        self._page.evaluate(
            """() => {
                const node = document.querySelector('[role="button"].usage-window');
                if (node) node.click();
            }"""
        )
        self._page.wait_for_timeout(900)

    def _write_cache(self, snapshot: UsageSnapshot) -> None:
        try:
            self.settings.cache_file.parent.mkdir(parents=True, exist_ok=True)
            payload = {
                "updated_at": snapshot.updated_at.isoformat(),
                "account": snapshot.account,
                "model_group": snapshot.model_group,
                "total_used": snapshot.total_used,
                "remaining": snapshot.remaining,
                "plan_status": snapshot.plan_status,
                "source_url": snapshot.source_url,
                "windows": [
                    {
                        "title": item.title,
                        "tokens": item.tokens,
                        "cache": item.cache,
                        "limit_used": item.limit_used,
                        "limit_total": item.limit_total,
                        "credits_remaining": item.credits_remaining,
                        "reset_text": item.reset_text,
                    }
                    for item in snapshot.windows
                ],
            }
            self.settings.cache_file.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        except Exception:
            pass

    def _fallback_status(self, text: str) -> str:
        if "EMAIL" in text or "Connect Codex" in text:
            return "нужен вход"
        return "кэш"

    def _read_cache(self, status_note: str | None = None) -> UsageSnapshot | None:
        try:
            if not self.settings.cache_file.exists():
                return None
            payload = json.loads(self.settings.cache_file.read_text(encoding="utf-8"))
            return UsageSnapshot(
                updated_at=datetime.fromisoformat(payload["updated_at"]),
                account=payload.get("account"),
                model_group=payload.get("model_group"),
                total_used=payload.get("total_used"),
                remaining=payload.get("remaining"),
                plan_status=payload.get("plan_status"),
                source_url=payload.get("source_url"),
                windows=[
                    UsageWindow(
                        title=item.get("title", ""),
                        tokens=item.get("tokens"),
                        cache=item.get("cache"),
                        limit_used=item.get("limit_used"),
                        limit_total=item.get("limit_total"),
                        credits_remaining=item.get("credits_remaining"),
                        reset_text=item.get("reset_text"),
                    )
                    for item in payload.get("windows", [])
                ],
                is_cached=True,
                status_note=status_note or "кэш",
            )
        except Exception:
            return None

    def _write_debug(self, snapshot: UsageSnapshot, note: str = "") -> None:
        try:
            self.settings.debug_log.parent.mkdir(parents=True, exist_ok=True)
            windows = "; ".join(
                f"{item.title} rem={item.credits_remaining} used={item.limit_used}/{item.limit_total}"
                for item in snapshot.windows
            )
            line = (
                f"{datetime.now().isoformat(timespec='seconds')} "
                f"account={snapshot.account!r} total={snapshot.total_used} "
                f"remaining={snapshot.remaining} windows={len(snapshot.windows)} "
                f"url={snapshot.source_url!r} {windows} "
                f"note={note!r} text={snapshot.raw_text[:240]!r}\n"
            )
            with self.settings.debug_log.open("a", encoding="utf-8") as handle:
                handle.write(line)
        except Exception:
            pass
