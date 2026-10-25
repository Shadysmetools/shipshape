#!/usr/bin/env python3
"""Voice narrator: turns steps and results into natural speech + .srt captions,
and mixes the narration under a video (the video's own audio is ducked while
the narrator speaks).

    python scripts/narrator.py report <run_dir> [--lang en|ar] [--voice <profile>] [--out summary.mp3]  # spoken summary of a run
    python scripts/narrator.py mix <video.mp4> <lines.json> [--voice <profile>] --out narrated.mp4      # lines: [{"t": 1.5, "text": "..."}]
    python scripts/narrator.py voices [--config qa.config.yaml]                                         # the configured voice profiles

Voice profiles (qa.config.yaml), picked with --voice <profile> or narrator.default_voice:

    narrator:
      default_voice: narrator
      voices:
        narrator: {provider: edge, voice: en-US-AndrewNeural, lang: en}
        sara: {provider: elevenlabs, voice: {env: ELEVENLABS_VOICE_ID_SARA}, lang: ar}

Providers:
  edge        default, free, no key: Microsoft neural voices through edge-tts
  openai      needs OPENAI_API_KEY (model gpt-4o-mini-tts or tts-1)
  elevenlabs  needs ELEVENLABS_API_KEY and a voice id (literal, or {env: NAME} looked up through keys.py)
API keys come only through keys.py (env var, keychain or the user store; asked for once when missing).
If a paid provider refuses (no key, HTTP 402 "paid plan required", offline), the line is spoken by the free
edge voice for the profile's language, with one warning line; the reason is kept as the narration note.
Without profiles: SMEKIT_TTS_PROVIDER or narrator.provider, and ELEVENLABS_VOICE_ID, as before.
Only use a cloned voice whose owner agreed to it being used.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import urllib.error
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import keys  # noqa: E402
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


PROVIDERS = ("edge", "openai", "elevenlabs")
API_KEY = {"openai": "OPENAI_API_KEY", "elevenlabs": "ELEVENLABS_API_KEY"}
_REFUSED = {}  # (provider, voice id) -> note: a refused paid voice is not called again in this process


class VoiceError(Exception):
    """A --voice / narrator.voices problem the user must fix; the message is one readable line."""


def provider(cfg=None):
    return (os.environ.get("SMEKIT_TTS_PROVIDER") or ((cfg or {}).get("narrator") or {}).get("provider") or "edge").lower()


def load_config(path="qa.config.yaml"):
    """The project config, or {} when there is none. A broken file is a VoiceError (one line)."""
    if not path or not os.path.exists(path):
        return {}
    import notify
    try:
        return notify.load_config(path)
    except notify.ConfigError as exc:
        raise VoiceError(str(exc)) from None


def profiles(cfg):
    voices = ((cfg or {}).get("narrator") or {}).get("voices") or {}
    if not isinstance(voices, dict):
        raise VoiceError("config error at narrator.voices: expected a mapping of profile names")
    return voices


def resolve(name=None, cfg=None, lang=None):
    """The voice to narrate with: --voice beats narrator.default_voice, which beats the legacy settings.
    Returns {"profile", "provider", "voice", "lang", "rate"}. The voice id may still be an {env: NAME} spec."""
    nar = (cfg or {}).get("narrator") or {}
    voices = profiles(cfg)
    name = name or nar.get("default_voice")
    rate = str(nar.get("rate") or "-5%")
    if not name:
        prov = provider(cfg)
        lang = lang or nar.get("lang") or "en"
        return {"profile": None, "provider": prov, "voice": (nar.get("voice") or os.environ.get("SMEKIT_VOICE")) if prov == "edge" else None, "lang": lang, "rate": rate}
    if name not in voices:
        known = ", ".join(sorted(voices)) or "none (add narrator.voices to qa.config.yaml)"
        raise VoiceError(f"unknown voice profile {name!r}; profiles: {known}")
    spec = voices[name]
    if isinstance(spec, str):
        spec = {"provider": "edge", "voice": spec}
    if not isinstance(spec, dict):
        raise VoiceError(f"config error at narrator.voices.{name}: expected {{provider, voice, lang}}")
    prov = str(spec.get("provider") or "edge").lower()
    if prov not in PROVIDERS:
        raise VoiceError(f"config error at narrator.voices.{name}.provider: expected one of {', '.join(PROVIDERS)}, got {prov!r}")
    vid = spec.get("voice")
    if isinstance(vid, dict) and not (len(vid) == 1 and isinstance(vid.get("env"), str)):
        raise VoiceError(f"config error at narrator.voices.{name}.voice: expected a voice id or {{env: NAME}}")
    return {"profile": name, "provider": prov, "voice": vid, "lang": spec.get("lang") or lang or nar.get("lang") or "en",
            "rate": str(spec.get("rate") or rate)}


def _voice_id(v):
    """The provider's voice id for a resolved voice: literal, {env: NAME} through keys.py, or the defaults."""
    vid, label = v.get("voice"), v.get("profile") or v["provider"]
    if isinstance(vid, dict):
        return keys.get(vid["env"], f"ElevenLabs voice id for the voice profile '{label}'.")
    if vid:
        return str(vid)
    if v["provider"] == "openai":
        return VOICES.get(v["lang"], VOICES["en"])["openai"]
    if v["provider"] == "elevenlabs":
        return keys.get("ELEVENLABS_VOICE_ID", "Which ElevenLabs voice should narrate?")
    return None


