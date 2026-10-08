"""Helpers for the CL-INT-1 acceptance tests (CP2 thin slice, API flow; PRD 5.4 CP2, 7.1 FR-INT-01..08,
10.1, 16.3; ADR-0008). The HTTP shapes and injection seams these tests pin are in `API_CL_INT_1.md`.

Named `_clint1_lib` for the same global-bare-module-name reason as `_api_contracts_lib.py`.

Nothing here is business logic. `Flow` wires the real `tilo_api.app` to: a fake signed-in principal, the
in-memory `deps.Store`, a `SafetyProvider` spy, and a real `tilo_providers.router.Router` over a scripted
director provider (no network, no live mode). Seams the production code does not have yet resolve to a
placeholder dependency nothing uses, so a missing seam shows up as a missing route or a wrong response,
not as an `AttributeError` in test setup.
"""

from __future__ import annotations

import copy
import inspect
import json
import pathlib
import sys
from typing import Any

from _api_contracts_lib import INJECTION_PHRASE, make_docx_bytes, make_png_bytes
from _api_lib import FakeEventWriter

FLOW_USER = "u_flow_owner"
OTHER_USER = "u_flow_other"

# What the scripted Director returns. `ambiguous_fields` is the Director's own extra key
# (packages/planning brief.output_schema); the brief itself is contracts/brief.schema.json.
_BASE_BRIEF: dict[str, Any] = {
    "goal": "Summarise the weekly supplier prices for the operations lead.",
    "deliverables": [{"title": "Supplier summary", "format": "pdf"}],
    "audience": "Operations lead",
    "deadline": None,
    "constraints": [],
    "sources": [],
    "sensitivity": "business",
}


def brief_reply(ambiguous: list[str]) -> dict[str, Any]:
    return {**copy.deepcopy(_BASE_BRIEF), "ambiguous_fields": ambiguous}


# Two approaches that differ on 4 of the 5 dimensions (PG-08), ranges ordered (PG-09). The credits are
# deliberately not equal to any budget cap the tests confirm (PRD 10.1, #106: never the model's number).
APPROACHES_REPLY: dict[str, Any] = {
    "approaches": [
        {
            "id": "quick",
            "label": "Quick scan",
            "summary": "Quick scan: overview research over 3 sources.",
            "dimensions": {
                "depth": "overview", "sources": 3, "parallelism": 3, "verification": "basic", "output_format": "pdf",
            },
            "time": {"min_s": 180, "max_s": 300},
            "credits": {"min": 30, "max": 45},
            "risks": ["A supplier may not have published prices"],
            "skips": ["Warranty terms"],
        },
        {
            "id": "thorough",
            "label": "Thorough review",
            "summary": "Thorough review: deep research over 8 sources.",
            "dimensions": {
                "depth": "deep", "sources": 8, "parallelism": 4, "verification": "thorough",
                "output_format": "pptx",
            },
            "time": {"min_s": 600, "max_s": 900},
            "credits": {"min": 90, "max": 130},
            "risks": ["A supplier may not have published prices"],
            "skips": [],
        },
    ]
}  # fmt: skip


class RoleScriptedProvider:
    """Answers by what the request asks for (the response schema), not by call order, so a test never
    depends on how many repairs or retries the code makes. Records every request."""

    profile_id = "scripted"

    def __init__(self, brief: dict[str, Any], approaches: dict[str, Any]) -> None:
        self.brief, self.approaches = brief, approaches
        self.calls: list[Any] = []

    def generate(self, request: Any) -> Any:
        from tilo_providers.interfaces import GenerateResponse  # noqa: PLC0415

        self.calls.append(request)
        properties = (request.response_schema or {}).get("properties", {})
        if "ambiguous_fields" in properties:
            text = json.dumps(self.brief)
        elif "approaches" in properties:
            text = json.dumps(self.approaches)
        else:
            raise AssertionError("an unexpected model call: neither a brief nor an approaches request")
        return GenerateResponse(text=text, profile_id=self.profile_id)

    def stream(self, request: Any):
        yield self.generate(request)

    def embed(self, request: Any) -> Any:
        raise NotImplementedError

    def count_tokens(self, text: str) -> int:
        return len(text.split())

    def capabilities(self) -> set[Any]:
        from tilo_providers.interfaces import Capability  # noqa: PLC0415

        return {Capability.JSON}

    def price(self) -> Any:
        from tilo_providers.interfaces import PriceQuote  # noqa: PLC0415

        return PriceQuote(input=0.0, output=0.0)


