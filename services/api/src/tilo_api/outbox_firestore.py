"""The durable outbox store (ADR-0035 L2, LC-11..LC-13; FR-CON-02).

`FirestoreOutboxStore` has the methods of `tilo_connectors.InMemoryOutboxStore`, mutators included, so `Outbox`, the OB
rules, `tilo_policy.check_entry`, SEC-03 and `outbox.schema.json` are untouched. One entry is one document,
`outbox/{outbox_id}`: `{entry, world_id, enqueued_at, send_lease, transfer_lease, retry, transfer, transfer_pending,
alert, alert_pending, alerted}`, so every mutator is one transaction on one document and PI-17's same-write rule (state
and its data.transfer or alert together) holds. The idempotency key is the create-only document
`outbox_keys/{world_id}/keys/{sha256(key)}` (`{outbox_id, revoked}`), created in the insert's transaction; a revoke
creates it with `revoked: true` and nothing ever deletes it.

A claim is a transaction on the lease (30 s) judged by the store's clock, so two instances cannot both win, and a dead
instance's lease just expires. Ids are fullmatched against `common.schema.json` before a path is built from them;
anything else is treated as absent (a read or mutator) or refused (an insert). Whatever Firestore raises leaves as a
fixed 503 `outbox_unavailable`, never its text. The gate (`outbox_store_for_env`) opens a client only for
`TILO_OUTBOX_STORE=firestore` and ADR-0026's project door (`store_door.open_api_store`); anything else is the process's
in-memory store. The composite index the pending-transfer query needs: collection `outbox`, `transfer_pending` ASC,
`enqueued_at` ASC. Nothing here does I/O until a store method is called.
"""

from __future__ import annotations

import hashlib
import logging
import os
import re
from collections.abc import Callable, Mapping
from copy import deepcopy
from typing import Any

from fastapi import HTTPException
from google.cloud import firestore
from google.cloud.firestore_v1.base_query import FieldFilter
from tilo_connectors._time import add_seconds

from tilo_api.store_door import ENV_STORE, open_api_store

logger = logging.getLogger("tilo_api.outbox_firestore")

ENV_OUTBOX = "TILO_OUTBOX_STORE"
ID_PATTERN = re.compile(r"[0-7][0-9A-HJKMNP-TV-Z]{25}")  # common.schema.json#/$defs/ulid
WORLD_PATTERN = re.compile(r"w_[0-9A-Za-z_]{1,48}")  # common.schema.json#/$defs/world_id
_UNSENT = ("queued", "scheduled", "sending")


class OutboxStoreUnavailable(HTTPException):
    """Firestore failed: 503, no entry written, nothing sent, and never the library's text."""

    def __init__(self) -> None:
        super().__init__(status_code=503, detail="outbox_unavailable")


def _id_ok(value: Any) -> bool:
    return isinstance(value, str) and ID_PATTERN.fullmatch(value) is not None


def _world_ok(value: Any) -> bool:
    return isinstance(value, str) and WORLD_PATTERN.fullmatch(value) is not None


