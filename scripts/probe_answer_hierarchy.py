"""Phase 2 helper: locate the precise container of the AI answer prose.

The iframe's ``.answer_container`` mixes the answer prose with a video
carousel and citation cards. This probe walks the DOM tree of the answer
frame and reports the deepest element that contains the answer prose, plus
any "stop generating" control used for completion detection.

Usage:
    py scripts/probe_answer_hierarchy.py
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

TREE_JS = """
(needle) => {
    const out = [];
    // find leaf-ish elements that contain the needle
    const all = document.querySelectorAll('*');
    let best = null, bestDepth = -1;
    for (const el of all) {
        const t = (el.innerText || '');
        if (!t.includes(needle)) continue;
        let d = 0, p = el;
        while (p) { d++; p = p.parentElement; }
        if (d > bestDepth) { bestDepth = d; best = el; }
    }
    if (!best) return {found: false};
    const chain = [];
    let p = best;
    while (p && p !== document.body) {
        const r = p.getBoundingClientRect();
        chain.push({
            tag: p.tagName.toLowerCase(),
            id: p.id || null,
            cls: (p.className||'').toString().slice(0,90),
            dataId: p.getAttribute('data-id'),
            textLen: (p.innerText||'').trim().length,
            rect: [Math.round(r.x),Math.round(r.y),Math.round(r.width),Math.round(r.height)],
        });
        p = p.parentElement;
    }
    // children of the deepest match
    const kids = Array.from(best.children).map(c => {
        const r = c.getBoundingClientRect();
        return {tag: c.tagName.toLowerCase(), id: c.id||null,
                cls: (c.className||'').toString().slice(0,80),
                textLen: (c.innerText||'').trim().length,
                text: (c.innerText||'').trim().slice(0,70),
                rect:[Math.round(r.x),Math.round(r.y),Math.round(r.width),Math.round(r.height)]};
    });
    return {found: true, chain, kids, bestText: (best.innerText||'').trim().slice(0,400)};
}
"""

CONTROLS_JS = """
() => {
    const out = [];
    for (const el of document.querySelectorAll('button,a,[role=button],[aria-label]')) {
        const aria = el.getAttribute('aria-label') || '';
        const title = el.getAttribute('title') || '';
        const txt = (el.innerText||'').trim().slice(0,40);
        const r = el.getBoundingClientRect();
        const hay = (aria + ' ' + title + ' ' + txt).toLowerCase();
        if (/stop|generat|cancel|loading|wait|thinking/.test(hay)) {
            out.push({tag: el.tagName.toLowerCase(), id: el.id||null,
                      cls:(el.className||'').toString().slice(0,70),
                      aria, title, txt, visible: !!(r.width&&r.height)});
        }
    }
    return out;
}
"""


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--question", default="What is Java programming?")
    ap.add_argument("--wait", type=int, default=22)
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

        # The answer frame of the LAST turn is the one with the highest turnindex.
        frames = [f for f in page.frames if "cpltsrchif=1" in (f.url or "")]

        def turn_index(url: str) -> int:
            import urllib.parse

            q = urllib.parse.parse_qs(urllib.parse.urlparse(url).query)
            try:
                return int(q.get("turnindex", ["0"])[0])
            except ValueError:
                return 0

        frames.sort(key=lambda f: turn_index(f.url or ""))
        answer_frame = frames[-1]
        print(f"== using frame turnindex={turn_index(answer_frame.url)}")
        print(f"   {answer_frame.url[:160]}")

        print("\n== DOM chain of the answer prose ==")
        res = answer_frame.evaluate(TREE_JS, "write once, run anywhere")
        if res.get("found"):
            for i, c in enumerate(res["chain"]):
                print(f"   [{i}] {c['tag']} id={c['id']} cls={c['cls']} len={c['textLen']} rect={c['rect']}")
            print("\n== children of the deepest match ==")
            for k in res["kids"]:
                print("   ", k)
        else:
            print("   needle not found in the frame")

        print("\n== generation controls in the answer frame ==")
        for c in answer_frame.evaluate(CONTROLS_JS):
            print("   ", c)

        print("\n== generation controls in the main page ==")
        for c in page.evaluate(CONTROLS_JS):
            print("   ", c)

        ctx.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
