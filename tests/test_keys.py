"""keys.py: missing API keys are asked for (masked window / hidden prompt), saved outside the repo, never printed."""
import json
import os
import subprocess
import sys

import pytest

import keys
import notify

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
KEYS = os.path.join(ROOT, "scripts", "keys.py")


def make_run(tmp_path):
    run = tmp_path / "run"
    run.mkdir()
    (run / "ledger.json").write_text(json.dumps({"goal": "g", "status": "met", "rounds": [{"summary": "1 pass / 0 fail"}]}))
    return run


@pytest.fixture
def store(tmp_path, monkeypatch):
    """An isolated user store, no keychain, prompts allowed, no stray env keys."""
    monkeypatch.setenv("SMEKIT_KEYS_DIR", str(tmp_path / "secrets"))
    monkeypatch.setenv("SMEKIT_NO_KEYRING", "1")
    monkeypatch.delenv("SMEKIT_NO_PROMPT", raising=False)
    for n in ("TELEGRAM_BOT_TOKEN", "ELEVENLABS_API_KEY", "ELEVENLABS_VOICE_ID", "OPENAI_API_KEY", "SK_TEST_KEY"):
        monkeypatch.delenv(n, raising=False)
    return tmp_path / "secrets" / "keys.json"


def test_env_wins_and_nothing_is_asked(store, monkeypatch):
    monkeypatch.setenv("SK_TEST_KEY", "  from-env​ ")
    asked = []
    assert keys.get("SK_TEST_KEY", asker=lambda n, r: asked.append(n)) == "from-env"
    assert asked == [] and keys.where("SK_TEST_KEY") == "env"


def test_missing_key_is_asked_once_then_saved(store):
    asked = []
    v = keys.get("SK_TEST_KEY", "why", asker=lambda n, r: asked.append((n, r)) or "abc123")
    assert v == "abc123" and asked == [("SK_TEST_KEY", "why")]
    assert json.loads(store.read_text())["SK_TEST_KEY"] == "abc123"
    # second call: found in the store, no second question
    assert keys.get("SK_TEST_KEY", asker=lambda n, r: pytest.fail("asked twice")) == "abc123"
    assert keys.where("SK_TEST_KEY") == "file"


def test_cancel_saves_nothing(store):
    assert keys.get("SK_TEST_KEY", asker=lambda n, r: "") is None
    assert keys.get("SK_TEST_KEY", asker=lambda n, r: None) is None
    assert not store.exists()


def test_no_prompt_mode_never_asks(store, monkeypatch):
    monkeypatch.setenv("SMEKIT_NO_PROMPT", "1")
    assert keys.get("SK_TEST_KEY", asker=lambda n, r: pytest.fail("prompted in no-prompt mode")) is None


def test_bad_names_rejected(store):
    for bad in ("", "has space", "../etc", "a-b"):
        with pytest.raises(ValueError):
            keys.save(bad, "x")


def test_store_is_outside_repo_and_guarded(store):
    keys.save("SK_TEST_KEY", "abc")
    assert not str(store).startswith(ROOT)
    import hook_guard
    default = keys.store_file({}).replace("\\", "/")
    assert hook_guard.classify_command(f"cat {default}", ROOT)[0] == "deny"
    assert hook_guard.classify_read(default)[0] == "deny"


def test_delete(store):
    keys.save("SK_TEST_KEY", "abc")
    assert keys.delete("SK_TEST_KEY") == ["file"]
    assert keys.lookup("SK_TEST_KEY") is None


def test_needed_reads_enabled_channels_and_narrator():
    cfg = {"notify": {"telegram": {"enabled": True, "token": {"env": "TELEGRAM_BOT_TOKEN"}, "chat_id": "1"},
                      "slack": {"enabled": False, "webhook_url": {"env": "SLACK_WEBHOOK_URL"}}},
           "narrator": {"provider": "elevenlabs"}}
    names = [n for n, _ in keys.needed(cfg)]
    assert names == ["TELEGRAM_BOT_TOKEN", "ELEVENLABS_API_KEY", "ELEVENLABS_VOICE_ID"]


