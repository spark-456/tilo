"""PEOPLE-SEAMS-1: the production plate sources and source owners (deps.get_plate_sources, deps.get_source_owners) read
the API's own store for the signed-in person only (ADR-0021, PE-8, PE-26, PE-27). Each test asks as the owner of some
records and then as someone else, a viewer-like stranger, an unknown id and a hostile one: nothing of another person
comes back. No network; the mail collection is a Firestore-shaped fake."""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from _cards_lib import FakeClock, add_seconds
from _peopleseams1_lib import (
    GATE_OUTBOX,
    NOW,
    OTHER,
    OWNER,
    STAMP,
    W1,
    W2,
    W3,
    W4,
    W5,
    card,
    ev,
    mail_doc,
    process,
    rig_with_mail,
    run_with_cards,
    seed_bare_world,
    seed_world,
)
from _pw1b_lib import make_rig, started
from fastapi import HTTPException
from tilo_api import deps, seams_store

STRANGER = "u_ps1_stranger"
HOSTILE = ["", "u_", "u_a\n", "../u_x", "u_" + "a" * 49, "U_abc", 5, None, "u_ａｂｃ", "u_a/b"]


def _sources(store):
    return seams_store.StorePlateSources(store)


# -- cards ----------------------------------------------------------------------------------------------------------


def test_PEOPLE_SEAMS_1_cards_are_only_the_signed_in_persons_open_cards():
    store = process(make_rig("memory"))
    clock = FakeClock(NOW)
    seed_world(store, W1, OWNER)
    seed_world(store, W2, OTHER)
    mine = run_with_cards(store, W1, OWNER, clock)
    theirs = run_with_cards(store, W2, OTHER, clock)
    assert mine.submit(card(W1, 1, name="needs_you_blocked")).outcome == "accepted"
    assert theirs.submit(card(W2, 2, name="needs_you_blocked")).outcome == "accepted"
    ours = _sources(store).cards(OWNER)
    assert [f["data"]["world_id"] for f in ours] == [W1]
    assert ours[0]["world_owner"] == OWNER and ours[0]["approver"] is None and ours[0]["answered"] is False
    assert [f["data"]["world_id"] for f in _sources(store).cards(OTHER)] == [W2]
    assert _sources(store).cards(STRANGER) == []


@pytest.mark.parametrize("who", HOSTILE)
def test_PEOPLE_SEAMS_1_a_malformed_user_id_reads_nothing(who):
    store = process(make_rig("memory"))
    seed_world(store, W1, OWNER)
    run_with_cards(store, W1, OWNER, FakeClock(NOW)).submit(card(W1, 1, name="needs_you_blocked"))
    sources = _sources(store)
    assert sources.cards(who) == [] and sources.runs(who) == [] and sources.mail(who) == []


def test_PEOPLE_SEAMS_1_a_gate_names_its_live_approver_and_only_a_gate_and_only_until_the_link_ends():
    store = process(make_rig("memory"))
    clock = FakeClock(NOW)
    seed_world(store, W1, OWNER)
    cards = run_with_cards(store, W1, OWNER, clock)
    gate, question = card(W1, 1), card(W1, 2, name="needs_you_blocked")
    assert cards.submit(gate, outbox_id=GATE_OUTBOX).outcome == "accepted"
    assert cards.submit(question, assignee=STRANGER).outcome == "accepted"  # assigned, but not a gate
    cards.share_gate(W1, gate["id"], approver=STRANGER, until=add_seconds(NOW, 60))
    seen = _sources(store).cards(STRANGER)
    assert {f["data"]["kind"] for f in seen} == {"gate"} and all(f["approver"] == STRANGER for f in seen)
    assert all(f["world_owner"] == OWNER for f in seen), "the owner is named, the card is theirs"
    clock.advance(120)
    assert _sources(store).cards(STRANGER) == [], "an ended share link is no longer the Approver's"
    assert _sources(store).cards(OTHER) == []
    assert len(_sources(store).cards(OWNER)) >= 2, "the owner keeps every open card of their world"


