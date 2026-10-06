"""EFF-05 / EFF-01 (PRD 6.6): the batch path replays recordings by default, makes zero network calls, and goes live only
with the user's live switch.

PRD 6.6 "Record and replay": "Dev and CI run on recorded model responses; live calls need an explicit live switch."
The batch path obeys the same rule as `RecordReplayProvider` (`test_EFF_01_provider_factory_and_replay.py`) and,
to avoid a second recording format, reads the SAME recordings:
`<fixtures>/model-recordings/<role>/<recording_key>.json`, keyed by
`tilo_providers.replay.recording_key(role, profile_id, request)`. Anything the inline path can replay, the batch
path can replay.

Interface (new, in `tilo_providers/batch.py` unless stated; see the contract file for the shared types):

  RecordReplayBatchProvider(role, profile_id, live_factory, fixtures_dir, live_permitted=False)  -> BatchProvider
      live_factory: zero-argument, builds the live BatchProvider; called only when a call actually goes live.
  build_batch_provider(role_id, config, *, fixtures_dir, live_permitted=False) -> BatchProvider
      `provider: fake` profile -> FakeBatchProvider; any other -> RecordReplayBatchProvider (no adapter module is
      imported, no client built, unless the live switch is on).
  tilo_providers.google_batch_adapter.GoogleBatchProvider(profile, profile_id, project, location, client=None,
      live_permitted=False): the real Vertex/Gemini batch adapter; built only through the live path.

Defaults chosen (PRD silent):
  * Replay completes on the first poll; a recording that is missing is an ITEM error naming the recording key (the job
    ends `partial` or `failed`), not an exception at submit, so one miss never hides the other results.
  * The live switch is the environment variable, as everywhere else (`is_live_mode`); `live_permitted=True` is the
    SEC-15 injected permission and is never read from the environment. Recording of batch results is out of scope for
    this ticket: the live path does not write recordings.
"""

from __future__ import annotations

import json
import socket
import sys

import pytest
from conftest import models_config, prices_config, write_providers_config
from tilo_providers.config import load_providers_config
from tilo_providers.errors import ProviderError
from tilo_providers.interfaces import GenerateRequest, GenerateResponse
from tilo_providers.replay import recording_key

pytestmark = pytest.mark.usefixtures("block_non_local_sockets")

TERMINAL = {"succeeded", "partial", "failed"}
ROLE, PROFILE = "director", "large"


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    for name in ("LIVE", "TILO_RECORD", "K_SERVICE", "CLOUD_RUN_JOB"):
        monkeypatch.delenv(name, raising=False)
    for name in ("tilo_providers.google_batch_adapter", "tilo_providers.google_adapter"):
        monkeypatch.delitem(sys.modules, name, raising=False)


def _batch(custom_id: str, prompt: str):
    from tilo_providers.batch import BatchRequest  # noqa: PLC0415

    return BatchRequest(custom_id=custom_id, request=GenerateRequest(prompt=prompt))


def _record(fixtures, request: GenerateRequest, text: str) -> str:
    """Writes a recording in the exact shape `RecordReplayProvider._write_recording` produces."""
    key = recording_key(ROLE, PROFILE, request)
    path = fixtures / "model-recordings" / ROLE / f"{key}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    response = GenerateResponse(text=text, profile_id=PROFILE, usage={"input_tokens": 3, "output_tokens": 2})
    payload = {"role": ROLE, "profile": PROFILE, "key": key, "response": response.model_dump(exclude_none=True)}
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return key


def _drain(provider, job_id: str, *, limit: int = 10) -> str:
    for _ in range(limit):
        state = str(provider.poll(job_id).state)
        if state in TERMINAL:
            return state
    raise AssertionError(f"EFF-05: job {job_id!r} not terminal after {limit} polls")


def _replay(fixtures, live_factory=None, **kwargs):
    from tilo_providers.batch import RecordReplayBatchProvider  # noqa: PLC0415

    def refuse() -> object:
        raise AssertionError("EFF-05: replay must never build the live provider")

    return RecordReplayBatchProvider(
        role=ROLE, profile_id=PROFILE, live_factory=live_factory or refuse, fixtures_dir=fixtures, **kwargs
    )


# --- replay: zero network, same recordings as the inline path ---------------------------------------------------


def test_EFF_05_replay_serves_recorded_responses_and_never_builds_the_live_provider(tmp_path):
    fixtures = tmp_path / "fixtures"
    one, two = _batch("one", "first prompt"), _batch("two", "second prompt")
    _record(fixtures, one.request, "recorded one")
    _record(fixtures, two.request, "recorded two")
    provider = _replay(fixtures)

    job = provider.submit([one, two], idempotency_key="nightly")
    state = _drain(provider, job.job_id)
    results = provider.results(job.job_id)

    assert state == "succeeded"
    assert [(r.custom_id, r.status, r.response.text) for r in results] == [
        ("one", "ok", "recorded one"),
        ("two", "ok", "recorded two"),
    ]
    assert results[0].response.usage == {"input_tokens": 3, "output_tokens": 2}


