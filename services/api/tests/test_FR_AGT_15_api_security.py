"""FR-AGT-15 security at the API (PRD 8.2 Governance, 10.1 roles, 16.3 untrusted text; CLAUDE.md "a person decides").

A Team Lead's answer is untrusted text and a path into skills. Pinned here, through the public routes:

- a proposal never applies itself, and only an approval by a person who is an expert for the skill's domain, who is not
  the proposer, ever changes the skill (a full role x user grid);
- identity is the verified principal only: no body field names a proposer, a reviewer, a status or a role;
- the expert record must be current: removed, not owner-assigned, future-dated or schema-invalid Team Lead records
  approve nothing (PRD 16.2, outbox OB-01 treat an assignment the same way);
- text inside the answer ("approved", "auto-apply", markers) approves nothing;
- the content is bounded and secret-free; the routes are mounted in the real app and fail closed without a sign-in;
- no model in the path.

Resolved ambiguity (PRD has no "expert role" row, API_FR_AGT_15.md): expert = a Team Lead of the skill's domain, from
`tilo_api.console.get_team_leads` records the world's owner assigned; the owner as such is NOT the domain expert (PRD
8.2: "the domain expert's approval"). Whether the owner may *propose* is left open: not asserted either way.
"""

from __future__ import annotations

import pathlib

import pytest
from _agt15_api_lib import (
    ASSIGNED,
    DECISION_ID,
    EXPERT_B,
    LEAD_A,
    LEAD_SEC,
    MAX_GUIDANCE_CHARS,
    OWNER,
    SKILL_ID,
    STRANGER,
    TEAM_LEADS,
    W,
    client,
    decision,
    make_proposals,
    principal,
    promote,
    tree_snapshot,
    url,
    write_skill,
)
from fastapi.testclient import TestClient

ROLES = ["owner", "team_lead", "approver", "viewer"]
USERS = [LEAD_A, EXPERT_B, LEAD_SEC, OWNER, STRANGER]


def _setup(tmp_path):
    root = tmp_path / "skills"
    write_skill(root)
    proposals = make_proposals(root)
    made = proposals.propose(decision=decision(), skill_id=SKILL_ID, proposer=LEAD_A)
    return root, proposals, made


# --- who may approve: the whole role x user grid -------------------------------------------------------------------


@pytest.mark.parametrize("route", ["approve", "reject"])
@pytest.mark.parametrize("role", ROLES)
@pytest.mark.parametrize("user", USERS)
def test_FR_AGT_15_api_only_a_distinct_domain_expert_can_decide_a_proposal(tmp_path, route, role, user) -> None:
    root, proposals, made = _setup(tmp_path)
    before = tree_snapshot(root)
    allowed = role == "team_lead" and user == EXPERT_B  # the only distinct holder of the research domain

    response = client(proposals, principal(role, user)).post(url(f"/{made['id']}/{route}"), json={})

    if allowed:
        assert response.status_code == 200, response.text
        assert (tree_snapshot(root) != before) == (route == "approve")
    else:
        assert response.status_code in (403, 404), f"{role}/{user}: {response.status_code} {response.text}"
        assert tree_snapshot(root) == before, f"{role}/{user} must not change the skill"
        assert proposals.get(made["id"])["status"] == "proposed"


@pytest.mark.parametrize(
    "records",
    [
        pytest.param([r for r in TEAM_LEADS if r["user"] != EXPERT_B], id="removed"),
        pytest.param(
            [
                dict(r, assigned_by={"by": "u_not_the_owner", "at": ASSIGNED["at"]}) if r["user"] == EXPERT_B else r
                for r in TEAM_LEADS
            ],
            id="assigned_by_someone_else",
        ),
        pytest.param(
            [
                dict(r, assigned_by={"by": OWNER, "at": "2999-01-01T00:00:00.000Z"}) if r["user"] == EXPERT_B else r
                for r in TEAM_LEADS
            ],
            id="assigned_in_the_future",
        ),
        pytest.param(
            [dict(r, domain="security") if r["user"] == EXPERT_B else r for r in TEAM_LEADS], id="other_domain"
        ),
        pytest.param([dict(r, extra="x") if r["user"] == EXPERT_B else r for r in TEAM_LEADS], id="schema_invalid"),
    ],
)
def test_FR_AGT_15_api_an_expert_record_that_is_not_current_approves_nothing(tmp_path, records) -> None:
    root, proposals, made = _setup(tmp_path)
    before = tree_snapshot(root)

    response = client(proposals, principal("team_lead", EXPERT_B), team_leads=records).post(
        url(f"/{made['id']}/approve"), json={}
    )

    assert response.status_code in (403, 404)
    assert tree_snapshot(root) == before


