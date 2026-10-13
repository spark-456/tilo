"""FR-MTG-11 (M2b), SEC-16, BQ-M2-4, ADR-0042 (MV-07, MV-10, MV-12, MV-16): the bot's half of the Live voice meter.

A fake tilo-api (an httpx mock transport): the claim the attend carried is echoed, each reply has its own fresh key, a
close carries usage only when settled, and anything but a 200 `live` is the local voice, never an exception into the
call. Flag off (no TILO_API_URL, no claim) changes nothing. No network, no SDK, no real audio, no paid call."""

import asyncio
import base64
import json
import logging
import threading
import time
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest
import yaml
from fastapi.testclient import TestClient
from tilo_contracts import MeetingVoiceMeterCloseRequest, MeetingVoiceMeterReserveRequest
from tilo_providers.gemini_live_voice_adapter import GeminiLiveVoiceProvider

from bot import cloud_worker, voice_meter
from bot.cloud_run import create_app
from bot.providers import ProviderTTS, load_voice_config, repo_root
from bot.tts import TTSError
from bot.voice_meter import CLAIM_HEADER, IdentityToken, RemoteLiveVoiceMeter, meter_from_env

ROOT = repo_root()
BASE = "https://tilo-api-example.asia-southeast1.run.app"
MEETING = "mt_demo"
CLAIM = "c" * 8 + "-_" * 8 + "Z9" * 8  # 40 characters of the claim alphabet, made at runtime
TOKEN = "-".join(["fake", "identity", "token", "for", "tests"])


class Api:
    """The two routes of tilo-api as the bot sees them. `reserve` and `close` are an answer (status, body) or a
    function of the request."""

    def __init__(self, reserve=(200, {"decision": "live"}), close=(200, None)):
        self.reserve_answer, self.close_answer = reserve, close
        self.calls: list[tuple[str, dict, httpx.Headers]] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        self.calls.append((request.url.path, body, request.headers))
        answer = self.reserve_answer if request.url.path.endswith("/reserve") else self.close_answer
        if callable(answer):
            return answer(request)
        status, payload = answer
        if payload is None:
            payload = {"outcome": body.get("outcome")}
        return httpx.Response(status, json=payload)

    @property
    def reserves(self):
        return [c for c in self.calls if c[0].endswith("/reserve")]

    @property
    def closes(self):
        return [c for c in self.calls if c[0].endswith("/close")]


def meter_for(api: Api, **kwargs) -> RemoteLiveVoiceMeter:
    kwargs.setdefault("token_for", lambda audience: TOKEN)
    return RemoteLiveVoiceMeter(BASE, MEETING, CLAIM, transport=httpx.MockTransport(api), **kwargs)


# -- reserve: the contract, the claim, a fresh key ----------------------------------------------------------------------
def test_FR_MTG_11_BQ_M2_4_MV_16_reserve_echoes_the_claim_with_a_fresh_key_for_every_reply():
    api = Api()
    meter = meter_for(api)
    holds = [meter.reserve() for _ in range(3)]
    assert all(holds) and len(api.reserves) == 3
    keys = [body["key"] for _, body, _ in api.reserves]
    assert len(set(keys)) == 3  # a key is never reused
    for path, body, headers in api.reserves:
        assert path == "/internal/meeting-voice/reserve"
        assert set(body) == {"meeting_id", "claim", "key"}  # the contract's closed body: no uid, org, amount or run
        assert body["claim"] == CLAIM and body["meeting_id"] == MEETING
        MeetingVoiceMeterReserveRequest.model_validate(body)
        assert headers["authorization"] == f"Bearer {TOKEN}"


def test_FR_MTG_11_BQ_M2_4_the_token_is_minted_for_the_api_url_as_audience():
    seen = []
    api = Api()
    meter = meter_for(api, token_for=lambda audience: seen.append(audience) or TOKEN)
    assert meter.reserve() is not None
    assert seen == [BASE]


