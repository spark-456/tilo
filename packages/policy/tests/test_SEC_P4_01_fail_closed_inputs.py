"""P4-01 review round 1 (security, qa): malformed input must never widen authority.

The engine reads policies, events, facts and crossref cases that other services wrote. A record
that breaks its contract (contracts/*.schema.json) covers nothing, an event part that breaks its
schema opens nothing, and an entry the engine cannot fully check is rejected (PRD 10.4 "the
engine is deterministic code", docs/security/p4-policy-invariants.md PI-06, PI-07, PI-11, PI-16,
SEC-06). Each case below was a probe that returned "run" or a valid verdict in review round 1 or 2.
"""

from __future__ import annotations

import copy
import itertools
import json
import pathlib
import time
from datetime import UTC, datetime, timedelta

import pytest
import tilo_policy
from _policy_lib import OWNER, WORLD, applied_entry, base_facts, base_instruction, base_policy

NOW = "2026-09-29T10:20:00.000Z"
ARABIC_INDIC = str.maketrans("0123456789", "٠١٢٣٤٥٦٧٨٩")
FULLWIDTH = str.maketrans("0123456789", "０１２３４５６７８９")
RUNS = ("run", "run_after_undo")
INVALID_POLICIES = sorted(
    (pathlib.Path(__file__).resolve().parents[3] / "contracts/fixtures/policy/invalid").glob("*.json")
)


def _table(risk_table_path):
    return tilo_policy.load_risk_table(risk_table_path)


def _status_proposal(recipients=("teammate@example.org",), **facts):
    return tilo_policy.Proposal(
        world_id=WORLD,
        action_type="post_status_update",
        connector="gmail",
        district="D1",
        destination=None,
        facts=tilo_policy.SideEffectFacts(**base_facts(recipients=recipients, known_recipients=recipients, **facts)),
        item={"artifact_id": "art_status_update", "version": 1},
        credits=0,
        instruction=None,
    )


def _l3(**overrides):
    args = {
        "id_": "pol_status",
        "action_type": "post_status_update",
        "level": "L3",
        "recipients": ("teammate@example.org",),
        "domains": (),
        "per_day": 5,
        "credits": None,
        "history": [{"by": OWNER, "at": "2026-09-29T09:30:00.000Z", "change": "Created", "level": "L3"}],
    }
    args.update(overrides)
    return base_policy(**args)


def _decide(table, proposal, policies, applied=(), now=NOW):
    return tilo_policy.decide(
        proposal, table=table, policies=policies, world_owner=OWNER, applied=list(applied), now=now
    )


def test_FR_HIL_06_PI_11_sanity_the_l3_baseline_runs(risk_table_path):
    """The baseline every case below breaks one thing of: without the break it runs."""
    assert _decide(_table(risk_table_path), _status_proposal(), [_l3()]).outcome == "run"


# --- policy records that break policy.schema.json cover nothing (PI-06) -----------------------


def _ts_plus(ts: str, seconds: int) -> str:
    dt = datetime.strptime(ts, "%Y-%m-%dT%H:%M:%S.%fZ").replace(tzinfo=UTC) + timedelta(seconds=seconds)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def _first(value, default):
    return value[0] if isinstance(value, list) and value and isinstance(value[0], str) else default


def _proposal_for(policy: dict, now: str) -> tilo_policy.Proposal:
    """A proposal the policy would cover if it were valid: its action type, first connector,
    district, recipient or domain; an owner's web instruction for L2."""
    scope = policy.get("scope") if isinstance(policy.get("scope"), dict) else {}
    domain = _first(scope.get("domains"), "example.com")
    recipient = _first(scope.get("recipients"), f"riya@{domain}")
    destination = "thread-regression-1"
    instruction = base_instruction(
        type_="world.requested", channel="web", ts=_ts_plus(now, -10), destination=destination
    )
    return tilo_policy.Proposal(
        world_id=WORLD,
        action_type=policy.get("action_type", "send_email"),
        connector=_first(scope.get("connectors"), "gmail"),
        district=_first(scope.get("districts"), "D1"),
        destination=destination,
        facts=tilo_policy.SideEffectFacts(**base_facts(recipients=(recipient,), known_recipients=(recipient,))),
        item={"artifact_id": "art_regression", "version": 1},
        credits=0,
        instruction=instruction,
    )


def _now_after(policy: dict) -> str:
    stamps = [policy.get("created_by") or {}, *(policy.get("history") or [])]
    ats = [s.get("at") for s in stamps if isinstance(s, dict) and isinstance(s.get("at"), str)]
    return _ts_plus(max(ats), 60) if ats else NOW


