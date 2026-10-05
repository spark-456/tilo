"""PL-02 live Vertex smoke (ticket PL-LIVE-vertex-smoke): recordings, replay, secrets, failures, fallback.

PRD 6.6 EFF-01 ("Dev and CI run on recorded model responses; live calls need an explicit live switch";
recordings under fixtures/model-recordings/<role>/<key>.json, redacted per PRD 16.1 rule 4), PL-03
(fall back on quota), NFR-25 (a fallback profile per role). Acceptance criteria covered here:

  (6) TILO_RECORD=1 writes recordings under the existing convention; a second run without the live switch
      replays with zero network; no ADC tokens or secrets in recordings, logs or output;
  (7) failures (quota, permission, wrong location, API disabled) produce one clear line naming the role and
      the likely fix, no traceback with credentials; a fallback profile is used on 429 and shown.

Replay without the live switch is the command's `--replay` flag / `replay=True` (the live path itself always
refuses without the switch, criterion 1). Public interface: `tilo_providers.vertex_smoke`, pinned in
API_PL_LIVE_vertex_smoke.md. All SDK behaviour is faked; the fake errors mimic Vertex's real status texts.
"""

from __future__ import annotations

import json
import socket
from pathlib import Path
from typing import Any

import pytest
from _fake_genai_sdk import FakeAPIError
from _vertex_smoke_lib import (
    FAIL_RE,
    PROJECT,
    REAL_MODELS,
    ROLES,
    DefaultCredentialsError,
    FakeVertexSdk,
    cli_args,
    env,
    expected_credits,
    fake_secret,
    invoke_main,
    live_run,
    real_config,
    smoke,
    vertex_imports_blocked,
    write_prices,
)
from tilo_providers.config import load_providers_config
from tilo_providers.interfaces import Capability, GenerateRequest
from tilo_providers.replay import recording_key


@pytest.fixture(autouse=True)
def _loopback_only_network(monkeypatch: pytest.MonkeyPatch) -> None:
    real_getaddrinfo = socket.getaddrinfo

    def guarded(host, *args, **kwargs):  # type: ignore[no-untyped-def]
        if host not in {"127.0.0.1", "::1", "localhost", None}:
            raise RuntimeError(f"PL_LIVE tests must not resolve {host!r}: no network except 127.0.0.1")
        return real_getaddrinfo(host, *args, **kwargs)

    monkeypatch.setattr(socket, "getaddrinfo", guarded)


def _recordings(fixtures: Path) -> list[Path]:
    return sorted(fixtures.glob("model-recordings/*/*.json"))


# ---------------------------------------------------------------------------------------------------------
# (6) Recordings and replay
# ---------------------------------------------------------------------------------------------------------


def test_PL_LIVE_06_record_mode_writes_one_recording_per_role_under_the_existing_convention(tmp_path: Path) -> None:
    cfg = real_config()
    result, sdk, fixtures = live_run(tmp_path, extra_env={"TILO_RECORD": "1"})
    assert result.code == 0, result.err
    files = _recordings(fixtures)
    assert len(files) == 7 and {f.parent.name for f in files} == set(
        ROLES
    )  # fixtures/model-recordings/<role>/<key>.json
    module = smoke()
    for path in files:
        role = path.parent.name
        data = json.loads(path.read_text(encoding="utf-8"))
        profile_id = cfg.roles[role].primary
        profile = cfg.profiles[profile_id]
        level = module.THINKING_MINIMUM if Capability.THINKING in {Capability(c) for c in profile.caps} else None
        request = GenerateRequest(prompt=module.SMOKE_PROMPT, max_output_tokens=64, thinking_level=level)
        assert data["role"] == role and data["profile"] == profile_id
        assert path.stem == data["key"] == recording_key(role, profile_id, request)
        assert data["response"]["usage"]["input_tokens"] == 20 and data["response"]["usage"]["output_tokens"] == 30
    assert len(sdk.calls) == 7


def test_PL_LIVE_06_without_the_record_switch_nothing_is_written(tmp_path: Path) -> None:
    result, _, fixtures = live_run(tmp_path)
    assert result.code == 0, result.err
    assert _recordings(fixtures) == []


