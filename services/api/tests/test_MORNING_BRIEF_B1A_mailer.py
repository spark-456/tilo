"""MORNING-BRIEF-B1A, MO-10: `DeskPlateMailer.deliver_text`, the brief's email copy over the FR-CHN-18 path.

Same harness as the plate mailer's tests (`test_FR_CHN_18b_plate_mailer`): the person's own standing L3 rule, a
Desk-world artifact, their own mailbox and the outbox, with a fake Gmail stub. Nothing leaves the process.
"""

from __future__ import annotations

from _ppl11a_lib import PRIYA
from test_FR_CHN_18b_plate_mailer import DESK, IN_WINDOW, _env
from tilo_api import deps, plate_mailer
from tilo_api.user_settings import defaults, settings_store_of

TEXT = "Your morning brief for 2026-10-06\n\nMeetings today\n  - Standup (10:00)\n"


def _mailer(env):
    return plate_mailer.production_mailer(env.rig.app.dependency_overrides)


def test_MORNING_BRIEF_B1A_MO10_the_brief_goes_to_the_owners_own_address_under_their_rule_once_a_utc_day(
    people_rig, monkeypatch
):
    env = _env(people_rig, monkeypatch)
    mailer = _mailer(env)
    assert mailer.rule_ready(PRIYA, IN_WINDOW) is True
    assert mailer.deliver_text(PRIYA, TEXT, now=IN_WINDOW, kind="morning_brief") is True
    assert [(m["to"], m["subject"], m["body"], m["owner"]) for m in env.gmail.sent] == [
        ([env.address], "Your morning brief (2026-10-06)", TEXT, PRIYA)
    ]
    assert mailer.deliver_text(PRIYA, TEXT + "again", now="2026-10-06T06:00:00.000Z", kind="morning_brief") is False
    assert len(env.gmail.sent) == 1  # one per person per UTC day, whatever the version
    types = [e["type"] for e in env.store.events.get(DESK, [])]
    assert "policy.applied" in types and "data.transfer" in types


def test_MORNING_BRIEF_B1A_MO10_the_plate_digest_and_the_brief_are_separate_mails_of_the_same_day(
    people_rig, monkeypatch
):
    env = _env(people_rig, monkeypatch)
    mailer = _mailer(env)
    assert mailer.deliver_text(PRIYA, TEXT, now=IN_WINDOW, kind="morning_brief") is True
    assert mailer.deliver_text(PRIYA, "Daily Digest\n", now=IN_WINDOW, kind="digest") is True
    assert len(env.gmail.sent) == 2


def test_MORNING_BRIEF_B1A_MO10_without_the_persons_own_pinned_rule_nothing_is_built_stored_or_sent(
    people_rig, monkeypatch
):
    env = _env(people_rig, monkeypatch, policy=None)
    mailer = _mailer(env)
    assert mailer.rule_ready(PRIYA, IN_WINDOW) is False
    assert mailer.deliver_text(PRIYA, TEXT, now=IN_WINDOW, kind="morning_brief") is False
    assert env.gmail.sent == [] and env.outbox.all_entries() == []


def test_MORNING_BRIEF_B1A_MO10_a_malformed_kind_is_refused(people_rig, monkeypatch):
    env = _env(people_rig, monkeypatch)
    mailer = _mailer(env)
    assert mailer.deliver_text(PRIYA, TEXT, now=IN_WINDOW, kind="Morning Brief!") is False
    assert env.gmail.sent == []


def test_MORNING_BRIEF_B1A_MO09_email_copy_artifact_uses_its_requested_retention_id(people_rig, monkeypatch):
    env = _env(people_rig, monkeypatch)
    assert _mailer(env).deliver_text(PRIYA, TEXT, now=IN_WINDOW, kind="morning_brief") is True
    assert any("/artifacts/art_morning_brief_" in path for path in env.meta.paths(""))


def _quiet(env, *, start: str, end: str) -> None:
    """The person's saved quiet hours (Asia/Kolkata): the copy must wait while they are on."""
    document = defaults(PRIYA) | {"version": 1, "updated_at": "2026-10-01T00:00:00.000Z"}
    document["quiet_hours"] = {
        "enabled": True,
        "start": start,
        "end": end,
        "timezone": "Asia/Kolkata",
        "threshold": None,
    }
    assert settings_store_of(env.rig.stores).write(deps.ORG_ID, PRIYA, expected_version=0, document=document)


def test_MORNING_BRIEF_B1A_MO10_quiet_hours_hold_the_copy_and_nothing_is_built_or_sent(people_rig, monkeypatch):
    env = _env(people_rig, monkeypatch)
    _quiet(env, start="09:00", end="12:00")  # IN_WINDOW is 10:30 IST: inside
    assert _mailer(env).deliver_text(PRIYA, TEXT, now=IN_WINDOW, kind="morning_brief") is False
    assert env.gmail.sent == [] and env.outbox.all_entries() == []


def test_MORNING_BRIEF_B1A_MO10_outside_the_persons_quiet_hours_the_copy_goes_out(people_rig, monkeypatch):
    env = _env(people_rig, monkeypatch)
    _quiet(env, start="19:00", end="08:00")  # 10:30 IST is outside
    assert _mailer(env).deliver_text(PRIYA, TEXT, now=IN_WINDOW, kind="morning_brief") is True
    assert len(env.gmail.sent) == 1
