"""FR-MTR-10 (Should): "Cost dashboards by task type and model profile". Acceptance (PRD 14.5): "Dashboard shows cost
per task by tier and profile". This is the API half (no UI): two read-only routes that serve
`tilo_metering.costs.cost_report` (packages/metering/tests/test_FR_MTR_10_cost_report.py), built from the Treasury
ledger and the world's recorded events. Routes, shapes and seams are pinned in services/api/tests/API_FR_MTR_10.md.

    GET /worlds/{world_id}/costs   one world's task (its run): the report plus "world_id"
    GET /costs                     every world the signed-in owner owns, as one report

Sources: PRD 14.1, 14.3-14.5, EV-07, FR-MTR-01, FR-MTR-06, 10.1 (roles), PL-01, NFR-24 (reads untouched). Refusals
follow the codebase's pattern (API_ST3b.md, redaction.py): a principal that is not a member of the world gets the same
404 as an unknown world; a member who is not its owner gets 403.

These fail today: neither route exists (404) and `tilo_api.deps.get_ledger` does not exist. No network, no provider.
"""

from __future__ import annotations

import copy
import json
import math
from types import SimpleNamespace

import pytest
from _api_lib import as_principal, make_principal, make_world
from _mtr10_lib import (
    A1,
    A2,
    CREDIT_USD,
    FLASH,
    LITE,
    OTHER,
    OWNER,
    RUN,
    B,
    build_ledger,
    commits,
    model_ids,
    row,
    seed,
    serve_ledger,
)
from tilo_api import app, deps
from tilo_metering import LedgerEntry


def near(a: float, b: float) -> bool:
    return math.isclose(a, b, rel_tol=0, abs_tol=1e-9)


def owner(world: str | None = A1):
    return make_principal(user_id=OWNER, role="owner", world_id=world)


@pytest.fixture()
def ledger(tmp_path):
    return build_ledger(tmp_path).ledger


@pytest.fixture()
def seeded(client, store, ledger):
    seed(store)
    serve_ledger(ledger)
    return store


# --- the world's own report -------------------------------------------------------------------------------------


def test_FR_MTR_10_owner_gets_the_worlds_cost_per_task_by_tier_and_profile(client, seeded):
    as_principal(owner(A1))
    response = client.get(f"/worlds/{A1}/costs")
    assert response.status_code == 200
    body = response.json()
    assert body["world_id"] == A1
    assert body["credit_usd"] == CREDIT_USD
    assert [t["run_id"] for t in body["tasks"]] == [RUN[A1]]
    assert body["tasks"][0]["tier"] == "village" and body["tasks"][0]["completed"] is True
    flash = row(body["by_tier_profile"], tier="village", profile=FLASH)
    lite = row(body["by_tier_profile"], tier="village", profile=LITE)
    assert (flash["tasks"], near(flash["credits"], 160), near(flash["credits_per_task"], 160)) == (1, True, True)
    assert (lite["tasks"], near(lite["credits"], 40), near(lite["usd"], 40 * CREDIT_USD)) == (1, True, True)
    assert len(body["by_tier_profile"]) == 2
    village = row(body["by_tier"], tier="village")
    assert (village["tasks"], near(village["credits"], 200), near(village["credits_per_task"], 200)) == (1, True, True)


def test_FR_MTR_10_FR_MTR_01_sums_equal_the_ledger_at_each_entrys_own_price(client, seeded, ledger):
    """r_a1's two flash-38 calls cost 40 (sheet v1) and 120 (sheet v2) credits; the route reports exactly the
    ledger's 160, not 240 (both at v2) and not 80 (both at v1). Runs of other worlds do not enter."""
    as_principal(owner(A1))
    body = client.get(f"/worlds/{A1}/costs").json()
    mine = commits(ledger, RUN[A1])
    assert body["totals"]["credits"] == math.fsum(e.credits for e in mine)  # exact
    assert near(body["totals"]["credits"], 200)
    assert near(body["totals"]["usd"], 200 * CREDIT_USD)
    flash = row(body["by_profile"], profile=FLASH)
    assert flash["credits"] == math.fsum(e.credits for e in mine if e.usage.profile == FLASH)
    assert near(flash["credits"], 160)
    assert near(row(body["by_profile"], profile=LITE)["credits"], 40)
    assert {e.price_effective_date for e in mine if e.usage.profile == FLASH} == {"2026-01-01", "2026-06-01"}
    assert RUN[A2] not in response_text(body) and RUN[B] not in response_text(body)


