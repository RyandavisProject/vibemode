from __future__ import annotations

import os
import re
import signal
import shutil
import subprocess
import sys
import time
from typing import Any
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from .models import UsageSnapshot, UsageWindow
from .log_utils import append_bounded_log
from .parser import has_invalid_session, has_stale_cabinet_data, parse_usage_text


USAGE_URL = "https://portal.vibemod.pro/client"
VIBEMODE_API_BASE_URL = "https://api.vibemod.pro"
VISIBLE_WINDOW_ARGS = ("--window-position=96,80", "--window-size=1180,860")
HIDDEN_WINDOW_ARGS = ("--window-position=-32000,-32000", "--window-size=1440,950")
LOGIN_CONFIRM_ATTEMPTS = 10
LOGIN_PROMPT_CONFIRM_ATTEMPTS = 3
AUTO_LOGIN_DELAY_ATTEMPTS = 3
PROFILE_CACHE_DIRS = (
    "GrShaderCache",
    "ShaderCache",
    "GraphiteDawnCache",
    "GPUPersistentCache",
    "Default/Cache",
    "Default/Code Cache",
    "Default/GPUCache",
    "Default/DawnWebGPUCache",
    "Default/DawnGraphiteCache",
    "Default/Service Worker/CacheStorage",
    "Default/Service Worker/ScriptCache",
)
CACHE_SIZE_BYTES = 16 * 1024 * 1024
PROFILE_BROWSER_TERMINATION_TIMEOUT_SECONDS = 1.5


