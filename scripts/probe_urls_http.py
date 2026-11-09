"""Phase 2 helper: HTTP-level redirect probe (no browser).

Shows the full redirect chain for candidate chat URLs so we can tell which
entry points still work anonymously vs. which bounce to Microsoft login.

Usage:
    py scripts/probe_urls_http.py
"""

from __future__ import annotations

import sys

import httpx

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:  # pragma: no cover
    pass

UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/140.0.0.0 Safari/537.36 Edg/140.0.0.0"
)

URLS = [
    "https://www.bing.com/chat",
    "https://www.bing.com/chat?q=hello&form=QBLH",
    "https://www.bing.com/talkcopilot",
    "https://www.bing.com/new/chat",
    "https://www.bing.com/search?q=hello&showconv=1&FORM=QBLH",
    "https://cn.bing.com/chat",
    "https://www.bing.com/chat/unsafe",
    "https://copilot.microsoft.com/en-us/chat",
    "https://www.bing.com/images/chat",
    "https://www.bing.com/copilotchat?form=ML",
]


def main() -> int:
    with httpx.Client(
        follow_redirects=False, timeout=25.0, headers={"User-Agent": UA}
    ) as client:
        for url in URLS:
            print("\n" + "=" * 78)
            print(f"### {url}")
            current = url
            for hop in range(8):
                try:
                    r = client.get(current)
                except Exception as exc:
                    print(f"  [{hop}] ERROR {type(exc).__name__}: {exc}")
                    break
                loc = r.headers.get("location")
                status = r.status_code
                print(f"  [{hop}] {status}  {current}")
                if not loc:
                    body = r.text[:200].replace("\n", " ")
                    print(f"        body: {body!r}")
                    break
                current = httpx.URL(current).join(loc).__str__()
    return 0


if __name__ == "__main__":
    sys.exit(main())
