"""Deterministic quality-bar checker for writing/deck-writing.

Pure standard library. Never raises: malformed output always yields at least
one finding (fail closed). See SKILL.md "Quality bar" for the check ids this
module can return.
"""

from __future__ import annotations

import re

_NUMBER_RE = re.compile(r"\d[\d,]*\.?\d*")
_DRAWING_KEYS = {"svg", "image", "image_base64", "pixels", "png", "path_data", "points"}


def check(inputs: dict, output: dict) -> list[dict]:
    if not isinstance(output, dict):
        return [{"check": "output-malformed", "detail": "output must be an object"}]
    slides = output.get("slides")
    if not isinstance(slides, list):
        return [{"check": "output-malformed", "detail": "output.slides must be an array"}]

    inputs = inputs if isinstance(inputs, dict) else {}
    material = inputs.get("material") if isinstance(inputs.get("material"), list) else []
    max_slides = inputs.get("max_slides")
    material_by_id = {m.get("source_id"): m.get("text", "") for m in material if isinstance(m, dict)}

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

        bullets = slide.get("bullets")
        if not isinstance(bullets, list):
            findings.append({"check": "output-malformed", "detail": f"slides[{i}].bullets must be an array"})
            bullets = []
        for j, bullet in enumerate(bullets):
            if not isinstance(bullet, dict) or not isinstance(bullet.get("text"), str):
                findings.append({"check": "output-malformed", "detail": f"slides[{i}].bullets[{j}] malformed"})
                continue
            text = bullet["text"]
            numbers = _NUMBER_RE.findall(text)
            if numbers:
                source_id = bullet.get("source_id")
                # source_id could be any JSON type (e.g. a list), which is
                # unhashable and would raise on a dict lookup or `in` a dict.
                source_text = material_by_id.get(source_id) if isinstance(source_id, str) else None
                if (
                    not isinstance(source_id, str)
                    or source_id not in material_by_id
                    or source_text is None
                    or not all(n in source_text for n in numbers)
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
    return findings
