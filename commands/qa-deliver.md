---
description: Deliver a QA run (summary, video, report) to the channels listed in qa.config.yaml - Telegram, WhatsApp, Slack, email, webhook, Knowcap. Dry-run unless the owner says send.
argument-hint: "[qa-runs/<run>] [--send]"
---
1. Privacy first: `python ${CLAUDE_PLUGIN_ROOT}/scripts/privacy.py scan <run>`; fix every hit.
2. Keys: `python ${CLAUDE_PLUGIN_ROOT}/scripts/keys.py check --config qa.config.yaml`. For each MISSING key run `python ${CLAUDE_PLUGIN_ROOT}/scripts/keys.py set <NAME>`: a masked window opens on the user's screen and the key is saved on their computer only. Never ask the user to paste a key into the chat.
3. Dry-run: `python ${CLAUDE_PLUGIN_ROOT}/scripts/notify.py <run> --config qa.config.yaml` and show the user what would be sent.
4. Add `--send` only when the owner said "send" in this conversation. Channels not in the config are refused. Security findings go out as a count only.
5. Knowcap: the channel runs first, and its link (`Knowcap link: ...`) goes into the other channels' messages. Put that link in the ticket note. The upload is refused on any privacy hit or for `live: true`. A run with security findings never gets a public share link.
Arguments: $ARGUMENTS
