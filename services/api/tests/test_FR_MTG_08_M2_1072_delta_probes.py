"""Independent repair-delta checks for nonce compensation, uncertain IO, replay and claims."""

from types import SimpleNamespace

import pytest
from _ppl11a_lib import OWNER
from fastapi import HTTPException
from google.api_core.exceptions import FailedPrecondition
from test_ACT_1_state_retention import retained  # noqa: F401
from test_FR_MTG_03_minutes_publication import publication, publish  # noqa: F401
from test_FR_MTG_08_M2_1064_review_probes import production_preview
from test_FR_MTG_08_owner_followup import followup  # noqa: F401
from test_FR_MTG_08_owner_followup_boundaries import remove_minutes
from test_FR_MTG_08_request_binding import durable  # noqa: F401
from tilo_api.followup_write_guard import guarded_write


@pytest.mark.parametrize("when", ["before_snapshot", "after_snapshot"])
def test_FR_MTG_08_M2_compensation_preserves_identical_payload_rival(when):
    row, deleted, options = {}, [], []
    rival = {"payload": "same private payload", "publication_nonce": "rival"}

    def write(value):
        row.update(value)

    def check():
        raise HTTPException(409, "source_closed")

    def read():
        if when == "before_snapshot":
            row.clear()
            row.update(rival)
        snapshot = dict(row)
        return SimpleNamespace(exists=True, to_dict=lambda: snapshot, update_time="original-version")

    def delete(*, option):
        assert option == "original-version"
        options.append(option)
        if when == "after_snapshot":
            row.clear()
            row.update(rival)
            raise FailedPrecondition("rival replaced source row")
        deleted.append(True)

    client = SimpleNamespace(write_option=lambda **kwargs: kwargs["last_update_time"])
    document = SimpleNamespace(get=read, delete=delete)
    with pytest.raises(HTTPException) as refused:
        guarded_write(client, document, {"payload": rival["payload"]}, write, check)
    assert refused.value.status_code == 409 and row == rival and deleted == []
    assert options == ([] if when == "before_snapshot" else ["original-version"])


@pytest.mark.parametrize("target", ["draft", "marker", "card", "stop"])
def test_FR_MTG_08_M2_valid_source_lost_ack_retry_keeps_one_row(retained, monkeypatch, target):  # noqa: F811
    c = retained
    document = c.db.document
    failed = []

    def lookup(path):
        ref = document(path)
        create = ref.create

        def lost_ack(row):
            result = create(row)
            if not failed:
                failed.append(path)
                raise RuntimeError("synthetic lost acknowledgement after successful write")
            return result

        ref.create = lost_ack
        return ref

    monkeypatch.setattr(c.db, "document", lookup)
    key = "draft#emitted" if target == "marker" else "retry"
    value = {} if target == "marker" else {"body": "private"}
    operations = {
        "draft": lambda: c.drafts.create(OWNER, key, value),
        "marker": lambda: c.drafts.create(OWNER, key, value),
        "card": lambda: c.cards.create(OWNER, key, value),
        "stop": lambda: c.stops.add(OWNER, key),
    }
    with pytest.raises(HTTPException) as refused:
        operations[target]()
    assert refused.value.status_code == 503
    assert len(c.db.docs) == 1
    before = dict(c.db.docs)
    assert operations[target]() is (None if target == "stop" else False)
    assert c.db.docs == before
    if target == "stop":
        assert c.stops.pending() == [(OWNER, key)]
    elif target == "card":
        assert c.cards.get(OWNER, key) == value
    else:
        assert c.drafts.get(OWNER, key) == value


@pytest.mark.parametrize("failure", ["erased", "lookup_failed"])
def test_FR_MTG_08_M2_existing_queue_claim_checks_source(durable, monkeypatch, failure):  # noqa: F811
    c = durable
    card, approval = production_preview(c)
    outcome = c.ap.send(OWNER, card.card_id, approval)
    assert outcome.status == "queued"
    if failure == "erased":
        remove_minutes(c, "metadata")
    else:

        def unavailable(*args):
            raise RuntimeError("synthetic authority lookup failure")

        monkeypatch.setattr(c.rig.artifacts, "head", unavailable)
    claims = []
    monkeypatch.setattr(c.box, "_claim_for_sending", lambda *args: claims.append(args))
    outbox = c.ap._ledger._outbox._inner
    assert outbox._halted() is True
    assert outbox._dispatch_one(outcome.outbox_id) is None
    assert claims == [] and c.line.api.sent == []


def test_FR_MTG_08_M2_uncertain_outbox_insert_erasure_compensates_and_no_duplicate(durable, monkeypatch):  # noqa: F811
    c = durable
    card, approval = production_preview(c)
    insert = c.box._insert_if_absent

    def lost_ack(entry):
        insert(entry)
        remove_minutes(c, "metadata")
        raise RuntimeError("synthetic outbox acknowledgement lost")

    monkeypatch.setattr(c.box, "_insert_if_absent", lost_ack)
    with pytest.raises(HTTPException):
        c.ap.send(OWNER, card.card_id, approval)
    entries = [row["entry"] for path, row in c.db.docs.items() if path.startswith("outbox/")]
    assert len(entries) == 1 and entries[0]["state"] == "failed"
    with pytest.raises(HTTPException):
        c.ap.send(OWNER, card.card_id, approval)
    after = [row["entry"] for path, row in c.db.docs.items() if path.startswith("outbox/")]
    assert after == entries and c.ap._ledger._outbox._inner._halted() is True
    assert c.line.api.sent == []


def test_FR_MTG_03_M2_uncertain_authority_lookup_keeps_referenced_artifact(publication, monkeypatch):  # noqa: F811
    rig, _, scope, _ = publication
    real_get = rig.stores.meetings.get
    replace = rig.stores.meetings.replace

    def unavailable(*args):
        raise RuntimeError("synthetic reread unavailable")

    def committed_ack_lost(record, *, expected_version):
        replace(record, expected_version=expected_version)
        monkeypatch.setattr(rig.stores.meetings, "get", unavailable)
        raise RuntimeError("synthetic successful CAS acknowledgement lost")

    monkeypatch.setattr(rig.stores.meetings, "replace", committed_ack_lost)
    with pytest.raises(RuntimeError):
        publish(publication)
    stored = real_get(rig.org, "mt_q4_plan")
    assert stored.record["minutes"] is not None
    assert rig.artifacts.head(scope, stored.record["minutes"]) is not None
