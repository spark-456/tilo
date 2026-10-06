"""Best effort before refusal (FR-INT-15, PRD 7.1, BQ-INT15-1..9). A safe task may have parts Tilo cannot do. The
Director only names each such part as `{category, part}`; `category` is an id of `config/capability_gaps.yaml` and
`part` a short label. Everything a person reads about a gap (the reason, the alternative, the lead when no part is
possible) is configured text beside the label cleaned here, so no model-written claim about what Tilo can or cannot
do reaches a person. A refusal id (FR-INT-12) is never a gap; that rule is enforced in `brief.extract_brief`."""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from tilo_planning.refusal import RefusalConfigError

_ROOT = Path(__file__).resolve().parents[4] / "config"
DEFAULT_GAP_CONFIG = _ROOT / "capability_gaps.yaml"
DEFAULT_CONNECTORS = _ROOT / "connectors.yaml"
MAX_GAPS = 3  # gaps per task, after de-duplication
MAX_PART = 60  # characters of a part label, raw and cleaned
MAX_REASON, MAX_ALTERNATIVE, MAX_LEAD = 120, 200, 200  # config text limits
GAP_LINE = "Not done: {part}. {reason}"  # one skips line: at most 10 + 60 + 2 + 120 = 192 <= 200 (plan.schema.json)
_SLUG = re.compile(r"[a-z][a-z0-9_]{0,63}")  # common.schema.json slug
_KEYS = {"id", "reason", "alternative"}


class GapConfigError(RefusalConfigError):
    """The gap config (or the connector list it reads) is missing or invalid. A subclass of the refusal config
    error, so tilo-api's existing fail-closed 503 covers it."""


@dataclass(frozen=True)
class GapCategory:
    id: str
    reason: str
    alternative: str


@dataclass(frozen=True)
class GapPolicy:
    categories: Sequence[GapCategory]  # file order
    nothing_possible: str  # the lead line when no part is possible
    services: Sequence[str]  # `name` of every entry of config/connectors.yaml, file order

    def get(self, category_id: str) -> GapCategory | None:
        return next((c for c in self.categories if c.id == category_id), None)  # exact match only


@dataclass(frozen=True)
class Gap:
    category: str
    part: str  # cleaned by `clean_part`
    reason: str  # configured text
    alternative: str  # configured text

    def skip_line(self) -> str:
        return GAP_LINE.format(part=self.part, reason=self.reason)

    def as_dict(self) -> dict[str, str]:
        return {"category": self.category, "part": self.part, "reason": self.reason, "alternative": self.alternative}


class NothingPossible(Exception):
    """The task is acceptable but Tilo can do no part of it. Not a refusal; holds only configured text and cleaned
    labels, and `str(exc)` holds only category ids."""

    def __init__(self, gaps: tuple[Gap, ...], message: str) -> None:
        super().__init__("nothing possible: " + ", ".join(g.category for g in gaps))
        self.gaps, self.message = gaps, message


def _text(value: Any, where: str, limit: int) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > limit:
        raise GapConfigError(f"{where} must be text of 1 to {limit} characters")
    return value


def _category(entry: Any, index: int) -> GapCategory:
    where = f"categories[{index}]"
    if not isinstance(entry, dict) or set(entry) != _KEYS:
        raise GapConfigError(f"{where} must have exactly id, reason and alternative")
    ident = entry["id"]
    if not isinstance(ident, str) or not _SLUG.fullmatch(ident):
        raise GapConfigError(f"{where}.id must be a lower-case slug")
    reason = _text(entry["reason"], f"{where}.reason", MAX_REASON)
    alternative = _text(entry["alternative"], f"{where}.alternative", MAX_ALTERNATIVE)
    if reason.strip() == alternative.strip():
        raise GapConfigError(f"{where}: the alternative must differ from the reason")
    return GapCategory(ident, reason, alternative)


def _load_yaml(path: Path) -> Any:
    try:
        return yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError, UnicodeError) as error:
        raise GapConfigError(f"cannot read {path.name}: {type(error).__name__}") from error


def _services(path: Path) -> tuple[str, ...]:
    data = _load_yaml(path)
    entries = data if isinstance(data, list) else [None]  # a non-list is one bad entry
    names = [entry.get("name") if isinstance(entry, dict) else None for entry in entries]
    services = tuple(n for n in names if isinstance(n, str) and n.strip())
    if len(services) != len(names):
        raise GapConfigError("the connectors file must be a list of mappings, each with a `name`")
    return services


def load_gap_policy(path: Path | None = None, *, connectors_path: Path | None = None) -> GapPolicy:
    path = DEFAULT_GAP_CONFIG if path is None else path
    data = _load_yaml(path)
    if not isinstance(data, dict) or set(data) != {"nothing_possible", "categories"}:
        raise GapConfigError("the gap config must be a mapping with only `nothing_possible` and `categories`")
    if not isinstance(data["categories"], list):
        raise GapConfigError("`categories` must be a list")
    lead = _text(data["nothing_possible"], "nothing_possible", MAX_LEAD)
    categories = tuple(_category(entry, i) for i, entry in enumerate(data["categories"]))
    ids = [c.id for c in categories]
    if not categories or len(ids) != len(set(ids)):
        raise GapConfigError("the gap config needs at least one category, with unique ids")
    return GapPolicy(categories, lead, _services(DEFAULT_CONNECTORS if connectors_path is None else connectors_path))


def clean_part(value: Any) -> str | None:
    """The label as shown, or None when unusable: a `str` of at most MAX_PART characters, with every C-category
    character (controls, bidi and zero-width marks, surrogates, private use, unassigned) removed, whitespace runs
    collapsed, a trailing period dropped. No NFKC (it can grow a string): cleaning only shrinks."""
    if not isinstance(value, str) or len(value) > MAX_PART:
        return None
    kept = "".join(ch for ch in value if not unicodedata.category(ch).startswith("C"))
    return " ".join(kept.split()).rstrip(".").strip() or None
