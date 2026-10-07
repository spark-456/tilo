"""SEC-11 (PRD 16.4: "Audit of every authorisation" -> "100% of side effects carry `authz`"; PRD 10.4 Audit, HR-7;
contracts/event.rules.md EV-03 to EV-07) at the RECORD: the one writer every world event passes through.

Acceptance claim, proved on the real `WorldWriter` / `EventValidator` over the in-memory store: every event type the
registry marks `side_effect: true` is written only with a valid `authz` (a person, a policy or a Team Lead as that type
allows, never a model), and a side-effect event without one is refused with nothing written (no stream row, no view,
no head move); no other event carries one (EV-05), so the audit trail is exactly the set of side effects. The set of
side-effect types is DISCOVERED from contracts/events/registry.yaml, so a new side-effect type that lacks an `authz`
rule fails here.

Side-effect event types discovered, 2026-10-07: budget.granted,
connection.consented, data.transfer, approval.resolved, policy.applied, policy.changed. The outbox that executes
connector side effects and emits `data.transfer` is proved in
services/connectors/tests/test_SEC_11_every_side_effect_carries_authz.py.

Defaults where the PRD is silent: "carries authz" is the EV-03 shape (`common.schema.json#/$defs/authz`) and EV-04
allowed authorities per type; `approval.requested` is not a side effect (it proposes, EV-05) and carries `authz: null`.
"""

from __future__ import annotations

import copy
import json
from typing import Any

import pytest
import yaml
from conftest import CONTRACTS_DIR, make_memory_writer
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st
from tilo_harness.validator import EventRejected, EventValidator

REGISTRY = yaml.safe_load((CONTRACTS_DIR / "events" / "registry.yaml").read_text(encoding="utf-8"))["types"]
SIDE_EFFECT_TYPES = sorted(t for t, v in REGISTRY.items() if v["side_effect"])
OTHER_TYPES = sorted(t for t, v in REGISTRY.items() if not v["side_effect"])
LAYOUT = json.loads((CONTRACTS_DIR / "fixtures/layout/valid/village_basic.json").read_text(encoding="utf-8"))
WORLD = "w_village_basic"
VALIDATOR = EventValidator.from_repo()


def _fixture(event_type: str) -> dict[str, Any]:
    return json.loads((CONTRACTS_DIR / REGISTRY[event_type]["fixture"]).read_text(encoding="utf-8"))


def _emit_kwargs(event_type: str, *, authz: Any) -> dict[str, Any]:
    fx = _fixture(event_type)
    kw = {k: copy.deepcopy(fx[k]) for k in ("type", "actor", "summary", "data", "level", "district", "item")}
    kw |= {"target": WORLD, "severity": fx["severity"], "credits": fx["credits"], "vis": fx["vis"], "authz": authz}
    return kw


def _writer():
    return make_memory_writer(LAYOUT, world_id=WORLD, run_id="r_sec11_1")


def _nothing_written(store: Any) -> None:
    assert store.read_events("org_demo", WORLD) == [], "a refused event must write nothing to the stream"
    assert store.read_view("org_demo", WORLD, "shared") == [], "...nor to any view"


def _authz_problem(problems: list[str]) -> bool:
    return any(p.startswith(("schema:", "EV-03", "EV-04", "EV-05", "EV-06", "EV-07")) for p in problems)


# ---------------------------------------------------------------------------------------------------------------
# Discovery


def test_SEC_11_the_side_effect_set_is_discovered_from_the_registry_and_matches_the_contract():
    from tilo_contracts import SIDE_EFFECT_EVENT_TYPES  # generated from the registry

    schema = json.loads((CONTRACTS_DIR / "event.schema.json").read_text(encoding="utf-8"))
    listed_in_schema = set(schema["if"]["properties"]["type"]["enum"])  # EV-03: carries authz

    assert SIDE_EFFECT_TYPES, "no side-effect type discovered: the discovery is broken"
    assert set(SIDE_EFFECT_TYPES) == {str(t) for t in SIDE_EFFECT_EVENT_TYPES}
    assert listed_in_schema == set(SIDE_EFFECT_TYPES), "event.schema.json lists the same types (EV-03)"
    assert {"approval.resolved", "policy.applied", "data.transfer", "connection.consented"} <= set(SIDE_EFFECT_TYPES)
    for event_type in SIDE_EFFECT_TYPES:
        assert REGISTRY[event_type]["authz_by"], f"{event_type} is a side effect and names who may authorise it"
        assert "model" not in REGISTRY[event_type]["authz_by"], "a model is never an authority"


