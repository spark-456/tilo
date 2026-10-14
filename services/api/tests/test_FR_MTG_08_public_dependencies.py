"""Public dependency seams reuse existing owner authority and configured allowance."""

from dataclasses import replace
from types import SimpleNamespace
from typing import Annotated
from unittest.mock import Mock

import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient
from tilo_api import deps
from tilo_api.assistant.config import load_assistant_config
from tilo_api.assistant.metering import InMemorySpendLedger
from tilo_api.owner_followup_caller import (
    OwnerFollowupCaller,
    get_owner_followup_autopilot_factory,
    get_owner_followup_caller,
    get_owner_followup_drafts,
)
from tilo_api.owner_minutes_caller import OwnerMinutesCaller, get_owner_minutes_budget, get_owner_minutes_caller
from tilo_api.people_writes import Refusal


@pytest.fixture
def owner():
    return OwnerMinutesCaller(
        request=SimpleNamespace(state=SimpleNamespace(uid="u_owner")),
        principal=deps.Principal("u_owner", "owner"),
        stores=object(),
        store=object(),
        artifacts=object(),
        clock=lambda: "2026-10-14T00:00:00.000Z",
        redact=lambda text: text,
        switches=object(),
        events=object(),
        budget=3.5,
        allowance=InMemorySpendLedger(),
        allowance_cap=100,
    )


@pytest.mark.parametrize("cap", [0.25, 3, 19.5])
def test_FR_MTG_08_budget_uses_existing_assistant_allowance(cap):
    config = replace(load_assistant_config(), user_day_credits=cap)
    assert get_owner_minutes_budget(config) == cap


@pytest.mark.parametrize("cap", [0, -1, float("nan"), float("inf"), True, "3", None])
def test_FR_MTG_08_invalid_allowance_fails_closed(cap):
    config = replace(load_assistant_config(), user_day_credits=cap)
    with pytest.raises(Refusal) as caught:
        get_owner_minutes_budget(config)
    assert caught.value.status_code == 429 and caught.value.detail == "allowance_capped"


def test_FR_MTG_08_factory_delegates_same_verified_owner(owner, monkeypatch):
    factory = object()
    resolver = Mock(return_value=factory)
    monkeypatch.setattr(deps, "get_followup_autopilot_factory", resolver)
    assert get_owner_followup_autopilot_factory(owner) is factory
    resolver.assert_called_once_with(owner)


def test_FR_MTG_08_fastapi_resolves_existing_config_dependency():
    app = FastAPI()
    config = replace(load_assistant_config(), user_day_credits=7.25)
    configured = Mock(return_value=config)
    app.dependency_overrides[deps.get_assistant_config] = lambda: configured()

    @app.get("/budget")
    def budget(value: Annotated[float, Depends(get_owner_minutes_budget)]):
        return {"budget": value}

    response = TestClient(app).get("/budget")
    assert response.status_code == 200 and response.json() == {"budget": 7.25}
    configured.assert_called_once_with()


def test_FR_MTG_08_fastapi_reuses_one_owner_for_caller_and_factory(owner, monkeypatch):
    app = FastAPI()
    drafts, factory = object(), object()
    verified = Mock(return_value=owner)
    resolved = Mock(return_value=factory)
    app.dependency_overrides[get_owner_minutes_caller] = lambda: verified()
    app.dependency_overrides[get_owner_followup_drafts] = lambda: drafts
    monkeypatch.setattr(deps, "get_followup_autopilot_factory", resolved)

    @app.get("/followup")
    def followup(caller: Annotated[OwnerFollowupCaller, Depends(get_owner_followup_caller)]):
        assert caller.owner is owner and caller.drafts is drafts and caller.autopilot_factory is factory
        return {"scoped": True}

    response = TestClient(app).get("/followup")
    assert response.status_code == 200 and response.json() == {"scoped": True}
    verified.assert_called_once_with()
    resolved.assert_called_once_with(owner)


def resolve_with_spend(owner, spent=1.25, budget=3, stamp="2026-10-14T00:00:00.000Z"):
    ledger = Mock()
    ledger.spent.return_value = spent
    caller = get_owner_minutes_caller(
        request=owner.request,
        principal=owner.principal,
        budget=budget,
        stores=owner.stores,
        store=owner.store,
        artifacts=owner.artifacts,
        clock=lambda: stamp,
        redact=owner.redact,
        switches=owner.switches,
        events=owner.events,
        allowance=ledger,
        config=replace(load_assistant_config(), user_day_credits=3),
    )
    return caller, ledger


@pytest.mark.parametrize("budget,expected", [(3, 1.75), (1, 1)])
def test_FR_MTG_08_operation_budget_clamps_to_remaining_allowance(owner, budget, expected):
    caller, ledger = resolve_with_spend(owner, budget=budget)
    assert caller.budget == expected and caller.allowance_cap == 3
    ledger.spent.assert_called_once_with("u_owner", "2026-10-14")
    ledger.reserve.assert_not_called()


def test_FR_MTG_08_operation_budget_uses_utc_allowance_day(owner):
    caller, ledger = resolve_with_spend(owner, stamp="2026-10-14T00:30:00.000+05:30")
    assert caller.budget == 1.75
    ledger.spent.assert_called_once_with("u_owner", "2026-10-13")


@pytest.mark.parametrize("spent", [3, 4, float("nan"), float("inf"), -1, "1", None, True])
def test_FR_MTG_08_exhausted_or_invalid_committed_spend_refuses(owner, spent):
    with pytest.raises(Refusal) as caught:
        resolve_with_spend(owner, spent=spent)
    assert caught.value.status_code == 429 and caught.value.detail == "allowance_capped"


@pytest.mark.parametrize("stamp", ["bad-time", "2026-10-14T00:00:00", "2026-99-14T00:00:00Z", None])
def test_FR_MTG_08_invalid_server_clock_cannot_choose_allowance_day(owner, stamp):
    with pytest.raises(Refusal) as caught:
        resolve_with_spend(owner, stamp=stamp)
    assert caught.value.status_code == 429 and caught.value.detail == "allowance_capped"
