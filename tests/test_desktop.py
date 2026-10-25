"""Desktop layer: safety gates and logging in dry-run / mock mode. The real-desktop
smoke test only runs with SMEKIT_DESKTOP_SMOKE=1 (CI never controls a desktop)."""
import json
import os
import platform
import shutil
import sys
import time

import pytest

import desktop

CFG = {"desktop": {"enabled": True, "allow_apps": ["notepad", "TextEdit"]}}


class Mock:
    def __init__(self):
        self.calls = []

    def __getattr__(self, name):
        if name == "is_password_focused":
            return lambda: False
        return lambda *a, **k: self.calls.append((name, a))


def test_disabled_project_refuses_everything(tmp_path):
    res = desktop.run([{"do": "open", "app": "notepad"}], {}, str(tmp_path), backend=Mock(), record=False, notice=False)
    assert res[0]["result"] == "BLOCKED" and "disabled" in res[0]["note"]


@pytest.mark.parametrize("step,why", [
    ({"do": "open", "app": "calc"}, "allow_apps"),
    ({"do": "open", "app": "MyBank Online"}, "banking"),
    ({"do": "type", "window": "notepad", "field": "Password", "text": "x"}, "password"),
    ({"do": "key", "window": "notepad", "keys": ["delete"]}, "irreversible"),
    ({"do": "click", "window": "notepad", "label": "Send", "x": 1, "y": 1}, "irreversible"),
])
def test_gates(step, why):
    with pytest.raises(desktop.Refused, match=why):
        desktop.Gate(CFG).check(step)


def test_confirmed_irreversible_step_passes_the_gate():
    desktop.Gate(CFG).check({"do": "click", "window": "notepad", "label": "Send", "x": 1, "y": 1, "confirmed": True})


def test_actions_are_logged_and_refusal_stops_the_run(tmp_path):
    mock = Mock()
    steps = [{"do": "open", "app": "notepad"}, {"do": "type", "window": "Notepad", "text": "hello"},
             {"do": "open", "app": "regedit"}, {"do": "type", "window": "Notepad", "text": "never reached"}]
    res = desktop.run(steps, CFG, str(tmp_path), backend=mock, record=False, notice=False)
    log = [json.loads(x) for x in open(tmp_path / "desktop-actions.jsonl")]
    assert [e["status"] for e in log] == ["DONE", "DONE", "REFUSED"]
    assert ("type", ("hello",)) in mock.calls and all("never reached" not in str(c) for c in mock.calls)
    assert res[-1]["result"] == "BLOCKED"
    assert "hello" not in open(tmp_path / "desktop-actions.jsonl").read()  # typed text is not logged, only its length


def test_dry_run_executes_nothing(tmp_path):
    res = desktop.run([{"do": "open", "app": "notepad"}, {"do": "screenshot", "name": "s"}], CFG, str(tmp_path), dry_run=True)
    assert [json.loads(x)["status"] for x in open(tmp_path / "desktop-actions.jsonl")] == ["DRY-RUN", "DRY-RUN"]
    assert not any(f.endswith(".png") for f in os.listdir(tmp_path))
    assert res[0]["result"] == "PASS"


def test_emergency_stop_aborts(tmp_path):
    class FailSafe(Mock):
        def type(self, *_):
            raise RuntimeError("FailSafeException: mouse in corner")

    m = FailSafe()
    res = desktop.run([{"do": "type", "window": "notepad", "text": "x"}], CFG, str(tmp_path), backend=m, record=False, notice=False)
    assert res[-1]["note"].startswith("aborted")


def test_record_command_per_os():
    assert "gdigrab" in desktop.record_cmd("o.mp4", 5, "Windows")
    assert "avfoundation" in desktop.record_cmd("o.mp4", 5, "Darwin")
    assert "-t" in desktop.record_cmd("o.mp4", 5, "Linux")




# ------------------------------------------------------------------ full-device control (issue #20)
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FULL = {"desktop": {"enabled": True, "allow_apps": ["notepad", "claude"]}}
NOTEPAD = {"hwnd": 11, "pid": 500, "process": "Notepad", "title": "Untitled - Notepad", "cls": "Notepad"}
CLAUDE_WIN = {"hwnd": 12, "pid": 600, "process": "claude", "title": "Claude", "cls": "Chrome_WidgetWin_1"}


