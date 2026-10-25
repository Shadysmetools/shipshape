---
description: Set up ShipShape for this project as a short interview in the chat - project, voice (ElevenLabs/OpenAI/free), video length, delivery channels, Odoo stages, timesheet rule. Collects API keys too, and saves them on this computer only.
argument-hint: "[resume]"
---
Run a friendly setup interview. Ask ONE question at a time in the chat, wait for the answer, then go on. Reply in the user's language (Arabic or English). Keep a short checklist of what's done, so `/qa-setup resume` (or a new session) can continue from the first unanswered step. Read the existing `qa.config.yaml` first and skip anything already set: confirm it in one line instead of asking again.

Before step 1, check what exists:
- `python ${CLAUDE_PLUGIN_ROOT}/scripts/keys.py list` shows saved key names (never values).
- `qa.config.yaml` in the project root; if missing, copy `${CLAUDE_PLUGIN_ROOT}/templates/qa.config.example.yaml`.

**Interview steps**
1. **Project**: the project name, and the staging URL to test (`base_url`). Is it a client's live site? (`live: true` stops before any input.) Set `allow_hosts` from the URL.
2. **Language**: narration in Arabic or English (`narrator.lang`).
3. **Voice**: free (edge), ElevenLabs or OpenAI (`narrator.provider`).
   - **ElevenLabs key**: ask for the API key and say plainly: "You can paste it here, or I can open a private window on your screen instead (safer: it never enters the chat history)." Both are fine; it's the user's choice.
     - Pasted in the chat: save it with `python ${CLAUDE_PLUGIN_ROOT}/scripts/keys.py set ELEVENLABS_API_KEY --stdin`, sending the key on stdin. Never repeat the key back, never write it into any file in the project, and never print it. After saving, say only "Saved on this computer (keychain or user folder)".
     - Window: run `python ${CLAUDE_PLUGIN_ROOT}/scripts/keys.py set ELEVENLABS_API_KEY` and tell the user to look for the "ShipShape needs a key" window.
   - Then run `python ${CLAUDE_PLUGIN_ROOT}/scripts/keys.py voices`, show the voice names, and ask which one should narrate. Save the voice id with `keys.py set ELEVENLABS_VOICE_ID --stdin` (an id is not secret, but it lives with the key). If they pick a library voice, warn that it needs a paid ElevenLabs plan through the API.
   - OpenAI: the same flow with `OPENAI_API_KEY`.
4. **Video length**: the maximum minutes per video (e.g. 1 for a simple case, 4 at most). Record it as `video.max_seconds` in the config.
5. **Delivery**: where results go: Telegram, WhatsApp, Slack, email, or none for now. For each one chosen, enable it in `notify:`, ask for the non-secret fields (chat id, recipients), and collect its key the same way as step 3 (chat or window) under the env name in the config (e.g. `TELEGRAM_BOT_TOKEN`). Deliveries stay dry-run until the owner says "send".
6. **Odoo** (if they test Odoo): the Odoo URL and database, and the stage names that should start QA (e.g. "Pending Internal Testing") and where to move a ticket on pass or fail. Save them under `odoo:` in the config. Say plainly that automatic starts from a stage are coming (issue #1) and that, until then, their agent can run `/qa-goal` with the ticket's analysis.
7. **Timesheet**: how they count billable hours. Is it measured agent time, or human-equivalent time (what a professional human tester would spend)? Write their rule in their own words under `timesheet.rule` (issue #5).
8. **Check**: run `python ${CLAUDE_PLUGIN_ROOT}/scripts/keys.py check --config qa.config.yaml` and `python ${CLAUDE_PLUGIN_ROOT}/scripts/doctor.py`. Show the results as plain lines: what's ready, and what's still missing.
9. **Summary**: list every setting in plain words (never a key), say what they can run now (`/qa-goal "..."`), and offer a first test run.

Rules: never show, log or commit a key value; the config holds key NAMES only. If a step fails, say what failed in one line and keep going with the next step.
Arguments: $ARGUMENTS
