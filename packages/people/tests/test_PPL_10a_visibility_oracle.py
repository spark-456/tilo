"""PPL-10a: the visibility oracle `tilo_people.decide`, `project`, `read`, `Directory`, `case_request`
(contracts/people.rules.md PE-01 to PE-08, PE-11, PE-17 to PE-20; FR-PA-11, FR-CAL-06, FR-PB-02,
FR-MTG-01; BQ-PPL10-1, -3, -10, -11, -12). Spec: packages/people/tests/API.md section 1.

Privacy path: this file is adversarial on purpose. Every refusal below is a refusal of a request the
reference oracle (`tests/contracts/_people_lib.permits`) either refuses too, or (S1 to S5) wrongly
grants, or (G1, G2) cannot express.

Ambiguities settled here (PRD / rule in brackets; also listed in the hand-back):

- A: API.md shows `AccessRequest`, `Directory` and the other dataclasses without `repr=False`, but the
  "Rules for every module" and packages/people/CLAUDE.md forbid record text (titles, names, aliases,
  emails) in any repr. The rule wins: reprs of `AccessRequest` and `Directory` carry no record text.
  [people.rules.md PE-20; API.md "Rules for every module"]
- B: `decide(None, d)` and `decide(request, None)` refuse instead of raising ("never raises").
  [API.md decide]
"""

from __future__ import annotations

import copy
import dataclasses
import re
import time

import _ppl10_testlib as t
import pytest
from _ppl10_testlib import access, crossref, directory, errors, pl, text
from hypothesis import HealthCheck, Phase, given, settings
from hypothesis import strategies as st

SETTINGS = settings(
    max_examples=60,
    deadline=None,
    database=None,
    phases=(Phase.explicit, Phase.generate),  # no shrinking: a failing run reports at once
    suppress_health_check=[HealthCheck.too_slow],
)
GRANTS = {("person", "create"), ("meeting", "create")}  # G1, G2 (BQ-PPL10-3): the only grants beyond the reference


def _expected_view(case):
    request = case["request"]
    action = "read_" + request["view"] if request["action"] == "read" else request["action"]
    return action[5:] if action.startswith("read_") else None


def _is_read(case):
    return case["request"]["action"] == "read" or case["request"]["action"].startswith("read_")


VALID_READS = [(n, c) for n, c in t.VALID_CASES if _is_read(c)]
INVALID_READS = [(n, c) for n, c in t.INVALID_CASES if _is_read(c)]


# ---------------------------------------------------------------------------------------------
# 0. The shapes the API pins
# ---------------------------------------------------------------------------------------------
def test_PPL_10a_testlib_builders_are_schema_valid():
    """Guard for these tests themselves: every record the helpers build conforms to its schema."""
    from tilo_policy.schemas import conforms

    for p in t.world_persons():
        assert conforms("person.schema.json", p), p["id"]
    built = [
        ("work_item", t.own_item()),
        ("work_item", t.tilo_item()),
        ("work_item", t.proposed_tilo_item()),
        ("pinboard_item", t.team_pin()),
        ("pinboard_item", t.personal_pin()),
        ("pinboard_item", t.tilo_team_pin()),
        ("calendar_entry", t.entry()),
        ("calendar_entry", t.shared_entry()),
        ("calendar_entry", t.tilo_proposal()),
        ("meeting", t.meeting()),
        ("meeting", t.minuted_meeting()),
        ("mention", t.tag()),
    ]
    for kind, record in built:
        assert conforms(f"{kind}.schema.json", record), kind


def test_PPL_10a_PE_19_constants_and_dataclass_shapes_are_pinned():
    assert tuple(access.ACTIONS) == tuple(t.ACTIONS) and len(access.ACTIONS) == 14
    assert tuple(access.RECORD_KINDS) == t.RECORD_KINDS
    assert {k: tuple(v) for k, v in access.VIEW_FIELDS.items()} == t.VIEW_KEYS
    r = access.AccessRequest(actor="u_riya", action="read_full", record_kind="work_item", record={}, now=t.NOW)
    assert (r.meeting, r.work_item, r.source_owner, r.pin, r.mentions) == (None, None, None, None, ())
    with pytest.raises(dataclasses.FrozenInstanceError):
        r.actor = "u_owner"  # type: ignore[misc]
    assert access.Verdict(False, None) == access.Verdict(allowed=False, view=None)
    with pytest.raises(dataclasses.FrozenInstanceError):
        access.Verdict(False, None).allowed = True  # type: ignore[misc]


def test_PPL_10a_PE_19_errors_hierarchy():
    assert issubclass(errors.PeopleInputError, errors.PeopleError)
    assert issubclass(errors.PeopleInputError, ValueError)
    for name in ("AlreadyExists", "NotFound", "VersionConflict"):
        cls = getattr(errors, name)
        assert issubclass(cls, errors.PeopleError)
        assert not issubclass(cls, ValueError)
    assert issubclass(errors.PeopleError, Exception)


# ---------------------------------------------------------------------------------------------
# 1. text.clean_line (PE-24)
# ---------------------------------------------------------------------------------------------
def test_PPL_10a_PE_24_clean_line_removes_exactly_cc_cf_zl_zp_over_every_code_point():
    import unicodedata

    bad = {"Cc", "Cf", "Zl", "Zp"}
    points = [c for c in range(0x110000) if not 0xD800 <= c <= 0xDFFF]
    source = "".join(chr(c) for c in points)
    expected = "".join(chr(c) for c in points if unicodedata.category(chr(c)) not in bad)
    assert text.clean_line(source) == expected


@pytest.mark.parametrize(
    ("raw", "cleaned"),
    [
        (t.u(0x50, 0x200B, 0x72), "Pr"),  # zero-width space
        (t.u(0x50, 0x200D, 0x72), "Pr"),  # zero-width joiner is Cf
        (t.u(0x202E, 0x50, 0x202C, 0x72), "Pr"),  # bidi override and pop
        (t.u(0x2066, 0x50, 0x2069), "P"),  # bidi isolates
        (t.u(0xFEFF, 0x50), "P"),  # byte order mark
        (t.u(0x50, 0xAD, 0x72), "Pr"),  # soft hyphen is Cf
        (t.u(0x50, 0xE0041, 0xE007F, 0x72), "Pr"),  # astral tag characters
        (t.u(0x50, 0x2028, 0x72, 0x2029), "Pr"),  # line and paragraph separators
        ("a\nb\rc\td\x00e\x1bf", "abcdef"),  # controls
        ("a b" + t.u(0xA0) + "c", "a b" + t.u(0xA0) + "c"),  # spaces (Zs) are not touched
        (t.u(0x915, 0x94D, 0x937), t.u(0x915, 0x94D, 0x937)),  # Devanagari virama stays
        (t.u(0x65, 0x301), t.u(0x65, 0x301)),  # combining accent stays
        (t.u(0xE000, 0x378), t.u(0xE000, 0x378)),  # private use and unassigned stay
        ("", ""),
    ],
)
def test_PPL_10a_PE_24_clean_line_examples(raw, cleaned):
    assert text.clean_line(raw) == cleaned


# ---------------------------------------------------------------------------------------------
# 2. Crossref fixtures: all 104 person cases (FR-PA-11, PE-01 to PE-20)
# ---------------------------------------------------------------------------------------------
def test_PPL_10a_FR_PA_11_crossref_folder_holds_every_case():
    assert len(t.VALID_CASES) >= 29, "contracts/fixtures/person/crossref/valid shrank"
    assert len(t.INVALID_CASES) >= 75, "contracts/fixtures/person/crossref/invalid shrank"


@pytest.mark.parametrize("case", t.case_params(t.VALID_CASES))
def test_PPL_10a_FR_PA_11_valid_crossref_case_is_allowed_with_the_right_view(case):
    assert case["rule"] is None
    v = crossref.verdict_for_case(case)
    assert v.allowed is True, case["note"]
    assert v.view == _expected_view(case)


@pytest.mark.parametrize("case", t.case_params(t.INVALID_CASES))
def test_PPL_10a_FR_PA_11_invalid_crossref_case_is_refused_with_no_view(case):
    v = crossref.verdict_for_case(case)
    assert v.allowed is False, f"{case['rule']}: {case['note']}"
    assert v.view is None


@pytest.mark.parametrize("case", t.case_params(VALID_READS))
def test_PPL_10a_PE_20_valid_read_returns_exactly_the_projection(case):
    request, d = crossref.case_request(case)
    view = _expected_view(case)
    data = case["record"]["data"]
    if view == "full":
        expected = data
    elif view == "busy":
        expected = None if data.get("end") is None else {"start": data["start"], "end": data["end"]}
    else:
        expected = {k: data[k] for k in t.VIEW_KEYS[view] if k in data}
    got = access.read(request, d)
    assert got == expected
    if got is not None:  # deep copy: editing the answer must not edit the stored record
        before = copy.deepcopy(data)
        for key in list(got):
            got[key] = "tampered"
        assert request.record == before


@pytest.mark.parametrize("case", t.case_params(INVALID_READS))
def test_PPL_10a_PE_20_refused_read_is_none_never_an_empty_answer(case):
    request, d = crossref.case_request(case)
    assert access.read(request, d) is None


def test_PPL_10a_FR_PA_11_case_request_maps_every_case_as_documented():
    for name, case in t.ALL_CASES:
        request, d = crossref.case_request(case)
        action = case["request"]["action"]
        want = "read_" + case["request"]["view"] if action == "read" else action
        rec = case["record"]
        assert request.actor == case["request"]["actor"], name
        assert request.action == want, name
        assert request.record_kind == rec["kind"], name
        assert request.record == rec["data"], name
        assert request.now == case["now"], name
        assert request.meeting == rec.get("meeting"), name
        assert request.work_item == rec.get("work_item"), name
        assert request.source_owner == rec.get("source_owner"), name
        assert request.pin == rec.get("pin"), name
        assert tuple(request.mentions) == tuple(rec.get("mentions", ())), name
        assert set(d.persons) == {k for k, p in case["persons"].items() if p.get("id") == k}, name


def test_PPL_10a_FR_PA_11_case_request_drops_a_person_whose_key_is_not_their_id():
    _, case = next(c for c in t.VALID_CASES if c[0] == "person_reads_own_record")
    case = copy.deepcopy(case)
    some = next(k for k in case["persons"] if k != case["request"]["actor"])
    case["persons"]["u_impostor"] = case["persons"][some]  # key differs from the record's id
    _, d = crossref.case_request(case)
    assert "u_impostor" not in d.persons and some in d.persons


