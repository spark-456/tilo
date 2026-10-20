"""MINUTES-SCREEN (20 Oct, tilo-api-00098): every live "Analyze minutes" answered 409 `transcript_unavailable`.

The bot's transcript was stored through the shared artifact store, whose screen has no request meter and so, deployed,
reads recordings: a miss, the record `unscreened`, and the analysis needs `clean`. The analysis' own screen and the
minutes artifact took the same replay path. Fixed without relaxing any check: the attend request screens the transcript
with its own metered live screen (as a run screens its outputs); the owner's minutes request screens with a live
screen it holds per call (`deps.safety_for_mode`, as `router_for_mode`), for the transcript, the analysis and the
minutes it stores; and a transcript stored `unscreened` is screened once more as the next version of the same
artifact, opening only on a real `clean` verdict. Offline doubles only; `K_SERVICE` makes the deployed rules apply.
"""

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from _mtg09b_lib import MEETING, ORG, OWNER, SAM, WORLD, HostRig, block_network
from _ppl11a_lib import OWNER as Q4_OWNER
from _sec16_lib import make_caps, make_ledger
from starlette.requests import Request
from test_FR_MTG_03_analysis_publication import integration  # noqa: F401
from tilo_api import deps, spend, team_access
from tilo_api.assistant.metering import InMemorySpendLedger
from tilo_api.meeting_bot import BotCapture
from tilo_api.people_writes import Refusal
from tilo_contracts import Transcript
from tilo_memory.artifacts import NewVersion, Origin, Scope
from tilo_metering.flags import InMemoryFlagStore

LINK = "https://meet.google.com/abc-defg-hij"


class NoVerdict:
    """What a deployed screen with no meter does: it reads recordings and misses."""

    def check(self, *args, **kwargs):
        raise RuntimeError("replay miss")


class Screen:
    def __init__(self, flagged: bool = False) -> None:
        self.flagged, self.down, self.texts = flagged, False, []

    def check(self, text, *args, **kwargs):
        if self.down:
            raise RuntimeError("no verdict")
        self.texts.append(text)
        return {"flagged": self.flagged, "reason": None}


# --- attend: the transcript is screened by the request's own metered live screen ---------------------------------


@pytest.fixture
def attend_rig(people_rig, monkeypatch):
    block_network(monkeypatch)
    h = HostRig(people_rig())
    h.rig.as_user(OWNER)
    h.art.store = h.art.store.with_screener(NoVerdict())  # the shared store, deployed
    capture = BotCapture(
        Transcript(
            v="1.0",
            meeting_id=MEETING,
            utterances=[{"id": "u0001", "speaker": "Someone", "t_ms": 900, "text": "Ship it on Friday."}],
        ),
        "left_on_request",
    )
    bot = SimpleNamespace(attend=AsyncMock(return_value=capture))
    from tilo_api.meeting_bot_rpc import get_meeting_bot_client

    h.rig.app.dependency_overrides[get_meeting_bot_client] = lambda: bot
    return h


def transcript_record(h, ref):
    return h.art.store.head(Scope(ORG, WORLD, OWNER), ref).record


def test_MINUTES_SCREEN_attend_screens_the_transcript_live_with_the_requests_meter(attend_rig, monkeypatch):
    h = attend_rig
    meter, screen, seen = object(), Screen(), []
    h.rig.app.dependency_overrides[deps.get_work_mode] = lambda: "live"
    monkeypatch.setattr(deps, "meter_for", lambda request, mode, switches, **kw: meter if mode == "live" else None)
    monkeypatch.setattr(deps, "get_safety", lambda mode=None, *a, meter=None, **k: seen.append((mode, meter)) or screen)
    response = h.rig.client.post(f"/v1/meetings/{MEETING}/attend", json={"join_url": LINK})
    assert response.status_code == 200, response.text
    record = transcript_record(h, response.json()["transcript"])
    assert record["screening"] == "clean" and record["screened_at"] is not None
    assert seen == [("live", meter)] and "Ship it on Friday." in screen.texts[0]


