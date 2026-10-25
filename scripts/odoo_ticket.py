#!/usr/bin/env python3
"""Odoo tickets as QA input and output: read a ticket, post the result, move it, watch stages.

    python scripts/odoo_ticket.py read  <ticket> [--config qa.config.yaml]
    python scripts/odoo_ticket.py post  <ticket> --run qa-runs/<run> [--send]
    python scripts/odoo_ticket.py move  <ticket> --stage "<name>" [--send]
    python scripts/odoo_ticket.py watch [--launch] [--once] [--interval 300] [--minutes 60] [--include-existing]

read   description, stage and log notes as plain text. Read-only.
post   ONE log note on the ticket: "N pass / M fail / K flaky / B blocked", the bug list and the video
       link, after the privacy filter. DRY-RUN BY DEFAULT: --send really posts (the hook guard asks the owner).
move   set the ticket's stage by name. Dry-run by default; --send writes, then reads back.
watch  poll the configured model for tickets newly in odoo.trigger.stages. At most one run per ticket
       per stage entry (state file qa-runs/odoo-watch.json). Without --launch it only prints what it
       would test; with --launch it writes the ticket analysis to qa-runs/odoo-tickets/ and starts the
       qa run (odoo.trigger.launch, default: claude -p "/qa-goal <goal>"). Watch never writes to Odoo.

Settings: the odoo: block of qa.config.yaml (templates/qa.config.example.yaml). The API key is the
user's own: env var ODOO_API_KEY, or saved with `keys.py set ODOO_API_KEY`; asked for once when missing.
Dry runs never contact Odoo. Transport: Odoo's JSON-RPC endpoint /jsonrpc (stdlib only).
"""
from __future__ import annotations

import argparse
import datetime as dt
import html
import html.parser
import itertools
import json
import os
import re
import subprocess
import sys
import time
import urllib.error
import urllib.parse

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import keys  # noqa: E402
import notify  # noqa: E402
import privacy  # noqa: E402

KEY_NAME = "ODOO_API_KEY"
SCOPE_FIELDS = {"team_id": "team_ids", "project_id": "project_ids"}  # ticket field -> stage field that narrows names
DEFAULT_LAUNCH = ["claude", "-p", "/qa-goal {goal}"]
LOCAL_HOSTS = ("127.0.0.1", "localhost", "::1")


class OdooError(Exception):
    """One readable line; never carries the key or the request parameters."""


# ------------------------------------------------------------- config
def odoo_config(cfg, path="qa.config.yaml"):
    """The odoo: block with defaults. Raises notify.ConfigError on a bad shape (exit 2)."""
    o = (cfg or {}).get("odoo")
    if not isinstance(o, dict):
        raise notify.ConfigError(f"config error in {path}: no odoo: block (see templates/qa.config.example.yaml)")
    for field in ("url", "db", "user"):
        if not isinstance(o.get(field), str) or not o[field].strip() or o[field].startswith("<"):
            raise notify.ConfigError(f"config error at odoo.{field}: expected a value")
    url = urllib.parse.urlparse(o["url"])
    if url.scheme not in ("http", "https") or not url.hostname:
        raise notify.ConfigError("config error at odoo.url: expected https://<host>")
    if url.scheme == "http" and url.hostname not in LOCAL_HOSTS:
        raise notify.ConfigError("config error at odoo.url: use https (the API key would travel in clear text)")
    for field in ("api_key", "password"):
        spec = o.get(field)
        if spec is not None and not (isinstance(spec, dict) and list(spec) == ["env"] and isinstance(spec["env"], str)):
            raise notify.ConfigError(f"config error at odoo.{field}: keys never go in the config; use {{env: {KEY_NAME}}}")
    trig = o.get("trigger") or {}
    if not isinstance(trig, dict):
        raise notify.ConfigError("config error at odoo.trigger: expected a mapping (stages, launch)")
    stages = trig.get("stages") or []
    if not isinstance(stages, list) or not all(isinstance(s, str) for s in stages):
        raise notify.ConfigError("config error at odoo.trigger.stages: expected a list of stage names")
    launch = trig.get("launch") or DEFAULT_LAUNCH
    if not isinstance(launch, list) or not all(isinstance(s, str) for s in launch):
        raise notify.ConfigError("config error at odoo.trigger.launch: expected a list of arguments")
    if "auto_move" in o and not isinstance(o["auto_move"], bool):
        raise notify.ConfigError(f"config error at odoo.auto_move: expected true or false, got {o['auto_move']!r}")
    return {"url": o["url"].rstrip("/"), "db": o["db"], "user": o["user"], "model": o.get("model") or "helpdesk.ticket",
            "key_name": (o.get("api_key") or o.get("password") or {}).get("env") or KEY_NAME,
            "stages": stages, "launch": launch, "entry_field": trig.get("entry_field") or "date_last_stage_update",
            "on_pass": o.get("on_pass"), "on_fail": o.get("on_fail"), "auto_move": o.get("auto_move", False)}


