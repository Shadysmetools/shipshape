import json

import privacy
import report


# ---------------------------------------------------------------- privacy filter
def test_masks_emails_phones_tokens_paths():
    txt = ("mail jane.doe@acme-corp.io, call +20 100 123 4567, key ghp_" + "A" * 36 +
           " jwt eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.abcdefghijklmnop path C:\\Users\\jdoe\\Desktop\\x.txt /home/jdoe/x")
    out = privacy.mask_text(txt, deny=[])
    for leaked in ("jane.doe", "123 4567", "ghp_AAAA", "eyJhbGci", "jdoe"):
        assert leaked not in out, leaked
    assert "[email]" in out and "[phone]" in out and "[home]" in out


def test_deny_list_names_are_masked_case_insensitively():
    out = privacy.mask_text("Report for ACME Trading and acme trading staff", deny=["Acme Trading"])
    assert "acme" not in out.lower() and out.count("[name]") == 2


def test_placeholders_and_dates_are_not_flagged():
    txt = "contact test.user@example.com on 2026-01-05, version 17.0.1.2.0, phone +00 000 000 0000, ${TELEGRAM_BOT_TOKEN}"
    assert list(privacy.find(txt, [])) == []


def test_secret_assignment_is_flagged_but_env_reference_is_not():
    assert any(k == "secret_assignment" for k, *_ in privacy.find("password = hunter2hunter2", []))
    assert not list(privacy.find("password: ${DB_PASSWORD}", []))


def test_scan_reports_location_and_kind_never_the_value(tmp_path, capsys):
    f = tmp_path / "notes.md"
    f.write_text("ok line\nsecret sk-ant-" + "x" * 30 + "\nname Acme Trading\n", encoding="utf-8")
    deny = tmp_path / "deny.txt"
    deny.write_text("Acme Trading\n", encoding="utf-8")
    rc = privacy.main(["scan", "--deny", str(deny), str(tmp_path)])
    out = capsys.readouterr().out
    assert rc == 1
    assert "notes.md:2: anthropic_or_openai_key" in out and "deny-list term #0" in out
    assert "sk-ant" not in out and "Acme" not in out


# ---------------------------------------------------------------- report counter
def test_counts_and_summary():
    rows = [{"id": "A", "result": "pass", "evidence": "a.mp4"}, {"id": "B", "result": "FAIL", "evidence": "b.png"},
            {"id": "C", "result": "skip"}, {"id": "D", "result": "blocked", "note": "stop at payment"}]
    counts, _ = report.count(rows)
    assert report.summary(counts) == "1 pass / 1 fail / 1 blocked / 1 skipped (4 total)"


def test_pass_without_evidence_is_not_a_pass():
    counts, rows = report.count([{"id": "A", "result": "PASS", "evidence": ""}])
    assert counts["PASS"] == 0 and counts["BLOCKED"] == 1 and "no evidence" in rows[0]["note"]


def test_planned_cases_without_results_are_not_checked():
    counts, _ = report.count([{"id": "A", "result": "PASS", "evidence": "x"}], plan_ids=["A", "B", "C"])
    assert counts["NOT CHECKED"] == 2 and counts["TOTAL"] == 3


def test_all_green_claims_are_caught():
    assert report.has_banned_claim("Everything is all green!")
    assert report.has_banned_claim("all-green, ship it")
    assert not report.has_banned_claim("12 pass / 0 fail (12 total)")


def test_two_passes_must_agree_or_flaky():
    a = [{"id": "A", "result": "PASS", "evidence": "1.png"}, {"id": "B", "result": "PASS", "evidence": "1b.png"},
         {"id": "C", "result": "FAIL", "evidence": "1c.png"}]
    b = [{"id": "A", "result": "PASS", "evidence": "2.png"}, {"id": "B", "result": "FAIL", "evidence": "2b.png"},
         {"id": "C", "result": "FAIL", "evidence": "2c.png"}]
    rows = report.combine_passes(a, b)
    assert [r["result"] for r in rows] == ["PASS", "FLAKY", "FAIL"]
    counts, _ = report.count(rows)
    assert report.summary(counts) == "1 pass / 1 fail / 1 flaky (3 total)"


def test_cli_writes_markdown(tmp_path):
    res = tmp_path / "r.json"
    res.write_text(json.dumps([{"id": "TC-1", "title": "login", "result": "PASS", "evidence": "v.mp4"}]))
    md = tmp_path / "QA.md"
    assert report.main([str(res), "--md", str(md)]) == 0
    assert "**Result: 1 pass / 0 fail (1 total)**" in md.read_text()
