"""PEOPLE-SEAMS-1 (security review r1, BQ-PEOPLESEAMS1-6, supervisor decision): `POST /worlds/{id}/cards/{id}/share`
names an Approver only from the org's people directory. Anyone else (an unknown `u_` id, a person of another org, a
directory that cannot be read) is one fixed 403, so the answer never says whether the id exists elsewhere, and the gate
is left alone. The owner naming themself is still the 422 it always was."""

from __future__ import annotations

import pytest
from _cards_lib import FakeClock, FakeEventWriter, load_valid_card, new_ulid, principal
from _peopleseams1_lib import directory
from fastapi import FastAPI
from fastapi.testclient import TestClient
from tilo_api import cards, deps, sharing
from tilo_api.cards import CardStore

W, OWNER, MEMBER, STRANGER = "w_01", "u_owner", "u_ps1_member", "u_ps1_stranger"
START = "2026-09-29T09:30:00.000Z"
FORBIDDEN = {"outcome": "rejected", "reason": "not_allowed"}


class _Rig:
    def __init__(self, stores) -> None:
        self.store = CardStore(clock=FakeClock(START), writer=FakeEventWriter(), world_owners={W: OWNER})
        self.card = load_valid_card("gate_send_reply")
        assert self.store.submit(self.card, outbox_id=new_ulid("ps1-ob")).outcome == "accepted"
        app = FastAPI()
        app.include_router(cards.build_router(self.store))
        app.include_router(sharing.build_router(self.store))
        app.dependency_overrides[deps.get_current_principal] = lambda: principal("owner", OWNER, W)
        if stores is not None:
            app.dependency_overrides[deps.get_people_stores] = stores
        self.client = TestClient(app)

    def share(self, approver: str):
        return self.client.post(f"/worlds/{W}/cards/{self.card['id']}/share", json={"approver": approver})

    def untouched(self) -> bool:
        return [c["id"] for c in self.store.list_for_world(W, principal=principal("owner", OWNER, W))] == [
            self.card["id"]
        ]


def test_PEOPLE_SEAMS_1_SEC_an_approver_who_is_in_the_directory_may_be_named():
    rig = _Rig(lambda: directory(OWNER, MEMBER))
    response = rig.share(MEMBER)
    assert response.status_code == 201 and response.json()["token"]


@pytest.mark.parametrize("who", [STRANGER, "u_ps1_other_org"])
def test_PEOPLE_SEAMS_1_SEC_an_unknown_id_and_a_person_of_another_org_are_the_same_fixed_403(who):
    stores = directory(OWNER, MEMBER)
    for uid in ("u_ps1_other_org",):
        stores.persons.create(next(iter(directory(uid, org="org_elsewhere").persons.list("org_elsewhere"))).record)
    rig = _Rig(lambda: stores)
    refused = rig.share(who)
    assert refused.status_code == 403 and refused.json() == FORBIDDEN
    assert rig.share("u_ps1_missing").json() == refused.json(), "an existing id elsewhere reads like an unknown one"
    assert rig.untouched(), "no second card, no link"


def test_PEOPLE_SEAMS_1_SEC_the_owner_naming_themself_is_still_refused_as_before():
    rig = _Rig(lambda: directory(OWNER, MEMBER))
    response = rig.share(OWNER)
    assert response.status_code == 422 and response.json()["reason"] == "owner_needs_no_link"


def test_PEOPLE_SEAMS_1_SEC_a_directory_that_cannot_be_read_or_is_not_configured_fails_closed():
    def down():
        raise RuntimeError("the people store is down")

    for stores in (down, None):  # None: the production default with nothing wired (the seam refuses)
        rig = _Rig(stores)
        refused = rig.share(MEMBER)
        assert refused.status_code == 403 and refused.json() == FORBIDDEN, stores
        assert rig.untouched()
