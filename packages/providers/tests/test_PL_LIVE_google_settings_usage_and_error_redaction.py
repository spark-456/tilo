"""PL-02 live Vertex smoke, security fix pass (PR 295 verdict): honest usage when Vertex leaves a count out,
settings validated before any client is built, and no token in an error. Nothing here reaches a network: the SDK
is faked at the `sys.modules` boundary and every fake secret is assembled at runtime.

  (1) a None token count is zero; thinking-only output (candidates None, thoughts 64) is 64 billed output tokens,
      and the smoke and the router charge that call;
  (2) GOOGLE_LOCATION, GOOGLE_CLOUD_PROJECT, GOOGLE_VERTEX_BASE_URL and a service-account key file are refused
      by variable name (never value) with one REFUSED line, before any client exists;
  (3) a server message echoing an access token never reaches str, repr or format_exception of a raised error.
"""

from __future__ import annotations

import json
import re
import traceback
import types as pytypes
from pathlib import Path

import pytest
from _fake_genai_sdk import FakeAPIError
from _vertex_smoke_lib import (
    PROJECT,
    REAL_MODELS,
    FakeVertexSdk,
    env,
    expected_credits,
    fake_secret,
    live_run,
    real_config,
    write_prices,
)
from tilo_contracts import ProvidersProfile
from tilo_providers.config import load_providers_config
from tilo_providers.interfaces import GenerateRequest
from tilo_providers.router import Router, RouterError

REFUSED_RE = re.compile(r"^REFUSED (?P<code>[a-z_]+): (?P<message>.+)$")
INJECTED_LOCATIONS = ["evil.example/x", "x@evil.example/", "evil.example#", "evil.example?a=", "global\n", "", "US"]
EVIL_BASE_URL = "https://evil.example/"
BAD_PROJECTS = ["x/evil.example", "p?a=1", "p#frag", "Bad_Project", "ab", "a" * 40, "1abcdef", "abcde-"]


def _profile(caps: tuple[str, ...] = ("json", "thinking")) -> ProvidersProfile:
    return ProvidersProfile.model_validate(
        {"provider": "google", "model": "adapter-test-model", "context": 1000, "caps": list(caps)}
    )


def _provider(sdk: FakeVertexSdk):
    from tilo_providers.google_adapter import GoogleModelProvider  # noqa: PLC0415

    return GoogleModelProvider(
        profile=_profile(), profile_id="p", project="demo-project", location="global", client=sdk._client()
    )


# ---------------------------------------------------------------------------------------------------------
# (1) None counts
# ---------------------------------------------------------------------------------------------------------


def test_PL_LIVE_05_candidates_none_with_thoughts_is_the_thought_tokens_as_output() -> None:
    sdk = FakeVertexSdk(usage=(18, None), thoughts=64)
    with sdk.installed():
        response = _provider(sdk).generate(GenerateRequest(prompt="hello", max_output_tokens=64))
    assert response.usage == {"input_tokens": 18, "output_tokens": 64, "total_tokens": 82}


def test_PL_LIVE_05_candidates_none_with_thoughts_is_counted_in_a_stream_chunk_too() -> None:
    sdk = FakeVertexSdk(usage=(18, None), thoughts=64)
    with sdk.installed():
        provider = _provider(sdk)
        models = provider._client.models
        models.generate_content_stream = lambda **kw: iter([models.generate_content(**kw)])
        chunks = list(provider.stream(GenerateRequest(prompt="hello")))
    assert [c.usage for c in chunks] == [{"input_tokens": 18, "output_tokens": 64, "total_tokens": 82}]


@pytest.mark.parametrize("thoughts", [None, 0])
def test_PL_LIVE_05_every_none_count_reads_as_zero(thoughts: int | None) -> None:
    sdk = FakeVertexSdk()
    with sdk.installed():
        provider = _provider(sdk)
    meta = pytypes.SimpleNamespace(
        prompt_token_count=None, candidates_token_count=None, thoughts_token_count=thoughts, total_token_count=None
    )
    response = pytypes.SimpleNamespace(text="x", candidates=[], prompt_feedback=None, usage_metadata=meta)
    assert provider._map_response(response).usage == {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0}


def test_PL_LIVE_05_the_smoke_charges_a_call_whose_candidates_count_is_none(tmp_path: Path) -> None:
    prices = write_prices(tmp_path)
    cfg = load_providers_config(REAL_MODELS, prices)
    sdk = FakeVertexSdk(usage=(18, None), thoughts=64)
    result, _, _ = live_run(tmp_path, sdk=sdk, prices=prices)
    assert result.code == 0, result.err
    rows = result.rows()
    assert len(rows) == 7 and all(m["fallback_from"] is None for m in rows)  # served by the primary, not a fallback
    for match in rows:
        assert (int(match["tin"]), int(match["tout"])) == (18, 64)
        assert float(match["credits"]) == pytest.approx(expected_credits(cfg, match["profile"], 18, 64), abs=1e-4)
    total = result.total()
    assert total is not None
    assert float(total["credits"]) == pytest.approx(sum(float(m["credits"]) for m in rows), abs=2e-4)
    assert float(total["credits"]) > 0


