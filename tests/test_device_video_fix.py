"""Issue #22: the device-control video had several narrator voices at once, and a privacy mask that hid the
whole app. These tests fail on the code before the fix."""
import json
import os
import re
import shutil
import subprocess
import sys

import pytest

import desktop
import narrator

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FFMPEG = shutil.which("ffmpeg") and shutil.which("ffprobe")

# the real timings from qa-runs/2026-10-25-device-control/claude-desktop (narration.json + clip lengths)
STARTS = [0.99, 1.26, 4.17, 4.69, 6.44]
LENGTHS = [4.08, 2.98, 2.83, 1.97, 2.23]


def _delays(cmd):
    fc = cmd[cmd.index("-filter_complex") + 1]
    return [int(x) / 1000 for x in re.findall(r"adelay=(\d+)", fc)]


# ------------------------------------------------------------------ 1. one narrator at a time
def test_narration_clips_never_overlap_in_time():
    clips = [(t, f"c{k}.mp3", d) for k, (t, d) in enumerate(zip(STARTS, LENGTHS))]
    starts = _delays(narrator.mix_cmd("v.mp4", clips, "o.mp4", video_has_audio=False))
    assert len(starts) == 5
    for (a, da), b in zip(zip(starts, LENGTHS), starts[1:]):
        assert b >= a + da, f"a clip starts at {b}s while the previous one plays until {a + da}s"
    assert starts[0] == STARTS[0]  # a line is never moved earlier than its action


def _probe_audio_streams(path):
    out = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "a", "-show_entries", "stream=index", "-of", "csv=p=0", path],
                         capture_output=True, text=True, timeout=60).stdout.split()
    return len(out)


def _duration(path):
    return float(subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", path],
                                capture_output=True, text=True, timeout=60).stdout.strip())


def _gaps(path):
    """(start, end) of the quiet gaps in the audio (ffmpeg silencedetect)."""
    err = subprocess.run(["ffmpeg", "-hide_banner", "-i", path, "-af", "silencedetect=n=-40dB:d=0.15", "-f", "null", "-"],
                         capture_output=True, text=True, timeout=120).stderr
    starts = [float(x) for x in re.findall(r"silence_start: (-?[\d.]+)", err)]
    ends = [float(x) for x in re.findall(r"silence_end: (-?[\d.]+)", err)]
    return list(zip(starts, ends))


@pytest.mark.skipif(not FFMPEG, reason="needs ffmpeg")
@pytest.mark.parametrize("with_audio", [False, True])
def test_narrated_video_has_one_audio_stream_and_no_overlapping_voices(tmp_path, monkeypatch, with_audio):
    """Real ffmpeg: three 1.5 s 'voices' asked to start 0.2 s apart. With one narrator at a time there is a quiet gap
    between each pair of voices (silencedetect); overlapping voices leave none. The output keeps exactly one audio stream and is not cut short."""
    video = str(tmp_path / "v.mp4")
    src = ["-f", "lavfi", "-i", "testsrc=size=320x240:rate=15:duration=3"]
    if with_audio:  # a video that already has a (quiet) track: it is ducked, never added as a second stream
        src += ["-f", "lavfi", "-i", "anullsrc=r=24000:cl=mono", "-t", "3", "-c:a", "aac"]
    subprocess.run(["ffmpeg", "-y", "-v", "error", *src, "-t", "3", "-c:v", "libx264", "-pix_fmt", "yuv420p", video], check=True)
    clips = {}
    for k, f in enumerate((440, 660, 880)):
        p = str(tmp_path / f"c{k}.mp3")
        subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", f"sine=frequency={f}:duration=1.5",
                        p], check=True)
        clips[f"line {k}"] = p
    monkeypatch.setattr(narrator, "say", lambda text, *a, **k: (clips[text], narrator.tts.duration(clips[text])))
    lines = tmp_path / "lines.json"
    lines.write_text(json.dumps([{"t": 0.2 * k, "text": f"line {k}"} for k in range(3)]), encoding="utf-8")
    out = str(tmp_path / "o.mp4")
    assert narrator.main(["mix", video, str(lines), "--out", out, "--config", str(tmp_path / "none.yaml")]) == 0
    assert _probe_audio_streams(out) == 1
    between = [g for g in _gaps(out) if 0.5 < g[0] < 4.0]
    assert len(between) == 2, f"no quiet gap between the voices, they overlap: {between}"
    assert _duration(out) >= 3 * 1.5, "the last narration line was cut off"
    srt = (tmp_path / "o.srt").read_text(encoding="utf-8")
    secs = [int(h) * 3600 + int(m) * 60 + int(sec) + int(ms) / 1000
            for h, m, sec, ms in re.findall(r"(\d\d):(\d\d):(\d\d),(\d\d\d)", srt)]
    spans = list(zip(secs[::2], secs[1::2]))
    assert len(spans) == 3 and all(b[0] >= a[1] for a, b in zip(spans, spans[1:])), spans  # captions do not overlap either