def load(path):
    return odoo_config(notify.load_config(path), path)


def ticket_id(text):
    m = re.fullmatch(r"#?(\d+)", str(text).strip())
    if not m:
        raise OdooError(f"not a ticket id: {text!r} (use the number, e.g. 42)")
    return int(m.group(1))


# ------------------------------------------------------------- RPC
class Odoo:
    """Minimal JSON-RPC client. http_fn(method, url, data, headers, timeout) -> (status, text), as in notify.http."""

    def __init__(self, oc, key, http_fn=None, timeout=60):
        self.oc, self.key, self.http_fn, self.timeout = oc, key, http_fn or notify.http, timeout
        self.uid, self._ids = None, itertools.count(1)

    def _mask(self, text):
        return (text or "").replace(self.key, "<SECRET>") if self.key else text

    def _rpc(self, service, method, *args):
        body = json.dumps({"jsonrpc": "2.0", "method": "call", "id": next(self._ids),
                           "params": {"service": service, "method": method, "args": list(args)}}).encode()
        try:
            _status, text = self.http_fn("POST", self.oc["url"] + "/jsonrpc", body, {"Content-Type": "application/json"}, self.timeout)
            data = json.loads(text)
        except urllib.error.HTTPError as exc:
            raise OdooError(f"Odoo answered HTTP {exc.code}") from None
        except (OSError, ValueError) as exc:
            raise OdooError(f"Odoo not reachable or not JSON-RPC: {type(exc).__name__}") from None
        if data.get("error"):
            err = data["error"]
            msg = (err.get("data") or {}).get("message") or err.get("message") or "error"
            raise OdooError("Odoo error: " + self._mask(str(msg)).splitlines()[0][:200])
        return data.get("result")

    def login(self):
        uid = self._rpc("common", "authenticate", self.oc["db"], self.oc["user"], self.key, {})
        if not uid:
            raise OdooError(f"Odoo refused the login for user {self.oc['user']} on database {self.oc['db']} (check {self.oc['key_name']})")
        self.uid = uid
        return uid

    def call(self, model, method, args, kwargs=None):
        if self.uid is None:
            self.login()
        return self._rpc("object", "execute_kw", self.oc["db"], self.uid, self.key, model, method, args, kwargs or {})

    def fields(self, model, names):
        info = self.call(model, "fields_get", [names], {"attributes": ["type", "relation"]}) or {}
        return {n: info[n] for n in names if n in info}


def connect(oc, http_fn=None, asker=None):
    key = keys.get(oc["key_name"], f"Odoo API key for {oc['user']} on {urllib.parse.urlparse(oc['url']).hostname} "
                                   "(Odoo: Preferences > Account Security > New API Key).", asker=asker)
    if not key:
        raise OdooError(f"{oc['key_name']} is not set (save it with: python scripts/keys.py set {oc['key_name']})")
    return Odoo(oc, key, http_fn)


