"""FR-MTG-08 property tests (PRD acceptance: "Property test (FR-HIL-04): no outbox entry without an approving
`approval.resolved`; 0 invented commitments"). The interface is pinned in test_FR_MTG_08_minutes_email_and_nudges.py.

1. FR-HIL-04: over any sequence of drafting, answers (none, wrong option, wrong channel, a policy, another person,
   another card's, the Owner's approve) and clock ticks, the outbox holds an entry only for a card whose gate the Owner
   approved, and Gmail has sent no more than those, whatever the autonomy policy says (it answers L2 for everything).
2. 0 invented commitments: over any mix of action items (verified or not, with or without a work item, `open`,
   `proposed`, `done`, `dropped`, confirmed by the Owner or by someone else, of this meeting or another, with or without
   an assignee or an address), exactly the confirmed open items get a nudge, each to its own assignee, and the minutes
   email names exactly those items: nothing else reaches a model prompt, a card body or an address.
"""

from __future__ import annotations

from typing import Any

import pytest
from _chn10_lib import fresh_key
from _chn_wire1_lib import OTHER_PERSON, real_check_is_live, requested_part, resolved, try_send
from _mtg08_lib import PEOPLE, Item, World, addresses, item, make_world, needs_followup
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

pytestmark = pytest.mark.filterwarnings("ignore")
SLOW = settings(max_examples=25, deadline=None, suppress_health_check=list(HealthCheck), derandomize=True)
PERSONS = ["u_priya", "u_sam", "u_lena", "u_sarah"]
APPROVALS = ["none", "hold", "whatsapp", "policy", "someone_else", "another_card", "approve"]


@pytest.fixture(autouse=True, scope="module")
def _real_check() -> None:
    real_check_is_live()


# ---------------------------------------------------------------------------
# 1. FR-HIL-04


operation = st.one_of(
    st.tuples(st.just("minutes"), st.lists(st.sampled_from(PERSONS), min_size=0, max_size=4), st.integers(0, 3)),
    st.tuples(st.just("nudges"), st.just(()), st.integers(0, 3)),
    st.tuples(st.just("send"), st.sampled_from(APPROVALS), st.integers(0, 30)),
    st.tuples(st.just("tick"), st.just(()), st.integers(1, 3600)),
)


def _approval_for(world: World, card: Any, other: Any, kind: str) -> dict | None:
    if kind == "none":
        return None
    requested = requested_part(world.line, card)
    world.line.advance(2)
    if kind == "another_card" and other is not None:
        return resolved(requested_part(world.line, other), world.line)
    kw = {
        "hold": {"option": "hold"},
        "whatsapp": {"channel": "whatsapp"},
        "policy": {"by": "policy", "ref": "pol_autopilot_l2"},
        "someone_else": {"ref": OTHER_PERSON},
    }.get(kind, {})
    return resolved(requested, world.line, **kw)


@needs_followup
@given(ops=st.lists(operation, min_size=1, max_size=14), level=st.sampled_from(["L1", "L2"]))
@SLOW
def test_FR_MTG_08_property_no_outbox_entry_without_an_approving_approval_resolved(ops: list, level: str) -> None:
    world = make_world(level=level)
    cards: list[Any] = []
    approved: set[str] = set()  # outbox ids whose gate the Owner approved (the only entries that may exist)

    for kind, arg, extra in ops:
        if kind == "minutes":
            card = world.minutes_email(*arg, request_id=f"m{extra}")
            cards += [card] if card is not None else []
        elif kind == "nudges":
            cards += world.nudges(request_id=f"n{extra}")
        elif kind == "tick":
            world.line.advance(extra)
        elif cards:
            card = cards[extra % len(cards)]
            other = cards[(extra + 1) % len(cards)]
            approval = _approval_for(world, card, other, arg)
            outcome = try_send(world.line.ap, card.card_id, approval)
            if arg == "approve" and outcome is not None and outcome.status in ("queued", "scheduled"):
                approved.add(card.outbox_id)
        world.line.storm(3, world.line.outbox, world.line.new_outbox())

        entries = world.line.entries()
        assert {e["id"] for e in entries} <= approved, "an outbox entry without the Owner's approving approval.resolved"
        assert all(e["authz"]["by"] == "person" and e["authz"]["ref"] == world.meeting_owner for e in entries)
        assert all(e["risk_tier"] == "T3" and "new_recipients" in e["modifiers"] for e in entries)
        assert len(world.line.api.sent) <= len(entries) and len(world.line.transfers) <= len(entries)
        assert all(c.level == "L1" and c.scheduled_at is None for c in cards), "T3 never rides an undo window"

    world.line.advance(7200)
    world.line.storm(10, world.line.outbox, world.line.new_outbox())
    assert {e["id"] for e in world.line.entries()} <= approved
    assert len(world.line.api.sent) <= len(approved)


