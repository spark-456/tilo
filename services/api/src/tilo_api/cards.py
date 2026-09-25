"""tilo_api.cards — the API side of cards and batching (FR-HIL-01, FR-HIL-02; PRD 10.2, 10.3,
10.6, 9.5, FR-INT-09). Public shapes are pinned in services/api/tests/API_ST3b.md; that file's
"Ambiguities resolved" section records the PRD defaults this module applies.

CardStore is a plain, deterministic in-memory store: an injected Clock and EventWriter, no
network, no randomness. Every card is validated against contracts/card.schema.json (with
contracts/common.schema.json resolved) before it is stored -- an invalid card is never shown and
never times out. Gate and consent cards are authorisations and are never merged, never delegated
to the Director and never time out to their "open" option; only a person's answer can resolve
them. Deciding *who* may open a gate (PI-02) is packages/policy's job, not this module's: answer()
only checks that the given option and channel are ones the card itself offers.
"""

from __future__ import annotations

import datetime
import functools
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

import jsonschema
from fastapi import APIRouter, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from referencing import Registry, Resource
from referencing.jsonschema import DRAFT202012

CONTRACTS = Path(__file__).resolve().parents[4] / "contracts"

_TS_FMT = "%Y-%m-%dT%H:%M:%S.%fZ"
_ULID_RE = re.compile(r"^[0-7][0-9A-HJKMNP-TV-Z]{25}$")


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


def _card_errors(card: Any) -> list[str]:
    """jsonschema validation error messages for `card` against card.schema.json; empty when
    valid. A rejected card is never stored and never times out."""
    schema = _card_schema()
    cls = jsonschema.validators.validator_for(schema, default=jsonschema.Draft202012Validator)
    validator = cls(schema, registry=_registry())
    return [e.message for e in validator.iter_errors(card)]


class Clock(Protocol):
    def now(self) -> str: ...  # RFC 3339, common.schema.json#/$defs/timestamp


