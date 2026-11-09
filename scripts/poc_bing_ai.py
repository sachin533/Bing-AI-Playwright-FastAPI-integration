"""Phase 2 proof of concept - real Bing AI question and answer.

This script uses the *backend service* (the same code path the FastAPI
API uses), so it proves the production extraction logic works against the
real Bing AI page.

Usage:
    py scripts/poc_bing_ai.py
    py scripts/poc_bing_ai.py --question "What is Java programming?"
    py scripts/poc_bing_ai.py --question "..." --new-conversation
"""

from __future__ import annotations

import argparse
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

import asyncio  # noqa: E402

from app.services.bing_service import BingService  # noqa: E402
from app.services.browser_manager import BrowserManager  # noqa: E402
from app.utils.errors import BingAIError  # noqa: E402


async def _run(question: str, new_conversation: bool) -> int:
    manager = BrowserManager()
    service = BingService(manager)
    try:
        print("== starting the Playwright browser (persistent profile) ...")
        await manager.start()
        print(f"   browser running : {manager.is_running}")
        print(f"   current url     : {manager.current_url}")

        status = await service.status()
        print(f"   login required  : {status.get('login_required')}")
        print(f"   composer found  : {status.get('composer_found')}")

        print(f"\n== asking Bing AI: {question!r}")
        result = await service.ask(question, new_conversation=new_conversation)

        print("\n" + "=" * 78)
        print("=== REAL BING AI ANSWER ===")
        print(result.answer)
        print("=" * 78)
        print(f"[chars={len(result.answer)} elapsed={result.elapsed_ms}ms]")
        print(f"[conversation_id={result.conversation_id}]")
        return 0
    except BingAIError as exc:
        print(f"\n!! Bing AI error [{exc.code}]: {exc.message}")
        if exc.detail:
            print(f"   detail: {exc.detail}")
        return 2
    finally:
        print("\n== closing the browser ...")
        await manager.stop()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--question", default="What is Java programming?")
    ap.add_argument("--new-conversation", action="store_true")
    args = ap.parse_args()
    return asyncio.run(_run(args.question, args.new_conversation))


if __name__ == "__main__":
    sys.exit(main())
