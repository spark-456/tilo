"""PPL-11c slice 1: the person's own work items over HTTP (API_PPL_11c.md section 2): list, get, edit (title and due
phrase), done, snooze, reopen, not-mine. PE-03 (who reads), PE-07 (an owner's edit changes only title, due and snooze;
`source`, `owner`, `assigned_by`, `created_by`, `confirmed_by` never change), PE-19 (stamps are the actor and the server
clock), PE-29/PE-30 (the plate's actions, the history change names), FR-PA-01, FR-PA-03.

Every write: closed JSON body (415, 422), text cleaned then redacted, `decide` (a refusal is the one 404), the record
rebuilt from the stored one plus the actor and the server clock, `check_write` (409 `write_refused`), compare-and-set
(409 `version_conflict` after one attempt). A refused read or write is a byte-identical 404 for every cause. Nothing a
request names (`id`, `org_id`, `owner`, `source`, `source.ref`, `status`, `due`, `history`, a stamp) is ever used.
"""

from __future__ import annotations

import copy
import time

import pytest
from _ppl11a_lib import (
    DEV,
    MEERA,
    NOW,
    OTHER_ORG,
    OWNER,
    PRIYA,
    SAM,
    conforms,
    fake_token,
    find_row,
    history_of,
    own_item,
    refs,
    run_threads,
    u,
)
from _ppl11c_lib import (
    R_WI_GET,
    R_WI_LIST,
    SNOOZE_NOW,
    SNOOZE_OK,
    SNOOZE_PAST,
    SNOOZE_TOO_FAR,
    UNIQUE_ID,
    WI_ACTIONS,
    as_proposed,
    at,
    confirmed_item,
    path_of,
    proposed_launch_note,
    refusals,
    work_rig,
)
from _ppl11c_lib import (
    act as _act,
)
from _ppl11c_lib import (
    done_item as _done_item,
)
from _ppl11c_lib import (
    item_for as _item_for,
)
from fastapi.testclient import TestClient
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

IMMUTABLE = ("id", "org_id", "owner", "source", "created_by", "assigned_by", "confirmed_by", "flagged", "created_at")


def _without_history(record: dict) -> dict:
    return {k: v for k, v in record.items() if k not in ("history", "updated_at")}


# --- edit: title and due phrase only (PE-07) ------------------------------------------------------------------------


def test_PPL_11c_s1_PE_07_the_owner_edits_title_and_due_phrase_and_the_server_stamps_it(people_rig):
    """Given u_priya's own open item, when she edits its title and due phrase, then 200 with the full record: new
    title, `due_text` as cleaned, `due` computed by code in her zone (tomorrow = 2026-10-07 at 10:00 UTC, 15:30 in
    Kolkata), `updated_at` = server now, one history entry `edited` by her at now, version + 1; id, org, owner, source,
    created_by, created_at untouched."""
    rig = work_rig(people_rig)
    before = rig.stored("work_items", "wi_own1")
    version = rig.version_of("work_items", "wi_own1")
    response = _act(rig, "edit", "wi_own1", {"title": "Water the ferns", "due_text": "tomorrow"})
    assert response.status_code == 200, response.text[:300]
    stored = rig.stored("work_items", "wi_own1")
    assert response.json() == stored and conforms("work_item.schema.json", stored)
    assert (stored["title"], stored["due_text"], stored["due"]) == ("Water the ferns", "tomorrow", "2026-10-07")
    assert stored["updated_at"] == NOW
    assert stored["history"] == before["history"] + [{"at": NOW, "by": PRIYA, "change": "edited", "status": "open"}]
    assert all(stored[k] == before[k] for k in IMMUTABLE) and stored["status"] == "open"
    assert rig.version_of("work_items", "wi_own1") == version + 1


