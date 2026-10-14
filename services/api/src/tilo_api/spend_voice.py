"""SEC-16 / FR-MTG-11 (M2b, BQ-M2-1): the Gemini Live voice's spend hook over the uid ledger. `LiveVoiceSpend` is a
`tilo_providers.voice.LiveVoiceMeter`: one spoken reply is one unit, asked of the same `SpendGuard` every other live
call goes through. Deterministic code; the provider is never reached when it answers no.

A process that speaks with the Live voice builds one per meeting (the owner's uid, org and a run id for the meeting)
over `deps.get_spend_cap_ledger()` and passes it as `meter=` to `tilo_providers.voice.build_voice_provider`. It
refuses (returns None) for a capped uid, with the replay-only switch set in either store, with less than one unit of
headroom, and whenever the ledger or the switch store cannot be read: fail closed, never live. Until PL-06 prices the
Live profile, a settled reply costs the whole `unit_reserve_minor` (BQ-SEC16-1), the same rule `spend_units` applies
to an unpriced call; a `price` hook may turn the reply's usage into INR minor units once a quote is approved. The
provider settles (never releases) once the text was sent, even when no reply or usage came back (input tokens are
billable): an empty usage prices to nothing and so charges the whole reserve."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from typing import cast

from tilo_api import spend


class LiveVoiceSpend:
    def __init__(
        self,
        guard: spend.SpendGuard,
        *,
        uid: str,
        run_id: str,
        org_id: str,
        unit_minor: int,
        price: Callable[[Mapping[str, int]], int | None] | None = None,
    ) -> None:
        self._guard, self._uid, self._run_id, self._org_id = guard, uid, run_id, org_id
        self._unit, self._price = unit_minor, price
        self.refusal: str | None = None  # after a None `reserve`: capped, replay_only or unavailable (ADR-0042)

    def reserve(self) -> spend.UnitPlan | None:
        if self._guard.uid_capped(self._uid):
            self.refusal = "capped"
            return None
        if not self._guard.live_allowed(self._uid):
            self.refusal = "replay_only" if self._guard.replay_only() else "unavailable"
            return None
        plan = self._guard.begin_unit(
            "live", uid=self._uid, run_id=self._run_id, org_id=self._org_id, estimate_minor=self._unit,
            at=datetime.now(UTC),
        )  # fmt: skip
        if plan.mode == "live" and plan.reservation is not None:
            return plan
        self.refusal = plan.reason if plan.reason in ("replay_only", "unavailable") else "capped"
        return None

    def settle(self, hold: object, usage: Mapping[str, int]) -> None:
        minor = self._price(usage) if self._price is not None else None
        charged = minor if type(minor) is int and minor >= 1 else self._unit  # unpriced or nonsense: the whole reserve
        self._guard.settle_unit(cast(spend.UnitPlan, hold), charged)

    def release(self, hold: object) -> None:
        self._guard.abort_unit(cast(spend.UnitPlan, hold))
