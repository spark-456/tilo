# writing/deck-writing checker (FR-AGT-04).
from skills._lib import guard

_TITLE_MAX = 60


@guard.fail_closed
def check(inputs: dict, output: dict) -> list[dict]:
    tokens, mat_ids = guard.gather_material(inputs)
    max_slides, slides = inputs.get("max_slides"), output.get("slides")
    if not isinstance(slides, list):
        return [guard.finding("slide-count-exceeded", "output.slides must be a list")]

    too_many = isinstance(max_slides, int) and len(slides) > max_slides
    findings = [guard.finding("slide-count-exceeded", f"{len(slides)} > max_slides {max_slides}")] if too_many else []

    for slide in slides:
        if not isinstance(slide, dict):
            continue
        title = slide.get("title")
        too_long = isinstance(title, str) and len(title) > _TITLE_MAX
        findings += [guard.finding("title-too-long", f"{title!r} exceeds {_TITLE_MAX} chars")] if too_long else []
        refs_field = slide.get("source_refs")
        refs = {r for r in refs_field if isinstance(r, str)} if isinstance(refs_field, list) else set()
        bullets = slide.get("bullets") if isinstance(slide.get("bullets"), list) else []
        parts = [title if isinstance(title, str) else ""]
        for b in bullets:
            text = b if isinstance(b, str) else (b.get("text") if isinstance(b, dict) else "")
            parts.append(text if isinstance(text, str) else "")
        refs |= {b["source_id"] for b in bullets if isinstance(b, dict) and isinstance(b.get("source_id"), str)}
        charts = slide.get("charts")
        if not isinstance(charts, list):
            charts = [slide["chart_ref"]] if isinstance(slide.get("chart_ref"), dict) else []
        for c in charts:
            if isinstance(c, dict):
                refs |= {r for r in (c.get("source_id"), c.get("material_id")) if isinstance(r, str)}
        bad_charts = [c for c in charts if not isinstance(c, dict)]
        findings += [guard.finding("source-ref-unknown", "chart must be a data reference") for _ in bad_charts]

        invented = guard.number_tokens(" ".join(parts)) - tokens
        findings += [guard.finding("number-not-in-material", f"invented: {sorted(invented)}")] if invented else []
        unknown = refs - mat_ids
        findings += [guard.finding("source-ref-unknown", f"unknown ref(s): {sorted(unknown)}")] if unknown else []
    return findings
