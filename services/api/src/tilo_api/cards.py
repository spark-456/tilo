"""tilo_api.cards -- the API side of cards and batching (FR-HIL-01, FR-HIL-02; PRD 10.1-10.3, 10.6,
9.5, FR-INT-09). Public shapes are pinned in services/api/tests/API_ST3b.md; its "Ambiguities
resolved" section and docs/open-questions.md record the PRD defaults this module applies.

CardStore is a plain, deterministic in-memory store: an injected Clock and EventWriter, no network,
no randomness. A card is validated against contracts/card.schema.json plus the validator rules
CR-01 and CR-02 before it is stored; an invalid card is never shown and never times out. Gate and
consent cards are authorisations: never merged, never delegated to the Director, and never resolved
by a timeout. Who answers comes only from the verified `deps.Principal` (PRD 10.1), never from the
request body: a web or mobile web session (one signed-in class) records either; an authenticated tilo-channels
caller claims only email, and only on a needs_you card, never a gate (CH-RM, SEC-06; `session_allows`). WhatsApp was
removed (SD-01, ADR-0019): no PIN path exists. Deciding whether an answer opens a gate stays with packages/policy.
"""

from __future__ import annotations

import copy
import datetime
import functools
import hashlib
import json
import logging
import re
import secrets
import threading
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any, Protocol
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import jsonschema
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict
from referencing import Registry, Resource
from referencing.jsonschema import DRAFT202012
from tilo_harness.question_wait import AlreadyCommitted  # raised by an event writer; one class for both sides

from tilo_api.deps import Principal, get_current_principal
from tilo_api.redaction import _DISTRICT_RE, _safe_districts

logger = logging.getLogger("tilo_api.cards")
CONTRACTS = Path(__file__).resolve().parents[4] / "contracts"

_TS_FMT = "%Y-%m-%dT%H:%M:%S.%fZ"
_HHMM_RE = re.compile(r"^([01][0-9]|2[0-3]):([0-5][0-9])$")
_ULID_RE = re.compile(r"^[0-7][0-9A-HJKMNP-TV-Z]{25}$")
_USER_RE = re.compile(r"^u_[0-9A-Za-z_]{1,48}$")
_DOMAIN_RE = re.compile(r"[a-z][a-z0-9_]{0,63}")  # common.schema.json slug
_MERGEABLE = ("needs_you", "meeting")
_ROLES = ("owner", "team_lead", "approver")  # any other role (a Viewer included) answers and lists nothing
_CROCKFORD = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"
_WEB_CHANNELS = ("web", "mobile_web")
OWNER_ONLY_ACTIONS = frozenset({"create_meeting_event"})  # FR-MTG-09, ADR-0024: no plan names it, no Approver opens it
_ANSWER_CHANNELS = (*_WEB_CHANNELS, "email")  # the only channels that answer, whatever a card lists (CH-RM)
_STATUS = {"card_not_found": 404, "forbidden": 403, "busy": 409}  # AnswerResult.reason -> HTTP; others are 400
_ALWAYS_NOTIFY = frozenset({"gate", "blocked"})


def _parse_hhmm(value: object) -> int | None:
    if not isinstance(value, str) or (m := _HHMM_RE.match(value.strip())) is None:
        return None
    return int(m.group(1)) * 60 + int(m.group(2))


def _quiet_hours_active(prefs: Mapping[str, Any] | None, now: datetime.datetime) -> bool:
    """FR-HIL-13: whether `now` falls in the user's `[start, end)` quiet-hours window in their IANA timezone."""
    if not isinstance(prefs, Mapping):
        return False
    raw = prefs.get("quiet_hours")
    block = raw if isinstance(raw, Mapping) else (prefs if "start" in prefs and "end" in prefs else None)
    if not isinstance(block, Mapping) or block.get("enabled") is False:
        return False
    start_min, end_min = _parse_hhmm(block.get("start")), _parse_hhmm(block.get("end"))
    if start_min is None or end_min is None or start_min == end_min:
        return False
    tz_name = (
        block.get("timezone") or block.get("time_zone") or prefs.get("timezone") or prefs.get("time_zone") or "UTC"
    )
    if not isinstance(tz_name, str) or not tz_name.strip():
        return False
    try:
        tz = ZoneInfo(tz_name.strip())
    except (ZoneInfoNotFoundError, KeyError, ValueError):
        return False
    local_dt = now.astimezone(tz)
    cur_min = local_dt.hour * 60 + local_dt.minute
    return (start_min <= cur_min < end_min) if start_min < end_min else (cur_min >= start_min or cur_min < end_min)


def _derived_id(seed: str) -> str:
    """A ulid derived from `seed`: the same seed always gives the same id. Its time part is arbitrary (some ids
    decode to the year 2047), so never sort or order events by these ids; `seq` is the order."""
    n = int.from_bytes(hashlib.sha256(seed.encode()).digest(), "big") % 32**25
    chars = []
    for _ in range(25):
        n, r = divmod(n, 32)
        chars.append(_CROCKFORD[r])
    return "0" + "".join(chars)


