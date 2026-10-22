#!/usr/bin/env python3
"""Desktop control for flows outside the browser (native apps, OS dialogs, file
pickers, Electron apps), with safety gates and a recorded, logged run.

Primary engine: Claude's own computer-use capability, when the user's Claude
has it. This module is the kit's fallback layer:
  Windows  pywinauto (UIA backend) for windows and controls + pyautogui for keys/mouse/screenshots
  macOS    osascript (AppleScript) for apps and windows + pyautogui (grant Accessibility and
           Screen Recording to the terminal in System Settings > Privacy & Security)
  video    ffmpeg gdigrab (Windows) / avfoundation (macOS) screen recording

    python scripts/desktop.py run steps.json --config qa.config.yaml --out qa-runs/<run>/desktop [--dry-run]

steps.json: [{"do": "open", "app": "notepad"}, {"do": "type", "text": "hello", "window": "Notepad"},
             {"do": "key", "keys": ["ctrl", "s"], "confirmed": false}, {"do": "screenshot", "name": "typed"}]

Safety gates (all enforced here, and repeated as plain-language hooks):
  - desktop control runs only when qa.config.yaml has desktop.enabled: true
  - apps/windows must match desktop.allow_apps (case-insensitive substring)
  - banking / payment / password-manager apps are always refused
  - never types into a password field (UIA IsPassword on Windows; refused by name otherwise)
  - irreversible actions (delete, send, purchase, pay, install, uninstall, format, submit, save over)
    stop and ask: they need "confirmed": true, set only after the user OK'd it in the conversation
  - a visible always-on-top notice "Agent is controlling this desktop" while it runs
  - emergency stop: move the mouse into a screen corner (pyautogui FAILSAFE) -> abort
  - every action (done, refused or dry-run) is appended to <out>/desktop-actions.jsonl
"""
from __future__ import annotations

import argparse
import json
import os
import platform
import re
import shutil
import signal
import subprocess
import sys
import time

BLOCKED_APPS = re.compile(r"(?i)bank|banking|paypal|wallet|payment|pay\b|stripe|crypto|coinbase|binance|1password|bitwarden|keepass|lastpass|keychain|credential")
IRREVERSIBLE = re.compile(r"(?i)\b(delete|remove|erase|send|submit|purchase|buy|pay|checkout|install|uninstall|format|shutdown|restart|empty trash|overwrite|transfer)\b")
PASSWORD_HINT = re.compile(r"(?i)pass(word|code)?|pin\b|secret|otp")


class Refused(Exception):
    pass


class Gate:
    """All safety decisions in one place, so they are testable without a desktop."""

    def __init__(self, cfg):
        d = (cfg or {}).get("desktop") or {}
        self.enabled = bool(d.get("enabled"))
        self.allow = [a.lower() for a in d.get("allow_apps", [])]

    def check(self, step):
        if not self.enabled:
            raise Refused("desktop control is disabled for this project (desktop.enabled: false)")
        target = " ".join(str(step.get(k, "")) for k in ("app", "window"))
        if BLOCKED_APPS.search(target):
            raise Refused("banking / payment / password apps are never controlled")
        if target.strip() and not any(a in target.lower() for a in self.allow):
            raise Refused(f"'{target.strip()}' is not in desktop.allow_apps")
        if step.get("do") in ("open", "focus") and not target.strip():
            raise Refused("open/focus needs an app or window from the allow-list")
        if step.get("do") == "type" and PASSWORD_HINT.search(str(step.get("field", "")) + " " + str(step.get("window", ""))):
            raise Refused("never types into password fields")
        words = " ".join(str(step.get(k, "")) for k in ("do", "label", "text", "keys", "control"))
        if (IRREVERSIBLE.search(words) or step.get("irreversible")) and not step.get("confirmed"):
            raise Refused("irreversible action: stop and ask the user, then set confirmed=true")


# ------------------------------------------------------------------ backends
class DryRun:
    def __getattr__(self, name):
        return lambda *a, **k: None


class Backend:
    """Real desktop. Imports are lazy so the module loads anywhere."""

    def __init__(self):
        import pyautogui
        pyautogui.FAILSAFE = True  # mouse into a corner -> pyautogui.FailSafeException -> abort
        pyautogui.PAUSE = 0.15
        self.pg = pyautogui
        self.os = platform.system()

    def open(self, app):
        if self.os == "Windows":
            subprocess.Popen([app] if os.path.splitext(app)[1] else [app + ".exe"])
        elif self.os == "Darwin":
            subprocess.run(["open", "-a", app], check=True, timeout=30)
        else:
            subprocess.Popen([app])
        time.sleep(1.5)

    def focus(self, window):
        if self.os == "Windows":
            from pywinauto import Desktop
            w = Desktop(backend="uia").window(title_re=f"(?i).*{re.escape(window)}.*")
            w.wait("exists ready", timeout=15)
            w.set_focus()
            return w
        if self.os == "Darwin":
            subprocess.run(["osascript", "-e", f'tell application "{window}" to activate'], check=True, timeout=15)
        return None

    def is_password_focused(self):
        if self.os != "Windows":
            return False
        try:
            from pywinauto import Desktop
            el = Desktop(backend="uia").get_active().element_info  # noqa: F841
            import comtypes.client  # noqa: F401
            from pywinauto.uia_defines import IUIA
            focused = IUIA().iuia.GetFocusedElement()
            return bool(focused.CurrentIsPassword)
        except Exception:  # noqa: BLE001
            return False

    def type(self, text):
        self.pg.write(text, interval=0.03)

    def key(self, keys):
        self.pg.hotkey(*keys)

    def click(self, x, y):
        self.pg.click(x, y)

    def screenshot(self, path):
        self.pg.screenshot(path)


