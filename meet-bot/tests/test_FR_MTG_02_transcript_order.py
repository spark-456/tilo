from types import SimpleNamespace

from bot.cloud_worker import transcript_from_items


def test_FR_MTG_02_ingestion_orders_completed_captions_by_offset_without_mutating_source():
    items = [
        SimpleNamespace(speaker="Slow speaker", text="Earlier speech finalized later.", t=1.25),
        SimpleNamespace(speaker="Fast speaker", text="Earlier finalized first.", t=0.5),
        SimpleNamespace(speaker="Slow speaker", text="Repeated speech.", t=2.0),
        SimpleNamespace(speaker="Slow speaker", text="Repeated speech.", t=3.0),
    ]
    original = list(items)
    rows = transcript_from_items("mt_demo", items)["utterances"]
    assert [row["t_ms"] for row in rows] == [500, 1250, 2000, 3000]
    assert [row["id"] for row in rows] == ["u0001", "u0002", "u0003", "u0004"]
    assert [row["text"] for row in rows] == [items[i].text for i in (1, 0, 2, 3)]
    assert items == original


def test_FR_MTG_02_equal_offsets_keep_capture_order_and_blank_rows_get_no_id():
    items = [
        SimpleNamespace(speaker="A", text="first", t=1),
        SimpleNamespace(speaker="Empty", text=" \n ", t=0),
        SimpleNamespace(speaker="B", text="second", t=1),
    ]
    rows = transcript_from_items("mt_demo", iter(items))["utterances"]
    assert [(row["id"], row["speaker"], row["t_ms"]) for row in rows] == [
        ("u0001", "A", 1000),
        ("u0002", "B", 1000),
    ]
