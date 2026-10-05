"""NFR-24 (PRD 17.2): "One flag switches the public link to replay-only." Also PRD 17.3: the US$25 daily hard
cap "triggers NFR-24", and NFR-22: a clear banner and labelled replays.

The flag is `replay_only` in the flag store (`tilo_metering.flags`, the one the daily-spend treasury sets at the
hard cap). tilo-api must read that store, so the seam pinned here is `tilo_api.deps.get_flag_store() -> FlagStore`
(a dependency, overridable like the store and the router). With the flag set the API starts no new live work:
`POST /intake` and `POST /tasks/{id}/approve` are refused with a message that says the link is replay-only;
what already exists stays readable (events of an existing world); clearing the flag restores service.
Written from the PRD text before any builder touches it: tests/NFR-24.
"""

from __future__ import annotations

import pytest
from _clint1_lib import seam
from tilo_api import app, deps
from tilo_metering.flags import InMemoryFlagStore

REFUSED = (409, 423, 503)  # "service not available for new work"; the PRD fixes no code, never 2xx


@pytest.fixture()
def flags(clear_flow):
    store = InMemoryFlagStore()
    app.dependency_overrides[seam(deps, "get_flag_store")] = lambda: store
    return store


def _says_replay(response) -> bool:
    body = response.json()
    text = str(body.get("detail") or body.get("error") or "").lower()
    return "replay" in text


def test_NFR_24_flag_off_the_link_takes_new_work(clear_flow, flags):
    assert not flags.get("replay_only")
    assert clear_flow.intake().status_code == 201


def test_NFR_24_flag_on_intake_is_refused_with_a_replay_message(clear_flow, flags):
    flags.set("replay_only", True, reason="NFR-24 test")

    response = clear_flow.intake()

    assert response.status_code in REFUSED, response.text
    assert _says_replay(response), f"the refusal must say the link is replay-only: {response.text}"


def test_NFR_24_flag_on_approve_is_refused_and_starts_no_run(clear_flow, flags):
    intake = clear_flow.task_with_approaches()  # work asked for before the flag flipped
    flags.set("replay_only", True, reason="NFR-24 test")

    response = clear_flow.approve(intake["task_id"], "quick", 50)

    assert response.status_code in REFUSED, response.text
    assert _says_replay(response), f"the refusal must say the link is replay-only: {response.text}"
    assert clear_flow.events(intake["world_id"], "budget.granted") == []


def test_NFR_24_flag_on_what_exists_stays_readable(run_flow):
    run_flow.run_to_completion()  # a finished run: what a replay-only link still shows
    store = InMemoryFlagStore()
    app.dependency_overrides[seam(deps, "get_flag_store")] = lambda: store
    store.set("replay_only", True, reason="NFR-24 test")

    response = run_flow.flow.client.get(f"/worlds/{run_flow.world_id}/events")

    assert response.status_code == 200, response.text
    assert response.json()["events"], "the recorded events are still served"


def test_NFR_24_clearing_the_flag_restores_service(clear_flow, flags):
    flags.set("replay_only", True, reason="NFR-24 test")
    assert clear_flow.intake().status_code in REFUSED
    flags.set("replay_only", False, reason="NFR-24 test: cleared")

    assert clear_flow.intake().status_code == 201
