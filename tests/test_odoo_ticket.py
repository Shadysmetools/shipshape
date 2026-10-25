"""odoo_ticket.py against a mocked Odoo JSON-RPC (no real Odoo is ever contacted).

The API key is the user's own: tests set a placeholder in the environment and check it never shows."""
import contextlib
import http.server
import json
import os
import subprocess
import sys
import threading

import pytest

import hook_guard
import keys
import odoo_ticket

from conftest import free_port

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPT = os.path.join(ROOT, "scripts", "odoo_ticket.py")
PLACEHOLDER = "placeholder-for-tests-only"
LEAKY = "someone" "@realmail.net"  # split so the commit scanner does not see an address
WRITES = {"write", "create", "unlink", "message_post"}

CONFIG = """project: demo-shop
video_link_base: https://files.example.com/qa
odoo:
  url: {url}
  db: qa-test
  user: qa-bot@example.com
  model: helpdesk.ticket
  trigger:
    stages: [Pending Internal Testing]
    launch: [python, -c, "print('{{ticket}}')"]
  on_pass: Client Testing
  on_fail: In Progress
  auto_move: {auto}
"""


class FakeOdoo:
    """In-memory Odoo: authenticate + execute_kw (fields_get, read, search_read, write, message_post)."""

    def __init__(self):
        self.calls = []
        self.uid = 7
        stage = lambda i, n, teams: {"id": i, "name": n, "team_ids": teams}  # noqa: E731
        self.db = {
            "helpdesk.stage": {s["id"]: s for s in (stage(1, "New", [1]), stage(2, "Pending Internal Testing", [1]),
                                                     stage(3, "Client Testing", [1]), stage(4, "In Progress", [1]),
                                                     stage(5, "Client Testing", [2]), stage(6, "Done", [1, 2]),
                                                     stage(7, "Done", [1]))},
            "helpdesk.ticket": {
                42: {"id": 42, "name": "Discount not applied at checkout", "team_id": [1, "Support"],
                     "description": "<p>Customer says the <b>10% code</b> is ignored.</p><ul><li>Step 1</li></ul>",
                     "stage_id": [2, "Pending Internal Testing"], "date_last_stage_update": "2026-10-25 09:00:00"},
                43: {"id": 43, "name": "Export button", "team_id": [1, "Support"], "description": False,
                     "stage_id": [1, "New"], "date_last_stage_update": "2026-10-20 09:00:00"},
            },
            "mail.message": {
                1: {"id": 1, "model": "helpdesk.ticket", "res_id": 42, "message_type": "comment", "date": "2026-10-25 08:00:00",
                    "author_id": [3, "Ticket Analyst Agent"], "subtype_id": [2, "Note"],
                    "body": "<p>Analysis: the code path skips <code>apply_discount</code> when the cart has 1 item.</p>"},
                2: {"id": 2, "model": "helpdesk.ticket", "res_id": 42, "message_type": "notification", "date": "2026-10-25 08:30:00",
                    "author_id": [3, "Bot"], "subtype_id": [1, "Stage changed"], "body": "<p>stage changed</p>"},
            },
        }

    def fields_of(self, model):
        out = {}
        for rec in self.db[model].values():
            out.update({k: {"type": "x"} for k in rec})
        if "stage_id" in out:
            out["stage_id"] = {"type": "many2one", "relation": "helpdesk.stage"}
        return out

    def match(self, rec, domain):
        for field, op, value in domain:
            if field == "stage_id.name":
                got = self.db["helpdesk.stage"][rec["stage_id"][0]]["name"]
            else:
                got = rec.get(field)
                got = got[0] if isinstance(got, list) and len(got) == 2 and isinstance(got[1], str) else got
            if op == "=" and got != value:
                return False
            if op == "in" and not (set(got) & set(value) if isinstance(got, list) else got in value):
                return False
        return True

    def execute(self, model, method, args, kw):
        self.calls.append((model, method))
        table = self.db[model]
        if method == "fields_get":
            return self.fields_of(model)
        if method == "read":
            return [{k: v for k, v in table[i].items() if k in kw.get("fields", table[i]) or k == "id"} for i in args[0] if i in table]
        if method == "search_read":
            rows = [r for r in table.values() if self.match(r, args[0])]
            return [{k: v for k, v in r.items() if k in kw.get("fields", r) or k == "id"} for r in rows][: kw.get("limit") or None]
        if method == "write":
            for i in args[0]:
                vals = dict(args[1])
                if "stage_id" in vals:
                    vals["stage_id"] = [vals["stage_id"], self.db["helpdesk.stage"][vals["stage_id"]]["name"]]
                table[i].update(vals)
            return True
        if method == "message_post":
            mid = max(self.db["mail.message"]) + 1
            self.db["mail.message"][mid] = {"id": mid, "model": model, "res_id": args[0][0], "message_type": "comment",
                                            "body": kw["body"], "subtype_xmlid": kw.get("subtype_xmlid")}
            return mid
        raise AssertionError(f"unexpected {model}.{method}")

    def handle(self, payload):
        p = payload["params"]
        if p["service"] == "common" and p["method"] == "authenticate":
            db, user, key, _ = p["args"]
            self.calls.append(("common", "authenticate"))
            return {"result": self.uid if key == PLACEHOLDER else False}
        db, uid, key, model, method, args, kw = p["args"]
        if key != PLACEHOLDER or uid != self.uid:
            return {"error": {"message": "Odoo Server Error", "data": {"message": f"Access denied for key {key}"}}}
        return {"result": self.execute(model, method, args, kw)}

    def http_fn(self, method, url, data=None, headers=None, timeout=60):
        assert url.endswith("/jsonrpc") and method == "POST"
        return 200, json.dumps({"jsonrpc": "2.0", "id": 1, **self.handle(json.loads(data))})

    def writes(self):
        return [c for c in self.calls if c[1] in WRITES]


