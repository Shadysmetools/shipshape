---
description: Deliver a QA run (summary, video, report) to the channels listed in qa.config.yaml - Telegram, WhatsApp, Slack, email, webhook. Dry-run unless the owner says send.
argument-hint: "[qa-runs/<run>] [--send]"
---
1. Privacy first: `python ${CLAUDE_PLUGIN_ROOT}/scripts/privacy.py scan <run>`; fix every hit.
2. Dry-run: `python ${CLAUDE_PLUGIN_ROOT}/scripts/notify.py <run> --config qa.config.yaml` and show the user what would be sent.
3. Add `--send` only when the owner said "send" in this conversation. Channels not in the config are refused. Security findings go out as a count only.
Arguments: $ARGUMENTS