def _refusal(prov, exc):
    if isinstance(exc, urllib.error.HTTPError):
        why = {402: "paid plan required", 401: "key not accepted", 403: "not allowed for this key",
               429: "rate limit or quota reached"}.get(exc.code, "refused")
        return f"{prov} refused: HTTP {exc.code} ({why})"
    if isinstance(exc, RuntimeError):
        return str(exc)
    return f"{prov} not reachable ({type(exc).__name__})"


_WARNED = set()


def _fallback(text, note, lang, rate):
    """Speak with the free edge voice for the language; warn once per reason."""
    edge = VOICES.get(lang, VOICES["en"])["edge"]
    note = f"{note}; spoken by the free edge voice {edge}"
    if note not in _WARNED:
        _WARNED.add(note)
        print(f"[narrator] {note}")
    p, d, _ = tts.speak(text, edge, rate)
    return p, d, note


def speak(text, v):
    """Speak one line with a resolved voice. Returns (mp3 path, seconds, note); note is None when the chosen
    voice was used, else why the free edge voice spoke instead. Raises RuntimeError only if edge fails too."""
    prov, lang = v["provider"], v.get("lang") or "en"
    rate = v.get("rate") or "-5%"
    if prov not in API_KEY:
        p, d, _ = tts.speak(text, v.get("voice") or VOICES.get(lang, VOICES["en"])["edge"], rate)
        return p, d, None
    label = f"voice profile '{v['profile']}'" if v.get("profile") else f"{prov} voice"
    if not keys.get(API_KEY[prov], f"Chosen narrator voice provider: {prov}."):
        return _fallback(text, f"{label}: no {API_KEY[prov]} (save it with keys.py set {API_KEY[prov]})", lang, rate)
    vid = _voice_id(v)
    if not vid:
        return _fallback(text, f"{label}: no {prov} voice id", lang, rate)
    if (prov, vid) not in _REFUSED:
        try:
            p, d = _http_tts(text, prov, vid)
            return p, d, None
        except (urllib.error.URLError, OSError, RuntimeError, ValueError) as exc:
            _REFUSED[(prov, vid)] = f"{label}: {_refusal(prov, exc)}"
    return _fallback(text, _REFUSED[(prov, vid)], lang, rate)


