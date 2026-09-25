# Deck writing

Domain expert review: tracked as GitHub issue spark-456/tilo#6 (no domain expert has signed off yet; this v0 draft is Tilo build, drafted by Claude Code).

## When to use

Use this skill to turn already-verified material (for example a Verifier-checked research brief) into a slide outline: titles and bullets, with any chart left as a reference to the underlying data rather than drawn. Do not use it as a first-draft research tool — the material it works from must already be sourced.

## Steps

1. Read `inputs.material` (an array of sourced passages) and `inputs.max_slides`.
2. Plan no more slides than `inputs.max_slides`. Fewer is fine; never more.
3. Write a short slide title, at most 60 characters.
4. Write bullets from the material. Every bullet that states a number must carry a `source_id` pointing at the passage that contains that exact number — copy the number as written in the source, do not recompute or round it.
5. If a slide needs a chart, never draw one yourself: add a `chart_ref` object naming only the `source_id` (and optionally a `chart_type`) so the render service builds the chart from data. Never embed pixel, SVG or image data.
6. Leave anything the material does not support out of the deck rather than filling gaps.

## Quality bar

- `slide-count-within-limit`: the number of slides must not exceed the requested max_slides.
- `title-too-long`: every slide title must be 60 characters or fewer.
- `number-has-source`: every number in a bullet must appear, as a whole number (not a substring of a larger number), in the material passage its bullet cites; every number in a slide title must appear, as a whole number, somewhere in the supplied material (a title has no source_id of its own, so it is checked against the whole material corpus).
- `chart-not-drawn`: a chart_ref must cite a supplied source and hold only a data reference, never drawing data (PRD 12.4: charts are rendered from data by code, never drawn by a model).
- `output-malformed`: the output must be an object with a slides array of title/bullets objects; malformed shapes fail closed.

## Checklist

- [ ] Slide count is within the requested limit.
- [ ] Every title is 60 characters or fewer.
- [ ] Every numbered bullet cites a source that contains that exact number, and every numbered title is traceable to the material (checked as a whole number, never a substring — "50" must never pass just because it sits inside "1500").
- [ ] Any chart is a data reference only, never a model-drawn image.
- [ ] Nothing on a slide is unsupported by the material.

## Pitfalls

- Rounding or reformatting a number for a cleaner-looking bullet — this breaks the exact-match source trace.
- Drawing a chart as an image or inline SVG "to save a step" instead of leaving it as a data reference for the render service.
- Splitting one idea across too many slides to dodge the slide limit.
- Writing a title that only fits by abbreviating past readability, instead of shortening the underlying claim.
