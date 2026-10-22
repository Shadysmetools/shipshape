"""Smoke + end-to-end tests against the LOCAL demo page only (no external sites).
Needs: pip install playwright && python -m playwright install chromium; ffmpeg on PATH."""
import json
import os
import shutil
import subprocess

import pytest

import full_qa
import record
from conftest import ROOT

pytestmark = pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg not installed")
PLANS = os.path.join(ROOT, "examples", "demo-app", "plans")


def local_plan(tmp_path, name, url):
    plan = json.load(open(os.path.join(PLANS, name), encoding="utf-8"))
    plan["base_url"] = url
    p = tmp_path / name
    p.write_text(json.dumps(plan))
    return plan, str(p)


def probe(path):
    out = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "stream=codec_type:format=duration", "-of", "json", path],
                         capture_output=True, text=True).stdout
    return json.loads(out)


def test_smoke_recording_of_local_page(tmp_path, demo_site):
    plan, _ = local_plan(tmp_path, "signup.json", demo_site)
    plan["steps"].append({"do": "goto", "url": "https://example.com/", "case": "EXT-1", "stop_on_fail": False})
    s = record.run(plan, str(tmp_path / "out"), narrate=False, total_timeout=120, step_timeout=10)
    assert s["counts"]["PASS"] == 2  # TC-01, TC-02
    assert "example.com" in s["blocked_hosts"]  # the guard blocked the external request
    mp4 = tmp_path / "out" / s["video"]
    info = probe(str(mp4))
    assert float(info["format"]["duration"]) > 3
    assert (tmp_path / "out" / "trace.zip").stat().st_size > 0
    assert (tmp_path / "out" / "captions.srt").read_text(encoding="utf-8").startswith("1\n")


def test_never_pay_rule_stops_the_run(tmp_path, demo_site):
    plan, _ = local_plan(tmp_path, "pay-guard.json", demo_site)
    s = record.run(plan, str(tmp_path / "out"), narrate=False, total_timeout=120, step_timeout=10)
    assert "never-pay" in s["stopped"]
    assert s["summary"] == "2 pass / 0 fail / 1 blocked (3 total)"


def test_live_site_stops_before_input(tmp_path, demo_site):
    plan, _ = local_plan(tmp_path, "signup.json", demo_site)
    plan["live"] = True
    s = record.run(plan, str(tmp_path / "out"), narrate=False, total_timeout=120, step_timeout=10)
    assert "stop-before-input" in s["stopped"]
    assert s["counts"]["FAIL"] == 0 and s["counts"]["BLOCKED"] == 1


def test_full_qa_end_to_end_dry_run(tmp_path, demo_site, capsys, monkeypatch):
    _, plan = local_plan(tmp_path, "signup.json", demo_site)
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "000:fake")
    root = tmp_path / "qa-runs"
    rc = full_qa.main(["Signup works", "--plan", plan, "--root", str(root), "--config", os.path.join(ROOT, "examples", "demo-app", "qa.config.yaml"),
                       "--url", demo_site, "--allow-host", "127.0.0.1", "--load", "smoke", "--load-scale", "0.4", "--repo", os.path.join(ROOT, "examples"),
                       "--max-rounds", "2"])
    out = capsys.readouterr().out
    run = next(p for p in root.iterdir() if p.is_dir())
    led = json.loads((run / "ledger.json").read_text())
    assert rc == 0 and led["status"] == "met", out[-1500:]
    assert led["rounds"][0]["summary"] == "2 pass / 0 fail (2 total)"
    assert os.path.isdir(run / "round-01" / "signup" / "pass-2")  # every scenario ran twice
    assert led["load"]["summary"] == "4 pass / 0 fail" and "security" in led
    html = (run / "report.html").read_text(encoding="utf-8")
    assert "<video" in html and "Goal met" in html
    assert "[dry-run] telegram" in out and "000:fake" not in out
