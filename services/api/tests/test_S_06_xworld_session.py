"""S-06 cross-world reads and answers by session kind (ticket API-CARDS-XWORLD-2, PR #561's Opus security flags 1 and 2;
supervisor decisions 7 Oct; PRD 10.1, 10.3, FR-HIL-04 T3 never automated, SEC-06, SEC-07, SEC-08).

Two decisions, pinned in API_CARDS_XWORLD.md ("Session kind", "Redacted cross-world reads") and docs/open-questions.md
(BQ-XWORLD-9, BQ-XWORLD-10):

1. An owner session that is not a full web sign-in (an email session, a signed-link session, anything without the
   server-set `deps.Principal.full_session` marker) reads another owned world's cards only as a redacted summary
   (`_cards_lib.redacted_card_summary`): no gate action text, no recipients, no consent scopes, no destination. Full
   detail across worlds needs a full web sign-in. Reads in the session's own bound world are unchanged.
2. Answering across worlds needs that marker on top of every existing rule: a principal on channel "web" or
   "mobile_web" without it (a signed-link landing session) gets the unknown-world 404 cross-world, T3 gates included.
   Answers in the bound world are unchanged.

The marker is a field of the server-side `deps.Principal`, `full_session: bool = False`, set only by the server for a
full sign-in (in dev mode the dev principal is that session). Nothing in a request sets it. `deps.Principal` is not a
contract (nothing in contracts/ or packages/contracts-* defines it), so no contract change.

Through the public interface: the real `tilo_api.app` over the in-memory `Store` (`client`, `store` from conftest.py),
each world's cards in its run's real `CardStore` over a recording writer. No network, no model, no paid call; fake
tokens are assembled at runtime. Until the change lands, the marker does not exist (building a full-session principal
raises TypeError) and a session without it reads full cards and answers across worlds, so these tests fail on that.
"""

from __future__ import annotations

import dataclasses
import json
import secrets
import string
from types import SimpleNamespace

import pytest
from _api_lib import as_principal, make_principal, make_store, make_world
from _cards_lib import (
    REDACTED_SUMMARY_KEYS,
    FakeClock,
    clone_card,
    load_valid_card,
    new_ulid,
    redacted_card_summary,
)
from _cards_lib import FakeEventWriter as CardWriter
from fastapi import FastAPI, HTTPException
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st
from tilo_api import app, cards, deps, dev
from tilo_api.cards import CardStore

ALICE, BOB = "u_alice", "u_bob"
A, B, C = "w_alice_a", "w_alice_b", "w_alice_c"  # Alice's worlds
D = "w_bob_d"  # Bob's world
GHOST = "w_nobody_here"
START = "2026-09-29T09:30:00.000Z"
ANSWERED = {"outcome": "answered"}
WEBBY = ("web", "mobile_web")

KINDS = {  # kind -> (fixture, an option a person picks, the event it writes)
    "needs_you": ("needs_you_compare_basis", "per_kwh", "question.answered"),
    "gate": ("gate_send_reply", "approve", "approval.resolved"),  # T3, irreversible
    "consent": ("consent_drive_folder", "connect", "connection.consented"),
    "meeting": ("meeting_budget_split", "even", "question.answered"),
}
RISKY_KEYS = ("gate", "consent", "recipients", "scopes", "destination", "action", "exact", "options")


class World:
    """One seeded world: its record, its run's CardStore and that store's recording writer."""

    def __init__(self, store: deps.Store, world_id: str, owner: str, *, paused: bool = False) -> None:
        self.world_id = world_id
        self.clock, self.writer = FakeClock(START), CardWriter()
        self.cards = CardStore(clock=self.clock, writer=self.writer, world_owners={world_id: owner})
        store.worlds[world_id] = make_world(owner=owner, paused=paused)
        store.runs[world_id] = SimpleNamespace(cards=self.cards)  # what runs.get_card_store reads

    def add(self, kind: str = "gate", *, seed: str = "1", card: dict | None = None) -> dict:
        card = card or clone_card(load_valid_card(KINDS[kind][0]))
        card = clone_card(card, id_=new_ulid(f"{self.world_id}:{seed}"), created_at=START)
        card["world_id"] = self.world_id
        outbox = new_ulid(f"outbox:{self.world_id}:{seed}") if card["kind"] == "gate" else None
        result = self.cards.submit(card, outbox_id=outbox, merge=False)
        assert result.outcome == "accepted", result.errors
        return card

    def is_open(self, card: dict) -> bool:
        return self.cards.is_open(self.world_id, card["id"])


