"""FR-HIL-12 through a real run (real app, the run_flow fixture): a gate and its re-raised share cards are ONE wait.
The first approve on any of them sends exactly once, under that card's own reservation and proposal, and closes the
others, so a later answer on either card (owner or Approver) writes nothing, also after world.completed."""

from __future__ import annotations

import pytest
from _clint2_lib import FLOW_USER, assert_stream_valid, wait_for
from _peopleseams1_lib import directory
from tilo_api import app, deps

APPROVER = "u_approver"


@pytest.fixture(autouse=True)
def _approver_is_in_the_directory(run_flow):
    """An Approver is named from the org's people directory (PEOPLE-SEAMS-1, BQ-PEOPLESEAMS1-6)."""
    people = directory(FLOW_USER, APPROVER, "u_other_approver")
    app.dependency_overrides[deps.get_people_stores] = lambda: people


def _share(rf, card_id: str, approver: str = APPROVER) -> dict:
    rf.as_member()
    response = rf.flow.client.post(f"/worlds/{rf.world_id}/cards/{card_id}/share", json={"approver": approver})
    assert response.status_code == 201, response.text
    return response.json()


def _approver_answer(rf, token: str, option: str = "approve"):
    rf.as_member(user_id=APPROVER, role="approver")
    response = rf.flow.client.post(f"/share/{token}/answer", json={"option": option})
    rf.as_member()
    return response


def _sent_once_by(rf, registry, who: str, card_id: str) -> None:
    wait_for(lambda: rf.events("world.completed"), what="world.completed")
    events = assert_stream_valid(rf, registry)
    (resolved,) = [e for e in events if e["type"] == "approval.resolved"]
    requested = next(e for e in events if e["type"] == "approval.requested" and e["data"]["card_id"] == card_id)
    assert resolved["data"]["card_id"] == card_id and resolved["authz"] == {
        **resolved["authz"],
        "by": "person",
        "ref": who,
    }
    (entry,) = rf.outbox_store.all_entries()
    assert entry["id"] == requested["data"]["outbox_id"] == resolved["data"]["outbox_id"]  # that card's reservation
    assert entry["authz"]["ref"] == who and len(rf.adapter.sent) == 1
    assert len([e for e in events if e["type"] == "data.transfer"]) == 1


def _nothing_more_opens(rf, ids: list[str], token: str) -> None:
    before = len(rf.quiet_stream())
    for card_id in ids:  # the owner, on the original and on the share's card
        assert (rf.answer(card_id, "approve").status_code, rf.answer(card_id, "hold").json()["reason"]) == (
            400,
            "already_resolved",
        )
    assert _approver_answer(rf, token).json() == {"outcome": "rejected", "reason": "already_resolved"}
    assert len(rf.quiet_stream()) == before and len(rf.outbox_store.all_entries()) == 1


def test_FR_HIL_12_the_approver_approves_first_and_the_gate_sends_once_for_them(run_flow, registry):
    _, original = run_flow.run_to_gate()
    share = _share(run_flow, original["id"])

    assert _approver_answer(run_flow, share["token"]).status_code == 200

    _sent_once_by(run_flow, registry, APPROVER, share["card_id"])
    _nothing_more_opens(run_flow, [original["id"], share["card_id"]], share["token"])


def test_FR_HIL_12_the_owner_approves_first_and_the_approver_then_opens_nothing(run_flow, registry):
    _, original = run_flow.run_to_gate()
    share = _share(run_flow, original["id"])

    assert run_flow.answer(original["id"], "approve").status_code == 200

    _sent_once_by(run_flow, registry, FLOW_USER, original["id"])
    _nothing_more_opens(run_flow, [original["id"], share["card_id"]], share["token"])


def test_FR_HIL_12_the_owner_approves_the_shared_card_and_the_run_does_not_wait_forever(run_flow, registry):
    _, original = run_flow.run_to_gate()
    share = _share(run_flow, original["id"])

    assert run_flow.answer(share["card_id"], "approve").status_code == 200

    _sent_once_by(run_flow, registry, FLOW_USER, share["card_id"])
    _nothing_more_opens(run_flow, [original["id"], share["card_id"]], share["token"])


def test_FR_HIL_12_the_shared_proposal_links_to_the_original_in_the_trace(run_flow):
    requested, original = run_flow.run_to_gate()
    share = _share(run_flow, original["id"])

    shared = next(e for e in run_flow.events("approval.requested") if e["data"]["card_id"] == share["card_id"])

    assert shared["cause"] == requested["id"] and shared["actor"] == requested["actor"] != "system"


def test_FR_HIL_12_a_gate_has_one_live_share_and_a_shared_card_is_never_shared_again(run_flow):
    _, original = run_flow.run_to_gate()
    first = _share(run_flow, original["id"])
    second = _share(run_flow, original["id"], approver="u_other_approver")  # replaces the first

    assert _approver_answer(run_flow, first["token"]).status_code in (404, 410)
    run_flow.as_member()
    again = run_flow.flow.client.post(
        f"/worlds/{run_flow.world_id}/cards/{second['card_id']}/share", json={"approver": APPROVER}
    )
    assert again.status_code == 409  # a shared card is not a gate to share
    assert len(run_flow.events("approval.requested")) == 3 and run_flow.events("approval.resolved") == []


def test_FR_HIL_12_a_resolved_gate_cannot_be_shared_after_the_run_completed(run_flow):
    _, original = run_flow.run_to_gate()
    assert run_flow.answer(original["id"], "approve").status_code == 200
    wait_for(lambda: run_flow.events("world.completed"), what="world.completed")
    before = len(run_flow.quiet_stream())

    late = run_flow.flow.client.post(
        f"/worlds/{run_flow.world_id}/cards/{original['id']}/share", json={"approver": APPROVER}
    )

    assert late.status_code in (404, 409) and len(run_flow.quiet_stream()) == before


def test_FR_HIL_12_an_email_session_cannot_read_a_shared_gate(run_flow):
    _, original = run_flow.run_to_gate()
    share = _share(run_flow, original["id"])
    run_flow.as_member(user_id=APPROVER, role="approver")  # the Approver, in an email session
    run_flow.sessions_by_channel()

    response = run_flow.flow.client.get(f"/share/{share['token']}", headers={"x-session-channel": "email"})

    assert response.status_code == 400 and "what_happened" not in response.text


def test_FR_HIL_12_a_link_whose_gate_was_answered_elsewhere_is_gone(run_flow):
    _, original = run_flow.run_to_gate()
    share = _share(run_flow, original["id"])
    assert run_flow.answer(original["id"], "approve").status_code == 200

    run_flow.as_member(user_id=APPROVER, role="approver")
    response = run_flow.flow.client.get(f"/share/{share['token']}")

    assert response.status_code == 410 and "what_happened" not in response.text
