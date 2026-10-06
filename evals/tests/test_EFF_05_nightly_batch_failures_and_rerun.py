"""EFF-05: what the nightly smoke does when the batch misbehaves, and when it is run again.

Partial failure, a bad batch answer, a batch that never finishes, and an idempotent re-run (Cloud Scheduler retries a
failed attempt, and the user can re-run a night by hand). Entry point, exit codes and defaults are in the module
docstring of `test_EFF_05_nightly_smoke_batch_path.py`; nothing here opens a socket.
"""

import json
import pathlib
import re
import socket

import pytest
from _nightly_lib import build_smoke_repo, outcome_text, replaying_batch, spy_batch
from tilo_evals.__main__ import main


@pytest.fixture(autouse=True)
def _no_network_and_clean_env(monkeypatch):
    def no_connect(self, address, *args, **kwargs):
        raise AssertionError(f"EFF-05/EFF-01: the nightly smoke tried to connect to {address!r}")

    monkeypatch.setattr(socket.socket, "connect", no_connect)
    for name in ("LIVE", "TILO_RECORD", "K_SERVICE", "CLOUD_RUN_JOB"):
        monkeypatch.delenv(name, raising=False)


def _json(path="r.json"):
    return json.loads(pathlib.Path(path).read_text(encoding="utf-8"))


def _run(args, provider):
    return main(["nightly", "--poll-interval-s", "0", "--results-json", "r.json", *args], batch_provider=provider)


# --- partial and total batch failure ---------------------------------------------------------------------------------


def test_EFF_05_nightly_partial_batch_failure_is_reported_per_case_and_fails_the_job(fake_repo):
    build_smoke_repo(fake_repo)
    spy = replaying_batch(fake_repo, fail={"E-RES-01"})

    code = _run(["--idempotency-key", "k1"], spy)

    data = _json()
    assert code == 1, "a night where a smoke case did not run is not green"
    assert (data["batch"]["state"], data["batch"]["succeeded"], data["batch"]["failed"]) == ("partial", 2, 1)
    assert data["ran"] == ["E-MAIL-01", "E-PLAN-01"], "the cases whose items succeeded are still evaluated"
    assert data["not_runnable"] == ["E-RES-01"]
    assert "batch" in data["not_runnable_reasons"]["E-RES-01"].lower()
    md = (fake_repo / "evals" / "nightly.local.md").read_text(encoding="utf-8")
    assert "E-RES-01" in md and "partial" in md.lower()


def test_EFF_05_nightly_whole_batch_failure_exits_1_and_runs_no_case(fake_repo):
    build_smoke_repo(fake_repo)
    spy = replaying_batch(fake_repo, fail={"E-MAIL-01", "E-PLAN-01", "E-RES-01"})

    code = _run(["--idempotency-key", "k1"], spy)

    data = _json()
    assert code == 1 and data["batch"]["state"] == "failed" and data["ran"] == []
    assert data["not_runnable"] == ["E-MAIL-01", "E-PLAN-01", "E-RES-01"]


_BAD_ANSWERS = [
    pytest.param("not json at all", id="not-json"),
    pytest.param(json.dumps(["a", "list"]), id="not-an-object"),
    pytest.param(json.dumps({"events": "no", "outputs": {}, "credits": 1}), id="events-not-a-list"),
    pytest.param(json.dumps({"events": [], "outputs": [], "credits": 1}), id="outputs-not-an-object"),
    pytest.param(json.dumps({"events": [], "outputs": {}, "credits": -1}), id="negative-credits"),
    pytest.param(json.dumps({"events": [], "outputs": {}, "credits": "9"}), id="credits-a-string"),
    pytest.param(json.dumps({"events": [], "outputs": {}, "credits": True}), id="credits-a-bool"),
    pytest.param('{"events": [], "outputs": {}, "credits": NaN}', id="credits-nan"),
]


@pytest.mark.parametrize("bad", _BAD_ANSWERS)
def test_EFF_05_nightly_bad_batch_answer_makes_that_case_not_runnable_and_never_crashes(fake_repo, bad):
    build_smoke_repo(fake_repo)
    spy = spy_batch(
        respond=lambda item: bad if item.custom_id == "E-PLAN-01" else outcome_text(fake_repo, item.custom_id)
    )

    code = _run(["--idempotency-key", "k1"], spy)

    data = _json()
    assert data["not_runnable"] == ["E-PLAN-01"] and data["ran"] == ["E-MAIL-01", "E-RES-01"]
    assert code == 1
    assert "\n" not in data["not_runnable_reasons"]["E-PLAN-01"], (
        "a reason is one bounded line (results.md splits lines)"
    )


def test_EFF_05_nightly_a_batch_that_never_finishes_exits_2_within_max_wait(fake_repo, capsys):
    build_smoke_repo(fake_repo)
    spy = replaying_batch(fake_repo, polls_until_done=1_000_000)

    code = main(
        ["nightly", "--idempotency-key", "k1", "--poll-interval-s", "0.001", "--max-wait-s", "0.05"],
        batch_provider=spy,
    )

    assert code == 2
    assert re.search(r"(?i)did not finish|timed out", capsys.readouterr().err)
    assert len(spy.polls) >= 2, "it did poll before giving up"
    assert spy.results_calls == [], "results are never read from an unfinished job"


def test_EFF_05_nightly_polls_until_the_job_is_terminal(fake_repo):
    build_smoke_repo(fake_repo)
    spy = replaying_batch(fake_repo, polls_until_done=3)

    code = _run(["--idempotency-key", "k1"], spy)

    assert code == 0 and len(spy.polls) == 3 and _json()["batch"]["state"] == "succeeded"


# --- idempotent re-run ----------------------------------------------------------------------------------------------


def test_EFF_05_nightly_rerun_with_the_same_key_joins_the_job_and_runs_no_case_twice(fake_repo):
    build_smoke_repo(fake_repo)
    spy = replaying_batch(fake_repo)

    first = _run(["--idempotency-key", "night-1"], spy)
    first_report = _json()
    second = _run(["--idempotency-key", "night-1"], spy)
    second_report = _json()

    assert first == second == 0
    assert sorted(spy.executed) == ["E-MAIL-01", "E-PLAN-01", "E-RES-01"], "each case ran once across both runs"
    assert second_report["batch"]["job_id"] == first_report["batch"]["job_id"]
    for key in ("ran", "passed", "failed", "spent", "cost_per_role"):
        assert second_report[key] == first_report[key], f"EFF-05: the re-run's report differs on {key}"


def test_EFF_05_nightly_a_new_key_is_a_new_job(fake_repo):
    build_smoke_repo(fake_repo)
    spy = replaying_batch(fake_repo)

    _run(["--idempotency-key", "night-1"], spy)
    one = _json()["batch"]["job_id"]
    _run(["--idempotency-key", "night-2"], spy)

    assert _json()["batch"]["job_id"] != one and len(spy.executed) == 6


def test_EFF_05_nightly_default_key_is_stable_within_a_day_and_dated(fake_repo):
    build_smoke_repo(fake_repo)
    spy = replaying_batch(fake_repo)

    _run([], spy)
    _run([], spy)

    keys = [key for _requests, key in spy.submits]
    assert keys[0] == keys[1], "Cloud Scheduler may retry an attempt the same night: the same key, the same job"
    assert re.search(r"\d{4}-\d{2}-\d{2}", keys[0]) and len(spy.executed) == 3