def test_PPL_10a_FR_PA_11_case_request_raises_input_error_on_a_missing_key_and_verdict_never_raises():
    _, case = t.VALID_CASES[0]
    for key in ("now", "persons", "record", "request"):
        broken = {k: v for k, v in case.items() if k != key}
        with pytest.raises(errors.PeopleInputError):
            crossref.case_request(broken)
        assert crossref.verdict_for_case(broken) == access.Verdict(False, None)
    for junk in (None, {}, [], "x", 5, {"now": "x"}, {**case, "record": {"kind": "work_item"}}):
        assert crossref.verdict_for_case(junk) == access.Verdict(False, None)


# ---------------------------------------------------------------------------------------------
# 3. Parity with the reference oracle (decide may only be stricter, plus G1 and G2)
# ---------------------------------------------------------------------------------------------
def test_PPL_10a_FR_PA_11_parity_decide_allows_only_what_the_reference_allows():
    started = time.perf_counter()
    allowed_total, problems = 0, []
    for name, case in t.ALL_CASES:
        request, d = crossref.case_request(case)
        for actor in [*case["persons"], "A_analyst"]:
            for action in t.ACTIONS:
                v = access.decide(dataclasses.replace(request, actor=actor, action=action), d)
                if not v.allowed:
                    assert v.view is None and v.allowed is False
                    continue
                allowed_total += 1
                suffix = action[5:] if action.startswith("read_") else None
                assert v.view == suffix, (name, actor, action)
                if (request.record_kind, action) in GRANTS:
                    continue
                if not t.reference_permits(case, actor, action):
                    problems.append(f"{name}: {actor} {action}")
    assert not problems, f"decide allowed what the reference refuses: {problems[:5]}"
    assert allowed_total >= len(t.VALID_CASES), "the parity run is vacuous: it allowed too little"
    assert time.perf_counter() - started < 30, "API.md: the parity run must take under 30 s"


def test_PPL_10a_FR_PA_11_g1_and_g2_are_the_only_grants_beyond_the_reference():
    seen = set()
    for name, case in t.ALL_CASES:
        request, d = crossref.case_request(case)
        for actor in [*case["persons"], "A_analyst"]:
            for action in t.ACTIONS:
                if access.decide(dataclasses.replace(request, actor=actor, action=action), d).allowed:
                    if not t.reference_permits(case, actor, action):
                        seen.add((request.record_kind, action))
    assert seen <= GRANTS, seen


# ---------------------------------------------------------------------------------------------
# 4. Mutation sweeps over every valid case: a tampered request is refused
# ---------------------------------------------------------------------------------------------
def _person_actor_cases():
    return [(n, c) for n, c in t.VALID_CASES if c["request"]["actor"] in c["persons"]]


def _with_record(request, **changes):
    return dataclasses.replace(request, record={**request.record, **changes})


@pytest.mark.parametrize("case", t.case_params(t.VALID_CASES))
def test_PPL_10a_PE_17_a_tampered_valid_request_is_refused(case):
    request, d = crossref.case_request(case)
    assert access.decide(request, d).allowed, "control: the untampered request is allowed"
    # an actor that is not in the directory has no rights (an A_ actor is Tilo and may only create)
    ghost = dataclasses.replace(request, actor="u_ghost")
    assert not access.decide(ghost, d).allowed
    # a record of another org: ids that look valid but belong elsewhere
    foreign = _with_record(request, org_id="org_foreign")
    assert not access.decide(foreign, d).allowed
    # an extra field makes the record invalid (additionalProperties false): fail closed
    assert not access.decide(_with_record(request, x_extra="1"), d).allowed
    # Tilo never reads, edits, confirms or tags without the setter's confirmation on a person's record
    if request.action != "create" and request.record_kind != "mention":
        assert not access.decide(dataclasses.replace(request, actor="A_analyst"), d).allowed
    # the same user id in two orgs: both records are dropped, so that id has no rights at all
    actor = request.actor
    if actor in d.persons:
        clone = {**d.persons[actor], "org_id": "org_foreign"}
        d2 = directory.Directory.of([*d.persons.values(), clone])
        assert d2.get(actor) is None
        assert not access.decide(request, d2).allowed


@pytest.mark.parametrize("case", t.case_params(_person_actor_cases()))
def test_PPL_10a_PE_02_an_emptied_directory_gives_a_person_no_rights(case):
    request, _ = crossref.case_request(case)
    assert not access.decide(request, directory.Directory.of([])).allowed


# ---------------------------------------------------------------------------------------------
# 5. S1 to S5 (stricter than the reference, PE-19) and G1, G2 (BQ-PPL10-1, -3)
# ---------------------------------------------------------------------------------------------
def _call(actor, action, kind, record, **extras):
    return {"actor": actor, "action": action, "kind": kind, "record": record, **extras}


def _evil_history(by, change="confirmed", status="open", at=t.T1):
    return {"at": at, "by": by, "change": change, "status": status}


def _s1_proposal(meeting):
    return _call("A_notes", "create", "calendar_entry", t.tilo_proposal(), meeting=meeting)


S_PAIRS = {
    "S1_minutes_stamp_by_a_non_owner": (
        _s1_proposal(t.minuted_meeting(by="u_riya")),
        _s1_proposal(t.minuted_meeting(by="u_owner")),
    ),
    "S1_minutes_stamp_in_the_future": (
        _s1_proposal(t.minuted_meeting(at=t.FUTURE)),
        _s1_proposal(t.minuted_meeting(at=t.NOW)),  # equal to now is allowed (at <= now)
    ),
    "S1_on_a_work_item_made_from_those_minutes": (
        _call("A_notes", "create", "work_item", t.proposed_tilo_item(), meeting=t.minuted_meeting(by="u_riya")),
        _call("A_notes", "create", "work_item", t.proposed_tilo_item(), meeting=t.minuted_meeting()),
    ),
    "S2_person_made_item_assigned_by_someone_else": (
        _call("u_riya", "read_full", "work_item", t.own_item(assigned_by={"by": "u_sam", "at": t.T0})),
        _call("u_riya", "read_full", "work_item", t.own_item(assigned_by={"by": "u_riya", "at": t.T0})),
    ),
    "S2_on_mark_done": (
        _call("u_riya", "mark_done", "work_item", t.own_item(assigned_by={"by": "u_sam", "at": t.T0})),
        _call("u_riya", "mark_done", "work_item", t.own_item()),
    ),
    "S3_confirmed_history_with_no_confirmed_by": (
        _call(
            "u_riya",
            "read_full",
            "work_item",
            t.own_item(history=[pl.history_entry("u_riya", "created", "open", t.T0), _evil_history("u_riya")]),
        ),
        _call(
            "u_riya",
            "read_full",
            "work_item",
            t.own_item(
                confirmed_by={"by": "u_riya", "at": t.T1},
                history=[pl.history_entry("u_riya", "created", "open", t.T0), _evil_history("u_riya")],
            ),
        ),
    ),
    "S3_confirmed_history_by_someone_other_than_confirmed_by": (
        _call(
            "u_riya",
            "read_full",
            "work_item",
            t.own_item(
                confirmed_by={"by": "u_riya", "at": t.T1},
                history=[pl.history_entry("u_riya", "created", "open", t.T0), _evil_history("u_sam")],
            ),
        ),
        _call(
            "u_riya",
            "read_full",
            "work_item",
            t.own_item(
                confirmed_by={"by": "u_riya", "at": t.T1},
                history=[pl.history_entry("u_riya", "created", "open", t.T0), _evil_history("u_riya")],
            ),
        ),
    ),
    "S3_accepted_pin_history_by_someone_other_than_confirmed_by": (
        _call(
            "u_riya",
            "read_full",
            "pinboard_item",
            t.team_pin(
                confirmed_by={"by": "u_owner", "at": t.T1},
                history=[
                    pl.history_entry("u_owner", "created", "proposed", t.T0),
                    _evil_history("u_riya", "accepted", "active"),
                ],
            ),
        ),
        _call(
            "u_riya",
            "read_full",
            "pinboard_item",
            t.team_pin(
                confirmed_by={"by": "u_owner", "at": t.T1},
                history=[
                    pl.history_entry("u_owner", "created", "proposed", t.T0),
                    _evil_history("u_owner", "accepted", "active"),
                ],
            ),
        ),
    ),
    "S3_on_the_pin_a_mention_tags": (
        _call(
            "u_owner",
            "mention",
            "mention",
            t.tag(),
            pin=t.team_pin(
                history=[
                    pl.history_entry("u_owner", "created", "active", t.T0),
                    _evil_history("u_riya", "accepted", "active"),
                ]
            ),
        ),
        _call("u_owner", "mention", "mention", t.tag(), pin=t.team_pin()),
    ),
    "S3_on_the_work_item_a_calendar_proposal_cites": (
        _call(
            "A_notes",
            "create",
            "calendar_entry",
            t.tilo_proposal(owner="u_riya", source={"kind": "tilo", "from": "meeting", "ref": "mt_weekly1#ai1"}),
            meeting=t.minuted_meeting(),
            work_item=t.tilo_item(
                source={"kind": "meeting", "ref": "mt_weekly1#ai1", "evidence": ["u0004"]},
                history=[
                    pl.history_entry("A_notes", "created", "proposed", t.T0),
                    pl.history_entry("u_owner", "confirmed", "open", t.T1),
                    _evil_history("u_sam"),
                ],
            ),
        ),
        _call(
            "A_notes",
            "create",
            "calendar_entry",
            t.tilo_proposal(owner="u_riya", source={"kind": "tilo", "from": "meeting", "ref": "mt_weekly1#ai1"}),
            meeting=t.minuted_meeting(),
            work_item=t.tilo_item(source={"kind": "meeting", "ref": "mt_weekly1#ai1", "evidence": ["u0004"]}),
        ),
    ),
    "S4_link_pin_without_a_url": (
        _call("u_riya", "read_full", "pinboard_item", t.team_pin(kind="link", url=None)),
        _call("u_riya", "read_full", "pinboard_item", t.team_pin(kind="link", url="https://example.com/doc")),
    ),
    "S4_note_pin_with_a_url": (
        _call("u_riya", "read_full", "pinboard_item", t.team_pin(kind="note", url="https://example.com/doc")),
        _call("u_riya", "read_full", "pinboard_item", t.team_pin(kind="note", url=None)),
    ),
    "S4_on_the_pin_a_mention_tags": (
        _call("u_owner", "mention", "mention", t.tag(), pin=t.team_pin(kind="link", url=None)),
        _call("u_owner", "mention", "mention", t.tag(), pin=t.team_pin(kind="link", url="https://example.com/doc")),
    ),
    "S5_entry_ends_before_it_starts": (
        _call("u_owner", "read_full", "calendar_entry", t.entry(start=t.T2, end=t.T1)),
        _call("u_owner", "read_full", "calendar_entry", t.entry(start=t.T1, end=t.T1)),  # equal is allowed
    ),
    "S5_open_ended_entry_is_fine": (
        _call("u_owner", "edit", "calendar_entry", t.entry(start=t.T2, end="2026-10-02T09:29:59.999Z")),
        _call("u_owner", "edit", "calendar_entry", t.entry(start=t.T2, end=None)),
    ),
}


