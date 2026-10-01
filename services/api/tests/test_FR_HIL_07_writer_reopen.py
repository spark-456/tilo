"""FR-HIL-07, issue #55 item 2: after a failed append the dispatcher reopens the writer (if it has a
`reopen` hook) before the same event id is sent again, so a stale lease or an ambiguous commit
recovers instead of answering WriterBusy for ever. The kill switch's level change never waits on it.
"""

from __future__ import annotations

from _api_lib import OWNER, WORLD, FakeEventWriter, as_principal, as_writer, base_policy, make_principal, make_world


class _BusyUntilReopened(FakeEventWriter):
    """Refuses every append until `reopen()` has been called, like a stale harness WorldWriter."""

    def __init__(self, store) -> None:
        super().__init__(store)
        self.reopened = 0
        self.attempts = 0

    def append(self, world_id: str, part: dict) -> dict:
        self.attempts += 1
        if not self.reopened:
            raise RuntimeError("WriterBusy: head has moved (test double)")
        return super().append(world_id, part)

    def reopen(self) -> None:
        self.reopened += 1


def test_FR_HIL_07_dispatcher_reopens_the_writer_after_a_failed_append_then_resends(client, store):
    store.worlds[WORLD] = make_world(owner=OWNER)
    store.policies["pol_r"] = base_policy(id_="pol_r", owner=OWNER, level="L2", action_type="send_email")
    store.policy_worlds["pol_r"] = WORLD
    writer = _BusyUntilReopened(store)
    as_writer(writer)
    as_principal(make_principal(user_id=OWNER, role="owner", world_id=WORLD))

    resp = client.post(f"/worlds/{WORLD}/autopilot/stop")

    assert resp.status_code == 200, resp.text
    assert resp.json()["pending"] == 0
    assert writer.reopened == 1
    assert writer.attempts == 2
    assert store.policies["pol_r"]["level"] == "L1"
    committed = [e for e in store.events[WORLD] if e["data"].get("policy_id") == "pol_r"]
    assert len(committed) == 1