class Fake:
    """A scripted desktop: one window, named controls with text, a clipboard."""

    def __init__(self, fg=NOTEPAD, texts=None):
        self.fg, self.target, self.launched_new = fg, None, True
        self.texts = dict(texts or {})
        self.calls, self.clip = [], "user clipboard"
        self.focused = None

    def launch(self, step, gate):
        self.calls.append(("launch", step["app"]))
        self.target = self.fg["hwnd"]
        return {"how": "start-menu"}

    def focus(self, window, gate=None):
        self.calls.append(("focus", window))
        self.target = self.fg["hwnd"]

    def ensure_target(self):
        if not self.target:
            raise desktop.Refused("no target window yet")

    def foreground(self):
        return self.fg

    def is_password_focused(self):
        return False

    def _name(self, spec):
        return spec if isinstance(spec, str) else spec.get("name") or spec.get("name_re")

    def type(self, text, control=None):
        key = self._name(control) if control else self.focused
        self.texts[key] = self.texts.get(key, "") + text
        self.calls.append(("type", len(text)))

    def key(self, keys):
        self.calls.append(("key", tuple(keys)))
        if tuple(keys) == ("backspace",):
            for k in self.texts:
                self.texts[k] = ""

    def click(self, x=None, y=None, control=None, at=None):
        self.calls.append(("click", self._name(control) if control else (x, y, at)))

    def read(self, spec):
        return self.texts.get(self._name(spec), "")

    def find_control(self, spec, timeout=None, required=True):
        n = self._name(spec)
        if n in self.texts:
            return n
        if required:
            raise desktop.StepFailed(f"control not found: {spec}")
        return None

    def find_window(self, spec, gate):
        return self.fg if spec.lower() in self.fg["title"].lower() else None

    def wait_window(self, spec, gate, timeout, **_):
        return self.find_window(spec, gate)

    def window_texts(self):
        return list(self.texts.values())

    def clipboard_get(self):
        return self.clip

    def clipboard_set(self, text):
        self.clip = text

    def close(self):
        self.calls.append(("close",))

    def minimize(self):
        self.calls.append(("minimize",))

    def screenshot(self, path, region=None, masks=()):
        self.calls.append(("shot", os.path.basename(path)))

    def scroll(self, amount, control=None):
        self.calls.append(("scroll", amount))


def log_of(path):
    return [json.loads(x) for x in open(os.path.join(path, "desktop-actions.jsonl"), encoding="utf-8")]


@pytest.mark.parametrize("info,why", [
    ({**NOTEPAD, "process": "WindowsTerminal", "cls": "CASCADIA_HOSTING_WINDOW_CLASS"}, "terminal"),
    ({**NOTEPAD, "process": "cmd", "cls": "ConsoleWindowClass"}, "terminal"),
    ({**NOTEPAD, "process": "Code"}, "terminal or editor"),
    ({**NOTEPAD, "pid": 4242}, "own terminal"),
    ({**NOTEPAD, "process": "consent", "title": "User Account Control"}, "UAC"),
    ({**NOTEPAD, "title": "Setup Wizard - Installer"}, "UAC"),
    ({**NOTEPAD, "process": "chrome", "title": "[Claude] issue - Google Chrome"}, "not in desktop.allow_apps"),
    ({**NOTEPAD, "process": "Bitwarden", "title": "Bitwarden"}, "banking"),
    ({"hwnd": 0}, "cannot tell"),
])
def test_runtime_gate_refuses_unsafe_foreground(info, why):
    with pytest.raises(desktop.Refused, match=why):
        desktop.Gate(FULL).check_window(info, own_pids={4242})


def test_runtime_gate_allows_allow_listed_process_not_titles():
    g = desktop.Gate(FULL)
    g.check_window(NOTEPAD, own_pids={1})
    g.check_window(CLAUDE_WIN, own_pids={1})
    assert not g.allowed_window({**NOTEPAD, "process": "chrome", "title": "notepad tips - Chrome"})  # a title is not an app
    assert desktop.Gate({"desktop": {"enabled": True, "allow_apps": ["title:Calculator"]}}).allowed_window(
        {"process": "ApplicationFrameHost", "title": "Calculator"})


