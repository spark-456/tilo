"""FR-TEAM-02 / FR-TEAM-04, security review of PR #642 (round 1): session scope, bounds and store errors.

* B3: the team routes are admin routes. Every write, and the read (it carries invite emails), needs a full web or
  mobile_web sign-in session (`Principal.full_session`, set only by the server, BQ-XWORLD-10); a stored Owner on any
  other session is refused with 403, the store unchanged and no audit line.
* A personal limit is bounded; pending invites are capped and deduplicated by normalised email.
* A store whose document is missing a field is a 503, never the non-member 404.
"""

from __future__ import annotations

import logging

import pytest
from _team_routes_lib import MEMBER, NOT_FOUND, OWNER, ROLES, state, team_api

WRITES = [
    ("put", f"/v1/team/members/{MEMBER}/role", {"role": "Viewer"}),
    ("put", f"/v1/team/members/{MEMBER}/limit", {"limit_minor": 1}),
    ("delete", f"/v1/team/members/{MEMBER}", None),
    ("post", "/v1/team/invites", {"email": "new@b.co", "role": "Member"}),
    ("put", "/v1/team/switches/weekend", {"on": True}),
    ("put", "/v1/team/tools/gmail", {"level": "read"}),
]


def _call(api, verb: str, path: str, body):  # type: ignore[no-untyped-def]
    return api.delete(path) if verb == "delete" else getattr(api, verb)(path, body)


@pytest.mark.parametrize(("full_session", "channel"), [(False, "web"), (True, "email"), (False, "email")])
@pytest.mark.parametrize(("verb", "path", "body"), WRITES, ids=[w[1] for w in WRITES])
def test_FR_TEAM_02_an_owner_on_a_narrow_session_cannot_write(
    full_session: bool, channel: str, verb: str, path: str, body: object, caplog: pytest.LogCaptureFixture
) -> None:
    with team_api() as api, caplog.at_level(logging.INFO):
        before = api.store.read()
        api.full_session, api.channel = full_session, channel
        assert _call(api, verb, path, body).status_code == 403
        assert api.store.read() == before
    assert not [r for r in caplog.records if "team_rule_changed" in r.getMessage()]


@pytest.mark.parametrize(("full_session", "channel"), [(False, "web"), (True, "email")])
def test_FR_TEAM_02_the_team_read_needs_a_full_web_session_too(full_session: bool, channel: str) -> None:
    with team_api() as api:
        api.full_session, api.channel = full_session, channel
        response = api.get()
        assert response.status_code == 403
        assert "@" not in response.text


def test_FR_TEAM_02_a_full_mobile_web_session_may_write() -> None:
    with team_api() as api:
        api.channel = "mobile_web"
        assert api.put("/v1/team/switches/weekend", {"on": True}).status_code == 200


def test_FR_TEAM_02_a_personal_limit_is_bounded() -> None:
    with team_api() as api:
        path = f"/v1/team/members/{MEMBER}/limit"
        assert api.put(path, {"limit_minor": 10**12}).status_code == 200
        for bad in (10**12 + 1, 10**30, -1):
            assert api.put(path, {"limit_minor": bad}).status_code == 422
        assert api.store.read().limits[MEMBER] == 10**12


def test_FR_TEAM_02_invites_are_capped_and_deduplicated_by_email() -> None:
    with team_api() as api:
        assert api.post("/v1/team/invites", {"email": "Ann@B.co", "role": "Member"}).status_code == 201
        assert api.post("/v1/team/invites", {"email": "ann@b.co", "role": "Viewer"}).status_code == 409
        for n in range(99):
            if (n + 2) % 50 == 0:
                api.advance_clock(61)
            assert api.post("/v1/team/invites", {"email": f"p{n}@b.co", "role": "Member"}).status_code == 201
        assert len(api.store.read().invites) == 100
        assert api.post("/v1/team/invites", {"email": "late@b.co", "role": "Member"}).status_code == 409
        assert len(api.store.read().invites) == 100


def test_FR_TEAM_02_a_store_missing_a_field_is_a_503_not_the_member_404() -> None:
    from tilo_api.team_store import InMemoryTeamStore

    class Missing(InMemoryTeamStore):
        def read(self):  # type: ignore[no-untyped-def]
            raise KeyError("roles")

    with team_api(store=Missing(state())) as api:
        assert api.get().status_code == 503
        response = api.put(f"/v1/team/members/{MEMBER}/role", {"role": "Viewer"})
        assert response.status_code == 503 and response.json() != NOT_FOUND
    with team_api() as api:  # a real non-member still gets the one 404
        assert api.as_("u_x").get().json() == NOT_FOUND
        assert api.as_(OWNER).get().status_code == 200 and api.store.read().roles == ROLES


def test_FR_TEAM_02_SEC_10_team_writes_have_write_limit() -> None:
    """Team write endpoints are bounded by write_limit (60 writes/min per principal, SEC-10)."""
    from tilo_api.people_limits import WRITES_PER_MINUTE  # noqa: PLC0415

    with team_api() as api:
        for n in range(WRITES_PER_MINUTE):
            assert api.put("/v1/team/switches/weekend", {"on": True}).status_code == 200, n
        over = api.put("/v1/team/switches/weekend", {"on": True})
        assert over.status_code == 429 and over.json().get("code") == "rate_limited", over.text
        assert 1 <= int(over.headers["retry-after"]) <= 60