def terminate_profile_browser_processes(
    profile_dir: Path,
    *,
    timeout_seconds: float = PROFILE_BROWSER_TERMINATION_TIMEOUT_SECONDS,
) -> int:
    """Terminate macOS Chrome processes that belong to the overlay profile only."""
    if sys.platform != "darwin":
        return 0
    try:
        needle = str(profile_dir.resolve())
        result = subprocess.run(
            ["ps", "-axo", "pid=,command="],
            check=False,
            capture_output=True,
            text=True,
            timeout=3,
        )
    except Exception:
        return 0

    current_pid = os.getpid()
    pids: set[int] = set()
    for line in result.stdout.splitlines():
        try:
            pid_text, command = line.strip().split(None, 1)
            pid = int(pid_text)
        except ValueError:
            continue
        if pid == current_pid or needle not in command:
            continue
        pids.add(pid)

    for pid in pids:
        try:
            os.kill(pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
        except Exception:
            continue

    deadline = time.monotonic() + max(0.0, timeout_seconds)
    while time.monotonic() < deadline:
        alive = [pid for pid in pids if _process_is_alive(pid)]
        if not alive:
            break
        time.sleep(0.05)

    for pid in pids:
        if not _process_is_alive(pid):
            continue
        try:
            os.kill(pid, signal.SIGKILL)
        except Exception:
            pass
    return len(pids)


def _process_is_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except Exception:
        return False
    return True


def _as_int(value: object) -> int | None:
    if value is None:
        return None
    try:
        return round(float(value))
    except (TypeError, ValueError):
        return None


def _format_plan_days_left(value: object, now: datetime | None = None) -> str | None:
    if not value:
        return None
    try:
        ends_at = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    current = now or datetime.now().astimezone()
    if ends_at.tzinfo is None:
        ends_at = ends_at.replace(tzinfo=current.tzinfo)
    delta_seconds = (ends_at - current).total_seconds()
    if delta_seconds <= 0:
        return "истёк"
    days = max(1, int((delta_seconds + 86_399) // 86_400))
    return f"{days} дн осталось"


def _vibemode_window(
    title: str,
    used_value: object,
    total_value: object,
    *,
    reset_text: str | None = None,
) -> UsageWindow | None:
    used = _as_int(used_value)
    total = _as_int(total_value)
    if total is None or total <= 0:
        return None
    used = max(0, used or 0)
    remaining = max(0, total - used)
    return UsageWindow(
        title=title,
        limit_used=used,
        limit_total=total,
        credits_remaining=remaining,
        reset_text=reset_text,
        progress_percent=min(100.0, (used / total) * 100),
    )


def _parse_vibemode_amount(value: str | None) -> int | None:
    if not value:
        return None
    cleaned = value.strip().replace("\u00a0", " ").replace(",", ".")
    match = re.search(r"(\d+(?:\.\d+)?)\s*([kкmмbб])?", cleaned, flags=re.IGNORECASE)
    if not match:
        return None
    amount = float(match.group(1))
    suffix = (match.group(2) or "").lower()
    multiplier = 1
    if suffix in {"k", "к"}:
        multiplier = 1_000
    elif suffix in {"m", "м"}:
        multiplier = 1_000_000
    elif suffix in {"b", "б"}:
        multiplier = 1_000_000_000
    return round(amount * multiplier)


def _vibemode_text_window(title: str, text: str) -> UsageWindow | None:
    label = "5-часовое окно" if "5" in title else "7-дневное окно"
    match = re.search(
        rf"{re.escape(label)}(?P<segment>.*?)(?:\n\s*(?:КВОТА|CLAUDE|АКТИВНОСТЬ)\b|\Z)",
        text,
        flags=re.IGNORECASE | re.DOTALL,
    )
    if not match:
        return None
    segment = match.group("segment")
    reset_text = _vibemode_reset_text_from_segment(segment)
    used_total = re.search(
        r"(?P<used>\d+(?:[.,]\d+)?\s*[kкmмbб]?)\s*\n\s*из\s+(?P<total>\d+(?:[.,]\d+)?\s*[kкmмbб]?)",
        segment,
        flags=re.IGNORECASE,
    )
    if not used_total:
        return None
    return _vibemode_window(
        title,
        _parse_vibemode_amount(used_total.group("used")),
        _parse_vibemode_amount(used_total.group("total")),
        reset_text=reset_text,
    )


def _vibemode_reset_text_from_segment(segment: str) -> str | None:
    match = re.search(r"Сброс\s+через\s+([^\n\r]+)", segment, flags=re.IGNORECASE)
    return match.group(1).strip() if match else None


def _vibemode_window_key(title: str) -> str:
    if "5" in title:
        return "5h"
    if "7" in title:
        return "7d"
    return title.strip().lower()


def _vibemode_reset_texts(text: str) -> dict[str, str]:
    resets: dict[str, str] = {}
    for title in ("5 часов", "7 дней"):
        label = "5-часовое окно" if "5" in title else "7-дневное окно"
        match = re.search(
            rf"{re.escape(label)}(?P<segment>.*?)(?:\n\s*(?:КВОТА|CLAUDE|АКТИВНОСТЬ)\b|\Z)",
            text,
            flags=re.IGNORECASE | re.DOTALL,
        )
        if not match:
            continue
        reset_text = _vibemode_reset_text_from_segment(match.group("segment"))
        if reset_text:
            resets[_vibemode_window_key(title)] = reset_text
    return resets


def _attach_vibemode_reset_texts(snapshot: UsageSnapshot, text: str) -> None:
    if not text or not snapshot.windows:
        return
    resets = _vibemode_reset_texts(text)
    if not resets:
        return
    for window in snapshot.windows:
        if not window.reset_text:
            window.reset_text = resets.get(_vibemode_window_key(window.title))


def _snapshot_from_vibemode_text(text: str, *, source_url: str | None) -> UsageSnapshot | None:
    if "5-часовое окно" not in text.lower() or "7-дневное окно" not in text.lower():
        return None

    snapshot = UsageSnapshot(
        updated_at=datetime.now().astimezone(),
        source_url=source_url,
        raw_text=text,
    )

    lines = [line.strip() for line in text.splitlines() if line.strip()]
    for index, line in enumerate(lines):
        if line.lower() == "план" and index + 1 < len(lines):
            snapshot.account = lines[index + 1]
            if index + 2 < len(lines) and "остал" in lines[index + 2].lower():
                snapshot.plan_status = lines[index + 2].lower()
            break

    windows = [
        _vibemode_text_window("5 часов", text),
        _vibemode_text_window("7 дней", text),
    ]
    snapshot.windows = [window for window in windows if window is not None]
    return snapshot if snapshot.has_data or snapshot.account else None


def _snapshot_from_vibemode_api(
    profile: dict[str, Any] | None,
    limits: dict[str, Any] | None,
    *,
    source_url: str | None,
    raw_text: str = "",
) -> UsageSnapshot | None:
    if not profile and not limits:
        return None

    snapshot = UsageSnapshot(
        updated_at=datetime.now().astimezone(),
        source_url=source_url,
        raw_text=raw_text,
    )

    plan = profile.get("plan") if isinstance(profile, dict) else None
    if isinstance(plan, dict):
        snapshot.account = str(plan.get("name") or plan.get("code") or "").strip() or None
        snapshot.plan_status = _format_plan_days_left(plan.get("endsAt"))
    elif isinstance(profile, dict):
        plan_code = str(profile.get("currentPlanCode") or "").strip()
        snapshot.account = plan_code.capitalize() if plan_code else None
        snapshot.plan_status = _format_plan_days_left(profile.get("currentPlanEndsAt"))

    rows = limits.get("rows") if isinstance(limits, dict) else None
    if not isinstance(rows, list):
        return snapshot if snapshot.account else None

    default_row = next(
        (
            row
            for row in rows
            if isinstance(row, dict)
            and row.get("scope") == "default"
            and (_as_int(row.get("creditLimit5Hours")) or _as_int(row.get("creditLimit7Days")))
        ),
        None,
    )
    if default_row is None:
        default_row = next(
            (
                row
                for row in rows
                if isinstance(row, dict)
                and (_as_int(row.get("creditLimit5Hours")) or _as_int(row.get("creditLimit7Days")))
            ),
            None,
        )
    if not isinstance(default_row, dict):
        return snapshot if snapshot.account else None

    five_hour = _vibemode_window(
        "5 часов",
        default_row.get("credits5Hours"),
        default_row.get("creditLimit5Hours"),
    )
    seven_day = _vibemode_window(
        "7 дней",
        default_row.get("credits7Days"),
        default_row.get("creditLimit7Days"),
    )
    snapshot.windows = [window for window in (five_hour, seven_day) if window is not None]
    _attach_vibemode_reset_texts(snapshot, raw_text)
    return snapshot if snapshot.has_data or snapshot.account else None


def _hide_windows_for_pids(process_ids: set[int]) -> int:
    """Hide visible browser windows by PID. Windows-only; no-op on other platforms."""
    if not process_ids or not sys.platform.startswith("win"):
        return 0

    import ctypes

    user32 = ctypes.windll.user32
    hidden_count = 0

    def callback(hwnd: int, _lparam: int) -> bool:
        nonlocal hidden_count
        pid = ctypes.c_ulong()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        if pid.value in process_ids and user32.IsWindowVisible(hwnd):
            user32.ShowWindow(hwnd, 0)
            hidden_count += 1
        return True

    enum_windows_proc = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)
    user32.EnumWindows(enum_windows_proc(callback), 0)
    return hidden_count


@dataclass(slots=True)
class BrowserSettings:
    usage_url: str = USAGE_URL
    profile_dir: Path = Path.home() / ".neurogate-usage-overlay" / "browser-profile"
    headless: bool = True
    show_browser_on_login: bool = True
    hide_after_successful_login: bool = True
    auto_login: bool = True
    browser_channel: str = "chrome"
    timeout_ms: int = 45_000
    debug_log: Path = Path.home() / ".neurogate-usage-overlay" / "overlay-debug.log"


class NeurogateUsageReader:
    def __init__(self, settings: BrowserSettings) -> None:
        self.settings = settings
        self._playwright = None
        self._context = None
        self._page = None
        self._current_headless: bool | None = None
        self._login_visible = False
        self._login_prompt_opened = False
        self._account_switch_pending = False

    def start(self) -> None:
        try:
            from playwright.sync_api import sync_playwright
        except ImportError as exc:
            install_hint = "scripts\\install.ps1" if sys.platform.startswith("win") else "scripts/install.sh"
            raise RuntimeError(
                f"Playwright is not installed. Run {install_hint} first."
            ) from exc

        self.settings.profile_dir.mkdir(parents=True, exist_ok=True)
        self._prune_browser_caches()
        if not self._playwright:
            self._playwright = sync_playwright().start()
        self._launch_context(headless=self.settings.headless)

    def _launch_context(self, headless: bool) -> None:
        assert self._playwright is not None
        self._close_context()
        args = self._browser_args(hidden=headless)
        self._context = self._playwright.chromium.launch_persistent_context(
            user_data_dir=str(self.settings.profile_dir),
            channel=self.settings.browser_channel,
            # The portal behaves differently in true headless mode and can
            # intermittently lose tariff data. Hidden mode uses headed Chrome
            # offscreen so the session stays equivalent to the user's browser.
            headless=False,
            ignore_default_args=["--no-sandbox"],
            viewport={"width": 1440, "height": 950},
            args=args,
        )
        self._current_headless = headless
        self._login_visible = False
        if self._context.pages:
            self._page = self._context.pages[0]
        else:
            self._page = self._context.new_page()
        self._page.set_default_timeout(self.settings.timeout_ms)
        self._page.goto(self.settings.usage_url, wait_until="domcontentloaded")
        if headless:
            self._hide_hidden_browser_taskbar_windows()

    def _browser_args(self, hidden: bool) -> list[str]:
        args = [
            f"--disk-cache-size={CACHE_SIZE_BYTES}",
            f"--media-cache-size={CACHE_SIZE_BYTES}",
        ]
        if hidden:
            args.extend(HIDDEN_WINDOW_ARGS)
        else:
            args.extend(VISIBLE_WINDOW_ARGS)
        return args

    def _prune_browser_caches(self) -> None:
        for relative_path in PROFILE_CACHE_DIRS:
            target = self.settings.profile_dir / Path(relative_path)
            try:
                if target.exists():
                    shutil.rmtree(target)
            except Exception as exc:  # noqa: BLE001 - cache cleanup must not block the overlay.
                self._write_debug(
                    parse_usage_text("", source_url=self.settings.usage_url),
                    note=f"cache_cleanup_failed path={relative_path!r} error={exc!r}",
                )

    def _hide_hidden_browser_taskbar_windows(self) -> int:
        if sys.platform.startswith("win"):
            pids = self._profile_browser_process_ids_windows()
            if not pids:
                return 0
            return _hide_windows_for_pids(pids)
        if sys.platform == "darwin":
            return self._hide_offscreen_chrome_macos()
        return 0

    def _profile_browser_process_ids_windows(self) -> set[int]:
        needle = str(self.settings.profile_dir.resolve()).replace("'", "''").lower()
        script = (
            "$needle = '" + needle + "'\n"
            "Get-CimInstance Win32_Process -Filter \"Name = 'chrome.exe'\" | "
            "Where-Object { $_.CommandLine -and $_.CommandLine.ToLower().Contains($needle) } | "
            "ForEach-Object { $_.ProcessId }"
        )
        try:
            result = subprocess.run(
                ["powershell", "-NoProfile", "-Command", script],
                check=False,
                capture_output=True,
                text=True,
                timeout=3,
            )
        except Exception:
            return set()
        pids: set[int] = set()
        for line in result.stdout.splitlines():
            try:
                pids.add(int(line.strip()))
            except ValueError:
                pass
        return pids

    def _hide_offscreen_chrome_macos(self) -> int:
        """On macOS, Chrome is already positioned offscreen via HIDDEN_WINDOW_ARGS.

        There is no system API to hide windows of other processes without
        Accessibility permissions. The offscreen placement (-32000,-32000)
        keeps the browser invisible in practice.  We use AppleScript to move
        Chrome windows off-screen only when we can, but we never raise an error
        if the call fails — the overlay must keep working regardless.
        """
        needle = str(self.settings.profile_dir.resolve())
        try:
            result = subprocess.run(
                ["pgrep", "-f", needle],
                check=False,
                capture_output=True,
                text=True,
                timeout=3,
            )
            pids: set[int] = set()
            for line in result.stdout.splitlines():
                try:
                    pids.add(int(line.strip()))
                except ValueError:
                    pass
            if not pids:
                return 0
            # AppleScript cannot target windows by PID without Accessibility
            # permissions, so just report that we found processes; the browser
            # stays at -32000,-32000 which is effectively hidden.
            return len(pids)
        except Exception:
            return 0

    def _close_context(self) -> None:
        if self._context:
            try:
                self._context.close()
            except Exception as exc:
                self._write_debug(
                    parse_usage_text("", source_url=self.settings.usage_url),
                    note=f"close_context_error={exc!r}",
                )
            finally:
                self._context = None
        self._page = None
        self._current_headless = None

    def stop(self) -> None:
        self._close_context()
        if self._playwright:
            self._playwright.stop()
            self._playwright = None

    @property
    def keep_browser_open(self) -> bool:
        return not self.settings.headless

    def set_keep_browser_open(self, enabled: bool) -> None:
        self.settings.headless = not enabled
        self.settings.hide_after_successful_login = not enabled
        self.settings.show_browser_on_login = enabled
        self._write_debug(
            parse_usage_text("", source_url=self.settings.usage_url),
            note=f"keep_browser_open={enabled}",
        )
        if not self._playwright:
            return
        if enabled and self._current_headless is not False:
            self._login_prompt_opened = True
            self._launch_context(headless=False)
            return
        if not enabled and self._current_headless is False:
            if sys.platform == "darwin":
                self._hide_current_browser_window()
                return
            self._hide_current_browser_window()

    def read(self) -> UsageSnapshot:
        if not self._page:
            self.start()
        assert self._page is not None
        if self.settings.usage_url not in self._page.url:
            self._page.goto(self.settings.usage_url, wait_until="domcontentloaded")
        text = self._wait_for_usage_text()
        if self._requires_visible_login(text) and self._current_headless and self.settings.show_browser_on_login:
            if self._maybe_auto_submit_login():
                text = self._wait_for_usage_text()
            if self._requires_visible_login(text):
                self._open_visible_login_window()
                self._maybe_auto_submit_login()
                text = self._wait_for_usage_text()
        snapshot = (
            self._read_vibemode_api_snapshot(text)
            or _snapshot_from_vibemode_text(text, source_url=self._page.url)
            or parse_usage_text(text, source_url=self._page.url)
        )
        if not self._is_vibemode_url(self._page.url):
            self._attach_window_progress(snapshot)
        if not snapshot.windows and not self._is_login_text(text):
            self._expand_usage_card(force=True)
            text = self._wait_for_usage_text()
            snapshot = (
                self._read_vibemode_api_snapshot(text)
                or _snapshot_from_vibemode_text(text, source_url=self._page.url)
                or parse_usage_text(text, source_url=self._page.url)
            )
            if not self._is_vibemode_url(self._page.url):
                self._attach_window_progress(snapshot)
        if snapshot.has_data:
            self._login_prompt_opened = False
            self._login_visible = False
            self._account_switch_pending = False
            self._hide_visible_browser_after_success()
        else:
            self._login_visible = self._is_login_text(snapshot.raw_text) and self._current_headless is False
            snapshot.status_note = self._fallback_status(snapshot.raw_text)
        self._write_debug(snapshot)
        return snapshot

    def refresh(self) -> UsageSnapshot:
        if not self._page:
            self.start()
        assert self._page is not None
        if not self._login_visible:
            if self._current_page_has_usage_data():
                self._click_portal_refresh()
            else:
                self._page.reload(wait_until="domcontentloaded")
        return self.read()

    def _is_login_text(self, text: str) -> bool:
        return (
            "EMAIL" in text
            or "Connect Codex" in text
            or "ПАРОЛЬ" in text
            or "awaiting credentials" in text
            or "Войти" in text
        )

    def _is_session_invalid_text(self, text: str) -> bool:
        return has_invalid_session(text)

    def _requires_visible_login(self, text: str) -> bool:
        return self._is_login_text(text) or self._is_session_invalid_text(text)

    def _open_visible_login_window(self) -> None:
        self._write_debug(parse_usage_text("", source_url=self.settings.usage_url), note="opening_visible_login")
        self._login_prompt_opened = True
        self._launch_context(headless=False)
        self._login_visible = True
        try:
            assert self._page is not None
            self._page.bring_to_front()
        except Exception:
            pass

    def reset_account_session(self) -> None:
        self._write_debug(parse_usage_text("", source_url=self.settings.usage_url), note="reset_account_session")
        self._close_context()
        if self.settings.profile_dir.exists():
            shutil.rmtree(self.settings.profile_dir)
        self._login_prompt_opened = True
        self._login_visible = True
        self._account_switch_pending = True
        if not self._playwright:
            self.start()
            self._close_context()
        self._launch_context(headless=False)
        try:
            assert self._page is not None
            self._page.bring_to_front()
        except Exception:
            pass

    def _maybe_auto_submit_login(self) -> bool:
        if not self.settings.auto_login or self._account_switch_pending:
            return False
        if not self._page:
            return False
        try:
            first_state = self._login_form_state()
            if not first_state.get("ready"):
                return False
            for _attempt in range(AUTO_LOGIN_DELAY_ATTEMPTS):
                self._page.wait_for_timeout(500)
                current_state = self._login_form_state()
                if not current_state.get("ready"):
                    return False
                if (
                    current_state.get("email") != first_state.get("email")
                    or current_state.get("password") != first_state.get("password")
                    or current_state.get("password_length") != first_state.get("password_length")
                ):
                    self._write_debug(
                        parse_usage_text("", source_url=self.settings.usage_url),
                        note="auto_login_cancelled_form_changed",
                    )
                    return False
            clicked = self._click_login_submit()
            if clicked:
                self._write_debug(parse_usage_text("", source_url=self.settings.usage_url), note="auto_login_submitted")
                self._page.wait_for_timeout(1200)
            return clicked
        except Exception as exc:
            self._write_debug(parse_usage_text("", source_url=self.settings.usage_url), note=f"auto_login_error={exc!r}")
            return False

    def _login_form_state(self) -> dict[str, object]:
        assert self._page is not None
        return self._page.evaluate(
            """() => {
                const inputs = Array.from(document.querySelectorAll("input"));
                const byText = (input, pattern) => {
                    const haystack = [
                        input.type,
                        input.name,
                        input.id,
                        input.autocomplete,
                        input.placeholder,
                        input.getAttribute("aria-label"),
                    ].filter(Boolean).join(" ").toLowerCase();
                    return pattern.test(haystack);
                };
                const email = inputs.find((input) => byText(input, /email|mail|login|user|почт|логин/i));
                const password = inputs.find((input) => input.type === "password" || byText(input, /password|парол/i));
                const emailValue = email ? email.value || "" : "";
                const passwordValue = password ? password.value || "" : "";
                return {
                    ready: Boolean(email && password && emailValue && passwordValue),
                    email: emailValue,
                    password: passwordValue ? "__filled__" : "",
                    password_length: passwordValue.length,
                };
            }"""
        )

    def _click_login_submit(self) -> bool:
        assert self._page is not None
        return bool(
            self._page.evaluate(
                """() => {
                    const normalize = (value) => (value || "").replace(/\\s+/g, " ").trim().toLowerCase();
                    const candidates = Array.from(document.querySelectorAll("button, input[type='submit'], [role='button']"));
                    const submit = candidates.find((node) => {
                        const text = normalize(node.innerText || node.value || node.getAttribute("aria-label"));
                        const type = normalize(node.getAttribute("type"));
                        return type === "submit" || text.includes("войти") || text.includes("login") || text.includes("sign in");
                    });
                    if (!submit) return false;
                    submit.click();
                    return true;
                }"""
            )
        )

    def _hide_visible_browser_after_success(self) -> None:
        if (
            self.settings.headless
            and self.settings.hide_after_successful_login
            and self._current_headless is False
        ):
            self._write_debug(parse_usage_text("", source_url=self.settings.usage_url), note="hiding_browser_after_login")
            self._hide_current_browser_window()

    def _hide_current_browser_window(self) -> int:
        if sys.platform == "darwin":
            self._close_context()
            self._login_visible = False
            return terminate_profile_browser_processes(self.settings.profile_dir)
        hidden_count = self._hide_hidden_browser_taskbar_windows()
        self._current_headless = True
        self._login_visible = False
        return hidden_count

    def _wait_for_usage_text(self) -> str:
        assert self._page is not None
        last_text = ""
        login_text = ""
        login_attempts = 0
        stale_text = ""
        stale_attempts = 0
        for _attempt in range(30):
            self._page.wait_for_timeout(500)
            last_text = self._page.locator("body").inner_text(timeout=self.settings.timeout_ms)
            if self._is_session_invalid_text(last_text):
                stale_text = last_text
                stale_attempts += 1
                if stale_attempts >= LOGIN_CONFIRM_ATTEMPTS:
                    return stale_text
                continue
            if has_stale_cabinet_data(last_text):
                stale_text = last_text
                stale_attempts += 1
                continue
            if last_text.count("Кредитов осталось") >= 2:
                return last_text
            if "ЛИМИТЫ ТАРИФА" in last_text:
                return last_text
            if "5-часовое окно" in last_text and "7-дневное окно" in last_text:
                return last_text
            if self._is_login_text(last_text):
                login_text = last_text
                login_attempts += 1
                if login_attempts >= LOGIN_PROMPT_CONFIRM_ATTEMPTS:
                    return login_text
                continue
            login_attempts = 0
            stale_attempts = 0
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

    def _current_page_has_usage_data(self) -> bool:
        assert self._page is not None
        try:
            text = self._page.locator("body").inner_text(timeout=3000)
        except Exception:
            return False
        if "5-часовое окно" in text and "7-дневное окно" in text:
            return True
        snapshot = parse_usage_text(text, source_url=self._page.url)
        return snapshot.has_data

    @staticmethod
    def _is_vibemode_url(url: str | None) -> bool:
        return bool(url and "portal.vibemod.pro" in url)

    def _read_vibemode_api_snapshot(self, page_text: str) -> UsageSnapshot | None:
        if not self._page or not self._is_vibemode_url(self._page.url):
            return None
        try:
            payload = self._page.evaluate(
                """async (apiBaseUrl) => {
                    const findToken = () => {
                        const raw = localStorage.getItem("vibemode-auth-session") || "";
                        const jwtPattern = /^[A-Za-z0-9_-]+\\.[A-Za-z0-9_-]+\\.[A-Za-z0-9_-]+$/;
                        const visit = (value, depth = 0) => {
                            if (depth > 5 || value == null) return null;
                            if (typeof value === "string") {
                                if (jwtPattern.test(value)) return value;
                                const match = value.match(/[A-Za-z0-9_-]+\\.[A-Za-z0-9_-]+\\.[A-Za-z0-9_-]+/);
                                return match && match[0];
                            }
                            if (Array.isArray(value)) {
                                for (const item of value) {
                                    const found = visit(item, depth + 1);
                                    if (found) return found;
                                }
                                return null;
                            }
                            if (typeof value === "object") {
                                const priorityKeys = ["accessToken", "access_token", "token", "jwt", "value"];
                                for (const key of priorityKeys) {
                                    const found = visit(value[key], depth + 1);
                                    if (found) return found;
                                }
                                for (const item of Object.values(value)) {
                                    const found = visit(item, depth + 1);
                                    if (found) return found;
                                }
                            }
                            return null;
                        };
                        try {
                            return visit(JSON.parse(raw)) || visit(raw);
                        } catch {
                            return visit(raw);
                        }
                    };

                    const token = findToken();
                    if (!token) return { ok: false, reason: "missing_token" };
                    const headers = { "accept": "application/json", "authorization": `Bearer ${token}` };
                    const [profileResponse, limitsResponse] = await Promise.all([
                        fetch(`${apiBaseUrl}/client/profile`, { headers }),
                        fetch(`${apiBaseUrl}/client/usage/limits`, { headers }),
                    ]);
                    return {
                        ok: profileResponse.ok && limitsResponse.ok,
                        profileStatus: profileResponse.status,
                        limitsStatus: limitsResponse.status,
                        profile: profileResponse.ok ? await profileResponse.json() : null,
                        limits: limitsResponse.ok ? await limitsResponse.json() : null,
                    };
                }""",
                VIBEMODE_API_BASE_URL,
            )
        except Exception as exc:  # noqa: BLE001 - text parser fallback should still run.
            self._write_debug(parse_usage_text("", source_url=self.settings.usage_url), note=f"vibemode_api_error={exc!r}")
            return None

        if not isinstance(payload, dict) or not payload.get("ok"):
            return None
        return _snapshot_from_vibemode_api(
            payload.get("profile"),
            payload.get("limits"),
            source_url=self._page.url,
            raw_text=page_text,
        )

    def _click_portal_refresh(self) -> None:
        assert self._page is not None
        try:
            self._page.evaluate(
                """() => {
                    const normalize = (value) => (value || "").replace(/\\s+/g, " ").trim().toLowerCase();
                    const nodes = Array.from(document.querySelectorAll("button, [role='button']"));
                    const refresh = nodes.find((node) => normalize(node.innerText).includes("обновить"));
                    if (refresh) refresh.click();
                }"""
            )
            self._page.wait_for_timeout(900)
        except Exception:
            pass

    def _attach_window_progress(self, snapshot: UsageSnapshot) -> None:
        if not snapshot.windows or not self._page:
            return
        try:
            progress_items = self._extract_window_progress()
        except Exception:
            return
        if not progress_items:
            return
        progress_by_key = {
            self._window_progress_key(str(item.get("title", ""))): item
            for item in progress_items
        }
        for window in snapshot.windows:
            item = progress_by_key.get(self._window_progress_key(window.title))
            if not item:
                continue
            percent = item.get("percent")
            if isinstance(percent, (int, float)):
                window.progress_percent = max(0.0, min(100.0, float(percent)))

    @staticmethod
    def _window_progress_key(title: str) -> str:
        if "5" in title:
            return "5h"
        if "24" in title:
            return "24h"
        if "7" in title:
            return "7d"
        return title.strip().lower()

    def _extract_window_progress(self) -> list[dict[str, float | str]]:
        assert self._page is not None
        return self._page.evaluate(
            """() => {
                const labels = ["5 часов", "24 часа", "7 дней"];

                const normalize = (value) => (value || "")
                    .replace(/\\s+/g, " ")
                    .trim()
                    .toLowerCase();

                const colorParts = (color) => {
                    const match = String(color).match(/rgba?\\((\\d+),\\s*(\\d+),\\s*(\\d+)/i);
                    return match ? match.slice(1, 4).map(Number) : null;
                };

                const isBlueFill = (element) => {
                    const rgb = colorParts(getComputedStyle(element).backgroundColor);
                    if (!rgb) return false;
                    const [r, g, b] = rgb;
                    return b > 150 && g > 90 && b > r + 45;
                };

                const percentFromAria = (element) => {
                    const raw = element.getAttribute("aria-valuenow") || element.getAttribute("value");
                    if (!raw) return null;
                    const parsed = Number(String(raw).replace(",", "."));
                    return Number.isFinite(parsed) ? parsed : null;
                };

                const percentFromStyle = (element) => {
                    const styleWidth = element.style && element.style.width;
                    if (styleWidth && styleWidth.includes("%")) {
                        const parsed = Number(styleWidth.replace("%", "").replace(",", "."));
                        if (Number.isFinite(parsed)) return parsed;
                    }
                    return null;
                };

                const percentFromGeometry = (element) => {
                    const rect = element.getBoundingClientRect();
                    const parentRect = element.parentElement && element.parentElement.getBoundingClientRect();
                    if (!parentRect || parentRect.width <= 0 || rect.width < 0) return null;
                    return (rect.width / parentRect.width) * 100;
                };

                const readPercent = (element) => {
                    const candidates = [
                        percentFromAria(element),
                        percentFromStyle(element),
                        percentFromGeometry(element),
                    ];
                    for (const value of candidates) {
                        if (Number.isFinite(value)) {
                            return Math.max(0, Math.min(100, value));
                        }
                    }
                    return null;
                };

                const findCard = (label) => {
                    const candidates = Array.from(document.body.querySelectorAll("div, section, article, [role='button']"))
                        .filter((element) => {
                            const text = normalize(element.innerText);
                            if (!text.includes(label)) return false;
                            return text.includes("кредитов осталось") || text.includes("лимиты тарифа");
                        })
                        .map((element) => {
                            const rect = element.getBoundingClientRect();
                            return { element, area: rect.width * rect.height };
                        })
                        .filter((item) => item.area > 1000)
                        .sort((a, b) => a.area - b.area);
                    return candidates[0] && candidates[0].element;
                };

                return labels.map((label) => {
                    const card = findCard(label);
                    if (!card) return null;
                    const cardRect = card.getBoundingClientRect();
                    const fills = Array.from(card.querySelectorAll("*"))
                        .filter((element) => {
                            const rect = element.getBoundingClientRect();
                            if (rect.width < 1 || rect.height < 2 || rect.height > 18) return false;
                            if (rect.top < cardRect.top + cardRect.height * 0.45) return false;
                            return isBlueFill(element);
                        })
                        .map((element) => ({
                            element,
                            percent: readPercent(element),
                            width: element.getBoundingClientRect().width,
                        }))
                        .filter((item) => Number.isFinite(item.percent))
                        .sort((a, b) => b.width - a.width);
                    if (!fills.length) return { title: label, percent: 0 };
                    return { title: label, percent: fills[0].percent };
                }).filter(Boolean);
            }"""
        )

    def _fallback_status(self, text: str) -> str:
        if self._requires_visible_login(text):
            return "нужен вход"
        return "нет данных"

    def _write_debug(self, snapshot: UsageSnapshot, note: str = "") -> None:
        try:
            self.settings.debug_log.parent.mkdir(parents=True, exist_ok=True)
            windows = "; ".join(
                f"{item.title} rem={item.credits_remaining} "
                f"used={item.limit_used}/{item.limit_total} progress={item.progress_percent}"
                for item in snapshot.windows
            )
            line = (
                f"{datetime.now().isoformat(timespec='seconds')} "
                f"account={snapshot.account!r} total={snapshot.total_used} "
                f"remaining={snapshot.remaining} windows={len(snapshot.windows)} "
                f"url={snapshot.source_url!r} {windows} "
                f"note={note!r} text_len={len(snapshot.raw_text)}\n"
            )
            append_bounded_log(self.settings.debug_log, line)
        except Exception:
            pass
