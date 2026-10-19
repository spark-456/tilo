"""EFF-05 (PRD 6.6 "Batch the non-urgent"; PRD 19.5 "Nightly from 30 Sep: smoke eval (one case per group)"):
"The nightly eval smoke runs through the batch path."

The user decided on 2026-10-06 that the nightly runs on Cloud Scheduler in tilo-dev (not GitHub Actions). This file
pins the entrypoint that the scheduled Cloud Run job (or endpoint) runs; the Terraform half is in
`tests/repo/test_EFF_05_nightly_scheduler_terraform.py`, the provider half in `packages/providers/tests/test_EFF_05_*`.

Entrypoint pinned here (new module `evals/src/tilo_evals/nightly.py`, a new `nightly` subcommand in `__main__.py`):

  python -m tilo_evals nightly [--idempotency-key K] [--results-md P] [--results-json P]
                               [--poll-interval-s S] [--max-wait-s S] [--live]
  main(argv, ..., batch_provider: BatchProvider | None = None)      # the seam the tests use; None = default wiring

What "through the batch path" means (the smoke pass is not a model call, it is replayed recordings, so the batch path
carries the recorded outcome of each case):
  * the cases are the smoke selection of `run_pass` (one ready, runnable case per group), unchanged;
  * ONE `BatchProvider.submit` for the whole smoke, one `BatchRequest` per case (`custom_id` = the case id, the
    request prompt a JSON object with `case_id`), then `poll` until terminal, then `results`;
  * a case's outcome is the response text of its result: a JSON object `{"events": [...], "outputs": {...},
    "credits": n}` validated like `ReplayExecutor` validates a recording (a bad one makes the case not runnable);
  * checks, the smoke credit cap and the counts then run exactly as in `run_pass` (same `PassResult`);
  * default wiring (no `batch_provider`): a replay provider that serves each case's recording in that same format.
    It never builds a model client, whatever the environment says.

Defaults chosen (PRD silent; listed in the ticket report to become BQ rows):
  * Exit codes as `run` (0 ok, 1 a case failed, 2 could not run, 3 stopped at the credit cap) plus: 1 when any
    selected case ended not runnable (a failed batch item or a bad batch answer), because a night where a smoke case
    did not run must not look green; 2 when no smoke case is selected, or the batch does not finish in `--max-wait-s`.
  * The report goes to the git-ignored `evals/nightly.local.md` (never the committed `evals/results.md`, PRD 19.5) and
    the summary is printed, because on Cloud Run the log is the durable record.
  * Idempotency key default: `eval-nightly-smoke-<UTC date>`; polling starts at once and waits `--poll-interval-s`
    (default 30) between polls; `--max-wait-s` default 3600.
  * The EFF-04 per-role cache-hit section is NOT here: its pieces (`trace.tokens_cached` read by the report) do not
    exist yet (ADR-0022 follow-up EFF-04b). When they do, the nightly report must include it.
"""

import json
import pathlib
import socket

import pytest
from _evals_lib import REPO_ROOT, add_case, write_evals_config
from _nightly_lib import build_smoke_repo, model_event, outcome_text, replaying_batch, spy_batch
from tilo_evals.__main__ import main
from tilo_evals.config import EvalsConfig
from tilo_evals.results import render_json
from tilo_evals.runner import run_pass


@pytest.fixture(autouse=True)
def _no_network_and_clean_env(monkeypatch):
    """Nothing in this file may open a socket (EFF-01: no paid calls; the nightly smoke replays)."""

    def no_connect(self, address, *args, **kwargs):
        raise AssertionError(f"EFF-05/EFF-01: the nightly smoke tried to connect to {address!r}")

    monkeypatch.setattr(socket.socket, "connect", no_connect)
    for name in ("LIVE", "TILO_RECORD", "K_SERVICE", "CLOUD_RUN_JOB"):
        monkeypatch.delenv(name, raising=False)


def _json(path="r.json"):
    return json.loads(pathlib.Path(path).read_text(encoding="utf-8"))


# --- it goes through the batch path --------------------------------------------------------------------------------


