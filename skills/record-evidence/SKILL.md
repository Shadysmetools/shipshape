---
name: record-evidence
description: Record a browser test with video evidence - use for "test X and record it", "record the signup flow", "video proof of this bug", or any QA step that needs a captioned, narrated recording, trace and screenshots with an honest N pass / M fail.
---
# Record a scenario
1. Plan JSON (template `${CLAUDE_PLUGIN_ROOT}/templates/qa-plan.example.json`). Steps: `goto | click | fill | type | select | check | press | wait | screenshot | expect_text | expect_visible | expect_url`. `say` = caption + narration; `case` = one result row.
2. `python ${CLAUDE_PLUGIN_ROOT}/scripts/record.py plan.json --out <dir> --narrate [--browser firefox|webkit] [--total-timeout 900]`
3. Outputs: `<name>.mp4` (video + voice), `captions.srt`, `trace.zip` (`npx playwright show-trace`), screenshots, `results.json` (with console/network), `QA-REPORT.md`.

Built-in guards: hosts outside `allow_hosts` are blocked, payment steps are refused, live sites stop before input, emails on screen are masked. Narration is synthesized before the run, so the video has no pauses.

A verdict that counts needs two passes (see the `qa-automation-tester` agent).
