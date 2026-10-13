"""VERTEX-EVAL-1, PR 1a (live adapter half): the Gen AI evaluation service adapter, tested on mocks only
(docs/design/VERTEX-EVAL-1.md section 2.3 and tests 7-14; ADR-0033; PRD 6.3, 6.6 EFF-01, 16.1 rule 4).

Public interface under test: `tilo_providers.vertex_eval_adapter.VertexEvalProvider` (class name and constructor
keywords are this file's reading of the design; every test builds it through `_provider`, so a different name
is a one-line change), driven through `EvalProvider.evaluate()`. Tests inject an `httpx.MockTransport` and a fake
`token` callable; `google.auth.default` is patched to raise in every test (design 4, point 5), so no network and
no ADC are touched.

Ambiguities resolved (listed in the report):
- Class `VertexEvalProvider(*, profile_id, model, project, location, transport=None, token=None, timeout_s=...)`,
  after `ModelArmorSafetyProvider`; `model` is `profile.model`, the judge the service is told to use.
- The explanation sits inside the metric result (`pairwiseMetricResult.explanation`,
  `pointwiseMetricResult.explanation`), as in the v1 REST reference the design cites; `autoraterConfig` is a
  top-level body field next to `pairwiseMetricInput` / `pointwiseMetricInput`.
- Location accepts regions only (`asia-southeast1` shape), like Model Armor's pattern; `global` is not tested.
- A 3xx or a non-200 2xx is not a verdict: any `ProviderError`.
- The "explanation is redacted, then capped at 500" test pins the order with an API key that straddles the cut.
- `build_eval_provider(..., live_permitted=True)` builds the live adapter without the live switch and without any
  ADC use (SEC-15); the adapter is spied on through its constructor keywords.
"""

from __future__ import annotations

import json
import traceback
from collections.abc import Callable
from typing import Any, cast

import httpx
import pytest
from conftest import build_providers_config, prices_config_for
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st
from tilo_providers.config import ProviderConfigError
from tilo_providers.errors import ProviderError, QuotaError, RequestError, RetryableError
from tilo_providers.google_adapter import GoogleSettingsError

# Fake secrets are assembled at runtime (CLAUDE.md: no secrets in fixtures).
TOKEN = "ya29." + "fakeToken" + "".join(str(n) for n in range(12))
API_KEY = "AIza" + "Sy" + "".join(chr(ord("a") + n % 26) for n in range(37))
BODY_SECRET = "response-body-" + "".join(chr(ord("a") + n) for n in range(10)) + "-SECRET"
SA_TYPE = "service" + "_account"

PROJECT = "demo-tilo-test"
LOCATION = "asia-southeast1"
MODEL = "fake-judge-1"
TEMPLATE = "Rubric {{prompt}} vs {{response}}\nline two é ✓  \n"  # sent as is, byte for byte
URL = f"https://{LOCATION}-aiplatform.googleapis.com/v1/projects/{PROJECT}/locations/{LOCATION}:evaluateInstances"

Handler = Callable[[httpx.Request], httpx.Response]


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch, tmp_path):
    for name in (
        "LIVE",
        "TILO_RECORD",
        "K_SERVICE",
        "CLOUD_RUN_JOB",
        "GOOGLE_CLOUD_PROJECT",
        "TILO_VERTEX_EVAL_LOCATION",
        "GOOGLE_APPLICATION_CREDENTIALS",
        "GOOGLE_API_KEY",
    ):
        monkeypatch.delenv(name, raising=False)
    # never read the developer's own gcloud ADC file when a test reaches the key-file refusal
    monkeypatch.setenv("CLOUDSDK_CONFIG", str(tmp_path / "no-gcloud"))


@pytest.fixture(autouse=True)
def adc_calls(monkeypatch) -> list[str]:
    """`google.auth.default` raises in every test; the list shows whether it was ever reached."""
    import google.auth  # noqa: PLC0415

    calls: list[str] = []

    def boom(*args: Any, **kwargs: Any) -> Any:
        calls.append("default")
        raise AssertionError("VERTEX-EVAL-1: a test reached google.auth.default (no ADC in tests)")

    monkeypatch.setattr(google.auth, "default", boom)
    return calls


