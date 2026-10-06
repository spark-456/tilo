"""PPL-10c: `tilo_people.check_write`, the problems with storing a new version of a record
(contracts/people.rules.md PE-02, PE-04, PE-07, PE-17, PE-19; BQ-PPL10-6, -7, -11). Spec: API.md
section 4 (the rules and the MAY table).

A caller runs `decide`, builds `after` with stamps `{by: actor, at: now}` from the session and the
server clock, runs `check_write`, then stores with compare-and-set. These tests drive that boundary
with the stamps right and then wrong, one defect at a time, and assert the exact problem codes.

Ambiguities settled here (PRD / rule in brackets; also listed in the hand-back):

- A: where a defect also makes `decide(request with record=after)` refuse, the extra code
  `after_not_allowed` may appear next to the specific one; those rows assert the specific code is
  present and nothing outside the allowed set appears. Rows that are isolated assert the exact tuple.
  [API.md section 4, last paragraph]
- B: API.md says `after_not_allowed` catches "a share on an entry that is not accepted", but a share on
  a non-accepted entry fails calendar_entry.schema.json (`else: share null`), and rule 1 returns
  exactly `("schema",)` for a schema failure. The schema rule wins: that case is `("schema",)`.
- C: a read action that `decide` refuses is `("not_allowed",)` (rule 1 lists it first); a read action
  that `decide` allows is `("unsupported",)`. [API.md section 4 rule 1]
- D: a person-made pin removed with change `undone`, or a Tilo-made personal pin removed with
  `removed`, are not tested either way: the table is open about which wins. Only the unambiguous
  pairs are asserted. [BQ-PPL10-6]
"""

from __future__ import annotations

import copy
import dataclasses
from datetime import UTC, datetime, timedelta

import _ppl10_testlib as t
import pytest
from _ppl10_testlib import access, pl, writes
from hypothesis import HealthCheck, Phase, given, settings
from hypothesis import strategies as st

SETTINGS = settings(
    max_examples=60,
    deadline=None,
    database=None,
    phases=(Phase.explicit, Phase.generate),  # no shrinking: a failing run reports at once
    suppress_health_check=[HealthCheck.too_slow],
)
PROBLEMS = (
    "not_allowed",
    "unsupported",
    "schema",
    "identity",
    "immutable",
    "stamp",
    "transition",
    "history",
    "owner_not_member",
    "after_not_allowed",
    "snooze_range",
)
NOW = t.NOW


def hist(actor, change, status, at=NOW):
    return {"at": at, "by": actor, "change": change, "status": status}


def moved(before, *, history=None, updated=True, **changes):
    """`before` with `changes`, one history entry appended and `updated_at` set to now."""
    after = copy.deepcopy(before)
    after.update(copy.deepcopy(changes))
    if history is not None:
        after["history"] = [*copy.deepcopy(before["history"]), copy.deepcopy(history)]
    if updated:
        after["updated_at"] = NOW
    return after


def check(request, after, d=None):
    return writes.check_write(request, after, d if d is not None else t.world_directory())


def assert_well_formed(result):
    assert isinstance(result, tuple) and all(isinstance(p, str) for p in result)
    assert list(result) == sorted(set(result)), "sorted and unique"
    assert set(result) <= set(PROBLEMS)


def stamp_after(days=0, millis=0):
    dt = datetime.strptime(NOW, "%Y-%m-%dT%H:%M:%S.%fZ").replace(tzinfo=UTC) + timedelta(days=days, milliseconds=millis)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


# ---------------------------------------------------------------------------------------------
# Baselines: (request, after) pairs that must store, so each defect below is the only defect
# ---------------------------------------------------------------------------------------------
def wi_edit():
    before = t.own_item(updated_at=t.T0)
    return t.req("u_riya", "edit", "work_item", before), moved(
        before, history=hist("u_riya", "edited", "open"), title="New title"
    )


def wi_reopen():
    before = t.own_item(
        status="done",
        updated_at=t.T1,
        history=[pl.history_entry("u_riya", "created", "open", t.T0), pl.history_entry("u_riya", "done", "done", t.T1)],
    )
    return t.req("u_riya", "edit", "work_item", before), moved(
        before, history=hist("u_riya", "reopened", "open"), status="open"
    )


def wi_confirm():
    before = t.proposed_tilo_item()
    request = t.req("u_owner", "confirm", "work_item", before, meeting=t.meeting())
    after = moved(
        before,
        history=hist("u_owner", "confirmed", "open"),
        status="open",
        confirmed_by={"by": "u_owner", "at": NOW},
    )
    return request, after


def wi_done():
    before = t.own_item(updated_at=t.T0)
    return t.req("u_riya", "mark_done", "work_item", before), moved(
        before, history=hist("u_riya", "done", "done"), status="done"
    )


def pin_edit():
    before = t.team_pin(updated_at=t.T0)
    return t.req("u_owner", "edit", "pinboard_item", before), moved(
        before, history=hist("u_owner", "edited", "active"), title="New title"
    )


def pin_confirm():
    before = t.team_pin(
        id="pb_prop1", status="proposed", history=[pl.history_entry("u_owner", "created", "proposed", t.T0)]
    )
    after = moved(
        before,
        history=hist("u_owner", "accepted", "active"),
        status="active",
        confirmed_by={"by": "u_owner", "at": NOW},
    )
    return t.req("u_owner", "confirm", "pinboard_item", before), after


def personal_pin_edit():
    before = t.personal_pin(updated_at=t.T0)
    return t.req("u_riya", "edit", "pinboard_item", before), moved(
        before, history=hist("u_riya", "edited", "active"), title="Mine"
    )


def cal_edit():
    before = t.entry(updated_at=t.T0)
    return t.req("u_owner", "edit", "calendar_entry", before), moved(before, title="Moved")


def cal_confirm():
    before = t.tilo_proposal()
    after = moved(before, state="accepted", confirmed_by={"by": "u_owner", "at": NOW})
    return t.req("u_owner", "confirm", "calendar_entry", before, meeting=t.meeting()), after


def google_edit():
    before = t.entry(
        id="ce_g1",
        created_by=pl.maker_tilo("A_calendar_sync", t.T0),
        source=copy.deepcopy(pl.GOOGLE_SOURCE),
        updated_at=t.T0,
    )
    return t.req("u_owner", "edit", "calendar_entry", before, source_owner="u_owner"), moved(
        before, share={"team": "tm_sales"}
    )


def mtg_edit():
    before = t.meeting()
    return t.req("u_owner", "edit", "meeting", before), {**copy.deepcopy(before), "title": "Weekly sync v2"}


def _minuted_unconfirmed():
    return pl.meeting(status="minuted", transcript=copy.deepcopy(pl.ART), minutes=copy.deepcopy(pl.ART_MINUTES))


def mtg_confirm():
    before = _minuted_unconfirmed()
    return t.req("u_owner", "confirm", "meeting", before), {
        **copy.deepcopy(before),
        "minutes_confirmed_by": {"by": "u_owner", "at": NOW},
    }


def untag():
    before = t.tag()
    return t.req("u_riya", "untag", "mention", before, pin=t.team_pin()), {
        **copy.deepcopy(before),
        "removed": {"by": "u_riya", "at": NOW},
    }


def assign():
    before = t.person_in("u_riya")
    after = copy.deepcopy(before)
    after["memberships"].append(t.member("tm_ops", "u_owner", NOW))
    return t.req("u_owner", "assign_membership", "person", before), after


def promote():
    before = t.person_in("u_riya")
    return t.req("u_owner", "set_org_role", "person", before), {**copy.deepcopy(before), "org_role": "owner"}


EDITS = {
    "wi_edit": wi_edit,
    "wi_reopen": wi_reopen,
    "wi_confirm": wi_confirm,
    "wi_done": wi_done,
    "pin_edit": pin_edit,
    "pin_confirm": pin_confirm,
    "personal_pin_edit": personal_pin_edit,
    "cal_edit": cal_edit,
    "cal_confirm": cal_confirm,
    "google_edit": google_edit,
    "mtg_edit": mtg_edit,
    "mtg_confirm": mtg_confirm,
    "untag": untag,
    "assign": assign,
    "promote": promote,
}


def c_wi_person():
    record = t.own_item(
        created_by=pl.maker_person("u_riya", NOW),
        created_at=NOW,
        updated_at=NOW,
        history=[hist("u_riya", "created", "open")],
    )
    return t.req("u_riya", "create", "work_item", record), record


