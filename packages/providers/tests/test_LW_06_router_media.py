"""LW-06 (ADR-0029 decisions 1 and 6, EFF-03, PL-03): the router picks a candidate by each media part's capability,
refuses a profile without `media_tokens` before sending (recorded as a fallback), adds the media estimate to the EFF-03
cap check and the PL-03 price, charges audio tokens at `audio_input`, refuses URI parts and parts that no longer match
their sha256, and replays a recorded call by the files' sha256."""

from __future__ import annotations

import json
import pathlib
from collections.abc import Iterator
from typing import Any

import pytest
import yaml
from tilo_providers.config import ProviderConfigError, ProvidersConfig, load_providers_config
from tilo_providers.errors import MissingCapabilityError
from tilo_providers.interfaces import Capability, GenerateRequest, GenerateResponse, ModelProvider, PriceQuote
from tilo_providers.media import MediaPart
from tilo_providers.replay import recording_key
from tilo_providers.router import (
    BudgetExceededError,
    Router,
    RouterExhaustedError,
    RouterRequestError,
    TokenCapExceededError,
)

PNG = b"\x89PNG\r\n\x1a\n" + b"image-bytes"
PDF = b"%PDF-1.7\n/Type /Page\n/Type /Page\n"  # two pages
WAV = b"RIFF\x00\x00\x00\x00WAVE" + b"audio-bytes"
MEDIA_TOKENS = {"image": 1000, "pdf_page": 100, "audio_per_second": 10, "video_per_second": 50}
CREDIT = 0.005


def credits(tokens_in: int, tokens_out: int, audio: int = 0) -> float:
    """Fake prices: input 1.0, output 2.0, audio_input 3.0 per million tokens."""
    return ((tokens_in - audio) * 1.0 + audio * 3.0 + tokens_out * 2.0) / 1e6 / CREDIT


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    for name in ("LIVE", "TILO_RECORD", "K_SERVICE", "CLOUD_RUN_JOB", "GOOGLE_LOCATION"):
        monkeypatch.delenv(name, raising=False)


def make_config(tmp_path: pathlib.Path, role: dict[str, Any]) -> ProvidersConfig:
    google = {"provider": "google", "context": 1000}
    models = {
        "example": True,
        "profiles": {
            "blind": {**google, "model": "example-blind", "caps": ["json"], "media_tokens": MEDIA_TOKENS},
            "nomt": {**google, "model": "example-nomt", "caps": ["json", "vision", "documents", "audio"]},
            "plain": {
                **google,
                "model": "example-plain",
                "caps": ["json", "vision", "documents"],
                "media_tokens": MEDIA_TOKENS,
            },
            "hearing": {
                **google,
                "model": "example-hearing",
                "caps": ["json", "vision", "documents", "audio"],
                "media_tokens": MEDIA_TOKENS,
            },
            "compat": {
                "provider": "openai_compat",
                "model": "example-compat",
                "context": 1000,
                "caps": ["json", "vision", "documents", "audio"],
                "media_tokens": MEDIA_TOKENS,
                "base_url": "https://mock.example/v1",
                "api_key_env": "FAKE_COMPAT_KEY",
            },
        },
        "roles": {"reader": {"primary": "plain", "fallback": "plain", **role}},
        "rules": {"deny": []},
    }
    rates = {"input": 1.0, "output": 2.0}
    prices = {
        "status": "set",
        "effective_date": "2026-10-01",
        "source": "Fake price sheet for tests.",
        "currency": "USD",
        "credit_usd": CREDIT,
        "profiles": {
            "blind": rates,
            "nomt": {**rates, "audio_input": 3.0},
            "plain": rates,
            "hearing": {**rates, "audio_input": 3.0},
            "compat": rates,
        },
    }
    (tmp_path / "models.yaml").write_text(yaml.safe_dump(models), encoding="utf-8")
    (tmp_path / "prices.yaml").write_text(yaml.safe_dump(prices), encoding="utf-8")
    return load_providers_config(tmp_path / "models.yaml", tmp_path / "prices.yaml", env={})


