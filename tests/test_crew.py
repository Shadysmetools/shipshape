"""Crew roles (a team's own agent fills a kit role) and external agents (asked, answer kept in the ledger)."""
import json
import os
import sys

import pytest

import crew
import qa_loop
import qa_report_html
from conftest import ROOT

TEMPLATE = os.path.join(ROOT, "templates", "qa.config.example.yaml")


def test_template_parses_and_maps_roles(tmp_path):
    cfg = crew.load(TEMPLATE)
    r = crew.roles(cfg, str(tmp_path))
    assert set(r) == set(crew.DEFAULT_ROLES)
    assert r["odoo-expert"] == "odoo-functional-consultant"          # the override from the template
    assert r["refuter"] == "smetools-agent-kit:qa-refuter"            # unlisted roles keep the kit agent
    ext = {e["name"]: e for e in crew.external(cfg)}
    assert {e["via"] for e in ext.values()} == {"subagent", "session", "command"}
    assert ext["odoo-consultant"] == {"name": "odoo-consultant", "role": "odoo-expert", "via": "subagent",
                                      "to": "odoo-functional-consultant", "when": ext["odoo-consultant"]["when"]}
    assert [e["name"] for e in crew.external(cfg, role="odoo-expert")] == ["odoo-consultant"]


def test_every_default_role_names_a_real_kit_agent():
    agents = {f[:-3] for f in os.listdir(os.path.join(ROOT, "agents")) if f.endswith(".md")}
    assert set(crew.DEFAULT_ROLES.values()) <= agents


def test_same_name_project_agent_overrides_kit_agent(tmp_path):
    assert crew.resolve("odoo-expert", {}, str(tmp_path)) == "smetools-agent-kit:odoo-expert"
    d = tmp_path / ".claude" / "agents"
    d.mkdir(parents=True)
    (d / "our-odoo.md").write_text("---\nname: odoo-expert\ndescription: our own\n---\nbody\n", encoding="utf-8")
    assert crew.resolve("odoo-expert", {}, str(tmp_path)) == "odoo-expert"
    assert crew.resolve("refuter", {}, str(tmp_path)) == "smetools-agent-kit:qa-refuter"
    # an explicit role map wins over the same-name file
    assert crew.resolve("odoo-expert", {"agents": {"roles": {"odoo-expert": "odoo-functional-consultant"}}}, str(tmp_path)) == "odoo-functional-consultant"


def test_no_config_means_kit_defaults(tmp_path):
    assert crew.load(str(tmp_path / "missing.yaml")) == {}
    assert crew.roles({}, str(tmp_path))["code-reviewer"] == "smetools-agent-kit:qa-code-reviewer"
    assert crew.external({}) == []


@pytest.mark.parametrize("agents,where", [
    ({"roles": {"odoo-guru": "x"}}, "agents.roles.odoo-guru"),
    ({"roles": {"odoo-expert": "bad name!"}}, "agents.roles.odoo-expert"),
    ({"external": [{"name": "a", "role": "r", "when": "w"}]}, "agents.external[0]: give exactly one"),
    ({"external": [{"name": "a", "role": "r", "when": "w", "subagent": "x", "session": "y"}]}, "agents.external[0]: give exactly one"),
    ({"external": [{"name": "a", "role": "r", "subagent": "x"}]}, "agents.external[0].when"),
    ({"external": [{"name": "a", "role": "r", "when": "w", "command": []}]}, "agents.external[0].command"),
    ({"external": [{"name": "a", "role": "r", "when": "w", "subagent": "x"}, {"name": "a", "role": "r", "when": "w", "session": "y"}]}, "duplicate"),
    ({"external": {"name": "a"}}, "agents.external: expected a list"),
])
def test_bad_agents_section_gives_one_readable_line(agents, where):
    with pytest.raises(crew.ConfigError) as exc:
        crew.validate_agents({"agents": agents})
    assert where in str(exc.value)


def test_cli_reports_config_error_without_traceback(tmp_path, capsys):
    cfg = tmp_path / "qa.config.yaml"
    cfg.write_text("agents:\n  roles:\n    nobody: x\n", encoding="utf-8")
    assert crew.main(["roles", "--config", str(cfg)]) == 2
    assert capsys.readouterr().out.startswith("config error at agents.roles.nobody")


def test_ask_command_transport_uses_stdin_and_stdout(tmp_path, capsys):
    script = tmp_path / "answer.py"
    script.write_text("import sys; print('expected: ' + sys.stdin.read().strip().upper())\n", encoding="utf-8")
    cfg = tmp_path / "qa.config.yaml"
    cfg.write_text(json.dumps({"agents": {"external": [
        {"name": "dev", "role": "developer", "when": "intent unclear", "command": [sys.executable, str(script)]},
        {"name": "analyst", "role": "ticket-analyst", "when": "criteria missing", "session": "ticket-analyst"}]}}), encoding="utf-8")
    cfg_yaml = tmp_path / "qa.config.yml"
    cfg_yaml.write_text(cfg.read_text(encoding="utf-8"), encoding="utf-8")  # JSON is valid YAML
    assert crew.main(["ask", "dev", "--question", "is it red?", "--config", str(cfg_yaml)]) == 0
    assert capsys.readouterr().out.strip() == "expected: IS IT RED?"
    assert crew.main(["ask", "analyst", "--question", "q", "--config", str(cfg_yaml)]) == 2
    assert "reached by session" in capsys.readouterr().out


def test_consult_is_recorded_in_ledger_bug_history_and_report(tmp_path, capsys):
    led = qa_loop.new_ledger("goal", ["p.json"])
    qa_loop.absorb_round(led, [{"plan": "p.json", "dir": "r/p/pass-1", "results": [
        {"id": "TC-1", "title": "invoice", "result": "FAIL", "evidence": "a.png", "note": "editable"}]}], "t", "t", 1.0)
    run = tmp_path / "run"
    run.mkdir()
    qa_loop.save(str(run), led)
    rc = qa_loop.main(["consult", "--run", str(run), "--agent", "odoo-consultant", "--via", "subagent", "--id", "B1",
                       "--by", "qa-refuter", "--question", "Is a posted invoice editable?", "--answer", "No, it is locked."])
    assert rc == 0 and json.loads(capsys.readouterr().out)["consults"] == 1
    saved = qa_loop.load(str(run))
    c = saved["consults"][0]
    assert (c["id"], c["agent"], c["via"], c["bug"], c["by"]) == ("Q1", "odoo-consultant", "subagent", "B1", "qa-refuter")
    assert c["answer"] == "No, it is locked." and c["at"]
    assert "asked odoo-consultant (Q1)" in saved["bugs"][0]["history"][0]
    assert qa_loop.decide(saved)["next"] == "verify-refute"   # an answer is not a verdict
    html = open(qa_report_html.build(str(run), str(tmp_path)), encoding="utf-8").read()
    assert "Questions asked to other agents" in html and "Is a posted invoice editable?" in html and "odoo-consultant (B1)" in html


def test_consult_works_on_an_old_ledger_and_rejects_unknown_bug():
    led = qa_loop.new_ledger("goal", ["p.json"])
    del led["consults"]                                       # ledgers written before this release
    assert qa_loop.add_consult(led, "a", "q", "ans")["id"] == "Q1"
    with pytest.raises(KeyError):
        qa_loop.add_consult(led, "a", "q", "ans", bug="B9")
