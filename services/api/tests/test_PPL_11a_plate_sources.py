"""PPL-11a slice B: the plate's other sources (ADR-0021 decision 2; PE-27 to PE-29; BQ-269 to BQ-272): cards, runs,
mail, pins and today's calendar, none of which the crossref files cover. The plate sources (`deps.get_plate_sources`,
API_PPL_11a.md section 4) are fakes that answer every question with everything they hold, the way a careless or
hostile store would, so each test proves the API filters by owner, world role, state and day itself.
"""

from __future__ import annotations

import json
import pathlib

import pytest
from _ppl11a_lib import (
    CONTRACTS,
    DEV,
    EARLY,
    OWNER,
    PRIYA,
    SAM,
    conforms,
    find_row,
    oracle,
    own_item,
    pl,
    refs,
    u,
)

CARD_DIR = CONTRACTS / "fixtures" / "card" / "valid"


def _card(name: str, card_id: str, *, created_at: str = "2026-10-06T09:30:00.000Z", **ov) -> dict:
    card = json.loads(pathlib.Path(CARD_DIR / f"{name}.json").read_text(encoding="utf-8"))
    card.update(id=card_id, created_at=created_at, **ov)
    return card


def _fact(card: dict, world_owner: str = PRIYA, approver: str | None = None, answered: bool = False) -> dict:
    return {"data": card, "world_owner": world_owner, "approver": approver, "answered": answered}


def _rig(make_rig, user: str = PRIYA, **kwargs):
    rig = make_rig(**kwargs)
    rig.add_people()
    rig.as_user(user)
    return rig


def _plate(rig, expect_rows: bool = True) -> dict:
    response = rig.plate()
    assert response.status_code == 200, response.text[:300]
    plate = response.json()
    assert conforms("plate.schema.json", plate), "the plate must validate against plate.schema.json"
    assert oracle._plate_problems(plate) == [], oracle._plate_problems(plate)
    return plate


# --- cards ----------------------------------------------------------------------------------------------------------

ULID = "01J8Z3K4M5N6P7Q8R9S0T1V2W"


def test_PPL_11a_PE_27_cards_join_by_kind_with_their_reason_and_group(people_rig):
    """Own-world cards: a gate and a consent card and a blocked needs_you card lead (`attention`, reasons `gate`,
    `consent`, `blocked`); a question and a meeting card are `soon` (`question`, `meeting_card`). Title is the card's
    own text or null, `due` null, `at` its creation, `from` null, and the only action is `open`."""
    rig = _rig(people_rig)
    cards = {
        "gate_send_reply": ("gate", "attention"),
        "consent_drive_folder": ("consent", "attention"),
        "needs_you_blocked": ("blocked", "attention"),
        "needs_you_compare_basis": ("question", "soon"),
        "meeting_budget_split": ("meeting_card", "soon"),
    }
    expected = {}
    for n, (name, (reason, group)) in enumerate(cards.items()):
        card = _card(name, f"{ULID}{n}")
        rig.sources.card_facts.append(_fact(card))
        expected[card["id"]] = (reason, group, card)
    plate = _plate(rig)
    assert len(plate["rows"]) == 5 and plate["parked"] == []
    for card_id, (reason, group, card) in expected.items():
        lane, row = find_row(plate, "card", card_id)
        assert lane == "rows" and (row["reason"], row["group"]) == (reason, group), card_id
        assert row["title"] in (None, oracle._clean(card["what_happened"]))
        assert (row["due"], row["from"], row["at"], row["evidence"]) == (None, None, card["created_at"], False)
        assert row["actions"] == ["open"] and row["flagged"] is False


