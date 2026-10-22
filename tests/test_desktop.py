"""Desktop layer: safety gates and logging in dry-run / mock mode. The real-desktop
smoke test only runs with SMEKIT_DESKTOP_SMOKE=1 (CI never controls a desktop)."""
import json
import os
import platform
import shutil

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


@pytest.mark.skipif(os.environ.get("SMEKIT_DESKTOP_SMOKE") != "1", reason="real desktop smoke test: set SMEKIT_DESKTOP_SMOKE=1")
def test_real_desktop_smoke(tmp_path):
    """Opens Notepad (Windows) or TextEdit (macOS), types one line, records ~5 s. Close it yourself without saving."""
    if not shutil.which("ffmpeg"):
        pytest.skip("ffmpeg missing")
    app = "notepad" if platform.system() == "Windows" else "TextEdit"
    steps = [{"do": "open", "app": app}, {"do": "wait", "sec": 1.5},
             {"do": "type", "window": "Notepad" if app == "notepad" else "TextEdit", "text": "ShipShape desktop smoke test (fake data)"},
             {"do": "wait", "sec": 2}, {"do": "screenshot", "name": "typed"}]
    res = desktop.run(steps, CFG, str(tmp_path))
    assert res and res[-1]["result"] == "PASS"
    assert os.path.getsize(tmp_path / "desktop.mp4") > 0
