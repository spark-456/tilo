"""FR-HIL-07 (PRD 10.4, 10.6): "Kill switches from app and WhatsApp: STOP AUTOPILOT sets all
policies to L1 in <= 5 s; confirmed on every channel." PI-13 and PI-18
(docs/security/p4-policy-invariants.md): Stop all autopilot sets every policy to L1, one
`policy.changed` per policy, only the owner may do it, and one writer per world stamps every
event -- tilo-api itself never does. Routes and shapes pinned in
services/api/tests/API_ST3a.md (round 8, redone per GitHub issue #46's binding S0 decision after
round 7/ST-3a-3 kept relying on writer-*instance* identity -- "is this the same writer object as
the one already presumed stuck" -- to decide whether a retry was safe. #46's resolved design uses
the idempotency key every event already carries instead: `EventWriter.append` receives the full,
pre-built event, ULID `id` included, built once when a part is enqueued and resent unchanged on
every retry; dedupe is on that `id`, never on raw content and never on which writer object
receives the call (EV-10: a reused id with identical content is a no-op success, with different
content it is rejected). Round 1-6's own fixes (run_id/seq stamping, the 403/404 membership
oracle, half-applied Stop-alls, the pause channel enum, per-scope vis, no silent history repair,
pending-on-failure for stop/pause/revoke, one consumer per world, world.paused jumping the queue)
are unchanged here and still pinned below; this round's own tests are new."""

from __future__ import annotations

import gc
import json
import pathlib
import threading
import time

import pytest
from _api_lib import (
    OWNER,
    PRINCIPAL_HEADER,
    WORLD,
    BlockingEventWriter,
    ConcurrencyTracker,
    EventRejected,
    FakeEventWriter,
    FlakyEventWriter,
    HangsOnceThenWorksEventWriter,
    LateSuccessEventWriter,
    PartiallySlowEventWriter,
    ReversedDelayEventWriter,
    SlowEventWriter,
    SlowFlakyEventWriter,
    SlowHistoryPolicy,
    TrackingBlockingEventWriter,
    as_part_write_deadline,
    as_principal,
    as_principal_by_header,
    as_store_and_writer_by_header,
    as_writer,
    assert_part_carries_no_stamped_fields,
    base_policy,
    make_district,
    make_pending_part,
    make_principal,
    make_store,
    make_world,
    ulid,
    validate_event,
)
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

OTHER_OWNER = "u_other_owner"
OTHER_WORLD = "w_other_owners_world"
MAX_LEN_WORLD = "w_" + "a" * 48  # common.schema.json#/$defs/world_id: "^w_[0-9A-Za-z_]{1,48}$"


def _world_with_policies(store, n: int, *, owner: str = OWNER, level: str = "L2", world_id: str = WORLD) -> list[str]:
    store.worlds[world_id] = make_world(owner=owner)
    ids = []
    for i in range(n):
        pid = f"pol_test_{i}"
        store.policies[pid] = base_policy(id_=pid, owner=owner, level=level, action_type="send_email")
        store.policy_worlds[pid] = world_id
        ids.append(pid)
    return ids


def test_FR_HIL_07_stop_all_sets_every_policy_to_L1(client, store):
    ids = _world_with_policies(store, 5, level="L2")
    as_principal(make_principal(user_id=OWNER, role="owner", world_id=WORLD))

    resp = client.post(f"/worlds/{WORLD}/autopilot/stop")

    assert resp.status_code == 200
    for pid in ids:
        assert store.policies[pid]["level"] == "L1"
        assert store.policies[pid]["history"][-1]["level"] == "L1"
        assert store.policies[pid]["history"][-1]["by"] == OWNER
        assert store.policies[pid]["history"][-1]["change"] == "stop_all"


def test_FR_HIL_07_PI_13_stop_all_emits_one_policy_changed_per_policy(client, store):
    ids = _world_with_policies(store, 3, level="L3")
    as_principal(make_principal(user_id=OWNER, role="owner", world_id=WORLD))

    resp = client.post(f"/worlds/{WORLD}/autopilot/stop")
    assert resp.status_code == 200

    changed = [e for e in store.events[WORLD] if e["type"] == "policy.changed"]
    assert len(changed) == len(ids)
    seen_policy_ids = {e["data"]["policy_id"] for e in changed}
    assert seen_policy_ids == set(ids)
    for e in changed:
        assert e["data"]["change"] == "stop_all"
        assert e["data"]["level"] == "L1"
        assert e["authz"] == {"by": "person", "ref": OWNER, "at": e["authz"]["at"]}
        validate_event(e)  # policy.changed's data validates against its schema (EV-02)


def test_PI_18_stop_all_hands_the_writer_unstamped_parts_only(client, store, writer):
    """Round-1 finding: tilo-api computed run_id and seq itself. It must instead hand the
    injected EventWriter an event part with none of those fields, and let the writer (standing in
    for the harness, PRD 15.3) stamp them."""
    ids = _world_with_policies(store, 3, level="L2")
    as_principal(make_principal(user_id=OWNER, role="owner", world_id=WORLD))

    resp = client.post(f"/worlds/{WORLD}/autopilot/stop")
    assert resp.status_code == 200

    assert len(writer.calls) == len(ids)
    for call in writer.calls:
        assert call.world_id == WORLD
        assert call.part["type"] == "policy.changed"
        assert_part_carries_no_stamped_fields(call.part)


def test_PI_18_stamped_events_validate_for_a_max_length_world_id(client, store, writer):
    """The stamped event -- not the part the API built -- must validate against
    event.schema.json, including at world_id's maximum length (50 chars: "w_" + 48)."""
    store.worlds[MAX_LEN_WORLD] = make_world(owner=OWNER)
    store.policies["pol_maxlen"] = base_policy(id_="pol_maxlen", owner=OWNER, level="L2")
    store.policy_worlds["pol_maxlen"] = MAX_LEN_WORLD
    as_principal(make_principal(user_id=OWNER, role="owner", world_id=MAX_LEN_WORLD))

    resp = client.post(f"/worlds/{MAX_LEN_WORLD}/autopilot/stop")

    assert resp.status_code == 200
    events = store.events[MAX_LEN_WORLD]
    assert events, "expected at least one stamped policy.changed event"
    for event in events:
        assert event["world_id"] == MAX_LEN_WORLD
        validate_event(event)


def test_FR_HIL_07_stop_all_is_idempotent_no_duplicate_l1_entries(client, store):
    ids = _world_with_policies(store, 4, level="L2")
    as_principal(make_principal(user_id=OWNER, role="owner", world_id=WORLD))

    first = client.post(f"/worlds/{WORLD}/autopilot/stop")
    assert first.status_code == 200
    assert first.json()["stopped"] == len(ids)

    history_lengths_after_first = {pid: len(store.policies[pid]["history"]) for pid in ids}
    events_after_first = len([e for e in store.events[WORLD] if e["type"] == "policy.changed"])

    second = client.post(f"/worlds/{WORLD}/autopilot/stop")
    assert second.status_code == 200
    assert second.json()["stopped"] == 0
    assert second.json()["already_l1"] == len(ids)

    for pid in ids:
        assert len(store.policies[pid]["history"]) == history_lengths_after_first[pid]
    events_after_second = len([e for e in store.events[WORLD] if e["type"] == "policy.changed"])
    assert events_after_second == events_after_first


def test_FR_HIL_07_stop_all_never_raises_an_l0_policy(client, store):
    """A kill switch only ever lowers autonomy. An L0 policy (observe: nothing leaves Tilo) is
    already below L1, so Stop all leaves it at L0 with no history entry and no event."""
    ids = _world_with_policies(store, 2, level="L0")
    before = {pid: len(store.policies[pid]["history"]) for pid in ids}
    as_principal(make_principal(user_id=OWNER, role="owner", world_id=WORLD))

    resp = client.post(f"/worlds/{WORLD}/autopilot/stop")

    assert resp.status_code == 200
    assert resp.json()["stopped"] == 0
    for pid in ids:
        assert store.policies[pid]["level"] == "L0"
        assert len(store.policies[pid]["history"]) == before[pid]
    assert not [e for e in store.events.get(WORLD, []) if e["type"] == "policy.changed"]


def test_FR_HIL_07_stop_all_confirms_on_every_enabled_channel(client, store):
    store.worlds[WORLD] = make_world(owner=OWNER, owner_channels=("web", "whatsapp", "email"))
    as_principal(make_principal(user_id=OWNER, role="owner", world_id=WORLD))

    resp = client.post(f"/worlds/{WORLD}/autopilot/stop")

    assert resp.status_code == 200
    body = resp.json()
    channels = {c["channel"] for c in body["confirmations"]}
    assert channels == {"web", "whatsapp", "email"}


def test_FR_HIL_07_stop_all_completes_within_5s_for_200_policies(client, store):
    _world_with_policies(store, 200, level="L3")
    as_principal(make_principal(user_id=OWNER, role="owner", world_id=WORLD))

    started = time.monotonic()
    resp = client.post(f"/worlds/{WORLD}/autopilot/stop")
    elapsed = time.monotonic() - started

    assert resp.status_code == 200
    assert resp.json()["stopped"] == 200
    assert elapsed <= 5.0, f"stop-all took {elapsed:.2f}s for 200 policies, must be <= 5s"


def test_FR_HIL_07_stop_all_forbidden_for_member_non_owner_roles(client, store):
    """A team lead, approver or viewer who *is* a member of this world (principal.world_id ==
    world_id) still cannot stop autopilot -- only the owner can (PRD 10.1)."""
    _world_with_policies(store, 2, level="L2")

    for role, user in (("team_lead", "u_finance_lead"), ("approver", "u_approver"), ("viewer", "u_viewer")):
        as_principal(make_principal(user_id=user, role=role, world_id=WORLD))
        resp = client.post(f"/worlds/{WORLD}/autopilot/stop")
        assert resp.status_code == 403, f"role={role} must not be able to stop autopilot"

    for pid, policy in store.policies.items():
        assert policy["level"] == "L2"
    assert store.events.get(WORLD, []) == []


def test_SEC_07_stop_all_non_member_gets_the_same_404_as_an_unknown_world(client, store):
    """Round-1 security finding: an owner of a *different* world previously got 403 (which
    reveals the world exists). A principal not bound to this world now gets exactly the same
    404 an unknown world_id gets -- no oracle to tell "wrong world" from "no such world"."""
    _world_with_policies(store, 2, level="L2")

    # Case 1: membership matches a world that genuinely does not exist -- 404 via the "no such
    # world" branch.
    as_principal(make_principal(user_id=OTHER_OWNER, role="owner", world_id="w_does_not_exist"))
    resp_unknown_world = client.post("/worlds/w_does_not_exist/autopilot/stop")

    # Case 2: the world exists, but this principal belongs to a different one -- 404 via the
    # "membership mismatch" branch, before the handler ever reads store.worlds[WORLD].
    as_principal(make_principal(user_id=OTHER_OWNER, role="owner", world_id=OTHER_WORLD))
    resp_wrong_membership = client.post(f"/worlds/{WORLD}/autopilot/stop")

    assert resp_unknown_world.status_code == 404
    assert resp_wrong_membership.status_code == 404
    assert resp_unknown_world.json() == resp_wrong_membership.json()

    for policy in store.policies.values():
        assert policy["level"] == "L2"
    assert store.events.get(WORLD, []) == []


def test_SEC_07_stop_all_no_membership_gets_404(client, store):
    _world_with_policies(store, 1, level="L2")
    as_principal(make_principal(user_id="u_nobody", role="viewer", world_id=None))

    resp = client.post(f"/worlds/{WORLD}/autopilot/stop")

    assert resp.status_code == 404
    assert store.events.get(WORLD, []) == []


def test_FR_HIL_07_PI_13_decide_gates_after_stop_all(client, store):
    """Integration with the P4-01 policy engine (FR-HIL-03 + FR-HIL-07): once Stop all has run,
    tilo_policy.decide for the next send under the previously-L2 policy returns outcome "gate".
    Imports tilo_policy directly (packages/policy/tests/API.md); that package is built by a
    parallel ticket and is not a workspace member yet, so this test fails on the import until it
    lands -- expected."""
    import tilo_policy

    ids = _world_with_policies(store, 1, level="L2")
    pid = ids[0]
    as_principal(make_principal(user_id=OWNER, role="owner", world_id=WORLD))

    resp = client.post(f"/worlds/{WORLD}/autopilot/stop")
    assert resp.status_code == 200

    repo_root = pathlib.Path(__file__).resolve().parents[3]
    table = tilo_policy.load_risk_table(
        repo_root / "contracts" / "fixtures" / "policy.risk_tier_table" / "valid" / "prd_10_4_tiers.json"
    )
    proposal = tilo_policy.Proposal(
        world_id=WORLD,
        action_type="send_email",
        connector="gmail",
        district="D1",
        destination="thread-supplier-1",
        facts=tilo_policy.SideEffectFacts(
            recipients=("riya@example.com",),
            known_recipients=("riya@example.com",),
        ),
        item={"artifact_id": "art_followup_reply", "version": 1},
        credits=1,
        instruction=None,
    )
    decision = tilo_policy.decide(
        proposal,
        table=table,
        policies=[store.policies[pid]],
        world_owner=OWNER,
        applied=[],
        now="2026-09-29T09:45:00.000Z",
    )
    assert decision.outcome == "gate"
    assert decision.level == "L1"


def test_FR_HIL_07_pause_all_emits_world_paused_and_sets_l1(client, store):
    ids = _world_with_policies(store, 3, level="L3")
    # ST-3a-2: the channel comes from the principal's session, never the request body.
    as_principal(make_principal(user_id=OWNER, role="owner", world_id=WORLD, channel="whatsapp"))

    resp = client.post(f"/worlds/{WORLD}/pause", json={"channel": "whatsapp"})

    assert resp.status_code == 200
    assert resp.json()["paused"] is True
    for pid in ids:
        assert store.policies[pid]["level"] == "L1"

    paused_events = [e for e in store.events[WORLD] if e["type"] == "world.paused"]
    assert len(paused_events) == 1
    event = paused_events[0]
    assert event["data"] == {"reason": "pause_all", "channel": "whatsapp"}
    assert event["authz"] is None  # world.paused is side_effect: false (events/registry.yaml)
    assert event["vis"] == "all"
    validate_event(event)
    assert store.worlds[WORLD].paused is True, "round-4: the durable paused flag must be set too"


def test_FR_HIL_07_pause_channel_outside_the_schema_enum_is_422(client, store, writer):
    """Round-1 finding: PauseRequest.channel accepted any string. It is now typed to
    common.schema.json#/$defs/channel's own enum, so an out-of-enum value never reaches the
    handler: 422, nothing changes, nothing is emitted."""
    ids = _world_with_policies(store, 2, level="L2")
    as_principal(make_principal(user_id=OWNER, role="owner", world_id=WORLD))

    resp = client.post(f"/worlds/{WORLD}/pause", json={"channel": "sms"})

    assert resp.status_code == 422
    for pid in ids:
        assert store.policies[pid]["level"] == "L2"
    assert store.events.get(WORLD, []) == []
    assert writer.calls == []


def test_SEC_07_pause_non_member_gets_the_same_404_as_an_unknown_world(client, store):
    _world_with_policies(store, 1, level="L2")
    as_principal(make_principal(user_id=OTHER_OWNER, role="owner", world_id=OTHER_WORLD))

    resp = client.post(f"/worlds/{WORLD}/pause", json={"channel": "web"})

    assert resp.status_code == 404
    assert store.events.get(WORLD, []) == []


