"""`WorldWriter`: the single writer per world (D-11, PRD 9.3, 15.3, 22.2). Every event is
checked against `EventValidator` before it is written; a rejected event raises `EventRejected`
and writes nothing. `WorldWriter` holds a lease on the world (writer id + expiry, from an
injectable clock); a second writer is refused while the lease is live (`WriterBusy`), every
write re-checks the lease inside the same store transaction so a superseded writer cannot write
any more, and after a crash a new writer takes over once the lease expires and continues at
`last_seq + 1` read from the store, never overwriting an existing event.

The lease is keyed on a token generated fresh per `WorldWriter` *instance* (`secrets.token_hex`),
never on the caller-supplied `writer_id` alone: `writer_id` is only a human-readable label, and
two instances can be constructed with the same one (two processes deriving it from the same
`--run`, or a test constructing two writers with the same string). Comparing lease ownership by
that label alone would let a second live instance slip past `open()` with no `WriterBusy`, which
is exactly the D-11 violation this ticket's fix round is closing. `_commit` also re-reads the
store's head inside the transaction and refuses the write unless `head.last_seq == event.seq -
1` and every view's `vseq` matches the head, so a writer acting on stale local state can never
overwrite or skip a seq even if it still (wrongly) believed it held the lease.

`_commit` also re-checks `lease.expires_at` against the clock on every write (not just at
`open()`), and every successful commit renews it to `now + lease_s`: a writer that emits faster
than `lease_s` keeps its lease indefinitely, and a writer that stalls past `lease_s` loses the
right to write as soon as the next commit is attempted, even before a second writer takes over.
Without this, a writer whose lease has lapsed keeps writing past its own TTL, and a healthy
writer that simply runs longer than `lease_s` loses its world out from under it.
"""

from __future__ import annotations

import secrets
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any

from tilo_harness.ids import ORG_ID, RUN_ID, WORLD_ID, check_id
from tilo_harness.validator import EventRejected, EventValidator, WorldState
from tilo_harness.views import redact, scopes_for

# Re-exported for callers written against `tilo_harness.writer.EventRejected` (this module's own
# docstring and the tests predate the ticket brief's public API, which places it at
# `tilo_harness.validator` instead -- see that module). Same class object either way, so
# `isinstance`/`pytest.raises` checks against either import path agree.
__all__ = ["EventRejected", "WorldWriter", "WriterBusy"]

_CROCKFORD = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"
_NULL_TRACE: dict[str, Any] = {
    "model_role": None,
    "profile": None,
    "tokens_in": None,
    "tokens_out": None,
    "tool": None,
    "latency_ms": None,
    "archive_ref": None,
}


class WriterBusy(Exception):
    """Raised when the world's lease is held by another writer."""


def _new_ulid(now: datetime) -> str:
    ms = int(now.timestamp() * 1000) & 0xFFFFFFFFFFFF
    value = (ms << 80) | int.from_bytes(secrets.token_bytes(10), "big")
    return "".join(_CROCKFORD[(value >> (i * 5)) & 0x1F] for i in range(25, -1, -1))


