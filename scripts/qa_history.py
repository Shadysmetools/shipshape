#!/usr/bin/env python3
"""Read old QA runs (qa-runs/*/ledger.json) before starting new work.

    python scripts/qa_history.py [--root qa-runs] [--json history.json]

Prints, from the ledgers alone (no guessing):
- the trend: "N pass / M fail" per round, oldest first;
- flaky cases: cases that flipped between PASS and FAIL at least twice;
- regressions to re-check: cases that failed once and passed later;
- past bugs and their last status;
- the baseline: the newest round's counts and duration.
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import report  # noqa: E402


def load_runs(root):
    runs = []
    for p in glob.glob(os.path.join(root, "*", "ledger.json")):
        try:
            with open(p, encoding="utf-8") as fh:
                led = json.load(fh)
        except (OSError, ValueError):
            continue
        led["_dir"] = os.path.basename(os.path.dirname(p))
        runs.append(led)
    return sorted(runs, key=lambda r: r.get("created", ""))


def history(runs):
    trend, seq, bugs = [], {}, []
    for led in runs:
        for rnd in led.get("rounds", []):
            c = rnd.get("counts", {})
            trend.append({"run": led["_dir"], "goal": led.get("goal"), "round": rnd.get("n"), "finished": rnd.get("finished"),
                          "pass": c.get("PASS", 0), "fail": c.get("FAIL", 0), "blocked": c.get("BLOCKED", 0),
                          "total": c.get("TOTAL", 0), "minutes": rnd.get("minutes"), "summary": rnd.get("summary")})
            for run in rnd.get("runs", []):
                for r in run.get("results", []):
                    seq.setdefault(r["id"], []).append(r["result"])
        for b in led.get("bugs", []):
            bugs.append({"run": led["_dir"], **{k: b.get(k) for k in ("id", "case", "title", "status", "link")}})
    flaky, regress = [], []
    for case, res in sorted(seq.items()):
        pf = [x for x in res if x in ("PASS", "FAIL")]
        flips = sum(1 for a, b in zip(pf, pf[1:]) if a != b)
        if flips >= 2:
            flaky.append({"case": case, "flips": flips, "history": "".join("P" if x == "PASS" else "F" for x in pf)})
        if "FAIL" in pf and pf and pf[-1] == "PASS":
            regress.append(case)
    baseline = trend[-1] if trend else None
    return {"trend": trend, "flaky": flaky, "recheck": regress, "bugs": bugs, "baseline": baseline}


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--root", default="qa-runs")
    ap.add_argument("--json")
    a = ap.parse_args(argv)
    h = history(load_runs(a.root))
    if a.json:
        json.dump(h, open(a.json, "w", encoding="utf-8"), indent=1)
    if not h["trend"]:
        print(f"no previous runs under {a.root}")
        return 0
    print("Trend (oldest first):")
    for t in h["trend"]:
        print(f"  {t['run']} r{t['round']}: {t['summary']}")
    print("Flaky cases:", ", ".join(f"{f['case']} ({f['history']})" for f in h["flaky"]) or "none")
    print("Re-check (failed before, passing now):", ", ".join(h["recheck"]) or "none")
    open_b = [b for b in h["bugs"] if b["status"] in ("suspected", "verified", "filed", "fixed")]
    print("Open bugs from earlier runs:", ", ".join(f"{b['id']} {b['case']} [{b['status']}]" for b in open_b) or "none")
    print("Baseline:", h["baseline"]["summary"], f"in {h['baseline']['minutes']} min")
    return 0


if __name__ == "__main__":
    sys.exit(main())