def c_wi_tilo():
    record = t.proposed_tilo_item(
        created_by=pl.maker_tilo("A_notes", NOW),
        assigned_by={"by": "u_owner", "at": NOW},
        created_at=NOW,
        updated_at=NOW,
        history=[hist("A_notes", "created", "proposed")],
    )
    return t.req("A_notes", "create", "work_item", record, meeting=t.meeting()), record


def c_pin_team():
    record = t.team_pin(
        created_by=pl.maker_person("u_owner", NOW),
        created_at=NOW,
        updated_at=NOW,
        history=[hist("u_owner", "created", "active")],
    )
    return t.req("u_owner", "create", "pinboard_item", record), record


def c_pin_personal():
    record = t.personal_pin(
        created_by=pl.maker_person("u_riya", NOW),
        created_at=NOW,
        updated_at=NOW,
        history=[hist("u_riya", "created", "active")],
    )
    return t.req("u_riya", "create", "pinboard_item", record), record


def c_pin_tilo():
    record = t.tilo_team_pin(
        status="proposed",
        confirmed_by=None,
        created_by=pl.maker_tilo("A_notes", NOW),
        created_at=NOW,
        updated_at=NOW,
        history=[hist("A_notes", "created", "proposed")],
    )
    return t.req("A_notes", "create", "pinboard_item", record, meeting=t.meeting()), record


def c_cal_person():
    record = t.entry(created_by=pl.maker_person("u_owner", NOW), updated_at=NOW)
    return t.req("u_owner", "create", "calendar_entry", record), record


def c_cal_tilo():
    record = t.tilo_proposal(created_by=pl.maker_tilo("A_notes", NOW), updated_at=NOW)
    return t.req("A_notes", "create", "calendar_entry", record, meeting=t.meeting()), record


def c_cal_google():
    record = t.entry(
        id="ce_g1",
        created_by=pl.maker_tilo("A_calendar_sync", NOW),
        source={"kind": "google", "ref": "evt_abc123", "synced_at": NOW},
        updated_at=NOW,
    )
    return t.req("A_calendar_sync", "create", "calendar_entry", record, source_owner="u_owner"), record


def c_meeting():
    record = t.meeting(
        id="mt_new1",
        owner="u_riya",
        attestation={"by": "u_riya", "at": t.T0, "notice_version": "1.0.0"},
        created_at=NOW,
    )
    return t.req("u_riya", "create", "meeting", record), record


def c_person():
    record = t.make_person("u_new", "Nia New", teams=("tm_sales",), by="u_owner", at=NOW)
    return t.req("u_owner", "create", "person", record), record


def c_mention():
    record = t.tag(id="mn_new1", added_by=pl.maker_person("u_owner", NOW), removed=None)
    return t.req("u_owner", "mention", "mention", record, pin=t.team_pin()), record


def c_mention_tilo():
    record = t.tag(id="mn_new2", pin_id="pb_tilo1", added_by=pl.maker_tilo("A_notes", NOW), removed=None)
    return t.req("A_notes", "mention", "mention", record, pin=t.tilo_team_pin(), meeting=t.meeting()), record


CREATES = {
    "c_wi_person": c_wi_person,
    "c_wi_tilo": c_wi_tilo,
    "c_pin_team": c_pin_team,
    "c_pin_personal": c_pin_personal,
    "c_pin_tilo": c_pin_tilo,
    "c_cal_person": c_cal_person,
    "c_cal_tilo": c_cal_tilo,
    "c_cal_google": c_cal_google,
    "c_meeting": c_meeting,
    "c_person": c_person,
    "c_mention": c_mention,
    "c_mention_tilo": c_mention_tilo,
}
BASELINES = {**EDITS, **CREATES}


@pytest.mark.parametrize("name", sorted(BASELINES))
def test_PPL_10c_PE_19_a_correctly_stamped_write_stores(name):
    request, after = BASELINES[name]()
    assert check(request, after) == (), name


def test_PPL_10c_PE_19_the_baselines_are_ones_the_reference_oracle_permits():
    """Guard for these tests themselves: each request is one the reference grants (G1, G2 aside)."""
    for name, make in BASELINES.items():
        request, _ = make()
        extras = {
            k: getattr(request, k)
            for k in ("meeting", "work_item", "source_owner", "pin")
            if getattr(request, k) is not None
        }
        if request.mentions:
            extras["mentions"] = request.mentions
        grant = (request.record_kind, request.action) in {("person", "create"), ("meeting", "create")}
        assert grant or t.ref_allows(request.actor, request.action, request.record_kind, request.record, **extras), name


def test_PPL_10c_PE_19_problem_codes_and_inputs_are_pinned():
    assert tuple(writes.WRITE_PROBLEMS) == PROBLEMS


def test_PPL_10c_PE_19_check_write_neither_mutates_its_inputs_nor_differs_between_runs():
    for name, make in BASELINES.items():
        request, after = make()
        d = t.world_directory()
        before = (copy.deepcopy(request), copy.deepcopy(after), copy.deepcopy(dict(d.persons)))
        first = writes.check_write(request, after, d)
        assert writes.check_write(request, after, d) == first
        assert (request, after, dict(d.persons)) == before, name


# ---------------------------------------------------------------------------------------------
# 1. Gates: not allowed, unsupported, schema
# ---------------------------------------------------------------------------------------------
def test_PPL_10c_PE_02_a_write_decide_refuses_is_not_allowed_whatever_the_after_says():
    request, after = wi_edit()
    assert check(dataclasses.replace(request, actor="u_sam"), after) == ("not_allowed",)  # another person's item
    assert check(dataclasses.replace(request, actor="u_owner"), after) == ("not_allowed",)  # a manager
    assert check(dataclasses.replace(request, actor="u_ext"), after) == ("not_allowed",)  # another org
    assert check(dataclasses.replace(request, actor="A_notes"), after) == ("not_allowed",)  # Tilo edits nothing
    assert check(dataclasses.replace(request, actor="system"), after) == ("not_allowed",)  # not an actor at all
    assert check(dataclasses.replace(request, actor="u_ghost"), after) == ("not_allowed",)
    garbage = {"nonsense": True}
    assert check(dataclasses.replace(request, actor="u_sam"), garbage) == ("not_allowed",)  # not_allowed comes first


@pytest.mark.parametrize(
    "action", ["read_full", "read_status", "read_busy", "read_directory", "read_membership", "start_capture"]
)
def test_PPL_10c_PE_19_a_read_or_a_capture_is_not_a_write(action):
    """Ambiguity C: allowed reads are `unsupported`, refused ones are `not_allowed`."""
    d = t.world_directory()
    cases = {
        "read_full": ("u_riya", "work_item", t.own_item()),
        "read_status": ("u_riya", "work_item", t.own_item()),
        "read_busy": ("u_owner", "calendar_entry", t.entry()),
        "read_directory": ("u_owner", "person", t.person_in("u_riya")),
        "read_membership": ("u_owner", "person", t.person_in("u_riya")),
        "start_capture": ("u_owner", "meeting", t.meeting()),
    }
    actor, kind, record = cases[action]
    assert t.allowed(actor, action, kind, record, d), "control"
    assert writes.check_write(t.req(actor, action, kind, record), copy.deepcopy(record), d) == ("unsupported",)
    assert not t.allowed("u_sam", action, kind, record, d)  # u_sam shares no team with any of these people
    assert writes.check_write(t.req("u_sam", action, kind, record), copy.deepcopy(record), d) == ("not_allowed",)


@pytest.mark.parametrize("after", [None, [], "x", 5, {}, {"id": "wi_own1"}, b"x"])
def test_PPL_10c_PE_19_an_after_that_is_not_a_record_is_a_schema_problem(after):
    request, _ = wi_edit()
    assert check(request, after) == ("schema",)


def test_PPL_10c_PE_19_an_after_with_an_extra_or_missing_field_or_a_wrong_type_is_a_schema_problem():
    request, after = wi_edit()
    assert check(request, {**after, "x_extra": 1}) == ("schema",)
    assert check(request, {k: v for k, v in after.items() if k != "flagged"}) == ("schema",)
    assert check(request, {**after, "flagged": "no"}) == ("schema",)
    assert check(request, {**after, "title": "x" * 141}) == ("schema",)
    assert check(request, {**after, "due": "2026-13-45"}) == ("schema",)
    assert check(request, {**after, "history": []}) == ("schema",)
    wrong_kind = t.team_pin()
    assert check(request, wrong_kind) == ("schema",)  # a pin is not a work item


def test_PPL_10c_PE_19_never_raises_on_a_junk_request():
    _, after = wi_edit()
    d = t.world_directory()
    for request in (
        None,
        5,
        "x",
        object(),
        {},
        access.AccessRequest(actor=None, action=None, record_kind=None, record=None, now=None),
    ):
        result = writes.check_write(request, after, d)
        assert_well_formed(result)
        assert result == ("not_allowed",)
    assert writes.check_write(wi_edit()[0], after, None) == ("not_allowed",)


