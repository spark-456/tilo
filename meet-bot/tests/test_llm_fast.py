"""VA-01: the fast-path model client. Fakes only: no network, no real key."""

import asyncio
import re
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

from bot.brain import COULD_NOT_GET_LINE, Agenda, Brain, LLMUnavailable
from bot.captions import Utterance
from bot.config import Config
from bot.llm_fast import Busy, FastLLM

FAKE_KEY = "AQ." + "x1y2z3" * 6  # assembled at runtime; never a real key
DEADLINE = 0.3


class ApiError(Exception):
    """Shaped like google.genai.errors.APIError: a numeric code and a status string."""

    def __init__(self, code, status="", message="boom"):
        super().__init__(message)
        self.code, self.status = code, status


class FakeClient:
    """Mimics `client.aio.models`. `script` is one behaviour per call: list of chunks, 'hang', or an exception."""

    def __init__(self, *script):
        self.script, self.calls, self.configs, self.gets = list(script), 0, [], 0
        self.aio = SimpleNamespace(models=self)

    async def generate_content_stream(self, *, model, contents, config):
        self.calls += 1
        self.configs.append(config)
        step = self.script.pop(0)
        if step == "hang":
            await asyncio.Event().wait()
        if isinstance(step, Exception):
            raise step
        return self._chunks(step)

    @staticmethod
    async def _chunks(texts):
        for t in texts:
            yield SimpleNamespace(text=t)

    async def get(self, *, model, config=None):
        self.gets += 1
        return SimpleNamespace(name=model)


class Factory:
    def __init__(self, *clients):
        self.clients, self.made = list(clients), 0

    def __call__(self):
        self.made += 1
        return self.clients.pop(0)


def make(*clients, **kw):
    attempts: list[dict] = []
    factory = Factory(*clients)
    llm = FastLLM(
        model="m-test",
        client_factory=factory,
        first_token_s=kw.pop("first_token_s", DEADLINE),
        on_attempt=attempts.append,
        **kw,
    )
    return llm, factory, attempts


def run(coro):
    return asyncio.run(coro)


def test_VA_01_hanging_first_attempt_retries_on_a_fresh_client_within_the_deadline():
    llm, factory, attempts = make(FakeClient("hang"), FakeClient(["Hi ", "there."]))
    t = time.monotonic()
    text = run(llm.generate("sys", "q"))
    assert text == "Hi there."
    assert time.monotonic() - t < DEADLINE + 0.05
    assert factory.made == 2  # the retry used a fresh client, not the hung one
    assert [a["outcome"] for a in attempts] == ["timeout", "ok"]


def test_VA_01_a_429_raises_busy_with_no_sleep(monkeypatch):
    async def no_sleep(*a, **k):
        raise AssertionError("a 429 must not sleep")

    monkeypatch.setattr(asyncio, "sleep", no_sleep)
    llm, factory, attempts = make(FakeClient(ApiError(429, "RESOURCE_EXHAUSTED")))
    with pytest.raises(Busy):
        run(llm.generate("sys", "q"))
    assert factory.made == 1 and [(a["outcome"], a["code"]) for a in attempts] == [("busy", 429)]


def test_VA_01_a_connection_reset_retries_immediately():
    llm, factory, attempts = make(FakeClient(ConnectionResetError("reset")), FakeClient(["ok"]))
    t = time.monotonic()
    assert run(llm.generate("sys", "q")) == "ok"
    assert time.monotonic() - t < 0.05
    assert [a["outcome"] for a in attempts] == ["error", "ok"]


def test_VA_01_two_failures_raise_unavailable_after_exactly_two_attempts():
    llm, factory, attempts = make(FakeClient("hang"), FakeClient(ApiError(503, "UNAVAILABLE")))
    with pytest.raises(LLMUnavailable):
        run(llm.generate("sys", "q"))
    assert factory.made == 2 and len(attempts) == 2


@pytest.mark.parametrize("code", [401, 403, 404])
def test_VA_01_auth_and_missing_model_fail_without_a_retry(code):
    llm, factory, attempts = make(FakeClient(ApiError(code)), FakeClient(["never used"]))
    with pytest.raises(LLMUnavailable):
        run(llm.generate("sys", "q"))
    assert factory.made == 1 and attempts[0]["code"] == code


def test_VA_01_deltas_arrive_in_order_and_empty_chunks_are_skipped():
    llm, _, _ = make(FakeClient(["", "One ", None, "two ", "three."]))

    async def collect():
        return [d async for d in llm.stream("sys", "q")]

    assert run(collect()) == ["One ", "two ", "three."]


def test_VA_01_the_attempt_log_has_outcome_code_and_first_token_time():
    llm, _, attempts = make(FakeClient(ApiError(500, "INTERNAL")), FakeClient(["a", "b"]))
    run(llm.generate("sys", "q"))
    bad, good = attempts
    assert bad["outcome"] == "error" and bad["code"] == 500 and bad["first_token_s"] is None
    assert good["outcome"] == "ok" and good["code"] is None and 0 <= good["first_token_s"] < DEADLINE
    for row in attempts:
        assert {"purpose", "model", "attempt", "outcome", "code", "first_token_s", "total_s"} <= row.keys()
    assert [a["attempt"] for a in attempts] == [1, 2]


