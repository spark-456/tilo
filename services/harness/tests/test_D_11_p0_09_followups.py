"""P0-09 follow-ups from the FR-AGT-01/02/03 (P2 harness) ticket brief, item 6:

(a) every problem string `EventValidator` returns is capped at 500 characters with a marked cut,
    so a jsonschema message that repeats a large value stays bounded;
(b) `_json_tree_problems` counts a container's children against the 100,000-value cap before
    pushing them, so a very wide dict is rejected without first stacking every child;
(c) a Firestore transaction aborted by contention (gRPC ABORTED, "Transaction lock timeout")
    surfaces from the writer as `WriterBusy`, never as a raw Google error.

(c) is unit-tested with a fake transaction (monkeypatching `google.cloud.firestore.transactional`
so the decorated function raises `google.api_core.exceptions.Aborted` outright) rather than the
real emulator, per the ticket brief; the emulator-marked repro stays in
test_D_11_emulator_concurrent_writers.py with generous subprocess timeouts.
"""

from __future__ import annotations

import time

import pytest
from conftest import sequential_ulid, world_requested_kwargs
from tilo_harness.validator import EventValidator

PROBLEM_CAP = 500


def _built_event(**field_overrides) -> dict:
    event = {
        "v": "1.0",
        "id": sequential_ulid(1),
        "seq": 1,
        "ts": "2026-09-29T09:30:00.000Z",
        "world_id": "w_followups",
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
    event.update(field_overrides)
    return event


def test_D_11_every_problem_string_is_capped_at_500_characters(repo_root) -> None:
    """world_id set to a 5000-character junk string: jsonschema's default "pattern" message
    echoes the whole instance ('XXXX...' does not match '^w_...'), which would otherwise be
    several thousand characters long."""
    validator = EventValidator.from_repo(repo_root)
    event = _built_event(world_id="X" * 5000)

    problems = validator.problems(event)

    assert problems, "an invalid world_id must still be reported"
    offenders = {p: len(p) for p in problems if len(p) > PROBLEM_CAP}
    assert offenders == {}, f"every problem string must be capped at {PROBLEM_CAP} characters, got lengths {offenders}"


def test_D_11_multiple_oversized_fields_each_stay_capped(repo_root) -> None:
    validator = EventValidator.from_repo(repo_root)
    event = _built_event(world_id="X" * 3000, run_id="Y" * 3000, summary="Z" * 3000)

    problems = validator.problems(event)

    assert len(problems) >= 1
    assert all(len(p) <= PROBLEM_CAP for p in problems), [len(p) for p in problems]


def test_D_11_wide_dict_over_the_100000_value_cap_is_rejected(repo_root) -> None:
    validator = EventValidator.from_repo(repo_root)
    event = _built_event(data={f"k{i}": i for i in range(150_000)})

    problems = validator.problems(event)

    assert any("100000" in p or "100,000" in p for p in problems), problems
    assert all(len(p) <= PROBLEM_CAP for p in problems)


@pytest.mark.slow
def test_D_11_very_wide_dict_is_rejected_quickly_not_after_stacking_every_child(repo_root) -> None:
    """Performance guard for the "before pushing them" fix, calling `_json_tree_problems`
    directly so the timed window is only the traversal, not building the 1,000,000-key fixture
    dict (done outside the timer). The un-fixed code pushes every one of a container's children
    onto the traversal stack before ever checking the 100,000-value cap on pop, so its traversal
    time is proportional to len(dict) (~2.5s-3s for 1,000,000 keys, measured while writing this
    test); a fix that counts each child against the cap before pushing it rejects the container
    almost immediately after the first ~100,001 keys, regardless of how many more remain."""
    from tilo_harness.validator import _json_tree_problems

    huge = {f"k{i}": i for i in range(1_000_000)}

    start = time.monotonic()
    problems = _json_tree_problems({"data": huge})
    elapsed = time.monotonic() - start

    assert any("100000" in p or "100,000" in p for p in problems), problems
    assert elapsed < 1.0, (
        f"D-11: rejecting a 1,000,000-key container took {elapsed:.2f}s -- the cap must be "
        "checked while enumerating each container's children, before pushing them onto the "
        "traversal stack, not only after they are all already stacked"
    )


def test_D_11_aborted_transaction_contention_maps_to_writer_busy(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Unit test (no real emulator): FirestoreStore.transact must translate a gRPC ABORTED /
    "Transaction lock timeout" from the underlying `@firestore.transactional` call into
    `WriterBusy`, never let the raw `google.api_core.exceptions.Aborted` escape."""
    from google.api_core import exceptions as gax_exceptions
    from google.cloud import firestore as gcf

    monkeypatch.setenv("FIRESTORE_EMULATOR_HOST", "127.0.0.1:1")  # unreachable on purpose: never actually dialled

    def _fake_transactional(func):
        def _wrapped(transaction, *args, **kwargs):
            raise gax_exceptions.Aborted("Transaction lock timeout")

        return _wrapped

    monkeypatch.setattr(gcf, "transactional", _fake_transactional)

    from tilo_harness.store import FirestoreStore
    from tilo_harness.writer import WriterBusy

    store = FirestoreStore(project_id="demo-tilo")
    monkeypatch.setattr(store._client, "transaction", lambda: object())

    def _noop(head: dict) -> tuple[dict, None, list]:
        return head, None, []

    with pytest.raises(WriterBusy):
        store.transact("org_demo", "w_aborted_contention", _noop)
