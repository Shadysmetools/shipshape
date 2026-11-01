"""expect_text must not pass on ShipShape's own caption overlay."""
import shutil

import pytest

import record

pytestmark = pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg not installed")


def _plan(url, step):
    return {"name": "cap", "base_url": url, "allow_hosts": ["127.0.0.1", "localhost"], "viewport": [800, 500],
            "steps": [{"do": "goto", "url": "index.html"}, step]}


def test_text_only_in_caption_does_not_pass(tmp_path, demo_site):
    step = {"do": "expect_text", "text": "Zebra-Only-In-Narration", "case": "CAP-1", "say": "We expect Zebra-Only-In-Narration here"}
    s = record.run(_plan(demo_site, step), str(tmp_path / "o"), narrate=False, total_timeout=60, step_timeout=3)
    assert s["counts"]["FAIL"] == 1 and s["counts"]["PASS"] == 0


def test_real_page_text_still_passes(tmp_path, demo_site):
    step = {"do": "expect_text", "text": "Create account", "case": "CAP-2", "say": "The button is there"}
    s = record.run(_plan(demo_site, step), str(tmp_path / "o"), narrate=False, total_timeout=60, step_timeout=5)
    assert s["counts"]["PASS"] == 1
