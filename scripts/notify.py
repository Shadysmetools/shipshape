#!/usr/bin/env python3
"""Deliver a QA run (summary + video + report) to the channels a project lists
in qa.config.yaml. DRY-RUN BY DEFAULT: it prints what it would send.

    python scripts/notify.py <run_dir> [--config qa.config.yaml] [--lang en|ar] [--send] [--only telegram]

Channels: telegram, whatsapp (meta | twilio), slack, email, webhook.
- Only channels present AND enabled in the project config are used. A channel
  name that is not in the config is refused (the plain-language hook enforces
  the same in conversation).
- Secrets come from environment variables, or from keys the user saved with
  scripts/keys.py (OS keychain or ~/.config/shipshape/secrets): the config holds
  key NAMES, never values. A real --send asks for a missing key once.
- File-size limits are respected per channel: the video is compressed with
  ffmpeg if it is too big, then a link is sent instead if it is still too big.
- Security findings are never sent in detail: only "N security findings, see
  the private report".
- --send is required for real delivery. Without it nothing leaves the machine.
"""
from __future__ import annotations

import argparse
import functools
import json
import mimetypes
import random
import re
import time
import os
import shutil
import smtplib
import ssl
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request
import uuid
from email.message import EmailMessage

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import keys  # noqa: E402

MB = 1024 * 1024
LIMITS = {"telegram": 50 * MB, "whatsapp": 16 * MB, "slack": 0, "email": 20 * MB, "webhook": 0}
CAPTION_MAX = {"telegram": 1024, "whatsapp": 1024}
TEMPLATES = {
    "en": "QA: {goal}\nResult: {summary}\nVerdict: {verdict}\nRun: {run}{security}{link}",
    "ar": "اختبار الجودة: {goal}\nالنتيجة: {summary}\nالحكم: {verdict}\nالتشغيل: {run}{security}{link}",
}


# ------------------------------------------------------------- config + secrets
class ConfigError(Exception):
    """qa.config.yaml is unusable; the message is one readable line."""


SECRET_FIELDS = ("token", "webhook_url", "url", "password", "account_sid", "auth_token")


def validate_config(cfg, path="qa.config.yaml"):
    """Check the shapes notify.py relies on. Raises ConfigError with the exact key path."""
    if not isinstance(cfg, dict):
        raise ConfigError(f"config error in {path}: the top level must be a mapping")
    notify = cfg.get("notify") or {}
    if not isinstance(notify, dict):
        raise ConfigError(f"config error at notify: expected a mapping of channels")
    for name, ch in notify.items():
        if ch is None:
            continue
        if not isinstance(ch, dict):
            raise ConfigError(f"config error at notify.{name}: expected a mapping (enabled, token, ...)")
        if "enabled" in ch and not isinstance(ch["enabled"], bool):
            raise ConfigError(f"config error at notify.{name}.enabled: expected true or false, got {ch['enabled']!r}")
        for field in SECRET_FIELDS:
            spec = ch.get(field)
            if spec is None or isinstance(spec, str):
                continue
            ok = isinstance(spec, dict) and len(spec) == 1 and (("env" in spec and isinstance(spec["env"], str)) or
                                                                 ("keyring" in spec and isinstance(spec["keyring"], str) and "/" in spec["keyring"]))
            if not ok:
                raise ConfigError(f"config error at notify.{name}.{field}: expected {{env: NAME}} or {{keyring: service/user}}, got {spec!r}")
        for field in ("to",):
            if field in ch and not isinstance(ch[field], list):
                raise ConfigError(f"config error at notify.{name}.{field}: expected a list of recipients")
    import video_trim
    try:
        video_trim.settings(cfg.get("video"))
    except video_trim.ConfigError as exc:
        raise ConfigError(str(exc)) from None
    return cfg


def load_config(path):
    try:
        with open(path, encoding="utf-8-sig") as fh:  # tolerate a BOM written by Windows editors
            text = fh.read()
    except FileNotFoundError:
        raise ConfigError(f"config file not found: {path}") from None
    try:
        if path.endswith((".yaml", ".yml")):
            import yaml  # PyYAML
            cfg = yaml.safe_load(text) or {}
        else:
            cfg = json.loads(text)
    except Exception as exc:  # yaml.YAMLError / json.JSONDecodeError: report the place, not a traceback
        mark = getattr(exc, "problem_mark", None)
        where = f" (line {mark.line + 1}, column {mark.column + 1})" if mark is not None else ""
        raise ConfigError(f"config error in {path}: not valid {'YAML' if path.endswith(('.yaml', '.yml')) else 'JSON'}{where}") from None
    return validate_config(cfg, path)


