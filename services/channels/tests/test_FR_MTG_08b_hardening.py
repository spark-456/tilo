"""FR-MTG-08b acceptance tests: hardening of `tilo_channels.meeting_followup` after the Opus security review of PR #440.

Seven points (ticket FR-MTG-08b), each pinned here and none weakening `test_FR_MTG_08_*`:

1. A commitment word is allowed only inside a verbatim repeat of a confirmed entry, never for the whole body.
2. The idempotency key is injective in its parts (a newline in a request id cannot forge another key).
3. A nudge goes to the confirmed work item's owner; a minutes owner that differs gets no nudge.
4. A missing or non-bool `flagged` (minutes, work item) reads as flagged (PE-21, fail closed).
5. The schema caps (240 characters per text; 8 / 30 / 60 entries) are enforced, before any work item is read.
6. A thread-less context fails closed in `_known`, `inbound_is_clean` and `Drafter.draft`.
7. Guards a mutation run showed unpinned: minutes.flagged on nudges, the safety screen of the model's answer, picks in
   the key, the subject in the screen, the SCREEN_CAP overflow flag, unconfirmed text never a source, a nudge repeating
   other items, the screen of a nudge's raw rest, the meeting title checked, a maximal minutes still checkable.

Uses the doubles of `_mtg08_lib`. No network, no paid call, no real mail.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import pytest
from _chn10_lib import INJECTION_MARKER, MemoryDraftStore, ScriptedModel, SpySafety, drafting_module, fresh_key
from _chn_wire1_lib import assert_nothing_sent, real_check_is_live
from _mtg08_lib import MAILBOX, OWNER, PEOPLE, World, addresses, item, make_world, needs_followup

PRIYA, SAM = PEOPLE["u_priya"], PEOPLE["u_sam"]


@pytest.fixture(autouse=True, scope="module")
def _real_check() -> None:
    real_check_is_live()


def assert_not_sendable(world: World, card: Any) -> None:
    if card is not None:
        assert card.status != "ready" and "send" not in card.options, (card.status, card.options)
    assert_nothing_sent(world.line)


def patch_minutes(world: World, change: Callable[[dict[str, Any]], None]) -> None:
    original = world.minutes.get

    def get(user_id: str, artifact_id: str, version: int) -> dict[str, Any] | None:
        doc = original(user_id, artifact_id, version)
        if doc is not None:
            change(doc)
        return doc

    world.minutes.get = get  # type: ignore[method-assign]


def patch_work_items(world: World, change: Callable[[str, dict[str, Any]], dict[str, Any]]) -> None:
    original = world.work_items.get

    def get(user_id: str, work_item_id: str) -> dict[str, Any] | None:
        doc = original(user_id, work_item_id)
        return change(work_item_id, dict(doc)) if doc is not None else None

    world.work_items.get = get  # type: ignore[method-assign]


def patch_meeting(world: World, change: Callable[[dict[str, Any]], None]) -> None:
    original = world.meetings.get

    def get(user_id: str, meeting_id: str) -> dict[str, Any] | None:
        doc = original(user_id, meeting_id)
        if doc is not None:
            change(doc)
        return doc

    world.meetings.get = get  # type: ignore[method-assign]


# ---------------------------------------------------------------------------
# 1. A commitment word is allowed only inside a verbatim repeat of a confirmed entry


@needs_followup
def test_FR_MTG_08b_a_commitment_word_in_a_confirmed_entry_does_not_license_it_in_the_rest_of_the_body() -> None:
    world = make_world(summary="Acme asked about a refund for the March order")
    world.model.minutes_body = lambda: f"Hi all,\n\n{world.summary}\n\nWe will refund Acme in full.\n\nBest,\nSarah"

    card = world.minutes_email("u_priya", "u_sam")

    assert_not_sendable(world, card)
    assert card is None or any(f.kind == "commitment" for f in card.findings)


@needs_followup
def test_FR_MTG_08b_a_confirmed_entry_repeated_inside_a_sentence_is_not_a_verbatim_repeat() -> None:
    world = make_world(summary="Acme asked about a refund for the March order")
    world.model.minutes_body = lambda: f"Hi all,\n\n{world.summary}, so we will refund Acme.\n\nBest,\nSarah"
    assert_not_sendable(world, world.minutes_email("u_priya"))


@needs_followup
def test_FR_MTG_08b_the_verbatim_repeat_of_a_confirmed_entry_with_a_commitment_word_stays_sendable() -> None:
    """Control: the faithful body repeats the confirmed summary, refund and all, on its own line."""
    world = make_world(
        summary="Acme asked about a refund for the March order",
        decisions=[(f"Offer partners a discount as agreed {fresh_key()}", "verified")],
    )
    card = world.minutes_email("u_priya", "u_sam")
    assert card is not None and card.status == "ready" and card.findings == ()
    assert "refund" in card.body and "discount" in card.body


@needs_followup
def test_FR_MTG_08b_a_nudge_for_a_commitment_item_repeats_it_verbatim_and_adds_no_commitment() -> None:
    items = [item(1, "Send the refund form to Acme", owner="u_priya")]
    world = make_world(items)
    (card,) = world.nudges()
    assert card.status == "ready" and items[0].text in card.body

    invented = make_world(items)
    invented.model.nudge_body = lambda it: f"Hi,\n\nA reminder: {it.text}\n\nWe will refund you in full.\n\nSarah"
    cards = invented.nudges()
    assert all(c.status != "ready" and "send" not in c.options for c in cards)
    assert_nothing_sent(invented.line)


# ---------------------------------------------------------------------------
# 2. The idempotency key is injective


@needs_followup
def test_FR_MTG_08b_a_request_id_holding_a_newline_and_an_address_cannot_forge_another_request_key() -> None:
    world = make_world()
    first = world.minutes_email("u_priya", "u_sam", request_id="r")
    assert first is not None and sorted(addresses(first)) == sorted([PRIYA, SAM])

    forged = world.minutes_email("u_sam", request_id=f"r\n{PRIYA}")

    assert forged is not None and forged.card_id != first.card_id
    assert addresses(forged) == (SAM,)
    assert len(world.model.minutes_prompts()) == 2, "a different request is a new draft"


@needs_followup
def test_FR_MTG_08b_the_picked_attendees_are_part_of_the_key() -> None:
    world = make_world()
    one = world.minutes_email("u_priya", request_id="r")
    other = world.minutes_email("u_sam", request_id="r")
    assert one is not None and other is not None and one.card_id != other.card_id
    assert addresses(one) == (PRIYA,) and addresses(other) == (SAM,)


# ---------------------------------------------------------------------------
# 3. A nudge goes to the confirmed work item's owner


@needs_followup
def test_FR_MTG_08b_a_minutes_owner_that_differs_from_the_work_item_owner_gets_no_nudge() -> None:
    world = make_world()
    patch_work_items(world, lambda wid, doc: {**doc, "owner": "u_sam"} if wid == "wi_ai1" else doc)

    cards = world.nudges()

    assert [addresses(c) for c in cards] == [(SAM,)], "ai1 (minutes: Priya, work item: Sam) fails closed"
    assert world.items[0].key not in cards[0].body
    assert world.minutes_email("u_priya") is not None
    assert not any(world.items[0].text in p for p in world.model.minutes_prompts())
    assert PRIYA not in {a for c in cards for a in addresses(c)}


@needs_followup
def test_FR_MTG_08b_the_nudge_address_is_the_work_item_owners_when_both_agree() -> None:
    world = make_world()
    assert {addresses(c) for c in world.nudges()} == {(PRIYA,), (SAM,)}


# ---------------------------------------------------------------------------
# 4. Missing or non-bool `flagged` reads as flagged


@needs_followup
@pytest.mark.parametrize(
    "value", ["absent", None, 0, "false", "no"], ids=["absent", "none", "zero", "false_str", "no_str"]
)
def test_FR_MTG_08b_a_work_item_flagged_that_is_not_false_reads_as_flagged(value: Any) -> None:
    world = make_world()

    def change(_: str, doc: dict[str, Any]) -> dict[str, Any]:
        doc.pop("flagged", None)
        return doc if value == "absent" else {**doc, "flagged": value}

    patch_work_items(world, change)
    cards = world.nudges()
    email = world.minutes_email("u_priya")

    assert len(cards) == 2 and all("safety_flag" in c.modifiers for c in cards)
    assert email is not None and "safety_flag" in email.modifiers


@needs_followup
@pytest.mark.parametrize("value", ["absent", None, 0, "false"], ids=["absent", "none", "zero", "false_str"])
def test_FR_MTG_08b_minutes_flagged_that_is_not_false_reads_as_flagged(value: Any) -> None:
    world = make_world()

    def change(doc: dict[str, Any]) -> None:
        doc.pop("flagged", None)
        if value != "absent":
            doc["flagged"] = value

    patch_minutes(world, change)
    email = world.minutes_email("u_priya")
    cards = world.nudges()

    assert email is not None and "safety_flag" in email.modifiers
    assert len(cards) == 2 and all("safety_flag" in c.modifiers for c in cards)


@needs_followup
def test_FR_MTG_08b_explicitly_unflagged_minutes_and_items_carry_no_safety_flag() -> None:
    world = make_world()
    email, cards = world.minutes_email("u_priya"), world.nudges()
    assert email is not None and "safety_flag" not in email.modifiers
    assert len(cards) == 2 and all("safety_flag" not in c.modifiers for c in cards)


# ---------------------------------------------------------------------------
# 5. The schema caps are enforced, before any work item is read


def _filler(n: int, key: str = "") -> str:
    text = (f"{key} " if key else "") + "alpha beta gamma delta " * 20
    return text[:n].rstrip()


def _many_items(count: int) -> list[Any]:
    return [item(n, f"Task {fresh_key()}", owner="u_priya") for n in range(1, count + 1)]


@needs_followup
def test_FR_MTG_08b_more_action_items_than_the_schema_allows_reads_nothing_and_drafts_nothing() -> None:
    world = make_world(_many_items(61))
    assert world.minutes_email("u_priya") is None
    assert world.nudges() == []
    assert world.work_items.calls == [], "the count is checked before any work item is read"
    assert world.untouched()


@needs_followup
def test_FR_MTG_08b_more_decisions_or_summary_points_than_the_schema_allows_drafts_nothing() -> None:
    many = make_world(decisions=[(f"Decision {fresh_key()}", "verified") for _ in range(31)])
    assert many.minutes_email("u_priya") is None and many.nudges() == []
    assert many.work_items.calls == [] and many.untouched()

    wide = make_world()
    patch_minutes(
        wide, lambda doc: doc["summary"].extend({"text": f"Point {fresh_key()}", "evidence": []} for _ in range(8))
    )
    assert wide.minutes_email("u_priya") is None and wide.nudges() == []
    assert wide.work_items.calls == [] and wide.untouched()


@needs_followup
def test_FR_MTG_08b_a_text_is_cut_to_240_characters_and_its_rest_is_screened_not_shown() -> None:
    world = make_world()
    tail = "tailmarkerofthesummary"

    def change(doc: dict[str, Any]) -> None:
        doc["summary"][0]["text"] = _filler(300, world.summary_key) + " " + tail

    patch_minutes(world, change)
    card = world.minutes_email("u_priya")

    assert card is not None
    (prompt,) = world.model.minutes_prompts()
    assert world.summary_key in prompt and tail not in prompt
    assert world.line.bench.rig.safety.screened(tail), "the raw rest of a cut text is screened"


@needs_followup
def test_FR_MTG_08b_the_raw_rest_of_a_cut_nudge_text_is_screened_and_flags_the_card() -> None:
    world = make_world()
    target = world.items[0]

    def change(doc: dict[str, Any]) -> None:
        doc["action_items"][0]["text"] = _filler(260, target.key) + f" {INJECTION_MARKER}"

    patch_minutes(world, change)
    cards = {addresses(c): c for c in world.nudges()}

    assert world.line.bench.rig.safety.screened(INJECTION_MARKER)
    assert all(INJECTION_MARKER not in p for p in world.model.nudge_prompts()), "the rest never reaches the model"
    assert "safety_flag" in cards[(PRIYA,)].modifiers and "safety_flag" not in cards[(SAM,)].modifiers


@needs_followup
def test_FR_MTG_08b_a_maximal_schema_valid_minutes_still_has_a_checkable_faithful_body() -> None:
    """8 summary points, 30 decisions and 60 open items of 240 characters (about 23.5k) must not fail closed."""
    summary_head = _filler(225)
    items = [item(n, "x", owner="u_priya") for n in range(1, 61)]
    for spec in items:
        spec.text = _filler(228, spec.key)
    decisions = [(_filler(238, fresh_key()), "verified") for _ in range(30)]
    world = make_world(items, decisions=decisions, summary=summary_head)
    extra = [_filler(238, fresh_key()) for _ in range(7)]
    patch_minutes(world, lambda doc: doc["summary"].extend({"text": t, "evidence": []} for t in extra))
    lines = ["Hi all,", world.summary, *extra, *[t for t, _ in decisions], *[i.text for i in items], "Best,"]
    body = "\n".join(lines)
    assert 20_000 < len(body) < 30_000
    world.model.minutes_body = lambda: body

    card = world.minutes_email("u_priya")

    assert card is not None and card.status == "ready" and card.findings == (), card and card.findings[:2]
    assert len(card.body) == len(body)


# ---------------------------------------------------------------------------
# 6. A thread-less context fails closed


class _SpyReader:
    def __init__(self) -> None:
        self.calls: list[Any] = []

    def get_thread(self, user_id: str, thread_id: Any) -> dict[str, Any]:
        self.calls.append(thread_id)
        return {"messages": []}


def test_FR_MTG_08b_inbound_is_clean_is_false_for_no_thread_and_reads_nothing() -> None:
    from tilo_channels.autopilot_inbound import inbound_is_clean

    reader = _SpyReader()
    assert inbound_is_clean(reader, OWNER, None, "<m@mail.example>") is False  # type: ignore[arg-type]
    assert reader.calls == []


def test_FR_MTG_08b_the_drafter_refuses_no_thread_before_reading_or_calling_anything() -> None:
    reader, model, safety = _SpyReader(), ScriptedModel(), SpySafety()
    drafter = drafting_module().Drafter(
        reader=reader, model=model, safety=safety, drafts=MemoryDraftStore(), clock=lambda: 0.0
    )
    with pytest.raises(ValueError):
        drafter.draft(OWNER, instruction_id="i1", thread_id=None, instruction="Reply", mailbox=MAILBOX)
    assert reader.calls == [] and model.requests == [] and safety.texts == []


def test_FR_MTG_08b_known_recipients_of_a_thread_less_context_read_no_thread() -> None:
    from tilo_channels.autopilot import DraftContext

    world = make_world()
    reader = _SpyReader()
    ap = world.line.ap
    ap._reader = reader
    context = DraftContext("i1", None, "Follow up", MAILBOX, "new")
    known = ap._known(OWNER, context)
    assert isinstance(known, set) and reader.calls == []


# ---------------------------------------------------------------------------
# 7. Guards a mutation run showed unpinned


@needs_followup
def test_FR_MTG_08b_flagged_minutes_make_every_nudge_card_safety_flagged() -> None:
    world = make_world(minutes_flagged=True)
    cards = world.nudges()
    assert len(cards) == 2 and all("safety_flag" in c.modifiers for c in cards)


@needs_followup
def test_FR_MTG_08b_a_model_answer_the_safety_provider_flags_is_never_a_card() -> None:
    world = make_world()
    world.model.minutes_body = lambda: world.faithful_minutes_body() + f"\n{INJECTION_MARKER}"
    world.model.nudge_body = lambda it: world.faithful_nudge_body(it) + f"\n{INJECTION_MARKER}"
    assert world.minutes_email("u_priya") is None
    assert world.nudges() == []
    assert world.of_type("artifact.created") == [] and world.of_type("approval.requested") == []
    assert_nothing_sent(world.line)


@needs_followup
def test_FR_MTG_08b_the_meeting_title_is_screened_with_the_prompt() -> None:
    world = make_world()
    patch_meeting(world, lambda doc: doc.update(title=f"Plan {INJECTION_MARKER}"))
    card = world.minutes_email("u_priya")
    assert world.line.bench.rig.safety.screened(INJECTION_MARKER)
    assert card is None or "safety_flag" in card.modifiers


@needs_followup
def test_FR_MTG_08b_text_beyond_the_screen_budget_flags_the_card_and_a_text_within_it_does_not() -> None:
    def card_of(sizes: list[int]) -> Any:
        world = make_world()

        def change(doc: dict[str, Any]) -> None:
            for point, size in zip(doc["summary"], sizes, strict=False):
                point["text"] = point["text"] + " " + "w" * size

        patch_minutes(world, change)
        card = world.minutes_email("u_priya")
        assert card is not None
        return card

    assert "safety_flag" not in card_of([50_000]).modifiers
    assert "safety_flag" not in card_of([60_000]).modifiers, "one rest of 60k is within the 100k budget"
    wide = make_world()

    def change(doc: dict[str, Any]) -> None:
        base = doc["summary"][0]
        doc["summary"] = [{**base, "text": base["text"] + " " + "w" * 60_000} for _ in range(2)]

    patch_minutes(wide, change)
    flagged = wide.minutes_email("u_priya")
    assert flagged is not None and "safety_flag" in flagged.modifiers, "two 60k rests exceed SCREEN_CAP"


@needs_followup
def test_FR_MTG_08b_a_fact_only_an_unconfirmed_text_holds_is_never_supported() -> None:
    items = [
        item(1, "Send the rate sheet to Acme", owner="u_priya"),
        item(2, "Quote Acme 4711 for the pallets and offer a refund", owner="u_sam", work="proposed", confirmed=None),
    ]
    world = make_world(items)
    world.model.minutes_body = lambda: world.faithful_minutes_body() + "\nThe code is 4711."
    assert_not_sendable(world, world.minutes_email("u_priya"))

    again = make_world(items)
    again.model.minutes_body = lambda: again.faithful_minutes_body() + "\nWe will offer a refund."
    assert_not_sendable(again, again.minutes_email("u_priya"))


@needs_followup
@pytest.mark.parametrize("other", ["decision", "item", "summary"])
def test_FR_MTG_08b_a_nudge_that_repeats_another_part_of_the_minutes_is_never_sendable(other: str) -> None:
    world = make_world()
    extra = {
        "decision": world.confirmed_decisions()[0],
        "item": world.items[1].text,
        "summary": world.summary,
    }[other]
    world.model.nudge_body = lambda it: world.faithful_nudge_body(it) + f"\nAlso: {extra}"
    ready = [c for c in world.nudges() if c.status == "ready"]
    if other == "item":  # item 2's own nudge may repeat its own text; item 1's nudge repeating item 2 is refused
        assert not [c for c in ready if world.items[0].key in c.body]
    else:
        assert ready == []
    assert_nothing_sent(world.line)


@needs_followup
def test_FR_MTG_08b_a_meeting_title_with_a_commitment_word_gets_the_generic_subject() -> None:
    world = make_world()
    patch_meeting(world, lambda doc: doc.update(title="Free refund for every partner"))
    card = world.minutes_email("u_priya")
    assert card is not None and card.status == "ready" and card.subject == "Meeting minutes"


@needs_followup
def test_FR_MTG_08b_a_meeting_title_with_a_mixed_script_word_gets_the_generic_subject() -> None:
    world = make_world()
    patch_meeting(world, lambda doc: doc.update(title="Launch plan sуnc"))  # Cyrillic u
    card = world.minutes_email("u_priya")
    assert card is not None and card.subject == "Meeting minutes"


@needs_followup
def test_FR_MTG_08b_an_ordinary_meeting_title_stays_in_the_subject() -> None:
    world = make_world()
    patch_meeting(world, lambda doc: doc.update(title="Q3 launch plan sync"))
    card = world.minutes_email("u_priya")
    assert card is not None and card.subject == "Minutes: Q3 launch plan sync"
