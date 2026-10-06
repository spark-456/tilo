"""FR-HIL-09 (PRD 10.1, 10.6): "Roles and redaction as in 10.1: a Viewer's API responses never
contain hidden-district names." SEC-07 (PRD 16.4): "Redacted event views per role: scoped users
never receive hidden names or counts." Routes and shapes pinned in
services/api/tests/API_ST3a.md (round 5, after code/security/qa review round 4 failed on: a
scoped view kept an event with a hidden district *nulled* out of `district`/`target`/`actor`/a
`data` leaf instead of dropping the whole event -- a viewer who receives an event at all, even
blanked, still learns something happened in a district it cannot see, which is exactly what SEC-07
"never receive hidden names or counts" rules out; a `data` dict *key* that was itself a district id
or an event ULID was never checked at all, only values were; and deeply nested `data` had no depth
guard, risking a 500 that would take a whole response down, well-formed siblings included). Round
1-4's fixes (the 403/404 membership oracle, the view's own dense `seq` and view-local `id`, a
dangling `cause` nulled/remapped, a malformed district record and a malformed event both failing
closed, Principal.districts of the wrong type never matched by substring, `trace.archive_ref`/
`data.message_ref` always nulled for a scoped viewer, `vis` filtered to the caller's own
intersection, and `data` walked recursively at any depth) are unchanged here and still pinned
below -- except where round 5 explicitly supersedes round 3/4's "null the field, keep the event"
treatment with "drop the whole event," per API_ST3a.md's hidden-district filter.
"""

from __future__ import annotations

import json
from types import SimpleNamespace
from typing import Any

