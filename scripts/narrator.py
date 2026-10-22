#!/usr/bin/env python3
"""Voice narrator: turns steps and results into natural speech + .srt captions,
and mixes the narration under a video (the video's own audio is ducked while
the narrator speaks).

    python scripts/narrator.py report <run_dir> [--lang en|ar] [--out summary.mp3]   # spoken summary of a run
    python scripts/narrator.py mix <video.mp4> <lines.json> --out narrated.mp4         # lines: [{"t": 1.5, "text": "..."}]
    python scripts/narrator.py voices                                                 # the configured voices

Providers (pick with SMEKIT_TTS_PROVIDER or qa.config.yaml narrator.provider):
  edge        default, free, no key: Microsoft neural voices through edge-tts
  openai      needs OPENAI_API_KEY (model gpt-4o-mini-tts or tts-1)
  elevenlabs  needs ELEVENLABS_API_KEY and a voice id
Keys come from env vars only. Voices per language are in VOICES and can be
overridden per project (narrator.voice, narrator.rate, narrator.lang).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import tts  # noqa: E402

VOICES = {
    "en": {"edge": "en-US-AndrewNeural", "edge_alt": "en-US-AvaNeural", "openai": "alloy"},
    "ar": {"edge": "ar-EG-ShakirNeural", "edge_alt": "ar-EG-SalmaNeural", "openai": "alloy"},
}
PHRASES = {
    "en": {"intro": "QA run for: {goal}.", "result": "Result: {summary}.", "verdict": "Verdict: {verdict}.",
           "fail": "Failed: {title}.", "bugs": "{n} open bug(s) waiting.", "none": "No failures.",
           "security": "{n} security finding(s); details are in the private report."},
    "ar": {"intro": "تشغيل اختبار الجودة لهدف: {goal}.", "result": "النتيجة: {summary}.", "verdict": "الحكم: {verdict}.",
           "fail": "فشل: {title}.", "bugs": "{n} خطأ مفتوح بانتظار الإصلاح.", "none": "لا توجد حالات فشل.",
           "security": "{n} ملاحظة أمنية، والتفاصيل في التقرير الخاص."},
}


def provider():
    return os.environ.get("SMEKIT_TTS_PROVIDER", "edge")


def say(text, lang="en", voice=None, rate="-5%", prov=None):
    """Return (mp3 path, seconds). Falls back to edge-tts if a paid provider has no key."""
    prov = prov or provider()
    if prov == "openai" and os.environ.get("OPENAI_API_KEY"):
        return _http_tts(text, "openai", voice or VOICES[lang]["openai"])
    if prov == "elevenlabs" and os.environ.get("ELEVENLABS_API_KEY") and (voice or os.environ.get("ELEVENLABS_VOICE_ID")):
        return _http_tts(text, "elevenlabs", voice or os.environ["ELEVENLABS_VOICE_ID"])
    p, d, _ = tts.speak(text, voice or VOICES.get(lang, VOICES["en"])["edge"], rate)
    return p, d


def _http_tts(text, prov, voice, urlopen=urllib.request.urlopen):
    os.makedirs(tts.CACHE, exist_ok=True)
    path = os.path.join(tts.CACHE, hashlib.sha1(f"{prov}\n{voice}\n{text}".encode()).hexdigest() + ".mp3")
    if os.path.exists(path) and tts.duration(path):
        return path, tts.duration(path)
    if prov == "openai":
        req = urllib.request.Request("https://api.openai.com/v1/audio/speech", method="POST",
                                     data=json.dumps({"model": os.environ.get("OPENAI_TTS_MODEL", "gpt-4o-mini-tts"), "voice": voice, "input": text}).encode(),
                                     headers={"Authorization": f"Bearer {os.environ['OPENAI_API_KEY']}", "Content-Type": "application/json"})
    else:
        req = urllib.request.Request(f"https://api.elevenlabs.io/v1/text-to-speech/{voice}", method="POST",
                                     data=json.dumps({"text": text, "model_id": os.environ.get("ELEVENLABS_MODEL", "eleven_multilingual_v2")}).encode(),
                                     headers={"xi-api-key": os.environ["ELEVENLABS_API_KEY"], "Content-Type": "application/json"})
    tmp = path + ".tmp.mp3"
    with urlopen(req, timeout=120) as r, open(tmp, "wb") as fh:
        fh.write(r.read())
    d = tts.duration(tmp)
    if not d:
        os.remove(tmp)
        raise RuntimeError(f"{prov} returned unreadable audio")
    os.replace(tmp, path)
    return path, d


def report_lines(run_dir, lang="en"):
    """Plain-language sentences summarising a run (for non-technical listeners)."""
    ph = PHRASES.get(lang, PHRASES["en"])
    led_p = os.path.join(run_dir, "ledger.json")
    lines = []
    if os.path.exists(led_p):
        led = json.load(open(led_p, encoding="utf-8"))
        last = led["rounds"][-1] if led.get("rounds") else None
        lines.append(ph["intro"].format(goal=led.get("goal", "")))
        if last:
            lines.append(ph["result"].format(summary=last["summary"]))
            fails = [r for run in last["runs"] for r in run["results"] if r["result"] == "FAIL"]
            lines += [ph["fail"].format(title=r.get("title") or r["id"]) for r in fails[:5]] or [ph["none"]]
        open_bugs = [b for b in led.get("bugs", []) if b["status"] in ("suspected", "verified", "filed")]
        if open_bugs:
            lines.append(ph["bugs"].format(n=len(open_bugs)))
        if led.get("security", {}).get("count"):
            lines.append(ph["security"].format(n=led["security"]["count"]))
        lines.append(ph["verdict"].format(verdict=led.get("status", "")))
    else:
        res = json.load(open(os.path.join(run_dir, "results.json"), encoding="utf-8"))
        lines.append(ph["intro"].format(goal=res.get("name", "")))
        lines.append(ph["result"].format(summary=res.get("summary", "")))
    return lines


def srt(entries, path):
    def ts(x):
        ms = int(round(x * 1000))
        return f"{ms // 3600000:02d}:{ms // 60000 % 60:02d}:{ms // 1000 % 60:02d},{ms % 1000:03d}"
    with open(path, "w", encoding="utf-8") as fh:
        for n, (a, b, t) in enumerate(entries, 1):
            fh.write(f"{n}\n{ts(a)} --> {ts(b)}\n{t}\n\n")


def narrate_lines(lines, out_mp3, lang="en", gap=0.4):
    """Speak lines back to back into one mp3 + srt. Returns the srt entries."""
    clips, t, entries = [], 0.0, []
    for line in lines:
        p, d = say(line, lang)
        clips.append(p)
        entries.append((t, t + d, line))
        t += d + gap
    lst = out_mp3 + ".txt"
    with open(lst, "w", encoding="utf-8") as fh:
        fh.write("\n".join(f"file '{os.path.abspath(c).replace(os.sep, '/')}'" for c in clips))
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "concat", "-safe", "0", "-i", lst, "-c:a", "libmp3lame", "-q:a", "4", out_mp3], check=True, timeout=600)
    os.remove(lst)
    srt(entries, os.path.splitext(out_mp3)[0] + ".srt")
    return entries


def has_audio(video):
    out = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "a", "-show_entries", "stream=index", "-of", "csv=p=0", video],
                         capture_output=True, text=True, timeout=60).stdout.strip()
    return bool(out)


def mix_cmd(video, clips, out, duck=True, video_has_audio=None):
    """ffmpeg command: narration clips placed at their times; the video's own audio
    is ducked under the narration (sidechaincompress) when it has an audio track."""
    vha = has_audio(video) if video_has_audio is None else video_has_audio
    args = ["ffmpeg", "-y", "-v", "error", "-i", video]
    for _t, p in clips:
        args += ["-i", p]
    parts = [f"[{k + 1}:a]adelay={int(t * 1000)}:all=1[n{k}]" for k, (t, _p) in enumerate(clips)]
    parts.append("".join(f"[n{k}]" for k in range(len(clips))) + f"amix=inputs={len(clips)}:normalize=0[narr]")
    if vha and duck:
        parts.append("[narr]asplit=2[narr1][sc]")
        parts.append("[0:a][sc]sidechaincompress=threshold=0.03:ratio=8:attack=20:release=400[duck]")
        parts.append("[duck][narr1]amix=inputs=2:normalize=0[aout]")
        amap = "[aout]"
    else:
        amap = "[narr]"
    args += ["-filter_complex", ";".join(parts), "-map", "0:v", "-map", amap, "-c:v", "copy", "-c:a", "aac", "-b:a", "128k", "-shortest", out]
    return args


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("cmd", choices=("report", "mix", "voices"))
    ap.add_argument("target", nargs="?")
    ap.add_argument("lines", nargs="?")
    ap.add_argument("--lang", default="en", choices=("en", "ar"))
    ap.add_argument("--out")
    a = ap.parse_args(argv)
    sys.stdout.reconfigure(encoding="utf-8")
    if a.cmd == "voices":
        print(json.dumps({"provider": provider(), "voices": VOICES}, ensure_ascii=False, indent=1))
        return 0
    if a.cmd == "report":
        out = a.out or os.path.join(a.target, f"summary-{a.lang}.mp3")
        entries = narrate_lines(report_lines(a.target, a.lang), out, a.lang)
        print(f"wrote {out} ({entries[-1][1]:.1f}s) and {os.path.splitext(out)[0]}.srt")
        return 0
    lines = json.load(open(a.lines, encoding="utf-8"))
    clips = [(x["t"], say(x["text"], a.lang)[0]) for x in lines]
    out = a.out or os.path.splitext(a.target)[0] + "-narrated.mp4"
    subprocess.run(mix_cmd(a.target, clips, out), check=True, timeout=900)
    srt([(x["t"], x["t"] + 3, x["text"]) for x in lines], os.path.splitext(out)[0] + ".srt")
    print("wrote", out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
