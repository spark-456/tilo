"""Bind the default harness to one owning run, with a shared budget and source handoff."""

from __future__ import annotations

import asyncio
import dataclasses
import json
import threading
from collections.abc import Callable, Mapping
from datetime import date
from functools import partial
from pathlib import Path
from typing import Any, cast

from tilo_archive import RunArchive
from tilo_harness.deliverable import render_format
from tilo_harness.executor import DefaultUnitRunner, UnitContext, UnitOutcome
from tilo_harness.quiz import validate_spec, verify_answers, wants_quiz
from tilo_harness.tools import ToolRegistry
from tilo_harness.unit_prompt import UpstreamItem
from tilo_planning.extraction import ExtractionError, stored_text
from tilo_providers.interfaces import GenerateRequest, GenerateResponse
from tilo_providers.media import ACCEPTED_MIME_TYPES, check_parts
from tilo_providers.router import Router, RouterResult
from tilo_providers.safety import SafetyProvider

from tilo_api.access import Mode
from tilo_api.quiz_apps import source_loader
from tilo_api.report_render import render_report
from tilo_api.web_tools import FetchTool, RunArchiveBridge, SearchTool, fetch_service, typed_hosts
from tilo_api.workspace_tools import READS_OF, WorkspaceAccess, WorkspaceUnit

FILE_TEXT_CAP = 4000  # characters of one converted upload a run agent reads (the prompt's upstream item cap)
MAX_FILE_BYTES = 2_000_000  # a stored text or Office upload past this is not read for a run agent
FILE_TEXT_TOTAL = 6000  # all uploads together: the rest of the upstream room stays for earlier units' output
# FR-AGT-03: a specialist whose plan pins no skill still gets the two read-only (T1) web tools. They are the registry's
# own: recorded search and fetch in replay, live only when the router is live (never this map's decision).
DEFAULT_TOOLS = {"specialist": ("web_search", "fetch_url")}


