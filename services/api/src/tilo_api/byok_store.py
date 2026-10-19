"""The org model key's records and the vault seam (ADR-0041 decision 2; BYOK-3a). SECURITY PATH: credential handling.

Three seams, none of which holds a key in tilo-api in production:

* `ModelKeyVault`: put / remove / status, tilo-api's side of tilo-connectors' `model-keys` routes. The deployed
  implementation does not exist yet (BYOK-4 and the contracts it needs); `MemoryModelKeyVault` is the in-memory vault
  of the ADR's slice, for dev and tests, and doubles as the proxy `ModelCallTransport`, so the whole path can be
  exercised with no network, no real key and no paid call.
* `OrgKeyStore`: the reference record `orgs/{org}/model_keys/models` and the audit entries. A reference holds no key
  character, length, hash or last four (BK-04). The deployed Firestore store is not built; `memory_org_key_store`
  is refused when deployed (503 `not_configured`, never memory).
* the act limiter: at most 5 widening key acts per org per hour (BK-08).
"""

from __future__ import annotations

import copy
import threading
import uuid
from collections import deque
from collections.abc import Mapping
from dataclasses import asdict, dataclass, replace
from typing import Any, Literal, Protocol

from tilo_providers.byok import ProxyRefusal
from tilo_providers.interfaces import GenerateRequest

SLOT = "models"  # BK: one slot, one active key per org
STATES = ("unverified", "active", "paused", "invalid")
ACTS_PER_HOUR = 5  # BK-08, widening acts only: a revocation is never rate-limited
WINDOW_S = 3600


@dataclass(frozen=True)
class KeyReference:
    """The Firestore reference (decision 2). Every field is a choice or a stamp; none is derived from the key."""

    bundle_id: str
    auth_mode: Literal["api_key", "vertex_iam"]
    project_id: str | None  # vertex_iam only: a Google project id, not a secret
    status: str  # one of STATES; a removed key has no record at all
    secret_version: int
    set_by: str
    set_at: str
    rotated_at: str | None
    day_cap_credits: int
    fallback_to_tilo: bool
    consent_version: int
    refusals: int = 0
    last_error: str | None = None  # a fixed code
    last_used_at: str | None = None
    rev: int = 1

    def active(self) -> bool:
        return self.status == "active"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def bumped(self, **changes: Any) -> KeyReference:
        return replace(self, **changes, rev=self.rev + 1)


class VaultRefused(Exception):
    """A fixed `code` from the vault: `key_refused` (the provider refused it) or `unavailable`."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


@dataclass(frozen=True)
class VaultPut:
    secret_version: int
    validated: bool


@dataclass(frozen=True)
class VaultStatus:
    state: Literal["none", "active", "unverified", "disabled"]
    secret_version: int | None


class OrgKeyStore:
    """In-memory reference, audit and act-limit store. Org-keyed everywhere: no method takes a user to look up."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._refs: dict[str, KeyReference] = {}
        self._audit: dict[str, list[dict[str, Any]]] = {}
        self._acts: dict[str, deque[float]] = {}

    def get(self, org_id: str) -> KeyReference | None:
        with self._lock:
            return self._refs.get(org_id)

    def cas(self, org_id: str, record: KeyReference, *, expected_rev: int) -> bool:
        """Stores `record` only if the held record is at `expected_rev` (0 when there is none)."""
        with self._lock:
            held = self._refs.get(org_id)
            if (held.rev if held is not None else 0) != expected_rev:
                return False
            self._refs[org_id] = record
            return True

    def delete(self, org_id: str) -> None:
        with self._lock:
            self._refs.pop(org_id, None)

    def audit(self, org_id: str, entry: Mapping[str, Any]) -> None:
        with self._lock:
            self._audit.setdefault(org_id, []).append(copy.deepcopy(dict(entry)))

    def audit_entries(self, org_id: str) -> list[dict[str, Any]]:
        with self._lock:
            return copy.deepcopy(self._audit.get(org_id, []))

    def note_act(self, org_id: str, now: float) -> int | None:
        """Counts one widening act, or returns the seconds to wait (the refused one is not counted)."""
        with self._lock:
            hits = self._acts.setdefault(org_id, deque())
            while hits and hits[0] <= now - WINDOW_S:
                hits.popleft()
            if len(hits) >= ACTS_PER_HOUR:
                return max(1, int(hits[0] + WINDOW_S - now) + 1)
            hits.append(now)
            return None


