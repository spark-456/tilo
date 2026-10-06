"""tilo_channels.digest: Daily digest of automated L2/L3 actions and FYI mail (FR-CHN-18; PRD 11.4, 11.6, SEC-03)."""

from __future__ import annotations

import copy
import datetime as dt
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Any, Literal, Protocol

import tilo_policy
from tilo_policy.schemas import conforms

from tilo_channels.autopilot_gate import gate_id_for
from tilo_channels.autopilot_state import ACTION_TYPE, parse_ms, timestamp, ulid

__all__ = [
    "AUTOMATED_LEVELS", "DailyDigest", "DailyDigestBuilder", "DigestAction", "DigestFyiItem",
    "DigestOutboxPort", "DigestPolicyPort", "DigestService", "FakeDigestChannel", "WINDOW_S", "build_daily_digest",
]  # fmt: skip

WINDOW_S = 86_400
AUTOMATED_LEVELS: frozenset[str] = frozenset({"L2", "L3"})
_POLICY_ID_REF = "common.schema.json#/$defs/policy_id"


class DigestOutboxPort(Protocol):
    def enqueue(self, entry: dict, evidence: dict) -> dict: ...


class DigestPolicyPort(Protocol):
    def decide(self, user_id: str, proposal: tilo_policy.Proposal) -> tilo_policy.Decision: ...


def _to_epoch_s(value: float | int | str | dt.datetime | None) -> float | None:
    if isinstance(value, int | float):
        return float(value)
    if isinstance(value, str) and (raw := value.strip()):
        try:
            value = dt.datetime.fromisoformat(raw[:-1] + "+00:00" if raw.endswith("Z") else raw)
        except ValueError:
            return None
    if isinstance(value, dt.datetime):
        return (value.astimezone(dt.UTC) if value.tzinfo is not None else value.replace(tzinfo=dt.UTC)).timestamp()
    return None


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
    action_url: str
    undo_url: str | None
    report_url: str


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
    rendered_text: str
    skipped_outbox_ids: tuple[str, ...] = ()


class DailyDigestBuilder:
    def __init__(self, *, base_url: str = "https://app.tilo.example", window_s: int = WINDOW_S) -> None:
        self._base_url, self._window_s = base_url.rstrip("/"), window_s

    def build(
        self, *, user_id: str, events: Iterable[Mapping[str, Any]], outbox_entries: Iterable[Mapping[str, Any]] = (),
        fyi_mail: Iterable[Mapping[str, Any]] = (), now: float | int | str | dt.datetime | None = None,
    ) -> DailyDigest | None:  # fmt: skip
        now_s = _to_epoch_s(now) if now is not None else dt.datetime.now(dt.UTC).timestamp()
        if now_s is None:
            raise ValueError(f"invalid digest timestamp: {now!r}")
        cutoff_s = now_s - float(self._window_s)
        entries_by_id = {
            str(e["id"]): e for e in outbox_entries if isinstance(e, Mapping) and isinstance(e.get("id"), str)
        }
        actions, seen_ids, skipped_ids = [], set(), []

        for ev in events:
            if not isinstance(ev, Mapping) or ev.get("type") != "policy.applied":
                continue
            data, ts_str = ev.get("data"), ev.get("ts")
            if not isinstance(data, Mapping) or not isinstance(ts_str, str):
                continue
            lvl, outbox_id = data.get("level"), data.get("outbox_id")
            if lvl not in AUTOMATED_LEVELS or not isinstance(outbox_id, str) or not outbox_id or outbox_id in seen_ids:
                continue
            ev_s = _to_epoch_s(ts_str)
            if ev_s is None or not (cutoff_s <= ev_s <= now_s):
                continue
            seen_ids.add(outbox_id)
            entry = entries_by_id.get(outbox_id)
            fields = ("action_type", "connector", "risk_tier", "policy_id")
            req = (*(data.get(k) for k in fields), entry.get("state")) if entry is not None else ()
            if not req or not all(isinstance(v, str) and v for v in req):
                skipped_ids.append(outbox_id)
                continue
            action_type, connector, risk_tier, policy_id, state = (str(v) for v in req)
            assert entry is not None
            sched_s = _to_epoch_s(entry.get("scheduled_at"))
            can_undo = state == "scheduled" and int(data.get("undo_window_s") or 0) > 0 and (sched_s or now_s) > now_s
            undo_url = f"{self._base_url}/outbox/{outbox_id}/undo" if can_undo else None
            report_url = f"{self._base_url}/outbox/{outbox_id}/report"
            actions.append(
                DigestAction(
                    outbox_id,
                    policy_id,
                    "L2" if lvl == "L2" else "L3",
                    action_type,
                    connector,
                    risk_tier,
                    state,
                    ts_str,
                    "undo" if can_undo else "report",
                    undo_url or report_url,
                    undo_url,
                    report_url,
                )  # fmt: skip
            )

        fyi_items = [
            DigestFyiItem(str(m["message_id"]), str(m.get("priority") or "normal"), ts)
            for m in fyi_mail
            if isinstance(m, Mapping)
            and m.get("category") == "fyi"
            and m.get("message_id")
            and (ts := _to_epoch_s(m.get("triaged_at"))) is not None
            and (cutoff_s <= ts <= now_s)
        ]
        if not actions and not fyi_items:
            return None

        start_iso, end_iso = timestamp(round(cutoff_s * 1000)), timestamp(round(now_s * 1000))
        lines = [f"Daily Digest ({start_iso} to {end_iso})"]
        lines.extend(
            f"- [{a.level}] {a.action_type} ({a.outbox_id}) state={a.state} {a.link_kind}={a.action_url}"
            for a in actions
        )
        lines.extend(f"- [FYI] {item.message_id} priority={item.priority}" for item in fyi_items)
        return DailyDigest(
            user_id, start_iso, end_iso, tuple(actions), tuple(fyi_items), "\n".join(lines), tuple(skipped_ids)
        )


