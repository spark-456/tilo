"""Shared, non-test support for the FR-AGT-15 API acceptance tests (services/api; module `tilo_api.skill_proposals`).

The module does not exist yet, so every helper that needs it imports it lazily; each test then fails with
ModuleNotFoundError until a builder ships it (interface: API_FR_AGT_15.md in this directory). Self-contained on
purpose: another ticket's helper module is never imported (the bare-module-name collision rule in conftest.py).

No business logic: skill folders, a Decision double, Team Lead records and a Principal per request are plain data.
"""

from __future__ import annotations

import pathlib
import re
from typing import Any

import yaml
from fastapi import FastAPI
from fastapi.testclient import TestClient
from tilo_api import deps

W = "w_village_basic"
OWNER = "u_owner"
LEAD_A = "u_lead_a"  # Team Lead of `research`, gave the answer, proposes
EXPERT_B = "u_expert_b"  # a second Team Lead of `research`: the expert who reviews
LEAD_SEC = "u_sec"  # Team Lead of `security`
STRANGER = "u_stranger"
SKILL_ID = "web_research"
DOMAIN = "research"
DECISION_ID = "01J8Z3K4M5N6P7Q8R9S0T1V2W6"
ASSIGNED = {"by": OWNER, "at": "2026-09-01T00:00:00.000Z"}
MAX_GUIDANCE_CHARS = 2000

BODY = (
    "# Web research\n\n"
    "When to use: a unit needs facts gathered from open web sources with citations.\n\n"
    "## Steps\n"
    "1. Form 2-3 search queries from the unit's brief.\n\n"
    "## Quality bar\n"
    "Every claim has at least one citation.\n"
)

TEAM_LEADS = [
    {"id": "tl_research", "user": LEAD_A, "domain": DOMAIN, "assigned_by": ASSIGNED},
    {"id": "tl_research_2", "user": EXPERT_B, "domain": DOMAIN, "assigned_by": ASSIGNED},
    {"id": "tl_security", "user": LEAD_SEC, "domain": "security", "assigned_by": ASSIGNED},
]


def write_skill(root: pathlib.Path, *, body: str = BODY) -> pathlib.Path:
    folder = root / DOMAIN / SKILL_ID
    folder.mkdir(parents=True, exist_ok=True)
    data = {
        "id": SKILL_ID,
        "version": "1.0.0",
        "domain": DOMAIN,
        "author": "Ada Example",
        "reviewer": "Grace Example",
        "tools_allowed": ["search_web"],
        "inputs": {"type": "object", "required": ["query"], "properties": {"query": {"type": "string"}}},
        "outputs": {"type": "object", "required": ["findings"], "properties": {"findings": {"type": "array"}}},
        "description": "Web research with citations for a specialist unit.",
    }
    (folder / "skill.yaml").write_bytes(yaml.safe_dump(data, sort_keys=False).encode())
    (folder / "SKILL.md").write_bytes(body.encode("utf-8"))
    return folder


def tree_snapshot(root: pathlib.Path) -> dict[str, bytes]:
    return {p.relative_to(root).as_posix(): p.read_bytes() for p in sorted(root.rglob("*")) if p.is_file()}


def decision(
    *, answer: str = "Prefer sources dated within the last 12 months; flag older ones as stale.", world_id: str = W
) -> dict[str, Any]:
    """A Team Lead's Decision (contracts/decision.schema.json) for LEAD_A in `research`."""
    return {
        "id": DECISION_ID,
        "org_id": "org_acme",
        "question": "How old may a source be before the research skill must flag it?",
        "domain": DOMAIN,
        "answer": answer,
        "option_id": None,
        "answered_by": {"by": "team_lead", "ref": "tl_research", "user": LEAD_A, "at": "2026-10-05T10:00:00.000Z"},
        "source": {"world_id": world_id, "run_id": "r_village_basic_1", "card_id": "01J8Z3K4M5N6P7Q8R9S0T1V2W2"},
        "scope": {"worlds": "all", "districts": "all"},
        "created_at": "2026-10-05T10:00:01.000Z",
        "expires_at": None,
    }


class FakeDecisions:
    """`get(decision_id) -> dict | None`: the Decision store tilo-api reads (decision.schema.json records)."""

    def __init__(self, *records: dict[str, Any]) -> None:
        self.records = {r["id"]: r for r in records}

    def get(self, decision_id: str) -> dict[str, Any] | None:
        return self.records.get(decision_id)


def principal(role: str, user_id: str, *, world_id: str | None = W) -> deps.Principal:
    return deps.Principal(user_id=user_id, role=role, world_id=world_id)  # type: ignore[arg-type]


def module() -> Any:
    import tilo_api.skill_proposals as skill_proposals  # noqa: PLC0415

    return skill_proposals


def make_proposals(root: pathlib.Path) -> Any:
    from tilo_harness.skill_proposals import SkillProposals  # noqa: PLC0415
    from tilo_harness.skills import SkillRegistry  # noqa: PLC0415

    return SkillProposals(SkillRegistry(root), clock=lambda: "2026-10-06T09:00:00.000Z")


def client(
    proposals: Any,
    who: deps.Principal,
    *,
    decisions: FakeDecisions | None = None,
    team_leads: list[dict[str, Any]] | None = None,
) -> TestClient:
    """A TestClient over `skill_proposals.build_router(proposals, owner_of=...)` with the caller, the Decision store and
    the Team Lead records (config/teams.yaml via `tilo_api.console.get_team_leads`) injected. Never a real sign-in."""
    import tilo_api.console as console  # noqa: PLC0415

    skill_proposals = module()
    app = FastAPI()
    app.include_router(skill_proposals.build_router(proposals, owner_of=lambda world: OWNER if world == W else None))
    app.dependency_overrides[deps.get_current_principal] = lambda: who
    app.dependency_overrides[skill_proposals.get_decision_store] = lambda: decisions or FakeDecisions(decision())
    app.dependency_overrides[console.get_team_leads] = lambda: list(TEAM_LEADS if team_leads is None else team_leads)
    return TestClient(app)


def url(suffix: str = "", world: str = W) -> str:
    return f"/worlds/{world}/skill-proposals{suffix}"


def promote(http: TestClient, **body: Any) -> Any:
    payload = {"decision_id": DECISION_ID, "skill_id": SKILL_ID} | body
    return http.post(url(), json=payload)


SAFE_ID = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
