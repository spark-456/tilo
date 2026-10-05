"""PL-02 live Vertex AI Gemini smoke (ticket PL-LIVE-vertex-smoke): the live gate, the hard caps, ADC only.

PRD 6.4 PL-02 ("`google` (default) adapter"), EFF-01 ("no paid model calls unless the live switch is on"),
PRD 6.5 (Gemini through the global endpoint on Vertex AI). Acceptance criteria covered here:

  (1) refuses unless environ LIVE == "1", checked first, before any Vertex client import, credential lookup
      or request;
  (2) HARD CAPS: small per-call max_output_tokens (default 64) and a total spend ceiling in credits (default
      tiny); the run aborts before the next call if the ceiling would be exceeded; fixed, short, synthetic prompt;
  ADC only (no API keys), project from GOOGLE_CLOUD_PROJECT, location default "global".

Public interface: `tilo_providers.vertex_smoke.run_vertex_smoke` / `main`, and `scripts/live_vertex_smoke.py`
(pinned in API_PL_LIVE_vertex_smoke.md). No network: the Google Gen AI SDK is faked at the `sys.modules`
boundary and the autouse guard below (plus conftest's socket guard) blocks everything except loopback.
The live switch is only ever set inside a test's own patched environ (`_vertex_smoke_lib.env`).

Ambiguities resolved (PRD 6.5 default, see the report): the location comes from GOOGLE_LOCATION, default
"global"; `contracts/providers.schema.json` $defs.profile has no location or endpoint field.
"""

from __future__ import annotations

import os
import re
import socket
import subprocess
import sys
from pathlib import Path

import pytest
from _vertex_smoke_lib import (
    FAIL_RE,
    PROJECT,
    REAL_MODELS,
    ROLES,
    SMOKE_SCRIPT,
    FakeVertexSdk,
    SpyEnviron,
    env,
    fake_secret,
    invoke_main,
    live_run,
    smoke,
    vertex_imports_blocked,
    write_prices,
)

REFUSED_RE = re.compile(r"^REFUSED (?P<code>[a-z_]+): (?P<message>.+)$")


@pytest.fixture(autouse=True)
def _loopback_only_network(monkeypatch: pytest.MonkeyPatch) -> None:
    """(8) Criterion: no network except a local fake on 127.0.0.1. conftest guards `connect`; this also
    refuses name resolution of anything but loopback, so not even a DNS lookup leaves the machine."""
    real_getaddrinfo = socket.getaddrinfo

    def guarded(host, *args, **kwargs):  # type: ignore[no-untyped-def]
        if host not in {"127.0.0.1", "::1", "localhost", None}:
            raise RuntimeError(f"PL_LIVE tests must not resolve {host!r}: no network except 127.0.0.1")
        return real_getaddrinfo(host, *args, **kwargs)

    monkeypatch.setattr(socket, "getaddrinfo", guarded)


def test_PL_LIVE_tests_reach_no_network_except_loopback() -> None:
    # (8) the guard itself works: a non-loopback connect and a non-loopback lookup both fail loudly.
    with pytest.raises(RuntimeError):
        socket.create_connection(("203.0.113.7", 443), timeout=0.2)
    with pytest.raises(RuntimeError):
        socket.getaddrinfo("us-central1-aiplatform.googleapis.com", 443)


# ---------------------------------------------------------------------------------------------------------
# (1) The gate: LIVE must be exactly "1", and is looked at before anything else
# ---------------------------------------------------------------------------------------------------------


@pytest.mark.parametrize("live", [None, "", "0", "true", "yes", "01", " 1", "1 "])
def test_PL_LIVE_01_run_refuses_unless_live_is_exactly_1_and_looks_at_nothing_else_first(
    live: str | None, tmp_path: Path
) -> None:
    values = {"GOOGLE_CLOUD_PROJECT": PROJECT, "GOOGLE_APPLICATION_CREDENTIALS": str(tmp_path / "adc.json")}
    if live is not None:
        values["LIVE"] = live
    spy = SpyEnviron(values)
    with env(), vertex_imports_blocked() as blocker:
        module = smoke()  # imported afresh inside the blocker: a module-level Vertex import would raise here
        with pytest.raises(module.SmokeRefused) as info:
            module.run_vertex_smoke(
                environ=spy,
                models_path=tmp_path / "does-not-exist.yaml",  # the gate comes before even reading config
                prices_path=tmp_path / "does-not-exist.yaml",
                fixtures_dir=tmp_path / "fixtures",
            )
    assert info.value.code == "live_not_enabled"
    assert spy.touched <= {"LIVE"}, f"looked at {sorted(spy.touched)} before the gate"
    assert blocker.hits == [], f"imported {blocker.hits} before the gate"
    assert not (tmp_path / "fixtures").exists()


