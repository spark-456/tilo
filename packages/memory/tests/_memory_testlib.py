"""Helpers for the FR-MEM-01 / FR-MEM-02 acceptance tests (PRD 13.1 memory layers, result cache).

Named `_memory_testlib` (not `_lib` or `conftest` imports) for the reason `packages/planning/tests/
_planning_contracts_lib.py` documents: this directory has no `__init__.py`, so pytest's "prepend" import
mode makes every helper module name global for the whole `uv run pytest` session.

`tilo_memory` does not exist yet: `packages/memory` is a new uv workspace package the builder creates
(workspace member, `pyproject.toml`, `CLAUDE.md`, `src/tilo_memory/`). Until then every test module here
fails at collection with `ModuleNotFoundError: No module named 'tilo_memory'`. That is the right failure.

The public interface these tests are written against is THIS PASS'S design (the PRD names the behaviour,
not the API). It is logged as BQ-191 in `docs/open-questions.md`; a builder may propose a better one but
must then update the tests to match rather than weaken them:

    from tilo_memory.cache import CacheRequest, Fetched, ResultCache

    cache = ResultCache(clock=<() -> aware datetime>, fit_check=<(CacheRequest, value) -> bool>,
                        verifier=<(CacheRequest, value) -> bool>, lookup_cost=<credits>)
    result = cache.get_or_fetch(CacheRequest(kind, text, fingerprint), fetch, base=<event base>, seq=<int>)

    `kind` is "web", "file" or "email_body". `fetch` is `() -> Fetched(value, origin_cost)`; it is called
    exactly when the cache does not reuse a result. `result` has `.value`, `.outcome` ("hit" | "miss"),
    `.reason` (None on a hit, else one of "absent", "stale", "not_cacheable", "fit_rejected",
    "verifier_rejected"), `.saved` (credits, 0.0 on a miss) and `.events` (a list: one `memory.hit` TiloEvent
    on a hit, empty on a miss). `cache.log` is an append-only list of lookup records with `.outcome`,
    `.reason` and `.saved`; `cache.credits_saved` is the running total of `saved` over accepted reuses.
`fit_check` is the model-backed fit check and `verifier` the Verifier (role `verifier`); both are injected
here as fakes. Production wiring of those two through `packages/providers` (PL-01) is the builder's.
"""

from __future__ import annotations

import json
import pathlib
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any

import jsonschema
from referencing import Registry, Resource
from referencing.jsonschema import DRAFT202012
from tilo_memory.cache import CacheRequest, Fetched, ResultCache

REPO_ROOT = pathlib.Path(__file__).resolve().parents[3]

T0 = datetime(2026, 10, 1, 9, 0, 0, tzinfo=UTC)
LOOKUP_COST = 0.5
ORIGIN_COST = 6.0
DAY = timedelta(days=1)
WEB_FRESH_FOR = timedelta(days=7)  # PRD 13.1: "Web results fresh for 7 days"


class FakeClock:
    """The cache's only source of time: tests advance it, nothing sleeps."""

    def __init__(self, start: datetime = T0) -> None:
        self.now = start

    def __call__(self) -> datetime:
        return self.now

    def advance(self, delta: timedelta) -> None:
        self.now = self.now + delta


class Decider:
    """A fake fit check or Verifier: records every (request, value) it is shown and answers a fixed bool."""

    def __init__(self, accept: bool = True) -> None:
        self.accept = accept
        self.calls: list[tuple[CacheRequest, Any]] = []

    def __call__(self, request: CacheRequest, value: Any) -> bool:
        self.calls.append((request, value))
        return self.accept


class Fetcher:
    """A fake source. Every call is counted; the value changes with each call so a refetch is visible."""

    def __init__(self, prefix: str = "table", origin_cost: float = ORIGIN_COST) -> None:
        self.prefix = prefix
        self.origin_cost = origin_cost
        self.calls = 0

    def __call__(self) -> Fetched:
        self.calls += 1
        return Fetched(value=f"{self.prefix}-v{self.calls}", origin_cost=self.origin_cost)


class Rig:
    """One cache wired to a fake clock, fit check and Verifier, plus its own event `seq` counter."""

    def __init__(self, *, fit: bool = True, verify: bool = True, lookup_cost: float = LOOKUP_COST) -> None:
        self.clock = FakeClock()
        self.fit = Decider(fit)
        self.verifier = Decider(verify)
        self.cache = ResultCache(clock=self.clock, fit_check=self.fit, verifier=self.verifier, lookup_cost=lookup_cost)
        self.seq = 100

    def get(self, request: CacheRequest, fetch: Callable[[], Fetched]):
        result = self.cache.get_or_fetch(request, fetch, base=event_base(), seq=self.seq)
        self.seq += 1
        return result


def web(text: str = "supplier price table", fingerprint: str = "sha256-aaaa") -> CacheRequest:
    return CacheRequest(kind="web", text=text, fingerprint=fingerprint)


def event_base(**overrides: Any) -> dict[str, Any]:
    """PRD 9.3 envelope base (v/ts/world_id/run_id/actor), as `get_or_fetch` takes it (same shape as
    `tilo_planning.questions.generate_questions(base=...)`)."""
    base = {
        "v": "1.0",
        "ts": "2026-10-01T09:00:00.000Z",
        "world_id": "w_testworld00000000000000",
        "run_id": "r_testrun0000000000000000",
        "actor": "A_s1",
    }
    base.update(overrides)
    return base


# --- contract validation (a deliberately small copy of the planning/archive helpers) ----------------


def build_registry() -> Registry:
    resources: list[tuple[str, Resource]] = []
    for path in sorted((REPO_ROOT / "contracts").glob("**/*.schema.json")):
        data = json.loads(path.read_text(encoding="utf-8"))
        uri = data.get("$id") or path.resolve().as_uri()
        resources.append((uri, Resource.from_contents(data, default_specification=DRAFT202012)))
    return Registry().with_resources(resources)


def assert_valid_memory_hit(event: dict[str, Any]) -> None:
    """The emitted event validates against `event.schema.json` and `events/data/memory.hit.schema.json`."""
    registry = build_registry()
    for rel in ("event.schema.json", "events/data/memory.hit.schema.json"):
        schema = json.loads((REPO_ROOT / "contracts" / rel).read_text(encoding="utf-8"))
        instance = event if rel == "event.schema.json" else event["data"]
        errors = list(jsonschema.Draft202012Validator(schema, registry=registry).iter_errors(instance))
        assert not errors, f"memory.hit fails {rel}: {[e.message for e in errors]}"