def _both(call):
    call = dict(call)
    return t.both(call.pop("actor"), call.pop("action"), call.pop("kind"), call.pop("record"), **call)


@pytest.mark.parametrize("name", sorted(S_PAIRS))
def test_PPL_10a_PE_19_stricter_clause_refuses_what_the_reference_permits(name):
    bad, good = S_PAIRS[name]
    ref_bad, got_bad = _both(bad)
    ref_good, got_good = _both(good)
    assert ref_bad is True, f"{name}: the test case must be one the reference oracle permits"
    assert got_bad is False, f"{name}: decide must refuse (PE-19 stricter clause)"
    assert ref_good is True and got_good is True, f"{name}: control must be allowed by both"


def test_PPL_10a_PE_17_g1_org_owner_creates_a_person_of_their_org():
    new = t.make_person("u_new", "Nia New", teams=("tm_sales",), by="u_owner", at=t.NOW)
    assert t.ref_allows("u_owner", "create", "person", new) is False  # the reference lacks it: a grant
    assert t.allowed("u_owner", "create", "person", new) is True
    for actor, why in (
        ("u_riya", "a member"),
        ("u_sam", "a member of another team"),
        ("u_ext", "an owner of another org"),
        ("u_ghost", "not in the directory"),
        ("A_notes", "Tilo"),
        ("system", "the system"),
    ):
        assert t.allowed(actor, "create", "person", new) is False, why


def test_PPL_10a_PE_17_g1_an_org_owner_never_creates_a_person_into_another_org():
    foreign = t.make_person("u_new", "Nia New", org=t.OTHER_ORG, by="u_ext", at=t.NOW)
    assert t.allowed("u_owner", "create", "person", foreign) is False
    assert t.allowed("u_ext", "create", "person", foreign) is True  # owner of that org


def test_PPL_10a_PE_18_g2_a_person_creates_the_meeting_they_attest():
    mine = t.meeting(owner="u_riya", attestation={"by": "u_riya", "at": t.T0, "notice_version": "1.0.0"})
    assert t.ref_allows("u_riya", "create", "meeting", mine) is False  # the reference lacks it: a grant
    assert t.allowed("u_riya", "create", "meeting", mine) is True
    assert t.allowed("u_owner", "create", "meeting", mine) is False  # not the owner of that meeting
    assert t.allowed("u_riya", "create", "meeting", t.meeting(owner="u_riya")) is False  # attested by u_owner
    assert (
        t.allowed(
            "u_riya",
            "create",
            "meeting",
            t.meeting(attestation={"by": "u_riya", "at": t.T0, "notice_version": "1.0.0"}),
        )
        is False
    )
    assert t.allowed("A_notes", "create", "meeting", t.meeting()) is False  # Tilo does not create meetings
    assert t.allowed("u_ext", "create", "meeting", mine) is False  # another org
    assert (
        t.allowed(
            "u_ghost",
            "create",
            "meeting",
            t.meeting(owner="u_ghost", attestation={"by": "u_ghost", "at": t.T0, "notice_version": "1.0.0"}),
        )
        is False
    )


# ---------------------------------------------------------------------------------------------
# 6. Hostile requests, one scenario per probe in API.md
# ---------------------------------------------------------------------------------------------
def _org_records():
    return {
        "team_pin": ("pinboard_item", t.team_pin(), {}),
        "personal_pin": ("pinboard_item", t.personal_pin(), {}),
        "own_item": ("work_item", t.own_item(), {}),
        "assigned_item": ("work_item", pl.work_item(), {}),
        "tilo_item": ("work_item", t.tilo_item(), {"meeting": t.minuted_meeting()}),
        "entry": ("calendar_entry", t.entry(), {}),
        "shared_entry": ("calendar_entry", t.shared_entry(), {}),
        "meeting": ("meeting", t.meeting(), {}),
        "mention": ("mention", t.tag(), {"pin": t.team_pin()}),
        "person": ("person", t.person_in("u_riya"), {}),
    }


@pytest.mark.parametrize("name", sorted(_org_records()))
def test_PPL_10a_PE_17_an_owner_of_another_org_does_nothing_to_this_orgs_records(name):
    kind, record, extras = _org_records()[name]
    for action in t.ACTIONS:
        assert not t.allowed("u_ext", action, kind, record, **extras), f"{action} on {name}"


@pytest.mark.parametrize("name", sorted(_org_records()))
def test_PPL_10a_PE_07_tilo_reads_nothing_and_confirms_nothing(name):
    kind, record, extras = _org_records()[name]
    for actor in ("A_notes", "A_calendar_sync", "A_analyst"):
        for action in t.ACTIONS:
            if action == "create" or (kind == "mention" and action in ("mention", "create")):
                continue
            assert not t.allowed(actor, action, kind, record, **extras), f"{actor} {action} on {name}"


@pytest.mark.parametrize(
    "actor",
    [
        "system",
        "System",
        "tl_sales",
        "pol_autoreply",
        "w_1",
        "A_",
        "a_notes",
        "u_",
        "",
        "A_notes\n",
        "u_owner\n",
        "u_owner ",
    ],
)
def test_PPL_10a_PE_19_an_actor_that_is_not_a_user_or_agent_id_is_refused(actor):
    """BQ-PPL10-11: `system` is not an actor `decide` accepts; neither is anything with a stray byte."""
    assert not t.allowed(
        actor,
        "create",
        "calendar_entry",
        t.tilo_proposal(created_by={"by": "tilo", "ref": "system", "at": t.T1}),
        meeting=t.meeting(),
    )
    assert not t.allowed(actor, "read_full", "meeting", t.meeting())


def test_PPL_10a_PE_19_look_alike_user_ids_are_not_the_user():
    fullwidth = "u_" + t.u(0xFF4F, 0xFF57, 0xFF4E, 0xFF45, 0xFF52)  # fullwidth "owner"
    assert not t.allowed(fullwidth, "read_full", "meeting", t.meeting())
    assert not t.allowed("u_owner", "read_full", "meeting", t.meeting(owner=fullwidth))


# -- membership: left the team, dated later, assigned by the wrong person ---------------------------
LEFT_TEAM = {
    "membership removed": [],
    "membership dated after the request": [t.member("tm_sales", "u_owner", t.FUTURE)],
    "membership dated one millisecond after the request": [t.member("tm_sales", "u_owner", "2026-10-03T09:00:00.001Z")],
    "assigned by a member, not an owner": [t.member("tm_sales", "u_sam")],
    "assigned by an owner of another org": [t.member("tm_sales", "u_ext")],
    "assigned by a person not in the directory": [t.member("tm_sales", "u_ghost")],
    "a different team": [t.member("tm_ops")],
}


def _team_requests():
    """Five requests u_riya may make while she is a member of tm_sales."""
    own_pin = pl.pin(
        id="pb_riya1",
        set_up_by="u_riya",
        created_by=pl.maker_person("u_riya"),
        history=[pl.history_entry("u_riya", "created", "active", t.T0)],
    )
    return [
        ("read an active team pin", _call("u_riya", "read_full", "pinboard_item", t.team_pin())),
        ("read a shared entry", _call("u_riya", "read_full", "calendar_entry", t.shared_entry())),
        ("read busy of a teammate", _call("u_riya", "read_busy", "calendar_entry", t.entry())),
        ("edit the pin she set up", _call("u_riya", "edit", "pinboard_item", own_pin)),
        ("create a team pin", _call("u_riya", "create", "pinboard_item", own_pin)),
    ]


def _riya_with(memberships):
    riya = copy.deepcopy(t.person_in("u_riya"))
    riya["memberships"] = memberships
    d = directory.Directory.of([p if p["id"] != "u_riya" else riya for p in t.world_persons()])
    return d


@pytest.mark.parametrize("label", sorted(LEFT_TEAM))
def test_PPL_10a_PE_02_a_person_who_is_not_a_current_member_keeps_no_team_right(label):
    d = _riya_with(LEFT_TEAM[label])
    control = _riya_with([t.member("tm_sales")])
    for what, call in _team_requests():
        args = dict(call)
        actor, action, kind, record = args.pop("actor"), args.pop("action"), args.pop("kind"), args.pop("record")
        assert t.allowed(actor, action, kind, record, control, **args), f"control: {what}"
        assert not t.allowed(actor, action, kind, record, d, **args), f"{label}: {what}"


def test_PPL_10a_PE_02_membership_dated_exactly_now_counts_and_the_directory_says_so():
    d = _riya_with([t.member("tm_sales", "u_owner", t.NOW)])
    assert d.is_member("u_riya", "tm_sales", t.NOW) is True
    assert d.is_member("u_riya", "tm_sales", "2026-10-03T08:59:59.999Z") is False
    assert d.teammates("u_riya", "u_owner", t.NOW) is True
    assert d.teammates("u_riya", "u_owner", "2026-10-03T08:59:59.999Z") is False


def test_PPL_10a_PE_02_the_assigning_owner_must_be_an_owner_of_the_members_own_org():
    owner_of_other_org = t.make_person("u_boss2", "Bea Boss", org=t.OTHER_ORG, role="owner", teams=(), by="u_boss2")
    riya = copy.deepcopy(t.person_in("u_riya"))
    riya["memberships"] = [t.member("tm_sales", "u_boss2")]
    d = directory.Directory.of([p if p["id"] != "u_riya" else riya for p in t.world_persons()] + [owner_of_other_org])
    assert d.get("u_boss2") is not None and d.get("u_riya") is not None
    assert d.is_member("u_riya", "tm_sales", t.NOW) is False
    assert d.is_member("u_owner", "tm_sales", t.NOW) is True


