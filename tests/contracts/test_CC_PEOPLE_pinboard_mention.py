"""CC-PEOPLE: contracts/pinboard_item.schema.json and contracts/mention.schema.json.

FR-PB-01 (team board), FR-PB-02 (personal board: owner only, never proposed), FR-PB-03 (get in
touch: the item names its `set_up_by` person), FR-PB-04 (tag a team member), FR-PB-06 (Tilo-made
items carry a source; a team item Tilo made becomes active only when a person confirms), and
people.rules.md PE-01, PE-02, PE-06, PE-08.
"""

from __future__ import annotations

import _people_lib as pl
import pytest
from hypothesis import Phase, given, settings
from hypothesis import strategies as st

PIN_REQUIRED = (
    "id",
    "org_id",
    "scope",
    "title",
    "body",
    "kind",
    "url",
    "owner",
    "due",
    "status",
    "created_by",
    "set_up_by",
    "source",
    "confirmed_by",
    "history",
    "created_at",
    "updated_at",
)
MENTION_REQUIRED = ("id", "org_id", "pin_id", "team", "user", "added_by", "removed")
TILO = pl.maker_tilo("A_notes")
SOURCE = {"kind": "meeting", "ref": "mt_weekly1", "evidence": ["u0004"]}


def v(repo_root, registry, doc, why=""):
    pl.assert_valid(repo_root, registry, "pinboard_item", doc, None, why or "pinboard_item")


def i(repo_root, registry, doc, why=""):
    pl.assert_invalid(repo_root, registry, "pinboard_item", doc, None, why or "pinboard_item")


def mv(repo_root, registry, doc, why=""):
    pl.assert_valid(repo_root, registry, "mention", doc, None, why or "mention")


def mi(repo_root, registry, doc, why=""):
    pl.assert_invalid(repo_root, registry, "mention", doc, None, why or "mention")


# ---------------------------------------------------------------------------------------------
# pinboard_item
# ---------------------------------------------------------------------------------------------
def test_CC_PEOPLE_FR_PB_01_a_team_pin_and_a_personal_pin_are_valid(repo_root, registry):
    v(repo_root, registry, pl.pin(), "team pin")
    v(repo_root, registry, pl.personal_pin(), "personal pin")
    for kind in ("note", "decision", "deadline", "link"):
        v(repo_root, registry, pl.pin(kind=kind), kind)
    v(
        repo_root,
        registry,
        pl.pin(body="Freeze on 31 Oct.", owner="u_riya", url="https://example.com/plan"),
        "all optional fields",
    )


@pytest.mark.parametrize("field", PIN_REQUIRED)
def test_CC_PEOPLE_FR_PB_01_every_pin_field_is_required(repo_root, registry, field):
    i(repo_root, registry, pl.drop(pl.pin(), (field,)), f"pin without {field}")


@pytest.mark.parametrize("extra", ["pinned", "team", "user", "priority", "attachment", "score", "views"])
def test_CC_PEOPLE_FR_PB_01_a_pin_holds_no_field_beyond_the_contract(repo_root, registry, extra):
    i(repo_root, registry, pl.with_(pl.pin(), **{extra: "x"}), extra)


def test_CC_PEOPLE_PE_01_scope_is_exactly_personal_with_a_user_or_team_with_a_team(repo_root, registry):
    for ok in ({"kind": "team", "team": "tm_sales"},):
        v(repo_root, registry, pl.pin(scope=ok), str(ok))
    v(repo_root, registry, pl.personal_pin(scope={"kind": "personal", "user": "u_riya"}), "personal scope")
    bad = [
        {"kind": "personal"},
        {"kind": "team"},
        {"kind": "personal", "user": "u_riya", "team": "tm_sales"},
        {"kind": "team", "team": "tm_sales", "user": "u_riya"},
        {"kind": "personal", "team": "tm_sales"},
        {"kind": "team", "user": "u_riya"},
        {"kind": "org", "org": "org_acme"},
        {"kind": "all"},
        {"kind": "team", "team": "sales"},
        {"kind": "team", "team": None},
        {"kind": "personal", "user": "riya"},
        {"kind": "personal", "user": None},
        {"team": "tm_sales"},
        {"user": "u_riya"},
        None,
        "team",
    ]
    for scope in bad:
        i(repo_root, registry, pl.pin(scope=scope), f"scope {scope!r}")


