"""Helpers for the CL-INT-2 acceptance tests (CP2 thin slice, second half: after approve the run plays to a
gated action and a delivery; PRD 5.4 CP2, 8.5, 9.4, 10.3, 10.4, FR-AGT-11, FR-HIL-01/03/04, FR-WLD-03/07;
ADR-0008). The routes and injection seams these tests pin are in `API_CL_INT_2.md`.

Named `_clint2_lib` for the same global-bare-module-name reason as `_clint1_lib.py`.

Nothing here is business logic. `RunFlow` wraps the CL-INT-1 `Flow` (the real `tilo_api.app`) and installs the
run-time fakes behind the seams of API_CL_INT_2.md: a scripted plan compiler, layout builder, unit runner and
action resolver; a connector registry holding one mock connector; a `MockConnector` adapter; an in-memory outbox
store; and an event writer that stands in for the harness's single writer. Seams the production code does not
have yet resolve to a placeholder dependency nothing uses (`_clint1_lib.seam`), so a missing seam shows up as a
run that never starts, not as an `AttributeError` in test setup.
"""

from __future__ import annotations

import asyncio
import copy
import json
import pathlib
import sys
import tempfile
import threading
import time
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

from _api_contracts_lib import assert_valid_event
from _api_lib import FakeEventWriter
from _cards_lib import build_registry as build_schema_registry
from _clint1_lib import FLOW_USER, OTHER_USER, Flow, registered_event_types, seam
from tilo_connectors.mock import MockConnector
from tilo_connectors.registry import ConnectorRegistry
from tilo_providers.fake import FakeModelProvider
from tilo_providers.interfaces import GenerateRequest, GenerateResponse

REPO_ROOT = pathlib.Path(__file__).resolve().parents[3]
SKILLS_ROOT = REPO_ROOT / "services" / "harness" / "tests" / "fixtures" / "skills"  # skills/ is empty until #70

CAP = 60  # the cap the owner confirms; not equal to any scripted approach credit figure
MOCK_ID = "mock_mail"
DESTINATION = "thread-supplier-1"
NEW_RECIPIENT = "finance@example.com"
KNOWN_RECIPIENT = "ops@example.com"
POOL = (NEW_RECIPIENT, KNOWN_RECIPIENT, "riya@example.com", "sam@example.org")

# Since ADR-0018 T4 (FR-AGT-02, FR-MEM-06) no test names an artifact id: each scripted unit returns Markdown
# (`UnitOutput`), the executor puts it on the artifact store, the store mints the id and `artifact.created` carries it.
# Read an id from the stream with `RunFlow.artifact_of("U4")` (U4 makes the draft that the gate holds).
FAKE_SECRET = "fake-secret-" + "".join(["0x", "CAFE", "F00D"])  # assembled at runtime, never a literal secret

# Event types that mean "the agents are doing something" (the pause and gate tests assert none follow).
WORK_PREFIXES = ("agent.", "artifact.", "building.", "skill.", "level.", "district.", "meeting.", "question.")


def load_json(*parts: str) -> Any:
    return json.loads(REPO_ROOT.joinpath(*parts).read_text(encoding="utf-8"))


# --- fixtures the tests script ----------------------------------------------------------------------------


def mock_declaration() -> dict[str, Any]:
    """The mock connector as a registry entry: the contract's gmail fixture under a test id (the shipped config
    never declares a mock; only tests do). Its `send_email` is T2, gate_type approval, irreversible."""
    declaration = load_json("contracts", "fixtures", "connector", "valid", "gmail.json")
    return {**declaration, "id": MOCK_ID, "name": "Mock Mail"}


def connector_registry() -> ConnectorRegistry:
    return ConnectorRegistry({MOCK_ID: mock_declaration()})