def test_MINUTES_SCREEN_attend_in_replay_never_builds_a_live_screen(attend_rig, monkeypatch):
    h = attend_rig
    h.rig.app.dependency_overrides[deps.get_work_mode] = lambda: "replay"
    monkeypatch.setattr(deps, "meter_for", lambda *a, **k: None)
    monkeypatch.setattr(deps, "get_safety", lambda *a, **k: pytest.fail("no live screen in replay"))
    response = h.rig.client.post(f"/v1/meetings/{MEETING}/attend", json={"join_url": LINK})
    assert response.status_code == 200, response.text
    assert transcript_record(h, response.json()["transcript"])["screening"] == "unscreened"


# --- the owner's minutes request: a live screen held per call, deployed ----------------------------------------------


@pytest.fixture
def minutes(integration, monkeypatch):  # noqa: F811
    rig, writer, scope, router = integration
    stored = rig.real.meetings.get(rig.org, "mt_q4_plan")
    rig.real.meetings.replace(
        {**stored.record, "scheduled": {"start": "2026-10-05T23:30:00.000Z", "end": "2026-10-06T00:30:00.000Z"}},
        expected_version=stored.version,
    )
    caps = make_caps()
    ledger = make_ledger(caps)
    flags = InMemoryFlagStore()
    request = Request(
        {"type": "http", "app": SimpleNamespace(dependency_overrides={deps.get_spend_caps: lambda: caps})}
    )
    request.state.uid = Q4_OWNER
    request.state.declaration = "owner"
    monkeypatch.setenv("K_SERVICE", "tilo-api")
    monkeypatch.setattr(deps, "get_work_mode", lambda request, switches: "live")
    monkeypatch.setattr(team_access, "user_cap_minor", lambda *args: caps.uid_lifetime_minor)
    monkeypatch.setattr(deps, "router_for_mode", lambda mode: router)
    built, screen = [], Screen()

    def provider(config, *, fixtures_dir, force_replay=False):
        built.append(force_replay)
        return NoVerdict() if force_replay else screen

    monkeypatch.setattr(deps, "build_safety_provider", provider)
    shared = rig.artifacts.with_screener(NoVerdict())  # the shared store, deployed: no verdict
    return SimpleNamespace(
        rig=rig, writer=writer, scope=scope, router=router, caps=caps, ledger=ledger, flags=flags, request=request,
        switches=spend.Switches(flags, ledger), built=built, screen=screen, shared=shared,
    )  # fmt: skip


def analyze(c):
    from tilo_api.meeting_analysis_mode import analyze_owner_minutes

    return analyze_owner_minutes(
        c.request,
        c.writer,
        c.rig.event_store,
        c.shared,
        "mt_q4_plan",
        principal=deps.Principal(c.writer.actor, "owner"),
        switches=c.switches,
        budget=2,
        events=c.rig.events,
        allowance=InMemorySpendLedger(),
        allowance_cap=100,
    )


def meeting(c):
    return c.rig.real.meetings.get(c.rig.org, "mt_q4_plan").record


def head(c, ref):
    return c.shared.head(c.scope, ref).record


def test_MINUTES_SCREEN_deployed_minutes_are_screened_live_and_published_clean(minutes):
    c = minutes
    result = analyze(c)
    assert result["status"] == "minuted" and result["minutes_confirmed_by"] is None
    assert c.built and not any(c.built)  # never the recordings
    assert head(c, result["minutes"])["screening"] == "clean"
    assert len(c.screen.texts) == 2  # the transcript for the analysis, then the minutes it stores
    assert c.ledger.spent_minor(Q4_OWNER) == 3 * c.caps.unit_reserve_minor  # two screens and the analysis


def unscreened_transcript(c):
    """A transcript as the bot path stored it before this fix: the same bytes, `unscreened`."""
    before = meeting(c)
    data = c.shared.read(c.scope, before["transcript"])
    c.rig._ids = ["art_unscreened_transcript", "art_minutes_after_rescreen"]
    made = c.shared.put(c.scope, NewVersion("application/json", data, "r_meeting_q4_plan_1", Origin(kind="upload")))
    assert made.record["screening"] == "unscreened"
    stored = c.rig.real.meetings.get(c.rig.org, "mt_q4_plan")
    c.rig.real.meetings.replace({**stored.record, "transcript": made.ref}, expected_version=stored.version)
    return made.ref, data


