"""PPL-11a slice A: the people routes behind the SEC-15 gate, their production seams failing closed, dev mode on fakes,
and no model, live switch or SEC-16 seam touched (API_PPL_11a.md sections 1, 6 and 7; SEC-15, SEC-16, EFF-01, PL-01).

Deployed (`K_SERVICE`), a visitor, an undeclared person and a signed-out caller are refused before any people seam,
store or source is touched; a judge reaches the route's own rules unchanged. Not deployed, a seam with no wiring answers
503 `not_configured` (never 500, never an empty 200). Dev mode (`TILO_API_DEV=1`, `dev.install`) wires in-memory
fakes and refuses when deployed or live, like every dev stand-in. The people code makes no model call, builds no
router and reads neither `replay_only` nor `LIVE` nor `TILO_JUDGE_LIVE`.
"""

from __future__ import annotations

import pathlib
import re

import pytest
from _clint1_lib import seam
from _ppl11a_lib import (
    ATTEST,
    DEV,
    OWNER,
    PEOPLE_ROUTES,
    PRIYA,
    R_CONFIRM_ITEM,
    R_CONFIRM_MEETING,
    R_CREATE_ITEM,
    R_CREATE_MEETING,
    R_CREATE_PERSON,
    R_ITEM_QUOTE,
    R_PLATE,
    R_QUOTES,
    SAM,
    fixture_case,
    own_item,
)
from _sec15_lib import (
    CODE_DECLARATION_REQUIRED,
    CODE_UNDER_CONSTRUCTION,
    PINNED_PUBLIC_ROUTES,
    FakeAccessStore,
    concrete,
)
from fastapi import FastAPI
from fastapi.testclient import TestClient

SRC = pathlib.Path(__file__).resolve().parents[1] / "src" / "tilo_api"
VISITOR, JUDGE, NEWCOMER = SAM, PRIYA, OWNER  # a visitor, a judge and a person who never declared (see `_access`)


def _access() -> FakeAccessStore:
    return FakeAccessStore({SAM: "visitor", PRIYA: "judge", DEV: "judge"})


def _call(rig, route, **kwargs):
    method, template = route
    return rig.client.request(method, concrete(template), **kwargs)


def _valid_request(route) -> dict:
    """A request of the right shape for each route: the seam check must come from the wiring, not from validation."""
    if route == R_QUOTES:
        return {"params": {"ids": "u0021"}}
    if route in (R_CONFIRM_ITEM, R_CONFIRM_MEETING):
        return {"json": {}}
    if route == R_CREATE_MEETING:
        return {"json": {"title": "Weekly sync", "source": "upload", **ATTEST}}
    if route == R_CREATE_PERSON:
        return {"json": _NEW_PERSON}
    if route == R_CREATE_ITEM:
        return {"json": {"title": "Water the plants", "source": {"kind": "manual", "ref": None}}}
    return {}


_NEW_PERSON = {
    "display_name": "New Person",
    "aliases": [],
    "email": "new@example.com",
    "time_zone": "Asia/Kolkata",
    "preferred_channel": "web",
}


# --- the routes exist and none is public ----------------------------------------------------------------------------


def test_PPL_11a_SEC_15_the_people_routes_exist_and_none_of_them_is_public(people_rig):
    from tilo_api import access  # noqa: PLC0415

    rig = people_rig()
    for route in PEOPLE_ROUTES:
        rig.require_route(route)
        assert route not in access.PUBLIC_ROUTES
    assert (
        access.PUBLIC_ROUTES
        == PINNED_PUBLIC_ROUTES
        == frozenset({("GET", "/health"), ("GET", "/healthz"), ("GET", "/access"), ("POST", "/access/declaration")})
    ), "a people route is never public (a new public route is the owner's decision)"


# --- deployed: the SEC-15 gate --------------------------------------------------------------------------------------


