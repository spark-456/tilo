"""ACT-2 / FR-MTG-08 / EFF-03: allowance authority cannot be omitted or swallowed."""

import inspect
from pathlib import Path

import pytest
import yaml
from test_FR_MTG_08_owner_followup import followup, run  # noqa: F401
from tilo_api.assistant.metering import InMemorySpendLedger
from tilo_api.meeting_allowance import allowance_router
from tilo_api.owner_minutes_caller import OwnerMinutesCaller
from tilo_api.people_writes import Refusal


def test_ACT_2_owner_allowance_is_required():
    assert inspect.signature(OwnerMinutesCaller).parameters["allowance"].default is inspect.Parameter.empty


def test_ACT_2_missing_ledger_refuses_instead_of_unmetered_context():
    with pytest.raises(Refusal) as caught:
        allowance_router(object(), ledger=None, user="owner", clock=lambda: "2026-10-14T00:00:00Z", cap=2, budget=2)
    assert (caught.value.status_code, caught.value.detail) == (429, "allowance_capped")


def test_ACT_2_followup_consumes_allowance_and_capped_nudges_refuse(followup):  # noqa: F811
    c = followup
    c.allowance = InMemorySpendLedger()
    run(c, None)
    assert len(c.calls) == 1
    assert c.allowance.spent(c.writer.actor, c.writer.now[:10]) == 2
    before = c.line.bench.cards.dump()
    c.allowance_cap = 2
    with pytest.raises(Refusal) as caught:
        run(c, None)
    assert (caught.value.status_code, caught.value.detail) == (429, "allowance_capped")
    assert len(c.calls) == 1 and c.line.bench.cards.dump() == before
    assert c.line.entries() == [] and c.line.api.sent == []


@pytest.mark.parametrize("failure", ["cap", "rate", "replay"])
def test_ACT_2_nudge_provider_cap_is_not_successful_empty_list(followup, monkeypatch, failure):  # noqa: F811
    from tilo_api import deps, spend
    from tilo_api.meeting_analysis_mode import _Calls

    def capped(*args):
        if failure == "rate":
            raise Refusal(429, "rate_limited", headers={"Retry-After": "60"})
        if failure == "replay":
            raise deps.ReplayOnly
        raise spend.SpendCapReached

    monkeypatch.setattr(_Calls, "invoke", capped)
    with pytest.raises(Refusal) as caught:
        run(followup, None)
    expected = {"cap": (429, "allowance_capped"), "rate": (429, "rate_limited"), "replay": (503, "replay_only")}
    assert (caught.value.status_code, caught.value.detail) == expected[failure]
    if failure == "rate":
        assert caught.value.headers == {"Retry-After": "60"}
    assert followup.calls == [] and followup.line.bench.cards.dump() == "{}"


def test_ACT_2_EFF_03_verifier_accepts_bounded_transcript():
    config = yaml.safe_load(Path("config/models.yaml").read_text(encoding="utf-8"))
    assert config["roles"]["verifier"]["max_input_tokens"] == 100000
