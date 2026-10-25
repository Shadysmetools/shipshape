"""Voice profiles (issue #6): narrator.voices in qa.config.yaml, --voice <profile>, and the edge fallback
when a paid provider refuses. All HTTP is mocked: no real key, no real voice id, no paid call."""
import io
import json
import os
import subprocess
import sys
import urllib.error

import pytest

import keys
import narrator
import record
import slides_video

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CFG = {"narrator": {"default_voice": "narrator", "lang": "en", "voices": {
    "narrator": {"provider": "edge", "voice": "en-US-AvaNeural", "lang": "en"},
    "sara": {"provider": "elevenlabs", "voice": {"env": "ELEVENLABS_VOICE_ID_SARA"}, "lang": "ar"},
    "omar": {"provider": "elevenlabs", "voice": "fake-voice-omar"},
    "nova": {"provider": "openai", "voice": "nova"}}}}


class FakeResponse(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *a):
        self.close()


@pytest.fixture
def env(tmp_path, monkeypatch):
    """Fake keys in the isolated store, a temp TTS cache, edge-tts and ffprobe mocked, HTTP recorded."""
    for n in ("ELEVENLABS_API_KEY", "ELEVENLABS_VOICE_ID", "ELEVENLABS_VOICE_ID_SARA", "OPENAI_API_KEY", "SMEKIT_TTS_PROVIDER", "SMEKIT_VOICE"):
        monkeypatch.delenv(n, raising=False)
    monkeypatch.setattr(narrator.tts, "CACHE", str(tmp_path / "cache"))
    monkeypatch.setattr(narrator.tts, "duration", lambda p: 1.5 if os.path.exists(p) else None)
    edge = []
    monkeypatch.setattr(narrator.tts, "speak", lambda text, voice, rate="-5%": edge.append(voice) or (f"edge-{voice}.mp3", 2.0, True))
    narrator._REFUSED.clear()
    narrator._WARNED.clear()
    calls = []

    def ok(req, timeout=None):
        calls.append(req)
        return FakeResponse(b"ID3fake-mp3")

    monkeypatch.setattr(narrator.urllib.request, "urlopen", ok)
    return {"edge": edge, "calls": calls, "monkeypatch": monkeypatch}


def refuse(code):
    def _urlopen(req, timeout=None):
        raise urllib.error.HTTPError(req.full_url, code, "Payment Required", {}, io.BytesIO(b'{"detail":"paid_plan_required"}'))
    return _urlopen


def test_resolve_order_and_profiles():
    assert narrator.resolve(None, CFG)["profile"] == "narrator"            # narrator.default_voice
    sara = narrator.resolve("sara", CFG)                                    # --voice wins
    assert sara["provider"] == "elevenlabs" and sara["lang"] == "ar" and sara["voice"] == {"env": "ELEVENLABS_VOICE_ID_SARA"}
    legacy = narrator.resolve(None, {"narrator": {"provider": "edge", "voice": "ar-EG-SalmaNeural", "lang": "ar"}})
    assert legacy == {"profile": None, "provider": "edge", "voice": "ar-EG-SalmaNeural", "lang": "ar", "rate": "-5%"}
    assert narrator.resolve(None, {})["provider"] == "edge"


def test_unknown_or_bad_profile_is_one_line_error():
    with pytest.raises(narrator.VoiceError, match="unknown voice profile 'bob'.*narrator, nova, omar, sara"):
        narrator.resolve("bob", CFG)
    with pytest.raises(narrator.VoiceError, match="provider"):
        narrator.resolve("x", {"narrator": {"voices": {"x": {"provider": "acme"}}}})
    with pytest.raises(narrator.VoiceError, match="env: NAME"):
        narrator.resolve("x", {"narrator": {"voices": {"x": {"provider": "elevenlabs", "voice": {"keyring": "a"}}}}})


def test_edge_profile_uses_its_voice(env):
    p, d, note = narrator.speak("hello", narrator.resolve("narrator", CFG))
    assert env["edge"] == ["en-US-AvaNeural"] and note is None and env["calls"] == []


def test_elevenlabs_env_voice_id_resolves_through_keys(env):
    keys.save("ELEVENLABS_API_KEY", "fake-test-key")
    keys.save("ELEVENLABS_VOICE_ID_SARA", "fake-voice-sara")
    p, d, note = narrator.speak("مرحبا", narrator.resolve("sara", CFG))
    assert note is None and env["edge"] == [] and p.endswith(".mp3") and d == 1.5
    req = env["calls"][0]
    assert req.full_url == "https://api.elevenlabs.io/v1/text-to-speech/fake-voice-sara"
    assert req.get_header("Xi-api-key") == "fake-test-key"


def test_openai_profile_voice(env):
    keys.save("OPENAI_API_KEY", "fake-openai")
    narrator.speak("hi", narrator.resolve("nova", CFG))
    assert json.loads(env["calls"][0].data)["voice"] == "nova"


def test_402_falls_back_to_edge_once_with_a_note(env, capsys):
    keys.save("ELEVENLABS_API_KEY", "fake-test-key")
    calls = []
    env["monkeypatch"].setattr(narrator.urllib.request, "urlopen", lambda req, timeout=None: calls.append(1) or refuse(402)(req))
    v = narrator.resolve("omar", CFG)
    notes = []
    for line in ("one", "two", "three"):
        p, d = narrator.say(line, profile=v, notes=notes)
        assert p == "edge-en-US-AndrewNeural.mp3"
    out = capsys.readouterr().out
    assert out.count("[narrator]") == 1 and "HTTP 402 (paid plan required)" in out and "fake-test-key" not in out
    assert calls == [1]                     # refused once, not asked again for every line
    assert len(notes) == 1 and "402" in notes[0] and "edge" in notes[0]


