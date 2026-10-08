"""tilo_channels.digest: Daily digest of automated L2/L3 actions and FYI mail (FR-CHN-18; PRD 11.4, 11.6, SEC-03)."""

from __future__ import annotations

import copy
import datetime as dt
import logging
import re
import sys
from collections.abc import Callable, Collection, Iterable, Mapping
from dataclasses import dataclass, field
from typing import Any, Literal, Protocol, TypeGuard
from zoneinfo import ZoneInfoNotFoundError

import tilo_policy
from tilo_policy.schemas import conforms, event_ok

from tilo_channels.autopilot_gate import gate_id_for
from tilo_channels.autopilot_state import (
    ACTION_TYPE,
    DigestSettleFailed,
    Outbox,
    enqueue_digest,
    fresh,
    parse_ms,
    timestamp,
    ulid,
)
from tilo_channels.links import CardState, KeyRing, LinkService, NonceStore, Redemption
from tilo_channels.quiet_hours import PreferenceReader, QuietHours, should_notify
from tilo_channels.triage import PRIORITIES

__all__ = [
    "AUTOMATED_LEVELS",
    "DailyDigest",
    "DailyDigestBuilder",
    "DigestAction",
    "DigestArtifactPort",
    "DigestArtifacts",
    "DigestFyiItem",
    "DigestPolicyPort",
    "DigestService",
    "WINDOW_S",
]

WINDOW_S = 86_400
AUTOMATED_LEVELS: frozenset[str] = frozenset({"L2", "L3"})
_MSG_ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}\Z")
_LOG = logging.getLogger("tilo_channels.digest")
_MAX_DIGEST_RETRIES = 16


def _is_expected_port_error(exc: Exception) -> bool:
    if isinstance(exc, DigestSettleFailed):
        return False
    mod = sys.modules.get("tilo_connectors.errors")
    conn_errs = tuple(
        cls for name in ("OutboxRefused", "AdapterError") if isinstance(cls := getattr(mod, name, None), type)
    )
    return isinstance(exc, (ZoneInfoNotFoundError, ValueError, PermissionError, RuntimeError, OSError, *conn_errs))


def _resolve_digest_key(outbox: Outbox, world_id: str, base_key: str) -> str | None:
    for attempt in range(_MAX_DIGEST_RETRIES):
        key = base_key if attempt == 0 else f"{base_key}:retry:{attempt}"
        existing = outbox.get_by_idempotency_key(world_id, key)
        if existing is None:
            return key
        if existing.get("state") != "failed":
            return None
        next_key = f"{base_key}:retry:{attempt + 1}"
        _LOG.warning("digest key %s held failed entry %s; retrying as %s", key, existing.get("id"), next_key)
    return None


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


class DigestArtifactPort(Protocol):
    def store(self, artifact_id: str, subject: str, body_text: str, version: int = 1) -> dict[str, Any]: ...
    def get(self, artifact_id: str, version: int) -> Mapping[str, Any]: ...


class DigestArtifacts:
    def __init__(self) -> None:
        self._by_ref: dict[tuple[str, int], dict[str, Any]] = {}

    def store(self, artifact_id: str, subject: str, body_text: str, version: int = 1) -> dict[str, Any]:
        doc = {"kind": "email", "subject": subject, "body_text": body_text, "in_reply_to": "", "references": ""}
        if self._by_ref.setdefault((artifact_id, version), doc) != doc:
            raise ValueError("digest artifact version is immutable")
        return {"artifact_id": artifact_id, "version": version}

    def get(self, artifact_id: str, version: int) -> Mapping[str, Any]:
        return copy.deepcopy(self._by_ref[(artifact_id, version)])


class DigestPolicyPort(Protocol):
    def decide(self, user_id: str, proposal: tilo_policy.Proposal) -> tilo_policy.Decision: ...
    def policy_for(self, user_id: str, policy_id: str) -> Mapping[str, Any] | None: ...


def _user_prefs(
    source: PreferenceReader | Mapping[str, Any] | QuietHours | None, user_id: str
) -> Mapping[str, Any] | QuietHours | None:
    if source is None or isinstance(source, QuietHours):
        return source
    if isinstance(source, Mapping) and ("quiet_hours" in source or "start" in source):
        return source
    res = source.get(user_id)
    return res if isinstance(res, Mapping | QuietHours) else None


def _allowed_l3_decision(d: Any, now_ms: int, default_undo_s: int) -> tuple[dict[str, str], int, int] | None:
    if type(d) is not tilo_policy.Decision or d.outcome != "run" or d.level != "L3" or d.tier not in ("T1", "T2"):
        return None
    authz = d.authz
    if type(d.modifiers) is not tuple or d.modifiers or type(authz) is not dict or len(authz) != 3:
        return None
    by, ref, stamp = authz.get("by"), authz.get("ref"), authz.get("at")
    if (
        by != "policy"
        or not isinstance(ref, str)
        or not _valid_str("common.schema.json#/$defs/policy_id", ref)
        or ref != d.policy_id
        or (at_ms := parse_ms(stamp)) is None
        or not fresh(stamp, now_ms)
    ):
        return None
    undo = d.undo_window_s if type(d.undo_window_s) is int else default_undo_s
    return ({"by": "policy", "ref": ref, "at": str(stamp)}, at_ms, undo) if 0 <= undo <= 3600 else None