# ------------------------------------------------------------- read
class _Text(html.parser.HTMLParser):
    BREAKS = {"br", "p", "div", "li", "tr", "h1", "h2", "h3", "h4", "blockquote"}

    def __init__(self):
        super().__init__()
        self.out = []

    def handle_starttag(self, tag, attrs):
        if tag in self.BREAKS:
            self.out.append("\n")
        if tag == "li":
            self.out.append("- ")

    def handle_data(self, data):
        self.out.append(data)


def to_text(body):
    if not body or body is False:
        return ""
    p = _Text()
    p.feed(str(body))
    text = re.sub(r"[ \t]+\n", "\n", "".join(p.out))
    return re.sub(r"\n{3,}", "\n\n", text).strip()


def m2o(value):
    return value[1] if isinstance(value, (list, tuple)) and len(value) > 1 else ""


def read_ticket(odoo, tid):
    model = odoo.oc["model"]
    have = odoo.fields(model, ["name", "description", "stage_id", odoo.oc["entry_field"]])
    rows = odoo.call(model, "read", [[tid]], {"fields": list(have)})
    if not rows:
        raise OdooError(f"{model} {tid} not found (or not visible to {odoo.oc['user']})")
    msgs = odoo.call("mail.message", "search_read",
                     [[["model", "=", model], ["res_id", "=", tid], ["message_type", "=", "comment"]]],
                     {"fields": ["date", "author_id", "subtype_id", "body"], "order": "date asc, id asc"})
    return rows[0], msgs or []


def format_ticket(model, tid, rec, msgs):
    out = [f"Ticket {tid} ({model}): {rec.get('name') or ''}", f"Stage: {m2o(rec.get('stage_id')) or '?'}", "",
           "--- Description", to_text(rec.get("description")) or "(empty)", "", f"--- Log notes and messages ({len(msgs)})"]
    for m in msgs:
        out.append(f"[{m.get('date', '')}] {m2o(m.get('author_id')) or '?'} ({m2o(m.get('subtype_id')) or 'comment'}):")
        out.append(to_text(m.get("body")) or "(empty)")
        out.append("")
    return "\n".join(out).rstrip() + "\n"


# ------------------------------------------------------------- post
def _counts(run_dir):
    sys.path.insert(0, HERE)
    import report
    led_path = os.path.join(run_dir, "ledger.json")
    if os.path.exists(led_path):
        led = json.load(open(led_path, encoding="utf-8"))
        c = led["rounds"][-1]["counts"] if led.get("rounds") else {}
        verdict = led.get("status", "") + (f" ({led['stop_reason']})" if led.get("stop_reason") else "")
        return led.get("goal", ""), c, verdict, led.get("bugs", [])
    res = json.load(open(os.path.join(run_dir, "results.json"), encoding="utf-8"))
    c, _rows = report.count(res.get("results", []))
    return res.get("name", ""), c, "single run", []


def note_text(run_dir, cfg):
    goal, c, verdict, bugs = _counts(run_dir)
    g = lambda k: c.get(k, 0)  # noqa: E731
    lines = [f"ShipShape QA result: {goal}",
             f"Result: {g('PASS')} pass / {g('FAIL')} fail / {g('FLAKY')} flaky / {g('BLOCKED')} blocked ({g('TOTAL')} total)",
             f"Verdict: {verdict or '?'}"]
    if g("NOT CHECKED"):
        lines.append(f"Not checked: {g('NOT CHECKED')}")
    lines.append("Bugs: none" if not bugs else f"Bugs ({len(bugs)}):")
    for b in bugs:
        lines.append(f"- {b.get('id')} [{b.get('status')}] {b.get('case', '')}: {b.get('title') or b.get('note') or ''}"
                     + (f" {b['link']}" if b.get("link") else ""))
    video, run = notify.find_video(run_dir), os.path.basename(os.path.abspath(run_dir))
    if video and cfg.get("video_link_base"):
        rel = os.path.relpath(video, os.path.dirname(os.path.abspath(run_dir))).replace("\\", "/")
        lines.append("Video: " + cfg["video_link_base"].rstrip("/") + "/" + rel)
    elif video:
        lines.append("Video: not uploaded (set video_link_base in qa.config.yaml); local file in run " + run)
    else:
        lines.append("Video: none recorded")
    if cfg.get("report_link_base"):
        lines.append("Report: " + cfg["report_link_base"].rstrip("/") + f"/{run}/report.html")
    lines.append(f"Run: {run}")
    text = "\n".join(lines)
    masked = privacy.mask_text(text)
    return masked, sum(1 for _ in privacy.find(text, privacy.load_denylist()))


