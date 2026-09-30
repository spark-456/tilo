"""Keyterms for streaming speech-to-text: words it would otherwise mishear (names, agenda titles, project terms)."""

from __future__ import annotations

import re
from collections import Counter
from typing import Any

MAX_KEYTERMS = 50
MAX_TERM_CHARS = 40
MIN_TERM_COUNT = 2  # a document term must appear at least this often to count as a project term
_WORD = re.compile(r"[A-Za-z][A-Za-z0-9-]{3,29}")
_COMMON = set(
    "that this with from have will would could should their there about which these those where when what than then "
    "they them were been being also into only over such very more most much many some each other your yours ours "
    "just like make made need needs want wants going does done doing work works using used uses ships".split()
)


def project_terms(kb: Any, limit: int = MAX_KEYTERMS) -> list[str]:
    """The most frequent distinctive words in the project documents, most frequent first."""
    if kb is None:
        return []
    counts: Counter[str] = Counter()
    spelling: dict[str, str] = {}
    for source in kb.sources:
        for word in _WORD.findall(source.text):
            key = word.lower()
            if key in _COMMON:
                continue
            counts[key] += 1
            spelling.setdefault(key, word)
    return [spelling[k] for k, n in counts.most_common(limit) if n >= MIN_TERM_COUNT]


def build_keyterms(
    bot_name: str, names: list[str], titles: list[str], kb: Any = None, limit: int = MAX_KEYTERMS
) -> list[str]:
    """Bot name, then participants, agenda titles and finally project terms; unique, at most `limit`."""
    out: list[str] = []
    seen: set[str] = set()
    for term in [bot_name, *names, *titles, *project_terms(kb, limit)]:
        term = (term or "").strip()
        if term and len(term) <= MAX_TERM_CHARS and term.lower() not in seen:
            seen.add(term.lower())
            out.append(term)
    return out[:limit]
