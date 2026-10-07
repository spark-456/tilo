"""CHN-GATE-E (FR-CHN-11; ADR-0025 decisions 1, 3, 4, 7): `tilo_channels.participants.read_participants(reader, user_id,
thread_id, mailbox)` and the name filter. The thread is untrusted: someone chooses every name in a mail header, so a
name counts only when the user's own client wrote it (a `SENT` message From the mailbox) or it comes from an address
local part, and the gate later uses only the names of the draft's own recipients and the mailbox.

Defaults applied (ADR-0025, "Name filter"):
 - A display name or a local part is dropped WHOLE unless every word is 2 to 24 ASCII letters (one inner apostrophe
   allowed), there are at most 4 words, `inbound_signal` finds nothing in the words joined with spaces or with nothing,
   and no word (nor two neighbouring words joined) is `_numberish`. A local part is split on `. _ - +`; a display name
   on spaces, `.`, `,` and `-`. The other source of the same address still counts ("Refunds Team <pat@...>" keeps
   "pat").
 - `Participant` lives in `tilo_channels.participants` (the ADR names the field, not the module of the class).
 - Caps (decision 7): 100 participants, newest message first, one per base address (plus tag dropped); 8 name words
   each.
   Whether the mailbox's own participant counts inside the 100 is not stated: the cap test allows either.
"""

from __future__ import annotations

import dataclasses
import re
import time
from typing import Any

import pytest
from _chn10_lib import FakeThreadReader, Msg, Thread
from _chn_gate_e_lib import (
    MAILBOX,
    OWN,
    Mail,
    RaisingReader,
    inbound,
    names_by_address,
    participants_module,
    sent,
    t3_module,
)
from hypothesis import given, settings
from hypothesis import strategies as st

USER = "u_participants"
THREAD = "t-participants"


def read(*messages: Msg, mailbox: str = MAILBOX, thread_id: str | None = THREAD, reader: Any = None) -> tuple[Any, ...]:
    if reader is None:
        reader = FakeThreadReader()
        reader.add(USER, Thread(thread_id=THREAD, messages=list(messages)))
    return tuple(participants_module().read_participants(reader, USER, thread_id, mailbox))


def names_of(address: str, *messages: Msg, **kw: Any) -> frozenset[str]:
    return names_by_address(read(*messages, **kw))[address]


# ---- 1. the shape (decision 1) ---------------------------------------------------------------------------------------


def test_FR_CHN_11_CHN_GATE_E_participant_holds_an_address_and_name_words_only() -> None:
    participant = participants_module().Participant
    assert dataclasses.is_dataclass(participant)
    assert [f.name for f in dataclasses.fields(participant)] == ["address", "names"]
    one = participant("david@example.com", frozenset({"david"}))
    with pytest.raises(dataclasses.FrozenInstanceError):
        one.names = frozenset()  # type: ignore[misc]
    (found,) = [p for p in read(sent(to=("David <David@Example.COM>",))) if "david" in p.address]
    assert found.address == "david@example.com", "a bare, lower-case address"
    assert isinstance(found.names, frozenset) and all(w == w.lower() for w in found.names)


# ---- 2. where names come from (decision 3) ---------------------------------------------------------------------------


def test_FR_CHN_11_CHN_GATE_E_sent_to_and_cc_display_names_name_the_recipients() -> None:
    names = names_by_address(
        read(
            sent(
                to=("David Lee <david@example.com>",),
                cc=("Priya Shah <priya@example.com>", "Marcus <marcus@example.com>"),
            )
        )
    )
    assert names["david@example.com"] == {"david", "lee"}
    assert names["priya@example.com"] == {"priya", "shah"}
    assert names["marcus@example.com"] == {"marcus"}


def test_FR_CHN_11_CHN_GATE_E_address_local_parts_are_names_split_on_dot_underscore_dash_plus() -> None:
    for address, words in (
        ("anna.maria_lee+jones@example.com", {"anna", "maria", "lee", "jones"}),
        ("anne-marie@example.com", {"anne", "marie"}),
        ("david@example.com", {"david"}),
    ):
        assert names_of(address, inbound(f"Zed <{address}>")) == words, address


