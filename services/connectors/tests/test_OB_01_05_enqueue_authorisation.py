"""SEC-03 / OB-01 / OB-05 (PRD 10.1, 10.3, 10.4, 11.4, 16.4 SEC-03 row): the outbox is the only
path to a side effect, and Outbox.enqueue writes an entry only once
`tilo_policy.check_entry` says it is authorised, reaching the same valid/invalid verdict as
each crossref fixture's own `rule` field. Parametrized over every file under
contracts/fixtures/outbox/crossref/{valid,invalid}/ so a new fixture is covered automatically,
the same pattern packages/policy/tests/test_FR_WLD_03_PI_06_check_entry_crossref.py uses for
`tilo_policy.check_entry` itself — this is the outbox's own half: that enqueue actually enforces
the verdict, not just that check_entry computes it.
"""

from __future__ import annotations

import pytest
import tilo_connectors
from _connectors_lib import ManualClock, evidence_from_case
from tilo_connectors.fakes import FakeGmail


def make_outbox(emitted: list[dict], clock: ManualClock | None = None):
    """Returns (outbox, gmail) so a test can assert on gmail.sent."""
    gmail = FakeGmail()
    store = tilo_connectors.InMemoryOutboxStore()
    connectors = {"gmail": gmail, "google_drive": FakeGmail()}
    outbox = tilo_connectors.Outbox(store, connectors, emitted.append, clock or ManualClock("2026-09-29T09:00:00.000Z"))
    return outbox, gmail


def test_OB_01_every_valid_crossref_case_is_present(crossref_valid_cases):
    assert crossref_valid_cases, "contracts/fixtures/outbox/crossref/valid/ must hold at least one case"


def test_OB_01_every_invalid_crossref_case_is_present(crossref_invalid_cases):
    assert crossref_invalid_cases, "contracts/fixtures/outbox/crossref/invalid/ must hold at least one case"
    for name, case in crossref_invalid_cases:
        assert case["rule"] in ("OB-01", "OB-05"), f"{name}: unexpected rule {case['rule']!r}"


def test_OB_01_enqueue_accepts_every_authorised_entry(crossref_valid_cases):
    """Every contracts/fixtures/outbox/crossref/valid/ case: enqueue writes the entry unchanged
    and raises nothing."""
    for name, case in crossref_valid_cases:
        outbox, _gmail = make_outbox([])
        stored = outbox.enqueue(case["entry"], evidence_from_case(case))
        assert stored == case["entry"], name


# These two cases break PI-16 / PI-17 only in the data.transfer a sent entry emitted; the entry
# itself is authorised. enqueue() never receives a transfer (the outbox emits it, deriving it from
# the entry in dispatch_due()), so they are covered by test_PI_14_16_17_data_transfer_emission.py.
TRANSFER_ONLY_CASES = {"ob01_transfer_stamped_other_than_entry.json", "ob05_transfer_sent_other_version.json"}


def test_OB_01_enqueue_refuses_every_unauthorised_entry(crossref_invalid_cases):
    """Every contracts/fixtures/outbox/crossref/invalid/ case (OB-01 or OB-05 broken) except the
    transfer-only ones: enqueue raises OutboxRefused and writes nothing (proven by dispatch_due()
    sending nothing after)."""
    assert TRANSFER_ONLY_CASES <= {name for name, _ in crossref_invalid_cases}
    for name, case in crossref_invalid_cases:
        if name in TRANSFER_ONLY_CASES:
            continue
        emitted: list[dict] = []
        outbox, _gmail = make_outbox(emitted)
        with pytest.raises(tilo_connectors.OutboxRefused):
            outbox.enqueue(case["entry"], evidence_from_case(case))
        # Nothing unauthorised is written (SEC-03): a later dispatch_due() has nothing to send.
        assert outbox.dispatch_due() == [], f"{name}: a refused entry must not be dispatchable"
        assert emitted == [], f"{name}: a refused entry must emit nothing"


@pytest.mark.parametrize(
    "name",
    [
        "gate_reply_sent_in_village_basic.json",
        "gate_t3_reply_approved_by_assigned_approver_with_pin.json",
        "policy_l3_status_update_waiting.json",
        "policy_reply_instructed_on_the_web.json",
        "policy_reply_sent_after_undo_window.json",
        "policy_reply_sent_before_revocation.json",
        "policy_reply_waiting_out_undo_window.json",
        "team_lead_save_names_its_file.json",
    ],
)
def test_OB_01_named_valid_case_is_accepted(crossref_valid_cases, name):
    """Every valid/ file present today, named explicitly so a file removed by accident fails
    loudly instead of shrinking the parametrized set quietly (mirrors packages/policy's own
    test_FR_WLD_03_PI_06_named_valid_case_passes)."""
    by_name = dict(crossref_valid_cases)
    assert name in by_name, f"{name} is missing from contracts/fixtures/outbox/crossref/valid/"
    case = by_name[name]
    outbox, _gmail = make_outbox([])
    stored = outbox.enqueue(case["entry"], evidence_from_case(case))
    assert stored["id"] == case["entry"]["id"]


def test_OB_05_enqueue_refuses_entry_that_fails_outbox_schema(gate_case_factory):
    """A structurally invalid entry (bad idempotency_key pattern) is refused before any
    authorisation check runs — OB-05 read with OB-01: nothing malformed is written either."""
    case = gate_case_factory(idempotency_key="")  # violates outbox.schema.json's pattern
    outbox, _gmail = make_outbox([])
    with pytest.raises(tilo_connectors.OutboxRefused):
        outbox.enqueue(case["entry"], evidence_from_case(case))


def test_OB_03_enqueue_with_an_already_stored_idempotency_key_writes_nothing_new(gate_case_factory):
    """Retrying the enqueue step itself (not just dispatch) with the same world_id and
    idempotency_key returns the already-stored entry and does not create a second one — proven
    by dispatch_due() only ever sending once (FR-AGT-11's "retrying a send step never produces
    a second email" applies one layer up too)."""
    case = gate_case_factory(undo_window_s=0)
    emitted: list[dict] = []
    outbox, gmail = make_outbox(emitted)
    first = outbox.enqueue(case["entry"], evidence_from_case(case))
    second = outbox.enqueue(case["entry"], evidence_from_case(case))
    assert first == second
    sent = outbox.dispatch_due()
    assert len(sent) == 1
    assert len(gmail.sent) == 1
