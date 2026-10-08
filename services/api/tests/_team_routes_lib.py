"""Helpers for the TEAM-ROUTES acceptance tests (FR-TEAM-02, FR-TEAM-04, FR-ACC-01; issues #621, #629).

Nothing here is business logic: a TestClient over the real app with the team store seam, the principal and the flag
store overridden, and a team snapshot in the shape the store keeps. Every principal's SESSION role is "owner" on
purpose: the routes must take the team role from the stored roles map, never from the session.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

OWNER, OWNER_2, APPROVER, MEMBER, VIEWER, STRANGER = "u_owner", "u_owner_2", "u_appr", "u_member", "u_viewer", "u_x"
ROLES = {OWNER: "Owner", APPROVER: "Approver", MEMBER: "Member", VIEWER: "Viewer"}
NOT_FOUND = {"detail": "No such team."}


class Flags:
    def __init__(self, *on: str) -> None:
        self.on = set(on)

    def get(self, name: str) -> bool:
        return name in self.on


def state(**overrides: Any) -> Any:
    from tilo_api.team_store import TeamState  # noqa: PLC0415

    base: dict[str, Any] = {"roles": dict(ROLES), "limits": {APPROVER: 100_000}, "worlds": {"w_1": MEMBER}}
    return TeamState(**{**base, **overrides})


class TeamApi:
    def __init__(self, client: Any, store: Any, flags: Flags) -> None:
        self.client, self.store, self.flags = client, store, flags
        self.user = OWNER
        self.full_session, self.channel = True, "web"  # a full web sign-in (BQ-XWORLD-10); tests narrow it

    def as_(self, user: str) -> TeamApi:
        self.user = user
        return self

    def get(self, path: str = "/v1/team") -> Any:
        return self.client.get(path)

    def put(self, path: str, body: Any, **kw: Any) -> Any:
        return self.client.put(path, json=body, **kw)

    def post(self, path: str, body: Any, **kw: Any) -> Any:
        return self.client.post(path, json=body, **kw)

    def delete(self, path: str) -> Any:
        return self.client.delete(path)


@contextmanager
def team_api(snapshot: Any = None, *, store: Any = None) -> Iterator[TeamApi]:
    from fastapi.testclient import TestClient  # noqa: PLC0415
    from tilo_api import app, deps  # noqa: PLC0415
    from tilo_api.team_store import InMemoryTeamStore, get_team_store  # noqa: PLC0415

    team = store if store is not None else InMemoryTeamStore(snapshot if snapshot is not None else state())
    flags = Flags()
    saved = dict(app.dependency_overrides)
    api = TeamApi(None, team, flags)
    app.dependency_overrides[deps.get_current_principal] = lambda: deps.Principal(
        user_id=api.user,
        role="owner",
        channel=api.channel,
        full_session=api.full_session,  # type: ignore[arg-type]
    )
    app.dependency_overrides[get_team_store] = lambda: team
    app.dependency_overrides[deps.get_flag_store] = lambda: flags
    app.dependency_overrides[deps.get_clock] = lambda: lambda: "2026-10-08T10:00:00.000Z"
    try:
        api.client = TestClient(app)
        yield api
    finally:
        app.dependency_overrides.clear()
        app.dependency_overrides.update(saved)
