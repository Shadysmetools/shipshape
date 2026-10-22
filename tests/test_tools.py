"""Notifiers (mocked HTTP + dry-run), load tester, security wrappers, narrator, odoo check, stack lock."""
import json
import os
import subprocess
import sys
import textwrap

import pytest

import load_test
import narrator
import notify
import odoo_check
import security_scan
import stack_lock
from conftest import ROOT, serve


# ---------------------------------------------------------------- notifiers
def make_run(tmp_path, video_bytes=1000, security=0):
    run = tmp_path / "2026-01-05-signup"
    (run / "round-01" / "p" / "pass-1").mkdir(parents=True)
    led = {"goal": "Signup works", "status": "met", "rounds": [{"summary": "2 pass / 0 fail (2 total)"}], "bugs": []}
    if security:
        led["security"] = {"count": security}
    (run / "ledger.json").write_text(json.dumps(led))
    (run / "round-01" / "p" / "pass-1" / "v.mp4").write_bytes(b"0" * video_bytes)
    (run / "report.html").write_text("<html></html>")
    return str(run)


CFG = {"notify": {
    "telegram": {"enabled": True, "token": {"env": "T_TOKEN"}, "chat_id": "-100", "topic_id": 20},
    "whatsapp": {"enabled": True, "provider": "meta", "token": {"env": "W_TOKEN"}, "phone_number_id": "123", "to": ["+00 000 000 0000"],
                 "template": {"name": "qa_run_summary", "language": "en"}},
    "slack": {"enabled": True, "webhook_url": {"env": "S_URL"}},
    "webhook": {"enabled": True, "url": {"env": "H_URL"}},
    "email": {"enabled": False}}, "video_link_base": "https://files.example.com/qa"}
ENV = {"T_TOKEN": "123:abc", "W_TOKEN": "wtok", "S_URL": "https://hooks.example.com/s", "H_URL": "https://hooks.example.com/h"}


def test_dry_run_sends_nothing_and_hides_tokens(tmp_path):
    run = make_run(tmp_path)
    printed, sent = [], []
    res = notify.deliver(run, CFG, env=ENV, http_fn=lambda *a, **k: sent.append(a), out=printed.append)
    assert not sent
    assert {r["channel"]: r["status"] for r in res} == {"telegram": "DRY-RUN", "whatsapp": "DRY-RUN", "slack": "DRY-RUN",
                                                         "webhook": "DRY-RUN", "email": "SKIPPED"}
    joined = "\n".join(printed)
    assert "123:abc" not in joined and "/bot<TOKEN>/" in joined and "message_thread_id" in joined


def test_channel_not_in_config_is_refused(tmp_path):
    res = notify.deliver(make_run(tmp_path), CFG, only="discord", env=ENV, out=lambda *_: None)
    assert res == [{"channel": "discord", "status": "REFUSED", "detail": "not listed in the project config"}]


def test_send_uses_mocked_http_for_each_channel(tmp_path, monkeypatch):
    monkeypatch.setenv("SMEKIT_LOCK_DIR", str(tmp_path))
    run = make_run(tmp_path)
    calls = []
    env = dict(ENV, SMEKIT_STATE_DIR=str(tmp_path / "state"))
    res = notify.deliver(run, CFG, send=True, env=env, http_fn=lambda m, u, d=None, h=None, **k: calls.append((u, h, d)) or (200, "{}"),
                         out=lambda *_: None)
    assert all(r["status"] in ("SENT", "SKIPPED") for r in res), res
    urls = [u for u, _h, _d in calls]
    assert any(u.endswith("/sendVideo") for u in urls) and any(u.endswith("/sendDocument") for u in urls)
    assert any("graph.facebook.com" in u and u.endswith("/123/messages") for u in urls)
    wa = [d for u, _h, d in calls if "graph.facebook.com" in u]
    assert b'"type": "template"' in wa[0] and b'"link": "https://files.example.com/qa/' in wa[1]
    assert any(h.get("Authorization") == "Bearer wtok" for u, h, _d in calls if "graph" in u)


def test_missing_secret_fails_cleanly(tmp_path):
    res = notify.deliver(make_run(tmp_path), CFG, send=True, only="telegram", env={}, out=lambda *_: None)
    assert res[0]["status"] == "FAIL" and "env var" in res[0]["detail"]


def test_oversized_video_is_not_attached(tmp_path, monkeypatch):
    run = make_run(tmp_path, video_bytes=10)
    monkeypatch.setitem(notify.LIMITS, "telegram", 5)
    monkeypatch.setattr(notify.shutil, "which", lambda *_: None)  # no ffmpeg -> cannot compress
    calls, _ = notify.plan_telegram(CFG["notify"]["telegram"], "hi", notify.fit_video(notify.find_video(run), 5, run), None, ENV)
    assert calls[0][1].endswith("/sendMessage")


