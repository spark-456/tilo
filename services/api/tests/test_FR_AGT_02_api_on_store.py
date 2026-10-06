"""FR-AGT-02 / FR-MEM-06 T4 (ADR-0018 section 5 ticket 4; tests/API_FR_AGT_02_T4.md): tilo-api runs go onto the
artifact store. `run_plan` gets the store, the run's Scope, the RunArchive and the redactor; the stopgap that dropped
a unit's outputs is gone; every item a run announces was stored first and is announced from the store's record
(HR-1, HR-2); the unit's credits ride on its first announced item through `Run.emit`; and a store that cannot be built
means no run starts. All fakes: no model, no network, no paid call.
"""

from __future__ import annotations

import hashlib
import math
from typing import Any

import pytest
from _clint1_lib import seam
from _clint2_lib import (
    CAP,
    FLOW_USER,
    ScriptedRunner,
    assert_stream_valid,
    build_run_flow,
    markdown_for,
    wait_for,
)
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st
from tilo_api import deps, runs
from tilo_harness.executor import UnitOutput


class _MeteredRunner(ScriptedRunner):
    """Every unit returns two Markdown outputs (the first labelled) and the credits `credits[unit_id]` metered."""

    def __init__(self, timeline: list[str], credits: dict[str, float]) -> None:
        super().__init__(timeline)
        self.credits = credits

    async def run(self, unit: Any, context: Any) -> Any:
        base = await super().run(unit, context)
        if not base.success:
            return base
        outputs = (
            UnitOutput("text/markdown", markdown_for(unit), label=f"{unit['id']} notes"),
            UnitOutput("text/markdown", markdown_for(unit) + b"\nAppendix.\n"),
        )
        return runs.MeteredOutcome(
            success=True, summary=base.summary, outputs=outputs, credits=self.credits.get(unit["id"], 0.0)
        )


def test_FR_AGT_02_an_api_run_hands_run_plan_the_store_scope_archive_and_redactor(run_flow, monkeypatch) -> None:
    seen: list[dict[str, Any]] = []
    real = runs.run_plan

    async def spy(*args: Any, **kwargs: Any) -> Any:
        seen.append(kwargs)
        return await real(*args, **kwargs)

    monkeypatch.setattr(runs, "run_plan", spy)
    run_flow.run_to_gate()

    (kw,) = seen
    rig, world_id = run_flow.rig, run_flow.world_id
    assert kw.get("artifacts") is rig.store, "run_plan puts outputs on the store the seam gives"
    assert kw.get("redact") is rig.redactor, "and passes on the shared secret redactor (MF-06)"
    scope = kw.get("scope")
    assert (scope.org_id, scope.world_id, scope.owner) == (deps.ORG_ID, world_id, FLOW_USER), "the run's Scope"
    run = run_flow.store.runs[world_id]
    assert (run.org_id, run.world_id) == (scope.org_id, scope.world_id), "the writer's org and world are the Scope's"
    run_id = run_flow.store.worlds[world_id].run_id
    archive = kw.get("archive")
    assert archive is not None and any(a is archive for _, _, a in rig.opened), "the run's own opened archive"
    assert {(org, run_id_) for org, run_id_, _ in rig.opened} == {(deps.ORG_ID, run_id)}


def test_FR_AGT_02_a_units_markdown_is_stored_then_announced_from_the_stores_record(run_flow, registry) -> None:
    run_flow.run_to_completion()
    stream = assert_stream_valid(run_flow, registry)  # EV-15 and the rest, in order, against the run's layout

    scope, rig = run_flow.scope(), run_flow.rig
    plan_units = {u["id"]: u for u in run_flow.last_plan["units"]}
    created = run_flow.created_by_unit()
    assert sorted(created) == ["U1", "U2", "U3", "U4"] and all(len(v) == 1 for v in created.values())
    for unit_id, (event,) in created.items():
        ref = event["data"]["artifact"]
        stored = rig.store.read(scope, ref)
        assert stored == markdown_for(plan_units[unit_id]), "the bytes the runner returned, as the store holds them"
        record = rig.store.head(scope, ref).record
        assert record["origin"]["kind"] == "unit" and record["origin"]["unit"] == unit_id
        assert (
            record["origin"]["agent"] == event["actor"]
            and record["run_id"] == run_flow.store.worlds[run_flow.world_id].run_id
        )
        assert event["data"] == {  # nothing a runner said: id, hash, type and size all come from the record
            "artifact": ref,
            "content_sha256": hashlib.sha256(stored).hexdigest(),
            "media_type": "text/markdown",
            "size_bytes": len(stored),
        }
        assert ref["version"] == 1 and rig.store.manifest(scope, ref)["content_sha256"] == record["content_sha256"]
    assert len({e[0]["data"]["artifact"]["artifact_id"] for e in created.values()}) == 4
    assert [e["type"] for e in stream if e["type"] == "artifact.versioned"] == []


def test_FR_AGT_02_run_emit_forwards_item_and_credits_the_credits_ride_on_the_units_first_item(
    run_flow, registry
) -> None:
    run_flow.runner = _MeteredRunner(run_flow.timeline, {"U1": 2.5})
    run_flow.run_to_gate()

    first, second = run_flow.created_by_unit()["U1"]
    assert first["credits"] == pytest.approx(2.5), "CL-INT-5d intent kept: the cost rides on the first created item"
    assert second["credits"] == 0
    ref = first["data"]["artifact"]
    assert first["item"] == {"kind": "document", "artifact_id": ref["artifact_id"], "label": "U1 notes"}
    assert second["item"] is None, "an unlabelled output carries no item"
    others = [e for e in run_flow.stream() if e["credits"] and e["id"] != first["id"]]
    assert others == [], "HR-1: the meter is the sum of the events, and only that one event carries credits"
    assert_stream_valid(run_flow, registry)