def test_PPL_11c_s1_PE_15_an_edit_can_clear_the_due_phrase_and_the_title_alone_keeps_it(people_rig):
    rig = work_rig(people_rig)
    assert _act(rig, "edit", "wi_own1", {"due_text": "tomorrow"}).status_code == 200
    kept = _act(rig, "edit", "wi_own1", {"title": "Water the cacti"}).json()
    assert (kept["due_text"], kept["due"]) == ("tomorrow", "2026-10-07"), "a title edit leaves the phrase alone"
    cleared = _act(rig, "edit", "wi_own1", {"due_text": None})
    assert cleared.status_code == 200 and (cleared.json()["due_text"], cleared.json()["due"]) == (None, None)


EDIT_FORBIDDEN = [
    {"source": {"kind": "meeting", "ref": "mt_someone_elses#ai9", "evidence": ["u0001"]}},
    {"source": {"ref": "mt_someone_elses#ai9"}},
    {"source.ref": "mt_someone_elses#ai9"},
    {"source": None},
    {"status": "done"},
    {"owner": "u_sam"},
    {"assigned_by": {"by": "u_sam", "at": NOW}},
    {"created_by": {"by": "person", "ref": "u_sam", "at": NOW}},
    {"confirmed_by": {"by": "u_sam", "at": NOW}},
    {"history": []},
    {"due": "2030-01-01"},
    {"flagged": False},
    {"id": "wi_other"},
    {"org_id": "org_elsewhere"},
    {"created_at": "2020-01-01T00:00:00.000Z"},
    {"updated_at": "2020-01-01T00:00:00.000Z"},
    {"snoozed_until": SNOOZE_OK},
    {"evidence": ["u0001"]},
    {"by": "u_sam"},
    {},
    [],
    "edit",
    {"title": "ok", "title ": "x"},
]


@pytest.mark.parametrize("body", EDIT_FORBIDDEN, ids=lambda b: str(b)[:40])
def test_PPL_11c_s1_PE_07_an_edit_body_names_a_title_or_a_due_phrase_and_nothing_else(people_rig, body):
    """A closed body (422, never echoed): `source` and `source.ref` are immutable stamps, `status` moves only by the
    named actions, `due` is code's, a snooze has its own route, nothing a stamp is made of comes from the request, and
    an edit with no field is no edit."""
    rig = work_rig(people_rig)
    before = rig.snapshot()
    response = _act(rig, "edit", "wi_own1", body)
    assert response.status_code == 422, (body, response.status_code, response.text[:200])
    assert rig.snapshot() == before, "a refused edit changes nothing"


@pytest.mark.parametrize("action", ["done", "snooze", "reopen", "not-mine"])
@pytest.mark.parametrize(
    "extra",
    [
        {"source": {"kind": "meeting", "ref": "mt_someone_elses#ai9", "evidence": []}},
        {"source": {"ref": "x"}},
        {"status": "open"},
        {"owner": "u_sam"},
        {"history": []},
        {"due": "2030-01-01"},
        {"assigned_by": None},
    ],
    ids=lambda e: next(iter(e)),
)
def test_PPL_11c_s1_PE_19_no_action_route_takes_a_field_it_does_not_name(people_rig, action, extra):
    """`source` and `source.ref` are refused on every route that changes an item, not only on edit."""
    rig = work_rig(people_rig)
    item_id = _item_for(rig, action)
    before = rig.snapshot()
    body = {**({"until": SNOOZE_OK} if action == "snooze" else {}), **extra}
    response = _act(rig, action, item_id, body)
    assert response.status_code == 422, (action, extra, response.status_code)
    assert rig.snapshot() == before


def test_PPL_11c_s1_SEC_01_a_caller_invented_key_is_never_echoed_back(people_rig):
    secret = fake_token()
    rig = work_rig(people_rig)
    for action in WI_ACTIONS:
        response = _act(rig, action, _item_for(rig, action), {"title": "x", secret: 1, "source": {secret: 1}})
        assert response.status_code == 422
        assert secret not in response.text and secret[:8] not in response.text, action


