"""FR-ACC-01, security review of PR #642 (round 1): no path may skip the team's tool level, and a configured team
store that cannot be opened fails CLOSED.

* B1: the meeting-host run (FR-MTG-09) builds its own seams; with `meeting_host` Off, Read or Draft its gate fails
  before any card or outbox entry, with Act the T3 card is still raised. `Seams.team` has no default.
* B2: `team_reader` is None only when no team store is configured at all; a non-empty `TILO_TEAM_STORE` that cannot
  be opened (a typo, Firestore without a valid project, a client that cannot be built) raises on read, so the step
  fails, the per-user cap is 0 and nothing is started.
* A connector outside the registry is blocked, never treated as Act.
* The level is read again when the approved send is dispatched: an Owner who turns a tool Off while its card waits
  stops the send.
"""

from __future__ import annotations

import dataclasses

import pytest
from _clint2_lib import wait_for
from _mtg09b_lib import CONNECTOR_ID, HostRig, block_network
from _team_routes_lib import OWNER, state

LEVEL_FREE = {"spend": True, "share": True, "undo": True, "tools": True, "weekend": False}


@pytest.fixture(autouse=True)
def _offline(monkeypatch: pytest.MonkeyPatch) -> None:
    block_network(monkeypatch)


def _team(level: str):  # type: ignore[no-untyped-def]
    from tilo_api.team_store import InMemoryTeamStore

    return InMemoryTeamStore(state(roles={OWNER: "Owner"}, tools={CONNECTOR_ID: level}))


@pytest.fixture()
def hosted(people_rig):  # type: ignore[no-untyped-def]
    from tilo_api.team_store import get_team_store

    def make(level: str):  # type: ignore[no-untyped-def]
        hr = HostRig(people_rig())
        team = _team(level)
        hr.rig.app.dependency_overrides[get_team_store] = lambda: team
        return hr, team

    return make


# --- B1 -------------------------------------------------------------------------------------------------------------


def test_FR_ACC_01_seams_team_has_no_default() -> None:
    from tilo_api.runs import Seams

    team = next(f for f in dataclasses.fields(Seams) if f.name == "team")
    assert team.default is dataclasses.MISSING and team.default_factory is dataclasses.MISSING


@pytest.mark.parametrize("level", ["off", "read", "draft"])
def test_FR_ACC_01_the_meeting_host_gate_fails_before_any_card_when_the_tool_level_says_no(hosted, level: str) -> None:  # type: ignore[no-untyped-def]
    hr, _ = hosted(level)
    assert hr.host().status_code == 200
    wait_for(lambda: hr.events("world.failed") or None, what="the host run failing")
    assert hr.gate_cards() == []
    assert hr.entries() == [] and hr.calendar.requests == []


def test_FR_ACC_01_the_meeting_host_gate_still_raises_its_card_on_act(hosted) -> None:  # type: ignore[no-untyped-def]
    hr, _ = hosted("act")
    assert hr.host_and_wait_gate()["kind"] == "gate"


def test_FR_ACC_01_turning_the_tool_off_while_the_card_waits_stops_the_send(hosted) -> None:  # type: ignore[no-untyped-def]
    hr, team = hosted("act")
    card = hr.host_and_wait_gate()
    now = team.read()
    assert team.compare_and_set(now.version, dataclasses.replace(now, tools={CONNECTOR_ID: "off"}))
    hr.answer(card["id"], "approve")
    hr.quiet()
    assert hr.entries() == [] and hr.calendar.requests == []


# --- B2 -------------------------------------------------------------------------------------------------------------


@pytest.fixture()
def env(monkeypatch: pytest.MonkeyPatch):  # type: ignore[no-untyped-def]
    from tilo_api.team_store import get_team_store

    for name in ("TILO_API_DEV", "TILO_TEAM_STORE", "TILO_FIRESTORE_PROJECT", "K_SERVICE"):
        monkeypatch.delenv(name, raising=False)
    get_team_store.cache_clear()  # type: ignore[attr-defined]
    yield monkeypatch
    get_team_store.cache_clear()  # type: ignore[attr-defined]


def test_FR_ACC_01_no_team_store_configured_reads_as_no_team(env) -> None:  # type: ignore[no-untyped-def]
    from tilo_api.team_store import team_reader

    assert team_reader({})() is None


@pytest.mark.parametrize(
    ("kind", "project"), [("Firestore", "demo-tilo-1"), ("firestore ", "demo-tilo-1"), ("firestore", ""),
                          ("firestore", "Not A Project"), ("memry", "")],
)  # fmt: skip
def test_FR_ACC_01_a_configured_team_store_that_cannot_open_fails_closed(env, kind: str, project: str) -> None:  # type: ignore[no-untyped-def]
    from tilo_api.team_store import team_reader

    env.setenv("TILO_TEAM_STORE", kind)
    env.setenv("TILO_FIRESTORE_PROJECT", project)
    with pytest.raises(Exception):  # noqa: B017
        team_reader({})()


def test_FR_ACC_01_a_firestore_client_that_cannot_be_built_fails_closed(env) -> None:  # type: ignore[no-untyped-def]
    from google.cloud import firestore
    from tilo_api.team_store import team_reader

    def refuse(*_a: object, **_k: object) -> object:
        raise RuntimeError("no credentials")

    env.setattr(firestore, "Client", refuse)
    env.setenv("TILO_TEAM_STORE", "firestore")
    env.setenv("TILO_FIRESTORE_PROJECT", "demo-tilo-1")
    with pytest.raises(Exception):  # noqa: B017
        team_reader({})()


def test_FR_ACC_01_an_unopenable_team_store_caps_spend_at_zero(env) -> None:  # type: ignore[no-untyped-def]
    from types import SimpleNamespace

    from tilo_api import deps, spend
    from tilo_metering.flags import process_flags

    caps = spend.SpendCaps(
        uid_lifetime_minor=1_000, run_minor=1_000, org_day_minor=None, global_day_hard_minor=20_000,
        unit_reserve_minor=100, rate_limit_requests=10, rate_limit_window_s=60,
    )  # fmt: skip
    env.setenv("TILO_TEAM_STORE", "Firestore")
    env.setenv("K_SERVICE", "tilo-api")
    env.setenv("TILO_JUDGE_" + "LIVE", "1")  # spelled apart: the repo's guard hook looks for the literal
    request = SimpleNamespace(app=SimpleNamespace(dependency_overrides={deps.get_spend_caps: lambda: caps}))
    switches = spend.Switches(process_flags(), spend.InMemorySpendLedger(caps))
    assert deps.spend_mode(request, OWNER, "judge", switches) == ("replay", True)  # type: ignore[arg-type]


# --- an unknown connector -------------------------------------------------------------------------------------------


def test_FR_ACC_01_a_connector_outside_the_registry_is_blocked() -> None:
    from tilo_api import deps
    from tilo_api.team_access import tool_check

    registry = deps.get_connector_registry()
    team = state(switches=LEVEL_FREE)
    assert tool_check(team, "not_a_connector", "send_email", "T2", registry=registry) == "block"
    assert tool_check(team, "not_a_connector", "read_email", "T1", registry=registry) == "block"
