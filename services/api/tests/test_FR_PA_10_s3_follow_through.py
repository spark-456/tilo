"""FR-PA-10 slice s3, what happens after the person confirms (API_FR_PA_10.md section 7): a proposal is carried out
only by the existing typed routes (`POST /v1/work-items/{id}/done`, `.../snooze`, PPL-11c S1), as the signed-in person,
with the same `check_write`, the same compare-and-set, the same per-principal write cap and the same S5 event as the
button. The ask route itself writes no work item; there is no new route (FR-PA-16: "each action produces the same
event as its card").

The people routes and the assistant route share one rig (`_ppl11b_lib.Rig` plus the Desk-world seam). The S5 events
carry `vis: []` until ADR-0009 lands, so they are compared as parts, not schema-validated. Strict xfails until the
builder removes `s3` from `SLICE_PENDING`.
"""

from __future__ import annotations

from typing import Any

from _fr_pa_10_lib import (
    BUDGET,
    PRINTER,
    RATE,
    SAM,
    TRAVEL,
    ask,
    assert_proposal,
    desk_ids,
    new_rig,
    pending,
    seam,
    update_world,
)
from _ppl11b_lib import Rig, principal, strip_volatile
from _ppl11b_lib import rig_factory as rig_factory  # noqa: PLC0414  (the fixture)
from tilo_api import app

pytestmark = pending("s3")


class _Desks:
    """`deps.get_desk_worlds()`: the person's one Desk world, the same id the assistant route uses."""

    def desk_world(self, org_id: str, user_id: str) -> str:
        return desk_ids(user_id, org_id)[0]


def wire_writes(rig: Rig) -> None:
    app.dependency_overrides[seam("get_desk_worlds")] = lambda: _Desks()


def apply(rig: Rig, action: dict[str, Any]) -> Any:
    """What the web executor does when the person confirms: the same call as the button."""
    assert action is not None, "the ask gave no proposal to confirm"
    rig.activate()
    wire_writes(rig)
    path = f"/v1/work-items/{action['work_item_id']}"
    if action["kind"] == "mark_done":
        return rig.client.post(f"{path}/done", json={})
    assert action["kind"] == "snooze", action
    return rig.client.post(f"{path}/snooze", json={"until": action["until"]})


def changed(rig: Rig, user: str = SAM) -> list[dict[str, Any]]:
    return [e for e in rig.events(user) if e["type"] == "work_item.changed"]


def core_of(event: dict[str, Any]) -> dict[str, Any]:
    keep = ("type", "actor", "target", "level", "district", "item", "severity", "credits", "summary", "vis", "authz")
    return {**{k: event[k] for k in keep}, "data": event["data"], "world_id": event["world_id"]}


def test_FR_PA_10_s3_a_confirmed_done_goes_through_the_done_route_and_writes_the_buttons_event(rig_factory, tmp_path):
    mr, rig = new_rig(rig_factory, tmp_path)
    wire_writes(rig)
    body = ask(rig, "it is done", record=BUDGET)
    assert_proposal(body, {"kind": "mark_done", "work_item_id": BUDGET}, by="rules")
    assert changed(rig) == [], "asking changed nothing: the proposal is not a write"
    stored = rig.world.stores.work_items.get("org_tilo", BUDGET)
    assert stored.record["status"] == "open"
    response = apply(rig, body["ui_action"])
    assert response.status_code == 200 and response.json()["status"] == "done"
    [event] = changed(rig)
    assert event["actor"] == SAM and event["target"] == SAM and event["world_id"] == desk_ids(SAM)[0]
    assert event["data"] == {"work_item_id": BUDGET, "change": "done", "status": "done"}
    assert rig.world.stores.work_items.get("org_tilo", BUDGET).version == stored.version + 1


def test_FR_PA_10_s3_a_confirmed_snooze_is_accepted_by_the_snooze_route_with_the_proposed_instant(
    rig_factory, tmp_path
):
    """The proposal's `until` (09:00 local of the resolved day) is inside the route's window (now, now + 30 days]."""
    mr, rig = new_rig(rig_factory, tmp_path)
    wire_writes(rig)
    body = ask(rig, "move it to friday", record=TRAVEL)
    action = body["ui_action"]
    assert action == {"kind": "snooze", "work_item_id": TRAVEL, "until": "2026-10-09T03:30:00.000Z"}
    response = apply(rig, action)
    assert response.status_code == 200
    assert response.json()["snoozed_until"] == action["until"]
    [event] = changed(rig)
    assert event["data"] == {"work_item_id": TRAVEL, "change": "snoozed", "status": "open"}


