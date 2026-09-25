"""D-11 / PRD 9.3, contracts/event.rules.md: `contracts/fixtures/streams/village-basic.jsonl`
is "the ... harness skeleton's (P0-09) input" -- it must append cleanly, in order, through a
`WorldWriter` over `contracts/fixtures/layout/valid/village_basic.json`, ending at seq 44 with
every event stored and readable back unchanged.
"""

from __future__ import annotations

from conftest import make_memory_writer


def test_D_11_village_basic_stream_appends_cleanly_through_a_world_writer(
    village_basic_layout: dict, village_basic_stream: list[dict]
) -> None:
    writer, store = make_memory_writer(village_basic_layout, world_id="w_village_basic", run_id="r_village_basic_1")

    for event in village_basic_stream:
        result = writer.append(event)
        assert result["seq"] == event["seq"]
        assert result["id"] == event["id"]

    stored = store.read_events("org_demo", "w_village_basic")
    assert len(stored) == len(village_basic_stream) == 44
    assert [e["seq"] for e in stored] == list(range(1, 45))
    assert stored[-1]["type"] == "world.completed"
    assert stored[0]["type"] == "world.requested"


def test_D_11_village_basic_stream_events_round_trip_unchanged(
    village_basic_layout: dict, village_basic_stream: list[dict]
) -> None:
    writer, store = make_memory_writer(village_basic_layout, world_id="w_village_basic", run_id="r_village_basic_1")
    for event in village_basic_stream:
        writer.append(event)

    stored_by_seq = {e["seq"]: e for e in store.read_events("org_demo", "w_village_basic")}
    for event in village_basic_stream:
        assert stored_by_seq[event["seq"]] == event, f"seq {event['seq']} must round-trip unchanged"
