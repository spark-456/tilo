"""The run after approve (CL-INT-2; PRD 5.4 CP2, 8.5, 9.4, 10.3, 10.4; services/api/tests/API_CL_INT_2.md; BQ-90).
The approved plan runs only if `validate_plan` accepts it. A unit's send goes through the policy engine and waits
at a gate card until a person approves; only then does the outbox send it, once. Every event goes through the
single writer, each built once with its own id; a paused world gets nothing more from the run."""

from __future__ import annotations

import asyncio
import copy
import dataclasses
import logging
import math
import threading
import time
import unicodedata
from collections.abc import Callable, Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Annotated, Any, Literal

import tilo_planning.plangraph as plangraph
import tilo_policy
from fastapi import APIRouter, Depends, HTTPException, Request
from tilo_connectors import Outbox, OutboxRefused
from tilo_harness.config import load_agents_config
from tilo_harness.executor import UnitOutcome, run_plan
from tilo_harness.must_ask import MustAsk
from tilo_harness.question_wait import AlreadyAnswered, QuestionWait
from tilo_harness.validator import repo_validator
from tilo_memory.artifacts import Scope
from tilo_planning.compiler import DELIVER, PlanInputs

from tilo_api import deps, events, team_access, team_store
from tilo_api.access import Mode
from tilo_api.cards import (
    OWNER_ONLY_ACTIONS,
    AlreadyCommitted,
    CardStore,
    _card_errors,
    answering_principal,
    get_channels_caller,
)

logger = logging.getLogger("tilo_api.runs")
router = APIRouter()

_TIERS = ("T1", "T2", "T3")
_FORMATS = {"send_email": "email"}  # the deliverable_format a send action delivers
_GATE_TIMEOUT_S = 86_400  # BQ-90: then the card holds; a gate never times out to go
_POLL_S = 0.25  # how often a waiting gate looks for an answer or a pause
_EXACT_MAX = 500  # card.schema.json: gate.action.exact
_SEND_RETRY_DELAYS_S = (0.0, 0.2, 0.5, 1.0, 2.0, 2.0)  # FR-AGT-11: the send step is retried, never resent
_RECORDS = ("artifact.created", "artifact.versioned", "artifact.rolled_back")  # the events that record a version


class _WallClock:
    def now(self) -> str:
        return events.now()


_CLOCK = _WallClock()


@dataclass(frozen=True)
class MeteredOutcome(UnitOutcome):
    """A unit's outcome plus the credits its work metered (PRD 14.1); recorded on the unit's first announced item."""

    credits: float = 0.0


class RunStopped(Exception):
    """The world is paused: the run writes nothing more."""


class _GateFailed(Exception):
    """The gated step could not finish; its unit fails."""


@dataclass(frozen=True)
class Seams:
    compiler: Callable[..., dict]
    layout_builder: Callable[..., dict]
    runner: Any
    resolver: Callable[..., dict]
    skills: Any
    connectors: Any
    adapters: dict[str, Any]
    outbox_store: Any
    writer: deps.EventWriter
    must_ask_providers: Mapping[str, Any]
    artifacts: Any  # tilo_memory.artifacts.ArtifactStore (ADR-0018 T4)
    redactor: Callable[[str], str]  # the shared secret redactor the store was given
    open_archive: Callable[..., Any]  # (*, org_id, run_id) -> the run's tilo_archive.RunArchive
    team: Callable[
        [], Any
    ]  # the team's settings (FR-ACC-01; team_store.team_reader): no default, every path passes one


_MODE_SEAMS = frozenset({"plan_compiler", "unit_runner", "must_ask_providers"})  # the seams that build a Router


def run_seams(request: Request, mode: Annotated[Mode, Depends(deps.get_work_mode)]) -> Seams | None:
    """The seams as the app wires them, overrides included; if any cannot be built, no run starts. The model
    seams get this request's mode (SEC-15), so a judge's run is live and everyone else's is replay."""
    overrides = request.app.dependency_overrides
    names = "plan_compiler layout_builder unit_runner action_resolver skill_registry connector_registry"
    names += " connector_adapters outbox_store event_writer must_ask_providers artifact_store redactor run_archive"

    from tilo_api import ephemeral  # noqa: PLC0415

    demo = None if ephemeral.has_no_person(request) else ephemeral.for_request(request)  # the tick has no person
    mine = (  # the storage seams a demo run takes from its own bundle; connector adapters stay empty: it sends nothing
        {}
        if demo is None
        else {
            "outbox_store": demo.outbox, "event_writer": demo.writer, "artifact_store": demo.artifacts,
            "redactor": demo.redactor, "run_archive": demo.open_archive, "connector_adapters": {},
        }
    )  # fmt: skip

    def build(name: str) -> Any:
        seam = getattr(deps, f"get_{name}")
        if seam in overrides:
            return overrides[seam]()
        if name in mine:
            return mine[name]
        return seam(mode) if name in _MODE_SEAMS else seam()

    try:
        built = dict(
            zip([f.name for f in dataclasses.fields(Seams) if f.name != "team"], map(build, names.split()), strict=True)
        )
        return Seams(**built, team=team_store.team_reader(overrides))
    except Exception as exc:
        logger.warning("the run seams are not wired, so no run starts: %s", type(exc).__name__)
        return None


