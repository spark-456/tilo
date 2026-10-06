"""Independent Verifier (FR-AGT-12; PRD 8.1, 8.6, 13.3; BQ-200, BQ-201, BQ-213).

Every deliverable a unit hands over is reviewed once, by a verifier-rank agent that did not produce
it, and one `artifact.reviewed` records the result. A claim is judged in this order, first rule wins:

1. no `source_ids`, or the claim is past the first `max_claims` of its deliverable   -> unverified
2. no cited source is usable (text missing, longer than `MAX_SOURCE_CHARS`, past the first
   `MAX_SOURCES` sources of the review, a long run of combining characters, or its SHA-256
   differs from the manifest's fingerprint; each is noted in `Review.notes`), the cited
   texts are together longer than `MAX_SOURCE_CHARS` (summed before any is prepared), or
   the review's `MAX_REVIEW_CHARS` budget for normalising text is spent              -> unverified
3. a number in the claim that no usable cited source contains                         -> contradicted (no model call)
4. otherwise the `verifier`-role model decides, one call per claim: exactly
   {"verdict": supported | contradicted | cannot_tell}; anything else, or an error   -> unverified.

All claims supported -> passed; any contradicted -> failed; otherwise unverified (no claims too). The
model can only confirm what rules 1-3 left standing. The author's own `verified` flag is never read: it is
recomputed, and a manifest that cannot be reviewed comes back with every flag false. Independence: only
`providers["verifier"]` is used (never another role's), the prompt holds the claim and its usable sources
(neutralised, `untrusted.neutralise`) and nothing that names the producer, a Verifier never reviews its
own work, and a verdict is recorded only for the artifact version its manifest describes.
"""

from __future__ import annotations

import asyncio
import copy
import hashlib
import json
import re
import unicodedata
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import Any

from tilo_providers.interfaces import GenerateRequest, GenerateResponse, ModelProvider
from tilo_providers.prompts import load_prompt

from tilo_harness.untrusted import Budget, BudgetSpent, has_long_mark_run, neutralise, nfkc
from tilo_harness.validator import repo_validator

ROLE = "verifier"  # prompts/verifier/claim_*.md, providers["verifier"]
MAX_SOURCE_CHARS = 30_000  # BQ-213: a source (or the sources of one claim together) over this is refused, never cut
MAX_CLAIMS = 200  # BQ-232: one model call per claim, so a deliverable's claims are bounded
MAX_SOURCES = 20  # BQ-232: distinct sources prepared per review; any further source is refused as unusable
MAX_REVIEW_CHARS = 3_000_000  # BQ-232: decomposed characters normalised per review, every call together
MAX_CLAIM_CHARS = 300  # manifest.schema.json caps claim text at 280
MAX_REPLY_CHARS = 200
_NUMBER = re.compile(r"[0-9]+(?:,[0-9]{3})*(?:\.[0-9]+)?")
_PROFILE = re.compile(r"[a-z][a-z0-9-]{0,31}")  # providers.schema.json profile_id
_SPENT = "the review's budget for normalising text is spent"


class VerifierNotIndependent(Exception):
    """The deliverable was produced by the agent that was asked to review it."""


class VerifierProviderMissing(Exception):
    """No `verifier` role provider: the Verifier never borrows another role's."""


@dataclass(frozen=True)
class Deliverable:
    manifest: dict[str, Any]
    sources: Mapping[str, str]  # source id -> the fetched text, as the raw archive holds it


@dataclass(frozen=True)
class _Source:
    """A cited source, checked and prepared once per review."""

    shown: str  # neutralised, as the model sees it
    numbers: frozenset[str]


def _prepare(text: Any, fingerprint: str | None, budget: Budget) -> tuple[_Source | None, str | None]:
    """(source, None) when the text can be trusted as fetched, else (None, why not). The size and
    mark-run checks come first, so nothing too long or too slow to normalise is hashed or scanned."""
    if not isinstance(text, str):
        return None, "text not held"
    if len(text) > MAX_SOURCE_CHARS:
        return None, "too long to check"
    if has_long_mark_run(text):
        return None, "holds a long run of combining characters"
    if fingerprint != "sha256:" + hashlib.sha256(text.encode("utf-8", "replace")).hexdigest():
        return None, "does not match its fingerprint"
    try:
        return _Source(neutralise(text, limit=MAX_SOURCE_CHARS, budget=budget), _numbers(text, budget)), None
    except BudgetSpent:
        return None, _SPENT


