"""tilo_evals: the eval harness (EFF-07; PRD 19). Case schema and loader,
the deterministic-check registry, replay/fake executors, the pass runner and
honest results reporting (evals/CLAUDE.md; SE ticket spec "## P8-06").
"""

from __future__ import annotations

from .cases import Case, CaseError, load_cases
from .config import EvalsConfig, EvalsConfigError

__all__ = [
    "Case",
    "CaseError",
    "load_cases",
    "EvalsConfig",
    "EvalsConfigError",
]