class Stub(ModelProvider):
    def __init__(self, profile_id: str, usage: dict[str, int] | None = None) -> None:
        self.profile_id, self.usage, self.requests = profile_id, usage, []

    def generate(self, request: GenerateRequest) -> GenerateResponse:
        self.requests.append(request)
        return GenerateResponse(text="ok", profile_id=self.profile_id, usage=self.usage)

    def stream(self, request: GenerateRequest) -> Iterator[GenerateResponse]:
        yield self.generate(request)

    def embed(self, request: Any) -> Any:
        raise NotImplementedError

    def count_tokens(self, text: str) -> int:
        return len(text.split())

    def capabilities(self) -> set[Capability]:
        return set()

    def price(self) -> PriceQuote:
        raise NotImplementedError


class Fleet:
    """provider_for_profile that builds a Stub per profile and remembers which profiles were ever built."""

    def __init__(self, usage: dict[str, dict[str, int]] | None = None) -> None:
        self.usage, self.built = usage or {}, {}

    def __call__(self, profile_id: str) -> Stub:
        return self.built.setdefault(profile_id, Stub(profile_id, self.usage.get(profile_id)))


def part(mime: str = "image/png", data: bytes | None = None, **extra: Any) -> MediaPart:
    data = data or {"image/png": PNG, "application/pdf": PDF, "audio/wav": WAV}[mime]
    if mime.startswith("audio/"):
        extra.setdefault("seconds", 10.0)
    return MediaPart(mime_type=mime, data=data, **extra)


def ask(*parts: MediaPart, prompt: str = "read this please") -> GenerateRequest:
    return GenerateRequest(prompt=prompt, parts=list(parts), max_output_tokens=100)


def reader(tmp_path, *, cascade=None, fleet=None, **role):
    config = make_config(tmp_path, {**({"cascade": cascade} if cascade else {}), **role})
    fleet = fleet or Fleet()
    return Router(config, provider_for_profile=fleet), fleet


def test_LW_06_a_candidate_is_picked_by_the_capability_of_each_part(tmp_path):
    router, fleet = reader(tmp_path, cascade=["blind", "plain", "hearing"])
    result = router.generate("reader", ask(part("image/png"), part("application/pdf")))
    assert [a.profile_id for a in result.attempts] == ["plain"], "blind has no vision: never built, never tried"
    assert list(fleet.built) == ["plain"]
    heard = router.generate("reader", ask(part("audio/wav")))
    assert [a.profile_id for a in heard.attempts] == ["hearing"], "only a profile with audio takes audio"


def test_LW_06_no_candidate_with_the_capability_refuses_without_building_anything(tmp_path):
    router, fleet = reader(tmp_path, cascade=["blind", "plain"])
    with pytest.raises(RouterExhaustedError, match="audio"):
        router.generate("reader", ask(part("audio/wav")))
    assert fleet.built == {}


def test_LW_06_a_profile_without_media_tokens_gets_no_media_and_the_fallback_is_recorded(tmp_path):
    router, fleet = reader(tmp_path, cascade=["nomt", "hearing"])
    result = router.generate("reader", ask(part("audio/wav")))
    first, second = result.attempts
    assert (first.profile_id, first.outcome, first.error_type) == ("nomt", "error", "MissingCapabilityError")
    assert (second.profile_id, second.outcome, second.reason) == (
        "hearing",
        "ok",
        "fallback after MissingCapabilityError",
    )
    assert fleet.built["nomt"].requests == [], "nothing was sent to it"
    only, fleet2 = reader(tmp_path, cascade=["nomt"])
    with pytest.raises(RouterExhaustedError):
        only.generate("reader", ask(part("image/png")))
    assert fleet2.built["nomt"].requests == []