def test_VA_01_the_key_never_reaches_the_attempt_log_or_the_error(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", FAKE_KEY)
    leaky = ApiError(400, "INVALID_ARGUMENT", f"bad request for key={FAKE_KEY}")
    llm, _, attempts = make(FakeClient(leaky))
    with pytest.raises(LLMUnavailable) as exc:
        run(llm.generate("sys", "q"))
    assert FAKE_KEY not in str(exc.value) and FAKE_KEY not in repr(attempts)


def test_VA_01_prewarm_is_rate_limited_to_once_per_10_seconds():
    now = [100.0]
    client = FakeClient()
    llm, _, _ = make(client, clock=lambda: now[0])

    async def go():
        done = [await llm.prewarm()]
        now[0] += 5
        done.append(await llm.prewarm())
        now[0] += 5.5
        done.append(await llm.prewarm())
        return done

    assert run(go()) == [True, False, True] and client.gets == 2


def test_VA_01_a_failed_prewarm_never_raises():
    class Broken(FakeClient):
        async def get(self, *, model, config=None):
            raise ApiError(503, "UNAVAILABLE")

    llm, _, attempts = make(Broken())
    assert run(llm.prewarm()) is True  # a call was made; its failure is logged, not raised
    assert attempts[0]["outcome"] == "error"


def test_VA_01_thinking_comes_from_config_not_the_model_name():
    def cfg_for(thinking):
        client = FakeClient(["x"])
        llm = FastLLM(model="gemini-2.5-named-but-irrelevant", thinking=thinking, client_factory=lambda: client)
        run(llm.generate("sys", "q"))
        return client.configs[0]["thinking_config"]

    assert cfg_for("off") == {"thinking_budget": 0}
    assert cfg_for("minimal") == {"thinking_level": "MINIMAL"}  # same model name, different setting


def test_VA_01_fast_model_and_thinking_are_configuration(monkeypatch):
    for name in ("FAST_MODEL", "FAST_THINKING"):
        monkeypatch.delenv(name, raising=False)
    base = Config.from_env()
    assert base.fast_model and base.fast_thinking == "off"
    monkeypatch.setenv("FAST_MODEL", "some-other-model")
    monkeypatch.setenv("FAST_THINKING", "minimal")
    cfg = Config.from_env()
    assert (cfg.fast_model, cfg.fast_thinking) == ("some-other-model", "minimal")


def test_VA_01_no_model_id_literal_outside_config():
    pattern = re.compile(r"gemini-\d|eleven_\w+_v\d|scribe_v\d", re.I)
    for path in (Path(__file__).parent.parent / "bot").glob("*.py"):
        if path.name != "config.py":
            assert not pattern.search(path.read_text(encoding="utf-8")), path.name


def test_VA_01_keep_warm_is_deleted():
    src = (Path(__file__).parent.parent / "bot" / "session.py").read_text(encoding="utf-8")
    assert "_keep_warm" not in src and "warm_task" not in src
    assert not hasattr(Config, "keep_warm_s") and "keep_warm_s" not in Config.__dataclass_fields__


class StubFast:
    def __init__(self, reply=None, exc=None):
        self.reply, self.exc, self.calls = reply, exc, []

    async def generate(self, system, prompt, **kw):
        self.calls.append(prompt)
        if self.exc:
            raise self.exc
        return self.reply


class SyncMustNotRun:
    def generate(self, system, prompt):
        raise AssertionError("the thread-bound client must not serve direct questions")


def _brain(fast):
    agenda = Agenda.parse("# Sync\n1. Roadmap (10 min)\n")
    return Brain(agenda, SyncMustNotRun(), 30, bot_name="Tilo", fast=fast)


ASK = [Utterance("Sam", "Tilo, what is the plan for the beta?", 5)]


def test_VA_01_direct_questions_use_the_fast_client_and_not_the_thread_client():
    fast = StubFast('{"reply": "The beta ships in October."}')
    msg = run(_brain(fast).aquick_reply(ASK, 30))
    assert msg is not None and msg.text == "The beta ships in October." and len(fast.calls) == 1


@pytest.mark.parametrize("exc", [Busy("429"), LLMUnavailable("down")])
def test_VA_01_a_busy_or_down_model_never_raises_and_only_speaks_when_addressed(exc):
    addressed = run(_brain(StubFast(exc=exc)).aquick_reply(ASK, 30))
    assert addressed is not None and addressed.text == COULD_NOT_GET_LINE  # never silent for a question put to Tilo
    chatter = [Utterance("Sam", "When does the beta ship for everyone?", 5)]
    assert run(_brain(StubFast(exc=exc)).aquick_reply(chatter, 30)) is None
