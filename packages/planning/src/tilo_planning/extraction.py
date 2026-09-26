"""File typing and text extraction for intake (FR-INT-02), stdlib only. PDF, PNG and JPG go to models
natively (no text); DOCX, PPTX, XLSX and CSV are converted to text. Uploads are untrusted: decompressed
bytes are bounded while reading, and an XML part with a DTD fails (OOXML never has one).
"""

from __future__ import annotations

import io
import zipfile
import zlib
from pathlib import PurePosixPath
from xml.parsers import expat

MAX_ZIP_MEMBERS = 5000
MAX_EXTRACTED_BYTES = 100 * 1024 * 1024

_OOXML = "application/vnd.openxmlformats-officedocument."
# extension -> (kind, mime type, magic prefix)
FILE_TYPES: dict[str, tuple[str, str, bytes]] = {
    ".pdf": ("native", "application/pdf", b"%PDF-"),
    ".png": ("native", "image/png", b"\x89PNG\r\n\x1a\n"),
    ".jpg": ("native", "image/jpeg", b"\xff\xd8\xff"),
    ".jpeg": ("native", "image/jpeg", b"\xff\xd8\xff"),
    ".docx": ("converted", _OOXML + "wordprocessingml.document", b"PK\x03\x04"),
    ".pptx": ("converted", _OOXML + "presentationml.presentation", b"PK\x03\x04"),
    ".xlsx": ("converted", _OOXML + "spreadsheetml.sheet", b"PK\x03\x04"),
    ".csv": ("converted", "text/csv", b""),
}

# Text-bearing parts per format; every text run in them is kept, hidden or not, so screening sees it.
_PARTS = {
    ".docx": ("word/",),
    ".pptx": ("ppt/slides/", "ppt/notesSlides/", "ppt/comments/"),
    ".xlsx": ("xl/sharedStrings.xml", "xl/worksheets/", "xl/comments"),
}
_TEXT_TAGS = {"t", "delText", "v"}  # w:t / a:t / xlsx t, tracked deletions, cell values
_BREAK_TAGS = {"p", "row", "si"}


class ExtractionError(Exception):
    pass


def file_type(filename: str) -> tuple[str, str, bytes] | None:
    """(kind "native" | "converted", mime type, magic prefix), or None when the type is not accepted."""
    return FILE_TYPES.get(PurePosixPath(filename.lower()).suffix)


def extract(filename: str, content: bytes) -> str | None:
    """Text of a converted file, None for a native one; ExtractionError if it cannot be read safely."""
    ext = PurePosixPath(filename.lower()).suffix
    kind, _mime, magic = FILE_TYPES[ext]
    if not content.startswith(magic):
        raise ExtractionError(f"content does not look like a {ext} file")
    if kind == "native":
        return None
    if ext == ".csv":
        return content.decode("utf-8-sig", errors="replace")
    return _ooxml_text(content, _PARTS[ext])


def _ooxml_text(content: bytes, prefixes: tuple[str, ...]) -> str:
    try:
        with zipfile.ZipFile(io.BytesIO(content)) as zf:
            members = zf.infolist()
            if len(members) > MAX_ZIP_MEMBERS:
                raise ExtractionError("too many parts in the package")
            budget = MAX_EXTRACTED_BYTES
            chunks: list[str] = []
            for info in sorted(members, key=lambda i: i.filename):
                if not info.filename.endswith(".xml") or not info.filename.startswith(prefixes):
                    continue
                with zf.open(info) as part:
                    data = part.read(budget + 1)
                budget -= len(data)
                if budget < 0:
                    raise ExtractionError("package expands beyond the size limit")
                chunks.append(_xml_text(data))
    except (zipfile.BadZipFile, zipfile.LargeZipFile, NotImplementedError, RuntimeError, EOFError, zlib.error) as exc:
        raise ExtractionError(f"unreadable package: {exc}") from exc
    return "\n".join(c for c in chunks if c)


def _xml_text(data: bytes) -> str:
    out: list[str] = []
    depth_in_text = 0

    def reject_dtd(*_args: object) -> None:
        raise ExtractionError("XML part declares a DTD")

    def start(name: str, _attrs: object) -> None:
        nonlocal depth_in_text
        if name.rsplit(" ", 1)[-1] in _TEXT_TAGS:
            depth_in_text += 1

    def end(name: str) -> None:
        nonlocal depth_in_text
        local = name.rsplit(" ", 1)[-1]
        if local in _TEXT_TAGS:
            depth_in_text -= 1
        elif local in _BREAK_TAGS:
            out.append("\n")

    def chars(text: str) -> None:
        if depth_in_text:
            out.append(text)

    parser = expat.ParserCreate(namespace_separator=" ")
    parser.StartDoctypeDeclHandler = reject_dtd
    parser.EntityDeclHandler = reject_dtd
    parser.StartElementHandler = start
    parser.EndElementHandler = end
    parser.CharacterDataHandler = chars
    try:
        parser.Parse(data, True)
    except expat.ExpatError as exc:
        raise ExtractionError(f"malformed XML: {exc}") from exc
    return "".join(out).strip()
