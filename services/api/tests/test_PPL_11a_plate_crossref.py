"""PPL-11a slice B: the plate read model through the real API (ADR-0021; contracts/people.rules.md PE-26 to PE-30;
BQ-269 to BQ-272, BQ-CCP3-1, BQ-CCP3-3). Every `fixtures/plate/crossref/` case, valid and invalid, is seeded as
stored state (work items, pins, mentions and meetings in the people stores; cards as facts from the plate sources)
and the case's actor asks `GET /v1/plate`. The source must land in the lane the reference oracle (`expected_join`
in `tests/contracts/test_CC_PEOPLE_3_quotes_and_plate.py`) gives it, or nowhere, and the whole document must be a
valid `Plate` that code grouped, ordered and fingerprinted (`_plate_problems`). `GET /v1/plate` takes no argument
that names a person (PE-26); the plate is never stored.
"""

from __future__ import annotations

import copy

import pytest
from _ppl11a_lib import (
    EARLY,
    OWNER,
    PRIYA,
    SAM,
    case_params,
    conforms,
    find_row,
    fixture_case,
    oracle,
    refs,
    today_in,
)


def _plate_of(make_rig, case):
    rig = make_rig()
    rig.seed_plate_case(case)
    response = rig.plate(params={"user": case["request"]["user"]})  # an ignored argument: PE-26
    return rig, response


def _source_ref(case) -> dict:
    return {"kind": case["source"]["kind"], "id": case["source"]["data"]["id"]}


@pytest.mark.parametrize(("kind", "name", "case"), case_params("plate"))
def test_PPL_11a_PE_27_every_plate_crossref_case_lands_where_the_oracle_puts_it(people_rig, kind, name, case):
    """Given the case's stored state, when its actor asks for their plate, then the source is in `rows` or `parked`
    exactly as `expected_join(case)` says (or nowhere), the plate validates against plate.schema.json, and its
    groups, order and fingerprint are the ones code gives (PE-28, PE-30)."""
    rig, response = _plate_of(people_rig, case)
    assert response.status_code == 200, f"{kind}/{name}: {response.status_code} {response.text[:200]}"
    plate = response.json()
    assert conforms("plate.schema.json", plate), f"{kind}/{name}: the answer must be a valid Plate"
    assert oracle._plate_problems(plate) == [], f"{kind}/{name}: {oracle._plate_problems(plate)}"
    actor = case["request"]["actor"]
    assert plate["user"] == actor, "the plate is the signed-in person's (PE-26)"
    assert plate["as_of"] == case["now"]
    assert plate["today"] == today_in(case["persons"][actor]["time_zone"], case["now"])
    lane = oracle.expected_join(case)
    found = find_row(plate, _source_ref(case)["kind"], _source_ref(case)["id"])
    if lane is None:
        assert found is None, f"{kind}/{name}: the rules keep this off the plate, it is in {found and found[0]}"
        assert plate["rows"] == [] and plate["parked"] == [], "nothing else is stored for this person"
    else:
        assert found is not None and found[0] == lane, f"{kind}/{name}: expected {lane}, got {found and found[0]}"
        assert refs(plate, lane) == [(_source_ref(case)["kind"], _source_ref(case)["id"])]
        assert plate["parked" if lane == "rows" else "rows"] == []
        _assert_row(case, found[1], lane)
        if case["source"].get("meeting"):
            assert case["source"]["meeting"]["title"] not in response.text, "no meeting title on a plate (PE-05, PE-29)"
    if kind == "invalid":
        assert (lane or "nowhere") != case["join"], f"{name}: the API must not do what the rule forbids"


def _clean(text: str) -> str:
    return oracle._clean(text)


def _assert_row(case: dict, row: dict, lane: str) -> None:
    """PE-29: what a row carries for the source kinds the crossref covers."""
    src, actor = case["source"], case["request"]["actor"]
    data = src["data"]
    assert row["flagged"] == data.get("flagged", False)
    if src["kind"] == "work_item":
        assigner = (data["assigned_by"] or {}).get("by")
        assert row["reason"] == "work_item" and row["title"] == _clean(data["title"]) and row["due"] == data["due"]
        assert row["at"] == data["created_at"], "the item's creation"
        assert row["from"] == (assigner if assigner and assigner != actor else None)
        assert row["evidence"] is (data["source"]["kind"] == "meeting" and bool(data["source"]["evidence"]))
        assert ("not_mine" in row["actions"]) is bool(assigner and assigner != actor), "PE-29: only on an assigned item"
        assert "draft_reply" not in row["actions"] and ("put_back" in row["actions"]) is (lane == "parked")
        if lane == "parked":
            history_last = data["history"][-1]["change"]
            expected = (
                "done" if data["status"] == "done" else ("asked" if history_last == "reassign_requested" else "snoozed")
            )
            assert row["group"] == expected
    elif src["kind"] == "pinboard_item":
        mine = data["scope"]["kind"] == "personal" or data["owner"] == actor
        assert row["reason"] == ("pin_owner" if mine else "pin_tagged") and row["title"] == _clean(data["title"])
        assert row["due"] == data["due"] and row["at"] == data["updated_at"]
        assert row["from"] == (data["set_up_by"] if data["set_up_by"] != actor else None)
        assert row["evidence"] is False and row["actions"] == ["open"]
    else:  # a card
        assert (
            row["reason"] == data["kind"] == "gate" and row["group"] == "attention" and row["at"] == data["created_at"]
        )
        assert row["title"] in (None, _clean(data["what_happened"])), "a card's title is its own text or null"
        assert row["due"] is None and row["from"] is None and row["evidence"] is False and row["actions"] == ["open"]


