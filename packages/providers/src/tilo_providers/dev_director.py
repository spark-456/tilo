"""tilo_providers.dev_director — the deterministic dev fake for the Director role (CL-INT-5, EFF-01, PL-01).

`config/models.dev.yaml`'s `director-dev` profile is served by this class, so `just dev-api` needs no recordings or
paid call. It answers the brief, approaches and plan-draft (`units`, FR-INT-09) requests (and their schema-repair
re-asks), chosen by `response_schema`.
Replies are derived only from the task text or brief it is sent plus fixed demo constants, tagged "(dev)", and every
guessed field is flagged ambiguous so questions appear (FR-INT-05). `dev_only`: never conforms (PL-05); refused when
deployed or live (EFF-01). No network, clock or randomness."""

from __future__ import annotations

import json
import re
from collections.abc import Iterator
from datetime import date
from typing import Any

from tilo_providers.config import refuse_dev_only
from tilo_providers.errors import RequestError
from tilo_providers.interfaces import Capability, GenerateRequest, GenerateResponse, ModelProvider, PriceQuote

TAG = "(dev)"
_TASK = re.compile(r"<<<TASK\n(.*?)\nTASK>>>", re.DOTALL)
_BRIEF = re.compile(r"<<<BRIEF\n(.*?)\nBRIEF>>>", re.DOTALL)
_CATALOGUE = re.compile(r"<<<CATALOGUE\n(.*?)\nCATALOGUE>>>", re.DOTALL)
_DATE = re.compile(r"\b(\d{4}-\d{2}-\d{2})\b")
_GOAL_MAX = 500  # brief.schema.json goal.maxLength
_FREE = PriceQuote(input=0.0, output=0.0)

# Fixed demo constants: differ on every dimension but the format; credits far below the 300-credit run cap.
_APPROACHES = (
    ("quick_overview", "Quick overview", "overview", 3, 1, "basic", (8, 30), (3, 8)),
    ("balanced_review", "Balanced review", "standard", 12, 3, "standard", (30, 120), (10, 30)),
    ("deep_review", "Deep, verified review", "deep", 40, 5, "thorough", (120, 480), (40, 110)),
)  # fmt: skip


def _block(pattern: re.Pattern[str], prompt: str) -> str:
    found = pattern.search(prompt)
    return found.group(1) if found else ""


def _brief_reply(prompt: str) -> dict[str, Any]:
    goal = " ".join(_block(_TASK, prompt).split())[:_GOAL_MAX].strip() or f"No task text was given {TAG}"
    deadline = next((d for d in _DATE.findall(goal) if _valid_date(d)), None)
    ambiguous = [
        f
        for f in ("deliverables", "audience", "deadline", "constraints", "sources", "sensitivity")
        if f != "deadline" or not deadline
    ]
    return {
        "goal": goal,
        "deliverables": [{"title": f"Draft deliverable {TAG}", "format": "markdown"}],
        "audience": f"Not stated {TAG}",
        "deadline": deadline,
        "constraints": [],
        "sources": [],
        "sensitivity": "business",
        "ambiguous_fields": ambiguous,
    }  # fmt: skip


def _valid_date(text: str) -> bool:
    try:
        date.fromisoformat(text)
    except ValueError:
        return False
    return True


def _approaches_reply(prompt: str) -> dict[str, Any]:
    try:
        deliverables = json.loads(_block(_BRIEF, prompt))["deliverables"]
        output_format = deliverables[0]["format"]
    except (ValueError, KeyError, IndexError, TypeError):
        output_format = "markdown"  # an unreadable brief block gets the demo default
    return {
        "approaches": [
            {
                "id": id_, "label": f"{label} {TAG}",
                "summary": f"Synthetic {TAG} plan: {depth} depth, up to {sources} sources, {verification} checking.",
                "dimensions": {
                    "depth": depth, "sources": sources, "parallelism": parallelism,
                    "verification": verification, "output_format": output_format,
                },
                "time": {"min_s": seconds[0], "max_s": seconds[1]},
                "credits": {"min": credits[0], "max": credits[1]},
                "risks": [f"Placeholder estimate, not a model's judgement {TAG}"],
                "skips": [f"Nothing was analysed: this is a dev stand-in {TAG}"],
            }
            for id_, label, depth, sources, parallelism, verification, seconds, credits in _APPROACHES
        ]
    }  # fmt: skip


def _first_approval_action(prompt: str) -> tuple[str, str] | None:
    """(connector id, action id) of the first catalogue action that needs an approval gate, or None."""
    try:
        connectors = json.loads(_block(_CATALOGUE, prompt))["connectors"]
        return next(
            (c["id"], a["id"]) for c in connectors for a in c["actions"] if a["gate_type"] == "approval"
        )  # fmt: skip
    except (ValueError, KeyError, TypeError, StopIteration):
        return None  # an unreadable catalogue, or one with no gated action, gets a plan with nothing to send


def _plan_reply(prompt: str) -> dict[str, Any]:
    """Specialist -> writer -> verifier, then a final writer unit that performs the catalogue's first gated action.
    Only units: the gates, the cap and every policy are added by code, never named here."""
    steps = [("research", "Gather the facts", "specialist"), ("draft", "Draft the deliverable", "writer"),
             ("verify", "Check the draft", "verifier")]  # fmt: skip
    units = [
        {"id": f"U{n}", "unit_type": kind, "title": f"{title} {TAG}", "role": role, "district": "D1", "skills": [],
         "connectors": [], "actions": [], "depends_on": [f"U{n - 1}"] if n > 1 else []}
        for n, (kind, title, role) in enumerate(steps, start=1)
    ]  # fmt: skip
    if send := _first_approval_action(prompt):
        units.append({
            "id": "U4", "unit_type": "deliver", "title": f"Hand over for approval {TAG}", "role": "writer",
            "district": "D1", "skills": [], "connectors": [send[0]], "actions": [send[1]], "depends_on": ["U3"],
        })  # fmt: skip
    return {"units": units}


class DevDirectorProvider(ModelProvider):
    dev_only = True  # PL-05: never counted as conforming for a real role

    def __init__(self, profile_id: str = "director-dev") -> None:
        refuse_dev_only(profile_id)
        self._profile_id = profile_id

    def generate(self, request: GenerateRequest) -> GenerateResponse:
        refuse_dev_only(self._profile_id)  # re-checked on every call, as the dev API's dependencies are
        properties = (request.response_schema or {}).get("properties", {})
        if "ambiguous_fields" in properties:
            reply = _brief_reply(request.prompt)
        elif "approaches" in properties:
            reply = _approaches_reply(request.prompt)
        elif "units" in properties:
            reply = _plan_reply(request.prompt)
        else:
            raise RequestError(
                f"CL-INT-5: the dev Director fake {TAG} only answers brief, approaches and plan requests"
            )
        return GenerateResponse(text=json.dumps(reply, sort_keys=True), profile_id=self._profile_id)

    def stream(self, request: GenerateRequest) -> Iterator[GenerateResponse]:
        yield self.generate(request)

    def embed(self, request: Any) -> Any:
        raise RequestError(f"CL-INT-5: the dev Director fake {TAG} makes no embeddings")

    def count_tokens(self, text: str) -> int:
        return len(text.split())

    def capabilities(self) -> set[Capability]:
        return {Capability.JSON}

    def price(self) -> PriceQuote:
        return _FREE
