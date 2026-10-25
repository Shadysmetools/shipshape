#!/usr/bin/env python3
"""Build a narrated explainer / evidence video from screenshots and text cards.

    python scripts/slides_video.py scenes.json --out out.mp4 [--voice <profile> | --voice en-US-AndrewNeural]

--voice is a voice profile from narrator.voices in qa.config.yaml (default: narrator.default_voice);
any other value is used as an edge-tts voice name, as before.

Use it when the evidence is screenshots (for example from a signed-in Chrome via
Chrome DevTools MCP, or Odoo screens) rather than a live recording. Pipeline:
scenes -> 1920x1080 HTML slides rendered by Playwright -> edge-tts narration
per line -> one clip per line -> one clip per scene -> crossfades (ffmpeg xfade)
-> burned-in captions + a matching .srt from the same timeline.

Each scene is labelled LIVE, SIMULATED, REGRESSION or ILLUSTRATION so nobody
mistakes a simulated or mocked step for a live one.

scenes.json:
{"title": "Run 3 evidence", "scenes": [
  {"kind": "card", "kicker": "QA round 3", "heading": "Sign-up flow", "body": ["Two cases", "Test data only"],
   "lines": ["Round three covers the sign-up flow."]},
  {"kind": "shot", "image": "shots/01.png", "kicker": "Step 1", "heading": "The form", "tag": "LIVE",
   "lines": ["The form opens with every field empty."]},
  {"kind": "terminal", "heading": "Unit tests", "text": "26 passed in 4.1s", "tag": "REGRESSION",
   "lines": ["The unit suite passes: twenty six tests, none failed."]}]}
"""
from __future__ import annotations

import argparse
import html
import json
import os
import pathlib
import re
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import narrator  # noqa: E402
import tts  # noqa: E402

W, H, XF = 1920, 1080, 0.6
TAGS = {"LIVE": "live", "SIMULATED": "sim", "REGRESSION": "reg", "ILLUSTRATION": "ill"}
CSS = """
*{box-sizing:border-box}body{margin:0;width:1920px;height:1080px;font-family:'Segoe UI',system-ui,Arial,sans-serif;background:#f4f6f8;color:#1d2733;overflow:hidden}
.top{position:absolute;left:0;right:0;top:0;height:78px;background:#fff;border-bottom:1px solid #dde2e8;display:flex;align-items:center;padding:0 44px;gap:18px}
.k{color:#3b5bdb;font-weight:700;letter-spacing:1.4px;text-transform:uppercase;font-size:19px}.t{font-size:29px;font-weight:650}
.tag{padding:5px 14px;border-radius:16px;font-size:18px;font-weight:700;margin-left:auto}
.live{background:#dff3e6;color:#17663a}.sim{background:#fdecd8;color:#8a4b12}.reg{background:#e6ecfa;color:#2c4a8a}.ill{background:#eee;color:#444}
.shot{position:absolute;left:44px;right:44px;top:98px;bottom:172px;display:flex;align-items:center;justify-content:center}
.shot img{max-width:100%;max-height:100%;border:1px solid #cfd6de;border-radius:8px;box-shadow:0 4px 18px rgba(0,0,0,.10)}
.term{position:absolute;left:90px;right:90px;top:120px;bottom:190px;background:#0f1720;color:#d6e2ee;border-radius:12px;padding:34px 40px;
 font:28px/1.45 Consolas,'Cascadia Mono',Menlo,monospace;white-space:pre-wrap;overflow:hidden}
.cap{position:absolute;left:0;right:0;bottom:0;height:150px;background:#1d2733;color:#fff;font-size:34px;line-height:1.35;padding:18px 110px;
 display:flex;align-items:center;justify-content:center;text-align:center}
.card{position:absolute;left:0;right:0;top:0;bottom:150px;padding:120px 150px}
.card h1{font-size:68px;margin:0 0 26px}.card p{font-size:34px;color:#4a5562;line-height:1.5;margin:0 0 14px}
"""


def scene_html(sc, base):
    tag = sc.get("tag", "")
    tag_html = f'<span class="tag {TAGS.get(tag.split()[0] if tag else "", "ill")}">{html.escape(tag)}</span>' if tag else ""
    top = f'<div class="top"><span class="k">{html.escape(sc.get("kicker", ""))}</span><span class="t">{html.escape(sc.get("heading", ""))}</span>{tag_html}</div>'
    kind = sc.get("kind", "card")
    if kind == "shot":
        img = (base / sc["image"]).resolve().as_uri()
        return top + f'<div class="shot"><img src="{img}"></div>'
    if kind == "terminal":
        return top + f'<div class="term">{html.escape(sc.get("text", ""))}</div>'
    body = "".join(f"<p>{html.escape(p)}</p>" for p in sc.get("body", []))
    return f'<div class="card"><div class="k">{html.escape(sc.get("kicker", ""))}</div><h1>{html.escape(sc.get("heading", ""))}</h1>{body}{tag_html}</div>'


def srt_time(x):
    ms = int(round(x * 1000))
    return f"{ms // 3600000:02d}:{ms // 60000 % 60:02d}:{ms // 1000 % 60:02d},{ms % 1000:03d}"


def run(cmd):
    subprocess.run(cmd, check=True, timeout=900)


def voice_for(arg, cfg):
    """--voice: a configured profile name, or a raw edge-tts voice name such as en-US-AndrewNeural (as before);
    None = the project default. Anything else is an unknown profile (VoiceError)."""
    if arg and arg not in narrator.profiles(cfg) and re.match(r"^[a-z]{2,3}-[A-Z]{2,4}-\w+Neural$", arg):
        return {"profile": None, "provider": "edge", "voice": arg, "lang": "en", "rate": "-5%"}
    return narrator.resolve(arg, cfg)