def full(principal: deps.Principal) -> deps.Principal:
    """The server-set full web sign-in marker (BQ-XWORLD-10). Strict: a TypeError until `deps.Principal` has it."""
    return dataclasses.replace(principal, full_session=True)


def sign_in(
    world_id: str | None = A,
    *,
    user: str = ALICE,
    role: str = "owner",
    channel: str = "web",
    full_session: bool = False,
    from_channels: bool = False,
) -> deps.Principal:
    """A principal as the server resolved it. `full_session=False` builds it with no marker at all (the field's own
    default), which is what a signed-link landing session or an email session is."""
    principal = make_principal(user_id=user, role=role, world_id=world_id, channel=channel)
    if full_session:
        principal = full(principal)
    as_principal(principal)
    app.dependency_overrides[cards.get_channels_caller] = lambda: from_channels
    return principal


def answer(client, world_id: str, card_id: str, option: str, channel: str = "web", **kwargs):
    return client.post(
        f"/worlds/{world_id}/cards/{card_id}/answer", json={"option": option, "channel": channel}, **kwargs
    )


def outcome(response) -> tuple[int, object]:
    return response.status_code, response.json()


def unknown_world(client, card_id: str, option: str = "approve", channel: str = "web") -> tuple[int, object]:
    response = answer(client, GHOST, card_id, option, channel)
    assert response.status_code == 404, response.text
    return outcome(response)


def seed_alice(store: deps.Store, kinds=tuple(KINDS)) -> tuple[World, World, list[dict]]:
    """Alice owns A (her bound world) and B; B holds one open card of each kind."""
    wa, wb = World(store, A, ALICE), World(store, B, ALICE)
    return wa, wb, [wb.add(kind, seed=str(n)) for n, kind in enumerate(kinds)]


def bound_read(client, world_id: str, channel: str = "web") -> list[dict]:
    """The reference: what a session bound to `world_id` reads there (today's behaviour, unchanged)."""
    sign_in(world_id, channel=channel)
    response = client.get(f"/worlds/{world_id}/cards")
    assert response.status_code == 200, response.text
    return response.json()


# --- the marker itself (BQ-XWORLD-10) -----------------------------------------------------------------------------


def test_S_06_xworld_principal_has_a_full_session_marker_that_defaults_to_false():
    """`deps.Principal.full_session: bool = False`: a principal built without it is not a full sign-in."""
    fields = {f.name: f for f in dataclasses.fields(deps.Principal)}
    assert "full_session" in fields, "deps.Principal needs the server-set full_session marker (BQ-XWORLD-10)"
    assert fields["full_session"].default is False
    assert deps.Principal(user_id=ALICE, role="owner").full_session is False
    assert deps.Principal(user_id=ALICE, role="owner", channel="mobile_web", world_id=A).full_session is False
    assert full(deps.Principal(user_id=ALICE, role="owner")).full_session is True


def test_S_06_xworld_the_dev_mode_principal_is_the_full_session(monkeypatch):
    """In dev mode the one dev owner is the person at the keyboard: a full web sign-in session (BQ-XWORLD-10)."""
    for name in ("LIVE", "K_SERVICE", "CLOUD_RUN_JOB"):
        monkeypatch.delenv(name, raising=False)
    dev_app = FastAPI()
    dev.install(dev_app, {})
    resolve = dev_app.dependency_overrides[deps.get_current_principal]

    for path_params in ({"world_id": A}, {}):
        principal = resolve(SimpleNamespace(path_params=path_params))
        assert principal.role == "owner"
        assert principal.full_session is True


