"""FR-CHN-06 acceptance: WhatsApp keywords STOP AUTOPILOT, PAUSE and UNSUBSCRIBE (PRD 11.1 "Keywords",
PRD 11.6 FR-CHN-06: "Each works in <= 5 s and is confirmed"; PRD 10.4 "Kill switches"; NFR-07
"Pause all or STOP AUTOPILOT -> effective <= 2 s and <= 5 s"; PRD 16.2 "Spoofed WhatsApp commands":
bound numbers only).

Public interface under test: `tilo_channels.keywords` (pinned in API.md next to this file), driven
through injected fakes: number bindings, the control plane (the tilo-api client in production),
the WhatsApp sender and a clock. One test also drives it end to end behind the signature-verified
webhook of FR-CHN-02. The package does not exist yet, so every test fails today with
ModuleNotFoundError.

Effects, from the PRD (PRD 11.1 keyword list, 10.4 kill switches):
- STOP AUTOPILOT: every one of the user's policies goes to L1 (`stop_all_autopilot`, which the
  control plane records as one `policy.changed` change=stop_all level=L1 per policy). Agents keep
  running: that is PAUSE's job ("Pause all stops the agents too").
- PAUSE: Pause all (`pause_all`, recorded as `world.paused` reason=pause_all channel=whatsapp).
  Policies are untouched.
- UNSUBSCRIBE: WhatsApp off (`unsubscribe_whatsapp`): Tilo stops messaging that number. Policies and
  runs are untouched.

Defaults the PRD does not state, chosen here and listed in the ticket report:
- Matching is the whole message, case-insensitive, with leading, trailing and repeated inner
  whitespace ignored. A keyword inside a longer sentence is NOT a keyword (a person writing "please
  pause the garden project" must not freeze every run), and bare STOP is not a keyword (PRD lists
  STOP AUTOPILOT only).
- A number that is not bound is not obeyed and gets no reply from this handler (`handled` is False,
  so the dispatcher can send the opt-in instructions, FR-CHN-03).
- The confirmation is sent only after the effect succeeded, to the number that sent the keyword,
  once. After UNSUBSCRIBE the confirmation is still sent (a final opt-out acknowledgement).
- If the control plane fails the effect is not claimed: `applied` and `confirmed` are False and the
  handler does not raise.
"""

from __future__ import annotations

import time

import pytest
from _channels_lib import (
    NUMBER_A,
    NUMBER_B,
    NUMBER_UNBOUND,
    T0,
    USER_A,
    USER_B,
    FakeBindings,
    FakeClock,
    FakeControls,
    FakeSender,
    MemoryDedupeStore,
    delivery_body,
    image_message,
    make_app_secret,
    sign,
    text_message,
    wamid,
)
from hypothesis import given, settings
from hypothesis import strategies as st
from tilo_channels.keywords import KeywordHandler, parse_keyword
from tilo_channels.whatsapp import InboundMessage, WhatsAppWebhook

STOP = "STOP AUTOPILOT"
PAUSE = "PAUSE"
UNSUB = "UNSUBSCRIBE"
EFFECT_METHOD = {STOP: "stop_all_autopilot", PAUSE: "pause_all", UNSUB: "unsubscribe_whatsapp"}
CONFIRM_WORD = {STOP: "autopilot", PAUSE: "pause", UNSUB: "unsubscribe"}
ALL_METHODS = set(EFFECT_METHOD.values())
LIMIT_S = 5.0
WHITESPACE = " \t\n\r"


def inbound(text, sender=NUMBER_A, *, ts=T0 + 30, n=1, kind="text"):
    return InboundMessage(message_id=wamid(n), sender=sender, timestamp=ts, kind=kind, text=text)


@pytest.fixture()
def handler(bindings, controls, sender):
    return KeywordHandler(bindings=bindings, controls=controls, sender=sender)


# ---------------------------------------------------------------------------
# Recognition.


@pytest.mark.parametrize("keyword", [STOP, PAUSE, UNSUB])
def test_FR_CHN_06_parse_keyword_recognises_each_canonical_keyword(keyword):
    assert parse_keyword(keyword) == keyword


@pytest.mark.parametrize(
    "text, expected",
    [
        ("stop autopilot", STOP),
        ("Stop Autopilot", STOP),
        ("  STOP AUTOPILOT  ", STOP),
        ("STOP   AUTOPILOT", STOP),
        ("stop\tautopilot\n", STOP),
        ("pause", PAUSE),
        ("Pause\n", PAUSE),
        ("unsubscribe", UNSUB),
        (" UnSubscribe ", UNSUB),
    ],
)
def test_FR_CHN_06_parse_keyword_ignores_case_and_surrounding_or_repeated_whitespace(text, expected):
    assert parse_keyword(text) == expected


@pytest.mark.parametrize(
    "text",
    [
        None,
        "",
        "   ",
        "STOP",
        "stop it",
        "AUTOPILOT",
        "STOPAUTOPILOT",
        "STOP AUTOPILOT NOW",
        "please STOP AUTOPILOT",
        "PAUSED",
        "PAUSE ALL",
        "please pause the garden project",
        "can you pause the report until Monday?",
        "UNSUBSCRIBE ME",
        "I will not unsubscribe",
        "what does STOP AUTOPILOT do?",
        "STOP AUTOPILOT\nPAUSE",
    ],
)
def test_FR_CHN_06_parse_keyword_requires_the_whole_message_to_be_the_keyword(text):
    assert parse_keyword(text) is None


