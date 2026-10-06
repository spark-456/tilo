"""Helpers for the FR-INT-15 acceptance tests (supplement 2026-10-05 section 4, PRD 7.1, 16.3). No business logic: a
scripted Director behind a real `Router` that answers the brief, approaches and plan requests by what each asks for,
the loader of the best-effort set, and tmp writers for the two gap configs. Named `_fr_int_15_lib` for the same
global-bare-module-name reason as `_fr_int_12_lib` (pytest prepend import mode). The interface under test is pinned
in `API_FR_INT_15.md`.

The Director is scripted, never a model (EFF-01): it replies with what a well-behaved model would say for each task
(the possible part as the brief, the rest as `out_of_scope`). What the tests check is everything the CODE does with
that reply: configured reason and alternative text, the refusal that always wins, fail closed on an unknown id or an
over-long list, and the gap lines in the approaches and the plan.
"""

from __future__ import annotations

import copy
import json
import pathlib
from typing import Any

import yaml
from _fr_int_12_lib import BASE_BRIEF, REPO_ROOT, make_router

BEST_EFFORT_SET = pathlib.Path(__file__).resolve().parent / "fixtures" / "best_effort_set.yaml"
GAP_CONFIG = REPO_ROOT / "config" / "capability_gaps.yaml"
REFUSAL_CONFIG = REPO_ROOT / "config" / "out_of_policy.yaml"
CONNECTORS_CONFIG = REPO_ROOT / "config" / "connectors.yaml"
APPROACHES_FIXTURE = pathlib.Path(__file__).resolve().parent / "fixtures" / "approaches" / "distinct_three.json"

OWNER = "u_owner"
CAP = 42.5

GAP_IDS = (
    "money_movement",
    "calls_and_chat",
    "physical_world",
    "desktop_apps",
    "unconnected_service",
    "unsupported_output",
    "non_english",
)
REFUSAL_IDS = (
    "credential_handling",
    "unapproved_send",
    "bypass_safeguards",
    "deception",
    "bulk_or_unsolicited_sending",
    "covert_or_private_data",
    "destructive_without_confirmation",
)

__all__ = [
    "APPROACHES_FIXTURE",
    "BASE_BRIEF",
    "CAP",
    "GAP_IDS",
    "OWNER",
    "REFUSAL_IDS",
    "REPO_ROOT",
    "StageDirector",
    "gap_config_dict",
    "gap_item",
    "gap_reply",
    "load_best_effort_set",
    "make_router",
    "write_connectors",
    "write_gap_config",
]


def load_yaml(path: pathlib.Path) -> Any:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def load_best_effort_set() -> dict[str, list[dict[str, Any]]]:
    return load_yaml(BEST_EFFORT_SET)


def gap_item(category: str, part: str) -> dict[str, str]:
    return {"category": category, "part": part}


def gap_reply(
    gaps: Any = ...,
    *,
    deliverables: Any = ...,
    out_of_policy: Any = ...,
    goal: str | None = None,
) -> dict[str, Any]:
    """The Director's JSON reply. `...` leaves a key out (for `gaps`: the `out_of_scope` key; for `deliverables`: the
    base one-deliverable brief; for `out_of_policy`: the key)."""
    reply = copy.deepcopy(BASE_BRIEF)
    if goal is not None:
        reply["goal"] = goal
    if deliverables is not ...:
        reply["deliverables"] = deliverables
    if out_of_policy is not ...:
        reply["out_of_policy"] = out_of_policy
    if gaps is not ...:
        reply["out_of_scope"] = gaps
    return reply


def _deliverables(case: dict[str, Any], given: Any) -> Any:
    if given is ... and "deliverables" in case:
        return copy.deepcopy(case["deliverables"])
    return given


