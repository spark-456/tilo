"""FR-MTG-11: the bot starts speaking at the first streamed audio piece, not when the whole reply is synthesized, and it
logs the text-in to first-audio latency without any of the text. Offline: scripted providers, no network."""

import asyncio
import logging
from collections.abc import Iterator
from typing import Any

import pytest
from tilo_providers.errors import QuotaError
from tilo_providers.speech import FakeSpeechProvider

from bot import providers as P
from bot.tts import TTSError


class Streaming(FakeSpeechProvider):
    def __init__(self, pieces: list[bytes], error: Exception | None = None) -> None:
        super().__init__()
        self.pieces, self.error, self.pulled = pieces, error, 0

    def synthesize_stream(self, text: str, *, voice: str | None = None, **kwargs: Any) -> Iterator[bytes]:
        for piece in self.pieces:
            self.pulled += 1
            yield piece
        if self.error is not None:
            raise self.error


def test_FR_MTG_11_the_first_streamed_piece_reaches_the_player_before_the_rest_is_synthesized():
    provider = Streaming([bytes(range(256)) * 10, b"\x00\x01" * 100, b"\x02\x03" * 100])

    async def go():
        stream = P.ProviderTTS(provider).stream("Hello there")
        first = await stream.__anext__()
        pulled_at_first = provider.pulled
        rest = [c async for c in stream]
        return first, pulled_at_first, rest

    first, pulled_at_first, rest = asyncio.run(go())
    assert pulled_at_first == 1 and len(first) <= 4800
    assert len(first) + sum(len(c) for c in rest) == sum(len(p) for p in provider.pieces)
    assert all(len(c) <= 4800 for c in rest)


def test_FR_MTG_11_a_failure_mid_stream_is_a_typed_tts_error_with_no_provider_text():
    provider = Streaming([b"\x00\x01" * 10], error=QuotaError("429 secret-token"))

    async def go():
        return [c async for c in P.ProviderTTS(provider).stream("Hello")]

    with pytest.raises(TTSError) as excinfo:
        asyncio.run(go())
    assert "secret-token" not in str(excinfo.value) and not excinfo.value.permanent


def test_FR_MTG_11_the_text_to_first_audio_latency_is_logged_without_the_text(caplog):
    async def go():
        return [c async for c in P.ProviderTTS(Streaming([b"\x00\x01" * 50])).stream("Private budget figures.")]

    with caplog.at_level(logging.INFO, logger="bot.providers"):
        asyncio.run(go())
    line = next(r.getMessage() for r in caplog.records if "first_audio_ms" in r.getMessage())
    assert "characters=23" in line and "Private" not in line and "budget" not in line
