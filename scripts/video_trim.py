#!/usr/bin/env python3
"""Keep QA videos short: speed up or cut still / idle stretches, keep the .srt in
sync, and check the length against a cap per video type.

    python scripts/video_trim.py <video.mp4> [--srt captions.srt] [--type simple|standard|walkthrough]
                                 [--config qa.config.yaml] [--dry-run]

How it works:
- ffmpeg freezedetect finds stretches where the picture does not change for
  video.min_idle_seconds or more. The recorder also passes the slow steps it ran
  (typing, waits), because typed text changes the picture but is still dead time.
- Stretches that overlap a caption (the narrator is talking) are left alone.
- The rest is played `video.speed` times faster (trim: speed) or cut (trim: cut),
  with video.keep_seconds of it kept at each side so the jump is not jarring.
- Still over the cap? Idle stretches are cut outright. Real activity is never cut
  to meet a cap: the result says "over cap" instead.

The original is kept next to the result (<name>.original.mp4, <captions>.original.srt).

qa.config.yaml:
  video:
    type: standard               # simple | standard | walkthrough (a plan can set "video_type")
    max_seconds: 240             # hard ceiling for every type
    types: {simple: 60, standard: 150, walkthrough: 240}
    trim: speed                  # speed | cut | off
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile

TYPES = {"simple": 60, "standard": 150, "walkthrough": 240}
DEFAULTS = {"type": "standard", "max_seconds": 240, "trim": "speed", "speed": 8.0,
            "min_idle_seconds": 2.0, "keep_seconds": 0.5}
NOISE = 0.003  # freezedetect noise tolerance: video-encoder noise is not "activity"
FREEZE = re.compile(r"lavfi\.freezedetect\.freeze_(start|end):\s*([0-9.]+)")


class ConfigError(Exception):
    """The video section of qa.config.yaml is unusable; the message is one readable line."""


def _num(v, where, minimum=0.0, strict=True):
    if isinstance(v, bool) or not isinstance(v, (int, float)) or (v <= minimum if strict else v < minimum):
        need = f"a number above {minimum:g}" if strict else f"a number of at least {minimum:g}"
        raise ConfigError(f"config error at video.{where}: expected {need}, got {v!r}")
    return float(v)


def settings(video=None):
    """Validated video settings with defaults filled in. Raises ConfigError."""
    if video is None:
        video = {}
    if not isinstance(video, dict):
        raise ConfigError(f"config error at video: expected a mapping (type, max_seconds, types, trim), got {video!r}")
    s = dict(DEFAULTS)
    types = dict(TYPES)
    raw_types = video.get("types")
    if raw_types is not None:
        if not isinstance(raw_types, dict):
            raise ConfigError(f"config error at video.types: expected a mapping like {{simple: 60}}, got {raw_types!r}")
        for name, sec in raw_types.items():
            types[str(name)] = _num(sec, f"types.{name}")
    s["types"] = types
    if video.get("max_seconds") is not None:
        s["max_seconds"] = _num(video["max_seconds"], "max_seconds")
    elif "max_seconds" in video:
        s["max_seconds"] = None
    if "type" in video:
        if video["type"] not in types:
            raise ConfigError(f"config error at video.type: expected one of {', '.join(types)}, got {video['type']!r}")
        s["type"] = video["type"]
    if "trim" in video:
        t = video["trim"]
        t = {False: "off", True: "speed"}.get(t, t) if isinstance(t, bool) else t  # YAML reads a bare off as false
        if t not in ("speed", "cut", "off"):
            raise ConfigError(f"config error at video.trim: expected speed, cut or off, got {video['trim']!r}")
        s["trim"] = t
    if "speed" in video:
        s["speed"] = _num(video["speed"], "speed", 1.0)
    if "min_idle_seconds" in video:
        s["min_idle_seconds"] = _num(video["min_idle_seconds"], "min_idle_seconds")
    if "keep_seconds" in video:
        s["keep_seconds"] = _num(video["keep_seconds"], "keep_seconds", strict=False)
    return s


def cap_for(s, vtype=None):
    """The length cap in seconds: the type's cap, never above max_seconds."""
    vtype = vtype or s["type"]
    if vtype not in s["types"]:
        raise ConfigError(f"unknown video type {vtype!r}: expected one of {', '.join(s['types'])}")
    cap = s["types"][vtype]
    return min(cap, s["max_seconds"]) if s.get("max_seconds") else cap