def test_PPL_11a_PE_27_a_card_is_hers_only_in_her_world_or_as_a_gates_approver_and_only_while_open(people_rig):
    rig = _rig(people_rig)
    facts = {
        "mine": _fact(_card("gate_send_reply", f"{ULID}0")),
        "approver_gate": _fact(_card("gate_send_reply", f"{ULID}1"), world_owner=SAM, approver=PRIYA),
        "approver_consent": _fact(_card("consent_drive_folder", f"{ULID}2"), world_owner=SAM, approver=PRIYA),
        "approver_question": _fact(_card("needs_you_compare_basis", f"{ULID}3"), world_owner=SAM, approver=PRIYA),
        "viewer_only": _fact(_card("gate_send_reply", f"{ULID}4"), world_owner=SAM, approver=None),
        "teammates_world": _fact(_card("needs_you_blocked", f"{ULID}5"), world_owner=DEV),
        "answered": _fact(_card("gate_send_reply", f"{ULID}6"), answered=True),
        "expired_exactly": _fact(
            _card("gate_send_reply", f"{ULID}7", created_at="2026-10-06T09:00:00.000Z", timeout=3600)
        ),
        "expiring_later": _fact(
            _card("gate_send_reply", f"{ULID}8", created_at="2026-10-06T09:00:00.001Z", timeout=3600)
        ),
        "approver_is_someone_else": _fact(_card("gate_send_reply", f"{ULID}9"), world_owner=SAM, approver=DEV),
    }
    rig.sources.card_facts.extend(facts.values())
    plate = _plate(rig)
    got = {row["ref"]["id"] for row in plate["rows"]}
    want = {facts[k]["data"]["id"] for k in ("mine", "approver_gate", "expiring_later")}
    assert got == want, f"on the plate: {sorted(got)}"
    assert plate["parked"] == []


# --- runs -----------------------------------------------------------------------------------------------------------


def _run(world: str, owner: str = PRIYA, state: str = "running", **ov) -> dict:
    base = {
        "world_id": world,
        "world_owner": owner,
        "state": state,
        "goal": "Prepare the weekly supplier summary",
        "deadline": None,
        "started_at": "2026-10-06T08:00:00.000Z",
    }
    return {**base, **ov}


def test_PPL_11a_PE_27_runs_of_her_own_worlds_that_are_running_or_blocked_join(people_rig):
    """A running run is `rest` (by its due date like any row), a blocked one leads (`attention`, reason `blocked`);
    completed or unknown states, a world someone else owns (she is only its Viewer or Team Lead) and a run with no
    owner are off the plate. The row points at the world, its title is the goal cut to 140 characters."""
    rig = _rig(people_rig)
    long_goal = ("Compile the quarterly supplier review for every region and send it " * 6).strip()
    rig.sources.run_facts.extend(
        [
            _run("w_run_ok", goal=long_goal),
            _run("w_run_late", deadline="2026-10-04"),
            _run("w_run_blocked", state="blocked", deadline="2026-10-30"),
            _run("w_run_done", state="completed"),
            _run("w_run_weird", state="exploding"),
            _run("w_run_viewer", owner=SAM),
            _run("w_run_lead", owner=OWNER, state="blocked"),
            _run("w_run_nobody", owner="u_ghost"),
            _run("w_run_bidi", goal="Pay" + u(0x202E) + "the invoice" + u(0x200B)),
        ]
    )
    plate = _plate(rig)
    by_id = {row["ref"]["id"]: row for row in plate["rows"]}
    assert set(by_id) == {"w_run_ok", "w_run_late", "w_run_blocked", "w_run_bidi"}, sorted(by_id)
    assert all(row["ref"]["kind"] == "world" for row in by_id.values())
    ok, late, blocked, bidi = (by_id[k] for k in ("w_run_ok", "w_run_late", "w_run_blocked", "w_run_bidi"))
    assert (ok["reason"], ok["group"], ok["due"], ok["at"]) == ("run", "rest", None, "2026-10-06T08:00:00.000Z")
    assert 1 <= len(ok["title"]) <= 140 and long_goal.startswith(ok["title"])
    assert (late["reason"], late["group"], late["due"]) == ("run", "overdue", "2026-10-04")
    assert (blocked["reason"], blocked["group"], blocked["due"]) == ("blocked", "attention", "2026-10-30")
    assert bidi["title"] == "Paythe invoice", "the title is cleaned like a quote line"
    for row in by_id.values():
        assert (row["from"], row["evidence"], row["flagged"], row["actions"]) == (None, False, False, ["open"])


# --- mail -----------------------------------------------------------------------------------------------------------


def _mail(message_id: str, owner: str = PRIYA, **ov) -> dict:
    base = {
        "message_id": message_id,
        "account_owner": owner,
        "received_at": "2026-10-06T07:00:00.000Z",
        "flagged": False,
        "answered": False,
        "dismissed": False,
    }
    return {**base, **ov}


