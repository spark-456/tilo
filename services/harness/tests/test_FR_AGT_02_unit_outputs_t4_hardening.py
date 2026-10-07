"""FR-AGT-02 / FR-MEM-06 (ADR-0018 section 5 ticket 4; the hardening from spark-456/tilo#393 that T4 owns). Built on
the T3 interface pinned in `agt_output_support.py`; the one addition is that a writer names its org: `run_plan`
reads `writer.org_id` and `writer.world_id` (the harness `WorldWriter` gets a public `org_id`, like `world_id`).

- `run_plan` refuses (PlanRefused, nothing written anywhere) a Scope whose org or world is not the writer's. Probe
  from #393: bytes stored in w_elsewhere while the event was announced in w_unit_out.
- A refused or failed attempt must not leave a stored-but-unannounced version that desyncs the store's vN from
  EV-15, so that a later version of the same artifact in that world is announced and EV-15 accepts it. How is the
  builder's choice (check before the first put, or purge on refusal); only the observable result is pinned. The
  refusals here are those that a check before the first put can see: claims (MF-01, MF-06) and a `parent`.
- `existing()` accepts a ref only if the world has it too: stored in this Scope is not enough, it must have been
  announced (`artifact.created` or `artifact.versioned`).
- The bytes the store gets are what the buffer holds: a `bytes` subclass that returns itself from `__bytes__` (so
  `bytes(content)` hands the very same lying object back) cannot slip past the caps.
"""

from __future__ import annotations

import asyncio
import tempfile
from pathlib import Path
from typing import Any

import pytest
from agt_output_support import (
    ARTICLE,
    ORG,
    OWNER,
    RUN,
    SECRET,
    WORLD,
    OutputRunner,
    Ran,
    created_ref,
    make_rig,
    outcome,
    run_units,
    sha,
    unit_output,
)
from agt_support import (
    build_layout,
    build_plan,
    build_unit,
    copy_skills_fixture_tree,
    load_config_sync,
    make_skill_registry,
    write_agents_config,
)
from conftest import make_memory_writer
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

OK_CLAIM = {"id": "cl_1", "location": "slide1/cell:B2", "text": "A plain claim.", "source_ids": [], "verified": False}


class AfterRetired(OutputRunner):
    """Runs `wait_for_unit` only once the previous units' workers have retired, so the order of the units that may
    run side by side is fixed. `after[unit_id]` is the worker whose `agent.retired` that unit waits for."""

    def __init__(self, script: dict[str, Any], events: Any, after: dict[str, str]) -> None:
        super().__init__(script, events)
        self.after = after

    async def run(self, unit: dict[str, Any], context: Any) -> Any:
        waiting_for = self.after.get(unit["id"])
        while waiting_for and not any(
            e["type"] == "agent.retired" and e["target"] == waiting_for for e in self.events()
        ):
            await asyncio.sleep(0.01)
        return await super().run(unit, context)


def run_collect(
    tmp_path: Path,
    script: dict[str, Any],
    *,
    rig: Any = None,
    depends: dict[str, list[str]] | None = None,
    after: dict[str, str] | None = None,
) -> tuple[Ran, BaseException | None]:
    """`run_units` that hands back what `run_plan` raised (and the writer's store) instead of raising it."""
    from tilo_harness.executor import run_plan

    unit_ids = list(script)
    specialists = [f"A_s{i}" for i in range(len(unit_ids))]
    layout = build_layout(
        world_id=WORLD,
        district_specs=[{"id": "D1", "lead": "A_lead", "specialists": specialists, "unit_ids": unit_ids}],
    )
    plan = build_plan([build_unit(uid, depends_on=(depends or {}).get(uid), district="D1") for uid in unit_ids])
    config = load_config_sync(write_agents_config(tmp_path / "agents.yaml"))
    registry = make_skill_registry(copy_skills_fixture_tree(tmp_path / "skills"))
    writer, store = make_memory_writer(layout, world_id=WORLD)
    rig = rig or make_rig()
    runner = AfterRetired(script, lambda: store.read_events(ORG, WORLD), after or {})
    ran = Ran(WORLD, rig, writer, store, None, layout, dict(zip(unit_ids, specialists, strict=True)), runner)
    try:
        ran.result = asyncio.run(
            asyncio.wait_for(
                run_plan(
                    plan,
                    layout,
                    writer=writer,
                    config=config,
                    skills=registry,
                    runner=runner,
                    artifacts=rig.store,
                    scope=rig.scope,
                    redact=rig.redactor,
                ),
                30,
            )
        )
    except Exception as error:  # noqa: BLE001 - the tests assert on exactly what was raised
        return ran, error
    return ran, None


# --- #393 / T4: the Scope must be the writer's -----------------------------------------------------------------