def test_FR_PA_10_s3_the_panel_and_the_button_write_the_same_event(rig_factory, tmp_path):
    """FR-PA-16: each action produces the same event as its card. A button press and a confirmed proposal for the
    same item leave events that are equal in every field the writer does not stamp."""
    mr, panel = new_rig(rig_factory, tmp_path)
    wire_writes(panel)
    done = ask(panel, "done", record=RATE)["ui_action"]
    snooze = ask(panel, "snooze it to monday", record=BUDGET)["ui_action"]
    assert apply(panel, done).status_code == 200 and apply(panel, snooze).status_code == 200

    mr2, button = new_rig(rig_factory, tmp_path, world=update_world())
    wire_writes(button)
    button.activate()
    assert button.client.post(f"/v1/work-items/{RATE}/done", json={}).status_code == 200
    assert button.client.post(f"/v1/work-items/{BUDGET}/snooze", json={"until": snooze["until"]}).status_code == 200
    assert [core_of(e) for e in changed(panel)] == [core_of(e) for e in changed(button)]
    assert len(changed(panel)) == 2


def test_FR_PA_10_s3_a_proposal_applied_twice_or_after_the_item_moved_changes_nothing_more(rig_factory, tmp_path):
    """A stale proposal is the route's own refusal (404 or 409, as a second 'done' on the button): one event, one
    version step, and the answer does not reveal why."""
    mr, rig = new_rig(rig_factory, tmp_path)
    wire_writes(rig)
    action = ask(rig, "done", record=PRINTER)["ui_action"]
    assert apply(rig, action).status_code == 200
    version = rig.world.stores.work_items.get("org_tilo", PRINTER).version
    again = apply(rig, action)
    assert again.status_code in (404, 409)
    assert rig.world.stores.work_items.get("org_tilo", PRINTER).version == version
    assert len(changed(rig)) == 1


def test_FR_PA_10_s3_another_person_cannot_apply_a_proposal_made_for_sam(rig_factory, tmp_path):
    """The proposal is not a capability: Priya posting Sam's action is the one 404 of an unknown id, and Sam's item
    does not move."""
    mr, rig = new_rig(rig_factory, tmp_path)
    wire_writes(rig)
    action = ask(rig, "done", record=RATE)["ui_action"]
    before = rig.world.snapshot()
    rig.set_principal(principal("u_priya"))
    refused = apply(rig, action)
    unknown = apply(rig, {"kind": "mark_done", "work_item_id": "wi_never_made"})
    assert refused.status_code == 404 and unknown.status_code == 404
    assert strip_volatile(refused.json()) == strip_volatile(unknown.json()) and refused.content == unknown.content
    assert rig.world.snapshot() == before
    assert changed(rig) == [] and changed(rig, "u_priya") == []


def test_FR_PA_10_s3_asking_spends_no_write_budget_and_the_follow_through_is_capped_like_a_button(
    rig_factory, tmp_path
):
    """S4: 60 people POST attempts a minute per principal, counted whatever the answer. Seventy asks that propose
    something use none of it; 59 refused attempts and one real write are the 60; the next confirmed proposal is the
    429 a button press would get (with `Retry-After`)."""
    mr, rig = new_rig(rig_factory, tmp_path)
    wire_writes(rig)
    actions = [ask(rig, "done", record=item)["ui_action"] for item in (RATE, BUDGET, TRAVEL, PRINTER)]
    for n in range(66):
        body = ask(rig, "snooze it to friday", record=RATE)
        assert body["ui_action"] is not None, n
    rig.activate()
    for _ in range(59):
        assert rig.client.post("/v1/work-items/wi_never_made/done", json={}).status_code == 404
    assert apply(rig, actions[0]).status_code == 200, "asking used none of the 60"
    limited = apply(rig, actions[1])
    assert limited.status_code == 429 and 1 <= int(limited.headers["retry-after"]) <= 60
    assert rig.world.stores.work_items.get("org_tilo", BUDGET).record["status"] == "open"