def base_plan(approach_id: str = "quick", budget_cap: float = CAP) -> dict[str, Any]:
    """A valid PlanGraph: U1 -> U2 -> U3 -> U4, where U4 sends the summary by the mock connector behind gate G1
    (T3: a recipient new to the owner, no policy). Built from the contract's own plan fixture."""
    plan = load_json("contracts", "fixtures", "plan", "valid", "two_approaches_email_send_gated.json")
    skills = {"U1": ["web_research"], "U2": ["web_research"], "U3": ["exec_summary"], "U4": []}
    for unit in plan["units"]:
        unit["skills"] = skills[unit["id"]]
    plan["units"][3]["connectors"] = [MOCK_ID]
    plan["chosen_approach"], plan["budget_cap"] = approach_id, budget_cap
    return plan


BAD_PLANS: dict[str, str] = {  # kind -> the plan.rules.md rule it breaks
    "ungated_send": "PG-04",
    "unknown_connector": "PG-11",
    "cycle": "PG-03",
    "unknown_skill": "PG-11",
    "gate_below_table": "PG-06",
}


def bad_plan(kind: str, approach_id: str = "quick", budget_cap: float = CAP) -> dict[str, Any]:
    plan = base_plan(approach_id, budget_cap)
    if kind == "ungated_send":
        plan["gates"] = []  # U4 sends with no gate guarding it
    elif kind == "unknown_connector":
        plan["units"][3]["connectors"] = ["no_such_connector"]
    elif kind == "cycle":
        plan["units"][0]["depends_on"] = ["U4"]
    elif kind == "unknown_skill":
        plan["units"][0]["skills"] = ["not_a_skill"]
    elif kind == "gate_below_table":
        plan["gates"][0]["risk_tier"] = "T1"  # the risk table has send_email at T2
    else:
        raise AssertionError(kind)
    return plan


def plan_violations(plan: dict[str, Any], registry: ConnectorRegistry, skills_root: pathlib.Path = SKILLS_ROOT) -> list:
    """What `tilo_planning.plangraph.validate_plan` says of `plan` against the scripted registries."""
    import tilo_policy  # noqa: PLC0415
    from tilo_harness.skills import SkillRegistry  # noqa: PLC0415
    from tilo_planning.plangraph import validate_plan  # noqa: PLC0415

    skill_ids = frozenset(skill_id for skill_id, _ in SkillRegistry(skills_root).catalog())
    connectors = {cid: registry.get(cid) for cid in registry.ids()}
    return validate_plan(
        plan, risk_table=tilo_policy.load_risk_table(), connectors=connectors, skills=skill_ids, policies={},
        owner=FLOW_USER,
    )  # fmt: skip


def layout_for(plan: dict[str, Any], *, world_id: str) -> dict[str, Any]:
    """A layout.schema.json record for `plan`: one Director, a Lead per district, one worker per unit by role, a
    workshop per district holding that district's units, an island per connector and a gate per plan gate."""
    districts: dict[str, list[dict[str, Any]]] = {}
    for unit in plan["units"]:
        districts.setdefault(unit["district"], []).append(unit)
    agents: list[dict[str, str]] = [{"id": "A_director", "rank": "director"}]
    counters = {"specialist": 0, "writer": 0, "verifier": 0}
    for unit in plan["units"]:
        counters[unit["role"]] += 1
    for role, prefix in (("specialist", "A_s"), ("writer", "A_w"), ("verifier", "A_v")):
        agents += [{"id": f"{prefix}{n}", "rank": role} for n in range(1, counters[role] + 1)]
    built, building_of = [], {}
    for index, (district_id, units) in enumerate(sorted(districts.items()), start=1):
        lead = f"A_lead{index}"
        agents.append({"id": lead, "rank": "lead"})
        building = f"B{index}"
        for unit in units:
            building_of[unit["id"]] = building
        built.append(
            {
                "id": district_id, "name": f"Work {index}", "icon": "inbox", "lead": lead,
                "buildings": [
                    {
                        "id": building, "name": "Workshop", "kind": "common", "common_type": "workshop",
                        "plan_units": [u["id"] for u in units],
                    }
                ],
            }
        )  # fmt: skip
    connector_ids = sorted({c for unit in plan["units"] for c in unit["connectors"]})
    islands = [
        {"id": f"I{n}", "name": "Mock Mail", "conn": "api", "bridge": "road", "state": "connected"}
        for n, _ in enumerate(connector_ids, start=1)
    ]
    island_of = {c: f"I{n}" for n, c in enumerate(connector_ids, start=1)}
    gates = []
    for gate in plan["gates"]:
        unit = next(u for u in plan["units"] if u["id"] == gate["guards"][0])
        gates.append(
            {
                "id": gate["id"], "guards": gate["action_type"], "policy_ref": gate["policy_ref"],
                "between": [building_of[unit["id"]], island_of[unit["connectors"][0]]],
            }
        )  # fmt: skip
    layout = {
        "v": "1.0", "world_id": world_id, "tier": "village", "theme": "metropolis", "geometry": None,
        "semantic": {"levels": [{"id": "L1", "name": "Level One", "districts": built}], "islands": islands,
                     "gates": gates, "agents": agents},
    }  # fmt: skip
    return layout


