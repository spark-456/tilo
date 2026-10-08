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

With `brief` and `intake_answers` (UNIT-PROMPT) every unit's `UnitContext` carries the brief the run began with and the
person's answers, and the text outputs of the units it depends on (`upstream`); `unit_prompt` shows them as data.

With `verifier` (FR-AGT-12) the layout must hold that verifier-rank agent and it must not work a unit
itself. Once a successful unit has handed over, each artifact it handed over gets one `artifact.reviewed`
(caused by the handoff) before the unit's dependents start; the review result is recorded, not acted on.

With `artifacts` and `scope` (FR-AGT-02, FR-MEM-06; ADR-0018 s5) a successful unit's `outputs` are stored with their
`created` manifests (`outputs.keep`) after the runner returns and before `agent.handoff`, then announced: one
`artifact.created` (or `artifact.versioned` for an output with a `parent`) per version, its data from the store's
record, the unit's credits on the first. Its `artifact_refs` must be versions the store holds in `scope` and the world
recorded (`writer.recorded_version`). The envelope names the stored refs, then those. Any refusal fails the unit with no
artifact event. `scope` must be the writer's org and world, or the plan is refused. Without a store, a unit that returns
outputs fails (nowhere to put them) and its refs pass unchecked. With `before_handoff` (tilo-api's gate), a unit whose
items are announced hands off only if it returns True; False fails the unit.

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
import dataclasses
import functools
import math
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, Protocol

from tilo_logging.context import bound
from tilo_providers.interfaces import GenerateRequest, ModelProvider
from tilo_providers.prompts import load_prompt

from tilo_harness.branch import Checkpoint, hit_summary, reusable_units
from tilo_harness.config import AgentsConfig
from tilo_harness.context_handoff import context_pct, next_spare, note_is_valid, store_note
from tilo_harness.must_ask import Ask, MustAsk
from tilo_harness.outputs import Kept, UnitOutput, existing, keep
from tilo_harness.question_wait import Answer, QuestionWait
from tilo_harness.skills import LoadedSkill, Pins, SkillError, SkillRegistry
from tilo_harness.unit_prompt import UPSTREAM_ITEM_CAP, UpstreamItem, data_line, inputs_text, request_variables
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
    artifact_refs: tuple[dict[str, Any], ...] = ()  # versions that already exist, which the unit selects
    provenance_ids: tuple[str, ...] = ()
    outputs: tuple[UnitOutput, ...] = ()  # what the unit made; the executor stores it (ADR-0018)
    context_share: float | None = None  # share 0..1 of this agent's context window used when run() returned (FR-AGT-09)
    handoff_note: dict[str, Any] | None = None  # a draft handoff note when the agent stops unfinished (FR-AGT-09)


@dataclass(frozen=True)
class UnitContext:
    agent_id: str
    skills: tuple[LoadedSkill, ...]
    answer: Answer | None = None  # the answer to the question this unit asked before it started (FR-HIL-10)
    note: dict[str, Any] | None = None  # the validated note a successor starts from (FR-AGT-09)
    note_ref: dict[str, Any] | None = None  # that note's artifact_ref
    # UNIT-PROMPT: what the unit is told about the task. The brief and the answers are person-supplied text, the
    # upstream results are model text; the prompt shows all of it as data (`unit_prompt`).
    brief: Mapping[str, Any] | None = None  # the brief the run was started with
    intake_answers: tuple[tuple[str, str], ...] = ()  # (the Director's question, the person's answer)
    upstream: tuple[UpstreamItem, ...] = ()  # the units this one depends on, in plan order


class UnitRunner(Protocol):
    async def run(self, unit: Mapping[str, Any], context: UnitContext) -> UnitOutcome: ...


# (unit, worker, [(announced ref, its artifact event id)]) -> whether the unit may hand off (e.g. tilo-api's gate)
BeforeHandoff = Callable[[dict[str, Any], str, list[tuple[dict[str, Any], str]]], Awaitable[bool]]


@dataclass
class RunResult:
    pins: Pins
    outcomes: dict[str, UnitOutcome] = field(default_factory=dict)
    skipped: list[str] = field(default_factory=list)
    parked: list[str] = field(default_factory=list)  # waiting for a person's answer (FR-AGT-05)
    held: list[str] = field(default_factory=list)  # answered, and the answer leaves the unit unrun (FR-HIL-10)
    reused: list[str] = field(default_factory=list)  # taken from the parent run's checkpoint, not run (FR-MEM-11)

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
                "title": data_line(unit["title"], 120),
                "unit_type": data_line(unit["unit_type"], 80),
                "skills": "\n\n".join(skill.body for skill in context.skills),
                "inputs": inputs_text(context.upstream),
                **request_variables(context.brief, context.intake_answers),
            },
        )
        response = await asyncio.to_thread(provider.generate, GenerateRequest(prompt=prompt))
        if not response.text:
            return UnitOutcome(success=False, summary=f"No result for {unit['title']}.")
        # Code picks the media type; a model never names one (ADR-0018 s1).
        output = UnitOutput(media_type="text/markdown", content=response.text.encode("utf-8"))
        return UnitOutcome(success=True, summary=f"Finished {unit['title']}.", outputs=(output,))