# --- builders -----------------------------------------------------------------------------------


class _Calls:
    def __init__(self) -> None:
        self.requests: list[httpx.Request] = []

    def bodies(self) -> list[dict[str, Any]]:
        return [json.loads(r.content) for r in self.requests]


def _item(**overrides: Any):
    from tilo_providers.interfaces import EvalItem  # noqa: PLC0415

    fields: dict[str, Any] = {
        "id": "case-1",
        "prompt": "Plan a launch for the spring sale",
        "context": "notes.txt: budget is 5000",
        "response": "candidate plan",
    }
    fields.update(overrides)
    return EvalItem(**fields)


def _request(kind: str = "pairwise", *, template: str = TEMPLATE, **item_overrides: Any):
    from tilo_providers.interfaces import EvalRequest  # noqa: PLC0415

    if kind == "pairwise" and "baseline_response" not in item_overrides:
        item_overrides["baseline_response"] = "baseline plan"
    return EvalRequest(
        metric="plan_pairwise" if kind == "pairwise" else "plan_groundedness",
        kind=cast("Any", kind),  # the tests also pass invalid kinds
        template=template,
        item=_item(**item_overrides),
    )


def _pairwise_body(choice: Any = "CANDIDATE", **result: Any) -> dict[str, Any]:
    return {"pairwiseMetricResult": {"pairwiseChoice": choice, "explanation": "judge says so", **result}}


def _pointwise_body(score: Any = 1.0, **result: Any) -> dict[str, Any]:
    return {"pointwiseMetricResult": {"score": score, "explanation": "judge says so", **result}}


def _provider(
    handler: Handler | None = None,
    *,
    kind: str = "pairwise",
    token: str | Callable[[], str] = TOKEN,
    calls: _Calls | None = None,
    **overrides: Any,
):
    """Returns (provider, calls). `handler` defaults to a usable verdict for `kind`."""
    from tilo_providers.vertex_eval_adapter import VertexEvalProvider  # noqa: PLC0415

    calls = calls if calls is not None else _Calls()
    default = _pairwise_body() if kind == "pairwise" else _pointwise_body()
    respond = handler if handler is not None else (lambda request: httpx.Response(200, json=default))

    def recording_handler(request: httpx.Request) -> httpx.Response:
        calls.requests.append(request)
        return respond(request)

    kwargs: dict[str, Any] = {
        "profile_id": "vertex-eval",
        "model": MODEL,
        "project": PROJECT,
        "location": LOCATION,
        "transport": httpx.MockTransport(recording_handler),
        "token": token if callable(token) else (lambda: token),
    }
    kwargs.update(overrides)
    return VertexEvalProvider(**kwargs), calls


def _bare_kwargs(**overrides: Any) -> dict[str, Any]:
    """Constructor keywords with no transport and no token: the live-looking build."""
    kwargs: dict[str, Any] = {"profile_id": "vertex-eval", "model": MODEL, "project": PROJECT, "location": LOCATION}
    kwargs.update(overrides)
    return kwargs


# --- (7) the live switch gate -------------------------------------------------------------------


def test_VERTEX_EVAL_1_adapter_refuses_without_live_switch_before_auth(monkeypatch, adc_calls):
    """EFF-01: without an injected transport the adapter needs the live switch, and refuses at construction,
    before google.auth is touched. A token callable alone is not an exemption."""
    from tilo_providers.vertex_eval_adapter import VertexEvalProvider  # noqa: PLC0415

    with pytest.raises(ProviderConfigError):
        VertexEvalProvider(**_bare_kwargs())
    with pytest.raises(ProviderConfigError):
        VertexEvalProvider(**_bare_kwargs(token=lambda: TOKEN))
    for value in ("0", "true", ""):
        monkeypatch.setenv("LIVE", value)
        with pytest.raises(ProviderConfigError):
            VertexEvalProvider(**_bare_kwargs())
    assert adc_calls == [], "ADC must not be reached before the gate"

    # a transport is the exemption the tests use (as in the other adapters)
    provider, _ = _provider()
    assert provider is not None


