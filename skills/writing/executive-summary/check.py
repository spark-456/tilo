"""Deterministic quality-bar checker for writing/executive-summary.

Pure standard library. Never raises: malformed output always yields at least
one finding (fail closed). See SKILL.md "Quality bar" for the check ids this
module can return.
"""

from __future__ import annotations

import re

_NUMBER_RE = re.compile(r"\d[\d,]*\.?\d*")


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
    all_material_text = " ".join(material_by_id.values())

    findings: list[dict] = []
    if not answer_first.strip():
        findings.append(
            {"check": "answer-first-missing", "detail": "answer_first must lead with the answer, not be empty"}
        )

    answer_first_numbers = _NUMBER_RE.findall(answer_first)
    if any(n not in all_material_text for n in answer_first_numbers):
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
        numbers = _NUMBER_RE.findall(claim["text"])
        if any(n not in source_text for n in numbers):
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