@dataclass(frozen=True)
class Review:
    result: str  # passed | failed | unverified
    status: dict[str, str]  # claim id -> supported | contradicted | unverified
    manifest: dict[str, Any]  # the input, with each claim's `verified` recomputed (false when not reviewable)
    trace: dict[str, Any] = field(default_factory=dict)  # the model calls made, for the event's trace
    notes: dict[str, list[str]] = field(default_factory=dict)  # claim id -> why a cited source or claim was not used


def _numbers(text: str, budget: Budget) -> frozenset[str]:
    """The numbers in the NFKC of `text` (capped to MAX_SOURCE_CHARS and stream-safe, `untrusted.nfkc`), any
    script's decimal digits read as 0-9. Linear in len(text)."""
    out = set()
    folded = "".join(
        str(unicodedata.decimal(c)) if unicodedata.category(c) == "Nd" else c
        for c in nfkc(text, limit=MAX_SOURCE_CHARS, budget=budget)
    )
    for raw in _NUMBER.findall(folded):
        number = raw.replace(",", "")
        out.add(number.rstrip("0").rstrip(".") if "." in number else number)
    return frozenset(out)


def _pairs(items: list[tuple[str, Any]]) -> dict[str, Any]:
    if len({key for key, _ in items}) != len(items):
        raise ValueError("duplicate key")
    return dict(items)


def _verdict(text: Any) -> str:
    try:
        reply = (
            json.loads(text, object_pairs_hook=_pairs)
            if isinstance(text, str) and len(text) <= MAX_REPLY_CHARS
            else None
        )
    except Exception:  # not JSON, a duplicate key, or too deeply nested
        return "unverified"
    if isinstance(reply, dict) and set(reply) == {"verdict"} and reply["verdict"] in ("supported", "contradicted"):
        return str(reply["verdict"])
    return "unverified"


def _cleared(manifest: Any) -> Any:
    """A copy of a manifest nobody could review: no claim keeps the author's `verified: true`."""
    manifest = copy.deepcopy(manifest)
    claims = manifest.get("claims") if isinstance(manifest, dict) else None
    for row in claims if isinstance(claims, list) else []:
        if isinstance(row, dict) and "verified" in row:
            row["verified"] = False
    return manifest


