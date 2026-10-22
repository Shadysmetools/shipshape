#!/usr/bin/env python3
"""Self-contained HTML report for a QA run (opens offline, no CDN, no scripts needed).

    python scripts/qa_report_html.py <run_dir> [--root qa-runs] [--embed-video]

Writes <run_dir>/report.html with: the verdict and "N pass / M fail", the
per-case table of the latest round, video players, screenshots (embedded),
console and network evidence, bugs with their verify/refute status and
links, human gates, and a trend chart across all runs under --root.
Videos are linked relatively (keep the folder together); --embed-video
inlines them as base64 for a single-file share (size permitting).
"""
from __future__ import annotations

import argparse
import base64
import html
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import qa_history  # noqa: E402

E = html.escape
CSS = """
:root{--bg:#f5f6f8;--card:#fff;--ink:#17202b;--muted:#5d6876;--line:#e3e7ec;--pass:#1b7f45;--fail:#b3261e;--block:#a15c00;--skip:#6b7280;--accent:#3355cc;--chip:#eef1f5}
@media (prefers-color-scheme:dark){:root:not([data-theme=light]){--bg:#0f1318;--card:#171c23;--ink:#e6ebf1;--muted:#9aa6b4;--line:#28303a;--pass:#4cc282;--fail:#ff6b61;--block:#f0a33c;--skip:#9aa3ad;--accent:#7f9cff;--chip:#222a33}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);font:15px/1.5 system-ui,-apple-system,"Segoe UI",Arial,sans-serif}
main{max-width:1180px;margin:0 auto;padding:28px 16px 60px}
header h1{font-size:28px;margin:0 0 4px}header p{margin:0;color:var(--muted)}
.verdict{display:flex;flex-wrap:wrap;gap:12px;margin:22px 0}
.tile{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:14px 18px;min-width:130px}
.tile b{display:block;font-size:28px;line-height:1.1}.tile span{color:var(--muted);font-size:13px;text-transform:uppercase;letter-spacing:.06em}
.big{flex:1 1 320px}.big b{font-size:22px}
section{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:18px 20px;margin:16px 0}
section h2{font-size:18px;margin:0 0 12px}
table{width:100%;border-collapse:collapse;font-size:14px}th,td{text-align:left;padding:8px 10px;border-bottom:1px solid var(--line);vertical-align:top}
th{color:var(--muted);font-weight:600;font-size:12px;text-transform:uppercase;letter-spacing:.05em}
.r{font-weight:700;border-radius:999px;padding:2px 10px;font-size:12px;white-space:nowrap}
.PASS{color:var(--pass);background:color-mix(in srgb,var(--pass) 14%,transparent)}.FAIL{color:var(--fail);background:color-mix(in srgb,var(--fail) 14%,transparent)}
.BLOCKED{color:var(--block);background:color-mix(in srgb,var(--block) 16%,transparent)}.SKIPPED,.NOT{color:var(--skip);background:var(--chip)}
.grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(260px,1fr));gap:12px}
.grid figure{margin:0}.grid img{width:100%;border-radius:8px;border:1px solid var(--line)}figcaption{font-size:12px;color:var(--muted)}
video{width:100%;max-width:960px;border-radius:10px;background:#000}
code,pre{font-family:Consolas,Menlo,monospace;font-size:12.5px}pre{background:var(--chip);padding:10px;border-radius:8px;overflow:auto;max-height:260px}
.muted{color:var(--muted)}a{color:var(--accent)}svg text{fill:var(--muted);font-size:11px}
@media (max-width:640px){th:nth-child(4),td:nth-child(4){display:none}}
"""


def b64(path, mime):
    with open(path, "rb") as fh:
        return f"data:{mime};base64," + base64.b64encode(fh.read()).decode()


def chip(result):
    cls = result.split()[0]
    return f'<span class="r {cls}">{E(result)}</span>'


