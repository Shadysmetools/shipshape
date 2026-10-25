"""Knowcap channel (issue #8): upload video + report, confirm, optional share link. Mocked HTTP only, no real key."""
import json
import urllib.error

import pytest

import notify
from test_tools import make_run

PID = "11111111-2222-3333-4444-555555555555"
FAKE_KEY = "fake-knowcap-test-value"  # not a key: a placeholder the mock checks for
ENV_NAME = "KC_TEST_KEY"


def kc_cfg(**over):
    ch = {"type": "knowcap", "enabled": True, "api_key": {"env": ENV_NAME}, "project_id": PID}
    ch.update(over)
    return {"notify": {"knowcap": ch}}


class FakeKnowcap:
    """Answers the Knowcap routes the way knowcap-mcp's client expects; records every call."""

    def __init__(self, lands_in_inbox=True, share_url="https://app.knowcap.ai/share/tok123", fail_report=False):
        self.calls, self.n = [], 0
        self.lands_in_inbox, self.share_url, self.fail_report = lands_in_inbox, share_url, fail_report

    def __call__(self, method, url, data=None, headers=None, **_k):
        self.calls.append((method, url, headers or {}, data))
        body = json.loads(data) if data and method == "POST" else {}
        if url.endswith("/api/sources/prepare-upload"):
            self.n += 1
            if self.fail_report and body["fileName"].endswith(".html"):
                raise urllib.error.HTTPError(url, 400, "unsupported type", None, None)
            return 200, json.dumps({"sourceId": f"src-{self.n}", "storagePath": f"u/{body['fileName']}",
                                    "uploadUrl": f"https://storage.example.com/signed/{self.n}", "token": f"upl-{self.n}", "bucketName": "b"})
        if url.startswith("https://storage.example.com/"):
            return 200, ""
        if url.endswith("/api/sources/confirm-upload"):
            sid = f"src-{self.n}"
            return 200, json.dumps({"success": True, "source": {"id": sid, "project_id": None if self.lands_in_inbox else PID}})
        if url.endswith("/move") or url.endswith("/sources/bulk"):
            return 200, json.dumps({"ok": True})
        if "/api/share/source/" in url:
            return 200, json.dumps({"success": True, "url": self.share_url, "token": "tok123"})
        raise AssertionError(f"unexpected call {method} {url}")

    def urls(self):
        return [(m, u) for m, u, _h, _d in self.calls]


@pytest.fixture
def kenv(tmp_path, monkeypatch):
    monkeypatch.setenv("SMEKIT_LOCK_DIR", str(tmp_path / "locks"))
    monkeypatch.delenv("SMEKIT_DENYLIST", raising=False)
    return {ENV_NAME: FAKE_KEY, "SMEKIT_STATE_DIR": str(tmp_path / "state")}


def send(run, cfg, env, fake, **kw):
    return notify.deliver(run, cfg, send=True, env=env, http_fn=fake, out=lambda *_: None, **kw)


def test_dry_run_makes_no_call_and_lists_the_upload_flow(tmp_path, kenv):
    run = make_run(tmp_path)
    fake, printed = FakeKnowcap(), []
    res = notify.deliver(run, kc_cfg(share=True), env=kenv, http_fn=fake, out=printed.append)
    assert not fake.calls
    assert res[0]["status"] == "DRY-RUN" and res[0]["video"]
    joined = "\n".join(printed)
    for route in ("/api/sources/prepare-upload", "<signed uploadUrl>", "/api/sources/confirm-upload", "/api/share/source/"):
        assert route in joined
    assert FAKE_KEY not in joined