def schema_errors(name: str, instance: Any) -> list[str]:
    """Messages from contracts/<name>.schema.json (cross-file $refs resolved), empty when valid."""
    import jsonschema  # noqa: PLC0415

    schema = load_json("contracts", f"{name}.schema.json")
    cls = jsonschema.validators.validator_for(schema, default=jsonschema.Draft202012Validator)
    return [e.message for e in cls(schema, registry=build_schema_registry(REPO_ROOT)).iter_errors(instance)]


# --- doubles ----------------------------------------------------------------------------------------------


def org_id() -> str:
    """The org tilo-api puts every run's Scope in: `deps.ORG_ID` (pinned by API_FR_AGT_02_T4: a single constant until
    sign-in gives a world its org). Until it exists this is a placeholder, so a missing constant shows up as a store
    that holds nothing for the run, not as an AttributeError in test setup."""
    from tilo_api import deps  # noqa: PLC0415

    return getattr(deps, "ORG_ID", "org_missing_constant")


class _CleanScreener:
    """SafetyProvider-shaped screener (`check(text, *, content, mime_type)`): every version is clean."""

    def check(self, text: str, *, content: bytes | None = None, mime_type: str | None = None) -> dict[str, Any]:
        return {"flagged": False, "reason": None}


class FakeRedactor:
    """The shared secret redactor, faked: replaces FAKE_SECRET. Records every input."""

    def __init__(self) -> None:
        self.calls: list[str] = []

    def __call__(self, text: str) -> str:
        self.calls.append(text)
        return text.replace(FAKE_SECRET, "[REDACTED]")


class ArtifactRig:
    """The artifact seams of API_FR_AGT_02_T4.md, all fakes: an `ArtifactStore` over the memory backends, the fake
    redactor, and a RunArchive factory over a throwaway directory. `opened` records each (org_id, run_id, archive)
    the run asked for."""

    def __init__(self) -> None:
        from tilo_memory.artifacts import ArtifactStore, MemoryBlobBackend, MemoryMetaBackend  # noqa: PLC0415

        self._dir = tempfile.TemporaryDirectory()
        self.meta, self.blobs = MemoryMetaBackend(), MemoryBlobBackend()
        self.redactor, self.alerts = FakeRedactor(), []
        self.opened: list[tuple[str, str, Any]] = []
        self.store = ArtifactStore(
            self.meta,
            self.blobs,
            clock=lambda: datetime.now(UTC),
            redactor=self.redactor,
            archive_lookup=lambda scope, archive_ref: None,
            alert_sink=self.alerts.append,
            screener=_CleanScreener(),
        )

    def open_archive(self, *, org_id: str, run_id: str) -> Any:
        """What `deps.get_run_archive()` returns: opens the run's raw archive (hash-chained, redacted)."""
        from tilo_archive import LocalDirStore, RunArchive  # noqa: PLC0415

        archive = RunArchive(
            LocalDirStore(pathlib.Path(self._dir.name)),
            org_id=org_id,
            run_id=run_id,
            redactor=lambda payload: payload,
            clock=lambda: datetime.now(UTC),
        )
        self.opened.append((org_id, run_id, archive))
        return archive

    def scope(self, world_id: str, owner: str = FLOW_USER, org: str | None = None) -> Any:
        from tilo_memory.artifacts import Scope  # noqa: PLC0415

        return Scope(org_id=org or org_id(), world_id=world_id, owner=owner)

    def seed(self, scope: Any, content: bytes = b"# Another item\n") -> dict[str, Any]:
        """A version held in `scope` (an upload), which a run of another Scope can only name by ref; returns its ref."""
        from tilo_memory.artifacts import NewVersion, Origin  # noqa: PLC0415

        new = NewVersion(media_type="text/markdown", content=content, run_id="r_seeded_1", origin=Origin(kind="upload"))
        return self.store.put(scope, new).ref

    def close(self) -> None:
        self._dir.cleanup()