@pytest.mark.parametrize("where", ["another_world", "another_org", "another_world_and_org"])
def test_FR_AGT_02_run_plan_refuses_a_scope_that_is_not_the_writers_world_and_writes_nothing(tmp_path, where) -> None:
    from tilo_harness.executor import PlanRefused
    from tilo_memory.artifacts import Scope

    scope = Scope(
        org_id=ORG if where == "another_world" else "org_rival",
        world_id=WORLD if where == "another_org" else "w_elsewhere",
        owner=OWNER,
    )
    rig = make_rig(world_id=scope.world_id)
    rig.scope = scope
    ran, error = run_collect(tmp_path, {"U1": outcome([unit_output()])}, rig=rig)

    assert isinstance(error, PlanRefused), f"run_plan must refuse the scope up front, got {error!r}"
    assert ran.store.read_events(ORG, WORLD) == [], "refused before the first event: not even the team spawns"
    assert ran.runner.ran == [], "no unit started"
    assert rig.meta.paths("") == [] and rig.blobs.keys("") == [], "nothing was stored in any world"


def test_FR_AGT_02_run_plan_still_runs_when_the_scope_is_the_writers(tmp_path) -> None:
    """Control for the refusal tests: the same wiring with the writer's own org and world works."""
    ran, error = run_collect(tmp_path, {"U1": outcome([unit_output()])})
    assert error is None and ran.result.outcomes["U1"].success is True
    assert len(ran.of("artifact.created")) == 1


# --- #393: a refused attempt leaves nothing stored-but-unannounced -----------------------------------------------


def _bad_second_output(case: str) -> Any:
    leak = {**OK_CLAIM, "text": f"The key is {SECRET}."}
    return {
        "claim_cites_a_source_the_manifest_lacks": unit_output(
            b"# second\n", claims=({**OK_CLAIM, "source_ids": ["src_nope"]},)
        ),
        "secret_in_a_claim_MF_06": unit_output(b"# second\n", claims=(leak,)),
        "parent_the_store_does_not_hold": unit_output(b"# second\n", parent={"artifact_id": "art_nope", "version": 1}),
    }[case]


REFUSALS = ("claim_cites_a_source_the_manifest_lacks", "secret_in_a_claim_MF_06", "parent_the_store_does_not_hold")


@pytest.mark.parametrize("case", REFUSALS)
def test_FR_AGT_02_a_refused_attempt_leaves_no_version_that_desyncs_the_store_from_EV_15(tmp_path, case) -> None:
    """U1 makes artifact X (v1). U2 returns a new version of X plus one output the unit is refused for, so U2 fails and
    announces nothing. U3, afterwards, makes the next version of X: the store must give it v2 (what EV-15 expects),
    not v3 behind a stored-but-unannounced v2, which would end the whole run."""

    def refused(unit: Any, context: Any, events: Any) -> Any:
        new_version = unit_output(b"# v2 that was refused\n", parent=created_ref(events, "A_s0"))
        return outcome([new_version, _bad_second_output(case)])

    def later(unit: Any, context: Any, events: Any) -> Any:
        return outcome([unit_output(b"# v2 that is announced\n", parent=created_ref(events, "A_s0"))])

    ran, error = run_collect(
        tmp_path,
        {"U1": outcome([unit_output(b"# v1\n")]), "U2": refused, "U3": later},
        depends={"U2": ["U1"], "U3": ["U1"]},
        after={"U3": "A_s1"},  # U3 starts once U2 has retired
    )

    assert error is None, f"a later version in this world must not end the run: {error!r}"
    assert ran.result.outcomes["U2"].success is False and ran.artifact_events_of("U2") == []
    assert ran.result.outcomes["U3"].success is True
    x1 = created_ref(ran.events, "A_s0")
    (versioned,) = ran.of("artifact.versioned")
    assert versioned["actor"] == "A_s2"
    assert versioned["data"]["artifact"] == {"artifact_id": x1["artifact_id"], "version": 2}
    assert versioned["data"]["previous_version"] == 1
    held = [v.version for v in ran.rig.store.versions(ran.rig.scope, x1["artifact_id"])]
    assert held == [1, 2], "the store holds exactly what the world announced"
    assert ran.rig.store.read(ran.rig.scope, versioned["data"]["artifact"]) == b"# v2 that is announced\n"
    assert SECRET not in str(ran.events)


