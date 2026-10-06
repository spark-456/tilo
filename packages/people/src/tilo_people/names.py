"""Spoken-name matching for minutes (FR-MTG-05, PE-15, PE-20; BQ-PPL10-4).

A model never resolves identity: a spoken name matches only by exact equality, after normalisation, with a
display name or an alias of a person the viewer (the meeting owner) may read in directory view. Two or more
matches are ambiguous and are never auto-assigned; attendance never breaks a tie.
"""

from __future__ import annotations

import copy
import unicodedata
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from .access import AccessRequest, decide
from .directory import Directory
from .text import clean_line

NAME_MAX = 80
_CANDIDATE_CAP = 10


def _collapse(text: str) -> str:
    return " ".join(text.split())


def _is_combining_fold(char: str) -> bool:
    return "̀" <= char <= "ͯ"


def normalize_name(text: object) -> str:
    """NFKC, control and format characters removed, diacritics U+0300..U+036F folded, casefold, outer
    punctuation stripped, whitespace collapsed. Not a str, or longer than NAME_MAX (before or after), is "".
    No look-alike mapping: a Cyrillic letter stays Cyrillic."""
    if not isinstance(text, str) or len(text) > NAME_MAX:
        return ""
    folded = unicodedata.normalize("NFKC", text)
    folded = clean_line(folded)
    folded = "".join(c for c in unicodedata.normalize("NFD", folded) if not _is_combining_fold(c))
    folded = unicodedata.normalize("NFKC", folded.casefold())
    folded = _collapse(folded)
    start, end = 0, len(folded)
    while start < end and unicodedata.category(folded[start]).startswith("P"):
        start += 1
    while end > start and unicodedata.category(folded[end - 1]).startswith("P"):
        end -= 1
    folded = _collapse(folded[start:end])
    return "" if len(folded) > NAME_MAX else folded


@dataclass(frozen=True)
class NameMatch:
    status: str  # "resolved" | "ambiguous" | "unknown"
    user: str | None  # set only when resolved
    candidates: tuple[str, ...]  # ambiguous only: matching ids, sorted, at most 10; else ()


_UNKNOWN = NameMatch("unknown", None, ())


def _visible(viewer: Any, directory: Directory, now: Any) -> list[Mapping[str, Any]]:
    """The stored records the viewer may read in directory view (PE-20), sorted by id."""
    found = []
    for person in directory.persons.values():
        request = AccessRequest(actor=viewer, action="read_directory", record_kind="person", record=person, now=now)
        if decide(request, directory).allowed:
            found.append(person)
    return sorted(found, key=lambda p: p["id"])


def name_candidates(viewer: str, directory: Directory, now: str) -> tuple[Mapping[str, Any], ...]:
    """Persons of the directory, sorted by id, that `viewer` may read in directory view: themself, their
    teammates, and everyone in the org for an org owner. No one else can be named in minutes."""
    return tuple(copy.deepcopy(dict(p)) for p in _visible(viewer, directory, now))


def match_name(spoken: object, directory: Directory, *, viewer: str, now: str) -> NameMatch:
    """Exact match of the normalised spoken name with a candidate's normalised display name or alias.
    No prefix, first-name, token, fuzzy or phonetic matching (BQ-PPL10-4)."""
    key = normalize_name(spoken)
    if not key:
        return _UNKNOWN
    matching = []
    for person in _visible(viewer, directory, now):
        if key in {normalize_name(person["display_name"]), *(normalize_name(a) for a in person["aliases"])}:
            matching.append(person["id"])
    if not matching:
        return _UNKNOWN
    if len(matching) == 1:
        return NameMatch("resolved", matching[0], ())
    return NameMatch("ambiguous", None, tuple(matching[:_CANDIDATE_CAP]))
