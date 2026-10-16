"""The morning brief's small records (ADR-0049, MO-02, MO-03, MO-04, MO-11): a person's brief setting, the claim that
makes one scheduled brief per (org, user, local date), the on-demand counter and the index that lets the source-owners
seam vouch for a message id of the person's own brief. The brief itself is an artifact (`morning_brief`).

Memory behind an in-memory `PeopleStores` (dev, tests, a demo session); Firestore on the people stores' own client:
`orgs/{org}/brief_settings/{uid}`, `orgs/{org}/brief_claims/{uid}_{date}_{kind}` and `orgs/{org}/brief_mail/{message}`.
Deployed, anything but Firestore is 503 `not_configured`, never memory. No document holds a title, subject, sender or
address: ids, dates and counts only.
"""

from __future__ import annotations

import copy
import re
import threading
import weakref
from datetime import date, timedelta
from typing import Any, Protocol

from fastapi import HTTPException
from tilo_people.stores import PeopleStores

from tilo_api import deps
from tilo_api.people_firestore import FirestoreRecordStore
from tilo_api.user_settings import _deployed

_USER = re.compile(r"u_[0-9A-Za-z_]{1,48}")
_ORG = re.compile(r"org_[0-9A-Za-z_]{1,48}")
_DATE = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}")
_MESSAGE = re.compile(r"[A-Za-z0-9_-]{1,128}")
KEEP_DAYS = 7  # MO-09, MO-11: how long a brief, and so a message id it vouches for, lasts


class BriefStore(Protocol):
    def settings(self, org: str, user: str) -> dict[str, Any] | None: ...

    def save_settings(self, org: str, user: str, doc: dict[str, Any]) -> None: ...

    def enabled(self, org: str, limit: int) -> list[dict[str, Any]]:
        """At most `limit` stored settings with `enabled` true (the sweep's candidates)."""
        ...

    def claim(self, org: str, user: str, day: str, kind: str) -> bool:
        """True for the first caller of (user, day, kind) and false for every later one (atomic)."""
        ...

    def take_on_demand(self, org: str, user: str, day: str, limit: int) -> bool:
        """Counts one on-demand brief of that local date; false (nothing counted) when `limit` were already made."""
        ...

    def index_mail(self, org: str, user: str, ids: list[str], day: str) -> None: ...

    def mail_owner(self, org: str, message_id: str, today: str) -> str | None:
        """The one person whose brief of the last `KEEP_DAYS` days holds this message id; None when none or several."""
        ...

    def erase(self, org: str, user: str) -> None:
        """FR-MEM-09: the person's setting; claims and the mail index expire by date and hold no content."""
        ...


def _fresh(day: str, today: str) -> bool:
    try:
        return date.fromisoformat(today) - timedelta(days=KEEP_DAYS) <= date.fromisoformat(day)
    except ValueError:
        return False


class MemoryBriefStore:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._settings: dict[tuple[str, str], dict[str, Any]] = {}
        self._claims: set[tuple[str, str, str, str]] = set()
        self._counts: dict[tuple[str, str, str], int] = {}
        self._mail: dict[tuple[str, str], dict[str, str]] = {}

    def settings(self, org: str, user: str) -> dict[str, Any] | None:
        with self._lock:
            return copy.deepcopy(self._settings.get((org, user)))

    def save_settings(self, org: str, user: str, doc: dict[str, Any]) -> None:
        with self._lock:
            self._settings[(org, user)] = copy.deepcopy(doc)

    def enabled(self, org: str, limit: int) -> list[dict[str, Any]]:
        with self._lock:
            rows = [copy.deepcopy(d) for (o, _), d in sorted(self._settings.items()) if o == org and d["enabled"]]
        return rows[:limit]

    def claim(self, org: str, user: str, day: str, kind: str) -> bool:
        with self._lock:
            key = (org, user, day, kind)
            held = key in self._claims
            self._claims.add(key)
            return not held

    def take_on_demand(self, org: str, user: str, day: str, limit: int) -> bool:
        with self._lock:
            n = self._counts.get((org, user, day), 0)
            if n >= limit:
                return False
            self._counts[(org, user, day)] = n + 1
            return True

    def index_mail(self, org: str, user: str, ids: list[str], day: str) -> None:
        with self._lock:
            for message_id in ids:
                self._mail.setdefault((org, message_id), {})[user] = day

    def mail_owner(self, org: str, message_id: str, today: str) -> str | None:
        with self._lock:
            owners = [u for u, day in self._mail.get((org, message_id), {}).items() if _fresh(day, today)]
        return owners[0] if len(owners) == 1 else None

    def erase(self, org: str, user: str) -> None:
        with self._lock:
            self._settings.pop((org, user), None)
            for key in [k for k in self._mail if user in self._mail[k]]:
                self._mail[key].pop(user, None)


