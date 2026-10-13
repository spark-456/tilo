"""The taught-skill store on Firestore, and its one door (SKILLS-2b, FR-SKL-04, BQ-SKILLS-1; ADR-0026, ADR-0034).

Layout: `orgs/{org}/taught_skills/{id}` holds the validated TaughtSkill record verbatim, no extra field, with the
subcollections `real_runs`, `ratings` and `fixes` of `skill_ledger.py` (FR-SKL-05, ADR-0037). A new id is
written with `create` (an id collision is a `SkillStoreError`, never an overwrite); a second `put` of an id replaces the
document only when the stored owner is the same. Reads are single-field queries (`owner ==`, `scope.team in` chunks of
at most 30, Firestore's limit), merged, de-duplicated and sorted by (name, id). Whatever the client raises leaves as a
`SkillStoreError` with no text and no cause. Importing this module builds no client.

`open_skill_store` is the door: `TILO_SKILLS_STORE=firestore` plus a `TILO_FIRESTORE_PROJECT` opens a client (outside
Cloud Run only the emulator with a `demo-` project, the rule of `store_door`); `memory` is refused when deployed.
Anything else raises `SkillStoreNotConfigured`; the caller answers 503 `not_configured`.
"""

from __future__ import annotations

import copy
import os
import re
from collections.abc import Callable, Iterable, Mapping
from typing import Any

from google.api_core import exceptions as gexc
from google.cloud import firestore
from tilo_harness.schedule_store import _PROJECT as GCP_PROJECT

from tilo_api.skill_ledger import SkillLedger, SkillRefused, Tx
from tilo_api.skill_store import MemorySkillStore, SkillStore, SkillStoreError

ENV_STORE, ENV_PROJECT = "TILO_SKILLS_STORE", "TILO_FIRESTORE_PROJECT"
_ORG = re.compile(r"org_[0-9A-Za-z_]{1,48}")
_ID = re.compile(r"tsk_[0-9A-Za-z_]{1,48}")
_IN_LIMIT = 30


class SkillStoreNotConfigured(RuntimeError):
    """No explicit, valid, permitted store config: nothing is opened (503 `not_configured`)."""


def _failed() -> SkillStoreError:
    return SkillStoreError("the skill store is unavailable")


def _sort_key(row: dict[str, Any]) -> tuple[str, str]:
    return (str(row.get("name", "")), str(row.get("id", "")))


