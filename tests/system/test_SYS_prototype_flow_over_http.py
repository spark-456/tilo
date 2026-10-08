"""SYS (ADR-0008, PRD 5.4 CP2): the prototype flow through the real `tilo-api` process, over HTTP.

Request -> clarifying questions -> approaches and budget -> run -> approval card -> approve or hold ->
outbox send -> delivery, with every claim read back from what the API recorded (HR-1). The API runs in
dev mode (fake Director, fake unit runner, a recording connector: nothing leaves the machine, EFF-01)."""

from __future__ import annotations

import time

import httpx
import pytest
from _sys_lib import event_types, gate_card, start_run, wait_for

pytestmark = pytest.mark.system

SEND = "data.transfer"  # the one recorded outbound send of the dev run


def test_SYS_CP2_FR_INT_08_FR_HIL_03_a_request_runs_to_a_gate_and_delivers_once_approved(client):
    intake = client.post("/intake", data={"text": "Prepare the weekly supplier summary."})
    assert intake.status_code == 201
    task = intake.json()
    assert task["questions"] and task["brief"]["goal"] == "Prepare the weekly supplier summary."
    assert client.get(f"/tasks/{task['task_id']}/approaches").status_code == 409  # not before the answers

    answers = [{"field": q["field"], "answer": None} for q in task["questions"]]
    assert (
        client.post(f"/tasks/{task['task_id']}/answers", json={"answers": answers, "brief_edits": {}}).status_code
        == 200
    )
    approaches = client.get(f"/tasks/{task['task_id']}/approaches").json()
    assert approaches["recommended"] in {a["id"] for a in approaches["approaches"]}

    approve = client.post(
        f"/tasks/{task['task_id']}/approve", json={"approach_id": approaches["recommended"], "budget_cap": 50}
    )
    assert approve.status_code == 200
    world = approve.json()["world_id"]
    assert (
        client.post(
            f"/tasks/{task['task_id']}/approve", json={"approach_id": approaches["recommended"], "budget_cap": 50}
        ).status_code
        == 409
    ), "one budget grant per task"

    card = gate_card(client, world)
    assert card["gate"]["risk_tier"] == "T3", "a send to a recipient new to the owner always needs a person (PRD 10.4)"
    assert {o["id"] if isinstance(o, dict) else o for o in card["options"]} >= {"approve", "hold"}
    assert SEND not in event_types(client, world), "nothing is sent before a person approves"
    assert client.get(f"/worlds/{world}/delivery").status_code == 409, "nothing is delivered before world.completed"

    assert client.post(f"/worlds/{world}/cards/{card['id']}/answer", json={"option": "approve"}).status_code == 200
    wait_for(lambda: "world.completed" in event_types(client, world), "world.completed")

    events = client.get(f"/worlds/{world}/events").json()["events"]
    types = [e["type"] for e in events]
    assert [e["seq"] for e in events] == list(range(1, len(events) + 1)), "seq is contiguous from 1"
    assert types[0] == "world.requested" and types[-1] == "world.completed"
    assert "world.failed" not in types and types.count(SEND) == 1
    assert types.index("approval.requested") < types.index("approval.resolved") < types.index(SEND)
    assert {e["world_id"] for e in events} == {world} and len({e["id"] for e in events}) == len(events)

    delivery = client.get(f"/worlds/{world}/delivery")
    assert delivery.status_code == 200 and delivery.json()["artifacts"]
    assert delivery.json()["credits_used"] <= 50, "the run stays inside the approved cap"
    late = client.post(f"/worlds/{world}/cards/{card['id']}/answer", json={"option": "approve"})
    assert (late.status_code, late.json()["reason"]) == (400, "already_resolved"), "the first answer wins"


def test_SYS_FR_HIL_03_a_hold_sends_nothing_and_a_later_approval_still_completes_the_run(client):
    _, world = start_run(client)
    card = gate_card(client, world)

    assert client.post(f"/worlds/{world}/cards/{card['id']}/answer", json={"option": "hold"}).status_code == 200
    time.sleep(1.5)  # nothing to wait for: the point is that nothing happens
    types = event_types(client, world)
    assert SEND not in types and "world.completed" not in types and "world.failed" not in types
    assert client.get(f"/worlds/{world}/delivery").status_code == 409

    assert client.post(f"/worlds/{world}/cards/{card['id']}/answer", json={"option": "approve"}).status_code == 200
    wait_for(lambda: "world.completed" in event_types(client, world), "world.completed after the later approval")
    assert event_types(client, world).count(SEND) == 1


