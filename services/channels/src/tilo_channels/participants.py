"""tilo_channels.participants: who a thread names, for the L2 name slot (FR-CHN-11, CHN-GATE-E, ADR-0025).

`read_participants` reads the last MAX_MESSAGES messages of a thread through the quarantined `ThreadReader` and returns
the addresses in it with the name words that may vouch for a name in a draft. Someone chooses every name in a mail
header, so a word counts only from one source: the BASE address local part (a plus tag dropped) of every From, To and Cc
address, split on `. _ - +`. No display name ever vouches a word (ADR-0025 amendment 8 Oct: Gmail copies an inbound
From display name into the user's own SENT To, so even the user's mail carries a sender's choice), and neither does a
plus tag. A local part is dropped whole unless it is a short run of plain words that holds no money, legal, commitment
or number signal. Caps: MAX_PEOPLE participants (newest message first, one per base address), MAX_WORDS words each, and
MAX_HEADER_CHARS of header text parsed per read (anything past it is not read: fewer names). No thread, a failed or
malformed read leaves the mailbox's own local part. Names live in memory for one card decision: nothing here logs,
stores or raises them, and nothing is cached between calls.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from tilo_channels.autopilot_t3 import _numberish, inbound_signal
from tilo_channels.drafting import MAX_ADDRESSES, MAX_MESSAGES, ThreadReader, _address, _addresses, _base

MAX_PEOPLE, MAX_WORDS, MAX_NAME_WORDS, MAX_HEADER_CHARS = 100, 8, 4, 60_000
_LOCAL = re.compile(r"[._+\-]+")
_WORD = re.compile(r"[A-Za-z]+(?:'[A-Za-z]+)?")
_LETTERS = range(2, 25)


@dataclass(frozen=True)
class Participant:
    address: str  # bare, lower-case ASCII, plus tag dropped (`drafting._base` of `drafting._address`)
    names: frozenset[str]  # lower-case words that passed the filter


def _words(local: str, seen: dict[str, tuple[str, ...]]) -> tuple[str, ...]:
    """The words of an address local part, or () when any rule drops it whole (ADR-0025 decision 4). `seen` is this
    call's own memo, so a local part is filtered once however often a thread repeats it."""
    if local in seen:
        return seen[local]
    found = tuple(w for w in _LOCAL.split(local) if w)
    ok = 1 <= len(found) <= MAX_NAME_WORDS and all(
        w.isascii() and _WORD.fullmatch(w) and len(w.replace("'", "")) in _LETTERS for w in found
    )
    low = tuple(w.lower() for w in found) if ok else ()
    ok = ok and not inbound_signal(" ".join(low)) and not inbound_signal("".join(low))
    ok = ok and not any(_numberish(w) for w in low) and not any(_numberish(a + b) for a, b in zip(low, low[1:]))
    seen[local] = low if ok else ()
    return seen[local]


def _cost(value: Any) -> int:
    """The characters `_addresses` would parse in a header value."""
    raw = [value] if isinstance(value, str) else value[:MAX_ADDRESSES] if isinstance(value, list) else []
    return sum(len(v) for v in raw if isinstance(v, str))


def read_participants(
    reader: ThreadReader, user_id: str, thread_id: str | None, mailbox: str
) -> tuple[Participant, ...]:
    """The thread's participants with their vouched name words, newest message first; the mailbox owner is always one
    (when it is a usable address). Never raises."""
    seen: dict[str, tuple[str, ...]] = {}
    people: dict[str, list[str]] = {}  # base address -> its name words in order
    budget = MAX_HEADER_CHARS

    def add(address: str) -> None:
        base = _base(address)
        words = people.get(base)
        if words is None and len(people) < MAX_PEOPLE:
            words = people[base] = []
        if words is not None:
            words.extend(w for w in _words(base.partition("@")[0], seen) if w not in words)
            del words[MAX_WORDS:]

    own = _address(mailbox) if isinstance(mailbox, str) else None
    if own:
        add(own)
    try:
        listed = reader.get_thread(user_id, thread_id).get("messages") if thread_id else []
        messages = [m for m in (listed if isinstance(listed, list) else [])[-MAX_MESSAGES:] if isinstance(m, dict)]
        for message in reversed(messages):
            for head in ("from", "to", "cc"):
                value = message.get(head)
                if (cost := _cost(value)) <= budget:  # an over-budget header is not parsed at all
                    budget -= cost
                    for address in _addresses(value)[
                        : 1 if head == "from" else MAX_ADDRESSES
                    ]:  # one sender, as `_known`
                        add(address)
    except Exception:  # a failed or malformed read only narrows the names (fail closed)
        pass
    return tuple(Participant(base, frozenset(words)) for base, words in people.items())
