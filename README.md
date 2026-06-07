# Vibemode Overlay

Compact Windows overlay for Vibemode/Neurogate API usage limits.

The app reads `https://portal.neurogate.space/client/usage` through a local
Chrome profile and shows a small always-on-top desktop widget with the current
credit limits. By default the browser runs hidden after login. A visible Chrome
window opens only when the user needs to log in again.

## Current UI

The current Vibemode limits page exposes fewer public values than the previous
Neurogate UI. The overlay intentionally shows only the data that is currently
available on the page:

- account name;
- 5-hour credit balance;
- 7-day credit balance;
- projected spendable credits until the current tariff time expires;
- reset time for each window;
- last refresh status;
- refresh interval.

Older fields such as token totals, cache totals, and `used / total` tariff
pairs are no longer shown because the new page does not expose them in the same
visible layout.

The value after `/` is a local projection. It estimates how many credits can
still be physically spent before the current tariff time expires, using the
current 5-hour balance, the current 7-day balance, their reset timers, and the
known tariff caps:

- 5-hour window: `120M` credits;
- 7-day window: `600M` credits.

The final projected number is the smaller of the 5-hour pacing capacity and the
7-day capacity.

## Privacy

The overlay is local-first.

- It does not ask for your Vibemode/Neurogate password.
- It does not collect API keys.
- It does not send usage data to this project, to a server, or to analytics.
- It reads only the text already visible in your own browser session.
- Browser cookies stay on your computer in a local Playwright/Chrome profile.
- After successful login, the visible Chrome window is closed and future reads
  continue in hidden browser mode.

Default local profile path:

```text
%USERPROFILE%\.neurogate-usage-overlay\browser-profile
```

Do not publish or share that folder.

## Requirements

- Windows 10/11
- Python 3.10+
- Google Chrome
- Internet access to the Vibemode/Neurogate portal

## Install

From GitHub:

```powershell
git clone https://github.com/RyandavisProject/vibemode-overlay.git
cd vibemode-overlay
powershell -ExecutionPolicy Bypass -File .\scripts\install.ps1
```

Or double-click:

```text
scripts\install.bat
```

The installer creates:

- local Python virtual environment in `.venv/`;
- editable Python package installation;
- desktop shortcut named `Vibemode Overlay`.

## Run

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\run-overlay.ps1
```

Or double-click the desktop shortcut:

```text
Vibemode Overlay
```

First run:

1. The overlay first tries to read the usage page in hidden mode.
2. If login is required, Chrome opens with a separate local browser profile.
3. Log in directly on the Vibemode/Neurogate website.
4. After the first successful read, the visible Chrome window closes.
5. Future updates continue in hidden mode.
6. The widget refreshes no more often than once per minute unless you choose
   manual refresh.

## Controls

- Drag the overlay by any visible area.
- Left-click the interval pill, for example `1м`, to cycle refresh intervals.
- Right-click the overlay to open the compact menu.
- Press `Esc` to close the overlay.
- Press `Ctrl+R` to refresh, respecting the 1-minute minimum refresh guard.

## Useful Commands

Install:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\install.ps1
```

Create desktop shortcut again:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\create-desktop-shortcut.ps1
```

Run overlay:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\run-overlay.ps1
```

Keep browser visible for debugging:

```powershell
.\.venv\Scripts\python.exe -m neurogate_usage_overlay --show-browser
```

Run one console check:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\run-once.ps1
```

Run project checks:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\check.ps1
```

## AI Install Prompt

For Codex, Claude Code, or another local coding agent, the short command is:

```text
Install Vibemode Overlay from https://github.com/RyandavisProject/vibemode-overlay
```

If the agent asks for more detail, use:

```text
Install Vibemode Overlay from https://github.com/RyandavisProject/vibemode-overlay.
Read docs/AI_INSTALL_PROMPT.md, follow it exactly, install dependencies, create
a desktop shortcut, launch the overlay, and give me a short installation report
in plain language.
```

The detailed prompt is stored in:

```text
docs/AI_INSTALL_PROMPT.md
```

## Project Structure

```text
vibemode-overlay/
  src/neurogate_usage_overlay/
    __main__.py          CLI entrypoint
    browser_reader.py    Playwright browser/session reader
    models.py            Typed usage data model
    overlay.py           Tkinter desktop overlay UI
    parser.py            Visible page text parser
  scripts/
    install.ps1
    run-overlay.ps1
    run-once.ps1
    create-desktop-shortcut.ps1
    check.ps1
  docs/
    AI_INSTALL_PROMPT.md
    ARCHITECTURE.md
    PRIVACY.md
    PUBLISHING.md
  tests/
    test_parser.py
```

## Development

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\check.ps1
```

The test suite currently covers both known page formats:

- old Neurogate page with `24 часа / 7 дней` and tariff limit pairs;
- current Vibemode page with `5 часов / 7 дней` and remaining credits.

## Limitations

- The parser reads visible page text. If Vibemode changes labels or page layout,
  the parser may need a small update.
- The app is Windows-focused because it uses Tkinter desktop behavior and
  Windows shortcut scripts.
- The app does not bypass login or session expiry. If the site logs you out, the
  overlay opens a visible Chrome window so you can log in again. After a
  successful read, it returns to hidden mode.

## License

MIT. See `LICENSE`.