def _alert_id(card_id: str) -> str:
    """The timeout nudge's own id: a retry reuses it and it never collides with an alert the harness raised."""
    return _derived_id(f"{card_id}:timeout")


def _parse_ts(ts: str) -> datetime.datetime:
    return datetime.datetime.strptime(ts, _TS_FMT).replace(tzinfo=datetime.UTC)


@functools.cache
def _registry() -> Registry:
    """Every contracts/**/*.schema.json loaded by its own $id, so card.schema.json's $refs into
    common.schema.json resolve."""
    resources: list[tuple[str, Resource]] = []
    for path in sorted(CONTRACTS.glob("**/*.schema.json")):
        data = json.loads(path.read_text(encoding="utf-8"))
        resources.append((data["$id"], Resource.from_contents(data, default_specification=DRAFT202012)))
    return Registry().with_resources(resources)


@functools.cache
def _card_schema() -> dict[str, Any]:
    return json.loads((CONTRACTS / "card.schema.json").read_text(encoding="utf-8"))


def _deadline(card: dict) -> datetime.datetime:
    """created_at + timeout; ValueError (not a real calendar instant) or OverflowError (a timeout
    past year 9999) means the card can never time out, so it is rejected up front."""
    return _parse_ts(card["created_at"]) + datetime.timedelta(seconds=card["timeout"])


def _card_errors(card: Any) -> list[str]:
    """Schema errors, then the validator-only rules CR-01 and CR-02 and a representable deadline;
    empty when valid. A rejected card is never stored and never times out."""
    schema = _card_schema()
    cls = jsonschema.validators.validator_for(schema, default=jsonschema.Draft202012Validator)
    errors = [e.message for e in cls(schema, registry=_registry()).iter_errors(card)]
    if errors:
        return errors
    ids = [o["id"] for o in card["options"]]
    if len(set(ids)) != len(ids):
        errors.append("CR-02: option ids must be unique within a card")
    if card["safe_default"] not in ids:
        errors.append("CR-01: safe_default must name one of options[].id")
    try:
        _deadline(card)
    except (ValueError, OverflowError):
        errors.append("created_at must be a real calendar instant and created_at + timeout must be representable")
    return errors


class Clock(Protocol):
    def now(self) -> str: ...  # RFC 3339, common.schema.json#/$defs/timestamp


class EventWriter(Protocol):
    def write(self, part: dict) -> None: ...

    """The API never stamps id/seq/ts/run_id (PI-18) -- it hands the harness-owned writer an
    unstamped part: {"type": str, "data": dict, "authz": dict | None, "severity"?: str} plus the
    scope the writer needs to stamp it: "world_id", "card_id" (question.answered data has no card
    field), "district", "vis" (["<district>"], or None for an owner-only card whose district is
    unknown), "owner_only", "event_id" (the event's own `id`, one per card resolution: the writer
    must commit under it and resend it unchanged) and, for a person's answer to a question, "option" (the chosen
    option id, for the agent waiting on it; not event data). The writer must not default a part without a vis
    to "all". If that id is already committed under other content, it raises AlreadyCommitted."""


@dataclass(frozen=True)
class SubmitResult:
    outcome: str  # "accepted" | "merged" | "rejected"
    card_id: str | None
    errors: tuple[str, ...]


@dataclass(frozen=True)
class AnswerResult:
    outcome: str  # "answered" | "rejected"
    reason: str | None
    emitted: tuple[dict, ...]


class ShareRefused(Exception):
    """`share_gate` refused; `args[0]` is a stable reason (card_not_found, not_an_open_gate, card_invalid)."""


@dataclass(frozen=True)
class TimeoutResult:
    card_id: str
    kind: str
    held: bool


@dataclass
class _Group:
    """Cards that merged into one: the first card's id and created_at anchor the 60 s window."""

    primary_id: str
    anchor: datetime.datetime
    members: list[_Record] = field(default_factory=list)
    closed: bool = False  # one answer or one timeout closes the whole group
    resolving: bool = False  # set under the store lock before the write, cleared if it raises


@dataclass
class _Record:
    """One stored card with its own question and options; merging only groups records."""

    world_id: str
    card: dict[str, Any]
    outbox_id: str | None
    district: str | None
    assignee: str | None
    deadline: datetime.datetime
    group: _Group
    status: str = "open"  # "open" | "resolved" -- a held gate/consent stays "open"
    attempt: tuple[tuple, dict] | None = None  # (who and what, part) of a write that raised: a retry resends it
    domain: str | None = None  # the Team Lead domain the question was routed to; None is the owner fallback
    assignee_until: datetime.datetime | None = None  # a share link's expiry: the assignee sees nothing at or after it
    reraised_from: str | None = None  # a share's new card names the gate card it re-raised (FR-HIL-12)

    @property
    def kind(self) -> str:
        return self.card["kind"]

    def assignee_until_live(self, now: datetime.datetime) -> bool:
        return self.assignee_until is None or now < self.assignee_until