def test_PPL_11c_s1_SEC_01_text_is_cleaned_then_redacted_then_checked_like_every_other_write(people_rig):
    """Hidden format characters go first (so none can hide a secret or a link), the secret redactor runs on the title,
    the fake token is never stored or answered; a title over 140 characters after cleaning is a 422."""
    secret = fake_token()
    hidden = u(0x202E, 0x200B, 0x2028)
    rig = work_rig(people_rig)
    ok = _act(rig, "edit", "wi_own1", {"title": f"Wa{hidden}ter {secret}"})
    assert ok.status_code == 200, ok.text[:300]
    assert ok.json()["title"] == "Water [REDACTED]" and secret not in ok.text
    assert any(secret in call for call in rig.redactor.calls), "the redactor saw the text"
    assert all(h not in call for call in rig.redactor.calls for h in hidden), "cleaned before it was redacted"
    before = rig.snapshot()
    assert _act(rig, "edit", "wi_own1", {"title": "x" * 141}).status_code == 422
    assert _act(rig, "edit", "wi_own1", {"title": f"line{chr(10)}break"}).status_code == 422
    assert _act(rig, "edit", "wi_own1", {"due_text": "x" * 61}).status_code == 422
    assert rig.snapshot() == before


# --- done, snooze, reopen, not mine (PE-30: the plate's actions) ----------------------------------------------------


def test_PPL_11c_s1_PE_30_done_moves_the_item_to_done_and_to_the_done_lane(people_rig):
    rig = work_rig(people_rig)
    before = rig.stored("work_items", "wi_own1")
    response = _act(rig, "done", "wi_own1")
    assert response.status_code == 200, response.text[:300]
    stored = rig.stored("work_items", "wi_own1")
    assert response.json() == stored and conforms("work_item.schema.json", stored)
    assert stored["status"] == "done" and stored["updated_at"] == NOW
    assert stored["history"][-1] == {"at": NOW, "by": PRIYA, "change": "done", "status": "done"}
    assert stored["history"][:-1] == before["history"]
    assert _without_history(stored) == {**_without_history(before), "status": "done"}
    lane, row = find_row(rig.plate().json(), "work_item", "wi_own1")
    assert (lane, row["group"]) == ("parked", "done"), "the row left `rows` only after the write committed"


def test_PPL_11c_s1_PE_30_a_second_done_changes_nothing(people_rig):
    rig = work_rig(people_rig)
    assert _act(rig, "done", "wi_own1").status_code == 200
    snapshot = rig.snapshot()
    again = _act(rig, "done", "wi_own1")
    assert again.status_code in (404, 409), "a done item is not marked done twice"
    assert rig.snapshot() == snapshot, "no second `done` entry, no new version"


def test_PPL_11c_s1_PE_30_snooze_sets_the_date_and_parks_the_item(people_rig):
    rig = work_rig(people_rig)
    before = rig.stored("work_items", "wi_own1")
    response = _act(rig, "snooze", "wi_own1", {"until": SNOOZE_OK})
    assert response.status_code == 200, response.text[:300]
    stored = rig.stored("work_items", "wi_own1")
    assert response.json() == stored and conforms("work_item.schema.json", stored)
    assert stored["snoozed_until"] == SNOOZE_OK and stored["status"] == "open"
    assert stored["history"][-1] == {"at": NOW, "by": PRIYA, "change": "snoozed", "status": "open"}
    assert _without_history(stored) == {**_without_history(before), "snoozed_until": SNOOZE_OK}
    lane, row = find_row(rig.plate().json(), "work_item", "wi_own1")
    assert (lane, row["group"]) == ("parked", "snoozed")
    rig.set_now(at(days=1, minutes=1))
    assert find_row(rig.plate().json(), "work_item", "wi_own1")[0] == "rows", "back on the plate once it lapses"


@pytest.mark.parametrize(
    ("until", "problem"),
    [(SNOOZE_PAST, "snooze_range"), (SNOOZE_NOW, "snooze_range"), (SNOOZE_TOO_FAR, "snooze_range")],
    ids=["in the past", "exactly now", "more than 30 days"],
)
def test_PPL_11c_s1_PE_19_a_snooze_must_end_within_30_days_after_now(people_rig, until, problem):
    rig = work_rig(people_rig)
    before = rig.snapshot()
    response = _act(rig, "snooze", "wi_own1", {"until": until})
    assert response.status_code == 409 and problem in response.json()["problems"], response.text[:200]
    assert response.json()["code"] == "write_refused"
    assert rig.snapshot() == before


