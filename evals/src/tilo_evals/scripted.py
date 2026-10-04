"""A scripted Director for the generality bank (issue #272, GEN-02; PRD 6.6 record and replay, EFF-01).

The dev Director fake gives every brief the same shape, so a bank that changed only the task text would prove nothing
about plan variety. A bank case carries its own Director replies instead (the brief, the approaches, the plan's units:
data only), authored once and frozen. The provider answers the brief, approaches and plan requests the pipeline makes,
chosen by `response_schema` like the dev fake, and nothing else. A reply the case leaves out (`null`) is a Director that
could not answer: the request fails and the pipeline must stop honestly.

No network, clock or randomness; no model id (PL-01); refused when deployed or live, like every dev-only provider.
Gates, the cap and every policy are never named in a script: code adds them.
"""

from __future__ import annotations

import json
from collections.abc import Iterator, Mapping
from typing import Any

from tilo_providers.config import refuse_dev_only
from tilo_providers.errors import RequestError
from tilo_providers.interfaces import Capability, GenerateRequest, GenerateResponse, ModelProvider, PriceQuote

PROFILE = "scripted-director"
_FREE = PriceQuote(input=0.0, output=0.0)

# Three approaches that differ on every dimension but the format (PG-08), credits far below any run cap.
_STANDARD = (
    ("quick", "Quick pass", "overview", 3, 1, "basic", (8, 30), (3, 8)),
    ("balanced", "Balanced pass", "standard", 12, 3, "standard", (30, 120), (10, 30)),
    ("thorough", "Thorough pass", "deep", 40, 5, "thorough", (120, 480), (40, 110)),
)


def standard_approaches(output_format: str) -> dict[str, Any]:
    return {
        "approaches": [
            {
                "id": id_,
                "label": label,
                "summary": f"A {depth} pass: up to {sources} sources, {verification} checking.",
                "dimensions": {
                    "depth": depth,
                    "sources": sources,
                    "parallelism": parallelism,
                    "verification": verification,
                    "output_format": output_format,
                },
                "time": {"min_s": seconds[0], "max_s": seconds[1]},
                "credits": {"min": credits[0], "max": credits[1]},
                "risks": ["A scripted estimate, not a model's judgement."],
                "skips": ["Nothing was analysed: the bank scripts the Director."],
            }
            for id_, label, depth, sources, parallelism, verification, seconds, credits in _STANDARD
        ]
    }


class ScriptedDirector(ModelProvider):
    """Answers from `script`: keys `brief`, `approaches` (a reply, or the word "standard") and `plan`."""

    dev_only = True  # PL-05: never counted as conforming for a real role

    def __init__(self, script: Mapping[str, Any], profile_id: str = PROFILE) -> None:
        refuse_dev_only(profile_id)
        self._script, self._profile_id = script, profile_id
        self.calls: list[str] = []  # the kind of each request, in order

    def _reply(self, kind: str) -> Any:
        reply = self._script.get(kind)
        if reply is None:
            raise RequestError(f"the script gives no {kind} reply: the Director could not answer")
        if kind == "approaches" and reply == "standard":
            deliverables = (self._script.get("brief") or {}).get("deliverables") or [{}]
            return standard_approaches(str(deliverables[0].get("format", "markdown")))
        return reply

    def generate(self, request: GenerateRequest) -> GenerateResponse:
        refuse_dev_only(self._profile_id)  # re-checked on every call
        properties = (request.response_schema or {}).get("properties", {})
        if "ambiguous_fields" in properties:
            kind = "brief"
        elif "approaches" in properties:
            kind = "approaches"
        elif "units" in properties:
            kind = "plan"
        else:
            raise RequestError("the scripted Director answers brief, approaches and plan requests only")
        self.calls.append(kind)
        return GenerateResponse(text=json.dumps(self._reply(kind), sort_keys=True), profile_id=self._profile_id)

    def stream(self, request: GenerateRequest) -> Iterator[GenerateResponse]:
        yield self.generate(request)

    def embed(self, request: Any) -> Any:
        raise RequestError("the scripted Director makes no embeddings")

    def count_tokens(self, text: str) -> int:
        return len(text.split())

    def capabilities(self) -> set[Capability]:
        return {Capability.JSON}

    def price(self) -> PriceQuote:
        return _FREE
