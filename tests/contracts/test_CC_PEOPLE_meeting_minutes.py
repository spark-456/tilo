"""CC-PEOPLE: contracts/meeting.schema.json and contracts/minutes.schema.json.

FR-MTG-01 (attestation before any invite; the disclosure), FR-MTG-02 (utterance ids), FR-MTG-03
(minutes shape: summary <= 8 bullets, decisions, action items, agenda coverage), FR-MTG-04 (a
verified item cites evidence; unverified is kept, never dropped), FR-MTG-05 (owner and due as said
plus resolved by code), FR-MTG-10 (retention; discard and delete leave nothing behind),
people.rules.md PE-05 (a meeting holds no link: it is owner-only data) and PE-15.
"""

from __future__ import annotations

import _people_lib as pl
import pytest

M_REQUIRED = (
    "id",
    "org_id",
    "owner",
    "title",
    "series",
    "scheduled",
    "agenda",
    "attendees",
    "attestation",
    "source",
    "status",
    "ended_reason",
    "transcript",
    "minutes",
    "delete_transcript_after",
    "delete_minutes_after",
    "created_at",
)
MIN_REQUIRED = ("meeting_id", "transcript", "generated_at", "flagged", "summary", "decisions", "action_items", "agenda")
STATUSES = ("scheduled", "joining", "live", "ended", "minuted", "discarded", "deleted")
REASONS = ("completed", "left_on_request", "removed", "timeout", "failed")


def mv(repo_root, registry, doc, why=""):
    pl.assert_valid(repo_root, registry, "meeting", doc, None, why or "meeting")


def mi(repo_root, registry, doc, why=""):
    pl.assert_invalid(repo_root, registry, "meeting", doc, None, why or "meeting")


def nv(repo_root, registry, doc, why=""):
    pl.assert_valid(repo_root, registry, "minutes", doc, None, why or "minutes")


def ni(repo_root, registry, doc, why=""):
    pl.assert_invalid(repo_root, registry, "minutes", doc, None, why or "minutes")


# ---------------------------------------------------------------------------------------------
# meeting
# ---------------------------------------------------------------------------------------------
def test_CC_PEOPLE_FR_MTG_01_a_minimal_meeting_is_valid(repo_root, registry):
    mv(repo_root, registry, pl.meeting())
    mv(repo_root, registry, pl.meeting(series=None, scheduled=None, agenda=[], attendees=[], source="upload"))
    mv(repo_root, registry, pl.meeting(scheduled={"start": pl.T1, "end": None}), "open-ended meeting")


@pytest.mark.parametrize("field", M_REQUIRED)
def test_CC_PEOPLE_FR_MTG_01_every_meeting_field_is_required(repo_root, registry, field):
    mi(repo_root, registry, pl.drop(pl.meeting(), (field,)), f"meeting without {field}")


@pytest.mark.parametrize(
    "extra",
    ["meet_link", "link", "url", "join_url", "meeting_url", "location", "conference_link", "invite", "password"],
)
def test_CC_PEOPLE_FR_MTG_01_no_field_can_hold_a_meeting_link(repo_root, registry, extra):
    mi(repo_root, registry, pl.with_(pl.meeting(), **{extra: "https://meet.example.com/abc-defg-hij"}), extra)
    mi(repo_root, registry, pl.with_(pl.meeting(), **{extra: None}), f"{extra}: null")


def test_CC_PEOPLE_FR_MTG_01_nested_objects_are_closed_too(repo_root, registry):
    base = pl.meeting()
    mi(repo_root, registry, pl.put(base, ("attendees", 0, "email"), "riya@example.com"), "attendee email")
    mi(repo_root, registry, pl.put(base, ("attendees", 0, "link"), "https://example.com"), "attendee link")
    mi(repo_root, registry, pl.put(base, ("agenda", 0, "link"), "https://example.com"), "agenda link")
    mi(repo_root, registry, pl.put(base, ("attestation", "link"), "https://example.com"), "attestation extra")
    mi(repo_root, registry, pl.put(base, ("scheduled", "link"), "https://example.com"), "scheduled extra")


