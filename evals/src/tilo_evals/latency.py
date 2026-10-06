"""NFR-02, NFR-03, NFR-05 (PRD 17.1): Tilo's own latency overhead, measured in process on fakes.

Drives the real tilo-api app (dev wiring, dev models file: a deterministic fake Director, in-memory store) through
its real routes and times three seams with `time.perf_counter()`:

- NFR-02: `POST /intake` (text and 3 files) until its 201 response, whose `brief` holds the chips.
- NFR-03: that intake, `POST /tasks/{id}/answers` (every question skipped), `GET /tasks/{id}/approaches` until the
  approaches come back.
- NFR-05: an event appended through the dev event writer until a `GET /worlds/{id}/events` response holds it. This
  stops at client receipt; the render half is not measured (see BQ-NFR05-1).

Honesty (EFF-01): no network, no paid call, never LIVE. Every entry says `scope: local_overhead_fake_providers` and
`live: None`. A sample whose seam does not answer raises `LatencyError`; it is never timed as a success.
"""

from __future__ import annotations

import math
import os
import time
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from typing import Any

SCOPE = "local_overhead_fake_providers"
REFUSED_ENV = ("LIVE", "K_SERVICE", "CLOUD_RUN_JOB")
BUDGETS: dict[str, dict[str, int]] = {  # PRD 17.1, milliseconds
    "NFR-02": {"p50_ms": 4000},
    "NFR-03": {"p50_ms": 12000, "p95_ms": 25000},
    "NFR-05": {"p95_ms": 1000},
}
NFR05_NOTE = (
    "Stops at client receipt: the server half of emitted to rendered; the render half is not measured. "
    "As built, the web client polls events every 1000 ms, so the 1 s p95 render budget cannot be met (BQ-NFR05-1)."
)
_FILES = [(f"suppliers{i}.csv", b"supplier,late_days\r\nAcme,2\r\nBeta,0\r\n") for i in range(3)]


class LatencyRefused(RuntimeError):
    """The environment is live or deployed: the harness never runs there (EFF-01)."""


class LatencyError(RuntimeError):
    """A seam did not answer, so the sample is not a measurement."""


def percentiles(samples: Sequence[float]) -> dict[str, Any]:
    """Nearest rank (rank = ceil(p/100 * n), 1-based): always a measured value, never interpolated."""
    if not samples:
        raise ValueError("no samples: a percentile of nothing is not 0")
    if any(not isinstance(s, int | float) or not math.isfinite(s) or s < 0 for s in samples):
        raise ValueError("every sample must be a finite, non-negative duration")
    ordered = sorted(samples)
    n = len(ordered)
    return {"p50": ordered[math.ceil(0.5 * n) - 1], "p95": ordered[math.ceil(0.95 * n) - 1], "n": n}


@contextmanager
def _dev_env() -> Iterator[None]:
    if any(name in os.environ for name in REFUSED_ENV):
        raise LatencyRefused("the latency harness runs on fakes only: LIVE, K_SERVICE and CLOUD_RUN_JOB must be unset")
    from tilo_api import dev  # noqa: PLC0415 (loads the service; the replay harness does not)

    keep = {k: os.environ.get(k) for k in ("TILO_MODELS_FILE", "TILO_DEV_UNIT_DELAY_S")}
    os.environ["TILO_MODELS_FILE"] = str(dev.DEV_MODELS)
    os.environ["TILO_DEV_UNIT_DELAY_S"] = "0"
    try:
        yield
    finally:
        for key, value in keep.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


def _app() -> Any:
    from fastapi import FastAPI  # noqa: PLC0415
    from tilo_api import dev  # noqa: PLC0415
    from tilo_api.intake import router as intake_router  # noqa: PLC0415
    from tilo_api.redaction import router as redaction_router  # noqa: PLC0415
    from tilo_api.tasks import router as tasks_router  # noqa: PLC0415

    app = FastAPI()
    for router in (intake_router, tasks_router, redaction_router):
        app.include_router(router)
    dev.install(app, {})
    return app


def _need(response: Any, status: int, what: str) -> Any:
    if response.status_code != status:
        raise LatencyError(f"{what}: HTTP {response.status_code}, not {status}; the sample is not timed")
    return response.json()