def _can_see(p: Principal, world_id: str, owner: str | None, r: _Record, now: datetime.datetime) -> bool:
    """PRD 10.1 scope: the owner sees every card, a Team Lead their districts' cards, an Approver
    only the cards assigned to them (and, for a share link's card, only before it expires); a Viewer none."""
    if p.world_id != world_id or owner is None or _USER_RE.match(p.user_id) is None:
        return False
    if p.role == "owner":
        return p.user_id == owner
    if p.role == "team_lead":
        # a question routed to a domain is the console's: only that domain's lead sees it (FR-HIL-10)
        return r.domain is None and r.district is not None and r.district in _safe_districts(p.districts)
    return p.role == "approver" and r.assignee == p.user_id and (r.assignee_until is None or now < r.assignee_until)


def _routed_to(r: _Record, world_id: str, domain: str) -> bool:
    return r.world_id == world_id and r.kind in _MERGEABLE and r.domain == domain


def _can_answer(p: Principal, r: _Record) -> bool:
    """A Team Lead answers only questions here: opening a gate needs the policy engine's lead
    record and policy (open_gate), and consent is the owner's grant. An Approver answers assigned
    questions and gates."""
    if p.role == "owner":
        return True
    return (p.role == "team_lead" and r.kind in _MERGEABLE) or (p.role == "approver" and r.kind != "consent")


