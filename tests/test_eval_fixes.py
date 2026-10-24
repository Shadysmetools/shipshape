"""Regression tests for the fixes from the 0.1.0 evaluation (numbered as in its top-10 list)."""
import io
import json
import os
import subprocess
import sys

import pytest

import hook_guard
import narrator
import notify
import privacy
import qa_loop
import qa_report_html
import record
from conftest import ROOT

PLAN = {"name": "p", "base_url": "http://127.0.0.1:8765/", "allow_hosts": ["127.0.0.1"], "steps": [{"do": "goto", "url": "index.html"}]}


# ---------------------------------------------------------------- #1 --url wins over the plan
def test_1_url_override_replaces_plan_base_url_and_says_so():
    p = record.apply_target(PLAN, "http://127.0.0.1:8799/", ["127.0.0.1"])
    assert p["base_url"] == "http://127.0.0.1:8799/"
    assert p["_target_notes"] and "plan says http://127.0.0.1:8765" in p["_target_notes"][0]
    same = record.apply_target(PLAN, "http://127.0.0.1:8765")
    assert same["_target_notes"] == []  # same target, nothing to warn about


def test_1_run_plan_passes_the_target_to_the_recorder(tmp_path, monkeypatch):
    seen = {}

    class P:
        returncode = 0
        stdout = "[record] base_url override: plan says a, running against b"

    def fake_run(cmd, **k):
        seen["cmd"] = cmd
        os.makedirs(cmd[cmd.index("--out") + 1], exist_ok=True)
        json.dump({"results": []}, open(os.path.join(cmd[cmd.index("--out") + 1], "results.json"), "w"))
        return P()

    monkeypatch.setattr(qa_loop.subprocess, "run", fake_run)
    plan = tmp_path / "p.json"
    plan.write_text(json.dumps(PLAN))
    qa_loop.run_plan(str(plan), str(tmp_path / "out"), 60, target={"url": "http://127.0.0.1:8799/", "allow_hosts": ["127.0.0.1"]})
    cmd = seen["cmd"]
    assert cmd[cmd.index("--base-url") + 1] == "http://127.0.0.1:8799/" and "--allow-host" in cmd


def test_1_dead_target_cannot_pass(tmp_path, demo_site):
    """The evaluator's exact trap: a plan whose base_url answers, run with --url pointing at a dead port."""
    plan = dict(PLAN, base_url=demo_site, steps=[{"do": "goto", "url": "index.html"},
                                                  {"do": "expect_text", "text": "Create your account", "case": "TC-01"}])
    s = record.run(record.apply_target(plan, "http://127.0.0.1:8799/"), str(tmp_path / "out"), total_timeout=60, step_timeout=5)
    assert s["counts"]["PASS"] == 0 and s["counts"]["FAIL"] >= 1
    assert s["base_url"] == "http://127.0.0.1:8799/" and s["target_notes"]


def test_1_ledger_records_target_and_relative_plans(tmp_path):
    plan = tmp_path / "plans" / "x.json"
    plan.parent.mkdir()
    plan.write_text(json.dumps(PLAN))
    root = tmp_path / "qa-runs"
    assert qa_loop.main(["start", "--root", str(root), "--goal", "g", "--plan", str(plan), "--url", "http://127.0.0.1:1/", "--allow-host", "127.0.0.1"]) == 0
    run = qa_loop.newest_open(str(root))
    led = qa_loop.load(run)
    assert led["target"] == {"url": "http://127.0.0.1:1/", "allow_hosts": ["127.0.0.1"]}
    assert not os.path.isabs(led["plans"][0]) and "Users" not in json.dumps(led)
    assert os.path.isfile(qa_loop.plan_path(run, led["plans"][0]))