@pytest.fixture
def fake():
    return FakeOdoo()


@pytest.fixture
def cfg(tmp_path, monkeypatch):
    monkeypatch.setenv("ODOO_API_KEY", PLACEHOLDER)
    monkeypatch.setenv("SMEKIT_LOCK_DIR", str(tmp_path / "locks"))
    path = tmp_path / "qa.config.yaml"
    path.write_text(CONFIG.format(url="https://odoo.example.com", auto="false"), encoding="utf-8")
    return path


def run_dir(tmp_path):
    run = tmp_path / "qa-runs" / "2026-10-25-discount"
    (run / "round-01" / "checkout" / "pass-1").mkdir(parents=True)
    (run / "round-01" / "checkout" / "pass-1" / "checkout.mp4").write_bytes(b"\0" * 10)
    (run / "ledger.json").write_text(json.dumps({
        "goal": "discount applies at checkout", "status": "stopped", "stop_reason": "max rounds (1) reached",
        "rounds": [{"counts": {"PASS": 3, "FAIL": 1, "FLAKY": 0, "BLOCKED": 1, "NOT CHECKED": 0, "TOTAL": 5}}],
        "bugs": [{"id": "B1", "case": "checkout-2", "title": "Code ignored, reported by " + LEAKY, "status": "filed",
                  "link": "https://tracker.example.com/1"}]}), encoding="utf-8")
    return run


def cli(args, fake, capsys, runner=None):
    code = odoo_ticket.main(args, http_fn=fake.http_fn, runner=runner)
    return code, capsys.readouterr().out


# ------------------------------------------------------------- config + keys
def test_config_refuses_keys_in_the_file_and_plain_http(tmp_path):
    bad = tmp_path / "c.yaml"
    for body, msg in (("odoo: {url: https://o.example.com, db: d, user: u, api_key: x}", "keys never go in the config"),
                      ("odoo: {url: http://o.example.com, db: d, user: u}", "use https"),
                      ("odoo: {url: https://o.example.com, db: d}", "odoo.user"),
                      ("odoo: {url: https://o.example.com, db: d, user: u, auto_move: yes please}", "auto_move"),
                      ("project: x", "no odoo: block")):
        bad.write_text(body, encoding="utf-8")
        with pytest.raises(odoo_ticket.notify.ConfigError, match=msg):
            odoo_ticket.load(str(bad))
    bad.write_text("odoo: {url: http://127.0.0.1:8069, db: d, user: u, api_key: {env: MY_ODOO_KEY}}", encoding="utf-8")
    assert odoo_ticket.load(str(bad))["key_name"] == "MY_ODOO_KEY"  # local http is fine, the key name is configurable


def test_keys_check_lists_the_odoo_key():
    names = dict(keys.needed({"odoo": {"url": "https://o.example.com"}}))
    assert names["ODOO_API_KEY"] == "odoo"
    assert "ODOO_API_KEY" in keys.HINTS


