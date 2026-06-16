# PROJECT_STATE - NeuroGate API Overlay

Updated: 15-06-2026
Project: NeuroGate API Overlay
Project id: neurogate-overlay
Local path: `C:\Codex\neurogate-usage-overlay`
GitHub: `https://github.com/RyandavisProject/neurogate-overlay`
Current version: `1.7.2` pushed with audit/performance fixes.
Current branch: `main`
Latest commit: `bf2b984 neurogate-overlay 15-06-2026 22-44 v1.7.2: audit performance hardening`
CPLS status: PASS - public project is usable and `v1.7.2` is pushed to GitHub `main`.
Current mode: patch-safe; preserve current compact UI unless owner explicitly asks for visual changes.

## State Summary

`NeuroGate API Overlay` is a small local-first Windows overlay for NeuroGate API limits.
It shows the current tariff, tariff time left, 5-hour and 7-day remaining limits,
progress bars, refresh time, optional 2x scale, usage tooltips, and an optional manual
daily spending limit row.

The project is public on GitHub and intended for Russian-speaking users. README,
CHANGELOG and UI text should stay mostly Russian. The product must not collect or
send private data to the project owner or third parties. User auth/session state is
local to the user's machine.

## Current Product Surface

- Compact borderless always-on-top overlay.
- Right-click settings menu.
- Manual refresh plus saved refresh interval.
- Optional `Не закрывать ЛК` mode.
- Account switching flow via `Сменить аккаунт`.
- Safe autologin only when the browser already has a stable prefilled login form
  and the user is not changing account.
- Local browser profile under `%USERPROFILE%\.neurogate-usage-overlay\browser-profile`.
- Daily usage file under `%USERPROFILE%\.neurogate-usage-overlay\usage-daily.json`.
- Overlay state under `%USERPROFILE%\.neurogate-usage-overlay\overlay-state.json`.
- Public ZIP/Git install flows and update checker.

## Latest Update - 15-06-2026

Version `1.7.2` was committed and pushed to `main`.

Changed:

- `лимит/день` now applies only on the calendar day when the user manually set it.
- On the next calendar day the third row is hidden and yesterday's daily limit is
  cleared instead of being carried forward.
- `Задать лимит на день` again suggests a calculated number, but saves it only
  after manual confirmation.
- Suggested daily limit formula: `7d remaining / remaining 7d reset time`, where
  hours and minutes are converted to decimal days.
- `Сменить аккаунт` was moved near the bottom of the menu, directly above `Закрыть`.
- README and CHANGELOG were updated for `1.7.2`.
- Drag movement is batched and no longer saves window position during every mouse movement.
- Canvas tooltip/daily-limit bindings are installed once instead of being recreated on every render.
- Browser cache cleanup removes only safe cache folders and keeps cookies/session storage intact.
- Chrome disk/media cache is capped.
- Reader worker queue is bounded and worker calls now have timeout protection.
- ZIP updater now requires SHA256 for ZIP updates by default; unverified ZIP updates require explicit local-dev override.
- `security_best_practices_report.md` was refreshed with the current audit.

Repository state after push:

- `main` is synchronized with `origin/main`.
- `bf2b984` is on local `HEAD` and `origin/main`.
- GitHub repository is public.
- No GitHub Release was created by owner preference.
- Existing `dist` artifacts currently go up to `neurogate-overlay-v1.7.0.zip`.
- No ZIP has been built yet for the local audit-fix candidate.

## Verification

Verified after push:

- `git status --short --branch`: clean, `main...origin/main`.
- `git log --oneline -3 --decorate`: `bf2b984` is on `HEAD` and `origin/main`.
- `gh repo view RyandavisProject/neurogate-overlay`: repository is public and default
  branch is `main`.
- `powershell -ExecutionPolicy Bypass -File .\scripts\check.ps1`: PASS, `106 tests OK` after local audit/performance fixes.

Tooling note:

- `pytest` is not installed in the active Python or project `.venv`.
- The supported project check command is `powershell -ExecutionPolicy Bypass -File .\scripts\check.ps1`,
  which uses `unittest`, compile checks and PowerShell script parsing.

## Accepted Product Rules

- Do not create GitHub Releases unless the owner explicitly asks.
- Do not change compact layout, positions, fonts or colors casually.
- Dates in docs should use `dd-mm-yyyy`.
- Commit names should follow: `neurogate-overlay dd-mm-yyyy hh-mm vX.Y.Z: short meaning`.
- Public sharing should normally link to the main repository page:
  `https://github.com/RyandavisProject/neurogate-overlay`.
- README should stay readable on the main GitHub page; avoid creating extra pages
  for chat-only announcements unless the owner asks.

## Daily Limit Rules

- The daily limit is manually set by the user.
- It is valid only for the calendar day when it was set.
- It must not be automatically carried into the next day.
- If hidden and set again, the dialog should suggest a calculated value but still
  require user confirmation.
- Suggested value is based on current 7-day remaining limit divided by the remaining
  7-day reset time in decimal days.
- Third row appears only when the daily limit is active for today.
- Double-click on the third row opens daily limit editing.
- Progress color scale:
  - up to 50%: blue;
  - after 50%: yellow;
  - around 75%: orange;
  - 100% and above: red.

## Safety Boundary

Do not commit or expose:

- GitHub tokens, API keys, passwords or `.env` files;
- local NeuroGate browser profiles;
- `%USERPROFILE%\.neurogate-usage-overlay\browser-profile`;
- local user state, logs with private content, or raw personal account data;
- temporary install/update sandboxes unless intentionally sanitized.

Do not do without explicit owner confirmation:

- delete repositories;
- force-push;
- change GitHub repository visibility;
- create GitHub Releases;
- publish installers or binaries as releases;
- change account/session behavior in a way that can log a new user into the owner's account.

## Current Risks

| Risk | Level | Mitigation |
| --- | --- | --- |
| `v1.7.2` ZIP artifact is not present in `dist` | WARN | Build package only if owner asks for a ZIP/release refresh |
| Candidate ZIP artifact is not present in `dist` | WARN | Run package script and verify ZIP/checksum before announcing ZIP update |
| Dev dependency setup is implicit | WARN | Consider documenting/installing test tooling or keeping `scripts/check.ps1` as the canonical check |
| NeuroGate page can change markup | WARN | Keep parser tests for old and current formats; add fixtures when page changes |
| Autologin can annoy users or affect account switching | WARN | Keep safe-autologin guardrails and preserve explicit `Сменить аккаунт` behavior |
| Compact UI is sensitive to small layout changes | WARN | Ask before visual redesign; prefer tiny measured changes |
| Public repo may accidentally include local data | BLOCKER | Keep `.gitignore`, release allowlist and manual review before packaging |

## Next Safe Step

Next safe step:

1. Let the owner live-test `v1.7.2`.
2. If a public ZIP/release refresh is needed, run `powershell -ExecutionPolicy Bypass -File .\scripts\package-release.ps1`.
3. Do not create GitHub Releases unless the owner explicitly asks.
