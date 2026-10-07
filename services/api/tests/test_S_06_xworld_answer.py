"""S-06 cross-world answering (ticket API-CARDS-XWORLD, issue #539; PRD 18 S-06, FR-HIL-01, FR-HIL-04 T3 never
automated, FR-HIL-11, SEC-06, SEC-07, SEC-11; PRD 10.1, 10.3, 10.4 Audit): an owner answers the cards of every world
they own from one session, through the existing `POST /worlds/{world_id}/cards/{card_id}/answer`.

Acceptance tests, written before any implementation. The pinned rules and every default chosen are in
API_CARDS_XWORLD.md and docs/open-questions.md (BQ-XWORLD-1..8).

Through the public interface only: the real `tilo_api.app` over the in-memory `Store` (`client`, `store` from
conftest.py). Each world's cards live where the routes read them, the world's run's `CardStore`
(`store.runs[world_id].cards`, what `tilo_api.runs.get_card_store` returns), seeded with a real `CardStore` over a
recording writer. No network, no model, no paid call, no cloud; the fake bearer token is assembled at runtime.

Until the change lands, an owner's answer or per-world read in a world their session does not name is today's 404,
so every positive test fails on that 404, not on an import or a typo.
"""

from __future__ import annotations

import logging
import secrets
from types import SimpleNamespace

import pytest
from _api_lib import as_principal, make_principal, make_store, make_world
from _cards_lib import FakeClock, clone_card, load_valid_card, new_ulid
from _cards_lib import FakeEventWriter as CardWriter
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st
from tilo_api import app, cards, deps
from tilo_api.cards import CardStore

ALICE, BOB, CARA = "u_alice", "u_bob", "u_cara"
A, B, C = "w_alice_a", "w_alice_b", "w_alice_c"  # Alice's worlds; none is a substring of another
D = "w_bob_d"  # Bob's world
GHOST = "w_nobody_here"  # no record, no run
START = "2026-09-29T09:30:00.000Z"
ANSWERED = {"outcome": "answered"}

# kind -> (fixture, an option that resolves the card when a person picks it, the event that option writes)
KINDS = {
    "needs_you": ("needs_you_compare_basis", "per_kwh", "question.answered"),
    "gate": ("gate_send_reply", "approve", "approval.resolved"),  # T3, irreversible: only a person's approve opens it
    "consent": ("consent_drive_folder", "connect", "connection.consented"),
    "meeting": ("meeting_budget_split", "even", "question.answered"),  # answer_channels: ["web"] only
}


class World:
    """One seeded world: its record, its run's CardStore and that store's recording writer. `card_store_owner`
    is the owner the run's CardStore was built with; it normally equals the WorldRecord owner."""

    def __init__(
        self,
        store: deps.Store,
        world_id: str,
        owner: str,
        *,
        card_store_owner: str | None = None,
        paused: bool = False,
    ) -> None:
        self.world_id, self.owner = world_id, owner
        self.clock, self.writer = FakeClock(START), CardWriter()
        owners = {world_id: card_store_owner or owner}
        self.cards = CardStore(clock=self.clock, writer=self.writer, world_owners=owners)
        store.worlds[world_id] = make_world(owner=owner, paused=paused)
        store.runs[world_id] = SimpleNamespace(cards=self.cards)  # what runs.get_card_store reads

    def add(
        self,
        kind: str = "needs_you",
        *,
        seed: str = "1",
        district: str | None = None,
        assignee: str | None = None,
        what_happened: str | None = None,
    ) -> dict:
        """A schema-valid card whose id depends only on (world, seed), so two identical setups get identical ids."""
        card = clone_card(load_valid_card(KINDS[kind][0]), id_=new_ulid(f"{self.world_id}:{seed}"), created_at=START)
        card["world_id"] = self.world_id
        if what_happened is not None:
            card["what_happened"] = what_happened
        outbox = new_ulid(f"outbox:{self.world_id}:{seed}") if kind == "gate" else None
        result = self.cards.submit(card, outbox_id=outbox, district=district, assignee=assignee, merge=False)
        assert result.outcome == "accepted", result.errors
        return card

    def is_open(self, card: dict) -> bool:
        return self.cards.is_open(self.world_id, card["id"])


def use(store: deps.Store) -> None:
    app.dependency_overrides[deps.get_store] = lambda: store