def markdown_for(unit: Any) -> bytes:
    return f"# {unit['title']}\n\nUnit {unit['id']} finished.\n".encode()


class ScriptedRunner:
    """The harness `UnitRunner`: no model, no network. Each unit succeeds with one Markdown output (the executor
    stores it and announces it, ADR-0018), or fails when its id is in `fail`. A unit named in `block_on` waits
    (without blocking the loop) until `release` is set."""

    def __init__(self, timeline: list[str]) -> None:
        self.timeline = timeline
        self.ran: list[str] = []
        self.fail: set[str] = set()
        self.block_on: str | None = None
        self.entered = threading.Event()
        self.release = threading.Event()

    async def run(self, unit: Any, context: Any) -> Any:
        from tilo_harness.executor import UnitOutcome, UnitOutput  # noqa: PLC0415

        self.ran.append(unit["id"])
        self.timeline.append(f"run:{unit['id']}")
        if unit["id"] == self.block_on:
            self.entered.set()
            while not self.release.is_set():
                await asyncio.sleep(0.01)
        if unit["id"] in self.fail:
            return UnitOutcome(success=False, summary="scripted failure")
        output = UnitOutput(media_type="text/markdown", content=markdown_for(unit))
        return UnitOutcome(success=True, summary=f"Finished {unit['title']}.", outputs=(output,))


class ClearModel(FakeModelProvider):
    """The must-ask model of a flow that is not about questions (FR-AGT-05, BQ-236): every unit is judged clear."""

    def __init__(self) -> None:
        super().__init__(profile_id="scripted-clear")

    def generate(self, request: GenerateRequest) -> GenerateResponse:
        return GenerateResponse(text='{"ask": false}', profile_id=self._profile_id)


def covering_policy(owner: str = FLOW_USER) -> dict[str, Any]:
    """The owner's L1 ("ask me each time") autonomy policy for send_email on the mock connector. It covers the
    action for FR-AGT-05's rule (PRD 8.3: no question for a send an autonomy policy covers) and changes nothing
    else: at L1 the policy engine gates exactly as with no policy."""
    stamp = {"by": owner, "at": "2026-09-29T09:30:00.000Z"}
    return {
        "id": "pol_send_ask", "owner": owner, "action_type": "send_email",
        "scope": {"connectors": [MOCK_ID], "recipients": [], "domains": [], "districts": []},
        "limits": {"per_day": None, "credits": None},
        "conditions": {"no_attachments": True, "no_new_recipients": True, "no_safety_flags": True},
        "level": "L1", "undo_window_s": 60, "expiry": None, "notify_channel": "email", "team_lead_domains": [],
        "created_by": stamp, "changed_by": stamp, "history": [{**stamp, "change": "Created at L1", "level": "L1"}],
    }  # fmt: skip