def test_PPL_11a_PE_27_mail_that_needs_a_reply_joins_only_from_her_own_connected_account(people_rig):
    """Mail rows: no title, no sender, no date (BQ-269); only unanswered, undismissed mail of her own account, even
    when the triage store hands back everyone's. A flagged message stays flagged on its row (PE-21)."""
    rig = _rig(people_rig)
    rig.sources.mail_facts.extend(
        [
            _mail("m_own_1"),
            _mail("m_own_2", received_at="2026-10-05T07:00:00.000Z", flagged=True),
            _mail("m_answered", answered=True),
            _mail("m_dismissed", dismissed=True),
            _mail("m_sams", owner=SAM),
            _mail("m_owners", owner=OWNER),
            _mail("m_nobodys", owner="u_ghost"),
        ]
    )
    plate = _plate(rig)
    assert refs(plate) == [("mail", "m_own_2"), ("mail", "m_own_1")], "oldest receipt first"
    for row in plate["rows"]:
        assert (row["reason"], row["group"], row["title"], row["due"], row["from"]) == (
            "mail_reply",
            "rest",
            None,
            None,
            None,
        )
        assert (
            row["evidence"] is False
            and "draft_reply" in row["actions"]
            and set(row["actions"]) <= {"open", "draft_reply"}
        )
    assert [r["flagged"] for r in plate["rows"]] == [True, False]
    assert [r["at"] for r in plate["rows"]] == ["2026-10-05T07:00:00.000Z", "2026-10-06T07:00:00.000Z"]
    assert "subject" not in json.dumps(plate) and "@" not in json.dumps(plate), "no subject, sender or address"


def test_PPL_11a_PE_27_each_person_gets_their_own_mail_and_cards_and_runs_only(people_rig):
    """The same hostile sources, three people: each plate holds exactly that person's rows."""
    rig = _rig(people_rig)
    rig.sources.mail_facts.extend([_mail("m_priya"), _mail("m_sam", owner=SAM), _mail("m_dev", owner=DEV)])
    rig.sources.run_facts.extend([_run("w_priya"), _run("w_sam", owner=SAM), _run("w_dev", owner=DEV)])
    rig.sources.card_facts.extend(
        [
            _fact(_card("gate_send_reply", f"{ULID}0"), world_owner=PRIYA),
            _fact(_card("gate_send_reply", f"{ULID}1"), world_owner=SAM),
            _fact(_card("gate_send_reply", f"{ULID}2"), world_owner=DEV),
        ]
    )
    seen = {}
    for who in (PRIYA, SAM, DEV, OWNER):
        rig.as_user(who)
        seen[who] = {kind_id for kind_id in refs(_plate(rig))}
    assert seen[PRIYA] == {("mail", "m_priya"), ("world", "w_priya"), ("card", f"{ULID}0")}
    assert seen[SAM] == {("mail", "m_sam"), ("world", "w_sam"), ("card", f"{ULID}1")}
    assert seen[DEV] == {("mail", "m_dev"), ("world", "w_dev"), ("card", f"{ULID}2")}
    assert seen[OWNER] == set(), "an org owner has no one else's rows"


# --- calendar -------------------------------------------------------------------------------------------------------


def _entry(entry_id: str, owner: str = PRIYA, **ov) -> dict:
    base = pl.calendar_entry(
        id=entry_id,
        org_id="org_example",
        owner=owner,
        title=f"Event {entry_id}",
        start="2026-10-06T08:00:00.000Z",
        end="2026-10-06T09:00:00.000Z",
        created_by=pl.maker_person(owner, EARLY),
        updated_at=EARLY,
    )
    return pl.with_(base, **ov)


