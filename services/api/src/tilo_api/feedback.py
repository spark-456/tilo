"""SEC-16 beta-allowance feedback: `POST /v1/feedback` (user request, 8 Oct 2026, BQ-FEEDBACK-1; spec in
services/api/tests/API_SPEND_FEEDBACK.md). A person who has used their live-model allowance can leave honest feedback.

The uid is always the verified principal's. The body is plain text, cleaned (control and invisible format characters
removed), 1 to 2000 characters, 8000 raw at most (checked before any cleaning). Each uid may send 5 an hour and 20 in a
lifetime, decided atomically by the store. It is not a model call: no router, no ledger. The text is never logged and
there is no read route (an owner or admin read path is deferred). Only `application/json` is read (415)."""

from __future__ import annotations

import math
import threading
import unicodedata
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Annotated, Any, Literal, Protocol

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field, StrictStr, ValidationError, field_validator
from starlette.concurrency import run_in_threadpool

from tilo_api import deps
from tilo_api.validation_copy import ValidationRefusal

CONTEXT = "lifetime_cap"
MAX_CHARS = 2000  # after cleaning
MAX_RAW_CHARS = 8000  # before any cleaning: a huge field costs no normalising work
MAX_BODY_BYTES = 65536  # a body over this is a 413 before it is read (8000 characters escaped is 48000 bytes)
PER_HOUR = 5
LIFETIME_MAX = 20
HOUR_S = 3600
_KEEP = {"\n", "\t"}
_BLANK_LOOKING = {"ㅤ", "ᅟ", "ᅠ", "ﾠ"}  # Hangul fillers: they render as nothing

router = APIRouter()
Principal = Annotated[deps.Principal, Depends(deps.get_current_principal)]


@dataclass(frozen=True)
class AddResult:
    status: Literal["stored", "hourly_limit", "lifetime_limit"]
    retry_after_s: int | None = None


class FeedbackStore(Protocol):
    def add(
        self, *, uid: str, text: str, context: str, created_at: str, hourly_limit: int, lifetime_limit: int
    ) -> AddResult: ...


def clean(raw: str) -> str:
    """Removes control characters (not newline or tab), format characters and blank-looking fillers, then trims."""
    kept = [c for c in raw if c in _KEEP or (c not in _BLANK_LOOKING and unicodedata.category(c) not in ("Cc", "Cf"))]
    return "".join(kept).strip()


class FeedbackIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    text: StrictStr = Field(max_length=MAX_RAW_CHARS)
    context: Literal["lifetime_cap"]

    @field_validator("text")
    @classmethod
    def _cleaned(cls, value: str) -> str:
        cleaned = clean(value)
        if not 1 <= len(cleaned) <= MAX_CHARS or not any(_visible(c) for c in cleaned):
            raise ValueError(f"send between 1 and {MAX_CHARS} visible characters")
        return cleaned


def _visible(char: str) -> bool:
    """A character a person can see: not a mark, separator, unassigned, private-use or blank-looking symbol."""
    return char not in _BLANK_LOOKING and unicodedata.category(char)[0] not in ("M", "Z", "C") and char != "⠀"


class FeedbackBusy(Exception):
    """The store could not settle the write after its retries: 503 `busy`, nothing stored."""


async def _body(request: Request) -> FeedbackIn:
    """Strict JSON only (415), refused over MAX_BODY_BYTES before it is read (413), parsed by pydantic from the bytes,
    and a 422 sentence with separate field locations: never the input (it is the person's text, and never logged)."""
    if request.headers.get("content-type", "").split(";")[0].strip().lower() != "application/json":
        raise HTTPException(status_code=415, detail="Send application/json.")
    declared = request.headers.get("content-length", "")
    if declared.isascii() and declared.isdigit() and int(declared) > MAX_BODY_BYTES:
        raise HTTPException(status_code=413, detail="body_too_large")
    chunks: list[bytes] = []
    size = 0
    async for chunk in request.stream():
        size += len(chunk)
        if size > MAX_BODY_BYTES:
            raise HTTPException(status_code=413, detail="body_too_large")
        chunks.append(chunk)
    try:
        return FeedbackIn.model_validate_json(b"".join(chunks))
    except ValidationError as exc:
        locs = [[*e["loc"][:-1], "?"] if e["type"] == "extra_forbidden" else list(e["loc"]) for e in exc.errors()]
        raise ValidationRefusal(
            "Check your feedback and send between 1 and 2000 visible characters.", [{"loc": loc} for loc in locs]
        ) from None