class FirestoreOutboxStore:
    def __init__(self, client: Any, clock: Callable[[], str] | None = None) -> None:
        self._client = client
        self._clock = clock  # set: claims compare against this time, not the caller's (PI-12 skew unchanged)

    # -- plumbing ---------------------------------------------------------------------------------------------------

    def _run(self, work: Callable[[Any], Any]) -> Any:
        try:
            return firestore.transactional(work)(self._client.transaction())
        except (HTTPException, OverflowError):  # ours, or a timestamp past datetime's range (Outbox skips it)
            raise
        except Exception as exc:  # the library's text is never passed on
            logger.warning("outbox store unavailable (%s)", type(exc).__name__)
            raise OutboxStoreUnavailable from None

    def _read(self, work: Callable[[], Any]) -> Any:
        try:
            return work()
        except HTTPException:
            raise
        except Exception as exc:
            logger.warning("outbox store unavailable (%s)", type(exc).__name__)
            raise OutboxStoreUnavailable from None

    def _ref(self, outbox_id: str) -> Any:
        return self._client.document(f"outbox/{outbox_id}")

    def _key_ref(self, world_id: str, key: str) -> Any:
        return self._client.document(f"outbox_keys/{world_id}/keys/{hashlib.sha256(key.encode()).hexdigest()}")

    def _now(self, caller_now: str) -> str:
        return self._clock() if self._clock is not None else caller_now

    def _mutate(self, outbox_id: Any, change: Callable[[dict], tuple[bool, Any]]) -> Any:
        """One transaction on one document: read it, let `change` edit it in place, write it back if it changed."""
        if not _id_ok(outbox_id):
            return None

        def work(tx: Any) -> Any:
            ref = self._ref(outbox_id)
            snap = ref.get(transaction=tx)
            if not snap.exists:
                return None
            doc = snap.to_dict()
            changed, result = change(doc)
            if changed:
                tx.set(ref, doc)
            return result

        return self._run(work)

    @staticmethod
    def _record_alert(doc: dict, alert: dict | None) -> None:  # once per entry
        if alert is not None and not doc["alerted"]:
            doc["alerted"], doc["alert"], doc["alert_pending"] = True, deepcopy(alert), True

    # -- reads ------------------------------------------------------------------------------------------------------

    def get(self, outbox_id: str | None) -> dict | None:
        if outbox_id is None or not _id_ok(outbox_id):
            return None

        def work() -> dict | None:
            snap = self._ref(outbox_id).get()
            return snap.to_dict()["entry"] if snap.exists else None

        return self._read(work)

    def get_by_idempotency_key(self, world_id: str, idempotency_key: str) -> dict | None:
        if not _world_ok(world_id) or not isinstance(idempotency_key, str):
            return None

        def work() -> str | None:
            snap = self._key_ref(world_id, idempotency_key).get()
            return snap.to_dict().get("outbox_id") if snap.exists else None

        return self.get(self._read(work))

    def all_entries(self) -> list[dict]:
        return self._read(lambda: [s.to_dict()["entry"] for s in self._client.collection("outbox").stream()])

    def retry_state(self, outbox_id: str) -> dict:
        base = {"attempts": 0, "not_before": "", "since": None, "ambiguous": False}
        if not _id_ok(outbox_id):
            return base

        def work() -> dict:
            snap = self._ref(outbox_id).get()
            return {**base, **((snap.to_dict()["retry"] or {}) if snap.exists else {})}

        return self._read(work)

    def _pending_alerts_of(self, only: str | None) -> list[tuple[str, dict]]:  # at-least-once; alert_id dedupes
        def work() -> list[tuple[str, dict]]:
            rows = self._client.collection("outbox").where(filter=FieldFilter("alert_pending", "==", True)).stream()
            return [(s.id, d["alert"]) for s in rows if only in (None, (d := s.to_dict())["world_id"])]

        return self._read(work)

    # -- mutators ---------------------------------------------------------------------------------------------------

    def _insert_if_absent(self, entry: dict) -> bool:  # OB-03: neither id nor key already stored
        if not _id_ok(entry.get("id")) or not _world_ok(entry.get("world_id")):
            raise ValueError("not an outbox entry id or world id")
        key = entry.get("idempotency_key")
        if not isinstance(key, str):
            raise ValueError("not an idempotency key")
        doc = {
            "entry": deepcopy(entry), "world_id": entry["world_id"],
            "enqueued_at": self._now(entry.get("created_at", "")), "send_lease": None, "transfer_lease": None,
            "retry": None, "transfer": None, "transfer_pending": False, "alert": None, "alert_pending": False,
            "alerted": False,
        }  # fmt: skip

        def work(tx: Any) -> bool:
            ref, key_ref = self._ref(entry["id"]), self._key_ref(entry["world_id"], key)
            if ref.get(transaction=tx).exists or key_ref.get(transaction=tx).exists:
                return False
            tx.create(ref, doc)
            tx.create(key_ref, {"outbox_id": entry["id"], "revoked": False})
            return True

        return self._run(work)

    def _cancel(self, outbox_id: str) -> dict | None:  # scheduled -> cancelled, for Outbox.cancel
        def change(doc: dict) -> tuple[bool, dict | None]:
            if doc["entry"]["state"] != "scheduled":
                return False, None
            doc["entry"]["state"] = "cancelled"
            return True, deepcopy(doc["entry"])

        return self._mutate(outbox_id, change)

    def _revoke(self, world_id: str, idempotency_key: str) -> dict | None:  # for Outbox.revoke; never creates an entry
        if not _world_ok(world_id) or not isinstance(idempotency_key, str):
            return None

        def work(tx: Any) -> dict | None:
            key_ref = self._key_ref(world_id, idempotency_key)
            key_snap = key_ref.get(transaction=tx)
            if not key_snap.exists:
                tx.create(key_ref, {"outbox_id": None, "revoked": True})  # the insert refuses the key from now on
                return None
            outbox_id = key_snap.to_dict().get("outbox_id")
            if not _id_ok(outbox_id):
                return None
            ref = self._ref(outbox_id)
            snap = ref.get(transaction=tx)
            if not snap.exists:
                return None
            doc = snap.to_dict()
            if doc["entry"]["state"] == "scheduled":
                doc["entry"]["state"] = "cancelled"
                tx.set(ref, doc)
            return deepcopy(doc["entry"])

        return self._run(work)

    def _abandon(self, outbox_id: str, now: str) -> dict | None:  # unsent, no live lease -> failed, for Outbox.abandon
        def change(doc: dict) -> tuple[bool, dict | None]:
            lease = doc["send_lease"]
            if doc["entry"]["state"] not in _UNSENT or (lease is not None and now < lease["until"]):
                return False, None
            doc["entry"]["state"], doc["retry"] = "failed", None
            return True, deepcopy(doc["entry"])

        return self._mutate(outbox_id, change)

    def _claim_for_sending(
        self, outbox_id: str, holder: str, now: str, lease_seconds: float, skew_s: float = 0
    ) -> dict | None:  # never before scheduled_at + skew_s (PI-12) or the entry's not-before
        def change(doc: dict) -> tuple[bool, dict | None]:
            at, entry, lease = self._now(now), doc["entry"], doc["send_lease"]
            if entry["state"] not in _UNSENT:
                return False, None
            if (
                entry.get("undo_window_s")
                and "scheduled_at" in entry
                and at < add_seconds(entry["scheduled_at"], skew_s)
            ):
                return False, None
            if at < (doc["retry"] or {}).get("not_before", "") or (lease is not None and at < lease["until"]):
                return False, None
            doc["send_lease"] = {"holder": holder, "until": add_seconds(at, lease_seconds)}
            entry["state"] = "sending"  # takes over an expired lease too
            return True, deepcopy(entry)

        return self._mutate(outbox_id, change)

    def _finalize_claim(
        self, outbox_id: str, holder: str, to_state: str, transfer: dict | None = None, alert: dict | None = None
    ) -> dict | None:
        def change(doc: dict) -> tuple[bool, dict | None]:
            lease = doc["send_lease"]
            if doc["entry"]["state"] != "sending" or lease is None or lease["holder"] != holder:
                return False, None
            doc["entry"]["state"], doc["send_lease"], doc["retry"] = to_state, None, None
            if transfer is not None and doc["transfer"] is None:  # the transfer or alert in the same write (PI-17)
                doc["transfer"], doc["transfer_pending"] = deepcopy(transfer), True
            self._record_alert(doc, alert)
            return True, deepcopy(doc["entry"])

        return self._mutate(outbox_id, change)

    def _defer(
        self, outbox_id: str, holder: str, attempts: int, now: str, delay_s: float, ambiguous: bool = False,
        alert: dict | None = None,
    ) -> None:  # fmt: skip
        """Releases holder's send lease; no attempt before now + delay_s (store time when the store has a clock)."""

        def change(doc: dict) -> tuple[bool, None]:
            lease, at = doc["send_lease"], self._now(now)
            if lease is None or lease["holder"] != holder:
                return False, None
            since = (doc["retry"] or {}).get("since") or at
            doc["retry"] = {"attempts": attempts, "not_before": add_seconds(at, delay_s), "since": since,
                            "ambiguous": ambiguous}  # fmt: skip
            self._record_alert(doc, alert)
            doc["send_lease"] = None
            return True, None

        self._mutate(outbox_id, change)

    def _release_lease(self, kind: str, outbox_id: str, holder: str) -> None:  # kind: "send"/"transfer"
        field = "send_lease" if kind == "send" else "transfer_lease"

        def change(doc: dict) -> tuple[bool, None]:
            if doc[field] is None or doc[field]["holder"] != holder:
                return False, None
            doc[field] = None
            return True, None

        self._mutate(outbox_id, change)

    def _claim_oldest_pending_transfer(
        self,
        holder: str,
        now: str,
        lease_seconds: float,
        exclude: frozenset[str] = frozenset(),
        only: str | None = None,
    ) -> tuple[str, str, dict] | None:  # oldest pending transfer of a world not in `exclude` (and == `only`, if set)
        def candidates() -> list[tuple[str, str]]:
            query = self._client.collection("outbox").where(filter=FieldFilter("transfer_pending", "==", True))
            return [(s.id, s.to_dict()["world_id"]) for s in query.order_by("enqueued_at").stream()]

        seen_worlds = set(exclude)
        for outbox_id, world_id in self._read(candidates):
            if world_id in seen_worlds or only not in (None, world_id):
                continue
            seen_worlds.add(world_id)  # a world's later transfer never passes its earlier one

            def change(doc: dict) -> tuple[bool, dict | None]:
                lease, at = doc["transfer_lease"], self._now(now)
                if not doc["transfer_pending"] or (lease is not None and at < lease["until"]):
                    return False, None
                doc["transfer_lease"] = {"holder": holder, "until": add_seconds(at, lease_seconds)}
                return True, deepcopy(doc["transfer"])  # a mutating emit never corrupts a retry

            if (transfer := self._mutate(outbox_id, change)) is not None:
                return (outbox_id, world_id, transfer)
        return None

    def _discard_pending_alert(self, outbox_id: str) -> None:
        def change(doc: dict) -> tuple[bool, None]:
            doc["alert"], doc["alert_pending"] = None, False
            return True, None

        self._mutate(outbox_id, change)

    def _discard_pending_transfer(self, outbox_id: str, holder: str) -> None:  # always removed once delivered
        def change(doc: dict) -> tuple[bool, None]:
            doc["transfer"], doc["transfer_pending"] = None, False
            if doc["transfer_lease"] is not None and doc["transfer_lease"]["holder"] == holder:
                doc["transfer_lease"] = None
            return True, None

        self._mutate(outbox_id, change)


