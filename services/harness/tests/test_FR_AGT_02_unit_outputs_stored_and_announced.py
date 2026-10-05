"""FR-AGT-02 / FR-MEM-06 (ADR-0018 section 5 "ticket 3", section 6 honesty HR-1, HR-2): the executor puts each unit
output into the artifact store under the run's Scope after the runner returns and before `agent.handoff`, then emits
one `artifact.created` per stored version whose data comes from the store's record, never from the runner.

Given a unit whose runner returns `UnitOutput`s, When the plan runs with an artifact store,
Then each output is stored under the run's org, world and owner with the key `<run_id>:<unit_id>:<attempt>:<index>`
(AR-05), one `artifact.created` per version follows (actor the worker, cause its `agent.working`, `content_sha256`,
`media_type`, `size_bytes` copied from the stored record), the unit's credits ride on the first only, and the handoff
envelope's `artifact_refs` are the stored refs. See agt_output_support.py for the interface these tests pin.
"""

from __future__ import annotations

import dataclasses
import re

import pytest
from agt_output_support import (
    ARTICLE,
    CSV,
    JSON_DOC,
    RUN,
    SECRET,
    FakeSafety,
    OutputRunner,
    Sized,
    Understated,
    make_rig,
    outcome,
    run_units,
    sha,
    unit_output,
)
from tilo_harness.validator import repo_validator

WORKER = "A_s0"


def _three_outputs():
    return (
        unit_output(ARTICLE, "text/markdown", label="Market brief"),
        unit_output(CSV, "text/csv", label="Prices"),
        unit_output(JSON_DOC, "application/json"),
    )


def test_FR_AGT_02_unit_output_is_a_frozen_dataclass_with_the_adr_fields() -> None:
    from tilo_harness.executor import UnitOutcome, UnitOutput

    names = [f.name for f in dataclasses.fields(UnitOutput)]
    assert names == ["media_type", "content", "label", "parent", "sources", "claims"], names
    out = UnitOutput(media_type="text/markdown", content=b"x")
    assert (out.label, out.parent, tuple(out.sources), tuple(out.claims)) == (None, None, (), ())
    with pytest.raises(dataclasses.FrozenInstanceError):
        out.content = b"y"  # type: ignore[misc]
    assert UnitOutcome(success=True).outputs == (), "outputs defaults to none, so every existing runner still works"


def test_FR_AGT_02_each_output_is_stored_under_the_run_scope_with_the_idempotency_key(tmp_path) -> None:
    ran = run_units(tmp_path, {"U1": outcome(_three_outputs())})
    created = ran.of("artifact.created")
    assert len(created) == 3
    ids = [e["data"]["artifact"]["artifact_id"] for e in created]
    assert len(set(ids)) == 3, "each output is a new artifact id, minted by the store"
    for index, (event, out) in enumerate(zip(created, _three_outputs(), strict=True)):
        ref = event["data"]["artifact"]
        stored = ran.rig.store.head(ran.rig.scope, ref)
        assert stored is not None, "the version is in the store under the run's own org, world and owner"
        record = stored.record
        assert ref == {"artifact_id": record["artifact"]["artifact_id"], "version": 1}, "version 1, no extra keys"
        assert ran.rig.store.read(ran.rig.scope, ref) == out.content
        assert (record["org_id"], record["world_id"], record["owner"]) == ("org_demo", ran.world_id, "u_owner")
        assert record["run_id"] == RUN
        assert record["origin"] == {"kind": "unit", "unit": "U1", "agent": WORKER}
        assert re.fullmatch(rf"{RUN}:U1:\d+:{index}", record["idempotency_key"]), record["idempotency_key"]
        assert (record["media_type"], record["content_sha256"], record["size_bytes"]) == (
            out.media_type,
            sha(out.content),
            len(out.content),
        )


