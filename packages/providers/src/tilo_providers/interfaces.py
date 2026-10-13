"""tilo_providers.interfaces — provider-layer contracts (PRD 6.4, 12.5). One
ABC per concern; adapters (P0-05) implement these, the router (P0-06)
returns them. Business code asks the router for a role, never a model id
(PL-01). Kept thin: request/response payloads are pydantic models."""

from __future__ import annotations

import enum
from abc import ABC, abstractmethod
from collections.abc import Iterator
from typing import Any, Literal, TypedDict

from pydantic import BaseModel, ConfigDict, Field

from tilo_providers.errors import NotConfigured, ProviderError, RequestError
from tilo_providers.media import MAX_PARTS, MediaPart


class Capability(enum.StrEnum):
    """Exactly contracts/providers.schema.json $defs.capability's enum."""

    JSON = "json"
    TOOLS = "tools"
    VISION = "vision"
    AUDIO = "audio"
    THINKING = "thinking"
    COMPUTER_USE = "computer_use"
    GROUNDING = "grounding"
    CODE_EXECUTION = "code_execution"
    VIDEO = "video"  # providers 1.3.0, ADR-0029 decision 6
    DOCUMENTS = "documents"  # a PDF read natively (FR-INT-02); providers 1.3.0, ADR-0029 decision 6


class GenerateRequest(BaseModel):  # one ModelProvider.generate() / .stream() call
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)  # LW-06: an error never echoes media content
    prompt: str
    system: str | None = None
    max_output_tokens: int | None = None
    tools: list[dict[str, Any]] | None = None
    json_mode: bool = False  # PL-02 structured output: force JSON-only output, no schema
    response_schema: dict[str, Any] | None = None  # PL-02 structured output: JSON output validated against this schema
    # google only; None sends no thinking config. A pattern, not a Literal, so callers' type checkers stay quiet.
    thinking_level: str | None = Field(default=None, pattern="^(minimal|low|medium|high)$")
    # LW-06 media input (ADR-0029): images, PDFs, audio, video the model reads natively. Untrusted: see `media`.
    parts: list[MediaPart] | None = Field(default=None, max_length=MAX_PARTS)


class GenerateResponse(BaseModel):  # one generate() result, or one stream() chunk
    model_config = ConfigDict(extra="forbid")
    text: str | None = None  # None for a tool-call-only turn with no text content (PL-02, ticket P0-05)
    profile_id: str
    tool_calls: list[dict[str, Any]] | None = None  # PL-02 tool calling: [{"name": ..., "args": {...}}]
    # PL-02 usage tokens: {"input_tokens", "output_tokens", "total_tokens"}, plus "cached_tokens" (a part of
    # input_tokens) only when the provider reported a cached count; left out means unknown (EFF-04, ADR-0022).
    usage: dict[str, int] | None = None


def cached_tokens_or_none(value: Any, input_tokens: Any) -> int | None:
    """EFF-04 (ADR-0022): a provider's cached-token count if it is a whole number from 0 to `input_tokens`, else None
    (the caller leaves `usage["cached_tokens"]` out, so EV-16 can never refuse an event over a misreport)."""
    if isinstance(value, bool) or not isinstance(value, int) or isinstance(input_tokens, bool):
        return None
    return value if isinstance(input_tokens, int) and 0 <= value <= input_tokens else None


class PriceQuote(BaseModel):  # standard list price, US dollars per million tokens (PL-06)
    model_config = ConfigDict(extra="forbid")
    input: float
    output: float


class ModelProvider(ABC):  # PRD 6.4: generate, stream, embed, count_tokens, capabilities, price
    @abstractmethod
    def generate(self, request: GenerateRequest) -> GenerateResponse: ...
    @abstractmethod
    def stream(self, request: GenerateRequest) -> Iterator[GenerateResponse]: ...
    @abstractmethod
    def embed(self, request: Any) -> Any: ...
    @abstractmethod
    def count_tokens(self, text: str) -> int: ...
    @abstractmethod
    def capabilities(self) -> set[Capability]: ...
    @abstractmethod
    def price(self) -> PriceQuote: ...

    def redact(self, text: str) -> str:
        """Scrubs this provider's own secret material (an API key value, an
        Authorization header) out of `text` before it leaves the process --
        e.g. a record-and-replay recording (PRD 16.1 rule 4). Defence in
        depth for the case a live endpoint echoes a secret back into
        ordinary model output, which never reaches `GenerateResponse`'s own
        fields but could still land in `text`. Default: no-op; a provider
        holding a raw secret (`openai_compat_adapter`) overrides it."""
        return text


class SearchProvider(ABC):  # PRD 6.1: grounded search; the typed result is `tilo_providers.search.SearchResult` (LW-05)
    @abstractmethod
    def search(self, query: str, **kwargs: Any) -> Any: ...

    def redact(self, text: str) -> str:  # same role as ModelProvider.redact (PRD 16.1 rule 4)
        return text


class SafetyResult(TypedDict):  # CC-SP-47: the one fixed SafetyProvider.check() result
    flagged: bool
    reason: str | None


NATIVE_MIME_TYPES = frozenset({"application/pdf", "image/png", "image/jpeg"})  # issue #47 item 2


def native_mime_type(content: bytes | None, mime_type: str | None) -> str | None:
    """Validates the native-file arguments; returns the normalised media type,
    or None for a text-only check. Raises `RequestError` for anything that
    cannot be screened, so an unsupported file never passes as clean."""
    if content is None and mime_type is None:
        return None
    if content is None or mime_type is None:
        raise RequestError("FR-INT-02: a native-file safety check needs both content= and mime_type=")
    if not isinstance(content, bytes):
        raise RequestError("FR-INT-02: a native-file safety check needs content= as bytes")
    normalised = mime_type.strip().lower()
    if normalised not in NATIVE_MIME_TYPES:
        raise RequestError(f"FR-INT-02: the safety provider cannot screen media type {mime_type!r}; refused")
    return normalised


