"""Phase 2 helper: inspect how citations are marked up inside the answer.

The extracted text contains citation artefacts such as "Wikipedia", "+1",
"2" and "3 Sources" on their own lines. This probe dumps the DOM of a
paragraph so the cleaner can remove exactly those nodes and nothing else.

Usage:
    py scripts/probe_citations.py
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


def _turn_index(url: str) -> int:
    q = urllib.parse.parse_qs(urllib.parse.urlparse(url).query)
    try:
        return int(q.get("turnindex", ["0"])[0])
    except ValueError:
        return 0


PARA_HTML_JS = """
() => {
    const host = document.querySelector('.gs_text') || document.querySelector('.gs_multianshead_main');
    if (!host) return null;
    const paras = Array.from(host.querySelectorAll('.gs_p'));
    return {
        paraCount: paras.length,
        samples: paras.slice(0, 4).map(p => p.innerHTML.slice(0, 1400)),
        childTags: Array.from(host.children).map(c => ({
            tag: c.tagName.toLowerCase(),
            cls: (c.className||'').toString().slice(0,80),
            textLen: (c.innerText||'').trim().length,
        })),
    };
}
"""

LINK_INFO_JS = """
() => {
    const host = document.querySelector('.gs_text') || document.querySelector('.gs_multianshead_main');
    if (!host) return null;
    return Array.from(host.querySelectorAll('a')).slice(0, 25).map(a => ({
        cls: (a.className||'').toString().slice(0,70),
        href: (a.getAttribute('href')||'').slice(0,90),
        title: a.getAttribute('title'),
        text: (a.innerText||'').trim().slice(0,40),
    }));
}
"""

NODE_TAGS_JS = """
() => {
    const host = document.querySelector('.gs_text') || document.querySelector('.gs_multianshead_main');
    if (!host) return null;
    const tags = {};
    for (const el of host.querySelectorAll('*')) {
        const cls = (el.className||'').toString();
        const key = el.tagName.toLowerCase() + (cls ? '.' + cls.split(/\\s+/)[0] : '');
        tags[key] = (tags[key] || 0) + 1;
    }
    return Object.entries(tags).sort((a,b) => b[1]-a[1]).slice(0, 45);
}
"""


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--question", default="What is the capital of the Maldives?")
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

        print("\n== element tag frequency inside the answer ==")
        for k, v in (frame.evaluate(NODE_TAGS_JS) or []):
            print(f"   {v:>4}  {k}")

        print("\n== links inside the answer ==")
        for a in (frame.evaluate(LINK_INFO_JS) or []):
            print("   ", a)

        print("\n== paragraph HTML samples ==")
        res = frame.evaluate(PARA_HTML_JS) or {}
        print(f"   paragraphs: {res.get('paraCount')}")
        for s in res.get("samples", []):
            print("\n   ---")
            print("   " + s.replace("\n", "\n   "))

        print("\n== direct children of the answer host ==")
        for c in res.get("childTags", []):
            print("   ", c)

        ctx.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
