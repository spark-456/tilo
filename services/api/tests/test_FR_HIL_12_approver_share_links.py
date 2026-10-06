"""FR-HIL-12 (PRD 10.1 roles, 10.3, 16.2, SEC-06; BQ-32; ADR-0006), API and security level.

Acceptance: "An Approver answers a gate from a shared link after sign-in."

Tested with no browser and no dev server: a `CardStore` over the injected fake clock and a recording event writer,
behind `cards.build_router(store)` and the new `tilo_api.sharing.build_router(store)`, with
`deps.get_current_principal` overridden (no override = no sign-in = the production 401). The HTTP shapes this file
pins are in `API_FR_HIL_12.md`; the PRD gives the behaviour, not the routes, so those shapes are the ticket's
defaults (listed in the report). Nothing here needs a contract change except what `API_FR_HIL_12.md` lists as a gap.

What the PRD and contracts fix, and what each test below checks (never invented):
- BQ-32 / ADR-0006: sharing a gate with an Approver after it is raised re-raises it as a NEW proposal with a new card;
  `approval.requested` then names `approver = {user, assigned_by: {by, at}}`, `by` the world's owner taken from the
  signed-in owner (never the request body), `at` the API clock; an Approver counts only when `assigned_by.by` is the
  owner and `assigned_by.at` is no later than the answer.
- PRD 10.3 / 16.2: gates need sign-in; a link alone never answers. SEC-08: forged or replayed requests rejected.
- OB-01 / PI-02: only `approve` on that gate opens it, from a person who may open it; `tilo_policy.open_gate` decides,
  a model never authorises, and T3 still needs a person.

Default chosen where the PRD is silent (PRD 10.1 "assigned gates"): a share link is for one gate, one Approver, one
answer; its lifetime is the server's (`expires_at` in the response), so the tests move the fake clock relative to that
value and never assert a number of hours.
"""

from __future__ import annotations

import datetime as dt
import json
import re
import string
from collections.abc import Callable
from typing import Any

import jsonschema
import pytest
from _cards_lib import (
    FakeClock,
    FakeEventWriter,
    add_seconds,
    build_registry,
    load_valid_card,
    new_ulid,
    principal,
)
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st
from tilo_api import cards, deps
from tilo_api.cards import CardStore

START = "2026-10-06T09:00:00.000Z"
W = "w_01"
OWNER, APPROVER, OTHER, LEAD, VIEWER = "u_owner", "u_approver", "u_other_approver", "u_lead", "u_viewer"
OWNER_P = principal("owner", OWNER, W)
APPROVER_P = principal("approver", APPROVER, W)
OTHER_P = principal("approver", OTHER, W)
LEAD_P = principal("team_lead", LEAD, W, districts=("D1",))
VIEWER_P = principal("viewer", VIEWER, W)
ULID = re.compile(r"^[0-7][0-9A-HJKMNP-TV-Z]{25}$")
TS_FMT = "%Y-%m-%dT%H:%M:%S.%fZ"
REFUSED = (403, 404)  # refused without telling the caller whether the gate or link exists (404 is the cards pattern)
GONE = (404, 410)  # an expired or revoked link


def sharing():
    import tilo_api.sharing as module  # noqa: PLC0415  (missing until FR-HIL-12 ships: each test fails here)

    return module


def _ts(value: str) -> dt.datetime:
    return dt.datetime.strptime(value, TS_FMT).replace(tzinfo=dt.UTC)


_REGISTRY = build_registry()


def schema_errors(name: str, instance: Any) -> list[str]:
    """Errors against contracts/events/data/<name>.schema.json (shapes come straight from the contract)."""
    from _cards_lib import contracts_dir, load_json  # noqa: PLC0415

    schema = load_json(contracts_dir() / "events" / "data" / f"{name}.schema.json")
    cls = jsonschema.validators.validator_for(schema, default=jsonschema.Draft202012Validator)
    return [e.message for e in cls(schema, registry=_REGISTRY).iter_errors(instance)]