from _api_lib import (
    OWNER,
    WORLD,
    as_principal,
    base_event,
    contracts_dir,
    load_json,
    make_district,
    make_principal,
    make_world,
    ulid,
)
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st
from tilo_api import deps

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
    as_principal(make_principal(user_id="u_finance_lead", role="team_lead", districts=(D2,)))

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
    starts at 1, in the order the visible events survive filtering.

    Round-3 finding (security a, "allowlist, not copy"): the returned `id` is no longer the
    store's real ULID either -- API_ST3a.md pins it as a view-local id derived from the view's
    own dense seq ("v{seq}"), so a scoped viewer can never read a real event id (whose ULID
    ordering would itself hint at how much else happened in the run) even for an event it can
    see. `ts`, `summary` and every other non-identifying field of a kept event stay untouched."""
    _two_district_world(store)
    as_principal(make_principal(user_id="u_viewer", role="viewer", districts=(D1,)))

    resp = client.get(f"/worlds/{WORLD}/events")

    events = resp.json()["events"]
    assert [e["seq"] for e in events] == [1, 2]
    # The kept events are the store's real seq 1 and seq 3 (seq 2, D2's, is hidden); their view id
    # follows the view's own dense seq, never the store's real ulid(1)/ulid(3).
    assert events[0]["id"] == "v1"
    assert events[1]["id"] == "v2"
    text = json.dumps(events)
    assert ulid(1) not in text
    assert ulid(3) not in text

    as_principal(make_principal(user_id=OWNER, role="owner"))
    owner_events = client.get(f"/worlds/{WORLD}/events").json()["events"]
    owner_by_seq = {e["seq"]: e for e in owner_events}
    assert owner_by_seq[1]["id"] == ulid(1), "the owner still sees the real store id, unchanged"
    assert owner_by_seq[3]["id"] == ulid(3)


def test_SEC_07_cause_naming_a_hidden_event_is_nulled(client, store):
    """Round-1 finding: `cause` was passed through unchanged, so a viewer could read the id of an
    event it could never itself fetch. A `cause` naming a filtered-out event must be null.

    Round-3 finding: since `id` is now a view-local id (not the store's real ulid), a `cause`
    naming a *visible* event must be remapped to that event's own view-local id, not the real
    store id it originally named -- a scoped viewer must never see a real store id anywhere in
    the response, including inside another event's `cause`."""
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
    by_seq = {e["seq"]: e for e in events}
    assert by_seq[1]["id"] == "v1"  # the store's real seq 2, view seq 1
    assert by_seq[2]["id"] == "v2"  # the store's real seq 3, view seq 2
    assert by_seq[1]["cause"] is None, "cause names a hidden event (store seq 1) -- must be nulled"
    assert by_seq[2]["cause"] == "v1", "cause names a visible event -- remapped to its view-local id"
    text = json.dumps(events)
    assert ulid(1) not in text
    assert ulid(2) not in text


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


def test_SEC_07_archive_ref_and_message_ref_are_nulled_in_scoped_views(client, store):
    """Round-3 finding (security a): `trace.archive_ref` and a data field like
    channel.message_in's `message_ref` both point at a position in the run-wide raw archive (PRD
    13.2) -- a counter that would let a scoped viewer infer how many raw records exist between two
    events it can see, even though the events themselves are visible. Both are nulled for every
    scoped (non-owner) view; the owner still sees them unchanged (PRD 10.1)."""
    store.worlds[WORLD] = make_world(owner=OWNER, districts={D1: make_district("Mail", "Triaging the inbox")})
    message_in = base_event(
        seq=1,
        type_="channel.message_in",
        data={"channel": "email", "message_ref": "r_village_basic_1/17", "card_id": None, "destination": None},
        district=D1,
        vis=[D1],
        summary="An email came in",
    )
    message_in["trace"]["archive_ref"] = "r_village_basic_1/17"
    store.events[WORLD] = [message_in]

    as_principal(make_principal(user_id="u_viewer", role="viewer", districts=(D1,)))
    resp = client.get(f"/worlds/{WORLD}/events")
    assert resp.status_code == 200
    seen = resp.json()["events"]
    assert len(seen) == 1
    assert seen[0]["trace"]["archive_ref"] is None
    assert seen[0]["data"]["message_ref"] is None
    text = json.dumps(seen[0])
    assert "r_village_basic_1/17" not in text

    as_principal(make_principal(user_id=OWNER, role="owner"))
    owner_events = client.get(f"/worlds/{WORLD}/events").json()["events"]
    assert owner_events[0]["trace"]["archive_ref"] == "r_village_basic_1/17"
    assert owner_events[0]["data"]["message_ref"] == "r_village_basic_1/17"


def test_SEC_07_ulid_shaped_data_field_naming_an_event_is_mapped_or_nulled(client, store):
    """Round-3 finding (security a): a ULID-shaped value inside `data` that names another event
    (for example policy.applied's `instruction_id`, PRD 10.4 "L2 is instruction is approval") must
    be treated exactly like `cause` -- remapped to the named event's view-local id when that event
    is itself visible, nulled when it is hidden or does not exist -- never the real store id."""
    store.worlds[WORLD] = make_world(owner=OWNER, districts={D1: make_district("Mail", "Triaging the inbox")})

    instruction_visible = base_event(
        seq=1, type_="world.requested", data={}, vis="all", summary="the owner asked for a followup reply"
    )
    instruction_hidden = base_event(
        seq=2,
        type_="channel.message_in",
        data={"channel": "email", "message_ref": None, "card_id": None, "destination": None},
        district=D2,
        vis=[D2],
        summary="a finance instruction, not visible to this viewer",
    )

    def _applied(seq: int, instruction_id: str) -> dict:
        return base_event(
            seq=seq,
            type_="policy.applied",
            data={
                "policy_id": "pol_x",
                "gate_id": "g_1",
                "outbox_id": ulid(90 + seq),
                "action_type": "send_email",
                "connector": "gmail",
                "destination": "thread-1",
                "district": D1,
                "risk_tier": "T1",
                "level": "L2",
                "instruction_id": instruction_id,
                "undo_window_s": 60,
                "item": None,
            },
            district=D1,
            vis=[D1],
            authz={"by": "policy", "ref": "pol_x", "at": "2026-09-29T09:30:00.000Z"},
            summary=f"gate {seq} opened",
        )

    applied_from_visible = _applied(3, instruction_visible["id"])
    applied_from_hidden = _applied(4, instruction_hidden["id"])
    store.events[WORLD] = [instruction_visible, instruction_hidden, applied_from_visible, applied_from_hidden]

    as_principal(make_principal(user_id="u_viewer", role="viewer", districts=(D1,)))
    resp = client.get(f"/worlds/{WORLD}/events")
    assert resp.status_code == 200
    seen = resp.json()["events"]
    # instruction_hidden (store seq 2) is dropped entirely; the other three survive.
    assert len(seen) == 3
    by_summary = {e["summary"]: e for e in seen}

    visible_view_id = by_summary["the owner asked for a followup reply"]["id"]
    assert by_summary["gate 3 opened"]["data"]["instruction_id"] == visible_view_id
    assert by_summary["gate 3 opened"]["data"]["instruction_id"] != instruction_visible["id"]

    assert by_summary["gate 4 opened"]["data"]["instruction_id"] is None
    text = json.dumps(seen)
    assert instruction_visible["id"] not in text
    assert instruction_hidden["id"] not in text


def test_SEC_07_district_field_naming_a_hidden_district_drops_the_whole_event_even_when_vis_is_all(client, store):
    """Round-5 finding (security, biggest; supersedes round-3's "null the field, keep the event"):
    an event globally visible (vis: "all") may still name a hidden district in its own `district`
    field (for example a platform-wide notice about a district-scoped step). That must not merely
    blank the field for a scoped viewer -- the whole event is dropped, since a scoped viewer
    receiving *any* record of it (its `summary`, its `ts`, the fact it happened at all) is itself a
    count/name leak SEC-07 forbids, not just the district id specifically."""
    hidden_district = "D9"
    store.worlds[WORLD] = make_world(
        owner=OWNER,
        districts={
            D1: make_district("Mail", "Triaging the inbox"),
            hidden_district: make_district("Payroll", "Running payroll"),
        },
    )
    store.events[WORLD] = [
        base_event(
            seq=1, type_="agent.working", data={}, district=hidden_district, vis="all", summary="cross-world notice"
        ),
        base_event(seq=2, type_="world.started", data={"budget_cap": 40}, vis="all", summary="unrelated, kept"),
    ]
    as_principal(make_principal(user_id="u_viewer", role="viewer", districts=(D1,)))

    resp = client.get(f"/worlds/{WORLD}/events")
    events = resp.json()["events"]
    assert [e["summary"] for e in events] == ["unrelated, kept"], (
        "the event naming a hidden district must be dropped entirely, not kept with district nulled"
    )
    assert hidden_district not in json.dumps(events)
    assert "cross-world notice" not in json.dumps(events)

    as_principal(make_principal(user_id=OWNER, role="owner"))
    owner_events = client.get(f"/worlds/{WORLD}/events").json()["events"]
    owner_by_summary = {e["summary"]: e for e in owner_events}
    assert owner_by_summary["cross-world notice"]["district"] == hidden_district


def test_SEC_07_malformed_events_are_dropped_from_scoped_views_and_owner_views_never_500(client, store):
    """A malformed event -- missing `id`, or a `cause` that is a list instead of a string or null
    -- must never crash the redaction pass. Resolved default (this ticket may only write
    services/api/tests, so this is pinned here rather than docs/open-questions.md): a malformed
    event is dropped for every viewer, owner included -- the same "cannot be safely read, cannot
    be honestly shown to anyone" rule round 2's API_ST3a.md already applies to a malformed
    district record."""
    good = base_event(seq=1, type_="world.started", data={"budget_cap": 40}, vis="all", summary="the world started")
    missing_id = base_event(seq=2, type_="agent.working", data={}, vis="all", summary="malformed: no id")
    del missing_id["id"]
    bad_cause = base_event(seq=3, type_="agent.working", data={}, vis="all", summary="malformed: cause is a list")
    bad_cause["cause"] = ["not", "a", "string"]
    store.worlds[WORLD] = make_world(owner=OWNER, districts={D1: make_district("Mail", "Triaging the inbox")})
    store.events[WORLD] = [good, missing_id, bad_cause]

    as_principal(make_principal(user_id="u_viewer", role="viewer", districts=(D1,)))
    resp = client.get(f"/worlds/{WORLD}/events")
    assert resp.status_code == 200
    assert [e["summary"] for e in resp.json()["events"]] == [good["summary"]]

    as_principal(make_principal(user_id=OWNER, role="owner"))
    owner_resp = client.get(f"/worlds/{WORLD}/events")
    assert owner_resp.status_code == 200
    assert [e["summary"] for e in owner_resp.json()["events"]] == [good["summary"]]

    owner_world_resp = client.get(f"/worlds/{WORLD}")  # same store, proves GET /worlds/{id} is unaffected
    assert owner_world_resp.status_code == 200


def test_SEC_07_principal_districts_wrong_type_never_matches_by_substring(client, store):
    """Round-3 security finding: Principal.districts is typed tuple[str, ...]; a caller that (by
    bug elsewhere in the stack) ends up with a bare string instead must not have it iterated
    char-by-char or substring-matched against a district id -- "D1" as districts must not
    accidentally match district id "D12", and it must not silently let every single-character
    district id through either. Treated as no districts at all."""
    store.worlds[WORLD] = make_world(
        owner=OWNER,
        districts={D1: make_district("Mail", "Triaging the inbox"), D2: make_district("Finance Ops", "Ledger")},
    )
    store.events[WORLD] = [
        base_event(seq=1, type_="agent.working", data={}, district=D1, vis=[D1], summary="Mail agent working"),
    ]
    bad_principal = deps.Principal(
        user_id="u_viewer", role="viewer", world_id=WORLD, districts=D1
    )  # a str, not a tuple
    as_principal(bad_principal)

    resp = client.get(f"/worlds/{WORLD}/events")
    assert resp.status_code == 200
    assert resp.json()["events"] == [], "a str districts value must never accidentally match -- treat as none"

    world_resp = client.get(f"/worlds/{WORLD}")
    assert world_resp.status_code == 200
    assert world_resp.json()["districts"] == []
    assert world_resp.json()["has_hidden_districts"] is True


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


# ---------------------------------------------------------------------------
# Round-3 property test (security finding a, "allowlist, not copy"): a scoped response must never
# contain an original store event id or a real trace.archive_ref, however the districts and events
# are shuffled -- both are values a scoped viewer could use to count hidden events or hidden raw
# archive records. The owner (PRD 10.1, "All") still sees every real id and archive_ref unchanged.


@st.composite
def _id_opacity_case(draw):
    n = draw(st.integers(min_value=2, max_value=6))
    district_ids = [f"D{i}" for i in range(1, n + 1)]
    visible = draw(st.sets(st.sampled_from(district_ids), max_size=n))
    events_per_district = draw(st.lists(st.integers(min_value=0, max_value=2), min_size=n, max_size=n))
    role = draw(st.sampled_from(["viewer", "team_lead", "owner"]))
    return district_ids, visible, events_per_district, role


@settings(max_examples=30, deadline=None, suppress_health_check=[HealthCheck.function_scoped_fixture])
@given(case=_id_opacity_case())
def test_SEC_07_property_scoped_view_never_returns_a_real_store_id_or_archive_ref(client, store, case):
    district_ids, visible, events_per_district, role = case

    districts = {did: make_district(f"District{i}", f"Summary{i}") for i, did in enumerate(district_ids, start=1)}
    store.worlds[WORLD] = make_world(owner=OWNER, districts=districts)

    events = []
    seq = 1
    for i, did in enumerate(district_ids, start=1):
        for k in range(events_per_district[i - 1]):
            event = base_event(seq=seq, type_="agent.working", data={}, district=did, vis=[did], summary=f"m{i}_{k}")
            event["trace"]["archive_ref"] = f"r_village_basic_1/{seq}"
            events.append(event)
            seq += 1
    store.events[WORLD] = events

    real_ids = {e["id"] for e in events}
    real_archive_refs = {e["trace"]["archive_ref"] for e in events}

    if role == "owner":
        as_principal(make_principal(user_id=OWNER, role="owner"))
    else:
        as_principal(
            make_principal(
                user_id="u_scoped",
                role=role,
                districts=tuple(visible),
            )
        )

    resp = client.get(f"/worlds/{WORLD}/events")
    assert resp.status_code == 200
    seen = resp.json()["events"]

    if role == "owner":
        assert {e["id"] for e in seen} == real_ids, "the owner still sees every real store id, unchanged"
        assert {e["trace"]["archive_ref"] for e in seen} == real_archive_refs
    else:
        seen_ids = {e["id"] for e in seen}
        assert seen_ids.isdisjoint(real_ids), "a scoped view must never return a real store event id"
        assert all(e["trace"]["archive_ref"] is None for e in seen), "archive_ref must never reach a scoped viewer"


# ---------------------------------------------------------------------------
# Round-4 finding 4 (security): a redacted view still leaked the caller's own visibility scope
# through `vis` (the full, unfiltered stored list, not just the caller's own intersection),
# through `target`/`actor` (either can legally be a district id per event.schema.json's own
# `target` anyOf, and neither was checked), and through `data` (round 3 only walked its top
# level -- a ULID or district id nested inside a sub-object or list, or `data.district`
# specifically, passed through unredacted).


def test_SEC_07_vis_list_in_scoped_view_is_filtered_to_the_callers_own_districts(client, store):
    """A kept event's vis can name more districts than the caller can see -- the event is kept
    whenever vis intersects principal.districts at all, not only when vis is a subset of it. The
    full, unfiltered list must never reach a scoped viewer; only the intersection with what that
    viewer can actually see."""
    store.worlds[WORLD] = make_world(
        owner=OWNER,
        districts={D1: make_district("Mail", "Triaging the inbox"), D2: make_district("Finance Ops", "Ledger")},
    )
    store.events[WORLD] = [
        base_event(seq=1, type_="agent.working", data={}, district=D1, vis=[D1, D2], summary="shared update"),
    ]
    as_principal(make_principal(user_id="u_viewer", role="viewer", districts=(D1,)))

    resp = client.get(f"/worlds/{WORLD}/events")
    assert resp.status_code == 200
    events = resp.json()["events"]
    assert len(events) == 1
    assert events[0]["vis"] == [D1], "vis must be filtered to the caller's own districts, not the full stored list"
    assert D2 not in json.dumps(events[0])

    as_principal(make_principal(user_id=OWNER, role="owner"))
    owner_events = client.get(f"/worlds/{WORLD}/events").json()["events"]
    assert owner_events[0]["vis"] == [D1, D2], "the owner still sees the full, unfiltered vis list"


def test_SEC_07_target_naming_a_hidden_district_drops_the_whole_event_in_scoped_views(client, store):
    """target may legally be a district id (event.schema.json#/$defs/target's own anyOf includes
    district_id); one naming a hidden district must drop the whole event for a scoped viewer even
    though the event itself is kept via vis: "all" -- round 5 supersedes round 4's "null the field,
    keep the event" treatment, exactly like the dedicated district field."""
    hidden = "D9"
    store.worlds[WORLD] = make_world(
        owner=OWNER,
        districts={
            D1: make_district("Mail", "Triaging the inbox"),
            hidden: make_district("Payroll", "Running payroll"),
        },
    )
    store.events[WORLD] = [
        base_event(
            seq=1, type_="agent.working", data={}, target=hidden, vis="all", summary="target names a hidden district"
        ),
        base_event(seq=2, type_="world.started", data={"budget_cap": 40}, vis="all", summary="unrelated, kept"),
    ]
    as_principal(make_principal(user_id="u_viewer", role="viewer", districts=(D1,)))

    resp = client.get(f"/worlds/{WORLD}/events")
    events = resp.json()["events"]
    assert [e["summary"] for e in events] == ["unrelated, kept"]
    assert hidden not in json.dumps(events)

    as_principal(make_principal(user_id=OWNER, role="owner"))
    owner_events = client.get(f"/worlds/{WORLD}/events").json()["events"]
    owner_by_summary = {e["summary"]: e for e in owner_events}
    assert owner_by_summary["target names a hidden district"]["target"] == hidden


def test_SEC_07_actor_naming_a_hidden_district_drops_the_whole_event_in_scoped_views(client, store):
    """Same fail-safe treatment as target above, applied to actor -- defensive: event.schema.json's
    own actor anyOf does not currently include district_id, but API_ST3a.md pins the redaction
    rule generically (by shape, not by field-specific semantics) so a scoped viewer is never one
    schema change away from a leak here. This event is deliberately not schema-valid (actor would
    never really be district-shaped in production data) so it is built directly, not validated.
    Round 5 supersedes round 4's "null the field, keep the event" treatment -- the whole event is
    dropped."""
    hidden = "D9"
    store.worlds[WORLD] = make_world(
        owner=OWNER,
        districts={
            D1: make_district("Mail", "Triaging the inbox"),
            hidden: make_district("Payroll", "Running payroll"),
        },
    )
    store.events[WORLD] = [
        base_event(
            seq=1, type_="agent.working", data={}, actor=hidden, vis="all", summary="actor names a hidden district"
        ),
        base_event(seq=2, type_="world.started", data={"budget_cap": 40}, vis="all", summary="unrelated, kept"),
    ]
    as_principal(make_principal(user_id="u_viewer", role="viewer", districts=(D1,)))

    resp = client.get(f"/worlds/{WORLD}/events")
    events = resp.json()["events"]
    assert [e["summary"] for e in events] == ["unrelated, kept"]
    assert hidden not in json.dumps(events)

    as_principal(make_principal(user_id=OWNER, role="owner"))
    owner_events = client.get(f"/worlds/{WORLD}/events").json()["events"]
    owner_by_summary = {e["summary"]: e for e in owner_events}
    assert owner_by_summary["actor names a hidden district"]["actor"] == hidden


def test_SEC_07_data_district_field_drops_the_whole_event_like_the_top_level_district_field(client, store):
    """`data.district` is not ULID-shaped, so round 3's ULID-only data pass never touched it -- it
    must get exactly the same treatment as the event's own top-level district field: round 5
    supersedes round 4's "null data.district, keep the event" with "drop the whole event" for the
    hidden case; a visible data.district is unaffected."""
    hidden = "D9"
    store.worlds[WORLD] = make_world(
        owner=OWNER,
        districts={
            D1: make_district("Mail", "Triaging the inbox"),
            hidden: make_district("Payroll", "Running payroll"),
        },
    )
    store.events[WORLD] = [
        base_event(
            seq=1,
            type_="agent.working",
            data={"district": hidden, "note": "unrelated payload field"},
            vis="all",
            summary="data.district names a hidden district",
        ),
        base_event(
            seq=2,
            type_="agent.working",
            data={"district": D1},
            vis="all",
            summary="data.district names a visible district",
        ),
    ]
    as_principal(make_principal(user_id="u_viewer", role="viewer", districts=(D1,)))

    resp = client.get(f"/worlds/{WORLD}/events")
    events = resp.json()["events"]
    by_summary = {e["summary"]: e for e in events}
    assert "data.district names a hidden district" not in by_summary, (
        "the event must be dropped entirely, not kept with data.district nulled"
    )
    assert by_summary["data.district names a visible district"]["data"]["district"] == D1
    assert hidden not in json.dumps(events)
    assert "unrelated payload field" not in json.dumps(events)

    as_principal(make_principal(user_id=OWNER, role="owner"))
    owner_events = client.get(f"/worlds/{WORLD}/events").json()["events"]
    by_summary_owner = {e["summary"]: e for e in owner_events}
    assert by_summary_owner["data.district names a hidden district"]["data"]["district"] == hidden


def test_SEC_07_nested_ulid_values_in_data_are_remapped_or_nulled_at_any_depth(client, store):
    """A ULID naming another event can be nested inside a list item or a sub-object within `data`,
    not only at its top level -- round 3's pass only walked data's own top-level values. Every such
    value, at any depth, gets the same treatment it would get at the top level: remapped to that
    event's view-local id when it survived filtering, else nulled. A ULID naming a hidden event is
    not itself a district reference, so (unlike a nested hidden district id, see the drop-the-whole-
    -event test below) it never causes the *containing* event to be dropped -- only nulled/remapped
    in place, per round 3/4's unchanged rule."""
    store.worlds[WORLD] = make_world(owner=OWNER, districts={D1: make_district("Mail", "Triaging the inbox")})
    visible_ref = base_event(seq=1, type_="world.requested", data={}, vis="all", summary="a visible reference event")
    hidden_ref = base_event(
        seq=2, type_="agent.working", data={}, district="D9", vis=["D9"], summary="a hidden reference event"
    )
    store.worlds[WORLD].districts["D9"] = make_district("Payroll", "Running payroll")
    nested = base_event(
        seq=3,
        type_="agent.working",
        data={
            "refs": [visible_ref["id"], {"inner_ref": hidden_ref["id"], "note": "kept"}],
            "district": D1,
            "outer": {"deep": {"deeper": [visible_ref["id"], "not-a-ulid-or-district"]}},
        },
        vis="all",
        summary="deeply nested ulid refs, no hidden district anywhere",
    )
    store.events[WORLD] = [visible_ref, hidden_ref, nested]

    as_principal(make_principal(user_id="u_viewer", role="viewer", districts=(D1,)))
    resp = client.get(f"/worlds/{WORLD}/events")
    events = resp.json()["events"]
    assert len(events) == 2, "the hidden reference event (store seq 2) is dropped by the vis filter"
    by_summary = {e["summary"]: e for e in events}
    visible_view_id = by_summary["a visible reference event"]["id"]
    nested_view = by_summary["deeply nested ulid refs, no hidden district anywhere"]

    assert nested_view["data"]["refs"][0] == visible_view_id
    assert nested_view["data"]["refs"][1]["inner_ref"] is None, "named a hidden/dropped event -- nulled, not dropped"
    assert nested_view["data"]["refs"][1]["note"] == "kept"
    assert nested_view["data"]["district"] == D1, "a visible district stays unchanged"
    assert nested_view["data"]["outer"]["deep"]["deeper"][0] == visible_view_id
    assert nested_view["data"]["outer"]["deep"]["deeper"][1] == "not-a-ulid-or-district"

    text = json.dumps(events)
    assert hidden_ref["id"] not in text
    assert visible_ref["id"] not in text, "the real store id must never appear, remapped only"


def test_SEC_07_a_hidden_district_id_nested_anywhere_in_data_drops_the_whole_event(client, store):
    """Round-5 finding (security, biggest): unlike a nested ULID naming a hidden *event* (nulled
    in place, previous test), a district id nested anywhere in `data` -- in a list item, inside a
    sub-object, at any depth -- names a hidden *district*, and per the round-5 hidden-district
    filter that drops the whole event, exactly like a top-level `district`/`target`/`actor` would.
    This is true even three levels deep, and even when everything else about the event (its own
    `vis`, its other data fields) would otherwise have kept it."""
    hidden = "D9"
    store.worlds[WORLD] = make_world(
        owner=OWNER,
        districts={D1: make_district("Mail", "Triaging the inbox"), hidden: make_district("Payroll", "Payroll")},
    )
    shallow_hidden = base_event(
        seq=1,
        type_="agent.working",
        data={"refs": [{"inner_district": hidden}]},
        vis="all",
        summary="hidden district one level inside a list item",
    )
    deep_hidden = base_event(
        seq=2,
        type_="agent.working",
        data={"outer": {"deep": {"deeper": [D1, hidden]}}},
        vis="all",
        summary="hidden district three levels deep",
    )
    clean = base_event(
        seq=3, type_="agent.working", data={"outer": {"deep": {"deeper": [D1, D1]}}}, vis="all", summary="all clean"
    )
    store.events[WORLD] = [shallow_hidden, deep_hidden, clean]

    as_principal(make_principal(user_id="u_viewer", role="viewer", districts=(D1,)))
    resp = client.get(f"/worlds/{WORLD}/events")
    events = resp.json()["events"]
    assert [e["summary"] for e in events] == ["all clean"], (
        "both events naming the hidden district anywhere in data, at any depth, must be dropped "
        "entirely -- only the clean event survives"
    )
    assert hidden not in json.dumps(events)

    as_principal(make_principal(user_id=OWNER, role="owner"))
    owner_events = client.get(f"/worlds/{WORLD}/events").json()["events"]
    assert {e["summary"] for e in owner_events} == {
        "hidden district one level inside a list item",
        "hidden district three levels deep",
        "all clean",
    }


@settings(max_examples=30, deadline=None, suppress_health_check=[HealthCheck.function_scoped_fixture])
@given(data=st.data())
def test_SEC_07_property_nested_data_never_leaks_hidden_districts_or_real_ids(client, store, data):
    """Property: whatever shape (dict/list nesting, up to depth 3) a data payload takes, a hidden
    district id and a real store event id (visible or hidden) never appear anywhere in a scoped
    viewer's response, however deeply either is buried."""
    hidden_district = "D9"
    visible_district = "D1"
    store.worlds[WORLD] = make_world(
        owner=OWNER,
        districts={
            visible_district: make_district("Mail", "Triaging the inbox"),
            hidden_district: make_district("Payroll", "Running payroll"),
        },
    )
    visible_ref = base_event(seq=1, type_="world.requested", data={}, vis="all", summary="a visible reference event")
    hidden_ref = base_event(
        seq=2,
        type_="agent.working",
        data={},
        district=hidden_district,
        vis=[hidden_district],
        summary="a hidden reference event",
    )
    leaves = [hidden_district, visible_district, hidden_ref["id"], visible_ref["id"], "plain_marker_value"]

    def build(depth: int):
        if depth <= 0:
            return data.draw(st.sampled_from(leaves))
        choice = data.draw(st.integers(min_value=0, max_value=2))
        if choice == 0:
            return data.draw(st.sampled_from(leaves))
        if choice == 1:
            width = data.draw(st.integers(min_value=0, max_value=3))
            return [build(depth - 1) for _ in range(width)]
        keys = data.draw(st.lists(st.sampled_from(["a", "b", "district", "ref"]), min_size=0, max_size=3, unique=True))
        return {k: build(depth - 1) for k in keys}

    # event.schema.json pins `data` as always an object (`{"type": "object"}`) -- the top level is
    # forced to a dict, with build()'s own random leaf/list/dict choice only applying two levels
    # further down, so this never constructs a contractually-impossible bare-string `data`.
    top_keys = data.draw(st.lists(st.sampled_from(["a", "b", "district", "ref"]), min_size=1, max_size=4, unique=True))
    nested_shape = {k: build(2) for k in top_keys}
    nested_event = base_event(seq=3, type_="agent.working", data=nested_shape, vis="all", summary="deeply nested data")
    store.events[WORLD] = [visible_ref, hidden_ref, nested_event]

    as_principal(make_principal(user_id="u_viewer", role="viewer", districts=(visible_district,)))
    resp = client.get(f"/worlds/{WORLD}/events")
    assert resp.status_code == 200
    events = resp.json()["events"]
    text = json.dumps(events)

    assert hidden_district not in text, "a hidden district id must never leak, however deeply nested"
    assert hidden_ref["id"] not in text, "a hidden event's real id must never leak, however deeply nested"
    assert visible_ref["id"] not in text, "a real store id must never leak either, even for a visible event"


# ---------------------------------------------------------------------------
# Round-5 finding 6 (security): a `data` dict *key* that is itself a district id or an event ULID
# was never checked at all -- only values were walked. A district-id key gets the same
# whole-event-drop treatment a district-id value gets (finding 1); a ULID-shaped key naming an
# event is remapped to that event's view-local id (visible) or dropped outright, key and value both
# (hidden/unknown) -- a JSON key cannot itself be null the way a value can (ambiguity 17).


def test_SEC_07_data_dict_keys_that_are_district_ids_or_ulids_are_treated_like_values(client, store):
    hidden = "D9"
    store.worlds[WORLD] = make_world(
        owner=OWNER,
        districts={D1: make_district("Mail", "Triaging the inbox"), hidden: make_district("Payroll", "Payroll")},
    )
    visible_ref = base_event(seq=1, type_="world.requested", data={}, vis="all", summary="a visible reference event")
    hidden_ref = base_event(
        seq=2, type_="agent.working", data={}, district=hidden, vis=[hidden], summary="a hidden reference event"
    )
    visible_district_key_event = base_event(
        seq=3, type_="agent.working", data={D1: "mail payload"}, vis="all", summary="visible district id as data key"
    )
    hidden_district_key_event = base_event(
        seq=4,
        type_="agent.working",
        data={hidden: "payroll payload"},
        vis="all",
        summary="hidden district id as data key",
    )
    visible_ulid_key_event = base_event(
        seq=5,
        type_="agent.working",
        data={visible_ref["id"]: "some value"},
        vis="all",
        summary="visible event id as data key",
    )
    hidden_ulid_key_event = base_event(
        seq=6,
        type_="agent.working",
        data={hidden_ref["id"]: "some value", "note": "kept"},
        vis="all",
        summary="hidden event id as data key",
    )
    store.events[WORLD] = [
        visible_ref,
        hidden_ref,
        visible_district_key_event,
        hidden_district_key_event,
        visible_ulid_key_event,
        hidden_ulid_key_event,
    ]

    as_principal(make_principal(user_id="u_viewer", role="viewer", districts=(D1,)))
    resp = client.get(f"/worlds/{WORLD}/events")
    assert resp.status_code == 200
    events = resp.json()["events"]
    by_summary = {e["summary"]: e for e in events}

    assert "a hidden reference event" not in by_summary
    assert "hidden district id as data key" not in by_summary, "a hidden district-id key must drop the whole event"

    visible_key_event = by_summary["visible district id as data key"]
    assert visible_key_event["data"] == {D1: "mail payload"}, "a visible district-id key is left unchanged"

    visible_ref_view_id = by_summary["a visible reference event"]["id"]
    ulid_key_event = by_summary["visible event id as data key"]
    assert list(ulid_key_event["data"].keys()) == [visible_ref_view_id], "a visible-event ULID key is renamed"
    assert ulid_key_event["data"][visible_ref_view_id] == "some value"

    hidden_key_event = by_summary["hidden event id as data key"]
    assert hidden_key_event["data"] == {"note": "kept"}, (
        "the key naming a hidden/unknown event is dropped (key and value); the sibling key is kept"
    )

    text = json.dumps(events)
    assert hidden not in text
    assert hidden_ref["id"] not in text
    assert visible_ref["id"] not in text

    as_principal(make_principal(user_id=OWNER, role="owner"))
    owner_events = client.get(f"/worlds/{WORLD}/events").json()["events"]
    owner_by_summary = {e["summary"]: e for e in owner_events}
    assert owner_by_summary["hidden district id as data key"]["data"] == {hidden: "payroll payload"}
    assert owner_by_summary["hidden event id as data key"]["data"] == {hidden_ref["id"]: "some value", "note": "kept"}


# ---------------------------------------------------------------------------
# Round-5 finding 5 (qa/security): data nested far past any realistic depth must never turn into a
# 500 -- for a non-owner the redaction walk fails closed and the event is dropped; the owner's own
# view never walks data at all, so it is unaffected and still returns the event unmodified
# (ambiguity 15).


def _deeply_nested(depth: int, leaf: Any = "bottom") -> Any:
    value: Any = leaf
    for _ in range(depth):
        value = {"n": value}
    return value


def test_FR_HIL_09_SEC_07_data_nested_500_deep_never_500s(client, store):
    store.worlds[WORLD] = make_world(owner=OWNER, districts={D1: make_district("Mail", "Triaging the inbox")})
    deep_data = _deeply_nested(500)
    deep_event = base_event(
        seq=1, type_="agent.working", data=deep_data, vis="all", summary="a very deeply nested payload"
    )
    normal_event = base_event(seq=2, type_="world.started", data={"budget_cap": 40}, vis="all", summary="normal")
    store.events[WORLD] = [deep_event, normal_event]

    as_principal(make_principal(user_id="u_viewer", role="viewer", districts=(D1,)))
    resp = client.get(f"/worlds/{WORLD}/events")
    assert resp.status_code == 200, "deeply nested data must never 500, even redacted for a scoped viewer"
    seen = [e["summary"] for e in resp.json()["events"]]
    assert seen == ["normal"], "the deeply nested event fails closed and is dropped for a non-owner"

    as_principal(make_principal(user_id=OWNER, role="owner"))
    owner_resp = client.get(f"/worlds/{WORLD}/events")
    assert owner_resp.status_code == 200, "deeply nested data must never 500 for the owner either"
    owner_seen = {e["summary"]: e for e in owner_resp.json()["events"]}
    assert set(owner_seen) == {"a very deeply nested payload", "normal"}
    assert owner_seen["a very deeply nested payload"]["data"] == deep_data, (
        "resolved default (ambiguity 15): the owner's view returns data unmodified regardless of "
        "depth, since it never walks data at all -- only the scoped-redaction walk needs a depth guard"
    )

    owner_world_resp = client.get(f"/worlds/{WORLD}")  # same store, proves GET /worlds/{id} is unaffected by depth
    assert owner_world_resp.status_code == 200


# ---------------------------------------------------------------------------
# Round-5 finding 1's second half: real contract fixtures (contracts/fixtures/events/valid/), not
# just hand-built events, must also be dropped entirely for a scoped viewer when they name a hidden
# district -- district.created and agent.spawned are both vis: "all" and both name a district in
# their own top-level `district` field (district.created's `target` is district-shaped too).


def test_FR_HIL_09_SEC_07_contract_fixture_events_naming_a_hidden_district_are_dropped_entirely(client, store):
    hidden = "D9"
    store.worlds[WORLD] = make_world(
        owner=OWNER,
        districts={D1: make_district("Mail", "Triaging the inbox"), hidden: make_district("Payroll", "Payroll")},
    )

    district_created = load_json(contracts_dir() / "fixtures" / "events" / "valid" / "district.created.json")
    district_created["world_id"] = WORLD
    district_created["seq"] = 1
    district_created["district"] = hidden
    district_created["target"] = hidden  # district.created's target names the district it created
    district_created["cause"] = None

    agent_spawned = load_json(contracts_dir() / "fixtures" / "events" / "valid" / "agent.spawned.json")
    agent_spawned["world_id"] = WORLD
    agent_spawned["seq"] = 2
    agent_spawned["district"] = hidden
    agent_spawned["cause"] = None

    normal = base_event(seq=3, type_="world.started", data={"budget_cap": 40}, vis="all", summary="the world started")
    store.events[WORLD] = [district_created, agent_spawned, normal]

    as_principal(make_principal(user_id="u_viewer", role="viewer", districts=(D1,)))
    resp = client.get(f"/worlds/{WORLD}/events")
    assert resp.status_code == 200
    events = resp.json()["events"]

    assert [e["summary"] for e in events] == ["the world started"], (
        "a D1-scoped viewer must get neither fixture event -- only the unrelated, hidden-district-free one"
    )
    text = json.dumps(events)
    assert hidden not in text
    assert "Mail is set up" not in text  # district.created's own summary must not leak either
    assert "joined the team for Mail" not in text  # agent.spawned's own summary must not leak

    as_principal(make_principal(user_id=OWNER, role="owner"))
    owner_events = client.get(f"/worlds/{WORLD}/events").json()["events"]
    assert {e["type"] for e in owner_events} == {"district.created", "agent.spawned", "world.started"}


# ---------------------------------------------------------------------------
# Round-6 (ST-3a-2, issue #38 item 5, security): a scoped view's `trace` must be rebuilt by
# allowlisting event.schema.json#/$defs/trace's own seven keys, not copied forward wholesale --
# today's `_scoped_event_view` does `dict(trace_value)` (every key the stored event happens to
# carry) and only overwrites `archive_ref` afterward, so an extra, schema-invalid key still reaches
# a scoped viewer verbatim.


def test_SEC_07_scoped_view_allowlists_trace_keys_and_drops_unknown_ones(client, store):
    store.worlds[WORLD] = make_world(owner=OWNER, districts={D1: make_district("Mail", "Triaging the inbox")})
    event = base_event(seq=1, type_="agent.working", data={}, district=D1, vis=[D1], summary="Mail agent is working")
    # trace.additionalProperties is false in the contract -- the stored value should never carry
    # this key, but a scoped view must not merely trust that; "D2" stands in for a hidden district
    # id or any other out-of-schema key that must never reach a viewer through an unfiltered copy.
    event["trace"]["D2"] = "a district id or any other value that must never leak through trace"
    store.events[WORLD] = [event]

    as_principal(make_principal(user_id="u_viewer", role="viewer", districts=(D1,)))
    resp = client.get(f"/worlds/{WORLD}/events")
    assert resp.status_code == 200, resp.text
    events = resp.json()["events"]
    assert len(events) == 1
    assert "D2" not in events[0]["trace"], "an extra, schema-invalid trace key must never reach a scoped viewer"
    assert set(events[0]["trace"]) == {
        "model_role",
        "profile",
        "tokens_in",
        "tokens_out",
        "tool",
        "latency_ms",
        "archive_ref",
    }, "a scoped view's trace must be rebuilt by allowlisting exactly the schema's own seven keys"

    as_principal(make_principal(user_id=OWNER, role="owner"))
    owner_events = client.get(f"/worlds/{WORLD}/events").json()["events"]
    assert owner_events[0]["trace"]["D2"] == "a district id or any other value that must never leak through trace"
