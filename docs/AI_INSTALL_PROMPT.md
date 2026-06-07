# AI Install Prompt

Use this prompt with Codex, Claude Code, or another local coding agent that can
run terminal commands on your Windows machine.

```text
You are installing Vibemode Overlay from the current repository.

Goal:
Install the local Windows overlay, create a desktop shortcut, launch it, and
give the user a short plain-language installation report.

Rules:
- Do not ask the user for Vibemode, Neurogate, API, or portal passwords.
- Do not collect, print, or store credentials.
- The user must log in directly on the Vibemode/Neurogate website if Chrome
  opens a login page.
- Do not upload local browser profiles, cookies, logs, screenshots, or API keys.
- Do not push to GitHub unless the user explicitly asks.

Steps:
1. Inspect the repository root and confirm these files exist:
   - README.md
   - pyproject.toml
   - scripts/install.ps1
   - scripts/run-overlay.ps1
   - scripts/create-desktop-shortcut.ps1
   - src/neurogate_usage_overlay/
2. Run:
   powershell -ExecutionPolicy Bypass -File .\scripts\install.ps1
3. Run checks:
   powershell -ExecutionPolicy Bypass -File .\scripts\check.ps1
4. Create or refresh the desktop shortcut:
   powershell -ExecutionPolicy Bypass -File .\scripts\create-desktop-shortcut.ps1
5. Launch the overlay:
   powershell -ExecutionPolicy Bypass -File .\scripts\run-overlay.ps1
6. If Chrome opens a Vibemode/Neurogate login page, tell the user:
   "Please log in in this Chrome window. The app does not receive your password."
7. After launch, report:
   - what was installed;
   - where the desktop shortcut is;
   - how to run the overlay again;
   - what privacy boundary is used;
   - whether checks passed.

Expected short report style:
"Installed Vibemode Overlay. I created a local .venv, installed the package,
created the desktop shortcut, ran checks, and launched the overlay. The app does
not collect passwords or API keys; login happens only on the Vibemode/Neurogate
website in the local Chrome profile."
```