@pytest.mark.parametrize(
    "answer",
    [
        (200, {"decision": "replay", "reason": "capped"}),
        (200, {"decision": "replay", "reason": "hold_open"}),
        (401, {"error": "unauthenticated"}),
        (403, {"error": "forbidden"}),
        (409, {"error": "not_attending"}),
        (409, {"error": "key_used"}),
        (422, {"error": "invalid_request"}),
        (503, {"error": "not_configured"}),
        (500, {"detail": "boom"}),
        (307, {"detail": "elsewhere"}),
        (404, {"detail": "Not Found"}),
        (200, {"decision": "live", "reason": "capped"}),  # off-contract: a reason on live
        (200, {"decision": "replay"}),  # off-contract: no reason on replay
        (200, {"decision": "maybe"}),
        (200, {"decision": "live", "uid": "u_1"}),  # an extra field
        (200, ["live"]),
        (200, {"decision": "live", "pad": "x" * 2000}),  # over 1 KiB
    ],
)
def test_FR_MTG_11_BQ_M2_4_MV_07_anything_but_a_200_live_is_the_local_voice(answer):
    api = Api(reserve=answer)
    assert meter_for(api).reserve() is None
    assert len(api.reserves) == 1  # no redirect followed, no retry of a reserve


def test_FR_MTG_11_BQ_M2_4_MV_07_a_non_json_200_a_timeout_and_an_unreachable_api_are_the_local_voice_not_errors():
    def non_json(request):
        return httpx.Response(200, content=b"<html>ok</html>")

    def timeout(request):
        raise httpx.ReadTimeout("slow")

    def unreachable(request):
        raise httpx.ConnectError("no route")

    def broken(request):
        raise RuntimeError("anything at all")

    for answer in (non_json, timeout, unreachable, broken):
        api = Api(reserve=answer)
        assert meter_for(api).reserve() is None


def test_FR_MTG_11_BQ_M2_4_MV_07_no_token_means_no_request_and_the_local_voice():
    def no_identity(audience):
        raise OSError("metadata server unreachable")

    api = Api()
    assert meter_for(api, token_for=no_identity).reserve() is None
    assert api.calls == []


def test_FR_MTG_11_BQ_M2_4_a_lost_reserve_answer_is_followed_by_one_release_of_the_same_key():
    def lost(request):
        raise httpx.ReadTimeout("slow")

    api = Api(reserve=lost)
    meter = meter_for(api)
    assert meter.reserve() is None
    assert meter.last_free is not None
    meter.last_free.join(5)
    (_, body, _), (_, freed, _) = api.reserves[0], api.closes[0]
    assert freed["key"] == body["key"] and freed["outcome"] == "released" and "usage" not in freed


def test_FR_MTG_11_BQ_M2_4_a_refusal_opens_no_hold_so_nothing_is_released():
    api = Api(reserve=(409, {"error": "not_attending"}))
    meter = meter_for(api)
    assert meter.reserve() is None
    assert meter.last_free is None and api.closes == []


# -- close: usage only when settled, once -------------------------------------------------------------------------------
def test_FR_MTG_11_BQ_M2_4_MV_05_a_settle_closes_once_with_the_adapters_counts_and_the_same_key():
    api = Api()
    meter = meter_for(api)
    hold = meter.reserve()
    usage = {"prompt_token_count": 12, "response_token_count": 30, "total_token_count": 42}
    meter.settle(hold, usage)
    meter.settle(hold, usage)  # a second close of the same hold sends nothing
    meter.release(hold)
    assert len(api.closes) == 1
    path, body, _ = api.closes[0]
    assert path == "/internal/meeting-voice/close"
    assert body == {
        "meeting_id": MEETING,
        "claim": CLAIM,
        "key": api.reserves[0][1]["key"],
        "outcome": "settled",
        "usage": usage,
    }
    MeetingVoiceMeterCloseRequest.model_validate(body)


def test_FR_MTG_11_BQ_M2_4_a_release_closes_without_usage():
    api = Api()
    meter = meter_for(api)
    hold = meter.reserve()
    meter.release(hold)
    assert [b["outcome"] for _, b, _ in api.closes] == ["released"]
    assert "usage" not in api.closes[0][1]
    MeetingVoiceMeterCloseRequest.model_validate(api.closes[0][1])


