#!/usr/bin/env python3
"""Privacy filter: mask names, emails, phones, tokens and storage paths before
anything is uploaded, posted or committed.

    python scripts/privacy.py mask  <in> [<out>]          # write a masked copy (stdout if no out)
    python scripts/privacy.py scan  <file|dir> ...        # exit 1 if anything sensitive is found
    python scripts/privacy.py scan --deny names.txt ...   # also flag private terms (client/people names)

The deny-list is a plain text file, one term per line, kept OUTSIDE the repo
(default: $SMEKIT_DENYLIST). Scan output never prints the matched value: it
prints the file, line, kind and, for deny-list terms, the term's index only,
so the report itself cannot leak what it found.
"""
from __future__ import annotations

import os
import re
import sys

# Order matters: the most specific patterns run first.
PATTERNS = [
    ("private_key", re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----[\s\S]*?-----END [A-Z ]*PRIVATE KEY-----")),
    ("jwt", re.compile(r"\beyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}")),
    ("github_token", re.compile(r"\b(?:gh[pousr]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,})")),
    ("anthropic_or_openai_key", re.compile(r"\bsk-(?:ant-)?[A-Za-z0-9_-]{20,}")),
    ("aws_key", re.compile(r"\b(?:AKIA|ASIA)[A-Z0-9]{16}\b")),
    ("google_key", re.compile(r"\bAIza[0-9A-Za-z_-]{30,}")),
    ("slack_token", re.compile(r"\bxox[abprs]-[A-Za-z0-9-]{10,}")),
    ("telegram_bot_token", re.compile(r"\b\d{8,10}:[A-Za-z0-9_-]{35}\b")),
    ("bearer", re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._~+/=-]{16,}")),
    ("secret_assignment", re.compile(r"(?i)\b(?:password|passwd|pwd|secret|api[_-]?key|access[_-]?token|auth[_-]?token)\s*[:=]\s*['\"]?(?!\$\{|<|\*{3}|x{3})[^\s'\"<>]{6,}")),
    ("url_credentials", re.compile(r"\b[a-z][a-z0-9+.-]*://[^\s/:@]+:[^\s/@]+@")),
    ("email", re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")),
    # international (+country ...), NANP-style (555) 123-4567 / 555-123-4567, or a local 0XXXXXXXXX(X) mobile
    ("phone", re.compile(r"(?<![\w.+])(?:\+\d{1,3}[ -]?\(?\d{1,4}\)?(?:[ -]?\d{2,4}){2,4}|\(?\d{3}\)?[ -]\d{3}-\d{4}|\d{3}-\d{3}-\d{4}|0\d{9,10})(?![\w.])")),
    # a home folder on any OS, or an absolute path on any Windows drive letter (D:\work\<company>\repo)
    ("user_path", re.compile(r"(?i)(?:[A-Z]:[\\/]+Users[\\/]+|/home/|/Users/)(?!<)[^\\/\s'\"]+|(?<![\w])[A-Za-z]:(?:\\\\|\\|/)(?!<)[^\\/\s'\"<>:]+[\\/]")),
]

REPLACEMENT = {
    "email": "[email]", "phone": "[phone]", "user_path": "[home]", "private_key": "[private-key]",
}

# Placeholders that are allowed to look like data (documentation examples).
ALLOW = re.compile(r"(?i)(?:example\.(?:com|org|net)|@users\.noreply\.github\.com|noreply@anthropic\.com|"
                   r"\+00 000 000 0000|000-000-0000|<[a-z_-]+>|your[-_]?(?:name|email)|\$\{[A-Z_]+|"
                   r"[A-Za-z]:[\\/]+(?:path|proj|\.\.\.)[\\/]|path[\\/]to[\\/])")  # documentation placeholders


def load_denylist(path=None):
    path = path or os.environ.get("SMEKIT_DENYLIST")
    if not path or not os.path.exists(path):
        return []
    with open(path, encoding="utf-8") as fh:
        return [t.strip() for t in fh if t.strip() and not t.startswith("#")]


def _deny_regex(term):
    return re.compile(r"(?<![A-Za-z0-9])" + re.escape(term) + r"(?![A-Za-z0-9])", re.I)


def _phone_like(s):
    digits = re.sub(r"\D", "", s)
    if len(digits) < 9 or len(digits) > 15:
        return False
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}.*", s.strip()):  # a date, not a phone
        return False
    if re.fullmatch(r"[\d.]+", s.strip()) and not re.fullmatch(r"0\d{9,10}", s.strip()):  # a plain number / version
        return False
    return True


def find(text, deny=()):
    """Yield (kind, start, end, deny_index) for every sensitive span."""
    for kind, rx in PATTERNS:
        for m in rx.finditer(text):
            val = m.group(0)
            if ALLOW.search(val):
                continue
            if kind == "phone" and not _phone_like(val):
                continue
            yield kind, m.start(), m.end(), None
    for i, term in enumerate(deny):
        for m in _deny_regex(term).finditer(text):
            yield "deny_term", m.start(), m.end(), i


def mask_text(text, deny=None, names_to=None):
    """Return text with every sensitive span replaced. Deny-list terms become
    names_to (default "[name]")."""
    if not text:
        return text
    deny = load_denylist() if deny is None else deny
    spans = sorted(find(text, deny), key=lambda s: (s[1], -(s[2] - s[1])))
    out, pos = [], 0
    for kind, a, b, _ in spans:
        if a < pos:
            continue
        out.append(text[pos:a])
        out.append((names_to or "[name]") if kind == "deny_term" else REPLACEMENT.get(kind, f"[{kind}]"))
        pos = b
    out.append(text[pos:])
    return "".join(out)


TEXT_EXT = {".md", ".py", ".js", ".mjs", ".cjs", ".ts", ".json", ".yml", ".yaml", ".txt", ".html", ".css", ".sql",
            ".xml", ".srt", ".vtt", ".csv", ".sh", ".ps1", ".toml", ".cfg", ".ini", ""}


def iter_files(paths):
    for p in paths:
        if os.path.isdir(p):
            for root, dirs, files in os.walk(p):
                dirs[:] = [d for d in dirs if d not in (".git", "node_modules", "__pycache__", ".pytest_cache", ".venv")]
                for f in files:
                    if os.path.splitext(f)[1].lower() in TEXT_EXT:
                        yield os.path.join(root, f)
        else:
            yield p


def scan_paths(paths, deny=()):
    """Return a list of findings: (path, line_no, kind, deny_index). Values are never returned."""
    hits = []
    for f in iter_files(paths):
        try:
            with open(f, encoding="utf-8", errors="replace") as fh:
                for n, line in enumerate(fh, 1):
                    for kind, _a, _b, di in find(line, deny):
                        hits.append((f, n, kind, di))
        except OSError:
            continue
    return hits


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    deny_path = None
    if "--deny" in argv:
        i = argv.index("--deny")
        deny_path = argv[i + 1]
        del argv[i:i + 2]
    if not argv or argv[0] not in ("mask", "scan"):
        print(__doc__)
        return 2
    deny = load_denylist(deny_path)
    if argv[0] == "mask":
        src = open(argv[1], encoding="utf-8", errors="replace").read()
        out = mask_text(src, deny)
        if len(argv) > 2:
            open(argv[2], "w", encoding="utf-8").write(out)
        else:
            sys.stdout.write(out)
        return 0
    hits = scan_paths(argv[1:], deny)
    for f, n, kind, di in hits:
        print(f"{f}:{n}: {kind}" + (f" (deny-list term #{di})" if di is not None else ""))
    print(f"privacy scan: {len(hits)} finding(s), deny-list terms loaded: {len(deny)}")
    return 1 if hits else 0


if __name__ == "__main__":
    sys.exit(main())
