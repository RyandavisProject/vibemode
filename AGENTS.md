# Vibemode Agent Protocol

This repository is edited from more than one machine and sometimes by more
than one AI coding agent. Treat this file as the first handoff document.

## First Read

Before changing code, read:

- `README.md`
- `docs/PUBLISHING.md`
- `docs/ARCHITECTURE.md`
- `docs/PRIVACY.md`
- `docs/AI_MAINTAINER_PROMPT.md`

## Source Of Truth

- `main` is the current development branch.
- GitHub Releases are what ZIP users and the in-app updater see.
- The in-app updater reads:
  `https://api.github.com/repos/RyandavisProject/vibemode/releases/latest`
- A version bump in files or on `main` is not a public update until a published
  GitHub Release exists with the matching tag and assets.
- A complete public release needs both:
  `vibemode-vX.Y.Z.zip` and `vibemode-vX.Y.Z.zip.sha256`.

## Multi-Machine Safety

At the start of every task:

1. Run `git fetch --tags`.
2. Run `git status --short --branch`.
3. Compare local version files with the latest GitHub Release.
4. Check whether the task is code-only, docs-only, or release-facing.
5. Do not overwrite local uncommitted work that you did not create.

Do not publish, delete, or print:

- browser profiles;
- cookies;
- local/session storage;
- overlay state/history files;
- tokens, API keys, passwords, or private account data.

## Push And Release Rule

When the owner asks to push, publish, update GitHub, or upload a version, do
not assume that `git push main` is enough. Follow `docs/PUBLISHING.md`.

Always report these five statuses:

```text
main: pushed / not pushed
version files: X.Y / mismatch
release ZIP: built / not built
GitHub Release: published / not published
in-app update: visible / not visible
```

If the owner explicitly asks for a code-only push, say clearly that ZIP installs
and in-app updates will not receive the change until a GitHub Release with
assets is published.

## Platform Parity

Vibemode has two user-facing surfaces:

- Windows: Tkinter desktop overlay.
- macOS: menu bar item and popover.

When a change affects user behavior, verify or explicitly skip with a reason:

- Windows Git install;
- Windows ZIP install;
- macOS Git install;
- macOS ZIP install;
- in-app update.

Do not change only one platform silently if the feature is expected to be
shared.

