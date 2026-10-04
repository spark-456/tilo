"""FR-MEM-03 with FR-MTR-06: a replayed Pub/Sub message must not inflate "credits saved".

PRD 13.2 (ledger deduplicated by `id`), 14.3 ("Saved = origin_cost - lookup cost"), 14.4 (Credits saved comes from
the events), MT-05 (`credits_saved` is the sum over accepted reuses). The meter reads the ledger's events, so a
duplicate row would double-count a saving.
"""

from __future__ import annotations

import math

from _memory_lib import make_event, message_for
from tilo_memory.ledger import EventLedger, InMemoryLedgerTable
from tilo_metering.savings import credits_saved


def test_FR_MEM_03_FR_MTR_06_replayed_hits_do_not_double_count_saved_credits():
    table = InMemoryLedgerTable()
    ledger = EventLedger(table)
    hits = [make_event(1, origin_cost=6, lookup_cost=0.5), make_event(2, origin_cost=10, lookup_cost=1)]
    for round_no in range(3):  # the same two events delivered three times
        for event in hits:
            ledger.ingest(message_for(event, f"m-{round_no}-{event['seq']}"))
    assert len(table.rows()) == 2
    assert math.isclose(credits_saved(ledger.events("w_alpha")), (6 - 0.5) + (10 - 1), abs_tol=1e-9)