# --- the gate (LC-13) -----------------------------------------------------------------------------------------------


def outbox_store_for_env(
    env: Mapping[str, str] | None = None, *, client_factory: Callable[[str], Any] | None = None
) -> FirestoreOutboxStore | None:
    """None (the caller keeps the process's in-memory store) unless `TILO_OUTBOX_STORE` is exactly `firestore`. Then
    ADR-0026's door decides: a valid `TILO_FIRESTORE_PROJECT`, on Cloud Run or on the emulator with a `demo-` project;
    asked for but not permitted (or not buildable) is 503, never a quiet fall back to memory, and no client is built.
    """
    values = dict(os.environ if env is None else env)
    if values.get(ENV_OUTBOX) != "firestore":
        return None
    from tilo_api.events import now  # noqa: PLC0415

    try:
        door = open_api_store({**values, ENV_STORE: "firestore"}, firestore_client_factory=client_factory)
    except Exception as exc:
        logger.warning("outbox store not opened (%s)", type(exc).__name__)
        raise HTTPException(status_code=503, detail="not_configured") from None
    return FirestoreOutboxStore(door.client, clock=now)


# --- the tick's sweep (LC-12) ---------------------------------------------------------------------------------------


class _Wired:
    """The store as the sweep sees it: only entries whose connector has an adapter. `Outbox` ends an entry it cannot
    send as failed, so an entry nothing here can send is not shown to it, and stays for whoever can."""

    def __init__(self, store: Any, wired: frozenset[str]) -> None:
        self._store, self._wired = store, wired

    def all_entries(self) -> list[dict]:
        return [e for e in self._store.all_entries() if e["connector"] in self._wired]

    def __getattr__(self, name: str) -> Any:
        return getattr(self._store, name)


