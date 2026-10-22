---
name: qa-goal-loop
description: Goal-driven autonomous QA - use when asked to test a web app until a goal holds ("make sure signup to checkout works", "QA this release", "keep testing until it passes"). Plans scenarios, runs them twice with narrated video, verifies and refutes failures, files bugs, re-tests after fixes, with a durable ledger and stop conditions.
---
# QA goal loop
State lives in `qa-runs/<date>-<goal>/ledger.json`; it survives restarts.

Quick path: `/qa-goal "<goal>"`. Script layer only: `python ${CLAUDE_PLUGIN_ROOT}/scripts/full_qa.py "<goal>" --plan <p.json> --config qa.config.yaml`.

Loop: `qa_loop.py status` -> do `next` (`run-round` | `verify-refute` | `file-bugs` | `wait-fix` | `stop`) -> repeat.

Stop conditions: goal met (no fail, flaky, blocked or open bug), max rounds, budget minutes, no progress (same failures twice with no fix), or an open human gate.

Pausing for a fix: schedule with `/loop` (for example `/loop 30m /qa-goal <goal>`) rather than waiting in a turn.

Details: the `qa-lead` agent; rules in `${CLAUDE_PLUGIN_ROOT}/docs/OPERATING-RULES.md`; orchestration in `${CLAUDE_PLUGIN_ROOT}/workflows/full-qa.workflow.js`.