def _flow(client: Any) -> tuple[float, float]:
    """One intake to approaches run: (ms to the intake response, ms to the approaches)."""
    start = time.perf_counter()
    files = [("files", (name, body, "text/csv")) for name, body in _FILES]
    task = _need(
        client.post("/intake", data={"text": "Prepare the weekly supplier summary."}, files=files), 201, "intake"
    )
    if not task.get("brief"):
        raise LatencyError("intake: no brief came back; the sample is not timed")
    chips = time.perf_counter()
    answers = [{"field": q["field"], "answer": None} for q in task["questions"]]  # skip: keep the guess
    body = {"answers": answers, "brief_edits": {}}
    _need(client.post(f"/tasks/{task['task_id']}/answers", json=body), 200, "answers")
    proposed = _need(client.get(f"/tasks/{task['task_id']}/approaches"), 200, "approaches")
    if not proposed.get("approaches"):
        raise LatencyError("approaches: none came back; the sample is not timed")
    done = time.perf_counter()
    return (chips - start) * 1000, (done - start) * 1000


def _event_flow(client: Any, writer: Any, world_id: str) -> float:
    from tilo_api import deps, events  # noqa: PLC0415

    part = {
        "id": events.new_part_id(), "type": "agent.idle", "actor": "A_latency", "target": "B3",
        "summary": "The Verifier is waiting for work.", "vis": "all",
    }  # fmt: skip
    start = time.perf_counter()
    try:
        writer.append(world_id, part)
    except deps.EventRejected as exc:
        raise LatencyError(f"event append refused: {exc}") from exc
    received = _need(client.get(f"/worlds/{world_id}/events"), 200, "world events")
    stop = time.perf_counter()
    if part["id"] not in {e.get("id") for e in received.get("events", [])}:
        raise LatencyError("the event was not in the events response; the sample is not timed")
    return (stop - start) * 1000


def _entry(nfr: str, samples: list[float], **extra: Any) -> dict[str, Any]:
    result = percentiles(samples)
    return {
        "p50_ms": result["p50"], "p95_ms": result["p95"], "n": result["n"], "budget": BUDGETS[nfr],
        "scope": SCOPE, "live": None, **extra,
    }  # fmt: skip


def measure(n: int) -> dict[str, dict[str, Any]]:
    """`n` samples of each measure; `{"NFR-02": entry, "NFR-03": entry, "NFR-05": entry}`."""
    if any(name in os.environ for name in REFUSED_ENV):
        raise LatencyRefused("the latency harness runs on fakes only: LIVE, K_SERVICE and CLOUD_RUN_JOB must be unset")
    if not isinstance(n, int) or n < 1:
        raise ValueError("n must be a positive integer")
    from fastapi.testclient import TestClient  # noqa: PLC0415
    from tilo_api import deps, dev  # noqa: PLC0415

    with _dev_env():
        app = _app()
        client = TestClient(app, base_url=f"http://localhost:{dev.PORT}", raise_server_exceptions=False)
        writer = app.dependency_overrides[deps.get_event_writer]()
        chips, approaches, delivery = [], [], []
        for _ in range(n):
            first, second = _flow(client)
            chips.append(first)
            approaches.append(second)
        world_id = _need(client.post("/intake", data={"text": "A world to read events from."}), 201, "intake")[
            "world_id"
        ]
        for _ in range(n):
            delivery.append(_event_flow(client, writer, world_id))
    return {
        "NFR-02": _entry("NFR-02", chips),
        "NFR-03": _entry("NFR-03", approaches),
        "NFR-05": _entry("NFR-05", delivery, note=NFR05_NOTE),
    }


def text_lines(report: dict[str, dict[str, Any]]) -> list[str]:
    lines = ["Tilo's own overhead on fake providers, in process: no live or cloud figure is claimed."]
    for nfr, entry in report.items():
        budget = ", ".join(f"{k.removesuffix('_ms')} <= {v} ms" for k, v in entry["budget"].items())
        lines.append(
            f"{nfr}  p50 {entry['p50_ms']:.1f} ms  p95 {entry['p95_ms']:.1f} ms  n={entry['n']}  "
            f"scope {entry['scope']}  budget {budget}"
        )
        if entry.get("note"):
            lines.append(f"    note: {entry['note']}")
    return lines


def markdown_lines(report: dict[str, dict[str, Any]]) -> list[str]:
    """The NFR table of the metrics report: a number and its scope, never a verdict."""
    head = ("ID", "p50", "p95", "n", "Scope", "Budget (PRD 17.1)", "Note")
    lines = [f"| {' | '.join(head)} |", f"| {' | '.join('---' for _ in head)} |"]
    for nfr, entry in report.items():
        budget = ", ".join(f"{k.removesuffix('_ms')} <= {v} ms" for k, v in entry["budget"].items())
        cells = (
            nfr, f"p50 {entry['p50_ms']:.1f} ms", f"p95 {entry['p95_ms']:.1f} ms", str(entry["n"]), entry["scope"],
            budget, entry.get("note", "-"),
        )  # fmt: skip
        lines.append("| " + " | ".join(cells) + " |")
    return lines
