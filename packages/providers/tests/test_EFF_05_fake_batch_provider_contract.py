"""EFF-05 (PRD 6.6 "Batch the non-urgent"): the batch path of the provider layer, and its deterministic fake.

PRD 6.6: "Evals, digests, style-profile builds and nightly jobs use batch or deferred processing where the provider
offers it". EFF-05: "Batch path for non-urgent jobs"; acceptance: "The nightly eval smoke runs through the batch path".
The user decided on 2026-10-06 that the nightly smoke runs on Cloud Scheduler in tilo-dev; this file pins the provider
half (no paid call, no network): submit, poll, results, partial failure, idempotent re-run. The replay and live-gate
half is in `test_EFF_05_batch_replay_and_live_gate.py`; the eval entrypoint is in `evals/tests/test_EFF_05_*.py`.

Interface the builder implements (new module `packages/providers/src/tilo_providers/batch.py`; `interfaces.py` may
re-export). This is the test-writer's reading of PRD 6.4 / 6.6; nothing in the PRD or contracts/ names these types, so
a different shape is a deliberate change to these tests, not a workaround:

  BatchRequest(custom_id: str, request: GenerateRequest)       pydantic, extra="forbid"
  BatchState                                                    StrEnum: pending, running, succeeded, partial, failed
  BatchJob(job_id: str, state: BatchState)                      returned by submit
  BatchStatus(job_id, state, total: int, succeeded: int, failed: int)    returned by poll
  BatchResult(custom_id: str, status: "ok" | "error", response: GenerateResponse | None, error: str | None)
  BatchProvider (ABC)
      submit(requests: Sequence[BatchRequest], *, idempotency_key: str) -> BatchJob
      poll(job_id: str) -> BatchStatus
      results(job_id: str) -> list[BatchResult]                 submission order; BatchNotReadyError until terminal
  BatchNotReadyError(ProviderError)
  FakeBatchProvider(profile_id="fake-batch", *, polls_until_done=1, fail=(), respond=None)
      .executed: list[str]    custom ids the fake actually ran, in order (an idempotent re-run adds nothing)
  RecordReplayBatchProvider, build_batch_provider              see the replay file

Defaults chosen where the PRD is silent (listed in the ticket report, to become BQ rows):
  * `polls_until_done=N`: submit returns `pending` and does no work; polls 1..N-1 return `running`; poll N returns
    the terminal state. Work (`executed`) happens when the terminal state is reached.
  * Terminal state: `succeeded` (no item failed), `partial` (some failed), `failed` (every item failed).
  * An item failure is data (`status="error"`, `response=None`, non-empty `error`), never an exception.
  * The fake is refused when the live switch is on or when deployed (K_SERVICE or CLOUD_RUN_JOB present), the same
    rule as `FakeSafetyProvider` (SEC-04): a fake must never stand in for a live or deployed run.
"""

from __future__ import annotations

import socket

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st
from tilo_providers.config import ProviderConfigError
from tilo_providers.errors import ProviderError, RequestError
from tilo_providers.interfaces import GenerateRequest, GenerateResponse

pytestmark = pytest.mark.usefixtures("block_non_local_sockets")

TERMINAL = {"succeeded", "partial", "failed"}


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    for name in ("LIVE", "TILO_RECORD", "K_SERVICE", "CLOUD_RUN_JOB"):
        monkeypatch.delenv(name, raising=False)


def _requests(*ids: str):
    from tilo_providers.batch import BatchRequest  # noqa: PLC0415

    return [BatchRequest(custom_id=i, request=GenerateRequest(prompt=f"prompt for {i}")) for i in ids]


def _drain(provider, job_id: str, *, limit: int = 20):
    """Polls until terminal; returns the list of states seen."""
    seen = []
    for _ in range(limit):
        state = str(provider.poll(job_id).state)
        seen.append(state)
        if state in TERMINAL:
            return seen
    raise AssertionError(f"EFF-05: job {job_id!r} not terminal after {limit} polls: {seen}")


# --- the interface ---------------------------------------------------------------------------------------------


def test_EFF_05_batch_provider_is_an_abstract_interface_with_submit_poll_results():
    from tilo_providers.batch import BatchProvider  # noqa: PLC0415

    with pytest.raises(TypeError):
        BatchProvider()  # type: ignore[abstract]
    for method in ("submit", "poll", "results"):
        assert method in BatchProvider.__abstractmethods__, f"EFF-05: {method} must be abstract on BatchProvider"


