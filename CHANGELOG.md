# Changelog

## Unreleased
- **Odoo tickets drive the QA cycle (#1, #2).** New `scripts/odoo_ticket.py` (stdlib JSON-RPC): `read <ticket>` prints the description, stage and log notes (read-only) and the qa-lead plans from that analysis; `post <ticket> --run <run>` writes one privacy-filtered log note with `N pass / M fail / K flaky / B blocked`, the bug list and the video link (once per run and ticket); `move <ticket> --stage NAME` finds the stage in the ticket's own team/project, writes, then reads back; `watch` polls `odoo.trigger.stages` and starts at most one run per ticket per stage entry (state in `qa-runs/odoo-watch.json`, first poll is a baseline, `--minutes` / `--run-timeout` limits, one watcher at a time). `post` and `move` are dry-run unless `--send`, and `hook_guard.py` routes `--send` to the owner's permission prompt; `auto_move: true` lets moves to `on_pass` / `on_fail` through. New `odoo:` block in the config template. The API key is the user's own (`ODOO_API_KEY` via `keys.py`, asked for once; `keys.py check` lists it); a key written in the config is refused. Tests: `tests/test_odoo_ticket.py` (mocked Odoo, no real instance).
- **Missing API keys are asked for, not just reported.** New `scripts/keys.py`: lookup order env var, OS keychain (`keyring`), then `~/.config/shipshape/secrets/keys.json` (outside the repo, owner-only, blocked by the read guard). When a key is missing, a masked window (or hidden terminal prompt) asks once and saves it. Used by every delivery channel on a real `--send` (never on a dry run) and by the OpenAI/ElevenLabs narrator. `keys.py check --config` lists what a project needs. `SMEKIT_NO_PROMPT=1` turns prompts off. Values are never printed. Tests: `tests/test_keys.py`.

## 0.1.1 (2026-10-24)
Fixes from the independent evaluation of 0.1.0 (score 6.5/10), in its order of impact.

- **`--url` now wins over a plan's `base_url`** (`record.py --base-url/--allow-host`, the ledger stores the target, `qa_loop.py round` passes it). A dead target now fails instead of reporting "goal met" from the plan's embedded URL; the override is printed and stored in `results.json`.
- Privacy scanner catches absolute paths on any Windows drive letter, not only `C:\Users`; tutorial manifests use relative paths.
- README and QUICKSTART state honest timings (first install about 20 min because of Chromium; demo about 6 min) and explain the two names (repo/marketplace `shipshape`, plugin `smetools-agent-kit`); installers print the real marketplace owner.
- `qa.config.yaml` is validated: broken YAML, a non-boolean `enabled` or a secret spec that is not `{env: NAME}` / `{keyring: service/user}` give one `config error at notify.<channel>.<field>` line (exit 2) instead of a traceback.
- Bad plan files fail fast with the path and line (`record.py` exit 2, `full_qa.py` checks every `--plan` before step 1, `qa_loop.py start` refuses missing plans).
- Narration: both passes are narrated (clips are cached, so pass 2 is free); `results.json` carries `narration_note`, the round prints it, and the HTML report marks each pass "voice" or "no voice (reason)".
- `narrator.py report` degrades like the recorder when no voice can be made: captions only, one warning, exit 0.
- Installer: Playwright pinned to `1.63.*`, no `pip --upgrade`, Chromium only by default (Firefox/WebKit behind `--with-browsers` / `-WithBrowsers`), download sizes printed.
- Hooks: 33 handlers (11 distinct texts) collapsed to 6. One deterministic command hook (`scripts/hook_guard.py`, matcher `Bash|PowerShell|Read`) denies secret reads, literal keys, force/protected pushes and leaky commits, and routes merges, deletes, real delivery and desktop runs to the user's own permission prompt (`permissionDecision: ask`). No model call on ordinary file reads any more. Marketplace `source` is `"."`.
- `run-qa` (sh + ps1) refuses to start when port 8765 is taken and kills the demo server's process tree; `ledger.json` stores plan paths relative to the run folder; `doctor.py` npm checks time out after 15 s.

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
