---
name: timesheet-measure
description: Measure real working hours from Claude Code session logs and git commits, map them to tasks, and produce an Excel timesheet plus Odoo account.analytic.line import rows with self-checks. Use for "log my hours", "timesheet for project X", "how long did this take".
---
# Timesheet
```
python ${CLAUDE_PLUGIN_ROOT}/scripts/timesheet.py --project-dir ~/.claude/projects/<slug> [--session <id>] --tasks tasks.json \
  [--repo <git repo>] --gap 10|15|20 --tz +03:00 --since YYYY-MM-DD --until YYYY-MM-DD \
  [--lookup lookup.json] [--existing existing.json] --out hours.xlsx
```
Sheets: Summary, Daily, Sessions, Evidence, Method, Checks, Odoo Import (values only, no formulas). It also writes `-odoo-import.csv` and `-analytic-lines.json` (status NOT WRITTEN).

Checks: totals match, no negative hours, no day over 16 h, no overlap with existing lines, employee visible, every block assigned.

Method and pitfalls: `${CLAUDE_PLUGIN_ROOT}/docs/TIMESHEET-METHOD.md`. Writing to Odoo needs the owner's explicit OK in this conversation.
