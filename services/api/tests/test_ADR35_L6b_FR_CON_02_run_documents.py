"""ADR35_L6b / FR_CON_02: a run PRODUCES the L5 item documents, so an approved card can really draft and send.

A whole run in process: the planned unit drafts, then sends. The fields a document lacks are asked of the person
(a needs-you card, nothing enqueued) and supplied on the fields route; the document is a new JSON version of the
unit's artifact that the cards pin and the hash covers; the real tilo-connectors route runs it with Google faked.
No network, no paid call, no live switch.
"""

from __future__ import annotations

import base64
import dataclasses
import email
import email.policy
import hashlib
import json

import pytest
from _adr35_l6_lib import FakeGoogle, InProcessConnectors5
from _clint2_lib import NEW_RECIPIENT, base_plan, build_run_flow, covering_policy, load_json, wait_for
from _mtg09b_lib import block_network
from tilo_api import deps, events
from tilo_api.connector_rpc import ConnectorRpcStub
from tilo_api.runs import DESTINATION_CHANGED
from tilo_connectors.registry import ConnectorRegistry
from tilo_people.stores import PeopleStores

SUBJECT = "Q3 note for the finance team"
THREAD = "<m1@example.org>"


@pytest.fixture(autouse=True)
def _offline(monkeypatch: pytest.MonkeyPatch) -> None:
    block_network(monkeypatch)


class Live:
    """A run of one unit that drafts and then sends by the live stub over the real connectors route."""

    def __init__(self, repo_root, *, actions=("create_draft", "send_email"), fields=None, destination=None,
                 connector="gmail", recipients=(NEW_RECIPIENT,), unit_type=None):  # fmt: skip
        self.rf = rf = build_run_flow(repo_root, covered=True)
        self.google = FakeGoogle()
        self.connectors = InProcessConnectors5(self.google, clock=events.now)
        self.fields, self.destination, self.actions = fields or {}, destination, actions
        self.connector, self.recipients, self.unit_type = connector, list(recipients), unit_type
        rf.registry = (
            ConnectorRegistry({"gmail": load_json("contracts", "fixtures", "connector", "valid", "gmail.json")})
            if connector == "gmail" else deps.get_connector_registry()
        )  # fmt: skip
        rf.compile_plan = self.compile_plan
        rf.resolve_action = self.resolve_action
        stub = ConnectorRpcStub(connector, self.connectors.rpc)
        rf.flow.app.dependency_overrides[deps.get_connector_adapters] = lambda: {connector: stub}
        people = PeopleStores.in_memory()  # the people write limit counts the fields route like any people POST
        rf.flow.app.dependency_overrides[deps.get_people_stores] = lambda: people
        rf.flow.app.dependency_overrides[deps.get_clock] = lambda: events.now
        self.destinations: dict[str, str | None] = {}

    def compile_plan(self, *, brief, approach, budget_cap, context=None):
        plan = base_plan(approach["id"], budget_cap)
        plan["units"][3] |= {"connectors": [self.connector], "actions": list(self.actions)}
        if self.unit_type:
            plan["units"][3]["unit_type"] = self.unit_type
        tiers = {
            "create_draft": "T1",
            "send_email": "T3",
            "create_event": "T1",
            "update_event": "T2",
            "save_file": "T1",
        }
        plan["gates"] = [
            {"id": f"G{n}", "action_type": a, "risk_tier": tiers[a], "guards": ["U4"], "policy_ref": None}
            for n, a in enumerate(self.actions, start=1)
        ]
        return plan

    def resolve_action(self, *, unit, action_type, item, brief):
        destination = self.destinations.get(action_type, self.destination)
        return {"destination": destination, "recipients": self.recipients, "known_recipients": [],
                "fields": dict(self.fields)}  # fmt: skip

    def start(self):
        self.rf.start()
        self.as_user("u_flow_owner", "owner", full=True)
        assert self.rf.approve().status_code == 200

    def as_user(self, user: str, role: str, *, full: bool = True, districts: tuple[str, ...] = ()):
        self.rf.flow.principal = deps.Principal(
            user_id=user, role=role, world_id=self.rf.world_id, districts=districts, full_session=full
        )  # type: ignore[arg-type]

    def ask_card(self):
        def find():
            cards = self.rf.cards().json() if self.rf.cards().status_code == 200 else []
            return next((c for c in cards if c["kind"] == "needs_you" and "needs" in c["what_happened"]), None)

        return wait_for(find, what="the needs-field card")

    def gate_card(self, action: str, *, nth: int = 0):
        def find():
            cards = self.rf.cards().json() if self.rf.cards().status_code == 200 else []
            gates = [c for c in cards if c["kind"] == "gate" and c["gate"]["action"]["type"] == action]
            return gates[nth] if len(gates) > nth else None

        return wait_for(find, what=f"the {action} gate card")

    def supply(self, card_id: str, fields: dict):
        return self.rf.flow.client.post(f"/worlds/{self.rf.world_id}/cards/{card_id}/fields", json={"fields": fields})

    def read(self, ref: dict) -> bytes:
        return self.rf.rig.store.read(self.rf.scope(), ref)

    def close(self) -> None:
        self.rf.close()


