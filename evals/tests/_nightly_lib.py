"""Helpers for the EFF-05 nightly-smoke tests (not a conftest, same reason as `_evals_lib.py`).

`spy_batch` builds a `FakeBatchProvider` that records what the entrypoint asks of it (imported lazily, so each test
fails on its own when `tilo_providers.batch` is missing, rather than one collection error hiding them all).
`outcome_text` turns a case's recording into the response text the batch path carries for it: a JSON object
`{"events": [...], "outputs": {...}, "credits": n}` (the recorded outcome of the case). That text format is part of
what the EFF-05 tests pin, because the default replay wiring and the injected fake must agree on it.
"""

import json
import pathlib
from typing import Any

from _evals_lib import add_case, make_event


def spy_batch(**kwargs: Any) -> Any:
    """A FakeBatchProvider that records every submit, poll and results call (`.submits`, `.polls`, `.results_calls`)."""
    from tilo_providers.batch import FakeBatchProvider  # noqa: PLC0415

    class SpyBatch(FakeBatchProvider):
        def __init__(self, **kw: Any) -> None:
            super().__init__(**kw)
            self.submits: list[tuple[list[Any], str]] = []
            self.polls: list[str] = []
            self.results_calls: list[str] = []

        def submit(self, requests, *, idempotency_key):  # noqa: ANN001
            self.submits.append((list(requests), idempotency_key))
            return super().submit(requests, idempotency_key=idempotency_key)

        def poll(self, job_id):  # noqa: ANN001
            self.polls.append(job_id)
            return super().poll(job_id)

        def results(self, job_id):  # noqa: ANN001
            self.results_calls.append(job_id)
            return super().results(job_id)

    return SpyBatch(**kwargs)


def outcome_text(repo: pathlib.Path, case_id: str, *, credits: float | None = None) -> str:
    """The recorded outcome of `case_id` (read from the fake repo's recording) as the batch response text."""
    events: list[dict[str, Any]] = []
    outputs: dict[str, Any] = {}
    total = 0.0
    for line in (repo / "evals" / "recordings" / f"{case_id}.jsonl").read_text(encoding="utf-8").splitlines():
        record = json.loads(line)
        if "type" in record:
            events.append(record)
            total += float(record.get("credits") or 0.0)
        else:
            outputs, total = record.get("outputs", {}), max(total, float(record.get("credits") or 0.0))
    return json.dumps({"events": events, "outputs": outputs, "credits": total if credits is None else credits})


def replaying_batch(repo: pathlib.Path, **kwargs: Any) -> Any:
    """A spy whose answer for each case is that case's recorded outcome."""
    return spy_batch(respond=lambda item: outcome_text(repo, item.custom_id), **kwargs)


def model_event(seq: int, credits: float, role: str, profile: str = "large") -> dict[str, Any]:
    return make_event(seq, "agent.working", credits=credits, trace={"model_role": role, "profile": profile})


def build_smoke_repo(repo: pathlib.Path) -> list[str]:
    """Three groups, four ready cases; the smoke pass picks the lowest id of each group (3 cases)."""
    add_case(repo, "E-PLAN-01", [model_event(1, 4.0, "director")], credits=4.0)
    add_case(repo, "E-PLAN-02", [model_event(1, 9.0, "director")], credits=9.0)  # not picked: second of its group
    add_case(repo, "E-RES-01", [model_event(1, 3.0, "specialist"), model_event(2, 1.0, "narrator")], credits=4.0)
    add_case(repo, "E-MAIL-01", [model_event(1, 2.0, "specialist")], credits=2.0)
    return ["E-MAIL-01", "E-PLAN-01", "E-RES-01"]
