"""FR-MEM-09 builder-added tests for edges the acceptance tests leave open: unreadable stores, hand-built requests,
the BigQuery delete statement, ledger rows with an unreadable timestamp, and a purge that stops before deleting."""

from __future__ import annotations

import io
import json
from datetime import timedelta
from types import SimpleNamespace

import pytest
from _memory_lib import NOW, FakeStore, Rec, ago, build_registry, make_event, message_for
from tilo_memory.erasure import (
    REQUIRED_STORES,
    UNREADABLE,
    ErasureRequest,
    IncompleteRegistry,
    erase_user,
    main,
    request_erasure,
    verify_erasure,
)
from tilo_memory.ledger import BigQueryLedgerTable, EventLedger, InMemoryLedgerTable, LedgerRetentionStore
from tilo_memory.retention import purge_expired

ALICE = "u_alice"
TABLE = "demo-tilo.tilo_ledger.events"


class UnreadableStore(FakeStore):
    def records(self):
        raise OSError("secret store detail alice private text")


def registry_with(store_cls=FakeStore, which=0):
    registry = build_registry(sorted(REQUIRED_STORES))
    for store in registry.values():
        store.add(Rec("run", "a", ago(1), ALICE, payload="alice private text"))
        store.add(Rec("org", "o", ago(1), None))
    name = sorted(REQUIRED_STORES)[which]
    registry[name] = store_cls(registry[name].records())
    return registry, name


def test_FR_MEM_09_an_unreadable_store_is_incomplete_and_reported_without_its_message():
    registry, name = registry_with(UnreadableStore)
    report = erase_user(registry, request_erasure(ALICE, requested_at=NOW), now=NOW)
    assert report.complete is False
    assert report.remaining[name] == UNREADABLE
    assert report.failures == {name: "OSError"}
    assert "alice private text" not in repr(report) and "secret store detail" not in repr(report)
    result = verify_erasure(registry, ALICE)
    assert result.ok is False and any(name in p for p in result.problems)
    assert "secret store detail" not in repr(result)


def test_FR_MEM_09_a_hand_built_request_object_is_refused():
    registry, _ = registry_with()
    forged = SimpleNamespace(user_id=ALICE, requested_at=NOW, deadline=NOW + timedelta(days=30))
    with pytest.raises(ValueError):
        erase_user(registry, forged, now=NOW)  # type: ignore[arg-type]
    with pytest.raises(ValueError):
        ErasureRequest("u_*", NOW)
    assert all("a" in s.ids() for s in registry.values())


def test_FR_MEM_09_a_naive_now_is_refused_before_any_delete():
    registry, _ = registry_with()
    with pytest.raises(ValueError):
        erase_user(registry, request_erasure(ALICE, requested_at=NOW), now=NOW.replace(tzinfo=None))
    assert all(s.delete_calls == [] for s in registry.values())


@pytest.mark.parametrize("bad_id", ["u_", "u_a b", "u_alice\n", "U_alice", "u_" + "a" * 49, "u_é"])
def test_FR_MEM_09_user_ids_must_match_the_contract_pattern_exactly(bad_id):
    with pytest.raises(ValueError):
        request_erasure(bad_id, requested_at=NOW)
    with pytest.raises(ValueError):
        verify_erasure(registry_with()[0], bad_id)


def test_FR_MEM_09_a_registry_entry_that_is_not_a_store_counts_as_missing():
    registry, _ = registry_with()
    registry[sorted(REQUIRED_STORES)[0]] = object()  # type: ignore[assignment]
    with pytest.raises(IncompleteRegistry):
        verify_erasure(registry, ALICE)


def test_FR_MEM_09_cli_without_a_configured_registry_fails_closed_and_echoes_no_input():
    for argv, expected in ((["verify", ALICE], 3), (["verify", "u_*<script>"], 2), ([], 2), (["delete", ALICE], 2)):
        out = io.StringIO()
        assert main(argv, stdout=out) == expected
        assert "<script>" not in out.getvalue() and json.loads(out.getvalue())["ok"] is False


def test_FR_MEM_09_the_module_exposes_no_network_surface():
    import pathlib

    import tilo_memory.erasure as module

    source = pathlib.Path(module.__file__).read_text(encoding="utf-8").lower()
    for word in ("fastapi", "http", "socket", "flask", "starlette"):
        assert word not in source


class DmlClient:
    def __init__(self) -> None:
        self.statements: list[tuple[str, dict]] = []

    def run_dml(self, sql, params):
        self.statements.append((sql, dict(params)))
        return 1

    def query(self, sql, params):
        return []


def test_FR_MEM_09_bigquery_delete_is_one_parameterised_statement_by_event_id():
    client = DmlClient()
    BigQueryLedgerTable(client, TABLE).delete_row("e1'; DROP TABLE x; --")
    ((sql, params),) = client.statements
    assert sql == f"DELETE FROM `{TABLE}` WHERE id = @id"
    assert params == {"id": "e1'; DROP TABLE x; --"}


def test_FR_MEM_09_ledger_row_with_an_unreadable_timestamp_is_kept_by_purge_but_erasable():
    table = InMemoryLedgerTable()
    ledger = EventLedger(table)
    event = make_event(1, world="w_alice_1")
    event["ts"] = "not a time"
    assert ledger.ingest(message_for(event, "m-1")).status == "inserted"
    store = LedgerRetentionStore(table, world_owner={"w_alice_1": ALICE}.get)
    assert purge_expired({"bigquery_ledger": store}, now=NOW) == {"bigquery_ledger": 0}
    registry = build_registry(sorted(REQUIRED_STORES))
    registry["bigquery_ledger"] = store
    assert erase_user(registry, request_erasure(ALICE, requested_at=NOW), now=NOW).complete is True
    assert table.rows() == []


def test_FR_MEM_09_ledger_owner_lookup_returning_junk_means_no_owner():
    table = InMemoryLedgerTable()
    EventLedger(table).ingest(message_for(make_event(1, world="w_x"), "m-1"))
    (record,) = LedgerRetentionStore(table, world_owner=lambda _w: 42).records()  # type: ignore[arg-type,return-value]
    assert record.user_id is None


def test_FR_MEM_09_purge_with_an_unknown_entity_deletes_nothing():
    good, bad = FakeStore([Rec("run", "old", ago(200), None)]), FakeStore([Rec("mystery", "m", ago(1), None)])
    with pytest.raises(ValueError):
        purge_expired({"a": good, "b": bad}, now=NOW)
    assert good.ids() == {"old"} and good.delete_calls == []