# ---------------------------------------------------------------------------------------------
# 2. Rows of the MAY table: one defect at a time
# ---------------------------------------------------------------------------------------------
def _set(**kw):
    return lambda a: {**a, **copy.deepcopy(kw)}


def _hist_set(fn):
    def apply(a):
        a = copy.deepcopy(a)
        a["history"] = fn(a["history"])
        return a

    return apply


def _last(**kw):
    return _hist_set(lambda h: [*h[:-1], {**h[-1], **kw}])


# Rows are (label, baseline, mutate, exact tuple or None, codes that must be present, codes that may also be present).
def _exact(label, base, mutate, codes):
    return (label, base, mutate, codes, (), ())


def _has(label, base, mutate, must, may=()):
    return (label, base, mutate, None, must, may)


def _ident(label, base, mutate):
    """An id or org change: `identity`, and the same field is also outside the MAY set."""
    return _has(label, base, mutate, ("identity",), ("immutable", "after_not_allowed"))


EDIT_ROWS = [
    # work item edit (PE-07: an edit changes only title, due, snooze; status moves by named actions)
    _exact("wi_edit due and due_text", "wi_edit", _set(due="2026-10-20", due_text="by the 20th"), ()),
    _exact(
        "wi_edit snooze within 30 days",
        "wi_edit",
        lambda a: {**_last(change="snoozed")(a), "snoozed_until": stamp_after(days=7)},
        (),
    ),
    _exact(
        "wi_edit snooze exactly 30 days",
        "wi_edit",
        lambda a: {**_last(change="snoozed")(a), "snoozed_until": stamp_after(days=30)},
        (),
    ),
    _exact(
        "wi_edit snooze one millisecond ahead",
        "wi_edit",
        lambda a: {**_last(change="snoozed")(a), "snoozed_until": stamp_after(millis=1)},
        (),
    ),
    _exact(
        "wi_edit snooze one millisecond over 30 days",
        "wi_edit",
        lambda a: {**_last(change="snoozed")(a), "snoozed_until": stamp_after(days=30, millis=1)},
        ("snooze_range",),
    ),
    _exact(
        "wi_edit snooze equal to now",
        "wi_edit",
        lambda a: {**_last(change="snoozed")(a), "snoozed_until": NOW},
        ("snooze_range",),
    ),
    _exact(
        "wi_edit snooze in the past",
        "wi_edit",
        lambda a: {**_last(change="snoozed")(a), "snoozed_until": t.T0},
        ("snooze_range",),
    ),
    _exact(
        "wi_edit snooze a year ahead",
        "wi_edit",
        lambda a: {**_last(change="snoozed")(a), "snoozed_until": "2027-10-03T09:00:00.000Z"},
        ("snooze_range",),
    ),
    _exact("wi_edit reassign request", "wi_edit", _last(change="reassign_requested"), ()),
    _exact("wi_reopen done to open with reopened", "wi_reopen", lambda a: a, ()),
    _exact(
        "wi_edit open to done by edit",
        "wi_edit",
        lambda a: {**_last(status="done")(a), "status": "done"},
        ("transition",),
    ),
    _exact(
        "wi_edit open to dropped by edit",
        "wi_edit",
        lambda a: {**_last(status="dropped")(a), "status": "dropped"},
        ("transition",),
    ),
    _has(
        "wi_edit open to proposed by edit",
        "wi_edit",
        lambda a: {**_last(status="proposed")(a), "status": "proposed"},
        ("transition",),
        ("after_not_allowed",),
    ),
    # work item edit: immutable fields (PE-07: source, owner, assigned_by, created_by, confirmed_by never change)
    _has("wi_edit owner changed", "wi_edit", _set(owner="u_sam"), ("immutable",), ("after_not_allowed",)),
    _has(
        "wi_edit source changed",
        "wi_edit",
        _set(source={"kind": "meeting", "ref": "mt_weekly1", "evidence": ["u0001"]}),
        ("immutable",),
    ),
    _has(
        "wi_edit created_by changed",
        "wi_edit",
        _set(created_by=pl.maker_person("u_sam", t.T0)),
        ("immutable",),
        ("after_not_allowed",),
    ),
    _has(
        "wi_edit created_by stamp backdated",
        "wi_edit",
        _set(created_by=pl.maker_person("u_riya", t.T1)),
        ("immutable",),
    ),
    _has("wi_edit assigned_by added", "wi_edit", _set(assigned_by={"by": "u_riya", "at": t.T0}), ("immutable",)),
    _has(
        "wi_edit confirmed_by set by edit",
        "wi_edit",
        _set(confirmed_by={"by": "u_riya", "at": NOW}),
        ("immutable",),
        ("after_not_allowed",),
    ),
    _has("wi_edit flagged raised", "wi_edit", _set(flagged=True), ("immutable",)),
    _has("wi_edit created_at changed", "wi_edit", _set(created_at=NOW), ("immutable",)),
    _ident("wi_edit id changed", "wi_edit", _set(id="wi_other1")),
    _ident("wi_edit org changed", "wi_edit", _set(org_id=t.OTHER_ORG)),
    # work item edit: history is append-only and one entry per write
    _exact("wi_edit history not grown", "wi_edit", _hist_set(lambda h: h[:-1]), ("history",)),
    _exact("wi_edit two entries added", "wi_edit", _hist_set(lambda h: [*h, h[-1]]), ("history",)),
    _exact("wi_edit entry by another person", "wi_edit", _last(by="u_sam"), ("history",)),
    _exact("wi_edit entry with an old stamp", "wi_edit", _last(at=t.T1), ("history",)),
    _exact("wi_edit entry with a future stamp", "wi_edit", _last(at=t.FUTURE), ("history",)),
    _exact("wi_edit entry status does not match the item", "wi_edit", _last(status="done"), ("history",)),
    _has(
        "wi_edit entry change confirmed", "wi_edit", _last(change="confirmed"), ("history",), ("after_not_allowed",)
    ),  # S3 on after
    _exact("wi_edit entry change done", "wi_edit", _last(change="done"), ("history",)),
    _exact("wi_edit entry change created", "wi_edit", _last(change="created"), ("history",)),
    _exact("wi_edit entry change reminded", "wi_edit", _last(change="reminded"), ("history",)),
    _exact(
        "wi_edit first entry rewritten", "wi_edit", _hist_set(lambda h: [{**h[0], "by": "u_sam"}, *h[1:]]), ("history",)
    ),
    _exact(
        "wi_edit first entry back-dated",
        "wi_edit",
        _hist_set(lambda h: [{**h[0], "at": "2020-01-01T00:00:00.000Z"}, *h[1:]]),
        ("history",),
    ),
    _exact("wi_edit old entry replaced by the new one", "wi_edit", _hist_set(lambda h: [h[-1]]), ("history",)),
    _exact(
        "wi_edit history entry removed and another added",
        "wi_edit",
        _hist_set(lambda h: [hist("u_riya", "edited", "open"), hist("u_riya", "edited", "open")]),
        ("history",),
    ),
    _exact("wi_edit updated_at stale", "wi_edit", _set(updated_at=t.T1), ("stamp",)),
    _exact("wi_edit updated_at in the future", "wi_edit", _set(updated_at=t.FUTURE), ("stamp",)),
    _exact(
        "wi_edit history and updated_at both wrong",
        "wi_edit",
        lambda a: {**_hist_set(lambda h: h[:-1])(a), "updated_at": t.T1},
        ("history", "stamp"),
    ),
    # work item confirm
    _exact(
        "wi_confirm confirmed_by names another person",
        "wi_confirm",
        _set(confirmed_by={"by": "u_sam", "at": NOW}),
        ("stamp",),
    ),
    _exact(
        "wi_confirm confirmed_by backdated", "wi_confirm", _set(confirmed_by={"by": "u_owner", "at": t.T1}), ("stamp",)
    ),
    _exact(
        "wi_confirm confirmed_by in the future",
        "wi_confirm",
        _set(confirmed_by={"by": "u_owner", "at": t.FUTURE}),
        ("stamp",),
    ),
    _has(
        "wi_confirm status left proposed",
        "wi_confirm",
        lambda a: {**_last(status="proposed")({**a, "confirmed_by": None}), "status": "proposed", "confirmed_by": None},
        ("transition",),
        ("stamp",),
    ),
    _has(
        "wi_confirm status jumps to done",
        "wi_confirm",
        lambda a: {**_last(status="done")(a), "status": "done"},
        ("transition",),
        ("history",),
    ),
    _exact("wi_confirm history says edited", "wi_confirm", _last(change="edited"), ("history",)),
    _has("wi_confirm title changed", "wi_confirm", _set(title="Another title"), ("immutable",)),
    _has("wi_confirm assigner swapped", "wi_confirm", _set(assigned_by={"by": "u_sam", "at": t.T0}), ("immutable",)),
    _has("wi_confirm due changed", "wi_confirm", _set(due="2026-11-01"), ("immutable",)),
    # work item mark_done
    _has(
        "wi_done status dropped",
        "wi_done",
        lambda a: {**_last(status="dropped")(a), "status": "dropped"},
        ("transition",),
    ),
    _has(
        "wi_done status stays open", "wi_done", lambda a: {**_last(status="open")(a), "status": "open"}, ("transition",)
    ),
    _exact("wi_done history says edited", "wi_done", _last(change="edited"), ("history",)),
    _has("wi_done title changed", "wi_done", _set(title="Sneaky edit"), ("immutable",)),
    _has("wi_done snooze set", "wi_done", _set(snoozed_until=stamp_after(days=3)), ("immutable",)),
    _exact("wi_done updated_at stale", "wi_done", _set(updated_at=t.T1), ("stamp",)),
    # pinboard item edit
    _exact("pin_edit body and due", "pin_edit", _set(body="More detail", due="2026-11-15"), ()),
    _exact("pin_edit becomes a link with a url", "pin_edit", _set(kind="link", url="https://example.com/doc"), ()),
    _exact(
        "pin_edit responsible person is a member",
        "pin_edit",
        lambda a: {**_last(change="owner_changed")(a), "owner": "u_riya"},
        (),
    ),
    _exact(
        "pin_edit responsible person cleared",
        "pin_edit",
        lambda a: {**_last(change="owner_changed")(a), "owner": None},
        (),
    ),
    _exact(
        "pin_edit responsible person is not a member",
        "pin_edit",
        lambda a: {**_last(change="owner_changed")(a), "owner": "u_sam"},
        ("owner_not_member",),
    ),
    _exact(
        "pin_edit responsible person is in another org",
        "pin_edit",
        lambda a: {**_last(change="owner_changed")(a), "owner": "u_ext"},
        ("owner_not_member",),
    ),
    _exact(
        "pin_edit responsible person is nobody in the directory",
        "pin_edit",
        lambda a: {**_last(change="owner_changed")(a), "owner": "u_ghost"},
        ("owner_not_member",),
    ),
    _exact(
        "pin_edit active to removed",
        "pin_edit",
        lambda a: {**_last(change="removed", status="removed")(a), "status": "removed"},
        (),
    ),
    _exact("pin_edit link without a url", "pin_edit", _set(kind="link", url=None), ("after_not_allowed",)),
    _exact(
        "pin_edit note with a url", "pin_edit", _set(kind="note", url="https://example.com/doc"), ("after_not_allowed",)
    ),
    _has(
        "pin_edit status active to proposed",
        "pin_edit",
        lambda a: {**_last(status="proposed")(a), "status": "proposed"},
        ("transition",),
        ("history", "after_not_allowed"),
    ),
    _has(
        "pin_edit scope changed to personal",
        "pin_edit",
        _set(scope={"kind": "personal", "user": "u_owner"}),
        ("immutable",),
        ("after_not_allowed",),
    ),
    _has(
        "pin_edit scope moved to another team",
        "pin_edit",
        _set(scope={"kind": "team", "team": "tm_ops"}),
        ("immutable",),
        ("after_not_allowed",),
    ),
    _has("pin_edit set_up_by changed", "pin_edit", _set(set_up_by="u_riya"), ("immutable",), ("after_not_allowed",)),
    _has(
        "pin_edit created_by changed",
        "pin_edit",
        _set(created_by=pl.maker_person("u_riya", t.T0)),
        ("immutable",),
        ("after_not_allowed",),
    ),
    _has(
        "pin_edit source set",
        "pin_edit",
        _set(source={"kind": "meeting", "ref": "mt_weekly1", "evidence": []}),
        ("immutable",),
        ("after_not_allowed",),
    ),
    _has(
        "pin_edit confirmed_by set by edit", "pin_edit", _set(confirmed_by={"by": "u_owner", "at": NOW}), ("immutable",)
    ),
    _has("pin_edit flagged raised", "pin_edit", _set(flagged=True), ("immutable",)),
    _ident("pin_edit id changed", "pin_edit", _set(id="pb_other1")),
    _exact("pin_edit history not grown", "pin_edit", _hist_set(lambda h: h[:-1]), ("history",)),
    _exact("pin_edit entry by another person", "pin_edit", _last(by="u_riya"), ("history",)),
    _has(
        "pin_edit entry accepted on an edit", "pin_edit", _last(change="accepted"), ("history",), ("after_not_allowed",)
    ),  # S3 on after
    _exact("pin_edit updated_at stale", "pin_edit", _set(updated_at=t.T1), ("stamp",)),
    # personal pins: a personal pin has no owner and takes no team fields
    _exact("personal_pin_edit retitled", "personal_pin_edit", lambda a: a, ()),
    _exact("personal_pin_edit given an owner", "personal_pin_edit", _set(owner="u_riya"), ("schema",)),
    _exact(
        "personal_pin_edit given a team scope",
        "personal_pin_edit",
        _set(scope={"kind": "team", "team": "tm_sales"}),
        ("immutable",),
    ),
    _exact(
        "personal_pin_edit removed",
        "personal_pin_edit",
        lambda a: {**_last(change="removed", status="removed")(a), "status": "removed"},
        (),
    ),
    _has(
        "personal_pin_edit moved to another person",
        "personal_pin_edit",
        _set(scope={"kind": "personal", "user": "u_sam"}),
        ("immutable",),
        ("after_not_allowed",),
    ),
    # pinboard item confirm
    _has(
        "pin_confirm status left proposed",
        "pin_confirm",
        lambda a: {**_last(status="proposed")({**a, "confirmed_by": None}), "status": "proposed", "confirmed_by": None},
        ("transition",),
        ("stamp",),
    ),
    _has(
        "pin_confirm status removed",
        "pin_confirm",
        lambda a: {**_last(status="removed")(a), "status": "removed"},
        ("transition",),
        ("history",),
    ),
    _exact(
        "pin_confirm confirmed_by names another person",
        "pin_confirm",
        _set(confirmed_by={"by": "u_riya", "at": NOW}),
        ("stamp",),
    ),
    _exact(
        "pin_confirm confirmed_by backdated",
        "pin_confirm",
        _set(confirmed_by={"by": "u_owner", "at": t.T0}),
        ("stamp",),
    ),
    _exact("pin_confirm history says edited", "pin_confirm", _last(change="edited"), ("history",)),
    _has("pin_confirm title changed", "pin_confirm", _set(title="Another title"), ("immutable",)),
    # calendar entry edit
    _exact("cal_edit time and all_day", "cal_edit", _set(start=t.T2, end="2026-10-02T10:30:00.000Z", all_day=True), ()),
    _exact("cal_edit shared with the owners team", "cal_edit", _set(share={"team": "tm_sales"}), ()),
    _exact("cal_edit accepted to cancelled", "cal_edit", _set(state="cancelled"), ()),
    _exact("cal_edit accepted to declined", "cal_edit", _set(state="declined"), ("transition",)),
    _exact("cal_edit accepted to proposed", "cal_edit", _set(state="proposed"), ("transition",)),
    _exact(
        "cal_edit shared with a team the owner is not in",
        "cal_edit",
        _set(share={"team": "tm_ops"}),
        ("after_not_allowed",),
    ),
    _exact("cal_edit ends before it starts", "cal_edit", _set(start=t.T2, end=t.T1), ("after_not_allowed",)),
    _exact("cal_edit end removed", "cal_edit", _set(end=None), ()),
    _has("cal_edit owner changed", "cal_edit", _set(owner="u_riya"), ("immutable",), ("after_not_allowed",)),
    _has("cal_edit attendee_count changed", "cal_edit", _set(attendee_count=12), ("immutable",)),
    _has(
        "cal_edit source changed",
        "cal_edit",
        _set(source=copy.deepcopy(pl.GOOGLE_SOURCE)),
        ("immutable",),
        ("after_not_allowed",),
    ),
    _has("cal_edit created_by changed", "cal_edit", _set(created_by=pl.maker_person("u_riya", t.T0)), ("immutable",)),
    _has(
        "cal_edit confirmed_by set by edit", "cal_edit", _set(confirmed_by={"by": "u_owner", "at": NOW}), ("immutable",)
    ),
    _has("cal_edit flagged raised", "cal_edit", _set(flagged=True), ("immutable",)),
    _ident("cal_edit id changed", "cal_edit", _set(id="ce_other1")),
    _exact("cal_edit updated_at stale", "cal_edit", _set(updated_at=t.T1), ("stamp",)),
    # calendar entry confirm
    _has(
        "cal_confirm state left proposed",
        "cal_confirm",
        lambda a: {**a, "state": "proposed", "confirmed_by": None},
        ("transition",),
        ("stamp",),
    ),
    _has(
        "cal_confirm state declined",
        "cal_confirm",
        lambda a: {**a, "state": "declined", "confirmed_by": None},
        ("transition",),
        ("stamp",),
    ),
    _exact(
        "cal_confirm confirmed_by names another person",
        "cal_confirm",
        _set(confirmed_by={"by": "u_riya", "at": NOW}),
        ("stamp",),
    ),
    _exact(
        "cal_confirm confirmed_by backdated",
        "cal_confirm",
        _set(confirmed_by={"by": "u_owner", "at": t.T1}),
        ("stamp",),
    ),
    _exact("cal_confirm updated_at stale", "cal_confirm", _set(updated_at=t.T1), ("stamp",)),
    _has("cal_confirm title changed", "cal_confirm", _set(title="Another title"), ("immutable",)),
    _has("cal_confirm shared at the same time", "cal_confirm", _set(share={"team": "tm_sales"}), ("immutable",)),
    # Google-synced entry: only its share may change (its times are Google's, FR-CAL-04)
    _exact("google_edit share withdrawn", "google_edit", _set(share=None), ()),
    _has("google_edit title changed", "google_edit", _set(title="Renamed"), ("immutable",)),
    _has("google_edit time moved", "google_edit", _set(start=t.T2, end="2026-10-02T10:30:00.000Z"), ("immutable",)),
    _has("google_edit cancelled", "google_edit", _set(state="cancelled", share=None), ("immutable",)),
    _has("google_edit all_day flipped", "google_edit", _set(all_day=True), ("immutable",)),
    # meeting edit and confirm
    _exact(
        "mtg_edit agenda attendees series and schedule",
        "mtg_edit",
        _set(
            agenda=[{"title": "Hiring", "minutes": 5}],
            attendees=[{"name": "Riya", "user": "u_riya"}],
            series=None,
            scheduled=None,
        ),
        (),
    ),
    _has("mtg_edit status changed", "mtg_edit", _set(status="live"), ("immutable",)),
    _has("mtg_edit owner changed", "mtg_edit", _set(owner="u_riya"), ("immutable",), ("after_not_allowed",)),
    _has(
        "mtg_edit attestation changed",
        "mtg_edit",
        _set(attestation={"by": "u_owner", "at": NOW, "notice_version": "2.0.0"}),
        ("immutable",),
    ),
    _has(
        "mtg_edit world_id written from outside",
        "mtg_edit",
        _set(world_id="w_01J8Z3K4M5N6P7Q8R9S0T1V2W3"),
        ("immutable",),
    ),
    _has("mtg_edit transcript pointed somewhere", "mtg_edit", _set(transcript=copy.deepcopy(pl.ART)), ("immutable",)),
    _has(
        "mtg_edit deletion dates moved",
        "mtg_edit",
        _set(delete_transcript_after="2027-01-01T00:00:00.000Z"),
        ("immutable",),
    ),
    _has("mtg_edit created_at changed", "mtg_edit", _set(created_at=NOW), ("immutable",)),
    _ident("mtg_edit id changed", "mtg_edit", _set(id="mt_other1")),
    _exact(
        "mtg_confirm confirmed by another person",
        "mtg_confirm",
        _set(minutes_confirmed_by={"by": "u_riya", "at": NOW}),
        ("stamp",),
    ),
    _exact(
        "mtg_confirm confirmed in the past",
        "mtg_confirm",
        _set(minutes_confirmed_by={"by": "u_owner", "at": t.T1}),
        ("stamp",),
    ),
    _exact(
        "mtg_confirm confirmed in the future",
        "mtg_confirm",
        _set(minutes_confirmed_by={"by": "u_owner", "at": t.FUTURE}),
        ("stamp",),
    ),
    _has("mtg_confirm title changed", "mtg_confirm", _set(title="Another title"), ("immutable",)),
    _has(
        "mtg_confirm confirmation withdrawn",
        "mtg_confirm",
        _set(minutes_confirmed_by=None),
        (),
        ("transition", "stamp"),
    ),
    _exact("mtg_confirm on an unminuted meeting", "mtg_confirm", _set(status="ended", minutes=None), ("schema",)),
    # mention untag
    _exact("untag removed by another person", "untag", _set(removed={"by": "u_owner", "at": NOW}), ("stamp",)),
    _exact("untag removal back-dated", "untag", _set(removed={"by": "u_riya", "at": t.T1}), ("stamp",)),
    _exact("untag removal in the future", "untag", _set(removed={"by": "u_riya", "at": t.FUTURE}), ("stamp",)),
    _has("untag not removed at all", "untag", _set(removed=None), (), ("transition", "stamp")),
    _has("untag tagged person swapped", "untag", _set(user="u_sam"), ("immutable",)),
    _has("untag team moved", "untag", _set(team="tm_ops"), ("immutable",)),
    _has("untag added_by rewritten", "untag", _set(added_by=pl.maker_person("u_riya", NOW)), ("immutable",)),
    _ident("untag id changed", "untag", _set(id="mn_other1")),
    # person: memberships and org role (PE-17; BQ-PPL10-7: nothing else of a person is written)
    _exact("assign a membership the owner stamped", "assign", lambda a: a, ()),
    _exact("assign removes an entry", "assign", lambda a: {**a, "memberships": []}, ()),
    _exact(
        "assign drops the old entry and keeps the new one",
        "assign",
        lambda a: {**a, "memberships": [a["memberships"][1]]},
        (),
    ),
    _exact(
        "assign new entry by another person",
        "assign",
        lambda a: {**a, "memberships": [a["memberships"][0], t.member("tm_ops", "u_sam", NOW)]},
        ("stamp",),
    ),
    _exact(
        "assign new entry with an old stamp",
        "assign",
        lambda a: {**a, "memberships": [a["memberships"][0], t.member("tm_ops", "u_owner", t.T0)]},
        ("stamp",),
    ),
    _exact(
        "assign new entry stamped in the future",
        "assign",
        lambda a: {**a, "memberships": [a["memberships"][0], t.member("tm_ops", "u_owner", t.FUTURE)]},
        ("stamp",),
    ),
    _exact(
        "assign an existing entry re-stamped by someone else",
        "assign",
        lambda a: {**a, "memberships": [t.member("tm_sales", "u_sam", NOW), a["memberships"][1]]},
        ("stamp",),
    ),
    _exact(
        "assign an existing entry back-dated",
        "assign",
        lambda a: {**a, "memberships": [t.member("tm_sales", "u_owner", t.T1), a["memberships"][1]]},
        ("stamp",),
    ),
    _exact(
        "assign nine memberships",
        "assign",
        lambda a: {**a, "memberships": [t.member(f"tm_t{n}", "u_owner", NOW) for n in range(9)]},
        ("schema",),
    ),
    _has("assign display name changed", "assign", _set(display_name="Someone Else"), ("immutable",)),
    _has("assign email changed", "assign", _set(email="other@example.com"), ("immutable",)),
    _has("assign time zone changed", "assign", _set(time_zone="UTC"), ("immutable",)),
    _has("assign aliases changed", "assign", _set(aliases=["Boss"]), ("immutable",)),
    _has("assign preferred channel changed", "assign", _set(preferred_channel="email"), ("immutable",)),
    _has("assign org role changed in the same write", "assign", _set(org_role="owner"), ("immutable",)),
    _has("assign created_by changed", "assign", _set(created_by={"by": "u_riya", "at": NOW}), ("immutable",)),
    _ident("assign id changed", "assign", _set(id="u_other")),
    _ident("assign org changed", "assign", _set(org_id=t.OTHER_ORG)),
    _exact("promote member to owner", "promote", lambda a: a, ()),
    _has(
        "promote with a membership added",
        "promote",
        lambda a: {**a, "memberships": [*a["memberships"], t.member("tm_ops", "u_owner", NOW)]},
        ("immutable",),
    ),
    _has("promote with the name changed", "promote", _set(display_name="Riya The Owner"), ("immutable",)),
    _has("promote with a new email", "promote", _set(email="riya@evil.example"), ("immutable",)),
    _exact("promote to a made-up role", "promote", _set(org_role="admin"), ("schema",)),
]


