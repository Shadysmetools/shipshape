"""Acceptance tests for the P0 rows of docs/LESSONS-TO-BEHAVIOUR.md (one test per row id)."""
import io
import json
import os
import subprocess
import sys
import urllib.error

import pytest

import notify
import odoo_check
import record
import report
import security_scan
import stack_lock
import timesheet as ts
from conftest import ROOT


def read(*p):
    return open(os.path.join(ROOT, *p), encoding="utf-8").read()


def hooks():
    return json.loads(read("hooks", "hooks.json"))["hooks"]


# QA-01: evidence before "done"; no evidence -> "pushed, unverified"
def test_qa01_evidence_wording():
    assert "pushed, unverified" in read("agents", "qa-lead.md")
    stop = hooks()["Stop"][0]["hooks"][0]["prompt"]
    assert "evidence" in stop and "all green" in stop


# QA-02: counts from a FINISHED run only
def test_qa02_report_refuses_unfinished_run(tmp_path, capsys):
    f = tmp_path / "results.json"
    f.write_text(json.dumps({"results": [{"id": "A", "result": "PASS", "evidence": "a.png"}]}))
    assert report.main([str(f)]) == 2 and "not finished" in capsys.readouterr().out
    f.write_text(json.dumps({"finished_at": "2026-01-05T10:00:00", "results": [{"id": "A", "result": "PASS", "evidence": "a.png"}]}))
    assert report.main([str(f)]) == 0


# QA-03: refute before anything is filed or delivered
def test_qa03_refute_precedes_delivery():
    wf = read("workflows", "full-qa.workflow.js")
    assert wf.index("phase('Refute')") < wf.index("phase('Report')") < wf.index("phase('Deliver')")
    assert "survives" in wf and "qa-refuter" in wf


# QA-04: revert proof for regression tests
def test_qa04_revert_proof_rule():
    assert "revert proof" in read("agents", "qa-automation-tester.md")
    assert "RED before the fix" in read("templates", "BUG-LOG.md")


# QA-07: a scan proves it can find something first, else UNKNOWN
def test_qa07_positive_control(tmp_path, monkeypatch):
    findings, ran = security_scan.secrets(str(tmp_path))
    assert "privacy-sweep (control ok)" in ran
    monkeypatch.setattr(security_scan.privacy, "scan_paths", lambda *a, **k: [])
    findings, ran = security_scan.secrets(str(tmp_path))
    assert "UNKNOWN" in findings[0]["title"] and "privacy-sweep (control ok)" not in ran


# QA-13: queued lock + commit recorded at scenario start and end
def test_qa13_fifo_queue_order(tmp_path, monkeypatch):
    monkeypatch.setenv("SMEKIT_LOCK_DIR", str(tmp_path))
    path = stack_lock.lock_path("q")
    os.makedirs(path)
    first = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"])
    try:
        with open(os.path.join(path, "00000000000000000001-a.json"), "w") as fh:
            json.dump({"pid": first.pid, "owner": "first", "since": 0}, fh)
        assert not stack_lock.acquire(path, "second", wait=0, poll=0)
        assert stack_lock.read(path)["holder"]["owner"] == "first"
    finally:
        first.kill()
        first.wait()


def test_qa13_git_head_recorded(tmp_path):
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    subprocess.run(["git", "-C", str(tmp_path), "-c", "user.name=t", "-c", "user.email=t@example.com", "commit", "-q", "--allow-empty", "-m", "x"], check=True)
    assert record.git_head(str(tmp_path))
    assert record.git_head(str(tmp_path / "missing")) is None


# DL-01: retry with backoff, size-scaled timeout, Retry-After, no retry on 4xx, never resend a done step
def _err(code, retry_after=None):
    hdrs = {"Retry-After": retry_after} if retry_after else {}
    return urllib.error.HTTPError("https://api.example.com", code, "x", hdrs, io.BytesIO(b""))


def test_dl01_retry_policy():
    seen, sleeps = [], []

    def flaky(m, u, d=None, h=None, timeout=None):
        seen.append(timeout)
        if len(seen) < 3:
            raise _err(503, "7")
        return 200, "{}"

    assert notify.with_retry(flaky, "POST", "u", b"x" * (5 * notify.MB), sleep=sleeps.append) == (200, "{}")
    assert len(seen) == 3 and seen[0] == pytest.approx(max(120, 60 + 5 * 90)) and sleeps[0] >= 7
    calls = []

    def denied(m, u, d=None, h=None, timeout=None):
        calls.append(1)
        raise _err(401)

    with pytest.raises(urllib.error.HTTPError):
        notify.with_retry(denied, "POST", "u", sleep=lambda s: None)
    assert len(calls) == 1


def _run(tmp_path):
    run = tmp_path / "2026-01-05-goal"
    run.mkdir()
    (run / "ledger.json").write_text(json.dumps({"goal": "g", "status": "met", "rounds": [{"summary": "1 pass / 0 fail (1 total)"}]}))
    return str(run)


def test_dl01_never_resends_a_successful_step(tmp_path, monkeypatch):
    monkeypatch.setenv("SMEKIT_LOCK_DIR", str(tmp_path))
    cfg = {"notify": {"slack": {"enabled": True, "webhook_url": {"env": "S"}}}}
    env = {"S": "https://hooks.example.com/x", "SMEKIT_STATE_DIR": str(tmp_path / "state")}
    calls = []
    fn = lambda m, u, d=None, h=None, **k: calls.append(u) or (200, "{}")  # noqa: E731
    run = _run(tmp_path)
    assert notify.deliver(run, cfg, send=True, env=env, http_fn=fn, out=lambda *_: None)[0]["status"] == "SENT"
    second = notify.deliver(run, cfg, send=True, env=env, http_fn=fn, out=lambda *_: None)[0]
    assert len(calls) == 1 and second["already_sent"] == 1