def _tool_access(seams: Any, connector: str, action: str, tier: str, skill_ids: Any = ()) -> None:
    """FR-ACC-01/02: the team's level for this tool, lowered by the unit's skills' `tool_access` (never raised); a
    refusal or a store that cannot be read fails the step."""
    try:
        lowest = team_access.skill_level(seams.skills, skill_ids, connector) if skill_ids else None
        access = team_access.tool_check(
            seams.team(), connector, action, tier, registry=seams.connectors, skill_level=lowest
        )
    except Exception as exc:
        raise _GateFailed("tool access could not be checked") from exc
    if access == "block":
        raise _GateFailed("tool access does not allow this step")


def start_run(store: deps.Store, task: deps.TaskRecord, *, approach: dict, budget_cap: float, seams: Seams) -> None:
    store.settle(task.world_id)  # the queued events go out first, so `world.started` follows them
    with store.runs_guard:  # one run per world, in any process: a started world's stream says so (ADR-0026 decision 5)
        started = any(e["type"] == "world.started" for e in store.events.get(task.world_id, []))
        if task.world_id in store.runs or started:
            return
        run = store.runs[task.world_id] = Run(store, task, approach, budget_cap, seams)
    threading.Thread(target=run.main, name=f"run-{task.world_id}", daemon=True).start()


def _plain(card: dict) -> dict:
    """The card without control, format and surrogate characters in the text a model may have written."""

    def clean(text: str) -> str:
        return "".join(c for c in text if unicodedata.category(c) not in ("Cc", "Cf", "Cs"))

    options = [{**o, **{k: clean(o[k]) for k in ("label", "reason") if k in o}} for o in card["options"]]
    return {**card, "what_happened": clean(card["what_happened"]), "why_it_matters": clean(card["why_it_matters"]),
            "options": options}  # fmt: skip


class _NoCards:
    def write(self, part: dict) -> None:
        raise RuntimeError("a world with no run holds no cards")


class _ObservedWait(QuestionWait):
    """The run's `QuestionWait`, which also says when a unit is asleep waiting for a person's answer (FR-AGT-14e)."""

    def __init__(self, run: Run) -> None:
        super().__init__(run)
        self._run = run

    async def wait_for(self, card: dict[str, Any], *, lead: str, director: str, district: str | None) -> Any:
        with self._run.asleep():
            return await super().wait_for(card, lead=lead, director=director, district=district)