class SafetyProvider(ABC):  # PRD 10.4, 16.3 item 2: screens intake, tool output, mail and model output
    def check(self, text: str, *, content: bytes | None = None, mime_type: str | None = None) -> SafetyResult:
        """Screens `text`, or a native file (`check("", content=..., mime_type=...)`,
        no text extracted). Template method: the media-type gate runs here, in
        the base class, so no adapter can skip it. A media type that cannot be
        screened raises `RequestError`, never `flagged: False` (fails closed).
        Adapters implement `_check`, which receives the normalised media type."""
        normalised = native_mime_type(content, mime_type)
        return self._check(text, content=content, mime_type=normalised)

    @abstractmethod
    def _check(self, text: str, *, content: bytes | None, mime_type: str | None) -> SafetyResult: ...

    def redact(self, text: str) -> str:  # same role as ModelProvider.redact (PRD 16.1 rule 4)
        return text


class EvalItem(BaseModel):
    """One instance to judge. `baseline_response` is for pairwise requests only."""

    model_config = ConfigDict(extra="forbid")

    id: str = Field(pattern=r"^[A-Za-z0-9_-]{1,64}$")
    prompt: str
    context: str = ""
    response: str
    baseline_response: str | None = None


class EvalRequest(BaseModel):
    """One instance against one metric (ADR-0033): a call is one quote and one charge."""

    model_config = ConfigDict(extra="forbid")

    metric: str = Field(pattern=r"^[a-z][a-z0-9_]{0,40}$")
    kind: Literal["pairwise", "pointwise"]
    template: str  # rubric text from prompts/eval_judge/ (PL-04), sent as is
    item: EvalItem


class EvalScore(BaseModel):
    """`choice` is set for pairwise, `score` (finite) for pointwise; `explanation` is already redacted and capped."""

    model_config = ConfigDict(extra="forbid")

    choice: Literal["candidate", "baseline", "tie"] | None = None
    score: float | None = Field(default=None, allow_inf_nan=False)
    explanation: str = Field(default="", max_length=500)


class EvalProvider(ABC):  # ADR-0033: the Gen AI evaluation service, a sibling of ModelProvider (no usage, no cascade)
    def evaluate(self, request: EvalRequest) -> EvalScore:
        """Template method: kind and fields must agree (`RequestError`, nothing sent), and the result must match the
        kind (`ProviderError`); an unusable judgement fails closed and is never replaced by a default."""
        has_baseline = request.item.baseline_response is not None
        if (request.kind == "pairwise") != has_baseline:
            raise RequestError(
                "VERTEX-EVAL-1: a pairwise request needs a baseline response and a pointwise one has none"
            )
        result = self._evaluate(request)
        if request.kind == "pairwise":
            usable = result.choice is not None and result.score is None
        else:
            usable = result.score is not None and result.choice is None
        if not usable:
            raise ProviderError("VERTEX-EVAL-1: the judgement does not match the request kind; failing closed")
        return result

    @abstractmethod
    def _evaluate(self, request: EvalRequest) -> EvalScore: ...

    def redact(self, text: str) -> str:  # same role as ModelProvider.redact (PRD 16.1 rule 4)
        return text


class SpeechProvider(ABC):  # FR-INT-14, FR-CHN-16: voice intake transcription; FR-MTG-11: and the bot's voice
    @abstractmethod
    def transcribe(self, audio: bytes, **kwargs: Any) -> Any: ...

    def synthesize(self, text: str, *, voice: str | None = None, **kwargs: Any) -> bytes:
        """FR-MTG-11: text to speech, returned as raw 16-bit mono little-endian PCM. The sample rate is not in the
        result: it is `config/voice.yaml`'s `sample_rate` (tilo_providers.voice). Additive and not abstract, so every
        transcribe-only provider still conforms; it says so instead of guessing."""
        raise NotConfigured("FR-MTG-11: this speech provider cannot synthesize speech")

    def synthesize_stream(self, text: str, *, voice: str | None = None, **kwargs: Any) -> Iterator[bytes]:
        """FR-MTG-11: the same PCM as `synthesize`, handed on in pieces as the service produces them, so a caller can
        start playing at the first piece (every piece an even number of bytes). The default is one piece: a provider
        that cannot stream still works; a streaming one (cloud_tts_adapter) overrides it."""
        yield self.synthesize(text, voice=voice, **kwargs)


class RenderProvider(ABC):  # PRD 12.4: PDF/PPTX deliverables rendered from templates
    @abstractmethod
    def render(self, template: str, data: dict[str, Any], **kwargs: Any) -> Any: ...


class HandsProvider(ABC):
    # PRD 12.5: cloud browsers ship this release; extension/desktop/VM Hands
    # plug into the same interface later (FR-CON-13: a second implementation
    # must pass the same conformance check). upload_file/download_file cover
    # "file operations" since Hands needs both directions.
    @abstractmethod
    def navigate(self, url: str) -> Any: ...
    @abstractmethod
    def find_element(self, selector: str) -> Any: ...
    @abstractmethod
    def click(self, ref: Any) -> Any: ...
    @abstractmethod
    def type(self, ref: Any, text: str) -> Any: ...
    @abstractmethod
    def read_accessibility_tree(self) -> Any: ...
    @abstractmethod
    def screenshot(self) -> bytes: ...
    @abstractmethod
    def upload_file(self, ref: Any, path: str) -> Any: ...
    @abstractmethod
    def download_file(self, ref: Any) -> bytes: ...
