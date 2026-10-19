"""PPL-11c-FS-2 (b), the event writer behind the work-item writes (PE-12 `work_item.created` and `work_item.changed`,
`vis: []`; PE-30; HR-1; API_PPL_11c_FS_2.md section 4).

The single writer (`deps.get_event_writer`) is idempotent by part id: the same id and content again answers the
committed event and appends nothing (EV-10; the harness `WorldWriter.emit(event_id=)` and every double in this suite).
What FS-2 adds is the caller's half. A durable writer can fail *ambiguously*: the append landed and the answer was
lost. Today the route then undoes the record and answers 503, leaving an event for a record that no longer exists
(HR-1). The route must instead resend the same part (same id, same content), once, so the writer commits it once; and
when the store is really down, the answer is the one fixed 503 with the write undone, as today.

Pinned defaults (the PRD names none; see the report): a work-item write makes at most 3 `append` attempts in all, one
part id for the request, resent unchanged; one lost or failed attempt is survived. A write whose every attempt fails is
the fixed 503 `{"detail": "unavailable"}` with the record undone (a part that did land on an earlier ambiguous attempt
cannot be taken back: the event schema has no compensating type; BQ proposed).
"""

from __future__ import annotations

import logging

import pytest
from _ppl11c_fs2_fake import SENTINEL
from _ppl11c_fs2_lib import (
    ScriptedWriter,
    all_stamped_events,
    firestore_rig,
    fresh_token,
    stamped_events_of,
    work_items_titled,
)
from _ppl11c_lib import WORK_ITEM_BODY, act, item_for, meeting_rig, work_rig
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

KINDS = ["create", "edit", "done", "snooze", "not-mine", "confirm"]
MAX_ATTEMPTS = 3


def _scripted(people_rig, kind, script):
    """(rig, send): `send()` makes one write of `kind`; the event writer follows `script`."""
    if kind == "confirm":
        rig = meeting_rig(people_rig)
        rig.events = ScriptedWriter(rig.event_store, script)
        return rig, lambda: rig.post("/v1/work-items/wi_launch_note/confirm")
    rig = work_rig(people_rig)
    rig.events = ScriptedWriter(rig.event_store, script)
    if kind == "create":
        return rig, lambda: rig.post("/v1/work-items", WORK_ITEM_BODY)
    item_id = item_for(rig, kind)
    return rig, lambda: act(rig, kind, item_id)


def _records(rig):
    return {s.record["id"]: s.record for s in rig.real.work_items.list(rig.org)}


def _same_part(attempts):
    assert attempts, "the writer was never asked"
    assert len({a["id"] for a in attempts}) == 1, "one part id per request, resent unchanged"
    assert all(a == attempts[0] for a in attempts), "and the same content every time"
    assert attempts[0]["vis"] == [] and attempts[0]["authz"] is None


@pytest.mark.parametrize("kind", KINDS)
def test_PPL_11c_FS_2_event_01_an_append_that_landed_and_lost_its_answer_is_resent_and_recorded_once(people_rig, kind):
    rig, send = _scripted(people_rig, kind, ["lands"])
    response = send()
    assert response.status_code in (200, 201), (kind, response.status_code, response.text[:200])
    assert len(rig.events.attempts) == 2, "the same part is handed over once more"
    _same_part(rig.events.attempts)
    events = all_stamped_events(rig)
    assert len(events) == 1 and events[0]["id"] == rig.events.attempts[0]["id"], "committed once"
    if kind == "create":
        assert events[0]["type"] == "work_item.created"
        assert events[0]["data"]["work_item_id"] == response.json()["id"]
        assert rig.stored("work_items", response.json()["id"]) is not None, "and the record it names is there"
    assert events[0]["vis"] == []


@pytest.mark.parametrize("kind", KINDS)
def test_PPL_11c_FS_2_event_02_an_append_that_failed_before_landing_is_resent_once_and_recorded_once(people_rig, kind):
    rig, send = _scripted(people_rig, kind, ["fail"])
    response = send()
    assert response.status_code in (200, 201), (kind, response.status_code, response.text[:200])
    assert len(rig.events.attempts) == 2
    _same_part(rig.events.attempts)
    assert len(all_stamped_events(rig)) == 1


