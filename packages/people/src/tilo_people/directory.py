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

    def counts(self, person: Mapping[str, Any], m: Mapping[str, Any], now: str) -> bool:
        """One `memberships` entry of a stored `person` counts at `now` (people.rules.md "Terms", ADR-0044): an org
        owner's assignment; the founding entry its creator assigned themselves with `lead: true`; or, without
        `lead: true`, an invitation by a lead of the team (a lead since no later than the invitation) that the person
        accepted between the invitation and `now`. The directory must hold the whole org (the founding check)."""
        a = self.record(m["assigned_by"]["by"])
        if a is None or a["org_id"] != person["org_id"] or m["assigned_by"]["at"] > now:
            return False
        if a["org_role"] == "owner":
            return True
        if m.get("lead") is True:
            return a["id"] == person["id"] and self._founding(person, m)
        at, accepted = m["assigned_by"]["at"], m.get("accepted_at")
        return accepted is not None and at <= accepted <= now and self.invited_by_a_lead(m, now)

    def _founding(self, person: Mapping[str, Any], m: Mapping[str, Any]) -> bool:
        """`m` is strictly earlier than every other entry for its team in the org (a tie founds nothing)."""
        at, team = m["assigned_by"]["at"], m["team"]
        return all(
            at < o["assigned_by"]["at"]
            for q in self.persons.values()
            if q["org_id"] == person["org_id"]
            for o in q["memberships"]
            if o is not m and o["team"] == team
        )

    def _lead_entries(self, user: str, team: str, now: str) -> list[Mapping[str, Any]]:
        p = self.record(user)
        if p is None:
            return []
        return [m for m in p["memberships"] if m["team"] == team and m.get("lead") is True and self.counts(p, m, now)]

    def invited_by_a_lead(self, m: Mapping[str, Any], now: str) -> bool:
        """`m`'s assigner leads its team at `now` through a lead entry assigned no later than `m` (no revival)."""
        leads = self._lead_entries(m["assigned_by"]["by"], m["team"], now)
        return m.get("lead") is not True and any(e["assigned_by"]["at"] <= m["assigned_by"]["at"] for e in leads)

    def is_lead(self, user: str, team: str, now: str) -> bool:
        """`user` leads `team` at `now`: a `lead: true` entry that counts (an owner's, or the founding one)."""
        if not isinstance(team, str) or not is_timestamp(now):
            return False
        return bool(self._lead_entries(user, team, now))

    def is_member(self, user: str, team: str, now: str) -> bool:
        """`user` is in the directory and has an entry for `team` that `counts` at `now` (amended "Terms")."""
        person = self.record(user)
        if person is None or not isinstance(team, str) or not is_timestamp(now):
            return False
        return any(m["team"] == team and self.counts(person, m, now) for m in person["memberships"])

    def teammates(self, a: str, b: str, now: str) -> bool:
        """Both in the directory, of one org, and members of at least one common team at `now`."""
        first, second = self.record(a), self.record(b)
        if first is None or second is None or first["org_id"] != second["org_id"]:
            return False
        return any(
            self.is_member(a, m["team"], now) and self.is_member(b, m["team"], now) for m in first["memberships"]
        )
