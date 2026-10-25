#!/usr/bin/env python3
"""ShipShape keys: find an API key, and ask the user for it when it is missing.

Lookup order for a key NAME (e.g. ELEVENLABS_API_KEY, TELEGRAM_BOT_TOKEN):
  1. the environment variable NAME
  2. the OS keychain (Windows Credential Manager / macOS Keychain) via the optional "keyring" package
  3. the user's own store: ~/.config/shipshape/secrets/keys.json (outside every repo, owner-only)
  4. ask the user: a masked pop-up window (tkinter) or, in a terminal, a hidden prompt (getpass).
     The answer is saved to the keychain when available, otherwise to the user store.

The key never goes through the chat: Claude runs `keys.py set NAME` and the user types the key into the
window. Nothing here prints a key; `list` and `check` print names and where they are stored.
Prompts are off when SMEKIT_NO_PROMPT=1 (CI, scheduled runs, tests).

  python scripts/keys.py set ELEVENLABS_API_KEY        # ask and save
  python scripts/keys.py check --config qa.config.yaml # which keys this project needs, which are missing
  python scripts/keys.py list                          # stored names (never values)
  python scripts/keys.py delete ELEVENLABS_API_KEY
"""
import argparse
import json
import os
import re
import sys

SERVICE = "shipshape"
_DECLINED = set()  # names the user cancelled in this process: never asked twice
NAME_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,99}$")
ZERO_WIDTH = "[" + "".join(chr(c) for c in (0xFEFF, 0x200B, 0x200C, 0x200D, 0x2060)) + "]"
# Keys the narrator can use, beyond the channels named in qa.config.yaml
NARRATOR_KEYS = {"openai": ["OPENAI_API_KEY"], "elevenlabs": ["ELEVENLABS_API_KEY", "ELEVENLABS_VOICE_ID"]}
HINTS = {
    "TELEGRAM_BOT_TOKEN": "Telegram bot token from @BotFather",
    "ELEVENLABS_API_KEY": "ElevenLabs API key (Profile > API keys)",
    "ELEVENLABS_VOICE_ID": "ElevenLabs voice id (Voices > the voice > ID)",
    "OPENAI_API_KEY": "OpenAI API key",
    "KNOWCAP_API_KEY": "Knowcap API key (Settings > API Keys)",
}


def clean(value):
    if value is None:
        return None
    value = re.sub(ZERO_WIDTH, "", value).strip()
    return value or None


def store_file(env=None):
    env = os.environ if env is None else env
    base = env.get("SMEKIT_KEYS_DIR") or os.path.join(os.path.expanduser("~"), ".config", "shipshape", "secrets")
    return os.path.join(base, "keys.json")


def _check_name(name):
    if not NAME_RE.match(name or ""):
        raise ValueError("not a valid key name (letters, digits and _ only, e.g. ELEVENLABS_API_KEY)")


def _keyring():
    if os.environ.get("SMEKIT_NO_KEYRING") == "1":
        return None
    try:
        import keyring
        keyring.get_keyring()
        return keyring
    except Exception:  # noqa: BLE001 - optional dependency
        return None


class StoreError(Exception):
    pass


def _read_store(env=None, strict=False):
    """The user store. A missing file is empty; a corrupt one is empty for reads and an error for writes."""
    path = store_file(env)
    if not os.path.exists(path):
        return {}
    try:
        with open(path, encoding="utf-8-sig") as fh:
            data = json.load(fh)
        if not isinstance(data, dict):
            raise ValueError("not a JSON object")
        return data
    except (OSError, ValueError) as exc:
        if strict:
            raise StoreError(f"the key store {path} is unreadable ({type(exc).__name__}); fix or move it, nothing was changed") from None
        return {}


def _write_store(data, env=None):
    path = store_file(env)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    try:
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(data, fh, indent=1, sort_keys=True)
        os.replace(tmp, path)
    except OSError as exc:
        try:
            os.remove(tmp)
        except OSError:
            pass
        raise StoreError(f"could not save to {path} ({type(exc).__name__})") from None
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass


def where(name, env=None):
    """Where a key is found: 'env', 'keychain', 'file' or None. Never returns the value."""
    env = os.environ if env is None else env
    if clean(env.get(name)):
        return "env"
    kr = _keyring()
    if kr:
        try:
            if clean(kr.get_password(SERVICE, name)):
                return "keychain"
        except Exception:  # noqa: BLE001
            pass
    if clean(_read_store(env).get(name)):
        return "file"
    return None