def test_PL_LIVE_05_the_router_reports_the_tokens_of_a_call_whose_candidates_count_is_none(tmp_path: Path) -> None:
    sdk = FakeVertexSdk(usage=(18, None), thoughts=64)
    config = load_providers_config(REAL_MODELS, write_prices(tmp_path))
    with env(LIVE="1", GOOGLE_CLOUD_PROJECT=PROJECT), sdk.installed():
        result = Router(config, fixtures_dir=tmp_path / "f").generate("director", GenerateRequest(prompt="hi"))
    assert [a.outcome for a in result.attempts] == ["ok"]  # no TypeError, no fallback
    assert (result.attempts[0].tokens_in, result.attempts[0].tokens_out) == (18, 64)


# ---------------------------------------------------------------------------------------------------------
# (2) Settings validated before any client is built
# ---------------------------------------------------------------------------------------------------------


def _one_refusal(result, sdk: FakeVertexSdk, tmp_path: Path, code: str, name: str, value: str | None = None) -> None:
    assert result.code == 2
    assert sdk.client_inits == [] and sdk.calls == []  # no client was built, nothing was sent
    lines = result.err_lines()
    assert len(lines) == 1, lines
    match = REFUSED_RE.match(lines[0])
    assert match and match["code"] == code and name in match["message"]
    if value and "evil" in value or value and value.startswith(str(tmp_path)):
        assert value.strip() not in result.everything  # the offending value is never printed
    assert result.out == ""
    assert not (tmp_path / "fixtures").exists()


@pytest.mark.parametrize("location", INJECTED_LOCATIONS)
def test_PL_LIVE_12_an_injected_location_is_refused_before_any_client_is_built(location: str, tmp_path: Path) -> None:
    sdk = FakeVertexSdk()
    result, _, _ = live_run(tmp_path, sdk=sdk, extra_env={"GOOGLE_LOCATION": location})
    _one_refusal(result, sdk, tmp_path, "location_invalid", "GOOGLE_LOCATION", location)


@pytest.mark.parametrize("location", ["global", "us", "eu", "asia-southeast1", "europe-west4", "us-central1"])
def test_PL_LIVE_12_the_accepted_locations_build_a_client(location: str, tmp_path: Path) -> None:
    result, sdk, _ = live_run(tmp_path, extra_env={"GOOGLE_LOCATION": location})
    assert result.code == 0, result.err
    assert {init["location"] for init in sdk.client_inits} == {location}


def test_PL_LIVE_12_a_base_url_override_is_refused_naming_the_variable_never_the_value(tmp_path: Path) -> None:
    sdk = FakeVertexSdk()
    result, _, _ = live_run(tmp_path, sdk=sdk, extra_env={"GOOGLE_VERTEX_BASE_URL": EVIL_BASE_URL})
    _one_refusal(result, sdk, tmp_path, "base_url_set", "GOOGLE_VERTEX_BASE_URL", "evil.example")


@pytest.mark.parametrize("project", BAD_PROJECTS)
def test_PL_LIVE_13_a_project_that_is_not_a_project_id_is_refused(project: str, tmp_path: Path) -> None:
    sdk = FakeVertexSdk()
    result, _, _ = live_run(tmp_path, sdk=sdk, extra_env={"GOOGLE_CLOUD_PROJECT": project})
    _one_refusal(result, sdk, tmp_path, "project_invalid", "GOOGLE_CLOUD_PROJECT", project)


def test_PL_LIVE_12_a_service_account_key_file_is_refused_by_name_but_an_empty_object_passes(tmp_path: Path) -> None:
    key = tmp_path / "key.json"
    key.write_text(json.dumps({"type": "service" + "_account", "project_id": "demo"}), encoding="utf-8")
    sdk = FakeVertexSdk()
    result, _, _ = live_run(tmp_path, sdk=sdk, extra_env={"GOOGLE_APPLICATION_CREDENTIALS": str(key)})
    _one_refusal(result, sdk, tmp_path, "service_account_key", "GOOGLE_APPLICATION_CREDENTIALS", str(key))

    for name, content in (("empty", {}), ("user", {"type": "authorized_user"})):
        path = tmp_path / f"{name}.json"
        path.write_text(json.dumps(content), encoding="utf-8")
        extra = {"GOOGLE_APPLICATION_CREDENTIALS": str(path)}
        ok, _, _ = live_run(tmp_path, extra_env=extra, fixtures=tmp_path / f"f-{name}")
        assert ok.code == 0, ok.err


