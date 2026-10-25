#!/usr/bin/env python3
"""One deterministic PreToolUse hook for the Bash, PowerShell and Read tools.
No model call: it reads the hook input on stdin, classifies the action and answers.

  deny  reading or printing secret files (.env, secrets/, *.pem, *.key, ~/.ssh, credential stores),
        commands that carry a literal key/token, force-pushes and pushes to main/master/production,
        and commits whose staged diff adds secrets or personal data (hook_commit_scan)
  ask   actions that need the owner's own click: merges (git merge, gh pr merge), deletes of
        branches/remote refs/files outside tmp or run folders, `notify.py --send` (after a
        deterministic config check), `desktop.py run` without --dry-run (after the desktop gate),
        `odoo_ticket.py post|move --send` (a move to the on_pass/on_fail stage is allowed only
        when the project config sets auto_move: true)

Exit 0 with a JSON decision on stdout; "ask" routes the call to the real user's permission prompt,
so a relayed "they approved" can never stand in for the owner's own words.
"""
from __future__ import annotations

import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

SECRET_PATH = re.compile(r"(?i)(?:^|[\s/\\\"'])(?:\.env(?:\.[\w-]+)?|[\w.-]*secrets?[/\\][\w./\\-]*|[\w./\\-]+\.(?:pem|key|p12|pfx)|"
                         r"~?[/\\]?\.ssh[/\\][\w.-]*|[\w./\\-]*(?:credentials|token|auth)\.json|[\w./\\-]*\.claude\.json|[\w./\\-]*Cookies)(?=$|[\s\"'|;&)])")
SECRET_LITERAL = re.compile(r"\b(?:gh[pousr]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,}|sk-(?:ant-)?[A-Za-z0-9_-]{20,}|xox[abprs]-[A-Za-z0-9-]{10,}|"
                            r"AKIA[A-Z0-9]{16}|AIza[0-9A-Za-z_-]{30,}|\d{8,10}:[A-Za-z0-9_-]{35}|eyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,})")
READERS = re.compile(r"(?i)(?:^|[\s|;&(])(?:cat|type|less|more|head|tail|Get-Content|gc|strings|bat|xxd|hexdump|grep|rg|findstr|Select-String)\b")
# ShipShape's own key store (scripts/keys.py): any mention next to a reader or open() is blocked, globs included
KEY_STORE = re.compile(r"(?i)keys\.json|SMEKIT_KEYS_DIR|shipshape.secrets")
OPENS = re.compile(r"(?i)\bopen\s*\(|read_text\s*\(|ReadAllText")
EXAMPLE = re.compile(r"(?i)\.env\.(?:example|sample|template)|templates?[/\\]|placeholder")
TMP_DIRS = re.compile(r"(?i)(?:^|[\s\"'])(?:\./|\.\\)?(?:tmp|temp|qa-runs|qa-evidence|build|dist|node_modules|__pycache__|\.pytest_cache)(?:[/\\][^\s\"']*)?(?=$|[\s\"'])")


def decide(decision, reason):
    out = {"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": decision, "permissionDecisionReason": reason}}
    sys.stdout.write(json.dumps(out))
    return 0


def classify_command(cmd, cwd):
    """Return (decision, reason) for a shell command, or None to allow."""
    if SECRET_LITERAL.search(cmd):
        return "deny", "The command contains a literal key or token. Secrets reach scripts only as environment variables."
    if KEY_STORE.search(cmd) and (READERS.search(cmd) or OPENS.search(cmd)):
        return "deny", "Reading ShipShape's key store is blocked. Use: python scripts/keys.py list|check (names only)."
    if READERS.search(cmd) and SECRET_PATH.search(cmd) and not EXAMPLE.search(cmd):
        return "deny", "Reading or printing a secrets file is blocked. Read it in code and print booleans or field names only."
    if re.search(r"\bgit\b[^|;&]*\bpush\b", cmd):
        if re.search(r"\s(?:--force(?:-with-lease)?|-f)\b|\s\+[\w/-]+", cmd):
            return "deny", "Force-pushes are blocked. Fix forward, or ask the owner to do it by hand."
        if re.search(r"\bpush\b[^|;&]*\s(?:[\w.-]+\s+)?(?:[\w/-]+:)?(?:main|master|prod|production|release)\b", cmd) and not re.search(r"--delete", cmd):
            return "deny", "Pushing to main/master/production is blocked. Push a feature branch and open a PR."
        if re.search(r"--delete|:\s*$|\s:[\w/-]+", cmd):
            return "ask", "Deleting a remote branch needs the owner's own OK."
    if re.search(r"\bgit\b[^|;&]*\bcommit\b", cmd):
        import hook_commit_scan
        hits = hook_commit_scan.staged_hits(cwd, hook_commit_scan.privacy.load_denylist())
        if hits:
            return "deny", "Commit blocked: staged changes add possible secrets or personal data: " + "; ".join(hits[:10])
    if re.search(r"\bgit\b[^|;&]*\bmerge\b|\bgh\s+pr\s+merge\b", cmd):
        return "ask", "A merge needs the owner's own OK in this conversation (a relayed approval does not count)."
    if re.search(r"\bgit\s+branch\s+(?:-D|-d|--delete)\b", cmd):
        return "ask", "Deleting a branch needs the owner's own OK."
    if re.search(r"(?:^|[\s|;&(])(?:rm\s+-[a-zA-Z]*r[a-zA-Z]*f?|rm\s+-[a-zA-Z]*f[a-zA-Z]*r|Remove-Item\b[^|;&]*(?:-Recurse|-Force)|rmdir\s+/s|del\s+/s)", cmd, re.I):
        if not TMP_DIRS.search(cmd):
            return "ask", "Deleting files outside tmp/, qa-runs/, qa-evidence/ or build/ needs the owner's own OK."
    if re.search(r"notify\.py\b[^|;&]*--send\b", cmd):
        return check_notify(cmd, cwd)
    if re.search(r"odoo_ticket\.py\b[^|;&]*\b(?:post|move)\b[^|;&]*--send\b", cmd):
        return check_odoo(cmd, cwd)
    if re.search(r"desktop\.py\b[^|;&]*\brun\b", cmd) and not re.search(r"--dry-run\b", cmd):
        return check_desktop(cmd, cwd)
    return None


