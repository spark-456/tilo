"""tilo_channels.plate_digest: the daily plate digest and reminder email (FR-PA-06; ADR-0021, PE-26, PE-29; PRD 10.3,
11.6, SEC-08).

The mail is a plain-text rendering of the signed-in person's plate `rows` (never `parked`), sent to their own trusted
mailbox through `DigestService.enqueue_text`: L3 policy decision, `policy.applied`, outbox, once per UTC day and kind.
Each work item row carries a Done and a Snooze link, signed single-use `LinkService` answer links bound to the item id
and the person (FR-CHN-07, 24 h). A link is a request to the caller's `PlateActionPort`, which checks ownership and
status again at the write (PE-10); a mail reply is never read, so an emailed "done" changes nothing. No model, no
network, no clock read beyond the injected one. Nothing here logs; a refusal carries only a stable reason code.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import re
import unicodedata
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import Any, Literal, Protocol
from urllib.parse import urlsplit

from tilo_policy.schemas import conforms

from tilo_channels.autopilot_state import timestamp
from tilo_channels.digest import DailyDigestBuilder, DigestService, _to_epoch_s
from tilo_channels.links import CardState, KeyRing, LinkRefused, LinkService, NonceStore, Redemption

__all__ = ["MAX_LISTED", "OPTIONS", "PlateActionPort", "PlateDigest", "PlateDigestBuilder", "PlateDigestService"]

OPTIONS = ("done", "snooze")  # the only two things an emailed link can ask for
MAX_LISTED = 25  # rows in one mail; the rest are counted, not listed
_ITEM_ID = re.compile(r"wi_[0-9A-Za-z_]{1,48}\Z")  # the work_item_id shape: a question card's link is not spent here
_SPACE = re.compile(r"\s+")
# PE-24: a link or an address in a title becomes `[removed]` before a mail client can linkify it beside the real links
_DEFANG = re.compile(r"(?i)\b(?:[a-z][a-z0-9+.-]{1,15}://|www\.)\S+|[^\s@<>()]+@[^\s@<>()]+\.[a-z0-9-]{2,}")
_REMINDER_GROUPS = ("overdue", "soon")
_GROUPS = {"attention": "Needs you now", "overdue": "Overdue", "soon": "Due soon", "rest": "Everything else"}
_REASONS = {
    "gate": "Approval waiting",
    "consent": "Consent waiting",
    "blocked": "A run is blocked",
    "question": "A question for you",
    "meeting_card": "A meeting card",
    "run": "A run in progress",
    "work_item": "A work item",
    "mail_reply": "Mail waiting for your reply",
    "pin_owner": "A pinned item",
    "pin_tagged": "A pinned item",
    "calendar": "A calendar entry",
}
_FOOTER = (
    "Done and Snooze links work once and expire after 24 hours; Snooze moves an item to tomorrow morning.",
    "Replies to this email change nothing. Open Tilo to do anything else.",
)


class PlateActionPort(Protocol):
    """The caller's seam (tilo-api): applies a redeemed Done or Snooze to the person's own open work item and returns
    whether it did. It checks owner and status again at the write; `authn` is "link" or "session"."""

    def apply(self, user_id: str, item_id: str, action: str, *, authn: str) -> bool: ...


@dataclass(frozen=True)
class PlateItem:
    item_id: str
    title: str
    due: str | None
    group: str
    done_url: str = field(repr=False)  # a live 24 h bearer link: never in a repr, log or traceback
    snooze_url: str = field(repr=False)


@dataclass(frozen=True)
class PlateDigest:
    user_id: str
    kind: Literal["digest", "reminder"]
    window_end: str
    items: tuple[PlateItem, ...]
    more: int
    flagged: int  # rows left out because the safety screen flagged them (PE-21); only their count is mailed
    rendered_text: str = field(repr=False)


def _line(text: Any, limit: int = 140) -> str:
    """One plain line: every control, format, separator and unassigned character becomes a space, whitespace is
    collapsed, a link or an address becomes `[removed]` (the plate has cleaned controls only; this is the second
    wall), cut at `limit`."""
    kept = "".join(" " if unicodedata.category(c)[0] in "CZ" else c for c in str(text))
    return _DEFANG.sub("[removed]", _SPACE.sub(" ", kept)).strip()[:limit]


def _work_item_card(item_id: str) -> CardState | None:
    """The card a link is checked against: a plain question that lists email, with the two options. The id is the
    work item's own (alphabet-checked here, so a crafted id never reaches the signer)."""
    if not isinstance(item_id, str) or not _ITEM_ID.match(item_id):
        return None
    card = {"kind": "needs_you", "rung": "needs_you", "gate": None, "consent": None, "answer_channels": ["email"]}
    return CardState(card=card | {"options": [{"id": o} for o in OPTIONS]}, answered=False)


