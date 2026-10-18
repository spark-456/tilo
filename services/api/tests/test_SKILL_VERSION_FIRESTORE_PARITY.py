"""SKILL-VERSION-FIRESTORE-PARITY: teach/version through the deployed Firestore seams."""

from __future__ import annotations

import pytest
from _ppl11a_lib import ORG, PRIYA
from _ppl11c_fs_lib import person
from _skills4_lib import CLEAR


@pytest.mark.emulator
def test_SKILL_VERSION_FIRESTORE_PARITY_capture_then_version_can_change_instances(
    skills4, pw1b_emulator_host: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    from tilo_api import deps, durable_store, prod, team_store

    project = "demo-skill-version-parity"
    for name in ("K_SERVICE", "CLOUD_RUN_JOB", "GOOGLE_CLOUD_PROJECT", "TILO_API_DEV"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("FIRESTORE_EMULATOR_HOST", pw1b_emulator_host)
    monkeypatch.setenv("TILO_FIRESTORE_PROJECT", project)
    monkeypatch.setenv("TILO_PEOPLE_STORE", "firestore")
    monkeypatch.setenv("TILO_TEAM_STORE", "firestore")
    monkeypatch.setenv("TILO_SKILLS_STORE", "firestore")
    monkeypatch.setenv("TILO_OUTBOX_STORE", "firestore")
    monkeypatch.setenv("TILO_API_STORE", "firestore")
    deps.get_people_stores.cache_clear()
    deps.get_skill_store.cache_clear()
    team_store.get_team_store.cache_clear()
    durable_store._opened.clear()
    prod.reset()

    skills4.rig.unwire("people_stores", "event_writer", "desk_worlds", "skill_store")
    people = deps.get_people_stores()
    people.persons.create(person(PRIYA, ORG, email="priya.skill.parity@example.com"))

    captured = skills4.capture(CLEAR)
    assert captured.status_code == 201, captured.text

    # Model the next request landing on another service instance while the first is idle.
    durable_store._opened.clear()
    version = skills4.version(captured.json()["capture_id"])

    assert version.status_code == 200, version.text
    assert len(version.json()["plan_steps"]) == 3
    stored = deps.get_skill_store().get(ORG, captured.json()["capture_id"])
    assert stored is not None and stored["plan"] == version.json()["plan_steps"]
