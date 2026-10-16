"""MORNING-BRIEF-B1A, MO-02, MO-03, MO-04, MO-11: the brief's small records, in memory and (marked `emulator`) on the
Firestore emulator with a `demo-` project: the setting, the once-a-day claim, the on-demand count and the mail-id index.
"""

from __future__ import annotations

import pytest
from tilo_api.brief_store import BriefStore, FirestoreBriefStore, MemoryBriefStore

ORG, ME, YOU = "org_tilo", "u_me", "u_you"
SETTING = {
    "owner_id": ME,
    "enabled": True,
    "time": "07:30",
    "time_zone": "UTC",
    "email_copy": False,
    "updated_at": None,
}


@pytest.fixture(params=["memory", pytest.param("firestore", marks=pytest.mark.emulator)])
def store(request) -> BriefStore:
    if request.param == "memory":
        return MemoryBriefStore()
    client = request.getfixturevalue("people_fs_client")
    for name in ("brief_settings", "brief_claims", "brief_mail"):
        for doc in client.collection(f"orgs/{ORG}/{name}").stream():
            doc.reference.delete()
    return FirestoreBriefStore(client)


def test_MORNING_BRIEF_B1A_MO02_a_setting_is_stored_per_person_and_only_enabled_ones_are_swept(store):
    assert store.settings(ORG, ME) is None
    store.save_settings(ORG, ME, SETTING)
    store.save_settings(ORG, YOU, {**SETTING, "owner_id": YOU, "enabled": False})
    assert store.settings(ORG, ME) == SETTING
    assert [d["owner_id"] for d in store.enabled(ORG, 10)] == [ME]
    store.erase(ORG, ME)
    assert store.settings(ORG, ME) is None and store.enabled(ORG, 10) == []


def test_MORNING_BRIEF_B1A_MO03_a_claim_is_won_once_per_person_date_and_kind(store):
    assert store.claim(ORG, ME, "2026-10-16", "schedule") is True
    assert store.claim(ORG, ME, "2026-10-16", "schedule") is False
    assert store.claim(ORG, ME, "2026-10-16", "purge") is True
    assert store.claim(ORG, ME, "2026-10-17", "schedule") is True
    assert store.claim(ORG, YOU, "2026-10-16", "schedule") is True


def test_MORNING_BRIEF_B1A_MO04_the_on_demand_count_stops_at_the_limit_and_counts_per_date_and_person(store):
    assert [store.take_on_demand(ORG, ME, "2026-10-16", 3) for _ in range(5)] == [True, True, True, False, False]
    assert store.take_on_demand(ORG, ME, "2026-10-17", 3) is True
    assert store.take_on_demand(ORG, YOU, "2026-10-16", 3) is True


def test_MORNING_BRIEF_B1A_MO11_a_message_id_is_vouched_for_by_exactly_one_person_for_seven_days(store):
    store.index_mail(ORG, ME, ["m1", "m2"], "2026-10-16")
    store.index_mail(ORG, YOU, ["m2"], "2026-10-16")
    store.index_mail(ORG, ME, ["m_old"], "2026-10-01")
    today = "2026-10-16"
    assert store.mail_owner(ORG, "m1", today) == ME
    assert store.mail_owner(ORG, "m2", today) is None  # two holders: ambiguous
    assert store.mail_owner(ORG, "m_old", today) is None and store.mail_owner(ORG, "never", today) is None
    assert store.mail_owner(ORG, "m1", "2026-10-24") is None  # eight days on
    assert store.mail_owner(ORG, "bad id", today) is None


def test_MORNING_BRIEF_B1A_MO03_a_malformed_id_never_reaches_a_document_path():
    class Client:
        def document(self, path: str):
            raise AssertionError(path)

    fs = FirestoreBriefStore(Client())
    for call in (lambda: fs.claim(ORG, "../x", "2026-10-16", "schedule"), lambda: fs.settings(ORG, "not a user")):
        with pytest.raises(ValueError):
            call()
