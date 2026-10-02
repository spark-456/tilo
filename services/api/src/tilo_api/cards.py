"""tilo_api.cards -- the API side of cards and batching (FR-HIL-01, FR-HIL-02; PRD 10.1-10.3, 10.6,
9.5, FR-INT-09). Public shapes are pinned in services/api/tests/API_ST3b.md; its "Ambiguities
resolved" section and docs/open-questions.md record the PRD defaults this module applies.

CardStore is a plain, deterministic in-memory store: an injected Clock and EventWriter, no network,
no randomness. A card is validated against contracts/card.schema.json plus the validator rules
CR-01 and CR-02 before it is stored; an invalid card is never shown and never times out. Gate and
consent cards are authorisations: never merged, never delegated to the Director, and never resolved
by a timeout. Who answers comes only from the verified `deps.Principal` (PRD 10.1), never from the
request body; a channel other than web and a PIN flag are accepted only from an authenticated
tilo-channels caller. Deciding whether an answer opens a gate stays with packages/policy.
"""

from __future__ import annotations

import copy
import datetime
import functools
import hashlib
import json
import re
import threading
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

import jsonschema
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict
from referencing import Registry, Resource
from referencing.jsonschema import DRAFT202012

from tilo_api.deps import Principal, get_current_principal
from tilo_api.redaction import _DISTRICT_RE, _safe_districts

CONTRACTS = Path(__file__).resolve().parents[4] / "contracts"

_TS_FMT = "%Y-%m-%dT%H:%M:%S.%fZ"
_ULID_RE = re.compile(r"^[0-7][0-9A-HJKMNP-TV-Z]{25}$")
_USER_RE = re.compile(r"^u_[0-9A-Za-z_]{1,48}$")
_MERGEABLE = ("needs_you", "meeting")
_ROLES = ("owner", "team_lead", "approver")  # any other role (a Viewer included) answers and lists nothing
_CROCKFORD = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"
_WEB_CHANNELS = ("web", "mobile_web")
_STATUS = {"card_not_found": 404, "forbidden": 403}  # AnswerResult.reason -> HTTP status; others are 400


