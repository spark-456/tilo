"""tilo_providers.interfaces — provider-layer contracts (PRD 6.4, 12.5). One
ABC per concern; adapters (P0-05) implement these, the router (P0-06)
returns them. Business code asks the router for a role, never a model id
(PL-01). Kept thin: request/response payloads are pydantic models."""

from __future__ import annotations

import enum
from abc import ABC, abstractmethod
from collections.abc import Iterator
from typing import Any

from pydantic import BaseModel, ConfigDict


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


class GenerateRequest(BaseModel):  # one ModelProvider.generate() / .stream() call
    model_config = ConfigDict(extra="forbid")
    prompt: str
    system: str | None = None
    max_output_tokens: int | None = None
    tools: list[dict[str, Any]] | None = None


class GenerateResponse(BaseModel):  # one generate() result, or one stream() chunk
    model_config = ConfigDict(extra="forbid")
    text: str | None  # None for a tool-call-only turn with no text content (PL-02, ticket P0-05)
    profile_id: str
    tool_calls: list[dict[str, Any]] | None = None  # PL-02 tool calling: [{"name": ..., "args": {...}}]
    usage: dict[str, int] | None = None  # PL-02 usage tokens: {"input_tokens", "output_tokens", "total_tokens"}


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


class SearchProvider(ABC):  # PRD 6.1: grounded search
    @abstractmethod
    def search(self, query: str, **kwargs: Any) -> Any: ...


class SafetyProvider(ABC):  # PRD 10.4: safety screening, e.g. "no safety flags" conditions
    @abstractmethod
    def check(self, text: str, **kwargs: Any) -> Any: ...


class SpeechProvider(ABC):  # FR-INT-14, FR-CHN-16: voice intake transcription
    @abstractmethod
    def transcribe(self, audio: bytes, **kwargs: Any) -> Any: ...


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