# -- directory construction -------------------------------------------------------------------------
def test_PPL_10a_PE_17_directory_drops_an_invalid_record_and_never_raises():
    bad = {**t.person_in("u_riya"), "x_extra": 1}
    junk = [None, 5, "u_riya", [], {}, {"id": "u_x"}, bad, {**t.person_in("u_sam"), "org_role": "root"}]
    d = directory.Directory.of([*t.world_persons(), *junk])
    assert set(d.persons) == {p["id"] for p in t.world_persons() if p["id"] != "u_riya"}
    assert d.get("u_riya") is None and d.get("u_ghost") is None
    assert directory.Directory.of([]).persons == {}


def test_PPL_10a_PE_17_an_id_held_by_two_records_drops_both():
    twin = {**t.person_in("u_owner"), "org_id": t.OTHER_ORG}
    d = directory.Directory.of([*t.world_persons(), twin])
    assert d.get("u_owner") is None
    assert d.is_member("u_owner", "tm_sales", t.NOW) is False
    # riya's membership was assigned by that id, so it no longer counts either
    assert d.is_member("u_riya", "tm_sales", t.NOW) is False
    assert not t.allowed("u_riya", "read_full", "pinboard_item", t.team_pin(), d)
    assert not t.allowed("u_owner", "read_full", "meeting", t.meeting(), d)
    exact = directory.Directory.of([*t.world_persons(), copy.deepcopy(t.person_in("u_lee"))])
    assert exact.get("u_lee") is None  # an exact duplicate is a duplicate


def test_PPL_10a_PE_17_directory_answers_for_people_it_does_not_hold_with_no_rights():
    d = t.world_directory()
    assert d.get("u_ghost") is None
    assert d.is_member("u_ghost", "tm_sales", t.NOW) is False
    assert d.teammates("u_ghost", "u_riya", t.NOW) is False
    assert d.teammates("u_riya", "u_ghost", t.NOW) is False
    assert d.teammates("u_riya", "u_owner", t.NOW) is True and d.teammates("u_owner", "u_riya", t.NOW) is True
    assert d.teammates("u_riya", "u_sam", t.NOW) is False  # different teams
    assert d.teammates("u_riya", "u_ext", t.NOW) is False  # another org
    assert d.teammates("u_lee", "u_lee", t.NOW) is False  # no team, no teammate
    assert d.is_member("u_riya", "tm_ops", t.NOW) is False


def test_PPL_10a_PE_17_an_owner_of_the_org_can_assign_themselves_a_membership_but_a_member_cannot():
    d = t.world_directory()
    assert d.is_member("u_owner", "tm_sales", t.NOW) is True  # u_owner assigned by u_owner, an org owner
    selfish = t.make_person("u_riya", "Riya Example", teams=("tm_sales",), by="u_riya")
    d2 = directory.Directory.of([p if p["id"] != "u_riya" else selfish for p in t.world_persons()])
    assert d2.is_member("u_riya", "tm_sales", t.NOW) is False  # a member vouching for themselves counts for nothing


# -- shares and busy ----------------------------------------------------------------------------------
def test_PPL_10a_PE_04_a_withdrawn_share_stops_the_teammates_read_at_once_but_not_busy():
    shared, withdrawn = t.shared_entry(), t.entry()
    assert t.allowed("u_riya", "read_full", "calendar_entry", shared)
    assert not t.allowed("u_riya", "read_full", "calendar_entry", withdrawn)
    assert not t.allowed("u_riya", "read_status", "calendar_entry", withdrawn)
    assert t.allowed("u_riya", "read_busy", "calendar_entry", withdrawn)  # still teammates
    assert t.allowed("u_owner", "read_full", "calendar_entry", withdrawn)  # the owner always reads


def test_PPL_10a_PE_04_an_owner_who_left_the_shared_team_loses_the_share_and_busy_to_it():
    owner_out = copy.deepcopy(t.person_in("u_owner"))
    owner_out["memberships"] = []
    d = directory.Directory.of([p if p["id"] != "u_owner" else owner_out for p in t.world_persons()])
    assert not t.allowed("u_riya", "read_full", "calendar_entry", t.shared_entry(), d)
    assert not t.allowed("u_riya", "read_status", "calendar_entry", t.shared_entry(), d)
    assert not t.allowed("u_riya", "read_busy", "calendar_entry", t.entry(), d)  # no longer teammates
    assert t.allowed("u_owner", "read_full", "calendar_entry", t.shared_entry(), d)  # their own entry
    assert not t.allowed("u_owner", "edit", "calendar_entry", t.shared_entry(), d)  # sharing needs membership
    assert t.allowed("u_owner", "edit", "calendar_entry", t.entry(), d)


@pytest.mark.parametrize("state", ["proposed", "declined", "cancelled"])
def test_PPL_10a_PE_04_only_accepted_entries_show_busy_and_a_proposed_one_shows_to_no_one_else(state):
    record = t.entry(state=state, confirmed_by=None)
    assert t.allowed("u_owner", "read_full", "calendar_entry", record)
    for action in ("read_full", "read_status", "read_busy"):
        assert not t.allowed("u_riya", action, "calendar_entry", record), f"{state} {action}"


def test_PPL_10a_PE_04_busy_needs_a_shared_team_and_org_owners_get_no_more_than_members():
    boss = t.make_person("u_boss", "Bo Boss", role="owner", teams=(), by="u_boss")
    d = directory.Directory.of([*t.world_persons(), boss])
    riyas = pl.calendar_entry(id="ce_riya1", owner="u_riya", created_by=pl.maker_person("u_riya"))
    for action in ("read_full", "read_status", "read_busy"):
        assert not t.allowed("u_boss", action, "calendar_entry", riyas, d), action
        assert not t.allowed("u_sam", action, "calendar_entry", riyas, d), action  # another team
        assert not t.allowed("u_lee", action, "calendar_entry", riyas, d), action  # no team
    assert t.allowed("u_owner", "read_busy", "calendar_entry", riyas, d)  # teammate
    assert not t.allowed(
        "u_owner", "read_full", "calendar_entry", riyas, d
    )  # an owner of the org and a teammate: busy only


# -- no manager, teammate or org-owner view of personal data ---------------------------------------
PERSONAL = {
    "personal pin": ("pinboard_item", t.personal_pin(), {}),
    "own work item": ("work_item", t.own_item(), {}),
    "own calendar entry": (
        "calendar_entry",
        pl.calendar_entry(id="ce_riya1", owner="u_riya", created_by=pl.maker_person("u_riya")),
        {},
    ),
    "own meeting": (
        "meeting",
        t.meeting(owner="u_riya", attestation={"by": "u_riya", "at": t.T0, "notice_version": "1.0.0"}),
        {},
    ),
}


@pytest.mark.parametrize("label", sorted(PERSONAL))
@pytest.mark.parametrize("viewer", ["u_owner", "u_boss", "u_sam", "u_lee", "u_ext", "A_notes"])
def test_PPL_10a_PE_01_nobody_but_the_person_reads_what_is_theirs(label, viewer):
    kind, record, extras = PERSONAL[label]
    boss = t.make_person("u_boss", "Bo Boss", role="owner", teams=(), by="u_boss")
    d = directory.Directory.of([*t.world_persons(), boss])
    for action in ("read_full", "read_status", "edit", "confirm", "mark_done"):
        assert not t.allowed(viewer, action, kind, record, d, **extras), f"{viewer} {action}"
    assert t.allowed("u_riya", "read_full", kind, record, d, **extras)


def test_PPL_10a_PE_20_an_org_owner_reads_directory_and_membership_of_a_person_never_the_full_record():
    boss = t.make_person("u_boss", "Bo Boss", role="owner", teams=(), by="u_boss")
    d = directory.Directory.of([*t.world_persons(), boss])
    riya = t.person_in("u_riya")
    assert t.allowed("u_boss", "read_membership", "person", riya, d)
    assert t.allowed("u_boss", "read_directory", "person", riya, d)
    assert not t.allowed("u_boss", "read_full", "person", riya, d)
    assert not t.allowed("u_boss", "read_status", "person", riya, d)
    assert not t.allowed("u_boss", "read_busy", "person", riya, d)
    # a teammate reads the directory view only
    assert t.allowed("u_owner", "read_directory", "person", riya)
    for action in ("read_full", "read_membership", "read_status"):
        assert not t.allowed("u_sam", action, "person", riya), action
    # the person reads themselves in full
    assert t.allowed("u_riya", "read_full", "person", riya)
    assert t.allowed("u_riya", "read_membership", "person", riya)


def test_PPL_10a_PE_20_a_stranger_reads_not_even_a_display_name():
    riya = t.person_in("u_riya")
    for viewer in ("u_sam", "u_lee", "u_ext", "A_notes", "u_ghost"):
        for action in t.READ_ACTIONS:
            assert not t.allowed(viewer, action, "person", riya), f"{viewer} {action}"


def test_PPL_10a_PE_01_teammates_read_busy_but_never_a_title():
    entry = pl.calendar_entry(id="ce_riya1", owner="u_riya", title=t.SENTINEL, created_by=pl.maker_person("u_riya"))
    assert not t.allowed("u_owner", "read_full", "calendar_entry", entry)
    assert not t.allowed("u_owner", "read_status", "calendar_entry", entry)  # status view carries the title
    assert t.allowed("u_owner", "read_busy", "calendar_entry", entry)
    request = t.req("u_owner", "read_busy", "calendar_entry", entry)
    got = access.read(request, t.world_directory())
    assert t.SENTINEL not in t.dump(got) and set(got) == {"start", "end"}
    for kind, record, extras in (PERSONAL["personal pin"], PERSONAL["own work item"], PERSONAL["own meeting"]):
        record = {**record, "title": t.SENTINEL}
        for action in ("read_full", "read_status"):
            assert not t.allowed("u_owner", action, kind, record, **extras), f"{kind} {action}"


def test_PPL_10a_PE_20_display_name_is_never_identity():
    """A viewer whose display name equals another person's gains nothing from it (identity is the id)."""
    pat_owner = t.make_person("u_pat1", "Pat Doe", role="owner", teams=(), by="u_pat1")
    pat_member = t.make_person("u_pat2", "Pat Doe", teams=("tm_sales",))
    d = directory.Directory.of([*t.world_persons(), pat_owner, pat_member])
    assert not t.allowed("u_pat2", "set_org_role", "person", pat_member, d)
    assert not t.allowed("u_pat2", "assign_membership", "person", t.person_in("u_riya"), d)
    assert t.allowed("u_pat1", "set_org_role", "person", t.person_in("u_riya"), d)
    assert not t.allowed("u_pat2", "read_full", "person", pat_owner, d)  # a namesake is not the person
    assert t.allowed("u_pat2", "read_full", "person", pat_member, d)


