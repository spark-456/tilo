# Executive summary

Domain expert review: tracked as GitHub issue spark-456/tilo#6 (no domain expert has signed off yet; this v0 draft is Tilo build, drafted by Claude Code).

## When to use

Use this skill to write a short, sourced answer to a question from supplied material, leading with the answer rather than burying it.

## Steps

1. Read `inputs.question`, `inputs.material` (source_id, text) and `inputs.max_words`.
2. Write `answer_first` as the direct answer, in plain language, before any supporting detail.
3. Every claim in `claims` must name the `source_id` of the material it came from; never cite a material id that was not supplied.
4. Every number anywhere in the summary — a figure, a percentage, a date — must already appear as a number in the material. Never invent, round, or approximate a number for effect.
5. Keep the whole summary within `max_words`.

## Quality bar

- `word-limit-exceeded`: the summary must stay within `max_words`.
- `number-not-in-material`: every number in the summary must be a number token of the material.
- `source-ref-unknown`: every claim's source_id must name a supplied material id.

## Checklist

- [ ] The answer comes first, before supporting detail.
- [ ] Word count is within the requested limit.
- [ ] Every number in the summary traces back to the material, matched as a whole number, not a substring.
- [ ] Every claim's source_id names a real material id.

## Pitfalls

- Burying the answer under background instead of leading with it.
- Rounding a number "for readability" (1500 becomes "about 1.5k") — the whole-token number check will not recognise it as the same figure.
- Writing a claim with no source, or guessing at a plausible-looking material id.
- Padding past the word limit "just this once" because the material seemed to deserve more space.
