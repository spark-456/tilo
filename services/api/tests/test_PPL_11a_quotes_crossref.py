"""PPL-11a slice A: the evidence-quote read model through the real API (ADR-0020; contracts/people.rules.md PE-19,
PE-22 to PE-25; BQ-265 to BQ-268, BQ-273, BQ-CCP3-2, BQ-CCP3-3). Every `fixtures/transcript/crossref/` case, valid
and invalid, is seeded as stored state (people stores, minutes and transcript on the artifact store in the
meeting's own scope), asked over HTTP as the case's actor, and must answer exactly what the reference oracle in
`tests/contracts/test_CC_PEOPLE_3_quotes_and_plate.py` answers: `evidence_quotes`, or a 404.

Routes (API_PPL_11a.md section 2): `GET /v1/meetings/{meeting_id}/quotes?ids=u0021,u0023` (the meeting owner) and
`GET /v1/work-items/{work_item_id}/quote` (the item's owner). The owner route takes 1 to 20 ids; the item route takes
no argument and picks the one quote itself. A refusal is a 404 whose body never depends on why.
"""

from __future__ import annotations

import copy

import pytest
from _ppl11a_lib import (
    DEV,
    MEERA,
    OTHER_ORG,
    OWNER,
    PRIYA,
    SAM,
    case_params,
    conforms,
    fixture_case,
    oracle,
)

QUOTES_DEF = "transcript.schema.json#/$defs/evidence_quotes"


def _ask(make_rig, case):
    rig = make_rig()
    rig.seed_quote_case(case)
    return rig, rig.quote_request(case)


# --- every crossref case, valid and invalid, through the real API ---------------------------------------------------


@pytest.mark.parametrize(("kind", "name", "case"), case_params("transcript"))
def test_PPL_11a_PE_23_every_transcript_crossref_case_gets_the_oracles_answer(people_rig, kind, name, case):
    """Given the case's stored state, when its actor asks, then the API answers `expected_quotes(case)`: 200 with the
    oracle's exact `evidence_quotes` (and it validates against the transcript contract), or a 404. An invalid case
    names an answer the rules forbid, and the API must not give that one."""
    _, response = _ask(people_rig, case)
    expected = oracle.expected_quotes(case)
    if name == "pe19_version_from_another_world":
        # The oracle sees a version stored in another world and says 404. A real store only says "not found in this
        # scope", which is what a swept transcript looks like too (API_PPL_11a.md ambiguity 3): the API may answer
        # either the 404 or an all-`expired` answer for a reader PE-23 admits, never text.
        assert response.status_code in (404, 200), response.text[:200]
        if response.status_code == 200:
            assert {q["state"] for q in response.json()["quotes"]} == {"expired"}
        assert "text" not in response.text or '"text":null' in response.text.replace(" ", "")
        return
    if expected is None:
        assert response.status_code == 404, f"{kind}/{name}: {response.status_code} {response.text[:200]}"
        assert "text" not in response.text and "quotes" not in response.text, "a 404 carries no quote"
    else:
        assert response.status_code == 200, f"{kind}/{name}: {response.status_code} {response.text[:200]}"
        assert response.json() == expected, f"{kind}/{name}"
        assert conforms(QUOTES_DEF, response.json()), f"{kind}/{name}: the answer must validate (evidence_quotes)"
        if case["request"]["work_item"] is not None and case["meeting"]:
            assert case["meeting"]["title"] not in response.text, "an assignee never sees the meeting title (BQ-266)"
            assert len(response.json()["quotes"]) <= 1, "an assignee gets at most one quote (PE-23)"
    if kind == "invalid" and case["response"] is not None:
        got = response.json() if response.status_code == 200 else None
        assert got != case["response"], f"{name}: the API answered what the rule forbids"


