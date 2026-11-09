"""Phase 2 helper: check Bing Search AI-mode entry points in a real browser.

Search-result AI mode historically allowed anonymous use, unlike copilot.com.
This script checks the live DOM for an AI-mode prompt box on each candidate.

Usage:
    py scripts/probe_bing_search_ai.py
"""

from __future__ import annotations

import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:  # pragma: no cover
    pass

PROJECT_ROOT = Path(__file__).resolve().parent.parent
USER_DATA_DIR = PROJECT_ROOT / "browser_data"

URLS = [
    "https://www.bing.com/search?q=what+is+java&showconv=1",
    "https://www.bing.com/search?q=what+is+java&FORM=QBLH&showconv=1&cvid=1",
    "https://www.bing.com/search?q=what+is+java&ensearch=1",
    "https://www.bing.com/images/search?q=what+is+java&showconv=1",
]

PROBES = [
    "#b_sde",
    "#b_prompt",
    "textarea",
    "[contenteditable='true']",
    "#b_tween span.s_txt",
    "[id*='b_prompt']",
    "[id*='copilot']",
    "[class*='copilot']",
    "[data-id*='Copilot']",
]


def main() -> int:
    USER_DATA_DIR.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as p:
        ctx = p.chromium.launch_persistent_context(
            user_data_dir=str(USER_DATA_DIR),
            headless=False,
            viewport={"width": 1440, "height": 900},
            locale="en-US",
            args=["--disable-blink-features=AutomationControlled"],
        )
        page = ctx.pages[0] if ctx.pages else ctx.new_page()

        for url in URLS:
            print("\n" + "=" * 78)
            print(f"### {url}")
            try:
                page.goto(url, wait_until="domcontentloaded", timeout=45000)
                page.wait_for_timeout(5000)
            except Exception as exc:
                print(f"  NAV ERROR: {str(exc)[:200]}")
                continue
            print(f"  final url : {page.url}")
            print(f"  title     : {page.title()}")
            for sel in PROBES:
                try:
                    loc = page.locator(sel)
                    n = loc.count()
                    vis = 0
                    for i in range(min(n, 3)):
                        try:
                            if loc.nth(i).is_visible():
                                vis += 1
                        except Exception:
                            pass
                    if n:
                        print(f"  probe {sel!r:38} count={n} visible~{vis}")
                except Exception:
                    pass
            snippet = page.evaluate(
                """() => {
                    const t = (document.body.innerText || '').replace(/\\n{2,}/g, '\\n');
                    return t.slice(0, 700);
                }"""
            )
            print("  body:")
            for line in snippet.splitlines():
                if line.strip():
                    print("      " + line.strip()[:120])

        ctx.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