# ---------------------------------------------------------------- #2 any drive letter
def test_2_privacy_catches_any_drive_letter():
    hits = {k for k, *_ in privacy.find(r'"file": "E:\\acme-dev\\kit\\docs\\x.mp4"', [])}
    assert "user_path" in hits
    assert "user_path" in {k for k, *_ in privacy.find("D:/work/client-x/repo/file.txt", [])}
    assert "[home]" in privacy.mask_text(r"see E:\acme-dev\kit\x", deny=[])
    assert not list(privacy.find("version 17.0.1.2.0 at 10:30", []))  # a time is not a drive path


# ---------------------------------------------------------------- #4 config errors are one line
def test_4_config_errors(tmp_path, capsys):
    bad = tmp_path / "qa.config.yaml"
    bad.write_text("notify:\n  telegram:\n    enabled: true\n    token: 12345\n")
    with pytest.raises(notify.ConfigError, match=r"notify\.telegram\.token: expected \{env: NAME\}"):
        notify.load_config(str(bad))
    bad.write_text("notify: [\n")
    with pytest.raises(notify.ConfigError, match="not valid YAML"):
        notify.load_config(str(bad))
    bad.write_text("notify:\n  slack:\n    enabled: yes please\n")
    with pytest.raises(notify.ConfigError, match=r"slack\.enabled: expected true or false"):
        notify.load_config(str(bad))
    assert notify.main([str(tmp_path), "--config", str(bad)]) == 2
    out = capsys.readouterr().out
    assert out.startswith("ERROR: config error") and "Traceback" not in out


# ---------------------------------------------------------------- #5 bad plan files fail fast
def test_5_record_main_reports_bad_plans(tmp_path, capsys):
    assert record.main([str(tmp_path / "missing.json"), "--out", str(tmp_path / "o")]) == 2
    assert "plan file not found" in capsys.readouterr().out
    broken = tmp_path / "broken.json"
    broken.write_text('{"name": "x", "steps": [\n  {"do": "goto",\n]')
    assert record.main([str(broken), "--out", str(tmp_path / "o")]) == 2
    out = capsys.readouterr().out
    assert "not valid JSON" in out and "line 3" in out and "Traceback" not in out


def test_5_full_qa_refuses_missing_plan_before_running(tmp_path, capsys):
    import full_qa
    rc = full_qa.main(["nope", "--plan", str(tmp_path / "does-not-exist.json"), "--root", str(tmp_path / "runs")])
    assert rc == 2 and "plan file not found" in capsys.readouterr().out
    assert not (tmp_path / "runs").exists()


# ---------------------------------------------------------------- #6 narration is surfaced
def test_6_narration_note_and_report_badge(tmp_path, monkeypatch):
    class Fail:
        @staticmethod
        def speak(text, *a, **k):
            raise RuntimeError("narration failed after 3 tries: offline")

    monkeypatch.setitem(sys.modules, "tts", Fail)
    plan = dict(PLAN, base_url="about:blank", steps=[{"do": "goto", "url": "about:blank", "say": "hello"}])
    s = record.run(plan, str(tmp_path / "out"), narrate=True, total_timeout=30, step_timeout=5)
    assert s["narrated"] is False and "not synthesized" in s["narration_note"]
    run = tmp_path / "2026-01-05-g"
    run.mkdir()
    led = qa_loop.new_ledger("g", ["p.json"])
    qa_loop.absorb_round(led, [{"plan": "p.json", "dir": "r/p/pass-1", "results": [{"id": "A", "result": "PASS", "evidence": "a.png"}],
                                "narration": ["voice", "narration off (--narrate not given)"]}], "2026-01-05T10:00:00", "2026-01-05T10:01:00", 1.0)
    qa_loop.save(str(run), led)
    html = open(qa_report_html.build(str(run), str(tmp_path)), encoding="utf-8").read()
    assert "pass 1: voice" in html and "pass 2: no voice (narration off" in html