def say(text, lang="en", voice=None, rate="-5%", prov=None, profile=None, notes=None):
    """Return (mp3 path, seconds). profile: a resolve() result; otherwise the legacy provider/voice.
    A paid provider without a key or that refuses falls back to edge-tts; the reason goes into notes."""
    v = profile or {"profile": None, "provider": prov or provider(), "voice": voice, "lang": lang, "rate": rate}
    p, d, note = speak(text, v)
    if note and notes is not None and note not in notes:
        notes.append(note)
    return p, d


def _http_tts(text, prov, voice, urlopen=None):
    urlopen = urlopen or urllib.request.urlopen
    os.makedirs(tts.CACHE, exist_ok=True)
    path = os.path.join(tts.CACHE, hashlib.sha1(f"{prov}\n{voice}\n{text}".encode()).hexdigest() + ".mp3")
    if os.path.exists(path) and tts.duration(path):
        return path, tts.duration(path)
    if prov == "openai":
        req = urllib.request.Request("https://api.openai.com/v1/audio/speech", method="POST",
                                     data=json.dumps({"model": os.environ.get("OPENAI_TTS_MODEL", "gpt-4o-mini-tts"), "voice": voice, "input": text}).encode(),
                                     headers={"Authorization": f"Bearer {keys.lookup('OPENAI_API_KEY')}", "Content-Type": "application/json"})
    else:
        req = urllib.request.Request(f"https://api.elevenlabs.io/v1/text-to-speech/{voice}", method="POST",
                                     data=json.dumps({"text": text, "model_id": os.environ.get("ELEVENLABS_MODEL", "eleven_multilingual_v2")}).encode(),
                                     headers={"xi-api-key": keys.lookup("ELEVENLABS_API_KEY"), "Content-Type": "application/json"})
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


def narrate_lines(lines, out_mp3, lang="en", gap=0.4, profile=None, notes=None):
    """Speak lines back to back into one mp3 + srt. Returns the srt entries.
    If no voice can be made (offline, provider down) the .srt is still written,
    one warning is printed and the entries come back with estimated timings."""
    clips, t, entries, missed = [], 0.0, [], 0
    for line in lines:
        try:
            p, d = say(line, lang, profile=profile, notes=notes)
        except (RuntimeError, OSError) as exc:
            missed += 1
            d = max(2.0, 0.4 * len(line.split()))  # a reading-speed estimate keeps the captions usable
            if missed == 1:
                print(f"[narrator] no voice: {str(exc).splitlines()[0][:120]}; writing captions only")
            entries.append((t, t + d, line))
            t += d + gap
            continue
        clips.append(p)
        entries.append((t, t + d, line))
        t += d + gap
    if missed:
        srt(entries, os.path.splitext(out_mp3)[0] + ".srt")
        return entries
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


def schedule(starts, durations, gap=0.3):
    """Non-overlapping (start, end) for each clip: a line never starts before the previous one has
    finished (+ gap). One narrator at a time, however close together the steps ran."""
    out, end = [], 0.0
    for t, d in zip(starts, durations):
        t = max(float(t), end + gap if out else float(t))
        out.append((round(t, 3), round(t + float(d), 3)))
        end = t + float(d)
    return out