@pytest.mark.parametrize(
    ("usage", "sent"),
    [
        ({}, {}),  # empty usage books the whole unit at tilo-api
        ({"response_token_count": 7}, {"response_token_count": 7}),
        ({"total_token_count": 16384}, {"total_token_count": 16384}),
        ({"prompt_token_count": 1, "unexpected": 5}, {"prompt_token_count": 1}),  # a closed body names three counts
        ({"prompt_token_count": 16385}, {}),  # out of the contract's range: the whole unit, not a 422
        ({"prompt_token_count": -1, "response_token_count": 3}, {}),
        ({"prompt_token_count": True}, {}),
        ({"prompt_token_count": 1.5}, {}),
    ],
)
def test_FR_MTG_11_BQ_M2_4_MV_09_only_the_contracts_counts_are_sent_and_never_money(usage, sent):
    api = Api()
    meter = meter_for(api)
    meter.settle(meter.reserve(), usage)
    assert api.closes[0][1]["usage"] == sent


def test_FR_MTG_11_BQ_M2_4_MV_08_a_failing_close_is_retried_once_with_the_same_key_then_dropped_never_raised():
    api = Api(close=(500, {"detail": "down"}))
    meter = meter_for(api)
    meter.settle(meter.reserve(), {"total_token_count": 5})  # no exception
    assert len(api.closes) == 2
    assert api.closes[0][1] == api.closes[1][1]


def test_FR_MTG_11_BQ_M2_4_a_close_that_works_on_the_retry_stops_there():
    attempts = []

    def flaky(request):
        attempts.append(1)
        if len(attempts) == 1:
            raise httpx.ConnectError("blip")
        return httpx.Response(200, json={"outcome": "released"})

    api = Api(close=flaky)
    meter = meter_for(api)
    meter.release(meter.reserve())
    assert len(attempts) == 2


def test_FR_MTG_11_BQ_M2_4_a_foreign_hold_is_ignored_and_never_raises():
    api = Api()
    meter = meter_for(api)
    meter.settle(object(), {})
    meter.release("not-a-hold")
    assert api.calls == []


# -- MV-10: nothing secret in a log line, an error, a repr -------------------------------------------------------------
def test_FR_MTG_11_BQ_M2_4_MV_10_the_claim_the_token_and_the_keys_are_in_no_log_line_or_repr(caplog):
    caplog.set_level(logging.DEBUG)
    api = Api(reserve=(500, {"detail": f"{CLAIM} {TOKEN}"}), close=(500, {"detail": CLAIM}))
    meter = meter_for(api)
    assert meter.reserve() is None
    ok = Api()
    healthy = meter_for(ok)
    hold = healthy.reserve()
    healthy.settle(hold, {"prompt_token_count": 11, "total_token_count": 4242})
    secrets_ = [CLAIM, TOKEN] + [b["key"] for _, b, _ in api.calls + ok.calls]
    text = caplog.text + repr(meter) + repr(hold) + repr(healthy) + repr(IdentityToken())
    assert caplog.records  # the refusal was noted (by reason word only)
    assert all(secret not in text for secret in secrets_)
    assert "4242" not in text  # usage never logged


def test_FR_MTG_11_BQ_M2_4_MV_10_a_failing_transport_logs_a_class_name_not_the_exception_text(caplog):
    caplog.set_level(logging.DEBUG)

    def boom(request):
        raise RuntimeError(f"{BASE} {CLAIM} {TOKEN}")

    meter = meter_for(Api(reserve=boom))
    assert meter.reserve() is None
    meter.last_free.join(5)  # the best-effort release of a reserve that errored
    ours = "\n".join(r.getMessage() for r in caplog.records if r.name == "bot.voice_meter")
    assert "RuntimeError" in ours
    assert CLAIM not in caplog.text and TOKEN not in caplog.text  # nothing at all, any logger
    assert BASE not in ours  # the exception text (which carried the url) is never kept


# -- the identity token from the metadata server ------------------------------------------------------------------------
def _jwt(exp: float) -> str:
    payload = base64.urlsafe_b64encode(json.dumps({"exp": exp}).encode()).decode().rstrip("=")
    return ".".join(["a" * 12, payload, "b" * 12])


