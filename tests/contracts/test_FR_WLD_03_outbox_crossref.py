"""FR-WLD-03 / PRD 10.4, 11.4, HR-7: an outbox entry sends exactly what was authorised, under
the authorisation that was given.

OB-01 and OB-05 (contracts/outbox.rules.md; harness validator, P0-09). OB-01: the entry's id is
the outbox_id reserved for it; on a gate it was opened by an approval.resolved answering approve
on that gate from someone who may open it (PRD 10.1: the world's owner, the Approver the gate
names, or a Team Lead whose owner-assigned domain is the gate's while the owner's policy the gate
names allows that domain; a T3 gate answered on WhatsApp also needs its PIN checked, SEC-06),
otherwise by a policy.applied under a policy that covers it (action type and
undo window, created before and not expired, at the applied level when the send was authorised
(its last history entry at or before authz.at, so not after a revocation or Stop all autopilot),
owned by the world's owner and created and changed only by that owner (every history entry
included, PRD 10.1), connector, recipients and district in scope; at L2 also the owner's
own earlier instruction in this world about the same destination, PRD 10.4 "instruction is
approval", given where Tilo knows who sent it: signed in on the web or mobile web, or from the
owner's bound WhatsApp number, never by email, PRD 10.3 and 11.1; and no earlier policy.applied
used that instruction, even if its entry was cancelled); the entry's authz equals
that event's authz, and the data.transfer it emitted carries the same authz. OB-05: its action
type, tier and pinned item (artifact id and version) equal those approval.requested reserved or
policy.applied assessed, and on the policy path also its connector, destination and undo window;
a sent entry emits one data.transfer out whose artifact is that item. `broken` below is the
reference check. Each file in contracts/fixtures/outbox/crossref/ is shape-valid (each event part
also passes EV-04 to EV-06), and each invalid one breaks exactly the rule its `rule` field and
name state. The P0-09 validator's tests must run the same files.
"""

from __future__ import annotations

from itertools import pairwise

import pytest
from _events_lib import load_registry_raw, registry_entries
from _lib import contracts_dir, errors_for, load_json

BASE = "https://contracts.tilo.example/"
RULES = ("OB-01", "OB-05")
CASE_KEYS = {
    "rule",
    "note",
    "entry",
    "reserved_by",
    "authorised_by",
    "policy",
    "team_lead",
    "world_owner",
    "instruction",
    "earlier_applied",
    "transfer",
}
EVENT_KEYS = {"type", "authz", "data"}
# OB-01, L2: the channels on which Tilo knows the sender is the owner, per instruction type.
INSTRUCTION_CHANNELS = {"world.requested": ("web", "mobile_web"), "channel.message_in": ("whatsapp",)}
INSTRUCTION_TYPES = tuple(INSTRUCTION_CHANNELS)
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


def _level_at(policy, at):
    """OB-01: the policy's level in force at `at`, the level of its last history entry at or before
    `at` (history is oldest first), or None before the first entry. A record that is out of time
    order, or whose level is not its last entry's, covers nothing. So a revocation or Stop all
    autopilot (an entry at L1) before the send is never skipped, even if the owner raised the level
    again later (PRD 10.4, FR-HIL-03, FR-HIL-07)."""
    history = policy["history"]
    in_order = all(a["at"] <= b["at"] for a, b in pairwise(history))
    if not history or not in_order or history[-1]["level"] != policy["level"]:
        return None
    earlier = [h["level"] for h in history if h["at"] <= at]
    return earlier[-1] if earlier else None


def _made_by_owner(policy) -> bool:
    """OB-01, PI-13: only the owner creates and changes a policy (PRD 10.1; a Team Lead only
    proposes, an Approver or Viewer has no say), so its creation, last change and every history
    entry are the owner's. A record anyone else made or changed covers nothing, whatever `owner`
    says, so a raise after a revocation by someone else never counts."""
    stamps = [policy["created_by"], policy["changed_by"], *policy["history"]]
    return all(stamp["by"] == policy["owner"] for stamp in stamps if stamp is not None)


def _may_answer(gate, answer, owner, lead, policy) -> bool:
    """OB-01, gate path (PRD 10.1): the world's owner, the Approver the gate names, or a Team Lead
    whose domain the owner assigned before the answer (PRD 16.2), when the gate names that domain
    and the owner's policy it names (same action type, in force) lists it. A Viewer, anyone else
    or a Team Lead of another domain opens nothing. A T3 gate answered on WhatsApp also needs its
    PIN checked (SEC-06)."""
    authz, allowed = answer["authz"], gate["data"]["team_lead"]
    if gate["data"]["risk_tier"] == "T3" and answer["data"]["channel"] == "whatsapp":
        if not answer["data"]["pin_verified"]:
            return False
    if authz["by"] == "person":
        return authz["ref"] in (owner, gate["data"]["approver"])
    return (
        allowed is not None
        and lead is not None
        and policy is not None
        and (lead["id"], lead["domain"]) == (authz["ref"], allowed["domain"])
        and lead["assigned_by"]["by"] == owner
        and lead["assigned_by"]["at"] <= authz["at"]
        and policy["id"] == allowed["policy_id"]
        and policy["owner"] == owner
        and _made_by_owner(policy)
        and policy["action_type"] == gate["data"]["action_type"]
        and allowed["domain"] in policy["team_lead_domains"]
        and policy["created_by"]["at"] <= authz["at"]
        and (policy["expiry"] is None or authz["at"] < policy["expiry"])
    )