def test_run_paces_steps_so_lines_do_not_overlap(tmp_path, monkeypatch):
    """The run waits for a line to be spoken before the next spoken step, so the video stays in sync."""
    monkeypatch.setattr(desktop, "speech_lengths", lambda steps: {s["say"]: 0.5 for s in steps if s.get("say")})

    class Be(desktop.Backend):  # a "real" backend with no screen
        def __init__(self):
            self.target, self.os, self.launched_new = 1, "test", False

        def launch(self, step, gate):
            return {}

        def target_rect(self):
            return (0, 0, 100, 100)

        virtual_bounds = target_rect

        def park_mouse(self):
            pass

        set_focus = park_mouse

        def screenshot(self, *a, **k):
            pass

    monkeypatch.setattr(desktop, "record_cmd", lambda *a, **k: [sys.executable, "-c", "import sys; sys.stdin.read(1)"])
    monkeypatch.setattr(desktop.shutil, "which", lambda n: "ffmpeg")
    monkeypatch.setattr(desktop.subprocess, "run", lambda *a, **k: None)  # the narrator mix itself
    open(os.path.join(tmp_path, "desktop.mp4"), "wb").close()
    steps = [{"do": "launch", "app": "notepad", "shot": False}, {"do": "record_start"},
             {"do": "wait", "sec": 0, "say": "one"}, {"do": "wait", "sec": 0, "say": "two"}, {"do": "wait", "sec": 0, "say": "three"}]
    desktop.run(steps, {"desktop": {"enabled": True, "allow_apps": ["notepad"]}}, str(tmp_path), backend=Be(), notice=False, narrate=True)
    ts = [x["t"] for x in json.load(open(tmp_path / "narration.json", encoding="utf-8"))]
    assert len(ts) == 3 and all(b - a >= 0.5 for a, b in zip(ts, ts[1:])), ts


# ------------------------------------------------------------------ 2. masks hide only the private parts
WIN = (0, 0, 2560, 1528)
SIDEBAR = (0, 0, 402, 1529)
SIDEBAR_TOGGLE = (285, 6, 390, 48)
RECENTS = (1001, 1070, 1962, 1293)
INPUT = (1013, 753, 1962, 829)


def test_mask_cover_is_limited_and_never_hides_the_control_under_test():
    rects, frac = desktop.fit_masks([SIDEBAR, RECENTS], WIN, keep=[INPUT])
    assert frac < 0.40
    assert not any(desktop.clip_rect(r, INPUT) for r in rects)
    # the old template (everything but the input box) is refused by default
    with pytest.raises(desktop.StepFailed, match="would hide"):
        desktop.fit_masks(desktop.outside(WIN, INPUT, 14), WIN, keep=[INPUT])
    # a mask drawn over the input box gets the box cut out of it
    rects, _ = desktop.fit_masks([(900, 700, 2000, 900)], WIN, keep=[INPUT])
    assert not any(desktop.clip_rect(r, INPUT) for r in rects)
    assert desktop.union_area(rects) == 1100 * 200 - (1962 - 1013) * (829 - 753)
    # a deliberate full cover (Save As lists folders) is allowed only when the step says so
    assert desktop.fit_masks([WIN], WIN, max_cover=None)[1] == 1.0


