"""tilo_providers.vertex_eval_adapter — the Gen AI evaluation service `EvalProvider` (VERTEX-EVAL-1, ADR-0033).

REST `:evaluateInstances` on the configured endpoint, user ADC bearer token, custom rubrics only (the template is sent
as `metricPromptTemplate`, as is). One instance a call, `samplingCount` 1, `flipEnabled` false: no hidden repeat.
`model` is the judge the service is told to use (`autoraterConfig.autoraterModel`). Fails closed: a missing or
unknown choice, a non-finite score, duplicate keys or non-JSON raise `ProviderError`. Messages never carry the
token, the request or the response body. Field names follow the v1 REST reference (BQ-VEVAL-3)."""

from __future__ import annotations

import json
import math
import os
import re
from collections.abc import Callable
from typing import Any, Literal

import httpx

from tilo_providers.config import ProviderConfigError
from tilo_providers.diagnostics import log_caught
from tilo_providers.errors import ProviderError, map_http_status, map_transport_error
from tilo_providers.google_adapter import _GOOGLE_SECRET_RE, GoogleSettingsError
from tilo_providers.interfaces import EvalProvider, EvalRequest, EvalScore
from tilo_providers.model_armor_adapter import _AdcTokens, _duplicate_key_free

# URL components: fullmatch only, so a trailing newline, a dot, a slash or a colon never reaches the URL.
_LOCATION_RE = re.compile(r"global|[a-z]+-[a-z]+[0-9]+")
_PROJECT_RE = re.compile(r"[a-z][a-z0-9-]{4,28}[a-z0-9]")
_MODEL_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,98}")
_TOKEN_RE = re.compile(r"[\x21-\x7e]+")  # visible ASCII only: no space, CR/LF or control character in a header
_CHOICES: dict[str, Literal["candidate", "baseline", "tie"]] = {
    "CANDIDATE": "candidate",
    "BASELINE": "baseline",
    "TIE": "tie",
}
_EXPLANATION_CAP = 500


class VertexEvalProvider(EvalProvider):
    def __init__(
        self,
        *,
        profile_id: str,
        model: str,
        project: str,
        location: str,
        transport: httpx.BaseTransport | None = None,
        token: Callable[[], str] | None = None,
        timeout_s: float = 60.0,
        live_permitted: bool = False,
    ) -> None:
        for name, value, pattern in (
            ("location", location, _LOCATION_RE),
            ("project", project, _PROJECT_RE),
            ("model", model, _MODEL_RE),
        ):
            if not pattern.fullmatch(value):
                raise ProviderConfigError(f"VERTEX-EVAL-1: the eval judge {name} for {profile_id!r} is not valid")
        if transport is None and not live_permitted and os.environ.get("LIVE") != "1":  # EFF-01
            raise ProviderConfigError(
                "VERTEX-EVAL-1/EFF-01: refusing to build a real eval client without the live switch"
            )
        self._location = location
        self._project = project
        self._model = model
        host = "aiplatform.googleapis.com" if location == "global" else f"{location}-aiplatform.googleapis.com"
        self._url = f"https://{host}/v1/projects/{project}/locations/{location}:evaluateInstances"
        # Redirects are never followed and the environment's proxy settings are ignored.
        self._client = httpx.Client(transport=transport, timeout=timeout_s, trust_env=False)
        self._token = token or _AdcTokens()
        self._last_token_re = re.compile(r"(?!)")  # matches nothing until a token has been used

    def _headers(self) -> dict[str, str]:
        failure: ProviderError | None = None
        token: Any = None
        try:
            token = self._token()
        except (ProviderConfigError, GoogleSettingsError) as caught_error:
            log_caught(caught_error, __name__, locals())
            raise
        except Exception as exc:
            log_caught(exc, __name__, locals())
            failure = ProviderError(f"VERTEX-EVAL-1: no Google credentials for the eval service ({type(exc).__name__})")
        if failure is None and not (isinstance(token, str) and _TOKEN_RE.fullmatch(token)):
            failure = ProviderError("VERTEX-EVAL-1: eval credentials produced no usable token")
        if failure is not None:
            raise failure  # outside the except block: nothing rides along as __context__
        self._last_token_re = re.compile(re.escape(token))
        headers = {"Authorization": f"Bearer {token}"}
        quota_project = getattr(self._token, "quota_project_id", None)
        if quota_project is not None:
            if not (isinstance(quota_project, str) and _PROJECT_RE.fullmatch(quota_project)):
                raise ProviderError("VERTEX-EVAL-1: the credentials' quota project is not a valid project id")
            headers["x-goog-user-project"] = quota_project
        return headers

    def _body(self, request: EvalRequest) -> dict[str, Any]:
        item = request.item
        instance: dict[str, str] = {"prompt": item.prompt, "context": item.context, "response": item.response}
        if request.kind == "pairwise":
            instance["baseline_model_response"] = item.baseline_response or ""
        model = f"projects/{self._project}/locations/{self._location}/publishers/google/models/{self._model}"
        return {
            f"{request.kind}MetricInput": {
                "metricSpec": {"metricPromptTemplate": request.template},
                "instance": {"jsonInstance": json.dumps(instance)},
            },
            "autoraterConfig": {"autoraterModel": model, "samplingCount": 1, "flipEnabled": False},
        }

    def _evaluate(self, request: EvalRequest) -> EvalScore:
        headers = self._headers()
        failure: ProviderError | None = None
        try:
            response = self._client.post(self._url, headers=headers, json=self._body(request))
        except httpx.HTTPError as exc:
            log_caught(exc, __name__, locals())
            failure = map_transport_error(exc) or ProviderError("VERTEX-EVAL-1: eval request failed")
        if failure is not None:
            raise failure  # raised outside the except block, so the request and its bearer header are not __context__
        if response.status_code != 200:  # any other 2xx, and every 3xx, is not a verdict
            raise map_http_status(
                response.status_code, f"VERTEX-EVAL-1: eval service returned HTTP {response.status_code}"
            )
        try:
            body = json.loads(response.content, object_pairs_hook=_duplicate_key_free)
        except (ValueError, RecursionError, ProviderError) as caught_error:  # ValueError includes UnicodeDecodeError
            log_caught(caught_error, __name__, locals())
            body = None
        return self._score(request.kind, body)

    def _score(self, kind: str, body: Any) -> EvalScore:
        result = body.get(f"{kind}MetricResult") if isinstance(body, dict) else None
        explanation = result.get("explanation") if isinstance(result, dict) else None
        text = self.redact(explanation)[:_EXPLANATION_CAP] if isinstance(explanation, str) else ""  # redact, then cap
        if isinstance(result, dict) and kind == "pairwise":
            choice = result.get("pairwiseChoice")
            if isinstance(choice, str) and choice in _CHOICES:
                return EvalScore(choice=_CHOICES[choice], explanation=text)
        elif isinstance(result, dict):
            score = result.get("score")
            if isinstance(score, int | float) and not isinstance(score, bool) and math.isfinite(score):
                return EvalScore(score=float(score), explanation=text)
        raise ProviderError("VERTEX-EVAL-1: the eval service returned a result that cannot be read; failing closed")

    def redact(self, text: str) -> str:
        return self._last_token_re.sub("[REDACTED]", _GOOGLE_SECRET_RE.sub("[REDACTED]", text))