def test_PPL_11c_s1_PE_19_the_last_second_of_the_snooze_window_is_allowed_and_a_bad_timestamp_is_a_422(people_rig):
    rig = work_rig(people_rig)
    assert _act(rig, "snooze", "wi_own1", {"until": at(days=30)}).status_code == 200
    before = rig.snapshot()
    for until in ("tomorrow", "2026-10-07", "2026-10-07T10:00:00Z", 5, None, ""):
        assert _act(rig, "snooze", "wi_own1", {"until": until}).status_code == 422, until
    assert _act(rig, "snooze", "wi_own1", {}).status_code == 422
    assert rig.snapshot() == before


def test_PPL_11c_s1_PE_30_reopen_moves_a_done_item_back_to_open(people_rig):
    rig = work_rig(people_rig)
    rig.add("work_items", _done_item())
    before = rig.stored("work_items", "wi_done1")
    response = _act(rig, "reopen", "wi_done1")
    assert response.status_code == 200, response.text[:300]
    stored = rig.stored("work_items", "wi_done1")
    assert response.json() == stored and conforms("work_item.schema.json", stored)
    assert stored["status"] == "open" and stored["updated_at"] == NOW
    assert stored["history"][-1] == {"at": NOW, "by": PRIYA, "change": "reopened", "status": "open"}
    assert stored["history"][:-1] == before["history"]
    assert find_row(rig.plate().json(), "work_item", "wi_done1")[0] == "rows"


def test_PPL_11c_s1_PE_07_reopen_is_only_for_a_done_item(people_rig):
    rig = work_rig(people_rig)
    before = rig.snapshot()
    response = _act(rig, "reopen", "wi_own1")
    assert response.status_code == 409 and response.json()["code"] == "write_refused", response.text[:200]
    assert rig.snapshot() == before


def test_PPL_11c_s1_PE_29_not_mine_asks_the_assigner_and_parks_the_item_without_moving_its_status(people_rig):
    """`not_mine` is for an item someone else assigned: the item stays `open`, one history entry
    `reassign_requested`, and it leaves `rows` for the `asked` lane until the assigner acts."""
    rig = work_rig(people_rig)
    before = rig.stored("work_items", "wi_rate_sheet")
    response = _act(rig, "not-mine", "wi_rate_sheet")
    assert response.status_code == 200, response.text[:300]
    stored = rig.stored("work_items", "wi_rate_sheet")
    assert response.json() == stored and conforms("work_item.schema.json", stored)
    assert stored["status"] == "open" and stored["owner"] == PRIYA
    assert stored["history"][-1] == {"at": NOW, "by": PRIYA, "change": "reassign_requested", "status": "open"}
    assert _without_history(stored) == _without_history(before)
    plate = rig.plate().json()
    lane, row = find_row(plate, "work_item", "wi_rate_sheet")
    assert (lane, row["group"]) == ("parked", "asked") and ("work_item", "wi_rate_sheet") not in refs(plate)


def test_PPL_11c_s1_PE_29_not_mine_is_refused_for_an_item_nobody_assigned_and_for_one_already_asked(people_rig):
    rig = work_rig(people_rig)
    before = rig.snapshot()
    own = _act(rig, "not-mine", "wi_own1")
    assert own.status_code == 409 and own.json()["problems"], "her own item: there is nobody to ask"
    assert rig.snapshot() == before
    assert _act(rig, "not-mine", "wi_rate_sheet").status_code == 200
    after = rig.snapshot()
    again = _act(rig, "not-mine", "wi_rate_sheet")
    assert again.status_code == 409 and again.json()["problems"]
    assert rig.snapshot() == after, "asking twice adds no entry"


# --- who may act (PE-03): one 404 for everyone else -----------------------------------------------------------------


