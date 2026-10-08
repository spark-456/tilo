"""tilo_providers.media -- media parts on a `GenerateRequest` (LW-06, ADR-0029 decision 6; FR-INT-02). A part is a file
a model reads natively: an image, a PDF, audio or video. Media is untrusted input, so every rule here refuses rather
than coerces, and nothing here ever puts the bytes anywhere but the request itself:

- the declared MIME type must be on a short allow-list (exact, lower case, no parameters) and the leading bytes must
  match it (magic numbers, and for mp4, webm and ogg the brand, DocType or codec);
- bytes are capped per part, per request and in parts per request;
- `sha256` is computed here from the bytes; a caller's value is only checked against it, never trusted;
- the pages of a PDF are measured here by walking its page tree with a real parser (`pypdf`) under a node budget, never
  read from a caller's number or a text scan; an unreadable PDF, or one over MAX_PDF_PAGES, is refused;
- `repr`, `model_dump` and validation errors leave the bytes out (`data` is excluded from the dump, which is what
  recordings are keyed on: the sha256, never the bytes), and no message below ever quotes content;
- a GCS URI part is typed but refused until ADR-0018 T8 gives it a reader.

Billing never uses the estimates here: they are bounds for the pre-flight EFF-03 cap check and the PL-03 budget check
(`estimate_tokens`); the reported usage is what is billed. Audio and video duration is not measured (no decoder is a
dependency yet): it is bounded from the size at a bitrate below any practical codec, which is a bound for real
recordings and not for digital silence (BQ-LW6-2)."""

from __future__ import annotations

import functools
import hashlib
import io
import math
import re
from collections.abc import Callable, Sequence
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator
from pypdf import PdfReader
from pypdf.generic import DictionaryObject

from tilo_providers.errors import RequestError

MAX_PARTS = 10  # FR-INT-01: at most 10 files a unit
MAX_PART_BYTES = 10 * 1024 * 1024
MAX_TOTAL_BYTES = 14 * 1024 * 1024  # inline data rides base64 (x4/3) under Gemini's 20 MB request limit
MAX_PDF_PAGES = 100
MAX_PDF_NODES = 4 * MAX_PDF_PAGES  # page-tree nodes visited, a shared or cyclic tree counts each visit
MAX_SECONDS = 3600.0  # the most a caller may declare
# Bytes a second of audio/video takes at the very least: below Opus at its lowest rate (about 750 B/s with its Ogg
# framing) and a 16 kbit/s video, so a file of N bytes lasts at most N / this seconds. Silence compressed to nothing is
# the one thing that beats it. The estimate uses the larger of this bound and any declared duration (BQ-LW6-2).
_MIN_BYTES_PER_SECOND = {"audio": 500, "video": 1_000}
_SHA256_RE = re.compile(r"[0-9a-f]{64}")
_GCS_URI_RE = re.compile(r"gs://[a-z0-9][a-z0-9._-]{1,220}/[^\s\x00-\x1f\x7f]{1,1000}")
_SHOWABLE_RE = re.compile(r"[a-z0-9/.+-]{1,60}")

# kind -> the providers.schema capability value it needs
CAPABILITY_FOR_KIND = {"image": "vision", "document": "documents", "audio": "audio", "video": "video"}

_MP4_BRANDS = frozenset({b"isom", b"iso2", b"iso4", b"iso5", b"iso6", b"mp41", b"mp42", b"avc1", b"dash", b"M4V "})
_OGG_CODECS = (b"OpusHead", b"\x01vorbis", b"\x7fFLAC")  # not Theora or Speex


def _riff(kind: bytes) -> Callable[[bytes], bool]:
    return lambda d: d[:4] == b"RIFF" and d[8:12] == kind


def _mpeg_audio(d: bytes) -> bool:
    """ID3 tag, or an MPEG audio frame sync with a real version and layer (an ADTS/AAC sync has layer 0)."""
    if d.startswith(b"ID3"):
        return True
    return len(d) > 1 and d[0] == 0xFF and d[1] & 0xE0 == 0xE0 and (d[1] >> 3) & 3 != 1 and (d[1] >> 1) & 3 != 0