def trend_svg(trend):
    if not trend:
        return '<p class="muted">No earlier runs yet.</p>'
    w, h, pad = 900, 220, 34
    n = len(trend)
    mx = max(max(t["total"] for t in trend), 1)
    bw = (w - 2 * pad) / n
    bars = []
    for i, t in enumerate(trend):
        x = pad + i * bw + bw * 0.15
        ww = bw * 0.7
        y = h - pad
        for key, color in (("pass", "var(--pass)"), ("fail", "var(--fail)"), ("blocked", "var(--block)")):
            hh = (h - 2 * pad) * t[key] / mx
            if hh:
                bars.append(f'<rect x="{x:.1f}" y="{y - hh:.1f}" width="{ww:.1f}" height="{hh:.1f}" fill="{color}" rx="2"><title>{E(t["run"])} r{t["round"]}: {E(t["summary"] or "")}</title></rect>')
            y -= hh
        bars.append(f'<text x="{x + ww / 2:.1f}" y="{h - pad + 14}" text-anchor="middle">r{t["round"]}</text>')
    axis = f'<line x1="{pad}" y1="{h - pad}" x2="{w - pad}" y2="{h - pad}" stroke="var(--line)"/>'
    legend = ('<text x="34" y="16">pass</text><rect x="62" y="7" width="10" height="10" fill="var(--pass)"/>'
              '<text x="84" y="16">fail</text><rect x="104" y="7" width="10" height="10" fill="var(--fail)"/>'
              '<text x="126" y="16">blocked</text><rect x="172" y="7" width="10" height="10" fill="var(--block)"/>')
    return f'<svg viewBox="0 0 {w} {h}" width="100%" role="img" aria-label="pass and fail per round">{legend}{axis}{"".join(bars)}</svg>'


