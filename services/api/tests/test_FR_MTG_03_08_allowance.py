"""FR-MTG-03/04/08: offline per-user UTC allowance, before publication or approval cards."""

from types import SimpleNamespace

import pytest
from test_FR_MTG_03_analysis_publication import integration  # noqa: F401
from test_FR_MTG_03_owner_analysis_mode import owner_call  # noqa: F401
from test_FR_MTG_03_owner_minutes_caller import call as minutes_call
from test_FR_MTG_03_owner_minutes_caller import caller_app as minutes_app  # noqa: F401
from test_FR_MTG_08_owner_followup import followup  # noqa: F401
from test_FR_MTG_08_owner_followup_caller import call as followup_call
from test_FR_MTG_08_owner_followup_caller import caller_app as followup_app  # noqa: F401
from tilo_api import deps
from tilo_api.assistant.metering import InMemorySpendLedger
from tilo_api.people_writes import Refusal

DAY, NOW = "2026-10-14", "2026-10-14T23:59:59.000Z"


class Script:
    def __init__(self, left=0, during=None):
        self.left, self.during, self.calls = left, during, []

    def generate(self, role, request, *, budget):
        self.calls.append((role, request, budget))
        if self.during:
            self.during()
        return SimpleNamespace(budget=self.left)


def wrap(inner, ledger=None, *, user="owner", clock=lambda: NOW, cap=2, budget=2):
    from tilo_api.meeting_allowance import AllowanceRouter

    return AllowanceRouter(
        inner, ledger=ledger or InMemorySpendLedger(), user=user, clock=clock, cap=cap, budget=budget
    )


def invoke(router, budget=2):
    return router.generate("analyst", SimpleNamespace(prompt="offline"), budget=budget)


def capped(action):
    with pytest.raises(Refusal) as failure:
        action()
    assert (failure.value.status_code, failure.value.detail) == (429, "allowance_capped")
    assert not failure.value.extra


@pytest.mark.parametrize("bad", [True, False, 0, -1, float("nan"), float("inf"), "2", None])
@pytest.mark.parametrize("field", ["cap", "budget"])
def test_FR_MTG_03_invalid_operation_allowance_before_provider(field, bad):
    inner = Script()
    capped(lambda: invoke(wrap(inner, **{field: bad})))
    assert inner.calls == []


@pytest.mark.parametrize("bad", [True, 0, -1, float("nan"), float("inf"), None])
def test_FR_MTG_04_invalid_request_budget_before_provider(bad):
    inner = Script()
    router = wrap(inner)
    capped(lambda: invoke(router, bad))
    assert inner.calls == []


def test_FR_MTG_04_router_budget_never_increases_and_actual_cost_is_committed():
    ledger, inner = InMemorySpendLedger(), Script(left=0.25)
    router = wrap(inner, ledger)
    invoke(router, 0.75)
    assert ledger.spent("owner", DAY) == 0  # Operation hold remains atomic until close.
    inner.left = 0
    invoke(router, 99)
    assert [call[2] for call in inner.calls] == [0.75, 1.5]
    capped(lambda: invoke(router))
    router.close()
    router.close()
    assert ledger.spent("owner", DAY) == 2


@pytest.mark.parametrize("left", [None, True, -0.1, 3, float("nan"), float("inf"), "1", "missing"])
def test_FR_MTG_04_invalid_provider_budget_charged_conservatively(left):
    ledger, inner = InMemorySpendLedger(), Script(left)
    if left == "missing":
        inner.generate = lambda *args, **kwargs: SimpleNamespace()
    router = wrap(inner, ledger)
    invoke(router)
    capped(lambda: invoke(router))
    router.close()
    assert ledger.spent("owner", DAY) == 2


def test_FR_MTG_03_shared_ledger_accounts_for_interleaved_and_open_holds():
    ledger, second = InMemorySpendLedger(), Script()
    unused = wrap(second, ledger)
    unused.close()
    first = Script(during=lambda: capped(lambda: wrap(second, ledger)))
    router = wrap(first, ledger)
    invoke(router)
    router.close()
    assert second.calls == [] and ledger.spent("owner", DAY) == 2
    capped(lambda: wrap(second, ledger))


def test_FR_MTG_08_utc_date_sampled_per_operation_and_foreign_user_partition():
    ledger, inner, stamps = InMemorySpendLedger(), Script(), []
    current = [NOW]
    router = wrap(inner, ledger, budget=4, clock=lambda: stamps.append(current[0]) or current[0])
    invoke(router)
    router.close()
    current[0] = "2026-10-15T00:00:00.000Z"
    router = wrap(inner, ledger, clock=lambda: stamps.append(current[0]) or current[0])
    invoke(router)
    router.close()
    foreign = wrap(Script(), ledger, user="other")
    invoke(foreign)
    foreign.close()
    assert stamps == [NOW, current[0]]
    assert ledger.spent("owner", DAY) == ledger.spent("owner", "2026-10-15") == 2
    assert ledger.spent("other", DAY) == 2


def test_FR_MTG_04_provider_failure_charges_hold_without_exception_content_leak():
    ledger = InMemorySpendLedger()

    def fail():
        raise RuntimeError("private transcript content")

    inner = Script(during=fail)
    router = wrap(inner, ledger)
    capped(lambda: invoke(router))
    capped(lambda: invoke(router))
    router.close()
    assert ledger.spent("owner", DAY) == 2
    assert len(inner.calls) == 1


def test_FR_MTG_03_reservation_failure_does_not_invoke_provider():
    class Broken(InMemorySpendLedger):
        def reserve(self, *args):
            raise RuntimeError("private ledger content")

    inner = Script()
    capped(lambda: invoke(wrap(inner, Broken())))
    assert inner.calls == []


@pytest.mark.parametrize("fixture_name", ["minutes_app", "followup_app"])
@pytest.mark.parametrize("exhausted", [True, False])
def test_FR_MTG_03_08_caller_daily_cap_before_provider_or_publication(request, fixture_name, exhausted):
    from tilo_api.owner_minutes_caller import get_owner_minutes_budget

    c = request.getfixturevalue(fixture_name)
    ledger = InMemorySpendLedger()
    day = c.writer.now[:10]
    if exhausted:
        hold = ledger.reserve(c.writer.actor, day, 2, 2)
        assert hold is not None
        ledger.commit(hold, 2)
    c.app.dependency_overrides[deps.get_spend_ledger] = lambda: ledger
    c.app.dependency_overrides[deps.get_assistant_config] = lambda: SimpleNamespace(
        user_day_credits=2 if exhausted else 0
    )
    c.app.dependency_overrides[get_owner_minutes_budget] = lambda: 2
    before = c.rig.snapshot()
    response = minutes_call(c) if fixture_name == "minutes_app" else followup_call(c)
    assert response.status_code == 429 and response.json()["detail"] == "allowance_capped"
    assert c.rig.snapshot() == before
    assert not (c.router.calls if fixture_name == "minutes_app" else c.calls)
    if fixture_name == "followup_app":
        assert c.line.bench.cards.dump() == "{}" and c.line.entries() == []