class World:
    """One world: the owner's gate (the `gate_send_reply` fixture, T3, irreversible) waiting in a CardStore, a fake
    clock, a recording writer, and a client whose signed-in person is whoever `as_` last set (None: signed out)."""

    def __init__(self, *, second_gate: bool = False) -> None:
        self.clock, self.writer = FakeClock(START), FakeEventWriter()
        self.store = CardStore(clock=self.clock, writer=self.writer, world_owners={W: OWNER})
        self.card = load_valid_card("gate_send_reply")
        self.outbox_id = new_ulid("ob-original")
        assert self.store.submit(self.card, outbox_id=self.outbox_id).outcome == "accepted"
        self.other_card = None
        if second_gate:
            self.other_card = {**load_valid_card("gate_send_reply"), "id": new_ulid("g2")}
            self.other_card["gate"] = {**self.card["gate"], "id": "G2"}
            assert self.store.submit(self.other_card, outbox_id=new_ulid("ob-2")).outcome == "accepted"
        self.who = None
        self._http: TestClient | None = None

    @property
    def http(self) -> TestClient:
        """Built on first use, so a missing `tilo_api.sharing` fails the test body, not its setup."""
        if self._http is None:
            app = FastAPI()
            app.include_router(cards.build_router(self.store))
            app.include_router(sharing().build_router(self.store))
            app.dependency_overrides[deps.get_current_principal] = self._principal
            self._http = TestClient(app)
        return self._http

    def _principal(self):
        if self.who is None:
            raise HTTPException(status_code=401, detail="Sign in to use this.")  # what production does unsigned
        return self.who

    def as_(self, who) -> TestClient:
        self.who = who
        return self.http

    # -- the routes this ticket pins (API_FR_HIL_12.md) --------------------------------------------------------
    def share(self, who=OWNER_P, *, approver: str = APPROVER, card_id: str | None = None, body: dict | None = None):
        payload = {"approver": approver} if body is None else body
        return self.as_(who).post(f"/worlds/{W}/cards/{card_id or self.card['id']}/share", json=payload)

    def shared(self, *, approver: str = APPROVER) -> dict:
        response = self.share(approver=approver)
        assert response.status_code == 201, response.text
        return response.json()

    def open(self, who, token: str):
        return self.as_(who).get(f"/share/{token}")

    def answer(self, who, token: str, option: str = "approve", **extra: Any):
        return self.as_(who).post(f"/share/{token}/answer", json={"option": option, **extra})

    def revoke(self, who, share_id: str):
        return self.as_(who).delete(f"/worlds/{W}/shares/{share_id}")

    # -- what was written -----------------------------------------------------------------------------------
    def of(self, type_: str) -> list[dict]:
        return self.writer.of_type(type_)

    def nothing_written(self) -> bool:
        return not self.writer.parts


@pytest.fixture()
def world() -> World:
    return World()


# --- owner creates a share link for one gate naming an Approver ---------------------------------------------------


def test_FR_HIL_12_the_owner_shares_one_gate_with_a_named_approver_as_a_new_proposal(world):
    response = world.share()

    assert response.status_code == 201, response.text
    body = response.json()
    assert set(body) >= {"share_id", "token", "card_id", "expires_at"}
    assert isinstance(body["token"], str) and len(body["token"]) >= 32  # a bearer secret, not a guessable counter
    assert ULID.match(body["card_id"]) and body["card_id"] != world.card["id"]  # re-raised: a new card (ADR-0006)
    assert _ts(body["expires_at"]) > _ts(world.clock.now())
    new_card = world.store.get(W, body["card_id"])
    assert new_card is not None and new_card["kind"] == "gate"
    for kept in ("irreversible", "risk_tier", "recipients"):  # sharing never lowers the tier or changes the send
        assert new_card["gate"][kept] == world.card["gate"][kept]
    assert new_card["gate"]["action"]["item"] == world.card["gate"]["action"]["item"]  # CR-12: the same pinned item


