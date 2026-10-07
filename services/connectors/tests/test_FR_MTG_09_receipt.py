"""FR-MTG-09 (receipt): `HostReceipt` and `InMemoryReceiptStore`, the dev and test `ReceiptStore`.
API_FR_MTG_09.md "`HostReceipt`", "`ReceiptStore`": the receipt holds Google's event id and ids of Tilo's own
records, never a link, an address, a title or a time (FR-MTG-01: the link is stored nowhere).

Every test fails today with ModuleNotFoundError: tilo_connectors.meeting_host.
"""

from __future__ import annotations

import dataclasses
import re
import threading

import pytest
from _meeting_host_lib import (
    MEETING_ID,
    OWNER,
    WORLD,
    errs,
    mh,
    no_network_and_no_live,  # noqa: F401 - autouse guard
)
from _oauth_lib import _validator

DRAFT_REF = {"artifact_id": "art_meeting_event", "version": 3}
EVENT_REF = "0123456789abcdef0123456789abcdef"
OUTBOX_A = "01JB5VQ0000000000000009801"
OUTBOX_B = "01JB5VQ0000000000000009802"


def receipt(**over):
    values = {
        "world_id": WORLD,
        "outbox_id": OUTBOX_A,
        "meeting_id": MEETING_ID,
        "owner": OWNER,
        "draft": dict(DRAFT_REF),
        "event_ref": EVENT_REF,
        "conference": "success",
    }
    values.update(over)
    return mh().HostReceipt(**values)


def test_FR_MTG_09_receipt_holds_exactly_the_seven_pinned_fields_ids_and_the_event_id():
    names = [f.name for f in dataclasses.fields(mh().HostReceipt)]

    assert names == ["world_id", "outbox_id", "meeting_id", "owner", "draft", "event_ref", "conference"]
    assert dataclasses.is_dataclass(mh().HostReceipt) and mh().HostReceipt.__dataclass_params__.frozen


def test_FR_MTG_09_receipt_is_frozen_and_its_repr_names_no_title_address_link_or_time():
    r = receipt()

    with pytest.raises(dataclasses.FrozenInstanceError):
        r.event_ref = "x"  # type: ignore[misc]
    shown = repr(r)
    for hidden in ("@", "http", "meet.google.com", "Q4", "2026-10-06T0"):
        assert hidden not in shown, hidden


def test_FR_MTG_09_in_memory_store_put_returns_an_artifact_ref_without_a_label():
    store = mh().InMemoryReceiptStore()

    ref = store.put(receipt())

    assert set(ref) == {"artifact_id", "version"}, "a pinned ref, no label"
    assert isinstance(ref["version"], int) and ref["version"] >= 1
    assert re.fullmatch(r"art_[0-9A-Za-z_]{1,48}", ref["artifact_id"])
    validator = _validator({"$ref": "https://contracts.tilo.example/common.schema.json#/$defs/artifact_ref"})
    assert [e.message for e in validator.iter_errors(ref)] == []


def test_FR_MTG_09_the_same_receipt_under_the_same_key_returns_the_same_ref_and_is_stored_once():
    store = mh().InMemoryReceiptStore()

    first = store.put(receipt())
    second = store.put(receipt())

    assert first == second
    assert list(store.receipts) == [receipt()], "`.receipts` lists what it stored, once"


def test_FR_MTG_09_a_different_receipt_under_the_same_world_and_outbox_id_is_refused():
    store = mh().InMemoryReceiptStore()
    store.put(receipt())

    for other in (
        receipt(event_ref="f" * 32),
        receipt(conference="failure"),
        receipt(draft={"artifact_id": "art_meeting_event", "version": 4}),
        receipt(meeting_id="mt_other"),
    ):
        with pytest.raises(errs().SideEffectRefused):
            store.put(other)

    assert list(store.receipts) == [receipt()], "the first receipt stands"


def test_FR_MTG_09_another_outbox_entry_or_world_is_another_receipt_with_another_ref():
    store = mh().InMemoryReceiptStore()

    first = store.put(receipt())
    second = store.put(receipt(outbox_id=OUTBOX_B))
    third = store.put(receipt(world_id="w_other_world"))

    assert len({tuple(first.items()), tuple(second.items()), tuple(third.items())}) == 3
    assert len(store.receipts) == 3


def test_FR_MTG_09_get_finds_a_meetings_receipt_by_world_and_meeting_and_nothing_across_worlds():
    store = mh().InMemoryReceiptStore()
    assert store.get(WORLD, MEETING_ID) is None
    stored = receipt()
    store.put(stored)

    assert store.get(WORLD, MEETING_ID) == stored
    assert store.get("w_other_world", MEETING_ID) is None, "scoped by the world"
    assert store.get(WORLD, "mt_other") is None


def test_FR_MTG_09_concurrent_puts_of_one_receipt_store_it_once():
    store = mh().InMemoryReceiptStore()
    refs: list[dict] = []
    barrier = threading.Barrier(8)

    def worker() -> None:
        barrier.wait()
        refs.append(store.put(receipt()))

    threads = [threading.Thread(target=worker) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert len(store.receipts) == 1
    assert all(r == refs[0] for r in refs)


def test_FR_MTG_09_the_receipt_store_protocol_is_part_of_the_public_module():
    assert hasattr(mh(), "ReceiptStore") and hasattr(mh(), "InMemoryReceiptStore")
    for method in ("put", "get"):
        assert callable(getattr(mh().InMemoryReceiptStore, method))