def test_FR_HIL_07_revoke_appends_l1_and_emits_policy_changed(client, store):
    store.worlds[WORLD] = make_world(owner=OWNER)
    store.policies["pol_autopilot_l2"] = base_policy(id_="pol_autopilot_l2", owner=OWNER, level="L2")
    store.policy_worlds["pol_autopilot_l2"] = WORLD
    as_principal(make_principal(user_id=OWNER, role="owner", world_id=WORLD))

    resp = client.post("/policies/pol_autopilot_l2/revoke")

    assert resp.status_code == 200
    policy = store.policies["pol_autopilot_l2"]
    assert policy["level"] == "L1"
    assert policy["history"][-1] == {"by": OWNER, "at": policy["history"][-1]["at"], "change": "revoked", "level": "L1"}

    changed = [e for e in store.events[WORLD] if e["type"] == "policy.changed" and e["data"]["change"] == "revoked"]
    assert len(changed) == 1
    assert changed[0]["data"]["policy_id"] == "pol_autopilot_l2"
    assert changed[0]["data"]["level"] == "L1"
    validate_event(changed[0])


def test_SEC_07_revoke_non_owner_gets_the_same_404_as_unknown_policy(client, store):
    """Round-1 security finding: revoking a policy you do not own previously answered 403 for a
    known policy id, letting a caller distinguish "not yours" from "no such policy". Both cases
    now answer 404 identically -- no 403/404 oracle."""
    store.worlds[WORLD] = make_world(owner=OWNER)
    store.policies["pol_autopilot_l2"] = base_policy(id_="pol_autopilot_l2", owner=OWNER, level="L2")
    store.policy_worlds["pol_autopilot_l2"] = WORLD

    as_principal(make_principal(user_id=OWNER, role="owner", world_id=WORLD))
    reference = client.post("/policies/pol_does_not_exist/revoke")
    assert reference.status_code == 404

    for role, user in (
        ("team_lead", "u_finance_lead"),
        ("approver", "u_approver"),
        ("viewer", "u_viewer"),
        ("owner", OTHER_OWNER),  # a different world's owner, impersonating no one -- still not
        # *this* policy's owner
    ):
        as_principal(make_principal(user_id=user, role=role, world_id=WORLD))
        resp = client.post("/policies/pol_autopilot_l2/revoke")
        assert resp.status_code == 404, f"role={role} user={user} must get 404, not a distinguishable 403"
        assert resp.json() == reference.json()

    assert store.policies["pol_autopilot_l2"]["level"] == "L2"
    assert store.events.get(WORLD, []) == []


def test_FR_HIL_07_stop_all_never_half_applies_with_an_unmapped_policy(client, store, writer):
    """Round-1 finding: a policy absent from store.policy_worlds raised KeyError partway through
    the loop, a 500 leaving earlier policies already flipped to L1 and later ones untouched. It
    is instead lowered to L1 like every other owned policy, and its policy.changed is routed to
    the world Stop-all was pressed in (policies live at the org level, PRD 15.3 -- they carry no
    world_id of their own)."""
    store.worlds[WORLD] = make_world(owner=OWNER)
    mapped_ids = []
    for i in range(2):
        pid = f"pol_mapped_{i}"
        store.policies[pid] = base_policy(id_=pid, owner=OWNER, level="L2")
        store.policy_worlds[pid] = WORLD
        mapped_ids.append(pid)
    store.policies["pol_unmapped"] = base_policy(id_="pol_unmapped", owner=OWNER, level="L2")
    # Deliberately no store.policy_worlds["pol_unmapped"] entry.

    as_principal(make_principal(user_id=OWNER, role="owner", world_id=WORLD))
    resp = client.post(f"/worlds/{WORLD}/autopilot/stop")

    assert resp.status_code == 200, resp.text
    assert resp.json()["stopped"] == 3
    for pid in [*mapped_ids, "pol_unmapped"]:
        assert store.policies[pid]["level"] == "L1"

    changed_ids = {e["data"]["policy_id"] for e in store.events[WORLD] if e["type"] == "policy.changed"}
    assert changed_ids == {*mapped_ids, "pol_unmapped"}


def test_FR_HIL_07_stop_all_fails_safe_on_malformed_history_and_level(client, store, writer):
    """Round-1 finding (qa + security): a policy record missing or with a malformed `history` or
    `level` must still be lowered to L1 (a kill switch fails safe) and get exactly one event,
    never a 500, and never block its well-formed siblings in the same call."""
    store.worlds[WORLD] = make_world(owner=OWNER)

    p_missing_history = base_policy(id_="pol_missing_history", owner=OWNER, level="L2")
    del p_missing_history["history"]
    store.policies["pol_missing_history"] = p_missing_history
    store.policy_worlds["pol_missing_history"] = WORLD

    p_bad_history_type = base_policy(id_="pol_bad_history_type", owner=OWNER, level="L2")
    p_bad_history_type["history"] = "not-a-list"
    store.policies["pol_bad_history_type"] = p_bad_history_type
    store.policy_worlds["pol_bad_history_type"] = WORLD

    p_bad_level = base_policy(id_="pol_bad_level", owner=OWNER, level="L2")
    del p_bad_level["level"]
    store.policies["pol_bad_level"] = p_bad_level
    store.policy_worlds["pol_bad_level"] = WORLD

    p_normal = base_policy(id_="pol_normal", owner=OWNER, level="L3")
    store.policies["pol_normal"] = p_normal
    store.policy_worlds["pol_normal"] = WORLD

    as_principal(make_principal(user_id=OWNER, role="owner", world_id=WORLD))
    resp = client.post(f"/worlds/{WORLD}/autopilot/stop")

    assert resp.status_code == 200, resp.text
    assert resp.json()["stopped"] == 4
    assert resp.json()["already_l1"] == 0

    for pid in ("pol_missing_history", "pol_bad_history_type", "pol_bad_level", "pol_normal"):
        policy = store.policies[pid]
        assert policy["level"] == "L1"
        assert isinstance(policy["history"], list)
        assert len(policy["history"]) >= 1
        assert policy["history"][-1]["level"] == "L1"
        assert policy["history"][-1]["change"] == "stop_all"
        assert policy["history"][-1]["by"] == OWNER

    changed = [e for e in store.events[WORLD] if e["type"] == "policy.changed"]
    assert len(changed) == 4
    for e in changed:
        validate_event(e)


_LEVELS = st.sampled_from(["L0", "L1", "L2", "L3", None, "not_a_real_level"])
# Round-3 code-review finding (biggest): "normal" was replaced with two distinct shapes because
# the old single "normal" shape built history from base_policy(level="L2") and then overwrote
# policy["level"] separately -- so a case with level="L1" silently got a *mismatched* history
# (last entry "L2") and the old test still asserted it was skipped as already_l1. That was wrong:
# a policy read as L1 is only left alone when its own history agrees. "matches_level" and
# "mismatched_level" below make that distinction explicit and deliberate instead of accidental.
_HISTORY_SHAPES = st.sampled_from(["matches_level", "mismatched_level", "missing", "not_a_list", "empty_list"])


def _history_for(level: str | None, hist_shape: str) -> list[dict] | str | None:
    """Builds the history shape a case asks for. `level` may itself be malformed (None or
    "not_a_real_level"); "matches_level"/"mismatched_level" fall back to a plain "L2" entry for
    the malformed-level cases since there is nothing valid to (mis)match against -- the level
    fail-safe rule (not one of L0..L3 -> always lowered) dominates regardless of history there."""
    valid_level = level if level in ("L0", "L1", "L2", "L3") else "L2"
    if hist_shape == "missing":
        return None  # caller deletes the key entirely
    if hist_shape == "not_a_list":
        return "oops"
    if hist_shape == "empty_list":
        return []
    if hist_shape == "matches_level":
        return [{"by": OWNER, "at": "2026-09-29T09:00:00.000Z", "change": "prior", "level": valid_level}]
    # mismatched_level: pick something guaranteed different from valid_level.
    other = "L3" if valid_level != "L3" else "L2"
    return [{"by": OWNER, "at": "2026-09-29T09:00:00.000Z", "change": "prior", "level": other}]


@st.composite
def _kill_switch_case(draw):
    n = draw(st.integers(min_value=1, max_value=5))
    levels = draw(st.lists(_LEVELS, min_size=n, max_size=n))
    history_shapes = draw(st.lists(_HISTORY_SHAPES, min_size=n, max_size=n))
    mapped = draw(st.lists(st.booleans(), min_size=n, max_size=n))
    return list(zip(levels, history_shapes, mapped))


@settings(max_examples=40, deadline=None, suppress_health_check=[HealthCheck.function_scoped_fixture])
@given(case=_kill_switch_case())
def test_FR_HIL_07_PI_13_stop_all_never_half_applies_property(client, store, writer, case):
    """Property: whatever mix of well-formed, malformed and unmapped policies an owner has,
    Stop-all never raises, every one of them not already at L0 ends at L1 with exactly one new
    policy.changed each, and the response's stopped/already_l1 counts match -- no partial
    application, whatever order the store's dict iterates in.

    Round-3 code-review finding (biggest, "no silent history repair"): a policy read as L1 is
    left alone (already_l1, no new history entry, no event) only when its own history agrees --
    last entry also "L1". A policy at L1 whose history ends at a different level, or is missing,
    not a list, or empty, is an *inconsistent* record: Stop-all lowers it through the exact same
    normal path as any other policy (one new history entry, one policy.changed, counted in
    "stopped"), never silently left alone and never silently "repaired" without an audit trail."""
    store.worlds.clear()
    store.policies.clear()
    store.policy_worlds.clear()
    store.events.clear()
    store.worlds[WORLD] = make_world(owner=OWNER)

    pids: list[str] = []
    expected_stopped = 0
    expected_already_l1 = 0
    already_l1_pids: set[str] = set()
    for i, (level, hist_shape, mapped) in enumerate(case):
        pid = f"pol_case_{i}"
        pids.append(pid)
        policy = base_policy(id_=pid, owner=OWNER, level="L2")
        policy["level"] = level
        history = _history_for(level, hist_shape)
        if history is None:
            del policy["history"]
        else:
            policy["history"] = history
        store.policies[pid] = policy
        if mapped:
            store.policy_worlds[pid] = WORLD

        is_consistent_l1 = level == "L1" and hist_shape == "matches_level"
        if level == "L0":
            pass
        elif is_consistent_l1:
            expected_already_l1 += 1
            already_l1_pids.add(pid)
        else:
            expected_stopped += 1

    as_principal(make_principal(user_id=OWNER, role="owner", world_id=WORLD))
    resp = client.post(f"/worlds/{WORLD}/autopilot/stop")

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["stopped"] == expected_stopped
    assert body["already_l1"] == expected_already_l1

    expected_changed_ids = set()
    for pid, (level, hist_shape, _) in zip(pids, case):
        if level == "L0":
            assert store.policies[pid]["level"] == "L0"
        else:
            assert store.policies[pid]["level"] == "L1"
            assert isinstance(store.policies[pid]["history"], list)
            assert store.policies[pid]["history"][-1]["level"] == "L1"
            if pid in already_l1_pids:
                # Left alone: exactly the one pre-existing entry, never rewritten or repaired.
                assert len(store.policies[pid]["history"]) == 1
                assert store.policies[pid]["history"][-1]["change"] == "prior"
            else:
                expected_changed_ids.add(pid)
                assert store.policies[pid]["history"][-1]["change"] == "stop_all"

    changed_ids = {e["data"]["policy_id"] for e in store.events.get(WORLD, []) if e["type"] == "policy.changed"}
    assert changed_ids == expected_changed_ids


def test_FR_HIL_07_no_silent_history_repair_for_inconsistent_l1(client, store, writer):
    """code-review finding (biggest, round 3): a policy already at level L1 is only left alone
    when its own history agrees (last entry also L1) -- true idempotency. A policy that merely
    reads level == "L1" while its history disagrees (ends at another level, or is empty) is an
    inconsistent record, not a repeat Stop-all: it must go through the exact same normal path as
    any other policy Stop-all lowers -- one new history entry (by/at/change/level), one
    policy.changed, and counted in "stopped" -- never silently left as-is and never silently
    "repaired" without an audit trail."""
    store.worlds[WORLD] = make_world(owner=OWNER)

    store.policies["pol_consistent_l1"] = base_policy(
        id_="pol_consistent_l1",
        owner=OWNER,
        level="L1",
        history=[{"by": OWNER, "at": "2026-09-29T09:00:00.000Z", "change": "revoked", "level": "L1"}],
    )
    store.policy_worlds["pol_consistent_l1"] = WORLD

    store.policies["pol_mismatched_l1"] = base_policy(
        id_="pol_mismatched_l1",
        owner=OWNER,
        level="L1",
        history=[{"by": OWNER, "at": "2026-09-29T09:00:00.000Z", "change": "Created", "level": "L2"}],
    )
    store.policy_worlds["pol_mismatched_l1"] = WORLD

    store.policies["pol_empty_history_l1"] = base_policy(
        id_="pol_empty_history_l1", owner=OWNER, level="L1", history=[]
    )
    store.policy_worlds["pol_empty_history_l1"] = WORLD

    as_principal(make_principal(user_id=OWNER, role="owner", world_id=WORLD))
    resp = client.post(f"/worlds/{WORLD}/autopilot/stop")

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["already_l1"] == 1  # only pol_consistent_l1
    assert body["stopped"] == 2  # pol_mismatched_l1 and pol_empty_history_l1

    consistent = store.policies["pol_consistent_l1"]
    assert len(consistent["history"]) == 1, "a truly consistent L1 policy is left alone -- no new entry"
    assert consistent["history"][0]["change"] == "revoked"  # unchanged, not rewritten

    mismatched = store.policies["pol_mismatched_l1"]
    assert len(mismatched["history"]) == 2
    assert mismatched["history"][-1] == {
        "by": OWNER,
        "at": mismatched["history"][-1]["at"],
        "change": "stop_all",
        "level": "L1",
    }

    empty_hist = store.policies["pol_empty_history_l1"]
    assert len(empty_hist["history"]) == 1
    assert empty_hist["history"][-1]["change"] == "stop_all"
    assert empty_hist["history"][-1]["level"] == "L1"

    changed_ids = {e["data"]["policy_id"] for e in store.events[WORLD] if e["type"] == "policy.changed"}
    assert changed_ids == {"pol_mismatched_l1", "pol_empty_history_l1"}
    assert "pol_consistent_l1" not in changed_ids
    for e in store.events[WORLD]:
        validate_event(e)


def test_FR_HIL_07_policy_changed_vis_matches_the_policys_scope_districts(client, store, writer):
    """SEC-07 / EV-13 (round-1 finding d): a policy scoped to specific districts must not
    broadcast its change to everyone -- vis follows scope.districts; an unrestricted policy's
    event stays vis: "all"."""
    hidden = "D9"
    visible = "D1"
    store.worlds[WORLD] = make_world(
        owner=OWNER,
        districts={
            visible: make_district("Mail", "Triaging the inbox"),
            hidden: make_district("Payroll", "Running payroll"),
        },
    )
    store.policies["pol_scoped"] = base_policy(id_="pol_scoped", owner=OWNER, level="L2", districts=(hidden,))
    store.policy_worlds["pol_scoped"] = WORLD
    store.policies["pol_open"] = base_policy(id_="pol_open", owner=OWNER, level="L2", districts=())
    store.policy_worlds["pol_open"] = WORLD

    as_principal(make_principal(user_id=OWNER, role="owner", world_id=WORLD))
    resp = client.post(f"/worlds/{WORLD}/autopilot/stop")
    assert resp.status_code == 200

    by_policy = {e["data"]["policy_id"]: e for e in store.events[WORLD] if e["type"] == "policy.changed"}
    assert by_policy["pol_scoped"]["vis"] == [hidden]
    assert by_policy["pol_open"]["vis"] == "all"
    for e in by_policy.values():
        validate_event(e)

    as_principal(make_principal(user_id="u_viewer", role="viewer", world_id=WORLD, districts=(visible,)))
    events_resp = client.get(f"/worlds/{WORLD}/events")
    assert events_resp.status_code == 200
    seen_policy_ids = {e["data"]["policy_id"] for e in events_resp.json()["events"] if e["type"] == "policy.changed"}
    assert "pol_open" in seen_policy_ids
    assert "pol_scoped" not in seen_policy_ids