@pytest.fixture
def live(repo_root):
    made = []

    def make(**kw):
        made.append(Live(repo_root, **kw))
        return made[-1]

    yield make
    for item in made:
        item.close()


def mime_of(raw_b64: str):
    return email.message_from_bytes(base64.urlsafe_b64decode(raw_b64), policy=email.policy.default)


def text_of(message) -> str:
    return "\n".join(message.get_content().splitlines()).strip()


def test_ADR35_L6b_FR_CON_02_a_missing_subject_asks_the_person_and_enqueues_nothing(live):
    lv = live()
    lv.start()
    card = lv.ask_card()
    assert "needs subject" in card["what_happened"] and card["gate"] is None
    assert [o["id"] for o in card["options"]] == ["provide", "hold"] and card["safe_default"] == "hold"
    assert lv.rf.events("approval.requested") == [] and lv.rf.outbox_store.all_entries() == []
    assert lv.google.reached() == 0 and lv.connectors.posts == []
    assert SUBJECT not in json.dumps(lv.rf.events())  # and the body's first line was never made the subject
    assert "Unit U4 finished" not in card["what_happened"]


def test_ADR35_L6b_FR_CON_02_the_answer_fills_the_field_and_the_draft_then_the_same_content_is_sent(live):
    lv = live()
    lv.start()
    asked = lv.ask_card()
    assert lv.supply(asked["id"], {"subject": SUBJECT}).status_code == 200
    draft_card = lv.gate_card("create_draft")
    item = draft_card["gate"]["action"]["item"]
    pinned = lv.read(item)
    document = json.loads(pinned)
    assert (
        document["kind"] == "email" and document["subject"] == SUBJECT and "Unit U4 finished" in document["body_text"]
    )
    assert item["version"] == 2 and draft_card["gate"]["recipients"] == [NEW_RECIPIENT]
    assert f"subject: {SUBJECT}" in draft_card["gate"]["action"]["exact"]
    assert lv.rf.outbox_store.all_entries() == [] and lv.google.reached() == 0  # nothing before the approval
    assert lv.rf.answer(draft_card["id"], "approve").status_code == 200
    send_card = lv.gate_card("send_email")
    assert send_card["gate"]["action"]["item"] == item  # one pin for the draft and the send
    assert len(lv.google.drafts) == 1 and lv.google.sent == []
    drafted = mime_of(lv.google.drafts[0]["message"]["raw"])
    assert drafted["Subject"] == SUBJECT and text_of(drafted) == document["body_text"].strip()
    assert lv.rf.answer(send_card["id"], "approve").status_code == 200
    wait_for(lambda: lv.rf.events("world.completed"), what="world.completed")
    assert len(lv.google.drafts) == 1 and len(lv.google.sent) == 1  # the draft once, the send once
    sent = mime_of(lv.google.sent[0]["raw"])
    assert (sent["Subject"], text_of(sent)) == (drafted["Subject"], text_of(drafted))
    entries = {e["action_type"]: e for e in lv.rf.outbox_store.all_entries()}
    assert entries["create_draft"]["item"] == entries["send_email"]["item"] == item  # approved = sent
    assert hashlib.sha256(pinned).hexdigest() == lv.rf.rig.store.head(lv.rf.scope(), item).record["content_sha256"]
    assert [p["items"][0]["content_sha256"] for p in lv.connectors.posts] == [hashlib.sha256(pinned).hexdigest()] * 2