class CardStore:
    def __init__(
        self,
        *,
        clock: Clock,
        writer: EventWriter,
        world_owners: dict[str, str] | None = None,
        merge_window_s: int = 60,
        preferences: Any | None = None,
        notifier: Callable[[dict], None] | None = None,
    ) -> None:
        self._clock = clock
        self._writer = writer
        self._world_owners = dict(world_owners or {})
        self._merge_window_s = merge_window_s
        self._preferences = preferences
        self._notifier = notifier
        self._records: dict[str, dict[str, _Record]] = {}
        self._seen: dict[tuple[str, str], tuple[str, SubmitResult]] = {}
        self._groups: dict[tuple, _Group] = {}
        self._pending: dict[tuple[str, str], _Record] = {}  # open and not yet nudged: tick's work set
        self._answers_by_lead: list[dict[str, Any]] = []  # a Team Lead's own answers, in order (FR-HIL-10)
        self._lock = threading.RLock()  # guards every state change; a write happens outside it

    def _user_prefs(self, user_id: str | None) -> Mapping[str, Any] | None:
        if not user_id or self._preferences is None:
            return None
        if isinstance(self._preferences, Mapping):
            return self._preferences.get(user_id)
        if callable(getattr(self._preferences, "get", None)):
            return self._preferences.get(user_id)
        return None

    def should_notify(self, card: dict, *, user_id: str | None = None, now: str | None = None) -> bool:
        """FR-HIL-13: during quiet hours only `gate` and `blocked` cards notify."""
        target = user_id or self._world_owners.get(card.get("world_id", ""))
        instant = _parse_ts(now or self._clock.now())
        rung = str(card.get("rung") or card.get("kind") or "").lower()
        if _quiet_hours_active(self._user_prefs(target), instant):
            return rung in _ALWAYS_NOTIFY or card.get("kind") == "gate"
        return True

    # -- submit ---------------------------------------------------------

    def submit(
        self,
        card: dict,
        *,
        outbox_id: str | None = None,
        district: str | None = None,
        assignee: str | None = None,
        domain: str | None = None,
        merge: bool = True,
    ) -> SubmitResult:
        """`merge=False` keeps the card its own group: it neither joins nor anchors a batch (a question a unit waits on
        means something of its own, so one answer must never close it for another).
        `outbox_id` (gates only), `district` (a Team Lead sees only their districts' cards; none
        means owner-only), `assignee` (the Approver the owner assigned) and `domain` (a question's routed Team
        Lead domain, FR-HIL-10; none is the owner fallback) are companion data the harness already holds; a
        model never supplies them. Re-submitting identical content returns the first result and changes
        nothing; a different card under a used id is rejected."""
        with self._lock:
            return self._submit(card, outbox_id, district, assignee, domain, merge)

    def _submit(
        self,
        card: dict,
        outbox_id: str | None,
        district: str | None,
        assignee: str | None,
        domain: str | None,
        merge: bool,
    ) -> SubmitResult:
        errors = self._submit_errors(card, outbox_id, district, assignee, domain)
        if errors:
            return SubmitResult("rejected", None, tuple(errors))

        world_id, card_id, kind = card["world_id"], card["id"], card["kind"]
        digest = hashlib.sha256(
            json.dumps([card, outbox_id, district, assignee, domain], sort_keys=True).encode()
        ).hexdigest()
        seen = self._seen.get((world_id, card_id))
        if seen is not None:
            return seen[1] if seen[0] == digest else SubmitResult("rejected", None, ("card id already used",))

        created = _parse_ts(card["created_at"])
        key = (world_id, kind, card["header"]["building"], district, assignee, domain)  # domain: never merge across
        batched = merge and kind in _MERGEABLE
        group = self._groups.get(key) if batched else None
        merged = (
            group is not None
            and not group.closed
            and not group.resolving  # its answer is being written: this card must stay open for its own answer
            and abs((created - group.anchor).total_seconds()) <= self._merge_window_s
        )
        if not merged:
            group = _Group(card_id, created)
            if batched:
                self._groups[key] = group
        assert group is not None
        record = _Record(world_id, copy.deepcopy(card), outbox_id, district, assignee, _deadline(card), group)
        record.domain = domain
        group.members.append(record)
        self._records.setdefault(world_id, {})[card_id] = record
        self._pending[(world_id, card_id)] = record
        result = SubmitResult("merged" if merged else "accepted", group.primary_id, ())
        self._seen[(world_id, card_id)] = (digest, result)
        if not merged and self._notifier is not None:
            recipient = assignee or self._world_owners.get(world_id)
            if self.should_notify(record.card, user_id=recipient):
                self._notifier(copy.deepcopy(record.card))
        return result

    def _submit_errors(
        self, card: dict, outbox_id: str | None, district: str | None, assignee: str | None, domain: str | None
    ) -> list[str]:
        """Every reason `_submit` would refuse this card on its own content (empty: it would store it)."""
        errors = _card_errors(card)
        if not errors:
            errors = self._companion_errors(card["kind"], outbox_id, district, assignee, domain)
        if not errors:
            usable = _WEB_CHANNELS if card["kind"] in ("gate", "consent") else _ANSWER_CHANNELS
            if not set(card["answer_channels"]) & set(usable):  # a card nobody can answer is never stored (CH-RM)
                errors = ["answer_channels: no listed channel can answer this card"]
        return errors

    @staticmethod
    def _companion_errors(
        kind: str, outbox_id: str | None, district: str | None, assignee: str | None, domain: str | None
    ) -> list[str]:
        errors = []
        if domain is not None and (
            kind not in _MERGEABLE or not isinstance(domain, str) or not _DOMAIN_RE.fullmatch(domain)
        ):
            errors.append("domain must be a slug, and only a question card is routed to one")
        if kind == "gate" and (not outbox_id or not _ULID_RE.match(outbox_id)):
            errors.append("outbox_id is required and must be a ulid for a gate card")
        if kind != "gate" and outbox_id is not None:
            errors.append("outbox_id must not be given for a non-gate card")
        if district is not None and not _DISTRICT_RE.match(district):
            errors.append("district must be a district id")
        if assignee is not None and not _USER_RE.match(assignee):
            errors.append("assignee must be a user id")
        return errors

    def _resolve_group(self, group: _Group) -> None:
        """Close every open member: one answer or one timeout closes a merged batch (BQ-74)."""
        for member in group.members:
            member.status, member.attempt = "resolved", None
            self._pending.pop((member.world_id, member.card["id"]), None)
        group.closed, group.resolving = True, False

    def _part(
        self, record: _Record, type_: str, data: dict, *, authz: dict | None = None, severity: str | None = None
    ) -> dict:
        """An unstamped part with the record's world and scope. A district card is `vis` its own
        district; event vis cannot express owner-only (district_list needs 1+ districts), so a card
        with no district carries vis None and owner_only True, never "all" (BQ-73)."""
        part: dict[str, Any] = {"type": type_, "data": data, "authz": authz, "world_id": record.world_id}
        part |= {"card_id": record.card["id"], "district": record.district, "owner_only": record.district is None}
        part["vis"] = [record.district] if record.district else None
        # One id per card resolution (card, event type, option), so a retry after a commit-then-raise is an identical
        # resend the writer dedupes (FR-HIL-07, #155), never a second event. A question's data holds no option, so a
        # question never gets two ids.
        part["event_id"] = _derived_id(f"{record.world_id}:{record.card['id']}:{type_}:{data.get('option', '')}")
        if severity:
            part["severity"] = severity
        return part

    def owner_of(self, world_id: str) -> str | None:
        return self._world_owners.get(world_id)

    def now(self) -> str:
        return self._clock.now()

    # -- reads ------------------------------------------------------------

    def is_open(self, world_id: str, card_id: str) -> bool:
        """Whether the card still waits for an answer (a gate's answer closes every card of it)."""
        with self._lock:
            return (r := self._records.get(world_id, {}).get(card_id)) is not None and r.status == "open"

    def get(self, world_id: str, card_id: str) -> dict | None:
        """A card by its own submitted id, merged or not."""
        record = self._records.get(world_id, {}).get(card_id)
        return copy.deepcopy(record.card) if record else None

    def list_for_world(self, world_id: str, *, principal: Principal) -> list[dict]:
        """The cards `principal` may see, oldest first: one per open group (its first open
        member, so a merge shows as one card until one answer or timeout closes the group). Raises
        PermissionError for a Viewer or a non-member. A Team Lead sees only their districts' cards, so
        a hidden district's cards and their count never leave the API (FR-HIL-09)."""
        owner = self._world_owners.get(world_id)
        if (
            principal.role not in _ROLES
            or principal.world_id != world_id
            or owner is None
            or (principal.role == "owner" and principal.user_id != owner)
        ):
            raise PermissionError(f"{principal.user_id} may not list cards of world {world_id}")
        shown: dict[int, _Record] = {}
        now = _parse_ts(self._clock.now())
        with self._lock:
            for record in self._records.get(world_id, {}).values():
                if (
                    record.status == "open"
                    and id(record.group) not in shown
                    and _can_see(principal, world_id, owner, record, now)
                ):
                    shown[id(record.group)] = record
            return sorted((copy.deepcopy(r.card) for r in shown.values()), key=lambda c: c["created_at"])

    def list_for_domain(self, world_id: str, domain: str) -> list[dict]:
        """FR-HIL-10: the open question cards routed to `domain`, oldest first, one per merged group. Gates,
        consents and cards routed elsewhere (another domain or the owner) are never in it."""
        with self._lock:
            shown: dict[int, _Record] = {}
            for record in self._records.get(world_id, {}).values():
                if record.status == "open" and id(record.group) not in shown and _routed_to(record, world_id, domain):
                    shown[id(record.group)] = record
            return sorted((copy.deepcopy(r.card) for r in shown.values()), key=lambda c: c["created_at"])

    def plate_facts(self, user_id: str, *, limit: int = 500) -> list[dict]:
        """PEOPLE-SEAMS-1 (ADR-0021, PE-27): the plate's card facts for `user_id` alone, oldest first, one per group:
        every open card of a world the person owns, and an open gate whose live Approver assignment names them (a share
        link's expiry ends it). `{data, world_owner, approver, answered: False}`; nothing of any other person's."""
        now = _parse_ts(self._clock.now())
        with self._lock:
            shown: dict[int, tuple[_Record, str | None]] = {}
            for world_id, records in self._records.items():
                owner = self._world_owners.get(world_id)
                for record in records.values():
                    if record.status != "open" or id(record.group) in shown:
                        continue
                    approves = record.kind == "gate" and record.assignee == user_id and record.assignee_until_live(now)
                    if (owner is not None and owner == user_id) or approves:
                        shown[id(record.group)] = (record, owner)
            found = sorted(shown.values(), key=lambda pair: (pair[0].card["created_at"], pair[0].card["id"]))
            return [
                {
                    "data": copy.deepcopy(r.card),
                    "world_owner": owner,
                    "approver": r.assignee if r.kind == "gate" and r.assignee_until_live(now) else None,
                    "answered": False,
                }
                for r, owner in found[: max(limit, 0)]
            ]

    def lead_answers(self, world_id: str, user_id: str) -> list[dict]:
        """FR-HIL-10: this Team Lead's own answers (never a timeout default), each `{card_id, option, answered_at,
        answer_time_s}`, with the time read from the injected clock."""
        with self._lock:
            return [
                {k: v for k, v in h.items() if k not in ("world_id", "user_id")}
                for h in self._answers_by_lead
                if h["world_id"] == world_id and h["user_id"] == user_id
            ]

    # -- share a gate with an Approver (FR-HIL-12) --------------------------------

    def share_gate(self, world_id: str, card_id: str, *, approver: str, until: str) -> tuple[str, str, list[str]]:
        """BQ-32, ADR-0006: re-raise an open gate as a NEW proposal for the owner's chosen Approver: a new card (new
        id, a fresh outbox id, the same gate, tier and pinned item) seen by that Approver until `until`, after one
        `approval.requested` naming `approver {user, assigned_by: {by: owner, at: now}}` (authz null: a proposal never
        authorises). The new card joins the original's group, so the gate is ONE wait: the first answer on any of its
        cards closes them all, in the one step that writes it. A gate has at most one live share: sharing again ends the
        earlier one's assignment. Returns (new card id, the assignment's time, the cards whose assignment it ended). The
        caller has already checked that the signed-in person is the world's owner; the original card is untouched. Held
        under the lock throughout, so no answer lands between the proposal and the card. Raises ShareRefused."""
        with self._lock:
            record = self._records.get(world_id, {}).get(card_id)
            owner = self._world_owners.get(world_id)
            if record is None or owner is None:
                raise ShareRefused("card_not_found")
            group = record.group
            if record.kind != "gate" or record.status != "open" or group.closed or group.resolving:
                raise ShareRefused("not_an_open_gate")
            if record.reraised_from is not None:
                raise ShareRefused("not_an_original_gate")  # a shared card is never shared again
            if record.card["gate"]["action"]["type"] in OWNER_ONLY_ACTIONS:
                raise ShareRefused("owner_only_gate")
            now = self._clock.now()
            new_id, outbox_id = _derived_id(secrets.token_hex(16)), _derived_id(secrets.token_hex(16))
            card = copy.deepcopy(record.card) | {"id": new_id, "created_at": now}
            if self._submit_errors(card, outbox_id, record.district, approver, None):  # before anything is written
                raise ShareRefused("card_invalid")
            gate = card["gate"]
            data = {
                "gate_id": gate["id"],
                "card_id": new_id,
                "outbox_id": outbox_id,
                "action_type": gate["action"]["type"],
            }
            data |= {
                "risk_tier": gate["risk_tier"],
                "irreversible": gate["irreversible"],
                "item": gate["action"].get("item"),
            }
            data |= {"approver": {"user": approver, "assigned_by": {"by": owner, "at": now}}, "team_lead": None}
            draft = _Record(world_id, card, outbox_id, record.district, approver, _deadline(card), group)
            part = self._part(draft, "approval.requested", data, authz=None) | {"reraised_from": card_id}
            self._writer.write(part)  # the proposal is on record before the card can be seen; a failure stores nothing
            ended = [m.card["id"] for m in group.members if m.assignee is not None and m.reraised_from is not None]
            for earlier in ended:
                self.unassign(world_id, earlier)
            if self._submit(card, outbox_id, record.district, approver, None, False).outcome != "accepted":
                raise ShareRefused("card_invalid")
            shared = self._records[world_id][new_id]
            self._pending.pop((world_id, new_id), None)  # the original's nudge speaks for the gate
            shared.group.members.remove(shared)
            shared.group = group
            group.members.append(shared)
            shared.reraised_from, shared.assignee_until = card_id, _parse_ts(until)
        return new_id, now, ended

    def unassign(self, world_id: str, card_id: str) -> None:
        """Ends an Approver's assignment (a revoked or replaced share link): the card stays open for the owner."""
        with self._lock:
            if (record := self._records.get(world_id, {}).get(card_id)) is not None:
                record.assignee = record.assignee_until = None

    # -- answer -------------------------------------------------------------

    def answer(
        self,
        world_id: str,
        card_id: str,
        *,
        option: str,
        channel: str,
        principal: Principal,
        console_domain: str | None = None,
    ) -> AnswerResult:
        """Rejections write nothing and leave the card open. A card outside the principal's scope
        is "card_not_found" (no existence oracle); a Viewer or a role that may not answer that
        kind is "forbidden". `console_domain` (FR-HIL-10, set only by the Team Lead console after it
        resolved the caller) scopes the answer to the questions routed to that domain instead of to districts."""
        with self._lock:
            record = self._records.get(world_id, {}).get(card_id)
            if principal.role not in _ROLES:
                return AnswerResult("rejected", "forbidden", ())
            if record is None:
                seen = False
            elif console_domain is not None:
                seen = principal.world_id == world_id and _routed_to(record, world_id, console_domain)
            else:
                now = _parse_ts(self._clock.now())
                seen = _can_see(principal, world_id, self._world_owners.get(world_id), record, now)
            if record is None or not seen:
                return AnswerResult("rejected", "card_not_found", ())
            if not _can_answer(principal, record):
                return AnswerResult("rejected", "forbidden", ())
            if record.status != "open":
                return AnswerResult("rejected", "already_resolved", ())
            if record.group.resolving:  # a write is in flight and may still fail, so the card may reopen: retry
                return AnswerResult("rejected", "busy", ())

            card = record.card
            if option not in {o["id"] for o in card["options"]}:
                return AnswerResult("rejected", "invalid_option", ())
            if channel not in card["answer_channels"] or channel not in _ANSWER_CHANNELS:
                # SEC-06: a gate opens only in a signed-in session; any other channel is refused, whatever a card lists
                return AnswerResult("rejected", "invalid_channel", ())
            if channel == "email" and record.kind != "needs_you":
                return AnswerResult("rejected", "invalid_channel", ())  # email answers a plain question only (CH-RM)

            who = (option, channel, principal.user_id, principal.role)
            authz = {"by": "person", "ref": principal.user_id, "at": self._clock.now()}
            if record.attempt is not None and record.attempt[0] == who:
                part: dict | None = record.attempt[1]  # this answer again after a write that raised: resend it as is
            elif record.kind == "gate":
                # CR-07: only approve opens a gate and writes approval.resolved; edit and hold write nothing.
                data = {"gate_id": card["gate"]["id"], "card_id": card_id, "outbox_id": record.outbox_id}
                data |= {"option": option, "channel": channel}
                data["pin_verified"] = False  # a required field that no rule reads (ADR-0019)
                part = self._part(record, "approval.resolved", data, authz=authz) if option == "approve" else None
            elif record.kind == "consent":
                # CR-13: only connect grants the connection; hold leaves it waiting.
                data = {"connector": card["consent"]["connector"], "card_id": card_id}
                data["scopes"] = card["consent"]["scopes"]
                part = self._part(record, "connection.consented", data, authz=authz) if option == "connect" else None
            else:
                by = "team_lead" if principal.role == "team_lead" else "person"
                part = self._part(record, "question.answered", {"answered_by": by}) | {"option": option}
                # `option` is scope for the waiting agent (BQ-207), not event data: the event stays {answered_by}
            if part is None:
                return AnswerResult("answered", None, ())
            record.group.resolving = True  # exactly one resolution per card: later answers and tick see this
        if not self._write_then_close(record, who, part):
            return AnswerResult("rejected", "already_resolved", ())  # an earlier answer committed: it won
        if principal.role == "team_lead" and part["type"] == "question.answered":
            self._note_answer(record, principal.user_id, option, authz["at"])
        return AnswerResult("answered", None, (part,))

    def _note_answer(self, record: _Record, user_id: str, option: str, at: str) -> None:
        seconds = (_parse_ts(at) - _parse_ts(record.card["created_at"])).total_seconds()
        entry = {"world_id": record.world_id, "user_id": user_id, "card_id": record.card["id"], "option": option}
        with self._lock:
            self._answers_by_lead.append({**entry, "answered_at": at, "answer_time_s": seconds})

    def _write_then_close(self, record: _Record, who: tuple, part: dict) -> bool:
        """False when the resolution was already committed by an earlier answer (the card closes under it)."""
        try:
            self._writer.write(part)  # outside the lock; a failed write leaves the card open
        except AlreadyCommitted:
            with self._lock:
                self._resolve_group(record.group)
            return False
        except BaseException:
            with self._lock:
                record.group.resolving = False
                record.attempt = (who, part)  # it may have committed: the same answer resends this exact part
            raise
        with self._lock:
            self._resolve_group(record.group)
        return True

    # -- timeouts -------------------------------------------------------------

    def tick(self) -> list[TimeoutResult]:
        """Every open card past its own deadline gets its safe default and a Nudge (BQ-04). A
        question closes its whole merged group with one question.answered (answered_by default,
        severity nudge). A gate or consent card is held, never resolved and never approved: it
        posts one alert.raised nudge instead, because question.answered would close the card on
        every channel (PI-03). A card a person is answering right now is skipped."""
        now = _parse_ts(self._clock.now())
        claimed: list[tuple[tuple[str, str], _Record, bool]] = []
        with self._lock:
            for key, record in list(self._pending.items()):
                if now < record.deadline or record.group.resolving or record.status != "open":
                    continue
                held = record.kind in ("gate", "consent")
                if held:
                    del self._pending[key]  # nudged once; still open for a person
                else:
                    record.group.resolving = True
                claimed.append((key, record, held))
        results: list[TimeoutResult] = []
        failures: list[Exception] = []
        for i, (key, record, held) in enumerate(claimed):
            try:
                if held:
                    data = {"alert_id": _alert_id(key[1]), "card_id": key[1]}
                    self._writer.write(self._part(record, "alert.raised", data, severity="nudge"))
                else:
                    part = self._part(record, "question.answered", {"answered_by": "default"}, severity="nudge")
                    try:
                        self._writer.write(part)
                    except AlreadyCommitted:  # a person's answer is already committed: the question is resolved
                        pass
                    with self._lock:
                        self._resolve_group(record.group)
                results.append(TimeoutResult(card_id=key[1], kind=record.kind, held=held))
            except AlreadyCommitted:  # the nudge itself is already committed
                results.append(TimeoutResult(card_id=key[1], kind=record.kind, held=held))
            except BaseException as exc:
                # This claim, and (if the failure is not an ordinary error) every later one, goes back to the
                # work set for the next tick; an ordinary failure never blocks the cards after it.
                rest = [claimed[i]] if isinstance(exc, Exception) else claimed[i:]
                with self._lock:
                    for k, r, h in rest:
                        if h:
                            self._pending[k] = r
                        else:
                            r.group.resolving = False
                if not isinstance(exc, Exception):
                    raise
                failures.append(exc)
        if failures:
            raise failures[0]
        return results


