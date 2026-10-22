# Install proof (2026-10-22, Claude Code 2.1.308, Windows 11)

This ran in a **clean, isolated Claude Code config** (`CLAUDE_CONFIG_DIR` pointed at an empty temporary folder), so it does not depend on any existing setup.

```text
$ claude plugin validate .            -> ✔ Validation passed
$ claude plugin validate . --strict   -> ✔ Validation passed
$ claude plugin marketplace add <path to this repo>
  ✔ Successfully added marketplace: shipshape
$ claude plugin install smetools-agent-kit@shipshape
  ✔ Successfully installed plugin: smetools-agent-kit@shipshape (scope: user)
$ claude plugin list
  smetools-agent-kit@shipshape  Version 0.1.0  Status: ✔ enabled
$ claude plugin details smetools-agent-kit@shipshape
  Skills (21): 11 skills + 10 slash commands
  Agents (11): odoo-expert, qa-automation-tester, qa-code-reviewer, qa-demo-video-producer, qa-desktop-tester,
               qa-lead, qa-live-regression-recorder, qa-load-tester, qa-refuter, qa-security-reviewer, timesheet-agent
  Hooks (3 events): SessionStart, Stop, PreToolUse
  MCP servers (2): playwright, chrome-devtools
  Always-on context cost: about 2,300 tokens
```

The pinned MCP packages resolve through npm (`@playwright/mcp@0.0.83`, `chrome-devtools-mcp@1.10.1`), and `bin/doctor` launches Chromium through Playwright.

## Not verified here
- `/plugin marketplace add <owner>/shipshape` from GitHub (the repo was not pushed from this session); the local-path add uses the same manifest.
- A live session in which the prompt and agent hooks are judged by a model. Hook JSON is validated, and the deterministic commit-scan hook is unit-tested.
- MCP servers started inside a live session (the packages were resolved, not run through `/mcp`).