def test_S_06_xworld_production_principal_seam_still_refuses_without_sign_in():
    """No sign-in is wired, so no request can mint any principal, let alone a full one: the seam is still 401."""
    with pytest.raises(HTTPException) as raised:
        deps.get_current_principal()
    assert raised.value.status_code == 401


@pytest.mark.parametrize("channel", WEBBY)
def test_S_06_xworld_the_marker_never_comes_from_the_request(client, store, channel):
    """A header, a query parameter, a cookie or a body field naming the marker changes nothing: the session without it
    still gets the unknown-world 404 cross-world and still reads only the redacted summary."""
    _, wb, [card] = seed_alice(store, ("gate",))
    sign_in(A, channel=channel)
    fake = "tok_" + secrets.token_hex(8)  # assembled at runtime, never a real token
    claims = {
        "headers": {
            "X-Tilo-Full-Session": "1",
            "X-Full-Session": "true",
            "Authorization": f"Bearer {fake}",
            "Cookie": f"full_session=1; session={fake}",
        },
        "params": {"full_session": "true"},
    }
    expected = unknown_world(client, card["id"], channel=channel)

    assert outcome(answer(client, B, card["id"], "approve", channel, **claims)) == expected
    smuggled = client.post(
        f"/worlds/{B}/cards/{card['id']}/answer",
        json={"option": "approve", "channel": channel, "full_session": True},
    )
    assert smuggled.status_code != 200, smuggled.text
    assert wb.writer.parts == [] and wb.is_open(card)

    read = client.get(f"/worlds/{B}/cards", **claims)
    assert read.status_code == 200, read.text
    assert read.json() == [redacted_card_summary(card)]


# --- cross-world answers need the marker (decision 2) -------------------------------------------------------------


@pytest.mark.parametrize("session_world", [A, None], ids=["session_names_A", "session_names_no_world"])
@pytest.mark.parametrize("channel", WEBBY)
@pytest.mark.parametrize("kind", list(KINDS))
def test_S_06_xworld_a_signed_link_style_web_session_never_answers_across_worlds(
    client, store, kind, channel, session_world
):
    """A test-built signed-link landing session: role owner, channel web or mobile_web, the owner of both worlds, no
    full-session marker. Cross-world it gets exactly the unknown-world 404, for every kind, the T3 gate included;
    nothing is written and the card stays open (FR-HIL-04: no T3 without a full sign-in person here)."""
    wa, wb, [card] = seed_alice(store, (kind,))
    if kind == "gate":
        assert card["gate"]["risk_tier"] == "T3"
    sign_in(session_world, channel=channel)
    option = KINDS[kind][1]
    expected = unknown_world(client, card["id"], option, channel)

    assert outcome(answer(client, B, card["id"], option, channel)) == expected
    assert wb.writer.parts == [] and wa.writer.parts == []
    assert wb.is_open(card)


@pytest.mark.parametrize("option", ["approve", "edit", "hold"])
def test_S_06_xworld_no_t3_gate_option_is_answered_cross_world_without_the_marker(client, store, option):
    """Every option of a T3 gate, including the ones that write nothing, is refused the same way."""
    _, wb, [card] = seed_alice(store, ("gate",))
    sign_in(None, channel="web")
    expected = unknown_world(client, card["id"], option)

    assert outcome(answer(client, B, card["id"], option)) == expected
    assert wb.writer.parts == [] and wb.is_open(card)


def test_S_06_xworld_a_paused_target_world_gives_a_session_without_the_marker_the_404_not_the_409(client, store):
    """The Pause-all guard runs only for a principal who may answer there, so a session without the marker learns
    nothing about the other world, not even that it is paused."""
    World(store, A, ALICE)
    wb = World(store, B, ALICE, paused=True)
    card = wb.add("gate")
    sign_in(A, channel="web")
    expected = unknown_world(client, card["id"])

    assert outcome(answer(client, B, card["id"], "approve")) == expected
    assert wb.writer.parts == []


