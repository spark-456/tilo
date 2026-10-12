"""I4 deterministic byte-only intake primitives; no execution, extraction or I/O.

ZIP expansion returns inert bytes, not trusted content. Callers must still perform
scope, provenance and safety screening before using any returned text or bytes.
"""

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
class Limits:
    input_bytes: int = 4 * 1024 * 1024
    expanded_bytes: int = 16 * 1024 * 1024
    entries: int = 256
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
        if any(
            value > (32 * 1024 * 1024 if name == "expanded_bytes" else getattr(maxima, name))
            for name, value in vars(self).items()
        ):
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
        or any(unicodedata.category(character) in ("Cc", "Cf") for character in name)
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
                or (local == "target" and re.match(r"(?:[a-zA-Z][\w+.-]*:|//)", value))
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
    size = 0
    for name, root in roots:
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
