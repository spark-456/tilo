"""RESULT-LIVE (live 15 Oct, w_7C0N...): a finished deployed run delivered two items in Tilo and `GET /result` was a
404. Deployed, the shared artifact store screens through a safety provider built with no request, so no SEC-16 meter,
which is replay: a miss, every run output `unscreened` (AR-07), so nothing ever opened. A live, metered run now
screens what it stores with its own metered safety provider. The result route serves the main delivered item (the
delivering agent's own, else the largest) and, by `?artifact=`, each other delivered item, under the same checks."""

from __future__ import annotations

from typing import Any

import pytest
from _clint2_lib import OTHER_USER, wait_for
from test_FR_CON_10_in_app_delivery_run import start
from tilo_api import deps, runs
from tilo_providers.replay import ReplayMissError

METER = object()  # the run's SEC-16 meter, as `deps.meter_for` hands it to the run seams


class _DeployedScreener:
    """What the shared store's screener is on Cloud Run: replay with no recording, so no verdict."""

    def check(self, *args: Any, **kwargs: Any) -> Any:
        raise ReplayMissError("no safety recording")


class _MeteredSafety:
    calls = 0

    def check(self, *args: Any, **kwargs: Any) -> dict[str, Any]:
        type(self).calls += 1
        return {"flagged": False, "reason": None}


def _live_metered(run_flow, monkeypatch) -> None:
    """The run is a judge's live run with a meter; the shared store screens as it does deployed."""
    run_flow.rig.store._screener = _DeployedScreener()
    run_flow.app.dependency_overrides[deps.get_work_mode] = lambda: "live"
    monkeypatch.setattr(deps, "meter_for", lambda *args, **kwargs: METER)

    def get_safety(mode: Any = None, request: Any = None, switches: Any = None, *, meter: Any = None) -> Any:
        assert (mode, meter) == ("live", METER), "outputs are screened by the run's own metered provider"
        return _MeteredSafety()

    monkeypatch.setattr(deps, "get_safety", get_safety)


def _finish(run_flow, **runner_options) -> list[dict[str, Any]]:
    start(run_flow, **runner_options)
    wait_for(lambda: run_flow.events("world.completed"), what="world.completed")
    return run_flow.events("artifact.delivered")


def _result(run_flow, artifact: str | None = None):
    query = {} if artifact is None else {"artifact": artifact}
    return run_flow.flow.client.get(f"/worlds/{run_flow.world_id}/result", params=query)


def _bytes_of(run_flow, unit_id: str) -> bytes:
    return run_flow.rig.store.read(run_flow.scope(), run_flow.artifact_of(unit_id))


def test_RESULT_LIVE_a_live_run_screens_its_outputs_with_its_own_meter_so_its_result_opens(run_flow, monkeypatch):
    _live_metered(run_flow, monkeypatch)

    delivered = _finish(run_flow, deliver_makes=True)

    assert [e["data"]["format"] for e in delivered] == ["in_app", "in_app"]
    for event in run_flow.events("artifact.created"):
        assert run_flow.rig.store.head(run_flow.scope(), event["data"]["artifact"]).record["screening"] == "clean"
    assert _MeteredSafety.calls >= 4, "each stored output got a metered verdict"
    response = _result(run_flow)
    assert response.status_code == 200, response.text
    assert response.content == _bytes_of(run_flow, "U4"), "the deliver unit's own item is the main deliverable"


def test_RESULT_LIVE_without_the_runs_meter_the_output_stays_unscreened_and_never_opens(run_flow):
    run_flow.rig.store._screener = _DeployedScreener()  # replay mode: nothing live may screen it

    _finish(run_flow, deliver_makes=True)

    made = run_flow.events("artifact.created")
    assert {run_flow.rig.store.head(run_flow.scope(), e["data"]["artifact"]).record["screening"] for e in made} == {
        "unscreened"
    }
    assert _result(run_flow).status_code == 404, "an unscreened item is never served (AR-07)"


def test_RESULT_LIVE_the_store_is_unchanged_for_a_replay_or_unmetered_run():
    store = object()
    assert runs.screened_by_run(store, "replay", METER) is store
    assert runs.screened_by_run(store, "live", None) is store


def test_RESULT_LIVE_main_is_the_delivering_agents_own_item_and_each_other_delivered_item_opens(run_flow):
    delivered = _finish(run_flow, deliver_makes=True)
    own, leaf = run_flow.artifact_of("U4"), run_flow.artifact_of("U3")
    assert [e["data"]["artifact"] for e in delivered] == [own, leaf], "the leaf is delivered last"

    assert _result(run_flow).content == _bytes_of(run_flow, "U4")
    other = _result(run_flow, leaf["artifact_id"])
    assert other.status_code == 200 and other.content == _bytes_of(run_flow, "U3")
    assert other.headers["cache-control"] == "no-store" and other.headers["x-content-type-options"] == "nosniff"


def test_RESULT_LIVE_with_no_item_of_its_own_the_largest_delivered_item_is_main(run_flow):
    def branching(approach_id: str, budget_cap: float) -> dict[str, Any]:
        from test_FR_CON_10_in_app_delivery_run import report_plan

        plan = report_plan(approach_id, budget_cap)
        plan["units"][1]["title"] = "Research the long list of options in depth"  # U2 writes the longest item
        plan["units"][2]["depends_on"] = ["U1"]
        plan["units"][3]["depends_on"] = ["U3", "U2", "U1"]  # delivered in this order: the longest is neither end
        return plan

    start(run_flow, plan=branching)
    wait_for(lambda: run_flow.events("world.completed"), what="world.completed")

    delivered = [e["data"]["artifact"] for e in run_flow.events("artifact.delivered")]
    assert delivered == [run_flow.artifact_of(u) for u in ("U3", "U2", "U1")]
    assert len(_bytes_of(run_flow, "U2")) > max(len(_bytes_of(run_flow, u)) for u in ("U1", "U3"))
    assert _result(run_flow).content == _bytes_of(run_flow, "U2")


@pytest.mark.parametrize("which", ["undelivered", "unknown", "other_user"])
def test_RESULT_LIVE_only_the_owner_reads_only_items_the_world_delivered(run_flow, which):
    _finish(run_flow, deliver_makes=True)
    artifact = run_flow.artifact_of("U3")["artifact_id"]
    if which == "undelivered":
        artifact = run_flow.artifact_of("U1")["artifact_id"]  # created by the run, never delivered
    elif which == "unknown":
        artifact = "art_00000000000000000000000000"
    else:
        run_flow.as_member(OTHER_USER, "owner")

    assert _result(run_flow, artifact).status_code == 404