@pytest.mark.parametrize("step,why", [
    ({"do": "key", "keys": ["win", "r"]}, "Windows key"),
    ({"do": "click", "control": {"name": "Don't save"}}, "irreversible"),
    ({"do": "click", "control": {"role": "Button", "name": "Install now"}}, "irreversible"),
    ({"do": "launch", "app": "Setup Wizard"}, "UAC"),
    ({"do": "launch"}, "needs an app"),
    ({"do": "teleport"}, "unknown step"),
    ({"do": "type", "control": {"role": "Edit", "name": "Password"}, "text": "x"}, "password"),
])
def test_static_gate_new_verbs(step, why):
    with pytest.raises(desktop.Refused, match=why):
        desktop.Gate(FULL).check(step)


@pytest.mark.parametrize("step,refused", [
    ({"do": "key", "keys": ["enter"]}, True),
    ({"do": "type", "text": "hello\n"}, True),
    ({"do": "key", "keys": ["enter"], "confirmed": True}, False),
    ({"do": "type", "text": "hello"}, False),
])
def test_enter_in_a_chat_app_is_a_send(step, refused):
    if refused:
        with pytest.raises(desktop.Refused, match="sends a message"):
            desktop.Gate.check_send(step, CLAUDE_WIN)
    else:
        desktop.Gate.check_send(step, CLAUDE_WIN)
    desktop.Gate.check_send({"do": "key", "keys": ["enter"]}, NOTEPAD)  # Enter in Notepad is just a new line


def test_templates_pass_the_static_gate():
    for name in ("desktop-steps.notepad.json", "desktop-steps.claude-desktop.json", "desktop-steps.example.json"):
        plan = os.path.join(ROOT, "templates", name)
        for s in desktop.load_steps(plan) + (desktop.load_cleanup(plan) or []):
            desktop.Gate(FULL).check(s)


def test_claude_template_never_presses_enter_or_sends():
    steps = desktop.load_steps(os.path.join(ROOT, "templates", "desktop-steps.claude-desktop.json"))
    assert not any("enter" in [k.lower() for k in s.get("keys", [])] or "\n" in s.get("text", "") or s.get("confirmed") for s in steps)


def test_type_read_assert_and_logs_lengths_only(tmp_path):
    fake = Fake(texts={"Text editor": ""})
    ctl = {"role": "Document", "name": "Text editor"}
    steps = [{"do": "launch", "app": "notepad"}, {"do": "type", "control": ctl, "text": "secret-ish words"},
             {"do": "read", "control": ctl, "save_as": "t"},
             {"do": "assert_text", "case": "A1", "control": ctl, "equals": "secret-ish words"},
             {"do": "assert_text", "case": "A2", "control": ctl, "contains": "nope"},
             {"do": "assert_text", "case": "A3", "var": "t", "equals_var": "t"}]
    res = desktop.run(steps, FULL, str(tmp_path), backend=fake, record=False, notice=False)
    assert [(r["id"], r["result"]) for r in res] == [("A1", "PASS"), ("A2", "FAIL"), ("A3", "PASS")]
    raw = open(tmp_path / "desktop-actions.jsonl", encoding="utf-8").read()
    assert "secret-ish" not in raw and '"chars": 16' in raw
    assert res[0]["evidence"].endswith(".png")  # a screenshot per step is the evidence


def test_stop_on_fail_stops_the_run(tmp_path):
    fake = Fake(texts={"box": "draft of the user"})
    steps = [{"do": "launch", "app": "claude"},
             {"do": "assert_text", "case": "C1", "control": "box", "equals": "", "stop_on_fail": True},
             {"do": "type", "control": "box", "text": "never typed"}]
    res = desktop.run(steps, FULL, str(tmp_path), backend=fake, record=False, notice=False)
    assert res[-1]["result"] == "FAIL" and not any(c[0] == "type" for c in fake.calls)
    assert log_of(tmp_path)[-1]["status"] == "STOPPED"


def test_input_refused_when_focus_moved_to_a_terminal(tmp_path):
    fake = Fake(texts={"box": ""})
    steps = [{"do": "launch", "app": "notepad"}, {"do": "type", "control": "box", "text": "x"}]
    fake.fg = {**NOTEPAD, "process": "WindowsTerminal", "cls": "CASCADIA_HOSTING_WINDOW_CLASS"}
    res = desktop.run(steps, FULL, str(tmp_path), backend=fake, record=False, notice=False)
    assert res[-1]["result"] == "BLOCKED" and "terminal" in res[-1]["note"]
    assert not any(c[0] == "type" for c in fake.calls)