def test_VERTEX_EVAL_1_build_live_adapter_needs_the_live_switch_or_live_permitted(monkeypatch, adc_calls):
    from tilo_providers.evaluation import build_eval_provider  # noqa: PLC0415
    from tilo_providers.vertex_eval_adapter import VertexEvalProvider  # noqa: PLC0415

    config = _vertex_config()
    monkeypatch.setenv("GOOGLE_CLOUD_PROJECT", PROJECT)
    with pytest.raises(ProviderConfigError):  # no live switch, not permitted
        build_eval_provider(config)

    monkeypatch.setenv("LIVE", "1")
    assert isinstance(build_eval_provider(config), VertexEvalProvider)
    monkeypatch.delenv("LIVE")

    assert isinstance(build_eval_provider(config, live_permitted=True), VertexEvalProvider)  # SEC-15
    assert adc_calls == [], "building the adapter must not use ADC (it is lazy)"


def _vertex_config():
    models = {
        "example": True,
        "profiles": {
            "vertex-eval": {"provider": "vertex_eval", "model": MODEL, "context": 1_000_000, "caps": []},
        },
        "roles": {"eval_judge": {"primary": "vertex-eval", "fallback": "vertex-eval"}},
        "rules": {"deny": []},
    }
    return build_providers_config(models, prices_config_for({"vertex-eval": (0.5, 2.0)}))


def test_VERTEX_EVAL_1_build_live_adapter_reads_project_and_location_from_the_environment(monkeypatch):
    from tilo_providers import vertex_eval_adapter  # noqa: PLC0415
    from tilo_providers.evaluation import build_eval_provider  # noqa: PLC0415

    seen: list[dict[str, Any]] = []
    original = vertex_eval_adapter.VertexEvalProvider.__init__

    def spy(self: Any, *args: Any, **kwargs: Any) -> None:
        seen.append(kwargs)
        original(self, *args, **kwargs)

    monkeypatch.setattr(vertex_eval_adapter.VertexEvalProvider, "__init__", spy)
    config = _vertex_config()
    monkeypatch.setenv("LIVE", "1")

    with pytest.raises(ProviderConfigError):  # GOOGLE_CLOUD_PROJECT unset
        build_eval_provider(config)

    monkeypatch.setenv("GOOGLE_CLOUD_PROJECT", PROJECT)
    build_eval_provider(config)
    assert (seen[-1]["project"], seen[-1]["location"], seen[-1]["model"]) == (PROJECT, "asia-southeast1", MODEL)

    monkeypatch.setenv("TILO_VERTEX_EVAL_LOCATION", "us-central1")
    build_eval_provider(config)
    assert seen[-1]["location"] == "us-central1"

    for bad in ("evil.com/x", "asia-southeast1\n", "asia southeast1"):
        monkeypatch.setenv("TILO_VERTEX_EVAL_LOCATION", bad)
        with pytest.raises(ProviderConfigError):
            build_eval_provider(config)


# --- (8) credentials and URL components ---------------------------------------------------------

_BAD_LOCATIONS = [
    "evil.com/x",
    "asia-southeast1\n",
    "asia-southeast1.evil.com",
    "asia-southeast1/../x",
    "",
    "asia southeast1",
    "asia-southeast",
    "asia-southeast1@evil.com",
    "ASIA-SOUTHEAST1",
]
_BAD_PROJECTS = [
    "evil.com/x",
    "demo-tilo-test\n",
    "../",
    "a",
    "Demo-Project",
    "demo-project-",
    "1demo-project",
    "demo_project",
    "p" * 31,
    "",
]


@pytest.mark.parametrize("location", _BAD_LOCATIONS)
def test_VERTEX_EVAL_1_adapter_rejects_a_bad_location_before_any_request(location):
    calls = _Calls()
    with pytest.raises(ProviderConfigError):
        provider, _ = _provider(calls=calls, location=location)
        provider.evaluate(_request())
    assert calls.requests == []


@pytest.mark.parametrize("project", _BAD_PROJECTS)
def test_VERTEX_EVAL_1_adapter_rejects_a_bad_project_before_any_request(project):
    calls = _Calls()
    with pytest.raises(ProviderConfigError):
        provider, _ = _provider(calls=calls, project=project)
        provider.evaluate(_request())
    assert calls.requests == []


