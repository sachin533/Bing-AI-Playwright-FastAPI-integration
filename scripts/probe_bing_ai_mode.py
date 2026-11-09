"""Phase 2 helper: locate the Bing 'AI MODE' entry point and test it anonymously."""

from __future__ import annotations

import json
import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:  # pragma: no cover
    pass

PROJECT_ROOT = Path(__file__).resolve().parent.parent
USER_DATA_DIR = PROJECT_ROOT / "browser_data"


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

        page.goto(
            "https://www.bing.com/search?q=what+is+java&ensearch=1",
            wait_until="domcontentloaded",
            timeout=45000,
        )
        page.wait_for_timeout(4000)

        links = page.evaluate(
            """() => {
                const out = [];
                for (const a of document.querySelectorAll('a[href]')) {
                    const t = (a.innerText || a.textContent || '').trim();
                    if (/ai\\s*mode|copilot/i.test(t) || /copilot|aimode|ai_mode|udm=/i.test(a.href)) {
                        out.push({text: t.slice(0,60), href: a.href,
                                  cls: (a.className||'').toString().slice(0,90)});
                    }
                }
                return out.slice(0, 40);
            }"""
        )
        print("== candidate AI-mode / copilot links on bing search ==")
        for item in links:
            print(json.dumps(item, ensure_ascii=False))

        # Click the visible "AI MODE" nav entry if it exists.
        try:
            ai = page.get_by_text("AI MODE", exact=False).first
            if ai.count() > 0 and ai.is_visible():
                print("\n== clicking 'AI MODE' ==")
                ai.click()
                page.wait_for_timeout(6000)
                print(f"  url after click: {page.url}")
                print(f"  title          : {page.title()}")
                inputs = page.evaluate(
                    """() => {
                        const out = [];
                        for (const el of document.querySelectorAll(
                                'textarea, input:not([type=hidden]), [contenteditable="true"], [role=textbox]')) {
                            const r = el.getBoundingClientRect();
                            if (r.width && r.height) {
                                out.push({
                                    tag: el.tagName.toLowerCase(),
                                    id: el.id || null,
                                    ph: el.getAttribute('placeholder'),
                                    aria: el.getAttribute('aria-label'),
                                    cls: (el.className||'').toString().slice(0,80),
                                });
                            }
                        }
                        return out;
                    }"""
                )
                print("  visible inputs:")
                for i in inputs:
                    print("   ", json.dumps(i, ensure_ascii=False))
        except Exception as exc:
            print(f"\nAI MODE click failed: {str(exc)[:300]}")

        ctx.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