def test_PPL_11a_PE_23_a_404_is_byte_identical_whatever_the_reason(people_rig):
    """No existence oracle: on each route every refusal (not the owner, never existed, another org, an item that is
    not theirs, a proposed item, unconfirmed minutes, ...) is the same status and the same body."""
    by_route: dict[str, set[tuple[int, str]]] = {"meeting": set(), "item": set()}
    for _kind, name, case in _all_transcript_cases():
        if oracle.expected_quotes(case) is not None or name == "pe19_version_from_another_world":
            continue
        _, response = _ask(people_rig, case)
        route = "meeting" if case["request"]["meeting"] is not None else "item"
        by_route[route].add((response.status_code, response.text))
    for route, seen in by_route.items():
        assert len(seen) == 1, f"the {route} route answered {len(seen)} different refusals: {sorted(seen)[:3]}"
        assert next(iter(seen))[0] == 404


def _all_transcript_cases():
    from _ppl11a_lib import crossref_cases  # noqa: PLC0415

    return crossref_cases("transcript")


# --- BQ-CCP3-2: a missing, a discarded, a deleted and a swept meeting, on both routes -------------------------------


def _owner_route(case: dict, actor: str, ids=("u0021", "u0023")) -> dict:
    mid = case["meeting"]["id"] if case["meeting"] else case["request"]["meeting"] or "mt_q4_plan"
    out = copy.deepcopy(case)
    out["request"] = {"actor": actor, "meeting": mid, "work_item": None, "ids": list(ids)}
    return out


def _item_route(case: dict, actor: str) -> dict:
    out = copy.deepcopy(case)
    wi = case["work_item"]["id"] if case["work_item"] else "wi_rate_sheet"
    out["request"] = {"actor": actor, "meeting": None, "work_item": wi, "ids": []}
    return out


def _states():
    """(label, a case for the owner route, a case for the item route) per state of the meeting."""
    t = lambda kind, n: fixture_case("transcript", kind, n)  # noqa: E731
    return [
        ("live", t("valid", "owner_reads_quotes"), t("valid", "assignee_reads_one_quote")),
        (
            "missing",
            t("valid", "meeting_that_never_existed_answers_a_404"),
            t("valid", "assignee_item_whose_meeting_is_missing"),
        ),
        (
            "discarded",
            t("valid", "assignee_item_from_a_discarded_meeting"),
            t("valid", "assignee_item_from_a_discarded_meeting"),
        ),
        (
            "deleted",
            t("valid", "owner_reads_quotes_of_a_deleted_meeting"),
            t("valid", "assignee_item_from_a_deleted_meeting"),
        ),
        ("swept", t("valid", "assignee_expired_after_the_sweep"), t("valid", "assignee_expired_after_the_sweep")),
    ]


ACTORS = (
    OWNER,
    PRIYA,
    DEV,
    SAM,
    MEERA,
    "u_ext",
    "u_ghost",
)  # owner, assignee, teammate, attendee, org owner, other org, nobody


@pytest.mark.parametrize("label", ["live", "missing", "discarded", "deleted", "swept"])
def test_PPL_11a_BQ_CCP3_2_owner_route_answers_only_the_owner_and_everyone_else_gets_the_same_404(people_rig, label):
    """Given the meeting is live, missing, discarded, deleted or swept, when each of seven people asks the owner
    route, then only the meeting owner is answered (every id `expired`, transcript null, once it is gone), and
    everyone else, including an org owner and a person of another org, gets the one 404 body."""
    owner_case = {s[0]: s[1] for s in _states()}[label]
    bodies, answers = set(), {}
    for actor in ACTORS:
        case = _owner_route(owner_case, actor)
        case["persons"] = {**case["persons"], "u_ext": _ext_person()}
        _, response = _ask(people_rig, case)
        expected = oracle.expected_quotes(case)
        assert response.status_code == (404 if expected is None else 200), f"{label}/{actor}"
        if expected is not None:
            assert response.json() == expected, f"{label}/{actor}"
            answers[actor] = response.json()
        else:
            bodies.add(response.text)
    assert len(bodies) == 1, f"{label}: the 404s differ: {bodies}"
    if label == "missing":
        assert answers == {}, "a meeting that never existed has no owner, so nobody is answered"
    else:
        assert set(answers) == {OWNER}, f"{label}: only the meeting owner is answered, got {sorted(answers)}"
    if label in ("discarded", "deleted", "swept"):
        quotes = answers[OWNER]["quotes"]
        assert [q["state"] for q in quotes] == ["expired", "expired"] and all(q["transcript"] is None for q in quotes)
        assert all(q["text"] is None and q["speaker"] is None and q["truncated"] is False for q in quotes)


