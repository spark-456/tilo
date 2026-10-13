"""SEC-16 / GOLIVE-935: the durable spend-cap ledger on Firestore (`spend.SpendLedger`, BQ-SEC16-1, BQ-PW-3-1).

Every document is under `orgs/{org}/spend_ledger/{id}`: counters `uid:{uid}`, `run:{run}`, `orgday:{org}:{day}` and
`day:{day}` (`settled_minor`, `held_minor`), one `hold:{unit id}` per reservation and one `switch`. Reserve, settle,
release and the switch's trip and reset are each ONE transaction that reads every document it decides on first, so
two instances racing for the last of a cap cannot both win (the loser's commit aborts and re-reads), and a retried
settle, release or reserve (same unit id) finds its hold's state and counts nothing twice.

Fail closed: a read that fails raises (the guard turns that into replay, never live), a malformed counter is a
`ValueError`, a malformed `switch` reads as set, and a hold that is not `held` can never be reopened. Needs no index
and no rule change: single-document reads and writes by the API's own service account (the Admin SDK), and nothing
reads this collection from a client."""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from google.api_core import exceptions as gexc
from google.cloud import firestore
from google.cloud.firestore_v1.base_query import FieldFilter

from tilo_api.spend import Refused, Reservation, Settled, SpendCaps, _int

logger = logging.getLogger("tilo_api.spend_firestore")
COLLECTION = "spend_ledger"
_ATTEMPTS = 4  # on top of the library's own five per call: contention only ever ends in replay, never in a pass
_REASONS = ("uid_lifetime", "run", "org_day", "global_hard")
HOLD_TTL = timedelta(hours=1)  # ADR-0042 MV-17(b): above any meeting claim's 3500 s; then a held hold is stranded
_SWEEP_EVERY = timedelta(seconds=60)  # a uid's reserves sweep its expired holds at most this often per process


def _part(value: object, name: str) -> str:
    if not isinstance(value, str) or not value or "/" in value or len(value.encode("utf-8", "replace")) > 400:
        raise ValueError(f"{name} must be a non-empty string without '/'")
    return value