def mix_cmd(video, clips, out, duck=True, video_has_audio=None, pad=0.0):
    """ffmpeg command: narration clips placed at their times; the video's own audio is ducked under the
    narration (sidechaincompress) when it has an audio track. clips: (t, path) or (t, path, seconds); with
    seconds the clips are scheduled so they never overlap. pad: seconds of the last frame held at the end so
    the last line is not cut. The output always has exactly one audio stream."""
    if clips and all(len(c) == 3 for c in clips):
        clips = [(a, p) for (a, _b), (_t, p, _d) in zip(schedule([c[0] for c in clips], [c[2] for c in clips]), clips)]
    vha = has_audio(video) if video_has_audio is None else video_has_audio
    args = ["ffmpeg", "-y", "-v", "error", "-i", video]
    for _t, p in clips:
        args += ["-i", p]
    parts = [f"[{k + 1}:a]adelay={int(t * 1000)}:all=1[n{k}]" for k, (t, _p) in enumerate(clips)]
    parts.append("".join(f"[n{k}]" for k in range(len(clips))) + f"amix=inputs={len(clips)}:normalize=0[narr]")
    if vha and duck:
        parts.append("[narr]asplit=2[narr1][sc]")
        parts.append("[0:a][sc]sidechaincompress=threshold=0.03:ratio=8:attack=20:release=400[duck]")
        parts.append("[duck][narr1]amix=inputs=2:normalize=0:duration=longest[aout]")
        amap = "[aout]"
    else:
        amap = "[narr]"
    parts.append(f"{amap}apad[afull]")  # silence to the end: the video, not the narration, sets the length
    amap = "[afull]"
    if pad > 0:
        parts.append(f"[0:v]tpad=stop_mode=clone:stop_duration={pad:.2f}[vout]")
        vmap, vcodec = "[vout]", ["-c:v", "libx264", "-preset", "veryfast", "-pix_fmt", "yuv420p"]
    else:
        vmap, vcodec = "0:v", ["-c:v", "copy"]
    args += ["-filter_complex", ";".join(parts), "-map", vmap, "-map", amap, *vcodec, "-c:a", "aac", "-b:a", "128k", "-shortest", out]
    return args


def describe(cfg):
    """The configured profiles, without resolving {env: NAME} (no key or id is looked up or printed)."""
    out = {}
    for name in sorted(profiles(cfg)):
        v = resolve(name, cfg)
        vid = v["voice"]
        out[name] = {"provider": v["provider"], "lang": v["lang"],
                     "voice": f"from {vid['env']}" if isinstance(vid, dict) else (vid or "default for the language")}
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("cmd", choices=("report", "mix", "voices"))
    ap.add_argument("target", nargs="?")
    ap.add_argument("lines", nargs="?")
    ap.add_argument("--lang", choices=("en", "ar"), help="default: the profile's language, else en")
    ap.add_argument("--voice", help="a voice profile from narrator.voices (default: narrator.default_voice)")
    ap.add_argument("--config", default="qa.config.yaml")
    ap.add_argument("--out")
    a = ap.parse_args(argv)
    sys.stdout.reconfigure(encoding="utf-8")
    try:
        cfg = load_config(a.config)
        voice = resolve(a.voice, cfg, a.lang)
    except VoiceError as exc:
        print(f"ERROR: {exc}")
        return 2
    lang = a.lang or voice["lang"]
    if a.cmd == "voices":
        print(json.dumps({"default_voice": ((cfg.get("narrator") or {}).get("default_voice")), "profiles": describe(cfg),
                          "provider_without_profile": provider(cfg), "builtin": VOICES}, ensure_ascii=False, indent=1))
        return 0
    notes = []
    if a.cmd == "report":
        if not os.path.isdir(a.target or ""):
            print(f"ERROR: run folder not found: {a.target}")
            return 2
        out = a.out or os.path.join(a.target, f"summary-{lang}.mp3")
        entries = narrate_lines(report_lines(a.target, lang), out, lang, profile=voice, notes=notes)
        if os.path.exists(out):
            print(f"wrote {out} ({entries[-1][1]:.1f}s) and {os.path.splitext(out)[0]}.srt")
        else:
            print(f"wrote {os.path.splitext(out)[0]}.srt only (no voice available this time)")
        return 0
    lines = json.load(open(a.lines, encoding="utf-8"))
    clips = [(x["t"], *say(x["text"], lang, profile=voice, notes=notes)) for x in lines]
    out = a.out or os.path.splitext(a.target)[0] + "-narrated.mp4"
    times = schedule([c[0] for c in clips], [c[2] for c in clips])
    pad = max(0.0, times[-1][1] + 0.5 - (tts.duration(a.target) or 0.0)) if times else 0.0
    subprocess.run(mix_cmd(a.target, clips, out, pad=pad), check=True, timeout=900)
    srt([(s0, e0, x["text"]) for (s0, e0), x in zip(times, lines)], os.path.splitext(out)[0] + ".srt")
    print("wrote", out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