class Run:
    """Also the executor's writer (`emit`, `org_id`, `world_id`, `recorded_version`) and its CardStore's (`write`):
    both end at the single writer."""

    owner_started: frozenset[str] = OWNER_ONLY_ACTIONS  # FR-MTG-09: no plan names it, only the owner starts it

    def __init__(self, store: deps.Store, task: deps.TaskRecord, approach: dict, cap: float, seams: Seams) -> None:
        self.store, self.seams, self.cap, self.approach = store, seams, cap, copy.deepcopy(approach)
        self.org_id = deps.ORG_ID  # the run's artifact Scope is (org_id, world_id, owner); never a request's
        self.scope: Scope | None = None  # set when the run starts
        self.world_id, self.run_id, self.owner, self.brief = task.world_id, task.run_id, task.owner, task.brief
        self.intake_answers = (
            tuple(  # (the Director's question, the person's answer) for the units' prompts (UNIT-PROMPT)
                (q.text, str(task.answers[q.field]))
                for q in task.questions
                if task.answers.get(q.field) and q.field not in task.edits
            )
        )
        self.approaches = copy.deepcopy(task.approaches or [])
        self.cards = CardStore(clock=_CLOCK, writer=self, world_owners={self.world_id: self.owner})
        self.question_wait = _ObservedWait(self)  # a unit that asked a person waits here for the answer (FR-HIL-10)
        self.plan: dict[str, Any] = {}
        self.layout: dict[str, Any] = {}
        self.levels: dict[str, str] = {}
        self.director = "system"
        self.requested: dict[str, dict] = {}  # card_id -> approval.requested
        self.resolved: dict[str, dict] = {}  # card_id -> approval.resolved
        self.reraised: dict[str, str] = {}  # a share's new card id -> the gate card it re-raised (FR-HIL-12)
        self.sends: dict[str, dict[str, Any]] = {}  # outbox_id -> what its data.transfer needs
        self.titles: dict[str, str] = {}  # artifact_id -> the delivering unit's title
        self.delivered: list[str] = []  # artifact.delivered event ids
        self.produced: dict[str, list[tuple[dict, dict, str]]] = {}  # unit id -> (unit, item, its announcing event id)
        self._built: dict[str, dict] = {}  # event id -> the event as first built, resent as is on an exact retry
        self.failure: str | None = None
        self._failed = False
        # What `wait_until_parked_or_done` looks at (FR-AGT-14e). Written from the run's thread, read from any thread.
        self._ended = threading.Event()  # the run's thread has finished, whichever way out
        self._seen = threading.Lock()
        self._unit_of: dict[str, str] = {}  # worker -> the unit it was assigned
        self._started: set[str] = set()  # units that were assigned
        self._live: set[str] = set()  # assigned and not yet retired
        self._handed: set[str] = set()  # units that handed their result over (their dependents may start)
        self._asleep = 0  # live units waiting for a person: a gate card or a question

    def now(self) -> datetime:
        return datetime.now(UTC)

    def paused(self) -> bool:
        world = self.store.worlds.get(self.world_id)
        return world is None or world.paused

    def put(self, type_: str, actor: str, target: str, summary: str, data: dict, **kw: Any) -> dict:
        """Builds the event once, with its own id, and appends it through the single writer. A paused world gets
        nothing (FR-WLD-07), except the record of a person's answer or of a send that already happened."""
        if kw.get("check_pause", True) and self.paused():
            raise RunStopped
        district = kw.get("district")
        vis = kw.get("vis", [district] if district else "all")  # a district's event is that district's (PRD 10.1)
        if vis is None:
            raise ValueError("an event's vis is never widened")
        event = {
            "id": kw.get("event_id") or events.new_part_id(), "type": type_, "actor": actor, "target": target,
            "level": self.levels.get(district) if district else None, "district": district, "item": kw.get("item"),
            "severity": kw.get("severity") or repo_validator().registry_types[type_]["default_severity"],
            "credits": kw.get("credits", 0), "summary": summary[:140], "cause": kw.get("cause"), "vis": vis,
            "authz": kw.get("authz"), "data": data,
        }  # fmt: skip
        if not kw.get("event_id"):
            return self.seams.writer.append(self.world_id, event)
        same = ("type", "actor", "target", "data", "authz", "cause")
        first = self._built.get(event["id"])  # a retried id: an event with the same content is the first, as built
        if first is not None and all(first[k] == event[k] for k in same + ("vis", "district", "severity")):
            event = first
        else:
            self._built[event["id"]] = copy.deepcopy(event)
        try:
            return self.seams.writer.append(self.world_id, event)
        except Exception:
            # An id already committed under other content means an earlier answer won although its caller saw a
            # failure (any other error, an identical committed event included, is the caller's to retry).
            stream = list(self.store.events.get(self.world_id, []))
            committed = next((e for e in stream if e["id"] == event["id"]), None)
            if committed is None or all(committed[k] == event[k] for k in same):
                raise
            raise AlreadyCommitted(committed) from None

    def metered(self, credits: Any) -> float:
        """A unit's credits, finite and at least 0, and never more than the approved budget still leaves (the sum of
        the run's event credits is the meter, HR-1)."""
        if isinstance(credits, bool) or not isinstance(credits, int | float) or not math.isfinite(credits):
            return 0
        spent = math.fsum(e["credits"] for e in self.store.events.get(self.world_id, []))
        return max(0, min(credits, self.cap - spent))

    def recorded_version(self, artifact_id: str) -> int:
        """The highest version of `artifact_id` this world's stream recorded (EV-15), 0 if none."""
        stream = list(self.store.events.get(self.world_id, []))
        versions = (e["data"]["artifact"] for e in stream if e["type"] in _RECORDS)
        return max((ref["version"] for ref in versions if ref["artifact_id"] == artifact_id), default=0)

    def emit(self, *, type: str, actor: str, target: str, summary: str, data: dict, **kw: Any) -> dict:
        """The executor's events. A unit's credits ride on its first announced item, clamped by `metered`."""
        keys = ("district", "cause", "vis", "severity", "event_id", "item")
        passed: dict[str, Any] = {k: kw[k] for k in keys if k in kw}
        if kw.get("credits"):
            passed["credits"] = self.metered(kw["credits"])
        defaulted = type == "question.answered" and data.get("answered_by") == "default"
        try:
            event = self.put(type, actor, target, summary, data, **passed)
        except AlreadyCommitted:
            if defaulted:  # an answer already committed this card's question: the deadline closes the card as well
                self._close_defaulted()
            raise
        self._observe(type, actor, target, data)
        if defaulted:
            self._close_defaulted()  # the harness applied a deadline default: close that card here too (BQ-208)
        return event

    def _observe(self, type_: str, actor: str, target: str, data: dict) -> None:
        """Which units are at work: assigned, handed over and retired are the executor's own events."""
        with self._seen:
            if type_ == "agent.assigned":
                self._unit_of[target] = data["unit"]
                self._started.add(data["unit"])
                self._live.add(data["unit"])
            elif type_ == "agent.handoff" and actor in self._unit_of:
                self._handed.add(self._unit_of[actor])
            elif type_ == "agent.retired":
                self._live.discard(self._unit_of.get(target, ""))

    @contextmanager
    def asleep(self) -> Iterator[None]:
        """A live unit is waiting for a person (a gate card or a question) from here until the block ends."""
        with self._seen:
            self._asleep += 1
        try:
            yield
        finally:
            with self._seen:
                self._asleep -= 1

    def _quiet(self) -> bool:
        """Nothing goes on until a person answers: someone waits for one, every live unit is that waiting, and no unit
        is about to start (not started, every dependency handed over). A paused world is winding down, not waiting."""
        if self.paused():
            return False
        with self._seen:
            if self._asleep == 0 or len(self._live) != self._asleep:
                return False
            units = self.plan.get("units", [])
            return not any(
                u["id"] not in self._started and all(d in self._handed for d in u["depends_on"]) for u in units
            )

    def wait_until_parked_or_done(
        self, timeout_s: float, *, clock: Callable[[], float] = time.monotonic, poll_s: float = 0.25
    ) -> Literal["done", "parked", "timeout"]:
        """FR-AGT-14e: for a Cloud Tasks delivery, which holds a request only while the run works. "done": the run's
        thread has ended. "parked": the run is quiet at a person (see `_quiet`), never while a unit computes.
        "timeout": `timeout_s` of `clock()` passed. The run itself is untouched either way."""
        deadline = clock() + timeout_s
        while True:
            if self._ended.is_set():
                return "done"
            if self._quiet():
                return "parked"
            if clock() >= deadline:
                return "timeout"
            self._ended.wait(poll_s)

    def _close_defaulted(self) -> None:
        try:
            self.cards.tick()
        except Exception:  # the resolution is committed; a card that failed to close stays in tick's work set
            logger.warning("a card could not be closed after its deadline default", exc_info=True)

    def committed(self, event_id: str) -> dict | None:
        """The event of this run already committed under `event_id`, if any (QuestionWait asks, #338)."""
        return next((e for e in self.store.events.get(self.world_id, []) if e["id"] == event_id), None)

    def write(self, part: dict) -> None:
        """The CardStore's part for a person's answer; an approve opens the waiting gate, an answer resumes its unit."""
        if part["type"] == "question.answered":
            try:
                self.question_wait.write(part)  # commits it through `emit` under the part's id, then resumes the unit
            except AlreadyAnswered:
                raise AlreadyCommitted from None  # the deadline default (or an earlier answer) won: the card closes
            return
        data, card_id, authz = part["data"], part["card_id"], part["authz"]
        requested = self.requested.get(card_id)
        shared = part["type"] == "approval.requested"  # FR-HIL-12: the owner shared a gate; a pause stops it like any
        summary = (
            "The gate was shared with an Approver."
            if shared
            else f"The gate card was answered: {data.get('option', 'default')}."
        )
        origin = self.requested.get(
            part.get("reraised_from", "")
        )  # a re-raise is the original proposal's again (Trace)
        who = origin["actor"] if origin else authz["ref"] if authz else "system"
        try:
            committed = self.put(
                part["type"], who, data.get("gate_id", self.world_id),
                summary, data, district=part["district"],
                cause=(origin or requested or {}).get("id"), authz=authz, vis=part["vis"],
                severity=part.get("severity"),
                check_pause=shared, event_id=part["event_id"],  # one id per resolution: a retry is an identical resend
            )  # fmt: skip
            if shared:
                self.requested[card_id], self.reraised[card_id] = committed, part["reraised_from"]
        except AlreadyCommitted as exc:
            # The card resolves under the committed event (its authz opens the gate), never a second one.
            if part["type"] == "approval.resolved":
                self.resolved[card_id] = exc.args[0]
            raise
        if part["type"] == "approval.resolved":
            self.resolved[card_id] = committed

    def _fail(self, reason: str, unit: str | None) -> None:
        try:
            if not (self._failed or self.paused()):
                self._failed = True
                self.put(
                    "world.failed", "system", self.world_id, f"Stopped: {reason}", {"reason": reason, "unit": unit}
                )
        except Exception:
            logger.exception("run %s could not record its failure", self.run_id)

    def main(self) -> None:
        """Every way out ends in a terminal event (or the pause) and leaves no entry of the run waiting to send."""
        try:
            asyncio.run(self._execute())
        except RunStopped:
            pass
        except BaseException as exc:  # the outbox re-raises a BaseException from a send; the run still ends
            logger.exception("run %s stopped on an error", self.run_id)
            self._abandon_unsent()
            self._fail("an internal error stopped the work", None)
            if isinstance(exc, KeyboardInterrupt):
                raise
        finally:
            self._abandon_unsent()
            self._ended.set()

    def _outbox(self) -> Outbox:
        """The run dispatches and records only its own world's entries, and claims none once the world is paused
        (FR-WLD-07)."""
        return Outbox(
            self.seams.outbox_store, self.seams.adapters, emit=self._record_transfer, clock=events.now,
            world_id=self.world_id, halted=self.paused,
        )  # fmt: skip

    def _abandon_unsent(self) -> None:
        for outbox_id, send in self.sends.items():
            entry = self.seams.outbox_store.get(outbox_id)
            if "committed" not in send and entry is not None and entry["state"] in ("queued", "scheduled", "sending"):
                try:
                    self._outbox().abandon(outbox_id)
                except Exception:
                    logger.warning("run %s left entry %s to its sender", self.run_id, outbox_id)

    def _compile(self, context: PlanInputs) -> dict:
        return self.seams.compiler(
            brief=copy.deepcopy(self.brief), approach=self.approach, budget_cap=self.cap, context=context
        )

    def _must_ask(self, config: Any) -> MustAsk | None:
        return MustAsk(
            self.seams.must_ask_providers, config=config, card_sink=self._store_card, owner=self.owner,
            covered_actions={p["action_type"] for p in self.store.policies.values() if p.get("owner") == self.owner},
        )  # fmt: skip

    def _prepare(self) -> Any:
        """Compile, validate, lay out. Returns the agents config, or None when no run may start."""
        registry = self.seams.connectors
        try:  # the policy context and the PI-11 history are read across all of the owner's worlds
            self.store.load_owner(self.owner, settle=True)
        except Exception as exc:
            logger.warning("run %s: the owner's records could not be read (%s)", self.run_id, type(exc).__name__)
            self._fail("the owner's records could not be read", None)
            return None
        try:
            context = PlanInputs(
                approaches=copy.deepcopy(self.approaches), owner=self.owner, skills=dict(self.seams.skills.catalog()),
                connectors={c: registry.get(c) for c in registry.ids()}, risk_table=tilo_policy.load_risk_table(),
                policies=dict(self.store.policies),
            )  # fmt: skip
            plan = self._compile(context)
        except Exception as exc:
            logger.warning("run %s: no plan (%s)", self.run_id, type(exc).__name__)
            self._fail("the Director could not plan this task", None)
            return None
        violations = plangraph.validate_plan(
            plan, risk_table=context.risk_table, connectors=context.connectors, skills=frozenset(context.skills),
            policies=context.policies, owner=self.owner,
        )  # fmt: skip
        if violations:
            self._fail("the plan broke " + ", ".join(sorted({v.rule_id for v in violations})), None)
            return None
        if self.owner_started & {action for unit in plan["units"] for action in unit["actions"]}:
            self._fail("the plan names an action only its owner can start", None)  # FR-MTG-09: never a planned unit
            return None
        try:
            self.layout, config = self.seams.layout_builder(plan, world_id=self.world_id), load_agents_config()
            if (record := self.store.worlds.get(self.world_id)) is not None:
                record.layout = self.layout  # before `world.started`: the event writer validates against it (ADR-0026)
                try:
                    self.store.commit(worlds={self.world_id: record}, evict=False)  # durable: the layout is stored too
                except Exception:
                    record.layout = None  # the record stays cached, as it was, for the run's `world.failed`
                    raise
        except Exception:
            self._fail("the world could not be laid out", None)
            return None
        self.plan, semantic = plan, self.layout["semantic"]
        self.levels = {d["id"]: level["id"] for level in semantic["levels"] for d in level["districts"]}
        self.director = next((a["id"] for a in semantic["agents"] if a["rank"] == "director"), "system")
        return config

    async def _execute(self) -> None:
        config = self._prepare()
        if config is None:
            return
        try:  # the run's own Scope and raw archive (ADR-0018 T4); never named by a request
            self.scope = scope = Scope(org_id=self.org_id, world_id=self.world_id, owner=self.owner)
            archive = self.seams.open_archive(org_id=self.org_id, run_id=self.run_id)
        except Exception as exc:
            logger.warning("run %s: no artifact scope or archive (%s)", self.run_id, type(exc).__name__)
            self._fail("the run's item store could not be opened", None)
            return
        stream = self.store.events.get(self.world_id, [])
        granted = next((e["id"] for e in reversed(stream) if e["type"] == "budget.granted"), None)
        summary = f"Work started with a budget of {self.cap:g} credits."
        self.put("world.started", self.director, self.world_id, summary, {"budget_cap": self.cap}, cause=granted)
        must_ask = self._must_ask(config)
        planned = asyncio.ensure_future(
            run_plan(
                self.plan,
                self.layout,
                writer=self,
                config=config,
                skills=self.seams.skills,
                runner=self.seams.runner,
                must_ask=must_ask,
                question_wait=self.question_wait,
                artifacts=self.seams.artifacts,
                scope=scope,
                archive=archive,
                redact=self.seams.redactor,
                before_handoff=self.before_handoff,
                brief=copy.deepcopy(self.brief),
                intake_answers=self.intake_answers,
            )  # fmt: skip
        )
        while not planned.done():  # a unit waiting for a person must not outlive a pause
            await asyncio.wait({planned}, timeout=_POLL_S)
            if self.paused():
                planned.cancel()
                raise RunStopped
        result = planned.result()
        if result.parked:  # waiting for a person: neither done nor failed
            return
        if stopped := result.failed + result.held + result.skipped:
            reason = "a step was held, so the work stopped" if result.held and not result.failed else None
            self._fail(self.failure or reason or "a unit failed, so the work stopped", stopped[0])
            return
        credits = math.fsum(e["credits"] for e in self.store.events.get(self.world_id, []))  # the meter (HR-1)
        data = {"credits_used": credits, "deliverable_count": len(self.delivered)}
        cause = self.delivered[-1] if self.delivered else None
        self.put("world.completed", self.director, self.world_id, "The work is done.", data, cause=cause)

    def _store_card(self, card: dict) -> None:
        """The question card goes to this run's CardStore with its unit's district, before anything
        names it. Never merged: its unit waits for an answer to this question (#338)."""
        building = card["header"]["building"]
        districts = (d["id"] for level in self.layout["semantic"]["levels"] for d in level["districts"]
                     if any(b["id"] == building for b in d["buildings"]))  # fmt: skip
        district = next(districts, None)
        card = _plain(card)
        if district is None or self.cards.submit(card, district=district, merge=False).outcome == "rejected":
            raise RuntimeError("the question card was refused")

    async def before_handoff(self, unit: dict, worker: str, announced: list[tuple[dict, str]]) -> bool:
        """The executor stored and announced the unit's items (ADR-0018 T4). A unit with actions stops at its gate (the
        item to send is its first announced version); a `deliver` unit with none delivers in Tilo. False fails it."""
        self.produced[unit["id"]] = [(unit, dict(ref), made) for ref, made in announced]
        try:
            for action in unit["actions"]:
                if not announced:
                    raise _GateFailed("the step had nothing to send")
                await self.gate(unit, worker, action, *announced[0])
        except _GateFailed as exc:
            self.failure = str(exc)
            return False
        if unit["unit_type"] == DELIVER and not unit["actions"]:  # a deliver unit that sends delivers at its gate
            self.deliver_in_app(unit, worker)
        return True

    async def gate(self, unit: dict, worker: str, action: str, ref: dict, made: str) -> None:
        """PRD 10.3/10.4: the policy engine assesses the send, a person approves it, the outbox sends it once."""
        item, district = {"artifact_id": ref["artifact_id"], "version": ref["version"]}, unit["district"]
        gate = next((g for g in self.plan["gates"] if unit["id"] in g["guards"] and g["action_type"] == action), None)
        connector = next((c for c in unit["connectors"] if self._action(c, action)), None)
        if gate is None or connector is None:
            raise _GateFailed(f"no gate or connector for {action}")
        try:
            brief, unit_copy = copy.deepcopy(self.brief), copy.deepcopy(unit)
            to = self.seams.resolver(unit=unit_copy, action_type=action, item=dict(item), brief=brief)
            recipients, destination, known = to["recipients"], to["destination"], to.get("known_recipients")
        except Exception as exc:
            raise _GateFailed("the send has no recipients") from exc
        if not (isinstance(destination, str) and destination.strip() and isinstance(recipients, list) and recipients
                and all(isinstance(r, str) and r.strip() for r in recipients)):  # fmt: skip
            raise _GateFailed("the send has no recipients or no destination")  # fails closed, before any gate
        try:  # AR-07, OB-05, BQ-264: from the stored record, never a default; only a `clean` verdict clears the flag
            flagged = self.seams.artifacts.head(self.scope, item).record["screening"] != "clean"
        except Exception as exc:
            raise _GateFailed("the item to send is not in the run's store") from exc
        facts = tilo_policy.SideEffectFacts(
            recipients=tuple(recipients), known_recipients=tuple(known or ()), safety_flags=flagged
        )
        proposal = tilo_policy.Proposal(self.world_id, action, connector, district, destination, facts, item, 0, None)
        table = tilo_policy.load_risk_table()
        assessed = max(table.assess(action, facts).tier, gate["risk_tier"], key=_TIERS.index)
        skills = unit.get("skills") or ()
        _tool_access(self.seams, connector, action, assessed, skills)  # FR-ACC-01/02: before the engine; only refuses
        decision = tilo_policy.decide(
            proposal, table=table, policies=list(self.store.policies.values()),
            world_owner=self.owner, applied=self._applied(), now=events.now(),
        )  # fmt: skip
        if decision.outcome == "draft_only":  # an owner's L0 policy: nothing leaves Tilo (PRD 10.4, BQ-90)
            self._deliver(unit, worker, item, {"artifact": item, "format": "in_app", "outbox_id": None}, made)
            return
        tier = max(decision.tier, gate["risk_tier"], key=_TIERS.index)  # never below the plan's gate (PG-06)
        irreversible = self._action(connector, action)["irreversible"]  # type: ignore[index]
        card_id, outbox_id = events.new_part_id(), events.new_part_id()
        card = self._gate_card(unit, worker, card_id, gate["id"], connector, action, tier, irreversible)
        exact = self._exact(connector, action, destination, recipients)
        if len(exact) > _EXACT_MAX:  # never cut: a cut would hide a recipient from the person approving
            raise _GateFailed("the send names too many recipients to show on one card")
        card["gate"]["action"] |= {"item": ref, "destination": destination, "exact": exact}
        card["gate"]["recipients"] = recipients
        if _card_errors(card):  # checked before anything is written
            raise _GateFailed("the gate card was refused")
        data = {
            "gate_id": gate["id"], "card_id": card_id, "outbox_id": outbox_id, "action_type": action,
            "risk_tier": tier, "irreversible": irreversible, "item": item, "approver": None, "team_lead": None,
        }  # fmt: skip
        summary = "The agent is waiting at a gate for approval."
        requested = self.put("approval.requested", worker, gate["id"], summary, data, district=district, cause=made)
        self.requested[card_id] = requested
        if self.cards.submit(card, outbox_id=outbox_id, district=district).outcome != "accepted":
            raise _GateFailed("the gate card was refused")
        with self.asleep():  # FR-AGT-14e: a person's approve on any card of this gate
            while (answered := self._answered_card(card_id)) is None:
                if self.paused():
                    raise RunStopped
                await asyncio.sleep(_POLL_S)
        resolved, requested = self.resolved[answered], self.requested[answered]  # the answered card's own proposal
        outbox_id = requested["data"]["outbox_id"]  # a share re-raised the gate under a fresh reservation (FR-HIL-12)
        if self.paused():
            raise RunStopped
        if tilo_policy.open_gate(requested, resolved, world_owner=self.owner).outcome != "run":
            raise _GateFailed("the gate did not open")
        _tool_access(self.seams, connector, action, assessed, skills)  # again at dispatch: a tool turned Off meanwhile
        created = events.now()
        entry = {
            "id": outbox_id, "idempotency_key": f"{self.run_id}:{unit['id']}:{action}:1", "world_id": self.world_id,
            "run_id": self.run_id, "action_type": action, "connector": connector, "recipients": recipients,
            "attachments": [], "item": item, "destination": destination, "modifiers": list(decision.modifiers),
            "risk_tier": tier, "authz": resolved["authz"], "undo_window_s": 0, "scheduled_at": created,
            "state": "queued", "created_at": created,
        }  # fmt: skip
        evidence: dict[str, Any] = {
            "reserved_by": requested, "authorised_by": resolved, "policy": None, "team_lead": None,
            "world_owner": self.owner, "instruction": None, "earlier_applied": [],
        }  # fmt: skip
        island = next((g["between"][1] for g in self.layout["semantic"]["gates"] if g["id"] == gate["id"]), gate["id"])
        self.sends[outbox_id] = {
            "worker": worker, "island": island, "district": district, "cause": resolved["id"],
            "event_id": events.new_part_id(),  # resent unchanged if the outbox retries the transfer
        }  # fmt: skip
        transfer = await self._send(entry, evidence)
        format_ = _FORMATS.get(action, "in_app")  # artifact.delivered: a format kept in Tilo has outbox_id null
        data = {"artifact": item, "format": format_, "outbox_id": outbox_id if format_ == "email" else None}
        self._deliver(unit, worker, item, data, transfer["id"])

    def _answered_card(self, card_id: str) -> str | None:
        """The card of this gate (`card_id` or a re-raise of it) with a committed answer: a gate is one wait."""
        ours = {card_id, *(c for c, origin in list(self.reraised.items()) if origin == card_id)}
        return next((c for c in list(self.resolved) if c in ours), None)

    def _deliver(self, unit: dict, worker: str, item: dict, data: dict, cause: str) -> None:
        delivered = self.put(
            "artifact.delivered", worker, item["artifact_id"], "The item was delivered.", data,
            district=unit["district"], cause=cause,
        )  # fmt: skip
        self.titles[item["artifact_id"]] = unit["title"]
        self.delivered.append(delivered["id"])

    def deliver_in_app(self, unit: dict, worker: str) -> None:
        """BQ-218, FR-CON-10: the items a `deliver` unit (and the units it waits for) really produced are delivered in
        Tilo: no outbound side effect, so no gate. Nothing is made up: a run whose units produced nothing delivers
        nothing and says so (deliverable_count 0)."""
        seen = {e["data"]["artifact"]["artifact_id"] for e in self.store.events.get(self.world_id, [])
                if e["type"] == "artifact.delivered"}  # fmt: skip
        for source in (unit["id"], *unit["depends_on"]):
            for producer, item, made in self.produced.get(source, []):
                if item["artifact_id"] in seen:
                    continue
                seen.add(item["artifact_id"])
                data = {"artifact": item, "format": "in_app", "outbox_id": None}
                self._deliver(producer, worker, item, data, made)

    async def _send(self, entry: dict, evidence: dict[str, Any]) -> dict:
        """Enqueue with the person's authz, then dispatch until the outbox records the entry sent."""
        outbox = self._outbox()
        try:
            outbox.enqueue(entry, evidence)
        except OutboxRefused as exc:
            raise _GateFailed("the outbox refused the send") from exc
        for delay in _SEND_RETRY_DELAYS_S:
            await asyncio.sleep(delay)
            if self.paused():
                raise RunStopped
            await asyncio.to_thread(outbox.dispatch_due)
            state = (self.seams.outbox_store.get(entry["id"]) or {}).get("state")
            if state == "sent" and "committed" in self.sends[entry["id"]]:
                return self.sends[entry["id"]]["committed"]
            if state in ("failed", "cancelled"):
                break
        self._abandon_unsent()  # given up: the entry never sends later in a failed world
        raise _GateFailed("the send could not be confirmed")

    def _record_transfer(self, transfer: dict) -> None:
        """The outbox's own data.transfer for one of this run's entries (the outbox is scoped to this world)."""
        send = self.sends[transfer["data"]["outbox_id"]]
        send["committed"] = self.put(
            "data.transfer", send["worker"], send["island"], "The item crossed the bridge.", transfer["data"],
            district=send["district"], cause=send["cause"], authz=transfer["authz"], event_id=send["event_id"],
            check_pause=False,
        )  # fmt: skip

    def _gate_card(self, unit: dict, worker: str, card_id: str, gate_id: str, connector: str, action: str,
                   tier: str, irreversible: bool) -> dict:  # fmt: skip
        """The deterministic gate card (PRD 10.3): from the plan gate, the connector action and the send."""
        building = next(
            b["id"] for level in self.layout["semantic"]["levels"] for d in level["districts"]
            for b in d["buildings"] if unit["id"] in b["plan_units"]
        )  # fmt: skip
        name, undo = self.seams.connectors.get(connector)["name"], "cannot" if irreversible else "can"
        return {
            "id": card_id, "world_id": self.world_id, "run_id": self.run_id, "kind": "gate", "rung": "gate",
            "header": {"building": building, "agent": worker},
            "what_happened": f"{unit['title']}: the draft is ready."[:140],
            "why_it_matters": f"It goes out by {name} ({action}) and {undo} be undone."[:280],
            "options": [
                {"id": "approve", "label": "Approve", "suggested": False, "irreversible": irreversible},
                {"id": "edit", "label": "Edit first", "suggested": True, "irreversible": False,
                 "reason": "Check the draft and who it goes to once before it is sent."},
                {"id": "hold", "label": "Hold", "suggested": False, "irreversible": False},
            ],
            "add_context": False, "actions": ["show_me"], "answer_channels": ["web", "mobile_web"],
            "created_at": events.now(), "timeout": _GATE_TIMEOUT_S, "safe_default": "hold",
            "gate": {"id": gate_id, "action": {"type": action, "connector": connector, "exact": ""},
                     "irreversible": irreversible, "risk_tier": tier},
            "consent": None,
        }  # fmt: skip

    def _exact(self, connector: str, action: str, destination: str, recipients: list[str]) -> str:
        """What the send does, from the action, connector, destination and recipients only; no model-written text
        (a unit's title is not trusted to describe what is sent)."""
        name = self.seams.connectors.get(connector)["name"]
        return f"{action} by {name} to {', '.join(recipients)} (destination {destination})."

    def _action(self, connector: str, action: str) -> dict | None:
        declared = self.seams.connectors.get(connector)["actions"] if connector in self.seams.connectors else []
        return next((a for a in declared if a["id"] == action), None)

    def _applied(self) -> list[dict]:
        """The owner's policy.applied events in every world, so a policy's daily caps never multiply (PI-11)."""
        worlds = [w for w, record in self.store.worlds.items() if record.owner == self.owner]
        return [e for w in worlds for e in self.store.events.get(w, []) if e.get("type") == "policy.applied"]


