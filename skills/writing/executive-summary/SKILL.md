# Executive summary

Domain expert review: tracked as GitHub issue spark-456/tilo#6 (no domain expert has signed off yet; this v0 draft is Tilo build, drafted by Claude Code).

## When to use

Use this skill to write a short, sourced executive summary that answers a specific question from already-gathered material, within a strict word budget. Use it after research is done, not to do the research itself.

## Steps

1. Read `inputs.question`, `inputs.material` and `inputs.max_words`.
2. Write `answer_first`: the direct answer to the question, in plain language, before any supporting detail.
3. Add supporting `claims`, each one a single sourced statement with a `source_id` from `inputs.material`. Never state a claim with no source.
4. Keep every number exactly as written in its cited source passage; do not recompute, round or estimate a new figure.
5. Count words across `answer_first` and every claim's text; stay at or under `inputs.max_words`. Cut supporting detail before cutting the answer.

## Quality bar

- `answer-first-missing`: answer_first must be non-empty and must lead with the answer.
- `claim-missing-source`: every claim must cite a source id present in the supplied material.
- `number-not-traceable`: every number in a claim must appear, as a whole number (not a substring of a larger number), in the material passage it cites; every number in `answer_first` must appear, as a whole number, somewhere in the supplied material.
- `word-count-over-limit`: the total word count across answer_first and every claim must not exceed max_words.
- `output-malformed`: the output must be an object with a string answer_first and a claims array; malformed shapes fail closed.

## Checklist

- [ ] The answer comes first, not buried under context.
- [ ] Every claim has a source id from the supplied material.
- [ ] Every number matches its cited source exactly.
- [ ] Total word count is at or under the requested limit.
- [ ] Nothing is asserted that the material does not actually say.

## Pitfalls

- Opening with background or caveats instead of the answer.
- Adding a plausible-sounding claim with no real source to pad the summary.
- Putting a made-up or rounded figure in `answer_first` itself, reasoning that only the claims need sourcing.
- Recomputing or rounding a figure from the material "for clarity", which breaks the exact source trace.
- Going over the word limit by counting only the claims and forgetting answer_first.