def test_FR_MTG_11_BQ_M2_4_the_identity_token_comes_from_the_metadata_server_for_the_audience_and_is_cached():
    requests = []
    now = [1000.0]
    token = _jwt(now[0] + 3600)

    def metadata(request):
        requests.append(request)
        return httpx.Response(200, text=token)

    minted = IdentityToken(transport=httpx.MockTransport(metadata), clock=lambda: now[0])
    assert minted(BASE) == token and minted(BASE) == token
    assert len(requests) == 1  # cached
    request = requests[0]
    assert request.url.host == "metadata.google.internal"
    assert request.headers["metadata-flavor"] == "Google"
    assert request.url.params["audience"] == BASE and request.url.params["format"] == "full"
    now[0] += 3600  # past its expiry less the margin
    assert minted(BASE) == token and len(requests) == 2


@pytest.mark.parametrize("answer", [httpx.Response(404, text="nope"), httpx.Response(200, text="not-a-jwt")])
def test_FR_MTG_11_BQ_M2_4_an_unusable_identity_answer_is_no_token(answer):
    minted = IdentityToken(transport=httpx.MockTransport(lambda request: answer))
    with pytest.raises(Exception):  # noqa: B017, PT011  (the meter turns any failure into the local voice)
        minted(BASE)


# -- built only when the flag, the url and the claim are all there -----------------------------------------------------
GOOD_ENV = {"LIVE": "1", "TILO_API_URL": BASE}


@pytest.mark.parametrize(
    ("claim", "env"),
    [
        (CLAIM, {}),  # nothing set: inert
        (CLAIM, {"TILO_API_URL": BASE}),  # no live switch
        (CLAIM, {"LIVE": "0", "TILO_API_URL": BASE}),
        (CLAIM, {"LIVE": "1"}),  # no TILO_API_URL
        (CLAIM, {"LIVE": "1", "TILO_API_URL": ""}),
        (CLAIM, {"LIVE": "1", "TILO_API_URL": "http://tilo-api.example"}),  # not https
        (CLAIM, {"LIVE": "1", "TILO_API_URL": BASE + "/v1"}),  # a path
        (CLAIM, {"LIVE": "1", "TILO_API_URL": BASE + "?x=1"}),
        (None, GOOD_ENV),  # an older caller: no claim header
        ("", GOOD_ENV),
        (CLAIM[:31], GOOD_ENV),
        (CLAIM + "\n", GOOD_ENV),
        ("x" * 65, GOOD_ENV),
        ("a b" * 12, GOOD_ENV),
    ],
)
def test_FR_MTG_11_BQ_M2_4_the_meter_is_built_only_with_the_switch_the_api_url_and_a_valid_claim(claim, env):
    assert meter_from_env(MEETING, claim, env) is None


def test_FR_MTG_11_BQ_M2_4_a_bad_meeting_id_builds_no_meter_and_a_good_set_builds_one():
    assert meter_from_env("not-a-meeting", CLAIM, GOOD_ENV) is None
    assert isinstance(meter_from_env(MEETING, CLAIM, GOOD_ENV), RemoteLiveVoiceMeter)


# -- the attend route and the worker: the claim travels in memory and nowhere else -------------------------------------
NOW = datetime(2026, 10, 13, 12, tzinfo=UTC)
AUDIENCE = "https://tilo-meet-bot-example.asia-southeast1.run.app"
CALLER = "tilo-api@example.iam.gserviceaccount.com"
JOIN = "https://meet.google.com/abc-defg-hij"


@pytest.fixture
def attend_app(monkeypatch):
    monkeypatch.setenv("TILO_MEET_BOT_AUDIENCE", AUDIENCE)
    monkeypatch.setenv("TILO_MEET_BOT_CALLER", CALLER)
    monkeypatch.setenv("LIVE", "1")
    claims = {"iss": "https://accounts.google.com", "aud": AUDIENCE, "email": CALLER, "email_verified": True}
    attend = AsyncMock(
        return_value={
            "v": "1.0",
            "meeting_id": MEETING,
            "utterances": [{"id": "u0001", "speaker": "Person", "t_ms": 0, "text": "A note."}],
        }
    )
    app = create_app(attend=attend, verifier=SimpleNamespace(verify=lambda *a: claims), clock=lambda: NOW)
    return TestClient(app), attend


