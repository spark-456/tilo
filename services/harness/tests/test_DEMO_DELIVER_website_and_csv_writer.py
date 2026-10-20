"""DEMO-DELIVER: the final writer's website and CSV come out as real files more often.

Website (WEB-1): a live CLAT questionnaire page (20 Oct) failed the WS checker on `window.scrollTo({ top: 0 })` and a
chart's `padding = { top: 30 }` further down; the checker names only the first problem, so the one repair fixed that
line and the page degraded to Markdown. `website.tidy` now rewrites the scroll call to positions before the check, and
the repair is told every failing line (up to 10) and shown the whole page. CSV: a brief whose first deliverable is
`csv` gets the spec prompt and a real `text/csv` file, also without the API's render door. Fake providers only.
"""

from __future__ import annotations

import asyncio
import csv
import io
import json
from typing import Any

import pytest
from tilo_harness.deliverable import DeliverableRefused
from tilo_harness.executor import UnitContext
from tilo_harness.tool_runner import ToolUnitRunner
from tilo_harness.website import MAX_HINTS, REPAIR_REPLY_CHARS, tidy, website_output
from tilo_memory.website_check import check_website
from tilo_providers.fake import FakeModelProvider
from tilo_providers.interfaces import GenerateRequest, GenerateResponse

UNIT = {"id": "U5", "title": "CLAT questionnaire", "unit_type": "deliver", "role": "writer"}
SITE = {"goal": "A CLAT questionnaire with a results graph", "deliverables": [{"title": "Quiz", "format": "website"}]}
FILLER = "".join(f"  // question {n}: scored on screen\n" for n in range(1, 1200))  # about 40k characters
CLAT = (
    '<!doctype html>\n<html><head><meta charset="utf-8"><title>CLAT check</title></head><body>\n'
    '<div id="q"></div><button type="button" id="next">Next</button><canvas id="c"></canvas>\n<script>\n'
    + FILLER
    + 'function restart() {\n  window.scrollTo({ top: 0, behavior: "smooth" });\n}\n'
    + "function graph() {\n  var padding = { top: 30, right: 30, bottom: 60, left: 55 };\n"
    + "  return padding.left;\n}\n</script>\n</body></html>"
)
FIXED = CLAT.replace("var padding = { top: 30, right: 30, bottom: 60, left: 55 };", "var pad = [30, 30, 60, 55];")
FIXED = FIXED.replace("return padding.left;", "return pad[3];")


class Script(FakeModelProvider):
    def __init__(self, *replies: str) -> None:
        super().__init__("script")
        self.replies, self.requests = list(replies), []

    def generate(self, request: GenerateRequest) -> GenerateResponse:
        self.requests.append(request)
        return GenerateResponse(text=self.replies.pop(0), profile_id="script")


def run(brief: Any, *replies: str) -> tuple[Any, Script]:
    provider = Script(*replies)
    runner = ToolUnitRunner({"writer": provider}, meter=lambda *_: 1.0)
    return asyncio.run(runner.run_unit(UNIT, UnitContext("A_w2", (), brief=brief))), provider


@pytest.mark.parametrize(
    "call, fixed",
    [
        ('window.scrollTo({ top: 0, behavior: "smooth" })', "window.scrollTo(0, 0)"),
        ("el.scrollBy({top: el.offsetHeight - 80, left: 10})", "el.scrollBy(10, el.offsetHeight - 80)"),
        ("scroll({ behavior: 'smooth', top: y, })", "scroll(0, y)"),
        ("scrollTo({\n  top: 0,\n  behavior: 'smooth'\n})", "scrollTo(0, 0)\n\n\n"),  # later lines keep their numbers
    ],
)
def test_DEMO_DELIVER_WEB_1_tidy_turns_scroll_options_into_positions(call: str, fixed: str) -> None:
    assert tidy(f"<script>{call};</script>") == f"<script>{fixed};</script>"


@pytest.mark.parametrize(
    "call",
    [
        "window.scrollTo({ top: Math.max(0, y) })",  # a call inside: left for the model to fix
        "window.scrollTo({ left: 5 })",
        "window.scrollTo({ top: 1, top: 2 })",
        "card.place({ top: 0 })",
        "window.scrollTo({ top: 0, block: 'start' })",
    ],
)
def test_DEMO_DELIVER_WEB_1_tidy_leaves_every_other_shape_unchanged(call: str) -> None:
    assert tidy(call) == call


def test_DEMO_DELIVER_WEB_1_the_live_clat_page_gets_one_repair_naming_the_line_tidy_cannot_fix() -> None:
    assert len(CLAT) > 40_000 and not check_website(CLAT.encode()).ok
    result, provider = run(SITE, CLAT, FIXED)
    out = result.outcome.outputs[0]
    assert result.outcome.success and out.media_type == "text/html" and len(provider.requests) == 2
    assert b"window.scrollTo(0, 0);" in out.content and check_website(out.content).ok
    repair = provider.requests[1].prompt
    padding_line = CLAT.split("\n").index("  var padding = { top: 30, right: 30, bottom: 60, left: 55 };") + 1
    assert f"ws_script, line {padding_line}" in repair and "Fix every one of these lines" in repair
    assert "return padding.left;" in repair  # the whole page, its last lines included, is shown as data


def test_DEMO_DELIVER_WEB_1_every_failing_line_is_named_up_to_the_cap_never_the_text() -> None:
    lines = ["<!doctype html>", "<p>ok</p>", "<script>"]
    lines += [f"var a{n} = {{ top: {n} }};" for n in range(MAX_HINTS + 3)] + ["</script>"]
    with pytest.raises(DeliverableRefused) as refused:
        website_output("\n".join(lines))
    hints = refused.value.detail.split("; ")
    assert hints == [f"ws_script, line {n}" for n in range(4, 4 + MAX_HINTS)]
    assert "top" not in refused.value.detail and REPAIR_REPLY_CHARS >= 100_000


SPEC = {
    "title": "Time zones",
    "date": "2026-10-20",
    "tables": [{"id": "z", "columns": ["Zone", "Offset"], "rows": [["Asia/Tokyo", 9], ["Europe/London", 0]]}],
    "sections": [{"heading": "Zones", "blocks": [{"type": "table", "table_id": "z"}]}],
}
CSV_BRIEF = {"goal": "All time zones as a CSV", "deliverables": [{"title": "Zones", "format": "csv"}]}


def test_DEMO_DELIVER_a_csv_brief_gets_the_spec_prompt_and_a_real_csv_file() -> None:
    result, provider = run(CSV_BRIEF, json.dumps(SPEC))
    out = result.outcome.outputs[0]
    assert result.outcome.success and out.media_type == "text/csv" and len(provider.requests) == 1
    assert list(csv.reader(io.StringIO(out.content.decode("utf-8-sig")))) == [
        ["Zone", "Offset"], ["Asia/Tokyo", "9"], ["Europe/London", "0"]
    ]  # fmt: skip
    assert "DeliverableSpec" in provider.requests[0].prompt and "is one table" in provider.requests[0].prompt


def test_DEMO_DELIVER_a_csv_reply_that_stays_prose_is_the_text_never_a_broken_file() -> None:
    result, provider = run(CSV_BRIEF, "Tokyo is UTC+9.", "Still prose.")
    out = result.outcome.outputs[0]
    assert result.outcome.success and out.media_type == "text/markdown" and out.content == b"Tokyo is UTC+9."
    assert len(provider.requests) == 2 and "could not build the csv file" in result.outcome.summary
