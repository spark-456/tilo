"""User erasure and the script that verifies it (FR-MEM-09, PRD 13.5, 15.1, 16.5).

Deleting a user removes their records from every store within 30 days. Rules that keep this safe:
- `erase_user` takes an `ErasureRequest`, which exists only for a well-formed user id and an aware time. Who may ask
  (authentication, authorisation) is the caller's job and belongs to the API ticket: this module has no endpoint and
  no trigger of its own.
- A record is the user's only when its `user_id` equals the request's. Records with no owner are nobody's and are
  never deleted here. A blank, None or wildcard id never reaches a store.
- The registry must hold every name in `REQUIRED_STORES`, else `IncompleteRegistry` is raised before any delete.
- Done means a fresh re-read finds nothing, never that `delete()` returned. `verify_erasure` is read-only.
- Reports, problems and CLI output hold store names and counts only; exception messages are dropped.

`remaining[store] == UNREADABLE` (-1) means the store could not be read, so nothing can be claimed about it.
"""

from __future__ import annotations

import json
import sys
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, TextIO

from .retention import USER_ID_PATTERN, RetentionStore

ERASURE_DEADLINE_DAYS = 30
UNREADABLE = -1
# PRD 13.1/13.2: Firestore, the BigQuery ledger, Memory Bank, and Cloud Storage for archive, artifacts and cache blobs.
REQUIRED_STORES: frozenset[str] = frozenset(
    {"firestore", "bigquery_ledger", "memory_bank", "gcs_archive", "gcs_artifacts", "gcs_cache"}
)
EXIT_OK, EXIT_DATA_REMAINS, EXIT_BAD_INPUT, EXIT_INCOMPLETE = 0, 1, 2, 3


class IncompleteRegistry(ValueError):
    """The registry lacks a required store (or one is not a store). Names the stores, never any data."""


def _check_user(user_id: object) -> str:
    if type(user_id) is not str or USER_ID_PATTERN.fullmatch(user_id) is None:  # exact str: no subclass with its own ==
        raise ValueError("user id must look like u_<letters, digits or _>")
    return user_id


def _check_aware(value: object, what: str) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None:
        raise ValueError(f"{what} must be a timezone-aware datetime")
    return value


@dataclass(frozen=True)
class ErasureRequest:
    """An already-authorised request to erase one user. Validated on construction, so no invalid one exists."""

    user_id: str
    requested_at: datetime

    def __post_init__(self) -> None:
        _check_user(self.user_id)
        _check_aware(self.requested_at, "requested_at")

    @property
    def deadline(self) -> datetime:
        return self.requested_at + timedelta(days=ERASURE_DEADLINE_DAYS)


def request_erasure(user_id: str, *, requested_at: datetime) -> ErasureRequest:
    return ErasureRequest(user_id, requested_at)


@dataclass(frozen=True)
class ErasureReport:
    complete: bool
    removed: dict[str, int]
    remaining: dict[str, int]
    failures: dict[str, str]  # store -> exception type name only
    late: bool


@dataclass(frozen=True)
class Verification:
    ok: bool
    remaining: dict[str, int]
    problems: list[str] = field(default_factory=list)


def _check_registry(registry: Mapping[str, RetentionStore]) -> None:
    if not isinstance(registry, Mapping):
        raise IncompleteRegistry("registry must map store names to stores")
    bad = sorted(
        name
        for name in REQUIRED_STORES
        if not (
            callable(getattr(registry.get(name), "records", None)) and callable(getattr(registry[name], "delete", None))
        )
    )
    if bad:
        raise IncompleteRegistry("registry lacks required store(s): " + ", ".join(bad))


def _owned_ids(store: RetentionStore, user_id: str) -> set[str]:
    return {r.record_id for r in list(store.records()) if r.user_id == user_id}


