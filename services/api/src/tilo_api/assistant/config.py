"""`config/assistant.yaml`, loaded strictly (API_PPL_11b.md section 2): an unknown or missing key, a wrong type, an
out-of-range number or a broken rule refuses the whole file. Errors name the key path, never a value (a value may
be anything a file author typed). The file is read on every call, like `providers_config`.
"""

from __future__ import annotations

import hashlib
import json
import re
import string
import unicodedata
from collections.abc import Mapping
from dataclasses import dataclass
from functools import cache
from pathlib import Path
from types import MappingProxyType
from typing import Any

import yaml
from tilo_policy.schemas import CONTRACTS, conforms

DEFAULT_PATH = Path(__file__).resolve().parents[5] / "config" / "assistant.yaml"
GROUPS = ("attention", "overdue", "soon", "rest")  # the lanes of plate `rows` (PE-28); parked lanes stay out
_REASON_PATH = ("$defs", "reason")
_ROW_KIND_PATH = ("$defs", "row_ref", "properties", "kind")
_WORD = re.compile(r"[a-z0-9]{1,40}")
_PHRASE = re.compile(r"[a-z0-9]{1,40}(?: [a-z0-9]{1,40}){0,5}")
_SEGMENT = re.compile(r"[A-Za-z0-9._~%-]{1,64}")
_INTENT_ID = re.compile(r"[a-z_]{1,32}")
_STRIPPED = frozenset({"Cc", "Cf", "Zl", "Zp"})
_MAX_TEXT = 400
WORD_LISTS = (
    "fillers",
    "nav_verbs",
    "nav_skip",
    "context",
    "context_nouns",
    "title_skip",
    "question_stop",
    "self_possessives",
    "third_person",
)
DECLINE_KEYS = ("unknown", "other_person", "no_selection", "dropped", "rules_only", "budget", "flagged", "failed")
ROW_KEYS = ("reasons", "groups", "kinds", "has_due", "within_hours")


class AssistantConfigError(Exception):
    """The message names the key path, never a value."""


@dataclass(frozen=True)
class FactRows:
    reasons: tuple[str, ...] | None
    groups: tuple[str, ...] | None
    kinds: tuple[str, ...] | None
    has_due: bool | None
    within_hours: int | None


@dataclass(frozen=True)
class FactIntent:
    id: str
    describe: str
    when: tuple[frozenset[str], ...]
    rows: FactRows
    header: str | None
    empty: str
    narrow: bool


@dataclass(frozen=True)
class NavRoute:
    route: str
    describe: str
    phrases: tuple[str, ...]
    with_context: str | None


@dataclass(frozen=True)
class AssistantConfig:
    question_max_chars: int
    words: Mapping[str, frozenset[str]]
    facts: tuple[FactIntent, ...]
    navigate: tuple[NavRoute, ...]
    screens: Mapping[str, str]
    answer: Mapping[str, Any]
    declines: Mapping[str, str]
    model: Mapping[str, Any]
    user_day_credits: float
    cache_per_user_entries: int
    cache_ttl_hours: int
    fingerprint: str


@cache
def _enum(file: str, *path: str) -> tuple[str, ...]:
    node: Any = json.loads((CONTRACTS / file).read_text(encoding="utf-8"))
    for key in path:
        node = node[key]
    return tuple(node["enum"])


def _fail(path: str, why: str) -> AssistantConfigError:
    return AssistantConfigError(f"{path}: {why}")


def _mapping(path: str, node: Any, required: tuple[str, ...], optional: tuple[str, ...] = ()) -> dict[str, Any]:
    if type(node) is not dict or any(type(k) is not str for k in node):
        raise _fail(path, "must be a mapping")
    if not set(required) <= set(node) or not set(node) <= set(required) | set(optional):
        raise _fail(path, "has an unknown or a missing key")
    return node


def _list(path: str, node: Any, *, least: int = 0, most: int = 500) -> list[Any]:
    if type(node) is not list or not least <= len(node) <= most:
        raise _fail(path, f"must be a list of {least} to {most} items")
    return node


def _int(path: str, node: Any, low: int, high: int) -> int:
    if type(node) is not int or not low <= node <= high:
        raise _fail(path, f"must be an integer from {low} to {high}")
    return node


def _text(path: str, node: Any, holes: frozenset[str] = frozenset()) -> str:
    """A one-line text of 1 to 400 characters whose only $placeholders are `holes`."""
    if type(node) is not str or not 1 <= len(node) <= _MAX_TEXT:
        raise _fail(path, f"must be a text of 1 to {_MAX_TEXT} characters")
    if any(unicodedata.category(c) in _STRIPPED for c in node):
        raise _fail(path, "holds a control or format character")
    names: set[str] = set()
    for match in string.Template.pattern.finditer(node):
        if match.group("invalid") is not None:
            raise _fail(path, "holds a broken placeholder")
        name = match.group("named") or match.group("braced")
        if name is not None:
            names.add(name)
    if not names <= holes:
        raise _fail(path, "holds a placeholder it may not use")
    return node