def _launch(client, **headers):
    expires = (NOW + timedelta(seconds=30)).isoformat(timespec="milliseconds").replace("+00:00", "Z")
    return client.post(
        f"/internal/meetings/{MEETING}/attend",
        json={"join_url": JOIN, "expires_at": expires},
        headers={"Authorization": "Bearer " + TOKEN, **headers},
    )


def test_FR_MTG_11_BQ_M2_4_MV_16_the_attend_header_reaches_the_worker_and_never_the_response(attend_app, caplog):
    caplog.set_level(logging.DEBUG)
    client, attend = attend_app
    response = _launch(client, **{CLAIM_HEADER: CLAIM})
    assert response.status_code == 200
    attend.assert_awaited_once_with(MEETING, JOIN, claim=CLAIM)
    assert CLAIM not in response.text and CLAIM not in str(response.headers) and CLAIM not in caplog.text


@pytest.mark.parametrize("header", [None, "", "short", "x" * 65, "a b" * 12])
def test_FR_MTG_11_BQ_M2_4_without_a_valid_claim_header_the_worker_is_called_exactly_as_before(attend_app, header):
    client, attend = attend_app
    response = _launch(client, **({} if header is None else {CLAIM_HEADER: header}))
    assert response.status_code == 200
    attend.assert_awaited_once_with(MEETING, JOIN)


def _capturing_worker(monkeypatch, tmp_path):
    from bot import config

    monkeypatch.setattr(config, "load_dotenv", lambda: None)
    seen = {}

    class Session:
        def __init__(self, cfg, *args, **kwargs):
            seen["kwargs"] = kwargs
            self.events = SimpleNamespace(echo=True)
            self.store = SimpleNamespace(items=[])

        async def run(self):
            return None

    monkeypatch.setattr(cloud_worker, "LiveSession", Session)
    return seen


def test_FR_MTG_11_BQ_M2_4_the_worker_builds_the_meter_only_with_the_switch_the_url_and_the_claim(
    monkeypatch, tmp_path
):
    seen = _capturing_worker(monkeypatch, tmp_path)
    run = lambda claim: asyncio.run(cloud_worker.attend_meeting(MEETING, JOIN, claim))  # noqa: E731
    monkeypatch.setenv("LIVE", "1")
    run(CLAIM)  # no TILO_API_URL: inert
    assert seen["kwargs"] == {}
    monkeypatch.setenv("TILO_API_URL", BASE)
    run(None)  # an older caller
    assert seen["kwargs"] == {}
    run(CLAIM)
    assert isinstance(seen["kwargs"]["voice_meter"], RemoteLiveVoiceMeter)
    monkeypatch.delenv("LIVE")
    run(CLAIM)  # not the user's live switch
    assert seen["kwargs"] == {}


def _session(monkeypatch, tmp_path, **kwargs):
    from bot.config import Config
    from bot.session import LiveSession

    monkeypatch.setattr("bot.config.load_dotenv", lambda path=None: None)
    monkeypatch.setenv("OUT_DIR", str(tmp_path / "out"))
    monkeypatch.setenv("CONTEXT_DIR", str(tmp_path / "ctx"))
    return LiveSession(
        Config.from_env(), "join", "https://meet.example/abc-defg-hij", None, 30, False, [], False, False, [], **kwargs
    )


def test_FR_MTG_11_BQ_M2_4_the_session_hands_its_meter_to_make_tts_and_without_one_calls_it_as_before(
    monkeypatch, tmp_path
):
    calls = []
    monkeypatch.setattr("bot.session.make_tts", lambda *a, **k: calls.append((a, k)) or None)
    monkeypatch.setattr("bot.session.setup_virtual_mic", lambda: True)
    meter = meter_for(Api())
    _session(monkeypatch, tmp_path, voice_meter=meter)._setup_voice()
    _session(monkeypatch, tmp_path)._setup_voice()
    assert calls == [((), {"meter": meter}), ((), {})]