def sign_in(
    user: str = ALICE,
    role: str = "owner",
    world_id: str | None = A,
    *,
    channel: str = "web",
    districts: tuple[str, ...] = (),
    from_channels: bool = False,
) -> None:
    """The verified principal (the only source of who answers and on which channel) and whether the request was
    authenticated as tilo-channels acting for an email session."""
    as_principal(make_principal(user_id=user, role=role, world_id=world_id, channel=channel, districts=districts))
    app.dependency_overrides[cards.get_channels_caller] = lambda: from_channels


def post_answer(client, world_id: str, card_id: str, option: str, channel: str = "web", **extra):
    return client.post(
        f"/worlds/{world_id}/cards/{card_id}/answer", json={"option": option, "channel": channel, **extra}
    )


def outcome(response) -> tuple[int, object]:
    return response.status_code, response.json()


def unknown_world(client, card_id: str, option: str = "approve", channel: str = "web") -> tuple[int, object]:
    """What the signed-in principal gets for a world that does not exist: the one 404 every refusal must equal."""
    response = post_answer(client, GHOST, card_id, option, channel)
    assert response.status_code == 404, response.text
    return outcome(response)


def two_worlds(store: deps.Store, kind: str = "gate", **world_b) -> tuple[World, World, dict]:
    """Alice owns A (the world her session names) and B; one open card waits in B."""
    wa, wb = World(store, A, ALICE), World(store, B, ALICE, **world_b)
    return wa, wb, wb.add(kind)


# --- 1. the owner answers in another owned world ------------------------------------------------------------------


@pytest.mark.parametrize("kind", list(KINDS))
def test_S_06_xworld_owner_answers_an_open_card_in_another_owned_world(client, store, kind):
    """Alice's session names A; she answers B's card on the same route with world_id B (issue #539)."""
    wa, wb, card = two_worlds(store, kind)
    sign_in(ALICE, world_id=A)

    response = post_answer(client, B, card["id"], KINDS[kind][1])

    assert outcome(response) == (200, ANSWERED), response.text
    assert [p["type"] for p in wb.writer.parts] == [KINDS[kind][2]]
    part = wb.writer.parts[0]
    assert (part["world_id"], part["card_id"]) == (B, card["id"])  # written in the card's world, never the session's
    assert not wb.is_open(card)
    assert wa.writer.parts == []


def _answer_in_fresh_store(client, kind: str, option: str, session_world: str | None, channel: str = "web"):
    """One answer to B's card in a fresh, identical store; returns everything a person or the run could observe."""
    store = make_store()
    use(store)
    wa, wb, card = two_worlds(store, kind)
    sign_in(ALICE, world_id=session_world, channel=channel)
    response = post_answer(client, B, card["id"], option, channel)
    return {
        "response": outcome(response),
        "parts": wb.writer.parts,
        "open": wb.is_open(card),
        "session_world_parts": wa.writer.parts,
        "events": store.events,
        "pending": store.pending_events,
    }


@pytest.mark.parametrize("session_world", [A, None], ids=["session_names_A", "session_names_no_world"])
@pytest.mark.parametrize(
    ("kind", "option"),
    [
        ("needs_you", "per_kwh"),
        ("needs_you", "per_pack"),
        ("gate", "approve"),
        ("gate", "edit"),  # CR-07: writes nothing, but is an answer
        ("gate", "hold"),
        ("consent", "connect"),
        ("consent", "hold"),
        ("meeting", "even"),
    ],
)
def test_S_06_xworld_cross_world_answer_is_exactly_the_answer_from_a_session_bound_to_that_world(
    client, kind, option, session_world
):
    """The same outcome, the same events (type, data, authz {by person, ref, at}, event id, scope) and the same open
    state as answering from a session that names B. The event carries no audit field of its own (BQ-XWORLD-4)."""
    bound = _answer_in_fresh_store(client, kind, option, B)
    assert bound["response"] == (200, ANSWERED)  # the reference: today's behaviour

    cross = _answer_in_fresh_store(client, kind, option, session_world)

    assert cross == bound


