---
description: Goal-driven QA loop - plan, run every scenario twice, record narrated video, verify + refute failures, file bugs, re-test after fixes, report and deliver, until the goal is met or a stop condition hits.
argument-hint: "<goal, e.g. signup to checkout works in EN and AR>"
---
Act as the `qa-lead` agent of this plugin for the goal: **$ARGUMENTS**

1. Read old runs: `python ${CLAUDE_PLUGIN_ROOT}/scripts/qa_history.py --root qa-runs`.
2. Read `qa.config.yaml` (or ask for base URL + allowed hosts; template `${CLAUDE_PLUGIN_ROOT}/templates/qa.config.example.yaml`).
3. Write the plan JSONs, then open or resume the ledger with `qa_loop.py start --goal "$ARGUMENTS" --plan ...`.
4. Run the full pipeline: `Workflow({scriptPath: "${CLAUDE_PLUGIN_ROOT}/workflows/full-qa.workflow.js", args: {goal: "$ARGUMENTS", plans: [...], url: "<base url>", allowHosts: [...], pluginRoot: "${CLAUDE_PLUGIN_ROOT}", agents: <output of crew.py roles>, external: <output of crew.py external>}})`, where both come from `python ${CLAUDE_PLUGIN_ROOT}/scripts/crew.py roles|external --config qa.config.yaml` (a team's own agents fill their roles; see `${CLAUDE_PLUGIN_ROOT}/docs/CUSTOMIZE-AGENTS.md`). Without the Workflow tool, follow the loop in the qa-lead agent by hand.
5. When `qa_loop.py status` says `wait-fix`, schedule the next check (for example `/loop 30m /qa-goal $ARGUMENTS`) instead of waiting.
Finish with `N pass / M fail / K flaky / B blocked`, the report.html path, open bugs and gates. Delivery stays dry-run unless the owner says send.
