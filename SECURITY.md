# Security

This project must not collect, request, store or transmit VibeMode
passwords, API keys, cookies, or browser profile folders.

## Login model

- Users log in directly on `https://portal.vibemod.pro/client`.
- The overlay opens a local browser profile and reuses that session.
- The app reads usage values from the VibeMode cabinet API using the user's
  existing local browser session, with visible-page parsing as a fallback.
- No password field is exposed by the app.
- The app has no telemetry, backend, or analytics endpoint.
- The browser runs hidden after successful login by default. A visible Chrome
  window is opened only when the user needs to log in again.

## Local session data

Playwright stores browser cookies/session files in the selected profile
directory. By default this is:

```text
%USERPROFILE%\.neurogate-usage-overlay\browser-profile
```

This folder is local-only and must not be committed to GitHub.

The last good parsed snapshot and local logs are stored under:

```text
%USERPROFILE%\.neurogate-usage-overlay\
```

These files can contain account labels, request IDs, and usage numbers. Treat
them as private local data.

## Do not commit

- `.env`
- cookies
- browser profiles
- HAR/trace files
- screenshots with private account data
- API keys, passwords or tokens

## Reporting security issues

Open a private security advisory in the GitHub repository or contact the
repository owner. Do not paste credentials into issues.