def posted_path(run_dir):
    return os.path.join(run_dir, "odoo-posted.json")


def post(oc, cfg, tid, run_dir, send=False, http_fn=None, out=print, asker=None):
    text, hits = note_text(run_dir, cfg)
    target = f"{oc['model']} {tid}"
    try:
        done = json.load(open(posted_path(run_dir), encoding="utf-8"))
    except (OSError, ValueError):
        done = []
    if f"{oc['model']}:{tid}" in done:
        out(f"already posted to {target} for this run (see {os.path.basename(posted_path(run_dir))}); nothing sent")
        return 0
    out(f"{'' if send else '[dry-run] '}log note on {target} (privacy filter: {hits} span(s) masked):")
    out("    " + text.replace("\n", "\n    "))
    if not send:
        out("dry-run: nothing was posted (add --send after the owner's OK)")
        return 0
    odoo = connect(oc, http_fn, asker)
    body = "".join(f"<p>{html.escape(line)}</p>" for line in text.splitlines())
    msg_id = odoo.call(oc["model"], "message_post", [[tid]], {"body": body, "message_type": "comment", "subtype_xmlid": "mail.mt_note"})
    done.append(f"{oc['model']}:{tid}")
    tmp = posted_path(run_dir) + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(done, fh)
    os.replace(tmp, posted_path(run_dir))
    out(f"posted: log note {msg_id} on {target}")
    return 0


# ------------------------------------------------------------- move
def find_stage(odoo, tid, name):
    """The stage id for a name, narrowed to the ticket's team/project. Refuses 0 or several matches."""
    model = odoo.oc["model"]
    info = odoo.fields(model, ["stage_id", *SCOPE_FIELDS])
    rel = (info.get("stage_id") or {}).get("relation")
    if not rel:
        raise OdooError(f"{model} has no stage_id field")
    have = [f for f in SCOPE_FIELDS if f in info]
    rec = (odoo.call(model, "read", [[tid]], {"fields": ["stage_id", *have]}) or [None])[0]
    if not rec:
        raise OdooError(f"{model} {tid} not found (or not visible to {odoo.oc['user']})")
    domain = [["name", "=", name]]
    stage_fields = odoo.fields(rel, list(SCOPE_FIELDS.values()))
    for tf, sf in SCOPE_FIELDS.items():
        if tf in have and sf in stage_fields and isinstance(rec.get(tf), list):
            domain.append([sf, "in", [rec[tf][0]]])
    found = odoo.call(rel, "search_read", [domain], {"fields": ["name"], "limit": 5})
    if len(found) != 1:
        raise OdooError(f"stage {name!r}: {len(found)} match(es) in {rel} for this ticket; need exactly one")
    return found[0]["id"], rec


def move(oc, tid, stage, send=False, http_fn=None, out=print, asker=None):
    target = f"{oc['model']} {tid}"
    if not send:
        out(f"[dry-run] would move {target} to stage {stage!r} (add --send after the owner's OK"
            + (", or auto_move: true for the on_pass/on_fail stages" if stage in (oc["on_pass"], oc["on_fail"]) else "") + ")")
        return 0
    odoo = connect(oc, http_fn, asker)
    sid, rec = find_stage(odoo, tid, stage)
    if isinstance(rec.get("stage_id"), list) and rec["stage_id"][0] == sid:
        out(f"{target} is already in stage {stage!r}; nothing written")
        return 0
    odoo.call(oc["model"], "write", [[tid], {"stage_id": sid}])
    back = odoo.call(oc["model"], "read", [[tid]], {"fields": ["stage_id"]})[0]
    if not (isinstance(back.get("stage_id"), list) and back["stage_id"][0] == sid):
        raise OdooError(f"wrote stage {stage!r} but read back {m2o(back.get('stage_id')) or '?'}")
    out(f"moved: {target} from {m2o(rec.get('stage_id')) or '?'} to {stage!r} (read back ok)")
    return 0


