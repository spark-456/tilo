"""FR-MTG-11 (M2b), SEC-16, BQ-M2-12, ADR-0042 decision 8: a refused Live reserve is TRANSIENT or PERMANENT.

The meter says why in a fixed word (`last_refusal`); the adapter raises `LiveVoiceRefused` (a `NotConfigured`, so every
caller that treats a refusal as permanent still does) with `transient` set from an allow-list of words. A transient
refusal never opens a session, never settles, and is bounded: `voice.live.max_consecutive_refusals` consecutive ones
in a row (config, not code) behave as permanent, and the meter is not asked again. Anything unknown is permanent: the
fail-closed default. Fake sessions and fake meters only: no network, no SDK session, no paid call."""

from __future__ import annotations

import pytest
from test_FR_MTG_11_gemini_live_voice import FAKE_TOKEN, FIXTURES, GOOD, REPO, TEXT, Transport, with_live
from test_FR_MTG_11_SEC_16_BQ_M2_1_live_voice_meter import Meter
from tilo_providers.config import ProviderConfigError
from tilo_providers.errors import LiveVoiceRefused, NotConfigured
from tilo_providers.gemini_live_voice_adapter import GeminiLiveVoiceProvider
from tilo_providers.voice import load_voice_config

TRANSIENT_WORDS = ["hold_open", "unavailable", "timeout", "unreachable", "rate_limited", "server_error", "no_token"]
PERMANENT_WORDS = [
    "capped",
    "replay_only",
    "meeting_limit",
    "not_attending",
    "not_configured",
    "unauthenticated",
    "forbidden",
    "invalid_request",
    "key_used",
    "no_hold",
    "refused",
    "off_contract",
    "malformed",
    "oversize",
]
MODELS = REPO / "config" / "models.yaml"


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    for name in ("LIVE", "TILO_RECORD", "K_SERVICE", "CLOUD_RUN_JOB", "GOOGLE_VERTEX_BASE_URL"):
        monkeypatch.delenv(name, raising=False)


class WordMeter(Meter):
    """A spend hook that answers from a script: a word is a refusal (None, `last_refusal` set to that word), "live" is
    a hold. It counts every `reserve`, so a test can see that the meter was not asked again."""

    def __init__(self, *script: str) -> None:
        super().__init__()
        self.script, self.asked = list(script), 0
        self.last_refusal: str | None = None

    def reserve(self):
        self.asked += 1
        word = self.script.pop(0) if self.script else "live"
        if word == "live":
            self.last_refusal = None
            return super().reserve()
        self.last_refusal = word
        self.events.append(("reserve", None))
        return None


def make(meter, transport=None, *, bound: int = 3):
    transport = transport or Transport(GOOD)
    config = with_live(price_approved=True, max_consecutive_refusals=bound)
    return GeminiLiveVoiceProvider(config, fixtures_dir=FIXTURES, session_factory=transport, meter=meter), transport


# -- the bound is config --------------------------------------------------------------------------------------------
def test_FR_MTG_11_BQ_M2_12_the_shipped_config_names_the_bound_and_no_code_does():
    real = load_voice_config(REPO / "config" / "voice.yaml", models_path=MODELS)
    assert real.live is not None and type(real.live.max_consecutive_refusals) is int
    assert 1 <= real.live.max_consecutive_refusals <= 10  # the loader accepts at most 10 transients in a row
    assert "max_consecutive_refusals" in (REPO / "config" / "voice.yaml").read_text(encoding="utf-8")


@pytest.mark.parametrize("bad", [0, -1, 11, 21, True, 2.5, "3", None])
def test_FR_MTG_11_BQ_M2_12_a_bad_bound_fails_start_up_loudly(tmp_path, bad):
    from test_FR_MTG_11_gemini_live_voice import write_voice_yaml

    path = write_voice_yaml(tmp_path, lambda v: v["live"].update(max_consecutive_refusals=bad))
    with pytest.raises(ProviderConfigError, match="max_consecutive_refusals"):
        load_voice_config(path, models_path=MODELS)