@pytest.mark.parametrize("action", list(WI_ACTIONS))
def test_PPL_11c_s1_PE_03_everyone_but_the_owner_gets_the_one_404(people_rig, action):
    """A teammate, an unrelated member, an org owner, the assigner of a confirmed item, a person with no record, the
    owner of a proposed item, another org's id, an unknown id and a malformed id: the same 404 body, and nothing
    changes. The assigner reads an item's status only (PE-03): she cannot touch it."""
    rig = work_rig(people_rig)
    item_id = _item_for(rig, action)
    rig.add("work_items", proposed_launch_note())
    foreign = {**confirmed_item(), "id": "wi_elsewhere", "org_id": OTHER_ORG}
    rig.real.work_items.create(foreign)
    before = rig.snapshot()
    bodies = []
    for actor in (DEV, SAM, MEERA, OWNER, "u_ghost"):
        rig.as_user(actor)
        for target in (item_id, "wi_launch_note", "wi_elsewhere", UNIQUE_ID, "not-an-id", "wi_" + "x" * 60):
            response = _act(rig, action, target)
            assert response.status_code == 404, (actor, target, response.status_code, response.text[:120])
            bodies.append(response)
    assert len(refusals(bodies)) == 1, "one byte-identical body whatever the cause"
    assert rig.snapshot() == before


@pytest.mark.parametrize("action", ["edit", "done", "snooze", "not-mine"])
def test_PPL_11c_s1_PE_19_a_lost_compare_and_set_is_a_409_after_one_attempt(people_rig, action):
    rig = work_rig(people_rig)
    item_id = _item_for(rig, action)
    before = rig.snapshot()
    rig.conflicting_stores("work_items")
    response = _act(rig, action, item_id)
    assert response.status_code == 409 and response.json()["code"] == "version_conflict", response.text[:200]
    assert [c for c in rig.store_calls if c[:2] == ("work_item", "replace")] == [("work_item", "replace", rig.org)]
    assert rig.snapshot() == before


def test_PPL_11c_s1_PE_19_eight_racing_done_calls_leave_exactly_one_done_entry(people_rig):
    rig = work_rig(people_rig)
    version = rig.version_of("work_items", "wi_own1")
    rig.require_route(WI_ACTIONS["done"])

    def done(_: int) -> int:
        with TestClient(rig.app, raise_server_exceptions=False) as client:
            return client.post("/v1/work-items/wi_own1/done", json={}).status_code

    statuses = run_threads(8, done)
    assert statuses.count(200) == 1 and all(s in (200, 404, 409) for s in statuses), statuses
    assert [h["change"] for h in rig.stored("work_items", "wi_own1")["history"]].count("done") == 1
    assert rig.version_of("work_items", "wi_own1") == version + 1


@pytest.mark.parametrize("action", list(WI_ACTIONS))
def test_PPL_11c_s1_BQ_PPL11C_12_a_write_reads_no_whole_org_directory_and_at_most_two_person_records(
    people_rig, action
):
    """No per-write listing of every person of the org (PPL-11a follow-up #464): the actor's own record is read by id,
    and a person other than the actor at most once more."""
    rig = work_rig(people_rig)
    item_id = _item_for(rig, action)
    del rig.store_calls[:]
    assert _act(rig, action, item_id).status_code in (200, 409)
    assert ("person", "list", rig.org) not in rig.store_calls, "the whole org directory was listed"
    assert len([c for c in rig.store_calls if c[:2] == ("person", "get")]) <= 2


def test_PPL_11c_s1_PE_19_an_item_with_a_huge_history_is_refused_fast_and_never_decided(people_rig):
    from tilo_people.errors import PeopleInputError  # noqa: PLC0415

    rig = work_rig(people_rig)
    big = own_item("wi_big", PRIYA, history=history_of(5000))
    try:
        rig.add("work_items", big)
    except PeopleInputError:
        pytest.skip("the contract now caps work_item.history; the store refuses the record")
    before = rig.snapshot()
    started = time.monotonic()
    for action in WI_ACTIONS:
        assert _act(rig, action, "wi_big").status_code == 404, action
    assert rig.client.get("/v1/work-items/wi_big").status_code == 404
    assert time.monotonic() - started < 3.0
    assert rig.snapshot() == before


# --- get and list (PE-03) -------------------------------------------------------------------------------------------