@pytest.mark.parametrize("row", EDIT_ROWS, ids=[r[0] for r in EDIT_ROWS])
def test_PPL_10c_PE_19_one_defect_gives_exactly_its_problem(row):
    label, base, mutate, exact, must, may = row
    request, after = BASELINES[base]()
    after = mutate(copy.deepcopy(after))
    if base in CREATES:
        request = dataclasses.replace(request, record=copy.deepcopy(after))
    got = check(request, after)
    assert_well_formed(got)
    if exact is not None:
        assert got == exact, label
    else:
        assert got, f"{label}: a defective write must not store"
        assert set(must) <= set(got) and set(got) <= {*must, *may}, f"{label}: got {got}"


def test_PPL_10c_PE_19_a_rewrite_that_changes_nothing_is_not_a_write():
    """Append-only history: a no-op still has to add its one entry, so an unchanged record is refused."""
    request, _ = wi_edit()
    problems = check(request, copy.deepcopy(request.record))
    assert "history" in problems and "stamp" in problems


# -- the second and third self-edit refusals of BQ-PPL10-7 -----------------------------------------
@pytest.mark.parametrize("field", ["time_zone", "aliases", "preferred_channel", "display_name", "email"])
def test_PPL_10c_PE_17_nobody_edits_a_persons_own_fields_through_check_write(field):
    riya = t.person_in("u_riya")
    new = {
        "time_zone": "UTC",
        "aliases": ["R"],
        "preferred_channel": "email",
        "display_name": "Riya Renamed",
        "email": "new@example.com",
    }[field]
    after = {**copy.deepcopy(riya), field: new}
    for actor in ("u_riya", "u_owner"):  # the person and an org owner
        assert check(t.req(actor, "edit", "person", riya), after) == ("not_allowed",), (actor, field)


