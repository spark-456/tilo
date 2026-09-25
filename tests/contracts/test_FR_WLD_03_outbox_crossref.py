"""FR-WLD-03 / PRD 10.4, 11.4, HR-7: an outbox entry sends exactly what was authorised, under
the authorisation that was given.

OB-01 and OB-05 (contracts/outbox.rules.md; harness validator, P0-09). OB-01: the entry's id is
the outbox_id reserved for it; on a gate it was opened by an approval.resolved answering approve
on that gate, otherwise by a policy.applied under a policy that covers it (action type, level,
undo window, not expired, connector, recipients and district in scope); the entry's authz equals
that event's authz, and the data.transfer it emitted carries the same authz. OB-05: its action
type, tier and pinned item (artifact id and version) equal those approval.requested reserved or
policy.applied assessed, and on the policy path also its connector, destination and undo window;
a sent entry emits one data.transfer out whose artifact is that item. `broken` below is the
reference check. Each file in contracts/fixtures/outbox/crossref/ is shape-valid (each event part
also passes EV-04 to EV-06), and each invalid one breaks exactly the rule its `rule` field and
name state. The P0-09 validator's tests must run the same files.
"""

from __future__ import annotations

import pytest
from _events_lib import load_registry_raw, registry_entries
from _lib import contracts_dir, errors_for, load_json

BASE = "https://contracts.tilo.example/"
RULES = ("OB-01", "OB-05")
CASE_KEYS = {"rule", "note", "entry", "reserved_by", "authorised_by", "policy", "transfer"}
EVENT_KEYS = {"type", "authz", "data"}
SLOT_TYPES = {
    "reserved_by": ("approval.requested",),
    "authorised_by": ("approval.resolved", "policy.applied"),
    "transfer": ("data.transfer",),
}


def _cases(repo_root, kind):
    return sorted((contracts_dir(repo_root) / "fixtures" / "outbox" / "crossref" / kind).glob("*.json"))


def _pinned(item):
    return None if item is None else (item["artifact_id"], item["version"])


def _opened(entry, reserved, auth) -> bool:
    """OB-01: the event that opened the gate for this entry, and only that, authorised it."""
    if auth is None or auth["authz"] != entry["authz"]:
        return False
    data = auth["data"]
    if data["outbox_id"] != entry["id"]:
        return False
    if reserved is None:
        return auth["type"] == "policy.applied"
    return (
        auth["type"] == "approval.resolved"
        and data["option"] == "approve"
        and reserved["data"]["outbox_id"] == entry["id"]
        and (data["gate_id"], data["card_id"]) == (reserved["data"]["gate_id"], reserved["data"]["card_id"])
    )


def _within(allowed, value) -> bool:
    """Policy scope: an empty list does not restrict that dimension (policy.schema.json)."""
    return not allowed or value in allowed


def _policy_covers(entry, applied, policy) -> bool:
    """OB-01, policy path: the policy named by policy_id covers this entry within its scope."""
    scope = policy["scope"]
    return (
        policy["id"] == applied["policy_id"]
        and (policy["action_type"], policy["level"], policy["undo_window_s"])
        == (applied["action_type"], applied["level"], applied["undo_window_s"])
        and (policy["expiry"] is None or entry["authz"]["at"] < policy["expiry"])
        and applied["connector"] in scope["connectors"]
        and _within(scope["districts"], applied["district"])
        and all(
            _within(scope["recipients"], r) and _within(scope["domains"], r.rsplit("@", 1)[1].lower())
            for r in entry["recipients"]
        )
    )


def broken(case) -> set[str]:
    entry, reserved, auth, transfer = case["entry"], case["reserved_by"], case["authorised_by"], case["transfer"]
    rules = set()
    if not _opened(entry, reserved, auth):
        rules.add("OB-01")
    if transfer is not None and transfer["authz"] != entry["authz"]:
        rules.add("OB-01")
    by_policy = auth is not None and auth["type"] == "policy.applied"
    if by_policy and not _policy_covers(entry, auth["data"], case["policy"]):
        rules.add("OB-01")
    pinned_by = reserved if reserved is not None else auth
    if pinned_by is not None and (
        (pinned_by["data"]["action_type"], pinned_by["data"]["risk_tier"]) != (entry["action_type"], entry["risk_tier"])
        or _pinned(pinned_by["data"]["item"]) != _pinned(entry["item"])
    ):
        rules.add("OB-05")
    if by_policy and any(auth["data"][f] != entry[f] for f in ("connector", "destination", "undo_window_s")):
        rules.add("OB-05")
    if (transfer is not None) != (entry["state"] == "sent"):
        rules.add("OB-05")
    if transfer is not None:
        sent = transfer["data"]
        if (
            sent["direction"] != "out"
            or sent["outbox_id"] != entry["id"]
            or (sent["connector"], sent["action_type"]) != (entry["connector"], entry["action_type"])
            or _pinned(sent["artifact"]) != _pinned(entry["item"])
        ):
            rules.add("OB-05")
    return rules