def case_reply(case: dict[str, Any], *, deliverables: Any = ...) -> dict[str, Any]:
    """The scripted reply for one case of the best-effort set (any of its three groups)."""
    return gap_reply(
        copy.deepcopy(case["gaps"]),
        deliverables=_deliverables(case, deliverables),
        out_of_policy=case.get("out_of_policy"),
        goal=f"Do the part of this task Tilo can do ({case['id']}).",
    )  # fmt: skip


class StageDirector:
    """One scripted provider for the whole planning flow. It answers by what the request asks for (the response
    schema), not by call order: a brief request gets the reply the test set for the task text found in its prompt
    (or `default`), an approaches request `approaches`, a plan request `units`. Records every request, so a test can
    count the model calls of a flow (EFF: a gap costs no extra call)."""

    profile_id = "scripted"

    def __init__(
        self,
        briefs: dict[str, dict[str, Any]] | None = None,
        *,
        default: dict[str, Any] | None = None,
        approaches: dict[str, Any] | None = None,
        units: list[dict[str, Any]] | None = None,
    ) -> None:
        self.briefs = briefs or {}
        self.default = default
        self.approaches = approaches if approaches is not None else json.loads(APPROACHES_FIXTURE.read_text("utf-8"))
        self.units = units if units is not None else [one_unit()]
        self.calls: list[Any] = []

    def kinds(self) -> list[str]:
        return [self._kind(request) for request in self.calls]

    @staticmethod
    def _kind(request: Any) -> str:
        properties = (request.response_schema or {}).get("properties", {})
        if "ambiguous_fields" in properties:
            return "brief"
        if "approaches" in properties:
            return "approaches"
        if "units" in properties:
            return "plan"
        return "other"

    def generate(self, request: Any) -> Any:
        from tilo_providers.interfaces import GenerateResponse  # noqa: PLC0415

        self.calls.append(request)
        kind = self._kind(request)
        if kind == "brief":
            for text, reply in self.briefs.items():
                if text in request.prompt:
                    return GenerateResponse(text=json.dumps(reply), profile_id=self.profile_id)
            if self.default is not None:
                return GenerateResponse(text=json.dumps(self.default), profile_id=self.profile_id)
            raise AssertionError("the task text did not reach the Director's prompt")
        if kind == "approaches":
            return GenerateResponse(text=json.dumps(self.approaches), profile_id=self.profile_id)
        if kind == "plan":
            return GenerateResponse(text=json.dumps({"units": self.units}), profile_id=self.profile_id)
        raise AssertionError("an unexpected model call: neither a brief, an approaches nor a plan request")

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


def one_unit() -> dict[str, Any]:
    """The one-unit plan reply: a writer with no skills, connectors or actions (code adds the deliver unit)."""
    return {
        "id": "U1",
        "unit_type": "document_drafted",
        "title": "Draft the document",
        "role": "writer",
        "district": "D1",
        "skills": [],
        "connectors": [],
        "actions": [],
        "depends_on": [],
    }


# --- tmp config writers ---


def gap_config_dict(*ids: str, nothing_possible: str = "Tilo cannot do any part of this task yet.") -> dict[str, Any]:
    """A valid capability_gaps.yaml as a dict with the given category ids (distinct texts per id)."""
    return {
        "nothing_possible": nothing_possible,
        "categories": [
            {"id": gid, "reason": f"Reason text for {gid}.", "alternative": f"Alternative text for {gid}."}
            for gid in ids
        ],
    }


def write_gap_config(path: pathlib.Path, config: dict[str, Any] | str) -> pathlib.Path:
    text = config if isinstance(config, str) else yaml.safe_dump(config, sort_keys=False)
    path.write_text(text, encoding="utf-8")
    return path


def write_connectors(path: pathlib.Path, names: list[str] | str) -> pathlib.Path:
    text = (
        names
        if isinstance(names, str)
        else yaml.safe_dump([{"id": n.lower().replace(" ", "_"), "name": n} for n in names])
    )
    path.write_text(text, encoding="utf-8")
    return path
