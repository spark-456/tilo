"""FR-AGT-04 acceptance suite: 10 v0 skills with golden tests passing.

PRD sources: 8.2 (expert skill library folder shape), 8.1 (roles), 8.6 (FR-AGT-04
and neighbours), 11.3 (triage categories), 11.4 (drafting and sending), 12.4
(deliverables: charts are data references, never drawn by a model), 13.3
(provenance / claims ledger), 16.3 (prompt-injection defence in depth), 22.2 D-07
(expert skills are versioned, approved folders).

Contract: contracts/skill.schema.json (skill.yaml shape).

These tests fail today because no skill exists yet under skills/. They must not be
weakened once skills are built; a builder makes the skills conform to these checks.
"""

from __future__ import annotations

import pytest
from conftest import (
    MALFORMED_OUTPUTS,
    REQUIRED_SKILL_CASE_IDS,
    REQUIRED_SKILL_MD_HEADINGS,
    REQUIRED_SKILLS,
    SIDE_EFFECT_TOKENS,
    SKILLS_DIR,
    UNTRUSTED_READER_CASE_IDS,
    UNTRUSTED_READER_SKILLS,
    assert_stdlib_or_lib_only_imports,
    assert_valid_2020_12_schema,
    budget_python_files,
    code_line_count,
    example_pairs,
    extract_level2_headings,
    extract_quality_bar_check_ids,
    fail_check_id,
    golden_case_paths,
    import_check_module,
    is_pass_case,
    load_json,
    load_yaml,
    skill_dir,
)
from jsonschema import Draft202012Validator

# ---------------------------------------------------------------------------
# 1. The ten required skills exist, in their stated domains.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("domain,skill_id", REQUIRED_SKILLS, ids=REQUIRED_SKILL_CASE_IDS)
def test_FR_AGT_04_required_skill_folder_exists(domain, skill_id):
    d = skill_dir(domain, skill_id)
    assert d.is_dir(), f"missing required v0 skill folder: skills/{domain}/{skill_id}/ (PRD 8.2, FR-AGT-04)"
    for name in ("SKILL.md", "skill.yaml", "check.py"):
        assert (d / name).is_file(), f"skills/{domain}/{skill_id}/{name} is required (PRD 8.2)"
    for name in ("examples", "tests/golden"):
        assert (d / name).is_dir(), f"skills/{domain}/{skill_id}/{name}/ is required (PRD 8.2)"


# ---------------------------------------------------------------------------
# 2. skill.yaml validates against contracts/skill.schema.json; folder matches id/domain.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("domain,skill_id", REQUIRED_SKILLS, ids=REQUIRED_SKILL_CASE_IDS)
def test_FR_AGT_04_skill_yaml_valid_against_contract(domain, skill_id, contract_validator):
    data = load_yaml(skill_dir(domain, skill_id) / "skill.yaml")
    errors = sorted(contract_validator.iter_errors(data), key=lambda e: e.path)
    assert not errors, "skill.yaml fails contracts/skill.schema.json:\n" + "\n".join(
        f"  {list(e.path)}: {e.message}" for e in errors
    )
    assert data.get("id") == skill_id, f"skill.yaml id {data.get('id')!r} must match its folder name {skill_id!r}"
    assert data.get("domain") == domain, (
        f"skill.yaml domain {data.get('domain')!r} must match its parent folder {domain!r}"
    )
    assert data.get("version") == "0.1.0", "v0 skills ship as version 0.1.0 (ticket brief)"
    assert data.get("author") == "Tilo build (drafted by Claude Code)", (
        "author must record who drafted the skill (ticket brief)"
    )
    assert data.get("reviewer") == "Pending domain expert review", (
        "no domain expert has signed off yet (PRD 8.2 governance, D-07); never invent a person's name (ticket brief)"
    )
    assert len(data.get("description", "")) <= 160
    assert "\n" not in data.get("description", "")