@pytest.mark.parametrize("location", ["asia-southeast1", "us-central1", "europe-west4"])
@pytest.mark.parametrize("project", ["demo-tilo-test", "essential-wares-510320-f0", "p" * 30, "abcde1"])
def test_VERTEX_EVAL_1_adapter_accepts_valid_url_components(location, project):
    provider, calls = _provider(location=location, project=project)
    provider.evaluate(_request())
    assert calls.requests[0].url.host == f"{location}-aiplatform.googleapis.com"
    assert calls.requests[0].url.path == f"/v1/projects/{project}/locations/{location}:evaluateInstances"


def test_VERTEX_EVAL_1_adapter_refuses_service_account_key_and_bad_location_or_project(
    monkeypatch, tmp_path, adc_calls
):
    """Design 2.3 auth: user ADC only. A key file (the variable's, or gcloud's well-known one) is refused through
    `refuse_service_account_key` before google.auth.default is reached and before any request is sent."""
    monkeypatch.setenv("LIVE", "1")

    key = tmp_path / "key.json"
    key.write_text(json.dumps({"type": SA_TYPE, "project_id": "demo"}), encoding="utf-8")
    monkeypatch.setenv("GOOGLE_APPLICATION_CREDENTIALS", str(key))
    with pytest.raises(GoogleSettingsError) as excinfo:
        provider = _live_looking_provider()
        provider.evaluate(_request())
    assert excinfo.value.code == "service_account_key"
    assert TOKEN not in str(excinfo.value)
    monkeypatch.delenv("GOOGLE_APPLICATION_CREDENTIALS")

    gcloud = tmp_path / "gcloud"
    gcloud.mkdir()
    (gcloud / "application_default_credentials.json").write_text(json.dumps({"type": SA_TYPE}), encoding="utf-8")
    monkeypatch.setenv("CLOUDSDK_CONFIG", str(gcloud))
    with pytest.raises(GoogleSettingsError) as excinfo:
        provider = _live_looking_provider()
        provider.evaluate(_request())
    assert excinfo.value.code == "service_account_key"

    assert adc_calls == [], "a key file is refused before google.auth.default"


def _live_looking_provider():
    from tilo_providers.vertex_eval_adapter import VertexEvalProvider  # noqa: PLC0415

    return VertexEvalProvider(**_bare_kwargs())


# --- (9)-(10) request bodies --------------------------------------------------------------------


@pytest.mark.parametrize("location", ["asia-southeast1", "us-central1"])
def test_VERTEX_EVAL_1_adapter_pairwise_request_body(location):
    provider, calls = _provider(location=location)

    provider.evaluate(_request("pairwise"))

    assert len(calls.requests) == 1, "one instance a call: one request, no hidden repeat"
    request = calls.requests[0]
    assert request.method == "POST"
    assert request.url.scheme == "https"
    assert request.url.host == f"{location}-aiplatform.googleapis.com"
    assert request.url.path == f"/v1/projects/{PROJECT}/locations/{location}:evaluateInstances"
    assert request.headers["authorization"] == f"Bearer {TOKEN}"
    assert request.headers["content-type"].startswith("application/json")

    body = calls.bodies()[0]
    assert set(body) == {"pairwiseMetricInput", "autoraterConfig"}
    metric_input = body["pairwiseMetricInput"]
    assert set(metric_input) == {"metricSpec", "instance"}
    assert metric_input["metricSpec"] == {"metricPromptTemplate": TEMPLATE}, "the rubric is sent as is"
    assert set(metric_input["instance"]) == {"jsonInstance"}
    assert json.loads(metric_input["instance"]["jsonInstance"]) == {
        "prompt": "Plan a launch for the spring sale",
        "context": "notes.txt: budget is 5000",
        "response": "candidate plan",
        "baseline_model_response": "baseline plan",
    }
    config = body["autoraterConfig"]
    assert config == {
        "autoraterModel": f"projects/{PROJECT}/locations/{location}/publishers/google/models/{MODEL}",
        "samplingCount": 1,
        "flipEnabled": False,
    }
    assert config["flipEnabled"] is False
    assert not isinstance(config["samplingCount"], bool)


