"""tilo_providers.media -- media parts on a `GenerateRequest` (LW-06, ADR-0029 decision 6; FR-INT-02). A part is a file
a model reads natively: an image, a PDF, audio or video. Media is untrusted input, so every rule here refuses rather
than coerces, and nothing here ever puts the bytes anywhere but the request itself:

- the declared MIME type must be on a short allow-list (exact, lower case, no parameters) and the leading bytes must
  match it (magic numbers);
- bytes are capped per part, per request and in parts per request;
- `sha256` is computed here from the bytes; a caller's value is only checked against it, never trusted;
- `repr`, `model_dump` and validation errors leave the bytes out (`data` is excluded from the dump, which is what
  recordings are keyed on: the sha256, never the bytes), and no message below ever quotes content;
- a GCS URI part is typed but refused until ADR-0018 T8 gives it a reader.

Billing never uses the estimates here: they are upper bounds for the pre-flight EFF-03 cap check and the PL-03 budget
check (`estimate_tokens`); the reported usage is what is billed."""

from __future__ import annotations

import hashlib
import math
import re
from collections.abc import Callable, Sequence
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator

from tilo_providers.errors import RequestError

MAX_PARTS = 10  # FR-INT-01: at most 10 files a unit
MAX_PART_BYTES = 10 * 1024 * 1024
MAX_TOTAL_BYTES = 14 * 1024 * 1024  # inline data rides base64 (x4/3) under Gemini's 20 MB request limit
MAX_PDF_PAGES = 100
MAX_SECONDS = 3600.0
# Floors on the bytes a second of audio/video can take: a part claiming more seconds than its size could ever hold
# is not a problem, one claiming fewer is raised to what its size implies, so a declared duration cannot slip a
# long file under an EFF-03 cap (BQ-LW6-2).
_MIN_BYTES_PER_SECOND = {"audio": 4_000, "video": 20_000}
_SHA256_RE = re.compile(r"[0-9a-f]{64}")
_GCS_URI_RE = re.compile(r"gs://[a-z0-9][a-z0-9._-]{1,220}/[^\s\x00-\x1f\x7f]{1,1000}")
_PAGE_RE = re.compile(rb"/Type\s*/Page(?![A-Za-z])")

# kind -> the providers.schema capability value it needs
CAPABILITY_FOR_KIND = {"image": "vision", "document": "documents", "audio": "audio", "video": "video"}


def _riff(kind: bytes) -> Callable[[bytes], bool]:
    return lambda d: d[:4] == b"RIFF" and d[8:12] == kind


# mime type -> (kind, does the leading bytes match). The allow-list: anything else is refused.
_TYPES: dict[str, tuple[str, Callable[[bytes], bool]]] = {
    "application/pdf": ("document", lambda d: d.startswith(b"%PDF-")),
    "image/png": ("image", lambda d: d.startswith(b"\x89PNG\r\n\x1a\n")),
    "image/jpeg": ("image", lambda d: d.startswith(b"\xff\xd8\xff")),
    "image/webp": ("image", _riff(b"WEBP")),
    "audio/wav": ("audio", _riff(b"WAVE")),
    "audio/mpeg": ("audio", lambda d: d.startswith(b"ID3") or (len(d) > 1 and d[0] == 0xFF and d[1] & 0xE0 == 0xE0)),
    "audio/flac": ("audio", lambda d: d.startswith(b"fLaC")),
    "audio/ogg": ("audio", lambda d: d.startswith(b"OggS")),
    "video/mp4": ("video", lambda d: d[4:8] == b"ftyp"),
    "video/webm": ("video", lambda d: d.startswith(b"\x1a\x45\xdf\xa3")),
}
ACCEPTED_MIME_TYPES = frozenset(_TYPES)
IMAGE_ONLY_PROVIDERS = frozenset({"openai_compat"})  # chat completions: image_url parts only (LW-06)


def kind_of(mime_type: str) -> str:
    """image, document, audio or video; a type off the allow-list is refused."""
    if mime_type not in _TYPES:  # exact: no case folding, no parameters, no aliases
        shown = mime_type[:60] if isinstance(mime_type, str) else type(mime_type).__name__
        raise RequestError(f"LW-06: media type {shown!r} is not accepted; accepted: {', '.join(sorted(_TYPES))}")
    return _TYPES[mime_type][0]


def _inspect(mime_type: str, data: bytes) -> str:
    """The checks every byte part passes (size, magic number); returns the sha256 computed from the bytes."""
    kind_of(mime_type)
    if not data:
        raise RequestError("LW-06: a media part has no bytes")
    if len(data) > MAX_PART_BYTES:
        raise RequestError(f"LW-06: a media part is {len(data)} bytes, over the {MAX_PART_BYTES} byte cap")
    if not _TYPES[mime_type][1](data):
        raise RequestError(f"LW-06: the bytes of a media part do not match its declared type {mime_type!r}")
    return hashlib.sha256(data).hexdigest()


