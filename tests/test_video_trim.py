"""Video length limits and dead-time trimming (scripts/video_trim.py).
The test videos are generated with ffmpeg lavfi: moving test pattern / still grey / moving."""
import json
import os
import shutil
import subprocess

import pytest
import yaml

import notify
import qa_report_html
import video_trim as vt
from conftest import ROOT

needs_ffmpeg = pytest.mark.skipif(not (shutil.which("ffmpeg") and shutil.which("ffprobe")), reason="ffmpeg not installed")


def make_video(path, parts=((2, "move"), (6, "still"), (2, "move")), audio=True):
    """parts: (seconds, 'move' | 'still'). A sine tone is the audio track when audio=True."""
    args, chain = ["ffmpeg", "-y", "-v", "error"], ""
    for k, (sec, kind) in enumerate(parts):
        src = f"testsrc2=size=320x240:rate=25:duration={sec}" if kind == "move" else f"color=c=gray:size=320x240:rate=25:duration={sec}"
        args += ["-f", "lavfi", "-i", src]
        chain += f"[{k}:v]"
    total = sum(sec for sec, _ in parts)
    fc = f"{chain}concat=n={len(parts)}:v=1[v]"
    if audio:
        args += ["-f", "lavfi", "-i", f"sine=frequency=440:duration={total}"]
    args += ["-filter_complex", fc, "-map", "[v]"]
    if audio:
        args += ["-map", f"{len(parts)}:a", "-c:a", "aac"]
    args += ["-c:v", "libx264", "-pix_fmt", "yuv420p", str(path)]
    subprocess.run(args, check=True, timeout=120)
    return str(path)


def srt_file(path, entries):
    vt.write_srt(entries, str(path))
    return str(path)


# ------------------------------------------------------------------ config
def test_defaults_and_caps():
    s = vt.settings(None)
    assert s["types"] == {"simple": 60, "standard": 150, "walkthrough": 240}
    assert vt.cap_for(s) == 150 and vt.cap_for(s, "simple") == 60 and vt.cap_for(s, "walkthrough") == 240


def test_max_seconds_is_a_ceiling_for_every_type():
    s = vt.settings({"max_seconds": 100, "types": {"demo": 300}})
    assert vt.cap_for(s, "walkthrough") == 100 and vt.cap_for(s, "demo") == 100 and vt.cap_for(s, "simple") == 60


def test_yaml_off_means_trim_off():
    cfg = yaml.safe_load("video: {trim: off}")
    assert cfg["video"]["trim"] is False  # YAML 1.1 reads a bare off as false
    assert vt.settings(cfg["video"])["trim"] == "off"


@pytest.mark.parametrize("video, where", [
    ({"max_seconds": True}, "video.max_seconds"),
    ({"max_seconds": -5}, "video.max_seconds"),
    ({"types": {"simple": "short"}}, "video.types.simple"),
    ({"types": [60, 150]}, "video.types"),
    ({"type": "epic"}, "video.type"),
    ({"trim": "blur"}, "video.trim"),
    ({"speed": 1}, "video.speed"),
    ("long", "video"),
])
def test_bad_video_config_is_one_line(video, where):
    with pytest.raises(vt.ConfigError) as e:
        vt.settings(video)
    assert f"config error at {where}:" in str(e.value) and "\n" not in str(e.value)


def test_notify_load_config_checks_the_video_section(tmp_path):
    bad = tmp_path / "qa.config.yaml"
    bad.write_text("video: {type: epic}\n", encoding="utf-8")
    with pytest.raises(notify.ConfigError, match="video.type"):
        notify.load_config(str(bad))


def test_example_configs_have_the_video_section():
    for p in ("templates/qa.config.example.yaml", "examples/demo-app/qa.config.yaml"):
        cfg = notify.load_config(os.path.join(ROOT, p))
        s = vt.settings(cfg["video"])
        assert s["types"]["simple"] == 60 and s["types"]["walkthrough"] == 240 and s["max_seconds"] == 240


def test_load_video_section_ignores_a_missing_file_and_reports_bad_yaml(tmp_path):
    assert vt.load_video_section(str(tmp_path / "none.yaml")) is None
    bad = tmp_path / "qa.config.yaml"
    bad.write_text("video: [\n", encoding="utf-8")
    with pytest.raises(vt.ConfigError, match=r"not valid YAML \(line"):
        vt.load_video_section(str(bad))


# ------------------------------------------------------------------ planning + caption sync (pure)
def test_idle_spans_skip_captions_and_short_pauses():
    spans = vt.idle_spans(20, [(2, 8), (10, 11), (12, 20)], protect=[(14, 16)], min_idle=2, keep=0.5)
    # (2,8) -> keep 0.5 each side; (10,11) too short; (12,20) split around the caption: (12,14) and (16,20)
    assert spans == [(2.5, 7.5), (12.5, 13.5), (16.5, 19.5)]


