"""Independent Verifier (FR-AGT-12; PRD 8.1, 8.6, 13.3; BQ-200, BQ-201, BQ-213).

Every deliverable a unit hands over is reviewed once, by a verifier-rank agent that did not produce
it, and one `artifact.reviewed` records the result. A claim is judged in this order, first rule wins:

1. no `source_ids`, or the claim is past the first `max_claims` of its deliverable   -> unverified
2. no cited source is usable (text missing, longer than `MAX_SOURCE_CHARS`, or its
   SHA-256 differs from the manifest's fingerprint; each is noted in `Review.notes`)  -> unverified
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

from tilo_harness.untrusted import neutralise
from tilo_harness.validator import repo_validator

ROLE = "verifier"  # prompts/verifier/claim_*.md, providers["verifier"]
MAX_SOURCE_CHARS = 30_000  # BQ-213: a source (or the sources of one claim together) over this is refused, never cut
MAX_CLAIMS = 200  # BQ-223: one model call per claim, so a deliverable's claims are bounded
MAX_CLAIM_CHARS = 300  # manifest.schema.json caps claim text at 280
MAX_REPLY_CHARS = 200
_NUMBER = re.compile(r"[0-9]+(?:,[0-9]{3})*(?:\.[0-9]+)?")
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
    manifest: dict[str, Any]  # the input, with each claim's `verified` recomputed (false when not reviewable)
    trace: dict[str, Any] = field(default_factory=dict)  # the model calls made, for the event's trace
    notes: dict[str, list[str]] = field(default_factory=dict)  # claim id -> why a cited source or claim was not used


def _numbers(text: str) -> set[str]:
    out = set()
    for raw in _NUMBER.findall(unicodedata.normalize("NFKC", text)):
        number = raw.replace(",", "")
        out.add(number.rstrip("0").rstrip(".") if "." in number else number)
    return out


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
        for index, row in enumerate(manifest["claims"]):
            claim_notes = notes.setdefault(row["id"], [])
            if index >= self._max_claims:
                claim_notes.append(f"past the first {self._max_claims} claims of this deliverable")
                status[row["id"]] = "unverified"
            else:
                usable = self._usable(row["source_ids"], fingerprints, deliverable.sources, claim_notes)
                status[row["id"]] = await self._judge(row["text"], usable, responses)
            row["verified"] = status[row["id"]] == "supported"
        values = set(status.values())
        result = "failed" if "contradicted" in values else "passed" if values == {"supported"} else "unverified"
        return Review(result, status, manifest, _trace(responses), {k: v for k, v in notes.items() if v})

    @staticmethod
    def _usable(
        ids: list[str], fingerprints: Mapping[str, str], held: Mapping[str, str], notes: list[str]
    ) -> list[str]:
        """The cited texts that can be trusted as fetched; each one that cannot is noted. The size check
        comes first, so nothing is hashed or scanned that is too long to send."""
        usable = []
        for sid in ids:
            text = held.get(sid)
            if not isinstance(text, str):
                notes.append(f"source {sid}: text not held")
            elif len(text) > MAX_SOURCE_CHARS:
                notes.append(f"source {sid}: too long to check")
            elif fingerprints.get(sid) != "sha256:" + hashlib.sha256(text.encode("utf-8", "replace")).hexdigest():
                notes.append(f"source {sid}: does not match its fingerprint")
            else:
                usable.append(text)
        return usable

    async def _judge(self, text: str, sources: list[str], responses: list[GenerateResponse]) -> str:
        if not sources or sum(len(source) for source in sources) > MAX_SOURCE_CHARS:  # rules 1 and 2
            return "unverified"
        known = set().union(*(_numbers(source) for source in sources))
        if not _numbers(text) <= known:  # rule 3
            return "contradicted"
        shown = "\n\n".join(f"[source {i}]\n{neutralise(s, limit=MAX_SOURCE_CHARS)}" for i, s in enumerate(sources, 1))
        fields = {"claim": neutralise(text, limit=MAX_CLAIM_CHARS), "sources": shown}
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
    return {
        "model_role": ROLE,
        "profile": profile if _PROFILE.fullmatch(profile) else None,
        "tokens_in": sum(u.get("input_tokens", 0) for u in usage) if usage else None,
        "tokens_out": sum(u.get("output_tokens", 0) for u in usage) if usage else None,
    }