class _AnswerBody(BaseModel):
    """No identity field: who answers is the verified principal. `channel` is honoured only from an
    authenticated tilo-channels caller; `pin_verified` is refused (no PIN exists, SEC-06)."""

    model_config = ConfigDict(extra="forbid")

    option: str
    channel: str = "web"
    pin_verified: bool = False


def session_allows(principal: Principal, claimed: str, from_channels: bool) -> bool:
    """The channel a request may record comes from its authenticated session, never the body (CH-RM, SEC-06). A user's
    session is web or mobile web, one signed-in class (policy SIGNED_IN): it may record either, never email or
    anything else. A tilo-channels caller acting for an email session may claim only email. Checked before the store
    sees the answer, so a refusal resolves, closes and writes nothing."""
    if from_channels:
        return principal.channel == "email" and claimed == "email"
    return principal.channel in _WEB_CHANNELS and claimed in _WEB_CHANNELS


def answering_principal(
    principal: Principal, world_id: str, *, record_owner: str | None, cards: CardStore, from_channels: bool
) -> Principal | None:
    """Who answers a card in `world_id` (BQ-XWORLD-1, BQ-XWORLD-2). A session bound to that world, unchanged. Otherwise
    only role owner, on the user's own web or mobile_web session (never a tilo-channels caller, so never an email link),
    when both the world's record owner and its run's CardStore owner are the caller: the principal narrowed to that
    world, role and user unchanged, and only on a full web sign-in session (`full_session`, BQ-XWORLD-10), so a
    signed-link landing session stays bound. Anything else is None, the unknown-world 404. Checked on every request."""
    if principal.world_id == world_id:
        return principal
    me = principal.user_id
    if principal.role != "owner" or principal.channel not in _WEB_CHANNELS or from_channels:
        return None
    if not principal.full_session:
        return None
    if record_owner != me or cards.owner_of(world_id) != me:
        return None
    return replace(principal, world_id=world_id)


