"""Helpers for the PPL-11c acceptance tests (the rest of the people API on tilo-api: work-item routes, meeting
get/edit/delete and the minutes read, directory changes, write limits, PE-12 events, the meeting world; the interface
is pinned in `API_PPL_11c.md`).

Built on `_ppl11a_lib` (the `Rig`: the real `tilo_api.app` with every people seam faked, now also with a stamping event
writer, Desk worlds and a meeting-world maker). Named `_ppl11c_lib` for the same global-bare-module-name reason as
`_ppl11a_lib.py`. Nothing here is business logic: it builds schema-valid records from the crossref fixtures, names the
routes and drives the app. No network, no paid call, no model id, no secret (the fake token is assembled at run time).
"""

from __future__ import annotations

import asyncio
import copy
import json
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any

from _ppl11a_lib import (
    ATTEST,
    EARLY,
    NOW,
    ORG,
    OWNER,
    PRIYA,
    SAM,
    Rig,
    conforms,
    fixture_case,
    own_item,
    pl,
)

# Each slice of PPL-11c is a strict xfail until its builder removes its entry (API_PPL_11c.md section 0). An entry is
# a substring of a pytest node id, so it names a whole file; a slice that goes green with its entry still here
# fails (strict), which is the reminder to delete it. Guards (`test_PPL_11c_guards.py`) are never pending.
SLICE_PENDING: tuple[str, ...] = (
    "test_PPL_11c_s4_",  # limits: body cap, idempotency key, rate cap, no whole-org listing, no-store, dev CORS
    "test_PPL_11c_s5_",  # PE-12 events (also needs the ADR-0009 contract change for `vis: []`)
)
# Tests inside a pending file that pass as soon as an earlier slice lands (a negative test: "a refused work-item write
# emits nothing" is true of S1's routes, which emit nothing yet). Not xfail: a strict XPASS fails the earlier slice.
PENDING_EXEMPT: tuple[str, ...] = (
    # a route-list guard for S4's body-cap test: true as soon as S1 to S3 and S6 have landed, and it must stay true
    "test_PPL_11c_s4_BQ_PPL11C_1_every_people_post_route_is_in_the_body_cap_list",
    # regression guards of S4 that already hold at the S1 to S3 and S6 head (those routes are no-store and read the
    # actor by id); the S4 builder's middleware must keep them true
    "test_PPL_11c_s4_BQ_PPL11C_12_meeting_world_and_delete_read_the_actor_by_id_and_list_no_directory",
    "test_PPL_11c_s4_PE_22_every_people_route_of_this_ticket_answers_no_store_whatever_the_status",
    "test_PPL_11c_s4_PE_22_a_409_and_a_503_are_no_store_too",
    # true once S3's person and membership routes exist (a meeting create already emits nothing)
    "test_PPL_11c_s5_PE_12_writes_that_have_no_registry_event_write_none_and_need_no_writer",
    "test_PPL_11c_s5_HR_1_a_refused_a_lost_or_a_read_only_request_writes_no_event_and_makes_no_world",
)

# --- routes (API_PPL_11c.md section 1) ------------------------------------------------------------------------------

R_WI_LIST = ("GET", "/v1/work-items")
R_WI_GET = ("GET", "/v1/work-items/{work_item_id}")
R_WI_EDIT = ("POST", "/v1/work-items/{work_item_id}/edit")
R_WI_DONE = ("POST", "/v1/work-items/{work_item_id}/done")
R_WI_SNOOZE = ("POST", "/v1/work-items/{work_item_id}/snooze")
R_WI_REOPEN = ("POST", "/v1/work-items/{work_item_id}/reopen")
R_WI_NOT_MINE = ("POST", "/v1/work-items/{work_item_id}/not-mine")
R_WI_PUT_BACK = ("POST", "/v1/work-items/{work_item_id}/put-back")
R_MT_GET = ("GET", "/v1/meetings/{meeting_id}")
R_MT_EDIT = ("POST", "/v1/meetings/{meeting_id}/edit")
R_MT_DELETE = ("POST", "/v1/meetings/{meeting_id}/delete")
R_MT_MINUTES = ("GET", "/v1/meetings/{meeting_id}/minutes")
R_MT_WORLD = ("POST", "/v1/meetings/{meeting_id}/world")
R_PERSON_FIRST = ("POST", "/v1/people/first")
R_TEAM_ADD = ("POST", "/v1/people/{person_id}/memberships")
R_TEAM_REMOVE = ("POST", "/v1/people/{person_id}/memberships/remove")
R_ROLE = ("POST", "/v1/people/{person_id}/role")

