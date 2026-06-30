"""Tiny local HTTP server that serves the popover HTML for the macOS menu bar UI.

The server binds on 127.0.0.1 on a random free port and is started in a daemon
thread so it does not block the main run loop. Call `get_url()` to get the URL
that WKWebView should load.
"""
from __future__ import annotations

import json
import secrets
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Any, Callable
from urllib.parse import parse_qs, unquote, urlparse

from .models import UsageSnapshot


_TEMPLATE = """\
<!DOCTYPE html>
<html lang="ru">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<style>
  * { margin: 0; padding: 0; box-sizing: border-box; }

  body {
    --bg: rgba(246,247,250,0.96);
    --text: #1c1c1e;
    --muted: #73737a;
    --subtle: #8e8e93;
    --card: rgba(255,255,255,0.72);
    --card-strong: rgba(255,255,255,0.9);
    --border: rgba(0,0,0,0.08);
    --hover: rgba(0,0,0,0.06);
    --field: rgba(255,255,255,0.9);
    --field-border: rgba(0,0,0,0.14);
    --accent: #0a84ff;
    --danger: #ff3b30;
    font-family: -apple-system, BlinkMacSystemFont, "SF Pro Text", sans-serif;
    font-size: 13px;
    background: var(--bg);
    color: var(--text);
    padding: 12px 14px 14px;
    width: 280px;
    -webkit-user-select: none;
  }
  body.theme-dark {
    --bg: rgba(24,24,27,0.97);
    --text: #f5f5f7;
    --muted: #b7b7bd;
    --subtle: #8d8d95;
    --card: rgba(44,44,48,0.82);
    --card-strong: rgba(55,55,60,0.92);
    --border: rgba(255,255,255,0.12);
    --hover: rgba(255,255,255,0.09);
    --field: rgba(18,18,20,0.9);
    --field-border: rgba(255,255,255,0.18);
    --accent: #64d2ff;
    --danger: #ff6961;
  }

  .header {
    display: flex;
    justify-content: space-between;
    align-items: baseline;
    gap: 10px;
    margin-bottom: 2px;
  }
  .account {
    font-weight: 600;
    font-size: 14px;
    color: var(--text);
    min-width: 0;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }
  .plan {
    font-size: 11px;
    color: var(--subtle);
    font-weight: 500;
    white-space: nowrap;
  }
  .updated {
    font-size: 11px;
    color: var(--subtle);
    margin-bottom: 10px;
  }

  .windows { display: flex; flex-direction: column; gap: 8px; margin-bottom: 10px; }

  .card {
    background: var(--card);
    border: 1px solid var(--border);
    border-radius: 8px;
    padding: 9px 11px 8px;
    backdrop-filter: blur(8px);
    -webkit-backdrop-filter: blur(8px);
  }

  .card-row {
    display: flex;
    justify-content: space-between;
    align-items: center;
    margin-bottom: 5px;
  }
  .card-title { font-weight: 600; font-size: 13px; }
  .card-pct { font-weight: 600; font-size: 13px; }

  .bar-track {
    height: 6px;
    background: var(--border);
    border-radius: 3px;
    overflow: hidden;
    margin-bottom: 4px;
  }
  .bar-fill {
    height: 100%;
    border-radius: 3px;
    transition: width 0.4s ease;
  }
  .bar-green { background: #34c759; }
  .bar-yellow { background: #ffcc00; }
  .bar-red { background: #ff3b30; }

  .card-sub {
    font-size: 11px;
    color: var(--subtle);
  }

  .status-row {
    text-align: center;
    color: var(--subtle);
    padding: 8px 0 4px;
    font-size: 13px;
  }

  .divider {
    height: 1px;
    background: var(--border);
    margin: 8px 0;
  }

  .actions { display: flex; flex-direction: column; gap: 1px; }

  .action-btn {
    display: flex;
    align-items: center;
    gap: 8px;
    width: 100%;
    padding: 6px 4px;
    border-radius: 7px;
    cursor: pointer;
    color: var(--text);
    background: transparent;
    border: 0;
    text-decoration: none;
    font-size: 13px;
    font-family: inherit;
    text-align: left;
    transition: background 0.12s;
  }
  .action-btn:hover { background: var(--hover); }
  .action-btn .icon { width: 18px; text-align: center; font-size: 14px; opacity: 0.75; }
  .action-btn .label { flex: 1; min-width: 0; }
  .action-btn .chevron { color: var(--subtle); font-size: 12px; }
  .action-btn.danger { color: var(--danger); }
  .action-btn.muted { color: var(--muted); }
  .action-btn.disabled { cursor: default; }
  .action-btn.disabled:hover { background: transparent; }
  .choice-list {
    display: grid;
    grid-template-columns: repeat(3, 1fr);
    gap: 5px;
    padding: 4px 0 7px 26px;
  }
  .choice-btn {
    height: 25px;
    border-radius: 7px;
    border: 1px solid var(--border);
    background: var(--card);
    color: var(--text);
    font: inherit;
    cursor: pointer;
  }
  .choice-btn:hover { background: var(--hover); }
  .choice-btn.active {
    color: #fff;
    border-color: var(--accent);
    background: var(--accent);
  }
  .daily-card {
    margin: 2px 0 6px;
  }
  .daily-form {
    background: var(--card);
    border: 1px solid var(--border);
    border-radius: 8px;
    padding: 8px;
    margin: 2px 0 6px;
  }
  .daily-form-row {
    display: flex;
    gap: 6px;
    align-items: center;
  }
  .daily-input {
    min-width: 0;
    flex: 1;
    height: 28px;
    border-radius: 7px;
    border: 1px solid var(--field-border);
    background: var(--field);
    color: var(--text);
    font: 600 13px -apple-system, BlinkMacSystemFont, "SF Pro Text", sans-serif;
    padding: 0 8px;
    outline: none;
  }
  .daily-input:focus { border-color: var(--accent); }
  .mini-btn {
    height: 28px;
    border-radius: 7px;
    border: 1px solid var(--border);
    background: var(--card-strong);
    color: var(--text);
    font: inherit;
    padding: 0 9px;
    cursor: pointer;
  }
  .mini-btn.primary {
    background: var(--accent);
    border-color: var(--accent);
    color: #fff;
  }
  .form-error {
    min-height: 14px;
    color: var(--danger);
    font-size: 11px;
    padding-top: 4px;
  }
</style>
</head>
<body>
<div id="root"></div>
<script>
let data = %DATA%;
window.__NG_ACTION_TOKEN__ = data.action_token || "";
let intervalMenuOpen = false;
let dailyEditorOpen = false;
let dailyDraft = null;

function shortNum(n) {
  if (n == null) return "—";
  if (n >= 1e9) return (n / 1e9).toFixed(1).replace(/\\.0$/, "") + "B";
  if (n >= 1e6) return (n / 1e6).toFixed(1).replace(/\\.0$/, "") + "M";
  if (n >= 1e3) return (n / 1e3).toFixed(0) + "K";
  return String(n);
}

function barClass(pct) {
  if (pct == null) return "bar-green";
  if (pct > 75) return "bar-red";
  if (pct > 50) return "bar-yellow";
  return "bar-green";
}

function render() {
  const snap = data.snapshot;
  document.body.className = data.theme === "dark" ? "theme-dark" : "theme-light";
  let html = "";

  if (snap && snap.has_data) {
    html += `<div class="header">
      <span class="account">${snap.account || "Vibemode"}</span>
      ${snap.plan_status ? `<span class="plan">${snap.plan_status}</span>` : ""}
    </div>`;
    if (snap.updated_at) {
      html += `<div class="updated">Обновлено ${snap.updated_at}</div>`;
    }

    html += `<div class="windows">`;
    for (const w of snap.windows) {
      const pct = w.progress_percent != null ? w.progress_percent : (w.limit_percent != null ? w.limit_percent : null);
      const barW = pct != null ? Math.min(100, pct).toFixed(1) : 0;
      const cls = barClass(pct);
      const val = limitValue(w);
      const pctLabel = pct != null ? Math.round(pct) + "%" : "";
      html += `<div class="card">
        <div class="card-row">
          <span class="card-title">${w.title}</span>
          <span class="card-pct">${pctLabel}</span>
        </div>
        <div class="bar-track"><div class="bar-fill ${cls}" style="width:${barW}%"></div></div>
        <div class="card-sub">${val}${w.reset_text ? " &nbsp;·&nbsp; " + w.reset_text : ""}</div>
      </div>`;
    }
    html += `</div>`;
    html += dailyLimitBlock();
  } else {
    html += `<div class="status-row">${snap && snap.status_note ? snap.status_note : "Загрузка..."}</div>`;
  }

  html += `<div class="divider"></div>`;
  html += `<div class="actions">`;
  html += action("↻", "Обновить", "window.__ng_action('refresh')");
  html += action("⏱", "Интервал обновления: " + data.interval_label, "toggleIntervalMenu(event)", false, "", "⌄", "toggleIntervalMenu(event)");
  if (intervalMenuOpen) {
    html += `<div class="choice-list">`;
    for (const choice of data.interval_choices || []) {
      const active = choice.minutes === data.interval_minutes ? " active" : "";
      html += `<button class="choice-btn${active}" type="button" onclick="setIntervalChoice(${choice.minutes})">${choice.label}</button>`;
    }
    html += `</div>`;
  }

  if (!data.daily_limit_enabled) {
    html += action("+", "Задать лимит на день", "openDailyEditor()");
  } else {
    html += action("✎", "Изменить лимит на день", "openDailyEditor()");
    html += action("−", "Скрыть лимит на день", "window.__ng_action('hide_daily')");
  }

  if (data.has_keep_toggle) {
    html += action(data.keep_browser_open ? "◉" : "○", data.keep_browser_open ? "Закрывать ЛК" : "Показывать ЛК", "toggleKeepBrowser()");
  }

  html += action(data.theme === "dark" ? "☀" : "☾", data.theme === "dark" ? "Светлая тема" : "Тёмная тема", "toggleTheme()");

  if (data.has_account_reset) {
    html += `<div class="divider"></div>`;
    if (data.version_update_available) {
      html += action("⬆", data.version_label, "window.__ng_action('update')");
    } else {
      html += action("i", data.version_label, "", false, "muted disabled");
    }
    html += action("↺", "Сменить аккаунт", "window.__ng_action('reset_account')", false, "muted");
  }

  html += `<div class="divider"></div>`;
  html += action("↻", "Перезапустить", "window.__ng_action('restart')");
  html += action("⏻", "Выход", "window.__ng_action('quit')", true);
  html += `</div>`;

  document.getElementById("root").innerHTML = html;
}

function dailyLimitBlock() {
  if (dailyEditorOpen) {
    return dailyForm();
  }
  if (data.daily_limit_enabled && data.daily_limit) {
    const d = data.daily_limit;
    const pct = d.percent != null ? Math.min(100, d.percent).toFixed(1) : 0;
    const pctLabel = d.percent != null ? Math.round(d.percent) + "%" : "";
    return `<div class="card daily-card" ondblclick="openDailyEditor()">
      <div class="card-row">
        <span class="card-title">Лимит/день</span>
        <span class="card-pct">${pctLabel}</span>
      </div>
      <div class="bar-track"><div class="bar-fill ${barClass(d.percent)}" style="width:${pct}%"></div></div>
      <div class="card-sub">${d.spent_label} / ${d.limit_label}</div>
    </div>`;
  }
  return "";
}

function limitValue(w) {
  if (w.credits_remaining != null && w.limit_total != null) {
    return shortNum(w.credits_remaining) + "/" + shortNum(w.limit_total);
  }
  if (w.credits_remaining != null) {
    return shortNum(w.credits_remaining) + " ост.";
  }
  if (w.limit_used != null && w.limit_total != null) {
    return shortNum(w.limit_used) + "/" + shortNum(w.limit_total);
  }
  return "—";
}

function action(icon, label, onclick, danger=false, extraClass="", trailing="", contextmenu="") {
  const classes = ["action-btn"];
  if (danger) classes.push("danger");
  if (extraClass) classes.push(extraClass);
  const clickAttr = onclick ? ` onclick="${onclick}"` : "";
  const contextAttr = contextmenu ? ` oncontextmenu="${contextmenu}"` : "";
  const trailingHtml = trailing ? `<span class="chevron">${trailing}</span>` : "";
  return `<button type="button" class="${classes.join(" ")}"${clickAttr}${contextAttr}>
    <span class="icon">${icon}</span><span class="label">${label}</span>${trailingHtml}
  </button>`;
}

function toggleIntervalMenu(event) {
  if (event) event.preventDefault();
  intervalMenuOpen = !intervalMenuOpen;
  dailyEditorOpen = false;
  render();
}

function setIntervalChoice(minutes) {
  intervalMenuOpen = false;
  const choice = (data.interval_choices || []).find(item => item.minutes === minutes);
  data.interval_minutes = minutes;
  if (choice) data.interval_label = choice.menu_label || choice.label;
  render();
  window.__ng_action('set_interval', {minutes});
}

function toggleTheme() {
  data.theme = data.theme === "dark" ? "light" : "dark";
  render();
  window.__ng_action('toggle_theme');
}

function toggleKeepBrowser() {
  data.keep_browser_open = !data.keep_browser_open;
  render();
  window.__ng_action('toggle_keep');
}

function openDailyEditor() {
  intervalMenuOpen = false;
  dailyEditorOpen = true;
  dailyDraft = data.daily_limit && data.daily_limit.limit_label ? data.daily_limit.limit_label : (data.daily_limit_default || "");
  render();
  setTimeout(() => {
    const input = document.getElementById("dailyLimitInput");
    if (input) { input.focus(); input.select(); }
  }, 0);
}

function dailyForm() {
  const value = dailyDraft != null ? dailyDraft : (data.daily_limit_default || "");
  return `<div class="daily-form">
    <div class="daily-form-row">
      <input id="dailyLimitInput" class="daily-input" value="${escapeAttr(value)}" oninput="dailyDraft=this.value" onkeydown="dailyKey(event)" placeholder="56M">
      <button type="button" class="mini-btn primary" onclick="saveDailyLimit()">OK</button>
      <button type="button" class="mini-btn" onclick="dailyEditorOpen=false;render()">Отмена</button>
    </div>
    <div id="dailyError" class="form-error"></div>
  </div>`;
}

function dailyKey(event) {
  if (event.key === "Enter") saveDailyLimit();
  if (event.key === "Escape") { dailyEditorOpen = false; render(); }
}

function saveDailyLimit() {
  const input = document.getElementById("dailyLimitInput");
  const value = input ? input.value.trim() : dailyDraft.trim();
  if (!parseCreditInput(value)) {
    const error = document.getElementById("dailyError");
    if (error) error.textContent = "Введите число: 56M или 56000000";
    return;
  }
  dailyEditorOpen = false;
  window.__ng_action('set_daily', {value});
}

function parseCreditInput(value) {
  const cleaned = String(value || "").trim().replace(",", ".").replace(/\\s+/g, "");
  const match = cleaned.match(/^(\\d+(?:\\.\\d+)?)([kKmMbBкКмМ]?|млн|млрд|тыс|bn)$/);
  if (!match) return null;
  return Number(match[1]) > 0 ? match : null;
}

function escapeAttr(value) {
  return String(value || "").replace(/&/g, "&amp;").replace(/"/g, "&quot;").replace(/</g, "&lt;");
}

render();

setInterval(() => {
  fetch("/data?token=" + encodeURIComponent(window.__NG_ACTION_TOKEN__ || "")).then(r => r.json()).then(d => {
    Object.assign(data, d);
    window.__NG_ACTION_TOKEN__ = data.action_token || window.__NG_ACTION_TOKEN__ || "";
    render();
  }).catch(() => {});
}, 2000);
</script>
</body>
</html>
"""