def test_FR_HIL_12_the_new_proposal_names_the_owners_assignment_in_approval_requested(world):
    share = world.shared()

    (requested,) = world.of("approval.requested")  # exactly one proposal; nothing else is raised or authorised
    data = requested["data"]
    assert schema_errors("approval.requested", data) == []
    assert requested["authz"] is None  # a proposal never authorises (EV-05)
    assert requested["world_id"] == W
    assert data["card_id"] == share["card_id"] and data["gate_id"] == world.card["gate"]["id"]
    assert data["approver"] == {"user": APPROVER, "assigned_by": {"by": OWNER, "at": world.clock.now()}}
    assert data["team_lead"] is None  # sharing with an Approver grants a Team Lead nothing
    assert (data["action_type"], data["risk_tier"], data["irreversible"]) == ("send_email", "T3", True)
    assert data["item"] == world.card["gate"]["action"]["item"]
    assert ULID.match(data["outbox_id"]) and data["outbox_id"] != world.outbox_id  # a fresh reservation (BQ-32)
    assert world.of("approval.resolved") == []


def test_FR_HIL_12_the_original_gate_is_not_reopened_to_the_approver(world):
    world.shared()

    assert world.store.list_for_world(W, principal=APPROVER_P) == [world.store.get(W, _only_new(world))]
    refused = world.as_(APPROVER_P).post(
        f"/worlds/{W}/cards/{world.card['id']}/answer", json={"option": "approve"}
    )  # the first card never named them: assignment after the gate is raised needs the new proposal
    assert refused.status_code == 404 and refused.json() == {"outcome": "rejected", "reason": "card_not_found"}
    assert world.of("approval.resolved") == []


def _only_new(world: World) -> str:
    (requested,) = world.of("approval.requested")
    return requested["data"]["card_id"]


def test_FR_HIL_12_the_assigner_comes_from_the_signed_in_owner_never_the_request_body(world):
    for body in (
        {"approver": APPROVER, "assigned_by": {"by": LEAD, "at": START}},
        {"approver": APPROVER, "by": LEAD},
        {"approver": APPROVER, "authz": {"by": "person", "ref": OWNER, "at": START}},
        {"approver": APPROVER, "outbox_id": new_ulid("chosen")},
        {"user": APPROVER},
    ):
        response = world.share(body=body)
        assert response.status_code == 422, (body, response.text)
    assert world.share(approver="not a user id").status_code == 422
    assert world.share(body={}).status_code == 422
    assert world.nothing_written()


@pytest.mark.parametrize("who", [LEAD_P, APPROVER_P, OTHER_P, VIEWER_P, principal("owner", OWNER, "w_other")])
def test_FR_HIL_12_only_the_world_owner_creates_a_share_link(world, who):
    named_self = world.share(who, approver=who.user_id)  # a Team Lead or Approver naming themself (BQ-32)
    named_other = world.share(who, approver=OTHER)

    assert named_self.status_code in REFUSED and named_other.status_code in REFUSED
    assert world.nothing_written()
    assert world.store.list_for_world(W, principal=principal("approver", who.user_id, W)) == []  # opens nothing
    assert (
        world.as_(principal("approver", who.user_id, W))
        .post(f"/worlds/{W}/cards/{world.card['id']}/answer", json={"option": "approve"})
        .status_code
        in REFUSED
    )


def test_FR_HIL_12_creating_a_share_link_needs_sign_in(world):
    assert world.share(None).status_code == 401
    assert world.nothing_written()