def test_EFF_05_fake_batch_provider_implements_the_interface():
    from tilo_providers.batch import BatchProvider, FakeBatchProvider  # noqa: PLC0415

    assert isinstance(FakeBatchProvider(), BatchProvider)


def test_EFF_05_batch_request_rejects_unknown_fields_and_empty_ids():
    from pydantic import ValidationError  # noqa: PLC0415
    from tilo_providers.batch import BatchRequest  # noqa: PLC0415

    with pytest.raises(ValidationError):
        BatchRequest(custom_id="a", request=GenerateRequest(prompt="p"), model="anything")  # type: ignore[call-arg]
    with pytest.raises(ValidationError):
        BatchRequest(custom_id="", request=GenerateRequest(prompt="p"))


# --- submit, poll, results ---------------------------------------------------------------------------------------


def test_EFF_05_submit_does_no_work_and_poll_reaches_a_terminal_state():
    from tilo_providers.batch import FakeBatchProvider  # noqa: PLC0415

    fake = FakeBatchProvider(polls_until_done=3)
    job = fake.submit(_requests("a", "b"), idempotency_key="k1")

    assert str(job.state) == "pending", "EFF-05: a submitted batch is pending, not done"
    assert fake.executed == [], "EFF-05: submit only queues the work"
    assert _drain(fake, job.job_id) == ["running", "running", "succeeded"]
    status = fake.poll(job.job_id)
    assert (status.total, status.succeeded, status.failed) == (2, 2, 0)
    assert status.job_id == job.job_id


def test_EFF_05_results_before_the_job_is_done_raise_not_ready():
    from tilo_providers.batch import BatchNotReadyError, FakeBatchProvider  # noqa: PLC0415

    fake = FakeBatchProvider(polls_until_done=2)
    job = fake.submit(_requests("a"), idempotency_key="k1")

    with pytest.raises(BatchNotReadyError):
        fake.results(job.job_id)
    assert issubclass(BatchNotReadyError, ProviderError)
    fake.poll(job.job_id)
    with pytest.raises(BatchNotReadyError):
        fake.results(job.job_id)  # still running after poll 1 of 2


def test_EFF_05_results_come_back_in_submission_order_one_per_request():
    from tilo_providers.batch import FakeBatchProvider  # noqa: PLC0415

    fake = FakeBatchProvider(profile_id="fake-batch-x")
    job = fake.submit(_requests("c", "a", "b"), idempotency_key="k1")
    _drain(fake, job.job_id)

    results = fake.results(job.job_id)

    assert [r.custom_id for r in results] == ["c", "a", "b"]
    assert all(r.status == "ok" and r.error is None for r in results)
    assert all(isinstance(r.response, GenerateResponse) and r.response.profile_id == "fake-batch-x" for r in results)
    assert fake.executed == ["c", "a", "b"]


def test_EFF_05_polling_a_finished_job_is_stable_and_results_can_be_read_twice():
    from tilo_providers.batch import FakeBatchProvider  # noqa: PLC0415

    fake = FakeBatchProvider()
    job = fake.submit(_requests("a", "b"), idempotency_key="k1")
    _drain(fake, job.job_id)

    assert str(fake.poll(job.job_id).state) == "succeeded" == str(fake.poll(job.job_id).state)
    assert fake.results(job.job_id) == fake.results(job.job_id)
    assert fake.executed == ["a", "b"], "EFF-05: reading results never runs an item again"


def test_EFF_05_the_same_request_gets_the_same_text_from_two_fresh_fakes():
    from tilo_providers.batch import FakeBatchProvider  # noqa: PLC0415

    texts = []
    for _ in range(2):
        fake = FakeBatchProvider()
        job = fake.submit(_requests("a"), idempotency_key="k1")
        _drain(fake, job.job_id)
        texts.append(fake.results(job.job_id)[0].response.text)
    assert texts[0] == texts[1] and texts[0], "EFF-05: the fake is deterministic, like FakeModelProvider (PL-02)"


