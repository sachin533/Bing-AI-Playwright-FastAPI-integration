"""Bing AI interaction service.

Drives the real Bing "AI MODE" (Copilot Search) web interface through
Playwright and extracts the assistant answer.

Everything in this module was derived by inspecting the live page
(``scripts/probe_*.py``), not guessed:

* the composer is ``textarea[id^='b_copilot_composer']``;
* the send button is ``button.b_copilot_send`` (it is a React controlled
  component, so the question must be typed with real key events - using
  ``.fill()`` leaves the button disabled);
* every question creates a new conversation turn ``li.ca_turn`` whose
  answer is rendered inside an **iframe** (``cpltsrchif=1``) that contains
  ``#copans_container > li.b_ans > .answer_container``;
* the generated prose lives in ``.gs_text``; the citation blocks
  ``ul.gs_cit_stry_pre`` are interleaved between the paragraphs and are
  removed before the text is returned;
* while Bing is still working it shows the transient "Searching for ..."
  / "Summarizing results" blocks (``.b_ts_search_stage``,
  ``.b_ts_sum_stage``, ``.b_ts_csronly``) instead of the answer.

Response-completion detection therefore combines two independent signals:
the answer container has to exist *and* its text has to stay unchanged for
a configurable period while no generation indicator is active.
"""

from __future__ import annotations

import asyncio
import os
import re
import urllib.parse
from dataclasses import dataclass, field
from typing import Any

from playwright.async_api import (
    Error as PlaywrightError,
    Frame,
    Locator,
    Page,
    TimeoutError as PlaywrightTimeoutError,
)

from ..config import settings
from ..utils.errors import (
    BrowserDisconnectedError,
    EmptyResponseError,
    InputNotFoundError,
    LoginRequiredError,
    ResponseTimeoutError,
    SubmitNotFoundError,
    UnexpectedLayoutError,
)
from ..utils.logging_config import get_logger
from .browser_manager import BrowserManager, browser_manager

logger = get_logger(__name__)


def _env_selectors(name: str, default: list[str]) -> list[str]:
    raw = os.getenv(name)
    if not raw:
        return list(default)
    items = [s.strip() for s in raw.split("|") if s.strip()]
    return items or list(default)


# ---------------------------------------------------------------------------
# Selectors (verified against the live DOM, overridable via env vars)
# ---------------------------------------------------------------------------
INPUT_SELECTORS = _env_selectors(
    "BING_INPUT_SELECTORS",
    [
        "textarea[id^='b_copilot_composer']",
        "textarea.b_copilot_composer",
        "textarea[placeholder*='Ask']",
    ],
)

SUBMIT_SELECTORS = _env_selectors(
    "BING_SUBMIT_SELECTORS",
    [
        "button.b_copilot_send",
        "button[aria-label='Send']",
        "button[aria-label*='Send' i]",
    ],
)

#: Conversation turns. A new turn appears for every submitted question.
TURN_SELECTORS = _env_selectors("BING_TURN_SELECTORS", ["li.ca_turn"])

#: Answer hosts, checked inside the answer iframe (best first).
ANSWER_SELECTORS = _env_selectors(
    "BING_ANSWER_SELECTORS",
    [
        ".gs_text",
        ".gs_multianshead_main",
        ".answer_container",
        "li.b_ans",
        "#copans_container",
    ],
)

#: Elements that only exist while Bing is still generating the answer.
GENERATING_SELECTORS = _env_selectors(
    "BING_GENERATING_SELECTORS",
    [
        ".b_ts_search_stage",
        ".b_ts_sum_stage",
        ".b_ts_csronly",
        ".b_ts_exp_content",
    ],
)