class CrashAfterSendMock(MockConnector):
    """The provider accepted the send, then the connection reset before the outbox could record it: `send_reply`
    records the send and raises on its first call only (what FR-AGT-11's "retried send step" looks like)."""

    def __init__(self, declaration: Any) -> None:
        super().__init__(declaration)
        self.calls = 0

    def send_reply(self, thread_id: Any, item: Any, recipients: Any, idempotency_key: Any, grant: Any) -> Any:
        self.calls += 1
        record = super().send_reply(thread_id, item, recipients, idempotency_key, grant)
        if self.calls == 1:
            raise ConnectionError("connection reset after the provider accepted the send")
        return record


class StreamWriter(FakeEventWriter):
    """Stands in for the harness's single writer (`deps.get_event_writer`): stamps `seq`, `run_id` and (when the
    caller left it out) `ts`, continuing after whatever the API itself already wrote to the world's stream
    (intake and `budget.granted`), idempotent by event `id`. It keeps a log of every append (`calls`) and a
    timeline entry per first commit, and, unlike the real writer, enforces nothing: the tests validate the
    stream afterwards, so a builder bug is reported by the test, not hidden by this double."""

    def __init__(self, store: Any, timeline: list[str]) -> None:
        super().__init__(store)
        self._lock = threading.Lock()
        self.timeline = timeline

    def append(self, world_id: str, event: dict) -> dict:
        from tilo_api.events import now  # noqa: PLC0415

        with self._lock:
            committed = self.store.events.setdefault(world_id, [])
            self._counters[world_id] = max((e["seq"] for e in committed), default=0)
            known = {e["id"] for e in committed}
            if event.get("id") not in known and not event.get("ts"):
                event = {**event, "ts": now()}
            stamped = super().append(world_id, event)
            if event.get("id") not in known:
                self.timeline.append(f"event:{stamped['type']}")
            return stamped


def wait_for(predicate: Callable[[], Any], *, timeout: float = 6.0, what: str = "the condition") -> Any:
    deadline = time.monotonic() + timeout
    while True:
        value = predicate()
        if value:
            return value
        if time.monotonic() > deadline:
            raise AssertionError(f"timed out after {timeout} s waiting for {what}")
        time.sleep(0.02)


def settle(read: Callable[[], Any], *, quiet_s: float = 0.5, timeout: float = 8.0) -> Any:
    """Waits until `read()` has not changed for `quiet_s`; returns the last value."""
    deadline = time.monotonic() + timeout
    last, since = read(), time.monotonic()
    while time.monotonic() - since < quiet_s:
        if time.monotonic() > deadline:
            raise AssertionError(f"still changing after {timeout} s")
        time.sleep(0.02)
        now_value = read()
        if now_value != last:
            last, since = now_value, time.monotonic()
    return last


# --- the flow with the run seams --------------------------------------------------------------------------


