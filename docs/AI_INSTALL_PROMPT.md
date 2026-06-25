# AI Install Prompt

Use this prompt with Codex, Claude Code, or another local coding agent that can
run terminal commands on your Windows machine.

```text
You are installing Vibemod for VibeMode from:

https://github.com/RyandavisProject/vibemod

Goal:
Install the local Windows overlay, create a desktop shortcut, launch it, and
give the user a short plain-language installation report.

Rules:
- Do not ask the user for VibeMode or portal passwords.
- Do not collect, print, or store credentials.
- The user must log in directly on the VibeMode website if Chrome
  opens a login page.
- Do not click the VibeMode login button for the user and do not rely on
  saved autofill credentials.
- After login succeeds, the visible Chrome window should hide automatically
  and future overlay updates should continue from the same local browser session.
- The right-click menu has `Не закрывать ЛК` for users who temporarily want to
  keep the account page visible. Turning it off hides that visible window.
- The right-click menu also has `Сменить аккаунт`. It clears only the overlay's
  local browser profile and opens a fresh login window.
- Do not upload local browser profiles, cookies, logs, screenshots, or API keys.
- Do not push to GitHub unless the user explicitly asks.

Steps:
1. If the repository is not already cloned locally, clone it:
   git clone https://github.com/RyandavisProject/vibemod.git
   cd vibemod
2. Inspect the repository root and confirm these files exist:
   - README.md
   - pyproject.toml
   - scripts/install.ps1
   - scripts/run-overlay.ps1
   - scripts/create-desktop-shortcut.ps1
   - src/neurogate_usage_overlay/
3. Run:
   powershell -ExecutionPolicy Bypass -File .\scripts\install.ps1
4. Run checks:
   powershell -ExecutionPolicy Bypass -File .\scripts\check.ps1
5. Create or refresh the desktop shortcut:
   powershell -ExecutionPolicy Bypass -File .\scripts\create-desktop-shortcut.ps1
6. Launch the overlay:
   powershell -ExecutionPolicy Bypass -File .\scripts\run-overlay.ps1
7. If Chrome opens a VibeMode login page, tell the user:
   "Please log in in this Chrome window. The app does not receive your password.
   After login, the visible browser will hide and updates will continue hidden."
8. After launch, report:
   - what was installed;
   - where the desktop shortcut is;
   - how to run the overlay again;
   - what privacy boundary is used;
   - whether checks passed.

Expected short report style:
"Installed Vibemod. I created a local .venv, installed the package,
created the desktop shortcut, ran checks, and launched the overlay. The app does
not collect passwords or API keys; login happens only on the VibeMode
website in the local Chrome profile."
```

