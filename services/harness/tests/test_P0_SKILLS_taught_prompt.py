"""A taught run sends its saved instructions to the worker, not just a generic task title."""

import asyncio

from tilo_harness.executor import UnitContext
from tilo_harness.tool_runner import ToolUnitRunner
from tilo_harness.tools import ToolRegistry
from tilo_providers.fake import FakeModelProvider
from tilo_providers.interfaces import GenerateRequest, GenerateResponse
from tilo_providers.safety import FakeSafetyProvider


class Capture(FakeModelProvider):
    def __init__(self):
        super().__init__("capture")
        self.prompts = []

    def generate(self, request: GenerateRequest) -> GenerateResponse:
        self.prompts.append(request.prompt)
        return GenerateResponse(text="Finished result", profile_id="capture")


def test_P0_SKILLS_taught_unit_uses_saved_steps_instead_of_generic_essay():
    provider = Capture()
    runner = ToolUnitRunner({"writer": provider}, tools=ToolRegistry([]), safety=FakeSafetyProvider())
    unit = {"id": "U2", "title": "Draft the supplier reply", "unit_type": "taught_step", "role": "writer"}
    context = UnitContext(
        "A_w0",
        (),
        brief={
            "goal": "Reply to the supplier",
            "taught_skill_steps": ["Read the supplier message", "Draft the supplier reply"],
        },
    )
    asyncio.run(runner.run_unit(unit, context))
    prompt = provider.prompts[0]
    assert "Read the supplier message" in prompt
    assert "Draft the supplier reply" in prompt
    assert "Execute this saved step" in prompt
