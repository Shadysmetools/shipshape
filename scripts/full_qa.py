#!/usr/bin/env python3
"""`qa` in one command: the script layer of the full QA pipeline.

    python scripts/full_qa.py "<goal>" --plan plans/signup.json [--plan ...] [--config qa.config.yaml]
                               [--url http://127.0.0.1:8000/ --allow-host 127.0.0.1] [--load smoke|ramp|soak|spike]
                               [--narrate] [--lang en|ar] [--send] [--max-rounds 3] [--root qa-runs]

Steps (each with a timeout; the ledger makes it resumable):
  1. history   read old runs: trend, flaky cases, open bugs, baseline
  2. start     open (or resume) qa-runs/<date>-<goal>/ledger.json
  3. security  secret sweep + dependency audit + passive header check (allow-listed url only); count goes in the ledger
  4. rounds    every plan twice (FLAKY if the passes disagree), recorded + narrated, until a stop condition
               or until a step needs judgement (verify-refute, file-bugs, wait-fix): that is the agents' job
  5. load      optional load profile on the allow-listed url
  6. report    self-contained report.html (+ spoken summary with --narrate)
  7. deliver   notify.py, DRY-RUN unless --send
The agent layer (code review, refuter, bug filing, demo video) is in the
workflows/ and agents/ folders; /qa-goal drives both.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import qa_history  # noqa: E402
import qa_loop  # noqa: E402


def step(title):
    print(f"\n== {title}", flush=True)


def py(script, *args, timeout=1800):
    cmd = [sys.executable, os.path.join(HERE, script), *args]
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, encoding="utf-8", errors="replace")
        out = (p.stdout or "").strip()
        if out:
            print(out[-2000:])
        if p.returncode not in (0, 1):
            print((p.stderr or "")[-800:])
        return p.returncode
    except subprocess.TimeoutExpired:
        print(f"TIMEOUT after {timeout}s: {script}")
        return 124


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("goal")
    ap.add_argument("--plan", action="append", required=True)
    ap.add_argument("--root", default="qa-runs")
    ap.add_argument("--config")
    ap.add_argument("--url")
    ap.add_argument("--allow-host", action="append", default=[])
    ap.add_argument("--load", choices=("smoke", "ramp", "soak", "spike"))
    ap.add_argument("--load-scale", default="1.0")
    ap.add_argument("--repo", default=".")
    ap.add_argument("--narrate", action="store_true")
    ap.add_argument("--lang", default="en", choices=("en", "ar"))
    ap.add_argument("--send", action="store_true")
    ap.add_argument("--max-rounds", type=int, default=3)
    ap.add_argument("--passes", type=int, default=2, choices=(1, 2))
    ap.add_argument("--skip-security", action="store_true")
    a = ap.parse_args(argv)
    sys.stdout.reconfigure(encoding="utf-8")

    print("ShipShape - your autonomous QA crew | goal:", a.goal)
    step("1/7 history: what earlier runs say")
    h = qa_history.history(qa_history.load_runs(a.root))
    if h["trend"]:
        print("baseline:", h["baseline"]["summary"], "| flaky:", ", ".join(f["case"] for f in h["flaky"]) or "none",
              "| re-check:", ", ".join(h["recheck"]) or "none")
    else:
        print("no earlier runs")

    step("2/7 start or resume the ledger")
    qa_loop.main(["start", "--root", a.root, "--goal", a.goal, "--max-rounds", str(a.max_rounds),
                  *sum((["--plan", p] for p in a.plan), [])])
    import datetime as dt
    run = os.path.join(a.root, f"{dt.date.today().isoformat()}-{qa_loop.slug(a.goal)}")

    if not a.skip_security:
        step("3/7 security (read-only; details stay private)")
        sec_dir = os.path.join(run, "security")
        args = ["--repo", a.repo, "--out", sec_dir]
        if a.url:
            args += ["--url", a.url, *sum((["--allow-host", x] for x in a.allow_host), [])]
        py("security_scan.py", *args, timeout=900)
        if os.path.exists(os.path.join(sec_dir, "security.json")):
            qa_loop.main(["attach", "--run", run, "--kind", "security", "--file", os.path.join(sec_dir, "security.json")])

    step("4/7 rounds: every plan twice, recorded")
    while True:
        d = qa_loop.decide(qa_loop.load(run))
        if d["stop"] or d["next"] != "run-round":
            print("loop pauses:", d["reason"] or f"next step is '{d['next']}' (agents: verify/refute, file, wait for fix)")
            break
        args = ["round", "--run", run, "--passes", str(a.passes)] + (["--narrate"] if a.narrate else [])
        qa_loop.main(args)

    if a.load and a.url:
        step(f"5/7 load ({a.load})")
        ld = os.path.join(run, "load")
        py("load_test.py", "--url", a.url, "--profile", a.load, "--scale", a.load_scale, "--out", ld,
           *sum((["--allow-host", x] for x in a.allow_host), []), timeout=3600)
        if os.path.exists(os.path.join(ld, "load.json")):
            qa_loop.main(["attach", "--run", run, "--kind", "load", "--file", os.path.join(ld, "load.json")])
            qa_loop.main(["status", "--run", run])

    step("6/7 report")
    py("qa_report_html.py", run, "--root", a.root, timeout=600)
    if a.narrate:
        py("narrator.py", "report", run, "--lang", a.lang, timeout=600)

    step("7/7 deliver" + ("" if a.send else " (dry-run)"))
    if a.config and os.path.exists(a.config):
        py("notify.py", run, "--config", a.config, "--lang", a.lang, *(["--send"] if a.send else []), timeout=2400)
    else:
        print("no qa.config.yaml: nothing to deliver (see templates/qa.config.example.yaml)")

    led = qa_loop.load(run)
    last = led["rounds"][-1]["summary"] if led["rounds"] else "no rounds"
    print(f"\nRESULT: {last} | status: {led['status']} | {led.get('stop_reason') or qa_loop.decide(led)['next']}")
    print(f"report: {os.path.join(run, 'report.html')}")
    json.dump({"run": run, "summary": last, "status": led["status"]}, open(os.path.join(run, "last.json"), "w"))
    return 0 if led["status"] == "met" else 1


if __name__ == "__main__":
    sys.exit(main())
