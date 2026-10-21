"""DEMO-BROWSER (owner, 21 Oct: "take screenshots and save it as pdf with proper captioning"): a pdf, docx or pptx
deliverable may show the pages Tilo's browser read in the run as figures. Code chooses them from the run's own recorded
events (each read step's frame; a session with no read gives its last frame), never from the task's words (GEN-06), and
only frames that are this run's masked browser PNGs, screened clean or unscreened (never flagged), within the render
caps. The writer sees them as F1, F2, ... with their page address and step; render_report adds the pictures.
"""

from __future__ import annotations

import asyncio
import base64
import io
import json
import threading
from types import SimpleNamespace

import pytest
from PIL import Image
from tilo_memory.artifacts import Scope

RUN, WORLD = "r_figs", "w_figs"


def _png(colour: str) -> bytes:
    out = io.BytesIO()
    Image.new("RGB", (240, 160), colour).save(out, "PNG")
    return out.getvalue()


class Artifacts:
    def __init__(self):
        self.saved: dict[str, tuple[bytes, dict]] = {}

    def add(self, ident, content, **record):
        base = {"run_id": RUN, "origin": {"kind": "browser"}, "media_type": "image/png", "screening": "unscreened"}
        self.saved[ident] = (content, {**base, "size_bytes": len(content), **record})

    def head(self, scope, ref):
        found = self.saved.get(ref["artifact_id"])
        return SimpleNamespace(record=found[1]) if found else None

    def read(self, scope, ref):
        return self.saved[ref["artifact_id"]][0]


def _acted(session, step, kind, host="en.wikipedia.org"):
    frame = {"artifact_id": f"art_{session}_{step}", "version": 1}
    data = {"session": session, "step": step, "kind": kind, "verdict": "done", "host": host, "frame": frame}
    return {"type": "browser.acted", "data": data}


def _runner(events, artifacts, pages=None):
    from tilo_api import run_tools

    owner = SimpleNamespace(
        world_id=WORLD,
        run_id=RUN,
        scope=Scope("org_demo", "w_demo", "u_demo"),
        store=SimpleNamespace(events={WORLD: events}),
        seams=SimpleNamespace(artifacts=artifacts),
    )
    runner = object.__new__(run_tools.BoundRunRunner)
    runner.run_owner, runner.frame_pages, runner.browser_lock = owner, dict(pages or {}), threading.Lock()
    return runner


def _run_with_three_sessions():
    artifacts = Artifacts()
    events = [{"type": "browser.started", "data": {"session": "s1", "host": "www.wikipedia.org",
                                                    "frame": {"artifact_id": "art_s1_0", "version": 1}}}]  # fmt: skip
    artifacts.add("art_s1_0", _png("#111"))
    for session, colour in (("s1", "#a00"), ("s2", "#0a0"), ("s3", "#00a")):
        for step, kind in ((1, "type"), (2, "click"), (3, "scroll"), (4, "extract")):
            events.append(_acted(session, step, kind))
            artifacts.add(f"art_{session}_{step}", _png(colour))
    pages = {
        "art_s1_4": {"url": "https://en.wikipedia.org/wiki/List_of_tallest_structures_in_Japan", "step": "Japan"},
        "art_s2_4": {"url": "https://en.wikipedia.org/wiki/List_of_tallest_buildings_in_India", "step": "India"},
    }
    return events, artifacts, pages


def test_DEMO_BROWSER_the_pages_the_browser_read_are_the_writers_figures():
    events, artifacts, pages = _run_with_three_sessions()
    figures, listing = _runner(events, artifacts, pages).browser_figures()
    assert list(figures) == ["F1", "F2", "F3"]
    assert base64.b64decode(figures["F2"]["image_base64"]) == artifacts.saved["art_s2_4"][0], "the read step's frame"
    assert figures["F1"]["source"] == "https://en.wikipedia.org/wiki/List_of_tallest_structures_in_Japan"
    assert figures["F3"]["source"] == "https://en.wikipedia.org/", (
        "an address not kept in memory falls back to the host"
    )
    assert listing.splitlines()[0] == (
        "F1: the page https://en.wikipedia.org/wiki/List_of_tallest_structures_in_Japan (for the step: Japan)"
    )


