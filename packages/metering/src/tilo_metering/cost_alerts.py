"""Owner cost alerts (NFR-27): 80% and 100% of a uid's lifetime cap, and a global daily USD threshold.

Alert-only: this module writes one redacted JSON line per alert and never raises, blocks or changes spend
(the NFR-24 soft/hard caps in Treasury are a separate mechanism). A Cloud Monitoring log-based metric on
`jsonPayload.event="cost_alert"` turns the line into an email to the owner (infra/modules/monitoring).

`check(ledger)` recomputes every total from the ledger it is given (commit entries only), so replaying a
ledger is idempotent. Dedup state is in-process: a restart can re-emit an alert (docs/open-questions.md).
The line carries only allowlisted keys and `uid_ref`, a one-way digest of the uid: no raw ids or free text.
"""

import hashlib
import json
import math
import threading
from collections.abc import Callable, Iterable
from datetime import UTC, date

from .treasury import LedgerEntry

COST_ALERT_EVENT = "cost_alert"

_EPS = 1e-9
_SEVERITY = {"uid_cap_80": "WARNING", "uid_cap_100": "ERROR", "global_daily": "WARNING"}


def _stdout_sink(line: str) -> None:
    print(line, flush=True)


def _uid_ref(uid: str) -> str:
    return hashlib.sha256(f"tilo-cost-alert-uid:{uid}".encode()).hexdigest()[:16]


def _credits(entry: object) -> float | None:
    """Credits of a priced commit entry, or None for anything else (junk never raises)."""
    if not isinstance(entry, LedgerEntry) or entry.kind != "commit" or entry.credits is None:
        return None
    value = entry.credits
    return float(value) if isinstance(value, int | float) and math.isfinite(value) and value >= 0 else None


class CostAlerts:
    def __init__(
        self,
        *,
        uid_cap_credits: float,
        daily_usd_threshold: float,
        credit_usd: float,
        sink: Callable[[str], None] | None = None,
    ) -> None:
        for name, value in (
            ("uid_cap_credits", uid_cap_credits),
            ("daily_usd_threshold", daily_usd_threshold),
            ("credit_usd", credit_usd),
        ):
            if isinstance(value, bool) or not isinstance(value, int | float) or not math.isfinite(value) or value <= 0:
                raise ValueError(f"{name} must be a finite number above 0")
        self._cap, self._daily_usd, self._credit_usd = uid_cap_credits, daily_usd_threshold, credit_usd
        self._sink = sink or _stdout_sink
        self._lock = threading.Lock()
        self._sent: set[tuple[str, str]] = set()  # (kind, uid_ref or ISO day) already delivered
        self._inflight: set[tuple[str, str]] = set()  # claimed by a check whose sink call is running

    def check(self, ledger: Iterable[object]) -> tuple[dict, ...]:
        """Write a line for each threshold newly crossed; return those delivered. Never raises."""
        try:
            with self._lock:
                pending = [
                    (key, rec) for key, rec in self._due(ledger) if key not in self._sent and key not in self._inflight
                ]
                self._inflight.update(key for key, _ in pending)
            raised: list[dict] = []
            for key, record in pending:  # the sink runs off the lock: a slow sink never blocks other callers
                delivered = False
                try:
                    self._sink(json.dumps(record, sort_keys=True, separators=(",", ":"), allow_nan=False))
                    delivered = True
                except Exception:  # not marked as sent: the next check retries
                    pass
                with self._lock:
                    self._inflight.discard(key)
                    if delivered:
                        self._sent.add(key)
                if delivered:
                    raised.append(record)
            return tuple(raised)
        except Exception:  # alert-only: this path must never break a caller
            return ()

    def _due(self, ledger: Iterable[object]) -> list[tuple[tuple[str, str], dict]]:
        per_uid: dict[str, float] = {}
        per_day: dict[date, float] = {}
        for entry in ledger:
            try:  # one poisoned entry must not hide a crossing made by the others
                credits = _credits(entry)
                if credits is None or not isinstance(entry, LedgerEntry):
                    continue
                day = entry.day or entry.at.astimezone(UTC).date()
                user = str(entry.user)
            except Exception:
                continue
            per_uid[user] = per_uid.get(user, 0.0) + credits
            per_day[day] = per_day.get(day, 0.0) + credits

        records: list[tuple[tuple[str, str], dict]] = []
        for uid, spent in per_uid.items():
            ref = _uid_ref(uid)
            for pct in (80, 100):
                if spent >= self._cap * pct / 100 - _EPS:
                    kind = f"uid_cap_{pct}"
                    msg = f"uid reached {pct}% of its lifetime spend cap"
                    extra = {"uid_ref": ref, "threshold_pct": pct, "spent_credits": spent, "cap_credits": self._cap}
                    records.append(((kind, ref), self._record(kind, msg, extra)))
        for day, spent in sorted(per_day.items()):
            spent_usd = spent * self._credit_usd
            if spent_usd >= self._daily_usd - _EPS:
                extra = {"day": day.isoformat(), "spent_usd": spent_usd, "threshold_usd": self._daily_usd}
                records.append(
                    (
                        ("global_daily", day.isoformat()),
                        self._record("global_daily", "global daily spend threshold reached", extra),
                    )
                )

        return records

    @staticmethod
    def _record(kind: str, message: str, extra: dict) -> dict:
        return {"event": COST_ALERT_EVENT, "kind": kind, "severity": _SEVERITY[kind], "message": message, **extra}
