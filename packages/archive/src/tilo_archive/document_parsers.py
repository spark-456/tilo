"""I4 deterministic byte-only intake primitives; no execution, extraction or I/O.

ZIP expansion returns inert bytes, not trusted content. Callers must still perform
scope, provenance and safety screening before using any returned text or bytes.
"""

import csv
import io
import re
import stat
import unicodedata
import xml.etree.ElementTree as ET
import zipfile
import zlib
from collections.abc import Iterator
from dataclasses import dataclass, field


class Refused(ValueError):
    """Stable refusal code only: never include uploaded names or content."""


@dataclass(frozen=True)
class DocumentRead:
    """Inert cited text and parser capabilities; no safety or understanding verdict."""

    fragments: tuple[tuple[str, str], ...]
    read: tuple[str, ...]
    skipped: tuple[str, ...]


@dataclass(frozen=True)
class Limits:
    input_bytes: int = 4 * 1024 * 1024
    expanded_bytes: int = 16 * 1024 * 1024
    entries: int = 256
    cells: int = 4096
    paragraphs: int = 2048
    nesting: int = 2
    path_depth: int = 16
    ratio: int = 100
    xml_nodes: int = 20000
    xml_depth: int = 64
    xml_attributes: int = 20000
    xml_part_bytes: int = 1024 * 1024
    output_chars: int = 1024 * 1024

    def validate(self) -> None:
        if any(
            type(value) is not int or value <= 0
            for value in (
                self.input_bytes,
                self.expanded_bytes,
                self.entries,
                self.cells,
                self.paragraphs,
                self.path_depth,
                self.ratio,
                self.xml_nodes,
                self.xml_depth,
                self.xml_attributes,
                self.xml_part_bytes,
                self.output_chars,
            )
        ):
            raise ValueError("invalid_limits")
        if type(self.nesting) is not int or self.nesting < 0:
            raise ValueError("invalid_limits")
        maxima = Limits()
        ceilings = {"expanded_bytes": 32 * 1024 * 1024, "cells": 8192, "paragraphs": 4096}
        if any(value > ceilings.get(name, getattr(maxima, name)) for name, value in vars(self).items()):
            raise ValueError("invalid_limits")


@dataclass
class _Budget:
    expanded: int = 0
    entries: int = 0
    paths: set[str] = field(default_factory=set)


@dataclass
class _XmlBudget:
    nodes: int = 0
    attributes: int = 0


def _path(name: str, limits: Limits) -> None:
    parts = name.removesuffix("/").split("/")
    if (
        any(part in ("", ".", "..") for part in parts)
        or any(character in name for character in ("\\", ":", "\x00"))
        or any(unicodedata.category(character) in ("Cc", "Cf", "Zl", "Zp", "Cs", "Co", "Cn") for character in name)
    ):
        raise Refused("unsafe_path")
    if len(parts) > limits.path_depth:
        raise Refused("path_depth")


def _expand(data: bytes, limits: Limits, budget: _Budget, depth: int, prefix: str) -> list[tuple[str, bytes]]:
    if depth > limits.nesting:
        raise Refused("nesting")
    output: list[tuple[str, bytes]] = []
    with zipfile.ZipFile(io.BytesIO(data)) as handle:
        infos = handle.infolist()
        budget.entries += len(infos)
        if budget.entries > limits.entries:
            raise Refused("entry_count")
        names: set[str] = set()
        for info in infos:
            # orig_filename retains NULs that ZipInfo.filename otherwise truncates.
            _path(info.orig_filename, limits)
            label = prefix + info.filename.rstrip("/")
            _path(label, limits)
            canonical = unicodedata.normalize("NFC", label).casefold()
            if canonical in names:
                raise Refused("duplicate_path")
            names.add(canonical)
            mode = stat.S_IFMT(info.external_attr >> 16)
            if mode not in (0, stat.S_IFREG, stat.S_IFDIR):
                raise Refused("special_entry")
            if info.flag_bits & 1:
                raise Refused("encrypted_zip")
            if info.compress_type not in (zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED):
                raise Refused("compression_method")
            budget.expanded += info.file_size
            if budget.expanded > limits.expanded_bytes:
                raise Refused("expanded_size")
            if info.file_size > limits.ratio * max(1, info.compress_size):
                raise Refused("compression_ratio")
        for info in infos:
            if info.is_dir():
                continue
            with handle.open(info) as source:
                content = source.read(min(info.file_size, limits.expanded_bytes) + 1)
            if len(content) != info.file_size:
                raise Refused("invalid_zip")
            label = prefix + info.filename
            if content.startswith(b"PK"):
                output.extend(_expand(content, limits, budget, depth + 1, label + "/"))
            else:
                canonical = unicodedata.normalize("NFC", label).casefold()
                if canonical in budget.paths:
                    raise Refused("duplicate_path")
                budget.paths.add(canonical)
                output.append((label, content))
    return output