def test_map_time_and_caption_shift_for_speed_and_cut():
    sped = vt.pieces_for(10, [(2, 8)], 4.0)
    assert vt.length(sped) == pytest.approx(5.5)          # 2 + 6/4 + 2
    assert vt.map_time(9, sped) == pytest.approx(4.5)
    cut = vt.pieces_for(10, [(2, 8)], 0.0)
    assert vt.length(cut) == pytest.approx(4)
    assert vt.shift_captions([(0.5, 1.5, "a"), (8.5, 9.5, "b")], cut) == [(0.5, 1.5, "a"), (2.5, 3.5, "b")]


def test_srt_round_trip(tmp_path):
    p = srt_file(tmp_path / "c.srt", [(0.25, 1.5, "Open the page"), (61.0, 63.25, "PASS TC-01")])
    assert vt.read_srt(p) == [(0.25, 1.5, "Open the page"), (61.0, 63.25, "PASS TC-01")]


# ------------------------------------------------------------------ real ffmpeg
@needs_ffmpeg
def test_freeze_detected_including_one_that_runs_to_the_end(tmp_path):
    v = make_video(tmp_path / "a.mp4", ((2, "move"), (5, "still"), (2, "move"), (4, "still")), audio=False)
    fr = vt.detect_freezes(v, 2.0)
    assert len(fr) == 2
    assert fr[0][0] == pytest.approx(2, abs=0.3) and fr[0][1] == pytest.approx(7, abs=0.3)
    assert fr[1][0] == pytest.approx(9, abs=0.3) and fr[1][1] == pytest.approx(13, abs=0.3)  # no freeze_end: the duration


@needs_ffmpeg
@pytest.mark.parametrize("audio", [True, False])
def test_speed_up_keeps_original_and_shifts_captions(tmp_path, audio):
    v = make_video(tmp_path / "run.mp4", audio=audio)  # 2 s move, 6 s still, 2 s move
    srt = srt_file(tmp_path / "captions.srt", [(0.2, 1.5, "Open the page"), (8.5, 9.5, "PASS TC-01")])
    s = vt.settings({"trim": "speed", "speed": 5, "keep_seconds": 0.5, "type": "simple"})
    info = vt.trim(v, srt, s)
    assert info["changed"] and info["original"] == "run.original.mp4"
    assert vt.duration(str(tmp_path / "run.original.mp4")) == pytest.approx(10, abs=0.3)
    assert info["original_seconds"] == pytest.approx(10, abs=0.3)
    # the still 6 s minus 0.5 s each side = 5 s at 5x -> 1 s: about 6 s total
    assert info["final_seconds"] == pytest.approx(6, abs=0.4)
    assert vt.duration(v) == pytest.approx(6, abs=0.4)
    assert vt.has_audio(v) is audio
    caps = vt.read_srt(srt)
    assert caps[0][:2] == (0.2, 1.5)                              # before the trim: unchanged
    assert caps[1][0] == pytest.approx(8.5 - 4, abs=0.05)         # after: 5 s became 1 s
    assert vt.read_srt(str(tmp_path / "captions.original.srt"))[1][0] == 8.5
    assert not info["over_cap"]


@needs_ffmpeg
def test_cut_mode_and_captioned_stillness_is_left_alone(tmp_path):
    v = make_video(tmp_path / "run.mp4", audio=True)
    srt = srt_file(tmp_path / "captions.srt", [(2.5, 7.5, "The narrator explains the still page")])
    info = vt.trim(v, srt, vt.settings({"trim": "cut"}))
    assert not info["changed"] and info["final_seconds"] == info["original_seconds"]  # all the stillness is narrated
    assert not os.path.exists(tmp_path / "run.original.mp4")
    os.remove(srt)
    info = vt.trim(v, None, vt.settings({"trim": "cut"}))
    assert info["changed"] and vt.duration(v) == pytest.approx(5, abs=0.4)  # 10 - (6 - 2*0.5)


@needs_ffmpeg
def test_slow_steps_count_as_dead_time_even_when_pixels_move(tmp_path):
    v = make_video(tmp_path / "run.mp4", ((10, "move"),), audio=False)  # typing: the picture keeps changing
    assert vt.detect_freezes(v, 2.0) == []
    info = vt.trim(v, None, vt.settings({"speed": 4}), slow=[(1.0, 9.0)])
    assert info["changed"] and info["final_seconds"] == pytest.approx(2 + 7 / 4 + 1, abs=0.4)