def test_security_details_never_reach_the_message(tmp_path):
    run = make_run(tmp_path, security=3)
    txt = notify.summary_text(run, "en")
    assert "3 finding(s), see the private report" in txt
    assert "الأمان" in notify.summary_text(run, "ar")


def test_example_config_parses_and_has_no_secret_values():
    cfg = notify.load_config(os.path.join(ROOT, "templates", "qa.config.example.yaml"))
    assert set(cfg["notify"]) == {"telegram", "whatsapp", "slack", "email", "webhook"}
    assert all(not ch["enabled"] for ch in cfg["notify"].values())


# ---------------------------------------------------------------- load tester
def test_load_refuses_hosts_not_allow_listed(capsys):
    assert load_test.main(["--url", "https://shop.example.com/", "--allow-host", "127.0.0.1"]) == 1
    assert "REFUSED" in capsys.readouterr().out


def test_load_refuses_production_looking_host(capsys, monkeypatch):
    monkeypatch.delenv("SMEKIT_LOAD_OWNER_OK", raising=False)
    assert load_test.main(["--url", "https://prod.example.com/", "--allow-host", "prod.example.com"]) == 1


def test_percentiles_and_thresholds():
    vals = list(range(1, 101))
    assert load_test.percentile(vals, 95) == pytest.approx(95.05)
    st = {"p95_ms": 600, "p99_ms": 900, "error_rate": 0.0, "requests": 10}
    checks = load_test.verdict(st, 500, 1000, 0.01)
    assert [c["result"] for c in checks] == ["FAIL", "PASS", "PASS", "PASS"]


def test_load_smoke_against_local_server(tmp_path):
    with serve(os.path.join(ROOT, "examples", "demo-app")) as url:
        rc = load_test.main(["--url", url, "--profile", "smoke", "--scale", "0.4", "--allow-host", "127.0.0.1",
                             "--out", str(tmp_path), "--p95-ms", "2000", "--p99-ms", "4000"])
    res = json.loads((tmp_path / "load.json").read_text())
    assert rc == 0 and res["stats"]["requests"] > 0 and res["summary"] == "4 pass / 0 fail"
    assert (tmp_path / "load.svg").read_text().startswith("<svg")


# ---------------------------------------------------------------- security wrappers
def test_header_check_finds_missing_headers_and_bad_cookie(tmp_path):
    (tmp_path / "index.html").write_text("hi")
    with serve(str(tmp_path), headers={"Set-Cookie": "sid=abc; Path=/", "Access-Control-Allow-Origin": "https://evil.example",
                                       "Access-Control-Allow-Credentials": "true"}) as url:
        findings, ran = security_scan.headers(url, ["127.0.0.1"])
    titles = " | ".join(f["title"] for f in findings)
    assert ran and "Missing content-security-policy" in titles and "Cookie sid lacks" in titles
    assert any(f["severity"] == "high" and "CORS" in f["title"] for f in findings)
    assert all("abc" not in json.dumps(f) for f in findings)  # cookie values are not stored


def test_header_check_refuses_other_hosts():
    findings, ran = security_scan.headers("https://shop.example.com/", ["127.0.0.1"])
    assert not ran and "REFUSED" in findings[0]["title"]


def test_missing_tools_are_skipped_not_passed(tmp_path, monkeypatch):
    (tmp_path / "requirements.txt").write_text("requests==2.0.0\n")
    monkeypatch.setattr(security_scan.shutil, "which", lambda *_: None)
    _f, ran, skipped = security_scan.dependencies(str(tmp_path))
    assert not ran and any("pip-audit" in s for s in skipped) and any("osv-scanner" in s for s in skipped)


def test_secret_sweep_flags_planted_key(tmp_path):
    (tmp_path / "app.py").write_text('API_KEY = "sk-' + "z" * 40 + '"\n')
    findings, ran = security_scan.secrets(str(tmp_path))
    assert "privacy-sweep (control ok)" in ran and any(f["severity"] == "high" for f in findings)
    assert all("zzzz" not in json.dumps(f) for f in findings)


# ---------------------------------------------------------------- narrator
def test_report_lines_en_and_ar(tmp_path):
    run = tmp_path / "r"
    run.mkdir()
    led = {"goal": "Checkout", "status": "stopped", "bugs": [{"status": "filed"}], "security": {"count": 1},
           "rounds": [{"summary": "1 pass / 1 fail (2 total)", "runs": [{"results": [{"id": "TC-2", "title": "Pay with test card", "result": "FAIL"}]}]}]}
    (run / "ledger.json").write_text(json.dumps(led))
    en = narrator.report_lines(str(run), "en")
    assert en[0] == "QA run for: Checkout." and "Failed: Pay with test card." in en and any("security" in x for x in en)
    ar = narrator.report_lines(str(run), "ar")
    assert ar[0].startswith("تشغيل") and len(ar) == len(en)