def _fixtures(repo_root, kind):
    return sorted((repo_root / "contracts" / "fixtures" / "policy" / kind).glob("*.json"))


def test_FR_HIL_03_PI_06_valid_l2_l3_policy_fixtures_run_for_their_own_proposal(repo_root, risk_table_path):
    """Keeps the invalid-fixture test below from passing vacuously: the same derivation runs
    for every valid L2/L3 fixture."""
    table = _table(risk_table_path)
    checked = 0
    for path in _fixtures(repo_root, "valid"):
        policy = json.loads(path.read_text(encoding="utf-8"))
        if policy["level"] not in ("L2", "L3"):
            continue
        now = _now_after(policy)
        decision = _decide(table, _proposal_for(policy, now), [policy], now=now)
        assert decision.outcome in RUNS, (path.name, decision)
        checked += 1
    assert checked >= 2


@pytest.mark.parametrize("path", INVALID_POLICIES, ids=[p.stem for p in INVALID_POLICIES])
def test_FR_HIL_03_PI_06_invalid_policy_fixture_covers_nothing(path, risk_table_path):
    policy = json.loads(path.read_text(encoding="utf-8"))
    now = _now_after(policy)
    decision = _decide(_table(risk_table_path), _proposal_for(policy, now), [policy], now=now)
    assert decision.outcome not in RUNS, decision
    assert decision.authz is None


@pytest.mark.parametrize("field", ["connectors", "recipients", "domains", "districts"])
def test_FR_HIL_03_PI_06_scope_given_as_a_string_covers_nothing(field, risk_table_path):
    policy = _l3()
    policy["scope"][field] = {
        "connectors": "gmail_admin",
        "recipients": "xteammate@example.org",
        "domains": "example.org",
        "districts": "D1D2",
    }[field]
    assert _decide(_table(risk_table_path), _status_proposal(), [policy]).outcome == "gate"


def test_FR_HIL_06_PI_11_nan_credit_limit_covers_nothing(risk_table_path):
    policy = _l3(credits=float("nan"))
    proposal = _status_proposal()
    assert _decide(_table(risk_table_path), proposal, [policy]).outcome == "gate"


# --- timestamps: ASCII digits only (common.schema.json timestamp) -----------------------------


def test_FR_HIL_03_PI_06_expired_policy_in_non_ascii_digits_is_not_live(risk_table_path):
    policy = _l3(expiry="2026-09-29T10:00:00.000Z".translate(ARABIC_INDIC))
    assert _decide(_table(risk_table_path), _status_proposal(), [policy]).outcome == "gate"


@pytest.mark.parametrize("digits", [ARABIC_INDIC, FULLWIDTH])
def test_FR_HIL_06_PI_11_non_ascii_now_never_skips_the_daily_cap(digits, risk_table_path):
    policy = _l3(per_day=1)
    earlier = [applied_entry(policy_id="pol_status", at="2026-09-29T10:00:00.000Z")]
    decision = _decide(_table(risk_table_path), _status_proposal(), [policy], earlier, now=NOW.translate(digits))
    assert decision.outcome == "gate"


def test_FR_HIL_06_PI_11_non_ascii_applied_timestamp_never_skips_the_daily_cap(risk_table_path):
    policy = _l3(per_day=1)
    earlier = [applied_entry(policy_id="pol_status", at="2026-09-29T10:00:00.000Z".translate(ARABIC_INDIC))]
    assert _decide(_table(risk_table_path), _status_proposal(), [policy], earlier).outcome == "gate"


# --- facts and recipients ---------------------------------------------------------------------


def test_FR_HIL_04_PI_07_attachments_none_is_not_no_attachments(risk_table_path):
    decision = _decide(_table(risk_table_path), _status_proposal(attachments=None), [_l3()])
    assert decision.outcome == "gate"


@pytest.mark.parametrize(
    "recipient", ["a@evil.com@example.org", "teammate@example.org.", "", "no-at-sign", "teammate@example.org\n"]
)
def test_FR_HIL_03_PI_06_malformed_recipient_is_never_in_scope(recipient, risk_table_path):
    policy = _l3(recipients=(), domains=("example.org",))
    decision = _decide(_table(risk_table_path), _status_proposal(recipients=(recipient,)), [policy])
    assert decision.outcome == "gate"


# --- gates: the tier and people the engine checks are the contract's (SEC-06, PI-02) ----------

