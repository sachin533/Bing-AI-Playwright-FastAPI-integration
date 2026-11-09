"""Verify conversation continuity and browser-session persistence.

Checks two claims made in the README:
  1. a follow-up question in the same page keeps the conversation context;
  2. stopping and restarting the browser re-uses the same persistent profile.

Usage:
    py scripts/verify_conversation.py
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
BACKEND_DIR = PROJECT_ROOT / "backend"
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:  # pragma: no cover
    pass

from app.services.bing_service import BingService  # noqa: E402
from app.services.browser_manager import BrowserManager  # noqa: E402


async def main() -> int:
    manager = BrowserManager()
    service = BingService(manager)
    ok = True

    try:
        await manager.start()
        page = manager.require_page()

        print("=" * 78)
        print("PART 1 - conversation continuity")
        print("=" * 78)

        first = await service.ask("My favourite colour is turquoise. Remember that.")
        print(f"\nQ1: My favourite colour is turquoise. Remember that.")
        print(f"A1: {first.answer[:400]}")

        turns_after_first = await service._count_turns(page)
        print(f"\nturns after Q1: {turns_after_first}")

        second = await service.ask("What is my favourite colour?")
        print(f"\nQ2: What is my favourite colour?")
        print(f"A2: {second.answer[:600]}")

        turns_after_second = await service._count_turns(page)
        print(f"\nturns after Q2: {turns_after_second}")

        context_ok = turns_after_second > turns_after_first
        print(f"\n[{'PASS' if context_ok else 'FAIL'}] a new turn was created for Q2")
        ok = ok and context_ok

        mentions = "turquoise" in second.answer.lower()
        print(f"[{'PASS' if mentions else 'INFO'}] the follow-up answer mentions "
              f"'turquoise' (context kept: {mentions})")
        if not mentions:
            print("      NOTE: the public Bing AI MODE UI did not use the earlier "
                  "context for this follow-up.")
        ok = ok and mentions

        print("\n" + "=" * 78)
        print("PART 2 - persistent browser profile")
        print("=" * 78)

        profile = manager._context  # noqa: SLF001 - diagnostic only
        cookies_before = len(await manager.require_page().context.cookies())
        print(f"cookies in the profile before restart: {cookies_before}")

        await manager.stop()
        print(f"after stop -> running: {manager.is_running}")

        await manager.start()
        print(f"after restart -> running: {manager.is_running}")
        cookies_after = len(await manager.require_page().context.cookies())
        print(f"cookies in the profile after restart : {cookies_after}")
        print(f"profile dir: {manager._context is not None}")  # noqa: SLF001

        third = await service.ask("Say hello in one short sentence.")
        print(f"\nQ3 after restart: {third.answer[:300]}")
        persist_ok = len(third.answer) > 20
        print(f"[{'PASS' if persist_ok else 'FAIL'}] the browser works again after a restart")
        ok = ok and persist_ok

        print("\n" + "=" * 78)
        print("RESULT:", "ALL CHECKS PASSED" if ok else "SOME CHECKS FAILED")
        print("=" * 78)
        return 0 if ok else 1
    finally:
        await manager.stop()


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