@pytest.mark.parametrize("live", [None, "0", "true"])
def test_PL_LIVE_01_main_prints_one_refusal_line_and_exits_2(live: str | None, tmp_path: Path) -> None:
    values = {"GOOGLE_CLOUD_PROJECT": PROJECT}
    if live is not None:
        values["LIVE"] = live
    spy = SpyEnviron(values)
    with env(), vertex_imports_blocked() as blocker:
        result = invoke_main(["--models-file", str(tmp_path / "nope.yaml")], environ=spy)
    assert result.code == 2
    assert result.out == ""
    lines = result.err_lines()
    assert len(lines) == 1
    match = REFUSED_RE.match(lines[0])
    assert match and match["code"] == "live_not_enabled"
    assert "LIVE" in match["message"]  # tells the user which switch to set
    assert spy.touched <= {"LIVE"} and blocker.hits == []


def test_PL_LIVE_01_script_refuses_without_the_switch_in_a_real_process(tmp_path: Path) -> None:
    child_env = {k: v for k, v in os.environ.items() if k not in {"LIVE", "TILO_RECORD", "GOOGLE_API_KEY"}}
    child_env["GOOGLE_CLOUD_PROJECT"] = PROJECT
    done = subprocess.run(
        [sys.executable, str(SMOKE_SCRIPT)], capture_output=True, text=True, env=child_env, cwd=tmp_path, timeout=120
    )
    assert done.returncode == 2, (done.stdout, done.stderr)
    assert "Traceback" not in done.stderr
    lines = [line for line in done.stderr.splitlines() if line.strip()]
    assert len(lines) == 1 and REFUSED_RE.match(lines[0])
    assert "live_not_enabled" in lines[0]


def test_PL_LIVE_01_script_help_lists_the_flags() -> None:
    child_env = {k: v for k, v in os.environ.items() if k not in {"LIVE", "TILO_RECORD"}}
    done = subprocess.run(
        [sys.executable, str(SMOKE_SCRIPT), "--help"], capture_output=True, text=True, env=child_env, timeout=120
    )
    assert done.returncode == 0, done.stderr
    for flag in (
        "--max-output-tokens",
        "--max-credits",
        "--replay",
        "--models-file",
        "--prices-file",
        "--fixtures-dir",
    ):
        assert flag in done.stdout


# ---------------------------------------------------------------------------------------------------------
# (2) Hard caps
# ---------------------------------------------------------------------------------------------------------


def test_PL_LIVE_02_default_caps_are_small_and_hard_limits_bound_the_flags() -> None:
    module = smoke()
    assert module.DEFAULT_MAX_OUTPUT_TOKENS == 64
    assert 64 <= module.HARD_MAX_OUTPUT_TOKENS <= 256
    assert 0 < module.DEFAULT_MAX_TOTAL_CREDITS <= 2.0  # at most US$0.01: tiny by default
    assert module.DEFAULT_MAX_TOTAL_CREDITS <= module.HARD_MAX_TOTAL_CREDITS <= 100.0
    assert module.SMOKE_ROLES == ROLES
    assert module.THINKING_MINIMUM == "minimal"


def test_PL_LIVE_02_prompt_is_fixed_short_and_synthetic() -> None:
    module = smoke()
    prompt = module.SMOKE_PROMPT
    assert isinstance(prompt, str) and 0 < len(prompt.split()) <= 40
    assert prompt == prompt.strip() and "\n" not in prompt
    # synthetic: nothing from the environment, the machine or the user's data
    for fragment in (PROJECT, str(Path.home()), os.environ.get("USERNAME", "\0"), "@", "http"):
        assert fragment not in prompt


def test_PL_LIVE_02_every_call_is_capped_and_sends_only_the_fixed_prompt(tmp_path: Path) -> None:
    result, sdk, _ = live_run(tmp_path)
    assert result.code == 0, result.err
    module = smoke()
    assert len(sdk.calls) == 7  # exactly one small call per role, no retries when nothing fails
    for call in sdk.calls:
        assert call["contents"] == module.SMOKE_PROMPT
        config = call["config"]
        assert config.max_output_tokens == 64
        # nothing else rides along: no system text, tools or response schema; thinking is the only extra
        assert set(vars(config)) <= {"max_output_tokens", "thinking_config"}


@pytest.mark.parametrize(
    "flag,value", [("--max-output-tokens", "4096"), ("--max-output-tokens", "0"), ("--max-credits", "1000")]
)
def test_PL_LIVE_02_caps_above_the_hard_limit_or_below_one_are_refused_before_any_call(
    flag: str, value: str, tmp_path: Path
) -> None:
    result, sdk, fixtures = live_run(tmp_path, extra_args=(flag, value), credits=None)
    assert result.code == 2
    assert sdk.client_inits == [] and sdk.calls == []
    lines = result.err_lines()
    assert len(lines) == 1
    match = REFUSED_RE.match(lines[0])
    assert match and match["code"] == "cap_out_of_range"
    assert not fixtures.exists()


