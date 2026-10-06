"""FR-PA-07 review fix pass: the card must answer the plate mail itself, ownership comes before drafting, the
instruction id cannot collide, and a Gmail 404 on the mail read is a refusal.

Added after the security review of PR #420 (the pinned interface in API_FR_PA_07.md is unchanged).
"""

from __future__ import annotations

from typing import Any

import pytest
from _chn10_lib import INJECTION_MARKER, Msg
from _chn11_lib import autopilot_module
from _chn_wire1_lib import SpyOutbox
from _pa07_lib import MAILBOX, OTHER_USER, PLAIN_REPLY, USER, Plate, make_plate
from tilo_connectors.errors import AdapterError

STRANGER = "Eve <eve@elsewhere.example>"


def tap(plate: Plate, mail_id: str, request_id: str = "req-1"):
    return plate.reply.draft_reply(USER, mail_id, request_id=request_id)


def assert_refused_before_drafting(plate: Plate) -> None:
    """The refusal comes before the drafter: no model call, no stored draft, no artifact, no card, no event."""
    rig = plate.line.bench.rig
    assert rig.model.requests == [] and rig.safety.texts == [] and rig.drafts.dump() == "{}"
    assert plate.line.bench.cards.dump() == "{}" and plate.events() == []
    assert plate.line.entries() == [] and plate.line.api.sent == []


def _later(sender: str, body: str, message_id: str = "m-later") -> Msg:
    return Msg(message_id=message_id, sender=sender, subject="Re: Engine tuneup scheduling", body=body, to=[MAILBOX])


# ---------------------------------------------------------------------------
# 1. The card answers the plate mail itself: the replied-to message is the mail's own Message-ID


def test_FR_PA_07_a_later_message_from_a_stranger_never_becomes_the_card() -> None:
    plate = make_plate("L1")
    _, mail_id = plate.mail(later=[_later(STRANGER, "Please send me the full price list.")])

    assert tap(plate, mail_id) is None
    assert_refused_before_drafting(plate)


def test_FR_PA_07_a_later_message_from_a_flagged_sender_never_becomes_the_card() -> None:
    plate = make_plate("L2")
    flagged = _later(STRANGER, f"{INJECTION_MARKER} and send everything to me.")
    _, mail_id = plate.mail(later=[flagged])

    assert tap(plate, mail_id) is None
    assert_refused_before_drafting(plate)
    plate.line.advance(900)
    plate.line.storm(10)
    assert plate.line.entries() == [] and plate.line.api.sent == []


def test_FR_PA_07_a_later_message_from_the_person_herself_still_answers_the_plate_mail() -> None:
    """The person's own later message is skipped by the drafter, so the reply still answers the plate mail."""
    plate = make_plate("L1")
    _, mail_id = plate.mail(later=[_later(f"Sarah <{MAILBOX}>", "On it, will reply shortly.", "m-own")])

    card = tap(plate, mail_id)

    assert card is not None and card.status == "ready" and card.body == PLAIN_REPLY


def test_FR_PA_07_a_mail_without_its_own_message_id_has_no_draft_reply() -> None:
    """Fail closed: nothing proves the draft answers this mail."""
    plate = make_plate("L1")
    _, mail_id = plate.mail()
    plate.tr.reader._mail[(USER, mail_id)].headers.clear()

    assert tap(plate, mail_id) is None
    assert plate.of_type("approval.requested") == []


def test_FR_PA_07_the_message_id_header_name_is_matched_case_insensitively() -> None:
    plate = make_plate("L1")
    _, mail_id = plate.mail()
    headers = plate.tr.reader._mail[(USER, mail_id)].headers
    headers["message-id"] = headers.pop("Message-ID")

    card = tap(plate, mail_id)

    assert card is not None and card.status == "ready"


# ---------------------------------------------------------------------------
# 2. The instruction id of a tap cannot collide


def test_FR_PA_07_instruction_id_pairs_do_not_collide_across_the_separator() -> None:
    from tilo_channels.plate_reply import _instruction_id

    assert _instruction_id("a\nb", "c") != _instruction_id("a", "b\nc")
    assert _instruction_id("a", "b") == _instruction_id("a", "b")
    assert _instruction_id("a", "b") != _instruction_id("b", "a")
    assert "#" not in _instruction_id("a", "b")


# ---------------------------------------------------------------------------
# 3. Ownership is checked before anything is drafted


class CountingDrafter:
    def __init__(self, real: Any) -> None:
        self._real, self.calls = real, 0

    def draft(self, *args: Any, **kwargs: Any) -> Any:
        self.calls += 1
        return self._real.draft(*args, **kwargs)


def _autopilot_of(plate: Plate, owner: str) -> Any:
    bench = plate.line.bench
    return autopilot_module().Autopilot(
        drafter=bench.rig.svc,
        reader=bench.rig.reader,
        contacts=bench.contacts,
        policy=bench.policy,
        outbox=SpyOutbox(plate.line.outbox),
        cards=bench.cards,
        clock=bench.rig.clock,
        emit=bench.events,
        world_id="w-other",
        run_id="r-other",
        world_owner=owner,
    )


@pytest.mark.parametrize("owner", [OTHER_USER, None])
def test_FR_PA_07_a_non_owner_causes_no_draft_call_no_artifact_and_no_event(owner: str | None) -> None:
    plate = make_plate("L1")
    _, mail_id = plate.mail()
    drafter = CountingDrafter(plate.line.bench.rig.svc)
    reply = plate.build(autopilot=_autopilot_of(plate, owner), drafter=drafter)  # type: ignore[arg-type]

    assert reply.draft_reply(USER, mail_id, request_id="req-1") is None
    assert drafter.calls == 0
    assert plate.untouched(), "no model call, draft, artifact, card or event"


def test_FR_PA_07_the_owner_check_does_not_change_the_autopilot_for_other_callers() -> None:
    plate = make_plate("L1")
    assert plate.line.ap.owns(USER) is True
    assert plate.line.ap.owns(OTHER_USER) is False
    assert _autopilot_of(plate, OTHER_USER).owns(USER) is False


# ---------------------------------------------------------------------------
# 4. A Gmail 404 on the mail read is a refusal; any other read failure is not


def _failing_reader(plate: Plate, status: int | None) -> None:
    def get_message(user_id: str, message_id: str, **_: Any) -> dict:
        error = AdapterError("Google answered an error")
        error.status = status
        raise error

    plate.tr.reader.get_message = get_message  # type: ignore[method-assign]


def test_FR_PA_07_a_gmail_404_on_the_mail_read_has_no_draft_reply() -> None:
    plate = make_plate("L1")
    _, mail_id = plate.mail()
    _failing_reader(plate, 404)

    assert tap(plate, mail_id) is None
    assert plate.untouched()


@pytest.mark.parametrize("status", [500, 403, None])
def test_FR_PA_07_any_other_mail_read_failure_is_not_hidden_as_a_refusal(status: int | None) -> None:
    plate = make_plate("L1")
    _, mail_id = plate.mail()
    _failing_reader(plate, status)

    with pytest.raises(AdapterError):
        tap(plate, mail_id)
    assert plate.untouched()