@pytest.mark.parametrize("route", PEOPLE_ROUTES, ids=[f"{m} {p}" for m, p in PEOPLE_ROUTES])
def test_PPL_11a_SEC_15_a_visitor_an_undeclared_person_and_nobody_are_refused_before_anything_is_touched(
    people_rig, route
):
    """Given a deployed process, when a visitor calls any people route with any body, then 403 `under_construction`,
    the same body every time; an undeclared person gets 403 `declaration_required`; a signed-out caller 401. In every
    case no people seam was resolved, no store or source was read, nothing was written and no router was built."""
    rig = people_rig(deployed=True, access=_access())
    rig.require_route(route)
    rig.add_people()
    before = rig.snapshot()
    bodies = (
        {},
        {"json": {}},
        {"data": {"declaration": "judge"}},
        {"content": "x", "headers": {"content-type": "text/plain"}},
        _valid_request(route),
    )
    seen = set()
    rig.as_user(VISITOR)
    for kwargs in bodies:
        response = _call(rig, route, **kwargs)
        assert response.status_code == 403 and response.json()["code"] == CODE_UNDER_CONSTRUCTION, (
            kwargs,
            response.text,
        )
        seen.add(response.text)
    assert len(seen) == 1, "the refusal is identical for every body and route state"
    rig.as_user(NEWCOMER)
    response = _call(rig, route, **_valid_request(route))
    assert response.status_code == 403 and response.json()["code"] == CODE_DECLARATION_REQUIRED
    rig.sign_out()
    assert _call(rig, route, **_valid_request(route)).status_code == 401
    assert rig.resolved == [], f"a refused request resolved {rig.resolved}"
    assert rig.store_calls == [] and rig.sources.calls == [] and rig.owners.calls == []
    assert rig.snapshot() == before and rig.router_calls == []


@pytest.mark.parametrize("route", [R_PLATE, R_QUOTES, R_CREATE_MEETING], ids=lambda r: f"{r[0]} {r[1]}")
def test_PPL_11a_SEC_15_a_deployed_process_with_no_access_store_lets_nobody_in(people_rig, route):
    rig = people_rig(deployed=True)  # no `get_access_store` override: the production default
    rig.require_route(route)
    rig.as_user(PRIYA)
    response = _call(rig, route, **_valid_request(route))
    assert response.status_code == 503 and rig.resolved == []


def test_PPL_11a_SEC_15_a_judge_reaches_the_routes_own_rules_unchanged(people_rig):
    """The gate adds nothing and takes nothing: a judge is answered by the route's own rules (their own plate, a 404
    for another person's meeting, a 403 where only an org owner may act)."""
    rig = people_rig(deployed=True, access=_access())
    rig.add_people()
    rig.add("work_items", own_item("wi_priya", PRIYA))
    rig.as_user(JUDGE)
    plate = rig.plate()
    assert plate.status_code == 200 and [r["ref"]["id"] for r in plate.json()["rows"]] == ["wi_priya"]
    case = fixture_case("transcript", "valid", "owner_reads_quotes")
    rig2 = people_rig(deployed=True, access=FakeAccessStore({PRIYA: "judge", OWNER: "judge"}))
    rig2.seed_quote_case(case)
    rig2.as_user(PRIYA)
    assert rig2.get("/v1/meetings/mt_q4_plan/quotes", params={"ids": "u0021"}).status_code == 404
    rig2.as_user(OWNER)
    assert rig2.get("/v1/meetings/mt_q4_plan/quotes", params={"ids": "u0021"}).status_code == 200
    rig2.as_user(PRIYA)
    forbidden = rig2.post("/v1/people", _NEW_PERSON)
    assert forbidden.status_code == 403, "a member may not create a person (PE-17)"


# --- not deployed: a seam with no wiring fails closed ---------------------------------------------------------------