def test_ADR35_L6b_FR_CON_02_a_subject_with_a_line_break_is_refused_with_a_reason_and_the_card_stays_open(live):
    lv = live()
    lv.start()
    asked = lv.ask_card()
    bad = lv.supply(asked["id"], {"subject": "Hi\r\nBcc: someone@example.org"})
    assert bad.status_code == 422 and "line breaks" in bad.json()["reason"]
    wrong = lv.supply(asked["id"], {"subject": SUBJECT, "name": "x"})
    assert wrong.status_code == 422 and "needs subject" in wrong.json()["reason"]
    assert lv.supply("0" * 26, {"subject": SUBJECT}).status_code == 404
    assert [c["id"] for c in lv.rf.cards().json() if c["kind"] == "needs_you"] == [asked["id"]]  # still open
    assert lv.rf.events("approval.requested") == [] and lv.google.reached() == 0
    assert lv.supply(asked["id"], {"subject": SUBJECT}).status_code == 200  # the right answer still works


def test_ADR35_L6b_FR_CON_02_holding_the_question_stops_the_work_and_sends_nothing(live):
    lv = live()
    lv.start()
    asked = lv.ask_card()
    assert lv.rf.answer(asked["id"], "hold").status_code == 200
    failed = wait_for(lambda: lv.rf.events("world.failed"), what="world.failed")[0]
    assert "needs subject" in failed["data"]["reason"] and lv.rf.events("approval.requested") == []
    assert lv.rf.outbox_store.all_entries() == [] and lv.google.reached() == 0


def test_ADR35_L6b_FR_CON_02_a_provide_answer_with_nothing_supplied_fails_the_step(live):
    lv = live()
    lv.start()
    asked = lv.ask_card()
    assert lv.rf.answer(asked["id"], "provide").status_code == 200  # the plain answer route carries no value
    failed = wait_for(lambda: lv.rf.events("world.failed"), what="world.failed")[0]
    assert "nothing was added" in failed["data"]["reason"] and lv.google.reached() == 0


def test_ADR35_L6b_FR_CON_02_a_declared_subject_asks_nothing_and_a_too_big_body_is_refused_before_any_card(live):
    lv = live(fields={"subject": SUBJECT}, actions=("create_draft",))
    lv.start()
    card = lv.gate_card("create_draft")
    assert json.loads(lv.read(card["gate"]["action"]["item"]))["subject"] == SUBJECT
    assert [c for c in lv.rf.cards().json() if c["kind"] == "needs_you"] == []

    big = live(fields={"subject": SUBJECT}, actions=("create_draft",))
    original = big.rf.runner.run

    async def run(unit, context):
        outcome = await original(unit, context)
        if unit["id"] != "U4":
            return outcome
        out = type(outcome.outputs[0])(media_type="text/markdown", content=b"x" * 40_000)
        return type(outcome)(success=True, summary=outcome.summary, outputs=(out,))

    big.rf.runner.run = run
    big.start()
    failed = wait_for(lambda: big.rf.events("world.failed"), what="world.failed")[0]
    assert "KiB" in failed["data"]["reason"] and big.rf.events("approval.requested") == []
    assert big.rf.outbox_store.all_entries() == []


def test_ADR35_L6b_FR_CON_02_a_reply_pins_the_subject_from_the_document_not_the_thread(live):
    lv = live(fields={"subject": SUBJECT, "in_reply_to": THREAD}, actions=("create_draft",), destination="thr_a1")
    lv.start()
    card = lv.gate_card("create_draft")
    document = json.loads(lv.read(card["gate"]["action"]["item"]))
    assert document["in_reply_to"] == THREAD and "destination thr_a1" in card["gate"]["action"]["exact"]
    plain = live(fields={"subject": SUBJECT}, actions=("create_draft",), destination="thr_a1")
    plain.start()
    failed = wait_for(lambda: plain.rf.events("world.failed"), what="world.failed")[0]
    assert "name the message" in failed["data"]["reason"] and plain.rf.events("approval.requested") == []


def test_ADR35_L6b_FR_CON_02_the_documents_events_are_recorded_and_registered(live):
    lv = live(fields={"subject": SUBJECT}, actions=("create_draft",))
    lv.start()
    card = lv.gate_card("create_draft")
    item = card["gate"]["action"]["item"]
    versioned = [e for e in lv.rf.events("artifact.versioned") if e["data"]["artifact"] == item]
    assert len(versioned) == 1 and versioned[0]["data"]["previous_version"] == 1


