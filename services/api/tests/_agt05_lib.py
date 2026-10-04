"""Helpers for the FR-AGT-05 / FR-HIL-10 API acceptance tests: the harness's must-ask rules (PRD 8.3, 8.6; merged in
#276, `tilo_harness.must_ask`) enforced end to end through the API's run (`tilo_api.runs.Run`, CL-INT-2). Named
`_agt05_lib` for the same global-bare-module-name reason as `_clint1_lib.py`.

THE WIRING THESE TESTS PIN (the PRD names no API seam; chosen here and logged as BQ-226..BQ-228 in
docs/open-questions.md; a builder implements exactly this in `tilo_api/runs.py` and `tilo_api/deps.py`):

    deps.get_must_ask_providers() -> Mapping[str, ModelProvider]      (a new run seam, like `get_unit_runner`)
        The models `MustAsk` judges with, keyed by role (the shape `DefaultUnitRunner` takes). The default builds a
        `_RoleModel(get_router(), role)` per worker role, so every call goes through the Router and the roles in
        config/models.yaml (PL-01): no model id appears in `services/api/src`. `run_seams` builds it with the others
        (overrides honoured). The tests override it with a scripted provider; one test leaves it alone, replaces
        `deps.get_router` and checks the calls arrive through the Router with the role's own profile.

    Run._execute:  must_ask = MustAsk(providers, config=<agents config>, card_sink=<the run's CardStore>,
                   owner=<the world owner>, covered_actions=<the action types the owner's autonomy policies cover>)
                   and `run_plan(..., must_ask=must_ask)`; `Run` also gives the harness what `raise_question` reads
                   (`layout`, `world_id`, `run_id`, `now()`).
        card_sink submits the needs_you card to the run's own CardStore WITH the unit's district, so the card is
        listed and answered through the existing cards routes, a Team Lead sees only their district's cards
        (FR-HIL-09), and the answer's `question.answered` is vis [district] (an event's vis is never widened).
        The card is stored BEFORE agent.help_requested, agent.escalated and question.routed are emitted (issue #292
        item 2: question.routed must never name a card that was not stored); if the store refuses or raises, none
        of the chain is emitted, the unit's work does not start and the run does not complete.
        A parked unit (`RunResult.parked`) is neither a failure nor a completion: `world.completed` and
        `world.failed` are written only when no unit is waiting for a person (issue #292 item 5).

    FR-HIL-10 (resume): with `tilo_harness.question_wait.QuestionWait` (interface pinned in the harness branch
        tests/FR-HIL-10-harness-resume, `hil_wait_support.py`) the run passes `question_wait=` too. Answering the card
        over the cards route writes `question.answered` and, within 2.0 s, the unit's work runs once with
        `UnitContext.answer` (`card_id`, `option`, `answered_by`), then the rest of the plan and `world.completed`.
        A waiting unit holds nothing back: the other units go on.

Not a test module. Everything is scripted: no model, no network, no live mode (EFF-01).
"""

from __future__ import annotations

import copy
import json
import threading
import time
from typing import Any

from _clint1_lib import FLOW_USER
from _clint2_lib import CAP, REPO_ROOT, RunFlow, ScriptedRunner, base_plan, build_run_flow
from tilo_providers.fake import FakeModelProvider
from tilo_providers.interfaces import GenerateRequest, GenerateResponse

TASKS_PATH = REPO_ROOT / "services" / "harness" / "tests" / "fixtures" / "must_ask" / "tasks.json"
QUESTION_TYPES = ("agent.help_requested", "agent.escalated", "question.routed")
CLEAR_REPLY = json.dumps({"ask": False})
ROLES = ("director", "lead", "specialist", "verifier", "writer", "narrator")
RESUME_BUDGET_S = 2.0  # PRD 10.6 FR-HIL-10


def task(task_id: str) -> dict[str, Any]:
    tasks = json.loads(TASKS_PATH.read_text(encoding="utf-8"))["tasks"]
    return next(t for t in tasks if t["id"] == task_id)


ASK = task("ASK-06")  # "Compare the two vendor quotes": the model asks "Compare on total cost or on delivery time?"
CLEAR = (task("CLR-01"), task("CLR-02"), task("CLR-03"))


class ScriptedProvider(FakeModelProvider):
    """A real `ModelProvider` whose reply is looked up by the longest script key found in the prompt (the harness
    tests' `ScriptedProvider`, restated here because test directories do not share modules). A prompt that matches no
    key gets `default`, or is recorded in `misses` and answered with an unreadable empty reply."""

    def __init__(self, replies: dict[str, str] | None = None, *, default: str | None = None) -> None:
        super().__init__(profile_id="scripted-must-ask")
        self._replies, self._default = dict(replies or {}), default
        self.prompts: list[str] = []
        self.misses: list[str] = []
        self._lock = threading.Lock()

    def generate(self, request: GenerateRequest) -> GenerateResponse:
        haystack = f"{request.system or ''}\n{request.prompt}"
        with self._lock:
            self.prompts.append(haystack)
            keys = [key for key in self._replies if key in haystack]
            if keys:
                text = self._replies[max(keys, key=len)]
            elif self._default is not None:
                text = self._default
            else:
                self.misses.append(request.prompt)
                text = ""
        return GenerateResponse(text=text, profile_id=self._profile_id)

    def calls_about(self, title: str) -> int:
        return sum(1 for prompt in self.prompts if title in prompt)


