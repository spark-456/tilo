"""LW-11 regressions: queued workers own no slot after cancellation; render work counts text."""

import asyncio
import time
from typing import Any

import httpx
import pytest
from pydantic import ValidationError
from tilo_render import app as render_app
from tilo_render.pdf import render_pdf
from tilo_render.pptx import render_pptx
from tilo_render.spec import RequestDeliverableSpec

SPEC = {"title": "Report", "date": "2026-10-11", "sections": []}
AUTH = {"Authorization": "Bearer test-token"}


@pytest.mark.parametrize("cancel", [False, True])
def test_LW_11_timeout_or_cancel_before_worker_starts_returns_slot(monkeypatch, cancel: bool) -> None:
    real_pool = render_app.run_in_threadpool
    renders: list[str] = []

    async def scenario() -> None:
        queued = asyncio.Event()
        stall = True

        async def pool(func, *args, **kwargs):
            if func.__name__ == "_run_worker" and stall:
                queued.set()
                await asyncio.Event().wait()
            return await real_pool(func, *args, **kwargs)

        monkeypatch.setattr(render_app, "run_in_threadpool", pool)
        app = render_app.create_app(
            audience="render",
            allowed_callers=("worker",),
            oidc_verifier=lambda _token, _aud: {
                "iss": "accounts.google.com",
                "aud": "render",
                "email": "worker",
                "email_verified": True,
            },
            renderer=lambda _spec, fmt: renders.append(fmt) or b"%PDF-1.4\n%%EOF\n",
            max_concurrency=1,
            render_timeout=0.05,
        )
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://render.test") as client:
            first = asyncio.create_task(client.post("/render", json={"format": "pdf", "spec": SPEC}, headers=AUTH))
            await asyncio.wait_for(queued.wait(), 2)
            if cancel:
                first.cancel()
                with pytest.raises(asyncio.CancelledError):
                    await first
            else:
                assert (await first).status_code == 504
            assert not renders
            stall = False
            assert (await client.post("/render", json={"format": "pdf", "spec": SPEC}, headers=AUTH)).status_code == 200
            assert renders == ["pdf"]

    asyncio.run(scenario())


@pytest.mark.parametrize("kind", ["paragraph", "bullets", "cell", "cell_chars", "repeated_chars", "metadata"])
def test_LW_11_refuses_text_amplification_before_render(kind: str) -> None:
    raw: dict[str, Any] = dict(SPEC)
    if kind == "paragraph":
        raw["sections"] = [{"heading": "Body", "blocks": [{"type": "paragraph", "text": "x\n" * 9000}]}]
    elif kind == "bullets":
        raw["sections"] = [{"heading": "Body", "blocks": [{"type": "bullets", "bullets": ["x\r" * 9000]}]}]
    elif kind == "metadata":
        raw["title"] = "x\n" * 9000
    else:
        cell = "x\n" * 9000 if kind == "cell" else "x" * (201 if kind == "cell_chars" else 190)
        rows = [[cell, cell] for _ in range(110 if kind == "repeated_chars" else 1)]
        raw["tables"] = [{"id": "t", "columns": ["A", "B"], "rows": rows}]
        raw["sections"] = [{"heading": "Body", "blocks": [{"type": "table", "table_id": "t"}]}]
    with pytest.raises(ValidationError):
        RequestDeliverableSpec.model_validate(raw)


@pytest.mark.parametrize("fmt", ["pdf", "pptx"])
@pytest.mark.parametrize("axis", ["tables", "bullets", "paragraphs", "charts", "cell_chars"])
def test_LW_11_largest_allowed_work_axes_render_inside_deadline(fmt: str, axis: str) -> None:
    raw: dict[str, Any] = dict(SPEC)
    blocks: list[dict[str, Any]] = []
    if axis == "tables":
        raw["tables"] = [{"id": "t", "columns": ["A", "B"], "rows": [["x", i] for i in range(500)]}]
        blocks = [{"type": "table", "table_id": "t"}]
    elif axis == "cell_chars":
        raw["tables"] = [{"id": "t", "columns": ["A", "B"], "rows": [["word " * 40, "x"] for _ in range(190)]}]
        blocks = [{"type": "table", "table_id": "t"}]
    elif axis == "paragraphs":
        blocks = [{"type": "paragraph", "text": "line\n" * 39 + "end"} for _ in range(29)]
    elif axis == "bullets":
        blocks = [{"type": "bullets", "bullets": ["line\n" * 9 + "end" for _ in range(80)]}]
    else:
        raw["tables"] = [{"id": "t", "columns": ["A", "B"], "rows": [[str(i), i] for i in range(200)]}]
        raw["charts"] = [{"id": "c", "kind": "bar", "table_id": "t", "x": "A", "y": "B", "title": "Chart"}]
        blocks = [{"type": "chart", "chart_id": "c"} for _ in range(4)]
    raw["sections"] = [{"heading": "Body", "blocks": blocks}]
    spec = RequestDeliverableSpec.model_validate(raw)
    started = time.monotonic()
    result = render_pdf(spec) if fmt == "pdf" else render_pptx(spec)
    assert time.monotonic() - started < render_app.DEFAULT_RENDER_TIMEOUT
    assert result.startswith(b"%PDF-" if fmt == "pdf" else b"PK\x03\x04")
    assert len(result) < render_app.MAX_OUTPUT_BYTES
