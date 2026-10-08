"""LW-06 (ADR-0029 decision 6, FR-INT-02): `GenerateRequest.parts` carries images, PDFs, audio and video as untrusted
input. The declared MIME type is on an allow-list and must match the leading bytes; bytes are capped per part, per
request and in parts per request; the sha256 is computed by code, never trusted; a GCS URI part is typed but refused
until ADR-0018 T8; and the bytes never reach a repr, a dump, an error message or a recording key (only the sha256)."""

from __future__ import annotations

import base64
import hashlib
import json

import pytest
from pydantic import ValidationError
from tilo_providers.batch import BatchRequest
from tilo_providers.errors import RequestError
from tilo_providers.fake import FakeModelProvider
from tilo_providers.interfaces import GenerateRequest
from tilo_providers.media import (
    MAX_PART_BYTES,
    MAX_PARTS,
    MAX_TOTAL_BYTES,
    MediaPart,
    check_parts,
    estimate_tokens,
)
from tilo_providers.replay import recording_key

MARK = b"SECRETMARK-do-not-leak"  # distinctive payload content: it must never show up in any text below
PNG = b"\x89PNG\r\n\x1a\n" + MARK
PDF = b"%PDF-1.7\n/Type /Page\n" + MARK
GOOD = {
    "application/pdf": PDF,
    "image/png": PNG,
    "image/jpeg": b"\xff\xd8\xff\xe0" + MARK,
    "image/webp": b"RIFF\x00\x00\x00\x00WEBP" + MARK,
    "audio/wav": b"RIFF\x00\x00\x00\x00WAVE" + MARK,
    "audio/mpeg": b"ID3\x04" + MARK,
    "audio/flac": b"fLaC" + MARK,
    "audio/ogg": b"OggS" + MARK,
    "video/mp4": b"\x00\x00\x00\x18ftypmp42" + MARK,
    "video/webm": b"\x1a\x45\xdf\xa3" + MARK,
}


def part(mime: str = "image/png", data: bytes | None = None, **extra: object) -> MediaPart:
    if mime.startswith(("audio/", "video/")):
        extra.setdefault("seconds", 3.0)
    return MediaPart(mime_type=mime, data=GOOD.get(mime, PNG) if data is None else data, **extra)  # type: ignore[arg-type]


def no_leak(text: str) -> None:
    assert MARK.decode() not in text
    assert base64.b64encode(MARK).decode() not in text
    assert "SECRETMARK" not in text


@pytest.mark.parametrize("mime", sorted(GOOD))
def test_LW_06_every_accepted_type_is_taken_and_its_sha256_is_computed_by_code(mime):
    made = part(mime)
    assert made.sha256 == hashlib.sha256(GOOD[mime]).hexdigest()
    assert made.size == len(GOOD[mime])
    stated = part(mime, sha256=hashlib.sha256(GOOD[mime]).hexdigest())
    assert stated == made


def test_LW_06_a_stated_sha256_that_does_not_match_the_bytes_is_refused_not_trusted():
    with pytest.raises(RequestError, match="sha256"):
        part("image/png", sha256="0" * 64)


@pytest.mark.parametrize(
    "mime", ["image/gif", "IMAGE/PNG", "image/png; charset=utf-8", "image/svg+xml", "text/html", "application/zip", ""]
)
def test_LW_06_a_mime_type_off_the_exact_allow_list_is_refused(mime):
    with pytest.raises(RequestError, match="not accepted"):
        MediaPart(mime_type=mime, data=PNG)


@pytest.mark.parametrize("declared", [m for m in GOOD if m != "image/png"])
def test_LW_06_bytes_that_do_not_match_the_declared_type_are_refused(declared):
    kwargs = {"seconds": 3.0} if declared.startswith(("audio/", "video/")) else {}
    with pytest.raises(RequestError, match="do not match") as caught:
        MediaPart(mime_type=declared, data=PNG, **kwargs)
    no_leak(str(caught.value))


def test_LW_06_empty_and_oversize_parts_are_refused():
    with pytest.raises(RequestError, match="no bytes"):
        MediaPart(mime_type="image/png", data=b"")
    with pytest.raises(RequestError, match="byte cap"):
        MediaPart(mime_type="image/png", data=PNG + b"\0" * MAX_PART_BYTES)
    assert MediaPart(mime_type="image/png", data=PNG + b"\0" * (MAX_PART_BYTES - len(PNG))).size == MAX_PART_BYTES


