"""The fast-path model client: streaming, a hard first-token deadline, and no sleeping.

Direct answers must not wait on the model, so this client is built differently from the analysis loop's `ProviderLLM`:
- one long-lived client per purpose (never a client per worker thread);
- the first token has a deadline; on a miss or a dropped connection it retries once on a fresh client, at once;
- a quota error raises `Busy` straight away: the caller falls back, it never sleeps and retries;
- `prewarm()` opens the connection early (when a question is likely), at most once every 10 s, and only reports a
  prewarm when the client really had something to warm;
- every attempt is reported (outcome, code, first-token time), so a slow reply can be explained from the logs.

The client behind it is a `FastClient` (the provider layer, `bot/providers.py`); this module names no model, vendor or
SDK. Which model answers is the role's profile in Tilo's `config/`; the thinking level comes from `FAST_THINKING`.
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import AsyncIterator, Callable
from typing import Any, Protocol

from .brain import Busy, LLMUnavailable

log = logging.getLogger("bot.llm_fast")


class ModelCallError(Exception):
    """A failed model call as `FastLLM` reads it: an HTTP-like code (429 quota, 4xx refused, None transport) and a
    status word. The message is a fixed word, never provider text."""

    def __init__(self, code: int | None, status: str = "", message: str = "model call failed") -> None:
        super().__init__(message)
        self.code, self.status = code, status


class CallCapReached(ModelCallError):
    """The meeting's cap on provider calls is reached (config/meeting.yaml): no request was made and none will be."""

    def __init__(self, message: str = "the meeting's model call cap is reached") -> None:
        super().__init__(None, "CALL_CAP", message)


class FastClient(Protocol):
    async def open(
        self, system: str, prompt: str, *, json_mode: bool, max_tokens: int, thinking: str
    ) -> AsyncIterator[str]:
        """The reply's text deltas, in order."""
        ...

    async def warm(self) -> bool:
        """Open whatever can be opened ahead of a call; True if something was."""
        ...


