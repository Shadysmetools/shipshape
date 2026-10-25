#!/usr/bin/env python3
"""Full-device control: drive any local app (Notepad, Claude Desktop, OS dialogs, Electron apps),
not just the browser. Gated, recorded and logged.

Engines (in order):
  uia       Windows UI Automation through pywinauto (backend "uia"): list windows, find controls by
            name/role, click, type, read text. The primary engine.
  pixel     screenshot + coordinate click/type through pyautogui: the fallback when an app exposes no
            controls (games, canvas apps). Use "x"/"y" (screen pixels) or "at": [fx, fy] (fractions of
            the target window).
  computer-use  Claude computer use through the Anthropic API (optional, documented in
            docs/DESKTOP-CONTROL.md). It needs the user's own ANTHROPIC_API_KEY through keys.py.
            ShipShape ships no keys. `desktop.py engines` shows what is available.
  macOS     osascript for apps and windows + pyautogui (grant Accessibility and Screen Recording).

    python scripts/desktop.py run steps.json --config qa.config.yaml --out qa-runs/<run>/desktop [--dry-run]
                              [--passes 2] [--narrate] [--step-timeout 20] [--run-timeout 180]
    python scripts/desktop.py windows --config qa.config.yaml        # allow-listed windows only
    python scripts/desktop.py inspect "Notepad" --config qa.config.yaml [--roles Edit,Button,Document]
    python scripts/desktop.py engines

steps.json is a list of steps (or {"name": ..., "steps": [...]}). Verbs:
  launch   {"app": "notepad"}           by path, Start-menu name (AUMID) or PATH; waits for its window
                                        ("require_new": true = only a window this launch opened)
  open     alias of launch
  focus    {"window": "Notepad"}        switch to an allow-listed window (alias: switch)
  minimize / close                      the target window (close = WM_CLOSE, never a kill; if the app asks
                                        to save, Cancel is pressed; "only_if_launched": true = only a
                                        window this run opened, "otherwise": "minimize")
  wait_window {"window": "...", "timeout": 15}
  wait_text   {"text": "...", "timeout": 10}            text appears in the target window
  click    {"control": {"name": "Cancel", "role": "Button", "in": {"role": "Window", "name": "Save as"}}}
           | {"x": 10, "y": 20} (screen pixels, pixel engine) | {"at": [0.5, 0.9]} (fractions of the window)
  type     {"text": "...", "control": {...}}            types into the control, or the focused field
  key      {"keys": ["ctrl", "n"]}                      shortcut; "win" is refused
  scroll   {"amount": -5}
  read     {"control": {...}, "save_as": "typed"}       read a control's text (logged as a length only)
  clipboard_set {"text": "..."} / clipboard_get {"save_as": "clip"}
  assert_text   {"control": {...}, "equals": "..."} | {"contains": "..."} | {"equals_var": "typed"}
  assert_window {"window": "...", "present": true}
  assert_control {"control": {...}, "present": false}   a control (a dialog, a button) is there or gone
  mask     {"rect": [fx0, fy0, fx1, fy1]} (fractions; add "within": {control} to measure inside a dialog)
           | {"control": {...}} | {"above_control": {...}} | {"outside_control": {...}, "pad": 8}
           | {"regions": [<several of these>], "replace": true} (swap masks with no gap)
           a blurred (pixelated) privacy overlay over part of the window (it shows in the video and the
           screenshots). control + "largest": true picks the biggest match; "optional": true skips a region that
           is not on screen. Masks may cover at most desktop.mask_max_cover (default 40%) of the window and never
           the controls the next steps type into or read; "allow_large": true for a deliberate full cover.
           Mask BEFORE a step that opens something private (a file dialog), then narrow it.
  unmask   remove all overlays
  record_start  start the screen recording of the target window (default: right after the first
                launch/focus); {"region": "screen"} records every monitor
  screenshot {"name": "...", "region": "window|screen|monitor:N"}
  wait     {"sec": 1.5}
Every step may carry "case" (a report id), "say" (narration), "shot": false (no screenshot),
"timeout" (seconds), "stop_on_fail": true (a failed check stops the run) and "confirmed": true
(only after the owner OK'd an irreversible step).

Safety gates (enforced here; hooks/hook_guard.py repeats the static ones before a run starts):
  - runs only when qa.config.yaml has desktop.enabled: true
  - apps/windows must match desktop.allow_apps (process name or window title, case-insensitive)
  - before EVERY input (type, key, click, scroll) the foreground window is checked: it must be the
    window under test (or its dialog), an allow-listed app, never a terminal, never this agent's own
    process chain, never a UAC prompt. Typing re-checks the focus before every character, so if
    another window jumps in front, at most one character can land there and the run stops
  - if a person is using the keyboard or mouse, the run waits for a quiet moment, then stops
  - banking / payment / password-manager apps, UAC / installer prompts: always refused
  - never types into a password field (UIA IsPassword); password fields are blacked out in screenshots
  - irreversible actions (delete, send, submit, purchase, pay, install, discard, don't save ...) and
    Enter / newlines in chat apps (they send) need "confirmed": true after the owner's OK
  - a visible always-on-top banner "ShipShape is controlling this PC" while it runs
  - emergency stop: move the mouse into a screen corner (pyautogui FAILSAFE) -> abort
  - per-step timeout (desktop.step_timeout, default 20 s) and per-run timeout (desktop.run_timeout,
    default 180 s, also the recording's hard ceiling)
  - typed text and read text are never logged, only their length
  - every action (done, refused, failed or dry-run) is appended to <out>/desktop-actions.jsonl
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
import threading
import time

HERE = os.path.dirname(os.path.abspath(__file__))

BLOCKED_APPS = re.compile(r"(?i)bank|banking|paypal|wallet|payment|pay\b|stripe|crypto|coinbase|binance|1password|bitwarden|keepass|lastpass|keychain|credential")
IRREVERSIBLE = re.compile(r"(?i)\b(delete|remove|erase|send|submit|purchase|buy|pay|checkout|install|uninstall|format|shutdown|restart|empty trash|overwrite|transfer|discard)\b|\bdon'?t save\b")
PASSWORD_HINT = re.compile(r"(?i)pass(word|code)?|pin\b|secret|otp")
UAC = re.compile(r"(?i)user account control|credential dialog|windows security|\binstall(er|shield| wizard)\b|setup wizard|\bmsiexec\b|consent\.exe")
UAC_CLASSES = {"Credential Dialog Xaml Host", "$$$Secure UAP Dummy Window Class For Interim Dialog"}
TERMINAL_PROCS = re.compile(r"(?i)^(windowsterminal|openconsole|conhost|cmd|powershell|pwsh|wt|bash|mintty|wsl|wslhost|code|cursor|alacritty|wezterm-gui|terminal|iterm2|warp)$")
TERMINAL_CLASSES = {"ConsoleWindowClass", "CASCADIA_HOSTING_WINDOW_CLASS", "PseudoConsoleWindow", "mintty", "VirtualConsoleClass"}
CHAT_APPS = re.compile(r"(?i)claude|chatgpt|slack|teams|whatsapp|telegram|outlook|discord|signal|messenger|mail")
TARGET_VERBS = ("launch", "open", "focus", "switch", "wait_window", "assert_window")
INPUT_VERBS = ("type", "key", "click", "scroll")
VERBS = TARGET_VERBS + INPUT_VERBS + ("minimize", "close", "wait_text", "read", "clipboard_set", "clipboard_get",
                                      "assert_text", "assert_control", "mask", "unmask", "record_start", "screenshot", "wait")
CHECK_VERBS = ("assert_text", "assert_window", "assert_control", "wait_text", "wait_window")
BANNER_TEXT = "ShipShape is controlling this PC - move the mouse into a screen corner to stop"


class Refused(Exception):
    pass


class StepFailed(Exception):
    pass


def _ctl_text(c):
    if isinstance(c, dict):
        return " ".join(str(c.get(k, "")) for k in ("name", "name_re", "role", "auto_id"))
    return str(c or "")


class Gate:
    """All safety decisions in one place, so they are testable without a desktop."""

    def __init__(self, cfg):
        d = (cfg or {}).get("desktop") or {}
        self.enabled = bool(d.get("enabled"))
        self.allow = [str(a).lower() for a in d.get("allow_apps", [])]

    # ---- static: the step itself (also run by hooks/hook_guard.py before anything starts)
    def check(self, step):
        if not self.enabled:
            raise Refused("desktop control is disabled for this project (desktop.enabled: false)")
        do = step.get("do")
        if do not in VERBS:
            raise Refused(f"unknown step '{do}'")
        target = " ".join(str(step.get(k, "")) for k in ("app", "window"))
        if BLOCKED_APPS.search(target):
            raise Refused("banking / payment / password apps are never controlled")
        if UAC.search(target):
            raise Refused("UAC / installer prompts are never operated: the owner handles them")
        if target.strip() and not any(a in target.lower() for a in self.allow):
            raise Refused(f"'{target.strip()}' is not in desktop.allow_apps")
        if do in TARGET_VERBS and not target.strip():
            raise Refused(f"{do} needs an app or window from the allow-list")
        if do == "type" and PASSWORD_HINT.search(str(step.get("field", "")) + " " + str(step.get("window", "")) + " " + _ctl_text(step.get("control"))):
            raise Refused("never types into password fields")
        keys = [str(k).lower() for k in step.get("keys", [])] if do == "key" else []
        if any(k in ("win", "winleft", "winright", "super", "command") for k in keys):
            raise Refused("the Windows key leaves the target app: use a launch step instead")
        words = " ".join(str(step.get(k, "")) for k in ("do", "label", "text", "keys")) + " " + _ctl_text(step.get("control"))
        if (IRREVERSIBLE.search(words) or step.get("irreversible")) and not step.get("confirmed"):
            raise Refused("irreversible action: stop and ask the user, then set confirmed=true")

    # ---- runtime: what is really on screen
    def allowed_window(self, info):
        """True when a window (dict: title, process, cls, pid) is an allow-listed app."""
        if not info:
            return False
        proc = (info.get("process") or "").lower()
        title = (info.get("title") or "").lower()
        for a in self.allow:
            if a.startswith("title:"):
                if a[6:] and a[6:] in title:
                    return True
            elif a and (a == proc or a in proc or (proc in ("applicationframehost",) and a in title)):
                return True
        return False

    def check_window(self, info, own_pids=(), chat_guard=None):
        """Refuse input unless the foreground window is a safe, allow-listed app window."""
        if info is None:
            return  # a test double without a real screen
        if not info.get("hwnd"):
            raise Refused("cannot tell which window has the focus: input refused")
        if info.get("pid") in set(own_pids):
            raise Refused("the focused window belongs to the agent's own terminal: input refused")
        if info.get("cls") in TERMINAL_CLASSES or TERMINAL_PROCS.match(info.get("process") or ""):
            raise Refused("the focused window is a terminal or editor: input refused")
        if info.get("cls") in UAC_CLASSES or UAC.search(info.get("title") or "") or (info.get("process") or "").lower() == "consent":
            raise Refused("a UAC / installer prompt has the focus: the owner handles it")
        if BLOCKED_APPS.search((info.get("title") or "") + " " + (info.get("process") or "")):
            raise Refused("banking / payment / password apps are never controlled")
        if not self.allowed_window(info):
            raise Refused(f"the focused window ({info.get('process')}) is not in desktop.allow_apps: input refused")

    @staticmethod
    def check_send(step, info):
        """Enter or a newline in a chat app sends a message: that needs the owner's OK."""
        if step.get("confirmed") or not info:
            return
        if not CHAT_APPS.search((info.get("process") or "") + " " + (info.get("title") or "")):
            return
        keys = [str(k).lower() for k in step.get("keys", [])] if step.get("do") == "key" else []
        if any(k in ("enter", "return") for k in keys) or "\n" in str(step.get("text", "")) or "\r" in str(step.get("text", "")):
            raise Refused("Enter in a chat app sends a message: stop and ask the user, then set confirmed=true")


