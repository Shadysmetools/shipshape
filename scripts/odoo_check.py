#!/usr/bin/env python3
"""Static pre-deploy checks for an Odoo module (17.0 / 18.0 / 19.0 / 20.0 style).
Read-only: it opens files and runs `git` read commands, nothing else.

    python scripts/odoo_check.py <module_dir> [--series 17.0] [--base origin/<staging-branch>]

Checks (each PASS / FAIL / WARN, then "N pass / M fail / W warn"):
  manifest      __manifest__.py parses; version is <series>.x.y.z; license set
  version-bump  with --base: version changed when code changed vs the base ref
  migration     migrations/<version>/ exists when the version changed and the
                module was already released; scripts are guarded (information_schema
                / IF EXISTS / IF NOT EXISTS) and idempotent (no bare INSERT without
                a guard, no DROP without IF EXISTS)
  crons         every ir.cron record sits in a noupdate="1" block, so an upgrade
                never re-activates a cron that a neutralized copy switched off
  neutralize    a module with crons or outbound HTTP ships data/neutralize.sql,
                and the manifest does NOT load it as ordinary data (it would switch
                production off on its own upgrade)
  no-commit     no cr.commit() in models/controllers (use an outbox + cron)
  outbound      requests/httpx/urllib calls only in sender code that checks a
                staging guard (warn)
  tests         tests/ exists with at least one test file and tests/__init__.py imports
  api-level     no 18+ APIs in a 17.0 module (<list> views, check_access(),
                @api.private, self.env._) (warn)
"""
from __future__ import annotations

import argparse
import ast
import os
import re
import subprocess
import sys
import xml.etree.ElementTree as ET

VERSION_RX = r"^{series}\.\d+\.\d+\.\d+$"


class Result:
    def __init__(self):
        self.rows = []

    def add(self, name, status, detail):
        self.rows.append((name, status, detail))

    def line(self):
        c = {s: sum(1 for r in self.rows if r[1] == s) for s in ("PASS", "FAIL", "WARN")}
        return f"{c['PASS']} pass / {c['FAIL']} fail / {c['WARN']} warn"


def read(path):
    with open(path, encoding="utf-8", errors="replace") as fh:
        return fh.read()


def files(root, exts):
    for d, dirs, fs in os.walk(root):
        dirs[:] = [x for x in dirs if x not in ("__pycache__", ".git", "node_modules", "static")]
        for f in fs:
            if os.path.splitext(f)[1] in exts:
                yield os.path.join(d, f)


def load_manifest(mod):
    path = os.path.join(mod, "__manifest__.py")
    return ast.literal_eval(read(path))


def git(mod, *args):
    try:
        return subprocess.run(["git", "-C", mod, *args], capture_output=True, text=True, timeout=60).stdout
    except (OSError, subprocess.SubprocessError):
        return ""