def test_FR_HIL_07_EV_13_policy_changed_vis_is_the_intersection_with_the_worlds_layout(client, store, writer):
    """EV-13 (contracts/event.rules.md): "every district vis lists exists in the world's
    layout." A policy's own scope.districts may name a district that is not part of the world
    Stop-all is run against at all (policies live at org level, PRD 15.3, with no world_id of
    their own): vis must be the *intersection* of scope.districts with this world's own
    districts, never a foreign district id. When that intersection is empty -- every scoped
    district is foreign to this world, or scope.districts was empty to begin with -- vis falls
    back to "all" (round-3 security finding b; the fallback itself is logged as an open question
    in API_ST3a.md, since the contract has no owner-only vis to fall back to instead)."""
    real_district = "D1"
    phantom_district = "D77"  # not in this world's layout at all
    store.worlds[WORLD] = make_world(
        owner=OWNER, districts={real_district: make_district("Mail", "Triaging the inbox")}
    )

    store.policies["pol_mixed"] = base_policy(
        id_="pol_mixed", owner=OWNER, level="L2", districts=(real_district, phantom_district)
    )
    store.policy_worlds["pol_mixed"] = WORLD

    store.policies["pol_all_foreign"] = base_policy(
        id_="pol_all_foreign", owner=OWNER, level="L2", districts=(phantom_district,)
    )
    store.policy_worlds["pol_all_foreign"] = WORLD

    as_principal(make_principal(user_id=OWNER, role="owner", world_id=WORLD))
    resp = client.post(f"/worlds/{WORLD}/autopilot/stop")
    assert resp.status_code == 200, resp.text

    by_policy = {e["data"]["policy_id"]: e for e in store.events[WORLD] if e["type"] == "policy.changed"}
    assert by_policy["pol_mixed"]["vis"] == [real_district], "the foreign district must be dropped, not kept"
    assert by_policy["pol_all_foreign"]["vis"] == "all", "an empty intersection falls back to all"
    for e in by_policy.values():
        assert phantom_district not in json.dumps(e)
        validate_event(e)


# ---------------------------------------------------------------------------
# Round-3 findings 2 and 3: the event writer going down must never stop a kill switch from
# actually lowering autonomy (FR-HIL-07's <= 5s budget is about autonomy actually lowering, not
# about the audit trail landing at the same instant), and pending parts must be written exactly
# once each when the writer works again. Concurrent kill switches must not double-write either.


def test_FR_HIL_07_stop_all_lowers_policies_even_when_the_writer_is_down(client, store):
    """qa/security finding (biggest): autopilot must actually stop even when the harness (the
    event writer) is unreachable. Every targeted policy is still lowered to L1; the policy.changed
    parts that could not be handed to the writer are kept as pending parts in the store rather
    than lost, and the response is never a 500."""
    ids = _world_with_policies(store, 4, level="L2")
    flaky = FlakyEventWriter(store, failing=True)
    as_writer(flaky)
    as_principal(make_principal(user_id=OWNER, role="owner", world_id=WORLD))

    started = time.monotonic()
    resp = client.post(f"/worlds/{WORLD}/autopilot/stop")
    elapsed = time.monotonic() - started

    assert resp.status_code in (200, 202), resp.text
    assert elapsed <= 5.0, f"stop-all took {elapsed:.2f}s with the writer down, must still be <= 5s"
    body = resp.json()
    assert body["stopped"] == len(ids)
    assert body["pending"] == len(ids)
    for pid in ids:
        assert store.policies[pid]["level"] == "L1"
        assert store.policies[pid]["history"][-1]["change"] == "stop_all"
    assert store.events.get(WORLD, []) == [], "nothing actually reached the (down) writer"
    pending = store.pending_events.get(WORLD, [])
    assert len(pending) == len(ids)
    for part in pending:
        assert part["type"] == "policy.changed"
        assert_part_carries_no_stamped_fields(part)


def test_FR_HIL_07_stop_all_partial_writer_failure_keeps_only_the_unwritten_parts_pending(client, store):
    """The writer can fail partway through a single Stop-all, not just be entirely down: some
    policy.changed parts land, others don't. Every targeted policy is still lowered to L1; only
    the parts that actually failed become pending, the rest are written normally."""
    ids = _world_with_policies(store, 5, level="L2")
    flaky = FlakyEventWriter(store, failing=False, fail_first_n=2)
    as_writer(flaky)
    as_principal(make_principal(user_id=OWNER, role="owner", world_id=WORLD))

    resp = client.post(f"/worlds/{WORLD}/autopilot/stop")

    assert resp.status_code in (200, 202), resp.text
    body = resp.json()
    assert body["stopped"] == len(ids)
    assert body["pending"] == 2
    for pid in ids:
        assert store.policies[pid]["level"] == "L1"

    written = {e["data"]["policy_id"] for e in store.events.get(WORLD, [])}
    pending_ids = {p["data"]["policy_id"] for p in store.pending_events.get(WORLD, [])}
    assert len(written) == 3
    assert len(pending_ids) == 2
    assert written | pending_ids == set(ids)
    assert written.isdisjoint(pending_ids)


def test_FR_HIL_07_pending_events_are_flushed_exactly_once_when_the_writer_recovers(client, store):
    """Across the failure and the retry, each lowered policy has exactly one policy.changed in
    the stream -- never zero (lost), never two (duplicated). API_ST3a.md pins the flush trigger as
    "the next mutating call against this world": a second Stop-all, even though it is a no-op for
    the already-L1 policies themselves, still flushes what an earlier failed call left pending."""
    ids = _world_with_policies(store, 3, level="L2")
    flaky = FlakyEventWriter(store, failing=True)
    as_writer(flaky)
    as_principal(make_principal(user_id=OWNER, role="owner", world_id=WORLD))

    first = client.post(f"/worlds/{WORLD}/autopilot/stop")
    assert first.status_code in (200, 202), first.text
    assert first.json()["pending"] == len(ids)
    assert store.events.get(WORLD, []) == []

    flaky.failing = False  # "the harness" is back up

    second = client.post(f"/worlds/{WORLD}/autopilot/stop")
    assert second.status_code == 200, second.text
    assert second.json()["stopped"] == 0
    assert second.json()["already_l1"] == len(ids)
    assert second.json()["pending"] == 0
    assert store.pending_events.get(WORLD, []) == []

    changed = [e for e in store.events[WORLD] if e["type"] == "policy.changed"]
    assert len(changed) == len(ids), "each pending part must be written exactly once, never dropped or duplicated"
    assert {e["data"]["policy_id"] for e in changed} == set(ids)
    for e in changed:
        validate_event(e)


def test_FR_HIL_07_pause_all_still_pauses_and_lowers_when_the_writer_is_down(client, store):
    """Pause's world.paused follows the same rule as Stop-all's policy.changed: the writer being
    down must not stop Pause from actually pausing and lowering autonomy."""
    ids = _world_with_policies(store, 2, level="L3")
    flaky = FlakyEventWriter(store, failing=True)
    as_writer(flaky)
    as_principal(make_principal(user_id=OWNER, role="owner", world_id=WORLD))

    resp = client.post(f"/worlds/{WORLD}/pause", json={"channel": "web"})

    assert resp.status_code in (200, 202), resp.text
    body = resp.json()
    assert body["paused"] is True
    assert body["pending"] == len(ids) + 1  # every policy.changed plus the world.paused part
    for pid in ids:
        assert store.policies[pid]["level"] == "L1"
    assert store.events.get(WORLD, []) == []
    pending_types = {p["type"] for p in store.pending_events.get(WORLD, [])}
    assert pending_types == {"policy.changed", "world.paused"}

    flaky.failing = False
    second = client.post(f"/worlds/{WORLD}/pause", json={"channel": "web"})
    assert second.status_code == 200, second.text
    assert second.json()["pending"] == 0
    paused_events = [e for e in store.events[WORLD] if e["type"] == "world.paused"]
    assert len(paused_events) == 1
    changed = [e for e in store.events[WORLD] if e["type"] == "policy.changed"]
    assert len(changed) == len(ids)


def test_FR_HIL_07_concurrent_stop_alls_produce_exactly_one_change_per_policy(client, store):
    """qa finding (biggest): two concurrent Stop-all requests (the owner double-tapping the
    button, or app and WhatsApp racing) against a slow writer must not each independently see
    every policy at L2 and both lower + emit for it. Exactly one policy.changed and one stop_all
    history entry per policy survive the race."""
    ids = _world_with_policies(store, 6, level="L2")
    slow = SlowEventWriter(store, delay_s=0.05)
    as_writer(slow)
    as_principal(make_principal(user_id=OWNER, role="owner", world_id=WORLD))

    barrier = threading.Barrier(2)
    responses: list = []
    errors: list = []

    def call():
        try:
            barrier.wait(timeout=5)
            responses.append(client.post(f"/worlds/{WORLD}/autopilot/stop"))
        except Exception as exc:  # pragma: no cover - surfaced via the assert below
            errors.append(exc)

    threads = [threading.Thread(target=call) for _ in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=10)

    assert not errors, errors
    assert len(responses) == 2
    for r in responses:
        assert r.status_code in (200, 202), r.text

    for pid in ids:
        stop_all_entries = [h for h in store.policies[pid]["history"] if h.get("change") == "stop_all"]
        assert len(stop_all_entries) == 1, f"{pid}: {len(stop_all_entries)} stop_all history entries"
        assert store.policies[pid]["level"] == "L1"

    changed = [e for e in store.events.get(WORLD, []) if e["type"] == "policy.changed"]
    by_policy: dict[str, list] = {}
    for e in changed:
        by_policy.setdefault(e["data"]["policy_id"], []).append(e)
    for pid in ids:
        assert len(by_policy.get(pid, [])) == 1, f"{pid}: {len(by_policy.get(pid, []))} policy.changed events"


def test_FR_HIL_07_concurrent_pause_alls_produce_exactly_one_world_paused(client, store):
    """Pause's world.paused follows the same one-event rule as Stop-all's policy.changed under
    concurrency (round-3 qa finding)."""
    _world_with_policies(store, 3, level="L2")
    slow = SlowEventWriter(store, delay_s=0.05)
    as_writer(slow)
    as_principal(make_principal(user_id=OWNER, role="owner", world_id=WORLD))

    barrier = threading.Barrier(2)
    responses: list = []
    errors: list = []

    def call():
        try:
            barrier.wait(timeout=5)
            responses.append(client.post(f"/worlds/{WORLD}/pause", json={"channel": "web"}))
        except Exception as exc:  # pragma: no cover - surfaced via the assert below
            errors.append(exc)

    threads = [threading.Thread(target=call) for _ in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=10)

    assert not errors, errors
    assert len(responses) == 2
    for r in responses:
        assert r.status_code in (200, 202), r.text

    paused_events = [e for e in store.events.get(WORLD, []) if e["type"] == "world.paused"]
    assert len(paused_events) == 1, f"expected exactly one world.paused, got {len(paused_events)}"
    assert store.worlds[WORLD].paused is True


# ---------------------------------------------------------------------------
# Round-4 finding 1 (security, biggest): Pause's dedupe must come from WorldRecord.paused, checked
# under the same lock that serializes the route's own mutation -- never from whether this call's
# own Stop-all step happened to lower a policy. The round-3 implementation built a world.paused
# part only when stopped > 0, which silently dropped two kinds of genuine, first-time pauses.


def test_FR_HIL_07_pause_after_stop_all_still_emits_exactly_one_world_paused(client, store):
    """A Stop-all followed by a single Pause-all must still leave exactly one world.paused: every
    owned policy is already L1 by the time Pause-all runs (stopped == 0 for Pause-all's own call),
    but the world itself was never paused before -- a durable record is still owed. This is the
    exact scenario round 3's `stopped > 0` gate silently dropped."""
    ids = _world_with_policies(store, 3, level="L2")
    as_principal(make_principal(user_id=OWNER, role="owner", world_id=WORLD))

    stop_resp = client.post(f"/worlds/{WORLD}/autopilot/stop")
    assert stop_resp.status_code == 200
    for pid in ids:
        assert store.policies[pid]["level"] == "L1"
    assert store.worlds[WORLD].paused is False

    pause_resp = client.post(f"/worlds/{WORLD}/pause", json={"channel": "web"})

    assert pause_resp.status_code == 200, pause_resp.text
    body = pause_resp.json()
    assert body["paused"] is True
    assert body["stopped"] == 0, "every policy was already L1 from Stop-all"
    paused_events = [e for e in store.events[WORLD] if e["type"] == "world.paused"]
    assert len(paused_events) == 1, "Pause-all must still leave a durable record even though stopped == 0"
    validate_event(paused_events[0])
    assert store.worlds[WORLD].paused is True


def test_FR_HIL_07_pause_with_zero_l2_l3_policies_still_emits_exactly_one_world_paused(client, store):
    """A world with no L2/L3 policies at all (nothing whatsoever for Pause-all to lower) must
    still get exactly one world.paused on its first Pause-all call -- stopped == 0 here too, on
    the very first call, which round 3's `stopped > 0` gate also silently dropped."""
    store.worlds[WORLD] = make_world(owner=OWNER)
    # No policies at all in store.policies for this world's owner.
    as_principal(make_principal(user_id=OWNER, role="owner", world_id=WORLD))

    resp = client.post(f"/worlds/{WORLD}/pause", json={"channel": "email"})

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["paused"] is True
    assert body["stopped"] == 0
    assert body["already_l1"] == 0
    paused_events = [e for e in store.events[WORLD] if e["type"] == "world.paused"]
    assert len(paused_events) == 1
    validate_event(paused_events[0])
    assert store.worlds[WORLD].paused is True


def test_FR_HIL_07_pause_all_is_idempotent_no_duplicate_world_paused_on_a_second_sequential_call(client, store):
    """An already-paused world (the flag is True) gets no second world.paused on a later,
    sequential Pause-all -- the flag is the one thing that dedupes, exactly as PI-13-style
    idempotency dedupes Stop-all's already-L1 policies via history, not via "did anything change
    this call." "paused": true is still reported both times."""
    _world_with_policies(store, 2, level="L2")
    as_principal(make_principal(user_id=OWNER, role="owner", world_id=WORLD))

    first = client.post(f"/worlds/{WORLD}/pause", json={"channel": "web"})
    assert first.status_code == 200, first.text
    assert first.json()["paused"] is True
    assert store.worlds[WORLD].paused is True

    second = client.post(f"/worlds/{WORLD}/pause", json={"channel": "web"})
    assert second.status_code == 200, second.text
    assert second.json()["paused"] is True

    paused_events = [e for e in store.events[WORLD] if e["type"] == "world.paused"]
    assert len(paused_events) == 1, "a second Pause-all on an already-paused world must not file a duplicate"


# ---------------------------------------------------------------------------
# Round-4 finding 2 (qa, biggest): the store lock (or whatever serializes a kill switch's own
# mutation) must never be held across writer I/O -- a kill switch against one world must never
# wait on another world's writer latency, and a slow-then-failing writer for 200 policies must
# never itself blow the 5s budget by being flushed serially and synchronously.


def test_FR_HIL_07_stop_all_meets_5s_budget_with_a_slow_failing_writer_on_first_call_and_retry(client, store):
    """200 policies, a writer that sleeps 30ms then always raises: 30ms * 200 = 6s if flushed
    serially and synchronously inside whatever the route uses to serialize its own mutation --
    well over the 5s budget. Every policy must still reach L1 within 5s on the first call, and a
    second Stop-all issued while the writer is still down (now only re-attempting the flush, since
    nothing is left to lower) must also finish within 5s."""
    ids = _world_with_policies(store, 200, level="L3")
    slow_flaky = SlowFlakyEventWriter(store, delay_s=0.03)
    as_writer(slow_flaky)
    as_principal(make_principal(user_id=OWNER, role="owner", world_id=WORLD))

    started = time.perf_counter()
    first = client.post(f"/worlds/{WORLD}/autopilot/stop")
    first_elapsed = time.perf_counter() - started

    assert first.status_code in (200, 202), first.text
    assert first_elapsed <= 5.0, f"first stop-all took {first_elapsed:.2f}s with a slow failing writer"
    assert first.json()["stopped"] == 200
    for pid in ids:
        assert store.policies[pid]["level"] == "L1"

    started_2 = time.perf_counter()
    second = client.post(f"/worlds/{WORLD}/autopilot/stop")
    second_elapsed = time.perf_counter() - started_2

    assert second.status_code in (200, 202), second.text
    assert second_elapsed <= 5.0, f"second stop-all (writer still down) took {second_elapsed:.2f}s"
    assert second.json()["already_l1"] == 200
    assert second.json()["stopped"] == 0


