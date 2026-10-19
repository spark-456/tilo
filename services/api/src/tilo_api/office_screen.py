"""DOCS-OUT: the text a safety check reads from a rendered Word, slide or Excel file.

The safety provider screens only PDF and images natively, so a rendered Office file would stay `unscreened` and the
owner route (which serves only `clean` output) would never open it. The store screens exact stored bytes; with this
converter it screens every text run in the file's XML parts instead (the strict upload parser refuses the printer
settings and chart workbooks that rendered decks and reports carry). Bounded: any oversize or unreadable package
raises, which the store records as `unscreened` (fail closed).
"""

import html
import io
import re
import zipfile

_OFFICE = "application/vnd.openxmlformats-officedocument."
TYPES = frozenset(
    _OFFICE + kind for kind in ("wordprocessingml.document", "presentationml.presentation", "spreadsheetml.sheet")
)
_PARTS = ("word/", "ppt/slides/", "ppt/notesSlides/", "ppt/charts/", "xl/worksheets/", "xl/sharedStrings", "xl/charts/")
_RUN = re.compile(r"<(?:[A-Za-z0-9]+:)?(?:t|v)(?:\s[^>]*)?>([^<]*)</", re.DOTALL)
MAX_PARTS, MAX_PART_BYTES, MAX_TEXT = 400, 4 * 1024 * 1024, 2_000_000


def office_text(content: bytes, mime: str) -> str:
    if mime not in TYPES:
        raise ValueError("not an Office type")
    texts: list[str] = []
    with zipfile.ZipFile(io.BytesIO(content)) as package:
        infos = package.infolist()
        if len(infos) > MAX_PARTS:
            raise ValueError("too many parts")
        for info in infos:
            if info.filename.endswith(".xml") and info.filename.startswith(_PARTS):
                if info.file_size > MAX_PART_BYTES:
                    raise ValueError("part too large")
                texts.extend(html.unescape(run) for run in _RUN.findall(package.read(info).decode("utf-8")))
    text = "\n".join(texts)
    if len(text) > MAX_TEXT:
        raise ValueError("too much text")
    return text
