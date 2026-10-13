"""FR-ACC-02 / ADR-0027 decision 3: the run's gate passes the running unit's skill `tool_access[connector]` to
`effective_level(team, skill)`. A skill can only LOWER the team's level; a connector it leaves out, a skill without
`tool_access` and an unknown or unreadable skill change nothing (the team's level applies); a value that is not a
`tool_access_level` fails closed (off, never act). Read from the skill registry's manifests, never from a model."""

from __future__ import annotations

import asyncio
import logging
from types import SimpleNamespace

import pytest
from _team_routes_lib import OWNER, state


@pytest.fixture(scope="module")
def registry():  # type: ignore[no-untyped-def]
    from tilo_api import deps

    return deps.get_connector_registry()


class Skills:
    """A skill registry stand-in: `load(id)` answers an object with `tool_access`; an id not in `by_id` raises."""

    def __init__(self, **by_id: object) -> None:
        self.by_id = by_id

    def folder(self, skill_id: str) -> object | None:
        return "skills/x" if skill_id in self.by_id else None  # None: not in the registry

    def load(self, skill_id: str) -> SimpleNamespace:
        if skill_id not in self.by_id:
            raise KeyError(skill_id)
        return SimpleNamespace(id=skill_id, tool_access=self.by_id[skill_id])


def _gate(registry, team, skills, skill_ids):  # type: ignore[no-untyped-def]
    from tilo_api import runs

    fake = SimpleNamespace(
        plan={"gates": [{"id": "g1", "guards": ["u1"], "action_type": "send_email", "risk_tier": "T2"}]},
        seams=SimpleNamespace(
            resolver=lambda **_: {"recipients": ["ann@example.com"], "destination": "thread-1"},
            artifacts=SimpleNamespace(head=lambda *_: SimpleNamespace(record={"screening": "clean"})),
            connectors=registry, team=team, skills=skills,
        ),
        brief={}, scope=None, world_id="w_1", owner=OWNER, store=SimpleNamespace(policies={}),
        _applied=lambda: [], adapters={}, _draft_first=lambda *_: None,
    )  # fmt: skip
    fake._action = lambda c, a: runs.Run._action(fake, c, a)  # type: ignore[arg-type]
    unit = {"id": "u1", "district": "d1", "connectors": ["gmail"], "skills": skill_ids}
    return asyncio.run(runs.Run.gate(fake, unit, "A_w", "send_email", {"artifact_id": "a1", "version": 1}, "e1"))  # type: ignore[arg-type]


def _blocked(registry, team_level, skills, skill_ids=("s1",)) -> bool:  # type: ignore[no-untyped-def]
    """True when the step failed at the tool-access check; False when it went on to the engine (the fake stops)."""
    from tilo_api import runs

    try:
        _gate(registry, lambda: state(tools={"gmail": team_level}), skills, list(skill_ids))
    except runs._GateFailed as exc:
        assert "tool access" in str(exc)
        return True
    except Exception:  # the fake has no card machinery: it stops after the engine decided
        return False
    return False


def test_FR_ACC_02_a_skill_declaring_read_turns_an_act_teams_t2_send_into_a_block(registry) -> None:  # type: ignore[no-untyped-def]
    assert _blocked(registry, "act", Skills(s1={"gmail": "read"})) is True
    assert _blocked(registry, "act", Skills(s1={"gmail": "draft"})) is True


def test_FR_ACC_02_a_skill_declaring_act_on_a_team_level_of_read_stays_read(registry) -> None:  # type: ignore[no-untyped-def]
    assert _blocked(registry, "read", Skills(s1={"gmail": "act"})) is True


def test_FR_ACC_02_a_skill_without_tool_access_changes_nothing(registry) -> None:  # type: ignore[no-untyped-def]
    assert _blocked(registry, "act", Skills(s1={})) is False
    assert _blocked(registry, "act", Skills(s1=None)) is False
    assert _blocked(registry, "read", Skills(s1={})) is True  # the team's own level still applies


