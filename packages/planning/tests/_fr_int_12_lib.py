"""Helpers for the FR-INT-12 acceptance tests (PRD 7.1, 16). No business logic: a scripted Director behind a
real `Router`, a loader for the refusal set, and a tmp refusal-config writer. Named `_fr_int_12_lib` for the same
global-bare-module-name reason as `_planning_contracts_lib` (pytest prepend import mode).

The Director is scripted, never a model: it classifies a task by looking the task text up in a table the test
owns and replies with the category id (or null). That is the recorded-replay stand-in for the model (EFF-01);
what the tests check is everything the CODE does with that reply: the fixed reason and alternative from config,
nothing stored, no echo of the task text, fail closed on an unknown category.
"""

from __future__ import annotations

import copy
import json
import pathlib
from typing import Any

import yaml

REPO_ROOT = pathlib.Path(__file__).resolve().parents[3]
REFUSAL_SET = pathlib.Path(__file__).resolve().parent / "fixtures" / "refusal_set.yaml"

BASE_BRIEF: dict[str, Any] = {
    "goal": "Summarise the weekly supplier prices for the operations lead.",
    "deliverables": [{"title": "Supplier summary", "format": "pdf"}],
    "audience": "Operations lead",
    "deadline": None,
    "constraints": [],
    "sources": [],
    "sensitivity": "business",
    "ambiguous_fields": [],
}


def load_refusal_set() -> dict[str, list[dict[str, str]]]:
    return yaml.safe_load(REFUSAL_SET.read_text(encoding="utf-8"))


def director_reply(out_of_policy: Any = ...) -> dict[str, Any]:
    """The Director's JSON reply. `...` leaves the `out_of_policy` key out entirely (an older reply shape)."""
    reply = copy.deepcopy(BASE_BRIEF)
    if out_of_policy is not ...:
        reply["out_of_policy"] = out_of_policy
    return reply


class ScriptedDirector:
    """Answers every brief request with the reply the test set for the task text found in the prompt. A prompt
    that holds none of the known task texts is a bug in the code under test (the text never reached the
    Director as data), so it fails loudly. Records every request."""

    profile_id = "scripted"

    def __init__(self, replies: dict[str, dict[str, Any]], default: dict[str, Any] | None = None) -> None:
        self.replies, self.default = replies, default
        self.calls: list[Any] = []

    def generate(self, request: Any) -> Any:
        from tilo_providers.interfaces import GenerateResponse  # noqa: PLC0415

        self.calls.append(request)
        for text, reply in self.replies.items():
            if text in request.prompt:
                return GenerateResponse(text=json.dumps(reply), profile_id=self.profile_id)
        if self.default is not None:
            return GenerateResponse(text=json.dumps(self.default), profile_id=self.profile_id)
        raise AssertionError("the task text did not reach the Director's prompt")

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


def make_router(provider: ScriptedDirector, repo_root: pathlib.Path = REPO_ROOT) -> Any:
    """A real Router over the shipped config/models.yaml and prices.yaml; every profile is the scripted one."""
    from tilo_providers.config import load_providers_config  # noqa: PLC0415
    from tilo_providers.router import Router  # noqa: PLC0415

    config = load_providers_config(repo_root / "config" / "models.yaml", repo_root / "config" / "prices.yaml")
    return Router(config, provider_for_profile=lambda _profile_id: provider)


def write_refusal_config(path: pathlib.Path, categories: list[dict[str, Any]] | str) -> pathlib.Path:
    text = categories if isinstance(categories, str) else yaml.safe_dump({"categories": categories})
    path.write_text(text, encoding="utf-8")
    return path


CATEGORY_A = {
    "id": "credential_handling",
    "reason": "Tilo never handles passwords or logins (PRD 16.1).",
    "alternative": "Connect the account with sign-in through its own consent screen, then ask for the work.",
}
CATEGORY_B = {
    "id": "unapproved_send",
    "reason": "Nothing leaves Tilo without your approval or a policy you set.",
    "alternative": "Ask Tilo to prepare the messages as drafts you can approve one by one.",
}
