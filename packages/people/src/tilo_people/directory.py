"""The membership facts `decide` rests on (people.rules.md "Terms").

The caller passes every person of the actor's org (team scale, ADR-0015). A person missing from the directory
has no rights and no membership. Membership is evaluated at `now`, so a person who left (entry removed) or
whose entry is dated later counts as no member.
"""

from __future__ import annotations

import copy
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any

from tilo_policy.schemas import conforms

from ._schema import is_timestamp, valid

_PERSON = "person.schema.json"
# A record "holds" its id when these fields are well formed, even if it is invalid elsewhere, so a malformed
# twin of a person cannot hide a collision. A record whose identity fields are junk holds nothing.
_IDENTITY = ("id", "org_id", "org_role", "memberships")


def _admit(records: Iterable[Any]) -> dict[str, dict[str, Any]]:
    """Valid, unambiguous person records by id; an id held by two records (two orgs, a duplicate) drops both."""
    held: dict[str, int] = {}
    good: dict[str, dict[str, Any]] = {}
    for record in records:
        if not isinstance(record, Mapping) or not conforms(_PERSON, record, *_IDENTITY):
            continue
        user = record["id"]
        held[user] = held.get(user, 0) + 1
        if valid(_PERSON, record):
            good[user] = copy.deepcopy(dict(record))
    return {user: record for user, record in good.items() if held[user] == 1}


@dataclass(frozen=True, repr=False)
class Directory:
    """Person records by user id, only valid and unambiguous ones (built by `of`; direct construction is
    re-checked the same way). Treat the records as read-only: `get` hands out copies."""

    persons: Mapping[str, Mapping[str, Any]]

    def __post_init__(self) -> None:
        records = self.persons.values() if isinstance(self.persons, Mapping) else ()
        object.__setattr__(self, "persons", MappingProxyType(_admit(records)))

    def __repr__(self) -> str:  # a count, never a name, alias or address
        return f"Directory(persons={len(self.persons)})"

    @classmethod
    def of(cls, persons: Iterable[Mapping[str, Any]]) -> Directory:
        """Keeps each record that conforms to person.schema.json, keyed by its `id`. A record that fails its
        schema is dropped; an id held by two records drops both. Never raises."""
        try:
            records = list(persons)
        except Exception:
            records = []
        return cls({str(i): p for i, p in enumerate(records)})

    def get(self, user: str) -> Mapping[str, Any] | None:
        record = self.record(user)
        return None if record is None else copy.deepcopy(dict(record))

    def record(self, user: Any) -> Mapping[str, Any] | None:
        """The stored record itself (no copy) for in-package decisions; never mutate it."""
        return self.persons.get(user) if isinstance(user, str) else None

    def is_member(self, user: str, team: str, now: str) -> bool:
        """`user` is in the directory and has a membership for `team` whose `assigned_by.by` is in the
        directory, of the user's own org, with org_role "owner", and `assigned_by.at <= now`."""
        person = self.record(user)
        if person is None or not isinstance(team, str) or not is_timestamp(now):
            return False
        for membership in person["memberships"]:
            if membership["team"] != team:
                continue
            assigner = self.record(membership["assigned_by"]["by"])
            if (
                assigner is not None
                and assigner["org_id"] == person["org_id"]
                and assigner["org_role"] == "owner"
                and membership["assigned_by"]["at"] <= now
            ):
                return True
        return False

    def teammates(self, a: str, b: str, now: str) -> bool:
        """Both in the directory, of one org, and members of at least one common team at `now`."""
        first, second = self.record(a), self.record(b)
        if first is None or second is None or first["org_id"] != second["org_id"]:
            return False
        return any(
            self.is_member(a, m["team"], now) and self.is_member(b, m["team"], now) for m in first["memberships"]
        )
