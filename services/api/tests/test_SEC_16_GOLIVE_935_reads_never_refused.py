"""SEC-16 / GOLIVE-935 (SEC-REVIEW-15 B1): with a real ledger a capped uid or a tripped switch is refused NEW work only.

API_SEC_16.md: "Reads are never refused", and NFR-24: finished work can still be replayed. The artifact store getter
(`deps.get_artifact_store`) sat behind `get_work_mode`, the refusing mode, so every read and delete route that only
needs the store (a quiz app view, the minutes, the quotes, a meeting delete, the join read) answered 403
`spend_cap_reached` for a uid at its cap and 503 replay-only for everybody once the day switch tripped. FR-MTG-10's
owner could not delete their own meeting at the cap.

These tests run the REAL `deps.get_artifact_store` (only the store it opens is the rig's in-memory one), on the
deployed-style people rig with the real gate, a real in-memory ledger and `TILO_JUDGE_LIVE=1`, so a uid is "live"
until it is capped. Each read or delete route class is asserted in three states: open (the control, so a failure is
the refusal and not the setup), capped and tripped. New work (`POST /intake`, a meeting host or attend) must still
be refused in the last two.

No network, no paid call, no secret.
"""

from __future__ import annotations

import pytest
from _clint1_lib import seam
from _ppl11a_lib import OWNER, PRIYA, fixture_case
from _ppl11c_lib import confirmed_item, holds_artifact, proposed_launch_note
from _sec16_lib import make_caps, make_ledger, spend

STATES = ("open", "capped", "tripped")
NEW_WORK_STATES = ("capped", "tripped")
TRANSCRIPT, MINUTES = "art_transcript_q4_plan", "art_minutes_q4_plan"


def spend_refusal(response) -> str | None:
    """ "cap" for the per-uid refusal (403 `spend_cap_reached`), "switch" for NFR-24's 503 replay-only, else None."""
    try:
        body = response.json()
    except ValueError:
        return None
    if not isinstance(body, dict):
        return None
    if response.status_code == 403 and body.get("code") == "spend_cap_reached":
        return "cap"
    if response.status_code == 503 and body.get("replay_only") is True:
        return "switch"
    return None


def wire_state(rig, monkeypatch, state: str):
    """The real getter over the rig's store, a real in-memory ledger, and `state` applied to it."""
    from tilo_api import deps, run_stores  # noqa: PLC0415
    from tilo_api.spend import RateLimiter  # noqa: PLC0415

    monkeypatch.setenv("TILO_JUDGE_LIVE", "1")  # after the rig cleared it: a deployed judge is live until capped
    caps = make_caps(rate_limit_requests=10_000)
    ledger = make_ledger(caps)
    overrides = rig.app.dependency_overrides
    overrides[seam(deps, "get_spend_caps")] = lambda: caps
    overrides[seam(deps, "get_spend_cap_ledger")] = lambda: ledger
    limiter = RateLimiter(limit=caps.rate_limit_requests, window_s=caps.rate_limit_window_s)
    overrides[seam(deps, "get_rate_limiter")] = lambda: limiter
    rig.unwire("artifact_store")  # the production getter, with its `Depends(...)` mode, is what is under test
    monkeypatch.setattr(run_stores, "open_artifact_store", lambda *args, **kwargs: rig.artifacts)
    deps.get_artifact_store.cache_clear()
    apply_state(ledger, caps, state)
    return ledger, caps


def apply_state(ledger, caps, state: str) -> None:
    """ "capped": every uid used is at its lifetime cap. "tripped": the durable day switch is set. "open": neither."""
    if state == "capped":
        for uid in (OWNER, PRIYA):
            spend(ledger, uid, caps.uid_lifetime_minor, run_id=f"r_prefill_{uid}")
    elif state == "tripped":
        ledger.trip_replay_only("test: global hard cap")


@pytest.fixture()
def meeting_world(people_rig, monkeypatch):
    """`make(state)` -> the rig: u_owner's minuted meeting `mt_q4_plan` with its transcript and minutes, a confirmed
    item for u_priya and a proposed one, both people declared judges, the ledger in `state`."""
    from tilo_api import deps  # noqa: PLC0415

    def make(state: str):
        rig = people_rig(deployed=True)
        rig.seed_quote_case(fixture_case("transcript", "valid", "owner_reads_quotes"))
        rig.add("work_items", confirmed_item())
        rig.add("work_items", proposed_launch_note())
        rig.as_user(OWNER)
        wire_state(rig, monkeypatch, state)
        # ACT-1b: a deployed delete drains follow-up drafts through the API store door (its own tests cover it and its
        # 503); this rig has no Firestore, so the drain is recorded and the cap/switch question stays the test's.
        from tilo_api.meeting_draft_cleanup import get_meeting_draft_cleanup  # noqa: PLC0415

        rig.drained = []
        rig.app.dependency_overrides[get_meeting_draft_cleanup] = lambda: lambda owner, mid: rig.drained.append(mid)
        return rig

    yield make
    deps.get_artifact_store.cache_clear()


# --- reads --------------------------------------------------------------------------------------------------------


@pytest.mark.parametrize("state", STATES)
def test_SEC_16_GOLIVE_935_B1_the_minutes_and_quote_reads_are_never_refused_for_a_cap_or_the_switch(
    meeting_world, state
):
    rig = meeting_world(state)

    minutes = rig.get("/v1/meetings/mt_q4_plan/minutes")
    quotes = rig.get("/v1/meetings/mt_q4_plan/quotes", params={"ids": "u0021,u0023"})
    rig.as_user(PRIYA)
    item_quote = rig.get("/v1/work-items/wi_rate_sheet/quote")

    for name, response in (("minutes", minutes), ("quotes", quotes), ("item quote", item_quote)):
        assert spend_refusal(response) is None, f"{name} in state {state}: {response.status_code} {response.text[:200]}"
        assert response.status_code == 200, f"{name} in state {state}: {response.status_code} {response.text[:200]}"


