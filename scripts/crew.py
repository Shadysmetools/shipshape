#!/usr/bin/env python3
"""Crew roles and external agents, read from qa.config.yaml (section `agents`).

The QA lead never hard-codes an agent file. It asks for a ROLE ("the Odoo expert role") and this
script says which agent fills it, so a team can put its own agent in a role without forking the plugin.

    python scripts/crew.py roles    [--config qa.config.yaml] [--project .]   # role -> agent, as JSON
    python scripts/crew.py resolve  <role> [--config ...] [--project .]        # one agent name
    python scripts/crew.py external [--config ...] [--role odoo-expert]        # registered external agents, as JSON
    python scripts/crew.py ask      <name> --question "..." [--config ...] [--timeout 300]
                                                     # command transport only: runs it, prints the answer

Resolution order for a role (first hit wins):
  1. `agents.roles.<role>` in qa.config.yaml (a team agent name, e.g. odoo-functional-consultant)
  2. a project agent in .claude/agents/ whose frontmatter `name` equals the kit's agent name
     (e.g. your own .claude/agents/odoo-expert.md)
  3. the kit's agent, plugin-scoped: smetools-agent-kit:<agent>

External agents (`agents.external`): each entry has `name`, `role`, `when` and exactly one way to
reach it: `subagent: <agent name>`, `session: <Claude Code session name>` (SendMessage) or
`command: <argv list or string>` (the question goes in on stdin, the answer comes back on stdout).
No secrets in this section: a command reads its own credentials on its own machine.
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import re
import shlex
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
PLUGIN = "smetools-agent-kit"
# role -> the kit agent that fills it by default (file agents/<name>.md)
DEFAULT_ROLES = {
    "code-reviewer": "qa-code-reviewer",
    "security-reviewer": "qa-security-reviewer",
    "automation-tester": "qa-automation-tester",
    "load-tester": "qa-load-tester",
    "live-regression": "qa-live-regression-recorder",
    "desktop-tester": "qa-desktop-tester",
    "demo-video": "qa-demo-video-producer",
    "refuter": "qa-refuter",
    "odoo-expert": "odoo-expert",
    "timesheet": "timesheet-agent",
}
TRANSPORTS = ("subagent", "session", "command")
NAME_RE = re.compile(r"^[A-Za-z0-9][\w.-]*(:[\w.-]+)*$")


class ConfigError(Exception):
    """The agents section is unusable; the message is one readable line."""


def validate_agents(cfg):
    """Check `agents.roles` and `agents.external`. Returns the agents section (a dict, maybe empty)."""
    sec = (cfg or {}).get("agents") or {}
    if not isinstance(sec, dict):
        raise ConfigError("config error at agents: expected a mapping with roles and/or external")
    roles = sec.get("roles") or {}
    if not isinstance(roles, dict):
        raise ConfigError("config error at agents.roles: expected a mapping of role: agent-name")
    for role, name in roles.items():
        if role not in DEFAULT_ROLES:
            raise ConfigError(f"config error at agents.roles.{role}: unknown role (known: {', '.join(DEFAULT_ROLES)})")
        if not isinstance(name, str) or not NAME_RE.match(name):
            raise ConfigError(f"config error at agents.roles.{role}: expected an agent name, got {name!r}")
    ext = sec.get("external") or []
    if not isinstance(ext, list):
        raise ConfigError("config error at agents.external: expected a list of agents")
    seen = set()
    for i, e in enumerate(ext):
        at = f"agents.external[{i}]"
        if not isinstance(e, dict):
            raise ConfigError(f"config error at {at}: expected a mapping (name, role, when, and subagent|session|command)")
        for field in ("name", "role", "when"):
            if not isinstance(e.get(field), str) or not e[field].strip():
                raise ConfigError(f"config error at {at}.{field}: required text")
        if e["name"] in seen:
            raise ConfigError(f"config error at {at}.name: duplicate name {e['name']!r}")
        seen.add(e["name"])
        ways = [t for t in TRANSPORTS if t in e]
        if len(ways) != 1:
            raise ConfigError(f"config error at {at}: give exactly one of subagent, session or command (got {ways or 'none'})")
        val = e[ways[0]]
        if ways[0] == "command":
            if not (isinstance(val, str) and val.strip()) and not (isinstance(val, list) and val and all(isinstance(x, str) for x in val)):
                raise ConfigError(f"config error at {at}.command: expected a command line or a list of arguments")
        elif not isinstance(val, str) or not NAME_RE.match(val):
            raise ConfigError(f"config error at {at}.{ways[0]}: expected a name, got {val!r}")
    return sec


def load(path):
    """Read qa.config.yaml (missing file = empty config) and validate the agents section."""
    if not path or not os.path.isfile(path):
        return {}
    sys.path.insert(0, HERE)
    import notify  # same loader as delivery: BOM-tolerant, one-line errors
    try:
        cfg = notify.load_config(path)
    except notify.ConfigError as exc:
        raise ConfigError(str(exc)) from None
    validate_agents(cfg)
    return cfg


def project_agents(project="."):
    """Frontmatter names of the project's own agents (.claude/agents/**/*.md)."""
    names = set()
    for f in glob.glob(os.path.join(project, ".claude", "agents", "**", "*.md"), recursive=True):
        try:
            text = open(f, encoding="utf-8-sig").read()
        except OSError:
            continue
        m = re.match(r"---\r?\n(.*?)\r?\n---", text, re.S)
        fm = re.search(r"^name:\s*['\"]?([^'\"\r\n]+?)['\"]?\s*$", m.group(1), re.M) if m else None
        names.add(fm.group(1) if fm else os.path.splitext(os.path.basename(f))[0])
    return names