def test_ADR35_L6b_FR_CON_02_a_demo_or_mock_connector_sends_the_units_own_artifact_unchanged(repo_root):
    rf = build_run_flow(repo_root, covered=True)  # the mock adapter: no stub, so no document and no question
    try:
        requested, card = rf.run_to_gate()
        stored = rf.rig.store.head(rf.scope(), card["gate"]["action"]["item"]).record
        assert stored["media_type"] == "text/markdown" and not rf.events("artifact.versioned")
    finally:
        rf.close()


EVENT = {"title": "Review", "start": "2026-10-12T09:00:00.000Z", "end": "2026-10-12T09:30:00.000Z",
         "time_zone": "Asia/Kolkata"}  # fmt: skip


def test_ADR35_L6b_FR_CON_02_an_event_needs_no_recipient_and_lands_on_the_own_calendar_once_approved(live):
    lv = live(connector="google_calendar", actions=("create_event",), fields=EVENT, destination="primary",
              recipients=())  # fmt: skip
    lv.start()
    card = lv.gate_card("create_event")
    document = json.loads(lv.read(card["gate"]["action"]["item"]))
    assert document == {"kind": "calendar_event", **EVENT} and card["gate"]["recipients"] == []
    assert (
        "event Review, 2026-10-12T09:00:00.000Z to 2026-10-12T09:30:00.000Z (Asia/Kolkata)"
        in card["gate"]["action"]["exact"]
    )
    assert lv.google.events == {} and lv.rf.outbox_store.all_entries() == []
    assert lv.rf.answer(card["id"], "approve").status_code == 200
    wait_for(lambda: lv.rf.events("world.completed"), what="world.completed")
    (made,) = lv.google.events.values()
    assert made["summary"] == "Review" and "attendees" not in made


def test_WORKSPACE_TOOLS_WT08_update_event_run_builds_approval_card_without_undo_claim(live):
    lv = live(
        connector="google_calendar", actions=("update_event",), fields=EVENT, destination="event-1", recipients=()
    )
    policy = covering_policy()
    policy.update(id="pol_update_event_ask", action_type="update_event")
    policy["scope"]["connectors"] = ["google_calendar"]
    lv.rf.rig.store.policies[policy["id"]] = policy
    lv.start()

    def ready():
        failed = lv.rf.events("world.failed")
        if failed:
            return ("failed", failed)
        completed = lv.rf.events("world.completed")
        if completed:
            return ("completed", completed, lv.rf.events())
        response = lv.rf.cards()
        if response.status_code != 200:
            return ("http", response.status_code, response.text)
        cards = response.json()
        if not isinstance(cards, list):
            return ("invalid_cards", cards)
        found = next((c for c in cards if c["kind"] == "gate" and c["gate"]["action"]["type"] == "update_event"), None)
        return ("card", found) if found else None

    try:
        state = wait_for(ready, what="the update_event approval card")
    except AssertionError as exc:
        raise AssertionError(lv.rf.events()) from exc
    assert state[0] == "card", state
    card = state[1]
    assert "cannot be undone" in card["why_it_matters"]
    document = json.loads(lv.read(card["gate"]["action"]["item"]))
    assert document == {"kind": "calendar_event", **EVENT}
    assert lv.google.reached() == 0


def test_WORKSPACE_TOOLS_WT08_reminder_unit_pins_15_minute_popup_before_approval(live):
    lv = live(
        connector="google_calendar",
        actions=("create_event",),
        fields={"title": "Pay bill", "start": "2026-10-12T09:00:00Z", "time_zone": "Asia/Kolkata"},
        destination="primary",
        recipients=(),
        unit_type="reminder",
    )
    lv.start()
    card = lv.gate_card("create_event")
    document = json.loads(lv.read(card["gate"]["action"]["item"]))
    assert document == {
        "kind": "calendar_event",
        "title": "Pay bill",
        "start": "2026-10-12T09:00:00Z",
        "end": "2026-10-12T09:15:00Z",
        "time_zone": "Asia/Kolkata",
        "reminders": [{"method": "popup", "minutes": 0}],
    }
    assert lv.google.reached() == 0 and lv.rf.outbox_store.all_entries() == []