# DL-05: one sender per channel (singleton) + persistent dedupe store
def test_dl05_one_sender_per_channel(tmp_path, monkeypatch):
    monkeypatch.setenv("SMEKIT_LOCK_DIR", str(tmp_path))
    path = stack_lock.lock_path("notify-slack")
    os.makedirs(path)
    other = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"])
    try:
        with open(os.path.join(path, "00000000000000000001-o.json"), "w") as fh:
            json.dump({"pid": other.pid, "owner": "other watcher", "since": 0}, fh)
        monkeypatch.setattr(stack_lock, "acquire", lambda *a, **k: False)  # do not wait 120 s in a test
        cfg = {"notify": {"slack": {"enabled": True, "webhook_url": {"env": "S"}}}}
        res = notify.deliver(_run(tmp_path), cfg, send=True, env={"S": "https://hooks.example.com/x", "SMEKIT_STATE_DIR": str(tmp_path)},
                             http_fn=lambda *a, **k: (200, "{}"), out=lambda *_: None)
        assert res[0]["status"] == "FAIL" and "another sender" in res[0]["detail"]
    finally:
        other.kill()
        other.wait()
    assert notify.store_path({"SMEKIT_STATE_DIR": str(tmp_path / "s")}).endswith("delivery-sent.json")


# SEC-01: secrets are never read or printed (deterministic guard on Bash, PowerShell and Read)
def test_sec01_secret_read_guard():
    import hook_guard
    for cmd in ("cat .env", "type .env.local", "Get-Content secrets/bots.json", "less ~/.ssh/id_rsa", "cat C:/x/token.json"):
        assert hook_guard.classify_command(cmd, os.getcwd())[0] == "deny", cmd
    assert hook_guard.classify_read("/home/x/proj/.env")[0] == "deny"
    assert hook_guard.classify_command("cat .env.example", os.getcwd()) is None
    pre = hooks()["PreToolUse"]
    assert any(m["matcher"] == "Bash|PowerShell|Read" and m["hooks"][0]["type"] == "command" for m in pre)


# SEC-05: no input on checkout/payment pages or live client hosts
def test_sec05_no_input_on_payment_pages():
    plan = {"live": False}
    assert "never-pay" in record.refuse_reason({"do": "fill", "selector": "#name", "value": "x"}, plan, "https://shop.example.com/checkout/step-2")
    assert record.refuse_reason({"do": "fill", "selector": "#name", "value": "x"}, plan, "https://shop.example.com/account") is None
    assert record.refuse_reason({"do": "fill", "selector": "#card", "value": "x"}, {"payment_mock": True}, "http://127.0.0.1:8000/checkout") is None
    assert "stop-before-input" in record.refuse_reason({"do": "fill", "selector": "#q", "value": "x"}, {"live": True}, "https://client.example.com/")


# TS-02: sorted stamps, no negative or overlapping intervals
def test_ts02_invariants_on_adversarial_input():
    t0 = 1_767_600_000
    noisy = [[t0 + 600, t0, t0, t0 + 300, t0 + 300], [t0 + 200, t0 + 100, t0 + 2000, t0 + 1900]]
    merged, blocks, total = ts.measure(noisy, 20)
    assert all(b >= a for a, b in merged) and all(x["sec"] >= 0 for x in blocks)
    assert all(n["start"] >= p["end"] for p, n in zip(blocks, blocks[1:]))
    assert total == pytest.approx((600 + 100) / 3600)


# OD-01: sending modules ship neutralize.sql and default to sending off
def test_od01_send_off_default(tmp_path):
    m = tmp_path / "mod"
    (m / "models").mkdir(parents=True)
    (m / "tests").mkdir()
    (m / "__manifest__.py").write_text(repr({"name": "m", "version": "17.0.1.0.0", "license": "LGPL-3", "data": []}))
    (m / "models" / "config.py").write_text("from odoo import fields, models\nclass C(models.Model):\n    _name = 'c'\n"
                                            "    enabled = fields.Boolean(default=True)\n\n    def go(self):\n        self.env['mail.mail'].create({}).send()\n")
    (m / "tests" / "test_a.py").write_text("")
    rows = {n: s for n, s, _ in odoo_check.check(str(m)).rows}
    assert rows["send-off-default"] == "FAIL" and rows["neutralize"] == "FAIL"


# PR-01: one promotion at a time with rollback, replay and a watch
def test_pr01_promotion_rule():
    pb = read("docs", "ODOO-PLAYBOOK.md")
    assert "60-minute watch" in pb and "rollback first" in pb.lower()


# WIN-02: BOM and zero-width characters stripped from config values
def test_win02_bom_and_zero_width(tmp_path):
    cfg = tmp_path / "qa.config.yaml"
    cfg.write_bytes("﻿notify:\n  slack: {enabled: true}\n".encode("utf-8"))
    assert notify.load_config(str(cfg))["notify"]["slack"]["enabled"] is True
    assert notify.secret({"env": "T"}, {"T": "﻿ abc​\n"}) == "abc"


# CO-01: only the owner's own words count as approval (merges, deletes, writes, sends)
def test_co01_owner_words_only():
    import hook_guard
    for cmd in ("git merge feat", "gh pr merge 7", "rm -rf src", "git branch -D x", "git push origin --delete x"):
        v = hook_guard.classify_command(cmd, os.getcwd())
        assert v and v[0] == "ask", cmd  # a real permission prompt: nothing relayed can click it
    pre = hooks()["PreToolUse"]
    prompts = " ".join(h["prompt"] for m in pre for h in m["hooks"] if h["type"] == "agent")
    assert prompts.count("relayed") >= 2  # Odoo writes and outward sends still check the conversation