def test_EFF_05_nightly_smoke_runs_through_the_batch_path(fake_repo):
    expected_ids = build_smoke_repo(fake_repo)
    spy = replaying_batch(fake_repo)

    code = main(["nightly", "--idempotency-key", "k1", "--results-json", "r.json"], batch_provider=spy)

    data = _json()
    assert code == 0
    assert len(spy.submits) == 1, "EFF-05: the whole smoke is one batch job"
    requests, key = spy.submits[0]
    assert key == "k1"
    assert sorted(r.custom_id for r in requests) == expected_ids, "one case per group, E-PLAN-02 is not picked"
    assert all(json.loads(r.request.prompt)["case_id"] == r.custom_id for r in requests)
    job_id = spy.polls[0]
    assert spy.results_calls == [job_id], "results are read once, after the poll loop"
    assert data["path"] == "batch"
    assert data["batch"] == {
        "job_id": job_id,
        "state": "succeeded",
        "total": 3,
        "succeeded": 3,
        "failed": 0,
        "idempotency_key": "k1",
    }
    assert sorted(data["ran"]) == expected_ids and data["failed"] == []


def test_EFF_05_nightly_case_outcomes_come_from_the_batch_response_not_the_recording_file(fake_repo):
    build_smoke_repo(fake_repo)  # the recordings say 4 + 4 + 2 = 10 credits
    spy = spy_batch(respond=lambda item: outcome_text(fake_repo, item.custom_id, credits=50.0))

    main(["nightly", "--idempotency-key", "k1", "--results-json", "r.json"], batch_provider=spy)

    assert _json()["spent"] == 150.0, "EFF-05: the outcome is what the batch returned, not a second read of the file"


def test_EFF_05_nightly_results_equal_the_inline_smoke_pass(fake_repo):
    build_smoke_repo(fake_repo)
    add_case(fake_repo, "E-CHN-01", [model_event(1, 1.0, "narrator")], credits=1.0, outputs={"outbox": [{"id": "x"}]})
    baseline = render_json(run_pass(pass_kind="smoke", config=EvalsConfig.load("config/evals.yaml")))
    spy = replaying_batch(fake_repo)

    code = main(["nightly", "--idempotency-key", "k1", "--results-json", "r.json"], batch_provider=spy)

    data = _json()
    for key in ("ran", "passed", "failed", "spent", "cost_per_case", "cost_per_role", "by_group", "not_run"):
        assert data[key] == baseline[key], f"EFF-05: batch path and inline smoke disagree on {key}"
    assert data["failures_by_cause"] == baseline["failures_by_cause"] and baseline["failed"] == ["E-CHN-01"]
    assert code == 1, "a failed case exits 1, as `run` does"


def test_EFF_05_nightly_respects_the_smoke_credit_cap_like_the_inline_pass(fake_repo):
    build_smoke_repo(fake_repo)  # E-MAIL-01 costs 2, E-PLAN-01 costs 4, E-RES-01 costs 4
    write_evals_config(fake_repo / "config", credit_cap={"full": 2000, "smoke": 5, "gate": 1000})
    spy = replaying_batch(fake_repo)

    code = main(["nightly", "--idempotency-key", "k1", "--results-json", "r.json"], batch_provider=spy)

    data = _json()
    assert code == 3 and data["stopped_at_cap"] is True and data["spent"] == 2.0
    assert data["ran"] == ["E-MAIL-01"] and data["not_run"] == ["E-PLAN-01", "E-RES-01"]


def test_EFF_05_nightly_submits_only_ready_runnable_cases(fake_repo):
    build_smoke_repo(fake_repo)
    add_case(fake_repo, "E-CHN-01", status="skeleton")

    spy = replaying_batch(fake_repo)
    main(["nightly", "--idempotency-key", "k1"], batch_provider=spy)

    assert "E-CHN-01" not in {r.custom_id for r in spy.submits[0][0]}


def test_EFF_05_nightly_with_no_smoke_case_exits_2_and_submits_nothing(fake_repo, capsys):
    spy = replaying_batch(fake_repo)

    code = main(["nightly", "--idempotency-key", "k1"], batch_provider=spy)

    assert code == 2 and spy.submits == [], "an empty night is a broken night, never a quiet pass"
    assert "smoke" in capsys.readouterr().err.lower()