def test_input_before_any_target_is_refused(tmp_path):
    res = desktop.run([{"do": "key", "keys": ["ctrl", "a"]}], FULL, str(tmp_path), backend=Fake(), record=False, notice=False)
    assert res[-1]["result"] == "BLOCKED" and "no target" in res[-1]["note"]


def test_enter_in_claude_refused_at_runtime(tmp_path):
    fake = Fake(fg=CLAUDE_WIN, texts={"box": ""})
    steps = [{"do": "launch", "app": "claude"}, {"do": "key", "keys": ["enter"]}]
    res = desktop.run(steps, FULL, str(tmp_path), backend=fake, record=False, notice=False)
    assert res[-1]["result"] == "BLOCKED" and "sends a message" in res[-1]["note"]
    assert ("key", ("enter",)) not in fake.calls


def test_clipboard_is_given_back(tmp_path):
    fake = Fake()
    steps = [{"do": "launch", "app": "notepad"}, {"do": "clipboard_set", "text": "test"},
             {"do": "clipboard_get", "save_as": "c"}, {"do": "assert_text", "case": "CB", "var": "c", "equals": "test"}]
    res = desktop.run(steps, FULL, str(tmp_path), backend=fake, record=False, notice=False)
    assert res[-1]["result"] == "PASS" and fake.clip == "user clipboard"


def test_wait_and_assert_window_and_control(tmp_path):
    fake = Fake(texts={"Save as": "", "Ready": "Ready"})
    steps = [{"do": "launch", "app": "notepad"}, {"do": "wait_window", "case": "W1", "window": "notepad", "timeout": 1},
             {"do": "assert_window", "case": "W2", "window": "notepad-calculator", "present": False},
             {"do": "wait_text", "case": "W3", "text": "Ready", "timeout": 1},
             {"do": "assert_control", "case": "W4", "control": {"name": "Save as"}},
             {"do": "assert_control", "case": "W5", "control": {"name": "Gone"}, "present": False}]
    res = desktop.run(steps, FULL, str(tmp_path), backend=fake, record=False, notice=False)
    assert [r["result"] for r in res] == ["PASS"] * 5


def test_close_only_if_launched_otherwise_minimise(tmp_path):
    fake = Fake()
    fake.launched_new = False
    steps = [{"do": "launch", "app": "claude"}, {"do": "close", "only_if_launched": True, "otherwise": "minimize"}]
    desktop.run(steps, FULL, str(tmp_path), backend=fake, record=False, notice=False)
    assert ("close",) not in fake.calls and ("minimize",) in fake.calls
    fake2 = Fake()
    desktop.run(steps, FULL, str(tmp_path / "b"), backend=fake2, record=False, notice=False)
    assert ("close",) in fake2.calls


def test_run_timeout_blocks_the_rest(tmp_path):
    steps = [{"do": "launch", "app": "notepad"}, {"do": "wait", "sec": 1.2}, {"do": "screenshot", "name": "late"}]
    res = desktop.run(steps, FULL, str(tmp_path), backend=Fake(), record=False, notice=False, run_timeout=1)
    assert res[-1]["result"] == "BLOCKED" and "run timeout" in res[-1]["note"]


def test_failed_action_stops_and_is_a_fail(tmp_path):
    steps = [{"do": "launch", "app": "notepad"}, {"do": "click", "control": {"name": "Missing"}},
             {"do": "screenshot", "name": "never"}]

    class Missing(Fake):
        def click(self, **kw):
            raise desktop.StepFailed("control not found: Missing")

    res = desktop.run(steps, FULL, str(tmp_path), backend=Missing(), record=False, notice=False)
    assert res[-1]["result"] == "FAIL" and "not found" in res[-1]["note"] and len(res) == 1


def test_two_passes_combine_and_write_the_report(tmp_path):
    fake = Fake(texts={"box": "ok"})
    steps = [{"do": "launch", "app": "notepad"}, {"do": "assert_text", "case": "P1", "control": "box", "equals": "ok"}]
    res, counts = desktop.run_passes(steps, FULL, str(tmp_path), 2, backend=fake, record=False, notice=False)
    assert counts["PASS"] == 1 and res[0]["evidence"].startswith("pass-1/")
    assert (tmp_path / "pass-2" / "desktop-actions.jsonl").exists()
    assert "1 pass / 0 fail" in open(tmp_path / "QA-REPORT.md", encoding="utf-8").read()


