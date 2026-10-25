---
description: Measure real working hours from Claude Code session logs + git commits for a project and produce an Excel timesheet and Odoo import rows, with self-checks. Never writes to Odoo without an explicit OK.
argument-hint: "<project or folder> [since YYYY-MM-DD] [until YYYY-MM-DD]"
---
Delegate to the `timesheet-agent` agent with: $ARGUMENTS. Core command: `python ${CLAUDE_PLUGIN_ROOT}/scripts/timesheet.py --project-dir <~/.claude/projects/...> --tasks tasks.json --gap 20 --tz <+HH:MM> --out <file>.xlsx`. Start from `${CLAUDE_PLUGIN_ROOT}/templates/tasks.example.json`. Human-equivalent hours (what a professional human tester would spend): add `--mode human --rates <rates>.json` (template `${CLAUDE_PLUGIN_ROOT}/templates/human-rates.example.json`) or `--config qa.config.yaml` with `timesheet.mode`/`timesheet.rule`.
