"""tilo_channels.digest: Daily digest of automated L2/L3 actions and FYI mail (FR-CHN-18; PRD 11.4, 11.6, SEC-03)."""

from __future__ import annotations

import copy
import datetime as dt
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Any, Literal, Protocol

__all__ = [
    "AUTOMATED_LEVELS",
    "DailyDigest",
    "DailyDigestBuilder",
    "DigestAction",
    "DigestFyiItem",
    "DigestOutboxPort",
    "DigestService",
    "FakeDigestChannel",
    "WINDOW_S",
    "build_daily_digest",
]

WINDOW_S = 86_400
AUTOMATED_LEVELS: frozenset[str] = frozenset({"L2", "L3"})


class DigestOutboxPort(Protocol):
    def enqueue(self, entry: dict, evidence: dict) -> dict: ...


def _to_epoch_s(value: float | int | str | dt.datetime | None) -> float | None:
    if isinstance(value, int | float):
        return float(value)
    if isinstance(value, dt.datetime):
        return (value.astimezone(dt.UTC) if value.tzinfo is not None else value.replace(tzinfo=dt.UTC)).timestamp()
    if isinstance(value, str) and (raw := value.strip()):
        try:
            parsed = dt.datetime.fromisoformat(raw[:-1] + "+00:00" if raw.endswith("Z") else raw)
        except ValueError:
            return None
        return (parsed.astimezone(dt.UTC) if parsed.tzinfo is not None else parsed.replace(tzinfo=dt.UTC)).timestamp()
    return None