# -- the classification ---------------------------------------------------------------------------------------------
@pytest.mark.parametrize("word", TRANSIENT_WORDS)
def test_FR_MTG_11_BQ_M2_12_a_transient_refusal_is_transient_opens_no_session_and_the_next_reply_asks_again(word):
    meter = WordMeter(word, "live")
    voice, transport = make(meter)
    with pytest.raises(LiveVoiceRefused) as caught:
        voice.synthesize(TEXT)
    assert isinstance(caught.value, NotConfigured)  # every caller that read a refusal as permanent still can
    assert caught.value.transient is True and caught.value.reason == word
    assert transport.opened == 0 and meter.kinds() == ["reserve"] and meter.events == [("reserve", None)]
    assert voice.synthesize(TEXT)  # the next reply: Live resumes
    assert transport.opened == 1 and meter.kinds() == ["reserve", "reserve", "settle"]


@pytest.mark.parametrize("word", PERMANENT_WORDS)
def test_FR_MTG_11_BQ_M2_12_a_permanent_refusal_is_permanent_and_opens_no_session(word):
    meter = WordMeter(word)
    voice, transport = make(meter)
    with pytest.raises(LiveVoiceRefused) as caught:
        voice.synthesize(TEXT)
    assert caught.value.transient is False and caught.value.reason == word
    assert transport.opened == 0 and meter.kinds() == ["reserve"]


def test_FR_MTG_11_BQ_M2_12_a_meter_with_no_word_or_one_that_raises_is_permanent_the_fail_closed_default():
    for meter in (Meter(refuse=True), Meter(error=ConnectionError(f"ledger down {FAKE_TOKEN}"))):
        voice, transport = make(meter)
        with pytest.raises(NotConfigured) as caught:
            voice.synthesize(TEXT)
        assert getattr(caught.value, "transient", False) is False
        assert FAKE_TOKEN not in str(caught.value) and transport.opened == 0


def test_FR_MTG_11_BQ_M2_12_a_word_outside_the_vocabulary_is_permanent_and_never_reaches_the_message():
    meter = WordMeter(f"hold_open {FAKE_TOKEN}")  # a meter must not be able to put its own text in an error
    voice, transport = make(meter)
    with pytest.raises(LiveVoiceRefused) as caught:
        voice.synthesize(TEXT)
    assert caught.value.transient is False and caught.value.reason == "unknown"
    assert FAKE_TOKEN not in str(caught.value) and transport.opened == 0


# -- the bound ------------------------------------------------------------------------------------------------------
def test_FR_MTG_11_BQ_M2_12_n_consecutive_transients_behave_as_permanent_and_the_meter_is_not_asked_again():
    meter = WordMeter(*["hold_open"] * 10)
    voice, transport = make(meter, bound=3)
    transient = []
    for _ in range(3):
        with pytest.raises(LiveVoiceRefused) as caught:
            voice.synthesize(TEXT)
        transient.append(caught.value.transient)
    assert transient == [True, True, False]  # the Nth refusal in a row is the one that stops it
    for _ in range(4):  # stopped: no more questions to the meter, no session, still never raises anything else
        with pytest.raises(LiveVoiceRefused) as caught:
            voice.synthesize(TEXT)
        assert caught.value.transient is False
    assert meter.asked == 3 and transport.opened == 0 and meter.kinds() == ["reserve"] * 3


def test_FR_MTG_11_BQ_M2_12_a_successful_reserve_resets_the_run_of_transients():
    meter = WordMeter("hold_open", "live", "unavailable", "live", "timeout", "live")
    voice, transport = make(meter, bound=2)
    outcomes = []
    for _ in range(6):
        try:
            voice.synthesize(TEXT)
            outcomes.append("spoke")
        except LiveVoiceRefused as refused:
            outcomes.append(refused.transient)
    assert outcomes == [True, "spoke", True, "spoke", True, "spoke"]
    assert transport.opened == 3


def test_FR_MTG_11_BQ_M2_12_a_permanent_refusal_after_transients_stops_without_asking_again():
    meter = WordMeter("hold_open", "capped")
    voice, transport = make(meter, bound=5)
    with pytest.raises(LiveVoiceRefused) as first:
        voice.synthesize(TEXT)
    with pytest.raises(LiveVoiceRefused) as second:
        voice.synthesize(TEXT)
    assert (first.value.transient, second.value.transient) == (True, False)
    assert transport.opened == 0 and meter.asked == 2


def test_FR_MTG_11_BQ_M2_12_a_refused_reserve_never_reaches_the_provider_whatever_the_word():
    for word in TRANSIENT_WORDS + PERMANENT_WORDS:
        meter = WordMeter(word)
        voice, transport = make(meter)
        with pytest.raises(NotConfigured):
            list(voice.synthesize_stream(TEXT))
        assert transport.opened == 0 and transport.sent == [] and meter.kinds() == ["reserve"]