# ------------------------------------------------------------- watch
def load_state(path):
    try:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return None


def save_state(path, state):
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(state, fh, indent=1, sort_keys=True)
    os.replace(tmp, path)  # atomic: a crash never loses or half-writes an entry


def entry_key(rec, entry_field):
    sid = rec["stage_id"][0] if isinstance(rec.get("stage_id"), list) else rec.get("stage_id")
    return f"{sid}@{rec.get(entry_field) or ''}"


def poll(odoo, state, include_existing=False):
    """Tickets newly in a watched stage: [(rec, key)]. Updates `state` in memory (caller decides to save)."""
    oc = odoo.oc
    if not oc["stages"]:
        raise OdooError("odoo.trigger.stages is empty: nothing to watch")
    have = odoo.fields(oc["model"], ["name", "stage_id", oc["entry_field"]])
    rows = odoo.call(oc["model"], "search_read", [[["stage_id.name", "in", oc["stages"]]]],
                     {"fields": list(have), "order": "id asc", "limit": 200}) or []
    first = not state.get("seen") and not state.get("started")
    state["started"] = state.get("started") or dt.datetime.now().isoformat(timespec="seconds")
    seen = state.setdefault("seen", {})
    here = {str(rec["id"]) for rec in rows}
    for gone in [t for t in seen if t not in here]:  # left the watched stages: a later re-entry is a new entry
        del seen[gone]
    new = []
    for rec in rows:
        k = entry_key(rec, oc["entry_field"])
        if seen.get(str(rec["id"])) == k:
            continue
        if first and not include_existing:
            seen[str(rec["id"])] = k  # already there when watching began: not "newly arrived"
            continue
        new.append((rec, k))  # the caller marks it seen right before launching it
    return new, first


def ticket_goal(oc, rec, path):
    return f"Odoo ticket {rec['id']} ({m2o(rec.get('stage_id'))}): {rec.get('name') or ''}. Plan from the ticket analysis in {path}"


def watch(oc, root="qa-runs", launch=False, once=False, interval=300, minutes=60, include_existing=False, run_timeout=7200,
          http_fn=None, runner=None, clock=time.time, sleep=time.sleep, out=print, asker=None, state_file=None):
    import stack_lock
    state_file = state_file or os.path.join(root, "odoo-watch.json")
    deadline = clock() + minutes * 60
    lock = stack_lock.lock_path("odoo-watch")
    if launch and not stack_lock.acquire(lock, "odoo-watch", wait=5, poll=1):
        out("another watcher is running: not starting a second one")
        return 1
    launched = 0
    try:
        odoo = connect(oc, http_fn, asker)
        while True:
            state = load_state(state_file) or {}
            new, first = poll(odoo, state, include_existing)
            if first and not include_existing:
                out(f"first poll: {len(state['seen'])} ticket(s) already in {', '.join(oc['stages'])}; "
                    "not tested (--include-existing to test them)" + ("" if launch else "; dry-run: nothing saved"))
            for rec, k in new:
                stamp = dt.datetime.now().strftime("%Y%m%d-%H%M%S")
                path = os.path.join(root, "odoo-tickets", f"{rec['id']}-{stamp}.md")
                goal = ticket_goal(oc, rec, path.replace("\\", "/"))
                argv = [a.format(goal=goal, ticket=rec["id"], file=path) for a in oc["launch"]]
                if not launch:
                    out(f"[dry-run] would test ticket {rec['id']} ({m2o(rec.get('stage_id'))}): {rec.get('name') or ''}")
                    out(f"    goal: {goal}")
                    out(f"    run: {' '.join(argv)}")
                    if oc["auto_move"]:
                        out(f"    then move to {oc['on_pass']!r} on pass / {oc['on_fail']!r} on fail (auto_move)")
                    continue
                rec_full, msgs = read_ticket(odoo, rec["id"])
                os.makedirs(os.path.dirname(path), exist_ok=True)
                with open(path, "w", encoding="utf-8") as fh:
                    fh.write(format_ticket(oc["model"], rec["id"], rec_full, msgs))
                state["seen"][str(rec["id"])] = k
                save_state(state_file, state)  # recorded BEFORE launching: a crash never launches twice
                out(f"launch: ticket {rec['id']} -> {' '.join(argv[:2])} ... (analysis in {path})")
                left = max(60, int(deadline - clock()))
                try:
                    code = (runner or _run)(argv, min(run_timeout, left))
                except Exception as exc:  # noqa: BLE001 - one failed launch never stops the watcher
                    code = f"did not run ({type(exc).__name__})"
                out(f"    finished: {code}")
                launched += 1
            if launch:
                save_state(state_file, state)
            if once or clock() + interval >= deadline:
                break
            sleep(interval)
    finally:
        if launch:
            stack_lock.release(lock)
    out(f"watch done: {launched} run(s) launched" + ("" if launch else " (dry-run: state not saved)"))
    return 0