def expand_zip(data: bytes, *, limits: Limits = Limits()) -> tuple[tuple[str, bytes], ...]:
    """Expand nested ZIPs in stored order under shared byte/entry/depth budgets.

    No paths are written. Every level counts toward the decompression budget,
    including nested ZIP containers. Unsupported/encrypted/corrupt ZIPs fail closed.
    """
    limits.validate()
    if len(data) > limits.input_bytes:
        raise Refused("input_size")
    try:
        return tuple(_expand(data, limits, _Budget(), 0, ""))
    except Refused:
        raise
    except (zipfile.BadZipFile, RuntimeError, NotImplementedError, EOFError, OSError, ValueError, zlib.error):
        pass
    raise Refused("invalid_zip")


class _BoundedTree(ET.TreeBuilder):
    def __init__(self, limits: Limits, budget: _XmlBudget) -> None:
        super().__init__()
        self.limits, self.budget, self.depth = limits, budget, 0

    def start(self, tag: str, attrs: dict[str, str]) -> ET.Element:
        self.budget.nodes += 1
        self.budget.attributes += len(attrs)
        self.depth += 1
        if self.budget.nodes > self.limits.xml_nodes:
            raise Refused("xml_nodes")
        if self.depth > self.limits.xml_depth:
            raise Refused("xml_depth")
        if self.budget.attributes > self.limits.xml_attributes:
            raise Refused("xml_attributes")
        for key, value in attrs.items():
            value = value.strip()
            local = key.rsplit("}", 1)[-1].lower()
            if local == "contenttype" and "macroenabled" in value.lower():
                raise Refused("active_content")
            if local == "type" and any(marker in value.lower() for marker in ("vbaproject", "oleobject", "activex")):
                raise Refused("active_content")
            if (
                (local == "targetmode" and value.lower() == "external")
                or local == "base"
                or (local == "target" and (value.startswith("\\\\") or re.match(r"(?:[a-zA-Z][\w+.-]*:|//)", value)))
            ):
                raise Refused("external_reference")
        return super().start(tag, attrs)

    def end(self, tag: str) -> ET.Element:
        node = super().end(tag)
        self.depth -= 1
        return node


def _xml(data: bytes, limits: Limits, budget: _XmlBudget) -> ET.Element:
    # Bound a whole start tag before Expat can allocate its attributes, too.
    if len(data) > limits.xml_part_bytes:
        raise Refused("xml_part_size")
    try:
        text = data.decode("utf-8-sig")
        if "<!DOCTYPE" in text.upper() or "<!ENTITY" in text.upper():
            raise Refused("xml_declaration")
        parser = ET.XMLParser(target=_BoundedTree(limits, budget))
        for offset in range(0, len(text), 4096):
            parser.feed(text[offset : offset + 4096])
        return parser.close()
    except (UnicodeError, ET.ParseError):
        pass
    raise Refused("invalid_xml")


def _office(
    data: bytes, limits: Limits, main: str, kind: str, tag: str, *, first: str | None = None
) -> Iterator[tuple[str, ET.Element]]:
    parts = dict(expand_zip(data, limits=limits))
    if main not in parts or kind.encode() not in parts.get("[Content_Types].xml", b""):
        raise Refused("unknown_type")
    budget = _XmlBudget()
    main_ok = types_ok = False
    for name in sorted(parts, key=lambda name: name != first):
        content = parts[name]
        lower = name.lower()
        if (
            lower.endswith((".bin", ".docm", ".xlsm", ".pptm"))
            or any(marker in lower for marker in ("vbaproject", "activex/", "embeddings/"))
            or (lower == "[content_types].xml" and b"macroenabled" in content.lower())
        ):
            raise Refused("active_content")
        if "externallinks/" in lower:
            raise Refused("external_reference")
        if lower.endswith((".xml", ".rels")):
            root = _xml(content, limits, budget)
            if name == main:
                main_ok = root.tag == tag
            if name == "[Content_Types].xml":
                types_ok = any(node.get("PartName") == "/" + main and node.get("ContentType") == kind for node in root)
            yield name, root
            del root
    if not main_ok or not types_ok:
        raise Refused("unknown_type")