def test_FR_HIL_07_stop_all_on_one_world_never_waits_on_another_worlds_writer_latency(client, store):
    """qa finding (biggest): a Stop-all against world A with 200 policies and a slow-then-failing
    writer must not block a concurrently-issued, single-policy Stop-all against a different world
    B. Uses as_principal_by_header instead of as_principal since the two concurrent requests need
    two *different* owner principals at once -- as_principal's single global override would race
    between the two threads."""
    big_ids = _world_with_policies(store, 200, level="L3", world_id=WORLD)
    small_ids = _world_with_policies(store, 1, owner=OTHER_OWNER, level="L2", world_id=OTHER_WORLD)
    slow_flaky = SlowFlakyEventWriter(store, delay_s=0.03)
    as_writer(slow_flaky)
    as_principal_by_header(
        {
            "big": make_principal(user_id=OWNER, role="owner", world_id=WORLD),
            "small": make_principal(user_id=OTHER_OWNER, role="owner", world_id=OTHER_WORLD),
        }
    )

    ready = threading.Event()
    big_result: dict = {}

    def stop_big():
        started = time.perf_counter()
        ready.set()
        resp = client.post(f"/worlds/{WORLD}/autopilot/stop", headers={PRINCIPAL_HEADER: "big"})
        big_result["resp"] = resp
        big_result["elapsed"] = time.perf_counter() - started

    t = threading.Thread(target=stop_big)
    t.start()
    assert ready.wait(timeout=5), "the big world's call never started"
    time.sleep(0.01)  # give it a moment to actually enter the handler

    started_small = time.perf_counter()
    small_resp = client.post(f"/worlds/{OTHER_WORLD}/autopilot/stop", headers={PRINCIPAL_HEADER: "small"})
    small_elapsed = time.perf_counter() - started_small

    t.join(timeout=10)
    assert "resp" in big_result, "the big world's call never finished"

    assert small_resp.status_code in (200, 202), small_resp.text
    assert small_elapsed < 1.0, f"stop on the other world took {small_elapsed:.2f}s, must be < 1s"
    for pid in small_ids:
        assert store.policies[pid]["level"] == "L1"

    assert big_result["resp"].status_code in (200, 202), big_result["resp"].text
    assert big_result["elapsed"] <= 5.0
    for pid in big_ids:
        assert store.policies[pid]["level"] == "L1"


# ---------------------------------------------------------------------------
# Round-4 finding 3 (code, biggest): policy.changed's vis must be computed against the policy's
# own *target* world (where the event is actually filed), never the Stop-all *request* world.


def test_FR_HIL_07_policy_changed_vis_uses_the_target_worlds_own_layout_not_the_stop_request_worlds(
    client, store, writer
):
    """A policy mapped to world B, whose scope districts exist only in B (not in the request
    world A at all), must get its policy.changed's vis computed against B's own layout. Round 3
    computed it against A's layout instead, which has nothing to intersect against -- silently
    falling back to "all" and broadcasting the change to everyone, not just B's own viewers."""
    district_only_in_b = "D5"
    store.worlds[WORLD] = make_world(owner=OWNER, districts={})  # world A: no districts at all
    store.worlds[OTHER_WORLD] = make_world(
        owner=OWNER, districts={district_only_in_b: make_district("Payroll", "Running payroll")}
    )
    store.policies["pol_mapped_to_b"] = base_policy(
        id_="pol_mapped_to_b", owner=OWNER, level="L2", districts=(district_only_in_b,)
    )
    store.policy_worlds["pol_mapped_to_b"] = OTHER_WORLD

    as_principal(make_principal(user_id=OWNER, role="owner", world_id=WORLD))
    resp = client.post(f"/worlds/{WORLD}/autopilot/stop")
    assert resp.status_code == 200, resp.text

    changed = [e for e in store.events.get(OTHER_WORLD, []) if e["type"] == "policy.changed"]
    assert len(changed) == 1
    event = changed[0]
    assert event["vis"] == [district_only_in_b], (
        "vis must come from world B's own layout (where district_only_in_b actually exists), not "
        "world A's (empty) layout -- the old, wrong behaviour fell back to 'all' here"
    )
    validate_event(event)
    assert store.events.get(WORLD, []) == [], "the event belongs to B's stream, not A's"


# ---------------------------------------------------------------------------
# Round-4 finding 5 (security): "pending" must count, and a later call must flush, parts queued
# for *any* world this call touches -- not only the request's own world_id.


def test_FR_HIL_07_pending_counts_parts_queued_for_another_world_too(client, store):
    """A Stop-all against world A owns two policies: one mapped to A itself, one mapped to a
    different world B. Both fail to write. The response's "pending" must count both, not just A's
    own queue, and both must actually be sitting in their own worlds' pending_events."""
    store.worlds[WORLD] = make_world(owner=OWNER)
    store.worlds[OTHER_WORLD] = make_world(owner=OWNER)
    store.policies["pol_in_a"] = base_policy(id_="pol_in_a", owner=OWNER, level="L2")
    store.policy_worlds["pol_in_a"] = WORLD
    store.policies["pol_in_b"] = base_policy(id_="pol_in_b", owner=OWNER, level="L2")
    store.policy_worlds["pol_in_b"] = OTHER_WORLD

    flaky = FlakyEventWriter(store, failing=True)
    as_writer(flaky)
    as_principal(make_principal(user_id=OWNER, role="owner", world_id=WORLD))

    resp = client.post(f"/worlds/{WORLD}/autopilot/stop")

    assert resp.status_code == 202, resp.text
    body = resp.json()
    assert body["stopped"] == 2
    assert body["pending"] == 2, "pending must count both A's own queue and B's, not just A's"
    assert len(store.pending_events.get(WORLD, [])) == 1
    assert len(store.pending_events.get(OTHER_WORLD, [])) == 1
    assert store.pending_events[WORLD][0]["data"]["policy_id"] == "pol_in_a"
    assert store.pending_events[OTHER_WORLD][0]["data"]["policy_id"] == "pol_in_b"


def test_FR_HIL_07_a_later_stop_all_flushes_pending_parts_of_every_world_it_touches(client, store):
    """After a failing first call leaves parts pending in both A and the mapped world B, a second
    Stop-all against A -- even though every owned policy is already L1, so it changes nothing new
    -- must still flush both A's and B's pending queues, since both are worlds this call's owned
    policies touch."""
    store.worlds[WORLD] = make_world(owner=OWNER)
    store.worlds[OTHER_WORLD] = make_world(owner=OWNER)
    store.policies["pol_in_a"] = base_policy(id_="pol_in_a", owner=OWNER, level="L2")
    store.policy_worlds["pol_in_a"] = WORLD
    store.policies["pol_in_b"] = base_policy(id_="pol_in_b", owner=OWNER, level="L2")
    store.policy_worlds["pol_in_b"] = OTHER_WORLD

    flaky = FlakyEventWriter(store, failing=True)
    as_writer(flaky)
    as_principal(make_principal(user_id=OWNER, role="owner", world_id=WORLD))

    first = client.post(f"/worlds/{WORLD}/autopilot/stop")
    assert first.status_code == 202, first.text
    assert first.json()["pending"] == 2
    assert store.events.get(WORLD, []) == []
    assert store.events.get(OTHER_WORLD, []) == []

    flaky.failing = False  # "the harness" is back up

    second = client.post(f"/worlds/{WORLD}/autopilot/stop")
    assert second.status_code == 200, second.text
    assert second.json()["already_l1"] == 2
    assert second.json()["stopped"] == 0
    assert second.json()["pending"] == 0
    assert store.pending_events.get(WORLD, []) == []
    assert store.pending_events.get(OTHER_WORLD, []) == [], "B's pending part must be flushed too"

    a_changed = [e for e in store.events[WORLD] if e["type"] == "policy.changed"]
    b_changed = [e for e in store.events[OTHER_WORLD] if e["type"] == "policy.changed"]
    assert len(a_changed) == 1
    assert len(b_changed) == 1
    validate_event(a_changed[0])
    validate_event(b_changed[0])


# ---------------------------------------------------------------------------
# Round-4 finding 6 (qa/security follow-up): revoke must never 500 when the writer is down -- the
# policy is lowered, the event goes to pending, and it is flushed by a later mutating call.


def test_FR_HIL_07_revoke_with_the_writer_down_lowers_the_policy_and_queues_a_pending_event(client, store):
    store.worlds[WORLD] = make_world(owner=OWNER)
    store.policies["pol_autopilot_l2"] = base_policy(id_="pol_autopilot_l2", owner=OWNER, level="L2")
    store.policy_worlds["pol_autopilot_l2"] = WORLD
    flaky = FlakyEventWriter(store, failing=True)
    as_writer(flaky)
    as_principal(make_principal(user_id=OWNER, role="owner", world_id=WORLD))

    resp = client.post("/policies/pol_autopilot_l2/revoke")

    assert resp.status_code == 200, resp.text  # never a 500, even with the writer down
    policy = store.policies["pol_autopilot_l2"]
    assert policy["level"] == "L1"
    assert policy["history"][-1]["change"] == "revoked"
    assert store.events.get(WORLD, []) == []

    pending = store.pending_events.get(WORLD, [])
    assert len(pending) == 1
    assert pending[0]["type"] == "policy.changed"
    assert pending[0]["data"]["change"] == "revoked"
    assert pending[0]["data"]["policy_id"] == "pol_autopilot_l2"
    assert_part_carries_no_stamped_fields(pending[0])

    flaky.failing = False  # "the harness" is back up
    follow_up = client.post(f"/worlds/{WORLD}/autopilot/stop")  # a later mutating call touching WORLD
    assert follow_up.status_code == 200, follow_up.text
    assert store.pending_events.get(WORLD, []) == []

    changed = [e for e in store.events[WORLD] if e["type"] == "policy.changed" and e["data"]["change"] == "revoked"]
    assert len(changed) == 1
    validate_event(changed[0])


# ---------------------------------------------------------------------------
# Round-5 finding 2 (qa biggest, security): a world's lock must never be held across writer I/O,
# and every writer attempt carries its own bounded deadline. Stop-all and Pause-all must return
# within 5s even against a writer whose append() never returns at all; a second call against the
# *same* world, or a *different* owner's call against a world the first call merely also touches,
# must not be held up by the first call's still-in-flight (or already-abandoned) writer attempt.


def test_FR_HIL_07_stop_all_returns_within_5s_against_a_writer_that_never_returns(client, store):
    ids = _world_with_policies(store, 5, level="L2")
    blocking = BlockingEventWriter(store)
    as_writer(blocking)
    as_principal(make_principal(user_id=OWNER, role="owner", world_id=WORLD))

    result: dict = {}

    def call():
        started = time.monotonic()
        resp = client.post(f"/worlds/{WORLD}/autopilot/stop")
        result["resp"] = resp
        result["elapsed"] = time.monotonic() - started

    t = threading.Thread(target=call, daemon=True)
    t.start()
    try:
        assert blocking.entered.wait(timeout=5), "the call never reached the (blocking) writer"
        t.join(timeout=8.0)
        assert not t.is_alive(), (
            "stop-all never returned against a writer whose append() never returns -- the world "
            "lock (or an unbounded per-writer-call wait) is blocking the whole request past its "
            "5s budget"
        )
        assert "resp" in result
        resp = result["resp"]
        assert resp.status_code in (200, 202), resp.text
        assert result["elapsed"] <= 5.0, f"stop-all took {result['elapsed']:.2f}s against a writer that never returns"
        body = resp.json()
        assert body["stopped"] == len(ids)
        for pid in ids:
            assert store.policies[pid]["level"] == "L1"
        assert body["pending"] >= 1, "an attempt that misses its deadline must stay pending, not be lost"
    finally:
        blocking.release()
        t.join(timeout=5.0)


def test_FR_HIL_07_pause_all_returns_within_5s_against_a_writer_that_never_returns(client, store):
    ids = _world_with_policies(store, 3, level="L3")
    blocking = BlockingEventWriter(store)
    as_writer(blocking)
    as_principal(make_principal(user_id=OWNER, role="owner", world_id=WORLD))

    result: dict = {}

    def call():
        started = time.monotonic()
        resp = client.post(f"/worlds/{WORLD}/pause", json={"channel": "web"})
        result["resp"] = resp
        result["elapsed"] = time.monotonic() - started

    t = threading.Thread(target=call, daemon=True)
    t.start()
    try:
        assert blocking.entered.wait(timeout=5), "the call never reached the (blocking) writer"
        t.join(timeout=8.0)
        assert not t.is_alive(), "pause-all never returned against a writer whose append() never returns"
        resp = result["resp"]
        assert resp.status_code in (200, 202), resp.text
        assert result["elapsed"] <= 5.0, f"pause-all took {result['elapsed']:.2f}s against a writer that never returns"
        body = resp.json()
        assert body["paused"] is True
        for pid in ids:
            assert store.policies[pid]["level"] == "L1"
        assert store.worlds[WORLD].paused is True
        assert body["pending"] >= 1
    finally:
        blocking.release()
        t.join(timeout=5.0)


def test_FR_HIL_07_second_stop_all_on_the_same_world_is_not_blocked_by_the_first(client, store):
    """A second Stop-all against the *same* world, issued while the first is still stuck on (or
    past the deadline of) a writer call that never returns, must itself return within 5s: by the
    time it runs, the first call's level-change section has already released the world lock (it
    never held it across writer I/O), so the second call finds every policy already at L1 and has
    nothing left to do.

    Both calls run in their own bounded background thread (never a raw, unbounded `client.post` on
    the main test thread): if the implementation under test still holds the world lock across
    writer I/O (the round-4 bug this test targets), the *second* call would itself block forever
    waiting for a lock the first call cannot release until its writer call returns -- which it
    never does until `blocking.release()` runs. A raw synchronous second call would then deadlock
    the whole test (release() is only reached after it returns); routing it through its own
    daemon thread with a join timeout instead turns that failure mode into a normal, bounded
    assertion failure."""
    ids = _world_with_policies(store, 3, level="L2")
    blocking = BlockingEventWriter(store)
    as_writer(blocking)
    as_principal(make_principal(user_id=OWNER, role="owner", world_id=WORLD))

    first_result: dict = {}
    second_result: dict = {}

    def call_first():
        started = time.monotonic()
        resp = client.post(f"/worlds/{WORLD}/autopilot/stop")
        first_result["resp"] = resp
        first_result["elapsed"] = time.monotonic() - started

    def call_second():
        started = time.monotonic()
        resp = client.post(f"/worlds/{WORLD}/autopilot/stop")
        second_result["resp"] = resp
        second_result["elapsed"] = time.monotonic() - started

    t1 = threading.Thread(target=call_first, daemon=True)
    t1.start()
    try:
        assert blocking.entered.wait(timeout=5), "the first call never reached the (blocking) writer"
        time.sleep(0.05)  # let the first call's level-change section fully settle

        t2 = threading.Thread(target=call_second, daemon=True)
        t2.start()
        t2.join(timeout=8.0)
        assert not t2.is_alive(), (
            "the second stop-all on the same world never returned while the first was still stuck "
            "on the writer -- the world lock is held across writer I/O"
        )
        assert "resp" in second_result
        second_resp = second_result["resp"]
        assert second_resp.status_code in (200, 202), second_resp.text
        assert second_result["elapsed"] <= 5.0, (
            f"second stop-all took {second_result['elapsed']:.2f}s while the first was still stuck on the writer"
        )
        for pid in ids:
            assert store.policies[pid]["level"] == "L1"
        body = second_resp.json()
        assert body["stopped"] == 0, "every policy was already lowered by the first call's (lock-scoped) mutation"
        assert body["already_l1"] == len(ids)
    finally:
        blocking.release()
        t1.join(timeout=8.0)
        assert "resp" in first_result
        assert first_result["resp"].status_code in (200, 202)
        assert first_result["elapsed"] <= 5.0