def test_PPL_10c_PE_17_a_member_cannot_assign_or_promote_themself_or_a_teammate():
    riya = t.person_in("u_riya")
    grown = copy.deepcopy(riya)
    grown["memberships"].append(t.member("tm_ops", "u_riya", NOW))
    assert check(t.req("u_riya", "assign_membership", "person", riya), grown) == ("not_allowed",)
    assert check(t.req("u_sam", "assign_membership", "person", riya), grown) == ("not_allowed",)
    assert check(t.req("u_riya", "set_org_role", "person", riya), {**copy.deepcopy(riya), "org_role": "owner"}) == (
        "not_allowed",
    )
    assert check(t.req("u_ext", "set_org_role", "person", riya), {**copy.deepcopy(riya), "org_role": "owner"}) == (
        "not_allowed",
    )  # another org's owner
    assert check(t.req("u_ext", "assign_membership", "person", riya), grown) == ("not_allowed",)


def test_PPL_10c_PE_17_roles_are_only_ever_promoted():
    owner = t.person_in("u_owner")
    demoted = {**copy.deepcopy(owner), "org_role": "member"}
    assert check(t.req("u_owner", "set_org_role", "person", owner), demoted) == ("transition",)
    promoted_again = {**copy.deepcopy(owner), "org_role": "owner"}
    assert check(t.req("u_owner", "set_org_role", "person", owner), promoted_again) != ()  # no-op: nothing to store


