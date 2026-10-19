"""PPL-11b fixtures check (FR-PA-13, FR-PA-14, FR-PA-17, FR-PA-19): the org, plates, sets and fakes the other
PPL-11b test files rely on are valid against the contracts and the REAL `tilo_people` oracle. These tests pass
today (they need no assistant code); if one fails, the fixtures changed under the other tests.
"""

from __future__ import annotations

import datetime as dt
import json

import pytest
from _ppl11b_lib import (
    CALL_COST,
    FIXTURES,
    NOW,
    OMAR,
    ORG,
    PRIYA,
    SAM,
    TODAY,
    WORST_CASE,
    AccessSpy,
    ArchiveRig,
    ScriptedProvider,
    ask_body,
    build_world,
    directory_of,
    expected_facts,
    fingerprint_of,
    fuzz_replies,
    intent_expected,
    is_plain,
    load_intents,
    load_questions,
    make_plate,
    make_providers_config,
    make_router,
    plate_buggy,
    plate_injection,
    plate_lena,
    plate_s0,
    plate_s1,
    plate_s2,
    s1_rows,
)
from tilo_people import access
from tilo_policy.schemas import conforms

PLATES = {
    "s0": plate_s0,
    "s1": plate_s1,
    "injection": plate_injection,
    "buggy": plate_buggy,
    "lena": lambda: plate_lena(),
}


@pytest.mark.parametrize("name", sorted(PLATES))
def test_PPL_11b_fixtures_plates_conform_to_the_plate_contract(name):
    plate = PLATES[name]()
    assert conforms("plate.schema.json", plate), name
    assert plate["fingerprint"] == fingerprint_of(plate["rows"])


def test_PPL_11b_fixtures_s2_has_14_rows_and_conforms():
    world = build_world()
    plate = plate_s2(world)
    assert len(plate["rows"]) == 14 and conforms("plate.schema.json", plate)
    assert len(plate_s2(build_world(long_titles=True))["rows"][0]["title"]) == 140


def test_PPL_11b_fixtures_s1_groups_reasons_and_boundaries():
    rows = plate_s1()["rows"]
    assert {r["reason"] for r in rows} == {
        "gate",
        "consent",
        "blocked",
        "question",
        "meeting_card",
        "run",
        "work_item",
        "mail_reply",
        "pin_owner",
        "pin_tagged",
        "calendar",
    }
    assert {r["group"] for r in rows} == {"attention", "overdue", "soon", "rest"}
    assert any(r["flagged"] for r in rows)
    for word in ("rate", "sheet", "budget", "launch", "notes"):  # the title-matching words are in exactly one title
        assert sum(word in (r["title"] or "").lower() for r in rows) == 1, word
    within = [
        r
        for r in rows
        if r["reason"] != "calendar"
        and r["at"]
        and dt.datetime(2026, 10, 5, 10)
        <= dt.datetime.strptime(r["at"], "%Y-%m-%dT%H:%M:%S.%fZ")
        <= dt.datetime(2026, 10, 6, 10)
    ]
    assert len(within) >= 1
    assert [r for r in rows if r["reason"] == "calendar"][0]["at"] == "2026-10-06T09:30:00.000Z"
    # PE-28: group codes by `today`
    soon_limit = (dt.date.fromisoformat(TODAY) + dt.timedelta(days=2)).isoformat()
    for r in rows:
        if r["reason"] in ("gate", "consent", "blocked"):
            want = "attention"
        elif r["due"] is not None and r["due"] < TODAY:
            want = "overdue"
        elif (r["due"] is not None and r["due"] <= soon_limit) or r["reason"] in (
            "calendar",
            "question",
            "meeting_card",
        ):
            want = "soon"
        else:
            want = "rest"
        assert r["group"] == want, r["ref"]


def test_PPL_11b_fixtures_the_plate_cut_at_ten_claim_lines_falls_inside_a_group():
    rows = plate_s1()["rows"]
    assert rows[9]["group"] == rows[10]["group"], (
        "a truncation boundary inside a group keeps the header rule unambiguous"
    )


def test_PPL_11b_fixtures_visibility_truth_table_under_the_real_oracle(monkeypatch):
    world = build_world()
    directory = directory_of(world)
    spy = AccessSpy(monkeypatch)

    def readable(actor, kind_store, record_kind, rid):
        stored = getattr(world.stores, kind_store).get(ORG, rid)
        assert stored is not None, rid
        request = access.AccessRequest(
            actor=actor, action="read_full", record_kind=record_kind, record=stored.record, now=NOW
        )
        return access.read(request, directory) is not None

    for kind_store, record_kind, rid in (
        ("work_items", "work_item", "wi_budget_notes"),
        ("work_items", "work_item", "wi_s2_14"),
        ("pins", "pinboard_item", "pb_vendor_review"),
        ("pins", "pinboard_item", "pb_kickoff"),
        ("pins", "pinboard_item", "pb_flagged"),
        ("pins", "pinboard_item", "pb_sam_team1"),
        ("pins", "pinboard_item", "pb_sam_personal"),
        ("calendar", "calendar_entry", "ce_plan1"),
        ("meetings", "meeting", "mt_samsync1"),
        ("persons", "person", SAM),
        ("calendar", "calendar_entry", "ce_priya_shared"),  # shared with tm_launch: readable, never on Sam's plate
    ):
        assert readable(SAM, kind_store, record_kind, rid), f"Sam must read {rid}"
    for kind_store, record_kind, rid in (
        ("work_items", "work_item", "wi_priya_1"),
        ("work_items", "work_item", "wi_sam_proposed"),
        ("pins", "pinboard_item", "pb_priya_personal"),
        ("pins", "pinboard_item", "pb_priya_proposed"),
        ("calendar", "calendar_entry", "ce_priya_private"),
        ("meetings", "meeting", "mt_priya1"),
        ("persons", "person", PRIYA),
        ("persons", "person", OMAR),
    ):
        assert not readable(SAM, kind_store, record_kind, rid), f"Sam must NOT read {rid}"
    assert not readable("u_lena", "pins", "pinboard_item", "pb_kickoff"), "Lena left tm_launch"
    assert len(spy.reads) >= 18