def test_CC_PEOPLE_FR_MTG_01_attestation_is_required_and_complete(repo_root, registry):
    base = pl.meeting()
    mi(repo_root, registry, pl.put(base, ("attestation",), None), "no attestation, no invite")
    for field in ("by", "at", "notice_version"):
        mi(repo_root, registry, pl.drop(base, ("attestation", field)), f"attestation without {field}")
    mi(repo_root, registry, pl.put(base, ("attestation", "by"), "A_notes"), "attested by an agent")
    mi(repo_root, registry, pl.put(base, ("attestation", "at"), "2026-10-01"), "attestation date only")
    mi(repo_root, registry, pl.put(base, ("attestation", "notice_version"), "v1"), "notice version not semver")
    mi(repo_root, registry, pl.put(base, ("attestation", "notice_version"), None), "notice version null")


@pytest.mark.parametrize("series", ["weekly-sync", "a", "q4_ops-2", "x" * 64])
def test_CC_PEOPLE_FR_MTG_01_series_accepts_a_slug(repo_root, registry, series):
    mv(repo_root, registry, pl.meeting(series=series), series)


@pytest.mark.parametrize("series", ["Weekly Sync", "weekly sync", "", "x" * 65, "https://example.com", "a/b", "A"])
def test_CC_PEOPLE_FR_MTG_01_series_rejects_anything_that_is_not_a_slug(repo_root, registry, series):
    mi(repo_root, registry, pl.meeting(series=series), repr(series))


def test_CC_PEOPLE_FR_MTG_01_scheduled_needs_a_start_and_a_timestamp(repo_root, registry):
    mi(repo_root, registry, pl.meeting(scheduled={"end": pl.T2}), "no start")
    mi(repo_root, registry, pl.meeting(scheduled={"start": None, "end": None}), "start null")
    mi(repo_root, registry, pl.meeting(scheduled={"start": "2026-10-02", "end": None}), "start date only")
    mi(repo_root, registry, pl.meeting(scheduled={"start": pl.T1, "end": "tomorrow"}), "end not a timestamp")


def test_CC_PEOPLE_FR_MTG_03_agenda_is_at_most_twenty_items_with_bounded_minutes(repo_root, registry):
    item = {"title": "Budget", "minutes": 10}
    mv(repo_root, registry, pl.meeting(agenda=[item] * 20), "20 agenda items")
    mi(repo_root, registry, pl.meeting(agenda=[item] * 21), "21 agenda items")
    for ok in (1, 240, None):
        mv(repo_root, registry, pl.meeting(agenda=[{"title": "Budget", "minutes": ok}]), f"minutes={ok}")
    for bad in (0, 241, -5, 1.5, "10"):
        mi(repo_root, registry, pl.meeting(agenda=[{"title": "Budget", "minutes": bad}]), f"minutes={bad!r}")
    mi(repo_root, registry, pl.meeting(agenda=[{"title": "Budget"}]), "agenda item without minutes")
    mi(repo_root, registry, pl.meeting(agenda=[{"minutes": 5}]), "agenda item without title")


def test_CC_PEOPLE_FR_MTG_05_attendees_are_at_most_fifty_names_as_said_with_an_optional_user(repo_root, registry):
    one = {"name": "Riya", "user": None}
    mv(repo_root, registry, pl.meeting(attendees=[one] * 50), "50 attendees")
    mi(repo_root, registry, pl.meeting(attendees=[one] * 51), "51 attendees")
    mi(repo_root, registry, pl.meeting(attendees=[{"name": "Riya", "user": "riya"}]), "user not a user id")
    mi(repo_root, registry, pl.meeting(attendees=[{"name": "Riya"}]), "attendee without user")
    mi(repo_root, registry, pl.meeting(attendees=[{"user": "u_riya"}]), "attendee without name")
    mi(repo_root, registry, pl.meeting(attendees=[{"name": "R" * 81, "user": None}]), "name of 81 characters")


@pytest.mark.parametrize("source", ["bot", "upload"])
def test_CC_PEOPLE_FR_MTG_02_source_is_bot_or_upload(repo_root, registry, source):
    mv(repo_root, registry, pl.meeting(source=source), source)


@pytest.mark.parametrize("source", ["link", "zoom", "Bot", "", None])
def test_CC_PEOPLE_FR_MTG_02_source_has_no_other_value(repo_root, registry, source):
    mi(repo_root, registry, pl.meeting(source=source), repr(source))