def test_LW_06_an_openai_compat_profile_takes_an_image_but_a_pdf_falls_back(tmp_path):
    router, fleet = reader(tmp_path, cascade=["compat", "plain"])
    image = router.generate("reader", ask(part("image/png")))
    assert [a.profile_id for a in image.attempts] == ["compat"]
    pdf = router.generate("reader", ask(part("application/pdf")))
    assert [(a.profile_id, a.error_type) for a in pdf.attempts] == [
        ("compat", "MissingCapabilityError"),
        ("plain", None),
    ]
    assert issubclass(MissingCapabilityError, Exception)


def test_LW_06_an_audio_part_needs_an_audio_input_price(tmp_path):
    config = make_config(tmp_path, {"cascade": ["hearing", "plain"]})
    object.__setattr__(
        config.prices.profiles["hearing"], "audio_input", None
    )  # a profile the sheet gives no audio rate
    router, fleet = Router(config, provider_for_profile=(fleet := Fleet())), fleet
    with pytest.raises(RouterExhaustedError):
        router.generate("reader", ask(part("audio/wav")))
    assert fleet.built["hearing"].requests == [], "audio is never sent where it cannot be priced"


def test_LW_06_media_tokens_count_against_the_role_cap_before_anything_is_sent(tmp_path):
    router, fleet = reader(tmp_path, cascade=["plain"], max_input_tokens=1500)
    router.generate("reader", ask(part("image/png")))  # 1000 + 3 words
    with pytest.raises(TokenCapExceededError):
        router.generate("reader", ask(part("image/png"), part("image/png")))  # 2000 + 3
    assert len(fleet.built["plain"].requests) == 1, "the over-cap request was never sent"
    long_text = " ".join(["word"] * 600)
    with pytest.raises(TokenCapExceededError):  # text alone fits, text plus the image does not
        router.generate("reader", ask(part("image/png"), prompt=long_text))


def test_LW_06_media_tokens_are_priced_before_the_call_and_the_reported_usage_is_charged_after(tmp_path):
    fleet = Fleet({"plain": {"input_tokens": 1500, "output_tokens": 10, "total_tokens": 1510}})
    router, _ = reader(tmp_path, cascade=["plain"], fleet=fleet)
    estimate = credits(1003 + 3, 100)  # prompt words + image estimate in, then max_output_tokens out
    with pytest.raises(BudgetExceededError):
        router.generate("reader", ask(part("image/png")), budget=estimate * 0.99)
    assert fleet.built == {} or fleet.built["plain"].requests == [], "over the budget is never sent"
    result = router.generate("reader", ask(part("image/png")), budget=estimate * 1.01)
    assert result.budget == pytest.approx(estimate * 1.01 - credits(1500, 10)), "the reported usage is billed"
    assert result.attempts[0].tokens_in == 1500


def test_LW_06_audio_input_tokens_are_charged_at_the_audio_rate_reported_or_estimated(tmp_path):
    reported = Fleet(
        {"hearing": {"input_tokens": 1000, "output_tokens": 10, "total_tokens": 1010, "audio_tokens": 400}}
    )
    router, _ = reader(tmp_path, cascade=["hearing"], fleet=reported)
    result = router.generate("reader", ask(part("audio/wav")), budget=100)
    assert result.budget == pytest.approx(100 - credits(1000, 10, audio=400))
    assert result.attempts[0].tokens_audio == 400
    unreported = Fleet({"hearing": {"input_tokens": 1000, "output_tokens": 10, "total_tokens": 1010}})
    router, _ = reader(tmp_path, cascade=["hearing"], fleet=unreported)
    result = router.generate("reader", ask(part("audio/wav")), budget=100)
    # 10 s at 10 tokens a second is 100 audio tokens (the estimate, an upper bound); the reply says nothing
    assert result.budget == pytest.approx(100 - credits(1000, 10, audio=100))
    assert result.attempts[0].tokens_audio is None, "unknown stays unknown on the attempt"
    no_audio = Fleet({"plain": {"input_tokens": 1000, "output_tokens": 10, "total_tokens": 1010, "audio_tokens": 900}})
    router, _ = reader(tmp_path, cascade=["plain"], fleet=no_audio)
    result = router.generate("reader", ask(part("image/png")), budget=100)
    assert result.budget == pytest.approx(100 - credits(1000, 10)), "a request with no audio part has no audio tokens"


