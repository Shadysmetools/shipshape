#!/usr/bin/env python3
"""Honest QA counts: "N pass / M fail / K blocked / S skipped" from the full list.

    python scripts/report.py results.json [--md QA-REPORT.md] [--title "Round 3"]

results.json is a list of {"id", "title", "result", "evidence", "note"}.
result is one of PASS, FAIL, FLAKY, BLOCKED, SKIPPED, NOT CHECKED (case-insensitive).
FLAKY = two independent passes disagreed (see combine_passes).

Rules enforced here (the Stop hook enforces the same in conversation):
- A PASS without evidence (video, screenshot, log path or link) is counted as
  BLOCKED "no evidence". A claim with no evidence is not a result.
- Every case in the plan is counted; a missing result is NOT CHECKED, never
  silently dropped.
- The summary never says "all green"; it always gives the counts.
Exit code: 0 when nothing failed or is blocked, 1 otherwise.
"""
from __future__ import annotations

import argparse
import json
import re
import sys

ORDER = ("PASS", "FAIL", "FLAKY", "BLOCKED", "SKIPPED", "NOT CHECKED")
ALIASES = {"OK": "PASS", "PASSED": "PASS", "FAILED": "FAIL", "ERROR": "FAIL", "SKIP": "SKIPPED",
           "NOT_CHECKED": "NOT CHECKED", "UNTESTED": "NOT CHECKED", "": "NOT CHECKED"}
BANNED = re.compile(r"(?i)\ball[ -]?green\b|\ball tests pass(?:ed)?\b(?![^.]*\d)|\beverything (?:works|passes)\b")


def normalise(result):
    r = (result or "").strip().upper()
    r = ALIASES.get(r, r)
    return r if r in ORDER else "NOT CHECKED"


def count(results, plan_ids=None):
    """Return (counts dict, normalised rows). plan_ids adds NOT CHECKED rows for
    planned cases with no result."""
    rows = []
    seen = set()
    for r in results:
        res = normalise(r.get("result"))
        note = r.get("note", "")
        if res == "PASS" and not (r.get("evidence") or "").strip():
            res, note = "BLOCKED", (note + "; " if note else "") + "no evidence attached to the PASS"
        rows.append({**r, "result": res, "note": note})
        seen.add(r.get("id"))
    for pid in plan_ids or []:
        if pid not in seen:
            rows.append({"id": pid, "title": "", "result": "NOT CHECKED", "evidence": "", "note": "in the plan, no result"})
    counts = {k: sum(1 for r in rows if r["result"] == k) for k in ORDER}
    counts["TOTAL"] = len(rows)
    return counts, rows


def combine_passes(first, second):
    """Every scenario runs twice. A result counts only if both passes agree;
    otherwise it is FLAKY. Returns the combined rows."""
    b = {r["id"]: r for r in second}
    out = []
    for r in first:
        o = b.get(r["id"])
        r1, r2 = normalise(r.get("result")), normalise(o.get("result")) if o else "NOT CHECKED"
        if r1 == r2:
            out.append({**r, "result": r1, "note": r.get("note", "")})
        else:
            out.append({**r, "result": "FLAKY", "note": f"pass 1 {r1}, pass 2 {r2}",
                        "evidence": " + ".join(x for x in (r.get("evidence"), (o or {}).get("evidence")) if x)})
    seen = {r["id"] for r in first}
    out += [{**r, "result": "FLAKY", "note": f"only in pass 2 ({normalise(r.get('result'))})"} for r in second if r["id"] not in seen]
    return out


def summary(counts):
    s = f"{counts['PASS']} pass / {counts['FAIL']} fail"
    extra = [f"{counts[k]} {k.lower()}" for k in ("FLAKY", "BLOCKED", "SKIPPED", "NOT CHECKED") if counts[k]]
    if extra:
        s += " / " + " / ".join(extra)
    return s + f" ({counts['TOTAL']} total)"


def has_banned_claim(text):
    """True when a status text claims success without counts ("all green")."""
    return bool(BANNED.search(text or ""))


def to_markdown(rows, counts, title="QA report"):
    out = [f"# {title}", "", f"**Result: {summary(counts)}**", "",
           "| ID | Case | Result | Evidence | Note |", "|---|---|---|---|---|"]
    for r in rows:
        cell = lambda v: str(v or "").replace("|", "\\|").replace("\n", " ")  # noqa: E731
        out.append(f"| {cell(r.get('id'))} | {cell(r.get('title'))} | {r['result']} | {cell(r.get('evidence'))} | {cell(r.get('note'))} |")
    return "\n".join(out) + "\n"


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("results")
    ap.add_argument("--plan", help="JSON list of case ids in the plan (missing ones count as NOT CHECKED)")
    ap.add_argument("--md", help="write a markdown report here")
    ap.add_argument("--title", default="QA report")
    a = ap.parse_args(argv)
    results = json.load(open(a.results, encoding="utf-8"))
    if isinstance(results, dict):  # a results.json written by record.py
        if not results.get("finished_at"):
            print("REFUSED: this run has not finished; counts are only reported from a finished run")
            return 2
        results = results.get("results", [])
    plan = json.load(open(a.plan, encoding="utf-8")) if a.plan else None
    counts, rows = count(results, plan)
    if a.md:
        open(a.md, "w", encoding="utf-8").write(to_markdown(rows, counts, a.title))
    print(summary(counts))
    return 0 if counts["FAIL"] == 0 and counts["BLOCKED"] == 0 and counts["FLAKY"] == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
