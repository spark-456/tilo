"""SEC-11 (PRD 16.4: "Audit of every authorisation" -> "100% of side effects carry `authz`"; PRD 10.4 Audit, HR-7)
through the API, on the real run path: a person approves a gate over the cards route, the run writes
`approval.resolved`, the outbox sends through the connector adapter, and the world's recorded stream is the audit
trail.

Acceptance claim: in the recorded stream of a complete gated run, EVERY event the registry marks `side_effect: true`
carries a valid `authz` of an authority that type allows (here: the signed-in owner, `by: person`), NO other event
carries one, every real send (the connector adapter's own log) has exactly one `data.transfer` out whose `authz` equals
the `authz` of the `approval.resolved` that opened it, and the run cannot send when nobody approved it. The set of
side-effect types is discovered from contracts/events/registry.yaml, not hard-coded.

Companion proofs: services/harness/tests/test_SEC_11_every_side_effect_carries_authz.py (the writer refuses any
side-effect event without authz, for every registered type) and
services/connectors/tests/test_SEC_11_every_side_effect_carries_authz.py (the outbox refuses every side-effect action
without authz, discovered from config). Fakes only: a scripted Director, a mock connector, an in-memory store.
"""

from __future__ import annotations

import json
import pathlib

import jsonschema
import yaml
from _clint1_lib import FLOW_USER
from _clint2_lib import wait_for
from referencing import Registry, Resource
from referencing.jsonschema import DRAFT202012

REPO_ROOT = pathlib.Path(__file__).resolve().parents[3]
REGISTRY = yaml.safe_load((REPO_ROOT / "contracts" / "events" / "registry.yaml").read_text(encoding="utf-8"))["types"]
SIDE_EFFECT_TYPES = {t for t, v in REGISTRY.items() if v["side_effect"]}


def _authz_validator() -> jsonschema.protocols.Validator:
    resources = []
    for path in sorted((REPO_ROOT / "contracts").glob("**/*.schema.json")):
        data = json.loads(path.read_text(encoding="utf-8"))
        resources.append((data.get("$id") or path.resolve().as_uri(), Resource.from_contents(data, DRAFT202012)))
    return jsonschema.Draft202012Validator(
        {"$ref": "https://contracts.tilo.example/common.schema.json#/$defs/authz"},
        registry=Registry().with_resources(resources),
    )


AUTHZ_ERRORS = _authz_validator()


def _authz_schema_errors(authz: object) -> list[str]:
    return [e.message for e in AUTHZ_ERRORS.iter_errors(authz)]


def test_SEC_11_a_complete_gated_run_records_authz_on_every_side_effect_and_on_nothing_else(run_flow):
    rf = run_flow
    rf.run_to_completion()
    wait_for(lambda: rf.adapter.sent, what="the send")
    stream = rf.quiet_stream()

    side_effects = [e for e in stream if e["type"] in SIDE_EFFECT_TYPES]
    assert {"budget.granted", "approval.resolved", "data.transfer"} <= {e["type"] for e in side_effects}
    for event in side_effects:
        assert event["authz"] is not None, f"seq {event['seq']} {event['type']}: a side effect with no authz"
        assert _authz_schema_errors(event["authz"]) == [], event["type"]
        assert event["authz"]["by"] in REGISTRY[event["type"]]["authz_by"], event["type"]
        assert event["authz"]["by"] == "person" and event["authz"]["ref"] == FLOW_USER, "the signed-in owner approved"
    assert [e["type"] for e in stream if e["type"] not in SIDE_EFFECT_TYPES and e["authz"] is not None] == []


def test_SEC_11_every_real_send_has_one_transfer_record_carrying_the_authz_of_the_approval_that_opened_it(run_flow):
    rf = run_flow
    requested, _card = rf.run_to_completion()
    wait_for(lambda: rf.adapter.sent, what="the send")
    stream = rf.quiet_stream()

    transfers = [e for e in stream if e["type"] == "data.transfer" and e["data"]["direction"] == "out"]
    resolved = [e for e in stream if e["type"] == "approval.resolved" and e["data"]["option"] == "approve"]

    assert len(rf.adapter.sent) == len(transfers) == len(resolved) == 1, "one send, one record, one approval"
    (transfer,), (approval,) = transfers, resolved
    assert transfer["data"]["outbox_id"] == approval["data"]["outbox_id"] == requested["data"]["outbox_id"]
    assert transfer["authz"] == approval["authz"], "the record carries the authz of the approval, unchanged"
    assert approval["seq"] < transfer["seq"], "the authorisation was recorded before the effect"
    assert requested["authz"] is None, "the proposal itself authorises nothing (EV-05)"


def test_SEC_11_a_run_that_nobody_approved_sends_nothing_and_records_no_authorisation_for_it(run_flow):
    rf = run_flow
    rf.run_to_gate()  # the proposal is on the gate; no one has answered
    stream = rf.quiet_stream()

    assert rf.adapter.sent == [], "nothing was sent without an approval"
    assert [e for e in stream if e["type"] in ("approval.resolved", "data.transfer", "policy.applied")] == []
    assert [e["type"] for e in stream if e["type"] in SIDE_EFFECT_TYPES] == ["budget.granted"]
