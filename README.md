# Bing AI Playwright Integration (FastAPI, no Chrome extension)

A self-contained project that exposes **Microsoft Bing "AI MODE"** (the Copilot
Search web interface) through an **OpenAI-compatible REST API**, using
**Playwright** browser automation and a **FastAPI** backend.

> **No Chrome extension is required.** There is no extension, no extension
> WebSocket channel and no browser-extension messaging anywhere in this
> codebase. Playwright drives a real Chromium browser directly.

---

## 1. Project overview

```
User / Frontend
      |
      v
FastAPI Backend  (backend/app)
      |
      v
Playwright Browser Automation  (backend/app/services/browser_manager.py)
      |
      v
Bing AI Web Interface  (https://www.bing.com/copilotsearch)
      |
      v
Extract AI Response  (backend/app/services/bing_service.py)
      |
      v
FastAPI Backend
      |
      v
Return Response to Client  (OpenAI-compatible JSON)
```

The browser is launched **once** with a **persistent user profile** stored in
`browser_data/` inside the project. Every API request reuses that browser and
that single chat page - a new browser is never launched per question.

---

## 2. Important discovery: which Bing URL is the AI interface?

Bing Chat was retired and its URLs now redirect to Microsoft Copilot, which
**requires a Microsoft account sign-in**:

| URL | Result (verified) |
|---|---|
| `https://www.bing.com/chat` | 302 -> `copilot.microsoft.com` -> 301 -> `copilot.com/` (marketing landing page, no composer) |
| `https://copilot.com/chat` | 302 -> `login.microsoftonline.com` (sign-in required) |
| `https://www.bing.com/copilotsearch?q=...&FORM=CSSCOP` | **Works - the Bing "AI MODE" interface, no sign-in required** |

The working entry point is the **AI MODE** scope of Bing Search:

```
https://www.bing.com/copilotsearch?q=what+is+java&FORM=CSSCOP
```

It is reachable from the Bing search page via the **"AI MODE"** tab
(`https://www.bing.com/copilotsearch?q=<query>&FORM=CSSCOP`).

> The marketing landing page of `copilot.com` still shows a "Sign in" button
> in the header. The service therefore only reports `login_required = true`
> when the *page itself* is an authentication wall **and** no composer is
> present - so the normal AI MODE page is never mis-flagged.

### Verified page structure

All selectors below were discovered by inspecting the live DOM
(`scripts/probe_*.py`), not guessed:

| Purpose | Selector |
|---|---|
| Question composer | `textarea[id^='b_copilot_composer']` |
| Send button | `button.b_copilot_send` (aria-label `Send`) |
| New chat button | `#cs_leftside_panel_newsearch` (aria-label `New chat`) |
| Conversation turn | `li.ca_turn` |
| User question inside a turn | `.ca_userquery_text` |
| Answer iframe | iframe whose URL contains `cpltsrchif=1` (param `turnindex`) |
| Answer prose | `.gs_text` (fallbacks: `.gs_multianshead_main`, `.answer_container`) |
| Citation chip (removed) | `.gs_sup_cit` |
| "N Sources" row (removed) | `li.gs_cit_stry_item`, `.gs_cit_stry_preview_txt` |
| "View all" link (removed) | `.gs_sm_cit` |
| Still generating | `.b_ts_search_stage`, `.b_ts_sum_stage`, `.b_ts_csronly` |
| **Content bullet list (KEPT)** | `ul.gs_cit_stry_pre` / `ol.gs_cit_stry_pre` |

Two hard-won details are encoded in the code:

1. The composer is a **React controlled component**. `locator.fill()` does
   **not** update its internal state, so the send button stays `disabled`.
   The question must be typed with real key events
   (`press_sequentially`).
2. Bing uses the class `gs_cit_stry_pre` for the **content bullet lists**
   *and* for citation blocks. Only the citation nodes listed above are
   stripped, otherwise the bullet lists would disappear from the answer.

---

## 3. Technology stack

| Layer | Technology |
|---|---|
| Language | Python 3.12.8 |
| Backend | FastAPI 0.141 + Uvicorn 0.53 |
| Automation | Playwright 1.64.1 (Python, async API) |
| Browser | Playwright Chromium (persistent profile) |
| Validation | Pydantic 2.13 |
| HTTP client | HTTPX 0.28 |
| Tests | pytest 9.1 + pytest-asyncio 1.4 |
| API format | OpenAI-compatible `chat.completion` |

---

## 4. Installation (Windows)

All commands use `py` (the `python` command on this machine is the Microsoft
Store alias and does not work).