def test_FR_HIL_12_a_resolved_or_unknown_gate_cannot_be_shared(world):
    world.as_(OWNER_P).post(f"/worlds/{W}/cards/{world.card['id']}/answer", json={"option": "approve"})
    before = len(world.writer.parts)

    assert world.share().status_code in (400, 404, 409)  # already answered: nothing left to assign
    assert world.share(card_id=new_ulid("unknown")).status_code == 404
    assert len(world.writer.parts) == before


def test_FR_HIL_12_a_question_card_is_not_a_gate_to_share(world):
    question = load_valid_card("needs_you_blocked")
    assert world.store.submit(question).outcome == "accepted"

    assert world.share(card_id=question["id"]).status_code in (400, 404, 409)  # FR-HIL-12 is about gates
    assert world.of("approval.requested") == []


# --- the link alone cannot answer ------------------------------------------------------------------------------


def test_FR_HIL_12_the_link_alone_without_sign_in_cannot_open_or_answer(world):
    token = world.shared()["token"]
    world.writer.parts.clear()

    opened, answered = world.open(None, token), world.answer(None, token)

    assert opened.status_code == 401 and answered.status_code == 401
    assert world.card["what_happened"] not in opened.text + answered.text  # no card content before sign-in
    assert world.nothing_written()
    assert world.store.get(W, _only_new_from(world, token)) is not None  # still open for a person to answer


def _only_new_from(world: World, token: str) -> str:
    return world.open(APPROVER_P, token).json()["card"]["id"]


# no dots in the alphabet: "." and ".." are not path segments
@given(
    token=st.text(alphabet=string.ascii_letters + string.digits + "-_", min_size=1, max_size=120),
    option=st.sampled_from(["approve", "edit", "hold", "bogus", ""]),
)
@settings(max_examples=40, deadline=None, suppress_health_check=[HealthCheck.function_scoped_fixture])
def test_FR_HIL_12_property_no_token_ever_answers_without_sign_in(token, option):
    world = World()
    real = world.shared()["token"]
    world.writer.parts.clear()

    for tok in (token, real):
        assert world.open(None, tok).status_code == 401  # sign-in first: not even a token oracle
        assert world.answer(None, tok, option).status_code == 401
    assert world.nothing_written()


# --- who may open it after sign-in -----------------------------------------------------------------------------


@pytest.mark.parametrize(
    "who",
    [
        OTHER_P,  # another Approver
        LEAD_P,  # a Team Lead (the console is for questions; gates need the policy and a record)
        VIEWER_P,
        principal("approver", APPROVER, "w_02"),  # the named user, signed in to another world
        principal("approver", APPROVER, None),
    ],
)
def test_FR_HIL_12_a_signed_in_user_who_is_not_the_named_approver_gets_nothing_and_learns_nothing(world, who):
    token = world.shared()["token"]
    world.writer.parts.clear()
    garbage = "x" * len(token)

    opened, answered = world.open(who, token), world.answer(who, token)

    assert opened.status_code == 404 and answered.status_code == 404
    unknown = (world.open(who, garbage), world.answer(who, garbage))
    assert (opened.status_code, opened.json()) == (unknown[0].status_code, unknown[0].json())  # no existence leak
    assert (answered.status_code, answered.json()) == (unknown[1].status_code, unknown[1].json())
    assert world.nothing_written()


def test_FR_HIL_12_the_named_approver_signed_in_opens_the_gate_and_sees_only_that_gate():
    world = World(second_gate=True)
    share = world.shared()

    opened = world.open(APPROVER_P, share["token"])

    assert opened.status_code == 200, opened.text
    card = opened.json()["card"]
    assert card["id"] == share["card_id"] and card["kind"] == "gate"
    assert {o["id"] for o in card["options"]} == {"approve", "edit", "hold"}
    listed = world.as_(APPROVER_P).get(f"/worlds/{W}/cards")
    assert [c["id"] for c in listed.json()] == [share["card_id"]]  # the other gate of the world stays unseen
    assert world.as_(OTHER_P).get(f"/worlds/{W}/cards").json() == []
    other = world.as_(APPROVER_P).post(f"/worlds/{W}/cards/{world.other_card['id']}/answer", json={"option": "approve"})
    assert other.status_code == 404  # the link names one gate (PRD 10.1: assigned gates)