# -- Tilo-made records: sources and confirmations ---------------------------------------------------
def _tilo_pin_tag(pin, **kw):
    return t.allowed("A_notes", "mention", "mention", t.tag(pin_id=pin["id"]), pin=pin, **kw)


def test_PPL_10a_PE_06_tilo_tags_only_for_a_pin_its_setter_confirmed_and_whose_meeting_is_supplied():
    pin, meeting = t.tilo_team_pin(), t.meeting()
    proposed = t.tilo_team_pin(
        status="proposed", confirmed_by=None, history=[pl.history_entry("A_notes", "created", "proposed", t.T0)]
    )
    assert _tilo_pin_tag(pin, meeting=meeting)  # control
    assert not _tilo_pin_tag(pin)  # meeting missing: fail closed
    assert not _tilo_pin_tag(pin, meeting=t.meeting(id="mt_other1"))  # another meeting
    assert not _tilo_pin_tag(pin, meeting=t.meeting(org_id=t.OTHER_ORG))  # another org
    assert not _tilo_pin_tag(
        t.tilo_team_pin(confirmed_by={"by": "u_riya", "at": t.T1}), meeting=meeting
    )  # not the setter
    assert not _tilo_pin_tag(t.tilo_team_pin(confirmed_by={"by": "u_owner", "at": t.FUTURE}), meeting=meeting)  # future
    assert not _tilo_pin_tag(
        t.tilo_team_pin(confirmed_by={"by": "u_owner", "at": "2026-09-30T09:00:00.000Z"}), meeting=meeting
    )  # before it was made
    assert not _tilo_pin_tag(t.team_pin(), meeting=meeting)  # a person-made pin has no confirmation to lean on
    assert not _tilo_pin_tag(t.tilo_team_pin(set_up_by="u_riya"), meeting=meeting)  # setter is not the meeting owner
    assert not _tilo_pin_tag(proposed, meeting=meeting)  # proposed pins take no tag
    assert not t.allowed(
        "A_notes", "untag", "mention", t.tag(pin_id=pin["id"]), pin=pin, meeting=meeting
    )  # never untags


MENTION_CASES = {
    # id: (allowed, action, actor, tag overrides, pin, mentions, persons override)
    "setter tags a member": (True, "mention", "u_owner", {}, None, (), None),
    "setter re-tags a person the setter removed earlier": (
        True,
        "mention",
        "u_owner",
        {},
        None,
        (t.tag(id="mn_old1", removed={"by": "u_owner", "at": t.T1}),),
        None,
    ),
    "tag on a personal pin": (False, "mention", "u_riya", {}, t.personal_pin(), (), None),
    "tag on a proposed pin": (False, "mention", "u_owner", {}, t.team_pin(status="proposed"), (), None),
    "tag on a removed pin": (False, "mention", "u_owner", {}, t.team_pin(status="removed"), (), None),
    "tag that is already removed": (
        False,
        "mention",
        "u_owner",
        {"removed": {"by": "u_owner", "at": t.T1}},
        None,
        (),
        None,
    ),
    "by a member who is not the setter": (False, "mention", "u_riya", {}, None, (), None),
    "tagged person is in another team": (False, "mention", "u_owner", {"user": "u_sam"}, None, (), None),
    "tagged person is of another org": (False, "mention", "u_owner", {"user": "u_ext"}, None, (), None),
    "tagged person is not in the directory": (False, "mention", "u_owner", {"user": "u_ghost"}, None, (), None),
    "tag names another pin": (False, "mention", "u_owner", {"pin_id": "pb_other1"}, None, (), None),
    "tag names another team": (False, "mention", "u_owner", {"team": "tm_ops"}, None, (), None),
    "tag of another org": (False, "mention", "u_owner", {"org_id": t.OTHER_ORG}, None, (), None),
    "re-tag after the person removed themself": (
        False,
        "mention",
        "u_owner",
        {},
        None,
        (t.tag(id="mn_old1", removed={"by": "u_riya", "at": t.T1}),),
        None,
    ),
    "tag by the setter of another org": (False, "mention", "u_ext", {}, None, (), None),
    "untag by the tagged person": (True, "untag", "u_riya", {}, None, (), None),
    "untag by the setter": (True, "untag", "u_owner", {}, None, (), None),
    "untag by a third person": (False, "untag", "u_sam", {}, None, (), None),
    "untag by a teammate who is not the setter": (False, "untag", "u_lee", {}, None, (), None),
    "untag of a mention already removed": (
        False,
        "untag",
        "u_riya",
        {"removed": {"by": "u_riya", "at": t.T1}},
        None,
        (),
        None,
    ),
    "untag by a person of another org": (False, "untag", "u_ext", {}, None, (), None),
    "untag on a personal pin": (False, "untag", "u_riya", {}, t.personal_pin(), (), None),
}


@pytest.mark.parametrize("label", sorted(MENTION_CASES))
def test_PPL_10a_PE_06_mention_and_untag_rules(label):
    ok, action, actor, overrides, pin, mentions, _ = MENTION_CASES[label]
    pin = pin if pin is not None else t.team_pin()
    record = t.tag(**overrides)
    assert t.allowed(actor, action, "mention", record, pin=pin, mentions=mentions) is ok, label


def test_PPL_10a_PE_06_a_setter_who_left_the_team_cannot_tag():
    owner_out = copy.deepcopy(t.person_in("u_owner"))
    owner_out["memberships"] = []
    d = directory.Directory.of([p if p["id"] != "u_owner" else owner_out for p in t.world_persons()])
    assert not t.allowed("u_owner", "mention", "mention", t.tag(), d, pin=t.team_pin())


def test_PPL_10a_PE_06_the_tagged_person_must_be_a_current_member():
    d = _riya_with([t.member("tm_sales", "u_owner", t.FUTURE)])  # riya's membership starts later
    assert not t.allowed("u_owner", "mention", "mention", t.tag(), d, pin=t.team_pin())


@pytest.mark.parametrize("actor", ["u_owner", "u_riya", "u_sam", "u_ext", "A_notes"])
def test_PPL_10a_PE_06_nobody_reads_a_mention_record_BQ_PPL10_12(actor):
    for action in t.READ_ACTIONS:
        assert not t.allowed(actor, action, "mention", t.tag(), pin=t.team_pin()), action
    for action in ("create", "edit", "confirm", "mark_done", "assign_membership", "set_org_role", "start_capture"):
        assert not t.allowed(actor, action, "mention", t.tag(), pin=t.team_pin()), action


def test_PPL_10a_PE_06_a_mention_request_without_its_pin_is_refused():
    assert not t.allowed("u_owner", "mention", "mention", t.tag())
    assert not t.allowed("u_owner", "untag", "mention", t.tag())


