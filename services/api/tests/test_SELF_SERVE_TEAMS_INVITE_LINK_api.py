"""ADR-0046: signed invite links are single-use and disclose no bearer material."""

import hashlib
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

from _ppl11a_lib import ORG, OWNER, SAM
from tilo_policy.schemas import conforms

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


def test_SELF_SERVE_TEAMS_INVITE_LINK_tampered_or_malformed_tokens_get_the_one_404(people_rig, monkeypatch):
    rig = _rig(people_rig, monkeypatch)
    token = _make(rig).json()["token"]
    rig.as_user(SAM)
    rig.email = "sam@example.com"
    parts = token.split(".")
    bad = [
        token[:-1] + ("A" if token[-1] != "A" else "B"),
        token.replace("key_a", "key_b"),
        "v2." + token[3:],
        token + ".x",
        token + "x" * 201,
        ".".join([*parts[:3], parts[3][:-1] + "=", parts[4]]),
    ]
    answers = [rig.post("/v1/team-invite-links/accept", {"token": value}) for value in bad]
    assert all(r.status_code == 404 and r.json() == {"detail": "invite_unavailable"} for r in answers)
    assert len({r.content for r in answers}) == 1


def test_SELF_SERVE_TEAMS_INVITE_LINK_create_lives_7_days_and_caps_10_pending_per_team(people_rig, monkeypatch):
    rig = _rig(people_rig, monkeypatch)
    for _ in range(10):
        made = _make(rig)
        assert made.status_code == 201, made.text
        assert made.json()["expires_at"] == "2026-10-13T10:00:00.000Z"
    assert _make(rig).json() == {"detail": "too_many_links"}
    rig.set_now("2026-10-13T10:00:00.000Z")
    assert _make(rig).status_code == 201


def test_SELF_SERVE_TEAMS_INVITE_LINK_accept_needs_a_verified_full_session(people_rig, monkeypatch):
    rig = _rig(people_rig, monkeypatch)
    token = _make(rig).json()["token"]
    rig.as_user(SAM)
    rig.email = None
    before = len(rig.store_calls)
    assert rig.post("/v1/team-invite-links/accept", {"token": token}).status_code == 403
    assert not any(method in ("get", "list") for _, method, _ in rig.store_calls[before:])


def test_SELF_SERVE_TEAMS_INVITE_LINK_membership_limit_is_409_and_consumes_nothing(people_rig, monkeypatch):
    rig = _rig(people_rig, monkeypatch)
    made = _make(rig).json()
    old = rig.real.persons.get(ORG, SAM)
    extra = [{"team": f"tm_extra_{i}", "assigned_by": {"by": OWNER, "at": rig.clock}} for i in range(7)]
    rig.real.persons.replace(
        {**old.record, "memberships": [*old.record["memberships"], *extra]}, expected_version=old.version
    )
    rig.as_user(SAM)
    rig.email = "sam@example.com"
    assert rig.post("/v1/team-invite-links/accept", {"token": made["token"]}).json() == {"detail": "membership_limit"}
    assert rig.stores.persons._invite_links.get(ORG, made["invite_id"]).record["status"] == "pending"


def test_SELF_SERVE_TEAMS_INVITE_LINK_failure_after_the_claim_undoes_the_entry_and_leaves_the_link_used(
    people_rig,
    monkeypatch,
):
    rig = _rig(people_rig, monkeypatch)
    made = _make(rig).json()
    rig.as_user(SAM)
    rig.email = "sam@example.com"
    original = rig.events.append

    def fail_accept(world, part):
        if part["type"] == "invite_link.accepted":
            raise RuntimeError("offline")
        return original(world, part)

    monkeypatch.setattr(rig.events, "append", fail_accept)
    assert rig.post("/v1/team-invite-links/accept", {"token": made["token"]}).status_code == 503
    assert all(m["team"] != TEAM for m in rig.stored("persons", SAM)["memberships"])
    assert rig.stores.persons._invite_links.get(ORG, made["invite_id"]).record["status"] == "redeemed"


def test_SELF_SERVE_TEAMS_INVITE_LINK_revoke_answers_done_and_writes_only_when_granted(people_rig, monkeypatch):
    rig = _rig(people_rig, monkeypatch)
    made = _make(rig).json()
    path = f"/v1/teams/{TEAM}/invite-links/{made['invite_id']}/revoke"
    rig.as_user(SAM)
    assert rig.post(path, {}).status_code == 403
    rig.as_user(OWNER)
    assert rig.post(path, {}).json() == {"status": "done"}
    assert rig.post(path, {}).json() == {"status": "done"}
    assert rig.stores.persons._invite_links.get(ORG, made["invite_id"]).record["status"] == "revoked"
    assert rig.post(f"/v1/teams/{TEAM}/invite-links/til_{'a' * 24}/revoke", {}).json() == {"status": "done"}
    rows = rig.client.get(f"/v1/teams/{TEAM}/invite-links").json()
    assert rows == [
        {"id": made["invite_id"], "created_at": rig.clock, "expires_at": made["expires_at"], "state": "withdrawn"}
    ]