def get_card_store(world_id: str, store: Annotated[deps.Store, Depends(deps.get_store)]) -> CardStore:
    """The world's own CardStore, its run's; a world with no run has no cards."""
    if (run := store.runs.get(world_id)) is not None:
        return run.cards
    owners = {world_id: world.owner} if (world := store.worlds.get(world_id)) else {}
    return CardStore(clock=_CLOCK, writer=_NoCards(), world_owners=owners)


def world_owner(world_id: str, store: Annotated[deps.Store, Depends(deps.get_store)]) -> str | None:
    """The path world's record owner; no record, no owner."""
    return world.owner if (world := store.worlds.get(world_id)) is not None else None


def answer_guard(
    world_id: str,
    principal: Annotated[deps.Principal, Depends(deps.get_current_principal)],
    store: Annotated[deps.Store, Depends(deps.get_store)],
    from_channels: Annotated[bool, Depends(get_channels_caller)],
    card_store: Annotated[CardStore, Depends(get_card_store)],
) -> None:
    """Pause all is final for the run (BQ-90): an answer in a paused world changes nothing. The card's world's pause
    decides (BQ-XWORLD-8), checked only for a principal who may answer there, so anyone else gets the route's 404."""
    world = store.worlds.get(world_id)
    if world is None or not world.paused:
        return
    actor = answering_principal(
        principal, world_id, record_owner=world.owner, cards=card_store, from_channels=from_channels
    )
    if actor is not None:
        raise HTTPException(status_code=409, detail="This world is paused; nothing it holds is sent.")


