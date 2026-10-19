"""tilo_providers.google_batch_adapter: the real batch adapter over `google.genai` `client.batches` (EFF-05, PRD 6.6).

Built and tested against mocks only; it is reached through `build_batch_provider`'s live path, never by dev or CI.
Without an injected `client=` it refuses to build unless the live switch is on (or `live_permitted`, SEC-15), like
`GoogleModelProvider`. The job's display name carries the idempotency key, so a re-run joins the existing job instead
of paying twice. Open point (docs/open-questions.md): Vertex batch may need a GCS source/destination instead of the
inline requests used here; decide before the first live night."""

from __future__ import annotations

import os
from collections.abc import Sequence
from typing import Any

from tilo_contracts import ProvidersProfile

from tilo_providers.batch import (
    BatchJob,
    BatchProvider,
    BatchRequest,
    BatchResult,
    BatchState,
    BatchStatus,
    refuse_media,
)
from tilo_providers.errors import ProviderError, RequestError
from tilo_providers.google_adapter import GoogleModelProvider, _genai_module, validate_google_settings
from tilo_providers.interfaces import GenerateResponse

_STATES = {
    "JOB_STATE_PENDING": BatchState.PENDING,
    "JOB_STATE_QUEUED": BatchState.PENDING,
    "JOB_STATE_RUNNING": BatchState.RUNNING,
    "JOB_STATE_SUCCEEDED": BatchState.SUCCEEDED,
    "JOB_STATE_PARTIALLY_SUCCEEDED": BatchState.PARTIAL,
    "JOB_STATE_FAILED": BatchState.FAILED,
    "JOB_STATE_CANCELLED": BatchState.FAILED,
    "JOB_STATE_EXPIRED": BatchState.FAILED,
}


def _state(job: Any) -> BatchState:
    raw = getattr(job.state, "name", job.state)
    return _STATES.get(str(raw), BatchState.RUNNING)  # an unknown state is not terminal: keep polling


class GoogleBatchProvider(BatchProvider):
    def __init__(
        self,
        profile: ProvidersProfile,
        profile_id: str,
        project: str,
        location: str,
        client: Any | None = None,
        live_permitted: bool = False,
    ) -> None:
        self._profile, self._profile_id = profile, profile_id
        self._mapper = GoogleModelProvider.__new__(GoogleModelProvider)  # reuse its response mapping; no client built
        self._mapper._profile, self._mapper._profile_id = profile, profile_id  # noqa: SLF001
        if client is None:
            if os.environ.get("LIVE") != "1" and not live_permitted:
                raise ProviderError("EFF-05/EFF-01: refusing to build a real batch client without LIVE=1")
            validate_google_settings(project, location)
            client = _genai_module("google.genai").Client(vertexai=True, project=project, location=location)
        self._client = client

    def submit(self, requests: Sequence[BatchRequest], *, idempotency_key: str) -> BatchJob:
        refuse_media(requests)
        if not idempotency_key.strip() or not requests:
            raise RequestError("EFF-05: a batch needs requests and a non-blank idempotency key")
        name = f"tilo-{idempotency_key}"
        for job in self._client.batches.list():
            if getattr(job, "display_name", None) == name:  # a re-run joins the job instead of paying twice
                return BatchJob(job_id=job.name, state=_state(job))
        inline = [
            {
                "contents": [{"role": "user", "parts": [{"text": item.request.prompt}]}],
                "metadata": {"key": item.custom_id},
            }
            for item in requests
        ]
        job = self._client.batches.create(model=self._profile.model, src=inline, config={"display_name": name})
        return BatchJob(job_id=job.name, state=_state(job))

    def poll(self, job_id: str) -> BatchStatus:
        job = self._client.batches.get(name=job_id)
        stats = getattr(job, "completion_stats", None)
        done, failed = int(getattr(stats, "successful_count", 0) or 0), int(getattr(stats, "failed_count", 0) or 0)
        return BatchStatus(job_id=job_id, state=_state(job), total=done + failed, succeeded=done, failed=failed)

    def results(self, job_id: str) -> list[BatchResult]:
        job = self._client.batches.get(name=job_id)
        if _state(job) not in (BatchState.SUCCEEDED, BatchState.PARTIAL, BatchState.FAILED):
            raise ProviderError(f"EFF-05: batch job {job_id!r} is not finished")
        out: list[BatchResult] = []
        for item in getattr(job.dest, "inlined_responses", None) or []:
            custom_id = str((getattr(item, "metadata", None) or {}).get("key", len(out)))
            if getattr(item, "error", None) is not None or getattr(item, "response", None) is None:
                error = " ".join(str(getattr(item, "error", "no response")).split())[:300] or "no response"
                out.append(BatchResult(custom_id=custom_id, status="error", error=error))
                continue
            try:
                response: GenerateResponse = self._mapper._map_response(item.response)  # noqa: SLF001
            except ProviderError as error:  # a safety block is an item failure, not a crash
                out.append(BatchResult(custom_id=custom_id, status="error", error=str(error)[:300]))
            else:
                out.append(BatchResult(custom_id=custom_id, status="ok", response=response))
        return out
