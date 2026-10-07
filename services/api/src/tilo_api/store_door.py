"""The one door to tilo-api's durable store (PROD-WIRE, ADR-0026 decision 1; same pattern as ADR-0023's schedule store).

`open_api_store` is the only code in tilo-api that builds a Firestore client. It opens one only for explicit config:
`TILO_API_STORE=firestore` plus a `TILO_FIRESTORE_PROJECT` that matches the schedule store's project regex. Outside
Cloud Run (no `K_SERVICE`) it opens only the emulator (`FIRESTORE_EMULATOR_HOST` and a `demo-` project), so a laptop
with credentials never reaches a live project. There is no `memory` value (memory is dev mode's), `K_SERVICE` alone
opens nothing, and importing this module builds no client. Anything else raises `ApiStoreNotConfigured`: callers
answer 503 `not_configured`, never cache the refusal and never fall back to memory. The harness `FirestoreStore` and
its own guard are untouched.

Slice 1a ships the door and the holder; the Firestore-backed `Store` that fills `FirestoreApiStore` is slice 1b.
"""

from __future__ import annotations

import logging
import os
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any

from fastapi import HTTPException
from tilo_harness.schedule_store import _PROJECT as GCP_PROJECT  # one project-id shape for both Firestore doors

logger = logging.getLogger("tilo_api.store_door")

ENV_STORE, ENV_PROJECT = "TILO_API_STORE", "TILO_FIRESTORE_PROJECT"


class ApiStoreNotConfigured(RuntimeError):
    """No explicit, valid, permitted store config: nothing is opened (503 `not_configured`)."""


class ApiStoreUnavailable(HTTPException):
    """The config was valid but the client could not be built (no credentials, no network): 503 `store_unavailable`."""

    def __init__(self) -> None:
        super().__init__(status_code=503, detail="store_unavailable")


@dataclass(frozen=True)
class FirestoreApiStore:
    """The opened handle: the project and its Firestore client. Slice 1b adds the records and events backends."""

    project: str
    client: Any


def open_api_store(
    env: Mapping[str, str] | None = None, *, firestore_client_factory: Callable[[str], Any] | None = None
) -> FirestoreApiStore:
    values = os.environ if env is None else env
    project = values.get(ENV_PROJECT, "")
    if values.get(ENV_STORE) != "firestore" or not GCP_PROJECT.fullmatch(project):
        raise ApiStoreNotConfigured(f"set {ENV_STORE}=firestore and {ENV_PROJECT} to a project id")
    emulator = values.get("FIRESTORE_EMULATOR_HOST", "")
    if values.get("K_SERVICE"):
        if emulator or os.environ.get("FIRESTORE_EMULATOR_HOST"):  # a deployed process never talks to an emulator host
            raise ApiStoreNotConfigured("FIRESTORE_EMULATOR_HOST is set on Cloud Run")
    elif not (emulator and project.startswith("demo-")):
        raise ApiStoreNotConfigured("outside Cloud Run only the emulator and a demo- project open")
    if "GOOGLE_CLOUD_PROJECT" in values and values["GOOGLE_CLOUD_PROJECT"] != project:
        raise ApiStoreNotConfigured(f"{ENV_PROJECT} must equal GOOGLE_CLOUD_PROJECT")  # the project is pinned
    if (
        env is not None
        and firestore_client_factory is None
        and os.environ.get("FIRESTORE_EMULATOR_HOST", "") != emulator
    ):
        raise ApiStoreNotConfigured("the client reads os.environ, which names another emulator host than env")
    try:
        if firestore_client_factory is not None:
            client = firestore_client_factory(project)
        else:
            from google.cloud import firestore

            client = firestore.Client(project=project)
    except Exception as exc:  # no credentials or no network: closed, and never the text
        logger.warning("api store client unavailable (%s)", type(exc).__name__)
        raise ApiStoreUnavailable from exc
    return FirestoreApiStore(project=project, client=client)
