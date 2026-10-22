"""Timesheet measurement. The first test is the regression test for the bug where
unsorted transcript lines produced negative intervals and negative hours."""
import datetime as dt
import json
import os

import pytest
from openpyxl import load_workbook

import timesheet as ts

T0 = dt.datetime(2026, 1, 5, 9, 0, tzinfo=dt.timezone.utc).timestamp()


def iso(sec):
    return dt.datetime.fromtimestamp(T0 + sec, dt.timezone.utc).isoformat().replace("+00:00", "Z")


def write_jsonl(path, rows):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        for r in rows:
            fh.write(json.dumps(r) + "\n")


def line(sec, kind="assistant", text=None):
    d = {"type": kind, "timestamp": iso(sec)}
    if text is not None:
        d["message"] = {"role": "user", "content": text}
    return d


# ---------------------------------------------------------------- the sorting regression
def test_unsorted_lines_never_give_negative_hours(tmp_path):
    """Lines written out of order (resumed sessions, merged files) used to be paired
    in file order: (10 min, 2 min) gave a -8 min "interval". Sorting fixes it."""
    p = tmp_path / "s.jsonl"
    # true timeline: 0, 2, 4, 6, 8, 10 min -> 10 active minutes; written shuffled
    write_jsonl(str(p), [line(m * 60) for m in (10, 2, 0, 8, 4, 6)])
    stamps, _ = ts.read_file(str(p))
    assert stamps == sorted(stamps)
    iv = ts.file_intervals(stamps, 20 * 60)
    assert all(b > a for a, b in iv)
    _, _, total = ts.measure([stamps], 20)
    assert total == pytest.approx(10 / 60)


def test_file_intervals_sorts_defensively():
    raw = [T0 + 600, T0, T0 + 300]  # unsorted input straight into the interval builder
    iv = ts.file_intervals(raw, 1200)
    assert iv == [(T0, T0 + 300), (T0 + 300, T0 + 600)]


def test_interleaved_main_and_subagent_count_parallel_time_once():
    main = [T0 + m * 60 for m in range(0, 31, 5)]       # 09:00-09:30, every 5 min
    sub = [T0 + m * 60 for m in range(10, 41, 2)]       # 09:10-09:40 in parallel
    _, blocks, total = ts.measure([main, sub], 20)
    assert total == pytest.approx(40 / 60)               # union 09:00-09:40, not 30 + 30
    assert len(blocks) == 1


def test_queue_operation_lines_are_excluded(tmp_path):
    p = tmp_path / "q.jsonl"
    write_jsonl(str(p), [line(0), line(300)] + [line(600 + i * 300, "queue-operation") for i in range(12)])
    stamps, _ = ts.read_file(str(p))
    assert len(stamps) == 2
    assert ts.measure([stamps], 20)[2] == pytest.approx(5 / 60)


@pytest.mark.parametrize("gap,expected_min", [(10, 10), (15, 22), (20, 22)])
def test_gap_rule_is_configurable(gap, expected_min):
    stamps = [T0, T0 + 600, T0 + 600 + 12 * 60]  # a 10-min step then a 12-min step
    assert ts.measure([stamps], gap)[2] == pytest.approx(expected_min / 60)


def test_split_days_at_local_midnight():
    tz = dt.timezone(dt.timedelta(hours=3))
    start = dt.datetime(2026, 1, 5, 23, 30, tzinfo=tz).timestamp()
    parts = ts.split_days(start, start + 3600, tz)
    assert parts == [("2026-01-05", 1800), ("2026-01-06", 1800)]


def test_checks_flag_long_day_overlap_and_missing_employee():
    booked = {("2026-01-05", 1): 10.0, ("2026-01-06", 1): 2.0}
    existing = [{"date": "2026-01-05", "task_id": 1, "hours": 7.0}]
    lookup = {"employees": [{"id": 9, "name": "Someone Else", "company_id": 1}]}
    cfg = {"employee": {"id": 7, "name": "Test Developer"}}
    checks = ts.run_checks(booked, booked, 12.0, cfg, existing, lookup)
    by = {c["check"].split(" (")[0]: c["result"] for c in checks}
    assert by["No day over 16 h"] == "FAIL"
    assert by["No overlap with existing lines"] == "FAIL"
    assert by["Employee exists and is visible"] == "FAIL"
    assert by["Totals match"] == "PASS"
    assert ts.summary_line(checks).startswith("3 pass / 3 fail")


def test_checks_not_checked_without_exports():
    checks = ts.run_checks({}, {("d", 1): 1.0}, 1.0, {}, None, None)
    assert sum(c["result"] == "NOT CHECKED" for c in checks) == 2


def test_end_to_end_workbook(tmp_path):
    proj = tmp_path / "proj"
    sid = "11111111-aaaa-bbbb-cccc-000000000001"
    # main: a login-page block 09:00-09:50 and a timesheet-admin block 13:00-13:20
    main = [line(0, "user", "build the login page")] + [line(m * 60) for m in range(5, 51, 5)]
    main += [line(4 * 3600, "user", "prepare my timesheet")] + [line(4 * 3600 + m * 60) for m in range(5, 21, 5)]
    write_jsonl(str(proj / f"{sid}.jsonl"), main[::-1])  # reversed on purpose
    write_jsonl(str(proj / sid / "subagents" / "agent-1.jsonl"), [line(m * 60) for m in range(30, 71, 4)])
    tasks = {"project": {"id": 100, "name": "Demo project"}, "employee": {"id": 7, "name": "Test Developer"},
             "tasks": [{"id": 1, "name": "Login page", "match": ["login"]}], "exclude": ["timesheet"]}
    tf = tmp_path / "tasks.json"
    tf.write_text(json.dumps(tasks))
    lk = tmp_path / "lookup.json"
    lk.write_text(json.dumps({"employees": [{"id": 7, "name": "Test Developer"}]}))
    ex = tmp_path / "existing.json"
    ex.write_text("[]")
    out = tmp_path / "ts.xlsx"
    rc = ts.main(["--project-dir", str(proj), "--tasks", str(tf), "--out", str(out), "--tz", "+00:00",
                  "--gap", "20", "--lookup", str(lk), "--existing", str(ex)])
    assert rc == 0
    wb = load_workbook(out)
    assert wb.sheetnames == ["Summary", "Daily", "Sessions", "Evidence", "Method", "Checks", "Odoo Import"]
    rows = list(wb["Odoo Import"].iter_rows(min_row=2, values_only=True))
    assert len(rows) == 1 and rows[0][3] == 1 and rows[0][7] == pytest.approx(1.25)  # 70 active min -> 1.25 h grid
    for ws in wb.worksheets:  # values, not formulas (Protected View blanks formulas)
        for r in ws.iter_rows(values_only=True):
            assert not any(isinstance(v, str) and v.startswith("=") for v in r)
    checks = {r[0]: r[1] for r in wb["Checks"].iter_rows(min_row=2, values_only=True)}
    assert all(v == "PASS" for v in checks.values()), checks
    lines = json.loads((tmp_path / "ts-analytic-lines.json").read_text())
    assert lines["write_status"].startswith("NOT WRITTEN")
    assert lines["rows"][0]["unit_amount"] == pytest.approx(1.25)
