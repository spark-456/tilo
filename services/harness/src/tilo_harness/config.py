"""config/agents.yaml loader (FR-AGT-01, PRD 8.1): role limits, context thresholds, liveness,
retries and question load control, validated against contracts/agents.schema.json. A missing,
unreadable or invalid file raises `AgentsConfigError`, so the harness refuses to start."""

from __future__ import annotations

from pathlib import Path

import yaml
from tilo_contracts import AgentsConfig

from tilo_harness.validator import repo_validator

__all__ = ["DEFAULT_AGENTS_CONFIG", "AgentsConfig", "AgentsConfigError", "load_agents_config"]

# services/harness/src/tilo_harness/config.py -> repo root is 4 parents up.
DEFAULT_AGENTS_CONFIG = Path(__file__).resolve().parents[4] / "config" / "agents.yaml"


class AgentsConfigError(Exception):
    """config/agents.yaml is missing, not YAML, or breaks contracts/agents.schema.json."""


def load_agents_config(path: Path | None = None) -> AgentsConfig:
    path = Path(path) if path is not None else DEFAULT_AGENTS_CONFIG
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, yaml.YAMLError) as error:
        raise AgentsConfigError(f"{path}: cannot read agents config ({type(error).__name__})") from error
    problems = repo_validator().contract_problems("agents", data)
    if problems:
        raise AgentsConfigError(f"{path}: " + "; ".join(problems))
    if data["liveness"]["silent_after_s"] <= data["liveness"]["heartbeat_s"]:
        raise AgentsConfigError(f"{path}: liveness.silent_after_s must exceed liveness.heartbeat_s")
    return AgentsConfig.model_validate(data)