def test_DEMO_BROWSER_a_read_page_is_shown_as_it_first_came_into_view():
    """The read step's frame is where the browser ended, often scrolled past the title; the figure is the session's
    first frame of that same page (the page's top), found by the page addresses kept in memory."""
    events, artifacts, pages = _run_with_three_sessions()
    url = pages["art_s1_4"]["url"]
    pages = {**pages, "art_s1_2": {"url": url, "step": "Japan"}, "art_s1_3": {"url": url, "step": "Japan"}}
    figures, _ = _runner(events, artifacts, pages).browser_figures()
    assert base64.b64decode(figures["F1"]["image_base64"]) == artifacts.saved["art_s1_2"][0]
    assert figures["F1"]["source"] == url


def test_DEMO_BROWSER_a_session_with_no_read_gives_its_last_frame():
    artifacts = Artifacts()
    events = [_acted("s1", 1, "click"), _acted("s1", 2, "scroll")]
    for step in (1, 2):
        artifacts.add(f"art_s1_{step}", _png("#555"))
    figures, _ = _runner(events, artifacts).browser_figures()
    assert base64.b64decode(figures["F1"]["image_base64"]) == artifacts.saved["art_s1_2"][0]


@pytest.mark.parametrize(
    "record",
    [{"screening": "flagged"}, {"run_id": "r_other"}, {"origin": {"kind": "upload"}}, {"media_type": "image/jpeg"}],
    ids=["flagged", "another run", "not a browser frame", "not the frame type"],
)
def test_DEMO_BROWSER_only_this_runs_unflagged_browser_frames_become_figures(record):
    artifacts = Artifacts()
    artifacts.add("art_s1_1", _png("#777"), **record)
    figures, listing = _runner([_acted("s1", 1, "extract")], artifacts).browser_figures()
    assert figures == {} and listing == ""


def test_DEMO_BROWSER_figures_stay_within_the_render_caps(monkeypatch):
    from tilo_api import run_tools

    monkeypatch.setattr(run_tools, "MAX_FIGURES", 2)
    events, artifacts, pages = _run_with_three_sessions()
    figures, _ = _runner(events, artifacts, pages).browser_figures()
    assert list(figures) == ["F1", "F2"]


def test_DEMO_BROWSER_the_report_carries_the_pictures_and_the_redactor_reads_only_words():
    from pypdf import PdfReader
    from tilo_api.report_render import render_report

    events, artifacts, pages = _run_with_three_sessions()
    figures, _ = _runner(events, artifacts, pages).browser_figures()
    reply = json.dumps(
        {
            "title": "Tallest buildings",
            "date": "2026-10-21",
            "sections": [
                {
                    "heading": "Screenshots",
                    "blocks": [
                        {"type": "figure", "figure_id": "F1", "caption": "Japan's list on Wikipedia"},
                        {"type": "figure", "figure_id": "F2", "caption": "India's list on Wikipedia"},
                    ],
                }
            ],
        }
    )
    pdf = asyncio.run(render_report(reply, fmt="pdf", figures=figures))
    reader = PdfReader(io.BytesIO(pdf.content))
    text = "\n".join(page.extract_text() for page in reader.pages)
    assert sum(len(page.images) for page in reader.pages) == 2
    assert "Figure 1: Japan's list on Wikipedia" in text and "Figure 2: India's list on Wikipedia" in text
    assert "Source: https://en.wikipedia.org/wiki/List_of_tallest_buildings_in_India" in text
    assert "image_base64" not in pdf.spec_text
    docx = asyncio.run(render_report(reply, fmt="docx", figures=figures))
    assert docx.content[:2] == b"PK" and b"word/media/figure2.png" in docx.content
