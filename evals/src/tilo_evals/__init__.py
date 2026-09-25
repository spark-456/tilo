"""tilo_evals: the eval harness (EFF-07; PRD 19). This part: case schema/loader, the check registry, and EvalsConfig."""

from .cases import Case, CaseError, load_cases
from .config import EvalsConfig, EvalsConfigError

__all__ = ["Case", "CaseError", "load_cases", "EvalsConfig", "EvalsConfigError"]