class FirestoreSpendLedger:
    def __init__(self, client: Any, caps: SpendCaps, *, org_id: str) -> None:
        self._client, self._caps, self._org = client, caps, _part(org_id, "org_id")
        self._swept: dict[str, datetime] = {}  # uid -> the `at` of its last sweep (this process only)

    # -- documents ----------------------------------------------------------------------------------------------
    def _ref(self, doc_id: str) -> Any:
        return self._client.document(f"orgs/{self._org}/{COLLECTION}/{doc_id}")

    @staticmethod
    def _counters(uid: str, run_id: str, org_id: str, day: str) -> tuple[str, ...]:
        return f"uid:{uid}", f"run:{run_id}", f"orgday:{org_id}:{day}", f"day:{day}"

    @staticmethod
    def _totals(snapshot: Any) -> tuple[int, int]:
        """(settled, held) of a counter; an absent document is zero, anything else unreadable is refused."""
        if not snapshot.exists:
            return 0, 0
        data = snapshot.to_dict()
        pair = (data.get("settled_minor"), data.get("held_minor")) if isinstance(data, dict) else (None, None)
        if not all(type(x) is int and x >= 0 for x in pair):
            raise ValueError("a spend counter is malformed")
        return pair  # type: ignore[return-value]

    @staticmethod
    def _switch_on(snapshot: Any) -> bool:
        if not snapshot.exists:
            return False
        data = snapshot.to_dict()
        on = data.get("on") if isinstance(data, dict) else None
        return on if isinstance(on, bool) else True  # a malformed record is never believed to be "off"

    def _write_switch(self, tx: Any, on: bool, reason: str, by: str | None = None) -> None:
        tx.set(
            self._ref("switch"),
            {"on": on, "reason": str(reason)[:200], "by": by, "at": datetime.now(UTC).isoformat()},
        )

    def _run(self, transaction_body: Any) -> Any:
        for _ in range(_ATTEMPTS):
            try:
                return transaction_body(self._client.transaction())
            except gexc.Aborted:
                continue
            except ValueError as exc:  # the library's "failed in N attempts" wraps the Aborted it gave up on
                if not isinstance(exc.__cause__, gexc.Aborted):
                    raise
        raise gexc.Aborted("the spend ledger is contended")  # not a reservation: the caller replays

    # -- SpendLedger --------------------------------------------------------------------------------------------
    def reserve(
        self, *, uid: str, run_id: str, org_id: str, amount_minor: int, at: datetime, unit_id: str | None = None
    ) -> Reservation | Refused:
        amount = _int(amount_minor, "amount_minor", 0)
        if not isinstance(at, datetime) or at.tzinfo is None:
            raise ValueError("`at` must be a timezone-aware datetime")
        rid = _part(unit_id, "unit_id") if unit_id is not None else uuid.uuid4().hex
        uid, run_id, org_id = _part(uid, "uid"), _part(run_id, "run_id"), _part(org_id, "org_id")
        day, c = at.astimezone(UTC).date().isoformat(), self._caps
        keys = self._counters(uid, run_id, org_id, day)
        caps = (c.uid_lifetime_minor, c.run_minor, c.org_day_minor, c.global_day_hard_minor)
        terms = {"uid": uid, "run_id": run_id, "org_id": org_id, "day": day, "amount_minor": amount}
        self._sweep_uid(uid, at)

        @firestore.transactional  # type: ignore[misc]
        def txn(tx: Any) -> Reservation | Refused:
            switch = self._ref("switch").get(transaction=tx)
            hold = self._ref(f"hold:{rid}").get(transaction=tx)
            totals = [self._totals(self._ref(k).get(transaction=tx)) for k in keys]
            if hold.exists:  # a retry of this unit: the same hold, or an error, never a second hold
                stored = hold.to_dict() or {}
                if stored.get("status") != "held" or any(stored.get(k) != v for k, v in terms.items()):
                    raise ValueError("this unit id is closed or was reserved on other terms")
                return Reservation(id=rid, uid=uid, run_id=run_id, org_id=org_id, amount_minor=amount)
            if self._switch_on(switch):
                return Refused("replay_only")
            for reason, cap, (settled, held) in zip(_REASONS, caps, totals, strict=True):
                if cap is not None and settled + held + amount > cap:  # exactly the cap passes
                    if reason == "global_hard":
                        self._write_switch(tx, True, "the daily hard cap would be exceeded")
                    return Refused(reason)
            for key, (settled, held) in zip(keys, totals, strict=True):
                tx.set(self._ref(key), {"settled_minor": settled, "held_minor": held + amount})
            expires = (at + HOLD_TTL).isoformat(timespec="milliseconds")
            tx.set(self._ref(f"hold:{rid}"), {**terms, "status": "held", "actual_minor": None, "expires_at": expires})
            return Reservation(id=rid, uid=uid, run_id=run_id, org_id=org_id, amount_minor=amount)

        return self._run(txn)  # type: ignore[no-any-return]

    def _sweep_uid(self, uid: str, at: datetime) -> None:
        last = self._swept.get(uid)
        if last is not None and abs(at - last) < _SWEEP_EVERY:
            return
        self._swept[uid] = at
        try:
            self.settle_expired(at, uid=uid)
        except Exception as exc:  # a sweep never blocks a reserve and never lifts a cap: the hold still counts
            logger.warning("expired spend holds not swept (%s)", type(exc).__name__)

    def settle_expired(self, now: datetime, *, uid: str | None = None) -> int:
        """ADR-0042 MV-17(b): a `held` hold past its `expires_at` (a restart, a claim that was lost) is settled at its
        own amount: the count is what it already was, only its status closes, so a later close finds it settled and
        nothing counts twice. Returns how many were settled. A hold with no readable `expires_at` is never expired."""
        query = self._client.collection(f"orgs/{self._org}/{COLLECTION}").where(
            filter=FieldFilter("status", "==", "held")
        )
        if uid is not None:
            query = query.where(filter=FieldFilter("uid", "==", uid))
        done = 0
        for snapshot in query.stream():
            held = snapshot.to_dict() or {}
            try:
                if datetime.fromisoformat(held["expires_at"]) > now:
                    continue
                reservation = Reservation(
                    id=snapshot.id.removeprefix("hold:"), uid=held["uid"], run_id=held["run_id"],
                    org_id=held["org_id"], amount_minor=held["amount_minor"],
                )  # fmt: skip
                self._close(reservation, held["amount_minor"])
                done += 1
            except Exception as exc:  # one bad or contended hold never stops the rest
                logger.warning("an expired spend hold was not settled (%s)", type(exc).__name__)
        return done

    def _close(self, reservation: Reservation, actual: int | None) -> Settled | None:
        """Settle (`actual` an int) or release (None) one hold, once. The same close again is a no-op that answers as
        the first did; the other close is a `KeyError`, like a hold that never existed."""
        rid = _part(reservation.id, "reservation id")
        want = "released" if actual is None else "settled"

        @firestore.transactional  # type: ignore[misc]
        def txn(tx: Any) -> Settled | None:
            hold = self._ref(f"hold:{rid}").get(transaction=tx)
            stored = hold.to_dict() if hold.exists else None
            if not isinstance(stored, dict) or stored.get("uid") != reservation.uid:
                raise KeyError(rid)  # unknown, or someone else's
            if stored.get("status") == want:
                done = stored.get("actual_minor")
                return None if actual is None else Settled(overrun=done > stored["amount_minor"])
            if stored.get("status") != "held":
                raise KeyError(rid)
            keys = self._counters(stored["uid"], stored["run_id"], stored["org_id"], stored["day"])
            switch = self._ref("switch").get(transaction=tx)
            totals = [self._totals(self._ref(k).get(transaction=tx)) for k in keys]
            amount = stored["amount_minor"]
            if any(held < amount for _settled, held in totals):
                raise ValueError("a spend counter holds less than this unit reserved")
            keep = 0 if actual is None else actual
            for key, (settled, held) in zip(keys, totals, strict=True):
                tx.set(self._ref(key), {"settled_minor": settled + keep, "held_minor": held - amount})
            tx.set(self._ref(f"hold:{rid}"), {**stored, "status": want, "actual_minor": actual})
            if actual is not None and totals[-1][0] + actual >= self._caps.global_day_hard_minor:
                if not self._switch_on(switch):  # the day reached its hard cap: new live work stops (NFR-24)
                    self._write_switch(tx, True, "the daily hard cap was reached")
            return None if actual is None else Settled(overrun=actual > amount)

        return self._run(txn)  # type: ignore[no-any-return]

    def settle(self, reservation: Reservation, actual_minor: int) -> Settled:
        actual = _int(actual_minor, "actual_minor", 0)  # a bad actual leaves the hold in place
        return self._close(reservation, actual)  # type: ignore[return-value]

    def release(self, reservation: Reservation) -> None:
        self._close(reservation, None)

    def spent_minor(self, uid: str) -> int:
        settled, held = self._totals(self._ref(f"uid:{_part(uid, 'uid')}").get())
        return settled + held

    def settled_minor(self, uid: str) -> int:
        return self._totals(self._ref(f"uid:{_part(uid, 'uid')}").get())[0]

    def replay_only(self) -> bool:
        """The durable switch. A store that cannot be read raises: the guard reads that as no live, never as off."""
        return self._switch_on(self._ref("switch").get())

    def trip_replay_only(self, reason: str) -> bool:
        @firestore.transactional  # type: ignore[misc]
        def txn(tx: Any) -> bool:
            if self._switch_on(self._ref("switch").get(transaction=tx)):
                return False
            self._write_switch(tx, True, reason)
            return True

        flipped = self._run(txn)
        if flipped:
            logger.warning("the spend ledger's replay-only switch was set")
        return bool(flipped)

    def reset_replay_only(self, *, by: str) -> None:
        """The only way back: a named human (no route and no guard reaches it)."""
        if not isinstance(by, str) or not by.strip():
            raise ValueError("a reset names who did it")

        @firestore.transactional  # type: ignore[misc]
        def txn(tx: Any) -> None:
            self._ref("switch").get(transaction=tx)
            self._write_switch(tx, False, "reset", by=by.strip()[:100])

        self._run(txn)
        logger.warning("the spend ledger's replay-only switch was reset")
