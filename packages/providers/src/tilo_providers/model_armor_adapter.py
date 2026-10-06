"""tilo_providers.model_armor_adapter — the Model Armor `SafetyProvider` (FR-INT-02, PRD 16.3 item 2).

REST `:sanitizeUserPrompt` on the regional endpoint, user ADC bearer token. The profile's `model` is the
template id; project and location come from the environment (see `safety._build_live_safety_provider`).
Fails closed: a MATCH_FOUND anywhere is flagged with a fixed category; clean only when NO_MATCH_FOUND,
invocation SUCCESS, `pi_and_jailbreak` present and every filter entry reports EXECUTION_SUCCESS (Google's REST
omits default enums, so a missing `executionState` is never read as "ran"); everything else raises a
`ProviderError`. Messages never carry the token, the screened text or the response body."""

from __future__ import annotations

import base64
import json
import os
import re
import threading
from collections.abc import Callable
from typing import Any

import httpx

from tilo_providers.config import ProviderConfigError
from tilo_providers.errors import ProviderError, map_http_status, map_transport_error
from tilo_providers.google_adapter import _GOOGLE_SECRET_RE, refuse_service_account_key
from tilo_providers.interfaces import SafetyProvider, SafetyResult
from tilo_providers.safety import enforce_input_cap

# URL components: fullmatch only, so a trailing newline, a dot, a slash or a colon never reaches the URL.
_LOCATION_RE = re.compile(r"[a-z]+-[a-z]+[0-9]+")
_PROJECT_RE = re.compile(r"[a-z][a-z0-9-]{4,28}[a-z0-9]")
_TEMPLATE_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]{0,62}")
_TOKEN_RE = re.compile(r"[\x21-\x7e]+")  # visible ASCII only: no space, CR/LF or control character in a header
_SCOPES = ["https://www.googleapis.com/auth/cloud-platform"]
_BYTE_DATA_TYPES = {"application/pdf": "PDF", "image/png": "IMAGE", "image/jpeg": "IMAGE"}
# First match wins when several filters match: the most security-relevant category first.
_FILTER_CATEGORIES = (
    ("pi_and_jailbreak", "prompt_injection"),
    ("sdp", "sensitive_data"),
    ("rai", "unsafe_content"),
    ("csam", "unsafe_content"),
)


class _AdcTokens:
    """User ADC (never a service-account key file), refreshed when invalid. Built lazily; the credentials'
    quota project (if any) is exposed so user ADC is billed to it instead of getting a 403."""

    def __init__(self) -> None:
        self._credentials: Any = None
        self._lock = threading.Lock()
        self.quota_project_id: str | None = None

    def __call__(self) -> str:
        with self._lock:
            if self._credentials is None:
                refuse_service_account_key()
                import google.auth  # noqa: PLC0415

                self._credentials, _ = google.auth.default(scopes=_SCOPES)
                self.quota_project_id = getattr(self._credentials, "quota_project_id", None)
            if not self._credentials.valid:
                from google.auth.transport.requests import Request  # noqa: PLC0415

                self._credentials.refresh(Request())
            return self._credentials.token