class ClaudeFake:
    """Claude Desktop's real control rects (from a UIA dump)."""

    def __init__(self):
        self.target, self.launched_new, self.texts = 12, False, {"Write your prompt to Claude": ""}

    def launch(self, step, gate):
        return {"how": "start-menu"}

    def target_rect(self):
        return WIN

    def find_control(self, spec, timeout=None, required=True):
        name, role = spec.get("name"), spec.get("role")
        if role == "Group" and name == "Sidebar":
            return SIDEBAR if spec.get("largest") else SIDEBAR_TOGGLE
        return {"List": RECENTS, "Edit": INPUT}.get(role)

    @staticmethod
    def rect_of(el):
        return el

    def read(self, spec):
        return self.texts["Write your prompt to Claude"]

    def screenshot(self, *a, **k):
        pass


def test_claude_template_masks_only_the_private_regions(tmp_path):
    plan = desktop.load_steps(os.path.join(ROOT, "templates", "desktop-steps.claude-desktop.json"))
    steps = [s for s in plan if s["do"] in ("launch", "mask", "assert_text")][:3]
    desktop.run(steps, {"desktop": {"enabled": True, "allow_apps": ["claude"]}}, str(tmp_path), backend=ClaudeFake(),
                record=False, notice=False)
    entry = next(json.loads(x) for x in open(tmp_path / "desktop-actions.jsonl", encoding="utf-8") if '"mask"' in x)
    assert entry["status"] == "DONE" and entry["masks"] == 2, entry
    assert 0.15 < entry["cover"] < 0.40  # the sidebar (the big one, not the mode toggle) and the recent items


def test_pixelate_makes_text_unreadable_but_keeps_the_rest():
    from PIL import Image, ImageDraw
    img = Image.new("RGB", (400, 200), "white")
    d = ImageDraw.Draw(img)
    for y in range(10, 190, 24):
        d.text((10, y), "Secret chat title 12345 private", fill="black")
    blurred = desktop.pixelate(img)
    assert blurred.size == img.size

    def edges(im):  # sharp black/white transitions: text strokes
        g = im.convert("L")
        px = g.load()
        return sum(1 for y in range(g.size[1]) for x in range(1, g.size[0]) if abs(px[x, y] - px[x - 1, y]) > 80)
    assert edges(img) > 1000 and edges(blurred) == 0


# ------------------------------------------------------------------ 3. keys only ever reach the app under test
def _typing_backend(on_target=True, focused_pid=600, target_pid=600):
    be = object.__new__(desktop.Backend)
    be.os, be._last_sent, be.target = "Windows", 0.0, 12
    be.on_target = lambda fg=None: on_target
    be.focused_pid = lambda: focused_pid
    be.target_pid = lambda: target_pid
    return be


@pytest.mark.parametrize("kw,why", [
    ({"on_target": False}, "not in front"),
    ({"focused_pid": 4242}, "keyboard focus is not inside"),  # e.g. a terminal tab has the keyboard focus
    ({"focused_pid": None}, "keyboard focus is not inside"),  # unknown: refused, never guessed
])
def test_no_character_is_typed_unless_the_target_has_the_keyboard_focus(monkeypatch, kw, why):
    import types
    sent = []
    monkeypatch.setitem(sys.modules, "pywinauto.keyboard", types.SimpleNamespace(send_keys=lambda k, **_: sent.append(k)))
    be = _typing_backend(**kw)
    with pytest.raises(desktop.Refused, match=why):
        be.type("ShipShape")
    assert sent == []


def test_a_shortcut_is_refused_when_the_keyboard_focus_is_elsewhere():
    be = _typing_backend(focused_pid=4242)
    be.pg = None  # would raise if a key were sent
    with pytest.raises(desktop.Refused, match="keyboard focus"):
        be.key(["ctrl", "a"])


def test_overlays_hand_the_focus_back_to_the_window_under_test(monkeypatch):
    seen = {}

    class P:
        def __init__(self, argv, **k):
            seen["restore"] = argv[-1]
            self.stdout = type("S", (), {"readline": lambda self: "ready\n"})()
    monkeypatch.setattr(desktop.subprocess, "Popen", P)
    desktop.Overlay([{"rect": [0, 0, 10, 10]}], restore=12)
    assert seen["restore"] == "12"  # never whatever window happened to be in front (a terminal)
