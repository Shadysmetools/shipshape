"""Workflow scripts dry-run with mocked agents; plugin manifests, hooks, agents, skills and commands are well formed."""
import json
import os
import re
import shutil
import subprocess
import sys

import pytest

from conftest import ROOT

HARNESS = os.path.join(ROOT, "tests", "workflow_harness.mjs")
node = pytest.mark.skipif(shutil.which("node") is None, reason="node not installed")


def run_wf(name, args):
    p = subprocess.run(["node", HARNESS, os.path.join(ROOT, "workflows", name), json.dumps(args)],
                       capture_output=True, text=True, timeout=60)
    assert p.returncode == 0, p.stderr
    return json.loads(p.stdout.strip().splitlines()[-1])


@node
def test_full_qa_workflow_dry_run():
    r = run_wf("full-qa.workflow.js", {"goal": "Signup works", "pluginRoot": ROOT, "plans": ["examples/demo-app/plans/signup.json"],
                                       "url": "http://127.0.0.1:8765/", "allowHosts": ["127.0.0.1"], "load": "smoke",
                                       "liveUrl": "http://127.0.0.1:8765/", "config": "examples/demo-app/qa.config.yaml"})
    assert r["ok"], r["unknownPhases"]
    assert r["phases"] == ["Review", "Automated x2", "Load", "Live regression", "Refute", "Report", "Deliver"]
    for a in ("qa-code-reviewer", "qa-security-reviewer", "qa-automation-tester", "qa-load-tester", "qa-live-regression-recorder", "qa-refuter"):
        assert "smetools-agent-kit:" + a in r["agentTypes"]
    assert r["result"]["survivingBugs"] == ["B1"]
    assert "--send" not in json.dumps(r["result"]["delivery"])


@node
def test_full_qa_workflow_skips_optional_phases():
    r = run_wf("full-qa.workflow.js", {"goal": "g", "pluginRoot": ROOT, "plans": ["p.json"]})
    assert "Load" not in r["phases"] and "Live regression" not in r["phases"]
    assert any("skipped" in m for m in r["logs"])


@node
def test_demo_and_regression_workflows_dry_run():
    d = run_wf("demo.workflow.js", {"feature": "sign-up", "pluginRoot": ROOT})
    assert d["ok"] and d["phases"] == ["Script", "Capture", "Review"]
    r = run_wf("regression-loop.workflow.js", {"pluginRoot": ROOT, "maxRounds": 3})
    assert r["ok"] and "Round" in r["phases"]


def test_plugin_and_marketplace_manifests():
    plugin = json.load(open(os.path.join(ROOT, ".claude-plugin", "plugin.json")))
    market = json.load(open(os.path.join(ROOT, ".claude-plugin", "marketplace.json")))
    assert plugin["name"] == market["plugins"][0]["name"] == "smetools-agent-kit"
    assert market["plugins"][0]["source"] == "."
    # docs (host-marketplace "Release a new version"): set version in plugin.json only, never in both
    assert plugin.get("version") and "version" not in market["plugins"][0]


def test_mcp_servers_are_pinned_and_secret_free():
    mcp = json.load(open(os.path.join(ROOT, ".mcp.json")))["mcpServers"]
    args = " ".join(mcp["playwright"]["args"] + mcp["chrome-devtools"]["args"])
    assert "@playwright/mcp@0.0.83" in args and "chrome-devtools-mcp@1.10.1" in args and "--caps=devtools" in args
    assert "@latest" not in args and not re.search(r"(?i)token|key|password", json.dumps(mcp))


def test_hooks_are_well_formed():
    hooks = json.load(open(os.path.join(ROOT, "hooks", "hooks.json")))["hooks"]
    assert set(hooks) == {"SessionStart", "Stop", "PreToolUse"}
    types = [h["type"] for group in hooks.values() for m in group for h in m["hooks"]]
    assert types.count("prompt") >= 2 and types.count("agent") >= 2 and types.count("command") >= 2
    for group in hooks.values():
        for m in group:
            for h in m["hooks"]:
                if h["type"] in ("prompt", "agent"):
                    assert "$ARGUMENTS" in h["prompt"] and '"ok"' in h["prompt"]
                if "matcher" in m:
                    re.compile(m["matcher"])


def test_commit_scan_hook_blocks_staged_secret(tmp_path):
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    (tmp_path / "a.py").write_text('TOKEN = "ghp_' + "B" * 36 + '"\n')
    subprocess.run(["git", "-C", str(tmp_path), "add", "a.py"], check=True)
    payload = json.dumps({"tool_input": {"command": "git commit -m x"}, "cwd": str(tmp_path)})
    p = subprocess.run([sys.executable, os.path.join(ROOT, "scripts", "hook_commit_scan.py")], input=payload, capture_output=True, text=True)
    assert p.returncode == 2 and "a.py:1: github_token" in p.stderr and "BBBB" not in p.stderr
    ok = subprocess.run([sys.executable, os.path.join(ROOT, "scripts", "hook_commit_scan.py")],
                        input=json.dumps({"tool_input": {"command": "git status"}}), capture_output=True, text=True)
    assert ok.returncode == 0