def test_PL_LIVE_02_total_ceiling_aborts_before_the_next_call(tmp_path: Path) -> None:
    # Uniform fixture prices of 100 / 200 US$ per million tokens: one call (20 in, 30 out) really costs
    # 1.6 credits, but sending a 64-token reply could cost >= 2.56 credits. With a ceiling of 4.0 the first
    # call fits (estimate <= 3.36) and, with 2.4 left, the second would not.
    prices = write_prices(tmp_path, uniform=(100.0, 200.0))
    result, sdk, _ = live_run(tmp_path, prices=prices, credits=4.0)
    assert len(sdk.calls) == 1  # aborted BEFORE the second request was made
    assert result.code == 1
    assert [m["role"] for m in result.rows()] == ["director"]
    lines = result.err_lines()
    assert len(lines) == 1
    match = FAIL_RE.match(lines[0])
    assert match and match["role"] == "lead" and match["code"] == "ceiling"
    assert "ceiling" in match["message"] and "--max-credits" in match["fix"]
    total = result.total()
    assert total is not None and float(total["credits"]) == pytest.approx(1.6, abs=1e-4)
    assert float(total["credits"]) <= 4.0


def test_PL_LIVE_02_ceiling_below_the_first_call_makes_no_request_at_all(tmp_path: Path) -> None:
    prices = write_prices(tmp_path, uniform=(100.0, 200.0))
    result, sdk, fixtures = live_run(tmp_path, prices=prices, credits=1.0)
    assert sdk.calls == []
    assert result.code == 1
    lines = result.err_lines()
    assert len(lines) == 1 and lines[0].startswith("FAIL role=director reason=ceiling:")
    assert not list(fixtures.glob("model-recordings/**/*.json"))


def test_PL_LIVE_02_default_ceiling_is_the_one_printed_and_a_normal_run_fits_under_it(tmp_path: Path) -> None:
    module = smoke()
    prices = write_prices(tmp_path, scale=0.1)  # fake fixture prices small enough for the default ceiling
    result, sdk, _ = live_run(tmp_path, prices=prices, credits=None)
    assert result.code == 0, result.err
    assert len(sdk.calls) == 7
    total = result.total()
    assert total is not None
    assert float(total["ceiling"]) == pytest.approx(module.DEFAULT_MAX_TOTAL_CREDITS, abs=1e-4)
    assert float(total["credits"]) <= float(total["ceiling"])


# ---------------------------------------------------------------------------------------------------------
# ADC only, project from the environment, location default "global"
# ---------------------------------------------------------------------------------------------------------


def test_PL_LIVE_12_vertex_client_uses_adc_project_and_global_location_and_no_key(tmp_path: Path) -> None:
    result, sdk, _ = live_run(tmp_path)
    assert result.code == 0, result.err
    assert sdk.client_inits, "the router never built a client"
    for init in sdk.client_inits:
        # exactly these three arguments: Application Default Credentials, never an api_key or a credentials object
        assert init == {"vertexai": True, "project": PROJECT, "location": "global"}


def test_PL_LIVE_12_location_comes_from_the_environment_when_set(tmp_path: Path) -> None:
    result, sdk, _ = live_run(tmp_path, extra_env={"GOOGLE_LOCATION": "asia-southeast1"})
    assert result.code == 0, result.err
    assert {init["location"] for init in sdk.client_inits} == {"asia-southeast1"}


@pytest.mark.parametrize("name", ["GOOGLE_API_KEY", "GEMINI_API_KEY"])
def test_PL_LIVE_12_an_api_key_in_the_environment_is_refused_by_name_never_by_value(name: str, tmp_path: Path) -> None:
    key_value = fake_secret("api_key")
    result, sdk, fixtures = live_run(tmp_path, extra_env={name: key_value})
    assert result.code == 2
    assert sdk.client_inits == [] and sdk.calls == []
    lines = result.err_lines()
    assert len(lines) == 1
    match = REFUSED_RE.match(lines[0])
    assert match and match["code"] == "api_key_present" and name in match["message"]
    assert key_value not in result.everything
    assert not fixtures.exists()


def test_PL_LIVE_13_missing_project_is_refused_naming_the_variable(tmp_path: Path) -> None:
    sdk = FakeVertexSdk()
    prices = write_prices(tmp_path)
    with env(LIVE="1"), sdk.installed():  # no GOOGLE_CLOUD_PROJECT
        result = invoke_main(
            ["--models-file", str(REAL_MODELS), "--prices-file", str(prices), "--fixtures-dir", str(tmp_path / "f")]
        )
    assert result.code == 2
    assert sdk.client_inits == [] and sdk.calls == []
    lines = result.err_lines()
    assert len(lines) == 1
    match = REFUSED_RE.match(lines[0])
    assert match and match["code"] == "missing_project" and "GOOGLE_CLOUD_PROJECT" in match["message"]