# --- the named Approver answers once ---------------------------------------------------------------------------


def test_FR_HIL_12_the_named_approver_answers_once_and_the_policy_engine_opens_the_gate(world):
    import tilo_policy  # noqa: PLC0415

    token = world.shared()["token"]
    world.clock.advance(30)

    response = world.answer(APPROVER_P, token)

    assert (response.status_code, response.json()) == (200, {"outcome": "answered"})
    (requested,), (resolved,) = world.of("approval.requested"), world.of("approval.resolved")
    data = resolved["data"]
    assert schema_errors("approval.resolved", data) == []
    assert data == {
        "gate_id": requested["data"]["gate_id"],
        "card_id": requested["data"]["card_id"],
        "outbox_id": requested["data"]["outbox_id"],
        "option": "approve",
        "channel": "web",  # gates need sign-in: a web session, never email or a bare link (PRD 10.3)
        "pin_verified": False,
    }
    assert resolved["authz"] == {"by": "person", "ref": APPROVER, "at": world.clock.now()}
    decision = tilo_policy.open_gate(requested, resolved, world_owner=OWNER)
    assert decision.outcome == "run" and decision.authz == resolved["authz"]  # the engine decides; the authz is theirs
    assert _only_new(world) not in [c["id"] for c in world.store.list_for_world(W, principal=OWNER_P)]  # it closed


def test_FR_HIL_12_a_second_answer_on_the_same_link_is_refused_and_writes_nothing(world):
    token = world.shared()["token"]
    assert world.answer(APPROVER_P, token).status_code == 200

    again = world.answer(APPROVER_P, token)
    other_option = world.answer(APPROVER_P, token, "hold")
    from_owner = world.as_(OWNER_P).post(f"/worlds/{W}/cards/{_only_new(world)}/answer", json={"option": "approve"})

    for response in (again, other_option, from_owner):
        assert response.status_code == 400 and response.json() == {"outcome": "rejected", "reason": "already_resolved"}
    assert len(world.of("approval.resolved")) == 1  # first answer wins; a replay is not a second authorisation


def test_FR_HIL_12_edit_and_hold_open_nothing_and_leave_the_link_usable(world):
    token = world.shared()["token"]
    before = len(world.writer.parts)

    for option in ("hold", "edit"):
        assert world.answer(APPROVER_P, option=option, token=token).status_code == 200  # CR-07: writes nothing
    assert len(world.writer.parts) == before and world.of("approval.resolved") == []
    assert world.answer(APPROVER_P, token, "bogus").status_code == 400  # an option the card does not offer
    assert world.answer(APPROVER_P, token).status_code == 200
    assert len(world.of("approval.resolved")) == 1


@pytest.mark.parametrize(
    "extra",
    [
        {"channel": "email"},
        {"channel": "whatsapp"},
        {"pin_verified": True},
        {"user": OWNER},
        {"authz": {"by": "policy", "ref": "p_any", "at": START}},
        {"by": "team_lead"},
    ],
)
def test_FR_HIL_12_the_answer_carries_no_identity_channel_or_pin_from_the_body(world, extra):
    token = world.shared()["token"]
    world.writer.parts.clear()

    response = world.answer(APPROVER_P, token, **extra)

    assert response.status_code in (403, 422)  # who and where come from the session (SEC-06, ADR-0019)
    assert world.nothing_written()


# --- expired and revoked links ---------------------------------------------------------------------------------


def test_FR_HIL_12_a_link_works_until_it_expires_and_not_after(world):
    share = world.shared()
    world.clock.set(add_seconds(share["expires_at"], -1))
    assert world.open(APPROVER_P, share["token"]).status_code == 200

    world.clock.set(add_seconds(share["expires_at"], 1))
    world.writer.parts.clear()

    assert world.open(APPROVER_P, share["token"]).status_code in GONE
    assert world.answer(APPROVER_P, share["token"]).status_code in GONE
    assert world.nothing_written()


