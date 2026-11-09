"""Phase 2 helper: probe candidate Bing / Copilot chat URLs.

For each URL it records the final URL after redirects, the page title, and
whether a chat input box could be found. Used to discover the correct
entry point for the chat interface - no selectors are assumed.

Usage:
    py scripts/probe_urls.py
"""

from __future__ import annotations

import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:  # pragma: no cover
    pass

PROJECT_ROOT = Path(__file__).resolve().parent.parent
USER_DATA_DIR = PROJECT_ROOT / "browser_data"

URLS = [
    "https://www.bing.com/chat",
    "https://copilot.com/chat",
    "https://copilot.microsoft.com/chat",
    "https://m365.cloud.microsoft/chat",
    "https://www.bing.com/copilotchat",
    "https://www.bing.com/search?q=test&showconv=1",
]

INPUT_PROBES = [
    "#b_sde",
    "textarea#b_sde",
    "#search_form textarea",
    "textarea",
    "input#b_sde",
    "[contenteditable='true']",
    "#prompt-text-container",
    ".text-area-container textarea",
]


def main() -> int:
    USER_DATA_DIR.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as p:
        ctx = p.chromium.launch_persistent_context(
            user_data_dir=str(USER_DATA_DIR),
            headless=False,
            args=["--start-maximized", "--disable-blink-features=AutomationControlled"],
            viewport={"width": 1440, "height": 900},
            locale="en-US",
        )
        page = ctx.pages[0] if ctx.pages else ctx.new_page()

        for url in URLS:
            print("\n" + "=" * 78)
            print(f"### {url}")
            try:
                page.goto(url, wait_until="domcontentloaded", timeout=45000)
                page.wait_for_timeout(4000)
            except Exception as exc:
                print(f"  NAV ERROR: {exc}")
                continue

            print(f"  final url : {page.url}")
            print(f"  title     : {page.title()}")

            found = None
            for sel in INPUT_PROBES:
                try:
                    loc = page.locator(sel).first
                    if loc.count() > 0 and loc.is_visible():
                        found = sel
                        break
                except Exception:
                    continue
            print(f"  input     : {found or 'NONE FOUND'}")

            snippet = page.evaluate(
                """() => {
                    const t = (document.body.innerText || '').replace(/\\n{2,}/g, '\\n');
                    return t.slice(0, 400);
                }"""
            )
            print("  body      :")
            for line in snippet.splitlines():
                if line.strip():
                    print("      " + line.strip()[:120])

        input("\nPress Enter to close the browser and exit...")
        ctx.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