class Verifier:
    def __init__(
        self,
        providers: Mapping[str, ModelProvider],
        *,
        agent_id: str,
        load: Callable[[dict[str, Any]], Deliverable] | None = None,
        max_claims: int = MAX_CLAIMS,
    ) -> None:
        if ROLE not in providers:
            raise VerifierProviderMissing("the Verifier needs a provider for the verifier role and uses no other")
        self._model = providers[ROLE]
        self.agent_id = agent_id
        self._load = load
        self._max_claims = max_claims
        self._system = load_prompt(ROLE, "claim_system.md")

    async def review(self, deliverable: Deliverable) -> Review:
        manifest = copy.deepcopy(deliverable.manifest)
        if repo_validator().contract_problems("manifest", manifest):
            return Review("unverified", {}, _cleared(manifest))  # nothing checkable: fail closed
        if manifest["produced_by"]["agent_id"] == self.agent_id:
            raise VerifierNotIndependent(f"{self.agent_id} produced this deliverable and cannot review it")
        fingerprints = {s["id"]: s["fingerprint"] for s in manifest["sources"]}
        responses: list[GenerateResponse] = []
        status: dict[str, str] = {}
        notes: dict[str, list[str]] = {}
        prepared: dict[str, tuple[_Source | None, str | None]] = {}  # each source once per review
        budget = Budget(MAX_REVIEW_CHARS)
        for index, row in enumerate(manifest["claims"]):
            claim_notes = notes.setdefault(row["id"], [])
            status[row["id"]] = "unverified"
            if index >= self._max_claims:
                claim_notes.append(f"past the first {self._max_claims} claims of this deliverable")
            elif len(row["text"]) > MAX_CLAIM_CHARS:
                claim_notes.append("claim text too long to check")
            else:
                cited = {sid: deliverable.sources.get(sid) for sid in row["source_ids"]}
                sizes = [len(t) for t in cited.values() if isinstance(t, str) and len(t) <= MAX_SOURCE_CHARS]
                if sum(sizes) > MAX_SOURCE_CHARS:  # summed before any of them is prepared
                    claim_notes.append("cited sources together too long to check")
                    cited = {}
                usable = []
                for sid, text in cited.items():
                    if sid not in prepared:
                        prepared[sid] = (
                            (None, f"past the first {MAX_SOURCES} sources of this review")
                            if len(prepared) >= MAX_SOURCES
                            else await asyncio.to_thread(_prepare, text, fingerprints.get(sid), budget)
                        )
                    source, why = prepared[sid]
                    if source is None:
                        claim_notes.append(f"source {sid}: {why}")
                    else:
                        usable.append(source)
                status[row["id"]] = await self._judge(row["text"], usable, responses, budget, claim_notes)
            row["verified"] = status[row["id"]] == "supported"
        values = set(status.values())
        result = "failed" if "contradicted" in values else "passed" if values == {"supported"} else "unverified"
        return Review(result, status, manifest, _trace(responses), {k: v for k, v in notes.items() if v})

    async def _judge(
        self, text: str, sources: list[_Source], responses: list[GenerateResponse], budget: Budget, notes: list[str]
    ) -> str:
        if not sources:  # rules 1 and 2
            return "unverified"
        try:
            numbers = _numbers(text, budget)
            claim = neutralise(text, limit=MAX_CLAIM_CHARS, budget=budget)
        except BudgetSpent:
            notes.append(f"claim: {_SPENT}")
            return "unverified"
        if not numbers <= frozenset().union(*(source.numbers for source in sources)):  # rule 3
            return "contradicted"
        shown = "\n\n".join(f"[source {i}]\n{source.shown}" for i, source in enumerate(sources, 1))
        fields = {"claim": claim, "sources": shown}
        request = GenerateRequest(
            system=self._system, prompt=load_prompt(ROLE, "claim_task.md", fields), json_mode=True, max_output_tokens=32
        )
        try:
            response = await asyncio.to_thread(self._model.generate, request)
        except Exception:  # a provider outage marks the claim unverified, never supported
            return "unverified"
        responses.append(response)
        return _verdict(response.text)

    async def review_and_record(
        self, ref: dict[str, Any], *, writer: Any, cause: str | None = None, district: str | None = None
    ) -> Review:
        """Loads, reviews and writes one `artifact.reviewed`. A ref that cannot be loaded, a manifest that
        describes another artifact or version than `ref`, or a deliverable this agent produced, is recorded
        as unverified: a deliverable is never skipped and a verdict never lands on the wrong version."""
        try:
            if self._load is None:
                raise LookupError("no loader")
            deliverable = await asyncio.to_thread(self._load, ref)
            artifact = deliverable.manifest.get("artifact")
            if not isinstance(artifact, dict) or (artifact.get("artifact_id"), artifact.get("version")) != (
                ref["artifact_id"],
                ref["version"],
            ):
                review = Review("unverified", {}, _cleared(deliverable.manifest))
            else:
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
    tokens_in = sum(u.get("input_tokens", 0) for u in usage) if usage else None
    trace: dict[str, Any] = {
        "model_role": ROLE,
        "profile": profile if _PROFILE.fullmatch(profile) else None,
        "tokens_in": tokens_in,
        "tokens_out": sum(u.get("output_tokens", 0) for u in usage) if usage else None,
    }
    if (cached := _cached_tokens(usage)) is not None and cached <= (tokens_in or 0):
        trace["tokens_cached"] = cached  # never above tokens_in: EV-16 would refuse the event
    return trace


def _cached_tokens(usage: list[dict[str, int]]) -> int | None:
    """EFF-04 (ADR-0022 decision 7): the sum of the calls' cache reads, only when every call counted in
    `tokens_in` reported a whole number >= 0. One missing or bad count makes it unknown (None), never 0."""
    total = 0
    for u in usage:
        count = u.get("cached_tokens")
        if isinstance(count, bool) or not isinstance(count, int) or count < 0:
            return None
        total += count
    return total if usage else None