@pytest.mark.parametrize(
    "url",
    [
        "https://example.com",
        "https://example.com/",
        "https://example.org/docs/plan-2026",
        "https://sub.example.com/a/b/c",
    ],
)
def test_CC_PEOPLE_FR_PB_01_url_accepts_a_plain_https_address(repo_root, registry, url):
    v(repo_root, registry, pl.pin(kind="link", url=url), url)


def _bad_urls() -> list[str]:
    user_info = "https://" + "bob" + ":" + "pw" + "@example.com/x"  # assembled at runtime, never a real login
    return [
        "http://example.com/x",
        "ftp://example.com/x",
        "javascript:alert(1)",
        "data:text/html;base64,AAAA",
        "//example.com/x",
        "example.com/x",
        "https://",
        "",
        user_info,
        "https://bob@example.com/x",
        "https://example.com/x?token=abc",
        "https://example.com/x?",
        "https://example.com/x#frag",
        "https://example.com/x#",
        "https://example.com/x\n",
        "https://example.com/\nx",
        "https://example.com/x\r",
        "https://example.com/x\r\nSet-Cookie: a=b",
    ]


@pytest.mark.parametrize("url", _bad_urls())
def test_CC_PEOPLE_FR_PB_01_url_rejects_user_info_query_fragment_newline_and_other_schemes(repo_root, registry, url):
    i(repo_root, registry, pl.pin(kind="link", url=url), repr(url))


@settings(max_examples=40, phases=[Phase.generate])
@given(
    path=st.text(alphabet="abcdefghijklmnopqrstuvwxyz0123456789-_", min_size=0, max_size=25),
    tail=st.text(alphabet="abcdefghijklmnopqrstuvwxyz0123456789=&", min_size=0, max_size=12),
    mark=st.sampled_from(["?", "#"]),
)
def test_CC_PEOPLE_FR_PB_01_property_a_plain_path_is_valid_and_a_query_or_fragment_never_is(
    repo_root, registry, path, tail, mark
):
    plain = f"https://example.com/{path}"
    v(repo_root, registry, pl.pin(kind="link", url=plain), plain)
    i(repo_root, registry, pl.pin(kind="link", url=plain + mark + tail), plain + mark + tail)


def test_CC_PEOPLE_FR_PB_01_title_body_and_enums_are_bounded(repo_root, registry):
    v(repo_root, registry, pl.pin(body="b" * 600), "body of 600")
    i(repo_root, registry, pl.pin(body="b" * 601), "body of 601")
    i(repo_root, registry, pl.pin(body=""), "empty body")
    for bad in ("memo", "Note", "", None):
        i(repo_root, registry, pl.pin(kind=bad), f"kind {bad!r}")
    for bad in ("pending", "Active", "", None):
        i(repo_root, registry, pl.pin(status=bad), f"status {bad!r}")
    for bad in ("friday", "2026-10-31T00:00:00.000Z"):
        i(repo_root, registry, pl.pin(due=bad), f"due {bad!r}")
    for bad in ("riya", "A_notes"):
        i(repo_root, registry, pl.pin(owner=bad), f"owner {bad!r}")


def test_CC_PEOPLE_FR_PB_03_set_up_by_is_always_a_person(repo_root, registry):
    for bad in ("tilo", "A_notes", "system", None, "u_"):
        i(repo_root, registry, pl.pin(set_up_by=bad), f"set_up_by {bad!r}")