# ------------------------------------------------------------------ helpers
def own_pids():
    """This process and its ancestors (the agent's terminal and Claude Code): never a target."""
    pids = {os.getpid()}
    try:
        import psutil
        p = psutil.Process()
        while p is not None:
            pids.add(p.pid)
            p = p.parent()
    except Exception:  # noqa: BLE001
        pids.add(os.getppid())
    return pids


def frac_rect(win, fr):
    """[fx0, fy0, fx1, fy1] fractions of a window rect (l, t, r, b) -> pixel rect."""
    l, t, r, b = win
    w, h = r - l, b - t
    return (int(l + fr[0] * w), int(t + fr[1] * h), int(l + fr[2] * w), int(t + fr[3] * h))


def outside(win, hole, pad=0):
    """Four rects covering a window except a hole (a control): mask everything but the input box."""
    l, t, r, b = win
    hl, ht, hr, hb = hole[0] - pad, hole[1] - pad, hole[2] + pad, hole[3] + pad
    rects = [(l, t, r, max(t, ht)), (l, min(b, hb), r, b), (l, max(t, ht), max(l, hl), min(b, hb)), (min(r, hr), max(t, ht), r, min(b, hb))]
    return [x for x in rects if x[2] > x[0] and x[3] > x[1]]


MASK_MAX_COVER = 0.40  # default: masks may hide at most 40% of the window; the app under test stays visible


def clip_rect(r, win):
    """r clipped to win, or None when nothing is left."""
    c = (max(r[0], win[0]), max(r[1], win[1]), min(r[2], win[2]), min(r[3], win[3]))
    return c if c[2] > c[0] and c[3] > c[1] else None


def subtract(r, hole):
    """r minus hole: up to four rects."""
    h = clip_rect(hole, r)
    if not h:
        return [r]
    out = [(r[0], r[1], r[2], h[1]), (r[0], h[3], r[2], r[3]), (r[0], h[1], h[0], h[3]), (h[2], h[1], r[2], h[3])]
    return [x for x in out if x[2] > x[0] and x[3] > x[1]]


def union_area(rects):
    """Area covered by rects (overlaps counted once)."""
    rects = [r for r in rects if r[2] > r[0] and r[3] > r[1]]
    xs = sorted({v for r in rects for v in (r[0], r[2])})
    total = 0
    for x0, x1 in zip(xs, xs[1:]):
        spans = sorted((r[1], r[3]) for r in rects if r[0] <= x0 and r[2] >= x1)
        cov, end = 0, None
        for a, b in spans:
            if end is None or a > end:
                cov += b - a
                end = b
            elif b > end:
                cov += b - end
                end = b
        total += cov * (x1 - x0)
    return total


def fit_masks(masks, win, keep=(), max_cover=MASK_MAX_COVER):
    """Masks with the controls under test (keep) cut out of them, so a mask can never hide
    the control a step types into or reads. Raises StepFailed when they would still cover more than max_cover of
    the window (None = no cap, for a deliberate full cover such as a Save As dialog). -> (rects, fraction)."""
    out = []
    for m in masks:  # not clipped: a dialog may stick out of the window and must stay covered
        pieces = [tuple(int(v) for v in m)]
        for k in keep:
            pieces = [p for q in pieces for p in subtract(q, k)]
        out += [p for p in pieces if p[2] > p[0] and p[3] > p[1]]
    win_area = max(1, (win[2] - win[0]) * (win[3] - win[1]))
    frac = union_area([c for c in (clip_rect(p, win) for p in out) if c]) / win_area
    if max_cover is not None and frac > max_cover:
        raise StepFailed(f"the privacy masks would hide {frac:.0%} of the window (limit {max_cover:.0%}): mask only the "
                         "private parts (sidebar, chat list, account), or set \"allow_large\": true on a deliberate full cover")
    return out, frac