def test_PL_LIVE_06_second_run_without_live_replays_the_recordings_with_zero_network(tmp_path: Path) -> None:
    prices = write_prices(tmp_path)
    live, sdk, fixtures = live_run(tmp_path, prices=prices, extra_env={"TILO_RECORD": "1"})
    assert live.code == 0 and len(sdk.calls) == 7
    # replay: no switch, no project, no credentials, no SDK installed at all; importing any of them fails the test
    with env(), vertex_imports_blocked() as blocker:
        replayed = invoke_main(cli_args(REAL_MODELS, prices, fixtures, replay=True))
    assert replayed.code == 0, replayed.err
    assert replayed.err == "" and blocker.hits == []
    first = [(m["role"], m["profile"], m["tin"], m["tout"], m["credits"]) for m in live.rows()]
    second = [(m["role"], m["profile"], m["tin"], m["tout"], m["credits"]) for m in replayed.rows()]
    assert second == first
    replayed_total, live_total = replayed.total(), live.total()
    assert replayed_total is not None and live_total is not None
    assert replayed_total["credits"] == live_total["credits"]
    assert len(sdk.calls) == 7  # still the 7 live calls only


def test_PL_LIVE_06_replay_never_runs_with_the_live_switch_on(tmp_path: Path) -> None:
    prices = write_prices(tmp_path)
    sdk = FakeVertexSdk()
    with env(LIVE="1", GOOGLE_CLOUD_PROJECT=PROJECT), sdk.installed():
        result = invoke_main(cli_args(REAL_MODELS, prices, tmp_path / "f", replay=True))
    assert result.code == 2 and sdk.calls == [] and sdk.client_inits == []
    lines = result.err_lines()
    assert len(lines) == 1 and lines[0].startswith("REFUSED replay_with_live:")


def test_PL_LIVE_06_replay_miss_is_one_line_with_the_fix(tmp_path: Path) -> None:
    prices = write_prices(tmp_path)
    with env(), vertex_imports_blocked():
        result = invoke_main(cli_args(REAL_MODELS, prices, tmp_path / "empty", replay=True))
    assert result.code == 1
    lines = result.err_lines()
    assert len(lines) == 1
    match = FAIL_RE.match(lines[0])
    assert match and match["role"] == "director" and match["code"] == "replay_miss"
    assert "TILO_RECORD" in match["fix"]


def test_PL_LIVE_06_no_tokens_or_secrets_reach_recordings_logs_or_output(tmp_path: Path) -> None:
    token, bearer = fake_secret("access_token"), fake_secret("bearer")
    sdk = FakeVertexSdk(text=f"echoed back {bearer} and {token} by a misbehaving endpoint")
    adc_path = tmp_path / "application_default_credentials.json"
    adc_path.write_text("{}", encoding="utf-8")
    result, _, fixtures = live_run(
        tmp_path,
        sdk=sdk,
        extra_env={"TILO_RECORD": "1", "GOOGLE_APPLICATION_CREDENTIALS": str(adc_path)},
    )
    assert result.code == 0, result.err
    recorded = "\n".join(p.read_text(encoding="utf-8") for p in _recordings(fixtures))
    assert recorded  # there were recordings to check
    secret_bodies = [token, bearer, token.split(".", 1)[1], bearer.split(" ", 1)[1]]
    for blob_name, blob in (("recordings", recorded), ("output", result.everything)):
        for secret in secret_bodies:
            assert secret not in blob, f"a fake credential leaked into the {blob_name}"
    assert PROJECT not in recorded  # no environment values in recordings (EFF-01)
    assert str(adc_path) not in recorded and str(adc_path) not in result.everything


# ---------------------------------------------------------------------------------------------------------
# (7) Failures: one clear line naming the role and the likely fix
# ---------------------------------------------------------------------------------------------------------

