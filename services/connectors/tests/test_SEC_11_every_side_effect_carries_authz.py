"""SEC-11 (PRD 16.4: "Audit of every authorisation" -> "100% of side effects carry `authz`"; PRD 10.4 Audit, HR-7;
contracts/outbox.rules.md OB-01; contracts/event.rules.md EV-03 to EV-06).

Acceptance claim, proved end to end on the real `Outbox` with in-process fakes: EVERY side effect that tilo-connectors
can execute (a) is an outbox entry that carries a valid `authz` (a person, a policy or a Team Lead, never a model),
equal to the authorisation that opened it, (b) emits exactly one `data.transfer` that carries that same `authz`, and
(c) is REFUSED, with nothing sent and nothing emitted, when `authz` is missing, null, a model, malformed, or not the
authorisation that opened it. The side-effect set is DISCOVERED, not hard-coded, so a new one without `authz`
coverage fails this file:

- the action catalogue: every action type in the risk table (config/autonomy.yaml, `tilo_policy.load_risk_table`)
  except the read-only `read_events`, `web_search` and `fetch_url` (ADR-0029) and the connector-less `grant_budget`
  (its authz is the `budget.granted` event,
  checked in the harness SEC-11 file), paired with the connector that declares it in config/connectors.yaml;
- every gated or non-read action of every connector in config/connectors.yaml (`load_registry`);
- every adapter class under `tilo_connectors.adapters` (and the in-process fakes) that exposes a method named in
  `side_effects.SIDE_EFFECT_METHOD_NAMES`, and any public adapter method that LOOKS like a mutation but is not
  registered there;
- every valid and invalid outbox cross-reference fixture (contracts/fixtures/outbox/crossref), which together cover
  the person-at-a-gate, Team Lead, L2 and L3 policy authorisation paths;
- every event type the registry marks `side_effect: true` that tilo-connectors emits.

Side-effect paths enumerated, 2026-10-07: send_email (gmail), create_draft (gmail), save_file and save_as_google_file
(google_drive), build_handoff (lovable), create_meeting_event (meeting_host) are declared and have adapters;
post_status_update, share_file and delete_file are risk-table actions with NO declaring connector and no adapter
(they cannot execute; they are still held to the authz rules below so adding an adapter cannot skip them).

Defaults where the PRD is silent: "carry authz" is read as the OB-01 rule, the entry's authz equals the authz of the
approval.resolved or policy.applied that opened it, and the transfer repeats it unchanged (PI-16).
"""

from __future__ import annotations

import copy
import importlib
import inspect
import json
import pathlib
import pkgutil

import jsonschema
import pytest
import tilo_connectors
import tilo_connectors.adapters as adapters_pkg
import yaml
from _connectors_lib import ManualClock, evidence_from_case, fresh_entry
from conftest import build_registry, gate_case
from hypothesis import given, settings
from hypothesis import strategies as st
from tilo_connectors.errors import MissingGrant, OutboxRefused
from tilo_connectors.fakes import FakeGmail
from tilo_connectors.registry import load_registry
from tilo_connectors.side_effects import SIDE_EFFECT_METHOD_NAMES
from tilo_policy import load_risk_table

REPO_ROOT = pathlib.Path(__file__).resolve().parents[3]
CONTRACTS = REPO_ROOT / "contracts"
NOW = "2026-09-29T09:00:00.000Z"

READ_ONLY_CAPABILITIES = {"read", "search", "list"}
# read-only (each declared ungated with a read capability, checked below); and a budget grant through no connector
# send_push: a risk-table action whose adapter lives in tilo-channels (`WebPushAdapter`, FR-CHN-17), not in
# config/connectors.yaml: nothing for a person to connect. Its per-action case below runs the real push path.
PUSH_ACTION, PUSH_CONNECTOR = "send_push", "web_push"
# ADR-0048: the agents' Gmail and Drive read tools joined the risk table as T1 reads (like read_events)
NOT_AN_OUTBOX_ACTION = {
    "read_events", "search_email", "read_email", "list_files", "read_file", "web_search", "fetch_url", "grant_budget"
}  # fmt: skip
MUTATION_VERBS = ("send", "create", "save", "share", "delete", "insert", "patch", "update", "upload", "post", "write")


