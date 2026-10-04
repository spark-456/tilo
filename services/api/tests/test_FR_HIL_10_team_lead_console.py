"""FR-HIL-10 (PRD 10.5, 10.6, 16.2, 8.3; ADR-0006) Team Lead console, API and event level.

Acceptance: "A routed question appears in <= 2 s; answering resumes the agent in <= 2 s."

Tested here with no browser and no dev server: a `CardStore` over the injected fake clock and recording event
writer, behind `tilo_api.console.build_router(cards)` and `deps.get_current_principal`. Shapes pinned in
`API_FR_HIL_10.md`.

How the two numbers are tested (BQ-205): in-process, against the 2.0 s budget with real time (`perf_counter`)
and a deliberately slow event writer, so a polling interval or a sleep on the path fails; and against the fake
clock, which is never advanced, so a queue that needs `tick()` or a later poll to show a question fails.
"Resumes the agent" is, at this layer, the `question.answered` part reaching the writer (the harness's agent
waits for exactly that event; its registry hud/world effect is "a sealed note returns to the agent") before the
answer call returns. What cannot be tested here is the harness resuming its agent from that event (no question
wait exists in `services/harness` yet) and the console screen in `apps/web` (an AG-WEB ticket): the API half
of FR-HIL-10 is this file.
"""

from __future__ import annotations

import pathlib
import time

import jsonschema
import pytest
import yaml
from _cards_lib import (
    FakeClock,
    FakeEventWriter,
    add_seconds,
    build_registry,
    clone_card,
    load_json,
    load_valid_card,
    new_ulid,
    principal,
)
from fastapi import FastAPI
from fastapi.testclient import TestClient
from hypothesis import given, settings
from hypothesis import strategies as st
from tilo_api import deps
from tilo_api.cards import CardStore

REPO_ROOT = pathlib.Path(__file__).resolve().parents[3]
START = "2026-09-29T09:30:00.000Z"
W = "w_01"
OWNER = "u_owner"
BUDGET_S = 2.0  # FR-HIL-10: appears <= 2 s, resumes <= 2 s
ASSIGNED = {"by": OWNER, "at": "2026-09-01T00:00:00.000Z"}
TEAM_LEADS = [
    {"id": "tl_security", "user": "u_sec", "domain": "security", "assigned_by": ASSIGNED},
    {"id": "tl_finance", "user": "u_fin", "domain": "finance", "assigned_by": ASSIGNED},
]
SEC = principal(role="team_lead", user_id="u_sec", world_id=W, districts=())
FIN = principal(role="team_lead", user_id="u_fin", world_id=W, districts=("D1",))


def console_module():
    import tilo_api.console as module  # noqa: PLC0415

    return module


class SlowWriter(FakeEventWriter):
    """A writer that takes `pause` seconds, like a real Firestore commit under load."""

    def __init__(self, pause: float) -> None:
        super().__init__()
        self.pause = pause

    def write(self, part: dict) -> None:
        time.sleep(self.pause)
        super().write(part)


def make(writer: FakeEventWriter | None = None):
    clock, writer = FakeClock(START), writer or FakeEventWriter()
    store = CardStore(clock=clock, writer=writer, world_owners={W: OWNER})
    return store, clock, writer


def card(seed: str, *, building: str = "B2", created_at: str = START) -> dict:
    return clone_card(
        load_valid_card("needs_you_blocked"), id_=new_ulid(seed), created_at=created_at, building=building
    )


def client(store: CardStore, who, team_leads=TEAM_LEADS) -> TestClient:
    module = console_module()
    app = FastAPI()
    app.include_router(module.build_router(store))
    app.dependency_overrides[deps.get_current_principal] = lambda: who
    app.dependency_overrides[module.get_team_leads] = lambda: list(team_leads)
    return TestClient(app)


def queue_ids(response) -> list[str]:
    assert response.status_code == 200, response.text
    return [c["id"] for c in response.json()["queue"]]


def routed(store: CardStore, c: dict, *, domain: str | None, district: str | None = "D1"):
    result = store.submit(c, district=district, domain=domain)
    assert result.outcome == "accepted", result
    return result


# --- the queue is the Team Lead's domain ---------------------------------------------------------------------------


