---
description: Record one QA scenario in a real browser with captions and narration (Playwright video + trace + screenshots + N pass / M fail).
argument-hint: "<plan.json or a plain description of the flow>"
---
Input: $ARGUMENTS
If it is a plan file: `python ${CLAUDE_PLUGIN_ROOT}/scripts/record.py <plan> --out qa-evidence/<name> --narrate` (add `--voice <profile>` to pick a voice profile from `narrator.voices`; default `narrator.default_voice`).
If it is a description: explore the page with the Playwright MCP (snapshot, stable selectors), write the plan JSON (template `${CLAUDE_PLUGIN_ROOT}/templates/qa-plan.example.json`), then record it. Run it a second time into `pass-2` and compare. Return the summary, the MP4 path and the captions file. Local/staging and test data only.