# ---------------------------------------------------------------------------------------------------------------
# Discovery


def _declared() -> dict[str, tuple[str, dict]]:
    """action id -> (connector id, action) for every connector action that is gated or not read-only."""
    registry = load_registry(REPO_ROOT / "config" / "connectors.yaml")
    found: dict[str, tuple[str, dict]] = {}
    for connector_id in registry.ids():
        declaration = registry.get(connector_id)
        for action in declaration["actions"]:
            if declaration["auth"] == "oauth2" and not declaration["scopes"].get(action["capability"]):
                continue  # FR-UX-18 setup catalogue (Slack, Notion, ...): no scope and no adapter, nothing to execute
            if action["gate_type"] != "none" or action["capability"] not in READ_ONLY_CAPABILITIES:
                found[action["id"]] = (connector_id, action)
    return found


DECLARED = _declared()
RISK = load_risk_table()
ACTION_TYPES = sorted(set(RISK.actions) - NOT_AN_OUTBOX_ACTION)
CONNECTOR_OF = {
    action: DECLARED[action][0] if action in DECLARED else (PUSH_CONNECTOR if action == PUSH_ACTION else "gmail")
    for action in ACTION_TYPES
}
REGISTRY = yaml.safe_load((CONTRACTS / "events" / "registry.yaml").read_text(encoding="utf-8"))["types"]
SIDE_EFFECT_EVENT_TYPES = {t for t, v in REGISTRY.items() if v["side_effect"]}


def _adapter_classes() -> list[type]:
    found: list[type] = []
    for info in pkgutil.iter_modules(adapters_pkg.__path__):
        module = importlib.import_module(f"tilo_connectors.adapters.{info.name}")
        for _, cls in inspect.getmembers(module, inspect.isclass):
            if cls.__module__ == module.__name__ and not cls.__name__.startswith("_"):
                found.append(cls)
    from tilo_connectors.mock import MockConnector

    return [*found, FakeGmail, MockConnector]


ADAPTERS = _adapter_classes()


def _validator(ref: str) -> jsonschema.protocols.Validator:
    return jsonschema.Draft202012Validator({"$ref": ref}, registry=build_registry(REPO_ROOT))


AUTHZ_ERRORS = _validator("https://contracts.tilo.example/common.schema.json#/$defs/authz")


def _outbox(emitted: list[dict], *, connectors: dict | None = None, clock: ManualClock | None = None):
    gmail = FakeGmail()
    registered = connectors or {cid: gmail for cid in {*CONNECTOR_OF.values(), "gmail", "google_drive"}}
    store = tilo_connectors.InMemoryOutboxStore()
    return tilo_connectors.Outbox(store, registered, emitted.append, clock or ManualClock(NOW)), gmail, store


class _PushSink:
    """The browser vendors' push service, in process: every send lands in `sent`."""

    def __init__(self) -> None:
        self.sent: list[bytes] = []

    def send(self, sub, payload: bytes, vapid) -> None:
        self.sent.append(payload)


def _push_outbox(emitted: list[dict], owner: str):
    """The real path of FR-CHN-17: tilo-channels' `WebPushAdapter` behind the real `Outbox` (the grant is
    checked by the outbox), one stored device of the owner, the notice read back from the stored item."""
    from tilo_channels.digest import DigestArtifacts
    from tilo_channels.web_push import SubscriptionStore, VapidRef, WebPushAdapter

    subs, artifacts, sink = SubscriptionStore(), DigestArtifacts(), _PushSink()
    endpoint = "https://fcm.googleapis.com/fcm/send/" + "a" * 40
    subs.add(owner, {"endpoint": endpoint, "keys": {"p256dh": "B" + "x" * 86, "auth": "y" * 22}})
    artifacts.store("art_reply_draft", "A send is waiting for your approval", "")
    adapter = WebPushAdapter(
        subscriptions=subs, sender=sink, artifacts=artifacts, owner=owner, vapid=VapidRef("webpush-vapid-private-key")
    )
    store = tilo_connectors.InMemoryOutboxStore()
    outbox = tilo_connectors.Outbox(store, {PUSH_CONNECTOR: adapter}, emitted.append, ManualClock(NOW))
    return outbox, sink, store