class MediaPart(BaseModel):
    """One media file on a request: `data` (bytes) or `uri` (gs://, refused for now), its MIME type and a sha256.
    `seconds` (audio, video; required) and `pages` (PDF; optional) are declared sizes used only for the pre-flight
    estimate. Build one with `MediaPart(mime_type=..., data=...)`; `sha256` and `size` are filled in from the bytes."""

    model_config = ConfigDict(extra="forbid", frozen=True, hide_input_in_errors=True)
    mime_type: str = Field(strict=True, max_length=100)
    data: bytes | None = Field(default=None, strict=True, repr=False, exclude=True)
    uri: str | None = Field(default=None, strict=True, max_length=1300)
    sha256: str | None = Field(default=None, strict=True, max_length=64)
    size: int | None = None
    seconds: float | None = Field(default=None, gt=0, le=MAX_SECONDS)
    pages: int | None = Field(default=None, ge=1, le=MAX_PDF_PAGES)

    @model_validator(mode="after")
    def _validated(self) -> MediaPart:
        kind = kind_of(self.mime_type)
        if (self.data is None) == (self.uri is None):
            raise RequestError("LW-06: a media part carries its bytes or a URI, exactly one")
        if self.size is not None and self.data is None:
            raise RequestError("LW-06: a URI media part cannot state a size")
        if (self.seconds is None) == (kind in ("audio", "video")):
            raise RequestError("LW-06: seconds is required for audio and video parts and allowed only for them")
        if self.pages is not None and self.mime_type != "application/pdf":
            raise RequestError("LW-06: pages is allowed only for PDF parts")
        if self.data is not None:
            digest = _inspect(self.mime_type, self.data)
            if self.sha256 is not None and self.sha256 != digest:
                raise RequestError("LW-06: the stated sha256 does not match the bytes")
            object.__setattr__(self, "sha256", digest)  # frozen: set once, here, by code
            object.__setattr__(self, "size", len(self.data))
        elif self.sha256 is None or not _SHA256_RE.fullmatch(self.sha256) or not _GCS_URI_RE.fullmatch(self.uri or ""):
            raise RequestError("LW-06: a URI media part needs a gs:// URI and a lower-case hex sha256")
        return self

    @property
    def kind(self) -> str:
        return kind_of(self.mime_type)


def check_parts(parts: Sequence[MediaPart] | None) -> Sequence[MediaPart] | None:
    """The request-level gate the router and every adapter run: part count, total bytes, URI parts refused, and each
    part's bytes checked again against its type and sha256 (a `model_copy(update=...)` skips model validation)."""
    if not parts:
        return parts
    if len(parts) > MAX_PARTS:
        raise RequestError(f"LW-06: {len(parts)} media parts, over the cap of {MAX_PARTS} a request")
    total = 0
    for part in parts:
        if part.data is None:
            raise RequestError("LW-06: GCS URI media parts are not supported yet (they need ADR-0018 T8); send bytes")
        if _inspect(part.mime_type, part.data) != part.sha256:
            raise RequestError("LW-06: a media part's sha256 does not match its bytes")
        total += len(part.data)
    if total > MAX_TOTAL_BYTES:
        raise RequestError(f"LW-06: media parts total {total} bytes, over the cap of {MAX_TOTAL_BYTES} a request")
    return parts


def capabilities_needed(parts: Sequence[MediaPart] | None) -> set[str]:
    return {CAPABILITY_FOR_KIND[p.kind] for p in parts or ()}


def provider_takes(provider: str, part: MediaPart) -> bool:
    return part.kind == "image" or provider not in IMAGE_ONLY_PROVIDERS


def estimate_tokens(parts: Sequence[MediaPart] | None, media_tokens: Any) -> tuple[int, int]:
    """(tokens of every part, of which audio tokens): an upper bound from a profile's `media_tokens`, for EFF-03 and
    PL-03 before sending. Images cost `image`; a PDF `pdf_page` for the larger of its declared pages and the page
    objects found in its bytes; audio and video `*_per_second` for the larger of the declared seconds and what the
    size implies at the floor bitrate. Billing uses the reported usage, never this."""
    total = audio = 0
    for part in parts or ():
        if part.kind == "image":
            tokens = media_tokens.image
        elif part.kind == "document":
            pages = max(part.pages or 0, len(_PAGE_RE.findall(part.data or b"")), 1)
            tokens = pages * media_tokens.pdf_page
        else:
            floor = math.ceil((part.size or 0) / _MIN_BYTES_PER_SECOND[part.kind])
            seconds = math.ceil(max(part.seconds or 0, floor))
            tokens = seconds * (
                media_tokens.audio_per_second if part.kind == "audio" else media_tokens.video_per_second
            )
        total += tokens
        audio += tokens if part.kind == "audio" else 0
    return total, audio