def seconds_until_free(oldest_created_at: str, now: str) -> int:
    """Whole seconds until a record created at `oldest_created_at` leaves the hour, between 1 and 3600."""
    left = (parse(oldest_created_at) - parse(now)).total_seconds() + HOUR_S
    return max(1, min(HOUR_S, math.ceil(left)))


def parse(stamp: str) -> datetime:
    return datetime.fromisoformat(stamp).astimezone(UTC)


def in_window(created_at: str, now: str) -> bool:
    return (parse(now) - parse(created_at)).total_seconds() < HOUR_S


def decide(created: list[str], now: str, hourly_limit: int, lifetime_limit: int) -> AddResult:
    """The shared rule over one uid's `created_at` stamps: lifetime first, then the rolling hour."""
    if len(created) >= lifetime_limit:
        return AddResult("lifetime_limit")
    recent = [c for c in created if in_window(c, now)]
    if len(recent) >= hourly_limit:
        return AddResult("hourly_limit", seconds_until_free(min(recent, key=parse), now))
    return AddResult("stored")


class InMemoryFeedbackStore:
    """Dev mode and tests: one lock makes the check and the write atomic."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._records: list[dict[str, Any]] = []

    def add(
        self, *, uid: str, text: str, context: str, created_at: str, hourly_limit: int, lifetime_limit: int
    ) -> AddResult:
        with self._lock:
            mine = [r["created_at"] for r in self._records if r["uid"] == uid]
            outcome = decide(mine, created_at, hourly_limit, lifetime_limit)
            if outcome.status == "stored":
                self._records.append({"uid": uid, "text": text, "created_at": created_at, "context": context})
            return outcome

    def records(self) -> list[dict[str, Any]]:
        with self._lock:
            return [dict(r) for r in self._records]


@router.post("/v1/feedback", status_code=201, response_model=None)
async def post_feedback(
    principal: Principal,
    store: Annotated[FeedbackStore, Depends(deps.get_feedback_store)],
    clock: Annotated[Any, Depends(deps.get_clock)],
    request: Request,
) -> dict[str, bool] | JSONResponse:
    if principal.demo_session:  # an anonymous demo session is replay-only and never reaches the allowance
        return JSONResponse(
            status_code=403,
            content={"detail": "Sign in with Google to send feedback.", "code": "full_session_required"},
        )
    body = await _body(request)
    try:
        outcome = await run_in_threadpool(
            lambda: store.add(
                uid=principal.user_id,
                text=body.text,
                context=body.context,
                created_at=clock(),
                hourly_limit=PER_HOUR,
                lifetime_limit=LIFETIME_MAX,
            )
        )
    except FeedbackBusy:
        return JSONResponse(status_code=503, content={"detail": "busy", "code": "busy"}, headers={"Retry-After": "2"})
    if outcome.status == "hourly_limit":
        return JSONResponse(
            status_code=429,
            content={"detail": "Too much feedback this hour. Please try again later.", "code": "rate_limited"},
            headers={"Retry-After": str(outcome.retry_after_s)},
        )
    if outcome.status == "lifetime_limit":
        return JSONResponse(
            status_code=429,
            content={
                "detail": "Thank you, you have sent all the feedback we can take.",
                "code": "feedback_limit_reached",
            },
        )
    return {"received": True}