GATE = {"gate_id": "G1", "card_id": "01JB5VQ0000000000000009001", "outbox_id": "01JB5VQ0000000000000009002"}


def _reserved(risk_tier):
    return {
        "type": "approval.requested",
        "authz": None,
        "data": {
            **GATE,
            "action_type": "send_email",
            "risk_tier": risk_tier,
            "irreversible": True,
            "item": {"artifact_id": "art_reply_draft", "version": 1},
            "approver": None,
            "team_lead": None,
        },
    }


def _resolved(*, ref=OWNER, channel="whatsapp", pin_verified=False):
    return {
        "type": "approval.resolved",
        "authz": {"by": "person", "ref": ref, "at": "2026-09-29T09:32:09.500Z"},
        "data": {**GATE, "option": "approve", "channel": channel, "pin_verified": pin_verified},
    }


@pytest.mark.parametrize("risk_tier", ["t3", " T3", "T3 ", "", None, "T4"])
def test_SEC_06_PI_02_unknown_gate_tier_never_skips_the_whatsapp_pin(risk_tier):
    decision = tilo_policy.open_gate(_reserved(risk_tier), _resolved(), world_owner=OWNER)
    assert decision.outcome == "gate"
    assert decision.authz is None


def test_FR_HIL_03_PI_02_missing_owner_and_ref_open_nothing():
    resolved = _resolved(ref=None, channel="web", pin_verified=True)
    decision = tilo_policy.open_gate(_reserved("T2"), resolved, world_owner=None)
    assert decision.outcome == "gate"


# --- check_entry on the policy path (PI-07, PI-11, PI-16) -------------------------------------


@pytest.fixture()
def l3_case(repo_root):
    path = repo_root / "contracts/fixtures/outbox/crossref/valid/policy_l3_status_update_waiting.json"
    return json.loads(path.read_text(encoding="utf-8"))


def test_FR_HIL_03_PI_06_sanity_the_l3_crossref_case_is_valid(l3_case):
    assert tilo_policy.check_entry(l3_case) is None


def test_FR_HIL_04_PI_07_policy_path_entry_at_t3_with_attachments_is_rejected(l3_case):
    case = copy.deepcopy(l3_case)
    case["entry"]["risk_tier"] = "T3"
    case["authorised_by"]["data"]["risk_tier"] = "T3"
    case["entry"]["modifiers"] = ["attachments"]
    case["entry"]["attachments"] = [{"artifact_id": "art_x", "version": 1}]
    assert tilo_policy.check_entry(case) is not None


@pytest.mark.parametrize("by,ref", [("person", OWNER), ("team_lead", "tl_ops")])
def test_FR_HIL_08_PI_16_policy_path_stamped_as_a_human_is_rejected(by, ref, l3_case):
    case = copy.deepcopy(l3_case)
    stamp = {"by": by, "ref": ref, "at": case["entry"]["authz"]["at"]}
    case["entry"]["authz"] = dict(stamp)
    case["authorised_by"]["authz"] = dict(stamp)
    assert tilo_policy.check_entry(case) is not None


def test_FR_HIL_06_PI_11_policy_path_over_its_daily_cap_is_rejected(l3_case):
    case = copy.deepcopy(l3_case)
    per_day = case["policy"]["limits"]["per_day"]
    authz = {**case["authorised_by"]["authz"], "at": _ts_plus(case["authorised_by"]["authz"]["at"], -60)}
    earlier = {"type": "policy.applied", "authz": authz, "data": case["authorised_by"]["data"]}
    case["earlier_applied"] = [copy.deepcopy(earlier) for _ in range(per_day)]
    assert tilo_policy.check_entry(case) is not None


# --- review round 2 --------------------------------------------------------------------------


@pytest.mark.parametrize("now", ["2026-19-39T10:20:00.000Z", "2026-09-29T25:20:00.000Z", "2026-02-30T10:20:00.000Z"])
def test_FR_HIL_06_PI_11_impossible_now_never_resets_the_daily_cap(now, risk_table_path):
    policy = _l3(per_day=1)
    earlier = [applied_entry(policy_id="pol_status", at="2026-09-29T10:00:00.000Z")]
    assert _decide(_table(risk_table_path), _status_proposal(), [policy], earlier, now=now).outcome == "gate"


