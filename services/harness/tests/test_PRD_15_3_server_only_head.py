"""PRD 15.3 (Firestore layout) + PRD 10.1 ("hidden districts show fog with no names or counts")
+ SEC-07 ("Redacted event views per role: Scoped users never receive hidden names or counts"):
the world's head -- `last_seq`, every scope's `view_seq`, the writer lease (token, writer id,
expiry) -- must not live on `orgs/{org}/worlds/{world}` itself, because Firestore security
rules are naturally scoped per document/collection and a client readable at that path (an Owner
or Team Lead, PRD 10.1) would otherwise see every scope's `view_seq`, including a district they
are not scoped into -- a count leak the PRD 10.1/SEC-07 fog rule forbids. It moves to
`orgs/{org}/worlds/{world}/_head/state`, a path under this world that is not one of PRD 15.3's
named client-readable paths (`events`, `views/{scope}`, `cards`, `checkpoints`) and so is safe
to deny to every client in Firestore security rules (documented in services/harness/CLAUDE.md;
there is no rules file in this repo yet -- SH files the infra issue per the ticket brief).

PRD 15.3 itself names no head document at all (only `events`, `views/{scope}`, `cards`,
`checkpoints`), so `_head/state` is an internal harness implementation path, not a change to
what PRD 15.3 promises a client; nothing here should be read as a contract change.

Resolved ambiguities (CLAUDE.md "apply the PRD's stated default"):
  1. The ticket brief names `last_seq` explicitly as one of the fields that "moves" to
     `_head/state` (not "renames"), so `test_PRD_15_3_head_document_holds_last_seq_after_writes`
     asserts that literal key. If the builder lands a different key for the same concept, that
     one test (not the others in this file) will need updating -- it is intentionally the
     single point of contact with an unspecified name.
  2. `MemoryStore`'s public surface used elsewhere in this suite (`read_events`, `read_view`)
     never exposes a raw "document" -- it has no Firestore-style path to leak from in the first
     place, so there is no MemoryStore equivalent of the world-document-emptiness assertions
     below. Its lease/`WriterBusy`/takeover *behaviour* is already covered store-agnostically by
     test_D_11_writer_lease_single_writer.py; this file only adds the FirestoreStore-specific
     document-placement assertions that file cannot make.

@pytest.mark.emulator: needs Java (Firestore emulator binary) and firebase-tools (pinned root
devDependency, run through `pnpm exec`); excluded from the default suite like other
`emulator`-marked tests here. Run explicitly with `uv run pytest services/harness/tests -m
emulator`.
"""

from __future__ import annotations

import time

import pytest

pytestmark = pytest.mark.emulator

# Names a client-readable orgs/{org}/worlds/{world} document must not carry, whatever it is
# still used for -- covers the concepts the ticket brief names (last_seq, each scope's
# view_seq, the lease token, writer id, expiry) under their plausible spellings.
FORBIDDEN_HEAD_KEYS = {
    "last_seq",
    "view_seq",
    "view_seqs",
    "lease",
    "lease_token",
    "token",
    "writer_id",
    "writer",
    "expiry",
    "expires_at",
    "expires",
}

LEASE_S = 3.0


def _world_doc(client, org_id: str, world_id: str):
    return client.document(f"orgs/{org_id}/worlds/{world_id}").get()


def _head_doc(client, org_id: str, world_id: str):
    return client.document(f"orgs/{org_id}/worlds/{world_id}/_head/state").get()


def test_PRD_15_3_world_document_carries_no_head_fields_after_writes(
    emulator_host: str, village_basic_layout: dict
) -> None:
    from google.cloud import firestore
    from tilo_harness.store import FirestoreStore
    from tilo_harness.writer import WorldWriter

    org_id, world_id = "org_demo", "w_head_placement_1"
    store = FirestoreStore(project_id="demo-tilo")
    writer = WorldWriter(
        store,
        org_id=org_id,
        world_id=world_id,
        run_id="r_head_placement_1",
        layout=village_basic_layout,
        writer_id="writer_1",
        lease_s=30.0,
    )
    writer.open()
    writer.emit(
        type="world.requested",
        actor="u_owner",
        target=world_id,
        summary="You asked Tilo to do some work.",
        data={"title": "Do some work", "channel": "web", "destination": None},
    )

    client = firestore.Client(project="demo-tilo")
    doc = _world_doc(client, org_id, world_id)
    if doc.exists:
        data = doc.to_dict() or {}
        leaked = FORBIDDEN_HEAD_KEYS & set(data.keys())
        assert not leaked, (
            f"PRD 15.3/10.1/SEC-07: orgs/{{org}}/worlds/{{world}} must never carry the world head "
            f"(a client readable here would see other scopes' view_seq and lease detail) -- found "
            f"{leaked} in {data}"
        )
    # doc.exists == False (the harness writes nothing to this path at all) is the preferred,
    # stronger outcome per the ticket brief ("Nothing else is written to the world document by
    # the harness") and passes this assertion trivially.


