"""FR-SKL-05 to 07 (ADR-0037, accepted 12 Oct 2026): `real_run` and `run_answer` in taught_skill.schema.json 1.1.0
and rules TS-13 to TS-17. `_refusal` below is the reference check for TS-15 and TS-16: the tilo-api tests must
reach the same verdict on the same files in `contracts/fixtures/taught_skill/crossref/`."""

from __future__ import annotations

import pytest
from _lib import contracts_dir, errors_for, list_fixtures, load_json, load_schema

ROOT = "https://contracts.tilo.example/taught_skill.schema.json"
FOLDERS = ("taught_skill.real_run", "taught_skill.run_answer")
MUST_ASK = ["send", "post", "pay", "delete", "share", "book"]
CASE_KEYS = {"rule", "note", "org_id", "run", "earlier", "rating", "answer"}


def _ref(key: str) -> dict:
    return {"$ref": f"{ROOT}#/$defs/{key}"}


def _cases(repo_root, kind):
    return sorted((contracts_dir(repo_root) / "fixtures" / "taught_skill" / "crossref" / kind).glob("*.json"))


def _refusal(case) -> str | None:
    """The rule id that refuses this rating or answer, or None when it is accepted (TS-15, TS-16)."""
    run, org = case["run"], case["org_id"]
    if run is None or run["org_id"] != org:
        return "TS-15" if "rating" in case else "TS-16"
    if "answer" in case:
        a = case["answer"]
        same = all(a[k] == run[k] for k in ("org_id", "skill", "version", "run_id", "world_id"))
        return None if same else "TS-16"
    r = case["rating"]
    if any(r[k] != run[k] for k in ("skill", "version", "run_id", "by")) or run["outcome"] is None:
        return "TS-15"
    if r["thumb"] == "up" and run["outcome"] != "completed":
        return "TS-15"
    if any((e["skill"], e["run_id"]) == (r["skill"], r["run_id"]) for e in case["earlier"]):
        return "TS-15"
    return None


@pytest.mark.parametrize("folder", FOLDERS)
def test_FR_SKL_05_every_valid_fixture_passes_and_every_invalid_one_fails(repo_root, registry, folder):
    valid, invalid = list_fixtures(repo_root, folder, "valid"), list_fixtures(repo_root, folder, "invalid")
    ref = _ref(folder.partition(".")[2])
    assert valid and invalid
    assert all(not errors_for(ref, load_json(p), registry) for p in valid)
    assert all(errors_for(ref, load_json(p), registry) for p in invalid), "each invalid case breaks a rule"


def test_FR_SKL_05_a_real_run_records_what_it_needs_and_nothing_a_rating_owns(repo_root):
    defs = load_schema(repo_root, "taught_skill")["$defs"]
    run = defs["real_run"]
    assert (
        set(run["required"])
        == set(run["properties"])
        == {
            "org_id",
            "skill",
            "version",
            "run_id",
            "world_id",
            "by",
            "plan",
            "started_at",
            "finished_at",
            "outcome",
        }
    )
    assert run["additionalProperties"] is False, "no thumb, note or answer text rides on the run"
    assert run["properties"]["plan"]["items"] == {"$ref": "#/$defs/plan_step"}, "the snapshot is a plan"
    assert (run["properties"]["plan"]["minItems"], run["properties"]["plan"]["maxItems"]) == (1, 20)


def test_FR_SKL_05_the_terminal_enum_is_completed_and_failed_only(repo_root):
    outcome = load_schema(repo_root, "taught_skill")["$defs"]["run_outcome"]
    assert outcome["enum"] == ["completed", "failed"], "Pause all and the kill switch finish nothing (TS-14)"


@pytest.mark.parametrize(
    ("changes", "ok"),
    [
        ({"outcome": None, "finished_at": None}, True),
        ({"outcome": "failed"}, True),
        ({"outcome": None}, False),
        ({"finished_at": None}, False),
    ],
)
def test_FR_SKL_05_finished_at_and_outcome_are_null_together(repo_root, registry, changes, ok):
    run = load_json(repo_root / "contracts/fixtures/taught_skill.real_run/valid/completed_by_team_member.json")
    assert bool(errors_for(_ref("real_run"), {**run, **changes}, registry)) is not ok, changes


@pytest.mark.parametrize("verb", MUST_ASK)
def test_FR_SKL_05_the_plan_snapshot_cannot_launder_a_must_ask_step(repo_root, registry, verb):
    run = load_json(repo_root / "contracts/fixtures/taught_skill.real_run/valid/completed_by_team_member.json")
    step = {"text": "Do it", "tool": "gmail", "action": "send_email", "verb": verb, "ask_first": True}
    for ask_first, must_ask, ok in ((True, True, True), (False, True, False), (True, False, False)):
        plan = [{**step, "ask_first": ask_first, "must_ask": must_ask}]
        assert bool(errors_for(_ref("real_run"), {**run, "plan": plan}, registry)) is not ok, (
            verb,
            ask_first,
            must_ask,
        )


def test_FR_SKL_07_a_run_answer_links_records_and_holds_no_text(repo_root):
    answer = load_schema(repo_root, "taught_skill")["$defs"]["run_answer"]
    assert set(answer["required"]) == set(answer["properties"])
    assert set(answer["properties"]) == {"org_id", "skill", "version", "run_id", "world_id", "card_id", "by", "at"}
    assert answer["additionalProperties"] is False, "no question, option or answer text (TS-16)"


@pytest.mark.parametrize("kind", ["valid", "invalid"])
def test_FR_SKL_05_07_crossref_cases_are_shaped_and_reach_the_stated_verdict(repo_root, registry, kind):
    cases = _cases(repo_root, kind)
    assert len(cases) >= (4 if kind == "valid" else 8)
    seen = set()
    for path in cases:
        case = load_json(path)
        assert set(case) <= CASE_KEYS and {"rule", "note", "org_id", "run", "earlier"} <= set(case), path.name
        assert ("rating" in case) != ("answer" in case), path.name
        for key, def_name in (("run", "real_run"), ("answer", "run_answer")):
            if case.get(key) is not None:
                assert not errors_for(_ref(def_name), case[key], registry), (path.name, key)
        if "rating" in case:
            assert not errors_for(_ref("rating"), case["rating"], registry), path.name
        verdict = _refusal(case)
        assert verdict == case["rule"], (path.name, verdict)
        if kind == "invalid":
            assert path.name.startswith(case["rule"].lower().replace("-", "")), path.name
            seen.add(case["rule"])
    assert seen == ({"TS-15", "TS-16"} if kind == "invalid" else set())


def test_FR_SKL_05_the_rules_file_states_ts_13_to_ts_17_and_the_version_is_at_least_1_1(repo_root):
    rules = (repo_root / "contracts/taught_skill.rules.md").read_text(encoding="utf-8")
    assert all(f"| TS-{n} |" in rules for n in range(13, 18))
    assert tuple(int(p) for p in load_schema(repo_root, "taught_skill")["x-version"].split(".")) >= (1, 1, 0)
