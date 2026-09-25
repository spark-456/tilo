"""Deterministic quality-bar checker for writing/deck-writing.

Pure standard library. Never raises: malformed output always yields at least
one finding (fail closed). See SKILL.md "Quality bar" for the check ids this
module can return.
"""

from __future__ import annotations

import re

_NUMBER_RE = re.compile(r"\d[\d,]*\.?\d*")
_DRAWING_KEYS = {"svg", "image", "image_base64", "pixels", "png", "path_data", "points"}


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


def check(inputs: dict, output: dict) -> list[dict]:
    if not isinstance(output, dict):
        return [{"check": "output-malformed", "detail": "output must be an object"}]
    slides = output.get("slides")
    if not isinstance(slides, list):
        return [{"check": "output-malformed", "detail": "output.slides must be an array"}]

    inputs = inputs if isinstance(inputs, dict) else {}
    material = inputs.get("material") if isinstance(inputs.get("material"), list) else []
    max_slides = inputs.get("max_slides")
    # source_id and text could each be any JSON type; only a string source_id
    # is usable as a lookup key and only string text is usable as source text
    # (a non-string text, e.g. a NaN float, is not iterable for `in`/regex use).
    material_by_id: dict[str, str] = {
        m["source_id"]: m["text"]
        for m in material
        if isinstance(m, dict) and isinstance(m.get("source_id"), str) and isinstance(m.get("text"), str)
    }
    all_material_numbers = _numbers(" ".join(material_by_id.values()))

    findings: list[dict] = []
    if isinstance(max_slides, int) and not isinstance(max_slides, bool) and len(slides) > max_slides:
        findings.append(
            {
                "check": "slide-count-within-limit",
                "detail": f"{len(slides)} slides exceeds the requested limit of {max_slides}",
            }
        )

    for i, slide in enumerate(slides):
        if not isinstance(slide, dict):
            findings.append({"check": "output-malformed", "detail": f"slides[{i}] is not an object"})
            continue
        title = slide.get("title")
        if not isinstance(title, str) or len(title) > 60:
            findings.append({"check": "title-too-long", "detail": f"slides[{i}] title exceeds 60 characters"})
        elif not _numbers(title) <= all_material_numbers:
            # A title carries no source_id of its own (the schema does not
            # give one), so its numbers are checked against the whole
            # material corpus, the same way executive-summary checks
            # answer_first.
            findings.append(
                {
                    "check": "number-has-source",
                    "detail": f"slides[{i}] title has a number not traceable to any supplied material",
                }
            )

        bullets = slide.get("bullets")
        if not isinstance(bullets, list):
            findings.append({"check": "output-malformed", "detail": f"slides[{i}].bullets must be an array"})
            bullets = []
        for j, bullet in enumerate(bullets):
            if not isinstance(bullet, dict) or not isinstance(bullet.get("text"), str):
                findings.append({"check": "output-malformed", "detail": f"slides[{i}].bullets[{j}] malformed"})
                continue
            text = bullet["text"]
            bullet_numbers = _numbers(text)
            if bullet_numbers:
                source_id = bullet.get("source_id")
                # source_id could be any JSON type (e.g. a list), which is
                # unhashable and would raise on a dict lookup or `in` a dict.
                source_text = material_by_id.get(source_id) if isinstance(source_id, str) else None
                if (
                    not isinstance(source_id, str)
                    or source_id not in material_by_id
                    or source_text is None
                    or not bullet_numbers <= _numbers(source_text)
                ):
                    findings.append(
                        {
                            "check": "number-has-source",
                            "detail": f"slides[{i}].bullets[{j}] has a number not traceable to its cited source",
                        }
                    )

        chart_ref = slide.get("chart_ref")
        if chart_ref is not None:
            chart_source_id = chart_ref.get("source_id") if isinstance(chart_ref, dict) else None
            if (
                not isinstance(chart_ref, dict)
                or not isinstance(chart_source_id, str)
                or chart_source_id not in material_by_id
            ):
                findings.append(
                    {"check": "chart-not-drawn", "detail": f"slides[{i}].chart_ref must cite a supplied source_id"}
                )
            elif _DRAWING_KEYS & set(chart_ref.keys()):
                findings.append(
                    {
                        "check": "chart-not-drawn",
                        "detail": f"slides[{i}].chart_ref carries drawing data instead of a plain data reference",
                    }
                )
            elif "chart_type" in chart_ref and not isinstance(chart_ref.get("chart_type"), str):
                findings.append(
                    {
                        "check": "output-malformed",
                        "detail": f"slides[{i}].chart_ref.chart_type must be a string when present",
                    }
                )
    return findings