class FirestoreBriefStore:
    def __init__(self, client: Any) -> None:
        self._client = client

    def _doc(self, org: str, collection: str, name: str) -> Any:
        if _ORG.fullmatch(org) is None:
            raise ValueError("malformed org id")
        return self._client.document(f"orgs/{org}/{collection}/{name}")

    @staticmethod
    def _checked(user: str, day: str | None = None) -> None:
        if _USER.fullmatch(user) is None or (day is not None and _DATE.fullmatch(day) is None):
            raise ValueError("malformed id")

    def settings(self, org: str, user: str) -> dict[str, Any] | None:
        self._checked(user)
        snap = self._doc(org, "brief_settings", user).get()
        found = snap.to_dict() if snap.exists else None
        return dict(found) if isinstance(found, dict) and found.get("owner_id") == user else None

    def save_settings(self, org: str, user: str, doc: dict[str, Any]) -> None:
        self._checked(user)
        self._doc(org, "brief_settings", user).set(doc)

    def enabled(self, org: str, limit: int) -> list[dict[str, Any]]:
        from google.cloud.firestore_v1.base_query import FieldFilter  # noqa: PLC0415

        query = self._client.collection(f"orgs/{org}/brief_settings").where(filter=FieldFilter("enabled", "==", True))
        return [d for s in query.limit(limit).stream() if isinstance(d := s.to_dict(), dict)]

    def claim(self, org: str, user: str, day: str, kind: str) -> bool:
        from google.api_core.exceptions import AlreadyExists  # noqa: PLC0415

        self._checked(user, day)
        try:
            self._doc(org, "brief_claims", f"{user}_{day}_{kind}").create({"at": day})
        except AlreadyExists:
            return False
        return True

    def take_on_demand(self, org: str, user: str, day: str, limit: int) -> bool:
        from google.cloud import firestore  # noqa: PLC0415

        self._checked(user, day)
        ref = self._doc(org, "brief_claims", f"{user}_{day}_od")

        @firestore.transactional  # type: ignore[misc]
        def work(tx: Any) -> bool:
            snap = ref.get(transaction=tx)
            n = int((snap.to_dict() or {}).get("n", 0)) if snap.exists else 0
            if n >= limit:
                return False
            tx.set(ref, {"n": n + 1, "at": day})
            return True

        return bool(work(self._client.transaction()))

    def index_mail(self, org: str, user: str, ids: list[str], day: str) -> None:
        self._checked(user, day)
        for message_id in ids:
            if _MESSAGE.fullmatch(message_id):
                self._doc(org, "brief_mail", message_id).set({"owners": {user: day}}, merge=True)

    def mail_owner(self, org: str, message_id: str, today: str) -> str | None:
        if _MESSAGE.fullmatch(message_id) is None:
            return None
        snap = self._doc(org, "brief_mail", message_id).get()
        held = (snap.to_dict() or {}).get("owners") if snap.exists else None
        owners = [u for u, d in held.items() if _fresh(str(d), today)] if isinstance(held, dict) else []
        return owners[0] if len(owners) == 1 and _USER.fullmatch(owners[0]) else None

    def erase(self, org: str, user: str) -> None:
        self._checked(user)
        self._doc(org, "brief_settings", user).delete()


_STORES: dict[int, BriefStore] = {}
_LOCK = threading.Lock()


def brief_store_of(stores: PeopleStores) -> BriefStore:
    """The one `BriefStore` of this install's people stores: Firestore on their own client, else memory off Cloud Run
    (a deployed service answers 503 `not_configured` rather than keep a person's setting in a process)."""
    with _LOCK:
        found = _STORES.get(id(stores))
        if found is None:
            if isinstance(stores.work_items, FirestoreRecordStore):
                found = FirestoreBriefStore(stores.work_items._client)
            elif _deployed():
                raise HTTPException(status_code=503, detail="not_configured")
            else:
                found = MemoryBriefStore()
            _STORES[id(stores)] = found
            weakref.finalize(stores, _STORES.pop, id(stores), None)
        return found


def get_brief_store() -> BriefStore:
    return brief_store_of(deps.get_people_stores())
