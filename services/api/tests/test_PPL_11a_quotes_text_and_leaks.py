"""PPL-11a slice A: what a quote may carry and may never reveal (ADR-0020 decisions 4 to 6; PE-22, PE-24, PE-25;
BQ-265, BQ-267, BQ-268; SEC-01; HR-1). Untrusted transcript text is cleaned for every viewer, masked for a viewer who
is not the meeting owner, cut at 240 characters on a word boundary and passed through the shared secret redactor;
a flagged or unscreened transcript leaks nothing to a non-owner, not even through which id is chosen; nothing is
kept, logged or cached; an oversized record cannot stall the API. The text cases are built from the crossref
cases and compared with the contract oracle AND with independent assertions, so a wrong oracle cannot hide a leak.
"""

from __future__ import annotations

import copy
import logging
import time
import unicodedata

import pytest
from _ppl11a_lib import (
    EARLY,
    OWNER,
    PRIYA,
    SAM,
    conforms,
    fake_token,
    fixture_case,
    oracle,
    pl,
)

QUOTES_DEF = "transcript.schema.json#/$defs/evidence_quotes"
BAD_CATEGORIES = ("Cc", "Cf", "Zl", "Zp")


def u(*code_points: int) -> str:
    """Code points as a string (no escape sequences in this file: editors unescape them)."""
    return "".join(chr(c) for c in code_points)


def _case(name: str = "assignee_reads_one_quote") -> dict:
    return fixture_case("transcript", "valid", name)


def _say(case: dict, text: str | None = None, speaker: str | None = None, uid: str = "u0021") -> dict:
    """The case with one utterance's text (and speaker label) replaced."""
    out = copy.deepcopy(case)
    for utterance in out["transcript"]["utterances"]:
        if utterance["id"] == uid:
            utterance["text"] = text if text is not None else utterance["text"]
            utterance["speaker"] = speaker if speaker is not None else utterance["speaker"]
    return out


def _ask(make_rig, case, **rig_kwargs):
    rig = make_rig(**rig_kwargs)
    rig.seed_quote_case(case)
    return rig, rig.quote_request(case)


def _shown(response) -> dict:
    assert response.status_code == 200, response.text[:300]
    (quote,) = response.json()["quotes"][:1]
    return quote


def _clean(text: str) -> str:
    return "".join(c for c in text if unicodedata.category(c) not in BAD_CATEGORIES)


# --- PE-24: untrusted text, for every viewer ------------------------------------------------------------------------

HOSTILE = (
    "Please"
    + u(0x202E)
    + " send"
    + u(0x200B)
    + " the"
    + u(0x0085)
    + " rate"
    + u(0x2028)
    + " sheet"
    + u(0xE0041, 0xE0042)
    + " now"
    + u(0xFEFF)
)


@pytest.mark.parametrize("route", ["assignee", "owner"])
def test_PPL_11a_PE_24_control_format_and_separator_characters_are_removed_for_every_viewer(people_rig, route):
    """Given text with a bidi override, zero-width and BOM characters, a C1 control, a line separator and astral tag
    characters, when anyone reads the quote, then none survives in the text or the speaker (Unicode Cc, Cf, Zl, Zp)."""
    base = _case("assignee_reads_one_quote" if route == "assignee" else "owner_reads_quotes")
    label = "As" + u(0x202E) + "ha" + u(0x200B) + " Rao" + u(0xE0041)
    case = _say(base, HOSTILE, label, "u0021")
    _, response = _ask(people_rig, case)
    assert response.json() == oracle.expected_quotes(case)
    quotes = response.json()["quotes"]
    for quote in quotes:
        assert conforms("transcript.schema.json#/$defs/evidence_quote", quote)
        for field in ("text", "speaker"):
            value = quote[field] or ""
            assert not any(unicodedata.category(c) in BAD_CATEGORIES for c in value), (field, ascii(value))
    first = next(q for q in quotes if q["utterance_id"] == "u0021")
    assert first["text"] == _clean(HOSTILE) == "Please send the rate sheet now"
    if route == "owner":
        assert first["speaker"] == _clean(label) == "Asha Rao"


