# Architecture

Vibemode Overlay is intentionally small and local-first. It has four main
runtime layers.

## Runtime Flow

```text
run-overlay.ps1
  -> python -m neurogate_usage_overlay
    -> NeurogateUsageReader
      -> Playwright persistent Chrome profile
      -> Vibemode/Neurogate usage page
      -> visible body text
    -> parse_usage_text()
      -> UsageSnapshot / UsageWindow
    -> UsageOverlay
      -> Tkinter always-on-top widget
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
- waits for the dynamic usage page to expose both limit cards;
- falls back to the last good snapshot if the site is temporarily logged out or
  still loading;
- writes local debug logs only.

### Parser

`src/neurogate_usage_overlay/parser.py`

- parses visible page text, not private APIs;
- supports the old `24 часа / 7 дней` layout;
- supports the current `5 часов / 7 дней` credit-balance layout;
- avoids parsing the paid-reset card as a limit card.

### Overlay UI

`src/neurogate_usage_overlay/overlay.py`

- draws a compact borderless Tkinter widget;
- keeps refresh rate at one minute or slower;
- is draggable from any area;
- uses a custom borderless menu instead of the native Windows menu.

## Data Boundaries

The project deliberately avoids a backend, cloud sync, telemetry, database, and
credential input form. Browser session files are stored by Chrome/Playwright on
the user's own machine.

## Current Tradeoffs

- Tkinter keeps installation simple, but styling is lower-level than a full UI
  framework.
- Text parsing is robust enough for the visible page but still depends on page
  labels.
- Playwright gives reliable browser automation, but it means the first install
  is heavier than a pure HTTP client.

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