@router.get("/worlds/{world_id}/delivery")
def get_delivery(
    world_id: str,
    principal: Annotated[deps.Principal, Depends(deps.get_current_principal)],
    store: Annotated[deps.Store, Depends(deps.get_store)],
) -> dict[str, Any]:
    """Issue #80's DeliveryResult, for the world's owner only, once `world.completed` is written."""
    world = store.worlds.get(world_id)
    owner = world.owner if world is not None else None
    if principal.world_id != world_id or (principal.role, principal.user_id) != ("owner", owner):
        raise HTTPException(status_code=404)
    stream = store.events.get(world_id, [])
    completed = next((e for e in stream if e["type"] == "world.completed"), None)
    if completed is None:
        raise HTTPException(status_code=409, detail="Nothing is delivered until the work is done.")
    titles = run.titles if (run := store.runs.get(world_id)) else {}
    delivered = [(e["data"]["artifact"], e["data"]["format"]) for e in stream if e["type"] == "artifact.delivered"]
    artifacts = [
        {"id": a["artifact_id"], "title": titles.get(a["artifact_id"], "Delivered item"), "kind": kind,
         "version": a["version"]}
        for a, kind in delivered
    ]  # fmt: skip
    credits = completed["data"]["credits_used"]
    return {"world_id": world_id, "artifacts": artifacts, "credits_used": credits, "time_saved": None}  # FR-MTR-02