def response_text(body) -> str:
    return json.dumps(body)


def test_FR_MTR_10_cost_by_task_type_reads_the_unit_types_of_the_runs_plan(client, seeded):
    as_principal(owner(A1))
    body = client.get(f"/worlds/{A1}/costs").json()
    assert len(body["by_task_type"]) == 2
    assert near(row(body["by_task_type"], task_type="research")["credits"], 80)  # U1 40 + U3 40
    assert near(row(body["by_task_type"], task_type="draft")["credits"], 120)  # U2


def test_FR_MTR_10_a_run_without_a_plan_is_reported_with_task_type_null_not_refused(client, store, ledger):
    seed(store, with_plans=False)
    serve_ledger(ledger)
    store.runs[A2] = SimpleNamespace(plan="not a plan")  # malformed: also no task types, still no error
    as_principal(owner(A1))
    body = client.get(f"/worlds/{A1}/costs").json()
    assert [(r["task_type"], near(r["credits"], 200)) for r in body["by_task_type"]] == [(None, True)]
    assert near(body["totals"]["credits"], 200)
    as_principal(owner(A2))
    assert client.get(f"/worlds/{A2}/costs").status_code == 200


def test_FR_MTR_10_FR_MTR_06_memory_hits_count_saved_credits_once_and_do_not_change_spend(client, seeded):
    """A1 holds one accepted reuse (origin 6, lookup 0.5) delivered twice: saved 5.5, once; spend stays 200."""
    as_principal(owner(A1))
    body = client.get(f"/worlds/{A1}/costs").json()
    assert near(body["totals"]["credits_saved"], 5.5)
    assert near(body["totals"]["usd_saved"], 5.5 * CREDIT_USD)
    assert near(body["tasks"][0]["credits_saved"], 5.5)
    assert near(row(body["by_tier"], tier="village")["credits_saved"], 5.5)
    assert near(body["totals"]["credits"], 200)  # not 194.5 and not 205.5
    seeded.events[A1] = [e for e in seeded.events[A1] if e["type"] != "memory.hit"]
    without = client.get(f"/worlds/{A1}/costs").json()
    assert without["totals"]["credits_saved"] == 0 and near(without["totals"]["credits"], 200)


def test_FR_MTR_10_a_world_with_nothing_recorded_gets_zeros_not_an_error(client, store):
    store.worlds[A1] = make_world(owner=OWNER, run_id=RUN[A1])
    serve_ledger([])
    as_principal(owner(A1))
    response = client.get(f"/worlds/{A1}/costs")
    assert response.status_code == 200
    body = response.json()
    assert body["world_id"] == A1
    assert body["totals"]["credits"] == 0 and body["totals"]["usd"] == 0 and body["totals"]["credits_saved"] == 0
    assert body["by_profile"] == [] and body["by_task_type"] == [] and body["by_tier_profile"] == []


# --- the owner's dashboard --------------------------------------------------------------------------------------