# ------------------------------------------------------------------ probing
def _probe(path, entries, stream=None):
    args = ["ffprobe", "-v", "error"] + (["-select_streams", stream] if stream else []) + \
           ["-show_entries", entries, "-of", "default=nw=1:nk=1", path]
    return subprocess.run(args, capture_output=True, text=True, timeout=60).stdout.strip()


def duration(path):
    try:
        return float(_probe(path, "format=duration").splitlines()[0])
    except (ValueError, IndexError):
        return 0.0


def has_audio(path):
    return bool(_probe(path, "stream=index", "a"))


def fps(path):
    try:
        num, den = _probe(path, "stream=r_frame_rate", "v:0").splitlines()[0].split("/")
        f = float(num) / float(den)
        return f if 1 <= f <= 120 else 25.0
    except (ValueError, IndexError, ZeroDivisionError):
        return 25.0


def detect_freezes(path, min_idle=2.0, timeout=300):
    """[(start, end)] where the picture is still for min_idle seconds or more.
    A freeze that runs to the end of the video has no freeze_end: it ends at the duration."""
    p = subprocess.run(["ffmpeg", "-hide_banner", "-nostats", "-i", path, "-map", "0:v:0",
                        "-vf", f"freezedetect=n={NOISE}:d={min_idle}", "-f", "null", "-"],
                       capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=timeout)
    out, start = [], None
    for kind, val in FREEZE.findall(p.stderr or ""):
        if kind == "start":
            start = float(val)
        elif start is not None:
            out.append((start, float(val)))
            start = None
    if start is not None:
        out.append((start, duration(path)))
    return out


# ------------------------------------------------------------------ captions
SRT_TIME = re.compile(r"(\d+):(\d+):(\d+)[,.](\d+)\s*-->\s*(\d+):(\d+):(\d+)[,.](\d+)")


def srt_time(sec):
    ms = int(round(max(sec, 0) * 1000))
    return f"{ms // 3600000:02d}:{ms // 60000 % 60:02d}:{ms // 1000 % 60:02d},{ms % 1000:03d}"


def read_srt(path):
    """[(start, end, text)] from an .srt file."""
    with open(path, encoding="utf-8-sig") as fh:
        blocks = re.split(r"\n\s*\n", fh.read().replace("\r\n", "\n").strip())
    out = []
    for b in blocks:
        lines = b.split("\n")
        for i, line in enumerate(lines):
            m = SRT_TIME.search(line)
            if m:
                g = [int(x) for x in m.groups()]
                a = g[0] * 3600 + g[1] * 60 + g[2] + g[3] / 1000
                e = g[4] * 3600 + g[5] * 60 + g[6] + g[7] / 1000
                out.append((a, e, "\n".join(lines[i + 1:])))
                break
    return out


def write_srt(entries, path):
    with open(path, "w", encoding="utf-8") as fh:
        for n, (a, b, t) in enumerate(entries, 1):
            fh.write(f"{n}\n{srt_time(a)} --> {srt_time(b)}\n{t}\n\n")


# ------------------------------------------------------------------ planning
def _subtract(span, blocks):
    """Parts of span (a, b) not covered by any block."""
    parts = [span]
    for ba, bb in blocks:
        nxt = []
        for a, b in parts:
            if bb <= a or ba >= b:
                nxt.append((a, b))
                continue
            if ba > a:
                nxt.append((a, ba))
            if bb < b:
                nxt.append((bb, b))
        parts = nxt
    return parts


def _merge(spans):
    out = []
    for a, b in sorted(spans):
        if out and a <= out[-1][1]:
            out[-1] = (out[-1][0], max(out[-1][1], b))
        else:
            out.append((a, b))
    return out


