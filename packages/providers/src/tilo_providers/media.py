"""tilo_providers.media -- media parts on a `GenerateRequest` (LW-06, ADR-0029 decision 6; FR-INT-02). A part is a file
a model reads natively: an image, a PDF, audio or video. Media is untrusted input, so every rule here refuses rather
than coerces, and nothing here ever puts the bytes anywhere but the request itself:

- the declared MIME type must be on a short allow-list (exact, lower case, no parameters) and the leading bytes must
  match it (magic numbers, and for mp4, webm and ogg the brand, DocType or codec);
- bytes are capped per part, per request and in parts per request;
- `sha256` is computed here from the bytes; a caller's value is only checked against it, never trusted;
- the pages of a PDF are measured here by walking its page tree with pypdf in a child process under a wall-clock limit
  and a decoded-size limit (`_pdf_pages_child`), never from a caller's number or a text scan; an unreadable, slow or
  oversize PDF, or one over MAX_PDF_PAGES, is refused;
- the duration of audio and video is never taken from a caller or a header: a plain PCM WAV is measured exactly from its
  length once its header agrees with the file and has no chunk ambiguity, and everything else (no decoder is a
  dependency yet) is assumed to last the provider's documented maximum (UNMEASURED_AUDIO_SECONDS,
  UNMEASURED_VIDEO_SECONDS), so a capped role refuses it (BQ-LW6-2);
- `repr`, `model_dump` and validation errors leave the bytes out (`data` is excluded from the dump, which is what
  recordings are keyed on: the sha256, never the bytes), and no message below ever quotes content;
- a GCS URI part is typed but refused until ADR-0018 T8 gives it a reader.

Billing never uses the estimates here: they are bounds for the pre-flight EFF-03 cap check and the PL-03 budget check
(`estimate_tokens`); the reported usage is what is billed."""

from __future__ import annotations

import hashlib
import math
import os
import re
import struct
import subprocess
import sys
import threading
from collections import OrderedDict
from collections.abc import Callable, Sequence
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator

from tilo_providers._pdf_pages_child import MAX_PDF_PAGES
from tilo_providers.errors import RequestError

MAX_PARTS = 10  # FR-INT-01: at most 10 files a unit
MAX_PART_BYTES = 10 * 1024 * 1024
MAX_TOTAL_BYTES = 14 * 1024 * 1024  # inline data rides base64 (x4/3) under Gemini's 20 MB request limit
PDF_TIMEOUT_SECONDS = 5.0  # wall clock for counting one PDF's pages, child start-up included; then it is killed
_PDF_CHILDREN = 2  # page-counting children running at once; the others wait their turn
_PDF_CACHE_ENTRIES = 32  # keyed on the sha256, never the bytes; at least MAX_PARTS
# What audio or video of unknown duration is assumed to last (config-free, BQ-LW6-2). Audio: the longest the
# provider documents for one file (Gemini audio understanding, 9.5 hours). Video: one hour, the length Gemini
# documents for video with audio; the provider's tokens-per-second figures come from `media_tokens`.
UNMEASURED_AUDIO_SECONDS = 34_200
UNMEASURED_VIDEO_SECONDS = 3_600
_WAV_RATES = range(8_000, 192_001)
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


def _child_command() -> list[str]:
    return [sys.executable, "-I", "-m", "tilo_providers._pdf_pages_child"]


def _measure(data: bytes) -> tuple[str, int]:
    """Runs the page counter in a child process: ("ok", pages), ("many", 0), ("bad", 0) for a file the child judged
    unreadable, or ("slow", 0) / ("error", 0) when no verdict was reached (still running at PDF_TIMEOUT_SECONDS and
    killed; could not start; died; printed nonsense). At most _PDF_CHILDREN run at once. The child gets the file on
    stdin and almost no environment."""
    with _pdf_children:
        try:
            done = subprocess.run(  # noqa: S603 -- our own module, a fixed command; the file never reaches argv
                _child_command(),
                input=data,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                timeout=PDF_TIMEOUT_SECONDS,
                check=False,
                env={"SYSTEMROOT": os.environ.get("SYSTEMROOT", "")} if sys.platform == "win32" else {},
            )
        except subprocess.TimeoutExpired:
            return "slow", 0
        except Exception:  # noqa: BLE001 -- no child could be run: refuse, never guess
            return "error", 0
    fields = done.stdout.split()
    if done.returncode == 0 and len(fields) == 2 and fields[0] in (b"ok", b"many", b"bad") and fields[1].isdigit():
        return fields[0].decode(), int(fields[1])
    return "error", 0


_pdf_cache: OrderedDict[str, tuple[str, int]] = OrderedDict()
_pdf_lock = threading.Lock()
_pdf_children = threading.BoundedSemaphore(_PDF_CHILDREN)
_CACHED_VERDICTS = frozenset({"ok", "many", "bad"})