def test_FR_HIL_04_PI_07_hand_built_table_with_an_unknown_level_never_runs(risk_table_path):
    """RiskTable is public: one built without load_risk_table is refused at construction or
    makes every decision gate. Only a policy at L2 ever yields run_after_undo."""
    good = _table(risk_table_path)
    try:
        bad = tilo_policy.RiskTable(
            actions=dict(good.actions),
            modifiers=tuple(good.modifiers),
            max_level={"T1": "L3", "T2": "L", "T3": "L1"},
        )
    except tilo_policy.PolicyConfigError:
        return
    proposal = tilo_policy.Proposal(
        world_id=WORLD,
        action_type="send_email",
        connector="gmail",
        district="D1",
        destination="thread-supplier-1",
        facts=tilo_policy.SideEffectFacts(**base_facts()),
        item={"artifact_id": "art_reply", "version": 1},
        credits=0,
        instruction=None,
    )
    decision = tilo_policy.decide(
        proposal, table=bad, policies=[base_policy(level="L2")], world_owner=OWNER, applied=[], now=NOW
    )
    assert decision.outcome == "gate"


def test_FR_HIL_03_PI_13_duplicate_policy_ids_fail_closed_whatever_the_order(risk_table_path):
    table = _table(risk_table_path)
    capped, loose = _l3(per_day=1), _l3(per_day=20)
    earlier = [applied_entry(policy_id="pol_status", at="2026-09-29T10:00:00.000Z")]
    for order in ([capped, loose], [loose, capped]):
        assert _decide(table, _status_proposal(), order, earlier).outcome == "gate"


def test_FR_HIL_03_decision_does_not_depend_on_the_order_of_policies(risk_table_path):
    table = _table(risk_table_path)
    policies = [
        _l3(id_="pol_a", per_day=5),
        _l3(id_="pol_b", per_day=1),
        _l3(
            id_="pol_c",
            level="L2",
            history=[{"by": OWNER, "at": "2026-09-29T09:30:00.000Z", "change": "c", "level": "L2"}],
        ),
    ]
    earlier = [applied_entry(policy_id="pol_b", at="2026-09-29T10:00:00.000Z")]
    decisions = [_decide(table, _status_proposal(), list(order), earlier) for order in itertools.permutations(policies)]
    assert all(d == decisions[0] for d in decisions)


def test_FR_HIL_03_PI_06_unicode_lookalike_domain_is_not_in_scope(risk_table_path):
    policy = _l3(recipients=(), domains=("kpmg.com",))
    decision = _decide(_table(risk_table_path), _status_proposal(recipients=("a@Kpmg.com",)), [policy])
    assert decision.outcome == "gate"


@pytest.mark.parametrize(
    "scope", [{"recipients": (), "domains": ("example.org",)}, {"recipients": ("teammate@example.org",), "domains": ()}]
)
def test_FR_HIL_03_PI_06_no_recipients_is_not_within_a_restricted_scope(scope, risk_table_path):
    """A policy that restricts recipients or domains covers only sends whose recipients it can
    check; a send with no recipients cannot show it stays in scope."""
    policy = _l3(**scope)
    assert _decide(_table(risk_table_path), _status_proposal(recipients=()), [policy]).outcome == "gate"


def test_FR_HIL_05_PI_12_check_entry_rejects_an_l2_entry_without_its_undo_wait(repo_root):
    path = repo_root / "contracts/fixtures/outbox/crossref/valid/policy_reply_waiting_out_undo_window.json"
    case = json.loads(path.read_text(encoding="utf-8"))
    assert tilo_policy.check_entry(case) is None
    case["entry"]["state"] = "queued"
    case["entry"]["scheduled_at"] = case["entry"]["created_at"]
    assert tilo_policy.check_entry(case) is not None


def test_FR_HIL_06_PI_11_decide_stays_fast_with_a_long_history(risk_table_path):
    """The owner's whole policy.applied history is passed every time (API.md): 5000 earlier
    parts, a handful of them today, decide in well under the 2 s budget."""
    table = _table(risk_table_path)
    older = [
        applied_entry(
            policy_id="pol_status", at=f"2026-08-{1 + i % 28:02d}T10:00:00.000Z", outbox_id=f"01JB5VQ{i:019d}"
        )
        for i in range(5000)
    ]
    start = time.perf_counter()
    decision = _decide(table, _status_proposal(), [_l3()], older)
    elapsed = time.perf_counter() - start
    assert decision.outcome == "run"
    assert elapsed < 2.0, f"decide took {elapsed:.2f} s with 5000 earlier parts"


# --- review round 3 --------------------------------------------------------------------------