class ModelKeyVault(Protocol):
    """tilo-api's side of connectors' `put`, `remove` and `status` (ADR-0041 decision 2); put may raise VaultRefused."""

    def put(self, org_id: str, slot: str, *, mode: str, key: str | None, project_id: str | None) -> VaultPut: ...
    def remove(self, org_id: str, slot: str, secret_version: int | None = None) -> bool: ...
    def status(self, org_id: str, slot: str) -> VaultStatus: ...


class MemoryModelKeyVault:
    """The in-memory vault and connectors double (BYOK slice, dev and CI): per org, numbered versions, each enabled
    or disabled. A rotation disables every earlier version; a removal destroys them all (never left `enabled`)."""

    def __init__(self, *, validates: bool = True, accepts: Any = None) -> None:
        self._lock = threading.Lock()
        self._versions: dict[str, dict[int, dict[str, Any]]] = {}
        self.validates, self._accepts = validates, accepts or (lambda _key: True)
        self.calls: list[tuple[str, str]] = []  # (org_id, profile_id) of each generate, for tests

    def put(self, org_id: str, slot: str, *, mode: str, key: str | None, project_id: str | None) -> VaultPut:
        if mode == "api_key" and (key is None or not self._accepts(key)):
            raise VaultRefused("key_refused")
        with self._lock:
            versions = self._versions.setdefault(org_id, {})
            version = max(versions, default=0) + 1
            enabled = self.validates  # validation runs only when the process may go live (EFF-01)
            displaced = [v for v, held in versions.items() if enabled and held["enabled"]]
            for v in displaced:  # a rotation disables every earlier version
                versions[v]["enabled"] = False
            versions[version] = {
                "mode": mode, "key": key, "project": project_id, "enabled": enabled, "displaced": displaced,
            }  # fmt: skip
            return VaultPut(version, enabled)

    def remove(self, org_id: str, slot: str, secret_version: int | None = None) -> bool:
        with self._lock:
            versions = self._versions.get(org_id, {})
            if secret_version is None:
                removed = bool(versions)
                self._versions.pop(org_id, None)
                return removed
            gone = versions.pop(secret_version, None)
            if gone is None:
                return False
            for v in gone["displaced"]:  # the compensating act: the key this version displaced stays the active one
                if v in versions:
                    versions[v]["enabled"] = True
            return True

    def status(self, org_id: str, slot: str) -> VaultStatus:
        with self._lock:
            versions = self._versions.get(org_id, {})
            if not versions:
                return VaultStatus("none", None)
            latest = max(versions)
            return VaultStatus("active" if versions[latest]["enabled"] else "unverified", latest)

    def versions(self, org_id: str) -> dict[int, bool]:  # test view: version -> enabled
        with self._lock:
            return {v: bool(row["enabled"]) for v, row in self._versions.get(org_id, {}).items()}

    def generate(
        self, *, org_id: str, slot: str, run_id: str, profile_id: str, request: GenerateRequest
    ) -> Mapping[str, Any]:
        """The proxy route (variant P): reads the org's own key here and answers text and usage only."""
        with self._lock:
            versions = self._versions.get(org_id, {})
            live = [row for row in versions.values() if row["enabled"]]
            self.calls.append((org_id, profile_id))
        if not live:
            raise ProxyRefusal("no_key" if not versions else "unverified")
        return {"text": f"[byok-vault:{uuid.uuid4().hex[:6]}]", "usage": {"input_tokens": 3, "output_tokens": 2}}
