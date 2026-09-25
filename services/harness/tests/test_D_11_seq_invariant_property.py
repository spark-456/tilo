"""D-11 property tests (root CLAUDE.md ticket loop: "Property tests (Hypothesis...) for
invariants: ... seq strictly increasing"). Two invariants, over randomly sized runs rather than
one fixed example each:

1. `WorldWriter.emit` always assigns `seq` 1..n, strictly increasing, for any n back-to-back
   emits on a fresh world.
2. `WorldWriter.append` accepts a seq only when it is exactly `last_seq + 1`; every other
   integer seq (a gap, a duplicate, or a seq below the last one) is rejected (EV-10), whatever
   the run's length so far.
"""

from __future__ import annotations

import pytest
from conftest import agent_idle_kwargs, make_memory_writer, sequential_ulid, world_requested_kwargs
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st


@settings(max_examples=25, deadline=None, suppress_health_check=[HealthCheck.function_scoped_fixture])
@given(n=st.integers(min_value=1, max_value=20))
def test_D_11_emit_seq_is_always_1_to_n_strictly_increasing(village_basic_layout, n: int) -> None:
    writer, store = make_memory_writer(village_basic_layout)

    seqs = [writer.emit(**agent_idle_kwargs("A_v1", "B3", level="L1", district="D1"))["seq"] for _ in range(n)]

    assert seqs == list(range(1, n + 1)), f"D-11: seq must be strictly increasing from 1, got {seqs}"
    stored_seqs = [e["seq"] for e in store.read_events("org_demo", "w_village_basic")]
    assert stored_seqs == seqs


def _built(seq: int) -> dict:
    return {
        "v": "1.0",
        "id": sequential_ulid(seq),
        "seq": seq,
        "ts": "2026-09-29T09:30:00.000Z",
        "world_id": "w_village_basic",
        "run_id": "r_test_1",
        "level": None,
        "district": None,
        "item": None,
        "severity": "info",
        "credits": 0,
        "cause": None,
        "vis": "all",
        "authz": None,
        "trace": {
            "model_role": None,
            "profile": None,
            "tokens_in": None,
            "tokens_out": None,
            "tool": None,
            "latency_ms": None,
            "archive_ref": None,
        },
        **world_requested_kwargs(),
    }


@settings(max_examples=30, deadline=None, suppress_health_check=[HealthCheck.function_scoped_fixture])
@given(
    k=st.integers(min_value=1, max_value=10),
    bad_offset=st.integers(min_value=-4, max_value=4).filter(lambda o: o != 1),
)
def test_D_11_append_rejects_every_seq_except_last_plus_one(village_basic_layout, k: int, bad_offset: int) -> None:
    from tilo_harness.writer import EventRejected

    writer, store = make_memory_writer(village_basic_layout)
    for seq in range(1, k + 1):
        writer.append(_built(seq))

    bad_seq = k + bad_offset
    if bad_seq < 0:
        return  # seq has schema minimum 0 (event.schema.json); not a seq-ordering case
    with pytest.raises(EventRejected) as excinfo:
        writer.append(_built(bad_seq))
    assert any(p.startswith("EV-10") for p in excinfo.value.problems), excinfo.value.problems
    assert [e["seq"] for e in store.read_events("org_demo", "w_village_basic")] == list(range(1, k + 1)), (
        "D-11: a rejected append must not disturb the already-written prefix"
    )