def test_FR_HIL_10_the_console_queue_holds_only_questions_routed_to_the_team_leads_domain():
    store, _, _ = make()
    # a, b and c share a building, district and instant: cards that merge by building (FR-HIL-02) must still
    # never hide one domain's question behind another's, so the domain is part of what keeps cards apart.
    a, d = card("a"), card("d", building="B4", created_at=add_seconds(START, 5))
    b, c = card("b"), card("c")
    routed(store, a, domain="security")
    routed(store, d, domain="security", district="D2")  # another district, same domain: still theirs
    routed(store, b, domain="finance")
    routed(store, c, domain=None)  # the owner fallback (question.routed domain null)

    response = client(store, SEC).get(f"/worlds/{W}/console")

    assert queue_ids(response) == [a["id"], d["id"]]  # oldest first, no finance and no owner-fallback card
    body = response.json()
    assert (body["team_lead"], body["domain"]) == ("tl_security", "security")
    assert queue_ids(client(store, FIN).get(f"/worlds/{W}/console")) == [b["id"]]


def test_FR_HIL_10_a_question_routed_to_the_owner_never_reaches_any_team_lead():
    store, _, writer = make()
    owner_only = card("o")
    routed(store, owner_only, domain=None)

    for who in (SEC, FIN):
        http = client(store, who)
        assert queue_ids(http.get(f"/worlds/{W}/console")) == []
        answer = http.post(f"/worlds/{W}/console/cards/{owner_only['id']}/answer", json={"option": "per_kwh"})
        assert answer.status_code == 404 and answer.json() == {"outcome": "rejected", "reason": "card_not_found"}
    assert writer.parts == []


# --- the two numbers ---------------------------------------------------------------------------------------


def test_FR_HIL_10_a_routed_question_appears_in_the_console_within_2_s():
    store, clock, _ = make()
    http = client(store, SEC)
    assert queue_ids(http.get(f"/worlds/{W}/console")) == []
    q = card("q")

    started = time.perf_counter()
    routed(store, q, domain="security")
    shown = queue_ids(http.get(f"/worlds/{W}/console"))
    elapsed = time.perf_counter() - started

    assert shown == [q["id"]]
    assert elapsed <= BUDGET_S, f"the question took {elapsed:.3f} s to appear"
    assert clock.now() == START, "it appeared with the clock unmoved: no tick, poll or delay is needed"


def test_FR_HIL_10_answering_resumes_the_agent_within_2_s_even_with_a_slow_event_writer():
    store, clock, writer = make(SlowWriter(0.5))
    q = card("q")
    routed(store, q, domain="security")
    http = client(store, SEC)

    started = time.perf_counter()
    response = http.post(f"/worlds/{W}/console/cards/{q['id']}/answer", json={"option": "per_kwh"})
    elapsed = time.perf_counter() - started

    assert response.status_code == 200 and response.json() == {"outcome": "answered"}
    (part,) = writer.of_type("question.answered")  # written before the call returned: nothing is deferred
    assert part["data"] == {"answered_by": "team_lead"}
    assert (part["world_id"], part["card_id"], part["district"]) == (W, q["id"], "D1")
    assert (part["vis"], part["owner_only"]) == (["D1"], False)
    assert elapsed <= BUDGET_S, f"the answer took {elapsed:.3f} s to resume the agent"
    assert clock.now() == START, "no tick or timer was needed to release the agent"
    assert queue_ids(http.get(f"/worlds/{W}/console")) == []  # and the question is gone from the queue


def test_FR_HIL_10_an_answer_is_written_once_and_a_second_answer_is_refused():
    store, _, writer = make()
    q = card("q")
    routed(store, q, domain="security")
    http = client(store, SEC)

    first = http.post(f"/worlds/{W}/console/cards/{q['id']}/answer", json={"option": "per_kwh"})
    second = http.post(f"/worlds/{W}/console/cards/{q['id']}/answer", json={"option": "per_pack"})

    assert first.status_code == 200
    assert second.status_code == 400 and second.json() == {"outcome": "rejected", "reason": "already_resolved"}
    assert len(writer.of_type("question.answered")) == 1


# --- who may use the console (PRD 10.1, 16.2) -----------------------------------------------------------------------