# --- PE-26: only ever the signed-in person's own plate --------------------------------------------------------------


def test_PPL_11a_PE_26_nothing_names_another_person_so_there_is_no_manager_view(people_rig):
    """No route, query, header or body picks a plate: whatever `user`, `as`, `owner` or `person` argument or header
    an actor adds, the plate is theirs, with their own rows only; and no route serves another person's."""
    rig = people_rig()
    rig.add_people()
    rig.add("work_items", _own(PRIYA, "wi_priya", "Priya's item"))
    rig.add("work_items", _own(SAM, "wi_sam", "Sam's item"))
    rig.add("work_items", _own(OWNER, "wi_owner", "Owner's item"))
    rig.as_user(OWNER)
    plain = rig.plate().json()
    assert refs(plain) == [("work_item", "wi_owner")] and plain["user"] == OWNER
    for who in (PRIYA, SAM, "u_ghost", "all", "*"):
        for params in ({"user": who}, {"as": who}, {"owner": who}, {"person": who}, {"user_id": who}, {"for": who}):
            again = rig.get("/v1/plate", params=params)
            assert again.status_code == 200 and again.json() == plain, (params, again.text[:150])
        again = rig.get("/v1/plate", headers={"X-User": who, "X-On-Behalf-Of": who, "X-Tilo-User": who})
        assert again.status_code == 200 and again.json() == plain
    for path in (f"/v1/plate/{PRIYA}", f"/v1/people/{PRIYA}/plate", f"/v1/users/{PRIYA}/plate", "/v1/plates"):
        assert rig.get(path).status_code in (404, 405), path
    assert rig.client.post("/v1/plate", json={"user": PRIYA}).status_code in (404, 405)
    assert rig.client.request("GET", "/v1/plate", json={"user": PRIYA}).json() == plain, "a body names nobody either"
    # an org owner and a team mate see only their own
    rig.as_user(PRIYA)
    assert refs(rig.plate().json()) == [("work_item", "wi_priya")]
    rig.as_user(SAM)
    assert refs(rig.plate().json()) == [("work_item", "wi_sam")]


def test_PPL_11a_PE_26_a_person_with_no_record_in_the_org_gets_a_404_and_the_sources_are_not_asked(people_rig):
    rig = people_rig()
    rig.add_people()
    rig.as_user("u_ghost")
    rig.require_route(("GET", "/v1/plate"))
    response = rig.get("/v1/plate")
    assert response.status_code == 404 and "rows" not in response.json()
    assert rig.sources.calls == [], "the sources are not asked for a person Tilo does not know"
    rig.sign_out()
    assert rig.get("/v1/plate").status_code == 401


def test_PPL_11a_PE_26_the_plate_is_never_stored_and_never_needs_the_artifact_store_or_the_redactor(people_rig):
    rig = people_rig()
    rig.add_people()
    rig.add("work_items", _own(PRIYA, "wi_priya", "Priya's item"))
    rig.as_user(PRIYA)
    rig.unwire("artifact_store", "redactor")
    before = rig.snapshot()
    first = rig.plate()
    assert first.status_code == 200 and rig.snapshot() == before, "a plate read changes no record"
    assert "artifact_store" not in rig.resolved and "redactor" not in rig.resolved
    rig.set_now("2026-10-06T10:00:00.001Z")
    second = rig.plate().json()
    assert second["as_of"] == "2026-10-06T10:00:00.001Z" and second["rows"] == first.json()["rows"]
    assert set(rig.sources.calls) == {("cards", PRIYA), ("runs", PRIYA), ("mail", PRIYA)}, (
        "the sources are asked about the caller only"
    )


def _own(user: str, item_id: str, title: str, **ov):
    from _ppl11a_lib import own_item  # noqa: PLC0415

    return own_item(item_id, user, title=title, **ov)


# --- records of a meeting: through the record or its tombstone, never without one -----------------------------------


