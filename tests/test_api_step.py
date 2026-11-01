"""api step: HTTP status check as a recorded case."""
import shutil

import pytest

import record

pytestmark = pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg not installed")


def _plan(url, step):
    return {"name": "api", "base_url": url, "allow_hosts": ["127.0.0.1", "localhost"], "viewport": [800, 500],
            "steps": [{"do": "goto", "url": "index.html"}, dict(step, do="api", case="API-1")]}


def test_api_expected_status_passes(tmp_path, demo_site):
    s = record.run(_plan(demo_site, {"path": "index.html", "expect_status": 200}), str(tmp_path / "o"), narrate=False, total_timeout=60, step_timeout=10)
    assert s["counts"]["PASS"] == 1


def test_api_unexpected_status_fails(tmp_path, demo_site):
    s = record.run(_plan(demo_site, {"path": "nope.html", "expect_status": 200}), str(tmp_path / "o"), narrate=False, total_timeout=60, step_timeout=10)
    assert s["counts"]["FAIL"] == 1


def test_api_accepts_status_list_405(tmp_path, demo_site):
    s = record.run(_plan(demo_site, {"path": "index.html", "method": "POST", "expect_status": [405, 501]}), str(tmp_path / "o"), narrate=False, total_timeout=60, step_timeout=10)
    assert s["counts"]["PASS"] == 1