def secret(spec, env=None):
    """spec: {"env": "NAME"} or {"keyring": "service/user"} or "NAME" (env var name)."""
    env = os.environ if env is None else env
    if isinstance(spec, str):
        spec = {"env": spec}
    if not spec:
        return None
    if spec.get("env"):
        # env var first, then the key the user saved with keys.py (keychain or ~/.config/shipshape)
        return clean(env.get(spec["env"])) or (keys.lookup(spec["env"], env) if env is os.environ else None)
    if spec.get("keyring"):
        try:
            import keyring
            service, user = spec["keyring"].split("/", 1)
            return keyring.get_password(service, user)
        except Exception:  # noqa: BLE001
            return None
    return None


ZERO_WIDTH = "[" + "".join(chr(c) for c in (0xFEFF, 0x200B, 0x200C, 0x200D, 0x2060)) + "]"


def clean(value):
    """Strip BOMs, zero-width characters and whitespace that copy-paste puts around secrets and ids."""
    if value is None:
        return None
    return re.sub(ZERO_WIDTH, "", value).strip()


# ------------------------------------------------------------- message
def summary_text(run_dir, lang="en", link=None, template=None):
    led_path = os.path.join(run_dir, "ledger.json")
    if os.path.exists(led_path):
        led = json.load(open(led_path, encoding="utf-8"))
        goal, verdict = led.get("goal", ""), led.get("status", "")
        summary = led["rounds"][-1]["summary"] if led.get("rounds") else "no rounds yet"
        sec = led.get("security", {}).get("count")
    else:
        res = json.load(open(os.path.join(run_dir, "results.json"), encoding="utf-8"))
        goal, verdict, summary, sec = res.get("name", ""), "single run", res.get("summary", ""), None
    security = ""
    if sec:
        security = f"\nSecurity: {sec} finding(s), see the private report" if lang == "en" else f"\nالأمان: {sec} ملاحظة، راجع التقرير الخاص"
    tpl = template or TEMPLATES.get(lang, TEMPLATES["en"])
    return tpl.format(goal=goal, summary=summary, verdict=verdict, run=os.path.basename(os.path.abspath(run_dir)),
                      security=security, link=f"\n{link}" if link else "")


def find_video(run_dir):
    best = None
    for root, _d, files in os.walk(run_dir):
        for f in files:
            if f.endswith(".mp4") and not f.endswith(".original.mp4"):  # send the trimmed video, not the kept original
                p = os.path.join(root, f)
                if not best or os.path.getmtime(p) > os.path.getmtime(best):
                    best = p
    return best


def fit_video(path, limit, workdir):
    """Return a path under the size limit, compressing once if needed, or None."""
    if not path or not limit:
        return None
    if os.path.getsize(path) <= limit:
        return path
    if shutil.which("ffmpeg"):
        out = os.path.join(workdir, "compressed-" + os.path.basename(path))
        subprocess.run(["ffmpeg", "-y", "-v", "error", "-i", path, "-vf", "scale='min(1024,iw)':-2", "-c:v", "libx264", "-crf", "30",
                        "-preset", "veryfast", "-c:a", "aac", "-b:a", "96k", "-movflags", "+faststart", out], timeout=900, check=False)
        if os.path.exists(out) and os.path.getsize(out) <= limit:
            return out
    return None


# ------------------------------------------------------------- HTTP (injectable for tests)
def http(method, url, data=None, headers=None, timeout=120):
    req = urllib.request.Request(url, data=data, headers=headers or {}, method=method)
    with urllib.request.urlopen(req, timeout=timeout) as r:  # noqa: S310 (https endpoints from config)
        return r.status, r.read().decode("utf-8", "replace")


RETRY_STATUS = {429, 500, 502, 503, 504}


def with_retry(http_fn, method, url, data=None, headers=None, attempts=4, base=2.0, sleep=time.sleep):
    """Retry network errors, timeouts, 429 and 5xx (honouring Retry-After); never 400/401/403/404.
    The per-attempt timeout grows with the payload size: max(120, 60 + MB * 90) seconds."""
    size_mb = len(data or b"") / MB
    timeout = max(120, 60 + size_mb * 90)
    for i in range(attempts):
        try:
            return http_fn(method, url, data, headers, timeout=timeout)
        except urllib.error.HTTPError as exc:
            if exc.code not in RETRY_STATUS or i == attempts - 1:
                raise
            wait = float(exc.headers.get("Retry-After") or 0) if exc.headers else 0
        except (urllib.error.URLError, TimeoutError, ConnectionError, OSError):
            if i == attempts - 1:
                raise
            wait = 0
        sleep(max(wait, base * (2 ** i) + random.uniform(0, 1)))