class _PopoverHTTPServer(HTTPServer):
    """HTTPServer subclass that carries a reference to PopoverServer."""

    popover: "PopoverServer"


class _Handler(BaseHTTPRequestHandler):
    server: "_PopoverHTTPServer"
    MAX_POST_BODY_BYTES = 16 * 1024

    def log_message(self, *_args: object) -> None:
        pass

    def do_GET(self) -> None:  # noqa: N802
        ps = self.server.popover
        parsed = urlparse(self.path)
        path = parsed.path
        if path == "/" or path == "/index.html":
            if not self._require_token(ps, parsed.query):
                return
            body = ps.render_html().encode("utf-8")
            self._respond(200, "text/html; charset=utf-8", body)
        elif path == "/data":
            if not self._require_token(ps, parsed.query):
                return
            body = ps.render_json().encode("utf-8")
            self._respond(200, "application/json", body)
        elif self._is_private_path(path):
            if not self._require_token(ps, parsed.query):
                return
            self._respond(405, "text/plain", b"method not allowed")
        else:
            self._respond(404, "text/plain", b"not found")

    def do_POST(self) -> None:  # noqa: N802
        ps = self.server.popover
        parsed = urlparse(self.path)
        path = parsed.path
        if path.startswith("/action/"):
            if not self._require_token(ps, parsed.query):
                return
            if not self._require_acceptable_body_size():
                return
            action = unquote(path[len("/action/") :])
            ps.handle_action(action, self._read_json_body())
            self._respond(200, "text/plain", b"ok")
        elif path.startswith("/resize/"):
            if not self._require_token(ps, parsed.query):
                return
            if not self._require_acceptable_body_size():
                return
            try:
                height = int(path[len("/resize/") :])
                ps.handle_resize(height)
            except ValueError:
                pass
            self._respond(200, "text/plain", b"ok")
        elif self._is_private_path(path):
            if not self._require_token(ps, parsed.query):
                return
            self._respond(405, "text/plain", b"method not allowed")
        else:
            self._respond(404, "text/plain", b"not found")

    def _is_private_path(self, path: str) -> bool:
        return path in {"/", "/index.html", "/data"} or path.startswith(("/action/", "/resize/"))

    def _require_token(self, ps: "PopoverServer", query: str) -> bool:
        if ps.authorize(query):
            return True
        self._respond(403, "text/plain", b"forbidden")
        return False

    def _content_length(self) -> int:
        try:
            return int(self.headers.get("Content-Length") or "0")
        except ValueError:
            return 0

    def _require_acceptable_body_size(self) -> bool:
        if self._content_length() <= self.MAX_POST_BODY_BYTES:
            return True
        self._respond(413, "text/plain", b"payload too large")
        return False

    def _respond(self, code: int, ctype: str, body: bytes) -> None:
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()
        self.wfile.write(body)

    def _read_json_body(self) -> dict[str, Any]:
        length = self._content_length()
        if length <= 0:
            return {}
        try:
            payload = json.loads(self.rfile.read(length).decode("utf-8"))
            return payload if isinstance(payload, dict) else {}
        except Exception:
            return {}


