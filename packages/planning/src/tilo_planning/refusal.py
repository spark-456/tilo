"""Refusal of out-of-policy tasks (FR-INT-12, PRD 7.1, 16, BQ-203). The Director only names a category of
`config/out_of_policy.yaml`; the text a person reads (the reason and the nearest task Tilo can do) comes from
that file alone, so no model-written or task-quoting text reaches a person. A bad file fails closed at load."""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

DEFAULT_REFUSAL_CONFIG = Path(__file__).resolve().parents[4] / "config" / "out_of_policy.yaml"
MAX_TEXT = 400
_SLUG = re.compile(r"[a-z][a-z0-9_]{0,63}")  # common.schema.json slug
_KEYS = {"id", "reason", "alternative"}


class RefusalConfigError(Exception):
    """The refusal config is missing or invalid; nothing is refused or allowed on a guess."""


@dataclass(frozen=True)
class RefusalCategory:
    id: str
    reason: str
    alternative: str


@dataclass(frozen=True)
class RefusalPolicy:
    categories: Sequence[RefusalCategory]

    def get(self, category_id: str) -> RefusalCategory | None:
        return next((c for c in self.categories if c.id == category_id), None)


class TaskRefused(Exception):  # noqa: N818 (named by the ticket's interface)
    """The task is out of policy. Holds only configured text; `str(exc)` never holds task or model text."""

    def __init__(self, category: str, reason: str, alternative: str) -> None:
        super().__init__(f"task refused: {category}")
        self.category, self.reason, self.alternative = category, reason, alternative


def _text(value: Any, where: str) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > MAX_TEXT:
        raise RefusalConfigError(f"{where} must be text of 1 to {MAX_TEXT} characters")
    return value


def _category(entry: Any, index: int) -> RefusalCategory:
    where = f"categories[{index}]"
    if not isinstance(entry, dict) or set(entry) != _KEYS:
        raise RefusalConfigError(f"{where} must have exactly id, reason and alternative")
    ident = entry["id"]
    if not isinstance(ident, str) or not _SLUG.fullmatch(ident):
        raise RefusalConfigError(f"{where}.id must be a lower-case slug")
    reason, alternative = _text(entry["reason"], f"{where}.reason"), _text(entry["alternative"], f"{where}.alternative")
    if reason.strip() == alternative.strip():
        raise RefusalConfigError(f"{where}: the alternative must differ from the reason")
    return RefusalCategory(ident, reason, alternative)


def load_refusal_policy(path: Path | None = None) -> RefusalPolicy:
    path = DEFAULT_REFUSAL_CONFIG if path is None else path
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError, UnicodeError) as error:
        raise RefusalConfigError(f"cannot read {path.name}: {type(error).__name__}") from error
    if not isinstance(data, dict) or set(data) != {"categories"} or not isinstance(data["categories"], list):
        raise RefusalConfigError("the refusal config must be a mapping with only a `categories` list")
    categories = tuple(_category(entry, i) for i, entry in enumerate(data["categories"]))
    ids = [c.id for c in categories]
    if not categories or len(ids) != len(set(ids)):
        raise RefusalConfigError("the refusal config needs at least one category, with unique ids")
    return RefusalPolicy(categories)
