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


def test_MORNING_BRIEF_B1A_MO01_a_bounded_memory_store_keeps_the_newest_and_never_grows_past_its_limit():
    store = MemoryBriefStore(limit=50)
    for n in range(500):
        user = f"u_demo{n}"
        store.save_settings(ORG, user, {**SETTING, "owner_id": user})
        store.claim(ORG, user, "2026-10-16", "schedule")
        store.take_on_demand(ORG, user, "2026-10-16", 3)
        store.index_mail(ORG, user, [f"m{n}"], "2026-10-16")
    assert all(v <= 50 for v in store.sizes().values())
    assert store.settings(ORG, "u_demo499") is not None and store.settings(ORG, "u_demo0") is None
    assert store.mail_owner(ORG, "m499", "2026-10-16") == "u_demo499"
    assert store.claim(ORG, "u_demo0", "2026-10-16", "schedule")  # the oldest claim was forgotten


def test_MORNING_BRIEF_B1A_MO01_the_demo_stores_in_the_routes_are_bounded():
    from tilo_api import brief_routes

    assert brief_routes._DEMO_STORE.limit <= 5000


def test_MORNING_BRIEF_B1A_MO09_firestore_erasure_removes_claims_and_mail_ownership():
    from google.cloud.firestore import DELETE_FIELD

    data = {
        f"orgs/{ORG}/brief_settings/{ME}": SETTING,
        f"orgs/{ORG}/brief_claims/{ME}_2026-10-16_schedule": {"at": "2026-10-16"},
        f"orgs/{ORG}/brief_claims/{ME}_other_2026-10-16_schedule": {"at": "2026-10-16"},
        f"orgs/{ORG}/brief_claims/{YOU}_2026-10-16_schedule": {"at": "2026-10-16"},
        f"orgs/{ORG}/brief_mail/m1": {"owners": {ME: "2026-10-16", YOU: "2026-10-16"}},
        f"orgs/{ORG}/brief_mail/m2": {"owners": {ME: "2026-10-16"}},
        f"orgs/{ORG}/brief_mail/m3": {"owners": {YOU: "2026-10-16"}},
    }

    class Ref:
        def __init__(self, path):
            self.path = path

        def delete(self):
            data.pop(self.path, None)

        def update(self, changes):
            owners = data[self.path]["owners"]
            key, owner = next(iter(changes)).split(".")
            assert key == "owners" and changes[f"owners.{owner}"] is DELETE_FIELD
            owners.pop(owner, None)

    class Snapshot:
        def __init__(self, path):
            self.id, self.reference = path.rsplit("/", 1)[-1], Ref(path)

        def to_dict(self):
            return data.get(self.reference.path)

    class Collection:
        def __init__(self, prefix):
            self.prefix = prefix + "/"

        def stream(self):
            return [Snapshot(path) for path in list(data) if path.startswith(self.prefix)]

    class Client:
        def document(self, path):
            return Ref(path)

        def collection(self, path):
            return Collection(path)

    FirestoreBriefStore(Client()).erase(ORG, ME)
    assert f"orgs/{ORG}/brief_settings/{ME}" not in data
    assert f"orgs/{ORG}/brief_claims/{ME}_2026-10-16_schedule" not in data
    assert f"orgs/{ORG}/brief_claims/{ME}_other_2026-10-16_schedule" in data
    assert f"orgs/{ORG}/brief_claims/{YOU}_2026-10-16_schedule" in data
    assert data[f"orgs/{ORG}/brief_mail/m1"]["owners"] == {YOU: "2026-10-16"}
    assert f"orgs/{ORG}/brief_mail/m2" not in data and f"orgs/{ORG}/brief_mail/m3" in data


def test_MORNING_BRIEF_B1A_MO09_memory_erasure_removes_claims_counts_and_mail_indexes():
    store = MemoryBriefStore()
    store.claim(ORG, ME, "2026-10-16", "schedule")
    store.take_on_demand(ORG, ME, "2026-10-16", 3)
    store.index_mail(ORG, ME, ["m1"], "2026-10-16")
    store.erase(ORG, ME)
    assert store.sizes() == {"settings": 0, "claims": 0, "counts": 0, "mail": 0}


def test_MORNING_BRIEF_B1A_MO09_people_erasure_hook_erases_brief_records(monkeypatch):
    from tilo_api import people_firestore

    calls = []
    monkeypatch.setattr(FirestoreBriefStore, "erase", lambda self, org, user: calls.append((org, user)))
    monkeypatch.setattr("tilo_api.followup_outbox_sources.cancel_source_entries", lambda *args: None)
    monkeypatch.setattr("tilo_api.followup_draft_retention.followup_retention", lambda *args: [])
    stores = people_firestore.firestore_people_stores(object())
    stores.erase_followup(ORG, ME)
    assert (ORG, ME) in calls