def test_6_both_passes_are_narrated(tmp_path):
    led = qa_loop.new_ledger("g", [str(tmp_path / "p.json")])
    calls = []
    qa_loop.run_round(str(tmp_path), led, narrate=True, passes=2,
                      runner=lambda plan, out, timeout, narrate, target=None: calls.append(narrate) or {"results": [], "narrated": narrate})
    assert calls == [True, True]
    assert led["rounds"][0]["runs"][0]["narration"] == ["voice", "voice"]


# ---------------------------------------------------------------- #7 narrator degrades
def test_7_narrator_report_offline_writes_captions_only(tmp_path, monkeypatch, capsys):
    def dead(*a, **k):
        raise RuntimeError("narration failed after 3 tries: offline")

    monkeypatch.setattr(narrator, "say", dead)
    run = tmp_path / "run"
    run.mkdir()
    (run / "ledger.json").write_text(json.dumps({"goal": "g", "status": "met", "bugs": [], "rounds": [{"summary": "1 pass / 0 fail (1 total)", "runs": [{"results": []}]}]}))
    assert narrator.main(["report", str(run), "--lang", "en"]) == 0
    out = capsys.readouterr().out
    assert "[narrator] no voice" in out and "Traceback" not in out
    assert (run / "summary-en.srt").exists() and not (run / "summary-en.mp3").exists()
    assert narrator.main(["report", str(tmp_path / "missing")]) == 2


# ---------------------------------------------------------------- #8 pinned playwright, chromium only
def test_8_installer_pins_and_chromium_only():
    req = open(os.path.join(ROOT, "requirements.txt"), encoding="utf-8").read()
    assert "playwright==1.63.*" in req
    for f in ("bin/install.sh", "bin/install.ps1"):
        s = open(os.path.join(ROOT, f), encoding="utf-8").read()
        assert "--upgrade" not in s and "playwright install chromium\n" in s and "firefox webkit" in s
        assert "<owner>" not in s and "Shadysmetools/shipshape" in s


# ---------------------------------------------------------------- #9 hook guard
def guard(tool, **ti):
    return hook_guard.classify_command(ti["command"], ti.get("cwd")) if tool != "Read" else hook_guard.classify_read(ti["file_path"])


@pytest.mark.parametrize("cmd,decision", [
    ("cat .env", "deny"), ("type secrets\\team.json", "deny"), ("Get-Content ~/.ssh/id_ed25519", "deny"), ("head -5 server.key", "deny"),
    ("cat .env.example", None), ("cat README.md", None), ("ls -la", None), ("python scripts/report.py r.json", None),
    ("git push --force origin feat", "deny"), ("git push origin main", "deny"), ("git push -f", "deny"), ("git push origin feat/x", None),
    ("echo ghp_" + "A" * 36, "deny"),
    ("git merge feat/x", "ask"), ("gh pr merge 12 --squash", "ask"), ("git branch -D old", "ask"), ("git push origin --delete old", "ask"),
    ("rm -rf src/", "ask"), ("rm -rf qa-runs/old", None), ("Remove-Item -Recurse -Force build", None), ("Remove-Item -Recurse -Force C:\\proj\\src", "ask"),
])
def test_9_hook_guard_decisions(cmd, decision):
    v = hook_guard.classify_command(cmd, os.getcwd())
    assert (v[0] if v else None) == decision, (cmd, v)


def test_9_hook_guard_read_tool():
    assert hook_guard.classify_read("C:/proj/.env")[0] == "deny"
    assert hook_guard.classify_read("C:/proj/secrets/bots.json")[0] == "deny"
    assert hook_guard.classify_read("C:/proj/templates/qa.config.example.yaml") is None
    assert hook_guard.classify_read("C:/proj/README.md") is None


