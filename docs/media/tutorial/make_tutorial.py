#!/usr/bin/env python3
"""Re-render the ShipShape tutorial video, teaser, captions, chapters and thumbnail.

    python make_tutorial.py capture [--with-claude]   # re-run the real commands on the local demo app -> capture/
    python make_tutorial.py render                     # out/shipshape-tutorial.mp4 (+ .srt, .ar.srt, chapters.txt, script.md)
    python make_tutorial.py teaser                     # out/shipshape-teaser.mp4 (<= 60 s)
    python make_tutorial.py thumb                      # out/shipshape-thumbnail.png (1280x720)
    python make_tutorial.py check                      # privacy check of every text source + OCR of sampled frames (if available)
    python make_tutorial.py [all] [--with-claude]      # capture, render, teaser, thumb, check (the default)

Everything is driven by scenes.yaml (same folder). Real footage only comes from the kit's own example app
(examples/demo-app, served on 127.0.0.1:8765) and synthetic fixtures (assets/make_fixtures.py).
A scene whose `requires:` paths are missing in the kit renders as a labelled mock ("COMING IN THIS BUILD").

--with-claude also re-runs the two steps that need a signed-in Claude Code (`claude -p` with this plugin
loaded via --plugin-dir, no user MCP servers): the refuter verdict and the plain-language push hook.
Without it, the transcripts captured earlier in capture/transcripts/ are reused.

Needs: python 3.10+, ffmpeg/ffprobe, playwright (chromium), edge-tts, PyYAML, Pillow; the kit's scripts/tts.py.
Folders: capture/ and build/ are scratch (do not commit); out/ holds the deliverables.
Privacy: set SMEKIT_DENYLIST to a deny-list file kept OUTSIDE the repo (private names to flag).
"""
from __future__ import annotations

import argparse
import datetime as dt
import glob
import html
import json
import math
import os
import re
import shutil
import socket
import subprocess
import sys
import time
import urllib.request

sys.dont_write_bytecode = True
HERE = os.path.dirname(os.path.abspath(__file__))
KIT = os.path.abspath(os.path.join(HERE, "..", "..", ".."))
CAP = os.path.join(HERE, "capture")
BUILD = os.path.join(HERE, "build")
OUT = os.path.join(HERE, "out")
TR = os.path.join(CAP, "transcripts")
sys.path.insert(0, os.path.join(KIT, "scripts"))
import tts  # noqa: E402  (kit narration: edge-tts with a self-healing cache)

W, H = 1920, 1080
TOPH, CAPH = 92, 150
BOX = (60, TOPH + 22, W - 60, H - CAPH - 22)  # content box x0, y0, x1, y1
FPS = 30
LEAD, GAP, TAIL, FADE = 0.55, 0.45, 0.7, 0.25
PORT = 8765
SAY = [(r"/qa-goal", "slash Q A goal"), (r"/timesheet", "slash timesheet"), (r"/odoo-check", "slash Odoo check"),
       (r"/qa-deliver", "slash Q A deliver"), (r"\bQA\b", "Q A"), (r"\bp95\b", "p ninety-five"), (r"\.html\b", " dot H T M L"),
       (r"\bHTML\b", "H T M L")]
SECRET_ENV = ("GROQ_API_KEY", "CLAUDE_CODE_MESSAGING_TOKEN", "TELEGRAM_BOT_TOKEN", "WHATSAPP_TOKEN", "SLACK_WEBHOOK_URL",
              "SMTP_PASSWORD", "OPENAI_API_KEY", "ELEVENLABS_API_KEY", "TWILIO_AUTH_TOKEN")


# ======================================================================= helpers
def load_spec():
    import yaml
    with open(os.path.join(HERE, "scenes.yaml"), encoding="utf-8") as fh:
        return yaml.safe_load(fh)


def sh(cmd, timeout=1800, **kw):
    subprocess.run(cmd, check=True, timeout=timeout, **kw)


def ff(args, timeout=1800):
    sh(["ffmpeg", "-y", "-v", "error", *args], timeout=timeout)


def dur(path):
    return tts.duration(path) or 0.0


def clean_env():
    env = {k: v for k, v in os.environ.items() if k not in SECRET_ENV}
    env.update(PYTHONDONTWRITEBYTECODE="1", PYTHONIOENCODING="utf-8")
    return env


def rmtree(path):
    import stat

    def onerr(func, p, _exc):
        os.chmod(p, stat.S_IWRITE)
        func(p)
    if os.path.exists(path):
        shutil.rmtree(path, onerror=onerr)


def slug(s):
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")[:60]


def kit_names():
    mk = json.load(open(os.path.join(KIT, ".claude-plugin", "marketplace.json"), encoding="utf-8"))
    pl = json.load(open(os.path.join(KIT, ".claude-plugin", "plugin.json"), encoding="utf-8"))
    return mk["name"], pl["name"]


def scrub(text):
    """Rewrite machine-specific paths and real API hosts into neutral placeholders."""
    reps = []
    for base, to in ((CAP, "~/demo-shop"), (KIT, "~/shipshape")):
        for v in {base, base.replace("\\", "/"), base.replace("\\", "\\\\")}:
            reps.append((v, to))
        drive, rest = os.path.splitdrive(base)
        if drive:
            reps.append(("/" + drive[0].lower() + rest.replace("\\", "/"), to))
    for a, b in sorted(reps, key=lambda x: -len(x[0])):
        text = re.sub(re.escape(a), b, text, flags=re.I)
    text = text.replace("https://api.telegram.org", "<telegram-api>").replace("https://graph.facebook.com", "<whatsapp-cloud-api>")
    # doctor-style "[OK] tool: C:\...\tool.exe" -> "found on PATH"
    text = re.sub(r"(?m)^(\s*\[[A-Za-z ]+\]\s+[\w:@./-]+): (?:[A-Za-z]:\\|/)[^\n]*$", r"\1: found on PATH", text)
    text = re.sub(r"(?i)(?<![A-Za-z])[A-Z]:[\\/]+Users[\\/]+[^\\/\s'\"]+", "~", text)
    text = re.sub(r"(?i)(?<![\w.])/(?:c/)?Users/[^/\s'\"]+", "~", text)
    text = re.sub(r"(?i)(?<![A-Za-z])[A-Z]:[\\/]+[^\s'\"]*", "<path>", text)
    text = re.sub(r"~[\\/]+demo-shop[\\/]+", "", text)
    return text.replace("\r\n", "\n")


def save_tr(name, items):
    os.makedirs(TR, exist_ok=True)
    items = [{"cmd": scrub(i.get("cmd", "")), "out": scrub(i.get("out", "")).rstrip(), **({"prompt": i["prompt"]} if "prompt" in i else {})}
             for i in items]
    json.dump(items, open(os.path.join(TR, name + ".json"), "w", encoding="utf-8"), indent=1, ensure_ascii=False)
    print(f"  transcript {name}: {sum(len(i['out'].splitlines()) for i in items)} lines")


def run_out(cmd, cwd=CAP, timeout=1800, env=None, stdin=None):
    p = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=timeout,
                       env=env or clean_env(), input=stdin)
    return ((p.stdout or "") + (p.stderr or "")).strip(), p.returncode


def server_up():
    try:
        urllib.request.urlopen(f"http://127.0.0.1:{PORT}/index.html", timeout=3).read()
        return True
    except OSError:
        return False


