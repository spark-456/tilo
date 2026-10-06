"""tilo_connectors.recording — record and replay Google HTTP traffic (EFF-01, SEC-14). API_FR_CON_04_05.md.

`ReplayTransport` serves recorded interactions and never opens a socket: a request nobody recorded is a
`ReplayMiss`, not a network call. `RecordingTransport` wraps a live transport (only under `LIVE=1`, which
only the user sets) and keeps every interaction scrubbed at the source, so a saved recording holds no
token. Addresses in a committed recording stay at example.com, example.net or example.org.
"""

from __future__ import annotations

import base64
import copy
import json as jsonlib
import os
import threading
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from .adapters import ApiResponse, Transport

RECORDING_FORMAT = "tilo.http-recording/1"
REDACTED = "REDACTED"

_SECRET_HEADERS = frozenset({"authorization", "proxy-authorization", "cookie", "set-cookie", "x-goog-api-key"})
_SECRET_PARAMS = frozenset({"access_token", "key", "oauth_token", "token", "code"})
_SECRET_KEYS = frozenset(
    {
        "access_token",
        "refresh_token",
        "id_token",
        "client_secret",
        "code",
        "code_verifier",
        "token",
        "assertion",
        "password",
    }
)


class ReplayMiss(Exception):
    """No unused recorded interaction matches, or the request carries no bearer token."""


def _scrub_json(value: Any) -> Any:
    if isinstance(value, dict):
        return {k: REDACTED if k in _SECRET_KEYS else _scrub_json(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_scrub_json(v) for v in value]
    return value


def _scrub_side(side: Mapping[str, Any], *, request: bool) -> dict[str, Any]:
    out = copy.deepcopy(dict(side))
    out["headers"] = {
        str(k).lower(): REDACTED if str(k).lower() in _SECRET_HEADERS else v
        for k, v in (side.get("headers") or {}).items()
    }
    if request:
        out["params"] = {k: REDACTED if k in _SECRET_PARAMS else v for k, v in (side.get("params") or {}).items()}
    out["json"] = _scrub_json(out.get("json"))
    return out


def scrub_interaction(interaction: Mapping[str, Any]) -> dict[str, Any]:
    """A scrubbed copy: secret headers, params and JSON keys (at any depth) become REDACTED."""
    return {
        "request": _scrub_side(interaction["request"], request=True),
        "response": _scrub_side(interaction["response"], request=False),
    }


def _param_text(value: Any) -> Any:
    if isinstance(value, list | tuple):
        return [str(v) for v in value]
    return str(value)


def _plain_params(params: Mapping[str, Any] | None) -> dict[str, Any]:
    """JSON-stable params: lists stay lists, None values are dropped."""
    return {
        str(k): list(v) if isinstance(v, list | tuple) else v for k, v in dict(params or {}).items() if v is not None
    }


class _RecordedResponse:
    def __init__(self, status: int, headers: Mapping[str, str], body: Any, content_b64: str | None) -> None:
        self.status_code = int(status)
        self.headers: Mapping[str, str] = {str(k).lower(): str(v) for k, v in headers.items()}
        self._json = copy.deepcopy(body)
        if body is not None:
            self.content = jsonlib.dumps(body).encode("utf-8")
        else:
            self.content = base64.b64decode(content_b64 or "")

    def json(self) -> Any:
        if self._json is None:
            raise ValueError("not a JSON response")
        return copy.deepcopy(self._json)


def _load(recording: Mapping[str, Any] | str | os.PathLike[str]) -> dict[str, Any]:
    if isinstance(recording, Mapping):
        data = copy.deepcopy(dict(recording))
    else:
        data = jsonlib.loads(Path(recording).read_text(encoding="utf-8"))
    if data.get("format") != RECORDING_FORMAT:
        raise ValueError(f"not a {RECORDING_FORMAT} recording")
    return data


class ReplayTransport:
    """A Transport that serves each recorded interaction once; never opens a socket."""

    def __init__(self, recording: Mapping[str, Any] | str | os.PathLike[str]) -> None:
        self._interactions: list[dict[str, Any]] = list(_load(recording)["interactions"])
        self._used: set[int] = set()
        self._lock = threading.Lock()

    def request(
        self,
        method: str,
        url: str,
        *,
        params: Mapping[str, Any] | None = None,
        headers: Mapping[str, str] | None = None,
        json: Any = None,
        content: bytes | None = None,
    ) -> ApiResponse:
        auth = {str(k).lower(): str(v) for k, v in (headers or {}).items()}.get("authorization", "")
        if not auth.startswith("Bearer ") or not auth[len("Bearer ") :].strip():
            raise ReplayMiss("a replayed request must carry a bearer token")
        live = {str(k): _param_text(v) for k, v in _plain_params(params).items()}
        with self._lock:
            best: tuple[int, int] | None = None  # (recorded param count, index)
            for index, interaction in enumerate(self._interactions):
                recorded = interaction["request"]
                if index in self._used or recorded["method"] != method.upper() or recorded["url"] != url:
                    continue
                wanted = {str(k): _param_text(v) for k, v in (recorded.get("params") or {}).items()}
                if any(live.get(k) != v for k, v in wanted.items()):
                    continue
                if recorded.get("json") is not None and recorded["json"] != json:
                    continue
                if best is None or len(wanted) > best[0]:
                    best = (len(wanted), index)
            if best is None:
                raise ReplayMiss(f"no unused recorded interaction matches {method.upper()} {url}")
            self._used.add(best[1])
            response = self._interactions[best[1]]["response"]
        return _RecordedResponse(
            response["status"], response.get("headers") or {}, response.get("json"), response.get("content_b64")
        )

    def unused(self) -> list[dict[str, Any]]:
        with self._lock:
            return [copy.deepcopy(it) for i, it in enumerate(self._interactions) if i not in self._used]


class RecordingTransport:
    """Wraps a Transport and keeps every interaction scrubbed; returns the inner response unchanged."""

    def __init__(self, inner: Transport, *, connector: str) -> None:
        self._inner = inner
        self._connector = connector
        self._interactions: list[dict[str, Any]] = []
        self._lock = threading.Lock()

    def request(
        self,
        method: str,
        url: str,
        *,
        params: Mapping[str, Any] | None = None,
        headers: Mapping[str, str] | None = None,
        json: Any = None,
        content: bytes | None = None,
    ) -> ApiResponse:
        response = self._inner.request(method, url, params=params, headers=headers, json=json, content=content)
        try:
            body, content_b64 = response.json(), None
        except ValueError:
            body, content_b64 = None, base64.b64encode(response.content).decode("ascii")
        interaction = {
            "request": {
                "method": method.upper(),
                "url": url,
                "params": _plain_params(params),
                "headers": {str(k).lower(): str(v) for k, v in (headers or {}).items()},
                "json": copy.deepcopy(json),
            },
            "response": {
                "status": int(response.status_code),
                "headers": {str(k).lower(): str(v) for k, v in response.headers.items()},
                "json": body,
                "content_b64": content_b64,
            },
        }
        scrubbed = scrub_interaction(interaction)  # nothing unscrubbed is ever kept
        with self._lock:
            self._interactions.append(scrubbed)
        return response

    def recording(self) -> dict[str, Any]:
        with self._lock:
            interactions = copy.deepcopy(self._interactions)
        return {"format": RECORDING_FORMAT, "connector": self._connector, "note": "", "interactions": interactions}

    def save(self, path: str | os.PathLike[str]) -> None:
        text = jsonlib.dumps(self.recording(), indent=2, ensure_ascii=False) + "\n"
        Path(path).write_text(text, encoding="utf-8", newline="\n")
