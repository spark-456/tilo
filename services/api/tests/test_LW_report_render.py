"""The writer renderer retains its slot until a claimed worker actually ends."""

import asyncio
import json
import threading

import pytest
from tilo_api import report_render
from tilo_harness.deliverable import DeliverableRefused

SPEC = json.dumps(
    {
        "title": "Report",
        "date": "2026-10-11",
        "sections": [
            {"heading": "Summary", "blocks": [{"type": "paragraph", "text": "Checked sources."}]},
        ],
    }
)


@pytest.mark.parametrize("cancel", [False, True])
def test_abandoned_queued_worker_releases_slot_once(monkeypatch, cancel):
    jobs = []
    slots = threading.BoundedSemaphore(1)
    monkeypatch.setattr(report_render, "_SLOTS", slots)
    monkeypatch.setattr(report_render, "RENDER_TIMEOUT_S", 0.01)

    async def queued(worker):
        jobs.append(worker)
        await asyncio.Event().wait()

    monkeypatch.setattr(report_render, "run_in_threadpool", queued)

    async def exercise():
        task = asyncio.create_task(report_render.render_report(SPEC))
        while not jobs:
            await asyncio.sleep(0)
        if cancel:
            task.cancel()
        with pytest.raises(asyncio.CancelledError if cancel else DeliverableRefused):
            await task

    asyncio.run(exercise())
    assert slots.acquire(blocking=False)
    assert jobs[0]() == b""  # late executor handoff does no work and cannot release a second slot
    assert not slots.acquire(blocking=False)
    slots.release()


def test_writer_uses_the_render_doors_work_budget():
    raw = json.loads(SPEC)
    raw["sections"][0]["blocks"][0]["text"] = "x" * 40001
    with pytest.raises(DeliverableRefused):
        asyncio.run(report_render.render_report(json.dumps(raw)))
