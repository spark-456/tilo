"""RUN-FAIL-1 (live world w_69VY..., 14 Oct): a run whose first unit loads the web-research skill after its must-ask
question is answered stopped one second later with "a unit failed, so the work stopped" and no log line.

The cause: the tool loop hands the provider layer OpenAI-style tool specs, and the google adapter put them into the Gen
AI SDK's `GenerateContentConfig` as they were; the SDK refuses that shape before anything is sent, the Router raises,
and the executor swallowed it. This rig runs the production path in replay: the API's `ApiUnitRunner` and
`BoundRunRunner`, `_RoleModel`, a real `Router` on config/models.yaml and config/prices.yaml, and the real
`GoogleModelProvider` building real SDK request objects, with only the network client faked (no call leaves).

It also pins what must never happen again: a failed unit's reason reaches `world.failed` in plain words and an ERROR
line, and the must-ask model is shown the whole task, not the unit's title alone.
"""

from __future__ import annotations

import asyncio
import copy
import json
import logging
from datetime import UTC, date, datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from tilo_api import deps
from tilo_api.layout import build_layout
from tilo_api.run_tools import ApiUnitRunner
from tilo_api.runs import Run, Seams
from tilo_api.world_writer import WorldWriterAdapter
from tilo_archive import LocalDirStore, RunArchive
from tilo_connectors import InMemoryOutboxStore
from tilo_connectors.registry import ConnectorRegistry
from tilo_harness.skills import SkillRegistry
from tilo_harness.store import MemoryStore
from tilo_memory.artifacts import ArtifactStore, MemoryBlobBackend, MemoryMetaBackend
from tilo_planning.compiler import _with_deliver
from tilo_providers.config import load_providers_config
from tilo_providers.google_adapter import GoogleModelProvider
from tilo_providers.interfaces import GenerateResponse
from tilo_providers.router import Router
from tilo_providers.safety import FakeSafetyProvider
from tilo_providers.search import FakeSearchProvider

pytestmark = pytest.mark.usefixtures("must_ask_ask_mode")  # these tests pin the card and its answer (BQ-ASSUME-1)

ROOT = Path(__file__).resolve().parents[3]
WORLD, RUN, OWNER = "w_run_fail_1", "r_run_fail_1", "u_run_fail_1"
GOAL = (
    "Plan a trip for me from Chennai to Gokarna by road while picking up a friend from Bangalore, 3-4 days on road "
    "while visiting some rarely explored places"
)
REGION_ASK = {  # the live must-ask reply, as the card showed it
    "ask": True,
    "reason": "ambiguous_brief",
    "question": "Which geographic region or country should I focus the research on?",
    "options": ["Europe", "Ask me later"],
    "suggested": 0,
    "why": "A region narrows the research.",
}
BUDGET_LINE = "a step's model call did not fit the credits left in the run's budget"


class AskingModel:
    """The must-ask model: asks the live question about the research unit, records every prompt it was shown."""

    def __init__(self) -> None:
        self.prompts: list[str] = []

    def generate(self, request: Any) -> GenerateResponse:
        self.prompts.append(request.prompt)
        ask = "Unit type: research" in request.prompt
        return GenerateResponse(text=json.dumps(REGION_ASK if ask else {"ask": False}), profile_id="scripted")


