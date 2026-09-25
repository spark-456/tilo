"""FR-HIL-09 (PRD 10.1, 10.6): "Roles and redaction as in 10.1: a Viewer's API responses never
contain hidden-district names." SEC-07 (PRD 16.4): "Redacted event views per role: scoped users
never receive hidden names or counts." Routes and shapes pinned in
services/api/tests/API_ST3a.md: GET /worlds/{world_id}/events and GET /worlds/{world_id} filtered
by the caller's Principal.districts, the owner always seeing everything.
"""

from __future__ import annotations

import json

from _api_lib import OWNER, WORLD, as_principal, base_event, make_district, make_principal, make_world
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

D1, D2 = "D1", "D2"


def _two_district_world(store):
    """Populates the given (fixture) store in place with a two-district world."""
    store.worlds[WORLD] = make_world(
        owner=OWNER,
        districts={
            D1: make_district("Mail", "Triaging the inbox"),
            D2: make_district("Finance Ops", "Reconciling the ledger"),
        },
    )
    store.events[WORLD] = [
        base_event(
            seq=1, type_="agent.working", data={}, district=D1, vis=[D1], summary="Mail agent is drafting a reply"
        ),
        base_event(
            seq=2,
            type_="agent.working",
            data={},
            district=D2,
            vis=[D2],
            summary="Finance agent is posting a ledger entry",
        ),
        base_event(seq=3, type_="world.started", data={"budget_cap": 40}, vis="all", summary="The world started"),
    ]


def test_FR_HIL_09_owner_sees_everything(client, store):
    _two_district_world(store)
    as_principal(make_principal(user_id=OWNER, role="owner"))

    events_resp = client.get(f"/worlds/{WORLD}/events")
    world_resp = client.get(f"/worlds/{WORLD}")

    assert events_resp.status_code == 200
    assert {e["seq"] for e in events_resp.json()["events"]} == {1, 2, 3}

    assert world_resp.status_code == 200
    body = world_resp.json()
    assert {d["id"] for d in body["districts"]} == {D1, D2}
    assert body["has_hidden_districts"] is False


def test_SEC_07_viewer_never_sees_hidden_district_events(client, store):
    _two_district_world(store)
    # A Viewer with shared scope covering only D1 (PRD 10.1 "Shared scope").
    as_principal(make_principal(user_id="u_viewer", role="viewer", districts=(D1,)))

    resp = client.get(f"/worlds/{WORLD}/events")

    assert resp.status_code == 200
    events = resp.json()["events"]
    seqs = {e["seq"] for e in events}
    assert seqs == {1, 3}, "D2's event (seq 2) must be dropped, not just redacted in place"
    for e in events:
        assert "Finance" not in json.dumps(e)
        assert "ledger" not in json.dumps(e)


def test_SEC_07_viewer_never_sees_hidden_district_name_or_summary(client, store):
    _two_district_world(store)
    as_principal(make_principal(user_id="u_viewer", role="viewer", districts=(D1,)))

    resp = client.get(f"/worlds/{WORLD}")

    assert resp.status_code == 200
    body = resp.json()
    ids = {d["id"] for d in body["districts"]}
    assert ids == {D1}
    assert body["has_hidden_districts"] is True
    text = json.dumps(body)
    assert D2 not in text
    assert "Finance Ops" not in text
    assert "Reconciling the ledger" not in text


def test_FR_HIL_09_team_lead_sees_only_domain_districts(client, store):
    _two_district_world(store)
    # A Team Lead whose domain covers D2 only (PRD 10.1 "Their districts plus summaries").
    as_principal(make_principal(user_id="u_finance_lead", role="team_lead", domain="finance", districts=(D2,)))

    events_resp = client.get(f"/worlds/{WORLD}/events")
    world_resp = client.get(f"/worlds/{WORLD}")

    assert {e["seq"] for e in events_resp.json()["events"]} == {2, 3}
    text = json.dumps(events_resp.json())
    assert "Mail agent" not in text

    body = world_resp.json()
    assert {d["id"] for d in body["districts"]} == {D2}
    assert D1 not in json.dumps(body)