@st.composite
def _keyword_variants(draw):
    keyword = draw(st.sampled_from([STOP, PAUSE, UNSUB]))
    gap = st.text(alphabet=WHITESPACE, min_size=1, max_size=4)
    margin = st.text(alphabet=WHITESPACE, max_size=3)
    words = ["".join(c.upper() if draw(st.booleans()) else c.lower() for c in w) for w in keyword.split(" ")]
    text = words[0]
    for word in words[1:]:
        text += draw(gap) + word
    return keyword, draw(margin) + text + draw(margin)


@settings(max_examples=100, deadline=None)
@given(_keyword_variants())
def test_FR_CHN_06_property_any_casing_and_whitespace_of_a_keyword_parses_to_it(case):
    keyword, text = case
    assert parse_keyword(text) == keyword


@settings(max_examples=100, deadline=None)
@given(
    keyword=st.sampled_from([STOP, PAUSE, UNSUB]),
    extra=st.text(alphabet=st.characters(min_codepoint=33, max_codepoint=126), min_size=1, max_size=8),
    before=st.booleans(),
)
def test_FR_CHN_06_property_a_keyword_with_any_extra_word_is_not_a_keyword(keyword, extra, before):
    text = f"{extra} {keyword}" if before else f"{keyword} {extra}"
    assert parse_keyword(text) is None


# ---------------------------------------------------------------------------
# Effect, confirmation and the 5 s bound for a bound number.


@pytest.mark.parametrize("keyword", [STOP, PAUSE, UNSUB])
def test_FR_CHN_06_keyword_from_a_bound_number_takes_effect_for_that_user_only(handler, controls, keyword):
    result = handler.handle(inbound(keyword))
    assert result.handled is True
    assert result.keyword == keyword
    assert result.applied is True
    assert controls.methods() == [EFFECT_METHOD[keyword]]
    assert [c[1] for c in controls.calls] == [USER_A]


@pytest.mark.parametrize("keyword", [STOP, PAUSE, UNSUB])
def test_FR_CHN_06_the_other_bound_user_is_resolved_from_their_own_number(handler, controls, keyword):
    handler.handle(inbound(keyword, sender=NUMBER_B))
    assert [c[1] for c in controls.calls] == [USER_B]


@pytest.mark.parametrize("keyword", [STOP, PAUSE, UNSUB])
def test_FR_CHN_06_each_keyword_touches_only_its_own_effect(handler, controls, keyword):
    handler.handle(inbound(keyword))
    assert set(controls.methods()).isdisjoint(ALL_METHODS - {EFFECT_METHOD[keyword]})


def test_FR_CHN_06_control_plane_calls_are_attributed_to_the_whatsapp_channel(handler, controls):
    handler.handle(inbound(STOP, n=1))
    handler.handle(inbound(PAUSE, n=2))
    assert controls.channels == ["whatsapp", "whatsapp"]


@pytest.mark.parametrize("keyword", [STOP, PAUSE, UNSUB])
def test_FR_CHN_06_keyword_is_confirmed_back_to_the_sender_once_after_the_effect(handler, controls, sender, keyword):
    result = handler.handle(inbound(keyword))
    assert result.confirmed is True
    assert len(sender.sent) == 1
    to, body, sent_at = sender.sent[0]
    assert to == NUMBER_A
    assert CONFIRM_WORD[keyword] in body.lower()
    assert sent_at >= controls.calls[0][2], "the confirmation must not precede the effect it reports"


@pytest.mark.parametrize("keyword", [STOP, PAUSE, UNSUB])
def test_FR_CHN_06_effect_and_confirmation_land_within_5_seconds_of_the_message(
    handler, controls, sender, clock, keyword
):
    ts = int(clock())
    handler.handle(inbound(keyword, ts=ts))
    (_, _, effect_at) = controls.calls[0]
    (_, _, confirm_at) = sender.sent[0]
    assert effect_at - ts <= LIMIT_S
    assert confirm_at - ts <= LIMIT_S


@pytest.mark.parametrize("keyword", [STOP, PAUSE, UNSUB])
def test_FR_CHN_06_handler_adds_no_real_delay_of_its_own(handler, keyword):
    start = time.perf_counter()
    handler.handle(inbound(keyword))
    assert time.perf_counter() - start < LIMIT_S


def test_FR_CHN_06_keyword_variants_behave_like_the_canonical_keyword(handler, controls):
    handler.handle(inbound("  stop   autopilot ", n=1))
    handler.handle(inbound("pause", n=2))
    handler.handle(inbound("Unsubscribe", n=3))
    assert controls.methods() == ["stop_all_autopilot", "pause_all", "unsubscribe_whatsapp"]


# ---------------------------------------------------------------------------
# What is NOT obeyed.


