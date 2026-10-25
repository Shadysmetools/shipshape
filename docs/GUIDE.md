# ShipShape guide

## Concepts
- **Goal**: one sentence a user would say ("a new customer can sign up and pay with a test card in Arabic"). The loop runs until it holds or a stop condition hits.
- **Plan**: a JSON list of browser steps with `say` (caption + voice) and `case` (a result row). One plan per scenario.
- **Round**: every plan runs twice (two independent passes). If both pass, the case passes; if both fail, it fails; if they disagree, it is FLAKY.
- **Ledger**: `qa-runs/<date>-<goal>/ledger.json` holds rounds, bugs (suspected → verified/refuted → filed → fixed → retest-pass), human gates, load and security summaries, and elapsed time. Every command reads and writes it, so a crash or a new session resumes exactly.
- **Stop conditions**: goal met, max rounds, budget minutes, no progress (same failures twice with no fix in between), or an open human gate (a payment page, input on a live site, an approval).
- **Two-agent bar**: a failure becomes a bug only after a verifier reproduces it and the refuter fails to kill it.
- **Evidence**: video with voice and captions, `.srt`, Playwright trace, screenshots, console/network lists, and the HTML report.
- **Video length**: after recording, `scripts/video_trim.py` finds still stretches (ffmpeg `freezedetect`) and slow steps (`type`, `wait`) that no caption covers, and plays them 8x faster or cuts them. The `.srt` is shifted to match. Each video type has a cap (`video.types`: simple 60 s, standard 150 s, walkthrough 240 s; `video.max_seconds` is a ceiling for all). If the speed-up is not enough, idle stretches are cut. Real activity is never cut: a video still over its cap is marked "over cap" in the report, and the fix is to split the plan. The untouched recording stays next to it as `<name>.original.mp4` with `captions.original.srt`.

## The crew
| Agent | Role | Writes? |
|---|---|---|
| qa-lead | plans, dispatches, runs the loop, reports | ledger, plans |
| qa-code-reviewer | reviews the diff before testing | no |
| qa-security-reviewer | OWASP-style review, secrets, dependencies, passive headers | private findings file |
| qa-automation-tester | writes and runs Playwright scenarios twice | evidence |
| qa-load-tester | ramp/soak/spike with thresholds | load results |
| qa-live-regression-recorder | read-only staging/live regression + DevTools evidence | evidence |
| qa-desktop-tester | native apps/dialogs, gated | evidence + action log |
| qa-demo-video-producer | demo and tutorial videos | videos |
| qa-refuter | tries to kill every claim | verdicts only |
| timesheet-agent | measured hours → Excel + Odoo rows | files only |
| odoo-expert | Odoo modules, migrations, staging safety, deploys | code (with review) |

## Workflows
`workflows/full-qa.workflow.js` runs: review + security (parallel) → automated ×2 → load → live regression → refute (verify, then refute, per failure) → report → dry-run delivery. `demo.workflow.js` covers script → capture → privacy + viewer review. `regression-loop.workflow.js` repeats rounds until stopped. Run them from Claude Code with the Workflow tool, passing `pluginRoot` (the commands do this for you).

## Rules
See `OPERATING-RULES.md`. In short: test data only, never pay, stop before input on live sites, privacy filter before upload, N pass / M fail with evidence, owner approval for writes and sends, timeouts everywhere.

## FAQ
- **The video has no voice.** edge-tts needs network. The run still produces captions; re-run with network, and cached clips are reused.
- **The video is too long / over cap.** Pick a longer `video_type` in the plan, or split the scenario into two plans. Try a dry run: `python scripts/video_trim.py <video.mp4> --srt captions.srt --type simple --dry-run`.
- **A case is FLAKY.** Look at both passes in the report; the refuter checks timing, waits and data. Fix the test or the product, then it must pass twice.
- **The loop stopped with "no progress".** The same cases failed in two rounds with no fix recorded. Mark a fix with `qa_loop.py bug --id B1 --status fixed`, or change the plan.
- **A human gate is open.** Read the reason (for example the never-pay rule). Do the step yourself or approve it, then `qa_loop.py gate --close G1`.
- **Sending to Telegram does nothing.** Delivery is dry-run until you pass `--send`, the channel is enabled in `qa.config.yaml`, and its env var is set.
- **Desktop control refuses.** Enable it per project (`desktop.enabled: true`) and allow-list the app. Banking, payment and password apps are always refused.
