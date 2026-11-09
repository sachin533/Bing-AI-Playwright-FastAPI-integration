"""Phase 2 helper: compare candidate answer containers + find the
"generation finished" signal.

Two questions:
  1. Which container holds the AI prose without the video carousel and the
     citation cards?
  2. How do we know the answer stopped streaming? (no "Stop generating"
     control was found by the previous probe)

Usage:
    py scripts/probe_candidates.py
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

CANDIDATES = [
    "li.b_ans",
    "#copans_container",
    ".answer_container",
    ".gs_multianshead_main",
    ".gs_temp_content.gs_row_4",
    ".gs_text",
    ".gs_text.gs_mdr",
    ".b_rich",
]

ALL_BUTTONS_JS = """
() => {
    const out = [];
    for (const el of document.querySelectorAll('button,[role=button],a[class*=copilot],div[class*=copilot]')) {
        const cls = (el.className||'').toString();
        const r = el.getBoundingClientRect();
        out.push({
            tag: el.tagName.toLowerCase(),
            id: el.id||null,
            cls: cls.slice(0,80),
            aria: el.getAttribute('aria-label'),
            title: el.getAttribute('title'),
            disabled: el.disabled === true || el.getAttribute('aria-disabled')==='true',
            visible: !!(r.width&&r.height),
            w: Math.round(r.width), h: Math.round(r.height),
            text: (el.innerText||'').trim().slice(0,40),
        });
    }
    return out;
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

        print("== buttons in the MAIN page BEFORE submit ==")
        for b in page.evaluate(ALL_BUTTONS_JS):
            if "copilot" in (b["cls"] or "").lower() or (b["aria"] or ""):
                print("   ", b)

        page.locator("button.b_copilot_send").first.click()
        print("\n== submitted ==")

        # Observe the answer growing to detect completion.
        frames = [f for f in page.frames if "cpltsrchif=1" in (f.url or "")]
        frames.sort(key=lambda f: _turn_index(f.url or ""))
        answer_frame = frames[-1] if frames else None

        print("\n== answer length over time (answer_frame .answer_container) ==")
        last = -1
        stable = 0
        for i in range(60):
            page.wait_for_timeout(1000)
            if answer_frame is None:
                frames = [f for f in page.frames if "cpltsrchif=1" in (f.url or "")]
                frames.sort(key=lambda f: _turn_index(f.url or ""))
                answer_frame = frames[-1] if frames else None
                continue
            try:
                loc = answer_frame.locator(".answer_container").first
                txt = loc.inner_text() if loc.count() else ""
            except Exception:
                txt = ""
            n = len(txt)
            if n == last and n > 0:
                stable += 1
            else:
                stable = 0
            print(f"   t={i+1:>2}s len={n:<6} stable={stable}")
            last = n
            if stable >= 4:
                break

        if answer_frame is None:
            print("!! no answer frame")
            ctx.close()
            return 1

        print("\n== candidate containers in the answer frame ==")
        for sel in CANDIDATES:
            try:
                loc = answer_frame.locator(sel).first
                if loc.count() == 0:
                    print(f"   {sel:38} -> (not present)")
                    continue
                text = loc.inner_text().strip()
                print(f"   {sel:38} -> {len(text)} chars")
                print(f"       head: {text[:110]!r}")
                print(f"       tail: {text[-110:]!r}")
            except Exception as exc:
                print(f"   {sel:38} -> error {str(exc)[:80]}")

        print("\n== buttons in the MAIN page AFTER submit ==")
        for b in page.evaluate(ALL_BUTTONS_JS):
            if "copilot" in (b["cls"] or "").lower() or (b["aria"] or ""):
                print("   ", b)

        print("\n== buttons in the ANSWER FRAME ==")
        for b in answer_frame.evaluate(ALL_BUTTONS_JS):
            if b.get("visible"):
                print("   ", b)

        ctx.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