# ---------------------------------------------------------------------------
# 3. inputs / outputs are valid JSON Schema 2020-12 object schemas.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("domain,skill_id", REQUIRED_SKILLS, ids=REQUIRED_SKILL_CASE_IDS)
def test_FR_AGT_04_skill_io_schemas_are_valid_2020_12(domain, skill_id):
    data = load_yaml(skill_dir(domain, skill_id) / "skill.yaml")
    inputs = data.get("inputs")
    outputs = data.get("outputs")
    assert_valid_2020_12_schema(inputs, what=f"skills/{domain}/{skill_id}/skill.yaml inputs")
    assert_valid_2020_12_schema(outputs, what=f"skills/{domain}/{skill_id}/skill.yaml outputs")
    assert inputs.get("type") == "object", "inputs must be an object schema (contracts/skill.schema.json)"
    assert outputs.get("type") == "object", "outputs must be an object schema (contracts/skill.schema.json)"


# ---------------------------------------------------------------------------
# 4. SKILL.md has the five exact level-2 headings and lists every check id.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("domain,skill_id", REQUIRED_SKILLS, ids=REQUIRED_SKILL_CASE_IDS)
def test_FR_AGT_04_skill_md_has_required_headings(domain, skill_id):
    path = skill_dir(domain, skill_id) / "SKILL.md"
    if not path.is_file():
        pytest.fail(f"missing required file: {path}")
    text = path.read_text(encoding="utf-8")
    headings = extract_level2_headings(text)
    for required in REQUIRED_SKILL_MD_HEADINGS:
        assert required in headings, f"SKILL.md is missing the exact level-2 heading '## {required}' (ticket brief)"


@pytest.mark.parametrize("domain,skill_id", REQUIRED_SKILLS, ids=REQUIRED_SKILL_CASE_IDS)
def test_FR_AGT_04_skill_md_quality_bar_lists_every_check_id(domain, skill_id):
    path = skill_dir(domain, skill_id) / "SKILL.md"
    if not path.is_file():
        pytest.fail(f"missing required file: {path}")
    text = path.read_text(encoding="utf-8")
    documented_ids = extract_quality_bar_check_ids(text)

    golden_paths = golden_case_paths(domain, skill_id)
    check_ids_in_goldens = set()
    for p in golden_paths:
        case = load_json(p)
        cid = fail_check_id(case.get("expect"))
        if cid:
            check_ids_in_goldens.add(cid)

    assert documented_ids, (
        "SKILL.md's Quality bar section lists no check ids as inline code, e.g. "
        "`price-cites-source` (ticket brief: 'stable slugs listed in SKILL.md's Quality bar')"
    )
    missing = check_ids_in_goldens - documented_ids
    assert not missing, f"check id(s) used by failing goldens but not listed in Quality bar: {sorted(missing)}"


# ---------------------------------------------------------------------------
# 5. check.py: stdlib (+ skills/_lib) only, exposes check(), never raises on
#    malformed output (ticket FR-AGT-04 re-scope, point 3: "check.py files may
#    import only the standard library and skills/_lib").
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("domain,skill_id", REQUIRED_SKILLS, ids=REQUIRED_SKILL_CASE_IDS)
def test_FR_AGT_04_check_py_is_stdlib_or_lib_only(domain, skill_id):
    path = skill_dir(domain, skill_id) / "check.py"
    assert_stdlib_or_lib_only_imports(path)


@pytest.mark.parametrize("domain,skill_id", REQUIRED_SKILLS, ids=REQUIRED_SKILL_CASE_IDS)
def test_FR_AGT_04_check_py_exposes_check_function(domain, skill_id):
    module = import_check_module(domain, skill_id)
    assert callable(module.check)


