"""FR-INT-11 (PRD 7.1, 4.3, 5 PR-7): "Scenario configs preload skills, connectors, seed data, autonomy policy
and world theme from `config/scenarios/<id>.yaml`." Acceptance: "Loading SC-01's file needs no code change and
passes its smoke test."

The public interface these tests pin is in `API_FR_INT_11_12.md` (module `tilo_planning.scenarios`). The scenario
config schema does not exist in `contracts/`: needs contract change: `contracts/scenario.schema.json` (shape of
`config/scenarios/<id>.yaml`). These tests assert behaviour through the loader, not through a schema, so they hold
whichever way the architect words it.

"No code change" is tested three ways: a fictional scenario loads through the same generic loader (nothing keyed
on an id), every file shipped under `config/scenarios/` loads, and no platform source names a scenario id (root
CLAUDE.md: no scenario-specific code). SC-01's own file is loaded only through that generic loader.
"""

from __future__ import annotations

import pathlib
import re
import shutil
from typing import Any

import pytest
import yaml
from _planning_contracts_lib import build_registry, errors_for, load_schema
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

REPO_ROOT = pathlib.Path(__file__).resolve().parents[3]
AT = "2026-10-05T09:00:00.000Z"
OWNER = "u_scenario_owner"

GOOD: dict[str, Any] = {
    "id": "TS-91",
    "title": "Fictional vendor comparison",
    "skills": ["vendor-research", "deck-drafting"],
    "connectors": ["google_drive"],
    "seed_data": ["seed/vendors.yaml"],
    "theme": "metropolis",
    "autonomy": [
        {"action_type": "save_file", "level": "L2", "connectors": ["google_drive"], "per_day": 5, "undo_window_s": 60}
    ],
}


def scenarios_module():
    import tilo_planning.scenarios as scenarios  # noqa: PLC0415

    return scenarios


def make_repo(root: pathlib.Path, *scenarios: dict[str, Any] | tuple[str, str]) -> pathlib.Path:
    """A tiny fake repo: the real connector registry and risk table (copied), one seed file, and the given scenario
    files. A `(filename, text)` pair writes raw text; a dict is dumped to `<id>.yaml`."""
    (root / "config" / "scenarios").mkdir(parents=True, exist_ok=True)
    for name in ("connectors.yaml", "autonomy.yaml"):
        shutil.copy(REPO_ROOT / "config" / name, root / "config" / name)
    (root / "seed").mkdir(exist_ok=True)
    (root / "seed" / "vendors.yaml").write_text("vendors:\n  - name: Fictional Vendor One\n", encoding="utf-8")
    (root / "seed" / "prices.csv").write_text("vendor,monthly\nFictional Vendor One,10\n", encoding="utf-8")
    for item in scenarios:
        name, text = item if isinstance(item, tuple) else (f"{item['id']}.yaml", yaml.safe_dump(item))
        (root / "config" / "scenarios" / name).write_text(text, encoding="utf-8")
    return root


def variant(**changes: Any) -> dict[str, Any]:
    scenario = {**GOOD, **changes}
    return {k: v for k, v in scenario.items() if v is not None}


@pytest.fixture()
def repo(tmp_path: pathlib.Path) -> pathlib.Path:
    return make_repo(tmp_path / "repo", GOOD)


# --- loading: everything a scenario preloads comes from the file --------------------------------------------------


def test_FR_INT_11_loader_preloads_skills_connectors_seed_data_autonomy_and_theme(repo):
    s = scenarios_module()

    scenario = s.load_scenario("TS-91", repo_root=repo)

    assert scenario.id == "TS-91" and scenario.title == "Fictional vendor comparison"
    assert list(scenario.skills) == ["vendor-research", "deck-drafting"]
    assert list(scenario.connectors) == ["google_drive"]
    assert [pathlib.Path(p).name for p in scenario.seed_data] == ["vendors.yaml"]
    assert all(pathlib.Path(p).is_absolute() and pathlib.Path(p).is_file() for p in scenario.seed_data)
    assert scenario.theme == "metropolis"
    assert len(scenario.autonomy) == 1 and scenario.autonomy[0]["action_type"] == "save_file"