#: Citation artefacts that are removed from the extracted answer.
#:
#: NOTE: ``ul.gs_cit_stry_pre`` / ``ol.gs_cit_stry_pre`` are the *content*
#: bullet lists of the answer and must be kept - Bing reuses the same class
#: name for both. Only the actual citation nodes are stripped:
#:   * ``div.gs_sup_cit``      - the inline citation chip ("Wikipedia", "+1")
#:   * ``li.gs_cit_stry_item`` - the "N Sources" row of a list
#:   * ``.gs_cit_stry_preview_txt`` - the "N Sources" label
#:   * ``.gs_sm_cit``          - the "View all" link of the sources block
CITATION_SELECTORS = _env_selectors(
    "BING_CITATION_SELECTORS",
    [
        ".gs_sup_cit",
        "li.gs_cit_stry_item",
        ".gs_cit_stry_preview_txt",
        ".gs_sm_cit",
    ],
)

#: Markers that indicate Microsoft is asking the user to authenticate.
LOGIN_URL_MARKERS = (
    "login.microsoftonline.com",
    "login.live.com",
    "account.microsoft.com",
    "/login",
)

LOGIN_TEXT_MARKERS = (
    "sign in to your account",
    "sign in to microsoft",
    "sign into copilot",
    "sign in to continue",
)

#: Query parameter that marks Bing's Copilot Search answer iframe.
ANSWER_FRAME_MARKER = "cpltsrchif=1"


@dataclass
class BingAnswer:
    """The result of asking one question."""

    question: str
    answer: str
    url: str | None = None
    elapsed_ms: int = 0
    conversation_url: str | None = None
    conversation_id: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "question": self.question,
            "answer": self.answer,
            "url": self.url,
            "elapsed_ms": self.elapsed_ms,
            "conversation_url": self.conversation_url,
            "conversation_id": self.conversation_id,
            "metadata": self.metadata,
        }


def _turn_index(url: str) -> int:
    """Extract Bing's ``turnindex`` query parameter from an answer iframe URL."""
    try:
        query = urllib.parse.parse_qs(urllib.parse.urlparse(url).query)
        return int(query.get("turnindex", ["0"])[0])
    except (ValueError, TypeError):
        return 0


def _conversation_id(url: str) -> str | None:
    """Extract Bing's ``convid`` query parameter from an answer iframe URL."""
    try:
        query = urllib.parse.parse_qs(urllib.parse.urlparse(url).query)
        value = query.get("convid", [None])[0]
        return value or None
    except (ValueError, TypeError):
        return None