@pytest.mark.parametrize("label", ["live", "missing", "discarded", "deleted", "swept"])
def test_PPL_11a_BQ_CCP3_2_item_route_answers_only_the_items_owner_from_the_items_own_data(people_rig, label):
    """Given the item's meeting is live, missing, discarded, deleted or swept, when each of seven people asks the
    item route, then only the item's owner is answered (never the assigner, an attendee, a teammate, an org owner,
    another org), and everyone else gets the item's one 404 whatever the meeting's state."""
    item_case = {s[0]: s[2] for s in _states()}[label]
    bodies, answers = set(), {}
    for actor in ACTORS:
        case = _item_route(item_case, actor)
        case["persons"] = {**case["persons"], "u_ext": _ext_person()}
        _, response = _ask(people_rig, case)
        expected = oracle.expected_quotes(case)
        assert response.status_code == (404 if expected is None else 200), f"{label}/{actor}"
        if expected is not None:
            assert response.json() == expected, f"{label}/{actor}"
            answers[actor] = response.json()
        else:
            bodies.add(response.text)
    assert len(bodies) == 1, f"{label}: the 404s differ"
    assert set(answers) == {PRIYA}, f"{label}: only the item's owner is answered, got {sorted(answers)}"
    quotes = answers[PRIYA]["quotes"]
    assert len(quotes) <= 1, "an assignee gets at most one quote (PE-23)"
    if label in ("missing", "discarded", "deleted", "swept"):
        assert [(q["state"], q["utterance_id"], q["transcript"]) for q in quotes] == [("expired", "u0021", None)]


def test_PPL_11a_BQ_CCP3_2_swept_and_deleted_name_the_same_utterance_id(people_rig):
    """The item route names the lowest id the item itself cites on every gone path (swept, deleted, discarded,
    missing), so the id says nothing about which path it was."""
    ids = set()
    for label in ("missing", "discarded", "deleted", "swept"):
        case = _item_route({s[0]: s[2] for s in _states()}[label], PRIYA)
        _, response = _ask(people_rig, case)
        ids.add(tuple(q["utterance_id"] for q in response.json()["quotes"]))
    assert ids == {("u0021",)}, ids


def _ext_person() -> dict:
    p = copy.deepcopy(fixture_case("transcript", "valid", "owner_reads_quotes")["persons"][PRIYA])
    p.update(id="u_ext", org_id=OTHER_ORG, display_name="Eve Outsider", email="eve@example.net")
    p["memberships"] = [{"team": "tm_launch", "assigned_by": {"by": "u_ext", "at": "2026-10-05T09:00:00.000Z"}}]
    p["org_role"] = "owner"
    p["created_by"] = {"by": "u_ext", "at": "2026-10-05T09:00:00.000Z"}
    return p


# --- request shape: no argument can widen an answer -----------------------------------------------------------------