def test_FR_INT_11_a_second_scenario_loads_through_the_same_loader_with_no_code_change(tmp_path):
    other = variant(
        id="TS-92",
        title="Fictional inbox triage",
        skills=["inbox-triage"],
        connectors=["gmail"],
        seed_data=["seed/prices.csv"],
        theme="harbour",
        autonomy=[{"action_type": "create_draft", "level": "L1", "connectors": ["gmail"]}],
    )
    root = make_repo(tmp_path / "repo", GOOD, other)
    s = scenarios_module()

    first, second = s.load_scenario("TS-91", repo_root=root), s.load_scenario("TS-92", repo_root=root)

    assert (first.id, second.id) == ("TS-91", "TS-92")
    assert list(second.skills) == ["inbox-triage"] and list(second.connectors) == ["gmail"]
    assert second.theme == "harbour" and [pathlib.Path(p).name for p in second.seed_data] == ["prices.csv"]


def test_FR_INT_11_the_loader_never_changes_what_it_reads(repo):
    s = scenarios_module()
    path = repo / "config" / "scenarios" / "TS-91.yaml"
    before = path.read_bytes()

    first, second = s.load_scenario("TS-91", repo_root=repo), s.load_scenario("TS-91", repo_root=repo)

    assert path.read_bytes() == before
    assert list(first.skills) == list(second.skills) and first.autonomy == second.autonomy  # deterministic


def test_FR_INT_11_skills_are_checked_against_the_catalog_when_one_is_given(repo):
    s = scenarios_module()

    ok = s.load_scenario("TS-91", repo_root=repo, skill_ids={"vendor-research", "deck-drafting", "other-skill"})
    assert list(ok.skills) == ["vendor-research", "deck-drafting"]
    with pytest.raises(s.ScenarioError, match="deck-drafting"):
        s.load_scenario("TS-91", repo_root=repo, skill_ids={"vendor-research"})


# --- loading: a bad file is refused with a reason, never half-loaded ----------------------------------------------


@pytest.mark.parametrize(
    ("change", "needle"),
    [
        ({"connectors": ["no_such_connector"]}, "no_such_connector"),
        ({"seed_data": ["seed/missing.yaml"]}, "missing.yaml"),
        ({"seed_data": ["../outside.yaml"]}, "outside"),
        ({"seed_data": ["/etc/hosts"]}, "hosts"),
        ({"skills": ["Not A Skill Id"]}, "skill"),
        ({"theme": "../themes/evil"}, "theme"),
        ({"theme": None}, "theme"),
        ({"title": None}, "title"),
        ({"unknown_key": 1}, "unknown_key"),
        ({"id": "TS-93"}, "ts-91"),  # the file's id must equal its file name
    ],
)
def test_FR_INT_11_an_invalid_scenario_is_refused_with_the_reason(tmp_path, change, needle):
    s = scenarios_module()
    root = make_repo(tmp_path / "repo", GOOD)
    bad = variant(**change)
    (root / "config" / "scenarios" / "TS-91.yaml").write_text(yaml.safe_dump(bad), encoding="utf-8")

    with pytest.raises(s.ScenarioError) as raised:
        s.load_scenario("TS-91", repo_root=root)

    assert needle.lower() in str(raised.value).lower()


@pytest.mark.parametrize("scenario_id", ["TS-404", "../config/autonomy", "..", "a/b", "", "TS-91\x00", "TS 91"])
def test_FR_INT_11_an_unknown_or_hostile_scenario_id_never_reads_outside_config_scenarios(repo, scenario_id):
    s = scenarios_module()

    with pytest.raises(s.ScenarioError):
        s.load_scenario(scenario_id, repo_root=repo)


@pytest.mark.parametrize(
    "text", ["", "- just\n- a list\n", "id: [unclosed", "&a {id: TS-91, b: *a}", "id: !!python/name:os.system\n"]
)
def test_FR_INT_11_a_malformed_scenario_file_is_a_scenario_error_not_a_crash(tmp_path, text):
    s = scenarios_module()
    root = make_repo(tmp_path / "repo", ("TS-91.yaml", text))

    with pytest.raises(s.ScenarioError):
        s.load_scenario("TS-91", repo_root=root)


# --- autonomy: a scenario can pre-authorise nothing a person must decide (PRD 10.4, HR: T3 needs a person) ----------


def test_FR_INT_11_a_scenario_cannot_put_a_t3_action_above_l1(tmp_path):
    s = scenarios_module()
    risky = variant(
        autonomy=[{"action_type": "delete_file", "level": "L2", "connectors": ["google_drive"], "per_day": 1}]
    )
    root = make_repo(tmp_path / "repo", risky)

    with pytest.raises(s.ScenarioError, match="delete_file"):
        s.load_scenario("TS-91", repo_root=root)


