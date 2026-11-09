"""Phase 2 helper: dump the citation-chip markup inside the answer.

Content bullet lists and citation blocks share the class
``gs_cit_stry_pre``. The citation artefacts that leaked into the extracted
text ("Wikipedia", "+1", "2", "3 Sources") come from specific inline
elements. This probe prints their outerHTML so the cleaner can target
exactly those nodes.

Usage:
    py scripts/probe_anchors.py
"""

from __future__ import annotations

import argparse
import sys
import urllib.parse
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

ANCHORS_JS = """
() => {
    const host = document.querySelector('.gs_text') || document.querySelector('.answer_container');
    if (!host) return null;
    return Array.from(host.querySelectorAll('a')).slice(0, 12).map(a => ({
        outer: a.outerHTML.slice(0, 420),
        text: (a.innerText||a.textContent||'').trim(),
        cls: (a.className||'').toString(),
        parentCls: (a.parentElement && a.parentElement.className || '').toString().slice(0,60),
        parentTag: a.parentElement ? a.parentElement.tagName.toLowerCase() : null,
        siblingTags: Array.from(a.parentElement ? a.parentElement.children : [])
            .map(c => c.tagName.toLowerCase() + '.' + ((c.className||'').toString().split(/\\s+/)[0]||'')),
    }));
}
"""

NONTOKEN_JS = """
() => {
    const host = document.querySelector('.gs_text') || document.querySelector('.answer_container');
    if (!host) return null;
    const out = [];
    for (const el of host.querySelectorAll('*')) {
        if (el.classList.contains('gs_tkn')) continue;
        if (el.children.length) continue;            // leaf only
        const t = (el.innerText||el.textContent||'').trim();
        if (!t || t.length > 40) continue;
        out.push({
            tag: el.tagName.toLowerCase(),
            cls: (el.className||'').toString(),
            text: t,
            outer: el.outerHTML.slice(0, 260),
        });
    }
    return out.slice(0, 30);
}
"""


def _turn_index(url: str) -> int:
    q = urllib.parse.parse_qs(urllib.parse.urlparse(url).query)
    try:
        return int(q.get("turnindex", ["0"])[0])
    except ValueError:
        return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--question", default="What is the capital of the Maldives and what is it famous for?"
    )
    ap.add_argument("--wait", type=int, default=30)
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
        page.wait_for_timeout(3500)

        ta = page.locator("textarea[id^='b_copilot_composer']").first
        ta.wait_for(state="visible", timeout=20000)
        ta.click()
        ta.press_sequentially(args.question, delay=15)
        page.wait_for_timeout(800)
        page.locator("button.b_copilot_send").first.click()
        print("== submitted; waiting...")
        page.wait_for_timeout(args.wait * 1000)

        frames = [f for f in page.frames if "cpltsrchif=1" in (f.url or "")]
        frames.sort(key=lambda f: _turn_index(f.url or ""))
        frame = frames[-1]
        print(f"== frame turnindex={_turn_index(frame.url)}")

        print("\n== anchors inside the answer ==")
        for a in frame.evaluate(ANCHORS_JS) or []:
            print(f"\n   text={a['text']!r}")
            print(f"   cls={a['cls']!r} parent={a['parentTag']}.{a['parentCls']}")
            print(f"   siblings={a['siblingTags']}")
            print(f"   outer={a['outer']!r}")

        print("\n== leaf nodes that are NOT .gs_tkn ==")
        for n in frame.evaluate(NONTOKEN_JS) or []:
            print(f"   {n['tag']} cls={n['cls']!r} text={n['text']!r}")
            print(f"      {n['outer']!r}")

        ctx.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
