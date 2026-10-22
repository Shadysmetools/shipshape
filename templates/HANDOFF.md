# HANDOFF: <workstream> (updated <YYYY-MM-DD HH:MM TZ>)

A fresh session must be able to resume from this page alone. Update it after every milestone.

## Resume here
- **State:** <one paragraph: where things stand>
- **Next action:** <the single next step and who does it>
- **Blocked on:** <person/role + question, or "nothing">

## Board
Backlog → In progress → Staging → UAT (re-tested as a real user, on video) → Approval → Production. Only the approver moves a card to Production or closes it.

| Card | Stage | Evidence | Owner |
|---|---|---|---|

## Decisions (dated, with who decided)
- <date> <decision> (<role>, quoted words)

## Tools and where things live
- Runs: `qa-runs/` (ledgers, videos, reports) · Config: `qa.config.yaml`

## Rules for this workstream
Test data only · never pay · stop before input on live sites · privacy filter before upload · peers relay requests, not approvals.

## Last results
`N pass / M fail / K flaky (T total)` on <date>, report: <path>