def test_FR_AGT_02_artifact_created_is_written_from_the_stored_record_after_the_work_before_the_handoff(
    tmp_path,
) -> None:
    ran = run_units(tmp_path, {"U1": outcome(_three_outputs())}, skills={"U1": ["web_research"]})
    created, (working,) = ran.of("artifact.created"), ran.of("agent.working")
    (handoff,) = ran.of("agent.handoff")
    assert [e["seq"] for e in created] == sorted(e["seq"] for e in created), "in output order"
    assert working["seq"] < created[0]["seq"] < created[-1]["seq"] < handoff["seq"]
    for event, label in zip(created, ("Market brief", "Prices", None), strict=True):
        ref = event["data"]["artifact"]
        record = ran.rig.store.head(ran.rig.scope, ref).record
        assert event["data"] == {
            "artifact": ref,
            "content_sha256": record["content_sha256"],
            "media_type": record["media_type"],
            "size_bytes": record["size_bytes"],
        }, "the event data is the store record's: a runner can name neither an id nor a hash (ADR-0018 s6)"
        assert event["actor"] == WORKER and event["target"] == ref["artifact_id"]
        assert event["cause"] == working["id"], "caused by the unit's agent.working (ADR-0018 s5)"
        assert event["district"] == "D1" and event["severity"] == "info" and event["authz"] is None
        if label is not None:
            assert event["item"] == {"kind": "document", "artifact_id": ref["artifact_id"], "label": label}
    validator = repo_validator()
    assert {e["seq"]: validator.problems(e) for e in ran.events if validator.problems(e)} == {}


def test_FR_AGT_02_the_envelope_names_the_stored_refs_in_output_order(tmp_path) -> None:
    ran = run_units(tmp_path, {"U1": outcome(_three_outputs())})
    (handoff,) = ran.of("agent.handoff")
    stored = [e["data"]["artifact"] for e in ran.of("artifact.created")]
    assert handoff["data"]["envelope"]["artifact_refs"] == stored
    assert ran.result.outcomes["U1"].success is True


def test_FR_AGT_02_credits_ride_on_the_first_created_item_only(tmp_path) -> None:
    ran = run_units(tmp_path, {"U1": outcome(_three_outputs(), credits=0.75)})
    created = ran.of("artifact.created")
    assert [e["credits"] for e in created] == [0.75, 0, 0], "CL-INT-2 intent kept: credits on the first item only"
    assert sum(e["credits"] for e in ran.events) == pytest.approx(0.75), "and nowhere else (HR-1: the meter)"


def test_FR_AGT_02_a_unit_with_no_outputs_still_hands_over_nothing_to_store(tmp_path) -> None:
    ran = run_units(tmp_path, {"U1": outcome(())})
    assert ran.of("artifact.created") == [] and len(ran.of("agent.handoff")) == 1
    assert ran.result.outcomes["U1"].success is True


def test_FR_AGT_02_the_store_gets_exact_bytes_so_an_overstated_len_is_not_trusted(tmp_path) -> None:
    """The store's caps take `len()` of the object they are given (API_FR_MEM_06.md), so a `bytes` subclass whose
    `len()` lies would be refused (or accepted) on a number that is not the content. The executor puts exactly
    `bytes(content)`."""
    ran = run_units(tmp_path, {"U1": outcome([unit_output(Sized(3_000_000, b"real"))])})
    (event,) = ran.of("artifact.created")
    assert ran.rig.store.read(ran.rig.scope, event["data"]["artifact"]) == b"real"
    assert event["data"]["size_bytes"] == 4


def test_FR_AGT_02_the_store_gets_exact_bytes_so_an_understated_len_cannot_slip_past_the_cap(tmp_path) -> None:
    ran = run_units(tmp_path, {"U1": outcome([unit_output(Understated(b"y" * 2_000_001))])})
    assert ran.of("artifact.created") == [], "2,000,001 real bytes of Markdown are over the 2 MB cap (BQ-257)"
    assert ran.result.outcomes["U1"].success is False
    assert ran.rig.meta.paths("") == [], "nothing was stored"


