"""Versioned invite records: process-local in tests, one Firestore document per link in production."""

from __future__ import annotations

import copy
import os
import re
import threading
from collections.abc import Mapping
from typing import Any

from google.api_core import exceptions as gexc
from tilo_people.errors import AlreadyExists, VersionConflict
from tilo_people.stores import PeopleStores, Stored
from tilo_policy.schemas import conforms

_ID = re.compile(r"til_[0-9a-f]{24}")
_ORG = re.compile(r"org_[0-9A-Za-z_]{1,48}")


def _valid(record: Mapping[str, Any]) -> None:
    if not conforms("team_invite_link.schema.json", record):
        raise ValueError("invalid invite record")


class MemoryLinks:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._rows: dict[tuple[str, str], Stored] = {}

    def get(self, org: str, rid: str) -> Stored | None:
        with self._lock:
            row = self._rows.get((org, rid))
            return copy.deepcopy(row)

    def list(self, org: str) -> tuple[Stored, ...]:
        with self._lock:
            return tuple(copy.deepcopy(v) for (o, _), v in self._rows.items() if o == org)

    def create(self, record: Mapping[str, Any]) -> Stored:
        _valid(record)
        key = record["org_id"], record["id"]
        with self._lock:
            if key in self._rows:
                raise AlreadyExists("invite exists")
            row = Stored("team_invite_link", copy.deepcopy(dict(record)), 1)
            self._rows[key] = row
            return copy.deepcopy(row)

    def replace(self, record: Mapping[str, Any], version: int) -> Stored:
        _valid(record)
        key = record["org_id"], record["id"]
        with self._lock:
            old = self._rows.get(key)
            if old is None or old.version != version:
                raise VersionConflict("invite changed")
            row = Stored("team_invite_link", copy.deepcopy(dict(record)), version + 1)
            self._rows[key] = row
            return copy.deepcopy(row)

    def delete(self, org: str, rid: str, version: int) -> None:
        with self._lock:
            old = self._rows.get((org, rid))
            if old is None or old.version != version:
                raise VersionConflict("invite changed")
            del self._rows[(org, rid)]


class FirestoreLinks:
    def __init__(self, client: Any) -> None:
        self._client = client

    def _ref(self, org: str, rid: str) -> Any:
        if _ORG.fullmatch(org) is None or _ID.fullmatch(rid) is None:
            raise ValueError("invalid invite id")
        return self._client.document(f"orgs/{org}/team_invite_links/{rid}")

    @staticmethod
    def _row(snapshot: Any) -> Stored:
        data = snapshot.to_dict()
        return Stored("team_invite_link", data["record"], data["version"])

    def get(self, org: str, rid: str) -> Stored | None:
        if _ORG.fullmatch(org) is None or _ID.fullmatch(rid) is None:
            return None
        snapshot = self._ref(org, rid).get()
        return self._row(snapshot) if snapshot.exists else None

    def list(self, org: str) -> tuple[Stored, ...]:
        if _ORG.fullmatch(org) is None:
            return ()
        snaps = self._client.collection(f"orgs/{org}/team_invite_links").stream()
        return tuple(self._row(s) for s in snaps)

    def create(self, record: Mapping[str, Any]) -> Stored:
        _valid(record)
        row = Stored("team_invite_link", copy.deepcopy(dict(record)), 1)
        try:
            self._ref(record["org_id"], record["id"]).create({"version": 1, "record": row.record})
        except gexc.AlreadyExists:
            raise AlreadyExists("invite exists") from None
        return row

    def replace(self, record: Mapping[str, Any], version: int) -> Stored:
        _valid(record)
        ref = self._ref(record["org_id"], record["id"])
        snap = ref.get()
        if not snap.exists or snap.get("version") != version:
            raise VersionConflict("invite changed")
        row = Stored("team_invite_link", copy.deepcopy(dict(record)), version + 1)
        try:
            ref.update(
                {"version": row.version, "record": row.record},
                option=self._client.write_option(last_update_time=snap.update_time),
            )
        except (gexc.FailedPrecondition, gexc.Aborted, gexc.NotFound):
            raise VersionConflict("invite changed") from None
        return row

    def delete(self, org: str, rid: str, version: int) -> None:
        ref = self._ref(org, rid)
        snap = ref.get()
        if not snap.exists or snap.get("version") != version:
            raise VersionConflict("invite changed")
        ref.delete(option=self._client.write_option(last_update_time=snap.update_time))


def get_links(stores: PeopleStores) -> MemoryLinks | FirestoreLinks:
    persons = stores.persons
    if os.environ.get("K_SERVICE") or os.environ.get("CLOUD_RUN_JOB"):
        client = getattr(persons, "_client", None)
        if client is None:
            raise NotImplementedError("invite store not configured")
        return FirestoreLinks(client)
    links = getattr(persons, "_invite_links", None)
    if links is None:
        links = MemoryLinks()
        setattr(persons, "_invite_links", links)
    return links