# -- work items, pins, calendar and meetings: the extra edges the fixtures leave out -------------------
EDGE_CASES = {
    "person creates their own item": (True, _call("u_riya", "create", "work_item", t.own_item())),
    "person creates an item for someone else": (
        False,
        _call("u_riya", "create", "work_item", t.own_item(owner="u_sam")),
    ),
    "person creates a proposed item": (False, _call("u_riya", "create", "work_item", t.own_item(status="proposed"))),
    "person creates an item assigned by another": (
        False,
        _call("u_riya", "create", "work_item", t.own_item(assigned_by={"by": "u_owner", "at": t.T0})),
    ),
    "tilo creates a proposed item with its meeting": (
        True,
        _call("A_notes", "create", "work_item", t.proposed_tilo_item(), meeting=t.meeting()),
    ),
    "tilo creates an open item": (False, _call("A_notes", "create", "work_item", t.tilo_item(), meeting=t.meeting())),
    "tilo creates an item without its meeting": (
        False,
        _call("A_notes", "create", "work_item", t.proposed_tilo_item()),
    ),
    "tilo creates an item from mail": (
        False,
        _call(
            "A_notes",
            "create",
            "work_item",
            t.proposed_tilo_item(source={"kind": "mail", "ref": "mail_1", "evidence": []}),
            meeting=t.meeting(),
        ),
    ),
    "tilo creates an item assigned by a person who does not own the meeting": (
        False,
        _call(
            "A_notes",
            "create",
            "work_item",
            t.proposed_tilo_item(assigned_by={"by": "u_sam", "at": t.T0}),
            meeting=t.meeting(),
        ),
    ),
    "owner marks an open item done": (True, _call("u_riya", "mark_done", "work_item", t.own_item())),
    "owner marks a done item done": (False, _call("u_riya", "mark_done", "work_item", t.own_item(status="done"))),
    "assigner reads the status of an open assigned item": (
        True,
        _call("u_owner", "read_status", "work_item", pl.work_item()),
    ),
    "assigner reads the full assigned item": (False, _call("u_owner", "read_full", "work_item", pl.work_item())),
    "assigner edits the assigned item": (False, _call("u_owner", "edit", "work_item", pl.work_item())),
    "owner reads a dropped item": (True, _call("u_riya", "read_full", "work_item", t.own_item(status="dropped"))),
    "unconfirmed tilo item is read by no one": (
        False,
        _call(
            "u_riya",
            "read_full",
            "work_item",
            t.tilo_item(confirmed_by={"by": "u_sam", "at": t.T1}),
            meeting=t.meeting(),
        ),
    ),
    "tilo item whose confirmation is in the future": (
        False,
        _call(
            "u_riya",
            "read_full",
            "work_item",
            t.tilo_item(confirmed_by={"by": "u_owner", "at": t.FUTURE}),
            meeting=t.meeting(),
        ),
    ),
    "tilo item read with its meeting": (
        True,
        _call("u_riya", "read_full", "work_item", t.tilo_item(), meeting=t.meeting()),
    ),
    "tilo item read with no meeting": (False, _call("u_riya", "read_full", "work_item", t.tilo_item())),
    "tilo item read with the meeting of another org": (
        False,
        _call("u_riya", "read_full", "work_item", t.tilo_item(), meeting=t.meeting(org_id=t.OTHER_ORG)),
    ),
    "tilo item read with another meeting": (
        False,
        _call("u_riya", "read_full", "work_item", t.tilo_item(), meeting=t.meeting(id="mt_other1")),
    ),
    "tilo item whose meeting has a deleted tombstone": (
        True,
        _call(
            "u_riya",
            "read_full",
            "work_item",
            t.tilo_item(),
            meeting=t.meeting(
                status="deleted", title="Deleted meeting", series=None, scheduled=None, agenda=[], attendees=[]
            ),
        ),
    ),
    "member edits a pin they did not set up": (False, _call("u_riya", "edit", "pinboard_item", t.team_pin())),
    "setter confirms an active pin": (False, _call("u_owner", "confirm", "pinboard_item", t.team_pin())),
    "setter confirms a proposed pin": (
        True,
        _call("u_owner", "confirm", "pinboard_item", t.team_pin(status="proposed")),
    ),
    "setter confirms a removed pin": (
        False,
        _call("u_owner", "confirm", "pinboard_item", t.team_pin(status="removed")),
    ),
    "setter edits an active pin": (True, _call("u_owner", "edit", "pinboard_item", t.team_pin())),
    "setter edits a removed pin": (True, _call("u_owner", "edit", "pinboard_item", t.team_pin(status="removed"))),
    "member reads a removed pin": (False, _call("u_riya", "read_full", "pinboard_item", t.team_pin(status="removed"))),
    "member reads an active tilo pin its setter did not confirm": (
        False,
        _call(
            "u_riya",
            "read_full",
            "pinboard_item",
            t.tilo_team_pin(confirmed_by={"by": "u_riya", "at": t.T1}),
            meeting=t.meeting(),
        ),
    ),
    "member reads an active tilo pin its setter confirmed": (
        True,
        _call("u_riya", "read_full", "pinboard_item", t.tilo_team_pin(), meeting=t.meeting()),
    ),
    "tilo creates a proposed team pin with a member as owner": (
        True,
        _call(
            "A_notes",
            "create",
            "pinboard_item",
            t.tilo_team_pin(
                status="proposed",
                confirmed_by=None,
                owner="u_riya",
                history=[pl.history_entry("A_notes", "created", "proposed", t.T0)],
            ),
            meeting=t.meeting(),
        ),
    ),
    "tilo creates a proposed team pin owned by a non-member": (
        False,
        _call(
            "A_notes",
            "create",
            "pinboard_item",
            t.tilo_team_pin(
                status="proposed",
                confirmed_by=None,
                owner="u_sam",
                history=[pl.history_entry("A_notes", "created", "proposed", t.T0)],
            ),
            meeting=t.meeting(),
        ),
    ),
    "tilo creates an active team pin": (
        False,
        _call("A_notes", "create", "pinboard_item", t.tilo_team_pin(), meeting=t.meeting()),
    ),
    "tilo creates a personal pin for the meeting owner": (
        True,
        _call(
            "A_notes",
            "create",
            "pinboard_item",
            t.personal_pin(
                id="pb_tp1",
                scope={"kind": "personal", "user": "u_owner"},
                set_up_by="u_owner",
                created_by=pl.maker_tilo("A_notes", t.T0),
                source={"kind": "meeting", "ref": "mt_weekly1", "evidence": []},
            ),
            meeting=t.meeting(),
        ),
    ),
    "tilo creates a personal pin for an attendee from the meeting": (
        False,
        _call(
            "A_notes",
            "create",
            "pinboard_item",
            t.personal_pin(
                created_by=pl.maker_tilo("A_notes", t.T0),
                source={"kind": "meeting", "ref": "mt_weekly1", "evidence": []},
            ),
            meeting=t.meeting(),
        ),
    ),
    "tilo creates a personal pin from the owners own request": (
        True,
        _call(
            "A_notes",
            "create",
            "pinboard_item",
            t.personal_pin(
                created_by=pl.maker_tilo("A_notes", t.T0), source={"kind": "request", "ref": "rq_1", "evidence": []}
            ),
            source_owner="u_riya",
        ),
    ),
    "tilo creates a personal pin from another persons request": (
        False,
        _call(
            "A_notes",
            "create",
            "pinboard_item",
            t.personal_pin(
                created_by=pl.maker_tilo("A_notes", t.T0), source={"kind": "request", "ref": "rq_1", "evidence": []}
            ),
            source_owner="u_sam",
        ),
    ),
    "tilo creates a personal pin from a request with no owner given": (
        False,
        _call(
            "A_notes",
            "create",
            "pinboard_item",
            t.personal_pin(
                created_by=pl.maker_tilo("A_notes", t.T0), source={"kind": "request", "ref": "rq_1", "evidence": []}
            ),
        ),
    ),
    "tilo creates a personal pin with a manual source": (
        False,
        _call(
            "A_notes",
            "create",
            "pinboard_item",
            t.personal_pin(
                created_by=pl.maker_tilo("A_notes", t.T0), source={"kind": "manual", "ref": None, "evidence": []}
            ),
            source_owner="u_riya",
        ),
    ),
    "person creates a personal pin for themself": (True, _call("u_riya", "create", "pinboard_item", t.personal_pin())),
    "person creates a personal pin for another": (False, _call("u_sam", "create", "pinboard_item", t.personal_pin())),
    "person creates a team pin they set up while a member": (
        True,
        _call("u_owner", "create", "pinboard_item", t.team_pin()),
    ),
    "person creates a team pin set up by another": (
        False,
        _call("u_owner", "create", "pinboard_item", t.team_pin(set_up_by="u_riya")),
    ),
    "person creates a team pin for a team they are not in": (
        False,
        _call("u_sam", "create", "pinboard_item", t.team_pin(set_up_by="u_sam", created_by=pl.maker_person("u_sam"))),
    ),
    "person creates a team pin with a non-member as owner": (
        False,
        _call("u_owner", "create", "pinboard_item", t.team_pin(owner="u_sam")),
    ),
    "person creates a team pin with a member as owner": (
        True,
        _call("u_owner", "create", "pinboard_item", t.team_pin(owner="u_riya")),
    ),
    "owner creates their calendar entry": (True, _call("u_owner", "create", "calendar_entry", t.entry())),
    "person creates an entry for another": (False, _call("u_riya", "create", "calendar_entry", t.entry())),
    "tilo creates a proposal for the meeting owner": (
        True,
        _call("A_notes", "create", "calendar_entry", t.tilo_proposal(), meeting=t.meeting()),
    ),
    "tilo creates a proposal for an attendee from the bare meeting": (
        False,
        _call("A_notes", "create", "calendar_entry", t.tilo_proposal(owner="u_riya"), meeting=t.meeting()),
    ),
    "tilo creates a proposal for an attendee from the transcript": (
        False,
        _call(
            "A_notes",
            "create",
            "calendar_entry",
            t.tilo_proposal(owner="u_riya", source={"kind": "tilo", "from": "transcript", "ref": "mt_weekly1"}),
            meeting=t.meeting(),
        ),
    ),
    "tilo creates a shared proposal": (
        False,
        _call(
            "A_notes",
            "create",
            "calendar_entry",
            t.tilo_proposal(share={"team": "tm_sales"}, state="accepted", confirmed_by={"by": "u_owner", "at": t.T1}),
            meeting=t.meeting(),
        ),
    ),
    "tilo syncs the connected persons own google entry": (
        True,
        _call(
            "A_calendar_sync",
            "create",
            "calendar_entry",
            t.entry(created_by=pl.maker_tilo("A_calendar_sync", t.T0), source=copy.deepcopy(pl.GOOGLE_SOURCE)),
            source_owner="u_owner",
        ),
    ),
    "tilo syncs a google entry onto someone elses calendar": (
        False,
        _call(
            "A_calendar_sync",
            "create",
            "calendar_entry",
            t.entry(created_by=pl.maker_tilo("A_calendar_sync", t.T0), source=copy.deepcopy(pl.GOOGLE_SOURCE)),
            source_owner="u_riya",
        ),
    ),
    "tilo syncs a google entry with no source owner": (
        False,
        _call(
            "A_calendar_sync",
            "create",
            "calendar_entry",
            t.entry(created_by=pl.maker_tilo("A_calendar_sync", t.T0), source=copy.deepcopy(pl.GOOGLE_SOURCE)),
        ),
    ),
    "owner confirms a proposed entry": (
        True,
        _call("u_owner", "confirm", "calendar_entry", t.tilo_proposal(), meeting=t.meeting()),
    ),
    "teammate confirms a proposed entry": (
        False,
        _call("u_riya", "confirm", "calendar_entry", t.tilo_proposal(), meeting=t.meeting()),
    ),
    "owner confirms an accepted entry": (False, _call("u_owner", "confirm", "calendar_entry", t.entry())),
    "owner edits their unshared entry": (True, _call("u_owner", "edit", "calendar_entry", t.entry())),
    "teammate edits a shared entry": (False, _call("u_riya", "edit", "calendar_entry", t.shared_entry())),
    "owner reads an accepted tilo entry nobody confirmed": (
        False,
        _call(
            "u_owner",
            "read_full",
            "calendar_entry",
            t.tilo_proposal(state="accepted", confirmed_by={"by": "u_riya", "at": t.T1}),
            meeting=t.meeting(),
        ),
    ),
    "owner starts capture on their meeting": (True, _call("u_owner", "start_capture", "meeting", t.meeting())),
    "owner starts capture on a meeting attested by someone else": (
        False,
        _call(
            "u_owner",
            "start_capture",
            "meeting",
            t.meeting(attestation={"by": "u_riya", "at": t.T0, "notice_version": "1.0.0"}),
        ),
    ),
    "attestor not in the directory": (
        False,
        _call(
            "u_ghost",
            "start_capture",
            "meeting",
            t.meeting(owner="u_ghost", attestation={"by": "u_ghost", "at": t.T0, "notice_version": "1.0.0"}),
        ),
    ),
    "attendee starts capture": (False, _call("u_riya", "start_capture", "meeting", t.meeting())),
    "owner confirms the minutes card of their meeting": (True, _call("u_owner", "confirm", "meeting", t.meeting())),
    "attendee reads the minutes": (False, _call("u_riya", "read_status", "meeting", t.minuted_meeting())),
    "owner of the org reads someone elses minutes": (
        False,
        _call(
            "u_owner",
            "read_full",
            "meeting",
            t.minuted_meeting(
                by="u_riya", owner="u_riya", attestation={"by": "u_riya", "at": t.T0, "notice_version": "1.0.0"}
            ),
        ),
    ),
    "member sets their own org role": (False, _call("u_riya", "set_org_role", "person", t.person_in("u_riya"))),
    "member assigns a membership": (False, _call("u_riya", "assign_membership", "person", t.person_in("u_riya"))),
    "org owner assigns a membership": (True, _call("u_owner", "assign_membership", "person", t.person_in("u_riya"))),
    "org owner sets a role": (True, _call("u_owner", "set_org_role", "person", t.person_in("u_riya"))),
    "person edits their own record": (False, _call("u_riya", "edit", "person", t.person_in("u_riya"))),
    "org owner edits another persons record": (False, _call("u_owner", "edit", "person", t.person_in("u_riya"))),
    "person confirms a person record": (False, _call("u_riya", "confirm", "person", t.person_in("u_riya"))),
    "person starts capture on a person record": (
        False,
        _call("u_owner", "start_capture", "person", t.person_in("u_riya")),
    ),
}


