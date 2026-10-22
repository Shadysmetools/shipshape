#!/usr/bin/env python3
"""ShipShape doctor: is everything the QA crew needs installed and working?

    python scripts/doctor.py [--json]

Checks: python, node/npx, ffmpeg/ffprobe, Python packages (playwright, openpyxl,
PyYAML, edge-tts, pytest; optional pyautogui/pywinauto/keyring/pip-audit),
Playwright browsers, the pinned MCP packages resolvable by npx, k6, gitleaks,
edge-tts synthesis (network), and env vars for configured channels (names only).
Nothing is installed or changed; it prints the fix for every missing piece.
"""
from __future__ import annotations

import importlib.util
import json
import os
import platform
import shutil
import subprocess
import sys

REQUIRED_PY = ["playwright", "openpyxl", "yaml", "edge_tts", "pytest"]
OPTIONAL_PY = {"pyautogui": "desktop control", "pywinauto": "desktop control (Windows)", "keyring": "secrets from the OS keychain",
               "pip_audit": "dependency audit"}
MCP = ["@playwright/mcp@0.0.83", "chrome-devtools-mcp@1.10.1"]


def run(cmd, timeout=60):
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return p.returncode, (p.stdout or p.stderr).strip()
    except (OSError, subprocess.SubprocessError) as exc:
        return -1, str(exc)


def check():
    rows = []

    def add(name, status, detail, fix=""):
        rows.append({"check": name, "status": status, "detail": detail, "fix": fix})

    add("python", "OK" if sys.version_info >= (3, 10) else "FAIL", platform.python_version(), "Install Python 3.10+")
    for tool, fix in (("node", "Install Node.js 20+"), ("npx", "Comes with Node.js"), ("ffmpeg", "Install ffmpeg (winget install Gyan.FFmpeg / brew install ffmpeg)"),
                      ("ffprobe", "Comes with ffmpeg"), ("git", "Install git")):
        path = shutil.which(tool)
        add(tool, "OK" if path else "FAIL", path or "not found", fix)
    for mod in REQUIRED_PY:
        ok = importlib.util.find_spec(mod) is not None
        add(f"py:{mod}", "OK" if ok else "FAIL", "installed" if ok else "missing", "pip install -r requirements.txt")
    for mod, why in OPTIONAL_PY.items():
        ok = importlib.util.find_spec(mod) is not None
        add(f"py:{mod}", "OK" if ok else "OPTIONAL", ("installed" if ok else "missing") + f" ({why})", f"pip install {mod.replace('_', '-')}")
    if importlib.util.find_spec("playwright"):
        code = ("from playwright.sync_api import sync_playwright\nwith sync_playwright() as p:\n b=p.chromium.launch(); b.close(); print('ok')")
        rc, out = run([sys.executable, "-c", code], 120)
        add("playwright chromium", "OK" if rc == 0 else "FAIL", "launches" if rc == 0 else out[-160:], "python -m playwright install chromium")
    for pkg in MCP:
        if shutil.which("npm"):
            rc, out = run(["npm", "view", pkg, "version"], 60) if os.name != "nt" else run(["cmd", "/c", "npm", "view", pkg, "version"], 60)
            add(f"mcp:{pkg}", "OK" if rc == 0 and out else "WARN", out or "not resolvable (offline?)", "Check network; npx downloads it on first use")
    for tool, why, fix in (("k6", "heavier load tests", "winget install k6 / brew install k6"), ("gitleaks", "secret scanning", "winget install gitleaks / brew install gitleaks"),
                           ("osv-scanner", "dependency audit", "go install github.com/google/osv-scanner/cmd/osv-scanner@v1")):
        path = shutil.which(tool)
        add(tool, "OK" if path else "OPTIONAL", path or f"missing ({why})", fix)
    if importlib.util.find_spec("edge_tts") and os.environ.get("SMEKIT_DOCTOR_TTS", "1") == "1":
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        try:
            import tts
            p, d, _ = tts.speak("ShipShape voice check.")
            add("narration (edge-tts)", "OK", f"{d:.1f}s clip")
        except Exception as exc:  # noqa: BLE001
            add("narration (edge-tts)", "WARN", str(exc)[:120], "Needs network; captions still work without it")
    for var in ("TELEGRAM_BOT_TOKEN", "WHATSAPP_TOKEN", "SLACK_WEBHOOK_URL", "SMTP_PASSWORD", "OPENAI_API_KEY", "ELEVENLABS_API_KEY"):
        add(f"env:{var}", "SET" if os.environ.get(var) else "unset", "value never printed", "Only needed if a channel/provider uses it")
    return rows


def main():
    rows = check()
    if "--json" in sys.argv:
        print(json.dumps(rows, indent=1))
    else:
        print("ShipShape doctor - your autonomous QA crew")
        for r in rows:
            line = f"  [{r['status']:8}] {r['check']}: {r['detail']}"
            if r["status"] in ("FAIL", "WARN") and r["fix"]:
                line += f"  -> {r['fix']}"
            print(line)
    fails = [r for r in rows if r["status"] == "FAIL"]
    print(f"\n{sum(r['status'] in ('OK', 'SET') for r in rows)} ok / {len(fails)} fail / "
          f"{sum(r['status'] in ('OPTIONAL', 'WARN', 'unset') for r in rows)} optional or warnings")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
