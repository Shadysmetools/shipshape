---
description: Record one QA scenario in a real browser with captions and narration (Playwright video + trace + screenshots + N pass / M fail).
argument-hint: "<plan.json or a plain description of the flow>"
---
Input: $ARGUMENTS
If it is a plan file: `python ${CLAUDE_PLUGIN_ROOT}/scripts/record.py <plan> --out qa-evidence/<name> --narrate`.
If it is a description: explore the page with the Playwright MCP (snapshot, stable selectors), write the plan JSON (template `${CLAUDE_PLUGIN_ROOT}/templates/qa-plan.example.json`), then record it. Run it a second time into `pass-2` and compare. Return the summary, the MP4 path, the captions file and the `[record] video a -> b` length line (idle stretches are trimmed to the plan's `video_type` cap; the original stays as `<name>.original.mp4`). Local/staging and test data only.