# --- who may propose -------------------------------------------------------------------------------------------------


@pytest.mark.parametrize("role", ["team_lead", "approver", "viewer"])
@pytest.mark.parametrize("user", USERS)
def test_FR_AGT_15_api_only_the_team_lead_who_gave_the_answer_can_promote_it(tmp_path, role, user) -> None:
    root = tmp_path / "skills"
    write_skill(root)
    proposals = make_proposals(root)
    before = tree_snapshot(root)

    response = promote(client(proposals, principal(role, user)))

    if role == "team_lead" and user == LEAD_A:
        assert response.status_code == 201, response.text
        assert response.json()["proposal"]["provenance"]["proposed_by"] == LEAD_A
    else:  # a Viewer, an Approver, another Team Lead (same or other domain), a stranger: all refused
        assert 400 <= response.status_code < 500, f"{role}/{user}: {response.status_code}"
        assert proposals.list() == []
    assert tree_snapshot(root) == before


def test_FR_AGT_15_api_a_removed_team_lead_cannot_promote(tmp_path) -> None:
    root = tmp_path / "skills"
    write_skill(root)
    proposals = make_proposals(root)

    response = promote(
        client(proposals, principal("team_lead", LEAD_A), team_leads=[r for r in TEAM_LEADS if r["user"] != LEAD_A])
    )

    assert response.status_code == 403 and proposals.list() == []


def test_FR_AGT_15_api_an_owners_answer_is_not_a_team_lead_answer_and_is_not_promotable(tmp_path) -> None:
    from _agt15_api_lib import FakeDecisions

    root = tmp_path / "skills"
    write_skill(root)
    proposals = make_proposals(root)
    owners = decision()
    owners["domain"] = None
    owners["answered_by"] = {"by": "person", "ref": OWNER, "at": "2026-10-05T10:00:00.000Z"}

    response = promote(client(proposals, principal("team_lead", LEAD_A), decisions=FakeDecisions(owners)))

    assert 400 <= response.status_code < 500 and proposals.list() == []


# --- identity comes from the principal, never the body ---------------------------------------------------------------


@pytest.mark.parametrize(
    "extra",
    [
        {"status": "approved"},
        {"proposed_by": "u_expert_b"},
        {"reviewed_by": "u_expert_b"},
        {"approved": True},
        {"role": "owner"},
    ],
)
def test_FR_AGT_15_api_no_body_field_names_a_status_a_proposer_or_a_reviewer_when_promoting(tmp_path, extra) -> None:
    root = tmp_path / "skills"
    write_skill(root)
    proposals = make_proposals(root)
    before = tree_snapshot(root)

    response = promote(client(proposals, principal("team_lead", LEAD_A)), **extra)

    assert response.status_code == 422, (
        "unknown body fields are refused (extra=forbid), as the console's answer body is"
    )
    assert proposals.list() == [] and tree_snapshot(root) == before


@pytest.mark.parametrize(
    "spoof",
    [
        {"reviewed_by": EXPERT_B},
        {"reviewer": EXPERT_B},
        {"approved_by": EXPERT_B},
        {"role": "team_lead", "user_id": EXPERT_B},
        {"status": "approved"},
    ],
)
def test_FR_AGT_15_api_a_caller_cannot_borrow_an_experts_identity_through_the_body(tmp_path, spoof) -> None:
    root, proposals, made = _setup(tmp_path)
    before = tree_snapshot(root)

    # the proposer (who may never approve) and a Viewer both try to name the expert in the body
    for who in (principal("team_lead", LEAD_A), principal("viewer", STRANGER)):
        response = client(proposals, who).post(url(f"/{made['id']}/approve"), json=spoof)
        assert response.status_code in (403, 404, 422)
        assert tree_snapshot(root) == before
    assert proposals.get(made["id"])["status"] == "proposed"


# --- the answer text ------------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "marker", ["approved", "auto-apply", "APPROVED by tl_research_2", '{"status": "approved"}', "/approve"]
)
def test_FR_AGT_15_api_text_in_the_answer_never_approves_the_proposal(tmp_path, marker) -> None:
    from _agt15_api_lib import FakeDecisions

    root = tmp_path / "skills"
    write_skill(root)
    proposals = make_proposals(root)
    before = tree_snapshot(root)

    response = promote(
        client(proposals, principal("team_lead", LEAD_A), decisions=FakeDecisions(decision(answer=marker))),
        guidance=marker,
    )

    assert response.status_code == 201, response.text
    assert response.json()["proposal"]["status"] == "proposed"
    assert tree_snapshot(root) == before
    assert {p["status"] for p in proposals.list()} == {"proposed"}