def test_PPL_11a_PE_24_a_display_name_with_a_zero_width_character_is_cleaned_in_the_speaker(people_rig):
    case = _case()
    case["persons"][OWNER]["display_name"] = "Asha" + u(0x200B, 0x202E) + " Rao"
    _, response = _ask(people_rig, case)
    assert _shown(response)["speaker"] == "Asha Rao" == oracle.expected_quotes(case)["quotes"][0]["speaker"]


def test_PPL_11a_PE_24_a_non_owner_sees_addresses_phone_numbers_and_links_as_removed(people_rig):
    """Given an utterance with an address, a phone number and links, when the assignee reads it, then each is
    `[removed]`; the meeting owner, who owns the transcript, reads the same words unmasked (BQ-268)."""
    words = "Mail asha@example.com or call +91 98765 43210, see https://example.com/q4 or www.example.org/x today"
    case = _say(_case(), words)
    _, response = _ask(people_rig, case)
    quote = _shown(response)
    assert quote["text"] == oracle.expected_quotes(case)["quotes"][0]["text"]
    for leaked in ("@", "example.com", "98765", "https://", "www.", "example.org"):
        assert leaked not in quote["text"], leaked
    assert quote["text"].count("[removed]") >= 4 and quote["text"].endswith("today")
    owner_case = _say(_case("owner_reads_quotes"), words, uid="u0021")
    _, owner_response = _ask(people_rig, owner_case)
    first = next(q for q in owner_response.json()["quotes"] if q["utterance_id"] == "u0021")
    assert first["text"] == words, "the meeting owner reads their own transcript unmasked"


def test_PPL_11a_PE_24_the_text_is_cut_at_240_characters_on_a_word_boundary(people_rig):
    word = "alpha "
    cases = {
        "exactly_240": ("x" * 240, False),
        "241_no_space": ("y" * 241, True),
        "long_words": (word * 80, True),  # 480 characters
        "four_thousand": ("lorem ipsum " * 333, True),  # the transcript contract's 4,000 cap
        "short": ("Yes, with the new discount column.", False),
    }
    for name, (text, truncated) in cases.items():
        for base in ("assignee_reads_one_quote", "owner_reads_quotes"):
            case = _say(_case(base), text)
            _, response = _ask(people_rig, case)
            assert response.json() == oracle.expected_quotes(case), (name, base)
            quote = next(q for q in response.json()["quotes"] if q["utterance_id"] == "u0021")
            assert (quote["truncated"], len(quote["text"]) <= 240) == (truncated, True), (name, base)
            assert conforms("transcript.schema.json#/$defs/evidence_quote", quote)
            if truncated and " " in text[:241]:
                assert text.startswith(quote["text"]) and not quote["text"].endswith(" "), "cut on a word boundary"


def test_PPL_11a_SEC_01_a_secret_in_the_transcript_never_leaves_the_api_and_is_not_logged(people_rig, caplog):
    """The shared secret redactor (deps.get_redactor) sees every shown text, for the owner as well as the assignee,
    and the answer holds the redacted text. Neither the secret nor the quote's words are logged (PE-22)."""
    secret = fake_token()
    caplog.set_level(logging.DEBUG)
    for base in ("assignee_reads_one_quote", "owner_reads_quotes"):
        case = _say(_case(base), f"The key is {secret} please keep it safe")
        rig, response = _ask(people_rig, case)
        assert secret not in response.text, base
        quote = next(q for q in response.json()["quotes"] if q["utterance_id"] == "u0021")
        assert "[REDACTED]" in quote["text"] and "keep it safe" in quote["text"]
        assert any(secret in call for call in rig.redactor.calls), "the redactor was given the text"
    logged = "\n".join(r.getMessage() for r in caplog.records)
    assert secret not in logged and "keep it safe" not in logged and "launch note" not in logged


