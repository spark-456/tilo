"""tilo_providers.model_armor_adapter — the Model Armor `SafetyProvider` (FR-INT-02, PRD 16.3 item 2).

REST `:sanitizeUserPrompt` on the regional endpoint, user ADC bearer token. The profile's `model` is the
template id; project and location come from the environment (see `safety._build_live_safety_provider`).
Fails closed: only NO_MATCH_FOUND with invocation SUCCESS and every filter EXECUTION_SUCCESS is clean,
MATCH_FOUND is flagged with a fixed category, and everything else raises a `ProviderError`. Messages never
carry the token, the screened text or the response body."""

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
from tilo_providers.google_adapter import refuse_service_account_key
from tilo_providers.interfaces import SafetyProvider, SafetyResult

# URL components: fullmatch only, so a trailing newline, a dot, a slash or a colon never reaches the URL.
_LOCATION_RE = re.compile(r"[a-z]+-[a-z]+[0-9]+")
_PROJECT_RE = re.compile(r"[a-z][a-z0-9-]{4,28}[a-z0-9]")
_TEMPLATE_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]{0,62}")
_SCOPES = ["https://www.googleapis.com/auth/cloud-platform"]
_BYTE_DATA_TYPES = {"application/pdf": "PDF", "image/png": "IMAGE", "image/jpeg": "IMAGE"}
# First match wins when several filters match: the most security-relevant category first.
_FILTER_CATEGORIES = (
    ("pi_and_jailbreak", "prompt_injection"),
    ("sdp", "sensitive_data"),
    ("rai", "unsafe_content"),
    ("csam", "unsafe_content"),
)


def _default_token_provider() -> Callable[[], str]:
    """User ADC (never a service-account key file), refreshed when invalid. Built lazily."""
    state: dict[str, Any] = {}
    lock = threading.Lock()

    def token() -> str:
        with lock:
            if "credentials" not in state:
                refuse_service_account_key()
                import google.auth  # noqa: PLC0415

                state["credentials"], _ = google.auth.default(scopes=_SCOPES)
            credentials = state["credentials"]
            if not credentials.valid:
                from google.auth.transport.requests import Request  # noqa: PLC0415

                credentials.refresh(Request())
            return credentials.token

    return token


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


def _category(filter_results: Any) -> str:
    if isinstance(filter_results, dict):
        matched = {
            key
            for key, detail in filter_results.items()
            if any(node.get("matchState") == "MATCH_FOUND" for node in _walk(detail))
        }
        for key, category in _FILTER_CATEGORIES:
            if key in matched:
                return category
    return "other"


def _verdict(body: Any) -> SafetyResult:
    result = body.get("sanitizationResult") if isinstance(body, dict) else None
    state = result.get("filterMatchState") if isinstance(result, dict) else None
    if state == "MATCH_FOUND":
        return {"flagged": True, "reason": _category(result.get("filterResults"))}
    if state == "NO_MATCH_FOUND" and result.get("invocationResult") == "SUCCESS":
        executions = [node["executionState"] for node in _walk(result.get("filterResults")) if "executionState" in node]
        if all(execution == "EXECUTION_SUCCESS" for execution in executions):
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
        self._profile_id = profile_id
        self._url = (
            f"https://modelarmor.{location}.rep.googleapis.com/v1/projects/{project}"
            f"/locations/{location}/templates/{template_id}:sanitizeUserPrompt"
        )
        self._client = httpx.Client(transport=transport, timeout=timeout_s)  # redirects are never followed
        self._token_provider = token_provider or _default_token_provider()
        self._last_token: str | None = None

    def _bearer(self) -> str:
        try:
            token = self._token_provider()
        except ProviderConfigError:
            raise
        except Exception as exc:
            raise ProviderError(f"FR-INT-02: no Google credentials for Model Armor ({type(exc).__name__})") from None
        if not isinstance(token, str) or not token or any(c in token for c in "\r\n"):
            raise ProviderError("FR-INT-02: Model Armor credentials produced no usable token")
        self._last_token = token
        return f"Bearer {token}"

    def _sanitize(self, user_prompt_data: dict[str, Any]) -> SafetyResult:
        headers = {"Authorization": self._bearer()}
        try:
            response = self._client.post(self._url, headers=headers, json={"userPromptData": user_prompt_data})
        except httpx.HTTPError as exc:
            raise (map_transport_error(exc) or ProviderError("FR-INT-02: Model Armor request failed")) from None
        if not 200 <= response.status_code < 300:
            raise map_http_status(response.status_code, f"FR-INT-02: Model Armor returned HTTP {response.status_code}")
        try:
            body = json.loads(response.content)
        except (ValueError, RecursionError):  # ValueError includes UnicodeDecodeError
            body = None
        return _verdict(body)

    def _check(self, text: str, *, content: bytes | None, mime_type: str | None) -> SafetyResult:
        parts: list[dict[str, Any]] = []
        if text or content is None:
            parts.append({"text": text})
        if content is not None:
            data_type = _BYTE_DATA_TYPES[mime_type or ""]
            parts.append({"byteItem": {"byteDataType": data_type, "byteData": base64.b64encode(content).decode()}})
        # Every part is screened (an error in any raises); flagged if any part is flagged.
        results = [self._sanitize(part) for part in parts]
        return next((r for r in results if r["flagged"]), results[0])

    def redact(self, text: str) -> str:
        return text.replace(self._last_token, "[REDACTED]") if self._last_token else text