def pixelate(img, block=22, blur=6):
    """A PIL image made unreadable but still recognisable as UI: coarse blocks, then a blur."""
    from PIL import Image, ImageFilter
    w, h = img.size
    small = img.resize((max(1, w // block), max(1, h // block)), Image.BILINEAR)
    return small.resize((w, h), Image.NEAREST).filter(ImageFilter.GaussianBlur(blur))


def even_region(rect, bounds=None):
    """Clip a rect to the virtual screen and make width/height even (yuv420p needs it)."""
    l, t, r, b = rect
    if bounds:
        bl, bt, br, bb = bounds
        l, t, r, b = max(l, bl), max(t, bt), min(r, br), min(b, bb)
    w, h = max(2, r - l), max(2, b - t)
    return l, t, w - w % 2, h - h % 2


def send_keys_text(text):
    """Escape text for pywinauto.keyboard.send_keys (literal characters, no modifiers)."""
    return "".join("{%s}" % c if c in "{}+^%~()[]" else c for c in text)


# ------------------------------------------------------------------ backends
class DryRun:
    def __getattr__(self, name):
        return lambda *a, **k: None


class Backend:
    """Real desktop. Imports are lazy so the module loads anywhere."""

    def __init__(self, step_timeout=20):
        self.os = platform.system()
        if self.os == "Windows":
            import ctypes
            try:
                ctypes.windll.shcore.SetProcessDpiAwareness(2)  # one pixel grid for UIA, clicks, mss and ffmpeg
            except Exception:  # noqa: BLE001
                pass
        import pyautogui
        pyautogui.FAILSAFE = True  # mouse into a corner -> pyautogui.FailSafeException -> abort
        pyautogui.PAUSE = 0.15
        self.pg = pyautogui
        self.step_timeout = step_timeout
        self.target = None  # hwnd of the window under test
        self.launched_new = False
        self._last_sent = 0.0
        self.allow = None
        self._apps = None

    # ---- windows
    def _info(self, hwnd):
        import win32gui
        import win32process
        try:
            _, pid = win32process.GetWindowThreadProcessId(hwnd)
        except Exception:  # noqa: BLE001
            return None
        exe = ""
        try:
            import psutil
            exe = psutil.Process(pid).exe()
        except Exception:  # noqa: BLE001
            pass
        return {"hwnd": hwnd, "title": win32gui.GetWindowText(hwnd), "cls": win32gui.GetClassName(hwnd), "pid": pid,
                "process": os.path.splitext(os.path.basename(exe))[0], "exe": exe, "rect": tuple(win32gui.GetWindowRect(hwnd))}

    def windows(self):
        if self.os != "Windows":
            return []
        import win32gui
        hw = []
        win32gui.EnumWindows(lambda h, _: hw.append(h) if win32gui.IsWindowVisible(h) and win32gui.GetWindowText(h) else None, None)
        return [i for i in (self._info(h) for h in hw) if i]  # z-order, topmost first

    def foreground(self):
        if self.os != "Windows":
            return None
        import win32gui
        h = win32gui.GetForegroundWindow()
        return self._info(h) if h else {"hwnd": 0}

    def find_window(self, spec, gate, exclude=(), prefer_new=None, only_new=False):
        spec = str(spec).lower()
        mine = own_pids()
        cands = [w for w in self.windows() if w["pid"] not in mine and w["cls"] not in TERMINAL_CLASSES
                 and not TERMINAL_PROCS.match(w["process"] or "") and gate.allowed_window(w)
                 and (spec in (w["process"] or "").lower() or spec in w["title"].lower()) and w["hwnd"] not in exclude]
        if prefer_new is not None:
            new = [w for w in cands if w["hwnd"] not in prefer_new]
            if new or only_new:
                return new[0] if new else None
        fg = self.foreground() or {}
        for w in cands:
            if w["hwnd"] == fg.get("hwnd"):
                return w
        return cands[0] if cands else None

    def wait_window(self, spec, gate, timeout, prefer_new=None, only_new=False):
        end = time.time() + timeout
        while True:
            w = self.find_window(spec, gate, prefer_new=prefer_new, only_new=only_new)
            if w or time.time() > end:
                return w
            time.sleep(0.4)

    def start_apps(self):
        if self._apps is None:
            self._apps = []
            if self.os == "Windows":
                try:
                    out = subprocess.run(["powershell", "-NoProfile", "-Command", "Get-StartApps | ConvertTo-Json -Compress"],
                                         capture_output=True, text=True, timeout=30).stdout
                    data = json.loads(out or "[]")
                    self._apps = data if isinstance(data, list) else [data]
                except Exception:  # noqa: BLE001
                    self._apps = []
        return self._apps

    def resolve_launch(self, app):
        """-> (argv, how). Order: a path, a Start-menu app name (AUMID), then PATH."""
        if os.path.exists(os.path.expandvars(app)):
            return [os.path.expandvars(app)], "path"
        if self.os == "Windows":
            apps = self.start_apps()
            name = app.lower()
            hit = [a for a in apps if (a.get("Name") or "").lower() == name] or \
                  [a for a in apps if (a.get("Name") or "").lower().startswith(name)]
            if hit:
                return ["explorer.exe", "shell:AppsFolder\\" + hit[0]["AppID"]], "start-menu"
        exe = shutil.which(app) or shutil.which(app + ".exe")
        if exe:
            return [exe], "PATH"
        if self.os == "Darwin":
            return ["open", "-a", app], "open -a"
        raise StepFailed(f"cannot find an app called '{app}' (not a path, not in the Start menu, not on PATH)")

    def launch(self, step, gate):
        app = step["app"]
        before = {w["hwnd"] for w in self.windows()}
        argv, how = self.resolve_launch(app)
        subprocess.Popen(argv)
        spec, to = step.get("window") or app, float(step.get("timeout", self.step_timeout))
        # a new window first (an app that is already running may open one); then, unless the step
        # requires a new window, the app's existing window (single-instance apps just come forward)
        w = self.wait_window(spec, gate, to if step.get("require_new") else min(to, 6), prefer_new=before, only_new=True)
        if not w and not step.get("require_new"):
            w = self.wait_window(spec, gate, max(1.0, to - 6))
        if not w:
            raise StepFailed(f"launched '{app}' ({how}) but no {'new ' if step.get('require_new') else ''}allow-listed window appeared")
        self.target = w["hwnd"]
        self.launched_new = w["hwnd"] not in before
        time.sleep(float(step.get("settle", 1.0)))
        self.set_focus()
        return {"how": how, "window_new": self.launched_new}

    def open(self, app):  # backwards compatible
        self.launch({"app": app}, self._gate_any())

    def _gate_any(self):
        g = Gate({"desktop": {"enabled": True, "allow_apps": self.allow or []}})
        return g

    def focus(self, window, gate=None):
        w = self.wait_window(window, gate or self._gate_any(), self.step_timeout)
        if not w:
            raise StepFailed(f"no allow-listed window matches '{window}'")
        self.target = w["hwnd"]
        self.set_focus()
        return w

    def wrapper(self, hwnd=None):
        from pywinauto import Desktop
        return Desktop(backend="uia").window(handle=hwnd or self.target).wrapper_object()

    def set_focus(self):
        import win32con
        import win32gui
        if win32gui.IsIconic(self.target):
            win32gui.ShowWindow(self.target, win32con.SW_RESTORE)
        try:
            self.wrapper().set_focus()
        except Exception:  # noqa: BLE001
            try:
                win32gui.SetForegroundWindow(self.target)
            except Exception:  # noqa: BLE001
                pass
        time.sleep(0.3)
        if not self.on_target():  # Windows may refuse a background process: minimise + restore activates it
            win32gui.ShowWindow(self.target, win32con.SW_MINIMIZE)
            win32gui.ShowWindow(self.target, win32con.SW_RESTORE)
            time.sleep(0.5)

    def root_owner(self, hwnd):
        import ctypes
        return ctypes.windll.user32.GetAncestor(hwnd, 3)  # GA_ROOTOWNER

    def on_target(self, fg=None):
        """True when the focused window is the target or a dialog the target owns."""
        import win32gui
        h = (fg or {}).get("hwnd") if fg else win32gui.GetForegroundWindow()
        return bool(h) and bool(self.target) and (h == self.target or self.root_owner(h) == self.target)

    def ensure_target(self):
        """Input goes to the window under test only: refocus once, else refuse."""
        if not self.target:
            raise Refused("no target window yet: start with a launch or focus step")
        self.wait_user_idle()
        if not self.on_target():
            self.set_focus()
        if not self.on_target():
            raise Refused("the window under test does not have the focus: input refused")

    def target_rect(self):
        """The visible window rect (DWM frame bounds): GetWindowRect adds an invisible resize border
        that would let a sliver of the window behind into the video."""
        import ctypes
        import ctypes.wintypes as wt
        r = wt.RECT()
        if ctypes.windll.dwmapi.DwmGetWindowAttribute(wt.HWND(self.target), 9, ctypes.byref(r), ctypes.sizeof(r)) == 0:
            return (r.left, r.top, r.right, r.bottom)
        import win32gui
        return tuple(win32gui.GetWindowRect(self.target))

    def minimize(self):
        import win32con
        import win32gui
        win32gui.ShowWindow(self.target, win32con.SW_MINIMIZE)

    def close(self):
        """WM_CLOSE through UIA WindowPattern, never a process kill. If the app then asks to save,
        Cancel is pressed (closing never discards anyone's work) and the step fails."""
        import win32con
        import win32gui
        try:
            self.wrapper().iface_window.Close()
        except Exception:  # noqa: BLE001
            win32gui.PostMessage(self.target, win32con.WM_CLOSE, 0, 0)
        time.sleep(1.2)
        if win32gui.IsWindow(self.target) and win32gui.IsWindowVisible(self.target):
            ask = self.find_control({"role": "Text", "name_re": r"(?i)save changes|do you want to save|unsaved"}, 1.5, required=False)
            if ask is not None:
                cancel = self.find_control({"role": "Button", "name": "Cancel"}, 1.5, required=False)
                if cancel is not None:
                    cancel.invoke()
                raise StepFailed("the app asked to save unsaved work: pressed Cancel, nothing was discarded")

    # ---- controls
    def _scopes(self):
        """The target window plus other top-level windows of the same process (its dialogs)."""
        import win32gui
        import win32process
        if not self.target or not win32gui.IsWindow(self.target):
            return []  # the target closed itself (for example its last tab was closed)
        _, pid = win32process.GetWindowThreadProcessId(self.target)
        out = [self.wrapper()]
        for w in self.windows():  # dialogs owned by the target, never the app's other windows
            if w["pid"] == pid and w["hwnd"] != self.target and self.root_owner(w["hwnd"]) == self.target:
                try:
                    out.append(self.wrapper(w["hwnd"]))
                except Exception:  # noqa: BLE001
                    pass
        return out

    @staticmethod
    def _match(el, spec):
        info = el.element_info
        if isinstance(spec, str):
            spec = {"name": spec}
        if spec.get("role") and (info.control_type or "").lower() != spec["role"].lower():
            return False
        if spec.get("auto_id") and info.automation_id != spec["auto_id"]:
            return False
        if spec.get("name") is not None and (info.name or "") != spec["name"]:
            return False
        if spec.get("name_re") and not re.search(spec["name_re"], info.name or "", re.I):
            return False
        if spec.get("name_contains") and spec["name_contains"].lower() not in (info.name or "").lower():
            return False
        return True

    def find_control(self, spec, timeout=None, required=True):
        """spec: a name, or {"name" | "name_re" | "name_contains", "role", "auto_id", "in": <parent spec>}."""
        end = time.time() + (timeout if timeout is not None else self.step_timeout)
        while True:
            scopes = self._scopes()
            if isinstance(spec, dict) and spec.get("in") is not None:
                parent = self.find_control(spec["in"], 0, required=False)
                scopes = [parent] if parent is not None else []
            largest = isinstance(spec, dict) and spec.get("largest")  # several match (two "Sidebar" groups): the biggest
            hits = []
            for scope in scopes:
                try:
                    kw = {"control_type": spec["role"]} if isinstance(spec, dict) and spec.get("role") else {}
                    for el in scope.descendants(**kw):
                        if self._match(el, spec) and el.is_visible():
                            if not largest:
                                return el
                            hits.append(el)
                except Exception:  # noqa: BLE001 (the tree changes while we walk it)
                    pass
            if hits:
                return max(hits, key=lambda e: (lambda r: (r[2] - r[0]) * (r[3] - r[1]))(self.rect_of(e)))
            if time.time() > end:
                if not required:
                    return None
                raise StepFailed(f"control not found: {spec}")
            time.sleep(0.4)

    @staticmethod
    def rect_of(el):
        r = el.rectangle()
        return (r.left, r.top, r.right, r.bottom)

    @staticmethod
    def read_el(el):
        for get in (lambda: el.iface_value.CurrentValue, lambda: el.iface_text.DocumentRange.GetText(-1),
                    lambda: el.legacy_properties().get("Value"), lambda: el.window_text()):
            try:
                v = get()
                if v:
                    return str(v).replace("\r\n", "\n").rstrip("\r")
            except Exception:  # noqa: BLE001
                pass
        return ""

    def read(self, spec):
        return self.read_el(self.find_control(spec))

    def window_texts(self):
        out = []
        for scope in self._scopes():
            try:
                for el in scope.descendants():
                    out.append(el.element_info.name or "")
                    if el.element_info.control_type in ("Edit", "Document"):
                        out.append(self.read_el(el))
            except Exception:  # noqa: BLE001
                pass
        return out

    def is_password_focused(self):
        if self.os != "Windows":
            return False
        try:
            from pywinauto.uia_defines import IUIA
            return bool(IUIA().iuia.GetFocusedElement().CurrentIsPassword)
        except Exception:  # noqa: BLE001
            return False

    def password_rects(self):
        out = []
        try:
            for el in self.wrapper().descendants(control_type="Edit"):
                if el.element_info.element.CurrentIsPassword:
                    out.append(self.rect_of(el))
        except Exception:  # noqa: BLE001
            pass
        return out

    # ---- input
    def idle_seconds(self):
        """Seconds since the last keyboard/mouse input on this PC (ours or the user's)."""
        import ctypes

        class LII(ctypes.Structure):
            _fields_ = [("cbSize", ctypes.c_uint), ("dwTime", ctypes.c_uint)]
        li = LII()
        li.cbSize = ctypes.sizeof(li)
        if not ctypes.windll.user32.GetLastInputInfo(ctypes.byref(li)):
            return 99.0
        return ((ctypes.windll.kernel32.GetTickCount() - li.dwTime) & 0xFFFFFFFF) / 1000.0

    def wait_user_idle(self, quiet=2.0, timeout=15.0):
        """The owner is using the PC: wait until there was no input for `quiet` seconds that we did not
        send ourselves, else refuse. Typing over a person's hands sends keys into the wrong window."""
        if self.os != "Windows":
            return
        end = time.time() + timeout
        while True:
            idle = self.idle_seconds()
            since_ours = time.time() - self._last_sent
            if idle >= quiet or (since_ours < quiet and idle >= since_ours - 0.25):
                return
            if time.time() > end:
                raise Refused("someone is using this PC (keyboard/mouse): paused, then stopped so no key lands in their window")
            time.sleep(0.25)

    def _guard(self, done=0, total=0):
        if self.os == "Windows" and not self.on_target():
            raise Refused(f"the focus left the window under test mid-way ({done}/{total} characters typed): stopped")

    def focused_pid(self):
        """Process id of the UIA element that has the keyboard focus (None if unknown)."""
        try:
            from pywinauto.uia_defines import IUIA
            return int(IUIA().iuia.GetFocusedElement().CurrentProcessId)
        except Exception:  # noqa: BLE001
            return None

    def target_pid(self):
        import win32process
        return win32process.GetWindowThreadProcessId(self.target)[1]

    def check_keyboard_focus(self):
        """Before the first character: the foreground window is the target itself, and the element that will
        receive the keys belongs to the target's process. A terminal tab, another app or an overlay never does."""
        if self.os != "Windows":
            return
        if not self.on_target():
            raise Refused("the window under test is not in front: typing refused")
        fp = self.focused_pid()
        if fp is None or fp != self.target_pid():
            raise Refused("the keyboard focus is not inside the window under test: typing refused")

    def type(self, text, control=None):
        if control is not None:
            el = self.find_control(control)
            el.set_focus()
            time.sleep(0.2)
        if self.os != "Windows":
            self.pg.write(text, interval=0.03)
            return
        self.check_keyboard_focus()
        from pywinauto.keyboard import send_keys
        for n, ch in enumerate(text):  # the focus is checked before EVERY character
            self._guard(n, len(text))
            send_keys(send_keys_text(ch), with_spaces=True, with_tabs=True, with_newlines=False, pause=0)
            self._last_sent = time.time()
            time.sleep(0.03)

    def key(self, keys):
        self._guard()
        self.check_keyboard_focus()
        self.pg.hotkey(*keys)
        self._last_sent = time.time()

    def click(self, x=None, y=None, control=None, at=None):
        self._guard()
        self._last_sent = time.time()
        if control is not None:
            el = self.find_control(control)
            try:
                el.invoke()
            except Exception:  # noqa: BLE001
                el.click_input()
                self.park_mouse()
            return
        if at is not None:
            x, y = frac_rect(self.target_rect(), [at[0], at[1], at[0], at[1]])[:2]
        self.pg.click(x, y)

    def park_mouse(self):
        """Rest the pointer on the banner strip at the bottom of the window: a pointer left over a file list
        pops tooltips (file details) that draw above the privacy masks."""
        try:
            l, t, r, b = self.target_rect()
            self.pg.moveTo((l + r) // 2, b - 30, duration=0.1)
        except Exception:  # noqa: BLE001
            pass

    def scroll(self, amount, control=None):
        r = self.rect_of(self.find_control(control)) if control else self.target_rect()
        self.pg.scroll(int(amount), x=(r[0] + r[2]) // 2, y=(r[1] + r[3]) // 2)

    # ---- clipboard
    def clipboard_get(self):
        if self.os != "Windows":
            return subprocess.run(["pbpaste"], capture_output=True, text=True, timeout=5).stdout
        import win32clipboard
        win32clipboard.OpenClipboard()
        try:
            return win32clipboard.GetClipboardData(win32clipboard.CF_UNICODETEXT)
        except Exception:  # noqa: BLE001
            return None
        finally:
            win32clipboard.CloseClipboard()

    def clipboard_set(self, text):
        if self.os != "Windows":
            subprocess.run(["pbcopy"], input=text, text=True, timeout=5)
            return
        import win32clipboard
        win32clipboard.OpenClipboard()
        try:
            win32clipboard.EmptyClipboard()
            if text is not None:
                win32clipboard.SetClipboardData(win32clipboard.CF_UNICODETEXT, text)
        finally:
            win32clipboard.CloseClipboard()

    # ---- screen
    def monitors(self):
        import mss
        with mss.MSS() as s:
            return [dict(m) for m in s.monitors]  # [0] = every monitor together, [1..] = each monitor

    def virtual_bounds(self):
        m = self.monitors()[0]
        return (m["left"], m["top"], m["left"] + m["width"], m["top"] + m["height"])

    def region(self, spec):
        spec = spec or ("window" if self.target else "screen")
        if spec == "window" and self.target:
            import win32gui
            if not win32gui.IsWindow(self.target) or not win32gui.IsWindowVisible(self.target) or win32gui.IsIconic(self.target):
                raise RuntimeError("the target window is closed or minimised: no screenshot of what is behind it")
            if not self.on_target():
                raise RuntimeError("another window is in front of the target: no screenshot of it")
            return self.target_rect()
        if str(spec).startswith("monitor:"):
            m = self.monitors()[int(str(spec).split(":")[1])]
            return (m["left"], m["top"], m["left"] + m["width"], m["top"] + m["height"])
        return self.virtual_bounds()

    def screenshot(self, path, region=None, masks=()):
        import mss
        from PIL import Image, ImageDraw
        l, t, r, b = self.region(region)
        with mss.MSS() as s:
            raw = s.grab({"left": l, "top": t, "width": r - l, "height": b - t})
            img = Image.frombytes("RGB", raw.size, raw.rgb)
        for m in masks:  # private regions: blurred (the overlay already is; this repeats it in the file)
            c = clip_rect((m[0] - l, m[1] - t, m[2] - l, m[3] - t), (0, 0, r - l, b - t))
            if c:
                img.paste(pixelate(img.crop(c)), c[:2])
        d = ImageDraw.Draw(img)
        for m in self.password_rects():  # passwords: solid black, never a blur
            d.rectangle([m[0] - l, m[1] - t, m[2] - l, m[3] - t], fill=(20, 20, 20))
        img.save(path)

    def blurred_snapshot(self, rect, path):
        """Save a pixelated picture of a screen rect (for the privacy overlay). The sharp pixels stay in memory."""
        import mss
        from PIL import Image
        l, t, r, b = rect
        with mss.MSS() as s:
            raw = s.grab({"left": l, "top": t, "width": r - l, "height": b - t})
        pixelate(Image.frombytes("RGB", raw.size, raw.rgb)).save(path)
        return path


class Overlay:
    """Always-on-top, click-through, non-activating boxes: the banner and the privacy masks.
    Runs as `desktop.py _overlay` in its own process so the run never blocks on Tk."""

    def __init__(self, boxes, enabled=True, ready_timeout=8.0, restore=None):
        self.p = None
        self.ready = False
        if enabled and boxes:
            fg = 0
            if platform.system() == "Windows":
                import ctypes
                # the focus is handed back to the window under test, never to whatever was in front (a terminal)
                fg = restore or ctypes.windll.user32.GetForegroundWindow() or 0
            try:
                self.p = subprocess.Popen([sys.executable, os.path.abspath(__file__), "_overlay", json.dumps(boxes), str(fg)],
                                          stdout=subprocess.PIPE, text=True)
            except OSError:
                self.p = None
                return
            # wait until the boxes are really on screen: a fixed sleep let a slow start show private content
            got = []
            t = threading.Thread(target=lambda: got.append(self.p.stdout.readline()), daemon=True)
            t.start()
            t.join(ready_timeout)
            self.ready = bool(got and got[0].strip() == "ready")

    def close(self):
        if self.p:
            self.p.terminate()
            try:
                self.p.wait(timeout=5)
            except Exception:  # noqa: BLE001
                pass
            self.p = None


def overlay_main(boxes_json, restore_fg=0):
    """Draw boxes: [{"rect": [l, t, r, b], "text": "...", "bg": "#..."}] in physical pixels."""
    import ctypes
    import tkinter as tk
    if platform.system() == "Windows":
        try:
            ctypes.windll.shcore.SetProcessDpiAwareness(2)
        except Exception:  # noqa: BLE001
            pass
    boxes = json.loads(boxes_json)
    root = tk.Tk()
    root.withdraw()
    for bx in boxes:
        l, t, r, b = bx["rect"]
        w = tk.Toplevel(root)
        w.overrideredirect(True)
        w.attributes("-topmost", True)
        w.geometry(f"{max(1, r - l)}x{max(1, b - t)}+{l}+{t}")
        w.configure(bg=bx.get("bg", "#141414"))
        if bx.get("image"):  # a blurred picture of what is under the box: the UI stays recognisable, text does not
            img = tk.PhotoImage(file=bx["image"], master=w)
            w._img = img
            tk.Label(w, image=img, text=bx.get("text", ""), compound="center", fg=bx.get("fg", "white"), bd=0,
                     font=("Segoe UI", int(bx.get("size", 10)), "bold")).place(x=0, y=0, relwidth=1, relheight=1)
        else:
            tk.Label(w, text=bx.get("text", ""), bg=bx.get("bg", "#141414"), fg=bx.get("fg", "#9a9a9a"),
                     font=("Segoe UI", int(bx.get("size", 10)), "bold" if bx.get("bold") else "normal")).place(relx=0.5, rely=0.5, anchor="center")
        if platform.system() == "Windows":
            w.update_idletasks()
            hwnd = ctypes.windll.user32.GetParent(w.winfo_id()) or w.winfo_id()
            gwl, ex = -20, 0x00080000 | 0x00000020 | 0x08000000 | 0x00000080 | 0x00000008  # layered, transparent, noactivate, toolwindow, topmost
            ctypes.windll.user32.SetWindowLongW(hwnd, gwl, ctypes.windll.user32.GetWindowLongW(hwnd, gwl) | ex)
            ctypes.windll.user32.SetLayeredWindowAttributes(hwnd, 0, 255, 2)
    if platform.system() == "Windows" and restore_fg:
        root.update()
        # creating a window can take the focus; this process may give it back (the window under test,
        # or its open dialog) because it is the foreground process at this moment
        ctypes.windll.user32.SetForegroundWindow(int(restore_fg))
    root.update()
    print("ready", flush=True)
    root.mainloop()


class Notice(Overlay):
    """The visible banner while ShipShape controls the PC (kept for older callers)."""

    def __init__(self, enabled=True, rect=None, restore=None):
        rect = rect or [20, 20, 860, 56]
        super().__init__([{"rect": rect, "text": BANNER_TEXT, "bg": "#b3261e", "fg": "white", "bold": True, "size": 11}], enabled,
                         restore=restore)


def record_cmd(out_mp4, seconds=None, system=None, fps=15, region=None):
    """ffmpeg screen-capture command for this OS (gdigrab / avfoundation / x11grab).
    region = (left, top, width, height) records only that part of the screen (the target window)."""
    system = system or platform.system()
    if system == "Windows":
        reg = ["-offset_x", str(region[0]), "-offset_y", str(region[1]), "-video_size", f"{region[2]}x{region[3]}"] if region else []
        src = ["-f", "gdigrab", "-framerate", str(fps), "-draw_mouse", "1", *reg, "-i", "desktop"]
    elif system == "Darwin":
        src = ["-f", "avfoundation", "-framerate", str(fps), "-capture_cursor", "1", "-i", os.environ.get("SMEKIT_AVF_SCREEN", "1:none")]
    else:
        src = ["-f", "x11grab", "-framerate", str(fps), "-i", os.environ.get("DISPLAY", ":0")]
    dur = ["-t", str(seconds)] if seconds else []
    return ["ffmpeg", "-y", "-v", "error", *src, *dur, "-vf", "scale='min(1920,iw)':-2", "-c:v", "libx264", "-preset", "veryfast",
            "-pix_fmt", "yuv420p", out_mp4]


# ------------------------------------------------------------------ the run
def under_test(be, later):
    """Screen rects of the controls the next steps type into, read or click (up to the next mask change):
    a mask is never allowed to hide them."""
    out = []
    for s in later:
        if s.get("do") in ("mask", "unmask"):
            break
        if s.get("do") in ("type", "read", "assert_text", "click") and s.get("control") is not None:
            try:
                el = be.find_control(s["control"], 0.5, required=False)
                if el is not None:
                    out.append(tuple(be.rect_of(el)))
            except Exception:  # noqa: BLE001 - a control that is not there yet (a dialog) has nothing to keep
                pass
    return out


def speech_lengths(steps):
    """Seconds each narration line takes (the free edge voice, cached), so the run can pace itself: a line is
    spoken to the end before the next one starts. Offline: a reading-speed estimate."""
    out = {}
    try:
        sys.path.insert(0, HERE)
        import narrator
    except Exception:  # noqa: BLE001
        narrator = None
    for s in steps:
        line = s.get("say")
        if not line or line in out:
            continue
        try:
            out[line] = float(narrator.say(line)[1])
        except Exception:  # noqa: BLE001
            out[line] = max(2.0, 0.4 * len(line.split()))
    return out


def _settings(cfg, step_timeout=None, run_timeout=None):
    d = (cfg or {}).get("desktop") or {}
    return float(step_timeout or d.get("step_timeout") or 20), float(run_timeout or d.get("run_timeout") or 180)


def run(steps, cfg, out, dry_run=False, backend=None, record=True, notice=True, step_timeout=None, run_timeout=None, narrate=False,
        cleanup_steps=None):
    """Run steps -> result rows {"id", "title", "result", "evidence", "note"}. Checks (assert_*, wait_*,
    screenshot) give PASS/FAIL rows; an action gives a row only when it fails or is refused."""
    os.makedirs(out, exist_ok=True)
    log_path = os.path.join(out, "desktop-actions.jsonl")
    gate = Gate(cfg)
    step_to, run_to = _settings(cfg, step_timeout, run_timeout)
    real = not dry_run and (backend is None or isinstance(backend, Backend))
    be = backend or (DryRun() if dry_run else Backend(step_to))
    if hasattr(be, "allow") and not callable(getattr(be, "allow")):
        be.allow = gate.allow
    mine = own_pids()
    results, masks, saved, lines = [], [], {}, []
    state = {"rec": None, "rec_t0": None, "banner": None, "mask_ov": None, "clip": None, "clip_saved": False,
             "speech_end": 0.0, "blur_dir": None}
    max_cover = ((cfg or {}).get("desktop") or {}).get("mask_max_cover", MASK_MAX_COVER)
    spoken = speech_lengths(steps) if narrate and real else {}
    t_run = time.time()
    done = threading.Event()

    def log(entry):
        entry["t"] = time.strftime("%Y-%m-%dT%H:%M:%S")
        with open(log_path, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(entry) + "\n")

    def cid(i, s):
        return s.get("case", f"desktop-{i + 1}")

    def start_recording(region_spec=None):
        if state["rec"] or not record or dry_run or not shutil.which("ffmpeg") or not real:
            return
        reg = None
        if region_spec != "screen" and getattr(be, "target", None):
            reg = even_region(be.target_rect(), be.virtual_bounds())
        if reg:
            show_banner(reg)
        be.park_mouse()
        state["rec"] = subprocess.Popen(record_cmd(os.path.join(out, "desktop.mp4"), int(run_to) + 5, region=reg), stdin=subprocess.PIPE)
        state["rec_t0"] = time.time()
        time.sleep(0.8)

    def show_banner(reg=None):
        if not (notice and real):
            return
        if state["banner"]:
            state["banner"].close()
        if reg:  # inside the bottom of the recorded window, so the video shows it too
            l, t, w, h = reg
            rect = [l + max(0, (w - 900) // 2), t + h - 52, l + max(0, (w - 900) // 2) + min(900, w), t + h - 12]
        else:
            rect = None
        state["banner"] = Notice(True, rect, restore=getattr(be, "target", None))
        if getattr(be, "target", None):
            be.set_focus()

    def refresh_masks():
        """The new overlay is up before the old one goes, so nothing private shows in between."""
        old = state["mask_ov"]
        boxes = []
        if masks and real:
            import tempfile
            state["blur_dir"] = state["blur_dir"] or tempfile.mkdtemp(prefix="shipshape-mask-")
            for k, m in enumerate(masks):
                box = {"rect": list(m), "text": "private"}
                try:  # a blurred picture of the region; a dark box only if the picture cannot be made
                    box["image"] = be.blurred_snapshot(m, os.path.join(state["blur_dir"], f"m{time.time_ns()}-{k}.png"))
                except Exception:  # noqa: BLE001
                    box["text"] = "hidden for privacy"
                boxes.append(box)
        state["mask_ov"] = Overlay(boxes, restore=getattr(be, "target", None)) if boxes else None
        if state["mask_ov"] is not None and not state["mask_ov"].ready:
            state["mask_ov"].close()
            state["mask_ov"] = old  # keep the old masks up; the run stops rather than show what is behind
            raise StepFailed("the privacy mask did not appear in time: stopped so nothing private is shown")
        if old:
            old.close()
        if masks and real and s.get("refocus", True):
            be.set_focus()

    def watchdog():
        if not done.wait(run_to + 20):
            log({"status": "ABORTED", "why": f"run timeout {run_to:.0f}s (hard stop)"})
            cleanup()
            os._exit(124)

    def stop_recording():
        if state["rec"]:
            try:
                state["rec"].stdin.write(b"q")
                state["rec"].stdin.flush()
                state["rec"].wait(timeout=20)
            except Exception:  # noqa: BLE001
                state["rec"].send_signal(signal.SIGTERM)
            state["rec"] = None

    def cleanup():
        stop_recording()
        for k in ("mask_ov", "banner"):
            if state[k]:
                state[k].close()
                state[k] = None
        if state["blur_dir"]:
            shutil.rmtree(state["blur_dir"], ignore_errors=True)
            state["blur_dir"] = None
        if state["clip_saved"]:
            try:
                be.clipboard_set(state["clip"])  # give the user back their clipboard
            except Exception:  # noqa: BLE001
                pass
            state["clip_saved"] = False

    if real:
        threading.Thread(target=watchdog, daemon=True).start()
        if notice:
            show_banner()
    try:
        explicit_rec = any(s.get("do") == "record_start" for s in steps)
        for i, s in enumerate(steps):
            if time.time() - t_run > run_to:
                log({"step": i + 1, "do": s.get("do"), "status": "ABORTED", "why": f"run timeout {run_to:.0f}s"})
                results.append({"id": cid(i, s), "title": s.get("do"), "result": "BLOCKED", "evidence": "", "note": f"run timeout {run_to:.0f}s"})
                break
            try:
                gate.check(s)
            except Refused as exc:
                log({"step": i + 1, "do": s.get("do"), "status": "REFUSED", "why": str(exc)})
                results.append({"id": cid(i, s), "title": s.get("do"), "result": "BLOCKED", "evidence": "", "note": str(exc)})
                break
            do = s["do"]
            t0 = time.time()
            to = min(float(s.get("timeout", step_to)), step_to * 3)
            entry = {"step": i + 1, "do": do, "target": s.get("app") or s.get("window"), "case": s.get("case")}
            if s.get("say") and state["rec_t0"]:
                # one narrator at a time: a step with a line waits until the previous line has been spoken
                time.sleep(max(0.0, state["speech_end"] - time.time()))
                lines.append({"t": round(time.time() - state["rec_t0"], 2), "text": s["say"]})
                state["speech_end"] = time.time() + spoken.get(s["say"], 0.0) + 0.3
                if do in ("close", "minimize"):  # these stop the recording: let the line finish on video first
                    time.sleep(max(0.0, state["speech_end"] - time.time()))
            row = None
            try:
                if do in INPUT_VERBS and not dry_run:
                    if hasattr(type(be), "ensure_target"):
                        be.ensure_target()
                    fg = be.foreground() if hasattr(be, "foreground") else None
                    gate.check_window(fg, mine)
                    Gate.check_send(s, fg)
                    if do == "type" and be.is_password_focused():
                        raise Refused("focused field is a password field")
                if dry_run:
                    pass
                elif do in ("launch", "open"):
                    if hasattr(type(be), "launch"):
                        entry["how"] = (be.launch(s, gate) or {}).get("how")
                    else:  # simple test doubles
                        be.open(s["app"])
                elif do in ("focus", "switch"):
                    be.focus(s["window"], gate) if hasattr(type(be), "focus") else be.focus(s["window"])
                elif do == "minimize":
                    stop_recording()  # the recorded region would show whatever is behind the window
                    be.minimize()
                elif do == "close":
                    stop_recording()
                    if s.get("only_if_launched") and not getattr(be, "launched_new", False):
                        entry["skipped"] = "the app was already open before the run: left as it was"
                        if s.get("otherwise") == "minimize":
                            be.minimize()
                            entry["skipped"] += " (minimised)"
                    else:
                        be.close()
                elif do == "wait_window":
                    w = be.wait_window(s["window"], gate, to)
                    row = ("PASS" if w else "FAIL", "" if w else f"no window '{s['window']}' within {to:.0f}s")
                    if w and s.get("target", True) and isinstance(w, dict):
                        be.target = w["hwnd"]
                elif do == "assert_window":
                    w = be.find_window(s["window"], gate)
                    want = s.get("present", True)
                    ok = bool(w) == bool(want)
                    row = ("PASS" if ok else "FAIL", "" if ok else f"window '{s['window']}' present={bool(w)}, expected {want}")
                elif do == "wait_text":
                    end, found = time.time() + to, False
                    while not found:
                        found = any(s["text"] in (x or "") for x in (be.window_texts() or []))
                        if found or time.time() > end:
                            break
                        time.sleep(0.4)
                    row = ("PASS" if found else "FAIL", "" if found else f"text not seen within {to:.0f}s")
                elif do == "type":
                    if s.get("control") is not None:
                        be.type(s["text"], s["control"])
                    else:
                        if s.get("window"):
                            be.focus(s["window"], gate) if hasattr(type(be), "focus") else be.focus(s["window"])
                        be.type(s["text"])
                    entry["chars"] = len(s["text"])
                elif do == "key":
                    be.key(s["keys"])
                elif do == "click":
                    if s.get("control") is not None:
                        be.click(control=s["control"])
                    elif s.get("at") is not None:
                        be.click(at=s["at"])
                    else:
                        be.click(s["x"], s["y"])
                elif do == "scroll":
                    be.scroll(s.get("amount", -3), s.get("control"))
                elif do == "read":
                    v = be.read(s["control"]) or ""
                    saved[s.get("save_as", "last")] = v
                    entry["chars"] = len(v)
                elif do == "clipboard_set":
                    if not state["clip_saved"]:
                        state["clip"], state["clip_saved"] = be.clipboard_get(), True
                    be.clipboard_set(s["text"])
                elif do == "clipboard_get":
                    v = be.clipboard_get() or ""
                    saved[s.get("save_as", "clipboard")] = v
                    entry["chars"] = len(v)
                elif do == "assert_text":
                    v = be.read(s["control"]) if s.get("control") is not None else saved.get(s.get("var", "last"), "")
                    v = (v or "").strip() if s.get("strip", True) else (v or "")
                    if "equals_var" in s:
                        want, ok = saved.get(s["equals_var"], None), v == (saved.get(s["equals_var"]) or "").strip()
                    elif "equals" in s:
                        want, ok = s["equals"], v == s["equals"]
                    else:
                        want, ok = s.get("contains", ""), s.get("contains", "") in v
                    if s.get("negate"):
                        ok = not ok
                    row = ("PASS" if ok else "FAIL", "" if ok else f"read {len(v)} chars, not the expected text")
                elif do == "assert_control":
                    want = s.get("present", True)
                    el = be.find_control(s["control"], to if want else min(to, 2.0), required=False)
                    ok = (el is not None) == bool(want)
                    row = ("PASS" if ok else "FAIL", "" if ok else f"control present={el is not None}, expected {want}")
                elif do == "mask":
                    new = []
                    for m in s.get("regions") or [s]:
                        win = be.rect_of(be.find_control(m["within"], to)) if m.get("within") is not None else be.target_rect()
                        if m.get("above_control") is not None:
                            c = be.rect_of(be.find_control(m["above_control"], to))
                            new.append((win[0], win[1], win[2], c[1]))
                        elif m.get("rect"):
                            new.append(frac_rect(win, m["rect"]))
                        elif m.get("outside_control") is not None:
                            new.extend(outside(win, be.rect_of(be.find_control(m["outside_control"], to)), int(m.get("pad", 8))))
                        elif m.get("control") is not None:
                            el = be.find_control(m["control"], min(to, 3.0) if m.get("optional") else to, required=not m.get("optional"))
                            if el is not None:  # "optional": a private region that is not on screen needs no mask
                                new.append(be.rect_of(el))
                    win = be.target_rect()
                    keep = [] if s.get("allow_large") else under_test(be, steps[i + 1:])
                    combined, frac = fit_masks(([] if s.get("replace") else masks) + new, win, keep,
                                               None if s.get("allow_large") else max_cover)
                    masks[:] = combined
                    refresh_masks()
                    entry["masks"], entry["cover"] = len(masks), round(frac, 3)
                elif do == "unmask":
                    masks.clear()
                    refresh_masks()
                elif do == "record_start":
                    start_recording(s.get("region"))
                elif do == "wait":
                    time.sleep(min(float(s.get("sec", 1)), 30))
                if real and not explicit_rec and do in ("launch", "open", "focus", "switch"):
                    start_recording()
                if time.time() - t0 > to + 2:
                    raise StepFailed(f"step timeout ({time.time() - t0:.1f}s > {to:.0f}s)")
            except Refused as exc:
                entry.update(status="REFUSED", why=str(exc))
                log(entry)
                results.append({"id": cid(i, s), "title": do, "result": "BLOCKED", "evidence": "", "note": str(exc)})
                break
            except StepFailed as exc:
                row = ("FAIL", str(exc)[:200])
            # one screenshot per step (BR-11), masked; the screenshot step itself always takes one
            shot = ""
            want_shot = do == "screenshot" or (s.get("shot", True) and getattr(be, "target", None) and do not in ("wait", "mask", "unmask", "record_start", "close", "minimize"))
            if want_shot and not dry_run:
                shot = f"{i + 1:02d}-{s.get('name', do)}.png"
                try:
                    if hasattr(type(be), "screenshot"):
                        be.screenshot(os.path.join(out, shot), s.get("region"), masks)
                    else:
                        be.screenshot(os.path.join(out, shot))
                except Exception as exc:  # noqa: BLE001
                    entry["shot_error"] = f"{type(exc).__name__}: {str(exc)[:120]}"
                    shot = ""
            if do == "screenshot":
                row = row or (("PASS", "") if shot or dry_run else ("FAIL", "no screenshot: " + entry.get("shot_error", "not taken")))
            entry["status"] = "DRY-RUN" if dry_run else ("FAILED" if row and row[0] == "FAIL" else "DONE")
            if row:
                entry["result"] = row[0]
            entry["sec"] = round(time.time() - t0, 2)
            if shot:
                entry["shot"] = shot
            log(entry)
            if row or (dry_run and do == "screenshot"):
                r = row or ("PASS", "")
                results.append({"id": cid(i, s), "title": s.get("name") or s.get("title") or do, "result": r[0],
                                "evidence": shot or ("desktop-actions.jsonl" if r[0] == "PASS" else ""), "note": r[1]})
                if r[0] == "FAIL" and (do not in CHECK_VERBS + ("screenshot",) or s.get("stop_on_fail")):
                    log({"step": i + 1, "status": "STOPPED", "why": "a failed step: later steps would act on the wrong thing"})
                    break
        else:
            state["finished"] = True
    except Exception as exc:  # noqa: BLE001 - includes pyautogui.FailSafeException (emergency stop)
        name = type(exc).__name__
        state["aborted"] = True
        log({"status": "ABORTED", "why": f"{name}: {str(exc)[:160]}"})
        results.append({"id": "desktop-abort", "title": "run", "result": "BLOCKED", "evidence": "", "note": f"aborted: {name}"})
    finally:
        done.set()
        cleanup()
    if cleanup_steps and not state.get("finished") and not state.get("aborted") and not dry_run:
        # the run stopped early: remove what it created (its own test tab, its own text), through the
        # same gates. Never after an emergency stop. Cleanup results never change the run's counts.
        log({"status": "CLEANUP", "why": f"{len(cleanup_steps)} cleanup step(s), see cleanup/desktop-actions.jsonl"})
        try:
            run(cleanup_steps, cfg, os.path.join(out, "cleanup"), backend=be, record=False, notice=notice,
                step_timeout=step_timeout, run_timeout=run_timeout)
        except Exception as exc:  # noqa: BLE001
            log({"status": "NOTE", "why": f"cleanup error: {type(exc).__name__}"})
    video = os.path.join(out, "desktop.mp4")
    if narrate and lines and os.path.exists(video):
        with open(os.path.join(out, "narration.json"), "w", encoding="utf-8") as fh:
            json.dump(lines, fh)
        try:
            subprocess.run([sys.executable, os.path.join(HERE, "narrator.py"), "mix", video, os.path.join(out, "narration.json"),
                            "--out", os.path.join(out, "desktop-narrated.mp4")], timeout=600, check=True)
        except Exception as exc:  # noqa: BLE001 - narration never changes a result
            log({"status": "NOTE", "why": f"narration skipped: {type(exc).__name__}"})
    return results


def load_steps(path):
    data = json.load(open(path, encoding="utf-8"))
    return data["steps"] if isinstance(data, dict) else data


def load_cleanup(path):
    """Optional "cleanup" steps: run only when the main steps stopped early (never after an emergency stop)."""
    data = json.load(open(path, encoding="utf-8"))
    return data.get("cleanup") if isinstance(data, dict) else None


def run_passes(steps, cfg, out, passes=1, **kw):
    """Run the steps `passes` times (pass-1, pass-2 ...); two passes that disagree are FLAKY."""
    sys.path.insert(0, HERE)
    import report
    if passes <= 1:
        res = run(steps, cfg, out, **kw)
    else:
        runs = [run(steps, cfg, os.path.join(out, f"pass-{p + 1}"), **kw) for p in range(passes)]
        for p, rr in enumerate(runs):
            for r in rr:
                if r.get("evidence"):
                    r["evidence"] = f"pass-{p + 1}/{r['evidence']}"
        res = report.combine_passes(runs[0], runs[1])
    counts, rows = report.count(res)
    with open(os.path.join(out, "results.json"), "w", encoding="utf-8") as fh:
        json.dump(rows, fh, indent=1)
    with open(os.path.join(out, "QA-REPORT.md"), "w", encoding="utf-8") as fh:
        fh.write(report.to_markdown(rows, counts, title="Desktop run"))
    return res, counts


def engines(cfg=None):
    """What can drive this device right now. The API key is checked by presence only, never printed."""
    out = {}
    for mod, name in (("pywinauto", "uia"), ("pyautogui", "pixel"), ("mss", "screenshots"), ("PIL", "masking")):
        try:
            __import__(mod)
            out[name] = "ready"
        except ImportError:
            out[name] = f"missing: pip install --user {'pillow' if mod == 'PIL' else mod}"
    if platform.system() != "Windows":
        out["uia"] = "Windows only (macOS uses osascript)"
    out["ffmpeg"] = "ready" if shutil.which("ffmpeg") else "missing (no video)"
    try:
        sys.path.insert(0, HERE)
        import keys
        out["computer-use"] = "key found (" + str(keys.where("ANTHROPIC_API_KEY")) + ")" if keys.lookup("ANTHROPIC_API_KEY") else \
            "optional: bring your own ANTHROPIC_API_KEY (python scripts/keys.py set ANTHROPIC_API_KEY)"
    except Exception:  # noqa: BLE001
        out["computer-use"] = "optional: needs your own ANTHROPIC_API_KEY"
    return out


def main(argv=None):
    if argv is None and len(sys.argv) > 2 and sys.argv[1] == "_overlay":
        overlay_main(sys.argv[2], int(sys.argv[3]) if len(sys.argv) > 3 else 0)
        return 0
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("cmd", choices=("run", "record-cmd", "windows", "inspect", "engines"))
    ap.add_argument("steps", nargs="?", help="steps.json (run) or a window (inspect)")
    ap.add_argument("--config", default="qa.config.yaml")
    ap.add_argument("--out", default="qa-evidence/desktop")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--no-record", action="store_true")
    ap.add_argument("--passes", type=int, default=1)
    ap.add_argument("--narrate", action="store_true")
    ap.add_argument("--step-timeout", type=float)
    ap.add_argument("--run-timeout", type=float)
    ap.add_argument("--roles", default="Edit,Document,Button,MenuItem,TabItem,CheckBox,ComboBox,Hyperlink")
    a = ap.parse_args(argv)
    if a.cmd == "record-cmd":
        print(" ".join(record_cmd(os.path.join(a.out, "desktop.mp4"), 5)))
        return 0
    if a.cmd == "engines":
        for k, v in engines().items():
            print(f"{k:13} {v}")
        return 0
    sys.path.insert(0, HERE)
    import notify
    import report
    cfg = notify.load_config(a.config) if os.path.exists(a.config) else {}
    gate = Gate(cfg)
    if a.cmd in ("windows", "inspect"):
        if not gate.enabled:
            print("desktop control is disabled for this project (desktop.enabled: false)")
            return 2
        be = Backend()
        if a.cmd == "windows":
            ws = be.windows()
            ok = [w for w in ws if gate.allowed_window(w) and w["pid"] not in own_pids()]
            for w in ok:
                print(f"{w['process']:20} {w['title'][:80]}")
            print(f"({len(ok)} allow-listed, {len(ws) - len(ok)} other windows not shown)")
            return 0
        w = be.find_window(a.steps or "", gate)
        if not w:
            print(f"no allow-listed window matches '{a.steps}'")
            return 2
        be.target = w["hwnd"]
        roles = set(a.roles.split(","))
        for el in be.wrapper().descendants():
            i = el.element_info
            if i.control_type in roles:
                print(f"{i.control_type:10} name={(i.name or '')[:50]!r} auto_id={i.automation_id!r}")
        return 0
    steps = load_steps(a.steps)
    res, counts = run_passes(steps, cfg, a.out, a.passes, dry_run=a.dry_run, record=not a.no_record, narrate=a.narrate,
                             cleanup_steps=load_cleanup(a.steps),
                             step_timeout=a.step_timeout, run_timeout=a.run_timeout)
    print(report.summary(counts), "| log:", os.path.join(a.out, "desktop-actions.jsonl"))
    return 0 if counts["BLOCKED"] == 0 and counts["FAIL"] == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
