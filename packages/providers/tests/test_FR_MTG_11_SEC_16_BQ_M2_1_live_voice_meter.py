"""FR-MTG-11 (M2b), SEC-16, BQ-M2-1: a LIVE Gemini Live voice call is metered by a hook the process supplies, or it is
refused. Code gates, not config flags: no hook means the live factory is not built (and the voice factory builds Chirp,
never the Live adapter, under the live switch); the hook reserves before any session opens, receives each call's own
usage exactly once and releases on a failure or a cancel; an unreadable or capped ledger never reaches the provider.
Fake sessions and fake meters only: no network, no SDK session."""

from __future__ import annotations

import asyncio
import logging
import threading
from concurrent.futures import ThreadPoolExecutor
from contextlib import asynccontextmanager
from types import SimpleNamespace as NS
from typing import Any

import pytest
from test_FR_MTG_11_gemini_live_voice import (
    CONFIG,
    FAKE_TOKEN,
    FIXTURES,
    TEXT,
    A,
    B,
    Transport,
    message,
    with_live,
)
from tilo_providers.errors import NotConfigured, ProviderError
from tilo_providers.gemini_live_voice_adapter import GeminiLiveVoiceProvider
from tilo_providers.voice import GoogleVoiceProvider, build_voice_provider


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    for name in ("LIVE", "TILO_RECORD", "K_SERVICE", "CLOUD_RUN_JOB", "GOOGLE_VERTEX_BASE_URL"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("GOOGLE_APPLICATION_CREDENTIALS", str(FIXTURES / "no-such-adc.json"))


def usage(prompt: int, reply: int) -> Any:
    return NS(prompt_token_count=prompt, response_token_count=reply, total_token_count=prompt + reply)


class Meter:
    """A fake spend hook. `events` is the whole story: reserve, settle (with the usage) and release, in order."""

    def __init__(self, *, refuse: bool = False, error: Exception | None = None, close_error: bool = False) -> None:
        self.refuse, self.error, self.close_error = refuse, error, close_error
        self.events: list[tuple[Any, ...]] = []
        self._lock, self._n = threading.Lock(), 0
        self.on_reserve: Any = None

    def reserve(self) -> Any:
        if self.on_reserve is not None:
            self.on_reserve()
        if self.error is not None:
            raise self.error
        if self.refuse:
            self.events.append(("reserve", None))
            return None
        with self._lock:
            self._n += 1
            hold = f"hold-{self._n}"
        self.events.append(("reserve", hold))
        return hold

    def settle(self, hold: Any, usage_counts: Any) -> None:
        self.events.append(("settle", hold, dict(usage_counts)))
        if self.close_error:
            raise ConnectionError("ledger went away")

    def release(self, hold: Any) -> None:
        self.events.append(("release", hold))
        if self.close_error:
            raise ConnectionError("ledger went away")

    def kinds(self) -> list[str]:
        return [event[0] for event in self.events]


def metered(transport: Any, meter: Any, **kwargs: Any) -> GeminiLiveVoiceProvider:
    return GeminiLiveVoiceProvider(CONFIG, fixtures_dir=FIXTURES, session_factory=transport, meter=meter, **kwargs)


GOOD_USAGE = [message(A, usage=usage(11, 22)), message(B, complete=True, usage=usage(11, 33))]


def forbid_sdk(monkeypatch) -> None:
    from google import genai

    monkeypatch.setattr(genai, "Client", lambda **kwargs: pytest.fail("a live SDK client was built"))


def go_live(monkeypatch) -> None:
    monkeypatch.setenv("LIVE", "1")
    monkeypatch.setenv("GOOGLE_CLOUD_PROJECT", "tilo-dev-test")


def test_FR_MTG_11_SEC_16_BQ_M2_1_a_live_call_without_a_hook_is_refused_and_builds_no_client(monkeypatch):
    forbid_sdk(monkeypatch)
    go_live(monkeypatch)
    approved = with_live(price_approved=True)
    with pytest.raises(NotConfigured, match="SEC-16"):  # price approved, project set, switch on: still no hook
        GeminiLiveVoiceProvider(approved, fixtures_dir=None).synthesize_stream(TEXT)
    with pytest.raises(NotConfigured, match="SEC-16"):
        GeminiLiveVoiceProvider(approved, fixtures_dir=FIXTURES).synthesize(TEXT)


def test_FR_MTG_11_SEC_16_BQ_M2_1_the_voice_factory_builds_chirp_not_the_live_adapter_without_a_hook(monkeypatch):
    flagged = with_live(price_approved=True)
    assert isinstance(build_voice_provider(flagged, fixtures_dir=FIXTURES), GeminiLiveVoiceProvider)  # replay only
    go_live(monkeypatch)
    assert isinstance(build_voice_provider(flagged, fixtures_dir=FIXTURES), GoogleVoiceProvider)  # the code gate
    hooked = build_voice_provider(flagged, fixtures_dir=FIXTURES, meter=Meter())
    assert isinstance(hooked, GeminiLiveVoiceProvider)
    off = with_live(price_approved=True, enabled=False)  # the flag is off: Chirp, with or without a hook
    assert isinstance(build_voice_provider(off, fixtures_dir=FIXTURES, meter=Meter()), GoogleVoiceProvider)


def test_FR_MTG_11_SEC_16_BQ_M2_1_the_hook_reserves_before_a_session_opens_and_gets_the_calls_usage_once():
    transport, meter = Transport(GOOD_USAGE), Meter()
    seen_open: list[int] = []
    meter.on_reserve = lambda: seen_open.append(transport.opened)
    assert metered(transport, meter).synthesize(TEXT) == A + B
    assert seen_open == [0]  # reserved while no session existed
    assert meter.events == [
        ("reserve", "hold-1"),
        ("settle", "hold-1", {"prompt_token_count": 11, "response_token_count": 33, "total_token_count": 44}),
    ]
    assert transport.opened == transport.closed == 1


def test_FR_MTG_11_SEC_16_BQ_M2_1_a_call_without_usage_metadata_still_settles_once_with_empty_usage():
    meter = Meter()
    assert metered(Transport([message(A), message(B, complete=True)]), meter).synthesize(TEXT) == A + B
    assert meter.events == [("reserve", "hold-1"), ("settle", "hold-1", {})]


def test_FR_MTG_11_SEC_16_BQ_M2_1_a_session_that_fails_before_anything_arrives_releases_the_hold():
    meter = Meter()
    transport = Transport([], error=RuntimeError("connect failed"))
    with pytest.raises(ProviderError):
        metered(transport, meter).synthesize(TEXT)
    assert meter.events == [("reserve", "hold-1"), ("release", "hold-1")]
    assert transport.closed == transport.opened == 1


@pytest.mark.parametrize(
    "replies",
    [
        [message(A, complete=False)],  # the turn did not finish (nothing reported)
        [message(A, interrupted=True)],
        [message(bytes(5000), complete=True)],  # over the audio cap
    ],
)
def test_FR_MTG_11_SEC_16_BQ_M2_1_every_failed_turn_closes_its_hold_exactly_once(replies):
    meter = Meter()
    with pytest.raises(ProviderError):
        metered(Transport(replies), meter).synthesize(TEXT)
    assert meter.kinds() in (["reserve", "release"], ["reserve", "settle"])  # closed once, never leaked, never both
    assert meter.events[0] == ("reserve", "hold-1") and meter.events[1][1] == "hold-1"


def test_FR_MTG_11_SEC_16_BQ_M2_1_a_failure_after_the_model_ran_is_charged_with_what_it_reported_not_released():
    meter = Meter()
    transport = Transport([message(A, usage=usage(5, 7))], error=RuntimeError("stream dropped"))
    with pytest.raises(ProviderError):
        metered(transport, meter).synthesize(TEXT)
    assert meter.events == [
        ("reserve", "hold-1"),
        ("settle", "hold-1", {"prompt_token_count": 5, "response_token_count": 7, "total_token_count": 12}),
    ]


def test_FR_MTG_11_SEC_16_BQ_M2_1_a_timeout_and_a_cancel_never_leak_the_hold():
    stalled, meter = Transport([]), Meter()

    async def forever():
        await asyncio.Event().wait()
        yield message()

    stalled.receive = forever  # type: ignore[method-assign]
    quick = with_live(timeout_s=0.05)
    with pytest.raises(ProviderError, match="timed out"):
        GeminiLiveVoiceProvider(quick, fixtures_dir=FIXTURES, session_factory=stalled, meter=meter).synthesize(TEXT)
    assert meter.events == [("reserve", "hold-1"), ("release", "hold-1")]

    cancelled = Meter()
    pieces = metered(Transport(GOOD_USAGE), cancelled).synthesize_stream(TEXT)
    assert next(pieces) == A
    pieces.close()  # the caller stops listening (barge-in)
    pieces.close()
    assert cancelled.kinds() == ["reserve", "settle"]


def test_FR_MTG_11_SEC_16_BQ_M2_1_a_stream_nobody_started_reserves_nothing():
    meter, transport = Meter(), Transport(GOOD_USAGE)
    pieces = metered(transport, meter).synthesize_stream(TEXT)
    pieces.close()
    del pieces
    assert meter.events == [] and transport.opened == 0


def test_FR_MTG_11_SEC_16_BQ_M2_1_a_refusing_or_unreadable_ledger_never_reaches_the_provider(caplog):
    caplog.set_level(logging.INFO)
    for meter in (Meter(refuse=True), Meter(error=ConnectionError(f"firestore says Bearer {FAKE_TOKEN}"))):
        transport = Transport(GOOD_USAGE)
        with pytest.raises(NotConfigured) as caught:
            metered(transport, meter).synthesize(TEXT)
        assert transport.opened == 0 and transport.sent == [] and FAKE_TOKEN not in str(caught.value)
        assert not any(kind in ("settle", "release") for kind in meter.kinds())
    assert FAKE_TOKEN not in caplog.text


def test_FR_MTG_11_SEC_16_BQ_M2_1_replay_and_bad_requests_cost_nothing_and_never_reserve():
    meter = Meter()
    live = GeminiLiveVoiceProvider(CONFIG, fixtures_dir=FIXTURES, meter=meter)  # no session, no switch: replay
    assert live.synthesize(TEXT) == A + B
    with pytest.raises(NotConfigured):
        live.synthesize_stream("A reply nobody recorded.")
    assert meter.events == []


def test_FR_MTG_11_SEC_16_BQ_M2_1_a_hook_that_fails_while_closing_never_breaks_the_voice(caplog):
    caplog.set_level(logging.INFO)
    meter = Meter(close_error=True)
    assert metered(Transport(GOOD_USAGE), meter).synthesize(TEXT) == A + B
    assert meter.kinds() == ["reserve", "settle"]
    assert "ConnectionError" in caplog.text and "ledger went away" not in caplog.text


class PerCallSessions:
    """One factory for the whole provider: each session answers with usage derived from the text it was sent."""

    def __init__(self) -> None:
        self.opened = 0

    def __call__(self, settings: Any):
        self.opened += 1
        sent: list[str] = []

        class Session:
            async def send_client_content(self, *, turns: Any, turn_complete: bool) -> None:
                sent.append(turns["parts"][0]["text"])

            async def receive(self):
                n = len(sent[0])
                yield message(A, usage=usage(n, n * 2))
                yield message(B, complete=True, usage=usage(n, n * 3))

        @asynccontextmanager
        async def connect():
            yield Session()

        return connect()


def test_FR_MTG_11_SEC_16_BQ_M2_1_interleaved_replies_on_one_provider_do_not_mix_usage():
    meter, factory = Meter(), PerCallSessions()
    live = metered(factory, meter)
    first, second = live.synthesize_stream("one"), live.synthesize_stream("seven!!")
    assert next(first) == A and next(second) == A  # both in flight on the one instance
    assert list(second) == [B] and list(first) == [B]
    settled = {e[1]: e[2] for e in meter.events if e[0] == "settle"}
    assert settled == {
        "hold-1": {"prompt_token_count": 3, "response_token_count": 9, "total_token_count": 3 + 9},
        "hold-2": {"prompt_token_count": 7, "response_token_count": 21, "total_token_count": 7 + 21},
    }


def test_FR_MTG_11_SEC_16_BQ_M2_1_concurrent_threads_each_settle_their_own_usage_once():
    meter, factory = Meter(), PerCallSessions()
    live = metered(factory, meter)
    texts = ["x" * n for n in range(1, 13)]
    with ThreadPoolExecutor(max_workers=6) as pool:
        assert all(audio == A + B for audio in pool.map(live.synthesize, texts))
    settles = [e for e in meter.events if e[0] == "settle"]
    assert len(settles) == len(meter.events) // 2 == len(texts)
    assert sorted(e[2]["prompt_token_count"] for e in settles) == list(range(1, 13))
    assert {e[1] for e in settles} == {e[1] for e in meter.events if e[0] == "reserve"}  # every hold closed once
    assert all(e[2]["response_token_count"] == 3 * e[2]["prompt_token_count"] for e in settles)  # never a mix


def test_FR_MTG_11_SEC_16_BQ_M2_1_the_provider_keeps_no_shared_last_usage_field():
    live = metered(Transport(GOOD_USAGE), Meter())
    live.synthesize(TEXT)
    assert not hasattr(live, "last_usage")