@pytest.mark.parametrize("domain,skill_id", REQUIRED_SKILLS, ids=REQUIRED_SKILL_CASE_IDS)
def test_FR_AGT_04_check_py_fails_closed_on_malformed_output(domain, skill_id):
    module = import_check_module(domain, skill_id)
    goldens = golden_case_paths(domain, skill_id)
    sample_input = {}
    for p in goldens:
        case = load_json(p)
        if is_pass_case(case.get("expect")):
            sample_input = case.get("input", {})
            break

    for bad_output in MALFORMED_OUTPUTS:
        try:
            findings = module.check(sample_input, bad_output)
        except Exception as exc:  # noqa: BLE001 - the point is that nothing may raise
            pytest.fail(
                f"check() raised {exc!r} on malformed output {bad_output!r}; "
                "checkers must fail closed, not raise (ticket brief)"
            )
        assert isinstance(findings, list), "check() must always return a list of findings"
        assert findings, (
            f"check() returned an empty list for malformed output {bad_output!r}; "
            "malformed output must fail closed with at least one finding"
        )
        for finding in findings:
            assert isinstance(finding, dict) and "check" in finding and "detail" in finding, (
                f"each finding must be {{'check': ..., 'detail': ...}}, got {finding!r}"
            )


# ---------------------------------------------------------------------------
# 6. examples/ validate against the schemas and pass check.py.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("domain,skill_id", REQUIRED_SKILLS, ids=REQUIRED_SKILL_CASE_IDS)
def test_FR_AGT_04_examples_validate_and_pass_check(domain, skill_id):
    data = load_yaml(skill_dir(domain, skill_id) / "skill.yaml")
    input_validator = Draft202012Validator(data["inputs"])
    output_validator = Draft202012Validator(data["outputs"])
    module = import_check_module(domain, skill_id)

    pairs = example_pairs(domain, skill_id)
    assert pairs, f"skills/{domain}/{skill_id}/examples/ must contain at least one worked pair (PRD 8.2)"

    for input_path, output_path in pairs:
        example_input = load_json(input_path)
        example_output = load_json(output_path)

        in_errors = list(input_validator.iter_errors(example_input))
        assert not in_errors, f"{input_path.name} fails the skill's inputs schema: {in_errors[0].message}"

        out_errors = list(output_validator.iter_errors(example_output))
        assert not out_errors, f"{output_path.name} fails the skill's outputs schema: {out_errors[0].message}"

        findings = module.check(example_input, example_output)
        assert findings == [], f"example {input_path.name} does not meet the quality bar: {findings}"


# ---------------------------------------------------------------------------
# 7. tests/golden/: schema validity, expected verdict, coverage, check-id coverage.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("domain,skill_id", REQUIRED_SKILLS, ids=REQUIRED_SKILL_CASE_IDS)
def test_FR_AGT_04_golden_cases_give_expected_verdict(domain, skill_id):
    data = load_yaml(skill_dir(domain, skill_id) / "skill.yaml")
    input_validator = Draft202012Validator(data["inputs"])
    output_validator = Draft202012Validator(data["outputs"])
    module = import_check_module(domain, skill_id)

    goldens = golden_case_paths(domain, skill_id)
    assert goldens, f"skills/{domain}/{skill_id}/tests/golden/ must contain golden cases (PRD 8.2)"

    for path in goldens:
        case = load_json(path)
        assert "input" in case and "output" in case and "expect" in case, (
            f"{path.name} must be {{'input', 'output', 'expect'}}"
        )
        case_input = case["input"]
        case_output = case["output"]
        expect = case["expect"]

        in_errors = list(input_validator.iter_errors(case_input))
        assert not in_errors, f"{path.name} input fails the skill's inputs schema: {in_errors[0].message}"

        findings = module.check(case_input, case_output)
        assert isinstance(findings, list)

        if is_pass_case(expect):
            out_errors = list(output_validator.iter_errors(case_output))
            assert not out_errors, f"{path.name} (expect pass) output fails the outputs schema: {out_errors[0].message}"
            assert findings == [], f"{path.name} expected an empty findings list (pass) but got {findings}"
        else:
            expected_check_id = fail_check_id(expect)
            assert expected_check_id, f"{path.name} 'expect' must be 'pass' or {{'fail': '<check id>'}}, got {expect!r}"
            found_ids = {f.get("check") for f in findings}
            assert expected_check_id in found_ids, (
                f"{path.name} expected a finding with check id {expected_check_id!r}, got {sorted(found_ids)}"
            )


