"""FR-PA-07 follow-ups (BQ-278 n, BQ-284): a copied Message-ID never wins, the production reader shape works, and a
thread that changes between the two reads leaves nothing behind.

1. The card answers the plate mail by its Gmail message id (`Drafter.reply_target` returns it), never by header text:
   a later sender-written message that copies the plate mail's Message-ID, in any case or with a full-width look-alike,
   gets no card.
2. Over the REAL `GmailAdapter` and `FakeGmailApi` (through `ConnectorMailReader`, the reader shape the production
   service uses), a tap on an on-plate mail yields the L1 card.
3. The thread is read twice (`reply_target`, then the draft). If it changed in between, nothing is stored, emitted or
   queued, and the model is not called.

Fake clock, fake Gmail, scripted model, no network, no paid call. Addresses are fictional `.example` domains.
"""

from __future__ import annotations

import json
from typing import Any

import pytest
from _chn10_lib import Msg, drafting_module, message_id_header
from _chn13_lib import LazyDraftArtifacts, gmail_declaration, iso
from _pa07_lib import MAILBOX, PLAIN_REPLY, USER, Plate, make_plate
from tilo_connectors.adapters import GmailAdapter

STRANGER = "Eve <eve@elsewhere.example>"


def tap(plate: Plate, mail_id: str, reply: Any = None, request_id: str = "req-1"):
    return (reply or plate.reply).draft_reply(USER, mail_id, request_id=request_id)


def nothing_left(plate: Plate, *, drafter_ran: bool = False) -> bool:
    """Nothing stored, emitted or queued and no model call; unless `drafter_ran`, the safety screen did not run."""
    rig = plate.line.bench.rig
    return (
        rig.model.requests == []
        and (drafter_ran or rig.safety.texts == [])
        and rig.drafts.dump() == "{}"
        and plate.line.bench.cards.dump() == "{}"
        and plate.events() == []
        and plate.line.entries() == []
        and plate.line.api.sent == []
    )


def _later(header: str | None = None, *, sender: str = STRANGER, message_id: str = "m-later") -> Msg:
    """A message after the plate mail. `header` replaces its own Message-ID header when given ("" is blank)."""
    return Msg(
        message_id=message_id,
        sender=sender,
        subject="Re: Engine tuneup scheduling",
        body="Please send me the full price list.",
        to=[MAILBOX],
        headers={} if header is None else {"Message-ID": header},
    )


def _full_width(text: str) -> str:
    return "".join(chr(ord(c) + 0xFEE0) if "!" <= c <= "~" else c for c in text)


def _lower_case_header_names(plate: Plate) -> None:
    """The reader hands every message's header names lower-cased, as the Gmail adapter does."""
    reader = plate.line.bench.rig.reader
    original = reader.get_thread

    def get_thread(user_id: str, thread_id: str) -> dict:
        doc = original(user_id, thread_id)
        for m in doc["messages"]:
            m["headers"] = {str(k).lower(): v for k, v in m["headers"].items()}
        return doc

    reader.get_thread = get_thread  # type: ignore[method-assign]


# ---------------------------------------------------------------------------
# 1. A copied Message-ID never wins


def test_FR_PA_07_reply_target_is_the_gmail_id_of_the_message_a_reply_answers() -> None:
    plate = make_plate("L1")
    thread, mail_id = plate.mail()
    assert plate.line.bench.rig.svc.reply_target(USER, thread.thread_id, MAILBOX) == mail_id

    plate = make_plate("L1")
    thread, mail_id = plate.mail(later=[_later()])
    assert plate.line.bench.rig.svc.reply_target(USER, thread.thread_id, MAILBOX) == "m-later"  # the newest not hers