def test_FR_HIL_10_a_team_lead_cannot_see_or_answer_another_domains_question():
    store, _, writer = make()
    finance_q = card("fin")
    routed(store, finance_q, domain="finance")

    attempt = client(store, SEC).post(f"/worlds/{W}/console/cards/{finance_q['id']}/answer", json={"option": "per_kwh"})

    assert attempt.status_code == 404 and attempt.json() == {"outcome": "rejected", "reason": "card_not_found"}
    assert writer.parts == []
    assert queue_ids(client(store, FIN).get(f"/worlds/{W}/console")) == [finance_q["id"]]  # still open for finance


@pytest.mark.parametrize(
    "who",
    [
        principal(role="viewer", user_id="u_sec", world_id=W),
        principal(role="approver", user_id="u_sec", world_id=W),
        principal(role="team_lead", user_id="u_nobody", world_id=W),  # no Team Lead record: removed or never assigned
        principal(role="intruder", user_id="u_sec", world_id=W),
    ],
    ids=["viewer", "approver", "no team lead record", "unknown role"],
)
def test_FR_HIL_10_only_a_current_team_lead_may_use_the_console(who):
    store, _, writer = make()
    q = card("q")
    routed(store, q, domain="security")
    http = client(store, who)

    listing = http.get(f"/worlds/{W}/console")
    answer = http.post(f"/worlds/{W}/console/cards/{q['id']}/answer", json={"option": "per_kwh"})

    assert listing.status_code == 403 and answer.status_code == 403
    assert "queue" not in listing.text and writer.parts == []


def test_FR_HIL_10_a_removed_team_lead_loses_the_console_at_once():
    store, _, writer = make()
    q = card("q")
    routed(store, q, domain="security")

    gone = client(store, SEC, team_leads=[t for t in TEAM_LEADS if t["id"] != "tl_security"])

    assert gone.get(f"/worlds/{W}/console").status_code == 403
    assert gone.post(f"/worlds/{W}/console/cards/{q['id']}/answer", json={"option": "per_kwh"}).status_code == 403
    assert writer.parts == []


def test_FR_HIL_10_the_console_is_scoped_to_the_principals_own_world():
    store, _, _ = make()
    elsewhere = principal(role="team_lead", user_id="u_sec", world_id="w_other")

    assert client(store, elsewhere).get(f"/worlds/{W}/console").status_code == 404  # same as an unknown world


def test_FR_HIL_10_the_console_answers_questions_only_a_gate_still_needs_the_policy_engine():
    store, _, writer = make()
    gate = clone_card(load_valid_card("gate_send_reply"), id_=new_ulid("g"), created_at=START)
    assert store.submit(gate, outbox_id=new_ulid("ob"), district="D1").outcome == "accepted"

    http = client(store, SEC)

    assert queue_ids(http.get(f"/worlds/{W}/console")) == []
    answer = http.post(f"/worlds/{W}/console/cards/{gate['id']}/answer", json={"option": "approve"})
    assert answer.status_code == 404 and writer.parts == []


def test_FR_HIL_10_a_domain_is_accepted_only_on_a_question_card_and_only_as_a_slug():
    store, _, _ = make()
    gate = clone_card(load_valid_card("gate_send_reply"), id_=new_ulid("g"), created_at=START)

    assert store.submit(gate, outbox_id=new_ulid("ob"), domain="security").outcome == "rejected"
    assert store.submit(card("x"), domain="Not A Slug").outcome == "rejected"
    assert store.submit(card("y"), domain="x" * 80).outcome == "rejected"


@pytest.mark.parametrize("body", [{}, {"option": 7}, {"option": "per_kwh", "actor": "u_fin"}, {"option": "nope"}])
def test_FR_HIL_10_a_bad_answer_body_changes_nothing(body):
    store, _, writer = make()
    q = card("q")
    routed(store, q, domain="security")
    http = client(store, SEC)

    response = http.post(f"/worlds/{W}/console/cards/{q['id']}/answer", json=body)

    assert response.status_code in (400, 422)  # unknown option 400, malformed or identity-bearing body 422
    assert writer.parts == [] and queue_ids(http.get(f"/worlds/{W}/console")) == [q["id"]]


# --- history and answer-time stats (PRD 10.5) -----------------------------------------------------------------------


