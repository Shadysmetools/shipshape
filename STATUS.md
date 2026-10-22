# ShipShape status (what works right now)

Updated as features land. "Works" = run here against the local example app with fake data.

| Feature | Command | Status |
|---|---|---|
| Record a scenario (video + voice + captions + trace) | `python scripts/record.py examples/demo-app/plans/signup.json --out qa-evidence/signup --narrate` (serve the demo first: `python -m http.server 8765 --bind 127.0.0.1 --directory examples/demo-app`) | works |
| Never-pay / stop-before-input guards | `examples/demo-app/plans/pay-guard.json` | works |
| Goal loop with ledger, 2 passes, FLAKY | `python scripts/qa_loop.py start/round/status/bug/gate/attach` | works |
| One-command pipeline | `python scripts/full_qa.py "Signup works" --plan examples/demo-app/plans/signup.json --config examples/demo-app/qa.config.yaml --url http://127.0.0.1:8765/ --allow-host 127.0.0.1 --load smoke --narrate` | works |
| Offline HTML report + trend | `python scripts/qa_report_html.py qa-runs/<run>` | works |
| Old runs: trend / flaky / re-check | `python scripts/qa_history.py --root qa-runs` | works |
| Delivery (Telegram, WhatsApp, Slack, email, webhook) | `python scripts/notify.py qa-runs/<run> --config examples/demo-app/qa.config.yaml` | dry-run works; real sends tested with mocked HTTP only |
| Load test (ramp/soak/spike/smoke) | `python scripts/load_test.py --url http://127.0.0.1:8765/ --allow-host 127.0.0.1 --profile smoke` | works (native engine); k6 engine untested here (k6 not installed) |
| Security scan | `python scripts/security_scan.py --repo . --url http://127.0.0.1:8765/ --allow-host 127.0.0.1` | works; gitleaks / pip-audit / osv-scanner are used when installed |
| Narrator (EN/AR), spoken report, mix with ducking | `python scripts/narrator.py report qa-runs/<run> --lang ar` | works (edge-tts) |
| Slides video from screenshots | `python scripts/slides_video.py scenes.json --out demo.mp4` | works |
| Desktop control (gated) | `python scripts/desktop.py run steps.json --config qa.config.yaml --dry-run` | dry-run + mock tested; real-desktop smoke test is gated (SMEKIT_DESKTOP_SMOKE=1) |
| Timesheet from Claude Code logs | `python scripts/timesheet.py --project-dir ... --tasks templates/tasks.example.json --out hours.xlsx` | works |
| Odoo pre-deploy check | `python scripts/odoo_check.py <module> --base origin/<branch>` | works |
| Plugin install (/plugin marketplace add) | see QUICKSTART.md | see README "Verified" |

## Lessons turned into behaviour (P0 rows of docs/LESSONS-TO-BEHAVIOUR.md)
Tests: `tests/test_lessons_p0.py` (one test per row).

| Row | Done | Where | Deferred part (reason) |
|---|---|---|---|
| QA-01 evidence before done | yes | Stop hook, qa-lead "pushed, unverified" | - |
| QA-02 counts from finished runs | yes | `report.py` refuses a results.json without `finished_at` | - |
| QA-03 refuter before filing | yes | full-qa workflow Refute phase precedes Report/Deliver; `qa_loop` next=verify-refute | - |
| QA-04 revert proof | rule | qa-automation-tester, BUG-LOG template; the kit's own timesheet test was mutation-proven | automatic revert runner deferred (needs per-project build knowledge) |
| QA-07 positive control | yes | `security_scan.secrets` plants a synthetic key first; else UNKNOWN | - |
| QA-13 queued lock + commit at start/end | yes | FIFO ticket queue in `stack_lock.py`; `record.py` head_start/head_end/mixed | re-running reds on the final tip is left to the agent (documented) |
| DL-01 retry, size timeout, no resend | yes | `notify.with_retry`, persistent step journal | storing provider message ids deferred (providers differ; the content key covers resend) |
| DL-05 singleton per stream + dedupe store | yes | per-channel queue lock + `~/.cache/smekit/delivery-sent.json` | - |
| SEC-01 never read secrets | yes | prompt hooks on Read(.env, secrets/) and cat/type/Get-Content | - |
| SEC-05 no input on payment/live pages | yes | `record.refuse_reason` (checkout/payment paths, live sites) | - |
| TS-02 no negative/overlapping intervals | yes | asserts in `timesheet.measure` | counting out-of-order stamps in the workbook deferred (cosmetic) |
| OD-01 neutralize + send-off default | yes (static) | `odoo_check.py` send-off-default + neutralize checks | live pre-test read of send switches on a staging DB deferred (needs DB access; runbook section A covers it manually) |
| PR-01 one promotion at a time | rule | odoo-expert + ODOO-PLAYBOOK | enforcement deferred (no deploy tooling in the kit) |
| WIN-02 BOM / zero-width | yes | `notify.load_config` (utf-8-sig), `notify.clean` | key-shape validation at startup deferred (provider formats change) |
| CO-01 owner's own words only | yes | agent hooks on Odoo writes, sends, merges, deletes | - |