@pytest.mark.parametrize("stopped_at", ["2026-09-29T10:20:00.500Z", "2026-09-30T10:20:00.000Z"])
def test_FR_HIL_07_PI_13_a_stop_dated_after_now_still_stops(stopped_at, risk_table_path):
    """decide is a live decision on the record as it is now: a Stop all (or revocation) already in
    the record gates, even when `now` is behind it (a retry, a replay, a skewed clock)."""
    history = [
        {"by": OWNER, "at": "2026-09-29T09:30:00.000Z", "change": "Created", "level": "L3"},
        {"by": OWNER, "at": stopped_at, "change": "stop_all", "level": "L1"},
    ]
    policy = _l3(level="L1", history=history)
    assert _decide(_table(risk_table_path), _status_proposal(), [policy]).outcome == "gate"


def test_FR_HIL_03_PI_06_a_stamp_dated_after_now_covers_nothing(risk_table_path):
    policy = _l3()
    policy["changed_by"] = {"by": OWNER, "at": "2026-09-29T11:00:00.000Z"}
    assert _decide(_table(risk_table_path), _status_proposal(), [policy]).outcome == "gate"


def test_FR_HIL_03_PI_13_duplicate_ids_gate_even_when_one_copy_does_not_cover(risk_table_path):
    table = _table(risk_table_path)
    wide = _l3()
    narrow = _l3(connectors=("slack",))
    broken = _l3()
    broken["limits"]["per_day"] = None
    for other in (narrow, broken):
        for order in ([wide, other], [other, wide]):
            assert _decide(table, _status_proposal(), order).outcome == "gate"


def test_FR_HIL_05_PI_08_an_instruction_older_than_the_l2_level_opens_nothing(risk_table_path):
    """Instruction is approval only while L2 is in force: an owner message sent before the policy
    reached L2 did not ask under that policy (PRD 10.4 L2)."""
    policy = base_policy(level="L2")  # created at L2 on 2026-09-29T09:30
    proposal = tilo_policy.Proposal(
        world_id=WORLD,
        action_type="send_email",
        connector="gmail",
        district="D1",
        destination="thread-supplier-1",
        facts=tilo_policy.SideEffectFacts(**base_facts()),
        item={"artifact_id": "art_reply", "version": 1},
        credits=0,
        instruction=base_instruction(ts="2026-08-01T09:00:00.000Z"),
    )
    decision = _decide(_table(risk_table_path), proposal, [policy])
    assert decision.outcome == "gate"


def test_FR_HIL_04_PI_07_check_entry_with_the_table_rejects_a_self_declared_lower_tier(l3_case, risk_table_path):
    """check_entry(case, table=...) re-assesses the tier: delete_file is T3 in the table, so an
    entry, policy.applied and policy that call it T2 are rejected (PI-07, PI-14)."""
    table = _table(risk_table_path)
    assert tilo_policy.check_entry(l3_case, table=table) is None
    case = copy.deepcopy(l3_case)
    case["entry"]["action_type"] = "delete_file"
    case["authorised_by"]["data"]["action_type"] = "delete_file"
    case["policy"]["action_type"] = "delete_file"
    assert tilo_policy.check_entry(case, table=table) is not None


# --- review round 4 --------------------------------------------------------------------------


def _l3_b():
    return _l3(id_="pol_b")


def test_FR_HIL_07_PI_13_a_revocation_after_now_gates_even_with_another_covering_policy(risk_table_path):
    """Any of the owner's policies for this action type stamped after `now` means the clock is
    behind the record: the whole decision gates, it never falls to the next policy."""
    history = [
        {"by": OWNER, "at": "2026-09-29T09:30:00.000Z", "change": "Created", "level": "L3"},
        {"by": OWNER, "at": "2026-09-29T10:20:00.500Z", "change": "revoked", "level": "L1"},
    ]
    revoked_a = _l3(id_="pol_a", level="L1", history=history)
    for order in ([revoked_a, _l3_b()], [_l3_b(), revoked_a]):
        assert _decide(_table(risk_table_path), _status_proposal(), order).outcome == "gate"


def test_FR_HIL_03_PI_13_a_new_l0_policy_after_now_gates_even_with_another_covering_policy(risk_table_path):
    new_l0 = _l3(
        id_="pol_a",
        level="L0",
        created_at="2026-09-29T10:20:00.500Z",
        history=[{"by": OWNER, "at": "2026-09-29T10:20:00.500Z", "change": "Created", "level": "L0"}],
    )
    assert _decide(_table(risk_table_path), _status_proposal(), [new_l0, _l3_b()]).outcome == "gate"


