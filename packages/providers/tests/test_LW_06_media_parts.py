"""LW-06 (ADR-0029 decision 6, FR-INT-02): `GenerateRequest.parts` carries images, PDFs, audio and video as untrusted
input. The declared MIME type is on an allow-list and must match the leading bytes (brand, DocType and codec included);
bytes are capped per part, per request and in parts per request; the sha256 is computed by code, never trusted; the
pages of a PDF are measured by walking its page tree; a GCS URI part is typed but refused until ADR-0018 T8; and the
bytes never reach a repr, a dump, an error message or a recording key (only the sha256)."""

from __future__ import annotations

import base64
import hashlib
import json

import pytest
from _lw06_media import MARK, MP4, OGG_HEAD, PNG, WAV, WEBM, classic_pdf, objstm_pdf, ogg, pdf
from pydantic import ValidationError
from tilo_providers.batch import BatchRequest, FakeBatchProvider
from tilo_providers.errors import RequestError
from tilo_providers.fake import FakeModelProvider
from tilo_providers.interfaces import GenerateRequest
from tilo_providers.media import (
    MAX_PART_BYTES,
    MAX_PARTS,
    MAX_PDF_PAGES,
    MAX_TOTAL_BYTES,
    MediaPart,
    check_parts,
    estimate_tokens,
    pdf_pages,
)
from tilo_providers.replay import recording_key

GOOD = {
    "application/pdf": pdf(1),
    "image/png": PNG,
    "image/jpeg": b"\xff\xd8\xff\xe0" + MARK,
    "image/webp": b"RIFF\x00\x00\x00\x00WEBP" + MARK,
    "audio/wav": WAV,
    "audio/mpeg": b"ID3\x04" + MARK,
    "audio/flac": b"fLaC" + MARK,
    "audio/ogg": ogg(),
    "video/mp4": MP4,
    "video/webm": WEBM,
}


def part(mime: str = "image/png", data: bytes | None = None, **extra: object) -> MediaPart:
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
    assert part(mime, sha256=hashlib.sha256(GOOD[mime]).hexdigest()) == made


def test_LW_06_a_stated_sha256_that_does_not_match_the_bytes_is_refused_not_trusted():
    with pytest.raises(RequestError, match="sha256"):
        part("image/png", sha256="0" * 64)


@pytest.mark.parametrize(
    "mime", ["image/gif", "IMAGE/PNG", "image/png; charset=utf-8", "image/svg+xml", "text/html", "application/zip", ""]
)
def test_LW_06_a_mime_type_off_the_exact_allow_list_is_refused(mime):
    with pytest.raises(RequestError, match="not accepted"):
        MediaPart(mime_type=mime, data=PNG)


def test_LW_06_a_refused_mime_type_is_echoed_only_as_a_short_plain_token():
    with pytest.raises(RequestError) as caught:
        MediaPart(mime_type="image/x-evil\n<script>alert(1)</script>", data=PNG)
    assert "script" not in str(caught.value) and "\n" not in str(caught.value).split("accepted:")[0]
    with pytest.raises(RequestError, match="image/gif"):
        MediaPart(mime_type="image/gif", data=PNG)


@pytest.mark.parametrize("declared", [m for m in GOOD if m != "image/png"])
def test_LW_06_bytes_that_do_not_match_the_declared_type_are_refused(declared):
    with pytest.raises(RequestError, match="do not match") as caught:
        MediaPart(mime_type=declared, data=PNG)
    no_leak(str(caught.value))


@pytest.mark.parametrize(
    ("mime", "data"),
    [
        ("video/mp4", b"\x00\x00\x00\x18ftypheic" + MARK),  # HEIC image
        ("video/mp4", b"\x00\x00\x00\x18ftypavif" + MARK),
        ("video/mp4", b"\x00\x00\x00\x14ftypqt  " + MARK),  # QuickTime
        ("video/webm", b"\x1a\x45\xdf\xa3\x42\x82\x88matroska" + MARK),  # Matroska, not WebM
        ("audio/ogg", OGG_HEAD + b"\x80theora" + MARK),
        ("audio/ogg", OGG_HEAD + b"Speex   " + MARK),
        ("audio/mpeg", b"\xff\xf1" + MARK),  # ADTS (AAC), not MPEG audio
        ("audio/mpeg", b"\xff\xe8" + MARK),  # reserved MPEG version
    ],
)
def test_LW_06_a_container_that_only_looks_like_an_accepted_type_is_refused(mime, data):
    with pytest.raises(RequestError, match="do not match"):
        MediaPart(mime_type=mime, data=data)


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
        MediaPart(
            mime_type="application/pdf", uri="gs://tilo-bucket/a.pdf", sha256="a" * 64, data=GOOD["application/pdf"]
        )


def test_LW_06_seconds_and_pages_are_allowed_only_where_they_mean_something():
    assert part("audio/wav", seconds=5.0).seconds == 5.0 and part("audio/wav").seconds is None
    with pytest.raises(RequestError, match="seconds"):
        MediaPart(mime_type="image/png", data=PNG, seconds=3.0)
    with pytest.raises(RequestError, match="pages"):
        MediaPart(mime_type="image/png", data=PNG, pages=2)
    assert part("application/pdf", pdf(3), pages=3).pages == 3
    assert part("application/pdf", pdf(3)).pages == 3, "a PDF's pages are filled in from the bytes"
    with pytest.raises(RequestError, match="pages"):
        part("application/pdf", pdf(3), pages=1)  # a caller's number below (or above) the measured count is refused


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


