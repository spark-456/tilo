"""VA-01: the fast-path model client. Fakes only: no network, no real key. (FR-MTG-11: the client behind `FastLLM` is a
`FastClient`; the provider-layer implementation is tested in test_FR_MTG_11_providers.py.)"""

import asyncio
import json
import time
from pathlib import Path

import pytest

from bot.brain import COULD_NOT_GET_LINE, Agenda, Brain, LLMUnavailable
from bot.captions import Utterance
from bot.config import Config
from bot.llm_fast import Busy, FastLLM, ModelCallError

DEADLINE = 0.3


class ApiError(ModelCallError):
    """What the provider adapter raises: a numeric code and a status word."""

    def __init__(self, code, status="", message="boom"):
        super().__init__(code, status, message)


class FakeClient:
    """`script` is one behaviour per call: a list of chunks, 'hang', or an exception."""

    def __init__(self, *script, warm_error=None, can_warm=True):
        self.script, self.calls, self.thinking, self.warms = list(script), 0, [], 0
        self.warm_error, self.can_warm = warm_error, can_warm

    async def open(self, system, prompt, *, json_mode, max_tokens, thinking):
        self.calls += 1
        self.thinking.append(thinking)
        step = self.script.pop(0)
        if step == "hang":
            await asyncio.Event().wait()
        if isinstance(step, Exception):
            raise step
        return self._chunks(step)

    @staticmethod
    async def _chunks(texts):
        for t in texts:
            yield t

    async def warm(self):
        self.warms += 1
        if self.warm_error:
            raise self.warm_error
        return self.can_warm


class Factory:
    def __init__(self, *clients):
        self.clients, self.made = list(clients), 0

    def __call__(self):
        self.made += 1
        return self.clients.pop(0)


def make(*clients, **kw):
    attempts: list[dict] = []
    factory = Factory(*clients)
    llm = FastLLM(factory, first_token_s=kw.pop("first_token_s", DEADLINE), on_attempt=attempts.append, **kw)
    return llm, factory, attempts


def run(coro):
    return asyncio.run(coro)


def test_VA_01_hanging_first_attempt_retries_on_a_fresh_client_within_the_deadline():
    llm, factory, attempts = make(FakeClient("hang"), FakeClient(["Hi ", "there."]))
    t = time.monotonic()
    text = run(llm.generate("sys", "q"))
    assert text == "Hi there."
    assert time.monotonic() - t < DEADLINE + 0.5  # a starved laptop adds scheduling noise; the retry is still at once
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
    assert time.monotonic() - t < 0.5
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
        assert {"purpose", "attempt", "outcome", "code", "first_token_s", "total_s"} <= row.keys()
        assert "model" not in row  # the bot does not know which model answered: the role's profile is config
    assert [a["attempt"] for a in attempts] == [1, 2]


def _secret() -> str:
    return "tok" + "en-" + "ab12" * 6  # assembled at runtime, never a real secret


def _every_text(exc: BaseException, attempts: list) -> str:
    """The raised exception (text and repr), the chain a traceback would print (`from None` hides the implicit context),
    and every attempt row as the connections.jsonl log holds it."""
    chain, seen = [], exc
    while seen is not None and len(chain) < 5:
        chain.append(f"{seen!s} {seen!r}")
        seen = seen.__cause__ or (None if seen.__suppress_context__ else seen.__context__)
    return " ".join([*chain, repr(attempts), json.dumps(attempts, default=str)])


def test_VA_01_provider_text_never_reaches_the_error_message_or_the_attempt_log():
    secret = _secret()
    leaky = ApiError(400, "INVALID_ARGUMENT", f"bad request for key={secret}")
    llm, _, attempts = make(FakeClient(leaky))
    with pytest.raises(LLMUnavailable) as exc:
        run(llm.generate("sys", "q"))
    assert "refused" in str(exc.value) and attempts and attempts[0]["code"] == 400
    assert secret not in _every_text(exc.value, attempts)


def test_VA_01_provider_text_never_reaches_the_error_after_two_failed_tries():
    secret = _secret()
    llm, _, attempts = make(
        FakeClient(ApiError(503, "UNAVAILABLE", f"upstream said {secret}")),
        FakeClient(RuntimeError(f"connection to host?key={secret} failed")),
    )
    with pytest.raises(LLMUnavailable) as exc:
        run(llm.generate("sys", "q"))
    text = _every_text(exc.value, attempts)
    assert secret not in text and len(attempts) == 2
    assert "RuntimeError" in attempts[1]["error"] and "503" in attempts[0]["error"]  # class and code stay: they explain


def test_VA_01_provider_text_never_reaches_the_error_when_a_stream_dies_after_its_first_token():
    secret = _secret()

    class Dying(FakeClient):
        async def open(self, system, prompt, *, json_mode, max_tokens, thinking):
            async def chunks():
                yield "partial "
                raise RuntimeError(f"stream cut, session={secret}")

            return chunks()

    llm, _, attempts = make(Dying())
    with pytest.raises(LLMUnavailable) as exc:
        run(llm.generate("sys", "q"))
    assert secret not in _every_text(exc.value, attempts) and attempts[-1]["outcome"] == "error"


def test_VA_01_provider_text_never_reaches_the_log_when_a_prewarm_fails():
    secret = _secret()
    llm, _, attempts = make(FakeClient(warm_error=RuntimeError(f"warm failed {secret}")))
    run(llm.prewarm())
    assert attempts and secret not in repr(attempts) and secret not in json.dumps(attempts)


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

    assert run(go()) == [True, False, True] and client.warms == 2


def test_VA_01_a_client_with_nothing_to_warm_logs_no_prewarm():
    llm, _, attempts = make(FakeClient(can_warm=False))
    run(llm.prewarm())
    assert attempts == []  # a prewarm row means a connection really was opened ahead of the call


def test_VA_01_a_failed_prewarm_never_raises():
    llm, _, attempts = make(FakeClient(warm_error=ApiError(503, "UNAVAILABLE")))
    assert run(llm.prewarm()) is True  # a call was made; its failure is logged, not raised
    assert attempts[0]["outcome"] == "error"


def test_VA_01_thinking_is_configuration():
    def level_for(thinking):
        client = FakeClient(["x"])
        llm = FastLLM(lambda: client, thinking=thinking)
        run(llm.generate("sys", "q"))
        return client.thinking[0]

    assert level_for("off") == "off" and level_for("minimal") == "minimal"


def test_VA_01_fast_thinking_is_configuration(monkeypatch):
    monkeypatch.setattr("bot.config.load_dotenv", lambda path=None: None)  # a developer's own .env must not leak in
    monkeypatch.delenv("FAST_THINKING", raising=False)
    assert Config.from_env().fast_thinking == "off"
    monkeypatch.setenv("FAST_THINKING", "minimal")
    assert Config.from_env().fast_thinking == "minimal"


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


@pytest.mark.parametrize("code", [401, 403, 404])
def test_VA_01_prewarm_switches_itself_off_when_the_client_cannot_warm(code):
    now = [0.0]
    client = FakeClient(warm_error=ApiError(code, "UNAUTHENTICATED"))
    llm, _, _ = make(client, clock=lambda: now[0])

    async def go():
        first = await llm.prewarm()
        now[0] += 60
        return first, await llm.prewarm()

    first, second = run(go())
    assert first is True and second is False and client.warms == 1  # never asked again: it can only fail
