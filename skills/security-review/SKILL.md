---
name: security-review
description: Security review for QA - use for "security review", "check for vulnerabilities", "is this safe to ship" on a diff or an allow-listed local/staging app. OWASP-style review, secrets, dependency audit, passive header/cookie/CORS checks; findings refuted before filing; only the count is shared.
---
# Security review
1. `python ${CLAUDE_PLUGIN_ROOT}/scripts/security_scan.py --repo . [--url <url> --allow-host <host>] --out <run>/security`
2. Review the diff with the checklist in the `qa-security-reviewer` agent: authz, tenant isolation, IDOR, injection, XSS, CSRF, SSRF, secrets, deserialization, open redirects, rate limits.
3. Send every finding to `qa-refuter`. File only the survivors, privately.
4. `qa_loop.py attach --kind security --file <run>/security/security.json` stores the count only.

Never production, never third-party hosts, never more than a read-only proof on test data. No video and no public link for security evidence.
