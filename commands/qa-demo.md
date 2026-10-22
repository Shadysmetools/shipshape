---
description: Produce a polished narrated demo or tutorial video of a feature (scripted scenes, captions, EN or AR voice, .srt).
argument-hint: "<feature or flow to demo> [en|ar]"
---
Delegate to the `qa-demo-video-producer` agent with: $ARGUMENTS. Or run the workflow: `Workflow({scriptPath: "${CLAUDE_PLUGIN_ROOT}/workflows/demo.workflow.js", args: {feature: "$ARGUMENTS", pluginRoot: "${CLAUDE_PLUGIN_ROOT}"}})`.