def _duplicate_key_free(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    keys = [key for key, _ in pairs]
    if len(set(keys)) != len(keys):
        raise ProviderError("FR-INT-02: Model Armor returned a response with a duplicate key; failing closed")
    return dict(pairs)


def _walk(node: Any) -> Any:
    """Yields every dict under `node` (iterative: a hostile, deeply nested body cannot recurse)."""
    stack = [node]
    while stack:
        current = stack.pop()
        if isinstance(current, dict):
            yield current
            stack.extend(current.values())
        elif isinstance(current, list):
            stack.extend(current)


def _matched_categories(filter_results: Any) -> list[str]:
    """The fixed category of every filter reporting MATCH_FOUND anywhere under it, most serious first."""
    if not isinstance(filter_results, dict):
        return []
    matched = {
        key
        for key, detail in filter_results.items()
        if any(node.get("matchState") == "MATCH_FOUND" for node in _walk(detail))
    }
    known = {key for key, _ in _FILTER_CATEGORIES}
    return [category for key, category in _FILTER_CATEGORIES if key in matched] + (["other"] if matched - known else [])


def _every_filter_ran(filter_results: Any) -> bool:
    """`pi_and_jailbreak` present, and every filter entry carries an executionState, all EXECUTION_SUCCESS."""
    if not isinstance(filter_results, dict) or "pi_and_jailbreak" not in filter_results:
        return False
    for detail in filter_results.values():
        states = [node["executionState"] for node in _walk(detail) if "executionState" in node]
        if not states or any(state != "EXECUTION_SUCCESS" for state in states):
            return False
    return True


def _verdict(body: Any) -> SafetyResult:
    result = body.get("sanitizationResult") if isinstance(body, dict) else None
    if isinstance(result, dict):
        filter_results = result.get("filterResults")
        categories = _matched_categories(filter_results)
        if categories:  # a match under any filter is flagged, even when the overall state says otherwise
            return {"flagged": True, "reason": categories[0]}
        if result.get("filterMatchState") == "MATCH_FOUND":
            return {"flagged": True, "reason": "other"}
        if (
            result.get("filterMatchState") == "NO_MATCH_FOUND"
            and result.get("invocationResult") == "SUCCESS"
            and _every_filter_ran(filter_results)
        ):
            return {"flagged": False, "reason": None}
    raise ProviderError("FR-INT-02: Model Armor returned a result that cannot be read as clean; failing closed")


class ModelArmorSafetyProvider(SafetyProvider):
    def __init__(
        self,
        *,
        profile_id: str,
        template_id: str,
        project: str,
        location: str,
        transport: httpx.BaseTransport | None = None,
        token_provider: Callable[[], str] | None = None,
        timeout_s: float = 10.0,
        max_input_tokens: int | None = None,
    ) -> None:
        for name, value, pattern in (
            ("location", location, _LOCATION_RE),
            ("project", project, _PROJECT_RE),
            ("template id", template_id, _TEMPLATE_RE),
        ):
            if not pattern.fullmatch(value):
                raise ProviderConfigError(f"FR-INT-02: the Model Armor {name} for {profile_id!r} is not valid")
        if transport is None and os.environ.get("LIVE") != "1":  # EFF-01: reachable directly, not only via replay
            raise ProviderConfigError("FR-INT-02/EFF-01: refusing to build a real Model Armor client without LIVE=1")
        self._max_input_tokens = max_input_tokens
        self._url = (
            f"https://modelarmor.{location}.rep.googleapis.com/v1/projects/{project}"
            f"/locations/{location}/templates/{template_id}:sanitizeUserPrompt"
        )
        # Redirects are never followed and the environment's proxy settings are ignored.
        self._client = httpx.Client(transport=transport, timeout=timeout_s, trust_env=False)
        self._token_provider = token_provider or _AdcTokens()
        self._last_token_re = re.compile(r"(?!)")  # matches nothing until a token has been used

    def _headers(self) -> dict[str, str]:
        failure: ProviderError | None = None
        token: Any = None
        try:
            token = self._token_provider()
        except ProviderConfigError:
            raise
        except Exception as exc:
            failure = ProviderError(f"FR-INT-02: no Google credentials for Model Armor ({type(exc).__name__})")
        if failure is None and not (isinstance(token, str) and _TOKEN_RE.fullmatch(token)):
            failure = ProviderError("FR-INT-02: Model Armor credentials produced no usable token")
        if failure is not None:
            raise failure  # outside the except block: nothing rides along as __context__
        self._last_token_re = re.compile(re.escape(token))
        headers = {"Authorization": f"Bearer {token}"}
        quota_project = getattr(self._token_provider, "quota_project_id", None)
        if quota_project is not None:
            if not (isinstance(quota_project, str) and _PROJECT_RE.fullmatch(quota_project)):
                raise ProviderError("FR-INT-02: the credentials' quota project is not a valid project id")
            headers["x-goog-user-project"] = quota_project
        return headers

    def _sanitize(self, user_prompt_data: dict[str, Any]) -> SafetyResult:
        headers = self._headers()
        failure: ProviderError | None = None
        try:
            response = self._client.post(self._url, headers=headers, json={"userPromptData": user_prompt_data})
        except httpx.HTTPError as exc:
            failure = map_transport_error(exc) or ProviderError("FR-INT-02: Model Armor request failed")
        if failure is not None:
            raise failure  # raised outside the except block, so the request and its bearer header are not __context__
        if response.status_code != 200:  # any other 2xx, and every 3xx, is not a verdict
            raise map_http_status(response.status_code, f"FR-INT-02: Model Armor returned HTTP {response.status_code}")
        try:
            body = json.loads(response.content, object_pairs_hook=_duplicate_key_free)
        except (ValueError, RecursionError):  # ValueError includes UnicodeDecodeError
            body = None
        return _verdict(body)

    def _check(self, text: str, *, content: bytes | None, mime_type: str | None) -> SafetyResult:
        enforce_input_cap(text, content, self._max_input_tokens)  # EFF-03: before any request
        if not text and content is None:
            return {"flagged": False, "reason": None}  # nothing to screen: no paid call
        parts: list[dict[str, Any]] = []
        if text:
            parts.append({"text": text})
        if content is not None:
            data_type = _BYTE_DATA_TYPES[mime_type or ""]
            parts.append({"byteItem": {"byteDataType": data_type, "byteData": base64.b64encode(content).decode()}})
        # Every part is screened (an error in any raises); flagged if any part is flagged.
        results = [self._sanitize(part) for part in parts]
        return next((r for r in results if r["flagged"]), results[0])

    def redact(self, text: str) -> str:
        return self._last_token_re.sub("[REDACTED]", _GOOGLE_SECRET_RE.sub("[REDACTED]", text))