def test_mask_geometry():
    assert desktop.frac_rect((0, 0, 200, 100), [0, 0, 1, 0.5]) == (0, 0, 200, 50)
    holes = desktop.outside((0, 0, 100, 100), (40, 40, 60, 60))
    covered = sum((r[2] - r[0]) * (r[3] - r[1]) for r in holes)
    assert covered == 100 * 100 - 20 * 20 and len(holes) == 4
    assert desktop.even_region((1, 1, 102, 53), (0, 0, 100, 100)) == (1, 1, 98, 52)


def test_record_command_records_only_the_window_region():
    cmd = desktop.record_cmd("o.mp4", 60, "Windows", region=(10, 20, 640, 480))
    assert cmd[cmd.index("-offset_x") + 1] == "10" and "640x480" in cmd and cmd[cmd.index("-t") + 1] == "60"


def test_send_keys_escaping():
    assert desktop.send_keys_text("a+b (c) {d}") == "a{+}b {(}c{)} {{}d{}}"


def test_engines_never_print_a_key(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "-".join(["sk", "ant", "test", "not", "a", "real", "key", "0" * 24]))  # built here: no key-like literal in the repo
    out = desktop.engines()
    assert "not-a-real" not in json.dumps(out) and "found" in out["computer-use"]


def test_hook_guard_denies_unsafe_new_steps(tmp_path):
    import hook_guard
    (tmp_path / "qa.config.yaml").write_text("desktop:\n  enabled: true\n  allow_apps: [notepad]\n", encoding="utf-8")
    (tmp_path / "bad.json").write_text(json.dumps([{"do": "key", "keys": ["win", "r"]}]), encoding="utf-8")
    (tmp_path / "ok.json").write_text(json.dumps([{"do": "launch", "app": "notepad"}]), encoding="utf-8")
    assert hook_guard.classify_command("python scripts/desktop.py run bad.json", str(tmp_path))[0] == "deny"
    assert hook_guard.classify_command("python scripts/desktop.py run ok.json", str(tmp_path))[0] == "ask"


# ------------------------------------------------------------------ live (real desktop, opt-in)
LIVE_OUT = os.environ.get("SMEKIT_DESKTOP_OUT") or os.path.join(ROOT, "qa-runs", time.strftime("%Y-%m-%d") + "-device-control")
LIVE_CFG = {"desktop": {"enabled": True, "allow_apps": ["notepad", "claude"], "step_timeout": 15, "run_timeout": 150}}


@pytest.mark.skipif(os.environ.get("SMEKIT_DESKTOP_SMOKE") != "1", reason="real desktop: set SMEKIT_DESKTOP_SMOKE=1")
def test_live_notepad_two_passes():
    """Opens a NEW Notepad window, types, reads back via UIA, opens Save As and cancels it, closes the test tab with
    Don't save, then closes only the window it opened. Two recorded passes. Nothing is saved."""
    if platform.system() != "Windows" or not shutil.which("ffmpeg"):
        pytest.skip("Windows + ffmpeg only")
    out = os.path.join(LIVE_OUT, "notepad")
    shutil.rmtree(out, ignore_errors=True)
    plan = os.path.join(ROOT, "templates", "desktop-steps.notepad.json")
    res, counts = desktop.run_passes(desktop.load_steps(plan), LIVE_CFG, out, 2, cleanup_steps=desktop.load_cleanup(plan),
                                     narrate=os.environ.get("SMEKIT_DESKTOP_NARRATE") == "1")
    assert counts["PASS"] == 7 and counts["FAIL"] == counts["BLOCKED"] == counts["FLAKY"] == 0, res
    for p in ("pass-1", "pass-2"):
        assert os.path.getsize(os.path.join(out, p, "desktop.mp4")) > 10_000