def test_PEOPLE_SEAMS_1_a_world_record_that_is_not_the_runs_owner_hides_its_cards():
    store = process(make_rig("memory"))
    seed_world(store, W1, OTHER)  # the durable record says OTHER owns it ...
    run_with_cards(store, W1, OWNER, FakeClock(NOW)).submit(
        card(W1, 1, name="needs_you_blocked")
    )  # ... the run says OWNER
    assert _sources(store).cards(OWNER) == [], "both the run and the stored world must name the person"


def test_PEOPLE_SEAMS_1_a_huge_list_is_cut_at_the_bound_oldest_first():
    store = process(make_rig("memory"))
    seed_world(store, W1, OWNER)
    cards = run_with_cards(store, W1, OWNER, FakeClock(NOW))
    for n in range(seams_store.MAX_FACTS + 25):
        stamp = add_seconds("2026-09-29T00:00:00.000Z", n)
        cards.submit(card(W1, n, name="needs_you_blocked", created_at=stamp), merge=False)
    found = _sources(store).cards(OWNER)
    assert len(found) == seams_store.MAX_FACTS
    assert [f["data"]["created_at"] for f in found] == sorted(f["data"]["created_at"] for f in found)


# -- runs -----------------------------------------------------------------------------------------------------------


def _runs_store():
    rig = make_rig("memory")
    store = process(rig)
    seed_world(store, W1, OWNER, deadline="2026-10-20")
    seed_world(store, W2, OTHER)
    seed_world(store, W3, OWNER)  # completed
    seed_world(store, W4, OWNER)  # paused
    seed_world(store, W5, OWNER)  # blocked
    store.worlds[W4].paused = True
    store.events[W1] = [ev("world.requested"), ev("world.started")]
    store.events[W2] = [ev("world.started")]
    store.events[W3] = [ev("world.started"), ev("world.completed")]
    store.events[W4] = [ev("world.started")]
    store.events[W5] = [ev("world.started"), ev("agent.blocked", actor="A_ps1_x")]
    return rig, store


def test_PEOPLE_SEAMS_1_runs_are_the_persons_running_or_blocked_worlds_with_their_brief():
    _, store = _runs_store()
    facts = _sources(store).runs(OWNER)
    assert [(f["world_id"], f["state"]) for f in facts] == [(W1, "running"), (W5, "blocked")]
    first = facts[0]
    assert first | {"started_at": STAMP} == {
        "world_id": W1, "world_owner": OWNER, "state": "running", "goal": "Compare prices", "deadline": "2026-10-20",
        "started_at": STAMP,
    }  # fmt: skip
    assert [f["world_id"] for f in _sources(store).runs(OTHER)] == [W2]
    assert _sources(store).runs(STRANGER) == []


def test_PEOPLE_SEAMS_1_a_recovered_agent_clears_blocked_and_an_unstarted_world_is_not_a_run():
    _, store = _runs_store()
    store.events[W5] += [ev("agent.recovered", actor="A_ps1_x")]
    store.events[W1] = [ev("world.requested")]
    assert [(f["world_id"], f["state"]) for f in _sources(store).runs(OWNER)] == [(W5, "running")]


def test_PEOPLE_SEAMS_1_a_task_without_a_goal_has_a_null_goal_and_a_bad_date_is_dateless():
    store = process(make_rig("memory"))
    seed_world(store, W1, OWNER, goal=None)
    seed_world(store, W2, OWNER, deadline="soon")
    store.events[W1] = store.events[W2] = [ev("world.started")]
    facts = _sources(store).runs(OWNER)
    assert [(f["world_id"], f["goal"], f["deadline"]) for f in facts] == [
        (W1, None, None),
        (W2, "Compare prices", None),
    ]