### 4.1 Virtual environment (optional but recommended)

```powershell
cd "E:\CyberF\Day9\Bing AI Playwright"
py -m venv .venv
.venv\Scripts\activate
```

If you activate the venv, `py` still works and picks up the venv
interpreter when it is active. Without the venv the globally installed
packages are used (they were already present on this machine).

### 4.2 Python dependencies

```powershell
py -m pip install fastapi uvicorn playwright pydantic httpx pytest pytest-asyncio
```

Or from the pinned file:

```powershell
py -m pip install -r backend\requirements.txt
```

### 4.3 Playwright Chromium

```powershell
py -m playwright install chromium
```

Chromium was already installed on this machine
(`%LOCALAPPDATA%\ms-playwright\chromium-1248`).

### 4.4 Configuration

```powershell
copy backend\.env.example backend\.env
```

`backend/.env` is git-ignored. Every value can also be supplied as a plain
environment variable.

---

## 5. Running the project

### 5.1 Start the backend

```powershell
cd "E:\CyberF\Day9\Bing AI Playwright"
py -m uvicorn app.main:app --host 127.0.0.1 --port 8001 --app-dir backend
```

- Swagger UI: <http://127.0.0.1:8001/docs>
- OpenAPI schema: <http://127.0.0.1:8001/openapi.json>
- Health: <http://127.0.0.1:8001/health>

> **Port 8001** is the default in `backend/.env` so this backend can run
> next to the Google AI Mode backend, which uses port 8000.  Set `PORT=8000`
> in `backend/.env` if you want the original port.

### 5.2 Start the browser and open Bing AI

```powershell
Invoke-RestMethod -Method Post -Uri "http://127.0.0.1:8000/api/browser/start"
```

A visible Chromium window opens on the Bing AI MODE page. The profile lives
in `browser_data/` and is reused on every start.

### 5.3 Signing in manually (only if it is ever required)

The AI MODE scope of Bing Search currently works **without** a Microsoft
account. If Bing ever shows an authentication wall:

1. The browser window is already open - switch to it.
2. Complete the Microsoft sign-in manually in that window.
3. The persistent profile keeps the session for all future runs.
4. Call `GET /api/browser/status`; `login_required` turns `false`.

This project **never** bypasses a login, a CAPTCHA or any other access
control. If a sign-in is required, it must be completed by a human.

### 5.4 Ask a question

```powershell
$body = @{
  model = "bing-ai"
  messages = @(@{ role = "user"; content = "What is Java programming?" })
  stream = $false
} | ConvertTo-Json -Depth 5

Invoke-RestMethod -Method Post `
  -Uri "http://127.0.0.1:8000/v1/chat/completions" `
  -ContentType "application/json" -Body $body
```

### 5.5 Standalone proof-of-concept (no backend needed)

```powershell
py scripts\poc_bing_ai.py
py scripts\poc_bing_ai.py --question "What is the capital of the Maldives?"
```

The script uses the very same service code as the API and prints the real
answer in the terminal.

### 5.6 Full acceptance script against a running backend

```powershell
py scripts\acceptance_test.py
```

---

## 6. API endpoints

| Method | Path | Description |
|---|---|---|
| `GET` | `/health` | Backend health, uptime, configured Bing URL |
| `GET` | `/health/ready` | Ready when the browser runs and the page is open |
| `GET` | `/api/browser/status` | Browser running, page open, login status, last error |
| `POST` | `/api/browser/start` | Launch Chromium (persistent profile) and open Bing AI |
| `POST` | `/api/browser/stop` | Close the browser gracefully |
| `POST` | `/api/browser/reload` | Re-navigate to the Bing AI URL |
| `GET` | `/v1/models` | OpenAI-compatible model list (`bing-ai`) |
| `POST` | `/v1/chat/completions` | Ask Bing AI, get an OpenAI-compatible answer |
| `POST` | `/api/ask` | Convenience wrapper returning the raw answer payload |

### `GET /api/browser/status` - response

```json
{
  "running": true,
  "page_open": true,
  "url": "https://www.bing.com/copilotsearch?q=what+is+java&FORM=CSSCOP",
  "login_required": false,
  "composer_found": true,
  "last_error": null,
  "bing_ai_url": "https://www.bing.com/copilotsearch?q=what+is+java&FORM=CSSCOP"
}
```

No cookies, tokens or profile contents are ever returned.

### `POST /v1/chat/completions` - request

```json
{
  "model": "bing-ai",
  "messages": [
    { "role": "user", "content": "What is Java?" }
  ],
  "stream": false
}
```

