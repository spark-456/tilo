"""The push feed (FR-CHN-17f; PRD 11, 16; BQ-CHN17f-1): from the same derived queue the bell reads
(`GET /v1/notifications`: the owner's open gate cards across worlds), each person who turned push on gets one
notice per new gate card, through the owner's standing L3 policy and the outbox, sent by tilo-channels
(`push_send`).

Run by the Scheduler's tick, best effort (`schedules._sweep_push`); nothing here is a request of a person. Only people
with a stored device AND the owner's own L3 `send_push` policy are visited (`push_policy.current`); a card must be
a gate, at most `FEED_MAX_AGE_S` old (turning push on never replays the backlog), and has the id of its card in the
idempotency key, so a second pass, a second instance or a restart finds the stored entry and queues nothing. The
notice text is fixed by code from the card's kind and holds no card, mail or model content, so the injection flag
that decides whether content may act cannot reach a lock screen; the card is passed as known clean on that ground
(BQ-CHN17f-1). No durable notification settings exist yet (ADR-0037 is Proposed), so no quiet hours are read here: a
gate is always notified, which is also what quiet hours would do. The owner's address for the entry comes from the
people directory. A failure of one person never stops the next, and no log holds more than the exception type.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from datetime import datetime
from typing import Any

import tilo_policy
from tilo_channels.digest import DigestArtifacts
from tilo_channels.web_push import CONNECTOR, PushNotifier, PushResult, load_config
from tilo_connectors import Outbox, RetryPolicy

from tilo_api import deps, desk, events, push_policy
from tilo_api.cards_feed import _scope, _world_cards

logger = logging.getLogger("tilo_api.push_feed")
FEED_MAX_AGE_S = 900  # a gate older than this is not "new": nobody is buzzed for yesterday's queue
TITLE = "A send is waiting for your approval"


class _EnginePort:
    """The real engine behind the notifier's port: this owner's one policy and the pushes already applied today."""

    def __init__(self, policy: dict[str, Any], applied: list[dict[str, Any]], now: Callable[[], str]) -> None:
        self._policy, self._applied, self._now = policy, applied, now

    def decide(self, user_id: str, proposal: tilo_policy.Proposal) -> tilo_policy.Decision:
        return tilo_policy.decide(
            proposal,
            table=tilo_policy.load_risk_table(),
            policies=[self._policy],
            world_owner=user_id,
            applied=self._applied,
            now=self._now(),
        )

    def policy_for(self, user_id: str, policy_id: str) -> dict[str, Any] | None:
        p = self._policy
        return p if p["id"] == policy_id and p["owner"] == user_id else None


def _stamp(at: datetime) -> str:
    return at.strftime("%Y-%m-%dT%H:%M:%S.") + f"{at.microsecond // 1000:03d}Z"


def _age_s(created_at: str, now: datetime) -> float:
    return (now - datetime.fromisoformat(created_at)).total_seconds()


def _email(people: Any, user: str) -> str | None:
    found = people.persons.get(deps.ORG_ID, user)
    email = None if found is None else found.record.get("email")
    return email if isinstance(email, str) else None


def sweep(
    *,
    subs: Any,
    store: Any,
    outbox_store: Any,
    adapter: Any,
    people: Any,
    writer: Any,
    clock: Callable[[], datetime],
    preferences: Any = None,
    paused: Callable[[str], bool] = lambda world_id: False,
) -> int:
    """Visits every person with a device; returns how many notices were queued."""
    queued = 0
    for user in list(subs.users()):
        try:
            queued += _one(user, subs, store, outbox_store, adapter, people, writer, clock, preferences, paused)
        except Exception as exc:  # noqa: BLE001 - one person's failure never stops the next
            logger.error("push feed failed for one person (%s)", type(exc).__name__)
    return queued


def _one(user, subs, store, outbox_store, adapter, people, writer, clock, preferences, paused) -> int:  # type: ignore[no-untyped-def]
    policy = push_policy.current(store, user)
    email = _email(people, user)
    if policy is None or email is None:
        return 0
    now = clock()
    desk_ref = desk.ensure_desk(store, org_id=deps.ORG_ID, user=user)
    principal = deps.Principal(user_id=user, role="owner", channel="web", full_session=True)
    cards = [
        card
        for world_id in _scope(principal, store)
        for _, card in _world_cards(principal, store, world_id)
        if card.get("kind") == "gate" and 0 <= _age_s(card["created_at"], now) <= FEED_MAX_AGE_S
    ]
    if not cards:
        return 0
    applied = [e for e in store.events.get(desk_ref.world_id, []) if e.get("type") == "policy.applied"]

    def record(part: dict[str, Any], *, actor: str, target: str, summary: str, key: str) -> dict[str, Any]:
        event = {
            "id": events.stable_part_id(part["type"], key),
            "actor": actor,
            "target": target,
            "summary": summary,
            "vis": "all",
            **part,
        }  # fmt: skip
        writer.append(desk_ref.world_id, event)
        return event

    def emit_applied(part: dict[str, Any]) -> None:
        d = part["data"]
        event = record(part, actor=d["policy_id"], target=d["gate_id"], key=d["outbox_id"],
                       summary="The owner's push policy opened a notice.")  # fmt: skip
        applied.append(event)  # the engine counts per_day from this list: a second notice in this pass sees the first

    def emit_transfer(part: dict[str, Any]) -> None:
        record(part, actor="system", target=desk_ref.world_id, key=part["data"]["outbox_id"],
               summary="A push notice went to the owner's device.")  # fmt: skip

    outbox = Outbox(
        outbox_store,
        {CONNECTOR: adapter},
        emit_transfer,
        lambda: _stamp(clock()),
        world_id=desk_ref.world_id,
        retry=RetryPolicy(),
        halted=lambda: paused(desk_ref.world_id),
    )
    notifier = PushNotifier(
        subscriptions=subs, outbox=outbox, policy=_EnginePort(policy, applied, lambda: _stamp(clock())),
        artifacts=DigestArtifacts(), emit=emit_applied, mailbox=lambda _u: email, world_id=desk_ref.world_id,
        world_owner=user, run_id=desk_ref.run_id, preferences=preferences, clock=clock, config=load_config(),
    )  # fmt: skip
    results: list[PushResult] = [
        notifier.notify(user, {"id": f"gate-{c['id']}", "kind": "gate", "title": TITLE, "body": "", "flagged": False})
        for c in cards
    ]
    outbox.dispatch_due()  # now, not a tick later: the 10 s bound starts at enqueue
    return sum(r.status == "queued" for r in results)
