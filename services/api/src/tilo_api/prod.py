"""The production composition root's Firestore seam (PROD-WIRE 3, ADR-0026 decision 1): one Firestore client per project
per process, and the one guard every door obeys; plus the Firestore-backed SEC-15 access store.

`firestore_client(project)` reads `os.environ` on every call, before the cache, and refuses with
`FirestoreNotConfigured` unless, in order: the project is a valid id (`store_door.GCP_PROJECT`'s shape); on a managed
runtime (`K_SERVICE` or `CLOUD_RUN_JOB` present, even empty) `FIRESTORE_EMULATOR_HOST` is absent (the library enters
emulator mode whenever the variable exists, even empty); a live project opens only when `K_SERVICE` is non-empty, and
anywhere else only an emulator host AND a `demo-` project open, so a laptop that holds real credentials never reaches a
live project; `GOOGLE_CLOUD_PROJECT`, when set, equals the project. A client is built once per project and emulator
host, single-flight, by `build_client`; a build that raises is not cached and surfaces as `FirestoreUnavailable`,
never with the exception text (only its type is logged).

`store_door.client_factory` and the people door's default factory delegate here lazily (this module imports both of
them), so the api store, the people stores and the access store share one client object.
"""

from __future__ import annotations

import logging
import os
import random
import re
import threading
import time
from typing import Any

from google.api_core import exceptions as gexc
from google.auth import exceptions as gauth_exc

from tilo_api.people_firestore import PeopleStoreNotConfigured
from tilo_api.store_door import GCP_PROJECT, ApiStoreNotConfigured, ApiStoreUnavailable

logger = logging.getLogger("tilo_api.prod")


class FirestoreNotConfigured(ApiStoreNotConfigured, PeopleStoreNotConfigured):
    """The environment does not permit a Firestore client: both doors answer 503 `not_configured`."""


class FirestoreUnavailable(ApiStoreUnavailable):
    """A permitted client could not be built (no credentials, no network): 503 `store_unavailable`, no detail."""


def build_client(project: str) -> Any:
    """The process's Firestore client for `project`, with the runtime identity's ADC; tests replace this."""
    from google.cloud import firestore

    return firestore.Client(project=project)


_clients: dict[tuple[str, str | None], Any] = {}  # keyed by the project and the emulator host it was built for
_building = threading.Lock()


def _guard(project: str) -> str | None:
    """Raises `FirestoreNotConfigured` unless this environment may hold a client for `project`; returns the emulator
    host (None when it is absent or empty)."""
    if not isinstance(project, str) or GCP_PROJECT.fullmatch(project) is None:
        raise FirestoreNotConfigured("not a project id")
    emulator = os.environ.get("FIRESTORE_EMULATOR_HOST")
    if emulator is not None and ("K_SERVICE" in os.environ or "CLOUD_RUN_JOB" in os.environ):
        raise FirestoreNotConfigured("FIRESTORE_EMULATOR_HOST is set on a managed runtime")
    if not os.environ.get("K_SERVICE") and not (emulator and project.startswith("demo-")):
        raise FirestoreNotConfigured("outside Cloud Run only the emulator and a demo- project open")
    if "GOOGLE_CLOUD_PROJECT" in os.environ and os.environ["GOOGLE_CLOUD_PROJECT"] != project:
        raise FirestoreNotConfigured("the project must equal GOOGLE_CLOUD_PROJECT")
    return emulator or None


def firestore_client(project: str) -> Any:
    """The one client for `project` and this emulator host in this process (guarded on every call)."""
    key = (project, _guard(project))
    client = _clients.get(key)
    if client is not None:
        return client
    with _building:
        client = _clients.get(key)
        if client is None:
            try:
                client = build_client(project)
            except Exception as exc:  # no credentials or no network: closed, never cached, never the text
                logger.warning("firestore client unavailable (%s)", type(exc).__name__)
                raise FirestoreUnavailable from None
            _clients[key] = client
        return client


def reset() -> None:
    """Forgets every cached client (a test starts from a cold process)."""
    with _building:
        _clients.clear()


_DECLARATIONS = ("visitor", "judge")
_ATTEMPTS = 8
_LIBRARY_ERRORS = (gexc.GoogleAPICallError, gexc.RetryError, gauth_exc.GoogleAuthError)
_RESERVED_ID = re.compile(r"__.*__", re.DOTALL)


def _is_document_id(value: object) -> bool:
    """What Firestore accepts as a document id: not empty, no `/`, not `.` or `..`, not `__.*__`, at most 1500 bytes."""
    if not isinstance(value, str) or not value or "/" in value or value in {".", ".."}:
        return False
    if _RESERVED_ID.fullmatch(value):
        return False
    try:
        return len(value.encode("utf-8")) <= 1500
    except UnicodeEncodeError:  # a lone surrogate
        return False


class FirestoreAccessStore:
    """SEC-15's declaration kept at `orgs/{org}/access/{uid}` (field `declaration`). First write wins: `declare` is one
    create-if-absent and, on `AlreadyExists`, a read-back. It never calls `set`, `update` or `delete`. A uid Firestore
    refuses as a document id is a `ValueError` before any path is built; a Google API error is `FirestoreUnavailable`
    (503, only its type logged)."""

    def __init__(self, client: Any, org_id: str = "org_tilo") -> None:
        self._client, self._org = client, org_id

    def _ref(self, user_id: str) -> Any:
        if not _is_document_id(user_id):
            raise ValueError("not a Firestore document id")
        return self._client.document(f"orgs/{self._org}/access/{user_id}")

    @staticmethod
    def _declaration(snapshot: Any) -> str | None:
        data = snapshot.to_dict() if snapshot.exists else None
        value = data.get("declaration") if isinstance(data, dict) else None
        return value if isinstance(value, str) and value in _DECLARATIONS else None  # fail closed on anything else

    def get(self, user_id: str) -> Any:
        ref = self._ref(user_id)
        try:
            return self._declaration(ref.get())
        except _LIBRARY_ERRORS as exc:
            logger.warning("access store unavailable (%s)", type(exc).__name__)
            raise FirestoreUnavailable from None

    def declare(self, user_id: str, declaration: Any) -> Any:
        ref = self._ref(user_id)
        if declaration not in _DECLARATIONS:
            raise ValueError("a declaration is visitor or judge")
        try:
            for attempt in range(_ATTEMPTS):
                try:
                    ref.create({"declaration": declaration})
                    return declaration
                except gexc.AlreadyExists:
                    stored = self._declaration(ref.get())
                    if stored is None:  # a document someone wrote by hand: never overwritten, never believed
                        logger.warning("stored access declaration is malformed")
                        raise FirestoreUnavailable from None
                    return stored
                except gexc.Aborted:  # contention on the one document (the emulator's lock timeout): create again
                    time.sleep(random.uniform(0, 0.05 * (attempt + 1)))  # noqa: S311 - jitter, not security
        except _LIBRARY_ERRORS as exc:
            logger.warning("access store unavailable (%s)", type(exc).__name__)
            raise FirestoreUnavailable from None
        logger.warning("access declaration contended beyond %d attempts", _ATTEMPTS)
        raise FirestoreUnavailable from None