def test_CC_PEOPLE_PE_08_source_is_null_or_a_closed_kind_with_an_opaque_ref_and_five_evidence_ids(repo_root, registry):
    for kind in ("meeting", "mail", "call", "request", "manual"):
        v(repo_root, registry, pl.pin(created_by=TILO, source={**SOURCE, "kind": kind}, status="proposed"), kind)
    v(repo_root, registry, pl.pin(source={**SOURCE, "ref": None}), "null ref")
    for bad in ("pinboard", "transcript", "", None):
        i(repo_root, registry, pl.pin(source={**SOURCE, "kind": bad}), f"source kind {bad!r}")
    for bad in ("https://example.com/m", "a:b", "a/b", "a.b", "", "x" * 97):
        i(repo_root, registry, pl.pin(source={**SOURCE, "ref": bad}), f"source ref {bad!r}")
    ids = [f"u{n:04d}" for n in range(1, 7)]
    v(repo_root, registry, pl.pin(source={**SOURCE, "evidence": ids[:5]}), "5 evidence ids")
    i(repo_root, registry, pl.pin(source={**SOURCE, "evidence": ids}), "6 evidence ids")
    i(repo_root, registry, pl.pin(source={**SOURCE, "evidence": ["u1"]}), "bad evidence id")
    i(repo_root, registry, pl.pin(source={**SOURCE, "quote": "x"}), "extra key in source")


def test_CC_PEOPLE_PE_08_history_is_never_empty_and_uses_the_pin_changes(repo_root, registry):
    i(repo_root, registry, pl.pin(history=[]), "empty history")
    for change in ("created", "edited", "accepted", "removed", "undone", "owner_changed"):
        v(repo_root, registry, pl.pin(history=[pl.history_entry(change=change, status="active")]), change)
    for change in ("reopened", "done", "snoozed", "deleted", "", None):
        i(repo_root, registry, pl.pin(history=[pl.history_entry(change=change, status="active")]), f"change {change!r}")
    for status in ("proposed", "active", "removed"):
        v(repo_root, registry, pl.pin(history=[pl.history_entry(status=status)]), f"history status {status}")
    for status in ("open", "done", "dropped", None):
        i(repo_root, registry, pl.pin(history=[pl.history_entry(status=status)]), f"history status {status!r}")
    for actor in pl.VALID_ACTORS:
        v(repo_root, registry, pl.pin(history=[pl.history_entry(by=actor, status="active")]), actor)
    for actor in pl.INVALID_ACTORS:
        i(repo_root, registry, pl.pin(history=[pl.history_entry(by=actor, status="active")]), repr(actor))
    i(repo_root, registry, pl.pin(history=[pl.with_(pl.history_entry(), note="x")]), "extra key in history entry")


def test_CC_PEOPLE_PE_01_a_personal_pin_has_no_owner_and_is_never_proposed(repo_root, registry):
    i(repo_root, registry, pl.personal_pin(owner="u_riya"), "personal pin with an owner")
    i(repo_root, registry, pl.personal_pin(owner="u_owner"), "personal pin owned by someone else")
    i(repo_root, registry, pl.personal_pin(status="proposed"), "personal pin proposed")
    for status in ("active", "removed"):
        v(repo_root, registry, pl.personal_pin(status=status), status)
    v(repo_root, registry, pl.pin(owner="u_riya", status="proposed"), "a team pin may be owned and proposed")


def test_CC_PEOPLE_PE_08_an_item_tilo_made_names_its_source(repo_root, registry):
    i(repo_root, registry, pl.pin(created_by=TILO, source=None, status="proposed"), "Tilo-made team pin without source")
    i(
        repo_root,
        registry,
        pl.personal_pin(created_by=TILO, source=None),
        "Tilo-made personal pin without source",
    )
    v(repo_root, registry, pl.pin(created_by=TILO, source=SOURCE, status="proposed"), "Tilo-made with source")
    v(repo_root, registry, pl.pin(created_by=pl.maker_person(), source=None), "person-made needs no source")


def test_CC_PEOPLE_PE_07_a_team_pin_tilo_made_is_active_only_when_a_person_confirmed_it(repo_root, registry):
    tilo_team = {"created_by": TILO, "source": SOURCE}
    i(repo_root, registry, pl.pin(**tilo_team, status="active", confirmed_by=None), "active without confirmation")
    v(repo_root, registry, pl.pin(**tilo_team, status="active", confirmed_by=pl.assignment()), "active and confirmed")
    v(repo_root, registry, pl.pin(**tilo_team, status="proposed", confirmed_by=None), "proposed waits")
    v(repo_root, registry, pl.pin(**tilo_team, status="removed", confirmed_by=None), "removed needs no confirmation")
    i(
        repo_root,
        registry,
        pl.pin(**tilo_team, status="active", confirmed_by={"by": "A_notes", "at": pl.T0}),
        "Tilo cannot confirm its own item",
    )
    v(
        repo_root,
        registry,
        pl.pin(created_by=pl.maker_person(), status="active", confirmed_by=None),
        "person-made active",
    )


