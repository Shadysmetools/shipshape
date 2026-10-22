---
name: browser-choice
description: Pick the right browser or desktop engine for a QA task - Playwright MCP/scripts vs Chrome DevTools MCP vs desktop control. Use when unsure which tool to use for testing, recording, debugging a failure, performance, Lighthouse, a real signed-in Chrome flow (passkeys, OAuth), or a native app.
---
# Which engine
- **Playwright** (MCP `browser_*` + `scripts/record.py`): the default for deterministic tests, accessibility snapshots, cross-browser runs, native video + trace, isolated test profiles, CI and loops.
- **Chrome DevTools MCP**: diagnosis when something fails or is slow (console, network, performance trace, Lighthouse, heap), and flows that need the user's real signed-in Chrome (passkeys, OAuth/SSO) with `--autoConnect`.
- **Desktop** (the `desktop-control` skill): native apps, OS dialogs, file pickers, Electron apps. Only when the project enables it.

Full decision table: `${CLAUDE_PLUGIN_ROOT}/docs/BROWSERS.md`.