def reading_principal(principal: Principal, world_id: str, *, record_owner: str | None) -> Principal | None:
    """Who reads `world_id`'s cards (BQ-XWORLD-6): a session bound to it, or its record owner with role owner on any
    channel, as `GET /cards` shows them (narrowed to that world); anyone else is None, the unknown-world 404. What the
    owner sees there, full or redacted, is `as_read_by`'s (BQ-XWORLD-9)."""
    if principal.world_id == world_id:
        return principal
    if principal.role == "owner" and record_owner == principal.user_id:
        return replace(principal, world_id=world_id)
    return None


_SUMMARY_KEYS = ("id", "world_id", "kind", "created_at", "timeout")


def as_read_by(session: Principal, world_id: str, cards: list[dict]) -> list[dict]:
    """What `session` reads of `world_id`'s cards (BQ-XWORLD-9): in full in its bound world or on a full web sign-in;
    otherwise each card as a summary built from an allowlist (ids, kind, timing, the gate's tier), never free text."""
    if session.world_id == world_id or session.full_session:
        return cards
    summaries = []
    for card in cards:
        gate = card.get("gate")
        summary = {key: card.get(key) for key in _SUMMARY_KEYS}
        summary["risk_tier"] = gate.get("risk_tier") if isinstance(gate, dict) else None
        summary["redacted"] = True
        summaries.append(summary)
    return summaries


