"""Private Cloud Run attendance client. Identity via metadata; response bounded.

The bot scales to zero, so the first call can meet a cold start: `wake` reads its /health until it answers, and `attend`
repeats the POST only while the bot has not started (a connection error, or a 502/503/504 that is not the bot's own
answer about a meeting it ran). Once the bot answers 200 or with its own post-launch error nothing is repeated: a
launch is never retried (MEET-SIMPLE, FR-MTG-09, ADR-0024)."""

from __future__ import annotations

import asyncio
import json
import os
import time

import httpx
from fastapi import HTTPException
from tilo_contracts import MeetingJoin, Transcript

from tilo_api.meeting_bot import BotCapture
from tilo_api.meeting_host_rpc import _URL, metadata_id_token

WAKE_BUDGET_S = 30.0  # waiting for a cold bot to answer /health
ATTEND_BUDGET_S = 45.0  # repeating a launch the bot never started
_BACKOFF_S = (1.0, 2.0, 3.0, 4.0, 5.0)
_COLD = frozenset({502, 503, 504})
# What the bot app itself says after it has run a meeting (meet-bot/bot/cloud_run.py): these are never repeated.
_RAN = frozenset(
    {
        "Meeting bot failed",
        "Meeting duration exceeded",
        "Bot is attending another meeting",
        "browser_unavailable",
        "meeting_requires_sign_in",
        "meeting_join_failed",
    }
)
_REASONS = frozenset({"browser_unavailable", "meeting_requires_sign_in", "meeting_join_failed"})


class MeetingBotRpc:
    def __init__(self, base_url: str, *, token_for=metadata_id_token, transport=None, sleep=asyncio.sleep) -> None:
        if _URL.fullmatch(base_url) is None:
            raise ValueError("Invalid bot endpoint")
        self._base, self._token_for, self._transport, self._sleep = base_url, token_for, transport, sleep

    def __repr__(self) -> str:
        return "MeetingBotRpc()"

    async def wake(self, budget_s: float = WAKE_BUDGET_S) -> bool:
        """Best effort: read the bot's /health until it answers, so a cold start is over before a launch. True once it
        answered; False when it did not within the budget (the launch then still tries, and repeats on its own)."""
        if os.environ.get("LIVE") != "1":
            return False
        spent = _Spent()
        try:
            token = await asyncio.wait_for(asyncio.to_thread(self._token_for, self._base), timeout=10)
        except Exception:
            return False
        for attempt in range(1000):
            try:
                timeout = httpx.Timeout(connect=5, read=10, write=5, pool=5)
                async with httpx.AsyncClient(transport=self._transport, timeout=timeout) as client:
                    got = await client.get(f"{self._base}/health", headers={"Authorization": f"Bearer {token}"})
                if got.status_code == 200:
                    return True
            except httpx.HTTPError:
                pass
            pause = _BACKOFF_S[min(attempt, len(_BACKOFF_S) - 1)]
            if spent.after(pause) >= budget_s:
                return False
            await self._sleep(pause)
            spent.slept += pause
        return False

    async def attend(
        self, meeting_id: str, join: MeetingJoin, claim: str | None = None, action_claim: str | None = None
    ) -> BotCapture:
        if os.environ.get("LIVE") != "1":
            raise HTTPException(503, "bot_not_enabled")
        try:
            token = await asyncio.wait_for(asyncio.to_thread(self._token_for, self._base), timeout=10)
            spent = _Spent()
            for attempt in range(1000):
                try:
                    return await self._launch(meeting_id, join, claim, token, action_claim)
                except _NotStarted:
                    pause = _BACKOFF_S[min(attempt, len(_BACKOFF_S) - 1)]
                    if spent.after(pause) >= ATTEND_BUDGET_S:
                        raise ValueError("Bot did not start") from None
                    await self._sleep(pause)
                    spent.slept += pause
            raise ValueError("Bot did not start")
        except _BotRefused as exc:
            raise HTTPException(exc.status, exc.detail) from None
        except Exception:
            raise HTTPException(503, "bot_unavailable") from None

    async def _launch(
        self, meeting_id: str, join: MeetingJoin, claim: str | None, token: str, action_claim: str | None = None
    ) -> BotCapture:
        timeout = httpx.Timeout(connect=5, read=3500, write=20, pool=5)
        try:
            async with httpx.AsyncClient(transport=self._transport, timeout=timeout, follow_redirects=False) as client:
                async with client.stream(
                    "POST",
                    f"{self._base}/internal/meetings/{meeting_id}/attend",
                    json=join.model_dump(mode="json"),
                    headers={"Authorization": f"Bearer {token}"}
                    | ({"X-Tilo-Meeting-Claim": claim} if claim else {})  # ADR-0042 MV-16: the bot never logs it
                    # ADR-0042 amendment 1: the attend's action nonce, only while TILO_MEETING_ACTIONS=1; never logged
                    | ({"X-Tilo-Meeting-Actions": action_claim} if action_claim else {}),
                ) as response:
                    if response.status_code != 200:
                        detail = await _bot_detail(response)
                        if detail in _REASONS:
                            raise _BotRefused(response.status_code, detail)
                        if response.status_code in _COLD and detail not in _RAN:
                            raise _NotStarted
                        raise ValueError("Bot refused")
                    data = bytearray()
                    async for chunk in response.aiter_bytes():
                        if len(data) + len(chunk) > 2_000_000:
                            raise ValueError("Capture is too large")
                        data.extend(chunk)
                    transcript = Transcript.model_validate_json(data)
                    reason = response.headers.get("X-Tilo-Meeting-End-Reason", "")
                    if transcript.meeting_id != meeting_id or reason not in (
                        "completed",
                        "left_on_request",
                        "removed",
                        "timeout",
                        "failed",
                    ):
                        raise ValueError("Invalid capture")
                    return BotCapture(transcript, reason)
        except (httpx.ConnectError, httpx.ConnectTimeout, httpx.PoolTimeout):
            raise _NotStarted from None  # the request never reached the bot


class _Spent:
    """Time used so far: the longer of the real clock and the pauses taken (so a fake sleep still runs out)."""

    def __init__(self) -> None:
        self._t0, self.slept = time.monotonic(), 0.0

    def after(self, pause: float) -> float:
        return max(time.monotonic() - self._t0, self.slept) + pause


class _NotStarted(Exception):
    """The bot did not start the launch (cold start or unreachable): safe to ask again."""


class _BotRefused(Exception):
    def __init__(self, status: int, detail: str) -> None:
        self.status, self.detail = status, detail


async def _bot_ran(response: httpx.Response) -> bool:
    """True when the body is the bot app's own post-launch answer; a Google front-end page or empty body is not."""
    try:
        return await _bot_detail(response) in _RAN
    except Exception:
        return False


async def _bot_detail(response: httpx.Response) -> str:
    try:
        body = bytearray()
        async for chunk in response.aiter_bytes():
            body.extend(chunk)
            if len(body) > 2048:
                return ""
        detail = json.loads(body).get("detail")
        return detail if isinstance(detail, str) else ""
    except Exception:
        return ""


def get_meeting_bot_client() -> MeetingBotRpc:
    if os.environ.get("LIVE") != "1":
        raise HTTPException(503, "bot_not_enabled")
    try:
        return MeetingBotRpc(os.environ.get("TILO_MEET_BOT_URL", ""))
    except ValueError:
        raise HTTPException(503, "bot_not_configured") from None