class Notice:
    """Always-on-top banner while the agent controls the desktop."""

    def __init__(self, enabled=True):
        self.p = None
        if enabled:
            code = ("import tkinter as t;r=t.Tk();r.overrideredirect(1);r.attributes('-topmost',1);"
                    "r.geometry('+20+20');t.Label(r,text='Agent is controlling this desktop - move the mouse to a corner to stop',"
                    "bg='#b3261e',fg='white',font=('Segoe UI',11,'bold'),padx=12,pady=6).pack();r.mainloop()")
            try:
                self.p = subprocess.Popen([sys.executable, "-c", code])
            except OSError:
                self.p = None

    def close(self):
        if self.p:
            self.p.terminate()


def record_cmd(out_mp4, seconds=None, system=None, fps=15):
    """ffmpeg screen-capture command for this OS (gdigrab / avfoundation / x11grab)."""
    system = system or platform.system()
    if system == "Windows":
        src = ["-f", "gdigrab", "-framerate", str(fps), "-i", "desktop"]
    elif system == "Darwin":
        src = ["-f", "avfoundation", "-framerate", str(fps), "-capture_cursor", "1", "-i", os.environ.get("SMEKIT_AVF_SCREEN", "1:none")]
    else:
        src = ["-f", "x11grab", "-framerate", str(fps), "-i", os.environ.get("DISPLAY", ":0")]
    dur = ["-t", str(seconds)] if seconds else []
    return ["ffmpeg", "-y", "-v", "error", *src, *dur, "-vf", "scale='min(1920,iw)':-2", "-c:v", "libx264", "-preset", "veryfast",
            "-pix_fmt", "yuv420p", out_mp4]


def run(steps, cfg, out, dry_run=False, backend=None, record=True, notice=True):
    os.makedirs(out, exist_ok=True)
    log_path = os.path.join(out, "desktop-actions.jsonl")
    gate = Gate(cfg)
    be = backend or (DryRun() if dry_run else Backend())
    rec = None
    results = []
    note = Notice(notice and not dry_run)

    def log(entry):
        entry["t"] = time.strftime("%Y-%m-%dT%H:%M:%S")
        with open(log_path, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(entry) + "\n")

    try:
        if record and not dry_run and shutil.which("ffmpeg"):
            rec = subprocess.Popen(record_cmd(os.path.join(out, "desktop.mp4")), stdin=subprocess.PIPE)
        for i, s in enumerate(steps):
            try:
                gate.check(s)
            except Refused as exc:
                log({"step": i + 1, "do": s.get("do"), "status": "REFUSED", "why": str(exc)})
                results.append({"id": s.get("case", f"desktop-{i + 1}"), "title": s.get("do"), "result": "BLOCKED", "evidence": "", "note": str(exc)})
                break
            do = s["do"]
            if do == "type" and not dry_run and be.is_password_focused():
                log({"step": i + 1, "do": do, "status": "REFUSED", "why": "focused field is a password field"})
                results.append({"id": s.get("case", f"desktop-{i + 1}"), "title": do, "result": "BLOCKED", "evidence": "", "note": "password field"})
                break
            if do == "open":
                be.open(s["app"])
            elif do == "focus":
                be.focus(s["window"])
            elif do == "type":
                if s.get("window"):
                    be.focus(s["window"])
                be.type(s["text"])
            elif do == "key":
                be.key(s["keys"])
            elif do == "click":
                be.click(s["x"], s["y"])
            elif do == "wait":
                time.sleep(min(float(s.get("sec", 1)), 30))
            elif do == "screenshot":
                p = os.path.join(out, f"{i + 1:02d}-{s.get('name', 'screen')}.png")
                be.screenshot(p)
                results.append({"id": s.get("case", f"desktop-{i + 1}"), "title": s.get("name", "screenshot"), "result": "PASS",
                                "evidence": os.path.basename(p)})
            log({"step": i + 1, "do": do, "status": "DRY-RUN" if dry_run else "DONE",
                 "target": s.get("app") or s.get("window"), "chars": len(s.get("text", "")) if do == "type" else None})
    except Exception as exc:  # noqa: BLE001 - includes pyautogui.FailSafeException (emergency stop)
        name = type(exc).__name__
        log({"status": "ABORTED", "why": f"{name}: {str(exc)[:160]}"})
        results.append({"id": "desktop-abort", "title": "run", "result": "BLOCKED", "evidence": "", "note": f"aborted: {name}"})
    finally:
        if rec:
            try:
                rec.stdin.write(b"q")
                rec.stdin.flush()
                rec.wait(timeout=20)
            except Exception:  # noqa: BLE001
                rec.send_signal(signal.SIGTERM)
        note.close()
    return results


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("cmd", choices=("run", "record-cmd"))
    ap.add_argument("steps", nargs="?")
    ap.add_argument("--config", default="qa.config.yaml")
    ap.add_argument("--out", default="qa-evidence/desktop")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--no-record", action="store_true")
    a = ap.parse_args(argv)
    if a.cmd == "record-cmd":
        print(" ".join(record_cmd(os.path.join(a.out, "desktop.mp4"), 5)))
        return 0
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import notify
    import report
    cfg = notify.load_config(a.config) if os.path.exists(a.config) else {}
    steps = json.load(open(a.steps, encoding="utf-8"))
    res = run(steps, cfg, a.out, a.dry_run, record=not a.no_record)
    counts, _ = report.count(res)
    print(report.summary(counts), "| log:", os.path.join(a.out, "desktop-actions.jsonl"))
    return 0 if counts["BLOCKED"] == 0 and counts["FAIL"] == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