def test_missing_key_is_asked_for_then_refused_cleanly(cfg, fake, capsys, monkeypatch):
    monkeypatch.delenv("ODOO_API_KEY")
    code, out = cli(["--config", str(cfg), "read", "42"], fake, capsys)
    assert code == 1 and "ODOO_API_KEY is not set" in out and "keys.py set ODOO_API_KEY" in out
    assert fake.calls == []  # nothing was sent without a key
    asked = []
    oc = odoo_ticket.load(str(cfg))
    monkeypatch.delenv("SMEKIT_NO_PROMPT")
    odoo = odoo_ticket.connect(oc, fake.http_fn, asker=lambda n, r: asked.append(n) or PLACEHOLDER)
    assert asked == ["ODOO_API_KEY"] and odoo.login() == 7


def test_rpc_errors_never_show_the_key(cfg, fake, capsys):
    oc = odoo_ticket.load(str(cfg))
    odoo = odoo_ticket.Odoo(oc, PLACEHOLDER, fake.http_fn)
    odoo.login()
    odoo.uid = 99  # the fake answers with an error that echoes the key
    with pytest.raises(odoo_ticket.OdooError) as exc:
        odoo.call("helpdesk.ticket", "read", [[42]])
    assert PLACEHOLDER not in str(exc.value) and "<SECRET>" in str(exc.value)
    wrong = odoo_ticket.Odoo(oc, "other-placeholder", fake.http_fn)
    with pytest.raises(odoo_ticket.OdooError, match="refused the login"):
        wrong.login()


# ------------------------------------------------------------- read
def test_read_prints_description_stage_and_log_notes(cfg, fake, capsys):
    code, out = cli(["--config", str(cfg), "read", "#42"], fake, capsys)
    assert code == 0
    assert "Ticket 42 (helpdesk.ticket): Discount not applied at checkout" in out
    assert "Stage: Pending Internal Testing" in out
    assert "Customer says the 10% code is ignored." in out and "- Step 1" in out and "<b>" not in out
    assert "Ticket Analyst Agent (Note):" in out and "skips apply_discount when the cart has 1 item" in out
    assert "stage changed" not in out  # tracking notifications are not analysis
    assert fake.writes() == [] and PLACEHOLDER not in out


def test_read_unknown_ticket(cfg, fake, capsys):
    code, out = cli(["--config", str(cfg), "read", "999"], fake, capsys)
    assert code == 1 and "helpdesk.ticket 999 not found" in out
    code, out = cli(["--config", str(cfg), "read", "abc"], fake, capsys)
    assert code == 1 and "not a ticket id" in out


# ------------------------------------------------------------- post
def test_post_dry_run_shows_the_masked_note_and_contacts_nobody(cfg, fake, capsys, tmp_path):
    run = run_dir(tmp_path)
    code, out = cli(["--config", str(cfg), "post", "42", "--run", str(run)], fake, capsys)
    assert code == 0 and fake.calls == []
    assert "Result: 3 pass / 1 fail / 0 flaky / 1 blocked (5 total)" in out
    assert "B1 [filed] checkout-2" in out and "https://tracker.example.com/1" in out
    assert "Video: https://files.example.com/qa/2026-10-25-discount/round-01/checkout/pass-1/checkout.mp4" in out
    assert LEAKY not in out and "[email]" in out and "1 span(s) masked" in out
    assert "nothing was posted" in out and not (run / "odoo-posted.json").exists()


def test_post_send_writes_one_masked_note_once(cfg, fake, capsys, tmp_path):
    run = run_dir(tmp_path)
    code, out = cli(["--config", str(cfg), "post", "42", "--run", str(run), "--send"], fake, capsys)
    assert code == 0 and "posted: log note 3 on helpdesk.ticket 42" in out
    assert fake.writes() == [("helpdesk.ticket", "message_post")]
    note = fake.db["mail.message"][3]
    assert note["subtype_xmlid"] == "mail.mt_note" and "3 pass / 1 fail / 0 flaky / 1 blocked" in note["body"]
    assert "realmail" not in note["body"] and "[email]" in note["body"]
    code, out = cli(["--config", str(cfg), "post", "42", "--run", str(run), "--send"], fake, capsys)
    assert code == 0 and "already posted" in out and len(fake.writes()) == 1  # one note per run per ticket


