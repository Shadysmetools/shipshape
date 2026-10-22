---
description: Run the QA pipeline once from the terminal layer (history, security, every plan twice with video, optional load, offline report, dry-run delivery).
argument-hint: "<goal> [plan.json ...]"
---
Run once, no agent loop: `python ${CLAUDE_PLUGIN_ROOT}/scripts/full_qa.py "<goal>" --plan <plan.json> [--plan ...] --config qa.config.yaml --url <base url> --allow-host <host> --narrate`
Arguments given: $ARGUMENTS. If no plan exists yet, write one first (format `${CLAUDE_PLUGIN_ROOT}/templates/qa-plan.example.json`). Report the RESULT line, the report path and anything blocked.
