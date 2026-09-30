"""File typing and text extraction for intake (FR-INT-02), stdlib only. PDF, PNG and JPG go to models
natively (no text); DOCX, PPTX, XLSX and CSV are converted to text. Uploads are untrusted (PRD 16.2
cost abuse): the part count is checked before parsing, decompressed bytes come out of one budget per
request, text past MAX_TEXT_CHARS fails the file, and an XML part with a DTD fails (OOXML has none).
"""

from __future__ import annotations

import codecs
import io
import zipfile
import zlib
from pathlib import PurePosixPath
from typing import IO
from xml.parsers import expat

MAX_ZIP_MEMBERS = 5000
MAX_EXTRACTED_BYTES = 50 * 1024 * 1024  # decompressed XML read for one whole request
MAX_XML_ELEMENTS = 1_000_000  # parsed elements for one whole request: about 1.5 s of CPU
MAX_TEXT_CHARS = 200_000  # per file: more than a brief or a model context can use
MAX_CENTRAL_DIRECTORY_BYTES = 1024 * 1024  # zipfile parses this many bytes of entries
MAX_RUN_BYTES = 256 * 1024  # bytes between two '<': bounds any tag, attribute or text run expat buffers
MAX_DEPTH = 256  # nested elements; OOXML stays far below this
_CHUNK = 64 * 1024

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
_TOO_LARGE = "too large to read"
_UNSUPPORTED = "unsupported XML: only plain UTF-8 Office markup is read"


class ExtractionError(Exception):
    pass


class Budget:
    """Decompressed bytes and XML elements a request may still read, shared by all of its files."""

    def __init__(self) -> None:
        self.remaining = MAX_EXTRACTED_BYTES
        self.elements = MAX_XML_ELEMENTS


def file_type(filename: str) -> tuple[str, str, bytes] | None:
    """(kind "native" | "converted", mime type, magic prefix), or None when the type is not accepted."""
    return FILE_TYPES.get(PurePosixPath(filename.lower()).suffix)


def extract(filename: str, content: bytes, budget: Budget | None = None) -> str | None:
    """Text of a converted file, None for a native one; ExtractionError if it cannot be read safely."""
    ext = PurePosixPath(filename.lower()).suffix
    kind, _mime, magic = FILE_TYPES[ext]
    if not content.startswith(magic):
        raise ExtractionError(f"content does not look like a {ext} file")
    if kind == "native":
        return None
    if ext == ".csv":
        if len(content) > 4 * MAX_TEXT_CHARS:
            raise ExtractionError(_TOO_LARGE)
        text = content.decode("utf-8-sig", errors="replace")
        if len(text) > MAX_TEXT_CHARS:
            raise ExtractionError(_TOO_LARGE)
        return text
    return _ooxml_text(content, _PARTS[ext], budget or Budget())


def _check_directory(content: bytes) -> None:
    """Refuse an oversized central directory from its end record, before zipfile parses it. zipfile
    walks the directory's byte size, not the entry count, so the size is what is bounded."""
    end = content.rfind(b"PK\x05\x06")
    if end < 0 or len(content) - end < 22:
        raise ExtractionError("unreadable package: no end of central directory")
    if end >= 20 and content[end - 20 : end - 16] == b"PK\x06\x07":
        raise ExtractionError("zip64 packages are not accepted")
    entries = int.from_bytes(content[end + 10 : end + 12], "little")
    directory_bytes = int.from_bytes(content[end + 12 : end + 16], "little")
    if entries > MAX_ZIP_MEMBERS or directory_bytes > MAX_CENTRAL_DIRECTORY_BYTES:
        raise ExtractionError("too many parts in the package")


def _ooxml_text(content: bytes, prefixes: tuple[str, ...], budget: Budget) -> str:
    _check_directory(content)
    chunks: list[str] = []
    chars_left = MAX_TEXT_CHARS
    try:
        with zipfile.ZipFile(io.BytesIO(content)) as zf:
            members = zf.infolist()
            if len(members) > MAX_ZIP_MEMBERS:
                raise ExtractionError("too many parts in the package")
            for info in sorted(members, key=lambda i: i.filename):
                if info.filename.endswith(".xml") and info.filename.startswith(prefixes):
                    with zf.open(info) as part:
                        text = _xml_text(part, budget, chars_left)
                    chars_left -= len(text)
                    chunks.append(text)
    # ValueError covers a corrupt central directory (negative seek) and undecodable member names.
    except (
        zipfile.BadZipFile,
        zipfile.LargeZipFile,
        NotImplementedError,
        RuntimeError,
        EOFError,
        ValueError,
        OSError,
        zlib.error,
    ) as exc:
        raise ExtractionError(f"unreadable package: {exc}") from exc
    except expat.ExpatError as exc:
        raise ExtractionError(f"malformed XML: {exc}") from exc
    return "\n".join(c for c in chunks if c)