def _front(path):
    text = open(path, encoding="utf-8").read()
    m = re.match(r"---\n(.*?)\n---\n", text, re.S)
    assert m, path
    return dict(re.findall(r"^(\w[\w-]*): (.*)$", m.group(1), re.M)), text


@pytest.mark.parametrize("kind", ["agents", "commands", "skills"])
def test_frontmatter(kind):
    base = os.path.join(ROOT, kind)
    files = [os.path.join(base, d, "SKILL.md") for d in os.listdir(base)] if kind == "skills" else \
        [os.path.join(base, f) for f in os.listdir(base) if f.endswith(".md")]
    assert files
    for f in files:
        fm, text = _front(f)
        assert len(fm.get("description", "")) > 40, f
        if kind != "commands":
            assert fm.get("name"), f
        for ref in re.findall(r"\$\{CLAUDE_PLUGIN_ROOT\}/([\w./-]+\.(?:py|md|json|js|yaml))\b", text):
            assert os.path.exists(os.path.join(ROOT, ref)), f"{f} -> {ref}"


def _guard_hook_command():
    pre = json.load(open(os.path.join(ROOT, "hooks", "hooks.json")))["hooks"]["PreToolUse"]
    return [h["command"] for m in pre if m["matcher"] == "Bash|PowerShell|Read" for h in m["hooks"] if h["type"] == "command"][0]


@pytest.mark.skipif(shutil.which("bash") is None, reason="bash not installed")
def test_guard_hook_command_from_hooks_json_blocks(tmp_path):
    """Runs the literal hooks.json command (not just the script): a staged secret must come back as a
    deny decision, and the command must not fall through to a second interpreter."""
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    (tmp_path / "a.py").write_text('TOKEN = "ghp_' + "D" * 36 + '"\n')
    subprocess.run(["git", "-C", str(tmp_path), "add", "a.py"], check=True)
    cmd = _guard_hook_command().replace("${CLAUDE_PLUGIN_ROOT}", ROOT.replace("\\", "/"))
    payload = json.dumps({"tool_name": "Bash", "tool_input": {"command": "git commit -m x"}, "cwd": str(tmp_path)})
    p = subprocess.run(["bash", "-c", cmd], input=payload, capture_output=True, text=True, timeout=60)
    assert p.returncode == 0, p.stderr[-300:]
    assert json.loads(p.stdout)["hookSpecificOutput"]["permissionDecision"] == "deny"


@node
def test_full_qa_workflow_uses_overriding_agents_and_asks_external():
    """A team agent in a role replaces the kit agent everywhere it is dispatched; a refuter question about
    unclear behaviour goes to the matching external subagent, is recorded with qa_loop.py consult, and the
    claim is refuted again with the answer."""
    import crew
    cfg = {"agents": {"roles": {"refuter": "our-refuter", "code-reviewer": "our-reviewer"},
                      "external": [{"name": "odoo-consultant", "role": "odoo-expert", "when": "Odoo behaviour unclear",
                                    "subagent": "odoo-functional-consultant"},
                                   {"name": "analyst", "role": "ticket-analyst", "when": "criteria missing", "session": "ticket-analyst"}]}}
    crew.validate_agents(cfg)
    r = run_wf("full-qa.workflow.js", {"goal": "g", "pluginRoot": ROOT, "plans": ["p.json"],
                                       "agents": crew.roles(cfg, ROOT), "external": crew.external(cfg),
                                       "mockFailures": [{"id": "B1", "case": "TC-1", "title": "a"}, {"id": "B2", "case": "TC-2", "title": "invoice"}]})
    assert r["ok"], r["unknownPhases"]
    types = r["agentTypes"]
    assert "our-refuter" in types and "our-reviewer" in types and "odoo-functional-consultant" in types
    assert "smetools-agent-kit:qa-refuter" not in types and "smetools-agent-kit:qa-code-reviewer" not in types
    assert "smetools-agent-kit:qa-automation-tester" in types          # roles not overridden keep the kit agent
    ask = [c for c in r["calls"] if c["agentType"] == "odoo-functional-consultant"]
    assert len(ask) == 1 and "B2" in ask[0]["label"] and "qa_loop.py\" consult" in ask[0]["prompt"] and "--id B2" in ask[0]["prompt"]
    assert any(c["label"] == "refute B2 again" for c in r["calls"])
    assert sorted(r["result"]["survivingBugs"]) == ["B1", "B2"] and r["result"]["openQuestions"] == []


@node
def test_full_qa_workflow_returns_questions_it_cannot_ask():
    r = run_wf("full-qa.workflow.js", {"goal": "g", "pluginRoot": ROOT, "plans": ["p.json"],
                                       "external": [{"name": "analyst", "role": "odoo-expert", "when": "w", "via": "session", "to": "ticket-analyst"}],
                                       "mockFailures": [{"id": "B2", "case": "TC-2", "title": "invoice"}]})
    q = r["result"]["openQuestions"]
    assert q == [{"bug": "B2", "question": "Should a draft invoice be editable?", "ask": "analyst via session ticket-analyst"}]
    assert r["result"]["survivingBugs"] == []
    assert any("question(s) for the QA lead" in m for m in r["logs"])