def _instructed(entry, applied, level, policy, instruction, earlier) -> bool:
    """OB-01, L2: the policy owner's own earlier instruction in this world, from a signed-in session
    or the owner's bound WhatsApp number (never email), asked for this send, and no earlier
    policy.applied used it up (whatever became of that entry, cancelled included)."""
    if level != "L2":
        return applied["instruction_id"] is None and instruction is None
    return (
        instruction is not None
        and instruction["id"] == applied["instruction_id"]
        and instruction["data"]["channel"] in INSTRUCTION_CHANNELS[instruction["type"]]
        and all(used["data"]["instruction_id"] != applied["instruction_id"] for used in earlier)
        and instruction["world_id"] == entry["world_id"]
        and instruction["ts"] < entry["authz"]["at"]
        and instruction["actor"] == policy["owner"]
        and applied["destination"] is not None
        and instruction["data"]["destination"] == applied["destination"]
    )


def _policy_covers(entry, applied, policy, world_owner, instruction, earlier) -> bool:
    """OB-01, policy path: the policy named by policy_id covers this entry within its scope."""
    scope = policy["scope"]
    at = entry["authz"]["at"]
    level = _level_at(policy, at)
    return (
        policy["id"] == applied["policy_id"]
        and policy["owner"] == world_owner
        and _made_by_owner(policy)
        and (policy["action_type"], level, policy["undo_window_s"])
        == (applied["action_type"], applied["level"], applied["undo_window_s"])
        and policy["created_by"]["at"] <= at
        and (policy["expiry"] is None or at < policy["expiry"])
        and _instructed(entry, applied, level, policy, instruction, earlier)
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
    answered = reserved is not None and auth is not None and auth["type"] == "approval.resolved"
    if answered and not _may_answer(reserved, auth, case["world_owner"], case["team_lead"], case["policy"]):
        rules.add("OB-01")
    by_policy = auth is not None and auth["type"] == "policy.applied"
    if by_policy and not _policy_covers(
        entry, auth["data"], case["policy"], case["world_owner"], case["instruction"], case["earlier_applied"]
    ):
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
        owner = {"$ref": BASE + "common.schema.json#/$defs/user_id"}
        found += [e.message for e in errors_for(owner, case["world_owner"], registry)]
        if by_policy and (case["policy"] is None or case["team_lead"] is not None):
            found.append("the policy path has a policy and no team_lead")
        if not by_policy and (case["policy"] is not None) != (case["team_lead"] is not None):
            found.append("on the gate path, policy and team_lead are both set (a Team Lead answered) or both null")
        for part, schema in ((case["policy"], "policy"), (case["team_lead"], "team_lead")):
            if part is not None:
                found += [e.message for e in errors_for({"$ref": f"{BASE}{schema}.schema.json"}, part, registry)]
        if (case["earlier_applied"] is not None) != by_policy:
            found.append("earlier_applied is set on the policy path only")
        elif by_policy:
            for used in case["earlier_applied"]:
                found += _event_part_problems("authorised_by", used, types, registry)
                found += [] if used["type"] == "policy.applied" else ["earlier_applied holds policy.applied parts"]
        instruction = case["instruction"]
        if instruction is not None and (not by_policy or instruction.get("type") not in INSTRUCTION_TYPES):
            found.append(f"instruction is a whole {INSTRUCTION_TYPES} event, on the policy path only")
        elif instruction is not None:
            found += [e.message for e in errors_for({"$ref": BASE + "event.schema.json"}, instruction, registry)]
            data_schema = {"$ref": f"{BASE}events/data/{instruction['type']}.schema.json"}
            found += [e.message for e in errors_for(data_schema, instruction["data"], registry)]
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
    """A gate nobody approved, a gate approved by someone who may not open it (PRD 10.1, 16.2,
    SEC-06) and a send stamped with the wrong authority each fail OB-01 (HR-7)."""
    names = {path.stem for path in _cases(repo_root, "invalid")}
    required = {
        "ob01_gate_answered_hold",
        "ob01_gate_never_answered",
        "ob01_authz_from_another_person",
        "ob01_authz_from_team_lead_not_the_person",
        "ob01_gate_approved_by_viewer",
        "ob01_gate_approved_by_team_lead_outside_domain",
        "ob01_gate_approved_by_team_lead_policy_does_not_allow",
        "ob01_gate_approved_by_team_lead_assigned_by_someone_else",
        "ob01_t3_whatsapp_without_pin",
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
        "ob01_policy_created_after_send",
        "ob01_policy_owned_by_someone_else",
        "ob01_policy_created_by_someone_else",
        "ob01_policy_raised_by_someone_else",
        "ob01_policy_revoked_before_send",
        "ob01_policy_stopped_before_send",
        "ob01_policy_level_not_its_last_history_level",
        "ob01_l2_policy_without_instruction",
        "ob01_l2_instruction_from_someone_else",
        "ob01_l2_instruction_on_another_thread",
        "ob01_l2_instruction_after_send",
        "ob01_l2_instruction_by_email",
        "ob01_l2_world_requested_by_email",
        "ob01_l2_instruction_reused",
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
