"""ADR-0046: signed invite links are single-use and disclose no bearer material."""

import hashlib

from _ppl11a_lib import ORG, OWNER, SAM

TEAM = "tm_launch"


def _rig(people_rig, monkeypatch):
    monkeypatch.setenv("TILO_INVITE_LINK_KEY", "".join("x" for _ in range(40)))
    monkeypatch.setenv("TILO_INVITE_LINK_KEY_ID", "key_a")
    rig = people_rig()
    rig.add_people()
    rig.as_user(OWNER)
    rig.email = "asha@example.com"
    return rig


def _make(rig):
    return rig.post(f"/v1/teams/{TEAM}/invite-links", {})


def test_SELF_SERVE_TEAMS_INVITE_LINK_create_needs_a_lead_or_org_owner_in_a_full_session(people_rig, monkeypatch):
    rig = _rig(people_rig, monkeypatch)
    rig.as_user(SAM)
    assert _make(rig).status_code == 403
    rig.as_user(OWNER)
    for channel, full, world in (("email", True, None), ("web", False, None), ("web", True, "w_else")):
        rig.channel, rig.full_session, rig.world_id = channel, full, world
        assert _make(rig).status_code == 403
    rig.channel, rig.full_session, rig.world_id = "web", True, None
    assert _make(rig).status_code == 201


def test_SELF_SERVE_TEAMS_INVITE_LINK_create_returns_the_token_once_and_stores_only_its_digest(people_rig, monkeypatch):
    rig = _rig(people_rig, monkeypatch)
    made = _make(rig)
    assert made.status_code == 201, made.text
    token = made.json()["token"]
    invite_id = made.json()["invite_id"]
    stored = rig.stores.persons._invite_links.get(ORG, invite_id).record
    assert (
        stored["nonce_sha256"]
        == hashlib.sha256(__import__("base64").urlsafe_b64decode(token.split(".")[3] + "=")).hexdigest()
    )
    assert token not in str(stored)
    listing = rig.client.get(f"/v1/teams/{TEAM}/invite-links")
    assert listing.status_code == 200 and token not in listing.text
    assert token not in str(rig.events.calls)


def test_SELF_SERVE_TEAMS_INVITE_LINK_accept_writes_one_counting_entry_stamped_by_the_maker(people_rig, monkeypatch):
    rig = _rig(people_rig, monkeypatch)
    token = _make(rig).json()["token"]
    rig.as_user(SAM)
    rig.email = "sam@example.com"
    answer = rig.post("/v1/team-invite-links/accept", {"token": token})
    assert answer.status_code == 200, answer.text
    assert answer.json() == {"team": TEAM, "state": "member"}
    entry = next(m for m in rig.stored("persons", SAM)["memberships"] if m["team"] == TEAM)
    assert entry["assigned_by"]["by"] == OWNER and entry["accepted_at"] == rig.clock
    assert rig.post("/v1/team-invite-links/accept", {"token": token}).json() == {"detail": "invite_unavailable"}


def test_SELF_SERVE_TEAMS_INVITE_LINK_create_and_accept_need_a_usable_key(people_rig, monkeypatch):
    rig = _rig(people_rig, monkeypatch)
    token = _make(rig).json()["token"]
    monkeypatch.delenv("TILO_INVITE_LINK_KEY")
    assert _make(rig).json() == {"detail": "not_configured"}
    assert rig.client.get(f"/v1/teams/{TEAM}/invite-links").status_code == 200
    rig.as_user(SAM)
    rig.email = "sam@example.com"
    assert rig.post("/v1/team-invite-links/accept", {"token": token}).json() == {"detail": "not_configured"}
