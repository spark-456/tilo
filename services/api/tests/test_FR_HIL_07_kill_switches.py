"""FR-HIL-07 (PRD 10.4, 10.6): "Kill switches from app and WhatsApp: STOP AUTOPILOT sets all
policies to L1 in <= 5 s; confirmed on every channel." PI-13 and PI-18
(docs/security/p4-policy-invariants.md): Stop all autopilot sets every policy to L1, one
`policy.changed` per policy, only the owner may do it, and one writer per world stamps every
event -- tilo-api itself never does. Routes and shapes pinned in
services/api/tests/API_ST3a.md (round 2, after code/security/qa review round 1 failed on: an
invented run_id and an O(n^2) seq scan, a 403/404 membership oracle, half-applied Stop-alls on
malformed policies, an unvalidated pause channel, and policy.changed always broadcast vis: "all").
"""

from __future__ import annotations

import pathlib
import time

from _api_lib import (
    OWNER,
    WORLD,
    as_principal,
    assert_part_carries_no_stamped_fields,
    base_policy,
    make_district,
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
_HISTORY_SHAPES = st.sampled_from(["normal", "missing", "not_a_list", "empty_list"])


@st.composite
def _kill_switch_case(draw):
    n = draw(st.integers(min_value=1, max_value=5))
    levels = draw(st.lists(_LEVELS, min_size=n, max_size=n))
    history_shapes = draw(st.lists(_HISTORY_SHAPES, min_size=n, max_size=n))
    mapped = draw(st.lists(st.booleans(), min_size=n, max_size=n))
    return list(zip(levels, history_shapes, mapped))


@settings(max_examples=25, deadline=None, suppress_health_check=[HealthCheck.function_scoped_fixture])
@given(case=_kill_switch_case())
def test_FR_HIL_07_PI_13_stop_all_never_half_applies_property(client, store, writer, case):
    """Property: whatever mix of well-formed, malformed and unmapped policies an owner has,
    Stop-all never raises, every one of them not already at L0 ends at L1 with exactly one new
    policy.changed each, and the response's stopped/already_l1 counts match -- no partial
    application, whatever order the store's dict iterates in."""
    store.worlds.clear()
    store.policies.clear()
    store.policy_worlds.clear()
    store.events.clear()
    store.worlds[WORLD] = make_world(owner=OWNER)

    pids: list[str] = []
    expected_stopped = 0
    expected_already_l1 = 0
    for i, (level, hist_shape, mapped) in enumerate(case):
        pid = f"pol_case_{i}"
        pids.append(pid)
        policy = base_policy(id_=pid, owner=OWNER, level="L2")
        policy["level"] = level
        if hist_shape == "missing":
            del policy["history"]
        elif hist_shape == "not_a_list":
            policy["history"] = "oops"
        elif hist_shape == "empty_list":
            policy["history"] = []
        store.policies[pid] = policy
        if mapped:
            store.policy_worlds[pid] = WORLD
        if level == "L0":
            pass
        elif level == "L1":
            expected_already_l1 += 1
        else:
            expected_stopped += 1

    as_principal(make_principal(user_id=OWNER, role="owner", world_id=WORLD))
    resp = client.post(f"/worlds/{WORLD}/autopilot/stop")

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["stopped"] == expected_stopped
    assert body["already_l1"] == expected_already_l1

    expected_changed_ids = set()
    for pid, (level, _, _) in zip(pids, case):
        if level == "L0":
            assert store.policies[pid]["level"] == "L0"
        else:
            assert store.policies[pid]["level"] == "L1"
            assert isinstance(store.policies[pid]["history"], list)
            assert store.policies[pid]["history"][-1]["level"] == "L1"
            if level != "L1":
                expected_changed_ids.add(pid)

    changed_ids = {e["data"]["policy_id"] for e in store.events.get(WORLD, []) if e["type"] == "policy.changed"}
    assert changed_ids == expected_changed_ids


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
