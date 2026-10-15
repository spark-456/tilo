"""Class-only failure logs. Never stringify exceptions or arbitrary local values."""

from __future__ import annotations

import logging
from collections.abc import Mapping
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Any

_ids: ContextVar[dict[str, str]] = ContextVar("failure_ids", default={})


@contextmanager
def failure_context(**ids: str | None):
    token = _ids.set({**_ids.get(), **{k: v for k, v in ids.items() if v}})
    try:
        yield
    finally:
        _ids.reset(token)


def log_caught(error: BaseException, module: str, context: Mapping[str, Any]) -> None:
    """Only known identifier fields are read; prompts, responses and exception text stay private.

    Context inherits across asyncio tasks and to_thread. Local ids cover routes and recovery
    outside a running task. A dash means this operation has no such identifier yet.
    """
    ids = dict(_ids.get())
    for name in ("self", "writer", "scope", "loop", "context", "task", "record"):
        obj = context.get(name)
        fields = vars(obj) if hasattr(obj, "__dict__") else {}
        for key in ("run_id", "unit_id", "world_id"):
            value = fields.get(key)
            if isinstance(value, str):
                ids[key] = value
    unit = context.get("unit")
    if isinstance(unit, Mapping) and isinstance(unit.get("id"), str):
        ids["unit_id"] = unit["id"]
    for key in ("run_id", "unit_id", "world_id"):
        value = context.get(key)
        if isinstance(value, str):
            ids[key] = value
    where = ""
    if (frame := error.__traceback__) is not None:  # RESULT-LIVE: the catch module and the raising code line
        while frame.tb_next is not None:  # (Cloud Run prints no logger name); file and line only, never text
            frame = frame.tb_next
        raised = frame.tb_frame.f_code.co_filename.replace("\\", "/").rsplit("/", 1)[-1]
        where = f" in={module} raised={raised}:{frame.tb_lineno}"
    logging.getLogger(module).error(
        "caught error run=%s unit=%s world=%s exception=%s%s",
        ids.get("run_id", "-"),
        ids.get("unit_id", "-"),
        ids.get("world_id", "-"),
        type(error).__name__,
        where,
    )
