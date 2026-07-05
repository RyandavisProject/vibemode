# Publishing To GitHub

Use this checklist before sharing the overlay publicly.

## Release Source Of Truth

Vibemode can be changed from multiple machines. Keep these states separate:

- local working tree: what the current machine has on disk;
- `main`: what developers and Git installs receive after `git pull`;
- GitHub Release: what ZIP installs and the in-app updater can see;
- release assets: the actual ZIP and checksum attached to the Release.

The in-app update checker reads only:

```text
https://api.github.com/repos/RyandavisProject/vibemode/releases/latest
```

If `releases/latest` returns `v2.4`, then a running `2.4` overlay is correct to
show no update, even if `main`, a local machine, or README already mentions
`2.5`.

A public update exists only when all of these are true:

- version files were updated consistently;
- `main` was pushed;
- a published GitHub Release exists for `vX.Y.Z`;
- `vibemode-vX.Y.Z.zip` is attached;
- `vibemode-vX.Y.Z.zip.sha256` is attached or the asset exposes a SHA256 digest;
- GitHub marks that Release as the latest stable Release.

## 0. Owner Push Protocol

When the owner asks to "push", "publish", "update GitHub", or "upload the
version", do not treat it as only `git push main` if the change is a user-facing
Vibemode version.

A complete Vibemode push must account for every user installation path:

- push `main`;
- update the package version, README, and changelog when behavior changed;
- verify Windows overlay behavior when Windows UI changed;
- verify macOS-safe tests and keep macOS install/run scripts in the release;
- build a fresh release ZIP with `scripts/package-release.ps1`;
- verify the ZIP contains Windows and macOS install/run/update scripts;
- verify the ZIP excludes `.venv`, `dist`, local state, browser profiles,
  cookies, logs, secrets, and internal handoff/audit files;
- publish or update the GitHub Release tag for that version;
- attach both `vibemode-vX.Y.Z.zip` and `vibemode-vX.Y.Z.zip.sha256`;
- confirm GitHub marks the new release as latest;
- report which install paths are ready: Windows Git, Windows ZIP, macOS Git,
  macOS ZIP, and in-app update.

If the owner explicitly asks for code-only push or no release, say clearly that
ZIP installs and in-app updates will not receive the new version until a GitHub
Release with assets is published.

## 0.1 Multi-Machine Handoff Protocol

When continuing work from another computer or AI agent:

1. Read `AGENTS.md` and `docs/AI_MAINTAINER_PROMPT.md`.
2. Run `git fetch --tags`.
3. Run `git status --short --branch`.
4. Compare local version files with the latest GitHub Release.
5. Check whether the latest work was only pushed to `main` or also released.
6. Do not overwrite uncommitted work from another machine.
7. Do not delete local state, browser profiles, cookies, logs, or history.

Before reporting "updated", explicitly state:

```text
main: pushed / not pushed
version files: X.Y / mismatch
release ZIP: built / not built
GitHub Release: published / not published
in-app update: visible / not visible
```

For Mac-only cosmetic changes, say whether they are:

- code-only changes for the next developer pull;
- included in a ZIP asset;
- visible to the in-app updater;
- expected to affect Windows behavior.

## 1. Remove Local Data

Do not publish:

- `.venv/`
- browser profile folders;
- cookies/session files;
- screenshots with private usage data;
- logs;
- `.env`;
- API keys, passwords or tokens.

The included `.gitignore` excludes the normal local-only files.

## 2. Verify Locally

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\check.ps1
```

Build the release ZIP:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\package-release.ps1
```

The ZIP is created in `dist/`, for example:

```text
dist\vibemode-vX.Y.Z.zip
```

The release ZIP intentionally excludes internal handoff/state/audit files:
`PROJECT_STATE.md`, `HANDOFF.md`, and `security_best_practices_report.md`.

## 3. Review Public Docs

Confirm these files are current:

- `README.md`
- `AGENTS.md`
- `SECURITY.md`
- `docs/PRIVACY.md`
- `docs/ARCHITECTURE.md`
- `docs/AI_INSTALL_PROMPT.md`
- `docs/AI_MAINTAINER_PROMPT.md`

## 4. Initialize Repository

```powershell
git init
git add .
git commit -m "Prepare Vibemode for public release"
```

## 5. Push To GitHub

Create a new GitHub repository, then:

```powershell
git remote add origin https://github.com/RyandavisProject/vibemode.git
git branch -M main
git push -u origin main
```

## 6. User Instructions

Tell users:

1. Install Python and Chrome.
2. Download the latest ZIP from GitHub Releases.
3. Extract the ZIP.
4. Run `Install-Vibemode.bat`.
5. Use the created `Vibemode` desktop shortcut.
6. Log in directly on the Vibemode website when Chrome opens.

For AI-assisted or developer installs, users can also clone the repository and
run:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\install.ps1
```

## 7. GitHub Release

After pushing a version commit:

1. Create a GitHub Release with tag `vX.Y.Z`.
2. Use the release title `Vibemode vX.Y.Z`.
3. Attach the generated ZIP from `dist/`.
4. Attach the generated `.sha256` file next to the ZIP, or make sure the
   release asset exposes a SHA256 digest.
5. Mention the main changes from `CHANGELOG.md`.

The in-app update checker reads the latest GitHub Release. Without a Release,
users will not see update notifications in the overlay menu.
ZIP updates require SHA256 by default on both Windows and macOS.

Never ask users to send you their password.

## 8. AI-Assisted Install

Point AI coding agents to:

```text
docs/AI_INSTALL_PROMPT.md
```

Suggested user command:

```text
Install Vibemode from this repository. Read docs/AI_INSTALL_PROMPT.md
and follow it exactly.
```

## 9. AI-Assisted Maintenance

Point AI coding agents that will edit or release the project to:

```text
AGENTS.md
docs/AI_MAINTAINER_PROMPT.md
```

Suggested owner command:

```text
Continue Vibemode Overlay from this repository. Read AGENTS.md and
docs/AI_MAINTAINER_PROMPT.md first. Then inspect the local version, main,
GitHub Releases, ZIP assets, and in-app update state before changing anything.
```