def _xml_text(part: IO[bytes], budget: Budget, chars_left: int) -> str:
    """Stream one part through expat, stopping as soon as the byte budget or text cap is spent."""
    out: list[str] = []
    depth, depth_in_text, run, seen, tail, decl_at = 0, 0, 0, 0, b"", 0
    utf8 = codecs.getincrementaldecoder("utf-8")()  # strict: any non-UTF-8 byte fails the part

    def reject_dtd(*_args: object) -> None:
        raise ExtractionError("XML part declares a DTD")

    def start(name: str, attrs: dict[str, str]) -> None:
        nonlocal depth, depth_in_text
        budget.elements -= 1 + len(attrs)  # attributes cost parse time too
        depth += 1
        if budget.elements < 0 or depth > MAX_DEPTH:
            raise ExtractionError(_TOO_LARGE)
        if name.rsplit(" ", 1)[-1] in _TEXT_TAGS:
            depth_in_text += 1

    def end(name: str) -> None:
        nonlocal depth, depth_in_text
        depth -= 1
        local = name.rsplit(" ", 1)[-1]
        if local in _TEXT_TAGS:
            depth_in_text -= 1
        elif local in _BREAK_TAGS:
            keep("\n")

    def chars(text: str) -> None:
        if depth_in_text:
            keep(text)

    def keep(text: str) -> None:
        nonlocal chars_left
        chars_left -= len(text)
        if chars_left < 0:
            raise ExtractionError(_TOO_LARGE)
        out.append(text)

    def check_raw(chunk: bytes) -> None:
        """expat buffers a whole token before any handler runs, so tokens are bounded in the raw bytes.
        Only plain UTF-8 markup is read (what Office writes): valid UTF-8 with no NUL byte (so expat
        never switches to UTF-16, where 0x3C can be half of another character, with or without a BOM),
        no `<!` (comment, DTD, CDATA) and no `<?` but the leading XML declaration. In what remains every
        0x3C byte starts a tag and none can sit inside one, so the run between two of them bounds every
        tag, attribute list and text run expat holds."""
        nonlocal run, tail, seen, decl_at
        try:
            utf8.decode(chunk)
        except UnicodeDecodeError as exc:
            raise ExtractionError(_UNSUPPORTED) from exc
        window = tail + chunk
        if seen == 0:  # the declaration sits first (after an optional UTF-8 BOM) and closes within 256 bytes
            decl_at = 3 if chunk.startswith(b"\xef\xbb\xbf") else 0
            if chunk.startswith(b"<?", decl_at) and b"?>" not in chunk[decl_at : decl_at + 256]:
                raise ExtractionError(_UNSUPPORTED)
        if b"\x00" in chunk or b"<!" in window:
            raise ExtractionError(_UNSUPPORTED)
        at = window.find(b"<?")
        while at >= 0:
            if seen - len(tail) + at != decl_at:
                raise ExtractionError(_UNSUPPORTED)
            at = window.find(b"<?", at + 1)
        tail, seen = chunk[-1:], seen + len(chunk)
        pieces = chunk.split(b"<")
        if len(pieces) == 1:
            run += len(chunk)
        else:  # the run carried over ends at the first '<'; the last piece carries on into the next chunk
            if max([run + len(pieces[0]), *map(len, pieces[1:-1])]) > MAX_RUN_BYTES:
                raise ExtractionError(_TOO_LARGE)
            run = len(pieces[-1])
        if run > MAX_RUN_BYTES:
            raise ExtractionError(_TOO_LARGE)

    parser = expat.ParserCreate("UTF-8", " ")
    parser.buffer_text = True  # one character-data call between tags, however many lines
    parser.StartDoctypeDeclHandler = reject_dtd
    parser.EntityDeclHandler = reject_dtd
    parser.StartElementHandler = start
    parser.EndElementHandler = end
    parser.CharacterDataHandler = chars
    while chunk := part.read(_CHUNK):
        budget.remaining -= len(chunk)
        if budget.remaining < 0:
            raise ExtractionError(f"the files expand past the {MAX_EXTRACTED_BYTES // (1024 * 1024)} MB read limit")
        check_raw(chunk)
        parser.Parse(chunk, False)
    parser.Parse(b"", True)
    return "".join(out).strip()