def test_PPL_11a_PE_27_todays_own_accepted_or_proposed_calendar_entries_join_as_soon(people_rig):
    """At 10:00 UTC on 6 Oct it is 15:30 on the 6th in Kolkata: an entry at 00:30 IST on the 6th (19:00 UTC on the
    5th) is today, one at 00:30 IST on the 7th (19:00 UTC on the 6th) is not, whatever its UTC date. Declined and
    cancelled entries, other days and a teammate's shared entry are off her plate; her own proposed one joins."""
    rig = _rig(people_rig)
    rig.add(
        "meetings",
        pl.meeting(
            id="mt_priya",
            org_id="org_example",
            owner=PRIYA,
            created_at=EARLY,
            attestation={"by": PRIYA, "at": EARLY, "notice_version": "1.0.0"},
        ),
    )
    proposal = _entry(
        "ce_proposed",
        state="proposed",
        start="2026-10-06T12:00:00.000Z",
        end=None,
        created_by=pl.maker_tilo("A_analyst", EARLY),
        source={"kind": "tilo", "from": "meeting", "ref": "mt_priya"},
    )
    entries = [
        _entry("ce_today"),
        proposal,
        _entry("ce_early_ist", start="2026-10-05T19:00:00.000Z", end="2026-10-05T19:30:00.000Z"),
        _entry("ce_late_ist", start="2026-10-06T19:00:00.000Z", end="2026-10-06T19:30:00.000Z"),
        _entry("ce_declined", state="declined"),
        _entry("ce_cancelled", state="cancelled"),
        _entry("ce_tomorrow", start="2026-10-07T08:00:00.000Z", end="2026-10-07T09:00:00.000Z"),
        _entry("ce_yesterday", start="2026-10-05T08:00:00.000Z", end="2026-10-05T09:00:00.000Z"),
        _entry("ce_team_mates", DEV, share={"team": "tm_launch"}),
        _entry("ce_sams", SAM),
    ]
    for entry in entries:
        rig.add("calendar", entry)
    plate = _plate(rig)
    assert {r["ref"]["id"] for r in plate["rows"]} == {"ce_today", "ce_proposed", "ce_early_ist"}, refs(plate)
    for row in plate["rows"]:
        entry = next(e for e in entries if e["id"] == row["ref"]["id"])
        assert row["ref"]["kind"] == "calendar_entry" and (row["reason"], row["group"]) == ("calendar", "soon")
        assert (row["title"], row["at"], row["due"], row["from"], row["actions"]) == (
            entry["title"],
            entry["start"],
            None,
            None,
            ["open"],
        )
    rig.as_user(DEV)  # the teammate's own entry is on their plate, shared or not
    assert {r["ref"]["id"] for r in _plate(rig)["rows"]} == {"ce_team_mates"}


# --- pins -----------------------------------------------------------------------------------------------------------


def test_PPL_11a_PE_27_pins_join_for_their_owner_or_an_active_tag_and_only_while_she_may_read_them(people_rig):
    rig = _rig(people_rig)

    def mk(pin_id: str, **ov):
        base = pl.pin(
            id=pin_id,
            org_id="org_example",
            scope={"kind": "team", "team": "tm_launch"},
            set_up_by=OWNER,
            owner=None,
            due="2026-10-20",
            created_by=pl.maker_person(OWNER, EARLY),
            history=[pl.history_entry(OWNER, "created", "active", EARLY)],
            created_at=EARLY,
            updated_at="2026-10-05T12:00:00.000Z",
        )
        return pl.with_(base, **ov)

    pins = [
        mk("pb_owned", owner=PRIYA),
        mk("pb_tagged"),
        mk("pb_untagged"),
        mk("pb_removed_tag"),
        mk(
            "pb_removed_pin",
            owner=PRIYA,
            status="removed",
            history=[
                pl.history_entry(OWNER, "created", "active", EARLY),
                pl.history_entry(OWNER, "removed", "removed", EARLY),
            ],
        ),
        mk("pb_other_team", scope={"kind": "team", "team": "tm_ops"}, owner=SAM),
        mk("pb_flagged", owner=PRIYA, flagged=True),
    ]
    for pin in pins:
        rig.add("pins", pin)
    for n, (pin_id, user, removed) in enumerate(
        (("pb_tagged", PRIYA, None), ("pb_removed_tag", PRIYA, {"by": PRIYA, "at": EARLY}), ("pb_untagged", DEV, None))
    ):
        rig.add(
            "mentions",
            pl.mention(
                id=f"mn_t{n}",
                org_id="org_example",
                pin_id=pin_id,
                team="tm_launch",
                user=user,
                added_by=pl.maker_person(OWNER, EARLY),
                removed=removed,
            ),
        )
    plate = _plate(rig)
    got = {r["ref"]["id"]: r for r in plate["rows"]}
    assert set(got) == {"pb_owned", "pb_tagged", "pb_flagged"}, sorted(got)
    assert got["pb_owned"]["reason"] == "pin_owner" and got["pb_tagged"]["reason"] == "pin_tagged"
    assert got["pb_flagged"]["flagged"] is True and got["pb_owned"]["flagged"] is False
    assert got["pb_owned"]["from"] == OWNER and got["pb_owned"]["due"] == "2026-10-20"
    assert got["pb_owned"]["at"] == "2026-10-05T12:00:00.000Z"
    rig.as_user(SAM)  # the person who left tm_launch's circle or never joined: nothing of it
    assert {r["ref"]["id"] for r in _plate(rig)["rows"]} == {"pb_other_team"}


