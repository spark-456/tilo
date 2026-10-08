"""FR-TEAM-02 / FR-TEAM-04 / FR-ACC-01, security review of PR #642 (round 2): a deployed service never runs on the
in-memory team store.

`TILO_TEAM_STORE=memory` is refused when `K_SERVICE` or `CLOUD_RUN_JOB` is set (presence, not truthiness), in any case
or with stray whitespace. The reader fails closed in that case (raises), exactly like the other configured-but-unusable
stores; with neither variable set, the dev memory store still works.
"""

from __future__ import annotations

import pytest
from fastapi import HTTPException
from tilo_api import team_store

DEPLOYED = [("K_SERVICE", "tilo-api"), ("K_SERVICE", ""), ("CLOUD_RUN_JOB", "job"), ("CLOUD_RUN_JOB", "")]
VARIANTS = ["memory", "Memory", "MEMORY", "memory ", " memory", "\tMemory\n"]


@pytest.fixture(autouse=True)
def _clean(monkeypatch: pytest.MonkeyPatch):  # type: ignore[no-untyped-def]
    for name in ("K_SERVICE", "CLOUD_RUN_JOB", "LIVE", "TILO_API_DEV", "TILO_TEAM_STORE", "TILO_FIRESTORE_PROJECT"):
        monkeypatch.delenv(name, raising=False)
    team_store.get_team_store.cache_clear()
    yield
    team_store.get_team_store.cache_clear()


@pytest.mark.parametrize(("var", "value"), DEPLOYED)
@pytest.mark.parametrize("kind", VARIANTS)
def test_FR_TEAM_02_open_refuses_memory_on_a_deployed_service(
    monkeypatch: pytest.MonkeyPatch, var: str, value: str, kind: str
) -> None:
    monkeypatch.setenv(var, value)
    with pytest.raises(LookupError):
        team_store._open(kind, "")
    monkeypatch.setenv("TILO_TEAM_STORE", kind)
    with pytest.raises(HTTPException) as err:
        team_store.get_team_store()
    assert err.value.status_code == 503 and err.value.detail == "not_configured"


@pytest.mark.parametrize(("var", "value"), DEPLOYED)
def test_FR_TEAM_02_a_refusal_is_not_cached_across_environments(
    monkeypatch: pytest.MonkeyPatch, var: str, value: str
) -> None:
    team_store._open("memory", "")  # a dev process opened one earlier
    monkeypatch.setenv(var, value)
    with pytest.raises(LookupError):
        team_store._open("memory", "")


@pytest.mark.parametrize(("var", "value"), DEPLOYED)
@pytest.mark.parametrize("kind", ["memory", "Memory", "memory "])
def test_FR_ACC_01_the_reader_fails_closed_when_memory_is_set_on_a_deployed_service(
    monkeypatch: pytest.MonkeyPatch, var: str, value: str, kind: str
) -> None:
    monkeypatch.setenv(var, value)
    monkeypatch.setenv("TILO_TEAM_STORE", kind)
    assert team_store.team_configured() is True  # asked for, so it must raise rather than read as "no team"
    with pytest.raises(HTTPException) as err:
        team_store.team_reader({})()
    assert err.value.status_code == 503


@pytest.mark.parametrize("kind", ["memory", "Memory", "memory "])
def test_FR_TEAM_02_memory_is_still_allowed_when_not_deployed(monkeypatch: pytest.MonkeyPatch, kind: str) -> None:
    monkeypatch.setenv("TILO_TEAM_STORE", kind)
    assert isinstance(team_store.get_team_store(), team_store.InMemoryTeamStore)
    assert team_store.team_reader({})() is not None


def test_FR_TEAM_02_dev_mode_default_memory_is_still_allowed_when_not_deployed(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TILO_API_DEV", "1")
    assert isinstance(team_store.get_team_store(), team_store.InMemoryTeamStore)


def test_FR_TEAM_02_a_blank_setting_means_not_configured(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TILO_TEAM_STORE", "  ")
    assert team_store.team_configured() is False
    assert team_store.team_reader({})() is None