def _case(gate_case_factory, action: str, **over):
    return gate_case_factory(
        action_type=action,
        connector=CONNECTOR_OF[action],
        risk_tier=RISK.tier_of(action, []),
        undo_window_s=0,
        idempotency_key=f"r_sec11:{action}:1",
        outbox_id=f"01JB5VQ00000000000000092{ACTION_TYPES.index(action):02d}",
        **over,
    )


# ---------------------------------------------------------------------------------------------------------------
# The side-effect set is discovered and consistent


def test_SEC_11_the_discovered_side_effect_set_is_consistent_between_config_and_risk_table():
    assert ACTION_TYPES, "no side-effect action discovered: the discovery is broken"
    gated = {a for a, (_, action) in DECLARED.items() if action["gate_type"] != "none"}
    for action, (connector, declared) in DECLARED.items():
        assert declared["risk_tier"] == RISK.actions[action], f"{connector}/{action}: config and risk table disagree"
    assert gated <= set(ACTION_TYPES), "a gated connector action is missing from the risk table"
    # org_model_key_change (ADR-0041 BK-07) is tilo-api's own T3 route: no connector, no adapter
    assert set(ACTION_TYPES) - set(DECLARED) == {
        "post_status_update",
        "share_file",
        "delete_file",
        "org_model_key_change",
        PUSH_ACTION,
    }, (
        "an action type changed between 'no connector declares it' and 'a connector declares it': it now needs an "
        "adapter that runs only from the outbox, and the SEC-11 cases below already cover it by name"
    )
    assert {"send_email", "create_draft", "save_file", "save_as_google_file", "build_handoff"} <= set(ACTION_TYPES)
    assert "create_meeting_event" in ACTION_TYPES
    registry = load_registry(REPO_ROOT / "config" / "connectors.yaml")
    actions = {a["id"]: a for c in registry.ids() for a in registry.get(c)["actions"]}
    for read_only in NOT_AN_OUTBOX_ACTION - {"grant_budget"}:  # excluded only while it stays an ungated read
        assert actions[read_only]["gate_type"] == "none", read_only
        assert actions[read_only]["capability"] in READ_ONLY_CAPABILITIES, read_only


def test_SEC_11_every_adapter_that_can_perform_a_side_effect_runs_only_from_the_outbox():
    with_side_effects = [c for c in ADAPTERS if SIDE_EFFECT_METHOD_NAMES & set(dir(c))]
    names = {c.__name__ for c in with_side_effects}
    assert {"GmailAdapter", "DriveAdapter", "MeetingHostAdapter", "LovableLinkAdapter", "FakeGmail"} <= names

    for cls in with_side_effects:
        entry = {"world_id": "w_probe", "idempotency_key": "k", "authz": None}
        bare = object.__new__(cls)  # no dependencies at all: the grant check must come before any of them is used
        for method in sorted(SIDE_EFFECT_METHOD_NAMES & set(dir(cls))):
            call = getattr(bare, method)
            args = ("t", None, ["a@example.com"], "k", None) if method == "send_reply" else (entry, None)
            with pytest.raises(MissingGrant):
                call(*args)
            with pytest.raises(MissingGrant):
                call(*args[:-1], object())  # a forged grant


def test_SEC_11_no_adapter_has_an_unregistered_method_that_looks_like_a_mutation():
    unregistered = {
        f"{cls.__name__}.{name}"
        for cls in ADAPTERS
        for name, member in inspect.getmembers(cls, inspect.isfunction)
        if not name.startswith("_") and name not in SIDE_EFFECT_METHOD_NAMES and name.startswith(MUTATION_VERBS)
    }
    assert unregistered == set(), (
        f"{sorted(unregistered)} look like side effects but are not in SIDE_EFFECT_METHOD_NAMES, so SEC-03's static "
        "check and this file do not see them: register them (outbox-only, grant-checked) or rename them"
    )


# ---------------------------------------------------------------------------------------------------------------
# 100% of side effects carry authz, per action type