# --- everything together, and failures ------------------------------------------------------------------------------


def test_PPL_11a_PE_28_all_six_sources_together_come_out_grouped_ordered_and_fingerprinted(people_rig):
    rig = _rig(people_rig)
    rig.add("work_items", own_item("wi_late", PRIYA, due="2026-10-01"))
    rig.add("calendar", _entry("ce_today"))
    rig.add(
        "pins",
        pl.pin(
            id="pb_mine",
            org_id="org_example",
            scope={"kind": "personal", "user": PRIYA},
            set_up_by=PRIYA,
            created_by=pl.maker_person(PRIYA, EARLY),
            history=[pl.history_entry(PRIYA, "created", "active", EARLY)],
            due="2026-10-07",
            owner=None,
            created_at=EARLY,
            updated_at=EARLY,
        ),
    )
    rig.sources.card_facts.append(_fact(_card("gate_send_reply", f"{ULID}0")))
    rig.sources.run_facts.extend([_run("w_blocked", state="blocked"), _run("w_running")])
    rig.sources.mail_facts.append(_mail("m_own"))
    plate = _plate(rig)
    assert {kind for kind, _ in refs(plate)} == {
        "work_item",
        "calendar_entry",
        "pinboard_item",
        "card",
        "world",
        "mail",
    }
    groups = [r["group"] for r in plate["rows"]]
    assert groups == sorted(groups, key=("attention", "overdue", "soon", "rest").index), (
        "the groups lead in PE-28's order"
    )
    assert groups[:2] == ["attention", "attention"] and groups[2] == "overdue"
    assert len(plate["fingerprint"]) == 64


def test_PPL_11a_HR_1_a_source_that_fails_makes_the_plate_a_503_never_a_partial_plate(people_rig):
    """An honest plate is complete or absent: if cards, runs or mail cannot be read the answer is 503 with no rows,
    not a plate that silently lacks them (ambiguity 6 in API_PPL_11a.md)."""
    for failing in ("cards", "runs", "mail"):
        rig = _rig(people_rig)
        rig.add("work_items", own_item("wi_x", PRIYA))

        def boom(user_id: str):
            raise RuntimeError("the source is down")

        rig.monkeypatch.setattr(rig.sources, failing, boom)
        response = rig.plate()
        assert response.status_code == 503, (failing, response.status_code)
        assert "rows" not in response.json() and "Traceback" not in response.text


@pytest.mark.parametrize("role", ["viewer", "approver", "team_lead", "owner"])
def test_PPL_11a_PE_26_a_world_role_on_the_session_changes_nothing_about_the_plate(people_rig, role):
    rig = _rig(people_rig)
    rig.sources.run_facts.extend([_run("w_mine"), _run("w_theirs", owner=SAM)])
    rig.sources.card_facts.append(_fact(_card("gate_send_reply", f"{ULID}0"), world_owner=SAM))
    rig.as_user(PRIYA, role=role, world_id="w_theirs")  # she is a Viewer (or Lead) of Sam's world
    assert refs(_plate(rig)) == [("world", "w_mine")], "nothing from a world where she is only a Viewer or a Team Lead"


def test_PPL_11a_PE_29_a_title_is_cleaned_like_a_quote_line_and_nothing_else_rides_on_a_row(people_rig):
    rig = _rig(people_rig)
    title = "Pay" + u(0x202E) + " the" + u(0x200B) + " bill" + u(0x0085) + " today" + u(0xE0041)
    rig.add("work_items", own_item("wi_bidi", PRIYA, title=title))
    plate = _plate(rig)
    (row,) = plate["rows"]
    assert row["title"] == "Pay the bill today"
    assert set(row) == {"ref", "reason", "group", "title", "due", "at", "from", "flagged", "evidence", "actions"}