@pytest.mark.skipif(os.environ.get("SMEKIT_DESKTOP_CLAUDE") != "1", reason="real Claude Desktop: set SMEKIT_DESKTOP_CLAUDE=1")
def test_live_claude_desktop_type_check_clear_never_send():
    """Types into Claude Desktop's message box, reads it back, clears it. Never presses Enter; nothing is sent."""
    if platform.system() != "Windows" or not shutil.which("ffmpeg"):
        pytest.skip("Windows + ffmpeg only")
    be = desktop.Backend()
    if not any((a.get("Name") or "") == "Claude" for a in be.start_apps()) and not os.path.isdir(os.path.expandvars(r"%LOCALAPPDATA%\AnthropicClaude")):
        pytest.skip("Claude Desktop is not installed")
    out = os.path.join(LIVE_OUT, "claude-desktop")
    shutil.rmtree(out, ignore_errors=True)
    plan = os.path.join(ROOT, "templates", "desktop-steps.claude-desktop.json")
    res, counts = desktop.run_passes(desktop.load_steps(plan), LIVE_CFG, out, 1, cleanup_steps=desktop.load_cleanup(plan),
                                     narrate=os.environ.get("SMEKIT_DESKTOP_NARRATE") == "1")
    assert counts["PASS"] == 4 and counts["FAIL"] == counts["BLOCKED"] == 0, res
    assert os.path.getsize(os.path.join(out, "desktop.mp4")) > 10_000
    assert not any(e.get("do") == "key" and "enter" in str(e) for e in log_of(out))


def test_typing_stops_the_moment_focus_leaves(monkeypatch):
    """A window that jumps in front mid-typing gets at most nothing: focus is checked before every character."""
    import types
    sent = []
    monkeypatch.setitem(sys.modules, "pywinauto.keyboard", types.SimpleNamespace(send_keys=lambda k, **kw: sent.append(k)))
    be = object.__new__(desktop.Backend)
    be.os, be._last_sent, be.target = "Windows", 0.0, 1
    checks = iter([True, True, True, False])
    be.on_target = lambda fg=None: next(checks)
    with pytest.raises(desktop.Refused, match="3/10"):
        be.type("abcdefghij")
    assert sent == ["a", "b", "c"]


def test_cleanup_runs_only_when_the_run_stopped_early(tmp_path):
    fake = Fake(texts={"box": "typed"})
    cleanup = [{"do": "key", "keys": ["backspace"]}]
    stop = [{"do": "launch", "app": "notepad"}, {"do": "assert_text", "case": "X", "control": "box", "equals": "other", "stop_on_fail": True}]
    res = desktop.run(stop, FULL, str(tmp_path / "a"), backend=fake, record=False, notice=False, cleanup_steps=cleanup)
    assert fake.texts["box"] == "" and [r["id"] for r in res] == ["X"]  # cleaned up; cleanup adds no result rows
    fake2 = Fake(texts={"box": "typed"})
    desktop.run(stop[:1], FULL, str(tmp_path / "b"), backend=fake2, record=False, notice=False, cleanup_steps=cleanup)
    assert fake2.texts["box"] == "typed"  # finished normally: no cleanup

    class Boom(Fake):
        def type(self, *a, **k):
            raise RuntimeError("FailSafeException")
    fake3 = Boom(texts={"box": "typed"})
    desktop.run([{"do": "launch", "app": "notepad"}, {"do": "type", "text": "x"}], FULL, str(tmp_path / "c"), backend=fake3,
                record=False, notice=False, cleanup_steps=cleanup)
    assert fake3.texts["box"] == "typed"  # emergency stop: nothing else runs


def test_a_screenshot_that_was_not_taken_is_a_fail(tmp_path):
    class NoShot(Fake):
        def screenshot(self, *a, **k):
            raise RuntimeError("another window is in front of the target")
    res = desktop.run([{"do": "launch", "app": "notepad"}, {"do": "screenshot", "case": "S1", "name": "x"}], FULL, str(tmp_path),
                      backend=NoShot(), record=False, notice=False)
    assert res[-1]["result"] == "FAIL" and "in front" in res[-1]["note"]


def test_hook_guard_reads_plan_files_with_steps_and_cleanup(tmp_path):
    import hook_guard
    (tmp_path / "qa.config.yaml").write_text("desktop:\n  enabled: true\n  allow_apps: [notepad]\n", encoding="utf-8")
    plan = os.path.join(ROOT, "templates", "desktop-steps.notepad.json")
    assert hook_guard.classify_command(f'python scripts/desktop.py run "{plan}"', str(tmp_path))[0] == "ask"
    (tmp_path / "bad.json").write_text(json.dumps({"steps": [{"do": "launch", "app": "notepad"}],
                                                   "cleanup": [{"do": "key", "keys": ["win", "r"]}]}), encoding="utf-8")
    assert hook_guard.classify_command("python scripts/desktop.py run bad.json", str(tmp_path))[0] == "deny"