def test_PPL_11a_PE_23_owner_route_takes_one_to_twenty_well_formed_ids_in_request_order(people_rig):
    case = fixture_case("transcript", "valid", "owner_reads_quotes")
    rig = people_rig()
    rig.seed_quote_case(case)
    rig.require_route(("GET", "/v1/meetings/{meeting_id}/quotes"))
    ids = [f"u{n:04d}" for n in (23, 21, 22, 20, 99, 1)]  # u0099 and u0001 are not in the transcript
    ok = rig.get("/v1/meetings/mt_q4_plan/quotes", params={"ids": ",".join(ids)})
    assert ok.status_code == 200
    quotes = ok.json()["quotes"]
    assert [q["utterance_id"] for q in quotes] == ids, "one quote per id, in the order asked"
    assert [q["state"] for q in quotes] == ["shown", "shown", "shown", "shown", "missing", "missing"]
    twenty = [f"u{n:04d}" for n in range(1, 21)]
    assert rig.get("/v1/meetings/mt_q4_plan/quotes", params={"ids": ",".join(twenty)}).status_code == 200
    for bad in ("", ",", "u0021,", "u0021,,u0022", "x0021", "U0021", "u21", "u0021 u0022", "u0021;u0022"):
        assert rig.get("/v1/meetings/mt_q4_plan/quotes", params={"ids": bad}).status_code == 422, bad
    assert rig.get("/v1/meetings/mt_q4_plan/quotes").status_code == 422, "ids is required"
    too_many = [f"u{n:04d}" for n in range(1, 22)]
    assert rig.get("/v1/meetings/mt_q4_plan/quotes", params={"ids": ",".join(too_many)}).status_code == 422


def test_PPL_11a_PE_23_a_bad_ids_list_is_refused_before_any_lookup_so_it_is_no_oracle(people_rig):
    """The shape check comes first: a non-owner, a person with no record and a meeting that never existed all get
    the same 422 for a malformed list, and the same 404 for a well-formed one."""
    case = fixture_case("transcript", "valid", "attendee_gets_a_404_on_the_owner_route")
    rig = people_rig()
    rig.seed_quote_case(case)  # u_sam, an attendee, is signed in
    rig.require_route(("GET", "/v1/meetings/{meeting_id}/quotes"))
    for meeting in ("mt_q4_plan", "mt_never_held"):
        assert rig.get(f"/v1/meetings/{meeting}/quotes", params={"ids": ""}).status_code == 422
        assert rig.get(f"/v1/meetings/{meeting}/quotes", params={"ids": "u0021"}).status_code == 404
    rig.as_user("u_ghost")
    assert rig.get("/v1/meetings/mt_q4_plan/quotes", params={"ids": ""}).status_code == 422
    assert rig.get("/v1/meetings/mt_q4_plan/quotes", params={"ids": "u0021"}).status_code == 404


def test_PPL_11a_PE_23_malformed_path_ids_are_the_same_404_as_unknown_ones(people_rig):
    case = fixture_case("transcript", "valid", "owner_reads_quotes")
    rig = people_rig()
    rig.seed_quote_case(case)
    rig.require_route(("GET", "/v1/meetings/{meeting_id}/quotes"))
    rig.require_route(("GET", "/v1/work-items/{work_item_id}/quote"))
    seen = set()
    for meeting in ("mt_never_held", "not_a_meeting", "mt_" + "a" * 100, "MT_q4_plan"):
        r = rig.get(f"/v1/meetings/{meeting}/quotes", params={"ids": "u0021"})
        seen.add((r.status_code, r.text))
    assert len(seen) == 1 and next(iter(seen))[0] == 404, seen
    seen = set()
    for item in ("wi_never_made", "not_an_item", "wi_" + "a" * 100, "WI_rate_sheet"):
        r = rig.get(f"/v1/work-items/{item}/quote")
        seen.add((r.status_code, r.text))
    assert len(seen) == 1 and next(iter(seen))[0] == 404, seen


