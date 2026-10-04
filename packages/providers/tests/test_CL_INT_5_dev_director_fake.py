"""CL-INT-5 / EFF-01 / PL-01 (PL-05): the deterministic dev fake behind the Director role, selected by
`config/models.dev.yaml`. It answers brief and approaches requests with schema-valid, synthetic replies derived only
from the input; it is refused when deployed or live, and it never counts as conforming for a real role."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from tilo_contracts import Brief, PlanApproach
from tilo_providers.config import ProviderConfigError, load_providers_config
from tilo_providers.conformance import run_conformance_suite
from tilo_providers.dev_director import DevDirectorProvider
from tilo_providers.errors import RequestError
from tilo_providers.interfaces import GenerateRequest
from tilo_providers.router import Router, RouterExhaustedError

ROOT = Path(__file__).resolve().parents[3]
DEV_MODELS = ROOT / "config" / "models.dev.yaml"
BRIEF_SCHEMA: dict = {"properties": {"ambiguous_fields": {}}}
APPROACHES_SCHEMA: dict = {"properties": {"approaches": {}}}


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    for name in ("LIVE", "TILO_RECORD", "K_SERVICE", "CLOUD_RUN_JOB", "TILO_REQUIRE_CONFORMANCE"):
        monkeypatch.delenv(name, raising=False)


def _brief_request(task: str) -> GenerateRequest:
    return GenerateRequest(prompt=f"Extract.\n\n<<<TASK\n{task}\nTASK>>>", json_mode=True, response_schema=BRIEF_SCHEMA)


def _approaches_request(brief: dict) -> GenerateRequest:
    prompt = f"Propose.\n\n<<<BRIEF\n{json.dumps(brief, indent=2)}\nBRIEF>>>"
    return GenerateRequest(prompt=prompt, json_mode=True, response_schema=APPROACHES_SCHEMA)


def _reply(request: GenerateRequest) -> dict:
    return json.loads(DevDirectorProvider().generate(request).text or "")


def _brief(task: str) -> dict:
    reply = _reply(_brief_request(task))
    return {k: v for k, v in reply.items() if k != "ambiguous_fields"} | {"assumptions": [], "applied_preferences": []}


def test_CL_INT_5_same_input_gives_byte_identical_output():
    for request in (_brief_request("Summarise the Q3 supplier delays."), _approaches_request(_brief("Task"))):
        assert DevDirectorProvider().generate(request) == DevDirectorProvider().generate(request)
    assert _reply(_brief_request("One task")) != _reply(_brief_request("Another task"))


@pytest.mark.parametrize("task", ["Summarise the Q3 supplier delays.", "x" * 5000, "   ", "Due 2026-11-02, ok."])
def test_CL_INT_5_brief_reply_validates_and_is_derived_only_from_the_task(task):
    reply = _reply(_brief_request(task))

    Brief.model_validate(_brief(task))
    assert reply["goal"] == (" ".join(task.split())[:500].strip() or "No task text was given (dev)")
    assert reply["deliverables"][0]["title"].endswith("(dev)") and reply["audience"].endswith("(dev)")
    assert reply["deadline"] == ("2026-11-02" if "2026-11-02" in task else None)
    assert ("deadline" in reply["ambiguous_fields"]) == (reply["deadline"] is None)
    assert {"deliverables", "audience", "constraints", "sources", "sensitivity"} <= set(reply["ambiguous_fields"])


def test_CL_INT_5_an_impossible_date_in_the_task_is_not_a_deadline():
    assert _reply(_brief_request("Finish by 2026-13-45."))["deadline"] is None


def test_CL_INT_5_approaches_reply_is_three_distinct_in_cap_and_follows_the_briefs_format():
    brief = _brief("Plan the offsite")
    brief["deliverables"] = [{"title": "Deck", "format": "pptx"}]

    approaches = _reply(_approaches_request(brief))["approaches"]

    parsed = [PlanApproach.model_validate(a).model_dump(mode="json") for a in approaches]
    assert len(parsed) == 3 and len({a["id"] for a in parsed}) == 3
    for i, a in enumerate(parsed):
        assert a["dimensions"]["output_format"] == "pptx"
        assert a["label"].endswith("(dev)") and len(a["label"]) <= 40
        assert 0 <= a["credits"]["min"] <= a["credits"]["max"] <= 300  # config/metering.yaml run cap
        assert a["time"]["min_s"] <= a["time"]["max_s"]
        for b in parsed[i + 1 :]:
            differing = sum(a["dimensions"][k] != b["dimensions"][k] for k in a["dimensions"])
            assert differing >= 2


def test_CL_INT_5_a_repair_prompt_is_answered_from_the_same_blocks():
    request = _brief_request("Repair me")
    wrapped = request.model_copy(update={"prompt": f"{request.prompt}\n\nYour previous answer did not match: x"})
    assert _reply(wrapped) == _reply(request)


def test_CL_INT_5_an_unsupported_request_is_refused_not_guessed():
    with pytest.raises(RequestError):
        DevDirectorProvider().generate(GenerateRequest(prompt="hello"))


@pytest.mark.parametrize(
    ("var", "value"), [("K_SERVICE", "tilo-api"), ("K_SERVICE", ""), ("CLOUD_RUN_JOB", ""), ("LIVE", "1")]
)
def test_CL_INT_5_refused_when_deployed_or_live_at_load_build_and_every_call(monkeypatch, tmp_path, var, value):
    config = load_providers_config(DEV_MODELS, ROOT / "config" / "prices.yaml")
    provider = DevDirectorProvider()
    monkeypatch.setenv(var, value)  # presence, not truthiness (LIVE is exactly "1")

    with pytest.raises(ProviderConfigError, match="dev-only"):
        load_providers_config(DEV_MODELS, ROOT / "config" / "prices.yaml")
    with pytest.raises(ProviderConfigError, match="dev-only"):
        DevDirectorProvider()
    with pytest.raises(ProviderConfigError, match="dev-only"):
        provider.generate(_brief_request("x"))
    with pytest.raises(RouterExhaustedError):  # the router never falls back to a recording or another answer
        Router(config, fixtures_dir=tmp_path).generate("director", _brief_request("x"))


def test_CL_INT_5_router_serves_the_director_with_no_recordings(tmp_path):
    config = load_providers_config(DEV_MODELS, ROOT / "config" / "prices.yaml")
    run = Router(config, fixtures_dir=tmp_path / "no-recordings").generate("director", _brief_request("Any task text"))

    assert run.response is not None and run.response.profile_id == "director-dev"
    assert [a.outcome for a in run.attempts] == ["ok"]
    assert not (tmp_path / "no-recordings").exists()


def test_PL_05_CL_INT_5_the_dev_fake_never_conforms_for_a_real_role(tmp_path, monkeypatch):
    with pytest.raises(ValueError, match="dev-only"):
        run_conformance_suite("director-dev", DevDirectorProvider(), build="dev")

    (tmp_path / "director-dev.json").write_text(json.dumps({"result": "pass"}), encoding="utf-8")
    (tmp_path / "safety-fake.json").write_text(json.dumps({"result": "pass"}), encoding="utf-8")
    monkeypatch.setenv("TILO_REQUIRE_CONFORMANCE", "1")
    with pytest.raises(ProviderConfigError, match="never conforms"):  # a passing file for it does not count
        load_providers_config(DEV_MODELS, ROOT / "config" / "prices.yaml", conformance_dir=tmp_path)