def _ogg(d: bytes) -> bool:
    """An Ogg page whose first packet is an Opus, Vorbis or FLAC header."""
    if not d.startswith(b"OggS") or len(d) < 28:
        return False
    start = 27 + d[26]  # the segment table follows the 27 byte page header
    return any(d[start:].startswith(codec) for codec in _OGG_CODECS)


# mime type -> (kind, does the leading bytes match). The allow-list: anything else is refused.
_TYPES: dict[str, tuple[str, Callable[[bytes], bool]]] = {
    "application/pdf": ("document", lambda d: d.startswith(b"%PDF-")),
    "image/png": ("image", lambda d: d.startswith(b"\x89PNG\r\n\x1a\n")),
    "image/jpeg": ("image", lambda d: d.startswith(b"\xff\xd8\xff")),
    "image/webp": ("image", _riff(b"WEBP")),
    "audio/wav": ("audio", _riff(b"WAVE")),
    "audio/mpeg": ("audio", _mpeg_audio),
    "audio/flac": ("audio", lambda d: d.startswith(b"fLaC")),
    "audio/ogg": ("audio", _ogg),
    "video/mp4": ("video", lambda d: d[4:8] == b"ftyp" and d[8:12] in _MP4_BRANDS),
    "video/webm": ("video", lambda d: d.startswith(b"\x1a\x45\xdf\xa3") and b"\x42\x82\x84webm" in d[:64]),
}
ACCEPTED_MIME_TYPES = frozenset(_TYPES)
IMAGE_ONLY_PROVIDERS = frozenset({"openai_compat"})  # chat completions: image_url parts only (LW-06)


def kind_of(mime_type: str) -> str:
    """image, document, audio or video; a type off the allow-list is refused. The message echoes the declared type
    only if it is a short token of [a-z0-9/.+-], else nothing of it."""
    if mime_type not in _TYPES:  # exact: no case folding, no parameters, no aliases
        shown = f" {mime_type!r}" if isinstance(mime_type, str) and _SHOWABLE_RE.fullmatch(mime_type) else ""
        raise RequestError(f"LW-06: media type{shown} is not accepted; accepted: {', '.join(sorted(_TYPES))}")
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


@functools.lru_cache(maxsize=4)
def pdf_pages(data: bytes) -> int:
    """The number of pages of a PDF, counted by walking its page tree (not its /Count, not a text scan): every node
    without /Kids is a page, whatever its /Type, so object streams and escaped names change nothing. Shared and
    cyclic trees are cut off by the node budget. Refuses an unreadable or encrypted PDF, no pages, or more than
    MAX_PDF_PAGES. Nothing of the file (pypdf's own messages can quote it) reaches an error."""
    pages = nodes = 0
    unreadable = too_many = False
    try:
        reader = PdfReader(io.BytesIO(data), strict=False)
        if reader.is_encrypted:
            raise ValueError
        root: Any = reader.trailer["/Root"]
        stack: list[Any] = [root["/Pages"]]
        while stack and not too_many:
            nodes += 1
            node = stack.pop().get_object()
            if not isinstance(node, DictionaryObject):
                raise ValueError
            kids = node.get("/Kids")
            if kids is None:
                pages += 1
            else:
                kids = kids.get_object()
                if not isinstance(kids, list):
                    raise ValueError
                too_many = len(stack) + len(kids) > MAX_PDF_NODES  # before the extend: a huge Kids array costs nothing
                stack.extend([] if too_many else kids)
            too_many = too_many or pages > MAX_PDF_PAGES or nodes > MAX_PDF_NODES
    except Exception:  # noqa: BLE001 -- pypdf raises many types; none of them may carry the file's content out
        unreadable = True
    if unreadable:
        raise RequestError("LW-06: a PDF part cannot be read as a PDF (malformed, encrypted or no pages tree)")
    if too_many:
        raise RequestError(f"LW-06: a PDF part has more than {MAX_PDF_PAGES} pages (or a page tree too large to count)")
    if pages < 1:
        raise RequestError("LW-06: a PDF part has no pages")
    return pages