def test_PPL_11a_PE_23_item_route_takes_no_argument_so_an_assignee_cannot_ask_for_a_second_quote(people_rig):
    """PE-23: at most one quote. Whatever query arguments the assignee adds, the answer is the one quote."""
    case = fixture_case("transcript", "valid", "assignee_reads_one_quote")
    rig = people_rig()
    rig.seed_quote_case(case)
    plain = rig.quote_request(case)
    assert plain.status_code == 200 and len(plain.json()["quotes"]) == 1
    for params in (
        {"ids": "u0022,u0023"},
        {"id": "u0023"},
        {"utterance": "u0020"},
        {"n": "5"},
        {"limit": "20"},
        {"ids": "u0020"},
    ):
        again = rig.get("/v1/work-items/wi_rate_sheet/quote", params=params)
        assert again.status_code == 200 and again.json() == plain.json(), params
    posted = rig.client.post("/v1/work-items/wi_rate_sheet/quote", json={"ids": ["u0022"]})
    assert posted.status_code in (404, 405), "the quote is read with GET only"


@pytest.mark.parametrize("role", ["viewer", "approver", "team_lead", "owner"])
def test_PPL_11a_PE_05_world_roles_neither_grant_nor_take_away_a_quote(people_rig, role):
    """A quote follows the person (PE-05, PE-23), never a world role on the session's principal."""
    for name, route in (("owner_reads_quotes", "meeting"), ("assignee_reads_one_quote", "item")):
        case = fixture_case("transcript", "valid", name)
        rig = people_rig()
        rig.seed_quote_case(case)
        rig.as_user(case["request"]["actor"], role=role, world_id="w_meeting_q4_plan")
        response = rig.quote_request(case)
        assert response.status_code == 200 and response.json() == oracle.expected_quotes(case), (name, role)
    stranger = fixture_case("transcript", "valid", "attendee_gets_a_404_on_the_owner_route")
    rig = people_rig()
    rig.seed_quote_case(stranger)
    rig.as_user(SAM, role="owner", world_id="w_meeting_q4_plan")  # the owner of a world is not the meeting's owner
    assert rig.quote_request(stranger).status_code == 404


# --- one org only, one store call path -----------------------------------------------------------------------------


def test_PPL_11a_PE_17_the_api_loads_one_org_and_only_that_orgs_records(people_rig, monkeypatch):
    """The org is `deps.ORG_ID`, never a request's. Every store call names it; with the process in another org the
    same stored data answers nothing (the owner is no person there and the meeting is not in that org)."""
    case = fixture_case("transcript", "valid", "assignee_reads_one_quote")
    rig = people_rig()
    rig.seed_quote_case(case)
    assert rig.quote_request(case).status_code == 200
    orgs = {org for _, _, org in rig.store_calls}
    assert orgs == {case["meeting"]["org_id"]}, f"store calls named {orgs}"
    other = people_rig()
    other.seed_quote_case(case)
    monkeypatch.setattr(other.deps, "ORG_ID", OTHER_ORG)  # the process serves another org than the stored data's
    other.store_calls.clear()
    for actor, asked in ((PRIYA, _item_route(case, PRIYA)), (OWNER, _owner_route(case, OWNER, ids=("u0021",)))):
        other.as_user(actor)
        assert other.quote_request(asked).status_code == 404, "another org's data is nobody's here"
    assert other.store_calls, "the store was asked"
    assert {org for _, _, org in other.store_calls} == {OTHER_ORG}, "no store call may name the data's org"