# ---------------------------------------------------------------------------------------------------------------
# Each side-effect type: written with authz, refused without


@pytest.mark.parametrize("event_type", SIDE_EFFECT_TYPES)
def test_SEC_11_a_side_effect_event_is_written_with_its_authz_and_the_valid_fixture_carries_one(event_type):
    fx = _fixture(event_type)
    assert fx["authz"] is not None and fx["authz"]["by"] in REGISTRY[event_type]["authz_by"]
    assert VALIDATOR.problems(fx) == []
    writer, store = _writer()

    written = writer.emit(**_emit_kwargs(event_type, authz=fx["authz"]))

    assert written["authz"] == fx["authz"]
    assert [e["authz"] for e in store.read_events("org_demo", WORLD)] == [fx["authz"]]


REFUSED = {
    "missing (null)": lambda authz, allowed: None,
    "a model": lambda authz, allowed: {"by": "model", "ref": "m_director", "at": authz["at"]},
    "an unknown authority": lambda authz, allowed: {"by": "system", "ref": "sys", "at": authz["at"]},
    "no ref": lambda authz, allowed: {"by": authz["by"], "at": authz["at"]},
    "no timestamp": lambda authz, allowed: {"by": authz["by"], "ref": authz["ref"]},
    "an empty ref": lambda authz, allowed: {**authz, "ref": ""},
    "not an object": lambda authz, allowed: "u_owner",
    "an authority this type does not allow": lambda authz, allowed: next(
        (
            {"by": by, "ref": {"person": "u_owner", "policy": "pol_x", "team_lead": "tl_x"}[by], "at": authz["at"]}
            for by in ("person", "policy", "team_lead")
            if by not in allowed
        ),
        None,
    ),
}


CASES = [
    (event_type, what)
    for event_type in SIDE_EFFECT_TYPES
    for what in sorted(REFUSED)
    if what != "an authority this type does not allow" or len(REGISTRY[event_type]["authz_by"]) < 3
]


@pytest.mark.parametrize(("event_type", "what"), CASES, ids=[f"{t}-{w}" for t, w in CASES])
def test_SEC_11_a_side_effect_event_without_a_valid_authz_is_refused_and_nothing_is_written(event_type, what):
    fx = _fixture(event_type)
    allowed = REGISTRY[event_type]["authz_by"]
    bad = REFUSED[what](fx["authz"], allowed)
    writer, store = _writer()
    writer.emit(**_emit_kwargs(event_type, authz=fx["authz"]))  # positive control: the same event is accepted
    before = store.read_events("org_demo", WORLD)

    with pytest.raises(EventRejected) as info:
        writer.emit(**_emit_kwargs(event_type, authz=bad))

    assert _authz_problem(info.value.problems), info.value.problems
    assert store.read_events("org_demo", WORLD) == before, "a refused event writes nothing"
    assert len(store.read_view("org_demo", WORLD, "shared")) <= len(before)


@pytest.mark.parametrize("event_type", [t for t in SIDE_EFFECT_TYPES if "risk_tier" in _fixture(t)["data"]])
def test_SEC_11_a_policy_never_authorises_a_tier_3_side_effect(event_type):
    fx = _fixture(event_type)
    data = {**fx["data"], "risk_tier": "T3"}
    policy = {"by": "policy", "ref": fx["data"].get("policy_id", "pol_x"), "at": fx["ts"]}
    event = {**fx, "data": data, "authz": policy}

    assert any("EV-07" in p or "schema" in p or "EV-04" in p for p in VALIDATOR.problems(event))