WI_ACTIONS = {
    "edit": R_WI_EDIT,
    "done": R_WI_DONE,
    "snooze": R_WI_SNOOZE,
    "reopen": R_WI_REOPEN,
    "not-mine": R_WI_NOT_MINE,
}
ALL_WI_ACTIONS = {**WI_ACTIONS, "put-back": R_WI_PUT_BACK}  # slice 1b adds the put-back route

SNOOZE_OK = "2026-10-07T10:00:00.000Z"  # NOW + 1 day: inside (now, now + 30 days]
SNOOZE_PAST = "2026-10-06T09:59:59.000Z"
SNOOZE_NOW = NOW
SNOOZE_TOO_FAR = "2026-11-06T10:00:01.000Z"  # NOW + 30 days + 1 s
MAX_BODY_BYTES = 32768  # API_PPL_11c.md section 7
WRITES_PER_MINUTE = 60  # API_PPL_11c.md section 7

UNIQUE_ID = "wi_never_made"
WORK_ITEM_BODY = {"title": "Water the plants", "source": {"kind": "manual", "ref": None}}
MEETING_BODY = {"title": "Weekly sync", "source": "upload", **ATTEST}
PERSON_BODY = {
    "display_name": "Nina Patel",
    "aliases": ["Nina"],
    "email": "nina.patel@example.com",
    "time_zone": "Asia/Kolkata",
    "preferred_channel": "web",
}


