"""CL-INT-2 / CP2 delivery (PRD 5.4 CP2; issue #80 TiloClient `getDelivery` -> `DeliveryResult`; 9.4 HR-1):
`GET /worlds/{world_id}/delivery` returns `{world_id, artifacts: [{id, title, kind, version}], credits_used,
time_saved: {low_min, high_min} | null}` once the run has completed, and only to the world's owner. Shapes:
API_CL_INT_2.md.
"""

from __future__ import annotations

from _clint2_lib import CAP, OTHER_USER, wait_for

DELIVERY_KEYS = {"world_id", "artifacts", "credits_used", "time_saved"}
ARTIFACT_KEYS = {"id", "title", "kind", "version"}


def test_CP2_delivery_returns_the_tilo_client_delivery_result(run_flow):
    run_flow.run_to_completion()

    response = run_flow.delivery()

    assert response.status_code == 200, response.text
    body = response.json()
    assert set(body) == DELIVERY_KEYS, set(body)
    assert body["world_id"] == run_flow.world_id
    delivered = run_flow.events("artifact.delivered")
    completed = run_flow.events("world.completed")[0]["data"]
    extra = {"media_type", "content_sha256"}  # WEB-2 (WS-11): the version record's type and hash, when recorded
    assert [set(a) - extra for a in body["artifacts"]] == [ARTIFACT_KEYS] * len(delivered)
    assert [(a["id"], a["version"], a["kind"]) for a in body["artifacts"]] == [
        (e["data"]["artifact"]["artifact_id"], e["data"]["artifact"]["version"], e["data"]["format"]) for e in delivered
    ]
    draft = run_flow.artifact_of("U4")  # the id the store minted for the draft that was sent
    assert body["artifacts"][0]["id"] == draft["artifact_id"] and body["artifacts"][0]["kind"] == "email"
    assert all(isinstance(a["title"], str) and a["title"] for a in body["artifacts"])
    assert len(body["artifacts"]) == completed["deliverable_count"]
    assert body["credits_used"] == completed["credits_used"] and 0 <= body["credits_used"] <= CAP
    saved = body["time_saved"]  # always an estimate (PRD 18.4); null until the metering ticket
    assert saved is None or (set(saved) == {"low_min", "high_min"} and 0 <= saved["low_min"] <= saved["high_min"])


def test_CP2_delivery_is_409_until_the_run_has_completed(run_flow):
    _, card = run_flow.run_to_gate()
    assert run_flow.delivery().status_code == 409  # at the gate: nothing is delivered (HR-1)

    run_flow.answer(card["id"], "approve")
    wait_for(lambda: run_flow.events("world.completed"), what="world.completed")
    assert run_flow.delivery().status_code == 200


def test_CP2_only_the_owner_of_the_world_reads_its_delivery(run_flow):
    run_flow.run_to_completion()

    run_flow.as_member(OTHER_USER, "owner")
    assert run_flow.delivery().status_code in (403, 404)
    run_flow.as_member("u_viewer", "viewer")
    assert run_flow.delivery().status_code in (403, 404)
    run_flow.as_member()
    run_flow.world_id, real = "w_not_this_one", run_flow.world_id
    assert run_flow.delivery().status_code == 404  # not a member of that world
    run_flow.world_id = real
    run_flow.flow.sign_out()
    assert run_flow.delivery().status_code == 401
    run_flow.as_member()
    assert run_flow.delivery().status_code == 200
