#!/usr/bin/env python3
"""PreToolUse command hook: block a `git commit` whose staged changes add secrets
or personal data. Deterministic on purpose: a model cannot see the staged diff,
so this check is a script, and the plain-language hooks cover the rest.

Reads the hook input JSON on stdin. Exit 0 = allow, exit 2 = block (stderr is
shown to Claude). Prints kinds and locations only, never the matched values.
Deny-list of private names: $SMEKIT_DENYLIST (a file kept outside the repo).
"""
import json
import os
import re
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import privacy  # noqa: E402

BLOCK_KINDS = {"private_key", "jwt", "github_token", "anthropic_or_openai_key", "aws_key", "google_key", "slack_token",
               "telegram_bot_token", "bearer", "secret_assignment", "url_credentials", "email", "phone", "deny_term"}


def staged_hits(cwd, deny):
    diff = subprocess.run(["git", "diff", "--cached", "-U0", "--no-color"], cwd=cwd, capture_output=True, text=True,
                          encoding="utf-8", errors="replace", timeout=60).stdout
    hits, path, line_no = [], None, 0
    for line in diff.splitlines():
        if line.startswith("+++ "):
            path = line[6:] if line.startswith("+++ b/") else line[4:]
        elif line.startswith("@@"):
            m = re.search(r"\+(\d+)", line)
            line_no = int(m.group(1)) if m else 0
        elif line.startswith("+") and not line.startswith("+++"):
            for kind, _a, _b, di in privacy.find(line[1:], deny):
                if kind in BLOCK_KINDS:
                    hits.append(f"{path}:{line_no}: {kind}" + (f" (deny-list #{di})" if di is not None else ""))
            line_no += 1
    return hits


def main():
    try:
        data = json.load(sys.stdin)
    except ValueError:
        return 0
    cmd = (data.get("tool_input") or {}).get("command", "")
    if not re.search(r"\bgit\b[^|;&]*\bcommit\b", cmd):
        return 0
    hits = staged_hits(data.get("cwd") or os.getcwd(), privacy.load_denylist())
    if not hits:
        return 0
    sys.stderr.write("Commit blocked: the staged changes add possible secrets or personal data:\n  " + "\n  ".join(hits[:30]) +
                     "\nReplace them with placeholders or env var references, then commit again.\n")
    return 2


if __name__ == "__main__":
    sys.exit(main())