@settings(max_examples=12, deadline=None, derandomize=True, suppress_health_check=list(HealthCheck))
@given(attempts=st.lists(st.sampled_from(("ok", *REFUSALS)), min_size=1, max_size=4))
def test_FR_AGT_02_property_the_stores_versions_of_an_artifact_are_exactly_the_announced_ones(attempts) -> None:
    """Whatever mix of good and refused attempts later units make, never an `EventRejected`, and the versions the
    store holds for X are 1..n for the n versions the stream announced (store vN never ahead of EV-15)."""
    n = len(attempts)

    def attempt(kind: str) -> Any:
        def make(unit: Any, context: Any, events: Any) -> Any:
            versions = [e["data"]["artifact"] for e in events if e["type"] == "artifact.versioned"]
            parent = dict(versions[-1]) if versions else created_ref(events, "A_s0")  # the latest announced version
            outputs = [unit_output(f"# {unit['id']}\n".encode(), parent=parent)]
            if kind != "ok":
                outputs.append(_bad_second_output(kind))
            return outcome(outputs)

        return make

    script: dict[str, Any] = {"U1": outcome([unit_output(b"# v1\n")])}
    script |= {f"U{i + 2}": attempt(kind) for i, kind in enumerate(attempts)}
    depends = {f"U{i + 2}": ["U1"] for i in range(n)}
    after = {f"U{i + 3}": f"A_s{i + 1}" for i in range(n - 1)}  # one attempt at a time, in order
    with tempfile.TemporaryDirectory() as tmp:
        ran, error = run_collect(Path(tmp), script, depends=depends, after=after)
        assert error is None, repr(error)
        x1 = created_ref(ran.events, "A_s0")
        announced = 1 + len(ran.of("artifact.versioned"))
        assert announced == 1 + attempts.count("ok")
        held = [v.version for v in ran.rig.store.versions(ran.rig.scope, x1["artifact_id"])]
        assert held == list(range(1, announced + 1))


# --- #393 / T5-T6 pre-work owned by T4: `existing()` also needs the world's own record --------------------------------


def test_FR_AGT_02_a_ref_the_store_holds_in_scope_but_the_world_never_announced_fails_the_unit(tmp_path) -> None:
    from tilo_memory.artifacts import NewVersion, Origin

    rig = make_rig()
    unannounced = rig.store.put(
        rig.scope,
        NewVersion(media_type="text/markdown", content=ARTICLE, run_id=RUN, origin=Origin(kind="upload")),
    )
    ran = run_units(tmp_path, {"U1": outcome((), refs=[unannounced.ref]), "U2": outcome(())}, rig=rig)

    assert ran.result.outcomes["U1"].success is False, "stored in this Scope is not enough: the world must have it"
    assert ran.of("agent.handoff", actor="A_s0") == [] and ran.artifact_events_of("U1") == []
    assert unannounced.ref["artifact_id"] not in str(ran.events), "the stream never names a version it did not announce"
    assert ran.result.outcomes["U2"].success is True


def test_FR_AGT_02_a_ref_to_a_version_announced_as_versioned_is_handed_over(tmp_path) -> None:
    """The world's record counts `artifact.versioned` as well as `artifact.created`."""

    def second(unit: Any, context: Any, events: Any) -> Any:
        return outcome([unit_output(b"# v2\n", parent=created_ref(events, "A_s0"))])

    def third(unit: Any, context: Any, events: Any) -> Any:
        (versioned,) = [e for e in events if e["type"] == "artifact.versioned"]
        return outcome((), refs=[dict(versioned["data"]["artifact"])])

    ran = run_units(
        tmp_path,
        {"U1": outcome([unit_output(b"# v1\n")]), "U2": second, "U3": third},
        depends={"U2": ["U1"], "U3": ["U2"]},
    )

    assert ran.result.outcomes["U3"].success is True
    (versioned,) = ran.of("artifact.versioned")
    handoff = next(e for e in ran.of("agent.handoff") if e["data"]["envelope"]["from"] == "A_s2")
    assert handoff["data"]["envelope"]["artifact_refs"] == [versioned["data"]["artifact"]]


# --- #393: the exact bytes of the buffer ----------------------------------------------------------------------------


class _Liar(bytes):
    """Reports a `len()` of 1, and `bytes(x)` hands the very same object back (`__bytes__` returns self)."""

    def __len__(self) -> int:
        return 1

    def __bytes__(self) -> _Liar:
        return self


class _LiarBig(bytes):
    """Four real bytes that report 3,000,000; `bytes(x)` hands the same object back."""

    def __len__(self) -> int:
        return 3_000_000

    def __bytes__(self) -> _LiarBig:
        return self


def test_FR_AGT_02_a_bytes_subclass_returning_itself_from___bytes___cannot_slip_past_the_cap(tmp_path) -> None:
    real = b"y" * 2_000_001
    ran = run_units(tmp_path, {"U1": outcome([unit_output(_Liar(real))])})
    assert ran.of("artifact.created") == [], "2,000,001 real bytes of Markdown are over the 2 MB cap (BQ-257)"
    assert ran.result.outcomes["U1"].success is False
    assert ran.rig.meta.paths("") == [] and ran.rig.blobs.keys("") == [], "nothing over the cap was stored"


def test_FR_AGT_02_an_overstated_bytes_subclass_with___bytes___stores_only_its_real_bytes_or_nothing(tmp_path) -> None:
    ran = run_units(tmp_path, {"U1": outcome([unit_output(_LiarBig(b"real"))])})
    for event in ran.of("artifact.created"):  # refused outright, or stored as exactly the buffer's bytes
        stored = ran.rig.store.read(ran.rig.scope, event["data"]["artifact"])
        assert stored == b"real" and event["data"]["size_bytes"] == 4
        assert event["data"]["content_sha256"] == sha(b"real")