@dataclass(frozen=True)
class _Roster:
    director: str
    leads: dict[str, str]  # district -> Lead
    levels: dict[str, str]  # district -> level
    workers: dict[str, str]  # unit -> worker agent
    sites: dict[str, str]  # unit -> building
    ranks: dict[str, str] = field(default_factory=dict)  # agent -> rank, in layout order (FR-AGT-09 successors)


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
    return _Roster(directors[0], leads, levels, workers, sites, rank)


NL2 = chr(10) * 2


def _upstream_item(
    unit: Mapping[str, Any], outcome: UnitOutcome, made: Sequence[Kept], store: Mapping[str, Any] | None
) -> UpstreamItem:
    """What a finished unit hands to the units that depend on it: the text of what it STORED (so the redacted version,
    never the runner's raw bytes), cut to the cap now; a flagged or unreadable item is left out with a note."""
    texts: list[str] = []
    for item in made:
        record = item.version.record
        if not str(record.get("media_type", "")).startswith("text/"):
            continue
        if record.get("screening") == "flagged":
            texts.append("(an item was left out: the safety screen flagged it)")
            continue
        try:
            raw = store["artifacts"].read(store["scope"], item.version.ref) if store else b""
        except Exception:  # an unreadable version is left out, never guessed at
            texts.append("(an item was left out: it could not be read)")
            continue
        texts.append(raw[: UPSTREAM_ITEM_CAP * 4].decode("utf-8", errors="replace")[:UPSTREAM_ITEM_CAP])
    refs = tuple(
        str(ref["artifact_id"]) for ref in outcome.artifact_refs if isinstance(ref, Mapping) and "artifact_id" in ref
    )
    return UpstreamItem(unit["id"], unit["title"], NL2.join(texts)[:UPSTREAM_ITEM_CAP] or None, refs)


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
        store: dict[str, Any],
        before_handoff: BeforeHandoff | None,
        handoff_at: float = 1.0,
        brief: Mapping[str, Any] | None = None,
        intake_answers: Sequence[tuple[str, str]] = (),
    ) -> None:
        self.writer, self.roster, self.skills, self.pins, self.runner = writer, roster, skills, pins, runner
        self.must_ask, self.verifier, self.question_wait = must_ask, verifier, question_wait
        self.store = store  # artifacts, scope, archive, redact, max_attempts, recorded (ADR-0018); empty without one
        self.before_handoff = before_handoff
        self.handoff_at = handoff_at  # config.context.handoff_at: a handoff is valid from this share (FR-AGT-09)
        self.used = {*roster.workers.values(), *([verifier.agent_id] if verifier is not None else [])}  # not spare
        self.held: set[str] = set()
        self.handoffs: dict[str, str] = {}  # unit -> the agent.handoff event that carried its artifacts
        self.brief, self.intake_answers = brief, tuple((str(q), str(a)) for q, a in intake_answers)
        self.results: dict[str, UpstreamItem] = {}  # unit -> what it made, for the units that depend on it

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
            **{k: kw[k] for k in ("item", "credits") if k in kw},
        )
        if (trail := kw.get("trail")) is not None:  # the unit's own events, for its manifest (MF-04, MF-05)
            trail.append(event)
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
        trail: list[dict[str, Any]] = []
        at = {"district": district, "trail": trail}
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
                # A stand-in ask that is not MustAsk's (the pinned FR-HIL-10 doubles) runs on any answer.
                runs, held_by = not isinstance(ask, Ask) or ask.runs(answer), answer
                if not runs and isinstance(ask, Ask) and (follow := self.must_ask.confirmation(ask, answer)):
                    # A model-raised sensitive step: the answer only recorded a choice. Code asks once more.
                    card = self.must_ask.raise_question(
                        follow,
                        writer=self.writer,
                        unit=unit,
                        specialist=worker,
                        lead=lead,
                        director=self.roster.director,
                        district=district,
                        cause=cause,
                    )
                    second = await self.question_wait.wait_for(  # still no slot: the card is raised and waited for
                        card, lead=lead, director=self.roster.director, district=district
                    )
                    runs, held_by = follow.runs(second), second  # the runner still gets the person's first choice
                await slot.take()
                if not runs:
                    self.held.add(unit_id)
                    why = (
                        "nobody answered in time, so the safe default"
                        if held_by.answered_by == "default"
                        else "the answer"
                    )
                    summary = f"The agent left without starting: {why} held this step."
                    self.emit("agent.retired", lead, worker, summary, {}, cause=cause, **at)
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
            upstream = tuple(self.results[dep] for dep in unit["depends_on"] if dep in self.results)
            first = UnitContext(
                worker, loaded, answer, brief=self.brief, intake_answers=self.intake_answers, upstream=upstream
            )
            outcome, worker, cause = await self.run_agents(unit, first, site, cause, at)  # a successor may finish it
        made: list[Kept] = []
        if outcome.success is True:
            outcome, made = await self.keep(unit, worker, outcome, trail)
        envelope = _envelope(outcome, worker, lead, unit) if outcome.success is True else None
        if envelope is None and outcome.success is not False:
            outcome = UnitOutcome(success=False, summary="The unit's result was not a valid handoff.")
        if envelope is not None:
            credits = getattr(outcome, "credits", 0)  # the unit's credits ride on its first item (HR-1: the meter)
            announced = [
                (item.version.ref, self.announce(item, worker, cause, district, credits if index == 0 else 0))
                for index, item in enumerate(made)
            ]
            if self.before_handoff is not None and not await self.before_handoff(unit, worker, announced):
                outcome = UnitOutcome(success=False, summary="The unit's step before its handoff did not finish.")
                envelope = None
        if envelope is not None:
            summary = "The agent handed its result to the Lead."
            try:
                cause = self.emit("agent.handoff", worker, lead, summary, {"envelope": envelope}, cause=cause, **at)
            except EventRejected:  # the writer refused the handoff and wrote nothing: this unit fails
                outcome = UnitOutcome(success=False, summary="The unit's result was not a valid handoff.")
            else:
                self.handoffs[unit_id] = cause
        self.emit("agent.retired", lead, worker, "The agent finished and left.", {}, cause=cause, **at)
        if outcome.success is True:
            self.results[unit_id] = _upstream_item(unit, outcome, made, self.store)
        return outcome

    async def call(self, work: Awaitable[Any]) -> Any:
        """The runner's result, or None if it crashed or cancelled its own work (a cancel of the run itself goes on)."""
        try:
            return await asyncio.ensure_future(work)  # its own task: a runner cancelling "the current task" is itself
        except asyncio.CancelledError:
            task = asyncio.current_task()
            if task is not None and task.cancelling():  # the run itself was cancelled
                raise
        except Exception:  # a runner crash fails this unit closed; the run goes on
            pass
        return None

    async def run_agents(
        self, unit: dict[str, Any], context: UnitContext, site: str, cause: str, at: dict[str, Any]
    ) -> tuple[UnitOutcome, str, str]:
        """Runs the unit. While the agent stops unfinished, the Lead hands the unit on (FR-AGT-09, PRD 8.5): the note is
        checked and stored before anything is announced, then the successor verifies it before it continues.
        Returns the outcome, the agent that ended the unit and the last event."""
        worker, lead, handoffs = context.agent_id, self.roster.leads[unit["district"]], 0
        closed = UnitOutcome(success=False, summary="The handoff could not be completed, so the unit stopped.")
        while True:
            ran = await self.call(self.runner.run(unit, context))
            if not isinstance(ran, UnitOutcome):
                return UnitOutcome(success=False, summary="The unit's work failed."), worker, cause
            if ran.handoff_note is None or ran.success is not True:
                return ran, worker, cause
            note, pct = ran.handoff_note, context_pct(ran.context_share, self.handoff_at)
            successor = next_spare(self.roster.ranks, unit["role"], self.used)
            if pct is None or not note_is_valid(note) or not self.store or successor is None:
                return closed, worker, cause  # nothing handoff-shaped is written
            self.used.add(successor)  # reserved before any await, so a concurrent handoff cannot pick the same spare
            try:
                ref = await asyncio.to_thread(
                    store_note, self.store, self.writer.run_id, unit["id"], worker, note, handoffs
                )
            except Exception:  # a refused or failed put: fail closed, and the unused spare goes back
                self.used.discard(successor)
                return closed, worker, cause
            handoffs += 1

            def say(type_: str, actor: str, target: str, text: str, data: dict[str, Any]) -> str:
                return self.emit(type_, actor, target, text, data, cause=cause, **at)

            started = {"note": ref, "context_pct": pct}
            cause = say("agent.context_handoff_started", worker, worker, "The agent wrote a handoff note.", started)
            cause = say("agent.spawned", lead, successor, "A successor joined the team.", {"role": unit["role"]})
            cause = say("agent.assigned", lead, successor, "The Lead gave it the unit.", {"unit": unit["id"]})
            context = dataclasses.replace(context, agent_id=successor, answer=None, note=note, note_ref=ref)
            check = getattr(self.runner, "verify", None)
            verified = check is not None and await self.call(check(unit, context)) is True
            done = {"predecessor": worker, "note": ref, "verification_passed": verified}
            cause = say("agent.context_handoff_completed", successor, site, "The successor took over.", done)
            say("agent.retired", lead, worker, "The agent handed over and left.", {})
            worker = successor
            if not verified:
                return closed, worker, cause

    def reuse(self, unit: dict[str, Any], checkpoint: Checkpoint) -> UnitOutcome:
        """A unit taken from the checkpoint: one `memory.hit` and nothing else (HR-1: no event, no animation)."""
        finished, worker = checkpoint.units[unit["id"]], self.roster.workers[unit["id"]]
        data = {"origin_cost": finished.origin_cost, "lookup_cost": 0, "saved": finished.origin_cost}
        summary, district = hit_summary(finished.origin_cost), unit["district"]
        self.emit("memory.hit", worker, worker, summary, data, district=district, cause=finished.handoff_event_id)
        outcome = UnitOutcome(success=True, artifact_refs=finished.artifact_refs)
        self.results[unit["id"]] = _upstream_item(unit, outcome, (), None)
        return outcome

    async def keep(
        self, unit: dict[str, Any], worker: str, outcome: UnitOutcome, trail: list[dict[str, Any]]
    ) -> tuple[UnitOutcome, list[Kept]]:
        """Stores the outputs and checks the refs (ADR-0018 s5), writing nothing; a failed outcome on any refusal."""
        if not self.store:  # nowhere to put outputs: fail closed; refs pass unchecked as before (tilo-api until T4)
            no_store = UnitOutcome(success=False, summary="The unit made items, but this run has no artifact store.")
            return (no_store if outcome.outputs else outcome), []
        store = self.store
        try:
            credits = getattr(outcome, "credits", 0)
            if isinstance(credits, bool) or not isinstance(credits, int | float) or not 0 <= credits < math.inf:
                raise ValueError("the unit's credits are not a finite number of at least 0")
            selected = existing(store["artifacts"], store["scope"], outcome.artifact_refs, store["recorded"])
            made = await asyncio.to_thread(
                keep, outcome.outputs, run_id=self.writer.run_id, unit=unit, worker=worker, events=list(trail), **store
            )
            stored = [item.version.ref for item in made]
            return dataclasses.replace(outcome, artifact_refs=(*stored, *selected)), made
        except Exception:  # a refused put, manifest or ref, or a backend error: no artifact event for this unit
            return UnitOutcome(success=False, summary="The unit's result could not be stored."), []

    def announce(self, item: Kept, worker: str, cause: str, district: str, credits: float) -> str:
        """One event per stored version, its data from the store's record (ADR-0018 s6): no runner-named id or hash."""
        record, ref = item.version.record, item.version.ref
        if record["parents"]:  # EV-15: created names version 1 only; a later version is recorded as versioned
            type_, summary = "artifact.versioned", "The agent made a new version of an item."
            data = {"artifact": ref, "previous_version": record["parents"][0]["version"]}
        else:
            type_, summary = "artifact.created", "The agent made an item."
            data = {"artifact": ref} | {k: record[k] for k in ("content_sha256", "media_type", "size_bytes")}
        labelled = {"item": {"kind": "document", "artifact_id": ref["artifact_id"], "label": item.label}}
        extra = labelled if item.label is not None else {}
        return self.emit(
            type_, worker, ref["artifact_id"], summary, data, cause=cause, district=district, credits=credits, **extra
        )

    async def review(self, unit: dict[str, Any], outcome: UnitOutcome) -> None:
        if self.verifier is None or unit["id"] not in self.handoffs:
            return
        for ref in outcome.artifact_refs:
            await self.verifier.review_and_record(
                ref, writer=self.writer, cause=self.handoffs[unit["id"]], district=unit["district"]
            )