def check(mod, series="17.0", base=None):
    r = Result()
    mod = os.path.abspath(mod)
    name = os.path.basename(mod)
    # manifest
    try:
        man = load_manifest(mod)
    except Exception as exc:  # noqa: BLE001
        r.add("manifest", "FAIL", f"__manifest__.py unreadable: {exc}")
        return r
    ver = str(man.get("version", ""))
    if re.match(VERSION_RX.format(series=re.escape(series)), ver):
        r.add("manifest", "PASS", f"version {ver}")
    else:
        r.add("manifest", "FAIL", f"version {ver!r} is not {series}.x.y.z")
    if not man.get("license"):
        r.add("manifest-license", "WARN", "no license key (Odoo defaults to LGPL-3 and logs a warning)")

    # version bump + migration
    changed_ver = False
    if base:
        diff = git(mod, "diff", "--name-only", f"{base}...HEAD", "--", ".")
        old = git(mod, "show", f"{base}:./__manifest__.py")
        try:
            old_ver = str(ast.literal_eval(old).get("version", "")) if old.strip() else None
        except Exception:  # noqa: BLE001
            old_ver = None
        code_changed = any(p.endswith((".py", ".xml", ".csv", ".sql")) for p in diff.splitlines())
        if old_ver is None:
            r.add("version-bump", "PASS", "new module on this branch")
        elif code_changed and old_ver == ver:
            r.add("version-bump", "FAIL", f"code changed vs {base} but version is still {ver}; Odoo.sh will not upgrade it")
        else:
            changed_ver = old_ver != ver
            r.add("version-bump", "PASS", f"{old_ver} -> {ver}" if changed_ver else "no code change")
        if changed_ver and old_ver:
            mig = os.path.join(mod, "migrations", ver)
            if os.path.isdir(mig):
                r.add("migration", "PASS", f"migrations/{ver}/ present")
            else:
                r.add("migration", "WARN", f"version bumped to {ver} without migrations/{ver}/ (fine if no data changes)")
    mdir = os.path.join(mod, "migrations")
    if os.path.isdir(mdir):
        bad = []
        for f in files(mdir, {".py"}):
            src = read(f)
            sql = " ".join(re.findall(r"(?is)execute\(\s*(?:f?\"\"\"|f?'''|f?\"|f?')(.*?)(?:\"\"\"|'''|\"|')", src))
            guarded = re.search(r"information_schema|IF (NOT )?EXISTS|column_exists|table_exists|_has_columns", src, re.I)
            if re.search(r"\b(ALTER|DROP|UPDATE|INSERT|DELETE)\b", sql, re.I) and not guarded:
                bad.append(os.path.relpath(f, mod) + ": SQL without an information_schema / IF EXISTS guard")
            if re.search(r"\bDROP\s+(TABLE|COLUMN)\b(?!\s+IF EXISTS)", sql, re.I):
                bad.append(os.path.relpath(f, mod) + ": DROP without IF EXISTS")
            if not re.search(r"def\s+migrate\s*\(\s*cr\s*,\s*version", src):
                bad.append(os.path.relpath(f, mod) + ": no migrate(cr, version)")
        r.add("migration-guards", "FAIL" if bad else "PASS", "; ".join(bad) or "every migration is guarded")

    # crons
    data_files = [os.path.join(mod, p) for p in man.get("data", [])]
    cron_files, loose = [], []
    for f in files(mod, {".xml"}):
        try:
            tree = ET.parse(f)
        except ET.ParseError as exc:
            r.add("xml", "FAIL", f"{os.path.relpath(f, mod)}: {exc}")
            continue
        root = tree.getroot()
        for parent in root.iter():
            for rec in parent.findall("record"):
                if rec.get("model") != "ir.cron":
                    continue
                cron_files.append(f)
                nu = parent.get("noupdate") or root.get("noupdate")
                if nu not in ("1", "True", "true"):
                    loose.append(f"{os.path.relpath(f, mod)}#{rec.get('id')}")
    cron_files = sorted(set(cron_files))
    if cron_files:
        r.add("crons-noupdate", "FAIL" if loose else "PASS",
              ("crons outside noupdate=\"1\": " + ", ".join(loose)) if loose else f"{len(cron_files)} cron file(s), all noupdate")

    # outbound HTTP
    py = [f for f in files(mod, {".py"}) if "/tests/" not in f.replace("\\", "/") and "/migrations/" not in f.replace("\\", "/")]
    outbound = []
    for f in py:
        src = read(f)
        if re.search(r"\b(requests|httpx)\.(get|post|put|patch|delete|request)\(|urllib\.request\.urlopen\(|\.send_mail\(|['\"]mail\.mail['\"]|smtplib\.", src):
            outbound.append((f, bool(re.search(r"staging|neutraliz|is_neutralized|allow.?list|kill.?switch", src, re.I))))
    for f, guarded in outbound:
        if not guarded:
            r.add("outbound-guard", "WARN", f"{os.path.relpath(f, mod)} makes HTTP calls with no visible staging guard")
    neut = os.path.join(mod, "data", "neutralize.sql")
    if cron_files or outbound:
        if not os.path.exists(neut):
            r.add("neutralize", "FAIL", "module has crons or outbound HTTP but no data/neutralize.sql")
        elif any(os.path.normpath(p) == os.path.normpath(neut) for p in data_files):
            r.add("neutralize", "FAIL", "neutralize.sql is listed in the manifest 'data': it would run on production upgrades")
        else:
            r.add("neutralize", "PASS", "data/neutralize.sql present and not loaded as data")

    # sending switches must default to OFF, so a fresh install (or a fresh staging copy) sends nothing
    on_by_default = []
    for f in py:
        for m in re.finditer(r"(\w*(?:enabled|send|live|production)\w*)\s*=\s*fields\.Boolean\(([^)]*)\)", read(f)):
            if re.search(r"default\s*=\s*True", m.group(2)):
                on_by_default.append(f"{os.path.relpath(f, mod)}: {m.group(1)}")
    if outbound or on_by_default:
        r.add("send-off-default", "FAIL" if on_by_default else "PASS",
              ("sending switches default to on: " + ", ".join(on_by_default)) if on_by_default else "no sending switch defaults to on")

    # cr.commit
    commits = [os.path.relpath(f, mod) for f in py if re.search(r"\bcr\.commit\(\)", read(f))]
    r.add("no-commit", "FAIL" if commits else "PASS", ("cr.commit() in " + ", ".join(commits)) if commits else "none")

    # tests
    tdir = os.path.join(mod, "tests")
    tfiles = [f for f in os.listdir(tdir) if f.startswith("test_") and f.endswith(".py")] if os.path.isdir(tdir) else []
    if not tfiles:
        r.add("tests", "FAIL", "no tests/test_*.py")
    else:
        init = os.path.join(tdir, "__init__.py")
        imported = read(init) if os.path.exists(init) else ""
        missing = [f for f in tfiles if os.path.splitext(f)[0] not in imported]
        r.add("tests", "WARN" if missing else "PASS",
              (f"{len(tfiles)} test files; not imported in tests/__init__.py: " + ", ".join(missing)) if missing else f"{len(tfiles)} test files")

    # API level
    if series == "17.0":
        hits = []
        for f in files(mod, {".py", ".xml"}):
            src = read(f)
            for rx, what in ((r"<list[\s>]", "<list> view (18+)"), (r"\.check_access\(", "check_access() (18+)"),
                             (r"@api\.private", "@api.private (18+)"), (r"self\.env\._\(", "self.env._ (18+)")):
                if re.search(rx, src):
                    hits.append(f"{os.path.relpath(f, mod)}: {what}")
        r.add("api-level", "WARN" if hits else "PASS", "; ".join(hits) or "17.0 APIs only")
    return r


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("module")
    ap.add_argument("--series", default="17.0")
    ap.add_argument("--base", help="git ref to compare with, e.g. origin/<staging-branch>")
    a = ap.parse_args(argv)
    r = check(a.module, a.series, a.base)
    for name, status, detail in r.rows:
        print(f"{status:4} {name}: {detail}")
    print(r.line())
    return 1 if any(s == "FAIL" for _, s, _ in r.rows) else 0


if __name__ == "__main__":
    sys.exit(main())