def _fmt_utc(epoch_s: float) -> str:
    ms = round(epoch_s * 1000)
    return dt.datetime.fromtimestamp(ms // 1000, dt.UTC).strftime("%Y-%m-%dT%H:%M:%S") + f".{ms % 1000:03d}Z"


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


class DailyDigestBuilder:
    def __init__(self, *, base_url: str = "https://app.tilo.example", window_s: int = WINDOW_S) -> None:
        self._base_url, self._window_s = base_url.rstrip("/"), window_s

    def build(
        self,
        *,
        user_id: str,
        events: Iterable[Mapping[str, Any]],
        outbox_entries: Iterable[Mapping[str, Any]] = (),
        fyi_mail: Iterable[Mapping[str, Any]] = (),
        now: float | int | str | dt.datetime | None = None,
    ) -> DailyDigest | None:
        now_s = _to_epoch_s(now) if now is not None else dt.datetime.now(dt.UTC).timestamp()
        if now_s is None:
            raise ValueError(f"invalid digest timestamp: {now!r}")
        cutoff_s = now_s - float(self._window_s)
        entries_by_id = {
            str(e["id"]): e for e in outbox_entries if isinstance(e, Mapping) and isinstance(e.get("id"), str)
        }
        actions: list[DigestAction] = []
        seen_outbox_ids: set[str] = set()

        for ev in events:
            if not isinstance(ev, Mapping) or ev.get("type") != "policy.applied":
                continue
            data = ev.get("data")
            if not isinstance(data, Mapping):
                continue
            lvl, outbox_id = str(data.get("level") or ev.get("level") or ""), str(data.get("outbox_id") or "")
            if lvl not in AUTOMATED_LEVELS or not outbox_id or outbox_id in seen_outbox_ids:
                continue
            ts_str = str(ev.get("ts") or (ev.get("authz") or {}).get("at") or "")
            ev_s = _to_epoch_s(ts_str)
            if ev_s is None or not (cutoff_s <= ev_s <= now_s):
                continue
            entry = entries_by_id.get(outbox_id, {})
            state = str(entry.get("state") or ("scheduled" if lvl == "L2" else "sent"))
            sched_s = _to_epoch_s(entry.get("scheduled_at"))
            undo_window = int(data.get("undo_window_s") or entry.get("undo_window_s") or 0)
            can_undo = state == "scheduled" and undo_window > 0 and (sched_s is None or sched_s > now_s)
            undo_url = f"{self._base_url}/outbox/{outbox_id}/undo" if can_undo else None
            report_url = f"{self._base_url}/outbox/{outbox_id}/report"
            link_kind: Literal["undo", "report"] = "undo" if can_undo else "report"
            level_lit: Literal["L2", "L3"] = "L2" if lvl == "L2" else "L3"
            actions.append(
                DigestAction(
                    outbox_id=outbox_id,
                    policy_id=str(data.get("policy_id") or ""),
                    level=level_lit,
                    action_type=str(data.get("action_type") or entry.get("action_type") or "send_email"),
                    connector=str(data.get("connector") or entry.get("connector") or "gmail"),
                    risk_tier=str(data.get("risk_tier") or entry.get("risk_tier") or "T2"),
                    state=state,
                    timestamp=ts_str,
                    link_kind=link_kind,
                    action_url=undo_url or report_url,
                    undo_url=undo_url,
                    report_url=report_url,
                )
            )
            seen_outbox_ids.add(outbox_id)

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

        lines = [f"Daily Digest ({_fmt_utc(cutoff_s)} to {_fmt_utc(now_s)})"]
        lines.extend(
            f"- [{a.level}] {a.action_type} ({a.outbox_id}) state={a.state} {a.link_kind}={a.action_url}"
            for a in actions
        )
        lines.extend(f"- [FYI] {item.message_id} priority={item.priority}" for item in fyi_items)
        return DailyDigest(
            user_id, _fmt_utc(cutoff_s), _fmt_utc(now_s), tuple(actions), tuple(fyi_items), "\n".join(lines)
        )


def build_daily_digest(**kwargs: Any) -> DailyDigest | None:
    base_url = str(kwargs.pop("base_url", "https://app.tilo.example"))
    return DailyDigestBuilder(base_url=base_url).build(**kwargs)


class FakeDigestChannel:
    def __init__(self) -> None:
        self.sent: list[dict[str, Any]] = []

    def send(self, user_id: str, recipient: str, digest: DailyDigest) -> dict[str, Any]:
        record = {"channel": "fake", "user_id": user_id, "recipient": recipient, "digest": digest}
        self.sent.append(record)
        return record


class DigestService:
    def __init__(
        self,
        *,
        builder: DailyDigestBuilder,
        outbox: DigestOutboxPort,
        dev_channel: FakeDigestChannel | None = None,
        world_id: str,
        run_id: str,
        connector: str = "gmail",
        dev_mode: bool = False,
    ) -> None:
        self._builder, self._outbox, self._dev_channel = builder, outbox, dev_channel
        self._world_id, self._run_id, self._connector, self._dev_mode = world_id, run_id, connector, dev_mode

    def deliver_if_non_empty(
        self,
        *,
        user_id: str,
        recipient: str,
        events: Iterable[Mapping[str, Any]],
        outbox_entries: Iterable[Mapping[str, Any]] = (),
        fyi_mail: Iterable[Mapping[str, Any]] = (),
        now: float | int | str | dt.datetime | None = None,
        policy_applied: Mapping[str, Any] | None = None,
    ) -> dict[str, Any] | None:
        digest = self._builder.build(
            user_id=user_id, events=events, outbox_entries=outbox_entries, fyi_mail=fyi_mail, now=now
        )
        if digest is None:
            return None
        if self._dev_mode and self._dev_channel is not None:
            return self._dev_channel.send(user_id, recipient, digest)
        if policy_applied is None or policy_applied.get("type") != "policy.applied":
            raise ValueError("production digest send requires a policy.applied authorisation record")
        data, authz = policy_applied["data"], copy.deepcopy(policy_applied["authz"])
        created, undo = str(authz.get("at") or digest.window_end), int(data.get("undo_window_s") or 0)
        entry = {
            "id": str(data["outbox_id"]),
            "idempotency_key": f"digest:{user_id}:{digest.window_end}",
            "world_id": self._world_id,
            "run_id": self._run_id,
            "action_type": str(data.get("action_type") or "send_email"),
            "connector": str(data.get("connector") or self._connector),
            "recipients": [recipient],
            "attachments": [],
            "item": copy.deepcopy(data.get("item")),
            "destination": data.get("destination"),
            "modifiers": [],
            "risk_tier": str(data.get("risk_tier") or "T2"),
            "authz": authz,
            "undo_window_s": undo,
            "scheduled_at": created,
            "state": "scheduled" if undo > 0 else "queued",
            "created_at": created,
        }
        return self._outbox.enqueue(entry, {"authorised_by": dict(policy_applied)})