def test_notify_secret_uses_saved_key(store):
    keys.save("TELEGRAM_BOT_TOKEN", "123:saved")
    assert notify.secret({"env": "TELEGRAM_BOT_TOKEN"}) == "123:saved"
    # an explicit env dict (tests, dry plans) stays hermetic: no stored-key fallback
    assert notify.secret({"env": "TELEGRAM_BOT_TOKEN"}, {}) is None


def test_send_asks_for_missing_key_then_sends(store, tmp_path):
    run = make_run(tmp_path)
    cfg = {"notify": {"telegram": {"enabled": True, "token": {"env": "TELEGRAM_BOT_TOKEN"}, "chat_id": "42"}}}
    os.environ["SMEKIT_STATE_DIR"] = str(tmp_path / "state")
    calls, asked = [], []
    try:
        res = notify.deliver(str(run), cfg, send=True, out=lambda *a: None,
                             http_fn=lambda *a, **k: calls.append(a) or {"ok": True},
                             asker=lambda n, r: asked.append(n) or "999:asked")
    finally:
        os.environ.pop("SMEKIT_STATE_DIR", None)
    assert asked == ["TELEGRAM_BOT_TOKEN"]
    assert res[0]["status"] == "SENT", res
    assert calls and "999:asked" in calls[0][1]  # the bot token is part of the Telegram URL
    assert keys.where("TELEGRAM_BOT_TOKEN") == "file"


def test_send_cancelled_fails_with_fix_hint(store, tmp_path):
    run = make_run(tmp_path)
    cfg = {"notify": {"telegram": {"enabled": True, "token": {"env": "TELEGRAM_BOT_TOKEN"}, "chat_id": "42"}}}
    res = notify.deliver(str(run), cfg, send=True, out=lambda *a: None,
                         http_fn=lambda *a, **k: pytest.fail("sent without a key"), asker=lambda n, r: "")
    assert res[0]["status"] == "FAIL" and "keys.py set" in res[0]["detail"]


def test_dry_run_never_asks(store, tmp_path):
    run = make_run(tmp_path)
    cfg = {"notify": {"telegram": {"enabled": True, "token": {"env": "TELEGRAM_BOT_TOKEN"}, "chat_id": "42"}}}
    res = notify.deliver(str(run), cfg, send=False, out=lambda *a: None, asker=lambda n, r: pytest.fail("asked on dry run"))
    assert res[0]["status"] == "DRY-RUN"


def test_narrator_asks_for_elevenlabs_key(store, monkeypatch):
    import narrator
    asked = []
    monkeypatch.setattr(keys, "_ask_window", lambda n, r: asked.append(n) or f"val-{n}")
    monkeypatch.setattr(narrator, "_http_tts", lambda text, prov, voice: (prov, voice))
    assert narrator.say("hello", prov="elevenlabs") == ("elevenlabs", "val-ELEVENLABS_VOICE_ID")
    assert asked == ["ELEVENLABS_API_KEY", "ELEVENLABS_VOICE_ID"]


def test_cli_never_prints_values(store, tmp_path):
    keys.save("SK_TEST_KEY", "supersecretvalue")
    cfg = tmp_path / "qa.config.yaml"
    cfg.write_text("notify:\n  telegram:\n    enabled: true\n    token: {env: TELEGRAM_BOT_TOKEN}\n    chat_id: '1'\n")
    env = dict(os.environ, PYTHONIOENCODING="utf-8")
    out_list = subprocess.run([sys.executable, KEYS, "list"], capture_output=True, text=True, env=env).stdout
    out_check = subprocess.run([sys.executable, KEYS, "check", "--config", str(cfg)], capture_output=True, text=True, env=env)
    assert "SK_TEST_KEY: file" in out_list and "supersecretvalue" not in out_list
    assert "TELEGRAM_BOT_TOKEN: MISSING" in out_check.stdout and out_check.returncode == 1
    nop = subprocess.run([sys.executable, KEYS, "set", "SK_TEST_KEY"], capture_output=True, text=True,
                         env=dict(env, SMEKIT_NO_PROMPT="1"))
    assert nop.returncode == 2 and "prompts are off" in nop.stdout


# ---- regression tests for the independent review (one per confirmed problem)
def test_cancel_is_remembered_for_the_process(store):
    asked = []
    for _ in range(3):
        assert keys.get("SK_TEST_KEY", asker=lambda n, r: asked.append(n) or "") is None
    assert asked == ["SK_TEST_KEY"]


