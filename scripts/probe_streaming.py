"""Phase 2 helper: verify streaming behaviour with a UNIQUE question.

The previous probes reused a cached answer, so the text was already
complete one second after submitting. This script asks something the page
has never been asked, then records:

  * the turn count before / after submitting,
  * the ``turnindex`` of the new answer frame,
  * the answer length over time (to see the text streaming in),
  * any control that appears while generating ("stop" / "cancel"),
  * the block structure inside ``.gs_multianshead_main``.

Usage:
    py scripts/probe_streaming.py
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

BLOCKS_JS = """
() => {
    const host = document.querySelector('.gs_multianshead_main')
              || document.querySelector('.answer_container');
    if (!host) return null;
    const walk = (el, depth) => {
        const out = [];
        for (const c of el.children) {
            const r = c.getBoundingClientRect();
            const t = (c.innerText || '').trim();
            out.push({
                depth,
                tag: c.tagName.toLowerCase(),
                id: c.id || null,
                cls: (c.className||'').toString().slice(0,80),
                textLen: t.length,
                head: t.slice(0,70),
                visible: !!(r.width && r.height),
            });
            if (depth < 2) out.push(...walk(c, depth + 1));
        }
        return out;
    };
    return walk(host, 0);
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
        "--question",
        default="In one short paragraph, what is the capital of the Maldives and what is it famous for?",
    )
    ap.add_argument("--wait", type=int, default=45)
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
        print(f"== turns before submit: {turns_before}")

        ta = page.locator("textarea[id^='b_copilot_composer']").first
        ta.wait_for(state="visible", timeout=20000)
        ta.click()
        ta.press_sequentially(args.question, delay=15)
        page.wait_for_timeout(800)
        page.locator("button.b_copilot_send").first.click()
        print("== submitted\n")

        print("== t | turns | newFrameTurn | answerLen | stable | stopCtl ==")
        last_len = -1
        stable = 0
        new_frame = None
        for i in range(args.wait):
            page.wait_for_timeout(1000)
            turns_now = page.locator("li.ca_turn").count()

            frames = [f for f in page.frames if "cpltsrchif=1" in (f.url or "")]
            frames.sort(key=lambda f: _turn_index(f.url or ""))
            # the frame of the newest turn
            target = None
            for f in frames:
                if _turn_index(f.url or "") >= turns_before:
                    target = f
            if target is None and frames:
                target = frames[-1]
            if target is not None:
                new_frame = target

            length = -1
            if new_frame is not None:
                try:
                    loc = new_frame.locator(".answer_container").first
                    if loc.count():
                        length = len(loc.inner_text().strip())
                except Exception:
                    length = -1

            if length == last_len and length > 0:
                stable += 1
            else:
                stable = 0
            last_len = length

            stop_ctl = 0
            try:
                stop_ctl = page.evaluate(
                    """() => {
                        let n = 0;
                        for (const el of document.querySelectorAll('*')) {
                            const hay = ((el.className||'')+' '+(el.id||'')+' '
                                +(el.getAttribute('aria-label')||'')).toLowerCase();
                            if (!/stop|cancel|abort|generating|loading|spinner/.test(hay)) continue;
                            const r = el.getBoundingClientRect();
                            if (r.width && r.height) n++;
                        }
                        return n;
                    }"""
                )
            except Exception:
                pass

            print(
                f"  {i+1:>2}s | {turns_now} | "
                f"{_turn_index(new_frame.url) if new_frame else '-':>3} | "
                f"{length:>9} | {stable:>6} | {stop_ctl:>8}"
            )
            if stable >= 4 and length > 50:
                break

        print("\n== block structure of .gs_multianshead_main ==")
        if new_frame:
            for row in new_frame.evaluate(BLOCKS_JS) or []:
                print(
                    f"   {'  '*row['depth']}{row['tag']} id={row['id']} cls={row['cls']} "
                    f"len={row['textLen']} vis={row['visible']}"
                )
                print(f"   {'  '*row['depth']}  head: {row['head']!r}")

        print("\n== final texts ==")
        if new_frame:
            for sel in (".answer_container", ".gs_multianshead_main", ".gs_text"):
                try:
                    loc = new_frame.locator(sel).first
                    if not loc.count():
                        print(f"   {sel}: not present")
                        continue
                    txt = loc.inner_text().strip()
                    print(f"\n   --- {sel} ({len(txt)} chars) ---")
                    print("   " + txt[:1500].replace("\n", "\n   "))
                except Exception as exc:
                    print(f"   {sel}: error {str(exc)[:100]}")

        page.screenshot(path=str(PROJECT_ROOT / "logs" / "streaming.png"), full_page=False)
        ctx.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