def _logged_with_run_ids[**P, R](work: Callable[P, Awaitable[R]]) -> Callable[P, Awaitable[R]]:
    """NFR-26: every log line made while the run works carries the run and world ids its writer was opened with
    (a contextvar, so two runs in one process never share them); outside the run there are none.
    `writer` is keyword-only in `run_plan` (a test pins it), so `kwargs` cannot miss a positional one."""

    @functools.wraps(work)
    async def wrapper(*args: P.args, **kwargs: P.kwargs) -> R:
        writer = kwargs.get("writer")
        with bound(run_id=getattr(writer, "run_id", None), world_id=getattr(writer, "world_id", None)):
            return await work(*args, **kwargs)

    return wrapper


@_logged_with_run_ids
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
    artifacts: Any = None,
    scope: Any = None,
    archive: Any = None,
    redact: Callable[[str], str] | None = None,
    before_handoff: BeforeHandoff | None = None,
    reuse: Checkpoint | None = None,
    brief: Mapping[str, Any] | None = None,
    intake_answers: Sequence[tuple[str, str]] = (),
) -> RunResult:
    """`artifacts` (a `tilo_memory.artifacts.ArtifactStore`) comes with the run's `scope`, which must be the writer's
    org and world, and the shared secret `redact`or the store also got; `archive` (`tilo_archive.RunArchive`) is the
    run's raw archive, for manifests. The writer then also says what its world recorded (`recorded_version`).

    With `reuse` (FR-MEM-11) this run is a branch of the checkpoint's parent run (its run id must differ, else
    `ValueError` before any write): a finished, unchanged unit whose dependencies are all reused is not run but
    recorded as one `memory.hit`, a success with the parent's refs, before its dependents start (see `branch`)."""
    if reuse is not None and getattr(writer, "run_id", None) == reuse.parent_run_id:
        raise ValueError("run_plan: a branch needs its own run id, not the parent run's")
    if artifacts is not None:
        if scope is None or redact is None or not callable(getattr(writer, "recorded_version", None)):
            raise PlanRefused(["run_plan: an artifact store needs the scope, the redactor and the world's record"])
        writer_at = (getattr(writer, "org_id", None), getattr(writer, "world_id", None))
        if (getattr(scope, "org_id", None), getattr(scope, "world_id", None)) != writer_at:
            raise PlanRefused(["run_plan: the artifact scope is not the writer's org and world"])
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
    store = {"artifacts": artifacts, "scope": scope, "archive": archive, "redact": redact}
    if artifacts is not None:
        store |= {"max_attempts": config.retries.max_attempts, "recorded": writer.recorded_version}
    run = _Run(
        writer,
        roster,
        skills,
        pins,
        runner,
        must_ask,
        verifier,
        question_wait,
        store if artifacts is not None else {},
        before_handoff,
        config.context.handoff_at,
        brief,
        intake_answers,
    )
    run.spawn_team()
    slots = asyncio.Semaphore(config.limits.max_specialists)
    loop = asyncio.get_running_loop()
    finished: dict[str, asyncio.Future[bool]] = {unit["id"]: loop.create_future() for unit in order}
    if reuse is not None:
        reused = set(reusable_units(reuse, order, getattr(writer, "recorded_version", None)))
        for unit in (u for u in order if u["id"] in reused):
            result.outcomes[unit["id"]] = run.reuse(unit, reuse)
            result.reused.append(unit["id"])
            finished[unit["id"]].set_result(True)

    async def unit_task(unit: dict[str, Any]) -> None:
        if unit["id"] in result.reused:
            return
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