def test_corrupt_store_is_never_wiped(store):
    store.parent.mkdir(parents=True, exist_ok=True)
    store.write_text('{"A_KEY": "a", "B_KEY": "b",}')
    with pytest.raises(keys.StoreError):
        keys.save("C_KEY", "c")
    assert store.read_text() == '{"A_KEY": "a", "B_KEY": "b",}'
    # asking still works for this run, the store stays untouched
    assert keys.get("C_KEY", asker=lambda n, r: "c-value") == "c-value"
    assert store.read_text() == '{"A_KEY": "a", "B_KEY": "b",}'


def test_failed_save_leaves_no_plaintext_tmp(store):
    store.mkdir(parents=True)  # keys.json is a directory: the write must fail cleanly
    with pytest.raises(keys.StoreError):
        keys.save("D_KEY", "ddd-secret")
    assert not os.path.exists(str(store) + ".tmp")


def test_invalid_name_is_not_echoed(store):
    with pytest.raises(ValueError) as exc:
        keys.save("123456789:AAHsecretTOKEN", "x")
    assert "AAHsecret" not in str(exc.value)


def test_dry_run_masks_stored_secret_urls(store, tmp_path):
    keys.save("SLACK_WEBHOOK_URL", "https://hooks.slack.com/services/T0/B0/SECRETSLACKPART")
    lines = []
    cfg = {"notify": {"slack": {"enabled": True, "webhook_url": {"env": "SLACK_WEBHOOK_URL"}}}}
    notify.deliver(str(make_run(tmp_path)), cfg, send=False, out=lines.append)
    printed = "\n".join(lines)
    assert "SECRETSLACKPART" not in printed and "<SECRET>" in printed


@pytest.mark.parametrize("cmd", [
    "cat ~/.config/shipshape/secrets/*",
    "cd ~/.config/shipshape/secrets && cat keys.json",
    "cat $SMEKIT_KEYS_DIR/keys.json",
    "python -c \"print(open('C:/Users/x/.config/shipshape/secrets/keys.json').read())\"",
    r"type C:\Users\x\.config\shipshape\secrets\keys.json",
])
def test_guard_blocks_key_store_reads(cmd):
    import hook_guard
    assert (hook_guard.classify_command(cmd, ROOT) or ("allow",))[0] == "deny"


@pytest.mark.parametrize("cmd", ["python scripts/keys.py list", "python scripts/keys.py set ELEVENLABS_API_KEY", "cat README.md"])
def test_guard_allows_key_cli(cmd):
    import hook_guard
    assert hook_guard.classify_command(cmd, ROOT) is None


def test_suite_never_touches_real_store():
    # the autouse fixture in conftest points every test at a temp store with prompts off
    assert os.environ["SMEKIT_NO_PROMPT"] == "1" and "_keys" in os.environ["SMEKIT_KEYS_DIR"]


# ---- /qa-setup interview: a key pasted in the chat is saved from stdin, never echoed
def test_set_from_stdin_saves_without_echo(store):
    env = dict(os.environ, PYTHONIOENCODING="utf-8")
    r = subprocess.run([sys.executable, KEYS, "set", "ELEVENLABS_API_KEY", "--stdin"], input="  sk_pasted_in_chat_123\n",
                       capture_output=True, text=True, env=env)
    assert r.returncode == 0 and "saved (file)" in r.stdout and "sk_pasted" not in r.stdout + r.stderr
    assert keys.lookup("ELEVENLABS_API_KEY") == "sk_pasted_in_chat_123"
    empty = subprocess.run([sys.executable, KEYS, "set", "ELEVENLABS_API_KEY", "--stdin"], input="", capture_output=True, text=True, env=env)
    assert empty.returncode == 1


def test_voices_needs_a_key(store):
    r = subprocess.run([sys.executable, KEYS, "voices"], capture_output=True, text=True, env=dict(os.environ, PYTHONIOENCODING="utf-8"))
    assert r.returncode == 1 and "MISSING" in r.stdout


def test_setup_command_never_writes_keys_into_project():
    text = open(os.path.join(ROOT, "commands", "qa-setup.md"), encoding="utf-8").read()
    assert "--stdin" in text and "never" in text.lower() and "keys.py voices" in text
