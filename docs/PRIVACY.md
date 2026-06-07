# Privacy

Vibemode Overlay is designed to be local-first.

## What The App Reads

The app reads text visible on:

```text
https://portal.neurogate.space/client/usage
```

It parses the values needed for the desktop overlay:

- account label;
- 5-hour remaining credits;
- 7-day remaining credits;
- reset times;
- refresh status.

The browser is hidden by default after login. If the saved browser session is
expired, the app opens a visible Chrome window so the user can log in directly
on the Vibemode/Neurogate website. After a successful read, that visible window
is closed and later updates continue in hidden mode.

## What The App Does Not Do

- It does not ask for a password.
- It does not ask for an API key.
- It does not upload usage data.
- It does not run a local web server.
- It does not include analytics.
- It does not write network traces by default.
- It does not keep a visible browser window open after successful login unless
  the user starts it with `--show-browser`.

## Local Files

The browser session is kept locally by Chrome/Playwright:

```text
%USERPROFILE%\.neurogate-usage-overlay\browser-profile
```

The last successful parsed snapshot is cached locally:

```text
%USERPROFILE%\.neurogate-usage-overlay\last-good-snapshot.json
```

Local logs are also written under:

```text
%USERPROFILE%\.neurogate-usage-overlay\
```

These files are for the user's own machine only and must not be published.

## Public Sharing Rule

When sharing screenshots, bug reports, or GitHub issues, remove account names,
request IDs, usage numbers, and any browser/session files.
