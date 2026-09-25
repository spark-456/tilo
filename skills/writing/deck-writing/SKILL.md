# Deck writing

Domain expert review: tracked as GitHub issue spark-456/tilo#6 (no domain expert has signed off yet; this v0 draft is Tilo build, drafted by Claude Code).

## When to use

Use this skill to outline slides from verified material, never from memory, with every number and chart traceable to a material id.

## Steps

1. Read `inputs.material` (source_id, text) and `inputs.max_slides`.
2. Produce at most `max_slides` slides; a title is at most 60 characters.
3. Every number in a title or bullet — a figure, a percentage, a date — must already appear as a number in the material. Never invent, round, or approximate a number for effect.
4. Every slide's bullets or `source_refs` must name material ids that were actually supplied.
5. A chart is a data reference to a material id (`source_id`, optionally `chart_type`) — never an image or drawing produced by a model (PRD 12.4). The render layer draws the chart deterministically from the referenced data.

## Quality bar

- `slide-count-exceeded`: the deck must have at most `max_slides` slides.
- `title-too-long`: every title must be at most 60 characters.
- `number-not-in-material`: every number in a title or bullet must be a number token of the material.
- `source-ref-unknown`: every source reference (bullet, slide-level ref, or chart) must name a supplied material id.

## Checklist

- [ ] Slide count is within the requested limit.
- [ ] Every title is 60 characters or fewer.
- [ ] Every number in the deck traces back to the material, matched as a whole number, not a substring.
- [ ] Every source reference and chart names a real material id.

## Pitfalls

- Rounding a number "for readability" (1500 becomes "about 1.5k") — the whole-token number check will not recognise it as the same figure.
- Referencing a chart with data the model made up instead of a material id the render layer can look up.
- Writing a bullet with no source reference when several plausible material ids exist, guessing at one that isn't right.
- Padding a title past 60 characters to fit in extra context.