class FakeModels:
    """`client.models` for the google adapter: no network. `generate_content` gets the SDK's real config object, so a
    request the SDK refuses never reaches it (exactly as live)."""

    def __init__(self) -> None:
        self.configs: list[Any] = []

    def count_tokens(self, *, model: str, contents: Any) -> Any:
        return SimpleNamespace(total_tokens=len(str(contents)) // 4 + 1)

    def generate_content(self, *, model: str, contents: Any, config: Any) -> Any:
        self.configs.append(config)
        text = str(contents)
        tools = getattr(config, "tools", None)
        calls = None
        if tools and "TOOL_RESULT" not in text:  # the specialist's first step: one search
            calls = [SimpleNamespace(name="web_search", args={"query": "offbeat stops Chennai Bangalore Gokarna"})]
        reply = None if calls else "Day 1 Chennai to Bangalore; day 2 Bangalore to Gokarna via quieter stops."
        usage = SimpleNamespace(
            prompt_token_count=len(text) // 4 + 1,
            candidates_token_count=200,
            total_token_count=len(text) // 4 + 201,
            thoughts_token_count=0,
            cached_content_token_count=None,
            prompt_tokens_details=None,
        )
        candidate = SimpleNamespace(finish_reason="STOP")
        return SimpleNamespace(
            prompt_feedback=None, candidates=[candidate], usage_metadata=usage, function_calls=calls, text=reply
        )


def _router(models: FakeModels) -> Router:
    config = load_providers_config(ROOT / "config" / "models.yaml", ROOT / "config" / "prices.yaml")
    client = SimpleNamespace(models=models)

    def provider(profile_id: str) -> GoogleModelProvider:
        return GoogleModelProvider(config.profiles[profile_id], profile_id, "demo-tilo", "global", client=client)

    return Router(config, provider_for_profile=provider, search_for_profile=lambda _pid: FakeSearchProvider())


def _artifacts(open_archive: Any) -> ArtifactStore:
    ids = iter(range(1, 50))
    return ArtifactStore(
        MemoryMetaBackend(),
        MemoryBlobBackend(),
        clock=lambda: datetime.now(UTC),
        redactor=lambda text: text,
        archive_lookup=lambda _scope, _ref: None,
        alert_sink=lambda _: None,
        screener=FakeSafetyProvider(),
        new_id=lambda: f"art_rf1_{next(ids)}",
    )


def _run(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, cap: float) -> tuple[Run, Any, AskingModel, FakeModels]:
    monkeypatch.delenv("TILO_MODELS_FILE", raising=False)
    monkeypatch.delenv("LIVE", raising=False)
    models, asking = FakeModels(), AskingModel()
    router = _router(models)
    monkeypatch.setattr(deps, "_seam_router", lambda mode, meter=None: router)
    monkeypatch.setattr(deps, "get_safety", lambda mode, meter=None: FakeSafetyProvider())
    monkeypatch.setattr(deps, "FIXTURES_DIR", tmp_path)
    state = deps.Store(worlds={WORLD: deps.WorldRecord(OWNER, {}, run_id=RUN)})
    writer = WorldWriterAdapter(state, MemoryStore(), clock=lambda: datetime.now(UTC))

    def open_archive(*, org_id: str, run_id: str) -> RunArchive:
        return RunArchive(
            LocalDirStore(tmp_path / "archive"), org_id=org_id, run_id=run_id, redactor=lambda value: value
        )

    brief = {"goal": GOAL, "deliverables": [{"title": "Road trip plan"}], "constraints": ["3-4 days on the road"]}
    plan = json.loads((ROOT / "contracts/fixtures/plan/valid/two_approaches_email_send_gated.json").read_text())
    plan["gates"], plan["budget_cap"] = [], cap
    research = {
        "id": "U1", "unit_type": "research", "title": "Research rarely explored stops on the route",
        "role": "specialist", "district": "D1", "skills": ["web-research"], "actions": [], "connectors": [],
        "depends_on": [],
    }  # fmt: skip
    plan["units"] = _with_deliver([research], brief)
    workers = {role: deps._RoleModel(router, role) for role in ("specialist", "writer", "verifier")}
    seams = Seams(
        compiler=lambda **_: copy.deepcopy(plan),
        layout_builder=build_layout,
        runner=ApiUnitRunner(workers, mode="replay", clock=lambda: date(2026, 10, 14)),
        resolver=lambda **_: {},
        skills=SkillRegistry(ROOT / "skills"),
        connectors=ConnectorRegistry({}),
        adapters={},
        outbox_store=InMemoryOutboxStore(),
        writer=writer,
        must_ask_providers={role: asking for role in ("specialist", "writer", "verifier")},
        artifacts=_artifacts(open_archive),
        redactor=lambda text: text,
        open_archive=open_archive,
        team=lambda: None,
    )
    task = deps.TaskRecord(OWNER, WORLD, RUN, brief, brief, [], 0, approaches=plan["approaches"])
    return Run(state, task, plan["approaches"][0], cap, seams), state, asking, models


async def _answer_and_finish(run: Run, state: Any) -> None:
    """Starts the run, answers the must-ask card with its first option (as the person did), waits for the end."""
    work = asyncio.ensure_future(run._execute())
    for _ in range(3000):
        routed = [e for e in state.events.get(WORLD, []) if e["type"] == "question.routed"]
        if routed or work.done():
            break
        await asyncio.sleep(0.01)
    assert routed, "the research unit must ask first (the live shape)"
    principal = deps.Principal(OWNER, "owner", WORLD)
    card = routed[0]["data"]["card_id"]
    answered = await asyncio.to_thread(run.cards.answer, WORLD, card, option="o1", channel="web", principal=principal)
    assert answered.outcome == "answered", answered
    await asyncio.wait_for(work, timeout=60)


def _handed_off(events: list[dict[str, Any]], unit: str) -> bool:
    worker = next(e["target"] for e in events if e["type"] == "agent.assigned" and e["data"]["unit"] == unit)
    return any(e["type"] == "agent.handoff" and e["actor"] == worker for e in events)


def _types(state: Any) -> list[str]:
    return [e["type"] for e in state.events[WORLD]]


def test_RUN_FAIL_1_tool_unit_runs_after_its_answer_on_the_google_adapter(tmp_path, monkeypatch):
    run, state, _asking, models = _run(tmp_path, monkeypatch, cap=40)

    asyncio.run(_answer_and_finish(run, state))

    events = state.events[WORLD]
    failed = [e for e in events if e["type"] == "world.failed"]
    assert not failed, failed
    assert _types(state)[-1] == "world.completed"
    assert _handed_off(events, "U1")
    with_tools = [c for c in models.configs if getattr(c, "tools", None)]
    assert with_tools, "the research unit's model call reached the SDK with its tools"
    names = [d.name for d in with_tools[0].tools[0].function_declarations]
    assert set(names) == {"web_search", "fetch_url"}


def test_RUN_FAIL_1_a_failed_unit_says_why_in_world_failed_and_an_error_line(tmp_path, monkeypatch, caplog):
    """The live grant was 3 credits: the research unit now works, and the writer's call (flash at its 16384-token cap,
    about 14 credits) cannot fit; the run stops with that reason in plain words, never the generic line."""
    run, state, _asking, _models = _run(tmp_path, monkeypatch, cap=3)
    caplog.set_level(logging.ERROR)

    asyncio.run(_answer_and_finish(run, state))

    events = state.events[WORLD]
    assert _handed_off(events, "U1"), "the research unit itself no longer fails"
    (failed,) = [e for e in events if e["type"] == "world.failed"]
    assert failed["data"] == {"reason": BUDGET_LINE, "unit": "U2"}
    assert failed["summary"] == f"Stopped: {BUDGET_LINE}"
    lines = [r.getMessage() for r in caplog.records if r.levelno >= logging.ERROR]
    assert any("unit U2 failed" in line and "BudgetExceededError" in line for line in lines), lines
    assert any(RUN in line and BUDGET_LINE in line for line in lines), lines


def test_RUN_FAIL_1_must_ask_is_shown_the_whole_task_not_only_the_unit_title(tmp_path, monkeypatch):
    run, state, asking, _models = _run(tmp_path, monkeypatch, cap=40)

    asyncio.run(_answer_and_finish(run, state))

    (research,) = [p for p in asking.prompts if "Unit type: research" in p]
    for place in ("Chennai", "Bangalore", "Gokarna", "3-4 days on the road"):
        assert place in research, f"the must-ask prompt lost {place!r}: {research}"
    assert research.index("Goal:") < research.index("TASK>>>"), "the task is data inside the TASK block"
