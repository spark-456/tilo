"""I4 deterministic byte-only intake primitives; no execution, extraction or I/O.

ZIP expansion returns inert bytes, not trusted content. Callers must still perform
scope, provenance and safety screening before using any returned text or bytes.
"""

import csv
import io
import re
import stat
import xml.etree.ElementTree as ET
import zipfile
import zlib
from dataclasses import dataclass, field


class Refused(ValueError):
    """Stable refusal code only: never include uploaded names or content."""


@dataclass(frozen=True)
class Limits:
    input_bytes: int = 4 * 1024 * 1024
    expanded_bytes: int = 16 * 1024 * 1024
    entries: int = 256
    nesting: int = 2
    path_depth: int = 16
    ratio: int = 100
    xml_nodes: int = 20000
    xml_depth: int = 64
    output_chars: int = 1024 * 1024

    def validate(self) -> None:
        if any(
            type(value) is not int or value <= 0
            for value in (
                self.input_bytes,
                self.expanded_bytes,
                self.entries,
                self.path_depth,
                self.ratio,
                self.xml_nodes,
                self.xml_depth,
                self.output_chars,
            )
        ):
            raise ValueError("invalid_limits")
        if type(self.nesting) is not int or self.nesting < 0:
            raise ValueError("invalid_limits")


@dataclass
class _Budget:
    expanded: int = 0
    entries: int = 0
    paths: set[str] = field(default_factory=set)


def _path(name: str, limits: Limits) -> None:
    parts = name.removesuffix("/").split("/")
    if (
        any(part in ("", ".", "..") for part in parts)
        or any(character in name for character in ("\\", ":", "\x00"))
        or any(ord(character) < 32 for character in name)
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
            if label in names:
                raise Refused("duplicate_path")
            names.add(label)
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
                if label in budget.paths:
                    raise Refused("duplicate_path")
                budget.paths.add(label)
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
        raise Refused("invalid_zip") from None


def _xml(data: bytes, limits: Limits) -> ET.Element:
    try:
        text = data.decode("utf-8-sig")
        if "<!DOCTYPE" in text.upper() or "<!ENTITY" in text.upper():
            raise Refused("xml_declaration")
        root = ET.fromstring(text)
    except (UnicodeError, ET.ParseError):
        raise Refused("invalid_xml") from None
    pending = [(root, 1)]
    nodes = 0
    while pending:
        node, depth = pending.pop()
        nodes += 1
        if nodes > limits.xml_nodes:
            raise Refused("xml_nodes")
        if depth > limits.xml_depth:
            raise Refused("xml_depth")
        for key, value in node.attrib.items():
            value = value.strip()
            local = key.rsplit("}", 1)[-1].lower()
            if local == "contenttype" and "macroenabled" in value.lower():
                raise Refused("active_content")
            if local == "type" and any(marker in value.lower() for marker in ("vbaproject", "oleobject", "activex")):
                raise Refused("active_content")
            if (
                (local == "targetmode" and value.lower() == "external")
                or local == "base"
                or (local == "target" and re.match(r"(?:[a-zA-Z][\w+.-]*:|//)", value))
            ):
                raise Refused("external_reference")
        pending.extend((child, depth + 1) for child in node)
    return root


def parse_docx(data: bytes, *, limits: Limits = Limits()) -> tuple[tuple[str, str], ...]:
    """Read UTF-8 DOCX paragraph text; refuse active content and external references.

    All XML parts are screened, including parts that contribute no returned text.
    Paragraph labels cite package parts, not page numbers (pagination needs layout).
    """
    parts = dict(expand_zip(data, limits=limits))
    kind = b"application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"
    if "word/document.xml" not in parts or kind not in parts.get("[Content_Types].xml", b""):
        raise Refused("unknown_type")
    roots: dict[str, ET.Element] = {}
    for name, content in parts.items():
        lower = name.lower()
        if (
            lower.endswith((".bin", ".docm", ".xlsm", ".pptm"))
            or any(marker in lower for marker in ("vbaproject", "activex/", "embeddings/"))
            or (lower == "[content_types].xml" and b"macroenabled" in content.lower())
        ):
            raise Refused("active_content")
        if lower.endswith((".xml", ".rels")):
            roots[name] = _xml(content, limits)
    word = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
    if roots["word/document.xml"].tag != word + "document" or not any(
        node.attrib.get("PartName") == "/word/document.xml" and node.attrib.get("ContentType") == kind.decode()
        for node in roots["[Content_Types].xml"]
    ):
        raise Refused("unknown_type")
    output: list[tuple[str, str]] = []
    size = 0
    for name, root in roots.items():
        if not name.startswith("word/"):
            continue
        for index, paragraph in enumerate(root.iter(word + "p"), 1):
            text = "".join(node.text or "" for node in paragraph.iter(word + "t"))
            size += len(text)
            if size > limits.output_chars:
                raise Refused("output_size")
            if text:
                output.append((f"{name}#p{index}", text))
    return tuple(output)


def parse_csv(data: bytes, *, limits: Limits = Limits()) -> tuple[tuple[str, str], ...]:
    """Read comma-separated UTF-8 cells as inert text, with logical row/cell labels.

    No dialect/encoding guesses, formula evaluation or global CSV limit changes.
    The entry budget counts every cell, including empty cells; blank rows count too.
    Python's CSV field-size limit also applies and yields a stable refusal.
    """
    limits.validate()
    if len(data) > limits.input_bytes:
        raise Refused("input_size")
    try:
        text = data.decode("utf-8-sig")
    except UnicodeError:
        raise Refused("invalid_encoding") from None
    if "\x00" in text:
        raise Refused("invalid_csv")
    output: list[tuple[str, str]] = []
    entries = size = 0
    try:
        for row_index, row in enumerate(csv.reader(io.StringIO(text, newline=""), strict=True), 1):
            entries += max(1, len(row))
            if entries > limits.entries:
                raise Refused("entry_count")
            for column, cell in enumerate(row, 1):
                size += len(cell)
                if size > limits.output_chars:
                    raise Refused("output_size")
                output.append((f"csv#r{row_index}c{column}", cell))
    except csv.Error:
        raise Refused("invalid_csv") from None
    return tuple(output)