def test_FR_AGT_02_a_units_credits_never_exceed_what_the_approved_budget_has_left(run_flow) -> None:
    run_flow.runner = _MeteredRunner(run_flow.timeline, {"U1": 1e9, "U2": 5.0})
    run_flow.run_to_gate()

    charged = [e for e in run_flow.stream() if e["credits"]]
    assert [e["type"] for e in charged] == ["artifact.created"] and charged[0]["credits"] == pytest.approx(CAP)
    assert math.fsum(e["credits"] for e in run_flow.stream()) <= CAP, "PRD 14.1: never past the approved cap"


@settings(max_examples=6, deadline=None, derandomize=True, suppress_health_check=list(HealthCheck))
@given(
    credits=st.fixed_dictionaries(
        {u: st.floats(min_value=0, max_value=5e7, allow_nan=False) for u in ("U1", "U2", "U3")}
    )
)
def test_FR_AGT_02_property_credits_are_on_one_item_per_unit_and_the_total_never_passes_the_cap(
    repo_root, credits
) -> None:
    rf = build_run_flow(repo_root, covered=True)
    try:
        rf.runner = _MeteredRunner(rf.timeline, credits)
        rf.run_to_gate()
        stream = rf.stream()
        assert math.fsum(e["credits"] for e in stream) <= CAP + 1e-9
        for events in rf.created_by_unit().values():
            assert [e["credits"] for e in events[1:]] == [0] * (len(events) - 1), "only a unit's first item is charged"
        assert [e["seq"] for e in stream] == list(range(1, len(stream) + 1))
    finally:
        rf.close()


def test_FR_AGT_02_a_secret_in_a_units_text_is_redacted_before_it_is_stored_and_never_reaches_the_stream(
    run_flow,
) -> None:
    from _clint2_lib import FAKE_SECRET  # noqa: PLC0415

    class _Leaky(ScriptedRunner):
        async def run(self, unit: Any, context: Any) -> Any:
            from tilo_harness.executor import UnitOutcome  # noqa: PLC0415

            await super().run(unit, context)
            leak = f"# Notes\n\nThe key is {FAKE_SECRET}.\n".encode()
            return UnitOutcome(success=True, summary="done", outputs=(UnitOutput("text/markdown", leak),))

    run_flow.runner = _Leaky(run_flow.timeline)
    run_flow.run_to_gate()

    ref = run_flow.artifact_of("U1")
    stored = run_flow.rig.store.read(run_flow.scope(), ref)
    assert FAKE_SECRET.encode() not in stored and b"[REDACTED]" in stored, "SEC-01, BQ-258: redacted before put"
    assert FAKE_SECRET not in str(run_flow.stream()) and FAKE_SECRET not in str(run_flow.cards().json())


def test_FR_AGT_02_a_run_whose_store_cannot_be_built_starts_no_run_and_stores_nothing(run_flow) -> None:
    def broken() -> Any:
        raise RuntimeError("the artifact store is not wired")

    run_flow.app.dependency_overrides[seam(deps, "get_artifact_store")] = broken
    run_flow.start()
    assert run_flow.approve().status_code == 200  # the grant is the person's; a run that cannot start never changes it

    run_flow.quiet_stream()
    assert {e["type"] for e in run_flow.after_grant()} <= {"world.failed"}, run_flow.types()
    assert run_flow.runner.ran == [], "no unit started without a store to put its work on"
    assert run_flow.rig.meta.paths("") == [] and run_flow.rig.blobs.keys("") == []
    assert run_flow.outbox_store.all_entries() == [] and run_flow.adapter.sent == []


def test_FR_AGT_02_a_failing_unit_in_an_api_run_leaves_no_item_in_the_world_and_the_run_still_ends(run_flow) -> None:
    run_flow.runner.fail = {"U2"}
    run_flow.start()
    assert run_flow.approve().status_code == 200
    wait_for(lambda: run_flow.events("world.failed"), what="world.failed")
    run_flow.quiet_stream()

    assert sorted(run_flow.created_by_unit()) == ["U1"], "U2 failed, U3 and U4 were skipped: no item for them"
    held = [
        v
        for e in run_flow.events("artifact.created")
        for v in run_flow.rig.store.versions(run_flow.scope(), e["data"]["artifact"]["artifact_id"])
    ]
    assert len(held) == 1, "and the store holds nothing the world did not announce"
    assert run_flow.events("approval.requested") == [] and run_flow.events("world.completed") == []


def test_FR_AGT_02_every_announced_item_has_a_stored_version_in_the_runs_scope(run_flow) -> None:
    run_flow.run_to_completion()
    scope = run_flow.scope()
    announced = [
        e["data"]["artifact"] for e in run_flow.stream() if e["type"] in ("artifact.created", "artifact.delivered")
    ]
    assert announced, "the run announced items"
    for ref in announced:
        assert run_flow.rig.store.head(scope, ref) is not None, "HR-2: nothing is announced that the store lacks"
