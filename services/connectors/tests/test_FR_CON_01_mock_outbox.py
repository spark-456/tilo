"""FR-CON-01 (PRD 12.1; SEC-03): the config-declared mock connector, and the rule that its
side-effecting actions run only through the outbox.

Public API these tests pin (new module `tilo_connectors.mock`):

    MockConnector(declaration: Mapping)       # a registry entry: `registry.get(id)`
        .id -> str                            # the declaration's id; the key to give Outbox
        .sent -> list[dict]                   # one record per unique (world, idempotency_key)
        .send_reply(thread_id, item, recipients, idempotency_key, grant) -> dict
            same signature and behaviour as `tilo_connectors.fakes.FakeGmail.send_reply`: the
            outbox calls this one method on every adapter (the existing, unchanged seam), a
            missing or foreign Grant raises MissingGrant, a repeated key records nothing new.

The mock has no network, no real account and no secret. It has no public method named after any
of its declared side-effecting actions (write, send, share, delete capability): the outbox's
`send_reply` is its only way to send.
"""

from __future__ import annotations

import importlib.util
import pathlib

import pytest
import tilo_connectors
from _connectors_lib import ManualClock, evidence_from_case
from _registry_lib import MOCK_ID, mock_entry, write_config
from tilo_connectors.errors import MissingGrant
from tilo_connectors.side_effects import SIDE_EFFECT_METHOD_NAMES, scan_for_side_effect_calls

SIDE_EFFECTING_CAPABILITIES = ("write", "send", "share", "delete")


def build_mock(tmp_path):
    from tilo_connectors.mock import MockConnector
    from tilo_connectors.registry import load_registry

    registry = load_registry(write_config(tmp_path, [mock_entry()]))
    return registry, MockConnector(registry.get(MOCK_ID))


def make_outbox(mock, emitted: list[dict]):
    store = tilo_connectors.InMemoryOutboxStore()
    clock = ManualClock("2026-09-29T09:00:00.000Z")
    return tilo_connectors.Outbox(store, {mock.id: mock}, emitted.append, clock)


def send_case(gate_case_factory, **overrides):
    return gate_case_factory(connector=MOCK_ID, action_type="send_email", **overrides)


def test_FR_CON_01_the_mock_connector_is_built_from_its_config_declaration(tmp_path):
    registry, mock = build_mock(tmp_path)

    assert mock.id == MOCK_ID
    assert mock.id in registry
    assert mock.sent == []


def test_FR_CON_01_a_mock_send_runs_through_the_outbox_and_emits_one_data_transfer(tmp_path, gate_case_factory):
    _, mock = build_mock(tmp_path)
    emitted: list[dict] = []
    outbox = make_outbox(mock, emitted)
    case = send_case(gate_case_factory, destination="thread-mock-1")
    outbox.enqueue(case["entry"], evidence_from_case(case))

    outbox.dispatch_due()

    assert len(mock.sent) == 1
    assert mock.sent[0]["thread_id"] == "thread-mock-1"
    assert mock.sent[0]["idempotency_key"] == case["entry"]["idempotency_key"]
    assert [e["type"] for e in emitted] == ["data.transfer"]
    assert emitted[0]["data"]["connector"] == MOCK_ID
    assert emitted[0]["data"]["action_type"] == "send_email"
    assert emitted[0]["data"]["outbox_id"] == case["entry"]["id"]


def test_FR_CON_01_nothing_reaches_the_mock_before_the_outbox_dispatches(tmp_path, gate_case_factory):
    _, mock = build_mock(tmp_path)
    outbox = make_outbox(mock, [])
    case = send_case(gate_case_factory, undo_window_s=60)

    outbox.enqueue(case["entry"], evidence_from_case(case))

    assert mock.sent == []  # enqueue is not a send; the undo window has not passed


def test_FR_CON_01_calling_the_mocks_send_directly_without_a_grant_is_refused(tmp_path):
    _, mock = build_mock(tmp_path)

    with pytest.raises(MissingGrant):
        mock.send_reply("thread-mock-1", None, ["riya@example.com"], "r_village_basic_1:U2:send_email:1", None)

    assert mock.sent == []


def test_FR_CON_01_a_grant_minted_for_one_send_cannot_be_replayed_by_hand_on_the_mock(tmp_path, gate_case_factory):
    """The Grant a dispatch minted is dead once that send is over (SEC-03): a caller holding it
    cannot make the mock send again, and a Grant for another key does not authorise this key."""
    _, mock = build_mock(tmp_path)
    captured: list = []
    real_send = mock.send_reply

    class Spy:  # hands the outbox's Grant to the test, then lets the mock do the real work
        id = MOCK_ID

        def send_reply(self, thread_id, item, recipients, idempotency_key, grant):
            captured.append(grant)
            return real_send(thread_id, item, recipients, idempotency_key, grant)

    outbox = make_outbox(Spy(), [])
    case = send_case(gate_case_factory)
    outbox.enqueue(case["entry"], evidence_from_case(case))
    outbox.dispatch_due()
    assert len(captured) == 1 and len(mock.sent) == 1

    with pytest.raises(MissingGrant):
        real_send("thread-mock-1", None, ["x@example.com"], "r_village_basic_1:U9:send_email:other", captured[0])
    with pytest.raises(MissingGrant):
        real_send("thread-mock-1", None, ["x@example.com"], case["entry"]["idempotency_key"] + "-new", captured[0])
    assert len(mock.sent) == 1


def test_FR_CON_01_a_retry_storm_through_the_outbox_sends_to_the_mock_once(tmp_path, gate_case_factory):
    _, mock = build_mock(tmp_path)
    emitted: list[dict] = []
    outbox = make_outbox(mock, emitted)
    case = send_case(gate_case_factory)

    for _ in range(3):
        outbox.enqueue(case["entry"], evidence_from_case(case))
    for _ in range(5):
        outbox.dispatch_due()

    assert len(mock.sent) == 1
    assert len(emitted) == 1


def test_FR_CON_01_the_mock_has_no_direct_send_path_named_after_a_declared_side_effecting_action(tmp_path):
    registry, mock = build_mock(tmp_path)
    declaration = registry.get(MOCK_ID)
    side_effecting = [a["id"] for a in declaration["actions"] if a["capability"] in SIDE_EFFECTING_CAPABILITIES]
    assert side_effecting == ["send_email"]

    for action_id in side_effecting:
        assert not hasattr(mock, action_id), f"mock exposes a direct path for side-effecting action {action_id!r}"
    # the one side-effect method is the outbox's registered one (side_effects.SIDE_EFFECT_METHOD_NAMES)
    assert "send_reply" in SIDE_EFFECT_METHOD_NAMES
    assert callable(mock.send_reply)


def test_FR_CON_01_the_registry_and_mock_modules_never_call_a_side_effect_method(tmp_path, outbox_module_path):
    """SEC-03's static scan, applied to the two new modules: only outbox.py may reference
    `send_reply`; the registry and the mock define one but never call one."""
    paths = []
    for name in ("tilo_connectors.registry", "tilo_connectors.mock"):
        spec = importlib.util.find_spec(name)
        assert spec is not None and spec.origin, f"{name} must exist"
        paths.append(pathlib.Path(spec.origin))

    violations = scan_for_side_effect_calls(paths, allowed_path=outbox_module_path)

    assert violations == []


def test_FR_CON_01_listing_islands_and_reading_declarations_sends_nothing(tmp_path, gate_case_factory):
    registry, mock = build_mock(tmp_path)

    registry.list_for_world()
    registry.get(MOCK_ID)
    registry.ids()

    assert mock.sent == []  # showing an island is not an action on it