def _answer_once(client, kind: str, *, session_world: str | None, full_session: bool, channel: str = "web") -> dict:
    """One answer to B's card in a fresh store; everything a person or the run could observe."""
    store = make_store()
    app.dependency_overrides[deps.get_store] = lambda: store
    wa, wb, [card] = seed_alice(store, (kind,))
    sign_in(session_world, channel=channel, full_session=full_session)
    response = answer(client, B, card["id"], KINDS[kind][1], channel)
    return {
        "response": outcome(response),
        "parts": wb.writer.parts,
        "open": wb.is_open(card),
        "a": wa.writer.parts,
        "events": store.events,
        "pending": store.pending_events,
    }


@pytest.mark.parametrize("channel", WEBBY)
@pytest.mark.parametrize("kind", list(KINDS))
def test_S_06_xworld_a_session_without_the_marker_still_answers_in_its_bound_world(client, kind, channel):
    """Bound-world answers are unchanged: the same outcome and events with or without the marker."""
    with_marker = _answer_once(client, kind, session_world=B, full_session=True, channel=channel)
    without = _answer_once(client, kind, session_world=B, full_session=False, channel=channel)

    assert without["response"] == (200, ANSWERED)
    assert without == with_marker


@pytest.mark.parametrize("session_world", [A, None], ids=["session_names_A", "session_names_no_world"])
@pytest.mark.parametrize("kind", list(KINDS))
def test_S_06_xworld_a_full_session_answers_across_worlds_exactly_as_a_bound_session(client, kind, session_world):
    """With the marker, a cross-world answer is still byte for byte the bound answer (BQ-XWORLD-3, BQ-XWORLD-4)."""
    bound = _answer_once(client, kind, session_world=B, full_session=True)
    cross = _answer_once(client, kind, session_world=session_world, full_session=True)

    assert bound["response"] == (200, ANSWERED)
    assert cross == bound


@pytest.mark.parametrize(
    ("label", "kwargs", "target"),
    [
        ("channels_caller", {"from_channels": True, "channel": "email"}, B),
        ("email_channel", {"channel": "email"}, B),
        ("web_channels_caller", {"from_channels": True, "channel": "web"}, B),
        ("approver", {"role": "approver"}, B),
        ("team_lead", {"role": "team_lead"}, B),
        ("another_owners_world", {}, D),
    ],
)
def test_S_06_xworld_the_marker_adds_to_every_existing_rule_and_replaces_none(client, store, label, kwargs, target):
    """The marker is required in addition to role owner, the user's own web or mobile_web session, no tilo-channels
    caller and both owner checks (BQ-XWORLD-1, BQ-XWORLD-2): each of those still refuses with the unknown-world 404."""
    World(store, A, ALICE)
    wb, wd = World(store, B, ALICE), World(store, D, BOB)
    card = (wd if target == D else wb).add("needs_you")
    claimed = "email" if kwargs.get("channel") == "email" else "web"
    sign_in(A, full_session=True, **kwargs)
    expected = unknown_world(client, card["id"], "per_kwh", claimed)

    assert outcome(answer(client, target, card["id"], "per_kwh", claimed)) == expected, label
    assert wb.writer.parts == [] and wd.writer.parts == []


# --- cross-world reads by a session without the marker are redacted (decision 1) ---------------------------------