def test_FR_HIL_07_stop_all_from_another_owner_mapped_to_the_same_target_world_is_not_blocked(client, store):
    """round-5 qa/security finding: an owner's Stop-all can touch a world it does not own at all
    (via store.policy_worlds), and that world's own lock must never be held across writer I/O --
    otherwise that world's own rightful owner, calling Stop-all on their own world directly and
    concurrently, would be stalled behind a stranger's stuck write. Owner B's call runs in its own
    bounded background thread for the same deadlock-avoidance reason as the same-world test above:
    a still-buggy implementation would otherwise block it forever on world B's lock, which owner
    A's call cannot release until the (never-arriving) `blocking.release()` -- which this test only
    calls after observing owner B's call's own outcome."""
    store.worlds[WORLD] = make_world(owner=OWNER)
    store.worlds[OTHER_WORLD] = make_world(owner=OTHER_OWNER)
    store.policies["pol_a_mapped_to_b"] = base_policy(id_="pol_a_mapped_to_b", owner=OWNER, level="L2")
    store.policy_worlds["pol_a_mapped_to_b"] = OTHER_WORLD
    store.policies["pol_b_own"] = base_policy(id_="pol_b_own", owner=OTHER_OWNER, level="L2")
    store.policy_worlds["pol_b_own"] = OTHER_WORLD

    blocking = BlockingEventWriter(store)
    as_writer(blocking)
    as_principal_by_header(
        {
            "a": make_principal(user_id=OWNER, role="owner", world_id=WORLD),
            "b": make_principal(user_id=OTHER_OWNER, role="owner", world_id=OTHER_WORLD),
        }
    )

    a_result: dict = {}
    b_result: dict = {}

    def call_a():
        started = time.monotonic()
        resp = client.post(f"/worlds/{WORLD}/autopilot/stop", headers={PRINCIPAL_HEADER: "a"})
        a_result["resp"] = resp
        a_result["elapsed"] = time.monotonic() - started

    def call_b():
        started = time.monotonic()
        resp = client.post(f"/worlds/{OTHER_WORLD}/autopilot/stop", headers={PRINCIPAL_HEADER: "b"})
        b_result["resp"] = resp
        b_result["elapsed"] = time.monotonic() - started

    ta = threading.Thread(target=call_a, daemon=True)
    ta.start()
    try:
        assert blocking.entered.wait(timeout=5), "owner A's call never reached the (blocking) writer"
        time.sleep(0.05)

        tb = threading.Thread(target=call_b, daemon=True)
        tb.start()
        tb.join(timeout=5.0)
        assert not tb.is_alive(), (
            "owner B's own Stop-all on world B never returned while owner A's call was still stuck "
            "on the writer -- world B's lock is being held across owner A's writer I/O"
        )
        b_resp = b_result["resp"]
        assert b_resp.status_code in (200, 202), b_resp.text
        assert b_result["elapsed"] < 1.0, (
            f"owner B's own Stop-all on world B took {b_result['elapsed']:.2f}s -- it must not be "
            "blocked by owner A's still-in-flight write for a policy merely mapped into B"
        )
        assert store.policies["pol_b_own"]["level"] == "L1"
    finally:
        blocking.release()
        ta.join(timeout=8.0)
        assert "resp" in a_result
        assert a_result["resp"].status_code in (200, 202)
        assert a_result["elapsed"] <= 5.0
        assert store.policies["pol_a_mapped_to_b"]["level"] == "L1"


# ---------------------------------------------------------------------------
# Round-5 finding 3 (code biggest, qa): writes to one world are sequential -- in build order, and
# oldest-pending-first -- regardless of how their underlying writer calls are dispatched; only
# different worlds' writes may run in parallel with each other.


def test_FR_HIL_07_100_pending_parts_are_flushed_in_their_queued_order(client, store):
    """A world's pending backlog is invariantly oldest-first (round 3); this round pins that it is
    also *committed* to store.events in exactly that order, however the underlying writer calls are
    dispatched. ReversedDelayEventWriter sleeps less on each successive call (the first submitted
    call sleeps longest) -- a completion-order-based (rather than queue-order-based) implementation
    would visibly reorder these 100 parts; a correctly ordered one never does, regardless of timing."""
    store.worlds[WORLD] = make_world(owner=OWNER)  # no owned policies -- this call only flushes
    n = 100
    store.pending_events[WORLD] = [make_pending_part(policy_id=f"pol_{i:03d}") for i in range(n)]

    writer = ReversedDelayEventWriter(store, base_delay_s=0.03, step_s=0.0003)
    as_writer(writer)
    as_principal(make_principal(user_id=OWNER, role="owner", world_id=WORLD))

    resp = client.post(f"/worlds/{WORLD}/autopilot/stop")

    assert resp.status_code == 200, resp.text
    assert resp.json()["pending"] == 0
    assert store.pending_events.get(WORLD, []) == []
    landed = [e["data"]["policy_id"] for e in store.events.get(WORLD, [])]
    assert landed == [f"pol_{i:03d}" for i in range(n)], "pending parts must land in exactly their queued order"


def test_FR_HIL_07_pause_writes_world_paused_before_policy_changed_in_the_same_call(client, store):
    """ST-3a-3 supersedes round-5's "world.paused lands last" rule (API_ST3a.md "What changed
    since round 6 (ST-3a-2) -- ST-3a-3"): FR-WLD-07/NFR-07's 2s pause-confirmation budget means
    world.paused must now be the *first* part committed for its world, ahead of every
    policy.changed this same Pause-all call builds -- never interleaved out of that order by which
    underlying writer call happens to finish first on the wire. ReversedDelayEventWriter sleeps
    less on each successive call (the first-submitted call sleeps longest); since world.paused is
    now submitted first, a completion-order-based (rather than queue-order-based) implementation
    would visibly let it finish *last* despite that -- a correctly order-preserving one still
    commits it first, regardless of its own longer delay."""
    ids = _world_with_policies(store, 5, level="L2")
    writer = ReversedDelayEventWriter(store, base_delay_s=0.15, step_s=0.02)
    as_writer(writer)
    as_principal(make_principal(user_id=OWNER, role="owner", world_id=WORLD))

    resp = client.post(f"/worlds/{WORLD}/pause", json={"channel": "web"})

    assert resp.status_code == 200, resp.text
    events = store.events[WORLD]
    types_in_order = [e["type"] for e in events]
    assert types_in_order.count("policy.changed") == len(ids)
    assert types_in_order.count("world.paused") == 1
    paused_index = types_in_order.index("world.paused")
    assert paused_index == 0, (
        f"world.paused landed at index {paused_index} of {types_in_order} -- it must be enqueued "
        "ahead of every policy.changed this call builds (ST-3a-3, FR-WLD-07/NFR-07), never after"
    )


# ---------------------------------------------------------------------------
# Round-5 finding 4 (code/qa/security, supersedes round-4 ambiguity 12): revoke now flushes its
# target world's whole pending backlog first, oldest first, under that world's lock -- not only a
# part its own earlier attempt might have left there.


def test_FR_HIL_07_revoke_flushes_its_worlds_pending_parts_before_its_own(client, store, writer):
    store.worlds[WORLD] = make_world(owner=OWNER)
    store.policies["pol_to_revoke"] = base_policy(id_="pol_to_revoke", owner=OWNER, level="L2")
    store.policy_worlds["pol_to_revoke"] = WORLD

    store.pending_events[WORLD] = [make_pending_part(policy_id=f"pol_stale_{i}") for i in range(3)]

    as_principal(make_principal(user_id=OWNER, role="owner", world_id=WORLD))
    resp = client.post("/policies/pol_to_revoke/revoke")

    assert resp.status_code == 200, resp.text
    assert store.pending_events.get(WORLD, []) == [], (
        "revoke must flush the whole world's pending queue, not only its own part (supersedes round-4 ambiguity 12)"
    )

    events = store.events[WORLD]
    stale_ids_in_order = [
        e["data"]["policy_id"] for e in events if str(e["data"].get("policy_id", "")).startswith("pol_stale_")
    ]
    assert stale_ids_in_order == ["pol_stale_0", "pol_stale_1", "pol_stale_2"], "pending parts flush oldest first"

    own = [e for e in events if e["data"].get("policy_id") == "pol_to_revoke"]
    assert len(own) == 1
    assert events.index(own[0]) == len(events) - 1, "revoke's own new part lands after the flushed backlog"
    validate_event(own[0])


def test_FR_HIL_07_revoke_and_a_concurrent_stop_all_on_the_same_world_never_double_write_a_pending_part(client, store):
    """Revoke's own flush of its target world's pending queue and a concurrently-issued Stop-all
    against that same world must serialize under that world's lock (round-5: revoke's own
    level/history mutation and flush now run under the lock, where round 4 had neither) -- otherwise
    both could read the same stale pending backlog and hand the same part to the writer twice."""
    store.worlds[WORLD] = make_world(owner=OWNER)
    store.policies["pol_to_revoke"] = base_policy(id_="pol_to_revoke", owner=OWNER, level="L3")
    store.policy_worlds["pol_to_revoke"] = WORLD
    store.policies["pol_other"] = base_policy(id_="pol_other", owner=OWNER, level="L2")
    store.policy_worlds["pol_other"] = WORLD

    store.pending_events[WORLD] = [make_pending_part(policy_id="pol_stale")]

    slow = SlowEventWriter(store, delay_s=0.08)
    as_writer(slow)
    as_principal(make_principal(user_id=OWNER, role="owner", world_id=WORLD))

    barrier = threading.Barrier(2)
    responses: list = []
    errors: list = []

    def call_revoke():
        try:
            barrier.wait(timeout=5)
            responses.append(("revoke", client.post("/policies/pol_to_revoke/revoke")))
        except Exception as exc:  # pragma: no cover - surfaced via the assert below
            errors.append(exc)

    def call_stop():
        try:
            barrier.wait(timeout=5)
            responses.append(("stop", client.post(f"/worlds/{WORLD}/autopilot/stop")))
        except Exception as exc:  # pragma: no cover - surfaced via the assert below
            errors.append(exc)

    threads = [threading.Thread(target=call_revoke), threading.Thread(target=call_stop)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=10)

    assert not errors, errors
    assert len(responses) == 2
    for _, r in responses:
        assert r.status_code in (200, 202), r.text

    stale_writes = [e for e in store.events.get(WORLD, []) if e["data"].get("policy_id") == "pol_stale"]
    assert len(stale_writes) == 1, f"the stale pending part must be written exactly once, got {len(stale_writes)}"
    assert store.pending_events.get(WORLD, []) == []

    assert store.policies["pol_to_revoke"]["level"] == "L1"
    assert store.policies["pol_other"]["level"] == "L1"


# ---------------------------------------------------------------------------
# Round-6 (ST-3a-2, issue #38 item 1, security/qa/code, blocking): a malformed stored scope must
# never abort a kill switch. `policy_vis` (tilo_api.events) intersects scope.districts against a
# world's own district keys; today a non-string entry (the issue's own example: [["D1"]], but "any
# non-string entry" per the ticket) raises TypeError, since `d in world_districts` (a dict) tries to
# hash `d`. That currently happens *inside* the locked block, after a touched world's pending
# backlog has already been popped into a local variable -- so today's implementation both 500s and
# silently drops whatever was popped (which can include an already-durably-queued world.paused).
# Every test below must see neither: a clean 200/202, every targeted policy at L1, and nothing lost.


def _policy_with_malformed_scope(*, id_: str, owner: str = OWNER, level: str = "L2") -> dict:
    policy = base_policy(id_=id_, owner=owner, level=level)
    # Mixed non-string entries "among others" (this ticket's own wording), plus one real district id
    # so the fixed intersection logic still has something valid left to consider.
    policy["scope"]["districts"] = [["D1"], 123, None, {"x": 1}, "D9"]
    return policy


def _stale_world_paused_part() -> dict:
    """An event *part* (API_ST3a.md's EventWriter.append shape) standing in for a world.paused an
    earlier (failed) Pause-all already built and left pending. Carries its own id (issue #46):
    a pending part is exactly the same "full event, id included" shape a route now builds."""
    return {
        "id": ulid(800_000_001),
        "type": "world.paused",
        "actor": OWNER,
        "target": WORLD,
        "level": None,
        "district": None,
        "item": None,
        "severity": "info",
        "credits": 0,
        "summary": "Pause all stopped every agent in this world",
        "cause": None,
        "vis": "all",
        "authz": None,
        "data": {"reason": "pause_all", "channel": "web"},
    }


def test_FR_HIL_07_malformed_scope_stop_all_never_500s_and_reaches_l1(client, store):
    # A world with at least one real district: policy_vis's `if not world_districts: return "all"`
    # short-circuits on an empty layout *before* ever reaching the intersection line that raises on
    # a non-string scope.districts entry -- an empty-districts world would never actually exercise
    # the bug this test exists to pin.
    store.worlds[WORLD] = make_world(owner=OWNER, districts={"D9": make_district("Ops", "test district")})
    store.policies["pol_malformed"] = _policy_with_malformed_scope(id_="pol_malformed")
    store.policy_worlds["pol_malformed"] = WORLD
    ok_ids = []
    for i in range(3):
        pid = f"pol_ok_{i}"
        store.policies[pid] = base_policy(id_=pid, owner=OWNER, level="L2")
        store.policy_worlds[pid] = WORLD
        ok_ids.append(pid)
    as_principal(make_principal(user_id=OWNER, role="owner", world_id=WORLD))

    resp = client.post(f"/worlds/{WORLD}/autopilot/stop")

    assert resp.status_code in (200, 202), resp.text
    for pid in ["pol_malformed", *ok_ids]:
        assert store.policies[pid]["level"] == "L1", f"{pid} never reached L1"
        assert store.policies[pid]["history"][-1]["change"] == "stop_all"

    changed = [e for e in store.events.get(WORLD, []) if e["type"] == "policy.changed"]
    seen = [e["data"]["policy_id"] for e in changed]
    assert sorted(seen) == sorted(["pol_malformed", *ok_ids]), (
        "every targeted policy, including the one with a malformed scope, must get exactly one "
        "policy.changed -- none lost, none duplicated, never a 500"
    )
    assert len(seen) == len(set(seen)), "no policy.changed was written twice"


def test_FR_HIL_07_malformed_scope_pause_all_writes_a_pending_world_paused_exactly_once(client, store, writer):
    """A world.paused an earlier call already built and left pending must still be written exactly
    once even when this call's own owned-policy scan also includes a policy with a malformed
    scope."""
    store.worlds[WORLD] = make_world(  # the earlier call already flipped `paused`
        owner=OWNER, paused=True, districts={"D9": make_district("Ops", "test district")}
    )
    store.policies["pol_malformed"] = _policy_with_malformed_scope(id_="pol_malformed")
    store.policy_worlds["pol_malformed"] = WORLD
    store.pending_events[WORLD] = [_stale_world_paused_part()]

    as_principal(make_principal(user_id=OWNER, role="owner", world_id=WORLD))
    resp = client.post(f"/worlds/{WORLD}/pause", json={"channel": "web"})

    assert resp.status_code in (200, 202), resp.text
    assert store.policies["pol_malformed"]["level"] == "L1"

    paused_events = [e for e in store.events.get(WORLD, []) if e["type"] == "world.paused"]
    assert len(paused_events) == 1, (
        f"the already-pending world.paused part must be written exactly once, got {len(paused_events)} "
        "-- a malformed policy elsewhere in the same call must not lose it"
    )
    assert store.pending_events.get(WORLD, []) == []