def test_PRD_15_3_head_document_holds_last_seq_after_writes(emulator_host: str, village_basic_layout: dict) -> None:
    from google.cloud import firestore
    from tilo_harness.store import FirestoreStore
    from tilo_harness.writer import WorldWriter

    org_id, world_id = "org_demo", "w_head_placement_2"
    store = FirestoreStore(project_id="demo-tilo")
    writer = WorldWriter(
        store,
        org_id=org_id,
        world_id=world_id,
        run_id="r_head_placement_2",
        layout=village_basic_layout,
        writer_id="writer_1",
        lease_s=30.0,
    )
    writer.open()
    writer.emit(
        type="world.requested",
        actor="u_owner",
        target=world_id,
        summary="You asked Tilo to do some work.",
        data={"title": "Do some work", "channel": "web", "destination": None},
    )
    writer.emit(
        type="agent.idle",
        actor="A_v1",
        target="B3",
        level="L1",
        district="D1",
        summary="The agent is waiting for work.",
        data={},
    )

    client = firestore.Client(project="demo-tilo")
    head = _head_doc(client, org_id, world_id)
    assert head.exists, "PRD 15.3: the world head must live at orgs/{org}/worlds/{world}/_head/state"
    data = head.to_dict() or {}
    assert data.get("last_seq") == 2, f"PRD 15.3: _head/state.last_seq must track the world's last seq, got {data}"


def test_PRD_15_3_second_writer_still_gets_WriterBusy_through_the_head_path(
    emulator_host: str, village_basic_layout: dict
) -> None:
    from tilo_harness.store import FirestoreStore
    from tilo_harness.writer import WorldWriter, WriterBusy

    org_id, world_id = "org_demo", "w_head_placement_busy"
    store = FirestoreStore(project_id="demo-tilo")

    def make(writer_id: str) -> WorldWriter:
        return WorldWriter(
            store,
            org_id=org_id,
            world_id=world_id,
            run_id="r_head_placement_busy",
            layout=village_basic_layout,
            writer_id=writer_id,
            lease_s=30.0,
        )

    writer1, writer2 = make("writer_1"), make("writer_2")
    writer1.open()
    writer1.emit(
        type="world.requested",
        actor="u_owner",
        target=world_id,
        summary="You asked Tilo to do some work.",
        data={"title": "Do some work", "channel": "web", "destination": None},
    )

    with pytest.raises(WriterBusy):
        writer2.open()

    assert [e["seq"] for e in store.read_events(org_id, world_id)] == [1], (
        "PRD 15.3: the lease re-check must still be effective now that it reads _head/state, not the world document"
    )


def test_PRD_15_3_takeover_after_expiry_continues_at_last_seq_plus_1_through_the_head_path(
    emulator_host: str, village_basic_layout: dict
) -> None:
    from google.cloud import firestore
    from tilo_harness.store import FirestoreStore
    from tilo_harness.writer import WorldWriter

    org_id, world_id = "org_demo", "w_head_placement_takeover"
    store = FirestoreStore(project_id="demo-tilo")

    crashed = WorldWriter(
        store,
        org_id=org_id,
        world_id=world_id,
        run_id="r_head_placement_takeover",
        layout=village_basic_layout,
        writer_id="writer_crashed",
        lease_s=LEASE_S,
    )
    crashed.open()
    crashed.emit(
        type="world.requested",
        actor="u_owner",
        target=world_id,
        summary="You asked Tilo to do some work.",
        data={"title": "Do some work", "channel": "web", "destination": None},
    )
    # crashed "dies" here; its lease at _head/state is left to expire on its own.

    time.sleep(LEASE_S + 1.0)

    successor = WorldWriter(
        store,
        org_id=org_id,
        world_id=world_id,
        run_id="r_head_placement_takeover",
        layout=village_basic_layout,
        writer_id="writer_successor",
        lease_s=LEASE_S,
    )
    successor.open()  # must not raise WriterBusy: the expired lease is read from _head/state
    resumed = successor.emit(
        type="agent.idle",
        actor="A_v1",
        target="B3",
        level="L1",
        district="D1",
        summary="The agent is waiting for work.",
        data={},
    )

    assert resumed["seq"] == 2, "PRD 15.3: takeover through the new head path must continue at last_seq + 1"
    stored = store.read_events(org_id, world_id)
    assert [e["seq"] for e in stored] == [1, 2]
    assert stored[0]["type"] == "world.requested", "PRD 15.3: takeover must never overwrite an existing event"

    client = firestore.Client(project="demo-tilo")
    doc = _world_doc(client, org_id, world_id)
    if doc.exists:
        leaked = FORBIDDEN_HEAD_KEYS & set((doc.to_dict() or {}).keys())
        assert not leaked, (
            f"PRD 15.3: takeover must not fall back to writing the head onto the world document: {leaked}"
        )
