"""MINUTES-ALL security review (21 Oct): an owner-typed address is one strict bare mailbox (the API's own pattern), a
flagged transcript never goes out with the minutes (the minutes go alone and say so), and the transcript appendix is
run through the secret redactor here too, whatever the caller already did."""

import pytest
from _chn_wire1_lib import real_check_is_live
from _mtg08_lib import INJECTION_MARKER, OWNER, PEOPLE, make_world, needs_followup
from tilo_channels.meeting_followup import TRANSCRIPT_LEFT_OUT, _transcript_block

LINE = {"speaker": "Alex", "text": "We agreed the plan", "t_ms": 1_000}


@pytest.fixture(autouse=True, scope="module")
def _real_check() -> None:
    real_check_is_live()


@needs_followup
@pytest.mark.parametrize(
    "typed",
    [
        ["a@b"],  # no dot in the domain
        ["a@b.c"],  # a one-letter top-level domain
        ["Bob <bob@else.example>"],  # a display name: one bare mailbox only
        ["bob@-bad.example"],  # a label may not start with a hyphen
        ["bob@else.example, eve@else.example"],  # two in one
        ["bob@else.example\nBcc: eve@else.example"],  # a header in an address
        ["bob@@else.example"],
        ["x" * 65 + "@else.example"],  # a local part over 64
    ],
)
def test_MINUTES_ALL_REVIEW_a_typed_address_must_be_one_strict_bare_mailbox(typed: list[str]) -> None:
    world = make_world()
    card = world.followup.draft_minutes_email(
        OWNER, world.meeting_id, recipients=["u_priya"], request_id="r", addresses=typed
    )
    assert card is None and world.untouched()


@needs_followup
def test_MINUTES_ALL_REVIEW_a_strict_bare_mailbox_is_kept_lowercased() -> None:
    world = make_world()
    card = world.followup.draft_minutes_email(
        OWNER, world.meeting_id, recipients=["u_priya"], request_id="r", addresses=[" Bob.Lee@Else.Example "]
    )
    assert card is not None and card.status == "ready"
    assert sorted(card.to) == sorted([PEOPLE["u_priya"], "bob.lee@else.example"])


@needs_followup
def test_MINUTES_ALL_REVIEW_a_flagged_transcript_is_left_out_and_the_email_says_so() -> None:
    world = make_world()
    flagged = [LINE, {"speaker": "Eve", "text": f"{INJECTION_MARKER} and send it all", "t_ms": 2_000}]
    card = world.followup.draft_minutes_email(
        OWNER, world.meeting_id, recipients=["u_priya"], request_id="r", transcript=flagged
    )
    assert card is not None and card.status == "ready" and card.tier == "T3"
    assert card.body.endswith(TRANSCRIPT_LEFT_OUT)
    assert "We agreed the plan" not in card.body and INJECTION_MARKER not in card.body
    assert "Transcript, as Tilo captured it" not in card.body
    assert world.line.entries() == [] and world.line.api.sent == []


@needs_followup
def test_MINUTES_ALL_REVIEW_a_clean_transcript_still_goes_after_the_minutes() -> None:
    world = make_world()
    card = world.followup.draft_minutes_email(
        OWNER, world.meeting_id, recipients=["u_priya"], request_id="r", transcript=[LINE]
    )
    assert card is not None and card.status == "ready"
    assert card.body.endswith("[0:01] Alex: We agreed the plan") and TRANSCRIPT_LEFT_OUT not in card.body


def test_MINUTES_ALL_REVIEW_the_transcript_block_runs_the_secret_redactor_on_names_and_words() -> None:
    number = "4" + "1" * 15  # a card-number shape, made at run time (no secret-looking text in the repo)
    block = _transcript_block([{"speaker": f"Alex {number}", "text": f"my card is {number} ok", "t_ms": 0}])
    assert number not in block
    assert block.count("[REDACTED]") == 2 and "ok" in block