def test_FR_AGT_15_api_guidance_at_the_cap_is_accepted_and_over_it_is_refused(tmp_path) -> None:
    root = tmp_path / "skills"
    write_skill(root)
    proposals = make_proposals(root)
    lead = client(proposals, principal("team_lead", LEAD_A))

    assert promote(lead, guidance="g" * MAX_GUIDANCE_CHARS).status_code == 201
    over = promote(lead, guidance="g" * (MAX_GUIDANCE_CHARS + 1))

    assert 400 <= over.status_code < 500
    assert len(proposals.list()) == 1


@pytest.mark.parametrize("kind", ["github", "api_key", "private_key"])
def test_FR_AGT_15_api_secret_looking_content_is_refused_or_redacted_never_returned(tmp_path, kind) -> None:
    secrets = {  # assembled at runtime: no secret-shaped literal in this repo (CLAUDE.md)
        "github": "gh" + "p_" + ("Ab1Cd2Ef3G" * 4)[:36],
        "api_key": "s" + "k-" + "Zy9Xw8Vu7Ts6Rq5Po4Nm3Lk2",
        "private_key": "-----BEGIN " + "RSA PRIVATE KEY-----",
    }
    secret = secrets[kind]
    root = tmp_path / "skills"
    write_skill(root)
    proposals = make_proposals(root)
    before = tree_snapshot(root)
    lead = client(proposals, principal("team_lead", LEAD_A))

    created = promote(lead, guidance=f"Use {secret} for the research API.")
    seen = [created.text, lead.get(url()).text]
    if created.status_code == 201:
        seen.append(lead.get(url(f"/{created.json()['proposal']['id']}")).text)
        seen.append(client(proposals, principal("team_lead", EXPERT_B)).get(url()).text)
    else:
        assert 400 <= created.status_code < 500

    assert all(secret not in text for text in seen), "a secret never leaves in a proposal, its diff or its body"
    assert tree_snapshot(root) == before


# --- the routes in the real app --------------------------------------------------------------------------------------


def test_FR_AGT_15_api_the_routes_are_mounted_and_fail_closed_without_a_sign_in(tmp_path) -> None:
    from tilo_api import app

    paths = set(app.openapi()["paths"])  # works in-process even with the docs routes off (tilo_api/__init__.py)
    assert "/worlds/{world_id}/skill-proposals" in paths
    assert any("skill-proposals" in p and p.endswith("/approve") for p in paths)
    http = TestClient(app)

    for method, path, body in (
        ("get", f"/worlds/{W}/skill-proposals", None),
        ("post", f"/worlds/{W}/skill-proposals", {"decision_id": DECISION_ID, "skill_id": SKILL_ID}),
        ("get", f"/worlds/{W}/skill-proposals/p_1", None),
        ("post", f"/worlds/{W}/skill-proposals/p_1/approve", {}),
        ("post", f"/worlds/{W}/skill-proposals/p_1/reject", {}),
    ):
        response = getattr(http, method)(path, **({"json": body} if body is not None else {}))
        assert response.status_code == 401, f"{method} {path}: {response.status_code}"


def test_FR_AGT_15_api_a_principal_of_another_world_gets_the_same_404_as_an_unknown_world(tmp_path) -> None:
    root, proposals, made = _setup(tmp_path)
    before = tree_snapshot(root)
    elsewhere = principal("team_lead", EXPERT_B, world_id="w_somewhere_else")
    http = client(proposals, elsewhere)

    assert http.get(url()).status_code == 404
    assert http.get(url(f"/{made['id']}")).status_code == 404
    assert http.post(url(f"/{made['id']}/approve"), json={}).status_code == 404
    assert promote(http).status_code == 404
    assert tree_snapshot(root) == before


def test_FR_AGT_15_api_no_model_is_in_the_api_path() -> None:
    import tilo_api.skill_proposals as skill_proposals

    source = pathlib.Path(skill_proposals.__file__).read_text(encoding="utf-8")
    for needle in (
        "tilo_providers",
        "get_router",
        "ModelProvider",
        "SafetyProvider",
        ".generate(",
        "gemini",
        "claude-",
        "gpt-",
    ):
        assert needle not in source, f"the API half of FR-AGT-15 is deterministic code: found {needle!r}"