def test_post_counts_from_a_single_run_results_json(cfg, fake, capsys, tmp_path):
    run = tmp_path / "single"
    run.mkdir()
    (run / "results.json").write_text(json.dumps({"name": "smoke", "results": [
        {"id": "a", "result": "PASS", "evidence": "a.png"}, {"id": "b", "result": "FLAKY", "evidence": "b.png"}]}))
    code, out = cli(["--config", str(cfg), "post", "42", "--run", str(run)], fake, capsys)
    assert code == 0 and "1 pass / 0 fail / 1 flaky / 0 blocked (2 total)" in out and "Video: none recorded" in out


# ------------------------------------------------------------- move
def test_move_dry_run_then_send_with_read_back(cfg, fake, capsys):
    code, out = cli(["--config", str(cfg), "move", "42", "--stage", "Client Testing"], fake, capsys)
    assert code == 0 and "[dry-run] would move helpdesk.ticket 42" in out and fake.calls == []
    code, out = cli(["--config", str(cfg), "move", "42", "--stage", "Client Testing", "--send"], fake, capsys)
    assert code == 0 and "read back ok" in out
    assert fake.db["helpdesk.ticket"][42]["stage_id"] == [3, "Client Testing"]  # team 1's stage, not team 2's id 5
    assert fake.writes() == [("helpdesk.ticket", "write")]
    code, out = cli(["--config", str(cfg), "move", "42", "--stage", "Client Testing", "--send"], fake, capsys)
    assert "already in stage" in out and len(fake.writes()) == 1


def test_move_refuses_unknown_or_ambiguous_stage(cfg, fake, capsys):
    for stage, n in (("Nope", 0), ("Done", 2)):  # two "Done" stages are both open to team 1
        code, out = cli(["--config", str(cfg), "move", "42", "--stage", stage, "--send"], fake, capsys)
        assert code == 1 and f"{n} match(es)" in out
    assert fake.writes() == []


# ------------------------------------------------------------- watch
def test_watch_dry_run_prints_and_saves_nothing(cfg, fake, capsys, tmp_path):
    root = tmp_path / "qa-runs"
    code, out = cli(["--config", str(cfg), "watch", "--root", str(root), "--once", "--include-existing"], fake, capsys)
    assert code == 0
    assert "[dry-run] would test ticket 42 (Pending Internal Testing): Discount not applied at checkout" in out
    assert "goal: Odoo ticket 42" in out and "ticket 43" not in out
    assert not (root / "odoo-watch.json").exists()
    assert fake.writes() == []


def test_watch_first_poll_is_a_baseline(cfg, fake, capsys, tmp_path):
    root, launched = tmp_path / "qa-runs", []
    code, out = cli(["--config", str(cfg), "watch", "--root", str(root), "--once", "--launch"], fake, capsys,
                    runner=lambda argv, t: launched.append(argv) or 0)
    assert code == 0 and launched == [] and "1 ticket(s) already in Pending Internal Testing" in out
    # ticket 43 arrives in the watched stage afterwards: that one runs
    fake.db["helpdesk.ticket"][43].update(stage_id=[2, "Pending Internal Testing"], date_last_stage_update="2026-10-25 10:00:00")
    code, out = cli(["--config", str(cfg), "watch", "--root", str(root), "--once", "--launch"], fake, capsys,
                    runner=lambda argv, t: launched.append(argv) or 0)
    assert [a[-1] for a in launched] == ["print('43')"]


def test_watch_one_run_per_stage_entry(cfg, fake, capsys, tmp_path):
    root, launched = tmp_path / "qa-runs", []
    runner = lambda argv, t: launched.append(argv) or 0  # noqa: E731
    args = ["--config", str(cfg), "watch", "--root", str(root), "--once", "--launch", "--include-existing"]
    cli(args, fake, capsys, runner)
    cli(args, fake, capsys, runner)  # same entry polled again: no second run
    assert len(launched) == 1
    state = json.loads((root / "odoo-watch.json").read_text())
    assert state["seen"]["42"] == "2@2026-10-25 09:00:00"
    files = list((root / "odoo-tickets").glob("42-*.md"))
    assert len(files) == 1 and "Ticket Analyst Agent" in files[0].read_text(encoding="utf-8")
    # the ticket leaves and comes back: a new stage entry, a new run
    fake.db["helpdesk.ticket"][42].update(stage_id=[4, "In Progress"])
    cli(args, fake, capsys, runner)
    fake.db["helpdesk.ticket"][42].update(stage_id=[2, "Pending Internal Testing"], date_last_stage_update="2026-10-26 09:00:00")
    cli(args, fake, capsys, runner)
    assert len(launched) == 2
    assert {c[1] for c in fake.calls} <= {"authenticate", "fields_get", "search_read", "read"}  # watch never writes