def multipart(fields, files):
    boundary = uuid.uuid4().hex
    body = bytearray()
    for k, v in fields.items():
        body += f'--{boundary}\r\nContent-Disposition: form-data; name="{k}"\r\n\r\n{v}\r\n'.encode()
    for k, path in files.items():
        mime = mimetypes.guess_type(path)[0] or "application/octet-stream"
        body += f'--{boundary}\r\nContent-Disposition: form-data; name="{k}"; filename="{os.path.basename(path)}"\r\nContent-Type: {mime}\r\n\r\n'.encode()
        with open(path, "rb") as fh:
            body += fh.read()
        body += b"\r\n"
    body += f"--{boundary}--\r\n".encode()
    return bytes(body), f"multipart/form-data; boundary={boundary}"


# ------------------------------------------------------------- channels
def plan_telegram(ch, text, video, report, env):
    token = secret(ch.get("token"), env)
    base = f"https://api.telegram.org/bot{token or '<TOKEN>'}"
    common = {"chat_id": ch["chat_id"]}
    if ch.get("topic_id"):
        common["message_thread_id"] = ch["topic_id"]
    calls = []
    cap = text[:CAPTION_MAX["telegram"]]
    if video:
        calls.append(("POST", base + "/sendVideo", {**common, "caption": cap, "supports_streaming": "true"}, {"video": video}))
        if len(text) > len(cap):
            calls.append(("POST", base + "/sendMessage", {**common, "text": text}, {}))
    else:
        calls.append(("POST", base + "/sendMessage", {**common, "text": text}, {}))
    if report and ch.get("send_report", True):
        calls.append(("POST", base + "/sendDocument", {**common, "caption": "QA report (open offline)"}, {"document": report}))
    return calls, token


def plan_whatsapp(ch, text, video, report, env, link=None):
    calls = []
    if ch.get("provider", "meta") == "twilio":
        sid, tok = secret(ch.get("account_sid"), env), secret(ch.get("auth_token"), env)
        url = f"https://api.twilio.com/2010-04-01/Accounts/{sid or '<SID>'}/Messages.json"
        for to in ch["to"]:
            fields = {"From": ch["from"], "To": to, "Body": text[:1500]}
            if link:
                fields["MediaUrl"] = link
            calls.append(("POST", url, fields, {}))
        return calls, (sid and tok) and f"{sid}:{tok}"
    token = secret(ch.get("token"), env)
    url = f"https://graph.facebook.com/{ch.get('api_version', 'v21.0')}/{ch['phone_number_id']}/messages"
    for to in ch["to"]:
        tpl = ch.get("template", {})
        if tpl:  # business-initiated messages need an approved template
            calls.append(("POST", url, {"messaging_product": "whatsapp", "to": to, "type": "template",
                                        "template": {"name": tpl["name"], "language": {"code": tpl.get("language", "en")},
                                                     "components": [{"type": "body", "parameters": [{"type": "text", "text": text[:900]}]}]}}, {}))
        if link:
            calls.append(("POST", url, {"messaging_product": "whatsapp", "to": to, "type": "video",
                                        "video": {"link": link, "caption": text[:CAPTION_MAX["whatsapp"]]}}, {}))
    return calls, token


def plan_slack(ch, text, video, report, env, link=None):
    hook = secret(ch.get("webhook_url"), env)
    return [("POST", hook or "<SLACK_WEBHOOK_URL>", {"text": text}, {})], hook


def plan_webhook(ch, text, video, report, env, link=None, payload=None):
    url = secret(ch.get("url"), env) or ch.get("url_plain")
    return [("POST", url or "<WEBHOOK_URL>", payload or {"text": text}, {})], url


def store_path(env=None):
    env = os.environ if env is None else env
    base = env.get("SMEKIT_STATE_DIR") or os.path.join(os.path.expanduser("~"), ".cache", "smekit")
    os.makedirs(base, exist_ok=True)
    return os.path.join(base, "delivery-sent.json")