@pytest.mark.parametrize("kind", KINDS)
def test_PPL_11c_FS_2_event_03_when_the_store_stays_down_the_answer_is_one_fixed_503_and_the_write_is_undone(
    people_rig, kind, caplog
):
    rig, send = _scripted(people_rig, kind, ["fail"] * 6)
    caplog.set_level(logging.DEBUG)
    before = _records(rig)
    response = send()
    assert response.status_code == 503 and response.json() == {"detail": "unavailable"}, response.text[:200]
    assert response.headers["cache-control"] == "no-store"
    assert 1 <= len(rig.events.attempts) <= MAX_ATTEMPTS, "bounded: a dead store is not hammered"
    _same_part(rig.events.attempts)
    assert _records(rig) == before, "the record is as it was (a created one is gone)"
    assert all_stamped_events(rig) == []
    assert SENTINEL not in response.text and SENTINEL not in caplog.text, "the library's error text is never echoed"


def test_PPL_11c_FS_2_event_04_a_replay_of_an_idempotent_create_whose_event_was_lost_says_nothing_new(people_rig):
    rig, _ = _scripted(people_rig, "create", ["lands"])
    key, body = fresh_token(), {**WORK_ITEM_BODY, "title": "Lost answer, kept key"}
    first = rig.client.post("/v1/work-items", json=body, headers={"Idempotency-Key": key})
    assert first.status_code == 201
    attempts = len(rig.events.attempts)
    again = rig.client.post("/v1/work-items", json=body, headers={"Idempotency-Key": key})
    assert again.status_code == 201 and again.content == first.content
    assert len(rig.events.attempts) == attempts, "a replay appends nothing, not even a resend"
    assert len(all_stamped_events(rig)) == 1


STEP = st.lists(st.sampled_from(["ok", "lands", "fail"]), max_size=5)


@settings(max_examples=40, deadline=None, suppress_health_check=[HealthCheck.function_scoped_fixture])
@given(script=STEP)
def test_PPL_11c_FS_2_event_05_whatever_the_writer_does_a_create_is_recorded_at_most_once_and_never_without_its_event(
    people_rig, script
):
    """Property over scripted writers: one part id per request and at most three attempts; the Desk world never holds
    two events for the write; a created answer has exactly one event naming its record; a refused one left no record."""
    title = f"Scripted {fresh_token()}"
    rig = work_rig(people_rig)
    rig.events = ScriptedWriter(rig.event_store, script)
    response = rig.post("/v1/work-items", {**WORK_ITEM_BODY, "title": title})
    attempts = rig.events.attempts
    steps = [*script, "ok", "ok"]
    if steps[0] == "ok" or steps[1] == "ok":
        assert response.status_code == 201, "at most one lost or failed attempt is survived"
    assert 1 <= len(attempts) <= MAX_ATTEMPTS
    _same_part(attempts)
    events = all_stamped_events(rig)
    assert len(events) <= 1, "a retry appends once"
    made = work_items_titled(rig, title)
    if response.status_code == 201:
        assert len(made) == 1 and len(events) == 1
        assert events[0]["data"]["work_item_id"] == made[0]["id"] == response.json()["id"]
    else:
        assert response.status_code == 503 and response.json() == {"detail": "unavailable"}
        assert made == [], "a refused create leaves no record"


def test_PPL_11c_FS_2_event_06_the_parts_of_a_work_item_write_on_firestore_stores_are_resent_the_same_way(people_rig):
    """The same on the Firestore people stores: the record is created once, its event committed once."""
    rig = firestore_rig(people_rig)
    rig.events = ScriptedWriter(rig.event_store, ["lands"])
    title = f"On firestore {fresh_token()}"
    response = rig.post("/v1/work-items", {**WORK_ITEM_BODY, "title": title})
    assert response.status_code == 201, response.text[:200]
    [made] = work_items_titled(rig, title)
    assert len(rig.events.attempts) == 2 and len(stamped_events_of(rig, made["id"])) == 1
    _same_part(rig.events.attempts)


def test_PPL_11c_FS_2_guard_event_distinct_requests_never_share_a_part_id(people_rig):
    """Passes today and must stay: the id is minted per request, so two writes are two events (an id derived from
    something constant would turn the second write's event into a silent no-op)."""
    rig = work_rig(people_rig)
    rig.events = ScriptedWriter(rig.event_store, [])
    for n in range(5):
        assert rig.post("/v1/work-items", {**WORK_ITEM_BODY, "title": f"Item {n}"}).status_code == 201
    ids = [a["id"] for a in rig.events.attempts]
    assert len(ids) == 5 and len(set(ids)) == 5
    assert len(all_stamped_events(rig)) == 5