def test_SEC_07_viewer_with_no_shared_districts_sees_only_vis_all(client, store):
    _two_district_world(store)
    as_principal(make_principal(user_id="u_viewer", role="viewer", districts=()))

    resp = client.get(f"/worlds/{WORLD}/events")

    assert {e["seq"] for e in resp.json()["events"]} == {3}


# ---------------------------------------------------------------------------
# Property test (Hypothesis): for random streams and random vis/district assignments, a scoped
# Viewer's or Team Lead's serialized response never contains a hidden district's id, name, or any
# string that appears only in a hidden district's events. District ids are capped at D1..D9 and
# every marker embeds its own single-digit index so no marker is ever a substring of another
# (D1 is not a substring of D2..D9, and "District1Secret" is not a prefix of "District2Secret");
# this keeps the substring assertions below free of false positives from coincidental overlaps.

_ALL_VIS_MARKER = "AllVisMarkerSecret"


@st.composite
def _redaction_case(draw):
    n = draw(st.integers(min_value=2, max_value=9))
    district_ids = [f"D{i}" for i in range(1, n + 1)]
    visible = draw(st.sets(st.sampled_from(district_ids), max_size=n))
    events_per_district = draw(st.lists(st.integers(min_value=0, max_value=2), min_size=n, max_size=n))
    role = draw(st.sampled_from(["viewer", "team_lead"]))
    return district_ids, visible, events_per_district, role


@settings(max_examples=40, deadline=None, suppress_health_check=[HealthCheck.function_scoped_fixture])
@given(case=_redaction_case())
def test_FR_HIL_09_SEC_07_property_hidden_district_content_never_leaks(client, store, case):
    district_ids, visible, events_per_district, role = case

    districts = {
        did: make_district(f"District{i}Secret", f"Summary{i}Secret") for i, did in enumerate(district_ids, start=1)
    }
    store.worlds[WORLD] = make_world(owner=OWNER, districts=districts)

    events = [base_event(seq=1, type_="world.started", data={}, vis="all", summary=_ALL_VIS_MARKER)]
    seq = 2
    for i, did in enumerate(district_ids, start=1):
        for k in range(events_per_district[i - 1]):
            events.append(
                base_event(
                    seq=seq,
                    type_="agent.working",
                    data={},
                    district=did,
                    vis=[did],
                    summary=f"Marker{i}_{k}Secret",
                )
            )
            seq += 1
    store.events[WORLD] = events

    hidden_ids = [d for d in district_ids if d not in visible]

    as_principal(
        make_principal(
            user_id="u_scoped",
            role=role,
            domain="finance" if role == "team_lead" else None,
            districts=tuple(visible),
        )
    )

    events_resp = client.get(f"/worlds/{WORLD}/events")
    world_resp = client.get(f"/worlds/{WORLD}")
    assert events_resp.status_code == 200
    assert world_resp.status_code == 200

    combined_text = json.dumps(events_resp.json()) + json.dumps(world_resp.json())

    # No hidden district's id, name, or summary leaks.
    for did in hidden_ids:
        i = district_ids.index(did) + 1
        assert did not in combined_text, f"hidden district id {did} leaked"
        assert f"District{i}Secret" not in combined_text
        assert f"Summary{i}Secret" not in combined_text
        # No event marker that exists only under a hidden district leaks either.
        for k in range(events_per_district[district_ids.index(did)]):
            assert f"Marker{i}_{k}Secret" not in combined_text

    # Sanity: the response is not vacuously empty -- the always-visible event and every visible
    # district's own name/summary/markers do appear.
    assert _ALL_VIS_MARKER in combined_text
    for did in visible:
        i = district_ids.index(did) + 1
        assert f"District{i}Secret" in combined_text
