---
name: report-results
description: Build the QA report - use for "show me the QA results", "make the report", "what is the trend". Offline self-contained HTML with pass/fail, videos, screenshots, console/network, bugs, load/security summary and a trend chart across old runs.
---
# Report
- HTML: `python ${CLAUDE_PLUGIN_ROOT}/scripts/qa_report_html.py <run> [--embed-video]` -> `<run>/report.html`. It opens offline; keep the folder together, or embed the video for a single file.
- Trend, flaky cases and the re-check list from old runs: `python ${CLAUDE_PLUGIN_ROOT}/scripts/qa_history.py --root qa-runs`.
- A markdown table from any results list: `python ${CLAUDE_PLUGIN_ROOT}/scripts/report.py results.json --md QA-REPORT.md`. A PASS without evidence counts as BLOCKED.

Always state `N pass / M fail` with flaky, blocked and not-checked counts. Never write "all green".