@pytest.mark.parametrize("label", sorted(EDGE_CASES))
def test_PPL_10a_PE_03_to_PE_08_edge_case_matches_the_rules(label):
    ok, call = EDGE_CASES[label]
    assert _both(call)[1] is ok, label


def test_PPL_10a_PE_03_edge_cases_decide_never_allows_what_the_reference_refuses():
    for label, (ok, call) in EDGE_CASES.items():
        ref, got = _both(call)
        if got:
            assert ref, label
        if ok:
            assert ref, f"{label}: the case itself must be one the reference oracle permits"


# ---------------------------------------------------------------------------------------------
# 7. Fail closed
# ---------------------------------------------------------------------------------------------
def _base_request():
    return t.req("u_riya", "read_full", "work_item", t.own_item())


JUNK_VALUES = [None, 0, 1, 1.5, True, "", " ", "x", b"u_riya", [], {}, ["u_riya"], {"id": "wi_x"}]


@pytest.mark.parametrize("field", ["actor", "action", "record_kind", "record", "now"])
@pytest.mark.parametrize("junk", JUNK_VALUES, ids=lambda v: f"{type(v).__name__}-{str(v)[:10]}")
def test_PPL_10a_SEC_fail_closed_junk_in_any_field_is_a_refusal_not_an_error(field, junk):
    base = _base_request()
    assert access.decide(base, t.world_directory()).allowed  # control
    broken = dataclasses.replace(base, **{field: junk})
    assert access.decide(broken, t.world_directory()) == access.Verdict(False, None)


@pytest.mark.parametrize("field", ["meeting", "work_item", "pin"])
@pytest.mark.parametrize("junk", [0, "x", [], {}, {"id": "mt_weekly1"}, {**t.meeting(), "x": 1}, b"x"])
def test_PPL_10a_SEC_fail_closed_a_context_record_that_is_not_valid_is_a_refusal(field, junk):
    base = t.req("u_riya", "read_full", "work_item", t.tilo_item(), meeting=t.meeting())
    assert access.decide(base, t.world_directory()).allowed
    assert access.decide(dataclasses.replace(base, **{field: junk}), t.world_directory()) == access.Verdict(False, None)


@pytest.mark.parametrize("junk", ["riya", 5, ["u_riya"], "u_riya\n", t.u(0xFF55) + "_riya"])
def test_PPL_10a_SEC_fail_closed_a_bad_source_owner_is_a_refusal(junk):
    base = t.req(
        "A_notes",
        "create",
        "pinboard_item",
        t.personal_pin(
            created_by=pl.maker_tilo("A_notes", t.T0), source={"kind": "request", "ref": "rq_1", "evidence": []}
        ),
        source_owner="u_riya",
    )
    assert access.decide(base, t.world_directory()).allowed
    assert not access.decide(dataclasses.replace(base, source_owner=junk), t.world_directory()).allowed


def test_PPL_10a_SEC_fail_closed_a_bad_mentions_entry_is_a_refusal():
    base = t.req(
        "u_owner",
        "mention",
        "mention",
        t.tag(),
        pin=t.team_pin(),
        mentions=(t.tag(id="mn_old1", removed={"by": "u_owner", "at": t.T1}),),
    )
    assert access.decide(base, t.world_directory()).allowed
    for junk in ({"id": "mn_old1"}, {**t.tag(), "x": 1}, None, "x"):
        assert not access.decide(dataclasses.replace(base, mentions=(junk,)), t.world_directory()).allowed


@pytest.mark.parametrize(
    "now",
    [
        "2026-10-03",
        "2026-10-03T09:00:00Z",
        "2026-10-03T09:00:00.000+00:00",
        "2026-10-03T09:00:00.000Z\n",
        "2026-10-03 09:00:00.000Z",
        "2026-13-03T09:00:00.000Z",
        "2026-10-03T24:00:00.000Z",
        "2026-10-03T09:00:00.0Z",
        "".join(t.u(0xFF10 + int(c)) if c.isdigit() else c for c in "2026-10-03T09:00:00.000Z"),  # fullwidth digits
        "".join(t.u(0x966 + int(c)) if c.isdigit() else c for c in "2026-10-03T09:00:00.000Z"),  # Devanagari digits
    ],
)
def test_PPL_10a_SEC_fail_closed_a_malformed_timestamp_is_a_refusal(now):
    assert not t.allowed("u_riya", "read_full", "work_item", t.own_item(), now=now)


@pytest.mark.parametrize(
    "action",
    ["read", "READ_FULL", "delete", "", "read_full ", "edit\n", "read_all", "Edit", "mention ", "start-capture"],
)
def test_PPL_10a_SEC_fail_closed_an_unknown_action_is_a_refusal(action):
    assert not t.allowed("u_riya", action, "work_item", t.own_item())


@pytest.mark.parametrize("kind", ["note", "team", "Person", "work_items", "", "person\n", "pin"])
def test_PPL_10a_SEC_fail_closed_an_unknown_record_kind_is_a_refusal(kind):
    assert not t.allowed("u_riya", "read_full", kind, t.own_item())


def test_PPL_10a_SEC_fail_closed_a_record_of_the_wrong_kind_is_a_refusal():
    assert not t.allowed("u_riya", "read_full", "meeting", t.own_item())
    assert not t.allowed("u_riya", "read_full", "pinboard_item", t.own_item())
    assert not t.allowed("u_riya", "read_full", "work_item", t.personal_pin())


def test_PPL_10a_SEC_fail_closed_a_record_with_a_missing_or_extra_field_is_a_refusal():
    record = t.own_item()
    assert t.allowed("u_riya", "read_full", "work_item", record)
    for key in record:
        assert not t.allowed("u_riya", "read_full", "work_item", {k: v for k, v in record.items() if k != key}), key
    assert not t.allowed("u_riya", "read_full", "work_item", {**record, "x": 1})
    assert not t.allowed("u_riya", "read_full", "work_item", {**record, "flagged": "false"})


def test_PPL_10a_SEC_fail_closed_decide_given_no_request_or_no_directory_refuses():
    assert access.decide(None, t.world_directory()) == access.Verdict(False, None)
    assert access.decide(_base_request(), None) == access.Verdict(False, None)
    assert access.decide("not a request", t.world_directory()) == access.Verdict(False, None)


def test_PPL_10a_SEC_decide_is_deterministic_and_does_not_mutate_its_inputs():
    for name, case in t.ALL_CASES:
        request, d = crossref.case_request(case)
        before_request, before_persons = copy.deepcopy(request), copy.deepcopy(dict(d.persons))
        first = access.decide(request, d)
        second = access.decide(request, d)
        assert first == second, name
        assert request == before_request and dict(d.persons) == before_persons, name
        access.read(request, d)
        assert request == before_request, name


# ---------------------------------------------------------------------------------------------
# 8. project / read: allowlists, deep copies, 404 shape
# ---------------------------------------------------------------------------------------------
LEAKY_PERSON = t.make_person(
    "u_riya", t.SENTINEL, aliases=("Alias-Secret",), email="secret.mail@example.com", tz="Europe/Paris"
)


@pytest.mark.parametrize("view", ["directory", "membership"])
def test_PPL_10a_PE_20_person_views_carry_only_their_allowlist(view):
    got = access.project("person", view, LEAKY_PERSON)
    assert set(got) == set(t.VIEW_KEYS[view])
    assert got["id"] == "u_riya" and got["display_name"] == t.SENTINEL
    for secret in ("secret.mail@example.com", "Alias-Secret", "Europe/Paris", "preferred_channel", "created_by"):
        assert secret not in t.dump(got), secret
    if view == "membership":
        assert got["org_role"] == "member" and got["memberships"] == LEAKY_PERSON["memberships"]
        assert got["memberships"] is not LEAKY_PERSON["memberships"]


def test_PPL_10a_PE_20_full_view_is_a_deep_copy_and_only_the_person_reads_their_own_email():
    got = access.project("person", "full", LEAKY_PERSON)
    assert got == LEAKY_PERSON and got is not LEAKY_PERSON
    got["memberships"].append("x")
    got["aliases"].append("x")
    assert len(LEAKY_PERSON["memberships"]) == 1 and LEAKY_PERSON["aliases"] == ["Alias-Secret"]
    # decide gives the full person view to no one but the person
    d = directory.Directory.of([LEAKY_PERSON, *[p for p in t.world_persons() if p["id"] != "u_riya"]])
    for viewer in ("u_owner", "u_sam", "u_lee", "u_ext", "A_notes"):
        assert access.read(t.req(viewer, "read_full", "person", LEAKY_PERSON), d) is None, viewer
    assert access.read(t.req("u_riya", "read_full", "person", LEAKY_PERSON), d) == LEAKY_PERSON
    for viewer in ("u_owner",):  # a teammate: directory view only
        out = access.read(t.req(viewer, "read_directory", "person", LEAKY_PERSON), d)
        assert set(out) == {"id", "display_name"}
        assert access.read(t.req(viewer, "read_membership", "person", LEAKY_PERSON), d) is not None  # an org owner too


@pytest.mark.parametrize(
    ("kind", "record", "expected"),
    [
        ("work_item", t.own_item(title="Plan"), {"id": "wi_own1", "title": "Plan", "status": "open", "due": None}),
        (
            "pinboard_item",
            t.team_pin(),
            {"id": "pb_deadline1", "title": "Q4 deadline", "status": "active", "due": "2026-10-31"},
        ),
        ("calendar_entry", t.entry(), {"id": "ce_plan1", "title": "Planning"}),  # no status or due on an entry
        ("meeting", t.meeting(), {"id": "mt_weekly1", "title": "Weekly sync", "status": "scheduled"}),
        ("person", t.person_in("u_riya"), {"id": "u_riya"}),
    ],
)
def test_PPL_10a_PE_03_status_view_keeps_only_the_keys_the_record_has(kind, record, expected):
    assert access.project(kind, "status", record) == expected


def test_PPL_10a_PE_04_busy_view_is_the_interval_only_and_none_without_an_end():
    record = t.entry(title=t.SENTINEL)
    got = access.project("calendar_entry", "busy", record)
    assert got == {"start": t.T1, "end": t.T2}
    assert t.SENTINEL not in t.dump(got)
    assert access.project("calendar_entry", "busy", t.entry(end=None)) is None  # BQ-PPL10-9
    for kind, other in (
        ("work_item", t.own_item()),
        ("pinboard_item", t.team_pin()),
        ("meeting", t.meeting()),
        ("person", LEAKY_PERSON),
    ):
        assert access.project(kind, "busy", other) is None, kind