@pytest.mark.parametrize(
    "forged",
    [
        {"seconds": -5.0},
        {"seconds": float("nan")},
        {"seconds": 1e9},
        {"size": -10_000_000},
        {"size": 3},
        {"pages": 1},
    ],
)
def test_LW_06_forged_sizes_seconds_and_pages_are_refused_by_the_request_gate(forged):
    base = part("audio/wav") if "seconds" in forged else part("application/pdf", pdf(3))
    with pytest.raises(RequestError):
        check_parts([base.model_copy(update=forged)])


def test_LW_06_the_pages_of_a_pdf_are_counted_from_its_page_tree_not_from_text_or_a_claimed_count():
    assert pdf_pages(pdf(4)) == 4
    assert pdf_pages(objstm_pdf(5)) == 5, "pages inside a compressed object stream"
    assert pdf_pages(classic_pdf(5, page_type=b"/Type /#50age")) == 5, "a page type written with a #-escape"
    assert pdf_pages(classic_pdf(5, count=1)) == 5, "a /Count that lies low"
    assert pdf_pages(classic_pdf(MAX_PDF_PAGES)) == MAX_PDF_PAGES
    assert b"/Type /Page" not in objstm_pdf(5), "nothing for a text scan to find"


def test_LW_06_a_pdf_over_the_page_cap_is_refused_whatever_it_claims_and_stays_small():
    tiny = classic_pdf(1000, count=1)  # a few kilobytes, a 1000 page tree, a /Count of 1
    assert len(tiny) < 10_000
    with pytest.raises(RequestError, match="more than 100 pages"):
        MediaPart(mime_type="application/pdf", data=tiny)
    with pytest.raises(RequestError, match="more than 100 pages"):
        MediaPart(mime_type="application/pdf", data=objstm_pdf(1000))


def test_LW_06_a_page_tree_that_loops_or_fans_out_is_cut_off_by_the_node_budget():
    # the page node is its own kid: a cycle that a count would never leave
    cycle = classic_pdf(1).replace(b"/Kids[3 0 R]", b"/Kids[2 0 R 3 0 R]")
    with pytest.raises(RequestError, match="more than 100 pages|cannot be read"):
        MediaPart(mime_type="application/pdf", data=cycle)


@pytest.mark.parametrize("junk", [b"%PDF-1.7\nnot a pdf at all" + MARK, b"%PDF-", b"%PDF-1.4\n" + b"\0" * 5000])
def test_LW_06_an_unreadable_pdf_is_refused_without_quoting_the_file(junk):
    with pytest.raises(RequestError, match="cannot be read") as caught:
        MediaPart(mime_type="application/pdf", data=junk)
    no_leak(str(caught.value))
    assert caught.value.__cause__ is None and caught.value.__context__ is None


def test_LW_06_recording_keys_use_the_sha256_and_never_the_bytes():
    a, b = part("image/png"), part("image/png", PNG + b"x")
    key = lambda p: recording_key("director", "flash", GenerateRequest(prompt="p", parts=[p]))  # noqa: E731
    assert key(a) == key(part("image/png")), "the same bytes give the same key"
    assert key(a) != key(b), "other bytes give another key"
    assert recording_key("director", "flash", GenerateRequest(prompt="p")) != key(a)


def test_LW_06_a_request_without_parts_keeps_its_recording_key():
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


def test_LW_06_a_batch_item_that_gains_parts_after_construction_is_refused_at_submit():
    plain = GenerateRequest(prompt="p")
    item = BatchRequest(custom_id="a", request=plain)
    plain.parts = [part()]  # a mutation after the item was built
    with pytest.raises(RequestError, match="batch"):
        FakeBatchProvider().submit([item], idempotency_key="k")
    with pytest.raises(RequestError, match="batch"):
        item.request = GenerateRequest(prompt="p", parts=[part()])  # an assignment is validated too


def test_LW_06_a_validation_error_on_a_batch_item_does_not_echo_its_input():
    with pytest.raises(ValidationError) as caught:
        BatchRequest(custom_id="a", request={"prompt": "p", "parts": [{"mime_type": "image/png", "data": "str" * 40}]})
    assert "input_value" not in str(caught.value)


class Tokens:
    image, pdf_page, audio_per_second, video_per_second = 1120, 1000, 25, 258


def test_LW_06_token_estimates_come_from_the_profile_media_tokens_and_the_measured_bytes():
    assert estimate_tokens([part("image/png")], Tokens) == (1120, 0)
    assert estimate_tokens([part("application/pdf", pdf(3))], Tokens) == (3000, 0)
    assert estimate_tokens([part("application/pdf", objstm_pdf(5))], Tokens) == (5000, 0)
    assert estimate_tokens([part("application/pdf", classic_pdf(5, page_type=b"/Type /#50age"))], Tokens) == (5000, 0)
    assert estimate_tokens(None, Tokens) == (0, 0)
    # audio and video: the larger of the declared seconds and size / minimum bytes a second (500 audio, 1,000 video)
    assert estimate_tokens([part("audio/wav", seconds=10.0)], Tokens) == (250, 250)
    assert estimate_tokens([part("video/mp4", seconds=2.0)], Tokens) == (516, 0)
    assert estimate_tokens([part("audio/wav")], Tokens) == (25, 25), "no declared seconds: one second at least"


def test_LW_06_a_short_declared_duration_cannot_lower_what_the_size_implies():
    clip = part("audio/ogg", ogg(10_000_000), seconds=1.0)  # a 10 MB ogg that claims one second
    assert estimate_tokens([clip], Tokens) == (20_000 * 25, 20_000 * 25)
    low_bitrate = part("audio/ogg", ogg(40_000), seconds=1.0)
    assert estimate_tokens([low_bitrate], Tokens)[0] == 80 * 25
    still = part("video/mp4", MP4 + bytes(500_000), seconds=1.0)
    assert estimate_tokens([still], Tokens)[0] == 501 * 258
