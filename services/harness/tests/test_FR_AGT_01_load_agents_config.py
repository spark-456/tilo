"""FR-AGT-01 (PRD 8.1, 8.6): `tilo_harness.config.load_agents_config(path=None)` loads
config/agents.yaml (the default path) and validates it against contracts/agents.schema.json; an
invalid or missing file raises AgentsConfigError and the harness refuses to start.

`tilo_harness.config` does not exist yet, so every test module here is expected to fail
collection with ImportError until the builder lands the ticket (see conftest.py's docstring).
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml
from agt_support import default_agents_config_dict, write_agents_config
from tilo_harness.config import AgentsConfigError, load_agents_config

REPO_ROOT = Path(__file__).resolve().parents[3]


def test_FR_AGT_01_default_path_loads_the_real_config_agents_yaml() -> None:
    """path=None loads the real config/agents.yaml (already committed, config/ owned by S0) and
    it must validate against contracts/agents.schema.json without raising."""
    config = load_agents_config(path=None)
    assert config is not None


def test_FR_AGT_01_missing_file_raises_agents_config_error(tmp_path: Path) -> None:
    missing = tmp_path / "does_not_exist.yaml"
    with pytest.raises(AgentsConfigError):
        load_agents_config(path=missing)


@pytest.mark.parametrize(
    "overrides",
    [
        pytest.param({"limits": {"directors_per_world": 2}}, id="directors_per_world_must_be_1"),
        pytest.param({"limits": {"leads_per_district": 2}}, id="leads_per_district_must_be_1"),
        pytest.param({"limits": {"max_specialists": 7}}, id="max_specialists_above_6"),
        pytest.param({"limits": {"max_specialists": 0}}, id="max_specialists_below_1"),
        pytest.param({"limits": {"max_depth": 4}}, id="max_depth_must_be_3"),
        pytest.param({"context": {"compact_at": 0.75}}, id="compact_at_must_stay_below_handoff_at_0_70"),
        pytest.param({"context": {"handoff_at": 0.8}}, id="handoff_at_is_fixed_at_0_70"),
        pytest.param({"retries": {"max_attempts": 4}}, id="max_attempts_above_3"),
    ],
)
def test_FR_AGT_01_schema_invalid_config_raises_agents_config_error(tmp_path: Path, overrides: dict) -> None:
    path = write_agents_config(tmp_path / "agents.yaml", **overrides)
    with pytest.raises(AgentsConfigError):
        load_agents_config(path=path)


def test_FR_AGT_01_config_missing_a_required_top_level_section_raises(tmp_path: Path) -> None:
    """A config missing a whole required section (agents.schema.json's top-level "required")
    must be refused, not silently defaulted."""
    data = default_agents_config_dict()
    del data["questions"]
    path = tmp_path / "agents.yaml"
    path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
    with pytest.raises(AgentsConfigError):
        load_agents_config(path=path)


def test_FR_AGT_01_silent_after_s_must_exceed_heartbeat_s(tmp_path: Path) -> None:
    """The harness loader also requires silent_after_s > heartbeat_s (services/harness's own
    rule on top of the schema, per contracts/agents.schema.json's liveness description)."""
    path = write_agents_config(tmp_path / "agents.yaml", liveness={"heartbeat_s": 30, "silent_after_s": 30})
    with pytest.raises(AgentsConfigError):
        load_agents_config(path=path)


def test_FR_AGT_01_not_yaml_raises_agents_config_error(tmp_path: Path) -> None:
    path = tmp_path / "agents.yaml"
    path.write_text("{not: valid: yaml: [", encoding="utf-8")
    with pytest.raises(AgentsConfigError):
        load_agents_config(path=path)


def test_FR_AGT_01_valid_override_loads_cleanly(tmp_path: Path) -> None:
    """A schema-valid config (max_specialists lowered to 3, never raised past the PRD's cap of 6)
    loads without raising -- the positive control for the parametrized negative cases above."""
    path = write_agents_config(tmp_path / "agents.yaml", limits={"max_specialists": 3})
    config = load_agents_config(path=path)
    assert config is not None