def _arg(cmd, flag, default=None):
    m = re.search(flag + r"[\s=]+(\"[^\"]+\"|'[^']+'|\S+)", cmd)
    return m.group(1).strip("\"'") if m else default


def _load_cfg(cmd, cwd):
    import notify
    path = _arg(cmd, "--config", "qa.config.yaml")
    path = path if os.path.isabs(path) else os.path.join(cwd or os.getcwd(), path)
    return notify.load_config(path), path


def check_notify(cmd, cwd):
    try:
        cfg, path = _load_cfg(cmd, cwd)
    except Exception as exc:  # noqa: BLE001
        return "deny", f"notify.py --send refused: {str(exc).splitlines()[0][:160]}"
    only = _arg(cmd, "--only")
    channels = cfg.get("notify") or {}
    names = [only] if only else [n for n, c in channels.items() if c and c.get("enabled")]
    bad = [n for n in names if n not in channels or not (channels[n] or {}).get("enabled")]
    if bad:
        return "deny", f"Delivery refused: channel(s) not listed and enabled in {os.path.basename(path)}: {', '.join(bad)}"
    if not names:
        return "deny", f"Delivery refused: no channel is enabled in {os.path.basename(path)}"
    return "ask", f"Real delivery to {', '.join(names)}: the owner clicks to approve (dry-run needs no approval)."


def check_odoo(cmd, cwd):
    try:
        import odoo_ticket
        cfg, path = _load_cfg(cmd, cwd)
        oc = odoo_ticket.odoo_config(cfg, path)
    except Exception as exc:  # noqa: BLE001
        return "deny", f"Odoo write refused: {str(exc).splitlines()[0][:160]}"
    if re.search(r"odoo_ticket\.py\b[^|;&]*\bmove\b", cmd):
        stage = _arg(cmd, "--stage")
        if oc["auto_move"] is True and stage and stage in (oc["on_pass"], oc["on_fail"]):
            return None  # the owner set auto_move: true in the project config for exactly these stages
        return "ask", f"Moving an Odoo ticket to stage {stage!r} is a write: the owner clicks to approve (dry-run needs no approval)."
    return "ask", "Posting a log note on an Odoo ticket is a write: the owner clicks to approve (dry-run needs no approval)."


def check_desktop(cmd, cwd):
    try:
        import desktop
        cfg, path = _load_cfg(cmd, cwd)
        m = re.search(r"desktop\.py\s+run\s+(\"[^\"]+\"|'[^']+'|\S+)", cmd)
        steps_path = m.group(1).strip("\"'") if m else None
        steps = json.load(open(steps_path if os.path.isabs(steps_path) else os.path.join(cwd or os.getcwd(), steps_path), encoding="utf-8"))
        gate = desktop.Gate(cfg)
        for s in steps:
            gate.check(s)
    except Exception as exc:  # noqa: BLE001 (Refused, missing files, bad JSON: all one line)
        return "deny", f"Desktop control refused: {str(exc).splitlines()[0][:160]}"
    return "ask", "Desktop control passed the gates; the owner clicks to approve this run."


def classify_read(path):
    if path and SECRET_PATH.search(path) and not EXAMPLE.search(path):
        return "deny", "Reading a secrets file is blocked. Read it in code and print booleans or field names only."
    return None


def main():
    try:
        data = json.load(sys.stdin)
    except ValueError:
        return 0
    tool = data.get("tool_name", "")
    ti = data.get("tool_input") or {}
    cwd = data.get("cwd") or os.getcwd()
    if tool in ("Bash", "PowerShell"):
        verdict = classify_command(ti.get("command", ""), cwd)
    elif tool == "Read":
        verdict = classify_read(ti.get("file_path", ""))
    else:
        verdict = None
    if verdict:
        return decide(*verdict)
    return 0


if __name__ == "__main__":
    sys.exit(main())
