from __future__ import annotations

from _ppl11a_lib import PRIYA


def test_SKILL_LIBRARY_new_builtins_are_listed_to_a_signed_in_user_and_hide_internal(skills4):
    skills4.rig.as_user(PRIYA)
    response = skills4.rig.get("/v1/skills?include_builtin=true")
    assert response.status_code == 200, response.text
    rows = response.json()["builtins"]
    by_id = {row["id"]: row for row in rows}
    expected = {
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
    assert expected <= by_id.keys()
    assert all(by_id[skill_id]["description"] and by_id[skill_id]["version"] == "1.0.0" for skill_id in expected)
    assert {"agent-self-report", "skill-from-description", "try-run-match"}.isdisjoint(by_id)