# ---------------------------------------------------------------------------------------------
# 3. Creates: every stamp is the actor's at now (PE-19), nothing comes from the body
# ---------------------------------------------------------------------------------------------
CREATE_ROWS = [
    # person-made work item
    _exact("c_wi_person created_at old", "c_wi_person", _set(created_at=t.T0), ("stamp",)),
    _exact("c_wi_person updated_at old", "c_wi_person", _set(updated_at=t.T0), ("stamp",)),
    _exact(
        "c_wi_person created_by.at old", "c_wi_person", _set(created_by=pl.maker_person("u_riya", t.T0)), ("stamp",)
    ),
    _exact(
        "c_wi_person created_by.at in the future",
        "c_wi_person",
        _set(created_by=pl.maker_person("u_riya", t.FUTURE)),
        ("stamp",),
    ),
    _exact("c_wi_person confirmed_by set", "c_wi_person", _set(confirmed_by={"by": "u_riya", "at": NOW}), ("stamp",)),
    _exact(
        "c_wi_person assigned_by stamped now by the creator",
        "c_wi_person",
        _set(assigned_by={"by": "u_riya", "at": NOW}),
        (),
    ),
    _exact(
        "c_wi_person assigned_by with an old stamp",
        "c_wi_person",
        _set(assigned_by={"by": "u_riya", "at": t.T0}),
        ("stamp",),
    ),
    _exact(
        "c_wi_person history entry missing a second entry",
        "c_wi_person",
        _hist_set(lambda h: [*h, hist("u_riya", "edited", "open")]),
        ("history",),
    ),
    _exact("c_wi_person history by another person", "c_wi_person", _last(by="u_sam"), ("history",)),
    _exact("c_wi_person history with an old stamp", "c_wi_person", _last(at=t.T0), ("history",)),
    _exact("c_wi_person history change edited", "c_wi_person", _last(change="edited"), ("history",)),
    _exact("c_wi_person history status mismatch", "c_wi_person", _last(status="done"), ("history",)),
    _exact(
        "c_wi_person stale updated_at and wrong history",
        "c_wi_person",
        lambda a: {**_last(by="u_sam")(a), "updated_at": t.T0},
        ("history", "stamp"),
    ),
    # Tilo-made work item
    _exact("c_wi_tilo assigned_by.at old", "c_wi_tilo", _set(assigned_by={"by": "u_owner", "at": t.T0}), ("stamp",)),
    _exact(
        "c_wi_tilo created_by names another agent",
        "c_wi_tilo",
        _set(created_by=pl.maker_tilo("A_other", NOW)),
        ("stamp",),
    ),
    _exact(
        "c_wi_tilo created_by is system, not an agent id (BQ-PPL10-11)",
        "c_wi_tilo",
        _set(created_by=pl.maker_tilo("system", NOW)),
        ("stamp",),
    ),
    _exact("c_wi_tilo created_by.at old", "c_wi_tilo", _set(created_by=pl.maker_tilo("A_notes", t.T1)), ("stamp",)),
    _exact(
        "c_wi_tilo confirmed_by pre-filled", "c_wi_tilo", _set(confirmed_by={"by": "u_owner", "at": NOW}), ("stamp",)
    ),
    _exact("c_wi_tilo history says edited", "c_wi_tilo", _last(change="edited"), ("history",)),
    _exact(
        "c_wi_tilo history says confirmed, which decide refuses (S3)",
        "c_wi_tilo",
        _last(change="confirmed"),
        ("not_allowed",),
    ),
    _exact("c_wi_tilo history by a person", "c_wi_tilo", _last(by="u_owner"), ("history",)),
    # team and personal pins
    _exact("c_pin_team created_at old", "c_pin_team", _set(created_at=t.T0), ("stamp",)),
    _exact("c_pin_team updated_at old", "c_pin_team", _set(updated_at=t.T0), ("stamp",)),
    _exact("c_pin_team created_by.at old", "c_pin_team", _set(created_by=pl.maker_person("u_owner", t.T0)), ("stamp",)),
    _exact("c_pin_team confirmed_by set", "c_pin_team", _set(confirmed_by={"by": "u_owner", "at": NOW}), ("stamp",)),
    _exact(
        "c_pin_team history missing its created entry",
        "c_pin_team",
        _hist_set(lambda h: [hist("u_owner", "edited", "active")]),
        ("history",),
    ),
    _exact("c_pin_team history entry by another person", "c_pin_team", _last(by="u_riya"), ("history",)),
    _exact("c_pin_team history status mismatch", "c_pin_team", _last(status="proposed"), ("history",)),
    _exact("c_pin_personal updated_at old", "c_pin_personal", _set(updated_at=t.T0), ("stamp",)),
    _exact(
        "c_pin_personal created_by.at old",
        "c_pin_personal",
        _set(created_by=pl.maker_person("u_riya", t.T0)),
        ("stamp",),
    ),
    _exact("c_pin_personal history old stamp", "c_pin_personal", _last(at=t.T0), ("history",)),
    _exact(
        "c_pin_tilo created_by names another agent",
        "c_pin_tilo",
        _set(created_by=pl.maker_tilo("A_other", NOW)),
        ("stamp",),
    ),
    _exact("c_pin_tilo created_at old", "c_pin_tilo", _set(created_at=t.T0), ("stamp",)),
    _exact("c_pin_tilo history by the setter", "c_pin_tilo", _last(by="u_owner"), ("history",)),
    # calendar entries
    _exact(
        "c_cal_person created_by.at old", "c_cal_person", _set(created_by=pl.maker_person("u_owner", t.T0)), ("stamp",)
    ),
    _exact(
        "c_cal_person created_by names another person",
        "c_cal_person",
        _set(created_by=pl.maker_person("u_riya", NOW)),
        ("stamp",),
    ),
    _exact("c_cal_person updated_at old", "c_cal_person", _set(updated_at=t.T0), ("stamp",)),
    _exact(
        "c_cal_person confirmed_by set", "c_cal_person", _set(confirmed_by={"by": "u_owner", "at": NOW}), ("stamp",)
    ),
    _exact(
        "c_cal_tilo created_by names another agent",
        "c_cal_tilo",
        _set(created_by=pl.maker_tilo("A_other", NOW)),
        ("stamp",),
    ),
    _exact(
        "c_cal_tilo created_by is system (BQ-PPL10-11)",
        "c_cal_tilo",
        _set(created_by=pl.maker_tilo("system", NOW)),
        ("stamp",),
    ),
    _exact(
        "c_cal_tilo created_by claims a person, so it is person-made and Tilo may not create it",
        "c_cal_tilo",
        _set(created_by=pl.maker_person("u_owner", NOW)),
        ("not_allowed",),
    ),
    _exact("c_cal_tilo created_by.at old", "c_cal_tilo", _set(created_by=pl.maker_tilo("A_notes", t.T1)), ("stamp",)),
    _exact("c_cal_tilo updated_at old", "c_cal_tilo", _set(updated_at=t.T1), ("stamp",)),
    _exact(
        "c_cal_google created_by is system (BQ-PPL10-11)",
        "c_cal_google",
        _set(created_by=pl.maker_tilo("system", NOW)),
        ("stamp",),
    ),
    _exact(
        "c_cal_google created_by.at old",
        "c_cal_google",
        _set(created_by=pl.maker_tilo("A_calendar_sync", t.T0)),
        ("stamp",),
    ),
    # meeting (G2)
    _exact("c_meeting created_at old", "c_meeting", _set(created_at=t.T0), ("stamp",)),
    _exact(
        "c_meeting attestation in the future",
        "c_meeting",
        _set(attestation={"by": "u_riya", "at": t.FUTURE, "notice_version": "1.0.0"}),
        ("stamp",),
    ),
    _exact(
        "c_meeting attestation at now",
        "c_meeting",
        _set(attestation={"by": "u_riya", "at": NOW, "notice_version": "1.0.0"}),
        (),
    ),
    _exact(
        "c_meeting attested by another person",
        "c_meeting",
        _set(attestation={"by": "u_owner", "at": t.T0, "notice_version": "1.0.0"}),
        ("not_allowed",),
    ),
    # person (G1): created_by and every membership are the creating owner's at now
    _exact("c_person created_by.at old", "c_person", _set(created_by={"by": "u_owner", "at": t.T0}), ("stamp",)),
    _exact(
        "c_person created_by names another person", "c_person", _set(created_by={"by": "u_riya", "at": NOW}), ("stamp",)
    ),
    _exact(
        "c_person membership stamped long ago",
        "c_person",
        _set(memberships=[t.member("tm_sales", "u_owner", t.T0)]),
        ("stamp",),
    ),
    _exact(
        "c_person membership assigned by a member",
        "c_person",
        _set(memberships=[t.member("tm_sales", "u_sam", NOW)]),
        ("stamp",),
    ),
    _exact(
        "c_person one good and one forged membership",
        "c_person",
        _set(memberships=[t.member("tm_sales", "u_owner", NOW), t.member("tm_ops", "u_riya", NOW)]),
        ("stamp",),
    ),
    _exact("c_person no memberships", "c_person", _set(memberships=[]), ()),
    # mentions
    _exact("c_mention added_by.at old", "c_mention", _set(added_by=pl.maker_person("u_owner", t.T0)), ("stamp",)),
    _exact(
        "c_mention added_by names another person",
        "c_mention",
        _set(added_by=pl.maker_person("u_riya", NOW)),
        ("stamp",),
    ),
    _exact("c_mention already removed", "c_mention", _set(removed={"by": "u_owner", "at": NOW}), ("not_allowed",)),
    _exact(
        "c_mention_tilo added_by claims a person",
        "c_mention_tilo",
        _set(added_by=pl.maker_person("u_owner", NOW)),
        ("stamp",),
    ),
    _exact(
        "c_mention_tilo added_by names another agent",
        "c_mention_tilo",
        _set(added_by=pl.maker_tilo("A_other", NOW)),
        ("stamp",),
    ),
]


