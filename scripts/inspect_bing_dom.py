"""Phase 2 helper: inspect the REAL Bing/Copilot chat DOM.

Opens the chat page in a persistent Chromium profile and prints:
  - final URL, title
  - every textbox / input / contenteditable / button with its accessible info
  - candidate response containers

Nothing here is hardcoded to a guessed selector: everything is discovered
from the live DOM. This script is a diagnostic tool, not part of the API.

Usage:
    py scripts/inspect_bing_dom.py
    py scripts/inspect_bing_dom.py --url "https://www.bing.com/chat" --wait 8
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

# Windows consoles default to cp1252 and choke on Unicode arrows/em-dashes.
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:  # pragma: no cover
    pass

PROJECT_ROOT = Path(__file__).resolve().parent.parent
USER_DATA_DIR = PROJECT_ROOT / "browser_data"
DEFAULT_URL = "https://www.bing.com/chat"


def _describe(page, index: int, handle) -> dict:
    try:
        info = handle.evaluate(
            """el => {
                const attrs = {};
                for (const a of el.attributes || []) attrs[a.name] = a.value;
                const rect = el.getBoundingClientRect();
                const label = el.getAttribute('aria-label');
                const ph = el.getAttribute('placeholder');
                const title = el.getAttribute('title');
                return {
                    tag: el.tagName.toLowerCase(),
                    id: el.id || null,
                    attrs,
                    ariaLabel: label || null,
                    placeholder: ph || null,
                    title: title || null,
                    role: el.getAttribute('role') || null,
                    text: (el.innerText || el.textContent || '').trim().slice(0, 120),
                    visible: !!(rect.width && rect.height),
                    rect: { x: Math.round(rect.x), y: Math.round(rect.y),
                            w: Math.round(rect.width), h: Math.round(rect.height) },
                    testid: el.getAttribute('data-testid')
                            || el.getAttribute('data-test')
                            || el.getAttribute('data-bi-id')
                            || null,
                };
            }"""
        )
    except Exception as exc:  # pragma: no cover - diagnostic path
        info = {"error": str(exc)}
    info["index"] = index
    return info


def collect(page) -> list[dict]:
    """Discover interactive + candidate answer elements from the live DOM."""
    selectors = [
        "textarea",
        "input:not([type=hidden])",
        "[contenteditable='true']",
        "[role=textbox]",
        "[role=button]",
        "button",
        "[role=searchbox]",
    ]
    found: list[dict] = []
    seen = set()
    for sel in selectors:
        try:
            handles = page.query_selector_all(sel)
        except Exception:
            continue
        for h in handles:
            try:
                key = h.evaluate(
                    "el => el.tagName + '|' + (el.id||'') + '|' + (el.className||'') + '|' + (el.innerText||'').slice(0,40)"
                )
            except Exception:
                continue
            if key in seen:
                continue
            seen.add(key)
            found.append(_describe(page, len(found), h))
    return found


def collect_answer_candidates(page) -> list[dict]:
    """Look for nodes that look like assistant answer bubbles."""
    return page.evaluate(
        """() => {
            const out = [];
            const sels = [
                '[data-message-author-role="assistant"]',
                '.b_ans .b_text',
                '[class*="conversation-answer"]',
                '[class*="answer"]',
                '[data-testid*="answer"]',
                '[data-testid*="response"]',
                'div[role="listitem"]',
                '.b_algoHeader',
            ];
            for (const s of sels) {
                let nodes = [];
                try { nodes = document.querySelectorAll(s); } catch (e) { continue; }
                for (const n of nodes) {
                    const r = n.getBoundingClientRect();
                    out.push({
                        selector: s,
                        tag: n.tagName.toLowerCase(),
                        cls: (n.className || '').toString().slice(0, 100),
                        text: (n.innerText || '').trim().slice(0, 200),
                        visible: !!(r.width && r.height),
                    });
                }
            }
            return out.slice(0, 60);
        }"""
    )


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default=DEFAULT_URL)
    ap.add_argument("--wait", type=int, default=6, help="seconds to wait after load")
    ap.add_argument("--headed", action="store_true", default=True)
    ap.add_argument("--headless", dest="headed", action="store_false")
    args = ap.parse_args()

    USER_DATA_DIR.mkdir(parents=True, exist_ok=True)

    with sync_playwright() as p:
        ctx = p.chromium.launch_persistent_context(
            user_data_dir=str(USER_DATA_DIR),
            headless=args.headed,
            args=["--start-maximized", "--disable-blink-features=AutomationControlled"],
            viewport={"width": 1440, "height": 900},
            locale="en-US",
        )
        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        print(f"== navigating to {args.url}")
        page.goto(args.url, wait_until="domcontentloaded", timeout=60000)
        page.wait_for_timeout(args.wait * 1000)

        print(f"== final url  : {page.url}")
        print(f"== title      : {page.title()}")

        print("\n== interactive elements ==")
        for item in collect(page):
            if not item.get("visible", True):
                continue
            print(json.dumps(item, ensure_ascii=False))

        print("\n== answer container candidates ==")
        for item in collect_answer_candidates(page):
            print(json.dumps(item, ensure_ascii=False))

        print("\n== body text (first 1500 chars) ==")
        body = page.evaluate("() => (document.body.innerText || '').slice(0, 1500)")
        print(body)

        input("\nPress Enter to close the browser and exit...")
        ctx.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