def test_FR_MTR_10_the_dashboard_sums_the_signed_in_owners_worlds_and_no_one_elses(client, seeded, ledger):
    as_principal(make_principal(user_id=OWNER, role="owner", world_id=None))
    response = client.get("/costs")
    assert response.status_code == 200
    body = response.json()
    mine = commits(ledger, RUN[A1]) + commits(ledger, RUN[A2])
    assert body["totals"]["credits"] == math.fsum(e.credits for e in mine)
    assert near(body["totals"]["credits"], 242)
    assert [t["run_id"] for t in body["tasks"]] == [RUN[A1], RUN[A2]]
    assert (body["totals"]["tasks"], body["totals"]["completed_tasks"]) == (2, 2)
    assert near(row(body["by_tier"], tier="village")["credits"], 200)
    outpost = row(body["by_tier"], tier="outpost")
    assert (outpost["tasks"], near(outpost["credits"], 42), near(outpost["credits_per_task"], 42)) == (1, True, True)
    assert near(row(body["by_profile"], profile=LITE)["credits"], 80)
    assert near(row(body["by_profile"], profile=None)["credits"], 2)  # the plain commit has no usage
    assert near(row(body["by_task_type"], task_type="research")["credits"], 120)
    assert near(row(body["by_task_type"], task_type=None)["credits"], 2)  # U9 is not in A2's plan
    assert near(body["totals"]["credits_saved"], 5.5)  # the other owner's hit (saves 9) is not here
    text = response.text
    for foreign in (B, RUN[B], OTHER):
        assert foreign not in text, foreign


def test_FR_MTR_10_each_owner_sees_only_their_own_worlds(client, seeded):
    as_principal(make_principal(user_id=OTHER, role="owner", world_id=None))
    body = client.get("/costs").json()
    assert [t["run_id"] for t in body["tasks"]] == [RUN[B]]
    assert near(body["totals"]["credits"], 120) and near(body["totals"]["credits_saved"], 9)
    as_principal(make_principal(user_id=OWNER, role="owner", world_id=B))  # claims the other owner's world
    assert near(client.get("/costs").json()["totals"]["credits"], 242)


def test_FR_MTR_10_an_owner_with_no_worlds_gets_zeros(client, store):
    serve_ledger([])
    as_principal(make_principal(user_id="u_brand_new", role="owner", world_id=None))
    response = client.get("/costs")
    assert response.status_code == 200
    body = response.json()
    assert body["totals"] == {
        "tasks": 0, "completed_tasks": 0, "credits": 0, "usd": 0, "credits_saved": 0, "usd_saved": 0,
    }  # fmt: skip
    assert body["tasks"] == [] and body["by_tier"] == [] and body["by_profile"] == [] and body["by_tier_profile"] == []


# --- who may read it: owners only, no existence leak ------------------------------------------------------------


@pytest.mark.parametrize("role", ["viewer", "approver", "team_lead"])
def test_FR_MTR_10_a_member_who_is_not_the_owner_is_refused_with_no_numbers(client, seeded, role):
    as_principal(make_principal(user_id="u_member", role=role, world_id=A1, districts=("D1",)))
    for path in (f"/worlds/{A1}/costs", "/costs"):
        response = client.get(path)
        assert response.status_code == 403, path
        assert "credits" not in response.text and RUN[A1] not in response.text


def test_FR_MTR_10_another_owners_id_on_this_world_is_refused_too(client, seeded):
    """Role owner, a member of A1, but not A1's owner (A1 belongs to u_owner)."""
    as_principal(make_principal(user_id=OTHER, role="owner", world_id=A1))
    response = client.get(f"/worlds/{A1}/costs")
    assert response.status_code == 403
    assert "credits" not in response.text
    as_principal(make_principal(user_id=OWNER, role="viewer", world_id=A1))  # the owner's id without the owner role
    assert client.get(f"/worlds/{A1}/costs").status_code == 403


def test_FR_MTR_10_a_non_member_gets_the_same_404_as_an_unknown_world(client, seeded):
    as_principal(make_principal(user_id=OTHER, role="owner", world_id=B))  # signed in, a member of another world
    not_member = client.get(f"/worlds/{A1}/costs")
    as_principal(make_principal(user_id=OTHER, role="owner", world_id="w_unknown"))
    unknown = client.get("/worlds/w_unknown/costs")
    assert (not_member.status_code, unknown.status_code) == (404, 404)
    assert not_member.content == unknown.content  # nothing tells the two apart
    as_principal(make_principal(user_id=OTHER, role="owner", world_id=None))
    assert client.get(f"/worlds/{A1}/costs").status_code == 404