def test_FR_HIL_04_PI_07_check_entry_with_the_table_enforces_max_level(l3_case, risk_table_path):
    """With a table whose T2 ceiling is L2, the L3 status-update case is over its ceiling: decide
    gates it, and check_entry must agree (PI-07)."""
    good = _table(risk_table_path)
    capped = tilo_policy.RiskTable(
        actions=dict(good.actions), modifiers=tuple(good.modifiers), max_level={**good.max_level, "T2": "L2"}
    )
    assert tilo_policy.check_entry(l3_case, table=good) is None
    assert tilo_policy.check_entry(l3_case, table=capped) is not None


# --- follow-up after round 5 -----------------------------------------------------------------


def test_FR_HIL_03_PI_06_an_invalid_owner_policy_covering_the_send_gates_the_decision(risk_table_path):
    """Lowest level wins only if every covering policy counts: an owner policy for this action
    that breaks its schema but whose scope covers the send gates the whole decision, whatever
    else covers it (fail closed, never skipped)."""
    table = _table(risk_table_path)
    invalid = _l3(id_="pol_a")
    invalid["limits"]["per_day"] = None  # schema-invalid at L3
    for order in ([invalid, _l3_b()], [_l3_b(), invalid]):
        assert _decide(table, _status_proposal(), order).outcome == "gate"


def test_FR_HIL_03_PI_06_an_owner_policy_with_an_unreadable_scope_gates_the_decision(risk_table_path):
    table = _table(risk_table_path)
    unreadable = _l3(id_="pol_a")
    unreadable["scope"] = "everything"
    for order in ([unreadable, _l3_b()], [_l3_b(), unreadable]):
        assert _decide(table, _status_proposal(), order).outcome == "gate"


def test_FR_HIL_03_PI_06_an_invalid_owner_policy_scoped_elsewhere_does_not_block(risk_table_path):
    """Keeps the two tests above from gating everything: an invalid policy whose readable scope
    does not cover this send (another connector) leaves the valid covering policy in charge."""
    table = _table(risk_table_path)
    elsewhere = _l3(id_="pol_a", connectors=("slack",))
    elsewhere["limits"]["per_day"] = None
    assert _decide(table, _status_proposal(), [elsewhere, _l3_b()]).outcome == "run"


def _l0_a():
    return _l3(
        id_="pol_a", level="L0", history=[{"by": OWNER, "at": "2026-09-29T09:30:00.000Z", "change": "c", "level": "L0"}]
    )


BAD_SCOPE_VALUES = {
    "mixed_case_domain": ("domains", ["Example.ORG"]),
    "lowercase_district": ("districts", ["d1"]),
    "capital_connector": ("connectors", ["Gmail"]),
    "padded_connector": ("connectors", ["gmail "]),
    "empty_connectors": ("connectors", []),
    "dict_in_list": ("recipients", [{"email": "teammate@example.org"}]),
}


@pytest.mark.parametrize("name", sorted(BAD_SCOPE_VALUES))
def test_FR_HIL_03_PI_06_a_scope_with_one_bad_value_never_clearly_misses(name, risk_table_path):
    """Only a scope that conforms to policy.schema.json#/$defs/scope can 'clearly miss' a send; an
    L0 policy with one bad scope value plus a valid L3 policy never runs."""
    field, value = BAD_SCOPE_VALUES[name]
    a = _l0_a()
    a["scope"][field] = value
    for order in ([a, _l3_b()], [_l3_b(), a]):
        assert _decide(_table(risk_table_path), _status_proposal(), order).outcome != "run", name


def test_FR_HIL_03_PI_06_an_extra_scope_key_never_clearly_misses(risk_table_path):
    a = _l0_a()
    a["scope"]["except_connectors"] = ["gmail"]
    assert _decide(_table(risk_table_path), _status_proposal(), [a, _l3_b()]).outcome != "run"


@pytest.mark.parametrize("field,value", [("action_type", None), ("action_type", 7), ("owner", None), ("owner", "")])
def test_FR_HIL_03_PI_06_a_policy_with_an_unreadable_action_or_owner_gates(field, value, risk_table_path):
    """A record whose action type or owner cannot be read might be this owner's policy for this
    action, so it cannot be ruled out: the decision gates."""
    a = _l0_a()
    a[field] = value
    for order in ([a, _l3_b()], [_l3_b(), a]):
        assert _decide(_table(risk_table_path), _status_proposal(), order).outcome == "gate"
