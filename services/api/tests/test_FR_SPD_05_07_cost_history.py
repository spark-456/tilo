"""Recorded approval history on the existing owner-only cost report; no writes or providers."""

from _api_lib import as_principal, make_principal
from _mtr10_lib import A1, A2, OWNER, RUN, B, seed, serve_ledger
from tilo_api.cost_history import cost_history


def event(world, kind, at, card="card-a", **data):
    return {
        "id": f"{world}-{kind}-{at}",
        "world_id": world,
        "run_id": RUN[world],
        "type": kind,
        "ts": at,
        "summary": kind,
        "data": {"card_id": card, **data},
    }


def test_FR_SPD_05_07_cost_history_only_uses_owned_worlds_and_matching_recorded_pairs(client, store):
    seed(store)
    serve_ledger([])
    as_principal(make_principal(user_id=OWNER, role="owner", world_id=A1))
    request = event(A1, "approval.requested", "2026-10-11T09:00:00Z", action_type="send_email")
    resolved = event(A1, "approval.resolved", "2026-10-11T09:02:00Z", option="approve")
    store.events[A1] = [resolved, request, resolved]
    store.events[A2] = [event(A2, "approval.resolved", "2026-10-11T09:03:00Z")]
    store.events[B] = [
        event(B, "approval.requested", "2026-10-11T09:00:00Z", action_type="private"),
        event(B, "approval.resolved", "2026-10-11T10:00:00Z"),
    ]
    body = client.get("/costs").json()
    assert body["approval_waits"] == [
        {"card_id": "card-a", "world_id": A1, "run_id": RUN[A1], "action_type": "send_email", "seconds": 120.0}
    ]
    assert len(body["activity"]) == 3
    assert all(row["world_id"] != B for row in body["activity"])
    assert body["activity"][0]["ts"] == "2026-10-11T09:03:00Z"
    assert client.get(f"/worlds/{A1}/costs").json()["approval_waits"] == body["approval_waits"]
    assert store.events[A1] == [resolved, request, resolved]


def test_FR_SPD_05_repeated_requests_after_an_answer_begin_a_new_measured_wait():
    rows = [
        event(A1, "approval.requested", "2026-10-11T09:00:00Z", action_type="send_email"),
        event(A1, "approval.resolved", "2026-10-11T09:02:00Z", option="hold"),
        event(A1, "approval.requested", "2026-10-11T09:05:00Z", action_type="send_email"),
        event(A1, "approval.resolved", "2026-10-11T09:06:00Z", option="approve"),
    ]
    assert [w["seconds"] for w in cost_history(rows)["approval_waits"]] == [120, 60]


def test_FR_SPD_05_missing_bad_or_reversed_timestamps_never_invent_waits(client, store):
    seed(store)
    serve_ledger([])
    as_principal(make_principal(user_id=OWNER, role="owner", world_id=A1))
    store.events[A1] = [
        event(A1, "approval.requested", "2026-10-11T09:00:00Z", action_type="send_email"),
        event(A1, "approval.resolved", "2026-10-11T08:00:00Z"),
        event(A1, "approval.resolved", "bad", card="invalid"),
        event(A1, "approval.requested", "2026-10-11T09:00:00", card="naive"),
    ]
    store.events[A2] = []
    body = client.get("/costs").json()
    assert body["approval_waits"] == []
    assert len(body["activity"]) == 2
    store.events[A1] = []
    empty = client.get("/costs").json()
    assert empty["approval_waits"] == empty["activity"] == []
