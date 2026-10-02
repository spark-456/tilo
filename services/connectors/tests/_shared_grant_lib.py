"""A Google double that models the shared grant (FR-CON-02, FR-CON-03; CON-D10).

Every Google connector uses one OAuth client and `include_granted_scopes=true`, so Google keeps ONE grant
per account and client: revoking any token of it ends the grant for every connector. `_oauth_lib.FakeGoogle`
revokes only the token it was sent; `SharedGrantGoogle` ends all of them, so a test sees what a premature
revoke costs. The fake models one account (every token it issued belongs to it). No production code here.
"""

from __future__ import annotations

from _oauth_lib import Env, FakeGoogle, FakeResponse, make_env


class SharedGrantGoogle(FakeGoogle):
    """A revoke that Google accepts ends every live refresh token of the client, not only the one sent."""

    def _revoke(self, d: dict[str, str]) -> FakeResponse:
        response = super()._revoke(d)
        if response.status_code == 200:
            with self._lock:
                self.live_refresh.clear()
        return response

    def grant_alive(self) -> bool:
        with self._lock:
            return bool(self.live_refresh)


def make_shared_env(**kwargs) -> Env:
    """`make_env()` whose Google double shares one grant per client. The class swap keeps the instance the
    broker and the consent service already hold, with its client id and secret."""
    env = make_env(**kwargs)
    env.google.__class__ = SharedGrantGoogle
    return env
