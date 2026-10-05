"""Plan executor (FR-AGT-01, FR-AGT-02, FR-AGT-03; PRD 8.1, 8.2, 8.4).

`run_plan` first refuses, writing nothing, a plan or layout that breaks its schema, a plan with
an unknown or self dependency (PG-02) or a cycle (PG-03), a unit naming a skill the registry
does not hold (PG-11), and a layout without exactly one Director, a lead-rank Lead for every
district with units, or one worker agent of the unit's rank per unit. It then pins every skill
the plan uses and runs the units as asyncio tasks in one thread: a unit starts only after every
unit it depends on has finished, and at most `limits.max_specialists` units run at once. A unit
whose dependency failed is skipped. Every event goes through the one `WorldWriter`.

With `must_ask` (FR-AGT-05) a unit is assessed right after it is assigned: when a must-ask rule fires,
the question chain and card are written and the unit is parked (`RunResult.parked`): its work does not
start, it does not retire, and its dependents are skipped. Answering is FR-AGT-06/07.
With `question_wait` as well (FR-HIL-10) the unit instead waits for its answer, holding no `max_specialists` slot,
then runs once with it in `UnitContext.answer` only if `Ask.runs` says so; Hold, Stop, Skip and a default leave
it held (`RunResult.held`, retired, nothing made) and its dependents skipped. The other units go on.

With `verifier` (FR-AGT-12) the layout must hold that verifier-rank agent and it must not work a unit
itself. Once a successful unit has handed over, each artifact it handed over gets one `artifact.reviewed`
(caused by the handoff) before the unit's dependents start; the review result is recorded, not acted on.

Per unit: agent.spawned (Lead spawns the worker), agent.assigned, skill.loaded per pinned skill,
agent.working, the `UnitRunner`'s work, agent.handoff (typed envelope, worker to Lead) when it
succeeded with a contract-valid envelope, agent.retired. A pinned skill whose files changed,
a runner that raises (or cancels its own work) and an outcome that breaks the envelope contract
each fail that unit only, as does a handoff the writer rejects: it retires, its dependents are
skipped, the other units go on. Only a cancel of `run_plan` itself or any other writer error
(WriterBusy, EventRejected) ends the run.
"""

from __future__ import annotations

import asyncio
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any, Protocol

from tilo_providers.interfaces import GenerateRequest, ModelProvider
from tilo_providers.prompts import load_prompt

from tilo_harness.config import AgentsConfig
from tilo_harness.must_ask import MustAsk
from tilo_harness.question_wait import Answer, QuestionWait
from tilo_harness.skills import LoadedSkill, Pins, SkillError, SkillRegistry
from tilo_harness.validator import EventRejected, repo_validator
from tilo_harness.verifier import Verifier

_WORKER_RANKS = ("specialist", "verifier", "writer")  # ranks that execute units (PRD 8.1)
_LEVELS = 3  # Director -> Lead -> worker


class PlanRefused(Exception):
    """The plan cannot run as given; nothing was written."""

    def __init__(self, problems: list[str]) -> None:
        super().__init__("; ".join(problems))
        self.problems = problems


@dataclass(frozen=True)
class UnitOutcome:
    success: bool
    summary: str = ""
    artifact_refs: tuple[dict[str, Any], ...] = ()
    provenance_ids: tuple[str, ...] = ()


@dataclass(frozen=True)
class UnitContext:
    agent_id: str
    skills: tuple[LoadedSkill, ...]
    answer: Answer | None = None  # the answer to the question this unit asked before it started (FR-HIL-10)


class UnitRunner(Protocol):
    async def run(self, unit: Mapping[str, Any], context: UnitContext) -> UnitOutcome: ...


@dataclass
class RunResult:
    pins: Pins
    outcomes: dict[str, UnitOutcome] = field(default_factory=dict)
    skipped: list[str] = field(default_factory=list)
    parked: list[str] = field(default_factory=list)  # waiting for a person's answer (FR-AGT-05)
    held: list[str] = field(default_factory=list)  # answered, and the answer leaves the unit unrun (FR-HIL-10)

    @property
    def failed(self) -> list[str]:
        return [unit_id for unit_id, outcome in self.outcomes.items() if not outcome.success]