def test_PEOPLE_SEAMS_1_a_scheduled_style_world_with_no_stored_task_is_a_run_with_the_in_process_brief():
    store = process(make_rig("memory"))
    for world, owner in ((W1, OWNER), (W2, OTHER), (W3, OWNER)):
        seed_bare_world(store, world, owner)
    store.events[W1] = store.events[W2] = store.events[W3] = [ev("world.started")]
    brief = {"goal": "Weekly report", "deadline": "2026-10-20"}
    store.runs[W1] = SimpleNamespace(owner=OWNER, brief=brief)  # a routine's Run: its task was never stored
    store.runs[W2] = SimpleNamespace(owner=OTHER, brief={"goal": "Not yours"})
    facts = _sources(store).runs(OWNER)
    assert [(f["world_id"], f["goal"], f["deadline"]) for f in facts] == [
        (W1, "Weekly report", "2026-10-20"),
        (W3, None, None),  # no task, no Run: still a running world of the person, with no title
    ]
    assert [f["world_id"] for f in _sources(store).runs(OTHER)] == [W2]
    assert _sources(store).runs(STRANGER) == []


def test_PEOPLE_SEAMS_1_a_run_brief_of_another_owner_is_not_read_and_desk_worlds_are_not_runs():
    store = process(make_rig("memory"))
    seed_bare_world(store, W1, OWNER)
    store.events[W1] = [ev("world.started")]
    store.runs[W1] = SimpleNamespace(owner=OTHER, brief={"goal": "Someone else's goal"})
    seams_store.StoreDeskWorlds(store).desk_world(deps.ORG_ID, OWNER)  # a Desk world: no `world.started`
    facts = _sources(store).runs(OWNER)
    assert [(f["world_id"], f["goal"]) for f in facts] == [(W1, None)]


def test_PEOPLE_SEAMS_1_a_task_is_found_by_its_world_and_a_task_of_another_owner_gives_no_goal():
    rig = make_rig("memory")
    first = process(rig)
    seed_world(first, W1, OWNER)
    seed_world(first, W2, OTHER)  # the stored task and world are OTHER's
    restarted = process(rig)
    assert restarted.load_world_task(W1).owner == OWNER and len(restarted.tasks) == 1
    assert restarted.load_world_task("w_nobody") is None and restarted.load_world_task("w_x\n") is None
    restarted.load_world(W2)
    restarted.worlds[W2].owner = OWNER  # a world record that now names OWNER, with a task still stored for OTHER
    restarted.events[W2] = [ev("world.started")]
    facts = [f for f in _sources(restarted).runs(OWNER) if f["world_id"] == W2]
    assert [f["goal"] for f in facts] == [None], "the other owner's brief is never this person's title"


def test_PEOPLE_SEAMS_1_runs_come_from_the_durable_backend_after_a_restart():
    rig = make_rig("memory")
    first, writer = rig.process()
    seed_world(first, W1, OWNER, deadline="2026-10-20")
    seed_world(first, W2, OTHER)
    writer.append(W1, started(1, W1))
    writer.append(W2, started(2, W2))
    restarted = process(rig)  # a new process over the same backend and events: its cache is empty
    assert restarted.tasks == {} and restarted.worlds == {}
    facts = _sources(restarted).runs(OWNER)
    assert [(f["world_id"], f["world_owner"], f["goal"]) for f in facts] == [(W1, OWNER, "Compare prices")]
    assert [f["world_id"] for f in _sources(restarted).runs(OTHER)] == [W2]


# -- mail -----------------------------------------------------------------------------------------------------------


def test_PEOPLE_SEAMS_1_mail_is_only_the_persons_unflagged_needs_reply_messages():
    docs = [
        mail_doc(OWNER, "m1"),
        mail_doc(OWNER, "m2", category="fyi"),
        mail_doc(OWNER, "m3", category="fyi", label="needs_reply"),  # the person's own label wins
        mail_doc(OWNER, "m4", flagged=True),
        mail_doc(OWNER, "m5", answered=True),
        mail_doc(OWNER, "m6", received_at="yesterday"),
        mail_doc(OWNER, "m7 bad id"),
        mail_doc(OWNER, "m8", dismissed="no"),
        mail_doc(OTHER, "m9"),
    ]
    rig, client = rig_with_mail(docs)
    facts = _sources(process(rig)).mail(OWNER)
    assert [(f["message_id"], f["answered"], f["dismissed"]) for f in facts] == [
        ("m1", False, False), ("m3", False, False), ("m5", True, False),
    ]  # fmt: skip
    assert {f["account_owner"] for f in facts} == {OWNER}
    assert [(q[1], q[2], q[3]) for q in client.queries] == [("owner", OWNER, seams_store.MAX_FACTS + 1)]
    assert [f["message_id"] for f in _sources(process(rig)).mail(OTHER)] == ["m9"]
    assert _sources(process(rig)).mail(STRANGER) == []


