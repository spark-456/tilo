"""The nightly eval smoke through the batch path (EFF-05; PRD 6.6 "Batch the non-urgent", PRD 19.5).

One `BatchProvider.submit` for the whole smoke selection (one case per group, `run_pass`'s own selection), `poll` until
terminal, `results` once; each case's outcome is its batch answer (`executors.parse_batch_answer`), and the checks,
credit cap and counts then run exactly as in `run_pass`. Default wiring replays each case's recording through an
in-memory batch job: no model client is ever built, deployed or not, and the only flag, `--live`, is a hard
refusal (live nightly is not built yet). The EFF-04 per-role cache-hit section is not here yet (its inputs do not
exist; ADR-0022 follow-up EFF-04b)."""

import argparse
import json
import os
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

from tilo_providers.batch import (
    TERMINAL_STATES,
    BatchProvider,
    BatchRequest,
    InMemoryBatchProvider,
)
from tilo_providers.errors import ProviderError
from tilo_providers.interfaces import GenerateRequest, GenerateResponse

from .cases import Case, CaseError, load_cases
from .config import EvalsConfig, EvalsConfigError
from .executors import BatchExecutor, ReplayExecutor
from .results import build_hash, render_json, render_section, summary_text
from .runner import SelectionError, _select, run_pass

EXIT_OK, EXIT_FAILED, EXIT_ERROR, EXIT_PARTIAL = 0, 1, 2, 3


class _RecordingBatch(InMemoryBatchProvider):
    """Default wiring: the batch answer for a case is its recorded outcome, serialised."""

    def __init__(self, cases: list[Case]) -> None:
        super().__init__()
        self._cases = {c.id: c for c in cases}

    def _run_item(self, item: BatchRequest) -> GenerateResponse:
        outcome = ReplayExecutor().run(self._cases[json.loads(item.request.prompt)["case_id"]])
        text = json.dumps({"events": list(outcome.events), "outputs": outcome.outputs, "credits": outcome.credits})
        return GenerateResponse(text=text, profile_id="replay")


def add_arguments(nightly: argparse.ArgumentParser) -> None:
    nightly.add_argument("--idempotency-key", dest="idempotency_key", default=None)
    nightly.add_argument("--results-md", dest="results_md", default="evals/nightly.local.md")
    nightly.add_argument("--results-json", dest="results_json", default=None)
    nightly.add_argument("--poll-interval-s", dest="poll_interval_s", type=float, default=30.0)
    nightly.add_argument("--max-wait-s", dest="max_wait_s", type=float, default=3600.0)
    nightly.add_argument("--live", action="store_true")


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(text.encode("utf-8"))  # bytes, so Windows never writes CRLF


def run_nightly(args: argparse.Namespace, batch_provider: BatchProvider | None = None) -> int:
    if args.live:
        live = os.environ.get("LIVE") == "1"
        print(
            "tilo_evals: --live is not built yet (it needs a packages/providers executor)."
            if live
            else "tilo_evals: --live refused; the user sets LIVE=1 in the environment first (EFF-01).",
            file=sys.stderr,
        )
        return EXIT_ERROR
    try:
        config = EvalsConfig.load("config/evals.yaml")
        cases = _select(load_cases(root="evals/cases"), "smoke", None, [], config)
        if not cases:
            raise SelectionError("no smoke case is selected (one ready, runnable case per group): nothing to run")
        provider = batch_provider or _RecordingBatch(cases)
        key = args.idempotency_key or f"eval-nightly-smoke-{datetime.now(UTC):%Y-%m-%d}"
        requests = [
            BatchRequest(custom_id=c.id, request=GenerateRequest(prompt=json.dumps({"case_id": c.id}))) for c in cases
        ]
        job = provider.submit(requests, idempotency_key=key)
        start = time.monotonic()
        while (status := provider.poll(job.job_id)).state not in TERMINAL_STATES:
            if time.monotonic() - start >= args.max_wait_s:
                raise SelectionError(
                    f"batch job {job.job_id} did not finish within {args.max_wait_s:g} s; no result read"
                )
            time.sleep(args.poll_interval_s)
        result = run_pass(pass_kind="smoke", config=config, executor=BatchExecutor(provider.results(job.job_id)))
    except (EvalsConfigError, CaseError, SelectionError, ProviderError) as exc:
        print(f"tilo_evals: {exc}", file=sys.stderr)
        return EXIT_ERROR

    batch = {
        "job_id": job.job_id, "state": str(status.state), "total": status.total,
        "succeeded": status.succeeded, "failed": status.failed, "idempotency_key": key,
    }  # fmt: skip
    line = f"batch job {job.job_id}: {status.state}, {status.succeeded} of {status.total} items ok (key {key})"
    now = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    section = render_section(result, build_hash=build_hash(), now_utc=now)
    _write(Path(args.results_md), f"# Nightly smoke (batch path)\n\n{line}\n\n{section}")
    if args.results_json:
        _write(Path(args.results_json), json.dumps({**render_json(result), "path": "batch", "batch": batch}, indent=2))
    print(line)
    print(summary_text(result))
    print(f"results: {Path(args.results_md).as_posix()}")
    if result.failed or result.not_runnable:  # a night where a smoke case did not run must not look green
        return EXIT_FAILED
    return EXIT_PARTIAL if result.stopped_at_cap else EXIT_OK
