"""FR-AGT-03 (tools half): a specialist whose plan pins no skill still gets the default read-only web tools.

The Director may leave a unit's `skills` empty (plan_system.md allows it), and a unit's tools were only its skills'
`tools_allowed`, so such a research unit had no way to look anything up. `default_tools` maps a role to the tool names
a unit of that role gets when its skills name none. It never widens a unit whose skills name tools, never adds a
tool the registry does not hold, and a role not in the map gets nothing.
"""

from __future__ import annotations

import asyncio

from test_LW_07_tool_unit_runner import UNIT, Script, SendEmail, context, make, tool_names
from tilo_harness.executor import UnitContext
from tilo_harness.tools import FakeFetchUrl, FakeWebSearch

DEFAULTS = {"specialist": ("web_search", "fetch_url")}
NO_SKILL = UnitContext(agent_id="A_s0", skills=())


def first_request(unit: dict, ctx: UnitContext, *tools, **kwargs):
    provider = Script("done")
    runner = make(provider, list(tools) or [FakeWebSearch(), FakeFetchUrl()], default_tools=DEFAULTS, **kwargs)
    asyncio.run(runner.run_unit(unit, ctx))
    return provider.requests[0]


def test_FR_AGT_03_a_specialist_with_no_skill_gets_web_search_and_fetch_url() -> None:
    assert tool_names(first_request(UNIT, NO_SKILL)) == {"web_search", "fetch_url"}


def test_FR_AGT_03_a_specialist_whose_skills_name_no_tool_gets_the_defaults() -> None:
    assert tool_names(first_request(UNIT, context())) == {"web_search", "fetch_url"}


def test_FR_AGT_03_a_skill_that_names_tools_is_not_widened_by_the_defaults() -> None:
    assert tool_names(first_request(UNIT, context("web_search"))) == {"web_search"}


def test_FR_AGT_03_only_registered_default_tools_are_offered_and_side_effects_never() -> None:
    request = first_request(UNIT, NO_SKILL, FakeWebSearch(), SendEmail())
    assert tool_names(request) == {"web_search"}


def test_FR_AGT_03_a_role_outside_the_defaults_gets_no_tools() -> None:
    writer = {**UNIT, "role": "writer"}
    provider = Script("done")
    runner = make(provider, [FakeWebSearch(), FakeFetchUrl()], default_tools=DEFAULTS)
    runner._providers["writer"] = provider  # the same script answers the writer
    asyncio.run(runner.run_unit(writer, NO_SKILL))
    assert provider.requests[0].tools is None


def test_FR_AGT_03_without_default_tools_a_unit_with_no_skill_still_has_none() -> None:
    provider = Script("done")
    asyncio.run(make(provider, [FakeWebSearch(), FakeFetchUrl()]).run_unit(UNIT, NO_SKILL))
    assert provider.requests[0].tools is None