def test_PPL_11b_fixtures_the_other_org_is_invisible_to_the_org_listing():
    world = build_world()
    assert {s.record["id"] for s in world.stores.persons.list(ORG)} == {"u_owner", SAM, PRIYA, OMAR, "u_lena"}
    assert world.stores.work_items.get(ORG, "wi_other_org") is None


def test_PPL_11b_fixtures_plain_data_helper_rejects_subclasses():
    class S(str):
        pass

    assert is_plain({"a": ["b", 1, None]}) and not is_plain({"a": S("b")}) and not is_plain({S("a"): "b"})


def test_PPL_11b_fixtures_oracle_matches_the_spec_cases():
    rows = plate_s1()["rows"]
    plate = expected_facts("plate", rows)
    claims = [ln for ln in plate.lines if ln[1] is not None]
    assert len(claims) == 10 and plate.lines[-1] == ("More on My plate.", None)
    assert plate.ui_action == {"kind": "navigate", "route": "plate", "target": None}
    cal = expected_facts("calendar_today", rows)
    assert cal.lines[1][0] == "15:00 Team planning"
    assert all(expected_facts(q["intent"], []).outcome == "declined" for q in load_questions())
    s2 = expected_facts("plate", plate_s2(build_world())["rows"])
    assert len([ln for ln in s2.lines if ln[1] is not None]) == 10 and s2.ui_action is not None
    narrowed = expected_facts("tasks", rows, narrow_title="Launch site refresh")
    assert [ln[0] for ln in narrowed.lines] == ["Your tasks:", "Launch site refresh: blocked"]


def test_PPL_11b_fixtures_acceptance_sets_have_the_spec_sizes():
    questions, intents = load_questions(), load_intents()
    assert [q["n"] for q in questions] == list(range(1, 21))
    assert [i["n"] for i in intents] == list(range(1, 31))
    assert sum(i["by"] == "rules" for i in intents) == 28
    for intent in intents:
        assert conforms("ui_action.schema.json", intent_expected(intent)), intent["n"]
    assert (FIXTURES / "questions.json").is_file()


def test_PPL_11b_fixtures_fuzz_has_200_replies_and_none_is_a_valid_decision():
    replies = fuzz_replies()
    assert len(replies) == 200 and len({t for _, t in replies}) >= 190
    # none of them is, as a whole, one of the three legal shapes with legal values
    for category, text in replies:
        try:
            value = json.loads(text, object_pairs_hook=lambda pairs: pairs)
        except (ValueError, RecursionError):
            continue
        assert category != "extra_keys" or isinstance(value, list), text[:80]


def test_PPL_11b_fixtures_provider_prices_give_the_documented_costs():
    import pathlib  # noqa: PLC0415
    import tempfile  # noqa: PLC0415

    from tilo_providers.interfaces import GenerateRequest  # noqa: PLC0415

    with tempfile.TemporaryDirectory() as tmp:
        providers = make_providers_config(pathlib.Path(tmp))
        assert providers.credits((8000 * 1.0 + 1000 * 12.0) / 1e6) == WORST_CASE
        provider = ScriptedProvider("ast-main", ['{"choice": "decline"}'])
        result = make_router(providers, provider).generate(
            "assistant", GenerateRequest(prompt="hello there", json_mode=True), budget=WORST_CASE
        )
        assert provider.calls[0].max_output_tokens == 1000
        assert WORST_CASE - result.budget == pytest.approx(CALL_COST)


def test_PPL_11b_fixtures_archive_rig_chains_and_redacts():
    rig = ArchiveRig()
    key = "".join(["s", "k", "-", "A1b2C3d4E5f6G7h8I9j0"])
    archive = rig.open_archive(org_id=ORG, run_id="r_desk_x1")
    ref = archive.append("channel_in", {"question": f"token {key}"})
    assert ref == "r_desk_x1/1" and key not in json.dumps(rig.records("r_desk_x1"))


def test_PPL_11b_fixtures_ask_body_shape():
    assert ask_body("hi") == {"question": "hi", "context": {"route": "/plate", "record": None, "label": "Panel"}}
    assert make_plate(SAM, s1_rows())["user"] == SAM