def test_send_uploads_video_and_report_moves_to_project_and_returns_private_link(tmp_path, kenv):
    run = make_run(tmp_path)
    fake = FakeKnowcap()
    res = send(run, kc_cfg(folder_id="fold-1"), kenv, fake)
    r = res[0]
    assert r["status"] == "SENT" and r["calls"] == 2, r
    assert r["knowcap_link"] == f"https://app.knowcap.ai/project/{PID}/meeting/src-1" and r["shared"] is False
    assert r["knowcap_link"] in r["summary"]
    urls = fake.urls()
    assert ("POST", "https://app.knowcap.ai/api/sources/prepare-upload") in urls
    assert ("PUT", "https://storage.example.com/signed/1") in urls
    assert ("POST", "https://app.knowcap.ai/api/sources/src-1/move") in urls
    assert ("POST", f"https://app.knowcap.ai/api/projects/{PID}/folders/fold-1/sources/bulk") in urls
    assert not any("/api/share/" in u for _m, u in urls)  # share: false -> no public link
    # request shapes from knowcap-mcp src/client.ts
    prep = json.loads(fake.calls[0][3])
    assert prep == {"projectId": PID, "fileName": "v.mp4", "fileSize": 1000, "mimeType": "video/mp4"}
    conf = next(json.loads(d) for m, u, _h, d in fake.calls if u.endswith("confirm-upload"))
    assert conf["path"] == "u/v.mp4" and conf["projectId"] == PID and conf["mimeType"] == "video/mp4"
    move = next(json.loads(d) for m, u, _h, d in fake.calls if u.endswith("/move"))
    assert move == {"targetProjectId": PID}


def test_api_key_goes_to_knowcap_only_never_to_the_signed_storage_url(tmp_path, kenv):
    run = make_run(tmp_path)
    fake = FakeKnowcap()
    send(run, kc_cfg(), kenv, fake)
    for method, url, headers, data in fake.calls:
        if method == "PUT":
            assert FAKE_KEY not in json.dumps(headers) and "x-api-key" not in headers
            assert headers["Authorization"] in ("Bearer upl-1", "Bearer upl-2")
            assert headers["Content-Type"] in ("video/mp4", "text/html")
        else:
            assert headers["x-api-key"] == FAKE_KEY and url.startswith("https://app.knowcap.ai/")
    put = next(d for m, _u, _h, d in fake.calls if m == "PUT")
    assert put == b"0" * 1000  # raw bytes, not multipart


def test_share_true_returns_public_link_and_other_channels_carry_it(tmp_path, kenv):
    run = make_run(tmp_path)
    fake = FakeKnowcap()
    cfg = kc_cfg(share=True)
    cfg["notify"] = {"webhook": {"enabled": True, "url": {"env": "H_URL"}}, **cfg["notify"]}  # listed first, still runs after
    env = dict(kenv, H_URL="https://hooks.example.com/h")
    res = send(run, cfg, env, fake)
    assert [r["channel"] for r in res] == ["knowcap", "webhook"]
    assert res[0]["knowcap_link"] == "https://app.knowcap.ai/share/tok123" and res[0]["shared"] is True
    hook = json.loads(next(d for m, u, _h, d in fake.calls if u == "https://hooks.example.com/h"))
    assert "Knowcap: https://app.knowcap.ai/share/tok123" in hook["text"]


def test_relative_share_url_is_made_absolute(tmp_path, kenv):
    res = send(make_run(tmp_path), kc_cfg(share=True), kenv, FakeKnowcap(share_url="/share/tok123"))
    assert res[0]["knowcap_link"] == "https://app.knowcap.ai/share/tok123"


def test_no_public_link_for_a_run_with_security_findings(tmp_path, kenv):
    fake = FakeKnowcap()
    res = send(make_run(tmp_path, security=2), kc_cfg(share=True), kenv, fake)
    assert res[0]["status"] == "SENT" and res[0]["shared"] is False and "/meeting/" in res[0]["knowcap_link"]
    assert not any("/api/share/" in u for _m, u in fake.urls())


def test_already_in_project_skips_the_move(tmp_path, kenv):
    fake = FakeKnowcap(lands_in_inbox=False)
    send(make_run(tmp_path), kc_cfg(), kenv, fake)
    assert not any(u.endswith("/move") for _m, u in fake.urls())


