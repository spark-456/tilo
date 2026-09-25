"""P4-01 review round 1 (security, qa): malformed input must never widen authority.

The engine reads policies, events, facts and crossref cases that other services wrote. A record
that breaks its contract (contracts/*.schema.json) covers nothing, an event part that breaks its
schema opens nothing, and an entry the engine cannot fully check is rejected (PRD 10.4 "the
engine is deterministic code", docs/security/p4-policy-invariants.md PI-06, PI-07, PI-11, PI-16,
SEC-06). Each case below was a probe that returned "run" or a valid verdict in review round 1.
"""

from __future__ import annotations

import copy
import json
import pathlib
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


@pytest.mark.parametrize("recipient", ["a@evil.com@example.org", "teammate@example.org.", "", "no-at-sign"])
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
