"""Readable validation refusals with separate, input-free field diagnostics."""

from typing import Any, cast

from fastapi import Request
from fastapi.responses import JSONResponse

from tilo_api.people_writes import Refusal


class ValidationRefusal(Refusal):
    def __init__(self, detail: str, errors: list[dict[str, Any]]) -> None:
        super().__init__(422, detail, errors=errors)


def validation_response(_: Request, exc: Exception) -> JSONResponse:
    refusal = cast(ValidationRefusal, exc)
    return JSONResponse(
        status_code=refusal.status_code,
        content={"detail": refusal.detail, **refusal.extra},
        headers=refusal.headers,
    )
