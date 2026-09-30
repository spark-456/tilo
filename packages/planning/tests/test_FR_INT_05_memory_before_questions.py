"""FR-INT-05 (PRD 7.1): "Memory is checked before asking: known preferences and past answers are
applied, not asked again." Acceptance test: "Given a stored preference for PDF output, when a
similar task arrives, then no format question appears and the brief cites the preference." PRD
13.1 memory layers: preferences are "applied in planning" and "a cached result is reused only if
[...] every reuse emits `memory.hit`".

Public interface: `tilo_planning.memory.MemoryLookup`, `.InMemoryPreferenceStore`,
`tilo_planning.questions.generate_questions` (same module FR-INT-04 tests exercise, here with a
memory hit present).
"""

from __future__ import annotations

from _planning_contracts_lib import assert_valid_brief, assert_valid_event, load_brief_fixture, sample_event_base
from tilo_planning.memory import InMemoryPreferenceStore
from tilo_planning.questions import generate_questions


def test_FR_INT_05_stored_preference_removes_the_question_and_brief_cites_it(repo_root, registry):
    brief = load_brief_fixture("valid_market_scan")
    memory = InMemoryPreferenceStore()
    memory.set_preference(
        "deliverables",
        "pdf",
        ref="pref_output_format_pdf",
        recorded_at="2026-09-01T09:00:00.000Z",
        origin_cost=2.0,
        lookup_cost=0.5,
    )

    result = generate_questions(brief, ["deliverables", "audience"], memory=memory, base=sample_event_base(), seq=2)

    fields_asked = {q.field for q in result.questions}
    assert "deliverables" not in fields_asked, "FR-INT-05: a known preference is applied, not asked again"
    assert "audience" in fields_asked, "test setup: audience has no stored preference, so it is still asked"

    applied = [p for p in result.brief["applied_preferences"] if p["field"] == "deliverables"]
    assert len(applied) == 1
    assert applied[0]["value"] == "pdf"
    assert applied[0]["citation"] == {
        "kind": "preference",
        "ref": "pref_output_format_pdf",
        "recorded_at": "2026-09-01T09:00:00.000Z",
    }
    assert_valid_brief(repo_root, registry, result.brief)

    assert len(result.memory_hit_events) == 1
    hit_event = result.memory_hit_events[0]
    assert hit_event["type"] == "memory.hit"
    assert hit_event["data"] == {"origin_cost": 2.0, "lookup_cost": 0.5, "saved": 1.5}
    assert_valid_event(repo_root, registry, hit_event)


def test_FR_INT_05_memory_is_checked_before_questions_are_generated(repo_root, registry):
    brief = load_brief_fixture("valid_market_scan")
    memory = InMemoryPreferenceStore()  # nothing stored, but every candidate field must still be looked up first
    lookup_calls: list[set[str]] = []
    original_lookup = memory.lookup

    def _spying_lookup(brief_arg, candidate_fields):
        lookup_calls.append(set(candidate_fields))
        return original_lookup(brief_arg, candidate_fields)

    memory.lookup = _spying_lookup  # type: ignore[method-assign]

    generate_questions(brief, ["deadline", "audience"], memory=memory, base=sample_event_base(), seq=2)

    assert lookup_calls, "FR-INT-05: memory must be consulted before questions are ranked and capped"
    assert lookup_calls[0] == {"deadline", "audience"}