def test_PEOPLE_SEAMS_1_an_in_memory_store_has_no_mail_and_a_failing_one_is_a_fixed_503():
    assert _sources(process(make_rig("memory"))).mail(OWNER) == [], "no triage backend, so no mail rows"
    rig, client = rig_with_mail([mail_doc(OWNER, "m1")])
    client.fail = True
    with pytest.raises(HTTPException) as caught:
        _sources(process(rig)).mail(OWNER)
    assert (caught.value.status_code, caught.value.detail) == (503, "store_unavailable")
    assert "tok_" not in repr(caught.value.detail) and caught.value.__cause__ is None


# -- who owns a source ----------------------------------------------------------------------------------------------


def test_PEOPLE_SEAMS_1_a_mail_message_is_owned_by_the_one_account_that_holds_it():
    docs = [mail_doc(OWNER, "m1"), mail_doc(OWNER, "twin"), mail_doc(OTHER, "twin")]
    rig, client = rig_with_mail(docs)
    owners = seams_store.StoreSourceOwners(process(rig))
    assert owners.owner_of("mail", "m1") == OWNER
    assert owners.owner_of("mail", "twin") is None, "two accounts hold it: ambiguous, so nobody"
    assert owners.owner_of("mail", "unknown") is None
    assert all(q[3] == 2 for q in client.queries), "the owner lookup reads at most two documents"


@pytest.mark.parametrize("ref", ["", "a b", "a/b", "m1\n", "x" * 65, "ｍ１", None, 5, ["m1"]])
def test_PEOPLE_SEAMS_1_a_malformed_mail_ref_is_nobodys_and_reaches_no_backend(ref):
    rig, client = rig_with_mail([mail_doc(OWNER, "m1")])
    assert seams_store.StoreSourceOwners(process(rig)).owner_of("mail", ref) is None and client.queries == []


def test_PEOPLE_SEAMS_1_a_request_is_owned_by_its_world_or_task_owner_and_other_kinds_by_nobody():
    store = process(make_rig("memory"))
    tid = seed_world(store, W1, OWNER)
    owners = seams_store.StoreSourceOwners(store)
    assert owners.owner_of("request", W1) == OWNER
    assert owners.owner_of("request", tid) == OWNER
    for kind, ref in [
        ("request", "w_unknown"), ("request", "t_nope"), ("request", W1 + "\n"), ("request", "../w_x"),
        ("meeting", W1), ("manual", W1), ("mail", W1), ("", W1), (None, W1), ("request", None), ("request", 7),
    ]:  # fmt: skip
        assert owners.owner_of(kind, ref) is None, (kind, ref)  # type: ignore[arg-type]


def test_PEOPLE_SEAMS_1_owner_lookups_are_remembered_for_the_request_misses_included():
    rig, client = rig_with_mail([mail_doc(OWNER, "m1")])
    store = process(rig)
    owners = seams_store.StoreSourceOwners(store)
    loads = []
    real = store.load_world
    store.load_world = lambda world_id, settle=False: loads.append(world_id) or real(world_id, settle)
    for _ in range(3):
        assert owners.owner_of("mail", "m1") == OWNER and owners.owner_of("mail", "nope") is None
        assert owners.owner_of("request", "w_nobody") is None
    assert len(client.queries) == 2 and loads == ["w_nobody"], "one read per distinct (kind, ref)"


def test_PEOPLE_SEAMS_1_a_mail_read_that_hits_the_cap_says_so():
    docs = [mail_doc(OWNER, f"m{n}") for n in range(120)]
    sources = _sources(process(rig_with_mail(docs)[0]))
    assert len(sources.mail(OWNER)) == 120 and sources.truncated is False
    docs = [mail_doc(OWNER, f"m{n}") for n in range(seams_store.MAX_FACTS + 1)]
    sources = _sources(process(rig_with_mail(docs)[0]))
    assert len(sources.mail(OWNER)) == seams_store.MAX_FACTS and sources.truncated is True
