"""SKILL-ROUTE: the skills a person may use, and which one fits a task (FR-SKL-04, FR-AGT-03, EFF-04; ADR-0051).

`GET /v1/skills/catalog` lists, for the signed-in person only, the library skills, the taught skills they own and the
shared taught skills of their current teams (the existing visibility rules; a draft is never listed). The matcher embeds
the task text with the `embed` role against the entries' cached description embeddings and answers the best one only
when its cosine score reaches `config/skills.yaml` `route.min_score`. When the top two are within `route.tie_margin` one
cheap `assistant` call picks between them; a failed call keeps the deterministic order (score, then id). An explicitly
tagged skill always wins and the matcher is not run. Nothing here authorises anything: a match only pins a library skill
the Director could have chosen, and text, names and descriptions are data. A failure anywhere is "no match".
"""

from __future__ import annotations

import hashlib
import inspect
import json
import logging
import math
import threading
from collections import OrderedDict
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Annotated, Any, Literal

import yaml
from fastapi import Depends, Request
from tilo_planning.compiler import DELIVER
from tilo_providers.interfaces import EmbedRequest, GenerateRequest
from tilo_providers.prompts import load_prompt, neutralise_marker
from tilo_providers.router import Router
from tilo_providers.schema_guard import first_error

from tilo_api import deps

logger = logging.getLogger("tilo_api.skills_route")
_ROOT = Path(__file__).resolve().parents[4] / "config"

CATALOG_MAX = 60  # one embed call holds 64 texts: the query and up to 63 entries
_CACHE_MAX = 512
_PICK = {
    "type": "object",
    "additionalProperties": False,
    "required": ["pick"],
    "properties": {"pick": {"enum": ["a", "b", "none"]}},
}
_cache: OrderedDict[tuple[str, int, str], list[float]] = OrderedDict()
_lock = threading.Lock()


@dataclass(frozen=True)
class RouteConfig:
    min_score: float
    tie_margin: float
    dimensions: int


def load_route_config(root: Path = _ROOT) -> RouteConfig:
    """`config/skills.yaml` `route`; a missing or unusable value falls back to the shipped number."""
    try:
        raw = yaml.safe_load((root / "skills.yaml").read_text(encoding="utf-8"))["route"]
        score, margin, dims = float(raw["min_score"]), float(raw["tie_margin"]), int(raw["dimensions"])
        if 0 < score <= 1 and 0 <= margin < 1 and 64 <= dims <= 2048:
            return RouteConfig(score, margin, dims)
    except Exception:
        logger.warning("config/skills.yaml route not read; using the shipped numbers")
    return RouteConfig(0.78, 0.02, 256)


# --- the catalog -------------------------------------------------------------------------------------------------


def _line(value: Any, limit: int) -> str:
    return " ".join(str(value).split())[:limit]


def library_entries(registry: Any) -> list[dict[str, Any]]:
    from tilo_api.skills_routes import (
        INTERNAL_BUILTIN_DOMAINS,  # noqa: PLC0415 - it imports modules that import this one
    )

    out = []
    for skill_id, description in registry.catalog():
        folder = registry.folder(skill_id)
        if folder is None or folder.parent.name in INTERNAL_BUILTIN_DOMAINS:
            continue
        try:
            manifest = yaml.safe_load((folder / "skill.yaml").read_text(encoding="utf-8"))
            schema = manifest.get("inputs") or {}
            required = set(schema.get("required") or ())
            inputs = [
                {"name": n, "label": _line(p.get("description") or n, 80), "kind": _kind(p), "required": n in required}
                for n, p in list((schema.get("properties") or {}).items())[:8]
            ]
            tools = [str(t) for t in manifest.get("tools_allowed") or ()]
        except Exception:  # noqa: BLE001 - a skill whose files cannot be read is listed without detail
            inputs, tools = [], []
        out.append(
            {
                "id": skill_id,
                "kind": "library",
                "scope": "library",
                "name": skill_id.replace("-", " "),
                "purpose": _line(description, 200),
                "inputs": inputs,
                "tools": tools,
                "version": registry.version(skill_id),
            }  # fmt: skip
        )
    return out