QUOTA = (429, "Quota exceeded for aiplatform.googleapis.com/generate_content_requests_per_minute. [RESOURCE_EXHAUSTED]")
PERMISSION = (
    403,
    "Permission 'aiplatform.endpoints.predict' denied on resource "
    "'//aiplatform.googleapis.com/projects/demo/locations/global/publishers/google/models/m'. [PERMISSION_DENIED]",
)
API_DISABLED = (
    403,
    "Vertex AI API has not been used in project 123456789 before or it is disabled. Enable it by visiting "
    "https://console.developers.google.com/apis/api/aiplatform.googleapis.com/overview?project=123456789 "
    "then retry. [SERVICE_DISABLED]",
)
WRONG_LOCATION = (
    404,
    "Publisher Model `projects/demo/locations/us-central1/publishers/google/models/m` was not found or your "
    "project does not have access to it. [NOT_FOUND]",
)
EXPIRED_ADC = (401, "Request had invalid authentication credentials. Expected OAuth 2 access token. [UNAUTHENTICATED]")

FAILURES = [
    pytest.param(QUOTA, "quota", "quota", 2, id="quota"),  # 429 tries the fallback profile too, then stops
    pytest.param(PERMISSION, "permission", "roles/aiplatform.user", 1, id="permission"),
    pytest.param(API_DISABLED, "api_disabled", "aiplatform.googleapis.com", 1, id="api-disabled"),
    pytest.param(WRONG_LOCATION, "location", "GOOGLE_LOCATION", 1, id="wrong-location"),
    pytest.param(EXPIRED_ADC, "auth", "gcloud auth application-default login", 1, id="expired-adc"),
]


@pytest.mark.parametrize("status_and_message,code,fix_has,calls", FAILURES)
def test_PL_LIVE_07_a_failure_is_one_line_naming_the_role_and_the_fix(
    status_and_message: tuple[int, str], code: str, fix_has: str, calls: int, tmp_path: Path
) -> None:
    cfg = real_config()
    status, message = status_and_message
    leaky = f"{message} Authorization: {fake_secret('bearer')} token={fake_secret('access_token')}"
    sdk = FakeVertexSdk(errors_by_model={p.model: FakeAPIError(status, leaky) for p in cfg.profiles.values()})
    result, _, fixtures = live_run(tmp_path, sdk=sdk, extra_env={"TILO_RECORD": "1"})
    assert result.code == 1
    assert len(sdk.calls) == calls  # the first role failed; the run stopped there (no spend on the other six)
    lines = result.err_lines()
    assert len(lines) == 1, lines
    match = FAIL_RE.match(lines[0])
    assert match, lines[0]
    assert match["role"] == "director" and match["code"] == code
    assert fix_has in match["fix"]
    assert result.rows() == []
    assert "Traceback" not in result.everything and 'File "' not in result.everything
    for secret in (fake_secret("access_token"), fake_secret("bearer").split(" ", 1)[1], "Authorization"):
        assert secret not in result.everything
    assert _recordings(fixtures) == []  # a failed call records nothing


def test_PL_LIVE_07_missing_adc_is_one_line_with_the_login_command(tmp_path: Path) -> None:
    error = DefaultCredentialsError(
        "Your default credentials were not found. To set up Application Default Credentials, see "
        "https://cloud.google.com/docs/authentication/external/set-up-adc for more information."
    )
    sdk = FakeVertexSdk(client_error=error)
    result, _, _ = live_run(tmp_path, sdk=sdk)
    assert result.code == 1
    assert sdk.calls == [] and sdk.client_inits  # a client was attempted, nothing was sent
    lines = result.err_lines()
    assert len(lines) == 1
    match = FAIL_RE.match(lines[0])
    assert match and match["role"] == "director" and match["code"] == "auth"
    assert "gcloud auth application-default login" in match["fix"]
    assert "Traceback" not in result.everything