def test_FR_MTR_10_signed_out_gets_401_and_a_missing_ledger_gets_503(client, store, ledger):
    seed(store)
    serve_ledger(ledger)
    del app.dependency_overrides[deps.get_current_principal]  # no sign-in wired: the default refuses
    assert client.get(f"/worlds/{A1}/costs").status_code == 401
    assert client.get("/costs").status_code == 401
    as_principal(owner(A1))
    del app.dependency_overrides[deps.get_ledger]  # signed in, but no ledger is wired
    for path in (f"/worlds/{A1}/costs", "/costs"):
        response = client.get(path)
        assert response.status_code == 503, path
        assert response.json()["detail"] == "not_configured"


# --- read-only, deterministic, profiles only --------------------------------------------------------------------


def test_FR_MTR_10_the_routes_are_read_only(client, seeded, ledger, writer):
    as_principal(owner(A1))
    events_before = copy.deepcopy(seeded.events)
    ledger_before = tuple(ledger)
    for path in (f"/worlds/{A1}/costs", "/costs"):
        assert client.get(path).status_code == 200
        for method in ("post", "put", "patch", "delete"):
            assert getattr(client, method)(path).status_code == 405, (method, path)
    assert seeded.events == events_before and tuple(ledger) == ledger_before
    assert writer.calls == [] and seeded.pending_events == {}  # no event was written


def test_FR_MTR_10_the_same_data_in_any_order_gives_byte_identical_responses(client, store, ledger):
    seed(store)
    serve_ledger(list(ledger))
    as_principal(make_principal(user_id=OWNER, role="owner", world_id=A1))
    first_world, first_all = client.get(f"/worlds/{A1}/costs").content, client.get("/costs").content
    assert client.get(f"/worlds/{A1}/costs").content == first_world  # no clock, no counter
    for world in (A1, A2, B):
        store.events[world] = list(reversed(store.events[world]))
    store.worlds = dict(reversed(list(store.worlds.items())))
    serve_ledger(list(reversed(ledger)))
    assert client.get(f"/worlds/{A1}/costs").content == first_world
    assert client.get("/costs").content == first_all


def test_FR_MTR_10_rows_come_in_the_pinned_order(client, seeded):
    as_principal(make_principal(user_id=OWNER, role="owner", world_id=None))
    body = client.get("/costs").json()
    assert [r["tier"] for r in body["by_tier"]] == ["outpost", "village"]  # world size order (PRD 9.1)
    assert [r["profile"] for r in body["by_profile"]] == [FLASH, LITE, None]
    assert [r["task_type"] for r in body["by_task_type"]] == ["draft", "research", None]
    assert [(r["tier"], r["profile"]) for r in body["by_tier_profile"]] == [
        ("outpost", LITE),
        ("outpost", None),
        ("village", FLASH),
        ("village", LITE),
    ]


def test_FR_MTR_10_PL_01_profiles_only_no_model_id_in_the_output(client, seeded, ledger):
    ids = model_ids()
    assert ids, "config/models*.yaml should list model ids; the check below would be vacuous without them"
    hostile = sorted(ids)[0]
    serve_ledger(
        [
            LedgerEntry(**{**e.__dict__, "price_source": f"Fake sheet for {hostile}"}) if e.kind == "commit" else e
            for e in ledger
        ]
    )
    for events in seeded.events.values():
        for e in events:
            e["summary"] = f"{hostile} said hello"
            e["trace"]["model_role"] = "specialist"
    for world, run in seeded.runs.items():
        for unit in run.plan["units"]:
            unit["title"] = f"Ask {hostile}"
    as_principal(make_principal(user_id=OWNER, role="owner", world_id=A1))
    for path in (f"/worlds/{A1}/costs", "/costs"):
        text = client.get(path).text
        for model in ids:
            assert model not in text, f"model id {model!r} leaked into {path}"
        assert f'"{FLASH}"' in text and f'"{LITE}"' in text