def erase_user(registry: Mapping[str, RetentionStore], request: ErasureRequest, *, now: datetime) -> ErasureReport:
    """Collect the user's ids from every store first, then delete, then re-read every store. Collecting before any
    delete means no store's ownership lookup (for example a ledger row owned through a World record in another store)
    can be erased out from under another store, whatever the registry order."""
    if not isinstance(request, ErasureRequest):
        raise ValueError("an ErasureRequest is required")
    user_id = _check_user(request.user_id)  # also catches a request mutated after construction
    _check_aware(request.requested_at, "requested_at")
    deadline = request.requested_at + timedelta(days=ERASURE_DEADLINE_DAYS)
    _check_aware(now, "now")
    _check_registry(registry)
    failures: dict[str, str] = {}
    unreadable: set[str] = set()
    owned: dict[str, set[str]] = {}
    for name, store in registry.items():  # phase 1: read everything before anything is deleted
        try:
            owned[name] = _owned_ids(store, user_id)
        except Exception as exc:  # noqa: BLE001 - only the type name is kept
            failures[name] = type(exc).__name__
            unreadable.add(name)
    for name, ids in owned.items():  # phase 2: delete
        for record_id in sorted(ids):
            try:
                registry[name].delete(record_id)
            except Exception as exc:  # noqa: BLE001 - keep going
                failures[name] = type(exc).__name__
    removed: dict[str, int] = {}
    remaining: dict[str, int] = {}
    for name, store in registry.items():  # phase 3: the independent re-read decides, not the delete calls
        try:
            after = _owned_ids(store, user_id) if name not in unreadable else None
        except Exception as exc:  # noqa: BLE001
            failures.setdefault(name, type(exc).__name__)
            after = None
        if after is None:
            removed[name], remaining[name] = 0, UNREADABLE
        else:
            removed[name], remaining[name] = len(owned[name] - after), len(after)
    complete = all(count == 0 for count in remaining.values())
    return ErasureReport(complete, removed, remaining, failures, late=now > deadline)


def verify_erasure(registry: Mapping[str, RetentionStore], user_id: str) -> Verification:
    """Re-read every store; never deletes. `ok` only when every store, required or extra, holds nothing of the user."""
    uid = _check_user(user_id)
    _check_registry(registry)
    remaining: dict[str, int] = {}
    problems: list[str] = []
    for name, store in registry.items():
        try:
            remaining[name] = len(_owned_ids(store, uid))
        except Exception as exc:  # noqa: BLE001
            remaining[name] = UNREADABLE
            problems.append(f"{name}: store could not be read ({type(exc).__name__})")
            continue
        if remaining[name]:
            problems.append(f"{name}: {remaining[name]} record(s) of the user remain")
    return Verification(not problems, remaining, problems)


HELP = """usage: python -m tilo_memory.erasure verify <user_id>

verify  re-read every store and report whether any record of the user is left.
        Prints JSON {"ok", "stores": {name: remaining}, "problems"}; store names and counts only.
        Exit 0: nothing left. 1: data remains. 2: bad input. 3: store registry incomplete or not configured.
"""


def main(argv: list[str], *, registry: Mapping[str, RetentionStore] | None = None, stdout: TextIO | None = None) -> int:
    out = stdout if stdout is not None else sys.stdout

    def emit(payload: dict[str, Any]) -> None:
        print(json.dumps(payload), file=out)

    if argv[:1] in (["-h"], ["--help"]):
        print(HELP, file=out, end="")
        return EXIT_OK
    if len(argv) != 2 or argv[0] != "verify":
        emit({"ok": False, "stores": {}, "problems": ["usage: verify <user_id>"]})
        return EXIT_BAD_INPUT
    try:
        result = verify_erasure({} if registry is None else registry, argv[1])
    except IncompleteRegistry as exc:
        emit({"ok": False, "stores": {}, "problems": [str(exc)]})
        return EXIT_INCOMPLETE
    except ValueError:  # the message never echoes the argument
        emit({"ok": False, "stores": {}, "problems": ["invalid user id"]})
        return EXIT_BAD_INPUT
    emit({"ok": result.ok, "stores": result.remaining, "problems": result.problems})
    return EXIT_OK if result.ok else EXIT_DATA_REMAINS


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
