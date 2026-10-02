"""tilo_connectors.outbox — the only path to a side effect (SEC-03). Full behaviour: tests/API.md."""

from __future__ import annotations

import contextlib
import logging
import math
import uuid
from collections.abc import Callable
from copy import deepcopy
from dataclasses import dataclass
from typing import Any

import tilo_policy

from ._schema import outbox_validator
from ._time import add_seconds, parse_ts
from .errors import MissingGrant, OutboxRefused, ProviderUnavailable, RateLimited, SideEffectRefused
from .registry import RESERVED_CONNECTOR_ID
from .store import InMemoryOutboxStore
from .tokens import ConnectionExpired, InsufficientScope, NotConnected

_ALWAYS_DUE_STATES = ("queued", "sending")  # "scheduled" also once scheduled_at <= now
_LEASE_SECONDS = 30  # generous next to any real adapter/emit call
_LIVE_GRANTS: set[int] = set()  # ids of Grants a send is currently authorised for (SEC-03)
_WAITS_FOR_A_PERSON = (InsufficientScope, NotConnected, ConnectionExpired)  # no provider call: uses no attempt
_log = logging.getLogger(__name__)


@dataclass(frozen=True)
class RetryPolicy:  # between attempts of one entry (#163, FR-AGT-13); defaults: docs/open-questions.md
    max_attempts: int = 8  # failures before the entry ends failed
    max_age_s: float = 86_400  # a failure this long after the entry's first failure ends it failed
    backoff_base_s: float = 30  # doubles with every failure
    max_delay_s: float = 3_600  # caps the backoff and a Retry-After
    ambiguous_delay_s: float = 60  # after ProviderUnavailable, so the earlier-attempt lookup sees a lagging index
    clock_skew_s: float = 2  # a claim waits this long past scheduled_at, in case the dispatcher's clock is fast

    def __post_init__(self) -> None:  # a bad policy could claim inside an undo window or never back off
        for name, value in vars(self).items():
            if isinstance(value, bool) or not isinstance(value, int | float) or not math.isfinite(value) or value < 0:
                raise ValueError(f"RetryPolicy.{name} must be a finite number >= 0")
        if not isinstance(self.max_attempts, int) or self.max_attempts < 1 or self.max_age_s <= 0:
            raise ValueError("RetryPolicy needs an integer max_attempts >= 1 and max_age_s > 0")

    def delay_s(self, exc: Exception, attempts: int) -> float:
        floor = _retry_after_s(exc) if isinstance(exc, RateLimited) else 0.0
        floor = self.ambiguous_delay_s if isinstance(exc, ProviderUnavailable) else floor
        return min(self.max_delay_s, max(floor, self.backoff_base_s * 2 ** min(max(attempts, 1) - 1, 32)))


def _retry_after_s(exc: Exception) -> float:  # anything but a number >= 0 falls back to the backoff
    value = getattr(exc, "retry_after_s", 0)
    if isinstance(value, bool) or not isinstance(value, int | float):
        return 0.0
    try:
        seconds = float(value)
    except OverflowError:
        return math.inf  # capped at max_delay_s
    return seconds if seconds >= 0 else 0.0  # NaN is not >= 0


_IMMEDIATE = RetryPolicy(max_delay_s=0, clock_skew_s=0)  # API.md "Failures": the next tick retries; still bounded


def _transfer_event(entry: dict) -> dict:  # PI-16/17: "out", this id, authz and item unchanged
    return {
        "type": "data.transfer",
        "authz": deepcopy(entry["authz"]),
        "data": {
            "connector": entry["connector"],
            "action_type": entry["action_type"],
            "direction": "out",
            "artifact": deepcopy(entry["item"]),  # independent of entry from the moment it's built
            "outbox_id": entry["id"],
            "risk_tier": entry["risk_tier"],
        },
    }


@dataclass(frozen=True)
class Grant:  # SEC-03: minted only by dispatch_due(); validity is object identity, not fields
    world_id: str
    idempotency_key: str

    def verify(self, idempotency_key: str) -> None:
        if id(self) not in _LIVE_GRANTS or self.idempotency_key != idempotency_key:
            raise MissingGrant("grant not minted by Outbox.dispatch_due() for this exact send")


