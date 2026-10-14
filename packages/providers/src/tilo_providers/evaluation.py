"""tilo_providers.evaluation — the `eval_judge` role's provider (VERTEX-EVAL-1, ADR-0033).

`FakeEvalProvider` is a deterministic dev stand-in (verdict from sha256(metric|id) only, visibly fake).
`build_eval_provider` reads the role's primary and never its fallback (one judge per run: a judge that changes in
the middle of a run invalidates the comparison). There is no record-and-replay provider: dev and CI use the fake."""

from __future__ import annotations

import hashlib
import os
from typing import Literal

from tilo_providers.config import ProviderConfigError, ProvidersConfig
from tilo_providers.interfaces import EvalProvider, EvalRequest, EvalScore
from tilo_providers.replay import is_live_mode

EVAL_ROLE = "eval_judge"
_CHOICES: tuple[Literal["candidate"], Literal["baseline"], Literal["tie"]] = ("candidate", "baseline", "tie")


class FakeEvalProvider(EvalProvider):
    """Choice and score come from sha256(metric|id); the texts never move them. Pointwise scores are 0.0 or 1.0."""

    def _evaluate(self, request: EvalRequest) -> EvalScore:
        digest = hashlib.sha256(f"{request.metric}|{request.item.id}".encode()).digest()
        explanation = "fake judgement (dev stand-in)"
        if request.kind == "pairwise":
            return EvalScore(choice=_CHOICES[digest[0] % 3], explanation=explanation)
        return EvalScore(score=float(digest[1] % 2), explanation=explanation)


def build_eval_provider(config: ProvidersConfig, *, live_permitted: bool = False) -> EvalProvider:
    """`fake` -> `FakeEvalProvider` (refused when live or deployed); `vertex_eval` -> the live adapter (needs the live
    switch or `live_permitted`, SEC-15; project from `GOOGLE_CLOUD_PROJECT`, location from `TILO_VERTEX_EVAL_LOCATION`,
    default asia-southeast1). Anything else, or a missing role, is a `ProviderConfigError`."""
    if EVAL_ROLE not in config.roles:
        raise ProviderConfigError(f"VERTEX-EVAL-1: config has no {EVAL_ROLE!r} role")
    profile_id = config.roles[EVAL_ROLE].primary
    profile = config.profiles[profile_id]
    if profile.provider == "fake":
        # Presence, not truthiness: Cloud Run can set a variable to an empty string.
        if is_live_mode() or "K_SERVICE" in os.environ or "CLOUD_RUN_JOB" in os.environ:
            raise ProviderConfigError(
                f"VERTEX-EVAL-1: refusing the fake eval judge for {profile_id!r} in live mode or when deployed"
            )
        return FakeEvalProvider()
    if profile.provider != "vertex_eval":
        raise ProviderConfigError(f"VERTEX-EVAL-1: unknown eval provider {profile.provider!r} for {profile_id!r}")
    if not (is_live_mode() or live_permitted):
        raise ProviderConfigError(
            "VERTEX-EVAL-1/EFF-01: refusing to build the live eval adapter without the live switch"
        )
    project = os.environ.get("GOOGLE_CLOUD_PROJECT")
    if not project:
        raise ProviderConfigError(
            f"VERTEX-EVAL-1: GOOGLE_CLOUD_PROJECT is not set; cannot judge live for {profile_id!r}"
        )
    location = os.environ.get("TILO_VERTEX_EVAL_LOCATION", "asia-southeast1")
    from tilo_providers import vertex_eval_adapter  # noqa: PLC0415  (lazy: the fake never loads it)

    return vertex_eval_adapter.VertexEvalProvider(
        profile_id=profile_id, model=profile.model, project=project, location=location, live_permitted=live_permitted
    )
