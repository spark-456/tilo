"""Runs one bank case end to end on fakes (issue #272, GEN-02; PRD 6.6, EFF-01).

The real tilo-api runs in process: intake -> questions -> approaches -> approve -> plan -> run -> gates -> delivery.
Only the model seam is scripted (`ScriptedDirector`, through the provider layer's Router); the unit runner, the
recipient and the connector adapters are the dev stand-ins that only record. No network and no paid call: a live or
deployed environment is refused before anything starts. Imports of the services are lazy, so the 160-case replay
harness does not load them.
"""

from __future__ import annotations

import os
import time
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Any

from .bank import BankCase
from .scripted import ScriptedDirector

_REFUSED_ENV = ("LIVE", "K_SERVICE", "CLOUD_RUN_JOB")
DEFAULT_TIMEOUT_S = 30.0
DEFAULT_CAP = 50.0
_POLL_S = 0.05


class BankRefused(RuntimeError):
    """The environment is live or deployed: the bank never runs there (EFF-01)."""


@dataclass
class Observation:
    case: BankCase
    outcome: str | None = None  # completed | held_at_gate | refused | needs_answers, or None: no terminal state
    reason: str | None = None  # what the person is told when the pipeline stops short
    world_id: str | None = None
    events: list[dict[str, Any]] = field(default_factory=list)
    cards: list[dict[str, Any]] = field(default_factory=list)
    http: list[tuple[str, str, int]] = field(default_factory=list)
    questions: int = 0
    answered: dict[str, str | None] = field(default_factory=dict)  # question field -> the answer sent
    plan: dict[str, Any] | None = None
    delivery: dict[str, Any] | None = None
    cap: float = 0.0
    approved_gates: int = 0
    sent_at_first_gate: int | None = None  # what the mock connectors had sent when the first gate card appeared
    sent_total: int = 0
    director_calls: list[str] = field(default_factory=list)
    crash: str | None = None
    timed_out: bool = False
    seconds: float = 0.0


@contextmanager
def _dev_env() -> Iterator[None]:
    if any(name in os.environ for name in _REFUSED_ENV):
        raise BankRefused("the generality bank runs on fakes only: LIVE, K_SERVICE and CLOUD_RUN_JOB must be unset")
    from tilo_api import dev  # noqa: PLC0415

    keep = {k: os.environ.get(k) for k in ("TILO_MODELS_FILE", "TILO_DEV_UNIT_DELAY_S")}
    os.environ["TILO_MODELS_FILE"] = str(dev.DEV_MODELS)
    os.environ["TILO_DEV_UNIT_DELAY_S"] = "0"
    try:
        yield
    finally:
        for key, value in keep.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


def _app(director: ScriptedDirector) -> Any:
    from fastapi import FastAPI  # noqa: PLC0415
    from tilo_api import deps, dev, runs  # noqa: PLC0415
    from tilo_api.cards import build_router  # noqa: PLC0415
    from tilo_api.dispatch import router as dispatch_router  # noqa: PLC0415
    from tilo_api.intake import router as intake_router  # noqa: PLC0415
    from tilo_api.redaction import router as redaction_router  # noqa: PLC0415
    from tilo_api.tasks import router as tasks_router  # noqa: PLC0415
    from tilo_planning.compiler import compile_plan  # noqa: PLC0415
    from tilo_providers.router import Router  # noqa: PLC0415

    app = FastAPI()
    for api_router in (intake_router, dispatch_router, redaction_router, tasks_router, runs.router):
        app.include_router(api_router)
    app.include_router(build_router(runs.get_card_store, answer_guard=runs.answer_guard))
    dev.install(app, {})
    router = Router(deps.providers_config(), provider_for_profile=lambda _profile: director)

    def compiler() -> Any:
        def compile_with_script(*, brief: dict, approach: dict, budget_cap: float, context: Any) -> dict:
            return compile_plan(brief, approach, budget_cap, context, router=router).plan

        return compile_with_script

    app.dependency_overrides[deps.get_router] = lambda: router
    app.dependency_overrides[deps.get_plan_compiler] = compiler
    return app


def _detail(response: Any) -> str:
    try:
        body = response.json()
        said = body.get("detail") or body.get("error")  # most routes say `detail`; intake says `error`
    except (ValueError, AttributeError):
        said = None
    return said if isinstance(said, str) and said else f"HTTP {response.status_code}"