def test_PL_LIVE_07_a_429_on_the_primary_uses_the_fallback_profile_and_shows_it(tmp_path: Path) -> None:
    prices = write_prices(tmp_path)
    cfg = load_providers_config(REAL_MODELS, prices)
    limited_profile = cfg.roles["director"].primary
    limited_model = cfg.profiles[limited_profile].model
    sdk = FakeVertexSdk(errors_by_model={limited_model: FakeAPIError(*QUOTA)}, usage=(20, 30))
    result, _, _ = live_run(tmp_path, sdk=sdk, prices=prices)
    assert result.code == 0, result.err
    rows = {m["role"]: m for m in result.rows()}
    assert list(rows) == list(ROLES)
    hit_roles = [r for r in ROLES if cfg.roles[r].primary == limited_profile]
    assert "director" in hit_roles
    for role in ROLES:
        primary, fallback = cfg.roles[role].primary, cfg.roles[role].fallback
        if role in hit_roles:
            assert rows[role]["profile"] == fallback and rows[role]["fallback_from"] == primary
        else:
            assert rows[role]["profile"] == primary and rows[role]["fallback_from"] is None
        # metering follows the profile that actually served the call
        want = expected_credits(cfg, rows[role]["profile"], 20, 30)
        assert float(rows[role]["credits"]) == pytest.approx(want, abs=1e-4)
    assert sdk.models_called().count(limited_model) == len(hit_roles)  # each tried the primary once, then fell back
    assert len(sdk.calls) == 7 + len(hit_roles)


def test_PL_LIVE_07_a_failure_after_some_successes_keeps_the_rows_already_printed(tmp_path: Path) -> None:
    cfg = real_config()
    # the narrator profile fails with a request error; the five roles before it succeeded and were printed
    broken = cfg.profiles[cfg.roles["narrator"].primary].model
    others = {cfg.profiles[cfg.roles[r].primary].model for r in ROLES if r != "narrator"}
    assert broken not in others, "fixture assumption: the narrator profile is not shared with another role"
    sdk = FakeVertexSdk(errors_by_model={broken: FakeAPIError(*PERMISSION)})
    result, _, _ = live_run(tmp_path, sdk=sdk)
    assert result.code == 1
    assert [m["role"] for m in result.rows()] == ["director", "lead", "specialist", "verifier", "writer"]
    lines = result.err_lines()
    assert len(lines) == 1 and lines[0].startswith("FAIL role=narrator reason=permission:")
    assert "autopilot" not in result.everything  # the run stopped; the last role never ran
    total = result.total()
    assert total is not None  # what was spent so far is still reported


# ---------------------------------------------------------------------------------------------------------
# (7b) A 400 is "rejected": the live smoke found Vertex answers 400 to a thinking level it does not support
# ---------------------------------------------------------------------------------------------------------

REJECTED_THINKING = (400, "Thinking level is unsupported: THINKING_LEVEL_MINIMAL")


def _rejected_run(tmp_path: Path, status: int, message: str) -> tuple[Any, FakeVertexSdk]:
    cfg = real_config()
    sdk = FakeVertexSdk(errors_by_model={p.model: FakeAPIError(status, message) for p in cfg.profiles.values()})
    result, _, _ = live_run(tmp_path, sdk=sdk)
    return result, sdk


def test_PL_LIVE_07_a_400_is_rejected_and_shows_the_servers_reason(tmp_path: Path) -> None:
    result, sdk = _rejected_run(tmp_path, *REJECTED_THINKING)
    assert result.code == 1 and len(sdk.calls) == 1
    lines = result.err_lines()
    assert len(lines) == 1, lines
    match = FAIL_RE.match(lines[0])
    assert match and match["role"] == "director" and match["code"] == "rejected", lines[0]
    assert "THINKING_LEVEL_MINIMAL" in match["message"]  # the reason, so it is never "unknown"
    assert "role or profile settings" in match["fix"]
    assert "Traceback" not in result.everything


def test_PL_LIVE_07_a_400_message_never_prints_a_token_or_an_authorization_header(tmp_path: Path) -> None:
    token, bearer, key = fake_secret("access_token"), fake_secret("bearer"), fake_secret("api_key")
    message = f"{REJECTED_THINKING[1]}. Authorization: {bearer} token={token} key={key}"
    result, _ = _rejected_run(tmp_path, REJECTED_THINKING[0], message)
    assert result.code == 1
    lines = result.err_lines()
    assert len(lines) == 1 and FAIL_RE.match(lines[0]) and FAIL_RE.match(lines[0])["code"] == "rejected"
    for secret in (token, bearer, bearer.split(" ", 1)[1], key, "Authorization"):
        assert secret not in result.everything


