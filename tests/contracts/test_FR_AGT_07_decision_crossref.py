"""FR-AGT-07 / PRD 8.3, 10.1, 13.1, 16.2: a repeat question is answered from a Decision only
inside the authority, scope and time of the answer it records.

DC-01 to DC-04 (contracts/decision.rules.md; tilo-api and harness validators, P7). DC-01: only
the source world's owner or a Team Lead gives a Decision (an Approver's answer makes none), and a
person's Decision covers only worlds that person owns. DC-02: a Team Lead's Decision names the
record's domain and the person who held the record, the source world's owner assigned the Team
Lead no later than the answer, and the Decision covers only that owner's worlds. DC-03: time
order. DC-04: the cited Decision is of the world's org, created before and unexpired at the
event, in scope for its world and district, and its answerer can still answer in that world at
that time: a person is the world's owner; a Team Lead's record still exists with the same domain
and the same person (`user`) as the Decision records, assigned by that world's owner no later
than the answer, and the question was routed with that domain. `broken` below is the reference
check. Each file in contracts/fixtures/decision/crossref/ is shape-valid, and each invalid one
breaks exactly the rule its `rule` field and name state. The P7 validator's tests must run the
same files.
"""

from __future__ import annotations

import pytest
from _lib import contracts_dir, errors_for, load_json

BASE = "https://contracts.tilo.example/"
RULES = ("DC-01", "DC-02", "DC-04")
CASE_KEYS = {"rule", "note", "decision", "worlds", "team_lead_at_answer", "reuse"}
REUSE_KEYS = {"answered", "routed", "team_lead"}
ANSWERED_KEYS = {"ts", "world_id", "district", "data"}


def _cases(repo_root, kind):
    return sorted((contracts_dir(repo_root) / "fixtures" / "decision" / "crossref" / kind).glob("*.json"))


def _covers(listed, value) -> bool:
    return listed == "all" or value in listed


def _assigned_by(lead, owner, at) -> bool:
    """A Team Lead's domain counts only as the world's owner assigned it, no later than `at`."""
    return lead["assigned_by"]["by"] == owner and lead["assigned_by"]["at"] <= at


def _scope_within(case, owner) -> bool:
    """DC-01, DC-02: every listed world is a world of the Decision's org that `owner` owns; `all`
    means those worlds and is checked again at each reuse (DC-04)."""
    decision, worlds = case["decision"], case["worlds"]
    listed = decision["scope"]["worlds"]
    return listed == "all" or all(
        worlds[w]["org_id"] == decision["org_id"] and worlds[w]["owner"] == owner for w in listed
    )


def _written_by_whom_may(case) -> set[str]:
    """DC-01 and DC-02: who may give a Decision, and where it may answer."""
    decision = case["decision"]
    by = decision["answered_by"]
    source = case["worlds"][decision["source"]["world_id"]]
    if source["org_id"] != decision["org_id"]:
        return {"DC-01"}
    if by["by"] == "person":
        return set() if by["ref"] == source["owner"] and _scope_within(case, by["ref"]) else {"DC-01"}
    lead = case["team_lead_at_answer"]
    ok = (
        lead["id"] == by["ref"]
        and lead["user"] == by["user"]
        and lead["domain"] == decision["domain"]
        and _assigned_by(lead, source["owner"], by["at"])
        and _scope_within(case, source["owner"])
    )
    return set() if ok else {"DC-02"}


def _reusable(case) -> bool:
    """DC-04: the Decision answers this repeat question, its answerer checked again in this world
    at this time (PRD 10.1, 16.2), as outbox OB-01 checks an answer to a gate. A Team Lead id is
    only an indirection to a person: the record must still name the person who answered."""
    decision, reuse = case["decision"], case["reuse"]
    answered, lead = reuse["answered"], reuse["team_lead"]
    world, ts, scope = case["worlds"][answered["world_id"]], answered["ts"], decision["scope"]
    if world["org_id"] != decision["org_id"] or answered["data"].get("decision_id") != decision["id"]:
        return False
    if not decision["created_at"] < ts or (decision["expires_at"] is not None and ts >= decision["expires_at"]):
        return False
    district = answered["district"]
    if (
        not _covers(scope["worlds"], answered["world_id"])
        or district is None
        or not _covers(scope["districts"], district)
    ):
        return False
    by = decision["answered_by"]
    if by["by"] == "person":
        return by["ref"] == world["owner"]
    return (
        lead is not None
        and lead["id"] == by["ref"]
        and lead["user"] == by["user"]
        and lead["domain"] == decision["domain"]
        and _assigned_by(lead, world["owner"], by["at"])
        and reuse["routed"]["data"]["domain"] == decision["domain"]
    )


def broken(case) -> set[str]:
    """The reference check: the DC rules a case breaks."""
    decision = case["decision"]
    found = _written_by_whom_may(case)
    at, created, expires = decision["answered_by"]["at"], decision["created_at"], decision["expires_at"]
    if created < at or (expires is not None and expires <= created):
        found.add("DC-03")
    if case["reuse"] is not None and not _reusable(case):
        found.add("DC-04")
    return found


def _ref(name):
    return {"$ref": f"{BASE}{name}"}