def lookup(name, env=None):
    """The stored value of a key, without asking. None if it is nowhere."""
    env = os.environ if env is None else env
    value = clean(env.get(name))
    if value:
        return value
    kr = _keyring()
    if kr:
        try:
            value = clean(kr.get_password(SERVICE, name))
            if value:
                return value
        except Exception:  # noqa: BLE001
            pass
    return clean(_read_store(env).get(name))


def save(name, value, env=None):
    """Save to the keychain when available, else to the user store. Returns where it went."""
    _check_name(name)
    value = clean(value)
    if not value:
        raise ValueError("empty key")
    kr = _keyring()
    if kr:
        try:
            kr.set_password(SERVICE, name, value)
            return "keychain"
        except Exception:  # noqa: BLE001 - fall back to the file
            pass
    data = _read_store(env, strict=True)
    data[name] = value
    _write_store(data, env)
    return "file"


def delete(name, env=None):
    removed = []
    kr = _keyring()
    if kr:
        try:
            if kr.get_password(SERVICE, name) is not None:
                kr.delete_password(SERVICE, name)
                removed.append("keychain")
        except Exception:  # noqa: BLE001
            pass
    data = _read_store(env, strict=True)
    if name in data:
        del data[name]
        _write_store(data, env)
        removed.append("file")
    return removed


def can_prompt(env=None):
    env = os.environ if env is None else env
    return env.get("SMEKIT_NO_PROMPT") != "1"


def _ask_window(name, reason):
    """Masked pop-up. Returns the text, '' if cancelled, None if no window can be shown."""
    try:
        import tkinter as tk
    except Exception:  # noqa: BLE001
        return None
    try:
        root = tk.Tk()
    except Exception:  # noqa: BLE001 - no display
        return None
    result = {"value": ""}
    root.title("ShipShape needs a key")
    root.attributes("-topmost", True)
    root.resizable(False, False)
    frame = tk.Frame(root, padx=16, pady=14)
    frame.pack()
    tk.Label(frame, text=f"ShipShape needs {name}", font=("Segoe UI", 11, "bold")).pack(anchor="w")
    tk.Label(frame, text=reason or HINTS.get(name, "Paste the key below."), wraplength=380, justify="left").pack(anchor="w", pady=(4, 8))
    entry = tk.Entry(frame, show="*", width=48)
    entry.pack(fill="x")
    tk.Label(frame, text="It is saved on this computer only (keychain or your user folder), never in the project.",
             wraplength=380, justify="left", fg="#555").pack(anchor="w", pady=(6, 10))
    buttons = tk.Frame(frame)
    buttons.pack(anchor="e")

    def ok(_=None):
        result["value"] = entry.get()
        root.destroy()

    tk.Button(buttons, text="Cancel", width=10, command=root.destroy).pack(side="right", padx=(6, 0))
    tk.Button(buttons, text="Save", width=10, command=ok).pack(side="right")
    root.bind("<Return>", ok)
    root.bind("<Escape>", lambda _: root.destroy())
    root.after(300_000, root.destroy)  # gives up after 5 minutes: no prompt waits forever
    entry.focus_force()
    root.mainloop()
    return result["value"]


def _ask_terminal(name, reason):
    if not (sys.stdin and sys.stdin.isatty()):
        return None
    import getpass
    print(f"ShipShape needs {name}. {reason or HINTS.get(name, '')}".strip(), file=sys.stderr)
    return getpass.getpass(f"{name} (hidden, Enter to skip): ")


def ask(name, reason="", env=None, asker=None):
    """Ask the user for a key and save it. Returns the value, or None when skipped / not possible."""
    _check_name(name)
    if not can_prompt(env) or name in _DECLINED:
        return None
    if asker is not None:
        value = asker(name, reason)
    else:
        value = _ask_window(name, reason)
        if value is None:
            value = _ask_terminal(name, reason)
    value = clean(value)
    if not value:
        _DECLINED.add(name)
        return None
    try:
        save(name, value, env)
    except StoreError as exc:
        print(f"[keys] {exc}; using the key for this run only", file=sys.stderr)
    return value


def get(name, reason="", prompt=True, env=None, asker=None):
    """The key from env / keychain / user store; ask for it when missing and prompting is allowed."""
    value = lookup(name, env)
    if value or not prompt:
        return value
    return ask(name, reason, env, asker)