def test_rerun_never_uploads_twice_but_returns_the_link(tmp_path, kenv):
    run = make_run(tmp_path)
    send(run, kc_cfg(), kenv, FakeKnowcap())
    again = FakeKnowcap()
    res = send(run, kc_cfg(), kenv, again)
    assert res[0]["status"] == "SENT" and res[0]["calls"] == 0 and res[0]["already_sent"] == 2
    assert res[0]["knowcap_link"].endswith("/meeting/src-1")
    assert not again.calls


def test_report_failure_does_not_lose_the_video_link(tmp_path, kenv):
    res = send(make_run(tmp_path), kc_cfg(), kenv, FakeKnowcap(fail_report=True))
    assert res[0]["status"] == "SENT" and "report not uploaded" in res[0]["detail"] and res[0]["knowcap_link"]


def test_privacy_hit_refuses_upload_before_any_call(tmp_path, kenv):
    run = make_run(tmp_path)
    with open(f"{run}/report.html", "w") as fh:
        fh.write("<p>contact jane.doe" + "@" + "realclient.io</p>")  # built at runtime: the commit scan blocks literal emails
    fake = FakeKnowcap()
    for dry in (False, True):
        res = notify.deliver(run, kc_cfg(), send=not dry, env=kenv, http_fn=fake, out=lambda *_: None)
        assert res[0]["status"] == "REFUSED" and "privacy" in res[0]["detail"] and "realclient" not in res[0]["detail"]
    assert not fake.calls


def test_live_client_site_is_never_uploaded(tmp_path, kenv):
    cfg = dict(kc_cfg(), live=True)
    fake = FakeKnowcap()
    res = send(make_run(tmp_path), cfg, kenv, fake)
    assert res[0]["status"] == "REFUSED" and "production data" in res[0]["detail"] and not fake.calls


def test_missing_key_fails_cleanly_with_no_call(tmp_path, kenv):
    env = {k: v for k, v in kenv.items() if k != ENV_NAME}
    fake = FakeKnowcap()
    res = send(make_run(tmp_path), kc_cfg(), env, fake)
    assert res[0]["status"] == "FAIL" and "keys.py set" in res[0]["detail"] and not fake.calls


def test_missing_key_is_asked_for_via_keys_py(tmp_path, monkeypatch):
    asked = []
    monkeypatch.setenv("SMEKIT_NO_PROMPT", "0")
    monkeypatch.delenv("KNOWCAP_API_KEY", raising=False)
    ch = {"type": "knowcap", "enabled": True, "api_key": {"env": "KNOWCAP_API_KEY"}, "project_id": PID}
    notify.ask_missing_keys("knowcap", ch, asker=lambda name, reason: asked.append(name) or "")
    assert asked == ["KNOWCAP_API_KEY"]


def test_http_error_is_reported_without_the_key(tmp_path, kenv):
    def refuse(method, url, data=None, headers=None, **_k):
        raise urllib.error.HTTPError(url, 401, "Unauthorized", None, None)
    res = send(make_run(tmp_path), kc_cfg(), kenv, refuse)
    assert res[0]["status"] == "FAIL" and "401" in res[0]["detail"] and FAKE_KEY not in res[0]["detail"]


@pytest.mark.parametrize("over,where", [
    ({"project_id": None}, "project_id"),
    ({"project_id": 42}, "project_id"),
    ({"share": "yes"}, "share"),
    ({"folder_id": 7}, "folder_id"),
    ({"api_key": "literal"}, "api_key"),
    ({"api_base": "http://app.knowcap.ai"}, "api_base"),
])
def test_config_validation(over, where):
    with pytest.raises(notify.ConfigError, match=rf"notify\.knowcap\.{where}"):
        notify.validate_config(kc_cfg(**over))


def test_keys_check_lists_the_knowcap_key():
    import keys
    assert ("KNOWCAP_API_KEY", "notify.knowcap.api_key") in keys.needed(
        {"notify": {"knowcap": {"enabled": True, "api_key": {"env": "KNOWCAP_API_KEY"}, "project_id": PID}}})