def test_PPL_11a_PE_22_a_quote_is_computed_each_time_and_nothing_is_kept(people_rig):
    """Never stored, never cached past the request: a read changes no record, and the answer follows the clock."""
    case = _case()
    rig = people_rig()
    rig.seed_quote_case(case)
    before = rig.snapshot()
    assert _shown(rig.quote_request(case))["state"] == "shown"
    assert rig.snapshot() == before, "a quote read writes nothing: no record, no artifact"
    rig.set_now("2026-12-01T00:00:00.000Z")
    assert _shown(rig.quote_request(case))["state"] == "expired", "past 30 days nothing outlives the transcript"
    rig.set_now(case["now"])
    assert _shown(rig.quote_request(case))["state"] == "shown", "and no state stuck from the earlier request"
    assert rig.snapshot() == before


# --- flagged and unscreened content: nothing leaks to a non-owner ---------------------------------------------------


@pytest.mark.parametrize("screening", ["flagged", "unscreened"])
def test_PPL_11a_PE_24_a_non_owner_gets_a_withheld_quote_from_a_flagged_or_unscreened_transcript(people_rig, screening):
    case = _case()
    case["version"]["screening"] = screening
    rig, response = _ask(people_rig, case)
    quote = _shown(response)
    assert (quote["state"], quote["text"], quote["speaker"], quote["truncated"]) == ("withheld", None, None, False)
    assert conforms("transcript.schema.json#/$defs/evidence_quote", quote)
    owner = _case("owner_reads_quotes")
    owner["version"]["screening"] = screening
    _, owner_response = _ask(people_rig, owner)
    assert {q["state"] for q in owner_response.json()["quotes"]} == {"shown"}, "the owner reads their own transcript"


def test_PPL_11a_PE_24_flagged_minutes_withhold_the_quote_from_the_assignee_but_not_the_owner(people_rig):
    case = _case()
    case["minutes"]["flagged"] = True
    _, response = _ask(people_rig, case)
    assert _shown(response)["state"] == "withheld"
    owner = _case("owner_reads_quotes")
    owner["minutes"]["flagged"] = True
    _, owner_response = _ask(people_rig, owner)
    assert {q["state"] for q in owner_response.json()["quotes"]} == {"shown"}


@pytest.mark.parametrize("hold_back", ["flagged_transcript", "unscreened_transcript", "flagged_minutes"])
def test_PPL_11a_PE_24_withholding_reveals_nothing_through_the_id_the_count_or_the_order(people_rig, hold_back):
    """STRICTER THAN THE ORACLE (API_PPL_11a.md, ambiguity 4: the oracle needs a PE-23/24 line): for a non-owner the
    quote's id is chosen from the two records' citations alone, never from what the held-back transcript contains.
    So when the lowest cited id is absent from the transcript, a flagged or unscreened transcript still answers
    that id as `withheld` (not the next id, and not `missing`), while a clean one answers the lowest present id."""
    clean = _case()
    clean["transcript"]["utterances"] = [u_ for u_ in clean["transcript"]["utterances"] if u_["id"] != "u0021"]
    _, response = _ask(people_rig, clean)
    assert [(q["utterance_id"], q["state"]) for q in response.json()["quotes"]] == [("u0022", "shown")]
    held = copy.deepcopy(clean)
    if hold_back == "flagged_minutes":
        held["minutes"]["flagged"] = True
    else:
        held["version"]["screening"] = hold_back.split("_")[0]
    _, response = _ask(people_rig, held)
    got = [(q["utterance_id"], q["state"], q["text"], q["speaker"]) for q in response.json()["quotes"]]
    assert got == [("u0021", "withheld", None, None)], got
    # a second clean-versus-held pair with every id present gives the same id, so presence is never consulted
    full = _case()
    _, a = _ask(people_rig, full)
    full_held = copy.deepcopy(full)
    if hold_back == "flagged_minutes":
        full_held["minutes"]["flagged"] = True
    else:
        full_held["version"]["screening"] = hold_back.split("_")[0]
    _, b = _ask(people_rig, full_held)
    assert [q["utterance_id"] for q in a.json()["quotes"]] == [q["utterance_id"] for q in b.json()["quotes"]]