@pytest.mark.parametrize("row", CREATE_ROWS, ids=[r[0] for r in CREATE_ROWS])
def test_PPL_10c_PE_19_create_stamps_come_from_the_actor_and_the_clock_not_the_body(row):
    label, base, mutate, exact, _, _ = row
    request, after = BASELINES[base]()
    mutated = mutate(copy.deepcopy(after))
    request = dataclasses.replace(request, record=copy.deepcopy(mutated))
    got = check(request, mutated)
    assert_well_formed(got)
    assert got == exact, label


@pytest.mark.parametrize("name", sorted(CREATES))
def test_PPL_10c_PE_19_a_create_whose_after_differs_from_the_record_is_an_identity_problem(name):
    request, after = CREATES[name]()
    other = copy.deepcopy(after)
    key = "title" if "title" in other else "display_name" if "display_name" in other else "user"
    other[key] = "u_other" if key == "user" else "A different value"
    assert check(request, other) == ("identity",), name
    swapped = copy.deepcopy(after)
    swapped["id"] = swapped["id"] + "x"
    assert check(request, swapped) == ("identity",), name


@pytest.mark.parametrize("name", sorted(CREATES))
def test_PPL_10c_PE_19_a_create_nobody_may_make_is_not_allowed(name):
    request, after = CREATES[name]()
    for actor in ("u_ghost", "u_ext", "system"):
        assert check(dataclasses.replace(request, actor=actor), after) == ("not_allowed",), (name, actor)


# ---------------------------------------------------------------------------------------------
# 4. Properties
# ---------------------------------------------------------------------------------------------
_JUNK = st.sampled_from(
    [None, 0, 1, "x", "", [], {}, True, "2020-01-01T00:00:00.000Z", {"by": "u_sam", "at": "2020-01-01T00:00:00.000Z"}]
)
_IMMUTABLE = ["id", "org_id", "owner", "source", "created_by", "assigned_by", "confirmed_by", "flagged", "created_at"]


@SETTINGS
@given(key=st.sampled_from(_IMMUTABLE), junk=_JUNK)
def test_PPL_10c_PE_07_property_no_immutable_field_of_a_work_item_ever_changes_through_an_edit(key, junk):
    request, after = wi_edit()
    if after[key] == junk and type(after[key]) is type(junk):
        return
    mutated = {**after, key: junk}
    got = check(request, mutated)
    assert_well_formed(got)
    assert got != ()


@SETTINGS
@given(
    key=st.sampled_from(["title", "due", "due_text", "snoozed_until", "status", "history", "updated_at"]),
    junk=_JUNK,
)
def test_PPL_10c_PE_19_property_any_garbage_in_a_mutable_field_never_raises_and_is_well_formed(key, junk):
    request, after = wi_edit()
    got = check(request, {**after, key: junk})
    assert_well_formed(got)


@SETTINGS
@given(
    keep=st.integers(0, 1),
    extras=st.lists(
        st.tuples(
            st.sampled_from(["u_riya", "u_sam", "A_notes"]),
            st.sampled_from(["edited", "created", "confirmed", "done", "dropped", "reopened", "reminded"]),
        ),
        max_size=3,
    ),
)
def test_PPL_10c_PE_19_property_history_is_append_only_and_gains_exactly_one_entry(keep, extras):
    request, after = wi_edit()
    prefix = after["history"][:-1]  # the one entry the record already had
    assert len(prefix) == 1
    rewritten = prefix[:keep] + [hist(actor, change, "open") for actor, change in extras]
    got = check(request, {**after, "history": rewritten})
    assert_well_formed(got)
    if not rewritten:
        assert got == ("schema",)  # a record has at least one history entry
    elif keep == 1 and extras == [("u_riya", "edited")]:
        assert got == ()
    else:
        assert "history" in got