class RunFlow:
    """A CL-INT-1 `Flow` plus the run seams of API_CL_INT_2.md. One task, one world (`start`)."""

    def __init__(self, flow: Flow, outbox_store: Any, adapter: Any = None) -> None:
        from tilo_api import deps  # noqa: PLC0415
        from tilo_harness.skills import SkillRegistry  # noqa: PLC0415

        self.flow, self.store, self.app = flow, flow.store, flow.app
        self.timeline: list[str] = []
        self.registry = connector_registry()
        self.adapter = adapter or MockConnector(self.registry.get(MOCK_ID))
        self.outbox_store = outbox_store
        self.runner = ScriptedRunner(self.timeline)
        self.rig = ArtifactRig()  # the run's artifact store, redactor and archive factory (ADR-0018 T4)
        self.writer = StreamWriter(self.store, self.timeline)
        self.skills = SkillRegistry(SKILLS_ROOT)
        self.recipients: list[str] = [NEW_RECIPIENT]
        self.known_recipients: list[str] = []
        self.compile_mode = "ok"  # "ok" | "raise" | a BAD_PLANS kind
        self.compile_calls: list[dict[str, Any]] = []
        self.resolver_calls: list[dict[str, Any]] = []
        self.layouts: dict[str, dict[str, Any]] = {}
        self.validate_calls: list[dict[str, Any]] = []
        self.last_plan: dict[str, Any] | None = None
        self.task_id = self.world_id = ""
        overrides = flow.app.dependency_overrides
        overrides[seam(deps, "get_plan_compiler")] = lambda: self.compile_plan
        overrides[seam(deps, "get_layout_builder")] = lambda: self.build_layout
        overrides[seam(deps, "get_unit_runner")] = lambda: self.runner
        overrides[seam(deps, "get_action_resolver")] = lambda: self.resolve_action
        overrides[seam(deps, "get_skill_registry")] = lambda: self.skills
        overrides[seam(deps, "get_connector_registry")] = lambda: self.registry
        overrides[seam(deps, "get_connector_adapters")] = lambda: {MOCK_ID: self.adapter}
        overrides[seam(deps, "get_outbox_store")] = lambda: self.outbox_store
        overrides[deps.get_event_writer] = lambda: self.writer
        overrides[seam(deps, "get_artifact_store")] = lambda: self.rig.store
        overrides[seam(deps, "get_redactor")] = lambda: self.rig.redactor
        overrides[seam(deps, "get_run_archive")] = lambda: self.rig.open_archive
        roles = ("director", "lead", "specialist", "verifier", "writer", "narrator")
        providers = {role: ClearModel() for role in roles}
        overrides[seam(deps, "get_must_ask_providers")] = lambda: providers  # judges every unit clear

    # the seam callables (keyword-only, as API_CL_INT_2.md fixes them)

    def compile_plan(self, *, brief: dict, approach: dict, budget_cap: float, context: Any = None) -> dict:
        self.timeline.append("compile")
        self.compile_calls.append(
            {"brief": copy.deepcopy(brief), "approach": copy.deepcopy(approach), "cap": budget_cap}
        )
        if self.compile_mode == "raise":
            raise RuntimeError("the Director could not compile a plan (scripted)")
        if self.compile_mode == "ok":
            self.last_plan = base_plan(approach["id"], budget_cap)
        else:
            self.last_plan = bad_plan(self.compile_mode, approach["id"], budget_cap)
        return copy.deepcopy(self.last_plan)

    def build_layout(self, plan: dict, *, world_id: str) -> dict:
        self.timeline.append("layout")
        self.layouts[world_id] = layout_for(plan, world_id=world_id)
        return copy.deepcopy(self.layouts[world_id])

    def resolve_action(self, *, unit: dict, action_type: str, item: dict, brief: dict) -> dict:
        self.resolver_calls.append({"unit": unit["id"], "action_type": action_type, "item": item, "brief": brief})
        return {
            "destination": DESTINATION,
            "recipients": list(self.recipients),
            "known_recipients": list(self.known_recipients),
        }

    def spy_validate_plan(self, monkeypatch: Any) -> None:
        """Records every `validate_plan` call (plan, result) on `validate_calls` and on the timeline."""
        import tilo_planning.plangraph as plangraph  # noqa: PLC0415

        original = plangraph.validate_plan

        def wrapper(plan: Any, *args: Any, **kwargs: Any) -> Any:
            result = original(plan, *args, **kwargs)
            self.timeline.append("validate")
            self.validate_calls.append({"plan": copy.deepcopy(plan), "violations": list(result)})
            return result

        monkeypatch.setattr(plangraph, "validate_plan", wrapper)
        for mod in list(sys.modules.values()):
            if getattr(mod, "__name__", "").startswith(
                ("tilo_api", "tilo_harness", "tilo_planning", "tilo_connectors")
            ):
                if getattr(mod, "validate_plan", None) is original:
                    monkeypatch.setattr(mod, "validate_plan", wrapper)

    # who is calling

    def as_member(self, user_id: str = FLOW_USER, role: str = "owner", districts: tuple[str, ...] = ()) -> None:
        from tilo_api import deps  # noqa: PLC0415

        self.flow._deny = False
        self.flow.principal = deps.Principal(user_id=user_id, role=role, world_id=self.world_id, districts=districts)  # type: ignore[arg-type]

    # the flow

    def start(self) -> dict[str, Any]:
        """Intake with nothing to ask, approaches fetched; the owner becomes a member of the task's world."""
        intake = self.flow.task_with_approaches()
        self.task_id, self.world_id = intake["task_id"], intake["world_id"]
        self.as_member()
        return intake

    def approve(self, cap: float = CAP, approach: str = "quick"):
        return self.flow.approve(self.task_id, approach, cap)

    def events(self, type_: str | None = None) -> list[dict[str, Any]]:
        return self.flow.events(self.world_id, type_)

    def types(self) -> list[str]:
        return [e["type"] for e in self.events()]

    def scope(self, owner: str = FLOW_USER) -> Any:
        """The Scope the run puts this world's artifacts in (org `deps.ORG_ID`, this world, the world's owner)."""
        return self.rig.scope(self.world_id, owner)

    def artifact_of(self, unit_id: str) -> dict[str, Any]:
        """The ref `artifact.created` announced for the one item `unit_id` made: its worker is the target of the
        unit's `agent.assigned`. Ids come from the stream, because the store mints them (ADR-0018 s6)."""
        stream = self.events()
        worker = next(e["target"] for e in stream if e["type"] == "agent.assigned" and e["data"]["unit"] == unit_id)
        made = [e for e in stream if e["type"] == "artifact.created" and e["actor"] == worker]
        assert len(made) == 1, f"expected one artifact.created by {unit_id}'s worker, got {len(made)}"
        return dict(made[0]["data"]["artifact"])

    def created_by_unit(self) -> dict[str, list[dict[str, Any]]]:
        """unit id -> the `artifact.created` events its worker wrote, in stream order."""
        stream = self.events()
        worker_of = {e["target"]: e["data"]["unit"] for e in stream if e["type"] == "agent.assigned"}
        found: dict[str, list[dict[str, Any]]] = {}
        for event in stream:
            if event["type"] == "artifact.created" and event["actor"] in worker_of:
                found.setdefault(worker_of[event["actor"]], []).append(event)
        return found

    def stream(self) -> list[dict[str, Any]]:
        return self.events()

    def after_grant(self) -> list[dict[str, Any]]:
        events = self.stream()
        granted = next((i for i, e in enumerate(events) if e["type"] == "budget.granted"), -1)
        return events[granted + 1 :]

    def cards(self):
        return self.flow.client.get(f"/worlds/{self.world_id}/cards")

    def answer(self, card_id: str, option: str, client: Any = None):
        return (client or self.flow.client).post(
            f"/worlds/{self.world_id}/cards/{card_id}/answer", json={"option": option}
        )

    def pause(self, client: Any = None):
        return (client or self.flow.client).post(f"/worlds/{self.world_id}/pause")

    def delivery(self):
        return self.flow.client.get(f"/worlds/{self.world_id}/delivery")

    def run_to_gate(self) -> tuple[dict[str, Any], dict[str, Any]]:
        """Start, approve, and wait for the gate: returns (approval.requested event, the gate card)."""
        self.start()
        response = self.approve()
        assert response.status_code == 200, response.text
        requested = wait_for(lambda: self.events("approval.requested"), what="approval.requested")[0]
        cards = wait_for(lambda: self.cards().json() if self.cards().status_code == 200 else None, what="the cards")
        gate_cards = [c for c in cards if c["kind"] == "gate"]
        assert len(gate_cards) == 1, cards
        return requested, gate_cards[0]

    def run_to_completion(self) -> tuple[dict[str, Any], dict[str, Any]]:
        requested, card = self.run_to_gate()
        response = self.answer(card["id"], "approve")
        assert response.status_code == 200, response.text
        wait_for(lambda: self.events("world.completed"), what="world.completed")
        return requested, card

    def quiet_stream(self, quiet_s: float = 0.5) -> list[dict[str, Any]]:
        settle(lambda: len(self.stream()), quiet_s=quiet_s)
        return self.stream()

    def close(self) -> None:
        self.runner.release.set()
        self.flow.close()
        self.rig.close()