def test_EFF_05_respond_callable_supplies_the_text_per_request():
    from tilo_providers.batch import FakeBatchProvider  # noqa: PLC0415

    fake = FakeBatchProvider(respond=lambda item: f"answer:{item.custom_id}:{item.request.prompt}")
    job = fake.submit(_requests("a", "b"), idempotency_key="k1")
    _drain(fake, job.job_id)

    assert [r.response.text for r in fake.results(job.job_id)] == [
        "answer:a:prompt for a",
        "answer:b:prompt for b",
    ]


# --- partial failure ---------------------------------------------------------------------------------------------


def test_EFF_05_partial_failure_is_reported_per_item_and_never_raises():
    from tilo_providers.batch import FakeBatchProvider  # noqa: PLC0415

    fake = FakeBatchProvider(fail={"b"})
    job = fake.submit(_requests("a", "b", "c"), idempotency_key="k1")
    _drain(fake, job.job_id)

    status = fake.poll(job.job_id)
    results = {r.custom_id: r for r in fake.results(job.job_id)}

    assert str(status.state) == "partial"
    assert (status.total, status.succeeded, status.failed) == (3, 2, 1)
    assert results["b"].status == "error" and results["b"].response is None
    assert isinstance(results["b"].error, str) and results["b"].error.strip()
    assert results["a"].status == "ok" and results["c"].status == "ok"
    assert [r.custom_id for r in fake.results(job.job_id)] == ["a", "b", "c"], "order is kept around a failure"


def test_EFF_05_a_batch_where_every_item_fails_is_failed_not_succeeded():
    from tilo_providers.batch import FakeBatchProvider  # noqa: PLC0415

    fake = FakeBatchProvider(fail={"a", "b"})
    job = fake.submit(_requests("a", "b"), idempotency_key="k1")
    _drain(fake, job.job_id)

    status = fake.poll(job.job_id)
    assert str(status.state) == "failed" and (status.succeeded, status.failed) == (0, 2)
    assert all(r.status == "error" for r in fake.results(job.job_id))


# --- idempotent re-run -------------------------------------------------------------------------------------------


def test_EFF_05_same_key_and_requests_return_the_same_job_and_run_nothing_twice():
    from tilo_providers.batch import FakeBatchProvider  # noqa: PLC0415

    fake = FakeBatchProvider()
    first = fake.submit(_requests("a", "b"), idempotency_key="nightly-2026-10-06")
    _drain(fake, first.job_id)
    second = fake.submit(_requests("a", "b"), idempotency_key="nightly-2026-10-06")

    assert second.job_id == first.job_id, "EFF-05: a re-run with the same key joins the same job"
    assert fake.executed == ["a", "b"], "EFF-05: a re-run never executes an item a second time"
    assert str(second.state) in TERMINAL, "the re-run sees the finished job, not a pending one"
    assert [r.custom_id for r in fake.results(second.job_id)] == ["a", "b"]


def test_EFF_05_resubmitting_before_the_job_finishes_also_joins_it():
    from tilo_providers.batch import FakeBatchProvider  # noqa: PLC0415

    fake = FakeBatchProvider(polls_until_done=3)
    first = fake.submit(_requests("a"), idempotency_key="k")
    fake.poll(first.job_id)
    second = fake.submit(_requests("a"), idempotency_key="k")

    assert second.job_id == first.job_id
    _drain(fake, first.job_id)
    assert fake.executed == ["a"]


def test_EFF_05_a_different_key_is_a_new_job():
    from tilo_providers.batch import FakeBatchProvider  # noqa: PLC0415

    fake = FakeBatchProvider()
    one = fake.submit(_requests("a"), idempotency_key="k1")
    two = fake.submit(_requests("a"), idempotency_key="k2")

    assert one.job_id != two.job_id
    _drain(fake, one.job_id)
    _drain(fake, two.job_id)
    assert fake.executed == ["a", "a"]


def test_EFF_05_reusing_a_key_for_different_requests_is_refused():
    from tilo_providers.batch import FakeBatchProvider  # noqa: PLC0415

    fake = FakeBatchProvider()
    fake.submit(_requests("a"), idempotency_key="k")

    with pytest.raises(RequestError, match="idempotency"):
        fake.submit(_requests("a", "b"), idempotency_key="k")