@SETTINGS
@given(delta_ms=st.integers(-3 * 86_400_000, 35 * 86_400_000))
def test_PPL_10c_PE_19_property_snooze_is_within_30_days_after_now_and_never_before(delta_ms):
    request, after = wi_edit()
    mutated = {**_last(change="snoozed")(after), "snoozed_until": stamp_after(millis=delta_ms)}
    got = check(request, mutated)
    ok = 0 < delta_ms <= 30 * 86_400_000
    assert got == (() if ok else ("snooze_range",))


@SETTINGS
@given(
    stamp=st.datetimes(min_value=datetime(2026, 1, 1), max_value=datetime(2027, 12, 31)),
    field=st.sampled_from(["created_at", "updated_at"]),
)
def test_PPL_10c_PE_19_property_a_create_with_any_clock_other_than_now_has_a_stamp_problem(stamp, field):
    wrong = stamp.strftime("%Y-%m-%dT%H:%M:%S.") + f"{stamp.microsecond // 1000:03d}Z"
    request, record = c_wi_person()
    mutated = {**record, field: wrong}
    request = dataclasses.replace(request, record=copy.deepcopy(mutated))
    got = check(request, mutated)
    assert got == (() if wrong == NOW else ("stamp",))


def test_PPL_10c_PE_19_check_write_leaks_no_record_text_in_its_answer():
    request, after = wi_edit()
    request = dataclasses.replace(request, record={**request.record, "title": t.SENTINEL})
    got = check(request, {**after, "title": t.SENTINEL + "-new", "x": t.SENTINEL})
    assert got == ("schema",) and t.SENTINEL not in repr(got)


# ---------------------------------------------------------------------------------------------
# 5. Fix pass (security review): a new meeting holds its initial state, PE-02 owners on every pin
#    write, and the rules edits already enforce also hold on create
# ---------------------------------------------------------------------------------------------
def _create_check(name, mutate):
    request, after = CREATES[name]()
    mutated = mutate(copy.deepcopy(after))
    return check(dataclasses.replace(request, record=copy.deepcopy(mutated)), mutated)


MEETING_FORGERIES = [
    ("status minuted", _set(status="minuted"), "transition"),
    ("status live", _set(status="live"), "transition"),
    ("status ended", _set(status="ended"), "transition"),
    ("foreign world_id", _set(world_id="w_01J8Z3K4M5N6P7Q8R9S0T1V2W3"), "stamp"),
    ("transcript ref", _set(transcript=copy.deepcopy(pl.ART)), "stamp"),
    ("ended_reason", _set(ended_reason="completed"), "stamp"),
    ("delete_transcript_after", _set(delete_transcript_after="9999-12-31T23:59:59.999Z"), "stamp"),
    ("delete_minutes_after", _set(delete_minutes_after="9999-12-31T23:59:59.999Z"), "stamp"),
]


@pytest.mark.parametrize("row", MEETING_FORGERIES, ids=[r[0] for r in MEETING_FORGERIES])
def test_PPL_10c_PE_19_a_new_meeting_holds_only_its_initial_state(row):
    _, mutate, code = row
    got = _create_check("c_meeting", mutate)
    assert got == ("not_allowed",) or (code in got and set(got) <= {code, "schema"}), got  # decide may refuse first


def test_PPL_10c_PE_19_a_new_meeting_cannot_carry_forged_minutes_for_a_later_confirmation():
    forged = _set(
        status="minuted",
        world_id="w_01J8Z3K4M5N6P7Q8R9S0T1V2W3",
        transcript=copy.deepcopy(pl.ART),
        minutes=copy.deepcopy(pl.ART_MINUTES),
        ended_reason="completed",
    )
    assert {"stamp", "transition"} <= set(_create_check("c_meeting", forged))


@pytest.mark.parametrize("owner", ["u_sam", "u_ext", "u_ghost"])
@pytest.mark.parametrize("name", ["c_pin_team", "c_pin_tilo"])
def test_PPL_10c_PE_02_a_team_pin_is_not_created_with_a_non_member_or_cross_org_owner(name, owner):
    got = _create_check(name, _set(owner=owner))
    assert got != () and set(got) <= {"owner_not_member", "not_allowed"}, got


def test_PPL_10c_PE_02_a_person_made_team_pin_create_names_a_cross_org_owner_not_member():
    assert _create_check("c_pin_team", _set(owner="u_ext")) == ("owner_not_member",)


def test_PPL_10c_PE_02_a_team_pin_is_created_with_a_member_owner():
    assert _create_check("c_pin_team", _set(owner="u_riya")) == ()


@pytest.mark.parametrize("owner", ["u_sam", "u_ext", "u_ghost"])
def test_PPL_10c_PE_02_a_pin_is_not_confirmed_with_a_non_member_or_cross_org_owner(owner):
    request, after = pin_confirm()
    before = {**copy.deepcopy(request.record), "owner": owner}
    request = dataclasses.replace(request, record=before)
    assert check(request, {**after, "owner": owner}) == ("owner_not_member",)


def test_PPL_10c_PE_02_a_pin_is_confirmed_with_a_member_owner():
    request, after = pin_confirm()
    request = dataclasses.replace(request, record={**copy.deepcopy(request.record), "owner": "u_riya"})
    assert check(request, {**after, "owner": "u_riya"}) == ()


@pytest.mark.parametrize("owner", ["u_sam", "u_ext", "u_ghost"])
def test_PPL_10c_PE_02_a_pin_edit_still_refuses_a_non_member_or_cross_org_owner(owner):
    request, after = pin_edit()
    assert check(request, {**_last(change="owner_changed")(after), "owner": owner}) == ("owner_not_member",)


@pytest.mark.parametrize("team", ["tm_ops", "tm_other"])
def test_PPL_10c_PE_04_an_accepted_entry_is_not_created_shared_with_a_team_the_owner_is_not_in(team):
    assert _create_check("c_cal_person", _set(share={"team": team})) == ("owner_not_member",)


def test_PPL_10c_PE_04_an_accepted_entry_is_created_shared_with_the_owners_team():
    assert _create_check("c_cal_person", _set(share={"team": "tm_sales"})) == ()


@pytest.mark.parametrize("until", [NOW, t.T0, stamp_after(days=30, millis=1), "2027-10-03T09:00:00.000Z"])
def test_PPL_10c_PE_19_a_work_item_is_not_created_with_a_snooze_outside_30_days(until):
    assert _create_check("c_wi_person", _set(snoozed_until=until)) == ("snooze_range",)


def test_PPL_10c_PE_19_a_work_item_is_created_with_a_snooze_inside_the_window():
    assert _create_check("c_wi_person", _set(snoozed_until=stamp_after(days=30))) == ()


@pytest.mark.parametrize(
    "name,source",
    [
        ("c_wi_person", {"kind": "meeting", "ref": "mt_weekly1", "evidence": []}),
        ("c_pin_team", {"kind": "meeting", "ref": "mt_weekly1", "evidence": []}),
        ("c_pin_personal", {"kind": "meeting", "ref": "mt_weekly1", "evidence": []}),
        ("c_cal_person", copy.deepcopy(pl.GOOGLE_SOURCE)),
        ("c_cal_person", {"kind": "tilo", "from": "meeting", "ref": "mt_weekly1"}),
    ],
)
def test_PPL_10c_PE_08_a_person_made_record_cannot_claim_a_machine_origin(name, source):
    request, after = CREATES[name]()
    mutated = {**after, "source": source}
    request = dataclasses.replace(request, record=copy.deepcopy(mutated), meeting=t.meeting(), source_owner="u_owner")
    got = check(request, mutated)
    assert "stamp" in got or got == ("not_allowed",), got


@pytest.mark.parametrize("kind", ["mail", "pinboard", "request", "manual"])
def test_PPL_10c_FR_PA_01_a_person_made_work_item_may_come_from_mail_a_pin_a_request_or_nothing(kind):
    """A tracked-mail item can only be person-made (PE-08), so these sources must store."""
    assert _create_check("c_wi_person", _set(source={"kind": kind, "ref": "src_abc123", "evidence": []})) == ()


@pytest.mark.parametrize("kind", ["mail", "request", "manual"])  # a pin's source kinds exclude "pinboard"
def test_PPL_10c_FR_PA_01_a_person_made_pin_may_come_from_mail_a_request_or_nothing(kind):
    got = _create_check("c_pin_team", _set(source={"kind": kind, "ref": "src_abc123", "evidence": []}))
    assert got == ()


def test_PPL_10c_PE_08_a_person_made_pin_and_calendar_entry_may_have_no_source_or_a_manual_one():
    assert _create_check("c_pin_team", _set(source=None)) == ()
    assert _create_check("c_pin_personal", _set(source=None)) == ()
    assert _create_check("c_cal_person", _set(source={"kind": "manual"})) == ()