class BingService:
    """High level operations against the Bing AI web interface."""

    def __init__(self, manager: BrowserManager | None = None) -> None:
        self.manager = manager or browser_manager

    # ------------------------------------------------------------------
    # Login detection
    # ------------------------------------------------------------------
    async def detect_login_required(self, page: Page | None = None) -> bool:
        """Best-effort detection of an authentication wall.

        Returns True when the page is an explicit Microsoft sign-in page or
        when a sign-in prompt is shown and no composer is available.
        """
        try:
            page = page or self.manager.require_page()
        except Exception:
            return False

        url = (page.url or "").lower()
        if any(marker in url for marker in LOGIN_URL_MARKERS):
            return True

        try:
            title = (await page.title()) or ""
        except Exception:
            title = ""

        try:
            snippet = await page.evaluate(
                "() => (document.body && document.body.innerText || '').slice(0, 3000).toLowerCase()"
            )
        except Exception:
            snippet = ""

        haystack = f"{title}\n{snippet}".lower()
        if any(marker in haystack for marker in LOGIN_TEXT_MARKERS):
            # A visible composer means we are actually signed in, so the word
            # "sign in" is probably just part of the navigation bar.
            if await self._find_input(page, timeout_ms=1500) is None:
                return True
        return False

    # ------------------------------------------------------------------
    # Locator helpers
    # ------------------------------------------------------------------
    async def _find_visible(
        self, page: Page, selectors: list[str], timeout_ms: int
    ) -> Locator | None:
        """Return the first visible locator matching any candidate selector."""
        deadline = asyncio.get_event_loop().time() + (timeout_ms / 1000)
        while True:
            for sel in selectors:
                try:
                    loc = page.locator(sel).first
                    if (await loc.count()) > 0 and await loc.is_visible():
                        return loc
                except Exception:
                    continue
            if asyncio.get_event_loop().time() >= deadline:
                return None
            await page.wait_for_timeout(200)

    async def _find_input(self, page: Page, timeout_ms: int | None = None) -> Locator | None:
        return await self._find_visible(
            page,
            INPUT_SELECTORS,
            timeout_ms if timeout_ms is not None else settings.action_timeout_ms,
        )

    async def _count_turns(self, page: Page) -> int:
        """Number of conversation turns currently rendered on the page."""
        for sel in TURN_SELECTORS:
            try:
                count = await page.locator(sel).count()
                if count:
                    return count
            except Exception:
                continue
        return 0

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    async def open(self) -> dict[str, Any]:
        """Open (or re-open) the Bing AI page."""
        if not self.manager.is_running:
            await self.manager.start()
        else:
            await self.manager.open_bing()
        page = self.manager.require_page()
        login_required = await self.detect_login_required(page)
        return {
            "url": page.url,
            "login_required": login_required,
            "composer_found": (await self._find_input(page, timeout_ms=2000)) is not None,
        }

    async def ask(self, question: str, *, new_conversation: bool = False) -> BingAnswer:
        """Submit a question to Bing AI and return the extracted answer."""
        question = (question or "").strip()
        if not question:
            raise EmptyResponseError("The question must not be empty.")

        async with self.manager.lock:
            return await self._ask_locked(question, new_conversation=new_conversation)

    async def _ask_locked(self, question: str, *, new_conversation: bool) -> BingAnswer:
        page = await self.manager.ensure_page_alive()
        loop = asyncio.get_event_loop()
        started = loop.time()

        # 1. Make sure we are on a usable chat page.
        if await self.detect_login_required(page):
            raise LoginRequiredError(
                "Microsoft sign-in is required. Complete the sign-in manually in the "
                "browser window that is already open, then retry the request."
            )

        composer = await self._find_input(page)
        if composer is None:
            # The page may have drifted to a landing page - try one reload.
            logger.warning("composer not found, reloading the Bing AI page")
            try:
                await self.manager.open_bing()
                page = await self.manager.ensure_page_alive()
            except Exception as exc:
                raise UnexpectedLayoutError(
                    "Could not load the Bing AI chat page.", detail=str(exc)
                ) from exc

            if await self.detect_login_required(page):
                raise LoginRequiredError(
                    "Microsoft sign-in is required. Sign in manually in the open "
                    "browser window, then retry."
                )

            composer = await self._find_input(page)
            if composer is None:
                raise InputNotFoundError(
                    "Could not find the Bing AI question input field on the page."
                )

        # 2. Optional: start a brand new conversation.
        if new_conversation:
            await self._try_new_conversation(page)
            page = await self.manager.ensure_page_alive()

        turns_before = await self._count_turns(page)

        # 3. Type the question. The composer is a React controlled component,
        #    so .fill() would not enable the send button - real key events
        #    are required.
        try:
            await composer.click(timeout=settings.action_timeout_ms)
            await composer.press_sequentially(question, delay=15)
        except PlaywrightTimeoutError as exc:
            raise InputNotFoundError(
                "Timed out while typing the question into the Bing AI input field.",
                detail=str(exc),
            ) from exc
        except PlaywrightError as exc:
            raise BrowserDisconnectedError(
                "Lost contact with the browser while typing the question.",
                detail=str(exc),
            ) from exc

        # 4. Submit.
        await self._submit(page, composer)

        # 5. Wait for and extract the answer.
        answer, conversation_id = await self._extract_answer(page, turns_before, started)
        elapsed_ms = int((loop.time() - started) * 1000)
        logger.info("Bing AI answered in %s ms (%s chars)", elapsed_ms, len(answer))
        return BingAnswer(
            question=question,
            answer=answer,
            url=page.url,
            elapsed_ms=elapsed_ms,
            conversation_url=page.url,
            conversation_id=conversation_id,
        )

    async def _submit(self, page: Page, composer: Locator) -> None:
        """Click the send button, falling back to the Enter key."""
        submit = await self._find_visible(page, SUBMIT_SELECTORS, timeout_ms=8000)
        if submit is not None:
            try:
                # The send button is enabled a moment after the last key
                # event - give React time to update its state.
                for _ in range(20):
                    try:
                        if await submit.is_enabled():
                            break
                    except Exception:
                        break
                    await page.wait_for_timeout(100)
                await submit.click(timeout=settings.action_timeout_ms)
                return
            except PlaywrightTimeoutError:
                logger.warning("send button was not clickable, falling back to Enter")
            except PlaywrightError as exc:
                logger.warning(
                    "send button click failed (%s), falling back to Enter", type(exc).__name__
                )
        try:
            await composer.press("Enter")
        except PlaywrightError as exc:
            raise SubmitNotFoundError(
                "Could not submit the question to Bing AI.", detail=str(exc)
            ) from exc

    # ------------------------------------------------------------------
    # Answer extraction
    # ------------------------------------------------------------------
    async def _pick_answer_frame(self, page: Page, turns_before: int) -> Frame | None:
        """Find the iframe that carries the answer of the newest turn."""
        frames = []
        for frame in page.frames:
            if ANSWER_FRAME_MARKER in (frame.url or ""):
                frames.append(frame)
        if not frames:
            return None
        frames.sort(key=lambda f: _turn_index(f.url or ""))
        for frame in frames:
            if _turn_index(frame.url or "") > turns_before:
                return frame
        return frames[-1]

    async def _extract_answer(
        self, page: Page, turns_before: int, started: float
    ) -> tuple[str, str | None]:
        """Locate the answer container and wait until generation finished."""
        deadline = started + (settings.answer_timeout_ms / 1000)
        settle_seconds = settings.stream_settle_ms / 1000

        frame: Frame | None = None
        host_selector: str | None = None
        last_text = ""
        stable_since: float | None = None
        conversation_id: str | None = None

        while True:
            now = asyncio.get_event_loop().time()
            if now >= deadline:
                if last_text.strip():
                    logger.warning("answer timeout reached - returning the partial text")
                    return self._clean_text(last_text), conversation_id
                raise ResponseTimeoutError(
                    "Timed out waiting for Bing AI to finish generating the answer."
                )

            # The answer lives in a nested iframe that Bing reloads while it
            # works, so the frame is re-resolved on every iteration.
            frame = await self._pick_answer_frame(page, turns_before)
            if frame is not None:
                conversation_id = _conversation_id(frame.url or "") or conversation_id
                text, selector = await self._read_answer_host(frame)
                if selector:
                    host_selector = selector
                if text.strip():
                    if text != last_text:
                        last_text = text
                        stable_since = None
                    elif stable_since is None:
                        stable_since = now
                    else:
                        generating = await self._is_generating(frame)
                        if not generating and (now - stable_since) >= settle_seconds:
                            cleaned = self._clean_text(text)
                            if cleaned:
                                return cleaned, conversation_id
                            stable_since = None
            await page.wait_for_timeout(500)

    async def _read_answer_host(self, frame: Frame) -> tuple[str, str | None]:
        """Return the text of the best answer container inside the iframe."""
        for sel in ANSWER_SELECTORS:
            try:
                loc = frame.locator(sel).first
                if (await loc.count()) == 0:
                    continue
                text = await self._raw_text(loc)
                if text.strip():
                    return text, sel
            except Exception:
                continue
        return "", None

    async def _raw_text(self, loc: Locator) -> str:
        """Read the answer text with the citation blocks removed.

        Bing renders the citations as ``ul.gs_cit_stry_pre`` elements that
        are interleaved between the paragraphs. They are temporarily hidden
        (not removed) so that the element stays attached to the document -
        ``innerText`` on a detached clone loses all block level line breaks.
        """
        try:
            return await loc.evaluate(
                """(el) => {
                    const sels = %s;
                    const hidden = [];
                    for (const sel of sels) {
                        let nodes = [];
                        try { nodes = el.querySelectorAll(sel); } catch (e) { continue; }
                        for (const n of nodes) {
                            hidden.push([n, n.getAttribute('style') || '']);
                            n.style.setProperty('display', 'none', 'important');
                        }
                    }
                    const text = el.innerText || '';
                    for (const [n, prev] of hidden) {
                        if (prev) n.setAttribute('style', prev);
                        else n.removeAttribute('style');
                    }
                    return text;
                }"""
                % _js_list(CITATION_SELECTORS)
            )
        except Exception:
            try:
                return await loc.inner_text()
            except Exception:
                return ""

    async def _is_generating(self, frame: Frame) -> bool:
        """True while Bing still shows its transient progress blocks.

        Only *visible* elements count - the hidden "See reasoning" panel
        keeps its text in the DOM even after the answer is complete.
        """
        try:
            return await frame.evaluate(
                """(sels) => {
                    for (const sel of sels) {
                        let nodes = [];
                        try { nodes = document.querySelectorAll(sel); } catch (e) { continue; }
                        for (const el of nodes) {
                            const r = el.getBoundingClientRect();
                            if (!(r.width && r.height)) continue;
                            const t = (el.innerText || '').trim();
                            if (t) return true;
                        }
                    }
                    return false;
                }""",
                GENERATING_SELECTORS,
            )
        except Exception:
            return False

    async def _try_new_conversation(self, page: Page) -> None:
        """Best-effort: click the 'New chat' control if the UI exposes one."""
        for sel in (
            "#cs_leftside_panel_newsearch",
            "button[aria-label='New chat']",
            "a[aria-label='New chat']",
            "button[title*='New chat' i]",
        ):
            try:
                loc = page.locator(sel).first
                if (await loc.count()) > 0 and await loc.is_visible():
                    await loc.click(timeout=8000)
                    await page.wait_for_timeout(2500)
                    logger.info("started a new Bing AI conversation")
                    return
            except Exception:
                continue
        logger.info("no 'new chat' control found - continuing in the current conversation")

    @staticmethod
    def _clean_text(text: str) -> str:
        """Normalise whitespace and drop leftover citation artefacts."""
        text = text.replace("\u00a0", " ")
        text = re.sub(r"[ \t]+\n", "\n", text)
        # A citation chip was removed from between a word and its punctuation
        # ("goods ." -> "goods.").
        text = re.sub(r"[ \t]+([.,;:!?])", r"\1", text)
        # Remove leftover citation rows such as "3 Sources".
        text = re.sub(r"(?m)^\s*\+?\d+\s+Sources?\s*$", "", text)
        text = re.sub(r"(?m)^\s*\+?\d+\s*$", "", text)
        text = re.sub(r"\n{3,}", "\n\n", text)
        return text.strip()

    # ------------------------------------------------------------------
    # Status
    # ------------------------------------------------------------------
    async def status(self) -> dict[str, Any]:
        """Status snapshot including a safe login determination."""
        status = self.manager.status()
        login_required: bool | None = None
        composer_found: bool | None = None
        if self.manager.is_running:
            try:
                page = self.manager.require_page()
                login_required = await self.detect_login_required(page)
                composer_found = (await self._find_input(page, timeout_ms=1500)) is not None
            except Exception:
                login_required = None
        return {
            **status,
            "login_required": login_required,
            "composer_found": composer_found,
            "bing_ai_url": settings.bing_ai_url,
        }


def _js_list(selectors: list[str]) -> str:
    """Render a Python list of CSS selectors as a JavaScript array literal."""
    import json

    return json.dumps(selectors)


bing_service = BingService()