@pytest.mark.parametrize("kind", ["gate", "needs_you", "consent"])
def test_S_06_xworld_a_mobile_web_session_answers_across_worlds_like_a_web_session(client, kind):
    """web and mobile_web are one signed-in session class (SEC-06 as amended, ADR-0019); the channel is recorded."""
    bound = _answer_in_fresh_store(client, kind, KINDS[kind][1], B, channel="mobile_web")
    cross = _answer_in_fresh_store(client, kind, KINDS[kind][1], A, channel="mobile_web")

    assert cross["response"] == (200, ANSWERED)
    assert cross == bound
    if kind == "gate":
        assert [p["data"]["channel"] for p in cross["parts"]] == ["mobile_web"]


def test_S_06_xworld_a_gate_answered_across_worlds_is_authorised_by_that_person_only(client, store):
    """T3 always needs a person and a model never decides authorisation: approval.resolved names the signed-in owner."""
    _, wb, card = two_worlds(store, "gate")
    assert card["gate"]["risk_tier"] == "T3"
    sign_in(ALICE, world_id=A)

    assert outcome(post_answer(client, B, card["id"], "approve")) == (200, ANSWERED)

    [part] = wb.writer.of_type("approval.resolved")
    assert part["authz"] == {"by": "person", "ref": ALICE, "at": START}
    assert part["data"]["option"] == "approve" and part["data"]["channel"] == "web"
    assert part["data"]["pin_verified"] is False  # no PIN path exists (ADR-0019); never true from a body


# --- 2. ownership per card ----------------------------------------------------------------------------------------


def test_S_06_xworld_another_owners_world_is_the_same_404_as_an_unknown_world(client, store):
    """No oracle: Bob's world with a real open card, Bob's world with no such card and a world that does not exist
    all answer Alice the same; nothing is written and Bob's card stays open."""
    World(store, A, ALICE)
    wd = World(store, D, BOB)
    bobs = wd.add("gate")
    sign_in(ALICE, world_id=A)
    expected = unknown_world(client, bobs["id"])

    assert outcome(post_answer(client, D, bobs["id"], "approve")) == expected
    assert outcome(post_answer(client, D, new_ulid("no-such-card"), "approve")) == expected
    assert wd.writer.parts == [] and wd.is_open(bobs)


@pytest.mark.parametrize(
    ("record_owner", "card_store_owner"), [(ALICE, BOB), (BOB, ALICE)], ids=["store_disagrees", "record_disagrees"]
)
def test_S_06_xworld_the_world_record_owner_and_the_card_store_owner_must_both_be_the_caller(
    client, store, record_owner, card_store_owner
):
    """Ownership is checked per card against the WorldRecord owner of the card's world, and the run's CardStore owner
    check agrees: when the two disagree the answer fails closed as the unknown-world 404 (BQ-XWORLD-1)."""
    World(store, A, ALICE)
    wb = World(store, B, record_owner, card_store_owner=card_store_owner)
    card = wb.add("gate")
    sign_in(ALICE, world_id=A)
    expected = unknown_world(client, card["id"])

    assert outcome(post_answer(client, B, card["id"], "approve")) == expected
    assert wb.writer.parts == [] and wb.is_open(card)


def test_S_06_xworld_ownership_is_checked_per_card_not_granted_by_the_session(client, store):
    """One session answers in B (Alice's) and is refused in D (Bob's): answering in one world opens no other."""
    World(store, A, ALICE)
    wb, wd = World(store, B, ALICE), World(store, D, BOB)
    mine, bobs = wb.add("needs_you"), wd.add("needs_you")
    sign_in(ALICE, world_id=A)
    expected = unknown_world(client, bobs["id"], "per_kwh")

    assert outcome(post_answer(client, B, mine["id"], "per_kwh")) == (200, ANSWERED)
    assert outcome(post_answer(client, D, bobs["id"], "per_kwh")) == expected
    assert wd.writer.parts == [] and wd.is_open(bobs)


def test_S_06_xworld_an_unknown_card_in_an_owned_world_is_what_a_bound_session_gets(client):
    """In a world the owner owns, an unknown card id is exactly the bound session's answer (no new oracle)."""
    results = []
    for session_world in (B, A):
        store = make_store()
        use(store)
        two_worlds(store, "gate")
        sign_in(ALICE, world_id=session_world)
        results.append(outcome(post_answer(client, B, new_ulid("no-such-card"), "approve")))

    assert results[0][0] == 404
    assert results[1] == results[0]