def test_FR_HIL_07_malformed_scope_pause_all_never_loses_a_pending_part_when_the_writer_is_down(client, store):
    """Same setup, but the writer cannot accept anything this call either: the pre-existing pending
    part must be put back (still pending, not lost) rather than vanishing because a malformed
    policy raised after it had already been popped from store.pending_events."""
    store.worlds[WORLD] = make_world(owner=OWNER, paused=True, districts={"D9": make_district("Ops", "test district")})
    store.policies["pol_malformed"] = _policy_with_malformed_scope(id_="pol_malformed")
    store.policy_worlds["pol_malformed"] = WORLD
    store.pending_events[WORLD] = [_stale_world_paused_part()]

    flaky = FlakyEventWriter(store, failing=True)
    as_writer(flaky)
    as_principal(make_principal(user_id=OWNER, role="owner", world_id=WORLD))

    resp = client.post(f"/worlds/{WORLD}/pause", json={"channel": "web"})

    assert resp.status_code == 202, resp.text
    assert store.policies["pol_malformed"]["level"] == "L1"
    still_pending = store.pending_events.get(WORLD, [])
    types = [p["type"] for p in still_pending]
    # The stale world.paused is never lost, and pol_malformed's own policy.changed is queued too
    # (with the writer down, dropping it would lose that event for good, PI-13), oldest first.
    assert types == ["world.paused", "policy.changed"], (
        f"expected the stale part put back plus this call's own part, oldest first -- got {types}"
    )


def test_FR_HIL_07_malformed_scope_revoke_never_500s_and_reaches_l1(client, store, writer):
    store.worlds[WORLD] = make_world(owner=OWNER, districts={"D9": make_district("Ops", "test district")})
    store.policies["pol_malformed"] = _policy_with_malformed_scope(id_="pol_malformed")
    store.policy_worlds["pol_malformed"] = WORLD
    as_principal(make_principal(user_id=OWNER, role="owner", world_id=WORLD))

    resp = client.post("/policies/pol_malformed/revoke")

    assert resp.status_code == 200, resp.text
    assert resp.json() == {"policy_id": "pol_malformed", "level": "L1"}
    assert store.policies["pol_malformed"]["level"] == "L1"
    assert store.policies["pol_malformed"]["history"][-1]["change"] == "revoked"

    changed = [e for e in store.events.get(WORLD, []) if e["type"] == "policy.changed"]
    assert len(changed) == 1
    assert changed[0]["data"]["policy_id"] == "pol_malformed"
    assert changed[0]["data"]["change"] == "revoked"


# ---------------------------------------------------------------------------
# Round-6 (ST-3a-2, issue #38 item 2, code/qa, biggest): one ordered writer per world -- a part
# whose attempt misses its deadline is queued pending while the underlying attempt keeps running;
# if it later succeeds for real without ever being cleared from pending, a later flush re-sends the
# same part and it lands in store.events twice.


def test_FR_HIL_07_late_writer_success_is_written_at_most_once(client, store):
    ids = _world_with_policies(store, 2, level="L2")
    late = LateSuccessEventWriter(store, delay_s=0.7)  # past _MAX_PART_DEADLINE_S (0.5s)
    as_writer(late)
    as_principal(make_principal(user_id=OWNER, role="owner", world_id=WORLD))

    resp1 = client.post(f"/worlds/{WORLD}/autopilot/stop")
    assert resp1.status_code in (200, 202), resp1.text
    body1 = resp1.json()
    assert body1["stopped"] == len(ids)
    for pid in ids:
        assert store.policies[pid]["level"] == "L1"

    assert late.first_call_settled.wait(timeout=2.0), "the slow first writer call never actually completed"

    # A second mutating call against the same world: every policy is already L1 (nothing new to
    # lower), but "Pending writes and flush" still requires this call to flush what is pending.
    resp2 = client.post(f"/worlds/{WORLD}/autopilot/stop")
    assert resp2.status_code in (200, 202), resp2.text
    body2 = resp2.json()
    assert body2["already_l1"] == len(ids), "both policies were already lowered by the first call"

    for pid in ids:
        landed = [e for e in store.events.get(WORLD, []) if e["data"].get("policy_id") == pid]
        assert len(landed) == 1, (
            f"{pid}'s policy.changed part was written {len(landed)} times -- an attempt that misses "
            "its deadline but later succeeds in the background must never be re-sent once it has "
            "actually landed"
        )
    assert store.pending_events.get(WORLD, []) == [], "a part that has actually succeeded must not stay pending"

    for call in late.calls:
        assert_part_carries_no_stamped_fields(call.part)  # no idempotency key smuggled into the part API


# ---------------------------------------------------------------------------
# Round-6 (ST-3a-2, issue #38 item 3, qa): bounded threads -- _write_world builds a brand-new
# ThreadPoolExecutor per call and shuts it down with wait=False, which never waits for (or bounds)
# a worker thread still blocked inside a hung writer.append; a fresh pool per call leaks roughly one
# thread per part per call, unboundedly.


def test_FR_HIL_07_bounded_threads_against_a_writer_that_never_returns(client, store):
    ids = _world_with_policies(store, 5, level="L2")
    blocking = BlockingEventWriter(store)
    as_writer(blocking)
    as_principal(make_principal(user_id=OWNER, role="owner", world_id=WORLD))

    baseline = threading.active_count()
    try:
        for i in range(20):
            resp = client.post(f"/worlds/{WORLD}/autopilot/stop")
            assert resp.status_code in (200, 202), f"call {i}: {resp.text}"
        grown = threading.active_count() - baseline
        assert grown <= 25, (
            f"thread count grew by {grown} after 20 Stop-alls (5 policies each) against a writer "
            "that never returns -- expected a small, bounded constant per world, not roughly one "
            f"leaked thread per part per call (unbounded growth would be close to {20 * len(ids)})"
        )
    finally:
        blocking.release()


# ---------------------------------------------------------------------------
# Round-6 (ST-3a-2, issue #38 item 5): world.paused.data.channel is derived from the principal's
# own resolved session channel, never from the request body.


def test_FR_HIL_07_pause_channel_is_derived_from_the_principals_session_not_the_body(client, store, writer):
    _world_with_policies(store, 2, level="L2")
    as_principal(make_principal(user_id=OWNER, role="owner", world_id=WORLD, channel="whatsapp"))

    resp = client.post(f"/worlds/{WORLD}/pause", json={"channel": "email"})

    assert resp.status_code == 200, resp.text
    paused_events = [e for e in store.events[WORLD] if e["type"] == "world.paused"]
    assert len(paused_events) == 1
    assert paused_events[0]["data"]["channel"] == "whatsapp", (
        "world.paused.data.channel must be the principal's own session channel, never the body's claim"
    )


def test_FR_HIL_07_pause_channel_defaults_to_web_when_the_principal_carries_none(client, store, writer):
    _world_with_policies(store, 2, level="L2")
    as_principal(make_principal(user_id=OWNER, role="owner", world_id=WORLD))  # channel defaults to "web"

    resp = client.post(f"/worlds/{WORLD}/pause", json={"channel": "whatsapp"})

    assert resp.status_code == 200, resp.text
    paused_events = [e for e in store.events[WORLD] if e["type"] == "world.paused"]
    assert len(paused_events) == 1
    assert paused_events[0]["data"]["channel"] == "web", (
        "a body claiming a different channel must be ignored; the default session channel is 'web'"
    )


# ---------------------------------------------------------------------------
# Round-6 (ST-3a-2, issue #38 item 5): revoke of an unmapped policy is done under a (policy-scoped)
# lock -- two concurrent revokes of the same unmapped policy must not silently drop one's history
# entry, and an unrelated, concurrently issued Stop-all against a different owner's world must not
# be blocked by it.


def test_FR_HIL_07_revoke_of_an_unmapped_policy_is_locked_against_a_concurrent_revoke_and_stop(client, store):
    policy = base_policy(id_="pol_unmapped", owner=OTHER_OWNER, level="L2")
    policy["history"] = None  # missing/malformed history: both concurrent readers must build their
    # own fresh list unless a lock serializes them -- a shared, already-list history's .append is
    # GIL-atomic and would hide the race entirely
    store.policies["pol_unmapped"] = SlowHistoryPolicy(policy)
    # deliberately absent from store.policy_worlds -- the no-mapping case (ambiguity 7)

    store.worlds[WORLD] = make_world(owner=OWNER)
    store.policies["pol_other"] = base_policy(id_="pol_other", owner=OWNER, level="L2")
    store.policy_worlds["pol_other"] = WORLD

    as_principal_by_header(
        {
            "revoker": make_principal(user_id=OTHER_OWNER, role="owner", world_id=None),
            "stopper": make_principal(user_id=OWNER, role="owner", world_id=WORLD),
        }
    )

    responses: list = []
    errors: list = []
    start = threading.Barrier(3, timeout=5)

    def call_revoke() -> None:
        try:
            start.wait()
            responses.append(
                ("revoke", client.post("/policies/pol_unmapped/revoke", headers={PRINCIPAL_HEADER: "revoker"}))
            )
        except Exception as exc:  # pragma: no cover - surfaced via the assert below
            errors.append(exc)

    def call_stop() -> None:
        try:
            start.wait()
            responses.append(
                (
                    "stop",
                    client.post(f"/worlds/{WORLD}/autopilot/stop", headers={PRINCIPAL_HEADER: "stopper"}),
                )
            )
        except Exception as exc:  # pragma: no cover - surfaced via the assert below
            errors.append(exc)

    threads = [
        threading.Thread(target=call_revoke),
        threading.Thread(target=call_revoke),
        threading.Thread(target=call_stop),
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=10)
    assert not any(t.is_alive() for t in threads), "a concurrent revoke and stop deadlocked"
    assert not errors, errors
    assert len(responses) == 3
    for _, r in responses:
        assert r.status_code in (200, 202), r.text

    assert store.policies["pol_unmapped"]["level"] == "L1"
    history = store.policies["pol_unmapped"]["history"]
    assert len(history) == 2, (
        "two concurrent revokes of the same unmapped policy must both land their own history entry "
        f"-- an unlocked read-modify-write can silently drop one, got {len(history)} entries"
    )
    assert [h["change"] for h in history] == ["revoked", "revoked"]

    assert store.policies["pol_other"]["level"] == "L1", "an unrelated Stop-all must not be blocked or corrupted"


# ---------------------------------------------------------------------------
# ST-3a-3 (PR #39, issue #38's last comment): round 6's `_WorldChannel` (an 8-worker pool, a
# per-call pending snapshot, `_in_flight` keyed by id(part)) reproduced, under real concurrency,
# duplicate writes, out-of-build-order commits, a world permanently stuck behind a hung writer
# (queued futures stay bound to the writer instance captured at submit time, so a healthy writer
# swapped in afterward gets zero calls), and id(part) reuse after GC silently dropping an unrelated
# part. The resolved design (API_ST3a.md "What changed since round 6 (ST-3a-2) -- ST-3a-3"): one
# consumer per world, owning a queue that lives on the Store instance itself; a route only enqueues
# under the world lock then waits up to budget; the head of a world's queue is never passed until
# it settles; dedupe on a stable id carried alongside the part, never id(part); a hung attempt frees
# its worker so the backlog can drain against whatever writer is current once the head settles, no
# restart needed; and world.paused now jumps to the front of its world's queue, ahead of any audit
# part (this call's own policy.changed, or an older pending backlog), so FR-WLD-07/NFR-07's 2s
# pause-confirmation budget holds even against a slow writer working through unrelated backlog.


def test_FR_HIL_07_three_concurrent_stop_alls_plus_revokes_against_a_partially_slow_writer(client, store):
    """Three concurrent Stop-alls (the owner double- and triple-tapping the kill switch, or app +
    WhatsApp + a retry racing) against ten owned policies, plus two concurrent revokes of two other
    policies in the same world (a different owner, so Stop-all's own owned-policy scan never also
    targets them -- keeping each policy's expected event count unambiguous), against a writer that
    is slow on roughly half its calls: every part is written exactly once, and the parts one call
    builds together under one lock hold commit to store.events in that same build (plan) order,
    whichever underlying writer call happens to finish first on the wire.

    Real thread scheduling cannot be forced deterministically, and Hypothesis shrinking a
    concurrency bug would just re-run the same non-deterministic race rather than find a smaller
    one -- so this repeats the race across several seeded trials instead (root CLAUDE.md: "seeded
    loop" is the ticket's own stated fallback when Hypothesis is not a good fit)."""
    n_stop_policies = 10
    trials = 5
    for trial in range(trials):
        store.worlds.clear()
        store.policies.clear()
        store.policy_worlds.clear()
        store.events.clear()
        store.pending_events.clear()

        store.worlds[WORLD] = make_world(owner=OWNER)
        stop_ids = []
        for i in range(n_stop_policies):
            pid = f"pol_stop_{i}"
            store.policies[pid] = base_policy(id_=pid, owner=OWNER, level="L2")
            store.policy_worlds[pid] = WORLD
            stop_ids.append(pid)
        revoke_ids = []
        for i in range(2):
            pid = f"pol_revoke_{i}"
            store.policies[pid] = base_policy(id_=pid, owner=OTHER_OWNER, level="L3")
            store.policy_worlds[pid] = WORLD
            revoke_ids.append(pid)

        writer = PartiallySlowEventWriter(store, delay_s=0.04, slow_fraction=0.5, seed=1000 + trial)
        as_writer(writer)
        as_principal_by_header(
            {
                "stopper": make_principal(user_id=OWNER, role="owner", world_id=WORLD),
                "revoker": make_principal(user_id=OTHER_OWNER, role="owner", world_id=None),
            }
        )

        responses: list = []
        errors: list = []
        barrier = threading.Barrier(5, timeout=5)

        def call_stop():
            try:
                barrier.wait()
                responses.append(
                    ("stop", client.post(f"/worlds/{WORLD}/autopilot/stop", headers={PRINCIPAL_HEADER: "stopper"}))
                )
            except Exception as exc:  # pragma: no cover - surfaced via the assert below
                errors.append(exc)

        def call_revoke(pid: str):
            try:
                barrier.wait()
                responses.append(
                    ("revoke", client.post(f"/policies/{pid}/revoke", headers={PRINCIPAL_HEADER: "revoker"}))
                )
            except Exception as exc:  # pragma: no cover - surfaced via the assert below
                errors.append(exc)

        threads = [threading.Thread(target=call_stop, daemon=True) for _ in range(3)]
        threads += [threading.Thread(target=call_revoke, args=(pid,), daemon=True) for pid in revoke_ids]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=10)
        assert not any(t.is_alive() for t in threads), f"trial {trial}: a call hung"
        assert not errors, f"trial {trial}: {errors}"
        assert len(responses) == 5
        for _, r in responses:
            assert r.status_code in (200, 202), f"trial {trial}: {r.text}"

        # Give any part that missed its deadline this call every chance to have landed.
        flush = client.post(f"/worlds/{WORLD}/autopilot/stop", headers={PRINCIPAL_HEADER: "stopper"})
        assert flush.status_code in (200, 202), flush.text

        events = store.events.get(WORLD, [])
        stop_all_events = [e for e in events if e["type"] == "policy.changed" and e["data"]["change"] == "stop_all"]
        revoked_events = [e for e in events if e["type"] == "policy.changed" and e["data"]["change"] == "revoked"]

        stop_seen = [e["data"]["policy_id"] for e in stop_all_events]
        assert stop_seen == stop_ids, (
            f"trial {trial}: stop_all parts must be exactly {stop_ids} in build (plan) order, got {stop_seen} "
            "-- either a duplicate/missing write, or a build-order violation"
        )

        revoked_seen = [e["data"]["policy_id"] for e in revoked_events]
        assert sorted(revoked_seen) == sorted(revoke_ids), f"trial {trial}: {revoked_seen} vs {revoke_ids}"
        assert len(revoked_seen) == len(set(revoked_seen)), f"trial {trial}: a revoked part was written more than once"

        for pid in stop_ids + revoke_ids:
            assert store.policies[pid]["level"] == "L1", f"trial {trial}: {pid}"
        assert store.pending_events.get(WORLD, []) == [], f"trial {trial}: pending left after the final flush"


