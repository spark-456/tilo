"""Builders for LW-06 tests: small valid media files made at runtime (no binary fixtures), including the PDFs a text
scan for `/Type /Page` gets wrong: pages inside an object stream, a page type written with a #-escape, a /Count that
lies."""

from __future__ import annotations

import io
import zlib

from pypdf import PdfWriter

MARK = b"SECRETMARK-do-not-leak"  # distinctive payload content: it must never show up in any text a test inspects
PNG = b"\x89PNG\r\n\x1a\n" + MARK
WAV = b"RIFF\x00\x00\x00\x00WAVE" + MARK
OGG_HEAD = b"OggS" + bytes(22) + b"\x01\x08"  # 27 byte page header, one segment of 8 bytes
MP4 = b"\x00\x00\x00\x18ftypmp42" + MARK
WEBM = b"\x1a\x45\xdf\xa3\x42\x82\x84webm" + MARK


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


def objstm_pdf(pages: int) -> bytes:
    """A PDF 1.5 file whose catalog, page tree and page live inside a compressed object stream, found through an
    xref stream: no `/Type /Page` text is visible anywhere in it."""
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
    stream = zlib.compress(header + b"\n".join(bodies))
    out = bytearray(b"%PDF-1.5\n")
    objstm_at = len(out)
    out += b"4 0 obj\n<</Type/ObjStm/N 3/First %d/Filter/FlateDecode/Length %d>>\nstream\n" % (len(header), len(stream))
    out += stream + b"\nendstream\nendobj\n"
    xref_at = len(out)

    def entry(kind: int, field2: int, field3: int) -> bytes:
        return bytes([kind]) + field2.to_bytes(4, "big") + field3.to_bytes(2, "big")

    table = entry(0, 0, 65535) + b"".join(entry(2, 4, index) for index in range(3))
    table += entry(1, objstm_at, 0) + entry(1, xref_at, 0)
    out += b"5 0 obj\n<</Type/XRef/Size 6/W[1 4 2]/Root 1 0 R/Length %d>>\nstream\n" % len(table)
    out += table + b"\nendstream\nendobj\nstartxref\n%d\n%%%%EOF\n" % xref_at
    return bytes(out)