def test_FR_HIL_10_history_and_answer_time_stats_come_from_the_clock():
    store, clock, _ = make()
    fast, slow, untouched = card("fast", building="B1"), card("slow", building="B2"), card("open", building="B3")
    for c in (fast, slow, untouched):
        routed(store, c, domain="security")
    http = client(store, SEC)
    assert http.get(f"/worlds/{W}/console").json()["stats"] == {"answered": 0, "median_answer_s": None}

    clock.advance(30)
    assert http.post(f"/worlds/{W}/console/cards/{fast['id']}/answer", json={"option": "per_kwh"}).status_code == 200
    clock.advance(60)
    assert http.post(f"/worlds/{W}/console/cards/{slow['id']}/answer", json={"option": "per_pack"}).status_code == 200

    body = http.get(f"/worlds/{W}/console").json()
    by_card = {h["card_id"]: h for h in body["history"]}
    assert set(by_card) == {fast["id"], slow["id"]}
    assert (by_card[fast["id"]]["option"], by_card[fast["id"]]["answer_time_s"]) == ("per_kwh", 30)
    assert (by_card[slow["id"]]["option"], by_card[slow["id"]]["answer_time_s"]) == ("per_pack", 90)
    assert by_card[slow["id"]]["answered_at"] == add_seconds(START, 90)
    assert body["stats"] == {"answered": 2, "median_answer_s": 60}
    assert [c["id"] for c in body["queue"]] == [untouched["id"]]


def test_FR_HIL_10_history_lists_only_this_team_leads_decisions_not_a_timeout_default():
    store, clock, _ = make()
    mine, timed_out, theirs = card("mine", building="B1"), card("late", building="B2"), card("fin", building="B3")
    routed(store, mine, domain="security")
    routed(store, timed_out, domain="security", district="D3")
    routed(store, theirs, domain="finance")
    sec_http, fin_http = client(store, SEC), client(store, FIN)
    clock.advance(10)
    sec_http.post(f"/worlds/{W}/console/cards/{mine['id']}/answer", json={"option": "per_kwh"})
    fin_http.post(f"/worlds/{W}/console/cards/{theirs['id']}/answer", json={"option": "per_kwh"})
    clock.advance(timed_out["timeout"])
    store.tick()  # the safe default answers `timed_out`: nobody decided it

    body = sec_http.get(f"/worlds/{W}/console").json()

    assert [h["card_id"] for h in body["history"]] == [mine["id"]]
    assert body["stats"]["answered"] == 1 and body["queue"] == []


# --- the Team Lead records of config/teams.yaml (ADR-0006) ----------------------------------------------------------


def test_FR_HIL_10_the_default_team_lead_records_are_config_teams_yaml_and_schema_valid():
    module = console_module()
    shipped = yaml.safe_load((REPO_ROOT / "config" / "teams.yaml").read_text(encoding="utf-8"))
    schema = load_json(REPO_ROOT / "contracts" / "team_lead.schema.json")
    validator = jsonschema.Draft202012Validator(schema, registry=build_registry())

    records = module.get_team_leads()

    assert records == shipped and len(records) >= 1
    for record in records:
        assert not list(validator.iter_errors(record))


# --- properties -----------------------------------------------------------------------------------------------------


@settings(max_examples=40, deadline=None)
@given(
    domains=st.lists(st.sampled_from(["security", "finance", None]), min_size=0, max_size=8),
    districts=st.lists(st.sampled_from(["D1", "D2", "D3"]), min_size=8, max_size=8),
)
def test_FR_HIL_10_property_a_team_leads_queue_is_exactly_their_domains_open_questions_oldest_first(domains, districts):
    """Invariant: nothing routed elsewhere leaks into a console, and nothing routed to its domain is missing."""
    store, _, _ = make()
    expected: dict[str, list[str]] = {"security": [], "finance": []}
    for i, domain in enumerate(domains):
        c = card(f"p{i}", building=f"B{i + 1}", created_at=add_seconds(START, i))  # one building each: no merging
        routed(store, c, domain=domain, district=districts[i])
        if domain is not None:
            expected[domain].append(c["id"])

    assert queue_ids(client(store, SEC).get(f"/worlds/{W}/console")) == expected["security"]
    assert queue_ids(client(store, FIN).get(f"/worlds/{W}/console")) == expected["finance"]
