"""COST-FAST-1: the Quick classifier (services/api/tests/API_COST_FAST_1.md). Deterministic, rules first, no model for
a text a rule reads, zero cost. It only SUGGESTS: the person's chosen mode decides, and a model verdict (the fallback
for a text no rule reads) is vetted here to a closed shape and can never override a rules verdict. Word lists are
`config/quick.yaml`; nothing here names a model, a person, a record or a scenario."""

from __future__ import annotations

import json
import re
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

import yaml

from tilo_api.assistant.words import MAX_KEY, question_key

_CONFIG = Path(__file__).resolve().parents[4] / "config" / "quick.yaml"
REASONS = frozenset(
    {"attachments", "side_effect", "deliverable", "needs_tools", "multi_step", "too_long", "scenario", "unclear"}
)
_TOKEN = re.compile(r"[a-z0-9]+(?:'[a-z]+)?")
_RUN = re.compile(r"[.?!;,:]{2,}")
_SENTENCE = re.compile(r"[.?!;]+(?:\s+|$)")
_MAX_VERDICT_CHARS = 400


class QuickConfigError(ValueError):
    """`config/quick.yaml` is unusable. Names a key, never a value."""


@dataclass(frozen=True)
class QuickRules:
    role: str
    budget: float
    answer_max_chars: int
    answer_max_output_tokens: int
    classifier_max_output_tokens: int
    thinking_level: str
    max_words: int
    openers: frozenset[str]
    phrases: tuple[tuple[str, ...], ...]
    fillers: frozenset[str]
    sets: dict[str, frozenset[str]]


def load_quick_rules(path: Path | None = None) -> QuickRules:
    try:
        doc = yaml.safe_load((path or _CONFIG).read_text(encoding="utf-8"))
        w = doc["words"]

        def words(key: str) -> frozenset[str]:
            if not isinstance(w[key], list) or not all(type(x) is str for x in w[key]):
                raise QuickConfigError(f"words.{key} must be a list of strings")
            return frozenset(w[key])

        budget = doc["budget_credits"]
        if type(budget) not in (int, float) or not 0 < budget <= 0.5:
            raise QuickConfigError("budget_credits must be above 0 and at most 0.5")
        names = ("deictic", "clause_breaks", "sequence", "recurrence", "side_effect_verbs", "production_verbs")
        return QuickRules(
            role=str(doc["role"]),
            budget=float(budget),
            answer_max_chars=int(doc["answer_max_chars"]),
            answer_max_output_tokens=int(doc["answer_max_output_tokens"]),
            classifier_max_output_tokens=int(doc["classifier_max_output_tokens"]),
            thinking_level=str(doc["thinking_level"]),
            max_words=int(doc["max_words"]),
            openers=words("simple_openers"),
            phrases=tuple(tuple(p) for p in w["simple_phrases"]),
            fillers=words("fillers"),
            sets={n: words(n) for n in (*names, "deliverable_nouns", "tool_words")},
        )
    except QuickConfigError:
        raise
    except (OSError, yaml.YAMLError, KeyError, TypeError, ValueError) as exc:
        raise QuickConfigError(f"quick.yaml is unusable ({type(exc).__name__})") from exc


def clean(text: str) -> str:
    """Control, format (bidi, zero-width) and unassigned characters out, any run of white space one space."""
    kept = (" " if ch.isspace() else ch for ch in text if ch.isspace() or unicodedata.category(ch)[0] != "C")
    return " ".join("".join(kept).split())


@dataclass(frozen=True)
class Verdict:
    kind: Literal["simple", "work", "model"]  # "model": no rule reads this text
    reason: str | None = None


def _stems(text: str) -> list[str]:
    return [t.split("'", 1)[0] for t in _TOKEN.findall(text)]


def _heads(clause: list[str], rules: QuickRules) -> set[str]:
    """The words a command starts with: the first word (fillers dropped) and the word after an early "to"."""
    while clause and clause[0] in rules.fillers:
        clause = clause[1:]
    return set(clause[:1]) | {clause[i + 1] for i, w in enumerate(clause[:4]) if w == "to" and i + 1 < len(clause)}


def classify(rules: QuickRules, text: str, *, max_chars: int, has_files: bool, scenario: bool) -> Verdict:
    """`text` is the raw question: its length is judged before anything is normalised (no NFKC amplification)."""
    if has_files:
        return Verdict("work", "attachments")  # never read: Quick processes nothing
    if scenario:
        return Verdict("work", "scenario")
    if len(text) > max_chars:
        return Verdict("work", "too_long")
    cleaned = clean(text)
    key = _RUN.sub(lambda m: m.group()[0], question_key(cleaned))  # a run of marks is one: linear splitting below
    cut = len(unicodedata.normalize("NFKC", cleaned)) > MAX_KEY  # the key lost its tail: later words were never read
    foreign = any(
        c.isalpha() and not c.isascii() and not unicodedata.name(c, "").startswith("LATIN") for c in key
    )  # no stems: blind
    breaks = "|".join(sorted(rules.sets["clause_breaks"]))
    clauses = [_stems(c) for c in re.split(rf"[,;:.!?]+|\s(?:{breaks})\s", key) if c.strip()]
    stems = [s for c in clauses for s in c]
    if not stems:
        return Verdict("model")
    first = clauses[0]
    while first and first[0] in rules.fillers:
        first = first[1:]
    led = bool(first) and (first[0] in rules.openers or any(tuple(first[: len(p)]) == p for p in rules.phrases))
    s = rules.sets
    heads = set().union(*(_heads(c, rules) for c in (clauses[1:] if led else clauses)))
    if (heads & s["side_effect_verbs"]) or (not led and s["recurrence"] & set(stems)):
        return Verdict("work", "side_effect")
    if heads & s["production_verbs"] and s["deliverable_nouns"] & set(stems):
        return Verdict("work", "deliverable")
    if s["tool_words"] & set(stems):
        return Verdict("work", "needs_tools")
    if sum(1 for w in _stems(key) if w in s["sequence"]) >= 2:  # "then" is a clause break: count on the whole text
        return Verdict("work", "multi_step")
    sentences = [x for x in _SENTENCE.split(key) if x.strip()]
    if led and not (cut or foreign) and len(sentences) == 1 and len(stems) <= rules.max_words:
        if not s["deictic"] & set(stems):
            return Verdict("simple")
    return Verdict("model")


def _pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    found = dict(pairs)
    if len(found) != len(pairs):
        raise ValueError("duplicate key")
    return found


def _no_constant(name: str) -> Any:
    raise ValueError("not JSON")


def parse_verdict(text: object) -> Verdict | None:
    """The model fallback's reply: exactly {"kind": "simple"} or {"kind": "work", "reason": <a reason>}, exact keys and
    JSON types, no duplicate key, no NaN, nothing before or after. Anything else is no verdict (None)."""
    if type(text) is not str or len(text) > _MAX_VERDICT_CHARS:
        return None
    try:
        doc = json.loads(text, object_pairs_hook=_pairs, parse_constant=_no_constant)
    except (ValueError, RecursionError):
        return None
    if type(doc) is not dict:
        return None
    if doc == {"kind": "simple"} and type(doc["kind"]) is str:
        return Verdict("simple")
    if set(doc) == {"kind", "reason"} and doc["kind"] == "work" and type(doc["reason"]) is str:
        return Verdict("work", doc["reason"]) if doc["reason"] in REASONS else None
    return None