### `POST /v1/chat/completions` - response (real output, trimmed)

```json
{
  "id": "chatcmpl-bing-0a5751d2d48c437f86131d0a",
  "object": "chat.completion",
  "created": 1794206949,
  "model": "bing-ai",
  "choices": [
    {
      "index": 0,
      "message": {
        "role": "assistant",
        "content": "✅ What Java Is\nJava is a high-level, object-oriented programming language ..."
      },
      "finish_reason": "stop"
    }
  ],
  "usage": { "prompt_tokens": 6, "completion_tokens": 514, "total_tokens": 521 }
}
```

The `content` field always contains the **real** text extracted from the live
Bing AI page. Nothing is hardcoded or simulated.

---

## 7. Conversation handling

Bing AI MODE keeps the conversation **in the page**:

- Every submitted question appends a new `li.ca_turn` to the page.
- Each turn owns an iframe carrying its own answer.
- The service records the turn count **before** submitting and then picks the
  answer iframe whose `turnindex` is newer - so a follow-up question always
  returns its own answer and never the previous one.
- The Bing conversation id is exposed as `conversation_id` in the
  `/api/ask` payload.
- `new_conversation=True` clicks the "New chat" control (`#cs_leftside_panel_newsearch`)
  before submitting.

Duplicate submissions are prevented by holding an `asyncio.Lock` for the whole
submit/extract cycle, so two concurrent requests can never fight over the
same composer.

> Conversation context lives in the browser page, not on the server. If the
> page is reloaded or the "New chat" button is used, the context is lost -
> the service always answers with the newest turn.

---

## 8. Error handling

| Situation | HTTP | `error.code` |
|---|---|---|
| Browser not started | 503 | `browser_not_running` |
| Chromium failed to launch | 500 | `browser_startup_failed` |
| Browser / page closed unexpectedly | 503 | `browser_disconnected` |
| Page did not load | 502 | `navigation_failed` |
| Microsoft sign-in required | 401 | `login_required` |
| Session expired | 401 | `session_expired` |
| Composer not found | 502 | `input_not_found` |
| Send button not usable | 502 | `submit_not_found` |
| Answer did not arrive in time | 504 | `response_timeout` |
| Answer empty | 502 | `empty_response` |
| Layout changed | 502 | `unexpected_layout` |
| Request without a user message | 422 | - |
| `stream: true` | 501 | `streaming_not_supported` |
| Request exceeded `API_REQUEST_TIMEOUT_S` | 504 | `request_timeout` |

Error body shape:

```json
{ "detail": { "code": "response_timeout", "message": "Timed out waiting for Bing AI to finish generating the answer." } }
```

---

## 9. Tests

### 9.1 Unit tests (mocked - no network, no browser)

```powershell
py -m pytest backend\tests -q
```

These never open a browser. A mocked answer is always prefixed with
`MOCKED` and **must never be counted as proof that the real integration
works**.

### 9.2 Integration tests (real Chromium + real Bing AI)

```powershell
set RUN_INTEGRATION_TESTS=1
py -m pytest backend\tests\integration -v -s
```

Without the environment variable the integration tests are skipped, so the
default test run stays offline.

---

## 10. Manual acceptance checklist

Work through this list after a fresh clone.

| # | Step | Command / Action | Expected result | Verified |
|---|---|---|---|---|
| 1 | Install deps | `py -m pip install -r backend\requirements.txt` | No errors | ✅ |
| 2 | Install Chromium | `py -m playwright install chromium` | Chromium present | ✅ |
| 3 | Create config | `copy backend\.env.example backend\.env` | `backend/.env` exists | ✅ |
| 4 | Start backend | `py -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --app-dir backend` | Server on :8000 | ✅ |
| 5 | Health check | `GET /health` | `status == "ok"` | ✅ |
| 6 | Swagger UI | Open <http://127.0.0.1:8000/docs> | Interactive docs | ✅ |
| 7 | Browser status | `GET /api/browser/status` | `running == false` | ✅ |
| 8 | Start browser | `POST /api/browser/start` | Chromium window opens on Bing AI | ✅ |
| 9 | Status again | `GET /api/browser/status` | `running/page_open == true`, `composer_found == true` | ✅ |
| 10 | Ask a question | `POST /v1/chat/completions` | Real answer text, `finish_reason == "stop"` | ✅ |
| 11 | Answer is genuine | Inspect the content | Contains real prose about the topic, headings, bullet lists | ✅ |
| 12 | Follow-up question | Send a second question | A **new** answer, not a repeat of the first | ✅ |
| 13 | Conversation context | `py scripts\verify_conversation.py` | Bing replies *"You previously said: 'My favourite colour is turquoise.'"* | ✅ |
| 14 | Standalone POC | `py scripts\poc_bing_ai.py` | Real answer printed in the terminal | ✅ |
| 15 | Unit tests | `py -m pytest backend\tests -q` | All pass | ✅ |
| 16 | Integration tests | `set RUN_INTEGRATION_TESTS=1` + `py -m pytest backend\tests\integration -v -s` | All pass against the real page | ✅ |
| 17 | Stop browser | `POST /api/browser/stop` | `running == false`, Chromium closed | ✅ |
| 18 | Persistence | Stop, restart, ask again | Same session, no new browser per question | ✅ |
| 19 | No extension | Inspect the repo | No `manifest.json`, no extension code, no `chrome-extension://` URL | ✅ |
| 20 | Security | Inspect `.gitignore` | `browser_data/`, `.venv/`, `.env` are ignored | ✅ |
| 21 | No secrets in API | Inspect `/api/browser/status` and logs | No cookies, tokens or profile contents | ✅ |

