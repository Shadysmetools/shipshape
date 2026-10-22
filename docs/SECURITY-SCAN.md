# Secret and PII scan (before publishing)

**Date:** 2026-10-22 · **Scope:** every file that git would add (`git ls-files --others --exclude-standard`, 118 files, of which 117 are text and 1 is the PNG icon). Ignored folders (`qa-runs/`, `qa-evidence/`, `docs/media/tutorial/capture/`, `docs/media/tutorial/build/`, logs, `.env*`) were excluded because they are never committed.

## Tools
- **gitleaks:** not installed on the build machine, so the regex sweep below was used instead. If gitleaks is installed, run `gitleaks detect --no-banner --redact -s .` before every release.
- **Regex sweep:** `python scripts/privacy.py scan --deny <deny-list kept outside the repo> <files>`. Patterns: private keys, JWTs, GitHub/OpenAI/Anthropic/AWS/Google/Slack/Telegram tokens, bearer tokens, `password=`/`api_key=` assignments, credentials in URLs, emails, phone numbers and user home paths.
- **Deny-list:** 24 private terms covering client and company names, people's names, internal branch and build names, a chat id and the account login. It is kept outside the repo, and the scan prints term indexes only.
- **Extra greps:** absolute local paths, session ids, local scratch paths, and case-sensitive client and partner names.

## Result: 0 real findings
The sweep reports 10 hits, all deliberate synthetic fixtures:
- `tests/test_privacy_report.py`: 6 hits on the strings the privacy filter is tested against (`jane.doe@acme-corp.io`, `+20 100 123 4567`, `ghp_AAAA…`, a sample JWT, `C:\Users\jdoe`, `password = hunter2hunter2`).
- `scripts/privacy.py`: 4 hits on the documentation examples inside its own regex comments.

Deny-list terms: 0 hits. Local paths and session ids: 0 hits.

## Fixed during the scan
- Telegram `chat_id`, WhatsApp `phone_number_id` and the Twilio sender in `templates/qa.config.example.yaml` and `examples/demo-app/qa.config.yaml` are now `<PLACEHOLDER>` values.
- The phone-number pattern was tightened, because SVG path numbers in the tutorial script were false positives. A regression check covers international, NANP and local mobile formats.

## Video frames
Every frame of the bundled videos is rendered from text the kit controls: plan `say` lines, scene and caption text, and the local demo page with fake data. Those sources are scanned above. The tutorial's own frame and caption scan is recorded by the tutorial build (`docs/media/tutorial/`).

## Known items (not leaks)
- Commit author metadata is set by whoever commits; it is not part of the file scan.
- `.claude-plugin/*.json` names "SMEtools" as the publisher on purpose.

## Re-run
```bash
python scripts/privacy.py scan --deny /path/outside/repo/deny.txt $(git ls-files --others --cached --exclude-standard)
```