def test_VERTEX_EVAL_1_adapter_pointwise_request_body():
    provider, calls = _provider(kind="pointwise")

    provider.evaluate(_request("pointwise", template="Is every statement supported? 0 or 1."))

    assert len(calls.requests) == 1
    assert calls.requests[0].url.path == f"/v1/projects/{PROJECT}/locations/{LOCATION}:evaluateInstances"
    body = calls.bodies()[0]
    assert set(body) == {"pointwiseMetricInput", "autoraterConfig"}
    metric_input = body["pointwiseMetricInput"]
    assert metric_input["metricSpec"] == {"metricPromptTemplate": "Is every statement supported? 0 or 1."}
    assert json.loads(metric_input["instance"]["jsonInstance"]) == {
        "prompt": "Plan a launch for the spring sale",
        "context": "notes.txt: budget is 5000",
        "response": "candidate plan",
    }
    assert body["autoraterConfig"] == {
        "autoraterModel": f"projects/{PROJECT}/locations/{LOCATION}/publishers/google/models/{MODEL}",
        "samplingCount": 1,
        "flipEnabled": False,
    }


@settings(max_examples=60, deadline=None, suppress_health_check=[HealthCheck.function_scoped_fixture])
@given(prompt=st.text(max_size=120), context=st.text(max_size=120), response=st.text(max_size=120))
def test_VERTEX_EVAL_1_adapter_instance_round_trips_any_text(prompt, context, response):
    """Invariant: whatever the three texts hold (quotes, braces, newlines, unicode), `jsonInstance` is valid JSON
    that gives them back unchanged, and the item id is never part of what is sent."""
    provider, calls = _provider(kind="pointwise")
    provider.evaluate(_request("pointwise", prompt=prompt, context=context, response=response))
    instance = json.loads(calls.bodies()[-1]["pointwiseMetricInput"]["instance"]["jsonInstance"])
    assert instance == {"prompt": prompt, "context": context, "response": response}


def test_VERTEX_EVAL_1_adapter_asks_the_token_callable_for_every_request():
    tokens = iter(["ya29." + "first" + "A" * 10, "ya29." + "second" + "B" * 10])
    provider, calls = _provider(token=lambda: next(tokens))
    provider.evaluate(_request())
    provider.evaluate(_request())
    assert [r.headers["authorization"] for r in calls.requests] == [
        "Bearer ya29." + "first" + "A" * 10,
        "Bearer ya29." + "second" + "B" * 10,
    ]


# --- (11) result mapping ------------------------------------------------------------------------


@pytest.mark.parametrize(("raw", "choice"), [("CANDIDATE", "candidate"), ("BASELINE", "baseline"), ("TIE", "tie")])
def test_VERTEX_EVAL_1_adapter_maps_choice_and_score(raw, choice):
    provider, _ = _provider(lambda request: httpx.Response(200, json=_pairwise_body(raw)))
    result = provider.evaluate(_request("pairwise"))
    assert result.choice == choice
    assert result.score is None
    assert result.explanation == "judge says so"


@pytest.mark.parametrize("raw", [0, 1, 0.0, 1.0, 0.5])
def test_VERTEX_EVAL_1_adapter_maps_a_pointwise_score(raw):
    provider, _ = _provider(lambda request: httpx.Response(200, json=_pointwise_body(raw)), kind="pointwise")
    result = provider.evaluate(_request("pointwise"))
    assert result.choice is None
    assert result.score == raw
    assert isinstance(result.score, float)
    assert result.explanation == "judge says so"


# --- (12) fail closed on an unusable result -----------------------------------------------------