def at(*, days: int = 0, minutes: int = 0, seconds: int = 0, base: str = NOW) -> str:
    """`base` plus an offset, as a `common#timestamp` (three fractional digits, Z)."""
    moment = datetime.fromisoformat(base.replace("Z", "+00:00")) + timedelta(
        days=days, minutes=minutes, seconds=seconds
    )
    return moment.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%S.") + f"{moment.microsecond // 1000:03d}Z"


def path_of(route: tuple[str, str], **ids: str) -> str:
    out = route[1]
    for name, value in ids.items():
        out = out.replace("{" + name + "}", value)
    return out


# --- records --------------------------------------------------------------------------------------------------------


def transcript_case(name: str = "assignee_reads_one_quote") -> dict[str, Any]:
    return fixture_case("transcript", "valid", name)


def confirmed_item() -> dict[str, Any]:
    """Tilo's open item `wi_rate_sheet` for u_priya from u_owner's meeting `mt_q4_plan#ai1`, confirmed by u_owner."""
    return copy.deepcopy(transcript_case()["work_item"])


def as_proposed(item: dict[str, Any]) -> dict[str, Any]:
    out = copy.deepcopy(item)
    out.update(status="proposed", confirmed_by=None, updated_at=out["created_at"], history=out["history"][:1])
    return out


def proposed_launch_note() -> dict[str, Any]:
    """A second proposed item of the same meeting (action item ai2), for u_sam."""
    out = as_proposed(confirmed_item())
    out.update(
        id="wi_launch_note",
        owner=SAM,
        title="Draft the launch note",
        source={"kind": "meeting", "ref": "mt_q4_plan#ai2", "evidence": ["u0023"]},
    )
    return out


def gone_meeting(meeting: dict[str, Any], status: str) -> dict[str, Any]:
    """The meeting after capture was discarded (`discarded`) or after the owner's delete (`deleted`: the PE-19
    tombstone `tilo_people.stores.meeting_tombstone` makes)."""
    from tilo_people.stores import meeting_tombstone  # noqa: PLC0415

    if status == "deleted":
        return meeting_tombstone(meeting)
    out = copy.deepcopy(meeting)
    out.update(
        status="discarded",
        transcript=None,
        minutes=None,
        minutes_confirmed_by=None,
        delete_transcript_after=None,
        delete_minutes_after=None,
    )
    return out


def proposed_pin_from_meeting() -> dict[str, Any]:
    """A proposed team pin Tilo made from `mt_q4_plan` for u_owner (PE-08)."""
    return pl.pin(
        id="pb_from_meeting",
        org_id=ORG,
        scope={"kind": "team", "team": "tm_launch"},
        status="proposed",
        created_by=pl.maker_tilo("A_analyst", EARLY),
        set_up_by=OWNER,
        source={"kind": "meeting", "ref": "mt_q4_plan#ai1", "evidence": ["u0021"]},
        history=[pl.history_entry("A_analyst", "created", "proposed", EARLY)],
        created_at=EARLY,
        updated_at=EARLY,
    )


def proposed_calendar_from_meeting() -> dict[str, Any]:
    """A proposed calendar entry Tilo made from `mt_q4_plan` for its owner (PE-08)."""
    return pl.calendar_entry(
        id="ce_from_meeting",
        org_id=ORG,
        owner=OWNER,
        state="proposed",
        source={"kind": "tilo", "from": "meeting", "ref": "mt_q4_plan"},
        created_by=pl.maker_tilo("A_analyst", EARLY),
        confirmed_by=None,
        updated_at=EARLY,
    )


def work_rig(people_rig: Callable[..., Rig]) -> Rig:
    """The standard people, u_owner's meeting `mt_q4_plan` (no artifacts), u_priya's confirmed Tilo-made item
    `wi_rate_sheet` (assigned by u_owner) and her own item `wi_own1`; signed in as u_priya."""
    rig = people_rig()
    rig.add_people()
    rig.add("meetings", transcript_case()["meeting"])
    rig.add("work_items", confirmed_item())
    rig.add("work_items", own_item("wi_own1", PRIYA))
    rig.as_user(PRIYA)
    return rig


def meeting_rig(people_rig: Callable[..., Rig], case_name: str = "owner_reads_quotes") -> Rig:
    """`mt_q4_plan` as the quote cases store it (minuted, minutes confirmed, minutes and transcript artifacts in its
    own scope), the confirmed item `wi_rate_sheet` and the proposed item `wi_launch_note`; signed in as u_owner."""
    rig = people_rig()
    case = fixture_case("transcript", "valid", case_name)
    rig.seed_quote_case(case)
    rig.add("work_items", confirmed_item())
    rig.add("work_items", proposed_launch_note())
    rig.as_user(OWNER)
    return rig


def artifact_paths(rig: Rig) -> list[str]:
    """Every metadata record and blob key the artifact store holds (what a delete must empty)."""
    return sorted([*rig.meta.paths(""), *rig.blobs.keys("")])


def holds_artifact(rig: Rig, artifact_id: str) -> bool:
    return any(artifact_id in p for p in artifact_paths(rig))


def refusals(responses: list[Any]) -> set[str]:
    return {r.text for r in responses}


def valid_request(route: tuple[str, str]) -> dict[str, Any]:
    """A request of the right shape for each PPL-11c route: a refusal seen with it comes from the wiring or the rules,
    never from validation."""
    if route == R_WI_EDIT:
        return {"json": {"title": "Water the ferns"}}
    if route == R_WI_SNOOZE:
        return {"json": {"until": SNOOZE_OK}}
    if route == R_MT_EDIT:
        return {"json": {"title": "Renamed"}}
    if route in (R_TEAM_ADD, R_TEAM_REMOVE):
        return {"json": {"team": "tm_ops"}}
    if route == R_ROLE:
        return {"json": {"org_role": "owner"}}
    if route == R_PERSON_FIRST:
        return {"json": PERSON_BODY}
    if route[0] == "POST":
        return {"json": {}}
    return {}


def done_item(item_id: str = "wi_done1", owner: str = PRIYA) -> dict[str, Any]:
    """The owner's own item, already marked done."""
    return own_item(
        item_id,
        owner,
        status="done",
        history=[pl.history_entry(owner, "created", "open", EARLY), pl.history_entry(owner, "done", "done", EARLY)],
    )


def snoozed_item(item_id: str = "wi_snoozed", owner: str = PRIYA) -> dict[str, Any]:
    return own_item(item_id, owner, snoozed_until=SNOOZE_OK)


def item_for(rig: Rig, action: str) -> str:
    """The id of an item of `work_rig` the action applies to: a done item for reopen, a snoozed one for put-back, the
    item someone else assigned for not-mine, her own item otherwise."""
    if action == "reopen":
        rig.add("work_items", done_item())
        return "wi_done1"
    if action == "put-back":
        rig.add("work_items", snoozed_item())
        return "wi_snoozed"
    return "wi_rate_sheet" if action == "not-mine" else "wi_own1"


def act(rig: Rig, action: str, item_id: str, body: Any = None) -> Any:
    """POST one work-item action (`WI_ACTIONS` plus put-back) with a valid body unless `body` is given."""
    route = ALL_WI_ACTIONS[action]
    rig.require_route(route)
    request = valid_request(route) if body is None else {"json": body}
    return rig.client.post(path_of(route, work_item_id=item_id), **request)


# --- driving the app without the test client ------------------------------------------------------------------------


def stream_post(
    app: Any,
    path: str,
    *,
    total_bytes: int,
    declared_length: int | None = None,
    chunk: int = 1024,
    headers: dict[str, str] | None = None,
) -> tuple[int, int, dict[str, str], str]:
    """POST `total_bytes` of body, `chunk` bytes at a time, straight into the ASGI app (no client buffering), pulling
    the next chunk only when the app asks for it. Returns (status, bytes the app consumed, response headers, text).
    `declared_length` sets a `Content-Length` that need not match what is then sent."""
    import httpx  # noqa: PLC0415

    consumed = 0

    async def body() -> Any:
        nonlocal consumed
        sent = 0
        while sent < total_bytes:
            size = min(chunk, total_bytes - sent)
            sent += size
            consumed += size
            yield b" " * size

    async def go() -> tuple[int, dict[str, str], str]:
        transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            sent_headers = {"content-type": "application/json", **(headers or {})}
            if declared_length is not None:
                sent_headers["content-length"] = str(declared_length)
            response = await client.post(path, content=body(), headers=sent_headers)
            return response.status_code, dict(response.headers), response.text

    status, response_headers, text = asyncio.run(go())
    return status, consumed, response_headers, text


def padded(body: dict[str, Any], size: int) -> bytes:
    """`body` as JSON followed by spaces, exactly `size` bytes (still one valid JSON document)."""
    raw = json.dumps(body, separators=(",", ":")).encode()
    assert len(raw) <= size
    return raw + b" " * (size - len(raw))


# --- events ---------------------------------------------------------------------------------------------------------


def emitted(rig: Rig) -> list[tuple[str, dict[str, Any]]]:
    """(world id, the part tilo-api handed the single writer), in order."""
    return [(c.world_id, c.part) for c in rig.events.calls]


def stamped(rig: Rig, world_id: str) -> list[dict[str, Any]]:
    return list(rig.event_store.events.get(world_id, []))


def validate_event(event: dict[str, Any]) -> None:
    """EV-02 for a committed event: event.schema.json plus its type's data schema. `vis: []` (PE-12) is valid only
    once the ADR-0009 contract change lands (`district_list` still has `minItems: 1`), so the check runs on a copy
    with `vis` widened and `vis` itself is asserted by the tests."""
    from _api_lib import validate_event as check  # noqa: PLC0415

    check({**event, "vis": "all"})


def conforms_work_item(record: dict[str, Any]) -> bool:
    return conforms("work_item.schema.json", record)


# --- the SEC-15 gate and the fail-closed seams, for any list of routes -----------------------------------------------


def assert_gated(people_rig: Callable[..., Rig], routes: list[tuple[str, str]]) -> None:
    """Deployed, a visitor, an undeclared person and a signed-out caller are refused before any people seam, store or
    source is touched (403 `under_construction`, 403 `declaration_required`, 401), and none of the routes is public."""
    from _sec15_lib import (  # noqa: PLC0415
        CODE_DECLARATION_REQUIRED,
        CODE_UNDER_CONSTRUCTION,
        FakeAccessStore,
        concrete,
    )
    from tilo_api import access  # noqa: PLC0415

    rig = people_rig(deployed=True, access=FakeAccessStore({SAM: "visitor", PRIYA: "judge"}))
    rig.add_people()
    before = rig.snapshot()
    for route in routes:
        rig.require_route(route)
        assert route not in access.PUBLIC_ROUTES, route
        method, template = route
        rig.as_user(SAM)
        refused = rig.client.request(method, concrete(template), **valid_request(route))
        assert refused.status_code == 403 and refused.json()["code"] == CODE_UNDER_CONSTRUCTION, (route, refused.text)
        rig.as_user(OWNER)
        undeclared = rig.client.request(method, concrete(template), **valid_request(route))
        assert undeclared.status_code == 403 and undeclared.json()["code"] == CODE_DECLARATION_REQUIRED, route
        rig.sign_out()
        assert rig.client.request(method, concrete(template), **valid_request(route)).status_code == 401, route
    assert rig.resolved == [] and rig.store_calls == [] and rig.router_calls == [], "a refused request touched a seam"
    assert rig.snapshot() == before


def assert_unwired_is_503(people_rig: Callable[..., Rig], routes: list[tuple[str, str]], *seams: str) -> None:
    """With these seams unwired (production defaults) every route is 503 `not_configured`: never a 500, never an
    empty 200, never a 404 that looks like an answer; and nothing was written."""
    from _sec15_lib import concrete  # noqa: PLC0415

    rig = people_rig()
    rig.add_people()
    rig.as_user(OWNER)
    rig.unwire(*seams)
    before = rig.snapshot()
    for route in routes:
        rig.require_route(route)
        response = rig.client.request(route[0], concrete(route[1]), **valid_request(route))
        assert response.status_code == 503, (route, seams, response.status_code, response.text[:120])
        assert response.json() == {"detail": "not_configured"}, route
    assert rig.snapshot() == before