def test_mix_command_ducks_video_audio_under_narration():
    cmd = narrator.mix_cmd("v.mp4", [(1.5, "a.mp3"), (6.0, "b.mp3")], "o.mp4", video_has_audio=True)
    fc = cmd[cmd.index("-filter_complex") + 1]
    assert "adelay=1500" in fc and "adelay=6000" in fc and "sidechaincompress" in fc
    silent = narrator.mix_cmd("v.mp4", [(0, "a.mp3")], "o.mp4", video_has_audio=False)
    assert "sidechaincompress" not in silent[silent.index("-filter_complex") + 1]


def test_paid_provider_without_key_falls_back_to_edge(monkeypatch):
    monkeypatch.setenv("SMEKIT_TTS_PROVIDER", "openai")
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setattr(narrator.tts, "speak", lambda text, voice, rate: ("edge.mp3", 1.0, False))
    assert narrator.say("hello", "ar") == ("edge.mp3", 1.0)


# ---------------------------------------------------------------- odoo check
def _module(tmp_path, good=True):
    m = tmp_path / "demo_module"
    (m / "data").mkdir(parents=True)
    (m / "models").mkdir()
    (m / "tests").mkdir()
    (m / "migrations" / "17.0.1.2.0").mkdir(parents=True)
    data = ["data/ir_cron.xml"] + ([] if good else ["data/neutralize.sql"])
    (m / "__manifest__.py").write_text(repr({"name": "Demo", "version": "17.0.1.2.0" if good else "1.2", "license": "LGPL-3", "data": data}))
    nu = ' noupdate="1"' if good else ""
    (m / "data" / "ir_cron.xml").write_text(f'<odoo><data{nu}><record id="cron_send" model="ir.cron"><field name="name">Send</field></record></data></odoo>')
    (m / "data" / "neutralize.sql").write_text("UPDATE ir_cron SET active = false WHERE id IN (SELECT res_id FROM ir_model_data WHERE module = 'demo_module' AND model = 'ir.cron');\n")
    sender = "import requests\n\ndef send(self):\n    if self._staging_reason():\n        return\n    requests.post('https://api.example.com')\n"
    if not good:
        sender += "\ndef bad(self):\n    self.env.cr.commit()\n"
    (m / "models" / "sender.py").write_text(sender)
    guard = "information_schema" if good else ""
    (m / "migrations" / "17.0.1.2.0" / "post-migration.py").write_text(textwrap.dedent(f"""
        def migrate(cr, version):
            # {guard}
            cr.execute("UPDATE demo SET x = 1")
        """))
    (m / "tests" / "__init__.py").write_text("from . import test_sender\n")
    (m / "tests" / "test_sender.py").write_text("")
    return str(m)


def test_odoo_check_good_module_passes(tmp_path):
    r = odoo_check.check(_module(tmp_path, good=True))
    assert not [x for x in r.rows if x[1] == "FAIL"], r.rows
    assert r.line().startswith(f"{len(r.rows)} pass / 0 fail") or "0 fail" in r.line()


def test_odoo_check_catches_every_unsafe_pattern(tmp_path):
    r = odoo_check.check(_module(tmp_path, good=False))
    fails = {name for name, s, _ in r.rows if s == "FAIL"}
    assert {"manifest", "crons-noupdate", "neutralize", "no-commit", "migration-guards"} <= fails, r.rows


# ---------------------------------------------------------------- stack lock
def test_stack_lock_is_fifo_and_drops_dead_tickets(tmp_path, monkeypatch):
    monkeypatch.setenv("SMEKIT_LOCK_DIR", str(tmp_path))
    path = stack_lock.lock_path("t")
    os.makedirs(path)
    sleeper = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"])
    try:
        # a live process queued first holds the lock; we wait behind it
        with open(os.path.join(path, "00000000000000000001-x.json"), "w") as fh:
            json.dump({"pid": sleeper.pid, "owner": "first", "since": 0}, fh)
        # a dead process's ticket is dropped, never honoured
        with open(os.path.join(path, "00000000000000000002-y.json"), "w") as fh:
            json.dump({"pid": 999999, "owner": "dead", "since": 0}, fh)
        assert not stack_lock.acquire(path, "me", wait=0, stale=1, poll=0)
        assert not os.path.exists(os.path.join(path, "00000000000000000002-y.json"))
    finally:
        sleeper.kill()
        sleeper.wait()
    assert stack_lock.acquire(path, "me", wait=5, stale=1, poll=0.1)  # first holder gone -> our turn
    stack_lock.release(path)
    assert stack_lock.read(path) == {"free": True}
    assert stack_lock.main(["run", "--name", "t2", "--wait", "1", "--", sys.executable, "-c", "print(1)"]) == 0
