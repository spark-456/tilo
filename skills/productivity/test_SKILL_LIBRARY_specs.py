from __future__ import annotations

import re
from pathlib import Path

import yaml
from tilo_harness.skills import SkillRegistry

ROOT = Path(__file__).resolve().parents[2]
SKILLS = ROOT / "skills" / "productivity"
EXPECTED = {
    "supplier-research-compare",
    "summarise-public-url",
    "draft-email-reply",
    "one-page-plan",
    "meeting-brief-calendar",
    "weekly-status-report",
    "competitor-scan",
    "road-trip-planner",
    "job-description-writer",
    "customer-feedback-digest",
    "inbox-triage-draft-only",
    "proposal-outline",
}


def test_SKILL_LIBRARY_every_new_skill_validates_in_the_registry():
    registry = SkillRegistry(ROOT / "skills")
    assert not {key: value for key, value in registry.problems.items() if key.startswith("productivity/")}
    assert EXPECTED <= {skill_id for skill_id, _ in registry.catalog()}
    assert len(EXPECTED) == 12


def test_SKILL_LIBRARY_cost_estimates_follow_config_and_stay_under_the_run_cap():
    prices = yaml.safe_load((ROOT / "config" / "prices.yaml").read_text(encoding="utf-8"))
    skills_cfg = yaml.safe_load((ROOT / "config" / "skills.yaml").read_text(encoding="utf-8"))
    caps = yaml.safe_load((ROOT / "config" / "spend_caps.yaml").read_text(encoding="utf-8"))
    step_credits = skills_cfg["prior"]["credits_per_step"]
    credit_usd = prices["credit_usd"]
    search_usd = prices["profiles"]["search-google"]["unit_price"]["per_1k"] / 1000
    cap_credits = caps["run_minor"] / 100 / 80 / credit_usd  # config documents INR 80 per US dollar
    for skill_id in EXPECTED:
        folder = SKILLS / skill_id
        data = yaml.safe_load((folder / "skill.yaml").read_text(encoding="utf-8"))
        body = (folder / "SKILL.md").read_text(encoding="utf-8")
        steps_section = body.split("## Steps", 1)[1].split("## Safety", 1)[0]
        step_count = len(re.findall(r"^\d+\. ", steps_section, re.MULTILINE))
        search_cap = int(re.search(r"Search cap: at most (\d+) grounded queries per run\.", body).group(1))
        estimate = step_count * step_credits + search_cap * (search_usd / credit_usd)
        declared = float(re.search(r"est\. max ([0-9.]+) credits/run", data["description"]).group(1))
        declared_usd = float(re.search(r"~\$([0-9.]+)", data["description"]).group(1))
        assert declared == estimate, skill_id
        assert round(declared * credit_usd, 3) == declared_usd, skill_id
        assert declared <= cap_credits, skill_id
