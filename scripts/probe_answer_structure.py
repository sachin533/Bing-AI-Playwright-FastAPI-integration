"""Phase 2 helper: refine the answer extraction.

Now that we know the answer lives inside the conversation turn's iframe
(``div.answer_container``), this script:
  1. submits a question,
  2. locates the LAST conversation turn,
  3. inspects the internal structure of ``.answer_container`` to find the
     cleanest way to pull the prose answer,
  4. prints the extracted answer.

Usage:
    py scripts/probe_answer_structure.py
"""

from __future__ import annotations

import argparse
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

TURN_JS = """
() => {
    const turns = document.querySelectorAll('li.ca_turn');
    const last = turns[turns.length - 1];
    if (!last) return null;
    return {
        turnCount: turns.length,
        query: (last.querySelector('.ca_userquery_text') || {}).innerText || '',
        iframes: last.querySelectorAll('iframe').length,
        frameIds: Array.from(last.querySelectorAll('iframe')).map(f => f.src),
    };
}
"""

INNER_JS = """
() => {
    const out = [];
    for (const el of document.querySelectorAll('div,section,p,span,ul,ol,h2,h3')) {
        const cls = (el.className || '').toString();
        const id = el.id || '';
        if (!/answer|response|content|main|body|rich/i.test(cls + ' ' + id)) continue;
        const own = Array.from(el.childNodes).filter(n => n.nodeType === 3)
                         .map(n => n.textContent).join(' ').trim();
        const r = el.getBoundingClientRect();
        if (!r.width) continue;
        out.push({tag: el.tagName.toLowerCase(), id: id||null, cls: cls.slice(0,80),
                  ownLen: own.length, own: own.slice(0,90),
                  textLen: (el.innerText||'').trim().length});
    }
    return out.slice(0, 60);
}
"""


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--question", default="What is Java programming?")
    ap.add_argument("--wait", type=int, default=25)
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

        ta = page.locator("textarea[id^='b_copilot_composer']").first
        ta.wait_for(state="visible", timeout=20000)
        ta.click()
        ta.press_sequentially(args.question, delay=15)
        page.wait_for_timeout(800)
        page.locator("button.b_copilot_send").first.click()
        print("== submitted, waiting...")
        page.wait_for_timeout(args.wait * 1000)

        turn_info = page.evaluate(TURN_JS)
        print(f"== turn info: {turn_info}")

        # The answer lives in the iframe of the last turn.
        turns = page.locator("li.ca_turn")
        last = turns.last
        iframe = last.locator("iframe").first
        iframe.wait_for(state="attached", timeout=20000)

        # Reach into the iframe via Playwright's frame API.
        answer_frame = None
        for frame in page.frames:
            if frame.url and "cpltsrchif=1" in frame.url:
                answer_frame = frame
                break
        print(f"== answer frame url: {answer_frame.url if answer_frame else 'NOT FOUND'}")

        if answer_frame:
            print("\n== inner structure of the answer frame ==")
            for row in answer_frame.evaluate(INNER_JS):
                print("   ", row)

            container = answer_frame.locator(".answer_container").first
            container.wait_for(state="visible", timeout=20000)
            text = container.inner_text().strip()

            print("\n" + "=" * 78)
            print("=== EXTRACTED ANSWER (.answer_container) ===")
            print(text)
            print("=" * 78)
            print(f"[chars={len(text)}]")

            page.screenshot(path=str(PROJECT_ROOT / "logs" / "answer_extracted.png"), full_page=True)

        ctx.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