class MediaPart(BaseModel):
    """One media file on a request: `data` (bytes) or `uri` (gs://, refused for now), its MIME type and a sha256.
    `seconds` (audio, video) is a declared duration that can only raise the estimate; `pages` (PDF) is optional and,
    if stated, must equal the measured count. Build one with `MediaPart(mime_type=..., data=...)`: `sha256`, `size`
    and a PDF's `pages` are set from the bytes."""

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
        if self.seconds is not None and kind not in ("audio", "video"):
            raise RequestError("LW-06: seconds is allowed only for audio and video parts")
        if self.pages is not None and self.mime_type != "application/pdf":
            raise RequestError("LW-06: pages is allowed only for PDF parts")
        if self.data is not None:
            digest = _inspect(self.mime_type, self.data)
            if self.sha256 is not None and self.sha256 != digest:
                raise RequestError("LW-06: the stated sha256 does not match the bytes")
            object.__setattr__(self, "sha256", digest)  # frozen: set once, here, by code
            object.__setattr__(self, "size", len(self.data))
            if kind == "document":
                measured = pdf_pages(self.data)
                if self.pages is not None and self.pages != measured:
                    raise RequestError("LW-06: the stated pages do not match the PDF")
                object.__setattr__(self, "pages", measured)
        elif self.sha256 is None or not _SHA256_RE.fullmatch(self.sha256) or not _GCS_URI_RE.fullmatch(self.uri or ""):
            raise RequestError("LW-06: a URI media part needs a gs:// URI and a lower-case hex sha256")
        return self

    @property
    def kind(self) -> str:
        return kind_of(self.mime_type)


def check_parts(parts: Sequence[MediaPart] | None) -> Sequence[MediaPart] | None:
    """The request-level gate the router and every adapter run: part count, total bytes, URI parts refused, and each
    part's fields checked again from its bytes -- type, sha256, size, declared seconds, measured PDF pages -- because
    a `model_copy(update=...)` or `model_construct` skips model validation."""
    if not parts:
        return parts
    if len(parts) > MAX_PARTS:
        raise RequestError(f"LW-06: {len(parts)} media parts, over the cap of {MAX_PARTS} a request")
    total = 0
    for part in parts:
        if part.data is None:
            raise RequestError("LW-06: GCS URI media parts are not supported yet (they need ADR-0018 T8); send bytes")
        if _inspect(part.mime_type, part.data) != part.sha256 or part.size != len(part.data):
            raise RequestError("LW-06: a media part's sha256 or size does not match its bytes")
        if part.seconds is not None and not (0 < part.seconds <= MAX_SECONDS and part.kind in ("audio", "video")):
            raise RequestError("LW-06: a media part's declared seconds are out of range")
        if part.kind == "document" and part.pages != pdf_pages(part.data):
            raise RequestError("LW-06: a PDF part's pages do not match the PDF")
        total += len(part.data)
    if total > MAX_TOTAL_BYTES:
        raise RequestError(f"LW-06: media parts total {total} bytes, over the cap of {MAX_TOTAL_BYTES} a request")
    return parts


def capabilities_needed(parts: Sequence[MediaPart] | None) -> set[str]:
    return {CAPABILITY_FOR_KIND[p.kind] for p in parts or ()}


def provider_takes(provider: str, part: MediaPart) -> bool:
    return part.kind == "image" or provider not in IMAGE_ONLY_PROVIDERS


def estimate_tokens(parts: Sequence[MediaPart] | None, media_tokens: Any) -> tuple[int, int]:
    """(tokens of every part, of which audio tokens): a bound from a profile's `media_tokens`, for EFF-03 and PL-03
    before sending (call `check_parts` first). Images cost `image`; a PDF `pdf_page` times its measured pages; audio
    and video `*_per_second` times the larger of the declared seconds and the size over the minimum bytes a second.
    Billing uses the reported usage, never this."""
    total = audio = 0
    for part in parts or ():
        data = part.data or b""
        if part.kind == "image":
            tokens = media_tokens.image
        elif part.kind == "document":
            tokens = pdf_pages(data) * media_tokens.pdf_page
        else:
            seconds = math.ceil(max(part.seconds or 0, len(data) / _MIN_BYTES_PER_SECOND[part.kind]))
            tokens = seconds * (
                media_tokens.audio_per_second if part.kind == "audio" else media_tokens.video_per_second
            )
        total += tokens
        audio += tokens if part.kind == "audio" else 0
    return total, audio
