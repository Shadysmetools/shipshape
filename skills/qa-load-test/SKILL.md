---
name: qa-load-test
description: Load, stress, soak and spike testing with p95/p99/error-rate thresholds and a chart - use for "load test", "can it handle N users", "performance check" on local or staging hosts only.
---
# Load test
`python ${CLAUDE_PLUGIN_ROOT}/scripts/load_test.py --url <url> --allow-host <host> --profile smoke|ramp|soak|spike [--scale 0.5] [--p95-ms 500 --p99-ms 1000 --max-error-rate 0.01] --out <dir>`

Writes `load.json` (stats + thresholds as `N pass / M fail`) and `load.svg`. For heavier load use `--engine k6` with `${CLAUDE_PLUGIN_ROOT}/templates/load/k6-profile.js`.

It refuses hosts not in `--allow-host` and hosts that look like production. Tell a shared staging's owner before a soak or spike.
