"""tilo_channels.participants: who a thread names, for the L2 name slot (FR-CHN-11, CHN-GATE-E, ADR-0025).

`read_participants` reads the last MAX_MESSAGES messages of a thread through the quarantined `ThreadReader` and returns
the addresses in it with the name words that may vouch for a name in a draft. Someone chooses every name in a mail
header, so a word counts only from three sources: the To / Cc display names on the mailbox's own `SENT` messages (a
From the mailbox alone is sender-controlled, BQ-223), every address's local part, and the mailbox's own From name on
that `SENT` mail. An inbound From, To or Cc display name names nobody. A display name or local part is dropped whole
unless it is a short run of plain words that holds no money, legal, commitment or number signal. Caps: MAX_PEOPLE
participants (newest message first, one per base address), MAX_WORDS words each. No thread, a failed or malformed read
leaves the mailbox's own local part. Names live in memory for one card decision: nothing here logs, stores or raises
them, and nothing is cached between calls.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from tilo_channels.autopilot_t3 import _numberish, inbound_signal
from tilo_channels.drafting import MAX_MESSAGES, ThreadReader, _address, _base, _pairs

MAX_PEOPLE, MAX_WORDS, MAX_NAME_WORDS = 100, 8, 4
_DISPLAY = re.compile(r"[ .,\-]+")
_LOCAL = re.compile(r"[._+\-]+")
_WORD = re.compile(r"[A-Za-z]+(?:'[A-Za-z]+)?")
_LETTERS = range(2, 25)


@dataclass(frozen=True)
class Participant:
    address: str  # bare, lower-case ASCII (`drafting._address`)
    names: frozenset[str]  # lower-case words that passed the filter


def _words(raw: str, splitter: re.Pattern[str], seen: dict[Any, tuple[str, ...]]) -> tuple[str, ...]:
    """The words of a display name or local part, or () when any rule drops it whole (ADR-0025 decision 4). `seen` is
    this call's own memo, so a name is filtered once however often a thread repeats it."""
    if (raw, splitter) in seen:
        return seen[raw, splitter]
    found = tuple(w.lower() for w in splitter.split(raw) if w)
    ok = 1 <= len(found) <= MAX_NAME_WORDS and all(
        _WORD.fullmatch(w) and len(w.replace("'", "")) in _LETTERS for w in found
    )
    ok = ok and not inbound_signal(" ".join(found)) and not inbound_signal("".join(found))
    ok = ok and not any(_numberish(w) for w in found) and not any(_numberish(a + b) for a, b in zip(found, found[1:]))
    seen[raw, splitter] = found if ok else ()
    return seen[raw, splitter]


def read_participants(
    reader: ThreadReader, user_id: str, thread_id: str | None, mailbox: str
) -> tuple[Participant, ...]:
    """The thread's participants with their vouched name words, newest message first; the mailbox owner is always one
    (when it is a usable address). Never raises."""
    seen: dict[Any, tuple[str, ...]] = {}
    people: dict[str, tuple[str, list[str]]] = {}  # base address -> (first address seen, words in order)

    def add(entry: tuple[str, list[str]], words: tuple[str, ...]) -> None:
        entry[1].extend(w for w in words if w not in entry[1])
        del entry[1][MAX_WORDS:]

    own = _address(mailbox) if isinstance(mailbox, str) else None
    if own:
        people[_base(own)] = (own, [])
        add(people[_base(own)], _words(own.partition("@")[0], _LOCAL, seen))
    try:
        listed = reader.get_thread(user_id, thread_id).get("messages") if thread_id else []
        messages = [m for m in (listed if isinstance(listed, list) else [])[-MAX_MESSAGES:] if isinstance(m, dict)]
        for message in reversed(messages):
            heads = [_pairs(message.get(h)) for h in ("from", "to", "cc")]
            heads[0] = heads[0][:1]  # the sender, as `Autopilot._known` reads it
            labels = message.get("labelIds")
            sender = _address(heads[0][0][1]) if heads[0] else None
            mine = bool(
                own and sender and _base(sender) == _base(own) and isinstance(labels, list) and "SENT" in labels
            )
            for display, raw in (pair for head in heads for pair in head):
                address = _address(raw)
                if address is None:
                    continue
                entry = people.get(_base(address))
                if entry is None and len(people) < MAX_PEOPLE:
                    entry = people[_base(address)] = (address, [])
                    add(entry, _words(address.partition("@")[0], _LOCAL, seen))
                if entry is not None and mine:  # only the user's own client wrote these display names
                    add(entry, _words(display, _DISPLAY, seen))
    except Exception:  # a failed or malformed read only narrows the names (fail closed)
        pass
    return tuple(Participant(address, frozenset(words)) for address, words in people.values())
