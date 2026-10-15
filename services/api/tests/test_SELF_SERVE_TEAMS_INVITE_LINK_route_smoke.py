"""The invite HTTP flow is wired to the signed, single-use store."""

from _ppl11a_lib import OWNER, SAM


def test_SELF_SERVE_TEAMS_INVITE_LINK_create_then_accept_once(people_rig, monkeypatch):
    monkeypatch.setenv("TILO_INVITE_LINK_KEY", "".join("x" for _ in range(40)))
    rig = people_rig()
    rig.add_people()
    rig.as_user(OWNER)
    rig.email = "asha@example.com"
    made = rig.post("/v1/teams/tm_launch/invite-links", {})
    assert made.status_code == 201, made.text
    rig.as_user(SAM)
    rig.email = "sam@example.com"
    token = made.json()["token"]
    first = rig.post("/v1/team-invite-links/accept", {"token": token})
    second = rig.post("/v1/team-invite-links/accept", {"token": token})
    assert first.json() == {"team": "tm_launch", "state": "member"}
    assert second.status_code == 404