def load_sent(path):
    try:
        with open(path, encoding="utf-8") as fh:
            return set(json.load(fh))
    except (OSError, ValueError):
        return set()


def mark_sent(path, key):
    sent = load_sent(path)
    sent.add(key)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(sorted(sent), fh)
    os.replace(tmp, path)


def step_key(run_dir, channel, idx, url, fields, files):
    """Content key of one delivery step: same run, channel, step and content = already sent."""
    import hashlib
    blob = json.dumps([os.path.basename(os.path.abspath(run_dir)), channel, idx, redact(url), fields,
                       {k: (os.path.basename(v), os.path.getsize(v)) for k, v in (files or {}).items() if v and os.path.exists(v)}],
                      sort_keys=True, default=str)
    return hashlib.sha256(blob.encode()).hexdigest()


def ask_missing_keys(name, ch, asker=None):
    """Before a real send: ask the user (masked window / hidden prompt) for any key this channel names but nobody set."""
    for field, spec in ch.items():
        if isinstance(spec, dict) and isinstance(spec.get("env"), str) and not secret(spec):
            try:
                keys.get(spec["env"], f"Needed to send to {name} ({field}).", asker=asker)
            except ValueError:  # not a usable key name: the send then fails with the usual credential message
                pass


def deliver(run_dir, cfg, lang="en", send=False, only=None, env=None, http_fn=None, out=print, asker=None):
    """Plan (and with send=True, perform) delivery. Returns a list of per-channel results."""
    env = os.environ if env is None else env
    http_fn = http_fn or http
    channels = cfg.get("notify", {})
    results = []
    names = [only] if only else list(channels)
    for name in names:
        if name not in channels:
            results.append({"channel": name, "status": "REFUSED", "detail": "not listed in the project config"})
            continue
        ch = channels[name] or {}
        if not ch.get("enabled", False):
            results.append({"channel": name, "status": "SKIPPED", "detail": "disabled in config"})
            continue
        kind = ch.get("type", name)
        if send and env is os.environ:
            ask_missing_keys(name, ch, asker)
        link = cfg.get("report_link_base") and cfg["report_link_base"].rstrip("/") + "/" + os.path.basename(os.path.abspath(run_dir)) + "/report.html"
        text = summary_text(run_dir, ch.get("lang", lang), link, (ch.get("templates") or {}).get(ch.get("lang", lang)))
        report = os.path.join(run_dir, "report.html") if os.path.exists(os.path.join(run_dir, "report.html")) else None
        if report and LIMITS.get(kind) and os.path.getsize(report) > LIMITS[kind]:
            report = None
        video = fit_video(find_video(run_dir), LIMITS.get(kind, 0), run_dir)
        vlink = cfg.get("video_link_base") and find_video(run_dir) and cfg["video_link_base"].rstrip("/") + "/" + os.path.relpath(find_video(run_dir), os.path.dirname(os.path.abspath(run_dir))).replace("\\", "/")
        if kind == "telegram":
            calls, cred = plan_telegram(ch, text, video, report, env)
        elif kind == "whatsapp":
            calls, cred = plan_whatsapp(ch, text, video, report, env, vlink)
        elif kind == "slack":
            calls, cred = plan_slack(ch, text + (f"\nVideo: {vlink}" if vlink else ""), video, report, env)
        elif kind == "webhook":
            calls, cred = plan_webhook(ch, text, video, report, env, payload={"text": text, "video": vlink, "report": link})
        elif kind == "email":
            calls, cred = [("SMTP", ch.get("host", "<SMTP_HOST>"), {"to": ch.get("to", []), "subject": text.splitlines()[0]}, {"video": video, "report": report})], secret(ch.get("password"), env)
        else:
            results.append({"channel": name, "status": "REFUSED", "detail": f"unknown type {kind}"})
            continue
        secrets_used = [v for v in (secret(sp, env) for sp in ch.values() if isinstance(sp, dict) and sp.get("env")) if v and len(v) >= 6]
        mask = lambda t: functools.reduce(lambda acc, v: acc.replace(v, "<SECRET>"), secrets_used, t)  # noqa: E731
        shown = [(m, mask(redact(u)), {k: (v if k not in ("caption", "text") else v[:60] + "...") for k, v in f.items()} if isinstance(f, dict) else f,
                  {k: os.path.basename(v) for k, v in fl.items() if v}) for m, u, f, fl in calls]
        if not send:
            out(f"[dry-run] {name}: {len(calls)} call(s)")
            for c in shown:
                out(f"    {c[0]} {c[1]} fields={json.dumps(c[2], ensure_ascii=False)[:240]} files={c[3]}")
            results.append({"channel": name, "status": "DRY-RUN", "calls": len(calls), "video": bool(video), "link": bool(vlink)})
            continue
        if not cred:
            results.append({"channel": name, "status": "FAIL", "detail": "credential env var is not set (or save it with: python scripts/keys.py set <NAME>)"})
            continue
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        import stack_lock  # one sender per channel at a time (singleton per alert stream)
        lock = stack_lock.lock_path(f"notify-{name}")
        if not stack_lock.acquire(lock, "notify", wait=120, stale=1800, poll=2):
            results.append({"channel": name, "status": "FAIL", "detail": "another sender holds this channel"})
            continue
        spath = store_path(env)
        skipped = 0
        try:
            for idx, (method, url, fields, files) in enumerate(calls):
                key = step_key(run_dir, name, idx, url, fields, files)
                if key in load_sent(spath):  # never resend a step that already succeeded (resume / duplicate watcher)
                    skipped += 1
                    continue
                if method == "SMTP":
                    send_email(ch, text, files, cred)
                elif files:
                    body, ctype = multipart(fields, {k: v for k, v in files.items() if v})
                    with_retry(http_fn, "POST", url, body, {"Content-Type": ctype})
                elif kind == "whatsapp" and ch.get("provider", "meta") == "twilio":
                    import base64
                    auth = base64.b64encode(cred.encode()).decode()
                    with_retry(http_fn, "POST", url, urllib.parse.urlencode(fields).encode(), {"Authorization": f"Basic {auth}", "Content-Type": "application/x-www-form-urlencoded"})
                elif kind == "telegram":
                    with_retry(http_fn, "POST", url, urllib.parse.urlencode(fields).encode(), {"Content-Type": "application/x-www-form-urlencoded"})
                else:
                    headers = {"Content-Type": "application/json"}
                    if kind == "whatsapp":
                        headers["Authorization"] = f"Bearer {cred}"
                    with_retry(http_fn, "POST", url, json.dumps(fields).encode(), headers)
                mark_sent(spath, key)
            results.append({"channel": name, "status": "SENT", "calls": len(calls) - skipped, "already_sent": skipped})
        except Exception as exc:  # noqa: BLE001
            results.append({"channel": name, "status": "FAIL", "detail": redact(str(exc))[:200]})
        finally:
            stack_lock.release(lock)
    return results