def resolve(role, cfg=None, project="."):
    """The agent that fills `role`: config map, then a same-name project agent, then the kit's own."""
    if role not in DEFAULT_ROLES:
        raise KeyError(f"unknown role {role!r} (known: {', '.join(DEFAULT_ROLES)})")
    mapped = ((cfg or {}).get("agents") or {}).get("roles") or {}
    if mapped.get(role):
        return mapped[role]
    kit = DEFAULT_ROLES[role]
    return kit if kit in project_agents(project) else f"{PLUGIN}:{kit}"


def roles(cfg=None, project="."):
    return {r: resolve(r, cfg, project) for r in DEFAULT_ROLES}


def external(cfg=None, role=None):
    """Registered external agents, each with `via` (subagent|session|command) and `to` (where)."""
    out = []
    for e in ((cfg or {}).get("agents") or {}).get("external") or []:
        if role and e["role"] != role:
            continue
        via = next(t for t in TRANSPORTS if t in e)
        out.append({"name": e["name"], "role": e["role"], "when": e["when"], "via": via, "to": e[via]})
    return out


def ask_command(entry, question, timeout=300):
    """Run a `command` external agent: question on stdin, answer from stdout. Never through a shell."""
    cmd = entry["to"] if isinstance(entry["to"], list) else shlex.split(entry["to"], posix=os.name != "nt")
    p = subprocess.run(cmd, input=question, capture_output=True, text=True, timeout=timeout, encoding="utf-8", errors="replace")
    if p.returncode != 0:
        raise RuntimeError(f"{entry['name']} exited {p.returncode}: {(p.stderr or '').strip()[-300:]}")
    return (p.stdout or "").strip()


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("cmd", choices=("roles", "resolve", "external", "ask"))
    ap.add_argument("target", nargs="?", help="role (resolve) or external agent name (ask)")
    ap.add_argument("--config", default="qa.config.yaml")
    ap.add_argument("--project", default=".")
    ap.add_argument("--role")
    ap.add_argument("--question")
    ap.add_argument("--timeout", type=int, default=300)
    a = ap.parse_args(argv)
    try:
        cfg = load(a.config)
    except ConfigError as exc:
        print(str(exc))
        return 2
    if a.cmd == "roles":
        print(json.dumps(roles(cfg, a.project)))
    elif a.cmd == "resolve":
        try:
            print(resolve(a.target or "", cfg, a.project))
        except KeyError as exc:
            print(exc.args[0])
            return 2
    elif a.cmd == "external":
        print(json.dumps(external(cfg, a.role)))
    else:
        e = next((x for x in external(cfg) if x["name"] == a.target), None)
        if not e:
            print(f"no external agent {a.target!r} in {a.config}")
            return 2
        if e["via"] != "command":
            print(f"{e['name']} is reached by {e['via']} ({e['to']}): ask it from the session, not this script")
            return 2
        if not a.question:
            ap.error("ask needs --question")
        try:
            print(ask_command(e, a.question, a.timeout))
        except (RuntimeError, OSError, subprocess.TimeoutExpired) as exc:
            print(f"ask failed: {exc}")
            return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
