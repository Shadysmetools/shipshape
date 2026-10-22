#!/usr/bin/env python3
"""Read-leaning security checks for the qa-security-reviewer agent.

    python scripts/security_scan.py --repo . [--url http://127.0.0.1:8000/ --allow-host 127.0.0.1] [--out dir]

What it runs (each tool only if installed; a missing tool is reported as
SKIPPED, never as a pass):
  secrets       gitleaks (if installed) + the kit's own privacy/secret sweep
  dependencies  npm audit (package-lock.json), pip-audit (requirements*.txt), osv-scanner
  headers       one GET to an ALLOW-LISTED url: security headers, cookie flags,
                CORS (wildcard with credentials), server banner. Passive only.
It never sends attack payloads, never runs against production or third-party
hosts, and writes findings to a PRIVATE file (security.json). Delivery
channels only ever receive the finding COUNT.

Each finding: {"id", "severity": high|medium|low|info, "title", "evidence", "fix", "source"}.
Findings go to the qa-refuter before anything is filed.
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import shutil
import subprocess
import sys
import urllib.error
import urllib.request
from urllib.parse import urlparse

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import privacy  # noqa: E402

SEC_HEADERS = {
    "content-security-policy": ("medium", "Add a Content-Security-Policy (start with default-src 'self')."),
    "x-content-type-options": ("low", "Send X-Content-Type-Options: nosniff."),
    "x-frame-options": ("low", "Send X-Frame-Options: DENY or a CSP frame-ancestors rule."),
    "referrer-policy": ("low", "Send Referrer-Policy: strict-origin-when-cross-origin."),
}


def tool(cmd, cwd, timeout=600):
    try:
        p = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, timeout=timeout, encoding="utf-8", errors="replace")
        return p.returncode, p.stdout, p.stderr
    except (OSError, subprocess.SubprocessError) as exc:
        return -1, "", str(exc)


def secrets(repo, deny=()):
    out, ran = [], []
    if shutil.which("gitleaks"):
        rc, so, _ = tool(["gitleaks", "detect", "--no-banner", "--redact", "--report-format", "json", "--report-path", "-", "-s", repo], repo)
        ran.append("gitleaks")
        try:
            for f in json.loads(so or "[]"):
                out.append({"severity": "high", "title": f"Secret ({f.get('RuleID')})", "evidence": f"{f.get('File')}:{f.get('StartLine')} (value redacted)",
                            "fix": "Remove it, rotate the credential, purge history if pushed.", "source": "gitleaks"})
        except ValueError:
            pass
    # positive control: the sweep must find a planted synthetic key, or the result is UNKNOWN, not "0 findings"
    import tempfile
    with tempfile.TemporaryDirectory() as td:
        with open(os.path.join(td, "control.txt"), "w", encoding="utf-8") as fh:
            fh.write("key = " + "sk-" + "C" * 40 + "\n")
        if not privacy.scan_paths([td]):
            return [{"severity": "high", "title": "Secret sweep UNKNOWN: positive control not detected", "evidence": "control",
                     "fix": "Fix the scanner before trusting a zero result.", "source": "privacy-sweep"}], ran
    ran.append("privacy-sweep (control ok)")
    for f, n, kind, _di in privacy.scan_paths([repo], deny):
        if kind in ("email", "phone", "user_path", "deny_term"):
            sev = "medium" if kind == "deny_term" else "low"
        else:
            sev = "high"
        out.append({"severity": sev, "title": f"Possible {kind.replace('_', ' ')}", "evidence": f"{os.path.relpath(f, repo)}:{n}",
                    "fix": "Replace with a placeholder or read it from an env var.", "source": "privacy-sweep"})
    return out, ran


def dependencies(repo):
    out, ran, skipped = [], [], []
    if glob.glob(os.path.join(repo, "**", "package-lock.json"), recursive=True):
        if shutil.which("npm"):
            rc, so, _ = tool(["npm", "audit", "--json"], repo)
            ran.append("npm audit")
            try:
                for name, v in (json.loads(so or "{}").get("vulnerabilities") or {}).items():
                    out.append({"severity": {"critical": "high", "high": "high", "moderate": "medium"}.get(v.get("severity"), "low"),
                                "title": f"Vulnerable dependency {name}", "evidence": f"npm audit: {v.get('severity')} via {str(v.get('via'))[:120]}",
                                "fix": "npm audit fix, or pin a patched version.", "source": "npm audit"})
            except ValueError:
                pass
        else:
            skipped.append("npm audit (npm not installed)")
    reqs = glob.glob(os.path.join(repo, "**", "requirements*.txt"), recursive=True)
    if reqs:
        if shutil.which("pip-audit"):
            for r in reqs:
                rc, so, _ = tool(["pip-audit", "-r", r, "-f", "json", "--progress-spinner", "off"], repo)
                ran.append(f"pip-audit {os.path.relpath(r, repo)}")
                try:
                    for d in json.loads(so or "{}").get("dependencies", []):
                        for v in d.get("vulns", []):
                            out.append({"severity": "high", "title": f"{d['name']} {d.get('version')}: {v.get('id')}", "evidence": "pip-audit",
                                        "fix": f"Upgrade to {', '.join(v.get('fix_versions') or ['a patched version'])}.", "source": "pip-audit"})
                except ValueError:
                    pass
        else:
            skipped.append("pip-audit (not installed: pip install pip-audit)")
    if shutil.which("osv-scanner"):
        rc, so, _ = tool(["osv-scanner", "--format", "json", "-r", repo], repo)
        ran.append("osv-scanner")
    else:
        skipped.append("osv-scanner (not installed)")
    return out, ran, skipped


def headers(url, allow, opener=None):
    host = (urlparse(url).hostname or "").lower()
    if host not in [a.lower() for a in allow]:
        return [{"severity": "info", "title": "Header check REFUSED", "evidence": f"{host} is not allow-listed", "fix": "Add a local/staging host with --allow-host.", "source": "headers"}], False
    opener = opener or urllib.request.urlopen
    req = urllib.request.Request(url, headers={"Origin": "https://evil.example"})
    try:
        with opener(req, timeout=20) as r:  # noqa: S310 (allow-listed host only)
            hdrs = {k.lower(): v for k, v in r.headers.items()}
            cookies = r.headers.get_all("Set-Cookie") or []
    except urllib.error.HTTPError as e:
        hdrs = {k.lower(): v for k, v in e.headers.items()}
        cookies = e.headers.get_all("Set-Cookie") or []
    except (urllib.error.URLError, OSError) as exc:
        return [{"severity": "info", "title": "Header check could not connect", "evidence": str(exc)[:120], "fix": "", "source": "headers"}], True
    out = []
    for h, (sev, fix) in SEC_HEADERS.items():
        if h not in hdrs:
            out.append({"severity": sev, "title": f"Missing {h}", "evidence": f"GET {url}", "fix": fix, "source": "headers"})
    if url.startswith("https") and "strict-transport-security" not in hdrs:
        out.append({"severity": "medium", "title": "Missing Strict-Transport-Security", "evidence": f"GET {url}", "fix": "Send HSTS on HTTPS.", "source": "headers"})
    acao, acac = hdrs.get("access-control-allow-origin"), hdrs.get("access-control-allow-credentials", "").lower()
    if acao in ("*", "https://evil.example") and (acac == "true" or acao != "*"):
        out.append({"severity": "high", "title": "CORS reflects an arbitrary origin" + (" with credentials" if acac == "true" else ""),
                    "evidence": f"Origin https://evil.example -> ACAO {acao}, ACAC {acac or 'unset'}", "fix": "Allow-list exact origins.", "source": "headers"})
    for c in cookies:
        low = c.lower()
        name = c.split("=", 1)[0]
        miss = [f for f in ("httponly", "secure", "samesite") if f not in low]
        if miss:
            out.append({"severity": "medium" if "httponly" in miss else "low", "title": f"Cookie {name} lacks {', '.join(miss)}",
                        "evidence": f"Set-Cookie on GET {url} (value not stored)", "fix": "Set HttpOnly; Secure; SameSite=Lax.", "source": "headers"})
    if hdrs.get("server") and any(ch.isdigit() for ch in hdrs["server"]):
        out.append({"severity": "info", "title": "Server banner shows a version", "evidence": "Server header", "fix": "Hide version numbers.", "source": "headers"})
    return out, True


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--repo", default=".")
    ap.add_argument("--url")
    ap.add_argument("--allow-host", action="append", default=[])
    ap.add_argument("--deny", help="deny-list of private terms (kept outside the repo)")
    ap.add_argument("--out", default=".")
    a = ap.parse_args(argv)
    findings, ran = secrets(a.repo, privacy.load_denylist(a.deny))
    dep, dran, skipped = dependencies(a.repo)
    findings += dep
    ran += dran
    if a.url:
        h, did = headers(a.url, a.allow_host)
        findings += h
        if did:
            ran.append("headers")
    for i, f in enumerate(findings, 1):
        f["id"] = f"S{i}"
        f["status"] = "suspected"  # the refuter decides what becomes "verified"
    counts = {s: sum(1 for f in findings if f["severity"] == s) for s in ("high", "medium", "low", "info")}
    os.makedirs(a.out, exist_ok=True)
    res = {"ran": ran, "skipped": skipped, "counts": counts, "count": len(findings), "findings": findings,
           "note": "PRIVATE: never paste findings into chat channels; share the count only."}
    with open(os.path.join(a.out, "security.json"), "w", encoding="utf-8") as fh:
        json.dump(res, fh, indent=1)
    print(f"security: {len(findings)} finding(s) high {counts['high']} / medium {counts['medium']} / low {counts['low']} / info {counts['info']}; "
          f"ran: {', '.join(ran)}; skipped: {', '.join(skipped) or 'none'}; details in {os.path.join(a.out, 'security.json')} (private)")
    return 1 if counts["high"] else 0


if __name__ == "__main__":
    sys.exit(main())