class DefaultUnitRunner:
    """Does a unit's work with the model for the unit's role, through the provider layer."""

    def __init__(self, providers: Mapping[str, ModelProvider]) -> None:
        self._providers = providers

    async def run(self, unit: Mapping[str, Any], context: UnitContext) -> UnitOutcome:
        provider = self._providers[unit["role"]]
        prompt = load_prompt(
            unit["role"],
            "unit.md",
            {
                "title": unit["title"],
                "unit_type": unit["unit_type"],
                "skills": "\n\n".join(skill.body for skill in context.skills),
            },
        )
        response = await asyncio.to_thread(provider.generate, GenerateRequest(prompt=prompt))
        return UnitOutcome(success=bool(response.text), summary=f"Finished {unit['title']}.")


@dataclass(frozen=True)
class _Roster:
    director: str
    leads: dict[str, str]  # district -> Lead
    levels: dict[str, str]  # district -> level
    workers: dict[str, str]  # unit -> worker agent
    sites: dict[str, str]  # unit -> building


def _dependency_order(units: list[dict[str, Any]]) -> list[dict[str, Any]]:
    ids = [unit["id"] for unit in units]
    if len(set(ids)) != len(ids):
        raise PlanRefused(["plan: unit ids must be unique"])
    for unit in units:
        for dep in unit["depends_on"]:
            if dep == unit["id"] or dep not in ids:
                raise PlanRefused([f"PG-02: {unit['id']} depends on {dep!r}, which is not another unit of this plan"])
    order: list[dict[str, Any]] = []
    placed: set[str] = set()
    pending = list(units)
    while pending:
        ready = [unit for unit in pending if set(unit["depends_on"]) <= placed]
        if not ready:
            raise PlanRefused(["PG-03: the depends_on graph has a cycle"])
        order += ready
        placed |= {unit["id"] for unit in ready}
        pending = [unit for unit in pending if unit["id"] not in placed]
    return order


def _roster(units: list[dict[str, Any]], layout: dict[str, Any], config: AgentsConfig) -> _Roster:
    semantic = layout["semantic"]
    rank = {agent["id"]: agent["rank"] for agent in semantic["agents"]}
    directors = [agent_id for agent_id, r in rank.items() if r == "director"]
    if len(directors) != config.limits.directors_per_world:
        raise PlanRefused([f"layout: needs exactly {config.limits.directors_per_world} director, has {len(directors)}"])
    if config.limits.max_depth < _LEVELS:
        raise PlanRefused([f"config: max_depth {config.limits.max_depth} is below the {_LEVELS} levels used"])
    districts = {d["id"]: (level["id"], d) for level in semantic["levels"] for d in level["districts"]}
    sites = {
        unit_id: building["id"]
        for _, district in districts.values()
        for building in district["buildings"]
        for unit_id in building.get("plan_units", [])
    }
    pool = {r: [agent_id for agent_id, agent_rank in rank.items() if agent_rank == r] for r in _WORKER_RANKS}
    leads: dict[str, str] = {}
    levels: dict[str, str] = {}
    workers: dict[str, str] = {}
    for unit in units:
        found = districts.get(unit["district"])
        if found is None:
            raise PlanRefused([f"layout: {unit['id']}'s district {unit['district']} is not in the layout"])
        level_id, district = found
        if rank.get(district["lead"]) != "lead":
            raise PlanRefused([f"layout: district {district['id']}'s lead {district['lead']} is not lead-rank"])
        if unit["role"] not in pool:
            raise PlanRefused([f"plan: {unit['id']} has role {unit['role']}; units run as {_WORKER_RANKS}"])
        if not pool[unit["role"]]:
            raise PlanRefused([f"layout: too few {unit['role']}-rank agents for the plan's units"])
        leads[district["id"]] = district["lead"]
        levels[district["id"]] = level_id
        workers[unit["id"]] = pool[unit["role"]].pop(0)
    return _Roster(directors[0], leads, levels, workers, sites)


def _envelope(outcome: UnitOutcome, worker: str, lead: str, unit: dict[str, Any]) -> dict[str, Any] | None:
    """The handoff envelope (PRD 8.4) for a successful outcome, or None if it breaks the contract."""
    summary, refs, provenance = outcome.summary, outcome.artifact_refs, outcome.provenance_ids
    if not (isinstance(summary, str) and isinstance(refs, list | tuple) and isinstance(provenance, list | tuple)):
        return None
    envelope = {
        "from": worker,
        "to": lead,
        "artifact_refs": list(refs),
        "summary": (summary or f"Finished unit {unit['id']}.")[:1000],
        "acceptance_criteria": [f"Unit {unit['id']} done: {unit['title']}"[:300]],
        "provenance_ids": list(provenance),
    }
    return None if repo_validator().contract_problems("envelope", envelope) else envelope


