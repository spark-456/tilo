"""FR-SET-01, FR-SET-02 (ADR-0039, USET-01..08): `GET` and `PUT /v1/me/settings`, one person's saved profile and
notification preferences. SECURITY PATH: an owner-data route.

Whose: the owner is `Principal.user_id` and the org is `deps.ORG_ID` (as every people route); the body names neither
(the contract refuses `owner_id`, `org_id` and `updated_at`), and no route lists or reads another person's document.
A write carries the version it read: a stale one is 409 with nothing written (compare-and-set in the store). The body
is checked whole by `contracts/user_settings.schema.json#/$defs/update`, then by USET-03's rules (window order, zone
database, currency table); a refusal is 422 naming only the field, never the value, and changes nothing. The server
refuses an all-off decisions row (USET-04, schema), a threshold in any form but `{amount_minor, currency}`, and
profile text with invisible characters. An anonymous demo session stores nothing (DEMO-EPHEMERAL): a read answers the
unsaved defaults and a write is 403. Saving sends nothing and authorises nothing (USET-07); no event, no log line
carries the content (USET-08).

The store is `SettingsStore`: memory behind an in-memory `PeopleStores` (dev mode, tests), Firestore behind the people
stores' own client (`user_settings_firestore`). Deployed, anything but Firestore is 503 `not_configured`, never memory.
`StoredPreferences` is the read-only view delivery code reads: the quiet-hours window and the rows, never the threshold
and never anything that could withhold a gate (USET-05)."""

from __future__ import annotations

import copy
import json
import os
import threading
import weakref
from typing import Annotated, Any, Protocol
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import APIRouter, Depends, HTTPException, Request
from starlette.concurrency import run_in_threadpool
from tilo_people.stores import PeopleStores
from tilo_people.text import clean_line
from tilo_policy.schemas import conforms

from tilo_api import deps
from tilo_api.people import _PeopleRoute
from tilo_api.people_firestore import FirestoreRecordStore
from tilo_api.people_limits import write_limit
from tilo_api.people_writes import Refusal

ROUTE = "/v1/me/settings"
SCHEMA = "user_settings.schema.json"
MAX_BODY_BYTES = 16384  # a whole document is under 2 KB; over this is 413 before it is read
VERSION_MAX = 1_000_000
_SECTIONS = ("profile", "notifications", "quiet_hours")
_TEXT = (("profile", "name"), ("profile", "title"), ("profile", "email"))
# ISO 4217 codes this release can store a threshold in (BQ-USET-2): code -> decimal digits of the minor unit.
CURRENCY_DIGITS = {
    "INR": 2, "USD": 2, "EUR": 2, "GBP": 2, "AUD": 2, "CAD": 2, "SGD": 2, "NZD": 2, "CHF": 2, "AED": 2,
    "HKD": 2, "CNY": 2, "SEK": 2, "NOK": 2, "DKK": 2, "ZAR": 2, "JPY": 0, "KRW": 0,
}  # fmt: skip


def defaults(owner_id: str) -> dict[str, Any]:
    """The unsaved document (version 0, no time): what a person who never saved reads. Nothing is stored."""
    on, off = {"phone": True, "email": True, "slack": True}, {"phone": False, "email": False, "slack": False}
    return {
        "owner_id": owner_id, "org_id": deps.ORG_ID, "version": 0,
        "profile": {
            "name": "Tilo user", "email": "not-set@example.invalid", "title": None, "time_zone": "UTC",
            "language": "en",
            "working_hours": {"days": ["mon", "tue", "wed", "thu", "fri"], "start": "09:00", "end": "17:00"},
        },
        "notifications": {
            "decisions": dict(on), "spend": {**off, "phone": True, "email": True},
            "finished": {**off, "phone": True, "slack": True}, "digest": {**off, "email": True},
            "weekly": {**off, "email": True, "slack": True},
        },
        "quiet_hours": {"enabled": True, "start": "19:00", "end": "08:00", "timezone": "UTC", "threshold": None},
        "updated_at": None,
    }  # fmt: skip


class SettingsStore(Protocol):
    def read(self, org_id: str, user_id: str) -> dict[str, Any] | None: ...

    def write(self, org_id: str, user_id: str, *, expected_version: int, document: dict[str, Any]) -> bool:
        """Stores `document` only if the stored version is `expected_version` (0 when nothing is stored)."""
        ...

    def erase(self, org_id: str, user_id: str) -> None: ...