# The round-7/ST-3a-3 version of this test proved recovery by *swapping in* a brand-new,
# healthy FakeEventWriter instance once a hung backlog had been observed -- exactly the
# writer-*identity* recovery signal issue #46 (round 8) retires: a dispatcher must recover a
# world's backlog because EventWriter.append itself is answering again (id-based idempotency,
# EV-10), never because tilo-api happened to be handed a *different* writer object. That
# scenario is superseded by the round-8 tests below: `test_FR_HIL_07_pause_recovers_via_the_same_
# writer_object_once_it_stops_hanging` proves the same nine-part-backlog-style recovery using one
# shared writer instance throughout (never swapped), and
# `test_FR_HIL_07_thirty_calls_with_per_request_writers_bound_threads_and_in_flight_appends_against_a_hung_harness`
# proves the bounded-thread-growth half of the old test using fresh, per-request writer instances
# instead (the opposite extreme from "never swapped": a *new* instance on every single call).


def test_FR_HIL_07_pause_reaches_the_writer_within_2s_ahead_of_policy_changed_and_backlog(client, store):
    """FR-WLD-07 / NFR-07: world.paused must reach the writer within 2s of a Pause-all call, even
    against a slow writer and even when this call's own policy.changed parts, and an older pending
    backlog for the same world, would otherwise sit ahead of it in a plain oldest-first queue.
    ST-3a-3's rule: world.paused jumps to the front of its world's queue, ahead of any audit part
    (this call's own policy.changed, or anything already pending), so a confirmation that "Pause
    all stopped the agents" is never delayed behind an unrelated backlog."""
    ids = _world_with_policies(store, 10, level="L2")
    store.pending_events[WORLD] = [make_pending_part(policy_id=f"pol_backlog_{i}") for i in range(5)]
    slow = SlowEventWriter(store, delay_s=0.25)
    as_writer(slow)
    as_principal(make_principal(user_id=OWNER, role="owner", world_id=WORLD))

    result: dict = {}

    def call():
        result["resp"] = client.post(f"/worlds/{WORLD}/pause", json={"channel": "web"})

    started = time.monotonic()
    t = threading.Thread(target=call, daemon=True)
    t.start()
    try:
        paused_at = None
        deadline = started + 4.0
        while time.monotonic() < deadline:
            types = [e["type"] for e in store.events.get(WORLD, [])]
            if "world.paused" in types:
                paused_at = time.monotonic() - started
                assert types.index("world.paused") == 0, (
                    f"world.paused must be the first event committed for this world, got order {types}"
                )
                break
            time.sleep(0.01)

        assert paused_at is not None, "world.paused never reached the writer"
        assert paused_at <= 2.0, (
            f"world.paused reached the writer after {paused_at:.2f}s -- FR-WLD-07/NFR-07 require <= 2s"
        )
    finally:
        t.join(timeout=15.0)
    assert "resp" in result
    assert result["resp"].status_code in (200, 202), result["resp"].text
    for pid in ids:
        assert store.policies[pid]["level"] == "L1"


def test_FR_HIL_07_a_part_that_commits_late_is_never_rewritten_by_a_call_that_snapshotted_earlier(client, store):
    """The ST-3a-2 duplicate repro (issue #38 item 2, "2-3 writes in 4-7 of 20 trials"): a part
    whose writer attempt overruns its own deadline stays queued while the real attempt keeps
    running in the background; a *later* call that touches the same world reads (snapshots) that
    same pending backlog before the outstanding attempt has actually landed, then -- racing another
    such call doing the same thing -- can independently resubmit a part that has, in the narrow
    window between the instant it actually settles and the instant the store's bookkeeping catches
    up, already been committed and cleared by someone else. A sizeable backlog, processed by
    several calls at once, widens that window far more reliably than any two sequential calls can
    (this test's own first attempt at a sequential "call while one is in flight" reproduction never
    landed a single duplicate in 8 trials; concurrency is what the issue's own repro actually
    needed). Repeated across several seeded trials, since real thread scheduling cannot be forced
    deterministically (a "seeded loop," per the ticket's own stated fallback to Hypothesis)."""
    trials = 6
    backlog_n = 15
    concurrent_calls = 6
    for trial in range(trials):
        store.worlds.clear()
        store.policies.clear()
        store.policy_worlds.clear()
        store.events.clear()
        store.pending_events.clear()

        store.worlds[WORLD] = make_world(owner=OWNER)
        backlog_ids = [f"pol_backlog_{trial}_{i}" for i in range(backlog_n)]
        store.pending_events[WORLD] = [make_pending_part(policy_id=pid) for pid in backlog_ids]

        writer = PartiallySlowEventWriter(store, delay_s=0.05, slow_fraction=0.6, seed=500 + trial)
        as_writer(writer)
        as_principal(make_principal(user_id=OWNER, role="owner", world_id=WORLD))

        barrier = threading.Barrier(concurrent_calls, timeout=5)
        responses: list = []
        errors: list = []

        def call():
            try:
                barrier.wait()
                responses.append(client.post(f"/worlds/{WORLD}/autopilot/stop"))
            except Exception as exc:  # pragma: no cover - surfaced via the assert below
                errors.append(exc)

        threads = [threading.Thread(target=call, daemon=True) for _ in range(concurrent_calls)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=15)
        assert not any(t.is_alive() for t in threads), f"trial {trial}: a call hung"
        assert not errors, f"trial {trial}: {errors}"
        assert len(responses) == concurrent_calls
        for r in responses:
            assert r.status_code in (200, 202), f"trial {trial}: {r.text}"

        # A final flush pass gives any still-outstanding remnant every remaining chance to land.
        flush = client.post(f"/worlds/{WORLD}/autopilot/stop")
        assert flush.status_code in (200, 202), flush.text

        events = store.events.get(WORLD, [])
        counts: dict[str, int] = {}
        for e in events:
            counts[e["data"]["policy_id"]] = counts.get(e["data"]["policy_id"], 0) + 1
        dupes = {pid: n for pid, n in counts.items() if n > 1}
        assert not dupes, f"trial {trial}: parts written more than once -- {dupes}"
        assert sorted(counts) == sorted(backlog_ids), (
            f"trial {trial}: expected every backlog part written exactly once, got counts {counts}"
        )
        assert store.pending_events.get(WORLD, []) == [], f"trial {trial}: pending left after the final flush"


def test_FR_HIL_07_repeated_allocation_and_gc_never_drops_or_duplicates_a_part(client, store):
    """issue #38 item 4: dedup keyed on id(part) can silently treat a brand-new part as an
    already-seen one once CPython's allocator reuses a freed part dict's address (3 of 20 trials in
    the issue's own repro). Built by creating and dropping many short-lived part dicts in a tight
    loop -- one small Stop-all per fresh, otherwise-untouched policy, with gc.collect() nudging the
    allocator to actually reuse those freed addresses -- then asserting every single one is still
    written, exactly once, never silently dropped and never doubled."""
    n = 150
    store.worlds[WORLD] = make_world(owner=OWNER)
    slow = SlowEventWriter(store, delay_s=0.01)
    as_writer(slow)
    as_principal(make_principal(user_id=OWNER, role="owner", world_id=WORLD))

    pids = []
    for i in range(n):
        pid = f"pol_churn_{i}"
        store.policies[pid] = base_policy(id_=pid, owner=OWNER, level="L2")
        store.policy_worlds[pid] = WORLD
        pids.append(pid)

        resp = client.post(f"/worlds/{WORLD}/autopilot/stop")
        assert resp.status_code in (200, 202), f"{pid}: {resp.text}"
        if i % 10 == 0:
            gc.collect()  # encourage the allocator to reuse just-freed part-dict addresses

    final = client.post(f"/worlds/{WORLD}/autopilot/stop")  # flush anything left from the tail of the loop
    assert final.status_code in (200, 202), final.text

    for pid in pids:
        assert store.policies[pid]["level"] == "L1", pid
        landed = [e for e in store.events.get(WORLD, []) if e["data"].get("policy_id") == pid]
        assert len(landed) == 1, f"{pid} written {len(landed)} times -- id() reuse must never drop or duplicate a part"
    assert store.pending_events.get(WORLD, []) == []


def test_FR_HIL_07_stable_ids_survive_a_pending_queue_rebuilt_mid_flight(client, store):
    """A persisted queue (Firestore, a later ticket) round-trips a part through brand-new Python
    objects with identical content but a different id() on every load. Dedupe keyed on id(part)
    (round 6's bug) loses track of an in-flight attempt the instant the queue is rebuilt this way,
    and can resubmit it once the original attempt eventually settles. ST-3a-3's fix is a stable id
    carried alongside the part, never id() -- this proves it survives exactly that kind of
    rebuild."""
    store.worlds[WORLD] = make_world(owner=OWNER)
    store.pending_events[WORLD] = [make_pending_part(policy_id="pol_persisted")]

    late = LateSuccessEventWriter(store, delay_s=0.8)
    as_writer(late)
    as_principal(make_principal(user_id=OWNER, role="owner", world_id=WORLD))

    result: dict = {}

    def call_first():
        result["resp1"] = client.post(f"/worlds/{WORLD}/autopilot/stop")

    t = threading.Thread(target=call_first, daemon=True)
    t.start()

    time.sleep(0.2)  # the flush attempt for pol_persisted is now in flight: its own deadline has
    # long passed, real success is still ~0.6s away
    still_pending = store.pending_events.get(WORLD, [])
    assert still_pending, "expected pol_persisted's part still sitting in pending_events while its attempt is in flight"
    # Simulate a reload from persistence: brand-new dict objects, identical content, different id().
    store.pending_events[WORLD] = [dict(p) for p in still_pending]

    resp2 = client.post(f"/worlds/{WORLD}/autopilot/stop")
    assert resp2.status_code in (200, 202), resp2.text

    t.join(timeout=5.0)
    assert not t.is_alive(), "the first call never returned"
    assert "resp1" in result
    assert result["resp1"].status_code in (200, 202), result["resp1"].text

    assert late.first_call_settled.wait(timeout=2.0), "the original in-flight attempt never actually landed"
    resp3 = client.post(f"/worlds/{WORLD}/autopilot/stop")  # a final flush pass
    assert resp3.status_code in (200, 202), resp3.text

    landed = [e for e in store.events.get(WORLD, []) if e["data"].get("policy_id") == "pol_persisted"]
    assert len(landed) == 1, f"pol_persisted written {len(landed)} times after its pending queue was rebuilt mid-flight"
    assert store.pending_events.get(WORLD, []) == []


def test_FR_HIL_07_two_store_instances_for_the_same_world_id_share_no_queue_or_dedupe_state(client):
    """API_ST3a.md "What changed since round 6 (ST-3a-2) -- ST-3a-3": the per-world consumer's
    queue and dedupe state must live on the Store instance itself, never a module-level dict keyed
    only by world_id -- two unrelated Store instances (two tests, two tenants) that merely happen
    to use the same world_id string must never share write-ordering, lock or dedupe state. Store
    A's writer never returns; Store B, a completely separate Store using the exact same world_id,
    must still be served promptly by its own healthy writer and must never see any of Store A's
    pending state, or vice versa."""
    store_a = make_store()
    store_b = make_store()
    store_a.worlds[WORLD] = make_world(owner=OWNER)
    store_b.worlds[WORLD] = make_world(owner=OWNER)
    store_a.policies["pol_a"] = base_policy(id_="pol_a", owner=OWNER, level="L2")
    store_a.policy_worlds["pol_a"] = WORLD
    store_b.policies["pol_b"] = base_policy(id_="pol_b", owner=OWNER, level="L2")
    store_b.policy_worlds["pol_b"] = WORLD

    blocking_a = BlockingEventWriter(store_a)
    writer_b = FakeEventWriter(store_b)

    as_store_and_writer_by_header({"a": (store_a, blocking_a), "b": (store_b, writer_b)})
    as_principal_by_header(
        {
            "a": make_principal(user_id=OWNER, role="owner", world_id=WORLD),
            "b": make_principal(user_id=OWNER, role="owner", world_id=WORLD),
        }
    )

    result: dict = {}

    def call_a():
        result["a"] = client.post(f"/worlds/{WORLD}/autopilot/stop", headers={PRINCIPAL_HEADER: "a"})

    t = threading.Thread(target=call_a, daemon=True)
    t.start()
    try:
        assert blocking_a.entered.wait(timeout=5), "store A's call never reached its (blocking) writer"
        time.sleep(0.05)  # let store A's level-change section fully settle

        started = time.monotonic()
        resp_b = client.post(f"/worlds/{WORLD}/autopilot/stop", headers={PRINCIPAL_HEADER: "b"})
        elapsed_b = time.monotonic() - started

        assert resp_b.status_code == 200, resp_b.text
        assert elapsed_b <= 2.0, (
            f"store B's call against its own healthy writer took {elapsed_b:.2f}s -- it must never "
            "wait on store A's stuck writer just because both happen to use the same world_id string"
        )
        assert store_b.policies["pol_b"]["level"] == "L1"
        landed_b = [e for e in store_b.events.get(WORLD, []) if e["data"].get("policy_id") == "pol_b"]
        assert len(landed_b) == 1
        assert store_b.pending_events.get(WORLD, []) == []

        assert store_a.policies["pol_a"]["level"] == "L1", "the level change itself is lock/I-O independent"
        assert not any(e["data"].get("policy_id") == "pol_b" for e in store_a.events.get(WORLD, [])), (
            "store B's event must never land in store A's event log"
        )
        assert not [e for e in store_a.events.get(WORLD, []) if e["data"].get("policy_id") == "pol_a"], (
            "store A's own part is still stuck behind its own blocking writer"
        )
    finally:
        blocking_a.release()
        t.join(timeout=5.0)
    assert "a" in result
    assert result["a"].status_code in (200, 202), result["a"].text


# ---------------------------------------------------------------------------
# Round 8 (issue #46, S0's decision, binding -- kill-switch redo): "The idempotency key already
# exists: every event carries a required ULID `id`... use it." EventWriter.append now receives the
# full, pre-built event -- id included -- built once at enqueue time and resent unchanged on every
# retry; dedupe is on that id, never on raw content (round 7's `_content_key`) and never on
# writer-*instance* identity (round 7's `head.attempt_writer is writer` check, which is what made
# round 7 permanently stuck against a shared writer object that merely stopped hanging, and is
# retired by every test below that uses one shared instance throughout).


