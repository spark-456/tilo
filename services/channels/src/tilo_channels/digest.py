"""tilo_channels.digest: Daily digest of automated L2/L3 actions and FYI mail (FR-CHN-18; PRD 11.4, 11.6, SEC-03)."""

from __future__ import annotations

import datetime as dt
import re
from collections.abc import Callable, Collection, Iterable, Mapping
from dataclasses import dataclass, field
from typing import Any, Literal, TypeGuard

from tilo_policy.schemas import conforms

from tilo_channels.autopilot_state import timestamp
from tilo_channels.links import CardState, KeyRing, LinkService, NonceStore, Redemption
from tilo_channels.triage import PRIORITIES

__all__ = ["AUTOMATED_LEVELS", "DailyDigest", "DailyDigestBuilder", "DigestAction", "DigestFyiItem", "WINDOW_S"]

WINDOW_S = 86_400
AUTOMATED_LEVELS: frozenset[str] = frozenset({"L2", "L3"})
_MSG_ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}\Z")


def _to_epoch_s(value: float | int | str | dt.datetime | None) -> float | None:
    if isinstance(value, int | float) and not isinstance(value, bool):
        return float(value)
    if type(value) is str and (raw := value.strip()):
        try:
            value = dt.datetime.fromisoformat(raw[:-1] + "+00:00" if raw.endswith("Z") else raw)
        except ValueError:
            return None
    if isinstance(value, dt.datetime):
        return (value.astimezone(dt.UTC) if value.tzinfo is not None else value.replace(tzinfo=dt.UTC)).timestamp()
    return None


def _valid_str(schema_ref: str, value: Any) -> TypeGuard[str]:
    return type(value) is str and conforms(schema_ref, value)


def _digest_card(opts: Iterable[str]) -> CardState:
    base = {"kind": "needs_you", "rung": "needs_you", "gate": None, "consent": None, "answer_channels": ["email"]}
    return CardState(card=base | {"options": [{"id": o} for o in opts]}, answered=False)


def _redeem_card(card_id: str) -> CardState | None:
    return _digest_card(("undo", "report")) if _valid_str("common.schema.json#/$defs/ulid", card_id) else None


def _valid_action_fields(data: Mapping[str, Any], entry: Mapping[str, Any] | None, world_id: Any) -> bool:
    undo_w = data.get("undo_window_s")
    return (
        entry is not None
        and entry.get("world_id") == world_id
        and _valid_str("common.schema.json#/$defs/action_type", data.get("action_type"))
        and _valid_str("common.schema.json#/$defs/connector_id", data.get("connector"))
        and _valid_str("common.schema.json#/$defs/risk_tier", data.get("risk_tier"))
        and _valid_str("common.schema.json#/$defs/policy_id", data.get("policy_id"))
        and _valid_str("outbox.schema.json#/properties/state", entry.get("state"))
        and type(undo_w) is int
        and 0 <= undo_w <= 3600
    )


@dataclass(frozen=True)
class DigestAction:
    outbox_id: str
    policy_id: str
    level: Literal["L2", "L3"]
    action_type: str
    connector: str
    risk_tier: str
    state: str
    timestamp: str
    link_kind: Literal["undo", "report"]
    action_url: str = field(repr=False)
    undo_url: str | None = field(repr=False)
    report_url: str = field(repr=False)


@dataclass(frozen=True)
class DigestFyiItem:
    message_id: str
    priority: str
    triaged_at: float


@dataclass(frozen=True)
class DailyDigest:
    user_id: str
    window_start: str
    window_end: str
    actions: tuple[DigestAction, ...]
    fyi_mail: tuple[DigestFyiItem, ...]
    rendered_text: str = field(repr=False)
    skipped_outbox_ids: tuple[str, ...] = ()
    skipped_fyi_ids: tuple[str, ...] = ()