def get_channels_caller() -> bool:
    """True only when the request was authenticated as tilo-channels, acting for the principal
    (service-to-service auth lands with sign-in, PRD 15.3). Until then no caller is, so every
    request is a web-session answer."""
    return False


def build_router(
    cards: CardStore | Callable[..., CardStore],
    *,
    answer_guard: Callable[..., None] | None = None,
    world_owner: Callable[..., str | None] | None = None,
) -> APIRouter:
    """`cards` is one CardStore, or a dependency that finds the world's own; `answer_guard` (a dependency) may
    refuse an answer before the store sees it; `world_owner` (a dependency) names the path world's record owner, so
    an owner reads and answers across the worlds they own (S-06); without it every route stays bound to one world."""
    router = APIRouter()
    get_cards = cards if not isinstance(cards, CardStore) else (lambda: cards)
    guards = [Depends(answer_guard)] if answer_guard is not None else []
    get_owner = world_owner or (lambda: None)

    @router.get("/worlds/{world_id}/cards")
    def list_cards(
        world_id: str,
        principal: Principal = Depends(get_current_principal),
        store: CardStore = Depends(get_cards),
        record_owner: str | None = Depends(get_owner),
    ) -> list[dict]:
        reader = reading_principal(principal, world_id, record_owner=record_owner)
        if reader is None:
            raise HTTPException(status_code=404)  # same as an unknown world
        try:
            return as_read_by(principal, world_id, store.list_for_world(world_id, principal=reader))
        except PermissionError as exc:
            raise HTTPException(status_code=403) from exc

    @router.post("/worlds/{world_id}/cards/{card_id}/answer", dependencies=guards)
    def answer_card(
        world_id: str,
        card_id: str,
        body: _AnswerBody,
        principal: Principal = Depends(get_current_principal),
        from_channels: bool = Depends(get_channels_caller),
        store: CardStore = Depends(get_cards),
        record_owner: str | None = Depends(get_owner),
    ) -> JSONResponse:
        actor = answering_principal(
            principal, world_id, record_owner=record_owner, cards=store, from_channels=from_channels
        )
        if actor is None:
            raise HTTPException(status_code=404)  # same as an unknown world, before any other check
        if body.pin_verified or (not from_channels and body.channel not in _WEB_CHANNELS):
            return JSONResponse(status_code=403, content={"outcome": "rejected", "reason": "channel_not_permitted"})
        if not session_allows(actor, body.channel, from_channels):
            return JSONResponse(status_code=400, content={"outcome": "rejected", "reason": "invalid_channel"})
        try:
            result = store.answer(
                world_id,
                card_id,
                option=body.option,
                channel=body.channel,
                principal=actor,
            )
        except Exception as exc:  # the event write failed; the card stays open and the answer can be sent again
            logger.warning("a card answer could not be written: %s", type(exc).__name__)
            return JSONResponse(status_code=503, content={"outcome": "error", "reason": "event_write_failed"})
        if result.outcome == "answered":
            if actor is not principal:  # BQ-XWORLD-5: an operations record of a cross-world answer, ids only
                logger.info(
                    "cross-world answer: user %s, session world %s, target world %s, card %s, option %s",
                    actor.user_id, principal.world_id, world_id, card_id, body.option,
                )  # fmt: skip
            return JSONResponse(status_code=200, content={"outcome": "answered"})
        return JSONResponse(
            status_code=_STATUS.get(result.reason or "", 400), content={"outcome": "rejected", "reason": result.reason}
        )

    return router