class DigestService:
    def __init__(
        self,
        *,
        builder: DailyDigestBuilder,
        outbox: Outbox,
        policy: DigestPolicyPort | None = None,
        artifacts: DigestArtifactPort,
        emit: Callable[[dict[str, Any]], None],
        mailbox: Callable[[str], str | None],
        world_id: str,
        world_owner: str,
        run_id: str,
        preferences: PreferenceReader | Mapping[str, Any] | QuietHours | None = None,
        connector: str = "gmail",
        district: str = "D1",
    ) -> None:
        self._builder, self._outbox, self._policy, self._artifacts = builder, outbox, policy, artifacts
        self._emit, self._mailbox, self._preferences = emit, mailbox, preferences
        self._world_id, self._world_owner, self._run_id = world_id, world_owner, run_id
        self._connector, self._district = connector, district

    def deliver_if_non_empty(
        self,
        *,
        user_id: str,
        events: Iterable[Mapping[str, Any]],
        outbox_entries: Iterable[Mapping[str, Any]] = (),
        fyi_mail: Iterable[Mapping[str, Any]] = (),
        world_ids: Collection[str] | None = None,
        recipient: str | None = None,
        now: float | int | str | dt.datetime | None = None,
    ) -> dict[str, Any] | None:
        if (
            self._policy is None
            or user_id != self._world_owner
            or not _valid_str("common.schema.json#/$defs/user_id", user_id)
        ):
            return None
        owner_addr = self._mailbox(user_id)
        if not isinstance(owner_addr, str) or not _valid_str("common.schema.json#/$defs/email_address", owner_addr):
            return None
        if recipient is not None and recipient != owner_addr:
            return None
        check_now = self._builder.now() if now is None else now
        try:
            if not should_notify("digest", prefs=_user_prefs(self._preferences, user_id), now=check_now):
                return None
        except Exception as exc:
            if _is_expected_port_error(exc) or isinstance(exc, TypeError):
                _LOG.warning("digest held: quiet hours check failed (%s)", type(exc).__name__)
                return None
            _LOG.error("digest unexpected failure in quiet hours (%s)", type(exc).__name__)
            raise
        scoped_worlds = {self._world_id} if world_ids is None else (set(world_ids) & {self._world_id})
        digest = self._builder.build(
            user_id=user_id,
            world_ids=scoped_worlds,
            events=events,
            outbox_entries=outbox_entries,
            fyi_mail=fyi_mail,
            now=check_now,
        )
        if digest is None:
            return None
        utc_day, base_key = digest.window_end[:10], f"digest:{user_id}:{digest.window_end[:10]}"
        if (idem_key := _resolve_digest_key(self._outbox, self._world_id, base_key)) is None:
            return None
        if (now_ms := parse_ms(digest.window_end)) is None:
            return None
        outbox_id = ulid(now_ms)
        item = self._artifacts.store(
            f"art_digest_{outbox_id[:16].lower()}", f"Daily Digest ({utc_day})", digest.rendered_text
        )
        if not conforms("common.schema.json#/$defs/artifact_ref", item):
            return None
        facts = tilo_policy.SideEffectFacts(recipients=(owner_addr,), known_recipients=(owner_addr,))
        proposal = tilo_policy.Proposal(
            self._world_id, ACTION_TYPE, self._connector, self._district, None, facts, copy.deepcopy(item), 0, None
        )
        try:
            decision = self._policy.decide(user_id, proposal)
            pol_doc = self._policy.policy_for(user_id, decision.policy_id) if type(decision.policy_id) is str else None
        except Exception as exc:
            if _is_expected_port_error(exc):
                _LOG.warning("digest policy check failed (%s)", type(exc).__name__)
                return None
            _LOG.error("digest unexpected failure in policy check (%s)", type(exc).__name__)
            raise
        if not isinstance(pol_doc, Mapping):
            return None
        pol_undo = pol_doc.get("undo_window_s")
        if (checked := _allowed_l3_decision(decision, now_ms, pol_undo if type(pol_undo) is int else 60)) is None:
            return None
        authz, at_ms, undo = checked
        pdata: dict[str, Any] = {"policy_id": decision.policy_id, "gate_id": gate_id_for(f"digest_{outbox_id}")}
        pdata |= {"outbox_id": outbox_id, "action_type": ACTION_TYPE, "connector": self._connector, "destination": None}
        pdata |= {"district": self._district, "risk_tier": decision.tier, "level": "L3", "instruction_id": None}
        pdata |= {"undo_window_s": undo, "item": copy.deepcopy(item), "credits": 0}
        policy_applied = {"type": "policy.applied", "authz": copy.deepcopy(authz), "data": pdata}
        entry: dict[str, Any] = {"id": outbox_id, "idempotency_key": idem_key, "world_id": self._world_id}
        entry |= {"run_id": self._run_id, "action_type": ACTION_TYPE, "connector": self._connector}
        entry |= {"recipients": [owner_addr], "attachments": [], "item": copy.deepcopy(item), "destination": None}
        entry |= {"modifiers": [], "risk_tier": decision.tier, "authz": authz, "undo_window_s": undo}
        entry |= {
            "scheduled_at": timestamp(at_ms + undo * 1000),
            "state": "scheduled" if undo > 0 else "queued",
            "created_at": authz["at"],
        }
        if not event_ok(policy_applied, ("policy.applied",)) or not conforms("outbox.schema.json", entry):
            return None
        try:
            return enqueue_digest(
                self._outbox,
                entry,
                policy_applied=policy_applied,
                policy=pol_doc,
                world_owner=self._world_owner,
                emit=self._emit,
            )
        except Exception as exc:
            if _is_expected_port_error(exc):
                _LOG.warning("digest enqueue failed (%s)", type(exc).__name__)
                return None
            _LOG.error("digest unexpected failure in enqueue (%s)", type(exc).__name__)
            raise