@pytest.mark.parametrize("status", STATUSES)
def test_CC_PEOPLE_FR_MTG_01_status_accepts_each_lifecycle_state(repo_root, registry, status):
    doc = pl.meeting(status=status)
    if status == "minuted":
        doc = pl.with_(doc, transcript=pl.ART, minutes=pl.ART_MINUTES)
    mv(repo_root, registry, doc, status)


@pytest.mark.parametrize("status", ["done", "cancelled", "Live", "", None])
def test_CC_PEOPLE_FR_MTG_01_status_rejects_other_values(repo_root, registry, status):
    mi(repo_root, registry, pl.meeting(status=status), repr(status))


@pytest.mark.parametrize("reason", [*REASONS, None])
def test_CC_PEOPLE_FR_MTG_10_ended_reason_accepts_the_five_reasons_or_null(repo_root, registry, reason):
    mv(repo_root, registry, pl.meeting(status="ended", ended_reason=reason), repr(reason))


@pytest.mark.parametrize("reason", ["crashed", "Completed", "", "left", 0])
def test_CC_PEOPLE_FR_MTG_10_ended_reason_rejects_other_values(repo_root, registry, reason):
    mi(repo_root, registry, pl.meeting(status="ended", ended_reason=reason), repr(reason))


@pytest.mark.parametrize("field", ["transcript", "minutes"])
def test_CC_PEOPLE_FR_MTG_02_transcript_and_minutes_are_artifact_refs_or_null(repo_root, registry, field):
    mv(repo_root, registry, pl.meeting(status="ended", **{field: pl.ART}), f"{field} as artifact_ref")
    for bad in (
        "art_transcript1",
        {"artifact_id": "art_x"},
        {"artifact_id": "x", "version": 1},
        {"artifact_id": "art_x", "version": 0},
        5,
    ):
        mi(repo_root, registry, pl.meeting(status="ended", **{field: bad}), f"{field}={bad!r}")


@pytest.mark.parametrize("field", ["delete_transcript_after", "delete_minutes_after"])
def test_CC_PEOPLE_FR_MTG_10_retention_dates_are_timestamps_or_null(repo_root, registry, field):
    mv(repo_root, registry, pl.meeting(**{field: "2026-11-01T00:00:00.000Z"}), field)
    for bad in ("2026-11-01", "in 30 days", 30):
        mi(repo_root, registry, pl.meeting(**{field: bad}), f"{field}={bad!r}")


@pytest.mark.parametrize("status", ["discarded", "deleted"])
def test_CC_PEOPLE_FR_MTG_10_discarded_or_deleted_meetings_keep_no_transcript_or_minutes(repo_root, registry, status):
    mv(repo_root, registry, pl.meeting(status=status), f"{status} with nothing kept")
    mi(repo_root, registry, pl.meeting(status=status, transcript=pl.ART), f"{status} with a transcript")
    mi(repo_root, registry, pl.meeting(status=status, minutes=pl.ART_MINUTES), f"{status} with minutes")
    mi(
        repo_root,
        registry,
        pl.meeting(status=status, transcript=pl.ART, minutes=pl.ART_MINUTES),
        f"{status} with both",
    )


def test_CC_PEOPLE_FR_MTG_10_other_states_may_hold_a_transcript_and_minutes(repo_root, registry):
    for status in ("live", "ended"):
        mv(repo_root, registry, pl.meeting(status=status, transcript=pl.ART, minutes=pl.ART_MINUTES), status)


def test_CC_PEOPLE_FR_MTG_03_a_minuted_meeting_has_minutes(repo_root, registry):
    mi(repo_root, registry, pl.meeting(status="minuted", transcript=pl.ART, minutes=None), "minuted without minutes")
    mi(repo_root, registry, pl.meeting(status="minuted"), "minuted with nothing")
    mv(repo_root, registry, pl.meeting(status="minuted", transcript=pl.ART, minutes=pl.ART_MINUTES), "minuted")
    mv(repo_root, registry, pl.meeting(status="ended", minutes=None), "ended without minutes is fine")


