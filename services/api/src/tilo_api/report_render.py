"""Bound the default writer's in-process renderer just like the authenticated render door."""

import asyncio
import json
import os
import threading
from collections.abc import Callable
from typing import Literal, cast

from starlette.concurrency import run_in_threadpool
from tilo_harness.deliverable import MAX_PDF, DeliverableRefused, parse_fill, parse_spec
from tilo_harness.outputs import RenderedOffice, RenderedPdf
from tilo_render.docx import render_docx
from tilo_render.pdf import render_pdf
from tilo_render.pptx import render_pptx
from tilo_render.spec import DeliverableSpec, RequestDeliverableSpec
from tilo_render.xlsx import fill_workbook, render_xlsx

from tilo_api.render_rpc import MIME, RenderRpc

_SLOTS = threading.BoundedSemaphore(2)
RENDER_TIMEOUT_S = 30.0
OFFICE_MIME = {**MIME, "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"}


def _render(spec: DeliverableSpec, fmt: str) -> bytes:
    url = os.environ.get("TILO_RENDER_URL", "")
    if fmt in ("pptx", "docx") and url:
        return RenderRpc(url).render(cast(RequestDeliverableSpec, spec), cast(Literal["pptx", "docx"], fmt))
    # DOCS-OUT: with no render door configured, the same library the door runs renders in process.
    return {"pdf": render_pdf, "docx": render_docx, "pptx": render_pptx, "xlsx": render_xlsx}[fmt](spec)


def _plan(reply: str, fmt: str, template: bytes | None) -> tuple[Callable[[], bytes], str]:
    """The validated reply as the work to do and the text the file says (for the redactor)."""
    if fmt == "xlsx" and template is not None:  # DOCS-OUT A4: the reply is cells for the person's own workbook
        fills = parse_fill(reply)
        return (lambda: fill_workbook(template, fills)), json.dumps({"cells": [f.model_dump() for f in fills]})
    # A workbook is made in process and has its own cell cap, so it takes the full spec, not the door's 1200 cells.
    spec = (DeliverableSpec if fmt == "xlsx" else RequestDeliverableSpec).model_validate(parse_spec(reply).model_dump())
    return (lambda: _render(spec, fmt)), spec.model_dump_json()


async def render_report(reply: str, *, fmt: str = "pdf", template: bytes | None = None) -> RenderedPdf | RenderedOffice:
    """The writer's reply as the file for `fmt`; with an uploaded workbook as `template` it is the cells to fill."""
    if fmt not in ("pdf", "pptx", "docx", "xlsx"):
        raise DeliverableRefused("render_failed")
    try:
        build, spec_text = _plan(reply, fmt, template)
    except DeliverableRefused:
        raise  # too_large remains a hard refusal; do not relabel it as a repairable specification
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
            return build()
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
    if fmt in ("pptx", "docx", "xlsx"):
        return RenderedOffice(media_type=OFFICE_MIME[fmt], content=content, spec_text=spec_text)
    if not content.startswith(b"%PDF") or len(content) > MAX_PDF:
        raise DeliverableRefused("too_large")
    return RenderedPdf(media_type="application/pdf", content=content, spec_text=spec_text)
