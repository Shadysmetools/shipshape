---
description: Load test a local or staging URL with ramp, soak or spike profiles and p95/p99/error-rate thresholds (refuses hosts that are not allow-listed).
argument-hint: "<url> [ramp|soak|spike|smoke]"
---
Delegate to the `qa-load-tester` agent with: $ARGUMENTS. Command core: `python ${CLAUDE_PLUGIN_ROOT}/scripts/load_test.py --url <url> --allow-host <host> --profile <profile> --out qa-runs/load-<date>`.