@pytest.mark.parametrize("exc", [urllib.error.URLError("offline"), TimeoutError("slow")])
def test_offline_provider_falls_back(env, exc):
    keys.save("ELEVENLABS_API_KEY", "fake-test-key")

    def boom(req, timeout=None):
        raise exc
    env["monkeypatch"].setattr(narrator.urllib.request, "urlopen", boom)
    p, d, note = narrator.speak("hi", narrator.resolve("omar", CFG))
    assert p.startswith("edge-") and "not reachable" in note


def test_missing_key_falls_back_without_prompt(env):
    p, d, note = narrator.speak("hi", narrator.resolve("sara", CFG))
    assert env["edge"] == ["ar-EG-ShakirNeural"] and "no ELEVENLABS_API_KEY" in note and env["calls"] == []


def test_missing_voice_id_falls_back(env):
    keys.save("ELEVENLABS_API_KEY", "fake-test-key")
    p, d, note = narrator.speak("hi", narrator.resolve("sara", CFG))
    assert "no elevenlabs voice id" in note and env["calls"] == []


def test_record_narration_note_carries_the_fallback(env):
    keys.save("ELEVENLABS_API_KEY", "fake-test-key")
    env["monkeypatch"].setattr(narrator.urllib.request, "urlopen", refuse(402))
    steps = [{"do": "goto", "say": "Open the page"}, {"do": "click", "say": "Click save"}, {"do": "wait"}]
    clips, note = record.synthesize(steps, narrator.resolve("omar", CFG))
    assert set(clips) == {"Open the page", "Click save"} and "402" in note and "edge" in note


def test_record_note_when_nothing_refused(env):
    clips, note = record.synthesize([{"do": "goto", "say": "Open"}], narrator.resolve("narrator", CFG))
    assert note is None and clips["Open"] == ("edge-en-US-AvaNeural.mp3", 2.0)


def test_slides_voice_profile_or_raw_edge_name():
    assert slides_video.voice_for("sara", CFG)["provider"] == "elevenlabs"
    raw = slides_video.voice_for("en-GB-RyanNeural", CFG)
    assert raw["provider"] == "edge" and raw["voice"] == "en-GB-RyanNeural"
    assert slides_video.voice_for(None, CFG)["profile"] == "narrator"


def test_needed_lists_profile_keys():
    names = [n for n, _ in keys.needed(CFG)]
    assert names == ["ELEVENLABS_API_KEY", "ELEVENLABS_VOICE_ID_SARA", "OPENAI_API_KEY"]
    assert "ELEVENLABS_VOICE_ID" in [n for n, _ in keys.needed({"narrator": {"voices": {"x": {"provider": "elevenlabs"}}}})]


def write_cfg(tmp_path):
    import yaml
    p = tmp_path / "qa.config.yaml"
    p.write_text(yaml.safe_dump(CFG), encoding="utf-8")
    return str(p)


def test_cli_voices_never_resolves_env_ids(env, tmp_path, capsys):
    keys.save("ELEVENLABS_VOICE_ID_SARA", "fake-voice-sara")
    assert narrator.main(["voices", "--config", write_cfg(tmp_path)]) == 0
    out = json.loads(capsys.readouterr().out)
    assert out["default_voice"] == "narrator" and out["profiles"]["sara"]["voice"] == "from ELEVENLABS_VOICE_ID_SARA"
    assert "fake-voice-sara" not in json.dumps(out)


def test_cli_unknown_profile_exits_2(tmp_path):
    cfg = write_cfg(tmp_path)
    for script, args in (("narrator.py", ["voices"]), ("record.py", [os.path.join(ROOT, "templates", "qa-plan.example.json"), "--out", str(tmp_path / "o")]),
                         ("slides_video.py", [str(tmp_path / "none.json"), "--out", str(tmp_path / "o.mp4")])):
        r = subprocess.run([sys.executable, os.path.join(ROOT, "scripts", script), *args, "--voice", "bob", "--config", cfg],
                           capture_output=True, text=True, env=dict(os.environ, PYTHONIOENCODING="utf-8"), timeout=120)
        assert r.returncode == 2 and "unknown voice profile 'bob'" in r.stdout and "Traceback" not in r.stderr, script


def test_report_with_refused_profile_still_narrates(env, tmp_path, capsys):
    keys.save("ELEVENLABS_API_KEY", "fake-test-key")
    env["monkeypatch"].setattr(narrator.urllib.request, "urlopen", refuse(402))
    env["monkeypatch"].setattr(narrator.subprocess, "run", lambda *a, **k: open(a[0][-1], "wb").close())
    run = tmp_path / "run"
    run.mkdir()
    (run / "results.json").write_text(json.dumps({"name": "demo", "summary": "1 pass / 0 fail"}))
    assert narrator.main(["report", str(run), "--voice", "omar", "--config", write_cfg(tmp_path)]) == 0
    out = capsys.readouterr().out
    assert out.count("HTTP 402") == 1 and (run / "summary-en.mp3").exists() and "Traceback" not in out


def test_template_and_docs_hold_no_voice_ids_and_have_consent():
    tpl = open(os.path.join(ROOT, "templates", "qa.config.example.yaml"), encoding="utf-8").read()
    assert "default_voice:" in tpl and "{env: ELEVENLABS_VOICE_ID_" in tpl
    setup = open(os.path.join(ROOT, "commands", "qa-setup.md"), encoding="utf-8").read()
    skill = open(os.path.join(ROOT, "skills", "qa-narrate", "SKILL.md"), encoding="utf-8").read()
    for text in (setup, skill):
        assert "consent" in text.lower() and "--voice" in text
