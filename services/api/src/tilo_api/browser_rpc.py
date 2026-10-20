"""Authenticated client for the isolated tilo-browser session service."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import requests
import yaml
from tilo_browser.session import SessionRefused

from tilo_api.meeting_host_rpc import metadata_id_token


def step_timeout() -> float:
    """config/browser.yaml `step_timeout_s`: how long one browser call may take (opening a page in a fresh Chromium
    on a cold instance is the slow one); 30 when the file cannot be read."""
    try:
        path = Path(__file__).resolve().parents[4] / "config" / "browser.yaml"
        value = float(yaml.safe_load(path.read_text(encoding="utf-8"))["step_timeout_s"])
    except Exception:  # noqa: BLE001 - a missing or broken file keeps the contract's default
        return 30.0
    return value if 0 < value <= 120 else 30.0


class BrowserRpc:
    def __init__(
        self,
        base_url: str,
        *,
        token_for: Callable[[str], str] = metadata_id_token,
        transport: Any = None,
    ) -> None:
        parsed = urlsplit(base_url)
        if (
            parsed.scheme != "https"
            or not parsed.hostname
            or parsed.username
            or parsed.password
            or parsed.port not in (None, 443)
            or parsed.path not in ("", "/")
            or parsed.query
            or parsed.fragment
        ):
            raise ValueError("the browser service needs an https origin")
        self.base_url = base_url.rstrip("/")
        self.token_for = token_for
        self.transport = transport or requests.Session()
        self.timeout = step_timeout()

    def _call(self, method: str, path: str, body: dict | None = None) -> dict:
        try:
            response = self.transport.request(
                method,
                self.base_url + path,
                headers={"Authorization": f"Bearer {self.token_for(self.base_url)}"},
                json=body,
                timeout=self.timeout,
            )
            data = response.json()
        except Exception:  # token, transport and malformed replies all fail closed without logging credentials
            raise SessionRefused("browser_unavailable", 503) from None
        if response.status_code != 200:
            reason = data.get("reason") if isinstance(data, dict) else None
            raise SessionRefused(reason or "browser_unavailable", response.status_code)
        if not isinstance(data, dict):
            raise ValueError("browser service returned an invalid result")
        return data

    def start(self, body: dict) -> dict:
        return self._call("POST", "/sessions", body)

    def inspect(self, session: str, at: dict) -> dict:
        return self._call("POST", f"/sessions/{session}/inspect", {"session": session, "at": at})

    def act(self, session: str, body: dict) -> dict:
        return self._call("POST", f"/sessions/{session}/act", body)

    def end(self, session: str) -> dict:
        return self._call("DELETE", f"/sessions/{session}")