class EventWriter(Protocol):
    def write(self, part: dict) -> None: ...

    """The API never stamps id/seq/ts/run_id (PI-18) -- it hands the harness-owned writer an
    unstamped part: {"type": str, "data": dict, "authz": dict | None, "severity"?: str}."""


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
class _Record:
    """One stored card and its group anchor. A merged card never gets its own record: it is only
    an alias onto the group's original (CardStore._alias)."""

    card: dict[str, Any]
    outbox_id: str | None
    anchor_created_at: str
    status: str = "open"  # "open" | "resolved" -- a held gate/consent stays "open"
    nudged: bool = False

    @property
    def kind(self) -> str:
        return self.card["kind"]

    @property
    def building(self) -> str:
        return self.card["header"]["building"]

    @property
    def timeout(self) -> int:
        return self.card["timeout"]


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
        self._alias: dict[str, dict[str, str]] = {}

    # -- submit ---------------------------------------------------------

    def submit(self, card: dict, *, outbox_id: str | None = None) -> SubmitResult:
        errors = _card_errors(card)
        if errors:
            return SubmitResult("rejected", None, tuple(errors))

        kind = card["kind"]
        if kind == "gate":
            if not outbox_id or not _ULID_RE.match(outbox_id):
                return SubmitResult("rejected", None, ("outbox_id is required and must be a ulid for a gate card",))
        elif outbox_id is not None:
            return SubmitResult("rejected", None, ("outbox_id must not be given for a non-gate card",))

        world_id = card["world_id"]
        card_id = card["id"]

        if kind in ("gate", "consent"):
            self._store_new(world_id, card_id, card, outbox_id)
            return SubmitResult("accepted", card_id, ())

        target = self._find_merge_target(world_id, card)
        if target is not None:
            self._alias.setdefault(world_id, {})[card_id] = target.card["id"]
            return SubmitResult("merged", target.card["id"], ())

        self._store_new(world_id, card_id, card, outbox_id)
        return SubmitResult("accepted", card_id, ())

    def _store_new(self, world_id: str, card_id: str, card: dict, outbox_id: str | None) -> None:
        record = _Record(card=card, outbox_id=outbox_id, anchor_created_at=card["created_at"])
        self._records.setdefault(world_id, {})[card_id] = record
        self._alias.setdefault(world_id, {})[card_id] = card_id

    def _find_merge_target(self, world_id: str, card: dict) -> _Record | None:
        """The group anchor is the *first* card's created_at (API_ST3b.md ambiguity 3); a new
        needs_you/meeting card merges into the first open record of the same world, kind and
        header.building (approximating "district") within merge_window_s of that anchor."""
        created_at = _parse_ts(card["created_at"])
        for record in self._records.get(world_id, {}).values():
            if record.status != "open" or record.kind != card["kind"] or record.building != card["header"]["building"]:
                continue
            delta = abs((created_at - _parse_ts(record.anchor_created_at)).total_seconds())
            if delta <= self._merge_window_s:
                return record
        return None

    # -- reads ------------------------------------------------------------

    def get(self, world_id: str, card_id: str) -> dict | None:
        primary = self._alias.get(world_id, {}).get(card_id)
        if primary is None:
            return None
        record = self._records.get(world_id, {}).get(primary)
        return record.card if record else None

    def list_for_world(self, world_id: str, *, as_user: str) -> list[dict]:
        owner = self._world_owners.get(world_id)
        if owner is None or owner != as_user:
            raise PermissionError(f"{as_user} is not the owner of world {world_id}")
        records = self._records.get(world_id, {}).values()
        return sorted((r.card for r in records if r.status == "open"), key=lambda c: c["created_at"])

    # -- answer -------------------------------------------------------------

    def answer(
        self,
        world_id: str,
        card_id: str,
        *,
        option: str,
        channel: str,
        actor: str,
        pin_verified: bool = False,
    ) -> AnswerResult:
        primary = self._alias.get(world_id, {}).get(card_id)
        if primary is None:
            return AnswerResult("rejected", "card_not_found", ())
        record = self._records[world_id][primary]
        if record.status != "open":
            return AnswerResult("rejected", "already_resolved", ())

        card = record.card
        if option not in {o["id"] for o in card["options"]}:
            return AnswerResult("rejected", "invalid_option", ())
        if channel not in card["answer_channels"]:
            return AnswerResult("rejected", "invalid_channel", ())
        if record.kind == "gate" and card["gate"]["risk_tier"] == "T3" and channel == "whatsapp" and not pin_verified:
            return AnswerResult("rejected", "pin_required", ())

        if record.kind == "gate":
            part: dict[str, Any] = {
                "type": "approval.resolved",
                "data": {
                    "gate_id": card["gate"]["id"],
                    "card_id": card["id"],
                    "outbox_id": record.outbox_id,
                    "option": option,
                    "channel": channel,
                    "pin_verified": pin_verified,
                },
                "authz": {"by": "person", "ref": actor, "at": self._clock.now()},
            }
            self._writer.write(part)
            if option == "approve":
                record.status = "resolved"
            return AnswerResult("answered", None, (part,))

        if record.kind == "consent":
            # CR-13: only "connect" grants the connection. connection.consented is
            # FR-HIL-08/token-broker territory -- out of scope here (API_ST3b.md ambiguity 7).
            if option == "connect":
                record.status = "resolved"
            return AnswerResult("answered", None, ())

        part = {"type": "question.answered", "data": {"answered_by": "person"}, "authz": None}
        self._writer.write(part)
        record.status = "resolved"
        return AnswerResult("answered", None, (part,))

    # -- timeouts -------------------------------------------------------------

    def tick(self) -> list[TimeoutResult]:
        now = _parse_ts(self._clock.now())
        results: list[TimeoutResult] = []
        for records in self._records.values():
            for record in records.values():
                if record.status != "open" or record.nudged:
                    continue
                deadline = _parse_ts(record.anchor_created_at) + datetime.timedelta(seconds=record.timeout)
                if now < deadline:
                    continue

                self._writer.write(
                    {
                        "type": "question.answered",
                        "data": {"answered_by": "default"},
                        "authz": None,
                        "severity": "nudge",
                    }
                )
                record.nudged = True
                held = record.kind in ("gate", "consent")
                if not held:
                    record.status = "resolved"
                results.append(TimeoutResult(card_id=record.card["id"], kind=record.kind, held=held))
        return results


class _AnswerBody(BaseModel):
    option: str
    channel: str
    actor: str
    pin_verified: bool = False


def build_router(store: CardStore) -> APIRouter:
    router = APIRouter()

    @router.get("/worlds/{world_id}/cards")
    def list_cards(world_id: str, as_user: str) -> list[dict]:
        try:
            return store.list_for_world(world_id, as_user=as_user)
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc

    @router.post("/worlds/{world_id}/cards/{card_id}/answer")
    def answer_card(world_id: str, card_id: str, body: _AnswerBody) -> JSONResponse:
        result = store.answer(
            world_id,
            card_id,
            option=body.option,
            channel=body.channel,
            actor=body.actor,
            pin_verified=body.pin_verified,
        )
        if result.outcome == "answered":
            return JSONResponse(status_code=200, content={"outcome": "answered"})
        status_code = 404 if result.reason == "card_not_found" else 400
        return JSONResponse(status_code=status_code, content={"outcome": "rejected", "reason": result.reason})

    return router