def redact(s):
    import re
    s = re.sub(r"/bot[^/]+/", "/bot<TOKEN>/", s or "")
    return re.sub(r"(Accounts/)[^/]+", r"\1<SID>", s)


def send_email(ch, text, files, password):
    msg = EmailMessage()
    msg["Subject"] = text.splitlines()[0]
    msg["From"] = ch["from"]
    msg["To"] = ", ".join(ch["to"])
    msg.set_content(text)
    for path in files.values():
        if path:
            ctype = (mimetypes.guess_type(path)[0] or "application/octet-stream").split("/")
            with open(path, "rb") as fh:
                msg.add_attachment(fh.read(), maintype=ctype[0], subtype=ctype[1], filename=os.path.basename(path))
    with smtplib.SMTP(ch["host"], int(ch.get("port", 587)), timeout=120) as s:
        s.starttls(context=ssl.create_default_context())
        s.login(ch.get("user", ch["from"]), password)
        s.send_message(msg)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("run_dir")
    ap.add_argument("--config", default="qa.config.yaml")
    ap.add_argument("--lang", default="en", choices=("en", "ar"))
    ap.add_argument("--send", action="store_true", help="really send (default: dry-run)")
    ap.add_argument("--only")
    a = ap.parse_args(argv)
    sys.stdout.reconfigure(encoding="utf-8")
    try:
        cfg = load_config(a.config)
    except ConfigError as exc:
        print(f"ERROR: {exc}")
        return 2
    if not os.path.isdir(a.run_dir):
        print(f"ERROR: run folder not found: {a.run_dir}")
        return 2
    res = deliver(a.run_dir, cfg, a.lang, a.send, a.only)
    for r in res:
        print(f"{r['channel']}: {r['status']}" + (f" ({r.get('detail')})" if r.get("detail") else ""))
    return 1 if any(r["status"] in ("FAIL", "REFUSED") for r in res) else 0


if __name__ == "__main__":
    sys.exit(main())
