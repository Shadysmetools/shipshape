# ShipShape quickstart: zero to a recorded QA run in 10 minutes

Works on Windows 10/11 and macOS (Linux too). Fake data only, nothing leaves your machine.

## 1. Install (about 4 min)
**macOS**
```bash
brew install python node ffmpeg          # skip what you already have
git clone https://github.com/Shadysmetools/shipshape.git && cd shipshape
bash bin/install.sh
```
**Windows (PowerShell)**
```powershell
git clone https://github.com/Shadysmetools/shipshape.git; cd shipshape
powershell -ExecutionPolicy Bypass -File bin\install.ps1     # installs Node/ffmpeg with winget if missing (per user)
```
The installer covers the Python packages, the Playwright browsers (Chromium, Firefox, WebKit), the pinned Playwright MCP and Chrome DevTools MCP, and the Playwright CLI. Optional flags: `--with-desktop` / `-WithDesktop` (pyautogui, pywinauto), `--with-k6` / `-WithK6`, `--with-security` / `-WithSecurity` (gitleaks, pip-audit).

## 2. Check (30 s)
```bash
bash bin/doctor.sh            # Windows: powershell -File bin\doctor.ps1
```
Every line should say OK, except the optional ones. Each FAIL line prints its fix.

## 3. Add it to Claude Code (1 min)
```
/plugin marketplace add Shadysmetools/shipshape          # or a local path to this folder
/plugin install smetools-agent-kit@shipshape
```
Restart Claude Code. You should see `ShipShape ready: /qa-goal /qa-run ...` at session start.

## 4. First recorded QA run (2 min)
```bash
bash bin/run-qa.sh demo       # Windows: powershell -File bin\run-qa.ps1 demo
```
Open the report it prints (`qa-runs/<date>-demo-shop-sign-up-works/report.html`). It shows `2 pass / 0 fail`, a narrated video of each pass, screenshots, console/network, the smoke load chart, the security count and the delivery dry-run.

Then try it from Claude Code, with the demo app served (`python -m http.server 8765 --bind 127.0.0.1 --directory examples/demo-app`):
```
/qa-goal "the demo shop sign-up works, including the empty-form error"
```
To see a guard fire, ask Claude to run `examples/demo-app/plans/pay-guard.json`: the run stops at "Pay now", and the ledger opens a human gate.

## 5. First timesheet (2 min)
```bash
cp templates/tasks.example.json tasks.json      # edit project, employee and task rules
python scripts/timesheet.py --project-dir ~/.claude/projects/<your-project-folder> --tasks tasks.json \
  --gap 20 --tz +00:00 --since 2026-01-01 --out hours.xlsx
```
Or just ask Claude: "log my hours for this project this week". You get 7 sheets (Summary, Daily, Sessions, Evidence, Method, Checks, Odoo Import) and the checks line. Nothing is written to Odoo.

## 6. Make it yours
- Copy `templates/qa.config.example.yaml` into your project as `qa.config.yaml`, then set `base_url`, `allow_hosts` and the channels (env var names only).
- Write plans like `examples/demo-app/plans/signup.json`, or let the `qa-lead` agent write them from your goal.
- Read `docs/OPERATING-RULES.md` once. It is short, and every rule exists for a reason.
