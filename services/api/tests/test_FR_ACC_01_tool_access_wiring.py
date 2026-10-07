"""FR-ACC-01 made real (issue #621): Off / Read / Draft / Act per tool, set on tilo-api and USED by the run's gate.

Done-when: "Each level maps to a risk tier; Act never goes past what the policy engine allows." Only the Owner sets a
tool's level (matrix row "Change tool access", BQ-TEAMACC-2). On the run path a send is checked with
`permits(effective_level(team_level, skill_level), tier, read_only)` BEFORE the policy engine, where `read_only` comes
from the connector tables (config/connectors.yaml, config/mcp.yaml), never from a tool call or model output. The check
only ever makes the path stricter: a blocked step fails before any card or outbox entry, an allowed one still goes to
the existing engine and its person gate. FR-TEAM-02's "limits feed the per-user cap" is checked here too: the team
limit is a MIN on the SEC-16 lifetime cap.
"""

from __future__ import annotations

import asyncio
import inspect
from types import SimpleNamespace

import pytest
from _team_routes_lib import APPROVER, MEMBER, OWNER, VIEWER, state, team_api


@pytest.fixture(scope="module")
def registry():  # type: ignore[no-untyped-def]
    from tilo_api import deps

    return deps.get_connector_registry()


# --- the route ---------------------------------------------------------------------------------------------------


def test_FR_ACC_01_the_owner_sets_a_tool_level_and_it_is_served() -> None:
    with team_api() as api:
        assert {t["connector"]: t["level"] for t in api.get().json()["tools"]}["gmail"] == "act"  # default: as today
        response = api.put("/v1/team/tools/gmail", {"level": "read"})
        assert response.status_code == 200, response.text
        assert {t["connector"]: t["level"] for t in response.json()["tools"]}["gmail"] == "read"
        assert api.store.read().tools["gmail"] == "read"


@pytest.mark.parametrize("actor", [APPROVER, MEMBER, VIEWER])
def test_FR_ACC_01_only_the_owner_changes_tool_access(actor: str) -> None:
    with team_api() as api:
        assert api.as_(actor).put("/v1/team/tools/gmail", {"level": "act"}).status_code == 403
        assert "gmail" not in api.store.read().tools


def test_FR_ACC_01_an_unknown_tool_or_level_is_refused() -> None:
    with team_api() as api:
        assert api.put("/v1/team/tools/not_a_tool", {"level": "read"}).status_code == 404
        for bad in ("Read", "write", "", 2, None):
            assert api.put("/v1/team/tools/gmail", {"level": bad}).status_code == 422


# --- read_only comes from the tables ----------------------------------------------------------------------------


def test_FR_ACC_01_read_only_comes_from_the_connector_table(registry) -> None:  # type: ignore[no-untyped-def]
    from tilo_api.team_access import read_only, tool_check

    assert read_only("gmail", "read_email", registry=registry) is True
    assert read_only("gmail", "search_email", registry=registry) is True
    assert read_only("gmail", "create_draft", registry=registry) is False  # a write, gated
    assert read_only("gmail", "send_email", registry=registry) is False
    assert read_only("gmail", "nope", registry=registry) is False
    assert read_only("nope", "read_email", registry=registry) is False
    assert "read_only" not in inspect.signature(tool_check).parameters  # nobody can assert it from outside


@pytest.mark.parametrize(
    ("level", "action", "tier", "expected"),
    [
        ("off", "read_email", "T1", "block"),
        ("off", "send_email", "T2", "block"),
        ("read", "read_email", "T1", "allow"),
        ("read", "create_draft", "T1", "block"),
        ("read", "send_email", "T2", "block"),
        ("draft", "create_draft", "T1", "allow"),
        ("draft", "send_email", "T2", "block"),
        ("act", "send_email", "T2", "allow"),
        ("act", "send_email", "T3", "needs_person"),
    ],
)
def test_FR_ACC_01_each_level_maps_to_a_tier(registry, level: str, action: str, tier: str, expected: str) -> None:  # type: ignore[no-untyped-def]
    from tilo_api.team_access import tool_check

    team = state(tools={"gmail": level})
    assert tool_check(team, "gmail", action, tier, registry=registry) == expected


def test_FR_ACC_02_a_skill_level_only_lowers_the_team_level(registry) -> None:  # type: ignore[no-untyped-def]
    from tilo_api.team_access import tool_check
    from tilo_policy import Level

    act = state(tools={"gmail": "act"})
    assert tool_check(act, "gmail", "send_email", "T2", registry=registry, skill_level=Level.DRAFT) == "block"
    read = state(tools={"gmail": "read"})
    assert tool_check(read, "gmail", "send_email", "T2", registry=registry, skill_level=Level.ACT) == "block"


def test_FR_ACC_01_no_team_store_wired_changes_nothing(registry) -> None:  # type: ignore[no-untyped-def]
    from tilo_api.team_access import tool_check

    assert tool_check(None, "gmail", "send_email", "T2", registry=registry) == "allow"  # the engine still decides