@settings(max_examples=40, suppress_health_check=[HealthCheck.function_scoped_fixture])
@given(
    ids=st.lists(st.text(alphabet="abcdefgh", min_size=1, max_size=3), min_size=1, max_size=8, unique=True),
    resubmits=st.integers(min_value=1, max_value=4),
)
def test_EFF_05_property_each_item_runs_exactly_once_however_often_the_key_is_resubmitted(ids, resubmits):
    from tilo_providers.batch import FakeBatchProvider  # noqa: PLC0415

    fake = FakeBatchProvider(polls_until_done=2)
    job_ids = set()
    for _ in range(resubmits):
        job = fake.submit(_requests(*ids), idempotency_key="same")
        job_ids.add(job.job_id)
        _drain(fake, job.job_id)
    assert len(job_ids) == 1
    assert sorted(fake.executed) == sorted(ids), "EFF-05: every item executed once, never more"


@settings(max_examples=60, suppress_health_check=[HealthCheck.function_scoped_fixture])
@given(
    ids=st.lists(st.text(alphabet="abcdefgh", min_size=1, max_size=3), min_size=1, max_size=8, unique=True),
    data=st.data(),
)
def test_EFF_05_property_counts_add_up_and_order_is_kept_whatever_fails(ids, data):
    from tilo_providers.batch import FakeBatchProvider  # noqa: PLC0415

    failing = set(data.draw(st.lists(st.sampled_from(ids), unique=True)))
    fake = FakeBatchProvider(fail=failing)
    job = fake.submit(_requests(*ids), idempotency_key="k")
    _drain(fake, job.job_id)

    status = fake.poll(job.job_id)
    results = fake.results(job.job_id)

    assert [r.custom_id for r in results] == ids
    assert {r.custom_id for r in results if r.status == "error"} == failing
    assert status.total == len(ids) and status.succeeded + status.failed == status.total
    assert status.failed == len(failing)
    expected = "failed" if len(failing) == len(ids) else "partial" if failing else "succeeded"
    assert str(status.state) == expected


# --- refusals ----------------------------------------------------------------------------------------------------


def test_EFF_05_an_empty_batch_a_duplicate_id_and_a_blank_key_are_refused():
    from tilo_providers.batch import FakeBatchProvider  # noqa: PLC0415

    fake = FakeBatchProvider()
    with pytest.raises(RequestError):
        fake.submit([], idempotency_key="k")
    with pytest.raises(RequestError, match="custom_id"):
        fake.submit(_requests("a", "a"), idempotency_key="k")
    with pytest.raises(RequestError, match="idempotency"):
        fake.submit(_requests("a"), idempotency_key="   ")


def test_EFF_05_an_unknown_job_id_is_refused_by_poll_and_results():
    from tilo_providers.batch import FakeBatchProvider  # noqa: PLC0415

    fake = FakeBatchProvider()
    with pytest.raises(RequestError):
        fake.poll("no-such-job")
    with pytest.raises(RequestError):
        fake.results("no-such-job")


@pytest.mark.parametrize("name", ["K_SERVICE", "CLOUD_RUN_JOB"])
def test_EFF_05_the_fake_is_refused_when_deployed_on_cloud_run(monkeypatch, name):
    from tilo_providers.batch import FakeBatchProvider  # noqa: PLC0415

    monkeypatch.setenv(name, "")  # presence, not truthiness: Cloud Run can set an empty string
    with pytest.raises(ProviderConfigError, match="fake"):
        FakeBatchProvider()


def test_EFF_05_the_fake_is_refused_when_the_live_switch_is_on(monkeypatch):
    from tilo_providers.batch import FakeBatchProvider  # noqa: PLC0415

    monkeypatch.setenv("LIVE", "1")
    with pytest.raises(ProviderConfigError, match="fake"):
        FakeBatchProvider()


def test_EFF_05_the_fake_opens_no_socket_at_all(monkeypatch):
    from tilo_providers.batch import FakeBatchProvider  # noqa: PLC0415

    def no_connect(self, address, *args, **kwargs):  # even loopback is refused here
        raise AssertionError(f"EFF-05: the fake batch provider tried to connect to {address!r}")

    monkeypatch.setattr(socket.socket, "connect", no_connect)
    fake = FakeBatchProvider()
    job = fake.submit(_requests("a", "b"), idempotency_key="k")
    _drain(fake, job.job_id)
    assert len(fake.results(job.job_id)) == 2
