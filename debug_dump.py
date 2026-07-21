"""One-off debug script: render a URL with headless Chromium and save the
resulting HTML to a file, so we can inspect the real DOM structure.

Usage: python debug_dump.py <url> [output_file]
"""

import sys

from playwright.sync_api import sync_playwright

url = sys.argv[1]
out_path = sys.argv[2] if len(sys.argv) > 2 else "page_dump.html"

with sync_playwright() as p:
    browser = p.chromium.launch()
    page = browser.new_page()
    page.goto(url, timeout=60000)
    page.wait_for_timeout(12000)  # let any client-side rendering settle
    html = page.content()
    browser.close()

with open(out_path, "w", encoding="utf-8") as f:
    f.write(html)

print(f"Saved {len(html)} chars to {out_path}")
