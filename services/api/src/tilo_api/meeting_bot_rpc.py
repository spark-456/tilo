"""Private Cloud Run attendance client. Identity via metadata; response bounded; never retry a launch."""

from __future__ import annotations

import asyncio
import os

import httpx
from fastapi import HTTPException
from tilo_contracts import MeetingJoin, Transcript

from tilo_api.meeting_bot import BotCapture
from tilo_api.meeting_host_rpc import _URL, metadata_id_token


class MeetingBotRpc:
    def __init__(self, base_url: str, *, token_for=metadata_id_token, transport=None) -> None:
        if _URL.fullmatch(base_url) is None:
            raise ValueError("Invalid bot endpoint")
        self._base, self._token_for, self._transport = base_url, token_for, transport

    def __repr__(self) -> str:
        return "MeetingBotRpc()"

    async def attend(self, meeting_id: str, join: MeetingJoin, claim: str | None = None) -> BotCapture:
        if os.environ.get("LIVE") != "1":
            raise HTTPException(503, "bot_not_enabled")
        try:
            token = await asyncio.wait_for(asyncio.to_thread(self._token_for, self._base), timeout=10)
            timeout = httpx.Timeout(connect=5, read=3500, write=20, pool=5)
            async with httpx.AsyncClient(transport=self._transport, timeout=timeout, follow_redirects=False) as client:
                async with client.stream(
                    "POST",
                    f"{self._base}/internal/meetings/{meeting_id}/attend",
                    json=join.model_dump(mode="json"),
                    headers={"Authorization": f"Bearer {token}"}
                    | ({"X-Tilo-Meeting-Claim": claim} if claim else {}),  # ADR-0042 MV-16: the bot never logs it
                ) as response:
                    if response.status_code != 200:
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
        except Exception:
            raise HTTPException(503, "bot_unavailable") from None


def get_meeting_bot_client() -> MeetingBotRpc:
    if os.environ.get("LIVE") != "1":
        raise HTTPException(503, "bot_not_enabled")
    try:
        return MeetingBotRpc(os.environ.get("TILO_MEET_BOT_URL", ""))
    except ValueError:
        raise HTTPException(503, "bot_not_configured") from None
