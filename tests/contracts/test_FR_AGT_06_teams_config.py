"""FR-AGT-06 (PRD 8.3, 8.6; GitHub issue #4 section 3, `spark-456/tilo`, ticket CC-SH).

PRD 8.3: "Team Leads are people assigned to a domain..., in `config/teams.yaml` or the Team
Lead console." PRD 8.6 acceptance test: "A security question reaches the Security Team Lead;
with none configured, the owner." Issue #4: "`config/teams.yaml`: an example file of
`team_lead.schema.json` entries... An empty list is fine; one `security` domain entry would
make the acceptance test fixture-driven." `contracts/team_lead.schema.json` already exists on
this branch (ticket P4-01) -- this ticket only needs the shipped example file.

CLAUDE.md: "Example config files use placeholder people (example.com) only" -- no real names or
addresses go into `config/teams.yaml`.

Test-writer split: `config/teams.yaml` does not exist yet, so every test here must fail for
that reason.
"""

from __future__ import annotations

import yaml
from _cc_sh_lib import sample_team_lead, teams_yaml_path
from _lib import errors_for, load_schema


def test_FR_AGT_06_config_teams_yaml_exists(repo_root):
    path = teams_yaml_path(repo_root)
    assert path.is_file(), "FR-AGT-06: config/teams.yaml must exist (issue #4 section 3, PRD 8.3)"


def test_FR_AGT_06_config_teams_yaml_is_a_list(repo_root):
    path = teams_yaml_path(repo_root)
    assert path.is_file(), "FR-AGT-06: see the config-exists test"
    entries = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert isinstance(entries, list), (
        f"FR-AGT-06: config/teams.yaml should be a list of team_lead.schema.json entries "
        f"(issue #4: 'an example file of team_lead.schema.json entries'; 'An empty list is "
        f"fine'), got {type(entries).__name__}"
    )


def test_FR_AGT_06_each_teams_yaml_entry_validates_against_team_lead_schema(repo_root, registry):
    """team_lead.schema.json is already on this branch (ticket P4-01) -- CC-SH does not
    change it, only ships an example file shaped by it."""
    path = teams_yaml_path(repo_root)
    assert path.is_file(), "FR-AGT-06: see the config-exists test"
    entries = yaml.safe_load(path.read_text(encoding="utf-8")) or []
    schema = load_schema(repo_root, "team_lead")
    for i, entry in enumerate(entries):
        errors = errors_for(schema, entry, registry)
        assert not errors, (
            f"FR-AGT-06: config/teams.yaml entry {i} must validate against team_lead.schema.json, "
            f"got: {[e.message for e in errors][:5]}"
        )


def test_FR_AGT_06_teams_yaml_has_a_security_domain_entry(repo_root):
    """Issue #4: 'one security domain entry would make the acceptance test fixture-driven'
    (PRD 8.6 FR-AGT-06: 'A security question reaches the Security Team Lead')."""
    path = teams_yaml_path(repo_root)
    assert path.is_file(), "FR-AGT-06: see the config-exists test"
    entries = yaml.safe_load(path.read_text(encoding="utf-8")) or []
    domains = [e.get("domain") for e in entries if isinstance(e, dict)]
    assert "security" in domains, (
        f"FR-AGT-06: config/teams.yaml must have at least one entry with domain: security "
        f"(issue #4), got domains {domains}"
    )


def test_FR_AGT_06_teams_yaml_uses_no_real_people(repo_root):
    """CLAUDE.md: 'Example config files use placeholder people (example.com) only.'
    contracts/fixtures/team_lead/valid/ already establishes the placeholder convention
    (u_finance_lead, u_ops_lead); config/teams.yaml must follow it, never a real name, real
    email domain or the repo's own git identity / user email."""
    path = teams_yaml_path(repo_root)
    assert path.is_file(), "FR-AGT-06: see the config-exists test"
    text = path.read_text(encoding="utf-8").lower()
    forbidden = ("gmail.com", "sacheevkrish", "spark-456", "regi")
    hits = [term for term in forbidden if term in text]
    assert not hits, f"FR-AGT-06: config/teams.yaml must not name a real person or address, found: {hits}"


def test_FR_AGT_06_sample_team_lead_matches_shipped_schema(repo_root, registry):
    """Sanity check on the helper itself: _cc_sh_lib.sample_team_lead() must already validate
    against the team_lead schema that exists today, so the teams.yaml tests above fail only
    because config/teams.yaml is missing, not because the helper is wrong."""
    schema = load_schema(repo_root, "team_lead")
    errors = errors_for(schema, sample_team_lead(), registry)
    msgs = [e.message for e in errors][:5]
    assert not errors, f"FR-AGT-06: sample_team_lead() should validate against team_lead.schema.json, got: {msgs}"