_PAIRWISE_UNUSABLE: list[tuple[str, bytes]] = [
    ("empty object", b"{}"),
    ("empty result", json.dumps({"pairwiseMetricResult": {}}).encode()),
    ("choice unspecified", json.dumps(_pairwise_body("PAIRWISE_CHOICE_UNSPECIFIED")).encode()),
    ("choice unknown", json.dumps(_pairwise_body("WINNER")).encode()),
    ("choice lowercase", json.dumps(_pairwise_body("candidate")).encode()),
    ("choice null", json.dumps(_pairwise_body(None)).encode()),
    ("choice number", json.dumps(_pairwise_body(1)).encode()),
    ("choice list", json.dumps(_pairwise_body(["CANDIDATE"])).encode()),
    ("result null", json.dumps({"pairwiseMetricResult": None}).encode()),
    ("result not an object", json.dumps({"pairwiseMetricResult": "CANDIDATE"}).encode()),
    ("wrong kind: pointwise result", json.dumps(_pointwise_body(1.0)).encode()),
    ("top-level list", b"[]"),
    ("top-level null", b"null"),
    (
        "duplicate choice key",
        b'{"pairwiseMetricResult": {"pairwiseChoice": "TIE", "pairwiseChoice": "CANDIDATE", "explanation": "x"}}',
    ),
    (
        "duplicate result key",
        b'{"pairwiseMetricResult": {"pairwiseChoice": "TIE"}, "pairwiseMetricResult": {"pairwiseChoice": "BASELINE"}}',
    ),
    ("empty body", b""),
    ("not json", b"not json at all"),
    ("html", b"<html>502</html>"),
    ("bad utf-8", b"\xff\xfe\x00"),
    ("truncated json", b'{"pairwiseMetricResult": {'),
]

_POINTWISE_UNUSABLE: list[tuple[str, bytes]] = [
    ("empty object", b"{}"),
    ("empty result", json.dumps({"pointwiseMetricResult": {}}).encode()),
    ("score NaN", b'{"pointwiseMetricResult": {"score": NaN, "explanation": "x"}}'),
    ("score Infinity", b'{"pointwiseMetricResult": {"score": Infinity}}'),
    ("score -Infinity", b'{"pointwiseMetricResult": {"score": -Infinity}}'),
    ("score overflows to inf", b'{"pointwiseMetricResult": {"score": 1e999}}'),
    ("score string", json.dumps(_pointwise_body("1")).encode()),
    ("score true", json.dumps(_pointwise_body(True)).encode()),
    ("score null", json.dumps(_pointwise_body(None)).encode()),
    ("score list", json.dumps(_pointwise_body([1])).encode()),
    ("result null", json.dumps({"pointwiseMetricResult": None}).encode()),
    ("wrong kind: pairwise result", json.dumps(_pairwise_body("TIE")).encode()),
    ("duplicate score key", b'{"pointwiseMetricResult": {"score": 1, "score": 0}}'),
    ("not json", b"not json at all"),
    ("bad utf-8", b"\xff\xfe\x00"),
]


@pytest.mark.parametrize(("label", "content"), _PAIRWISE_UNUSABLE, ids=[label for label, _ in _PAIRWISE_UNUSABLE])
def test_VERTEX_EVAL_1_adapter_fails_closed_on_unusable_pairwise_result(label, content):
    secret_content = content + BODY_SECRET.encode()  # trailing junk is also unusable, and must not be echoed
    for body in (content, secret_content):
        provider, _ = _provider(lambda request, body=body: httpx.Response(200, content=body))
        with pytest.raises(ProviderError) as excinfo:
            provider.evaluate(_request("pairwise"))
        assert BODY_SECRET not in str(excinfo.value)
        assert TOKEN not in str(excinfo.value)


@pytest.mark.parametrize(("label", "content"), _POINTWISE_UNUSABLE, ids=[label for label, _ in _POINTWISE_UNUSABLE])
def test_VERTEX_EVAL_1_adapter_fails_closed_on_unusable_pointwise_result(label, content):
    provider, _ = _provider(lambda request: httpx.Response(200, content=content), kind="pointwise")
    with pytest.raises(ProviderError) as excinfo:
        provider.evaluate(_request("pointwise"))
    assert TOKEN not in str(excinfo.value)


# --- (13) HTTP and transport errors -------------------------------------------------------------


def _error_response(status: int) -> Handler:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            status, json={"error": {"message": f"denied for {BODY_SECRET} using {request.headers['authorization']}"}}
        )

    return handler


@pytest.mark.parametrize(
    ("status", "error_type"),
    [
        (400, RequestError),
        (401, RequestError),
        (403, RequestError),
        (404, RequestError),
        (429, QuotaError),
        (500, RetryableError),
        (503, RetryableError),
        (504, RetryableError),
    ],
)
def test_VERTEX_EVAL_1_adapter_maps_http_errors_without_echo(status, error_type):
    provider, calls = _provider(_error_response(status))

    with pytest.raises(error_type) as excinfo:
        provider.evaluate(_request("pairwise"))

    assert type(excinfo.value) is error_type
    assert len(calls.requests) == 1, "no hidden retry: one call, one charge"
    assert BODY_SECRET not in str(excinfo.value)
    assert TOKEN not in str(excinfo.value)
    chain = "".join(traceback.format_exception(excinfo.value))
    assert BODY_SECRET not in chain, "the server's response body must not ride along on the exception chain"
    assert TOKEN not in chain


