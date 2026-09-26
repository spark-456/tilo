"""The Director, Lead and Specialist of the P0-09 fixture plan (FR-AGT-01 partial, PRD 8.1):
three deterministic google-adk `BaseAgent` subclasses that make no model call. Each writes its
own step(s) through the single `WorldWriter` (ticket brief item 2), sleeping `step_delay`
(0 by default) after each one so `python -m tilo_harness.skeleton --step-delay` can be killed
mid-run in tests, then -- if it has one -- hands control to its one sub-agent: Director to Lead,
Lead to Specialist.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncGenerator
from typing import Any

from google.adk.agents import BaseAgent
from google.adk.agents.invocation_context import InvocationContext
from google.adk.events import Event


class _StepAgent(BaseAgent):
    """Shared plumbing: `writer.emit(**kwargs)` for each of `self._steps()`, sleeping
    `step_delay` after each one, then hand off to the one sub-agent, if any."""

    writer: Any
    agent_id: str
    unit_id: str
    level: str
    district: str
    step_delay: float = 0.0

    def _steps(self) -> list[dict[str, Any]]:
        raise NotImplementedError

    async def _run_async_impl(self, ctx: InvocationContext) -> AsyncGenerator[Event, None]:
        for kwargs in self._steps():
            self.writer.emit(**kwargs)
            yield Event(author=self.name)
            if self.step_delay:
                await asyncio.sleep(self.step_delay)
        for sub in self.sub_agents:
            async for event in sub.run_async(ctx):
                yield event


class DirectorAgent(_StepAgent):
    """Spawns the Lead and assigns it the plan unit."""

    lead_id: str

    def _steps(self) -> list[dict[str, Any]]:
        common = {"level": self.level, "district": self.district}
        return [
            {
                "type": "agent.spawned",
                "actor": self.agent_id,
                "target": self.lead_id,
                "summary": "A lead joined the team.",
                "data": {"role": "lead"},
                **common,
            },
            {
                "type": "agent.assigned",
                "actor": self.agent_id,
                "target": self.lead_id,
                "summary": "The Director gave the Lead a unit of work.",
                "data": {"unit": self.unit_id},
                **common,
            },
        ]


class LeadAgent(_StepAgent):
    """Spawns the Specialist and hands it the unit through a typed envelope (`agent.handoff`,
    FR-AGT-08: agents never message each other in free text)."""

    specialist_id: str

    def _steps(self) -> list[dict[str, Any]]:
        common = {"level": self.level, "district": self.district}
        envelope = {
            "from": self.agent_id,
            "to": self.specialist_id,
            "artifact_refs": [],
            "summary": f"Work on unit {self.unit_id}.",
            "acceptance_criteria": ["Produce the triage list artifact."],
            "provenance_ids": [],
        }
        return [
            {
                "type": "agent.spawned",
                "actor": self.agent_id,
                "target": self.specialist_id,
                "summary": "A specialist joined the team.",
                "data": {"role": "specialist"},
                **common,
            },
            {
                "type": "agent.handoff",
                "actor": self.agent_id,
                "target": self.specialist_id,
                "summary": "The Lead handed work to the Specialist.",
                "data": {"envelope": envelope},
                **common,
            },
        ]


class SpecialistAgent(_StepAgent):
    """Works the unit and produces an artifact."""

    building_id: str
    artifact_id: str

    def _steps(self) -> list[dict[str, Any]]:
        common = {"level": self.level, "district": self.district}
        return [
            {
                "type": "agent.working",
                "actor": self.agent_id,
                "target": self.building_id,
                "summary": "The Specialist is working at the workshop.",
                "data": {"unit": self.unit_id},
                **common,
            },
            {
                "type": "artifact.created",
                "actor": self.agent_id,
                "target": self.artifact_id,
                "summary": "The Specialist made the triage list.",
                "data": {"artifact": {"artifact_id": self.artifact_id, "version": 1}},
                **common,
            },
        ]