def test_PPL_11a_PE_19_a_released_item_stays_on_the_plate_through_its_meetings_tombstone_but_not_without_one(
    people_rig,
):
    """A confirmed item from a meeting is readable while the meeting record or its PE-19 tombstone exists; with the
    meeting missing the item fails closed and stays off the plate."""
    from tilo_people.stores import meeting_tombstone  # noqa: PLC0415

    case = fixture_case("plate", "valid", "own_confirmed_meeting_item_joins_rows")
    live = people_rig()
    live.seed_plate_case(case)
    assert refs(live.plate().json()) == [("work_item", "wi_rate_sheet")]

    tomb = people_rig()
    tomb.seed_plate_case({**case, "source": {**case["source"], "meeting": None}})
    tomb.add("meetings", meeting_tombstone(case["source"]["meeting"]))
    assert refs(tomb.plate().json()) == [("work_item", "wi_rate_sheet")], (
        "a tombstone keeps the owner, so the item reads"
    )

    gone = people_rig()
    gone.seed_plate_case({**case, "source": {**case["source"], "meeting": None}})
    plate = gone.plate().json()
    assert plate["rows"] == [] and plate["parked"] == [], "no meeting record, no tombstone: fail closed"


def test_PPL_11a_PE_27_boundaries_snooze_done_window_and_the_two_day_rule(people_rig):
    """`snoozed_until == now` is not snoozed (strictly after counts); done 24 hours ago is parked, one millisecond
    longer is not; due `today + 2` is `soon` and `today + 3` is `rest`; `due < today` is overdue."""
    now = "2026-10-06T10:00:00.000Z"
    rig = people_rig()
    rig.add_people()
    items = [
        _own(PRIYA, "wi_snz_eq", "snooze ends now", snoozed_until=now),
        _own(PRIYA, "wi_snz_later", "snoozed", snoozed_until="2026-10-06T10:00:00.001Z"),
        _own(
            PRIYA,
            "wi_done_24h",
            "done a day ago",
            status="done",
            updated_at="2026-10-05T10:00:00.000Z",
            history=_done_history(PRIYA),
        ),
        _own(
            PRIYA,
            "wi_done_over",
            "done too long ago",
            status="done",
            updated_at="2026-10-05T09:59:59.999Z",
            history=_done_history(PRIYA),
        ),
        _own(PRIYA, "wi_over", "overdue", due="2026-10-05"),
        _own(PRIYA, "wi_today", "today", due="2026-10-06"),
        _own(PRIYA, "wi_plus2", "in two days", due="2026-10-08"),
        _own(PRIYA, "wi_plus3", "in three days", due="2026-10-09"),
        _own(PRIYA, "wi_none", "no date"),
    ]
    for item in items:
        rig.add("work_items", item)
    rig.as_user(PRIYA)
    plate = rig.plate().json()
    group = {row["ref"]["id"]: row["group"] for lane in ("rows", "parked") for row in plate[lane]}
    assert group == {
        "wi_snz_eq": "rest",
        "wi_snz_later": "snoozed",
        "wi_done_24h": "done",
        "wi_over": "overdue",
        "wi_today": "soon",
        "wi_plus2": "soon",
        "wi_plus3": "rest",
        "wi_none": "rest",
    }, group
    assert "wi_done_over" not in group
    assert oracle._plate_problems(plate) == []


def _done_history(user: str) -> list:
    from _ppl11a_lib import pl  # noqa: PLC0415

    return [pl.history_entry(user, "created", "open", EARLY), pl.history_entry(user, "done", "done", EARLY)]


def test_PPL_11a_PE_28_today_is_the_date_in_the_persons_time_zone_at_as_of(people_rig):
    """Asha in Asia/Kolkata at 20:00 UTC on 6 Oct is already on 7 Oct; a UTC person is still on 6 Oct (BQ-272)."""
    now = "2026-10-06T20:00:00.000Z"
    rig = people_rig(now=now)
    persons = copy.deepcopy(fixture_case("plate", "valid", "gate_card_in_her_own_world")["persons"])
    persons[SAM]["time_zone"] = "UTC"
    rig.add_people(persons.values())
    for who in (PRIYA, SAM):
        rig.add("work_items", _own(who, f"wi_{who[2:]}", "due the sixth", due="2026-10-06"))
    rig.as_user(PRIYA)
    kolkata = rig.plate().json()
    rig.as_user(SAM)
    utc = rig.plate().json()
    assert (kolkata["today"], utc["today"]) == ("2026-10-07", "2026-10-06")
    assert kolkata["rows"][0]["group"] == "overdue", "the 6th is yesterday in Kolkata"
    assert utc["rows"][0]["group"] == "soon", "the 6th is today for a UTC person"
    assert conforms("plate.schema.json", kolkata) and conforms("plate.schema.json", utc)