class _Slot:
    """One of `max_specialists` places; a unit waiting for a person gives its place back and takes one again."""

    def __init__(self, slots: asyncio.Semaphore) -> None:
        self._slots, self._held = slots, False

    async def __aenter__(self) -> _Slot:
        await self.take()
        return self

    async def __aexit__(self, *exc: object) -> None:
        self.give()

    async def take(self) -> None:
        await self._slots.acquire()
        self._held = True

    def give(self) -> None:
        if self._held:
            self._held = False
            self._slots.release()


class _Run:
    def __init__(
        self,
        writer: Any,
        roster: _Roster,
        skills: SkillRegistry,
        pins: Pins,
        runner: Any,
        must_ask: MustAsk | None,
        verifier: Verifier | None,
        question_wait: QuestionWait | None,
    ) -> None:
        self.writer, self.roster, self.skills, self.pins, self.runner = writer, roster, skills, pins, runner
        self.must_ask, self.verifier, self.question_wait = must_ask, verifier, question_wait
        self.held: set[str] = set()
        self.handoffs: dict[str, str] = {}  # unit -> the agent.handoff event that carried its artifacts

    def emit(self, type_: str, actor: str, target: str, summary: str, data: dict[str, Any], **kw: Any) -> str:
        district = kw.get("district")
        event = self.writer.emit(
            type=type_,
            actor=actor,
            target=target,
            summary=summary,
            data=data,
            level=self.roster.levels.get(district) if district else None,
            district=district,
            cause=kw.get("cause"),
        )
        return str(event["id"])

    def spawn_team(self) -> None:
        director = self.roster.director
        cause = self.emit("agent.spawned", "system", director, "The Director joined the team.", {"role": "director"})
        for district, lead in self.roster.leads.items():
            self.emit(
                "agent.spawned",
                director,
                lead,
                "A Lead joined the team.",
                {"role": "lead"},
                district=district,
                cause=cause,
            )

    async def work(self, unit: dict[str, Any], slot: _Slot) -> UnitOutcome | None:
        """None when the unit was parked to ask a person first."""
        unit_id, district = unit["id"], unit["district"]
        lead, worker = self.roster.leads[district], self.roster.workers[unit_id]
        at = {"district": district}
        cause = self.emit("agent.spawned", lead, worker, "An agent joined the team.", {"role": unit["role"]}, **at)
        cause = self.emit(
            "agent.assigned", lead, worker, "The Lead gave it a unit.", {"unit": unit_id}, cause=cause, **at
        )
        answer: Answer | None = None
        if self.must_ask is not None:
            ask = await self.must_ask.assess(unit)  # no failure count yet: retries arrive with FR-AGT-13
            if ask is not None:
                card = self.must_ask.raise_question(
                    ask,
                    writer=self.writer,
                    unit=unit,
                    specialist=worker,
                    lead=lead,
                    director=self.roster.director,
                    district=district,
                    cause=cause,
                )
                if self.question_wait is None:
                    return None
                slot.give()  # that branch waits (PRD 10.2); the other units use its place
                answer = await self.question_wait.wait_for(
                    card, lead=lead, director=self.roster.director, district=district
                )
                await slot.take()
                check = getattr(ask, "runs", None)  # a stand-in ask without a rule runs on any answer
                if check is not None and not check(answer):
                    self.held.add(unit_id)
                    self.emit("agent.retired", lead, worker, "The agent left without starting.", {}, cause=cause, **at)
                    return UnitOutcome(success=False, summary="The step was held, so it did not run.")
        try:
            loaded = tuple(self.skills.load_pinned(skill_id, self.pins) for skill_id in unit["skills"])
        except SkillError:
            outcome = UnitOutcome(success=False, summary="A pinned skill changed on disk, so the unit stopped.")
        else:
            for skill in loaded:
                data = {"skill": skill.id, "version": skill.version}
                cause = self.emit("skill.loaded", worker, worker, "The agent loaded a skill.", data, cause=cause, **at)
            site = self.roster.sites.get(unit_id, district)
            cause = self.emit(
                "agent.working", worker, site, "The agent is working.", {"unit": unit_id}, cause=cause, **at
            )
            ran: object
            try:
                # Its own task, so a runner that cancels the current task cancels only its work.
                ran = await asyncio.ensure_future(self.runner.run(unit, UnitContext(worker, loaded, answer)))
            except asyncio.CancelledError:
                task = asyncio.current_task()
                if task is not None and task.cancelling():  # the run itself was cancelled
                    raise
                ran = None  # the runner cancelled its own work: this unit fails, the run goes on
            except Exception:  # a runner crash fails this unit closed; the run goes on
                ran = None
            failed = UnitOutcome(success=False, summary="The unit's work failed.")
            outcome = ran if isinstance(ran, UnitOutcome) else failed
        envelope = _envelope(outcome, worker, lead, unit) if outcome.success is True else None
        if envelope is None and outcome.success is not False:
            outcome = UnitOutcome(success=False, summary="The unit's result was not a valid handoff.")
        if envelope is not None:
            summary = "The agent handed its result to the Lead."
            try:
                cause = self.emit("agent.handoff", worker, lead, summary, {"envelope": envelope}, cause=cause, **at)
            except EventRejected:  # the writer refused the handoff and wrote nothing: this unit fails
                outcome = UnitOutcome(success=False, summary="The unit's result was not a valid handoff.")
            else:
                self.handoffs[unit_id] = cause
        self.emit("agent.retired", lead, worker, "The agent finished and left.", {}, cause=cause, **at)
        return outcome

    async def review(self, unit: dict[str, Any], outcome: UnitOutcome) -> None:
        if self.verifier is None or unit["id"] not in self.handoffs:
            return
        for ref in outcome.artifact_refs:
            await self.verifier.review_and_record(
                ref, writer=self.writer, cause=self.handoffs[unit["id"]], district=unit["district"]
            )


