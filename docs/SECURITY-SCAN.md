# Secret and PII scan (before publishing)

**Latest scan: 2026-10-24 (v0.1.1).** Scope: every tracked and untracked-but-not-ignored file (`git ls-files` plus `git ls-files --others --exclude-standard`, 134 files; 133 text, 1 PNG icon). Ignored folders (`qa-runs/`, `qa-evidence/`, `docs/media/tutorial/capture/`, `docs/media/tutorial/build/`, logs, `.env*`) are never committed and were excluded.

## Tools
- **gitleaks:** not installed on the build machine, so the regex sweep below was used. If gitleaks is installed, run `gitleaks detect --no-banner --redact -s .` before every release.
- **Regex sweep:** `python scripts/privacy.py scan --deny <deny-list kept outside the repo> <files>`. Patterns: private keys, JWTs, GitHub/OpenAI/Anthropic/AWS/Google/Slack/Telegram tokens, bearer tokens, `password=`/`api_key=` assignments, credentials in URLs, emails, phone numbers, home folders, and (since 0.1.1) absolute paths on **any** Windows drive letter such as `E:\<company>-dev\repo\`.
- **Deny-list:** 23 private terms (client and company names, people's names, internal branch and build names, a chat id, the account login). Kept outside the repo; the scan prints term indexes only.
- **Extra greps:** client and partner names (case-sensitive), local user paths, session ids, scratch paths.

## Result: 0 real findings
The sweep reports 30 hits, all deliberate synthetic fixtures or documentation of the patterns themselves:
- `tests/test_privacy_report.py`, `tests/test_eval_fixes.py`, `tests/test_lessons_p0.py`: the strings the privacy filter and the hook guard are tested against (`jane.doe@acme-corp.io`, `+20 100 123 4567`, `ghp_AAAA…`, a sample JWT, `C:\Users\jdoe`, `E:\acme-dev\kit`, `password = hunter2hunter2`).
- `scripts/privacy.py`: the examples inside the pattern comments.
- `docs/SECURITY-SCAN.md`: this file, quoting those fixtures.

Deny-list terms: 0 hits. Client names, local user paths and session ids: 0 hits (the only `*-dev\` path in the tree is the synthetic `E:\acme-dev\kit` fixture in a test).

## Fixed in 0.1.1
- The evaluator found two tutorial manifests with an absolute local path naming the internal repo folder; `privacy.py` had missed them because its path rule only knew `C:\Users`, `/home` and `/Users`. The manifests now store relative paths, the rule covers any drive letter, and a regression test guards it.
- Documentation placeholders (`C:\path\to\…`, `C:\proj\…`, `C:\...\tool.exe`) are allow-listed so the scanner stays quiet on examples without hiding real paths.

## Earlier scan (2026-10-22, v0.1.0)
118 files, 10 fixture hits, 0 real findings at the time; the manifest leak above was created after that scan by the tutorial build and caught by the external evaluation.

## Video frames
Every frame of the bundled videos is rendered from text the kit controls: plan `say` lines, scene and caption text, and the local demo page with fake data. Those sources are scanned above.

## Known items (not leaks)
- Commit author metadata is set by whoever commits; it is not part of the file scan.
- `.claude-plugin/*.json` and the README name the publisher and the GitHub owner on purpose.

## Re-run
```bash
python scripts/privacy.py scan --deny /path/outside/repo/deny.txt $(git ls-files --cached --others --exclude-standard)
```