@pytest.mark.parametrize("action", ACTION_TYPES)
def test_SEC_11_every_side_effect_action_runs_with_authz_and_emits_the_same_authz(action, gate_case_factory):
    case = _case(gate_case_factory, action)
    emitted: list[dict] = []
    if action == PUSH_ACTION:  # the real push path, not a fake mailbox
        outbox, sink, _ = _push_outbox(emitted, case["entry"]["authz"]["ref"])
        executed = lambda: len(sink.sent)  # noqa: E731
    else:
        outbox, gmail, _ = _outbox(emitted)
        executed = lambda: len(gmail.sent)  # noqa: E731
    stored = outbox.enqueue(case["entry"], evidence_from_case(case))
    assert list(AUTHZ_ERRORS.iter_errors(stored["authz"])) == []

    (sent,) = outbox.dispatch_due()

    assert sent["state"] == "sent" and executed() == 1
    transfers = [p for p in emitted if p["type"] == "data.transfer"]
    assert len(transfers) == 1, "each executed side effect is recorded exactly once"
    (transfer,) = transfers
    assert transfer["authz"] == stored["authz"], "the record carries the authorisation that opened the effect"
    assert list(AUTHZ_ERRORS.iter_errors(transfer["authz"])) == []
    assert transfer["authz"]["by"] in REGISTRY["data.transfer"]["authz_by"]
    if RISK.tier_of(action, []) == "T3":
        assert transfer["authz"]["by"] != "policy", "T3 always needs a person (EV-07)"
    assert transfer["data"]["action_type"] == action and transfer["data"]["outbox_id"] == stored["id"]


def _without(entry: dict) -> dict:
    return {k: v for k, v in entry.items() if k != "authz"}


REFUSED_AUTHZ = {
    "missing": lambda e: _without(e),
    "null": lambda e: {**e, "authz": None},
    "a model": lambda e: {**e, "authz": {"by": "model", "ref": "m_director", "at": e["created_at"]}},
    "empty": lambda e: {**e, "authz": {}},
    "no ref": lambda e: {**e, "authz": {"by": "person", "at": e["created_at"]}},
    "no timestamp": lambda e: {**e, "authz": {"by": "person", "ref": e["authz"]["ref"]}},
    "string": lambda e: {**e, "authz": "u_owner"},
    "another person": lambda e: {**e, "authz": {**e["authz"], "ref": "u_someone_else"}},
    "a policy for a person's gate": lambda e: {**e, "authz": {"by": "policy", "ref": "pol_x", "at": e["created_at"]}},
    "a team lead for a person's gate": lambda e: {
        **e,
        "authz": {"by": "team_lead", "ref": "tl_x", "at": e["created_at"]},
    },
}


@pytest.mark.parametrize("what", sorted(REFUSED_AUTHZ))
@pytest.mark.parametrize("action", ACTION_TYPES)
def test_SEC_11_a_side_effect_without_a_valid_authz_is_refused_and_nothing_is_sent(action, what, gate_case_factory):
    case = _case(gate_case_factory, action)
    entry = REFUSED_AUTHZ[what](copy.deepcopy(case["entry"]))
    emitted: list[dict] = []
    outbox, gmail, store = _outbox(emitted)

    with pytest.raises(OutboxRefused):
        outbox.enqueue(entry, evidence_from_case(case))

    assert outbox.dispatch_due() == []
    assert gmail.sent == [] and emitted == [], "nothing was sent and nothing was recorded"
    assert store.all_entries() == [], "nothing was stored to be sent later"


# ---------------------------------------------------------------------------------------------------------------
# Every authorisation path in the contracts: 100% of authorised side effects carry authz, 100% of the rest refused


def _fixture_cases(folder: str) -> list[tuple[str, dict]]:
    return [
        (path.name, json.loads(path.read_text(encoding="utf-8")))
        for path in sorted((CONTRACTS / "fixtures" / "outbox" / "crossref" / folder).glob("*.json"))
    ]


VALID_CASES = _fixture_cases("valid")
AUTHZ_INVALID_CASES = [
    (name, case)
    for name, case in _fixture_cases("invalid")
    if case["rule"] == "OB-01" and not name.startswith("ob01_transfer")  # those two break the transfer, not the entry
]


