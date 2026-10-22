# Timesheet method: measured hours from Claude Code logs

**Rule: never ship estimates as hours.** In one real case a 40 h estimate measured 23.94 h. Measure, keep the script next to the output, and write the method into the file.

## What is measured
Session activity: the time Claude Code was being worked with (the developer typing, Claude and its subagents working). It is not keyboard time, and it does not include meetings or calls outside the tool; add those separately and label them.

## Algorithm (`scripts/timesheet.py`)
1. Files: `~/.claude/projects/<slug>/<session>.jsonl` plus `<session>/subagents/*.jsonl`.
2. Lines counted: `user` and `assistant`. Always excluded: `queue-operation` (messages queued into an idle session; counting them inflated one total by about 30%).
3. **Sort** each file's timestamps. Lines are not guaranteed to be in time order (resumed sessions, merged logs); pairing unsorted lines once produced negative hours. A regression test guards this.
4. Within a file, consecutive lines at most GAP apart form an active interval.
5. Union the intervals of all files: parallel subagents count once.
6. Blocks: cut the union where the break is longer than GAP.
7. Attach typed requests and commits (±5 min) to each block; map each block to a task by regex rules (first match wins per item, shares are proportional), a manual map by block start, or exclude it (timesheet admin and non-project work). A fragment under 10 min with no signal inherits the nearest same-day block's task. Anything still unassigned fails a check.
8. Split by local calendar day (configurable time zone), round each (day, task) to 0.25 h.

## Choosing GAP
One rule per organisation, written in the Method sheet. 10, 15 or 20 minutes are supported; two projects measured with different rules gave numbers that could not be compared. Show all three when the rule is not agreed yet.

## Self-checks (Checks sheet)
Totals match (booked vs measured within rounding) · no negative hours · no day over 16 h including existing lines · no overlap with existing lines for the same day and task · the employee exists and is visible to the importing user (company access matters: an API user may see only one company's employees) · every block assigned.

## Odoo import
- "Odoo Import" sheet: Date | Project/Database ID | Project | Task/Database ID | Task | Employee | Description | Hours Spent. Values only: files opened from a chat app start in Protected View, which does not calculate formulas.
- `-analytic-lines.json`: `account.analytic.line` rows (`date, project_id, task_id, employee_id, name, unit_amount`), status NOT WRITTEN.
- Agree on ONE importer before anyone uploads; mark replacement files "supersedes <file>".
- One owner per number sent to a client: another session references the figure instead of recomputing it.
- Writing through an Odoo MCP happens only after the owner's explicit OK in the conversation, then read back.

## Privacy
The Evidence sheet keeps block times, allocation basis, masked requests and masked commit subjects. Employee ids and evidence are internal; never send the Evidence sheet to a client without review.
