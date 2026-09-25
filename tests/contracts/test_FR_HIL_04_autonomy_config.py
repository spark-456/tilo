"""FR-HIL-04 / PRD 10.4: the risk-tier table the policy engine loads is config/autonomy.yaml
(issue #1). It must exist and validate against policy.schema.json#/$defs/risk_tier_table.
`just contracts-check` validates it only when present (its drift sandbox has no config/), so this
test is what fails when the file is missing."""

from __future__ import annotations

import yaml
from _lib import errors_for

TABLE = {"$ref": "https://contracts.tilo.example/policy.schema.json#/$defs/risk_tier_table"}


def test_FR_HIL_04_autonomy_config_is_a_valid_risk_tier_table(repo_root, registry):
    path = repo_root / "config" / "autonomy.yaml"
    assert path.is_file(), "config/autonomy.yaml must exist: the policy engine fails closed without it"
    table = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert not [e.message for e in errors_for(TABLE, table, registry)]
    assert table["max_level"]["T3"] == "L1", "T3 runs at L1 only: always a person (PRD 10.4)"