def test_EFF_05_batch_replay_returns_what_the_inline_replay_provider_returns(tmp_path):
    from tilo_providers.replay import RecordReplayProvider  # noqa: PLC0415

    fixtures = tmp_path / "fixtures"
    item = _batch("only", "same recording both ways")
    _record(fixtures, item.request, "shared recording")
    inline = RecordReplayProvider(ROLE, PROFILE, live_factory=lambda: pytest.fail("live"), fixtures_dir=fixtures)
    provider = _replay(fixtures)

    job = provider.submit([item], idempotency_key="k")
    _drain(provider, job.job_id)

    assert provider.results(job.job_id)[0].response == inline.generate(item.request)


def test_EFF_05_replay_makes_zero_network_calls(tmp_path, monkeypatch):
    fixtures = tmp_path / "fixtures"
    item = _batch("only", "p")
    _record(fixtures, item.request, "r")

    def no_connect(self, address, *args, **kwargs):  # even loopback is refused
        raise AssertionError(f"EFF-05/EFF-01: batch replay tried to connect to {address!r}")

    monkeypatch.setattr(socket.socket, "connect", no_connect)
    provider = _replay(fixtures)
    job = provider.submit([item], idempotency_key="k")
    _drain(provider, job.job_id)

    assert provider.results(job.job_id)[0].status == "ok"
    assert "tilo_providers.google_batch_adapter" not in sys.modules
    assert "tilo_providers.google_adapter" not in sys.modules


def test_EFF_05_a_missing_recording_is_one_item_error_naming_the_key_not_an_exception(tmp_path):
    fixtures = tmp_path / "fixtures"
    have, miss = _batch("have", "recorded prompt"), _batch("miss", "never recorded")
    _record(fixtures, have.request, "ok text")
    provider = _replay(fixtures)

    job = provider.submit([have, miss], idempotency_key="k")
    state = _drain(provider, job.job_id)
    by_id = {r.custom_id: r for r in provider.results(job.job_id)}

    assert state == "partial"
    assert by_id["have"].status == "ok"
    assert by_id["miss"].status == "error" and by_id["miss"].response is None
    assert recording_key(ROLE, PROFILE, miss.request) in by_id["miss"].error, "the error names the missing key"


def test_EFF_05_replay_with_no_recordings_at_all_is_failed_not_a_crash(tmp_path):
    provider = _replay(tmp_path / "empty")
    job = provider.submit([_batch("a", "p")], idempotency_key="k")

    assert _drain(provider, job.job_id) == "failed"


def test_EFF_05_replay_rerun_with_the_same_key_is_the_same_job(tmp_path):
    fixtures = tmp_path / "fixtures"
    item = _batch("only", "p")
    _record(fixtures, item.request, "r")
    provider = _replay(fixtures)

    first = provider.submit([item], idempotency_key="nightly-2026-10-06")
    _drain(provider, first.job_id)
    second = provider.submit([item], idempotency_key="nightly-2026-10-06")

    assert second.job_id == first.job_id
    assert [r.custom_id for r in provider.results(second.job_id)] == ["only"]


def test_EFF_05_the_record_switch_alone_never_writes_a_recording_in_replay(tmp_path, monkeypatch):
    fixtures = tmp_path / "fixtures"
    item = _batch("only", "p")
    _record(fixtures, item.request, "r")
    before = sorted(p.name for p in fixtures.rglob("*") if p.is_file())
    monkeypatch.setenv("TILO_RECORD", "1")  # without the live switch this must be inert

    provider = _replay(fixtures)
    job = provider.submit([item], idempotency_key="k")
    _drain(provider, job.job_id)

    assert sorted(p.name for p in fixtures.rglob("*") if p.is_file()) == before


# --- live gate -----------------------------------------------------------------------------------------------------


class _StubLive:
    """Stands in for the live adapter: records the calls it receives; no network."""

    def __init__(self) -> None:
        self.submitted: list[tuple[list[str], str]] = []

    def submit(self, requests, *, idempotency_key):
        from tilo_providers.batch import BatchJob  # noqa: PLC0415

        self.submitted.append(([r.custom_id for r in requests], idempotency_key))
        return BatchJob(job_id="live-job-1", state="pending")

    def poll(self, job_id):
        from tilo_providers.batch import BatchStatus  # noqa: PLC0415

        return BatchStatus(job_id=job_id, state="succeeded", total=1, succeeded=1, failed=0)

    def results(self, job_id):
        from tilo_providers.batch import BatchResult  # noqa: PLC0415

        return [
            BatchResult(
                custom_id="a", status="ok", response=GenerateResponse(text="live", profile_id=PROFILE), error=None
            )
        ]


