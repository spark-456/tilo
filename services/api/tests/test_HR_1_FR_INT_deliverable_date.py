"""A deliverable's printed date is a code fact, never the writer's claim."""

import asyncio
import json
from datetime import UTC, date, datetime
from types import SimpleNamespace

import pytest
from tilo_api import report_render
from tilo_api.run_tools import report_day
from tilo_harness.executor import UnitContext
from tilo_harness.tool_runner import ToolUnitRunner
from tilo_providers.interfaces import GenerateResponse


@pytest.mark.parametrize("fmt", ["docx", "pptx", "xlsx", "pdf"])
def test_HR_1_FR_INT_render_stamps_fixed_run_date_over_model_date(fmt):
    model = json.dumps({"title": "Report", "date": "2024-05-15", "sections": []})
    output = asyncio.run(report_render.render_report(model, fmt=fmt, report_date=date(2026, 10, 16)))
    assert json.loads(output.spec_text)["date"] == "2026-10-16"
    assert output.content


def test_HR_1_FR_INT_invalid_model_date_is_ignored():
    model = json.dumps({"title": "Report", "date": "yesterday", "sections": []})
    output = asyncio.run(report_render.render_report(model, report_date=date(2026, 10, 16)))
    assert json.loads(output.spec_text)["date"] == "2026-10-16"


def test_HR_1_FR_INT_run_date_uses_owner_zone_else_utc():
    now = datetime(2026, 10, 15, 20, 30, tzinfo=UTC)
    person = SimpleNamespace(record={"time_zone": "Asia/Kolkata"})
    stores = SimpleNamespace(persons=SimpleNamespace(get=lambda *_: person))
    assert report_day("owner", "org", lambda: stores, now) == date(2026, 10, 16)
    assert report_day("owner", "org", lambda: None, now) == date(2026, 10, 15)


def test_HR_1_FR_INT_writer_prompt_and_fallback_pdf_use_fixed_date():
    class Writer:
        prompt = ""

        def generate(self, request):
            self.prompt = request.prompt
            return GenerateResponse(
                text=json.dumps({"title": "Report", "date": "2024-05-15", "sections": []}), profile_id="fake"
            )

    writer = Writer()
    runner = ToolUnitRunner({"writer": writer}, today=lambda: date(2026, 10, 16))
    unit = {"id": "U1", "role": "writer", "unit_type": "deliver", "title": "Report"}
    context = UnitContext("A_w", (), brief={"deliverables": [{"format": "pdf", "title": "Report"}]})
    result = asyncio.run(runner.run(unit, context))
    assert result.success
    assert "Today's date (from code): 2026-10-16" in writer.prompt
    assert json.loads(result.outputs[0].spec_text)["date"] == "2026-10-16"