class PopoverServer:
    def __init__(self) -> None:
        self._snapshot: UsageSnapshot | None = None
        self._extra: dict[str, Any] = {}
        self._action_callbacks: dict[str, Callable[[dict[str, Any]], None]] = {}
        self._action_token = secrets.token_urlsafe(24)
        self._resize_callback: Callable[[int], None] | None = None
        self._server = _PopoverHTTPServer(("127.0.0.1", 0), _Handler)
        self._server.popover = self
        self._port = self._server.server_address[1]
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)
        self._thread.start()

    @property
    def port(self) -> int:
        return self._port

    def get_url(self) -> str:
        return f"http://127.0.0.1:{self._port}/?token={self._action_token}"

    def authorize(self, query: str) -> bool:
        token = parse_qs(query).get("token", [""])[0]
        return secrets.compare_digest(token, self._action_token)

    def update(self, snapshot: UsageSnapshot | None, extra: dict[str, Any]) -> None:
        self._snapshot = snapshot
        self._extra = extra

    def on_action(self, name: str, callback: Callable[[dict[str, Any]], None]) -> None:
        self._action_callbacks[name] = callback

    def on_resize(self, callback: Callable[[int], None]) -> None:
        self._resize_callback = callback

    def handle_action(self, name: str, payload: dict[str, Any] | None = None) -> None:
        cb = self._action_callbacks.get(name)
        if cb:
            threading.Thread(target=lambda: cb(payload or {}), daemon=True).start()

    def handle_resize(self, height: int) -> None:
        cb = self._resize_callback
        if cb:
            threading.Thread(target=lambda: cb(height), daemon=True).start()

    def render_json(self) -> str:
        return json.dumps(self._build_data(), ensure_ascii=False)

    def _build_data(self) -> dict[str, Any]:
        snap = self._snapshot
        snap_dict: dict[str, Any] | None = None
        if snap:
            windows = []
            for w in snap.windows:
                windows.append(
                    {
                        "title": w.title,
                        "credits_remaining": w.credits_remaining,
                        "limit_used": w.limit_used,
                        "limit_total": w.limit_total,
                        "progress_percent": w.progress_percent,
                        "limit_percent": w.limit_percent,
                        "reset_text": w.reset_text,
                    }
                )
            snap_dict = {
                "has_data": snap.has_data,
                "account": snap.account,
                "plan_status": snap.plan_status,
                "status_note": snap.status_note,
                "updated_at": _relative_time(snap.updated_at),
                "windows": windows,
            }
        return {
            "snapshot": snap_dict,
            "action_token": self._action_token,
            **self._extra,
        }

    def render_html(self) -> str:
        return _TEMPLATE.replace("%DATA%", self.render_json())

    def stop(self) -> None:
        self._server.shutdown()
        self._server.server_close()
        self._thread.join(timeout=1)


def _relative_time(dt: Any) -> str:
    from datetime import datetime, timezone

    try:
        now = datetime.now(timezone.utc)
        diff = now - dt.astimezone(timezone.utc)
        seconds = int(diff.total_seconds())
        if seconds < 5:
            return "только что"
        if seconds < 60:
            return f"{seconds} сек. назад"
        minutes = seconds // 60
        if minutes < 60:
            return f"{minutes} мин. назад"
        hours = minutes // 60
        if hours < 24:
            return f"{hours} ч. назад"
        return f"{hours // 24} д. назад"
    except Exception:
        return ""