def test_FR_HIL_07_pause_recovers_via_the_same_writer_object_once_it_stops_hanging(client, store):
    """issue #46 (S0's decision): recovery must never depend on tilo-api being handed a
    *different* EventWriter instance -- production's own get_event_writer() dependency may just as
    well hand back the very same, now-recovering harness connection object on every call. One
    writer OBJECT is used for this entire test: its first-ever `.append` call hangs until
    `release()` is called (the harness momentarily wedged); every later call on that same instance
    answers immediately (HangsOnceThenWorksEventWriter, _api_lib.py). The world must recover --
    without a restart and without ever being handed a second writer instance -- and world.paused
    must land exactly once, never twice."""
    ids = _world_with_policies(store, 4, level="L2")
    shared = HangsOnceThenWorksEventWriter(store)
    as_writer(shared)
    as_principal(make_principal(user_id=OWNER, role="owner", world_id=WORLD))

    result: dict = {}

    def call_pause():
        result["resp"] = client.post(f"/worlds/{WORLD}/pause", json={"channel": "web"})

    t = threading.Thread(target=call_pause, daemon=True)
    t.start()
    try:
        assert shared.entered.wait(timeout=5), "pause never reached the (hanging) shared writer at all"
        t.join(timeout=8.0)
        assert not t.is_alive(), "pause never returned even though the level/pause-flag change is lock/I-O independent"
        assert "resp" in result
        assert result["resp"].status_code in (200, 202), result["resp"].text
        for pid in ids:
            assert store.policies[pid]["level"] == "L1"
        assert store.worlds[WORLD].paused is True

        # The same writer object throughout -- never swapped -- and the resolved flush trigger
        # stays "the next mutating call that touches this world" (ambiguity 9/21, unchanged): a
        # further call is what gives the long-lived per-world consumer another chance to retry
        # the still-stuck head, now against the very same instance that is answering again.
        deadline = time.monotonic() + 5.0
        recovered = False
        while time.monotonic() < deadline:
            recover_resp = client.post(f"/worlds/{WORLD}/autopilot/stop")
            assert recover_resp.status_code in (200, 202), recover_resp.text
            events = store.events.get(WORLD, [])
            if any(e["type"] == "world.paused" for e in events) and not store.pending_events.get(WORLD, []):
                recovered = True
                break
            time.sleep(0.05)

        assert recovered, "world.paused never landed even after the same writer object started answering again"
        events = store.events.get(WORLD, [])
        paused_events = [e for e in events if e["type"] == "world.paused"]
        assert len(paused_events) == 1, f"expected exactly one world.paused, got {len(paused_events)}"
        landed_pids = {e["data"]["policy_id"] for e in events if e["type"] == "policy.changed"}
        assert landed_pids == set(ids)
    finally:
        shared.release()
        t.join(timeout=5.0)


def test_FR_HIL_07_a_new_writer_object_per_request_over_a_slow_harness_lands_each_event_once(client, store):
    """issue #46: correctness must come from the id carried in the event itself, never from any
    writer-instance-local state -- so it must survive the realistic opposite case too, where
    get_event_writer() hands back a genuinely *different* object on every single call (an ordinary
    stateless FastAPI dependency, or a fresh per-request harness client). A 0.6s-per-append writer
    is slow enough to miss any reasonable per-part deadline at least once; repeated Stop-all calls,
    each with its own brand-new SlowEventWriter instance, must still land the policy's one
    policy.changed exactly once -- never zero, never twice -- once the backlog finally drains."""
    ids = _world_with_policies(store, 1, level="L2")
    pid = ids[0]
    as_principal(make_principal(user_id=OWNER, role="owner", world_id=WORLD))

    deadline = time.monotonic() + 6.0
    landed = 0
    while time.monotonic() < deadline:
        as_writer(SlowEventWriter(store, delay_s=0.6))  # a brand-new instance every single call
        resp = client.post(f"/worlds/{WORLD}/autopilot/stop")
        assert resp.status_code in (200, 202), resp.text
        landed = len([e for e in store.events.get(WORLD, []) if e["data"].get("policy_id") == pid])
        assert landed <= 1, f"{pid}'s policy.changed landed {landed} times -- must never exceed 1"
        if landed == 1 and not store.pending_events.get(WORLD, []):
            break

    assert landed == 1, f"{pid}'s policy.changed never landed at all across repeated per-request writer instances"
    assert store.policies[pid]["level"] == "L1"


def test_FR_HIL_07_thirty_calls_with_per_request_writers_bound_threads_and_at_most_one_append_in_flight(client, store):
    """issue #46, S0's decision point 1: "At most one append in flight per world" -- a hard cap
    that must hold even when every single call supplies its own brand-new writer instance (the
    realistic shape of get_event_writer() as an ordinary, stateless FastAPI dependency) and that
    instance never returns at all. Also re-proves round-6's original thread-leak finding (issue
    #38 item 3) stays fixed under the #46 redesign: 30 calls against a harness that never answers
    must not leak anywhere near 30 threads *per part* -- growth stays roughly proportional to the
    number of calls (one retry attempt each), never one thread per part per call."""
    store.worlds[WORLD] = make_world(owner=OWNER)
    as_principal(make_principal(user_id=OWNER, role="owner", world_id=WORLD))
    tracker = ConcurrencyTracker()

    baseline = threading.active_count()
    for i in range(30):
        pid = f"pol_thirty_{i}"
        store.policies[pid] = base_policy(id_=pid, owner=OWNER, level="L2")
        store.policy_worlds[pid] = WORLD
        as_writer(TrackingBlockingEventWriter(store, tracker))
        resp = client.post(f"/worlds/{WORLD}/autopilot/stop")
        assert resp.status_code == 202, f"call {i}: {resp.text}"

    assert tracker.max_seen <= 1, (
        f"at most one append() must ever be in flight for this world at once, saw {tracker.max_seen}"
    )
    grown = threading.active_count() - baseline
    assert grown <= 45, (
        f"thread count grew by {grown} after 30 calls against a harness that never answers -- "
        "expected roughly one retry attempt per call, not one per part per call"
    )


def test_FR_HIL_07_two_concurrent_calls_with_two_slow_writer_instances_on_one_store_produce_exactly_one_event(
    client, store
):
    """Every existing concurrent-Stop-all test (round 3/7 above) uses one *shared* SlowEventWriter
    for both racing calls; this closes the gap issue #46's id-based redesign specifically invites --
    two calls racing for the *same* policy, each handed a genuinely *different* SlowEventWriter
    instance against the same store/world, must still leave exactly one policy.changed.
    Correctness here can only come from the per-world lock serializing the level/history mutation
    (so the second call finds the policy already L1) -- never from writer-instance-local
    bookkeeping, since these two instances share none."""
    ids = _world_with_policies(store, 1, level="L2")
    pid = ids[0]
    principal = make_principal(user_id=OWNER, role="owner", world_id=WORLD)
    as_store_and_writer_by_header(
        {
            "one": (store, SlowEventWriter(store, delay_s=0.05)),
            "two": (store, SlowEventWriter(store, delay_s=0.05)),
        }
    )
    as_principal_by_header({"one": principal, "two": principal})

    barrier = threading.Barrier(2)
    responses: list = []
    errors: list = []

    def call(key: str):
        try:
            barrier.wait(timeout=5)
            responses.append(client.post(f"/worlds/{WORLD}/autopilot/stop", headers={PRINCIPAL_HEADER: key}))
        except Exception as exc:  # pragma: no cover - surfaced via the assert below
            errors.append(exc)

    threads = [threading.Thread(target=call, args=(k,)) for k in ("one", "two")]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=10)

    assert not errors, errors
    assert len(responses) == 2
    for r in responses:
        assert r.status_code in (200, 202), r.text

    assert store.policies[pid]["level"] == "L1"
    stop_all_entries = [h for h in store.policies[pid]["history"] if h.get("change") == "stop_all"]
    assert len(stop_all_entries) == 1, f"{len(stop_all_entries)} stop_all history entries across two writer instances"
    changed = [e for e in store.events.get(WORLD, []) if e["type"] == "policy.changed"]
    assert len(changed) == 1, (
        f"expected exactly one policy.changed across two independent writer instances, got {len(changed)}"
    )


def test_FR_HIL_07_two_parts_with_identical_content_but_different_ids_are_both_written(client, store, writer):
    """issue #46, S0's decision point 1: dedupe the queue on id, never on content. Two logically
    distinct events -- built here at the exact same frozen instant (the same literal `ts`/`at`),
    with otherwise byte-identical content -- must land as two separate committed events when they
    carry two different ids; a content-keyed dedupe (round 7's `_content_key`, the very thing #46
    replaces) would have wrongly collapsed these into one. The flip side is pinned in the same
    test: resending the *same* id with identical content is the idempotent no-op the harness
    writer (#46 item 2) defines, and the same id with genuinely different content is a real
    conflict (EventRejected), not a silent overwrite."""
    frozen_at = "2026-09-29T09:30:00.000Z"
    part_a = {
        "id": ulid(700_000_001),
        "type": "policy.changed",
        "actor": OWNER,
        "target": "pol_x",
        "level": None,
        "district": None,
        "item": None,
        "severity": "info",
        "credits": 0,
        "summary": "identical content",
        "cause": None,
        "vis": "all",
        "authz": {"by": "person", "ref": OWNER, "at": frozen_at},
        "data": {"policy_id": "pol_x", "change": "stop_all", "level": "L1"},
        "ts": frozen_at,
    }
    part_b = dict(part_a, id=ulid(700_000_002))  # only the id differs -- content is otherwise identical

    event_a = writer.append(WORLD, part_a)
    event_b = writer.append(WORLD, part_b)

    assert event_a["id"] == part_a["id"]
    assert event_b["id"] == part_b["id"]
    assert event_a["id"] != event_b["id"]
    assert event_a["seq"] != event_b["seq"], "two distinct ids must never collapse onto one committed event"
    landed = store.events[WORLD]
    assert len(landed) == 2
    assert {e["id"] for e in landed} == {part_a["id"], part_b["id"]}

    # Resending part_a's exact id and content again must be an idempotent no-op, not a third event.
    replay = writer.append(WORLD, dict(part_a))
    assert replay == event_a
    assert len(store.events[WORLD]) == 2, "resending the same id with identical content must not append a third event"

    # The same id with genuinely different content is a real conflict, per #46 item 2.
    conflicting = dict(part_a, summary="different content, same id")
    with pytest.raises(EventRejected):
        writer.append(WORLD, conflicting)
    assert len(store.events[WORLD]) == 2, "a rejected conflicting resend must not be appended either"


def test_FR_HIL_07_a_healthy_350ms_writer_drains_ten_parts_within_the_calls_budget(client, store):
    """issue #46 item 1's own budget note ("read the part deadline from config... small enough
    that even a full Stop-all's worth of missed deadlines cannot blow the 5s budget") cuts the
    other way too: a writer that is merely slow, not hung -- 350ms is comfortably realistic
    harness latency, not a hang -- must not be mistaken for one. A default deadline tuned too
    tight against real latency would queue every part pending even though the harness was healthy
    the whole time. Ten parts at 350ms each (3.5s serial) must all land as real, committed events,
    with nothing left pending, inside the shared 5s call budget."""
    ids = _world_with_policies(store, 10, level="L2")
    slow = SlowEventWriter(store, delay_s=0.35)
    as_writer(slow)
    as_principal(make_principal(user_id=OWNER, role="owner", world_id=WORLD))

    started = time.monotonic()
    resp = client.post(f"/worlds/{WORLD}/autopilot/stop")
    elapsed = time.monotonic() - started

    assert resp.status_code == 200, resp.text  # never 202: a healthy-but-slow writer must not end up pending
    assert elapsed <= 5.0, f"stop-all took {elapsed:.2f}s draining 10 healthy-but-350ms-slow parts"
    body = resp.json()
    assert body["stopped"] == len(ids)
    assert body["pending"] == 0, "a merely-slow (not hung) writer must not be treated as missing its deadline"
    for pid in ids:
        assert store.policies[pid]["level"] == "L1"
    changed = [e for e in store.events.get(WORLD, []) if e["type"] == "policy.changed"]
    assert len(changed) == len(ids)


def test_FR_HIL_07_part_write_deadline_is_read_from_config_not_a_module_constant(client, store):
    """issue #46 item 1: "Read the part deadline from config, not a constant tuned to the tests"
    -- API_ST3a.md's #46 update adds `deps.get_part_write_deadline_s()`, resolved the same
    injectable way as get_store/get_event_writer/get_current_principal, precisely so this is
    provable: overriding it to a value shorter than a writer's own real latency must make that
    latency look like a miss (queued pending); overriding it to a value comfortably longer must
    let the very same writer land directly on a retry. A hardcoded module constant could not
    respond to either override."""
    _world_with_policies(store, 1, level="L2")
    slow = SlowEventWriter(store, delay_s=0.2)
    as_writer(slow)
    as_principal(make_principal(user_id=OWNER, role="owner", world_id=WORLD))

    as_part_write_deadline(0.02)  # far shorter than the writer's own 0.2s latency
    resp_short = client.post(f"/worlds/{WORLD}/autopilot/stop")
    assert resp_short.status_code == 202, resp_short.text
    assert resp_short.json()["pending"] == 1, "a deadline shorter than the writer's own latency must miss it"

    as_part_write_deadline(2.0)  # comfortably longer than the same writer's 0.2s latency
    resp_long = client.post(f"/worlds/{WORLD}/autopilot/stop")  # flushes the now-pending part
    assert resp_long.status_code == 200, resp_long.text
    assert resp_long.json()["pending"] == 0, (
        "the exact same writer, given a longer config-supplied deadline, must land within it -- "
        "proving the deadline is read fresh, not captured once from a module constant"
    )


def test_FR_HIL_07_pause_flag_is_never_set_without_its_event_queued_even_with_corrupted_pending(client, store, writer):
    """PRD 9.4 honesty (nothing animates without a recorded event) applied to the durable
    WorldRecord.paused flag itself, not just the world.paused animation: `paused` must only ever
    read True together with a world.paused event existing somewhere in the store (pending or
    committed) -- never before it is queued, and never as a side effect of a request that
    otherwise fails. A corrupted store.pending_events[world_id] (here: None instead of a list --
    the same "some other write left this in a bad shape" scenario the round-5/6 malformed-scope
    tests already cover for policy history) must be treated exactly like any other malformed
    stored value in this ticket: never allowed to raise past the route (never a 500), and never
    allowed to leave `paused` flipped True with no world.paused event anywhere."""
    store.worlds[WORLD] = make_world(owner=OWNER)
    store.pending_events[WORLD] = None  # corrupted: a real list is always expected here
    as_principal(make_principal(user_id=OWNER, role="owner", world_id=WORLD))

    resp = client.post(f"/worlds/{WORLD}/pause", json={"channel": "web"})

    assert resp.status_code in (200, 202), resp.text  # never a bare exception or 500
    paused_flag = store.worlds[WORLD].paused
    pending = store.pending_events.get(WORLD)
    pending_list = pending if isinstance(pending, list) else []
    committed = store.events.get(WORLD, [])
    has_paused_event = any(p.get("type") == "world.paused" for p in pending_list) or any(
        e["type"] == "world.paused" for e in committed
    )
    assert paused_flag == has_paused_event, (
        f"paused={paused_flag} but a world.paused event "
        f"{'exists' if has_paused_event else 'does not exist'} anywhere in the store -- the flag "
        "must only ever be true together with its own queued event"
    )
    if paused_flag:
        assert resp.json()["paused"] is True


def test_FR_HIL_07_a_fast_failing_append_is_retried_within_budget_and_still_lands_before_policy_changed(client, store):
    """A raising `append` that fails *fast* (no hang, no timeout -- an immediate rejection) with
    ample call budget left must be retried within the same call, not parked pending the instant it
    fails once: FlakyEventWriter here raises on its very first call only, then succeeds. Since
    world.paused is enqueued ahead of every policy.changed this same Pause-all call builds
    (ST-3a-3, still pinned), that first call is world.paused's own attempt -- this also proves
    world.paused still lands *before* every policy.changed even after its own first attempt failed
    fast and had to be retried."""
    ids = _world_with_policies(store, 3, level="L2")
    flaky = FlakyEventWriter(store, failing=False, fail_first_n=1)
    as_writer(flaky)
    as_principal(make_principal(user_id=OWNER, role="owner", world_id=WORLD))

    resp = client.post(f"/worlds/{WORLD}/pause", json={"channel": "web"})

    assert resp.status_code == 200, resp.text  # never 202: a fast failure with budget left is retried, not parked
    body = resp.json()
    assert body["paused"] is True
    assert body["pending"] == 0

    events = store.events[WORLD]
    types = [e["type"] for e in events]
    assert types.count("world.paused") == 1
    assert types.count("policy.changed") == len(ids)
    assert types.index("world.paused") == 0, (
        "world.paused must still land first even though its own first attempt failed fast and had to be retried"
    )