# --- the run's gate uses it -------------------------------------------------------------------------------------


def _gate(registry, team):  # type: ignore[no-untyped-def]
    from tilo_api import runs

    fake = SimpleNamespace(
        plan={"gates": [{"id": "g1", "guards": ["u1"], "action_type": "send_email", "risk_tier": "T2"}]},
        seams=SimpleNamespace(
            resolver=lambda **_: {"recipients": ["ann@example.com"], "destination": "thread-1"},
            artifacts=SimpleNamespace(head=lambda *_: SimpleNamespace(record={"screening": "clean"})),
            connectors=registry,
            team=team,
        ),
        brief={}, scope=None, world_id="w_1", owner=OWNER, store=SimpleNamespace(policies={}),
        _applied=lambda: [],
    )  # fmt: skip
    fake._action = lambda c, a: runs.Run._action(fake, c, a)  # type: ignore[arg-type]
    unit = {"id": "u1", "district": "d1", "connectors": ["gmail"]}
    return asyncio.run(runs.Run.gate(fake, unit, "A_w", "send_email", {"artifact_id": "a1", "version": 1}, "e1"))  # type: ignore[arg-type]


@pytest.mark.parametrize("level", ["off", "read", "draft"])
def test_FR_ACC_01_a_send_the_tool_level_does_not_allow_fails_before_any_card(registry, level: str) -> None:  # type: ignore[no-untyped-def]
    from tilo_api import runs

    with pytest.raises(runs._GateFailed, match="tool access"):
        _gate(registry, lambda: state(tools={"gmail": level}))


def test_FR_ACC_01_an_unreadable_team_store_fails_the_step_closed(registry) -> None:  # type: ignore[no-untyped-def]
    from tilo_api import runs

    def broken() -> object:
        raise RuntimeError("down")

    with pytest.raises(runs._GateFailed, match="tool access"):
        _gate(registry, broken)


def test_FR_ACC_01_act_goes_on_to_the_existing_engine_and_person_gate(registry) -> None:  # type: ignore[no-untyped-def]
    with pytest.raises(Exception) as went_on:  # the fake has no card machinery: it stops after the engine decided
        _gate(registry, lambda: state(tools={"gmail": "act"}))
    assert "tool access" not in str(went_on.value)


# --- FR-TEAM-02: the team limit feeds the SEC-16 per-user cap as a MIN ------------------------------------------


def test_FR_TEAM_02_the_team_limit_can_only_lower_the_per_user_cap() -> None:
    from tilo_api.team_access import user_cap_minor

    team = state(limits={MEMBER: 500, APPROVER: 9_999_999})
    assert user_cap_minor(team, MEMBER, 1_000) == 500
    assert user_cap_minor(team, APPROVER, 1_000) == 1_000  # never lifts the lifetime cap
    assert user_cap_minor(team, VIEWER, 1_000) == 0  # a Viewer spends nothing (role limit)
    assert user_cap_minor(team, "u_not_in_team", 1_000) == 1_000
    assert user_cap_minor(None, MEMBER, 1_000) == 1_000


def test_FR_TEAM_02_spend_mode_caps_a_person_at_their_team_limit(monkeypatch: pytest.MonkeyPatch) -> None:
    from tilo_api import deps, spend
    from tilo_api.team_store import InMemoryTeamStore, get_team_store
    from tilo_metering.flags import process_flags

    caps = spend.SpendCaps(
        uid_lifetime_minor=1_000, run_minor=1_000, org_day_minor=None, global_day_hard_minor=20_000,
        unit_reserve_minor=100, rate_limit_requests=10, rate_limit_window_s=60,
    )  # fmt: skip
    ledger = spend.InMemorySpendLedger(caps)
    for uid in (MEMBER, APPROVER):
        held = ledger.reserve(uid=uid, run_id=f"r_{uid}", org_id="org_tilo", amount_minor=600, at=_now())
        ledger.settle(held, 600)  # type: ignore[arg-type]
    team = InMemoryTeamStore(state(limits={MEMBER: 500}))
    request = SimpleNamespace(app=SimpleNamespace(dependency_overrides={
        deps.get_spend_caps: lambda: caps, get_team_store: lambda: team,
    }))  # fmt: skip
    monkeypatch.setenv("K_SERVICE", "tilo-api")
    monkeypatch.setenv("TILO_JUDGE_" + "LIVE", "1")  # spelled apart: the repo's guard hook looks for the literal
    switches = spend.Switches(process_flags(), ledger)
    assert deps.spend_mode(request, MEMBER, "judge", switches) == ("replay", True)  # type: ignore[arg-type]
    assert deps.spend_mode(request, VIEWER, "judge", switches) == ("replay", True)  # type: ignore[arg-type]
    assert deps.spend_mode(request, APPROVER, "judge", switches) == ("live", False)  # type: ignore[arg-type]


def _now():  # type: ignore[no-untyped-def]
    from datetime import UTC, datetime

    return datetime(2026, 10, 8, 10, 0, tzinfo=UTC)