def test_FR_INT_11_an_l2_or_l3_entry_needs_a_daily_limit(tmp_path):
    s = scenarios_module()
    no_limit = variant(autonomy=[{"action_type": "save_file", "level": "L3", "connectors": ["google_drive"]}])
    root = make_repo(tmp_path / "repo", no_limit)

    with pytest.raises(s.ScenarioError, match="per_day"):
        s.load_scenario("TS-91", repo_root=root)


def test_FR_INT_11_policy_connectors_must_come_from_the_scenarios_own_connectors(tmp_path):
    s = scenarios_module()
    stray = variant(autonomy=[{"action_type": "send_email", "level": "L1", "connectors": ["gmail"]}])
    root = make_repo(tmp_path / "repo", stray)  # the scenario lists google_drive only

    with pytest.raises(s.ScenarioError, match="gmail"):
        s.load_scenario("TS-91", repo_root=root)


def test_FR_INT_11_policies_materialise_as_schema_valid_policy_records_owned_by_the_person(repo):
    s = scenarios_module()
    scenario = s.load_scenario("TS-91", repo_root=repo)
    schema, registry = load_schema(REPO_ROOT, "policy"), build_registry(REPO_ROOT)

    policies = scenario.policies(owner=OWNER, at=AT)

    assert len(policies) == len(scenario.autonomy) == 1
    (policy,) = policies
    assert not errors_for(schema, policy, registry)
    assert (policy["owner"], policy["action_type"], policy["level"]) == (OWNER, "save_file", "L2")
    assert policy["limits"]["per_day"] == 5 and policy["undo_window_s"] == 60
    assert policy["scope"]["connectors"] == ["google_drive"]
    assert policy["created_by"] == {"by": OWNER, "at": AT}  # only the owner creates a policy (PRD 10.1)
    assert policy["history"][-1]["level"] == policy["level"] and policy["history"][0]["by"] == OWNER
    assert policy["expiry"] is None or policy["expiry"] > AT


def test_FR_INT_11_policy_ids_are_unique_across_entries_and_scenarios(tmp_path):
    s = scenarios_module()
    two = variant(
        autonomy=[
            {"action_type": "save_file", "level": "L1", "connectors": ["google_drive"]},
            {"action_type": "create_draft", "level": "L1", "connectors": ["google_drive"]},
        ]
    )
    root = make_repo(tmp_path / "repo", two, variant(id="TS-92"))

    first = s.load_scenario("TS-91", repo_root=root).policies(owner=OWNER, at=AT)
    second = s.load_scenario("TS-92", repo_root=root).policies(owner=OWNER, at=AT)

    ids = [p["id"] for p in (*first, *second)]
    assert len(ids) == len(set(ids)) == 3 and all(re.fullmatch(r"pol_[0-9a-z_]{1,48}", i) for i in ids)


_RISK = yaml.safe_load((REPO_ROOT / "config" / "autonomy.yaml").read_text(encoding="utf-8"))
_ACTIONS = sorted(_RISK["actions"])


@pytest.fixture(scope="module")
def property_root(tmp_path_factory) -> pathlib.Path:
    return make_repo(tmp_path_factory.mktemp("prop"), GOOD)


@settings(max_examples=60, deadline=None, suppress_health_check=[HealthCheck.function_scoped_fixture])
@given(action=st.sampled_from(_ACTIONS), level=st.sampled_from(["L0", "L1", "L2", "L3"]))
def test_FR_INT_11_property_no_scenario_policy_exceeds_its_tiers_max_level(property_root, action, level):
    """Invariant: a scenario loads only if every policy level is within `max_level` of the action's risk tier."""
    s = scenarios_module()
    entry = {"action_type": action, "level": level, "connectors": ["google_drive"], "per_day": 3}
    (property_root / "config" / "scenarios" / "TS-91.yaml").write_text(
        yaml.safe_dump(variant(autonomy=[entry])), encoding="utf-8"
    )
    tier = _RISK["actions"][action]
    allowed = int(level[1]) <= int(_RISK["max_level"][tier][1])

    if allowed:
        loaded = s.load_scenario("TS-91", repo_root=property_root)
        assert all(p["level"] == level for p in loaded.policies(owner=OWNER, at=AT))
    else:
        with pytest.raises(s.ScenarioError):
            s.load_scenario("TS-91", repo_root=property_root)


