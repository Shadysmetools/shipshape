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

## Rules for unattended runs
- Delivery stays dry-run unless the project config enables a channel AND the schedule passes `--send` deliberately (the owner set it up).
- Every scheduled job has a time limit (Task Scheduler `ExecutionTimeLimit`, `timeout` in cron).
- A run that hits a human gate stops and reports; it never waits silently.