@pytest.mark.parametrize("role", ["approver", "team_lead", "viewer"])
def test_S_06_xworld_non_owner_roles_keep_their_one_world_binding(client, store, role):
    """An Approver, a Team Lead and a Viewer act only in the world their principal names: B's card, assigned to Cara
    and in her district, is the unknown-world 404 from a session naming A, for answers and per-world reads alike."""
    World(store, A, ALICE)
    wb = World(store, B, ALICE)
    kind = "gate" if role == "approver" else "needs_you"
    card = wb.add(kind, district="D1", assignee=CARA if role == "approver" else None)
    option = KINDS[kind][1]
    sign_in(CARA, role=role, world_id=A, districts=("D1",))
    expected = unknown_world(client, card["id"], option)

    assert outcome(post_answer(client, B, card["id"], option)) == expected
    assert client.get(f"/worlds/{B}/cards").status_code == 404
    assert wb.writer.parts == [] and wb.is_open(card)

    sign_in(CARA, role=role, world_id=B, districts=("D1",))  # control: bound to B, today's rules are unchanged
    bound = post_answer(client, B, card["id"], option)
    assert bound.status_code == (403 if role == "viewer" else 200), bound.text


# --- 3. session kind ----------------------------------------------------------------------------------------------


def test_S_06_xworld_an_email_session_never_answers_across_worlds(client, store):
    """A signed email link's session is minted for one world and one card (PRD 10.3): a tilo-channels caller acting
    for an email session answers only in the world its principal names (BQ-XWORLD-2)."""
    World(store, A, ALICE)
    wb = World(store, B, ALICE)
    card = wb.add("needs_you")
    sign_in(ALICE, world_id=A, channel="email", from_channels=True)
    expected = unknown_world(client, card["id"], "per_kwh", "email")

    assert outcome(post_answer(client, B, card["id"], "per_kwh", "email")) == expected
    assert wb.writer.parts == [] and wb.is_open(card)

    sign_in(ALICE, world_id=B, channel="email", from_channels=True)  # control: bound to B it answers, as today
    assert outcome(post_answer(client, B, card["id"], "per_kwh", "email")) == (200, ANSWERED)


@pytest.mark.parametrize(
    ("channel", "from_channels", "claimed"),
    [("web", True, "web"), ("email", False, "email"), ("email", False, "web"), ("mobile_web", True, "email")],
    ids=["channels_caller_web_principal", "email_principal_direct", "email_principal_claims_web", "channels_mobile"],
)
def test_S_06_xworld_only_a_users_own_web_or_mobile_web_session_answers_across_worlds(
    client, store, channel, from_channels, claimed
):
    """Any session that is not the user's own web or mobile_web session is refused cross-world with the unknown-world
    404, before any channel check could tell it the world is theirs."""
    World(store, A, ALICE)
    wb = World(store, B, ALICE)
    card = wb.add("needs_you")
    sign_in(ALICE, world_id=A, channel=channel, from_channels=from_channels)
    expected = unknown_world(client, card["id"], "per_kwh", claimed)

    assert outcome(post_answer(client, B, card["id"], "per_kwh", claimed)) == expected
    assert wb.writer.parts == [] and wb.is_open(card)


# --- 4. every existing check applies unchanged; no auto-answer ----------------------------------------------------


def _check_case(client, case: str, session_world: str) -> dict:
    """One refusal case in a fresh store, answered from `session_world`."""
    store = make_store()
    use(store)
    kind = {"invalid_option": "needs_you", "channel_not_on_card": "meeting"}.get(case, "gate")
    wa, wb, card = two_worlds(store, kind, paused=(case == "paused"))
    channel = "mobile_web" if case == "channel_not_on_card" else "web"
    if case == "already_resolved":
        sign_in(ALICE, world_id=B)
        assert post_answer(client, B, card["id"], "approve").status_code == 200
    sign_in(ALICE, world_id=session_world, channel=channel)
    option, claimed, extra = KINDS[kind][1], channel, {}
    if case == "invalid_option":
        option = "not_an_option"
    elif case == "pin_verified":
        extra = {"pin_verified": True}
    elif case == "body_claims_email":
        claimed = "email"
    response = post_answer(client, B, card["id"], option, claimed, **extra)
    return {"response": outcome(response), "parts": wb.writer.parts, "open": wb.is_open(card), "a": wa.writer.parts}