def build_daily_digest(**kwargs: Any) -> DailyDigest | None:
    return DailyDigestBuilder(base_url=str(kwargs.pop("base_url", "https://app.tilo.example"))).build(**kwargs)


class FakeDigestChannel:
    def __init__(self) -> None:
        self.sent: list[dict[str, Any]] = []

    def send(self, user_id: str, recipient: str, digest: DailyDigest) -> dict[str, Any]:
        record = {"channel": "fake", "user_id": user_id, "recipient": recipient, "digest": digest}
        self.sent.append(record)
        return record


def _allowed_decision(d: Any) -> tuple[dict[str, str], int] | None:
    if type(d) is not tilo_policy.Decision or d.outcome not in ("run_after_undo", "run"):
        return None
    if d.level not in AUTOMATED_LEVELS or d.tier not in ("T1", "T2") or d.modifiers:
        return None
    authz = d.authz
    if not isinstance(authz, dict) or authz.get("by") != "policy" or not isinstance(d.policy_id, str):
        return None
    ref, stamp = authz.get("ref"), authz.get("at")
    if ref != d.policy_id or not isinstance(ref, str) or not conforms(_POLICY_ID_REF, ref) or parse_ms(stamp) is None:
        return None
    undo = 0 if d.outcome == "run" else d.undo_window_s
    return ({"by": "policy", "ref": ref, "at": str(stamp)}, undo) if isinstance(undo, int) and undo >= 0 else None


class DigestService:
    def __init__(
        self, *, builder: DailyDigestBuilder, outbox: DigestOutboxPort, policy: DigestPolicyPort | None = None,
        dev_channel: FakeDigestChannel | None = None, world_id: str, run_id: str, connector: str = "gmail",
        district: str = "D1", dev_mode: bool = False,
    ) -> None:  # fmt: skip
        if dev_mode and dev_channel is None:
            raise ValueError("dev_mode=True requires a dev_channel")
        self._builder, self._outbox, self._policy, self._dev_channel = builder, outbox, policy, dev_channel
        self._world_id, self._run_id, self._connector, self._district = world_id, run_id, connector, district
        self._dev_mode = dev_mode

    def deliver_if_non_empty(
        self, *, user_id: str, recipient: str, events: Iterable[Mapping[str, Any]],
        outbox_entries: Iterable[Mapping[str, Any]] = (), fyi_mail: Iterable[Mapping[str, Any]] = (),
        now: float | int | str | dt.datetime | None = None,
    ) -> dict[str, Any] | None:  # fmt: skip
        digest = self._builder.build(
            user_id=user_id, events=events, outbox_entries=outbox_entries, fyi_mail=fyi_mail, now=now
        )
        if digest is None:
            return None
        if self._dev_mode:
            assert self._dev_channel is not None
            return self._dev_channel.send(user_id, recipient, digest)
        if self._policy is None:
            return None
        now_ms = parse_ms(digest.window_end) or round(dt.datetime.now(dt.UTC).timestamp() * 1000)
        outbox_id = ulid(now_ms)
        item = {"artifact_id": f"art_digest_{outbox_id[:16].lower()}", "version": 1}
        facts = tilo_policy.SideEffectFacts(recipients=(recipient,), known_recipients=(recipient,))
        proposal = tilo_policy.Proposal(
            world_id=self._world_id, action_type=ACTION_TYPE, connector=self._connector, district=self._district,
            destination=None, item=copy.deepcopy(item), credits=0, facts=facts, instruction=None,
        )  # fmt: skip
        try:
            decision = self._policy.decide(user_id, proposal)
        except Exception:
            return None
        if (checked := _allowed_decision(decision)) is None:
            return None
        authz, undo = checked
        policy_applied = {
            "type": "policy.applied", "authz": copy.deepcopy(authz),
            "data": {
                "policy_id": decision.policy_id, "gate_id": gate_id_for(f"digest_{outbox_id}"), "outbox_id": outbox_id,
                "action_type": ACTION_TYPE, "connector": self._connector, "destination": None,
                "district": self._district, "risk_tier": decision.tier, "level": decision.level,
                "instruction_id": None, "undo_window_s": undo, "item": copy.deepcopy(item), "credits": 0,
            },
        }  # fmt: skip
        entry = {
            "id": outbox_id, "idempotency_key": f"digest:{user_id}:{digest.window_end}",
            "world_id": self._world_id, "run_id": self._run_id, "action_type": ACTION_TYPE,
            "connector": self._connector, "recipients": [recipient], "attachments": [], "item": item,
            "destination": None, "modifiers": [], "risk_tier": decision.tier, "authz": authz,
            "undo_window_s": undo, "scheduled_at": timestamp(now_ms + undo * 1000),
            "state": "scheduled" if undo > 0 else "queued", "created_at": authz["at"],
        }  # fmt: skip
        return self._outbox.enqueue(entry, {"authorised_by": policy_applied})
