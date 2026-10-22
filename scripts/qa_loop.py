#!/usr/bin/env python3
"""Goal-driven QA loop with a durable ledger (qa-runs/<date>-<goal>/ledger.json).

The agent (qa-tester, driven by /qa-goal and /loop) calls this script; the
script owns state, timeouts and stop conditions so a restart loses nothing.

    python scripts/qa_loop.py start  --goal "signup works" --plan plans/signup.json [--plan ...]
                                     [--max-rounds 5] [--budget-min 120] [--round-timeout 900] [--root qa-runs]
    python scripts/qa_loop.py round  [--run <dir>] [--narrate]    # run every plan once, record, update ledger
    python scripts/qa_loop.py status [--run <dir>]                # stop decision + the next action, as JSON
    python scripts/qa_loop.py bug    [--run <dir>] --id B1 --status verified|refuted|filed|fixed [--link URL] [--note ...]
    python scripts/qa_loop.py gate   [--run <dir>] --close G1 | --open "reason"
    python scripts/qa_loop.py resume [--root qa-runs]             # print the newest unfinished run dir

Next actions, in priority order:
  stop           a stop condition holds (goal met, max rounds, budget, no progress, human gate)
  verify-refute  a failure is "suspected": an independent verifier must reproduce it, then a refuter
                 must try to kill it; only a claim that survives both becomes "verified"
  file-bugs      "verified" bugs are not filed yet (needs the board / tracker; follow its rules)
  wait-fix       every open bug is filed and none is marked fixed: pause (ScheduleWakeup / /loop), then status again
  run-round      run (or re-run after fixes) every plan
"""
from __future__ import annotations

import argparse
import datetime as dt
import glob
import json
import os
import re
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
OPEN_BUG = ("suspected", "verified", "filed")
GUARD_NOTE = re.compile(r"never-pay|stop-before-input")


def now():
    return dt.datetime.now().strftime("%Y-%m-%dT%H:%M:%S")


def slug(text):
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")[:40] or "goal"


def load(run):
    with open(os.path.join(run, "ledger.json"), encoding="utf-8") as fh:
        return json.load(fh)


def save(run, ledger):
    tmp = os.path.join(run, "ledger.json.tmp")
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(ledger, fh, indent=1)
    os.replace(tmp, os.path.join(run, "ledger.json"))  # atomic: a crash never leaves half a ledger


def new_ledger(goal, plans, max_rounds=5, budget_min=120, round_timeout=900):
    return {"goal": goal, "created": now(), "status": "running", "stop_reason": None,
            "limits": {"max_rounds": max_rounds, "budget_minutes": budget_min, "round_timeout_sec": round_timeout},
            "plans": plans, "rounds": [], "bugs": [], "human_gates": [], "elapsed_minutes": 0.0}


def failing_set(rnd):
    return sorted({r["id"] for run in rnd["runs"] for r in run.get("results", []) if r["result"] in ("FAIL", "FLAKY", "BLOCKED")})


def decide(ledger):
    """Pure decision: returns {"stop": bool, "reason": str|None, "status": str, "next": str}."""
    lim = ledger["limits"]
    rounds = ledger["rounds"]
    gates = [g for g in ledger["human_gates"] if g.get("open")]
    bugs = ledger["bugs"]
    if gates:
        return {"stop": True, "reason": "human gate: " + gates[0]["reason"], "status": "waiting-human", "next": "stop"}
    if rounds:
        last = rounds[-1]
        c = last["counts"]
        open_bugs = [b for b in bugs if b["status"] in OPEN_BUG]
        if c.get("FAIL", 0) == 0 and c.get("FLAKY", 0) == 0 and c.get("BLOCKED", 0) == 0 and c.get("NOT CHECKED", 0) == 0 and c.get("PASS", 0) > 0 and not open_bugs:
            return {"stop": True, "reason": "goal met: " + last["summary"], "status": "met", "next": "stop"}
    if len(rounds) >= lim["max_rounds"]:
        return {"stop": True, "reason": f"max rounds ({lim['max_rounds']}) reached", "status": "stopped", "next": "stop"}
    if ledger["elapsed_minutes"] >= lim["budget_minutes"]:
        return {"stop": True, "reason": f"budget ({lim['budget_minutes']} min) used", "status": "stopped", "next": "stop"}
    if len(rounds) >= 2 and failing_set(rounds[-1]) and failing_set(rounds[-1]) == failing_set(rounds[-2]):
        fixed_between = any(b.get("fixed_at", "") > rounds[-2]["finished"] for b in bugs)
        if not fixed_between:
            return {"stop": True, "reason": "no progress: the same cases failed twice with no fix in between", "status": "stopped", "next": "stop"}
    if any(b["status"] == "suspected" for b in bugs):
        return {"stop": False, "reason": None, "status": "running", "next": "verify-refute"}
    if any(b["status"] == "verified" for b in bugs):
        return {"stop": False, "reason": None, "status": "running", "next": "file-bugs"}
    open_filed = [b for b in bugs if b["status"] == "filed"]
    if open_filed and not any(b["status"] == "fixed" for b in bugs):
        return {"stop": False, "reason": None, "status": "running", "next": "wait-fix"}
    return {"stop": False, "reason": None, "status": "running", "next": "run-round"}


