"""Goal loop: stop conditions, ledger resume, bug/gate bookkeeping, old-run reading, HTML report."""
import json
import os

import qa_history
import qa_loop
import qa_report_html


def rnd(n, results, finished="2026-01-05T10:00:00"):
    return {"n": n, "finished": finished, "runs": [{"plan": "p.json", "dir": "round/p/pass-1", "results": results}]}


def absorb(led, results, finished="2026-01-05T10:00:00", minutes=1.0):
    return qa_loop.absorb_round(led, [{"plan": "p.json", "dir": "r/p/pass-1", "results": results}], finished, finished, minutes)


R_PASS = {"id": "TC-1", "title": "signup", "result": "PASS", "evidence": "a.png"}
R_FAIL = {"id": "TC-1", "title": "signup", "result": "FAIL", "evidence": "a.png", "note": "button missing"}


def test_new_ledger_runs_first():
    led = qa_loop.new_ledger("goal", ["p.json"])
    assert qa_loop.decide(led) == {"stop": False, "reason": None, "status": "running", "next": "run-round"}


def test_goal_met_when_everything_passes():
    led = qa_loop.new_ledger("goal", ["p.json"])
    absorb(led, [R_PASS])
    d = qa_loop.decide(led)
    assert d["stop"] and d["status"] == "met" and "1 pass / 0 fail" in d["reason"]


def test_failure_opens_suspected_bug_then_verify_refute_then_file_then_wait():
    led = qa_loop.new_ledger("goal", ["p.json"])
    absorb(led, [R_FAIL])
    assert led["bugs"][0]["status"] == "suspected"
    assert qa_loop.decide(led)["next"] == "verify-refute"
    led["bugs"][0]["status"] = "verified"
    assert qa_loop.decide(led)["next"] == "file-bugs"
    led["bugs"][0]["status"] = "filed"
    assert qa_loop.decide(led)["next"] == "wait-fix"
    led["bugs"][0]["status"], led["bugs"][0]["fixed_at"] = "fixed", "2026-01-05T11:00:00"
    assert qa_loop.decide(led)["next"] == "run-round"
    absorb(led, [R_PASS], "2026-01-05T12:00:00")
    assert led["bugs"][0]["status"] == "retest-pass"
    assert qa_loop.decide(led)["status"] == "met"


def test_failed_retest_goes_back_to_suspected():
    led = qa_loop.new_ledger("goal", ["p.json"])
    absorb(led, [R_FAIL])
    led["bugs"][0].update(status="fixed", fixed_at="2026-01-05T11:00:00")
    absorb(led, [R_FAIL], "2026-01-05T12:00:00")
    assert led["bugs"][0]["status"] == "suspected" and len(led["bugs"]) == 1


def test_stop_on_max_rounds_and_budget():
    led = qa_loop.new_ledger("goal", ["p.json"], max_rounds=2, budget_min=100)
    led["bugs"] = [{"id": "B1", "case": "X", "status": "refuted"}]
    absorb(led, [R_FAIL])
    led["bugs"] = []
    absorb(led, [dict(R_FAIL, id="TC-2")], "2026-01-05T11:00:00")
    d = qa_loop.decide(led)
    assert d["stop"] and "max rounds" in d["reason"]
    led2 = qa_loop.new_ledger("goal", ["p.json"], budget_min=5)
    absorb(led2, [R_FAIL], minutes=6)
    led2["bugs"] = []
    assert "budget" in qa_loop.decide(led2)["reason"]


def test_stop_on_no_progress():
    led = qa_loop.new_ledger("goal", ["p.json"], max_rounds=9)
    absorb(led, [R_FAIL], "2026-01-05T10:00:00")
    led["bugs"][0]["status"] = "refuted"
    absorb(led, [R_FAIL], "2026-01-05T11:00:00")
    led["bugs"] = [b for b in led["bugs"] if b["status"] == "refuted"]
    d = qa_loop.decide(led)
    assert d["stop"] and "no progress" in d["reason"]


def test_flaky_blocks_goal_met():
    led = qa_loop.new_ledger("goal", ["p.json"])
    absorb(led, [dict(R_PASS, result="FLAKY")])
    assert not qa_loop.decide(led)["stop"]