def test_SEC_11_the_fixture_set_covers_every_authorisation_path():
    paths = {case["entry"]["authz"]["by"] for _, case in VALID_CASES}
    assert paths == {"person", "policy", "team_lead"}, "person, policy and Team Lead authorisations are all exercised"
    levels = {(case["authorised_by"] or {}).get("data", {}).get("level") for _, case in VALID_CASES}
    assert {"L2", "L3"} & levels, "both policy levels that run without a person at the gate"


@pytest.mark.parametrize(("name", "case"), VALID_CASES, ids=[n for n, _ in VALID_CASES])
def test_SEC_11_every_authorised_entry_in_the_contract_fixtures_is_recorded_with_its_authz(name, case):
    emitted: list[dict] = []
    clock = ManualClock(NOW)
    outbox, gmail, _ = _outbox(emitted, connectors=dict.fromkeys(("gmail", "google_drive"), FakeGmail()), clock=clock)
    entry = fresh_entry(case["entry"])
    outbox.enqueue(entry, evidence_from_case(case))
    clock.set("2026-09-29T23:00:00.000Z")  # past any undo window in the fixtures

    sent = outbox.dispatch_due()

    transfers = [p for p in emitted if p["type"] == "data.transfer"]
    assert len(sent) == len(transfers) == 1, f"{name}: every executed side effect has its record"
    assert transfers[0]["authz"] == entry["authz"]
    assert list(AUTHZ_ERRORS.iter_errors(transfers[0]["authz"])) == []


@pytest.mark.parametrize(("name", "case"), AUTHZ_INVALID_CASES, ids=[n for n, _ in AUTHZ_INVALID_CASES])
def test_SEC_11_every_unauthorised_entry_in_the_contract_fixtures_is_refused(name, case):
    gmail = FakeGmail()
    emitted: list[dict] = []
    outbox, _, _ = _outbox(emitted, connectors={"gmail": gmail, "google_drive": gmail})

    with pytest.raises(OutboxRefused):
        outbox.enqueue(fresh_entry(case["entry"]), evidence_from_case(case))

    assert outbox.dispatch_due() == [] and gmail.sent == [] and emitted == []


def test_SEC_11_every_schema_level_authz_defect_in_the_contract_fixtures_is_refused():
    names = {
        "authz_null.json",
        "authz_by_model.json",
        "t3_authorised_by_policy.json",
        "t3_attachment_authorised_by_policy.json",
    }
    for name in sorted(names):
        entry = json.loads((CONTRACTS / "fixtures" / "outbox" / "invalid" / name).read_text("utf-8"))
        outbox, gmail, _ = _outbox([])
        with pytest.raises(OutboxRefused):
            outbox.enqueue(entry, {})
        assert gmail.sent == [], name


# ---------------------------------------------------------------------------------------------------------------
# Property: whatever authz is presented, a side effect runs only with the authorisation that opened it


_REF = st.one_of(st.text(max_size=12), st.sampled_from(["u_owner", "pol_x", "tl_x", ""]))
_AUTHZ = st.one_of(
    st.none(),
    st.text(max_size=8),
    st.fixed_dictionaries(
        {},
        optional={
            "by": st.sampled_from(["person", "policy", "team_lead", "model", "system", "", "Person"]),
            "ref": _REF,
            "at": st.sampled_from(["2026-09-29T09:32:09.500Z", "now", "", "2026-09-29"]),
            "extra": st.just("x"),
        },
    ),
)


@settings(max_examples=150, deadline=None)
@given(presented=_AUTHZ)
def test_SEC_11_property_no_side_effect_runs_unless_its_authz_is_the_one_that_opened_it(presented):
    case = gate_case(undo_window_s=0)
    genuine = case["entry"]["authz"]
    entry = {**case["entry"], "authz": presented}
    emitted: list[dict] = []
    outbox, gmail, _ = _outbox(emitted)

    try:
        outbox.enqueue(entry, evidence_from_case(case))
    except OutboxRefused:
        assert presented != genuine
        outbox.dispatch_due()
        assert gmail.sent == [] and emitted == []
        return

    assert presented == genuine, "only the genuine authorisation may open the side effect"
    outbox.dispatch_due()
    assert len(gmail.sent) == 1
    assert [p["authz"] for p in emitted if p["type"] == "data.transfer"] == [genuine]


