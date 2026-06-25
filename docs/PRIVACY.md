# Privacy

Vibemode is designed to be local-first.

## What The App Reads

The app opens the local account page:

```text
https://portal.vibemod.pro/client
```

For the current Vibemode cabinet, the app reads the values through the cabinet
API from the same local browser session:

```text
https://api.vibemod.pro/client/profile
https://api.vibemod.pro/client/usage/limits
```

It parses only the values needed for the desktop overlay:

- account label;
- 5-hour remaining credits;
- 7-day remaining credits;
- current-window spending tooltip values;
- current-day spending tooltip values;
- refresh status.

The browser is hidden by default after login. If the saved browser session is
expired, the app opens a visible Chrome window so the user can log in directly
on the Vibemode website. After a successful read, that visible window
is hidden and later updates continue from the same local browser session.

The user can temporarily keep the account page visible with the `Не закрывать ЛК`
menu toggle. Turning the toggle off hides the visible Chrome window and returns
the app to hidden mode. This does not change the privacy boundary: the app still
uses the local Chrome profile and does not collect credentials.

The user can switch Vibemode accounts from the overlay menu with
`Сменить аккаунт`. This closes the current browser context, removes only the
overlay's local browser profile, and opens a fresh Vibemode login window.
Automatic login clicks are blocked during this account-switch flow until the
user successfully logs in to the new account. It does not touch the user's
normal Chrome profile.

## What The App Does Not Do

- It does not ask for a password.
- It does not ask for an API key.
- It does not upload usage data.
- It does not expose a public web server. On macOS it uses a tiny
  `127.0.0.1`-only server to render the menu-bar popover locally.
- It does not include analytics.
- It does not write network traces by default.
- It does not keep a visible browser window open after successful login unless
  the user starts it with `--show-browser` or enables `Не закрывать ЛК` in the
  overlay menu.
- It may automatically press the login button only for normal session recovery,
  when the Vibemode login form is already filled by the local browser and stays
  unchanged for several seconds. It does not store the password; it only checks
  whether the local form is filled. During `Сменить аккаунт`, automatic login is
  disabled and the user confirms login manually on the Vibemode website.

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

The app also creates a small local lock file:

```text
%USERPROFILE%\.neurogate-usage-overlay\overlay.lock
```

This file is only used to prevent two overlay instances from running at the
same time. It does not contain credentials or usage data.

The release ZIP and the GitHub repository do not include the local
`browser-profile` folder. Each user gets a separate local browser session on
their own computer.

## Public Sharing Rule

When sharing screenshots, bug reports, or GitHub issues, remove account names,
request IDs, usage numbers, and any browser/session files.