def ensure_server():
    if server_up():
        return None
    p = subprocess.Popen([sys.executable, "-m", "http.server", str(PORT), "--bind", "127.0.0.1"],
                         cwd=os.path.join(KIT, "examples", "demo-app"), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    for _ in range(30):
        time.sleep(0.5)
        if server_up():
            return p
    raise SystemExit("demo app did not start on port %d" % PORT)


def run_dir(goal):
    hits = sorted(glob.glob(os.path.join(CAP, "qa-runs", "*-" + slug(goal))))
    if not hits:
        raise SystemExit(f"no captured run for goal {goal!r}: run `make_tutorial.py capture` first")
    return hits[-1]


# ======================================================================= capture
def capture(with_claude=False):
    spec = load_spec()
    goal = spec["meta"]["run_goal"]
    os.makedirs(CAP, exist_ok=True)
    py = sys.executable
    S = os.path.join(KIT, "scripts")
    srv = ensure_server()
    try:
        sh([py, os.path.join(HERE, "assets", "make_fixtures.py"), os.path.join(CAP, "fixtures")], env=clean_env())
        shutil.rmtree(os.path.join(CAP, "qa-runs"), ignore_errors=True)

        print("install (isolated CLAUDE_CONFIG_DIR, never the user's own config)")
        mkt, plugin = kit_names()
        home = os.path.join(CAP, "claude-home")
        shutil.rmtree(home, ignore_errors=True)
        os.makedirs(home)
        env = {**clean_env(), "CLAUDE_CONFIG_DIR": home}
        claude = shutil.which("claude") or "claude"
        o1, _ = run_out([claude, "plugin", "marketplace", "add", KIT], env=env, timeout=300)
        o2, _ = run_out([claude, "plugin", "install", f"{plugin}@{mkt}"], env=env, timeout=300)
        o3, _ = run_out([claude, "plugin", "list"], env=env, timeout=120)
        o3 = re.sub(r"\n\s*Read from:[^\n]*", "", o3)
        save_tr("install", [{"cmd": "claude plugin marketplace add your-org/shipshape", "out": o1},
                            {"cmd": f"claude plugin install {plugin}@{mkt}", "out": o2},
                            {"cmd": "claude plugin list", "out": o3}])

        print("doctor")
        o, _ = run_out([py, os.path.join(S, "doctor.py")], timeout=600)
        save_tr("doctor", [{"cmd": "python scripts/doctor.py", "out": o}])

        print("qa goal (full pipeline on the demo app)")
        demo = os.path.join(KIT, "examples", "demo-app")
        o, _ = run_out([py, os.path.join(S, "full_qa.py"), goal, "--plan", os.path.join(demo, "plans", "signup.json"),
                        "--plan", os.path.join(demo, "plans", "pay-guard.json"), "--config", os.path.join(demo, "qa.config.yaml"),
                        "--url", f"http://127.0.0.1:{PORT}/", "--allow-host", "127.0.0.1", "--load", "smoke",
                        "--repo", demo, "--narrate", "--root", "qa-runs"], timeout=2400)
        save_tr("qa_goal", [{"cmd": f'python scripts/full_qa.py "{goal}" --plan plans/signup.json --plan plans/pay-guard.json '
                                    f'--config qa.config.yaml --url http://127.0.0.1:{PORT}/ --allow-host 127.0.0.1 --load smoke --narrate',
                             "out": o}])
        run = run_dir(goal)

        print("failing plan -> verify/refute")
        g2 = "returning user sees welcome back"
        o, _ = run_out([py, os.path.join(S, "full_qa.py"), g2, "--plan", os.path.join(CAP, "fixtures", "plans", "welcome-back.json"),
                        "--url", f"http://127.0.0.1:{PORT}/", "--allow-host", "127.0.0.1", "--repo", demo, "--skip-security",
                        "--root", "qa-runs"], timeout=1800)
        save_tr("refute_run", [{"cmd": f'python scripts/full_qa.py "{g2}" --plan plans/welcome-back.json --url http://127.0.0.1:{PORT}/ '
                                       f'--allow-host 127.0.0.1', "out": o}])
        run2 = run_dir(g2)
        rel2 = os.path.relpath(run2, CAP).replace("\\", "/")
        if with_claude:
            prompt = ("Use the qa-refuter subagent from the ShipShape plugin on this claim and report its verdict. "
                      f"CLAIM: B1 (case TC-04) - after sign-up, a returning user does not see 'Welcome back, Test User'. "
                      f"Evidence: both passes failed in {rel2}/round-01/welcome-back (ledger at {rel2}/ledger.json, screenshot "
                      "02-TC-04-fail.png). The app under test is the local demo shop at http://127.0.0.1:8765/index.html; its source is "
                      "../../../../examples/demo-app/index.html and the original plans are in ../../../../examples/demo-app/plans/. "
                      "The failing plan is fixtures/plans/welcome-back.json. Fake data only.")
            o, _ = run_out([claude, "-p", "--plugin-dir", KIT, "--strict-mcp-config", "--setting-sources", "project", "--allowedTools",
                            "Read", "Grep", "Glob", "Bash(python:*)", "Bash(curl:*)", "Bash(ls:*)", "Bash(cat:*)", "Task", "Agent",
                            "--output-format", "text", prompt], timeout=1200)
            save_tr("refuter", [{"cmd": "claude -p \"Use the qa-refuter agent on claim B1 (TC-04: 'Welcome back, Test User' missing)\"",
                                 "out": o}])
        else:
            _retarget("refuter", rel2)
        o, _ = run_out([py, os.path.join(S, "qa_loop.py"), "bug", "--run", run2, "--id", "B1", "--status", "refuted", "--note",
                        "wrong expectation: the app and the plan say 'Welcome, <name>'; 'Welcome back' is in no spec"])
        save_tr("refute_ledger", [{"cmd": 'python scripts/qa_loop.py bug --id B1 --status refuted --note "wrong expectation ..."',
                                   "out": o}])

        print("delivery dry run")
        o1, _ = run_out([py, os.path.join(S, "privacy.py"), "scan", os.path.join(run, "report.html"), os.path.join(run, "summary-en.srt")])
        o2, _ = run_out([py, os.path.join(S, "notify.py"), run, "--config", os.path.join(CAP, "fixtures", "qa.config.deliver.yaml")])
        save_tr("deliver", [{"cmd": "python scripts/privacy.py scan report.html summary-en.srt", "out": o1},
                            {"cmd": "python scripts/notify.py qa-runs/<run> --config qa.config.yaml", "out": o2}])

        print("commit-scan hook (throwaway git repo, fake token)")
        hd = os.path.join(CAP, "hookdemo")
        rmtree(hd)
        os.makedirs(hd)
        for c in (["git", "init", "-q"], ["git", "config", "user.name", "Demo Dev"], ["git", "config", "user.email", "dev@example.com"]):
            run_out(c, cwd=hd)
        fake = "123456789:" + ("AAFake" + "Fake" * 8)[:35]  # token-shaped, fake
        open(os.path.join(hd, "settings.env"), "w").write(f"TELEGRAM_BOT_TOKEN={fake}\nSUPPORT=help@example.com\n")
        run_out(["git", "add", "settings.env"], cwd=hd)
        o, rc = run_out([py, os.path.join(S, "hook_commit_scan.py")], cwd=hd,
                        stdin=json.dumps({"tool_name": "Bash", "tool_input": {"command": 'git commit -m "add settings"'}, "cwd": hd}))
        save_tr("hook_commit", [{"prompt": "claude", "cmd": 'git commit -m "add settings"',
                                 "out": f"PreToolUse hook (hook_commit_scan.py), exit {rc}:\n{o}"}])
        if with_claude:
            run_out(["git", "reset", "-q"], cwd=hd)
            os.remove(os.path.join(hd, "settings.env"))
            open(os.path.join(hd, "README.md"), "w").write("# demo\n")
            run_out(["git", "add", "README.md"], cwd=hd)
            run_out(["git", "commit", "-qm", "demo readme"], cwd=hd)
            o, _ = run_out([claude, "-p", "--plugin-dir", KIT, "--strict-mcp-config", "--setting-sources", "project", "--allowedTools",
                            "Bash(git push:*)", "--output-format", "stream-json", "--verbose",
                            "Run exactly this command with the Bash tool and then tell me in two short sentences what happened: "
                            "git push --force origin main"], cwd=hd, timeout=600)
            save_tr("hook_push", _push_items(o))

        print("desktop control dry runs")
        fx = os.path.join(CAP, "fixtures")
        items = []
        for cfg, steps in (("desktop-off.yaml", "desktop-steps.json"), ("desktop-on.yaml", "desktop-steps.json"),
                           ("desktop-on.yaml", "desktop-bank.json")):
            outd = os.path.join(CAP, "desktop", cfg[:-5] + "-" + steps[:-5])
            shutil.rmtree(outd, ignore_errors=True)
            o, _ = run_out([py, os.path.join(S, "desktop.py"), "run", os.path.join(fx, steps), "--config", os.path.join(fx, cfg),
                            "--out", outd, "--dry-run"])
            log = open(os.path.join(outd, "desktop-actions.jsonl"), encoding="utf-8").read()
            log = "\n".join(re.sub(r', "t": "[^"]+"', "", ln) for ln in log.splitlines())
            items.append({"cmd": f"python scripts/desktop.py run {steps} --config {cfg} --dry-run", "out": o.split(" | log:")[0] + "\n" + log})
        save_tr("desktop", items)

        print("timesheet (synthetic logs)")
        os.makedirs(os.path.join(CAP, "timesheet"), exist_ok=True)
        o, _ = run_out([py, os.path.join(S, "timesheet.py"), "--project-dir", os.path.join(fx, "fake-claude-project"), "--tasks",
                        os.path.join(fx, "tasks.json"), "--gap", "20", "--tz", "+02:00", "--out", os.path.join("timesheet", "demo-shop-week43.xlsx")])
        save_tr("timesheet", [{"cmd": "python scripts/timesheet.py --project-dir fake-claude-project --tasks tasks.json --gap 20 "
                                      "--tz +02:00 --out timesheet/demo-shop-week43.xlsx", "out": o}])

        print("odoo check (fake module)")
        o, _ = run_out([py, os.path.join(S, "odoo_check.py"), os.path.join(fx, "demo_shop_loyalty"), "--series", "17.0"])
        save_tr("odoo", [{"cmd": "python scripts/odoo_check.py demo_shop_loyalty --series 17.0", "out": o}])

        report_shot(run)
    finally:
        if srv:
            srv.terminate()


def _retarget(name, rel_run):
    """Reused claude transcript: point its run folder at today's run name."""
    p = os.path.join(TR, name + ".json")
    if os.path.exists(p):
        s = open(p, encoding="utf-8").read()
        s = re.sub(r"qa-runs/\d{4}-\d{2}-\d{2}-returning-user-sees-welcome-back", rel_run, s)
        open(p, "w", encoding="utf-8").write(s)


def _push_items(stream):
    cmd, res, final = "git push --force origin main", "", ""
    for ln in stream.splitlines():
        try:
            d = json.loads(ln)
        except ValueError:
            continue
        if d.get("type") in ("assistant", "user"):
            for c in d["message"].get("content", []):
                if isinstance(c, dict) and c.get("type") == "tool_use":
                    cmd = (c.get("input") or {}).get("command", cmd)
                elif isinstance(c, dict) and c.get("type") == "tool_result":
                    res = str(c.get("content"))
        elif d.get("type") == "result":
            final = d.get("result", "")
    m = re.search(r"\]:\s*(.*)$", res, re.S)
    reason = (m.group(1) if m else res).strip()
    head = res.split("Hook input")[0].split("[")[0].strip() or "PreToolUse:Bash hook error:"
    rule = re.search(r"\[(Guard for git push)", res)
    return [{"prompt": "claude", "cmd": cmd,
             "out": f"{head} [{rule.group(1) if rule else 'Guard for git push'} ...]\n{reason}"},
            {"prompt": "claude-says", "cmd": "", "out": final}]


def report_shot(run):
    from playwright.sync_api import sync_playwright
    os.makedirs(BUILD, exist_ok=True)
    with sync_playwright() as p:
        b = p.chromium.launch()
        pg = b.new_page(viewport={"width": 1440, "height": 810})
        pg.goto("file:///" + os.path.join(run, "report.html").replace("\\", "/"))
        pg.wait_for_timeout(800)
        pg.screenshot(path=os.path.join(BUILD, "report_full.png"), full_page=True)
        b.close()


# ======================================================================= HTML / visuals
CSS = """
:root{--bg:#0d1726;--panel:#13213a;--ink:#eef3fb;--muted:#9fb0c8;--accent:#2dd4bf;--accent2:#fbbf24;--line:#24375a;--term:#0a111d}
*{box-sizing:border-box}html,body{margin:0;width:1920px;height:1080px;overflow:hidden;background:var(--bg);color:var(--ink);
 font-family:'Segoe UI',system-ui,Arial,sans-serif}
.top{position:absolute;left:0;right:0;top:0;height:92px;display:flex;align-items:center;gap:22px;padding:0 60px;
 background:linear-gradient(90deg,#10203a,#0d1726);border-bottom:1px solid var(--line)}
.brand{font-weight:800;font-size:26px;letter-spacing:.5px}.brand b{color:var(--accent)}
.sep{width:1px;height:36px;background:var(--line)}
.k{color:var(--accent);font-weight:700;letter-spacing:1.6px;text-transform:uppercase;font-size:19px}
.t{font-size:31px;font-weight:650}
.tag{margin-left:auto;padding:7px 16px;border-radius:999px;font-size:17px;font-weight:800;letter-spacing:1.2px}
.real{background:rgba(45,212,191,.14);color:#5eead4;border:1px solid rgba(45,212,191,.45)}
.ill{background:rgba(159,176,200,.12);color:#c6d2e3;border:1px solid rgba(159,176,200,.4)}
.mock{background:rgba(251,191,36,.16);color:#fcd34d;border:1px solid rgba(251,191,36,.6)}
.capbar{position:absolute;left:0;right:0;bottom:0;height:150px;background:#08101c;border-top:1px solid var(--line)}
.box{position:absolute;left:60px;top:114px;right:60px;bottom:172px}
.card{padding:40px 70px}.card h1{font-size:72px;margin:0 0 34px;line-height:1.1}
.card ul{list-style:none;margin:0;padding:0}.card li{font-size:38px;line-height:1.35;margin:0 0 22px;padding-left:44px;position:relative;color:#dbe5f3}
.card li:before{content:'';position:absolute;left:0;top:17px;width:16px;height:16px;border-radius:4px;background:var(--accent)}
.card code,.card .c{font-family:Consolas,'Cascadia Mono',monospace;color:var(--accent2)}
.title{position:absolute;inset:0;display:flex;flex-direction:column;justify-content:center;padding:0 160px;
 background:radial-gradient(1200px 700px at 78% 30%,rgba(45,212,191,.18),transparent 60%),radial-gradient(900px 600px at 10% 90%,rgba(251,191,36,.10),transparent 60%),var(--bg)}
.title .kick{font-size:30px;color:var(--accent);font-weight:700;letter-spacing:2px;text-transform:uppercase;margin-bottom:18px}
.title h1{font-size:170px;margin:0;line-height:1;font-weight:850;letter-spacing:-3px}
.title h1 span{color:var(--accent)}.title .sub{font-size:52px;color:#d5deeb;margin-top:22px}
.mark{position:absolute;right:160px;top:50%;transform:translateY(-62%);width:300px;height:300px}
.term{position:absolute;inset:0;background:var(--term);border:1px solid var(--line);border-radius:14px;overflow:hidden}
.term .bar{height:44px;background:#111b2c;display:flex;align-items:center;gap:9px;padding:0 18px;border-bottom:1px solid var(--line)}
.term .bar i{width:13px;height:13px;border-radius:50%;display:inline-block}.term .bar span{margin-left:14px;color:var(--muted);font:17px Consolas,monospace}
.term pre{margin:0;padding:22px 30px;font:23px/1.42 Consolas,'Cascadia Mono',Menlo,monospace;color:#d7e3f1;white-space:pre-wrap;word-break:break-word}
.p{color:var(--accent)}.cm{color:#fff;font-weight:600}.ok{color:#4ade80}.bad{color:#f87171}.warn{color:#fbbf24}.dim{color:#7f91ab}
.cur{display:inline-block;width:12px;height:24px;background:var(--accent);vertical-align:-4px}
.shot{position:absolute;inset:0;display:flex;align-items:center;justify-content:center}
.shot img{max-width:100%;max-height:100%;border-radius:10px;border:1px solid var(--line);box-shadow:0 10px 40px rgba(0,0,0,.45)}
.mockbody{position:absolute;inset:0;display:flex;flex-direction:column;justify-content:center;align-items:center;text-align:center;
 border:3px dashed rgba(251,191,36,.55);border-radius:18px;background:rgba(251,191,36,.04)}
.mockbody h2{font-size:64px;margin:0 0 20px;color:#fcd34d}.mockbody p{font-size:34px;color:#dbe5f3;margin:6px 0}
"""

LOGO = """<svg viewBox="0 0 120 120" xmlns="http://www.w3.org/2000/svg"><defs><linearGradient id="g" x1="0" y1="0" x2="1" y2="1">
<stop offset="0" stop-color="#2dd4bf"/><stop offset="1" stop-color="#0ea5e9"/></linearGradient></defs>
<path d="M60 6 L104 22 V58 C104 86 84 104 60 114 C36 104 16 86 16 58 V22 Z" fill="url(#g)" opacity=".95"/>
<path d="M38 60 L54 76 L84 44" fill="none" stroke="#0d1726" stroke-width="10" stroke-linecap="round" stroke-linejoin="round"/></svg>"""

TAGCLASS = {"REAL OUTPUT": "real", "LIVE RECORDING": "real", "ILLUSTRATION": "ill", "MOCK": "mock"}


def page(body, transparent=False):
    bg = "html,body{background:transparent!important}" if transparent else ""
    return f'<!doctype html><html><head><meta charset="utf-8"><style>{CSS}{bg}</style></head><body>{body}</body></html>'


def topbar(sc):
    tag = sc.get("tag", "")
    t = f'<span class="tag {TAGCLASS.get(tag, "ill")}">{html.escape(tag)}</span>' if tag else ""
    return (f'<div class="top"><span class="brand">Ship<b>Shape</b></span><span class="sep"></span>'
            f'<span class="k">{html.escape(sc.get("kicker", ""))}</span><span class="t">{html.escape(sc.get("heading", ""))}</span>{t}</div>'
            '<div class="capbar"></div>')


def md_inline(s):
    s = html.escape(s)
    return re.sub(r"(/[a-z][a-z-]+)", r'<span class="c">\1</span>', s)


def title_html(sc):
    h = html.escape(sc.get("heading", "ShipShape"))
    h = h.replace("Shape", "<span>Shape</span>", 1) if h == "ShipShape" else h
    return (f'<div class="title"><div class="kick">{html.escape(sc.get("kicker", ""))}</div><h1>{h}</h1>'
            f'<div class="sub">{html.escape(sc.get("sub", ""))}</div><div class="mark">{LOGO}</div></div><div class="capbar" style="background:transparent;border:0"></div>')


def card_html(sc):
    lis = "".join(f"<li>{md_inline(b)}</li>" for b in sc.get("bullets", []))
    return topbar(sc) + f'<div class="box card"><h1>{html.escape(sc.get("heading", ""))}</h1><ul>{lis}</ul></div>'


def mock_html(sc, missing):
    m = dict(sc, tag="MOCK")
    return topbar(m) + (f'<div class="box"><div class="mockbody"><h2>COMING IN THIS BUILD</h2>'
                        f'<p>{html.escape(sc.get("heading", ""))}</p><p style="color:#9fb0c8;font-size:26px">'
                        f'not in the kit yet: {html.escape(", ".join(missing))} - this slide is a placeholder</p></div></div>')


def frame_html(sc):
    return topbar(sc) + '<div class="box"></div>'


def image_html(sc, img):
    return topbar(sc) + f'<div class="box"><div class="shot"><img src="{_uri(img)}"></div></div>'


def _uri(p):
    return "file:///" + os.path.abspath(p).replace("\\", "/")


def caption_html(text):
    return page(f'<div style="position:absolute;left:0;right:0;bottom:0;height:150px;display:flex;align-items:center;justify-content:center;'
                f'padding:0 150px;text-align:center;font-size:36px;line-height:1.32;color:#fff;font-weight:500;'
                f'text-shadow:0 2px 6px rgba(0,0,0,.6)">{html.escape(text)}</div>', transparent=True)


# ----------------------------------------------------------------------- terminal content
def term_items(sc):
    out = []
    for it in sc.get("items", []):
        if "t" in it:
            p = os.path.join(TR, it["t"] + ".json")
            if not os.path.exists(p):  # committed fallback (the two claude -p captures)
                p = os.path.join(HERE, "assets", "transcripts", it["t"] + ".json")
            if not os.path.exists(p):
                out.append({"cmd": f"# transcript '{it['t']}' not captured", "out": ""})
                continue
            for x in json.load(open(p, encoding="utf-8")):
                o = x["out"]
                if it.get("from") and it["from"] in o:
                    o = o[o.index(it["from"]):]
                if it.get("upto") and it["upto"] in o:
                    o = o[:o.index(it["upto"])]
                out.append({**x, "out": o.rstrip()})
        elif "file" in it:
            lines = open(os.path.join(KIT, it["file"]), encoding="utf-8").read().splitlines()
            if it.get("grep"):
                rx = re.compile(it["grep"])
                lines = [ln.strip() if it.get("wrap") else ln for ln in lines if rx.search(ln)]
            lines = [ln if len(ln) <= 260 else ln[:257] + "..." for ln in lines]
            cmd = f'grep -E "{it["grep"]}" {it["file"]}' if it.get("grep") else f"cat {it['file']}"
            out.append({"cmd": cmd, "out": scrub("\n".join(lines))})
    return out


def colorize(line):
    s = html.escape(line)
    s = re.sub(r"(\b(?:PASS|OK|DRY-RUN|DONE)\b|✔[^\n]*)", r'<span class="ok">\1</span>', s)
    s = re.sub(r"(\b(?:FAIL|REFUSED|BLOCKED|Blocked|refuted)\b|✘)", r'<span class="bad">\1</span>', s)
    s = re.sub(r"(\b(?:OPTIONAL|WARN|unset|waiting-human|verify-refute)\b)", r'<span class="warn">\1</span>', s)
    s = re.sub(r"^(== .*)$", r'<span class="p">\1</span>', s)
    return s


PROMPTS = {None: '<span class="p">~/demo-shop $</span> ', "claude": '<span class="p">Claude ▸ Bash</span> ',
           "claude-says": '<span class="p">Claude:</span> '}


def term_state(items, upto_item, typed, shown):
    """HTML <pre> body: items [0, upto_item) complete; item upto_item typed `typed` chars and `shown` output lines."""
    rows = []
    for i, it in enumerate(items[:upto_item + 1]):
        last = i == upto_item
        cmd = it["cmd"] if not last else it["cmd"][:typed]
        pr = PROMPTS.get(it.get("prompt"), PROMPTS[None])
        if it.get("prompt") == "claude-says":
            outl = it["out"].splitlines()
            n = len(outl) if not last else shown
            if n:
                rows.append(pr + colorize(outl[0]))
                rows += [colorize(x) for x in outl[1:n]]
            continue
        if it["cmd"]:
            cur = '<span class="cur"></span>' if last and (typed < len(it["cmd"]) or shown == 0) else ""
            rows.append(pr + f'<span class="cm">{html.escape(cmd)}</span>{cur}')
        outl = it["out"].splitlines()
        rows += [colorize(x) for x in (outl if not last else outl[:shown])]
    return rows


def fit_tail(rows, max_rows=21, cpr=124):
    used, keep = 0, []
    for r in reversed(rows):
        txt = re.sub(r"<[^>]+>", "", html.unescape(r))
        n = max(1, math.ceil(len(txt) / cpr))
        if used + n > max_rows:
            break
        keep.append(r)
        used += n
    return list(reversed(keep))


def term_html(sc, rows, title="bash"):
    body = "\n".join(fit_tail(rows))
    return topbar(sc) + (f'<div class="box"><div class="term"><div class="bar"><i style="background:#f87171"></i><i style="background:#fbbf24"></i>'
                         f'<i style="background:#4ade80"></i><span>{html.escape(title)}</span></div><pre>{body}</pre></div></div>')


# ======================================================================= scene rendering
class Shooter:
    def __init__(self):
        from playwright.sync_api import sync_playwright
        self._p = sync_playwright().start()
        self.b = self._p.chromium.launch()
        self.pg = self.b.new_page(viewport={"width": W, "height": H})
        self.n = 0

    def shot(self, doc, path, transparent=False, size=(W, H)):
        if size != (self.pg.viewport_size["width"], self.pg.viewport_size["height"]):
            self.pg.set_viewport_size({"width": size[0], "height": size[1]})
        tmp = os.path.join(BUILD, "tmp.html")
        open(tmp, "w", encoding="utf-8").write(doc)
        self.pg.goto(_uri(tmp))
        self.pg.wait_for_timeout(60)
        self.pg.screenshot(path=path, omit_background=transparent)
        return path

    def close(self):
        self.b.close()
        self._p.stop()


def resolve(path, run):
    p = path.replace("@run", run).replace("@build", BUILD)
    hits = sorted(glob.glob(p))
    return hits[0] if hits else None


def say_text(t):
    for a, b in SAY:
        t = re.sub(a, b, t)
    return t


def split_caption(text, maxc=105):
    if len(text) <= maxc:
        return [text]
    parts = re.split(r"(?<=[.;!?])\s+", text)
    out = []
    for p in parts:
        if len(p) > maxc:
            sub = re.split(r"(?<=,)\s+", p)
            cur = ""
            for s in sub:
                if cur and len(cur) + len(s) + 1 > maxc:
                    out.append(cur)
                    cur = s
                else:
                    cur = (cur + " " + s).strip()
            if cur:
                out.append(cur)
        else:
            out.append(p)
    merged = []
    for p in out:
        if merged and len(merged[-1]) + len(p) + 1 <= maxc:
            merged[-1] += " " + p
        else:
            merged.append(p)
    return merged


def missing_requires(sc):
    return [r for r in sc.get("requires", []) if not os.path.exists(os.path.join(KIT, r))]


def render_scene(sc, idx, run, shooter, voice, rate, work):
    os.makedirs(work, exist_ok=True)
    # ---- narration timeline
    lines = sc.get("lines", [])
    t, cues, audio = LEAD, [], []
    for ln in lines:
        mp3, d, _ = tts.speak(say_text(ln["en"]), voice, rate)
        audio.append((mp3, t))
        chunks = split_caption(ln["en"])
        tot = sum(len(c) for c in chunks)
        ct = t
        for c in chunks:
            cd = d * len(c) / tot
            cues.append({"a": ct, "b": ct + cd + (0.12 if c is chunks[-1] else 0), "en": c, "burn": True})
            ct += cd
        cues[-len(chunks)]["ar"] = ln.get("ar", "")
        cues[-len(chunks)]["ar_end"] = t + d + 0.12
        t += d + GAP
    narr_end = t - GAP if lines else 0.0
    D = narr_end + TAIL
    missing = missing_requires(sc)
    kind = "mock" if missing else sc["kind"]
    vis = os.path.join(work, "vis.mp4")
    src_audio, src_t0 = None, 0.0

    def still(png, d=None):
        ff(["-loop", "1", "-framerate", str(FPS), "-i", png, "-t", f"{d or D:.3f}", "-c:v", "libx264", "-preset", "veryfast", "-crf", "18",
            "-pix_fmt", "yuv420p", "-r", str(FPS), vis])

    if kind == "title":
        still(shooter.shot(page(title_html(sc)), os.path.join(work, "f.png")))
    elif kind == "card":
        still(shooter.shot(page(card_html(sc)), os.path.join(work, "f.png")))
    elif kind == "mock":
        still(shooter.shot(page(mock_html(sc, missing)), os.path.join(work, "f.png")))
    elif kind == "image":
        img = resolve(sc["image"], run)
        still(shooter.shot(page(image_html(sc, img)), os.path.join(work, "f.png")))
    elif kind == "terminal":
        render_terminal(sc, D, shooter, work, vis)
    elif kind == "scroll":
        img = resolve(sc["image"], run)
        bg = shooter.shot(page(frame_html(sc)), os.path.join(work, "bg.png"))
        from PIL import Image
        iw, ih = Image.open(img).size
        bw, bh = BOX[2] - BOX[0], BOX[3] - BOX[1]
        sc_w = min(bw, iw)
        sc_h = int(ih * sc_w / iw)
        span = max(0, sc_h - bh)
        a, b = 1.2, max(2.0, D - 1.5)
        y = f"{span}*clip((t-{a})/{b - a},0,1)"
        x0 = BOX[0] + (bw - sc_w) // 2
        ff(["-loop", "1", "-framerate", str(FPS), "-i", bg, "-loop", "1", "-framerate", str(FPS), "-i", img, "-filter_complex",
            f"[1:v]scale={sc_w}:{sc_h},crop={sc_w}:{min(bh, sc_h)}:0:'{y}'[s];[0:v][s]overlay={x0}:{BOX[1]}[v]", "-map", "[v]",
            "-t", f"{D:.3f}", "-c:v", "libx264", "-preset", "veryfast", "-crf", "18", "-pix_fmt", "yuv420p", "-r", str(FPS), vis])
    elif kind == "video":
        src = resolve(sc["src"], run)
        sd = dur(src)
        bg = shooter.shot(page(frame_html(sc)), os.path.join(work, "bg.png"))
        bw, bh = BOX[2] - BOX[0], BOX[3] - BOX[1]
        vh = bh
        vw = int(round(vh * 16 / 9 / 2) * 2)
        x0 = BOX[0] + (bw - vw) // 2
        if sc.get("keep_audio"):
            src_t0 = (narr_end + 0.4) if lines else 0.4
            D = src_t0 + sd + 0.6
            chain = f"[1:v]fps={FPS},scale={vw}:{vh},tpad=start_mode=clone:start_duration={src_t0:.3f}:stop_mode=clone:stop_duration=2[s]"
            src_audio = src
            # captions of the embedded video (already burned into it) go into the .srt files too
            if sc.get("embedded_srt"):
                emb = parse_srt(resolve(sc["embedded_srt"], run))
                for k, (a, b, txt) in enumerate(emb):
                    ar = (sc.get("embedded_ar") or [])
                    cues.append({"a": src_t0 + a, "b": src_t0 + b, "en": txt, "burn": False,
                                 "ar": ar[k] if k < len(ar) else "", "ar_end": src_t0 + b})
        else:
            f = sd / D if sd > D else 1.0
            f = min(f, 2.5)
            chain = f"[1:v]setpts=PTS/{f:.4f},fps={FPS},scale={vw}:{vh},tpad=stop_mode=clone:stop_duration={D + 1:.2f}[s]"
        ff(["-loop", "1", "-framerate", str(FPS), "-i", bg, "-i", src, "-filter_complex", f"{chain};[0:v][s]overlay={x0}:{BOX[1]}:shortest=0[v]",
            "-map", "[v]", "-t", f"{D:.3f}", "-c:v", "libx264", "-preset", "veryfast", "-crf", "18", "-pix_fmt", "yuv420p", "-r", str(FPS), vis])
    else:
        raise SystemExit(f"unknown scene kind {kind}")

    # ---- captions overlay + audio
    args = ["-i", vis]
    burn = [c for c in cues if c["burn"]]
    for k, c in enumerate(burn):
        png = shooter.shot(caption_html(c["en"]), os.path.join(work, f"cap{k:02d}.png"), transparent=True)
        args += ["-loop", "1", "-framerate", str(FPS), "-t", f"{D:.3f}", "-i", png]
    na = len(audio)
    for mp3, _ in audio:
        args += ["-i", mp3]
    if src_audio:
        args += ["-i", src_audio]
    fc, prev = [], "0:v"
    for k, c in enumerate(burn):
        fc.append(f"[{prev}][{k + 1}:v]overlay=0:0:enable='between(t,{c['a']:.3f},{c['b']:.3f})'[o{k}]")
        prev = f"o{k}"
    fc.append(f"[{prev}]fade=t=in:st=0:d={FADE},fade=t=out:st={D - FADE:.3f}:d={FADE},format=yuv420p[v]")
    base = 1 + len(burn)
    alabels = []
    for k, (_, at) in enumerate(audio):
        fc.append(f"[{base + k}:a]aresample=48000,aformat=channel_layouts=stereo,adelay={int(at * 1000)}:all=1[a{k}]")
        alabels.append(f"[a{k}]")
    if src_audio:
        fc.append(f"[{base + na}:a]aresample=48000,aformat=channel_layouts=stereo,volume=0.9,adelay={int(src_t0 * 1000)}:all=1[as]")
        alabels.append("[as]")
    if alabels:
        fc.append(f"{''.join(alabels)}amix=inputs={len(alabels)}:normalize=0:duration=longest,apad,atrim=0:{D:.3f},"
                  f"afade=t=in:st=0:d=0.05,afade=t=out:st={D - 0.2:.3f}:d=0.2[a]")
    else:
        args += ["-f", "lavfi", "-t", f"{D:.3f}", "-i", "anullsrc=r=48000:cl=stereo"]
        fc.append(f"[{base}:a]anull[a]")
    clip = os.path.join(work, "scene.mp4")
    ff([*args, "-filter_complex", ";".join(fc), "-map", "[v]", "-map", "[a]", "-t", f"{D:.3f}", "-c:v", "libx264", "-preset", "veryfast",
        "-crf", "18", "-r", str(FPS), "-c:a", "aac", "-b:a", "160k", "-ar", "48000", "-ac", "2", clip])
    real = dur(clip)
    return {"clip": clip, "dur": real, "cues": cues, "kind": kind, "missing": missing}


def render_terminal(sc, D, shooter, work, vis):
    items = term_items(sc)
    n = max(1, len(items))
    span = max(1.0, D * 0.78 - LEAD)
    starts = [LEAD * 0.6 + i * span / n for i in range(n)]
    states = []  # (t, rows)
    for i, it in enumerate(items):
        s = starts[i]
        nxt = starts[i + 1] if i + 1 < n else D - 0.6
        cmd = it["cmd"]
        tsteps = min(18, len(cmd)) if cmd else 0
        type_d = min(1.1, 0.03 * len(cmd)) if cmd else 0
        for k in range(tsteps + 1):
            c = int(len(cmd) * k / tsteps) if tsteps else 0
            states.append((s + type_d * k / max(tsteps, 1), term_state(items, i, c, 0)))
        outl = it["out"].splitlines()
        o0 = s + type_d + 0.35
        o1 = min(nxt - 0.25, o0 + 0.07 * len(outl) + 0.3)
        steps = min(len(outl), 28)
        for k in range(1, steps + 1):
            shown = int(round(len(outl) * k / steps))
            states.append((o0 + (o1 - o0) * (k - 1) / max(steps, 1), term_state(items, i, len(cmd), shown)))
    if not states:
        states = [(0, [])]
    states.sort(key=lambda x: x[0])
    lst = []
    title = "bash  -  Claude Code" if any(it.get("prompt", "").startswith("claude") for it in items if it.get("prompt")) else "bash"
    for k, (st, rows) in enumerate(states):
        png = shooter.shot(page(term_html(sc, rows, title)), os.path.join(work, f"t{k:03d}.png"))
        end = states[k + 1][0] if k + 1 < len(states) else D
        lst.append((png, max(1 / FPS, end - (st if k else 0))))
    cf = os.path.join(work, "frames.txt")
    with open(cf, "w", encoding="utf-8") as fh:
        for png, d in lst:
            fh.write(f"file '{png.replace(os.sep, '/')}'\nduration {d:.4f}\n")
        fh.write(f"file '{lst[-1][0].replace(os.sep, '/')}'\n")
    ff(["-f", "concat", "-safe", "0", "-i", cf, "-vf", f"fps={FPS},format=yuv420p", "-t", f"{D:.3f}", "-c:v", "libx264", "-preset", "veryfast",
        "-crf", "18", "-r", str(FPS), vis])


def parse_srt(path):
    txt = open(path, encoding="utf-8").read().replace("\r\n", "\n")
    out = []
    for blk in txt.strip().split("\n\n"):
        ls = blk.strip().split("\n")
        if len(ls) >= 3 and "-->" in ls[1]:
            a, b = [_srt_sec(x.strip()) for x in ls[1].split("-->")]
            out.append((a, b, " ".join(ls[2:])))
    return out


def _srt_sec(s):
    h, m, rest = s.split(":")
    sec, ms = rest.split(",")
    return int(h) * 3600 + int(m) * 60 + int(sec) + int(ms) / 1000


def srt_time(x):
    ms = int(round(max(0, x) * 1000))
    return f"{ms // 3600000:02d}:{ms // 60000 % 60:02d}:{ms // 1000 % 60:02d},{ms % 1000:03d}"


def hms(x):
    x = int(x)
    return f"{x // 3600}:{x // 60 % 60:02d}:{x % 60:02d}" if x >= 3600 else f"{x // 60:02d}:{x % 60:02d}"


def build_video(scenes, name, chapters=True, crf=27, label="tutorial"):
    spec = load_spec()
    meta = spec["meta"]
    run = run_dir(meta["run_goal"])
    if not os.path.exists(os.path.join(BUILD, "report_full.png")):
        report_shot(run)
    os.makedirs(OUT, exist_ok=True)
    shooter = Shooter()
    results = []
    try:
        for i, sc in enumerate(scenes):
            r = render_scene(sc, i, run, shooter, meta.get("voice", tts.VOICE), meta.get("rate", "-4%"),
                             os.path.join(BUILD, label, f"{i:02d}-{sc['id']}"))
            print(f"  scene {i:02d} {sc['id']:<18} {r['kind']:<9} {r['dur']:6.1f}s" + (f"  MOCK (missing {r['missing']})" if r["missing"] else ""))
            results.append(r)
    finally:
        shooter.close()
    lst = os.path.join(BUILD, label, "concat.txt")
    with open(lst, "w", encoding="utf-8") as fh:
        fh.write("".join(f"file '{r['clip'].replace(os.sep, '/')}'\n" for r in results))
    joined = os.path.join(BUILD, label, "joined.mp4")
    ff(["-f", "concat", "-safe", "0", "-i", lst, "-c", "copy", joined])
    # timeline
    t0, en, ar, chaps = 0.0, [], [], []
    for sc, r in zip(scenes, results):
        if sc.get("chapter"):
            chaps.append((t0, sc["chapter"]))
        for c in r["cues"]:
            en.append((t0 + c["a"], t0 + c["b"], c["en"]))
            if c.get("ar"):
                ar.append((t0 + c["a"], t0 + c["ar_end"], c["ar"]))
        r["start"] = t0
        t0 += r["dur"]
    total = dur(joined)
    base = os.path.join(OUT, name)
    write_srt(base + ".srt", en)
    write_srt(base + ".ar.srt", ar)
    args = ["-i", joined, "-i", base + ".srt", "-i", base + ".ar.srt"]
    maps = ["-map", "0:v", "-map", "0:a", "-map", "1:0", "-map", "2:0"]
    if chapters and chaps:
        meta_f = os.path.join(BUILD, label, "chapters.ffmeta")
        with open(meta_f, "w", encoding="utf-8") as fh:
            fh.write(f";FFMETADATA1\ntitle={meta['title']}\n")
            for k, (a, title) in enumerate(chaps):
                b = chaps[k + 1][0] if k + 1 < len(chaps) else total
                fh.write(f"\n[CHAPTER]\nTIMEBASE=1/1000\nSTART={int(a * 1000)}\nEND={int(b * 1000)}\ntitle={title}\n")
        args += ["-i", meta_f]
        maps += ["-map_metadata", "3", "-map_chapters", "3"]
        with open(os.path.join(OUT, "chapters.txt"), "w", encoding="utf-8") as fh:
            fh.write("".join(f"{hms(a)} {title}\n" for a, title in chaps))
    else:
        maps += ["-metadata", f"title={meta['title']} (teaser)"]
    out = base + ".mp4"
    ff([*args, *maps, "-c:v", "libx264", "-preset", "slow", "-crf", str(crf), "-tune", "stillimage", "-pix_fmt", "yuv420p", "-r", str(FPS),
        "-c:a", "aac", "-b:a", "128k", "-metadata:s:a:0", "language=eng", "-c:s", "mov_text", "-metadata:s:s:0", "language=eng", "-metadata:s:s:0", "title=English",
        "-metadata:s:s:1", "language=ara", "-metadata:s:s:1", "title=Arabic", "-movflags", "+faststart", out], timeout=7200)
    size = os.path.getsize(out) / 1e6
    print(f"{out}: {dur(out):.1f}s, {size:.1f} MB, {len(chaps)} chapters")
    json.dump({"file": out, "seconds": dur(out), "mb": round(size, 1), "chapters": [(round(a, 2), t) for a, t in chaps],
               "scenes": [{"id": s["id"], "kind": r["kind"], "start": round(r["start"], 2), "dur": round(r["dur"], 2), "mock": bool(r["missing"]),
                           "tag": "MOCK" if r["missing"] else s.get("tag", "")} for s, r in zip(scenes, results)]},
              open(base + ".manifest.json", "w", encoding="utf-8"), indent=1)
    return results, chaps, total


def write_srt(path, cues):
    cues = sorted(cues)
    with open(path, "w", encoding="utf-8") as fh:
        for n, (a, b, t) in enumerate(cues):
            fh.write(f"{n + 1}\n{srt_time(a)} --> {srt_time(b)}\n{t}\n\n")


def write_script(spec, results=None):
    lines = [f"# {spec['meta']['title']}", "", "Narration script, generated from scenes.yaml by make_tutorial.py. "
             "Voice: " + spec["meta"].get("voice", "") + ". Tags: REAL OUTPUT / LIVE RECORDING = captured from the kit; "
             "ILLUSTRATION = explanatory slide; MOCK = feature not in the kit yet.", ""]
    words = 0
    for i, sc in enumerate(spec["scenes"]):
        if sc.get("chapter"):
            lines += [f"## {sc['chapter']}", ""]
        when = f"[{hms(results[i]['start'])}] " if results else ""
        tag = "MOCK" if missing_requires(sc) else sc.get("tag", "")
        lines.append(f"**{when}{sc.get('heading', sc['id'])}** ({sc['kind']}{', ' + tag if tag else ''})")
        lines.append("")
        for ln in sc.get("lines", []):
            words += len(ln["en"].split())
            lines.append(f"- {ln['en']}")
            lines.append(f"  - AR: {ln.get('ar', '')}")
        lines.append("")
    lines += ["## Teaser (60 s)", ""] + [f"- {ln['en']}" for sc in spec["teaser"] for ln in sc.get("lines", [])]
    lines += ["", f"_Narration words (tutorial): {words}_", ""]
    open(os.path.join(OUT, "script.md"), "w", encoding="utf-8").write("\n".join(lines))


# ======================================================================= thumbnail
def thumbnail():
    spec = load_spec()
    th = spec["thumbnail"]
    os.makedirs(OUT, exist_ok=True)
    doc = f"""<!doctype html><html><head><meta charset="utf-8"><style>{CSS}
html,body{{width:1280px;height:720px}}
.th{{position:absolute;inset:0;padding:70px 80px;background:radial-gradient(900px 600px at 85% 20%,rgba(45,212,191,.28),transparent 60%),
radial-gradient(700px 500px at 0% 100%,rgba(251,191,36,.16),transparent 60%),#0d1726}}
.th .kick{{font-size:30px;color:#2dd4bf;font-weight:800;letter-spacing:2px;text-transform:uppercase}}
.th h1{{font-size:150px;line-height:.95;margin:28px 0 22px;font-weight:900;letter-spacing:-4px}}.th h1 span{{color:#2dd4bf}}
.th .sub{{font-size:52px;font-weight:750;color:#fff;max-width:780px;line-height:1.12}}
.th .pill{{position:absolute;left:80px;bottom:62px;display:flex;gap:14px}}
.th .pill b{{font:700 26px Consolas,monospace;padding:10px 18px;border-radius:12px;background:#13213a;border:1px solid #24375a;color:#fbbf24}}
.th .logo{{position:absolute;right:80px;top:190px;width:260px;height:260px;filter:drop-shadow(0 20px 40px rgba(0,0,0,.5))}}
</style></head><body><div class="th"><div class="kick">{html.escape(th['kicker'])}</div><h1>Ship<span>Shape</span></h1>
<div class="sub">{html.escape(th['sub'])}</div><div class="logo">{LOGO}</div>
<div class="pill"><b>/qa-goal</b><b>2x tests</b><b>refuter</b><b>report.html</b></div></div></body></html>"""
    os.makedirs(BUILD, exist_ok=True)
    s = Shooter()
    try:
        out = s.shot(doc, os.path.join(OUT, "shipshape-thumbnail.png"), size=(1280, 720))
    finally:
        s.close()
    print(out)


# ======================================================================= privacy check
GENERIC = [
    ("windows path", re.compile(r"(?i)\b[A-Z]:[\\/]")),
    ("user home path", re.compile(r"(?i)[\\/](?:Users|home)[\\/][A-Za-z0-9._-]+")),
    ("email (non-example)", re.compile(r"(?i)\b[A-Za-z0-9._%+-]+@(?!example\.(?:com|org|net)\b)[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")),
    ("url (non-local)", re.compile(r"(?i)\bhttps?://(?!127\.0\.0\.1|localhost|example\.(?:com|org))[^\s'\"<>)]+")),
    ("token shape", re.compile(r"\b(?:sk-[A-Za-z0-9_-]{16,}|gh[pousr]_[A-Za-z0-9]{20,}|xox[abprs]-[A-Za-z0-9-]{10,}|AKIA[A-Z0-9]{16}|AIza[0-9A-Za-z_-]{30,}|eyJ[A-Za-z0-9_-]{10,}\.)")),
    ("phone", re.compile(r"(?<![\w.:-])\+\d{1,3}[ -]?\d{2,4}[ -]?\d{3,4}[ -]?\d{3,4}(?![\w.])")),
]
ALLOWED_PHONE = "+00 000 000 0000"


def text_sources():
    files = [os.path.join(HERE, "scenes.yaml")] + glob.glob(os.path.join(TR, "*.json"))
    files += [f for f in glob.glob(os.path.join(OUT, "*")) if f.endswith((".srt", ".txt", ".md", ".json"))]
    return files


def check():
    deny = []
    dp = os.environ.get("SMEKIT_DENYLIST")
    if dp and os.path.exists(dp):
        deny = [t.strip() for t in open(dp, encoding="utf-8") if t.strip() and not t.startswith("#")]
    hits = 0
    for f in text_sources():
        txt = open(f, encoding="utf-8", errors="replace").read()
        if f.endswith(".manifest.json"):
            txt = re.sub(r'"file": "[^"]*"', "", txt)
        for kind, rx in GENERIC:
            for m in rx.finditer(txt):
                if kind == "phone" and m.group(0).strip() == ALLOWED_PHONE.strip():
                    continue
                hits += 1
                print(f"  HIT {kind}: {os.path.relpath(f, HERE)} line {txt[:m.start()].count(chr(10)) + 1}")
        for i, term in enumerate(deny):
            for m in re.finditer(r"(?<![A-Za-z0-9])" + re.escape(term) + r"(?![A-Za-z0-9])", txt, re.I):
                hits += 1
                print(f"  HIT deny-list #{i}: {os.path.relpath(f, HERE)} line {txt[:m.start()].count(chr(10)) + 1}")
    r = subprocess.run([sys.executable, os.path.join(KIT, "scripts", "privacy.py"), "scan", *text_sources()],
                       capture_output=True, text=True, encoding="utf-8", errors="replace", env=clean_env())
    print("  kit privacy.py:", (r.stdout or r.stderr).strip().splitlines()[-1] if (r.stdout or r.stderr).strip() else r.returncode)
    print(f"text sources: {len(text_sources())} files, deny-list terms: {len(deny)}, generic+deny hits: {hits}")
    ocr_hits = ocr_frames(deny)
    return hits + max(ocr_hits, 0)


def ocr_frames(deny, step=2.0):
    """OCR every `step` seconds of the rendered videos (needs rapidocr_onnxruntime; skipped if absent)."""
    try:
        from rapidocr_onnxruntime import RapidOCR
    except ImportError:
        print("OCR: rapidocr_onnxruntime not installed -> skipped (text sources were checked)")
        return -1
    eng = RapidOCR()
    hits = 0
    for vid in glob.glob(os.path.join(OUT, "*.mp4")):
        fd = os.path.join(BUILD, "ocr", os.path.basename(vid))
        shutil.rmtree(fd, ignore_errors=True)
        os.makedirs(fd)
        ff(["-i", vid, "-vf", f"fps=1/{step}", os.path.join(fd, "%05d.png")])
        frames = sorted(glob.glob(os.path.join(fd, "*.png")))
        for k, fr in enumerate(frames):
            res, _ = eng(fr)
            txt = " ".join(r[1] for r in (res or []))
            for kind, rx in GENERIC:
                for m in rx.finditer(txt):
                    if kind == "phone" and ALLOWED_PHONE in txt:
                        continue
                    hits += 1
                    print(f"  OCR HIT {kind} in {os.path.basename(vid)} at {hms(k * step)}: {m.group(0)[:3]}...")
            for i, term in enumerate(deny):
                if re.search(r"(?<![A-Za-z0-9])" + re.escape(term) + r"(?![A-Za-z0-9])", txt, re.I):
                    hits += 1
                    print(f"  OCR HIT deny-list #{i} in {os.path.basename(vid)} at {hms(k * step)}")
        print(f"OCR: {os.path.basename(vid)}: {len(frames)} frames checked")
    return hits


# ======================================================================= main
def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("cmd", nargs="?", default="all", choices=("capture", "render", "teaser", "thumb", "check", "all"))
    ap.add_argument("--with-claude", action="store_true")
    ap.add_argument("--crf", type=int, default=24)
    a = ap.parse_args(argv)
    os.makedirs(BUILD, exist_ok=True)
    spec = load_spec()
    if a.cmd in ("capture", "all"):
        capture(a.with_claude)
    if a.cmd in ("render", "all"):
        res, chaps, total = build_video(spec["scenes"], "shipshape-tutorial", chapters=True, crf=a.crf, label="tutorial")
        write_script(spec, res)
    if a.cmd in ("teaser", "all"):
        _, _, total = build_video(spec["teaser"], "shipshape-teaser", chapters=False, crf=a.crf, label="teaser")
        if total > 60.5:
            print(f"WARNING: teaser is {total:.1f}s (> 60 s): shorten the teaser lines in scenes.yaml")
    if a.cmd in ("thumb", "all"):
        thumbnail()
    if a.cmd in ("check", "all"):
        n = check()
        print("PRIVACY CHECK:", "clean" if n == 0 else f"{n} hit(s) - fix before publishing")
        return 1 if n else 0
    return 0


if __name__ == "__main__":
    sys.exit(main())