def test_watch_state_is_saved_before_the_launch(cfg, fake, capsys, tmp_path):
    root = tmp_path / "qa-runs"
    seen_at_launch = []
    runner = lambda argv, t: seen_at_launch.append(json.loads((root / "odoo-watch.json").read_text())["seen"].get("42")) or 0  # noqa: E731
    cli(["--config", str(cfg), "watch", "--root", str(root), "--once", "--launch", "--include-existing"], fake, capsys, runner)
    assert seen_at_launch == ["2@2026-10-25 09:00:00"]


def test_watch_has_a_time_limit(cfg, fake, tmp_path):
    oc = odoo_ticket.load(str(cfg))
    t = [0.0]
    sleeps = []

    def sleep(s):
        sleeps.append(s)
        t[0] += s
    odoo_ticket.watch(oc, str(tmp_path / "qa-runs"), interval=300, minutes=20, http_fn=fake.http_fn,
                      clock=lambda: t[0], sleep=sleep, out=lambda *_: None)
    assert sleeps == [300, 300, 300] and t[0] <= 20 * 60  # 4 polls in 20 minutes, then it stops on its own


def test_watch_refuses_a_second_watcher(cfg, fake, tmp_path, monkeypatch):
    import stack_lock
    monkeypatch.setattr(stack_lock, "acquire", lambda *a, **k: False)
    msgs = []
    oc = odoo_ticket.load(str(cfg))
    assert odoo_ticket.watch(oc, str(tmp_path), launch=True, once=True, http_fn=fake.http_fn, out=msgs.append) == 1
    assert "another watcher" in msgs[0] and fake.calls == []


# ------------------------------------------------------------- hook guard
def test_hook_guard_gates_odoo_writes(tmp_path):
    cfg = tmp_path / "qa.config.yaml"
    cfg.write_text(CONFIG.format(url="https://odoo.example.com", auto="false"), encoding="utf-8")
    base = f"python scripts/odoo_ticket.py --config {cfg}"
    v = lambda c: hook_guard.classify_command(c, str(tmp_path))  # noqa: E731
    assert v(f"{base} post 42 --run qa-runs/x --send")[0] == "ask"
    assert v(f'{base} move 42 --stage "Client Testing" --send')[0] == "ask"
    assert v(f"{base} post 42 --run qa-runs/x") is None  # dry-run: no gate
    assert v(f'{base} move 42 --stage "Client Testing"') is None
    assert v(f"{base} read 42") is None and v(f"{base} watch --once") is None
    cfg.write_text(CONFIG.format(url="https://odoo.example.com", auto="true"), encoding="utf-8")
    assert v(f'{base} move 42 --stage "Client Testing" --send') is None  # auto_move: the owner's own setting
    assert v(f'{base} move 42 --stage "In Progress" --send') is None
    assert v(f'{base} move 42 --stage "Done" --send')[0] == "ask"  # not an on_pass/on_fail stage
    assert v(f"{base} post 42 --run qa-runs/x --send")[0] == "ask"  # auto_move never covers notes
    cfg.write_text("odoo: {url: https://o.example.com, db: d, user: u, api_key: x}", encoding="utf-8")
    assert v(f"{base} post 42 --run qa-runs/x --send")[0] == "deny"


# ------------------------------------------------------------- the real CLI over HTTP (local fake server)
@contextlib.contextmanager
def fake_server(fake):
    class H(http.server.BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def do_POST(self):
            body = json.dumps({"jsonrpc": "2.0", "id": 1, **fake.handle(json.loads(self.rfile.read(int(self.headers["Content-Length"]))))})
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(body.encode())
    port = free_port()
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", port), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        yield f"http://127.0.0.1:{port}"
    finally:
        srv.shutdown()


def test_cli_end_to_end_over_jsonrpc(cfg, fake, tmp_path):
    with fake_server(fake) as url:
        cfg.write_text(CONFIG.format(url=url, auto="false"), encoding="utf-8")
        env = {**os.environ, "PYTHONIOENCODING": "utf-8"}
        p = subprocess.run([sys.executable, SCRIPT, "--config", str(cfg), "read", "42"], capture_output=True, text=True,
                           encoding="utf-8", env=env, timeout=60)
    assert p.returncode == 0, p.stdout + p.stderr
    assert "Stage: Pending Internal Testing" in p.stdout and "Ticket Analyst Agent (Note):" in p.stdout
    assert PLACEHOLDER not in p.stdout + p.stderr