def test_PPL_11a_PE_17_a_person_with_the_same_id_in_another_org_changes_nothing(people_rig):
    """Team ids are not org-scoped and `Directory.of` drops an id held twice, so loading two orgs would break the
    first. A second org holding `u_priya` and the team `tm_launch` must not change the first org's answers."""
    case = fixture_case("transcript", "valid", "assignee_reads_one_quote")
    rig = people_rig()
    rig.seed_quote_case(case)
    twin = copy.deepcopy(case["persons"][PRIYA])
    twin.update(org_id=OTHER_ORG, display_name="Priya Elsewhere", email="priya@example.net")
    twin["memberships"] = [{"team": "tm_launch", "assigned_by": {"by": "u_bossb", "at": "2026-10-05T09:00:00.000Z"}}]
    boss = copy.deepcopy(twin)
    boss.update(id="u_bossb", org_role="owner", display_name="Boss B", email="boss@example.net")
    boss["memberships"] = []
    boss["created_by"] = twin["created_by"] = {"by": "u_bossb", "at": "2026-10-05T09:00:00.000Z"}
    rig.real.persons.create(boss)
    rig.real.persons.create(twin)
    response = rig.quote_request(case)
    assert response.status_code == 200 and response.json() == oracle.expected_quotes(case)


# --- a store that cannot be read fails closed, never a half answer --------------------------------------------------


def test_PPL_11a_PE_22_a_transcript_missing_before_its_time_is_expired_for_the_owner(people_rig):
    """A live meeting whose transcript version is not on the store (swept early, or never written) is `expired`
    for a reader PE-23 admits, with transcript null; the API never invents a quote."""
    case = fixture_case("transcript", "valid", "owner_reads_quotes")
    case["version"], case["transcript"] = None, None
    expected = oracle.expected_quotes(case)
    assert expected is not None and all(q["state"] == "expired" for q in expected["quotes"])
    _, response = _ask(people_rig, case)
    assert response.status_code == 200 and response.json() == expected


def test_PPL_11a_PE_22_the_clock_decides_expiry_even_while_the_transcript_is_still_stored(people_rig):
    """`delete_transcript_after` (30 days, FR-MTG-10) is checked against the server clock with `>=`: one millisecond
    before, the quote is shown; at the instant and after, it is `expired` although the sweeper has not run."""
    base = fixture_case("transcript", "valid", "owner_reads_quotes")
    after = base["meeting"]["delete_transcript_after"]  # 2026-11-04T10:00:00.000Z
    before = "2026-11-04T09:59:59.999Z"
    for route_case, label in (
        (base, "owner"),
        (fixture_case("transcript", "valid", "assignee_reads_one_quote"), "assignee"),
    ):
        for now, state in ((before, "shown"), (after, "expired"), ("2026-12-01T00:00:00.000Z", "expired")):
            case = copy.deepcopy(route_case)
            case["now"] = now
            case["meeting"]["minutes_confirmed_by"]["at"] = "2026-10-05T10:30:00.000Z"
            rig = people_rig()
            rig.seed_quote_case(case)  # the transcript IS on the store at every one of these clocks
            response = rig.quote_request(case)
            assert response.status_code == 200, (label, now, response.text[:200])
            states = {q["state"] for q in response.json()["quotes"]}
            assert states == {state}, (label, now, states)
            if state == "expired":
                assert all(q["transcript"] is None and q["text"] is None for q in response.json()["quotes"])


@pytest.mark.parametrize("name", ["owner_reads_quotes", "assignee_reads_one_quote"])
def test_PPL_11a_PE_22_a_corrupt_transcript_blob_is_a_503_with_no_text(people_rig, name):
    """The artifact store refuses a blob that does not match its hash (AR-01). The API answers 503, with no partial
    quote, no traceback, and never `shown`; and a non-owner still gets only the 404 (the store is not read for them)."""
    case = fixture_case("transcript", "valid", name)
    rig = people_rig()
    rig.seed_quote_case(case)
    rig.monkeypatch.setattr(rig.blobs, "read", lambda key: b'{"v":"1.0","meeting_id":"mt_q4_plan","utterances":[]}')
    response = rig.quote_request(case)
    assert response.status_code == 503, response.text[:200]
    assert "text" not in response.json() and "quotes" not in response.json()
    assert "Traceback" not in response.text
    rig.as_user("u_ghost")
    assert rig.quote_request({**case, "request": {**case["request"], "actor": "u_ghost"}}).status_code == 404