def test_guard_stop_opens_human_gate():
    led = qa_loop.new_ledger("goal", ["p.json"])
    absorb(led, [R_PASS, {"id": "TC-3", "result": "BLOCKED", "note": "never-pay rule: payment / checkout step refused"}])
    d = qa_loop.decide(led)
    assert d["status"] == "waiting-human" and "TC-3" in d["reason"]
    assert not led["bugs"]


def test_ledger_survives_restart_and_resume(tmp_path):
    root = tmp_path / "qa-runs"
    plan = tmp_path / "p.json"
    plan.write_text("{}")
    assert qa_loop.main(["start", "--root", str(root), "--goal", "Signup works", "--plan", str(plan)]) == 0
    run = qa_loop.newest_open(str(root))
    assert run and run.endswith("signup-works")
    led = qa_loop.load(run)
    absorb(led, [R_FAIL])
    qa_loop.save(run, led)
    # "restart": a fresh start with the same goal resumes the same ledger
    assert qa_loop.main(["start", "--root", str(root), "--goal", "Signup works", "--plan", str(plan)]) == 0
    assert len(qa_loop.load(run)["rounds"]) == 1
    assert qa_loop.main(["bug", "--run", run, "--id", "B1", "--status", "refuted", "--note", "env issue"]) == 0
    assert qa_loop.load(run)["bugs"][0]["status"] == "refuted"


def test_attach_security_keeps_only_the_count(tmp_path):
    root = tmp_path / "qa-runs"
    plan = tmp_path / "p.json"
    plan.write_text("{}")
    qa_loop.main(["start", "--root", str(root), "--goal", "g", "--plan", str(plan)])
    run = qa_loop.newest_open(str(root))
    sec = tmp_path / "security.json"
    sec.write_text(json.dumps({"count": 2, "counts": {"high": 1}, "findings": [{"title": "secret detail"}]}))
    qa_loop.main(["attach", "--run", run, "--kind", "security", "--file", str(sec)])
    led = qa_loop.load(run)
    assert led["security"]["count"] == 2 and "findings" not in json.dumps(led["security"])


def test_round_runs_each_plan_twice_and_flags_flaky(tmp_path):
    led = qa_loop.new_ledger("g", [str(tmp_path / "plan.json")])
    calls = []

    def fake_runner(plan, out, timeout, narrate, target=None):
        calls.append(out)
        res = "PASS" if len(calls) == 1 else "FAIL"
        return {"summary": "", "results": [{"id": "TC-1", "result": res, "evidence": "x.png"}]}

    rnd = qa_loop.run_round(str(tmp_path), led, passes=2, runner=fake_runner)
    assert len(calls) == 2 and calls[0].endswith("pass-1") and calls[1].endswith("pass-2")
    assert rnd["counts"]["FLAKY"] == 1


def _make_history(root):
    for i, (date, results) in enumerate([("2026-01-01", [R_FAIL]), ("2026-01-02", [R_PASS]), ("2026-01-03", [R_FAIL]),
                                         ("2026-01-04", [R_PASS])]):
        run = os.path.join(root, f"{date}-signup")
        os.makedirs(run)
        led = qa_loop.new_ledger("signup", ["p.json"])
        led["created"] = date + "T09:00:00"
        absorb(led, results, date + "T10:00:00")
        qa_loop.save(run, led)
    return run


def test_history_trend_flaky_and_recheck(tmp_path):
    _make_history(str(tmp_path))
    h = qa_history.history(qa_history.load_runs(str(tmp_path)))
    assert [t["pass"] for t in h["trend"]] == [0, 1, 0, 1]
    assert h["flaky"][0]["case"] == "TC-1" and h["flaky"][0]["history"] == "FPFP"
    assert h["recheck"] == ["TC-1"]
    assert h["baseline"]["summary"].startswith("1 pass / 0 fail")


def test_html_report_is_self_contained(tmp_path):
    run = _make_history(str(tmp_path))
    shots = os.path.join(run, "r", "p", "pass-1")
    os.makedirs(shots)
    with open(os.path.join(shots, "01-TC-1-pass.png"), "wb") as fh:
        fh.write(b"\x89PNG\r\n\x1a\n" + b"0" * 20)
    out = qa_report_html.build(run, str(tmp_path))
    html = open(out, encoding="utf-8").read()
    assert "1 pass / 0 fail" in html and "data:image/png;base64," in html and "<svg" in html
    assert "http://" not in html and "https://" not in html  # no CDN: opens offline