@pytest.mark.parametrize("keyword", [STOP, PAUSE, UNSUB])
def test_FR_CHN_06_unbound_number_is_not_obeyed_and_not_answered(handler, controls, sender, keyword):
    result = handler.handle(inbound(keyword, sender=NUMBER_UNBOUND))
    assert result.handled is False
    assert result.applied is False
    assert controls.calls == []
    assert sender.sent == []


@pytest.mark.parametrize(
    "text", ["hello", "please pause the garden project", "stop", "UNSUBSCRIBE ME", "what is STOP AUTOPILOT?", None]
)
def test_FR_CHN_06_ordinary_messages_from_a_bound_number_are_left_to_the_dispatcher(handler, controls, sender, text):
    result = handler.handle(inbound(text))
    assert result.handled is False
    assert result.keyword is None
    assert controls.calls == []
    assert sender.sent == []


def test_FR_CHN_06_non_text_message_is_never_a_keyword(handler, controls, sender):
    message = InboundMessage(message_id=wamid(1), sender=NUMBER_A, timestamp=T0 + 30, kind="image", text=None)
    assert handler.handle(message).handled is False
    assert controls.calls == [] and sender.sent == []


@pytest.mark.parametrize("keyword", [STOP, PAUSE, UNSUB])
def test_FR_CHN_06_failed_effect_is_not_claimed_and_does_not_raise(handler, controls, sender, keyword):
    controls.fail.add(EFFECT_METHOD[keyword])
    result = handler.handle(inbound(keyword))
    assert result.handled is True
    assert result.applied is False
    assert result.confirmed is False
    assert controls.calls == []


# ---------------------------------------------------------------------------
# End to end behind the signed webhook (FR-CHN-02 + FR-CHN-06).


def _wired(*, bound=None):
    clock = FakeClock(T0 + 60)
    secret = make_app_secret()
    bindings = FakeBindings(bound)
    controls = FakeControls(clock)
    sender = FakeSender(clock)
    keywords = KeywordHandler(bindings=bindings, controls=controls, sender=sender)
    hook = WhatsAppWebhook(
        app_secret=secret, now=clock, store=MemoryDedupeStore(clock), handler=keywords.handle, max_age_s=300
    )
    return hook, secret, controls, sender, clock


def _post(hook, secret, messages):
    body = delivery_body(messages)
    return hook.receive(body, sign(secret, body))


@pytest.mark.parametrize("keyword", [STOP, PAUSE, UNSUB])
def test_FR_CHN_06_signed_webhook_delivery_takes_effect_and_confirms_within_5_seconds(keyword):
    hook, secret, controls, sender, clock = _wired()
    ts = int(clock())
    response = _post(hook, secret, [text_message(wamid(1), NUMBER_A, ts, keyword)])
    assert response.status == 200
    assert controls.methods() == [EFFECT_METHOD[keyword]]
    assert controls.calls[0][2] - ts <= LIMIT_S
    assert len(sender.sent) == 1
    assert sender.sent[0][0] == NUMBER_A
    assert sender.sent[0][2] - ts <= LIMIT_S


def test_FR_CHN_06_duplicate_keyword_delivery_takes_effect_and_confirms_once():
    hook, secret, controls, sender, clock = _wired()
    message = text_message(wamid(1), NUMBER_A, int(clock()), STOP)
    for _ in range(3):
        _post(hook, secret, [message])
    assert controls.methods() == ["stop_all_autopilot"]
    assert len(sender.sent) == 1


def test_FR_CHN_06_forged_keyword_delivery_has_no_effect_even_from_a_bound_number():
    hook, secret, controls, sender, clock = _wired()
    body = delivery_body([text_message(wamid(1), NUMBER_A, int(clock()), STOP)])
    response = hook.receive(body, sign(make_app_secret(), body))
    assert response.status == 401
    assert controls.calls == []
    assert sender.sent == []


def test_FR_CHN_06_keywords_in_one_delivery_take_effect_in_the_order_sent():
    hook, secret, controls, _sender, clock = _wired()
    ts = int(clock())
    _post(
        hook,
        secret,
        [
            text_message(wamid(3), NUMBER_A, ts - 1, UNSUB),
            text_message(wamid(1), NUMBER_A, ts - 3, PAUSE),
            text_message(wamid(2), NUMBER_A, ts - 2, STOP),
        ],
    )
    assert controls.methods() == ["pause_all", "stop_all_autopilot", "unsubscribe_whatsapp"]


def test_FR_CHN_06_keyword_from_an_unbound_number_through_the_webhook_does_nothing():
    hook, secret, controls, sender, clock = _wired()
    _post(hook, secret, [text_message(wamid(1), NUMBER_UNBOUND, int(clock()), PAUSE)])
    assert controls.calls == []
    assert sender.sent == []


def test_FR_CHN_06_non_keyword_and_non_text_messages_through_the_webhook_do_nothing():
    hook, secret, controls, sender, clock = _wired()
    ts = int(clock())
    _post(
        hook,
        secret,
        [text_message(wamid(1), NUMBER_A, ts, "pause the garden report"), image_message(wamid(2), NUMBER_A, ts)],
    )
    assert controls.calls == []
    assert sender.sent == []
