---
description: Set up ShipShape for this project as a short interview in the chat - project, voice profiles (one per consenting team member; ElevenLabs/OpenAI/free), video length, delivery channels, Odoo stages, timesheet rule. Collects API keys too, and saves them on this computer only.
argument-hint: "[resume]"
---
Run a friendly setup interview. Ask ONE question at a time in the chat, wait for the answer, then go on. Reply in the user's language (Arabic or English). Keep a short checklist of what's done, so `/qa-setup resume` (or a new session) can continue from the first unanswered step. Read the existing `qa.config.yaml` first and skip anything already set: confirm it in one line instead of asking again.

Before step 1, check what exists:
- `python ${CLAUDE_PLUGIN_ROOT}/scripts/keys.py list` shows saved key names (never values).
- `qa.config.yaml` in the project root; if missing, copy `${CLAUDE_PLUGIN_ROOT}/templates/qa.config.example.yaml`.

**Interview steps**
1. **Project**: the project name, and the staging URL to test (`base_url`). Is it a client's live site? (`live: true` stops before any input.) Set `allow_hosts` from the URL.
2. **Language**: narration in Arabic or English (`narrator.lang`).
3. **Voices**: build named voice profiles under `narrator.voices` (see the template). Start with a free `narrator` profile (edge, in the language from step 2). Then ask: "Should any videos be narrated in a team member's own voice?" Make one profile per team member who agrees, named after them (e.g. `sara`).
   - **Consent first**: only make a cloned-voice profile when the voice's owner has agreed to it narrating these videos. Ask "Has <name> agreed?" and skip the profile if the answer is not a clear yes. Never clone or pick a voice of someone who has not agreed.
   - **Provider per profile**: free (edge), ElevenLabs or OpenAI.
   - **ElevenLabs key** (once, for all ElevenLabs profiles): this is the user's own key; ShipShape has none and ships none. Ask for it and say plainly: "You can paste it here, or I can open a private window on your screen instead (safer: it never enters the chat history)." Both are fine; it's the user's choice.
     - Pasted in the chat: save it with `python ${CLAUDE_PLUGIN_ROOT}/scripts/keys.py set ELEVENLABS_API_KEY --stdin`, sending the key on stdin. Never repeat the key back, never write it into any file in the project, and never print it. After saving, say only "Saved on this computer (keychain or user folder)".
     - Window: run `python ${CLAUDE_PLUGIN_ROOT}/scripts/keys.py set ELEVENLABS_API_KEY` and tell the user to look for the "ShipShape needs a key" window.
   - **Voice per member**: run `python ${CLAUDE_PLUGIN_ROOT}/scripts/keys.py voices`, show the voice names, and ask which voice is that member's. Save its id under a per-member name with `keys.py set ELEVENLABS_VOICE_ID_<NAME> --stdin` (e.g. `ELEVENLABS_VOICE_ID_SARA`), and write the profile as `sara: {provider: elevenlabs, voice: {env: ELEVENLABS_VOICE_ID_SARA}, lang: ar}`. Never put the id itself in the config. If they pick a library voice, warn that it needs a paid ElevenLabs plan through the API; without one, ShipShape falls back to the free voice and says so.
   - OpenAI: the same key flow with `OPENAI_API_KEY`; the profile voice is an OpenAI voice name (e.g. `alloy`).
   - **Default**: ask which profile narrates when nobody says otherwise, and set `narrator.default_voice`. Tell them any run can pick another with `--voice <profile>` (`record.py`, `slides_video.py`, `narrator.py report`).
4. **Video length**: the maximum minutes per video (e.g. 1 for a simple case, 4 at most). Record it as `video.max_seconds` in the config.
5. **Delivery**: where results go: Telegram, WhatsApp, Slack, email, Knowcap, or none for now. For each one chosen, enable it in `notify:`, ask for the non-secret fields (chat id, recipients), and collect its key the same way as step 3 (chat or window) under the env name in the config (e.g. `TELEGRAM_BOT_TOKEN`). Deliveries stay dry-run until the owner says "send".
   - **Knowcap**: uploads the video and report to the user's own Knowcap project and returns a Knowcap link that the other channels' messages then carry. Ask for the `project_id` (and an optional `folder_id`), and whether to make a public share link (`share: true` is a publish, so it needs the owner's OK; the default is false: a private project link). Collect the user's own key as `KNOWCAP_API_KEY` (Knowcap > Settings > API Keys) the same way as step 3. ShipShape ships no key of its own. Say plainly that uploads are refused when the privacy filter finds anything, and for `live: true` client sites.
6. **Odoo** (if they test Odoo): the Odoo URL and database, and the stage names that should start QA (e.g. "Pending Internal Testing") and where to move a ticket on pass or fail. Save them under `odoo:` in the config. Say plainly that automatic starts from a stage are coming (issue #1) and that, until then, their agent can run `/qa-goal` with the ticket's analysis.
7. **Timesheet**: how they count billable hours. Is it measured agent time, or human-equivalent time (what a professional human tester would spend)? Write their rule in their own words under `timesheet.rule` (issue #5).
8. **Check**: run `python ${CLAUDE_PLUGIN_ROOT}/scripts/narrator.py voices --config qa.config.yaml` (profiles, no ids printed), `python ${CLAUDE_PLUGIN_ROOT}/scripts/keys.py check --config qa.config.yaml` and `python ${CLAUDE_PLUGIN_ROOT}/scripts/doctor.py`. Show the results as plain lines: what's ready, and what's still missing.
9. **Summary**: list every setting in plain words (never a key), say what they can run now (`/qa-goal "..."`), and offer a first test run.

Rules: never show, log or commit a key value; the config holds key NAMES only. If a step fails, say what failed in one line and keep going with the next step.
Arguments: $ARGUMENTS