# ---------------------------------------------------------------------------------------------
# minutes
# ---------------------------------------------------------------------------------------------
def test_CC_PEOPLE_FR_MTG_03_minimal_minutes_are_valid(repo_root, registry):
    nv(repo_root, registry, pl.minutes())
    nv(repo_root, registry, pl.minutes(summary=[], decisions=[], action_items=[], agenda=[], flagged=True))


@pytest.mark.parametrize("field", MIN_REQUIRED)
def test_CC_PEOPLE_FR_MTG_03_every_minutes_field_is_required(repo_root, registry, field):
    ni(repo_root, registry, pl.drop(pl.minutes(), (field,)), f"minutes without {field}")


@pytest.mark.parametrize("extra", ["title", "body", "talk_time", "sentiment", "score", "link"])
def test_CC_PEOPLE_PE_15_minutes_hold_nothing_beyond_the_contract(repo_root, registry, extra):
    ni(repo_root, registry, pl.with_(pl.minutes(), **{extra: "x"}), extra)


def test_CC_PEOPLE_FR_MTG_03_minutes_ids_and_flag_are_checked(repo_root, registry):
    ni(repo_root, registry, pl.minutes(meeting_id="mt_"), "bad meeting id")
    ni(repo_root, registry, pl.minutes(meeting_id="wi_x"), "meeting id of another kind")
    ni(repo_root, registry, pl.minutes(transcript="art_x"), "transcript not an artifact_ref")
    ni(repo_root, registry, pl.minutes(generated_at="2026-10-02"), "generated_at date only")
    for bad in ("yes", 1, None):
        ni(repo_root, registry, pl.minutes(flagged=bad), f"flagged={bad!r}")


def test_CC_PEOPLE_FR_MTG_03_summary_is_at_most_eight_bullets_each_citing_at_most_twenty_utterances(
    repo_root, registry
):
    bullet = {"text": "Agreed the split.", "evidence": ["u0001"]}
    nv(repo_root, registry, pl.minutes(summary=[bullet] * 8), "8 bullets")
    ni(repo_root, registry, pl.minutes(summary=[bullet] * 9), "9 bullets")
    ids = [f"u{i:04d}" for i in range(1, 22)]
    nv(repo_root, registry, pl.minutes(summary=[{"text": "x", "evidence": ids[:20]}]), "20 utterances")
    ni(repo_root, registry, pl.minutes(summary=[{"text": "x", "evidence": ids}]), "21 utterances")
    ni(repo_root, registry, pl.minutes(summary=[{"text": "x", "evidence": ["u1"]}]), "bad utterance id")
    ni(
        repo_root,
        registry,
        pl.minutes(summary=[{"text": "x", "evidence": ["u0001"], "state": "verified"}]),
        "extra key",
    )
    ni(repo_root, registry, pl.minutes(summary=[{"evidence": ["u0001"]}]), "bullet without text")


@pytest.mark.parametrize("where", ["decisions", "action_items"])
def test_CC_PEOPLE_FR_MTG_04_a_verified_claim_cites_at_least_one_utterance(repo_root, registry, where):
    make = (lambda **k: pl.claim(**k)) if where == "decisions" else (lambda **k: pl.action_item(**k))

    def doc(item):
        return pl.minutes(**{where: [item]})

    nv(repo_root, registry, doc(make()), "verified with evidence")
    ni(repo_root, registry, doc(pl.with_(make(), evidence=[])), "verified without evidence")
    nv(
        repo_root,
        registry,
        doc(pl.with_(make(), state="unverified", evidence=[])),
        "unverified without evidence is kept",
    )
    nv(repo_root, registry, doc(pl.with_(make(), state="unverified")), "unverified with evidence")
    ni(repo_root, registry, doc(pl.with_(make(), state="pending")), "state outside verified|unverified")
    ni(repo_root, registry, doc(pl.drop(make(), ("state",))), "no state")
    ni(repo_root, registry, doc(pl.drop(make(), ("text",))), "no text")
    ni(repo_root, registry, doc(pl.with_(make(), evidence=["u1"])), "bad utterance id")
    ni(repo_root, registry, doc(pl.with_(make(), evidence=[f"u{i:04d}" for i in range(1, 22)])), "21 utterances")


