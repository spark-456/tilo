"""FR-MTG-11 (M2b), SEC-16, BQ-M2-1: the Gemini Live voice's hook, backed by the production `SpendGuard` over the
in-memory ledger (the Firestore ledger is the same Protocol). One spoken reply is one unit: reserved before any session
opens, settled with the call's own usage, released when nothing reached the model. A capped uid, the replay-only switch,
an unreadable ledger or switch store and a uid with less than a unit left each refuse, and a fake session records that
the provider was never reached. No network, no SDK."""

from __future__ import annotations

from contextlib import asynccontextmanager
from types import SimpleNamespace as NS
from typing import Any

import pytest
from _sec16_lib import (
    JUDGE_A,
    JUDGE_B,
    ORG,
    DeadFlags,
    DeadLedger,
    SpyLedger,
    make_caps,
    make_guard,
    make_ledger,
    spend,
)
from tilo_metering.flags import InMemoryFlagStore
from tilo_providers.errors import NotConfigured, ProviderError
from tilo_providers.gemini_live_voice_adapter import GeminiLiveVoiceProvider
from tilo_providers.voice import LiveVoiceConfig, VoiceConfig

AUDIO = bytes(range(100))
UNIT = 100  # DEFAULT_CAPS unit_reserve_minor in `_sec16_lib`: a test number
LIVE = LiveVoiceConfig(True, "gemini-live-voice", "gemini-live-test", "Leda", "global", 5.0, 128, True)
CONFIG = VoiceConfig("google-cloud-tts", "chirp3-hd", "chirp-3-hd", "en-US-Chirp3-HD-Test", 24000, 400, 4000, live=LIVE)


class Sessions:
    """A fake Live session factory that counts how often the provider was reached."""

    def __init__(self, *, error: Exception | None = None, usage: Any = None) -> None:
        self.opened, self.error, self.usage = 0, error, usage

    def __call__(self, settings: Any):
        self.opened += 1
        factory = self

        class Session:
            async def send_client_content(self, **kwargs: Any) -> None:
                return None

            async def receive(self):
                if factory.error is not None:
                    raise factory.error
                content = NS(model_turn=NS(parts=[NS(inline_data=NS(data=AUDIO, mime_type="audio/pcm;rate=24000"))]))
                content.turn_complete = True
                yield NS(server_content=content, usage_metadata=factory.usage)

        @asynccontextmanager
        async def connect():
            yield Session()

        return connect()


def voice(sessions: Sessions, meter: Any) -> GeminiLiveVoiceProvider:
    return GeminiLiveVoiceProvider(CONFIG, fixtures_dir=None, session_factory=sessions, meter=meter)


def meter_for(guard: Any, uid: str = JUDGE_A, **kwargs: Any) -> Any:
    from tilo_api.spend_voice import LiveVoiceSpend  # noqa: PLC0415

    return LiveVoiceSpend(guard, uid=uid, run_id="m_meeting", org_id=ORG, unit_minor=UNIT, **kwargs)


def test_FR_MTG_11_SEC_16_BQ_M2_1_a_reply_is_one_unit_reserved_then_settled_on_the_uid_ledger():
    ledger = SpyLedger(make_ledger())
    sessions = Sessions(usage=NS(prompt_token_count=4, response_token_count=9, total_token_count=13))
    assert voice(sessions, meter_for(make_guard(ledger))).synthesize("The release is Friday.") == AUDIO
    assert ledger.writes == ["reserve", "settle"] and sessions.opened == 1
    assert (
        ledger.spent_minor(JUDGE_A) == ledger.settled_minor(JUDGE_A) == UNIT
    )  # unpriced: the whole unit, no hold left
    assert ledger.spent_minor(JUDGE_B) == 0


def test_FR_MTG_11_SEC_16_BQ_M2_1_a_priced_hook_settles_the_price_of_the_usage_it_was_given():
    ledger, seen = make_ledger(), []

    def price(usage: dict[str, int]) -> int | None:
        seen.append(dict(usage))
        return usage.get("total_token_count", 0) // 2

    sessions = Sessions(usage=NS(prompt_token_count=40, response_token_count=60, total_token_count=100))
    voice(sessions, meter_for(make_guard(ledger), price=price)).synthesize("Hello.")
    assert seen == [{"prompt_token_count": 40, "response_token_count": 60, "total_token_count": 100}]
    assert ledger.settled_minor(JUDGE_A) == 50
    voice(Sessions(), meter_for(make_guard(ledger), price=lambda usage: None)).synthesize("Hello.")  # unpriced
    assert ledger.settled_minor(JUDGE_A) == 50 + UNIT


def test_FR_MTG_11_SEC_16_BQ_M2_1_a_session_that_fails_before_any_audio_releases_the_hold_and_costs_nothing():
    ledger, sessions = SpyLedger(make_ledger()), Sessions(error=RuntimeError("connect failed"))
    with pytest.raises(ProviderError):
        voice(sessions, meter_for(make_guard(ledger))).synthesize("Hello.")
    assert ledger.writes == ["reserve", "release"] and sessions.opened == 1
    assert ledger.spent_minor(JUDGE_A) == 0


def test_FR_MTG_11_SEC_16_BQ_M2_1_a_capped_uid_is_refused_and_the_provider_is_never_reached():
    ledger = SpyLedger(make_ledger())
    spend(ledger, JUDGE_A, 1_000)  # the whole lifetime cap
    ledger.calls.clear()
    sessions = Sessions()
    with pytest.raises(NotConfigured):
        voice(sessions, meter_for(make_guard(ledger))).synthesize("Hello.")
    assert sessions.opened == 0 and ledger.writes == []
    other = Sessions()  # one uid's cap never refuses another uid
    assert voice(other, meter_for(make_guard(ledger), JUDGE_B)).synthesize("Hello.") == AUDIO and other.opened == 1


def test_FR_MTG_11_SEC_16_BQ_M2_1_less_than_a_unit_of_headroom_is_refused_not_overspent():
    ledger = make_ledger()
    spend(ledger, JUDGE_A, 1_000 - UNIT + 1)  # one paisa short of a whole unit
    sessions = Sessions()
    with pytest.raises(NotConfigured):
        voice(sessions, meter_for(make_guard(ledger))).synthesize("Hello.")
    assert sessions.opened == 0 and ledger.spent_minor(JUDGE_A) == 1_000 - UNIT + 1


def test_FR_MTG_11_SEC_16_BQ_M2_1_the_replay_only_switch_refuses_in_both_of_its_stores():
    ledger = make_ledger()
    ledger.trip_replay_only("a hard cap was reached")
    sessions = Sessions()
    with pytest.raises(NotConfigured):
        voice(sessions, meter_for(make_guard(ledger))).synthesize("Hello.")
    flags = InMemoryFlagStore()
    flags.set("replay_only", True, reason="operator")
    with pytest.raises(NotConfigured):
        voice(sessions, meter_for(make_guard(make_ledger(), flags))).synthesize("Hello.")
    assert sessions.opened == 0


@pytest.mark.parametrize("dead", ["ledger", "flags"])
def test_FR_MTG_11_SEC_16_BQ_M2_1_an_unreadable_ledger_or_switch_store_fails_closed(dead):
    guard = (
        make_guard(DeadLedger()) if dead == "ledger" else make_guard(make_ledger(), flags=DeadFlags(), caps=make_caps())
    )
    sessions = Sessions()
    with pytest.raises(NotConfigured):
        voice(sessions, meter_for(guard)).synthesize("Hello.")
    assert sessions.opened == 0
