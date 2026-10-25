# Timesheet method: measured hours from Claude Code logs

**Rule: never ship estimates as hours.** In one real case a 40 h estimate measured 23.94 h. Measure, keep the script next to the output, and write the method into the file.

The one exception is **human-equivalent mode** (below). It is a stated, rate-based figure built from what the logs show was done. It is always printed next to the measured figure, and it is booked only when the team has chosen it.

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

## Human-equivalent hours (`--mode human`)
Billing may need to reflect what a professional human tester with Odoo experience would spend, not how long the agent ran. The agent can run for 10 hours on something a person tests in 15 minutes. The default stays `--mode measured`.

1. **Count what was done in each block** from the transcripts (main and subagents) and git:
   - tool calls: test scenario runs (`record.py`, `full_qa.py`, `qa_loop.py`, `playwright test`, Odoo `--test-enable`), UI steps (browser click/type/navigate...), bugs filed (`gh issue create`, `/bug-creator`);
   - distinct files changed (Edit/Write);
   - commits in the block;
   - typed requests that mention a meeting.
   Identical repeated tool calls count once, because the agent re-running the same command is iteration, not new work.
2. **Minutes = sum(count x rate)**, raised to `block_minimum_minutes` (default 15) when something was done. A block where nothing was counted is 0.
3. **Share** the minutes across the block's tasks exactly like measured time, times the task's `task_multiplier` (ticket complexity, default 1). Book on the block's start day, round to the grid.
4. **Show the reasoning.** Daily and Evidence rows carry `counts x rates = minutes`, for example `1 test scenario run x 10 + 3 UI step x 1 + 1 bug filed x 15 = 28 min`. The Method sheet lists the rates file, every rate, the multipliers and the team's rule.

**Rates are per team.** Copy `templates/human-rates.example.json` and change the minutes, the regexes (what counts as a scenario, a step or a bug) and the multipliers; pass it with `--rates`. Each activity has a `source`: `tool` (a regex on the tool name, plus an optional regex on its input), `file`, `commit` or `request`. A broken rates file stops the run with one `rates error at activities.<name>.<field>` line.

**The team's rule** goes in `qa.config.yaml` (set by `/qa-setup`), and is written into the Summary and Method sheets and the analytic-lines JSON:
```yaml
timesheet:
  mode: human            # measured (default) | human
  rule: "Bill tester time for the scenarios run and bugs filed, not agent run time."
  rates: human-rates.json
```
Pass it with `--config qa.config.yaml`. `--mode` and `--rates` on the command line win over the config. Without a rule there, the rates file's `rule` is used.

**Both numbers are always shown.** Summary and Daily have Measured hours and Human-equivalent hours side by side; Evidence has both per block. Only "Booked hours", the Odoo Import sheet, the CSV and the analytic-lines JSON follow the chosen mode. The JSON carries `hours_basis: measured | human-equivalent`. In human mode, Totals match compares booked with the human-equivalent total, the 16 h day check uses the booked human figure, and one more check requires reasoning on every booked row.

Limits: a meeting is counted when a typed request mentions one; meetings held outside the tool and never mentioned are not seen. Regexes on tool input can over-count (a command that only *mentions* `record.py`). Review the Evidence sheet before sending.

## Choosing GAP
One rule per organisation, written in the Method sheet. 10, 15 or 20 minutes are supported; two projects measured with different rules gave numbers that could not be compared. Show all three when the rule is not agreed yet.

## Self-checks (Checks sheet)
Totals match (booked vs measured within rounding) · no negative hours · no day over 16 h including existing lines · no overlap with existing lines for the same day and task · the employee exists and is visible to the importing user (company access matters: an API user may see only one company's employees) · every block assigned · (human mode) every booked row has its reasoning.

## Odoo import
- "Odoo Import" sheet: Date | Project/Database ID | Project | Task/Database ID | Task | Employee | Description | Hours Spent. Values only: files opened from a chat app start in Protected View, which does not calculate formulas.
- `-analytic-lines.json`: `account.analytic.line` rows (`date, project_id, task_id, employee_id, name, unit_amount`), status NOT WRITTEN.
- Agree on ONE importer before anyone uploads; mark replacement files "supersedes <file>".
- One owner per number sent to a client: another session references the figure instead of recomputing it.
- Writing through an Odoo MCP happens only after the owner's explicit OK in the conversation, then read back.

## Privacy
The Evidence sheet keeps block times, allocation basis, masked requests and masked commit subjects. Employee ids and evidence are internal; never send the Evidence sheet to a client without review.