def idle_spans(total, candidates, protect, min_idle=2.0, keep=0.5):
    """Stretches that may be shortened: candidates (freezes, slow steps) minus the
    protected caption windows, at least min_idle long, with `keep` seconds left at each side."""
    out = []
    for a, b in _merge([(max(0.0, a), min(total, b)) for a, b in candidates if b > a]):
        for pa, pb in _subtract((a, b), protect):
            if pb - pa >= min_idle and pb - pa > 2 * keep:
                out.append((pa + keep, pb - keep))
    return _merge(out)


def pieces_for(total, spans, factor):
    """Cover [0, total] with (start, end, factor): 1 = normal, >1 = faster, 0 = cut."""
    out, t = [], 0.0
    for a, b in spans:
        if a > t:
            out.append((t, a, 1.0))
        out.append((a, b, factor))
        t = b
    if t < total:
        out.append((t, total, 1.0))
    return out


def length(pieces):
    return sum((b - a) / f for a, b, f in pieces if f)


def map_time(t, pieces):
    """Where original time t lands in the shortened video."""
    new = 0.0
    for a, b, f in pieces:
        if t <= a:
            break
        seg = min(t, b) - a
        new += seg / f if f else 0.0
        if t <= b:
            break
    return new


def shift_captions(entries, pieces):
    return [(map_time(a, pieces), max(map_time(b, pieces), map_time(a, pieces) + 0.1), text) for a, b, text in entries]


# ------------------------------------------------------------------ rendering
def render(src, pieces, out, timeout=300):
    """Encode the kept / sped-up pieces of src into out. The filter graph goes in a
    file so a long run never hits the Windows command-line limit."""
    keep = [(a, b, f) for a, b, f in pieces if f and b - a > 0.01]
    audio, rate = has_audio(src), fps(src)
    parts, labels = [], ""
    for i, (a, b, f) in enumerate(keep):
        parts.append(f"[0:v]trim=start={a:.3f}:end={b:.3f},setpts=(PTS-STARTPTS)/{f:g},fps={rate:g}[v{i}]")
        labels += f"[v{i}]"
        if audio:  # idle audio is silence or room noise: the first part of it, at normal speed, keeps the length right
            parts.append(f"[0:a]atrim=start={a:.3f}:end={a + (b - a) / f:.3f},asetpts=PTS-STARTPTS[a{i}]")
            labels += f"[a{i}]"
    parts.append(f"{labels}concat=n={len(keep)}:v=1:a={1 if audio else 0}" + ("[v][a]" if audio else "[v]"))
    fd, graph = tempfile.mkstemp(suffix=".ffgraph", text=True)
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        fh.write(";\n".join(parts))
    args = ["ffmpeg", "-y", "-v", "error", "-i", src, "-/filter_complex", graph, "-map", "[v]"]
    if audio:
        args += ["-map", "[a]", "-c:a", "aac", "-b:a", "128k"]
    args += ["-c:v", "libx264", "-pix_fmt", "yuv420p", "-preset", "veryfast", "-crf", "23", "-movflags", "+faststart", out]
    try:
        subprocess.run(args, check=True, timeout=timeout, capture_output=True)
    finally:
        os.remove(graph)
    return out


def original_name(path):
    root, ext = os.path.splitext(path)
    return f"{root}.original{ext}"