# --- the smoke test -----------------------------------------------------------------------------------------------


def test_FR_INT_11_smoke_test_passes_for_a_scenario_whose_references_all_resolve(repo):
    s = scenarios_module()
    scenario = s.load_scenario("TS-91", repo_root=repo)

    assert s.smoke_test(scenario, repo_root=repo) == []


def test_FR_INT_11_smoke_test_lists_a_seed_file_that_stopped_parsing(repo):
    s = scenarios_module()
    scenario = s.load_scenario("TS-91", repo_root=repo)
    (repo / "seed" / "vendors.yaml").write_text("vendors: [unclosed\n", encoding="utf-8")

    problems = s.smoke_test(scenario, repo_root=repo)

    assert problems and any("vendors.yaml" in p for p in problems)


def test_FR_INT_11_smoke_test_lists_a_connector_that_left_the_registry(repo):
    s = scenarios_module()
    scenario = s.load_scenario("TS-91", repo_root=repo)
    registry = yaml.safe_load((repo / "config" / "connectors.yaml").read_text(encoding="utf-8"))
    kept = [c for c in registry if c["id"] != "google_drive"]
    (repo / "config" / "connectors.yaml").write_text(yaml.safe_dump(kept), encoding="utf-8")

    problems = s.smoke_test(scenario, repo_root=repo)

    assert problems and any("google_drive" in p for p in problems)


# --- SC-01: the file ships, loads through the generic loader and passes its smoke test ----------------------------


def test_FR_INT_11_SC_01_file_loads_with_no_code_change_and_passes_its_smoke_test():
    s = scenarios_module()
    assert (REPO_ROOT / "config" / "scenarios" / "SC-01.yaml").is_file(), "config/scenarios/SC-01.yaml is missing"

    scenario = s.load_scenario("SC-01")  # default repo root, the shipped config

    assert scenario.id == "SC-01"
    assert len(scenario.skills) >= 1  # PRD 4.3: research skills (resolved against the catalog once FR-AGT-04 lands)
    sandbox_seeds = [p for p in scenario.seed_data if "sandbox-web/seed" in pathlib.Path(p).as_posix()]
    assert sandbox_seeds, "PRD 4.3: SC-01 needs the Sandbox Web seed"
    registry = yaml.safe_load((REPO_ROOT / "config" / "connectors.yaml").read_text(encoding="utf-8"))
    assert set(scenario.connectors) <= {c["id"] for c in registry}
    assert re.fullmatch(r"[a-z][a-z0-9_]{0,63}", scenario.theme)
    policies = scenario.policies(owner=OWNER, at=AT)
    schema, schemas = load_schema(REPO_ROOT, "policy"), build_registry(REPO_ROOT)
    assert all(not errors_for(schema, p, schemas) for p in policies)
    assert all(
        int(p["level"][1]) <= int(_RISK["max_level"][_RISK["actions"].get(p["action_type"], "T3")][1]) for p in policies
    )  # PRD 10.4: nothing a person must decide is pre-authorised
    assert s.smoke_test(scenario, repo_root=REPO_ROOT) == []


def test_FR_INT_11_every_shipped_scenario_file_loads_and_passes_its_smoke_test():
    s = scenarios_module()
    files = sorted((REPO_ROOT / "config" / "scenarios").glob("*.yaml"))
    assert files, "no scenario files under config/scenarios/"

    for path in files:
        scenario = s.load_scenario(path.stem)
        assert scenario.id == path.stem
        assert s.smoke_test(scenario, repo_root=REPO_ROOT) == [], path.name


def test_FR_INT_11_no_platform_source_names_a_scenario_id():
    """Root CLAUDE.md: no scenario-specific code. A scenario id in `packages/*/src` or `services/*/src` means
    the platform branches on a scenario; a scenario that needs code becomes a pillar requirement first."""
    pattern = re.compile(r"\bSC-\d{2}\b")
    roots = [*REPO_ROOT.glob("packages/*/src"), *REPO_ROOT.glob("services/*/src")]
    hits = [
        f"{path.relative_to(REPO_ROOT).as_posix()}:{n}"
        for root in roots
        for path in root.rglob("*.py")
        for n, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1)
        if pattern.search(line)
    ]

    assert hits == [], f"scenario ids found in platform source: {hits}"
