"""Live POST /v1/pinboards was a silent 503: the web always sends an `Idempotency-Key`, and `DurableLimits.once` refused
every route outside `_KINDS` with the fixed 503 and no log line (pinboards were not in it). On the in-memory limiter the
same request is a 201, which is why the other tests never saw it."""

from __future__ import annotations

import pytest
from _ppl11a_lib import PRIYA
from _ppl11c_fs2_lib import backend_rig, firestore_rig, fresh_token

BODY = {"title": "Client meeting with PwC in 2 hours", "kind": "note"}
TEAM_BODY = {"title": "Team board pin", "kind": "note"}


def _keyed(rig, body, key):
    return rig.client.post("/v1/pinboards", json=body, headers={"Idempotency-Key": key})


@pytest.mark.parametrize("store", ["memory", "firestore"])
def test_PIN_503_a_keyed_pin_create_is_a_201_and_a_replay_is_the_first_answer(people_rig, store):
    rig = backend_rig(people_rig, store)
    rig.as_user(PRIYA)
    key = fresh_token()
    first = _keyed(rig, BODY, key)
    assert first.status_code == 201, first.text[:200]
    again = _keyed(rig, BODY, key)
    assert again.status_code == 201 and again.content == first.content, "the first answer, byte for byte"


def test_PIN_503_a_replay_of_a_removed_pin_frees_the_key(people_rig):
    rig = firestore_rig(people_rig)
    rig.as_user(PRIYA)
    key = fresh_token()
    first = _keyed(rig, BODY, key)
    assert first.status_code == 201, first.text[:200]
    gone = rig.client.post(f"/v1/pinboards/{first.json()['id']}/delete", json={})
    assert gone.status_code == 200, gone.text[:200]
    again = _keyed(rig, BODY, key)
    assert again.status_code == 201 and again.json()["id"] != first.json()["id"], again.text[:200]


def test_PIN_503_a_route_outside_the_limiter_kinds_logs_its_503(caplog):
    import logging
    from datetime import UTC, datetime

    from fastapi import HTTPException
    from tilo_api.people_limits_store import DurableLimits
    from tilo_api.people_writes import Refusal  # noqa: F401

    limits = DurableLimits(object(), {})
    with caplog.at_level(logging.WARNING, logger="tilo_api.people"), pytest.raises(HTTPException) as caught:
        limits.once("u_a", "/v1/unknown", "k-1", _Body(), lambda: {"id": "x"}, datetime.now(UTC).timestamp())
    assert caught.value.status_code == 503
    assert any("/v1/unknown" in r.getMessage() for r in caplog.records), "a silent 503 is the bug"


class _Body:
    def model_dump_json(self) -> str:
        return "{}"