def _event_part_problems(slot, part, types, registry) -> list[str]:
    """Shape of one event part plus the per-event authz rules EV-04 to EV-06."""
    if set(part) != EVENT_KEYS or part["type"] not in SLOT_TYPES[slot]:
        return [f"{slot} must be {sorted(EVENT_KEYS)} with type one of {SLOT_TYPES[slot]}"]
    type_, authz, data = part["type"], part["authz"], part["data"]
    found = [e.message for e in errors_for({"$ref": f"{BASE}events/data/{type_}.schema.json"}, data, registry)]
    entry = types[type_]
    if not entry["side_effect"]:
        return found + ([] if authz is None else [f"EV-05: {type_} carries no authz"])
    if authz is None:
        return [*found, f"EV-03: {type_} carries authz"]
    found += [e.message for e in errors_for({"$ref": f"{BASE}common.schema.json#/$defs/authz"}, authz, registry)]
    if authz["by"] not in entry["authz_by"]:
        found.append(f"EV-04: {type_} is not authorised by {authz['by']}")
    if authz["by"] == "policy" and data.get("policy_id", authz["ref"]) != authz["ref"]:
        found.append("EV-06: authz.ref must equal data.policy_id")
    return found


@pytest.mark.parametrize("kind", ["valid", "invalid"])
def test_FR_WLD_03_OB_05_outbox_crossref_cases_are_shape_valid(repo_root, registry, kind):
    files = _cases(repo_root, kind)
    assert files, f"contracts/fixtures/outbox/crossref/{kind}/ must hold at least one case"
    types = registry_entries(load_registry_raw(repo_root))
    for path in files:
        case = load_json(path)
        assert set(case) == CASE_KEYS, f"{path.name}: keys must be {sorted(CASE_KEYS)}"
        found = [e.message for e in errors_for({"$ref": BASE + "outbox.schema.json"}, case["entry"], registry)]
        for slot in SLOT_TYPES:
            if case[slot] is not None:
                found += _event_part_problems(slot, case[slot], types, registry)
        by_policy = case["authorised_by"] is not None and case["authorised_by"]["type"] == "policy.applied"
        if (case["policy"] is not None) != by_policy:
            found.append("policy is the policy record that policy.applied names, and null on a gate path")
        elif by_policy:
            found += [e.message for e in errors_for({"$ref": BASE + "policy.schema.json"}, case["policy"], registry)]
        assert not found, f"{path.name}: every part must be shape-valid, got {found[:3]}"


def test_FR_WLD_03_OB_05_valid_entries_send_what_was_authorised(repo_root):
    for path in _cases(repo_root, "valid"):
        case = load_json(path)
        assert case["rule"] is None and not broken(case), f"{path.name}: breaks {sorted(broken(case))}"


def test_FR_WLD_03_OB_05_each_invalid_entry_breaks_only_its_rule(repo_root):
    covered = set()
    for path in _cases(repo_root, "invalid"):
        case = load_json(path)
        rule = case["rule"]
        assert path.name.startswith(rule.lower().replace("-", "")), f"{path.name} must start with {rule}"
        assert broken(case) == {rule}, f"{path.name}: expected only {rule}, got {sorted(broken(case))}"
        covered.add(rule)
    assert covered == set(RULES), f"every rule needs an invalid case; missing {set(RULES) - covered}"


def test_FR_WLD_03_OB_01_every_authorisation_path_has_an_invalid_case(repo_root):
    """A gate nobody approved and a send stamped with the wrong authority each fail OB-01 (HR-7)."""
    names = {path.stem for path in _cases(repo_root, "invalid")}
    required = {
        "ob01_gate_answered_hold",
        "ob01_gate_never_answered",
        "ob01_authz_from_another_person",
        "ob01_authz_from_team_lead_not_the_person",
        "ob01_policy_send_stamped_as_person",
        "ob01_person_approved_send_stamped_as_policy",
        "ob01_transfer_stamped_other_than_entry",
    }
    assert required <= names, f"missing OB-01 cases {sorted(required - names)}"


def test_FR_WLD_03_OB_01_OB_05_policy_path_has_an_invalid_case_per_binding(repo_root):
    """With no gate card, a policy send is bound to its policy's scope and to policy.applied (PRD 10.4)."""
    names = {path.stem for path in _cases(repo_root, "invalid")}
    required = {
        "ob01_policy_recipient_out_of_scope",
        "ob01_policy_connector_out_of_scope",
        "ob01_policy_district_out_of_scope",
        "ob01_policy_expired",
        "ob05_policy_undo_window_dropped",
        "ob05_policy_risk_tier_differs",
        "ob05_policy_thread_reply_sent_as_new_email",
        "ob05_policy_entry_on_another_connector",
    }
    assert required <= names, f"missing policy-path cases {sorted(required - names)}"


def test_FR_WLD_03_OB_05_save_file_entry_names_its_file(repo_root):
    saves = [load_json(p) for p in (contracts_dir(repo_root) / "fixtures" / "outbox" / "valid").glob("*.json")]
    saves = [e for e in saves if e["action_type"] == "save_file"]
    assert saves and all(e["item"] is not None for e in saves), "a save_file entry must name the file it saves"
