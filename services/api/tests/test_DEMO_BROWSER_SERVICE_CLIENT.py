"""DEMO-BROWSER-SERVICE: the run calls only the authenticated internal RPC."""

from types import SimpleNamespace

import pytest
import requests
from tilo_browser.session import SessionRefused


class FakeTransport:
    def __init__(self):
        self.calls = []

    def request(self, method, url, **kwargs):
        self.calls.append((method, url, kwargs))
        return SimpleNamespace(
            status_code=200,
            json=lambda: {"session": "bs_test", "step": 0, "kind": "start"},
        )


def test_DEMO_BROWSER_SERVICE_client_attaches_id_token_and_calls_session_rpc():
    from tilo_api.browser_rpc import BrowserRpc

    transport = FakeTransport()
    rpc = BrowserRpc("https://browser.example.run.app", token_for=lambda audience: "signed-token", transport=transport)
    result = rpc.start({"session": "bs_test"})
    assert result["session"] == "bs_test"
    method, url, request = transport.calls[0]
    assert (method, url) == ("POST", "https://browser.example.run.app/sessions")
    assert request["headers"]["Authorization"] == "Bearer signed-token"
    assert request["timeout"] <= 30


def test_DEMO_BROWSER_SERVICE_call_timeout_is_config_browser_step_timeout_s():
    """A cold Chromium on tilo-browser's one browser thread needs the configured step time, not a shorter guess."""
    from pathlib import Path

    import yaml
    from tilo_api.browser_rpc import BrowserRpc

    transport = FakeTransport()
    BrowserRpc("https://browser.example.run.app", token_for=lambda audience: "t", transport=transport).start({})
    config = yaml.safe_load((Path(__file__).resolve().parents[3] / "config" / "browser.yaml").read_text())
    assert transport.calls[0][2]["timeout"] == float(config["step_timeout_s"])


def test_DEMO_BROWSER_SERVICE_client_rejects_non_https_url():
    from tilo_api.browser_rpc import BrowserRpc

    with pytest.raises(ValueError):
        BrowserRpc("http://browser.example.run.app", token_for=lambda audience: "signed-token")


def test_DEMO_BROWSER_SERVICE_client_reports_transport_failure_without_leaking_token():
    from tilo_api.browser_rpc import BrowserRpc

    class BrokenTransport:
        def request(self, method, url, **kwargs):
            raise requests.ConnectionError("bearer token must stay private")

    rpc = BrowserRpc(
        "https://browser.example.run.app", token_for=lambda audience: "signed-token", transport=BrokenTransport()
    )
    with pytest.raises(SessionRefused) as refused:
        rpc.start({"session": "bs_test"})
    assert refused.value.reason == "browser_unavailable"
