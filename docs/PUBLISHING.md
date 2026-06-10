# Publishing To GitHub

Use this checklist before sharing the overlay publicly.

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
dist\neurogate-overlay-v1.5.0.zip
```

## 3. Review Public Docs

Confirm these files are current:

- `README.md`
- `SECURITY.md`
- `docs/PRIVACY.md`
- `docs/ARCHITECTURE.md`
- `docs/AI_INSTALL_PROMPT.md`

## 4. Initialize Repository

```powershell
git init
git add .
git commit -m "Prepare NeuroGate API for public release"
```

## 5. Push To GitHub

Create a new GitHub repository, then:

```powershell
git remote add origin https://github.com/RyandavisProject/neurogate-overlay.git
git branch -M main
git push -u origin main
```

## 6. User Instructions

Tell users:

1. Install Python and Chrome.
2. Download the latest ZIP from GitHub Releases.
3. Extract the ZIP.
4. Run `Install-NeuroGate-API.bat`.
5. Use the created `NeuroGate API` desktop shortcut.
6. Log in directly on the NeuroGate website when Chrome opens.

For AI-assisted or developer installs, users can also clone the repository and
run:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\install.ps1
```

## 7. GitHub Release

After pushing a version commit:

1. Create a GitHub Release with tag `vX.Y.Z`.
2. Use the release title `NeuroGate API vX.Y.Z`.
3. Attach the generated ZIP from `dist/`.
4. Mention the main changes from `CHANGELOG.md`.

The in-app update checker reads the latest GitHub Release. Without a Release,
users will not see update notifications in the overlay menu.

Never ask users to send you their password.

## 8. AI-Assisted Install

Point AI coding agents to:

```text
docs/AI_INSTALL_PROMPT.md
```

Suggested user command:

```text
Install NeuroGate API from this repository. Read docs/AI_INSTALL_PROMPT.md
and follow it exactly.
```