def make_spy_safety() -> Any:
    """A deterministic SafetyProvider that records every call: (text, content-is-native, mime_type)."""
    from tilo_providers.interfaces import SafetyProvider  # noqa: PLC0415

    class SpySafety(SafetyProvider):
        def __init__(self) -> None:
            self.calls: list[tuple[str, bool, str | None]] = []

        def _check(self, text: str, *, content: bytes | None = None, mime_type: str | None = None) -> Any:
            self.calls.append((text, content is not None, mime_type))
            flagged = INJECTION_PHRASE in text.upper()
            return {"flagged": flagged, "reason": "instruction aimed at the assistant" if flagged else None}

    return SpySafety()


def build_router(repo_root: pathlib.Path, provider: RoleScriptedProvider) -> Any:
    """A real Router over the shipped config/models.yaml and prices.yaml; every profile is the scripted one."""
    from tilo_providers.config import load_providers_config  # noqa: PLC0415
    from tilo_providers.router import Router  # noqa: PLC0415

    config = load_providers_config(repo_root / "config" / "models.yaml", repo_root / "config" / "prices.yaml")
    return Router(config, provider_for_profile=lambda _profile_id: provider)


def _missing_seam() -> None:  # a placeholder key for dependency_overrides that no route depends on
    raise NotImplementedError


def seam(module: Any, name: str) -> Any:
    return getattr(module, name, _missing_seam)


def spy_on(monkeypatch: Any, module: Any, name: str) -> list[dict[str, Any]]:
    """Wraps `module.name` (and any `tilo_api.*` module that imported the same function object) and returns a
    list that receives each call's bound arguments."""
    original = getattr(module, name)
    bound_calls: list[dict[str, Any]] = []

    def wrapper(*args: Any, **kwargs: Any) -> Any:
        bound_calls.append(dict(inspect.signature(original).bind(*args, **kwargs).arguments))
        return original(*args, **kwargs)

    monkeypatch.setattr(module, name, wrapper)
    for mod in list(sys.modules.values()):
        if getattr(mod, "__name__", "").startswith("tilo_api") and getattr(mod, name, None) is original:
            monkeypatch.setattr(mod, name, wrapper)
    return bound_calls


def models_yaml(*, safety_provider: str | None, with_safety: bool = True) -> dict[str, Any]:
    """A models.yaml whose profiles reuse ids that config/prices.yaml already prices (the loader needs one
    per profile), all with fake model names. `safety_provider` is the provider slug of the safety profile."""
    profile = {"model": "fake-model", "context": 1000, "caps": ["json"]}
    config: dict[str, Any] = {
        "example": True,
        "profiles": {
            "flash-38": {"provider": "fake", **profile},
            "flash-37": {"provider": "fake", **profile},
            "lite-31": {"provider": safety_provider or "fake", **profile},
        },
        "roles": {"director": {"primary": "flash-38", "fallback": "flash-37"}},
        "rules": {"deny": []},
    }
    if with_safety:
        config["roles"]["safety"] = {"primary": "lite-31", "fallback": "flash-37"}
    return config


