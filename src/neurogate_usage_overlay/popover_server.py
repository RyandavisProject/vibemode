"""Tiny local HTTP server that serves the popover HTML for the macOS menu bar UI.

The server binds on 127.0.0.1 on a random free port and is started in a daemon
thread so it doesn't block the main run loop.  Call `get_url()` to get the URL
that WKWebView should load.
"""
from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Any

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
    font-family: -apple-system, BlinkMacSystemFont, "SF Pro Text", sans-serif;
    font-size: 13px;
    background: transparent;
    color: #1c1c1e;
    padding: 12px 14px 14px;
    width: 280px;
    -webkit-user-select: none;
  }

  /* ── header ── */
  .header {
    display: flex;
    justify-content: space-between;
    align-items: baseline;
    margin-bottom: 2px;
  }
  .account {
    font-weight: 600;
    font-size: 14px;
    color: #1c1c1e;
  }
  .plan {
    font-size: 11px;
    color: #8e8e93;
    font-weight: 500;
  }
  .updated {
    font-size: 11px;
    color: #8e8e93;
    margin-bottom: 10px;
  }

  /* ── window cards ── */
  .windows { display: flex; flex-direction: column; gap: 8px; margin-bottom: 10px; }

  .card {
    background: rgba(255,255,255,0.55);
    border-radius: 10px;
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
  .card-pct   { font-weight: 600; font-size: 13px; }

  .bar-track {
    height: 6px;
    background: rgba(0,0,0,0.08);
    border-radius: 3px;
    overflow: hidden;
    margin-bottom: 4px;
  }
  .bar-fill {
    height: 100%;
    border-radius: 3px;
    transition: width 0.4s ease;
  }
  .bar-green  { background: #34c759; }
  .bar-yellow { background: #ff9f0a; }
  .bar-red    { background: #ff3b30; }

  .card-sub {
    font-size: 11px;
    color: #8e8e93;
  }

  /* ── status (no data) ── */
  .status-row {
    text-align: center;
    color: #8e8e93;
    padding: 8px 0 4px;
    font-size: 13px;
  }

  /* ── divider ── */
  .divider {
    height: 1px;
    background: rgba(0,0,0,0.08);
    margin: 8px 0;
  }

  /* ── actions ── */
  .actions { display: flex; flex-direction: column; gap: 1px; }

  .action-btn {
    display: flex;
    align-items: center;
    gap: 8px;
    padding: 6px 4px;
    border-radius: 7px;
    cursor: pointer;
    color: #1c1c1e;
    text-decoration: none;
    font-size: 13px;
    transition: background 0.12s;
  }
  .action-btn:hover { background: rgba(0,0,0,0.06); }
  .action-btn .icon { width: 18px; text-align: center; font-size: 14px; opacity: 0.75; }
  .action-btn.danger { color: #ff3b30; }

  /* ── refresh spinner ── */
  @keyframes spin { to { transform: rotate(360deg); } }
  .spinning { animation: spin 0.8s linear infinite; display: inline-block; }
</style>
</head>
<body>
<div id="root"></div>
<script>
const data = %DATA%;

function shortNum(n) {
  if (n == null) return "—";
  if (n >= 1e9) return (n / 1e9).toFixed(1).replace(/\\.0$/, "") + "B";
  if (n >= 1e6) return (n / 1e6).toFixed(1).replace(/\\.0$/, "") + "M";
  if (n >= 1e3) return (n / 1e3).toFixed(0) + "K";
  return String(n);
}

function barClass(pct) {
  if (pct == null) return "bar-green";
  if (pct >= 90) return "bar-red";
  if (pct >= 60) return "bar-yellow";
  return "bar-green";
}

function render() {
  const snap = data.snapshot;
  let html = "";

  if (snap && snap.has_data) {
    // header
    html += `<div class="header">
      <span class="account">${snap.account || "NeuroGate"}</span>
      ${snap.plan_status ? `<span class="plan">${snap.plan_status}</span>` : ""}
    </div>`;
    if (snap.updated_at) {
      html += `<div class="updated">Обновлено ${snap.updated_at}</div>`;
    }

    // window cards
    html += `<div class="windows">`;
    for (const w of snap.windows) {
      const pct = w.progress_percent != null ? w.progress_percent : (w.limit_percent != null ? w.limit_percent : null);
      const barW = pct != null ? Math.min(100, pct).toFixed(1) : 0;
      const cls  = barClass(pct);
      const val  = w.credits_remaining != null ? shortNum(w.credits_remaining) + " ост." : (w.limit_used != null ? shortNum(w.limit_used) + " / " + shortNum(w.limit_total) : "—");
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
  } else {
    html += `<div class="status-row">${snap && snap.status_note ? snap.status_note : "Загрузка…"}</div>`;
  }

  html += `<div class="divider"></div>`;

  // actions
  html += `<div class="actions">`;
  html += action("↻", "Обновить", "window.__ng_action('refresh')");

  // interval submenu placeholder — just show current
  html += action("⏱", "Интервал: " + data.interval_label, "window.__ng_action('open_interval')");

  if (data.update_available) {
    html += `<div class="divider"></div>`;
    html += action("⬆", "Обновить до " + data.update_label, "window.__ng_action('update')");
  }

  html += `<div class="divider"></div>`;
  html += action("✕", "Закрыть", "window.__ng_action('quit')", true);
  html += `</div>`;

  document.getElementById("root").innerHTML = html;
}

function action(icon, label, onclick, danger=false, hidden=false) {
  if (hidden) return "";
  return `<a class="action-btn${danger ? " danger" : ""}" onclick="${onclick}">
    <span class="icon">${icon}</span><span>${label}</span>
  </a>`;
}

render();

// Poll for updates every 2s so menu stays fresh
setInterval(() => {
  fetch("/data").then(r => r.json()).then(d => {
    Object.assign(data, d);
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

    def log_message(self, *_args: object) -> None:
        pass

    def do_GET(self) -> None:  # noqa: N802
        ps = self.server.popover
        if self.path == "/" or self.path == "/index.html":
            body = ps.render_html().encode("utf-8")
            self._respond(200, "text/html; charset=utf-8", body)
        elif self.path == "/data":
            body = ps.render_json().encode("utf-8")
            self._respond(200, "application/json", body)
        elif self.path.startswith("/action/"):
            action = self.path[len("/action/"):]
            ps.handle_action(action)
            self._respond(200, "text/plain", b"ok")
        else:
            self._respond(404, "text/plain", b"not found")

    def do_POST(self) -> None:  # noqa: N802
        ps = self.server.popover
        if self.path.startswith("/action/"):
            action = self.path[len("/action/"):]
            ps.handle_action(action)
            self._respond(200, "text/plain", b"ok")
        elif self.path.startswith("/resize/"):
            try:
                height = int(self.path[len("/resize/"):])
                ps.handle_resize(height)
            except ValueError:
                pass
            self._respond(200, "text/plain", b"ok")
        else:
            self._respond(404, "text/plain", b"not found")

    def _respond(self, code: int, ctype: str, body: bytes) -> None:
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()
        self.wfile.write(body)


class PopoverServer:
    def __init__(self) -> None:
        self._snapshot: UsageSnapshot | None = None
        self._extra: dict[str, Any] = {}
        self._action_callbacks: dict[str, Any] = {}
        self._server = _PopoverHTTPServer(("127.0.0.1", 0), _Handler)
        self._server.popover = self
        self._port = self._server.server_address[1]
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)
        self._thread.start()

    @property
    def port(self) -> int:
        return self._port

    def get_url(self) -> str:
        return f"http://127.0.0.1:{self._port}/"

    def update(self, snapshot: UsageSnapshot | None, extra: dict[str, Any]) -> None:
        self._snapshot = snapshot
        self._extra = extra

    def on_action(self, name: str, callback: Any) -> None:
        self._action_callbacks[name] = callback

    def on_resize(self, callback: "Callable[[int], None]") -> None:
        self._resize_callback = callback

    def handle_action(self, name: str) -> None:
        cb = self._action_callbacks.get(name)
        if cb:
            threading.Thread(target=cb, daemon=True).start()

    def handle_resize(self, height: int) -> None:
        cb = getattr(self, "_resize_callback", None)
        if cb:
            threading.Thread(target=lambda: cb(height), daemon=True).start()

    def render_json(self) -> str:
        return json.dumps(self._build_data())

    def _build_data(self) -> dict[str, Any]:
        snap = self._snapshot
        snap_dict: dict[str, Any] | None = None
        if snap:
            windows = []
            for w in snap.windows:
                windows.append({
                    "title": w.title,
                    "credits_remaining": w.credits_remaining,
                    "limit_used": w.limit_used,
                    "limit_total": w.limit_total,
                    "progress_percent": w.progress_percent,
                    "limit_percent": w.limit_percent,
                    "reset_text": w.reset_text,
                })
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
            **self._extra,
        }

    def render_html(self) -> str:
        return _TEMPLATE.replace("%DATA%", self.render_json())

    def stop(self) -> None:
        self._server.shutdown()


def _relative_time(dt: Any) -> str:
    from datetime import datetime, timezone
    try:
        now = datetime.now(timezone.utc)
        diff = now - dt.astimezone(timezone.utc)
        s = int(diff.total_seconds())
        if s < 5:
            return "только что"
        if s < 60:
            return f"{s} сек. назад"
        m = s // 60
        if m < 60:
            return f"{m} мин. назад"
        h = m // 60
        if h < 24:
            return f"{h} ч. назад"
        return f"{h // 24} д. назад"
    except Exception:
        return ""