def test_CC_PEOPLE_FR_MTG_03_decisions_are_at_most_thirty_and_action_items_at_most_sixty(repo_root, registry):
    nv(repo_root, registry, pl.minutes(decisions=[pl.claim()] * 30), "30 decisions")
    ni(repo_root, registry, pl.minutes(decisions=[pl.claim()] * 31), "31 decisions")
    nv(repo_root, registry, pl.minutes(action_items=[pl.action_item(f"ai{i}") for i in range(1, 61)]), "60 items")
    ni(repo_root, registry, pl.minutes(action_items=[pl.action_item(f"ai{i}") for i in range(1, 62)]), "61 items")


def test_CC_PEOPLE_FR_MTG_05_an_action_item_carries_owner_and_due_as_said_and_as_resolved(repo_root, registry):
    def item(**ov):
        return pl.minutes(action_items=[pl.action_item(**ov)])

    nv(repo_root, registry, item(), "fully resolved item")
    nv(
        repo_root,
        registry,
        item(owner_text=None, owner=None, due_text=None, due=None, work_item_id=None),
        "unresolved item stays",
    )
    nv(repo_root, registry, item(work_item_id="wi_budget1"), "item linked to its work item")
    for field in ("id", "owner_text", "owner", "due_text", "due", "work_item_id", "text", "state"):
        ni(repo_root, registry, pl.minutes(action_items=[pl.drop(pl.action_item(), (field,))]), f"without {field}")
    ni(repo_root, registry, item(extra="x"), "extra key")


@pytest.mark.parametrize("ok", ["ai1", "ai12", "ai999"])
def test_CC_PEOPLE_FR_MTG_03_action_item_ids_are_ai_and_one_to_three_digits(repo_root, registry, ok):
    nv(repo_root, registry, pl.minutes(action_items=[pl.action_item(ok)]), ok)


@pytest.mark.parametrize("bad", ["ai", "ai1000", "AI1", "a1", "ai_1", "ai-1", "ai1a", "", 1])
def test_CC_PEOPLE_FR_MTG_03_action_item_ids_reject_other_shapes(repo_root, registry, bad):
    ni(repo_root, registry, pl.minutes(action_items=[pl.action_item(bad)]), repr(bad))


@pytest.mark.parametrize(
    "field,bad",
    [
        ("due", "next friday"),
        ("due", "2026-13-01"),
        ("due", "2026-10-09T00:00:00.000Z"),
        ("due", "09/10/2026"),
        ("owner", "Priya"),
        ("owner", "A_notes"),
        ("work_item_id", "mt_weekly1"),
        ("work_item_id", "wi_"),
        ("due_text", ""),
        ("due_text", "x" * 61),
        ("owner_text", ""),
        ("owner_text", "x" * 81),
    ],
)
def test_CC_PEOPLE_PE_15_resolved_owner_due_and_work_item_have_their_own_shapes(repo_root, registry, field, bad):
    ni(repo_root, registry, pl.minutes(action_items=[pl.action_item(**{field: bad})]), f"{field}={bad!r}")


def test_CC_PEOPLE_FR_MTG_03_agenda_coverage_is_covered_partial_or_not_discussed(repo_root, registry):
    def row(**ov):
        return pl.minutes(agenda=[pl.with_({"title": "Budget", "coverage": "covered", "evidence": ["u0002"]}, **ov)])

    for ok in ("covered", "partial", "not_discussed"):
        nv(repo_root, registry, row(coverage=ok, evidence=[] if ok == "not_discussed" else ["u0002"]), ok)
    for bad in ("skipped", "Covered", "", None):
        ni(repo_root, registry, row(coverage=bad), f"coverage={bad!r}")
    nv(
        repo_root,
        registry,
        pl.minutes(agenda=[{"title": "Budget", "coverage": "covered", "evidence": []}] * 20),
        "20 rows",
    )
    ni(
        repo_root,
        registry,
        pl.minutes(agenda=[{"title": "Budget", "coverage": "covered", "evidence": []}] * 21),
        "21 rows",
    )
    ni(repo_root, registry, row(evidence=["u1"]), "bad utterance id")
    ni(repo_root, registry, row(extra=1), "extra key")