def test_SYS_FR_WLD_07_pause_all_is_recorded_and_the_run_stops(client):
    _, world = start_run(client)
    paused = client.post(f"/worlds/{world}/pause")
    assert paused.status_code == 200 and paused.json()["paused"] is True
    wait_for(lambda: "world.paused" in event_types(client, world), "world.paused")
    settled = len(event_types(client, world))
    time.sleep(1.0)
    assert len(event_types(client, world)) == settled, "a paused run records nothing more"
    assert SEND not in event_types(client, world), "and sends nothing"
    assert client.post(f"/worlds/{world}/autopilot/stop").status_code == 200


def test_SYS_FR_WLD_05_the_run_has_a_layout_the_web_can_draw(client):
    _, world = start_run(client)
    ready = wait_for(lambda: (r := client.get(f"/worlds/{world}/layout")).status_code == 200 and r, "the layout")
    layout = ready.json()
    assert layout["world_id"] == world and layout["tier"] in {"outpost", "village", "town", "city"}
    assert layout["semantic"]["levels"] and layout["semantic"]["agents"]
    assert isinstance(layout["geometry"], dict), "the solver's geometry is attached for the owner (CL-INT-6)"


def test_SYS_FR_INT_01_FR_INT_12_intake_refuses_what_it_must_and_stores_nothing(client):
    assert client.post("/intake", data={"text": "   "}).status_code == 422
    assert client.post("/intake", data={"text": "x" * 4001}).status_code == 422
    assert client.post("/intake", data={"text": "hi", "scenario": "no-such-scenario"}).status_code == 422
    exe = client.post(
        "/intake", data={"text": "hello"}, files=[("files", ("a.exe", b"MZ", "application/x-msdownload"))]
    )
    assert exe.status_code == 422 and "PDF" in exe.json()["error"]
    csv = client.post("/intake", data={"text": "hello"}, files=[("files", ("a.csv", b"a,b\n1,2\n", "text/csv"))])
    assert csv.status_code == 201 and csv.json()["files"][0]["status"] == "ok"


def test_SYS_FR_INT_08_a_budget_must_be_inside_the_ceiling_and_name_a_proposed_approach(client):
    intake = client.post("/intake", data={"text": "Prepare the weekly supplier summary."}).json()
    answers = [{"field": q["field"], "answer": None} for q in intake["questions"]]
    client.post(f"/tasks/{intake['task_id']}/answers", json={"answers": answers, "brief_edits": {}})
    recommended = client.get(f"/tasks/{intake['task_id']}/approaches").json()["recommended"]
    approve = f"/tasks/{intake['task_id']}/approve"
    assert client.post(approve, json={"approach_id": recommended, "budget_cap": 100000}).status_code == 422
    assert client.post(approve, json={"approach_id": "bogus", "budget_cap": 5}).status_code == 422
    assert client.post(approve, json={"approach_id": recommended, "budget_cap": 0}).status_code in {400, 422}


def test_SYS_SEC_unknown_ids_and_bad_bodies_are_refused_never_a_server_error(client):
    statuses = {
        client.get("/worlds/w_nope/events").status_code,
        client.get("/worlds/w_nope/cards").status_code,
        client.get("/worlds/w_nope/layout").status_code,
        client.get("/worlds/w_nope/delivery").status_code,
        client.get("/tasks/t_nope/approaches").status_code,
        client.post("/worlds/w_nope/pause").status_code,
        client.post("/policies/pol_nope/revoke").status_code,
        client.post("/tasks/t_nope/answers", content=b"{", headers={"content-type": "application/json"}).status_code,
        client.post("/tasks/t_nope/answers", content=b"hi", headers={"content-type": "text/plain"}).status_code,
    }
    assert statuses <= {400, 403, 404, 409, 415, 422}, statuses


def test_SYS_SEC_06_the_dev_server_answers_only_its_own_host_and_only_the_web_origin(dev_api):
    assert httpx.get(f"{dev_api}/openapi.json", headers={"Host": "evil.example"}).status_code == 400
    ask = {"Access-Control-Request-Method": "POST"}
    ok = httpx.options(f"{dev_api}/intake", headers={"Origin": "http://localhost:5173", **ask})
    assert ok.headers.get("access-control-allow-origin") == "http://localhost:5173"
    assert "access-control-allow-credentials" not in ok.headers
    evil = httpx.options(f"{dev_api}/intake", headers={"Origin": "http://evil.example", **ask})
    assert "access-control-allow-origin" not in evil.headers