def test_PL_LIVE_07_a_400_reason_is_one_line_and_capped_at_200_characters(tmp_path: Path) -> None:
    long_reason = "x" * 400 + "\nsecond line"
    result, _ = _rejected_run(tmp_path, 400, long_reason)
    lines = result.err_lines()
    assert len(lines) == 1, lines
    match = FAIL_RE.match(lines[0])
    assert match and match["code"] == "rejected"
    assert "x" * 200 in match["message"] and "x" * 201 not in match["message"]
    assert "second line" not in result.everything


def test_PL_LIVE_07_other_failure_codes_still_print_no_server_text(tmp_path: Path) -> None:
    result, _ = _rejected_run(tmp_path, 403, "Permission denied: SERVER-TEXT-MARKER [PERMISSION_DENIED]")
    assert FAIL_RE.match(result.err_lines()[0])["code"] == "permission"
    assert "SERVER-TEXT-MARKER" not in result.everything


OPAQUE = "OpaqueValue" + "0123456789abcdef"  # not credential-shaped on purpose: only the label around it gives it away
LEAKY_SHAPES = [
    pytest.param(f'Authorization: "Bearer {OPAQUE}"', id="quoted-authorization"),
    pytest.param('{\\"Authorization\\":\\"Bearer ' + OPAQUE + '\\"}', id="escaped-json-authorization"),
    pytest.param(f"access_token={OPAQUE}", id="access_token"),
    pytest.param(f"refresh_token: {OPAQUE}", id="refresh_token"),
    pytest.param(f"api_key={OPAQUE}", id="api_key"),
    pytest.param(f"apiKey={OPAQUE}", id="apiKey"),
    pytest.param(f"client_secret={OPAQUE}", id="client_secret"),
    pytest.param(f'{{"token": "{OPAQUE}"}}', id="json-token"),
    pytest.param(f'{{"key": "{OPAQUE}"}}', id="json-key"),
    pytest.param(f"X-Goog-Signature={OPAQUE}", id="signed-url-signature"),
    pytest.param(f"Author\u200bization: Bearer {OPAQUE}", id="zero-width-in-label"),
    pytest.param("ya\u200b" + "29." + OPAQUE, id="zero-width-in-token"),
]


@pytest.mark.parametrize("leak", LEAKY_SHAPES)
def test_PL_LIVE_07_a_400_reason_scrubs_labelled_values_in_every_common_shape(leak: str, tmp_path: Path) -> None:
    result, _ = _rejected_run(tmp_path, 400, f"Request rejected. {leak} End.")
    lines = result.err_lines()
    assert len(lines) == 1 and FAIL_RE.match(lines[0])["code"] == "rejected"
    assert OPAQUE not in result.everything


def test_PL_LIVE_07_a_400_reason_drops_terminal_control_and_format_characters(tmp_path: Path) -> None:
    message = "Bad setting \x1b]52;c;ZGF0YQ==\x07 \x1b[2K \x08 \u202e reversed \u200b zero."
    result, _ = _rejected_run(tmp_path, 400, message)
    line = result.err_lines()[0]
    assert FAIL_RE.match(line) and "Bad setting" in line
    assert not any(ord(c) < 32 or 127 <= ord(c) < 160 or c in "\u202e\u200b" for c in result.err.rstrip("\n"))


def test_PL_LIVE_07_a_rejected_request_with_no_server_reason_still_prints_a_clean_line() -> None:
    module = smoke()
    from tilo_providers.errors import RequestError  # noqa: PLC0415

    assert module.classify(RequestError("plain")) == "rejected"
    assert module._reason(RequestError("plain")) == ""


def test_PL_LIVE_07_a_400_whose_text_looks_like_another_failure_is_still_rejected(tmp_path: Path) -> None:
    result, _ = _rejected_run(tmp_path, 400, "The field is disabled. [NOT_FOUND] [PERMISSION_DENIED]")
    assert FAIL_RE.match(result.err_lines()[0])["code"] == "rejected"