def test_9_hook_guard_notify_and_desktop(tmp_path):
    cfg = tmp_path / "qa.config.yaml"
    cfg.write_text("notify:\n  telegram: {enabled: true, token: {env: T}, chat_id: '1'}\n  slack: {enabled: false}\ndesktop: {enabled: true, allow_apps: [notepad]}\n")
    base = f"python scripts/notify.py qa-runs/x --config {cfg} --send"
    assert hook_guard.classify_command(base, str(tmp_path))[0] == "ask"
    assert hook_guard.classify_command(base + " --only slack", str(tmp_path))[0] == "deny"
    assert hook_guard.classify_command(base + " --only discord", str(tmp_path))[0] == "deny"
    assert hook_guard.classify_command(f"python scripts/notify.py qa-runs/x --config {cfg}", str(tmp_path)) is None  # dry-run: no gate
    steps = tmp_path / "steps.json"
    steps.write_text(json.dumps([{"do": "open", "app": "notepad"}]))
    assert hook_guard.classify_command(f"python scripts/desktop.py run {steps} --config {cfg}", str(tmp_path))[0] == "ask"
    steps.write_text(json.dumps([{"do": "open", "app": "MyBank"}]))
    v = hook_guard.classify_command(f"python scripts/desktop.py run {steps} --config {cfg}", str(tmp_path))
    assert v[0] == "deny" and "banking" in v[1]
    assert hook_guard.classify_command(f"python scripts/desktop.py run {steps} --config {cfg} --dry-run", str(tmp_path)) is None


def test_9_hook_guard_end_to_end_json(tmp_path):
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    (tmp_path / "a.py").write_text('TOKEN = "ghp_' + "E" * 36 + '"\n')
    subprocess.run(["git", "-C", str(tmp_path), "add", "a.py"], check=True)
    payload = json.dumps({"tool_name": "Bash", "tool_input": {"command": "git commit -m x"}, "cwd": str(tmp_path)})
    p = subprocess.run([sys.executable, os.path.join(ROOT, "scripts", "hook_guard.py")], input=payload, capture_output=True, text=True)
    out = json.loads(p.stdout)["hookSpecificOutput"]
    assert p.returncode == 0 and out["permissionDecision"] == "deny" and "a.py:1: github_token" in out["permissionDecisionReason"]
    assert "EEEE" not in p.stdout
    ok = subprocess.run([sys.executable, os.path.join(ROOT, "scripts", "hook_guard.py")],
                        input=json.dumps({"tool_name": "PowerShell", "tool_input": {"command": "git status"}}), capture_output=True, text=True)
    assert ok.returncode == 0 and ok.stdout == ""


def test_9_hooks_json_is_small_and_distinct():
    hooks = json.load(open(os.path.join(ROOT, "hooks", "hooks.json")))["hooks"]
    handlers = [h for g in hooks.values() for m in g for h in m["hooks"]]
    texts = [h.get("prompt") or h.get("command") for h in handlers]
    assert len(handlers) == 6 and len(set(texts)) == 6
    pre = {m["matcher"]: m for m in hooks["PreToolUse"]}
    assert "Bash|PowerShell|Read" in pre and pre["Bash|PowerShell|Read"]["hooks"][0]["type"] == "command"
    assert not any("cat *" in (h.get("if") or "") for h in handlers)
    market = json.load(open(os.path.join(ROOT, ".claude-plugin", "marketplace.json")))
    assert market["plugins"][0]["source"] == "."


# ---------------------------------------------------------------- #10 wrappers and doctor
def test_10_wrappers_check_the_port_and_kill_the_tree():
    sh = open(os.path.join(ROOT, "bin", "run-qa.sh"), encoding="utf-8").read()
    ps = open(os.path.join(ROOT, "bin", "run-qa.ps1"), encoding="utf-8").read()
    assert "port_busy" in sh and "stop_tree" in sh and "taskkill" in sh
    assert "Get-NetTCPConnection" in ps and "Stop-Tree" in ps and "already in use" in ps
    doc = open(os.path.join(ROOT, "scripts", "doctor.py"), encoding="utf-8").read()
    assert '"version"], 15)' in doc and '"version"], 60)' not in doc