def _no_writer(part: dict) -> None:
    raise RuntimeError("the tick has no world writer")  # the transfer stays pending for a run that has one


def sweep_due(
    store: Any, adapters: Mapping[str, Any], clock: Callable[[], str], world_paused: Callable[[str], bool]
) -> int:
    """`dispatch_due()` over the unsent entries, one world at a time so a paused world is not claimed (FR-WLD-07).
    A dead instance's due entry goes out within one tick; an ambiguous attempt stays ambiguous (the outbox's retry
    state), never failed. Returns how many entries settled. A world's data.transfer and alerts are left pending: the
    tick has no world writer (BQ-ADR35-L2-3)."""
    from tilo_connectors import Outbox, RetryPolicy  # noqa: PLC0415

    adapters = {
        name: a for name, a in adapters.items() if not getattr(a, "needs_run", False)
    }  # L6: a stub needs its run
    if not adapters:
        return 0
    wired = _Wired(store, frozenset(adapters))
    worlds = sorted({e["world_id"] for e in wired.all_entries() if e["state"] in _UNSENT})
    settled = 0
    for world in worlds:
        outbox = Outbox(
            wired, dict(adapters), emit=_no_writer, clock=clock, world_id=world, retry=RetryPolicy(),
            halted=lambda world=world: world_paused(world),
        )  # fmt: skip
        settled += len(outbox.dispatch_due())
    return settled
