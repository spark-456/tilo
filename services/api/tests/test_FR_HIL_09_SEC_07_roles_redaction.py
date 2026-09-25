"""FR-HIL-09 (PRD 10.1, 10.6): "Roles and redaction as in 10.1: a Viewer's API responses never
contain hidden-district names." SEC-07 (PRD 16.4): "Redacted event views per role: scoped users
never receive hidden names or counts." Routes and shapes pinned in
services/api/tests/API_ST3a.md (round 3, after code/security/qa review round 2 failed on: a
scoped view being built by copying the event forward rather than allowlisting -- so it still
leaked the real event `id` (a viewer could correlate it against another view or use its
ULID ordering to guess how much happened between two visible events), a `trace.archive_ref` or
`data.message_ref` (both name a position in the run-wide raw archive), any other ULID-shaped
value in `data` naming an event (for example policy.applied's instruction_id), and a `district`
field naming a hidden district even on an otherwise vis: "all" event; plus a malformed event
(missing `id`, a non-string `cause`) was never proven not to 500, and Principal.districts being
some non-tuple value (a bare string) was never proven not to be matched by substring). Round 1's
fixes (the 403/404 membership oracle, the view's own dense `seq`, a dangling `cause` nulled, and a
malformed district record failing closed) are unchanged here and still pinned below.
"""

from __future__ import annotations

import json
from types import SimpleNamespace

from _api_lib import OWNER, WORLD, as_principal, base_event, make_district, make_principal, make_world, ulid
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
        data={"channel": "whatsapp", "message_ref": "r_village_basic_1/17", "card_id": None, "destination": None},
        district=D1,
        vis=[D1],
        summary="A WhatsApp message came in",
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
        data={"channel": "whatsapp", "message_ref": None, "card_id": None, "destination": None},
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


def test_SEC_07_district_field_naming_a_hidden_district_is_nulled_even_when_vis_is_all(client, store):
    """Round-3 finding (security a): an event globally visible (vis: "all") may still name a
    hidden district in its own `district` field (for example a platform-wide notice about a
    district-scoped step). That field must not leak the hidden district's id to a scoped viewer
    even though the event itself is kept -- any district id outside the caller's scope is removed
    or re-keyed, per event field, not just per event."""
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
    ]
    as_principal(make_principal(user_id="u_viewer", role="viewer", districts=(D1,)))

    resp = client.get(f"/worlds/{WORLD}/events")
    events = resp.json()["events"]
    assert len(events) == 1
    assert events[0]["district"] is None
    assert hidden_district not in json.dumps(events[0])

    as_principal(make_principal(user_id=OWNER, role="owner"))
    owner_events = client.get(f"/worlds/{WORLD}/events").json()["events"]
    assert owner_events[0]["district"] == hidden_district


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
                domain="finance" if role == "team_lead" else None,
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
