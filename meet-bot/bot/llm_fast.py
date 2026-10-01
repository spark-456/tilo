"""The fast-path model client: streaming, a hard first-token deadline, and no sleeping.

Direct answers must not wait on the model, so this client is built differently from the analysis loop's `GeminiLLM`:
- one long-lived async client per purpose (never a client per worker thread);
- the first token has a deadline; on a miss or a dropped connection it retries once on a fresh client, at once;
- a 429 raises `Busy` straight away: the caller falls back, it never sleeps and retries;
- `prewarm()` opens the connection early (when a question is likely), at most once every 10 s;
- every attempt is reported (outcome, code, first-token time), so a slow reply can be explained from the logs.

Model id and thinking level come from config (`FAST_MODEL`, `FAST_THINKING`), never from the model's name.
"""

from __future__ import annotations

import asyncio
import logging
import os
import re
import time
from collections.abc import AsyncIterator, Callable
from typing import Any

from .brain import Busy, LLMUnavailable

log = logging.getLogger("bot.llm_fast")


def thinking_config(level: str) -> dict[str, Any]:
    """`off` switches thinking off; anything else sets that thinking level."""
    return {"thinking_budget": 0} if level == "off" else {"thinking_level": level.upper()}


def make_client(timeout_s: float = 10.0) -> Any:
    key = os.environ.get("GEMINI_API_KEY", "")
    if not key:
        raise LLMUnavailable("GEMINI_API_KEY is not set. Add it to .env to enable direct answers.")
    from google import genai
    from google.genai import types

    return genai.Client(vertexai=True, api_key=key, http_options=types.HttpOptions(timeout=int(timeout_s * 1000)))


class FastLLM:
    def __init__(
        self,
        model: str,
        thinking: str = "off",
        purpose: str = "fast",
        client_factory: Callable[[], Any] = make_client,
        first_token_s: float = 2.5,
        on_attempt: Callable[[dict[str, Any]], None] | None = None,
        clock: Callable[[], float] = time.monotonic,
        prewarm_every_s: float = 10.0,
        api_key: str | None = None,
        fallback_model: str | None = None,
    ) -> None:
        self.model, self.thinking, self.purpose = model, thinking, purpose
        self.fallback_model = fallback_model  # used for good if `model` is not available to this key
        self._prewarm_off = False
        self.first_token_s, self.on_attempt, self.clock = first_token_s, on_attempt, clock
        self.prewarm_every_s, self._api_key = prewarm_every_s, api_key
        self._factory = client_factory
        self._client: Any = None
        self._last_prewarm: float | None = None
        self.last_call: dict[str, float] = {}  # clock time of the last request and of its first token

    # -- public --------------------------------------------------------------------------------------------------------
    async def stream(
        self, system: str, prompt: str, *, json_mode: bool = False, max_tokens: int = 256
    ) -> AsyncIterator[str]:
        """Text deltas in order. Raises `Busy` on a 429 and `LLMUnavailable` when both attempts fail."""
        config: dict[str, Any] = {
            "system_instruction": system,
            "temperature": 0.2,
            "max_output_tokens": max_tokens,
            "automatic_function_calling": {"disable": True},
            "thinking_config": thinking_config(self.thinking),
        }
        if json_mode:
            config["response_mime_type"] = "application/json"
        last: Exception | None = None
        for attempt in (1, 2):
            if attempt == 2 or self._client is None:
                self._client = self._factory()  # a retry never reuses the connection that just failed
            started = self.clock()
            chunks = None
            try:
                async with asyncio.timeout(self.first_token_s):
                    chunks = await self._client.aio.models.generate_content_stream(
                        model=self.model, contents=prompt, config=config
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
                if code == 429 or _status(e) == "RESOURCE_EXHAUSTED":
                    self._report(attempt, "busy", 429, None, started)
                    raise Busy("the model is rate limited") from None
                if code in (400, 401, 403, 404):
                    self._report(attempt, "error", code, None, started, self._redact(e))
                    if code == 404 and self.fallback_model and self.fallback_model != self.model and attempt == 1:
                        log.warning("model %s is not available to this key; using %s", self.model, self.fallback_model)
                        self.model = self.fallback_model
                        continue
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
            await asyncio.wait_for(self._client.aio.models.get(model=self.model), timeout=self.first_token_s * 2)
            self._report(1, "prewarm", None, None, now)
        except Exception as e:  # warming is best effort
            self._report(1, "error", _code(e), None, now, self._redact(e))
            if _code(e) in (401, 403, 404):  # this key cannot call models.get: it would only fail again
                self._prewarm_off = True
        return True

    # -- internals -----------------------------------------------------------------------------------------------------
    @staticmethod
    async def _first_text(iterator: Any) -> str:
        """The first non-empty delta; an empty stream gives ''."""
        async for chunk in iterator:
            text = getattr(chunk, "text", None)
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
            "model": self.model,
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

    def _redact(self, e: Exception | None) -> str:
        text = re.sub(r"\s+", " ", f"{type(e).__name__}: {e}")
        for secret in (self._api_key, os.environ.get("GEMINI_API_KEY")):
            if secret:
                text = text.replace(secret, "[redacted]")
        return text[:200]

    def _explain(self, code: int | None, e: Exception) -> str:
        if code in (401, 403):
            return f"Gemini rejected the API key or permissions ({code}). Check GEMINI_API_KEY."
        if code == 404:
            return f"Model '{self.model}' was not found. Set FAST_MODEL to a model your key can use."
        return f"Gemini request failed ({code}): {self._redact(e)}"


async def _texts(iterator: Any) -> AsyncIterator[str]:
    async for chunk in iterator:
        text = getattr(chunk, "text", None)
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