def test_FR_CHN_11_CHN_GATE_E_an_inbound_from_display_name_is_not_a_name_source() -> None:
    # "Marcus Reed" passes the name filter, so only the trust rule keeps it out; the sender's address local part stays.
    assert names_of("sender@example.com", inbound("Marcus Reed <sender@example.com>")) == {"sender"}
    assert names_of("sender@example.com", inbound("Fifty Thousand <sender@example.com>")) == {"sender"}


def test_FR_CHN_11_CHN_GATE_E_a_display_name_a_third_party_wrote_for_someone_else_names_nobody() -> None:
    mail = inbound(
        "Dana <dana@example.com>", to=("Marcus Reed <ops@harborview.example>", "Zebra Pelican <zoe@example.com>")
    )
    mail.cc = ["Marcus Reed <david@example.com>", "Fifty Thousand <david@example.com>"]
    names = names_by_address(read(mail))
    assert names["david@example.com"] == {"david"}, "an inbound Cc display name names nobody"
    assert names["zoe@example.com"] == {"zoe"}, "an inbound To display name names nobody"
    assert names[MAILBOX] == {"ops"}, "an inbound To display name does not name the user"


def test_FR_CHN_11_CHN_GATE_E_a_from_header_alone_is_not_the_users_own_mail() -> None:
    # BQ-223: a From header naming the mailbox is set by the sender; only Gmail's SENT label makes it the user's own.
    spoof = Mail(
        "m-spoof",
        OWN,
        "Engine tune-up",
        "x",
        to=["Marcus Reed <david@example.com>"],
        cc=["Zebra Pelican <priya@example.com>"],
        labels=["INBOX"],
    )
    names = names_by_address(read(spoof))
    assert names["david@example.com"] == {"david"} and names["priya@example.com"] == {"priya"}
    assert names[MAILBOX] == {"ops"}, "the From name of an unlabelled message is not the owner's name"
    unlabelled = Mail("m-nolabel", OWN, "Engine tune-up", "x", to=["Marcus Reed <david@example.com>"])
    assert names_by_address(read(unlabelled))["david@example.com"] == {"david"}


def test_FR_CHN_11_CHN_GATE_E_the_mailbox_from_name_counts_only_on_its_own_sent_mail() -> None:
    assert names_of(MAILBOX, sent(to=("david@example.com",))) == {"ops", "sarah", "chen"}
    # another message From the mailbox address but not SENT, and an inbound sender's own From name: neither counts
    spoof = inbound("Marcus Reed <ops@harborview.example>")
    assert names_of(MAILBOX, spoof) == {"ops"}
    assert names_of(MAILBOX, sent(to=("david@example.com",)), spoof) == {"ops", "sarah", "chen"}


def test_FR_CHN_11_CHN_GATE_E_a_member_of_the_thread_is_a_participant_with_its_local_part_only() -> None:
    names = names_by_address(
        read(inbound("Dana Fox <dana.fox@example.com>", to=(MAILBOX, "Priya Shah <priya@example.com>")))
    )
    assert names["dana.fox@example.com"] == {"dana", "fox"}
    assert names["priya@example.com"] == {"priya"}


# ---- 3. no thread, a failed read (decision 3: fail closed) ----


@pytest.mark.parametrize("thread_id", [None, ""])
def test_FR_CHN_11_CHN_GATE_E_no_thread_leaves_only_the_mailbox_local_part(thread_id: str | None) -> None:
    assert names_by_address(read(thread_id=thread_id)) == {MAILBOX: {"ops"}}


def test_FR_CHN_11_CHN_GATE_E_a_failing_reader_leaves_only_the_mailbox_local_part() -> None:
    reader = RaisingReader()
    assert names_by_address(read(reader=reader)) == {MAILBOX: {"ops"}}
    assert reader.calls == 1


class _Garbage:
    def __init__(self, value: Any) -> None:
        self.value = value

    def get_thread(self, user_id: str, thread_id: str) -> Any:
        return self.value


