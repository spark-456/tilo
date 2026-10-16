"""The kinds of work Tilo offers to produce (FR-INT-04, INTAKE-QUALITY-1 slice 3, BQ-IQ1-5). The deliverables question
lists the kinds `config/deliverable_kinds.yaml` marks available instead of a bare "which format?"; a person may pick
several. A kind that needs work that has not shipped (`available: false`, with `needs`) is never offered. The file is
configuration, not code: no kind or subject is named here, and a bad file fails loudly at load
(`DeliverableKindsError`)."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

DEFAULT_KINDS_CONFIG = Path(__file__).resolve().parents[4] / "config" / "deliverable_kinds.yaml"
MAX_CHOICES = 6  # kinds offered at once
MAX_LABEL = 60
FORMATS = (  # brief.schema.json deliverable formats (a test pins this list to the contract's)
    "pdf",
    "pptx",
    "docx",
    "xlsx",
    "csv",
    "markdown",
    "google_slides",
    "google_docs",
    "google_sheets",
    "email",
    "in_app",
    "app",
    "website",
)
_SLUG = re.compile(r"[a-z][a-z0-9_]{0,63}")
_NEEDS = re.compile(r"[A-Za-z0-9][A-Za-z0-9 ._-]{0,39}")
_BAD_LABEL = re.compile(r"[;,+&/<>`\x00-\x1f\x7f]")  # the separators of a multi-choice answer, markup and controls
_KEYS = {"id", "label", "format", "available"}


class DeliverableKindsError(Exception):
    """The kinds config is missing or invalid; nothing is offered on a guess."""


@dataclass(frozen=True)
class DeliverableKind:
    id: str
    label: str  # the deliverable's title when chosen
    format: str


@dataclass(frozen=True)
class UnavailableKind(DeliverableKind):
    """A kind that is not offered yet; `needs` names what must ship first. Naming one in an answer is refused."""

    needs: str


@dataclass(frozen=True)
class KindsConfig:
    offered: tuple[DeliverableKind, ...]  # the available kinds, in file order, at most MAX_CHOICES
    unavailable: tuple[UnavailableKind, ...]  # the others, in file order


def _kind(entry: Any, index: int) -> tuple[DeliverableKind, bool, str | None]:
    where = f"kinds[{index}]"
    if not isinstance(entry, dict) or not _KEYS <= set(entry) <= _KEYS | {"needs"}:
        raise DeliverableKindsError(f"{where} must have id, label, format and available (and needs)")
    ident, label, fmt, available = entry["id"], entry["label"], entry["format"], entry["available"]
    if not isinstance(ident, str) or not _SLUG.fullmatch(ident):
        raise DeliverableKindsError(f"{where}.id must be a lower-case slug")
    if not isinstance(label, str) or not label.strip() or len(label) > MAX_LABEL or _BAD_LABEL.search(label):
        raise DeliverableKindsError(f"{where}.label must be plain text of 1 to {MAX_LABEL} characters")
    if label != " ".join(label.split()):
        raise DeliverableKindsError(f"{where}.label must have single spaces and no edge spaces")
    if fmt not in FORMATS:
        raise DeliverableKindsError(f"{where}.format is not a deliverable format")
    if not isinstance(available, bool):
        raise DeliverableKindsError(f"{where}.available must be true or false")
    needs = entry.get("needs")
    if (needs is not None and not (isinstance(needs, str) and _NEEDS.fullmatch(needs))) or (
        not available and needs is None
    ):
        raise DeliverableKindsError(f"{where}.needs must name what must ship first, and is required when unavailable")
    return DeliverableKind(ident, label, fmt), available, needs


_CACHE: dict[Path, tuple[tuple[int, int], KindsConfig]] = {}  # path -> ((mtime, size), parsed): a good parse only


def load_kinds(path: Path | None = None) -> KindsConfig:
    """The kinds config, every entry checked, available or not. Parsed again only when the file changes."""
    path = DEFAULT_KINDS_CONFIG if path is None else path
    try:
        info = path.stat()
    except OSError as error:
        raise DeliverableKindsError(f"cannot read {path.name}: {type(error).__name__}") from error
    stamp = (info.st_mtime_ns, info.st_size)
    cached = _CACHE.get(path)
    if cached is None or cached[0] != stamp:
        cached = _CACHE[path] = (stamp, _parse(path))
    return cached[1]


def load_deliverable_kinds(path: Path | None = None) -> tuple[DeliverableKind, ...]:
    """The available kinds in file order (at most `MAX_CHOICES`)."""
    return load_kinds(path).offered


def _parse(path: Path) -> KindsConfig:
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError, UnicodeError) as error:
        raise DeliverableKindsError(f"cannot read {path.name}: {type(error).__name__}") from error
    if not isinstance(data, dict) or set(data) != {"kinds"} or not isinstance(data["kinds"], list):
        raise DeliverableKindsError("the kinds config must be a mapping with only a `kinds` list")
    read = [_kind(entry, i) for i, entry in enumerate(data["kinds"])]
    ids, labels = [k.id for k, _, _ in read], [k.label.casefold() for k, _, _ in read]
    if len(ids) != len(set(ids)) or len(labels) != len(set(labels)):
        raise DeliverableKindsError("kind ids and labels must be unique")
    offered = tuple(kind for kind, available, _ in read if available)
    if len(offered) > MAX_CHOICES:
        raise DeliverableKindsError(f"at most {MAX_CHOICES} kinds may be available")
    withheld = tuple(
        UnavailableKind(kind.id, kind.label, kind.format, str(needs))
        for kind, available, needs in read
        if not available
    )
    return KindsConfig(offered, withheld)
