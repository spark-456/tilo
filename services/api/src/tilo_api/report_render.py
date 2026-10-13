"""Bound the default writer's in-process renderer just like the authenticated render door."""

import asyncio
import threading

from starlette.concurrency import run_in_threadpool
from tilo_harness.deliverable import MAX_PDF, DeliverableRefused, parse_spec
from tilo_harness.outputs import RenderedPdf
from tilo_render.pdf import render_pdf
from tilo_render.spec import RequestDeliverableSpec

_SLOTS = threading.BoundedSemaphore(2)
RENDER_TIMEOUT_S = 30.0


async def render_report(reply: str) -> RenderedPdf:
    try:
        spec = RequestDeliverableSpec.model_validate(parse_spec(reply).model_dump())
    except Exception:
        raise DeliverableRefused("invalid_spec") from None
    if not _SLOTS.acquire(blocking=False):
        raise DeliverableRefused("render_failed")
    handover = threading.Lock()
    claimed, abandoned = False, False

    def worker() -> bytes:
        nonlocal claimed
        with handover:
            if abandoned:
                return b""
            claimed = True
        try:
            return render_pdf(spec)
        finally:
            _SLOTS.release()

    try:
        content = await asyncio.wait_for(run_in_threadpool(worker), timeout=RENDER_TIMEOUT_S)
    except Exception:
        raise DeliverableRefused("render_failed") from None
    finally:
        with handover:
            abandoned = True
            if not claimed:
                _SLOTS.release()
    if not content.startswith(b"%PDF") or len(content) > MAX_PDF:
        raise DeliverableRefused("too_large")
    return RenderedPdf(media_type="application/pdf", content=content, spec_text=spec.model_dump_json())