def _run(argv, timeout):
    import shutil
    try:
        return subprocess.run([shutil.which(argv[0]) or argv[0], *argv[1:]], timeout=timeout).returncode  # claude.cmd on Windows
    except subprocess.TimeoutExpired:
        return f"timed out after {timeout}s"


# ------------------------------------------------------------- CLI
def main(argv=None, http_fn=None, runner=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--config", default="qa.config.yaml")
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("read", help="description, stage and log notes (read-only)")
    r.add_argument("ticket")
    p = sub.add_parser("post", help="one log note with the run result (dry-run unless --send)")
    p.add_argument("ticket")
    p.add_argument("--run", required=True)
    p.add_argument("--send", action="store_true")
    m = sub.add_parser("move", help="set the ticket's stage (dry-run unless --send)")
    m.add_argument("ticket")
    m.add_argument("--stage", required=True)
    m.add_argument("--send", action="store_true")
    w = sub.add_parser("watch", help="start a qa run for tickets newly in the watched stages")
    w.add_argument("--root", default="qa-runs")
    w.add_argument("--launch", action="store_true", help="really start the runs (default: print what would run)")
    w.add_argument("--once", action="store_true")
    w.add_argument("--interval", type=int, default=300, help="seconds between polls")
    w.add_argument("--minutes", type=float, default=60, help="time limit for the whole watch")
    w.add_argument("--run-timeout", type=int, default=7200, help="time limit per launched run (seconds)")
    w.add_argument("--include-existing", action="store_true", help="also test tickets already in the stage at the first poll")
    for sp in (r, p, m, w):
        sp.add_argument("--config", default=argparse.SUPPRESS)
    a = ap.parse_args(argv)
    sys.stdout.reconfigure(encoding="utf-8")
    try:
        oc = load(a.config)
        if a.cmd == "read":
            tid = ticket_id(a.ticket)
            odoo = connect(oc, http_fn)
            rec, msgs = read_ticket(odoo, tid)
            sys.stdout.write(format_ticket(oc["model"], tid, rec, msgs))
            return 0
        if a.cmd == "post":
            if not os.path.isdir(a.run):
                print(f"ERROR: run folder not found: {a.run}")
                return 2
            return post(oc, notify.load_config(a.config), ticket_id(a.ticket), a.run, a.send, http_fn)
        if a.cmd == "move":
            return move(oc, ticket_id(a.ticket), a.stage, a.send, http_fn)
        return watch(oc, a.root, a.launch, a.once, a.interval, a.minutes, a.include_existing, a.run_timeout, http_fn, runner)
    except notify.ConfigError as exc:
        print(f"ERROR: {exc}")
        return 2
    except OdooError as exc:
        print(f"ERROR: {exc}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