@pytest.mark.parametrize(
    ("kind", "view"),
    [
        ("work_item", "directory"),
        ("calendar_entry", "membership"),
        ("pinboard_item", "directory"),
        ("meeting", "membership"),
    ],
)
def test_PPL_10a_PE_20_person_views_do_not_apply_to_other_kinds(kind, view):
    record = {
        "work_item": t.own_item(),
        "calendar_entry": t.entry(),
        "pinboard_item": t.team_pin(),
        "meeting": t.meeting(),
    }[kind]
    assert access.project(kind, view, record) is None


@pytest.mark.parametrize(
    ("kind", "view"),
    [
        ("note", "full"),
        ("work_item", "everything"),
        ("work_item", ""),
        ("", "full"),
        (None, "full"),
        ("work_item", None),
        ("Work_Item", "full"),
        ("work_item", "FULL"),
    ],
)
def test_PPL_10a_PE_20_project_with_an_unknown_kind_or_view_is_none(kind, view):
    assert access.project(kind, view, t.own_item()) is None


def test_PPL_10a_PE_20_project_full_is_a_deep_copy_of_every_kind():
    for kind, record, extras in _org_records().values():
        out = access.project(kind, "full", record)
        assert out == record and out is not record
        out["injected"] = 1
        assert "injected" not in record


def test_PPL_10a_PE_20_read_is_none_for_a_refused_read_and_for_any_write_action():
    d = t.world_directory()
    assert access.read(t.req("u_sam", "read_full", "work_item", t.own_item()), d) is None
    assert access.read(t.req("u_riya", "read_full", "work_item", t.own_item()), d) == t.own_item()
    assert access.read(t.req("u_riya", "edit", "work_item", t.own_item()), d) is None  # allowed, but not a read
    assert access.read(t.req("u_riya", "mark_done", "work_item", t.own_item()), d) is None
    assert access.read(t.req("u_riya", "read_full", "work_item", {"id": "wi_x"}), d) is None
    assert access.read(None, d) is None


def test_PPL_10a_PE_11_an_agent_id_reads_nothing_the_assistant_reads_as_the_person():
    d = t.world_directory()
    for kind, record, extras in _org_records().values():
        for action in t.READ_ACTIONS:
            assert access.read(t.req("A_assistant", action, kind, record, **extras), d) is None, (kind, action)


def test_PPL_10a_PE_20_read_answers_with_the_view_of_the_action_not_a_bigger_one():
    d = t.world_directory()
    own = t.own_item()
    assigned = pl.work_item()  # u_owner assigned it to u_riya
    full = access.read(t.req("u_riya", "read_full", "work_item", assigned), d)
    status = access.read(t.req("u_owner", "read_status", "work_item", assigned), d)
    assert full == assigned
    assert status == {k: assigned[k] for k in ("id", "title", "status", "due")}
    assert "source" not in status and "history" not in status and "evidence" not in t.dump(status)
    assert (
        access.read(t.req("u_owner", "read_full", "work_item", assigned), d) is None
    )  # the assigner reads status only
    assert access.read(t.req("u_riya", "read_status", "work_item", own), d) == {
        "id": "wi_own1",
        "title": own["title"],
        "status": "open",
        "due": None,
    }


# ---------------------------------------------------------------------------------------------
# 9. No record text in a repr
# ---------------------------------------------------------------------------------------------
def test_PPL_10a_PE_20_reprs_of_requests_directories_and_verdicts_carry_no_record_text():
    """Ambiguity A in the module docstring: the rule (no record text in a repr) wins over the sketch."""
    person = t.make_person("u_riya", t.SENTINEL, aliases=(t.SENTINEL + "-alias",), email="sentinel.mail@example.com")
    d = directory.Directory.of([person, *[p for p in t.world_persons() if p["id"] != "u_riya"]])
    r = t.req("u_riya", "read_full", "work_item", t.own_item(title=t.SENTINEL), meeting=t.meeting(title=t.SENTINEL))
    for obj in (r, d, access.decide(r, d), repr(r), repr(d)):
        shown = repr(obj) if not isinstance(obj, str) else obj
        assert t.SENTINEL not in shown and "sentinel.mail" not in shown
        assert t.SENTINEL not in str(obj)


def test_PPL_10a_SEC_refusals_and_errors_never_carry_record_text():
    record = t.own_item(title=t.SENTINEL)
    bad = {**record, "x_" + "extra": t.SENTINEL}
    with pytest.raises(errors.PeopleInputError) as caught:
        crossref.case_request(
            {"now": t.SENTINEL, "persons": {}, "record": {"kind": t.SENTINEL, "data": bad}, "request": {}}
        )
    assert t.SENTINEL not in str(caught.value) and t.SENTINEL not in repr(caught.value)
    import traceback

    assert t.SENTINEL not in "".join(traceback.format_exception(caught.value))
    assert not t.allowed("u_riya", "read_full", "work_item", bad)


# ---------------------------------------------------------------------------------------------
# 10. Properties
# ---------------------------------------------------------------------------------------------
_WORD = st.text(alphabet="abcdefghijklmnopqrstuvwxyz", min_size=10, max_size=16)
_ACTORS = ["u_owner", "u_riya", "u_sam", "u_lee", "u_ext", "A_notes", "A_calendar_sync", "u_ghost"]


def _canary_records(c):
    riya = t.make_person("u_riya", f"dn-{c}", aliases=(f"a-{c}",), email=f"{c}@example.com", tz="Europe/Paris")
    entry = pl.calendar_entry(
        id="ce_riya1",
        owner="u_riya",
        title=f"t-{c}",
        created_by=pl.maker_person("u_riya"),
        source={"kind": "google", "ref": f"g{c}", "synced_at": t.T0},
    )
    return {
        "pin": ("pinboard_item", t.team_pin(title=f"t-{c}", body=f"b-{c}"), {}),
        "personal_pin": ("pinboard_item", t.personal_pin(title=f"t-{c}", body=f"b-{c}"), {}),
        "assigned_item": ("work_item", pl.work_item(title=f"t-{c}", due_text=f"d-{c}"), {}),
        "own_item": ("work_item", t.own_item(title=f"t-{c}", due_text=f"d-{c}"), {}),
        "entry": ("calendar_entry", entry, {}),
        "shared": ("calendar_entry", pl.calendar_entry(title=f"t-{c}", share={"team": "tm_sales"}), {}),
        "meeting": ("meeting", t.meeting(title=f"t-{c}", attendees=[{"name": f"n-{c}", "user": "u_riya"}]), {}),
        "person": ("person", riya, {}),
    }, riya


@SETTINGS
@given(
    c=_WORD,
    which=st.sampled_from(["pin", "personal_pin", "assigned_item", "own_item", "entry", "shared", "meeting", "person"]),
    actor=st.sampled_from(_ACTORS),
    action=st.sampled_from(t.READ_ACTIONS),
)
def test_PPL_10a_PE_20_property_no_allowed_read_exposes_a_field_outside_its_view(c, which, actor, action):
    records, riya = _canary_records(c)
    kind, record, extras = records[which]
    d = directory.Directory.of([riya if p["id"] == "u_riya" else p for p in t.world_persons()])
    request = t.req(actor, action, kind, record, **extras)
    v = access.decide(request, d)
    out = access.read(request, d)
    if not v.allowed:
        assert out is None
        return
    assert v.view == action[5:] and not actor.startswith("A_")
    if v.view == "full":
        assert out == record
        return
    if out is None:  # a busy view of an entry with no end
        return
    assert set(out) <= set(t.VIEW_KEYS[v.view])
    shown = t.dump(out)
    for secret in (
        f"b-{c}",
        f"d-{c}",
        f"a-{c}",
        f"{c}@example.com",
        f"g{c}",
        f"n-{c}",
        "Europe/Paris",
        "preferred_channel",
    ):
        assert secret not in shown, (which, actor, action, secret)
    if v.view == "busy":
        assert f"t-{c}" not in shown


_JUNK = st.one_of(
    st.none(),
    st.integers(),
    st.floats(allow_nan=True),
    st.text(max_size=12),
    st.binary(max_size=4),
    st.lists(st.integers(), max_size=3),
    st.dictionaries(st.text(max_size=4), st.integers(), max_size=3),
)


_NOT_THE_BASE_VALUE = {
    "actor": lambda v: v != "u_riya",
    "action": lambda v: v not in t.ACTIONS,
    "record_kind": lambda v: v != "work_item",
    "record": lambda v: True,  # a random dict is never a whole work item
    "now": lambda v: not (isinstance(v, str) and re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9:]{8}\.[0-9]{3}Z", v)),
}


@SETTINGS
@given(field=st.sampled_from(sorted(_NOT_THE_BASE_VALUE)), junk=_JUNK)
def test_PPL_10a_SEC_property_junk_in_a_required_field_never_raises_and_never_allows(field, junk):
    if not _NOT_THE_BASE_VALUE[field](junk):
        return
    got = access.decide(dataclasses.replace(_base_request(), **{field: junk}), t.world_directory())
    assert got == access.Verdict(False, None)


@SETTINGS
@given(actor=st.sampled_from(_ACTORS), action=st.sampled_from(t.ACTIONS), which=st.sampled_from(sorted(_org_records())))
def test_PPL_10a_PE_07_property_tilo_is_only_ever_allowed_to_create_or_tag(actor, action, which):
    kind, record, extras = _org_records()[which]
    got = t.verdict(actor, action, kind, record, **extras)
    if actor.startswith("A_") and got.allowed:
        assert action == "create" or (kind == "mention" and action == "mention")
    if not actor.startswith("A_") and actor not in t.world_directory().persons:
        assert got.allowed is False


@SETTINGS
@given(
    actor=st.sampled_from(["u_owner", "u_riya", "u_sam", "u_lee"]),
    action=st.sampled_from(t.ACTIONS),
    which=st.sampled_from(sorted(_org_records())),
)
def test_PPL_10a_PE_17_property_a_person_of_this_org_never_beats_the_reference_on_this_orgs_records(
    actor, action, which
):
    kind, record, extras = _org_records()[which]
    got = t.allowed(actor, action, kind, record, **extras)
    if got and (kind, action) not in GRANTS:
        assert t.ref_allows(actor, action, kind, record, **extras), (actor, action, which)