class FastLLM:
    def __init__(
        self,
        client_factory: Callable[[], FastClient],
        thinking: str = "off",
        purpose: str = "fast",
        first_token_s: float = 2.5,
        on_attempt: Callable[[dict[str, Any]], None] | None = None,
        clock: Callable[[], float] = time.monotonic,
        prewarm_every_s: float = 10.0,
    ) -> None:
        self.thinking, self.purpose = thinking, purpose
        self._prewarm_off = False
        self.first_token_s, self.on_attempt, self.clock = first_token_s, on_attempt, clock
        self.prewarm_every_s = prewarm_every_s
        self._factory = client_factory
        self._client: FastClient | None = None
        self._last_prewarm: float | None = None
        self.last_call: dict[str, float] = {}  # clock time of the last request and of its first token

    # -- public --------------------------------------------------------------------------------------------------------
    async def stream(
        self, system: str, prompt: str, *, json_mode: bool = False, max_tokens: int = 256
    ) -> AsyncIterator[str]:
        """Text deltas in order. Raises `Busy` on a quota error and `LLMUnavailable` when both attempts fail."""
        last: Exception | None = None
        for attempt in (1, 2):
            if attempt == 2 or self._client is None:
                self._client = self._factory()  # a retry never reuses the connection that just failed
            started = self.clock()
            chunks = None
            try:
                async with asyncio.timeout(self.first_token_s):
                    chunks = await self._client.open(
                        system, prompt, json_mode=json_mode, max_tokens=max_tokens, thinking=self.thinking
                    )
                    iterator = chunks.__aiter__()
                    first = await self._first_text(iterator)
            except TimeoutError:
                self._report(attempt, "timeout", None, None, started)
                last = LLMUnavailable(f"no first token within {self.first_token_s:.1f}s")
                await _close(chunks)
                continue
            except Exception as e:
                code = _code(e)
                await _close(chunks)
                if isinstance(e, CallCapReached):  # nothing was sent; a second try is refused the same way
                    self._report(attempt, "capped", None, None, started)
                    raise LLMUnavailable(str(e)) from None
                if code == 429 or _status(e) == "RESOURCE_EXHAUSTED":
                    self._report(attempt, "busy", 429, None, started)
                    raise Busy("the model is rate limited") from None
                if code in (400, 401, 403, 404):
                    self._report(attempt, "error", code, None, started, self._redact(e))
                    raise LLMUnavailable(self._explain(code, e)) from None
                self._report(attempt, "error", code, None, started, self._redact(e))
                last = e
                continue
            first_token_s = self.clock() - started
            self.last_call = {"request_at": started, "first_token_at": started + first_token_s}
            outcome = "cancelled"  # the consumer stopped early (barge-in): not a failure
            try:
                if first:
                    yield first
                async for chunk in _texts(iterator):
                    yield chunk
                outcome = "ok"
            except Exception as e:  # a stream that dies after its first token is not replayed
                outcome = "error"
                self._report(attempt, "error", _code(e), first_token_s, started, self._redact(e))
                raise LLMUnavailable(f"model stream broke: {self._redact(e)}") from None
            finally:
                await _close(chunks)
                if outcome != "error":
                    self._report(attempt, outcome, None, first_token_s, started)
            return
        raise LLMUnavailable(f"fast model unavailable after 2 tries: {self._redact(last)}") from None

    async def generate(self, system: str, prompt: str, **kw: Any) -> str:
        return "".join([d async for d in self.stream(system, prompt, **kw)])

    async def prewarm(self) -> bool:
        """Open the connection before it is needed. True if a call was made (at most one per `prewarm_every_s`)."""
        now = self.clock()
        if self._prewarm_off or (self._last_prewarm is not None and now - self._last_prewarm < self.prewarm_every_s):
            return False
        self._last_prewarm = now
        try:
            if self._client is None:
                self._client = self._factory()
            warmed = await asyncio.wait_for(self._client.warm(), timeout=self.first_token_s * 2)
            if warmed:
                self._report(1, "prewarm", None, None, now)
        except Exception as e:  # warming is best effort
            self._report(1, "error", _code(e), None, now, self._redact(e))
            if _code(e) in (401, 403, 404):  # this client cannot warm: it would only fail again
                self._prewarm_off = True
        return True

    # -- internals -----------------------------------------------------------------------------------------------------
    @staticmethod
    async def _first_text(iterator: Any) -> str:
        """The first non-empty delta; an empty stream gives ''."""
        async for text in iterator:
            if text:
                return text
        return ""

    def _report(
        self,
        attempt: int,
        outcome: str,
        code: int | None,
        first_token_s: float | None,
        started: float,
        error: str | None = None,
    ) -> None:
        row = {
            "purpose": self.purpose,
            "attempt": attempt,
            "outcome": outcome,
            "code": code,
            "first_token_s": None if first_token_s is None else round(first_token_s, 3),
            "total_s": round(self.clock() - started, 3),
        }
        if error:
            row["error"] = error
        log.info("model attempt %s", row)
        if self.on_attempt:
            self.on_attempt(row)

    @staticmethod
    def _redact(e: Exception | None) -> str:
        """Provider error text never reaches a log, a row or a message: the exception class and the status code only."""
        code = None if e is None else _code(e)
        return type(e).__name__ if code is None else f"{type(e).__name__} ({code})"

    @staticmethod
    def _explain(code: int | None, e: Exception) -> str:
        if code in (401, 403):
            return f"the model service refused the credentials or permissions ({code})"
        if code == 404:
            return "the model for this role was not found (check the role's profile in config/)"
        return f"the model request was refused ({code})"


async def _texts(iterator: Any) -> AsyncIterator[str]:
    async for text in iterator:
        if text:
            yield text


async def _close(chunks: Any) -> None:
    closer = getattr(chunks, "aclose", None)
    if closer:
        try:
            await closer()
        except Exception:
            pass


def _code(e: Exception) -> int | None:
    code = getattr(e, "code", None) or getattr(e, "status_code", None)
    return code if isinstance(code, int) else None


def _status(e: Exception) -> str:
    return str(getattr(e, "status", "") or "")
