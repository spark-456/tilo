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
from pydantic import BaseModel, ConfigDict, Field, StrictStr, field_validator

from tilo_api import deps

CONTEXT = "lifetime_cap"
MAX_CHARS = 2000  # after cleaning
MAX_RAW_CHARS = 8000  # before any cleaning: a huge field costs no normalising work
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
        if not 1 <= len(cleaned) <= MAX_CHARS:
            raise ValueError(f"send between 1 and {MAX_CHARS} characters")
        return cleaned


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


def _json_only(request: Request) -> None:
    if request.headers.get("content-type", "").split(";")[0].strip().lower() != "application/json":
        raise HTTPException(status_code=415, detail="Send application/json.")


@router.post("/v1/feedback", status_code=201, dependencies=[Depends(_json_only)], response_model=None)
def post_feedback(
    body: FeedbackIn,
    principal: Principal,
    store: Annotated[FeedbackStore, Depends(deps.get_feedback_store)],
    clock: Annotated[Any, Depends(deps.get_clock)],
) -> dict[str, bool] | JSONResponse:
    outcome = store.add(
        uid=principal.user_id,
        text=body.text,
        context=body.context,
        created_at=clock(),
        hourly_limit=PER_HOUR,
        lifetime_limit=LIFETIME_MAX,
    )
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