def test_LW_06_the_estimate_prices_audio_at_the_audio_rate(tmp_path):
    router, fleet = reader(tmp_path, cascade=["hearing"])
    estimate = credits(103 + 3, 100, audio=100)  # 100 audio tokens (10 s), 3 prompt words
    with pytest.raises(BudgetExceededError):
        router.generate("reader", ask(part("audio/wav")), budget=estimate * 0.99)
    router.generate("reader", ask(part("audio/wav")), budget=estimate * 1.01)


def test_LW_06_uri_parts_and_parts_that_no_longer_match_their_sha256_are_refused_before_a_candidate(tmp_path):
    router, fleet = reader(tmp_path, cascade=["plain"])
    uri = MediaPart(mime_type="application/pdf", uri="gs://tilo-bucket/a.pdf", sha256="c" * 64)
    with pytest.raises(RouterRequestError, match="ADR-0018 T8"):
        router.generate("reader", ask(uri))
    swapped = part("image/png").model_copy(update={"data": PNG + b"other"})
    with pytest.raises(Exception, match="sha256"):  # building the request already re-validates the part ...
        ask(swapped)
    forged = GenerateRequest.model_construct(prompt="read this", parts=[swapped])  # ... so skip validation entirely
    with pytest.raises(RouterRequestError, match="sha256"):
        router.generate("reader", forged)
    with pytest.raises(RouterRequestError):
        router.stream("reader", ask(uri))
    assert fleet.built == {}


def test_LW_06_a_streamed_call_is_checked_and_priced_the_same_way(tmp_path):
    router, fleet = reader(tmp_path, cascade=["plain"], max_input_tokens=1500)
    with pytest.raises(TokenCapExceededError):
        list(router.stream("reader", ask(part("image/png"), part("image/png"))))
    chunks = list(router.stream("reader", ask(part("image/png"))))
    assert chunks and fleet.built["plain"].requests[-1].parts is not None


def test_LW_06_cost_usd_prices_audio_apart_from_cached_and_plain_input(tmp_path):
    config = make_config(tmp_path, {})
    usd = config.cost_usd("hearing", 1000, 10, cached=0, audio=400)
    assert usd == pytest.approx((600 * 1.0 + 400 * 3.0 + 10 * 2.0) / 1e6)
    with pytest.raises(ProviderConfigError, match="audio_input"):
        config.cost_usd("plain", 1000, 10, audio=1)
    with pytest.raises(ValueError, match="together"):
        config.cost_usd("hearing", 1000, 10, cached=700, audio=400)
    assert config.price("hearing").audio_input == 3.0 and config.price("plain").audio_input is None


def test_LW_06_a_recorded_call_replays_by_the_files_sha256_and_a_changed_file_misses(tmp_path):
    config = make_config(tmp_path, {"cascade": ["plain"]})
    fixtures = tmp_path / "fixtures"
    request = ask(part("image/png"))
    sent = request.model_copy(update={"prompt": request.prompt})
    key = recording_key("reader", "plain", sent)
    path = fixtures / "model-recordings" / "reader" / f"{key}.json"
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps({"response": {"text": "from the recording", "profile_id": "plain"}}), encoding="utf-8")
    assert PNG.hex() not in key and b"image-bytes".decode() not in path.read_text()
    router = Router(config, fixtures_dir=fixtures)
    assert router.generate("reader", request).response.text == "from the recording"
    with pytest.raises(RouterExhaustedError):  # other bytes: another key, no recording
        router.generate("reader", ask(part("image/png", PNG + b"x")))