def drive(case: BankCase, obs: Observation, timeout_s: float, app: Any, person: Any = None) -> None:
    """Intake to a terminal state through `app`'s own routes (the live runner passes its own wiring). With `person`,
    a person answers the questions, picks or declines the approach and says yes or no to each gate card."""
    from fastapi.testclient import TestClient  # noqa: PLC0415
    from tilo_api import deps, dev  # noqa: PLC0415

    client = TestClient(app, base_url=f"http://localhost:{dev.PORT}", raise_server_exceptions=False)
    store = app.dependency_overrides[deps.get_store]()
    adapters = app.dependency_overrides[deps.get_connector_adapters]()

    def call(method: str, path: str, **kwargs: Any) -> Any:
        response = client.request(method, path, **kwargs)
        obs.http.append((method, path, response.status_code))
        return response

    def sent() -> int:
        return sum(len(adapter.sent) for adapter in adapters.values())

    def fail(response: Any, *, honest: tuple[int, ...] = ()) -> bool:
        """True when the pipeline stopped: an honest 4xx (or a listed 5xx) is a refusal, any other 5xx a crash."""
        if response.status_code < 400:
            return False
        if response.status_code >= 500 and response.status_code not in honest:
            obs.crash = f"HTTP {response.status_code} from {response.request.url.path}: {_detail(response)}"
        else:
            obs.outcome, obs.reason = "refused", _detail(response)
        return True

    try:
        files = [("files", (f["name"], f["text"].encode("utf-8"), "text/plain")) for f in case.files]
        intake = call("POST", "/intake", data={"text": case.brief}, files=files or None)
        if fail(intake, honest=(502,)):  # 502: "The Director could not draft a brief", said on purpose
            return
        task = intake.json()
        obs.world_id, obs.questions = task["world_id"], len(task["questions"])
        if case.stop_after == "questions":
            obs.outcome = "needs_answers" if obs.questions else None
            return
        given = case.answers or {}
        pick = person.answer if person else lambda q: given.get(q["field"])
        answers = [{"field": q["field"], "answer": pick(q)} for q in task["questions"]]
        obs.answered = {a["field"]: a["answer"] for a in answers}
        if fail(call("POST", f"/tasks/{task['task_id']}/answers", json={"answers": answers, "brief_edits": {}})):
            return
        approaches = call("GET", f"/tasks/{task['task_id']}/approaches")
        if fail(approaches, honest=(502,)):  # 502: "The Director could not propose approaches", said on purpose
            return
        offered = approaches.json()
        wanted = (case.approve or {}).get("approach") or offered["recommended"]
        if person is not None and (wanted := person.approach(offered)) is None:
            obs.outcome, obs.reason = "declined", "the person declined the approach; nothing ran"
            return
        obs.cap = float((case.approve or {}).get("cap", DEFAULT_CAP))
        body = {"approach_id": wanted, "budget_cap": obs.cap}
        if fail(call("POST", f"/tasks/{task['task_id']}/approve", json=body)):
            return

        answered: set[str] = set()
        deadline = time.monotonic() + timeout_s
        while time.monotonic() < deadline:
            types = {e["type"] for e in store.events.get(obs.world_id, [])}
            if "world.failed" in types:
                failed = next(e for e in store.events[obs.world_id] if e["type"] == "world.failed")
                obs.outcome, obs.reason = "refused", str(failed["data"].get("reason") or failed["summary"])
                break
            if "world.completed" in types:
                obs.outcome = "completed"
                break
            for card in call("GET", f"/worlds/{obs.world_id}/cards").json():
                if card["kind"] != "gate" or card["id"] in answered:
                    continue
                if obs.sent_at_first_gate is None:
                    obs.sent_at_first_gate = sent()
                asked = time.monotonic()
                if not (person.gate(card) if person is not None else case.gates != "hold"):
                    obs.outcome = "held_at_gate"
                    break
                deadline += time.monotonic() - asked  # the time a person takes is not the run's
                answered.add(card["id"])
                reply = call("POST", f"/worlds/{obs.world_id}/cards/{card['id']}/answer", json={"option": "approve"})
                if reply.status_code == 200:
                    obs.approved_gates += 1
            if obs.outcome:
                break
            time.sleep(_POLL_S)
        else:
            obs.timed_out = True
    finally:
        if obs.world_id:
            obs.events = list(store.events.get(obs.world_id, []))
            obs.cards = list(client.get(f"/worlds/{obs.world_id}/cards").json()) if obs.events else []
            run = store.runs.get(obs.world_id)
            obs.plan = run.plan if run is not None and run.plan else None
            if obs.outcome == "completed":
                delivery = call("GET", f"/worlds/{obs.world_id}/delivery")
                obs.delivery = delivery.json() if delivery.status_code == 200 else None
            if obs.outcome in (None, "held_at_gate"):
                client.post(f"/worlds/{obs.world_id}/pause")  # end the run's thread; a held gate never times out
        obs.sent_total = sent()


def run_case(case: BankCase, *, timeout_s: float = DEFAULT_TIMEOUT_S) -> Observation:
    """One end-to-end run; a crash is recorded, never raised (a refused environment is the one exception)."""
    obs = Observation(case=case)
    started = time.monotonic()
    with _dev_env():
        director = ScriptedDirector(case.director)
        try:
            drive(case, obs, timeout_s, _app(director))
        except BankRefused:
            raise
        except Exception as exc:  # noqa: BLE001 - a crash is an observation: the checks report it
            obs.crash = f"{type(exc).__name__}: {exc}"
        obs.director_calls = list(director.calls)
    obs.seconds = round(time.monotonic() - started, 3)
    return obs
