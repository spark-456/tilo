"""The ids a log line carries, bound with contextvars (so per asyncio task and per thread, never shared)."""

from __future__ import annotations

import contextlib
import contextvars
import os
import re
from collections.abc import Iterator

_ids: contextvars.ContextVar[dict[str, str]] = contextvars.ContextVar("tilo_log_ids", default={})
_TRACE_ID = re.compile(r"[0-9a-fA-F]{32}")


def current() -> dict[str, str]:
    return _ids.get()


@contextlib.contextmanager
def bound(**ids: str | None) -> Iterator[None]:
    """Bind `run_id`, `world_id` and/or `trace` for the block; a None value is left out, not stored."""
    token = _ids.set({**_ids.get(), **{k: v for k, v in ids.items() if v}})
    try:
        yield
    finally:
        _ids.reset(token)


def trace_from_header(value: str | None) -> str | None:
    """`TRACE_ID/SPAN_ID;o=1` (X-Cloud-Trace-Context) to the Cloud Logging trace field, or None if it is not one.
    With `GOOGLE_CLOUD_PROJECT` set the value is `projects/<project>/traces/<id>`, else the bare trace id."""
    trace_id = (value or "").split("/", 1)[0].strip()
    if not _TRACE_ID.fullmatch(trace_id):
        return None
    project = os.environ.get("GOOGLE_CLOUD_PROJECT")
    return f"projects/{project}/traces/{trace_id}" if project else trace_id
