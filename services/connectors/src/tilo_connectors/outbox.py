"""tilo_connectors.outbox — the only path to a side effect (SEC-03, PRD 12.1). Outbox.enqueue
writes an entry only once it is schema-valid (OB-05), its state/scheduled_at correlation holds
(OB-02), and tilo_policy.check_entry says it is authorised (OB-01/OB-05); a retry with the same
world_id + idempotency_key is a no-op (OB-03). Outbox.dispatch_due() sends every entry currently
due, minting a Grant no caller outside this module can construct, so a connector adapter's
side-effect method can only run from here (SEC-03). Public surface: tests/API.md.
"""

from __future__ import annotations

import threading
from collections.abc import Callable
from copy import deepcopy
from dataclasses import dataclass
from typing import Any

import tilo_policy

from ._schema import outbox_validator
from ._time import add_seconds
from .errors import OutboxRefused
from .store import InMemoryOutboxStore

_DUE_STATES = ("queued", "scheduled", "failed")


def _transfer_event(entry: dict) -> dict:
    """The one data.transfer a sent entry emits (PI-16/17): direction "out", this entry's id,
    authz and pinned item, unchanged. Shared by dispatch_due() (the real emission) and
    enqueue()'s check for an entry that already arrives "sent" (docs/open-questions.md BQ-33:
    a real caller never presents enqueue() with an already-sent entry, so this only matters for
    a full-lifecycle fixture reused as enqueue input)."""
    return {
        "type": "data.transfer",
        "authz": entry["authz"],
        "data": {
            "connector": entry["connector"],
            "action_type": entry["action_type"],
            "direction": "out",
            "artifact": entry["item"],
            "outbox_id": entry["id"],
            "risk_tier": entry["risk_tier"],
        },
    }


@dataclass(frozen=True)
class Grant:
    """SEC-03: the capability a side-effect method requires. Only Outbox.dispatch_due() mints
    one, so a caller outside this module has no supported way to construct a valid Grant."""

    outbox_id: str
    idempotency_key: str


class Outbox:
    def __init__(
        self,
        store: InMemoryOutboxStore,
        connectors: dict[str, Any],
        emit: Callable[[dict], None],
        clock: Callable[[], str],
    ) -> None:
        self._store = store
        self._connectors = connectors
        self._emit = emit
        self._clock = clock
        self._lock = threading.Lock()

    # -- enqueue -----------------------------------------------------------------------------

    def enqueue(self, entry: dict, evidence: dict) -> dict:
        with self._lock:
            errors = sorted(outbox_validator().iter_errors(entry), key=lambda e: list(e.path))
            if errors:
                raise OutboxRefused(f"OB-05: entry fails outbox.schema.json: {errors[0].message}")

            self._check_state_schedule_correlation(entry)

            existing = self._store.get_by_idempotency_key(entry["world_id"], entry["idempotency_key"])
            if existing is not None:
                return existing

            # tests/API.md: transfer is None (nothing sent yet). An entry that already arrives
            # "sent" is checked against what dispatching it would emit instead, since a bare
            # None would misread it as never sent (BQ-33).
            transfer = _transfer_event(entry) if entry["state"] == "sent" else None
            case = {**deepcopy(evidence), "entry": deepcopy(entry), "transfer": transfer, "rule": None}
            verdict = tilo_policy.check_entry(case)
            if verdict is not None:
                raise OutboxRefused(f"{verdict}: entry is not authorised")

            self._store.put(entry)
            return deepcopy(entry)

    def _check_state_schedule_correlation(self, entry: dict) -> None:
        """OB-02: scheduled_at == created_at + undo_window_s, always; while state is "queued" or
        "scheduled" (the only two enqueue is meant to introduce) it must also match undo_window_s
        ("queued" for none, else "scheduled"). Neither the schema nor check_entry cover this
        (tests/API.md "OB-02, resolved"), so enqueue enforces it itself."""
        undo_window_s = entry["undo_window_s"]
        try:
            expected_scheduled_at = add_seconds(entry["created_at"], undo_window_s)
        except (ValueError, TypeError) as exc:
            raise OutboxRefused(f"OB-02: cannot compute scheduled_at: {exc}") from exc
        if entry["scheduled_at"] != expected_scheduled_at:
            raise OutboxRefused(
                f"OB-02: scheduled_at must equal created_at + undo_window_s (expected {expected_scheduled_at!r})"
            )
        state = entry["state"]
        expected_state = "queued" if undo_window_s == 0 else "scheduled"
        if state in ("queued", "scheduled") and state != expected_state:
            raise OutboxRefused(f"OB-02: state {state!r} does not match undo_window_s (expected {expected_state!r})")

    # -- cancel --------------------------------------------------------------------------------

    def cancel(self, outbox_id: str) -> dict:
        with self._lock:
            entry = self._store.get(outbox_id)
            if entry is None or entry["state"] != "scheduled":
                raise OutboxRefused(f"cannot cancel {outbox_id!r}: only a 'scheduled' entry can be cancelled")
            entry["state"] = "cancelled"
            self._store.put(entry)
            return deepcopy(entry)

    # -- dispatch ------------------------------------------------------------------------------

    def dispatch_due(self) -> list[dict]:
        with self._lock:
            now = self._clock()
            due = [entry for entry in self._store.all_entries() if self._is_due(entry, now)]
            return [self._dispatch_one(entry) for entry in due]

    @staticmethod
    def _is_due(entry: dict, now: str) -> bool:
        state = entry["state"]
        if state not in _DUE_STATES:
            return False
        if state == "scheduled":
            return entry["scheduled_at"] <= now
        return True  # "queued" is always due; "failed" is retried on every dispatch_due call

    def _dispatch_one(self, entry: dict) -> dict:
        entry["state"] = "sending"
        self._store.put(entry)

        adapter = self._connectors[entry["connector"]]
        grant = Grant(outbox_id=entry["id"], idempotency_key=entry["idempotency_key"])
        try:
            adapter.send_reply(
                entry["destination"], entry["item"], entry["recipients"], entry["idempotency_key"], grant
            )
        except Exception:
            entry["state"] = "failed"
            self._store.put(entry)
            return deepcopy(entry)

        entry["state"] = "sent"
        self._store.put(entry)
        self._emit(_transfer_event(entry))
        return deepcopy(entry)