@pytest.mark.parametrize(
    ("case", "status", "reason"),
    [
        ("invalid_option", 400, "invalid_option"),
        ("pin_verified", 403, "channel_not_permitted"),  # no PIN path exists (ADR-0019): a body claiming one is refused
        ("body_claims_email", 403, "channel_not_permitted"),  # a web session never records email
        ("channel_not_on_card", 400, "invalid_channel"),  # the meeting card lists web only
        ("already_resolved", 400, "already_resolved"),  # first answer wins
        ("paused", 409, None),  # Pause all of the card's world: nothing it holds is answered
    ],
)
def test_S_06_xworld_every_answer_check_applies_unchanged_across_worlds(client, case, status, reason):
    """Option validity, allowed channels, the refused PIN claim, already_resolved and Pause all: the same status, the
    same body and the same (lack of) writes as from a session bound to the card's world."""
    bound = _check_case(client, case, B)
    assert bound["response"][0] == status, bound["response"]
    if reason is not None:
        assert bound["response"][1] == {"outcome": "rejected", "reason": reason}

    cross = _check_case(client, case, A)

    assert cross == bound


def test_S_06_xworld_pause_follows_the_cards_world_not_the_sessions(client, store):
    """Pause all stops one world's run (FR-WLD-07): a paused session world does not stop an answer in an unpaused
    owned world, and a paused target world refuses it (BQ-XWORLD-8)."""
    World(store, A, ALICE, paused=True)
    wb = World(store, B, ALICE)
    card = wb.add("gate")
    sign_in(ALICE, world_id=A)

    assert outcome(post_answer(client, B, card["id"], "approve")) == (200, ANSWERED)
    assert len(wb.writer.of_type("approval.resolved")) == 1


def test_S_06_xworld_reading_never_answers_and_a_t3_gate_waits_for_a_person(client, store):
    """Reading GET /cards or GET /worlds/{B}/cards, however often and even past the gate's deadline, answers nothing:
    the T3 gate stays open until the person's own answer writes exactly one approval.resolved."""
    wa, wb, card = two_worlds(store, "gate")
    wb.clock.advance(card["timeout"] + 60)
    sign_in(ALICE, world_id=A)

    for _ in range(3):
        feed = client.get("/cards")
        assert feed.status_code == 200, feed.text
        assert (B, card["id"]) in {(i["world_id"], i["card_id"]) for i in feed.json()["cards"]}
        listed = client.get(f"/worlds/{B}/cards")
        assert listed.status_code == 200, listed.text
        assert card["id"] in {c["id"] for c in listed.json()}
    assert wb.writer.parts == [] and wa.writer.parts == []
    assert wb.is_open(card)
    assert store.events == {} and store.pending_events == {}

    assert outcome(post_answer(client, B, card["id"], "approve")) == (200, ANSWERED)
    [part] = wb.writer.parts
    assert part["type"] == "approval.resolved" and part["authz"]["by"] == "person" and part["authz"]["ref"] == ALICE


def test_S_06_xworld_one_answer_answers_one_card_in_one_world(client, store):
    """No auto-answer and no fan-out: the same gate waiting in A, B and C is answered only where the person answered."""
    wa, wb, wc = World(store, A, ALICE), World(store, B, ALICE), World(store, C, ALICE)
    ca, cb, cc = wa.add("gate"), wb.add("gate"), wc.add("gate")
    sign_in(ALICE, world_id=A)

    assert outcome(post_answer(client, B, cb["id"], "approve")) == (200, ANSWERED)

    assert len(wb.writer.parts) == 1
    assert wa.writer.parts == [] and wc.writer.parts == []
    assert wa.is_open(ca) and wc.is_open(cc) and not wb.is_open(cb)
    remaining = {(i["world_id"], i["card_id"]) for i in client.get("/cards").json()["cards"]}
    assert remaining == {(A, ca["id"]), (C, cc["id"])}


# --- 5. audit -----------------------------------------------------------------------------------------------------


def _audit_records(caplog, *values: str) -> list[logging.LogRecord]:
    return [
        r
        for r in caplog.records
        if r.name.startswith("tilo_api") and r.levelno >= logging.INFO and all(v in r.getMessage() for v in values)
    ]