def test_FR_HIL_12_an_expired_link_leaves_the_gate_for_the_owner(world):
    share = world.shared()
    world.clock.set(add_seconds(share["expires_at"], 1))
    assert world.answer(APPROVER_P, share["token"]).status_code in GONE

    owner = world.as_(OWNER_P).post(f"/worlds/{W}/cards/{share['card_id']}/answer", json={"option": "approve"})

    assert owner.status_code == 200  # the gate never timed out to go (PRD 10.3); the owner still opens it
    assert [p["authz"]["ref"] for p in world.of("approval.resolved")] == [OWNER]


def test_FR_HIL_12_a_revoked_link_is_refused_and_the_owner_keeps_the_gate(world):
    share = world.shared()
    assert world.open(APPROVER_P, share["token"]).status_code == 200

    revoked = world.revoke(OWNER_P, share["share_id"])

    assert revoked.status_code == 204
    world.writer.parts.clear()
    assert world.open(APPROVER_P, share["token"]).status_code in GONE
    assert world.answer(APPROVER_P, share["token"]).status_code in GONE
    assert world.as_(APPROVER_P).get(f"/worlds/{W}/cards").json() == []  # the assignment ends with the link
    assert (
        world.as_(APPROVER_P)
        .post(f"/worlds/{W}/cards/{share['card_id']}/answer", json={"option": "approve"})
        .status_code
        in REFUSED
    )
    assert world.nothing_written()
    owner = world.as_(OWNER_P).post(f"/worlds/{W}/cards/{share['card_id']}/answer", json={"option": "approve"})
    assert owner.status_code == 200


@pytest.mark.parametrize("who", [APPROVER_P, OTHER_P, LEAD_P, VIEWER_P, None])
def test_FR_HIL_12_only_the_owner_revokes_a_link(world, who):
    share = world.shared()

    response = world.revoke(who, share["share_id"])

    assert response.status_code in (*REFUSED, 401)
    assert world.open(APPROVER_P, share["token"]).status_code == 200  # still live


# --- an assignment the owner did not make, or made after the answer, opens nothing -------------------------------


def test_FR_HIL_12_an_answer_stamped_before_the_owners_assignment_opens_nothing(world):
    token = world.shared()["token"]
    world.clock.set(add_seconds(START, -60))  # a skewed clock: the answer would carry an `at` before assigned_by.at

    response = world.answer(APPROVER_P, token)

    assert response.status_code in (400, 403, 404, 409)  # BQ-32: assigned_by.at must be no later than the answer
    assert world.of("approval.resolved") == []


def test_FR_HIL_12_tampered_assignments_open_nothing_in_the_policy_engine(world):
    import copy  # noqa: PLC0415

    import tilo_policy  # noqa: PLC0415

    token = world.shared()["token"]
    world.clock.advance(30)
    assert world.answer(APPROVER_P, token).status_code == 200
    (requested,), (resolved,) = world.of("approval.requested"), world.of("approval.resolved")
    assert tilo_policy.open_gate(requested, resolved, world_owner=OWNER).outcome == "run"  # the untouched pair opens

    def opens(req: dict, res: dict) -> bool:
        return tilo_policy.open_gate(req, res, world_owner=OWNER).outcome == "run"

    by_approver = copy.deepcopy(requested)
    by_approver["data"]["approver"]["assigned_by"]["by"] = APPROVER  # an Approver naming themself
    by_lead = copy.deepcopy(requested)
    by_lead["data"]["approver"]["assigned_by"]["by"] = LEAD  # a Team Lead naming the Approver
    after = copy.deepcopy(requested)
    after["data"]["approver"]["assigned_by"]["at"] = add_seconds(
        resolved["authz"]["at"], 1
    )  # assigned after the answer
    unnamed = copy.deepcopy(requested)
    unnamed["data"]["approver"] = None  # nobody besides the owner may answer
    other_user = copy.deepcopy(resolved)
    other_user["authz"]["ref"] = OTHER  # someone the owner never named
    assert not any(opens(r, resolved) for r in (by_approver, by_lead, after, unnamed))
    assert not opens(requested, other_user)