def needed(cfg):
    """Key names a project config refers to: every {env: NAME} under notify, plus narrator provider keys."""
    names = []
    for ch_name, ch in ((cfg or {}).get("notify") or {}).items():
        if not isinstance(ch, dict) or not ch.get("enabled", False):
            continue
        for field, spec in ch.items():
            if isinstance(spec, dict) and isinstance(spec.get("env"), str):
                names.append((spec["env"], f"notify.{ch_name}.{field}"))
    prov = (((cfg or {}).get("narrator") or {}).get("provider") or os.environ.get("SMEKIT_TTS_PROVIDER") or "edge").lower()
    for n in NARRATOR_KEYS.get(prov, []):
        names.append((n, f"narrator.{prov}"))
    seen, out = set(), []
    for n, used in names:
        if n not in seen:
            seen.add(n)
            out.append((n, used))
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("set", help="ask for a key and save it")
    s.add_argument("name")
    s.add_argument("--reason", default="")
    s.add_argument("--stdin", action="store_true", help="read the key from standard input (the user pasted it in the chat)")
    c = sub.add_parser("check", help="which keys a project needs and which are missing")
    c.add_argument("--config", default="qa.config.yaml")
    c.add_argument("--ask", action="store_true", help="ask for each missing key")
    sub.add_parser("list", help="stored key names (never values)")
    sub.add_parser("voices", help="ElevenLabs voices this key can use: name, id, type (no key printed)")
    d = sub.add_parser("delete")
    d.add_argument("name")
    a = ap.parse_args(argv)
    sys.stdout.reconfigure(encoding="utf-8")

    if a.cmd == "set":
        try:
            _check_name(a.name)
        except ValueError as exc:
            print(f"ERROR: {exc}")
            return 2
        if a.stdin:
            value = clean(sys.stdin.read())
            if not value:
                print(f"{a.name}: nothing on stdin, not saved")
                return 1
            try:
                print(f"{a.name}: saved ({save(a.name, value)})")
            except StoreError as exc:
                print(f"ERROR: {exc}")
                return 2
            return 0
        if not can_prompt():
            print("ERROR: prompts are off (SMEKIT_NO_PROMPT=1); set the environment variable instead")
            return 2
        try:
            got = ask(a.name, a.reason)
        except StoreError as exc:
            print(f"ERROR: {exc}")
            return 2
        if got is None:
            print(f"{a.name}: not saved (cancelled, or no window/terminal to ask in)")
            return 1
        print(f"{a.name}: saved ({where(a.name)})")
        return 0

    if a.cmd == "check":
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        import notify
        try:
            cfg = notify.load_config(a.config)
        except notify.ConfigError as exc:
            print(f"ERROR: {exc}")
            return 2
        missing = 0
        for name, used in needed(cfg):
            w = where(name)
            if not w and a.ask:
                if ask(name, f"Needed by {used} in {os.path.basename(a.config)}.") is not None:
                    w = where(name)
            print(f"{name}: {'ok (' + w + ')' if w else 'MISSING'}  <- {used}")
            missing += 0 if w else 1
        print(f"{missing} missing" if missing else "all keys found")
        return 1 if missing else 0

    if a.cmd == "list":
        names = sorted(_read_store().keys())
        for n in names:
            print(f"{n}: file")
        kr = _keyring()
        print(f"keychain: {'available (service ' + SERVICE + ')' if kr else 'not available (pip install keyring)'}")
        print(f"user store: {store_file()}")
        return 0

    if a.cmd == "voices":
        key = lookup("ELEVENLABS_API_KEY")
        if not key:
            print("ELEVENLABS_API_KEY: MISSING (save it first: keys.py set ELEVENLABS_API_KEY)")
            return 1
        import urllib.error
        import urllib.request
        try:
            req = urllib.request.Request("https://api.elevenlabs.io/v1/voices", headers={"xi-api-key": key})
            with urllib.request.urlopen(req, timeout=30) as r:
                voices = json.load(r).get("voices", [])
        except urllib.error.HTTPError as exc:
            print(f"ElevenLabs refused the key: HTTP {exc.code}")
            return 1
        except OSError as exc:
            print(f"ElevenLabs not reachable: {type(exc).__name__}")
            return 1
        for v in voices:
            kind = v.get("category", "")
            note = "  (library voice: needs a paid ElevenLabs plan via the API)" if kind == "professional" else ""
            print(f"{v.get('name', '?')} | {v.get('voice_id', '?')} | {kind}{note}")
        print(f"{len(voices)} voices")
        return 0

    if a.cmd == "delete":
        try:
            removed = delete(a.name)
        except StoreError as exc:
            print(f"ERROR: {exc}")
            return 2
        print(f"{a.name}: removed from {', '.join(removed)}" if removed else f"{a.name}: not stored")
        return 0
    return 2


if __name__ == "__main__":
    sys.exit(main())