@pytest.mark.parametrize(
    ("kind", "option"),
    [("gate", "approve"), ("gate", "hold"), ("needs_you", "per_pack"), ("consent", "connect"), ("meeting", "even")],
)
def test_S_06_xworld_every_cross_world_answer_is_logged_with_actor_session_world_target_card_and_option(
    client, store, caplog, kind, option
):
    """BQ-XWORLD-5: an application log record (INFO or above, a `tilo_api.*` logger) names the actor's user id, the
    session's world, the target world, the card and the option, also for a gate hold that writes no event."""
    caplog.set_level(logging.INFO, logger="tilo_api")
    _, _, card = two_worlds(store, kind)
    sign_in(ALICE, world_id=A)

    assert outcome(post_answer(client, B, card["id"], option)) == (200, ANSWERED)

    assert _audit_records(caplog, ALICE, A, B, card["id"], option), [r.getMessage() for r in caplog.records]


def test_S_06_xworld_audit_log_names_the_target_world_when_the_session_names_none(client, store, caplog):
    caplog.set_level(logging.INFO, logger="tilo_api")
    _, _, card = two_worlds(store, "gate")
    sign_in(ALICE, world_id=None)

    assert outcome(post_answer(client, B, card["id"], "approve")) == (200, ANSWERED)

    assert _audit_records(caplog, ALICE, B, card["id"], "approve"), [r.getMessage() for r in caplog.records]


def test_S_06_xworld_logs_carry_no_token_cookie_or_card_text(client, store, caplog):
    """No secret or token in any log record (root CLAUDE.md), and ids only: no card text (BQ-XWORLD-5)."""
    caplog.set_level(logging.DEBUG)
    token = "tok_" + secrets.token_hex(16)  # a fake bearer, assembled at runtime
    marker = "card-text-" + secrets.token_hex(6)
    World(store, A, ALICE)
    wb = World(store, B, ALICE)
    card = wb.add("gate", what_happened=f"Reply drafted {marker}")
    sign_in(ALICE, world_id=A)

    response = client.post(
        f"/worlds/{B}/cards/{card['id']}/answer",
        json={"option": "approve", "channel": "web"},
        headers={"Authorization": f"Bearer {token}", "Cookie": f"session={token}"},
    )

    assert outcome(response) == (200, ANSWERED)
    for record in caplog.records:
        rendered = record.getMessage() + repr(vars(record))
        assert token not in rendered, record.name
        assert marker not in rendered, record.name


# --- 6. per-world reads -------------------------------------------------------------------------------------------


@pytest.mark.parametrize("channel", ["web", "mobile_web", "email"])
def test_S_06_xworld_owner_reads_another_owned_worlds_cards_exactly_as_the_feed_shows_them(client, store, channel):
    """BQ-XWORLD-6: `GET /worlds/{B}/cards` opens for the owner cross-world, matching `GET /cards` (which has no channel
    rule) and what a session bound to B sees; reading writes nothing."""
    World(store, A, ALICE).add("needs_you", seed="a")
    wb = World(store, B, ALICE)
    for n, kind in enumerate(KINDS):
        wb.add(kind, seed=str(n))
    sign_in(ALICE, world_id=B, channel=channel)
    reference = client.get(f"/worlds/{B}/cards")
    assert reference.status_code == 200 and len(reference.json()) == len(KINDS)
    sign_in(ALICE, world_id=A, channel=channel)

    cross = client.get(f"/worlds/{B}/cards")

    assert cross.status_code == 200, cross.text
    assert cross.json() == reference.json()
    assert cross.json() == [i["card"] for i in client.get("/cards").json()["cards"] if i["world_id"] == B]
    assert wb.writer.parts == []


def test_S_06_xworld_per_world_read_of_another_owners_world_is_the_unknown_world_404(client, store):
    World(store, A, ALICE)
    World(store, D, BOB).add("gate")
    sign_in(ALICE, world_id=A)

    mine_not = client.get(f"/worlds/{D}/cards")
    ghost = client.get(f"/worlds/{GHOST}/cards")

    assert mine_not.status_code == ghost.status_code == 404
    assert mine_not.json() == ghost.json()


# --- 7. no regression: one scope for the feed, the worlds list and answering --------------------------------------


