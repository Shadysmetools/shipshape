#!/usr/bin/env python3
"""Load test with ramp / soak / spike profiles and p95 / p99 / error-rate thresholds.
LOCAL OR STAGING ONLY: the target host must be in the allow-list.

    python scripts/load_test.py --url http://127.0.0.1:8000/ --profile ramp --allow-host 127.0.0.1 \
        [--p95-ms 500] [--p99-ms 1000] [--max-error-rate 0.01] [--out qa-runs/<run>/load]
    python scripts/load_test.py ... --engine k6     # use k6 with templates/load/k6-profile.js if k6 is installed

Default engine: a stdlib thread pool (no install needed, good for smoke-level load
up to a few hundred requests per second). For heavier tests use k6 (same profiles,
same thresholds, template in templates/load/).

Profiles (scaled by --scale, default 1.0):
  ramp   0 -> 20 virtual users over 30 s, hold 30 s, down over 10 s
  soak   10 users for 5 min
  spike  5 users, jump to 50 for 15 s, back to 5
Outputs: load.json (stats, verdict) and load.svg (latency + errors over time).
Exit 1 when a threshold fails or the host is not allowed.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import statistics
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
from urllib.parse import urlparse

PROFILES = {
    "ramp": [(30, 0, 20), (30, 20, 20), (10, 20, 0)],
    "soak": [(300, 10, 10)],
    "spike": [(10, 5, 5), (15, 50, 50), (10, 5, 5)],
    "smoke": [(5, 2, 2)],
}
PRODUCTION_WORDS = ("prod", "production", "www.", "live")


def host_allowed(url, allow):
    h = (urlparse(url).hostname or "").lower()
    return any(h == a.lower() for a in allow)


def schedule(profile, scale=1.0):
    """[(duration_sec, start_users, end_users)] scaled; durations scale, users scale."""
    return [(max(1, round(d * scale)), round(a * max(scale, 0.1)), round(b * max(scale, 0.1))) for d, a, b in PROFILES[profile]]


def percentile(values, p):
    if not values:
        return 0.0
    s = sorted(values)
    k = (len(s) - 1) * p / 100
    f = int(k)
    c = min(f + 1, len(s) - 1)
    return s[f] + (s[c] - s[f]) * (k - f)


def run_native(url, sched, timeout=10, think=0.2):
    samples = []  # (t_offset, latency_ms, ok)
    lock = threading.Lock()
    stop_all = threading.Event()
    t0 = time.time()
    total = sum(d for d, _a, _b in sched)

    def target_users(t):
        acc = 0
        for d, a, b in sched:
            if t < acc + d:
                return round(a + (b - a) * (t - acc) / d)
            acc += d
        return 0

    def worker(idx):
        while not stop_all.is_set():
            t = time.time() - t0
            if idx >= target_users(t):
                time.sleep(0.1)
                continue
            s = time.time()
            ok = True
            try:
                with urllib.request.urlopen(url, timeout=timeout) as r:  # noqa: S310 (allow-listed host only)
                    r.read()
                    ok = r.status < 400
            except (urllib.error.URLError, OSError, ValueError):
                ok = False
            lat = (time.time() - s) * 1000
            with lock:
                samples.append((s - t0, lat, ok))
            time.sleep(think)

    peak = max(max(a, b) for _d, a, b in sched)
    threads = [threading.Thread(target=worker, args=(i,), daemon=True) for i in range(peak)]
    for th in threads:
        th.start()
    time.sleep(total)
    stop_all.set()
    for th in threads:
        th.join(timeout + 1)
    return samples


def stats(samples):
    lat = [s[1] for s in samples]
    errors = sum(1 for s in samples if not s[2])
    dur = (max(s[0] for s in samples) - min(s[0] for s in samples)) if len(samples) > 1 else 1
    return {"requests": len(samples), "errors": errors, "error_rate": round(errors / len(samples), 4) if samples else 1.0,
            "rps": round(len(samples) / max(dur, 1e-6), 1), "p50_ms": round(percentile(lat, 50), 1),
            "p95_ms": round(percentile(lat, 95), 1), "p99_ms": round(percentile(lat, 99), 1),
            "mean_ms": round(statistics.mean(lat), 1) if lat else 0.0}


def verdict(st, p95, p99, max_err):
    checks = [("p95", st["p95_ms"] <= p95, f"{st['p95_ms']} ms <= {p95} ms"),
              ("p99", st["p99_ms"] <= p99, f"{st['p99_ms']} ms <= {p99} ms"),
              ("error rate", st["error_rate"] <= max_err, f"{st['error_rate']:.2%} <= {max_err:.2%}"),
              ("requests made", st["requests"] > 0, f"{st['requests']} requests")]
    return [{"check": n, "result": "PASS" if ok else "FAIL", "detail": d} for n, ok, d in checks]


def chart(samples, path, width=900, height=260):
    if not samples:
        return
    end = max(s[0] for s in samples) or 1
    buckets = {}
    for t, lat, ok in samples:
        b = int(t)
        buckets.setdefault(b, []).append((lat, ok))
    mx = max(percentile([x[0] for x in v], 95) for v in buckets.values()) or 1
    pad = 36
    pts, errs = [], []
    for b, v in sorted(buckets.items()):
        x = pad + (width - 2 * pad) * b / max(end, 1)
        y = height - pad - (height - 2 * pad) * percentile([q[0] for q in v], 95) / mx
        pts.append(f"{x:.1f},{y:.1f}")
        e = sum(1 for q in v if not q[1])
        if e:
            errs.append(f'<circle cx="{x:.1f}" cy="{height - pad - 4}" r="3" fill="#c0392b"><title>{e} errors</title></circle>')
    svg = (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width} {height}" font-family="Segoe UI,Arial" font-size="11">'
           f'<rect width="100%" height="100%" fill="#fff"/><text x="{pad}" y="18">p95 latency per second (max {mx:.0f} ms); red dots = errors</text>'
           f'<line x1="{pad}" y1="{height - pad}" x2="{width - pad}" y2="{height - pad}" stroke="#ccc"/>'
           f'<polyline fill="none" stroke="#3355cc" stroke-width="2" points="{" ".join(pts)}"/>{"".join(errs)}'
           f'<text x="{pad}" y="{height - 10}">0 s</text><text x="{width - pad - 30}" y="{height - 10}">{end:.0f} s</text></svg>')
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(svg)


def run_k6(url, profile, scale, p95, p99, max_err, out):
    script = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "templates", "load", "k6-profile.js")
    summary = os.path.join(out, "k6-summary.json")
    env = {**os.environ, "TARGET_URL": url, "PROFILE": profile, "SCALE": str(scale), "P95": str(p95), "P99": str(p99), "MAX_ERR": str(max_err)}
    rc = subprocess.run(["k6", "run", "--summary-export", summary, script], env=env, timeout=3600).returncode
    return rc, summary


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--url", required=True)
    ap.add_argument("--profile", choices=sorted(PROFILES), default="ramp")
    ap.add_argument("--scale", type=float, default=1.0)
    ap.add_argument("--allow-host", action="append", default=[], help="repeatable; required")
    ap.add_argument("--p95-ms", type=float, default=500)
    ap.add_argument("--p99-ms", type=float, default=1000)
    ap.add_argument("--max-error-rate", type=float, default=0.01)
    ap.add_argument("--engine", choices=("native", "k6"), default="native")
    ap.add_argument("--out", default="load-results")
    a = ap.parse_args(argv)
    host = (urlparse(a.url).hostname or "").lower()
    if not host_allowed(a.url, a.allow_host):
        print(f"REFUSED: host {host!r} is not in --allow-host. Load tests run on local or staging hosts only.")
        return 1
    if any(w in host for w in PRODUCTION_WORDS) and not os.environ.get("SMEKIT_LOAD_OWNER_OK"):
        print(f"REFUSED: {host!r} looks like production. Set SMEKIT_LOAD_OWNER_OK=1 only with the owner's direct OK for a staging host.")
        return 1
    os.makedirs(a.out, exist_ok=True)
    if a.engine == "k6":
        if not shutil.which("k6"):
            print("k6 is not installed; use --engine native or run scripts/install.(sh|ps1) --with-k6")
            return 1
        rc, summary = run_k6(a.url, a.profile, a.scale, a.p95_ms, a.p99_ms, a.max_error_rate, a.out)
        print(f"k6 finished with exit {rc}; summary {summary}")
        return 0 if rc == 0 else 1
    samples = run_native(a.url, schedule(a.profile, a.scale))
    st = stats(samples)
    checks = verdict(st, a.p95_ms, a.p99_ms, a.max_error_rate)
    chart(samples, os.path.join(a.out, "load.svg"))
    n = sum(c["result"] == "PASS" for c in checks)
    m = len(checks) - n
    res = {"url": a.url, "profile": a.profile, "scale": a.scale, "stats": st, "checks": checks, "summary": f"{n} pass / {m} fail"}
    with open(os.path.join(a.out, "load.json"), "w", encoding="utf-8") as fh:
        json.dump(res, fh, indent=1)
    print(f"{a.profile}: {st['requests']} req, {st['rps']} rps, p95 {st['p95_ms']} ms, p99 {st['p99_ms']} ms, "
          f"errors {st['error_rate']:.2%} -> thresholds {n} pass / {m} fail")
    return 0 if m == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
