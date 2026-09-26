"""ST-2 last extra round: the store is copy-in, copy-out. Whatever a hostile adapter or a hostile
event writer does to the objects it is handed, the stored entry, the pending transfer and every
emitted data.transfer stay exactly what was authorised (PI-14, PI-16, PI-17)."""

from __future__ import annotations

import copy

import tilo_connectors
from _connectors_lib import ManualClock, evidence_from_case
from hypothesis import given, settings
from hypothesis import strategies as st
from tilo_connectors.fakes import FakeGmail

T0 = "2026-09-29T09:32:09.500Z"


def _vandalise(value) -> None:
    """Mutate every dict and list reachable from value, nested keys included."""
    if isinstance(value, dict):
        for key in list(value):
            _vandalise(value[key])
        value["provider_msg_id"] = "msg-from-the-provider"
        if "version" in value:
            value["version"] = 99
        if "artifact_id" in value:
            value["artifact_id"] = "art_swapped"
    elif isinstance(value, list):
        for item in value:
            _vandalise(item)
        value.append("stranger@evil.example")


class HostileGmail(FakeGmail):
    def send_reply(self, thread_id, item, recipients, idempotency_key, grant):
        result = super().send_reply(thread_id, item, recipients, idempotency_key, grant)
        _vandalise(item)
        _vandalise(recipients)
        _vandalise(result)
        return result


@settings(max_examples=10, deadline=None)
@given(fail_first=st.integers(min_value=0, max_value=3))
def test_PI_16_PI_17_hostile_adapter_and_writer_never_change_what_is_stored_or_emitted(fail_first, gate_case_factory):
    emitted: list[dict] = []
    left = {"fail": fail_first}

    def hostile_writer(part: dict) -> None:
        emitted.append(copy.deepcopy(part))
        _vandalise(part)
        if left["fail"]:
            left["fail"] -= 1
            raise RuntimeError("writer failed after mutating the part")

    case = gate_case_factory(outbox_id="01JB5VQ0000000000000009901", idempotency_key="r_village_basic_1:U2:boundary:1")
    authorised = copy.deepcopy(case["entry"])
    outbox = tilo_connectors.Outbox(
        tilo_connectors.InMemoryOutboxStore(), {"gmail": HostileGmail()}, hostile_writer, ManualClock(T0)
    )
    returned = outbox.enqueue(case["entry"], evidence_from_case(case))
    _vandalise(returned)  # the caller mutating enqueue's return value changes nothing either
    for _ in range(fail_first + 2):
        settled = outbox.dispatch_due()
        for entry in settled:
            _vandalise(entry)

    assert len(emitted) == fail_first + 1, "one attempt per failure, then exactly one that lands"
    for part in emitted:
        assert part["data"]["artifact"] == authorised["item"]
        assert part["data"]["outbox_id"] == authorised["id"]
        assert part["authz"] == authorised["authz"]
        assert "provider_msg_id" not in str(part)
    assert all(part == emitted[0] for part in emitted), "every retry sends the part first built"
