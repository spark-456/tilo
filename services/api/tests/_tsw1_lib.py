"""Rig for the TSW-1 tests (BQ-CTX-TEAMWORLD, ADR-0040): one org, a few people, one world owned by Asha and shared
(or not) with team `tm_launch`, the real `tilo_api.app` over the in-memory stores, explicit principals.

Not a test module. No business logic: it builds plain records and wires the seams the routes already have.
"""

from __future__ import annotations

import hashlib
from typing import Any

from _api_lib import FakeEventWriter, make_district, make_store
from fastapi.testclient import TestClient
from tilo_api import app, deps
from tilo_people.stores import PeopleStores

ORG = deps.ORG_ID
WORLD = "w_launch_plan"
OTHER_WORLD = "w_ops_plan"
LAUNCH, OPS = "tm_launch", "tm_ops"
ORGOWNER, ASHA, BEN, CARA, DEV = "u_orgowner", "u_asha", "u_ben", "u_cara", "u_dev"
T_MEMBER = "2026-10-01T09:00:00.000Z"  # when the memberships were assigned
T_GRANT = "2026-10-02T09:00:00.000Z"  # a share granted by Asha, after her membership
NOW = "2026-10-10T09:00:00.000Z"
LATER = "2026-10-11T09:00:00.000Z"


def share_id(world_id: str, team: str) -> str:
    return "ws_" + hashlib.sha256(f"{world_id}/{team}".encode()).hexdigest()[:32]


def person(uid: str, *, role: str = "member", teams: tuple[str, ...] = (), org: str = ORG, at: str = T_MEMBER) -> dict:
    return {
        "id": uid,
        "org_id": org,
        "display_name": f"Person {uid[2:]}",
        "aliases": [],
        "email": f"{uid[2:]}@example.com",
        "time_zone": "Asia/Kolkata",
        "preferred_channel": "web",
        "org_role": role,
        "memberships": [{"team": t, "assigned_by": {"by": ORGOWNER, "at": at}} for t in teams],
        "created_by": {"by": ORGOWNER, "at": at},
    }


def share(*, team: str = LAUNCH, world: str = WORLD, by: str = ASHA, at: str = T_GRANT, revoked: Any = None) -> dict:
    return {
        "id": share_id(world, team),
        "org_id": ORG,
        "world_id": world,
        "team": team,
        "granted_by": {"by": by, "at": at},
        "revoked": revoked,
    }


def web(uid: str, **kw: Any) -> deps.Principal:
    """A full web sign-in session bound to no world: what a deployed sign-in resolves to."""
    return deps.Principal(user_id=uid, role="owner", world_id=None, channel="web", full_session=True, **kw)


class Rig:
    def __init__(self, *, writer: Any = None) -> None:
        districts = {"D1": make_district("Design", "design summary"), "D2": make_district("Build", "build summary")}
        self.store = make_store(worlds={WORLD: deps.WorldRecord(owner=ASHA, districts=districts, run_id="r_launch_1")})
        self.store.worlds[OTHER_WORLD] = deps.WorldRecord(owner=ASHA, districts={}, run_id="r_ops_1")
        self.writer = writer or FakeEventWriter(self.store)
        self.people = PeopleStores.in_memory()
        self.now = NOW
        self.people_error: Exception | None = None
        for p in (
            person(ORGOWNER, role="owner", teams=(LAUNCH, OPS)),
            person(ASHA, teams=(LAUNCH,)),
            person(BEN, teams=(LAUNCH,)),
            person(CARA, teams=(OPS,)),
            person(DEV, teams=(LAUNCH,), org="org_elsewhere"),
        ):
            self.people.persons.create(p)
        self.principal: deps.Principal = web(ASHA)
        app.dependency_overrides[deps.get_store] = lambda: self.store
        app.dependency_overrides[deps.get_event_writer] = lambda: self.writer
        app.dependency_overrides[deps.get_people_stores] = self._people
        app.dependency_overrides[deps.get_clock] = lambda: lambda: self.now
        app.dependency_overrides[deps.get_current_principal] = lambda: self.principal
        self.client = TestClient(app, raise_server_exceptions=False)

    def _people(self) -> PeopleStores:
        if self.people_error is not None:
            raise self.people_error
        return self.people

    def as_(self, principal: deps.Principal) -> Rig:
        self.principal = principal
        return self

    def grant(self, **kw: Any) -> dict:
        """A share record written straight into the store (a state the routes could also have made)."""
        record = share(**kw)
        self.people.world_shares.create(record)
        return record

    def shares(self) -> list[dict]:
        return [s.record for s in self.people.world_shares.list(ORG)]

    def events_of(self, world: str = WORLD, type_: str | None = None) -> list[dict]:
        found = self.store.events.get(world, [])
        return [e for e in found if type_ is None or e["type"] == type_]


# --- TSW-1b: layout, work items of the shared world -----------------------------------------------------------------
LAYOUT = {
    "v": "1.0",
    "world_id": WORLD,
    "tier": "village",
    "theme": "metropolis",
    "geometry": None,
    "semantic": {
        "levels": [
            {
                "id": "L1",
                "name": "Level One",
                "districts": [
                    {
                        "id": d,
                        "name": f"District {d}",
                        "icon": "inbox",
                        "lead": f"A_lead{d[1:]}",
                        "buildings": [
                            {
                                "id": f"B{d[1:]}",
                                "name": "Workshop",
                                "kind": "common",
                                "common_type": "workshop",
                                "plan_units": [f"u{d[1:]}"],
                            }
                        ],
                    }
                    for d in ("D1", "D2")
                ],
            }
        ],
        "islands": [],
        "gates": [],
        "agents": [{"id": "A_director", "rank": "director"}, {"id": "A_lead1", "rank": "lead"}],
    },
}


def work_item(wid: str, owner: str, *, world: str | None = WORLD, status: str = "open", flagged: bool = False) -> dict:
    stamp = "2026-10-03T09:00:00.000Z"
    record: dict[str, Any] = {
        "id": wid,
        "org_id": ORG,
        "owner": owner,
        "title": f"Title of {wid}",
        "due": None,
        "due_text": None,
        "status": status,
        "source": {"kind": "manual", "ref": None, "evidence": []},
        "created_by": {"by": "person", "ref": owner, "at": stamp},
        "assigned_by": None,
        "confirmed_by": None,
        "snoozed_until": None,
        "flagged": flagged,
        "history": [{"at": stamp, "by": owner, "change": "created", "status": status}],
        "created_at": stamp,
        "updated_at": stamp,
    }
    if world is not None:
        record["world_id"] = world
    return record