def tasks_provider(*tasks: dict[str, Any], default: str | None = None) -> ScriptedProvider:
    """The recorded replies of the model for each task title (tasks.json), nothing else."""
    return ScriptedProvider({t["title"]: json.dumps(t["model_reply"]) for t in tasks}, default=default)


def role_providers(provider: ScriptedProvider) -> dict[str, Any]:
    """One scripted model behind every role, so a unit of any rank is judged by the same recorded replies."""
    return {role: provider for role in ROLES}


class AnswerRunner(ScriptedRunner):
    """The scripted unit runner that also records when each unit's work started and the `answer` its context carried."""

    def __init__(self, timeline: list[str]) -> None:
        super().__init__(timeline)
        self.started_at: dict[str, float] = {}
        self.answers: dict[str, Any] = {}

    async def run(self, unit: Any, context: Any) -> Any:
        self.started_at[unit["id"]] = time.monotonic()
        self.answers[unit["id"]] = getattr(context, "answer", None)
        return await super().run(unit, context)


def work_plan(approach_id: str, cap: float, *, first: dict[str, Any], independent: bool = False) -> dict[str, Any]:
    """The CL-INT-2 plan without its send: U1 -> U2 -> U3 (no action, no gate), U1 titled by `first`. With
    `independent`, U2 and U3 do not depend on U1, so a parked U1 leaves them free to run."""
    plan = base_plan(approach_id, cap)
    plan["units"], plan["gates"] = plan["units"][:3], []
    for unit, source in zip(plan["units"], (first, CLEAR[1], CLEAR[2]), strict=True):
        unit["title"] = source["title"]
    if independent:
        plan["units"][1]["depends_on"] = []
    return plan


def build_ask_flow(
    repo_root: Any,
    provider: ScriptedProvider,
    *,
    first: dict[str, Any] | None = None,
    independent: bool = False,
    send: bool = False,
) -> RunFlow:
    """A `RunFlow` (the real app, a clear task, scripted run seams) whose plan is `work_plan` (or, with `send`, the
    CL-INT-2 plan with its gated send as U4) and whose must-ask providers are `provider` for every role. `deps` may not
    have the `get_must_ask_providers` seam yet: the override is then a placeholder, the run never asks, and each test
    fails on the missing behaviour."""
    from _clint1_lib import seam  # noqa: PLC0415
    from tilo_api import deps  # noqa: PLC0415

    rf = build_run_flow(repo_root)
    rf.provider = provider  # type: ignore[attr-defined]
    rf.runner = AnswerRunner(rf.timeline)

    def compile_plan(*, brief: dict, approach: dict, budget_cap: float, context: Any = None) -> dict:
        rf.timeline.append("compile")
        rf.compile_calls.append({"brief": copy.deepcopy(brief), "approach": copy.deepcopy(approach), "cap": budget_cap})
        if send:
            rf.last_plan = base_plan(approach["id"], budget_cap)
        else:
            rf.last_plan = work_plan(approach["id"], budget_cap, first=first or ASK, independent=independent)
        return copy.deepcopy(rf.last_plan)

    rf.compile_plan = compile_plan  # type: ignore[method-assign]
    providers = role_providers(provider)
    rf.app.dependency_overrides[seam(deps, "get_must_ask_providers")] = lambda: providers
    return rf


def start_and_approve(rf: RunFlow, cap: float = CAP) -> None:
    rf.start()
    response = rf.approve(cap)
    assert response.status_code == 200, response.text


def question_events(rf: RunFlow) -> dict[str, list[dict[str, Any]]]:
    return {type_: rf.events(type_) for type_ in QUESTION_TYPES}


def needs_you_cards(rf: RunFlow) -> list[dict[str, Any]]:
    response = rf.cards()
    assert response.status_code == 200, response.text
    return [c for c in response.json() if c["kind"] == "needs_you"]


def worker_of(rf: RunFlow, unit_id: str) -> str:
    """The agent the Lead assigned the unit to."""
    assigned = next(e for e in rf.events("agent.assigned") if e["data"]["unit"] == unit_id)
    return assigned["target"]


def spy_card_submit(monkeypatch: Any, rf: RunFlow, *, fail: Exception | None = None) -> None:
    """Records "card:submit" on the run's timeline (which also holds "event:<type>" per committed event) every time a
    CardStore is handed a card; with `fail`, the store raises instead (a sink that is down)."""
    from tilo_api.cards import CardStore  # noqa: PLC0415

    original = CardStore.submit

    def submit(self: Any, card: dict, **kwargs: Any) -> Any:
        rf.timeline.append("card:submit")
        if fail is not None:
            raise fail
        return original(self, card, **kwargs)

    monkeypatch.setattr(CardStore, "submit", submit)


__all__ = [
    "ASK",
    "CAP",
    "CLEAR",
    "CLEAR_REPLY",
    "FLOW_USER",
    "QUESTION_TYPES",
    "RESUME_BUDGET_S",
    "AnswerRunner",
    "ScriptedProvider",
    "build_ask_flow",
    "needs_you_cards",
    "question_events",
    "role_providers",
    "spy_card_submit",
    "start_and_approve",
    "task",
    "tasks_provider",
    "work_plan",
    "worker_of",
]