# -- end to end in process: the meter over the Live adapter and the fake API -------------------------------------------
def _live_config(tmp_path: Path):
    raw = yaml.safe_load((ROOT / "config" / "voice.yaml").read_text(encoding="utf-8"))
    raw["voice"]["live"]["enabled"] = True
    raw["voice"]["live"]["price_approved"] = True
    path = tmp_path / "voice.yaml"
    path.write_text(yaml.safe_dump(raw), encoding="utf-8")
    return load_voice_config(path, models_path=ROOT / "config" / "models.yaml")


def _live_tts(tmp_path, meter, opened):
    config = _live_config(tmp_path)
    rate = config.sample_rate

    class Session:
        async def send_client_content(self, **kwargs):
            return None

        async def receive(self):
            usage = SimpleNamespace(prompt_token_count=12, response_token_count=30, total_token_count=42)
            part = SimpleNamespace(
                inline_data=SimpleNamespace(data=b"\x01\x02" * 64, mime_type=f"audio/pcm;rate={rate}")
            )
            content = SimpleNamespace(interrupted=False, model_turn=SimpleNamespace(parts=[part]), turn_complete=True)
            yield SimpleNamespace(usage_metadata=usage, server_content=content)

    @asynccontextmanager
    async def connect(settings):
        opened.append(1)
        yield Session()

    provider = GeminiLiveVoiceProvider(config, fixtures_dir=None, session_factory=connect, meter=meter)
    return ProviderTTS(provider=provider, config=config)


def _speak(tts):
    async def go():
        return [piece async for piece in tts.stream("The release is Friday.")]

    return asyncio.run(go())


def test_FR_MTG_11_BQ_M2_4_a_live_answer_speaks_live_and_settles_the_replys_counts_once(tmp_path):
    api, opened = Api(), []
    pieces = _speak(_live_tts(tmp_path, meter_for(api), opened))
    assert pieces and opened == [1]
    assert len(api.reserves) == 1 and len(api.closes) == 1
    body = api.closes[0][1]
    assert body["outcome"] == "settled" and body["key"] == api.reserves[0][1]["key"]
    assert body["usage"] == {"prompt_token_count": 12, "response_token_count": 30, "total_token_count": 42}


@pytest.mark.parametrize(
    ("answer", "permanent"),
    # BQ-M2-12: a 500 is a blip and the next reply asks again (permanent False); a cap or a lost claim is not
    [
        ((200, {"decision": "replay", "reason": "capped"}), True),
        ((409, {"error": "not_attending"}), True),
        ((500, {}), False),
    ],
)
def test_FR_MTG_11_BQ_M2_4_MV_07_without_a_200_live_no_session_opens_and_the_local_voice_takes_over(
    tmp_path, answer, permanent
):
    api, opened = Api(reserve=answer), []
    with pytest.raises(TTSError) as caught:
        _speak(_live_tts(tmp_path, meter_for(api), opened))
    assert caught.value.permanent is permanent and opened == []  # the bot's FallbackTTS speaks the local voice
    assert api.closes == [] or all(b["outcome"] == "released" for _, b, _ in api.closes)


def test_FR_MTG_11_BQ_M2_4_an_unreachable_api_keeps_the_voice_unmetered_and_unlive(tmp_path):
    def unreachable(request):
        raise httpx.ConnectError("no route")

    opened = []
    with pytest.raises(TTSError):
        _speak(_live_tts(tmp_path, meter_for(Api(reserve=unreachable, close=unreachable)), opened))
    assert opened == []


def test_FR_MTG_11_BQ_M2_4_MV_12_the_meter_is_fast_to_give_up(tmp_path):
    def slow_failure(request):
        raise httpx.ConnectTimeout("late")

    meter = meter_for(Api(reserve=slow_failure))
    started = time.monotonic()
    assert meter.reserve() is None
    assert time.monotonic() - started < 2.5
    assert voice_meter.TIMEOUT_S == 2.0  # ADR-0042 decision 11: 2 s timeouts