class MemorySettingsStore:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._rows: dict[tuple[str, str], dict[str, Any]] = {}

    def read(self, org_id: str, user_id: str) -> dict[str, Any] | None:
        with self._lock:
            row = self._rows.get((org_id, user_id))
            return copy.deepcopy(row) if row is not None else None

    def write(self, org_id: str, user_id: str, *, expected_version: int, document: dict[str, Any]) -> bool:
        with self._lock:
            held = self._rows.get((org_id, user_id))
            if (held["version"] if held is not None else 0) != expected_version:
                return False
            self._rows[(org_id, user_id)] = copy.deepcopy(document)
            return True

    def erase(self, org_id: str, user_id: str) -> None:
        with self._lock:
            self._rows.pop((org_id, user_id), None)


_STORES: dict[int, SettingsStore] = {}
_STORES_LOCK = threading.Lock()


def _deployed() -> bool:
    return "K_SERVICE" in os.environ or "CLOUD_RUN_JOB" in os.environ  # presence, as `dev.refuse_if_unsafe`


def settings_store_of(stores: PeopleStores) -> SettingsStore:
    """The one `SettingsStore` of this install's people stores, on their own Firestore client when they have one;
    otherwise in memory, which a deployed service refuses (503, never memory)."""
    with _STORES_LOCK:
        found = _STORES.get(id(stores))
        if found is None:
            if isinstance(stores.work_items, FirestoreRecordStore):  # the people seam's own client: no second one
                from tilo_api.user_settings_firestore import FirestoreSettingsStore  # noqa: PLC0415

                found = FirestoreSettingsStore(stores.work_items._client)
            elif _deployed():
                raise HTTPException(status_code=503, detail="not_configured")
            else:
                found = MemorySettingsStore()
            _STORES[id(stores)] = found
            weakref.finalize(stores, _STORES.pop, id(stores), None)
        return found


class StoredPreferences:
    """`get(user_id)` for `tilo_channels.quiet_hours.PreferenceReader` and `CardStore(preferences=)`: the stored quiet
    window and rows, or None for a person with nothing saved (behaviour as before) or a store that cannot be read
    (nothing is hidden). The threshold is not passed on: it can never narrow a gate's push (USET-05)."""

    def __init__(self, store: SettingsStore, org_id: str | None = None) -> None:
        self._store, self._org = store, org_id or deps.ORG_ID

    def get(self, user_id: str) -> dict[str, Any] | None:
        try:
            doc = self._store.read(self._org, user_id)
        except Exception:
            return None
        if doc is None:
            return None
        quiet = doc["quiet_hours"]
        return {
            "quiet_hours": {k: quiet[k] for k in ("enabled", "start", "end", "timezone")},
            "notifications": copy.deepcopy(doc["notifications"]),
        }


def _zone_known(name: str) -> bool:
    try:
        ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError, OSError):
        return False
    return True


def refused_field(update: dict[str, Any]) -> str | None:
    """USET-03 and the text rule over a shape-valid write: the dotted name of the first field refused, else None."""
    hours, quiet, profile = update["profile"]["working_hours"], update["quiet_hours"], update["profile"]
    for section, key in _TEXT:
        value = update[section][key]
        if value is not None and (clean_line(value) != value or not value.strip()):
            return f"{section}.{key}"
    if not hours["start"] < hours["end"]:
        return "profile.working_hours"
    if quiet["start"] == quiet["end"]:
        return "quiet_hours.start"
    if not _zone_known(profile["time_zone"]):
        return "profile.time_zone"
    if not _zone_known(quiet["timezone"]):
        return "quiet_hours.timezone"
    if quiet["threshold"] is not None and quiet["threshold"]["currency"] not in CURRENCY_DIGITS:
        return "quiet_hours.threshold"
    return None


def _shape_fields(payload: Any) -> list[str]:
    """Where a body that the schema refused is wrong: top-level and section names only, never a value."""
    if not isinstance(payload, dict):
        return ["body"]
    fields = ["?" for key in payload if key not in {"version", *_SECTIONS}]
    fields += [key for key in ("version", *_SECTIONS) if key not in payload]
    version = payload.get("version")
    if "version" in payload and not (type(version) is int and 0 <= version <= VERSION_MAX):
        fields.append("version")
    for key in _SECTIONS:
        if key in payload and not conforms(f"{SCHEMA}#/$defs/{key}", payload[key]):
            deeper = key == "notifications" and isinstance(payload[key], dict) and "decisions" in payload[key]
            decisions_bad = deeper and not conforms(f"{SCHEMA}#/$defs/decision_channels", payload[key]["decisions"])
            fields.append("notifications.decisions" if decisions_bad else key)
    return fields or ["body"]


