import contextlib
import functools
import http.server
import os
import socket
import sys
import threading

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "scripts"))


def free_port():
    with contextlib.closing(socket.socket()) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class _Quiet(http.server.SimpleHTTPRequestHandler):
    extra_headers = {}

    def log_message(self, *a):
        pass

    def end_headers(self):
        for k, v in self.extra_headers.items():
            self.send_header(k, v)
        super().end_headers()


@contextlib.contextmanager
def serve(directory, headers=None):
    port = free_port()
    handler = type("H", (_Quiet,), {"extra_headers": headers or {}})
    httpd = http.server.ThreadingHTTPServer(("127.0.0.1", port), functools.partial(handler, directory=directory))
    t = threading.Thread(target=httpd.serve_forever, daemon=True)
    t.start()
    try:
        yield f"http://127.0.0.1:{port}/"
    finally:
        httpd.shutdown()


@pytest.fixture
def demo_site():
    with serve(os.path.join(ROOT, "examples", "demo-app")) as url:
        yield url


@pytest.fixture(autouse=True)
def _no_real_keys(tmp_path, monkeypatch):
    """No test opens a key window, reads the user's real key store or keychain (keys.py)."""
    monkeypatch.setenv("SMEKIT_NO_PROMPT", "1")
    monkeypatch.setenv("SMEKIT_NO_KEYRING", "1")
    monkeypatch.setenv("SMEKIT_KEYS_DIR", str(tmp_path / "_keys"))
    try:
        import keys
        keys._DECLINED.clear()
    except ImportError:
        pass