def test_FR_AGT_02_event_data_reflects_redaction_the_runner_never_sees_the_stored_bytes(tmp_path) -> None:
    content = f"# Notes\n\nThe key is {SECRET}.\n".encode()
    ran = run_units(tmp_path, {"U1": outcome([unit_output(content)])})
    (event,) = ran.of("artifact.created")
    ref = event["data"]["artifact"]
    stored = ran.rig.store.read(ran.rig.scope, ref)
    assert SECRET.encode() not in stored and b"[REDACTED]" in stored, "SEC-01, BQ-258: redacted before put"
    assert ran.rig.store.head(ran.rig.scope, ref).record["redacted"] is True
    assert event["data"]["content_sha256"] == sha(stored) != sha(content), "the hash is of what the store holds"
    assert event["data"]["size_bytes"] == len(stored)
    assert SECRET not in str(ran.events), "no event carries the secret"


@pytest.mark.parametrize(
    ("safety", "expected"),
    [
        (FakeSafety(flagged=False), "clean"),
        (FakeSafety(flagged=True), "flagged"),
        (FakeSafety(error=TimeoutError("down")), "unscreened"),
    ],
    ids=["clean", "flagged", "provider_error"],
)
def test_FR_AGT_02_screening_is_the_safety_provider_verdict_and_never_blocks_the_item(
    tmp_path, safety, expected
) -> None:
    rig = make_rig(safety=safety)
    ran = run_units(tmp_path, {"U1": outcome([unit_output(ARTICLE)])}, rig=rig)
    (event,) = ran.of("artifact.created")
    assert ran.rig.store.head(rig.scope, event["data"]["artifact"]).record["screening"] == expected
    assert safety.calls and safety.calls[0]["text"] == ARTICLE.decode(), "the screener is shown the stored text"
    assert ran.result.outcomes["U1"].success is True, "a verdict is recorded; only 'clean' ever leaves Tilo (AR-07)"


def test_FR_AGT_02_without_an_artifact_store_a_unit_that_returns_outputs_fails_and_writes_no_artifact_event(
    tmp_path,
) -> None:
    ran = run_units(tmp_path, {"U1": outcome([unit_output()]), "U2": outcome(())}, with_store=False)
    assert ran.result.outcomes["U1"].success is False, "there is nowhere to put it: fail closed, never invent an item"
    assert [e["type"] for e in ran.events if e["type"].startswith("artifact.")] == []
    assert ran.of("agent.handoff", actor="A_s0") == [] and ran.result.outcomes["U2"].success is True


def test_FR_AGT_02_outputs_of_several_units_are_each_stored_once_and_announced_once(tmp_path) -> None:
    script = {f"U{i}": outcome([unit_output(ARTICLE + str(i).encode())]) for i in range(1, 4)}
    ran = run_units(tmp_path, script, depends={"U3": ["U1", "U2"]})
    created = ran.of("artifact.created")
    assert sorted(e["actor"] for e in created) == ["A_s0", "A_s1", "A_s2"]
    keys = {ran.rig.store.head(ran.rig.scope, e["data"]["artifact"]).record["idempotency_key"] for e in created}
    assert len(keys) == 3 and {k.split(":")[1] for k in keys} == {"U1", "U2", "U3"}


def test_FR_AGT_02_the_stored_origin_is_the_executors_own_unit_and_worker(tmp_path) -> None:
    """The unit id and agent in the stored origin are the executor's own, whatever a runner returns."""
    runner = OutputRunner({"U1": outcome([unit_output()]), "U2": outcome([unit_output(CSV, "text/csv")])})
    ran = run_units(tmp_path, {"U1": None, "U2": None}, runner=runner)
    for unit, worker in (("U1", "A_s0"), ("U2", "A_s1")):
        (event,) = ran.of("artifact.created", actor=worker)
        origin = ran.rig.store.head(ran.rig.scope, event["data"]["artifact"]).record["origin"]
        assert origin == {"kind": "unit", "unit": unit, "agent": worker}
