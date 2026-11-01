"""Evidence video/screenshots must not show phone numbers (text or tel inputs)."""
import pytest
from playwright.sync_api import sync_playwright

import record


def test_phone_text_and_tel_input_are_masked():
    with sync_playwright() as p:
        b = p.chromium.launch()
        pg = b.new_page()
        pg.set_content("<p id=t>Call +44 7934 356171 now</p><input id=wa-phone type=tel value='+447934356171'>")
        pg.evaluate(record.CAPTION_JS)
        pg.wait_for_timeout(300)
        assert "[phone]" in pg.inner_text("#t") and "7934" not in pg.inner_text("#t")
        assert "text-security" in pg.evaluate("getComputedStyle(document.getElementById('wa-phone')).webkitTextSecurity") or \
            pg.evaluate("getComputedStyle(document.getElementById('wa-phone')).webkitTextSecurity") == "disc"
        b.close()