# ---------------------------------------------------------------------------------------------------------------
# Events: every event the connectors emit carries authz exactly when the registry says it is a side effect


def test_SEC_11_events_emitted_by_connectors_carry_authz_exactly_when_they_are_side_effects(gate_case_factory):
    from _oauth_lib import OWNER, finish_flow, make_env, start_flow

    env = make_env()
    finish_flow(env, start_flow(env, OWNER, "google_drive", ["write"]), OWNER)  # connection.consented / established

    emitted: list[dict] = []
    outbox, _, _ = _outbox(emitted)
    for action in ACTION_TYPES:
        case = _case(gate_case_factory, action)
        outbox.enqueue(case["entry"], evidence_from_case(case))
    outbox.dispatch_due()

    parts = [*env.emitted, *emitted]
    assert {p["type"] for p in parts} >= {"connection.consented", "data.transfer"}
    for part in parts:
        is_side_effect = part["type"] in SIDE_EFFECT_EVENT_TYPES
        assert (part["authz"] is not None) == is_side_effect, f"{part['type']}: authz must be set iff side_effect"
        if is_side_effect:
            assert list(AUTHZ_ERRORS.iter_errors(part["authz"])) == []
            assert part["authz"]["by"] in REGISTRY[part["type"]]["authz_by"], part["type"]
    sent_transfers = [p for p in emitted if p["type"] == "data.transfer"]
    assert len(sent_transfers) == len(ACTION_TYPES), "one authorised record per executed side effect"


# ---------------------------------------------------------------------------------------------------------------
# Defence in depth: the last gate before the effect


@pytest.mark.parametrize(
    "damage",
    [
        lambda e: e.pop("authz"),
        lambda e: e.update(authz=None),
        lambda e: e.update(authz={"by": "model", "ref": "m", "at": e["created_at"]}),
    ],
    ids=["authz-removed", "authz-null", "authz-a-model"],
)
def test_SEC_11_dispatch_refuses_a_stored_entry_that_no_longer_carries_a_valid_authz(damage, gate_case_factory):
    """A stored entry that lost its authz (a store bug, a hand-edited document, a writer other than `enqueue`) must
    not be executed: the side effect and its audit record must stay one thing. The entry is damaged through the
    store's own dict, the only way to reach this state, because `enqueue` refuses it."""
    case = gate_case_factory(undo_window_s=0)
    emitted: list[dict] = []
    outbox, gmail, store = _outbox(emitted)
    outbox.enqueue(case["entry"], evidence_from_case(case))
    damage(store._by_id[case["entry"]["id"]])

    done = outbox.dispatch_due()  # refused cleanly: no exception, no half-written record

    assert gmail.sent == [], "a side effect ran without a valid authz, and its audit record could not be written"
    assert [e["state"] for e in done] == ["failed"]
    assert emitted == [], "no data.transfer for a send that did not happen"
    assert store._pending_alerts == {}, "nothing was ever sent, so no person is alerted"
    assert outbox.dispatch_due() == [] and gmail.sent == [], "a failed entry is final: never retried"


def test_SEC_11_a_refused_entry_that_an_earlier_attempt_may_have_sent_still_alerts_a_person(gate_case_factory):
    """FR-AGT-13: when an earlier attempt was ambiguous (the provider may have acted), the authz refusal is final
    but a person is still told, as on every other final refusal of a possibly-sent entry."""
    case = gate_case_factory(undo_window_s=0)
    emitted: list[dict] = []
    outbox, gmail, store = _outbox(emitted)
    outbox.enqueue(case["entry"], evidence_from_case(case))
    outbox_id = case["entry"]["id"]
    store._retries[outbox_id] = {"attempts": 1, "ambiguous": True}  # an earlier try timed out after the provider acted
    store._by_id[outbox_id].pop("authz")

    done = outbox.dispatch_due()

    assert gmail.sent == [] and [e["state"] for e in done] == ["failed"] and emitted == []
    assert list(store._pending_alerts) == [outbox_id], "a possibly-sent entry that is refused alerts a person once"