@pytest.mark.parametrize("status", [204, 302])
def test_VERTEX_EVAL_1_adapter_a_redirect_or_other_success_code_is_not_a_verdict(status):
    body = _pairwise_body("CANDIDATE")
    provider, calls = _provider(lambda request: httpx.Response(status, json=body, headers={"location": "https://x/"}))
    with pytest.raises(ProviderError):
        provider.evaluate(_request("pairwise"))
    assert len(calls.requests) == 1, "a redirect is never followed"


@pytest.mark.parametrize("error", [httpx.ReadTimeout, httpx.ConnectError])
def test_VERTEX_EVAL_1_adapter_maps_transport_errors_without_echo(error):
    def handler(request: httpx.Request) -> httpx.Response:
        raise error(f"failed {TOKEN} {BODY_SECRET}", request=request)

    provider, _ = _provider(handler)
    with pytest.raises(RetryableError) as excinfo:
        provider.evaluate(_request("pairwise"))
    chain = "".join(traceback.format_exception(excinfo.value))
    assert TOKEN not in chain
    assert BODY_SECRET not in chain


# --- (14) explanation redaction and cap ---------------------------------------------------------


def test_VERTEX_EVAL_1_adapter_redacts_and_caps_explanation():
    """Design 2.3: `redact()` uses the Google secret pattern; the explanation is redacted first, then capped at 500
    characters, so a cut never leaves part of a secret."""
    # 1. a token and an API key inside a short explanation
    text = f"saw {TOKEN} and then {API_KEY} in the plan"
    provider, _ = _provider(lambda request: httpx.Response(200, json=_pairwise_body("TIE", explanation=text)))
    explanation = provider.evaluate(_request("pairwise")).explanation
    assert TOKEN not in explanation
    assert API_KEY not in explanation
    assert explanation.startswith("saw ")

    # 2. an explanation over the cap is cut to at most 500 characters
    long_text = "word " * 400
    provider, _ = _provider(lambda request: httpx.Response(200, json=_pairwise_body("TIE", explanation=long_text)))
    capped = provider.evaluate(_request("pairwise")).explanation
    assert 400 <= len(capped) <= 500

    # 3. a short explanation is left alone
    provider, _ = _provider(lambda request: httpx.Response(200, json=_pairwise_body("TIE", explanation="fine")))
    assert provider.evaluate(_request("pairwise")).explanation == "fine"

    # 4. redact BEFORE cap: a key that straddles character 500 leaves no fragment (cut first, the 16-character stub
    #    would be too short for the key pattern to match and would leak)
    straddling = "x" * 480 + API_KEY + " and more text " * 20
    provider, _ = _provider(lambda request: httpx.Response(200, json=_pairwise_body("TIE", explanation=straddling)))
    explanation = provider.evaluate(_request("pairwise")).explanation
    assert len(explanation) <= 500
    assert API_KEY[:12] not in explanation
    assert API_KEY[4:20] not in explanation

    # 5. the same for a pointwise result
    provider, _ = _provider(
        lambda request: httpx.Response(200, json=_pointwise_body(1.0, explanation=straddling)), kind="pointwise"
    )
    explanation = provider.evaluate(_request("pointwise")).explanation
    assert len(explanation) <= 500
    assert API_KEY[4:20] not in explanation


def test_VERTEX_EVAL_1_adapter_redact_removes_secrets_and_the_bearer_token():
    provider, _ = _provider()
    provider.evaluate(_request())  # the adapter has now used the token

    redacted = provider.redact(f"upstream said: Bearer {TOKEN}, again {TOKEN}, and {API_KEY}")
    assert TOKEN not in redacted
    assert API_KEY not in redacted
    assert "upstream said" in redacted
    assert provider.redact("nothing secret here") == "nothing secret here"