def _kind(prop: Any) -> str:
    kind = prop.get("type") if isinstance(prop, dict) else None
    return {"integer": "number", "number": "number"}.get(kind if isinstance(kind, str) else "", "text")


def taught_entries(records: list[dict[str, Any]], user: str) -> list[dict[str, Any]]:
    from tilo_api.skills_routes import WRITER  # noqa: PLC0415

    out = []
    for r in records:
        if r.get("paused"):  # a paused skill is not offered, matched or tagged (TS-10, FR-SKL-06)
            continue
        steps = "; ".join(_line(s["text"], 60) for s in r["plan"][:3])
        tools = list(dict.fromkeys(s["tool"] for s in r["plan"] if s["tool"] != WRITER[0]))
        out.append(
            {
                "id": r["id"],
                "kind": "taught",
                "scope": "mine" if r["owner"] == user else "team",
                "name": _line(r["name"], 80),
                "purpose": _line(steps, 200),
                "inputs": list(r.get("inputs", [])),
                "tools": tools,
                "version": r["version"],
            }  # fmt: skip
        )
    return out


@dataclass
class SkillContext:
    """Per request: the caller's catalog and the matcher. Everything it reads is the caller's own view."""

    user: str
    registry: Any
    read_taught: Callable[[], list[dict[str, Any]]]
    router: Router | None
    budget: float | None = None  # credits left to this caller's ask (Quick's hold): a call is priced out of it
    failed: bool = False  # the last best_for ended on a failure or a refusal, not on "nothing fits"

    def catalog(self, limit: int | None = CATALOG_MAX) -> list[dict[str, Any]]:
        """The library skills and, if the stores can be read, the caller's taught ones. Advisory: a store that cannot
        be read leaves those out; it never fails the request that asked."""
        try:
            entries = library_entries(self.registry)
        except Exception as exc:  # noqa: BLE001
            logger.warning("skill library not read: %s", type(exc).__name__)
            entries = []
        try:
            entries += taught_entries(self.read_taught(), self.user)
        except Exception as exc:  # noqa: BLE001
            logger.warning("taught skills not read: %s", type(exc).__name__)
        return entries[:limit]

    def match(self, text: str, *, tagged: str | None = None) -> dict[str, Any] | None:
        """The one skill that fits `text`, or None. `tagged` (an id the person named) wins when they may use it."""
        if tagged is not None:
            return self.resolve_tag(None, tagged)
        return self.best_for(text)

    def best_for(self, text: str) -> dict[str, Any] | None:
        """The skill that fits `text` by score alone (no tag): None below the threshold or on any failure."""
        self.failed = False
        entries = self.catalog()
        if not entries or self.router is None or not text.strip():
            return None
        if self.budget is not None and self.budget <= 0:  # a capped caller sends no embedding at all
            self.failed = True
            return None
        try:
            return _match(self, text, entries, load_route_config())
        except Exception as exc:  # noqa: BLE001
            self.failed = True
            logger.warning("skill match failed: %s", type(exc).__name__)
            return None

    def resolve_tag(self, kind: str | None, ref_id: str) -> dict[str, Any] | None:
        """A skill the person tagged, as the caller may use it now (MN-02): `kind` is the ref's (`skill` is a library
        skill, `taught_skill` a taught one). Anything else, or a skill not in their view, is None: one answer."""
        wanted = {"skill": "library", "taught_skill": "taught"}.get(kind or "")
        found = next((e for e in self.catalog(None) if e["id"] == ref_id and wanted in (None, e["kind"])), None)
        return None if found is None else _data(found, 1.0, "tagged")

    def taught_plan(self, tagged: dict[str, Any] | None) -> list[dict[str, Any]] | None:
        """Return the readable version's stored steps for an explicitly tagged taught skill."""
        if tagged is None or tagged.get("kind") != "taught":
            return None
        try:
            record = next(
                (
                    row
                    for row in self.read_taught()
                    if row.get("id") == tagged["id"]
                    and row.get("version") == tagged["version"]
                    and not row.get("paused")
                ),
                None,
            )
        except Exception as exc:  # noqa: BLE001 - intake already resolved visibility; a second read fails closed
            logger.warning("tagged taught skill plan not read: %s", type(exc).__name__)
            return None
        return None if record is None else json.loads(json.dumps(record["plan"]))

    def block(self) -> str:
        """The catalog as fenced data for a prompt: one line per skill, name and purpose only."""
        lines = [f"{e['name']}: {e['purpose']}" for e in self.catalog()]
        body = neutralise_marker("\n".join(lines), "SKILLS")
        return f"<<<SKILLS\n{body}\nSKILLS>>>" if lines else ""


