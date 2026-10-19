"""Uncertain SDK outcomes retain authority and compensate only this publication."""

from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from google.api_core.exceptions import FailedPrecondition
from test_FR_MTG_03_minutes_publication import publication, publish  # noqa: F401
from tilo_api.followup_write_guard import guarded_write


@pytest.mark.parametrize("outcome", ["written", "lost_ack"])
@pytest.mark.parametrize("replacement", [False, True])
def test_FR_MTG_08_uncertain_write_cleanup_is_conditional(outcome, replacement):
    rows, options = {}, []

    def write(row):
        rows.update(row)
        if outcome == "lost_ack":
            raise RuntimeError("offline lost acknowledgement")

    def check():
        raise HTTPException(409, "source_closed")

    def read():
        snapshot = dict(rows)
        return SimpleNamespace(exists=True, to_dict=lambda: snapshot, update_time="pinned")

    def delete(*, option):
        assert option == "pinned"
        if replacement:
            rows.update(payload="replacement", publication_nonce="other-writer")
            raise FailedPrecondition("changed since snapshot")
        rows.clear()

    def write_option(*, last_update_time):
        options.append(last_update_time)
        return last_update_time

    client = SimpleNamespace(write_option=write_option)
    document = SimpleNamespace(get=read, delete=delete)
    with pytest.raises(HTTPException) as refused:
        guarded_write(client, document, {"payload": "private"}, write, check)
    assert refused.value.status_code == 409 and options == ["pinned"]
    assert rows == ({"payload": "replacement", "publication_nonce": "other-writer"} if replacement else {})


def test_FR_MTG_08_uncertain_write_preserves_already_replaced_row():
    deleted = []
    document = SimpleNamespace(
        get=lambda: SimpleNamespace(exists=True, to_dict=lambda: {"payload": "replacement"}),
        delete=lambda **kwargs: deleted.append(kwargs),
    )

    def check():
        raise HTTPException(409, "source_closed")

    with pytest.raises(HTTPException):
        guarded_write(None, document, {"payload": "private"}, lambda row: None, check)
    assert deleted == []


def test_FR_MTG_03_uncertain_commit_and_authority_read_preserve_artifact(publication, monkeypatch):  # noqa: F811
    rig, _, scope, _ = publication
    replace, get = rig.stores.meetings.replace, rig.stores.meetings.get

    def lost_ack(record, *, expected_version):
        replace(record, expected_version=expected_version)
        monkeypatch.setattr(rig.stores.meetings, "get", unavailable)
        raise RuntimeError("offline lost acknowledgement")

    def unavailable(*args):
        raise RuntimeError("offline authority unavailable")

    monkeypatch.setattr(rig.stores.meetings, "replace", lost_ack)
    with pytest.raises(RuntimeError):
        publish(publication)
    stored = get(rig.org, "mt_q4_plan")
    assert stored is not None and stored.record["minutes"] is not None
    assert rig.artifacts.head(scope, stored.record["minutes"]) is not None