def brief_texts(run: Any) -> list[str]:
    """Every string the person's task put into the brief and the intake answers, plus the brief's url sources."""
    brief = run.brief if isinstance(run.brief, Mapping) else {}
    texts = [brief.get("goal"), brief.get("audience"), *(brief.get("constraints") or [])]
    texts += [d.get("title") for d in brief.get("deliverables") or [] if isinstance(d, Mapping)]
    texts += [s.get("ref") for s in brief.get("sources") or [] if isinstance(s, Mapping) and s.get("kind") == "url"]
    texts += [answer for _question, answer in getattr(run, "intake_answers", ())]
    return [text for text in texts if isinstance(text, str)]


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
    def __init__(
        self,
        providers: Mapping[str, Any],
        *,
        mode: Mode,
        clock: Callable[[], date],
        meter: Any = None,
        workspace: WorkspaceAccess | None = None,
    ) -> None:
        super().__init__(providers, clock=clock)
        self.mode, self.meter = mode, meter  # SEC-16: the run's meter; deployed, live with none is replay
        self.workspace = workspace  # ADR-0048 WT-01: set for a live run only; a demo or replay run reads nothing

    def bind_run(self, run: Any, archive: RunArchive) -> BoundRunRunner:
        from tilo_api import deps

        safety = deps.get_safety(self.mode, meter=self.meter) if self.meter is not None else deps.get_safety(self.mode)
        return BoundRunRunner(
            run,
            self._providers,
            self.mode,
            self._date_clock,
            archive,
            safety,
            deps._seam_router(self.mode, self.meter),
            deps.FIXTURES_DIR,
            self.workspace,
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
        workspace: WorkspaceAccess | None = None,
    ) -> None:
        self.workspace = workspace
        self.run_owner, self.providers, self.clock, self.safety = run, providers, clock, safety
        self.budget = RunBudget(run.cap)
        self.router = router
        self.archive = RunArchiveBridge(run, archive)
        self.service = fetch_service(mode, self.archive, fixtures)
        self.hosts: set[str] = typed_hosts(brief_texts(run))  # FR-CON-07: what the person typed or attached
        self.sources: dict[str, list[tuple[dict, Any]]] = {}
        self.file_texts: dict[tuple[str, int], str | None] = {}

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
        texts: dict[str, tuple[str, str | None]] = {}
        load = source_loader(owner.seams.artifacts, owner.scope, stream)
        for event in stream:
            if event["type"] not in {"artifact.created", "artifact.versioned"}:
                continue
            ref = event["data"]["artifact"]
            version = owner.seams.artifacts.head(owner.scope, ref)
            if version.record["origin"]["kind"] == "upload" and version.record["run_id"] == owner.run_id:
                if version.record["media_type"] not in ACCEPTED_MIME_TYPES:  # DOCX, XLSX, PPTX, CSV, text: as text
                    label = (event.get("item") or {}).get("label") or "attached file"
                    texts.setdefault(version.record["content_sha256"], (label, self.file_text(ref, version.record)))
                elif (part := load(ref)) is not None:
                    native[part.sha256] = (ref, part)
        parts = [part for _, part in native.values()]
        check_parts(parts)
        context = dataclasses.replace(context, upstream=(*self.file_items(texts), *context.upstream))
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
        tools: list[Any] = [SearchTool(self.search, self.hosts), fetch]
        defaults: Mapping[str, tuple[str, ...]] = DEFAULT_TOOLS
        on_call: Callable[[Any], None] | None = None
        if self.workspace is not None and self.workspace.client() is not None:  # ADR-0048: live and configured only
            reads = WorkspaceUnit(
                owner, self.workspace, unit, context.agent_id, self.building_of(unit), self.archive.refs
            )
            if reads.owner() is not None:  # WT-01: not offered in a world shared with a team (and checked per call)
                tools += reads.tools()
                defaults, on_call = self.default_tools(), reads.on_call
        runner = DefaultUnitRunner(
            models,
            clock=self.clock,
            tools=ToolRegistry(tools),
            default_tools=defaults,
            on_tool_call=on_call,
            safety=self.safety,
            archive=self.archive,
            request_options={role: {"parts": parts} for role in models} if parts else {},
            quiz_sources=source_loader(owner.seams.artifacts, owner.scope, owner.store.events[owner.world_id]),
            meter=lambda role, _request, _reply: models[role].take_charge(),
            credit_cap=self.budget.left,
            report_renderer=partial(render_report, fmt=render_format(unit, context.brief) or "pdf"),
        )
        return await runner.run(unit, context)

    def default_tools(self) -> dict[str, tuple[str, ...]]:
        """ADR-0048: a unit with no pinned skill also gets the reads of a connector the brief names as a source
        ({kind: connector, ref: <id>}); specialist, writer and verifier only, never the Director, Leads or Narrator."""
        brief = self.run_owner.brief if isinstance(self.run_owner.brief, Mapping) else {}
        sources = [s for s in brief.get("sources") or [] if isinstance(s, Mapping) and s.get("kind") == "connector"]
        reads = tuple(dict.fromkeys(r for s in sources for r in READS_OF.get(str(s.get("ref")), ())))
        return {role: (*DEFAULT_TOOLS.get(role, ()), *reads) for role in ("specialist", "writer", "verifier")}

    def building_of(self, unit: Mapping[str, Any]) -> str:
        """The unit's building in the run's layout (the target of its read events), else its district."""
        for level in self.run_owner.layout["semantic"]["levels"]:
            for district in level["districts"]:
                for building in district["buildings"]:
                    if unit["id"] in building.get("plan_units", []):
                        return str(building["id"])
        return str(unit["district"])

    def file_text(self, ref: Mapping[str, Any], record: Mapping[str, Any]) -> str | None:
        """The stored text of a converted upload (read again from its stored, redacted bytes), only if it was screened
        clean and is small enough to read; None otherwise (a flagged or unreadable file is never given to a model)."""
        key = (ref["artifact_id"], ref["version"])
        if key not in self.file_texts:
            text = None
            if record["screening"] == "clean" and record["size_bytes"] <= MAX_FILE_BYTES:
                try:
                    text = stored_text(
                        record["media_type"], self.run_owner.seams.artifacts.read(self.run_owner.scope, ref)
                    )
                except ExtractionError:
                    text = None
            self.file_texts[key] = text
        return self.file_texts[key]

    @staticmethod
    def file_items(texts: Mapping[str, tuple[str, str | None]]) -> tuple[UpstreamItem, ...]:
        """One untrusted upstream item per readable file, each cut to its cap and all to a shared one."""
        items: list[UpstreamItem] = []
        room = FILE_TEXT_TOTAL
        for number, (label, text) in enumerate(texts.values(), 1):
            if not text or not text.strip() or room <= 0:
                continue
            body = text.strip()[: min(FILE_TEXT_CAP, room)]
            room -= len(body)
            note = " (cut: the file is longer)" if len(text.strip()) > len(body) else ""
            items.append(UpstreamItem(f"file{number}", f"File: {label}", body + note, screening="clean", tainted=True))
        return tuple(items)

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
            passed = await asyncio.to_thread(verify_answers, spec, cast(Any, model), load)
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