def pdf_pages(data: bytes) -> int:
    """The number of pages of a PDF, counted by walking its page tree (not its /Count, not a text scan) in a child
    process with a wall-clock limit and decoded-size limits, so a hostile file cannot burn the service's CPU or memory
    (`_pdf_pages_child`). Refuses an unreadable, encrypted, slow or oversize PDF, no pages, or more than MAX_PDF_PAGES.
    A verdict on the file (ok, too many, unreadable) is cached by its sha256, so a repeat costs nothing; a timeout
    or a failure to run is not a verdict on the file and is tried again next time."""
    key = hashlib.sha256(data).hexdigest()
    with _pdf_lock:
        result = _pdf_cache.get(key)
    if result is None:
        result = _measure(data)
        if result[0] in _CACHED_VERDICTS:
            with _pdf_lock:
                _pdf_cache[key] = result
                while len(_pdf_cache) > _PDF_CACHE_ENTRIES:
                    _pdf_cache.popitem(last=False)
    status, pages = result
    if status == "ok":
        return pages
    if status == "many":
        raise RequestError(f"LW-06: a PDF part has more than {MAX_PDF_PAGES} pages (or a page tree too large to count)")
    if status == "slow":
        raise RequestError(f"LW-06: a PDF part took over {PDF_TIMEOUT_SECONDS:g} seconds to read and was refused")
    raise RequestError("LW-06: a PDF part cannot be read as a PDF (malformed, encrypted, oversize or no pages)")


def wav_seconds(data: bytes) -> float | None:
    """The exact duration of a plain PCM WAV, or None (not measured). The header must agree with the file: PCM format,
    1 to 8 channels, 8 to 192 kHz, 8 to 32 bits, block align and byte rate consistent with them, and a data chunk that
    does not claim more bytes than the file holds. Any ambiguity a decoder could resolve differently makes it None:
    more than one fmt or data chunk, a fmt after the data, an odd-sized chunk before the data, a chunk running past
    the end of the file, or trailing bytes that are no chunk. The seconds are every byte after the data header over
    the byte rate (the safe side if chunks follow the data)."""
    if len(data) < 12 or data[:4] != b"RIFF" or data[8:12] != b"WAVE":
        return None
    pos, byte_rate, data_start = 12, 0, None
    while pos + 8 <= len(data):
        chunk, size = data[pos : pos + 4], int.from_bytes(data[pos + 4 : pos + 8], "little")
        body = pos + 8
        if body + size > len(data):
            return None
        if chunk == b"fmt ":
            if byte_rate or data_start is not None or size < 16:
                return None
            tag, channels, rate, byte_rate, align, bits = struct.unpack("<HHIIHH", data[body : body + 16])
            if tag != 1 or not 1 <= channels <= 8 or rate not in _WAV_RATES or bits not in (8, 16, 24, 32):
                return None
            if align != channels * bits // 8 or byte_rate != rate * align:
                return None
        elif chunk == b"data":
            if byte_rate == 0 or data_start is not None:
                return None
            data_start = body
        elif size & 1 and data_start is None:
            return None
        pos = body + size + (size & 1)
    if data_start is None or pos < len(data) - 1:
        return None
    return (len(data) - data_start) / byte_rate


class MediaPart(BaseModel):
    """One media file on a request: `data` (bytes) or `uri` (gs://, refused for now), its MIME type and a sha256.
    `pages` (PDF) is optional and, if stated, must equal the measured count. Build one with
    `MediaPart(mime_type=..., data=...)`: `sha256`, `size` and a PDF's `pages` are set from the bytes."""

    model_config = ConfigDict(extra="forbid", frozen=True, hide_input_in_errors=True)
    mime_type: str = Field(strict=True, max_length=100)
    data: bytes | None = Field(default=None, strict=True, repr=False, exclude=True)
    uri: str | None = Field(default=None, strict=True, max_length=1300)
    sha256: str | None = Field(default=None, strict=True, max_length=64)
    size: int | None = None
    pages: int | None = Field(default=None, ge=1, le=MAX_PDF_PAGES)

    @model_validator(mode="after")
    def _validated(self) -> MediaPart:
        kind = kind_of(self.mime_type)
        if (self.data is None) == (self.uri is None):
            raise RequestError("LW-06: a media part carries its bytes or a URI, exactly one")
        if self.size is not None and self.data is None:
            raise RequestError("LW-06: a URI media part cannot state a size")
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
    part's fields checked again from its bytes -- type, sha256, size, measured PDF pages -- because a
    `model_copy(update=...)` or `model_construct` skips model validation."""
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
    before sending (call `check_parts` first). Images cost `image`; a PDF `pdf_page` times its measured pages; a WAV
    `audio_per_second` times its exact seconds; any other audio (video) `*_per_second` times
    UNMEASURED_AUDIO_SECONDS (UNMEASURED_VIDEO_SECONDS).
    Billing uses the reported usage, never this."""
    total = audio = 0
    for part in parts or ():
        data = part.data or b""
        if part.kind == "image":
            tokens = media_tokens.image
        elif part.kind == "document":
            tokens = pdf_pages(data) * media_tokens.pdf_page
        else:
            measured = wav_seconds(data) if part.mime_type == "audio/wav" else None
            worst = UNMEASURED_AUDIO_SECONDS if part.kind == "audio" else UNMEASURED_VIDEO_SECONDS
            seconds = math.ceil(worst if measured is None else measured)
            tokens = seconds * (
                media_tokens.audio_per_second if part.kind == "audio" else media_tokens.video_per_second
            )
        total += tokens
        audio += tokens if part.kind == "audio" else 0
    return total, audio
