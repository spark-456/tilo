"""The production runner must bind reads and quiz checks to the owning run."""

import pytest
from tilo_api import deps


def test_grounded_publisher_hosts_survive_search_redirects():
    from tilo_api.web_tools import SearchTool
    from tilo_providers.search import SearchResult, SearchSource

    result = SearchResult(
        query="papers",
        answer="Recorded publishers",
        queries=["papers"],
        profile_id="fixture",
        sources=[
            SearchSource(
                title="Paper",
                domain="papers.example.test",
                redirect_url="https://search.example.test/grounding/opaque",
                resolved_url="https://cdn.example.test/paper.pdf",
            )
        ],
    )
    hosts = set()
    tool = SearchTool(lambda _: (result, 0.0), hosts)
    tool.run({"query": "papers"})
    assert hosts == {"search.example.test", "papers.example.test", "cdn.example.test"}


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