def test_FR_MTG_11_BQ_M2_4_concurrent_replies_each_get_their_own_key():
    api = Api()
    meter = meter_for(api)
    holds = []

    def reserve():
        holds.append(meter.reserve())

    threads = [threading.Thread(target=reserve) for _ in range(5)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    assert len({b["key"] for _, b, _ in api.reserves}) == 5 and all(holds)


# -- the contract's if/then/else pairs, from the JSON Schema itself (the generated models drop them) -------------------
def test_FR_MTG_11_BQ_M2_4_MV_07_a_live_answer_that_carries_a_reason_is_not_live():
    """`reserve_answer`: `live` must carry no `reason`. The generated pydantic model accepts it; the schema does not."""
    from tilo_contracts import MeetingVoiceMeterReserveAnswer

    bad = {"decision": "live", "reason": "capped"}
    assert MeetingVoiceMeterReserveAnswer.model_validate(bad).decision == "live"  # why the schema is the check
    api = Api(reserve=(200, bad))
    assert meter_for(api).reserve() is None


@pytest.mark.parametrize("bad", [{"decision": "replay"}, {"decision": "replay", "reason": "free_money"}])
def test_FR_MTG_11_BQ_M2_4_MV_07_a_not_live_answer_must_carry_one_of_the_contracts_reasons(bad):
    """`reserve_answer`: any decision but `live` must carry a `reason` from the enum. Never a hold either way."""
    assert meter_for(Api(reserve=(200, bad))).reserve() is None


@pytest.mark.parametrize(
    "bad",
    [
        {},
        {"decision": None},
        {"decision": "LIVE"},
        {"decision": "live", "reason": None},
        {"decision": ["live"]},
        "live",
        0,
        [],
    ],
)
def test_FR_MTG_11_BQ_M2_4_MV_07_a_malformed_reserve_answer_is_never_a_hold(bad):
    assert meter_for(Api(reserve=(200, bad))).reserve() is None


@pytest.mark.parametrize("bad", [{"outcome": "closed"}, {"outcome": "settled", "extra": 1}, {}, "settled"])
def test_FR_MTG_11_BQ_M2_4_a_malformed_close_answer_is_retried_once_then_dropped_never_raised(bad):
    api = Api(close=(200, bad))
    meter = meter_for(api)
    meter.settle(meter.reserve(), {"total_token_count": 1})
    assert len(api.closes) == 2


def test_FR_MTG_11_BQ_M2_4_a_close_answer_for_the_other_outcome_is_not_taken_for_the_one_asked():
    api = Api(close=(200, {"outcome": "released"}))
    meter = meter_for(api)
    meter.settle(meter.reserve(), {"total_token_count": 1})
    assert len(api.closes) == 2  # a mismatch is a failed close: one retry, then dropped


def test_FR_MTG_11_BQ_M2_4_the_requests_the_bot_sends_are_valid_against_the_schema_pairs():
    """`close_request`: `usage` exactly when `settled`. Checked on what really went out, with the schema itself."""
    api = Api()
    meter = meter_for(api)
    meter.settle(meter.reserve(), {"prompt_token_count": 3})
    meter.release(meter.reserve())
    meter.settle(meter.reserve(), {"prompt_token_count": 99999})  # out of range: sent as empty usage, still valid
    for name, (_, body, _) in [("reserve_request", api.reserves[0])] + [("close_request", c) for c in api.closes]:
        assert voice_meter._validator(name).is_valid(body), name
    assert [("usage" in c[1]) for c in api.closes] == [True, False, True]


def test_FR_MTG_11_BQ_M2_4_without_the_contracts_schema_files_there_is_no_meter(monkeypatch, tmp_path):
    """The image carries the two schema files; an image without them stays on the local voice, never unchecked."""
    monkeypatch.setenv("TILO_REPO_ROOT", str(tmp_path))
    voice_meter._registry.cache_clear()
    voice_meter._validator.cache_clear()
    try:
        assert meter_from_env(MEETING, CLAIM, GOOD_ENV) is None
    finally:
        monkeypatch.delenv("TILO_REPO_ROOT")
        voice_meter._registry.cache_clear()
        voice_meter._validator.cache_clear()
    assert meter_from_env(MEETING, CLAIM, GOOD_ENV) is not None