def _format_ts(now: datetime) -> str:
    return now.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%S.") + f"{now.microsecond // 1000:03d}Z"


class WorldWriter:
    def __init__(
        self,
        store: Any,
        *,
        org_id: str,
        world_id: str,
        run_id: str,
        layout: dict[str, Any],
        writer_id: str,
        lease_s: float = 30.0,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        # Reject any org_id/world_id/run_id that does not match common.schema.json's pattern
        # *before* any store call (open() builds Firestore paths from these ids). Each pattern
        # excludes "/", so a world_id such as "w_victim/events/00000001" can never reach a
        # path-building f-string -- see ids.py.
        check_id(org_id, ORG_ID, label="org_id")
        check_id(world_id, WORLD_ID, label="world_id")
        check_id(run_id, RUN_ID, label="run_id")

        self._store = store
        self._org_id = org_id
        self._world_id = world_id
        self._run_id = run_id
        self._layout = layout
        self.writer_id = writer_id
        self._lease_s = lease_s
        self._clock = clock or (lambda: datetime.now(UTC))
        # Unique per WorldWriter instance, independent of the caller-supplied `writer_id` label
        # (see the module docstring): this is what lease ownership is actually checked against.
        self._instance_token = secrets.token_hex(16)
        self._validator = EventValidator.from_repo()
        self._scopes = scopes_for(layout)
        self._state = WorldState(layout)
        self._state.world_id = world_id
        self._view_ids: dict[str, set[str]] = {}
        self._view_seq: dict[str, int] = {}

    def open(self) -> None:
        """Acquires the world's lease and loads the head: last seq, and every event id already
        in the full stream and each view, so a takeover continues at `last_seq + 1` and never
        re-derives `cause` visibility from scratch."""
        now = self._clock()

        def _acquire(head: dict[str, Any]) -> tuple[dict[str, Any], None, list[Any]]:
            lease = head["lease"]
            if lease is not None and lease["token"] != self._instance_token and lease["expires_at"] > now:
                raise WriterBusy(f"world {self._world_id!r} is leased to {lease['writer_id']!r}")
            new_head = dict(head)
            new_head["lease"] = {
                "writer_id": self.writer_id,
                "token": self._instance_token,
                "expires_at": now + timedelta(seconds=self._lease_s),
            }
            return new_head, None, []

        self._store.transact(self._org_id, self._world_id, _acquire)

        self._state = WorldState(self._layout)
        self._state.world_id = self._world_id
        for event in self._store.read_events(self._org_id, self._world_id):
            self._state.observe(event)
        self._view_ids = {
            scope: {e["id"] for e in self._store.read_view(self._org_id, self._world_id, scope)}
            for scope in self._scopes
        }
        self._view_seq = {scope: len(ids) for scope, ids in self._view_ids.items()}

    def close(self) -> None:
        """Releases the lease, if it is still this writer's."""

        def _release(head: dict[str, Any]) -> tuple[dict[str, Any], None, list[Any]]:
            lease = head["lease"]
            if lease is not None and lease["token"] == self._instance_token:
                return dict(head, lease=None), None, []
            return head, None, []

        self._store.transact(self._org_id, self._world_id, _release)

    def emit(
        self,
        *,
        type: str,
        actor: str,
        target: str,
        summary: str,
        data: dict[str, Any],
        level: str | None = None,
        district: str | None = None,
        item: dict[str, Any] | None = None,
        severity: str | None = None,
        credits: float = 0,
        cause: str | None = None,
        vis: str | list[str] = "all",
        authz: dict[str, Any] | None = None,
        trace: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        now = self._clock()
        entry = self._validator.registry_types.get(type)
        event = {
            "v": "1.0",
            "id": _new_ulid(now),
            "seq": self._state.last_seq + 1,
            "ts": _format_ts(now),
            "world_id": self._world_id,
            "run_id": self._run_id,
            "type": type,
            "actor": actor,
            "target": target,
            "level": level,
            "district": district,
            "item": item,
            "severity": severity if severity is not None else (entry["default_severity"] if entry else "info"),
            "credits": credits,
            "summary": summary,
            "cause": cause,
            "vis": vis,
            "authz": authz,
            "data": data,
            "trace": trace if trace is not None else dict(_NULL_TRACE),
        }
        return self._write(event)

    def append(self, event: dict[str, Any]) -> dict[str, Any]:
        """Writes a pre-built event unchanged (the replay path): `seq` must be exactly
        `last_seq + 1`, `id` must be unused, `cause` must be null or an earlier event of this
        world -- EventValidator's EV-10/EV-11 catch each case."""
        return self._write(dict(event))

    def _write(self, event: dict[str, Any]) -> dict[str, Any]:
        problems = self._validator.problems(event, self._state)
        if problems:
            raise EventRejected(problems)

        view_writes: list[tuple[str, dict[str, Any]]] = []
        new_view_seq = dict(self._view_seq)
        for scope in self._scopes:
            vseq = self._view_seq.get(scope, 0) + 1
            copy = redact(event, scope, vseq, self._view_ids.get(scope, set()))
            if copy is not None:
                view_writes.append((scope, copy))
                new_view_seq[scope] = vseq

        def _commit(head: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any], list[tuple[str, dict[str, Any]]]]:
            now = self._clock()
            lease = head["lease"]
            if lease is None or lease["token"] != self._instance_token:
                raise WriterBusy(f"world {self._world_id!r} is no longer leased to {self.writer_id!r}")
            # The token check above is necessary but not sufficient -- a writer's lease can
            # expire (another writer has not taken over yet, but is now free to) while this
            # instance's token is still the one recorded on the head. Without this check, a
            # writer whose lease has lapsed keeps writing past its own TTL. Re-derive "now" from
            # the injectable clock at commit time (not from `open()`'s stale reading), since a
            # long-running writer emits many events after a single `open()`.
            if lease["expires_at"] <= now:
                raise WriterBusy(
                    f"world {self._world_id!r} lease for {self.writer_id!r} expired at "
                    f"{lease['expires_at']!r} (now {now!r})"
                )
            # Belt-and-suspenders on top of the lease check: even if this instance still (wrongly)
            # believes it holds the lease, refuse to write unless the store's actual head is still
            # exactly where this writer's local state thinks it is, so a write can never overwrite
            # or skip a seq/vseq that another writer already committed.
            if head["last_seq"] != event["seq"] - 1:
                raise WriterBusy(
                    f"world {self._world_id!r} head has moved to last_seq={head['last_seq']!r}, "
                    f"expected {event['seq'] - 1!r} before writing seq {event['seq']!r}"
                )
            head_view_seq = head["view_seq"]
            for scope, doc in view_writes:
                if doc["seq"] != head_view_seq.get(scope, 0) + 1:
                    raise WriterBusy(
                        f"world {self._world_id!r} view {scope!r} head has moved to "
                        f"vseq={head_view_seq.get(scope, 0)!r}, expected {doc['seq'] - 1!r}"
                    )
            # Every successful commit renews the lease from *this* commit's "now", not from
            # `open()`'s: a writer that keeps emitting faster than `lease_s` must never lose its
            # own lease out from under itself, and a writer that stalls past `lease_s` must be
            # the one that loses it (checked above, and by the next writer's `open()`).
            renewed_lease = dict(lease, expires_at=now + timedelta(seconds=self._lease_s))
            new_head = dict(head, last_seq=event["seq"], view_seq=new_view_seq, lease=renewed_lease)
            return new_head, event, view_writes

        self._store.transact(self._org_id, self._world_id, _commit)
        self._state.observe(event)
        self._view_seq = new_view_seq
        for scope, doc in view_writes:
            self._view_ids.setdefault(scope, set()).add(doc["id"])
        return event