def test_FR_HIL_12_t3_still_needs_a_person_and_a_model_or_policy_cannot_stand_in(world):
    import copy  # noqa: PLC0415

    import tilo_policy  # noqa: PLC0415

    token = world.shared()["token"]
    world.clock.advance(30)
    assert world.answer(APPROVER_P, token).status_code == 200
    (requested,), (resolved,) = world.of("approval.requested"), world.of("approval.resolved")
    assert requested["data"]["risk_tier"] == "T3" and resolved["authz"]["by"] == "person"

    for stand_in in ({"by": "policy", "ref": "p_any"}, {"by": "agent", "ref": "A_s1"}, {"by": "model", "ref": "m_x"}):
        forged = copy.deepcopy(resolved)
        forged["authz"] = {**stand_in, "at": resolved["authz"]["at"]}
        assert tilo_policy.open_gate(requested, forged, world_owner=OWNER).outcome != "run"
    # sharing and answering write only the proposal and the answer; the run writes the outbox entry, from this authz
    assert {p["type"] for p in world.writer.parts} == {"approval.requested", "approval.resolved"}


# --- a link is a bearer secret ---------------------------------------------------------------------------------


def test_FR_HIL_12_the_token_never_enters_an_event_or_a_stored_card(world):
    share = world.shared()
    world.answer(APPROVER_P, share["token"])

    text = json.dumps(world.writer.parts, default=str) + json.dumps(world.store.get(W, share["card_id"]), default=str)

    assert share["token"] not in text


def test_FR_HIL_12_two_links_are_distinct_secrets_for_distinct_assignments(world):
    first = world.shared()
    second = world.shared(approver=OTHER)

    assert first["token"] != second["token"] and first["share_id"] != second["share_id"]
    assert first["card_id"] != second["card_id"]
    assert world.open(OTHER_P, first["token"]).status_code == 404  # each link opens only for the user it names
    assert world.open(APPROVER_P, second["token"]).status_code == 404
    assert world.open(OTHER_P, second["token"]).status_code == 200


# --- invariant: whatever is attempted, at most one answer, and only by the named Approver -------------------------

_ACTORS: list[Callable[[], Any]] = [lambda: None, lambda: APPROVER_P, lambda: OTHER_P, lambda: LEAD_P, lambda: VIEWER_P]


@given(
    attempts=st.lists(
        st.tuples(st.integers(0, len(_ACTORS) - 1), st.sampled_from(["approve", "edit", "hold", "bogus"])),
        min_size=1,
        max_size=12,
    )
)
@settings(max_examples=40, deadline=None, suppress_health_check=[HealthCheck.function_scoped_fixture])
def test_FR_HIL_12_property_at_most_one_approval_and_only_from_the_named_approver(attempts):
    world = World()
    token = world.shared()["token"]
    world.writer.parts.clear()

    for actor, option in attempts:
        world.answer(_ACTORS[actor](), token, option)

    resolved = world.of("approval.resolved")
    assert len(resolved) <= 1
    assert all(p["authz"]["by"] == "person" and p["authz"]["ref"] == APPROVER for p in resolved)
    assert all(p["data"]["option"] == "approve" and p["data"]["channel"] == "web" for p in resolved)
    approved_by_approver = any(a == 1 and o == "approve" for a, o in attempts)
    assert bool(resolved) == approved_by_approver  # the Approver's first approve opens it; nobody else's attempt does