def test_MINUTES_SCREEN_an_unscreened_transcript_is_screened_again_as_its_next_version(minutes):
    c = minutes
    ref, data = unscreened_transcript(c)
    result = analyze(c)
    moved = result["transcript"]
    assert moved == {"artifact_id": ref["artifact_id"], "version": 2}
    record = head(c, moved)
    assert record["screening"] == "clean" and record["parents"] == [ref]
    assert c.shared.read(c.scope, moved) == data and head(c, ref)["screening"] == "unscreened"
    assert (
        result["status"] == "minuted" and json.loads(c.shared.read(c.scope, result["minutes"]))["transcript"] == moved
    )


def test_MINUTES_SCREEN_a_flagged_transcript_never_becomes_minutes(minutes):
    c = minutes
    ref, _ = unscreened_transcript(c)
    c.screen.flagged = True
    with pytest.raises(Refusal) as refused:
        analyze(c)
    assert (refused.value.status_code, refused.value.detail) == (409, "transcript_unavailable")
    after = meeting(c)
    assert after["minutes"] is None and after["status"] == "ended"
    assert head(c, after["transcript"])["screening"] == "flagged"  # the record says what the screen found
    assert not c.router.calls


def test_MINUTES_SCREEN_no_verdict_again_leaves_the_meeting_refused_and_retryable(minutes):
    c = minutes
    ref, _ = unscreened_transcript(c)
    c.screen.down = True
    with pytest.raises(Refusal) as refused:
        analyze(c)
    assert refused.value.detail == "transcript_unavailable" and meeting(c)["minutes"] is None
    assert head(c, meeting(c)["transcript"])["screening"] == "unscreened" and not c.router.calls
    c.screen.down = False  # the screen answers again: the next request screens version 3 and opens it
    c.rig._ids = ["art_minutes_on_retry"]
    result = analyze(c)
    assert result["status"] == "minuted" and result["transcript"] == {"artifact_id": ref["artifact_id"], "version": 3}


def test_MINUTES_SCREEN_replay_never_screens_again_or_writes(minutes, monkeypatch):
    c = minutes
    ref, _ = unscreened_transcript(c)
    monkeypatch.setattr(deps, "get_work_mode", lambda request, switches: "replay")
    before = c.rig.snapshot()
    with pytest.raises(Refusal) as refused:
        analyze(c)
    assert refused.value.detail == "transcript_unavailable"
    assert meeting(c)["transcript"] == ref and c.rig.snapshot() == before
    assert c.ledger.spent_minor(Q4_OWNER) == 0


def test_MINUTES_SCREEN_safety_for_mode_is_live_only_for_live(monkeypatch):
    seen = []
    monkeypatch.setattr(deps, "build_safety_provider", lambda *a, force_replay=False, **k: seen.append(force_replay))
    monkeypatch.setenv("K_SERVICE", "tilo-api")
    deps.safety_for_mode("live")
    deps.safety_for_mode("replay")
    assert seen == [False, True]


def test_MINUTES_SCREEN_the_owner_reads_the_transcript_lines_after_the_call(attend_rig, monkeypatch):
    h = attend_rig
    path = f"/v1/meetings/{MEETING}/transcript"
    assert h.rig.client.get(path).status_code == 404  # nothing captured yet
    h.rig.app.dependency_overrides[deps.get_work_mode] = lambda: "replay"
    monkeypatch.setattr(deps, "meter_for", lambda *a, **k: None)
    assert h.rig.client.post(f"/v1/meetings/{MEETING}/attend", json={"join_url": LINK}).status_code == 200
    response = h.rig.client.get(path)
    assert response.status_code == 200, response.text
    body = response.json()
    line = {"id": "u0001", "t_ms": 900, "speaker": "Someone", "text": "Ship it on Friday.", "truncated": False}
    assert body["utterances"] == [line] and body["meeting_id"] == MEETING
    assert body["screening"] == "unscreened" and body["transcript"]["version"] == 1  # the owner sees what it says
    h.rig.as_user(SAM)
    assert h.rig.client.get(path).status_code == 404  # one answer for anyone else