class Flow:
    """The real app, with the injected seams. Use `as_user` to switch the signed-in principal."""

    def __init__(self, repo_root: pathlib.Path, store: Any, safety: Any, brief: dict[str, Any]) -> None:
        from fastapi import HTTPException  # noqa: PLC0415
        from fastapi.testclient import TestClient  # noqa: PLC0415
        from tilo_api import app, deps  # noqa: PLC0415
        from tilo_api import intake as intake_module  # noqa: PLC0415

        self.store, self.safety = store, safety
        self.provider = RoleScriptedProvider(brief, copy.deepcopy(APPROACHES_REPLY))
        self.router = build_router(repo_root, self.provider)
        self.principal = deps.Principal(user_id=FLOW_USER, role="owner")
        self._deny = False
        self._http_exc = HTTPException

        def current_principal() -> Any:
            if self._deny:
                raise self._http_exc(status_code=401, detail="not signed in")
            return self.principal

        app.dependency_overrides[deps.get_current_principal] = current_principal
        app.dependency_overrides[deps.get_store] = lambda: store
        self.writer = FakeEventWriter(store)  # every event of the flow goes through the single writer (ADR-0026)
        app.dependency_overrides[deps.get_event_writer] = lambda: self.writer
        app.dependency_overrides[seam(deps, "get_router")] = lambda: self.router
        if safety is not None:
            app.dependency_overrides[intake_module.get_safety] = lambda: safety
        self.app = app
        self.client = TestClient(app, raise_server_exceptions=False)

    def close(self) -> None:
        self.app.dependency_overrides.clear()

    # --- who is calling -------------------------------------------------------------------------

    def as_user(self, user_id: str, role: str = "owner") -> None:
        from tilo_api import deps  # noqa: PLC0415

        self._deny = False
        self.principal = deps.Principal(user_id=user_id, role=role)  # type: ignore[arg-type]

    def sign_out(self) -> None:
        self._deny = True

    # --- the four flow calls --------------------------------------------------------------------

    def intake(self, text: str = "Prepare the weekly supplier summary.", files: list[tuple[str, bytes]] | None = None):
        parts = [("files", (name, content, "application/octet-stream")) for name, content in files or []]
        return self.client.post("/intake", data={"text": text}, files=parts)

    def new_task(self, **kwargs: Any) -> dict[str, Any]:
        response = self.intake(**kwargs)
        assert response.status_code == 201, response.text
        body = response.json()
        missing = {"task_id", "brief", "questions", "files"} - set(body)
        assert not missing, f"POST /intake response lacks {sorted(missing)}: {sorted(body)}"
        return body

    def answers(self, task_id: str, answers: list[dict[str, Any]], brief_edits: dict[str, Any] | None = None):
        return self.client.post(
            f"/tasks/{task_id}/answers", json={"answers": answers, "brief_edits": brief_edits or {}}
        )

    def approaches(self, task_id: str):
        return self.client.get(f"/tasks/{task_id}/approaches")

    def approve(self, task_id: str, approach_id: str, budget_cap: Any):
        return self.client.post(
            f"/tasks/{task_id}/approve", json={"approach_id": approach_id, "budget_cap": budget_cap}
        )

    def approve_raw(self, task_id: str, body: str):
        """The request body as literal JSON text, for values a Python dict cannot carry (NaN, Infinity)."""
        return self.client.post(f"/tasks/{task_id}/approve", content=body, headers={"content-type": "application/json"})

    # --- the flow up to a point -----------------------------------------------------------------

    def task_with_approaches(self) -> dict[str, Any]:
        """A task whose brief had no questions, with its approaches fetched. Returns the intake body."""
        intake = self.new_task()
        assert intake["questions"] == [], intake
        response = self.approaches(intake["task_id"])
        assert response.status_code == 200, response.text
        return intake

    def answered_task(self) -> dict[str, Any]:
        """A task with questions (the audience and the deadline), every question answered or skipped."""
        intake = self.new_task()
        fields = {q["field"] for q in intake["questions"]}
        assert fields, intake
        answers = [{"field": q["field"], "answer": None} for q in intake["questions"]]
        assert self.answers(intake["task_id"], answers).status_code == 200
        return intake

    # --- events the API wrote -------------------------------------------------------------------

    def events(self, world_id: str, type_: str | None = None) -> list[dict[str, Any]]:
        found = list(self.store.events.get(world_id, []))
        return [e for e in found if type_ is None or e["type"] == type_]


def registered_event_types(repo_root: pathlib.Path) -> set[str]:
    import yaml  # noqa: PLC0415

    registry = yaml.safe_load((repo_root / "contracts" / "events" / "registry.yaml").read_text(encoding="utf-8"))
    return set(registry["types"])


__all__ = [
    "APPROACHES_REPLY",
    "FLOW_USER",
    "OTHER_USER",
    "Flow",
    "RoleScriptedProvider",
    "brief_reply",
    "make_docx_bytes",
    "make_png_bytes",
    "make_spy_safety",
    "models_yaml",
    "registered_event_types",
    "seam",
    "spy_on",
]
