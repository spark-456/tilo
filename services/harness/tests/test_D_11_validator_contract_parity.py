"""D-11 / PRD 9.3-9.5, 15.3: the harness validator (`tilo_harness.validator.EventValidator`)
runs contracts/event.rules.md's EV-01..EV-14 itself -- a service must not import from
scripts/ (root CLAUDE.md), so this cannot reuse scripts/contracts_events.py directly, but it
must agree with it on every fixture that ships in contracts/.

`EventValidator.problems(event, state=None)` is the event-level check (schema, EV-01, EV-02,
EV-04, EV-05, EV-06, EV-08, EV-09, and the state-independent half of EV-13 -- the same rules
scripts/contracts_events.py's `event_problems()` runs without a stream or a layout). The
stream- and layout-dependent rules (EV-10 seq/id, EV-11 cause, EV-12 layout ids, and the
layout half of EV-13) need a `WorldState`, whose own update API is not part of this ticket's
public surface (only `WorldState(layout: dict)` is); those rules are exercised end-to-end
through `WorldWriter.emit`/`.append` instead, in test_D_11_writer_seq_and_atomicity.py and
test_D_11_village_basic_stream_append.py. This split is this file's one resolved ambiguity
(see the test-writer report).
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from conftest import event_fixture_paths, load_json
from tilo_harness.validator import EventValidator

RULE_FILE = re.compile(r"^ev(\d{2})_")


@pytest.fixture(scope="module")
def validator(repo_root: Path) -> EventValidator:
    return EventValidator.from_repo(repo_root)


@pytest.mark.parametrize("path", event_fixture_paths("valid"), ids=lambda p: p.name)
def test_D_11_valid_event_fixtures_pass_the_validator(validator: EventValidator, path: Path) -> None:
    event = load_json(path)
    problems = validator.problems(event)
    assert problems == [], f"D-11: {path.name} should validate cleanly but got {problems}"


@pytest.mark.parametrize("path", event_fixture_paths("invalid"), ids=lambda p: p.name)
def test_D_11_invalid_event_fixtures_fail_schema_or_EV_02(validator: EventValidator, path: Path) -> None:
    event = load_json(path)
    problems = validator.problems(event)
    assert problems, f"D-11: {path.name} is in fixtures/events/invalid/ but the validator found no problem"
    assert any(p.startswith(("schema", "EV-02")) for p in problems), (
        f"D-11: {path.name} must fail event.schema.json or its data schema (problem must start with "
        f"'schema' or 'EV-02'), got {problems}"
    )


@pytest.mark.parametrize("path", event_fixture_paths("registry/invalid"), ids=lambda p: p.name)
def test_D_11_registry_invalid_fixtures_break_only_their_named_rule(validator: EventValidator, path: Path) -> None:
    match = RULE_FILE.match(path.name)
    assert match, f"D-11: {path.name} must be named ev<NN>_<slug>.json"
    rule = f"EV-{match.group(1)}"
    event = load_json(path)
    problems = validator.problems(event)

    assert not any(p.startswith(("schema", "EV-02")) for p in problems), (
        f"D-11: {path.name} must pass event.schema.json and its data schema (it only breaks {rule}), got {problems}"
    )
    assert any(p.startswith(rule) for p in problems), (
        f"D-11: {path.name} must fail with {rule} specifically (its filename says so), got {problems}"
    )


def test_D_11_every_problem_starts_with_schema_or_a_rule_id(validator: EventValidator) -> None:
    """contracts/event.rules.md: "a failing check names its rule" -- every problems() entry, across
    every fixture folder, starts with "schema" or "EV-<NN>", never a bare message."""
    rule_or_schema = re.compile(r"^(schema|EV-\d{2})\b")
    offenders: list[str] = []
    for kind in ("valid", "invalid", "registry/invalid"):
        for path in event_fixture_paths(kind):
            for problem in validator.problems(load_json(path)):
                if not rule_or_schema.match(problem):
                    offenders.append(f"{path.name}: {problem!r}")
    assert not offenders, f"D-11: problems not tagged 'schema'/'EV-NN': {offenders}"