def _alert_id(card_id: str) -> str:
    """A ulid of its own for the timeout nudge, derived from the card id so a retry reuses it and
    it never collides with an alert the harness raised under the card's id."""
    n = int.from_bytes(hashlib.sha256(f"{card_id}:timeout".encode()).digest(), "big") % 32**25
    chars = []
    for _ in range(25):
        n, r = divmod(n, 32)
        chars.append(_CROCKFORD[r])
    return "0" + "".join(chars)


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
    unknown) and "owner_only". The writer must not default a part without a vis to "all"."""


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

    @property
    def kind(self) -> str:
        return self.card["kind"]


def _can_see(p: Principal, world_id: str, owner: str | None, r: _Record) -> bool:
    """PRD 10.1 scope: the owner sees every card, a Team Lead their districts' cards, an Approver
    only the cards assigned to them; a Viewer none."""
    if p.world_id != world_id or owner is None or _USER_RE.match(p.user_id) is None:
        return False
    if p.role == "owner":
        return p.user_id == owner
    if p.role == "team_lead":
        return r.district is not None and r.district in _safe_districts(p.districts)
    return p.role == "approver" and r.assignee == p.user_id


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
    ) -> None:
        self._clock = clock
        self._writer = writer
        self._world_owners = dict(world_owners or {})
        self._merge_window_s = merge_window_s
        self._records: dict[str, dict[str, _Record]] = {}
        self._seen: dict[tuple[str, str], tuple[str, SubmitResult]] = {}
        self._groups: dict[tuple, _Group] = {}
        self._pending: dict[tuple[str, str], _Record] = {}  # open and not yet nudged: tick's work set
        self._lock = threading.RLock()  # guards every state change; a write happens outside it

    # -- submit ---------------------------------------------------------

    def submit(
        self,
        card: dict,
        *,
        outbox_id: str | None = None,
        district: str | None = None,
        assignee: str | None = None,
    ) -> SubmitResult:
        """`outbox_id` (gates only), `district` (a Team Lead sees only their districts' cards; none
        means owner-only) and `assignee` (the Approver the owner assigned) are companion data the
        harness already holds; a model never supplies them. Re-submitting identical content returns
        the first result and changes nothing; a different card under a used id is rejected."""
        with self._lock:
            return self._submit(card, outbox_id, district, assignee)

    def _submit(self, card: dict, outbox_id: str | None, district: str | None, assignee: str | None) -> SubmitResult:
        errors = _card_errors(card)
        if not errors:
            errors = self._companion_errors(card["kind"], outbox_id, district, assignee)
        if errors:
            return SubmitResult("rejected", None, tuple(errors))

        world_id, card_id, kind = card["world_id"], card["id"], card["kind"]
        digest = hashlib.sha256(json.dumps([card, outbox_id, district, assignee], sort_keys=True).encode()).hexdigest()
        seen = self._seen.get((world_id, card_id))
        if seen is not None:
            return seen[1] if seen[0] == digest else SubmitResult("rejected", None, ("card id already used",))

        created = _parse_ts(card["created_at"])
        key = (world_id, kind, card["header"]["building"], district, assignee)
        group = self._groups.get(key) if kind in _MERGEABLE else None
        merged = (
            group is not None
            and not group.closed
            and abs((created - group.anchor).total_seconds()) <= self._merge_window_s
        )
        if not merged:
            group = _Group(card_id, created)
            if kind in _MERGEABLE:
                self._groups[key] = group
        assert group is not None
        record = _Record(world_id, copy.deepcopy(card), outbox_id, district, assignee, _deadline(card), group)
        group.members.append(record)
        self._records.setdefault(world_id, {})[card_id] = record
        self._pending[(world_id, card_id)] = record
        result = SubmitResult("merged" if merged else "accepted", group.primary_id, ())
        self._seen[(world_id, card_id)] = (digest, result)
        return result

    @staticmethod
    def _companion_errors(kind: str, outbox_id: str | None, district: str | None, assignee: str | None) -> list[str]:
        errors = []
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
            member.status = "resolved"
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
        if severity:
            part["severity"] = severity
        return part

    # -- reads ------------------------------------------------------------

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
        with self._lock:
            for record in self._records.get(world_id, {}).values():
                if (
                    record.status == "open"
                    and id(record.group) not in shown
                    and _can_see(principal, world_id, owner, record)
                ):
                    shown[id(record.group)] = record
            return sorted((copy.deepcopy(r.card) for r in shown.values()), key=lambda c: c["created_at"])

    # -- answer -------------------------------------------------------------

    def answer(
        self,
        world_id: str,
        card_id: str,
        *,
        option: str,
        channel: str,
        principal: Principal,
        pin_verified: bool = False,
    ) -> AnswerResult:
        """Rejections write nothing and leave the card open. A card outside the principal's scope
        is "card_not_found" (no existence oracle); a Viewer or a role that may not answer that
        kind is "forbidden"."""
        with self._lock:
            record = self._records.get(world_id, {}).get(card_id)
            if principal.role not in _ROLES:
                return AnswerResult("rejected", "forbidden", ())
            if record is None or not _can_see(principal, world_id, self._world_owners.get(world_id), record):
                return AnswerResult("rejected", "card_not_found", ())
            if not _can_answer(principal, record):
                return AnswerResult("rejected", "forbidden", ())
            if record.status != "open" or record.group.resolving:
                return AnswerResult("rejected", "already_resolved", ())

            card = record.card
            if option not in {o["id"] for o in card["options"]}:
                return AnswerResult("rejected", "invalid_option", ())
            if channel not in card["answer_channels"]:
                return AnswerResult("rejected", "invalid_channel", ())
            tier_t3 = record.kind == "gate" and card["gate"]["risk_tier"] == "T3"
            if tier_t3 and channel == "whatsapp" and not pin_verified:
                return AnswerResult("rejected", "pin_required", ())

            authz = {"by": "person", "ref": principal.user_id, "at": self._clock.now()}
            if record.kind == "gate":
                # CR-07: only approve opens a gate and writes approval.resolved; edit and hold write nothing.
                data = {"gate_id": card["gate"]["id"], "card_id": card_id, "outbox_id": record.outbox_id}
                data |= {"option": option, "channel": channel, "pin_verified": pin_verified}
                part = self._part(record, "approval.resolved", data, authz=authz) if option == "approve" else None
            elif record.kind == "consent":
                # CR-13: only connect grants the connection; hold leaves it waiting.
                data = {"connector": card["consent"]["connector"], "card_id": card_id}
                data["scopes"] = card["consent"]["scopes"]
                part = self._part(record, "connection.consented", data, authz=authz) if option == "connect" else None
            else:
                by = "team_lead" if principal.role == "team_lead" else "person"
                part = self._part(record, "question.answered", {"answered_by": by})
            if part is None:
                return AnswerResult("answered", None, ())
            record.group.resolving = True  # exactly one resolution per card: later answers and tick see this
        self._write_then_close(record.group, part)
        return AnswerResult("answered", None, (part,))

    def _write_then_close(self, group: _Group, part: dict) -> None:
        try:
            self._writer.write(part)  # outside the lock; a failed write leaves the card open
        except BaseException:
            with self._lock:
                group.resolving = False
            raise
        with self._lock:
            self._resolve_group(group)

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
        try:
            for key, record, held in claimed:
                if held:
                    data = {"alert_id": _alert_id(key[1]), "card_id": key[1]}
                    self._writer.write(self._part(record, "alert.raised", data, severity="nudge"))
                else:
                    part = self._part(record, "question.answered", {"answered_by": "default"}, severity="nudge")
                    self._writer.write(part)
                    with self._lock:
                        self._resolve_group(record.group)
                results.append(TimeoutResult(card_id=key[1], kind=record.kind, held=held))
        except BaseException:
            with self._lock:  # unwritten claims go back to the work set; the next tick retries them
                for key, record, held in claimed[len(results) :]:
                    if held:
                        self._pending[key] = record
                    else:
                        record.group.resolving = False
            raise
        return results


class _AnswerBody(BaseModel):
    """No identity field: who answers is the verified principal. `channel` and `pin_verified` are
    honoured only from an authenticated tilo-channels caller."""

    model_config = ConfigDict(extra="forbid")

    option: str
    channel: str = "web"
    pin_verified: bool = False


def get_channels_caller() -> bool:
    """True only when the request was authenticated as tilo-channels, acting for the principal
    (service-to-service auth lands with sign-in, PRD 15.3). Until then no caller is, so every
    request is a web-session answer."""
    return False


def build_router(
    cards: CardStore | Callable[..., CardStore], *, answer_guard: Callable[..., None] | None = None
) -> APIRouter:
    """`cards` is one CardStore, or a dependency that finds the world's own; `answer_guard` (a dependency) may
    refuse an answer before the store sees it."""
    router = APIRouter()
    get_cards = cards if not isinstance(cards, CardStore) else (lambda: cards)
    guards = [Depends(answer_guard)] if answer_guard is not None else []

    @router.get("/worlds/{world_id}/cards")
    def list_cards(
        world_id: str,
        principal: Principal = Depends(get_current_principal),
        store: CardStore = Depends(get_cards),
    ) -> list[dict]:
        if principal.world_id != world_id:
            raise HTTPException(status_code=404)  # same as an unknown world
        try:
            return store.list_for_world(world_id, principal=principal)
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
    ) -> JSONResponse:
        if principal.world_id != world_id:
            raise HTTPException(status_code=404)
        if not from_channels and (body.channel not in _WEB_CHANNELS or body.pin_verified):
            return JSONResponse(status_code=403, content={"outcome": "rejected", "reason": "channel_not_permitted"})
        result = store.answer(
            world_id,
            card_id,
            option=body.option,
            channel=body.channel,
            principal=principal,
            pin_verified=body.pin_verified,
        )
        if result.outcome == "answered":
            return JSONResponse(status_code=200, content={"outcome": "answered"})
        return JSONResponse(
            status_code=_STATUS.get(result.reason or "", 400), content={"outcome": "rejected", "reason": result.reason}
        )

    return router