def test_EFF_05_with_the_live_switch_off_the_live_factory_is_never_called(tmp_path):
    calls: list[str] = []

    def factory():
        calls.append("built")
        return _StubLive()

    provider = _replay(tmp_path / "fixtures", live_factory=factory)
    job = provider.submit([_batch("a", "p")], idempotency_key="k")
    _drain(provider, job.job_id)
    provider.results(job.job_id)

    assert calls == [], "EFF-05/EFF-01: the live provider is never even built without the live switch"


def test_EFF_05_with_the_live_switch_on_calls_go_to_the_live_provider(tmp_path, monkeypatch):
    monkeypatch.setenv("LIVE", "1")
    stub = _StubLive()
    provider = _replay(tmp_path / "fixtures", live_factory=lambda: stub)

    job = provider.submit([_batch("a", "p")], idempotency_key="nightly")

    assert job.job_id == "live-job-1" and stub.submitted == [(["a"], "nightly")]
    assert provider.results(job.job_id)[0].response.text == "live"


def test_EFF_05_live_permitted_is_an_injected_permission_not_an_environment_read(tmp_path):
    stub = _StubLive()
    provider = _replay(tmp_path / "fixtures", live_factory=lambda: stub, live_permitted=True)

    provider.submit([_batch("a", "p")], idempotency_key="k")

    assert stub.submitted == [(["a"], "k")], "SEC-15: live_permitted routes live without the environment switch"


@pytest.mark.parametrize("value", ["true", "0", "", "yes"])
def test_EFF_05_only_the_exact_live_value_counts_as_live(tmp_path, monkeypatch, value):
    monkeypatch.setenv("LIVE", value)
    provider = _replay(tmp_path / "fixtures")  # a live call would hit the refusing factory

    job = provider.submit([_batch("a", "p")], idempotency_key="k")

    assert _drain(provider, job.job_id) == "failed", "no recording, so replay reports a failed item, never goes live"


def test_EFF_05_the_real_batch_adapter_refuses_to_build_without_the_live_switch(tmp_path):
    from tilo_providers.google_batch_adapter import GoogleBatchProvider  # noqa: PLC0415

    models = models_config()
    models["profiles"]["large"]["provider"] = "google"
    config = load_providers_config(*write_providers_config(tmp_path, models, prices_config()))

    with pytest.raises(ProviderError, match="LIVE"):
        GoogleBatchProvider(
            profile=config.profiles[PROFILE], profile_id=PROFILE, project="demo-project", location="global"
        )


# --- factory -------------------------------------------------------------------------------------------------------


def _config(tmp_path, provider: str):
    models = models_config()
    models["profiles"]["large"]["provider"] = provider
    return load_providers_config(*write_providers_config(tmp_path, models, prices_config()))


def test_EFF_05_factory_returns_replay_for_a_live_profile_and_never_imports_an_adapter(tmp_path):
    from tilo_providers.batch import (  # noqa: PLC0415
        BatchProvider,
        FakeBatchProvider,
        RecordReplayBatchProvider,
        build_batch_provider,
    )

    config = _config(tmp_path, "google")

    provider = build_batch_provider(ROLE, config, fixtures_dir=tmp_path / "fixtures")

    assert isinstance(provider, BatchProvider) and isinstance(provider, RecordReplayBatchProvider)
    assert not isinstance(provider, FakeBatchProvider)
    assert "tilo_providers.google_batch_adapter" not in sys.modules
    assert "tilo_providers.google_adapter" not in sys.modules


def test_EFF_05_factory_returns_the_fake_for_a_fake_profile(tmp_path):
    from tilo_providers.batch import FakeBatchProvider, build_batch_provider  # noqa: PLC0415

    config = _config(tmp_path, "fake")

    assert isinstance(build_batch_provider(ROLE, config, fixtures_dir=tmp_path / "fixtures"), FakeBatchProvider)


def test_EFF_05_factory_refuses_the_fake_when_deployed(tmp_path, monkeypatch):
    from tilo_providers.batch import build_batch_provider  # noqa: PLC0415
    from tilo_providers.config import ProviderConfigError  # noqa: PLC0415

    monkeypatch.setenv("CLOUD_RUN_JOB", "tilo-eval-nightly")
    config = _config(tmp_path, "fake")

    with pytest.raises(ProviderConfigError, match="fake"):
        build_batch_provider(ROLE, config, fixtures_dir=tmp_path / "fixtures")


def test_EFF_05_factory_replay_works_when_deployed_on_a_cloud_run_job(tmp_path, monkeypatch):
    """The nightly job runs on Cloud Run (CLOUD_RUN_JOB set) and replays recordings: that must work."""
    from tilo_providers.batch import build_batch_provider  # noqa: PLC0415

    monkeypatch.setenv("CLOUD_RUN_JOB", "tilo-eval-nightly")
    fixtures = tmp_path / "fixtures"
    item = _batch("only", "p")
    _record(fixtures, item.request, "r")
    provider = build_batch_provider(ROLE, _config(tmp_path, "google"), fixtures_dir=fixtures)

    job = provider.submit([item], idempotency_key="k")

    assert _drain(provider, job.job_id) == "succeeded"
