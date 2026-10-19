"""LIVE-RUN, 8 Oct 2026: a live run sat silent for 40 minutes (the report printed only at the end), and every model
call took one meter-wide lock, so independent units the harness runs in parallel were served one at a time.

(1) Each model call prints one numbers-only progress line when it finishes. (2) Calls of independent units overlap in
time. (3) The cap still holds: a call is only started with its share reserved, and when what is left cannot cover a
second call beside the first, the second waits for the first to be accounted. Fakes only: no network, no paid call."""

from __future__ import annotations

import threading
from concurrent.futures import ThreadPoolExecutor
from typing import Any

from _live_e2e_lib import live_e2e, network_guard  # noqa: F401  (autouse fixture)
from tilo_providers.config import load_providers_config
from tilo_providers.interfaces import Capability, GenerateRequest, GenerateResponse, ModelProvider, PriceQuote

SECRET_WORDS = "zebra-quartz-prompt-words"


class _Inner(ModelProvider):
    """Answers with fixed usage; `gate` (if any) is a barrier every call must reach while the others are in flight."""

    def __init__(self, profile: str, gate: threading.Barrier | None = None, tokens: int = 10) -> None:
        self.profile, self.gate, self.tokens = profile, gate, tokens
        self.in_flight = self.peak = 0
        self.lock = threading.Lock()

    def generate(self, request: GenerateRequest) -> GenerateResponse:
        with self.lock:
            self.in_flight += 1
            self.peak = max(self.peak, self.in_flight)
        try:
            if self.gate is not None:
                self.gate.wait(timeout=5)  # raises BrokenBarrierError unless the other call is inside at the same time
            return GenerateResponse(
                text="done", profile_id=self.profile, usage={"input_tokens": self.tokens, "output_tokens": self.tokens}
            )
        finally:
            with self.lock:
                self.in_flight -= 1

    def stream(self, request: GenerateRequest) -> Any:
        yield self.generate(request)

    def embed(self, request: Any) -> Any:
        raise NotImplementedError

    def count_tokens(self, text: str) -> int:
        return len(text.split())

    def provider_count_tokens(self, text: str) -> int:
        return self.count_tokens(text)

    def capabilities(self) -> set[Capability]:
        return {Capability.JSON}

    def price(self) -> PriceQuote:
        return PriceQuote(input=0.0, output=0.0)


def _setup(
    cap: float, gate: threading.Barrier | None = None, tokens: int = 10
) -> tuple[Any, Any, Any, dict[str, _Inner]]:
    module = live_e2e()
    config = load_providers_config(module._REPO / "config" / "models.yaml", module._REPO / "config" / "prices.yaml")
    meter = module._Meter(config, cap)
    inners: dict[str, _Inner] = {}

    def providers(role: str, profile: str) -> ModelProvider:
        inner = inners.setdefault(profile, _Inner(profile, gate, tokens))
        return module._Metered(inner, role, profile, meter)

    return module, meter, module._MeteredRouter(config, meter, providers), inners


def _request(max_out: int = 100) -> GenerateRequest:
    return GenerateRequest(prompt=f"write {SECRET_WORDS}", max_output_tokens=max_out)


def test_LIVE_RUN_1_each_model_call_prints_one_numbers_only_progress_line_when_it_finishes() -> None:
    _, meter, router, _ = _setup(1000.0)
    lines: list[str] = []
    meter.progress = lines.append

    router.generate("specialist", _request())
    router.generate("specialist", _request())

    assert len(lines) == 2
    assert lines[0].startswith("progress ") and "stage=run" in lines[0] and "role=specialist" in lines[0]
    assert "calls=1" in lines[0] and "calls=2" in lines[1]
    assert "total_credits=" in lines[1] and "elapsed_s=" in lines[1]
    assert not any(SECRET_WORDS in line or "done" in line.split("elapsed_s")[0] for line in lines), "numbers only"


def test_LIVE_RUN_2_calls_of_independent_units_overlap_in_time() -> None:
    _, meter, router, inners = _setup(1000.0, gate=threading.Barrier(2))

    with ThreadPoolExecutor(2) as pool:
        results = [f.result() for f in [pool.submit(router.generate, "specialist", _request()) for _ in range(2)]]

    assert all(r.response.text == "done" for r in results), "both calls were inside the provider at the same time"
    assert max(i.peak for i in inners.values()) == 2
    assert meter.reserved == 0, "every reservation is released once its call is accounted"


def test_LIVE_RUN_3_the_cap_holds_in_parallel_a_second_call_waits_when_only_one_fits() -> None:
    module, meter, router, inners = _setup(1000.0)
    worst = router._worst_quote("specialist", _request())
    meter.cap = worst * 1.2  # room for one call's worst case, not two

    with ThreadPoolExecutor(2) as pool:
        for future in [pool.submit(router.generate, "specialist", _request()) for _ in range(2)]:
            future.result()

    assert max(i.peak for i in inners.values()) == 1, "the second call waited for the first to be accounted"
    assert meter.total <= meter.cap
    assert meter.reserved == 0


def test_LIVE_RUN_3_a_call_that_cannot_fit_even_alone_still_ends_the_run_at_the_cap() -> None:
    module, meter, router, _ = _setup(1000.0)
    meter.cap = router._worst_quote("specialist", _request()) * 0.1

    try:
        router.generate("specialist", _request())
    except Exception as error:  # noqa: BLE001
        assert type(error).__name__ in ("BudgetExceededError", "RouterExhaustedError")
    else:
        raise AssertionError("a call over the cap was sent")
    assert meter.stop is not None and meter.stop[0] == "stopped_at_cap"
    assert meter.reserved == 0


def test_LIVE_RUN_3_eight_parallel_calls_near_the_cap_never_spend_past_it() -> None:
    _, meter, router, inners = _setup(1000.0, tokens=50)
    worst = router._worst_quote("specialist", _request())
    meter.cap = worst * 4.5  # about four calls' worst case, eight asked for at once

    outcomes: list[str] = []

    def call() -> None:
        try:
            router.generate("specialist", _request())
            outcomes.append("ok")
        except Exception as error:  # noqa: BLE001
            outcomes.append(type(error).__name__)

    with ThreadPoolExecutor(8) as pool:
        for future in [pool.submit(call) for _ in range(8)]:
            future.result()

    assert meter.total <= meter.cap, "the run never spent past --max-credits"
    assert max(i.peak for i in inners.values()) <= 4, "in flight, reservations never exceeded what was left"
    assert meter.reserved == 0
    assert outcomes.count("ok") >= 1 and len(outcomes) == 8


def test_LIVE_RUN_3_a_call_that_fails_releases_its_reservation_and_is_still_metered() -> None:
    module, meter, router, inners = _setup(1000.0)

    class _Boom(_Inner):
        def generate(self, request: GenerateRequest) -> GenerateResponse:
            raise TimeoutError("slow")

    def providers(role: str, profile: str) -> ModelProvider:
        return module._Metered(_Boom(profile), role, profile, meter)

    boom = module._MeteredRouter(meter.config, meter, providers)
    try:
        boom.generate("specialist", _request())
    except Exception:  # noqa: BLE001
        pass
    assert meter.reserved == 0, "a failed or timed-out call gives its reservation back"
    assert meter.total > 0, "a call that raised after it may have been billed is still counted"
    assert meter.failure is not None