def parse_docx(data: bytes, *, limits: Limits = Limits()) -> tuple[tuple[str, str], ...]:
    """Read UTF-8 paragraphs with part citations, screening and dropping each XML tree."""
    word = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
    roots = _office(
        data,
        limits,
        "word/document.xml",
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml",
        word + "document",
    )
    output: list[tuple[str, str]] = []
    size = paragraphs = 0
    for name, root in roots:
        if not name.startswith("word/"):
            continue
        for index, paragraph in enumerate(root.iter(word + "p"), 1):
            paragraphs += 1
            if paragraphs > limits.paragraphs:
                raise Refused("paragraph_count")
            text = "".join(node.text or "" for node in paragraph.iter(word + "t"))
            size += len(text)
            if size > limits.output_chars:
                raise Refused("output_size")
            if text:
                output.append((f"{name}#p{index}", text))
    return tuple(output)


def parse_xlsx(data: bytes, *, limits: Limits = Limits()) -> tuple[tuple[str, str], ...]:
    """Read stored worksheet values with package-part/cell provenance.

    Shared/inline strings are resolved; formula cached values remain inert text.
    Missing cached values are empty. No formulas, styles, dates or layouts evaluated.
    """
    sheet = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
    roots = _office(
        data,
        limits,
        "xl/workbook.xml",
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml",
        sheet + "workbook",
        first="xl/sharedStrings.xml",
    )

    def string(node: ET.Element) -> str:
        return "".join(
            item.text or "" for path in (sheet + "t", sheet + "r/" + sheet + "t") for item in node.findall(path)
        )

    strings: list[str] = []
    output: list[tuple[str, str]] = []
    size = 0
    cells = 0
    for name, root in roots:
        if name == "xl/sharedStrings.xml":
            if root.tag != sheet + "sst":
                raise Refused("invalid_spreadsheet")
            strings = [string(item) for item in root.findall(sheet + "si")]
            continue
        if not name.startswith("xl/worksheets/") or not name.endswith(".xml"):
            continue
        if root.tag != sheet + "worksheet":
            raise Refused("invalid_spreadsheet")
        seen: set[str] = set()
        for cell in root.iter(sheet + "c"):
            cells += 1
            if cells > limits.cells:
                raise Refused("cell_count")
            ref = cell.get("r", "")
            if not re.fullmatch(r"[A-Z]{1,3}[1-9][0-9]{0,6}", ref) or ref in seen:
                raise Refused("invalid_spreadsheet")
            seen.add(ref)
            kind = cell.get("t", "n")
            value = cell.findtext(sheet + "v", "")
            if kind == "s":
                if not re.fullmatch(r"[0-9]+", value) or len(value) > 9 or int(value) >= len(strings):
                    raise Refused("invalid_spreadsheet")
                value = strings[int(value)]
            elif kind == "inlineStr":
                inline = cell.find(sheet + "is")
                value = "" if inline is None else string(inline)
            elif kind not in ("n", "b", "d", "str", "e"):
                raise Refused("invalid_spreadsheet")
            size += len(value)
            if size > limits.output_chars:
                raise Refused("output_size")
            output.append((f"{name}#{ref}", value))
    return tuple(output)


def parse_pptx(data: bytes, *, limits: Limits = Limits()) -> tuple[tuple[str, str], ...]:
    """Read slide DrawingML paragraphs in stored part order, with part citations.

    Tables contribute paragraphs; explicit line breaks are preserved. No rendering,
    slide-order inference, notes, layouts, images, animation or field evaluation.
    """
    presentation = "{http://schemas.openxmlformats.org/presentationml/2006/main}"
    drawing = "{http://schemas.openxmlformats.org/drawingml/2006/main}"
    roots = _office(
        data,
        limits,
        "ppt/presentation.xml",
        "application/vnd.openxmlformats-officedocument.presentationml.presentation.main+xml",
        presentation + "presentation",
    )
    output: list[tuple[str, str]] = []
    size = paragraphs = 0
    for name, root in roots:
        if not re.fullmatch(r"ppt/slides/slide[1-9][0-9]*\.xml", name):
            continue
        if root.tag != presentation + "sld":
            raise Refused("invalid_presentation")
        for index, paragraph in enumerate(root.iter(drawing + "p"), 1):
            paragraphs += 1
            if paragraphs > limits.paragraphs:
                raise Refused("paragraph_count")
            text = "".join(
                "\n" if node.tag == drawing + "br" else node.text or ""
                for node in paragraph.iter()
                if node.tag in (drawing + "t", drawing + "br")
            )
            size += len(text)
            if size > limits.output_chars:
                raise Refused("output_size")
            if text:
                output.append((f"{name}#p{index}", text))
    return tuple(output)