# ---------------------------------------------------------------------------------------------------------------
# And only side effects carry one (EV-05): the trail is exactly the side effects


@pytest.mark.parametrize("event_type", OTHER_TYPES)
def test_SEC_11_an_event_that_is_not_a_side_effect_carries_no_authz(event_type):
    fx = _fixture(event_type)
    assert fx["authz"] is None
    forged = {**fx, "authz": {"by": "person", "ref": "u_owner", "at": fx["ts"]}}

    problems = VALIDATOR.problems(forged)

    assert any(p.startswith("EV-05") for p in problems), problems


# ---------------------------------------------------------------------------------------------------------------
# A whole recorded run: 100% of its side effects carry authz


def test_SEC_11_every_side_effect_event_of_a_recorded_run_carries_authz_and_no_other_event_does(
    village_basic_layout, village_basic_stream
):
    writer, store = make_memory_writer(village_basic_layout, world_id=WORLD, run_id="r_village_basic_1")
    for event in village_basic_stream:
        writer.append(event)

    stored = store.read_events("org_demo", WORLD)
    side_effects = [e for e in stored if e["type"] in SIDE_EFFECT_TYPES]
    assert len(side_effects) >= 4, "the recorded run exercises several authorisations"
    assert all(e["authz"] is not None and e["authz"]["by"] in REGISTRY[e["type"]]["authz_by"] for e in side_effects)
    assert all(e["authz"] is None for e in stored if e["type"] not in SIDE_EFFECT_TYPES)
    for transfer in (e for e in stored if e["type"] == "data.transfer" and e["data"]["direction"] == "out"):
        resolved = [
            e
            for e in stored
            if e["type"] in ("approval.resolved", "policy.applied")
            and e["data"].get("outbox_id", transfer["data"]["outbox_id"]) == transfer["data"]["outbox_id"]
            and e["authz"] == transfer["authz"]
        ]
        assert resolved, f"seq {transfer['seq']}: a send whose authz matches no approval or policy event"


def test_SEC_11_a_run_cannot_be_replayed_with_a_side_effect_stripped_of_its_authz(
    village_basic_layout, village_basic_stream
):
    index = next(i for i, e in enumerate(village_basic_stream) if e["type"] == "data.transfer")
    writer, store = make_memory_writer(village_basic_layout, world_id=WORLD, run_id="r_village_basic_1")
    for event in village_basic_stream[:index]:
        writer.append(event)
    stripped = {**village_basic_stream[index], "authz": None}

    with pytest.raises(EventRejected):
        writer.append(stripped)

    assert len(store.read_events("org_demo", WORLD)) == index


# ---------------------------------------------------------------------------------------------------------------
# Property: the validator accepts an authz only if it is a real authority of that type


_AUTHZ = st.one_of(
    st.none(),
    st.text(max_size=6),
    st.fixed_dictionaries(
        {},
        optional={
            "by": st.sampled_from(["person", "policy", "team_lead", "model", "system", "", "PERSON"]),
            "ref": st.sampled_from(["u_owner", "pol_x", "tl_x", "", "m_director"]),
            "at": st.sampled_from(["2026-09-29T09:30:24.000Z", "2026-09-29", "", "now"]),
        },
    ),
)


@settings(max_examples=250, deadline=None, suppress_health_check=[HealthCheck.too_slow])
@given(event_type=st.sampled_from(SIDE_EFFECT_TYPES), authz=_AUTHZ)
def test_SEC_11_property_a_side_effect_event_is_valid_only_with_an_authz_of_an_allowed_authority(event_type, authz):
    event = {**_fixture(event_type), "authz": authz}

    problems = VALIDATOR.problems(event)

    if not problems:
        assert isinstance(authz, dict)
        assert authz["by"] in REGISTRY[event_type]["authz_by"] and authz["by"] != "model"
        assert authz["ref"] and authz["at"].endswith("Z")
        if authz["by"] == "policy" and "policy_id" in event["data"]:
            assert authz["ref"] == event["data"]["policy_id"]
