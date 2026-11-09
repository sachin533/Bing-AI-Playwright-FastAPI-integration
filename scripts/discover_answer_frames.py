"""Phase 2 helper: find where the Bing AI answer text actually lives.

The answer is rendered inside a nested frame / shadow root, so plain
``inner_text`` on the main document does not see it. This script enumerates
all frames and shadow roots and reports which one contains the answer.

Usage:
    py scripts/discover_answer_frames.py
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


def dump_frame(frame, label: str) -> None:
    try:
        info = frame.evaluate(
            """() => {
                const body = (document.body && document.body.innerText || '').trim();
                const iframes = Array.from(document.querySelectorAll('iframe'))
                    .map(f => ({id: f.id, cls: (f.className||'').toString().slice(0,60),
                                src: (f.src||'').slice(0,120), title: f.title,
                                w: Math.round(f.getBoundingClientRect().width),
                                h: Math.round(f.getBoundingClientRect().height)}));
                const shadows = [];
                for (const el of document.querySelectorAll('*')) {
                    if (el.shadowRoot) {
                        shadows.push({tag: el.tagName.toLowerCase(),
                                      id: el.id || null,
                                      cls: (el.className||'').toString().slice(0,60),
                                      textLen: (el.shadowRoot.innerText||'').trim().length});
                    }
                }
                const cand = [];
                for (const sel of ['#cplt_frame_2','#cplt_frame_1','.frame_cont','.ca_answer',
                                   '.ca_answer_body','[class*=answer]','[id*=answer]']) {
                    let nodes = [];
                    try { nodes = document.querySelectorAll(sel); } catch(e) { continue; }
                    for (const n of nodes) {
                        const r = n.getBoundingClientRect();
                        cand.push({sel, id: n.id||null, cls:(n.className||'').toString().slice(0,70),
                                   textLen: (n.innerText||'').trim().length,
                                   rect:[Math.round(r.x),Math.round(r.y),Math.round(r.width),Math.round(r.height)]});
                    }
                }
                return {url: location.href, bodyLen: body.length, body: body.slice(0, 1500),
                        iframes, shadows, cand};
            }"""
        )
    except Exception as exc:
        print(f"  [{label}] evaluate failed: {str(exc)[:160]}")
        return

    print(f"\n--- frame [{label}] url={info['url'][:110]}")
    print(f"    bodyLen={info['bodyLen']}")
    if info["iframes"]:
        print("    IFRAMES:")
        for f in info["iframes"]:
            print("      ", json.dumps(f, ensure_ascii=False))
    if info["shadows"]:
        print("    SHADOW ROOTS:")
        for s in info["shadows"]:
            print("      ", json.dumps(s, ensure_ascii=False))
    if info["cand"]:
        print("    CANDIDATES:")
        for c in info["cand"]:
            print("      ", json.dumps(c, ensure_ascii=False))
    if info["bodyLen"]:
        print("    BODY:")
        for line in info["body"].splitlines():
            if line.strip():
                print("      | " + line.strip()[:150])


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

        send = page.locator("button.b_copilot_send").first
        print(f"== send enabled: {send.is_enabled()}")
        send.click()
        print("== submitted; waiting for the answer ...")
        page.wait_for_timeout(args.wait * 1000)

        print(f"\n== url: {page.url}")
        dump_frame(page.main_frame, "main")

        for i, frame in enumerate(page.frames):
            if frame == page.main_frame:
                continue
            dump_frame(frame, f"child#{i} {frame.name or '(unnamed)'}")

        # Also try the last conversation turn specifically.
        print("\n== last .ca_turn ==")
        try:
            turn = page.locator("li.ca_turn").last
            print("   turn text:", json.dumps(turn.inner_text()[:600], ensure_ascii=False))
            for child in turn.query_selector_all("*")[:40]:
                pass
        except Exception as exc:
            print("   failed:", str(exc)[:160])

        page.screenshot(path=str(PROJECT_ROOT / "logs" / "answer_frames.png"), full_page=True)
        ctx.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