def build(spec, out, voice=None, workdir=None, base=None):
    """voice: a narrator.resolve() result, an edge-tts voice name, or None (the project default)."""
    from playwright.sync_api import sync_playwright

    if not isinstance(voice, dict):
        voice = voice_for(voice, narrator.load_config())

    out = pathlib.Path(out)
    base = pathlib.Path(base or ".")
    work = pathlib.Path(workdir) if workdir else out.parent / (out.stem + "-build")
    for sub in ("slides", "clips"):
        (work / sub).mkdir(parents=True, exist_ok=True)
    items = []  # (index, scene_index, line, html)
    for si, sc in enumerate(spec["scenes"]):
        for line in sc["lines"]:
            items.append((len(items), si, line, scene_html(sc, base)))
    audio = {i: narrator.speak(line, voice) for i, _, line, _ in items}  # (mp3, seconds, fallback note)
    notes = sorted({a[2] for a in audio.values() if a[2]})
    with sync_playwright() as p:
        br = p.chromium.launch()
        pg = br.new_page(viewport={"width": W, "height": H})
        for i, _si, line, vis in items:
            f = work / "slides" / f"{i:03d}.html"
            f.write_text(f'<!doctype html><meta charset="utf-8"><style>{CSS}</style>{vis}<div class="cap">{html.escape(line)}</div>', encoding="utf-8")
            pg.goto(f.as_uri())
            pg.wait_for_timeout(120)
            pg.screenshot(path=str(work / "slides" / f"{i:03d}.png"))
        br.close()
    scenes, srt, t_scene = [], [], 0.0
    for si in range(len(spec["scenes"])):
        lines = [it for it in items if it[1] == si]
        parts, t_in = [], 0.0
        for k, (i, _s, line, _v) in enumerate(lines):
            mp3, dur, _ = audio[i]
            lead = XF if (k == 0 and si > 0) else 0.0
            d = dur + 0.35 + lead + (0.5 if k == len(lines) - 1 else 0)
            clip = work / "clips" / f"l{i:03d}.mp4"
            run(["ffmpeg", "-y", "-v", "error", "-loop", "1", "-framerate", "30", "-i", str(work / "slides" / f"{i:03d}.png"), "-i", mp3,
                 "-c:v", "libx264", "-tune", "stillimage", "-pix_fmt", "yuv420p", "-r", "30", "-c:a", "aac", "-b:a", "128k", "-ar", "48000", "-ac", "2",
                 "-af", f"adelay={int(lead * 1000)}:all=1,apad", "-t", f"{d:.3f}", str(clip)])
            parts.append(clip)
            start = t_scene + t_in + lead
            srt.append((start, start + dur + 0.15, line))
            t_in += d
        lst = work / "clips" / f"s{si:02d}.txt"
        lst.write_text("\n".join(f"file '{c.as_posix()}'" for c in parts), encoding="utf-8")
        sc = work / "clips" / f"s{si:02d}.mp4"
        run(["ffmpeg", "-y", "-v", "error", "-f", "concat", "-safe", "0", "-i", str(lst), "-c", "copy", str(sc)])
        real = tts.duration(str(sc))
        scenes.append((sc, real))
        t_scene += real - XF
    args = ["ffmpeg", "-y", "-v", "error"]
    for sc, _ in scenes:
        args += ["-i", str(sc)]
    if len(scenes) > 1:
        fc, vprev, aprev, off = [], "0:v", "0:a", 0.0
        for k in range(1, len(scenes)):
            off += scenes[k - 1][1] - XF
            fc.append(f"[{vprev}][{k}:v]xfade=transition=fade:duration={XF}:offset={off:.3f}[v{k}]")
            fc.append(f"[{aprev}][{k}:a]acrossfade=d={XF}:c1=tri:c2=tri[a{k}]")
            vprev, aprev = f"v{k}", f"a{k}"
        args += ["-filter_complex", ";".join(fc), "-map", f"[{vprev}]", "-map", f"[{aprev}]"]
    args += ["-c:v", "libx264", "-preset", "medium", "-crf", "23", "-pix_fmt", "yuv420p", "-r", "30", "-c:a", "aac", "-b:a", "128k",
             "-movflags", "+faststart", str(out)]
    run(args)
    out.with_suffix(".srt").write_text("\n".join(f"{n + 1}\n{srt_time(a)} --> {srt_time(b)}\n{t}\n" for n, (a, b, t) in enumerate(srt)), encoding="utf-8")
    return {"scenes": len(scenes), "lines": len(items), "duration": tts.duration(str(out)), "srt": str(out.with_suffix(".srt")),
            "voice": voice.get("profile"), "narration_note": "; ".join(notes) or None}


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("scenes")
    ap.add_argument("--out", required=True)
    ap.add_argument("--voice", help="voice profile from narrator.voices (or an edge-tts voice name)")
    ap.add_argument("--config", default="qa.config.yaml")
    a = ap.parse_args(argv)
    try:
        voice = voice_for(a.voice, narrator.load_config(a.config))
    except narrator.VoiceError as exc:
        print(f"ERROR: {exc}")
        return 2
    spec = json.load(open(a.scenes, encoding="utf-8"))
    info = build(spec, a.out, voice, base=os.path.dirname(os.path.abspath(a.scenes)))
    print(f"scenes={info['scenes']} lines={info['lines']} duration={info['duration']:.1f}s srt={info['srt']}"
          + (f" voice-note={info['narration_note']}" if info["narration_note"] else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main())