@pytest.mark.parametrize("session_world", [A, None], ids=["session_names_A", "session_names_no_world"])
@pytest.mark.parametrize(
    ("channel", "from_channels"),
    [("email", False), ("email", True), ("web", False), ("mobile_web", False)],
    ids=["email", "email_channels_caller", "signed_link_web", "signed_link_mobile_web"],
)
def test_S_06_xworld_a_session_without_the_marker_reads_other_worlds_only_as_redacted_summaries(
    client, store, channel, from_channels, session_world
):
    """`GET /worlds/{B}/cards`: the same cards, in the same order, as the full view, each reduced to the summary
    allowlist; no gate action text, recipients, consent scopes, destination or options; nothing is written."""
    _, wb, seeded = seed_alice(store)
    reference = bound_read(client, B)
    assert {c["id"] for c in reference} == {c["id"] for c in seeded}
    sign_in(session_world, channel=channel, from_channels=from_channels)

    response = client.get(f"/worlds/{B}/cards")

    assert response.status_code == 200, response.text
    body = response.json()
    assert body == [redacted_card_summary(c) for c in reference]
    for item in body:
        assert set(item) == REDACTED_SUMMARY_KEYS
        assert item["redacted"] is True
        assert not set(item) & set(RISKY_KEYS)
    gate = next(c for c in seeded if c["kind"] == "gate")
    assert next(i for i in body if i["id"] == gate["id"])["risk_tier"] == "T3"
    text = response.text
    assert gate["gate"]["action"]["exact"] not in text
    assert gate["gate"]["action"]["destination"] not in text
    assert all(r not in text for r in gate["gate"]["recipients"])
    consent = next(c for c in seeded if c["kind"] == "consent")
    assert all(s not in text for s in consent["consent"]["scopes"])
    assert wb.writer.parts == []


@pytest.mark.parametrize("channel", ["email", "web", "mobile_web"])
def test_S_06_xworld_a_session_without_the_marker_reads_its_bound_world_in_full(client, store, channel):
    """Reads in the session's own bound world are unchanged: the full cards, risky-action detail included."""
    _, _, seeded = seed_alice(store)
    sign_in(B, channel=channel)

    response = client.get(f"/worlds/{B}/cards")

    assert response.status_code == 200, response.text
    assert {c["id"] for c in response.json()} == {c["id"] for c in seeded}
    gate = next(c for c in response.json() if c["kind"] == "gate")
    assert gate["gate"]["action"]["exact"] and gate["gate"]["recipients"]
    assert "redacted" not in gate


@pytest.mark.parametrize("session_world", [A, None], ids=["session_names_A", "session_names_no_world"])
@pytest.mark.parametrize("channel", WEBBY)
def test_S_06_xworld_a_full_session_owner_still_gets_the_full_card_across_worlds(client, store, channel, session_world):
    """Regression: with the marker, the cross-world read is byte for byte the bound session's, exactly as before."""
    seed_alice(store)
    reference = bound_read(client, B, channel)
    sign_in(session_world, channel=channel, full_session=True)

    response = client.get(f"/worlds/{B}/cards")

    assert response.status_code == 200, response.text
    assert response.json() == reference
    gate = next(c for c in response.json() if c["kind"] == "gate")
    assert gate["gate"]["action"]["exact"] and gate["gate"]["recipients"] and gate["gate"]["action"]["destination"]


def test_S_06_xworld_the_feed_shows_a_session_without_the_marker_summaries_for_other_worlds(client, store):
    """`GET /cards` mirrors the per-world route for the same principal (BQ-S06-2): the bound world's cards in full,
    every other owned world's as the redacted summary; worlds, ids, order, count and paging are unchanged."""
    wa, wb, seeded = seed_alice(store, ("gate", "consent"))
    mine = wa.add("gate", seed="a")
    wc = World(store, C, ALICE)
    other = wc.add("needs_you", seed="c")
    references = {w: bound_read(client, w) for w in (A, B, C)}
    sign_in(A, channel="web")

    feed = client.get("/cards", params={"limit": 100})

    assert feed.status_code == 200, feed.text
    body = feed.json()
    assert body["count"] == len(body["cards"]) == 4
    by_world: dict[str, list[dict]] = {}
    for item in body["cards"]:
        by_world.setdefault(item["world_id"], []).append(item["card"])
    assert by_world[A] == references[A] and by_world[A][0]["id"] == mine["id"]  # bound: full
    assert by_world[B] == [redacted_card_summary(c) for c in references[B]]
    assert by_world[C] == [redacted_card_summary(c) for c in references[C]] == [redacted_card_summary(other)]
    for world_id in (B, C):
        per_world = client.get(f"/worlds/{world_id}/cards")
        assert per_world.status_code == 200 and per_world.json() == by_world[world_id]
    assert all(r not in feed.text for c in seeded if c["kind"] == "gate" for r in c["gate"]["recipients"])


