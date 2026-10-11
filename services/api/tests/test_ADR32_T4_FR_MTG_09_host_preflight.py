"""ADR32_T4 / FR_MTG_09: the host route asks connectors for the owner's grant state before any gate card exists, and
the real connectors routes carry a whole host run (ADR-0032 decision 8). Connectors is its real app in process."""

from __future__ import annotations

import pytest
from _clint2_lib import wait_for
from _mtg09b_lib import HostRig, block_network
from tilo_api.meeting_host_rpc import Reply, RequestsTransport, TransportError


@pytest.fixture(autouse=True)
def _offline(monkeypatch: pytest.MonkeyPatch) -> None:
    block_network(monkeypatch)


@pytest.fixture()
def hr(people_rig):
    return HostRig(people_rig())


def test_ADR32_T4_FR_MTG_09_a_connectors_that_is_not_configured_is_503_before_any_run_or_gate(hr):
    hr.connectors.down = True
    before = hr.nothing_happened()
    response = hr.host()
    assert (response.status_code, response.json()) == (503, {"detail": "not_configured"})
    assert hr.nothing_happened() == before and hr.store.runs == {} and hr.events("approval.requested") == []


def test_ADR32_T4_FR_MTG_09_an_unreachable_connectors_is_503_and_starts_nothing(hr, monkeypatch):
    monkeypatch.setattr(hr.connectors, "post", lambda *a: (_ for _ in ()).throw(TransportError()))
    response = hr.host()
    assert (response.status_code, response.json()) == (503, {"detail": "not_configured"}) and hr.store.runs == {}


def test_ADR32_T4_FR_MTG_09_a_not_connected_owner_still_reaches_the_gate(hr):
    hr.broker.connected = False  # BQ-ADR32-1: the send fails after the gate with a plain reason, unchanged by the ADR
    assert hr.host().status_code == 200 and hr.wait_gate()["gate"]["recipients"]


def test_ADR32_T4_FR_MTG_09_the_id_token_goes_to_connectors_and_never_into_tilo(hr):
    hr.approve_and_wait_sent()
    assert hr.broker.token not in repr(hr.store.events) and hr.connectors.id_token not in repr(hr.store.events)
    wait_for(lambda: hr.receipt_refs() or None, what="the receipt artifact")
    assert hr.events("data.transfer") and len(hr.receipt_refs()) == 1 and hr.calendar.invitations


def test_ADR32_T4_FR_MTG_09_the_requests_transport_does_not_follow_redirects_and_caps_the_reply(monkeypatch):
    import requests

    seen: dict = {}

    class Response:
        status_code = 200
        raw = type("Raw", (), {"read": lambda self, n, decode_content=True: b"x" * n})()

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

    def post(url, **kw):
        seen.update(kw)
        return Response()

    monkeypatch.setattr(requests, "post", post)
    with pytest.raises(TransportError):
        RequestsTransport().post("https://x.a.run.app/a", b"{}", {"Authorization": "Bearer t"}, 20.0)
    assert seen["allow_redirects"] is False and seen["timeout"][1] == 20.0 and seen["stream"] is True
    Response.raw = type("Raw", (), {"read": lambda self, n, decode_content=True: b"{}"})()
    assert RequestsTransport().post("https://x.a.run.app/a", b"{}", {}, 20.0) == Reply(200, b"{}")


# --- security round 1: an ambiguous or possibly-sent invitation is never abandoned silently ---

import json  # noqa: E402

from _mtg09b_lib import OWNER, assert_registered_and_valid  # noqa: E402


def _sent_answer(**over):
    """A scripted connectors answer: `sent`, with the receipt built from the request it answers."""

    def build(body: bytes):
        entry = json.loads(body)["entry"]
        doc = {
            "world_id": entry["world_id"], "outbox_id": entry["id"], "meeting_id": "mt_host1", "owner": OWNER,
            "draft": {"artifact_id": entry["item"]["artifact_id"], "version": entry["item"]["version"]},
            "event_ref": "0" * 32, "conference": "success",
        }  # fmt: skip
        doc.update(over)
        return Reply(200, json.dumps({"outcome": "sent", "receipt": doc, "may_have_sent": None, "parts": []}).encode())

    return build


def _outcome_answer(outcome: str):
    return lambda body: Reply(
        200, json.dumps({"outcome": outcome, "receipt": None, "may_have_sent": None, "parts": []}).encode()
    )


def _alerts(hr):
    return [e for e in hr.events("alert.raised")]


def test_ADR32_T4_FR_MTG_09_a_lost_answer_after_the_send_leaves_the_entry_ambiguous_with_one_alert_and_no_false_failure(
    hr, registry, repo_root
):
    hr.connectors.lose_answers = 99  # every answer is lost; the first call did reach the calendar
    card = hr.host_and_wait_gate()
    assert hr.answer(card["id"], "approve").status_code == 200
    wait_for(lambda: hr.events("world.failed") or None, what="the run's end", timeout=60)
    (entry,) = hr.entries()
    assert len(hr.calendar.events) == 1 and len(hr.calendar.invitations) == 1, "one invitation (MH-13 on every retry)"
    assert entry["state"] != "failed", "a possibly-sent invitation is never marked failed"
    assert hr.outbox_store.retry_state(entry["id"])["ambiguous"] is True
    assert [a["data"]["alert_id"] for a in _alerts(hr)] == [entry["id"]], "exactly one alert, ids only"
    assert _alerts(hr)[0]["data"]["card_id"] is None and hr.events("data.transfer") == []
    (failed,) = hr.events("world.failed")  # honest outcome: the world stops, and says it cannot tell
    reason = failed["data"]["reason"]
    assert "may have" in reason and "check" in reason and "could not be sent" not in reason, reason
    assert_registered_and_valid(registry, repo_root, hr.events())


@pytest.mark.parametrize(
    "script", [_outcome_answer("possibly_sent"), _sent_answer()], ids=["possibly_sent", "sent_breaking_hb07"]
)
def test_ADR32_T4_FR_MTG_09_a_possibly_sent_answer_raises_exactly_one_alert_and_no_transfer(
    hr, script, registry, repo_root
):
    hr.connectors.script = [script]
    card = hr.host_and_wait_gate()
    assert hr.answer(card["id"], "approve").status_code == 200
    wait_for(lambda: hr.events("world.failed") or None, what="the run's end")
    (entry,) = hr.entries()
    assert entry["state"] == "failed" and hr.events("data.transfer") == []
    assert [a["data"]["alert_id"] for a in _alerts(hr)] == [entry["id"]]
    reason = hr.events("world.failed")[0]["data"]["reason"]
    assert "may have" in reason, reason
    assert_registered_and_valid(registry, repo_root, hr.events())