class DailyDigestBuilder:
    def __init__(
        self,
        *,
        base_url: str,
        keys: KeyRing,
        nonces: NonceStore,
        clock: Callable[[], dt.datetime] | None = None,
        window_s: int = WINDOW_S,
    ) -> None:
        if not isinstance(base_url, str) or not base_url.strip():
            raise ValueError("base_url is required")
        self._base_url, self._window_s = base_url.rstrip("/"), window_s
        self._keys, self._nonces = keys, nonces
        self._clock = clock or (lambda: dt.datetime.now(dt.UTC))

    def now(self) -> dt.datetime:
        return self._clock()

    def _resolve_now(self, now: float | int | str | dt.datetime | None) -> tuple[float, dt.datetime]:
        if now is None:
            now_dt = self._clock()
            return now_dt.timestamp(), now_dt
        if (now_s := _to_epoch_s(now)) is None:
            raise ValueError(f"invalid timestamp: {now!r}")
        return now_s, dt.datetime.fromtimestamp(now_s, tz=dt.UTC)

    def redeem(
        self,
        token: str,
        *,
        outbox_id: str,
        option: Literal["undo", "report"],
        viewer: str | None = None,
        now: float | int | str | dt.datetime | None = None,
    ) -> Redemption:
        _, clock_dt = self._resolve_now(now)
        svc = LinkService(
            keys=self._keys, nonces=self._nonces, clock=lambda: clock_dt, cards=_redeem_card, base_url=self._base_url
        )
        return svc.redeem(token, card_id=outbox_id, action="answer", viewer=viewer, option=option)

    def build(
        self,
        *,
        user_id: str,
        world_ids: Collection[str],
        events: Iterable[Mapping[str, Any]],
        outbox_entries: Iterable[Mapping[str, Any]] = (),
        fyi_mail: Iterable[Mapping[str, Any]] = (),
        now: float | int | str | dt.datetime | None = None,
    ) -> DailyDigest | None:
        if not _valid_str("common.schema.json#/$defs/user_id", user_id):
            raise ValueError("invalid user_id")
        now_s, now_dt = self._resolve_now(now)
        cutoff_s = now_s - float(self._window_s)
        user_worlds = {w for w in world_ids if _valid_str("common.schema.json#/$defs/world_id", w)}
        entries_by_id = {
            e["id"]: e
            for e in outbox_entries
            if isinstance(e, Mapping)
            and _valid_str("common.schema.json#/$defs/ulid", e.get("id"))
            and e.get("world_id") in user_worlds
        }
        cards: dict[str, CardState] = {}
        link_svc = LinkService(
            keys=self._keys, nonces=self._nonces, clock=lambda: now_dt, cards=cards.get, base_url=self._base_url
        )
        actions, seen_ids, skipped_ids = list[DigestAction](), set[str](), list[str]()

        for ev in events:
            if not (
                isinstance(ev, Mapping) and ev.get("type") == "policy.applied" and ev.get("world_id") in user_worlds
            ):
                continue
            data, ts_str = ev.get("data"), ev.get("ts")
            if not (
                isinstance(data, Mapping)
                and isinstance(ts_str, str)
                and _valid_str("common.schema.json#/$defs/timestamp", ts_str)
            ):
                continue
            lvl, outbox_id = data.get("level"), data.get("outbox_id")
            if lvl not in AUTOMATED_LEVELS or not (
                isinstance(outbox_id, str) and _valid_str("common.schema.json#/$defs/ulid", outbox_id)
            ):
                continue
            if outbox_id in seen_ids or (ev_s := _to_epoch_s(ts_str)) is None or not (cutoff_s <= ev_s <= now_s):
                continue
            seen_ids.add(outbox_id)
            entry = entries_by_id.get(outbox_id)
            if not _valid_action_fields(data, entry, ev.get("world_id")) or entry is None:
                skipped_ids.append(outbox_id)
                continue
            sched_s = _to_epoch_s(entry.get("scheduled_at")) or now_s
            can_undo = entry["state"] == "scheduled" and data["undo_window_s"] > 0 and sched_s > now_s
            cards[outbox_id] = _digest_card(("report", "undo") if can_undo else ("report",))
            report_url = link_svc.issue(card_id=outbox_id, user_id=user_id, action="answer", option="report").url
            undo_url = (
                link_svc.issue(card_id=outbox_id, user_id=user_id, action="answer", option="undo").url
                if can_undo
                else None
            )
            actions.append(
                DigestAction(
                    outbox_id,
                    data["policy_id"],
                    "L2" if lvl == "L2" else "L3",
                    data["action_type"],
                    data["connector"],
                    data["risk_tier"],
                    entry["state"],
                    ts_str,
                    "undo" if can_undo else "report",
                    undo_url or report_url,
                    undo_url,
                    report_url,
                )
            )

        fyi_items, skipped_fyi = list[DigestFyiItem](), list[str]()
        for m in fyi_mail:
            if not (isinstance(m, Mapping) and m.get("user_id") == user_id and m.get("category") == "fyi"):
                continue
            if (ts := _to_epoch_s(m.get("triaged_at"))) is None or not (cutoff_s <= ts <= now_s):
                continue
            mid, prio = m.get("message_id"), m.get("priority", "normal")
            if type(mid) is not str or not _MSG_ID_RE.match(mid) or type(prio) is not str or prio not in PRIORITIES:
                skipped_fyi.append(str(mid or ""))
                continue
            fyi_items.append(DigestFyiItem(mid, prio, ts))

        if not actions and not fyi_items and not skipped_ids:
            return None
        start_iso, end_iso = timestamp(round(cutoff_s * 1000)), timestamp(round(now_s * 1000))
        lines = [f"Daily Digest ({start_iso} to {end_iso})"]
        lines.extend(
            f"- [{a.level}] {a.action_type} ({a.outbox_id}) state={a.state} {a.link_kind}={a.action_url}"
            for a in actions
        )
        if skipped_ids:
            lines.append(f"- {len(skipped_ids)} actions not listed")
        lines.extend(f"- [FYI] {item.message_id} priority={item.priority}" for item in fyi_items)
        return DailyDigest(
            user_id,
            start_iso,
            end_iso,
            tuple(actions),
            tuple(fyi_items),
            "\n".join(lines),
            tuple(skipped_ids),
            tuple(skipped_fyi),
        )
