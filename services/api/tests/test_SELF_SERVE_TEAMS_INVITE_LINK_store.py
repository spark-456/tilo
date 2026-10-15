"""SELF-SERVE-TEAMS invite record store compare-and-set behavior."""

import json
from pathlib import Path

import pytest
from tilo_api.invite_link_store import MemoryLinks
from tilo_people.errors import AlreadyExists, VersionConflict

PENDING = Path(__file__).resolve().parents[3] / "contracts/fixtures/team_invite_link/valid/pending.json"


def test_SELF_SERVE_TEAMS_INVITE_LINK_store_claim_is_single_winner():
    record = json.loads(PENDING.read_text(encoding="utf-8"))
    store = MemoryLinks()
    first = store.create(record)
    with pytest.raises(AlreadyExists):
        store.create(record)
    changed = {
        **record,
        "status": "redeemed",
        "redeemed": {"by": record["created_by"]["by"], "at": record["created_by"]["at"]},
    }
    store.replace(changed, first.version)
    with pytest.raises(VersionConflict):
        store.replace(changed, first.version)
    assert store.get(record["org_id"], record["id"]).record["status"] == "redeemed"