async def run_plan(
    plan: dict[str, Any],
    layout: dict[str, Any],
    *,
    writer: Any,
    config: AgentsConfig,
    skills: SkillRegistry,
    runner: UnitRunner,
    must_ask: MustAsk | None = None,
    verifier: Verifier | None = None,
    question_wait: QuestionWait | None = None,
) -> RunResult:
    validator = repo_validator()
    problems = validator.contract_problems("plan", plan) + validator.contract_problems("layout", layout)
    if problems:
        raise PlanRefused(problems)
    order = _dependency_order(plan["units"])
    roster = _roster(plan["units"], layout, config)
    if verifier is not None:
        ranks = {agent["id"]: agent["rank"] for agent in layout["semantic"]["agents"]}
        if ranks.get(verifier.agent_id) != "verifier" or verifier.agent_id in roster.workers.values():
            raise PlanRefused([f"layout: {verifier.agent_id} must be a verifier-rank agent that works no unit"])
    try:
        pins = skills.pin(sorted({skill_id for unit in order for skill_id in unit["skills"]}))
    except SkillError as error:
        raise PlanRefused([f"PG-11: {error}"]) from error

    result = RunResult(pins=pins)
    run = _Run(writer, roster, skills, pins, runner, must_ask, verifier, question_wait)
    run.spawn_team()
    slots = asyncio.Semaphore(config.limits.max_specialists)
    loop = asyncio.get_running_loop()
    finished: dict[str, asyncio.Future[bool]] = {unit["id"]: loop.create_future() for unit in order}

    async def unit_task(unit: dict[str, Any]) -> None:
        dependencies_ok = [await finished[dep] for dep in unit["depends_on"]]
        if not all(dependencies_ok):
            result.skipped.append(unit["id"])
            finished[unit["id"]].set_result(False)
            return
        async with _Slot(slots) as slot:
            outcome = await run.work(unit, slot)
        if outcome is None:  # parked: a person must answer first, so its dependents wait (skipped)
            result.parked.append(unit["id"])
            finished[unit["id"]].set_result(False)
            return
        await run.review(unit, outcome)  # after the slot is free; dependents wait for it
        if unit["id"] in run.held:  # a person's Hold (or the default) kept it from running: dependents are skipped
            result.held.append(unit["id"])
            finished[unit["id"]].set_result(False)
            return
        result.outcomes[unit["id"]] = outcome
        finished[unit["id"]].set_result(outcome.success)

    try:
        async with asyncio.TaskGroup() as group:
            for unit in order:
                group.create_task(unit_task(unit))
    except ExceptionGroup as errors:  # e.g. WriterBusy or EventRejected: stop the run, raise it plainly
        raise errors.exceptions[0] from None
    return result
