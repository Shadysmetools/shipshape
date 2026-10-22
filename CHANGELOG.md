# Changelog

## 0.1.0 (2026-10-22)
First release of ShipShape (plugin id `smetools-agent-kit`).

- QA crew: qa-lead plus 9 sub-agents (code review, security review, automated ×2, load, live regression, desktop, demo video, refuter).
- Goal loop with a durable ledger, stop conditions, bug lifecycle and human gates; old-run history (trend, flaky, re-check).
- Playwright recorder: caption bar, edge-tts narration synthesized before the run, `.srt`, trace, screenshots, console/network, host allow-list, never-pay and stop-before-input guards, step and run timeouts.
- Two-pass runs with FLAKY detection; an honest counter (a PASS without evidence counts as BLOCKED; "all green" is caught).
- Offline HTML report with videos, screenshots, load chart, security count and trend.
- Notifiers: Telegram, WhatsApp (Meta/Twilio), Slack, email, webhook; dry-run default; env-var secrets; size limits with compress-or-link.
- Load tester (native ramp/soak/spike + k6 template), security scan wrapper, narrator (edge/OpenAI/ElevenLabs, EN/AR, ducking), slides video builder.
- Desktop control layer (pywinauto/pyautogui/osascript + ffmpeg recording) with gates, notice banner, failsafe and action log.
- Plain-language prompt/agent hooks, a commit secret-scan hook, and a SessionStart line.
- Timesheet agent: measured hours from Claude Code logs (sorted, merged, union, gap 10/15/20) + git, 7-sheet Excel, Odoo rows, self-checks.
- Odoo expert + pre-deploy checker, neutralize/migration/runbook templates.
- Workflows: full-qa, demo, regression-loop. Installers and doctor for bash + PowerShell.
