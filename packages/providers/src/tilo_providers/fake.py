"""tilo_providers.fake — deterministic canned-response ModelProvider (PL-02,
PRD 6.6 "Record and replay" row: "UI work uses a fake provider"). The same
request always yields the same response (stable UI/fixture work); different
prompts yield different text (so mocked cards, chat turns etc. never look
identical). No network, no recordings — just a hash of the prompt."""

from __future__ import annotations

import hashlib
import math
from collections.abc import Iterator

from tilo_providers.interfaces import (
    Capability,
    EmbedRequest,
    EmbedResponse,
    GenerateRequest,
    GenerateResponse,
    ModelProvider,
    PriceQuote,
)

_DEFAULT_CAPS = frozenset({Capability.JSON, Capability.TOOLS})
_DEFAULT_PRICE = PriceQuote(input=0.0, output=0.0)  # UI/fixture work never meters real spend


def _canned_text(prompt: str, media: list[str] | None = None) -> str:
    # A short stable digest keeps two different prompts from ever colliding,
    # while the same prompt always reproduces byte-for-byte the same text.
    # LW-06: a media part's sha256 (never its bytes) is part of the digest, so two files give two replies
    digest = hashlib.sha256("\n".join([prompt, *(media or [])]).encode("utf-8")).hexdigest()[:8]
    return f"[fake:{digest}] {prompt}"


class FakeModelProvider(ModelProvider):
    def __init__(
        self,
        profile_id: str = "fake",
        caps: set[Capability] | None = None,
        price: PriceQuote | None = None,
        usage: dict[str, int] | None = None,
    ) -> None:
        self._profile_id = profile_id
        self._caps = set(caps) if caps is not None else set(_DEFAULT_CAPS)
        self._price = price if price is not None else _DEFAULT_PRICE
        self._usage = usage  # None: no usage, so token counts and cached tokens read as unknown (EFF-04)

    def generate(self, request: GenerateRequest) -> GenerateResponse:
        usage = dict(self._usage) if self._usage is not None else None
        return GenerateResponse(
            text=_canned_text(request.prompt, [p.sha256 or "" for p in request.parts or ()]),
            profile_id=self._profile_id,
            usage=usage,
        )

    def stream(self, request: GenerateRequest) -> Iterator[GenerateResponse]:
        yield self.generate(request)

    def embed(self, request: EmbedRequest) -> EmbedResponse:
        if not isinstance(request, EmbedRequest):  # older provider tests still exercise the pre-RT-05 raw shape
            return {"vectors": [[0.0] * 8], "profile_id": self._profile_id}  # type: ignore[return-value]
        vectors: list[list[float]] = []
        for value in request.texts:
            seed = f"{request.task}\0{value}".encode()
            numbers: list[float] = []
            for counter in range((request.dimensions + 7) // 8):
                digest = hashlib.sha256(seed + counter.to_bytes(4, "big")).digest()
                numbers.extend(int.from_bytes(digest[i : i + 4], "big") / 0xFFFFFFFF * 2 - 1 for i in range(0, 32, 4))
            numbers = numbers[: request.dimensions]
            length = math.sqrt(sum(number * number for number in numbers))
            vectors.append([number / length for number in numbers])
        return EmbedResponse(vectors=vectors, profile_id=self._profile_id)

    def count_tokens(self, text: str) -> int:
        return len(text.split())

    def capabilities(self) -> set[Capability]:
        return set(self._caps)

    def price(self) -> PriceQuote:
        return self._price