def absorb_round(ledger, runs, started, finished, minutes):
    """Add a finished round, open suspected bugs for new failures, open human gates for guard stops,
    and mark fixed bugs as retest-pass / retest-fail."""
    counts = {k: 0 for k in ("PASS", "FAIL", "FLAKY", "BLOCKED", "SKIPPED", "NOT CHECKED")}
    results = [r for run in runs for r in run.get("results", [])]
    for r in results:
        counts[r["result"]] = counts.get(r["result"], 0) + 1
    counts["TOTAL"] = len(results)
    sys.path.insert(0, HERE)
    import report
    rnd = {"n": len(ledger["rounds"]) + 1, "started": started, "finished": finished, "minutes": round(minutes, 2),
           "runs": runs, "counts": counts, "summary": report.summary(counts)}
    ledger["rounds"].append(rnd)
    ledger["elapsed_minutes"] = round(ledger["elapsed_minutes"] + minutes, 2)
    by_case = {r["id"]: r for r in results}
    for b in ledger["bugs"]:
        if b["status"] == "fixed" and b["case"] in by_case:
            b["status"] = "retest-pass" if by_case[b["case"]]["result"] == "PASS" else "retest-fail"
            b["retested_in_round"] = rnd["n"]
            if b["status"] == "retest-fail":  # the fix did not hold: back to suspected, verify again
                b["status"] = "suspected"
    tracked = {b["case"] for b in ledger["bugs"] if b["status"] in OPEN_BUG}
    for r in results:
        if r["result"] == "BLOCKED" and GUARD_NOTE.search(r.get("note", "")):
            if not any(g["reason"].startswith(r["id"]) for g in ledger["human_gates"]):
                ledger["human_gates"].append({"id": f"G{len(ledger['human_gates']) + 1}", "reason": f"{r['id']}: {r['note']}",
                                              "open": True, "opened": finished})
        elif r["result"] == "FAIL" and r["id"] not in tracked:
            ledger["bugs"].append({"id": f"B{len(ledger['bugs']) + 1}", "case": r["id"], "title": r.get("title", ""),
                                   "status": "suspected", "evidence": r.get("evidence", ""), "note": r.get("note", ""),
                                   "round": rnd["n"], "verify": None, "refute": None, "link": None})
    return rnd


def run_plan(plan, out, timeout, narrate=False):
    cmd = [sys.executable, os.path.join(HERE, "record.py"), plan, "--out", out, "--total-timeout", str(timeout)]
    if narrate:
        cmd.append("--narrate")
    name = os.path.splitext(os.path.basename(plan))[0]
    try:
        subprocess.run(cmd, timeout=timeout + 120, capture_output=True)
        return json.load(open(os.path.join(out, "results.json"), encoding="utf-8"))
    except (subprocess.TimeoutExpired, OSError, ValueError) as exc:
        return {"summary": "0 pass / 0 fail / 1 blocked", "results": [{"id": f"{name}-run", "title": name, "result": "BLOCKED",
                                                                       "evidence": "", "note": f"run did not finish: {exc}"}]}


def run_round(run_dir, ledger, narrate=False, passes=2, runner=None):
    """Run every plan `passes` times (default 2, independent runs). With 2 passes a
    result counts only if both agree; otherwise it is FLAKY."""
    sys.path.insert(0, HERE)
    import report
    runner = runner or run_plan
    started, t0 = now(), time.time()
    runs = []
    timeout = ledger["limits"]["round_timeout_sec"]
    rdir = f"round-{len(ledger['rounds']) + 1:02d}"
    for plan in ledger["plans"]:
        name = os.path.splitext(os.path.basename(plan))[0]
        outs = [os.path.join(run_dir, rdir, name, f"pass-{k + 1}") for k in range(passes)]
        res = [runner(plan, o, timeout, narrate and k == 0) for k, o in enumerate(outs)]
        rows = res[0].get("results", [])
        if passes > 1:
            rows = report.combine_passes(res[0].get("results", []), res[1].get("results", []))
            for r in rows:  # evidence paths point into pass-1 unless only pass 2 has it
                r["evidence"] = r.get("evidence", "").split(" + ")[0]
        runs.append({"plan": plan, "dir": os.path.relpath(outs[0], run_dir).replace(os.sep, "/"), "passes": passes,
                     "summary": res[0].get("summary"), "video": res[0].get("video"), "results": rows,
                     "console": res[0].get("console", []), "network": res[0].get("network", []), "stopped": res[0].get("stopped"), "mixed": res[0].get("mixed")})
    return absorb_round(ledger, runs, started, now(), (time.time() - t0) / 60)


