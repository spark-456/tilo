"""FR-HIL-09 (PRD 10.1, 10.6): "Roles and redaction as in 10.1: a Viewer's API responses never
contain hidden-district names." SEC-07 (PRD 16.4): "Redacted event views per role: scoped users
never receive hidden names or counts." Routes and shapes pinned in
services/api/tests/API_ST3a.md (round 2, after code/security/qa review round 1 failed on: a
403/404 membership oracle on both GET routes, a scoped view leaking the underlying store `seq`
(letting a viewer count hidden events) and a dangling `cause`, and a malformed district record
raising instead of failing closed): GET /worlds/{world_id}/events and GET /worlds/{world_id}
filtered by the caller's Principal.districts, the owner always seeing everything, but never a
malformed district record.
"""

from __future__ import annotations

import json
from types import SimpleNamespace

from _api_lib import OWNER, WORLD, as_principal, base_event, make_district, make_principal, make_world, ulid
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

D1, D2 = "D1", "D2"
OTHER_WORLD = "w_other_owners_world"


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
    assert seqs == {1, 2}, "D2's event (store seq 2) must be dropped and the view's own seq renumbered densely"
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

    assert {e["seq"] for e in events_resp.json()["events"]} == {1, 2}
    text = json.dumps(events_resp.json())
    assert "Mail agent" not in text

    body = world_resp.json()
    assert {d["id"] for d in body["districts"]} == {D2}
    assert D1 not in json.dumps(body)


def test_SEC_07_viewer_with_no_shared_districts_sees_only_vis_all(client, store):
    _two_district_world(store)
    as_principal(make_principal(user_id="u_viewer", role="viewer", districts=()))

    resp = client.get(f"/worlds/{WORLD}/events")

    assert {e["seq"] for e in resp.json()["events"]} == {1}


def test_SEC_07_events_view_seq_is_its_own_dense_sequence(client, store):
    """Round-1 finding: a scoped response returned the store's own seq, so a viewer could count
    the gap between seq 1 and seq 3 to learn an event was hidden between them. PRD 15.3's
    "views/{scope}/events/{seq}" is a distinct sequence per view: the returned seq is dense and
    starts at 1, in the order the visible events survive filtering; every other field (id, ts,
    ...) of a kept event is untouched."""
    _two_district_world(store)
    as_principal(make_principal(user_id="u_viewer", role="viewer", districts=(D1,)))

    resp = client.get(f"/worlds/{WORLD}/events")

    events = resp.json()["events"]
    assert [e["seq"] for e in events] == [1, 2]
    # The kept events are the store's real seq 1 and seq 3 (seq 2, D2's, is hidden); their real
    # ids are untouched even though their view seq is renumbered.
    assert events[0]["id"] == ulid(1)
    assert events[1]["id"] == ulid(3)


def test_SEC_07_cause_naming_a_hidden_event_is_nulled(client, store):
    """Round-1 finding: `cause` was passed through unchanged, so a viewer could read the id of an
    event it could never itself fetch. A `cause` naming a filtered-out event must be null; a
    `cause` naming a visible event is untouched."""
    store.worlds[WORLD] = make_world(
        owner=OWNER,
        districts={D1: make_district("Mail", "Triaging the inbox"), D2: make_district("Finance Ops", "Ledger")},
    )
    store.events[WORLD] = [
        base_event(seq=1, type_="agent.working", data={}, district=D2, vis=[D2], summary="hidden from the viewer"),
        base_event(
            seq=2,
            type_="agent.working",
            data={},
            district=D1,
            vis=[D1],
            summary="visible, caused by the hidden event",
            cause=ulid(1),
        ),
        base_event(
            seq=3,
            type_="world.started",
            data={"budget_cap": 40},
            vis="all",
            summary="visible, caused by another visible event",
            cause=ulid(2),
        ),
    ]
    as_principal(make_principal(user_id="u_viewer", role="viewer", districts=(D1,)))

    resp = client.get(f"/worlds/{WORLD}/events")

    events = resp.json()["events"]
    assert len(events) == 2
    by_id = {e["id"]: e for e in events}
    assert by_id[ulid(2)]["cause"] is None, "cause names a hidden event (seq 1) -- must be nulled"
    assert by_id[ulid(3)]["cause"] == ulid(2), "cause names a visible event -- must be untouched"


