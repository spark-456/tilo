"""Deterministic quality-bar checker for writing/executive-summary.

Pure standard library. Never raises: malformed output always yields at least
one finding (fail closed). See SKILL.md "Quality bar" for the check ids this
module can return.
"""

from __future__ import annotations

import re

_NUMBER_RE = re.compile(r"\d[\d,]*\.?\d*")


def _normalize_number(token: str) -> str:
    """Strip thousands separators so "1,500" and "1500" compare equal."""
    return token.replace(",", "").strip()


def _numbers(text: str) -> set[str]:
    """Whole, normalised number tokens found in text.

    Used for set-membership comparison, never substring comparison: a raw
    substring test ("n in source_text") would let a fabricated "50" pass
    because it sits inside a genuine "1500" in the source text.
    """
    return {_normalize_number(n) for n in _NUMBER_RE.findall(text)}


def _word_count(text: str) -> int:
    return len(text.split())


def check(inputs: dict, output: dict) -> list[dict]:
    if not isinstance(output, dict):
        return [{"check": "output-malformed", "detail": "output must be an object"}]
    answer_first = output.get("answer_first")
    claims = output.get("claims")
    if not isinstance(answer_first, str) or not isinstance(claims, list):
        return [{"check": "output-malformed", "detail": "output must have a string answer_first and a claims array"}]

    inputs = inputs if isinstance(inputs, dict) else {}
    material = inputs.get("material") if isinstance(inputs.get("material"), list) else []
    max_words = inputs.get("max_words")
    # Only keep entries whose source_id and text are actually strings: a
    # malformed material item (e.g. text as an int) must never be trusted as
    # a source, and must never reach a string operation that could raise.
    material_by_id: dict[str, str] = {
        m["source_id"]: m["text"]
        for m in material
        if isinstance(m, dict) and isinstance(m.get("source_id"), str) and isinstance(m.get("text"), str)
    }
    all_material_numbers = _numbers(" ".join(material_by_id.values()))

    findings: list[dict] = []
    if not answer_first.strip():
        findings.append(
            {"check": "answer-first-missing", "detail": "answer_first must lead with the answer, not be empty"}
        )

    if not _numbers(answer_first) <= all_material_numbers:
        findings.append(
            {
                "check": "number-not-traceable",
                "detail": "answer_first has a number not present in any supplied material",
            }
        )

    total_words = _word_count(answer_first)
    for i, claim in enumerate(claims):
        if (
            not isinstance(claim, dict)
            or not isinstance(claim.get("text"), str)
            or not isinstance(claim.get("source_id"), str)
        ):
            findings.append({"check": "output-malformed", "detail": f"claims[{i}] malformed"})
            continue
        total_words += _word_count(claim["text"])
        source_text = material_by_id.get(claim["source_id"])
        if source_text is None:
            findings.append(
                {"check": "claim-missing-source", "detail": f"claims[{i}] cites unknown source {claim['source_id']!r}"}
            )
            continue
        if not _numbers(claim["text"]) <= _numbers(source_text):
            findings.append(
                {"check": "number-not-traceable", "detail": f"claims[{i}] has a number not present in its cited source"}
            )

    if isinstance(max_words, int) and not isinstance(max_words, bool) and total_words > max_words:
        findings.append(
            {
                "check": "word-count-over-limit",
                "detail": f"{total_words} words exceeds the requested limit of {max_words}",
            }
        )
    return findings