# --- the report ----------------------------------------------------------------------------------------------------


def test_EFF_05_nightly_writes_the_local_report_names_the_batch_job_and_prints_the_summary(fake_repo, capsys):
    build_smoke_repo(fake_repo)
    spy = replaying_batch(fake_repo)

    code = main(["nightly", "--idempotency-key", "k1"], batch_provider=spy)

    job_id = spy.polls[0]
    md = (fake_repo / "evals" / "nightly.local.md").read_text(encoding="utf-8")
    out = capsys.readouterr().out
    assert code == 0
    assert "batch" in md.lower() and job_id in md and "3 of 3" in md, "the report names the batch job and its counts"
    assert "smoke" in md.lower() and "10 credits" in md
    assert job_id in out and "batch" in out.lower(), "the summary is printed: on Cloud Run the log is the record"
    assert not (fake_repo / "evals" / "results.md").exists(), "the committed results.md is never touched (PRD 19.5)"


def test_EFF_05_nightly_report_path_flags_are_honoured(fake_repo):
    build_smoke_repo(fake_repo)

    main(
        ["nightly", "--idempotency-key", "k1", "--results-md", "out/n.md", "--results-json", "out/n.json"],
        batch_provider=replaying_batch(fake_repo),
    )

    assert (fake_repo / "out" / "n.md").is_file() and (fake_repo / "out" / "n.json").is_file()
    assert not (fake_repo / "evals" / "nightly.local.md").exists()


def test_EFF_05_nightly_local_report_is_git_ignored():
    ignore = (REPO_ROOT / ".gitignore").read_text(encoding="utf-8").splitlines()
    assert "evals/nightly.local.md" in [line.strip() for line in ignore], (
        "EFF-05: the default nightly report must be git-ignored like results.local.md, or a dev run dirties the tree"
    )


# --- default wiring: replay, no network, never live ------------------------------------------------------------------


def test_EFF_05_nightly_default_wiring_replays_recordings_through_a_batch_job(fake_repo):
    build_smoke_repo(fake_repo)
    baseline = render_json(run_pass(pass_kind="smoke", config=EvalsConfig.load("config/evals.yaml")))

    code = main(["nightly", "--idempotency-key", "k1", "--results-json", "r.json"])

    data = _json()
    assert code == 0 and data["path"] == "batch"
    assert isinstance(data["batch"]["job_id"], str) and data["batch"]["job_id"]
    assert (data["batch"]["state"], data["batch"]["total"], data["batch"]["failed"]) == ("succeeded", 3, 0)
    assert data["ran"] == baseline["ran"] and data["spent"] == baseline["spent"] == 10.0


def test_EFF_05_nightly_runs_when_deployed_on_a_cloud_run_job(fake_repo, monkeypatch):
    """Unlike `metrics` and `bank`, the nightly is meant to run deployed: it replays, so it is allowed."""
    build_smoke_repo(fake_repo)
    monkeypatch.setenv("CLOUD_RUN_JOB", "tilo-eval-nightly")
    monkeypatch.setenv("K_SERVICE", "tilo-harness")

    assert main(["nightly", "--idempotency-key", "k1", "--results-json", "r.json"]) == 0
    assert _json()["path"] == "batch"


def test_EFF_05_nightly_replays_even_when_the_live_switch_is_set_but_no_live_flag_is_given(fake_repo, monkeypatch):
    build_smoke_repo(fake_repo)
    monkeypatch.setenv("LIVE", "1")  # the user set it for other work; the nightly still replays unless asked live

    code = main(["nightly", "--idempotency-key", "k1", "--results-json", "r.json"])

    assert code == 0 and _json()["spent"] == 10.0  # the autouse fixture fails the test if a socket is opened


def test_EFF_05_nightly_live_flag_is_refused_without_the_live_switch(fake_repo, capsys):
    build_smoke_repo(fake_repo)
    spy = replaying_batch(fake_repo)

    code = main(["nightly", "--live", "--idempotency-key", "k1"], batch_provider=spy)

    assert code == 2 and spy.submits == [], "EFF-01: nothing is submitted when live is refused"
    assert "refused" in capsys.readouterr().err.lower()
