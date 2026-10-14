"""Owner-bound meeting preview factory over existing stores/outbox/policy (FR-MTG-08).

No route, dispatcher, provider or thread reader. The caller remains closed until
fresh publication and retention integration are reviewed together.
"""

from collections.abc import Callable
from datetime import datetime
from typing import Any, cast

import tilo_policy
from fastapi import HTTPException
from tilo_channels.autopilot import Autopilot, DraftContext, Preview
from tilo_channels.drafting import Drafter, DraftResult, DraftStore, _result
from tilo_connectors import Outbox
from tilo_policy.schemas import conforms

from tilo_api import deps
from tilo_api.draft_firestore import FirestoreDraftStore
from tilo_api.followup_autopilot_state import FirestoreCards, FirestoreStops
from tilo_api.followup_publication_ports import PublicationCards, PublicationOutbox, PublicationStops
from tilo_api.owner_minutes_caller import OwnerMinutesCaller


def _refuse(status: int = 404, detail: str = "not_found") -> HTTPException:
    return HTTPException(status, detail, headers={"Cache-Control": "no-store"})


class _StoredDrafts:
    def __init__(self, drafts: DraftStore, check: Callable[[], None]) -> None:
        self._drafts, self._check = drafts, check

    def stored(self, user_id: str, instruction_id: str) -> DraftResult | None:
        self._check()
        doc = self._drafts.get(user_id, instruction_id)
        return _result(instruction_id, doc) if doc is not None else None


class _NoThreads:
    def get_thread(self, user_id: str, thread_id: str) -> dict:
        raise _refuse(409, "followup_unavailable")


class _MeetingPreview(Autopilot):
    def __init__(self, *, check: Callable[[], None], **ports: Any) -> None:
        super().__init__(**ports)
        self._check = check

    def preview(self, user_id: str, context: DraftContext, result: DraftResult) -> Preview:
        self._check()
        if user_id != self._world_owner():
            raise _refuse()
        if (
            context.mode != "new"
            or context.thread_id is not None
            or context.instruction_id != result.instruction_id
            or (result.draft is not None and (result.draft.mode != "new" or result.draft.thread_id is not None))
        ):
            raise _refuse(409, "followup_unavailable")
        return super().preview(user_id, context, result)


class _Policies:
    def __init__(self, owner: OwnerMinutesCaller, user: str, check: Callable[[], None]) -> None:
        self._owner, self._user, self._check = owner, user, check
        self._table = tilo_policy.load_risk_table()

    def level(self, user_id: str, action_type: str) -> tuple[str, str | None]:
        return "L1", None

    def decide(self, user_id: str, proposal: tilo_policy.Proposal) -> tilo_policy.Decision:
        self._check()
        if user_id != self._user:
            raise _refuse()
        store = self._owner.store
        store.load_owner(self._user, settle=False)
        policies = [p for p in store.policies.values() if p.get("owner") == self._user]
        worlds = [key for key, value in store.worlds.items() if value.owner == self._user]
        applied = [e for key in worlds for e in store.events.get(key, []) if e.get("type") == "policy.applied"]
        self._check()
        return tilo_policy.decide(
            proposal,
            table=self._table,
            policies=policies,
            world_owner=self._user,
            applied=applied,
            now=self._owner.clock(),
        )


def build_factory(
    owner: OwnerMinutesCaller,
    *,
    client: Any,
    outbox_store: Any,
    drafts: DraftStore,
) -> Callable[[str, str, str, Callable[[dict], None]], Autopilot]:
    """Inputs resolved by deps; no client creation, new store door or memory fallback here."""

    def factory(world_id: str, run_id: str, user_id: str, emit: Callable[[dict], None]) -> Autopilot:
        for value, definition in ((world_id, "world_id"), (run_id, "run_id"), (user_id, "user_id")):
            if not conforms(f"common.schema.json#/$defs/{definition}", value):
                raise _refuse()
        hook = getattr(emit, "before_publication", None)
        scoped_drafts = getattr(emit, "drafts", None)
        if not callable(emit) or not callable(hook) or scoped_drafts is None:
            raise _refuse(503, "not_configured")

        def authority() -> None:
            principal, state = owner.principal, owner.request.state
            world = owner.store.load_world(world_id, settle=False)
            if (
                principal.demo_session
                or getattr(state, "demo_session", False) is True
                or getattr(state, "uid", None) != user_id
                or principal.user_id != user_id
                or principal.world_id not in (None, world_id)
                or world is None
                or world.owner != user_id
                or world.run_id != run_id
            ):
                raise _refuse()
            if world.paused:
                raise _refuse(409, "world_paused")

        def check() -> None:
            authority()
            hook()
            authority()

        authority()

        def halted() -> bool:
            try:
                check()
            except Exception:
                return True
            return False

        def world_owner() -> str:
            authority()
            return user_id

        scope = dict(org_id=deps.ORG_ID, owner=user_id, world_id=world_id, run_id=run_id)
        retained = scoped_drafts if isinstance(scoped_drafts, FirestoreDraftStore) else None
        cards = FirestoreCards(client, **scope, before_publication=check, drafts=retained)
        stops = FirestoreStops(client, **scope, before_publication=check, drafts=retained)
        outbox = Outbox(
            outbox_store,
            {},
            emit=emit,
            clock=owner.clock,
            world_id=world_id,
            halted=halted,
        )
        return _MeetingPreview(
            check=check,
            drafter=cast(Drafter, _StoredDrafts(scoped_drafts, check)),
            reader=_NoThreads(),
            contacts=lambda uid: (),
            policy=_Policies(owner, user_id, check),
            outbox=PublicationOutbox(outbox, check),
            cards=PublicationCards(cards, check),
            stops=PublicationStops(stops, check),
            clock=lambda: datetime.fromisoformat(owner.clock().replace("Z", "+00:00")).timestamp(),
            emit=emit,
            world_id=world_id,
            run_id=run_id,
            world_owner=world_owner,
        )

    return factory