---

## 11. Project structure

```
Bing AI Playwright/
├── backend/
│   ├── app/
│   │   ├── main.py                  # FastAPI app, CORS, lifespan, error handler
│   │   ├── config.py                # Settings from env / .env
│   │   ├── api/
│   │   │   ├── health.py            # /health, /health/ready
│   │   │   └── routes.py            # browser control + chat completions
│   │   ├── services/
│   │   │   ├── browser_manager.py   # Playwright lifecycle, persistent profile, lock
│   │   │   └── bing_service.py      # Bing AI interaction + answer extraction
│   │   ├── schemas/
│   │   │   ├── browser.py           # Browser status/action models
│   │   │   └── chat.py              # OpenAI-compatible models
│   │   └── utils/
│   │       ├── errors.py            # Typed exceptions -> HTTP status codes
│   │       └── logging_config.py    # Logging + secret redaction
│   ├── tests/
│   │   ├── conftest.py              # Fixtures (mocked manager / mocked service)
│   │   ├── test_health.py
│   │   ├── test_chat.py
│   │   ├── test_browser_manager.py
│   │   ├── test_error_handling.py
│   │   ├── test_conversation.py
│   │   └── integration/
│   │       └── test_bing_integration.py   # REAL browser tests
│   ├── requirements.txt
│   └── .env.example
├── scripts/
│   ├── poc_bing_ai.py               # Real question/answer proof of concept
│   ├── acceptance_test.py           # End-to-end API acceptance run
│   ├── verify_conversation.py       # Conversation context + profile persistence
│   ├── inspect_bing_dom.py          # DOM inspection helper
│   ├── probe_urls.py / probe_urls_http.py
│   ├── probe_bing_search_ai.py
│   ├── probe_bing_ai_mode.py        # Finds the AI MODE entry point
│   ├── discover_answer_dom.py
│   ├── discover_answer_frames.py    # Finds the answer iframe
│   ├── probe_answer_structure.py
│   ├── probe_answer_hierarchy.py
│   ├── probe_candidates.py
│   ├── probe_lists.py               # Tells bullet lists from citation lists
│   ├── probe_citations.py
│   ├── probe_anchors.py
│   ├── probe_streaming.py
│   └── probe_extraction_v2.py       # Reference extraction algorithm
├── browser_data/                    # Persistent Chromium profile  (git-ignored)
├── logs/                            # Screenshots + logs              (git-ignored)
├── pytest.ini
├── .gitignore
├── README.md
└── test_bing.py                     # Original pre-existing script (kept as-is)
```

---

## 12. Security

- `browser_data/` (cookies, session data) is git-ignored and must never be
  committed.
- `.env` is git-ignored; `backend/.env.example` documents every setting.
- The API never returns cookies, tokens, `storage_state` or profile files.
- The logging filter scrubs messages that mention cookie / token / password
  keywords.
- CORS is restricted to the origins in `CORS_ORIGINS`
  (default `http://localhost:3000`, `http://localhost:5173`).
- Request payloads are validated by Pydantic (message list must be non-empty
  and contain a `user` message, content must not be blank).
- Every chat request is bounded by `API_REQUEST_TIMEOUT_S` (default 180 s).
- No login, CAPTCHA or anti-bot protection is bypassed - a sign-in wall is
  reported as `login_required` and must be completed by a human.

---

## 13. Troubleshooting