class FirestoreSkillStore(SkillLedger):
    def __init__(self, client: Any) -> None:
        self._client = client

    @staticmethod
    def _addressable(org: Any) -> bool:
        return isinstance(org, str) and _ORG.fullmatch(org) is not None

    def put(self, record: dict[str, Any]) -> None:
        org, skill_id = record.get("org_id"), record.get("id")
        if not (self._addressable(org) and isinstance(skill_id, str) and _ID.fullmatch(skill_id)):
            raise SkillStoreError("the skill has no addressable id")
        data = copy.deepcopy(record)
        try:
            ref = self._client.document(f"orgs/{org}/taught_skills/{skill_id}")
            try:
                ref.create(data)
                return
            except gexc.AlreadyExists:
                pass
            held = ref.get().to_dict()
            if not held or held.get("owner") != record.get("owner"):
                raise SkillStoreError("that skill id is taken")
            ref.set(data)
        except SkillStoreError:
            raise
        except Exception:
            raise _failed() from None

    def get(self, org: str, skill_id: str) -> dict[str, Any] | None:
        if not (isinstance(skill_id, str) and _ID.fullmatch(skill_id)) or not self._addressable(org):
            return None
        try:
            snap = self._client.document(f"orgs/{org}/taught_skills/{skill_id}").get()
            return snap.to_dict() if snap.exists else None
        except Exception:
            raise _failed() from None

    def _where(self, org: str, field: str, op: str, value: Any) -> list[dict[str, Any]]:
        from google.cloud.firestore_v1.base_query import FieldFilter  # noqa: PLC0415 - lazy: no client at import

        if not self._addressable(org):
            return []
        col = self._client.collection(f"orgs/{org}/taught_skills")
        return [s.to_dict() for s in col.where(filter=FieldFilter(field, op, value)).stream()]

    def list_for_owner(self, org: str, owner: str) -> list[dict[str, Any]]:
        try:
            return sorted(self._where(org, "owner", "==", owner), key=_sort_key)
        except Exception:
            raise _failed() from None

    # -- FR-SKL-05/06: the ledger's two seams (skill_ledger.py); runs, ratings and fixes are subcollections -----------

    def _doc(self, path: str) -> dict[str, Any] | None:
        try:
            snap = self._client.document(path).get()
            return snap.to_dict() if snap.exists else None  # type: ignore[no-any-return]
        except Exception:
            raise _failed() from None

    def _children(self, path: str) -> list[dict[str, Any]]:
        try:
            return [s.to_dict() for s in self._client.collection(path).stream()]
        except Exception:
            raise _failed() from None

    def _atomic(self, work: Callable[[Tx], Any]) -> Any:
        """One Firestore transaction: the reads of `work`, then its writes; a concurrent write retries all of it."""
        from google.cloud.firestore_v1.base_query import FieldFilter  # noqa: PLC0415 - lazy: no client at import

        def run(transaction: Any) -> Any:
            def read(path: str) -> dict[str, Any] | None:
                snap = self._client.document(path).get(transaction=transaction)
                return snap.to_dict() if snap.exists else None  # type: ignore[no-any-return]

            def find(coll: str, field: str, value: Any) -> list[dict[str, Any]]:
                query = self._client.collection(coll).where(filter=FieldFilter(field, "==", value))
                return [s.to_dict() for s in query.stream(transaction=transaction)]

            tx = Tx(read, find)
            out = work(tx)
            for kind, path, doc in tx.writes:
                getattr(transaction, kind)(self._client.document(path), doc)
            return out

        try:
            return firestore.transactional(run)(self._client.transaction())
        except (SkillRefused, SkillStoreError):
            raise
        except Exception:
            raise _failed() from None

    def list_visible(self, org: str, user: str, team_ids: Iterable[str]) -> list[dict[str, Any]]:
        teams = sorted({t for t in team_ids if isinstance(t, str)})
        try:
            rows = self._where(org, "owner", "==", user)
            for i in range(0, len(teams), _IN_LIMIT):
                rows += self._where(org, "scope.team", "in", teams[i : i + _IN_LIMIT])
        except Exception:
            raise _failed() from None
        unique = {r.get("id"): r for r in rows if r.get("org_id") == org}
        return sorted(unique.values(), key=_sort_key)


def client_factory(project: str) -> Any:
    """The production root's shared client for `project`, built only on demand."""
    from tilo_api.prod import firestore_client  # noqa: PLC0415

    return firestore_client(project)


def open_skill_store(env: Mapping[str, str] | None = None) -> SkillStore:
    """The store the env names. Raises `SkillStoreNotConfigured` before any client is tried; a client that cannot be
    built raises whatever the factory raised (the caller backs off and never echoes it)."""
    values = os.environ if env is None else env
    kind = values.get(ENV_STORE, "")
    deployed = "K_SERVICE" in values or "CLOUD_RUN_JOB" in values
    if kind == "memory":
        if deployed:
            raise SkillStoreNotConfigured("the in-memory skill store is refused when deployed")
        return MemorySkillStore()
    project = values.get(ENV_PROJECT, "")
    if kind != "firestore" or not GCP_PROJECT.fullmatch(project):
        raise SkillStoreNotConfigured(f"set {ENV_STORE} to memory or firestore (with {ENV_PROJECT})")
    emulator = values.get("FIRESTORE_EMULATOR_HOST", "")
    if deployed:
        if emulator:
            raise SkillStoreNotConfigured("FIRESTORE_EMULATOR_HOST is set on Cloud Run")
    elif not (emulator and project.startswith("demo-")):
        raise SkillStoreNotConfigured("outside Cloud Run only the emulator and a demo- project open")
    if values.get("GOOGLE_CLOUD_PROJECT", project) != project:
        raise SkillStoreNotConfigured(f"{ENV_PROJECT} must equal GOOGLE_CLOUD_PROJECT")
    factory: Callable[[str], Any] = client_factory
    return FirestoreSkillStore(factory(project))
