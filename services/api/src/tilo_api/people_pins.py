"""FR-PB-01/02/05: indexed lists and caller-owned writes through the existing people oracle."""

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Literal

from tilo_people.access import AccessRequest, decide, read
from tilo_people.directory import Directory
from tilo_policy.schemas import conforms

from tilo_api import deps
from tilo_api.people_access import request_parts
from tilo_api.people_quotes import MAX_HISTORY
from tilo_api.people_writes import Refusal, Text, Writer, _Closed, _mint


class PinIn(_Closed):
    title: Text
    body: Text | None = None
    kind: Literal["note", "decision", "deadline", "link"] = "note"
    url: Text | None = None
    team: Text | None = None


def _directory(w: Writer, owner: str | None = None) -> Directory:
    # Membership stamps need their assigning org owner. Read only those ids, never the org directory.
    rows = {}
    for user in {w.actor, owner} - {None}:
        stored = w.stores.persons.get(w.org, user)
        if stored is not None:
            rows[user] = stored.record
    assigners = {m["assigned_by"]["by"] for row in rows.values() for m in row["memberships"]}
    for user in assigners - rows.keys():
        stored = w.stores.persons.get(w.org, user)
        if stored is not None:
            rows[user] = stored.record
    return Directory.of(rows.values())


def create_pin(w: Writer, body: PinIn) -> dict[str, Any]:
    directory = _directory(w) if body.team is not None else w.directory()
    record = {
        "id": _mint("pb"),
        "org_id": w.org,
        "scope": {"kind": "personal", "user": w.actor} if body.team is None else {"kind": "team", "team": body.team},
        "title": w.text(body.title),
        "body": None if body.body is None else w.text(body.body),
        "kind": body.kind,
        "url": None if body.url is None else w.text(body.url),
        "owner": None,
        "due": None,
        "status": "active",
        "created_by": {"by": "person", "ref": w.actor, "at": w.now},
        "set_up_by": w.actor,
        "source": None,
        "confirmed_by": None,
        "flagged": False,
        "history": [{"at": w.now, "by": w.actor, "change": "created", "status": "active"}],
        "created_at": w.now,
        "updated_at": w.now,
    }
    return w.create("pinboard_item", record, w.stores.pins, directory)


def delete_pin(w: Writer, pin_id: str, owners: deps.SourceOwners) -> dict[str, Any]:
    directory = _directory(w)
    parts = request_parts(
        w.stores,
        actor=w.actor,
        org_id=w.org,
        record_kind="pinboard_item",
        record_id=pin_id,
        now=w.now,
        source_owners=_Owners(owners),
    )
    if parts is None:
        raise Refusal(404, "not_found")
    pin = parts["record"]
    request = AccessRequest(action="edit", **parts)
    if not decide(request, directory).allowed:
        raise Refusal(404, "not_found")
    if pin["owner"] is not None:
        directory = _directory(w, pin["owner"])
    if pin["status"] == "removed" or len(pin["history"]) >= MAX_HISTORY:
        raise Refusal(409, "write_refused")
    stored = w.stores.pins.get(w.org, pin_id)
    if stored is None or stored.record != pin:
        raise Refusal(409, "version_conflict")
    change = "undone" if pin["created_by"]["by"] == "tilo" and pin["scope"]["kind"] == "personal" else "removed"
    after = {
        **pin,
        "status": "removed",
        "updated_at": w.now,
        "history": [*pin["history"], {"at": w.now, "by": w.actor, "change": change, "status": "removed"}],
    }
    if not conforms("pinboard_item.schema.json", after):
        raise Refusal(422, "invalid_record")
    w.commit(request, after, w.stores.pins, directory, Refusal(404, "not_found"), version=stored.version)
    return after


@dataclass(frozen=True)
class _Owners:
    seam: deps.SourceOwners

    def owner_of(self, org_id: str, record_kind: str, record: Mapping[str, Any]) -> str | None:
        source = record["source"]
        return self.seam.owner_of(source["kind"], source["ref"])


def list_pins(w: Writer, owners: deps.SourceOwners) -> dict[str, Any]:
    directory = w.org_directory()
    person = directory.record(w.actor)
    if person is None:
        raise Refusal(404, "not_found")
    indexes = [("scope.user", w.actor), ("set_up_by", w.actor)]
    indexes.extend(
        ("scope.team", m["team"]) for m in person["memberships"] if directory.is_member(w.actor, m["team"], w.now)
    )
    candidates = {s.record["id"] for index, value in indexes for s in w.stores.pins.list(w.org, index, value)}
    rows = []
    for pin_id in sorted(candidates):
        parts = request_parts(
            w.stores,
            actor=w.actor,
            org_id=w.org,
            record_kind="pinboard_item",
            record_id=pin_id,
            now=w.now,
            source_owners=_Owners(owners),
        )
        if parts is not None:
            if parts["record"]["status"] == "removed":
                continue
            got = read(AccessRequest(action="read_full", **parts), directory)
            if got is not None:
                rows.append(got)
    rows.sort(key=lambda row: (row["created_at"], row["id"]))
    return {"items": rows[:200], "truncated": len(rows) > 200}