def _csv_cell_preflight(text: str, limit: int) -> None:
    """Count cells before csv.reader can allocate a large row, without a row list.

    Match its fixed comma/double-quote dialect; syntax validation stays with the
    reader. Quoted newlines/commas and doubled quotes remain inert cell text.
    """
    cells = index = 0
    quoted = active = False
    field_start = True
    while index < len(text):
        char = text[index]
        if quoted:
            if char == '"':
                if index + 1 < len(text) and text[index + 1] == '"':
                    index += 2
                    continue
                quoted = False
        else:
            if not active:
                cells += 1  # includes a blank logical row
                active = True
            if char == ",":
                cells += 1
                field_start = True
            elif char in "\r\n":
                active = False
                field_start = True
                if char == "\r" and index + 1 < len(text) and text[index + 1] == "\n":
                    index += 1
            else:
                quoted = char == '"' and field_start
                field_start = False
            if cells > limit:
                raise Refused("cell_count")
        index += 1


def parse_csv(data: bytes, *, limits: Limits = Limits()) -> tuple[tuple[str, str], ...]:
    """Read comma-separated UTF-8 cells as inert text, with logical row/cell labels.

    No dialect/encoding guesses, formula evaluation or global CSV limit changes.
    The cell budget counts every cell, including empty cells; blank rows count too.
    Python's CSV field-size limit also applies and yields a stable refusal.
    """
    limits.validate()
    if len(data) > limits.input_bytes:
        raise Refused("input_size")
    text = None
    try:
        text = data.decode("utf-8-sig")
    except UnicodeError:
        pass
    if text is None:
        raise Refused("invalid_encoding")
    if "\x00" in text:
        raise Refused("invalid_csv")
    _csv_cell_preflight(text, limits.cells)
    output: list[tuple[str, str]] = []
    entries = size = 0
    try:
        for row_index, row in enumerate(csv.reader(io.StringIO(text, newline=""), strict=True), 1):
            entries += max(1, len(row))
            if entries > limits.cells:
                raise Refused("cell_count")
            for column, cell in enumerate(row, 1):
                size += len(cell)
                if size > limits.output_chars:
                    raise Refused("output_size")
                output.append((f"csv#r{row_index}c{column}", cell))
    except csv.Error:
        pass
    else:
        return tuple(output)
    raise Refused("invalid_csv")


def read_document(data: bytes, *, kind: str, limits: Limits = Limits()) -> DocumentRead:
    """Return explicit coverage only after parsing succeeds, with original citations.

    Kind is chosen by the caller's type gate, never inferred from an uploaded name.
    Coverage describes capabilities, not a claim that each feature was present.
    Returned text still requires safety screening and a quarantined reader.
    """
    read: tuple[str, ...]
    skipped: tuple[str, ...]
    match kind:
        case "docx":
            fragments = parse_docx(data, limits=limits)
            read = ("Word paragraph text", "hidden text and comments")
            skipped = ("page layout", "images", "altChunk payloads", "field evaluation")
        case "xlsx":
            fragments = parse_xlsx(data, limits=limits)
            read = ("stored worksheet values", "hidden sheets", "cached formula values")
            skipped = ("formula evaluation", "images", "charts", "styles and date interpretation", "layout")
        case "pptx":
            fragments = parse_pptx(data, limits=limits)
            read = ("slide and table paragraphs", "hidden slides", "explicit line breaks")
            skipped = ("speaker notes", "images", "layouts", "animation", "field evaluation")
        case "csv":
            fragments = parse_csv(data, limits=limits)
            read = ("UTF-8 comma-separated cells", "quoted multiline and empty cells")
            skipped = ("formula evaluation", "dialect and encoding inference")
        case _:
            raise Refused("unknown_type")
    return DocumentRead(fragments, read, skipped)