def test_S_06_xworld_a_full_session_feed_is_unchanged(client, store):
    """Regression: with the marker every owned world's feed items are the full cards, as before."""
    seed_alice(store, ("gate", "consent"))
    references = {w: bound_read(client, w) for w in (A, B)}
    sign_in(A, channel="web", full_session=True)

    body = client.get("/cards", params={"limit": 100}).json()

    assert [i["card"] for i in body["cards"] if i["world_id"] == B] == references[B]


@pytest.mark.parametrize("channel", ["email", "web"])
def test_S_06_xworld_a_redacted_read_of_another_owners_world_is_still_the_unknown_world_404(client, store, channel):
    """Redaction never opens a world: Bob's world is the same 404 as a world that does not exist."""
    World(store, A, ALICE)
    World(store, D, BOB).add("gate")
    sign_in(A, channel=channel)

    mine_not, ghost = client.get(f"/worlds/{D}/cards"), client.get(f"/worlds/{GHOST}/cards")

    assert mine_not.status_code == ghost.status_code == 404
    assert mine_not.json() == ghost.json()


# --- property: the summary never carries risky-action detail ------------------------------------------------------

_MARK = st.text(alphabet=string.ascii_lowercase + string.digits, min_size=8, max_size=16).map(lambda s: "zq" + s)


@settings(max_examples=40, deadline=None, suppress_health_check=[HealthCheck.function_scoped_fixture])
@given(
    exact=_MARK,
    destination=_MARK,
    recipients=st.lists(_MARK, min_size=1, max_size=4, unique=True),
    scopes=st.lists(_MARK, min_size=1, max_size=3, unique=True),
    channel=st.sampled_from(["email", "web", "mobile_web"]),
    from_channels=st.booleans(),
    session_world=st.sampled_from([A, None]),
)
def test_S_06_xworld_property_a_redacted_summary_never_contains_action_text_recipients_scopes_or_destination(
    client, exact, destination, recipients, scopes, channel, from_channels, session_world
):
    """For any gate action text, destination, recipients and consent scopes, and any owner session without the marker,
    neither `GET /worlds/{B}/cards` nor `GET /cards` serves any of them for world B, and each item is exactly the
    summary allowlist."""
    store = make_store()
    app.dependency_overrides[deps.get_store] = lambda: store
    World(store, A, ALICE)
    wb = World(store, B, ALICE)
    gate = clone_card(load_valid_card(KINDS["gate"][0]))
    gate["gate"]["action"]["exact"] = f"Send it {exact}"
    gate["gate"]["action"]["destination"] = destination
    gate["gate"]["recipients"] = [f"{r}@example.com" for r in recipients]
    consent = clone_card(load_valid_card(KINDS["consent"][0]))
    consent["consent"]["scopes"] = [f"Scope {s}" for s in scopes]
    gate, consent = wb.add(card=gate, seed="g"), wb.add(card=consent, seed="c")
    markers = [exact, destination, *recipients, *scopes]
    sign_in(session_world, channel=channel, from_channels=from_channels)

    per_world = client.get(f"/worlds/{B}/cards")
    feed = client.get("/cards", params={"limit": 100})

    assert per_world.status_code == 200 and feed.status_code == 200, (per_world.text, feed.text)
    served = per_world.json() + [i["card"] for i in feed.json()["cards"] if i["world_id"] == B]
    assert len(served) == 4
    for item in served:
        assert set(item) == REDACTED_SUMMARY_KEYS and item["redacted"] is True
    rendered = json.dumps(served) + per_world.text + feed.text
    for marker in markers:
        assert marker not in rendered
    assert wb.writer.parts == [] and wb.is_open(gate) and wb.is_open(consent)
