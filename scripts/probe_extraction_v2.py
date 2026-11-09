"""Phase 2 helper: the definitive answer-extraction algorithm.

This is the reference implementation that the backend service mirrors:

  1. remember how many conversation turns exist before submitting;
  2. submit the question;
  3. wait for a NEW turn to appear;
  4. find the answer iframe of that new turn (highest ``turnindex``);
  5. wait until the real answer container (``.gs_multianshead_main`` /
     ``.gs_text``) exists - while it does not, Bing shows the transient
     "Searching for ..." / "Summarizing results" placeholder;
  6. wait until the answer text stops growing AND the generation
     indicators are gone;
  7. extract the answer.

Usage:
    py scripts/probe_extraction_v2.py
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

# Selectors whose presence indicates that Bing is still generating.
GENERATING_SELECTORS = [
    ".b_ts_search_stage",
    ".b_ts_sum_stage",
    ".b_ts_csronly",
    ".b_ts_exp_content",
]

# The real answer containers (checked inside the answer iframe).
ANSWER_SELECTORS = [
    ".gs_text",
    ".gs_multianshead_main",
    ".answer_container",
]


def _turn_index(url: str) -> int:
    q = urllib.parse.parse_qs(urllib.parse.urlparse(url).query)
    try:
        return int(q.get("turnindex", ["0"])[0])
    except ValueError:
        return 0


def pick_answer_frame(page, turns_before: int):
    frames = [f for f in page.frames if "cpltsrchif=1" in (f.url or "")]
    frames.sort(key=lambda f: _turn_index(f.url or ""))
    for f in frames:
        if _turn_index(f.url or "") > turns_before:
            return f
    return frames[-1] if frames else None


def is_generating(frame) -> bool:
    try:
        for sel in GENERATING_SELECTORS:
            loc = frame.locator(sel).first
            if loc.count():
                txt = (loc.inner_text() or "").strip()
                if txt:
                    return True
    except Exception:
        return False
    return False


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--question",
        default="In one short paragraph, what is the capital of the Maldives and what is it famous for?",
    )
    ap.add_argument("--timeout", type=int, default=90)
    ap.add_argument("--settle", type=float, default=2.0, help="seconds of stable text required")
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

        # --- phase A: wait for the new turn + a real answer container -------
        frame = None
        answer_loc = None
        deadline = args.timeout
        waited = 0.0
        while waited < deadline:
            page.wait_for_timeout(500)
            waited += 0.5
            frame = pick_answer_frame(page, turns_before)
            if frame is None:
                continue
            for sel in ANSWER_SELECTORS:
                try:
                    loc = frame.locator(sel).first
                    if loc.count() and (loc.inner_text() or "").strip():
                        answer_loc = loc
                        print(
                            f"== real answer container appeared after {waited:.1f}s "
                            f"({sel})"
                        )
                        break
                except Exception:
                    continue
            if answer_loc is not None:
                break

        if answer_loc is None:
            print("!! answer container never appeared")
            page.screenshot(path=str(PROJECT_ROOT / "logs" / "v2_timeout.png"))
            ctx.close()
            return 1

        # --- phase B: wait for the text to settle --------------------------
        last = ""
        stable_since = None
        waited = 0.0
        while waited < deadline:
            page.wait_for_timeout(500)
            waited += 0.5
            try:
                current = answer_loc.inner_text() or ""
            except Exception:
                break
            generating = is_generating(frame)
            if current != last:
                last = current
                stable_since = None
                print(f"   t={waited:5.1f}s len={len(current):>5} generating={generating}")
            elif stable_since is None:
                stable_since = waited
            else:
                if (waited - stable_since) >= args.settle and not generating:
                    print(f"   t={waited:5.1f}s STABLE len={len(current)}")
                    last = current
                    break
                if generating:
                    stable_since = None

        print("\n" + "=" * 78)
        print("=== FINAL ANSWER ===")
        print(last.strip())
        print("=" * 78)
        print(f"[chars={len(last.strip())}]")

        page.screenshot(path=str(PROJECT_ROOT / "logs" / "v2_answer.png"), full_page=False)
        ctx.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
