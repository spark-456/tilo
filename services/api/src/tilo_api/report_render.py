"""Bound the default writer's in-process renderer just like the authenticated render door."""

import asyncio
import os
import threading
from typing import Literal, cast

from starlette.concurrency import run_in_threadpool
from tilo_harness.deliverable import MAX_PDF, DeliverableRefused, parse_spec
from tilo_harness.outputs import RenderedOffice, RenderedPdf
from tilo_render.docx import render_docx
from tilo_render.pdf import render_pdf
from tilo_render.pptx import render_pptx
from tilo_render.spec import RequestDeliverableSpec

from tilo_api.render_rpc import MIME, RenderRpc

_SLOTS = threading.BoundedSemaphore(2)
RENDER_TIMEOUT_S = 30.0


async def render_report(reply: str, *, fmt: str = "pdf") -> RenderedPdf | RenderedOffice:
    if fmt not in ("pdf", "pptx", "docx"):
        raise DeliverableRefused("render_failed")
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
            url = os.environ.get("TILO_RENDER_URL", "")
            if fmt in ("pptx", "docx") and url:
                return RenderRpc(url).render(spec, cast(Literal["pptx", "docx"], fmt))
            # DOCS-OUT: with no render door configured, the same library the door runs renders in process.
            return {"pdf": render_pdf, "docx": render_docx, "pptx": render_pptx}[fmt](spec)
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
    if fmt in ("pptx", "docx"):
        return RenderedOffice(
            media_type=MIME[fmt],
            content=content,
            spec_text=spec.model_dump_json(),
        )
    if not content.startswith(b"%PDF") or len(content) > MAX_PDF:
        raise DeliverableRefused("too_large")
    return RenderedPdf(media_type="application/pdf", content=content, spec_text=spec.model_dump_json())
