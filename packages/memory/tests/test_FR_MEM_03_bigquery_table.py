"""FR-MEM-03: the BigQuery table adapter behind the ledger's table protocol, against a mock client only (no cloud)."""

from __future__ import annotations

import pytest
from _memory_lib import make_event, message_for
from tilo_memory.ledger import COLUMNS, BigQueryLedgerTable, EventLedger

TABLE = "demo-tilo.tilo_ledger.events"


class MockClient:
    """Emulates insert-if-absent keyed on the `id` parameter and records every statement sent."""

    def __init__(self) -> None:
        self.stored: dict[str, dict] = {}
        self.statements: list[tuple[str, dict]] = []
        self.vanish = False  # the row is reported present by the DML but not found by the lookup

    def run_dml(self, sql, params):
        self.statements.append((sql, dict(params)))
        if self.vanish or params["id"] in self.stored:
            return 0
        self.stored[params["id"]] = dict(params)
        return 1

    def query(self, sql, params):
        self.statements.append((sql, dict(params)))
        typed = {"seq": int, "credits": float}  # BigQuery returns INT64 and FLOAT64 typed, parameters are strings
        rows = [
            {k: typed[k](v) if k in typed and v is not None else v for k, v in r.items()} for r in self.stored.values()
        ]
        return [r for r in rows if "id" not in params or r["id"] == params["id"]]


def test_FR_MEM_03_bigquery_table_inserts_once_and_reports_duplicates():
    client = MockClient()
    ledger = EventLedger(BigQueryLedgerTable(client, TABLE))
    event = make_event(1)
    assert ledger.ingest(message_for(event, "m-1")).status == "inserted"
    assert ledger.ingest(message_for(event, "m-2")).status == "duplicate"
    forged = make_event(1)
    forged["summary"] = "Rewritten."
    assert ledger.ingest(message_for(forged, "m-3")).status == "conflict"
    assert len(client.stored) == 1
    assert ledger.events("w_alpha") == [event]


def test_FR_MEM_03_bigquery_insert_is_one_guarded_statement_with_parameters_only():
    client = MockClient()
    event = make_event(1)
    event["summary"] = "x'); DROP TABLE t; --"
    EventLedger(BigQueryLedgerTable(client, TABLE)).ingest(message_for(event, "m-1"))
    sql, params = client.statements[0]
    assert sql.startswith("INSERT INTO") and "NOT EXISTS" in sql and "WHERE id = @id" in sql
    assert "DROP TABLE" not in sql and event["id"] not in sql  # values travel as parameters
    assert set(params) == set(COLUMNS)
    assert not any(w in sql.upper() for w in (" UPDATE ", "DELETE ", "MERGE "))


@pytest.mark.parametrize("table", ["", "a b", "t`; DROP TABLE x; --", "a/b"])
def test_FR_MEM_03_bigquery_table_id_is_validated_before_it_reaches_sql(table):
    with pytest.raises(ValueError):
        BigQueryLedgerTable(MockClient(), table)


def test_FR_MEM_03_bigquery_unconfirmed_insert_raises_so_pubsub_redelivers():
    client = MockClient()
    client.vanish = True
    with pytest.raises(RuntimeError):
        BigQueryLedgerTable(client, TABLE).insert_if_absent({"id": "e1", "seq": 1})