def test_PL_LIVE_12_the_smoke_reads_the_environment_the_router_reads(tmp_path: Path) -> None:
    # a programmatic caller's own `environ` must not hide an API key or a project problem from the checks
    from tilo_providers.vertex_smoke import SmokeRefused, run_vertex_smoke  # noqa: PLC0415

    sdk = FakeVertexSdk()
    prices = write_prices(tmp_path)
    clean = {"LIVE": "1", "GOOGLE_CLOUD_PROJECT": PROJECT}
    with env(LIVE="1", GOOGLE_CLOUD_PROJECT=PROJECT, GOOGLE_API_KEY=fake_secret("api_key")), sdk.installed():
        with pytest.raises(SmokeRefused) as key_info:
            run_vertex_smoke(environ=clean, models_path=REAL_MODELS, prices_path=prices, fixtures_dir=tmp_path / "f")
    assert key_info.value.code == "api_key_present"
    with env(LIVE="1", GOOGLE_CLOUD_PROJECT="x/evil.example"), sdk.installed():
        with pytest.raises(SmokeRefused) as project_info:
            run_vertex_smoke(environ=clean, models_path=REAL_MODELS, prices_path=prices, fixtures_dir=tmp_path / "f")
    assert project_info.value.code == "project_invalid"
    assert sdk.client_inits == [] and sdk.calls == []


@pytest.mark.parametrize("location", INJECTED_LOCATIONS[:4])
def test_PL_LIVE_12_the_adapter_itself_refuses_an_injected_location_before_building_a_client(location: str) -> None:
    from tilo_providers.google_adapter import GoogleModelProvider, GoogleSettingsError  # noqa: PLC0415

    sdk = FakeVertexSdk()
    with env(LIVE="1"), sdk.installed(), pytest.raises(GoogleSettingsError) as info:
        GoogleModelProvider(profile=_profile(), profile_id="p", project=PROJECT, location=location)
    assert "GOOGLE_LOCATION" in str(info.value) and "evil.example" not in str(info.value)
    assert sdk.client_inits == []


def test_PL_LIVE_12_the_adapter_itself_refuses_a_base_url_override_before_building_a_client() -> None:
    from tilo_providers.google_adapter import GoogleModelProvider, GoogleSettingsError  # noqa: PLC0415

    sdk = FakeVertexSdk()
    with env(LIVE="1", GOOGLE_VERTEX_BASE_URL=EVIL_BASE_URL), sdk.installed():
        with pytest.raises(GoogleSettingsError) as info:
            GoogleModelProvider(profile=_profile(), profile_id="p", project=PROJECT, location="global")
    assert "GOOGLE_VERTEX_BASE_URL" in str(info.value) and "evil.example" not in str(info.value)
    assert sdk.client_inits == []


# ---------------------------------------------------------------------------------------------------------
# (3) No token in a mapped error
# ---------------------------------------------------------------------------------------------------------


def _everywhere(error: BaseException) -> str:
    return "\n".join([str(error), repr(error), "".join(traceback.format_exception(error))])


def test_PL_LIVE_06_a_403_echoing_a_token_never_shows_in_the_adapter_error() -> None:
    token = fake_secret("access_token")
    echo = FakeAPIError(403, f"denied for {token} [PERMISSION_DENIED]")
    sdk = FakeVertexSdk(errors_by_model={"adapter-test-model": echo})
    with sdk.installed():
        provider = _provider(sdk)
        with pytest.raises(Exception) as info:
            provider.generate(GenerateRequest(prompt="hello"))
    text = _everywhere(info.value)
    assert token not in text and token.split(".", 1)[1] not in text
    assert "denied for" in text and getattr(info.value.__cause__, "code", None) == 403  # status kept for classifying


def test_PL_LIVE_06_a_403_echoing_a_token_never_shows_in_the_router_error(tmp_path: Path) -> None:
    token = fake_secret("access_token")
    cfg = real_config()
    errors: dict[str, Exception] = {
        p.model: FakeAPIError(403, f"denied for {token} [PERMISSION_DENIED]") for p in cfg.profiles.values()
    }
    sdk = FakeVertexSdk(errors_by_model=errors)
    config = load_providers_config(REAL_MODELS, write_prices(tmp_path))
    with env(LIVE="1", GOOGLE_CLOUD_PROJECT=PROJECT), sdk.installed():
        with pytest.raises(RouterError) as info:
            Router(config, fixtures_dir=tmp_path / "f").generate("director", GenerateRequest(prompt="hi"), budget=50.0)
    text = _everywhere(info.value)
    assert token not in text and token.split(".", 1)[1] not in text
    assert "denied for" in text