def _data(entry: dict[str, Any], score: float, source: str) -> dict[str, Any]:
    keys = ("id", "kind", "scope", "name", "version")
    return {**{k: entry[k] for k in keys}, "score": round(score, 4), "source": source}


# --- the matcher -------------------------------------------------------------------------------------------------


def _doc(entry: dict[str, Any]) -> str:
    return f"{entry['name']}: {entry['purpose']}"[:500]


def _embed(
    ctx: SkillContext, texts: list[str], task: Literal["document", "query"], dims: int
) -> tuple[str, list[list[float]]]:
    # a deployed router is a MeteredRouter: its embeddings are SEC-16 units, named `metered_embed`; a Router has `embed`
    if ctx.router is None:
        raise ValueError("no router")
    call = getattr(ctx.router, "metered_embed", None) or ctx.router.embed
    result = call("embed", EmbedRequest(texts=texts, task=task, dimensions=dims), **_budgeted(ctx))
    _spent(ctx, result)
    reply = result.embedding
    return reply.profile_id, [list(v) for v in reply.vectors]


def _budgeted(ctx: SkillContext) -> dict[str, Any]:
    return {} if ctx.budget is None else {"budget": ctx.budget}


def _spent(ctx: SkillContext, result: Any) -> None:
    """What the call cost comes out of the caller's budget (the Router prices an embedding by what was sent)."""
    if ctx.budget is not None and result.budget is not None:
        ctx.budget = result.budget


def _cosine(a: list[float], b: list[float]) -> float:
    dot, na, nb = (
        sum(x * y for x, y in zip(a, b, strict=True)),
        math.sqrt(sum(x * x for x in a)),
        math.sqrt(sum(y * y for y in b)),
    )
    return dot / (na * nb) if na and nb else 0.0


def _scores(ctx: SkillContext, text: str, entries: list[dict[str, Any]], cfg: RouteConfig) -> dict[str, float]:
    profile, (query,) = _embed(ctx, [neutralise_marker(text, "TASK")[:2000]], "query", cfg.dimensions)
    keyed = {e["id"]: (profile, cfg.dimensions, hashlib.sha256(_doc(e).encode()).hexdigest()) for e in entries}
    with _lock:
        vectors = {i: _cache[k] for i, k in keyed.items() if k in _cache}
    missing = [e for e in entries if e["id"] not in vectors]
    if missing:
        got_profile, fresh = _embed(ctx, [_doc(e) for e in missing], "document", cfg.dimensions)
        if got_profile != profile:  # vectors of two profiles are never compared
            raise ValueError("embedding profile changed")
        with _lock:
            for entry, vector in zip(missing, fresh, strict=True):
                _cache[keyed[entry["id"]]] = vector
                vectors[entry["id"]] = vector
            while len(_cache) > _CACHE_MAX:
                _cache.popitem(last=False)
    return {i: _cosine(query, v) for i, v in vectors.items()}


def _fenced(entry: dict[str, Any]) -> str:
    """An entry line that cannot close the SKILLS block or open another block of the prompt."""
    return neutralise_marker(neutralise_marker(_doc(entry), "SKILLS"), "TASK")