def trim(video, srt=None, s=None, vtype=None, slow=(), dry_run=False, timeout=300):
    """Shorten video in place (the original is kept as <name>.original.mp4) and keep
    srt in sync. slow: extra (start, end) candidates, e.g. typing or wait steps.
    Returns a summary dict for results.json and the report."""
    s = s or settings()
    vtype = vtype or s["type"]
    cap = cap_for(s, vtype)
    total = duration(video)
    if not total:
        raise RuntimeError(f"cannot read the length of {os.path.basename(video)}")
    captions = read_srt(srt) if srt and os.path.exists(srt) else []
    info = {"type": vtype, "cap_seconds": round(cap, 1), "original_seconds": round(total, 1), "final_seconds": round(total, 1),
            "mode": s["trim"], "idle_stretches": 0, "idle_seconds": 0.0, "over_cap": total > cap, "original": None, "changed": False}
    if s["trim"] == "off":
        return info
    candidates = detect_freezes(video, s["min_idle_seconds"], timeout) + list(slow)
    spans = idle_spans(total, candidates, [(a, b) for a, b, _ in captions], s["min_idle_seconds"], s["keep_seconds"])
    if not spans:
        return info
    factor = 0.0 if s["trim"] == "cut" else s["speed"]
    pieces = pieces_for(total, spans, factor)
    if factor and length(pieces) > cap:  # still too long: cut the idle stretches instead of speeding them
        pieces = pieces_for(total, spans, 0.0)
        info["mode"] = "cut (to meet the cap)"
    final = length(pieces)
    info.update(idle_stretches=len(spans), idle_seconds=round(sum(b - a for a, b in spans), 1),
                final_seconds=round(final, 1), over_cap=final > cap + 0.5, changed=True)
    if dry_run:
        return info
    orig = original_name(video)
    os.replace(video, orig)
    try:
        render(orig, pieces, video, timeout)
    except (subprocess.SubprocessError, OSError):
        if os.path.exists(video):
            os.remove(video)
        os.replace(orig, video)  # never lose the evidence: put the original back
        raise
    info["original"] = os.path.basename(orig)
    info["final_seconds"] = round(duration(video) or final, 1)
    info["over_cap"] = info["final_seconds"] > cap + 0.5
    if captions:
        shutil.copyfile(srt, original_name(srt))
        write_srt(shift_captions(captions, pieces), srt)
    return info


def describe(info):
    """One plain line: 'video 3:12 -> 0:58 (cap 1:00, simple; 4 idle stretches sped up 8x)'."""
    def mmss(x):
        x = int(round(x))
        return f"{x // 60}:{x % 60:02d}"
    line = f"video {mmss(info['original_seconds'])} -> {mmss(info['final_seconds'])} (cap {mmss(info['cap_seconds'])}, {info['type']}"
    if info.get("changed"):
        line += f"; {info['idle_stretches']} idle stretch(es), {info['idle_seconds']:g}s, {info['mode']}"
    line += ")"
    if info.get("over_cap"):
        line += " OVER CAP: split the plan or pick a longer video type"
    return line


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("video")
    ap.add_argument("--srt")
    ap.add_argument("--type", dest="vtype")
    ap.add_argument("--config", default=os.environ.get("SMEKIT_QA_CONFIG", "qa.config.yaml"))
    ap.add_argument("--dry-run", action="store_true", help="measure and plan only, change nothing")
    a = ap.parse_args(argv)
    if not os.path.isfile(a.video):
        print(f"ERROR: video not found: {a.video}")
        return 2
    if not (shutil.which("ffmpeg") and shutil.which("ffprobe")):
        print("ERROR: ffmpeg and ffprobe are needed (see scripts/doctor.py)")
        return 2
    try:
        s = settings(load_video_section(a.config))
        info = trim(a.video, a.srt, s, a.vtype, dry_run=a.dry_run)
    except ConfigError as exc:
        print(f"ERROR: {exc}")
        return 2
    except (RuntimeError, subprocess.SubprocessError, OSError) as exc:
        print(f"ERROR: trim failed, the video is unchanged: {str(exc).splitlines()[0][:160] if str(exc) else type(exc).__name__}")
        return 1
    print(describe(info))
    print(json.dumps(info))
    return 0


def load_video_section(path):
    """Only the video section of qa.config.yaml (a typo elsewhere must not stop a recording)."""
    if not path or not os.path.exists(path):
        return None
    try:
        import yaml  # PyYAML
        with open(path, encoding="utf-8-sig") as fh:
            cfg = yaml.safe_load(fh.read()) if path.endswith((".yaml", ".yml")) else json.loads(fh.read())
    except Exception as exc:  # yaml.YAMLError / JSONDecodeError: one line, no traceback
        mark = getattr(exc, "problem_mark", None)
        where = f" (line {mark.line + 1}, column {mark.column + 1})" if mark is not None else ""
        raise ConfigError(f"config error in {path}: not valid YAML{where}") from None
    return (cfg or {}).get("video") if isinstance(cfg, dict) else None


if __name__ == "__main__":
    sys.exit(main())