@pytest.mark.parametrize("state", STATES)
def test_SEC_16_GOLIVE_935_B1_the_join_read_is_never_refused_for_a_cap_or_the_switch(meeting_world, state):
    from tilo_api import deps  # noqa: PLC0415

    rig = meeting_world(state)
    overrides = rig.app.dependency_overrides  # the seams the join read needs before the store, so it gets that far
    overrides[deps.get_store] = lambda: rig.event_store
    overrides[seam(deps, "get_meeting_host_client")] = lambda: object()

    response = rig.get("/v1/meetings/mt_q4_plan/join")

    assert spend_refusal(response) is None, f"join in state {state}: {response.status_code} {response.text[:200]}"


def test_SEC_16_GOLIVE_935_B1_the_artifact_store_getter_takes_the_non_refusing_mode():
    """Every read and delete route that only needs the store inherits its mode: it must be `get_mode`, the one that
    never raises for a cap or the switch. A route that starts new work takes `get_work_mode` itself (attend, host)."""
    import typing  # noqa: PLC0415

    from tilo_api import deps  # noqa: PLC0415

    hint = typing.get_type_hints(deps.get_artifact_store, include_extras=True)["mode"]
    taken = [m.dependency for m in hint.__metadata__ if hasattr(m, "dependency")]
    assert taken == [deps.get_mode], "get_artifact_store must not depend on the refusing get_work_mode"


# --- delete -------------------------------------------------------------------------------------------------------


@pytest.mark.parametrize("state", STATES)
def test_SEC_16_GOLIVE_935_B1_the_owner_can_delete_their_meeting_at_the_cap_or_with_the_switch_tripped(
    meeting_world, state
):
    """FR-MTG-10: deleting is the owner's right and costs nothing; the cap and the switch only stop new live work."""
    rig = meeting_world(state)
    assert holds_artifact(rig, TRANSCRIPT) and holds_artifact(rig, MINUTES)

    response = rig.post("/v1/meetings/mt_q4_plan/delete")

    assert spend_refusal(response) is None, f"delete in state {state}: {response.status_code} {response.text[:200]}"
    assert response.status_code == 200, response.text[:300]
    assert response.json() == {"id": "mt_q4_plan", "status": "deleted"}
    assert not holds_artifact(rig, TRANSCRIPT) and not holds_artifact(rig, MINUTES)


# --- the apps view ------------------------------------------------------------------------------------------------


@pytest.mark.parametrize("state", NEW_WORK_STATES)
def test_SEC_16_GOLIVE_935_B1_a_quiz_apps_view_is_never_refused_for_a_cap_or_the_switch(people_rig, monkeypatch, state):
    """The route's own answer with the uid under its cap is the baseline (200 where the sources validate); capped or
    with the switch tripped the same request gets the same status and body, never a spend refusal."""
    from test_LW_complete_quiz_owner import WORLD, make_case  # noqa: PLC0415
    from tilo_api import deps, run_stores  # noqa: PLC0415

    rig = people_rig(deployed=True)
    case_app, world_state, writer, quiz, _source, _spec = make_case()
    artifacts = case_app.dependency_overrides[deps.get_artifact_store]()
    try:
        ledger, caps = wire_state(rig, monkeypatch, "open")
        monkeypatch.setattr(run_stores, "open_artifact_store", lambda *args, **kwargs: artifacts)
        rig.app.dependency_overrides[deps.get_store] = lambda: world_state
        rig.app.dependency_overrides[deps.get_event_writer] = lambda: writer
        deps.get_artifact_store.cache_clear()
        rig.as_user(OWNER)
        url = f"/worlds/{WORLD}/apps/{quiz.artifact_id}"

        baseline = rig.get(url)
        assert spend_refusal(baseline) is None, f"{baseline.status_code} {baseline.text[:200]}"
        apply_state(ledger, caps, state)
        response = rig.get(url)

        assert spend_refusal(response) is None, f"apps in state {state}: {response.status_code} {response.text[:200]}"
        assert (response.status_code, response.json()) == (baseline.status_code, baseline.json())
    finally:
        writer.reopen()
        deps.get_artifact_store.cache_clear()


# --- new work is still refused ------------------------------------------------------------------------------------


@pytest.mark.parametrize("state", NEW_WORK_STATES)
def test_SEC_16_GOLIVE_935_B1_new_work_is_still_refused_with_the_same_state(meeting_world, state):
    """The control for the three tests above: in the very same state, `POST /intake` and the meeting routes that
    start live work (host, attend) are refused, 403 `spend_cap_reached` for the cap and 503 replay-only for the
    switch. Reads are not refused; new work is."""
    rig = meeting_world(state)
    want = "cap" if state == "capped" else "switch"

    intake = rig.client.post("/intake", data={"text": "Prepare the weekly supplier summary."})
    host = rig.post("/v1/meetings/mt_q4_plan/host")
    attend = rig.post("/v1/meetings/mt_q4_plan/attend")

    for name, response in (("intake", intake), ("host", host), ("attend", attend)):
        assert spend_refusal(response) == want, f"{name} in state {state}: {response.status_code} {response.text[:200]}"