def build(run_dir, root=None, embed_video=False):
    led = json.load(open(os.path.join(run_dir, "ledger.json"), encoding="utf-8"))
    root = root or os.path.dirname(os.path.abspath(run_dir))
    hist = qa_history.history(qa_history.load_runs(root))
    rnd = led["rounds"][-1] if led["rounds"] else None
    c = rnd["counts"] if rnd else {}
    status = {"met": "Goal met", "stopped": "Stopped", "waiting-human": "Waiting for a human", "running": "In progress"}.get(led["status"], led["status"])
    parts = ['<p class="muted" style="letter-spacing:.08em;text-transform:uppercase;font-weight:700;margin:0 0 6px">ShipShape &middot; your autonomous QA crew</p>', f"<header><h1>{E(led['goal'])}</h1><p>QA run <code>{E(os.path.basename(os.path.abspath(run_dir)))}</code> · started {E(led['created'])} · "
             f"{len(led['rounds'])} round(s) · {led['elapsed_minutes']} min</p></header>",
             '<div class="verdict">',
             f'<div class="tile big"><span>Verdict</span><b>{E(status)}</b><div class="muted">{E(led.get("stop_reason") or "")}</div></div>']
    for k, label in (("PASS", "pass"), ("FAIL", "fail"), ("BLOCKED", "blocked"), ("NOT CHECKED", "not checked")):
        parts.append(f'<div class="tile"><span>{label}</span><b class="r {k.split()[0]}" style="background:none;padding:0">{c.get(k, 0)}</b></div>')
    parts.append("</div>")
    if rnd:
        parts.append(f"<section><h2>Round {rnd['n']}: {E(rnd['summary'])}</h2><table><tr><th>Case</th><th>Result</th><th>What was checked</th><th>Evidence</th><th>Note</th></tr>")
        for run in rnd["runs"]:
            for r in run["results"]:
                ev = r.get("evidence") or ""
                link = f'<a href="{E(run["dir"] + "/" + ev)}">{E(ev)}</a>' if ev else '<span class="muted">none</span>'
                parts.append(f"<tr><td><code>{E(r['id'])}</code></td><td>{chip(r['result'])}</td><td>{E(r.get('title', ''))}</td><td>{link}</td><td>{E(r.get('note', ''))}</td></tr>")
        parts.append("</table></section>")
        for run in rnd["runs"]:
            d = os.path.join(run_dir, run["dir"])
            parts.append(f"<section><h2>Video: {E(os.path.basename(run['plan']))}</h2>")
            vid = run.get("video")
            vpath = os.path.join(d, vid) if vid else None
            if vpath and os.path.exists(vpath) and vpath.endswith(".mp4"):
                src = b64(vpath, "video/mp4") if embed_video else E(run["dir"] + "/" + vid)
                track = os.path.join(d, "captions.srt")
                parts.append(f'<video controls preload="metadata" src="{src}"></video>')
                if os.path.exists(track):
                    parts.append(f'<p class="muted">Captions: <a href="{E(run["dir"])}/captions.srt">captions.srt</a> · trace: <a href="{E(run["dir"])}/trace.zip">trace.zip</a> (open with <code>npx playwright show-trace</code>)</p>')
            else:
                parts.append('<p class="muted">No video for this plan.</p>')
            shots = sorted(f for f in os.listdir(d) if f.endswith(".png")) if os.path.isdir(d) else []
            if shots:
                parts.append('<div class="grid">' + "".join(f'<figure><img alt="{E(s)}" src="{b64(os.path.join(d, s), "image/png")}"><figcaption>{E(s)}</figcaption></figure>' for s in shots) + "</div>")
            con, net = run.get("console", []), run.get("network", [])
            parts.append("<h2 style='margin-top:16px'>Console and network</h2>")
            con_txt = "\n".join(f"[{x.get('type')}] {x.get('text')}" for x in con) or "no console errors or warnings"
            net_txt = "\n".join(f"{x.get('status')} {x.get('url')}" for x in net) or "no failed or 4xx/5xx requests"
            parts.append(f"<pre>{E(con_txt)}</pre><pre>{E(net_txt)}</pre>")
            if run.get("stopped"):
                parts.append(f"<p><b>Stopped:</b> {E(run['stopped'])}</p>")
            parts.append("</section>")
    rev, load, sec = led.get("review"), led.get("load"), led.get("security")
    if rev or load or sec:
        parts.append("<section><h2>Review, load and security</h2><table><tr><th>Check</th><th>Result</th><th>Details</th></tr>")
        if rev:
            parts.append(f"<tr><td>Code review</td><td>{E(str(rev.get('verdict') or ''))}</td><td>{E(str(rev.get('summary') or ''))}</td></tr>")
        if load:
            st = load.get("stats", {})
            parts.append(f"<tr><td>Load ({E(str(load.get('profile')))})</td><td>{E(str(load.get('summary')))}</td><td>p95 {st.get('p95_ms')} ms, p99 {st.get('p99_ms')} ms, "
                         f"errors {st.get('error_rate')}, {st.get('rps')} rps</td></tr>")
        if sec:
            parts.append(f"<tr><td>Security</td><td>{sec.get('count', 0)} finding(s)</td><td>Details are private ({E(sec.get('file', ''))}); "
                         "each goes through the refuter before filing.</td></tr>")
        parts.append("</table>")
        svg = load and os.path.join(run_dir, load.get("svg", ""))
        if svg and os.path.isfile(svg):
            parts.append(f'<img alt="load chart" style="width:100%;margin-top:12px;border-radius:8px" src="{b64(svg, "image/svg+xml")}">')
        parts.append("</section>")
    parts.append("<section><h2>Bugs (verify + refute before filing)</h2>")
    if led["bugs"]:
        parts.append("<table><tr><th>Bug</th><th>Case</th><th>Status</th><th>Title</th><th>Link</th></tr>")
        for b in led["bugs"]:
            ln = f'<a href="{E(b["link"])}">{E(b["link"])}</a>' if b.get("link") else '<span class="muted">not filed</span>'
            parts.append(f"<tr><td>{E(b['id'])}</td><td><code>{E(b['case'])}</code></td><td>{E(b['status'])}</td><td>{E(b.get('title', ''))}</td><td>{ln}</td></tr>")
        parts.append("</table>")
    else:
        parts.append('<p class="muted">No bugs in this run.</p>')
    gates = led.get("human_gates", [])
    if gates:
        parts.append("<h2 style='margin-top:16px'>Human gates</h2><ul>" + "".join(
            f"<li>{E(g['id'])} {'OPEN' if g.get('open') else 'closed'}: {E(g['reason'])}</li>" for g in gates) + "</ul>")
    parts.append("</section>")
    parts.append(f"<section><h2>Trend across runs</h2>{trend_svg(hist['trend'])}")
    if hist["flaky"]:
        parts.append("<p><b>Flaky:</b> " + ", ".join(f"<code>{E(f['case'])}</code> ({E(f['history'])})" for f in hist["flaky"]) + "</p>")
    parts.append("</section>")
    parts.append('<p class="muted">ShipShape: your autonomous QA crew. Test data only. Privacy-filter this folder before sharing it.</p>')
    doc = (f'<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">'
           f"<title>ShipShape QA report</title><style>{CSS}</style></head><body><main>{''.join(parts)}</main></body></html>")
    out = os.path.join(run_dir, "report.html")
    with open(out, "w", encoding="utf-8") as fh:
        fh.write(doc)
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("run_dir")
    ap.add_argument("--root")
    ap.add_argument("--embed-video", action="store_true")
    a = ap.parse_args(argv)
    print(build(a.run_dir, a.root, a.embed_video))


if __name__ == "__main__":
    main()