def newest_open(root):
    runs = sorted(glob.glob(os.path.join(root, "*", "ledger.json")), key=os.path.getmtime, reverse=True)
    for p in runs:
        try:
            if json.load(open(p, encoding="utf-8")).get("status") in ("running", "waiting-human"):
                return os.path.dirname(p)
        except ValueError:
            continue
    return None


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("cmd", choices=("start", "round", "status", "bug", "gate", "resume", "attach"))
    ap.add_argument("--root", default="qa-runs")
    ap.add_argument("--run")
    ap.add_argument("--goal")
    ap.add_argument("--plan", action="append", default=[])
    ap.add_argument("--max-rounds", type=int, default=5)
    ap.add_argument("--budget-min", type=int, default=120)
    ap.add_argument("--round-timeout", type=int, default=900)
    ap.add_argument("--narrate", action="store_true")
    ap.add_argument("--passes", type=int, default=2, choices=(1, 2), help="independent passes per plan (2 = flakiness check)")
    ap.add_argument("--id")
    ap.add_argument("--status", dest="bug_status", choices=("verified", "refuted", "filed", "fixed"))
    ap.add_argument("--link")
    ap.add_argument("--note")
    ap.add_argument("--kind", choices=("security", "load", "review"))
    ap.add_argument("--file")
    ap.add_argument("--close")
    ap.add_argument("--open", dest="open_reason")
    a = ap.parse_args(argv)

    if a.cmd == "start":
        if not a.goal or not a.plan:
            ap.error("start needs --goal and at least one --plan")
        run = os.path.join(a.root, f"{dt.date.today().isoformat()}-{slug(a.goal)}")
        os.makedirs(run, exist_ok=True)
        if os.path.exists(os.path.join(run, "ledger.json")):
            print(json.dumps({"run": run, "resumed": True, **decide(load(run))}))
            return 0
        save(run, new_ledger(a.goal, [os.path.abspath(p) for p in a.plan], a.max_rounds, a.budget_min, a.round_timeout))
        print(json.dumps({"run": run, "resumed": False, **decide(load(run))}))
        return 0
    if a.cmd == "resume":
        print(newest_open(a.root) or "")
        return 0
    run = a.run or newest_open(a.root)
    if not run:
        print("no open run; start one with: qa_loop.py start --goal ... --plan ...", file=sys.stderr)
        return 2
    ledger = load(run)
    if a.cmd == "round":
        d = decide(ledger)
        if d["stop"]:
            print(json.dumps({"run": run, "skipped": "stop condition holds", **d}))
            return 0
        rnd = run_round(run, ledger, a.narrate, a.passes)
    elif a.cmd == "bug":
        b = next((x for x in ledger["bugs"] if x["id"] == a.id), None)
        if not b:
            ap.error(f"no bug {a.id}")
        b["status"] = a.bug_status
        if a.link:
            b["link"] = a.link
        if a.note:
            b.setdefault("history", []).append(f"{now()} {a.bug_status}: {a.note}")
        if a.bug_status == "fixed":
            b["fixed_at"] = now()
    elif a.cmd == "attach":
        data = json.load(open(a.file, encoding="utf-8"))
        entry = {"file": os.path.relpath(os.path.abspath(a.file), os.path.abspath(run)).replace(os.sep, "/"), "attached": now()}
        if a.kind == "security":  # the count only: details stay in the private file
            entry.update(count=data.get("count", 0), counts=data.get("counts", {}))
        elif a.kind == "load":
            entry.update(summary=data.get("summary"), stats=data.get("stats", {}), profile=data.get("profile"),
                         svg=os.path.relpath(os.path.join(os.path.dirname(os.path.abspath(a.file)), "load.svg"), os.path.abspath(run)).replace(os.sep, "/"))
            if "FAIL" in json.dumps(data.get("checks", [])):
                ledger["bugs"].append({"id": f"B{len(ledger['bugs']) + 1}", "case": "LOAD-" + str(data.get("profile")), "title": "Load thresholds failed",
                                       "status": "suspected", "evidence": entry["file"], "note": data.get("summary"), "round": len(ledger["rounds"]),
                                       "verify": None, "refute": None, "link": None})
        else:
            entry.update(summary=data.get("summary"), verdict=data.get("verdict"))
        ledger[a.kind] = entry
    elif a.cmd == "gate":
        if a.close:
            for g in ledger["human_gates"]:
                if g["id"] == a.close:
                    g["open"], g["closed"] = False, now()
        elif a.open_reason:
            ledger["human_gates"].append({"id": f"G{len(ledger['human_gates']) + 1}", "reason": a.open_reason, "open": True, "opened": now()})
    d = decide(ledger)
    ledger["status"], ledger["stop_reason"] = d["status"], d["reason"]
    save(run, ledger)
    out = {"run": run, **d, "rounds": len(ledger["rounds"]), "elapsed_minutes": ledger["elapsed_minutes"],
           "last": ledger["rounds"][-1]["summary"] if ledger["rounds"] else None,
           "open_bugs": [b["id"] + ":" + b["status"] for b in ledger["bugs"] if b["status"] in OPEN_BUG]}
    print(json.dumps(out))
    return 0


if __name__ == "__main__":
    sys.exit(main())
