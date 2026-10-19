"""PPL-11c guards: behaviour that is true today and that the rest of the people API must keep true. These are never
pending (they pass on `phase0-stack` now); a slice that breaks one fails its own review. API_PPL_11c.md section 9.
"""

from __future__ import annotations

import pathlib

import pytest
from _ppl11a_lib import OWNER, PRIYA, u
from _ppl11c_lib import PERSON_BODY, confirmed_item, gone_meeting, transcript_case
from _sec15_lib import PINNED_PUBLIC_ROUTES

CONTRACTS = pathlib.Path(__file__).resolve().parents[3] / "contracts"
GOOD_EMAILS = ["nina@example.com", "n.p+tag@sub.example.co.uk", "A_B-c@Example.COM", "o'brien@example.com"]
ALREADY_REFUSED_EMAILS = {
    "line separator": "ni" + u(0x2028) + "na@example.com",
    "tab": "ni\tna@example.com",
    "space": "ni na@example.com",
    "display name form": "Nina <nina@example.com>",
    "two addresses": "a@example.com,b@example.com",
    "no dot in the domain": "nina@localhost",
    "two at signs": "a@b@example.com",
    "over 254 characters": "a" * 250 + "@example.com",
    "no-break space": "ni na@example.com",
    "empty": "",
}


def test_PPL_11c_PE_12_the_two_work_item_events_are_registered_and_fixtured():
    """`work_item.created` and `work_item.changed` need no contract change: each has a registry entry, a data schema
    and a valid fixture (the S5 slice emits only these)."""
    registry = (CONTRACTS / "events" / "registry.yaml").read_text(encoding="utf-8")
    for type_ in ("work_item.created", "work_item.changed"):
        assert f"\n  {type_}:\n" in registry, f"{type_} is not registered"
        assert (CONTRACTS / "events" / "data" / f"{type_}.schema.json").is_file()
        assert (CONTRACTS / "fixtures" / "events" / "valid" / f"{type_}.json").is_file()


@pytest.mark.parametrize("email", list(ALREADY_REFUSED_EMAILS.values()), ids=list(ALREADY_REFUSED_EMAILS))
def test_PPL_11c_PE_09_an_email_the_contract_already_refuses_stays_a_422(people_rig, email):
    rig = people_rig()
    rig.add_people()
    rig.as_user(OWNER)
    before = rig.snapshot()
    assert rig.client.post("/v1/people", json={**PERSON_BODY, "email": email}).status_code == 422
    assert rig.snapshot() == before


@pytest.mark.parametrize("email", GOOD_EMAILS)
def test_PPL_11c_PE_09_an_ordinary_address_is_accepted_and_stored_as_typed(people_rig, email):
    """The stricter email rule (slice 3) must not turn a real address away."""
    rig = people_rig()
    rig.add_people()
    rig.as_user(OWNER)
    response = rig.post("/v1/people", {**PERSON_BODY, "email": email})
    assert response.status_code == 201, response.text[:200]
    assert rig.stored("persons", response.json()["id"])["email"] == email


@pytest.mark.parametrize("status", ["discarded", "deleted"])
def test_PPL_11c_PE_23_an_item_whose_assigner_is_the_owner_still_gets_expired_from_a_gone_meeting(people_rig, status):
    """The stricter gone path (assigner must be the owner) leaves the honest case alone: the item's owner is still told
    `expired`, naming the lowest utterance the item cites, with no transcript."""
    rig = people_rig()
    rig.add_people()
    rig.add("meetings", gone_meeting(transcript_case()["meeting"], status))
    rig.add("work_items", confirmed_item())
    rig.as_user(PRIYA)
    response = rig.get("/v1/work-items/wi_rate_sheet/quote")
    assert response.status_code == 200
    assert [(q["utterance_id"], q["state"], q["transcript"]) for q in response.json()["quotes"]] == [
        ("u0021", "expired", None)
    ]


def test_PPL_11c_PE_23_an_item_whose_meeting_is_missing_still_gets_expired_and_a_stranger_nothing(people_rig):
    rig = people_rig()
    rig.add_people()
    rig.add("work_items", confirmed_item())
    rig.as_user(PRIYA)
    assert [q["state"] for q in rig.get("/v1/work-items/wi_rate_sheet/quote").json()["quotes"]] == ["expired"]
    rig.as_user(OWNER)  # the assigner: no quote, the item's own 404
    assert rig.get("/v1/work-items/wi_rate_sheet/quote").status_code == 404


def test_PPL_11c_SEC_15_no_people_route_is_public_and_the_public_list_is_the_pinned_one(people_rig):
    from tilo_api import access  # noqa: PLC0415

    people_rig()
    assert access.PUBLIC_ROUTES == PINNED_PUBLIC_ROUTES, "a new public route is the owner's decision"
