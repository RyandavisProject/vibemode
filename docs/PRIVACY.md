# Privacy

NeuroGate API is designed to be local-first.

## What The App Reads

The app reads text visible on:

```text
https://portal.neurogate.space/client/usage
```

It parses the values needed for the desktop overlay:

- account label;
- 5-hour remaining credits;
- 7-day remaining credits;
- current-window spending tooltip values;
- current-day spending tooltip values;
- reset times;
- refresh status.

The browser is hidden by default after login. If the saved browser session is
expired, the app opens a visible Chrome window so the user can log in directly
on the NeuroGate website. After a successful read, that visible window
is hidden and later updates continue from the same local browser session.

The user can temporarily keep the account page visible with the `Не закрывать ЛК`
menu toggle. Turning the toggle off hides the visible Chrome window and returns
the app to hidden mode. This does not change the privacy boundary: the app still
uses the local Chrome profile and does not collect credentials.

## What The App Does Not Do

- It does not ask for a password.
- It does not ask for an API key.
- It does not upload usage data.
- It does not run a local web server.
- It does not include analytics.
- It does not write network traces by default.
- It does not keep a visible browser window open after successful login unless
  the user starts it with `--show-browser` or enables `Не закрывать ЛК` in the
  overlay menu.

## Local Files

The browser session is kept locally by Chrome/Playwright:

```text
%USERPROFILE%\.neurogate-usage-overlay\browser-profile
```

Overlay UI state is stored locally:

```text
%USERPROFILE%\.neurogate-usage-overlay\overlay-state.json
```

The current-day spending baseline is stored locally:

```text
%USERPROFILE%\.neurogate-usage-overlay\usage-daily.json
```

This file keeps only the current day's 7-day remaining-credit baseline, the
baseline timestamp, and the last seen 7-day remaining value. It is rewritten
when the local date changes or the 7-day remaining balance grows. It is not an
append-only history file.

Local logs are also written under:

```text
%USERPROFILE%\.neurogate-usage-overlay\
```

These files are for the user's own machine only and must not be published.
The app does not store old usage-limit snapshots for fallback display.

## Public Sharing Rule

When sharing screenshots, bug reports, or GitHub issues, remove account names,
request IDs, usage numbers, and any browser/session files.