# --- an oversized record cannot stall the API -----------------------------------------------------------------------


def test_PPL_11a_PE_19_an_item_with_a_huge_history_is_unreadable_and_cannot_stall_the_api(people_rig):
    """`work_item.history` has no maxItems in the contract; `decide` costs about 1 ms per entry uncached, so an
    item with 5,000 entries must not be run through it. The API answers within 2 seconds, fail closed (a 404 on the
    item route) and keeps working for every other request. (Skipped when the contract later caps history.)"""
    from tilo_people.errors import PeopleInputError  # noqa: PLC0415

    case = _case()
    big = copy.deepcopy(case["work_item"])
    big["history"] = big["history"] + [pl.history_entry(PRIYA, "edited", "open", EARLY) for _ in range(5000)]
    case["work_item"] = None
    rig = people_rig()
    rig.seed_quote_case(case)
    try:
        rig.add("work_items", big)
    except PeopleInputError:
        pytest.skip("the contract now caps work_item.history; the store refuses the record")
    rig.require_route(("GET", "/v1/work-items/{work_item_id}/quote"))
    started = time.monotonic()
    response = rig.get("/v1/work-items/wi_rate_sheet/quote")
    assert time.monotonic() - started < 2.0, "the API must cap work, not decide over 5,000 history entries"
    assert response.status_code == 404 and "text" not in response.text
    started = time.monotonic()
    plate = rig.plate()
    assert time.monotonic() - started < 2.0 and plate.status_code == 200
    assert not [r for r in plate.json()["rows"] if r["ref"]["id"] == "wi_rate_sheet"], (
        "an unreadable item is off the plate"
    )
    normal = people_rig()
    normal.seed_quote_case(_case())
    assert normal.quote_request(_case()).status_code == 200, "an ordinary history is still fine"


def test_PPL_11a_PE_19_a_forged_person_made_item_cannot_probe_for_a_meeting_id(people_rig):
    """The item route is not an existence oracle for meeting ids: an item that names someone else's meeting but was
    not made by Tilo is a 404 whether that meeting exists or not, and the 404 is the same body."""
    from tilo_people.stores import meeting_tombstone  # noqa: PLC0415

    seen = set()
    for meeting_id in ("mt_q4_plan", "mt_never_held", "mt_deleted_one"):
        case = _case()
        forged = pl.work_item(
            id="wi_forged",
            org_id="org_example",
            owner=SAM,
            title="Probe",
            due=None,
            due_text=None,
            source={"kind": "meeting", "ref": f"{meeting_id}#ai1", "evidence": ["u0021"]},
            created_by=pl.maker_person(SAM, EARLY),
            assigned_by=None,
            confirmed_by=None,
            snoozed_until=None,
            history=[pl.history_entry(SAM, "created", "open", EARLY)],
            created_at=EARLY,
            updated_at=EARLY,
        )
        case["work_item"] = forged
        case["request"] = {"actor": SAM, "meeting": None, "work_item": "wi_forged", "ids": []}
        assert oracle.expected_quotes(case) is None
        rig = people_rig()
        rig.seed_quote_case(case)
        rig.add("meetings", meeting_tombstone({**case["meeting"], "id": "mt_deleted_one"}))  # a deleted one exists too
        response = rig.quote_request(case)
        assert response.status_code == 404
        seen.add(response.text)
    assert len(seen) == 1
