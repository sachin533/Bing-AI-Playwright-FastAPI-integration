"""Phase 2 helper: tell bullet lists apart from citation lists.

The previous extraction hid every ``ul.gs_cit_stry_pre`` element, which
also removed the real bullet lists. This probe dumps every list element in
the answer with its class, attributes and text so the two can be told
apart reliably.

Usage:
    py scripts/probe_lists.py
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

LISTS_JS = """
() => {
    const host = document.querySelector('.gs_text') || document.querySelector('.answer_container');
    if (!host) return null;
    const out = [];
    for (const ul of host.querySelectorAll('ul,ol')) {
        const r = ul.getBoundingClientRect();
        const attrs = {};
        for (const a of ul.attributes) attrs[a.name] = a.value;
        out.push({
            tag: ul.tagName.toLowerCase(),
            attrs,
            cls: (ul.className||'').toString(),
            visible: !!(r.width && r.height),
            textLen: (ul.innerText||'').trim().length,
            text: (ul.innerText||'').trim().slice(0,220),
            liCount: ul.children.length,
            liClasses: Array.from(ul.children).slice(0,4).map(li => ({
                cls: (li.className||'').toString(),
                attrs: Array.from(li.attributes).map(a => a.name + '=' + a.value).join(' ').slice(0,120),
                text: (li.innerText||'').trim().slice(0,80),
                links: li.querySelectorAll('a').length,
                hasImg: li.querySelectorAll('img').length,
            })),
        });
    }
    return out;
}
"""

HEADINGS_JS = """
() => {
    const host = document.querySelector('.gs_text') || document.querySelector('.answer_container');
    if (!host) return null;
    return Array.from(host.children).map(c => ({
        tag: c.tagName.toLowerCase(),
        cls: (c.className||'').toString().slice(0,60),
        textLen: (c.innerText||'').trim().length,
        head: (c.innerText||'').trim().slice(0,60),
    }));
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
    ap.add_argument("--question", default="What is Java programming?")
    ap.add_argument("--wait", type=int, default=28)
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

        turns_before = page.locator("li.ca_turn").count()
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

        print("\n== direct children of the answer host ==")
        for c in frame.evaluate(HEADINGS_JS) or []:
            print("   ", c)

        print("\n== every list element ==")
        for ul in frame.evaluate(LISTS_JS) or []:
            print(f"\n   <{ul['tag']} class={ul['cls']!r} visible={ul['visible']} "
                  f"textLen={ul['textLen']} liCount={ul['liCount']}>")
            print(f"     attrs: {ul['attrs']}")
            print(f"     text : {ul['text']!r}")
            for li in ul["liClasses"]:
                print(f"     li   : {li}")

        ctx.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