@needs_ffmpeg
def test_over_cap_switches_to_cut_and_is_flagged(tmp_path):
    v = make_video(tmp_path / "run.mp4", ((3, "move"), (8, "still"), (3, "move")), audio=False)
    s = vt.settings({"types": {"tiny": 5}, "type": "tiny", "speed": 2})
    info = vt.trim(v, None, s)
    assert info["mode"] == "cut (to meet the cap)"
    assert info["final_seconds"] == pytest.approx(7, abs=0.4)    # 14 - 7 idle; real activity is never cut
    assert info["over_cap"] and "OVER CAP" in vt.describe(info)


@needs_ffmpeg
def test_trim_off_and_dry_run_change_nothing(tmp_path):
    v = make_video(tmp_path / "run.mp4", audio=False)
    before = os.path.getsize(v)
    assert not vt.trim(v, None, vt.settings({"trim": "off"}))["changed"]
    dry = vt.trim(v, None, vt.settings(), dry_run=True)
    assert dry["changed"] and dry["final_seconds"] < dry["original_seconds"]
    assert os.path.getsize(v) == before and not os.path.exists(tmp_path / "run.original.mp4")


@needs_ffmpeg
def test_failed_render_puts_the_original_back(tmp_path, monkeypatch):
    v = make_video(tmp_path / "run.mp4", audio=False)
    before = os.path.getsize(v)

    def boom(*a, **k):
        raise subprocess.CalledProcessError(1, "ffmpeg")
    monkeypatch.setattr(vt, "render", boom)
    with pytest.raises(subprocess.CalledProcessError):
        vt.trim(v, None, vt.settings())
    assert os.path.getsize(v) == before and not os.path.exists(tmp_path / "run.original.mp4")


@needs_ffmpeg
def test_cli_prints_one_line_and_json(tmp_path, capsys):
    v = make_video(tmp_path / "run.mp4", audio=False)
    assert vt.main([v, "--dry-run", "--type", "simple", "--config", str(tmp_path / "none.yaml")]) == 0
    out = capsys.readouterr().out.splitlines()
    assert out[0].startswith("video 0:10 -> 0:0") and "cap 1:00, simple" in out[0]
    assert json.loads(out[1])["type"] == "simple"
    assert vt.main([str(tmp_path / "missing.mp4")]) == 2
    assert capsys.readouterr().out.startswith("ERROR: video not found")


# ------------------------------------------------------------------ report
def test_report_shows_original_and_final_length(tmp_path):
    run = tmp_path / "runs" / "r1"
    (run / "round-01" / "p" / "pass-1").mkdir(parents=True)
    vs = {"type": "simple", "cap_seconds": 60, "original_seconds": 192.4, "final_seconds": 58.2, "original": "p.original.mp4",
          "over_cap": False, "changed": True}
    led = {"goal": "sign up", "created": "2026-10-25T10:00:00", "status": "met", "elapsed_minutes": 3, "bugs": [], "human_gates": [],
           "rounds": [{"n": 1, "summary": "1 pass / 0 fail", "counts": {"PASS": 1},
                       "runs": [{"plan": "p.json", "dir": "round-01/p/pass-1", "video": "p.mp4", "video_seconds": vs,
                                 "results": [{"id": "TC-1", "title": "t", "result": "PASS", "evidence": "x.png"}]}]}]}
    (run / "ledger.json").write_text(json.dumps(led), encoding="utf-8")
    html = open(qa_report_html.build(str(run)), encoding="utf-8").read()
    assert "Length: original 3:12 → final 0:58" in html and "cap 1:00, simple" in html and "p.original.mp4" in html


def test_notify_sends_the_trimmed_video_not_the_original(tmp_path):
    d = tmp_path / "round-01" / "p" / "pass-1"
    d.mkdir(parents=True)
    (d / "p.mp4").write_bytes(b"0")
    (d / "p.original.mp4").write_bytes(b"0")
    os.utime(d / "p.mp4", (1, 1))  # even when the original is newer
    assert notify.find_video(str(tmp_path)).endswith(os.path.join("pass-1", "p.mp4"))


def test_record_refuses_a_bad_video_config_before_the_run(tmp_path, capsys):
    import record
    cfg = tmp_path / "qa.config.yaml"
    cfg.write_text("video: {max_seconds: lots}\nnotify: {slack: {enabled: maybe}}\n", encoding="utf-8")
    plan = os.path.join(ROOT, "examples", "demo-app", "plans", "signup.json")
    assert record.main([plan, "--out", str(tmp_path / "o"), "--config", str(cfg)]) == 2
    assert capsys.readouterr().out.strip() == "ERROR: config error at video.max_seconds: expected a number above 0, got 'lots'"


def test_record_ignores_notify_typos_it_does_not_use(tmp_path):
    cfg = tmp_path / "qa.config.yaml"
    cfg.write_text("notify: {slack: {enabled: maybe}}\n", encoding="utf-8")
    assert vt.settings(vt.load_video_section(str(cfg)))["type"] == "standard"