async def _body(request: Request) -> dict[str, Any]:
    """JSON only (415); over MAX_BODY_BYTES is 413 before it is parsed; NaN, a non-object or the contract's refusal is
    a 422 that carries field names only (a value is the person's text and is never echoed or logged)."""
    if request.headers.get("content-type", "").split(";")[0].strip().lower() != "application/json":
        raise HTTPException(status_code=415, detail="Send application/json.")
    declared = request.headers.get("content-length", "")
    if declared.isdigit() and int(declared) > MAX_BODY_BYTES:
        raise HTTPException(status_code=413, detail="body_too_large")
    chunks: list[bytes] = []
    size = 0
    async for chunk in request.stream():
        size += len(chunk)
        if size > MAX_BODY_BYTES:
            raise HTTPException(status_code=413, detail="body_too_large")
        chunks.append(chunk)
    try:
        body = json.loads(b"".join(chunks), parse_constant=_no_constant)
    except (ValueError, RecursionError):
        raise Refusal(422, "invalid_settings", code="invalid_settings", fields=["body"]) from None
    if not (isinstance(body, dict) and conforms(f"{SCHEMA}#/$defs/update", body)):
        raise Refusal(422, "invalid_settings", code="invalid_settings", fields=_shape_fields(body))
    return body


def _no_constant(name: str) -> Any:
    raise ValueError(name)  # NaN and Infinity are not JSON


router = APIRouter(route_class=_PeopleRoute)
Principal = Annotated[deps.Principal, Depends(deps.get_current_principal)]


def _store(stores: Annotated[PeopleStores, Depends(deps.get_people_stores)]) -> SettingsStore:
    return settings_store_of(stores)


Settings = Annotated[SettingsStore, Depends(_store)]


@router.get(ROUTE)
def get_settings(principal: Principal, store: Settings) -> dict[str, Any]:
    """The caller's saved document, or the unsaved defaults (version 0): never a claim that anything was saved."""
    if principal.demo_session:  # replay-only, stores nothing (DEMO-EPHEMERAL)
        return defaults(principal.user_id)
    try:
        stored = store.read(deps.ORG_ID, principal.user_id)
    except Exception:
        raise HTTPException(status_code=503, detail="unavailable") from None
    return stored if stored is not None else defaults(principal.user_id)


@router.put(ROUTE, dependencies=[Depends(write_limit)])
async def put_settings(
    request: Request, principal: Principal, store: Settings, clock: Annotated[Any, Depends(deps.get_clock)]
) -> dict[str, Any]:
    """Whole, checked and atomic (USET-02): the stored version + 1 on success, the stored document untouched on any
    refusal. The answer is the stored document."""
    if principal.demo_session:
        raise Refusal(403, "Sign in with Google to save settings.", code="full_session_required")
    update = await _body(request)
    org, uid = deps.ORG_ID, principal.user_id
    try:
        held = await run_in_threadpool(store.read, org, uid)
    except Exception:
        raise HTTPException(status_code=503, detail="unavailable") from None
    current = held["version"] if held is not None else 0
    if update["version"] != current or current >= VERSION_MAX:
        raise Refusal(409, "version_conflict", code="version_conflict", version=current)
    if (field := refused_field(update)) is not None:
        raise Refusal(422, "invalid_settings", code="invalid_settings", fields=[field])
    document = {
        "owner_id": uid, "org_id": org, "version": current + 1, "profile": update["profile"],
        "notifications": update["notifications"], "quiet_hours": update["quiet_hours"], "updated_at": clock(),
    }  # fmt: skip
    if not conforms(SCHEMA, document):  # a broken clock is a fixed 503, never a stored bad document
        raise HTTPException(status_code=503, detail="unavailable")
    try:
        stored = await run_in_threadpool(lambda: store.write(org, uid, expected_version=current, document=document))
    except Exception:
        raise HTTPException(status_code=503, detail="unavailable") from None
    if not stored:  # a rival write landed between the read and the write
        raise Refusal(409, "version_conflict", code="version_conflict", version=current + 1)
    return document
