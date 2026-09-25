"""FR-HIL-04 / FR-HIL-08 (PRD 10.4): "The engine is deterministic code; a model never decides
whether something is authorised." Two checks: decide() and open_gate() give equal Decisions for
equal arguments (no hidden randomness or ambient state), and no file under packages/policy/src
imports a model/network/randomness source or reads the wall clock — every time value is an
argument (`now`, event `at`/`ts` fields), never read internally.
"""

from __future__ import annotations

import ast
import pathlib

import tilo_policy
from _policy_lib import OWNER, WORLD, base_facts, base_instruction, base_policy

NOW = "2026-09-29T09:42:16.000Z"

FORBIDDEN_IMPORTS = {"tilo_providers", "random", "secrets", "requests", "httpx", "urllib", "socket"}
FORBIDDEN_CLOCK_CALLS = {
    ("datetime", "now"),
    ("datetime", "utcnow"),
    ("time", "time"),
    ("time", "time_ns"),
}


def _src_root(repo_root: pathlib.Path) -> pathlib.Path:
    return repo_root / "packages" / "policy" / "src"


def _proposal(instruction=None):
    return tilo_policy.Proposal(
        world_id=WORLD,
        action_type="send_email",
        connector="gmail",
        district="D1",
        destination="thread-supplier-1",
        facts=tilo_policy.SideEffectFacts(**base_facts()),
        item={"artifact_id": "art_x", "version": 1},
        credits=1,
        instruction=instruction,
    )


def test_FR_HIL_04_decide_is_deterministic_same_inputs_give_equal_decisions(risk_table_path):
    table = tilo_policy.load_risk_table(risk_table_path)
    instruction = base_instruction()
    policy = base_policy(id_="pol_autopilot_l2", level="L2")
    first = tilo_policy.decide(
        _proposal(instruction), table=table, policies=[policy], world_owner=OWNER, applied=[], now=NOW
    )
    second = tilo_policy.decide(
        _proposal(instruction), table=table, policies=[policy], world_owner=OWNER, applied=[], now=NOW
    )
    assert first == second


def test_FR_HIL_04_open_gate_is_deterministic_same_inputs_give_equal_decisions():
    reserved = {
        "type": "approval.requested",
        "authz": None,
        "data": {
            "gate_id": "G1",
            "card_id": "01JB5VQ0000000000000009001",
            "outbox_id": "01JB5VQ0000000000000009002",
            "action_type": "send_email",
            "risk_tier": "T2",
            "irreversible": True,
            "item": {"artifact_id": "art_x", "version": 1},
            "approver": None,
            "team_lead": None,
        },
    }
    resolved = {
        "type": "approval.resolved",
        "authz": {"by": "person", "ref": OWNER, "at": NOW},
        "data": {
            "gate_id": "G1",
            "card_id": "01JB5VQ0000000000000009001",
            "outbox_id": "01JB5VQ0000000000000009002",
            "option": "approve",
            "channel": "web",
            "pin_verified": True,
        },
    }
    first = tilo_policy.open_gate(reserved, resolved, world_owner=OWNER)
    second = tilo_policy.open_gate(reserved, resolved, world_owner=OWNER)
    assert first == second


def _iter_source_files(repo_root: pathlib.Path):
    src = _src_root(repo_root)
    if not src.is_dir():
        return []
    return sorted(src.rglob("*.py"))


def test_FR_HIL_04_no_provider_network_or_randomness_import_under_src(repo_root):
    files = _iter_source_files(repo_root)
    assert files, "packages/policy/src must exist once the engine is implemented"
    violations = []
    for path in files:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                names = [a.name.split(".")[0] for a in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module:
                names = [node.module.split(".")[0]]
            else:
                continue
            bad = FORBIDDEN_IMPORTS & set(names)
            if bad:
                violations.append(f"{path.relative_to(repo_root)}: imports {sorted(bad)}")
    assert not violations, violations


def test_FR_HIL_04_no_wall_clock_read_under_src(repo_root):
    files = _iter_source_files(repo_root)
    assert files, "packages/policy/src must exist once the engine is implemented"
    violations = []
    for path in files:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
                continue
            attr = node.func.attr
            owner = node.func.value
            owner_name = owner.id if isinstance(owner, ast.Name) else None
            if owner_name and (owner_name, attr) in FORBIDDEN_CLOCK_CALLS:
                violations.append(f"{path.relative_to(repo_root)}: calls {owner_name}.{attr}()")
    assert not violations, violations