def test_SELF_SERVE_TEAMS_INVITE_LINK_no_get_route_takes_a_token(people_rig, monkeypatch):
    rig = _rig(people_rig, monkeypatch)
    token = _make(rig).json()["token"]
    rig.as_user(SAM)
    assert rig.client.get("/v1/team-invite-links/accept", params={"token": token}).status_code in (404, 405)


def test_SELF_SERVE_TEAMS_INVITE_LINK_concurrent_redeemers_have_exactly_one_winner(people_rig, monkeypatch):
    rig = _rig(people_rig, monkeypatch)
    made = _make(rig).json()
    rig.as_user(SAM)
    rig.email = "sam@example.com"
    store = rig.stores.persons._invite_links
    original = store.replace
    barrier = Barrier(2)

    def racing(record, version):
        if record["status"] == "redeemed":
            barrier.wait(timeout=5)
        return original(record, version)

    monkeypatch.setattr(store, "replace", racing)
    with ThreadPoolExecutor(max_workers=2) as pool:
        responses = list(
            pool.map(lambda _: rig.post("/v1/team-invite-links/accept", {"token": made["token"]}), range(2))
        )
    assert sorted(r.status_code for r in responses) == [200, 404]
    assert sum(m["team"] == TEAM for m in rig.stored("persons", SAM)["memberships"]) == 1


def test_SELF_SERVE_TEAMS_INVITE_LINK_events_are_registered_ids_only_in_the_actors_desk_world(people_rig, monkeypatch):
    rig = _rig(people_rig, monkeypatch)
    made = _make(rig).json()
    rig.as_user(SAM)
    rig.email = "sam@example.com"
    assert rig.post("/v1/team-invite-links/accept", {"token": made["token"]}).status_code == 200
    for call in rig.events.calls:
        part = call.part
        assert part["actor"] == part["target"]
        assert call.world_id == "w_desk_" + part["actor"][2:]
        assert part["vis"] == [] and part["authz"] is None
        assert conforms(f"events/data/{part['type']}.schema.json", part["data"])
        assert made["token"] not in str(part)


def test_SELF_SERVE_TEAMS_INVITE_LINK_event_failures_fail_closed_and_revoke_retry_writes_once(people_rig, monkeypatch):
    rig = _rig(people_rig, monkeypatch)
    original = rig.events.append

    def fail_create(world, part):
        if part["type"] == "invite_link.created":
            raise RuntimeError("offline")
        return original(world, part)

    monkeypatch.setattr(rig.events, "append", fail_create)
    assert _make(rig).status_code == 503
    assert rig.stores.persons._invite_links.list(ORG) == ()
    monkeypatch.setattr(rig.events, "append", original)
    made = _make(rig).json()
    attempts = 0

    def fail_once(world, part):
        nonlocal attempts
        if part["type"] == "invite_link.revoked" and attempts == 0:
            attempts += 1
            raise RuntimeError("offline")
        return original(world, part)

    monkeypatch.setattr(rig.events, "append", fail_once)
    path = f"/v1/teams/{TEAM}/invite-links/{made['invite_id']}/revoke"
    assert rig.post(path, {}).status_code == 503
    assert rig.stores.persons._invite_links.get(ORG, made["invite_id"]).record["status"] == "revoked"
    assert rig.post(path, {}).json() == {"status": "done"}
    assert [call.part["type"] for call in rig.events.calls].count("invite_link.revoked") == 1


def test_SELF_SERVE_TEAMS_INVITE_LINK_an_entry_accepted_through_an_owners_link_may_be_left(people_rig, monkeypatch):
    rig = _rig(people_rig, monkeypatch)
    token = _make(rig).json()["token"]
    rig.as_user(SAM)
    rig.email = "sam@example.com"
    assert rig.post("/v1/team-invite-links/accept", {"token": token}).status_code == 200
    assert rig.post(f"/v1/teams/{TEAM}/members/{SAM}/remove", {}).status_code == 200
    assert all(m["team"] != TEAM for m in rig.stored("persons", SAM)["memberships"])