| Symptom | Cause / fix |
|---|---|
| `browser_not_running` (503) | Call `POST /api/browser/start` first. |
| The Chromium window does not open | Check `logs/`; `browser_data` may be locked by another Chromium using the same profile - close it. |
| `login_required` (401) | Bing demands a Microsoft sign-in. Complete it manually in the open window; the profile keeps it. |
| `input_not_found` (502) | Bing changed the composer. Re-run `py scripts\inspect_bing_dom.py` and update `INPUT_SELECTORS` in `backend/app/services/bing_service.py`. |
| `response_timeout` (504) | The answer did not arrive within `ANSWER_TIMEOUT_MS` (default 120 s). Raise it in `backend/.env`. |
| `unexpected_layout` (502) | The answer iframe or container moved. Re-run `py scripts\probe_lists.py` / `probe_answer_hierarchy.py` and update `ANSWER_SELECTORS`. |
| The answer lost its bullet lists | Do **not** add `ul.gs_cit_stry_pre` to `BING_CITATION_SELECTORS` - that class is used for real content lists. |
| Console shows `UnicodeEncodeError` (cp1252) | Use `py` from a UTF-8 terminal, or `chcp 65001`. The scripts already reconfigure stdout to UTF-8. |
| `pytest` complains about an async fixture | `pytest.ini` pins `asyncio_default_fixture_loop_scope` / `asyncio_default_test_loop_scope` to `session` - Playwright objects are bound to the loop that created them. |
| The answer repeats the previous question | The follow-up answer was read from the wrong turn. Check `scripts/probe_extraction_v2.py` against the live DOM. |

---

## 14. Known limitations

1. **Streaming is not implemented.** `stream: true` returns `501`. The
   extraction needs the complete answer to detect the end of generation, so a
   token stream would require a different completion signal.
2. **One question at a time.** The service serialises requests through a
   single page and a single lock, so concurrent calls queue up instead of
   running in parallel.
3. **The answer is read from the DOM.** Bing can change its markup; the
   selectors live in one place (`bing_service.py`) and can be overridden with
   the `BING_*_SELECTORS` environment variables.
4. **Conversation context lives in the page.** Reloading the page or using
   "New chat" clears it.
5. **The public Bing AI MODE interface is undocumented.** There is no
   supported API, so the integration depends on the live web UI.
6. **The answer text is cleaned.** Citation chips ("Wikipedia", "+1",
   "3 Sources") are removed from the extracted answer.
7. **Rate limiting / anti-bot protection** is not bypassed. If Microsoft
   throttles or challenges the session, the request fails with a clear error
   instead of trying to work around it.
8. **`/v1/models` lists only `bing-ai`.**
9. **No API key is enforced by default.** `API_KEY` in `backend/.env` is
   reserved for a future authenticated mode; CORS is the current guard.

---

## 15. Answer to the mentor's question

**Is a Chrome extension necessary? No.**

Playwright controls the browser directly: it launches Chromium, navigates to
the Bing AI MODE page, types into the real composer, clicks the real send
button and reads the real answer out of the live DOM. No extension is
installed, no extension messaging (`chrome.runtime.sendMessage`) is used and
no `chrome-extension://` URL appears anywhere in the project. The persistent
profile in `browser_data/` replaces the main benefit an extension would have
provided (a reusable signed-in session).

---

## 16. Using this backend from the shared playground

This backend is the **Bing** provider of the multi-provider playground in
`E:\CyberF\Day 8\Google Gemini\frontend`. The two backends stay completely
independent - the frontend only chooses which one to talk to.

```powershell
# 1) this backend on port 8001
cd "E:\CyberF\Day9\Bing AI Playwright"
py -m uvicorn app.main:app --host 127.0.0.1 --port 8001 --app-dir backend

# 2) start the browser once
Invoke-RestMethod -Method Post -Uri "http://127.0.0.1:8001/api/browser/start"

# 3) the playground
cd "E:\CyberF\Day 8\Google Gemini\frontend"
npm run dev
```

The frontend reads the URL from `VITE_BING_API_BASE_URL`
(default `http://127.0.0.1:8001`). CORS is configured in `backend/.env`:

```ini
CORS_ORIGINS=http://localhost:3000,http://localhost:5173,http://127.0.0.1:3000,http://127.0.0.1:5173
```

The endpoints the playground uses:

| Endpoint | Purpose |
|---|---|
| `GET /health` | Backend liveness |
| `GET /api/browser/status` | Browser / page / sign-in state |
| `POST /api/browser/start` | Launch the visible Chromium window |
| `POST /v1/chat/completions` | The real Bing AI answer (non streaming) |
