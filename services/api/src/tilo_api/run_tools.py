"""Bind the default harness to one owning run, with a shared budget and source handoff."""

from __future__ import annotations

import asyncio
import dataclasses
import json
import threading
from collections.abc import Callable, Mapping
from datetime import date
from pathlib import Path
from typing import Any

from tilo_archive import RunArchive
from tilo_harness.executor import DefaultUnitRunner, UnitContext, UnitOutcome
from tilo_harness.quiz import validate_spec, verify_answers, wants_quiz
from tilo_harness.tools import ToolRegistry
from tilo_harness.unit_prompt import UpstreamItem
from tilo_providers.interfaces import GenerateRequest, GenerateResponse
from tilo_providers.media import check_parts
from tilo_providers.router import Router, RouterResult
from tilo_providers.safety import SafetyProvider

from tilo_api.access import Mode
from tilo_api.quiz_apps import source_loader
from tilo_api.web_tools import FetchTool, RunArchiveBridge, SearchTool, fetch_service


class RunBudget:
    def __init__(self, cap: float) -> None:
        self.left = cap
        self.lock = threading.Lock()

    def call(self, method: Callable[..., RouterResult], *args: Any) -> tuple[RouterResult, float]:
        with self.lock:
            before = self.left
            result = method(*args, budget=before)
            if result.budget is None:
                raise ValueError("The provider returned no remaining budget")
            self.left = result.budget
            return result, max(0.0, before - self.left)


class BoundModel:
    def __init__(self, model: Any, budget: RunBudget) -> None:
        self.model, self.budget, self.spent = model, budget, 0.0

    def generate(self, request: GenerateRequest) -> GenerateResponse:
        if hasattr(self.model, "generate_budgeted"):
            reply, charge = self.model.generate_budgeted(request, self.budget)
            self.spent += charge
            return reply
        return self.model.generate(request)  # injected test model, never the default production model

    def take_charge(self) -> float:
        spent, self.spent = self.spent, 0.0
        return spent


class ApiUnitRunner(DefaultUnitRunner):
    def __init__(self, providers: Mapping[str, Any], *, mode: Mode, clock: Callable[[], date]) -> None:
        super().__init__(providers, clock=clock)
        self.mode = mode

    def bind_run(self, run: Any, archive: RunArchive) -> BoundRunRunner:
        from tilo_api import deps

        return BoundRunRunner(
            run,
            self._providers,
            self.mode,
            self._date_clock,
            archive,
            deps.get_safety(self.mode),
            deps._seam_router(self.mode),
            deps.FIXTURES_DIR,
        )


class BoundRunRunner:
    def __init__(
        self,
        run: Any,
        providers: Mapping[str, Any],
        mode: Mode,
        clock: Callable[[], date],
        archive: RunArchive,
        safety: SafetyProvider,
        router: Router,
        fixtures: Path,
    ) -> None:
        self.run_owner, self.providers, self.clock, self.safety = run, providers, clock, safety
        self.budget = RunBudget(run.cap)
        self.router = router
        self.archive = RunArchiveBridge(run, archive)
        self.service = fetch_service(mode, self.archive, fixtures)
        self.hosts: set[str] = set()
        self.sources: dict[str, list[tuple[dict, Any]]] = {}

    def search(self, query: str) -> tuple[Any, float]:
        result, credits = self.budget.call(self.router.search, "search", query)
        if result.search_result is None:
            raise ValueError("no search result")
        return result.search_result, credits

    def dependencies(self, unit: Mapping[str, Any]) -> set[str]:
        plan = {u["id"]: u for u in self.run_owner.plan["units"]}
        found: set[str] = set()

        def visit(ident: str) -> None:
            if ident in found:
                return
            found.add(ident)
            for parent in plan[ident]["depends_on"]:
                visit(parent)

        for ident in unit["depends_on"]:
            visit(ident)
        return found

    async def run(self, unit: Mapping[str, Any], context: UnitContext) -> UnitOutcome:
        owner = self.run_owner
        context = dataclasses.replace(context, brief=self.brief_for(unit))
        native = {
            part.sha256: (ref, part) for ident in self.dependencies(unit) for ref, part in self.sources.get(ident, [])
        }
        stream = owner.store.events[owner.world_id]
        load = source_loader(owner.seams.artifacts, owner.scope, stream)
        for event in stream:
            if event["type"] not in {"artifact.created", "artifact.versioned"}:
                continue
            ref = event["data"]["artifact"]
            version = owner.seams.artifacts.head(owner.scope, ref)
            if version.record["origin"]["kind"] == "upload" and version.record["run_id"] == owner.run_id:
                part = load(ref)
                if part is not None:
                    native[part.sha256] = (ref, part)
        parts = [part for _, part in native.values()]
        check_parts(parts)
        if native:
            refs = json.dumps([ref for ref, _ in native.values()])
            context = dataclasses.replace(
                context,
                upstream=(
                    *context.upstream,
                    UpstreamItem(
                        "sources",
                        "Recorded native sources",
                        refs,
                        screening="clean",
                        tainted=True,
                    ),
                ),
            )
        models = {role: BoundModel(model, self.budget) for role, model in self.providers.items()}
        fetch = FetchTool(owner, self.service, self.hosts, unit, context, self.sources)
        runner = DefaultUnitRunner(
            models,
            clock=self.clock,
            tools=ToolRegistry([SearchTool(self.search, self.hosts), fetch]),
            safety=self.safety,
            archive=self.archive,
            request_options={role: {"parts": parts} for role in models} if parts else {},
            quiz_sources=source_loader(owner.seams.artifacts, owner.scope, owner.store.events[owner.world_id]),
            meter=lambda role, _request, _reply: models[role].take_charge(),
            credit_cap=self.budget.left,
        )
        return await runner.run(unit, context)

    async def before_handoff(self, unit: Mapping[str, Any], worker: str, announced: list[tuple[dict, str]]) -> bool:
        owner = self.run_owner
        if not wants_quiz(unit, self.brief_for(unit)):
            return True
        verifier = next(
            (a["id"] for a in owner.layout["semantic"]["agents"] if a["rank"] == "verifier" and a["id"] != worker), None
        )
        if verifier is None or "verifier" not in self.providers or not announced:
            owner.failure = "The quiz has no independent verifier."
            return False
        for ref, made in announced:
            spec = validate_spec(json.loads(owner.seams.artifacts.read(owner.scope, ref)))
            created = owner.put(
                "app.spec",
                worker,
                ref["artifact_id"],
                "The quiz specification was stored.",
                {"spec": ref},
                district=unit["district"],
                cause=made,
            )
            model = BoundModel(self.providers["verifier"], self.budget)
            load = source_loader(owner.seams.artifacts, owner.scope, owner.store.events[owner.world_id])
            passed = await asyncio.to_thread(verify_answers, spec, model, load)
            owner.put(
                "app.tested",
                verifier,
                ref["artifact_id"],
                "The quiz answers were checked.",
                {"spec": ref, "passed": passed},
                district=unit["district"],
                cause=created["id"],
                credits=model.take_charge(),
            )
            if not passed:
                owner.failure = "The quiz answers could not be independently confirmed."
                return False
        return True

    def brief_for(self, unit: Mapping[str, Any]) -> dict[str, Any]:
        brief = self.run_owner.brief
        items = brief.get("deliverables", [])
        if len(items) <= 1 or unit["unit_type"] != "deliver":
            return brief
        own = [item for item in items if item.get("title", "").strip()[:80] == unit["title"]]
        if len(own) != 1:
            raise ValueError("ambiguous deliverable")
        return {**brief, "deliverables": own}