# --- assertions shared by several test files --------------------------------------------------------------


def assert_stream_valid(rf: RunFlow, registry: Any) -> list[dict[str, Any]]:
    """The whole stream: strictly increasing, gap-free `seq`; unique ids; every event schema-valid and registered;
    and every event the run wrote passes the harness validator (event.rules.md EV-01..EV-14) against the layout
    the run was given, in order. Returns the stream."""
    from tilo_harness.validator import EventValidator, WorldState  # noqa: PLC0415

    events = rf.stream()
    assert [e["seq"] for e in events] == list(range(1, len(events) + 1)), [e["seq"] for e in events]
    assert len({e["id"] for e in events}) == len(events)
    registered = registered_event_types(REPO_ROOT)
    assert {e["type"] for e in events} <= registered, {e["type"] for e in events} - registered
    layout = rf.layouts.get(rf.world_id)
    assert layout is not None, "the run never asked the layout builder for this world's layout"
    assert not schema_errors("layout", layout), schema_errors("layout", layout)
    validator, state = EventValidator.from_repo(REPO_ROOT), WorldState(layout)
    state.world_id = rf.world_id
    granted = next(i for i, e in enumerate(events) if e["type"] == "budget.granted")
    for index, event in enumerate(events):
        assert_valid_event(REPO_ROOT, registry, event)
        if index > granted:
            problems = validator.problems(event, state)
            assert not problems, (event["seq"], event["type"], problems)
        state.observe(event)
    return events


