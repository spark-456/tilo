"""FR-MTR-10 error paths of GET /worlds/{id}/costs and GET /costs (follow-ups of PR #434; API_FR_MTR_10.md):

- 422 `inconsistent_ledger` when `cost_report` refuses a memory.hit that disagrees with its own costs (BQ-MTR10-5),
  and only then: any other ValueError is a bug and must surface;
- 503 `not_configured` when config/prices.yaml is unreadable; prices.yaml is read once, only a good read is kept.
No network, no provider.
"""

from __future__ import annotations

import copy

import pytest
from _api_lib import as_principal, make_principal
from _mtr10_lib import A1, OWNER, build_ledger, seed, serve_ledger
from tilo_api import costs as costs_routes
from tilo_api import deps

PATHS = (f"/worlds/{A1}/costs", "/costs")


def owner():
    return make_principal(user_id=OWNER, role="owner", world_id=A1)


@pytest.fixture()
def seeded(client, store, tmp_path):
    seed(store)
    serve_ledger(build_ledger(tmp_path).ledger)
    as_principal(owner())
    costs_routes.reset_credit_usd_cache()  # the route keeps prices.yaml once read: start and end every test empty
    yield store
    costs_routes.reset_credit_usd_cache()


@pytest.mark.parametrize("path", PATHS)
def test_FR_MTR_10_a_memory_hit_that_disagrees_with_its_costs_is_422_inconsistent_ledger(client, seeded, path):
    bad = copy.deepcopy(next(e for e in seeded.events[A1] if e["type"] == "memory.hit"))
    bad["id"] = f"01JB5VQ{999:019d}"
    bad["data"]["saved"] = bad["data"]["origin_cost"]  # EV-09: saved must be origin_cost - lookup_cost
    seeded.events[A1].append(bad)
    response = client.get(path)
    assert response.status_code == 422
    assert response.json() == {"detail": "inconsistent_ledger"}


@pytest.mark.parametrize("path", PATHS)
def test_FR_MTR_10_any_other_value_error_is_not_turned_into_a_422(client, seeded, monkeypatch, path):
    def boom(*_args, **_kwargs):
        raise ValueError("some other bug")

    monkeypatch.setattr(costs_routes, "cost_report", boom)
    with pytest.raises(ValueError, match="some other bug"):
        client.get(path)


@pytest.mark.parametrize("path", PATHS)
def test_FR_MTR_10_unreadable_prices_file_is_503_not_configured(client, seeded, monkeypatch, tmp_path, path):
    monkeypatch.setattr(deps, "prices_path", lambda: tmp_path / "missing" / "prices.yaml")
    response = client.get(path)
    assert response.status_code == 503
    assert response.json() == {"detail": "not_configured"}


def test_FR_MTR_10_prices_yaml_is_read_once_and_only_a_successful_read_is_kept(client, seeded, monkeypatch, tmp_path):
    real = deps.prices_path()
    reads: list[object] = []
    original = costs_routes.load_credit_usd

    def counting(path):
        reads.append(path)
        return original(path)

    monkeypatch.setattr(costs_routes, "load_credit_usd", counting)
    monkeypatch.setattr(deps, "prices_path", lambda: tmp_path / "missing.yaml")
    assert client.get("/costs").status_code == 503  # a failed read is not kept ...
    assert client.get("/costs").status_code == 503
    assert len(reads) == 2  # ... so it is retried
    monkeypatch.setattr(deps, "prices_path", lambda: real)
    assert client.get("/costs").status_code == 200
    assert client.get(f"/worlds/{A1}/costs").status_code == 200
    assert client.get("/costs").status_code == 200
    assert len(reads) == 3  # the good read happened once