def test_ADR35_L6b_FR_CON_02_guests_on_create_event_fail_the_step_with_a_reason_before_any_card(live):
    lv = live(connector="google_calendar", actions=("create_event",), destination="primary", recipients=(),
              fields={**EVENT, "attendees": ["guest@example.org"]})  # fmt: skip
    lv.start()
    failed = wait_for(lambda: lv.rf.events("world.failed"), what="world.failed")[0]
    assert "guest" in failed["data"]["reason"] and lv.rf.events("approval.requested") == []
    assert lv.rf.outbox_store.all_entries() == [] and lv.google.reached() == 0


def test_ADR35_L6b_FR_CON_02_a_file_with_no_name_asks_for_it_by_name(live):
    lv = live(connector="google_drive", actions=("save_file",), destination="fld_tilo_reports", recipients=())
    lv.start()
    assert "needs name" in lv.ask_card()["what_happened"] and lv.google.reached() == 0


def entry_of(lv, action):
    found = lambda: next((e for e in lv.rf.outbox_store.all_entries() if e["action_type"] == action), None)  # noqa: E731
    return wait_for(found, what=f"the {action} entry")


class Flagging:
    """A screener that flags Markdown only: the unit's body is flagged, the JSON document made from it is clean."""

    def check(self, text, *, content=None, mime_type=None):
        return {"flagged": text.startswith("# ")}


@pytest.mark.parametrize(
    "kwargs, action",
    [
        ({"actions": ("create_draft",), "fields": {"subject": SUBJECT}}, "create_draft"),
        ({"connector": "google_drive", "actions": ("save_file",), "fields": {"name": "n.md"},
          "destination": "fld_tilo_reports", "recipients": ()}, "save_file"),
    ],
)  # fmt: skip
def test_ADR35_L6b_FR_CON_02_the_bodys_flagged_verdict_stays_with_the_pin_and_keeps_the_safety_modifier(
    live, kwargs, action
):
    flagged = live(**kwargs)
    flagged.rf.rig.store._screener = Flagging()
    flagged.start()
    card = flagged.gate_card(action)
    assert card["gate"]["risk_tier"] == "T3"  # a flagged body is not cleared by its clean document
    item = card["gate"]["action"]["item"]
    assert flagged.rf.rig.store.head(flagged.rf.scope(), item).record["screening"] == "clean"
    assert flagged.rf.answer(card["id"], "approve").status_code == 200
    entry = entry_of(flagged, action)
    assert "safety_flag" in entry["modifiers"] and entry["risk_tier"] == "T3"


def test_ADR35_L6b_FR_CON_02_a_send_must_go_where_its_draft_went(live):
    lv = live(fields={"subject": SUBJECT, "in_reply_to": THREAD})
    lv.destinations = {"create_draft": None, "send_email": "thr_a1"}
    lv.start()
    card = lv.gate_card("create_draft")
    assert lv.rf.answer(card["id"], "approve").status_code == 200
    failed = wait_for(lambda: lv.rf.events("world.failed"), what="world.failed")[0]
    assert failed["data"]["reason"] == DESTINATION_CHANGED
    gates = [c for c in lv.rf.cards().json() if c["kind"] == "gate" and c["gate"]["action"]["type"] == "send_email"]
    assert gates == [] and len(lv.google.sent) == 0


@pytest.mark.parametrize(
    "who, role, districts",
    [
        ("u_viewer1", "viewer", ()),
        ("u_appr1", "approver", ()),
        ("u_lead1", "team_lead", ("D9",)),
        ("u_lead2", "team_lead", ("D2",)),
    ],
)
def test_ADR35_L6b_FR_CON_02_only_the_owner_may_supply_and_a_stranger_learns_nothing(live, who, role, districts):
    lv = live()
    lv.start()
    asked = lv.ask_card()
    lv.as_user(who, role, full=True, districts=districts)
    answers = [lv.supply(asked["id"], f) for f in ({"subject": SUBJECT}, {"subject": "a\nb"}, {"name": "x"}, {})]
    assert {a.status_code for a in answers} == {404} and len({a.text for a in answers}) == 1
    assert "subject" not in answers[0].text and lv.rf.events("approval.requested") == []
    lv.as_user("u_flow_owner", "owner", full=True)
    assert lv.supply(asked["id"], {"subject": SUBJECT}).status_code == 200  # nothing was wiped or answered