def test_SEC_07_get_world_malformed_district_record_fails_closed(client, store):
    """A district record that is None, or that is missing usable name/summary fields, must be
    treated as hidden -- left out of `districts`, counted in `has_hidden_districts` -- and must
    never 500, even for the owner (a value tilo-api cannot safely read cannot be honestly shown
    to anyone)."""
    store.worlds[WORLD] = make_world(
        owner=OWNER,
        districts={
            D1: make_district("Mail", "Triaging the inbox"),
            "D8": None,
            "D9": SimpleNamespace(name="Incomplete"),  # no .summary -- malformed, not just empty
        },
    )
    as_principal(make_principal(user_id=OWNER, role="owner"))

    resp = client.get(f"/worlds/{WORLD}")

    assert resp.status_code == 200
    body = resp.json()
    assert {d["id"] for d in body["districts"]} == {D1}
    assert body["has_hidden_districts"] is True
    text = json.dumps(body)
    assert "D8" not in text
    assert "D9" not in text
    assert "Incomplete" not in text


def test_SEC_07_get_events_non_member_gets_the_same_404_as_unknown_world(client, store):
    _two_district_world(store)

    # Case 1: membership matches a world that genuinely does not exist.
    as_principal(make_principal(user_id="u_someone", role="owner", world_id="w_does_not_exist"))
    resp_unknown_world = client.get("/worlds/w_does_not_exist/events")

    # Case 2: the world exists, but this principal belongs to a different one.
    as_principal(make_principal(user_id="u_someone", role="owner", world_id=OTHER_WORLD))
    resp_wrong_membership = client.get(f"/worlds/{WORLD}/events")

    assert resp_unknown_world.status_code == 404
    assert resp_wrong_membership.status_code == 404
    assert resp_unknown_world.json() == resp_wrong_membership.json()


def test_SEC_07_get_events_no_membership_gets_404(client, store):
    _two_district_world(store)
    as_principal(make_principal(user_id="u_nobody", role="viewer", world_id=None))

    resp = client.get(f"/worlds/{WORLD}/events")

    assert resp.status_code == 404


def test_SEC_07_get_world_non_member_gets_the_same_404_as_unknown_world(client, store):
    _two_district_world(store)

    as_principal(make_principal(user_id="u_someone", role="owner", world_id="w_does_not_exist"))
    resp_unknown_world = client.get("/worlds/w_does_not_exist")

    as_principal(make_principal(user_id="u_someone", role="owner", world_id=OTHER_WORLD))
    resp_wrong_membership = client.get(f"/worlds/{WORLD}")

    assert resp_unknown_world.status_code == 404
    assert resp_wrong_membership.status_code == 404
    assert resp_unknown_world.json() == resp_wrong_membership.json()


def test_SEC_07_get_world_no_membership_gets_404(client, store):
    _two_district_world(store)
    as_principal(make_principal(user_id="u_nobody", role="viewer", world_id=None))

    resp = client.get(f"/worlds/{WORLD}")

    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Property test (Hypothesis): for random streams and random vis/district assignments, a scoped
# Viewer's or Team Lead's serialized response never contains a hidden district's id, name, or any
# string that appears only in a hidden district's events, and the events view's own `seq` is
# always dense (no gaps a hidden event could leave for the viewer to count). District ids are
# capped at D1..D9 and every marker embeds its own single-digit index so no marker is ever a
# substring of another (D1 is not a substring of D2..D9, and "District1Secret" is not a prefix of
# "District2Secret"); this keeps the substring assertions below free of false positives from
# coincidental overlaps.

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

    seen_events = events_resp.json()["events"]
    # The view's own seq is dense: 1..len(seen_events), whatever the store's real seq gaps are.
    assert [e["seq"] for e in seen_events] == list(range(1, len(seen_events) + 1))

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