@pytest.mark.parametrize(
    "value",
    [
        {},
        {"messages": None},
        {"messages": "not a list"},
        {"messages": [None, 7, "x", ["y"]]},
        {"messages": [{"from": 7, "to": {"a": 1}, "cc": [None, 3], "labelIds": "SENT"}]},
        {"messages": [{"from": "((((((((((((((((((((((", "to": "<<<<>>>>@@@@", "labelIds": ["SENT"]}]},
        {"messages": [{"from": OWN, "to": ["x" * 600 + "@example.com"], "labelIds": ["SENT"]}]},
        [],
        "nope",
    ],
)
def test_FR_CHN_11_CHN_GATE_E_malformed_thread_data_never_raises_and_adds_nothing(value: Any) -> None:
    found = names_by_address(read(reader=_Garbage(value)))
    assert found.get(MAILBOX, frozenset()) <= {"ops", "sarah", "chen"}
    assert all(not names or all(re.fullmatch(r"[a-z']+", w) for w in names) for names in found.values())


@pytest.mark.parametrize("mailbox", ["", "not an address", "òps@harborview.example", "ops@@x.example"])
def test_FR_CHN_11_CHN_GATE_E_an_unusable_mailbox_gives_it_no_names(mailbox: str) -> None:
    assert not any(p.names for p in read(sent(to=("david@example.com",)), mailbox=mailbox) if p.address == mailbox)


# ---- 4. the name filter (decision 4) --------------------------------------------------------------------------------

PASSING = [
    ("David Lee", {"david", "lee"}),
    ("Lee, David", {"lee", "david"}),
    ('"Lee, David"', {"lee", "david"}),
    ("Anne-Marie Smith", {"anne", "marie", "smith"}),
    ("Dr. David Lee", {"dr", "david", "lee"}),
    ("Pat O'Brien", {"pat", "o'brien"}),
    ("Al Li", {"al", "li"}),  # two letters is long enough
    ("Mary Ann Van Berg", {"mary", "ann", "van", "berg"}),  # four words is the limit
    ("q" * 24, {"q" * 24}),  # 24 letters is the limit (alone: `_numberish` on a neighbour join also caps its length)
]
DROPPED = [
    "Fifty Thousand",
    "Refunds Team",
    "Tenk",
    "Legal Dept",
    "Re Fund",  # joined with nothing: "refund"
    "Con Tract",  # joined with nothing: "contract"
    "Fif Ty",  # two neighbouring words that join into a number word
    "Ten K",
    "Wire Services",
    "José Núñez",  # non-ASCII
    "Dave99",
    "Dave 2nd",
    "J Smith",  # one letter
    "Mary Ann Van Der Berg",  # five words
    "q" * 25,  # 25 letters
    "Pat_Lee",  # an underscore is not a separator in a display name, and not a letter
    "Pat/Lee",
    "We Will",  # joined with spaces: a commitment phrase
    "   ",
]


@pytest.mark.parametrize(("display", "words"), PASSING, ids=[d[:28] for d, _ in PASSING])
def test_FR_CHN_11_CHN_GATE_E_filter_keeps_a_plain_display_name(display: str, words: set[str]) -> None:
    quoted = display if display.startswith('"') else f'"{display}"' if "," in display else display
    found = names_of("pat@example.com", sent(to=(f"{quoted} <pat@example.com>",)))
    assert found == words | {"pat"}


@pytest.mark.parametrize("display", DROPPED, ids=[d[:28] for d in DROPPED])
def test_FR_CHN_11_CHN_GATE_E_filter_drops_a_display_name_whole_and_names_nobody(display: str) -> None:
    quoted = f'"{display}"' if "," in display or "/" in display else display
    found = names_of("pat@example.com", sent(to=(f"{quoted} <pat@example.com>",)))
    assert found == {"pat"}, "a dropped display name leaves the address local part alone"


@pytest.mark.parametrize(
    ("address", "expected"),
    [
        ("refunds@example.com", set()),
        ("fifty.thousand@example.com", set()),
        ("tenk@example.com", set()),
        ("dave99@example.com", set()),
        ("j.smith@example.com", set()),
        ("legal-dept@example.com", set()),
        ("pat.lee@example.com", {"pat", "lee"}),
        ("a" + "b" * 24 + "@example.com", set()),
    ],
)
def test_FR_CHN_11_CHN_GATE_E_filter_applies_to_a_local_part_too(address: str, expected: set[str]) -> None:
    assert names_of(address, sent(to=(address,))) == expected