def test_LW_06_parts_per_request_and_total_bytes_are_capped():
    with pytest.raises(ValidationError):
        GenerateRequest(prompt="p", parts=[part()] * (MAX_PARTS + 1))
    assert len(GenerateRequest(prompt="p", parts=[part()] * MAX_PARTS).parts or []) == MAX_PARTS
    big = part("image/png", PNG + b"\0" * (MAX_PART_BYTES - len(PNG)))
    assert -(-MAX_TOTAL_BYTES // MAX_PART_BYTES) == 2
    with pytest.raises(RequestError, match="total"):
        check_parts([big, big])


def test_LW_06_a_uri_part_is_typed_but_refused_until_adr_0018_t8():
    uri = MediaPart(mime_type="application/pdf", uri="gs://tilo-bucket/papers/gate-2025.pdf", sha256="a" * 64)
    assert uri.data is None
    with pytest.raises(RequestError, match="ADR-0018 T8"):
        check_parts([uri])
    for bad in ("https://example.com/a.pdf", "gs://", "file:///etc/passwd", "gs://b/o p"):
        with pytest.raises(RequestError):
            MediaPart(mime_type="application/pdf", uri=bad, sha256="a" * 64)
    with pytest.raises(RequestError):
        MediaPart(mime_type="application/pdf", uri="gs://tilo-bucket/a.pdf")  # no sha256
    with pytest.raises(RequestError, match="exactly one"):
        MediaPart(mime_type="application/pdf", uri="gs://tilo-bucket/a.pdf", sha256="a" * 64, data=PDF)


def test_LW_06_seconds_and_pages_are_allowed_only_where_they_mean_something():
    with pytest.raises(RequestError, match="seconds"):
        MediaPart(mime_type="audio/wav", data=GOOD["audio/wav"])
    with pytest.raises(RequestError, match="seconds"):
        MediaPart(mime_type="image/png", data=PNG, seconds=3.0)
    with pytest.raises(RequestError, match="pages"):
        MediaPart(mime_type="image/png", data=PNG, pages=2)
    assert MediaPart(mime_type="application/pdf", data=PDF, pages=7).pages == 7


def test_LW_06_a_non_bytes_payload_is_a_validation_error_that_does_not_echo_it():
    with pytest.raises(ValidationError) as caught:
        GenerateRequest(prompt="p", parts=[{"mime_type": "image/png", "data": base64.b64encode(PNG).decode()}])
    no_leak(str(caught.value))
    assert "input_value" not in str(caught.value)


def test_LW_06_bytes_reach_no_repr_dump_json_or_error():
    request = GenerateRequest(prompt="describe", parts=[part("image/png"), part("application/pdf")])
    no_leak(repr(request))
    no_leak(repr(request.parts))
    no_leak(json.dumps(request.model_dump(exclude_none=True), default=str))
    no_leak(request.model_dump_json())
    assert request.parts and request.parts[0].data == PNG, "the adapter still gets the bytes"


def test_LW_06_a_part_swapped_after_validation_is_caught_by_the_request_gate():
    swapped = part("image/png").model_copy(update={"data": PNG + b"other"})  # model_copy skips validation
    with pytest.raises(RequestError, match="sha256"):
        check_parts([swapped])
    retyped = part("image/png").model_copy(update={"mime_type": "application/pdf"})
    with pytest.raises(RequestError, match="do not match"):
        check_parts([retyped])


def test_LW_06_recording_keys_use_the_sha256_and_never_the_bytes():
    a, b = part("image/png"), part("image/png", PNG + b"x")
    key = lambda p: recording_key("director", "flash", GenerateRequest(prompt="p", parts=[p]))  # noqa: E731
    assert key(a) == key(part("image/png")), "the same bytes give the same key"
    assert key(a) != key(b), "other bytes give another key"
    assert recording_key("director", "flash", GenerateRequest(prompt="p")) != key(a)


def test_LW_06_a_request_without_parts_keeps_its_recording_key():
    assert recording_key("r", "p", GenerateRequest(prompt="p")) == recording_key("r", "p", GenerateRequest(prompt="p"))
    assert "parts" not in GenerateRequest(prompt="p").model_dump(exclude_none=True), "existing keys do not shift"


def test_LW_06_the_fake_provider_answers_differently_for_different_files():
    fake = FakeModelProvider()
    one = fake.generate(GenerateRequest(prompt="p", parts=[part("image/png")]))
    two = fake.generate(GenerateRequest(prompt="p", parts=[part("image/png", PNG + b"x")]))
    assert one.text != two.text
    assert fake.generate(GenerateRequest(prompt="p")).text == fake.generate(GenerateRequest(prompt="p")).text


def test_LW_06_a_batch_request_with_parts_is_refused_not_silently_dropped():
    with pytest.raises(RequestError, match="batch"):
        BatchRequest(custom_id="a", request=GenerateRequest(prompt="p", parts=[part()]))


class Tokens:
    image, pdf_page, audio_per_second, video_per_second = 1120, 1000, 25, 258


def test_LW_06_token_estimates_are_upper_bounds_from_the_profile_media_tokens():
    assert estimate_tokens([part("image/png")], Tokens) == (1120, 0)
    assert estimate_tokens([part("application/pdf", pages=3)], Tokens) == (3000, 0)
    pages = b"%PDF-1.7\n" + b"/Type /Page\n" * 5 + b"/Type /Pages\n"
    assert estimate_tokens([part("application/pdf", pages)], Tokens) == (5000, 0), "page objects counted, /Pages not"
    assert estimate_tokens([part("application/pdf", pages, pages=8)], Tokens) == (8000, 0), "the larger of the two"
    assert estimate_tokens([part("audio/wav", seconds=10.0)], Tokens) == (250, 250)
    assert estimate_tokens([part("video/mp4", seconds=2.0)], Tokens) == (516, 0)
    assert estimate_tokens(None, Tokens) == (0, 0)
    # a duration too short for the file's size is raised to what the size implies at the floor bitrate
    long_clip = part("audio/mpeg", b"ID3\x04" + b"\0" * 400_000, seconds=1.0)
    assert estimate_tokens([long_clip], Tokens) == (101 * 25, 101 * 25)
