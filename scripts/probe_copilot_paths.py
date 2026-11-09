"""Phase 2 helper: probe copilot.com app paths for the post-login chat route."""

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

PATHS = [
    "https://copilot.com/",
    "https://copilot.com/chat",
    "https://copilot.com/landingv2",
    "https://copilot.com/copilotchat",
    "https://copilot.com/consumer",
    "https://copilot.com/",
    "https://www.bing.com/talk",
    "https://www.bing.com/chat?FORM=IQFRML",
    "https://www.bing.com/search?q=hello&ensearch=1&FORM=QBRE",
]


def main() -> int:
    with httpx.Client(
        follow_redirects=False, timeout=25.0, headers={"User-Agent": UA}
    ) as client:
        for url in PATHS:
            print("\n" + "=" * 78)
            print(f"### {url}")
            current = url
            for hop in range(6):
                try:
                    r = client.get(current)
                except Exception as exc:
                    print(f"  [{hop}] ERROR {type(exc).__name__}: {exc}")
                    break
                loc = r.headers.get("location")
                print(f"  [{hop}] {r.status_code}  {current}")
                if not loc:
                    low = r.text.lower()
                    has_input = any(
                        k in low
                        for k in ("textarea", "contenteditable", "b_sde", "prompt-text")
                    )
                    print(f"        input-ish markers in html: {has_input}")
                    break
                current = httpx.URL(current).join(loc).__str__()
    return 0


if __name__ == "__main__":
    sys.exit(main())
