---
description: Build the offline HTML report for a QA run (pass/fail table, videos, screenshots, console/network, bugs, trend) and optionally a spoken summary.
argument-hint: "[qa-runs/<run>] [--narrate en|ar]"
---
Run dir: $ARGUMENTS (default: the newest under qa-runs, `python ${CLAUDE_PLUGIN_ROOT}/scripts/qa_loop.py resume`).
`python ${CLAUDE_PLUGIN_ROOT}/scripts/qa_report_html.py <run>`; spoken summary: `python ${CLAUDE_PLUGIN_ROOT}/scripts/narrator.py report <run> --lang en`. Open report.html in a browser to check it before sharing.