def _pick(ctx: SkillContext, text: str, first: dict[str, Any], second: dict[str, Any]) -> str | None:
    """One cheap `assistant` call between two near-equal skills: 'a', 'b', 'none' or None when it cannot answer."""
    try:
        prompt = load_prompt(
            "assistant",
            "skill_route_task.md",
            {
                "task": neutralise_marker(text, "TASK")[:1000],
                "a": _fenced(first),
                "b": _fenced(second),
            },
        )
        system = load_prompt("assistant", "skill_route_system.md")
        request = GenerateRequest(
            system=system, prompt=prompt, json_mode=True, response_schema=_PICK, max_output_tokens=64
        )
        if ctx.router is None:
            raise ValueError("no router")
        result = ctx.router.generate("assistant", request, **_budgeted(ctx))
        _spent(ctx, result)
        reply = result.response.text if result.outcome == "ok" and result.response is not None else None
        doc = None if reply is None else json.loads(reply)
        return doc["pick"] if doc is not None and first_error(doc, _PICK) is None else None
    except Exception as exc:  # noqa: BLE001
        logger.warning("skill tie-break not answered: %s", type(exc).__name__)
        return None


def _match(ctx: SkillContext, text: str, entries: list[dict[str, Any]], cfg: RouteConfig) -> dict[str, Any] | None:
    by_id = {e["id"]: e for e in entries}
    ranked = sorted(_scores(ctx, text, entries, cfg).items(), key=lambda kv: (-kv[1], kv[0]))
    if not ranked or ranked[0][1] < cfg.min_score:
        return None
    (top, top_score), source = ranked[0], "matched"
    if len(ranked) > 1 and ranked[1][1] >= cfg.min_score and top_score - ranked[1][1] <= cfg.tie_margin:
        choice = _pick(ctx, text, by_id[top], by_id[ranked[1][0]])
        if choice == "none":
            return None
        if choice == "b":
            (top, top_score), source = ranked[1], "picked"
        elif choice == "a":
            source = "picked"
    return _data(by_id[top], top_score, source)


def pin_matched_skill(plan: dict[str, Any], skill: dict[str, Any] | None, known: set[str]) -> dict[str, Any]:
    """The matched (or tagged) LIBRARY skill goes onto the plan's working units (specialist and writer, not the
    delivery step), so the run pins and loads it. It must be one the plan validator knows; a taught skill is not
    pinned here (its steps are the outline, M1b)."""
    if not skill or skill.get("kind") != "library" or skill.get("id") not in known:
        return plan
    for unit in plan["units"]:
        working = unit["role"] in ("specialist", "writer") and unit["unit_type"] != DELIVER
        if working and skill["id"] not in unit["skills"] and len(unit["skills"]) < 10:
            unit["skills"].append(skill["id"])
    return plan


# --- wiring ------------------------------------------------------------------------------------------------------


def _seam(request: Request, fn: Callable[..., Any]) -> Any:
    provider = request.app.dependency_overrides.get(fn, fn)
    return provider(request=request) if "request" in inspect.signature(provider).parameters else provider()


def get_skill_context(
    request: Request,
    principal: Annotated[deps.Principal, Depends(deps.get_current_principal)],
    model_router: Annotated[Router, Depends(deps.get_router)],
) -> SkillContext:
    return skill_context_for(request, principal, model_router)


def skill_context_for(request: Request, principal: deps.Principal, model_router: Router) -> SkillContext:
    """The caller's skill context. A seam that is not wired (no skill or people store) leaves taught skills out; it
    never fails the request that asked (intake, approaches)."""

    def taught() -> list[dict[str, Any]]:
        from tilo_api.skills_routes import _readable  # noqa: PLC0415

        store, stores = _seam(request, deps.get_skill_store), _seam(request, deps.get_people_stores)
        return _readable(store, stores, principal, _seam(request, deps.get_clock), allow_unfounded=True)

    return SkillContext(principal.user_id, _seam(request, deps.get_skill_registry), taught, model_router)