def test_PPL_11c_s1_PE_03_the_owner_reads_the_item_in_full_and_the_assigner_reads_its_status_only(people_rig):
    rig = work_rig(people_rig)
    rig.require_route(R_WI_GET)
    stored = rig.stored("work_items", "wi_rate_sheet")
    owner = rig.client.get("/v1/work-items/wi_rate_sheet")
    assert owner.status_code == 200 and owner.json() == stored
    rig.as_user(OWNER)
    assigner = rig.client.get("/v1/work-items/wi_rate_sheet")
    assert assigner.status_code == 200
    assert assigner.json() == {k: stored[k] for k in ("id", "title", "status", "due")}, "status only (PE-03)"


def test_PPL_11c_s1_PE_03_everyone_else_and_every_proposed_item_get_the_one_404_on_a_read(people_rig):
    rig = work_rig(people_rig)
    rig.add("work_items", proposed_launch_note())
    rig.require_route(R_WI_GET)
    seen = []
    for actor in (DEV, SAM, MEERA, "u_ghost"):
        rig.as_user(actor)
        seen.append(rig.client.get("/v1/work-items/wi_rate_sheet"))
        seen.append(rig.client.get("/v1/work-items/wi_own1"))
    for actor in (SAM, OWNER, MEERA):  # the assignee and the assigner of a proposed item read nothing (PE-03)
        rig.as_user(actor)
        seen.append(rig.client.get("/v1/work-items/wi_launch_note"))
    rig.as_user(PRIYA)
    seen += [rig.client.get(f"/v1/work-items/{i}") for i in (UNIQUE_ID, "nope", "wi_" + "x" * 60)]
    assert {r.status_code for r in seen} == {404} and len(refusals(seen)) == 1


def test_PPL_11c_s1_PE_03_the_list_is_the_callers_own_readable_items_in_a_fixed_order(people_rig):
    """Her open, done and dropped items only: never a proposed item, an item of someone else, or one she may not read;
    ordered by due date (none last), then creation, then id; each the full record."""
    rig = work_rig(people_rig)
    rig.add("work_items", _done_item("wi_done1"))
    rig.add("work_items", own_item("wi_due_later", PRIYA, due="2026-12-01", created_at=at(days=-1)))
    rig.add("work_items", own_item("wi_due_soon", PRIYA, due="2026-10-08", created_at=at(days=-2)))
    rig.add("work_items", own_item("wi_a_none", PRIYA, created_at=at(days=-3)))
    rig.add("work_items", own_item("wi_sam", SAM))
    rig.add("work_items", as_proposed({**confirmed_item(), "id": "wi_prop_priya"}))
    rig.require_route(R_WI_LIST)
    response = rig.client.get("/v1/work-items")
    assert response.status_code == 200, response.text[:300]
    body = response.json()
    assert set(body) == {"items", "truncated"} and body["truncated"] is False
    ids = [i["id"] for i in body["items"]]
    # due ascending (none last), then created_at, then id: wi_done1 and wi_own1 share a creation time
    assert ids == ["wi_due_soon", "wi_rate_sheet", "wi_due_later", "wi_a_none", "wi_done1", "wi_own1"], ids
    assert all(item == rig.stored("work_items", item["id"]) for item in body["items"])


def test_PPL_11c_s1_PE_03_the_list_can_be_filtered_by_status_and_a_bad_status_is_a_422(people_rig):
    rig = work_rig(people_rig)
    rig.add("work_items", _done_item("wi_done1"))
    rig.require_route(R_WI_LIST)
    done = rig.client.get("/v1/work-items", params={"status": "done"})
    assert done.status_code == 200 and [i["id"] for i in done.json()["items"]] == ["wi_done1"]
    opened = rig.client.get("/v1/work-items", params={"status": "open"})
    assert {i["id"] for i in opened.json()["items"]} == {"wi_own1", "wi_rate_sheet"}
    for bad in ("proposed", "all", "", "open,done"):
        assert rig.client.get("/v1/work-items", params={"status": bad}).status_code == 422, bad