def test_ADR35_L6b_FR_CON_02_a_demo_session_is_refused_and_json_only_closed_and_capped_bodies_hold(live):
    lv = live()
    lv.start()
    asked = lv.ask_card()
    lv.as_user("u_flow_owner", "owner", full=False)
    assert lv.supply(asked["id"], {"subject": SUBJECT}).status_code == 403
    lv.as_user("u_flow_owner", "owner", full=True)
    url = f"/worlds/{lv.rf.world_id}/cards/{asked['id']}/fields"
    client = lv.rf.flow.client
    plain = client.post(url, content=b'{"fields": {"subject": "x"}}', headers={"content-type": "text/plain"})
    assert plain.status_code == 415
    assert client.post(url, json={"fields": {"subject": "x"}, "more": 1}).status_code == 422
    assert client.post(url, json={"fields": {"subject": "x" * 40_000}}).status_code == 413
    assert lv.supply(asked["id"], {"subject": SUBJECT}).status_code == 200


def test_ADR35_L6b_FR_CON_02_two_answers_do_not_wipe_each_other_and_the_loser_changes_nothing(live):
    import threading  # noqa: PLC0415

    lv = live()
    lv.start()
    asked = lv.ask_card()
    codes: list[int] = []

    def go(subject: str) -> None:
        codes.append(lv.supply(asked["id"], {"subject": subject}).status_code)

    threads = [threading.Thread(target=go, args=(f"Subject number {n}",)) for n in range(2)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    assert sorted(codes)[0] == 200 and all(c in (200, 400, 404, 409) for c in codes)
    card = lv.gate_card("create_draft")
    document = json.loads(lv.read(card["gate"]["action"]["item"]))
    assert document["subject"].startswith("Subject number") and lv.google.reached() == 0
    run = lv.rf.store.runs[lv.rf.world_id]
    assert run._supplied == {} and asked["id"] not in run._asking  # nothing is left behind


def test_ADR35_L6b_FR_CON_02_a_hold_clears_what_was_asked_and_staged(live):
    lv = live()
    lv.start()
    asked = lv.ask_card()
    assert lv.rf.answer(asked["id"], "hold").status_code == 200
    wait_for(lambda: lv.rf.events("world.failed"), what="world.failed")
    run = lv.rf.store.runs[lv.rf.world_id]
    assert run._asking == {} and run._supplied == {}
    assert lv.supply(asked["id"], {"subject": SUBJECT}).status_code == 404


def test_ADR35_L6b_FR_CON_02_a_guest_on_create_event_from_the_resolver_fails_before_any_card(live):
    lv = live(connector="google_calendar", actions=("create_event",), destination="primary",
              recipients=("guest@example.org",), fields={})  # fmt: skip
    lv.start()
    failed = wait_for(lambda: lv.rf.events("world.failed"), what="world.failed")[0]
    assert "guest" in failed["data"]["reason"]
    assert lv.rf.events("approval.requested") == [] and lv.rf.cards().json() == []


def test_ADR35_L6b_FR_CON_02_the_cards_line_is_read_from_the_stored_redacted_version(live):
    lv = live()
    lv.start()
    asked = lv.ask_card()
    token = "tkn-0123456789abcdef"
    store = lv.rf.rig.store
    original = store.put

    def put(scope, new):  # the store redacts the subject on the way in
        if new.media_type == "application/json":
            new = dataclasses.replace(new, content=new.content.replace(token.encode(), b"[redacted]"))
        return original(scope, new)

    store.put = put
    assert lv.supply(asked["id"], {"subject": "Pay " + token}).status_code == 200
    exact = lv.gate_card("create_draft")["gate"]["action"]["exact"]
    assert token not in exact and "[redacted]" in exact


def test_ADR35_L6b_FR_CON_02_the_resolver_alone_declares_fields_never_the_brief_or_the_units_text(live):
    seen = {}
    lv = live()
    original = lv.resolve_action

    def spy(**kw):
        seen.update(kw)
        return original(**kw)

    lv.rf.resolve_action = spy
    lv.start()
    lv.ask_card()  # the brief and the unit's title were offered to the resolver, and none became the subject
    assert "brief" in seen and lv.rf.events("approval.requested") == []


def test_ADR35_L6b_FR_CON_02_a_clean_body_carries_no_safety_modifier(live):
    lv = live(actions=("create_draft",), fields={"subject": SUBJECT})
    lv.start()
    card = lv.gate_card("create_draft")
    assert lv.rf.answer(card["id"], "approve").status_code == 200
    assert "safety_flag" not in entry_of(lv, "create_draft")["modifiers"]
