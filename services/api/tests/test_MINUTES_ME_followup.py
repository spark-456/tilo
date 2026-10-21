"""MINUTES-ME (owner's live test, 21 Oct): a bot meeting has no attendee with a person record, so "Draft follow-up"
offered nobody and the owner could not send the minutes anywhere. The Owner may now pick themself: the same T3 card,
nothing sent until they approve it. Anyone else who is no attendee is still refused. Offline doubles only."""

from _ppl11a_lib import OWNER, SAM
from test_FR_MTG_03_04_08_minutes_chain import analyze_confirm, chain, no_preview, post, rows  # noqa: F401
from test_FR_MTG_03_analysis_publication import integration  # noqa: F401
from test_FR_MTG_03_owner_analysis_mode import owner_call  # noqa: F401
from test_FR_MTG_03_owner_minutes_caller import caller_app  # noqa: F401
from tilo_api import deps


def no_attendees(c):
    current = c.rig.real.meetings.get(c.rig.org, "mt_q4_plan")
    c.rig.real.meetings.replace({**current.record, "attendees": []}, expected_version=current.version)


def test_MINUTES_ME_the_owner_drafts_the_minutes_to_themself_when_nobody_else_is_linked(chain):  # noqa: F811
    c = chain
    no_attendees(c)
    analyze_confirm(c)
    owner = c.rig.real.persons.get(c.rig.org, OWNER).record
    response = post(c, "draft-followup", {"recipients": [OWNER]})
    assert response.status_code == 200, response.text
    preview = response.json()
    assert (preview["tier"], preview["status"]) == ("T3", "ready") and preview["to"] == [owner["email"]]
    assert preview["options"] == ["send", "edit", "cancel"]  # the Owner approves the send; nothing goes by itself
    assert deps.get_outbox_store().all_entries() == []
    assert rows(c, "followup_drafts") and rows(c, "cards")


def test_MINUTES_ME_someone_who_is_no_attendee_is_still_refused(chain):  # noqa: F811
    c = chain
    no_attendees(c)
    analyze_confirm(c)
    response = post(c, "draft-followup", {"recipients": [SAM]})
    assert response.status_code == 422 and response.json()["detail"] == "invalid_recipients"
    no_preview(c)