def only(events: list[dict[str, Any]], type_: str) -> dict[str, Any]:
    found = [e for e in events if e["type"] == type_]
    assert len(found) == 1, f"expected exactly one {type_}, got {len(found)} in {[e['type'] for e in events]}"
    return found[0]


def index_of(events: list[dict[str, Any]], event: dict[str, Any]) -> int:
    return next(i for i, e in enumerate(events) if e["id"] == event["id"])


def build_run_flow(
    repo_root: pathlib.Path,
    *,
    ambiguous: list[str] | None = None,
    adapter_factory: Callable[[Any], Any] | None = None,
    covered: bool = False,
) -> RunFlow:
    """A fresh store, `Flow` (clear task: no questions) and `RunFlow`. Usable inside a Hypothesis example. The plan's
    send is T2 and, with no autonomy policy covering it, asks a question before its gate card (PRD 8.3, BQ-236);
    `covered` installs the owner's L1 policy for it, so a flow about the gate meets no question."""
    from _api_lib import make_store  # noqa: PLC0415
    from _clint1_lib import brief_reply, make_spy_safety  # noqa: PLC0415
    from tilo_connectors import InMemoryOutboxStore  # noqa: PLC0415

    store = make_store()
    flow = Flow(repo_root, store, make_spy_safety(), brief_reply([] if ambiguous is None else ambiguous))
    adapter = adapter_factory(mock_declaration()) if adapter_factory else None
    if covered:
        store.policies["pol_send_ask"] = covering_policy()
    return RunFlow(flow, InMemoryOutboxStore(), adapter)


__all__ = [
    "CAP",
    "DESTINATION",
    "FAKE_SECRET",
    "FLOW_USER",
    "KNOWN_RECIPIENT",
    "MOCK_ID",
    "NEW_RECIPIENT",
    "OTHER_USER",
    "POOL",
    "REPO_ROOT",
    "WORK_PREFIXES",
    "BAD_PLANS",
    "ArtifactRig",
    "ClearModel",
    "CrashAfterSendMock",
    "RunFlow",
    "assert_stream_valid",
    "bad_plan",
    "base_plan",
    "build_run_flow",
    "covering_policy",
    "index_of",
    "markdown_for",
    "layout_for",
    "only",
    "org_id",
    "plan_violations",
    "schema_errors",
    "settle",
    "wait_for",
]
