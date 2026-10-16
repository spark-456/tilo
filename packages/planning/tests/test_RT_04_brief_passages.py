"""RT-04 (ADR-0049, R2): the Director's brief request carries retrieved passages only as fenced data appended to the
user turn; with none it is byte-identical to before (B-007); a memory source is kept only if code sent that id."""

from __future__ import annotations

from datetime import date

from tilo_planning.brief import brief_request, vet_sources

TODAY = date(2026, 10, 16)
TASK = "Draft the Acme supplier review agenda."
BLOCK = "\n\n<<<PASSAGES\n[1] (id ch_aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa) Notes\nreview is thursday\nPASSAGES>>>\n"


def test_RT_04_no_passages_is_byte_identical_and_a_block_is_appended_after_the_task():
    plain = brief_request(TASK, today=TODAY)
    assert brief_request(TASK, today=TODAY, passages="") == plain
    grounded = brief_request(TASK, today=TODAY, passages=BLOCK)
    assert grounded.prompt == plain.prompt + BLOCK  # appended, never inside the TASK block
    assert grounded.system == plain.system  # EFF-04: the system prompt is static
    assert (grounded.json_mode, grounded.response_schema) == (plain.json_mode, plain.response_schema)


def test_RT_04_a_memory_source_is_kept_only_when_code_sent_that_id():
    sent = frozenset({"ch_" + "a" * 32})
    sources = [
        {"kind": "memory", "ref": "ch_" + "a" * 32},
        {"kind": "memory", "ref": "ch_" + "b" * 32},  # an id the model made up, or another person's chunk
        {"kind": "file", "ref": "art_x"},
        {"kind": "web", "ref": "prices"},
    ]
    assert [s["ref"] for s in vet_sources(sources, memory_ids=sent)] == ["ch_" + "a" * 32, "prices"]
    assert [s["ref"] for s in vet_sources(sources)] == ["prices"]  # none sent: as before
