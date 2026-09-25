"""FR-HIL-07 (PRD 10.4, 10.6): "Kill switches from app and WhatsApp: STOP AUTOPILOT sets all
policies to L1 in <= 5 s; confirmed on every channel." PI-13 (docs/security/p4-policy-invariants.md):
Stop all autopilot sets every policy to L1, one `policy.changed` per policy, and only the owner
may do it. Routes and shapes pinned in services/api/tests/API_ST3a.md.
"""

from __future__ import annotations

import pathlib
import time

from _api_lib import OWNER, WORLD, as_principal, base_policy, make_principal, make_world, validate_event

OTHER_OWNER = "u_other_owner"


def _world_with_policies(store, n: int, *, owner: str = OWNER, level: str = "L2") -> list[str]:
    store.worlds[WORLD] = make_world(owner=owner)
    ids = []
    for i in range(n):
        pid = f"pol_test_{i}"
        store.policies[pid] = base_policy(id_=pid, owner=owner, level=level, action_type="send_email")
        store.policy_worlds[pid] = WORLD
        ids.append(pid)
    return ids


def test_FR_HIL_07_stop_all_sets_every_policy_to_L1(client, store):
    ids = _world_with_policies(store, 5, level="L2")
    as_principal(make_principal(user_id=OWNER, role="owner"))

    resp = client.post(f"/worlds/{WORLD}/autopilot/stop")

    assert resp.status_code == 200
    for pid in ids:
        assert store.policies[pid]["level"] == "L1"
        assert store.policies[pid]["history"][-1]["level"] == "L1"
        assert store.policies[pid]["history"][-1]["by"] == OWNER
        assert store.policies[pid]["history"][-1]["change"] == "stop_all"


def test_FR_HIL_07_PI_13_stop_all_emits_one_policy_changed_per_policy(client, store):
    ids = _world_with_policies(store, 3, level="L3")
    as_principal(make_principal(user_id=OWNER, role="owner"))

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


def test_FR_HIL_07_stop_all_is_idempotent_no_duplicate_l1_entries(client, store):
    ids = _world_with_policies(store, 4, level="L2")
    as_principal(make_principal(user_id=OWNER, role="owner"))

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
    as_principal(make_principal(user_id=OWNER, role="owner"))

    resp = client.post(f"/worlds/{WORLD}/autopilot/stop")

    assert resp.status_code == 200
    assert resp.json()["stopped"] == 0
    for pid in ids:
        assert store.policies[pid]["level"] == "L0"
        assert len(store.policies[pid]["history"]) == before[pid]
    assert not [e for e in store.events.get(WORLD, []) if e["type"] == "policy.changed"]


def test_FR_HIL_07_stop_all_confirms_on_every_enabled_channel(client, store):
    store.worlds[WORLD] = make_world(owner=OWNER, owner_channels=("web", "whatsapp", "email"))
    as_principal(make_principal(user_id=OWNER, role="owner"))

    resp = client.post(f"/worlds/{WORLD}/autopilot/stop")

    assert resp.status_code == 200
    body = resp.json()
    channels = {c["channel"] for c in body["confirmations"]}
    assert channels == {"web", "whatsapp", "email"}


def test_FR_HIL_07_stop_all_completes_within_5s_for_200_policies(client, store):
    _world_with_policies(store, 200, level="L3")
    as_principal(make_principal(user_id=OWNER, role="owner"))

    started = time.monotonic()
    resp = client.post(f"/worlds/{WORLD}/autopilot/stop")
    elapsed = time.monotonic() - started

    assert resp.status_code == 200
    assert resp.json()["stopped"] == 200
    assert elapsed <= 5.0, f"stop-all took {elapsed:.2f}s for 200 policies, must be <= 5s"


def test_FR_HIL_07_stop_all_forbidden_for_non_owner(client, store):
    _world_with_policies(store, 2, level="L2")

    for role, user in (("team_lead", "u_finance_lead"), ("approver", "u_approver"), ("viewer", "u_viewer")):
        as_principal(make_principal(user_id=user, role=role))
        resp = client.post(f"/worlds/{WORLD}/autopilot/stop")
        assert resp.status_code == 403, f"role={role} must not be able to stop autopilot"

    # The owner of a *different* world is not this world's owner either.
    as_principal(make_principal(user_id=OTHER_OWNER, role="owner"))
    resp = client.post(f"/worlds/{WORLD}/autopilot/stop")
    assert resp.status_code == 403

    # Nothing changed.
    for pid, policy in store.policies.items():
        assert policy["level"] == "L2"
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
    as_principal(make_principal(user_id=OWNER, role="owner"))

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
    as_principal(make_principal(user_id=OWNER, role="owner"))

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


def test_FR_HIL_07_revoke_appends_l1_and_emits_policy_changed(client, store):
    store.worlds[WORLD] = make_world(owner=OWNER)
    store.policies["pol_autopilot_l2"] = base_policy(id_="pol_autopilot_l2", owner=OWNER, level="L2")
    store.policy_worlds["pol_autopilot_l2"] = WORLD
    as_principal(make_principal(user_id=OWNER, role="owner"))

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


def test_FR_HIL_07_revoke_forbidden_for_non_owner_and_nothing_changes(client, store):
    store.worlds[WORLD] = make_world(owner=OWNER)
    store.policies["pol_autopilot_l2"] = base_policy(id_="pol_autopilot_l2", owner=OWNER, level="L2")
    store.policy_worlds["pol_autopilot_l2"] = WORLD

    for role, user in (("team_lead", "u_finance_lead"), ("approver", "u_approver"), ("viewer", "u_viewer")):
        as_principal(make_principal(user_id=user, role=role))
        resp = client.post("/policies/pol_autopilot_l2/revoke")
        assert resp.status_code == 403, f"role={role} (PRD 10.1: Team Lead proposes only) must not revoke"

    assert store.policies["pol_autopilot_l2"]["level"] == "L2"
    assert store.events.get(WORLD, []) == []