def _word_list(path: str, node: Any) -> frozenset[str]:
    items = _list(path, node)
    if any(type(w) is not str or not _WORD.fullmatch(w) for w in items):
        raise _fail(path, "must hold lower-case words only")
    return frozenset(items)


def _choice(path: str, node: Any, allowed: tuple[str, ...]) -> str:
    if type(node) is not str or node not in allowed:
        raise _fail(path, "is not one of the allowed values")
    return node


def _subset(path: str, node: Any, allowed: tuple[str, ...]) -> tuple[str, ...]:
    items = _list(path, node, least=1, most=len(allowed))
    chosen = tuple(_choice(f"{path}.{i}", v, allowed) for i, v in enumerate(items))
    if len(set(chosen)) != len(chosen):
        raise _fail(path, "names a value twice")
    return chosen


def _rows(path: str, node: Any) -> FactRows:
    rows = _mapping(path, node, (), ROW_KEYS)
    reasons = (
        _subset(f"{path}.reasons", rows["reasons"], _enum("plate.schema.json", *_REASON_PATH))
        if "reasons" in rows
        else None
    )
    groups = _subset(f"{path}.groups", rows["groups"], GROUPS) if "groups" in rows else None
    kinds = (
        _subset(f"{path}.kinds", rows["kinds"], _enum("plate.schema.json", *_ROW_KIND_PATH))
        if "kinds" in rows
        else None
    )
    has_due = rows.get("has_due")
    if "has_due" in rows and type(has_due) is not bool:
        raise _fail(f"{path}.has_due", "must be true or false")
    hours = _int(f"{path}.within_hours", rows["within_hours"], 1, 168) if "within_hours" in rows else None
    return FactRows(reasons, groups, kinds, has_due, hours)


def _facts(node: Any) -> tuple[FactIntent, ...]:
    out: list[FactIntent] = []
    for i, raw in enumerate(_list("facts", node, least=1, most=60)):
        path = f"facts.{i}"
        item = _mapping(path, raw, ("id", "describe", "when", "rows", "header", "empty"), ("narrow",))
        iid = item["id"]
        if type(iid) is not str or not _INTENT_ID.fullmatch(iid) or any(f.id == iid for f in out):
            raise _fail(f"{path}.id", "must be a unique lower-case id of at most 32 letters")
        groups = [
            _word_list(f"{path}.when.{n}", g)
            for n, g in enumerate(_list(f"{path}.when", item["when"], least=1, most=8))
        ]
        if not all(groups):
            raise _fail(f"{path}.when", "has an empty group")
        rows = _rows(f"{path}.rows", item["rows"])
        header = None if item["header"] is None else _text(f"{path}.header", item["header"])
        if header is None and (rows.groups is None or set(rows.groups) != set(GROUPS)):
            raise _fail(f"{path}.header", "may be null only for the intent over all four groups")
        narrow = item.get("narrow", False)
        if type(narrow) is not bool:
            raise _fail(f"{path}.narrow", "must be true or false")
        out.append(
            FactIntent(
                iid,
                _text(f"{path}.describe", item["describe"]),
                tuple(groups),
                rows,
                header,
                _text(f"{path}.empty", item["empty"]),
                narrow,
            )
        )
    return tuple(out)


def _navigate(node: Any) -> tuple[NavRoute, ...]:
    from tilo_api.assistant.navigation import ROUTE_TARGETS  # noqa: PLC0415  (BQ-PPL11B-20: one reader of the contract)

    routes = tuple(r for r in ROUTE_TARGETS if r not in ("world", "meeting"))  # these two always need a target
    kinds = _enum("common.schema.json", "$defs", "record_ref", "properties", "kind")
    out: list[NavRoute] = []
    seen: set[str] = set()
    for i, raw in enumerate(_list("navigate", node, least=1, most=40)):
        path = f"navigate.{i}"
        item = _mapping(path, raw, ("route", "describe", "phrases"), ("with_context",))
        route = _choice(f"{path}.route", item["route"], routes)
        if any(r.route == route for r in out):
            raise _fail(f"{path}.route", "is named twice")
        phrases = tuple(_list(f"{path}.phrases", item["phrases"], least=1, most=60))
        for n, phrase in enumerate(phrases):
            if type(phrase) is not str or not _PHRASE.fullmatch(phrase) or phrase in seen:
                raise _fail(f"{path}.phrases.{n}", "must be words joined by one space, in one route only")
            seen.add(phrase)
        with_context = item.get("with_context")
        if with_context is not None:
            _choice(f"{path}.with_context", with_context, kinds)
        out.append(NavRoute(route, _text(f"{path}.describe", item["describe"]), phrases, with_context))
    return tuple(out)


