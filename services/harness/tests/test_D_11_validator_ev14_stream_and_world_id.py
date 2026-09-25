"""D-11 fix round, security-reviewer's second finding: `EventValidator._stream_problems` left
out the stream half of EV-14 (a delivery that left Tilo must be caused by the matching
`data.transfer` out, same outbox_id and artifact -- contracts/scripts/contracts_events.py's
`_is_send_of`) and never checked that an appended event's `world_id` belongs to the world being
written (EV-10). Both are exercised end-to-end through `WorldWriter`, the same way the rest of
EV-10..EV-14 already is in test_D_11_writer_seq_and_atomicity.py and
test_D_11_village_basic_stream_append.py.
"""

from __future__ import annotations

import pytest
from conftest import make_memory_writer, sequential_ulid, world_requested_kwargs
from tilo_harness.writer import EventRejected

OUTBOX_ID = "01JB5VQ0000000000000009999"
ARTIFACT = {"artifact_id": "art_reply_draft", "version": 1}


@pytest.fixture
def writer_and_store(village_basic_layout: dict):
    return make_memory_writer(village_basic_layout)


def _sent_kwargs(cause: str) -> dict:
    return {
        "type": "data.transfer",
        "actor": "A_s2",
        "target": "I1",
        "level": "L1",
        "district": "D1",
        "item": {"kind": "scroll", "artifact_id": "art_reply_draft", "label": "Reply to supplier"},
        "summary": "The reply went to the supplier.",
        "cause": cause,
        "authz": {"by": "person", "ref": "u_owner", "at": "2026-09-29T09:32:09.500Z"},
        "data": {
            "connector": "gmail",
            "action_type": "send_email",
            "direction": "out",
            "artifact": ARTIFACT,
            "outbox_id": OUTBOX_ID,
            "risk_tier": "T2",
        },
    }


def _delivered_kwargs(cause: str | None) -> dict:
    return {
        "type": "artifact.delivered",
        "actor": "A_l1",
        "target": "art_reply_draft",
        "level": "L1",
        "district": "D1",
        "item": {"kind": "parcel", "artifact_id": "art_reply_draft", "label": "Reply to supplier"},
        "summary": "The reply was delivered by email.",
        "cause": cause,
        "data": {"artifact": ARTIFACT, "format": "email", "outbox_id": OUTBOX_ID},
    }


def test_D_11_stream_rejects_an_email_delivery_whose_cause_is_not_the_matching_transfer_EV_14(
    writer_and_store,
) -> None:
    """The exact bug named: an email delivery whose cause is `world.requested` (an earlier event
    of this world, so EV-11 alone lets it through) must still be rejected by EV-14."""
    writer, store = writer_and_store
    requested = writer.emit(**world_requested_kwargs())
    writer.emit(**_sent_kwargs(cause=requested["id"]))  # the real data.transfer out, unused below

    with pytest.raises(EventRejected) as excinfo:
        writer.emit(**_delivered_kwargs(cause=requested["id"]))  # wrong: not the data.transfer out
    assert any(p.startswith("EV-14") for p in excinfo.value.problems), excinfo.value.problems
    assert [e["seq"] for e in store.read_events("org_demo", "w_village_basic")] == [1, 2], (
        "D-11: the rejected delivery must not have been written"
    )


def test_D_11_stream_accepts_an_email_delivery_caused_by_its_matching_transfer_out(writer_and_store) -> None:
    writer, store = writer_and_store
    requested = writer.emit(**world_requested_kwargs())
    sent = writer.emit(**_sent_kwargs(cause=requested["id"]))

    delivered = writer.emit(**_delivered_kwargs(cause=sent["id"]))
    assert delivered["seq"] == 3
    assert [e["seq"] for e in store.read_events("org_demo", "w_village_basic")] == [1, 2, 3]


def test_D_11_stream_rejects_an_email_delivery_caused_by_a_transfer_of_a_different_outbox_entry(
    writer_and_store,
) -> None:
    writer, _store = writer_and_store
    requested = writer.emit(**world_requested_kwargs())
    other_sent_kwargs = _sent_kwargs(cause=requested["id"])
    other_sent_kwargs["data"] = dict(other_sent_kwargs["data"], outbox_id="01JB5VQ0000000000000001111")
    other_sent = writer.emit(**other_sent_kwargs)

    with pytest.raises(EventRejected) as excinfo:
        writer.emit(**_delivered_kwargs(cause=other_sent["id"]))  # names a different outbox_id
    assert any(p.startswith("EV-14") for p in excinfo.value.problems), excinfo.value.problems


def _built_event(seq: int, event_id: str, *, world_id: str = "w_village_basic") -> dict:
    kwargs = world_requested_kwargs()
    return {
        "v": "1.0",
        "id": event_id,
        "seq": seq,
        "ts": "2026-09-29T09:30:00.000Z",
        "world_id": world_id,
        "run_id": "r_test_1",
        "level": None,
        "district": None,
        "item": None,
        "severity": "info",
        "credits": 0,
        "cause": None,
        "vis": "all",
        "authz": None,
        "trace": {
            "model_role": None,
            "profile": None,
            "tokens_in": None,
            "tokens_out": None,
            "tool": None,
            "latency_ms": None,
            "archive_ref": None,
        },
        **kwargs,
    }


def test_D_11_append_rejects_an_event_whose_world_id_belongs_to_another_world_EV_10(writer_and_store) -> None:
    """security-reviewer's second finding: `append()` must not accept an event stamped with some
    other world's world_id just because seq/id/cause otherwise line up."""
    writer, store = writer_and_store
    with pytest.raises(EventRejected) as excinfo:
        writer.append(_built_event(1, sequential_ulid(9201), world_id="w_someone_elses_world"))
    assert any(p.startswith("EV-10") for p in excinfo.value.problems), excinfo.value.problems
    assert store.read_events("org_demo", "w_village_basic") == []


def test_D_11_append_accepts_an_event_whose_world_id_matches_this_world(writer_and_store) -> None:
    writer, store = writer_and_store
    written = writer.append(_built_event(1, sequential_ulid(9202)))
    assert written["seq"] == 1
    assert store.read_events("org_demo", "w_village_basic") != []
