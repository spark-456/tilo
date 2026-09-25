"""FR-HIL-06 / PI-11 (docs/security/p4-policy-invariants.md): "L2 and L3 policies have a daily
cap (limits.per_day); the engine opens a send only while that day's actions under the policy,
this one included, stay within per_day and their credits within limits.credits, otherwise the
send waits at a gate." No crossref case exists yet for this rule (outbox.rules.md / PI-11 note:
"the P4 ticket adds oc/invalid/ob01_policy_daily_limit_reached and a credits twin") — these
cases are built inline here, derived from the L3 status-update policy in
contracts/fixtures/outbox/crossref/valid/policy_l3_status_update_waiting.json (per_day=5,
credits=null), the same shape conftest.py's applied_entry() factory follows.
"""

from __future__ import annotations

import tilo_policy
from _policy_lib import OWNER, WORLD, applied_entry, base_facts, base_instruction, base_policy

NOW = "2026-09-29T10:20:00.000Z"
POLICY_ID = "pol_status_updates"


def _table(risk_table_path):
    return tilo_policy.load_risk_table(risk_table_path)


def _proposal(credits=1):
    return tilo_policy.Proposal(
        world_id=WORLD,
        action_type="post_status_update",
        connector="gmail",
        district="D1",
        destination=None,
        facts=tilo_policy.SideEffectFacts(
            **base_facts(recipients=("teammate@example.org",), known_recipients=("teammate@example.org",))
        ),
        item={"artifact_id": "art_status_update", "version": 1},
        credits=credits,
        instruction=None,
    )


def _l3_policy(**overrides):
    kwargs = dict(
        id_=POLICY_ID,
        action_type="post_status_update",
        level="L3",
        connectors=("gmail",),
        recipients=("teammate@example.org",),
        domains=(),
        districts=(),
        per_day=5,
        credits=None,
        history=[{"by": OWNER, "at": "2026-09-29T09:30:00.000Z", "change": "Created at L3", "level": "L3"}],
    )
    kwargs.update(overrides)
    return base_policy(**kwargs)


def _earlier_today(count, *, credits=0):
    return [applied_entry(policy_id=POLICY_ID, at=f"2026-09-29T10:0{i}:00.000Z", credits=credits) for i in range(count)]


def test_FR_HIL_06_PI_11_within_daily_limit_runs(risk_table_path):
    table = _table(risk_table_path)
    policy = _l3_policy()
    decision = tilo_policy.decide(
        _proposal(), table=table, policies=[policy], world_owner=OWNER, applied=_earlier_today(4), now=NOW
    )
    assert decision.outcome == "run"


def test_FR_HIL_06_PI_11_per_day_reached_gates(risk_table_path):
    """5 actions already ran today under a per_day=5 policy; the 6th (this one included in the
    count, per PI-11) waits at a gate."""
    table = _table(risk_table_path)
    policy = _l3_policy()
    decision = tilo_policy.decide(
        _proposal(), table=table, policies=[policy], world_owner=OWNER, applied=_earlier_today(5), now=NOW
    )
    assert decision.outcome == "gate"


def test_FR_HIL_06_PI_11_per_day_only_counts_the_same_policy(risk_table_path):
    """Actions logged under a different policy_id do not count against this policy's cap."""
    table = _table(risk_table_path)
    policy = _l3_policy()
    other_policy_entries = [applied_entry(policy_id="pol_unrelated", at="2026-09-29T10:00:00.000Z") for _ in range(10)]
    decision = tilo_policy.decide(
        _proposal(), table=table, policies=[policy], world_owner=OWNER, applied=other_policy_entries, now=NOW
    )
    assert decision.outcome == "run"


def test_FR_HIL_06_PI_11_per_day_only_counts_the_same_calendar_day(risk_table_path):
    """5 actions ran yesterday under the same policy; today's count is still 0, so this send
    runs (per_day=5 not yet reached today)."""
    table = _table(risk_table_path)
    policy = _l3_policy()
    yesterday = [applied_entry(policy_id=POLICY_ID, at=f"2026-09-28T10:0{i}:00.000Z") for i in range(5)]
    decision = tilo_policy.decide(
        _proposal(), table=table, policies=[policy], world_owner=OWNER, applied=yesterday, now=NOW
    )
    assert decision.outcome == "run"


def test_FR_HIL_06_PI_11_credits_within_limit_runs(risk_table_path):
    table = _table(risk_table_path)
    policy = _l3_policy(per_day=None, credits=100)
    decision = tilo_policy.decide(
        _proposal(credits=20),
        table=table,
        policies=[policy],
        world_owner=OWNER,
        applied=_earlier_today(3, credits=20),
        now=NOW,
    )
    assert decision.outcome == "run"


def test_FR_HIL_06_PI_11_credits_exceeded_gates(risk_table_path):
    """limits.credits=100; 4 earlier sends at 20 credits (80) plus this 25-credit send (105)
    goes over, so it waits at a gate — the credits twin of the daily-limit case."""
    table = _table(risk_table_path)
    policy = _l3_policy(per_day=None, credits=100)
    decision = tilo_policy.decide(
        _proposal(credits=25),
        table=table,
        policies=[policy],
        world_owner=OWNER,
        applied=_earlier_today(4, credits=20),
        now=NOW,
    )
    assert decision.outcome == "gate"


def test_FR_HIL_06_PI_11_l3_policy_without_a_daily_limit_covers_nothing(risk_table_path):
    """policy.schema.json requires per_day at L2 and L3 (fixture policy/invalid/l3_without_daily_limit):
    a record without one is invalid, so it covers nothing and the send waits at a gate."""
    table = _table(risk_table_path)
    policy = _l3_policy(per_day=None, credits=None)
    decision = tilo_policy.decide(
        _proposal(), table=table, policies=[policy], world_owner=OWNER, applied=_earlier_today(500), now=NOW
    )
    assert decision.outcome == "gate"


def test_FR_HIL_06_PI_11_l2_policy_also_has_a_daily_cap(risk_table_path):
    """PI-11 applies to L2 as well as L3. An L2 policy at its per_day limit gates even with a
    valid, unused instruction."""
    table = _table(risk_table_path)
    instruction = base_instruction(destination="thread-status-1")
    policy = base_policy(
        id_="pol_l2_status",
        action_type="post_status_update",
        level="L2",
        connectors=("gmail",),
        recipients=("teammate@example.org",),
        domains=("example.org",),
        per_day=2,
        credits=None,
    )
    proposal = tilo_policy.Proposal(
        world_id=WORLD,
        action_type="post_status_update",
        connector="gmail",
        district="D1",
        destination="thread-status-1",
        facts=tilo_policy.SideEffectFacts(
            **base_facts(recipients=("teammate@example.org",), known_recipients=("teammate@example.org",))
        ),
        item={"artifact_id": "art_status_update", "version": 1},
        credits=1,
        instruction=instruction,
    )
    earlier = [
        applied_entry(policy_id="pol_l2_status", at="2026-09-29T10:00:00.000Z", instruction_id="01J_used_1"),
        applied_entry(policy_id="pol_l2_status", at="2026-09-29T10:05:00.000Z", instruction_id="01J_used_2"),
    ]
    decision = tilo_policy.decide(proposal, table=table, policies=[policy], world_owner=OWNER, applied=earlier, now=NOW)
    assert decision.outcome == "gate"