@pytest.mark.parametrize("domain,skill_id", REQUIRED_SKILLS, ids=REQUIRED_SKILL_CASE_IDS)
def test_FR_AGT_04_golden_coverage_at_least_2_pass_3_fail(domain, skill_id):
    goldens = golden_case_paths(domain, skill_id)
    pass_count = 0
    fail_count = 0
    for path in goldens:
        case = load_json(path)
        expect = case.get("expect")
        if is_pass_case(expect):
            pass_count += 1
        elif fail_check_id(expect):
            fail_count += 1
    assert pass_count >= 2, f"expected at least 2 passing golden cases, found {pass_count} (ticket brief)"
    assert fail_count >= 3, f"expected at least 3 failing golden cases, found {fail_count} (ticket brief)"


@pytest.mark.parametrize("domain,skill_id", REQUIRED_SKILLS, ids=REQUIRED_SKILL_CASE_IDS)
def test_FR_AGT_04_every_check_id_has_a_failing_golden(domain, skill_id):
    path = skill_dir(domain, skill_id) / "SKILL.md"
    if not path.is_file():
        pytest.fail(f"missing required file: {path}")
    documented_ids = extract_quality_bar_check_ids(path.read_text(encoding="utf-8"))
    assert documented_ids, "SKILL.md Quality bar must list at least one check id as inline code"

    goldens = golden_case_paths(domain, skill_id)
    covered_ids = set()
    for p in goldens:
        case = load_json(p)
        cid = fail_check_id(case.get("expect"))
        if cid:
            covered_ids.add(cid)

    missing = documented_ids - covered_ids
    assert not missing, f"check id(s) with no failing golden case: {sorted(missing)}"


# ---------------------------------------------------------------------------
# 8. Privilege separation (PRD 16.3): untrusted-content readers get no side-effect tools.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("domain,skill_id", UNTRUSTED_READER_SKILLS, ids=UNTRUSTED_READER_CASE_IDS)
def test_FR_AGT_04_untrusted_reader_skills_have_no_side_effect_tools(domain, skill_id):
    data = load_yaml(skill_dir(domain, skill_id) / "skill.yaml")
    tools = data.get("tools_allowed", [])
    offending = [t for t in tools if any(token in t for token in SIDE_EFFECT_TOKENS)]
    assert not offending, (
        f"{domain}/{skill_id} reads untrusted content and must get no side-effect tools "
        f"(PRD 16.3 privilege separation), but tools_allowed includes {offending}"
    )


# ---------------------------------------------------------------------------
# 9. Line budget (ticket FR-AGT-04 re-scope, point 4): hand-written Python across
#    skills/**/check.py and skills/_lib/*.py stays under 400 non-blank,
#    non-comment lines in total. Passes trivially before any of those files
#    exist; it exists to stop the checkers regrowing to the ~1,786 lines the
#    regex-based v0 attempt reached.
# ---------------------------------------------------------------------------


def test_FR_AGT_04_check_py_and_lib_line_budget_at_most_400():
    files = budget_python_files()
    total = sum(code_line_count(p) for p in files)
    breakdown = ", ".join(f"{p.relative_to(SKILLS_DIR.parent).as_posix()}={code_line_count(p)}" for p in files)
    assert total <= 400, (
        f"skills/**/check.py + skills/_lib/*.py total {total} non-blank, non-comment "
        f"lines, over the 400-line budget (ticket brief): {breakdown}"
    )