def _fingerprint(rows: list[Any]) -> str:
    raw = json.dumps(rows, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(raw.encode()).hexdigest()


class PlateDigestBuilder:
    def __init__(
        self,
        *,
        base_url: str,
        keys: KeyRing,
        nonces: NonceStore,
        clock: Callable[[], dt.datetime] | None = None,
    ) -> None:
        parts = urlsplit(base_url) if isinstance(base_url, str) else None
        if parts is None or parts.scheme != "https" or not parts.hostname or parts.username or parts.password:
            raise ValueError("base_url must be https without user info")
        if parts.query or parts.fragment:
            raise ValueError("base_url must have no query or fragment")
        self._base_url, self._keys, self._nonces = base_url.rstrip("/"), keys, nonces
        self._clock = clock or (lambda: dt.datetime.now(dt.UTC))

    def daily_builder(self) -> DailyDigestBuilder:
        """The FR-CHN-18 builder over the same https base, key ring, nonce store and clock, for the `DigestService`
        that sends this mail (it asks only for the clock; no daily digest is built from it here)."""
        return DailyDigestBuilder(base_url=self._base_url, keys=self._keys, nonces=self._nonces, clock=self._clock)

    def _at(self, now: float | int | str | dt.datetime | None) -> dt.datetime:
        if now is None:
            return self._clock()
        if (seconds := _to_epoch_s(now)) is None:
            raise ValueError(f"invalid timestamp: {now!r}")
        return dt.datetime.fromtimestamp(seconds, tz=dt.UTC)

    def _links(self, at: dt.datetime) -> LinkService:
        return LinkService(
            keys=self._keys, nonces=self._nonces, clock=lambda: at, cards=_work_item_card, base_url=self._base_url
        )

    def build(
        self,
        *,
        user_id: str,
        plate: Mapping[str, Any],
        kind: Literal["digest", "reminder"] = "digest",
        now: float | int | str | dt.datetime | None = None,
    ) -> PlateDigest | None:
        """The mail for `user_id`'s plate, or None (nothing to send): an empty plate, a plate that does not validate,
        whose fingerprint is not its rows' or that belongs to someone else. `reminder` keeps overdue and due-soon
        work items only."""
        if not conforms("common.schema.json#/$defs/user_id", user_id) or kind not in ("digest", "reminder"):
            raise ValueError("invalid user_id or kind")
        if not conforms("plate.schema.json", plate) or plate["user"] != user_id:
            return None
        rows = plate["rows"]
        if plate["fingerprint"] != _fingerprint(rows):
            return None
        if kind == "reminder":
            rows = [r for r in rows if r["ref"]["kind"] == "work_item" and r["group"] in _REMINDER_GROUPS]
        # PE-21, PRD 16.2: a flagged record never reaches an unattended mail; no title, id or link of it is rendered
        flagged = sum(1 for r in rows if r["flagged"] is not False)
        rows = [r for r in rows if r["flagged"] is False]
        if not rows:
            return None
        at = self._at(now)
        window_end = timestamp(round(at.timestamp() * 1000))
        links, items, lines = self._links(at), list[PlateItem](), [f"Your plate for {window_end[:10]}"]
        listed, group = rows[:MAX_LISTED], None
        for row in listed:
            if row["group"] != group:
                group = row["group"]
                lines += ["", _GROUPS.get(group, "Everything else")]
            ref, title = row["ref"], _line(row["title"]) if row["title"] else ""
            label = title or _REASONS.get(row["reason"], "An item")
            due = f" (due {row['due']})" if row["due"] else ""
            lines.append(f"- {label}{due}")
            if ref["kind"] == "work_item" and {"done", "snooze"} <= set(row["actions"]):
                made = {
                    o: links.issue(card_id=ref["id"], user_id=user_id, action="answer", option=o).url for o in OPTIONS
                }
                items.append(PlateItem(ref["id"], title, row["due"], row["group"], made["done"], made["snooze"]))
                lines += [f"  Done: {made['done']}", f"  Snooze: {made['snooze']}"]
        more = len(rows) - len(listed)
        if more:
            lines += ["", f"{more} more on your plate in Tilo."]
        if flagged:
            lines += ["", f"{flagged} more need a look in Tilo."]
        lines += ["", *_FOOTER]
        return PlateDigest(user_id, kind, window_end, tuple(items), more, flagged, "\n".join(lines))

    def peek(self, token: str, *, now: float | int | str | dt.datetime | None = None) -> tuple[str, str, str]:
        """(item id, option, user) of a well-signed, unexpired Done or Snooze link, for a confirm page; consumes
        nothing (a GET must not redeem). `LinkRefused` for anything that is not one of ours."""
        card_id, action, option, user = self._links(self._at(now)).peek(token)
        if action != "answer" or option not in OPTIONS or not _ITEM_ID.match(card_id):
            raise LinkRefused("malformed")
        return card_id, option, user

    def redeem(
        self,
        token: str,
        *,
        item_id: str,
        option: str,
        viewer: str | None = None,
        now: float | int | str | dt.datetime | None = None,
    ) -> Redemption:
        """Verifies and consumes a Done or Snooze link (`LinkRefused` with a stable reason otherwise). The nonce is
        consumed last, so a refusal never burns the link."""
        if option not in OPTIONS:
            raise LinkRefused("unknown_option")
        return self._links(self._at(now)).redeem(token, card_id=item_id, action="answer", viewer=viewer, option=option)

    def redeem_and_apply(
        self,
        token: str,
        *,
        item_id: str,
        option: str,
        port: PlateActionPort,
        viewer: str | None = None,
        now: float | int | str | dt.datetime | None = None,
    ) -> bool:
        """Redeems the link, then asks the caller's port to apply it once. False when the port declines (the item is
        no longer the person's own open item); the link is spent either way."""
        got = self.redeem(token, item_id=item_id, option=option, viewer=viewer, now=now)
        if got.requires_sign_in or got.option not in OPTIONS:  # fail closed, whatever LinkService later learns
            return False
        return bool(port.apply(got.user_id, got.card_id, got.option, authn=got.authn))


class PlateDigestService:
    """Plate digest and reminder delivery: the FR-CHN-18 sender's owner, mailbox, quiet-hours and policy checks, then
    the same outbox path. One mail per UTC day and kind (`plate_digest`, `plate_reminder`)."""

    def __init__(self, *, builder: PlateDigestBuilder, sender: DigestService) -> None:
        self._builder, self._sender = builder, sender

    def deliver_if_non_empty(
        self,
        *,
        user_id: str,
        plate: Mapping[str, Any],
        kind: Literal["digest", "reminder"] = "digest",
        recipient: str | None = None,
        now: float | int | str | dt.datetime | None = None,
    ) -> dict[str, Any] | None:
        cleared = self._sender.ready(user_id, recipient=recipient, now=now)
        if cleared is None:
            return None
        owner_addr, check_now = cleared
        digest = self._builder.build(user_id=user_id, plate=plate, kind=kind, now=check_now)
        if digest is None:
            return None
        subject = "Your plate" if kind == "digest" else "Reminders from your plate"
        return self._sender.enqueue_text(
            user_id=user_id,
            owner_addr=owner_addr,
            window_end=digest.window_end,
            rendered_text=digest.rendered_text,
            kind=f"plate_{kind}",
            subject=subject,
        )
