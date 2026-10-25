#!/usr/bin/env python3
"""Run a QA plan in a real browser and record narrated video evidence.

    python scripts/record.py plan.json --out qa-evidence/<run> [--narrate] [--browser chromium|firefox|webkit]
                             [--headed] [--total-timeout 900] [--step-timeout 15]

Pipeline: run -> record (Playwright native video + trace) -> caption -> narrate
(edge-tts, synthesized BEFORE the run so there are no pauses) -> mp4 + .srt ->
trim dead time to the video cap (scripts/video_trim.py, original kept) ->
results.json + "N pass / M fail". Upload is a separate, privacy-filtered step.

Video length comes from the `video` section of qa.config.yaml (--config, default
$SMEKIT_QA_CONFIG or ./qa.config.yaml) and the plan's optional "video_type".

Guards built in (see docs/OPERATING-RULES.md):
- Requests to hosts outside plan.allow_hosts are aborted and listed.
- live=true plans stop before any input (fill/type/select/check/press/submit)
  unless allow_input=true, which needs the site owner's OK.
- Never pay: steps that touch pay/checkout/card fields are refused unless the
  host is local and the plan says payment_mock=true.
- Every step has a timeout and the whole run has a total timeout.

Plan format (see templates/qa-plan.example.json):
{"name": "...", "base_url": "http://127.0.0.1:8000", "allow_hosts": ["127.0.0.1", "localhost"],
 "live": false, "allow_input": false, "viewport": [1280, 720],
 "steps": [{"do": "goto", "url": "/", "say": "Open the sign-up page"},
           {"do": "fill", "selector": "#email", "value": "test.user@example.com"},
           {"do": "click", "selector": "text=Create account"},
           {"do": "expect_text", "text": "Welcome", "case": "TC-01", "say": "The welcome message shows"},
           {"do": "screenshot", "name": "welcome"}]}
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import time
from urllib.parse import urljoin, urlparse

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import report  # noqa: E402
import video_trim  # noqa: E402

INPUT_STEPS = {"fill", "type", "select", "check", "press", "submit"}
PAY = re.compile(r"(?i)\b(pay|payment|checkout|purchase|buy now|place order|subscribe|card[-_ ]?number|cvc|cvv|iban)\b")
CAPTION_JS = r"""
(() => {
  window.__qaCaption = (text, kind) => {
    let bar = document.getElementById('__qa_caption');
    if (!bar) {
      bar = document.createElement('div'); bar.id = '__qa_caption';
      bar.style.cssText = 'position:fixed;left:0;right:0;bottom:0;z-index:2147483647;padding:12px 24px;' +
        'font:600 20px/1.35 system-ui,Segoe UI,Arial,sans-serif;color:#fff;background:rgba(20,24,31,.88);text-align:center;pointer-events:none';
      (document.body || document.documentElement).appendChild(bar);
    }
    bar.style.background = kind === 'FAIL' ? 'rgba(150,30,30,.92)' : kind === 'PASS' ? 'rgba(20,100,50,.92)' : 'rgba(20,24,31,.88)';
    bar.textContent = text;
  };
  const re = /[\w.+-]+@[\w-]+\.[\w.]+/g;
  const mask = () => {
    if (!document.body) return;
    const w = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
    for (let n; (n = w.nextNode());) {
      if (n.parentElement && n.parentElement.id === '__qa_caption') continue;
      const c = n.nodeValue.replace(re, '[email]'); if (c !== n.nodeValue) n.nodeValue = c;
    }
  };
  const start = () => {
    mask();
    // init scripts can run before <html> exists, so the observer is attached once the DOM is there
    new MutationObserver(mask).observe(document.documentElement, {subtree: true, childList: true, characterData: true});
    const st = document.createElement('style');
    st.textContent = 'input[type=email],input[name*=mail i],input[id*=mail i]{-webkit-text-security:disc}';
    (document.head || document.documentElement).appendChild(st);
  };
  if (window.__qaMask !== false) {
    if (document.readyState === 'loading' || !document.documentElement) document.addEventListener('DOMContentLoaded', start);
    else start();
  }
})();
"""


def host_allowed(url, allow):
    h = (urlparse(url).hostname or "").lower()
    return url.startswith(("data:", "about:", "blob:")) or any(h == a or h.endswith("." + a) for a in allow)


def refuse_reason(step, plan, url):
    """Why a step must not run, or None."""
    do = step.get("do")
    blob = " ".join(str(step.get(k, "")) for k in ("selector", "value", "text", "url"))
    local = (urlparse(url).hostname or "") in ("localhost", "127.0.0.1", "::1")
    if do in INPUT_STEPS and PAY.search(urlparse(url).path or "") and not (local and plan.get("payment_mock")):
        return "never-pay rule: no input on a checkout / payment page"
    if PAY.search(blob) and not (local and plan.get("payment_mock")):
        return "never-pay rule: payment / checkout step refused"
    if plan.get("live") and not plan.get("allow_input"):
        if do in INPUT_STEPS or (do == "click" and re.search(r"(?i)submit|type=.?submit|send|save|confirm|book|order", blob)):
            return "stop-before-input: live site and no owner OK (allow_input=false)"
    return None


def git_head(cwd=None):
    """The commit under test (None outside a git repo). Recorded at start and end of every scenario:
    if it moved during the run, the result is "mixed" and failures must be re-run on the final tip."""
    try:
        out = subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=cwd, capture_output=True, text=True, timeout=20)
        return out.stdout.strip() or None
    except (OSError, subprocess.SubprocessError):
        return None


def srt_time(sec):
    ms = int(round(sec * 1000))
    return f"{ms // 3600000:02d}:{ms // 60000 % 60:02d}:{ms // 1000 % 60:02d},{ms % 1000:03d}"


class PlanError(Exception):
    """A plan file that cannot be used; the message is a single readable line."""


def load_plan(path):
    """Read a plan JSON file; raise PlanError with the path (and line) on any problem."""
    try:
        with open(path, encoding="utf-8-sig") as fh:
            plan = json.load(fh)
    except FileNotFoundError:
        raise PlanError(f"plan file not found: {path}") from None
    except json.JSONDecodeError as exc:
        raise PlanError(f"plan file is not valid JSON: {path} (line {exc.lineno}, column {exc.colno}: {exc.msg})") from None
    except OSError as exc:
        raise PlanError(f"plan file unreadable: {path} ({exc.strerror})") from None
    if not isinstance(plan, dict) or not isinstance(plan.get("steps"), list) or not plan["steps"]:
        raise PlanError(f"plan file needs an object with a non-empty 'steps' list: {path}")
    return plan


def apply_target(plan, base_url=None, allow_hosts=None):
    """The command line wins over the plan: --base-url replaces plan.base_url and
    --allow-host replaces plan.allow_hosts. Says so when they differ, so a run can
    never silently test a different target than the one asked for."""
    plan = dict(plan)
    notes = []
    if base_url:
        old = (plan.get("base_url") or "").rstrip("/")
        if old and old != base_url.rstrip("/"):
            notes.append(f"base_url override: plan says {old}, running against {base_url.rstrip('/')}")
        plan["base_url"] = base_url
    if allow_hosts:
        plan["allow_hosts"] = list(allow_hosts)
    plan["_target_notes"] = notes
    return plan


def run(plan, out, narrate=False, browser_name="chromium", headed=False, total_timeout=900, step_timeout=15, video_cfg=None):
    """video_cfg: settings from video_trim.settings(); None means the defaults."""
    from playwright.sync_api import sync_playwright

    os.makedirs(out, exist_ok=True)
    raw_dir = os.path.join(out, "video-raw")
    shutil.rmtree(raw_dir, ignore_errors=True)
    allow = [h.lower() for h in plan.get("allow_hosts", ["127.0.0.1", "localhost"])]
    base = plan.get("base_url", "")
    w, h = plan.get("viewport", [1280, 720])

    clips = {}
    narration_note = None
    if narrate:  # synthesize first: no pauses in the recording, and a failed voice never blocks the test
        import tts
        missed = []
        for s in plan["steps"]:
            if s.get("say"):
                try:
                    p, d, _ = tts.speak(s["say"])
                    clips[s["say"]] = (p, d)
                except RuntimeError as exc:
                    missed.append(str(exc).splitlines()[0][:120])
        if missed:
            narration_note = f"{len(missed)} narration line(s) not synthesized (no voice for them): {missed[0]}"
            print("[record]", narration_note)
        elif not clips:
            narration_note = "no 'say' lines in the plan, so there is no voice"
    else:
        narration_note = "narration off (--narrate not given)"
    for n in plan.get("_target_notes", []):
        print("[record]", n)

    results, blocked, captions, shots, slow = [], [], [], [], []  # slow: typing / wait windows, dead time even when pixels move
    t_start = time.time()
    head_start = git_head(plan.get("repo"))
    with sync_playwright() as p:
        bt = getattr(p, browser_name)
        browser = bt.launch(headless=not headed)
        ctx = browser.new_context(viewport={"width": w, "height": h}, record_video_dir=raw_dir,
                                  record_video_size={"width": w, "height": h})
        ctx.tracing.start(screenshots=True, snapshots=True)
        ctx.add_init_script(CAPTION_JS)

        def guard(route):
            if host_allowed(route.request.url, allow):
                return route.continue_()
            blocked.append(urlparse(route.request.url).hostname)
            return route.abort()

        ctx.route("**/*", guard)
        page = ctx.new_page()
        page.set_default_timeout(step_timeout * 1000)
        console, network = [], []
        page.on("console", lambda m: console.append({"type": m.type, "text": m.text[:300]}) if m.type in ("error", "warning") else None)
        page.on("pageerror", lambda e: console.append({"type": "pageerror", "text": str(e)[:300]}))
        page.on("response", lambda r: network.append({"status": r.status, "url": r.url[:200]}) if r.status >= 400 else None)
        page.on("requestfailed", lambda r: network.append({"status": "failed", "url": r.url[:200], "error": (r.failure or "")[:120]}))
        t0 = time.time()
        current = {"text": ""}

        def caption(text, kind=""):
            current["text"] = text
            try:
                page.evaluate("([t,k]) => window.__qaCaption && window.__qaCaption(t,k)", [text, kind])
            except Exception:  # noqa: BLE001
                pass

        stop = None
        for i, s in enumerate(plan["steps"]):
            if time.time() - t_start > total_timeout:
                stop = f"total timeout {total_timeout}s reached"
                break
            do = s.get("do")
            url = urljoin(base, s.get("url", "")) if do == "goto" else page.url or base
            why = refuse_reason(s, plan, url if do == "goto" else (page.url or base))
            if why:
                stop = why
                caption(f"STOPPED before this step: {why}", "FAIL")
                page.wait_for_timeout(2500)
                results.append({"id": s.get("case", f"step-{i + 1}"), "title": s.get("say", do), "result": "BLOCKED",
                                "evidence": "", "note": why})
                break
            say = s.get("say")
            if say:
                start = time.time() - t0
                caption(say)
                hold = clips.get(say, (None, 0))[1]
                captions.append((start, say))
            t_step = time.time() - t0
            try:
                if do == "goto":
                    page.goto(url, wait_until="domcontentloaded")
                    if current["text"]:
                        caption(current["text"])
                elif do == "click":
                    page.click(s["selector"])
                elif do == "fill":
                    page.fill(s["selector"], s.get("value", ""))
                elif do == "type":
                    page.type(s["selector"], s.get("value", ""), delay=s.get("delay", 60))
                elif do == "select":
                    page.select_option(s["selector"], s.get("value"))
                elif do == "check":
                    page.check(s["selector"])
                elif do == "press":
                    page.press(s.get("selector", "body"), s["key"])
                elif do == "wait":
                    page.wait_for_timeout(min(int(s.get("ms", 1000)), step_timeout * 1000))
                elif do == "screenshot":
                    path = os.path.join(out, f"{len(shots) + 1:02d}-{s.get('name', 'shot')}.png")
                    page.screenshot(path=path)
                    shots.append(path)
                elif do in ("expect_text", "expect_visible", "expect_url"):
                    if do == "expect_text":
                        page.get_by_text(s["text"]).first.wait_for(state="visible")
                    elif do == "expect_visible":
                        page.wait_for_selector(s["selector"], state="visible")
                    else:
                        page.wait_for_url(re.compile(s["pattern"]))
                    path = os.path.join(out, f"{len(shots) + 1:02d}-{s.get('case', 'check')}-pass.png")
                    caption(f"PASS {s.get('case', '')}: {say or s.get('text') or s.get('selector') or s.get('pattern')}", "PASS")
                    page.screenshot(path=path)
                    shots.append(path)
                    results.append({"id": s.get("case", f"step-{i + 1}"), "title": say or do, "result": "PASS",
                                    "evidence": os.path.basename(path)})
                else:
                    raise ValueError(f"unknown step {do!r}")
                if do in ("type", "wait"):
                    slow.append((t_step, time.time() - t0))
            except Exception as exc:  # noqa: BLE001
                path = os.path.join(out, f"{len(shots) + 1:02d}-{s.get('case', 'step')}-fail.png")
                msg = str(exc).splitlines()[0][:160]
                caption(f"FAIL {s.get('case', f'step {i + 1}')}: {msg}", "FAIL")
                try:
                    page.screenshot(path=path)
                    shots.append(path)
                except Exception:  # noqa: BLE001
                    pass
                results.append({"id": s.get("case", f"step-{i + 1}"), "title": say or do, "result": "FAIL",
                                "evidence": os.path.basename(path), "note": msg})
                if do in ("type", "wait"):
                    slow.append((t_step, time.time() - t0))
                if s.get("case") is None or s.get("stop_on_fail", True):
                    stop = f"step {i + 1} failed"
                    page.wait_for_timeout(1500)
                    break
            if say:
                page.wait_for_timeout(int(max(hold, 1.2) * 1000) + 250)
        page.wait_for_timeout(800)
        ctx.tracing.stop(path=os.path.join(out, "trace.zip"))
        video = page.video
        ctx.close()  # the video file is only complete after the context closes
        raw = video.path() if video else None
        browser.close()

    # planned cases that never ran are NOT CHECKED, not silently dropped
    planned = [s["case"] for s in plan["steps"] if s.get("case")]
    counts, rows = report.count(results, planned)
    srt = os.path.join(out, "captions.srt")
    with open(srt, "w", encoding="utf-8") as fh:
        for n, (start, text) in enumerate(captions, 1):
            end = start + max(clips.get(text, (None, 2.5))[1], 1.2) + 0.25
            fh.write(f"{n}\n{srt_time(start)} --> {srt_time(end)}\n{text}\n\n")
    mp4 = None
    if raw and shutil.which("ffmpeg"):
        mp4 = os.path.join(out, plan.get("name", "qa-run").replace(" ", "-") + ".mp4")
        args = ["ffmpeg", "-y", "-v", "error", "-i", raw]
        used = [(start, clips[text][0]) for start, text in captions if text in clips]
        for _, clip in used:
            args += ["-i", clip]
        if used:
            mix = "".join(f"[{k + 1}:a]adelay={int(st * 1000)}:all=1[a{k}];" for k, (st, _) in enumerate(used))
            mix += "".join(f"[a{k}]" for k in range(len(used))) + f"amix=inputs={len(used)}:normalize=0[aout]"
            args += ["-filter_complex", mix, "-map", "0:v", "-map", "[aout]", "-c:a", "aac", "-b:a", "128k"]
        args += ["-c:v", "libx264", "-pix_fmt", "yuv420p", "-preset", "medium", "-crf", "23", "-movflags", "+faststart", mp4]
        subprocess.run(args, check=True, timeout=600)
    video_len, trim_note = None, None
    if mp4:  # a failed or slow trim keeps the untrimmed video and never changes a result
        try:
            video_len = video_trim.trim(mp4, srt, video_cfg or video_trim.settings(), plan.get("video_type"), slow=slow, timeout=240)
            trim_note = video_trim.describe(video_len)
            print("[record]", trim_note)
        except (video_trim.ConfigError, RuntimeError, subprocess.SubprocessError, OSError) as exc:
            trim_note = f"video not trimmed: {str(exc).splitlines()[0][:160] if str(exc) else type(exc).__name__}"
            print("[record]", trim_note)
    summary = {"name": plan.get("name"), "summary": report.summary(counts), "counts": counts, "stopped": stop,
               "blocked_hosts": sorted(set(b for b in blocked if b)), "video": os.path.basename(mp4) if mp4 else (raw and os.path.relpath(raw, out)),
               "trace": "trace.zip", "captions": "captions.srt", "narrated": bool(clips), "narration_note": narration_note,
               "base_url": base, "target_notes": plan.get("_target_notes", []), "screenshots": [os.path.basename(x) for x in shots],
               "console": console, "network": network, "results": rows, "elapsed_sec": round(time.time() - t_start, 1),
               "browser": browser_name, "finished_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
               "head_start": head_start, "head_end": git_head(plan.get("repo")),
               "video_original": (video_len or {}).get("original"), "video_seconds": video_len, "video_note": trim_note}
    summary["mixed"] = bool(head_start and summary["head_end"] and head_start != summary["head_end"])
    with open(os.path.join(out, "results.json"), "w", encoding="utf-8") as fh:
        json.dump(summary, fh, indent=1)
    with open(os.path.join(out, "QA-REPORT.md"), "w", encoding="utf-8") as fh:
        fh.write(report.to_markdown(rows, counts, f"QA run: {plan.get('name', '')}"))
        if trim_note:
            fh.write(f"\nVideo length: {trim_note}\n")
    return summary


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("plan")
    ap.add_argument("--out", required=True)
    ap.add_argument("--narrate", action="store_true")
    ap.add_argument("--browser", default="chromium", choices=("chromium", "firefox", "webkit"))
    ap.add_argument("--headed", action="store_true")
    ap.add_argument("--total-timeout", type=int, default=900)
    ap.add_argument("--step-timeout", type=int, default=15)
    ap.add_argument("--base-url", help="overrides the plan's base_url (the target you name wins)")
    ap.add_argument("--allow-host", action="append", default=[], help="overrides the plan's allow_hosts (repeatable)")
    ap.add_argument("--config", default=os.environ.get("SMEKIT_QA_CONFIG", "qa.config.yaml"),
                    help="qa.config.yaml; only its video section is read here")
    a = ap.parse_args(argv)
    try:
        plan = apply_target(load_plan(a.plan), a.base_url, a.allow_host)
        video_cfg = video_trim.settings(video_trim.load_video_section(a.config))
        video_trim.cap_for(video_cfg, plan.get("video_type"))  # an unknown plan video_type fails here, before the run
    except (PlanError, video_trim.ConfigError) as exc:
        print(f"ERROR: {exc}")
        return 2
    s = run(plan, a.out, a.narrate, a.browser, a.headed, a.total_timeout, a.step_timeout, video_cfg)
    print(s["summary"], "| stopped:", s["stopped"] or "no", "| blocked hosts:", s["blocked_hosts"] or "none",
          "| video:", s["video"])
    return 0 if s["counts"]["FAIL"] == 0 and s["counts"]["BLOCKED"] == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