# ---------------------------------------------------------------------------
# 2. 0 invented commitments


@st.composite
def items_strategy(draw: st.DrawFn) -> list[Item]:
    out: list[Item] = []
    for n in range(1, draw(st.integers(0, 6)) + 1):
        state = draw(st.sampled_from(["verified", "verified", "unverified"]))
        owner = draw(st.sampled_from([None, "u_priya", "u_sam", "u_lena", "u_nobody"]))
        work = draw(st.sampled_from([None, "proposed", "open", "open", "done", "dropped"]))
        work = None if state == "unverified" or owner is None else work  # no assignee, no work item (PE-03)
        out.append(
            item(
                n,
                f"Handle the task called {chr(96 + n)}",
                state=state,
                owner=owner,
                work=work,
                confirmed=draw(st.sampled_from(["owner", "owner", "other", None])),
                source=draw(st.sampled_from(["this", "this", "other"])),
                flagged=draw(st.booleans()),
            )
        )
    return out


@needs_followup
@given(items=items_strategy(), decisions=st.lists(st.sampled_from(["verified", "unverified"]), max_size=3))
@SLOW
def test_FR_MTG_08_property_every_nudge_maps_to_a_confirmed_open_item_and_nothing_is_invented(
    items: list[Item], decisions: list[str]
) -> None:
    world = make_world(items, level="L2", decisions=[(f"The call is made {fresh_key()}", s) for s in decisions])
    expected = world.confirmed_items()
    directory_has = lambda spec: spec.owner in PEOPLE  # noqa: E731 - "u_nobody" has no address

    email = world.minutes_email("u_priya", "u_sam")
    cards = world.nudges()

    wanted = [i for i in expected if directory_has(i)]
    assert len(cards) == len(wanted), "exactly one nudge per open, confirmed item with an assignee Tilo can address"
    for spec in wanted:
        mine = [c for c in cards if spec.key in c.body]
        assert len(mine) == 1, f"item {spec.id} gets one nudge"
        assert addresses(mine[0]) == (PEOPLE[spec.owner],), "to its own assignee, resolved from the directory"
        assert mine[0].tier == "T3" and mine[0].level == "L1"
        assert ("safety_flag" in mine[0].modifiers) == spec.flagged
    for spec in items:
        if spec not in wanted:
            assert not any(spec.key in c.body for c in cards), f"no nudge for {spec.id}: not confirmed and open"
    for prompt in world.model.nudge_prompts():
        assert sum(spec.key in prompt for spec in items) == 1, "a nudge prompt holds its own item only"

    assert email is not None, "the minutes email needs only a confirmed meeting and attendee picks"
    (prompt,) = world.model.minutes_prompts()
    for spec in items:
        assert (spec.key in prompt) == spec.eligible, (
            f"{spec.id} is in the minutes email only if the Owner confirmed it"
        )
        assert (spec.key in email.body) == spec.eligible
    for text, state in world.decisions:
        assert (text in prompt) == (state == "verified") and (text in email.body) == (state == "verified")
    assert world.line.entries() == [] and world.line.api.sent == []