def test_PPL_11a_PE_28_ties_break_on_due_then_at_then_kind_then_id_with_null_last(people_rig):
    rig = people_rig()
    rig.add_people()
    from _ppl11a_lib import pl  # noqa: PLC0415

    pin = pl.pin(
        id="pb_tie",
        org_id="org_example",
        scope={"kind": "team", "team": "tm_launch"},
        due="2026-10-20",
        owner=PRIYA,
        set_up_by=OWNER,
        created_by=pl.maker_person(OWNER, EARLY),
        history=[pl.history_entry(OWNER, "created", "active", EARLY)],
        created_at=EARLY,
        updated_at=EARLY,
    )
    rig.add("pins", pin)
    for item_id, due in (("wi_b", "2026-10-20"), ("wi_a", "2026-10-20"), ("wi_nodate", None), ("wi_c", "2026-10-19")):
        rig.add("work_items", _own(PRIYA, item_id, item_id, due=due))
    rig.as_user(PRIYA)
    plate = rig.plate().json()
    assert refs(plate) == [
        ("work_item", "wi_c"),  # due 19 Oct first
        ("pinboard_item", "pb_tie"),  # same due and same `at`: kind "pinboard_item" sorts before "work_item"
        ("work_item", "wi_a"),
        ("work_item", "wi_b"),
        ("work_item", "wi_nodate"),  # no date: last in its group
    ]
    assert oracle._plate_problems(plate) == []


def test_PPL_11a_PE_27_caps_two_hundred_rows_and_a_hundred_parked_and_truncated_only_for_readable_overflow(people_rig):
    """At most 200 rows and 100 parked. `truncated` is true only when more rows that pass PE-26 and PE-27 exist than
    the cap: records the person may not read (a proposed item) never count, so it says nothing about them."""
    import time  # noqa: PLC0415

    from _ppl11a_lib import pl  # noqa: PLC0415

    def build(readable: int, parked: int, hidden: int):
        rig = people_rig()
        rig.add_people()
        for n in range(readable):
            rig.add("work_items", _own(PRIYA, f"wi_r{n:04d}", f"open {n}"))
        for n in range(parked):
            rig.add("work_items", _own(PRIYA, f"wi_p{n:04d}", f"snoozed {n}", snoozed_until="2026-10-07T10:00:00.000Z"))
        for n in range(hidden):  # Tilo's proposals no one may read (PE-03): they never join and are never counted
            hid = pl.work_item(
                id=f"wi_h{n:04d}",
                org_id="org_example",
                owner=PRIYA,
                status="proposed",
                confirmed_by=None,
                created_by=pl.maker_tilo("A_analyst", EARLY),
                assigned_by={"by": OWNER, "at": EARLY},
                source={"kind": "meeting", "ref": "mt_q4_plan#ai1", "evidence": []},
                history=[pl.history_entry("A_analyst", "created", "proposed", EARLY)],
                created_at=EARLY,
                updated_at=EARLY,
            )
            rig.add("work_items", hid)
        rig.as_user(PRIYA)
        started = time.monotonic()
        plate = rig.plate().json()
        assert time.monotonic() - started < 10, "a plate of a few hundred records is not slow"
        assert conforms("plate.schema.json", plate) and oracle._plate_problems(plate) == []
        return plate

    full = build(200, 0, 60)
    assert (len(full["rows"]), full["truncated"]) == (200, False), "exactly 200 readable rows, plus 60 unreadable ones"
    over = build(201, 0, 0)
    assert (len(over["rows"]), over["truncated"]) == (200, True)
    assert [r["ref"]["id"] for r in over["rows"]] == [f"wi_r{n:04d}" for n in range(200)], "the cap keeps the first 200"
    parked = build(0, 101, 0)
    assert (len(parked["parked"]), parked["truncated"]) == (100, True)
    exact = build(0, 100, 0)
    assert (len(exact["parked"]), exact["truncated"]) == (100, False)


def test_PPL_11a_PE_29_the_plate_row_does_not_depend_on_what_the_transcript_holds(people_rig):
    """`evidence` on a plate row is true for an item that cites an utterance whatever the transcript's screening or
    content (the row never carries a quote or a count of what exists)."""
    rows = []
    for screening in ("clean", "flagged", "unscreened"):
        case = fixture_case("transcript", "valid", "assignee_reads_one_quote")
        case["version"]["screening"] = screening
        rig = people_rig()
        rig.seed_quote_case(case)
        rig.as_user(PRIYA)
        plate = rig.plate().json()
        rows.append([r for r in plate["rows"] if r["ref"]["id"] == "wi_rate_sheet"])
    assert rows[0] and rows[0] == rows[1] == rows[2]
    assert rows[0][0]["evidence"] is True