# Routes added after the prototype flow, driven here as one real HTTP call each in dev mode (one fixed owner, no
# Firestore, no Google config): the call must answer with the status that route gives for an unknown id, an empty
# body or a missing config, never a 5xx other than the by-design 503 `not_configured`. Their deep behaviour is
# covered by the owning service's own tests; this suite proves each is mounted, reachable and fails closed.
PROBES = {
    "GET /access": {503}, "POST /access/declaration": {503}, "GET /costs": {503}, "GET /worlds/{world_id}/costs": {503},
    "GET /worlds": {200}, "GET /cards": {200},
    "POST /worlds/{world_id}/cards/{card_id}/share": {422}, "DELETE /worlds/{world_id}/shares/{share_id}": {404},
    "GET /share/{token}": {404}, "POST /share/{token}/answer": {422},
    "POST /v1/assistant/ask": {422}, "GET /v1/meetings/{meeting_id}/quotes": {422},
    "GET /v1/work-items/{work_item_id}/quote": {404}, "GET /v1/plate": {200},
    "POST /v1/meetings": {422}, "POST /v1/meetings/{meeting_id}/confirm": {404},
    "GET /v1/meetings/{meeting_id}": {404}, "POST /v1/meetings/{meeting_id}/edit": {422},
    "GET /v1/meetings/{meeting_id}/minutes": {404}, "POST /v1/meetings/{meeting_id}/world": {503},
    "POST /v1/meetings/{meeting_id}/host": {503}, "POST /v1/meetings/{meeting_id}/delete": {404},
    "POST /v1/people": {422}, "POST /v1/people/first": {422}, "POST /v1/people/{person_id}/memberships": {422},
    "POST /v1/people/{person_id}/memberships/remove": {422}, "POST /v1/people/{person_id}/role": {422},
    "POST /v1/work-items": {422}, "GET /v1/work-items": {200}, "GET /v1/work-items/{work_item_id}": {404},
    "POST /v1/work-items/{work_item_id}/confirm": {404}, "POST /v1/work-items/{work_item_id}/edit": {422},
    "POST /v1/work-items/{work_item_id}/snooze": {422}, "POST /v1/work-items/{work_item_id}/done": {404},
    "POST /v1/work-items/{work_item_id}/reopen": {404}, "POST /v1/work-items/{work_item_id}/not-mine": {404},
    "POST /v1/work-items/{work_item_id}/put-back": {404},
    "GET /schedules": {200}, "POST /schedules": {422}, "GET /schedules/{schedule_id}": {404},
    "PATCH /schedules/{schedule_id}": {404}, "DELETE /schedules/{schedule_id}": {404},
    "POST /internal/schedules/tick": {503},  # public by design, fails closed: no OIDC audience/caller configured
    "POST /worlds/{world_id}/skill-proposals": {503},
    "GET /worlds/{world_id}/skill-proposals": {403}, "GET /worlds/{world_id}/skill-proposals/{proposal_id}": {403},
    "POST /worlds/{world_id}/skill-proposals/{proposal_id}/approve": {403},
    "POST /worlds/{world_id}/skill-proposals/{proposal_id}/reject": {403},
}  # fmt: skip


def test_SYS_every_later_route_answers_over_http_the_way_its_contract_says(dev_api):
    for route, allowed in PROBES.items():
        method, path = route.split(" ")
        url = dev_api + path.replace("{", "x_").replace("}", "")
        response = httpx.request(method, url, json={} if method in {"POST", "PATCH"} else None, timeout=15)
        assert response.status_code in allowed, f"{route} answered {response.status_code}, expected {sorted(allowed)}"
        assert "Traceback" not in response.text, f"{route} leaks a server error body"


def test_SYS_every_route_the_api_serves_is_driven_by_this_suite(dev_api):
    """A new route fails here until a system test drives it (or this list says why not)."""
    driven = {
        "GET /health", "GET /healthz", "POST /intake", "POST /tasks/{task_id}/answers",
        "GET /tasks/{task_id}/approaches", "POST /tasks/{task_id}/approve", "GET /worlds/{world_id}",
        "GET /worlds/{world_id}/events", "GET /worlds/{world_id}/cards",
        "POST /worlds/{world_id}/cards/{card_id}/answer", "GET /worlds/{world_id}/layout",
        "GET /worlds/{world_id}/delivery", "POST /worlds/{world_id}/pause",
        "POST /worlds/{world_id}/autopilot/stop", "POST /policies/{policy_id}/revoke",
    } | set(PROBES)  # fmt: skip
    # Team Lead console (FR-HIL-10): needs a team_lead principal, which dev mode (one fixed owner) has none of.
    not_drivable = {"GET /worlds/{world_id}/console", "POST /worlds/{world_id}/console/cards/{card_id}/answer"}
    spec = httpx.get(f"{dev_api}/openapi.json").json()
    served = {f"{m.upper()} {p}" for p, ops in spec["paths"].items() for m in ops}
    assert served == driven | not_drivable, sorted(served ^ (driven | not_drivable))
    console = httpx.get(f"{dev_api}/worlds/w_nope/console")
    assert console.status_code in {403, 404}, "the console refuses the owner: it is for a team lead only"
