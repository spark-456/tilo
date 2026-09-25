"""FR-HIL-07 (PRD 10.4, 10.6): "Kill switches from app and WhatsApp: STOP AUTOPILOT sets all
policies to L1 in <= 5 s; confirmed on every channel." PI-13 and PI-18
(docs/security/p4-policy-invariants.md): Stop all autopilot sets every policy to L1, one
`policy.changed` per policy, only the owner may do it, and one writer per world stamps every
event -- tilo-api itself never does. Routes and shapes pinned in
services/api/tests/API_ST3a.md (round 4, after code/security/qa review round 3 failed on: Pause's
dedupe keyed on "did this call lower any policy" instead of a durable `paused` flag, a
process-wide lock held across writer I/O so a slow/failing writer for one world stalled a kill
switch against a different world, policy.changed's vis computed against the Stop-all *request*
world instead of the policy's own *target* world, a redacted view still leaking a caller's own
visibility scope through `vis`/`target`/`actor` and through nested `data` values, `pending` only
ever counting the request's own world, and revoke raising a 500 on a down writer instead of
queuing pending like stop/pause do). Round 1-3's own fixes (run_id/seq stamping, the 403/404
membership oracle, half-applied Stop-alls, the pause channel enum, per-scope vis, no silent
history repair, and pending-on-failure for stop/pause) are unchanged here and still pinned below.
"""

from __future__ import annotations

import json
import pathlib
import threading
import time

from _api_lib import (
    OWNER,
    PRINCIPAL_HEADER,
    WORLD,
    BlockingEventWriter,
    FlakyEventWriter,
    LateSuccessEventWriter,
    ReversedDelayEventWriter,
    SlowEventWriter,
    SlowFlakyEventWriter,
    SlowHistoryPolicy,
    as_principal,
    as_principal_by_header,
    as_writer,
    assert_part_carries_no_stamped_fields,
    base_policy,
    make_district,
    make_pending_part,
    make_principal,
    make_world,
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
    as_principal(make_principal(user_id=OWNER, role="owner", world_id=WORLD))

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


def test_FR_HIL_07_pause_writes_policy_changed_before_world_paused_in_the_same_call(client, store):
    """Within one Pause-all call, every policy.changed part it builds must land in store.events
    before that same call's own world.paused part, never interleaved out of order by which
    underlying writer call happens to finish first on the wire (round-5 finding 3)."""
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
    assert paused_index == len(types_in_order) - 1, (
        f"world.paused landed at index {paused_index} of {types_in_order} -- every policy.changed "
        "must land before it, never interleaved by completion timing"
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
    earlier (failed) Pause-all already built and left pending."""
    return {
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
    store.worlds[WORLD] = make_world(owner=OWNER)
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
    store.worlds[WORLD] = make_world(owner=OWNER, paused=True)  # the earlier call already flipped this
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
    store.worlds[WORLD] = make_world(owner=OWNER, paused=True)
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
    assert len(still_pending) == 1, (
        "a part already sitting in store.pending_events before this call must be put back if "
        f"anything raises inside the locked block, never lost -- got {len(still_pending)} parts pending"
    )
    assert still_pending[0]["type"] == "world.paused"


def test_FR_HIL_07_malformed_scope_revoke_never_500s_and_reaches_l1(client, store, writer):
    store.worlds[WORLD] = make_world(owner=OWNER)
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