def test_PPL_11c_s1_PE_27_the_list_holds_at_most_200_items_and_says_when_there_are_more(people_rig):
    rig = work_rig(people_rig)
    for i in range(201):
        rig.add("work_items", own_item(f"wi_bulk_{i:03d}", PRIYA, due="2026-12-01"))
    rig.require_route(R_WI_LIST)
    body = rig.client.get("/v1/work-items").json()
    assert len(body["items"]) == 200 and body["truncated"] is True


def test_PPL_11c_s1_PE_03_a_person_with_no_record_has_no_list_and_no_directory_is_read(people_rig):
    rig = work_rig(people_rig)
    rig.require_route(R_WI_LIST)
    del rig.store_calls[:]
    assert rig.client.get("/v1/work-items").status_code == 200
    assert ("person", "list", rig.org) not in rig.store_calls
    rig.as_user("u_ghost")
    assert rig.client.get("/v1/work-items").status_code == 404, "no person record: the one 404"


# --- invariants (property tests) ------------------------------------------------------------------------------------

ACTION_STEPS = st.lists(
    st.tuples(st.sampled_from(["edit", "snooze", "done", "reopen", "not-mine"]), st.integers(0, 90)),
    max_size=10,
)


@settings(max_examples=25, deadline=None, suppress_health_check=[HealthCheck.function_scoped_fixture])
@given(steps=ACTION_STEPS)
def test_PPL_11c_s1_PE_07_any_sequence_of_actions_keeps_the_stamps_the_history_and_the_schema(people_rig, steps):
    """Whatever an owner does and whenever she does it: a success adds exactly one history entry at the server now by
    her, bumps the version once, leaves every immutable field alone and stays schema-valid; a refusal changes
    nothing."""
    rig = work_rig(people_rig)
    original = rig.stored("work_items", "wi_rate_sheet")
    for n, (action, minutes) in enumerate(steps):
        rig.set_now(at(minutes=minutes + n))
        before = rig.stored("work_items", "wi_rate_sheet")
        version = rig.version_of("work_items", "wi_rate_sheet")
        body = {"until": at(days=1, minutes=minutes + n)} if action == "snooze" else {"title": f"Rate sheet {n}"}
        response = _act(rig, action, "wi_rate_sheet", body if action in ("snooze", "edit") else {})
        after = rig.stored("work_items", "wi_rate_sheet")
        assert response.status_code in (200, 404, 409), (action, response.status_code)
        if response.status_code == 200:
            assert rig.version_of("work_items", "wi_rate_sheet") == version + 1
            assert after["history"][:-1] == before["history"] and len(after["history"]) == len(before["history"]) + 1
            assert (after["history"][-1]["at"], after["history"][-1]["by"]) == (rig.clock, PRIYA)
            assert after["updated_at"] == rig.clock and conforms("work_item.schema.json", after)
        else:
            assert after == before and rig.version_of("work_items", "wi_rate_sheet") == version
        assert all(after[k] == original[k] for k in IMMUTABLE), "an immutable stamp changed"
        assert after["source"] == original["source"], "source.ref never changes"


def test_PPL_11c_s1_PE_19_the_edit_body_is_copied_never_mass_assigned(people_rig):
    """Sending the whole stored record back as an edit is a 422 and changes nothing."""
    rig = work_rig(people_rig)
    before = rig.snapshot()
    whole = copy.deepcopy(rig.stored("work_items", "wi_own1"))
    assert _act(rig, "edit", "wi_own1", whole).status_code == 422
    assert rig.snapshot() == before


def test_PPL_11c_s1_PE_19_non_json_bodies_are_415_and_broken_json_is_422(people_rig):
    rig = work_rig(people_rig)
    before = rig.snapshot()
    route = WI_ACTIONS["edit"]
    rig.require_route(route)
    path = path_of(route, work_item_id="wi_own1")
    assert (
        rig.client.post(
            path, content="title=x", headers={"content-type": "application/x-www-form-urlencoded"}
        ).status_code
        == 415
    )
    assert rig.client.post(path, content="{}", headers={"content-type": "text/plain"}).status_code == 415
    assert rig.client.post(path, content="{not json", headers={"content-type": "application/json"}).status_code == 422
    assert rig.snapshot() == before
