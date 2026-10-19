"""Existing receipt in, ephemeral MeetingJoin out: no new contract and no live call."""

import pytest
from test_ADR32_T3_host_routes import Rig


def test_FR_MTG_09_join_rpc_reads_sent_event_returns_only_expiring_capability(caplog):
    rig = Rig()
    receipt = rig.send()["receipt"]
    before = len(rig.cal.requests)
    response = rig.call("join", receipt)
    assert response.status_code == 200
    assert response.json() == {"join_url": rig.cal.plant.link, "expires_at": "2026-10-08T09:34:00.000Z"}
    assert response.headers["cache-control"] == "no-store"
    assert len(rig.cal.requests) == before + 1
    assert rig.cal.requests[-1].params == {"fields": "status,hangoutLink"}
    assert rig.cal.plant.link not in caplog.text


@pytest.mark.parametrize("token", [None, "invalid"])
def test_FR_MTG_09_join_rpc_refuses_identity_before_calendar(token):
    rig = Rig()
    assert rig.call("join", {}, token=token).status_code == 401
    assert rig.cal.requests == []


def test_FR_MTG_09_join_rpc_other_service_is_forbidden():
    rig = Rig()
    other = rig.verifier.add(email="harness@example.test")
    assert rig.call("join", {}, token=other).status_code == 403
    assert rig.cal.requests == []


def test_FR_MTG_09_join_rpc_receipt_validation_never_echoes_invalid_input():
    rig = Rig()
    response = rig.call("join", {"event_ref": "https://meet.google.com/abc-defg-hij"})
    assert response.status_code == 422
    assert "meet.google.com" not in response.text
    assert rig.cal.requests == []


def test_FR_MTG_09_join_rpc_missing_event_fixed_conflict():
    rig = Rig()
    receipt = rig.send()["receipt"]
    rig.cal.get_hides_events = True
    response = rig.call("join", receipt)
    assert response.status_code == 409
    assert "meet.google.com" not in response.text
