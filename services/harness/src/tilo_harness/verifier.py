"""Independent Verifier (FR-AGT-12; PRD 8.1, 8.6, 13.3; BQ-200, BQ-201).

Every deliverable a unit hands over is reviewed once, by a verifier-rank agent that did not produce
it, and one `artifact.reviewed` records the result. A claim is judged in this order, first rule wins:

1. no `source_ids`                                                  -> unverified
2. no cited source is usable (text missing, or its SHA-256 differs
   from the manifest's fingerprint, or too long to send whole)     -> unverified
3. a number in the claim that no usable cited source contains       -> contradicted (no model call)
4. otherwise the `verifier`-role model decides, one call per claim: {"verdict": supported |
   contradicted | cannot_tell}; anything else, or a provider error -> unverified.

All claims supported -> passed; any contradicted -> failed; otherwise unverified (no claims too). The
model can only confirm what rules 1-3 left standing. The author's own `verified` flag is never read: it is
recomputed. Independence: only `providers["verifier"]` is used (never another role's), the prompt holds the
claim and its usable sources and nothing that names the producer, and a Verifier never reviews its own work.
"""

from __future__ import annotations

import asyncio
import copy
import hashlib
import json
import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import Any

from tilo_providers.interfaces import GenerateRequest, GenerateResponse, ModelProvider
from tilo_providers.prompts import load_prompt, neutralise_marker

from tilo_harness.validator import repo_validator

ROLE = "verifier"  # prompts/verifier/claim_*.md, providers["verifier"]
MAX_SOURCE_CHARS = 30_000  # BQ-203: more than this across a claim's sources is refused, never cut
_NUMBER = re.compile(r"\d+(?:,\d{3})*(?:\.\d+)?")
_PROFILE = re.compile(r"[a-z][a-z0-9-]{0,31}")  # providers.schema.json profile_id


class VerifierNotIndependent(Exception):
    """The deliverable was produced by the agent that was asked to review it."""


class VerifierProviderMissing(Exception):
    """No `verifier` role provider: the Verifier never borrows another role's."""


@dataclass(frozen=True)
class Deliverable:
    manifest: dict[str, Any]
    sources: Mapping[str, str]  # source id -> the fetched text, as the raw archive holds it


@dataclass(frozen=True)
class Review:
    result: str  # passed | failed | unverified
    status: dict[str, str]  # claim id -> supported | contradicted | unverified
    manifest: dict[str, Any]  # the input, with each claim's `verified` recomputed
    trace: dict[str, Any] = field(default_factory=dict)  # the model calls made, for the event's trace


def _numbers(text: str) -> set[str]:
    out = set()
    for raw in _NUMBER.findall(text):
        number = raw.replace(",", "")
        out.add(number.rstrip("0").rstrip(".") if "." in number else number)
    return out


def _verdict(text: Any) -> str:
    try:
        reply = json.loads(text) if isinstance(text, str) else None
    except ValueError:
        return "unverified"
    verdict = reply.get("verdict") if isinstance(reply, dict) else None
    return verdict if verdict in ("supported", "contradicted") else "unverified"


class Verifier:
    def __init__(
        self,
        providers: Mapping[str, ModelProvider],
        *,
        agent_id: str,
        load: Callable[[dict[str, Any]], Deliverable] | None = None,
    ) -> None:
        if ROLE not in providers:
            raise VerifierProviderMissing("the Verifier needs a provider for the verifier role and uses no other")
        self._model = providers[ROLE]
        self.agent_id = agent_id
        self._load = load
        self._system = load_prompt(ROLE, "claim_system.md")

    async def review(self, deliverable: Deliverable) -> Review:
        manifest = copy.deepcopy(deliverable.manifest)
        if repo_validator().contract_problems("manifest", manifest):
            return Review("unverified", {}, manifest)  # nothing checkable: fail closed
        if manifest["produced_by"]["agent_id"] == self.agent_id:
            raise VerifierNotIndependent(f"{self.agent_id} produced this deliverable and cannot review it")
        fingerprints = {s["id"]: s["fingerprint"] for s in manifest["sources"]}
        responses: list[GenerateResponse] = []
        status: dict[str, str] = {}
        for row in manifest["claims"]:
            usable = [
                deliverable.sources[sid]
                for sid in row["source_ids"]
                if sid in deliverable.sources
                and fingerprints.get(sid)
                == "sha256:" + hashlib.sha256(deliverable.sources[sid].encode("utf-8", "replace")).hexdigest()
            ]
            status[row["id"]] = await self._judge(row["text"], usable, responses)
            row["verified"] = status[row["id"]] == "supported"
        values = set(status.values())
        result = "failed" if "contradicted" in values else "passed" if values == {"supported"} else "unverified"
        return Review(result, status, manifest, _trace(responses))

    async def _judge(self, text: str, sources: list[str], responses: list[GenerateResponse]) -> str:
        if not sources:  # rules 1 and 2
            return "unverified"
        known = set().union(*(_numbers(source) for source in sources))
        if not _numbers(text) <= known:  # rule 3
            return "contradicted"
        if sum(len(source) for source in sources) > MAX_SOURCE_CHARS:
            return "unverified"
        shown = "\n\n".join(f"[source {i}]\n{source}" for i, source in enumerate(sources, 1))
        fields = {"claim": text, "sources": shown}
        prompt = load_prompt(ROLE, "claim_task.md", {k: neutralise_marker(v, k.upper()) for k, v in fields.items()})
        request = GenerateRequest(system=self._system, prompt=prompt, json_mode=True, max_output_tokens=32)
        try:
            response = await asyncio.to_thread(self._model.generate, request)
        except Exception:  # a provider outage marks the claim unverified, never supported
            return "unverified"
        responses.append(response)
        return _verdict(response.text)

    async def review_and_record(
        self, ref: dict[str, Any], *, writer: Any, cause: str | None = None, district: str | None = None
    ) -> Review:
        """Loads, reviews and writes one `artifact.reviewed`. A ref that cannot be loaded, or whose
        deliverable this agent produced, is recorded as unverified: a deliverable is never skipped."""
        try:
            if self._load is None:
                raise LookupError("no loader")
            deliverable = await asyncio.to_thread(self._load, ref)
            review = await self.review(deliverable)
        except Exception:  # unloadable, malformed or not independent: fail closed
            review = Review("unverified", {}, {})
        levels = [
            lv["id"] for lv in writer.layout["semantic"]["levels"] for d in lv["districts"] if d["id"] == district
        ]
        trace = {"model_role": None, "profile": None, "tokens_in": None, "tokens_out": None, "tool": None}
        trace |= review.trace | {"latency_ms": None, "archive_ref": None}
        writer.emit(
            type="artifact.reviewed",
            actor=self.agent_id,
            target=ref["artifact_id"],
            summary=f"The Verifier checked {ref['artifact_id']}: {review.result}.",
            data={"artifact": ref, "result": review.result},
            level=levels[0] if levels else None,
            district=district,
            cause=cause,
            trace=trace,
        )
        return review


def _trace(responses: list[GenerateResponse]) -> dict[str, Any]:
    if not responses:
        return {}
    usage = [r.usage for r in responses if r.usage]
    profile = responses[-1].profile_id
    return {
        "model_role": ROLE,
        "profile": profile if _PROFILE.fullmatch(profile) else None,
        "tokens_in": sum(u.get("input_tokens", 0) for u in usage) if usage else None,
        "tokens_out": sum(u.get("output_tokens", 0) for u in usage) if usage else None,
    }
