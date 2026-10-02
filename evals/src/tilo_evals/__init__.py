"""tilo_evals: the eval harness (EFF-07; PRD 19): case schema and loader, checks, EvalsConfig, runner and results."""

from .cases import Case, CaseError, load_cases
from .config import EvalsConfig, EvalsConfigError
from .runner import PassResult, run_pass

__all__ = ["Case", "CaseError", "load_cases", "EvalsConfig", "EvalsConfigError", "PassResult", "run_pass"]