def _shape_problems(case, registry) -> list[str]:
    found = [e.message for e in errors_for(_ref("decision.schema.json"), case["decision"], registry)]
    decision, worlds = case["decision"], case["worlds"]
    for world_id, world in worlds.items():
        found += [e.message for e in errors_for(_ref("common.schema.json#/$defs/world_id"), world_id, registry)]
        if set(world) != {"org_id", "owner"}:
            found.append(f"worlds.{world_id} holds org_id and owner")
            continue
        found += [e.message for e in errors_for(_ref("common.schema.json#/$defs/org_id"), world["org_id"], registry)]
        found += [e.message for e in errors_for(_ref("common.schema.json#/$defs/user_id"), world["owner"], registry)]
    named = {decision["source"]["world_id"]}
    named |= set() if decision["scope"]["worlds"] == "all" else set(decision["scope"]["worlds"])
    person = decision["answered_by"]["by"] == "person"
    if (case["team_lead_at_answer"] is None) != person:
        found.append("team_lead_at_answer is set exactly for a Team Lead's Decision")
    leads = [case["team_lead_at_answer"]]
    reuse = case["reuse"]
    if reuse is not None:
        if set(reuse) != REUSE_KEYS or set(reuse["answered"]) != ANSWERED_KEYS or set(reuse["routed"]) != {"data"}:
            return [*found, f"reuse holds {sorted(REUSE_KEYS)}, answered {sorted(ANSWERED_KEYS)}, routed data"]
        answered = reuse["answered"]
        named.add(answered["world_id"])
        found += [e.message for e in errors_for(_ref("common.schema.json#/$defs/timestamp"), answered["ts"], registry)]
        district = _ref("common.schema.json#/$defs/district_id")
        found += [e.message for e in errors_for(district, answered["district"], registry)]
        data = _ref("events/data/question.answered.schema.json")
        found += [e.message for e in errors_for(data, answered["data"], registry)]
        if answered["data"]["answered_by"] != "decision":
            found.append("reuse.answered is answered by a decision")
        routed = _ref("events/data/question.routed.schema.json")
        found += [e.message for e in errors_for(routed, reuse["routed"]["data"], registry)]
        if person and reuse["team_lead"] is not None:
            found.append("reuse.team_lead is null for a person's Decision")
        leads.append(reuse["team_lead"])
    for lead in leads:
        if lead is not None:
            found += [e.message for e in errors_for(_ref("team_lead.schema.json"), lead, registry)]
    if not named <= set(worlds):
        found.append(f"worlds must describe {sorted(named - set(worlds))}")
    return found


@pytest.mark.parametrize("kind", ["valid", "invalid"])
def test_FR_AGT_07_decision_crossref_cases_are_shape_valid(repo_root, registry, kind):
    files = _cases(repo_root, kind)
    assert files, f"contracts/fixtures/decision/crossref/{kind}/ must hold at least one case"
    for path in files:
        case = load_json(path)
        assert set(case) == CASE_KEYS, f"{path.name}: keys must be {sorted(CASE_KEYS)}"
        found = _shape_problems(case, registry)
        assert not found, f"{path.name}: every part must be shape-valid, got {found[:3]}"


def test_FR_AGT_07_valid_decisions_answer_their_repeat_questions(repo_root):
    for path in _cases(repo_root, "valid"):
        case = load_json(path)
        assert case["rule"] is None and case["reuse"] is not None, f"{path.name}: a valid case reuses its Decision"
        assert not broken(case), f"{path.name}: breaks {sorted(broken(case))}"


def test_FR_AGT_07_each_invalid_decision_case_breaks_only_its_rule(repo_root):
    covered = set()
    for path in _cases(repo_root, "invalid"):
        case = load_json(path)
        rule = case["rule"]
        assert path.name.startswith(rule.lower().replace("-", "")), f"{path.name} must start with {rule}"
        assert broken(case) == {rule}, f"{path.name}: expected only {rule}, got {sorted(broken(case))}"
        covered.add(rule)
    assert covered == set(RULES), f"every rule needs an invalid case; missing {set(RULES) - covered}"


def test_FR_AGT_07_answerer_authority_is_checked_where_a_decision_is_reused(repo_root):
    """A removed Team Lead, a person no longer behind the Team Lead id, another owner's world
    and an Approver answer nothing through a Decision (PRD 10.1, 13.1, 16.2; team_lead.schema.json:
    a removed Team Lead answers nothing)."""
    names = {path.stem for path in _cases(repo_root, "invalid")}
    required = {
        "dc01_approver_answer_kept_as_decision",
        "dc01_owner_decision_scoped_to_another_owners_world",
        "dc02_team_lead_assigned_by_another_owner",
        "dc02_team_lead_decision_scoped_to_another_owners_world",
        "dc02_team_lead_decision_names_another_person",
        "dc04_team_lead_removed",
        "dc04_team_lead_removed_and_assigned_again",
        "dc04_team_lead_domain_changed",
        "dc04_team_lead_person_replaced",
        "dc04_team_lead_decision_in_another_owners_world",
        "dc04_owner_decision_in_another_owners_world",
        "dc04_approver_decision_reused_where_they_only_approve",
    }
    assert required <= names, f"missing DC cases {sorted(required - names)}"


def test_FR_AGT_07_event_fixture_cites_a_decision_fixture(repo_root):
    """fixtures/events/valid has a question.answered answered from a Decision whose decision_id
    names a valid Decision fixture created before the event, in scope for its world and district."""
    fixtures = contracts_dir(repo_root) / "fixtures"
    decisions = {d["id"]: d for d in map(load_json, sorted((fixtures / "decision" / "valid").glob("*.json")))}
    events = [load_json(p) for p in sorted((fixtures / "events" / "valid").glob("question.answered*.json"))]
    cited = [e for e in events if e["data"]["answered_by"] == "decision"]
    assert cited, "a valid question.answered fixture must be answered from a Decision"
    for event in cited:
        decision = decisions.get(event["data"]["decision_id"])
        assert decision is not None, f"decision_id {event['data']['decision_id']} names no Decision fixture"
        assert decision["created_at"] < event["ts"]
        assert _covers(decision["scope"]["worlds"], event["world_id"])
        assert _covers(decision["scope"]["districts"], event["district"])
