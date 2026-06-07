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
git commit -m "Prepare Vibemode overlay for public release"
```

## 5. Push To GitHub

Create a new GitHub repository, then:

```powershell
git remote add origin https://github.com/YOUR-ORG/neurogate-usage-overlay.git
git branch -M main
git push -u origin main
```

## 6. User Instructions

Tell users:

1. Install Python and Chrome.
2. Download/clone the repository.
3. Run `scripts\install.bat`.
4. Use the created `Vibemode Overlay` desktop shortcut.
5. Log in directly on the Vibemode/Neurogate website when Chrome opens.

Never ask users to send you their password.

## 7. AI-Assisted Install

Point AI coding agents to:

```text
docs/AI_INSTALL_PROMPT.md
```

Suggested user command:

```text
Install Vibemode Overlay from this repository. Read docs/AI_INSTALL_PROMPT.md
and follow it exactly.
```
