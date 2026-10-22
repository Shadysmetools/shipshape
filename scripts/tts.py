#!/usr/bin/env python3
"""Narration clips with Microsoft neural voices (edge-tts), cached by voice + text.

Self-healing cache: a clip is written to a temp file and kept only if ffprobe
can read a positive duration. A network blip therefore never leaves a broken
clip behind (a corrupt cached clip once broke every later recording).
Every synthesis has a timeout and 3 tries.

    python scripts/tts.py "Text to speak" [--voice en-US-AndrewNeural]
"""
from __future__ import annotations

import argparse
import hashlib
import os
import shutil
import subprocess
import sys

VOICE = os.environ.get("SMEKIT_VOICE", "en-US-AndrewNeural")
CACHE = os.environ.get("SMEKIT_TTS_CACHE", os.path.join(os.path.expanduser("~"), ".cache", "smekit-tts"))
TIMEOUT = int(os.environ.get("SMEKIT_TTS_TIMEOUT", "90"))


def have(tool):
    return shutil.which(tool) is not None


def duration(path):
    """Seconds (float) from ffprobe, or None if unreadable."""
    try:
        out = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", path],
                             capture_output=True, text=True, timeout=60).stdout.strip()
        v = float(out)
        return v if v > 0 else None
    except (ValueError, OSError, subprocess.SubprocessError):
        return None


def speak(text, voice=VOICE, rate="-5%", cache=CACHE):
    """Return (mp3 path, seconds, synthesized_now). Raises RuntimeError after 3 failed tries."""
    os.makedirs(cache, exist_ok=True)
    key = hashlib.sha1(f"{voice}\n{rate}\n{text}".encode("utf-8")).hexdigest()
    path = os.path.join(cache, key + ".mp3")
    if os.path.exists(path):
        d = duration(path)
        if d:
            return path, d, False
        os.remove(path)  # corrupt cache entry: heal it
    tmp = f"{path}.{os.getpid()}.tmp.mp3"
    for _attempt in range(3):
        try:
            subprocess.run([sys.executable, "-m", "edge_tts", "--voice", voice, f"--rate={rate}", "--text", text,
                            "--write-media", tmp], capture_output=True, timeout=TIMEOUT)
        except (subprocess.SubprocessError, OSError):
            pass
        d = duration(tmp) if os.path.exists(tmp) else None
        if d:
            os.replace(tmp, path)
            return path, d, True
    if os.path.exists(tmp):
        os.remove(tmp)
    raise RuntimeError(f"narration failed after 3 tries: {text[:60]}")


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("text")
    ap.add_argument("--voice", default=VOICE)
    a = ap.parse_args(argv)
    p, d, new = speak(a.text, a.voice)
    print(f"{p} {d:.2f}s {'new' if new else 'cached'}")


if __name__ == "__main__":
    main()