def test_PPL_11a_PE_19_every_people_route_is_503_not_configured_until_its_seams_are_wired(people_rig):
    """Production defaults refuse like T4's: with the people stores unwired every route is 503 `not_configured`
    (never a 500, never an empty 200 or a 404 that looks like an answer)."""
    rig = people_rig()
    rig.add_people()
    rig.unwire("people_stores", "artifact_store", "redactor", "plate_sources", "source_owners")
    rig.as_user(PRIYA)
    for route in PEOPLE_ROUTES:
        rig.require_route(route)
        response = _call(rig, route, **_valid_request(route))
        assert response.status_code == 503, (route, response.status_code, response.text[:120])
        assert response.json() == {"detail": "not_configured"}, route


def test_PPL_11a_PE_19_each_route_needs_exactly_the_seams_it_uses(people_rig):
    """Wired stores alone: the plate still needs its sources, quotes still need the artifact store and the redactor,
    and a write needs the redactor; with the sources wired but no stores the plate is still 503."""
    rig = people_rig()
    rig.add_people()
    rig.as_user(OWNER)
    rig.unwire("artifact_store", "redactor", "plate_sources", "source_owners")
    assert _call(rig, R_PLATE).status_code == 503, "no plate sources"
    assert _call(rig, R_QUOTES, params={"ids": "u0021"}).status_code == 503, "no artifact store, no redactor"
    assert _call(rig, R_ITEM_QUOTE).status_code == 503
    assert _call(rig, R_CREATE_MEETING, **_valid_request(R_CREATE_MEETING)).status_code == 503, "no redactor"
    rig.unwire("people_stores")
    rig.app.dependency_overrides[seam(rig.deps, "get_plate_sources")] = lambda: rig.sources
    assert _call(rig, R_PLATE).status_code == 503, "no stores"


def test_PPL_11a_PE_19_an_unwired_artifact_store_is_a_503_for_everyone_so_it_is_no_oracle(people_rig):
    case = fixture_case("transcript", "valid", "owner_reads_quotes")
    rig = people_rig()
    rig.seed_quote_case(case)
    rig.unwire("artifact_store")
    statuses = set()
    for actor in (OWNER, PRIYA, SAM, "u_ghost"):
        rig.as_user(actor)
        statuses.add(rig.get("/v1/meetings/mt_q4_plan/quotes", params={"ids": "u0021"}).status_code)
        statuses.add(rig.get("/v1/meetings/mt_never_held/quotes", params={"ids": "u0021"}).status_code)
    assert statuses == {503}


# --- dev mode on fakes ----------------------------------------------------------------------------------------------


def _dev_client(monkeypatch):
    from tilo_api import dev  # noqa: PLC0415
    from tilo_api.people import router  # noqa: PLC0415

    for name in ("LIVE", "K_SERVICE", "CLOUD_RUN_JOB"):
        monkeypatch.delenv(name, raising=False)
    app = FastAPI()
    app.include_router(router)
    dev.install(app, {})
    return app, TestClient(app, base_url=f"http://localhost:{dev.PORT}", raise_server_exceptions=False)


def test_PPL_11a_PE_17_dev_mode_serves_its_one_owner_an_empty_plate_and_lets_them_create_people_and_meetings(
    monkeypatch,
):
    from tilo_api import dev  # noqa: PLC0415

    _, client = _dev_client(monkeypatch)
    plate = client.get("/v1/plate")
    assert plate.status_code == 200 and plate.json()["user"] == dev.DEV_OWNER
    assert plate.json()["rows"] == [] and plate.json()["parked"] == [] and plate.json()["truncated"] is False
    person = client.post("/v1/people", json=_NEW_PERSON)
    assert person.status_code == 201 and person.json()["id"].startswith("u_"), "the dev owner is an org owner"
    meeting = client.post("/v1/meetings", json=_valid_request(R_CREATE_MEETING)["json"])
    assert meeting.status_code == 201 and meeting.json()["owner"] == dev.DEV_OWNER