def test_S_06_xworld_answerable_worlds_are_exactly_the_worlds_list_and_the_feed_scope(client, store):
    """BQ-XWORLD-7 with BQ-S14-1 and BQ-S06-1: an owner answers in exactly the worlds `GET /worlds` lists and
    `GET /cards` covers, whatever world their session names; anyone else only in the world their principal names."""
    worlds = {w: World(store, w, ALICE) for w in (A, B, C)} | {D: World(store, D, BOB)}
    owner_cards = {w: wd.add("needs_you", seed="o") for w, wd in worlds.items()}
    cara_cards = {w: wd.add("gate", seed="c", assignee=CARA) for w, wd in worlds.items()}

    sign_in(ALICE, world_id=A)
    listed = {w["world_id"] for w in client.get("/worlds", params={"limit": 100}).json()["worlds"]}
    fed = {i["world_id"] for i in client.get("/cards", params={"limit": 100}).json()["cards"]}
    answerable = {w for w, c in owner_cards.items() if post_answer(client, w, c["id"], "per_kwh").status_code == 200}
    assert listed == fed == answerable == {A, B, C}

    sign_in(CARA, role="approver", world_id=B)
    listed = {w["world_id"] for w in client.get("/worlds", params={"limit": 100}).json()["worlds"]}
    fed = {i["world_id"] for i in client.get("/cards", params={"limit": 100}).json()["cards"]}
    answerable = {w for w, c in cara_cards.items() if post_answer(client, w, c["id"], "approve").status_code == 200}
    assert listed == fed == answerable == {B}


# --- property: only the owner's own web session answers cross-world, and only a person authorises -----------------

_MODES = [  # (principal channel, tilo-channels caller, claimed channel)
    ("web", False, "web"),
    ("mobile_web", False, "mobile_web"),
    ("email", True, "email"),
    ("email", False, "email"),
    ("web", True, "web"),
]


@settings(max_examples=60, deadline=None, suppress_health_check=[HealthCheck.function_scoped_fixture])
@given(
    user=st.sampled_from([ALICE, BOB]),
    role=st.sampled_from(["owner", "team_lead", "approver", "viewer"]),
    session_world=st.sampled_from([A, None, D]),
    record_owner=st.sampled_from([ALICE, BOB]),
    card_store_owner=st.sampled_from([ALICE, BOB]),
    kind=st.sampled_from(list(KINDS)),
    valid_option=st.booleans(),
    mode=st.sampled_from(_MODES),
)
def test_S_06_xworld_property_only_an_owners_own_web_session_answers_and_only_a_person_authorises(
    client, user, role, session_world, record_owner, card_store_owner, kind, valid_option, mode
):
    """For any caller in a world other than B: the answer lands only for role owner, in their own web or mobile_web
    session, when both the WorldRecord and the run's CardStore name them as B's owner; then every existing check
    decides as for a bound session, and every authorisation written is that person's. Anything else is the
    unknown-world 404 and writes nothing (FR-HIL-04: no T3 without a person)."""
    p_channel, from_channels, claimed = mode
    store = make_store()
    use(store)
    World(store, A, ALICE)
    World(store, D, BOB)
    wb = World(store, B, record_owner, card_store_owner=card_store_owner)
    card = wb.add(kind, district="D1", assignee=user if role == "approver" else None)
    sign_in(user, role=role, world_id=session_world, channel=p_channel, districts=("D1",), from_channels=from_channels)
    option = KINDS[kind][1] if valid_option else "not_an_option"

    response = outcome(post_answer(client, B, card["id"], option, claimed))

    eligible = (
        role == "owner"
        and user == record_owner == card_store_owner
        and p_channel in ("web", "mobile_web")
        and not from_channels
    )
    if not eligible:
        assert response == unknown_world(client, card["id"], option, claimed)
        assert wb.writer.parts == [] and wb.is_open(card)
    elif not valid_option:
        assert response == (400, {"outcome": "rejected", "reason": "invalid_option"})
        assert wb.writer.parts == [] and wb.is_open(card)
    elif claimed not in card["answer_channels"]:
        assert response == (400, {"outcome": "rejected", "reason": "invalid_channel"})
        assert wb.writer.parts == [] and wb.is_open(card)
    else:
        assert response == (200, ANSWERED)
        assert [p["type"] for p in wb.writer.parts] == [KINDS[kind][2]]
        assert not wb.is_open(card)
    for part in wb.writer.parts:
        if part.get("authz") is not None:
            assert part["authz"]["by"] == "person" and part["authz"]["ref"] == user
