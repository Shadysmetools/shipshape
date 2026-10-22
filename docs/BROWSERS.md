# Which browser engine, when

ShipShape bundles two browser MCP servers (pinned in `.mcp.json`) plus a recording script and a desktop layer.

**Recommendation:** use **Playwright** for everything that should be repeatable: tests, recordings, loops, cross-browser runs, CI. Reach for **Chrome DevTools MCP** when you need to *diagnose* (why did it fail or why is it slow) or when the flow needs the user's *real signed-in Chrome* (passkeys, OAuth/SSO). Use the **desktop** layer only for things outside a browser.

## Decision table

| Task | Engine | Why |
|---|---|---|
| Scripted regression, goal loop, CI | Playwright script (`record.py`) | deterministic, isolated profile, two passes, native video + trace |
| Exploring a page to write selectors | Playwright MCP `browser_snapshot` | accessibility tree with stable refs, cheap in context |
| Cross-browser check (Firefox, WebKit, Edge) | Playwright (`--browser firefox/webkit`) | one API, three engines |
| Video evidence with captions and voice | Playwright (`record.py --narrate`) or Playwright MCP `browser_start_video` / `browser_video_chapter` (`--caps=devtools`) | native recording |
| Trace for a flaky failure | Playwright `trace.zip` (`npx playwright show-trace`) | DOM snapshots per step |
| Console errors / failed requests after a FAIL | Chrome DevTools MCP `list_console_messages`, `list_network_requests`, `get_network_request` | full request/response detail |
| "It is slow" | Chrome DevTools MCP `performance_start_trace` / `performance_stop_trace` / `performance_analyze_insight` | real performance insights |
| Page quality (performance, a11y, SEO) | Chrome DevTools MCP `lighthouse_audit` | Lighthouse in place |
| Memory leak | Chrome DevTools MCP `take_heapsnapshot` | heap snapshots |
| Passkeys, OAuth, SSO, a session only the user has | Chrome DevTools MCP with `--autoConnect` (user's Chrome, user present) | real signed-in browser |
| Chrome extension surface | Chrome DevTools MCP extension tools | pipe connection support |
| Native app, OS dialog, file picker, Electron | Claude computer use, else `desktop.py` | outside the browser |

## How they are wired
- Playwright MCP: `npx @playwright/mcp@0.0.83 --caps=devtools --isolated --output-dir ${SMEKIT_EVIDENCE_DIR:-qa-evidence}/mcp --save-session`. `--caps=devtools` adds video/tracing tools; `--isolated` keeps each session in a clean in-memory profile (no leaked cookies, no account memory confounding results).
- Chrome DevTools MCP: `npx chrome-devtools-mcp@1.10.1 --isolated --usageStatistics=false`. For a signed-in session, add a user-level server with `--autoConnect` (Chrome 144+, remote debugging enabled in `chrome://inspect/#remote-debugging`) or `--browserUrl http://127.0.0.1:9222`. Do this only on your own machine, with you present.

## Pitfalls we hit
- Keep an MCP browser session under about 15 interactions; long sessions bloat context. Split flows.
- Test as the real user, from the link they actually received (query keys, locale, account preferences change results).
- Account preferences and memory leak into results (a "reply in English" preference failed an Arabic test). Grade only on a clean test account.
- In-page masking scripts may run after first paint on some profiles; sanitize the video too.
