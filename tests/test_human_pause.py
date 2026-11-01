"""human_pause step: wait for a person (scan, tap, approve), then resume."""
import shutil
import threading
import time

import pytest

import record

needs_browser = pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg not installed")


def _plan(url, go, timeout_s):
    return {"name": "hp", "base_url": url, "allow_hosts": ["127.0.0.1", "localhost"], "viewport": [800, 500],
            "steps": [{"do": "goto", "url": "index.html"},
                      {"do": "human_pause", "say": "Scan the QR with your phone", "wait_file": str(go),
                       "timeout_s": timeout_s, "case": "HP-1"},
                      {"do": "screenshot", "name": "after"}]}


@needs_browser
def test_human_pause_resumes_on_go_file(tmp_path, demo_site):
    go = tmp_path / "GO.txt"
    threading.Timer(4, lambda: go.write_text("go")).start()
    t = time.time()
    s = record.run(_plan(demo_site, go, 60), str(tmp_path / "out"), narrate=False, total_timeout=120, step_timeout=10)
    assert s["counts"]["PASS"] == 1 and s["counts"]["FAIL"] == 0
    assert time.time() - t >= 4
    assert not (tmp_path / "GO.txt.WAITING").exists()


@needs_browser
def test_human_pause_times_out_as_fail(tmp_path, demo_site):
    s = record.run(_plan(demo_site, tmp_path / "never", 2), str(tmp_path / "out"), narrate=False, total_timeout=120, step_timeout=10)
    assert s["counts"]["FAIL"] == 1 and "failed" in s["stopped"]
