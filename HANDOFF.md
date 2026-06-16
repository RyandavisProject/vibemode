# HANDOFF - NeuroGate API Overlay

Updated: 15-06-2026
Project id: neurogate-overlay
Format: Handoff v2 / short transfer sheet

## Current Snapshot

Current version: `1.7.2` pushed with audit/performance fixes.
Current branch: `main`
GitHub: `https://github.com/RyandavisProject/neurogate-overlay`
Latest pushed commit: `bf2b984 neurogate-overlay 15-06-2026 22-44 v1.7.2: audit performance hardening`
Current status: PASS - `v1.7.2` is on GitHub `main`.

Next safe step:

- Let the owner live-test `v1.7.2`; package ZIP/release only if explicitly requested.

## Project Goal

NeuroGate API Overlay is a compact Windows overlay for NeuroGate API usage limits.
It should be easy for a regular Russian-speaking user to install, launch, understand
and update without giving the project owner any private credentials or data.

The overlay is local-first:

- browser session stays on the user's machine;
- usage/state files stay under `%USERPROFILE%\.neurogate-usage-overlay`;
- the public repository contains code, docs and sanitized screenshots only.

## Read These First

- `PROJECT_STATE.md`
- `README.md`
- `CHANGELOG.md`
- `docs/ARCHITECTURE.md`
- `docs/PRIVACY.md`
- `docs/PUBLISHING.md`
- `security_best_practices_report.md`

## Latest Important Changes

`v1.7.1`:

- Daily limit no longer carries into the next calendar day.
- Third row is hidden after day rollover until the user manually sets a new limit.
- Daily limit dialog again suggests a calculated value:
  `7d remaining / remaining 7d reset time` with hours/minutes converted to decimal days.
- Suggested value is only a suggestion; nothing is saved until the user confirms.
- `Сменить аккаунт` was moved down in the menu above `Закрыть`.
- Version was updated in code, README and CHANGELOG.
- Pushed to GitHub `main`.

`v1.7.2` prepared changes:

- Drag performance fix: movement is batched and position is saved after release.
- Canvas leak fix: render no longer recreates tooltip/daily-limit tag bindings.
- Browser cache hygiene: safe cache folders are pruned without deleting cookies/session/local storage.
- Chrome cache caps were added.
- Reader worker queue is bounded and worker calls have timeout protection.
- ZIP update now requires SHA256 by default; unverified ZIP update requires explicit local-dev override.
- `security_best_practices_report.md` was refreshed for the current audit.
- `PROJECT_STATE.md` and `HANDOFF.md` were refreshed.

`v1.7.0` context that must be preserved:

- Optional `лимит/день` third row.
- Double-click on daily-limit row opens editing.
- Daily progress color scale: blue to 50%, yellow after 50%, orange near 75%, red at 100%+.
- UI site-reading work moved out of the main UI path to reduce hangs.
- Watchdog after Windows sleep forces refresh without erasing last good data on temporary failure.
- Window position should be restored after restart.
- ZIP updater uses release ZIP asset/checksum logic and safer rollback/allowlist behavior.

## Verification State

Checked after push and local audit fixes:

- `main` is synchronized with `origin/main`.
- `bf2b984` is on local `HEAD` and `origin/main`.
- GitHub repository is public.
- `powershell -ExecutionPolicy Bypass -File .\scripts\check.ps1`: PASS, `106 tests OK`.

Tooling note:

- `pytest` is not installed in the active Python or `.venv`.
- Use this canonical check command instead:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\check.ps1
```

Packaging note:

- `dist` currently contains ZIP artifacts through `v1.7.0`.
- No ZIP has been built for `v1.7.2` yet.

## Owner Preferences

- Speak Russian by default.
- Keep GitHub README in Russian and visually readable.
- Link users to the main repo page unless a release link is explicitly requested.
- Do not create GitHub Releases without explicit approval.
- Do not push design drift: the overlay is small, compact and sensitive to pixel-level changes.
- Use version bumps intentionally: patch for fixes, minor for visible feature changes.
- Commit naming pattern:

```text
neurogate-overlay dd-mm-yyyy hh-mm vX.Y.Z: short meaning
```

## Safety Boundaries

Never expose or commit:

- tokens, passwords, API keys;
- local browser profiles;
- local session state;
- private NeuroGate data;
- raw logs with account page content;
- temporary install/update folders unless sanitized.

Ask before:

- force-push;
- deleting repos/tags/releases;
- changing repo visibility;
- creating GitHub Releases;
- publishing ZIP installers;
- changing auth/session/autologin behavior.

## Next Safe Commands

Check project:

```powershell
cd C:\Codex\neurogate-usage-overlay
powershell -ExecutionPolicy Bypass -File .\scripts\check.ps1
```

Package release if owner asks:

```powershell
cd C:\Codex\neurogate-usage-overlay
powershell -ExecutionPolicy Bypass -File .\scripts\package-release.ps1
```

Before packaging candidate fixes:

```powershell
cd C:\Codex\neurogate-usage-overlay
powershell -ExecutionPolicy Bypass -File .\scripts\check.ps1
```

Then package only if the owner explicitly asks for ZIP/release artifacts.

Verify GitHub state:

```powershell
git status --short --branch
git log --oneline -3 --decorate
gh repo view RyandavisProject/neurogate-overlay --json name,visibility,url,defaultBranchRef
```