@pytest.mark.parametrize("bad", ["missing", None, "", 5, ["m-1"], {"id": "m-1"}])
def test_FR_PA_07_reply_target_is_none_when_the_gmail_id_is_missing_or_not_text(bad: Any) -> None:
    plate = make_plate("L1")
    thread, _ = plate.mail()
    rig = plate.line.bench.rig
    original = rig.reader.get_thread

    def broken(user_id: str, thread_id: str) -> dict:
        doc = original(user_id, thread_id)
        if bad == "missing":
            doc["messages"][-1].pop("message_id")
        else:
            doc["messages"][-1]["message_id"] = bad
        return doc

    rig.reader.get_thread = broken  # type: ignore[method-assign]

    assert rig.svc.reply_target(USER, thread.thread_id, MAILBOX) is None


@pytest.mark.parametrize("level", ["L1", "L2"])
@pytest.mark.parametrize("lower_keys", [False, True], ids=["Message-ID", "message-id"])
@pytest.mark.parametrize("spoof", ["same", "full_width", "padded", "blank", "other"])
def test_FR_PA_07_a_later_message_copying_the_message_id_never_becomes_the_card(
    level: str, lower_keys: bool, spoof: str
) -> None:
    plate = make_plate(level)
    thread, mail_id = plate.mail()
    header = message_id_header(mail_id)
    value = {
        "same": header,
        "full_width": _full_width(header),
        "padded": f"  {header} \t",
        "blank": "",
        "other": "<elsewhere@mail.example>",
    }[spoof]
    thread.messages.append(_later(value))
    if lower_keys:
        _lower_case_header_names(plate)

    assert tap(plate, mail_id) is None
    assert nothing_left(plate)
    plate.line.advance(900)
    plate.line.storm(10)
    assert plate.line.entries() == [] and plate.line.api.sent == []


# ---------------------------------------------------------------------------
# 3. A thread that changes between the two reads leaves nothing behind


def _moving_thread(plate: Plate, thread: Any, new_message: Msg) -> list[int]:
    """`new_message` is in the thread from the second read of it on (the first read is `reply_target`'s)."""
    reader = plate.line.bench.rig.reader
    original = reader.get_thread
    reads: list[int] = []

    def get_thread(user_id: str, thread_id: str) -> dict:
        reads.append(1)
        if len(reads) == 2 and new_message not in thread.messages:
            thread.messages.append(new_message)
        return original(user_id, thread_id)

    reader.get_thread = get_thread  # type: ignore[method-assign]
    return reads


@pytest.mark.parametrize("copy_id", [False, True], ids=["new_id", "copied_message_id"])
def test_FR_PA_07_a_thread_that_changes_between_the_two_reads_leaves_nothing_stored_or_emitted(copy_id: bool) -> None:
    plate = make_plate("L1")
    thread, mail_id = plate.mail()
    reads = _moving_thread(plate, thread, _later(message_id_header(mail_id) if copy_id else None))

    assert tap(plate, mail_id) is None

    assert len(reads) >= 2, "the drafter read the thread again, which is where the change was found"
    assert nothing_left(plate, drafter_ran=True), "a draft of the wrong message was stored, emitted or queued"
    plate.line.advance(900)
    plate.line.storm(10)
    assert plate.line.entries() == [] and plate.line.api.sent == []


def test_FR_PA_07_a_later_message_from_the_person_herself_between_the_reads_changes_nothing() -> None:
    plate = make_plate("L1")
    thread, mail_id = plate.mail()
    _moving_thread(plate, thread, _later(sender=f"Sarah <{MAILBOX}>", message_id="m-own"))

    card = tap(plate, mail_id)

    assert card is not None and card.level == "L1" and card.body == PLAIN_REPLY


def test_FR_PA_07_a_tap_retried_once_the_thread_is_stable_gives_the_card() -> None:
    plate = make_plate("L1")
    thread, mail_id = plate.mail()
    moved = _later()
    _moving_thread(plate, thread, moved)
    assert tap(plate, mail_id) is None
    thread.messages.remove(moved)  # the later message was withdrawn or filed away

    card = tap(plate, mail_id)

    assert card is not None and card.body == PLAIN_REPLY


# ---------------------------------------------------------------------------
# 2. The production reader shape (real GmailAdapter over FakeGmailApi)