class Outbox:
    def __init__(
        self,
        store: InMemoryOutboxStore,
        connectors: dict[str, Any],
        emit: Callable[[dict], None],
        clock: Callable[[], str],
        *,
        world_id: str | None = None,
        retry: RetryPolicy | None = None,  # production passes RetryPolicy()
        alert: Callable[[dict], None] | None = None,  # gets alert.raised parts {type, authz, data, world_id}
    ) -> None:
        if any(name.strip() == RESERVED_CONNECTOR_ID for name in connectors):
            raise ValueError(f"connector id {RESERVED_CONNECTOR_ID!r} is reserved and cannot be bound")
        self._store = store
        self._connectors = connectors
        self._emit = emit
        self._clock = clock
        self._world_id = world_id  # set: dispatch and emit only this world's entries and transfers
        self._retry = retry if retry is not None else _IMMEDIATE
        self._alert = alert

    def enqueue(self, entry: dict, evidence: dict) -> dict:
        if errors := sorted(outbox_validator().iter_errors(entry), key=lambda e: list(e.path)):
            raise OutboxRefused(f"OB-05: {errors[0].message}")
        self._check_fresh_state(entry)
        if (existing := self._existing_or_conflict(entry)) is not None:
            return existing
        snapshot = deepcopy(entry)  # before check_entry: a caller mutating entry afterwards changes nothing
        case = {**deepcopy(evidence), "entry": deepcopy(snapshot), "transfer": None, "rule": None}
        if (verdict := tilo_policy.check_entry(case)) is not None:
            raise OutboxRefused(f"{verdict}: entry is not authorised")
        if self._store._insert_if_absent(snapshot):
            return deepcopy(snapshot)
        winner = self._existing_or_conflict(entry)  # lost a race with a concurrent enqueue
        assert winner is not None
        return winner

    def _existing_or_conflict(self, entry: dict) -> dict | None:
        if (existing := self._store.get_by_idempotency_key(entry["world_id"], entry["idempotency_key"])) is not None:
            return existing
        if self._store.get(entry["id"]) is not None:
            raise OutboxRefused(f"id {entry['id']!r} already stored under a different idempotency_key")
        return None

    def _check_fresh_state(self, entry: dict) -> None:  # OB-02: fresh state must match undo_window_s
        undo_window_s = entry["undo_window_s"]
        expected_state = "queued" if undo_window_s == 0 else "scheduled"
        if entry["state"] != expected_state:
            raise OutboxRefused(f"OB-02: a new entry must be {expected_state!r}, got {entry['state']!r}")
        try:
            expected_scheduled_at = add_seconds(entry["created_at"], undo_window_s)
        except (ValueError, TypeError, OverflowError) as exc:
            raise OutboxRefused(f"OB-02: cannot compute scheduled_at: {exc}") from exc
        if entry["scheduled_at"] != expected_scheduled_at:
            raise OutboxRefused(f"OB-02: bad scheduled_at, expected {expected_scheduled_at!r}")

    def cancel(self, outbox_id: str) -> dict:
        if (updated := self._store._cancel(outbox_id)) is None:
            raise OutboxRefused(f"cannot cancel {outbox_id!r}: not 'scheduled'")
        return updated

    def abandon(self, outbox_id: str) -> dict:
        """A run gave up on this unsent entry: "failed", so no later dispatch_due() ever sends it. Refused while a
        live lease may be sending it, or once it is sent, failed or cancelled."""
        if (updated := self._store._abandon(outbox_id, self._clock())) is None:
            raise OutboxRefused(f"cannot abandon {outbox_id!r}: being sent or already settled")
        return updated

    def dispatch_due(self) -> list[dict]:
        now = self._clock()
        ours = [e for e in self._store.all_entries() if self._world_id in (None, e["world_id"])]
        settled = [self._dispatch_one(e["id"]) for e in ours if self._is_due(e, now)]
        self._flush_pending_transfers()
        self._flush_pending_alerts()
        return [entry for entry in settled if entry is not None]

    @staticmethod
    def _is_due(entry: dict, now: str) -> bool:
        state = entry["state"]
        if state in _ALWAYS_DUE_STATES:
            return True
        return state == "scheduled" and entry["scheduled_at"] <= now

    def _dispatch_one(self, outbox_id: str) -> dict | None:
        holder = uuid.uuid4().hex
        skew = self._retry.clock_skew_s
        if (claimed := self._store._claim_for_sending(outbox_id, holder, self._clock(), _LEASE_SECONDS, skew)) is None:
            return None
        name = claimed["connector"]
        adapter = None if name.strip() == RESERVED_CONNECTOR_ID else self._connectors.get(name)
        if adapter is None:  # never a reserved id, even if the map was edited after construction
            return self._store._finalize_claim(outbox_id, holder, "failed")
        grant = Grant(world_id=claimed["world_id"], idempotency_key=claimed["idempotency_key"])
        _LIVE_GRANTS.add(id(grant))
        execute = getattr(adapter, "execute_side_effect", None)  # FR-CON-04/05 adapters; else send_reply
        try:  # copies: a mutating adapter never touches what _transfer_event reads back below
            if execute is not None:
                execute(deepcopy(claimed), grant)
            else:
                adapter.send_reply(
                    claimed["destination"],
                    deepcopy(claimed["item"]),
                    deepcopy(claimed["recipients"]),
                    claimed["idempotency_key"],
                    grant,
                )
        except SideEffectRefused:  # final: it can never succeed as written; nothing is emitted
            return self._store._finalize_claim(outbox_id, holder, "failed")
        except Exception as exc:  # ambiguous or not final: retried later, within the policy's bounds
            try:
                return self._retry_later(claimed, holder, exc)
            except Exception as err:  # a failure to record it never holds the lease or stops the batch
                _log.error("outbox entry %s: recording a failed attempt raised %s", outbox_id, type(err).__name__)
                with contextlib.suppress(Exception):
                    self._store._release_lease("send", outbox_id, holder)
                return None
        except BaseException:  # a process death: release the lease and let it propagate
            self._store._release_lease("send", outbox_id, holder)
            raise
        finally:
            _LIVE_GRANTS.discard(id(grant))
        return self._store._finalize_claim(outbox_id, holder, "sent", _transfer_event(claimed))  # PI-17, atomic

    def _retry_later(self, entry: dict, holder: str, exc: Exception) -> dict | None:
        now, policy = self._clock(), self._retry
        state = self._store.retry_state(entry["id"])
        attempts = state["attempts"] + (0 if isinstance(exc, _WAITS_FOR_A_PERSON) else 1)
        since, ambiguous = state["since"] or now, state["ambiguous"] or isinstance(exc, ProviderUnavailable)
        if attempts < policy.max_attempts and (parse_ts(now) - parse_ts(since)).total_seconds() < policy.max_age_s:
            self._store._defer(entry["id"], holder, attempts, now, policy.delay_s(exc, attempts), ambiguous)
            return None
        if self._alert is None:
            _log.error("outbox entry %s ran out of retries and no alert sink is wired", entry["id"])
        data = {"alert_id": entry["id"], "card_id": None}
        alert = {"type": "alert.raised", "authz": None, "data": data, "world_id": entry["world_id"]}
        if ambiguous:  # it may have been sent: never failed; each later try re-runs the earlier-attempt lookup
            self._store._defer(entry["id"], holder, attempts, now, policy.max_delay_s, True, alert)
            return None
        return self._store._finalize_claim(entry["id"], holder, "failed", alert=alert)

    def _flush_pending_alerts(self) -> None:  # FR-AGT-13: an entry that ran out of retries never stops silently
        if self._alert is None:
            return
        for outbox_id, part in self._store._pending_alerts_of(self._world_id):
            try:
                self._alert(part)
            except Exception:
                continue
            self._store._discard_pending_alert(outbox_id)

    def _flush_pending_transfers(self) -> None:  # only emit path, oldest-first per world_id
        blocked_worlds: set[str] = set()
        while True:
            holder = uuid.uuid4().hex
            claim = self._store._claim_oldest_pending_transfer(
                holder, self._clock(), _LEASE_SECONDS, exclude=frozenset(blocked_worlds), only=self._world_id
            )
            if claim is None:
                return
            outbox_id, world_id, transfer = claim
            try:
                self._emit(transfer)
            except Exception:
                self._store._release_lease("transfer", outbox_id, holder)
                blocked_worlds.add(world_id)
                continue
            self._store._discard_pending_transfer(outbox_id, holder)