@pytest.mark.parametrize("var", ["K_SERVICE", "CLOUD_RUN_JOB"])
def test_PPL_11a_EFF_01_the_dev_people_seams_refuse_once_the_process_turns_out_to_be_deployed_or_live(monkeypatch, var):
    from tilo_api import deps, dev  # noqa: PLC0415

    app, _ = _dev_client(monkeypatch)
    names = ("get_people_stores", "get_plate_sources", "get_source_owners")
    for seam_name in names:
        app.dependency_overrides[seam(deps, seam_name)]()  # fine while local
    monkeypatch.setenv(var, "tilo-api")
    for seam_name in names:
        with pytest.raises(dev.DevModeRefused):
            app.dependency_overrides[seam(deps, seam_name)]()
    monkeypatch.delenv(var)
    live_var = "LIVE"
    monkeypatch.setenv(live_var, "1")
    with pytest.raises(dev.DevModeRefused):
        app.dependency_overrides[seam(deps, "get_people_stores")]()


def test_PPL_11a_EFF_01_the_dev_people_stores_are_one_in_memory_set_shared_by_every_request(monkeypatch):
    from tilo_api import deps  # noqa: PLC0415

    app, client = _dev_client(monkeypatch)
    stores = app.dependency_overrides[seam(deps, "get_people_stores")]
    assert stores() is stores(), "one set per dev.install, so a write is read back by the next request"
    created = client.post("/v1/people", json=_NEW_PERSON).json()["id"]
    assert stores().persons.get(deps.ORG_ID, created) is not None


# --- no model, no live switch, no SEC-16 seam, no network -----------------------------------------------------------


def _people_sources() -> list[pathlib.Path]:
    found = sorted([*SRC.glob("people*.py"), *SRC.glob("people*/*.py")])
    assert found, "tilo_api has no people module yet"
    return found


def test_PPL_11a_PL_01_the_people_code_names_no_model_no_switch_no_network_and_no_sec16_seam():
    """Static: the people modules make no model call (PL-01), read none of the switches EFF-01 and SEC-15 own, do
    not import the provider layer or a network client, and never print."""
    forbidden = {
        "a model id": r"(?i)\b(gemini|gpt-?[0-9]|claude|llama|nemotron|mistral|qwen|deepseek)\b",
        "a live switch": r"\bLIVE\b|TILO_JUDGE_LIVE|replay_only|K_SERVICE|CLOUD_RUN_JOB",
        "the provider layer": r"tilo_providers|router_for_mode|get_router|get_safety|provider_mode",
        "a flag or mode seam": r"get_flag_store|get_mode\b|get_access_store",
        "a network client": r"\b(import|from)\s+(httpx|requests|urllib|socket|aiohttp|http\.client)\b",
        "print": r"(?m)^\s*print\(",
        "a secret-looking literal": r"(?i)(api[_-]?key|secret|password|token)\s*=\s*[\"'][A-Za-z0-9_\-]{12,}[\"']",
    }
    for path in _people_sources():
        text = path.read_text(encoding="utf-8")
        for what, pattern in forbidden.items():
            assert not re.search(pattern, text), f"{path.name} contains {what}"


def test_PPL_11a_SEC_16_serving_people_requests_builds_no_router_and_reads_no_flag(people_rig):
    """Behaviour, with a router spy that fails the test: a run of people routes builds no model router and never
    resolves the flag store (`replay_only`) or the request's model mode."""
    case = fixture_case("transcript", "valid", "assignee_reads_one_quote")
    rig = people_rig()
    rig.seed_quote_case(case)
    rig.quote_request(case)
    rig.as_user(PRIYA)
    rig.plate()
    rig.as_user(OWNER)
    rig.post("/v1/meetings/mt_q4_plan/confirm")
    rig.post("/v1/people", _NEW_PERSON)
    assert rig.router_calls == [] and rig.flag_calls == []