@settings(max_examples=120, deadline=None)
@given(
    display=st.text(max_size=60),
    local=st.text("abcdefghijklmnopqrstuvwxyz0123456789._+-", min_size=1, max_size=40),
)
def test_FR_CHN_11_CHN_GATE_E_property_every_kept_name_word_is_a_short_plain_clean_word(
    display: str, local: str
) -> None:
    module = t3_module()
    mail = sent(to=(f'"{display}" <{local}@example.com>',), cc=(f'"{display}" <{local}@example.com>',))
    result = read(mail)
    assert len(result) <= 100
    for participant in result:
        assert len(participant.names) <= 8
        for word in participant.names:
            assert re.fullmatch(r"[a-z]+(?:'[a-z]+)?", word), word
            assert 2 <= len(word.replace("'", "")) <= 24
            assert not module.inbound_signal(word), f"a family word is a name: {word!r}"
            assert not module._numberish(word), f"a number is a name: {word!r}"


# ---- 5. caps and time (decision 7) ----


def test_FR_CHN_11_CHN_GATE_E_at_most_100_participants_newest_message_first() -> None:
    old = inbound("Old <old@example.com>")
    newer = [inbound(f"<s{i}@example.com>", to=tuple(f"p{i}x{j}@example.com" for j in range(49))) for i in range(2)]
    # 1 + 2 x (1 sender + 49 recipients) = 101 distinct non-mailbox addresses; the mailbox is not among them
    found = names_by_address(read(old, *newer))
    others = [a for a in found if a != MAILBOX]
    assert len(found) <= 101 and len(others) <= 100, "a 101st participant is cut"
    assert "old@example.com" not in found, "the oldest message's participant is the one cut"
    assert len(others) >= 99, "only the cap cuts: the newest messages' participants are kept"


def test_FR_CHN_11_CHN_GATE_E_one_participant_per_base_address() -> None:
    found = names_by_address(read(sent(to=("david+a@example.com", "david+b@example.com", "David@Example.com"))))
    assert len([a for a in found if a.split("@")[0].split("+")[0] == "david"]) == 1


def test_FR_CHN_11_CHN_GATE_E_at_most_8_name_words_per_participant_newest_first() -> None:
    oldest = sent(to=("Aa Bb Cc Dd <pat@example.com>",))
    middle = sent(to=("Ee Ff Gg Hh <pat@example.com>",))
    newest = sent(to=("Ii Jj Kk Ll <pat@example.com>",))
    names = names_of("pat@example.com", oldest, middle, newest)
    assert len(names) == 8, "anything past 8 words is dropped"
    assert {"ii", "jj", "kk", "ll"} <= names, "the newest message's words come first"
    assert not names & {"aa", "bb", "cc", "dd"}, "the oldest message's words are the ones cut"


def test_FR_CHN_11_CHN_GATE_E_only_the_last_50_messages_are_read() -> None:
    first = sent(to=("Zed Old <zed@example.com>",))
    rest = [inbound(f"Dana <dana{i}@example.com>") for i in range(50)]
    found = names_by_address(read(first, *rest))
    assert "zed@example.com" not in found, "a 51st message from the end is not read (drafting.MAX_MESSAGES)"
    assert "dana49@example.com" in found


def test_FR_CHN_11_CHN_GATE_E_50_messages_of_50_addresses_stay_within_today_s_time() -> None:
    messages = [
        sent(to=tuple(f"Person {chr(97 + i % 26)}{chr(97 + j % 26)} <p{i}x{j}@example.com>" for j in range(50)))
        for i in range(50)
    ]
    started = time.perf_counter()
    result = read(*messages)
    elapsed = time.perf_counter() - started
    assert len(result) <= 101
    assert elapsed < 1.5, f"{elapsed:.2f}s for 50 messages of 50 addresses: reading participants must stay linear"
