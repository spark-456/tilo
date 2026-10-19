"""E2E-ONESTEP: after a run reaches `world.completed` on the dev wiring (fake runner, in-memory artifact store), the
owner's "Open result" (`GET /worlds/{id}/result`) answers with the delivered output, not a 404 or a 500."""

from __future__ import annotations

from _clint2_lib import OTHER_USER


def test_E2E_ONESTEP_the_owner_downloads_the_delivered_output_of_a_finished_dev_run(run_flow):
    run_flow.run_to_completion()

    response = run_flow.flow.client.get(f"/worlds/{run_flow.world_id}/result")

    assert response.status_code == 200, response.text
    assert response.content, "the delivered item has bytes"
    assert response.headers["content-disposition"].startswith("attachment")


def test_E2E_ONESTEP_nobody_else_downloads_it(run_flow):
    run_flow.run_to_completion()
    run_flow.as_member(OTHER_USER, "owner")

    assert run_flow.flow.client.get(f"/worlds/{run_flow.world_id}/result").status_code == 404
