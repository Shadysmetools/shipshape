---
name: deliver-results
description: Send QA results automatically - use for "send the video to Telegram", "post the report to WhatsApp/Slack/email", or setting up per-project delivery in qa.config.yaml. Dry-run by default; real sends only to configured channels after the owner's OK.
---
# Deliver
1. Configure channels in `qa.config.yaml` (template `${CLAUDE_PLUGIN_ROOT}/templates/qa.config.example.yaml`). Secrets are env var NAMES only (or the OS keychain through `keyring`).
2. `python ${CLAUDE_PLUGIN_ROOT}/scripts/privacy.py scan <run>` and fix every hit.
3. `python ${CLAUDE_PLUGIN_ROOT}/scripts/notify.py <run> --config qa.config.yaml [--lang ar]` is a dry-run. Show it, then add `--send` after the owner says send.

Limits: Telegram 50 MB, WhatsApp 16 MB (sent as a link), email 20 MB. Bigger videos are compressed first, then sent as a link (`video_link_base`). Security details never leave the machine: the count only.

Knowcap (`type: knowcap`) uploads the video and report to the user's own project with their own `KNOWCAP_API_KEY` (prepare-upload, PUT, confirm-upload, then a move into the project and an optional folder) and returns a Knowcap link: a private project link, or a public share link with `share: true`. The privacy filter and `live: true` refuse the upload. Each file is uploaded once; a re-run reuses it.
