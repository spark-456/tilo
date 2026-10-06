"""EFF-05: the Google batch adapter against a mock client only (no network, no SDK): submit joins an existing job by
display name, poll maps the job state, results map per-item answers and failures."""

from __future__ import annotations

from types import SimpleNamespace as NS

import pytest
from conftest import models_config, prices_config, write_providers_config
from tilo_providers.batch import BatchRequest
from tilo_providers.config import load_providers_config
from tilo_providers.google_batch_adapter import GoogleBatchProvider
from tilo_providers.interfaces import GenerateRequest

pytestmark = pytest.mark.usefixtures("block_non_local_sockets")


class _Batches:
    def __init__(self, jobs):
        self.jobs, self.created = jobs, []

    def list(self):
        return list(self.jobs)

    def create(self, *, model, src, config):
        self.created.append((model, src, config))
        job = NS(name="batches/1", display_name=config["display_name"], state=NS(name="JOB_STATE_PENDING"))
        self.jobs.append(job)
        return job

    def get(self, *, name):
        return next(j for j in self.jobs if j.name == name)


def _provider(tmp_path, jobs=()):
    models = models_config()
    models["profiles"]["large"]["provider"] = "google"
    config = load_providers_config(*write_providers_config(tmp_path, models, prices_config()))
    client = NS(batches=_Batches(list(jobs)))
    provider = GoogleBatchProvider(config.profiles["large"], "large", "demo-project", "global", client=client)
    return provider, client


def _items(*ids):
    return [BatchRequest(custom_id=i, request=GenerateRequest(prompt=f"p {i}")) for i in ids]


def test_EFF_05_google_batch_submit_creates_once_and_a_rerun_joins_the_job(tmp_path):
    provider, client = _provider(tmp_path)

    first = provider.submit(_items("a", "b"), idempotency_key="night-1")
    second = provider.submit(_items("a", "b"), idempotency_key="night-1")

    assert first.job_id == second.job_id == "batches/1" and len(client.batches.created) == 1
    assert client.batches.created[0][2] == {"display_name": "tilo-night-1"}


def test_EFF_05_google_batch_results_map_answers_and_item_failures(tmp_path):
    ok = NS(
        metadata={"key": "a"},
        error=None,
        response=NS(text="hi", prompt_feedback=None, candidates=[], usage_metadata=None, function_calls=None),
    )
    bad = NS(metadata={"key": "b"}, error="quota", response=None)
    job = NS(
        name="batches/9",
        display_name="x",
        state=NS(name="JOB_STATE_PARTIALLY_SUCCEEDED"),
        completion_stats=NS(successful_count=1, failed_count=1),
        dest=NS(inlined_responses=[ok, bad]),
    )
    provider, _ = _provider(tmp_path, [job])

    status = provider.poll("batches/9")
    results = provider.results("batches/9")

    assert (str(status.state), status.total, status.failed) == ("partial", 2, 1)
    assert [(r.custom_id, r.status) for r in results] == [("a", "ok"), ("b", "error")]
    assert results[0].response.text == "hi" and results[1].error == "quota"
