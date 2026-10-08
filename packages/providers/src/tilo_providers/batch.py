"""tilo_providers.batch: the batch path for non-urgent jobs (EFF-05, PRD 6.6 "Batch the non-urgent").

`BatchProvider` is submit, poll, results. `FakeBatchProvider` is the deterministic in-memory fake (refused when the live
switch is on or when deployed, like `FakeSafetyProvider`). `RecordReplayBatchProvider` replays the same recordings as
`RecordReplayProvider` (`model-recordings/<role>/<key>.json`) and builds the live provider only when a call goes live
(the live switch, or the injected `live_permitted`, SEC-15). An item failure is data (`status="error"`), never an
exception; a re-run with the same idempotency key joins the same job and runs no item twice."""

from __future__ import annotations

import enum
import hashlib
import json
import os
from abc import ABC, abstractmethod
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from tilo_providers.config import ProviderConfigError, ProvidersConfig
from tilo_providers.errors import ProviderError, RequestError
from tilo_providers.fake import _canned_text
from tilo_providers.interfaces import GenerateRequest, GenerateResponse
from tilo_providers.replay import is_live_mode, recording_key


class BatchNotReadyError(ProviderError):
    """`results()` was called before the job reached a terminal state."""


class BatchState(enum.StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    PARTIAL = "partial"
    FAILED = "failed"


TERMINAL_STATES = frozenset({BatchState.SUCCEEDED, BatchState.PARTIAL, BatchState.FAILED})


class BatchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    custom_id: str = Field(min_length=1)
    request: GenerateRequest

    @field_validator("request")
    @classmethod
    def _no_media(cls, request: GenerateRequest) -> GenerateRequest:
        if request.parts:  # the batch wire carries the prompt only: refuse rather than drop a file silently
            raise RequestError("LW-06: a batch request carries no media parts")
        return request


class BatchJob(BaseModel):
    model_config = ConfigDict(extra="forbid")
    job_id: str
    state: BatchState


class BatchStatus(BaseModel):
    model_config = ConfigDict(extra="forbid")
    job_id: str
    state: BatchState
    total: int
    succeeded: int
    failed: int


class BatchResult(BaseModel):
    model_config = ConfigDict(extra="forbid")
    custom_id: str
    status: Literal["ok", "error"]
    response: GenerateResponse | None = None
    error: str | None = None


class BatchProvider(ABC):
    @abstractmethod
    def submit(self, requests: Sequence[BatchRequest], *, idempotency_key: str) -> BatchJob: ...
    @abstractmethod
    def poll(self, job_id: str) -> BatchStatus: ...
    @abstractmethod
    def results(self, job_id: str) -> list[BatchResult]:
        """Submission order; raises `BatchNotReadyError` until the job is terminal."""


def _fingerprint(requests: Sequence[BatchRequest]) -> str:
    payload = [item.model_dump(exclude_none=True) for item in requests]
    return hashlib.sha256(json.dumps(payload, sort_keys=True).encode("utf-8")).hexdigest()


def _item_error(error: Exception) -> str:
    return " ".join(f"{type(error).__name__}: {error}".split())[:300]


class _Job:
    def __init__(self, requests: Sequence[BatchRequest], fingerprint: str) -> None:
        self.requests, self.fingerprint = list(requests), fingerprint
        self.polls = 0
        self.state = BatchState.PENDING
        self.results: list[BatchResult] = []


class InMemoryBatchProvider(BatchProvider):
    """Job bookkeeping shared by the fake, the replay path and the nightly's default wiring: submit queues, poll
    number `polls_until_done` runs every item (`_run_item`) and reaches the terminal state."""

    def __init__(self, *, polls_until_done: int = 1) -> None:
        self._polls_until_done = max(1, polls_until_done)
        self._jobs: dict[str, _Job] = {}
        self.executed: list[str] = []  # custom ids actually run, in order (a re-run adds none)

    @abstractmethod
    def _run_item(self, item: BatchRequest) -> GenerateResponse: ...

    def submit(self, requests: Sequence[BatchRequest], *, idempotency_key: str) -> BatchJob:
        if not idempotency_key.strip():
            raise RequestError("EFF-05: a batch needs a non-blank idempotency key")
        if not requests:
            raise RequestError("EFF-05: a batch needs at least one request")
        ids = [item.custom_id for item in requests]
        if len(set(ids)) != len(ids):
            raise RequestError("EFF-05: custom_id values in one batch must be unique")
        job_id = "batch-" + hashlib.sha256(idempotency_key.encode("utf-8")).hexdigest()[:12]
        fingerprint = _fingerprint(requests)
        if (job := self._jobs.get(job_id)) is None:
            job = self._jobs[job_id] = _Job(requests, fingerprint)
        elif job.fingerprint != fingerprint:
            raise RequestError("EFF-05: the idempotency key was already used for different requests")
        return BatchJob(job_id=job_id, state=job.state)

    def _job(self, job_id: str) -> _Job:
        if job_id not in self._jobs:
            raise RequestError(f"EFF-05: unknown batch job {job_id!r}")
        return self._jobs[job_id]

    def poll(self, job_id: str) -> BatchStatus:
        job = self._job(job_id)
        if job.state not in TERMINAL_STATES:
            job.polls += 1
            job.state = BatchState.RUNNING
            if job.polls >= self._polls_until_done:
                self._finish(job)
        failed = sum(r.status == "error" for r in job.results)
        return BatchStatus(
            job_id=job_id, state=job.state, total=len(job.requests), succeeded=len(job.results) - failed, failed=failed
        )

    def _finish(self, job: _Job) -> None:
        for item in job.requests:
            self.executed.append(item.custom_id)
            try:
                response = self._run_item(item)
            except Exception as error:  # noqa: BLE001 - an item failure is data, never an exception
                job.results.append(BatchResult(custom_id=item.custom_id, status="error", error=_item_error(error)))
            else:
                job.results.append(BatchResult(custom_id=item.custom_id, status="ok", response=response))
        failed = sum(r.status == "error" for r in job.results)
        job.state = (
            BatchState.SUCCEEDED
            if not failed
            else BatchState.FAILED
            if failed == len(job.results)
            else BatchState.PARTIAL
        )

    def results(self, job_id: str) -> list[BatchResult]:
        job = self._job(job_id)
        if job.state not in TERMINAL_STATES:
            raise BatchNotReadyError(f"EFF-05: batch job {job_id!r} is {job.state}, not finished")
        return list(job.results)


class FakeBatchProvider(InMemoryBatchProvider):
    def __init__(
        self,
        profile_id: str = "fake-batch",
        *,
        polls_until_done: int = 1,
        fail: Sequence[str] = (),
        respond: Callable[[BatchRequest], str] | None = None,
    ) -> None:
        if is_live_mode() or "K_SERVICE" in os.environ or "CLOUD_RUN_JOB" in os.environ:
            raise ProviderConfigError(
                "EFF-05: the fake batch provider is refused in live mode or when deployed "
                "(K_SERVICE or CLOUD_RUN_JOB set)"
            )
        super().__init__(polls_until_done=polls_until_done)
        self._profile_id, self._fail, self._respond = profile_id, frozenset(fail), respond

    def _run_item(self, item: BatchRequest) -> GenerateResponse:
        if item.custom_id in self._fail:
            raise ProviderError("the fake was told to fail this item")
        text = self._respond(item) if self._respond else _canned_text(item.request.prompt)
        return GenerateResponse(text=text, profile_id=self._profile_id)


class RecordReplayBatchProvider(InMemoryBatchProvider):
    """Replays recordings by default (zero network); with the live switch (or `live_permitted`) every call goes to the
    provider `live_factory` builds. A missing recording is an item error naming its key. Never records."""

    def __init__(
        self,
        role: str,
        profile_id: str,
        live_factory: Callable[[], BatchProvider],
        fixtures_dir: Path | str,
        live_permitted: bool = False,
    ) -> None:
        super().__init__(polls_until_done=1)
        self._role, self._profile_id = role, profile_id
        self._live_factory, self._live_permitted = live_factory, live_permitted
        self._live_provider: BatchProvider | None = None
        self._live_jobs: set[str] = set()
        self._recordings_dir = Path(fixtures_dir) / "model-recordings" / role

    def _live(self) -> BatchProvider:
        if self._live_provider is None:
            self._live_provider = self._live_factory()
        return self._live_provider

    def _run_item(self, item: BatchRequest) -> GenerateResponse:
        key = recording_key(self._role, self._profile_id, item.request)
        path = self._recordings_dir / f"{key}.json"
        if not path.is_file():
            raise ProviderError(
                f"EFF-01: no recording for role={self._role!r} profile={self._profile_id!r} key={key!r}"
            )
        return GenerateResponse.model_validate(json.loads(path.read_text(encoding="utf-8"))["response"])

    def submit(self, requests: Sequence[BatchRequest], *, idempotency_key: str) -> BatchJob:
        if not (self._live_permitted or is_live_mode()):
            return super().submit(requests, idempotency_key=idempotency_key)
        job = self._live().submit(requests, idempotency_key=idempotency_key)
        self._live_jobs.add(job.job_id)
        return job

    def poll(self, job_id: str) -> BatchStatus:
        return self._live().poll(job_id) if job_id in self._live_jobs else super().poll(job_id)

    def results(self, job_id: str) -> list[BatchResult]:
        return self._live().results(job_id) if job_id in self._live_jobs else super().results(job_id)


def build_batch_provider(
    role_id: str, config: ProvidersConfig, *, fixtures_dir: Path | str, live_permitted: bool = False
) -> BatchProvider:
    """`provider: fake` -> `FakeBatchProvider`; else replay. No adapter is imported unless a call goes live."""
    profile_id = config.roles[role_id].primary
    profile = config.profiles[profile_id]
    if profile.provider == "fake":
        return FakeBatchProvider(profile_id=profile_id)

    def live_factory() -> BatchProvider:
        if profile.provider != "google":
            raise ProviderConfigError(
                f"EFF-05: provider {profile.provider!r} has no batch adapter (profile {profile_id!r})"
            )
        from tilo_providers.google_batch_adapter import GoogleBatchProvider  # noqa: PLC0415

        return GoogleBatchProvider(
            profile=profile,
            profile_id=profile_id,
            project=os.environ["GOOGLE_CLOUD_PROJECT"],
            location=os.environ.get("GOOGLE_LOCATION", "global"),
            live_permitted=live_permitted,
        )

    return RecordReplayBatchProvider(role_id, profile_id, live_factory, fixtures_dir, live_permitted=live_permitted)
