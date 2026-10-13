"""The order of a model unit under BYOK (ADR-0041 decisions 6 and 7, BK-14 to BK-17; BYOK-3b). Deterministic code: no
model decides whose key a unit uses, whether it may run, or whether Tilo's key is tried. SECURITY PATH.

`plan_unit` is the ADR's table, in order:

1. a demo session, or a mode that is not live (the switch, a cap, no declaration): replay, as today, no BYOK;
2. BYOK off, no key for this org, a personal-scope unit (BQ-BYOK-3) or a role the bundle leaves out: Tilo's key under
   SEC-16, as today;
3. key active, role covered, the org's day cap not reached, connectors answering: the org's key, `payer: org_key`;
   SEC-16 is not consulted (BK-15) but the unit's mode (the shared replay switch, LIVE, the declaration) already was;
4. the key is paused, invalid, unverified or removed, connectors refused or is unreachable, or the cap is reached:
   REFUSED with a fixed code. No call is made and Tilo's key is not tried;
5. step 4 and the owner opted in (`fallback_to_tilo`): Tilo's key under SEC-16, per unit, with the reason.

The plan carries a reservation against the org's own day (`ByokSpend`): estimate plus 15%, committed at the actual
(MT-03). The Firestore transaction with the ledger row, the per-path wiring in the live run paths and `trace.payer` on
the event are not here (they need contract changes and the SEC-16 wiring of issue 935 first; docs/byok.md).
"""

from __future__ import annotations

import threading
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Literal

from tilo_providers.byok import ByokConfig, OrgBinding, OrgProviderSource

from tilo_api.byok_store import SLOT, KeyReference, ModelKeyVault

RESERVE_MARGIN = 1.15  # BK-16: estimate plus 15%
_STATE_CODE = {"paused": "key_paused", "invalid": "invalid_key", "unverified": "unverified"}


class ByokSpend:
    """`orgs/{org}/byok_spend/{utc day}`: reserved and committed credits of one org's own key. In memory here; the
    Firestore one must do reserve, commit and release as one transaction each, with the ledger row."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._committed: dict[tuple[str, str], float] = {}
        self._held: dict[tuple[str, str], float] = {}

    def reserve(self, org_id: str, day: str, credits: float, cap: int) -> bool:
        with self._lock:
            key = (org_id, day)
            if self._committed.get(key, 0.0) + self._held.get(key, 0.0) + credits > cap:
                return False
            self._held[key] = self._held.get(key, 0.0) + credits
            return True

    def commit(self, org_id: str, day: str, reserved: float, actual: float) -> None:
        """The actual is recorded in full, even over the reservation (an overrun is never hidden, MT-03)."""
        with self._lock:
            key = (org_id, day)
            self._held[key] = max(0.0, self._held.get(key, 0.0) - reserved)
            self._committed[key] = self._committed.get(key, 0.0) + max(0.0, actual)

    def release(self, org_id: str, day: str, reserved: float) -> None:
        with self._lock:
            key = (org_id, day)
            self._held[key] = max(0.0, self._held.get(key, 0.0) - reserved)

    def spent(self, org_id: str, day: str) -> float:
        with self._lock:
            return self._committed.get((org_id, day), 0.0) + self._held.get((org_id, day), 0.0)


@dataclass(frozen=True)
class ByokUnitPlan:
    payer: Literal["tilo", "org_key"]
    uses_tilo_meter: bool  # True: SEC-16's begin_unit/settle_unit and the Treasury apply (BK-15)
    refused: str | None = None  # a fixed code: the unit blocks (step 4)
    reason: str | None = None  # why Tilo's key runs a unit of a BYOK org (step 5), for the Trace
    binding: OrgBinding | None = None  # hand to `Router(org=...)`: only when payer is org_key
    reserved_credits: float = 0.0
    day: str | None = None
    org_id: str | None = None

    @property
    def blocked(self) -> bool:
        return self.refused is not None


_TILO = ByokUnitPlan("tilo", True)


def plan_unit(
    *,
    config: ByokConfig,
    ref: KeyReference | None,
    vault: ModelKeyVault,
    spend: ByokSpend,
    source: OrgProviderSource,
    org_id: str,
    run_id: str,
    role: str,
    mode: str,
    demo: bool,
    personal_scope: bool,
    estimate_credits: float,
    now: Callable[[], datetime] = lambda: datetime.now(UTC),
) -> ByokUnitPlan:
    # 1. replay as today: the shared switch, LIVE, the declaration and the demo session all arrive as `mode`/`demo`
    if demo or mode != "live":
        return _TILO
    # 2. Tilo's key as today: BYOK off, no key for this org, personal scope, or a role the bundle leaves out
    bundle = config.bundles.get(ref.bundle_id) if ref is not None else None
    if not config.enabled or ref is None or bundle is None or personal_scope or role not in bundle.roles:
        return _TILO
    # 3 and 4
    code = _refusal(ref, vault, org_id)
    day = now().astimezone(UTC).date().isoformat()
    reserve = max(0.0, estimate_credits) * RESERVE_MARGIN
    if code is None and not spend.reserve(org_id, day, reserve, ref.day_cap_credits):
        code = "cap_reached"
    if code is None:
        binding = OrgBinding(org_id=org_id, slot=SLOT, run_id=run_id, bundle=bundle, source=source)
        return ByokUnitPlan("org_key", False, binding=binding, reserved_credits=reserve, day=day, org_id=org_id)
    # 5. the owner's opt-in (a T3 act to turn on) lets this unit, never a call in flight, run on Tilo's key
    if ref.fallback_to_tilo:
        return ByokUnitPlan("tilo", True, reason=code)
    return ByokUnitPlan("tilo", False, refused=code)


def _refusal(ref: KeyReference, vault: ModelKeyVault, org_id: str) -> str | None:
    if ref.status != "active":
        return _STATE_CODE.get(ref.status, "invalid_key")
    try:  # variant P: connectors answers. Unreachable or unsure is a refusal, never a pass
        got = vault.status(org_id, SLOT)
    except Exception:  # noqa: BLE001
        return "unreachable"
    if got.state == "none":
        return "key_removed"
    return None if got.state == "active" else "unverified"


def settle_unit(plan: ByokUnitPlan, spend: ByokSpend, actual_credits: float) -> None:
    """An org-key unit's actual credits against the org's day; a Tilo-metered plan is settled by SEC-16 as before."""
    if plan.payer == "org_key" and plan.org_id is not None and plan.day is not None:
        spend.commit(plan.org_id, plan.day, plan.reserved_credits, actual_credits)


def abort_unit(plan: ByokUnitPlan, spend: ByokSpend) -> None:
    if plan.payer == "org_key" and plan.org_id is not None and plan.day is not None:
        spend.release(plan.org_id, plan.day, plan.reserved_credits)
