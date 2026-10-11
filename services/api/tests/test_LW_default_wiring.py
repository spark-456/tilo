"""The production runner must bind reads and quiz checks to the owning run."""

import pytest
from tilo_api import deps


def test_default_runner_binds_per_run(monkeypatch):
    monkeypatch.setattr(deps, "_worker_models", lambda mode: {})
    runner = deps.get_unit_runner("replay")
    assert callable(getattr(runner, "bind_run", None))


def test_replay_fetch_never_uses_dns(tmp_path, monkeypatch):
    from tilo_api.web_tools import fetch_service

    def forbidden(*args, **kwargs):
        pytest.fail("Replay attempted network access")

    monkeypatch.setattr("socket.getaddrinfo", forbidden)
    service = fetch_service("replay", None, tmp_path)
    with pytest.raises(Exception):
        service.fetch(
            "https://source.test/paper.pdf",
            allow_hosts=("source.test",),
            org_id="org_test",
            run_id="r_test",
            unit_id="U1",
        )