def _screens(node: Any) -> dict[str, str]:
    from tilo_api.assistant.navigation import ROUTE_TARGETS  # noqa: PLC0415

    if type(node) is not dict or not 1 <= len(node) <= 40:
        raise _fail("screens", "must be a mapping of 1 to 40 entries")
    for key, route in node.items():
        if type(key) is not str or not _SEGMENT.fullmatch(key):
            raise _fail("screens", "has a key that is no path segment")
        _choice(f"screens.{key}", route, tuple(ROUTE_TARGETS))
    return dict(node)


def _answer(node: Any) -> Mapping[str, Any]:
    keys = (
        "max_lines",
        "more",
        "due_suffix",
        "flagged_suffix",
        "kind_labels",
        "untitled",
        "opening",
        "target_screens",
        "group_headers",
        "lines",
    )
    a = _mapping("answer", node, keys)
    reasons = _enum("plate.schema.json", *_REASON_PATH)
    labels = _mapping("answer.kind_labels", a["kind_labels"], (), _enum("plate.schema.json", *_ROW_KIND_PATH))
    lines = _mapping("answer.lines", a["lines"], reasons)
    shown = _mapping("answer.target_screens", a["target_screens"], ("world", "meeting"))
    headers = _mapping("answer.group_headers", a["group_headers"], GROUPS)
    return MappingProxyType(
        {
            "max_lines": _int("answer.max_lines", a["max_lines"], 1, 20),
            "more": _text("answer.more", a["more"]),
            "due_suffix": _text("answer.due_suffix", a["due_suffix"], frozenset({"due"})),
            "flagged_suffix": _text("answer.flagged_suffix", a["flagged_suffix"]),
            "kind_labels": MappingProxyType({k: _text(f"answer.kind_labels.{k}", v) for k, v in labels.items()}),
            "untitled": _text("answer.untitled", a["untitled"]),
            "opening": _text("answer.opening", a["opening"], frozenset({"screen"})),
            "target_screens": MappingProxyType({k: _text(f"answer.target_screens.{k}", v) for k, v in shown.items()}),
            "group_headers": MappingProxyType({k: _text(f"answer.group_headers.{k}", v) for k, v in headers.items()}),
            "lines": MappingProxyType(
                {k: _text(f"answer.lines.{k}", v, frozenset({"label", "time"})) for k, v in lines.items()}
            ),
        }
    )


def load_assistant_config(path: str | Path | None = None) -> AssistantConfig:
    """Strict. Read on every call. Raises AssistantConfigError, naming the key path and no value."""
    try:
        raw = yaml.safe_load(Path(path or DEFAULT_PATH).read_text(encoding="utf-8"))
    except (OSError, UnicodeError, yaml.YAMLError) as exc:
        raise AssistantConfigError(f"assistant.yaml: unreadable ({type(exc).__name__})") from None
    top = _mapping(
        "assistant.yaml",
        raw,
        (
            "version",
            "question",
            "words",
            "facts",
            "navigate",
            "screens",
            "answer",
            "declines",
            "model",
            "cost",
            "cache",
        ),
    )
    if type(top["version"]) is not int or top["version"] != 1:
        raise _fail("version", "must be 1")
    question = _mapping("question", top["question"], ("max_chars",))
    words = _mapping("words", top["words"], WORD_LISTS)
    declines = _mapping("declines", top["declines"], DECLINE_KEYS)
    model = _mapping("model", top["model"], ("role", "menu_rows", "max_output_chars"))
    cost = _mapping("cost", top["cost"], ("user_day_credits",))
    cache = _mapping("cache", top["cache"], ("per_user_entries", "ttl_hours"))
    credits = cost["user_day_credits"]
    if type(credits) not in (int, float) or not 0 < credits <= 50 or credits != credits:
        raise _fail("cost.user_day_credits", "must be above 0 and at most 50")
    if type(model["role"]) is not str or not conforms("common.schema.json#/$defs/slug", model["role"]):
        raise _fail("model.role", "must be a role name")
    return AssistantConfig(
        question_max_chars=_int("question.max_chars", question["max_chars"], 1, 2000),
        words=MappingProxyType({name: _word_list(f"words.{name}", words[name]) for name in WORD_LISTS}),
        facts=_facts(top["facts"]),
        navigate=_navigate(top["navigate"]),
        screens=MappingProxyType(_screens(top["screens"])),
        answer=_answer(top["answer"]),
        declines=MappingProxyType({k: _text(f"declines.{k}", v) for k, v in declines.items()}),
        model=MappingProxyType(
            {
                "role": model["role"],
                "menu_rows": _int("model.menu_rows", model["menu_rows"], 1, 40),
                "max_output_chars": _int("model.max_output_chars", model["max_output_chars"], 100, 4000),
            }
        ),
        user_day_credits=float(credits) if type(credits) is float else credits,
        cache_per_user_entries=_int("cache.per_user_entries", cache["per_user_entries"], 1, 1000),
        cache_ttl_hours=_int("cache.ttl_hours", cache["ttl_hours"], 1, 168),
        fingerprint=hashlib.sha256(json.dumps(top, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest(),
    )
