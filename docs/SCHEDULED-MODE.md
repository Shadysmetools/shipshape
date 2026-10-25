# Scheduled mode (optional, off by default)

Nothing in ShipShape runs on a schedule until you set it up. Three ways:

## 1. Inside a Claude Code session: `/loop`
Self-paced re-checks while a goal waits for a fix:
```
/loop 30m /qa-goal "signup to checkout works"
```
The ledger (`qa-runs/<date>-<goal>/ledger.json`) carries state between iterations, so each run continues where the last stopped.

## 2. Cloud routines: `/schedule`
Claude Code's scheduled agents run a prompt on a cron, e.g. "every night at 02:00 run `/qa-run` on staging". Headless runs may not have interactively-authenticated MCP servers; keep scheduled runs to local scripts + dry-run delivery, or channels with env-var tokens.

## 3. The OS scheduler (local machine)
### Nightly QA regression (Windows Task Scheduler)
```powershell
$act = New-ScheduledTaskAction -Execute 'powershell.exe' -Argument '-NoProfile -File C:\path\to\shipshape\bin\run-qa.ps1 "Nightly regression" --plan C:\proj\plans\regression.json --config C:\proj\qa.config.yaml --url http://127.0.0.1:8000/ --allow-host 127.0.0.1' -WorkingDirectory 'C:\proj'
$trg = New-ScheduledTaskTrigger -Daily -At 2am
Register-ScheduledTask -TaskName 'ShipShape nightly QA' -Action $act -Trigger $trg -Settings (New-ScheduledTaskSettingsSet -ExecutionTimeLimit (New-TimeSpan -Hours 2))
```
### Weekly timesheet draft (macOS/Linux cron)
```
0 18 * * FRI cd ~/proj && python3 ~/shipshape/scripts/timesheet.py --project-dir ~/.claude/projects/<slug> --tasks tasks.json --gap 20 --tz +03:00 --since $(date -v-6d +\%F) --out timesheets/week-$(date +\%V).xlsx
```
A draft only: a person reviews it, and nothing is written to Odoo.

## 4. Odoo stage trigger: `odoo_ticket.py watch`
Start the QA cycle when an Odoo ticket enters a chosen stage (for example *Pending Internal Testing*). Configure the `odoo:` block in `qa.config.yaml` (`url`, `db`, `user`, `model`, `trigger.stages`, `on_pass`, `on_fail`, `auto_move: false`); the API key is the user's own (`ODOO_API_KEY`, saved with `keys.py set ODOO_API_KEY`).
```
python scripts/odoo_ticket.py watch --once --include-existing          # dry-run: what it would test, nothing saved
python scripts/odoo_ticket.py watch --launch --interval 300 --minutes 600
```
- It polls the model for tickets in `trigger.stages` and starts **at most one run per ticket per stage entry**: the entry is the stage plus `date_last_stage_update`, kept in `qa-runs/odoo-watch.json`. The entry is recorded before the run starts, so a crash never starts it twice. A ticket that leaves and comes back is a new entry.
- The first poll is a baseline: tickets already in the stage are recorded, not tested (`--include-existing` tests them).
- With `--launch` it saves the ticket analysis (description + log notes) to `qa-runs/odoo-tickets/<id>-<time>.md` and runs `trigger.launch` (default `claude -p "/qa-goal <goal>"`, the goal names that file). Without `--launch` it only prints.
- Time limits: `--minutes` for the whole watch, `--run-timeout` per run (default 2 h, capped by what is left). One watcher at a time (a lock).
- Watch itself only reads from Odoo. Posting the result and moving the ticket are separate, gated writes (`post`, `move`, dry-run unless `--send`). A headless `claude -p` run cannot answer the owner's permission prompt, so in a watch-started run those writes stay dry-run, except a move to `on_pass` / `on_fail` when the project set `auto_move: true` deliberately.
- Run it from Task Scheduler / cron like the jobs above, with `--minutes` below the scheduler's own limit, or with `/loop 15m python scripts/odoo_ticket.py watch --once --launch`.

## Rules for unattended runs
- Delivery stays dry-run unless the project config enables a channel AND the schedule passes `--send` deliberately (the owner set it up).
- Every scheduled job has a time limit (Task Scheduler `ExecutionTimeLimit`, `timeout` in cron).
- A run that hits a human gate stops and reports; it never waits silently.
