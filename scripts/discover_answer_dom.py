"""Phase 2 helper: submit a question and DISCOVER the answer container.

Instead of guessing selectors, this script submits the question and then
polls the live DOM, printing every element whose id/class looks answer-like
along with the growing text length. The element whose text grows with the
streamed answer is the answer container.

Usage:
    py scripts/discover_answer_dom.py
"""

from __future__ import annotations

import argparse
import json
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
BING_AI_URL = "https://www.bing.com/copilotsearch?q=what+is+java&FORM=CSSCOP"

SNAPSHOT_JS = """
() => {
    const out = [];
    const skip = new Set(['SCRIPT','STYLE','NOSCRIPT','SVG','PATH']);
    for (const el of document.querySelectorAll('div,section,article,main,span,p,h2,h3,li')) {
        if (skip.has(el.tagName)) continue;
        const id = el.id || '';
        const cls = (el.className || '').toString();
        const r = el.getBoundingClientRect();
        if (!(r.width > 30 && r.height > 10)) continue;
        const own = Array.from(el.childNodes)
            .filter(n => n.nodeType === 3)
            .map(n => n.textContent)
            .join(' ').trim();
        const text = (el.innerText || '').trim();
        out.push({
            tag: el.tagName.toLowerCase(),
            id: id || null,
            cls: cls.slice(0, 90),
            dataId: el.getAttribute('data-id'),
            ownTextLen: own.length,
            textLen: text.length,
            own: own.slice(0, 60),
            text: text.slice(0, 80),
            rect: [Math.round(r.x), Math.round(r.y), Math.round(r.width), Math.round(r.height)],
        });
    }
    return out;
}
"""


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--question", default="What is Java programming?")
    ap.add_argument("--poll", type=int, default=45, help="seconds to poll the DOM")
    ap.add_argument("--interval", type=float, default=2.0)
    args = ap.parse_args()

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

        page.goto(BING_AI_URL, wait_until="domcontentloaded", timeout=60000)
        page.wait_for_timeout(3000)
        print(f"== url: {page.url}")

        ta = page.locator("textarea[id^='b_copilot_composer']").first
        ta.wait_for(state="visible", timeout=20000)
        ta.click()
        ta.press_sequentially(args.question, delay=15)
        page.wait_for_timeout(600)

        send = page.locator("button.b_copilot_send").first
        print(f"== send enabled: {send.is_enabled()}")
        send.click()
        print("== submitted")

        baseline = set()
        prev_snapshot: list[dict] = []
        elapsed = 0.0
        while elapsed < args.poll:
            page.wait_for_timeout(int(args.interval * 1000))
            elapsed += args.interval
            snapshot = page.evaluate(SNAPSHOT_JS)
            prev_map = {f"{e['tag']}|{e['id']}|{e['cls']}|{e['dataId']}": e for e in prev_snapshot}
            changed = []
            for e in snapshot:
                key = f"{e['tag']}|{e['id']}|{e['cls']}|{e['dataId']}"
                old = prev_map.get(key)
                if old is None:
                    if e["textLen"] > 40:
                        changed.append(("NEW", e))
                elif old["textLen"] != e["textLen"]:
                    changed.append((f"GROW {old['textLen']}->{e['textLen']}", e))
            if changed:
                print(f"\n--- t={elapsed:.0f}s  url={page.url}")
                for kind, e in changed[:25]:
                    print(f"  [{kind}] {e['tag']} id={e['id']} cls={e['cls'][:60]} data-id={e['dataId']}")
                    print(f"        own={e['ownTextLen']} text={e['textLen']} rect={e['rect']}")
                    if e["text"]:
                        print(f"        text: {e['text']!r}")
            prev_snapshot = snapshot

        print("\n== FINAL: largest text blocks ==")
        final = page.evaluate(SNAPSHOT_JS)
        final.sort(key=lambda e: -e["textLen"])
        for e in final[:25]:
            print(
                f"  {e['tag']} id={e['id']} cls={e['cls'][:70]} data-id={e['dataId']} "
                f"textLen={e['textLen']} rect={e['rect']}"
            )
            if e["text"]:
                print(f"      {e['text']!r}")

        page.screenshot(path=str(PROJECT_ROOT / "logs" / "discover_answer.png"), full_page=False)
        ctx.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