def test_CC_PEOPLE_PE_08_on_the_personal_board_tilo_adds_active_without_confirmation(repo_root, registry):
    v(
        repo_root,
        registry,
        pl.personal_pin(created_by=TILO, source=SOURCE, status="active", confirmed_by=None),
        "added by Tilo",
    )
    v(
        repo_root,
        registry,
        pl.personal_pin(
            created_by=TILO,
            source=SOURCE,
            status="removed",
            history=[pl.history_entry("A_notes", "created", "active"), pl.history_entry("u_riya", "undone", "removed")],
        ),
        "undone by the person",
    )


# ---------------------------------------------------------------------------------------------
# mention
# ---------------------------------------------------------------------------------------------
def test_CC_PEOPLE_FR_PB_04_a_mention_names_a_team_pin_a_team_and_the_tagged_person(repo_root, registry):
    mv(repo_root, registry, pl.mention())
    mv(repo_root, registry, pl.mention(added_by=TILO), "tag added by Tilo")


@pytest.mark.parametrize("field", MENTION_REQUIRED)
def test_CC_PEOPLE_FR_PB_04_every_mention_field_is_required(repo_root, registry, field):
    mi(repo_root, registry, pl.drop(pl.mention(), (field,)), f"mention without {field}")


@pytest.mark.parametrize("extra", ["scope", "personal", "reason", "message", "channel", "title"])
def test_CC_PEOPLE_PE_01_a_mention_has_no_personal_variant_and_no_extra_field(repo_root, registry, extra):
    mi(repo_root, registry, pl.with_(pl.mention(), **{extra: "x"}), extra)
    swapped = pl.drop(pl.mention(), ("team",))
    mi(
        repo_root,
        registry,
        pl.with_(swapped, scope={"kind": "personal", "user": "u_riya"}),
        "personal scope in place of a team",
    )


@pytest.mark.parametrize(
    "field,bad",
    [
        ("id", "wi_tag1"),
        ("id", "mn_"),
        ("pin_id", "wi_budget1"),
        ("pin_id", "pb_"),
        ("team", "sales"),
        ("team", "u_riya"),
        ("team", None),
        ("user", "riya"),
        ("user", "A_notes"),
        ("user", None),
        ("org_id", "acme"),
    ],
)
def test_CC_PEOPLE_FR_PB_04_ids_have_their_shapes(repo_root, registry, field, bad):
    mi(repo_root, registry, pl.mention(**{field: bad}), f"{field}={bad!r}")


@pytest.mark.parametrize(
    "added_by",
    [None, {"by": "tilo", "ref": "u_owner", "at": pl.T0}, {"by": "person", "ref": "A_notes", "at": pl.T0}, "u_owner"],
)
def test_CC_PEOPLE_PE_06_added_by_is_a_maker(repo_root, registry, added_by):
    mi(repo_root, registry, pl.mention(added_by=added_by), f"added_by={added_by!r}")


def test_CC_PEOPLE_PE_06_removed_is_null_or_who_removed_it_and_when(repo_root, registry):
    mv(repo_root, registry, pl.mention(removed={"by": "u_riya", "at": pl.T1}), "removed by the tagged person")
    mv(repo_root, registry, pl.mention(removed={"by": "u_owner", "at": pl.T1}), "removed by the set-up person")
    for bad in (
        {"by": "A_notes", "at": pl.T1},
        {"by": "system", "at": pl.T1},
        {"by": "u_riya"},
        {"at": pl.T1},
        {"by": "u_riya", "at": "2026-10-02"},
        {"by": "u_riya", "at": pl.T1, "reason": "x"},
        {},
        True,
        "u_riya",
    ):
        mi(repo_root, registry, pl.mention(removed=bad), f"removed={bad!r}")
