"""End-to-end acceptance test against a RUNNING backend.

Usage:
    py scripts/acceptance_test.py
    py scripts/acceptance_test.py --base-url http://127.0.0.1:8000
"""

from __future__ import annotations

import argparse
import json
import sys
import time

import httpx

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:  # pragma: no cover
    pass


def _hr(title: str) -> None:
    print("\n" + "=" * 78)
    print(title)
    print("=" * 78)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base-url", default="http://127.0.0.1:8000")
    ap.add_argument("--question", default="What is Java programming?")
    ap.add_argument("--follow-up", default="Give me one sentence about Java.")
    ap.add_argument("--skip-browser", action="store_true")
    args = ap.parse_args()

    base = args.base_url.rstrip("/")
    failures: list[str] = []

    def check(name: str, ok: bool, detail: str = "") -> None:
        status = "PASS" if ok else "FAIL"
        print(f"[{status}] {name}" + (f" - {detail}" if detail else ""))
        if not ok:
            failures.append(name)

    with httpx.Client(timeout=300.0) as client:
        _hr("1. GET /health")
        r = client.get(f"{base}/health")
        check("GET /health -> 200", r.status_code == 200, f"status={r.status_code}")
        body = r.json()
        check("health status == ok", body.get("status") == "ok", str(body.get("status")))
        print(json.dumps(body, indent=2, ensure_ascii=False))

        _hr("2. GET /api/browser/status")
        r = client.get(f"{base}/api/browser/status")
        check("GET /api/browser/status -> 200", r.status_code == 200)
        status = r.json()
        for field in ("running", "page_open", "url", "login_required", "composer_found", "last_error"):
            check(f"status has field '{field}'", field in status)
        print(json.dumps(status, indent=2, ensure_ascii=False))

        if not args.skip_browser:
            _hr("3. POST /api/browser/start")
            r = client.post(f"{base}/api/browser/start")
            check("POST /api/browser/start -> 200", r.status_code == 200, r.text[:200])
            print(json.dumps(r.json(), indent=2, ensure_ascii=False))

        _hr("4. POST /v1/chat/completions (real Bing AI)")
        payload = {
            "model": "bing-ai",
            "messages": [{"role": "user", "content": args.question}],
            "stream": False,
        }
        started = time.time()
        r = client.post(f"{base}/v1/chat/completions", json=payload)
        elapsed = time.time() - started
        check("POST /v1/chat/completions -> 200", r.status_code == 200, r.text[:300])
        if r.status_code == 200:
            body = r.json()
            check("object == chat.completion", body.get("object") == "chat.completion")
            check("model == bing-ai", body.get("model") == "bing-ai")
            check("id starts with chatcmpl-bing-", str(body.get("id", "")).startswith("chatcmpl-bing-"))
            check("created is an int", isinstance(body.get("created"), int))
            choices = body.get("choices") or []
            check("exactly one choice", len(choices) == 1)
            if choices:
                c = choices[0]
                check("choice.index == 0", c.get("index") == 0)
                check("finish_reason == stop", c.get("finish_reason") == "stop")
                check("message.role == assistant", c.get("message", {}).get("role") == "assistant")
                content = c.get("message", {}).get("content", "")
                check("answer is non-empty", bool(content.strip()), f"{len(content)} chars")
                check("answer is not a mock", "MOCK" not in content.upper())
                low = content.lower()
                check(
                    "answer is topical",
                    any(w in low for w in ("java", "programming", "jvm", "class", "bytecode")),
                    content[:160].replace("\n", " "),
                )
                check("answer keeps its line breaks", content.count("\n") >= 3, f"{content.count(chr(10))} newlines")
                print("\n--- REAL ANSWER FROM THE API ---")
                print(content)
                print("--- END ---")
            check("usage block present", "usage" in body)
            print(f"\n[elapsed {elapsed:.1f}s]")

        _hr("5. Follow-up question (conversation continuity)")
        payload2 = {
            "model": "bing-ai",
            "messages": [{"role": "user", "content": args.follow_up}],
            "stream": False,
        }
        r = client.post(f"{base}/v1/chat/completions", json=payload2)
        check("follow-up -> 200", r.status_code == 200, r.text[:300])
        if r.status_code == 200:
            content = r.json()["choices"][0]["message"]["content"]
            check("follow-up answer non-empty", bool(content.strip()), f"{len(content)} chars")
            check("follow-up answer not a mock", "MOCK" not in content.upper())
            print(content[:400])

        _hr("6. Validation / error handling")
        r = client.post(
            f"{base}/v1/chat/completions",
            json={"model": "bing-ai", "messages": [{"role": "system", "content": "x"}]},
        )
        check("no user message -> 422", r.status_code == 422, f"status={r.status_code}")

        r = client.post(
            f"{base}/v1/chat/completions",
            json={"model": "bing-ai", "messages": [{"role": "user", "content": "hi"}], "stream": True},
        )
        check("stream=true -> 501", r.status_code == 501, f"status={r.status_code}")

        r = client.get(f"{base}/openapi.json")
        check("GET /openapi.json -> 200", r.status_code == 200)
        paths = r.json().get("paths", {})
        for p in ("/health", "/api/browser/status", "/api/browser/start", "/api/browser/stop",
                  "/v1/chat/completions"):
            check(f"openapi contains {p}", p in paths)

        r = client.get(f"{base}/docs")
        check("GET /docs -> 200 (Swagger UI)", r.status_code == 200)

        if not args.skip_browser:
            _hr("7. POST /api/browser/stop")
            r = client.post(f"{base}/api/browser/stop")
            check("POST /api/browser/stop -> 200", r.status_code == 200)
            print(json.dumps(r.json(), indent=2, ensure_ascii=False))
            r = client.get(f"{base}/api/browser/status")
            check("browser stopped", r.json().get("running") is False)

    _hr("RESULT")
    if failures:
        print(f"{len(failures)} CHECK(S) FAILED:")
        for f in failures:
            print("   -", f)
        return 1
    print("ALL CHECKS PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
