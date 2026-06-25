# Architecture

Vibemode is intentionally small and local-first. It has four main
runtime layers.

## Runtime Flow

```text
run-overlay.ps1
  -> python -m neurogate_usage_overlay
    -> NeurogateUsageReader
      -> Playwright persistent Chrome profile
      -> hidden browser by default
      -> visible browser only when login is required
      -> Vibemode cabinet
      -> Vibemode cabinet API
      -> visible body text fallback
    -> Vibemode API adapter / parse_usage_text()
      -> UsageSnapshot / UsageWindow
    -> UsageOverlay / MenuBarOverlay
      -> Windows Tkinter always-on-top widget
      -> macOS menu bar NSPopover
```

## Components

### CLI

`src/neurogate_usage_overlay/__main__.py`

- parses command-line options;
- builds browser settings;
- starts the browser reader;
- runs either the desktop overlay or one console read.

### Browser Reader

`src/neurogate_usage_overlay/browser_reader.py`

- owns the Playwright lifecycle;
- launches a persistent local Chrome profile;
- prefers hidden browser mode after login;
- opens a visible Chrome window only when the saved session requires login;
- hides the visible Chrome window after a successful read and continues from the
  same local browser session;
- exposes a runtime `keep_browser_open` toggle for the overlay menu;
- reads `https://api.vibemod.pro/client/profile` and
  `https://api.vibemod.pro/client/usage/limits` from the local Vibemode session;
- falls back to visible dashboard text if API reads fail;
- waits for the dynamic cabinet to expose both limit cards;
- reports login or missing-data states directly instead of showing old saved
  values;
- writes local debug logs only.

### Parser

`src/neurogate_usage_overlay/parser.py`

- parses visible page text as a fallback;
- supports the old `24 часа / 7 дней` layout;
- supports the current Vibemode `5 часов / 7 дней` credit-balance layout;
- avoids parsing the paid-reset card as a limit card.

### Overlay UI

`src/neurogate_usage_overlay/overlay.py`

- draws a compact borderless Tkinter widget on Windows;
- runs a native menu-bar popover on macOS;
- keeps refresh rate at one minute or slower;
- is draggable from any area;
- uses a custom borderless menu instead of the native Windows menu;
- lets the user temporarily keep or hide the visible account page;
- saves the overlay window position locally and restores it on the next launch.

## Data Boundaries

The project deliberately avoids a backend, cloud sync, telemetry, database, and
credential input form. Browser session files are stored by Chrome/Playwright on
the user's own machine.

## Current Tradeoffs

- Tkinter keeps installation simple, but styling is lower-level than a full UI
  framework.
- The Vibemode API adapter is preferred, while text parsing still depends on
  visible page labels when used as fallback.
- Playwright gives reliable browser automation, but it means the first install
  is heavier than a pure HTTP client.
- Hidden mode improves desktop privacy, but it still relies on local browser
  session files. Treat the profile folder like normal browser cookies.

## Next Engineering Improvements

- add configurable theme values in a small settings file;
- add screenshot-based UI smoke tests;
- package a signed Windows executable for non-technical users;
- add a parser fixture folder with real anonymized page text samples;
- add structured JSON output for `--once`.

## Public Release Improvements Included

This release moves the project closer to a public, maintainable standard by
adding:

- a clear local-first privacy boundary;
- a documented runtime architecture;
- parser tests for both old and current portal layouts;
- one-command local checks;
- desktop shortcut automation;
- AI-agent installation instructions;
- GitHub Actions CI;
- publishing checklist and security guidance.

