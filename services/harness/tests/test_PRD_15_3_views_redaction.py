"""PRD 15.3 (Firestore layout: `orgs/{org}/worlds/{world}/views/{scope}/events/{vseq:08d}`) and
the ticket brief's REQUIRED BEHAVIOUR item 7: server-side redaction views. "shared" holds only
`vis: "all"` events; a per-district scope holds `vis: "all"` plus events whose `vis` list names
that district. Each view has its own dense `vseq` starting at 1, the copy's `seq` field equals
`vseq`, `cause` is null unless the cause event is in that same view, every other field is
unchanged, and an event goes to no view its `vis` excludes.

`tilo_harness.views.redact`/`.scopes_for` are tested directly (pure-function unit tests), then
`WorldWriter.emit` end-to-end against a two-district layout (village_basic has only one
district, D1, which cannot show scope exclusivity -- see conftest.two_district_layout).
"""

from __future__ import annotations

from conftest import make_memory_writer
from tilo_harness.validator import EventValidator
from tilo_harness.views import redact, scopes_for


def _district_ids_in_order(layout: dict) -> list[str]:
    return [district["id"] for level in layout["semantic"]["levels"] for district in level["districts"]]


def test_PRD_15_3_scopes_for_is_shared_plus_each_layout_district(village_basic_layout, two_district_layout):
    assert scopes_for(village_basic_layout) == ["shared", *_district_ids_in_order(village_basic_layout)]
    assert scopes_for(two_district_layout) == ["shared", *_district_ids_in_order(two_district_layout)]


def _base_event(**overrides) -> dict:
    event = {
        "v": "1.0",
        "id": "01JB5VQ0000000000000000900",
        "seq": 5,
        "ts": "2026-09-29T09:30:00.000Z",
        "world_id": "w_two_district_test",
        "run_id": "r_test_1",
        "type": "agent.idle",
        "actor": "A_l1",
        "target": "B1",
        "level": "L1",
        "district": "D1",
        "item": None,
        "severity": "info",
        "credits": 0,
        "summary": "The Lead is waiting for work.",
        "cause": None,
        "vis": "all",
        "authz": None,
        "data": {},
        "trace": {
            "model_role": None,
            "profile": None,
            "tokens_in": None,
            "tokens_out": None,
            "tool": None,
            "latency_ms": None,
            "archive_ref": None,
        },
    }
    event.update(overrides)
    return event


def test_PRD_15_3_redact_vis_all_appears_in_every_scope(two_district_layout):
    event = _base_event(vis="all")
    for scope in scopes_for(two_district_layout):
        copy = redact(event, scope, 1, set())
        assert copy is not None, f"vis='all' must appear in scope {scope!r}"


def test_PRD_15_3_redact_district_scoped_event_is_hidden_from_scopes_its_vis_excludes(two_district_layout):
    event = _base_event(vis=["D1"], district="D1")
    assert redact(event, "D1", 1, set()) is not None
    assert redact(event, "shared", 1, set()) is None, "shared holds only vis='all' events"
    assert redact(event, "D2", 1, set()) is None, "an event whose vis excludes D2 must not appear there"


def test_PRD_15_3_redact_copy_seq_equals_vseq_and_does_not_mutate_the_original(two_district_layout):
    event = _base_event(vis="all")
    copy = redact(event, "shared", 7, set())
    assert copy["seq"] == 7
    assert event["seq"] == 5, "redact must not mutate the original event"


def test_PRD_15_3_redact_nulls_cause_when_the_cause_event_is_not_in_this_view(two_district_layout):
    event = _base_event(vis="all", cause="01JB5VQ0000000000000000800")
    copy = redact(event, "shared", 2, view_ids=set())
    assert copy["cause"] is None


def test_PRD_15_3_redact_keeps_cause_when_the_cause_event_is_in_this_view(two_district_layout):
    cause_id = "01JB5VQ0000000000000000800"
    event = _base_event(vis="all", cause=cause_id)
    copy = redact(event, "shared", 2, view_ids={cause_id})
    assert copy["cause"] == cause_id


def test_PRD_15_3_redact_changes_only_seq_and_cause_every_other_field_matches(two_district_layout):
    event = _base_event(vis="all", cause="01JB5VQ0000000000000000800")
    copy = redact(event, "shared", 9, view_ids=set())
    assert copy == dict(event, seq=9, cause=None)


def test_PRD_15_3_every_redacted_copy_validates_against_the_event_contract(repo_root, two_district_layout):
    validator = EventValidator.from_repo(repo_root)
    event = _base_event(vis="all", cause="01JB5VQ0000000000000000800")
    for scope in scopes_for(two_district_layout):
        copy = redact(event, scope, 3, set())
        assert copy is not None
        problems = validator.problems(copy)
        assert problems == [], f"redacted copy for scope {scope!r} must itself validate: {problems}"


# --- end to end through WorldWriter: dense per-scope vseq, hidden events absent -----------


def test_PRD_15_3_views_are_dense_per_scope_and_hide_events_their_vis_excludes(two_district_layout):
    writer, store = make_memory_writer(two_district_layout, world_id="w_two_district_test")

    e1 = writer.emit(type="agent.idle", actor="A_dir", target="A_dir", summary="Director is idle.", data={})
    e2 = writer.emit(
        type="agent.idle",
        actor="A_l1",
        target="B1",
        level="L1",
        district="D1",
        vis=["D1"],
        cause=e1["id"],
        summary="Alpha's Lead is idle.",
        data={},
    )
    e3 = writer.emit(
        type="agent.idle",
        actor="A_l2",
        target="B2",
        level="L1",
        district="D2",
        vis=["D2"],
        cause=e2["id"],
        summary="Beta's Lead is idle.",
        data={},
    )
    e4 = writer.emit(
        type="agent.idle", actor="A_dir", target="A_dir", cause=e3["id"], summary="Director is idle again.", data={}
    )

    shared = store.read_view("org_demo", "w_two_district_test", "shared")
    d1 = store.read_view("org_demo", "w_two_district_test", "D1")
    d2 = store.read_view("org_demo", "w_two_district_test", "D2")

    assert [e["id"] for e in shared] == [e1["id"], e4["id"]], "shared must hold only vis='all' events"
    assert [e["id"] for e in d1] == [e1["id"], e2["id"], e4["id"]]
    assert [e["id"] for e in d2] == [e1["id"], e3["id"], e4["id"]]

    for scope, view in (("shared", shared), ("D1", d1), ("D2", d2)):
        assert [e["seq"] for e in view] == list(range(1, len(view) + 1)), (
            f"scope {scope!r} must have its own dense vseq with copy seq == vseq, got {[e['seq'] for e in view]}"
        )

    e3_in_d2 = next(e for e in d2 if e["id"] == e3["id"])
    assert e3_in_d2["cause"] is None, "e2 (e3's cause) is absent from D2's view, so the D2 copy must null cause"

    e2_in_d1 = next(e for e in d1 if e["id"] == e2["id"])
    assert e2_in_d1["cause"] == e1["id"], "e1 (e2's cause) is present in D1's view, so the D1 copy keeps cause"

    e4_in_shared = next(e for e in shared if e["id"] == e4["id"])
    assert e4_in_shared["cause"] is None, "e3 (e4's cause) is absent from shared, so the shared copy must null cause"
