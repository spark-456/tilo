"""Builders for LW-06 tests: small valid media files made at runtime (no binary fixtures), including the PDFs a text
scan for `/Type /Page` gets wrong (pages inside an object stream, a page type written with a #-escape, a /Count that
lies), hostile PDFs that make a parser burn time or memory, and WAV files with an exact duration."""

from __future__ import annotations

import io
import struct
import zlib

from pypdf import PdfWriter

MARK = b"SECRETMARK-do-not-leak"  # distinctive payload content: it must never show up in any text a test inspects
PNG = b"\x89PNG\r\n\x1a\n" + MARK
OGG_HEAD = b"OggS" + bytes(22) + b"\x01\x08"  # 27 byte page header, one segment of 8 bytes
MP4 = b"\x00\x00\x00\x18ftypmp42" + MARK
WEBM = b"\x1a\x45\xdf\xa3\x42\x82\x84webm" + MARK


def wav(
    seconds: float, rate: int = 8000, *, declared: int | None = None, fmt_tag: int = 1, byte_rate: int | None = None
):
    """A PCM WAV (8-bit mono unless the rate says otherwise) lasting exactly `seconds`: header and byte length agree.
    `declared`, `fmt_tag` and `byte_rate` let a test make the header lie."""
    body = b"\x80" * int(seconds * rate)
    header = b"fmt " + struct.pack("<IHHIIHH", 16, fmt_tag, 1, rate, byte_rate or rate, 1, 8)
    data = b"data" + struct.pack("<I", len(body) if declared is None else declared) + body
    return b"RIFF" + struct.pack("<I", 4 + len(header) + len(data)) + b"WAVE" + header + data


WAV = wav(1.0)


def chunk(chunk_id: bytes, body: bytes) -> bytes:
    """A RIFF chunk, padded to an even length."""
    return chunk_id + struct.pack("<I", len(body)) + body + (b"\0" if len(body) & 1 else b"")


def fmt_chunk(rate: int = 8000, bits: int = 8, channels: int = 1) -> bytes:
    align = channels * bits // 8
    return chunk(b"fmt ", struct.pack("<HHIIHH", 1, channels, rate, rate * align, align, bits))


def riff(*chunks: bytes) -> bytes:
    body = b"WAVE" + b"".join(chunks)
    return b"RIFF" + struct.pack("<I", len(body)) + body


def ogg(size: int = 0) -> bytes:
    return OGG_HEAD + b"OpusHead" + MARK + bytes(max(0, size - len(OGG_HEAD) - 8 - len(MARK)))


def pdf(pages: int = 1, mark: bytes = MARK) -> bytes:
    """A valid PDF with `pages` blank pages and `mark` in its title."""
    writer = PdfWriter()
    for _ in range(pages):
        writer.add_blank_page(72, 72)
    writer.add_metadata({"/Title": mark.decode()})
    out = io.BytesIO()
    writer.write(out)
    return out.getvalue()


def classic_pdf(pages: int, *, page_type: bytes = b"/Type/Page", count: int | None = None) -> bytes:
    """A classic xref-table PDF whose page tree lists one page object `pages` times. `page_type` is how the page
    object's type is written (`/Type /#50age` is the same name); `count` is the /Count the Pages node claims."""
    kids = b" ".join([b"3 0 R"] * pages)
    claimed = pages if count is None else count
    objects = [
        b"<</Type/Catalog/Pages 2 0 R>>",
        b"<</Type/Pages/Count %d/Kids[%s]>>" % (claimed, kids),
        b"<<%s/Parent 2 0 R/MediaBox[0 0 10 10]>>" % page_type,
    ]
    out, offsets = bytearray(b"%PDF-1.4\n"), []
    for number, body in enumerate(objects, 1):
        offsets.append(len(out))
        out += b"%d 0 obj\n%s\nendobj\n" % (number, body)
    start = len(out)
    out += b"xref\n0 4\n0000000000 65535 f \n" + b"".join(b"%010d 00000 n \n" % offset for offset in offsets)
    out += b"trailer\n<</Size 4/Root 1 0 R>>\nstartxref\n%d\n%%%%EOF\n" % start
    return bytes(out)


def _entry(kind: int, field2: int, field3: int) -> bytes:
    return bytes([kind]) + field2.to_bytes(4, "big") + field3.to_bytes(2, "big")


def _objstm_file(header: bytes, content: bytes, objects: int) -> bytes:
    """A PDF 1.5 file: `objects` objects (1 is the catalog) live in one compressed object stream (`header` is its
    "number offset" pairs, `content` what follows them), found through an xref stream."""
    stream = zlib.compress(header + content)
    out = bytearray(b"%PDF-1.5\n")
    objstm_at, xref_number = len(out), objects + 2
    out += b"%d 0 obj\n<</Type/ObjStm/N %d/First %d/Filter/FlateDecode/Length %d>>\nstream\n" % (
        objects + 1,
        objects,
        len(header),
        len(stream),
    )
    out += stream + b"\nendstream\nendobj\n"
    xref_at = len(out)
    table = _entry(0, 0, 65535) + b"".join(_entry(2, objects + 1, index) for index in range(objects))
    table += _entry(1, objstm_at, 0) + _entry(1, xref_at, 0)
    out += b"%d 0 obj\n<</Type/XRef/Size %d/W[1 4 2]/Root 1 0 R/Length %d>>\nstream\n" % (
        xref_number,
        objects + 3,
        len(table),
    )
    out += table + b"\nendstream\nendobj\nstartxref\n%d\n%%%%EOF\n" % xref_at
    return bytes(out)


def objstm_pdf(pages: int, *, pad: int = 0) -> bytes:
    """The catalog, page tree and page live inside a compressed object stream: no `/Type /Page` text is visible
    anywhere in the file. `pad` appends that many spaces to the decoded stream (a small file that inflates)."""
    bodies = [
        b"<</Type/Catalog/Pages 2 0 R>>",
        b"<</Type/Pages/Count %d/Kids[%s]>>" % (pages, b" ".join([b"3 0 R"] * pages)),
        b"<</Type/Page/Parent 2 0 R/MediaBox[0 0 10 10]>>",
    ]
    offsets, at = [], 0
    for body in bodies:
        offsets.append(at)
        at += len(body) + 1
    header = b" ".join(b"%d %d" % (number, offset) for number, offset in enumerate(offsets, 1)) + b"\n"
    return _objstm_file(header, b"\n".join(bodies) + b" " * pad, 3)


def whitespace_run_pdf(entries: int = 10, run: int = 2_000_000) -> bytes:
    """`entries` object-stream entries that all point at the start of one `run` byte whitespace run: a parser that
    skips whitespace once per entry does entries x run work from a file of a few kilobytes."""
    header = b" ".join(b"%d 0" % number for number in range(1, entries + 1)) + b"\n"
    return _objstm_file(header, b" " * run + b"<</Type/Catalog/Pages 2 0 R>>", entries)


def huge_xref_pdf(entries: int = 2_000_000) -> bytes:
    """A few tens of kilobytes whose xref stream declares `entries` bogus entries (zeros) once decoded."""
    table = zlib.compress(bytes(7 * entries))
    out = bytearray(b"%PDF-1.5\n")
    at = len(out)
    out += b"1 0 obj\n<</Type/XRef/Size %d/Index[0 %d]/W[1 4 2]/Root 1 0 R/Filter/FlateDecode/Length %d>>\nstream\n" % (
        entries,
        entries,
        len(table),
    )
    out += table + b"\nendstream\nendobj\nstartxref\n%d\n%%%%EOF\n" % at
    return bytes(out)