def test_FR_ACC_02_a_connector_the_skill_leaves_out_uses_the_team_level(registry) -> None:  # type: ignore[no-untyped-def]
    assert _blocked(registry, "act", Skills(s1={"google_drive": "off"})) is False


def test_FR_ACC_02_a_skill_act_on_an_act_team_goes_on_to_the_engine(registry) -> None:  # type: ignore[no-untyped-def]
    assert _blocked(registry, "act", Skills(s1={"gmail": "act"})) is False


@pytest.mark.parametrize("bad", ["write", "Read", "", 2, None, ["read"], True])
def test_FR_ACC_02_a_malformed_value_blocks_never_acts(registry, bad: object) -> None:  # type: ignore[no-untyped-def]
    assert _blocked(registry, "act", Skills(s1={"gmail": bad})) is True


def test_FR_ACC_02_a_malformed_tool_access_map_blocks(registry) -> None:  # type: ignore[no-untyped-def]
    assert _blocked(registry, "act", Skills(s1=["gmail"])) is True
    assert _blocked(registry, "act", Skills(s1="read")) is True


def test_FR_ACC_02_the_lowest_level_of_a_units_skills_applies(registry) -> None:  # type: ignore[no-untyped-def]
    skills = Skills(s1={"gmail": "act"}, s2={"gmail": "read"})
    assert _blocked(registry, "act", skills, ("s1", "s2")) is True
    assert _blocked(registry, "act", skills, ("s1",)) is False


def test_FR_ACC_02_an_unknown_skill_does_not_weaken_and_logs_ids_only(  # type: ignore[no-untyped-def]
    registry, caplog: pytest.LogCaptureFixture
) -> None:
    with caplog.at_level(logging.INFO):
        assert _blocked(registry, "read", Skills(), ("ghost",)) is True  # the team's read still blocks the send
        assert _blocked(registry, "act", Skills(), ("ghost",)) is False  # and nothing is lowered or raised
    lines = [r.getMessage() for r in caplog.records if "ghost" in r.getMessage()]
    assert lines and all("KeyError" in m or "skill" in m for m in lines)
    assert not any("ann@example.com" in r.getMessage() for r in caplog.records)


def test_FR_ACC_02_a_registered_skill_that_cannot_be_read_counts_as_off(registry) -> None:  # type: ignore[no-untyped-def]
    class Broken:
        def folder(self, _id: str) -> object:
            return "skills/x"  # in the registry

        def load(self, _id: str) -> object:
            raise RuntimeError("disk")

    assert _blocked(registry, "act", Broken()) is True  # unreadable at gate time: off, not skipped
    assert _blocked(registry, "act", Skills(), ("ghost",)) is False  # an id the registry never had stays skipped


def test_FR_ACC_02_the_skill_loader_reads_tool_access_from_the_manifest(tmp_path) -> None:  # type: ignore[no-untyped-def]
    from tilo_harness.skills import SkillRegistry

    folder = tmp_path / "ops" / "mailer"
    folder.mkdir(parents=True)
    (folder / "SKILL.md").write_text("Send mail.\n", encoding="utf-8", newline="\n")
    (folder / "skill.yaml").write_text(
        "id: mailer\nversion: 1.1.0\ndomain: ops\nauthor: A <a@example.com>\nreviewer: B <b@example.com>\n"
        "tools_allowed: [send_email]\ntool_access:\n  gmail: read\n"
        "inputs: {type: object}\noutputs: {type: object}\ndescription: Sends mail.\n",
        encoding="utf-8", newline="\n",
    )  # fmt: skip
    assert dict(SkillRegistry(tmp_path).load("mailer").tool_access) == {"gmail": "read"}
    (folder / "skill.yaml").write_text(
        "id: mailer\nversion: 1.0.0\ndomain: ops\nauthor: A <a@example.com>\nreviewer: B <b@example.com>\n"
        "tools_allowed: [send_email]\ninputs: {type: object}\noutputs: {type: object}\ndescription: Sends mail.\n",
        encoding="utf-8", newline="\n",
    )  # fmt: skip
    assert dict(SkillRegistry(tmp_path).load("mailer").tool_access) == {}