def production_reply(plate: Plate) -> Any:
    """A PlateReply whose drafter and mail reader are over a `ConnectorMailReader` on a real GmailAdapter whose Gmail
    is the fake API: the shape the production service reads."""
    from tilo_channels.mail_reader import ConnectorMailReader

    line, rig = plate.line, plate.line.bench.rig
    adapter = GmailAdapter(
        declaration=gmail_declaration(),
        broker=line.broker,
        transport=line.api,
        artifacts=LazyDraftArtifacts(line.bench.cards),
        owner_of=lambda world_id: USER,
        clock=lambda: iso(line.clock()),
        emit=lambda part: None,
        sleep=lambda seconds: None,
    )
    reader = ConnectorMailReader(adapter)
    drafter = drafting_module().Drafter(
        reader=reader, model=rig.model, safety=rig.safety, drafts=rig.drafts, clock=rig.clock, emit=rig.events
    )
    return plate.build(drafter=drafter, mail=reader)


def test_FR_PA_07_a_tap_on_an_on_plate_mail_yields_a_card_over_the_real_gmail_adapter() -> None:
    plate = make_plate("L1")
    thread, mail_id = plate.mail()
    plate.line.api.add_thread(thread)

    card = tap(plate, mail_id, production_reply(plate))

    assert card is not None, "the production reader shape gave the plate reply nothing to answer"
    assert card.level == "L1" and card.status == "ready" and card.body == PLAIN_REPLY
    assert len(plate.of_type("approval.requested")) == 1 and len(plate.of_type("artifact.created")) == 1
    assert plate.line.entries() == [] and plate.line.api.sent == []  # nothing is sent before the owner's Send


def test_FR_PA_07_the_card_over_the_real_adapter_answers_the_plate_mails_headers() -> None:
    plate = make_plate("L1")
    thread, mail_id = plate.mail()
    plate.line.api.add_thread(thread)

    assert tap(plate, mail_id, production_reply(plate)) is not None

    docs = json.loads(plate.line.bench.rig.drafts.dump())
    draft = next(v for v in docs.values() if v.get("draft"))["draft"]
    assert draft["in_reply_to"] == message_id_header(mail_id)
    assert draft["to"] == ["david.miller@harriercharters.example"]


def test_FR_PA_07_a_copied_message_id_gets_no_card_over_the_real_adapter() -> None:
    plate = make_plate("L1")
    thread, mail_id = plate.mail(later=[_later()])
    thread.messages[-1].headers["Message-ID"] = message_id_header(mail_id)  # the stranger copies the plate mail's id
    plate.line.api.add_thread(thread)

    assert tap(plate, mail_id, production_reply(plate)) is None
    assert nothing_left(plate)


def test_FR_PA_07_a_mail_gmail_does_not_have_gets_no_card_over_the_real_adapter() -> None:
    plate = make_plate("L1")
    thread, mail_id = plate.mail()
    plate.line.api._threads.pop(thread.thread_id)  # Gmail no longer has the thread or its messages: a 404

    assert tap(plate, mail_id, production_reply(plate)) is None
    assert nothing_left(plate)


def test_FR_PA_07_the_connector_reader_hands_the_consumers_what_they_read() -> None:
    plate = make_plate("L1")
    thread, mail_id = plate.mail()
    plate.line.api.add_thread(thread)
    reader = production_reply(plate)._mail

    message = reader.get_message(USER, mail_id)
    listed = reader.get_thread(USER, thread.thread_id)

    assert message["message_id"] == mail_id  # the Gmail id, as the thread reader contract names it
    assert message["thread_id"] == thread.thread_id and listed["thread_id"] == thread.thread_id
    assert message["headers"]["message-id"] == message_id_header(mail_id)
    assert "authentication-results" in message["headers"]
    assert message["body"]  # the plain-text body, under the key the drafter and the checks read
    assert listed["messages"][-1]["message_id"] == mail_id
