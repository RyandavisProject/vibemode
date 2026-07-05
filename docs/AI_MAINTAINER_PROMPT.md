# AI Maintainer Prompt

Use this prompt when continuing Vibemode Overlay from another machine or AI
coding agent.

```text
Project: Vibemode Overlay
Repository: https://github.com/RyandavisProject/vibemode

You are continuing a cross-platform desktop overlay project used on Windows and
macOS.

Before changing anything:
1. Read AGENTS.md, README.md, docs/PUBLISHING.md, docs/ARCHITECTURE.md,
   docs/PRIVACY.md.
2. Run:
   - git fetch --tags
   - git status --short --branch
3. Check local version files:
   - src/neurogate_usage_overlay/__init__.py
   - pyproject.toml
   - README.md
4. Check the public updater source:
   - https://api.github.com/repos/RyandavisProject/vibemode/releases/latest
5. Clearly separate:
   - local code version;
   - main branch state;
   - latest published GitHub Release;
   - release ZIP assets;
   - what the in-app updater can see.

Rules:
- Do not delete browser-profile, cookies, localStorage, sessionStorage,
  overlay state, or daily history.
- Do not print tokens, cookies, API keys, passwords, or private account data.
- Do not overwrite uncommitted work that you did not create.
- Do not commit, push, create tags, publish releases, or upload assets unless
  the owner explicitly asks for that step.
- Do not treat a version bump in files as a public release.

If the owner asks to push, publish, update GitHub, or upload a version:
1. Run the project checks from docs/PUBLISHING.md.
2. Build a fresh ZIP with scripts/package-release.ps1.
3. Verify the ZIP contains Windows and macOS install/run/update scripts.
4. Verify the ZIP excludes .venv, dist, local state, browser profiles, cookies,
   logs, secrets, and internal handoff/audit files.
5. Push main only after reviewing the diff.
6. Publish or update the GitHub Release tag vX.Y.Z if this is a public version.
7. Attach both vibemode-vX.Y.Z.zip and vibemode-vX.Y.Z.zip.sha256.
8. Confirm GitHub Releases marks that version as latest.
9. Confirm the in-app updater sees the release through releases/latest.

Final report must include:
- what changed;
- files changed;
- checks run and results;
- skipped checks and why;
- whether commit/push/release happened;
- these five statuses:
  main: pushed / not pushed
  version files: X.Y / mismatch
  release ZIP: built / not built
  GitHub Release: published / not published
  in-app update: visible / not visible

If changes are Mac-only cosmetics, say whether Windows behavior and Windows ZIP
users are affected. If the change should reach users, complete the release
process; otherwise state that only main has changed and installed users will not
see an update yet.
```

