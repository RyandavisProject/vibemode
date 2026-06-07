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

## What The App Does Not Do

- It does not ask for a password.
- It does not ask for an API key.
- It does not upload usage data.
- It does not run a local web server.
- It does not include analytics.
- It does not write network traces by default.

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
